"""Bench smoke tests for the Keithley 2604B software late-pet watchdog.

These run against a REAL instrument at hardware setup and before every
overnight — they re-verify the firmware integrity checks that get no CI:

  * version stamp — the script is re-uploaded from repo ``tsp/`` on every arm;
    the host reads ``CRYODAQ_WDOG_VERSION`` back and refuses to arm on mismatch.
  * A8a upload/version — version 3 loads and explicitly reports
    ``cryodaq_wdog_autonomous == 0``.
  * verified-OFF readback — ``emergency_off`` confirms the outputs are OFF.
  * A8b late-pet recovery — stall past the deadline, send a later pet, and
    confirm both outputs turn OFF and the latch is set.

They SKIP gracefully with no hardware: set ``CRYODAQ_KEITHLEY_RESOURCE`` to the
VISA resource string to enable them. Any test that ENERGISES the source is
additionally gated on ``CRYODAQ_SMOKE_ALLOW_SOURCE=1`` and MUST only be run on a
macet (dummy) load at a safe low level — NEVER on the cryostat heater.

A8c (true host death with no later command), A8d (independently measured
terminal V/I/P and trip time), and A8e (external interlock/common-cause proof)
are separate manual hardware gates. These in-process tests cannot prove them.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from cryodaq.drivers.instruments.keithley_2604b import (
    _WDOG_SCRIPT_VERSION,
    Keithley2604B,
    WatchdogMode,
)

pytestmark = pytest.mark.smoke

_RESOURCE = os.environ.get("CRYODAQ_KEITHLEY_RESOURCE")
_ALLOW_SOURCE = os.environ.get("CRYODAQ_SMOKE_ALLOW_SOURCE") == "1"

requires_hw = pytest.mark.skipif(
    not _RESOURCE,
    reason="no live Keithley 2604B; set CRYODAQ_KEITHLEY_RESOURCE to enable",
)
requires_source = pytest.mark.skipif(
    not (_RESOURCE and _ALLOW_SOURCE),
    reason=(
        "sourcing smoke test disabled; set CRYODAQ_KEITHLEY_RESOURCE and "
        "CRYODAQ_SMOKE_ALLOW_SOURCE=1 (dummy load, safe low level ONLY)"
    ),
)

_TIMEOUT_S = 3.0


def _driver(mode: WatchdogMode = WatchdogMode.BEST_EFFORT) -> Keithley2604B:
    return Keithley2604B(
        "k2604_smoke",
        _RESOURCE or "USB0::UNSET",
        mock=False,
        watchdog_mode=mode,
        watchdog_timeout_s=_TIMEOUT_S,
    )


@requires_hw
async def test_a8a_smoke_version_and_non_autonomous_contract() -> None:
    """The uploaded script reports version 3 and no autonomous protection."""
    drv = _driver()
    await drv.connect()
    try:
        assert drv._wdog_armed is True
        assert drv._wdog_autonomous is False
        raw = await drv._transport.query("print(CRYODAQ_WDOG_VERSION)")
        assert int(float(raw.strip())) == _WDOG_SCRIPT_VERSION
        autonomous = await drv._transport.query("print(cryodaq_wdog_autonomous)")
        assert int(float(autonomous.strip())) == 0
    finally:
        await drv.disconnect()


@requires_hw
async def test_a8a_smoke_software_active_state_readback() -> None:
    """The late-pet checker is active, without implying an autonomous arm."""
    drv = _driver()
    await drv.connect()
    try:
        active = await drv._transport.query("print(cryodaq_wdog_active)")
        tripped = await drv._transport.query("print(cryodaq_wdog_tripped)")
        assert float(active.strip()) > 0.5
        assert float(tripped.strip()) < 0.5
    finally:
        await drv.disconnect()


@requires_hw
async def test_a8a_smoke_verified_off_readback() -> None:
    """emergency_off readback-confirms both outputs are OFF (no sourcing)."""
    drv = _driver(mode=WatchdogMode.OFF)
    await drv.connect()
    try:
        assert await drv.emergency_off() is True
    finally:
        await drv.disconnect()


@requires_source
async def test_a8b_smoke_late_pet_stall_recovery_turns_output_off() -> None:
    """A8b on a DUMMY LOAD: activate, source, then stall
    past the deadline without petting — both outputs must die and the latch set.

    A later command deliberately triggers the check. This is not A8c host-death
    coverage and must never be reported as such.
    """
    drv = _driver()
    await drv.connect()
    try:
        # Safe low level on a dummy load only.
        await drv.start_source("smua", p_target=0.01, v_compliance=1.0, i_compliance=0.1)
        # Stall: do NOT pet for longer than the deadline. Manually advance the
        # firmware deadline by calling pet once past the timeout to force the
        # stall-then-recover shutdown the TSP script evaluates inside pet().
        await asyncio.sleep(_TIMEOUT_S + 1.0)
        await drv._transport.write("cryodaq_wdog_pet()")
        tripped = await drv._transport.query("print(cryodaq_wdog_tripped)")
        assert float(tripped.strip()) > 0.5, "watchdog did not latch a trip"
        out_a = await drv._transport.query("print(smua.source.output)")
        out_b = await drv._transport.query("print(smub.source.output)")
        assert float(out_a.strip()) < 0.5 and float(out_b.strip()) < 0.5
    finally:
        await drv.emergency_off()
        await drv.disconnect()
