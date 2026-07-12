from __future__ import annotations

import asyncio
import re
import time
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager, SafetyState
from cryodaq.engine_wiring.operator_safety_snapshot import (
    OperatorSafetySnapshot,
    SafetyLifecycle,
)
from cryodaq.engine_wiring.operator_snapshot_authorities import (
    AuthorityAvailability,
    CommonCut,
)
from cryodaq.engine_wiring.operator_snapshot_live_authorities import (
    LiveSafetyReadinessAuthority,
)
from cryodaq.operator_snapshot import OperatorPresentationState, ReadinessTruth


def _manager(*, mock: bool = False, driver: object | None = None) -> SafetyManager:
    return SafetyManager(SafetyBroker(), keithley_driver=driver, mock=mock)


def _codes(snapshot: OperatorSafetySnapshot) -> set[str]:
    return {item.code for item in snapshot.blockers}


_CUT = CommonCut(
    generation=1,
    token="cut-v1:1:" + "1" * 64,
    observed_at=datetime(2026, 7, 12, tzinfo=UTC),
)


def test_initial_cut_is_exact_unknown_false_and_disconnected() -> None:
    manager = _manager()
    snapshot = manager.snapshot_operator_safety()
    assert type(snapshot) is OperatorSafetySnapshot
    assert snapshot.revision == 1
    assert snapshot.lifecycle is SafetyLifecycle.UNKNOWN
    assert snapshot.readiness is ReadinessTruth.UNKNOWN
    assert snapshot.verified_off is False
    assert _codes(snapshot) == {"safety_authority_unavailable"}
    assert snapshot.plant_health[0].state is OperatorPresentationState.DISCONNECTED


def test_getter_is_identity_stable_and_performs_no_sampling_or_driver_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = MagicMock()
    driver.emergency_off = AsyncMock(side_effect=AssertionError("driver I/O"))
    manager = _manager(driver=driver)
    cached = manager.snapshot_operator_safety()
    monkeypatch.setattr(
        time,
        "monotonic",
        lambda: (_ for _ in ()).throw(AssertionError("time sampled")),
    )
    assert manager.snapshot_operator_safety() is cached
    driver.emergency_off.assert_not_awaited()


def test_explicit_connection_evidence_advances_exactly_one_revision_and_never_regresses_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager()
    first = manager.snapshot_operator_safety()
    monkeypatch.setattr(time, "monotonic", lambda: first.observed_monotonic_s - 100.0)
    manager.record_reviewed_source_connected(verified_off=False)
    connected = manager.snapshot_operator_safety()
    assert connected.revision == first.revision + 1
    assert connected.observed_monotonic_s == first.observed_monotonic_s
    assert connected.verified_off is False
    assert "reviewed_source_off_unverified" in _codes(connected)

    manager.record_reviewed_source_connected(verified_off=True)
    proved = manager.snapshot_operator_safety()
    assert proved.revision == connected.revision + 1
    assert proved.observed_monotonic_s == connected.observed_monotonic_s
    with pytest.raises(TypeError, match="exact bool"):
        manager.record_reviewed_source_connected(verified_off=1)  # type: ignore[arg-type]

    manager._active_sources.add("smua")
    with pytest.raises(ValueError, match="source lifecycle is active"):
        manager.record_reviewed_source_connected(verified_off=True)


def test_safe_off_name_and_empty_active_set_do_not_imply_ready() -> None:
    manager = _manager()
    manager._safety_monitor_active = True
    manager.record_reviewed_source_connected(verified_off=True)
    snapshot = manager.snapshot_operator_safety()
    assert snapshot.lifecycle is SafetyLifecycle.SAFE_OFF
    assert snapshot.readiness is ReadinessTruth.BLOCKED
    assert snapshot.verified_off is True
    assert "safety_state_safe_off" in _codes(snapshot)


def test_state_change_observer_sees_the_matching_new_owner_cut() -> None:
    manager = _manager()
    manager._safety_monitor_active = True
    manager.record_reviewed_source_connected(verified_off=True)
    observed: list[SafetyLifecycle] = []
    manager.on_state_change(lambda _old, _new, _reason: observed.append(manager.snapshot_operator_safety().lifecycle))
    manager._transition(SafetyState.READY, "qualified")
    assert observed == [SafetyLifecycle.READY]


