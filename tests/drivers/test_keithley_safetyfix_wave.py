"""Safety fix wave — driver-level (Keithley 2604B).

F1: stop_source must RAISE on an unverified OFF (readback still ON) instead of
    silently clearing runtime state — so SafetyManager latches FAULT, not
    SAFE_OFF.
F2: connect() crash-recovery force-OFF must readback-verify both channels; an
    unverified/still-ON output sets a blocking flag (output_state_unverified)
    without aborting connect. A later verified emergency_off clears it.
"""

from __future__ import annotations

import logging
import re

import pytest

from cryodaq.drivers.instruments.keithley_2604b import (
    Keithley2604B,
    OutputStateUnverifiedError,
)


class _FakeTransport:
    """Fake TSP transport whose source.output readback is configurable."""

    def __init__(
        self,
        *,
        output_readback: str = "0",
        idn: str = "Keithley Instruments Inc., Model 2604B, 04089762, 4.0.8",
    ) -> None:
        self.output_readback = output_readback
        self._idn = idn
        self.writes: list[str] = []

    async def open(self, resource: str) -> None:
        return None

    async def close(self) -> None:
        return None

    async def query(self, cmd: str, timeout_ms: int | None = None) -> str:
        c = cmd.lower()
        if "*idn?" in c:
            return self._idn
        if "source.output" in c:
            if "cryodaq_off_v1" in c:
                match = re.search(r"CRYODAQ_OFF_V1\|([0-9a-f]{32})\|%g", cmd)
                assert match is not None
                return f"CRYODAQ_OFF_V1|{match.group(1)}|{self.output_readback}\n"
            return self.output_readback
        if "measure.iv()" in c:
            return "0.0\t0.0"
        if "source.compliance" in c:
            return "false"
        return "0"

    async def write(self, cmd: str) -> None:
        self.writes.append(cmd)


# ---------------------------------------------------------------------------
# F1 — stop_source fail-closed on unverified OFF
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_source_raises_when_output_readback_still_on() -> None:
    """Readback reports output STILL ON after OUTPUT_OFF → stop_source RAISES
    and does NOT clear runtime state (fail-closed)."""
    driver = Keithley2604B("k", "USB0::FAKE", mock=False)
    driver._transport = _FakeTransport(output_readback="1")  # still ON
    driver._connected = True
    driver._channels["smua"].active = True
    driver._channels["smua"].p_target = 0.5
    driver._last_v["smua"] = 5.0

    with pytest.raises(OutputStateUnverifiedError):
        await driver.stop_source("smua")

    # Runtime state NOT cleared — the P=const loop must keep treating it active.
    assert driver._channels["smua"].active is True, "unverified OFF must keep active=True"
    assert driver._channels["smua"].p_target == 0.5


@pytest.mark.asyncio
async def test_stop_source_clean_off_still_clears_state() -> None:
    """Regression: a readback-confirmed OFF still resets runtime state."""
    driver = Keithley2604B("k", "USB0::FAKE", mock=False)
    driver._transport = _FakeTransport(output_readback="0")  # confirmed OFF
    driver._connected = True
    driver._channels["smua"].active = True
    driver._channels["smua"].p_target = 0.5
    driver._last_v["smua"] = 5.0

    await driver.stop_source("smua")

    assert driver._channels["smua"].active is False
    assert driver._last_v["smua"] == 0.0


# ---------------------------------------------------------------------------
# F2 — connect crash-recovery readback + blocking flag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_sets_unverified_flag_when_output_still_on(caplog) -> None:
    """connect() readback reports output ON → connect SUCCEEDS but the
    output_state_unverified flag is set (blocking flag, not a connect abort)."""
    caplog.set_level(logging.CRITICAL)
    driver = Keithley2604B("k", "USB0::FAKE", mock=False)
    driver._transport = _FakeTransport(output_readback="1")  # force-off never verifies

    await driver.connect()

    assert driver._connected is True, "connect must not abort on unverified output"
    assert driver.output_state_unverified is True
    assert any("unverified" in r.message.lower() for r in caplog.records)


@pytest.mark.asyncio
async def test_connect_clean_output_leaves_flag_false() -> None:
    """Readback confirms OFF on both channels → flag stays False."""
    driver = Keithley2604B("k", "USB0::FAKE", mock=False)
    driver._transport = _FakeTransport(output_readback="0")

    await driver.connect()

    assert driver._connected is True
    assert driver.output_state_unverified is False


@pytest.mark.asyncio
async def test_verified_emergency_off_clears_unverified_flag() -> None:
    """A later full emergency_off that confirms OFF clears the flag."""
    driver = Keithley2604B("k", "USB0::FAKE", mock=False)
    driver._transport = _FakeTransport(output_readback="1")
    await driver.connect()
    assert driver.output_state_unverified is True

    # Now the outputs read back OFF; a full emergency_off confirms and clears.
    driver._transport.output_readback = "0"
    assert await driver.emergency_off() is True
    assert driver.output_state_unverified is False
