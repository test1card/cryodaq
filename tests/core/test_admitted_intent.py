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


# ---------------------------------------------------------------------------
# Restoring it after a reconnect
# ---------------------------------------------------------------------------


async def test_the_intended_output_is_restored_after_a_reconnect():
    """A cable trip mid-sweep must not end the run.

    connect() leads with a forced OFF and zeroes the driver's p_target, so a
    reconnect used to recover the link and throw away the run. The intent is
    re-issued through request_run, which is the same admission an operator
    Start goes through.
    """
    driver = _Keithley()
    manager = _manager(driver)
    _admit(manager, "smub", 0.7)
    issued: list[tuple[float, float, float, str]] = []

    async def _capture(p, v, i, *, channel=None, **kwargs):
        issued.append((p, v, i, channel))
        return {"ok": True}

    manager.request_run = _capture  # type: ignore[method-assign]
    manager._mock = False

    await manager._resume_admitted_intent()

    assert issued == [(0.7, 40.0, 1.0, "smub")], "the setpoint AND its limits are restored"


async def test_a_stale_intent_is_not_restored():
    """A setpoint from another sitting must not re-energize a cryostat."""
    import time

    from cryodaq.core.safety_manager import _INTENT_RESUME_MAX_AGE_S, _AdmittedIntent

    driver = _Keithley()
    manager = _manager(driver)
    channel = manager._resolve_channels("smub").pop()
    manager._admitted_intent[channel] = _AdmittedIntent(
        p_target=0.7,
        v_comp=40.0,
        i_comp=1.0,
        admitted_monotonic_s=time.monotonic() - (_INTENT_RESUME_MAX_AGE_S + 60),
        abort_generation=manager._abort_generation,
    )
    issued: list = []

    async def _capture(*args, **kwargs):
        issued.append(args)
        return {"ok": True}

    manager.request_run = _capture  # type: ignore[method-assign]
    manager._mock = False

    await manager._resume_admitted_intent()

    assert issued == [], "an intent older than the bound is not restored"
    assert channel not in manager._admitted_intent, "and it is discarded, not left to age further"


async def test_a_refused_resume_leaves_the_source_off():
    """Minutes passed blind; an interlock may have arisen. Refusal is fail-closed."""
    driver = _Keithley()
    manager = _manager(driver)
    _admit(manager, "smub", 0.7)

    async def _refuse(*args, **kwargs):
        return {"ok": False, "error": "Interlock latched"}

    manager.request_run = _refuse  # type: ignore[method-assign]
    manager._mock = False

    await manager._resume_admitted_intent()

    assert manager._active_sources == set(), "a refused resume does not energize anything"


async def test_a_revoked_intent_is_never_restored():
    """The whole point of recording a link-less Stop."""
    driver = _Keithley()
    manager = _manager(driver)
    manager._state = SafetyState.RUNNING
    _admit(manager, "smub", 0.7)
    driver.reachable = False
    issued: list = []

    async def _capture(*args, **kwargs):
        issued.append(args)
        return {"ok": True}

    try:
        await manager.request_stop(channel="smub")
    except Exception:
        pass

    manager.request_run = _capture  # type: ignore[method-assign]
    manager._mock = False
    await manager._resume_admitted_intent()

    assert issued == [], (
        "the operator stopped it while the cable was out; reconnect must not "
        "restore the power they were stopping"
    )


async def test_an_already_active_channel_is_not_restarted():
    driver = _Keithley()
    manager = _manager(driver)
    channel = manager._resolve_channels("smub").pop()
    _admit(manager, "smub", 0.7)
    manager._active_sources.add(channel)
    issued: list = []

    async def _capture(*args, **kwargs):
        issued.append(args)
        return {"ok": True}

    manager.request_run = _capture  # type: ignore[method-assign]
    manager._mock = False

    await manager._resume_admitted_intent()

    assert issued == []


# ---------------------------------------------------------------------------
# Reviewer P1: Stop must win a race with a queued resume
# ---------------------------------------------------------------------------


async def test_a_stop_landing_mid_resume_prevents_the_source_coming_back_on():
    """Deterministic: pause the resume after it reads intent, Stop, then release.

    _resume_admitted_intent reads the intent, then awaits. A Stop arriving in
    that window revokes the intent and advances the abort epoch, but the value
    already read still described a live output. Restoring it would turn the
    source back on AFTER the operator pressed Stop, which is the worst thing
    this feature could do.
    """
    driver = _Keithley()
    manager = _manager(driver)
    manager._state = SafetyState.RUNNING
    channel = manager._resolve_channels("smub").pop()
    _admit(manager, "smub", 0.7)
    issued: list = []
    released = __import__("asyncio").Event()
    reached = __import__("asyncio").Event()

    async def _slow_request_run(*args, **kwargs):
        issued.append((args, kwargs))
        return {"ok": True}

    manager.request_run = _slow_request_run  # type: ignore[method-assign]
    manager._mock = False

    original_get = manager._admitted_intent.get

    async def _resume_with_pause():
        # Stand in for the await inside the loop: the Stop lands here.
        reached.set()
        await released.wait()
        await manager._resume_admitted_intent()

    import asyncio

    task = asyncio.create_task(_resume_with_pause())
    await reached.wait()
    try:
        await manager.request_stop(channel="smub")
    except Exception:
        pass
    released.set()
    await task

    assert channel not in manager._admitted_intent
    assert issued == [], "a Stop must make a queued resume permanently stale"


