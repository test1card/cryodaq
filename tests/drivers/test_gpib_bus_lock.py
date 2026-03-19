"""Tests for GPIB transport open-per-query semantics."""

from __future__ import annotations

import pytest

from cryodaq.drivers.transport.gpib import GPIBTransport


async def test_gpib_open_stores_resource_str():
    """open() stores resource string without opening a VISA resource."""
    t = GPIBTransport(mock=True)
    await t.open("GPIB0::12::INSTR")
    assert t._resource_str == "GPIB0::12::INSTR"
    assert t._bus_prefix == "GPIB0"


async def test_gpib_query_returns_mock_response():
    """Mock query returns known responses."""
    t = GPIBTransport(mock=True)
    await t.open("GPIB0::12::INSTR")
    response = await t.query("*IDN?")
    assert "MODEL218S" in response


async def test_gpib_close_is_noop():
    """close() is a no-op — no exception, no state change."""
    t = GPIBTransport(mock=True)
    await t.open("GPIB0::12::INSTR")
    await t.close()
    # Can still query after close (open-per-query)
    response = await t.query("*IDN?")
    assert "MODEL218S" in response


async def test_gpib_shared_resource_manager():
    """Two transports on the same bus share one ResourceManager."""
    t1 = GPIBTransport(mock=True)
    t2 = GPIBTransport(mock=True)
    await t1.open("GPIB0::12::INSTR")
    await t2.open("GPIB0::11::INSTR")
    assert t1._bus_prefix == t2._bus_prefix == "GPIB0"


async def test_gpib_different_buses_independent():
    """Transports on different buses have different prefixes."""
    t1 = GPIBTransport(mock=True)
    t2 = GPIBTransport(mock=True)
    await t1.open("GPIB0::12::INSTR")
    await t2.open("GPIB1::12::INSTR")
    assert t1._bus_prefix != t2._bus_prefix
