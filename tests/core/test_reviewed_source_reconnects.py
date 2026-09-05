"""A reviewed source that becomes reachable again must reconnect by itself.

2026-09-02 on lab53: the engine started while the Keithley 2604B was unplugged.

    10:50:09  Keithley_1: connecting to USB0::0x05E6::0x2604::4083236::0::INSTR
    10:50:10  USBTMC: resource open failed
    10:50:10  SAFETY: safe_off -> fault_latched
    10:50:10  Backoff 'Keithley_1': 1.0s

``Keithley_1: connecting to`` never appeared again. The operator plugged the
instrument in at 11:53 and the engine polled on for another hour reporting it
unreachable, ``'Keithley_1': 0`` in every heartbeat. Only a full restart
recovered it -- which fragments the record and costs the operator their plots.

The mechanism: ``_own_reviewed_connect`` sets ``driver_io_started`` before
``driver.connect()``, so a failed connect runs cleanup, which proves OFF through
``driver.emergency_off()``. With no transport open that returns
PHYSICAL_STATE_UNKNOWN without touching the hardware, so the cleanup is
UNSATISFIABLE. ``_adjudicate_reviewed_attempt`` then raises before the line that
clears ``state.reviewed_source_attempt``, and the poll loop re-adjudicates the
same dead attempt every backoff period forever.

Reviewed by fable, who inverted the safety argument: the latch is the more
dangerous behaviour, because retry is the engine's only path to de-energizing a
source that becomes reachable again. It fails inert, not closed.

What must stay true is pinned in test_reviewed_source_disconnect.py and in the
negative tests at the bottom of this file: a source that MAY have been energized
by us -- a transport retained for recovery, an unsettled teardown -- is not
released, and no release ever mints OFF evidence.
"""

from __future__ import annotations

import pytest

from cryodaq.core.broker import DataBroker
from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager, SafetyShutdownUnverifiedError, SafetyState
from cryodaq.core.scheduler import InstrumentConfig, Scheduler
from cryodaq.drivers import registry as driver_registry
from cryodaq.drivers.base import InstrumentDriver, Reading
from cryodaq.drivers.contracts import (
    AcquisitionTiming,
    DriverTrustClass,
    SourceOffResult,
    _issue_registry_runtime_binding,
)


class _AbsentThenPresentSource(InstrumentDriver):
    """A source whose transport cannot open until the cable is back."""

    def __init__(self, *, absent: bool = True) -> None:
        super().__init__("reviewed", mock=True)
        self.absent = absent
        self.connect_attempts = 0
        self.disconnect_calls = 0
        self._connected = False
        # Nothing is held and nothing is unresolved: the transport never opened.
        self.recovery_transport_open = False
        self.teardown_incomplete = False

    async def connect(self) -> None:
        self.connect_attempts += 1
        if self.absent:
            raise OSError("USBTMC: resource open failed")
        self._connected = True

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        self._connected = False

    async def read_channels(self) -> list[Reading]:
        return []

    async def emergency_off(self, channel: str | None = None) -> SourceOffResult:
        del channel
        if self.recovery_transport_open or self.teardown_incomplete:
            # A transport is retained for recovery precisely BECAUSE OFF could
            # not be proven; that is the lane that must keep latching.
            return SourceOffResult.PHYSICAL_STATE_UNKNOWN
        if not self._connected:
            # The real driver's behaviour: it never touches the transport, so
            # replugging the instrument is invisible to this call.
            return SourceOffResult.PHYSICAL_STATE_UNKNOWN
        return SourceOffResult.DEVICE_REPORTED_OFF

    async def start_source(self, *_args, **_kwargs) -> None:
        return None

    async def stop_source(self, _channel: str) -> None:
        return None

    @property
    def output_state_unverified(self) -> bool:
        return not self._connected

    @property
    def unreachable_idle(self) -> bool:
        """No handle held, nothing unresolved: this instance cannot influence the output."""
        return (
            not self._connected
            and not self.recovery_transport_open
            and not self.teardown_incomplete
        )


