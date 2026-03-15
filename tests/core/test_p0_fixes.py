"""Tests for P0 critical fixes.

P0-01: AlarmEngine publishes Reading to DataBroker on alarm events
P0-02: SafetyManager publishes state as Reading to DataBroker
P0-03: SafetyManager.request_run validates source parameter limits
P0-04: SafetyManager.emergency_off returns latched flag when FAULT_LATCHED
"""

from __future__ import annotations

import ast
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.core.alarm import AlarmCondition, AlarmEngine, AlarmSeverity
from cryodaq.core.broker import DataBroker
from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager, SafetyState
from cryodaq.drivers.base import ChannelStatus, Reading

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_keithley():
    k = MagicMock()
    k.connected = True
    k.emergency_off = AsyncMock()
    k.stop_source = AsyncMock()
    k.start_source = AsyncMock()
    return k


async def _make_safety(*, mock=True, keithley=None, data_broker=None):
    sb = SafetyBroker()
    mgr = SafetyManager(sb, keithley_driver=keithley, mock=mock, data_broker=data_broker)
    mgr._config.stale_timeout_s = 10.0
    mgr._config.cooldown_before_rearm_s = 0.1
    mgr._config.require_keithley_for_run = not mock
    await mgr.start()
    return mgr, sb


async def _feed_safety(broker: SafetyBroker, channel: str = "Т1 Криостат верх", value: float = 4.5):
    r = Reading.now(channel=channel, value=value, unit="K", instrument_id="test")
    await broker.publish(r)
    await asyncio.sleep(0.02)


def _alarm_condition(
    name: str = "test_alarm",
    channel_pattern: str = "sensor/temp",
    threshold: float = 100.0,
    comparison: str = ">",
    severity: AlarmSeverity = AlarmSeverity.WARNING,
    hysteresis_k: float = 10.0,
) -> AlarmCondition:
    return AlarmCondition(
        name=name,
        description=f"Test alarm: {name}",
        channel_pattern=channel_pattern,
        threshold=threshold,
        comparison=comparison,
        severity=severity,
        hysteresis_k=hysteresis_k,
    )


async def _drain_queue(queue: asyncio.Queue, *, timeout: float = 0.1) -> list[Reading]:
    """Drain all items from a queue within timeout."""
    items: list[Reading] = []
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            break
        try:
            item = await asyncio.wait_for(queue.get(), timeout=remaining)
            items.append(item)
        except asyncio.TimeoutError:
            break
    return items


# ---------------------------------------------------------------------------
# P0-01: AlarmEngine publishes Reading on alarm events
# ---------------------------------------------------------------------------


async def test_alarm_publishes_reading_on_activate() -> None:
    """AlarmEngine publishes a Reading to broker on alarm activation.

    Channel: alarm/{name}, metadata has event_type='activated', severity as string.
    """
    broker = DataBroker()
    test_q = await broker.subscribe(
        "test_alarm_activate",
        maxsize=100,
        filter_fn=lambda r: r.channel.startswith("alarm/"),
    )
    engine = AlarmEngine(broker=broker)
    engine.add_condition(
        _alarm_condition(name="high_temp", threshold=100.0, comparison=">", hysteresis_k=10.0)
    )
    await engine.start()
    try:
        # Trigger alarm: value=150 > threshold=100
        await broker.publish(Reading.now(channel="sensor/temp", value=150.0, unit="K", instrument_id="test"))
        await asyncio.sleep(0.05)

        readings = await _drain_queue(test_q, timeout=0.2)
        assert readings, "Expected at least one Reading published to broker on alarm activation"

        activated = [r for r in readings if r.metadata.get("event_type") == "activated"]
        assert activated, "No Reading with event_type='activated' found"

        r = activated[0]
        assert r.channel == "alarm/high_temp"
        assert r.metadata["event_type"] == "activated"
        # severity must be a string, NOT an enum
        assert isinstance(r.metadata["severity"], str)
        assert r.metadata["severity"] == "warning"
    finally:
        await engine.stop()


