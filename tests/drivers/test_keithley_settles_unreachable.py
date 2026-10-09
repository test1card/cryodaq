"""The real driver must be able to bury a handle whose device is gone.

lab53, 2026-09-02: everything was unplugged at once and replugged two minutes
later. The GPIB LakeShores and the serial gauge recovered by themselves. The
Keithley did not, and this is the line that explains why:

    14:24:32  Keithley_1: SAFETY: query lost transport authority;
              retaining the existing handle only for OFF recovery and close

``_enter_recovery_after_transport_loss`` keeps the VISA handle deliberately, so
a later OFF attempt has something to try. That is right when the instrument is
still there. When the cable is out it is a trap: the handle is bound to the
pre-replug USB enumeration, so re-plugging is invisible to it, every OFF
attempt writes into a corpse, and -- because the handle is still held -- the
driver never becomes ``unreachable_idle``, so the scheduler never retries and
``connect()`` would refuse anyway with "recovery transport remains open".

``settle_unreachable()`` closes that handle, and ONLY when the device did not
answer. The distinction carries the whole safety content: an OFF readback that
RAISES means nothing is on the far side; one that ANSWERS -- even to say the
output is still on -- means there is, and discarding a live session to an
instrument that is refusing to de-energize would be the opposite of safe.

These run against the real Keithley2604B with a fake transport, because the
SafetyManager-level fake is only as good as my model of the driver, and my
first model of it was wrong.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.drivers.contracts import SourceOffResult
from cryodaq.drivers.instruments.keithley_2604b import Keithley2604B

_RESOURCE = "USB0::0x05E6::0x2604::4083236::0::INSTR"
_IDN = "Keithley Instruments Inc., Model 2604B, 4083236, 3.2.1"


class _Cable:
    """A transport whose device can be removed and returned."""

    def __init__(self) -> None:
        self.present = True
        self.closed = 0
        self.close_raises = False
        self.opened = 0

    def _fail(self) -> None:
        raise OSError("USBTMC query failed in bounded worker (VISA session dead)")

    async def open(self, _resource: str) -> None:
        self.opened += 1
        if not self.present:
            raise OSError("USBTMC: resource open failed")

    async def close(self) -> None:
        self.closed += 1
        if self.close_raises:
            raise OSError("viClose failed")

    async def write(self, _command: str) -> None:
        if not self.present:
            self._fail()

    async def query(self, command: str, timeout_ms: int | None = None) -> str:
        del timeout_ms
        if not self.present:
            self._fail()
        if "*IDN?" in command:
            return _IDN
        if "CRYODAQ_OFF_V1" in command:
            # The challenge/response the driver requires, answering "output 0".
            nonce = command.split("|")[1]
            return f"CRYODAQ_OFF_V1|{nonce}|0"
        if "source.output" in command:
            return "0"
        return "0"


def _driver() -> tuple[Keithley2604B, _Cable]:
    k = Keithley2604B(name="test", resource_str=_RESOURCE, mock=False)
    cable = _Cable()
    transport = MagicMock()
    transport.open = AsyncMock(side_effect=cable.open)
    transport.close = AsyncMock(side_effect=cable.close)
    transport.write = AsyncMock(side_effect=cable.write)
    transport.query = AsyncMock(side_effect=cable.query)
    k._transport = transport
    return k, cable


# ---------------------------------------------------------------------------
# The real transition
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_driver_demotes_and_retains_its_handle_when_the_cable_goes():
    """Pin the state my first fix mismodelled, so it cannot be got wrong again."""
    k, cable = _driver()
    await k.connect()
    assert k.connected is True

    cable.present = False
    with pytest.raises(Exception):
        await k.read_channels()

    assert k.connected is False, "the driver demotes itself"
    assert k._recovery_transport_open is True, "and KEEPS the handle -- this is what blocked reconnect"
    assert k.unreachable_idle is False, "so it is not idle, and nothing retries"


@pytest.mark.asyncio
async def test_an_unanswering_device_lets_the_handle_be_buried():
    k, cable = _driver()
    await k.connect()
    cable.present = False
    with pytest.raises(Exception):
        await k.read_channels()

    # The OFF attempt is what discovers that nothing answers.
    assert await k.emergency_off() is SourceOffResult.PHYSICAL_STATE_UNKNOWN
    assert k._recovery_off_transport_dead is True

    closes_before = cable.closed
    assert await k.settle_unreachable() is True
    assert cable.closed == closes_before + 1
    assert k._recovery_transport_open is False
    assert k.unreachable_idle is True, "now the scheduler can retry"


@pytest.mark.asyncio
async def test_the_settled_driver_opens_a_fresh_session_when_the_cable_returns():
    k, cable = _driver()
    await k.connect()
    cable.present = False
    with pytest.raises(Exception):
        await k.read_channels()
    await k.emergency_off()
    assert await k.settle_unreachable() is True

    cable.present = True
    await k.connect()
    assert k.connected is True
    assert k.output_state_unverified is False, "a real connect re-establishes proof"


# ---------------------------------------------------------------------------
# What must NOT be buried
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_device_that_answers_keeps_its_handle():
    """Reachable and refusing to go off is a hardware fault, not a missing cable."""
    k, _cable = _driver()
    await k.connect()
    # Force the recovery state while the device is still answering.
    k._enter_recovery_after_transport_loss("test")
    assert k._recovery_transport_open is True

    # An answered readback must clear the dead-transport flag.
    await k.emergency_off()
    assert k._recovery_off_transport_dead is False

    assert await k.settle_unreachable() is False, "a live session must not be discarded"
    assert k._recovery_transport_open is True


@pytest.mark.asyncio
async def test_settle_refuses_while_connected():
    k, _cable = _driver()
    await k.connect()
    assert await k.settle_unreachable() is False


@pytest.mark.asyncio
async def test_a_failed_close_records_an_incomplete_teardown():
    k, cable = _driver()
    await k.connect()
    cable.present = False
    with pytest.raises(Exception):
        await k.read_channels()
    await k.emergency_off()

    cable.close_raises = True
    assert await k.settle_unreachable() is False
    assert k._teardown_incomplete is True
    assert k.unreachable_idle is False


@pytest.mark.asyncio
async def test_burying_the_handle_mints_no_off_evidence():
    k, cable = _driver()
    await k.connect()
    cable.present = False
    with pytest.raises(Exception):
        await k.read_channels()
    await k.emergency_off()
    assert await k.settle_unreachable() is True

    assert k.output_state_unverified is True, "closing a handle says nothing about the output"


@pytest.mark.asyncio
async def test_a_mock_driver_never_settles():
    k = Keithley2604B(name="test", resource_str=_RESOURCE, mock=True)
    assert await k.settle_unreachable() is False
