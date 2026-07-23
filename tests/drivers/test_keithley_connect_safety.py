"""Verify Keithley connect()/emergency_off() safety guards (Phase 2a G.1)."""

from __future__ import annotations

import asyncio
import logging
import re
from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.drivers.instruments.keithley_2604b import (
    FailedConnectCleanupError,
    Keithley2604B,
    OutputStateUnverifiedError,
    TransportTeardownIncompleteError,
)
from cryodaq.drivers.transport.usbtmc import (
    USBTMCFailedOpenError,
    USBTMCIncompleteCloseError,
    USBTMCTransport,
)

_CANONICAL_IDN = "Keithley Instruments Inc., Model 2604B, 04089762, 4.0.8"
_CANONICAL_RESOURCE = "USB0::0x05E6::0x2604::04089762::INSTR"
_OFF_NONCE_RE = re.compile(r"CRYODAQ_OFF_V1\|([0-9a-f]{32})\|%g")


def _off_reply(command: str, state: str = "0") -> str:
    match = _OFF_NONCE_RE.search(command)
    assert match is not None, f"missing strict OFF challenge in {command!r}"
    return f"CRYODAQ_OFF_V1|{match.group(1)}|{state}\n"


def _canonical_query(command: str, timeout_ms: int | None = None) -> str:
    del timeout_ms
    if command == "*IDN?":
        return _CANONICAL_IDN
    if "source.output" in command:
        return _off_reply(command)
    return "0"


def _make_keithley(mock: bool = False) -> Keithley2604B:
    return Keithley2604B(name="test", resource_str=_CANONICAL_RESOURCE, mock=mock)


@pytest.mark.asyncio
async def test_connect_forces_output_off_non_mock():
    """In non-mock mode, connect() must issue OUTPUT_OFF on both SMU channels."""
    k = _make_keithley(mock=False)
    transport = MagicMock()
    transport.open = AsyncMock()
    transport.close = AsyncMock()
    transport.write = AsyncMock()
    transport.query = AsyncMock(side_effect=_canonical_query)
    k._transport = transport

    await k.connect()

    writes = [call.args[0] for call in transport.write.call_args_list]
    assert any("smua.source.output = smua.OUTPUT_OFF" in w for w in writes), (
        f"smua OUTPUT_OFF not issued on connect. Writes: {writes}"
    )
    assert any("smub.source.output = smub.OUTPUT_OFF" in w for w in writes), (
        f"smub OUTPUT_OFF not issued on connect. Writes: {writes}"
    )
    # Also force levelv = 0 before flipping the output
    assert any("smua.source.levelv = 0" in w for w in writes)
    assert any("smub.source.levelv = 0" in w for w in writes)
    assert k._connected is True

    # Ordering check (Phase 2a P2): levelv=0 must come BEFORE OUTPUT_OFF
    # for each channel — flipping output without first dropping the level can
    # produce a brief glitch on some Keithley firmware revisions.
    def _idx(needle: str) -> int:
        for i, w in enumerate(writes):
            if needle in w:
                return i
        raise AssertionError(f"{needle!r} not in writes: {writes}")

    assert _idx("smua.source.levelv = 0") < _idx("smua.source.output = smua.OUTPUT_OFF"), (
        "smua: levelv=0 must precede OUTPUT_OFF"
    )
    assert _idx("smub.source.levelv = 0") < _idx("smub.source.output = smub.OUTPUT_OFF"), (
        "smub: levelv=0 must precede OUTPUT_OFF"
    )


@pytest.mark.asyncio
async def test_connect_skips_force_off_in_mock_mode():
    """Mock mode must skip the force-off path entirely.

    The previous test only asserted _connected=True — mock transport writes
    are silent no-ops, so the assertion was vacuously true even if the
    force-off block ran. Fix: spy the transport's write method and assert
    no OUTPUT_OFF or levelv=0 commands were issued."""
    k = _make_keithley(mock=True)
    written: list[str] = []

    original_write = k._transport.write

    async def _spy_write(cmd: str) -> None:
        written.append(cmd)
        return await original_write(cmd)

    k._transport.write = _spy_write  # type: ignore[method-assign]
    await k.connect()

    assert k._connected is True
    force_off_cmds = [w for w in written if "OUTPUT_OFF" in w or ("levelv" in w and "= 0" in w)]
    assert not force_off_cmds, f"mock mode must NOT issue force-off writes, but saw: {force_off_cmds}"


