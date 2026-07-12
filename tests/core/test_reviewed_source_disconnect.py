"""SafetyManager owns every registry-reviewed source disconnect."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from cryodaq.core.broker import DataBroker
from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager, SafetyState
from cryodaq.core.scheduler import InstrumentConfig, Scheduler
from cryodaq.drivers import registry as driver_registry
from cryodaq.drivers.base import InstrumentDriver, Reading
from cryodaq.drivers.contracts import (
    AcquisitionTiming,
    DriverTrustClass,
    _issue_registry_runtime_binding,
)


class _ReviewedSource(InstrumentDriver):
    def __init__(self, proofs: list[bool]) -> None:
        super().__init__("reviewed", mock=True)
        self.proofs = list(proofs)
        self.disconnect_calls = 0
        self._connected = True

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


def _bind_reviewed(driver: InstrumentDriver):
    binding = _issue_registry_runtime_binding(
        driver=driver,
        timing=AcquisitionTiming(1.0, 1.0, 1.0),
        registry_provenance="test:reviewed-source-disconnect",
        trust_class=DriverTrustClass.REVIEWED_SOURCE,
    )
    with driver_registry._RUNTIME_BINDINGS_LOCK:
        driver_registry._RUNTIME_BINDINGS[driver] = binding
    return binding


async def test_safety_manager_keeps_source_tracked_when_off_proof_fails() -> None:
    driver = _ReviewedSource([False])
    manager = SafetyManager(SafetyBroker(), keithley_driver=driver, mock=False)
    manager._active_sources.add("smua")

    assert await manager.disconnect_reviewed_source(driver, "poll failure") is False

    assert manager.state is SafetyState.FAULT_LATCHED
    assert manager._active_sources == {"smua"}
    assert driver.disconnect_calls == 0


async def test_safety_manager_disconnects_only_after_exact_true_proof() -> None:
    driver = _ReviewedSource([True])
    manager = SafetyManager(SafetyBroker(), keithley_driver=driver, mock=False)
    manager._active_sources.add("smua")

    assert await manager.disconnect_reviewed_source(driver, "poll failure") is True

    assert driver.disconnect_calls == 1
    assert manager._active_sources == set()
    assert manager.state is SafetyState.SAFE_OFF


async def test_truthy_non_boolean_proof_cannot_authorize_disconnect() -> None:
    driver = _ReviewedSource([True])

    async def _truthy_not_true(channel: str | None = None) -> int:
        del channel
        return 1

    driver.emergency_off = _truthy_not_true  # type: ignore[method-assign]
    manager = SafetyManager(SafetyBroker(), keithley_driver=driver, mock=False)
    manager._active_sources.add("smua")

    assert await manager.disconnect_reviewed_source(driver, "truthy") is False
    assert manager.state is SafetyState.FAULT_LATCHED
    assert manager._active_sources == {"smua"}
    assert driver.disconnect_calls == 0


async def test_confirmed_disconnect_clears_active_evidence_but_keeps_fault_latched() -> None:
    driver = _ReviewedSource([True])
    manager = SafetyManager(SafetyBroker(), keithley_driver=driver, mock=False)
    manager._state = SafetyState.FAULT_LATCHED
    manager._active_sources.add("smua")

    assert await manager.disconnect_reviewed_source(driver, "fault recovery") is True
    assert manager.state is SafetyState.FAULT_LATCHED
    assert manager._active_sources == set()
    assert driver.disconnect_calls == 1


async def test_safety_manager_rejects_different_driver_identity() -> None:
    driver = _ReviewedSource([True])
    impostor = _ReviewedSource([True])
    manager = SafetyManager(SafetyBroker(), keithley_driver=driver, mock=False)

    with pytest.raises(ValueError, match="identity mismatch"):
        await manager.disconnect_reviewed_source(impostor, "wrong object")

    assert driver.disconnect_calls == 0
    assert impostor.disconnect_calls == 0


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

    async def _authority(candidate: InstrumentDriver, context: str) -> bool:
        calls.append((candidate, context))
        return True

    scheduler = Scheduler(DataBroker(), reviewed_source_disconnect=_authority)
    scheduler.add(InstrumentConfig(driver=driver, runtime_binding=binding))

    assert await scheduler._disconnect_driver(driver, context="recovery") is True
    assert calls == [(driver, "recovery")]
    assert driver.disconnect_calls == 0


async def test_scheduler_does_not_upgrade_truthy_callback_result() -> None:
    driver = _ReviewedSource([True])
    binding = _bind_reviewed(driver)

    async def _truthy(_candidate: InstrumentDriver, _context: str) -> int:
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
    manager = SafetyManager(SafetyBroker(), keithley_driver=driver, mock=False)
    manager._active_sources.add("smua")
    task = asyncio.create_task(manager.disconnect_reviewed_source(driver, "cancelled"))
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
    manager = SafetyManager(SafetyBroker(), keithley_driver=driver, mock=False)
    manager._active_sources.add("smua")

    assert await manager.disconnect_reviewed_source(driver, "child cancelled") is False
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
    manager = SafetyManager(SafetyBroker(), keithley_driver=driver, mock=False)
    manager._config.critical_channels = []
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
    manager = SafetyManager(SafetyBroker(), keithley_driver=driver, mock=False)
    manager._config.critical_channels = []
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
    manager = SafetyManager(SafetyBroker(), keithley_driver=driver, mock=False)
    manager._config.critical_channels = []
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
