"""Connection-scoped verified-OFF evidence at the Keithley lifecycle boundary."""

from __future__ import annotations

import asyncio
import math
import re

import pytest

from cryodaq.drivers.base import ChannelStatus
from cryodaq.drivers.instruments.keithley_2604b import (
    Keithley2604B,
    OutputStateUnverifiedError,
    TransportTeardownIncompleteError,
)

_CANONICAL_IDN = "Keithley Instruments Inc., Model 2604B, 04089762, 4.0.8"
_OFF_NONCE_RE = re.compile(r"CRYODAQ_OFF_V1\|([0-9a-f]{32})\|%g")


def _off_reply(command: str, state: str = "0") -> str:
    match = _OFF_NONCE_RE.search(command)
    assert match is not None, f"missing strict OFF challenge in {command!r}"
    return f"CRYODAQ_OFF_V1|{match.group(1)}|{state}\n"


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
            return _CANONICAL_IDN
        if "source.output" in command:
            self.output_queries += 1
            if self.fail_read:
                raise OSError("read failed")
            state = self.readbacks.pop(0) if len(self.readbacks) > 1 else self.readbacks[0]
            if "CRYODAQ_OFF_V1" in command:
                return _off_reply(command, state)
            return state
        return "0"


def _connected_driver(*, readbacks: list[str]) -> tuple[Keithley2604B, _Transport]:
    driver = Keithley2604B("k", "USB0::0x05E6::0x2604::04089762::INSTR", mock=False)
    transport = _Transport(readbacks)
    driver._transport = transport
    driver._connected = True
    driver._instrument_id = _CANONICAL_IDN
    return driver, transport


async def test_never_connected_emergency_off_has_no_optimistic_proof() -> None:
    driver = Keithley2604B("k", "USB0::0x05E6::0x2604::04089762::INSTR", mock=False)

    assert await driver.emergency_off() is False


async def test_disconnected_stop_source_fails_closed_without_current_off_proof() -> None:
    driver = Keithley2604B("k", "USB0::0x05E6::0x2604::04089762::INSTR", mock=False)
    driver._channels["smua"].active = True
    driver._channels["smua"].p_target = 0.5

    with pytest.raises(OutputStateUnverifiedError, match="disconnected"):
        await driver.stop_source("smua")

    assert driver._channels["smua"].active is True
    assert driver._channels["smua"].p_target == 0.5
    assert driver.output_state_unverified is True


async def test_disconnected_verify_off_never_fabricates_readback() -> None:
    driver = Keithley2604B("k", "USB0::0x05E6::0x2604::04089762::INSTR", mock=False)
    driver._output_off_verified["smua"] = True

    assert await driver._verify_output_off("smua") is False


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
    driver = Keithley2604B("k", "USB0::0x05E6::0x2604::04089762::INSTR", mock=False)
    transport = _Transport(
        ["0"],
        fail_write=failure == "write",
        fail_read=failure == "read",
    )
    driver._transport = transport
    driver._connected = True
    driver._channels["smua"].active = True

    exact_off = await driver.emergency_off()
    assert exact_off is False
    assert driver._channels["smua"].active is True
    assert driver._output_off_verified["smua"] is False
    driver._connected = False
    assert await driver.emergency_off() is False


async def test_disconnect_reuses_current_generation_both_off_proof() -> None:
    driver, transport = _connected_driver(readbacks=["0"])

    assert await driver.emergency_off() is True
    queries_after_proof = transport.output_queries
    await driver.disconnect()

    assert transport.output_queries == queries_after_proof
    assert transport.closed == 1
    assert await driver.emergency_off() is False


async def test_observed_external_output_on_invalidates_stale_off_proof() -> None:
    driver, transport = _connected_driver(readbacks=["1", "0"])
    driver._output_off_verified = {"smua": True, "smub": True}

    async def _query(command: str, timeout_ms: int | None = None) -> str:
        del timeout_ms
        if "smua.source.output" in command:
            return "1"
        if "smub.source.output" in command:
            return "0"
        if "smua.measure.iv" in command:
            return "0.01\t5.0"
        return "0"

    transport.query = _query  # type: ignore[method-assign]
    await driver.read_channels()

    assert driver._output_off_verified["smua"] is False
    assert driver.output_state_unverified is True


