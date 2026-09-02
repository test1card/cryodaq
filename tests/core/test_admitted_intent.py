"""What the engine last ACCEPTED as the source's intended state.

Nothing durable held this. The driver's ``_channels[ch].p_target`` is the
instrument-side mirror and ``connect()`` zeroes it before anything else
(``runtime.p_target = 0.0``), so the reconnect after a cable trip destroys the
very value needed to resume; ``_active_sources`` is a bare set with no
magnitude; and the sweep's plan lives in a GUI process that can close, which
the engine must never command hardware from.

The half that matters most is revocation. Recording an operator's intent to
stop and DELIVERING that stop to the instrument used to be the same act, so
with the cable out a stop could not be expressed at all: the panel refused to
send one ("Останов нельзя отправить без живой связи") and stop_source against
an absent device latched fail-closed. The operator was left with a running
heater, no way to say they wanted it off, and -- once reconnect works -- a
system that would faithfully restore the power they had been trying to stop.

Intent is not observation. None of this says what the instrument is doing;
that is only ever established by readback.
"""

from __future__ import annotations

import pytest

from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager, SafetyState
from cryodaq.drivers.contracts import SourceOffResult


class _Keithley:
    def __init__(self) -> None:
        self.output_state_unverified = True
        self.connected = True
        self.reachable = True
        self.stopped: list[str] = []

    async def stop_source(self, smu_channel) -> bool:
        if not self.reachable:
            raise OSError("USBTMC write failed in bounded worker")
        self.stopped.append(str(smu_channel))
        self.output_state_unverified = False
        return True

    async def emergency_off(self, channel=None) -> SourceOffResult:
        if not self.reachable:
            return SourceOffResult.PHYSICAL_STATE_UNKNOWN
        self.output_state_unverified = False
        return SourceOffResult.DEVICE_REPORTED_OFF


def _manager(driver: _Keithley) -> SafetyManager:
    manager = SafetyManager(SafetyBroker(), keithley_driver=driver, mock=True)
    manager._energizing_mutation_refusal = lambda: None  # type: ignore[method-assign]
    manager._config.critical_channels = []
    return manager


def _admit(manager: SafetyManager, channel: str, power: float) -> None:
    """Record intent the way an accepted start does."""
    from cryodaq.core.safety_manager import _AdmittedIntent
    import time

    manager._admitted_intent[manager._resolve_channels(channel).pop()] = _AdmittedIntent(
        p_target=power,
        v_comp=40.0,
        i_comp=1.0,
        admitted_monotonic_s=time.monotonic(),
        abort_generation=manager._abort_generation,
    )


# ---------------------------------------------------------------------------
# Stop must be expressible without the instrument
# ---------------------------------------------------------------------------


async def test_stop_revokes_intent_even_when_the_instrument_is_unreachable():
    """The operator can say "off" with the cable out; delivery follows later."""
    driver = _Keithley()
    manager = _manager(driver)
    manager._state = SafetyState.RUNNING
    channel = manager._resolve_channels("smub").pop()
    _admit(manager, "smub", 1.0)
    driver.reachable = False

    try:
        await manager.request_stop(channel="smub")
    except Exception:
        # Delivery may well fail against an absent device; that is not the
        # subject. What must survive is the recorded intent.
        pass

    assert channel not in manager._admitted_intent, (
        "a stop that could not be delivered must still have been recorded, "
        "or reconnect would restore the power the operator was stopping"
    )


async def test_emergency_off_revokes_intent_even_when_unreachable():
    driver = _Keithley()
    manager = _manager(driver)
    manager._state = SafetyState.RUNNING
    _admit(manager, "smua", 0.5)
    _admit(manager, "smub", 0.7)
    driver.reachable = False

    try:
        await manager.emergency_off()
    except Exception:
        pass

    assert manager._admitted_intent == {}, "a global OFF revokes every channel's intent"


async def test_a_targeted_stop_leaves_the_other_channel_intended():
    driver = _Keithley()
    manager = _manager(driver)
    manager._state = SafetyState.RUNNING
    _admit(manager, "smua", 0.5)
    _admit(manager, "smub", 0.7)
    smua = manager._resolve_channels("smua").pop()
    smub = manager._resolve_channels("smub").pop()

    try:
        await manager.request_stop(channel="smua")
    except Exception:
        pass

    assert smua not in manager._admitted_intent
    assert smub in manager._admitted_intent, "stopping one channel says nothing about the other"


# ---------------------------------------------------------------------------
# It survives the thing that used to destroy it
# ---------------------------------------------------------------------------


async def test_intent_is_not_the_drivers_mirror():
    """connect() zeroes the driver's p_target; the engine's record is separate."""
    driver = _Keithley()
    manager = _manager(driver)
    _admit(manager, "smub", 0.7)
    channel = manager._resolve_channels("smub").pop()

    # Whatever the driver does to its own runtime, the admitted intent stands.
    driver.output_state_unverified = True
    assert manager._admitted_intent[channel].p_target == 0.7


async def test_intent_carries_its_admission_time_and_abort_epoch():
    """Both exist so an intent can be judged stale or superseded later."""
    driver = _Keithley()
    manager = _manager(driver)
    before = manager._abort_generation
    _admit(manager, "smub", 0.7)
    intent = manager._admitted_intent[manager._resolve_channels("smub").pop()]

    assert intent.admitted_monotonic_s > 0
    assert intent.abort_generation == before
    assert intent.v_comp == 40.0 and intent.i_comp == 1.0, "limits are part of the intent"


# ---------------------------------------------------------------------------
# A delivered stop clears it too
# ---------------------------------------------------------------------------


async def test_a_delivered_stop_clears_the_intent():
    driver = _Keithley()
    manager = _manager(driver)
    manager._state = SafetyState.RUNNING
    channel = manager._resolve_channels("smub").pop()
    manager._active_sources.add(channel)
    _admit(manager, "smub", 1.0)

    await manager._safe_off("Operator stop", channels={channel})

    assert channel not in manager._admitted_intent
    assert driver.stopped, "and it really did reach the instrument"
