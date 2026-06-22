"""Tests for Scheduler — registration, polling, stats, and graceful stop."""

from __future__ import annotations

import asyncio

import pytest

from cryodaq.core.broker import DataBroker
from cryodaq.core.scheduler import InstrumentConfig, Scheduler
from cryodaq.drivers.base import InstrumentDriver, Reading

# ---------------------------------------------------------------------------
# Concrete mock driver for use in all scheduler tests
# ---------------------------------------------------------------------------


class MockDriver(InstrumentDriver):
    """Minimal concrete driver: connect sets flag, read returns one reading."""

    def __init__(self, name: str = "mock_instrument") -> None:
        super().__init__(name, mock=True)
        self.connect_calls: int = 0
        self.disconnect_calls: int = 0
        self.read_calls: int = 0

    async def connect(self) -> None:
        self.connect_calls += 1
        self._connected = True

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        self._connected = False

    async def read_channels(self) -> list[Reading]:
        self.read_calls += 1
        return [Reading.now("CH1", 4.2, "K", instrument_id="test")]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def broker() -> DataBroker:
    return DataBroker()


@pytest.fixture()
def scheduler(broker: DataBroker) -> Scheduler:
    return Scheduler(broker)


# ---------------------------------------------------------------------------
# 1. add() registers the instrument by driver name
# ---------------------------------------------------------------------------


async def test_add_instrument(scheduler: Scheduler) -> None:
    driver = MockDriver("ls218s")
    config = InstrumentConfig(driver=driver, poll_interval_s=1.0)
    scheduler.add(config)

    assert "ls218s" in scheduler.stats


# ---------------------------------------------------------------------------
# 2. Mock driver is polled and readings reach the broker
# ---------------------------------------------------------------------------


async def test_mock_driver_polled(broker: DataBroker) -> None:
    queue = await broker.subscribe("test_consumer", maxsize=100)

    driver = MockDriver("poller")
    sched = Scheduler(broker)
    sched.add(InstrumentConfig(driver=driver, poll_interval_s=0.01))

    await sched.start()
    # Wait deterministically for the first reading to arrive (no fixed sleep)
    reading = await asyncio.wait_for(queue.get(), timeout=2.0)
    await sched.stop()

    assert reading.channel == "CH1"
    assert abs(reading.value - 4.2) < 1e-9


# ---------------------------------------------------------------------------
# 3. Registering the same driver name twice raises ValueError
# ---------------------------------------------------------------------------


async def test_duplicate_driver_rejected(scheduler: Scheduler) -> None:
    driver_a = MockDriver("duplicate")
    driver_b = MockDriver("duplicate")

    scheduler.add(InstrumentConfig(driver=driver_a))

    with pytest.raises(ValueError, match="duplicate"):
        scheduler.add(InstrumentConfig(driver=driver_b))


# ---------------------------------------------------------------------------
# 4. stats.total_reads increases after polling
# ---------------------------------------------------------------------------


async def test_stats_track_reads(broker: DataBroker) -> None:
    await broker.subscribe("stats_consumer", maxsize=1000)

    driver = MockDriver("stats_driver")
    sched = Scheduler(broker)
    sched.add(InstrumentConfig(driver=driver, poll_interval_s=0.01))

    await sched.start()
    await asyncio.sleep(0.15)
    await sched.stop()

    assert sched.stats["stats_driver"]["total_reads"] > 0


# ---------------------------------------------------------------------------
# 5. stop() cancels tasks and disconnects drivers
# ---------------------------------------------------------------------------


async def test_graceful_stop(broker: DataBroker) -> None:
    await broker.subscribe("stop_consumer", maxsize=100)

    driver = MockDriver("stoppable")
    sched = Scheduler(broker)
    sched.add(InstrumentConfig(driver=driver, poll_interval_s=0.01))

    await sched.start()
    await asyncio.sleep(0.05)
    await sched.stop()

    # Driver must have been disconnected by stop()
    assert not driver.connected
    assert driver.disconnect_calls >= 1

    # All tasks must be cancelled/done — no lingering tasks in the scheduler
    states = list(sched._instruments.values())
    for state in states:
        assert state.task is None or state.task.done()


# ---------------------------------------------------------------------------
# 6. GPIB instruments on same bus share one task; non-GPIB get their own
# ---------------------------------------------------------------------------


async def test_gpib_bus_grouping(broker: DataBroker) -> None:
    await broker.subscribe("gpib_consumer", maxsize=1000)

    ls1 = MockDriver("ls218_1")
    ls2 = MockDriver("ls218_2")
    usb_driver = MockDriver("keithley")

    sched = Scheduler(broker)
    sched.add(InstrumentConfig(driver=ls1, poll_interval_s=0.01, resource_str="GPIB0::12::INSTR"))
    sched.add(InstrumentConfig(driver=ls2, poll_interval_s=0.01, resource_str="GPIB0::11::INSTR"))
    sched.add(InstrumentConfig(driver=usb_driver, poll_interval_s=0.01, resource_str="USB0::MOCK"))

    await sched.start()

    # Both GPIB instruments must share the same task
    ls1_task = sched._instruments["ls218_1"].task
    ls2_task = sched._instruments["ls218_2"].task
    usb_task = sched._instruments["keithley"].task

    assert ls1_task is ls2_task, "GPIB instruments on same bus must share one task"
    assert usb_task is not ls1_task, "Non-GPIB instrument must have its own task"

    await asyncio.sleep(0.1)
    await sched.stop()

    # Both GPIB instruments must have been polled
    assert ls1.read_calls > 0
    assert ls2.read_calls > 0
    assert usb_driver.read_calls > 0