@pytest.mark.asyncio
async def test_force_off_failure_never_grants_connected_authority(caplog):
    """An unverified OFF retains recovery I/O without returning connect success."""
    caplog.set_level(logging.CRITICAL)
    k = _make_keithley(mock=False)
    transport = MagicMock()
    transport.open = AsyncMock()
    transport.close = AsyncMock()
    transport.query = AsyncMock(side_effect=_canonical_query)

    write_calls = {"n": 0}

    async def write_side_effect(cmd: str) -> None:
        write_calls["n"] += 1
        if "source" in cmd:
            raise OSError("simulated transport failure")

    transport.write = AsyncMock(side_effect=write_side_effect)
    k._transport = transport

    with pytest.raises(OutputStateUnverifiedError, match="retained only for recovery"):
        await k.connect()

    assert k.connected is False
    assert k._recovery_transport_open is True
    assert k._instrument_id == ""
    assert k.output_state_unverified is True
    with pytest.raises(RuntimeError, match="recovery-only transport"):
        await k.start_source("smua", 0.5, 40.0, 1.0)
    with pytest.raises(OutputStateUnverifiedError, match="recovery close refused"):
        await k.disconnect()
    transport.close.assert_not_awaited()
    assert any("connect command failed" in r.message.lower() for r in caplog.records), (
        "CRITICAL log not emitted for force-off failure"
    )

    transport.write = AsyncMock()
    assert await k.emergency_off() is True
    assert k.connected is False
    assert k._instrument_id == ""
    assert k.output_state_unverified is False

    writes_after_recovery = transport.write.await_count
    queries_after_recovery = transport.query.await_count
    with pytest.raises(RuntimeError, match="recovery-only transport"):
        await k.read_channels()
    with pytest.raises(RuntimeError, match="recovery-only transport"):
        await k.read_buffer()
    with pytest.raises(RuntimeError, match="recovery-only transport"):
        await k.check_error()
    with pytest.raises(RuntimeError, match="recovery-only transport"):
        await k.diagnostics()
    with pytest.raises(RuntimeError, match="recovery-only transport"):
        await k.stop_source("smua")
    k._wdog_enabled = True
    k._wdog_armed = True
    with pytest.raises(RuntimeError, match="recovery-only transport"):
        await k._wdog_arm()
    with pytest.raises(RuntimeError, match="recovery-only transport"):
        await k._wdog_pet()
    with pytest.raises(RuntimeError, match="recovery-only transport"):
        await k._wdog_disarm()
    with pytest.raises(RuntimeError, match="recovery transport remains open"):
        await k.connect()
    assert transport.write.await_count == writes_after_recovery
    assert transport.query.await_count == queries_after_recovery

    await k.disconnect()
    transport.close.assert_awaited_once()
    assert k.connected is False
    assert k._recovery_transport_open is False
    assert k._instrument_id == ""


@pytest.mark.asyncio
async def test_configured_identity_and_serial_are_exact():
    matching = _make_keithley(mock=False)
    matching_transport = MagicMock()
    matching_transport.open = AsyncMock()
    matching_transport.close = AsyncMock()
    matching_transport.write = AsyncMock()
    matching_transport.query = AsyncMock(side_effect=_canonical_query)
    matching._transport = matching_transport

    await matching.connect()

    assert matching._instrument_id == _CANONICAL_IDN

    mismatched = Keithley2604B(
        name="test",
        resource_str="USB0::0x05E6::0x2604::DIFFERENT::INSTR",
        mock=False,
    )
    mismatched_transport = MagicMock()
    mismatched_transport.open = AsyncMock()
    mismatched_transport.close = AsyncMock()
    mismatched_transport.write = AsyncMock()
    mismatched_transport.query = AsyncMock(side_effect=_canonical_query)
    mismatched._transport = mismatched_transport

    with pytest.raises(ValueError, match="does not exactly match"):
        await mismatched.connect()

    mismatched_transport.close.assert_awaited_once()
    assert mismatched.connected is False
    assert mismatched._instrument_id == ""

    case_variant = _make_keithley(mock=False)
    case_variant_transport = MagicMock()
    case_variant_transport.open = AsyncMock()
    case_variant_transport.close = AsyncMock()
    case_variant_transport.write = AsyncMock()
    case_variant_transport.query = AsyncMock(return_value="keithley instruments inc., Model 2604B, 04089762, 4.0.8")
    case_variant._transport = case_variant_transport

    with pytest.raises(ValueError, match="manufacturer"):
        await case_variant.connect()

    case_variant_transport.write.assert_not_awaited()
    case_variant_transport.close.assert_awaited_once()
    assert case_variant._instrument_id == ""

    for invalid_resource in (
        "USB0::0x05E7::0x2604::04089762::INSTR",
        "USB0::0x05E6::0x2605::04089762::INSTR",
        "USB0::0x05E6::0x2604::INSTR",
        "TCPIP0::04089762::INSTR",
    ):
        invalid = Keithley2604B(name="test", resource_str=invalid_resource, mock=False)
        invalid._instrument_id = "stale-authority"
        invalid_transport = MagicMock()
        invalid_transport.open = AsyncMock()
        invalid._transport = invalid_transport

        with pytest.raises(ValueError):
            await invalid.connect()

        invalid_transport.open.assert_not_awaited()
        assert invalid._instrument_id == ""


@pytest.mark.asyncio
async def test_invalid_identity_with_unverified_off_returns_explicit_recovery_receipt_without_connected_authority():
    k = _make_keithley(mock=False)
    transport = MagicMock()
    transport.open = AsyncMock()
    transport.close = AsyncMock()
    transport.write = AsyncMock()

    def _query(command: str, timeout_ms: int | None = None) -> str:
        del timeout_ms
        if command == "*IDN?":
            return "Keithley Instruments Inc., Model 2604B, WRONG-SERIAL, 4.0.8"
        return _off_reply(command, "1")

    transport.query = AsyncMock(side_effect=_query)
    k._transport = transport

    with pytest.raises(OutputStateUnverifiedError, match="connected authority was not granted") as exc_info:
        await k.connect()

    assert isinstance(exc_info.value.__cause__, ValueError)
    assert "does not exactly match" in str(exc_info.value.__cause__)
    assert k.connected is False
    assert k._recovery_transport_open is True
    assert k._instrument_id == ""
    assert k.output_state_unverified is True
    transport.close.assert_not_awaited()


