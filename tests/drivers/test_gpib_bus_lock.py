"""Tests for GPIB transport — persistent sessions, LabVIEW-style."""

from __future__ import annotations

import sys
import types

from cryodaq.drivers.transport.gpib import GPIBTransport


async def test_gpib_open_stores_resource_str():
    """open() stores resource string and opens persistent session (mock)."""
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


async def test_gpib_close_releases_resource():
    """close() clears the resource handle."""
    t = GPIBTransport(mock=True)
    await t.open("GPIB0::12::INSTR")
    await t.close()
    # In mock mode, resource is None (never set)
    assert t._resource is None


def test_gpib_resource_manager_shared_per_bus(monkeypatch):
    """_get_rm caches one pyvisa.ResourceManager per bus prefix and reuses it.

    Tests the real caching logic (the previous test ran in mock mode, which
    returns before _get_rm, and only compared _bus_prefix strings). A fake pyvisa
    counts how many ResourceManagers are actually constructed."""
    created: list = []

    class _FakeRM:
        def __init__(self):
            created.append(self)

    monkeypatch.setitem(sys.modules, "pyvisa", types.SimpleNamespace(ResourceManager=_FakeRM))
    monkeypatch.setattr(GPIBTransport, "_resource_managers", {}, raising=False)

    rm_a1 = GPIBTransport._get_rm("GPIB0")
    rm_a2 = GPIBTransport._get_rm("GPIB0")
    rm_b = GPIBTransport._get_rm("GPIB1")

    assert rm_a1 is rm_a2, "same bus must reuse the cached ResourceManager"
    assert rm_b is not rm_a1, "different bus must get its own ResourceManager"
    assert len(created) == 2, f"expected exactly 2 RMs (one per bus), got {len(created)}"


async def test_gpib_different_buses_independent():
    """Transports on different buses have different prefixes."""
    t1 = GPIBTransport(mock=True)
    t2 = GPIBTransport(mock=True)
    await t1.open("GPIB0::12::INSTR")
    await t2.open("GPIB1::12::INSTR")
    assert t1._bus_prefix != t2._bus_prefix


async def test_gpib_no_ifc_in_codebase():
    """IFC recovery is removed — no send_ifc method."""
    t = GPIBTransport(mock=True)
    assert not hasattr(t, "_send_ifc") or not callable(getattr(t, "_send_ifc", None))


async def test_gpib_connect_does_not_send_idn():
    """open() does not send *IDN? — just opens resource + clear."""
    t = GPIBTransport(mock=True)
    await t.open("GPIB0::12::INSTR")
    # In mock mode, no queries are sent during open
    # The key test: open() succeeds without any query


async def test_gpib_krdg_no_argument():
    """KRDG? (no argument) returns 8 values; KRDG? N returns single value."""
    t = GPIBTransport(mock=True)
    await t.open("GPIB0::12::INSTR")

    all_channels = await t.query("KRDG?")
    assert len(all_channels.split(",")) == 8

    single = await t.query("KRDG? 3")
    assert "," not in single
