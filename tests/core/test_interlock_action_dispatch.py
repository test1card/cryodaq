"""Verify interlock action differentiation (Phase 2a Codex I.1).

Codex finding: ``stop_source`` and ``emergency_off`` interlocks both
collapsed into a full latched fault path because the original engine.py
wrappers discarded the action name. After Phase 2a, the InterlockEngine's
new ``trip_handler`` callback delivers the full ``(condition, reading)``
context to ``SafetyManager.on_interlock_trip(action=...)``, which
differentiates the two actions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager, SafetyState


@pytest.fixture
async def mgr():
    safety_broker = SafetyBroker()
    keithley = MagicMock()
    keithley.emergency_off = AsyncMock()
    keithley.start_source = AsyncMock()
    keithley.stop_source = AsyncMock()

    m = SafetyManager(safety_broker, keithley_driver=keithley, mock=True)
    m._config.cooldown_before_rearm_s = 0.0
    m._config.require_reason = False

    await m.start()
    # Pretend we are RUNNING with smua active.
    m._state = SafetyState.RUNNING
    m._active_sources.add("smua")
    try:
        yield m
    finally:
        await m.stop()


@pytest.mark.asyncio
async def test_emergency_off_interlock_latches_fault(mgr):
    await mgr.on_interlock_trip(
        interlock_name="overheat_cryostat",
        channel="Т1 Криостат верх",
        value=360.0,
        action="emergency_off",
    )
    assert mgr.state == SafetyState.FAULT_LATCHED
    assert mgr.fault_reason != ""
    mgr._keithley.emergency_off.assert_awaited()


@pytest.mark.asyncio
async def test_stop_source_interlock_does_not_latch(mgr):
    await mgr.on_interlock_trip(
        interlock_name="detector_warmup",
        channel="Т12",
        value=15.0,
        action="stop_source",
    )
    # Outputs off, but no fault latch — operator can restart immediately.
    assert mgr.state != SafetyState.FAULT_LATCHED
    assert mgr.state == SafetyState.SAFE_OFF
    mgr._keithley.emergency_off.assert_awaited()
    assert mgr._active_sources == set()


@pytest.mark.asyncio
async def test_stop_source_allows_request_run_after(mgr):
    """After stop_source interlock, request_run should not be blocked by FAULT."""
    await mgr.on_interlock_trip(
        interlock_name="detector_warmup",
        channel="Т12",
        value=15.0,
        action="stop_source",
    )
    # The state machine is now SAFE_OFF, not FAULT_LATCHED. request_run
    # should be permitted (no FAULT prefix in error). It may still be
    # blocked by other preconditions in mock mode, but NOT by fault latch.
    result = await mgr.request_run(
        p_target=1.0,
        v_comp=10.0,
        i_comp=0.1,
        channel="smua",
    )
    assert "FAULT" not in str(result.get("error", "")), (
        f"request_run blocked by FAULT despite stop_source: {result}"
    )


@pytest.mark.asyncio
async def test_unknown_action_escalates_to_fault(mgr):
    await mgr.on_interlock_trip(
        interlock_name="weird",
        channel="Т1",
        value=1.0,
        action="totally_made_up_action",
    )
    assert mgr.state == SafetyState.FAULT_LATCHED


@pytest.mark.asyncio
async def test_default_action_is_emergency_off(mgr):
    """Backwards compatibility: omitting action keyword defaults to emergency_off."""
    await mgr.on_interlock_trip(
        interlock_name="legacy",
        channel="Т1",
        value=999.0,
    )
    assert mgr.state == SafetyState.FAULT_LATCHED


# ---- InterlockEngine trip_handler integration ----


@pytest.mark.asyncio
async def test_interlock_engine_trip_handler_receives_full_context():
    """End-to-end: InterlockEngine._trip must call trip_handler with the
    real condition + reading, not the discarded zero-arg shim."""
    from cryodaq.core.broker import DataBroker
    from cryodaq.core.interlock import (
        InterlockCondition,
        InterlockEngine,
    )
    from cryodaq.drivers.base import ChannelStatus, Reading

    broker = DataBroker()

    received: list[tuple[str, str, str, float]] = []

    async def trip_handler(condition, reading) -> None:
        received.append((condition.action, condition.name, reading.channel, reading.value))

    # Action callable is a no-op — the real signal is the trip_handler.
    async def noop() -> None:
        return None

    engine = InterlockEngine(
        broker=broker,
        actions={"stop_source": noop, "emergency_off": noop},
        trip_handler=trip_handler,
    )

    cond = InterlockCondition(
        name="detector_warmup",
        description="T12 too warm",
        channel_pattern=r".*Т12.*",
        threshold=10.0,
        comparison=">",
        action="stop_source",
        cooldown_s=0.0,
    )
    engine.add_condition(cond)

    # Drive _process_reading directly.
    rd = Reading(
        channel="lakeshore/Т12",
        value=15.0,
        unit="K",
        instrument_id="ls",
        timestamp=datetime.now(UTC),
        status=ChannelStatus.OK,
        raw=15.0,
        metadata={},
    )
    await engine._process_reading(rd)

    assert received == [("stop_source", "detector_warmup", "lakeshore/Т12", 15.0)], (
        f"trip_handler did not receive expected context: {received}"
    )
