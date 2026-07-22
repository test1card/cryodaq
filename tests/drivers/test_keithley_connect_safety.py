"""Verify Keithley connect()/emergency_off() safety guards (Phase 2a G.1)."""

from __future__ import annotations

import logging
import re
from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.drivers.instruments.keithley_2604b import (
    Keithley2604B,
    TransportTeardownIncompleteError,
)
from cryodaq.drivers.transport.usbtmc import USBTMCIncompleteCloseError

_CANONICAL_IDN = "Keithley Instruments Inc., Model 2604B, 04089762, 4.0.8"
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
    return Keithley2604B(name="test", resource_str="USB0::fake", mock=mock)


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
async def test_connect_does_not_fail_on_force_off_error(caplog):
    """If the force-off write raises, connect() logs CRITICAL but still succeeds.

    The principle is: a sourcing instrument we cannot talk to is the worst
    state. We never want to abort connect over the safety guard — the higher
    level health checks will catch a truly broken transport.
    """
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

    await k.connect()

    assert k._connected is True, "connect must succeed even if force-off failed"
    assert any("connect command failed" in r.message.lower() for r in caplog.records), (
        "CRITICAL log not emitted for force-off failure"
    )


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
    from cryodaq.drivers.transport.usbtmc import USBTMCTransport

    writes: list[str] = []
    queries: list[str] = []
    nonce = "d" * 32

    class _Resource:
        timeout = 0

        def query(self, command: str) -> str:
            queries.append(command)
            if command == "poison-query":
                raise OSError("USBTMC response framing lost")
            assert command == f'print(string.format("CRYODAQ_OFF_V1|{nonce}|%g", smua.source.output))'
            return f"CRYODAQ_OFF_V1|{nonce}|0\n"

        def write(self, command: str) -> None:
            writes.append(command)

        def close(self) -> None:
            return None

    class _Manager:
        def close(self) -> None:
            return None

    transport = USBTMCTransport(mock=False)
    transport._resource = _Resource()
    transport._rm = _Manager()
    with pytest.raises(OSError, match="framing lost"):
        await transport.query("poison-query")

    k = _make_keithley(mock=False)
    k._transport = transport
    k._connected = True
    monkeypatch.setattr("cryodaq.drivers.instruments.keithley_2604b.secrets.token_hex", lambda _size: nonce)

    assert await k.emergency_off("smua") is True
    assert writes == [
        "smua.source.levelv = 0",
        "smua.source.output = smua.OUTPUT_OFF",
    ]
    assert queries == [
        "poison-query",
        f'print(string.format("CRYODAQ_OFF_V1|{nonce}|%g", smua.source.output))',
    ]
    await transport.close()


@pytest.mark.asyncio
async def test_incomplete_transport_close_blocks_keithley_disconnect_and_reconnect() -> None:
    k = _make_keithley(mock=False)
    transport = MagicMock()
    transport.close = AsyncMock(side_effect=USBTMCIncompleteCloseError("retained handle is unsettled"))
    transport.open = AsyncMock()
    k._transport = transport
    k._connected = True
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

    assert k.connected is True
    assert k._teardown_incomplete is True
    with pytest.raises(TransportTeardownIncompleteError, match="reconnect refused"):
        await k.connect()
    transport.open.assert_not_awaited()


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

    with pytest.raises(ValueError, match="serial"):
        await k.connect()

    transport.close.assert_not_awaited()
    assert k.connected is True
    assert k._instrument_id == ""
    assert k.output_state_unverified is True