def test_ready_requires_monitor_current_inputs_connection_and_exact_off_proof() -> None:
    manager = _manager()
    manager._safety_monitor_active = True
    manager._config.critical_channels = [re.compile("critical/temperature")]
    manager._latest["critical/temperature"] = (time.monotonic(), 4.2, "ok")
    manager.record_reviewed_source_connected(verified_off=True)
    manager._transition(SafetyState.READY, "qualified")
    ready = manager.snapshot_operator_safety()
    assert ready.lifecycle is SafetyLifecycle.READY
    assert ready.readiness is ReadinessTruth.READY
    assert ready.verified_off is True
    assert ready.blockers == ()

    manager.record_reviewed_source_connected(verified_off=False)
    unproved = manager.snapshot_operator_safety()
    assert unproved.lifecycle is SafetyLifecycle.UNKNOWN
    assert unproved.readiness is ReadinessTruth.UNKNOWN
    assert unproved.verified_off is False
    assert "reviewed_source_off_unverified" in _codes(unproved)


@pytest.mark.parametrize(
    "state",
    (
        SafetyState.RUN_PERMITTED,
        SafetyState.RUNNING,
        SafetyState.FAULT_LATCHED,
        SafetyState.MANUAL_RECOVERY,
    ),
)
def test_active_fault_and_recovery_matrix_is_blocked(state: SafetyState) -> None:
    manager = _manager()
    manager._safety_monitor_active = True
    manager.record_reviewed_source_connected(verified_off=True)
    if state in {SafetyState.RUN_PERMITTED, SafetyState.RUNNING}:
        manager._reviewed_source_verified_off = False
        manager._active_sources.add("smua")
    manager._transition(state, "matrix")
    snapshot = manager.snapshot_operator_safety()
    assert snapshot.lifecycle is SafetyLifecycle(state.value)
    assert snapshot.readiness is ReadinessTruth.BLOCKED
    assert snapshot.blockers
    if state in {SafetyState.RUN_PERMITTED, SafetyState.RUNNING}:
        assert snapshot.verified_off is False
        assert "source_operation_active" in _codes(snapshot)


def test_stale_invalid_and_missing_critical_inputs_are_explicit_blockers() -> None:
    manager = _manager()
    manager._safety_monitor_active = True
    manager.record_reviewed_source_connected(verified_off=True)
    manager._config.critical_channels = [re.compile("critical/temperature")]

    manager._refresh_operator_safety_snapshot()
    assert "critical_input_missing" in _codes(manager.snapshot_operator_safety())

    manager._latest["critical/temperature"] = (
        time.monotonic() - manager._config.stale_timeout_s - 1.0,
        4.2,
        "ok",
    )
    manager._refresh_operator_safety_snapshot()
    assert "critical_input_stale" in _codes(manager.snapshot_operator_safety())

    manager._latest["critical/temperature"] = (time.monotonic(), float("nan"), "ok")
    manager._refresh_operator_safety_snapshot()
    assert "critical_input_invalid" in _codes(manager.snapshot_operator_safety())


async def test_persistence_fault_recovery_and_source_start_stop_each_refresh_owner_cut() -> None:
    driver = MagicMock()
    driver.start_source = AsyncMock()
    driver.stop_source = AsyncMock()
    driver.emergency_off = AsyncMock(return_value=True)
    driver.watchdog_trip_pending = False
    driver.output_state_unverified = False
    driver.connected = True
    manager = _manager(mock=True, driver=driver)
    await manager.start()
    try:
        before_run = manager.snapshot_operator_safety()
        result = await manager.request_run(0.1, 1.0, 0.1)
        running = manager.snapshot_operator_safety()
        assert result["ok"] is True
        assert running.revision > before_run.revision
        assert running.lifecycle is SafetyLifecycle.RUNNING
        assert running.verified_off is False

        result = await manager.request_stop()
        stopped = manager.snapshot_operator_safety()
        assert result["ok"] is True
        assert stopped.revision > running.revision
        assert stopped.verified_off is True

        await manager.on_persistence_failure("disk unavailable")
        faulted = manager.snapshot_operator_safety()
        assert faulted.revision > stopped.revision
        assert "persistence_fault_active" in _codes(faulted)

        manager._config.cooldown_before_rearm_s = 0.0
        recovered = await manager.acknowledge_fault("storage restored")
        recovery_cut = manager.snapshot_operator_safety()
        assert recovered["ok"] is True
        assert recovery_cut.revision > faulted.revision
        assert "persistence_fault_active" not in _codes(recovery_cut)
        assert recovery_cut.lifecycle is SafetyLifecycle.MANUAL_RECOVERY
    finally:
        before_stop = manager.snapshot_operator_safety().revision
        await manager.stop()
        assert manager.snapshot_operator_safety().revision > before_stop


