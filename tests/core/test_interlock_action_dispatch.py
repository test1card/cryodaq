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
import functools
from collections import namedtuple
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.channels.persistence import PersistedChannelEnvelopeV1
from cryodaq.core.broker import DataBroker
from cryodaq.core.event_bus import EventBus
from cryodaq.core.interlock import InterlockEngine, InterlockState
from cryodaq.core.operator_log import OperatorLogEntry
from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager, SafetyState
from cryodaq.drivers.base import Reading
from cryodaq.drivers.contracts import (
    AcquisitionTiming,
    DriverTrustClass,
    SourceOffResult,
    _issue_registry_runtime_binding,
)
from cryodaq.engine import (
    _interlock_trip_handler,
    _InterlockHandlerContext,
    _persist_keithley_warning_choice_intent,
    _safety_fault_log_callback,
    _SafetyFaultLogContext,
)
from cryodaq.storage.channel_descriptors import load_live_channel_descriptor_catalog

ROOT = Path(__file__).resolve().parents[2]
INTERLOCKS_PATH = ROOT / "config" / "interlocks.yaml"
DESCRIPTORS_PATH = ROOT / "config" / "channel_descriptors.yaml"
POLL_INTERVALS = {"LS218_1": 2.0, "LS218_2": 2.0}


class _OperatorLogProbe:
    def __init__(self) -> None:
        self.entries: list[OperatorLogEntry] = []

    async def append_operator_log(self, **kwargs: object) -> OperatorLogEntry:
        entry = OperatorLogEntry(
            id=len(self.entries) + 1,
            timestamp=datetime.now(UTC),
            experiment_id=kwargs.get("experiment_id") if isinstance(kwargs.get("experiment_id"), str) else None,
            author=str(kwargs["author"]),
            source=str(kwargs["source"]),
            message=str(kwargs["message"]),
            tags=tuple(kwargs.get("tags", ())),
        )
        self.entries.append(entry)
        return entry


async def _publish_bound_interlock_reading(broker: DataBroker, value: float) -> None:
    catalog = load_live_channel_descriptor_catalog(DESCRIPTORS_PATH)
    bound = catalog.bind(
        Reading.now(
            "Т11 Теплообменник 1",
            value,
            "K",
            instrument_id="LS218_2",
        )
    )
    await broker.publish(
        bound.reading,
        persistence_authoritative=True,
        descriptor_envelope=PersistedChannelEnvelopeV1.from_descriptor(bound.descriptor).canonical_json,
    )


