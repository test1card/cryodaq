"""The cable is pulled while the source is connected and idle, then put back.

Run on real hardware 2026-09-02 14:24, everything unplugged at once and
replugged ~2 minutes later. The three LakeShores on GPIB and the Thyracont on
serial all recovered by themselves. The Keithley did not:

    state        : fault_latched
    fault_reason : reviewed source disconnect lacked verified OFF (standalone read error)
    keithley_connected : False, sample count frozen

    Keithley_1: SAFETY: emergency_off command failed on smua
                (smua.source.levelv = 0): USBTMC write failed in bounded worker
    Keithley_1: SAFETY: emergency_off OFF readback failed on smua:
                USBTMC query failed in bounded worker

ab390a72 released a failed CONNECT (engine started with the device already
absent: nothing was ever opened, so the driver was ``connected = False``). This
is the other transition and it is not the same one. The read path reaches
``disconnect_reviewed_source`` through
``scheduler._settle_reviewed_read_uncertainty`` with the driver still marked
connected -- disconnect is what would clear it -- so a predicate keyed on
``connected is False`` never fires.

The owner's correction is the design point:

    "it just means it is connected, it doesnt mean that power gets there"

``connected`` is a COMMUNICATION fact. Whether the SMU is delivering power is a
different fact -- active sources, and whether current-generation OFF proof was
held. The release must ask the second question, not the first.

The hot case is not an exception to this, it is the strongest instance of it.
A channel that was sourcing when the cable went is STILL sourcing; the 2604B
holds its output across a controller-side disconnection. Neither disconnection
mode lets the software stop it: the panel refuses to send Stop without a live
link ("Останов нельзя отправить без живой связи"), and when only the instrument
cable is out the engine's stop_source() fails against an absent device and
latches fail-closed. So a tripped cable mid-sweep leaves a heater running that
CryoDAQ cannot stop -- and reconnecting is the ONLY software path back to being
able to stop it. Refusing to retry is what makes that permanent.

Releasing the attempt is not the same as granting RUN authority: no OFF
evidence is minted here, so energizing stays refused until a real connect
proves the state.
"""

from __future__ import annotations

import pytest

from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager, SafetyShutdownUnverifiedError, SafetyState
from cryodaq.drivers import registry as driver_registry
from cryodaq.drivers.base import InstrumentDriver, Reading
from cryodaq.drivers.contracts import (
    AcquisitionTiming,
    DriverTrustClass,
    SourceOffResult,
    _issue_registry_runtime_binding,
)


class _VanishingSource(InstrumentDriver):
    """Models the REAL demotion the driver performs on a transport loss.

    My first draft of this fake kept ``_connected = True`` through the unplug
    and never modelled the retained handle. That was wrong, and the hardware
    log says so:

        14:24:32  Keithley_1: SAFETY: query lost transport authority;
                  retaining the existing handle only for OFF recovery and close

    ``_enter_recovery_after_transport_loss`` sets ``_connected = False`` AND
    ``_recovery_transport_open = True`` before the exception reaches the
    scheduler. So the release predicate did not fail on ``connected``; it failed
    on the retained handle. A fake that gets this wrong lets a fix pass green
    and fail on the bench -- which is exactly what happened twice.
    """

    def __init__(self) -> None:
        super().__init__("reviewed", mock=True)
        self.cable_present = True
        self.device_answers = True
        self.connect_attempts = 0
        self.settle_calls = 0
        self.close_fails = False
        self._connected = True
        self.recovery_transport_open = False
        self.recovery_off_transport_dead = False
        self.teardown_incomplete = False

    def _demote(self) -> None:
        """What _enter_recovery_after_transport_loss does."""
        if not self._connected:
            return
        self._connected = False
        self.recovery_transport_open = True

    async def connect(self) -> None:
        self.connect_attempts += 1
        if self.recovery_transport_open:
            raise RuntimeError("recovery transport remains open; settle it before reconnect")
        if not self.cable_present:
            raise OSError("USBTMC: resource open failed")
        self._connected = True

    async def disconnect(self) -> None:
        if not self.cable_present:
            raise RuntimeError("recovery close refused until emergency_off verifies both outputs")
        self._connected = False

    async def read_channels(self) -> list[Reading]:
        if not self.cable_present:
            self._demote()
            raise OSError("USBTMC query failed in bounded worker")
        return []

    async def emergency_off(self, channel: str | None = None) -> SourceOffResult:
        del channel
        if not self.cable_present:
            self._demote()
            # The readback raised rather than answering: nothing is there.
            self.recovery_off_transport_dead = True
            return SourceOffResult.PHYSICAL_STATE_UNKNOWN
        if not self.device_answers:
            return SourceOffResult.PHYSICAL_STATE_UNKNOWN
        # It answered, so the handle is not buriable.
        self.recovery_off_transport_dead = False
        return SourceOffResult.DEVICE_REPORTED_OFF

    async def settle_unreachable(self) -> bool:
        self.settle_calls += 1
        if not self.recovery_transport_open or self._connected:
            return False
        if self.teardown_incomplete:
            return False
        if not self.recovery_off_transport_dead:
            return False
        if self.close_fails:
            self.teardown_incomplete = True
            return False
        self.recovery_transport_open = False
        self.recovery_off_transport_dead = False
        return True

    async def start_source(self, *_args, **_kwargs) -> None:
        return None

    async def stop_source(self, _channel: str) -> None:
        return None

    @property
    def output_state_unverified(self) -> bool:
        return True

    @property
    def unreachable_idle(self) -> bool:
        return (
            not self._connected
            and not self.recovery_transport_open
            and not self.teardown_incomplete
        )