async def test_confirmed_off_and_disconnect_are_separate_explicit_mutations() -> None:
    driver = MagicMock()
    driver.emergency_off = AsyncMock(return_value=True)
    driver.disconnect = AsyncMock()
    manager = _manager(driver=driver)
    manager._safety_monitor_active = True
    before = manager.snapshot_operator_safety()
    assert await manager.disconnect_reviewed_source(driver, "test") is True
    disconnected = manager.snapshot_operator_safety()
    assert disconnected.revision >= before.revision + 3
    assert disconnected.verified_off is True
    assert "reviewed_source_disconnected" in _codes(disconnected)
    driver.emergency_off.assert_awaited_once()
    driver.disconnect.assert_awaited_once()


async def test_disconnect_cancellation_settles_proof_and_lifecycle_revisions() -> None:
    off_started = asyncio.Event()
    off_release = asyncio.Event()
    disconnect_started = asyncio.Event()
    disconnect_release = asyncio.Event()

    class Driver:
        async def emergency_off(self) -> bool:
            off_started.set()
            await off_release.wait()
            return True

        async def disconnect(self) -> None:
            disconnect_started.set()
            await disconnect_release.wait()

    driver = Driver()
    manager = _manager(driver=driver)
    manager._safety_monitor_active = True
    before = manager.snapshot_operator_safety()
    task = asyncio.create_task(manager.disconnect_reviewed_source(driver, "cancelled"))
    await off_started.wait()
    task.cancel()
    off_release.set()
    await disconnect_started.wait()
    disconnect_release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    settled = manager.snapshot_operator_safety()
    assert settled.revision >= before.revision + 3
    assert settled.lifecycle is SafetyLifecycle.SAFE_OFF
    assert settled.verified_off is True
    assert "reviewed_source_disconnected" in _codes(settled)


def test_non_ok_plant_fact_is_not_implicitly_a_readiness_blocker() -> None:
    manager = _manager()
    manager._safety_monitor_active = True
    manager.record_reviewed_source_connected(verified_off=True)
    manager._transition(SafetyState.READY, "qualified")
    snapshot = manager.snapshot_operator_safety()
    assert snapshot.blockers == ()
    # Plant health remains an independent typed collection; only explicit
    # SafetyBlocker values participate in readiness.
    assert all(fact.subsystem_id for fact in snapshot.plant_health)


