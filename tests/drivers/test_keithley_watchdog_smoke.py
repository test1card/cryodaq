"""Bench smoke tests for the Keithley 2604B TSP dead-man watchdog (A8).

These run against a REAL instrument at hardware setup and before every
overnight — they re-verify the firmware integrity checks that get no CI:

  * version stamp — the script is re-uploaded from repo ``tsp/`` on every arm;
    the host reads ``CRYODAQ_WDOG_VERSION`` back and refuses to arm on mismatch.
  * arm-state readback — ``cryodaq_wdog_active == 1`` and
    ``cryodaq_wdog_tripped == 0`` after ``cryodaq_wdog_run()`` (a truncated
    upload would otherwise pass the fire-and-forget writes silently).
  * verified-OFF readback — ``emergency_off`` confirms the outputs are OFF.
  * trip-test — arm, stall past the deadline, confirm both outputs die and the
    latch is set.

They SKIP gracefully with no hardware: set ``CRYODAQ_KEITHLEY_RESOURCE`` to the
VISA resource string to enable them. Any test that ENERGISES the source is
additionally gated on ``CRYODAQ_SMOKE_ALLOW_SOURCE=1`` and MUST only be run on a
macet (dummy) load at a safe low level — NEVER on the cryostat heater.

The autonomous ``trigger.timer`` dead-man (true host-death cover) is the single
remaining bench-verified upgrade — see ``tsp/cryodaq_wdog.lua``. These smoke
tests exercise the pet-based stall-then-recover trip; they do NOT prove the
autonomous no-host path.
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
async def test_smoke_version_stamp_matches() -> None:
    """The uploaded firmware reports the version the driver expects (refuse-on-
    mismatch is proven by a successful arm)."""
    drv = _driver()
    await drv.connect()
    try:
        assert drv._wdog_armed is True
        raw = await drv._transport.query("print(CRYODAQ_WDOG_VERSION)")
        assert int(float(raw.strip())) == _WDOG_SCRIPT_VERSION
    finally:
        await drv.disconnect()


@requires_hw
async def test_smoke_arm_state_readback() -> None:
    """After arm, firmware reports active==1 and tripped==0."""
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
async def test_smoke_verified_off_readback() -> None:
    """emergency_off readback-confirms both outputs are OFF (no sourcing)."""
    drv = _driver(mode=WatchdogMode.OFF)
    await drv.connect()
    try:
        assert await drv.emergency_off() is True
    finally:
        await drv.disconnect()


@requires_source
async def test_smoke_watchdog_trip_kills_output() -> None:
    """Trip-test on a DUMMY LOAD at a safe low level: arm, source, then stall
    past the deadline without petting — both outputs must die and the latch set.

    NOTE: this exercises the pet-based (stall-then-recover) mechanism, NOT the
    autonomous no-host trigger.timer path (bench-parked). Results are for
    Vladimir to record; this test never fabricates them.
    """
    drv = _driver()
    await drv.connect()
    try:
        # Safe low level on a dummy load only.
        await drv.start_source("smua", p_target=0.01, v_compliance=1.0, i_compliance=0.1)
        # Stall: do NOT pet for longer than the deadline. Manually advance the
        # firmware deadline by calling pet once past the timeout to force the
        # stall-then-recover kill the firmware evaluates inside pet().
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
