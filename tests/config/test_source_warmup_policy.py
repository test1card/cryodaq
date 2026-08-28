"""Owner-ratified warm-cryostat source policy regressions.

The production interlock configuration, descriptor authority, mock LakeShore
readings, and operator alarm dispatch are exercised together.  These tests do
not stand in for the still-open physical heater/dummy-load gates.
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from types import SimpleNamespace

import yaml

from cryodaq.channels.persistence import PersistedChannelEnvelopeV1
from cryodaq.core.alarm_config import load_alarm_config
from cryodaq.core.broker import DataBroker
from cryodaq.core.event_bus import EventBus
from cryodaq.core.interlock import InterlockEngine, InterlockState
from cryodaq.drivers.base import Reading
from cryodaq.drivers.instruments.lakeshore_218s import LakeShore218S
from cryodaq.engine import _interlock_trip_handler, _InterlockHandlerContext
from cryodaq.storage.channel_descriptors import load_live_channel_descriptor_catalog

ROOT = Path(__file__).resolve().parents[2]
INTERLOCKS_PATH = ROOT / "config" / "interlocks.yaml"
ALARMS_V3_PATH = ROOT / "config" / "alarms_v3.yaml"
DESCRIPTORS_PATH = ROOT / "config" / "channel_descriptors.yaml"
INSTRUMENTS_PATH = ROOT / "config" / "instruments.yaml"
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


async def test_detector_warmup_dispatches_operator_warning_without_control() -> None:
    bus = EventBus()
    queue = await bus.subscribe("detector-warning-test")

    class SafetyProbe:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, float, str]] = []

        async def on_interlock_trip(self, interlock_name, channel, value, *, action) -> None:
            self.calls.append((interlock_name, channel, value, action))

    safety = SafetyProbe()
    context = _InterlockHandlerContext(
        safety_manager=safety,
        alarm_dispatch_tasks=set(),
        dead_channel_alarm_sent=set(),
        event_bus=bus,
        experiment_manager=SimpleNamespace(active_experiment_id="measurement-1"),
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
    assert overtemp["threshold"] == 310.0
    assert overtemp["comparison"] == ">"
    assert overtemp["action"] == "stop_source"

    catalog = load_live_channel_descriptor_catalog(DESCRIPTORS_PATH)
    broker = DataBroker()
    stops: list[str] = []

    async def emergency_off() -> None:
        raise AssertionError("310.1 K must not cross the unchanged 350 K emergency tier")

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
        above_limit = Reading.now("Т1 Криостат верх", 310.1, "K", instrument_id="LS218_1")
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