@pytest.mark.parametrize("role", ("collect", "monitor"))
@pytest.mark.parametrize("outcome", ("completed", "failed", "cancelled"))
async def test_exact_child_death_invalidates_ready_off_and_available_ready_receipt(
    monkeypatch: pytest.MonkeyPatch,
    role: str,
    outcome: str,
) -> None:
    release = asyncio.Event()
    keep_alive = asyncio.Event()

    async def terminal_child() -> None:
        await release.wait()
        if outcome == "failed":
            raise RuntimeError("deterministic child failure")

    async def live_child() -> None:
        await keep_alive.wait()

    manager = _manager(mock=True)
    monkeypatch.setattr(
        manager,
        "_collect_loop",
        terminal_child if role == "collect" else live_child,
    )
    monkeypatch.setattr(
        manager,
        "_monitor_loop",
        terminal_child if role == "monitor" else live_child,
    )
    await manager.start()
    try:
        manager._transition(SafetyState.READY, "qualified child-liveness test")
        ready = manager.snapshot_operator_safety()
        assert ready.readiness is ReadinessTruth.READY
        assert ready.verified_off is True

        task = manager._collect_task if role == "collect" else manager._monitor_task
        assert task is not None
        if outcome == "cancelled":
            task.cancel()
        else:
            release.set()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)

        failed = manager.snapshot_operator_safety()
        assert failed.revision > ready.revision
        assert failed.lifecycle is SafetyLifecycle.UNKNOWN
        assert failed.readiness is ReadinessTruth.UNKNOWN
        assert failed.verified_off is False
        assert f"safety_{role}_{outcome}" in _codes(failed)
        failed_fact = next(fact for fact in failed.plant_health if fact.subsystem_id == f"safety_{role}")
        assert failed_fact.state is OperatorPresentationState.DISCONNECTED
        receipt = LiveSafetyReadinessAuthority(manager).snapshot_for_cut(_CUT)
        assert not (
            receipt.availability is AuthorityAvailability.AVAILABLE and receipt.readiness is ReadinessTruth.READY
        )
        assert receipt.verified_off is False
    finally:
        await manager.stop()


async def test_expected_stop_settles_children_and_invalidates_ready_without_failure() -> None:
    manager = _manager(mock=True)
    await manager.start()
    manager._transition(SafetyState.READY, "qualified expected-stop test")
    before = manager.snapshot_operator_safety()

    await manager.stop()

    stopped = manager.snapshot_operator_safety()
    assert stopped.revision == before.revision + 1
    assert stopped.lifecycle is SafetyLifecycle.UNKNOWN
    assert stopped.readiness is ReadinessTruth.UNKNOWN
    assert stopped.verified_off is False
    assert "safety_manager_stopping" in _codes(stopped)
    assert manager._collect_task is None
    assert manager._monitor_task is None


async def test_cancelled_stop_still_settles_both_exact_children_before_propagating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    never = asyncio.Event()
    cancellation_seen = asyncio.Event()
    release_settlement = asyncio.Event()
    cancellations = 0

    async def cancellation_delayed_child() -> None:
        nonlocal cancellations
        try:
            await never.wait()
        except asyncio.CancelledError:
            cancellations += 1
            if cancellations == 2:
                cancellation_seen.set()
            await release_settlement.wait()
            raise

    manager = _manager(mock=True)
    monkeypatch.setattr(manager, "_collect_loop", cancellation_delayed_child)
    monkeypatch.setattr(manager, "_monitor_loop", cancellation_delayed_child)
    await manager.start()
    manager._transition(SafetyState.READY, "qualified cancelled-stop test")

    stopping = asyncio.create_task(manager.stop())
    await cancellation_seen.wait()
    stopping.cancel()
    release_settlement.set()
    with pytest.raises(asyncio.CancelledError):
        await stopping

    stopped = manager.snapshot_operator_safety()
    assert stopped.lifecycle is SafetyLifecycle.UNKNOWN
    assert stopped.readiness is ReadinessTruth.UNKNOWN
    assert stopped.verified_off is False
    assert manager._collect_task is None
    assert manager._monitor_task is None
    assert manager._stopping_child_generation is None


async def test_prior_generation_done_callback_cannot_invalidate_restarted_children(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    never = asyncio.Event()

    async def live_child() -> None:
        await never.wait()

    manager = _manager(mock=True)
    monkeypatch.setattr(manager, "_collect_loop", live_child)
    monkeypatch.setattr(manager, "_monitor_loop", live_child)
    await manager.start()
    old_collect = manager._collect_task
    old_generation = manager._child_generation
    assert old_collect is not None
    await manager.stop()

    await manager.start()
    try:
        manager._transition(SafetyState.READY, "qualified restarted generation")
        restarted = manager.snapshot_operator_safety()
        assert restarted.readiness is ReadinessTruth.READY
        manager._operator_child_done(
            old_collect,
            role="collect",
            generation=old_generation,
        )
        assert manager.snapshot_operator_safety() is restarted
        assert manager._safety_monitor_active is True
    finally:
        await manager.stop()