def _bind(driver: InstrumentDriver):
    binding = _issue_registry_runtime_binding(
        driver=driver,
        timing=AcquisitionTiming(0.5, 0.5, 0.05),
        registry_provenance="test:reviewed-source-reconnect",
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
# The incident
# ---------------------------------------------------------------------------


async def test_a_failed_connect_settles_so_the_next_one_can_happen():
    """The cleanup after an absent-device connect must be satisfiable.

    On master this returns False forever: emergency_off cannot prove OFF with no
    transport, so the attempt never settles and connect is never retried.
    """
    driver = _AbsentThenPresentSource(absent=True)
    binding = _bind(driver)
    manager = _manager(driver, binding)

    released = await manager.disconnect_reviewed_source(driver, binding, None, "failed connect cleanup")

    assert released is True, (
        "an unreachable, idle source must release its connect attempt; "
        "otherwise the poll loop re-adjudicates a dead attempt forever"
    )


async def test_releasing_does_not_mint_off_evidence():
    """Releasing says nothing about the physical output state."""
    driver = _AbsentThenPresentSource(absent=True)
    binding = _bind(driver)
    manager = _manager(driver, binding)

    await manager.disconnect_reviewed_source(driver, binding, None, "failed connect cleanup")

    assert manager._reviewed_source_off_evidence.verified_off is False, (
        "the device is unreachable; its output state is UNKNOWN, not OFF"
    )
    assert manager._reviewed_source_connected is False
    ok, reason = manager._check_preconditions()
    assert not ok, "RUN must stay refused while the source is unreachable"


async def test_releasing_does_not_latch_a_fault():
    """Device-absent-never-commanded is not a fault; it is the state before a first connect."""
    driver = _AbsentThenPresentSource(absent=True)
    binding = _bind(driver)
    manager = _manager(driver, binding)

    await manager.disconnect_reviewed_source(driver, binding, None, "failed connect cleanup")

    assert manager.state is not SafetyState.FAULT_LATCHED


async def test_a_pre_existing_fault_is_never_cleared_by_a_release():
    driver = _AbsentThenPresentSource(absent=True)
    binding = _bind(driver)
    manager = _manager(driver, binding)
    manager._state = SafetyState.FAULT_LATCHED

    await manager.disconnect_reviewed_source(driver, binding, None, "failed connect cleanup")

    assert manager.state is SafetyState.FAULT_LATCHED, "a release must not unlatch an existing fault"


# ---------------------------------------------------------------------------
# What must NOT be released -- the source may still be energized
# ---------------------------------------------------------------------------


async def test_a_retained_recovery_transport_is_not_released():
    """family-authorized transport held for OFF recovery: the output MAY be on."""
    driver = _AbsentThenPresentSource(absent=True)
    driver.recovery_transport_open = True
    binding = _bind(driver)
    manager = _manager(driver, binding)

    released = await manager.disconnect_reviewed_source(driver, binding, None, "retained for recovery")

    assert released is False
    assert manager.state is SafetyState.FAULT_LATCHED


async def test_an_unsettled_teardown_is_not_released():
    driver = _AbsentThenPresentSource(absent=True)
    driver.teardown_incomplete = True
    binding = _bind(driver)
    manager = _manager(driver, binding)

    released = await manager.disconnect_reviewed_source(driver, binding, None, "unsettled teardown")

    assert released is False
    assert manager.state is SafetyState.FAULT_LATCHED


async def test_a_connected_source_still_requires_a_real_off_proof():
    """Reachable means prove it, not assume it."""
    driver = _AbsentThenPresentSource(absent=False)
    await driver.connect()
    binding = _bind(driver)
    manager = _manager(driver, binding)

    released = await manager.disconnect_reviewed_source(driver, binding, None, "ordinary disconnect")

    assert released is True
    assert driver.disconnect_calls == 1, "the ordinary path must still disconnect the driver"


# ---------------------------------------------------------------------------
# End to end: the cable comes back and acquisition resumes without a relaunch
# ---------------------------------------------------------------------------


async def test_the_source_reconnects_when_the_cable_comes_back():
    driver = _AbsentThenPresentSource(absent=True)
    binding = _bind(driver)
    manager = _manager(driver, binding)

    scheduler = Scheduler(
        DataBroker(),
        reviewed_source_connect_begin=manager.begin_reviewed_source_connect,
        reviewed_source_connect_complete=manager.complete_reviewed_source_connect,
        reviewed_source_disconnect=manager.disconnect_reviewed_source,
        reviewed_source_uncertain=manager.mark_reviewed_source_uncertain,
        reviewed_source_connect_abandon=manager.abandon_reviewed_source_connect,
    )
    scheduler.add(InstrumentConfig(driver=driver, runtime_binding=binding))
    state = scheduler._instruments[driver.name]
    # begin_reviewed_source_connect refuses to issue a generation without live
    # safety children, so the manager must be running for this to reach the
    # driver at all.
    await manager.start()
    try:
        # First attempt: the instrument is absent.
        with pytest.raises(Exception):
            await scheduler._connect_driver(state, context="standalone connect")
        assert driver.connect_attempts == 1
        assert state.reviewed_source_attempt is None, (
            "a settled failure must leave no attempt behind; a retained one is never retried"
        )

        # The operator plugs the cable back in.
        driver.absent = False

        await scheduler._connect_driver(state, context="standalone connect")
        assert driver.connect_attempts == 2, "connect must be attempted again after the failure"
        assert driver.connected is True
    finally:
        # The shutdown HOLD is a SEPARATE open defect (a stop that cannot prove
        # OFF refuses to settle and, on the stand, forces a SIGKILL). It is not
        # what this test is about, and swallowing it here keeps the reconnect
        # assertions above from being masked by it.
        try:
            await manager.stop()
        except SafetyShutdownUnverifiedError:
            pass