async def test_alarm_publishes_reading_on_clear() -> None:
    """AlarmEngine publishes a Reading with event_type='cleared' when alarm clears."""
    broker = DataBroker()
    test_q = await broker.subscribe(
        "test_alarm_clear",
        maxsize=100,
        filter_fn=lambda r: r.channel.startswith("alarm/"),
    )
    engine = AlarmEngine(broker=broker)
    # hysteresis_k=10: clears when value < 90
    engine.add_condition(
        _alarm_condition(name="high_temp", threshold=100.0, comparison=">", hysteresis_k=10.0)
    )
    await engine.start()
    try:
        # Activate
        await broker.publish(Reading.now(channel="sensor/temp", value=150.0, unit="K", instrument_id="test"))
        await asyncio.sleep(0.05)

        # Clear: value=80 < threshold - hysteresis_k = 90
        await broker.publish(Reading.now(channel="sensor/temp", value=80.0, unit="K", instrument_id="test"))
        await asyncio.sleep(0.05)

        readings = await _drain_queue(test_q, timeout=0.2)
        cleared = [r for r in readings if r.metadata.get("event_type") == "cleared"]
        assert cleared, "Expected a Reading with event_type='cleared'"
        assert cleared[0].channel == "alarm/high_temp"
    finally:
        await engine.stop()


async def test_alarm_publishes_alarm_count_on_activate() -> None:
    """AlarmEngine publishes analytics/alarm_count with value=1.0 when alarm activates."""
    broker = DataBroker()
    count_q = await broker.subscribe(
        "test_count_activate",
        maxsize=100,
        filter_fn=lambda r: r.channel == "analytics/alarm_count",
    )
    engine = AlarmEngine(broker=broker)
    engine.add_condition(
        _alarm_condition(name="high_temp", threshold=100.0, comparison=">", hysteresis_k=10.0)
    )
    await engine.start()
    try:
        # Trigger alarm
        await broker.publish(Reading.now(channel="sensor/temp", value=150.0, unit="K", instrument_id="test"))
        await asyncio.sleep(0.05)

        readings = await _drain_queue(count_q, timeout=0.2)
        # Find the count reading that shows 1 active alarm
        count_readings = [r for r in readings if r.value == pytest.approx(1.0)]
        assert count_readings, (
            f"Expected analytics/alarm_count Reading with value=1.0, got: "
            f"{[r.value for r in readings]}"
        )
    finally:
        await engine.stop()


async def test_alarm_publishes_alarm_count_on_clear() -> None:
    """AlarmEngine publishes analytics/alarm_count with value=0.0 after trigger→ack→clear."""
    broker = DataBroker()
    count_q = await broker.subscribe(
        "test_count_clear",
        maxsize=100,
        filter_fn=lambda r: r.channel == "analytics/alarm_count",
    )
    engine = AlarmEngine(broker=broker)
    # hysteresis_k=10: clears when value < 90
    engine.add_condition(
        _alarm_condition(name="high_temp", threshold=100.0, comparison=">", hysteresis_k=10.0)
    )
    await engine.start()
    try:
        # Activate
        await broker.publish(Reading.now(channel="sensor/temp", value=150.0, unit="K", instrument_id="test"))
        await asyncio.sleep(0.05)

        # Acknowledge
        engine.acknowledge("high_temp")
        await asyncio.sleep(0.02)

        # Clear: value=80 < 90
        await broker.publish(Reading.now(channel="sensor/temp", value=80.0, unit="K", instrument_id="test"))
        await asyncio.sleep(0.05)

        readings = await _drain_queue(count_q, timeout=0.2)
        # The last count reading after clear should be 0
        count_values = [r.value for r in readings]
        assert 0.0 in count_values, (
            f"Expected analytics/alarm_count=0.0 after clear, got history: {count_values}"
        )
    finally:
        await engine.stop()


