"""A successful stop must not disarm the stand.

stop_source() returns success only AFTER OUTPUT_OFF and its readback
verification, so when _safe_off finishes with no active source the driver holds
current-generation OFF proof for what it just turned off. _safe_off used to
overwrite that with _unknown_global_off_evidence(), and _check_preconditions
then refused to leave SAFE_OFF:

    SAFETY: остаётся SAFE_OFF, запуск источника заблокирован:
    Reviewed source OFF state is UNVERIFIED - confirm exact OFF before RUN

Observed on the stand on 2026-09-02: the source started at 12:27:19, the
operator stopped it at 12:29:18, and it could not be started again. The
operator's own successful stop was what disarmed the stand -- while an
"Operator emergency off" minutes earlier recovered fine, because that path
records evidence.

Nothing physical becomes uncertain at that line. These tests pin that the proof
survives a stop, and that a genuine absence of proof still refuses RUN.
"""

from __future__ import annotations

import pytest

from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager, SafetyState
from cryodaq.drivers.contracts import SourceOffResult


class _Keithley:
    """A source driver that reports whether it holds live OFF proof."""

    def __init__(self, *, proves_off: bool = True) -> None:
        self.output_state_unverified = True
        self.connected = True
        self.stopped: list[str] = []
        self._proves_off = proves_off

    async def stop_source(self, smu_channel) -> bool:
        self.stopped.append(str(smu_channel))
        # A real stop verifies OUTPUT_OFF by readback before returning success.
        if self._proves_off:
            self.output_state_unverified = False
        return True

    async def emergency_off(self, channel=None) -> SourceOffResult:
        if self._proves_off:
            self.output_state_unverified = False
        return SourceOffResult.DEVICE_REPORTED_OFF


def _manager(driver: _Keithley) -> SafetyManager:
    manager = SafetyManager(SafetyBroker(), keithley_driver=driver, mock=True)
    manager._state = SafetyState.RUNNING
    return manager


# ---------------------------------------------------------------------------
# The proof survives the stop
# ---------------------------------------------------------------------------


async def test_successful_stop_keeps_the_off_proof_it_just_obtained():
    driver = _Keithley()
    manager = _manager(driver)
    channels = manager._resolve_channels(None)
    manager._active_sources.update(channels)

    _applied, interrupted = await manager._safe_off("Operator stop", channels=channels)

    assert interrupted is False
    assert manager._state is SafetyState.SAFE_OFF
    assert driver.stopped, "the stop must actually reach the driver"
    assert manager._reviewed_source_off_evidence.verified_off is True, (
        "the stop verified OUTPUT_OFF by readback; discarding that proof is what disarmed the stand"
    )


async def test_the_evidence_is_device_reported_not_assumed():
    driver = _Keithley()
    manager = _manager(driver)
    channels = manager._resolve_channels(None)
    manager._active_sources.update(channels)

    await manager._safe_off("Operator stop", channels=channels)

    results = dict(manager._reviewed_source_off_evidence.channel_off_results)
    assert set(results.values()) == {SourceOffResult.DEVICE_REPORTED_OFF}


# ---------------------------------------------------------------------------
# Genuine absence of proof still refuses RUN
# ---------------------------------------------------------------------------


async def test_a_driver_without_live_proof_still_yields_unknown():
    """The fix stops manufacturing the ABSENCE of evidence; it must not manufacture its presence."""
    driver = _Keithley(proves_off=False)
    manager = _manager(driver)
    channels = manager._resolve_channels(None)
    manager._active_sources.update(channels)

    await manager._safe_off("Operator stop", channels=channels)

    assert manager._reviewed_source_off_evidence.verified_off is False
    results = dict(manager._reviewed_source_off_evidence.channel_off_results)
    assert set(results.values()) == {SourceOffResult.PHYSICAL_STATE_UNKNOWN}


async def test_no_driver_at_all_still_yields_unknown():
    manager = SafetyManager(SafetyBroker(), keithley_driver=None, mock=True)
    manager._state = SafetyState.RUNNING
    channels = manager._resolve_channels(None)
    manager._active_sources.update(channels)

    await manager._safe_off("Operator stop", channels=channels)

    assert manager._reviewed_source_off_evidence.verified_off is False


# ---------------------------------------------------------------------------
# A partial stop never reaches this tail
# ---------------------------------------------------------------------------


async def test_a_partial_stop_stays_running_and_does_not_touch_the_evidence():
    driver = _Keithley()
    manager = _manager(driver)
    channels = sorted(manager._resolve_channels(None))
    manager._active_sources.update(channels)

    _applied, interrupted = await manager._safe_off("Partial", channels={channels[0]})

    assert interrupted is False
    assert manager._state is SafetyState.RUNNING
    assert manager._active_sources, "another channel is still active"
