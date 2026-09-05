"""The signed laboratory-qualification gate is gone, and nothing replaced it.

Removed on the owner's ruling of 2026-09-04. The gate demanded an RSA-signed
receipt before the source could be energised, and no such receipt could ever be
obtained on this stand: only the public modulus ships, there is no private key
in the tree, and the issuer does not exist. `start.sh` therefore exported
CRYODAQ_LAB_QUALIFICATION_OVERRIDE=1 unconditionally, and every boot logged two
CRITICALs about a certificate that cannot exist.

These tests pin the two halves of a removal that must not become anything else.

The first half is that it took effect: a non-mock manager, connected and bound
to a real-reporting driver, energizes without a receipt. On its own that could
be satisfied by a manager which now admits everything, so the second half pins
the other direction — the guards the gate sat in front of still refuse, by their
own names, and the de-energizing path was never gated at all.

Scope, stated because review of 2026-09-05 found the earlier wording overstated
it: the driver here is a MagicMock that REPORTS itself real. These tests
exercise the manager's admission logic against a double, not a Keithley, and no
part of this suite touches laboratory hardware. Nothing below is evidence about
how the physical stack behaves.

An earlier draft also added a refusal for "a mock-flagged manager must not
energize a REAL source", believing the gate had enforced it incidentally. It had
not: with the override exported unconditionally, an absent receipt returned None
and the mismatch was admitted on every production run. That refusal was
therefore a NEW veto rather than a preserved protection, it broke five
limit-write regressions that deliberately drive a real-reporting double from a
mock manager, and it is not part of this change. Whether the mismatch should be
refused is left open for the owner, in its own reviewed commit.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager
from cryodaq.drivers.contracts import (
    AcquisitionTiming,
    DriverTrustClass,
    SourceOffResult,
    _issue_registry_runtime_binding,
)

pytestmark = pytest.mark.asyncio


def _driver(*, simulated: bool) -> MagicMock:
    driver = MagicMock()
    driver.mock = simulated
    driver.connected = True
    driver.output_state_unverified = False
    driver.watchdog_trip_pending = False
    driver.emergency_off = AsyncMock(return_value=SourceOffResult.DEVICE_REPORTED_OFF)
    driver.stop_source = AsyncMock()
    driver.update_source_limit = AsyncMock()
    runtime = SimpleNamespace(active=False, p_target=0.0, v_comp=40.0, i_comp=1.0)
    driver._channels = {"smua": runtime, "smub": SimpleNamespace(**vars(runtime))}

    async def start_source(channel: str, p_target: float, v_comp: float, i_comp: float) -> None:
        selected = driver._channels[channel]
        selected.active = True
        selected.p_target = p_target
        selected.v_comp = v_comp
        selected.i_comp = i_comp

    async def update_source_target(channel: str, p_target: float) -> None:
        driver._channels[channel].p_target = p_target

    driver.start_source = AsyncMock(side_effect=start_source)
    driver.update_source_target = AsyncMock(side_effect=update_source_target)
    return driver


async def _manager(*, driver_simulated: bool, manager_mock: bool) -> tuple[SafetyManager, MagicMock]:
    driver = _driver(simulated=driver_simulated)
    binding = _issue_registry_runtime_binding(
        driver=driver,
        timing=AcquisitionTiming(1.0, 1.0, 1.0),
        registry_provenance="test:qualification-gate-removed",
        trust_class=DriverTrustClass.REVIEWED_SOURCE,
        simulation=manager_mock and driver_simulated,
    )
    manager = SafetyManager(
        SafetyBroker(),
        keithley_driver=driver,
        reviewed_source_runtime_binding=binding,
        mock=manager_mock,
    )
    manager._config.critical_channels = []
    await manager.start()
    if not manager_mock:
        generation = await manager.begin_reviewed_source_connect(driver, binding, "gate-removal test")
        assert await manager.complete_reviewed_source_connect(driver, binding, generation, "gate-removal test")
    return manager, driver


async def test_a_connected_non_mock_manager_is_no_longer_refused_for_want_of_a_receipt() -> None:
    """The removal, asserted directly rather than inferred from silence."""

    manager, driver = await _manager(driver_simulated=False, manager_mock=False)
    try:
        result = await manager.request_run(0.1, 10.0, 0.1, channel="smua")
        assert result["ok"] is True, result.get("error")
        driver.start_source.assert_awaited_once()
    finally:
        await manager.stop()


async def test_a_simulated_stack_still_runs() -> None:
    """Simulation was never what the gate was about, and still is not."""

    manager, driver = await _manager(driver_simulated=True, manager_mock=True)
    try:
        result = await manager.request_run(0.1, 10.0, 0.1, channel="smua")
        assert result["ok"] is True, result.get("error")
        driver.start_source.assert_awaited_once()
    finally:
        await manager.stop()


# Preconditions with nothing to do with qualification, which must still refuse a
# connected, non-mock manager on a real-reporting driver double now that the
# receipt check is gone.
_INDEPENDENT_REFUSALS = (
    ("watchdog", "watchdog_trip_pending", True, "watchdog"),
    ("disconnected", "connected", False, "connected=False"),
)


@pytest.mark.parametrize(
    ("name", "attribute", "value", "expected"),
    _INDEPENDENT_REFUSALS,
    ids=[name for name, _, _, _ in _INDEPENDENT_REFUSALS],
)
async def test_the_removal_did_not_become_unconditional_permission(
    name: str, attribute: str, value: object, expected: str
) -> None:
    """The gate is gone; the guards it sat in front of are not.

    Without these, the removal test above would be equally satisfied by a
    manager that now admits everything.
    """

    manager, driver = await _manager(driver_simulated=False, manager_mock=False)
    try:
        setattr(driver, attribute, value)
        result = await manager.request_run(0.1, 10.0, 0.1, channel="smua")
        assert result["ok"] is False, f"{name}: RUN was admitted with the guard tripped"
        assert expected in result["error"], f"{name}: refused for the wrong reason: {result['error']}"
        driver.start_source.assert_not_awaited()
    finally:
        await manager.stop()


async def test_de_energizing_was_never_gated_and_still_is_not() -> None:
    """Refusing to energize must never refuse to de-energize.

    `request_stop` and `emergency_off` consult no energizing refusal at all.
    A stand that cannot be switched off is worse than one that cannot be
    switched on, so this stays pinned whatever happens on the RUN side.
    """

    manager, driver = await _manager(driver_simulated=False, manager_mock=False)
    try:
        manager._active_sources.add("smua")
        stopped = await manager.request_stop(channel="smua")
        assert stopped["ok"] is True, stopped.get("error")

        before = driver.emergency_off.await_count
        killed = await manager.emergency_off(channel=None)
        assert killed["ok"] is True, killed.get("error")
        assert driver.emergency_off.await_count > before, "emergency OFF never reached the driver"
    finally:
        await manager.stop()
