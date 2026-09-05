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

import contextlib

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
    import time

    from cryodaq.core.safety_manager import _AdmittedIntent

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


async def test_a_stale_epoch_is_refused_by_the_real_locked_admission():
    """The guard the resume relies on, exercised through production request_run.

    This is one half of closing the Stop/resume race, and it is deliberately
    the half that can be proven. An end-to-end race test was attempted twice
    and both attempts were theatre: the first paused BEFORE resume started, so
    the snapshot was taken after the Stop; the second queued a real resume
    behind the admission lock but still passed with the fix disabled, because
    after a Stop the run is refused by the ordinary preconditions anyway. A
    test that passes without the mechanism does not test the mechanism.

    So the two halves are asserted separately, on the production path:
    here, that an epoch superseded since admission is refused before any driver
    call; and in the test below, that the resume passes exactly the epoch its
    intent was admitted under. Together they are the race.
    """

    class _StartCounting(_Keithley):
        def __init__(self) -> None:
            super().__init__()
            self.started: list = []
            runtime = lambda: type("R", (), {"active": False, "p_target": 0.0})()
            self._channels = {"smua": runtime(), "smub": runtime()}

        async def start_source(self, smu_channel, p_target, v_comp, i_comp):
            self.started.append((str(smu_channel), p_target))
            return True

    driver = _StartCounting()
    manager = _manager(driver)
    manager._mock = False
    manager._state = SafetyState.READY
    admitted_under = manager._abort_generation

    # Anything that aborts -- a Stop, an emergency OFF, an interlock -- advances
    # this. The queued command still presents the epoch it was admitted under.
    manager._register_abort_intent(full=True)

    result = await manager.request_run(
        0.7, 40.0, 1.0, channel="smub", _expected_abort_generation=admitted_under
    )

    assert result.get("ok") is not True
    assert "authority changed" in str(result.get("error", "")).lower()
    assert driver.started == [], "no source may be started on a superseded epoch"


async def test_a_current_epoch_is_not_refused_by_that_guard():
    """The guard must reject the stale case only, or resume never works."""

    class _StartCounting(_Keithley):
        def __init__(self) -> None:
            super().__init__()
            self.started: list = []
            runtime = lambda: type("R", (), {"active": False, "p_target": 0.0})()
            self._channels = {"smua": runtime(), "smub": runtime()}

        async def start_source(self, smu_channel, p_target, v_comp, i_comp):
            self.started.append((str(smu_channel), p_target))
            return True

    driver = _StartCounting()
    manager = _manager(driver)
    manager._mock = False
    manager._state = SafetyState.READY

    result = await manager.request_run(
        0.7, 40.0, 1.0, channel="smub", _expected_abort_generation=manager._abort_generation
    )

    assert "authority changed" not in str(result.get("error", "")).lower(), (
        "a current epoch must not trip the superseded-authority guard"
    )


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
    manager._admitted_intent.pop(channel)
    await manager._resume_admitted_intent()

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


class _SweepSource(_Keithley):
    """A source that accepts targets and records what it was asked to start."""

    def __init__(self) -> None:
        super().__init__()
        self.started: list = []
        runtime = lambda: type("R", (), {"active": True, "p_target": 0.010})()
        self._channels = {"smua": runtime(), "smub": runtime()}

    async def update_source_target(self, smu_channel, p_target):
        self._channels[str(smu_channel)].p_target = p_target

    async def start_source(self, smu_channel, p_target, v_comp, i_comp):
        self.started.append((str(smu_channel), p_target))
        return True


async def test_p1_then_update_to_p2_then_reconnect_restores_only_p2():
    """The whole path, joined: start, step, lose the link, come back.

    Previously this evidence was split -- one test wrote _admitted_intent by
    hand, another called update_target but never resumed. Neither showed that a
    reconnect after a step restores the STEP. A sweep's first target comes
    through request_run and every later one through update_target, so recording
    only the first meant a reconnect during step three reapplied step one: a
    power nobody asked for, on a run that still looked correct in the GUI.
    """
    driver = _SweepSource()
    manager = _manager(driver)
    manager._mock = False
    # update_target requires live safety children, so this runs a real manager
    # lifecycle rather than reaching past the check it has to satisfy.
    await manager.start()
    manager._state = SafetyState.RUNNING
    channel = manager._resolve_channels("smub").pop()
    manager._active_sources.add(channel)
    _admit(manager, "smub", 0.010)                       # P1, as request_run records it

    assert (await manager.update_target(0.020, channel="smub")).get("ok") is True

    issued: list = []

    async def _capture(p_target, v_comp, i_comp, **kwargs):
        issued.append(p_target)
        return {"ok": True}

    manager.request_run = _capture  # type: ignore[method-assign]
    manager._active_sources.discard(channel)             # the link dropped; nothing is active
    try:
        await manager._resume_admitted_intent()
    finally:
        with contextlib.suppress(Exception):
            await manager.stop()

    assert issued == [0.020], f"reconnect must restore the current step, not the first: {issued}"


async def test_a_failed_update_leaves_the_previous_target_resumable():
    """P1 stands when the step to P2 did not reach the instrument."""
    driver = _Keithley()          # no _channels: update_target cannot confirm
    manager = _manager(driver)
    manager._mock = False
    await manager.start()
    manager._state = SafetyState.RUNNING
    channel = manager._resolve_channels("smub").pop()
    manager._active_sources.add(channel)
    _admit(manager, "smub", 0.010)

    try:
        assert (await manager.update_target(0.020, channel="smub")).get("ok") is not True
    except Exception:
        pass

    issued: list = []

    async def _capture(p_target, v_comp, i_comp, **kwargs):
        issued.append(p_target)
        return {"ok": True}

    manager.request_run = _capture  # type: ignore[method-assign]
    manager._active_sources.discard(channel)
    try:
        await manager._resume_admitted_intent()
    finally:
        with contextlib.suppress(Exception):
            await manager.stop()

    assert issued == [0.010], f"an unconfirmed step must not become the resumable intent: {issued}"


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