@pytest.mark.asyncio
async def test_recovery_close_failure_remains_disconnected_and_blocks_reconnect():
    k = _make_keithley(mock=False)
    transport = MagicMock()
    transport.open = AsyncMock()
    transport.close = AsyncMock(side_effect=USBTMCIncompleteCloseError("retained recovery handle"))
    transport.write = AsyncMock(side_effect=OSError("initial OFF failed"))
    transport.query = AsyncMock(side_effect=_canonical_query)
    k._transport = transport

    with pytest.raises(OutputStateUnverifiedError, match="retained only for recovery"):
        await k.connect()

    transport.write = AsyncMock()
    assert await k.emergency_off() is True
    with pytest.raises(TransportTeardownIncompleteError, match="teardown is incomplete"):
        await k.disconnect()

    assert k.connected is False
    assert k._recovery_transport_open is True
    assert k._instrument_id == ""
    assert k._teardown_incomplete is True
    with pytest.raises(TransportTeardownIncompleteError, match="reconnect remains blocked"):
        await k.connect()
    assert transport.close.await_count == 2


@pytest.mark.asyncio
async def test_emergency_off_verifies_readback_both_channels():
    """emergency_off must readback source.output on both SMU channels."""
    k = _make_keithley(mock=False)
    transport = MagicMock()
    transport.write = AsyncMock()
    transport.query = AsyncMock(side_effect=lambda command, timeout_ms=None: _off_reply(command))
    k._transport = transport
    k._connected = True

    await k.emergency_off()

    queries = [call.args[0] for call in transport.query.call_args_list]
    assert any("smua.source.output" in q and "CRYODAQ_OFF_V1" in q for q in queries), (
        f"smua output readback missing. Queries: {queries}"
    )
    assert any("smub.source.output" in q and "CRYODAQ_OFF_V1" in q for q in queries), (
        f"smub output readback missing. Queries: {queries}"
    )


@pytest.mark.asyncio
async def test_emergency_off_logs_critical_on_verify_failure(caplog):
    """If readback shows output still on, log CRITICAL and do not raise."""
    caplog.set_level(logging.CRITICAL)
    k = _make_keithley(mock=False)
    transport = MagicMock()
    transport.write = AsyncMock()
    transport.query = AsyncMock(side_effect=lambda command, timeout_ms=None: _off_reply(command, "1"))
    k._transport = transport
    k._connected = True

    # Must NOT raise — we are already in an emergency path.
    await k.emergency_off()

    relevant = [
        r for r in caplog.records if "did not report literal state 0" in r.message or "readback failed" in r.message
    ]
    assert relevant, f"no CRITICAL log emitted on verify failure. records: {[r.message for r in caplog.records]}"


@pytest.mark.asyncio
async def test_emergency_off_handles_query_exception(caplog):
    """Verify-readback exceptions are logged CRITICAL but do not propagate."""
    caplog.set_level(logging.CRITICAL)
    k = _make_keithley(mock=False)
    transport = MagicMock()
    transport.write = AsyncMock()
    transport.query = AsyncMock(side_effect=OSError("transport down"))
    k._transport = transport
    k._connected = True

    await k.emergency_off()  # must not raise

    # CRITICAL log MUST be emitted (Phase 2a P2 — was missing).
    relevant = [r for r in caplog.records if "readback failed" in r.message or "invalid off challenge" in r.message]
    assert relevant, f"No CRITICAL log emitted on query exception. records: {[r.message for r in caplog.records]}"


# ---------------------------------------------------------------------------
# CR-2: emergency_off must REPORT success/failure so callers can fail closed.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emergency_off_returns_true_on_clean_off():
    """Writes succeed and readback confirms OFF on both channels → True."""
    k = _make_keithley(mock=False)
    transport = MagicMock()
    transport.write = AsyncMock()
    transport.query = AsyncMock(side_effect=lambda command, timeout_ms=None: _off_reply(command))
    k._transport = transport
    k._connected = True

    assert await k.emergency_off() is True


@pytest.mark.asyncio
async def test_emergency_off_returns_true_in_mock_mode():
    k = _make_keithley(mock=True)
    assert await k.emergency_off() is True


@pytest.mark.asyncio
async def test_emergency_off_fails_closed_when_output_off_write_raises():
    """An ambiguous OFF write cannot report verified-OFF success."""
    k = _make_keithley(mock=False)
    transport = MagicMock()

    async def write_side_effect(cmd: str) -> None:
        if "OUTPUT_OFF" in cmd:
            raise OSError("transport hiccup")

    transport.write = AsyncMock(side_effect=write_side_effect)
    transport.query = AsyncMock(side_effect=lambda command, timeout_ms=None: _off_reply(command))
    k._transport = transport
    k._connected = True

    assert await k.emergency_off() is False


@pytest.mark.asyncio
async def test_emergency_off_single_channel_uses_exact_quarantine_recovery_traffic(monkeypatch):
    import cryodaq.drivers.transport.usbtmc as usbtmc_module
    from tests.drivers.test_usbtmc_process_protocol import _owner, _response

    nonce = "d" * 32
    challenge = f'print(string.format("CRYODAQ_OFF_V1|{nonce}|%g", smua.source.output))'
    owner, connection, _process = _owner(
        incoming=[
            _response("query", status="error", payload={"code": "VISA_QUERY_FAILED"}),
            _response("write", sequence=1),
            _response("write", sequence=2),
            _response("query", sequence=3, payload={"text": f"CRYODAQ_OFF_V1|{nonce}|0"}),
        ]
    )
    transport = USBTMCTransport(mock=False)
    transport._process_owner = owner
    transport._resource = usbtmc_module._ProcessHandleToken(1, "resource")
    transport._rm = usbtmc_module._ProcessHandleToken(1, "manager")
    with pytest.raises(usbtmc_module.USBTMCRemoteOperationError):
        await transport.query("poison-query")

    k = _make_keithley(mock=False)
    k._transport = transport
    k._connected = True
    monkeypatch.setattr("cryodaq.drivers.instruments.keithley_2604b.secrets.token_hex", lambda _size: nonce)

    assert await k.emergency_off("smua") is True
    requests = [usbtmc_module._decode_ipc_frame(frame) for frame in connection.sent]
    assert [request["operation"] for request in requests] == ["query", "write", "write", "query"]
    assert [request["payload"] for request in requests[1:3]] == [
        {"command": "smua.source.levelv = 0"},
        {"command": "smua.source.output = smua.OUTPUT_OFF"},
    ]
    assert requests[3]["payload"]["command"] == challenge


