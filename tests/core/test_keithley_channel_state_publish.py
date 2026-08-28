from __future__ import annotations

import asyncio
import math
from collections.abc import Sequence
from typing import Any

import zmq

from cryodaq.core.broker import DataBroker
from cryodaq.core.interlock import InterlockCondition, InterlockEngine, InterlockState
from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager
from cryodaq.core.smu_channel import SMU_CHANNELS
from cryodaq.core.zmq_bridge import ZMQPublisher, ZMQSubscriber, _unpack_reading
from cryodaq.drivers.base import Reading
from cryodaq.drivers.contracts import SourceOffEvidence, SourceOffResult, SourceOffTier


class _LateAttachingSocket:
    """Non-retaining PUB transport whose observer attaches on demand."""

    def __init__(self) -> None:
        self.attached = False
        self.messages: list[list[bytes]] = []

    async def send_multipart(self, frames: Sequence[bytes]) -> None:
        if self.attached:
            self.messages.append(list(frames))

    def close(self, *, linger: int) -> None:
        del linger


def _start_non_socket_publisher(
    queue: asyncio.Queue[Any],
) -> tuple[ZMQPublisher, _LateAttachingSocket]:
    """Run the production drain/encoding loop without opening a socket."""

    publisher = ZMQPublisher()
    socket = _LateAttachingSocket()
    publisher._queue = queue
    publisher._session_id = "0" * 32
    publisher._socket = socket  # type: ignore[assignment]
    publisher._running = True
    publisher._task = asyncio.create_task(publisher._publish_loop(queue))
    return publisher, socket


async def _wait_for_channel_states(socket: _LateAttachingSocket) -> dict[str, Reading]:
    async def collect() -> dict[str, Reading]:
        while True:
            readings = [_unpack_reading(frames[1]) for frames in socket.messages]
            by_channel = {
                reading.metadata["channel"]: reading
                for reading in readings
                if reading.instrument_id == "safety_manager" and reading.metadata.get("channel") in SMU_CHANNELS
            }
            if set(by_channel) == set(SMU_CHANNELS):
                return by_channel
            await asyncio.sleep(0)

    return await asyncio.wait_for(collect(), timeout=2.5)


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


async def test_late_transport_observer_receives_authoritative_states_without_interlock_trip() -> None:
    data_broker = DataBroker()
    publisher_queue = await data_broker.subscribe(
        "zmq_publisher",
        maxsize=100,
        wants_descriptor_envelope=True,
    )
    publisher, socket = _start_non_socket_publisher(publisher_queue)
    warning_calls: list[None] = []

    async def warn_only() -> None:
        warning_calls.append(None)

    detector_guard = InterlockEngine(data_broker, actions={"warning": warn_only})
    detector_guard.add_condition(
        InterlockCondition(
            name="detector_warmup",
            description="test warning-only masking control",
            channel_ids=frozenset({"test/detector_temperature"}),
            threshold=10.0,
            comparison=">",
            action="warning",
        )
    )
    await detector_guard.start()
    manager = SafetyManager(SafetyBroker(), mock=True, data_broker=data_broker)
    await manager.start()
    try:
        result = await manager.request_run(0.5, 40.0, 1.0, channel=SMU_CHANNELS[0])
        assert result["ok"] is True
        await asyncio.wait_for(publisher_queue.join(), timeout=0.5)

        socket.attached = True
        try:
            by_channel = await _wait_for_channel_states(socket)
        except TimeoutError as exc:
            assert detector_guard.get_state()["detector_warmup"] is InterlockState.ARMED
            assert warning_calls == []
            raise AssertionError(
                "late source-state publication timed out while the warning-only detector guard stayed uninvolved"
            ) from exc

        assert {channel: reading.metadata["state"] for channel, reading in by_channel.items()} == {
            SMU_CHANNELS[0]: "on",
            SMU_CHANNELS[1]: "unknown",
        }
        assert (
            by_channel[SMU_CHANNELS[1]].metadata["off_evidence"]["channel_off_results"][SMU_CHANNELS[1]]
            == SourceOffResult.PHYSICAL_STATE_UNKNOWN.value
        )
        assert detector_guard.get_state()["detector_warmup"] is InterlockState.ARMED
        assert warning_calls == []
    finally:
        await manager.stop()
        await detector_guard.stop()
        await publisher.stop()


async def test_late_transport_observer_preserves_genuinely_unknown_source_state() -> None:
    data_broker = DataBroker()
    publisher_queue = await data_broker.subscribe(
        "zmq_publisher",
        maxsize=100,
        wants_descriptor_envelope=True,
    )
    publisher, socket = _start_non_socket_publisher(publisher_queue)
    manager = SafetyManager(SafetyBroker(), mock=False, data_broker=data_broker)
    await manager.start()
    try:
        await asyncio.wait_for(publisher_queue.join(), timeout=0.5)

        socket.attached = True
        by_channel = await _wait_for_channel_states(socket)

        assert set(by_channel) == set(SMU_CHANNELS)
        assert all(reading.metadata["state"] == "unknown" for reading in by_channel.values())
        assert all(math.isnan(reading.value) for reading in by_channel.values())
        assert all(
            reading.metadata["off_evidence"]["channel_off_results"][channel]
            == SourceOffResult.PHYSICAL_STATE_UNKNOWN.value
            for channel, reading in by_channel.items()
        )
    finally:
        await manager.stop()
        await publisher.stop()