@pytest.fixture
async def mgr():
    safety_broker = SafetyBroker()
    keithley = MagicMock()
    keithley.emergency_off = AsyncMock(return_value=SourceOffResult.DEVICE_REPORTED_OFF)
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
async def test_shipped_emergency_interlock_cuts_warns_records_and_deliberate_start_proceeds() -> None:
    """The shipped hard alarm keeps its cut but cannot become a Start lockout."""

    operator_log = _OperatorLogProbe()
    event_bus = EventBus()
    alarm_queue = await event_bus.subscribe("latched-interlock-start")
    experiment = SimpleNamespace(active_experiment_id="thermal-run")
    alarm_dispatch_tasks: set[asyncio.Task[object]] = set()
    fault_context = _SafetyFaultLogContext(
        writer=operator_log,
        broker=DataBroker(),
        alarm_dispatch_tasks=alarm_dispatch_tasks,
        event_bus=event_bus,
        experiment_manager=experiment,
    )

    source = MagicMock()
    source.mock = True
    source.connected = True
    source.output_state_unverified = False
    source.emergency_off = AsyncMock(return_value=SourceOffResult.DEVICE_REPORTED_OFF)
    source.start_source = AsyncMock()
    source.stop_source = AsyncMock()
    runtime_binding = _issue_registry_runtime_binding(
        driver=source,
        timing=AcquisitionTiming(1.0, 1.0, 1.0),
        registry_provenance="test:latched-interlock-start",
        trust_class=DriverTrustClass.REVIEWED_SOURCE,
        simulation=True,
    )
    manager = SafetyManager(
        SafetyBroker(),
        keithley_driver=source,
        reviewed_source_runtime_binding=runtime_binding,
        mock=True,
        fault_log_callback=functools.partial(
            _safety_fault_log_callback,
            context=fault_context,
        ),
    )
    manager._config.critical_channels = []
    manager._config.require_reason = False
    await manager.start()
    manager._state = SafetyState.RUNNING
    manager._active_sources.add("smua")

    broker = DataBroker()

    async def noop() -> None:
        return None

    interlock_context = _InterlockHandlerContext(
        safety_manager=manager,
        alarm_dispatch_tasks=alarm_dispatch_tasks,
        dead_channel_alarm_sent=set(),
    )
    interlocks = InterlockEngine(
        broker,
        actions={"emergency_off": noop, "stop_source": noop},
        trip_handler=functools.partial(
            _interlock_trip_handler,
            context=interlock_context,
        ),
    )
    interlocks.load_config(
        INTERLOCKS_PATH,
        descriptor_catalog=load_live_channel_descriptor_catalog(DESCRIPTORS_PATH),
        poll_intervals_s_by_instrument=POLL_INTERVALS,
    )
    await interlocks.start()
    offered_warnings: list[dict[str, str]] = []
    try:
        await _publish_bound_interlock_reading(broker, 350.1)
        alarm = await asyncio.wait_for(alarm_queue.get(), timeout=1.0)
        for _ in range(100):
            if source.emergency_off.await_count >= 2:
                break
            await asyncio.sleep(0)
        else:
            pytest.fail("the shipped source_overtemp soft cut did not settle after the hard interlock")
        await asyncio.sleep(0)

        assert manager.state is SafetyState.FAULT_LATCHED
        assert manager._active_sources == set()
        source.emergency_off.assert_awaited()
        assert alarm.event_type == "alarm_fired"
        assert alarm.payload["alarm_id"].startswith("safety_fault_")
        assert alarm.payload["level"] == "CRITICAL"
        assert any(
            event.interlock_name == "overheat_cryostat"
            and event.action_taken == "emergency_off"
            and event.value == pytest.approx(350.1)
            for event in interlocks.get_events()
        )
        assert operator_log.entries[0].source == "machine"
        assert operator_log.entries[0].tags == ("safety_fault", "Т11")

        async def persist_start_offer(warnings: list[dict[str, str]]) -> dict[str, object]:
            offered_warnings.extend(dict(warning) for warning in warnings)
            return await _persist_keithley_warning_choice_intent(
                warnings,
                cmd={"channel": "smua"},
                writer=operator_log,
                experiment_manager=experiment,
            )

        result = await manager.request_run(
            0.1,
            1.0,
            0.1,
            channel="smua",
            warning_choice_committer=persist_start_offer,
        )

        assert offered_warnings, result
        assert offered_warnings[0]["code"] == "latched_interlock_start"
        assert "overheat_cryostat" in offered_warnings[0]["operator_text"]
        assert result["ok"] is True
        assert result["state"] == "running"
        assert manager.state is SafetyState.RUNNING
        assert manager._active_sources == {"smua"}
        assert manager._latched_fault_abort_generation is None
        source.start_source.assert_awaited_once_with("smua", 0.1, 1.0, 0.1)
        start_record = operator_log.entries[-1]
        assert "latched_interlock_start" in start_record.tags
        assert "overheat_cryostat" in start_record.message
        assert result["operator_warning_receipt"]["committed"] is True
        assert result["operator_warning_receipt"]["operator_log_id"] == start_record.id
    finally:
        await interlocks.stop()
        await manager.stop()


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
async def test_shipped_source_overtemp_soft_stop_stays_safe_off_without_latch(mgr):
    await mgr.on_interlock_trip(
        interlock_name="source_overtemp",
        channel="Т11",
        value=320.1,
        action="stop_source",
    )

    assert mgr.state is SafetyState.SAFE_OFF
    assert mgr._latched_fault_abort_generation is None
    assert mgr._active_sources == set()
    mgr._keithley.emergency_off.assert_awaited()