async def test_alarm_no_feedback_loop() -> None:
    """AlarmEngine must not process readings from alarm/ channels (no feedback loop)."""
    broker = DataBroker()
    alarm_q = await broker.subscribe(
        "test_feedback",
        maxsize=100,
        filter_fn=lambda r: r.channel.startswith("alarm/"),
    )
    engine = AlarmEngine(broker=broker)
    # Condition matching "alarm/" prefix — this must NOT trigger on alarm/ channels
    engine.add_condition(
        AlarmCondition(
            name="alarm_feedback",
            description="Feedback test",
            channel_pattern="alarm/.*",
            threshold=0.0,
            comparison=">",
            severity=AlarmSeverity.WARNING,
            hysteresis_k=0.0,
        )
    )
    await engine.start()
    try:
        # Publish a Reading directly to an alarm/ channel — simulates what engine would publish
        alarm_reading = Reading.now(
            channel="alarm/alarm_feedback",
            value=1.0,
            unit="",
            instrument_id="test",
            metadata={"event_type": "activated", "severity": "warning"},
        )
        await broker.publish(alarm_reading)
        await asyncio.sleep(0.1)

        # Drain — if feedback loop exists, we'd see new alarm readings appear
        readings = await _drain_queue(alarm_q, timeout=0.15)
        # The only reading should be the one we published, not new engine-generated ones
        engine_generated = [
            r for r in readings
            if r is not alarm_reading
            and r.metadata.get("event_type") in ("activated", "cleared")
        ]
        assert not engine_generated, (
            f"Feedback loop detected! Engine generated new alarm readings: {engine_generated}"
        )
    finally:
        await engine.stop()


async def test_alarm_initial_count_zero() -> None:
    """AlarmEngine publishes analytics/alarm_count=0.0 on start (before any alarms)."""
    broker = DataBroker()
    count_q = await broker.subscribe(
        "test_initial_count",
        maxsize=100,
        filter_fn=lambda r: r.channel == "analytics/alarm_count",
    )
    engine = AlarmEngine(broker=broker)
    engine.add_condition(
        _alarm_condition(name="high_temp", threshold=100.0, comparison=">")
    )
    await engine.start()
    try:
        readings = await _drain_queue(count_q, timeout=0.2)
        assert readings, "Expected at least one analytics/alarm_count Reading on start"
        first = readings[0]
        assert first.value == pytest.approx(0.0), (
            f"Expected initial alarm count=0.0, got {first.value}"
        )
    finally:
        await engine.stop()


# ---------------------------------------------------------------------------
# P0-02: SafetyManager publishes state as Reading to DataBroker
# ---------------------------------------------------------------------------


async def test_safety_start_publishes_initial_state_safe_off() -> None:
    """SafetyManager publishes analytics/safety_state with state='safe_off' on start."""
    data_broker = DataBroker()
    state_q = await data_broker.subscribe(
        "test_safety_state_initial",
        maxsize=100,
        filter_fn=lambda r: r.channel == "analytics/safety_state",
    )
    mgr, sb = await _make_safety(data_broker=data_broker)
    try:
        readings = await _drain_queue(state_q, timeout=0.2)
        assert readings, "Expected analytics/safety_state Reading on start"
        safe_off_readings = [
            r for r in readings if r.metadata.get("state") == "safe_off"
        ]
        assert safe_off_readings, (
            f"Expected Reading with state='safe_off', got: "
            f"{[r.metadata.get('state') for r in readings]}"
        )
    finally:
        await mgr.stop()


async def test_safety_publishes_state_on_transition() -> None:
    """SafetyManager publishes analytics/safety_state when transitioning to RUNNING."""
    data_broker = DataBroker()
    state_q = await data_broker.subscribe(
        "test_safety_state_transition",
        maxsize=100,
        filter_fn=lambda r: r.channel == "analytics/safety_state",
    )
    mgr, sb = await _make_safety(data_broker=data_broker)
    try:
        # Feed data and wait for SAFE_OFF → READY
        await _feed_safety(sb)
        await asyncio.sleep(1.2)

        # Transition to RUNNING
        result = await mgr.request_run(1.0, 40.0, 1.0)
        assert result["ok"] is True
        await asyncio.sleep(0.05)

        readings = await _drain_queue(state_q, timeout=0.2)
        states = [r.metadata.get("state") for r in readings]
        assert "running" in states, (
            f"Expected Reading with state='running' after request_run, got states: {states}"
        )
    finally:
        await mgr.stop()


async def test_safety_publish_failure_does_not_crash() -> None:
    """SafetyManager must not crash if data_broker.publish raises an exception."""
    failing_broker = MagicMock()
    failing_broker.publish = AsyncMock(side_effect=RuntimeError("publish failed"))

    mgr, sb = await _make_safety(data_broker=failing_broker)
    try:
        # start() should not raise even with a failing broker
        assert mgr.state == SafetyState.SAFE_OFF

        # Transitions should still work
        await _feed_safety(sb)
        await asyncio.sleep(1.2)
        # State machine should still function despite broker publish failures
        assert mgr.state in (SafetyState.SAFE_OFF, SafetyState.READY)
    finally:
        await mgr.stop()