async def test_gpib_sequential_connect(broker: DataBroker) -> None:
    """GPIB instruments must connect sequentially in one task, not in parallel.

    Asserts max concurrent connects == 1 (overlap counter), which catches a
    parallel-connect regression that the original order-only check would miss.
    """
    await broker.subscribe("seq_consumer", maxsize=1000)

    connect_order: list[str] = []
    concurrent_count = 0
    max_concurrent = 0

    class OrderedDriver(MockDriver):
        async def connect(self) -> None:
            nonlocal concurrent_count, max_concurrent
            concurrent_count += 1
            max_concurrent = max(max_concurrent, concurrent_count)
            connect_order.append(self.name)
            await asyncio.sleep(0.02)  # small delay so overlap is detectable
            await super().connect()
            concurrent_count -= 1

    d1 = OrderedDriver("gpib_first")
    d2 = OrderedDriver("gpib_second")

    sched = Scheduler(broker)
    sched.add(InstrumentConfig(driver=d1, poll_interval_s=0.05, resource_str="GPIB0::12::INSTR"))
    sched.add(InstrumentConfig(driver=d2, poll_interval_s=0.05, resource_str="GPIB0::11::INSTR"))

    await sched.start()
    await asyncio.sleep(0.3)
    await sched.stop()

    # Both must have connected
    assert "gpib_first" in connect_order, f"gpib_first never connected; order={connect_order}"
    assert "gpib_second" in connect_order, f"gpib_second never connected; order={connect_order}"
    # Sequential invariant: at no point were two connects in-flight simultaneously
    assert max_concurrent == 1, (
        f"GPIB connects must be sequential (max concurrent=1), got {max_concurrent}. "
        f"connect_order={connect_order}"
    )


# ---------------------------------------------------------------------------
# Phase 2d B-2.3: P1 — graceful drain
# ---------------------------------------------------------------------------


async def test_stop_graceful_drain_completes_inflight():
    """P1: stop() graceful drain must let in-flight polls finish.

    The driver's read_channels signals that it has started (read_started event),
    then blocks on a release_event. stop() is called while the read is blocked.
    The test releases the block before the drain timeout, then verifies:
    - the poll completed (read completed without CancelledError)
    - disconnect was called (clean teardown, not forced cancel)
    This is distinct from test_stop_drain_timeout_forces_cancel (:235) which
    tests the force-cancel path — do NOT weaken that test.
    """
    read_started = asyncio.Event()
    release_read = asyncio.Event()
    read_completed = False

    class BlockingUntilReleased(MockDriver):
        async def read_channels(self) -> list[Reading]:
            nonlocal read_completed
            read_started.set()
            await release_read.wait()
            read_completed = True
            return [Reading.now("CH1", 4.2, "K", instrument_id="test")]

    broker = DataBroker()
    sched = Scheduler(broker=broker, sqlite_writer=None, drain_timeout_s=2.0)
    driver = BlockingUntilReleased("drainer")
    sched.add(InstrumentConfig(driver=driver, poll_interval_s=0.05, resource_str="mock"))

    await sched.start()

    # Wait until the driver is actually in the middle of a read
    await asyncio.wait_for(read_started.wait(), timeout=2.0)
    assert not read_completed, "Read must be in-flight (blocked) when stop() is called"

    # Call stop() — drain should wait for the in-flight read to finish
    stop_task = asyncio.create_task(sched.stop())

    # Release the blocked read so drain can complete within its timeout
    release_read.set()
    await asyncio.wait_for(stop_task, timeout=3.0)

    # Drain completed: read finished naturally (not force-cancelled)
    assert read_completed, "In-flight read must complete during graceful drain"
    assert driver._connected is False, "Driver must be disconnected after stop()"
    assert driver.disconnect_calls >= 1, "disconnect() must be called during stop()"


async def test_stop_drain_timeout_forces_cancel():
    """P1: if a poll is stuck mid-read past the drain timeout, stop() must escalate
    to a forced cancel. Uses the REAL drain_timeout_s ctor param (production reads
    self._drain_timeout_s, not the _DRAIN_TIMEOUT_S a prior test set) and a driver
    whose read blocks, so the timeout→cancel path actually executes."""

    class BlockingDriver(MockDriver):
        def __init__(self, name: str) -> None:
            super().__init__(name)
            self.read_started = False
            self.cancelled = False

        async def read_channels(self) -> list[Reading]:
            self.read_started = True
            try:
                await asyncio.sleep(30)  # block well past the drain timeout
            except asyncio.CancelledError:
                self.cancelled = True
                raise
            return [Reading.now("CH1", 4.2, "K", instrument_id="test")]

    broker = DataBroker()
    sched = Scheduler(broker=broker, sqlite_writer=None, drain_timeout_s=0.05)

    driver = BlockingDriver("slow")
    sched.add(InstrumentConfig(driver=driver, poll_interval_s=0.01, resource_str="mock"))

    await sched.start()
    await asyncio.sleep(0.1)  # let the poll enter the blocking read
    assert driver.read_started, "poll must be in-flight for the drain path to matter"

    await sched.stop()  # drain times out → forced cancel

    # The stuck poll was force-cancelled, and the instrument was disconnected.
    assert driver.cancelled, "drain timeout must escalate to task.cancel()"
    assert driver.disconnect_calls >= 1
    assert driver._connected is False