@pytest.mark.asyncio
async def test_persistence_latch_still_refuses_deliberate_start(mgr):
    persistence_clear = MagicMock()
    mgr.set_persistence_failure_clear(persistence_clear)
    mgr._keithley.start_source.reset_mock()

    await mgr.on_persistence_failure("disk full")
    result = await mgr.request_run(
        p_target=0.1,
        v_comp=1.0,
        i_comp=0.1,
        channel="smua",
    )

    assert mgr.state is SafetyState.FAULT_LATCHED
    assert result["ok"] is False
    assert result["error"].startswith("FAULT: Persistence failure:")
    mgr._keithley.start_source.assert_not_awaited()
    persistence_clear.assert_not_called()


@pytest.mark.asyncio
async def test_latch_origins_record_interlock_and_joined_persistence_cause(mgr):
    await mgr.on_interlock_trip(
        interlock_name="overheat_cryostat",
        channel="Т11",
        value=350.1,
        action="emergency_off",
    )
    assert mgr._fault_sources == {"interlock"}

    await mgr.on_persistence_failure("disk full after interlock")

    assert mgr._fault_sources == {"interlock", "persistence"}
    result = await mgr.request_run(0.1, 1.0, 0.1, channel="smua")
    assert result["ok"] is False
    assert mgr.state is SafetyState.FAULT_LATCHED


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
        channel_ids=frozenset({"lakeshore/Т12"}),
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
async def test_tripped_control_interlock_is_rearmed_and_fires_again() -> None:
    """A control interlock that fired once must not go blind for the rest of the run.

    ``_process_reading`` evaluates ARMED records only, and the sole
    operator-reachable path back to ARMED (``interlock_acknowledge``) has no
    control in the GUI.  Before this guard, ``source_overtemp`` and
    ``overheat_cryostat`` each protected exactly one event per application
    lifetime.  That was survivable only while a latched fault also blocked the
    next Start; once the owner's ruling made the Start possible again, it became
    a source running with no thermal protection.
    """

    broker = DataBroker()
    actions_seen: list[str] = []

    async def _emergency_off() -> None:
        actions_seen.append("emergency_off")

    async def _stop_source() -> None:
        actions_seen.append("stop_source")

    engine = InterlockEngine(
        broker,
        actions={"emergency_off": _emergency_off, "stop_source": _stop_source},
    )
    engine.load_config(
        INTERLOCKS_PATH,
        descriptor_catalog=load_live_channel_descriptor_catalog(DESCRIPTORS_PATH),
        poll_intervals_s_by_instrument=POLL_INTERVALS,
    )
    await engine.start()
    try:
        # 1. It fires, and it cuts.
        await _publish_bound_interlock_reading(broker, 350.1)
        await asyncio.sleep(0.05)
        assert engine.get_state()["overheat_cryostat"] is InterlockState.TRIPPED
        assert engine.get_state()["source_overtemp"] is InterlockState.TRIPPED
        first_round = list(actions_seen)
        assert first_round, "the shipped ladder did not act on its first trip"

        # 2. Still hot, but every control row is latched: nothing more happens.
        actions_seen.clear()
        await _publish_bound_interlock_reading(broker, 350.1)
        await asyncio.sleep(0.05)
        assert actions_seen == [], "a latched control interlock must not act again until it is re-armed"

        # 3. The operator deliberately starts again; the guards come back.
        rearmed = engine.rearm_tripped_control_interlocks()
        assert sorted(rearmed) == ["overheat_cryostat", "source_overtemp"]
        assert engine.get_state()["overheat_cryostat"] is InterlockState.ARMED
        assert engine.get_state()["source_overtemp"] is InterlockState.ARMED

        # 4. THE POINT: the cryostat is still hot, so they fire AGAIN and cut AGAIN.
        await _publish_bound_interlock_reading(broker, 350.1)
        await asyncio.sleep(0.05)
        assert engine.get_state()["overheat_cryostat"] is InterlockState.TRIPPED
        assert actions_seen, "a re-armed interlock did not protect the new run while the violation was still present"
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_rearm_leaves_observational_warning_rows_alone() -> None:
    """Warning rows own their own recovery; the control re-arm must not touch them."""

    from cryodaq.core.interlock import InterlockCondition

    broker = DataBroker()
    engine = InterlockEngine(broker, actions={"emergency_off": None, "stop_source": None})
    engine.add_condition(
        InterlockCondition(
            name="synthetic_observational",
            description="operator warning only",
            channel_ids=frozenset({"Т11"}),
            threshold=10.0,
            comparison=">",
            action="warning",
        )
    )
    engine._interlocks["synthetic_observational"].state = InterlockState.TRIPPED

    rearmed = engine.rearm_tripped_control_interlocks()

    assert rearmed == []
    assert engine.get_state()["synthetic_observational"] is InterlockState.TRIPPED


