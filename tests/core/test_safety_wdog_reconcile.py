"""SafetyManager reconcile with the Keithley firmware watchdog.

If the driver reports the firmware dead-man watchdog tripped (it killed the
outputs while the host was away), SafetyManager must latch FAULT_LATCHED — a
silent re-arm over a tripped watchdog is worse than having no watchdog.
"""

from __future__ import annotations

from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager, SafetyState


class _FakeKeithley:
    def __init__(self, *, tripped: bool) -> None:
        self._tripped = tripped
        self.connected = True
        self.emergency_off_called = False

    async def wdog_tripped(self) -> bool:
        return self._tripped

    async def emergency_off(self, channel: str | None = None) -> bool:
        self.emergency_off_called = True
        return True


async def test_reconcile_trip_latches_fault() -> None:
    k = _FakeKeithley(tripped=True)
    sm = SafetyManager(SafetyBroker(), keithley_driver=k, mock=False)
    sm._state = SafetyState.RUNNING

    await sm._run_checks()

    assert sm.state == SafetyState.FAULT_LATCHED
    assert k.emergency_off_called is True
    assert "watchdog" in sm.fault_reason.lower()


async def test_reconcile_no_trip_stays_running() -> None:
    k = _FakeKeithley(tripped=False)
    sm = SafetyManager(SafetyBroker(), keithley_driver=k, mock=False)
    sm._state = SafetyState.RUNNING

    await sm._run_checks()

    assert sm.state == SafetyState.RUNNING
    assert k.emergency_off_called is False


async def test_reconcile_skipped_in_mock_mode() -> None:
    # Mock managers never touch the firmware watchdog.
    k = _FakeKeithley(tripped=True)
    sm = SafetyManager(SafetyBroker(), keithley_driver=k, mock=True)
    sm._state = SafetyState.RUNNING

    await sm._run_checks()

    assert sm.state == SafetyState.RUNNING
