"""SafetyManager owns every registry-reviewed source disconnect."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from cryodaq.core.broker import DataBroker
from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager, SafetyState
from cryodaq.core.scheduler import InstrumentConfig, ReviewedSourceSettlementIncomplete, Scheduler
from cryodaq.drivers import registry as driver_registry
from cryodaq.drivers.base import InstrumentDriver, Reading
from cryodaq.drivers.contracts import (
    AcquisitionTiming,
    BusDescriptor,
    DriverTrustClass,
    _issue_registry_runtime_binding,
)

_STARTED_MANAGERS: list[SafetyManager] = []


@pytest.fixture(autouse=True)
async def _settle_started_managers() -> None:
    """Close every production-like SafetyManager lifecycle opened by a test."""

    first = len(_STARTED_MANAGERS)
    errors: list[Exception] = []
    try:
        yield
    finally:
        created = _STARTED_MANAGERS[first:]
        try:
            for manager in reversed(created):
                if (
                    manager._collect_task is not None
                    or manager._monitor_task is not None
                    or manager._pending_child_fault_settlements
                ):
                    try:
                        await manager.stop()
                    except Exception as exc:  # preserve cleanup of every owned manager
                        errors.append(exc)
        finally:
            del _STARTED_MANAGERS[first:]
        if errors:
            raise ExceptionGroup("failed to settle started SafetyManager fixtures", errors)


class _ReviewedSource(InstrumentDriver):
    def __init__(self, proofs: list[bool]) -> None:
        super().__init__("reviewed", mock=True)
        self.proofs = list(proofs)
        self.disconnect_calls = 0
        self._connected = True
        self._output_state_unverified = False

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        self._connected = False

    async def read_channels(self) -> list[Reading]:
        return []

    async def emergency_off(self, channel: str | None = None) -> bool:
        del channel
        return self.proofs.pop(0) if len(self.proofs) > 1 else self.proofs[0]

    async def start_source(self, *_args, **_kwargs) -> None:
        return None

    async def stop_source(self, _channel: str) -> None:
        return None

    @property
    def output_state_unverified(self) -> bool:
        return self._output_state_unverified

    @output_state_unverified.setter
    def output_state_unverified(self, value: bool) -> None:
        self._output_state_unverified = value


def _bind_reviewed(
    driver: InstrumentDriver,
    *,
    connect_timeout_s: float = 1.0,
    read_timeout_s: float = 1.0,
    poll_interval_s: float = 1.0,
    bus_id: str | None = None,
    lifecycle: object | None = None,
):
    binding = _issue_registry_runtime_binding(
        driver=driver,
        timing=AcquisitionTiming(connect_timeout_s, read_timeout_s, poll_interval_s),
        registry_provenance="test:reviewed-source-disconnect",
        trust_class=DriverTrustClass.REVIEWED_SOURCE,
        bus_descriptor=BusDescriptor(bus_id) if bus_id is not None else None,
        lifecycle=lifecycle,
    )
    with driver_registry._RUNTIME_BINDINGS_LOCK:
        driver_registry._RUNTIME_BINDINGS[driver] = binding
    return binding


def _manager(driver: InstrumentDriver, binding=None):
    binding = _bind_reviewed(driver) if binding is None else binding
    return (
        SafetyManager(
            SafetyBroker(),
            keithley_driver=driver,
            reviewed_source_runtime_binding=binding,
            mock=False,
        ),
        binding,
    )


async def _start_manager(manager: SafetyManager) -> None:
    if manager._collect_task is None and manager._monitor_task is None:
        # Own the manager before start(): a cancelled/failed startup may have
        # created children and still requires exact teardown.
        _STARTED_MANAGERS.append(manager)
        await manager.start()


async def _qualify_generation(
    manager: SafetyManager,
    driver: InstrumentDriver,
    binding: object,
    *,
    verified_off: bool = True,
) -> None:
    await _start_manager(manager)
    driver._connected = True
    driver.output_state_unverified = not verified_off  # type: ignore[attr-defined]
    generation = await manager.begin_reviewed_source_connect(
        driver,
        binding,  # type: ignore[arg-type]
        "test qualification",
    )
    committed = await manager.complete_reviewed_source_connect(
        driver,
        binding,  # type: ignore[arg-type]
        generation,
        "test qualification",
    )
    assert committed is verified_off


def test_non_mock_manual_connection_record_cannot_grant_authority() -> None:
    driver = _ReviewedSource([True])
    manager, _ = _manager(driver)

    with pytest.raises(RuntimeError, match="simulator-only"):
        manager.record_reviewed_source_connected(verified_off=True)

    assert manager._reviewed_source_generation is None
    assert manager._reviewed_source_connected is False


async def test_safety_manager_keeps_source_tracked_when_off_proof_fails() -> None:
    driver = _ReviewedSource([False])
    manager, binding = _manager(driver)
    manager._active_sources.add("smua")

    assert await manager.disconnect_reviewed_source(driver, binding, None, "poll failure") is False

    assert manager.state is SafetyState.FAULT_LATCHED
    assert manager._active_sources == {"smua"}
    assert driver.disconnect_calls == 0


async def test_safety_manager_disconnects_only_after_exact_true_proof() -> None:
    driver = _ReviewedSource([True])
    manager, binding = _manager(driver)
    manager._active_sources.add("smua")

    assert await manager.disconnect_reviewed_source(driver, binding, None, "poll failure") is True

    assert driver.disconnect_calls == 1
    assert manager._active_sources == set()
    assert manager.state is SafetyState.SAFE_OFF


async def test_truthy_non_boolean_proof_cannot_authorize_disconnect() -> None:
    driver = _ReviewedSource([True])

    async def _truthy_not_true(channel: str | None = None) -> int:
        del channel
        return 1

    driver.emergency_off = _truthy_not_true  # type: ignore[method-assign]
    manager, binding = _manager(driver)
    manager._active_sources.add("smua")

    assert await manager.disconnect_reviewed_source(driver, binding, None, "truthy") is False
    assert manager.state is SafetyState.FAULT_LATCHED
    assert manager._active_sources == {"smua"}
    assert driver.disconnect_calls == 0


async def test_confirmed_disconnect_clears_active_evidence_but_keeps_fault_latched() -> None:
    driver = _ReviewedSource([True])
    manager, binding = _manager(driver)
    manager._state = SafetyState.FAULT_LATCHED
    manager._active_sources.add("smua")

    assert await manager.disconnect_reviewed_source(driver, binding, None, "fault recovery") is True
    assert manager.state is SafetyState.FAULT_LATCHED
    assert manager._active_sources == set()
    assert driver.disconnect_calls == 1


async def test_safety_manager_rejects_different_driver_identity() -> None:
    driver = _ReviewedSource([True])
    impostor = _ReviewedSource([True])
    manager, binding = _manager(driver)
    before_abort = manager._abort_generation

    with pytest.raises(ValueError, match="identity mismatch"):
        await manager.disconnect_reviewed_source(impostor, binding, None, "wrong object")

    assert driver.disconnect_calls == 0
    assert impostor.disconnect_calls == 0
    assert manager._abort_generation == before_abort


async def test_scheduler_never_directly_disconnects_reviewed_binding() -> None:
    driver = _ReviewedSource([True])
    binding = _bind_reviewed(driver)
    scheduler = Scheduler(DataBroker())
    scheduler.add(InstrumentConfig(driver=driver, runtime_binding=binding))

    assert await scheduler._disconnect_driver(driver, context="test") is False
    assert driver.disconnect_calls == 0


async def test_scheduler_routes_reviewed_binding_to_injected_authority() -> None:
    driver = _ReviewedSource([True])
    binding = _bind_reviewed(driver)
    calls: list[tuple[InstrumentDriver, str]] = []

    async def _authority(candidate, candidate_binding, generation, context: str) -> bool:
        assert candidate_binding is binding
        assert generation is None
        calls.append((candidate, context))
        driver._connected = False
        return True

    scheduler = Scheduler(DataBroker(), reviewed_source_disconnect=_authority)
    scheduler.add(InstrumentConfig(driver=driver, runtime_binding=binding))

    assert await scheduler._disconnect_driver(driver, context="recovery") is True
    assert calls == [(driver, "recovery")]
    assert driver.disconnect_calls == 0


async def test_scheduler_does_not_upgrade_truthy_callback_result() -> None:
    driver = _ReviewedSource([True])
    binding = _bind_reviewed(driver)

    async def _truthy(_candidate, _binding, _generation, _context: str) -> int:
        return 1

    scheduler = Scheduler(DataBroker(), reviewed_source_disconnect=_truthy)  # type: ignore[arg-type]
    scheduler.add(InstrumentConfig(driver=driver, runtime_binding=binding))

    assert await scheduler._disconnect_driver(driver, context="recovery") is False


async def test_cancelled_proof_is_settled_and_faults_if_ambiguous() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    driver = _ReviewedSource([False])

    async def _slow_false(channel: str | None = None) -> bool:
        del channel
        entered.set()
        await release.wait()
        return False

    driver.emergency_off = _slow_false  # type: ignore[method-assign]
    manager, binding = _manager(driver)
    manager._active_sources.add("smua")
    task = asyncio.create_task(manager.disconnect_reviewed_source(driver, binding, None, "cancelled"))
    await entered.wait()
    task.cancel()
    release.set()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert manager.state is SafetyState.FAULT_LATCHED
    assert manager._active_sources == {"smua"}
    assert driver.disconnect_calls == 0


async def test_internally_cancelled_proof_latches_without_cancelling_caller() -> None:
    driver = _ReviewedSource([False])

    async def _internally_cancelled(channel: str | None = None) -> bool:
        del channel
        raise asyncio.CancelledError

    driver.emergency_off = _internally_cancelled  # type: ignore[method-assign]
    manager, binding = _manager(driver)
    manager._active_sources.add("smua")

    assert await manager.disconnect_reviewed_source(driver, binding, None, "child cancelled") is False
    assert manager.state is SafetyState.FAULT_LATCHED
    assert manager._active_sources == {"smua"}
    assert driver.disconnect_calls == 0


async def test_scheduler_timeout_cannot_clear_abort_intent_for_inflight_start() -> None:
    driver = _ReviewedSource([True])
    binding = _bind_reviewed(driver)
    started = asyncio.Event()
    release = asyncio.Event()

    async def _slow_start(*_args, **_kwargs) -> None:
        started.set()
        await release.wait()

    driver.start_source = _slow_start  # type: ignore[attr-defined]
    driver.output_state_unverified = False  # type: ignore[attr-defined]
    driver.emergency_off = AsyncMock(return_value=True)  # type: ignore[method-assign]
    manager, _ = _manager(driver, binding)
    manager._config.critical_channels = []
    await _qualify_generation(manager, driver, binding)
    scheduler = Scheduler(
        DataBroker(),
        reviewed_source_disconnect=manager.disconnect_reviewed_source,
    )
    scheduler.add(InstrumentConfig(driver=driver, runtime_binding=binding))

    run_task = asyncio.create_task(manager.request_run(0.5, 40.0, 1.0, channel="smua"))
    await started.wait()
    disconnected = await scheduler._disconnect_driver(
        driver,
        timeout_s=0.01,
        context="timeout while start owns command lock",
    )
    assert disconnected is False

    release.set()
    run_result = await run_task

    assert run_result["ok"] is False
    assert manager.state in {SafetyState.SAFE_OFF, SafetyState.FAULT_LATCHED}
    assert manager.state is not SafetyState.RUNNING
    assert manager._active_sources == set()
    assert driver.emergency_off.await_count >= 1
    assert driver.disconnect_calls == 0


async def test_full_disconnect_timeout_aborts_all_channels_before_safe_off() -> None:
    driver = _ReviewedSource([True])
    binding = _bind_reviewed(driver)
    started = asyncio.Event()
    release = asyncio.Event()

    async def _slow_start(*_args, **_kwargs) -> None:
        started.set()
        await release.wait()

    driver.start_source = _slow_start  # type: ignore[attr-defined]
    driver.output_state_unverified = False  # type: ignore[attr-defined]
    driver.emergency_off = AsyncMock(return_value=True)  # type: ignore[method-assign]
    manager, _ = _manager(driver, binding)
    manager._config.critical_channels = []
    await _qualify_generation(manager, driver, binding)
    manager._state = SafetyState.RUNNING
    manager._active_sources.add("smub")
    scheduler = Scheduler(
        DataBroker(),
        reviewed_source_disconnect=manager.disconnect_reviewed_source,
    )
    scheduler.add(InstrumentConfig(driver=driver, runtime_binding=binding))

    run_task = asyncio.create_task(manager.request_run(0.5, 40.0, 1.0, channel="smua"))
    await started.wait()
    assert not await scheduler._disconnect_driver(
        driver,
        timeout_s=0.01,
        context="full disconnect timeout during smua start",
    )
    release.set()

    run_result = await run_task

    assert run_result["ok"] is False
    driver.emergency_off.assert_awaited_with(None)
    assert manager._active_sources == set()
    assert manager.state is SafetyState.SAFE_OFF
    assert not (manager.state is SafetyState.SAFE_OFF and manager._active_sources), (
        "SAFE_OFF must never retain an active source"
    )


async def test_narrow_abort_preserves_existing_channel_and_running_state() -> None:
    driver = _ReviewedSource([True])
    started = asyncio.Event()
    release = asyncio.Event()

    async def _slow_start(*_args, **_kwargs) -> None:
        started.set()
        await release.wait()

    driver.start_source = _slow_start  # type: ignore[attr-defined]
    driver.output_state_unverified = False  # type: ignore[attr-defined]
    driver.emergency_off = AsyncMock(return_value=True)  # type: ignore[method-assign]
    manager, binding = _manager(driver)
    manager._config.critical_channels = []
    await _qualify_generation(manager, driver, binding)
    manager._state = SafetyState.RUNNING
    manager._active_sources.add("smub")

    run_task = asyncio.create_task(manager.request_run(0.5, 40.0, 1.0, channel="smua"))
    await started.wait()
    generation = manager._abort_generation
    abort_task = asyncio.create_task(manager.emergency_off(channel="smua"))
    await asyncio.sleep(0)
    assert manager._abort_generation > generation
    release.set()

    run_result = await run_task
    abort_result = await abort_task

    assert run_result["ok"] is False
    assert abort_result["ok"] is True
    assert manager._active_sources == {"smub"}
    assert manager.state is SafetyState.RUNNING
    assert all(call.args == ("smua",) for call in driver.emergency_off.await_args_list)
    assert not (manager.state is SafetyState.SAFE_OFF and manager._active_sources), (
        "SAFE_OFF must never retain an active source"
    )


async def test_active_source_reconnect_fault_and_ack_cannot_reuse_generation() -> None:
    driver = _ReviewedSource([True])
    manager, binding = _manager(driver)
    manager._config.critical_channels = []
    manager._config.cooldown_before_rearm_s = 0.0
    await _qualify_generation(manager, driver, binding)
    manager._state = SafetyState.RUNNING
    manager._active_sources.add("smua")

    stale_generation = await manager.begin_reviewed_source_connect(
        driver,
        binding,
        "active reconnect",
    )

    assert manager.state is SafetyState.FAULT_LATCHED
    assert manager._reviewed_source_generation is None
    assert manager._active_sources == set()
    assert (
        await manager.complete_reviewed_source_connect(
            driver,
            binding,
            stale_generation,
            "late active reconnect",
        )
        is False
    )
    assert (await manager.acknowledge_fault("reviewed reconnect"))["ok"] is True
    manager._transition(SafetyState.READY, "test recovered state")
    blocked = await manager.request_run(0.1, 1.0, 0.1)
    assert blocked["ok"] is False
    assert "generation" in blocked["error"]

    fresh = await manager.begin_reviewed_source_connect(driver, binding, "fresh reconnect")
    assert (
        await manager.complete_reviewed_source_connect(
            driver,
            binding,
            fresh,
            "fresh reconnect",
        )
        is True
    )
    manager._transition(SafetyState.READY, "fresh reviewed evidence")
    assert (await manager.request_run(0.1, 1.0, 0.1))["ok"] is True


async def test_timed_out_reviewed_connect_is_retained_and_blocks_retry() -> None:
    driver = _ReviewedSource([True])
    binding = _bind_reviewed(driver, connect_timeout_s=0.01)
    driver._connected = False
    entered = asyncio.Event()
    release = asyncio.Event()
    connect_calls = 0

    async def _slow_connect() -> None:
        nonlocal connect_calls
        connect_calls += 1
        entered.set()
        await release.wait()
        driver._connected = True

    driver.connect = _slow_connect  # type: ignore[method-assign]
    manager = SafetyManager(
        SafetyBroker(),
        keithley_driver=driver,
        reviewed_source_runtime_binding=binding,
        mock=False,
    )
    await _start_manager(manager)
    scheduler = Scheduler(
        DataBroker(),
        reviewed_source_connect_begin=manager.begin_reviewed_source_connect,
        reviewed_source_connect_complete=manager.complete_reviewed_source_connect,
        reviewed_source_uncertain=manager.mark_reviewed_source_uncertain,
        reviewed_source_connect_abandon=manager.abandon_reviewed_source_connect,
        reviewed_source_disconnect=manager.disconnect_reviewed_source,
    )
    config = InstrumentConfig(driver=driver, runtime_binding=binding)
    scheduler.add(config)
    state = scheduler._instruments[driver.name]

    with pytest.raises(TimeoutError):
        await scheduler._connect_driver(state, context="timeout test")
    await entered.wait()
    assert state.reviewed_source_settlement_task is not None
    assert not state.reviewed_source_settlement_task.done()
    # The caller returns at its deadline without awaiting cleanup, but the
    # synchronous abandonment cut has already made RUN authority impossible.
    assert manager._reviewed_source_generation is None
    assert manager._reviewed_source_connected is False
    assert manager._reviewed_source_verified_off is False
    manager._config.critical_channels = []
    blocked = await manager.request_run(0.1, 1.0, 0.1)
    assert blocked["ok"] is False
    assert manager.state is not SafetyState.RUNNING
    with pytest.raises(RuntimeError, match="unsettled prior connect"):
        await scheduler._connect_driver(state, context="forbidden retry")
    assert connect_calls == 1

    release.set()
    await state.reviewed_source_settlement_task
    assert connect_calls == 1
    assert manager._reviewed_source_generation is None
    assert manager.snapshot_operator_safety().verified_off is False
    assert driver.connected is False


async def test_reviewed_connect_rejects_incomplete_lifecycle_before_driver_io() -> None:
    driver = _ReviewedSource([True])
    binding = _bind_reviewed(driver)
    driver._connected = False
    manager = SafetyManager(
        SafetyBroker(),
        keithley_driver=driver,
        reviewed_source_runtime_binding=binding,
        mock=False,
    )
    scheduler = Scheduler(
        DataBroker(),
        reviewed_source_connect_begin=manager.begin_reviewed_source_connect,
        reviewed_source_connect_complete=manager.complete_reviewed_source_connect,
        reviewed_source_uncertain=manager.mark_reviewed_source_uncertain,
        reviewed_source_disconnect=manager.disconnect_reviewed_source,
    )
    scheduler.add(InstrumentConfig(driver=driver, runtime_binding=binding))
    state = scheduler._instruments[driver.name]

    with pytest.raises(RuntimeError, match="complete SafetyManager lifecycle authority"):
        await scheduler._connect_driver(state, context="missing synchronous cut")

    assert state.reviewed_source_attempt is None
    assert manager._reviewed_source_generation is None
    assert driver.connected is False


async def test_stale_generation_cannot_register_abort_or_revoke_newer_generation() -> None:
    driver = _ReviewedSource([True])
    manager, binding = _manager(driver)
    await _qualify_generation(manager, driver, binding)
    current = manager._reviewed_source_generation
    before = manager._abort_generation

    await manager.mark_reviewed_source_uncertain(driver, binding, object(), "stale precheck")
    assert manager._abort_generation == before
    assert manager._reviewed_source_generation is current

    await manager._cmd_lock.acquire()
    task = asyncio.create_task(manager.mark_reviewed_source_uncertain(driver, binding, current, "stale lock recheck"))
    try:
        for _ in range(20):
            if manager._abort_generation > before:
                break
            await asyncio.sleep(0)
        replacement = object()
        manager._reviewed_source_generation = replacement  # type: ignore[assignment]
    finally:
        manager._cmd_lock.release()
    await task

    assert manager._reviewed_source_generation is replacement
    assert manager._reviewed_source_connected is True


async def test_timeout_racing_committed_complete_revokes_before_run_can_start() -> None:
    driver = _ReviewedSource([True])
    binding = _bind_reviewed(driver, connect_timeout_s=0.01)
    driver._connected = False
    manager = SafetyManager(
        SafetyBroker(),
        keithley_driver=driver,
        reviewed_source_runtime_binding=binding,
        mock=False,
    )
    await _start_manager(manager)
    manager._config.critical_channels = []
    committed = asyncio.Event()
    release_complete = asyncio.Event()

    async def _complete(candidate, candidate_binding, generation, context: str) -> bool:
        result = await manager.complete_reviewed_source_connect(
            candidate,
            candidate_binding,
            generation,
            context,
        )
        assert result is True
        committed.set()
        await release_complete.wait()
        return result

    scheduler = Scheduler(
        DataBroker(),
        reviewed_source_connect_begin=manager.begin_reviewed_source_connect,
        reviewed_source_connect_complete=_complete,
        reviewed_source_uncertain=manager.mark_reviewed_source_uncertain,
        reviewed_source_connect_abandon=manager.abandon_reviewed_source_connect,
        reviewed_source_disconnect=manager.disconnect_reviewed_source,
    )
    scheduler.add(InstrumentConfig(driver=driver, runtime_binding=binding))
    state = scheduler._instruments[driver.name]
    before_abort = manager._abort_generation

    with pytest.raises(TimeoutError):
        await scheduler._connect_driver(state, context="complete race")
    assert committed.is_set()
    assert manager._abort_generation > before_abort
    assert manager._reviewed_source_generation is None
    assert manager._reviewed_source_connected is False
    assert manager._reviewed_source_verified_off is False
    blocked = await manager.request_run(0.1, 1.0, 0.1)
    assert blocked["ok"] is False
    assert manager.state is not SafetyState.RUNNING

    release_complete.set()
    assert state.reviewed_source_settlement_task is not None
    await state.reviewed_source_settlement_task
    assert driver.connected is False


@pytest.mark.parametrize(
    "disconnect_result",
    (False, 1, OSError("disconnect failed")),
)
async def test_abandoned_connect_cleanup_requires_literal_true(
    disconnect_result: object,
) -> None:
    driver = _ReviewedSource([True])
    binding = _bind_reviewed(driver, connect_timeout_s=0.01)
    driver._connected = False
    entered = asyncio.Event()
    release = asyncio.Event()

    async def _connect() -> None:
        entered.set()
        await release.wait()
        driver._connected = True

    async def _disconnect(*_args) -> object:
        if isinstance(disconnect_result, BaseException):
            raise disconnect_result
        return disconnect_result

    driver.connect = _connect  # type: ignore[method-assign]
    manager = SafetyManager(
        SafetyBroker(),
        keithley_driver=driver,
        reviewed_source_runtime_binding=binding,
        mock=False,
    )
    await _start_manager(manager)
    scheduler = Scheduler(
        DataBroker(),
        reviewed_source_connect_begin=manager.begin_reviewed_source_connect,
        reviewed_source_connect_complete=manager.complete_reviewed_source_connect,
        reviewed_source_uncertain=manager.mark_reviewed_source_uncertain,
        reviewed_source_connect_abandon=manager.abandon_reviewed_source_connect,
        reviewed_source_disconnect=_disconnect,  # type: ignore[arg-type]
    )
    scheduler.add(InstrumentConfig(driver=driver, runtime_binding=binding))
    state = scheduler._instruments[driver.name]

    with pytest.raises(TimeoutError):
        await scheduler._connect_driver(state, context="literal true cleanup")
    await entered.wait()
    release.set()
    assert state.reviewed_source_settlement_task is not None
    await state.reviewed_source_settlement_task

    assert state.reviewed_source_attempt is not None
    assert state.reviewed_source_attempt.failure is not None
    with pytest.raises(ReviewedSourceSettlementIncomplete):
        scheduler._adjudicate_reviewed_attempt(state)


async def test_partial_connect_error_disconnects_even_when_uncertainty_callback_raises() -> None:
    driver = _ReviewedSource([True])
    binding = _bind_reviewed(driver)
    driver._connected = False

    async def _partial_connect() -> None:
        driver._connected = True
        raise OSError("partial connect")

    async def _uncertain(*_args) -> None:
        raise RuntimeError("uncertainty callback failed")

    driver.connect = _partial_connect  # type: ignore[method-assign]
    manager = SafetyManager(
        SafetyBroker(),
        keithley_driver=driver,
        reviewed_source_runtime_binding=binding,
        mock=False,
    )
    await _start_manager(manager)
    scheduler = Scheduler(
        DataBroker(),
        reviewed_source_connect_begin=manager.begin_reviewed_source_connect,
        reviewed_source_connect_complete=manager.complete_reviewed_source_connect,
        reviewed_source_uncertain=_uncertain,
        reviewed_source_connect_abandon=manager.abandon_reviewed_source_connect,
        reviewed_source_disconnect=manager.disconnect_reviewed_source,
    )
    scheduler.add(InstrumentConfig(driver=driver, runtime_binding=binding))
    state = scheduler._instruments[driver.name]

    with pytest.raises(RuntimeError, match="connect failed"):
        await scheduler._connect_driver(state, context="partial connect")

    assert driver.disconnect_calls == 1
    assert driver.connected is False
    assert state.reviewed_source_attempt is None
    assert manager._reviewed_source_generation is None


async def test_repeated_caller_cancellation_cannot_cancel_off_or_disconnect_proof() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    driver = _ReviewedSource([True])

    async def _slow_true(channel: str | None = None) -> bool:
        del channel
        entered.set()
        await release.wait()
        return True

    driver.emergency_off = _slow_true  # type: ignore[method-assign]
    manager, binding = _manager(driver)
    manager._active_sources.add("smua")
    task = asyncio.create_task(manager.disconnect_reviewed_source(driver, binding, None, "double cancel"))
    await entered.wait()
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    release.set()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert driver.disconnect_calls == 1
    assert driver.connected is False
    assert manager._active_sources == set()


async def test_failed_done_disconnect_owner_is_consumed_and_retried() -> None:
    driver = _ReviewedSource([True])
    binding = _bind_reviewed(driver)
    results = iter((False, True))
    calls = 0

    async def _disconnect(*_args) -> bool:
        nonlocal calls
        calls += 1
        result = next(results)
        if result:
            driver._connected = False
        return result

    scheduler = Scheduler(DataBroker(), reviewed_source_disconnect=_disconnect)
    scheduler.add(InstrumentConfig(driver=driver, runtime_binding=binding))
    state = scheduler._instruments[driver.name]

    assert await scheduler._disconnect_driver(driver, context="first") is False
    assert state.reviewed_source_disconnect_task is None
    assert state.reviewed_source_disconnect_required is True
    assert await scheduler._disconnect_driver(driver, context="retry") is True
    assert calls == 2
    assert state.reviewed_source_disconnect_task is None
    assert state.reviewed_source_disconnect_required is False


async def test_stop_retains_pending_connect_owner_then_second_stop_settles() -> None:
    driver = _ReviewedSource([True])
    binding = _bind_reviewed(driver, connect_timeout_s=0.01)
    driver._connected = False
    entered = asyncio.Event()
    release = asyncio.Event()

    async def _connect() -> None:
        entered.set()
        await release.wait()
        driver._connected = True

    driver.connect = _connect  # type: ignore[method-assign]
    manager = SafetyManager(
        SafetyBroker(),
        keithley_driver=driver,
        reviewed_source_runtime_binding=binding,
        mock=False,
    )
    await _start_manager(manager)
    scheduler = Scheduler(
        DataBroker(),
        drain_timeout_s=0.01,
        reviewed_source_connect_begin=manager.begin_reviewed_source_connect,
        reviewed_source_connect_complete=manager.complete_reviewed_source_connect,
        reviewed_source_uncertain=manager.mark_reviewed_source_uncertain,
        reviewed_source_connect_abandon=manager.abandon_reviewed_source_connect,
        reviewed_source_disconnect=manager.disconnect_reviewed_source,
    )
    scheduler.add(InstrumentConfig(driver=driver, runtime_binding=binding))
    state = scheduler._instruments[driver.name]

    with pytest.raises(TimeoutError):
        await scheduler._connect_driver(state, context="pending stop")
    await entered.wait()
    with pytest.raises(ReviewedSourceSettlementIncomplete, match="connect owner still pending"):
        await scheduler.stop()
    assert state.reviewed_source_attempt is not None

    release.set()
    assert state.reviewed_source_settlement_task is not None
    await state.reviewed_source_settlement_task
    await scheduler.stop()
    assert state.reviewed_source_attempt is None
    assert driver.connected is False


async def test_stop_retries_failed_exact_cleanup_without_publishing_success() -> None:
    driver = _ReviewedSource([True])
    binding = _bind_reviewed(driver, connect_timeout_s=0.01)
    driver._connected = False
    release = asyncio.Event()
    outcomes = iter((False, False, True))

    async def _connect() -> None:
        await release.wait()
        driver._connected = True

    async def _disconnect(*_args) -> bool:
        result = next(outcomes)
        if result:
            driver._connected = False
        return result

    driver.connect = _connect  # type: ignore[method-assign]
    manager = SafetyManager(
        SafetyBroker(),
        keithley_driver=driver,
        reviewed_source_runtime_binding=binding,
        mock=False,
    )
    await _start_manager(manager)
    scheduler = Scheduler(
        DataBroker(),
        drain_timeout_s=0.05,
        reviewed_source_connect_begin=manager.begin_reviewed_source_connect,
        reviewed_source_connect_complete=manager.complete_reviewed_source_connect,
        reviewed_source_uncertain=manager.mark_reviewed_source_uncertain,
        reviewed_source_connect_abandon=manager.abandon_reviewed_source_connect,
        reviewed_source_disconnect=_disconnect,
    )
    scheduler.add(InstrumentConfig(driver=driver, runtime_binding=binding))
    state = scheduler._instruments[driver.name]

    with pytest.raises(TimeoutError):
        await scheduler._connect_driver(state, context="retry stop")
    release.set()
    assert state.reviewed_source_settlement_task is not None
    await state.reviewed_source_settlement_task
    with pytest.raises(ReviewedSourceSettlementIncomplete, match="connect cleanup unproved"):
        await scheduler.stop()
    assert state.reviewed_source_attempt is not None

    await scheduler.stop()
    assert state.reviewed_source_attempt is None
    assert driver.connected is False


async def test_first_standalone_reviewed_read_error_disconnects_immediately() -> None:
    driver = _ReviewedSource([True])
    manager, binding = _manager(driver)
    await _qualify_generation(manager, driver, binding)
    driver.safe_read = AsyncMock(side_effect=OSError("read failed"))  # type: ignore[method-assign]
    scheduler = Scheduler(
        DataBroker(),
        reviewed_source_uncertain=manager.mark_reviewed_source_uncertain,
        reviewed_source_disconnect=manager.disconnect_reviewed_source,
    )
    scheduler.add(InstrumentConfig(driver=driver, runtime_binding=binding))
    state = scheduler._instruments[driver.name]
    state.reviewed_source_generation = manager._reviewed_source_generation
    state.reviewed_source_disconnect_required = False

    async def _stop_backoff(*_args, **_kwargs) -> None:
        scheduler._running = False

    scheduler._backoff = _stop_backoff  # type: ignore[method-assign]
    scheduler._running = True
    await scheduler._poll_loop(state)

    driver.safe_read.assert_awaited_once()
    assert driver.disconnect_calls == 1
    assert driver.connected is False
    assert state.reviewed_source_generation is None


async def test_shared_bus_disconnect_barrier_blocks_reviewed_read_io() -> None:
    driver = _ReviewedSource([True])
    binding = _bind_reviewed(driver, bus_id="reviewed-bus")
    driver.safe_read = AsyncMock(return_value=[])  # type: ignore[method-assign]
    scheduler: Scheduler

    async def _disconnect(*_args) -> bool:
        scheduler._running = False
        return False

    scheduler = Scheduler(DataBroker(), reviewed_source_disconnect=_disconnect)
    scheduler.add(InstrumentConfig(driver=driver, runtime_binding=binding))
    state = scheduler._instruments[driver.name]
    assert state.reviewed_source_disconnect_required is True

    scheduler._running = True
    await scheduler._shared_bus_poll_loop("reviewed-bus", [state])

    driver.safe_read.assert_not_awaited()
    assert state.reviewed_source_disconnect_required is True


async def test_first_shared_bus_reviewed_read_error_disconnects_immediately() -> None:
    driver = _ReviewedSource([True])
    binding = _bind_reviewed(driver, bus_id="reviewed-read-bus")
    manager = SafetyManager(
        SafetyBroker(),
        keithley_driver=driver,
        reviewed_source_runtime_binding=binding,
        mock=False,
    )
    await _qualify_generation(manager, driver, binding)
    driver.safe_read = AsyncMock(side_effect=OSError("shared read failed"))  # type: ignore[method-assign]
    scheduler: Scheduler

    async def _disconnect(*args) -> bool:
        result = await manager.disconnect_reviewed_source(*args)
        scheduler._running = False
        return result

    scheduler = Scheduler(
        DataBroker(),
        reviewed_source_uncertain=manager.mark_reviewed_source_uncertain,
        reviewed_source_disconnect=_disconnect,
    )
    scheduler.add(InstrumentConfig(driver=driver, runtime_binding=binding))
    state = scheduler._instruments[driver.name]
    state.reviewed_source_generation = manager._reviewed_source_generation
    state.reviewed_source_disconnect_required = False

    scheduler._running = True
    await scheduler._shared_bus_poll_loop("reviewed-read-bus", [state])

    driver.safe_read.assert_awaited_once()
    assert driver.disconnect_calls == 1
    assert driver.connected is False
    assert state.reviewed_source_generation is None


async def test_non_reviewed_connect_path_calls_driver_once() -> None:
    driver = _ReviewedSource([True])
    with driver_registry._RUNTIME_BINDINGS_LOCK:
        driver_registry._RUNTIME_BINDINGS.pop(driver, None)
    driver._connected = False
    calls = 0

    async def _connect() -> None:
        nonlocal calls
        calls += 1
        driver._connected = True

    driver.connect = _connect  # type: ignore[method-assign]
    scheduler = Scheduler(DataBroker())
    scheduler.add(InstrumentConfig(driver=driver))
    state = scheduler._instruments[driver.name]

    await scheduler._connect_driver(state, context="passive connect")

    assert calls == 1
    assert driver.connected is True


async def test_sealed_reviewed_binding_cannot_downgrade_after_registry_removal() -> None:
    driver = _ReviewedSource([True])
    binding = _bind_reviewed(driver)
    authority_calls = 0

    async def _authority(*_args: object) -> bool:
        nonlocal authority_calls
        authority_calls += 1
        driver._connected = False
        return True

    scheduler = Scheduler(DataBroker(), reviewed_source_disconnect=_authority)
    scheduler.add(InstrumentConfig(driver=driver, runtime_binding=binding))
    with driver_registry._RUNTIME_BINDINGS_LOCK:
        driver_registry._RUNTIME_BINDINGS.pop(driver, None)

    assert await scheduler._disconnect_driver(driver, context="registry removed") is True
    assert authority_calls == 1
    assert driver.disconnect_calls == 0


async def test_exact_disconnect_receipt_requires_connected_false_then_retries() -> None:
    driver = _ReviewedSource([True])
    binding = _bind_reviewed(driver)
    calls = 0

    async def _authority(*_args: object) -> bool:
        nonlocal calls
        calls += 1
        if calls == 2:
            driver._connected = False
        return True

    scheduler = Scheduler(DataBroker(), reviewed_source_disconnect=_authority)
    scheduler.add(InstrumentConfig(driver=driver, runtime_binding=binding))

    assert await scheduler._disconnect_driver(driver, context="no-op receipt") is False
    state = scheduler._instruments[driver.name]
    assert state.reviewed_source_disconnect_required is True
    assert driver.connected is True
    assert await scheduler._disconnect_driver(driver, context="real retry") is True
    assert calls == 2


async def test_manager_rejects_normal_returning_noop_disconnect() -> None:
    driver = _ReviewedSource([True])

    async def _noop_disconnect() -> None:
        driver.disconnect_calls += 1

    driver.disconnect = _noop_disconnect  # type: ignore[method-assign]
    manager, binding = _manager(driver)
    manager._active_sources.add("smua")

    assert await manager.disconnect_reviewed_source(driver, binding, None, "no-op") is False
    assert driver.connected is True
    assert manager.state is SafetyState.FAULT_LATCHED


async def test_poll_barrier_retries_failed_cleanup_then_allows_fresh_generation() -> None:
    driver = _ReviewedSource([True])
    binding = _bind_reviewed(driver, connect_timeout_s=0.01)
    driver._connected = False
    entered = asyncio.Event()
    release = asyncio.Event()
    disconnect_outcomes = iter((False, True))

    async def _blocked_connect() -> None:
        entered.set()
        await release.wait()
        driver._connected = True

    async def _disconnect(*_args: object) -> bool:
        result = next(disconnect_outcomes)
        if result:
            driver._connected = False
        return result

    driver.connect = _blocked_connect  # type: ignore[method-assign]
    manager = SafetyManager(
        SafetyBroker(),
        keithley_driver=driver,
        reviewed_source_runtime_binding=binding,
        mock=False,
    )
    await _start_manager(manager)
    scheduler = Scheduler(
        DataBroker(),
        reviewed_source_connect_begin=manager.begin_reviewed_source_connect,
        reviewed_source_connect_complete=manager.complete_reviewed_source_connect,
        reviewed_source_uncertain=manager.mark_reviewed_source_uncertain,
        reviewed_source_connect_abandon=manager.abandon_reviewed_source_connect,
        reviewed_source_disconnect=_disconnect,
    )
    scheduler.add(InstrumentConfig(driver=driver, runtime_binding=binding))
    state = scheduler._instruments[driver.name]

    with pytest.raises(TimeoutError):
        await scheduler._connect_driver(state, context="first generation")
    await entered.wait()
    release.set()
    assert state.reviewed_source_settlement_task is not None
    await state.reviewed_source_settlement_task
    assert state.reviewed_source_attempt is not None
    assert await scheduler._settle_reviewed_poll_barrier(state, "poll retry") is True
    assert state.reviewed_source_attempt is None

    async def _fresh_connect() -> None:
        driver._connected = True

    driver.connect = _fresh_connect  # type: ignore[method-assign]
    await scheduler._connect_driver(state, context="fresh generation")
    assert state.reviewed_source_attempt is None
    assert state.reviewed_source_generation is manager._reviewed_source_generation
    assert state.reviewed_source_generation is not None


async def test_shared_bus_cancelled_reviewed_connect_keeps_one_cleanup_owner() -> None:
    class _Lifecycle:
        def __init__(self) -> None:
            self.abort_calls = 0

        async def abort_connect(self) -> None:
            self.abort_calls += 1

    lifecycle = _Lifecycle()
    driver = _ReviewedSource([True])
    binding = _bind_reviewed(
        driver,
        connect_timeout_s=1.0,
        poll_interval_s=0.01,
        bus_id="cancel-connect-bus",
        lifecycle=lifecycle,
    )
    driver._connected = False
    entered = asyncio.Event()
    release = asyncio.Event()

    async def _connect() -> None:
        entered.set()
        await release.wait()
        driver._connected = True

    driver.connect = _connect  # type: ignore[method-assign]
    manager = SafetyManager(
        SafetyBroker(),
        keithley_driver=driver,
        reviewed_source_runtime_binding=binding,
        mock=False,
    )
    await _start_manager(manager)
    scheduler = Scheduler(
        DataBroker(),
        drain_timeout_s=0.01,
        reviewed_source_connect_begin=manager.begin_reviewed_source_connect,
        reviewed_source_connect_complete=manager.complete_reviewed_source_connect,
        reviewed_source_uncertain=manager.mark_reviewed_source_uncertain,
        reviewed_source_connect_abandon=manager.abandon_reviewed_source_connect,
        reviewed_source_disconnect=manager.disconnect_reviewed_source,
    )
    scheduler.add(InstrumentConfig(driver=driver, runtime_binding=binding))
    await scheduler.start()
    state = scheduler._instruments[driver.name]
    poll_task = state.task
    assert poll_task is not None
    await entered.wait()
    poll_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await poll_task

    assert lifecycle.abort_calls == 0
    assert state.reviewed_source_attempt is not None
    assert manager._reviewed_source_generation is None
    release.set()
    assert state.reviewed_source_settlement_task is not None
    await state.reviewed_source_settlement_task
    await scheduler.stop()
    assert driver.disconnect_calls == 1


async def test_terminal_shared_read_requires_fresh_disconnect_after_live_task_settles() -> None:
    driver = _ReviewedSource([True])
    binding = _bind_reviewed(
        driver,
        connect_timeout_s=0.02,
        read_timeout_s=0.01,
        poll_interval_s=0.01,
        bus_id="terminal-reviewed-read",
    )
    manager = SafetyManager(
        SafetyBroker(),
        keithley_driver=driver,
        reviewed_source_runtime_binding=binding,
        mock=False,
    )
    manager._config.critical_channels = []
    await _qualify_generation(manager, driver, binding)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def _resistant_read() -> list[Reading]:
        entered.set()
        while not release.is_set():
            try:
                await release.wait()
            except asyncio.CancelledError:
                continue
        return []

    driver.safe_read = _resistant_read  # type: ignore[method-assign]
    scheduler = Scheduler(
        DataBroker(),
        drain_timeout_s=0.01,
        reviewed_source_connect_abandon=manager.abandon_reviewed_source_connect,
        reviewed_source_uncertain=manager.mark_reviewed_source_uncertain,
        reviewed_source_disconnect=manager.disconnect_reviewed_source,
    )
    scheduler.add(InstrumentConfig(driver=driver, runtime_binding=binding))
    state = scheduler._instruments[driver.name]
    state.reviewed_source_generation = manager._reviewed_source_generation
    state.reviewed_source_disconnect_required = False
    await scheduler.start()
    await entered.wait()
    shared_task = state.task
    assert shared_task is not None
    await asyncio.wait_for(shared_task, timeout=0.5)

    assert manager._reviewed_source_generation is None
    blocked = await manager.request_run(0.1, 1.0, 0.1)
    assert blocked["ok"] is False
    assert "terminal-reviewed-read" in scheduler._unsettled_bus_operations
    with pytest.raises(ReviewedSourceSettlementIncomplete, match="still pending"):
        await scheduler.stop()

    first_disconnects = driver.disconnect_calls
    release.set()
    retained = scheduler._unsettled_bus_operations.get("terminal-reviewed-read")
    if retained is not None:
        await asyncio.wait_for(retained, timeout=0.5)
    await asyncio.sleep(0)
    await scheduler.stop()
    assert driver.disconnect_calls > first_disconnects
    assert driver.connected is False


async def test_standalone_resistant_read_stop_is_bounded_and_retryable() -> None:
    driver = _ReviewedSource([True])
    binding = _bind_reviewed(
        driver,
        connect_timeout_s=0.02,
        read_timeout_s=10.0,
        poll_interval_s=0.01,
    )
    manager = SafetyManager(
        SafetyBroker(),
        keithley_driver=driver,
        reviewed_source_runtime_binding=binding,
        mock=False,
    )
    manager._config.critical_channels = []
    await _qualify_generation(manager, driver, binding)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def _resistant_read() -> list[Reading]:
        entered.set()
        while not release.is_set():
            try:
                await release.wait()
            except asyncio.CancelledError:
                continue
        return []

    driver.safe_read = _resistant_read  # type: ignore[method-assign]
    scheduler = Scheduler(
        DataBroker(),
        drain_timeout_s=0.01,
        reviewed_source_connect_abandon=manager.abandon_reviewed_source_connect,
        reviewed_source_uncertain=manager.mark_reviewed_source_uncertain,
        reviewed_source_disconnect=manager.disconnect_reviewed_source,
    )
    scheduler.add(InstrumentConfig(driver=driver, runtime_binding=binding))
    state = scheduler._instruments[driver.name]
    state.reviewed_source_generation = manager._reviewed_source_generation
    state.reviewed_source_disconnect_required = False
    await scheduler.start()
    await entered.wait()
    poll_task = state.task
    assert poll_task is not None

    started = asyncio.get_running_loop().time()
    with pytest.raises(ReviewedSourceSettlementIncomplete, match="poll task still pending"):
        await scheduler.stop()
    assert asyncio.get_running_loop().time() - started < 0.25
    assert state.task is poll_task
    assert manager._reviewed_source_generation is None
    assert (await manager.request_run(0.1, 1.0, 0.1))["ok"] is False

    release.set()
    await asyncio.gather(poll_task, return_exceptions=True)
    await scheduler.stop()
    assert state.task is None
    assert driver.connected is False