def _qualified_manager() -> SafetyManager:
    """A SafetyManager that can actually start, built like the shipped E2E guard.

    The plain `mgr` fixture is refused by request_run at the laboratory
    qualification gate long before the re-arm hook is reached. That refusal is
    correct and is not weakened here; the guard simply supplies the reviewed
    source binding it asks for.
    """
    source = MagicMock()
    source.mock = True
    source.connected = True
    source.output_state_unverified = False
    source.emergency_off = AsyncMock(return_value=SourceOffResult.DEVICE_REPORTED_OFF)
    source.start_source = AsyncMock()
    source.stop_source = AsyncMock()
    runtime_binding = _issue_registry_runtime_binding(
        driver=source,
        timing=AcquisitionTiming(1.0, 1.0, 1.0),
        registry_provenance="test:interlock-rearm",
        trust_class=DriverTrustClass.REVIEWED_SOURCE,
        simulation=True,
    )
    manager = SafetyManager(
        SafetyBroker(),
        keithley_driver=source,
        reviewed_source_runtime_binding=runtime_binding,
        mock=True,
    )
    manager._config.critical_channels = []
    manager._config.require_reason = False
    return manager


@pytest.mark.asyncio
async def test_deliberate_start_rearms_control_interlocks() -> None:
    """The Start that follows a trip must also put the guards back."""

    calls: list[str] = []

    def _probe() -> list[str]:
        calls.append("rearm")
        return ["overheat_cryostat"]

    manager = _qualified_manager()
    manager.set_interlock_rearm(_probe)
    await manager.start()
    try:
        manager._state = SafetyState.SAFE_OFF
        result = await manager.request_run(0.1, 1.0, 0.1, channel="smua")
        assert result["ok"] is True, result
        assert calls == ["rearm"], "a deliberate start did not re-arm the control interlocks"
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_rearm_hook_failure_does_not_block_the_operator() -> None:
    """If the re-arm hook raises, he still starts.

    The owner's rule is that the software does not refuse him. A broken hook is
    our defect, not his, and must never become a lockout.
    """

    def _boom() -> list[str]:
        raise RuntimeError("hook is broken")

    manager = _qualified_manager()
    manager.set_interlock_rearm(_boom)
    await manager.start()
    try:
        manager._state = SafetyState.SAFE_OFF
        result = await manager.request_run(0.1, 1.0, 0.1, channel="smua")
        assert result["ok"] is True, result
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_recovered_persistence_latch_lets_the_operator_start_again() -> None:
    """The disk filled, he freed space, and he can resume without restarting.

    The documented recovery for a persistence fault is acknowledge_fault, exposed
    as the safety_acknowledge command.  Measured 2026-08-29: it has ZERO call sites
    in src/cryodaq/gui/.  So before this, a disk that filled during a week-long run
    ended it until the application was restarted - the data-continuity event the
    whole campaign exists to prevent, reached through the guard meant to protect
    data.

    The latch is consumable ONLY once persistence reports it can write again, so
    the data-loss protection is kept rather than traded away.
    """

    cleared: list[str] = []
    manager = _qualified_manager()
    manager.set_persistence_failure_clear(lambda: cleared.append("cleared"))
    manager.set_persistence_recovered(lambda: True)
    await manager.start()
    try:
        await manager.on_persistence_failure("disk full")
        assert manager.state is SafetyState.FAULT_LATCHED

        result = await manager.request_run(0.1, 1.0, 0.1, channel="smua")

        assert result["ok"] is True, result
        assert cleared == ["cleared"], "the writer's disk-full flag was not cleared on the way through"
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_persistence_latch_still_refuses_while_the_disk_is_still_full() -> None:
    """Recovery is the gate, not the operator's impatience.

    This is the half that must never be traded away: starting a run that cannot be
    recorded would satisfy the owner's ruling by destroying what the ruling
    protects.  While persistence reports it still cannot write, the refusal stands.
    """

    manager = _qualified_manager()
    manager.set_persistence_failure_clear(lambda: None)
    manager.set_persistence_recovered(lambda: False)
    await manager.start()
    try:
        await manager.on_persistence_failure("disk still full")
        result = await manager.request_run(0.1, 1.0, 0.1, channel="smua")
        assert result["ok"] is False, result
        assert manager.state is SafetyState.FAULT_LATCHED
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_a_failing_recovery_query_keeps_the_latch() -> None:
    """An exception in our own hook must fail CLOSED, not open.

    This is the one place in the campaign where failing closed is right: the
    question is whether data can be recorded, and an unanswerable question is not
    a yes.
    """

    def _boom() -> bool:
        raise RuntimeError("writer is unreachable")

    manager = _qualified_manager()
    manager.set_persistence_failure_clear(lambda: None)
    manager.set_persistence_recovered(_boom)
    await manager.start()
    try:
        await manager.on_persistence_failure("disk full")
        result = await manager.request_run(0.1, 1.0, 0.1, channel="smua")
        assert result["ok"] is False, result
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_expired_off_proof_is_revoked_and_current_proof_is_not() -> None:
    """Proof that a device was OFF long ago must not stay positive evidence.

    Codex P1 at c9d1326ea: when verified-OFF evidence aged past `stale_timeout_s`,
    the publish path substituted UNKNOWN only in the PUBLISHED READING, while
    `_reviewed_source_off_evidence.verified_off` stayed true - so the snapshot and
    the command boundary went on authorising.  The GUI hid Start after seeing
    UNKNOWN, which made the interface the only thing between an expired proof and
    an energised source.

    Both directions are pinned here: a guard that revoked unconditionally would
    satisfy the first assertion while refusing every legitimate Start.
    """

    manager = _qualified_manager()
    await manager.start()
    try:
        manager.record_reviewed_source_connected(verified_off=True)
        assert manager._reviewed_source_off_evidence.verified_off is True

        # Still current: nothing is revoked.
        assert manager._expire_stale_off_evidence() is False
        assert manager._reviewed_source_off_evidence.verified_off is True

        # Aged past the bound, with every other precondition unchanged - exactly
        # the situation the finding describes.
        manager._reviewed_source_off_evidence_observed_monotonic_s -= manager._config.stale_timeout_s + 5.0
        assert manager._expire_stale_off_evidence() is True
        assert manager._reviewed_source_off_evidence.verified_off is False, (
            "expired OFF proof was left as positive evidence"
        )
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_the_command_boundary_expires_off_proof_itself() -> None:
    """`request_run` must run the expiry itself, not inherit it from elsewhere.

    A REQ client can issue `keithley_start` without ever reading the operator
    snapshot, and `request_run` contains NO snapshot refresh - measured, lines
    1142-1450 - so the boundary call is the only expiry on that path.

    THE FIRST VERSION OF THIS GUARD WAS VACUOUS. It monkeypatched the expiry and
    asserted it had been called, which stayed true with the boundary call removed
    because `manager.start()` runs a background monitor that refreshes the
    snapshot on its own schedule. It observed the process, not the path.

    This is deterministic instead: the state makes `request_run` refuse at a check
    that sits AFTER the expiry, so the only thing that can have revoked the proof
    by then is the boundary call.
    """

    manager = _qualified_manager()
    await manager.start()
    try:
        manager.record_reviewed_source_connected(verified_off=True)
        manager._reviewed_source_off_evidence_observed_monotonic_s -= manager._config.stale_timeout_s + 5.0
        assert manager._reviewed_source_off_evidence.verified_off is True

        # MANUAL_RECOVERY is not a state a Start may proceed from, and that check
        # is downstream of the expiry.
        manager._state = SafetyState.MANUAL_RECOVERY
        result = await manager.request_run(0.1, 1.0, 0.1, channel="smua")
        assert result["ok"] is False

        assert manager._reviewed_source_off_evidence.verified_off is False, (
            "request_run refused for another reason without expiring the stale "
            "OFF proof, so a client reaching a permitted state would still "
            "energise from it"
        )
    finally:
        await manager.stop()


