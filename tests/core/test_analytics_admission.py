"""Acquisition always runs; analytics runs only when it is given resource.

The rule these tests hold in place was written after 2026-09-01 02:39, when a
vacuum curve fit ran inline on the event loop, blocked it for ~8 s, and cost a
running cryostat 6 h 46 min of temperature data.
"""

import asyncio
import time

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

    samples.extend(range(90))          # input continues at full rate
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

    admission.observe_lag(0.25)   # slipping: cheaper, still runs
    assert admission.precision is AnalyticsPrecision.REDUCED
    assert admission.overloaded is False
    assert await job.run(lambda: "cheap") == "cheap"

    admission.observe_lag(0.9)    # overloaded: refuse outright
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
        admission.observe_lag(0.3)   # below enter, above leave
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
        time.sleep(0.6)            # block the loop exactly as a bad analytic would
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
