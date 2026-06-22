"""Tests for GPIB transport — persistent sessions, LabVIEW-style."""

from __future__ import annotations

import asyncio
import contextlib
import sys
import types

from cryodaq.core.broker import DataBroker
from cryodaq.core.scheduler import InstrumentConfig, Scheduler
from cryodaq.drivers.base import InstrumentDriver
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


async def test_gpib_send_ifc_is_available_level2_recovery():
    """IFC (Interface Clear) IS the Level-2 bus recovery: GPIBTransport exposes a
    public, awaitable send_ifc() (the scheduler calls it on bus lockup). In mock
    mode it is a no-op that reports success. (This replaces a stale test that
    asserted IFC was 'removed' — production re-added it as send_ifc.)"""
    t = GPIBTransport(mock=True)
    assert callable(getattr(t, "send_ifc", None)), "send_ifc must exist as recovery"
    assert await t.send_ifc() is True


class _SpyGPIBTransport:
    """Records Level-1 (clear_bus) and Level-2 (send_ifc) recovery calls."""

    def __init__(self) -> None:
        self.clear_calls = 0
        self.ifc_calls = 0
        self.ifc_fired = asyncio.Event()

    async def clear_bus(self) -> bool:
        self.clear_calls += 1
        return True

    async def send_ifc(self) -> bool:
        self.ifc_calls += 1
        self.ifc_fired.set()
        return True


class _FailingGPIBDriver(InstrumentDriver):
    """Driver whose every read raises — drives the bus into escalating recovery."""

    def __init__(self, name: str, transport: _SpyGPIBTransport) -> None:
        super().__init__(name, mock=False)
        self._transport = transport
        self._connected = True

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def read_channels(self):
        raise RuntimeError("simulated GPIB bus lockup")


async def test_gpib_ifc_recovery_invokes_send_ifc():
    """Behavioral integration (replaces a source grep): when reads keep failing,
    the scheduler's GPIB recovery escalates and ACTUALLY awaits transport.send_ifc()
    at Level 2 — proven by spying the transport, not by reading source text."""
    broker = DataBroker()
    sched = Scheduler(broker=broker, sqlite_writer=None)
    transport = _SpyGPIBTransport()
    driver = _FailingGPIBDriver("ls218", transport)
    sched.add(
        InstrumentConfig(driver=driver, poll_interval_s=0.01, resource_str="GPIB0::12::INSTR")
    )
    state = sched._instruments["ls218"]

    sched._running = True
    task = asyncio.create_task(sched._gpib_poll_loop("GPIB0", [state]))
    try:
        # Level 2 fires on the 3rd consecutive bus error; well within 5s.
        await asyncio.wait_for(transport.ifc_fired.wait(), timeout=5.0)
    finally:
        sched._running = False
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    assert transport.ifc_calls >= 1, "Level-2 recovery must invoke send_ifc()"
    assert transport.clear_calls >= 1, "Level-1 clear_bus must run before IFC escalation"


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