class _WarningLogProbe:
    """Capture exactly what would be written to the operator log."""

    def __init__(self) -> None:
        self.entries: list[OperatorLogEntry] = []

    async def append_operator_log(
        self, *, message: str, author: str, source: str, experiment_id: object, tags: tuple[str, ...]
    ) -> OperatorLogEntry:
        entry = OperatorLogEntry(
            id=len(self.entries) + 1,
            timestamp=datetime.now(UTC),
            message=message,
            author=author,
            source=source,
            experiment_id=experiment_id,
            tags=tags,
        )
        self.entries.append(entry)
        return entry


_VALID_CHOICE = {
    "schema": "cryodaq.keithley_warning_choice.v1",
    "request_id": "a" * 32,
    "warning": "predictor unavailable",
    "choice": "start",
}

_A_WARNING = [
    {"code": "predictor_unavailable", "operator_text": "Предиктор недоступен", "consequence": "оценка отключена"}
]


@pytest.mark.asyncio
async def test_a_start_without_a_choice_is_not_recorded_as_confirmed() -> None:
    """The operator log must not say he confirmed something he never saw.

    Codex P1 at c9d1326ea: the GUI attaches `operator_warning_choice` ONLY when the
    safety gate is not ready, so every Start taken while Safety is READY carried no
    choice - and the log recorded «намерение запуска подтверждено», a decision the
    operator never made.  That is data misrepresented, in the record a week-long
    run is judged from.

    Start stays permissive.  Only what is WRITTEN changes.
    """

    writer = _WarningLogProbe()
    receipt = await _persist_keithley_warning_choice_intent(
        _A_WARNING,
        cmd={"channel": "smua"},  # no operator_warning_choice at all
        writer=writer,
        experiment_manager=SimpleNamespace(active_experiment_id="thermal-run"),
    )

    assert receipt["committed"] is True, "the record must still be written"
    entry = writer.entries[0]
    assert "БЕЗ подтверждения оператора" in entry.message, entry.message
    assert "подтверждено при предупреждении" not in entry.message
    assert "operator_warning_unconfirmed" in entry.tags
    assert "operator_warning_choice" not in entry.tags