@pytest.mark.asyncio
async def test_live_query_desynchronization_demotes_to_same_handle_recovery() -> None:
    """A production USBTMC quarantine can recover OFF but can never reopen in place."""

    transport = USBTMCTransport(mock=True)
    await transport.open(_CANONICAL_RESOURCE)
    original_mock_response = transport._mock_response
    desynchronized = False

    def _desynchronize_active_measurement(command: str) -> str:
        nonlocal desynchronized
        if command == "print(smua.measure.iv())" and not desynchronized:
            desynchronized = True
            raise RuntimeError("production-shaped query frame lost")
        return original_mock_response(command)

    transport._mock_response = _desynchronize_active_measurement
    open_spy = AsyncMock(side_effect=AssertionError("replacement open must not run"))
    close_spy = AsyncMock(wraps=transport.close)
    write_spy = AsyncMock(wraps=transport.write)
    transport.open = open_spy
    transport.close = close_spy
    transport.write = write_spy

    k = _make_keithley(mock=False)
    k._transport = transport
    k._connected = True
    k._instrument_id = _CANONICAL_IDN
    k._channels["smua"].active = True
    k._channels["smua"].p_target = 0.5
    k._source_regulation_epoch["smua"] = k._source_command_epoch["smua"]

    with pytest.raises(RuntimeError, match="query frame lost"):
        await k.read_channels()

    assert transport._query_desynchronized is True
    assert k.connected is False
    assert k._recovery_transport_open is True
    assert k._instrument_id == ""
    assert k.output_state_unverified is True
    assert k._channels["smua"].active is True
    with pytest.raises(RuntimeError, match="recovery transport remains open"):
        await k.connect()
    open_spy.assert_not_awaited()
    close_spy.assert_not_awaited()

    assert await k.emergency_off() is True
    assert k.connected is False
    assert k._recovery_transport_open is True
    assert k.output_state_unverified is False
    assert not any("OUTPUT_ON" in call.args[0] for call in write_spy.await_args_list)

    await k.disconnect()
    close_spy.assert_awaited_once()
    open_spy.assert_not_awaited()
    assert k.connected is False
    assert k._recovery_transport_open is False


@pytest.mark.asyncio
async def test_connected_without_exact_identity_demotes_before_any_ordinary_query() -> None:
    k = _make_keithley(mock=False)
    transport = MagicMock()
    transport.open = AsyncMock()
    transport.close = AsyncMock()
    transport.write = AsyncMock()
    transport.query = AsyncMock(side_effect=_canonical_query)
    k._transport = transport
    await k.connect()
    queries_before = transport.query.await_count
    k._instrument_id = ""

    with pytest.raises(OutputStateUnverifiedError, match="exact connected identity authority"):
        await k.read_channels()

    assert transport.query.await_count == queries_before
    assert k.connected is False
    assert k._recovery_transport_open is True
    assert k._instrument_id == ""
    assert k.output_state_unverified is True
    assert await k.emergency_off() is True
    await k.disconnect()


@pytest.mark.asyncio
async def test_queued_source_rechecks_authority_after_failing_ordinary_write() -> None:
    k = _make_keithley(mock=False)
    transport = MagicMock()
    transport.open = AsyncMock()
    transport.close = AsyncMock()
    transport.write = AsyncMock()
    transport.query = AsyncMock(side_effect=_canonical_query)
    k._transport = transport
    await k.connect()
    await k.start_source("smua", 0.5, 40.0, 1.0)

    write_entered = asyncio.Event()
    release_write = asyncio.Event()
    writes: list[str] = []

    async def _blocked_then_failed_write(command: str) -> None:
        writes.append(command)
        if command == "smua.source.limitv = 20.0":
            write_entered.set()
            await release_write.wait()
            raise OSError("ordinary limit write lost completion")

    transport.write = AsyncMock(side_effect=_blocked_then_failed_write)
    update = asyncio.create_task(k.update_source_limit("smua", v_comp=20.0))
    await write_entered.wait()
    queued_start = asyncio.create_task(k.start_source("smub", 0.5, 40.0, 1.0))
    await asyncio.sleep(0)
    release_write.set()

    with pytest.raises(OSError, match="lost completion"):
        await update
    with pytest.raises(RuntimeError, match="recovery-only transport"):
        await queued_start

    assert k.connected is False
    assert k._recovery_transport_open is True
    assert k._instrument_id == ""
    assert k.output_state_unverified is True
    assert not any("OUTPUT_ON" in command for command in writes)

    assert await k.emergency_off() is True
    await k.disconnect()


