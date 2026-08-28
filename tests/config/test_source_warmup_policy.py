"""Owner-ratified warm-cryostat source policy regressions.

The production interlock configuration, descriptor authority, mock LakeShore
readings, and operator alarm dispatch are exercised together.  These tests do
not stand in for the still-open physical heater/dummy-load gates.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import yaml

from cryodaq.channels.persistence import PersistedChannelEnvelopeV1
from cryodaq.core.alarm_config import load_alarm_config
from cryodaq.core.alarm_v2 import AlarmStateManager
from cryodaq.core.annunciation import AnnunciationRegistry
from cryodaq.core.broker import DataBroker
from cryodaq.core.event_bus import EventBus
from cryodaq.core.interlock import InterlockEngine, InterlockState
from cryodaq.drivers.base import Reading
from cryodaq.drivers.instruments.lakeshore_218s import LakeShore218S
from cryodaq.engine import (
    _interlock_trip_admission,
    _interlock_trip_handler,
    _interlock_warning_recovery_handler,
    _InterlockHandlerContext,
)
from cryodaq.storage.channel_descriptors import load_live_channel_descriptor_catalog

ROOT = Path(__file__).resolve().parents[2]
INTERLOCKS_PATH = ROOT / "config" / "interlocks.yaml"
ALARMS_V3_PATH = ROOT / "config" / "alarms_v3.yaml"
DESCRIPTORS_PATH = ROOT / "config" / "channel_descriptors.yaml"
INSTRUMENTS_PATH = ROOT / "config" / "instruments.yaml"
ALARMS_GUIDE_PATH = ROOT / "docs" / "alarms_tuning_guide.md"
SAFETY_OPERATOR_PATH = ROOT / "docs" / "safety-operator.md"
POLL_INTERVALS = {"LS218_1": 2.0, "LS218_2": 2.0}

_EMERGENCY_ROW_SHA256 = {
    "overheat_cryostat": "d6d4fdd9bab43576ff5ab2e6939a076f3a3196263d5be7553d400d2e25c69143",
    "overheat_compressor": "0dadc8df19382d97fcb478472c275e287ea7b2b29cd871a6fa2cedaebe778ee8",
}


def _interlocks() -> dict[str, dict]:
    raw = yaml.safe_load(INTERLOCKS_PATH.read_text(encoding="utf-8"))
    return {entry["name"]: entry for entry in raw["interlocks"]}


def _row_bytes(name: str) -> bytes:
    lines = INTERLOCKS_PATH.read_bytes().splitlines(keepends=True)
    marker = f'  - name: "{name}"'.encode()
    start = next(index for index, line in enumerate(lines) if line.rstrip(b"\r\n") == marker)
    end = next(
        (index for index in range(start + 1, len(lines)) if lines[index].strip() == b""),
        len(lines),
    )
    return b"".join(lines[start:end])


async def _publish_bound_sensor(
    broker: DataBroker,
    catalog,
    reading: Reading,
) -> None:
    bound = catalog.bind(reading)
    await broker.publish(
        bound.reading,
        persistence_authoritative=True,
        descriptor_envelope=PersistedChannelEnvelopeV1.from_descriptor(bound.descriptor).canonical_json,
    )


def _mock_driver(name: str) -> LakeShore218S:
    raw = yaml.safe_load(INSTRUMENTS_PATH.read_text(encoding="utf-8"))
    config = next(entry for entry in raw["instruments"] if entry["name"] == name)
    return LakeShore218S(
        name,
        config["resource"],
        channel_labels={int(index): label for index, label in config["channels"].items()},
        mock=True,
    )


def test_detector_warmup_is_kept_as_t12_warning() -> None:
    entry = _interlocks()["detector_warmup"]

    assert entry["channel_bindings"] == [{"instrument_id": "LS218_2", "source_key": "input.4.temperature"}]
    assert entry["threshold"] == 10.0
    assert entry["comparison"] == ">"
    assert entry["action"] == "warning"
    assert "2-я ступень" in entry["description"]
    assert "измер" in entry["description"].lower()


def test_operator_docs_match_warm_detector_and_source_overtemp_policy() -> None:
    entries = _interlocks()
    detector = entries["detector_warmup"]
    source_overtemp = entries["source_overtemp"]
    guide = ALARMS_GUIDE_PATH.read_text(encoding="utf-8")
    operator = SAFETY_OPERATOR_PATH.read_text(encoding="utf-8")

    guide_interlocks = guide.split("## Слой 2: Interlock Engine", 1)[1].split("## Слой 3:", 1)[0]
    operator_ack = operator.split("## Interlock acknowledge", 1)[1].split("## Связанные документы", 1)[0]

    assert detector["threshold"] == 10.0
    assert detector["action"] == "warning"
    assert 'action: "warning"' in guide_interlocks
    assert "источник остаётся включён" in guide_interlocks
    assert "во всех lifecycle-состояниях" in guide_interlocks
    assert "ручной acknowledge не применяется" in guide_interlocks
    assert "при Т12 >10 K" in operator_ack
    assert "источник не отключается" in operator_ack
    assert "не квитируется вручную" in operator_ack

    assert source_overtemp["threshold"] == 320.0
    assert source_overtemp["action"] == "stop_source"
    assert '- name: "source_overtemp"' in guide_interlocks
    assert "только в активном lifecycle источника" in guide_interlocks
    assert "Имя для acknowledge после устранения причины: `source_overtemp`" in guide_interlocks
    assert "`source_overtemp` — отдельная защитная ступень для Т1-Т8 >320 K" in operator_ack
    assert "имя acknowledge после устранения причины —\n`source_overtemp`" in operator_ack


def test_documented_current_interlocks_are_loadable_with_production_bindings(tmp_path: Path) -> None:
    guide = ALARMS_GUIDE_PATH.read_text(encoding="utf-8")
    interlock_layer = guide.split("## Слой 2: Interlock Engine", 1)[1].split("## Слой 3:", 1)[0]
    current = interlock_layer.split("### Текущая конфигурация", 1)[1].split("### Actions", 1)[0]
    yaml_block = current.split("```yaml", 1)[1].split("```", 1)[0]
    documented = yaml.safe_load(yaml_block)
    source_overtemp = next(row for row in documented["interlocks"] if row["name"] == "source_overtemp")

    assert source_overtemp["channel_bindings"] == _interlocks()["source_overtemp"]["channel_bindings"]
    assert "channel_pattern" not in source_overtemp

    documented_path = tmp_path / "interlocks.yaml"
    documented_path.write_text(yaml_block, encoding="utf-8")
    catalog = load_live_channel_descriptor_catalog(DESCRIPTORS_PATH)
    engine = InterlockEngine(
        DataBroker(),
        actions={"emergency_off": lambda: None, "stop_source": lambda: None},
    )
    engine.load_config(
        documented_path,
        descriptor_catalog=catalog,
        poll_intervals_s_by_instrument=POLL_INTERVALS,
    )
    assert set(engine.get_state()) == set(_interlocks())


async def test_detector_warmup_dispatches_operator_warning_without_control() -> None:
    bus = EventBus()
    queue = await bus.subscribe("detector-warning-test")

    class SafetyProbe:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, float, str]] = []

        async def on_interlock_trip(self, interlock_name, channel, value, *, action) -> None:
            self.calls.append((interlock_name, channel, value, action))

    safety = SafetyProbe()
    alarm_state_manager = AlarmStateManager()
    context = _InterlockHandlerContext(
        safety_manager=safety,
        alarm_dispatch_tasks=set(),
        dead_channel_alarm_sent=set(),
        event_bus=bus,
        experiment_manager=SimpleNamespace(active_experiment_id="measurement-1"),
        alarm_state_manager=alarm_state_manager,
    )
    condition = SimpleNamespace(
        name="detector_warmup",
        description=("2-я ступень (Т12) выше рабочей температуры; данные измерения могут быть недостоверны"),
        threshold=10.0,
        comparison=">",
        action="warning",
    )
    reading = Reading.now("Т12", 77.5, "K", instrument_id="LS218_2")

    await _interlock_trip_handler(condition, reading, context=context)

    assert safety.calls == [], "warning action must not acquire source-control authority"
    event = queue.get_nowait()
    assert event.event_type == "alarm_fired"
    assert event.payload["alarm_id"] == "detector_warmup"
    assert event.payload["level"] == "WARNING"
    assert "2-я ступень" in event.payload["message"]
    assert "измер" in event.payload["message"].lower()
    assert event.payload["channels"] == ["Т12"]

    active = alarm_state_manager.get_active()
    assert active["detector_warmup"].level == "WARNING"
    registry = AnnunciationRegistry(engine_instance_id="1" * 32)
    registry.sync(
        active,
        {"state": "ready", "fault_revision": 0},
    )
    assert registry.snapshot()["activations"] == [
        {
            "activation_id": "a1",
            "source": "alarm_v2",
            "source_key": "detector_warmup",
            "severity": "WARNING",
            "activated_at": active["detector_warmup"].triggered_at,
            "acknowledged": False,
        }
    ]


async def test_detector_warning_publication_failure_never_latches_safety(caplog) -> None:
    class FailingBus:
        async def publish(self, _event) -> None:
            raise RuntimeError("notification transport unavailable")

    class SafetyProbe:
        def __init__(self) -> None:
            self.latch_calls: list[dict] = []

        async def on_interlock_trip(self, *_args, **_kwargs) -> None:
            raise AssertionError("warning must not enter the control path")

        async def latch_fault(self, **kwargs) -> None:
            self.latch_calls.append(kwargs)

    safety = SafetyProbe()
    alarm_state_manager = AlarmStateManager()
    context = _InterlockHandlerContext(
        safety_manager=safety,
        alarm_dispatch_tasks=set(),
        dead_channel_alarm_sent=set(),
        event_bus=FailingBus(),
        experiment_manager=SimpleNamespace(active_experiment_id="measurement-1"),
        alarm_state_manager=alarm_state_manager,
    )
    condition = SimpleNamespace(
        name="detector_warmup",
        description="detector stage is warm",
        action="warning",
    )

    await _interlock_trip_handler(
        condition,
        Reading.now("Т12", 12.0, "K", instrument_id="LS218_2"),
        context=context,
    )

    assert safety.latch_calls == []
    assert "detector_warmup" in alarm_state_manager.get_active()
    assert "Interlock warning publication failed" in caplog.text


async def test_warm_mock_readings_do_not_request_source_stop(monkeypatch) -> None:
    monkeypatch.setattr(
        "cryodaq.drivers.instruments.lakeshore_218s.random.uniform",
        lambda _low, _high: 0.0,
    )
    catalog = load_live_channel_descriptor_catalog(DESCRIPTORS_PATH)
    broker = DataBroker()
    protective_actions: list[str] = []

    async def emergency_off() -> None:
        protective_actions.append("emergency_off")

    async def stop_source() -> None:
        protective_actions.append("stop_source")

    engine = InterlockEngine(
        broker,
        actions={"emergency_off": emergency_off, "stop_source": stop_source},
    )
    engine.load_config(
        INTERLOCKS_PATH,
        descriptor_catalog=catalog,
        poll_intervals_s_by_instrument=POLL_INTERVALS,
    )
    await engine.start()
    try:
        for instrument_id in POLL_INTERVALS:
            driver = _mock_driver(instrument_id)
            await driver.connect()
            try:
                readings = await driver.read_channels()
            finally:
                await driver.disconnect()
            for reading in readings:
                await _publish_bound_sensor(broker, catalog, reading)

        await asyncio.sleep(0.1)

        assert protective_actions == []
        assert engine.get_state()["detector_warmup"] is InterlockState.TRIPPED
        assert engine.get_state()["source_overtemp"] is InterlockState.ARMED
    finally:
        await engine.stop()


async def test_source_overtemp_stops_above_threshold() -> None:
    entries = _interlocks()
    overtemp = entries["source_overtemp"]
    cryostat = entries["overheat_cryostat"]

    assert overtemp["channel_bindings"] == cryostat["channel_bindings"]
    assert overtemp["threshold"] == 320.0
    assert overtemp["comparison"] == ">"
    assert overtemp["action"] == "stop_source"

    catalog = load_live_channel_descriptor_catalog(DESCRIPTORS_PATH)
    broker = DataBroker()
    stops: list[str] = []

    async def emergency_off() -> None:
        raise AssertionError("320.1 K must not cross the unchanged 350 K emergency tier")

    async def stop_source() -> None:
        stops.append("stop_source")

    engine = InterlockEngine(
        broker,
        actions={"emergency_off": emergency_off, "stop_source": stop_source},
    )
    engine.load_config(
        INTERLOCKS_PATH,
        descriptor_catalog=catalog,
        poll_intervals_s_by_instrument=POLL_INTERVALS,
    )
    await engine.start()
    try:
        above_limit = Reading.now("Т1 Криостат верх", 320.1, "K", instrument_id="LS218_1")
        await _publish_bound_sensor(broker, catalog, above_limit)
        await asyncio.sleep(0.05)
        assert stops == ["stop_source"]
        assert engine.get_state()["source_overtemp"] is InterlockState.TRIPPED
    finally:
        await engine.stop()


async def test_source_overtemp_does_not_trip_at_mock_ambient() -> None:
    catalog = load_live_channel_descriptor_catalog(DESCRIPTORS_PATH)
    broker = DataBroker()
    protective_actions: list[str] = []

    async def emergency_off() -> None:
        protective_actions.append("emergency_off")

    async def stop_source() -> None:
        protective_actions.append("stop_source")

    engine = InterlockEngine(
        broker,
        actions={"emergency_off": emergency_off, "stop_source": stop_source},
    )
    engine.load_config(
        INTERLOCKS_PATH,
        descriptor_catalog=catalog,
        poll_intervals_s_by_instrument=POLL_INTERVALS,
    )
    await engine.start()
    try:
        ambient = Reading.now("Т8 Калибровка", 300.0, "K", instrument_id="LS218_1")
        await _publish_bound_sensor(broker, catalog, ambient)
        await asyncio.sleep(0.05)

        assert protective_actions == []
        assert engine.get_state()["source_overtemp"] is InterlockState.ARMED
    finally:
        await engine.stop()


async def test_source_overtemp_accepts_documented_320_k_upper_band() -> None:
    catalog = load_live_channel_descriptor_catalog(DESCRIPTORS_PATH)
    broker = DataBroker()
    protective_actions: list[str] = []

    async def emergency_off() -> None:
        protective_actions.append("emergency_off")

    async def stop_source() -> None:
        protective_actions.append("stop_source")

    engine = InterlockEngine(
        broker,
        actions={"emergency_off": emergency_off, "stop_source": stop_source},
    )
    engine.load_config(
        INTERLOCKS_PATH,
        descriptor_catalog=catalog,
        poll_intervals_s_by_instrument=POLL_INTERVALS,
    )
    await engine.start()
    try:
        legitimate = Reading.now("Т1 Криостат верх", 320.0, "K", instrument_id="LS218_1")
        await _publish_bound_sensor(broker, catalog, legitimate)
        await asyncio.sleep(0.05)

        assert protective_actions == []
        assert engine.get_state()["source_overtemp"] is InterlockState.ARMED
    finally:
        await engine.stop()


async def test_idle_overtemp_remains_armed_then_stops_running_source() -> None:
    class SafetyProbe:
        def __init__(self) -> None:
            self.state = "safe_off"
            self.calls: list[tuple[str, str, float, str]] = []

        def get_status(self) -> dict[str, str]:
            return {"state": self.state}

        async def on_interlock_trip(self, interlock_name, channel, value, *, action) -> None:
            self.calls.append((interlock_name, channel, value, action))

        async def latch_fault(self, **_kwargs) -> None:
            raise AssertionError("the admitted stop_source path must not fault")

    catalog = load_live_channel_descriptor_catalog(DESCRIPTORS_PATH)
    broker = DataBroker()
    safety = SafetyProbe()

    async def noop() -> None:
        return None

    context = _InterlockHandlerContext(
        safety_manager=safety,
        alarm_dispatch_tasks=set(),
        dead_channel_alarm_sent=set(),
    )
    engine = InterlockEngine(
        broker,
        actions={"emergency_off": noop, "stop_source": noop},
        trip_handler=lambda condition, reading: _interlock_trip_handler(
            condition,
            reading,
            context=context,
        ),
        trip_admission=lambda condition, reading: _interlock_trip_admission(
            condition,
            reading,
            context=context,
        ),
    )
    engine.load_config(
        INTERLOCKS_PATH,
        descriptor_catalog=catalog,
        poll_intervals_s_by_instrument=POLL_INTERVALS,
    )
    await engine.start()
    try:
        overtemp = Reading.now("Т1 Криостат верх", 320.1, "K", instrument_id="LS218_1")
        await _publish_bound_sensor(broker, catalog, overtemp)
        await asyncio.sleep(0.05)
        assert safety.calls == []
        assert engine.get_state()["source_overtemp"] is InterlockState.ARMED

        safety.state = "running"
        await _publish_bound_sensor(broker, catalog, overtemp)
        await asyncio.sleep(0.05)
        assert safety.calls == [("source_overtemp", "Т1", 320.1, "stop_source")]
        assert engine.get_state()["source_overtemp"] is InterlockState.TRIPPED
    finally:
        await engine.stop()


async def test_detector_warning_rearms_and_refires_after_cold_recovery() -> None:
    class SafetyProbe:
        def get_status(self) -> dict[str, str]:
            return {"state": "ready"}

        async def on_interlock_trip(self, *_args, **_kwargs) -> None:
            raise AssertionError("detector warning must not acquire control authority")

        async def latch_fault(self, **_kwargs) -> None:
            raise AssertionError("operator warning routing must remain available")

    catalog = load_live_channel_descriptor_catalog(DESCRIPTORS_PATH)
    broker = DataBroker()
    bus = EventBus()
    queue = await bus.subscribe("detector-warning-refire-test")
    alarm_state_manager = AlarmStateManager()
    context = _InterlockHandlerContext(
        safety_manager=SafetyProbe(),
        alarm_dispatch_tasks=set(),
        dead_channel_alarm_sent=set(),
        event_bus=bus,
        experiment_manager=SimpleNamespace(active_experiment_id="measurement-1"),
        alarm_state_manager=alarm_state_manager,
    )
    engine = InterlockEngine(
        broker,
        actions={"emergency_off": lambda: None, "stop_source": lambda: None},
        trip_handler=lambda condition, reading: _interlock_trip_handler(
            condition,
            reading,
            context=context,
        ),
        trip_admission=lambda condition, reading: _interlock_trip_admission(
            condition,
            reading,
            context=context,
        ),
        warning_recovery_handler=lambda condition, reading: _interlock_warning_recovery_handler(
            condition,
            reading,
            context=context,
        ),
    )
    engine.load_config(
        INTERLOCKS_PATH,
        descriptor_catalog=catalog,
        poll_intervals_s_by_instrument=POLL_INTERVALS,
    )
    await engine.start()
    try:
        warm = Reading.now("Т12 Теплообменник 2", 12.0, "K", instrument_id="LS218_2")
        cold = Reading.now("Т12 Теплообменник 2", 5.0, "K", instrument_id="LS218_2")

        await _publish_bound_sensor(broker, catalog, warm)
        await asyncio.sleep(0.05)
        first = queue.get_nowait()
        first_activation = alarm_state_manager.get_active()["detector_warmup"].activation_id
        assert first.payload["alarm_id"] == "detector_warmup"
        assert engine.get_state()["detector_warmup"] is InterlockState.TRIPPED

        # Advance the notification window without adding a five-second wall-clock
        # delay. The test still drives the production recovery and refire paths.
        record = engine._interlocks["detector_warmup"]
        assert record.last_trip_time is not None
        record.last_trip_time -= timedelta(seconds=record.condition.cooldown_s + 1.0)

        await _publish_bound_sensor(broker, catalog, cold)
        await asyncio.sleep(0.05)
        assert engine.get_state()["detector_warmup"] is InterlockState.ARMED
        assert "detector_warmup" not in alarm_state_manager.get_active()

        await _publish_bound_sensor(broker, catalog, warm)
        await asyncio.sleep(0.05)
        second = queue.get_nowait()
        second_activation = alarm_state_manager.get_active()["detector_warmup"].activation_id
        assert second.payload["alarm_id"] == "detector_warmup"
        assert second_activation > first_activation
        assert engine.get_state()["detector_warmup"] is InterlockState.TRIPPED
    finally:
        await engine.stop()


async def test_detector_warning_cold_blip_does_not_refire_within_cooldown() -> None:
    class SafetyProbe:
        def get_status(self) -> dict[str, str]:
            return {"state": "ready"}

        async def on_interlock_trip(self, *_args, **_kwargs) -> None:
            raise AssertionError("detector warning must not acquire control authority")

        async def latch_fault(self, **_kwargs) -> None:
            raise AssertionError("operator warning routing must remain available")

    catalog = load_live_channel_descriptor_catalog(DESCRIPTORS_PATH)
    broker = DataBroker()
    bus = EventBus()
    queue = await bus.subscribe("detector-warning-cooldown-test")
    alarm_state_manager = AlarmStateManager()
    context = _InterlockHandlerContext(
        safety_manager=SafetyProbe(),
        alarm_dispatch_tasks=set(),
        dead_channel_alarm_sent=set(),
        event_bus=bus,
        experiment_manager=SimpleNamespace(active_experiment_id="measurement-1"),
        alarm_state_manager=alarm_state_manager,
    )
    engine = InterlockEngine(
        broker,
        actions={"emergency_off": lambda: None, "stop_source": lambda: None},
        trip_handler=lambda condition, reading: _interlock_trip_handler(
            condition,
            reading,
            context=context,
        ),
        trip_admission=lambda condition, reading: _interlock_trip_admission(
            condition,
            reading,
            context=context,
        ),
        warning_recovery_handler=lambda condition, reading: _interlock_warning_recovery_handler(
            condition,
            reading,
            context=context,
        ),
    )
    engine.load_config(
        INTERLOCKS_PATH,
        descriptor_catalog=catalog,
        poll_intervals_s_by_instrument=POLL_INTERVALS,
    )
    await engine.start()
    try:
        warm = Reading.now("Т12 Теплообменник 2", 12.0, "K", instrument_id="LS218_2")
        cold = Reading.now("Т12 Теплообменник 2", 5.0, "K", instrument_id="LS218_2")

        await _publish_bound_sensor(broker, catalog, warm)
        await asyncio.sleep(0.05)
        first = queue.get_nowait()
        first_activation = alarm_state_manager.get_active()["detector_warmup"].activation_id
        assert first.payload["alarm_id"] == "detector_warmup"
        assert queue.empty()

        await _publish_bound_sensor(broker, catalog, cold)
        await asyncio.sleep(0.05)
        state_after_cold = engine.get_state()["detector_warmup"]
        active_after_cold = alarm_state_manager.get_active()

        await _publish_bound_sensor(broker, catalog, warm)
        await asyncio.sleep(0.05)
        assert queue.empty(), "warm/cold/warm inside cooldown must emit one alarm_fired event"
        assert state_after_cold is InterlockState.TRIPPED
        assert active_after_cold["detector_warmup"].activation_id == first_activation
        assert alarm_state_manager.get_active()["detector_warmup"].activation_id == first_activation
        assert engine.get_state()["detector_warmup"] is InterlockState.TRIPPED
    finally:
        await engine.stop()


def test_alarm_v2_has_no_phantom_detector_warmup_control() -> None:
    raw = yaml.safe_load(ALARMS_V3_PATH.read_text(encoding="utf-8"))
    assert "detector_warmup_interlock" not in (raw.get("interlocks") or {})

    _engine, alarms = load_alarm_config(ALARMS_V3_PATH)
    assert all(alarm.alarm_id != "detector_warmup_interlock" for alarm in alarms)


def test_emergency_off_rows_are_byte_unchanged() -> None:
    for name, expected_sha256 in _EMERGENCY_ROW_SHA256.items():
        assert hashlib.sha256(_row_bytes(name)).hexdigest() == expected_sha256

    entries = _interlocks()
    assert entries["overheat_cryostat"]["threshold"] == 350.0
    assert entries["overheat_cryostat"]["action"] == "emergency_off"
    assert entries["overheat_compressor"]["threshold"] == 320.0
    assert entries["overheat_compressor"]["action"] == "emergency_off"