@pytest.mark.asyncio
async def test_a_start_with_a_valid_choice_is_recorded_as_confirmed() -> None:
    """The other direction: a real confirmation must still read as one."""

    writer = _WarningLogProbe()
    receipt = await _persist_keithley_warning_choice_intent(
        _A_WARNING,
        cmd={"channel": "smua", "operator_warning_choice": dict(_VALID_CHOICE)},
        writer=writer,
        experiment_manager=SimpleNamespace(active_experiment_id="thermal-run"),
    )

    entry = writer.entries[0]
    assert "намерение запуска подтверждено при предупреждении" in entry.message
    assert "operator_warning_choice" in entry.tags
    assert receipt["request_id"] == "a" * 32, "a real choice lends its correlation ID"


@pytest.mark.asyncio
async def test_an_invalid_choice_does_not_lend_its_correlation_id() -> None:
    """A syntactically valid ID inside an invalid payload is a WRONG id, not an unknown one.

    `_warning_choice_request_id` used to inspect only the ID's lexical form, so a
    receipt could carry the GUI's correlation identifier for a choice the GUI never
    made - and a consumer reconciling by that ID would tie the two together.
    """

    writer = _WarningLogProbe()
    broken = dict(_VALID_CHOICE)
    broken["schema"] = "cryodaq.keithley_warning_choice.v0"  # wrong schema, valid id
    receipt = await _persist_keithley_warning_choice_intent(
        _A_WARNING,
        cmd={"channel": "smua", "operator_warning_choice": broken},
        writer=writer,
        experiment_manager=SimpleNamespace(active_experiment_id="thermal-run"),
    )

    assert receipt["request_id"] != "a" * 32, "an invalid choice lent its correlation ID to the receipt"
    assert "operator_warning_unconfirmed" in writer.entries[0].tags


