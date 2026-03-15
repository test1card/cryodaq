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