@pytest.mark.asyncio
async def test_queued_limit_write_rechecks_after_emergency_off_preclaim() -> None:
    k = _make_keithley(mock=False)
    transport = MagicMock()
    transport.open = AsyncMock()
    transport.close = AsyncMock()
    transport.write = AsyncMock()
    transport.query = AsyncMock(side_effect=_canonical_query)
    k._transport = transport
    await k.connect()
    await k.start_source("smua", 0.5, 40.0, 1.0)
    original_limit = k._channels["smua"].v_comp

    hold_entered = asyncio.Event()
    release_hold = asyncio.Event()

    async def _blocking_query(command: str, timeout_ms: int | None = None) -> str:
        if command == "hold-limit-queue":
            hold_entered.set()
            await release_hold.wait()
            return "0"
        return _canonical_query(command, timeout_ms)

    writes: list[str] = []

    async def _record_write(command: str) -> None:
        writes.append(command)

    transport.query = AsyncMock(side_effect=_blocking_query)
    transport.write = AsyncMock(side_effect=_record_write)
    hold = asyncio.create_task(k._operational_query("hold-limit-queue"))
    await hold_entered.wait()

    limit_queued = asyncio.Event()
    original_operational_write = k._operational_write

    async def _observe_limit_queue(command: str, *, authority_check=None) -> None:
        if command == "smua.source.limitv = 20.0":
            limit_queued.set()
        await original_operational_write(command, authority_check=authority_check)

    k._operational_write = _observe_limit_queue  # type: ignore[method-assign]
    update = asyncio.create_task(k.update_source_limit("smua", v_comp=20.0))
    await limit_queued.wait()
    assert update.done() is False

    assert await k.emergency_off("smua") is True
    release_hold.set()
    await hold
    with pytest.raises(RuntimeError, match="regulation was superseded"):
        await update

    assert not any(command == "smua.source.limitv = 20.0" for command in writes)
    assert k._channels["smua"].v_comp == original_limit
    assert k._channels["smua"].active is False
    assert k._has_current_off_proof("smua") is True
    await k.disconnect()


@pytest.mark.asyncio
async def test_best_effort_watchdog_query_desync_never_publishes_connected_authority() -> None:
    transport = USBTMCTransport(mock=True)
    original_mock_response = transport._mock_response

    def _watchdog_desync(command: str) -> str:
        if command == "*IDN?":
            return _CANONICAL_IDN
        if command == "print(cryodaq_wdog_tripped)":
            raise RuntimeError("watchdog query frame lost")
        return original_mock_response(command)

    transport._mock_response = _watchdog_desync
    close_spy = AsyncMock(wraps=transport.close)
    transport.close = close_spy
    k = Keithley2604B(
        name="test",
        resource_str=_CANONICAL_RESOURCE,
        mock=False,
        watchdog_mode="best_effort",
    )
    k._transport = transport

    with pytest.raises(RuntimeError, match="watchdog query invalidated transport authority"):
        await k.connect()

    close_spy.assert_awaited_once()
    assert k.connected is False
    assert k._recovery_transport_open is False
    assert k._instrument_id == ""
    assert k._wdog_armed is False
    assert transport._query_desynchronized is True


@pytest.mark.asyncio
async def test_incomplete_transport_close_blocks_keithley_disconnect_and_reconnect() -> None:
    k = _make_keithley(mock=False)
    transport = MagicMock()
    transport.close = AsyncMock(side_effect=USBTMCIncompleteCloseError("retained handle is unsettled"))
    transport.open = AsyncMock()
    transport.query = AsyncMock()
    transport.write = AsyncMock()
    k._transport = transport
    k._connected = True
    k._instrument_id = _CANONICAL_IDN
    k._output_off_verified = {"smua": True, "smub": True}
    k._output_off_verified_generation = {
        "smua": k._connection_generation,
        "smub": k._connection_generation,
    }
    k._output_off_verified_epoch = {
        "smua": k._source_command_epoch["smua"],
        "smub": k._source_command_epoch["smub"],
    }

    with pytest.raises(TransportTeardownIncompleteError, match="teardown is incomplete"):
        await k.disconnect()

    assert k.connected is False
    assert k._recovery_transport_open is True
    assert k._instrument_id == ""
    assert k._teardown_incomplete is True
    with pytest.raises(TransportTeardownIncompleteError, match="reconnect remains blocked"):
        await k.connect()
    assert transport.close.await_count == 2
    transport.open.assert_not_awaited()
    blocked_operations = (
        lambda: k.read_channels(),
        lambda: k.start_source("smua", 0.5, 40.0, 1.0),
        lambda: k.stop_source("smua"),
        lambda: k.emergency_off(),
        lambda: k.read_buffer(),
        lambda: k.check_error(),
        lambda: k.diagnostics(),
        lambda: k._wdog_arm(),
        lambda: k._wdog_pet(),
        lambda: k._wdog_disarm(),
        lambda: k.acknowledge_wdog_trip(),
        lambda: k.wdog_tripped(),
    )
    for operation in blocked_operations:
        with pytest.raises(TransportTeardownIncompleteError, match="teardown remains incomplete"):
            await operation()
    transport.query.assert_not_awaited()
    transport.write.assert_not_awaited()


