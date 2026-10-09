"""Acquisition always runs; analytics runs only when it is given resource.

The rule these tests hold in place was written after 2026-09-01 02:39, when a
vacuum curve fit ran inline on the event loop, blocked it for ~8 s, and cost a
running cryostat 6 h 46 min of temperature data.
"""

import asyncio
import threading
import time

# Imported before anything that reaches cryodaq.storage: on this conda
# environment the system libstdc++ is loaded first otherwise, and the sqlite3
# extension then fails with a missing CXXABI. numpy pulls conda's own C++
# runtime in first, which is enough to fix the order.
import numpy  # noqa: F401
import pytest

from cryodaq.core.analytics_admission import (
    AnalyticsAdmission,
    AnalyticsPrecision,
    LoopLagMonitor,
)


def _admission(**overrides):
    settings = {
        "enter_overload_s": 0.5,
        "leave_overload_s": 0.15,
        "reduce_at_s": 0.2,
        "recovery_s": 1.0,
    }
    settings.update(overrides)
    return AnalyticsAdmission(**settings)


# ---------------------------------------------------------------------------
# The property that matters: a hung analytic must not stop acquisition
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_hung_analytic_does_not_delay_acquisition_or_persistence():
    """The incident, reproduced as a test.

    An analytic that never returns must not cost a single acquisition cycle or
    a single commit. Previously the equivalent work ran inline, so a stalled
    calculation stopped instrument polling, persistence and every timer at once.
    """
    admission = _admission()
    job = admission.job("wedged", min_interval_s=0.0)

    acquired: list[float] = []
    committed: list[float] = []
    release = asyncio.Event()

    async def acquisition() -> None:
        while True:
            acquired.append(time.monotonic())
            committed.append(time.monotonic())
            await asyncio.sleep(0.01)

    def wedged() -> str:
        # Blocking, in a worker thread, for far longer than the test runs.
        while not release.is_set():
            time.sleep(0.01)
        return "eventually"

    poller = asyncio.create_task(acquisition())
    analytics = asyncio.create_task(job.run(wedged))
    try:
        await asyncio.sleep(0.4)
        assert admission.status("wedged").running, "the analytic should still be stuck"
        # ~40 cycles at 10 ms; assert generously to stay stable under load.
        assert len(acquired) > 15, f"acquisition stalled: only {len(acquired)} cycles"
        assert len(committed) == len(acquired)
    finally:
        release.set()
        poller.cancel()
        await analytics
        with pytest.raises(asyncio.CancelledError):
            await poller


@pytest.mark.asyncio
async def test_a_failing_analytic_is_recorded_and_does_not_propagate():
    admission = _admission()
    job = admission.job("broken", min_interval_s=0.0)

    def explode() -> None:
        raise RuntimeError("fit did not converge")

    assert await job.run(explode) is None
    status = admission.status("broken")
    assert status.failures == 1
    assert status.running is False
    assert status.last_result_monotonic is None


# ---------------------------------------------------------------------------
# Jobs must not accumulate, and recovery must use the freshest data
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recomputes_do_not_queue_behind_a_slow_run():
    admission = _admission()
    job = admission.job("slow", min_interval_s=0.0)
    release = asyncio.Event()
    starts = 0

    def slow() -> str:
        nonlocal starts
        starts += 1
        while not release.is_set():
            time.sleep(0.005)
        return "done"

    first = asyncio.create_task(job.run(slow))
    await asyncio.sleep(0.05)
    # Five more ticks fire while the first is still running.
    refused = [await job.run(slow) for _ in range(5)]
    assert refused == [None] * 5, "a run in flight must refuse, not queue"
    assert starts == 1, "no second instance may start"
    assert admission.status("slow").skipped_still_running == 5

    release.set()
    assert await first == "done"


@pytest.mark.asyncio
async def test_the_run_after_a_skip_sees_the_latest_data():
    """Skipping drops the computation, never the data.

    Input keeps arriving at full rate while a recompute is refused, so the next
    admitted run reads everything that accumulated meanwhile — which is the
    whole reason skipping beats queueing.
    """
    admission = _admission()
    job = admission.job("fit", min_interval_s=0.0)
    samples: list[int] = []
    seen: list[int] = []
    release = asyncio.Event()

    def fit() -> int:
        while not release.is_set():
            time.sleep(0.005)
        seen.append(len(samples))
        return len(samples)

    samples.extend(range(10))
    first = asyncio.create_task(job.run(fit))
    await asyncio.sleep(0.05)

    samples.extend(range(90))  # input continues at full rate
    assert await job.run(fit) is None  # refused while the first is in flight
    release.set()
    await first

    release.clear()
    samples.extend(range(100))
    release.set()
    assert await job.run(fit) == 200, "the next run must see every sample that arrived"


