"""Verify GPIB executor ownership; USBTMC process ownership lives in test_usbtmc_process_protocol."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_gpib_query_and_write_use_dedicated_executor():
    """Behavioral proof (not a source grep): non-mock query() and write() must
    dispatch their blocking VISA calls to the transport's OWN single-worker
    executor, never the default (None) executor. Spies the running loop's
    run_in_executor and asserts the executor argument identity."""
    import asyncio

    from cryodaq.drivers.transport.gpib import GPIBTransport

    class _FakeResource:
        # The spy executes the submitted wrapper synchronously so both
        # dedicated-executor dispatch and lifecycle settlement are exercised.
        def write(self, *a, **k) -> None: ...
        def read(self, *a, **k) -> str:
            return ""

    transport = GPIBTransport(mock=False)
    transport._resource_str = "GPIB0::12::INSTR"
    transport._resource = _FakeResource()  # non-None so the mock/None guards fall through

    loop = asyncio.get_running_loop()
    captured: list[object] = []

    def spy(executor, func, *args):
        captured.append(executor)
        fut = loop.create_future()
        # Execute the submitted wrapper synchronously so its lifecycle-finally
        # settlement is represented as well as its executor identity.
        fut.set_result(func(*args))
        return fut

    with patch.object(loop, "run_in_executor", side_effect=spy):
        await transport.query("*IDN?")
        await transport.write("*CLS")

    assert len(captured) == 2, "both query and write must dispatch via run_in_executor"
    dedicated = transport._get_executor()
    assert dedicated is not None
    for ex in captured:
        assert ex is dedicated, "VISA calls must use the dedicated executor, not None"
    dedicated.shutdown(wait=False)


def test_gpib_get_executor_creates_single_worker_pool():
    from cryodaq.drivers.transport.gpib import GPIBTransport

    t = GPIBTransport(mock=True)
    ex = t._get_executor()
    assert isinstance(ex, ThreadPoolExecutor)
    assert ex._max_workers == 1
    # Idempotent — second call returns the same instance.
    assert t._get_executor() is ex
    ex.shutdown(wait=True)


@pytest.mark.asyncio
async def test_gpib_close_shuts_down_executor():
    """Behavioral: after close(), _executor must be None (shutdown was called)."""
    from cryodaq.drivers.transport.gpib import GPIBTransport

    transport = GPIBTransport(mock=False)
    transport._resource_str = "GPIB0::12::INSTR"

    class _Resource:
        def close(self) -> None:
            return None

    transport._resource = _Resource()
    # Force executor creation before close.
    _ = transport._get_executor()
    assert transport._executor is not None

    await transport.close()
    assert transport._executor is None, "close() must shut down and clear _executor"


@pytest.mark.asyncio
async def test_usbtmc_open_refuses_to_overwrite_live_handles(monkeypatch):
    from cryodaq.drivers.transport.usbtmc import USBTMCTransport

    old_resource = object()
    old_manager = object()
    transport = USBTMCTransport(mock=False)
    transport._resource = old_resource
    transport._rm = old_manager
    monkeypatch.setattr(transport, "_blocking_open", lambda *_args: None)

    with pytest.raises(RuntimeError, match="already open"):
        await transport.open("USB0::NEW::INSTR")

    assert transport._resource is old_resource
    assert transport._rm is old_manager


def test_gpib_resource_manager_lock_exists():
    """Phase 2b F.1: _get_rm must be guarded by a class-level lock."""
    from cryodaq.drivers.transport.gpib import GPIBTransport

    assert hasattr(GPIBTransport, "_rm_lock")
    assert isinstance(GPIBTransport._rm_lock, type(threading.Lock()))


def test_concurrent_get_rm_creates_single_manager():
    """Phase 2b F.1: 10 threads racing on _get_rm produce ONE RM and all
    callers receive the same instance."""
    from cryodaq.drivers.transport.gpib import GPIBTransport

    GPIBTransport._resource_managers.clear()
    created: list[object] = []
    create_lock = threading.Lock()

    def fake_rm():
        import time

        time.sleep(0.01)  # widen the TOCTOU window
        marker = object()
        with create_lock:
            created.append(marker)
        return marker

    results: list[object] = []
    results_lock = threading.Lock()
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            r = GPIBTransport._get_rm("GPIB0")
            with results_lock:
                results.append(r)
        except BaseException as exc:  # pragma: no cover
            with results_lock:
                errors.append(exc)

    with patch("pyvisa.ResourceManager", side_effect=fake_rm):
        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert errors == [], f"Worker thread errors: {errors}"
    assert len(created) == 1, f"Expected exactly 1 RM creation, got {len(created)} — TOCTOU race"
    assert len(results) == 10, f"Some workers did not return: got {len(results)}"
    # All workers must have received the SAME instance.
    first = results[0]
    assert all(r is first for r in results), "Workers received different RM instances despite the lock"
    assert len(GPIBTransport._resource_managers) == 1
    GPIBTransport._resource_managers.clear()


def test_close_all_managers_holds_rm_lock():
    """Behavioral: close_all_managers must acquire _rm_lock while closing.

    We replace _rm_lock with a spy lock that records whether it was held
    during the rm.close() call, proving the critical section is correct.
    """
    from cryodaq.drivers.transport.gpib import GPIBTransport

    lock_held_during_close: list[bool] = []
    spy_lock = threading.Lock()
    original_lock = GPIBTransport._rm_lock

    class _SpyLock:
        """Wraps a real Lock but records whether it was held when rm.close() ran."""

        def acquire(self, *a, **kw):
            return spy_lock.acquire(*a, **kw)

        def release(self):
            return spy_lock.release()

        def __enter__(self):
            self.acquire()
            return self

        def __exit__(self, *a):
            self.release()

        def locked(self) -> bool:
            return spy_lock.locked()

    spy = _SpyLock()

    class _FakeRM:
        def close(self) -> None:
            # Record whether the spy lock is held at the moment of close().
            lock_held_during_close.append(spy.locked())

    original_managers = GPIBTransport._resource_managers.copy()
    try:
        GPIBTransport._resource_managers = {"GPIB0": _FakeRM()}
        GPIBTransport._rm_lock = spy  # type: ignore[assignment]
        GPIBTransport.close_all_managers()
    finally:
        GPIBTransport._rm_lock = original_lock
        GPIBTransport._resource_managers = original_managers

    assert lock_held_during_close, "close_all_managers did not call rm.close() at all"
    assert all(lock_held_during_close), (
        "close_all_managers must hold _rm_lock while closing managers — "
        "scheduler L3 recovery on one bus must not race with _get_rm on healthy buses"
    )


@pytest.mark.asyncio
async def test_gpib_close_returns_even_if_executor_worker_is_blocked():
    from cryodaq.drivers.transport.gpib import GPIBTransport

    transport = GPIBTransport(mock=False)
    transport._resource_str = "GPIB0::12::INSTR"

    class _Resource:
        def close(self) -> None:
            return None

    transport._resource = _Resource()
    executor = transport._get_executor()
    blocker = threading.Event()
    release = threading.Event()

    def _hang() -> None:
        blocker.set()
        release.wait(timeout=10.0)

    executor.submit(_hang)
    assert blocker.wait(timeout=1.0)

    started = time.monotonic()
    await transport.close()
    elapsed = time.monotonic() - started
    release.set()

    assert elapsed < 2.5, f"GPIB close blocked too long ({elapsed:.2f}s)"


@pytest.mark.asyncio
async def test_gpib_double_open_and_incomplete_close_keep_retained_owner() -> None:
    import asyncio

    from cryodaq.drivers.transport.gpib import GPIBIncompleteCloseError, GPIBTransport

    release = threading.Event()

    class _Resource:
        def close(self) -> None:
            assert release.wait(3.0)

    transport = GPIBTransport(mock=False)
    transport._resource_str = "GPIB0::12::INSTR"
    transport._resource = _Resource()
    transport._session_open = True

    with pytest.raises(RuntimeError, match="previous GPIB executor generation"):
        await transport.open("GPIB0::12::INSTR")
    close_task = asyncio.create_task(transport.close())
    await asyncio.sleep(0)
    with pytest.raises(GPIBIncompleteCloseError):
        await close_task
    with pytest.raises(RuntimeError, match="previous GPIB executor generation"):
        await transport.open("GPIB0::12::INSTR")
    release.set()
    assert await asyncio.to_thread(transport._close_done.wait, 2.0)
    await transport.close()
    assert transport._resource is None


@pytest.mark.asyncio
async def test_gpib_close_error_is_typed_and_remains_quarantined() -> None:
    from cryodaq.drivers.transport.gpib import GPIBIncompleteCloseError, GPIBTransport

    class _Resource:
        def close(self) -> None:
            raise OSError("close failed")

    transport = GPIBTransport(mock=False)
    transport._resource = _Resource()
    transport._session_open = True
    with pytest.raises(GPIBIncompleteCloseError, match="handle remains quarantined"):
        await transport.close()
    with pytest.raises(GPIBIncompleteCloseError, match="handle remains quarantined"):
        await transport.close()
    assert transport._resource is not None


def test_usbtmc_close_outcome_retains_process_control_exception() -> None:
    from cryodaq.drivers.transport.usbtmc import USBTMCTransport

    class _ProcessControl(BaseException):
        pass

    process_control = _ProcessControl("terminate")
    manager_closed = False

    class _Resource:
        def close(self) -> None:
            raise process_control

    class _Manager:
        def close(self) -> None:
            nonlocal manager_closed
            manager_closed = True

    outcome = USBTMCTransport(mock=False)._blocking_close_handles(_Resource(), _Manager())

    assert outcome.succeeded is False
    assert outcome.resource_error is process_control
    assert outcome.manager_error is None
    assert manager_closed is True


@pytest.mark.asyncio
async def test_gpib_double_open_and_incomplete_close_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    import cryodaq.drivers.transport.gpib as gpib_module
    from cryodaq.drivers.transport.gpib import GPIBIncompleteCloseError, GPIBTransport

    close_entered = threading.Event()
    release_close = threading.Event()
    exact_handle = object()
    close_calls: list[object] = []

    class Resource:
        def close(self) -> None:
            close_entered.set()
            assert release_close.wait(3.0)
            close_calls.append(exact_handle)

    resource = Resource()
    transport = GPIBTransport(mock=False)
    transport._resource = resource
    transport._resource_str = "GPIB0::12::INSTR"
    transport._session_open = True
    initial_generation = transport._open_generation
    monkeypatch.setattr(gpib_module, "_CLOSE_TIMEOUT_S", 0.01)

    close_task: asyncio.Task | None = None
    try:
        with pytest.raises(RuntimeError, match="generation has not settled"):
            await transport.open("GPIB0::13::INSTR")
        assert transport._open_generation == initial_generation

        close_task = asyncio.create_task(transport.close())
        assert await asyncio.to_thread(close_entered.wait, 1.0)
        with pytest.raises(GPIBIncompleteCloseError, match="did not settle"):
            await close_task
        assert transport._resource is resource
        assert transport._terminal_unsettled is True
        with pytest.raises(RuntimeError, match="generation has not settled"):
            await transport.open("GPIB0::13::INSTR")

        release_close.set()
        assert transport._close_done is not None
        assert await asyncio.to_thread(transport._close_done.wait, 2.0)
        await transport.close()
        assert close_calls == [exact_handle]
        assert transport._resource is None
        assert transport._terminal_unsettled is False
    finally:
        release_close.set()
        if close_task is not None:
            await asyncio.gather(close_task, return_exceptions=True)
        if transport._executor is not None:
            transport._executor.shutdown(wait=False, cancel_futures=True)


@pytest.mark.asyncio
async def test_gpib_clean_new_generation_recovers_from_desynchronization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.drivers.transport.gpib as gpib_module
    from cryodaq.drivers.transport.gpib import GPIBTransport

    events: list[tuple[str, object]] = []

    class Resource:
        write_termination = ""
        read_termination = ""
        timeout = 0

        def __init__(self, name: str, *, fail_query: bool) -> None:
            self.name = name
            self.fail_query = fail_query

        def clear(self) -> None:
            events.append(("sdc", self))

        def set_visa_attribute(self, _attr, _value) -> None:
            pass

        def write(self, command: str) -> None:
            events.append((command, self))

        def read(self) -> str:
            if self.fail_query:
                raise OSError("GPIB response provenance lost")
            return "fresh-response"

        def close(self) -> None:
            events.append(("close", self))

    class Interface:
        def send_ifc(self) -> None:
            events.append(("ifc", self))

        def close(self) -> None:
            events.append(("close", self))

    failed = Resource("failed", fail_query=True)
    fresh = Resource("fresh", fail_query=False)
    interface = Interface()
    normal_resources = iter((failed, fresh))

    class ResourceManager:
        def open_resource(self, resource_str: str):
            if resource_str.endswith("::INTFC"):
                return interface
            resource = next(normal_resources)
            events.append(("open", resource))
            return resource

    manager = ResourceManager()
    monkeypatch.setattr(GPIBTransport, "_resource_managers", {"GPIB0": manager}, raising=False)
    monkeypatch.setattr(gpib_module, "_WRITE_READ_DELAY_S", 0.0)
    transport = GPIBTransport(mock=False)
    try:
        await transport.open("GPIB0::12::INSTR")
        with pytest.raises(OSError, match="provenance lost"):
            await transport.query("KRDG?")
        assert transport._query_desynchronized is True
        await transport.close()
        assert ("close", failed) in events

        await transport.open("GPIB0::12::INSTR")
        assert transport._resource is fresh
        assert transport._query_desynchronized is True
        assert await transport.recover() is True
        assert transport._query_desynchronized is False
        assert await transport.query("KRDG?") == "fresh-response"
        assert ("sdc", fresh) in events
        assert ("ifc", interface) in events
    finally:
        if transport._resource is not None:
            await transport.close()


@pytest.mark.asyncio
async def test_gpib_successful_recovery_clears_query_quarantine_only_after_both_steps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from cryodaq.drivers.transport.gpib import GPIBTransport

    transport = GPIBTransport(mock=False)
    transport._resource = object()
    transport._session_open = True
    transport._query_desynchronized = True
    generation = transport._open_generation
    clear_entered = asyncio.Event()
    release_clear = asyncio.Event()
    ifc_entered = asyncio.Event()
    release_ifc = asyncio.Event()

    async def clear_bus() -> bool:
        clear_entered.set()
        await release_clear.wait()
        return True

    async def send_ifc() -> bool:
        ifc_entered.set()
        await release_ifc.wait()
        return True

    monkeypatch.setattr(transport, "clear_bus", clear_bus)
    monkeypatch.setattr(transport, "send_ifc", send_ifc)
    recovery = asyncio.create_task(transport.recover())
    try:
        await asyncio.wait_for(clear_entered.wait(), 1.0)
        assert transport._query_desynchronized is True
        assert transport._open_generation == generation
        release_clear.set()
        await asyncio.wait_for(ifc_entered.wait(), 1.0)
        assert transport._query_desynchronized is True
        assert transport._open_generation == generation
        release_ifc.set()
        assert await recovery is True
        assert transport._query_desynchronized is False
        assert transport._open_generation == generation + 1

        transport._query_desynchronized = True

        async def fail_ifc() -> bool:
            return False

        monkeypatch.setattr(transport, "send_ifc", fail_ifc)
        assert await transport.recover() is False
        assert transport._query_desynchronized is True
    finally:
        release_clear.set()
        release_ifc.set()
        await asyncio.gather(recovery, return_exceptions=True)
        transport._resource = None
        transport._session_open = False


@pytest.mark.asyncio
async def test_gpib_terminal_close_intent_survives_cancelled_operation_settlement_and_closes_exact_handle() -> None:
    import asyncio

    from cryodaq.drivers.transport.gpib import GPIBIncompleteCloseError, GPIBTransport

    write_entered = threading.Event()
    release_write = threading.Event()
    closes: list[object] = []

    class Resource:
        def write(self, _command: str) -> None:
            write_entered.set()
            assert release_write.wait(3.0)

        def close(self) -> None:
            closes.append(self)

    exact_handle = Resource()
    transport = GPIBTransport(mock=False)
    transport._resource = exact_handle
    transport._resource_str = "GPIB0::12::INSTR"
    transport._session_open = True
    operation = asyncio.create_task(transport.write("OUTPUT 0"))
    try:
        assert await asyncio.to_thread(write_entered.wait, 1.0)
        operation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await operation
        with pytest.raises(GPIBIncompleteCloseError, match="still running|incomplete"):
            await transport.close()
        assert transport._resource is exact_handle
        assert transport._terminal_unsettled is True

        release_write.set()
        assert await asyncio.to_thread(transport._open_settled.wait, 2.0)
        assert closes == [exact_handle]
        assert transport._resource is None
        assert transport._session_open is False
        assert transport._terminal_unsettled is False
    finally:
        release_write.set()
        await asyncio.gather(operation, return_exceptions=True)
        if transport._executor is not None:
            transport._executor.shutdown(wait=False, cancel_futures=True)


@pytest.mark.asyncio
async def test_usbtmc_mock_queries_require_exact_allowlisted_commands() -> None:
    from cryodaq.drivers.transport.usbtmc import USBTMCTransport

    transport = USBTMCTransport(mock=True)
    nonce = "a" * 32
    known = {
        "*IDN?": "Keithley Instruments Inc., Model 2604B, MOCK00001, 3.0.0",
        "print(smua.measure.iv())": "0.01\t5.0",
        "print(smub.source.output)": "0",
        "print(smua.source.compliance)": "false",
        "print(errorqueue.count)": "0",
        "print(CRYODAQ_WDOG_VERSION)": "3",
        "print(cryodaq_wdog_tripped)": "0",
        f'print(string.format("CRYODAQ_OFF_V1|{nonce}|%g", smua.source.output))': (f"CRYODAQ_OFF_V1|{nonce}|0"),
    }
    for command, expected in known.items():
        assert await transport.query(command) == expected

    buffer_query = "printbuffer(1, 4, smub.nvbuffer1.timestamps, smub.nvbuffer1.sourcevalues, smub.nvbuffer1)"
    assert await transport.query(buffer_query) == "0.5\t5.0\t0.01"

    unsupported = [
        "print(unknown_value)",
        " print(smua.measure.iv())",
        "print(smua.measure.iv()) ",
        "prefix-print(smua.measure.iv())",
        "print(smua.measure.iv())-suffix",
        "print(smua.measure.iv( ))",
        f'print(string.format("CRYODAQ_OFF_V1|{nonce}|%g", smua.source.output))extra',
    ]
    for command in unsupported:
        transport = USBTMCTransport(mock=True)
        with pytest.raises(ValueError, match="unsupported USBTMC mock query"):
            await transport.query(command)
        assert transport._query_desynchronized is True
        with pytest.raises(RuntimeError, match="quarantined"):
            await transport.query("*IDN?")
        await transport.write("smua.source.output = smua.OUTPUT_OFF")


@pytest.mark.asyncio
async def test_gpib_late_failed_query_is_quarantined_until_fresh_recovery(
    monkeypatch,
) -> None:
    import asyncio

    from cryodaq.drivers.transport.gpib import GPIBTransport

    started = threading.Event()
    release = threading.Event()

    class _Resource:
        timeout = 3000

        def __init__(self) -> None:
            self.writes: list[str] = []
            self.read_calls = 0
            self.clear_calls = 0

        def write(self, command: str) -> None:
            self.writes.append(command)

        def read(self) -> str:
            self.read_calls += 1
            if self.read_calls == 1:
                started.set()
                assert release.wait(3.0)
            raise OSError("late GPIB read failure")

        def clear(self) -> None:
            self.clear_calls += 1

        def close(self) -> None:
            return None

    resource = _Resource()
    transport = GPIBTransport(mock=False)
    transport._resource_str = "GPIB0::12::INSTR"
    transport._bus_prefix = "GPIB0"
    transport._resource = resource
    task = asyncio.create_task(transport.query("KRDG?"))
    assert await asyncio.to_thread(started.wait, 1.0)

    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert transport._open_settled.wait(5.0)
    assert transport._query_desynchronized is True

    writes_before_refusal = list(resource.writes)
    with pytest.raises(RuntimeError, match="quarantined"):
        await transport.query("KRDG? 1")
    assert resource.writes == writes_before_refusal

    off_command = "OUTPUT 0"
    with pytest.raises(RuntimeError, match="quarantined"):
        await transport.write(off_command)
    assert resource.writes == writes_before_refusal
    # Cancellation settles and closes the retained handle; recovery cannot
    # operate on a retired generation.  A fresh validated open is required.
    assert await transport.clear_bus() is False

    reopened = _Resource()

    def _reopen(generation, _resource_str, _bus_prefix, _timeout_ms) -> None:
        with transport._state_lock:
            if generation == transport._open_generation:
                transport._resource = reopened
                transport._session_open = True
        transport._settle_executor_operation()

    monkeypatch.setattr(transport, "_blocking_connect", _reopen)
    await transport.open("GPIB0::12::INSTR")
    monkeypatch.setattr(transport, "_blocking_ifc", lambda: True)
    assert await transport.recover() is True
    await transport.close()


@pytest.mark.asyncio
async def test_gpib_cancelled_successful_query_closes_retained_handle() -> None:
    import asyncio

    from cryodaq.drivers.transport.gpib import GPIBTransport

    started = threading.Event()
    release = threading.Event()

    class _Resource:
        timeout = 3000

        def __init__(self) -> None:
            self.read_calls = 0

        def write(self, _command: str) -> None:
            return None

        def read(self) -> str:
            self.read_calls += 1
            if self.read_calls == 1:
                started.set()
                assert release.wait(3.0)
                return "discarded-success"
            return "next-response"

        def close(self) -> None:
            return None

    transport = GPIBTransport(mock=False)
    transport._resource_str = "GPIB0::12::INSTR"
    transport._resource = _Resource()
    task = asyncio.create_task(transport.query("first"))
    assert await asyncio.to_thread(started.wait, 1.0)

    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert transport._open_settled.wait(5.0)

    assert transport._query_desynchronized is False
    assert transport._resource is None
    with pytest.raises(RuntimeError, match="not connected"):
        await transport.query("second")


@pytest.mark.asyncio
async def test_gpib_cancelled_queued_query_keeps_settlement_owner() -> None:
    import asyncio

    from cryodaq.drivers.transport.gpib import GPIBTransport

    blocker_started = threading.Event()
    blocker_release = threading.Event()
    calls: list[tuple[str, str | None]] = []

    class _Resource:
        timeout = 3000

        def write(self, command: str) -> None:
            calls.append(("write", command))

        def read(self) -> str:
            calls.append(("read", None))
            return "settled-response"

        def close(self) -> None:
            return None

    transport = GPIBTransport(mock=False)
    transport._resource_str = "GPIB0::12::INSTR"
    transport._resource = _Resource()
    executor = transport._get_executor()

    def _block_executor() -> None:
        blocker_started.set()
        assert blocker_release.wait(3.0)

    executor.submit(_block_executor)
    assert await asyncio.to_thread(blocker_started.wait, 1.0)

    task = asyncio.create_task(transport.query("queued"))
    for _ in range(100):
        if not transport._open_settled.is_set():
            break
        await asyncio.sleep(0)
    assert transport._open_settled.is_set() is False

    task.cancel()
    await asyncio.sleep(0)
    # Cancellation returns immediately; the retained executor owner settles
    # the queued VISA call before the next generation is admitted.
    assert task.done() is True
    blocker_release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert transport._open_settled.wait(5.0)
    assert transport._query_desynchronized is False
    assert calls == [("write", "queued"), ("read", None)]
    assert transport._resource is None
    with pytest.raises(RuntimeError, match="not connected"):
        await transport.query("next")


@pytest.mark.asyncio
async def test_gpib_executor_submission_failure_restores_settlement() -> None:
    from concurrent.futures import ThreadPoolExecutor

    from cryodaq.drivers.transport.gpib import GPIBTransport

    class _Resource:
        def write(self, _command: str) -> None:
            return None

    transport = GPIBTransport(mock=False)
    transport._resource = _Resource()
    executor = ThreadPoolExecutor(max_workers=1)
    executor.shutdown(wait=True)
    transport._executor = executor

    with pytest.raises(RuntimeError, match="cannot schedule new futures"):
        await transport.write("OUTPUT 0")

    assert transport._open_settled.is_set() is True


@pytest.mark.asyncio
async def test_gpib_query_quarantine_survives_close_and_open(monkeypatch) -> None:
    from cryodaq.drivers.transport.gpib import GPIBTransport

    class _FailedResource:
        timeout = 3000

        def write(self, _command: str) -> None:
            return None

        def read(self) -> str:
            raise OSError("GPIB response provenance lost")

        def clear(self) -> None:
            return None

        def close(self) -> None:
            return None

    class _ReopenedResource:
        def __init__(self) -> None:
            self.writes: list[str] = []

        def write(self, command: str) -> None:
            self.writes.append(command)

        def close(self) -> None:
            return None

    transport = GPIBTransport(mock=False)
    transport._resource_str = "GPIB0::12::INSTR"
    transport._resource = _FailedResource()
    with pytest.raises(OSError, match="provenance lost"):
        await transport.query("KRDG?")
    await transport.close()

    reopened = _ReopenedResource()

    def _reopen(generation, _resource_str, _bus_prefix, _timeout_ms) -> None:
        with transport._state_lock:
            if generation == transport._open_generation:
                transport._resource = reopened
        transport._settle_executor_operation()

    monkeypatch.setattr(transport, "_blocking_connect", _reopen)
    await transport.open("GPIB0::12::INSTR")

    with pytest.raises(RuntimeError, match="quarantined"):
        await transport.query("KRDG? 1")
    assert reopened.writes == []
    with pytest.raises(RuntimeError, match="quarantined"):
        await transport.write("OUTPUT 0")
    assert reopened.writes == []
    await transport.close()
