"""Verify interlock action differentiation (Phase 2a I.1).

finding: ``stop_source`` and ``emergency_off`` interlocks both
collapsed into a full latched fault path because the original engine.py
wrappers discarded the action name. After Phase 2a, the InterlockEngine's
new ``trip_handler`` callback delivers the full ``(condition, reading)``
context to ``SafetyManager.on_interlock_trip(action=...)``, which
differentiates the two actions.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.core.broker import DataBroker
from cryodaq.core.interlock import InterlockCondition, InterlockEngine, InterlockState
from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager, SafetyState
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.engine import _interlock_trip_handler, _InterlockHandlerContext


@pytest.fixture
async def mgr():
    safety_broker = SafetyBroker()
    keithley = MagicMock()
    keithley.emergency_off = AsyncMock(return_value=True)
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
    assert "FAULT" not in str(result.get("error", "")), f"request_run blocked by FAULT despite stop_source: {result}"


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

    async def trip_handler(condition, reading) -> bool:
        received.append((condition.action, condition.name, reading.channel, reading.value))
        return True

    # Action callable is a no-op — the real signal is the trip_handler.
    engine = InterlockEngine(
        broker=broker,
        action_names={"stop_source", "emergency_off"},
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


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["emergency_off", "stop_source"])
async def test_engine_authority_wiring_calls_safety_manager_once_per_trip(action: str) -> None:
    """The engine's installed handler retains action/context and has no second path."""
    manager = MagicMock()
    manager.on_interlock_trip = AsyncMock(return_value=True)
    context = _InterlockHandlerContext(
        safety_manager=manager,
        alarm_dispatch_tasks=set(),
        dead_channel_alarm_sent=set(),
    )
    condition = MagicMock(name="condition")
    condition.name = "trip"
    condition.action = action
    reading = MagicMock(name="reading")
    reading.channel = "T1"
    reading.value = 350.0

    assert await _interlock_trip_handler(condition, reading, context=context) is True
    manager.on_interlock_trip.assert_awaited_once_with(interlock_name="trip", channel="T1", value=350.0, action=action)


class _FakeKeithley:
    """Small final-element fake with exact emergency-OFF receipts."""

    def __init__(self, result: object = True, *, release: asyncio.Event | None = None) -> None:
        self.result = result
        self.release = release
        self.calls: list[str | None] = []
        self.started = asyncio.Event()
        self.connected = True
        self.output_state_unverified = False

    async def emergency_off(self, channel: str | None = None) -> object:
        self.calls.append(channel)
        self.started.set()
        if self.release is not None:
            await self.release.wait()
        return self.result


async def _settlement_manager(fake: _FakeKeithley) -> SafetyManager:
    manager = SafetyManager(SafetyBroker(), keithley_driver=fake, mock=True)
    await manager.start()
    manager.record_reviewed_source_connected(verified_off=True)
    manager._state = SafetyState.RUNNING
    manager._active_sources.add("smua")
    return manager


def _trip_condition(action: str = "emergency_off") -> InterlockCondition:
    return InterlockCondition(
        name="trip",
        description="trip",
        channel_pattern=r"T1",
        threshold=300.0,
        comparison=">",
        action=action,
    )


def _trip_reading() -> Reading:
    return Reading(
        channel="T1",
        value=350.0,
        unit="K",
        instrument_id="test",
        timestamp=datetime.now(UTC),
        status=ChannelStatus.OK,
        raw=350.0,
        metadata={},
    )


@pytest.mark.asyncio
async def test_emergency_interlock_returns_true_only_after_exact_global_off() -> None:
    fake = _FakeKeithley(True)
    manager = await _settlement_manager(fake)
    try:
        assert await manager.on_interlock_trip("trip", "T1", 350.0) is True
        assert fake.calls == [None]
        assert manager.state is SafetyState.FAULT_LATCHED
        assert manager.snapshot_operator_safety().verified_off is True
    finally:
        await manager.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("off_result", [False, None, 1], ids=["false", "unknown", "truthy-nonbool"])
