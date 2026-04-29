"""Vacuum leak rate estimator — F13.

Automates the standard post-valve-close leak measurement:
    leak_rate = (dP/dt) × V_chamber   [mbar·L/s]

Operator workflow (Mode A — primary):
1. Close isolation valve.
2. Issue `leak_rate_start` ZMQ command (optional duration override).
3. System samples pressure for sample_window_s seconds.
4. Issue `leak_rate_stop` (or wait for auto-finalize).
5. `LeakRateMeasurement` logged to event_logger + optionally appended
   to data/leak_rate_history.json.

Mode B (auto-trigger on pressure signature) is deferred to F13 polish.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_HISTORY_FILENAME = "leak_rate_history.json"


@dataclass
class LeakRateMeasurement:
    """Result of a completed leak rate measurement."""

    started_at: str          # ISO 8601 UTC
    duration_s: float        # actual measurement duration
    initial_pressure_mbar: float
    final_pressure_mbar: float
    dpdt_mbar_per_s: float   # linear regression slope
    chamber_volume_l: float
    leak_rate_mbar_l_per_s: float  # dpdt × volume
    fit_quality_r2: float    # coefficient of determination (0–1)
    samples_n: int


class LeakRateEstimator:
    """Accumulates pressure samples and computes leak rate via linear regression.

    Parameters
    ----------
    chamber_volume_l:
        Physical chamber volume in litres. If 0.0 or negative, finalize()
        raises ValueError (operator must configure before measuring).
    sample_window_s:
        Default measurement duration in seconds. Can be overridden on
        start_measurement().
    data_dir:
        Optional directory for persisting leak_rate_history.json.
    """

    def __init__(
        self,
        chamber_volume_l: float,
        sample_window_s: float = 300.0,
        data_dir: Path | None = None,
    ) -> None:
        self._volume = chamber_volume_l
        self._window_s = sample_window_s
        self._data_dir = data_dir

        self._active = False
        self._t0: float = 0.0
        self._p0: float = 0.0
        self._window_override: float | None = None
        self._samples: list[tuple[float, float]] = []  # (t_rel_s, p_mbar)

    # ------------------------------------------------------------------
    # Measurement lifecycle
    # ------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        return self._active

    def start_measurement(
        self,
        t0: datetime | None = None,
        p0_mbar: float = 0.0,
        *,
        window_s: float | None = None,
    ) -> None:
        """Begin a new leak measurement.

        Parameters
        ----------
        t0:
            Measurement start time (default: now).
        p0_mbar:
            Initial pressure reading at valve close.
        window_s:
            Override default sample_window_s for this measurement.
        """
        if self._active:
            logger.warning(
                "LeakRateEstimator: start_measurement called while already active — resetting"
            )

        self._t0 = (t0 or datetime.now(UTC)).timestamp()
        self._p0 = p0_mbar
        self._window_override = window_s
        self._samples = [(0.0, p0_mbar)] if p0_mbar > 0 else []
        self._active = True
        logger.info("Leak rate measurement started (window=%.0fs)", window_s or self._window_s)

    def add_sample(self, t: datetime, p_mbar: float) -> None:
        """Record a pressure sample, keeping only the trailing window_s of data."""
        if not self._active:
            return
        t_rel = t.timestamp() - self._t0
        self._samples.append((t_rel, p_mbar))
        window = self._window_override or self._window_s
        cutoff = t_rel - window
        if cutoff > 0:
            keep = next(
                (i for i, (ts, _) in enumerate(self._samples) if ts >= cutoff),
                len(self._samples),
            )
            self._samples = self._samples[keep:]

    def should_finalize(self) -> bool:
        """Return True when the configured window has elapsed."""
        if not self._active or not self._samples:
            return False
        window = self._window_override or self._window_s
        last_t_rel = self._samples[-1][0]
        return last_t_rel >= window

    def finalize(self) -> LeakRateMeasurement:
        """Compute and return the leak rate measurement.

        Raises
        ------
        ValueError
            If chamber volume is not configured (≤ 0) or no samples collected.
        """
        if self._volume <= 0:
            raise ValueError(
                "Chamber volume not configured. Set chamber.volume_l in "
                "config/instruments.yaml before measuring leak rate."
            )
        if len(self._samples) < 2:
            raise ValueError(
                f"Insufficient samples for leak rate fit: {len(self._samples)} "
                f"(minimum 2 required)"
            )

        self._active = False
        samples = self._samples
        self._samples = []

        ts, ps = zip(*samples)
        dpdt, intercept, r2 = _linear_regression(list(ts), list(ps))

        duration_s = ts[-1] - ts[0]
        p_initial = ps[0]
        p_final = ps[-1]
        leak_rate = dpdt * self._volume
        started_at = datetime.fromtimestamp(self._t0, tz=UTC).isoformat()

        result = LeakRateMeasurement(
            started_at=started_at,
            duration_s=duration_s,
            initial_pressure_mbar=p_initial,
            final_pressure_mbar=p_final,
            dpdt_mbar_per_s=dpdt,
            chamber_volume_l=self._volume,
            leak_rate_mbar_l_per_s=leak_rate,
            fit_quality_r2=r2,
            samples_n=len(samples),
        )

        logger.info(
            "Leak rate: %.3e mbar·L/s (dP/dt=%.3e mbar/s, R²=%.3f, n=%d)",
            leak_rate,
            dpdt,
            r2,
            len(samples),
        )

        if self._data_dir is not None:
            _append_history(self._data_dir, result)

        return result

    def cancel(self) -> None:
        """Abort measurement without computing result."""
        self._active = False
        self._samples = []
        logger.info("Leak rate measurement cancelled")


# ---------------------------------------------------------------------------
# Math helpers (no numpy — simple OLS)
# ---------------------------------------------------------------------------


def _linear_regression(
    xs: list[float], ys: list[float]
) -> tuple[float, float, float]:
    """Return (slope, intercept, R²) for the linear fit y = slope·x + intercept."""
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    ss_xx = sum((x - mean_x) ** 2 for x in xs)
    ss_xy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))

    if ss_xx == 0.0:
        return 0.0, mean_y, 0.0

    slope = ss_xy / ss_xx
    intercept = mean_y - slope * mean_x

    y_pred = [slope * x + intercept for x in xs]
    ss_res = sum((y - yp) ** 2 for y, yp in zip(ys, y_pred))
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 1.0

    return slope, intercept, max(0.0, min(1.0, r2))


# ---------------------------------------------------------------------------
# History persistence
# ---------------------------------------------------------------------------


def _append_history(data_dir: Path, result: LeakRateMeasurement) -> None:
    history_path = data_dir / _HISTORY_FILENAME
    try:
        if history_path.exists():
            history = json.loads(history_path.read_text(encoding="utf-8"))
        else:
            history = {"measurements": []}
        history["measurements"].append(asdict(result))
        tmp = history_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(history_path)
    except Exception:
        logger.exception("Failed to persist leak rate history")