async def test_garbage_output_state_is_not_published_as_ok_zeros() -> None:
    driver, transport = _connected_driver(readbacks=["garbage", "0"])

    readings = await driver.read_channels()

    smua = [reading for reading in readings if "/smua/" in reading.channel]
    assert smua
    assert all(reading.status is ChannelStatus.SENSOR_ERROR for reading in smua)
    assert all(math.isnan(reading.value) for reading in smua)
    assert transport.output_queries == 2


@pytest.mark.parametrize(
    "readback",
    ["0"],
)
async def test_only_literal_zero_in_current_challenge_verifies_off(readback: str) -> None:
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
    driver = Keithley2604B("k", "USB0::0x05E6::0x2604::04089762::INSTR", mock=False)
    first = _Transport(["0"])
    driver._transport = first
    await driver.connect()
    await driver.disconnect()
    assert await driver.emergency_off() is False

    second = _Transport(["1"])
    driver._transport = second
    with pytest.raises(OutputStateUnverifiedError, match="retained only for recovery"):
        await driver.connect()

    assert driver.connected is False
    assert driver._recovery_transport_open is True
    assert driver.output_state_unverified is True
    assert driver._instrument_id == ""
    with pytest.raises(RuntimeError, match="recovery-only transport"):
        await driver.start_source("smua", 0.5, 40.0, 1.0)
    assert await driver.emergency_off() is False


async def test_connect_keeps_output_state_unsafe_until_both_readbacks_finish() -> None:
    second_read_started = asyncio.Event()
    release_second_read = asyncio.Event()

    class _TwoStepReadbackTransport(_Transport):
        async def query(self, command: str, timeout_ms: int | None = None) -> str:
            if "source.output" in command:
                self.output_queries += 1
                if self.output_queries == 2:
                    second_read_started.set()
                    await release_second_read.wait()
                return _off_reply(command)
            return await super().query(command, timeout_ms)

    driver = Keithley2604B("k", "USB0::0x05E6::0x2604::04089762::INSTR", mock=False)
    transport = _TwoStepReadbackTransport(["0"])
    driver._transport = transport
    task = asyncio.create_task(driver.connect())
    await second_read_started.wait()

    assert driver.connected is False
    assert driver.output_state_unverified is True

    release_second_read.set()
    await task
    assert driver.connected is True
    assert driver.output_state_unverified is False


async def test_new_connection_revokes_stale_runtime_authority_before_open() -> None:
    open_started = asyncio.Event()
    release_open = asyncio.Event()

    class _BlockingOpenTransport(_Transport):
        async def open(self, _resource: str) -> None:
            open_started.set()
            await release_open.wait()

    driver = Keithley2604B("k", "USB0::0x05E6::0x2604::04089762::INSTR", mock=False)
    for runtime in driver._channels.values():
        runtime.active = True
        runtime.p_target = 0.75
    transport = _BlockingOpenTransport(["0"])
    driver._transport = transport
    task = asyncio.create_task(driver.connect())
    await open_started.wait()

    assert driver.connected is False
    assert all(runtime.active is False for runtime in driver._channels.values())
    assert all(runtime.p_target == 0.0 for runtime in driver._channels.values())
    assert driver.output_state_unverified is True

    release_open.set()
    await task


async def test_process_control_baseexception_is_not_masked_by_connect_cleanup() -> None:
    class _ProcessControl(BaseException):
        pass

    class _ExitTransport(_Transport):
        async def open(self, _resource: str) -> None:
            raise _ProcessControl("terminate")

    driver = Keithley2604B("k", "USB0::0x05E6::0x2604::04089762::INSTR", mock=False)
    transport = _ExitTransport(["0"])
    driver._transport = transport

    with pytest.raises(_ProcessControl, match="terminate"):
        await driver.connect()

    assert transport.closed == 1
    assert driver.connected is False
    assert driver._connect_in_progress is False
    assert driver.output_state_unverified is True


