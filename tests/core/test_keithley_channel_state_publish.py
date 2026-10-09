from __future__ import annotations

import asyncio

from cryodaq.core.broker import DataBroker
from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager
from cryodaq.drivers.base import Reading


async def _make_manager(*, data_broker: DataBroker):
    safety_broker = SafetyBroker()
    manager = SafetyManager(safety_broker, mock=True, data_broker=data_broker)
    manager._config.cooldown_before_rearm_s = 0.1
    await manager.start()
    return manager, safety_broker


async def _drain(queue: asyncio.Queue, timeout: float = 0.2) -> list[Reading]:  # noqa: ASYNC109
    readings: list[Reading] = []
    while True:
        try:
            readings.append(await asyncio.wait_for(queue.get(), timeout=timeout))
        except TimeoutError:
            break
    return readings


async def test_initial_channel_state_publish_is_off_for_both() -> None:
    data_broker = DataBroker()
    queue = await data_broker.subscribe(
        "test_keithley_channel_state_initial",
        maxsize=100,
        filter_fn=lambda reading: reading.channel.startswith("analytics/keithley_channel_state/"),
    )
    manager, safety_broker = await _make_manager(data_broker=data_broker)
    try:
        readings = await _drain(queue)
        states = {(reading.metadata["channel"], reading.metadata["state"]) for reading in readings}
        assert ("smua", "off") in states
        assert ("smub", "off") in states
    finally:
        await manager.stop()


async def test_channel_state_publish_tracks_run_and_stop() -> None:
    data_broker = DataBroker()
    queue = await data_broker.subscribe(
        "test_keithley_channel_state_transitions",
        maxsize=100,
        filter_fn=lambda reading: reading.channel.startswith("analytics/keithley_channel_state/"),
    )
    manager, safety_broker = await _make_manager(data_broker=data_broker)
    try:
        await safety_broker.publish(
            Reading.now(channel="T1", value=4.5, unit="K", instrument_id="test")
        )
        await asyncio.sleep(1.2)

        result = await manager.request_run(0.5, 40.0, 1.0, channel="smub")
        assert result["ok"] is True
        await asyncio.sleep(0.05)

        result = await manager.request_stop(channel="smub")
        assert result["ok"] is True
        await asyncio.sleep(0.05)

        readings = await _drain(queue)
        states = [(reading.metadata["channel"], reading.metadata["state"]) for reading in readings]
        assert ("smub", "on") in states
        assert states[-1] == ("smub", "off")
    finally:
        await manager.stop()


async def test_fault_publishes_fault_state_for_triggering_channel() -> None:
    data_broker = DataBroker()
    queue = await data_broker.subscribe(
        "test_keithley_channel_state_fault",
        maxsize=100,
        filter_fn=lambda reading: reading.channel.startswith("analytics/keithley_channel_state/"),
    )
    manager, safety_broker = await _make_manager(data_broker=data_broker)
    try:
        await manager._fault("test fault", channel="smua")
        await asyncio.sleep(0.05)

        readings = await _drain(queue)
        states = {(reading.metadata["channel"], reading.metadata["state"]) for reading in readings}
        assert ("smua", "fault") in states
        assert ("smub", "off") in states
    finally:
        await manager.stop()
