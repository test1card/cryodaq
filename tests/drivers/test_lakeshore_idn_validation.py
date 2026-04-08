"""Verify LakeShore 218S IDN validation + retry (Phase 2c Codex F.1)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.drivers.instruments.lakeshore_218s import LakeShore218S


def _make_ls(transport: MagicMock) -> LakeShore218S:
    ls = LakeShore218S(name="LS1", resource_str="GPIB0::12::INSTR", mock=False)
    ls._transport = transport
    return ls


@pytest.mark.asyncio
async def test_connect_succeeds_on_valid_idn():
    transport = MagicMock()
    transport.open = AsyncMock()
    transport.close = AsyncMock()
    transport.query = AsyncMock(return_value="LSCI,MODEL218S,12345,1.5")
    transport.write = AsyncMock()
    transport.clear_bus = AsyncMock(return_value=True)

    ls = _make_ls(transport)
    await ls.connect()
    assert ls._connected is True
    assert "LSCI" in ls._instrument_id
    transport.clear_bus.assert_not_awaited()  # no clear needed on first try


@pytest.mark.asyncio
async def test_connect_raises_on_wrong_idn():
    transport = MagicMock()
    transport.open = AsyncMock()
    transport.close = AsyncMock()
    # Wrong device — Keithley on the wrong GPIB address
    transport.query = AsyncMock(return_value="KEITHLEY INSTRUMENTS,MODEL 2604B")
    transport.write = AsyncMock()
    transport.clear_bus = AsyncMock(return_value=True)

    ls = _make_ls(transport)
    with pytest.raises(RuntimeError, match="IDN validation failed"):
        await ls.connect()
    assert ls._connected is False
    transport.close.assert_awaited()


@pytest.mark.asyncio
async def test_connect_retries_once_after_clear():
    transport = MagicMock()
    transport.open = AsyncMock()
    transport.close = AsyncMock()
    # First query returns garbage, second returns valid IDN
    transport.query = AsyncMock(
        side_effect=["garbage_response", "LSCI,MODEL218S,12345,1.5"]
    )
    transport.write = AsyncMock()
    transport.clear_bus = AsyncMock(return_value=True)

    ls = _make_ls(transport)
    await ls.connect()
    assert ls._connected is True
    assert transport.query.await_count == 2
    transport.clear_bus.assert_awaited_once()


@pytest.mark.asyncio
async def test_connect_retries_once_when_query_raises():
    """A query that raises also triggers clear+retry."""
    transport = MagicMock()
    transport.open = AsyncMock()
    transport.close = AsyncMock()
    transport.query = AsyncMock(
        side_effect=[OSError("transport hiccup"), "LSCI,MODEL218S,12345,1.5"]
    )
    transport.write = AsyncMock()
    transport.clear_bus = AsyncMock(return_value=True)

    ls = _make_ls(transport)
    await ls.connect()
    assert ls._connected is True
    transport.clear_bus.assert_awaited_once()


@pytest.mark.asyncio
async def test_connect_raises_when_both_attempts_fail():
    transport = MagicMock()
    transport.open = AsyncMock()
    transport.close = AsyncMock()
    transport.query = AsyncMock(side_effect=OSError("dead bus"))
    transport.write = AsyncMock()
    transport.clear_bus = AsyncMock(return_value=True)

    ls = _make_ls(transport)
    with pytest.raises(RuntimeError, match="IDN validation failed"):
        await ls.connect()
    assert ls._connected is False
    assert transport.query.await_count == 2  # initial + retry
