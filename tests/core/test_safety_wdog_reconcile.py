"""SafetyManager reconcile with the Keithley software late-pet watchdog.

If the driver reports that a late pet latched after TSP issued OFF commands,
SafetyManager must latch FAULT_LATCHED. This is not an independent physical
OFF proof and does not prove action during complete host death;
silently reactivating after any trip is still unsafe.
"""

from __future__ import annotations

from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager, SafetyState
from cryodaq.drivers import registry as driver_registry
from cryodaq.drivers.contracts import (
    AcquisitionTiming,
    DriverTrustClass,
    _issue_registry_runtime_binding,
)


class _FakeKeithley:
    def __init__(self, *, tripped: bool, ack_ok: bool = True) -> None:
        self._tripped = tripped
        self._ack_ok = ack_ok
        self.connected = True
        self.output_state_unverified = False
        self.emergency_off_called = False
        self.ack_called = False

    async def wdog_tripped(self) -> bool:
        return self._tripped

    @property
    def watchdog_trip_pending(self) -> bool:
        return self._tripped

    async def emergency_off(self, channel: str | None = None) -> bool:
        self.emergency_off_called = True
        return True

    async def acknowledge_wdog_trip(self) -> bool:
        self.ack_called = True
        if self._ack_ok:
            self._tripped = False
        return self._ack_ok


def _manager(driver: _FakeKeithley) -> tuple[SafetyManager, object]:
    binding = _issue_registry_runtime_binding(
        driver=driver,
        timing=AcquisitionTiming(1.0, 1.0, 1.0),
        registry_provenance="test:safety-watchdog-reconcile",
        trust_class=DriverTrustClass.REVIEWED_SOURCE,
    )
    with driver_registry._RUNTIME_BINDINGS_LOCK:
        driver_registry._RUNTIME_BINDINGS[driver] = binding
    return (
        SafetyManager(
            SafetyBroker(),
            keithley_driver=driver,
            reviewed_source_runtime_binding=binding,
            mock=False,
        ),
        binding,
    )


async def _qualify(sm: SafetyManager, driver: _FakeKeithley, binding: object) -> None:
    generation = await sm.begin_reviewed_source_connect(
        driver,
        binding,  # type: ignore[arg-type]
        "watchdog fixture",
    )
    assert (
        await sm.complete_reviewed_source_connect(
            driver,
            binding,  # type: ignore[arg-type]
            generation,
            "watchdog fixture",
        )
        is True
    )


async def test_reconcile_trip_latches_fault() -> None:
    k = _FakeKeithley(tripped=True)
    sm, _ = _manager(k)
    sm._state = SafetyState.RUNNING

    await sm._run_checks()

    assert sm.state == SafetyState.FAULT_LATCHED
    assert k.emergency_off_called is True
    assert "watchdog" in sm.fault_reason.lower()


async def test_reconcile_no_trip_stays_running() -> None:
    k = _FakeKeithley(tripped=False)
    sm, _ = _manager(k)
    sm._state = SafetyState.RUNNING

    await sm._run_checks()

    assert sm.state == SafetyState.RUNNING
    assert k.emergency_off_called is False


async def test_reconcile_invalid_trip_readback_fails_closed() -> None:
    k = _FakeKeithley(tripped=False)

    async def _invalid_readback() -> bool:
        raise ValueError("cryodaq_wdog_tripped must be exactly 0 or 1")

    k.wdog_tripped = _invalid_readback  # type: ignore[method-assign]
    sm, _ = _manager(k)
    sm._state = SafetyState.RUNNING

    await sm._run_checks()

    assert sm.state == SafetyState.FAULT_LATCHED
    assert k.emergency_off_called is True
    assert "invalid/unavailable" in sm.fault_reason


async def test_reconcile_skipped_in_mock_mode() -> None:
    # Mock managers never touch the TSP late-pet checker.
    k = _FakeKeithley(tripped=True)
    sm = SafetyManager(SafetyBroker(), keithley_driver=k, mock=True)
    sm._state = SafetyState.RUNNING

    await sm._run_checks()

    assert sm.state == SafetyState.RUNNING


async def test_trip_acknowledge_recovery_does_not_refault_on_stale_latch() -> None:
    k = _FakeKeithley(tripped=True)
    sm, binding = _manager(k)
    await _qualify(sm, k, binding)
    sm._config.cooldown_before_rearm_s = 0
    sm._config.require_keithley_for_run = False
    sm._state = SafetyState.RUNNING

    await sm._run_checks()
    assert sm.state == SafetyState.FAULT_LATCHED

    result = await sm.acknowledge_fault("Late-pet trip inspected; outputs OFF")
    assert result["ok"] is True
    assert k.ack_called is True
    assert sm.state == SafetyState.MANUAL_RECOVERY

    await sm._run_checks()
    assert sm.state == SafetyState.READY
    sm._state = SafetyState.RUNNING
    await sm._run_checks()
    assert sm.state == SafetyState.RUNNING


async def test_trip_acknowledge_failure_stays_fault_latched_and_actionable() -> None:
    k = _FakeKeithley(tripped=True, ack_ok=False)
    sm, _ = _manager(k)
    sm._config.cooldown_before_rearm_s = 0
    sm._state = SafetyState.RUNNING

    await sm._run_checks()
    result = await sm.acknowledge_fault("Tried recovery")

    assert result["ok"] is False
    assert sm.state == SafetyState.FAULT_LATCHED
    assert k.ack_called is True
    assert "disconnect/reconnect" in result["error"]


async def test_pending_trip_blocks_immediate_run_before_monitor_tick() -> None:
    k = _FakeKeithley(tripped=True)
    sm, _ = _manager(k)
    sm._state = SafetyState.SAFE_OFF

    result = await sm.request_run(0.1, 1.0, 0.1)

    assert result["ok"] is False
    assert "unconsumed prior-trip evidence" in result["error"]
    assert sm.state == SafetyState.SAFE_OFF
