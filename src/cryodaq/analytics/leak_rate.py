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

import asyncio
import hashlib
import json
import logging
import math
import multiprocessing
import os
import stat
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from multiprocessing.connection import Connection
from pathlib import Path

from cryodaq.instance_lock import release_lock, try_acquire_lock

logger = logging.getLogger(__name__)

_HISTORY_FILENAME = "leak_rate_history.json"
_HISTORY_LOCK_FILENAME = ".leak_rate_history.lock"
_HISTORY_LOCK_RETRY_S = 0.01
# Matches the configured scheduler shutdown-drain default.  The engine passes
# its active value so leak-rate settlement shares the engine shutdown bound.
_DEFAULT_FINALIZATION_SETTLEMENT_TIMEOUT_S = 5.0
# The standalone default matches the engine's 3 × 10 s default driver-poll
# liveness window.  The production engine always injects its derived value.
_DEFAULT_SAMPLE_LIVENESS_GRACE_S = 30.0


class _HistoryProcessUnsettled(RuntimeError):
    """A history child resisted its bounded termination settlement."""


def _is_finite(value: object) -> bool:
    """Return whether a numeric input is finite without leaking type errors."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except (TypeError, ValueError, OverflowError):
        return False


@dataclass
class LeakRateMeasurement:
    """Result of a completed leak rate measurement."""

    started_at: str  # ISO 8601 UTC
    duration_s: float  # actual measurement duration
    initial_pressure_mbar: float
    final_pressure_mbar: float
    dpdt_mbar_per_s: float  # linear regression slope
    chamber_volume_l: float
    leak_rate_mbar_l_per_s: float  # dpdt × volume
    fit_quality_r2: float  # coefficient of determination (0–1)
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
    sample_liveness_grace_s:
        Finite live-source grace after the measurement window.  The engine
        derives and injects this from the active driver poll-liveness window.
    """

    def __init__(
        self,
        chamber_volume_l: float,
        sample_window_s: float = 300.0,
        data_dir: Path | None = None,
        finalization_settlement_timeout_s: float = _DEFAULT_FINALIZATION_SETTLEMENT_TIMEOUT_S,
        sample_liveness_grace_s: float = _DEFAULT_SAMPLE_LIVENESS_GRACE_S,
    ) -> None:
        self._volume = chamber_volume_l
        if isinstance(chamber_volume_l, bool):
            raise ValueError("Leak-rate chamber volume must be numeric, not boolean")
        self._window_s = sample_window_s
        if not _is_finite(sample_window_s) or sample_window_s <= 0:
            raise ValueError("Leak-rate sample window must be positive and finite")
        if not _is_finite(finalization_settlement_timeout_s) or finalization_settlement_timeout_s <= 0:
            raise ValueError("Leak-rate finalization settlement timeout must be positive and finite")
        if not _is_finite(sample_liveness_grace_s) or sample_liveness_grace_s <= 0:
            raise ValueError("Leak-rate sample liveness grace must be positive and finite")
        self._data_dir = data_dir
        self._finalization_settlement_timeout_s = float(finalization_settlement_timeout_s)
        self._sample_liveness_grace_s = float(sample_liveness_grace_s)

        self._active = False
        self._t0: float = 0.0
        self._p0: float = 0.0
        self._window_override: float | None = None
        self._samples: list[tuple[float, float]] = []  # (t_rel_s, p_mbar)
        self._generation = 0
        self._finalizing_generations: set[int] = set()
        self._history_receipt = ""
        self._time_basis_invalid = False
        self._deadline_monotonic: float | None = None

    # ------------------------------------------------------------------
    # Measurement lifecycle
    # ------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def is_finalizing(self) -> bool:
        """Whether the current measurement generation owns a finalization."""
        return bool(self._finalizing_generations)

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
        if self.is_finalizing:
            raise ValueError("Leak-rate measurement finalization is already in progress")
        if self._active:
            logger.warning("LeakRateEstimator: start_measurement called while already active — resetting")
        if window_s is not None and (not _is_finite(window_s) or window_s <= 0):
            raise ValueError("Leak-rate sample window must be positive and finite")

        self._t0 = (t0 or datetime.now(UTC)).timestamp()
        if not _is_finite(self._t0):
            raise ValueError("Leak-rate measurement start time must be finite")
        self._p0 = p0_mbar
        self._window_override = window_s
        self._samples = [(0.0, p0_mbar)] if _is_finite(p0_mbar) and p0_mbar > 0 else []
        self._generation += 1
        self._history_receipt = uuid.uuid4().hex
        self._time_basis_invalid = False
        self._deadline_monotonic = time.monotonic() + self._window() + self._sample_liveness_grace_s
        self._active = True
        logger.info("Leak rate measurement started (window=%.0fs)", self._window())

    def add_sample(self, t: datetime, p_mbar: float) -> None:
        """Record a pressure sample, keeping only the trailing window_s of data."""
        if not self._active:
            return
        t_rel = t.timestamp() - self._t0
        if not _is_finite(t_rel) or not _is_finite(p_mbar):
            return
        if self._samples and t_rel <= self._samples[-1][0]:
            self._time_basis_invalid = True
        self._samples.append((t_rel, p_mbar))
        window = self._window()
        cutoff = t_rel - window
        if cutoff > 0:
            keep = next(
                (i for i, (ts, _) in enumerate(self._samples) if ts >= cutoff),
                len(self._samples),
            )
            self._samples = self._samples[keep:]

    def should_finalize(self, t: datetime | None = None) -> bool:
        """Return True when the configured window has elapsed."""
        if not self._active:
            return False
        window = self._window()
        if t is None:
            if not self._samples:
                return False
            elapsed_s = self._samples[-1][0]
        else:
            elapsed_s = t.timestamp() - self._t0
        return _is_finite(elapsed_s) and elapsed_s >= window

    def deadline_remaining_s(self) -> float | None:
        """Return remaining bounded live-source liveness grace for the active run."""
        if not self._active or self._deadline_monotonic is None:
            return None
        return max(0.0, self._deadline_monotonic - time.monotonic())

    def finalize(self) -> LeakRateMeasurement | None:
        """Compute, persist, and return the leak rate measurement.

        Raises
        ------
        ValueError
            If chamber volume is not configured (≤ 0) or no samples collected.
        """
        generation, result = self._claim_finalization()
        try:
            if self._data_dir is not None:
                _append_history(self._data_dir, result)
        except BaseException:
            self._release_finalization(generation)
            raise
        return self._complete(generation, result)

    async def finalize_async(self) -> LeakRateMeasurement | None:
        """Finalize through an owned process, never the loop's default executor."""
        generation, result = self._claim_finalization()
        try:
            if self._data_dir is not None:
                await self._persist_history_in_owned_process(result)
        except _HistoryProcessUnsettled:
            # A live child still owns a possible write.  Keep this generation
            # fenced rather than making retry/publication authority available.
            raise
        except BaseException:
            self._release_finalization(generation)
            raise
        return self._complete(generation, result)

    async def _persist_history_in_owned_process(self, result: LeakRateMeasurement) -> None:
        """Wait for one daemon process and forcibly settle it on cancellation.

        A process is the visibility boundary: after cancellation we terminate it
        before returning, so a stalled write cannot survive ``asyncio.run()``
        teardown or later replace the visible history file.
        """
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(
            target=_history_process_entry,
            args=(self._data_dir, result, sender, self._finalization_settlement_timeout_s),
            daemon=True,
        )
        outcome: tuple[str, str] | None = None
        started = False
        settled = False
        deadline = time.monotonic() + self._finalization_settlement_timeout_s
        try:
            interrupted = await self._start_history_process(process)
            started = True
            if interrupted:
                raise asyncio.CancelledError
            while True:
                if outcome is None and receiver.poll():
                    outcome = receiver.recv()
                if not process.is_alive():
                    if outcome is None and receiver.poll():
                        continue
                    if outcome is None:
                        raise OSError(f"Leak-rate history process exited without a result (exit={process.exitcode})")
                    status, detail = outcome
                    if status == "ok":
                        self._close_history_process(process)
                        settled = True
                        return
                    raise OSError(f"Leak-rate history persistence failed: {detail}")
                if time.monotonic() >= deadline:
                    interrupted = await self._settle_history_process(process, deadline)
                    settled = True
                    if interrupted:
                        raise asyncio.CancelledError
                    raise OSError("Leak-rate history process did not report within the settlement bound")
                await asyncio.sleep(0.001)
        except asyncio.CancelledError:
            if started and not settled:
                await self._settle_history_process(process, deadline)
                settled = True
            raise
        finally:
            sender.close()
            receiver.close()
            if started and not settled and not process.is_alive():
                self._close_history_process(process)

    @staticmethod
    async def _await_owned_future(future: asyncio.Future[object]) -> bool:
        """Wait through repeated caller cancellation and report that it occurred."""
        interrupted = False
        while True:
            try:
                await asyncio.shield(future)
                return interrupted
            except asyncio.CancelledError:
                interrupted = True

    async def _start_history_process(self, process: multiprocessing.Process) -> bool:
        """Run blocking Windows process startup in a per-owner executor."""
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="leak-history-start")
        future = asyncio.get_running_loop().run_in_executor(executor, process.start)
        try:
            interrupted = await self._await_owned_future(future)
        finally:
            # The future has settled before this executor is released; no default
            # executor worker can survive engine teardown with a process owner.
            executor.shutdown(wait=False, cancel_futures=True)
        return interrupted

    async def _settle_history_process(self, process: multiprocessing.Process, deadline: float) -> bool:
        """Shield the process lifetime settlement from repeated cancellation."""
        cleanup = asyncio.create_task(self._terminate_history_process(process, deadline))
        return await self._await_owned_future(cleanup)

    @staticmethod
    def _close_history_process(process: multiprocessing.Process) -> None:
        process.join(timeout=0)
        process.close()

    async def _terminate_history_process(self, process: multiprocessing.Process, deadline: float) -> None:
        """Terminate a cancelled persistence owner within the configured bound."""
        terminate_deadline = time.monotonic() + max(0.0, deadline - time.monotonic()) / 2
        try:
            process.terminate()
        except Exception:
            logger.warning("Leak-rate history process terminate failed", exc_info=True)
        while process.is_alive() and time.monotonic() < terminate_deadline:  # noqa: ASYNC110 -- OS process has no awaitable exit
            await asyncio.sleep(0.001)
        if process.is_alive():
            try:
                process.kill()
            except Exception:
                logger.warning("Leak-rate history process kill failed", exc_info=True)
            while process.is_alive() and time.monotonic() < deadline:  # noqa: ASYNC110 -- OS process has no awaitable exit
                await asyncio.sleep(0.001)
        if process.is_alive():
            raise _HistoryProcessUnsettled("Leak-rate history process did not terminate within the settlement bound")
        self._close_history_process(process)

    def _window(self) -> float:
        return self._window_override if self._window_override is not None else self._window_s

    def _claim_finalization(self) -> tuple[int, LeakRateMeasurement]:
        if not self._active:
            raise ValueError("Leak-rate measurement is not active")
        generation = self._generation
        if generation in self._finalizing_generations:
            raise ValueError("Leak-rate measurement finalization is already in progress")
        result = self._build_result()
        self._finalizing_generations.add(generation)
        return generation, result

    def _build_result(self) -> LeakRateMeasurement:
        """Build a result without settling the active measurement state."""
        if not _is_finite(self._volume) or self._volume <= 0:
            raise ValueError(
                "Chamber volume not configured. Set chamber.volume_l in "
                "config/instruments.yaml before measuring leak rate."
            )
        if len(self._samples) < 2:
            raise ValueError(f"Insufficient samples for leak rate fit: {len(self._samples)} (minimum 2 required)")

        samples = self._samples
        if not _is_finite(self._t0) or not all(
            _is_finite(t_rel) and _is_finite(pressure) for t_rel, pressure in samples
        ):
            raise ValueError("Leak-rate samples must have finite timestamps and pressures")
        if self._time_basis_invalid or any(
            current[0] <= previous[0] for previous, current in zip(samples, samples[1:])
        ):
            raise ValueError("Leak-rate regression requires a strictly increasing time basis")

        ts, ps = zip(*samples)
        duration_s = ts[-1] - ts[0]
        if not _is_finite(duration_s) or duration_s <= 0:
            raise ValueError("Leak-rate regression requires a positive, identifiable time basis")
        dpdt, intercept, r2 = _linear_regression(list(ts), list(ps))

        p_initial = ps[0]
        p_final = ps[-1]
        leak_rate = dpdt * self._volume
        if not all(
            _is_finite(value)
            for value in (
                duration_s,
                p_initial,
                p_final,
                dpdt,
                intercept,
                self._volume,
                leak_rate,
                r2,
            )
        ):
            raise ValueError("Leak-rate calculation produced a non-finite result")
        try:
            started_at = datetime.fromtimestamp(self._t0, tz=UTC).isoformat()
        except (OSError, OverflowError, ValueError) as exc:
            raise ValueError("Leak-rate measurement start time is invalid") from exc

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
        result._history_receipt = self._history_receipt

        return result

    def _release_finalization(self, generation: int) -> bool:
        self._finalizing_generations.discard(generation)
        return generation != self._generation

    def _complete(self, generation: int, result: LeakRateMeasurement) -> LeakRateMeasurement | None:
        stale = self._release_finalization(generation)
        if stale:
            return None
        self._active = False
        self._samples = []
        self._deadline_monotonic = None
        logger.info(
            "Leak rate: %.3e mbar·L/s (dP/dt=%.3e mbar/s, R²=%.3f, n=%d)",
            result.leak_rate_mbar_l_per_s,
            result.dpdt_mbar_per_s,
            result.fit_quality_r2,
            result.samples_n,
        )
        return result

    def cancel(self) -> None:
        """Abort measurement without computing result."""
        if self.is_finalizing:
            logger.warning("LeakRateEstimator: finalization owns settlement; cancellation deferred")
            return
        self._active = False
        self._samples = []
        self._deadline_monotonic = None
        self._generation += 1
        logger.info("Leak rate measurement cancelled")