# ---------------------------------------------------------------------------
# The ladder: degrade before dropping, and do not flap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_precision_degrades_before_runs_are_refused():
    admission = _admission()
    job = admission.job("fit", min_interval_s=0.0)

    assert admission.precision is AnalyticsPrecision.FULL
    assert await job.run(lambda: "full") == "full"

    admission.observe_lag(0.25)  # slipping: cheaper, still runs
    assert admission.precision is AnalyticsPrecision.REDUCED
    assert admission.overloaded is False
    assert await job.run(lambda: "cheap") == "cheap"

    admission.observe_lag(0.9)  # overloaded: refuse outright
    assert admission.overloaded is True
    assert await job.run(lambda: "never") is None


def test_recovery_needs_sustained_calm_not_one_quiet_sample():
    admission = _admission(recovery_s=10.0)
    admission.observe_lag(0.9)
    assert admission.overloaded

    admission.observe_lag(0.01)
    assert admission.overloaded, "one quiet sample is not recovery"

    # An excursion back up restarts the calm window.
    admission.observe_lag(0.4)
    admission.observe_lag(0.01)
    assert admission.overloaded


def test_lag_between_the_thresholds_does_not_flap():
    admission = _admission()
    admission.observe_lag(0.9)
    assert admission.overloaded
    for _ in range(20):
        admission.observe_lag(0.3)  # below enter, above leave
        assert admission.overloaded, "hysteresis gap must hold the state"


def test_thresholds_must_be_ordered():
    with pytest.raises(ValueError):
        AnalyticsAdmission(enter_overload_s=0.1, leave_overload_s=0.5)
    with pytest.raises(ValueError):
        AnalyticsAdmission(enter_overload_s=0.5, leave_overload_s=0.15, reduce_at_s=0.9)


# ---------------------------------------------------------------------------
# Visibility: a skipped recompute is a fact, not a silence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_reports_staleness_and_skips():
    admission = _admission()
    job = admission.job("fit", min_interval_s=0.0)
    assert admission.status("fit").staleness_s() is None

    await job.run(lambda: "ok")
    assert admission.status("fit").staleness_s() < 1.0

    admission.observe_lag(0.9)
    await job.run(lambda: "never")
    await job.run(lambda: "never")

    snapshot = admission.snapshot()
    assert snapshot["overloaded"] is True
    assert snapshot["precision"] == "reduced"
    assert snapshot["jobs"]["fit"]["skipped_overloaded"] == 2
    assert snapshot["jobs"]["fit"]["stale_s"] is not None


@pytest.mark.asyncio
async def test_min_interval_throttles_recomputes():
    admission = _admission()
    job = admission.job("fit", min_interval_s=60.0)
    assert await job.run(lambda: "first") == "first"
    assert await job.run(lambda: "too soon") is None
    assert admission.status("fit").skipped_too_soon == 1


# ---------------------------------------------------------------------------
# The probe
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_probe_measures_a_real_stall():
    monitor = LoopLagMonitor(interval_s=0.02)
    admission = _admission()
    monitor.subscribe(admission.observe_lag)
    task = asyncio.create_task(monitor.run())
    try:
        await asyncio.sleep(0.1)
        assert monitor.lag_s < 0.2, "an idle loop must not look stalled"
        # Blocking the loop on purpose: this is the failure being measured,
        # not an accident. ASYNC251 is exactly the rule the probe exists to catch.
        time.sleep(0.6)  # noqa: ASYNC251
        await asyncio.sleep(0.05)
        assert monitor.peak_lag_s > 0.4, "the probe must see the stall it slept through"
        assert admission.overloaded, "and the stall must pause analytics"
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


def test_peak_is_reported_then_reset():
    monitor = LoopLagMonitor()
    monitor.observe(1.5)
    monitor.observe(0.01)
    assert monitor.take_peak() == pytest.approx(1.5)
    assert monitor.take_peak() == pytest.approx(0.01), "peak resets to the current value"


