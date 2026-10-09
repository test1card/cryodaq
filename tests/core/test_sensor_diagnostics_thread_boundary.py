"""Sensor diagnostics may compute off the event loop, but not mutate off it.

The tick moved the recomputation into a worker thread because inlining a
250 ms pairwise correlation cost acquisition an entire observation window. What
crossed with it was the whole of ``update``: the diagnostics cache, the anomaly
timers, and every AlarmStateManager transition. Those belong to the event loop.

Two independent defects are covered:

* ``push`` appended to the deque OUTSIDE the lock that ``snapshot_buffers``
  copies under, so a copy concurrent with acquisition raises "deque mutated
  during iteration";
* the alarm publisher was driven from the worker thread.
"""

import asyncio
import sys
import threading

import pytest


@pytest.fixture
def forced_thread_interleaving():
    """Make the GIL switch often enough for the race to be deterministic.

    The unguarded read is a Python-level comprehension over a live deque. At
    the default 5 ms switch interval it completes inside a single slice, so the
    producer thread almost never lands in the middle of it and the defect hides
    -- these tests passed against the unfixed code until this was added. A
    microsecond interval forces the interleaving that a loaded engine produces
    on its own.
    """

    original = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        yield
    finally:
        sys.setswitchinterval(original)

from cryodaq.core.sensor_diagnostics import SensorDiagnosticsEngine


class _RecordingPublisher:
    """Records the thread every alarm mutation is made from."""

    def __init__(self) -> None:
        self.threads: set[int] = set()

    def publish_diagnostic_alarm(self, channel_id, level, elapsed):
        self.threads.add(threading.get_ident())
        return None

    def clear_diagnostic_alarm(self, channel_id):
        self.threads.add(threading.get_ident())
        return None


GROUP = ["Т1", "Т2", "Т3", "Т4"]


def _worker_entry(engine: SensorDiagnosticsEngine):
    """Whatever this version runs in the analytics worker.

    Before the split that was ``update``; now it is ``compute``. Naming it this
    way lets the race tests run unchanged against both, which is what makes
    them evidence rather than assertion.
    """
    return getattr(engine, "compute", None) or engine.update


def _engine(publisher=None) -> SensorDiagnosticsEngine:
    engine = SensorDiagnosticsEngine(
        config={
            "min_points": 3,
            "noise_window_s": 60,
            "drift_window_s": 60,
            "corr_window_s": 600,
            # Correlation must be reachable: with no group the pairwise path
            # returns immediately and never reads a neighbour's buffer, which
            # is precisely where the unguarded read lives.
            "correlation_groups": {"stage": GROUP},
        },
        alarm_publisher=publisher,
    )
    # Score them as cryogenic so the full compute path runs, not the warm-ref
    # short circuit.
    engine.set_channel_cold_map({f"Т{i}": True for i in range(1, 9)})
    return engine


def _fill(engine: SensorDiagnosticsEngine, channels=("Т1", "Т2"), count=200) -> None:
    for index in range(count):
        for offset, channel in enumerate(channels):
            engine.push(channel, 1_000_000.0 + index, 4.2 + 0.001 * index + offset)


# ---------------------------------------------------------------------------
# The lock must cover the mutation, not just the lookup
# ---------------------------------------------------------------------------


def test_a_snapshot_concurrent_with_acquisition_does_not_raise(forced_thread_interleaving):
    """push() on one thread, snapshot_buffers() on another, repeatedly.

    The buffers are filled deeply on purpose. The race is between an append and
    the ``list(buffer)`` inside the snapshot, so the window is exactly as long
    as that copy takes: with a few dozen samples it is too short to hit
    reliably, and the test would pass against the unfixed code. At the depth a
    real run reaches, an unguarded append is caught every time.
    """
    engine = _engine()
    _fill(engine, channels=("Т1", "Т2", "Т3", "Т4"), count=5000)
    failures: list[BaseException] = []
    stop = threading.Event()

    def producer() -> None:
        index = 0
        while not stop.is_set():
            try:
                for channel in ("Т1", "Т2", "Т3", "Т4"):
                    engine.push(channel, 2_000_000.0 + index, 4.2)
            except BaseException as exc:  # noqa: BLE001 - the test is the assertion
                failures.append(exc)
                return
            index += 1

    thread = threading.Thread(target=producer, daemon=True)
    thread.start()
    try:
        for _ in range(2000):
            try:
                engine.snapshot_buffers()
            except BaseException as exc:  # noqa: BLE001
                failures.append(exc)
                break
    finally:
        stop.set()
        thread.join(timeout=5)

    assert not failures, f"concurrent push/snapshot raised {failures[0]!r}"


def test_compute_concurrent_with_acquisition_does_not_raise(forced_thread_interleaving):
    """The real worker path, not just the copy."""
    engine = _engine()
    _fill(engine, channels=tuple(GROUP), count=4000)
    failures: list[BaseException] = []
    stop = threading.Event()
    worker = _worker_entry(engine)

    def producer() -> None:
        index = 0
        while not stop.is_set():
            try:
                for channel in GROUP:
                    engine.push(channel, 3_000_000.0 + index, 4.2 + 0.0001 * index)
            except BaseException as exc:  # noqa: BLE001
                failures.append(exc)
                return
            index += 1

    thread = threading.Thread(target=producer, daemon=True)
    thread.start()
    try:
        for _ in range(30):
            try:
                worker()
            except BaseException as exc:  # noqa: BLE001
                failures.append(exc)
                break
    finally:
        stop.set()
        thread.join(timeout=5)

    assert not failures, f"the analytics worker racing acquisition raised {failures[0]!r}"


# ---------------------------------------------------------------------------
# Alarm state is mutated by the event loop, never by the worker
# ---------------------------------------------------------------------------


def test_compute_touches_no_shared_state():
    publisher = _RecordingPublisher()
    engine = _engine(publisher)
    _fill(engine)

    before = dict(engine.get_diagnostics())
    computed = engine.compute()

    assert computed, "compute produced nothing to apply"
    assert publisher.threads == set(), "compute reached the alarm publisher"
    assert dict(engine.get_diagnostics()) == before, "compute mutated the diagnostics cache"


@pytest.mark.asyncio
async def test_alarm_mutation_happens_on_the_event_loop():
    """compute() in a worker, apply() on the loop: the production sequence."""
    publisher = _RecordingPublisher()
    engine = _engine(publisher)
    _fill(engine)
    engine.mark_engine_started()

    loop_thread = threading.get_ident()
    computed = await asyncio.to_thread(engine.compute)
    worker_threads = set(publisher.threads)
    engine.apply(computed)

    assert worker_threads == set(), "the worker mutated alarm state"
    assert publisher.threads <= {loop_thread}, (
        f"alarm state mutated off the event loop from {publisher.threads - {loop_thread}}"
    )
    assert engine.get_diagnostics(), "apply published nothing"


@pytest.mark.asyncio
async def test_apply_publishes_what_the_worker_computed():
    engine = _engine()
    _fill(engine)
    computed = await asyncio.to_thread(engine.compute)
    engine.apply(computed)
    published = engine.get_diagnostics()
    assert set(published) == {channel for channel, diag in computed.items() if diag is not None}


def test_a_channel_that_lost_its_samples_drops_its_cached_result():
    engine = _engine()
    _fill(engine)
    engine.apply(engine.compute())
    assert "Т1" in engine.get_diagnostics()
    engine.apply({"Т1": None})
    assert "Т1" not in engine.get_diagnostics(), "stale diagnostics survived a no_data tick"
