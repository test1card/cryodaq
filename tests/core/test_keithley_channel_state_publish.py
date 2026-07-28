from __future__ import annotations

import asyncio
import math

from cryodaq.core.broker import DataBroker
from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager
from cryodaq.drivers.base import Reading
from cryodaq.drivers.contracts import SourceOffEvidence, SourceOffResult, SourceOffTier


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


async def test_initial_channel_state_without_off_evidence_publishes_unknown_for_both() -> None:
    data_broker = DataBroker()
    queue = await data_broker.subscribe(
        "test_keithley_channel_state_initial_unknown",
        maxsize=100,
        filter_fn=lambda reading: reading.channel.startswith("analytics/keithley_channel_state/"),
    )
    manager = SafetyManager(SafetyBroker(), mock=False, data_broker=data_broker)
    await manager.start()
    try:
        readings = await _drain(queue)
        by_channel = {reading.metadata["channel"]: reading for reading in readings}
        assert set(by_channel) == {"smua", "smub"}
        assert all(reading.metadata["state"] == "unknown" for reading in by_channel.values())
        assert all(math.isnan(reading.value) for reading in by_channel.values())
    finally:
        await manager.stop()


async def test_initial_channel_state_with_device_reported_off_publishes_off_for_both() -> None:
    data_broker = DataBroker()
    queue = await data_broker.subscribe(
        "test_keithley_channel_state_initial",
        maxsize=100,
        filter_fn=lambda reading: reading.channel.startswith("analytics/keithley_channel_state/"),
    )
    manager, safety_broker = await _make_manager(data_broker=data_broker)
    try:
        readings = await _drain(queue)
        by_channel = {reading.metadata["channel"]: reading for reading in readings}
        assert {channel: reading.metadata["state"] for channel, reading in by_channel.items()} == {
            "smua": "off",
            "smub": "off",
        }
        assert all(reading.value == 0.0 for reading in by_channel.values())
        assert all(
            reading.metadata["off_evidence"]["channel_off_results"][channel] == "device_reported_off"
            for channel, reading in by_channel.items()
        )
    finally:
        await manager.stop()


async def test_command_tier_device_reported_off_publishes_off_without_verified_claim() -> None:
    data_broker = DataBroker()
    queue = await data_broker.subscribe(
        "test_keithley_channel_state_device_reported_off",
        maxsize=100,
        filter_fn=lambda reading: reading.channel.startswith("analytics/keithley_channel_state/"),
    )
    manager = SafetyManager(SafetyBroker(), mock=False, data_broker=data_broker)
    await manager.start()
    try:
        await _drain(queue)
        manager._reviewed_source_off_evidence = SourceOffEvidence.from_global_result(
            SourceOffTier.COMMAND_ONLY,
            SourceOffResult.DEVICE_REPORTED_OFF,
        )
        await manager._publish_keithley_channel_states("device_reported_off")
        readings = await _drain(queue)
        assert all(reading.metadata["state"] == "off" and reading.value == 0.0 for reading in readings)
        assert all(reading.metadata["off_evidence"]["verified_off"] is False for reading in readings)
    finally:
        await manager.stop()


async def test_channel_state_publisher_does_not_publish_other_analytics_channels() -> None:
    data_broker = DataBroker()
    queue = await data_broker.subscribe(
        "test_keithley_channel_state_only",
        maxsize=100,
        filter_fn=lambda reading: reading.channel.startswith("analytics/"),
    )
    manager = SafetyManager(SafetyBroker(), mock=False, data_broker=data_broker)
    await manager.start()
    try:
        await _drain(queue)
        await manager._publish_keithley_channel_states("test")
        readings = await _drain(queue)
        assert {reading.channel for reading in readings} == {
            "analytics/keithley_channel_state/smua",
            "analytics/keithley_channel_state/smub",
        }
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
        await safety_broker.publish(Reading.now(channel="T1", value=4.5, unit="K", instrument_id="test"))
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
        assert states[-1] == ("smub", "unknown")
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