# ---------------------------------------------------------------------------
# The production tick paths, not just the primitive
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slow_sensor_diagnostics_does_not_cost_acquisition_cycles():
    """A 250 ms diagnostics call must not shrink the acquisition window.

    Reported against the first version of this work: sensor_diag_tick called
    update() inline, so a 250 ms diagnostics pass reduced the same observation
    window to a single scheduler read and a single SQLite write, and delayed
    safety monitoring and alarm evaluation with it.
    """
    from cryodaq.engine_wiring.runtime_tasks import sensor_diag_tick

    admission = AnalyticsAdmission(max_workers=2)
    reads: list[int] = []
    writes: list[int] = []
    calls = 0
    applied_on: list[int] = []

    class _SlowDiagnostics:
        """The worker/loop split the tick actually drives.

        `compute` is the slow, pure half and runs in a worker. `apply` is the
        half that mutates alarm state and must run on the event loop, so it
        records the thread it was called from.
        """

        def compute(self):
            nonlocal calls
            calls += 1
            time.sleep(0.25)  # noqa: ASYNC251 - deliberately slow, in a worker
            return {}

        def apply(self, computed):
            applied_on.append(threading.get_ident())
            return []

    async def acquisition() -> None:
        while True:
            reads.append(1)
            writes.append(1)
            await asyncio.sleep(0.01)

    poller = asyncio.create_task(acquisition())
    tick = asyncio.create_task(
        sensor_diag_tick(
            sensor_diag=_SlowDiagnostics(),
            sd_cfg={"update_interval_s": 0.05, "notify_telegram": False},
            telegram_bot=None,
            alarm_dispatch_tasks=set(),
            event_bus=None,
            experiment_manager=None,
            admission=admission,
        )
    )
    try:
        await asyncio.sleep(1.0)
        # ~100 cycles at 10 ms. Asserted generously; the failure being guarded
        # against produced ONE.
        assert len(reads) > 40, f"acquisition starved: {len(reads)} reads in 1 s"
        assert len(writes) == len(reads)
        assert calls >= 1, "diagnostics should still have run"
        assert applied_on, "the loop never applied what the worker computed"
        assert set(applied_on) == {threading.get_ident()}, (
            "alarm-bearing apply() ran off the event loop"
        )
    finally:
        tick.cancel()
        poller.cancel()
        for task in (tick, poller):
            with pytest.raises(asyncio.CancelledError):
                await task
        admission.shutdown(wait=False)


@pytest.mark.asyncio
async def test_a_cancelled_analytic_keeps_its_slot_until_the_worker_stops():
    """Cancelling the caller does not stop the thread, so it must not re-admit.

    Reported: the finally block cleared `running` on cancellation while the
    worker kept going, and a readmitted job then ran a second worker for a
    calculation whose whole contract is single-flight.
    """
    admission = AnalyticsAdmission(max_workers=4)
    job = admission.job("fit", min_interval_s=0.0)
    release = threading.Event()
    peak = 0
    live = 0
    guard = threading.Lock()

    def work() -> str:
        nonlocal peak, live
        with guard:
            live += 1
            peak = max(peak, live)
        while not release.is_set():
            time.sleep(0.005)
        with guard:
            live -= 1
        return "done"

    first = asyncio.create_task(job.run(work))
    await asyncio.sleep(0.1)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    await asyncio.sleep(0.05)
    assert admission.status("fit").running, "ownership must follow the worker, not the await"
    assert await job.run(work) is None, "must not re-admit while the worker runs"

    release.set()
    await asyncio.sleep(0.2)
    assert peak == 1, f"single-flight violated: {peak} concurrent workers"
    assert not admission.status("fit").running
    admission.shutdown(wait=False)


@pytest.mark.asyncio
async def test_analytics_never_queues_in_a_shared_executor():
    """Concurrency is bounded by admission, not by a pool queue.

    Reported: jobs were single-flight only against themselves, and different
    analytics could all be admitted into the loop's default executor — shared
    with other engine work — and queue there once it saturated, while loop lag
    stayed low and nothing looked wrong.
    """
    admission = AnalyticsAdmission(max_workers=2)
    jobs = [admission.job(f"job{index}", min_interval_s=0.0) for index in range(5)]
    release = threading.Event()
    peak = 0
    live = 0
    guard = threading.Lock()

    def work() -> str:
        nonlocal peak, live
        with guard:
            live += 1
            peak = max(peak, live)
        while not release.is_set():
            time.sleep(0.005)
        with guard:
            live -= 1
        return "done"

    tasks = [asyncio.create_task(job.run(work)) for job in jobs]
    try:
        await asyncio.sleep(0.3)
        admitted = sum(1 for job in jobs if admission.status(job.name).running)
        refused = sum(admission.status(job.name).skipped_saturated for job in jobs)
        assert admitted == 2, f"admitted {admitted}, pool holds 2"
        assert refused == 3, "the rest must be refused, not queued"
        assert peak <= 2
    finally:
        release.set()
        await asyncio.gather(*tasks)
        admission.shutdown(wait=False)


@pytest.mark.asyncio
async def test_settle_waits_for_workers_so_shutdown_does_not_hang():
    admission = AnalyticsAdmission(max_workers=2)
    job = admission.job("fit", min_interval_s=0.0)
    release = threading.Event()

    def work() -> str:
        while not release.is_set():
            time.sleep(0.005)
        return "done"

    task = asyncio.create_task(job.run(work))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert admission.inflight_futures(), "the worker is still owned"
    release.set()
    assert await admission.settle(timeout_s=5.0) is True
    assert not admission.inflight_futures()
    admission.shutdown(wait=False)
