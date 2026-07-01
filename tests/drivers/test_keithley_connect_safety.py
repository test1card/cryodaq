"""Verify Keithley connect()/emergency_off() safety guards (Phase 2a G.1)."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.drivers.instruments.keithley_2604b import Keithley2604B


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
    transport.query = AsyncMock(return_value="KEITHLEY INSTRUMENTS,MODEL 2604B,FAKE,1.0")
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

    # Ordering check (Codex Phase 2a P2): levelv=0 must come BEFORE OUTPUT_OFF
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
    assert not force_off_cmds, (
        f"mock mode must NOT issue force-off writes, but saw: {force_off_cmds}"
    )


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
    transport.query = AsyncMock(return_value="KEITHLEY INSTRUMENTS,MODEL 2604B,FAKE,1.0")

    write_calls = {"n": 0}

    async def write_side_effect(cmd: str) -> None:
        write_calls["n"] += 1
        # errorqueue.clear() succeeds, then the first force-off write fails.
        if cmd != "errorqueue.clear()" and "source" in cmd:
            raise OSError("simulated transport failure")

    transport.write = AsyncMock(side_effect=write_side_effect)
    k._transport = transport

    await k.connect()

    assert k._connected is True, "connect must succeed even if force-off failed"
    assert any("failed to force output off" in r.message.lower() for r in caplog.records), (
        "CRITICAL log not emitted for force-off failure"
    )


@pytest.mark.asyncio
async def test_emergency_off_verifies_readback_both_channels():
    """emergency_off must readback source.output on both SMU channels."""
    k = _make_keithley(mock=False)
    transport = MagicMock()
    transport.write = AsyncMock()
    transport.query = AsyncMock(return_value="0.00000e+00\n")
    k._transport = transport
    k._connected = True

    await k.emergency_off()

    queries = [call.args[0] for call in transport.query.call_args_list]
    assert any("print(smua.source.output)" in q for q in queries), (
        f"smua output readback missing. Queries: {queries}"
    )
    assert any("print(smub.source.output)" in q for q in queries), (
        f"smub output readback missing. Queries: {queries}"
    )


@pytest.mark.asyncio
async def test_emergency_off_logs_critical_on_verify_failure(caplog):
    """If readback shows output still on, log CRITICAL and do not raise."""
    caplog.set_level(logging.CRITICAL)
    k = _make_keithley(mock=False)
    transport = MagicMock()
    transport.write = AsyncMock()
    # 1.0 == output STILL ON after we issued OUTPUT_OFF
    transport.query = AsyncMock(return_value="1.00000e+00\n")
    k._transport = transport
    k._connected = True

    # Must NOT raise — we are already in an emergency path.
    await k.emergency_off()

    relevant = [
        r
        for r in caplog.records
        if "still reports output" in r.message or "verify FAILED" in r.message
    ]
    assert relevant, (
        f"no CRITICAL log emitted on verify failure. records: {[r.message for r in caplog.records]}"
    )


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

    # CRITICAL log MUST be emitted (Codex Phase 2a P2 — was missing).
    relevant = [
        r
        for r in caplog.records
        if "verify FAILED" in r.message
        or "unexpected output response" in r.message
        or "still reports output" in r.message
    ]
    assert relevant, (
        f"No CRITICAL log emitted on query exception. records: "
        f"{[r.message for r in caplog.records]}"
    )


# ---------------------------------------------------------------------------
# CR-2: emergency_off must REPORT success/failure so callers can fail closed.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emergency_off_returns_true_on_clean_off():
    """Writes succeed and readback confirms OFF on both channels → True."""
    k = _make_keithley(mock=False)
    transport = MagicMock()
    transport.write = AsyncMock()
    transport.query = AsyncMock(return_value="0.00000e+00\n")
    k._transport = transport
    k._connected = True

    assert await k.emergency_off() is True


@pytest.mark.asyncio
async def test_emergency_off_returns_true_in_mock_mode():
    k = _make_keithley(mock=True)
    assert await k.emergency_off() is True


@pytest.mark.asyncio
async def test_emergency_off_returns_false_when_output_off_write_raises():
    """OUTPUT_OFF write raising means the SMU may still be sourcing — must
    return False even if the subsequent readback (from a flaky link) says 0."""
    k = _make_keithley(mock=False)
    transport = MagicMock()

    async def write_side_effect(cmd: str) -> None:
        if "OUTPUT_OFF" in cmd:
            raise OSError("transport hiccup")

    transport.write = AsyncMock(side_effect=write_side_effect)
    transport.query = AsyncMock(return_value="0.00000e+00\n")
    k._transport = transport
    k._connected = True

    assert await k.emergency_off() is False


@pytest.mark.asyncio
async def test_emergency_off_returns_false_when_readback_still_on():
    """Readback reports output=1 after OUTPUT_OFF → False."""
    k = _make_keithley(mock=False)
    transport = MagicMock()
    transport.write = AsyncMock()
    transport.query = AsyncMock(return_value="1.00000e+00\n")
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
            return "1.00000e+00\n"  # smub still ON
        return "0.00000e+00\n"

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

    for response, expected in [
        ("0.00000e+00\n", True),
        ("0\n", True),
        ("1.00000e+00\n", False),
        ("1\n", False),
        ("garbage\n", False),
    ]:
        transport.query = AsyncMock(return_value=response)
        assert await k._verify_output_off("smua") is expected, (
            f"readback {response!r} must yield {expected}"
        )
