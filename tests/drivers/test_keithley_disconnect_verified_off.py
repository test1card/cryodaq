"""Connection-scoped verified-OFF evidence at the Keithley lifecycle boundary."""

from __future__ import annotations

import asyncio
import re

import pytest

from cryodaq.drivers.instruments.keithley_2604b import (
    Keithley2604B,
    OutputStateUnverifiedError,
)


class _Transport:
    def __init__(
        self,
        readbacks: list[str] | None = None,
        *,
        fail_write: bool = False,
        fail_read: bool = False,
    ) -> None:
        self.readbacks = list(readbacks or ["0"])
        self.fail_write = fail_write
        self.fail_read = fail_read
        self.closed = 0
        self.writes: list[str] = []
        self.output_queries = 0

    async def open(self, _resource: str) -> None:
        return None

    async def close(self) -> None:
        self.closed += 1

    async def write(self, command: str) -> None:
        if self.fail_write and "source." in command:
            raise OSError("write failed")
        self.writes.append(command)

    async def query(self, command: str, timeout_ms: int | None = None) -> str:
        del timeout_ms
        if "*IDN?" in command:
            return "Keithley Instruments Inc.,Model 2604B,04052028,1.0"
        if "source.output" in command:
            self.output_queries += 1
            if self.fail_read:
                raise OSError("read failed")
            value = self.readbacks.pop(0) if len(self.readbacks) > 1 else self.readbacks[0]
            match = re.search(r"CRYODAQ_OFF_V1\|([0-9a-f]{32})\|", command)
            assert match is not None
            return f"CRYODAQ_OFF_V1|{match.group(1)}|{value}"
        return "0"


def _connected_driver(*, readbacks: list[str]) -> tuple[Keithley2604B, _Transport]:
    driver = Keithley2604B("k", "USB::FAKE", mock=False)
    transport = _Transport(readbacks)
    driver._transport = transport
    driver._connected = True
    return driver, transport


async def test_never_connected_emergency_off_has_no_optimistic_proof() -> None:
    driver = Keithley2604B("k", "USB::FAKE", mock=False)

    assert await driver.emergency_off() is False


async def test_failed_emergency_off_preserves_active_runtime_and_disconnect_surfaces() -> None:
    driver, transport = _connected_driver(readbacks=["0", "1"])
    driver._channels["smub"].active = True
    driver._channels["smub"].p_target = 0.5

    with pytest.raises(OutputStateUnverifiedError, match="readback-verified OFF"):
        await driver.disconnect()

    assert transport.closed == 0
    assert driver.connected is True
    assert driver._channels["smub"].active is True
    assert driver._channels["smub"].p_target == 0.5
    assert driver.output_state_unverified is True
    driver._connected = False
    assert await driver.emergency_off() is False


async def test_partial_channel_proof_cannot_authorize_disconnected_success() -> None:
    driver, _transport = _connected_driver(readbacks=["0"])

    assert await driver.emergency_off("smua") is True
    driver._connected = False

    assert await driver.emergency_off("smua") is False
    assert await driver.emergency_off() is False


@pytest.mark.parametrize("failure", ["write", "read"])
async def test_transport_failure_cannot_stamp_off_proof(failure: str) -> None:
    driver = Keithley2604B("k", "USB::FAKE", mock=False)
    transport = _Transport(
        ["0"],
        fail_write=failure == "write",
        fail_read=failure == "read",
    )
    driver._transport = transport
    driver._connected = True
    driver._channels["smua"].active = True

    assert await driver.emergency_off() is False
    assert driver._channels["smua"].active is True
    driver._connected = False
    assert await driver.emergency_off() is False


async def test_disconnect_reuses_current_generation_both_off_proof() -> None:
    driver, transport = _connected_driver(readbacks=["0"])

    assert await driver.emergency_off() is True
    queries_after_proof = transport.output_queries
    await driver.disconnect()

    assert transport.output_queries == queries_after_proof
    assert transport.closed == 1


@pytest.mark.parametrize(
    "readback",
    ["0", "+0", "-0", "0.0", "-0.000", ".0", "0e9", " 0 \n"],
)
async def test_only_exact_finite_zero_literals_verify_off(readback: str) -> None:
    driver, _transport = _connected_driver(readbacks=[readback])

    assert await driver._verify_output_off("smua") is True


@pytest.mark.parametrize(
    "readback",
    [
        "nan",
        "NaN",
        "inf",
        "+Inf",
        "-1",
        "-0.0001",
        "0.25",
        "1",
        "false",
        "true",
        "0x0",
        "0 trailing",
        "0,0",
        "٠",
        "۰",
        "０",
        "＋0",
        "－0",
        "0．0",
        "0٠",
        "٠e0",
        "0e٠",
        "०",
        "",
        "0" * 65,
    ],
)
async def test_nonzero_or_nonliteral_readback_is_unverified(readback: str) -> None:
    driver, _transport = _connected_driver(readbacks=[readback])

    assert await driver._verify_output_off("smua") is False


@pytest.mark.parametrize("readback", ["nan", "-1", "0.25", "false", "0 trailing"])
async def test_invalid_readback_cannot_clear_runtime_or_authorize_disconnect(
    readback: str,
) -> None:
    driver, transport = _connected_driver(readbacks=[readback])
    driver._channels["smua"].active = True

    assert await driver.emergency_off() is False
    assert driver._channels["smua"].active is True
    with pytest.raises(OutputStateUnverifiedError):
        await driver.disconnect()
    assert driver.connected is True
    assert transport.closed == 0


async def test_reconnect_invalidates_old_generation_then_reproves_both_off() -> None:
    driver = Keithley2604B("k", "USB::FAKE", mock=False)
    first = _Transport(["0"])
    driver._transport = first
    await driver.connect()
    await driver.disconnect()
    assert await driver.emergency_off() is True

    second = _Transport(["1"])
    driver._transport = second
    await driver.connect()

    assert driver.output_state_unverified is True
    driver._connected = False
    assert await driver.emergency_off() is False


async def test_disconnect_cancellation_still_closes_and_preserves_uncertainty() -> None:
    driver, transport = _connected_driver(readbacks=["1"])
    driver._channels["smua"].active = True

    async def _cancelled_off(channel: str | None = None) -> bool:
        del channel
        raise asyncio.CancelledError

    driver.emergency_off = _cancelled_off  # type: ignore[method-assign]

    with pytest.raises(asyncio.CancelledError):
        await driver.disconnect()

    assert transport.closed == 0
    assert driver.connected is True
    assert driver._channels["smua"].active is True
    assert driver.output_state_unverified is True


async def test_mock_connection_uses_simulator_local_proof_only() -> None:
    driver = Keithley2604B("k", "USB::MOCK", mock=True)
    assert await driver.emergency_off() is True

    await driver.connect()
    await driver.start_source("smua", 0.5, 40.0, 1.0)
    assert driver.output_state_unverified is True
    assert await driver.emergency_off() is True
    await driver.disconnect()
    await driver.disconnect()  # idempotent cleanup

    assert await driver.emergency_off() is True
