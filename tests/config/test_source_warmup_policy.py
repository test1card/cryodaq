"""Owner-ratified warm-detector and cryostat overtemperature guards.

These tests exercise the production configuration, descriptor binding,
interlock engine, and operator-alarm/control routing. They do not close any
physical heater, source, dummy-load, target-OS, or laboratory gate.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import yaml

from cryodaq.channels.persistence import PersistedChannelEnvelopeV1
from cryodaq.core.alarm_v2 import AlarmStateManager
from cryodaq.core.broker import DataBroker
from cryodaq.core.event_bus import EventBus
from cryodaq.core.interlock import InterlockEngine, InterlockState
from cryodaq.drivers.base import Reading
from cryodaq.drivers.contracts import SourceOffResult
from cryodaq.engine import _interlock_trip_handler, _InterlockHandlerContext
from cryodaq.storage.channel_descriptors import load_live_channel_descriptor_catalog

ROOT = Path(__file__).resolve().parents[2]
INTERLOCKS_PATH = ROOT / "config" / "interlocks.yaml"
DESCRIPTORS_PATH = ROOT / "config" / "channel_descriptors.yaml"
POLL_INTERVALS = {"LS218_1": 2.0, "LS218_2": 2.0}


def _interlocks() -> dict[str, dict]:
    raw = yaml.safe_load(INTERLOCKS_PATH.read_text(encoding="utf-8"))
    return {entry["name"]: entry for entry in raw["interlocks"]}


async def _publish_bound(broker: DataBroker, reading: Reading) -> None:
    catalog = load_live_channel_descriptor_catalog(DESCRIPTORS_PATH)
    bound = catalog.bind(reading)
    await broker.publish(
        bound.reading,
        persistence_authoritative=True,
        descriptor_envelope=PersistedChannelEnvelopeV1.from_descriptor(bound.descriptor).canonical_json,
    )


async def test_warm_detector_warns_operator_without_stopping_running_source() -> None:
    entry = _interlocks()["detector_warmup"]
    assert entry["channel_bindings"] == [{"instrument_id": "LS218_2", "source_key": "input.4.temperature"}]
    assert entry["threshold"] == 10.0
    assert entry["comparison"] == ">"
    assert entry["action"] == "warning"

    class SafetyProbe:
        def __init__(self) -> None:
            self.state = "running"
            self.calls: list[tuple[str, str, float, str]] = []

        async def on_interlock_trip(self, interlock_name, channel, value, *, action) -> None:
            self.calls.append((interlock_name, channel, value, action))

    broker = DataBroker()
    event_bus = EventBus()
    event_queue = await event_bus.subscribe("warm-detector-policy")
    safety = SafetyProbe()
    alarm_state_manager = AlarmStateManager()
    local_control_actions: list[str] = []

    async def emergency_off() -> SourceOffResult:
        local_control_actions.append("emergency_off")
        return SourceOffResult.COMMAND_ACCEPTED

    async def stop_source() -> None:
        local_control_actions.append("stop_source")

    context = _InterlockHandlerContext(
        safety_manager=safety,
        alarm_dispatch_tasks=set(),
        dead_channel_alarm_sent=set(),
        event_bus=event_bus,
        experiment_manager=SimpleNamespace(active_experiment_id="thermal-run"),
        alarm_state_manager=alarm_state_manager,
    )
    engine = InterlockEngine(
        broker,
        actions={"emergency_off": emergency_off, "stop_source": stop_source},
        trip_handler=lambda condition, reading: _interlock_trip_handler(
            condition,
            reading,
            context=context,
        ),
    )
    engine.load_config(
        INTERLOCKS_PATH,
        descriptor_catalog=load_live_channel_descriptor_catalog(DESCRIPTORS_PATH),
        poll_intervals_s_by_instrument=POLL_INTERVALS,
    )

    await engine.start()
    try:
        await _publish_bound(
            broker,
            Reading.now("Т12 Теплообменник 2", 12.0, "K", instrument_id="LS218_2"),
        )
        await asyncio.sleep(0.05)

        assert safety.state == "running"
        assert safety.calls == []
        assert local_control_actions == []
        assert engine.get_state()["detector_warmup"] is InterlockState.TRIPPED
        event = event_queue.get_nowait()
        assert event.event_type == "alarm_fired"
        assert event.payload["alarm_id"] == "detector_warmup"
        assert event.payload["level"] == "WARNING"
        assert event.payload["channels"] == ["Т12"]
        assert alarm_state_manager.get_active()["detector_warmup"].level == "WARNING"
    finally:
        await engine.stop()


async def test_cryostat_above_320_k_stops_source_without_emergency_off() -> None:
    entries = _interlocks()
    overtemp = entries["source_overtemp"]
    assert overtemp["channel_bindings"] == entries["overheat_cryostat"]["channel_bindings"]
    assert overtemp["threshold"] == 320.0
    assert overtemp["comparison"] == ">"
    assert overtemp["action"] == "stop_source"

    broker = DataBroker()
    actions: list[str] = []

    async def emergency_off() -> SourceOffResult:
        actions.append("emergency_off")
        return SourceOffResult.COMMAND_ACCEPTED

    async def stop_source() -> None:
        actions.append("stop_source")

    engine = InterlockEngine(
        broker,
        actions={"emergency_off": emergency_off, "stop_source": stop_source},
    )
    engine.load_config(
        INTERLOCKS_PATH,
        descriptor_catalog=load_live_channel_descriptor_catalog(DESCRIPTORS_PATH),
        poll_intervals_s_by_instrument=POLL_INTERVALS,
    )
    await engine.start()
    try:
        await _publish_bound(
            broker,
            Reading.now("Т1 Криостат верх", 320.1, "K", instrument_id="LS218_1"),
        )
        await asyncio.sleep(0.05)
        assert actions == ["stop_source"]
        assert engine.get_state()["source_overtemp"] is InterlockState.TRIPPED
        assert engine.get_state()["overheat_cryostat"] is InterlockState.ARMED
    finally:
        await engine.stop()


async def test_cryostat_above_350_k_keeps_emergency_off_tier() -> None:
    entries = _interlocks()
    assert entries["source_overtemp"]["threshold"] == 320.0
    emergency = entries["overheat_cryostat"]
    assert emergency["threshold"] == 350.0
    assert emergency["comparison"] == ">"
    assert emergency["action"] == "emergency_off"

    broker = DataBroker()
    actions: list[str] = []

    async def emergency_off() -> SourceOffResult:
        actions.append("emergency_off")
        return SourceOffResult.COMMAND_ACCEPTED

    async def stop_source() -> None:
        actions.append("stop_source")

    engine = InterlockEngine(
        broker,
        actions={"emergency_off": emergency_off, "stop_source": stop_source},
    )
    engine.load_config(
        INTERLOCKS_PATH,
        descriptor_catalog=load_live_channel_descriptor_catalog(DESCRIPTORS_PATH),
        poll_intervals_s_by_instrument=POLL_INTERVALS,
    )
    await engine.start()
    try:
        await _publish_bound(
            broker,
            Reading.now("Т1 Криостат верх", 350.1, "K", instrument_id="LS218_1"),
        )
        await asyncio.sleep(0.05)
        assert sorted(actions) == ["emergency_off", "stop_source"]
        assert engine.get_state()["overheat_cryostat"] is InterlockState.TRIPPED
    finally:
        await engine.stop()


async def test_warning_route_cannot_silence_configured_stop_action() -> None:
    entry = _interlocks()["source_overtemp"]
    assert entry["action"] == "stop_source"

    class SafetyProbe:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, float, str]] = []

        async def on_interlock_trip(self, interlock_name, channel, value, *, action) -> None:
            self.calls.append((interlock_name, channel, value, action))

    event_bus = EventBus()
    event_queue = await event_bus.subscribe("configured-stop-policy")
    safety = SafetyProbe()
    context = _InterlockHandlerContext(
        safety_manager=safety,
        alarm_dispatch_tasks=set(),
        dead_channel_alarm_sent=set(),
        event_bus=event_bus,
        experiment_manager=SimpleNamespace(active_experiment_id="thermal-run"),
        alarm_state_manager=AlarmStateManager(),
    )
    condition = SimpleNamespace(
        name=entry["name"],
        description=entry["description"],
        action=entry["action"],
    )

    await _interlock_trip_handler(
        condition,
        Reading.now("Т1", 320.1, "K", instrument_id="LS218_1"),
        context=context,
    )

    assert safety.calls == [("source_overtemp", "Т1", 320.1, "stop_source")]
    assert event_queue.empty(), "a configured stop must not be diverted to the warning-only alarm path"