async def test_disconnect_cancellation_without_off_proof_refuses_close() -> None:
    driver, transport = _connected_driver(readbacks=["1"])
    driver._channels["smua"].active = True
    original_query = transport.query

    async def _cancelled_query(command: str, timeout_ms: int | None = None) -> str:
        if "CRYODAQ_OFF_V1" in command:
            raise asyncio.CancelledError
        return await original_query(command, timeout_ms)

    transport.query = _cancelled_query  # type: ignore[method-assign]

    with pytest.raises(asyncio.CancelledError):
        await driver.disconnect()

    assert transport.closed == 0
    assert driver.connected is False
    assert driver._recovery_transport_open is True
    assert driver._instrument_id == ""
    assert driver.output_state_unverified is True
    assert driver._channels["smua"].active is True
    assert driver.output_state_unverified is True


async def test_connect_cancellation_settles_transport_and_connection_truth() -> None:
    started = asyncio.Event()

    class _CancelledConnectTransport(_Transport):
        async def query(self, command: str, timeout_ms: int | None = None) -> str:
            del timeout_ms
            if command == "*IDN?":
                started.set()
                await asyncio.Event().wait()
            return "0"

    driver = Keithley2604B("k", "USB0::0x05E6::0x2604::04089762::INSTR", mock=False)
    transport = _CancelledConnectTransport()
    driver._transport = transport
    task = asyncio.create_task(driver.connect())
    await started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert transport.closed == 1
    assert driver.connected is False
    assert driver._connect_in_progress is False
    assert driver._output_off_verified == {"smua": False, "smub": False}
    assert driver.output_state_unverified is True


async def test_connect_cancellation_preserved_when_cleanup_close_fails(caplog) -> None:
    import logging

    started = asyncio.Event()

    class _FailedCleanupTransport(_Transport):
        async def query(self, command: str, timeout_ms: int | None = None) -> str:
            del timeout_ms
            if command == "*IDN?":
                started.set()
                await asyncio.Event().wait()
            return "0"

        async def close(self) -> None:
            self.closed += 1
            raise OSError("cleanup close failed")

    driver = Keithley2604B("k", "USB0::0x05E6::0x2604::04089762::INSTR", mock=False)
    transport = _FailedCleanupTransport()
    driver._transport = transport
    task = asyncio.create_task(driver.connect())
    await started.wait()
    task.cancel()

    with caplog.at_level(logging.CRITICAL), pytest.raises(asyncio.CancelledError):
        await task

    assert transport.closed == 1
    assert driver.connected is False
    assert driver._connect_in_progress is False
    assert driver.output_state_unverified is True
    assert "failed-connect transport cleanup failed" in caplog.text


async def test_repeated_connect_cannot_close_a_live_connection() -> None:
    driver, transport = _connected_driver(readbacks=["0"])
    generation = driver._connection_generation

    with pytest.raises(RuntimeError, match="connect already active"):
        await driver.connect()

    assert driver.connected is True
    assert driver._connection_generation == generation
    assert transport.closed == 0


async def test_concurrent_connect_is_rejected_without_closing_first_attempt() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    class _BlockingOpenTransport(_Transport):
        async def open(self, _resource: str) -> None:
            started.set()
            await release.wait()

    driver = Keithley2604B("k", "USB0::0x05E6::0x2604::04089762::INSTR", mock=False)
    transport = _BlockingOpenTransport(["0"])
    driver._transport = transport
    first = asyncio.create_task(driver.connect())
    await started.wait()

    with pytest.raises(RuntimeError, match="connect already active"):
        await driver.connect()
    assert transport.closed == 0

    release.set()
    await first
    assert driver.connected is True


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


async def test_stale_generation_proof_cannot_skip_disconnect_readback() -> None:
    driver, transport = _connected_driver(readbacks=["1"])
    driver._connection_generation = 4
    driver._output_off_verified = {"smua": True, "smub": True}
    driver._output_off_verified_generation = {"smua": 3, "smub": 3}

    with pytest.raises(OutputStateUnverifiedError):
        await driver.disconnect()

    assert transport.output_queries >= 1
    assert transport.closed == 0
    assert driver.connected is True