async def test_unverified_emergency_interlock_never_logs_engine_success(
    off_result: object,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake = _FakeKeithley(off_result)
    manager = await _settlement_manager(fake)
    context = _InterlockHandlerContext(manager, set(), set())

    async def handler(condition: InterlockCondition, reading: Reading) -> bool:
        return await _interlock_trip_handler(condition, reading, context=context)

    engine = InterlockEngine(DataBroker(), {"emergency_off"}, trip_handler=handler)
    engine.add_condition(_trip_condition())
    try:
        with caplog.at_level(logging.CRITICAL, logger="cryodaq.core.interlock"):
            await engine._process_reading(_trip_reading())
        assert engine.get_state()["trip"] is InterlockState.TRIPPED
        assert manager.state is SafetyState.FAULT_LATCHED
        assert manager.snapshot_operator_safety().verified_off is False
        assert "authority result was not confirmed" in caplog.text
        assert "выполнено успешно" not in caplog.text
    finally:
        fake.result = True
        await manager.stop()


@pytest.mark.asyncio
async def test_stop_source_interlock_returns_true_only_for_safe_off() -> None:
    fake = _FakeKeithley(True)
    manager = await _settlement_manager(fake)
    try:
        assert await manager.on_interlock_trip("trip", "T1", 350.0, action="stop_source") is True
        assert fake.calls == [None]
        assert manager.state is SafetyState.SAFE_OFF
        assert manager._active_sources == set()
        assert manager.snapshot_operator_safety().verified_off is True
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_stop_source_interlock_failure_escalates_but_returns_false() -> None:
    fake = _FakeKeithley(False)
    manager = await _settlement_manager(fake)
    try:
        assert await manager.on_interlock_trip("trip", "T1", 350.0, action="stop_source") is False
        assert manager.state is SafetyState.FAULT_LATCHED
        assert manager.snapshot_operator_safety().verified_off is False
    finally:
        fake.result = True
        await manager.stop()


@pytest.mark.asyncio
async def test_interlock_cancellation_settles_owned_action_without_success() -> None:
    release = asyncio.Event()
    fake = _FakeKeithley(True, release=release)
    manager = await _settlement_manager(fake)
    task = asyncio.create_task(manager.on_interlock_trip("trip", "T1", 350.0, action="stop_source"))
    try:
        await fake.started.wait()
        task.cancel()
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert manager.state is SafetyState.SAFE_OFF
        assert manager._active_sources == set()
        assert fake.calls == [None]
    finally:
        release.set()
        await manager.stop()


@pytest.mark.asyncio
async def test_fallback_latch_returns_false_after_primary_exception() -> None:
    manager = MagicMock()
    manager.on_interlock_trip = AsyncMock(side_effect=RuntimeError("primary failure"))
    manager.latch_fault = AsyncMock()
    context = _InterlockHandlerContext(manager, set(), set())
    condition = MagicMock(name="condition")
    condition.name = "trip"
    condition.action = "emergency_off"
    reading = MagicMock(name="reading")
    reading.channel = "T1"
    reading.value = 350.0

    assert await _interlock_trip_handler(condition, reading, context=context) is False
    manager.latch_fault.assert_awaited_once()


@pytest.mark.asyncio
async def test_primary_exception_fallback_latch_never_confirms_interlock_success(
    caplog: pytest.LogCaptureFixture,
) -> None:
    manager = MagicMock()
    manager.on_interlock_trip = AsyncMock(side_effect=RuntimeError("primary failure"))
    manager.latch_fault = AsyncMock()
    context = _InterlockHandlerContext(manager, set(), set())

    async def handler(condition: InterlockCondition, reading: Reading) -> bool:
        return await _interlock_trip_handler(condition, reading, context=context)

    engine = InterlockEngine(DataBroker(), {"emergency_off"}, trip_handler=handler)
    engine.add_condition(_trip_condition())
    with caplog.at_level(logging.CRITICAL, logger="cryodaq.core.interlock"):
        await engine._process_reading(_trip_reading())

    manager.latch_fault.assert_awaited_once()
    assert engine.get_state()["trip"] is InterlockState.TRIPPED
    assert "authority result was not confirmed" in caplog.text
    assert "выполнено успешно" not in caplog.text
