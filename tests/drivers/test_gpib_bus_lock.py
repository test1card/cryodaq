"""Tests for GPIB transport — persistent sessions, LabVIEW-style."""

from __future__ import annotations

import asyncio
import contextlib
import sys
import threading
import types

import pytest

from cryodaq.core.broker import DataBroker
from cryodaq.core.scheduler import InstrumentConfig, Scheduler
from cryodaq.drivers import registry as driver_registry
from cryodaq.drivers.base import InstrumentDriver
from cryodaq.drivers.contracts import (
    AcquisitionTiming,
    BusDescriptor,
    BusRecoveryLevel,
    DriverTrustClass,
    _issue_registry_runtime_binding,
)
from cryodaq.drivers.instruments.lakeshore_218s import LakeShore218S
from cryodaq.drivers.transport.gpib import GPIBIncompleteCloseError, GPIBTransport


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
    descriptor = BusDescriptor(
        "GPIB0",
        supported_recovery=frozenset({BusRecoveryLevel.DEVICE_CLEAR, BusRecoveryLevel.INTERFACE_CLEAR}),
    )

    class _Participant:
        bus_descriptor = descriptor

        async def mark_disconnected(self) -> None:
            await driver.disconnect()

        async def recover_device(self) -> None:
            await transport.clear_bus()

    class _Coordinator:
        bus_descriptor = descriptor

        async def interface_clear(self) -> bool:
            return await transport.send_ifc()

        async def reopen_bus(self) -> bool:
            raise AssertionError("reopen is outside this recovery level")

    binding = _issue_registry_runtime_binding(
        driver=driver,
        timing=AcquisitionTiming(1.0, 1.0, 0.01),
        registry_provenance="test:explicit-gpib",
        trust_class=DriverTrustClass.PASSIVE_EXTENSION,
        bus_descriptor=descriptor,
        participant=_Participant(),
        coordinator=_Coordinator(),
    )
    with driver_registry._RUNTIME_BINDINGS_LOCK:
        driver_registry._RUNTIME_BINDINGS[driver] = binding
    sched.add(InstrumentConfig(driver=driver, runtime_binding=binding))
    state = sched._instruments["ls218"]

    sched._running = True
    task = asyncio.create_task(sched._shared_bus_poll_loop("GPIB0", [state]))
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


async def test_gpib_connect_does_not_send_idn(monkeypatch):
    """open() must NOT send *IDN? — only opens resource + VISA Clear.

    The real _blocking_connect() runs against a fake pyvisa ResourceManager so
    every attribute assignment, clear(), and set_visa_attribute() call goes to
    _FakeResource.  Any *IDN? write/query inside _blocking_connect would be
    caught; patching the method itself would let an accidental send slip through.
    """

    class _FakeResource:
        def __init__(self) -> None:
            self.writes: list[str] = []
            self.queries: list[str] = []
            self.clears: int = 0
            self.write_termination = ""
            self.read_termination = ""
            self.timeout = 3000

        def clear(self) -> None:
            self.clears += 1

        def set_visa_attribute(self, attr: int, value: object) -> None:
            pass

        def write(self, cmd: str) -> None:
            self.writes.append(cmd)

        def read(self) -> str:
            return ""

        def query(self, cmd: str) -> str:
            self.queries.append(cmd)
            return ""

        def close(self) -> None:
            pass

    fake_resource = _FakeResource()

    class _FakeRM:
        def open_resource(self, resource_str: str) -> _FakeResource:  # noqa: ARG002
            return fake_resource

    # Inject fake pyvisa so _get_rm() constructs _FakeRM instead of the real RM.
    monkeypatch.setitem(
        sys.modules,
        "pyvisa",
        types.SimpleNamespace(ResourceManager=_FakeRM),
    )
    # Clear cached RMs so _get_rm() calls the fake constructor.
    monkeypatch.setattr(GPIBTransport, "_resource_managers", {}, raising=False)

    t = GPIBTransport(mock=False)
    await t.open("GPIB0::12::INSTR")

    # Verify the real _blocking_connect configured the resource correctly.
    assert fake_resource.clears >= 1, "VISA clear() must be called during connect"

    # Main assertion: no *IDN? ever written or queried.
    idn_writes = [w for w in fake_resource.writes if "*IDN?" in w.upper()]
    idn_queries = [q for q in fake_resource.queries if "*IDN?" in q.upper()]
    assert not idn_writes, f"open() must not write *IDN?, but saw: {idn_writes}"
    assert not idn_queries, f"open() must not query *IDN?, but saw: {idn_queries}"


