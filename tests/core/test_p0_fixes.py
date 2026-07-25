"""Tests for P0 critical fixes.

P0-01 (AlarmEngine v1 Reading-publish behavior) retired with alarm.py in the
alarm v1->v2 migration; see tests/core/test_engine_alarm_ring_buffer.py and
tests/core/test_alarm_v2_integration.py for the v2-equivalent coverage.
P0-02: SafetyManager publishes state as Reading to DataBroker
P0-03: SafetyManager.request_run validates source parameter limits
P0-04: SafetyManager.emergency_off returns latched flag when FAULT_LATCHED
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.core.broker import DataBroker
from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager, SafetyState
from cryodaq.drivers.base import Reading

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_keithley():
    k = MagicMock()
    k.connected = True
    k.output_state_unverified = False  # MagicMock attrs are truthy; declare the real default
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


async def _drain_queue(queue: asyncio.Queue, *, timeout: float = 0.1) -> list[Reading]:  # noqa: ASYNC109
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
        except TimeoutError:
            break
    return items


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
        safe_off_readings = [r for r in readings if r.metadata.get("state") == "safe_off"]
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
    """SafetyManager must not crash if data_broker.publish raises an exception.

    Verifies three things:
    1. publish is actually called BEYOND the start() baseline — the transition
       triggers additional publish calls, not just the initial one.
    2. The state machine transitions SAFE_OFF → READY despite publish failures.
    3. No exception propagates out of start() or state transitions.
    """
    failing_broker = MagicMock()
    failing_broker.publish = AsyncMock(side_effect=RuntimeError("publish failed"))

    mgr, sb = await _make_safety(data_broker=failing_broker)
    try:
        # start() should not raise even with a failing broker
        assert mgr.state == SafetyState.SAFE_OFF

        # Capture publish call count AFTER start() — any calls here are from the
        # initial state publication, not from a transition yet.
        baseline_count = failing_broker.publish.await_count

        # Feed a healthy reading to trigger SAFE_OFF → READY transition
        await _feed_safety(sb)

        # Deadline-poll until BOTH the state reaches READY AND the transition's
        # publish attempt has actually landed (up to 2 s). The state flips to
        # READY synchronously, but the READY-state publish is an awaited task that
        # can lag under load — polling on the publish count too (not just the
        # state) removes the race where await_count is read before that task runs.
        deadline = asyncio.get_event_loop().time() + 2.0
        while not (
            mgr.state == SafetyState.READY
            and failing_broker.publish.await_count > baseline_count
        ):
            if asyncio.get_event_loop().time() >= deadline:
                break
            await asyncio.sleep(0.05)

        # State machine must reach READY despite failing broker
        assert mgr.state == SafetyState.READY, (
            f"Expected READY after healthy feed, got {mgr.state}"
        )

        # publish must have been called BEYOND the post-start baseline,
        # proving the SAFE_OFF → READY transition triggered a publish attempt
        # (which was swallowed, not crashed).
        assert failing_broker.publish.await_count > baseline_count, (
            f"Expected data_broker.publish to be called beyond baseline "
            f"({baseline_count}), got await_count={failing_broker.publish.await_count}"
        )
    finally:
        await mgr.stop()


# ---------------------------------------------------------------------------
# P0-03: SafetyManager.request_run validates source parameter limits
# ---------------------------------------------------------------------------


async def _make_safety_ready(
    *, max_power_w: float = 5.0, max_voltage_v: float = 40.0, max_current_a: float = 1.0
):
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
    mgr, sb = await _make_safety_ready(max_power_w=5.0, max_voltage_v=40.0, max_current_a=1.0)
    try:
        result = await mgr.request_run(p_target=5.0, v_comp=40.0, i_comp=1.0)
        assert result["ok"] is True, f"Expected acceptance at exact limits, got: {result}"
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

        assert result.get("latched") is True, f"Expected latched=True in response, got: {result}"
        warning = result.get("warning", "")
        assert warning, f"Expected a non-empty warning string when latched, got: {result}"
        # FAULT_LATCHED state must be preserved after emergency_off
        assert mgr.state == SafetyState.FAULT_LATCHED, (
            f"FAULT_LATCHED must be preserved after emergency_off, got: {mgr.state}"
        )
    finally:
        await mgr.stop()