def test_persistence_recovery_is_probed_not_read_off_the_latch(tmp_path, monkeypatch):
    """Codex P1 at 8314e9273: the latch gated its own clearing.

    `_disk_full` is cleared only by `clear_disk_full()`, whose sole production caller is
    the SafetyManager hook this predicate gates. Reading `is_disk_full` here therefore
    refused the operator forever after a real disk-full event, however much space was
    freed - a refusal, on the criterion the owner cares most about.

    This drives the PRODUCTION predicate. The previous regression replaced it with
    `set_persistence_recovered(lambda: True)`, and a test that substitutes the unit
    under test cannot fail when that unit is wrong.
    """

    import shutil as _shutil

    from cryodaq.engine import _persistence_can_write

    class _Writer:
        def __init__(self, latched: bool) -> None:
            self.db_path = tmp_path / "data" / "cryodaq.db"
            self._latched = latched

        @property
        def is_disk_full(self) -> bool:
            return self._latched

    Usage = namedtuple("Usage", "total used free")

    def _free(gb: float):
        def _usage(_path):
            return Usage(total=0, used=0, free=int(gb * (1024**3)))

        return _usage

    # THE DEFECT: latched, but the disk has plenty of room. Must be True - otherwise the
    # operator can never recover without restarting the program.
    monkeypatch.setattr(_shutil, "disk_usage", _free(500.0))
    assert _persistence_can_write(_Writer(latched=True)) is True, (
        "a freed disk still refused recovery because the latch was read instead of probed"
    )

    # Still genuinely full: recovery is not asserted.
    monkeypatch.setattr(_shutil, "disk_usage", _free(0.05))
    assert _persistence_can_write(_Writer(latched=True)) is False
    assert _persistence_can_write(_Writer(latched=False)) is False, (
        "an unlatched writer on a full disk must not be reported as able to write"
    )


def test_persistence_recovery_uses_the_disk_monitors_own_threshold():
    """The recovery definition is borrowed, so the two cannot drift apart.

    If someone retunes the monitor's warning threshold and this predicate keeps an
    independent copy, the operator's recovery point silently stops matching the
    condition the operator was warned about.
    """

    from cryodaq.core.disk_monitor import _WARNING_THRESHOLD_GB
    from cryodaq.engine import _DISK_RECOVERY_THRESHOLD_GB

    assert _DISK_RECOVERY_THRESHOLD_GB == _WARNING_THRESHOLD_GB


def test_unreadable_disk_evidence_is_not_recovery(tmp_path, monkeypatch):
    """ "Cannot tell" is not "recovered" - fail closed on unreadable evidence."""

    import shutil as _shutil

    from cryodaq.engine import _persistence_can_write

    class _Writer:
        db_path = tmp_path / "data" / "cryodaq.db"
        is_disk_full = True

    def _boom(_path):
        raise OSError("stat failed")

    monkeypatch.setattr(_shutil, "disk_usage", _boom)
    assert _persistence_can_write(_Writer()) is False

    class _NoPath:
        is_disk_full = True

    assert _persistence_can_write(_NoPath()) is False