async def test_off_readback_from_superseded_connection_cannot_stamp_proof() -> None:
    driver, transport = _connected_driver(readbacks=["0"])
    started = asyncio.Event()
    release = asyncio.Event()

    async def _query(command: str, timeout_ms: int | None = None) -> str:
        del timeout_ms
        if "source.output" in command:
            started.set()
            await release.wait()
            return _off_reply(command)
        return "0"

    transport.query = _query  # type: ignore[method-assign]
    task = asyncio.create_task(driver.emergency_off("smua"))
    await started.wait()
    driver._connection_generation += 1
    release.set()

    assert await task is False
    assert driver._output_off_verified["smua"] is False
    assert driver.output_state_unverified is True


async def test_nonfinite_iv_is_masked_with_bounded_raw_evidence() -> None:
    driver, transport = _connected_driver(readbacks=["1", "0"])

    async def _query(command: str, timeout_ms: int | None = None) -> str:
        del timeout_ms
        if "smua.source.output" in command:
            return "1"
        if "smub.source.output" in command:
            return "0"
        if "smua.measure.iv" in command:
            return "nan\tinf"
        return "0"

    transport.query = _query  # type: ignore[method-assign]

    readings = await driver.read_channels()

    smua = [reading for reading in readings if "/smua/" in reading.channel]
    assert len(smua) == 4
    assert all(reading.status is ChannelStatus.SENSOR_ERROR for reading in smua)
    assert all(math.isnan(reading.value) for reading in smua)
    assert all(reading.raw is None for reading in smua)
    assert all("nan\\tinf" in reading.metadata["reported_iv_response"] for reading in smua)


def test_nonfinite_raw_buffer_rows_are_rejected_but_finite_truth_is_retained() -> None:
    driver = Keithley2604B("k", "USB0::0x05E6::0x2604::04089762::INSTR", mock=False)

    assert driver._parse_buffer_response("0,nan,1") == []

    zero_current = driver._parse_buffer_response("0,1,0")
    assert len(zero_current) == 1
    assert zero_current[0]["timestamp"] == 0.0
    assert zero_current[0]["voltage"] == 1.0
    assert zero_current[0]["current"] == 0.0
    assert math.isnan(zero_current[0]["resistance"])
    assert zero_current[0]["power"] == 0.0

    overflow = driver._parse_buffer_response("0,1e308,1e308")
    assert len(overflow) == 1
    assert overflow[0]["voltage"] == 1e308
    assert overflow[0]["current"] == 1e308
    assert overflow[0]["resistance"] == 1.0
    assert math.isnan(overflow[0]["power"])


def test_unavailable_resistance_does_not_hide_valid_iv_or_power() -> None:
    driver = Keithley2604B("k", "USB0::0x05E6::0x2604::04089762::INSTR", mock=False)

    readings = driver._build_channel_readings("smua", voltage=5.0, current=0.0)
    by_field = {reading.channel.rsplit("/", 1)[-1]: reading for reading in readings}

    assert by_field["voltage"].value == 5.0
    assert by_field["voltage"].status is ChannelStatus.OK
    assert by_field["current"].value == 0.0
    assert by_field["current"].status is ChannelStatus.OK
    assert math.isnan(by_field["resistance"].value)
    assert by_field["resistance"].status is ChannelStatus.SENSOR_ERROR
    assert by_field["power"].value == 0.0
    assert by_field["power"].status is ChannelStatus.OK


async def test_start_source_requires_current_channel_off_proof() -> None:
    driver, transport = _connected_driver(readbacks=["0"])
    driver._mark_channel_off_verified("smub")

    with pytest.raises(OutputStateUnverifiedError, match="smua source start blocked"):
        await driver.start_source("smua", 0.5, 40.0, 1.0)

    assert transport.writes == []