def _bind(driver: InstrumentDriver):
    binding = _issue_registry_runtime_binding(
        driver=driver,
        timing=AcquisitionTiming(0.5, 0.5, 0.05),
        registry_provenance="test:reviewed-source-unplug",
        trust_class=DriverTrustClass.REVIEWED_SOURCE,
    )
    with driver_registry._RUNTIME_BINDINGS_LOCK:
        driver_registry._RUNTIME_BINDINGS[driver] = binding
    return binding


def _manager(driver: InstrumentDriver, binding):
    return SafetyManager(
        SafetyBroker(),
        keithley_driver=driver,
        reviewed_source_runtime_binding=binding,
        mock=False,
    )


# ---------------------------------------------------------------------------
# Idle when the cable went: releasing is the only route back to the instrument
# ---------------------------------------------------------------------------


async def test_an_unplug_while_idle_releases_instead_of_latching():
    driver = _VanishingSource()
    binding = _bind(driver)
    manager = _manager(driver, binding)
    # Idle: nothing was sourcing, and OFF was proven while the cable was in.
    manager._active_sources.clear()
    manager._reviewed_source_off_proven = True

    driver.cable_present = False
    released = await manager.disconnect_reviewed_source(driver, binding, None, "standalone read error")

    assert released is True, (
        "an idle source whose cable was pulled must settle so the poll loop can retry; "
        "refusing guarantees the engine can never reach that instrument again"
    )
    assert manager.state is not SafetyState.FAULT_LATCHED


async def test_the_release_leaves_the_output_state_unknown():
    driver = _VanishingSource()
    binding = _bind(driver)
    manager = _manager(driver, binding)
    manager._active_sources.clear()
    manager._reviewed_source_off_proven = True

    driver.cable_present = False
    await manager.disconnect_reviewed_source(driver, binding, None, "standalone read error")

    assert manager._reviewed_source_off_evidence.verified_off is False
    assert manager._reviewed_source_connected is False
    ok, _reason = manager._check_preconditions()
    assert not ok, "RUN must stay refused while the instrument is unreachable"


# ---------------------------------------------------------------------------
# Sourcing when the cable went: it is STILL sourcing, so we must get back to it
# ---------------------------------------------------------------------------
#
# I first wrote these two as "must keep latching", reasoning that an output
# which may be hot is the dangerous case. The owner overruled it with the
# better argument, and it is the same inversion as the cold case taken one step
# further:
#
#   "if power was on, it MUST connect, because power was not stopped. it must
#    connect and take over the process, continue giving power on the plan"
#
# The 2604B holds its output across a controller-side disconnection. A channel
# that was sourcing when the cable was pulled IS STILL SOURCING, whether or not
# the software reconnects. Latching does not de-energize it; it only means an
# energized heater on a cryostat that we can neither observe nor command.
# Reconnecting is the only way to regain both.
#
# Releasing the attempt is NOT the same as granting RUN authority: no OFF
# evidence is minted here, so energizing stays refused until a real connect
# proves the state. What the connect then does with a live output is the
# separate take-over contract -- adopt it only if the readback matches what the
# engine last commanded and still intends, otherwise force OFF.


async def test_an_unplug_while_sourcing_also_releases_so_it_can_reconnect():
    driver = _VanishingSource()
    binding = _bind(driver)
    manager = _manager(driver, binding)
    manager._active_sources.add("smua")
    manager._reviewed_source_off_proven = False

    driver.cable_present = False
    released = await manager.disconnect_reviewed_source(driver, binding, None, "standalone read error")

    assert released is True, (
        "the output is still hot whether or not we reconnect; refusing to retry "
        "leaves an energized heater we can neither see nor stop"
    )


async def test_releasing_a_hot_source_still_grants_no_run_authority():
    """Getting back to the instrument is not the same as being allowed to drive it."""
    driver = _VanishingSource()
    binding = _bind(driver)
    manager = _manager(driver, binding)
    manager._active_sources.add("smua")
    manager._reviewed_source_off_proven = False

    driver.cable_present = False
    await manager.disconnect_reviewed_source(driver, binding, None, "standalone read error")

    assert manager._reviewed_source_off_evidence.verified_off is False
    ok, _reason = manager._check_preconditions()
    assert not ok, "RUN stays refused until a real connect proves the output state"


