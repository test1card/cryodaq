"""SensorDiagnosticsEngine — мониторинг здоровья датчиков.

Read-only аналитика поверх ChannelStateTracker:
- noise (MAD-based, robust to outliers)
- drift (OLS slope)
- correlation (Pearson r внутри групп)
- health score (0-100)
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np

from cryodaq.core.rate_estimator import _ols_slope_per_min


@dataclass
class ChannelDiagnostics:
    channel_id: str
    channel_name: str
    current_T: float
    noise_std: float           # MAD-based σ (K)
    noise_mK: float            # same in mK
    drift_rate: float          # K/min
    drift_mK_per_min: float    # same in mK/min
    outlier_count: int         # in outlier window
    correlation: float | None  # Pearson r with nearest neighbour in group
    health_score: int          # 0-100
    fault_flags: list[str] = field(default_factory=list)
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class DiagnosticsSummary:
    total_channels: int
    healthy: int               # health >= 80
    warning: int               # 50 <= health < 80
    critical: int              # health < 50
    worst_channel: str
    worst_score: int
    worst_flags: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Noise thresholds by temperature (DT-670 sensitivity zones)
# ---------------------------------------------------------------------------

def _get_noise_threshold(T: float) -> float:
    """Допустимый шум (K) для данной температуры DT-670."""
    if T < 30:
        return 0.02
    elif T < 100:
        return 0.05
    elif T < 200:
        return 0.1
    else:
        return 0.2


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------

def _mad_sigma(values: np.ndarray) -> float:
    """MAD-based estimate of σ: median(|x - median(x)|) × 1.4826."""
    if len(values) < 2:
        return float("nan")
    median = np.median(values)
    mad = np.median(np.abs(values - median))
    return float(mad * 1.4826)


def _pearson_r(x: np.ndarray, y: np.ndarray) -> float | None:
    """Pearson correlation. None if insufficient data or zero variance."""
    if len(x) < 10 or len(y) < 10 or len(x) != len(y):
        return None
    sx = np.std(x, ddof=0)
    sy = np.std(y, ddof=0)
    if sx == 0.0 or sy == 0.0:
        return None
    r = float(np.corrcoef(x, y)[0, 1])
    if math.isnan(r):
        return None
    return r


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------

class SensorDiagnosticsEngine:
    """Мониторинг здоровья датчиков. Read-only, работает поверх буферов данных."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
    ) -> None:
        cfg = config or {}
        thresholds = cfg.get("thresholds", {})

        self.noise_window_s: float = cfg.get("noise_window_s", 120)
        self.drift_window_s: float = cfg.get("drift_window_s", 600)
        self.corr_window_s: float = cfg.get("corr_window_s", 600)
        self.outlier_window_s: float = cfg.get("outlier_window_s", 300)
        self.outlier_sigma: float = thresholds.get("outlier_sigma", 5.0)
        self.drift_threshold: float = thresholds.get("drift_K_per_min", 0.1)
        self.corr_min: float = thresholds.get("correlation_min", 0.8)
        self.min_points: int = cfg.get("min_points", 10)

        # channel_id → deque of (timestamp_s, value)
        self._buffers: dict[str, deque[tuple[float, float]]] = {}
        # Max buffer size: drift window at 10 Hz + margin
        self._maxlen: int = max(500, int(max(self.drift_window_s, self.corr_window_s) * 10) + 200)

        # correlation_groups: group_name → list of channel_ids
        self._correlation_groups: dict[str, list[str]] = dict(cfg.get("correlation_groups", {}))
        # Reverse map: channel_id → group_name
        self._channel_to_group: dict[str, str] = {}
        for group_name, channels in self._correlation_groups.items():
            for ch in channels:
                self._channel_to_group[ch] = group_name

        # channel_id → display name
        self._channel_names: dict[str, str] = {}

        # Cached diagnostics
        self._diagnostics: dict[str, ChannelDiagnostics] = {}

    def set_channel_names(self, names: dict[str, str]) -> None:
        """Set display names for channels."""
        self._channel_names = dict(names)

    def push(self, channel_id: str, timestamp: float, value: float) -> None:
        """Add a data point for a channel."""
        buf = self._buffers.setdefault(channel_id, deque(maxlen=self._maxlen))
        buf.append((timestamp, value))

    def update(self) -> None:
        """Recompute diagnostics for all channels with data."""
        now = datetime.now(timezone.utc)
        for channel_id, buf in self._buffers.items():
            if not buf:
                continue
            diag = self._compute_channel(channel_id, buf, now)
            self._diagnostics[channel_id] = diag

    def get_diagnostics(self) -> dict[str, ChannelDiagnostics]:
        """All channel diagnostics."""
        return dict(self._diagnostics)

    def get_summary(self) -> DiagnosticsSummary:
        """Aggregate summary for status bar."""
        diags = list(self._diagnostics.values())
        if not diags:
            return DiagnosticsSummary(
                total_channels=0, healthy=0, warning=0, critical=0,
                worst_channel="", worst_score=100, worst_flags=[],
            )
        healthy = sum(1 for d in diags if d.health_score >= 80)
        warning = sum(1 for d in diags if 50 <= d.health_score < 80)
        critical = sum(1 for d in diags if d.health_score < 50)
        worst = min(diags, key=lambda d: d.health_score)
        return DiagnosticsSummary(
            total_channels=len(diags),
            healthy=healthy,
            warning=warning,
            critical=critical,
            worst_channel=worst.channel_id,
            worst_score=worst.health_score,
            worst_flags=list(worst.fault_flags),
        )

    # -------------------------------------------------------------------
    # Internal computation
    # -------------------------------------------------------------------

    def _compute_channel(
        self, channel_id: str, buf: deque[tuple[float, float]], now: datetime,
    ) -> ChannelDiagnostics:
        current_T = buf[-1][1]
        name = self._channel_names.get(channel_id, channel_id)

        # Noise (over noise window)
        noise_points = self._window_values(buf, self.noise_window_s)
        if len(noise_points) >= self.min_points:
            noise_std = _mad_sigma(noise_points)
        else:
            noise_std = float("nan")

        # Drift (over drift window)
        drift_points = self._window_points(buf, self.drift_window_s)
        if len(drift_points) >= self.min_points:
            drift_rate = _ols_slope_per_min(drift_points)
            if drift_rate is None:
                drift_rate = float("nan")
        else:
            drift_rate = float("nan")

        # Outliers (over outlier window)
        outlier_points = self._window_values(buf, self.outlier_window_s)
        outlier_count = self._count_outliers(outlier_points)

        # Correlation
        correlation = self._compute_correlation(channel_id)

        # Fault flags
        fault_flags = self._compute_fault_flags(
            current_T, noise_std, drift_rate, outlier_count, correlation,
        )

        # Health score
        health_score = self._compute_health(
            noise_std, drift_rate, outlier_count, correlation, current_T,
        )

        return ChannelDiagnostics(
            channel_id=channel_id,
            channel_name=name,
            current_T=current_T,
            noise_std=noise_std if math.isfinite(noise_std) else float("nan"),
            noise_mK=noise_std * 1000.0 if math.isfinite(noise_std) else float("nan"),
            drift_rate=drift_rate if math.isfinite(drift_rate) else float("nan"),
            drift_mK_per_min=drift_rate * 1000.0 if math.isfinite(drift_rate) else float("nan"),
            outlier_count=outlier_count,
            correlation=correlation,
            health_score=health_score,
            fault_flags=fault_flags,
            updated_at=now,
        )

    def _window_values(self, buf: deque[tuple[float, float]], window_s: float) -> np.ndarray:
        """Extract values within the last window_s seconds."""
        if not buf:
            return np.array([])
        latest_ts = buf[-1][0]
        cutoff = latest_ts - window_s
        return np.array([v for t, v in buf if t >= cutoff])

    def _window_points(self, buf: deque[tuple[float, float]], window_s: float) -> list[tuple[float, float]]:
        """Extract (ts, value) pairs within the last window_s seconds."""
        if not buf:
            return []
        latest_ts = buf[-1][0]
        cutoff = latest_ts - window_s
        return [(t, v) for t, v in buf if t >= cutoff]

    def _count_outliers(self, values: np.ndarray) -> int:
        """Count values deviating > outlier_sigma × MAD-σ from median."""
        if len(values) < self.min_points:
            return 0
        median = np.median(values)
        sigma = _mad_sigma(values)
        if sigma == 0.0 or not math.isfinite(sigma):
            return 0
        return int(np.sum(np.abs(values - median) > self.outlier_sigma * sigma))

    def _compute_correlation(self, channel_id: str) -> float | None:
        """Pearson r with best-correlated neighbour in the same group."""
        group_name = self._channel_to_group.get(channel_id)
        if group_name is None:
            return None
        group_channels = self._correlation_groups.get(group_name, [])
        neighbours = [ch for ch in group_channels if ch != channel_id and ch in self._buffers]
        if not neighbours:
            return None

        my_buf = self._buffers[channel_id]
        my_points = self._window_points(my_buf, self.corr_window_s)
        if len(my_points) < self.min_points:
            return None

        # Build aligned arrays by matching timestamps
        my_ts_set = {t for t, _ in my_points}
        best_r: float | None = None
        for neighbour_id in neighbours:
            n_buf = self._buffers[neighbour_id]
            n_points = self._window_points(n_buf, self.corr_window_s)
            if len(n_points) < self.min_points:
                continue

            # Align by common timestamps
            n_map = {t: v for t, v in n_points}
            common_ts = sorted(my_ts_set & set(n_map.keys()))
            if len(common_ts) < self.min_points:
                continue

            my_vals = np.array([v for t, v in my_points if t in set(common_ts)])
            n_vals = np.array([n_map[t] for t in common_ts])

            if len(my_vals) != len(n_vals):
                # Rebuild properly
                my_map = {t: v for t, v in my_points}
                my_vals = np.array([my_map[t] for t in common_ts])
                n_vals = np.array([n_map[t] for t in common_ts])

            r = _pearson_r(my_vals, n_vals)
            if r is not None and (best_r is None or r > best_r):
                best_r = r

        return best_r

    def _compute_fault_flags(
        self,
        current_T: float,
        noise_std: float,
        drift_rate: float,
        outlier_count: int,
        correlation: float | None,
    ) -> list[str]:
        flags: list[str] = []
        if current_T > 350.0:
            flags.append("disconnected")
        if current_T <= 0.0:
            flags.append("shorted")
        if math.isfinite(noise_std):
            threshold = _get_noise_threshold(current_T)
            if noise_std > threshold:
                flags.append("noisy")
        if math.isfinite(drift_rate) and abs(drift_rate) > self.drift_threshold:
            flags.append("drifting")
        if correlation is not None and correlation < self.corr_min:
            flags.append("uncorrelated")
        return flags

    def _compute_health(
        self,
        noise: float,
        drift: float,
        outliers: int,
        correlation: float | None,
        T_current: float,
    ) -> int:
        # Disconnected / shorted → immediate low score
        if T_current > 350.0 or T_current <= 0.0:
            return 0

        # Insufficient data → no penalty
        if not math.isfinite(noise) and not math.isfinite(drift):
            return 100

        health = 100

        # Noise penalty (temperature-dependent thresholds)
        if math.isfinite(noise):
            threshold = _get_noise_threshold(T_current)
            if noise > threshold * 3:
                health -= 40
            elif noise > threshold:
                health -= 20

        # Drift penalty
        if math.isfinite(drift) and abs(drift) > self.drift_threshold:
            health -= 25

        # Outlier penalty
        if outliers > 5:
            health -= 30
        elif outliers > 2:
            health -= 15

        # Correlation penalty
        if correlation is not None and correlation < self.corr_min:
            health -= 20

        return max(0, health)