async def test_real_loopback_subscribers_repeatedly_attach_after_startup_and_receive_source_state() -> None:
    data_broker = DataBroker()
    publisher_queue = await data_broker.subscribe(
        "zmq_publisher",
        maxsize=100,
        wants_descriptor_envelope=True,
    )
    publisher = ZMQPublisher("tcp://127.0.0.1:*")
    await publisher.start(publisher_queue)
    manager = SafetyManager(SafetyBroker(), mock=True, data_broker=data_broker)
    await manager.start()
    try:
        result = await manager.request_run(0.5, 40.0, 1.0, channel=SMU_CHANNELS[0])
        assert result["ok"] is True
        await asyncio.wait_for(publisher_queue.join(), timeout=0.5)

        assert publisher._socket is not None
        endpoint = publisher._socket.getsockopt_string(zmq.LAST_ENDPOINT)
        for _attachment in range(3):
            received: dict[str, Reading] = {}
            complete = asyncio.Event()

            def on_reading(reading: Reading) -> None:
                if reading.instrument_id != "safety_manager":
                    return
                channel = reading.metadata.get("channel")
                if channel in SMU_CHANNELS:
                    received[str(channel)] = reading
                if set(received) == set(SMU_CHANNELS):
                    complete.set()

            subscriber = ZMQSubscriber(endpoint, callback=on_reading)
            await subscriber.start()
            try:
                await asyncio.wait_for(complete.wait(), timeout=3.5)
            finally:
                await subscriber.stop()

            assert {channel: reading.metadata["state"] for channel, reading in received.items()} == {
                SMU_CHANNELS[0]: "on",
                SMU_CHANNELS[1]: "unknown",
            }
            assert all(reading.metadata["reason"] == "periodic" for reading in received.values())
            assert all(reading.metadata["is_transition"] is False for reading in received.values())
    finally:
        await manager.stop()
        await publisher.stop()


async def test_periodic_off_snapshot_preserves_evidence_age_then_expires_to_unknown() -> None:
    data_broker = DataBroker()
    queue = await data_broker.subscribe(
        "test_keithley_periodic_off_age",
        maxsize=100,
        filter_fn=lambda reading: reading.channel.startswith("analytics/keithley_channel_state/"),
    )
    manager, _safety_broker = await _make_manager(data_broker=data_broker)
    try:
        initial = await _drain(queue)
        observed_at = initial[0].timestamp
        assert {reading.timestamp for reading in initial} == {observed_at}

        await manager._publish_keithley_channel_states("periodic")
        retained = await _drain(queue)
        assert {reading.timestamp for reading in retained} == {observed_at}
        assert all(reading.metadata["state"] == "off" for reading in retained)

        manager._config.stale_timeout_s = 0.0
        await manager._publish_keithley_channel_states("periodic")
        expired = await _drain(queue)
        assert all(reading.metadata["state"] == "unknown" for reading in expired)
        assert all(math.isnan(reading.value) for reading in expired)
        assert all(
            reading.metadata["off_evidence"]["channel_off_results"][channel]
            == SourceOffResult.PHYSICAL_STATE_UNKNOWN.value
            for channel, reading in ((reading.metadata["channel"], reading) for reading in expired)
        )
    finally:
        await manager.stop()


async def test_periodic_snapshot_reports_physical_off_while_manager_fault_remains_latched() -> None:
    data_broker = DataBroker()
    queue = await data_broker.subscribe(
        "test_keithley_periodic_latched_fault",
        maxsize=100,
        filter_fn=lambda reading: reading.channel.startswith("analytics/keithley_channel_state/"),
    )
    manager, _safety_broker = await _make_manager(data_broker=data_broker)
    manager._config.cooldown_before_rearm_s = 0.0
    try:
        await _drain(queue)
        await manager._fault("latched channel fault", channel=SMU_CHANNELS[0])
        await _drain(queue)
        assert manager.state.value == "fault_latched"
        assert manager.fault_reason == "latched channel fault"

        async def collect_periodic() -> dict[str, Reading]:
            by_channel: dict[str, Reading] = {}
            while set(by_channel) != set(SMU_CHANNELS):
                reading = await queue.get()
                if reading.metadata.get("reason") == "periodic":
                    by_channel[reading.metadata["channel"]] = reading
            return by_channel

        periodic = await asyncio.wait_for(collect_periodic(), timeout=2.5)
        assert all(reading.metadata["state"] == "off" for reading in periodic.values())
        assert all(reading.metadata["is_transition"] is False for reading in periodic.values())

        acknowledged = await manager.acknowledge_fault("fault inspected")
        assert acknowledged["ok"] is True
        await manager._publish_keithley_channel_states("periodic")
        after_ack = await _drain(queue)
        assert all(reading.metadata["state"] != "fault" for reading in after_ack)
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