# ---------------------------------------------------------------------------
# Math helpers (no numpy — simple OLS)
# ---------------------------------------------------------------------------


def _linear_regression(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    """Return (slope, intercept, R²) for the linear fit y = slope·x + intercept."""
    n = len(xs)
    if n < 2 or len(ys) != n:
        raise ValueError("Leak-rate regression requires equal coordinate lists with at least two samples")
    if not all(_is_finite(x) and _is_finite(y) for x, y in zip(xs, ys)):
        raise ValueError("Leak-rate regression coordinates must be finite")

    try:
        mean_x = sum(xs) / n
        mean_y = sum(ys) / n
        ss_xx = sum((x - mean_x) ** 2 for x in xs)
        ss_xy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    except OverflowError as exc:
        raise ValueError("Leak-rate regression calculation must remain finite") from exc
    if not all(_is_finite(value) for value in (mean_x, mean_y, ss_xx, ss_xy)):
        raise ValueError("Leak-rate regression calculation must remain finite")

    if ss_xx <= 0.0 or any(current <= previous for previous, current in zip(xs, xs[1:])):
        raise ValueError("Leak-rate regression requires a strictly increasing, identifiable time basis")

    slope = ss_xy / ss_xx
    intercept = mean_y - slope * mean_x

    try:
        y_pred = [slope * x + intercept for x in xs]
        ss_res = sum((y - yp) ** 2 for y, yp in zip(ys, y_pred))
        ss_tot = sum((y - mean_y) ** 2 for y in ys)
    except OverflowError as exc:
        raise ValueError("Leak-rate regression calculation must remain finite") from exc
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 1.0
    if not all(_is_finite(value) for value in (slope, intercept, ss_res, ss_tot, r2)):
        raise ValueError("Leak-rate regression calculation must remain finite")

    return slope, intercept, max(0.0, min(1.0, r2))


# ---------------------------------------------------------------------------
# History persistence
# ---------------------------------------------------------------------------


def _strict_json_number(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite JSON number")
    return number


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Non-standard JSON constant: {value}")


def _reject_history_payload_link(history_path: Path) -> None:
    """Refuse a link/reparse payload before any history read or replacement."""
    try:
        metadata = os.lstat(history_path)
    except FileNotFoundError:
        return
    reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if stat.S_ISLNK(metadata.st_mode) or bool(getattr(metadata, "st_file_attributes", 0) & reparse_point):
        raise OSError(f"Leak-rate history payload must not be a symlink or reparse point: {history_path}")


def _receipt_for_measurement(measurement: dict[str, object]) -> str:
    return hashlib.sha256(json.dumps(measurement, sort_keys=True, allow_nan=False).encode("utf-8")).hexdigest()


_HISTORY_MEASUREMENT_NUMERIC_FIELDS = frozenset(
    {
        "duration_s",
        "initial_pressure_mbar",
        "final_pressure_mbar",
        "dpdt_mbar_per_s",
        "chamber_volume_l",
        "leak_rate_mbar_l_per_s",
        "fit_quality_r2",
    }
)
_HISTORY_MEASUREMENT_KEYS = _HISTORY_MEASUREMENT_NUMERIC_FIELDS | {"started_at", "samples_n"}


def _validate_history_measurement(measurement: dict[str, object]) -> None:
    """Reject a receipt row whose persisted JSON shape is not a measurement."""
    if (
        set(measurement) != _HISTORY_MEASUREMENT_KEYS
        or type(measurement["started_at"]) is not str
        or not measurement["started_at"]
        or type(measurement["samples_n"]) is not int
        or measurement["samples_n"] < 2
        or any(not _is_finite(measurement[field]) for field in _HISTORY_MEASUREMENT_NUMERIC_FIELDS)
    ):
        raise ValueError("Leak-rate history measurements are inconsistent")


def _canonical_measurement_bytes(measurement: dict[str, object]) -> bytes:
    """Retain JSON's exact bool-versus-number distinction for receipt pairing."""
    return json.dumps(measurement, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _validate_history_receipts(
    history: object, result: LeakRateMeasurement, receipt: str
) -> tuple[dict[str, object], bool]:
    """Return validated history and whether its exact result already committed."""
    if not isinstance(history, dict):
        raise ValueError("Leak-rate history must be a JSON object")
    measurements = history.get("measurements", [])
    if not isinstance(measurements, list) or not all(isinstance(item, dict) for item in measurements):
        raise ValueError("Leak-rate history measurements are inconsistent")
    normalized_measurements = [dict(item) for item in measurements]
    for measurement in normalized_measurements:
        _validate_history_measurement(measurement)
    expected_measurement = asdict(result)
    _validate_history_measurement(expected_measurement)
    receipts = history.get("receipts")
    if receipts is None:
        receipts = [_receipt_for_measurement(item) for item in normalized_measurements]
        history["receipts"] = receipts
    if (
        not isinstance(receipts, list)
        or len(receipts) != len(normalized_measurements)
        or any(type(item) is not str or not item for item in receipts)
        or len(set(receipts)) != len(receipts)
    ):
        raise ValueError("Leak-rate history receipts are inconsistent")
    matches = [index for index, item in enumerate(receipts) if item == receipt]
    if not matches:
        return history, False
    if len(matches) != 1 or (
        _canonical_measurement_bytes(normalized_measurements[matches[0]])
        != _canonical_measurement_bytes(expected_measurement)
    ):
        raise ValueError("Leak-rate history receipt does not match its persisted measurement")
    return history, True


def _quarantine_legacy_history(history_path: Path, content: bytes) -> None:
    digest = hashlib.sha256(content).hexdigest()
    quarantine_path = history_path.with_name(f"{history_path.name}.invalid-{digest}")
    try:
        with quarantine_path.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        with quarantine_path.open("r+b") as handle:
            if handle.read() != content:
                raise
            handle.flush()
            os.fsync(handle.fileno())
    _fsync_directory(history_path.parent)


def _fsync_directory(path: Path) -> None:
    """Settle directory entries where Python exposes directory fsync."""
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_replace_bytes(path: Path, content: bytes) -> None:
    """Cooldown-model idiom: temp write, file fsync, replace, directory fsync."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    replaced = False
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        replaced = True
        _fsync_directory(path.parent)
    except BaseException:
        if not replaced:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        raise


def _history_process_entry(
    data_dir: Path,
    result: LeakRateMeasurement,
    sender: Connection,
    lock_timeout_s: float,
) -> None:
    """Run one persistence attempt in the process that owns its lifetime."""
    try:
        _append_history(data_dir, result, lock_timeout_s=lock_timeout_s)
    except BaseException:
        sender.send(("error", "history write failed"))
    else:
        sender.send(("ok", ""))
    finally:
        sender.close()


def _settle_visible_history(history_path: Path) -> None:
    """Durably acknowledge a receipt that survived replacement before returning it."""
    _reject_history_payload_link(history_path)
    with history_path.open("r+b") as handle:
        os.fsync(handle.fileno())
    _fsync_directory(history_path.parent)


def _acquire_history_lock(data_dir: Path, lock_timeout_s: float) -> int:
    """Acquire the stable per-history kernel lock within one truthful bound."""
    deadline = time.monotonic() + lock_timeout_s
    while True:
        descriptor = try_acquire_lock(_HISTORY_LOCK_FILENAME, lock_dir=data_dir)
        if descriptor is not None:
            return descriptor
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Timed out acquiring leak-rate history lock")
        time.sleep(min(_HISTORY_LOCK_RETRY_S, remaining))


def _append_history(
    data_dir: Path,
    result: LeakRateMeasurement,
    *,
    lock_timeout_s: float = _DEFAULT_FINALIZATION_SETTLEMENT_TIMEOUT_S,
) -> None:
    """Append one history result under the one crash-safe lock for its data directory."""
    descriptor = _acquire_history_lock(data_dir, lock_timeout_s)
    try:
        _append_history_locked(data_dir, result)
    finally:
        release_lock(descriptor, _HISTORY_LOCK_FILENAME, unlink=False, lock_dir=data_dir)


def _append_history_locked(data_dir: Path, result: LeakRateMeasurement) -> None:
    history_path = data_dir / _HISTORY_FILENAME
    _reject_history_payload_link(history_path)
    if history_path.exists():
        content = history_path.read_bytes()
        try:
            history = json.loads(
                content.decode("utf-8"),
                parse_constant=_reject_json_constant,
                parse_float=_strict_json_number,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            _quarantine_legacy_history(history_path, content)
            logger.warning("Quarantined invalid leak rate history: %s", history_path)
            history = {"measurements": []}
    else:
        history = {"measurements": []}
    receipt = getattr(result, "_history_receipt", None)
    if not receipt:
        receipt = hashlib.sha256(
            json.dumps(asdict(result), sort_keys=True, allow_nan=False).encode("utf-8")
        ).hexdigest()
    history, already_persisted = _validate_history_receipts(history, result, receipt)
    if already_persisted:
        _settle_visible_history(history_path)
        return
    history["measurements"].append(asdict(result))
    history["receipts"].append(receipt)
    _reject_history_payload_link(history_path)
    _atomic_replace_bytes(
        history_path,
        json.dumps(history, indent=2, ensure_ascii=False, allow_nan=False).encode("utf-8"),
    )