# ---------------------------------------------------------------------------
# P0-03: SafetyManager.request_run validates source parameter limits
# ---------------------------------------------------------------------------


async def _make_safety_ready(*, max_power_w: float = 5.0, max_voltage_v: float = 40.0, max_current_a: float = 1.0):
    """Create a SafetyManager in READY state with source limits configured."""
    mgr, sb = await _make_safety()
    # Configure source limits
    mgr._config.max_power_w = max_power_w
    mgr._config.max_voltage_v = max_voltage_v
    mgr._config.max_current_a = max_current_a

    # Get to READY
    await _feed_safety(sb)
    await asyncio.sleep(1.2)
    assert mgr.state == SafetyState.READY, f"Expected READY, got {mgr.state}"
    return mgr, sb


async def test_request_run_rejects_over_power_limit() -> None:
    """request_run returns ok=False when p_target exceeds max_power_w."""
    mgr, sb = await _make_safety_ready(max_power_w=5.0)
    try:
        result = await mgr.request_run(p_target=10.0, v_comp=40.0, i_comp=1.0)
        assert result["ok"] is False, "Expected rejection when p_target > max_power_w"
        error = result.get("error", "")
        assert "P" in error or "мощ" in error.lower() or "power" in error.lower(), (
            f"Error message should mention power limit, got: '{error}'"
        )
    finally:
        await mgr.stop()


async def test_request_run_rejects_over_voltage_limit() -> None:
    """request_run returns ok=False when v_comp exceeds max_voltage_v."""
    mgr, sb = await _make_safety_ready(max_voltage_v=40.0)
    try:
        result = await mgr.request_run(p_target=1.0, v_comp=50.0, i_comp=1.0)
        assert result["ok"] is False, "Expected rejection when v_comp > max_voltage_v"
        error = result.get("error", "")
        assert error, "Expected a non-empty error message"
    finally:
        await mgr.stop()


async def test_request_run_rejects_over_current_limit() -> None:
    """request_run returns ok=False when i_comp exceeds max_current_a."""
    mgr, sb = await _make_safety_ready(max_current_a=1.0)
    try:
        result = await mgr.request_run(p_target=1.0, v_comp=40.0, i_comp=2.0)
        assert result["ok"] is False, "Expected rejection when i_comp > max_current_a"
        error = result.get("error", "")
        assert error, "Expected a non-empty error message"
    finally:
        await mgr.stop()


async def test_request_run_accepts_exact_limits() -> None:
    """request_run returns ok=True when parameters equal the limits (== is allowed)."""
    mgr, sb = await _make_safety_ready(
        max_power_w=5.0, max_voltage_v=40.0, max_current_a=1.0
    )
    try:
        result = await mgr.request_run(p_target=5.0, v_comp=40.0, i_comp=1.0)
        assert result["ok"] is True, (
            f"Expected acceptance at exact limits, got: {result}"
        )
        assert mgr.state == SafetyState.RUNNING
    finally:
        await mgr.stop()


# ---------------------------------------------------------------------------
# P0-04: emergency_off returns latched flag when in FAULT_LATCHED
# ---------------------------------------------------------------------------


async def test_emergency_off_returns_latched_flag_in_fault() -> None:
    """emergency_off() returns latched=True and a warning string when FAULT_LATCHED."""
    mgr, sb = await _make_safety()
    try:
        # Force FAULT_LATCHED
        await mgr._fault("Тест аварии P0-04")
        assert mgr.state == SafetyState.FAULT_LATCHED

        result = await mgr.emergency_off()

        assert result.get("latched") is True, (
            f"Expected latched=True in response, got: {result}"
        )
        warning = result.get("warning", "")
        assert warning, (
            f"Expected a non-empty warning string when latched, got: {result}"
        )
        # FAULT_LATCHED state must be preserved after emergency_off
        assert mgr.state == SafetyState.FAULT_LATCHED, (
            f"FAULT_LATCHED must be preserved after emergency_off, got: {mgr.state}"
        )
    finally:
        await mgr.stop()
