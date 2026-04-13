"""Tests for AlarmEngine — threshold monitoring, state transitions, notifiers."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml

from cryodaq.core.alarm import (
    AlarmCondition,
    AlarmEngine,
    AlarmEvent,
    AlarmSeverity,
    AlarmState,
)
from cryodaq.core.broker import DataBroker
from cryodaq.drivers.base import Reading

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _condition(
    name: str = "test_alarm",
    channel_pattern: str = "sensor/temp",
    threshold: float = 100.0,
    comparison: str = ">",
    severity: AlarmSeverity = AlarmSeverity.WARNING,
    hysteresis_k: float = 0.0,
    enabled: bool = True,
    description: str = "Test alarm",
) -> AlarmCondition:
    return AlarmCondition(
        name=name,
        description=description,
        channel_pattern=channel_pattern,
        threshold=threshold,
        comparison=comparison,
        severity=severity,
        hysteresis_k=hysteresis_k,
        enabled=enabled,
    )


async def _make_engine(
    *conditions: AlarmCondition,
    notifiers=None,
) -> tuple[AlarmEngine, DataBroker]:
    broker = DataBroker()
    engine = AlarmEngine(broker=broker, notifiers=notifiers or [])
    for cond in conditions:
        engine.add_condition(cond)
    await engine.start()
    return engine, broker


async def _publish_and_wait(
    broker: DataBroker,
    channel: str,
    value: float,
    unit: str = "K",
    delay: float = 0.05,
) -> None:
    await broker.publish(Reading.now(channel, value, unit, instrument_id="test"))
    await asyncio.sleep(delay)


# ---------------------------------------------------------------------------
# 1. OK → ACTIVE transition
# ---------------------------------------------------------------------------

async def test_ok_to_active_transition() -> None:
    engine, broker = await _make_engine(_condition(threshold=100.0, comparison=">"))
    try:
        assert engine.get_state()["test_alarm"] == AlarmState.OK
        await _publish_and_wait(broker, "sensor/temp", 105.0)
        assert engine.get_state()["test_alarm"] == AlarmState.ACTIVE
    finally:
        await engine.stop()


# ---------------------------------------------------------------------------
# 2. ACTIVE → ACKNOWLEDGED
# ---------------------------------------------------------------------------

async def test_active_to_acknowledged() -> None:
    engine, broker = await _make_engine(_condition(threshold=100.0, comparison=">"))
    try:
        await _publish_and_wait(broker, "sensor/temp", 110.0)
        assert engine.get_state()["test_alarm"] == AlarmState.ACTIVE

        await engine.acknowledge("test_alarm")
        assert engine.get_state()["test_alarm"] == AlarmState.ACKNOWLEDGED
    finally:
        await engine.stop()


# ---------------------------------------------------------------------------
# 3. ACTIVE → OK requires clearing hysteresis band
# ---------------------------------------------------------------------------

async def test_active_cleared_with_hysteresis() -> None:
    # threshold=100, hysteresis_k=5 → clears only when value < 95
    engine, broker = await _make_engine(
        _condition(threshold=100.0, comparison=">", hysteresis_k=5.0)
    )
    try:
        await _publish_and_wait(broker, "sensor/temp", 110.0)
        assert engine.get_state()["test_alarm"] == AlarmState.ACTIVE

        # value=96 is below threshold but still within hysteresis band → stays ACTIVE
        await _publish_and_wait(broker, "sensor/temp", 96.0)
        assert engine.get_state()["test_alarm"] == AlarmState.ACTIVE

        # value=94 is below threshold - hysteresis_k (95) → clears
        await _publish_and_wait(broker, "sensor/temp", 94.0)
        assert engine.get_state()["test_alarm"] == AlarmState.OK
    finally:
        await engine.stop()


# ---------------------------------------------------------------------------
# 4. ACKNOWLEDGED → OK when value clears with hysteresis
# ---------------------------------------------------------------------------

async def test_acknowledged_cleared() -> None:
    engine, broker = await _make_engine(
        _condition(threshold=100.0, comparison=">", hysteresis_k=5.0)
    )
    try:
        await _publish_and_wait(broker, "sensor/temp", 110.0)
        await engine.acknowledge("test_alarm")
        assert engine.get_state()["test_alarm"] == AlarmState.ACKNOWLEDGED

        # Value fully below hysteresis band → transition to OK
        await _publish_and_wait(broker, "sensor/temp", 90.0)
        assert engine.get_state()["test_alarm"] == AlarmState.OK
    finally:
        await engine.stop()


# ---------------------------------------------------------------------------
# 5. Value between threshold and threshold-hysteresis stays ACTIVE
# ---------------------------------------------------------------------------

async def test_no_clear_within_hysteresis() -> None:
    engine, broker = await _make_engine(
        _condition(threshold=100.0, comparison=">", hysteresis_k=10.0)
    )
    try:
        await _publish_and_wait(broker, "sensor/temp", 105.0)
        assert engine.get_state()["test_alarm"] == AlarmState.ACTIVE

        # 95 is inside [90, 100] hysteresis dead-band → stays ACTIVE
        await _publish_and_wait(broker, "sensor/temp", 95.0)
        assert engine.get_state()["test_alarm"] == AlarmState.ACTIVE

        # 99 is still above threshold-hysteresis (90) but below threshold → stays ACTIVE
        await _publish_and_wait(broker, "sensor/temp", 99.0)
        assert engine.get_state()["test_alarm"] == AlarmState.ACTIVE
    finally:
        await engine.stop()


# ---------------------------------------------------------------------------
# 6. All severity levels work correctly
# ---------------------------------------------------------------------------

async def test_severity_levels() -> None:
    conditions = [
        _condition(name="info_alarm", threshold=10.0, comparison=">",
                   severity=AlarmSeverity.INFO),
        _condition(name="warning_alarm", threshold=20.0, comparison=">",
                   severity=AlarmSeverity.WARNING),
        _condition(name="critical_alarm", threshold=30.0, comparison=">",
                   severity=AlarmSeverity.CRITICAL),
    ]
    engine, broker = await _make_engine(*conditions)
    try:
        await _publish_and_wait(broker, "sensor/temp", 35.0)

        state = engine.get_state()
        assert state["info_alarm"] == AlarmState.ACTIVE
        assert state["warning_alarm"] == AlarmState.ACTIVE
        assert state["critical_alarm"] == AlarmState.ACTIVE

        events = engine.get_events()
        activated = [e for e in events if e.event_type == "activated"]
        severities = {e.alarm_name: e.severity for e in activated}
        assert severities["info_alarm"] == AlarmSeverity.INFO
        assert severities["warning_alarm"] == AlarmSeverity.WARNING
        assert severities["critical_alarm"] == AlarmSeverity.CRITICAL
    finally:
        await engine.stop()


# ---------------------------------------------------------------------------
# 7. Notifier is called on alarm activation
# ---------------------------------------------------------------------------

async def test_notifier_called_on_activate() -> None:
    captured: list[AlarmEvent] = []

    async def mock_notifier(event: AlarmEvent) -> None:
        captured.append(event)

    engine, broker = await _make_engine(
        _condition(threshold=50.0, comparison=">"),
        notifiers=[mock_notifier],
    )
    try:
        await _publish_and_wait(broker, "sensor/temp", 60.0)

        assert len(captured) == 1
        evt = captured[0]
        assert evt.event_type == "activated"
        assert evt.alarm_name == "test_alarm"
        assert evt.value == pytest.approx(60.0)
        assert evt.threshold == pytest.approx(50.0)
        assert evt.severity == AlarmSeverity.WARNING
        assert evt.channel == "sensor/temp"
    finally:
        await engine.stop()


# ---------------------------------------------------------------------------
# 8. Notifier is called on alarm clear
# ---------------------------------------------------------------------------

async def test_notifier_called_on_clear() -> None:
    captured: list[AlarmEvent] = []

    async def mock_notifier(event: AlarmEvent) -> None:
        captured.append(event)

    engine, broker = await _make_engine(
        _condition(threshold=50.0, comparison=">", hysteresis_k=0.0),
        notifiers=[mock_notifier],
    )
    try:
        await _publish_and_wait(broker, "sensor/temp", 60.0)
        assert len(captured) == 1
        assert captured[0].event_type == "activated"

        # Value below threshold (no hysteresis) → clears
        await _publish_and_wait(broker, "sensor/temp", 40.0)
        assert len(captured) == 2
        assert captured[1].event_type == "cleared"
        assert captured[1].alarm_name == "test_alarm"
    finally:
        await engine.stop()


# ---------------------------------------------------------------------------
# 9. Failing notifier doesn't block others
# ---------------------------------------------------------------------------

async def test_notifier_error_isolated() -> None:
    good_calls: list[AlarmEvent] = []

    async def bad_notifier(event: AlarmEvent) -> None:
        raise RuntimeError("Simulated notifier failure")

    async def good_notifier(event: AlarmEvent) -> None:
        good_calls.append(event)

    engine, broker = await _make_engine(
        _condition(threshold=50.0, comparison=">"),
        notifiers=[bad_notifier, good_notifier],
    )
    try:
        # Should not raise despite bad_notifier throwing
        await _publish_and_wait(broker, "sensor/temp", 60.0)

        assert len(good_calls) == 1
        assert good_calls[0].event_type == "activated"
    finally:
        await engine.stop()


# ---------------------------------------------------------------------------
# 10. Load config from YAML
# ---------------------------------------------------------------------------

async def test_load_config_from_yaml(tmp_path: Path) -> None:
    config = {
        "alarms": [
            {
                "name": "yaml_alarm_1",
                "description": "Temperature too high",
                "channel_pattern": "ls218s/ch1",
                "threshold": 300.0,
                "comparison": ">",
                "severity": "CRITICAL",
                "hysteresis_k": 10.0,
                "enabled": True,
            },
            {
                "name": "yaml_alarm_2",
                "description": "Pressure too low",
                "channel_pattern": "vacuum/p1",
                "threshold": 0.001,
                "comparison": "<",
                "severity": "WARNING",
                "hysteresis_k": 0.0,
                "enabled": False,
            },
        ]
    }
    config_file = tmp_path / "alarms.yaml"
    config_file.write_text(yaml.dump(config), encoding="utf-8")

    broker = DataBroker()
    engine = AlarmEngine(broker=broker)
    engine.load_config(config_file)

    state = engine.get_state()
    assert "yaml_alarm_1" in state
    assert "yaml_alarm_2" in state

    cond1 = engine._alarms["yaml_alarm_1"].condition
    assert cond1.threshold == pytest.approx(300.0)
    assert cond1.comparison == ">"
    assert cond1.severity == AlarmSeverity.CRITICAL
    assert cond1.hysteresis_k == pytest.approx(10.0)
    assert cond1.enabled is True

    cond2 = engine._alarms["yaml_alarm_2"].condition
    assert cond2.comparison == "<"
    assert cond2.severity == AlarmSeverity.WARNING
    assert cond2.enabled is False


# ---------------------------------------------------------------------------
# 11. Event history is bounded at 1000 entries
# ---------------------------------------------------------------------------

async def test_event_history_bounded() -> None:
    # Each activate+clear cycle produces 2 events; 600 cycles → 1200 events,
    # but deque(maxlen=1000) caps it at 1000.
    engine, broker = await _make_engine(
        _condition(threshold=50.0, comparison=">", hysteresis_k=0.0)
    )
    try:
        for _ in range(600):
            await broker.publish(Reading.now("sensor/temp", 60.0, "K", instrument_id="test"))
            await broker.publish(Reading.now("sensor/temp", 40.0, "K", instrument_id="test"))

        # Allow the check loop to drain the queue
        await asyncio.sleep(0.2)

        events = engine.get_events()
        assert len(events) <= 1000
    finally:
        await engine.stop()


# ---------------------------------------------------------------------------
# 12. Multiple alarms on same channel, different thresholds
# ---------------------------------------------------------------------------

async def test_multiple_alarms_simultaneous() -> None:
    cond_low = _condition(
        name="alarm_low",
        channel_pattern="sensor/temp",
        threshold=50.0,
        comparison=">",
    )
    cond_high = _condition(
        name="alarm_high",
        channel_pattern="sensor/temp",
        threshold=100.0,
        comparison=">",
    )
    engine, broker = await _make_engine(cond_low, cond_high)
    try:
        # Value crosses only the lower threshold
        await _publish_and_wait(broker, "sensor/temp", 75.0)
        state = engine.get_state()
        assert state["alarm_low"] == AlarmState.ACTIVE
        assert state["alarm_high"] == AlarmState.OK

        # Value crosses both thresholds
        await _publish_and_wait(broker, "sensor/temp", 120.0)
        state = engine.get_state()
        assert state["alarm_low"] == AlarmState.ACTIVE   # still ACTIVE (already was)
        assert state["alarm_high"] == AlarmState.ACTIVE

        # Value drops well below both thresholds
        await _publish_and_wait(broker, "sensor/temp", 10.0)
        state = engine.get_state()
        assert state["alarm_low"] == AlarmState.OK
        assert state["alarm_high"] == AlarmState.OK
    finally:
        await engine.stop()


# ---------------------------------------------------------------------------
# 13. Rapid oscillation across threshold produces correct transitions
# ---------------------------------------------------------------------------

async def test_rapid_oscillation() -> None:
    engine, broker = await _make_engine(
        _condition(threshold=50.0, comparison=">", hysteresis_k=0.0)
    )
    try:
        activation_count_before = engine._alarms["test_alarm"].activation_count

        # Alternate above/below threshold several times
        transitions = [60.0, 40.0, 60.0, 40.0, 60.0, 40.0]
        for v in transitions:
            await broker.publish(Reading.now("sensor/temp", v, "K", instrument_id="test"))
        await asyncio.sleep(0.1)

        # 3 above-threshold values → 3 activations total (each from OK)
        record = engine._alarms["test_alarm"]
        assert record.activation_count == activation_count_before + 3
        assert record.state == AlarmState.OK
    finally:
        await engine.stop()


# ---------------------------------------------------------------------------
# 14. comparison="<" — alarm when value drops below threshold
# ---------------------------------------------------------------------------

async def test_less_than_comparison() -> None:
    # Alarm fires when value < 10.0, clears when value > 10.0 + hysteresis_k
    engine, broker = await _make_engine(
        _condition(
            threshold=10.0,
            comparison="<",
            hysteresis_k=2.0,
            channel_pattern="sensor/pressure",
        )
    )
    try:
        # Value above threshold → OK
        await _publish_and_wait(broker, "sensor/pressure", 15.0)
        assert engine.get_state()["test_alarm"] == AlarmState.OK

        # Value below threshold → ACTIVE
        await _publish_and_wait(broker, "sensor/pressure", 8.0)
        assert engine.get_state()["test_alarm"] == AlarmState.ACTIVE

        # Value at 11.0 — above threshold but inside hysteresis band [10, 12] → still ACTIVE
        await _publish_and_wait(broker, "sensor/pressure", 11.0)
        assert engine.get_state()["test_alarm"] == AlarmState.ACTIVE

        # Value at 13.0 — above threshold + hysteresis_k (12.0) → clears
        await _publish_and_wait(broker, "sensor/pressure", 13.0)
        assert engine.get_state()["test_alarm"] == AlarmState.OK
    finally:
        await engine.stop()


# ---------------------------------------------------------------------------
# 15. Disabled alarm is never triggered
# ---------------------------------------------------------------------------

async def test_disabled_alarm_ignored() -> None:
    engine, broker = await _make_engine(
        _condition(threshold=50.0, comparison=">", enabled=False)
    )
    try:
        await _publish_and_wait(broker, "sensor/temp", 200.0)
        assert engine.get_state()["test_alarm"] == AlarmState.OK

        events = engine.get_events()
        assert len(events) == 0
    finally:
        await engine.stop()


# ---------------------------------------------------------------------------
# 16. Acknowledging an alarm not in ACTIVE state is a no-op
# ---------------------------------------------------------------------------

async def test_acknowledge_wrong_state() -> None:
    engine, broker = await _make_engine(_condition(threshold=50.0, comparison=">"))
    try:
        # Alarm is OK — acknowledging is a no-op, no exception raised
        await engine.acknowledge("test_alarm")
        assert engine.get_state()["test_alarm"] == AlarmState.OK

        # Activate, then acknowledge properly
        await _publish_and_wait(broker, "sensor/temp", 60.0)
        await engine.acknowledge("test_alarm")
        assert engine.get_state()["test_alarm"] == AlarmState.ACKNOWLEDGED

        # Acknowledging an already-ACKNOWLEDGED alarm is also a no-op
        await engine.acknowledge("test_alarm")
        assert engine.get_state()["test_alarm"] == AlarmState.ACKNOWLEDGED
    finally:
        await engine.stop()


# ---------------------------------------------------------------------------
# 17. Duplicate alarm name raises ValueError
# ---------------------------------------------------------------------------

async def test_duplicate_alarm_name_rejected() -> None:
    broker = DataBroker()
    engine = AlarmEngine(broker=broker)

    cond_a = _condition(name="duplicate")
    cond_b = _condition(name="duplicate", threshold=999.0)

    engine.add_condition(cond_a)

    with pytest.raises(ValueError, match="duplicate"):
        engine.add_condition(cond_b)
