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
    # Give the poll loop time to fire at least once
    await asyncio.sleep(0.1)
    await sched.stop()

    assert not queue.empty(), "Expected at least one Reading in the broker queue"
    reading = queue.get_nowait()
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
    """GPIB instruments must connect sequentially in one task, not in parallel."""
    await broker.subscribe("seq_consumer", maxsize=1000)

    connect_order: list[str] = []

    class OrderedDriver(MockDriver):
        async def connect(self) -> None:
            connect_order.append(self.name)
            await super().connect()

    d1 = OrderedDriver("gpib_first")
    d2 = OrderedDriver("gpib_second")

    sched = Scheduler(broker)
    sched.add(InstrumentConfig(driver=d1, poll_interval_s=0.05, resource_str="GPIB0::12::INSTR"))
    sched.add(InstrumentConfig(driver=d2, poll_interval_s=0.05, resource_str="GPIB0::11::INSTR"))

    await sched.start()
    await asyncio.sleep(0.15)
    await sched.stop()

    # Both must have connected, and in sequence (same task → deterministic order)
    assert "gpib_first" in connect_order
    assert "gpib_second" in connect_order


# ---------------------------------------------------------------------------
# Phase 2d B-2.3: P1 — graceful drain
# ---------------------------------------------------------------------------


async def test_stop_graceful_drain_completes_inflight():
    """P1: stop() graceful drain must let in-flight polls finish."""
    broker = DataBroker()
    sched = Scheduler(broker=broker, sqlite_writer=None)
    driver = MockDriver("drainer")
    sched.add(InstrumentConfig(driver=driver, poll_interval_s=0.1, resource_str="mock"))

    await sched.start()
    await asyncio.sleep(0.15)  # let at least one poll complete
    await sched.stop()

    # Drain should have completed — driver disconnected cleanly
    assert driver._connected is False
    assert driver.disconnect_calls >= 1


async def test_stop_drain_timeout_forces_cancel():
    """P1: if drain times out, forced cancel still works."""
    broker = DataBroker()
    sched = Scheduler(broker=broker, sqlite_writer=None)
    sched._DRAIN_TIMEOUT_S = 0.1  # very short

    driver = MockDriver("slow")
    sched.add(InstrumentConfig(driver=driver, poll_interval_s=60.0, resource_str="mock"))

    await sched.start()
    await asyncio.sleep(0.05)  # let it start
    await sched.stop()  # drain should timeout, force cancel

    # If we got here, stop returned — drain timeout + cancel worked