async def test_a_revoked_intent_is_not_restored_even_if_a_snapshot_held_it():
    """The loop re-reads the live intent before issuing, not its own snapshot."""
    driver = _Keithley()
    manager = _manager(driver)
    channel = manager._resolve_channels("smub").pop()
    _admit(manager, "smub", 0.7)
    issued: list = []

    async def _capture(*args, **kwargs):
        issued.append(args)
        return {"ok": True}

    manager.request_run = _capture  # type: ignore[method-assign]
    manager._mock = False
    # Revoke between the snapshot and the issue, exactly as a Stop would.
    original = manager._resume_admitted_intent

    manager._admitted_intent.pop(channel)
    await original()

    assert issued == []


async def test_the_resume_pins_the_epoch_its_intent_was_admitted_under():
    driver = _Keithley()
    manager = _manager(driver)
    _admit(manager, "smub", 0.7)
    intent = manager._admitted_intent[manager._resolve_channels("smub").pop()]
    seen: list = []

    async def _capture(*args, **kwargs):
        seen.append(kwargs.get("_expected_abort_generation"))
        return {"ok": True}

    manager.request_run = _capture  # type: ignore[method-assign]
    manager._mock = False

    await manager._resume_admitted_intent()

    assert seen == [intent.abort_generation], (
        "an abort landing while the command is queued must invalidate it at the existing cuts"
    )


# ---------------------------------------------------------------------------
# Reviewer P1: reconnect must restore the CURRENT step, not the first
# ---------------------------------------------------------------------------


async def test_a_confirmed_target_update_becomes_the_resumable_intent():
    """start at P1 -> update to P2 -> reconnect restores P2, never P1."""
    driver = _Keithley()
    manager = _manager(driver)
    channel = manager._resolve_channels("smub").pop()
    _admit(manager, "smub", 0.010)          # P1, as request_run records it
    assert manager._admitted_intent[channel].p_target == 0.010

    # What a confirmed update_target does to the record.
    from cryodaq.core.safety_manager import _AdmittedIntent
    import time as _t

    previous = manager._admitted_intent[channel]
    manager._admitted_intent[channel] = _AdmittedIntent(
        p_target=0.020,
        v_comp=previous.v_comp,
        i_comp=previous.i_comp,
        admitted_monotonic_s=_t.monotonic(),
        abort_generation=manager._abort_generation,
    )

    issued: list = []

    async def _capture(p, v, i, **kwargs):
        issued.append(p)
        return {"ok": True}

    manager.request_run = _capture  # type: ignore[method-assign]
    manager._mock = False
    await manager._resume_admitted_intent()

    assert issued == [0.020], "restoring P1 while the sweep is at P2 applies a power nobody asked for"


async def test_the_update_keeps_the_limits_from_the_start():
    """A step change is a power change; the compliance limits are not re-asked."""
    driver = _Keithley()
    manager = _manager(driver)
    channel = manager._resolve_channels("smub").pop()
    _admit(manager, "smub", 0.010)
    before = manager._admitted_intent[channel]

    from cryodaq.core.safety_manager import _AdmittedIntent
    import time as _t

    manager._admitted_intent[channel] = _AdmittedIntent(
        p_target=0.020,
        v_comp=before.v_comp,
        i_comp=before.i_comp,
        admitted_monotonic_s=_t.monotonic(),
        abort_generation=manager._abort_generation,
    )

    assert manager._admitted_intent[channel].v_comp == before.v_comp
    assert manager._admitted_intent[channel].i_comp == before.i_comp


async def test_the_real_update_target_records_the_new_intent():
    """Drive the production path, not a stand-in for it."""

    class _Runtime:
        def __init__(self) -> None:
            self.active = True
            self.p_target = 0.010

    class _Source(_Keithley):
        def __init__(self) -> None:
            super().__init__()
            self._channels = {"smua": _Runtime(), "smub": _Runtime()}
            self.updated: list = []

        async def update_source_target(self, smu_channel, p_target):
            self.updated.append((str(smu_channel), p_target))
            self._channels[str(smu_channel)].p_target = p_target

    driver = _Source()
    manager = _manager(driver)
    manager._state = SafetyState.RUNNING
    channel = manager._resolve_channels("smub").pop()
    manager._active_sources.add(channel)
    _admit(manager, "smub", 0.010)

    result = await manager.update_target(0.020, channel="smub")

    assert result.get("ok") is True, result
    assert driver.updated == [("smub", 0.020)]
    assert manager._admitted_intent[channel].p_target == 0.020, (
        "a confirmed step change must become the intent a reconnect would restore"
    )


async def test_a_refused_target_update_leaves_the_last_confirmed_intent():
    driver = _Keithley()          # no _channels: the update cannot reach the instrument
    manager = _manager(driver)
    manager._state = SafetyState.RUNNING
    channel = manager._resolve_channels("smub").pop()
    manager._active_sources.add(channel)
    _admit(manager, "smub", 0.010)

    try:
        result = await manager.update_target(0.020, channel="smub")
        assert result.get("ok") is not True
    except Exception:
        pass

    assert manager._admitted_intent[channel].p_target == 0.010, (
        "an update that did not reach the source must not replace the intent"
    )
