"""Acquisition always runs. Analytics runs only when it is given resource.

The rule this module makes structural, rather than a convention every author has
to remember:

    Reading an instrument and committing to SQLite are never delayed by a
    calculation. Safety, interlocks and alarm evaluation are NOT analytics —
    they stay in the critical path. Everything that merely computes over data
    already captured — vacuum fits, cooldown ETA, steady-state, sensor
    diagnostics, correlations, reports — is best-effort: it may be late, and it
    may skip a recompute entirely, but it may never make acquisition wait.

Written after 2026-09-01 02:39, where a vacuum curve fit ran inline on the event
loop, blocked it for ~8 s, and cost a running cryostat 6 h 46 min of temperature
data. Nothing in the tree measured event-loop lag, so the stall was invisible
except as a side effect on the fastest-sampling channel.

Three properties matter, and each exists because its absence caused harm:

**Input is never throttled.** Only the *recompute* is skipped. Samples keep
arriving at full rate into whatever buffer the analytic owns; what is dropped is
arithmetic, never data.

**Jobs never queue.** One instance of a calculation at a time. If a run is still
in flight when the next is due, the next is skipped and counted — it is not
queued behind it. A queue would convert a slow analytic into an ever-growing
backlog that re-runs stale work; skipping means the next admitted run reads the
freshest buffer there is.

**Degradation is visible.** A silently stale forecast is the same class of lie
as a chart that draws a straight line through an outage. Every job reports when
it last produced a result and how many recomputes it has skipped, so the
operator is told the number is old instead of being left to assume it is current.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class AnalyticsPrecision(StrEnum):
    """How much work a calculation may spend, given what the loop can spare.

    Refusing to run at all is the last resort, not the first response. A cheaper
    answer now is worth more to an operator than an exact one after the engine
    has recovered — a vacuum ETA computed from a quarter of the samples is still
    the right order of magnitude, and it costs a fraction of the time. Skipping
    is reserved for the case where even the cheap version cannot be afforded.
    """

    FULL = "full"
    REDUCED = "reduced"


# Loop lag at or above which calculations drop to their cheap form. Chosen so
# ordinary jitter on a loaded operator PC does not trigger it, while a loop
# already starting to slip does.
DEFAULT_REDUCE_AT_S = 0.2

# Loop lag at or above which new analytic runs stop being admitted. Well below
# the bus-scoped read deadlines that a stall turns into instrument timeouts, and
# far above ordinary scheduling jitter on a loaded operator PC.
DEFAULT_OVERLOAD_ENTER_S = 0.5
# Lag must fall back to this and stay there before analytics resumes. The gap
# between the two thresholds is the hysteresis: without it a loop sitting near
# the limit would admit and refuse alternately, which is worse than either
# state because every run would then be a partial one.
DEFAULT_OVERLOAD_LEAVE_S = 0.15
DEFAULT_RECOVERY_S = 30.0
# How often the lag probe wakes. Small enough to notice a stall while it is
# still happening; one timer, no measurable cost.
DEFAULT_PROBE_INTERVAL_S = 0.5
# Analytics runs on its own small pool, never the loop's default executor.
# The default one is shared with everything else that offloads work, so a
# saturated pool would let best-effort calculations queue in front of, and
# delay, operations that are not best-effort at all — while loop lag stays
# low and the admission controller sees nothing wrong.
DEFAULT_ANALYTICS_WORKERS = 2


@dataclass(frozen=True, slots=True)
class AnalyticsJobStatus:
    """What an operator needs to judge whether a number can be trusted."""

    name: str
    running: bool
    last_result_monotonic: float | None
    last_duration_s: float | None
    skipped_overloaded: int
    skipped_still_running: int
    skipped_too_soon: int
    skipped_saturated: int
    failures: int

    def staleness_s(self, *, now: float | None = None) -> float | None:
        """Seconds since this job last produced a result, or None if never."""
        if self.last_result_monotonic is None:
            return None
        return max(0.0, (time.monotonic() if now is None else now) - self.last_result_monotonic)


@dataclass
class _JobState:
    name: str
    min_interval_s: float
    running: bool = False
    last_result_monotonic: float | None = None
    last_attempt_monotonic: float | None = None
    last_duration_s: float | None = None
    skipped_overloaded: int = 0
    skipped_still_running: int = 0
    skipped_too_soon: int = 0
    skipped_saturated: int = 0
    failures: int = 0
    inflight: Future | None = None


class LoopLagMonitor:
    """Measures how late the event loop is running its own timers.

    A task that sleeps a known interval and measures the overshoot. That
    overshoot IS the lag: if the loop were free, ``sleep(0.5)`` would return
    after 0.5 s, and anything beyond that is time some other coroutine held it.

    This is the sense organ the engine did not have. The 2026-09-01 freeze was
    only ever visible as a clock-jump warning on the one channel sampled fast
    enough to notice, and it took a log archaeology session to find.
    """

    def __init__(self, *, interval_s: float = DEFAULT_PROBE_INTERVAL_S) -> None:
        if not interval_s > 0.0:
            raise ValueError("lag probe interval must be positive")
        self._interval_s = float(interval_s)
        self._lag_s = 0.0
        self._peak_lag_s = 0.0
        self._observers: list[Callable[[float], None]] = []

    @property
    def lag_s(self) -> float:
        """Most recently measured loop lag."""
        return self._lag_s

    @property
    def peak_lag_s(self) -> float:
        """Worst lag seen since the last ``take_peak()``."""
        return self._peak_lag_s

    def take_peak(self) -> float:
        """Read and reset the peak, for periodic reporting."""
        peak = self._peak_lag_s
        self._peak_lag_s = self._lag_s
        return peak

    def subscribe(self, observer: Callable[[float], None]) -> None:
        self._observers.append(observer)

    def observe(self, lag_s: float) -> None:
        """Record one measurement. Public so tests can drive it directly."""
        lag = max(0.0, float(lag_s))
        self._lag_s = lag
        self._peak_lag_s = max(self._peak_lag_s, lag)
        for observer in self._observers:
            try:
                observer(lag)
            except Exception:  # pragma: no cover - an observer must not stop the probe
                logger.debug("loop lag observer failed", exc_info=True)

    async def run(self) -> None:
        """Probe forever. Cheap by construction: one sleep, one subtraction."""
        while True:
            started = time.monotonic()
            await asyncio.sleep(self._interval_s)
            self.observe(time.monotonic() - started - self._interval_s)


def _wait_for(future: Future, timeout_s: float) -> bool:
    try:
        future.result(timeout=timeout_s)
    except Exception:
        # Any completion settles ownership; the outcome itself is the job's.
        return True
    return True


class AnalyticsAdmission:
    """Decides whether a recompute may start, and remembers what it refused.

    Deliberately not a scheduler and not a queue. It answers one question —
    *may this run now* — and records the answer, so a skipped recompute is a
    fact the operator can see rather than a silence.
    """

    def __init__(
        self,
        *,
        enter_overload_s: float = DEFAULT_OVERLOAD_ENTER_S,
        leave_overload_s: float = DEFAULT_OVERLOAD_LEAVE_S,
        reduce_at_s: float = DEFAULT_REDUCE_AT_S,
        recovery_s: float = DEFAULT_RECOVERY_S,
        max_workers: int = DEFAULT_ANALYTICS_WORKERS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not enter_overload_s > leave_overload_s > 0.0:
            raise ValueError("overload thresholds must satisfy enter > leave > 0")
        if not enter_overload_s > reduce_at_s > 0.0:
            raise ValueError("precision threshold must sit below the overload threshold")
        self._enter_s = float(enter_overload_s)
        self._leave_s = float(leave_overload_s)
        self._recovery_s = float(recovery_s)
        self._clock = clock
        self._reduce_at_s = float(reduce_at_s)
        self._overloaded = False
        self._calm_since: float | None = None
        self._overloaded_since: float | None = None
        self._precision = AnalyticsPrecision.FULL
        self._precision_calm_since: float | None = None
        self._jobs: dict[str, _JobState] = {}
        if max_workers < 1:
            raise ValueError("analytics needs at least one worker")
        self._max_workers = int(max_workers)
        self._executor = ThreadPoolExecutor(max_workers=self._max_workers, thread_name_prefix="cryodaq-analytics")
        # Admission is what bounds concurrency, not the pool's own queue: a
        # submission that would have to wait for a worker is refused instead,
        # so analytics never forms a backlog anywhere.
        self._inflight = 0
        self._lock = threading.Lock()

    @property
    def executor(self) -> ThreadPoolExecutor:
        """The analytics pool. Never the loop's default executor.

        Offered so paths that already own their offload shape (the cooldown
        service runs several separate calls per prediction) can still be bounded
        by the same pool instead of competing for the shared default one.
        """
        return self._executor

    # -- overload state ---------------------------------------------------

    @property
    def overloaded(self) -> bool:
        return self._overloaded

    @property
    def precision(self) -> AnalyticsPrecision:
        """How much work the next admitted calculation may spend."""
        return self._precision

    @property
    def overloaded_since(self) -> float | None:
        return self._overloaded_since

    def observe_lag(self, lag_s: float) -> None:
        """Feed one loop-lag measurement and apply the hysteresis."""
        now = self._clock()
        lag = max(0.0, float(lag_s))
        self._update_precision(lag, now)
        if not self._overloaded:
            if lag >= self._enter_s:
                self._overloaded = True
                self._overloaded_since = now
                self._calm_since = None
                logger.warning(
                    "Аналитика приостановлена: задержка event loop %.2f с (порог %.2f с). "
                    "Приём данных и запись продолжаются.",
                    lag,
                    self._enter_s,
                )
            return
        if lag > self._leave_s:
            # Any excursion back above the low mark restarts the calm window,
            # so recovery means "quiet for a while", not "quiet for an instant".
            self._calm_since = None
            return
        if self._calm_since is None:
            self._calm_since = now
        elif now - self._calm_since >= self._recovery_s:
            held_for = now - (self._overloaded_since or now)
            self._overloaded = False
            self._overloaded_since = None
            self._calm_since = None
            logger.info(
                "Аналитика возобновлена: задержка event loop ниже %.2f с в течение %.0f с "
                "(была приостановлена %.0f с).",
                self._leave_s,
                self._recovery_s,
                held_for,
            )

    def _update_precision(self, lag: float, now: float) -> None:
        """Drop to the cheap form quickly; return to full only after calm.

        Asymmetric on purpose. Degrading has to be immediate, because the point
        is to stop adding load to a loop that is already slipping. Restoring
        full precision waits out the same calm window as overload recovery, so
        a loop hovering near the threshold does not alternate between an exact
        and an approximate answer from one minute to the next.
        """
        if lag >= self._reduce_at_s:
            self._precision_calm_since = None
            if self._precision is not AnalyticsPrecision.REDUCED:
                self._precision = AnalyticsPrecision.REDUCED
                logger.info(
                    "Аналитика переведена в упрощённый режим: задержка event loop %.2f с "
                    "(порог %.2f с). Расчёты продолжаются с меньшей точностью.",
                    lag,
                    self._reduce_at_s,
                )
            return
        if self._precision is AnalyticsPrecision.FULL:
            return
        if self._precision_calm_since is None:
            self._precision_calm_since = now
        elif now - self._precision_calm_since >= self._recovery_s:
            self._precision = AnalyticsPrecision.FULL
            self._precision_calm_since = None
            logger.info("Аналитика вернулась к полной точности.")

    # -- jobs -------------------------------------------------------------

    def register(self, name: str, *, min_interval_s: float) -> None:
        if name in self._jobs:
            raise ValueError(f"analytics job {name!r} is already registered")
        if not min_interval_s >= 0.0:
            raise ValueError("min_interval_s must not be negative")
        self._jobs[name] = _JobState(name=name, min_interval_s=float(min_interval_s))

    def job(self, name: str, *, min_interval_s: float) -> AnalyticsJob:
        self.register(name, min_interval_s=min_interval_s)
        return AnalyticsJob(self, name)

    def status(self, name: str) -> AnalyticsJobStatus:
        state = self._jobs[name]
        return AnalyticsJobStatus(
            name=state.name,
            running=state.running,
            last_result_monotonic=state.last_result_monotonic,
            last_duration_s=state.last_duration_s,
            skipped_overloaded=state.skipped_overloaded,
            skipped_still_running=state.skipped_still_running,
            skipped_too_soon=state.skipped_too_soon,
            skipped_saturated=state.skipped_saturated,
            failures=state.failures,
        )

    def snapshot(self) -> dict[str, Any]:
        """Operator-facing view of the whole analytics tier."""
        now = self._clock()
        return {
            "overloaded": self._overloaded,
            "precision": str(self._precision),
            "overloaded_for_s": (None if self._overloaded_since is None else now - self._overloaded_since),
            "jobs": {
                name: {
                    "running": state.running,
                    "last_duration_s": state.last_duration_s,
                    "stale_s": (None if state.last_result_monotonic is None else now - state.last_result_monotonic),
                    "skipped_overloaded": state.skipped_overloaded,
                    "skipped_still_running": state.skipped_still_running,
                    "skipped_too_soon": state.skipped_too_soon,
                    "skipped_saturated": state.skipped_saturated,
                    "failures": state.failures,
                }
                for name, state in self._jobs.items()
            },
        }

    # -- admission, used by AnalyticsJob ----------------------------------

    def _admit(self, name: str) -> bool:
        with self._lock:
            return self._admit_locked(name)

    def _admit_locked(self, name: str) -> bool:
        state = self._jobs[name]
        now = self._clock()
        if state.running:
            # No queueing, by design. The run in flight will finish against a
            # buffer that already contains everything this attempt would have
            # seen, so waiting behind it would only recompute staler data.
            state.skipped_still_running += 1
            return False
        if self._overloaded:
            state.skipped_overloaded += 1
            return False
        if (
            state.min_interval_s > 0.0
            and state.last_attempt_monotonic is not None
            and (now - state.last_attempt_monotonic) < state.min_interval_s
        ):
            state.skipped_too_soon += 1
            return False
        if self._inflight >= self._max_workers:
            # Every worker is busy. Refusing here is what keeps "analytics never
            # queues" true ACROSS jobs and not merely within one: submitting
            # anyway would park this calculation in the pool's queue behind
            # another, which is a backlog by a different name.
            state.skipped_saturated += 1
            return False
        state.running = True
        state.last_attempt_monotonic = now
        self._inflight += 1
        return True

    def _finish(self, name: str, *, started: float, ok: bool) -> None:
        """Release ownership. Called when the WORKER finishes, never earlier."""
        with self._lock:
            state = self._jobs[name]
            if not state.running:
                return
            state.running = False
            state.inflight = None
            self._inflight = max(0, self._inflight - 1)
            state.last_duration_s = self._clock() - started
            if ok:
                state.last_result_monotonic = self._clock()
            else:
                state.failures += 1

    def inflight_futures(self) -> list[Future]:
        with self._lock:
            return [state.inflight for state in self._jobs.values() if state.inflight is not None]

    async def settle(self, *, timeout_s: float = 30.0) -> bool:
        """Wait for in-flight calculations to finish, for orderly shutdown.

        A cancelled await does not stop a worker thread — the thread runs to
        completion whatever happens to the coroutine that started it. Shutdown
        therefore has to settle them explicitly, or the loop closes while a fit
        is still running and the process hangs on a non-daemon pool thread.
        """
        futures = self.inflight_futures()
        if not futures:
            return True
        done = await asyncio.get_running_loop().run_in_executor(
            None, lambda: all(_wait_for(future, timeout_s) for future in futures)
        )
        return bool(done)

    def shutdown(self, *, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=not wait)


class AnalyticsJob:
    """One best-effort calculation, bounded and observable.

    ``run`` executes the work off the event loop and returns None when the
    attempt was refused — overloaded, already running, or too soon. A refusal
    is an ordinary outcome, not an error: the caller keeps its previous result
    and the operator can see it is stale.
    """

    def __init__(self, admission: AnalyticsAdmission, name: str) -> None:
        self._admission = admission
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def status(self) -> AnalyticsJobStatus:
        return self._admission.status(self._name)

    def try_begin(self) -> bool:
        """Claim the job for async-shaped work; pair with ``end``.

        ``run`` is the safe path and should be preferred: it ties ownership to
        the worker, so a cancelled caller cannot re-admit. This exists for work
        that is not one synchronous callable — a prediction that offloads twice
        and publishes to the broker between. The caller owns the pairing, and
        must release in a ``finally``.
        """
        return self._admission._admit(self._name)

    def end(self, *, ok: bool, started: float) -> None:
        self._admission._finish(self._name, started=started, ok=ok)

    async def run(self, work: Callable[[], T]) -> T | None:
        """Run ``work`` on the analytics pool if admitted; otherwise skip it.

        Ownership is released when the WORKER finishes, not when this coroutine
        stops awaiting. Cancelling the caller does not stop a thread that has
        already started, so clearing the flag in a ``finally`` re-admitted the
        job while its previous worker was still running — two concurrent
        workers for a job whose entire contract is single-flight.
        """
        admission = self._admission
        if not admission._admit(self._name):
            return None
        started = time.monotonic()
        loop = asyncio.get_running_loop()
        future = admission._executor.submit(work)
        with admission._lock:
            admission._jobs[self._name].inflight = future

        def _release(completed: Future) -> None:
            failed = completed.cancelled() or completed.exception() is not None
            admission._finish(self._name, started=started, ok=not failed)

        future.add_done_callback(_release)
        try:
            return await asyncio.wrap_future(future, loop=loop)
        except asyncio.CancelledError:
            # The worker keeps running and still releases ownership through the
            # done callback; shutdown settles it via AnalyticsAdmission.settle().
            raise
        except Exception:
            logger.warning("Аналитика %s: расчёт завершился ошибкой", self._name, exc_info=True)
            return None