@pytest.mark.asyncio
async def test_late_close_success_requires_fresh_identity_off_and_watchdog_before_reconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.drivers.transport.usbtmc as usbtmc_module
    from tests.drivers.test_usbtmc_process_protocol import _owner, _Process

    events: list[str] = []
    process = _Process(refuse_terminate=True, refuse_kill=True)
    owner, connection, _process = _owner(process=process)
    owner.close_command_sent = True
    owner.close_receipt = {"resource_error": None, "manager_error": None}
    transport = USBTMCTransport(mock=False)
    transport._resource_str = _CANONICAL_RESOURCE
    transport._process_owner = owner
    transport._resource = usbtmc_module._ProcessHandleToken(1, "resource")
    transport._rm = usbtmc_module._ProcessHandleToken(1, "manager")
    k = Keithley2604B(
        name="test",
        resource_str=_CANONICAL_RESOURCE,
        mock=False,
        watchdog_mode="best_effort",
    )
    k._transport = transport
    k._connected = True
    k._instrument_id = _CANONICAL_IDN
    k._mark_channel_off_verified("smua")
    k._mark_channel_off_verified("smub")

    with pytest.raises(TransportTeardownIncompleteError, match="teardown is incomplete"):
        await k.disconnect()
    assert k._teardown_incomplete is True
    assert k._teardown_can_settle is True
    assert transport._process_owner is owner
    assert connection.sent == []

    watchdog_active = False

    async def _fresh_open(_resource: str) -> None:
        events.append("fresh-open")

    async def _fresh_write(command: str) -> None:
        nonlocal watchdog_active
        events.append(f"write:{command}")
        if command == "cryodaq_wdog_run()":
            watchdog_active = True

    async def _fresh_query(command: str, timeout_ms: int | None = None) -> str:
        del timeout_ms
        events.append(f"query:{command}")
        if command == "*IDN?":
            return _CANONICAL_IDN
        if "source.output" in command:
            return _off_reply(command)
        if command == "print(CRYODAQ_WDOG_VERSION)":
            return "3"
        if command == "print(cryodaq_wdog_autonomous)":
            return "0"
        if command == "print(cryodaq_wdog_active)":
            return "1" if watchdog_active else "0"
        if command == "print(cryodaq_wdog_tripped)":
            return "0"
        return "0"

    original_close = transport.close

    async def _settle_then_switch() -> None:
        await original_close()
        transport.open = _fresh_open  # type: ignore[method-assign]
        transport.write = _fresh_write  # type: ignore[method-assign]
        transport.query = _fresh_query  # type: ignore[method-assign]

    transport.close = _settle_then_switch  # type: ignore[method-assign]
    process.refuse_terminate = False
    await k.connect()

    assert connection.sent == []
    assert process.terminate_calls >= 2
    assert events[0] == "fresh-open"
    assert k.connected is True
    assert k._instrument_id == _CANONICAL_IDN
    assert k._has_current_off_proof("smua") is True
    assert k._has_current_off_proof("smub") is True
    assert k._wdog_armed is True
    assert k._teardown_incomplete is False
    assert k._teardown_can_settle is False


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled", [False, True], ids=["error", "cancellation"])
@pytest.mark.parametrize("typed_cleanup", [False, True], ids=["generic-close", "typed-close"])
async def test_any_failed_connect_cleanup_close_sets_terminal_barrier_and_preserves_cause(
    cancelled: bool,
    typed_cleanup: bool,
) -> None:
    k = _make_keithley(mock=False)
    original: BaseException
    if cancelled:
        original = asyncio.CancelledError("original connect cancellation")
    else:
        original = OSError("original open failure")
    cleanup_failure: BaseException
    if typed_cleanup:
        terminal_close = OSError("physical cleanup close failed")
        cleanup_failure = USBTMCIncompleteCloseError(
            "typed cleanup close failure",
            settled=True,
            terminal_error=terminal_close,
        )
    else:
        cleanup_failure = RuntimeError("generic cleanup close failure")
    transport = MagicMock()
    transport.open = AsyncMock(side_effect=original)
    transport.close = AsyncMock(side_effect=cleanup_failure)
    transport.query = AsyncMock()
    transport.write = AsyncMock()
    k._transport = transport

    if cancelled:
        with pytest.raises(asyncio.CancelledError, match="original") as exc_info:
            await k.connect()
        assert exc_info.value is original
        combined = exc_info.value.__cause__
    else:
        with pytest.raises(FailedConnectCleanupError) as exc_info:
            await k.connect()
        combined = exc_info.value

    assert isinstance(combined, FailedConnectCleanupError)
    assert combined.connect_error is original
    assert isinstance(combined.cleanup_error, TransportTeardownIncompleteError)
    assert combined.cleanup_error.__cause__ is cleanup_failure

    assert k.connected is False
    assert k._recovery_transport_open is False
    assert k._teardown_incomplete is True
    with pytest.raises(TransportTeardownIncompleteError, match="reconnect refused"):
        await k.connect()
    transport.open.assert_awaited_once()
    transport.close.assert_awaited_once()
    transport.query.assert_not_awaited()
    transport.write.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_identity_cleanup_exposes_identity_and_close_failures() -> None:
    k = _make_keithley(mock=False)
    cleanup_failure = RuntimeError("identity cleanup close failed")
    transport = MagicMock()
    transport.open = AsyncMock()
    transport.query = AsyncMock(
        return_value="Unexpected Vendor, Model 2604B, 04089762, 4.0.8",
    )
    transport.write = AsyncMock()
    transport.close = AsyncMock(side_effect=cleanup_failure)
    k._transport = transport

    with pytest.raises(FailedConnectCleanupError) as exc_info:
        await k.connect()

    failure = exc_info.value
    assert isinstance(failure.connect_error, ValueError)
    assert "manufacturer" in str(failure.connect_error)
    assert failure.cleanup_error.__cause__ is cleanup_failure
    assert failure.__cause__ is failure.cleanup_error
    assert k.connected is False
    assert k._instrument_id == ""
    assert k._teardown_incomplete is True
    assert k._teardown_can_settle is False
    transport.open.assert_awaited_once()
    transport.query.assert_awaited_once_with("*IDN?")
    transport.write.assert_not_awaited()
    transport.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_usbtmc_open_preserves_exact_primary_and_manager_cleanup_through_keithley() -> None:
    k = _make_keithley(mock=False)
    primary_error = OSError("exact native open failure")
    manager_cleanup_error = RuntimeError("exact resource-manager cleanup failure")
    failed_open = USBTMCFailedOpenError(
        primary_error=primary_error,
        cleanup_error=manager_cleanup_error,
    )
    failed_open.__cause__ = primary_error
    transport_failure = USBTMCIncompleteCloseError(
        "typed failed-open settlement",
        settled=True,
        terminal_error=failed_open,
        primary_error=primary_error,
        cleanup_error=manager_cleanup_error,
    )
    transport_failure.__cause__ = failed_open
    transport = MagicMock()
    transport.open = AsyncMock(side_effect=transport_failure)
    transport.close = AsyncMock(side_effect=transport_failure)
    transport.query = AsyncMock()
    transport.write = AsyncMock()
    k._transport = transport

    with pytest.raises(FailedConnectCleanupError) as exc_info:
        await k.connect()

    combined = exc_info.value
    assert combined.connect_error is primary_error
    assert combined.cleanup_error.__cause__ is manager_cleanup_error
    assert combined.__cause__ is combined.cleanup_error
    assert transport_failure.primary_error is primary_error
    assert transport_failure.cleanup_error is manager_cleanup_error
    assert transport_failure.terminal_error is failed_open
    assert failed_open.primary_error is primary_error
    assert failed_open.cleanup_error is manager_cleanup_error
    assert failed_open.__cause__ is primary_error
    assert k.connected is False
    assert k._teardown_incomplete is True
    transport.open.assert_awaited_once()
    transport.close.assert_awaited_once()
    transport.query.assert_not_awaited()
    transport.write.assert_not_awaited()