async def test_gpib_krdg_no_argument():
    """KRDG? (no argument) returns 8 values; KRDG? N returns single value."""
    t = GPIBTransport(mock=True)
    await t.open("GPIB0::12::INSTR")

    all_channels = await t.query("KRDG?")
    assert len(all_channels.split(",")) == 8

    single = await t.query("KRDG? 3")
    assert "," not in single


async def test_lakeshore_validated_read_timeout_reaches_concrete_transport() -> None:
    driver = LakeShore218S(
        "LS",
        "GPIB0::12::INSTR",
        mock=True,
        connect_timeout_s=2.0,
        read_timeout_s=7.0,
    )
    await driver.connect()
    assert driver._transport._timeout_ms == 7000
    await driver.disconnect()


async def test_cancelled_partial_connect_closes_late_resource_and_executor(monkeypatch) -> None:
    opened = threading.Event()
    release = threading.Event()
    closed = threading.Event()

    class _LateResource:
        write_termination = ""
        read_termination = ""
        timeout = 0

        def clear(self) -> None:
            pass

        def set_visa_attribute(self, _attr: int, _value: object) -> None:
            pass

        def close(self) -> None:
            closed.set()

    class _BlockingRM:
        def open_resource(self, _resource: str) -> _LateResource:
            opened.set()
            release.wait(timeout=2.0)
            return _LateResource()

    monkeypatch.setitem(sys.modules, "pyvisa", types.SimpleNamespace(ResourceManager=_BlockingRM))
    monkeypatch.setattr(GPIBTransport, "_resource_managers", {}, raising=False)
    driver = LakeShore218S(
        "LS",
        "GPIB0::12::INSTR",
        mock=False,
        connect_timeout_s=0.05,
        read_timeout_s=0.1,
    )
    task = asyncio.create_task(driver.connect())
    assert await asyncio.to_thread(opened.wait, 1.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(RuntimeError, match="previous GPIB executor generation has not settled"):
        await driver._transport.open("GPIB0::12::INSTR", timeout_ms=100)
    release.set()
    assert await asyncio.to_thread(closed.wait, 1.0)
    assert driver._transport._resource is None
    assert driver._transport._executor is None
    assert not driver.connected


async def test_cancelled_connect_late_success_closes_exact_handle_automatically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_entered = threading.Event()
    release_clear = threading.Event()
    closed: list[object] = []
    opened: list[tuple[str, object]] = []

    class Handle:
        write_termination = ""
        read_termination = ""
        timeout = 0

        def clear(self) -> None:
            clear_entered.set()
            assert release_clear.wait(2.0)

        def set_visa_attribute(self, _attr, _value) -> None:
            pass

        def close(self) -> None:
            closed.append(self)

    exact_handle = Handle()

    class ResourceManager:
        def open_resource(self, resource: str) -> Handle:
            opened.append((resource, exact_handle))
            return exact_handle

    monkeypatch.setitem(
        sys.modules,
        "pyvisa",
        types.SimpleNamespace(ResourceManager=ResourceManager),
    )
    monkeypatch.setattr(GPIBTransport, "_resource_managers", {}, raising=False)
    transport = GPIBTransport(mock=False)

    owner = asyncio.create_task(
        transport.open("GPIB0::12::INSTR", timeout_ms=100),
    )
    assert await asyncio.to_thread(clear_entered.wait, 1.0)
    owner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await owner

    with pytest.raises(RuntimeError, match="generation has not settled"):
        await transport.open("GPIB0::13::INSTR", timeout_ms=100)

    release_clear.set()
    assert await asyncio.to_thread(transport._open_settled.wait, 2.0)
    assert closed == [exact_handle]
    assert opened == [("GPIB0::12::INSTR", exact_handle)]
    assert transport._resource is None
    assert transport._executor is None


async def test_cancelled_connect_late_failure_retains_quarantined_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_entered = threading.Event()
    release_clear = threading.Event()
    exact_close_attempts: list[object] = []

    class Handle:
        write_termination = ""
        read_termination = ""
        timeout = 0

        def clear(self) -> None:
            clear_entered.set()
            assert release_clear.wait(2.0)
            raise OSError("late connect failed")

        def set_visa_attribute(self, _attr, _value) -> None:
            pass

        def close(self) -> None:
            exact_close_attempts.append(self)
            raise OSError("exact late handle did not close")

    exact_handle = Handle()

    class ResourceManager:
        def open_resource(self, _resource: str) -> Handle:
            return exact_handle

    monkeypatch.setitem(
        sys.modules,
        "pyvisa",
        types.SimpleNamespace(ResourceManager=ResourceManager),
    )
    monkeypatch.setattr(GPIBTransport, "_resource_managers", {}, raising=False)
    transport = GPIBTransport(mock=False)
    owner = asyncio.create_task(transport.open("GPIB0::12::INSTR"))
    try:
        assert await asyncio.to_thread(clear_entered.wait, 1.0)
        owner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await owner
        release_clear.set()
        assert await asyncio.to_thread(transport._open_settled.wait, 2.0)

        assert exact_close_attempts == [exact_handle]
        assert transport._resource is exact_handle
        assert transport._terminal_unsettled is True
        assert isinstance(transport._close_error, OSError)
        with pytest.raises(RuntimeError, match="generation has not settled"):
            await transport.open("GPIB0::13::INSTR")
        with pytest.raises(GPIBIncompleteCloseError, match="quarantined"):
            await transport.close()
    finally:
        release_clear.set()
        await asyncio.gather(owner, return_exceptions=True)
        if transport._executor is not None:
            transport._executor.shutdown(wait=False, cancel_futures=True)


async def test_close_during_cancelled_connect_joins_same_terminal_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_entered = threading.Event()
    release_clear = threading.Event()
    closed: list[object] = []

    class Handle:
        write_termination = ""
        read_termination = ""
        timeout = 0

        def clear(self) -> None:
            clear_entered.set()
            assert release_clear.wait(2.0)

        def set_visa_attribute(self, _attr, _value) -> None:
            pass

        def close(self) -> None:
            closed.append(self)

    exact_handle = Handle()

    class ResourceManager:
        def open_resource(self, _resource: str) -> Handle:
            return exact_handle

    monkeypatch.setitem(
        sys.modules,
        "pyvisa",
        types.SimpleNamespace(ResourceManager=ResourceManager),
    )
    monkeypatch.setattr(GPIBTransport, "_resource_managers", {}, raising=False)
    transport = GPIBTransport(mock=False)
    owner = asyncio.create_task(transport.open("GPIB0::12::INSTR"))
    close_owner: asyncio.Task | None = None
    try:
        assert await asyncio.to_thread(clear_entered.wait, 1.0)
        owner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await owner
        close_owner = asyncio.create_task(transport.close())
        await asyncio.sleep(0)
        assert not close_owner.done()

        release_clear.set()
        await asyncio.wait_for(close_owner, 2.0)
        assert closed == [exact_handle]
        assert transport._resource is None
        assert transport._terminal_unsettled is False
        assert transport._open_settled.is_set()
    finally:
        release_clear.set()
        await asyncio.gather(owner, return_exceptions=True)
        if close_owner is not None:
            await asyncio.gather(close_owner, return_exceptions=True)
        if transport._executor is not None:
            transport._executor.shutdown(wait=False, cancel_futures=True)


async def test_reopen_blocked_until_cancelled_connect_terminal_settlement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_clear_entered = threading.Event()
    release_first_clear = threading.Event()
    opened: list[object] = []
    closed: list[object] = []

    class Handle:
        write_termination = ""
        read_termination = ""
        timeout = 0

        def __init__(self, *, blocks: bool) -> None:
            self.blocks = blocks

        def clear(self) -> None:
            if self.blocks:
                first_clear_entered.set()
                assert release_first_clear.wait(2.0)

        def set_visa_attribute(self, _attr, _value) -> None:
            pass

        def close(self) -> None:
            closed.append(self)

    first_handle = Handle(blocks=True)
    second_handle = Handle(blocks=False)

    class ResourceManager:
        def open_resource(self, _resource: str) -> Handle:
            handle = first_handle if not opened else second_handle
            opened.append(handle)
            return handle

    monkeypatch.setitem(
        sys.modules,
        "pyvisa",
        types.SimpleNamespace(ResourceManager=ResourceManager),
    )
    monkeypatch.setattr(GPIBTransport, "_resource_managers", {}, raising=False)
    transport = GPIBTransport(mock=False)
    owner = asyncio.create_task(transport.open("GPIB0::12::INSTR"))
    try:
        assert await asyncio.to_thread(first_clear_entered.wait, 1.0)
        owner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await owner
        with pytest.raises(RuntimeError, match="generation has not settled"):
            await transport.open("GPIB0::13::INSTR")
        assert opened == [first_handle]

        release_first_clear.set()
        assert await asyncio.to_thread(transport._open_settled.wait, 2.0)
        assert closed == [first_handle]
        await transport.open("GPIB0::13::INSTR")
        assert opened == [first_handle, second_handle]
        assert transport._resource is second_handle
        assert transport._session_open is True
    finally:
        release_first_clear.set()
        await asyncio.gather(owner, return_exceptions=True)
        if transport._resource is second_handle:
            await transport.close()
        if transport._executor is not None:
            transport._executor.shutdown(wait=False, cancel_futures=True)


async def test_cancelled_blocking_idn_rejects_overlap_until_executor_settles(monkeypatch) -> None:
    read_started = threading.Event()
    release_read = threading.Event()
    closed = threading.Event()
    resources_opened = 0

    class _BlockingIDNResource:
        write_termination = ""
        read_termination = ""
        timeout = 0

        def clear(self) -> None:
            pass

        def set_visa_attribute(self, _attr: int, _value: object) -> None:
            pass

        def write(self, _command: str) -> None:
            pass

        def read(self) -> str:
            read_started.set()
            release_read.wait(timeout=2.0)
            return "LSCI,MODEL218S,SERIAL,1"

        def close(self) -> None:
            closed.set()

    class _RM:
        def open_resource(self, _resource: str) -> _BlockingIDNResource:
            nonlocal resources_opened
            resources_opened += 1
            return _BlockingIDNResource()

    monkeypatch.setitem(sys.modules, "pyvisa", types.SimpleNamespace(ResourceManager=_RM))
    monkeypatch.setattr(GPIBTransport, "_resource_managers", {}, raising=False)
    driver = LakeShore218S("LS", "GPIB0::12::INSTR", mock=False, read_timeout_s=0.1)
    task = asyncio.create_task(driver.connect())
    assert await asyncio.to_thread(read_started.wait, 1.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(RuntimeError, match="executor generation has not settled"):
        await driver.connect()
    assert resources_opened == 1
    assert driver._transport._executor is not None
    release_read.set()
    assert await asyncio.to_thread(driver._transport._open_settled.wait, 2.0)
    assert await asyncio.to_thread(closed.wait, 1.0)
    await driver.disconnect()
    assert driver._transport._executor is None
    assert resources_opened == 1


async def test_cancelled_idn_phase_uses_public_partial_connect_cleanup() -> None:
    query_started = asyncio.Event()

    class _BlockingTransport:
        aborted = 0

        async def open(self, _resource: str, *, timeout_ms: int) -> None:
            assert timeout_ms == 7000

        async def query(self, _command: str, *, timeout_ms: int | None = None) -> str:
            assert timeout_ms == 2000
            query_started.set()
            await asyncio.Event().wait()
            return ""

        async def abort_open(self) -> None:
            self.aborted += 1

        async def close(self) -> None:
            self.aborted += 1

    driver = LakeShore218S(
        "LS",
        "GPIB0::12::INSTR",
        mock=False,
        connect_timeout_s=2.0,
        read_timeout_s=7.0,
    )
    transport = _BlockingTransport()
    driver._transport = transport  # type: ignore[assignment]
    task = asyncio.create_task(driver.connect())
    await asyncio.wait_for(query_started.wait(), timeout=0.5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert transport.aborted >= 1
    assert not driver.connected