# ---------------------------------------------------------------------------
# And the cable comes back
# ---------------------------------------------------------------------------


async def test_the_instrument_is_reachable_again_after_the_cable_returns():
    driver = _VanishingSource()
    binding = _bind(driver)
    manager = _manager(driver, binding)
    manager._active_sources.clear()
    manager._reviewed_source_off_proven = True

    driver.cable_present = False
    assert await manager.disconnect_reviewed_source(driver, binding, None, "standalone read error") is True
    assert driver.connected is False, "the dead handle must be settled, not retained"

    # The operator plugs it back in.
    driver.cable_present = True
    await driver.connect()
    assert driver.connected is True
    assert driver.connect_attempts == 1


# ---------------------------------------------------------------------------
# The handle may be buried ONLY when the device did not answer
# ---------------------------------------------------------------------------


async def test_a_device_that_answers_but_will_not_go_off_is_not_released():
    """Reachable and refusing is a hardware fault, not a missing cable.

    The distinction is the whole safety content of settle_unreachable: an OFF
    readback that RAISES means nothing is on the far side of the handle; one
    that ANSWERS -- even to say the output is still on -- means there is. Only
    the first may have its handle buried. Burying the second would discard a
    live session to an instrument that is refusing to de-energize.
    """
    driver = _VanishingSource()
    binding = _bind(driver)
    manager = _manager(driver, binding)
    # Cable is in, so the readback answers; the device just will not confirm OFF.
    driver.cable_present = True
    driver.device_answers = False
    driver._demote()

    released = await manager.disconnect_reviewed_source(driver, binding, None, "standalone read error")

    assert released is False
    assert driver.recovery_transport_open is True, "a live session must not be discarded"
    assert manager.state is SafetyState.FAULT_LATCHED


async def test_a_close_that_fails_does_not_release():
    driver = _VanishingSource()
    binding = _bind(driver)
    manager = _manager(driver, binding)
    driver.cable_present = False
    driver.close_fails = True

    released = await manager.disconnect_reviewed_source(driver, binding, None, "standalone read error")

    assert released is False
    assert driver.teardown_incomplete is True
    assert manager.state is SafetyState.FAULT_LATCHED


async def test_burying_the_handle_mints_no_off_evidence():
    driver = _VanishingSource()
    binding = _bind(driver)
    manager = _manager(driver, binding)
    driver.cable_present = False

    assert await manager.disconnect_reviewed_source(driver, binding, None, "standalone read error") is True

    assert driver.unreachable_idle is True
    assert manager._reviewed_source_off_evidence.verified_off is False, (
        "closing a handle tells us nothing about the output"
    )
    ok, _reason = manager._check_preconditions()
    assert not ok, "energizing stays refused until a real connect proves the state"


async def test_the_settled_driver_can_open_a_fresh_session():
    """The retained handle is what blocked reconnect; burying it unblocks."""
    driver = _VanishingSource()
    binding = _bind(driver)
    manager = _manager(driver, binding)
    driver.cable_present = False

    await manager.disconnect_reviewed_source(driver, binding, None, "standalone read error")
    # Before the settle, connect() refuses: "recovery transport remains open".
    assert driver.recovery_transport_open is False

    driver.cable_present = True
    await driver.connect()
    assert driver.connected is True


# ---------------------------------------------------------------------------
# Shutdown must not hold for a proof that can never arrive
# ---------------------------------------------------------------------------


async def test_shutdown_completes_when_the_source_is_unreachable():
    """Holding is only right while holding can still accomplish something.

    The HOLD exists so a process that may still be able to de-energize a source
    cannot walk away from it. When the instrument is physically gone that
    inverts: the proof is unobtainable however long we wait, the engine ignores
    SIGTERM, and the operator must SIGKILL -- the uncontrolled exit the
    transport's PDEATHSIG design exists to avoid. That happened four times on
    2026-09-02, and once in a plain standalone run:

        SafetyManager shutdown HOLD: global OFF could not be verified
        Keithley_1: SAFETY: emergency_off OFF readback failed on smua:
                    USBTMC has no live process-owned session
    """
    driver = _VanishingSource()
    binding = _bind(driver)
    manager = _manager(driver, binding)
    await manager.start()
    driver.cable_present = False

    # Must not raise SafetyShutdownUnverifiedError.
    await manager.stop()


async def test_shutdown_still_holds_while_a_live_handle_is_retained():
    """A device that answers can still be acted on, so the hold stands."""
    driver = _VanishingSource()
    binding = _bind(driver)
    manager = _manager(driver, binding)
    await manager.start()
    # Cable is in and the device answers, but it will not confirm OFF.
    driver.device_answers = False
    driver._demote()

    with pytest.raises(SafetyShutdownUnverifiedError):
        await manager.stop()