@pytest.mark.asyncio
async def test_real_usbtmc_failed_open_chain_reaches_keithley_without_identity_loss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.drivers.transport.usbtmc as usbtmc_module
    from tests.drivers.test_usbtmc_process_protocol import _Connection, _Process, _response

    connection = _Connection(
        [
            _response(
                "open",
                status="error",
                payload={
                    "cleanup_code": "VISA_MANAGER_CLOSE_FAILED",
                    "code": "VISA_OPEN_FAILED",
                },
            )
        ]
    )
    process = _Process()

    class ChildConnection:
        def close(self) -> None:
            return None

    class Context:
        def Pipe(self, *, duplex: bool):
            assert duplex is True
            return connection, ChildConnection()

        def Process(self, **kwargs):
            assert kwargs["target"] is usbtmc_module._visa_process_main
            return process

    monkeypatch.setattr(usbtmc_module.multiprocessing, "get_context", lambda _method: Context())
    k = _make_keithley(mock=False)
    transport = USBTMCTransport(mock=False)
    k._transport = transport

    with pytest.raises(FailedConnectCleanupError) as exc_info:
        await k.connect()

    combined = exc_info.value
    assert isinstance(combined.connect_error, usbtmc_module.USBTMCRemoteOperationError)
    assert combined.connect_error.error_code == "VISA_OPEN_FAILED"
    assert isinstance(combined.cleanup_error, TransportTeardownIncompleteError)
    cleanup_cause = combined.cleanup_error.__cause__
    assert isinstance(cleanup_cause, usbtmc_module.USBTMCRemoteOperationError)
    assert cleanup_cause.error_code == "VISA_MANAGER_CLOSE_FAILED"
    terminal = transport._close_terminal_error
    assert isinstance(terminal, usbtmc_module.USBTMCFailedOpenError)
    assert terminal.primary_error.error_code == "VISA_OPEN_FAILED"
    assert terminal.cleanup_error.error_code == "VISA_MANAGER_CLOSE_FAILED"
    assert "VISA_OPEN_FAILED" not in str(combined)
    assert transport._close_incomplete is True
    assert transport._close_settled is True
    assert transport._resource is None
    assert transport._rm is None
    assert transport._process_owner is None


@pytest.mark.asyncio
async def test_emergency_off_returns_false_when_readback_still_on():
    """Readback reports output=1 after OUTPUT_OFF → False."""
    k = _make_keithley(mock=False)
    transport = MagicMock()
    transport.write = AsyncMock()
    transport.query = AsyncMock(side_effect=lambda command, timeout_ms=None: _off_reply(command, "1"))
    k._transport = transport
    k._connected = True

    assert await k.emergency_off() is False


@pytest.mark.asyncio
async def test_emergency_off_returns_false_on_verify_query_exception():
    """Readback query raising means OFF is unconfirmed → False (no raise)."""
    k = _make_keithley(mock=False)
    transport = MagicMock()
    transport.write = AsyncMock()
    transport.query = AsyncMock(side_effect=OSError("transport down"))
    k._transport = transport
    k._connected = True

    assert await k.emergency_off() is False


@pytest.mark.asyncio
async def test_emergency_off_single_channel_failure_returns_false():
    """emergency_off(None) targets both channels; ONE stuck channel → False."""
    k = _make_keithley(mock=False)
    transport = MagicMock()
    transport.write = AsyncMock()

    async def query_side_effect(cmd: str, timeout_ms: int | None = None) -> str:
        if "smub" in cmd:
            return _off_reply(cmd, "1")  # smub still ON
        return _off_reply(cmd)

    transport.query = AsyncMock(side_effect=query_side_effect)
    k._transport = transport
    k._connected = True

    assert await k.emergency_off() is False