async def test_cancelled_disconnect_close_late_success_settles_exact_generation() -> None:
    driver, transport = _connected_driver(readbacks=["0"])
    driver._mark_channel_off_verified("smua")
    driver._mark_channel_off_verified("smub")
    disconnect_generation = driver._connection_generation
    close_started = asyncio.Event()
    release_close = asyncio.Event()

    async def _slow_close() -> None:
        close_started.set()
        await release_close.wait()
        transport.closed += 1

    transport.close = _slow_close  # type: ignore[method-assign]
    task = asyncio.create_task(driver.disconnect())
    await close_started.wait()

    writes_before = list(transport.writes)
    queries_before = transport.output_queries
    with pytest.raises(RuntimeError, match="lifecycle transition"):
        await driver.start_source("smua", 0.5, 40.0, 1.0)
    with pytest.raises(RuntimeError, match="lifecycle transition"):
        await driver.read_channels()
    with pytest.raises(RuntimeError, match="lifecycle transition"):
        await driver.update_source_limit("smua", v_comp=20.0)
    assert transport.writes == writes_before
    assert transport.output_queries == queries_before

    task.cancel()
    await asyncio.sleep(0)

    assert task.done() is False
    release_close.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert transport.closed == 1
    assert driver._connection_generation == disconnect_generation
    assert driver.connected is False
    assert driver.output_state_unverified is True


async def test_cancelled_disconnect_close_late_failure_keeps_reconnect_blocked() -> None:
    driver, transport = _connected_driver(readbacks=["0"])
    driver._mark_channel_off_verified("smua")
    driver._mark_channel_off_verified("smub")
    close_started = asyncio.Event()
    release_close = asyncio.Event()

    async def _late_failed_close() -> None:
        close_started.set()
        await release_close.wait()
        raise RuntimeError("late close failed")

    transport.close = _late_failed_close  # type: ignore[method-assign]
    task = asyncio.create_task(driver.disconnect())
    await close_started.wait()
    task.cancel()
    await asyncio.sleep(0)

    assert task.done() is False
    release_close.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert driver.connected is False
    assert driver._recovery_transport_open is True
    assert driver._instrument_id == ""
    assert driver._teardown_incomplete is True
    with pytest.raises(TransportTeardownIncompleteError, match="reconnect refused"):
        await driver.connect()


async def test_wrong_generation_late_close_cannot_settle_current_connection() -> None:
    driver, transport = _connected_driver(readbacks=["0"])
    driver._mark_channel_off_verified("smua")
    driver._mark_channel_off_verified("smub")
    close_started = asyncio.Event()
    release_close = asyncio.Event()

    async def _late_old_generation_close() -> None:
        close_started.set()
        await release_close.wait()
        transport.closed += 1

    transport.close = _late_old_generation_close  # type: ignore[method-assign]
    task = asyncio.create_task(driver.disconnect())
    await close_started.wait()
    old_generation = driver._connection_generation
    current_identity = "Keithley Instruments Inc., Model 2604B, CURRENTGEN, 4.0.8"
    driver._connection_generation += 1
    driver._connected = True
    driver._instrument_id = current_identity
    release_close.set()

    with pytest.raises(TransportTeardownIncompleteError, match="late close for generation"):
        await task

    assert transport.closed == 1
    assert driver._connection_generation == old_generation + 1
    assert driver.connected is False
    assert driver._recovery_transport_open is False
    assert driver._instrument_id == ""
    assert driver._teardown_incomplete is True
    with pytest.raises(TransportTeardownIncompleteError, match="reconnect refused"):
        await driver.connect()


async def test_start_superseded_during_config_never_reaches_output_on() -> None:
    driver, transport = _connected_driver(readbacks=["0"])
    assert await driver.emergency_off("smua") is True
    transport.writes.clear()
    reset_started = asyncio.Event()
    release_reset = asyncio.Event()
    original_write = transport.write

    async def _blocking_write(command: str) -> None:
        if command == "smua.reset()":
            reset_started.set()
            await release_reset.wait()
        await original_write(command)

    transport.write = _blocking_write  # type: ignore[method-assign]
    start = asyncio.create_task(driver.start_source("smua", 0.5, 40.0, 1.0))
    await reset_started.wait()

    assert await driver.emergency_off("smua") is True
    release_reset.set()
    with pytest.raises(RuntimeError, match="superseded"):
        await start

    assert not any("OUTPUT_ON" in command for command in transport.writes)
    assert driver._channels["smua"].active is False
    assert driver._has_current_off_proof("smua") is True