@pytest.mark.asyncio
async def test_verify_output_off_returns_bool_per_readback():
    """_verify_output_off: True iff readback confirms OFF; False on
    still-on ('1', '1.0e+00') or unparseable responses."""
    k = _make_keithley(mock=False)
    transport = MagicMock()
    transport.write = AsyncMock()
    k._transport = transport
    k._connected = True

    for state, expected in [
        ("0", True),
        ("1", False),
        ("2", False),
        ("garbage", False),
    ]:
        transport.query = AsyncMock(
            side_effect=lambda command, timeout_ms=None, state=state: _off_reply(command, state)
        )
        assert await k._verify_output_off("smua") is expected, f"readback state {state!r} must yield {expected}"


@pytest.mark.asyncio
async def test_prior_process_nonce_replay_cannot_prove_off(monkeypatch):
    k = _make_keithley(mock=False)
    transport = MagicMock()
    transport.write = AsyncMock()
    transport.query = AsyncMock(return_value=f"CRYODAQ_OFF_V1|{'1' * 32}|0\n")
    k._transport = transport
    k._connected = True
    monkeypatch.setattr(
        "cryodaq.drivers.instruments.keithley_2604b.secrets.token_hex",
        lambda _size: "2" * 32,
    )

    assert await k._verify_output_off("smua") is False


@pytest.mark.asyncio
async def test_one_behind_stale_queue_never_proves_off(monkeypatch):
    current_nonces = iter(["2" * 32, "3" * 32, "4" * 32])
    stale_nonces = iter(["1" * 32, "2" * 32, "3" * 32])
    k = _make_keithley(mock=False)
    transport = MagicMock()
    transport.write = AsyncMock()
    transport.query = AsyncMock(side_effect=lambda command, timeout_ms=None: f"CRYODAQ_OFF_V1|{next(stale_nonces)}|0\n")
    k._transport = transport
    k._connected = True
    monkeypatch.setattr(
        "cryodaq.drivers.instruments.keithley_2604b.secrets.token_hex",
        lambda _size: next(current_nonces),
    )

    assert [await k._verify_output_off("smua") for _ in range(3)] == [False, False, False]


@pytest.mark.asyncio
async def test_each_off_proof_query_uses_a_unique_nonce():
    k = _make_keithley(mock=False)
    transport = MagicMock()
    transport.write = AsyncMock()
    observed: list[str] = []

    def _query(command: str, timeout_ms: int | None = None) -> str:
        del timeout_ms
        match = _OFF_NONCE_RE.search(command)
        assert match is not None
        observed.append(match.group(1))
        return _off_reply(command)

    transport.query = AsyncMock(side_effect=_query)
    k._transport = transport
    k._connected = True

    assert await k._verify_output_off("smua") is True
    assert await k._verify_output_off("smua") is True
    assert len(set(observed)) == 2


@pytest.mark.asyncio
async def test_bare_legacy_zero_cannot_prove_off():
    k = _make_keithley(mock=False)
    transport = MagicMock()
    transport.write = AsyncMock()
    transport.query = AsyncMock(return_value="0\n")
    k._transport = transport
    k._connected = True

    assert await k._verify_output_off("smua") is False


@pytest.mark.asyncio
async def test_legacy_vendor_substring_gets_zero_tsp_writes():
    k = _make_keithley(mock=False)
    transport = MagicMock()
    transport.open = AsyncMock()
    transport.close = AsyncMock()
    transport.write = AsyncMock()
    transport.query = AsyncMock(return_value="KEITHLEY INSTRUMENTS,MODEL 2604B,FAKE,1.0")
    k._transport = transport

    with pytest.raises(ValueError, match="manufacturer"):
        await k.connect()

    transport.write.assert_not_awaited()
    transport.close.assert_awaited_once()
    assert k.connected is False
    assert k._instrument_id == ""


@pytest.mark.asyncio
async def test_bad_serial_after_exact_off_closes_without_publishing_identity():
    k = _make_keithley(mock=False)
    transport = MagicMock()
    transport.open = AsyncMock()
    transport.close = AsyncMock()
    transport.write = AsyncMock()

    def _query(command: str, timeout_ms: int | None = None) -> str:
        del timeout_ms
        if command == "*IDN?":
            return "Keithley Instruments Inc., Model 2604B, , 4.0.8"
        return _off_reply(command)

    transport.query = AsyncMock(side_effect=_query)
    k._transport = transport

    with pytest.raises(ValueError, match="serial"):
        await k.connect()

    transport.close.assert_awaited_once()
    assert k.connected is False
    assert k._instrument_id == ""


@pytest.mark.asyncio
async def test_bad_serial_with_unverified_off_retains_recovery_without_identity():
    k = _make_keithley(mock=False)
    transport = MagicMock()
    transport.open = AsyncMock()
    transport.close = AsyncMock()
    transport.write = AsyncMock()

    def _query(command: str, timeout_ms: int | None = None) -> str:
        del timeout_ms
        if command == "*IDN?":
            return "Keithley Instruments Inc., Model 2604B, , 4.0.8"
        return _off_reply(command, "1")

    transport.query = AsyncMock(side_effect=_query)
    k._transport = transport

    with pytest.raises(OutputStateUnverifiedError, match="retained only for recovery") as exc_info:
        await k.connect()

    assert isinstance(exc_info.value.__cause__, ValueError)
    assert "serial" in str(exc_info.value.__cause__)
    transport.close.assert_not_awaited()
    assert k.connected is False
    assert k._recovery_transport_open is True
    assert k._instrument_id == ""
    assert k.output_state_unverified is True