async def test_ambiguous_output_on_is_pessimistically_active_until_off_cleanup() -> None:
    driver, transport = _connected_driver(readbacks=["0"])
    assert await driver.emergency_off("smua") is True
    transport.writes.clear()
    output_on_started = asyncio.Event()
    release_output_on = asyncio.Event()
    original_write = transport.write

    async def _ambiguous_write(command: str) -> None:
        if "OUTPUT_ON" in command:
            transport.writes.append(command)
            output_on_started.set()
            await release_output_on.wait()
            raise OSError("write completed but host lost completion status")
        await original_write(command)

    transport.write = _ambiguous_write  # type: ignore[method-assign]
    start = asyncio.create_task(driver.start_source("smua", 0.5, 40.0, 1.0))
    await output_on_started.wait()

    assert driver._channels["smua"].active is True
    assert driver._source_regulation_epoch["smua"] is None
    release_output_on.set()
    with pytest.raises(OSError, match="lost completion"):
        await start

    output_on_index = next(i for i, command in enumerate(transport.writes) if "OUTPUT_ON" in command)
    later_off = [i for i, command in enumerate(transport.writes) if i > output_on_index and "OUTPUT_OFF" in command]
    assert later_off
    assert driver._channels["smua"].active is False
    assert driver._has_current_off_proof("smua") is True


async def test_emergency_supersedes_regulation_before_positive_level_write() -> None:
    driver, transport = _connected_driver(readbacks=["0"])
    runtime = driver._channels["smua"]
    runtime.active = True
    runtime.p_target = 0.5
    runtime.v_comp = 40.0
    runtime.i_comp = 1.0
    driver._source_command_epoch["smua"] = 7
    driver._source_regulation_epoch["smua"] = 7
    measure_started = asyncio.Event()
    release_measure = asyncio.Event()
    original_query = transport.query

    async def _blocking_query(command: str, timeout_ms: int | None = None) -> str:
        if "smua.measure.iv()" in command:
            measure_started.set()
            await release_measure.wait()
            return "0.01\t1.0"
        if "smua.source.compliance" in command:
            return "false"
        return await original_query(command, timeout_ms)

    transport.query = _blocking_query  # type: ignore[method-assign]
    read_task = asyncio.create_task(driver.read_channels())
    await measure_started.wait()

    assert await driver.emergency_off("smua") is True
    release_measure.set()
    await read_task

    positive_writes = [
        command
        for command in transport.writes
        if "smua.source.levelv" in command and not command.rstrip().endswith("= 0")
    ]
    assert positive_writes == []
    assert driver._last_v["smua"] == 0.0
    assert driver._channels["smua"].active is False


async def test_stale_overlapping_off_completion_cannot_clobber_newer_proof() -> None:
    driver, transport = _connected_driver(readbacks=["0"])
    first_read_started = asyncio.Event()
    release_first_read = asyncio.Event()
    query_count = 0
    original_query = transport.query

    async def _reversed_query(command: str, timeout_ms: int | None = None) -> str:
        nonlocal query_count
        if "CRYODAQ_OFF_V1" in command:
            query_count += 1
            if query_count == 1:
                first_read_started.set()
                await release_first_read.wait()
            return _off_reply(command)
        return await original_query(command, timeout_ms)

    transport.query = _reversed_query  # type: ignore[method-assign]
    older = asyncio.create_task(driver.emergency_off("smua"))
    await first_read_started.wait()
    newer = asyncio.create_task(driver.emergency_off("smua"))

    assert await newer is True
    newest_epoch = driver._source_command_epoch["smua"]
    release_first_read.set()
    assert await older is False

    assert driver._output_off_verified["smua"] is True
    assert driver._output_off_verified_generation["smua"] == driver._connection_generation
    assert driver._output_off_verified_epoch["smua"] == newest_epoch
    assert driver._has_current_off_proof("smua") is True
