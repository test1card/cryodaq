"""Verify GPIB/USBTMC transports use dedicated executors (Phase 2b F.2 + F.1)."""

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


@pytest.mark.asyncio
async def test_usbtmc_transport_no_default_executor():
    """Behavioral proof: non-mock query() and write() must dispatch to the
    transport's OWN single-worker executor, never the default (None) executor."""
    import asyncio

    from cryodaq.drivers.transport.usbtmc import USBTMCTransport

    class _FakeResource:
        def write(self, *a, **k) -> None: ...
        def write_raw(self, *a, **k) -> None: ...
        def query(self, *a, **k) -> str:
            return ""

    transport = USBTMCTransport(mock=False)
    transport._resource_str = "USB0::MOCK::INSTR"
    transport._resource = _FakeResource()

    loop = asyncio.get_running_loop()
    captured: list[object] = []

    def spy(executor, func, *args):
        captured.append(executor)
        fut = loop.create_future()
        fut.set_result("")
        return fut

    with patch.object(loop, "run_in_executor", side_effect=spy):
        await transport.query("print(smua.measure.iv())")
        await transport.write("smua.source.output = 0")

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


def test_usbtmc_get_executor_creates_single_worker_pool():
    from cryodaq.drivers.transport.usbtmc import USBTMCTransport

    t = USBTMCTransport(mock=True)
    ex = t._get_executor()
    assert isinstance(ex, ThreadPoolExecutor)
    assert ex._max_workers == 1
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
async def test_usbtmc_close_shuts_down_executor():
    """Behavioral: after close(), _executor must be None (shutdown was called)."""
    from cryodaq.drivers.transport.usbtmc import USBTMCTransport

    transport = USBTMCTransport(mock=False)
    transport._resource_str = "USB0::MOCK::INSTR"

    class _Resource:
        def close(self) -> None:
            return None

    class _Manager:
        def close(self) -> None:
            return None

    transport._resource = _Resource()
    transport._rm = _Manager()
    _ = transport._get_executor()
    assert transport._executor is not None

    await transport.close()
    assert transport._executor is None, "close() must shut down and clear _executor"


@pytest.mark.asyncio
async def test_usbtmc_owned_handle_close_failure_marks_transport_terminal(
    monkeypatch,
    caplog,
) -> None:
    import logging

    import cryodaq.drivers.transport.usbtmc as usbtmc_module
    from cryodaq.drivers.transport.usbtmc import USBTMCTransport

    def _fail_close(*_args, **_kwargs) -> bool:
        raise OSError("owned close failed")

    transport = USBTMCTransport(mock=False)
    monkeypatch.setattr(usbtmc_module, "_run_with_timeout", _fail_close)

    with caplog.at_level(logging.CRITICAL), pytest.raises(OSError, match="owned close failed"):
        await transport._settle_handle_close(object(), object())

    assert transport._close_incomplete is True
    assert "owned handle-close task failed" in caplog.text


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


@pytest.mark.asyncio
async def test_usbtmc_close_releases_partial_manager_ownership():
    from cryodaq.drivers.transport.usbtmc import USBTMCTransport

    class _Manager:
        closed = False

        def close(self) -> None:
            self.closed = True

    transport = USBTMCTransport(mock=False)
    manager = _Manager()
    transport._rm = manager

    await transport.close()

    assert manager.closed
    assert transport._rm is None
    assert transport._resource is None


@pytest.mark.asyncio
async def test_usbtmc_close_failure_raises_typed_terminal_receipt_and_blocks_reopen(caplog):
    import logging

    from cryodaq.drivers.transport.usbtmc import USBTMCIncompleteCloseError, USBTMCTransport

    manager_closed = False

    class _Resource:
        def close(self) -> None:
            raise OSError("resource close failed")

    class _Manager:
        def close(self) -> None:
            nonlocal manager_closed
            manager_closed = True

    transport = USBTMCTransport(mock=False)
    transport._resource = _Resource()
    transport._rm = _Manager()

    with caplog.at_level(logging.CRITICAL), pytest.raises(USBTMCIncompleteCloseError, match="remains owned"):
        await transport.close()

    assert manager_closed is True
    assert transport._close_incomplete is True
    assert transport._resource is not None
    assert transport._rm is not None
    assert "resource close failed" in caplog.text
    with pytest.raises(RuntimeError, match="terminal"):
        await transport.open("USB0::REOPEN::INSTR")


def test_usbtmc_failed_open_cleanup_failure_is_terminal(caplog):
    import logging

    from cryodaq.drivers.transport.usbtmc import USBTMCTransport

    class _Manager:
        def open_resource(self, _resource_str: str):
            raise OSError("open failed")

        def close(self) -> None:
            raise RuntimeError("manager cleanup failed")

    transport = USBTMCTransport(mock=False)
    with patch("pyvisa.ResourceManager", return_value=_Manager()), caplog.at_level(logging.CRITICAL):
        with pytest.raises(OSError, match="open failed"):
            transport._blocking_open("USB0::BROKEN::INSTR")

    assert transport._close_incomplete is True
    assert "manager cleanup failed" in caplog.text


@pytest.mark.asyncio
async def test_usbtmc_cancelled_open_settles_and_closes_late_handles(monkeypatch):
    import asyncio

    from cryodaq.drivers.transport.usbtmc import USBTMCTransport

    started = threading.Event()
    release = threading.Event()
    worker_done = threading.Event()
    resource_closed = threading.Event()
    manager_closed = threading.Event()

    class _Resource:
        def close(self) -> None:
            resource_closed.set()

    class _Manager:
        def close(self) -> None:
            manager_closed.set()

    transport = USBTMCTransport(mock=False)
    transport._mark_query_desynchronized()
    transport._quarantine_clean_close = True

    def _late_open(_resource_str: str):
        started.set()
        assert release.wait(2.0)
        worker_done.set()
        return _Manager(), _Resource()

    monkeypatch.setattr(transport, "_blocking_open", _late_open)
    task = asyncio.create_task(transport.open("USB0::LATE::INSTR"))
    assert await asyncio.to_thread(started.wait, 1.0)

    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert worker_done.is_set()
    assert resource_closed.is_set()
    assert manager_closed.is_set()
    assert transport._resource is None
    assert transport._rm is None
    assert transport._executor is None
    assert transport._query_desynchronized is True
    with pytest.raises(RuntimeError, match="quarantined"):
        await transport.query("ordinary-query")

    def _recovered_open(_resource_str: str):
        return _Manager(), _Resource()

    monkeypatch.setattr(transport, "_blocking_open", _recovered_open)
    await transport.open("USB0::RECOVERED::INSTR")
    assert transport._query_desynchronized is False
    await transport.close()


@pytest.mark.asyncio
async def test_usbtmc_cancelled_open_preserves_cancellation_when_cleanup_task_fails(
    monkeypatch,
    caplog,
) -> None:
    import asyncio
    import logging

    from cryodaq.drivers.transport.usbtmc import USBTMCTransport

    started = threading.Event()
    release = threading.Event()
    transport = USBTMCTransport(mock=False)

    def _late_open(_resource_str: str):
        started.set()
        assert release.wait(2.0)
        return object(), object()

    def _failed_cleanup(_resource, _manager) -> bool:
        raise OSError("cleanup task failed")

    monkeypatch.setattr(transport, "_blocking_open", _late_open)
    monkeypatch.setattr(transport, "_blocking_close_handles", _failed_cleanup)
    task = asyncio.create_task(transport.open("USB0::FAILED-CLEANUP::INSTR"))
    assert await asyncio.to_thread(started.wait, 1.0)

    task.cancel()
    release.set()
    with caplog.at_level(logging.CRITICAL), pytest.raises(asyncio.CancelledError):
        await task

    assert transport._close_incomplete is True
    assert "cancelled-open cleanup failed" in caplog.text
    assert transport._executor is None


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["query", "write", "write_raw"])
async def test_usbtmc_cancelled_io_keeps_close_serialized_until_worker_settles(operation: str):
    import asyncio

    from cryodaq.drivers.transport.usbtmc import USBTMCTransport

    started = threading.Event()
    release = threading.Event()
    io_live = threading.Event()
    close_started = threading.Event()
    overlap: list[bool] = []

    class _Resource:
        timeout = 0

        def query(self, _command: str) -> str:
            io_live.set()
            started.set()
            assert release.wait(3.0)
            io_live.clear()
            return "0"

        def write(self, _command: str) -> None:
            io_live.set()
            started.set()
            assert release.wait(3.0)
            io_live.clear()

        def write_raw(self, _data: bytes) -> None:
            io_live.set()
            started.set()
            assert release.wait(3.0)
            io_live.clear()

        def close(self) -> None:
            overlap.append(io_live.is_set())
            close_started.set()

    class _Manager:
        def close(self) -> None:
            return None

    transport = USBTMCTransport(mock=False)
    transport._resource = _Resource()
    transport._rm = _Manager()
    if operation == "query":
        task = asyncio.create_task(transport.query("print(smua.source.output)"))
    elif operation == "write":
        task = asyncio.create_task(transport.write("smua.source.output = 0"))
    else:
        task = asyncio.create_task(transport.write_raw(b"smua.source.output = 0"))
    assert await asyncio.to_thread(started.wait, 1.0)

    task.cancel()
    task.cancel()  # repeated cancellation cannot release serialization ownership
    close_task = asyncio.create_task(transport.close())
    await asyncio.sleep(0.05)
    assert not close_started.is_set()

    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    await close_task

    assert close_started.is_set()
    assert overlap == [False]


@pytest.mark.asyncio
async def test_usbtmc_cancelled_io_preserves_cancellation_if_worker_fails() -> None:
    import asyncio

    from cryodaq.drivers.transport.usbtmc import USBTMCTransport

    started = threading.Event()
    release = threading.Event()

    class _Resource:
        timeout = 0

        def query(self, _command: str) -> str:
            started.set()
            assert release.wait(3.0)
            raise OSError("late worker failure")

        def close(self) -> None:
            return None

    class _Manager:
        def close(self) -> None:
            return None

    transport = USBTMCTransport(mock=False)
    transport._resource = _Resource()
    transport._rm = _Manager()
    task = asyncio.create_task(transport.query("print(smua.source.output)"))
    assert await asyncio.to_thread(started.wait, 1.0)

    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    await transport.close()


@pytest.mark.asyncio
async def test_usbtmc_wedged_cancelled_open_returns_bounded_and_reaps_late_handles(monkeypatch, caplog):
    import asyncio
    import logging

    from cryodaq.drivers.transport.usbtmc import USBTMCTransport

    started = threading.Event()
    release = threading.Event()
    resource_closed = threading.Event()
    manager_closed = threading.Event()

    class _Resource:
        def close(self) -> None:
            resource_closed.set()

    class _Manager:
        def close(self) -> None:
            manager_closed.set()

    transport = USBTMCTransport(mock=False)

    def _wedged_open(_resource_str: str):
        started.set()
        assert release.wait(5.0)
        return _Manager(), _Resource()

    monkeypatch.setattr(transport, "_blocking_open", _wedged_open)
    task = asyncio.create_task(transport.open("USB0::LATE::INSTR"))
    assert await asyncio.to_thread(started.wait, 1.0)
    task.cancel()

    with caplog.at_level(logging.CRITICAL), pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2.0)
    assert "late-handle reaper remains active" in caplog.text
    assert transport._resource is None
    assert transport._rm is None
    with pytest.raises(RuntimeError, match="still settling"):
        await transport.open("USB0::RETRY::INSTR")

    release.set()
    assert await asyncio.to_thread(resource_closed.wait, 2.0)
    assert await asyncio.to_thread(manager_closed.wait, 2.0)
    for _ in range(100):
        if transport._open_future is None:
            break
        await asyncio.sleep(0.01)
    assert transport._open_future is None
    assert transport._executor is None


@pytest.mark.asyncio
async def test_usbtmc_cancelled_timed_out_close_is_terminal() -> None:
    import asyncio

    from cryodaq.drivers.transport.usbtmc import USBTMCIncompleteCloseError, USBTMCTransport

    close_started = threading.Event()
    close_release = threading.Event()
    manager_closed = threading.Event()

    class _Resource:
        def close(self) -> None:
            close_started.set()
            assert close_release.wait(5.0)

    class _Manager:
        def close(self) -> None:
            manager_closed.set()

    transport = USBTMCTransport(mock=False)
    transport._resource = _Resource()
    transport._rm = _Manager()
    task = asyncio.create_task(transport.close())
    assert await asyncio.to_thread(close_started.wait, 1.0)

    task.cancel()
    task.cancel()
    with pytest.raises(USBTMCIncompleteCloseError, match="terminally quarantined"):
        await asyncio.wait_for(task, timeout=2.0)

    assert transport._close_incomplete is True
    with pytest.raises(RuntimeError, match="terminal"):
        await transport.open("USB0::UNSAFE-RETRY::INSTR")

    close_release.set()
    assert await asyncio.to_thread(manager_closed.wait, 2.0)


@pytest.mark.asyncio
async def test_usbtmc_late_open_close_timeout_is_bounded_and_terminal(monkeypatch) -> None:
    import asyncio

    from cryodaq.drivers.transport.usbtmc import USBTMCTransport

    open_started = threading.Event()
    open_release = threading.Event()
    close_started = threading.Event()
    close_release = threading.Event()
    manager_closed = threading.Event()

    class _Resource:
        def close(self) -> None:
            close_started.set()
            assert close_release.wait(5.0)

    class _Manager:
        def close(self) -> None:
            manager_closed.set()

    transport = USBTMCTransport(mock=False)

    def _wedged_open(_resource_str: str):
        open_started.set()
        assert open_release.wait(5.0)
        return _Manager(), _Resource()

    monkeypatch.setattr(transport, "_blocking_open", _wedged_open)
    task = asyncio.create_task(transport.open("USB0::LATE-CLOSE::INSTR"))
    assert await asyncio.to_thread(open_started.wait, 1.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2.0)

    open_release.set()
    assert await asyncio.to_thread(close_started.wait, 2.0)
    for _ in range(200):
        if transport._open_future is None:
            break
        await asyncio.sleep(0.01)

    assert transport._open_future is None
    assert transport._close_incomplete is True
    with pytest.raises(RuntimeError, match="terminal"):
        await transport.open("USB0::UNSAFE-RETRY::INSTR")

    close_release.set()
    assert await asyncio.to_thread(manager_closed.wait, 2.0)


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


@pytest.mark.asyncio
async def test_usbtmc_close_returns_even_if_executor_worker_is_blocked():
    from cryodaq.drivers.transport.usbtmc import USBTMCTransport

    transport = USBTMCTransport(mock=False)
    transport._resource_str = "USB0::MOCK::INSTR"

    class _Resource:
        def close(self) -> None:
            return None

    class _Manager:
        def close(self) -> None:
            return None

    transport._resource = _Resource()
    transport._rm = _Manager()
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

    assert elapsed < 2.5, f"USBTMC close blocked too long ({elapsed:.2f}s)"


@pytest.mark.asyncio
async def test_usbtmc_close_does_not_wait_for_saturated_default_executor() -> None:
    import asyncio

    from cryodaq.drivers.transport.usbtmc import USBTMCTransport

    loop = asyncio.get_running_loop()
    previous_default = getattr(loop, "_default_executor", None)
    saturated = ThreadPoolExecutor(max_workers=1)
    blocker_started = threading.Event()
    blocker_release = threading.Event()

    def _block_default_executor() -> None:
        blocker_started.set()
        blocker_release.wait(3.0)

    saturated.submit(_block_default_executor)
    assert blocker_started.wait(1.0)
    loop.set_default_executor(saturated)

    class _Handle:
        def close(self) -> None:
            return None

    transport = USBTMCTransport(mock=False)
    transport._resource = _Handle()
    transport._rm = _Handle()
    close_task = asyncio.create_task(transport.close())
    try:
        done, _pending = await asyncio.wait({close_task}, timeout=0.4)
        assert close_task in done, "USBTMC close queued behind the saturated default executor"
        await close_task
    finally:
        blocker_release.set()
        if not close_task.done():
            await close_task
        saturated.shutdown(wait=True)
        loop._default_executor = previous_default


@pytest.mark.asyncio
async def test_usbtmc_cancelled_open_cleanup_does_not_wait_for_saturated_default_executor(
    monkeypatch,
) -> None:
    import asyncio

    from cryodaq.drivers.transport.usbtmc import USBTMCTransport

    loop = asyncio.get_running_loop()
    previous_default = getattr(loop, "_default_executor", None)
    saturated = ThreadPoolExecutor(max_workers=1)
    blocker_started = threading.Event()
    blocker_release = threading.Event()
    open_started = threading.Event()
    open_release = threading.Event()

    def _block_default_executor() -> None:
        blocker_started.set()
        blocker_release.wait(3.0)

    saturated.submit(_block_default_executor)
    assert blocker_started.wait(1.0)
    loop.set_default_executor(saturated)

    class _Handle:
        def close(self) -> None:
            return None

    transport = USBTMCTransport(mock=False)

    def _late_open(_resource_str: str):
        open_started.set()
        assert open_release.wait(2.0)
        return _Handle(), _Handle()

    monkeypatch.setattr(transport, "_blocking_open", _late_open)
    open_task = asyncio.create_task(transport.open("USB0::LATE-CLEANUP::INSTR"))
    try:
        for _ in range(100):
            if open_started.is_set():
                break
            await asyncio.sleep(0.01)
        assert open_started.is_set()
        open_task.cancel()
        open_release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(open_task), timeout=0.4)
    finally:
        open_release.set()
        blocker_release.set()
        if not open_task.done():
            open_task.cancel()
        try:
            await open_task
        except asyncio.CancelledError:
            pass
        saturated.shutdown(wait=True)
        loop._default_executor = previous_default


@pytest.mark.asyncio
async def test_usbtmc_completed_late_open_callback_hands_cleanup_off_event_loop() -> None:
    import asyncio
    from concurrent.futures import Future

    from cryodaq.drivers.transport.usbtmc import USBTMCTransport

    close_started = threading.Event()
    close_release = threading.Event()

    class _Resource:
        def close(self) -> None:
            close_started.set()
            assert close_release.wait(2.0)

    class _Manager:
        def close(self) -> None:
            return None

    transport = USBTMCTransport(mock=False)
    completed: Future[tuple[object, object]] = Future()
    completed.set_result((_Manager(), _Resource()))
    transport._open_future = completed

    try:
        transport._start_late_open_reaper(completed)
        await asyncio.sleep(0)
        assert close_started.wait(0.2)
    finally:
        close_release.set()

    for _ in range(100):
        if transport._open_future is None:
            break
        await asyncio.sleep(0.01)
    assert transport._open_future is None


def test_usbtmc_bounded_close_propagates_process_control_exception() -> None:
    from cryodaq.drivers.transport.usbtmc import _run_with_timeout

    class _ProcessControl(BaseException):
        pass

    def _raise_process_control() -> None:
        raise _ProcessControl("terminate")

    with pytest.raises(_ProcessControl, match="terminate"):
        _run_with_timeout(_raise_process_control, timeout_s=1.0, label="test")


@pytest.mark.asyncio
async def test_usbtmc_queued_quarantine_rechecks_all_waiters_before_resource_access() -> None:
    import asyncio

    from cryodaq.drivers.transport.usbtmc import USBTMCTransport

    started = threading.Event()
    release = threading.Event()
    query_calls: list[str] = []
    writes: list[str] = []
    raw_writes: list[bytes] = []
    member_accesses: list[str] = []

    class _Resource:
        timeout = 0

        def __getattribute__(self, name: str):
            if name in {"query", "write", "write_raw"}:
                member_accesses.append(name)
            return object.__getattribute__(self, name)

        def query(self, command: str) -> str:
            query_calls.append(command)
            if command == "failing-query":
                started.set()
                assert release.wait(3.0)
                raise OSError("late USBTMC query failure")
            nonce = command.split("|")[1]
            return f"CRYODAQ_OFF_V1|{nonce}|0"

        def write(self, command: str) -> None:
            writes.append(command)

        def write_raw(self, data: bytes) -> None:
            raw_writes.append(data)

        def close(self) -> None:
            return None

    class _Manager:
        def close(self) -> None:
            return None

    transport = USBTMCTransport(mock=False)
    transport._resource = _Resource()
    transport._rm = _Manager()
    failing = asyncio.create_task(transport.query("failing-query"))
    assert await asyncio.to_thread(started.wait, 1.0)

    ordinary = asyncio.create_task(transport.write("smua.source.levelv = 1"))
    raw = asyncio.create_task(transport.write_raw(b"smua.source.output = smua.OUTPUT_OFF"))
    ordinary_query = asyncio.create_task(transport.query("queued-ordinary-query"))
    off = asyncio.create_task(transport.write("smua.source.output = smua.OUTPUT_OFF"))
    nonce = "a" * 32
    challenge_command = f'print(string.format("CRYODAQ_OFF_V1|{nonce}|%g", smua.source.output))'
    challenge = asyncio.create_task(transport.query(challenge_command))
    await asyncio.sleep(0)

    release.set()
    with pytest.raises(OSError, match="late USBTMC query failure"):
        await failing
    with pytest.raises(RuntimeError, match="quarantined"):
        await ordinary
    with pytest.raises(RuntimeError, match="quarantined"):
        await raw
    with pytest.raises(RuntimeError, match="quarantined"):
        await ordinary_query
    await off
    assert await challenge == f"CRYODAQ_OFF_V1|{nonce}|0"

    assert transport._query_desynchronized is True
    assert query_calls == ["failing-query", challenge_command]
    assert writes == ["smua.source.output = smua.OUTPUT_OFF"]
    assert raw_writes == []
    assert member_accesses == ["query", "write", "query"]
    await transport.close()


@pytest.mark.asyncio
async def test_usbtmc_cancelled_successful_query_does_not_poison_next_query() -> None:
    import asyncio

    from cryodaq.drivers.transport.usbtmc import USBTMCTransport

    started = threading.Event()
    release = threading.Event()
    calls = 0

    class _Resource:
        timeout = 0

        def query(self, _command: str) -> str:
            nonlocal calls
            calls += 1
            if calls == 1:
                started.set()
                assert release.wait(3.0)
                return "discarded-success"
            return "next-response"

        def close(self) -> None:
            return None

    class _Manager:
        def close(self) -> None:
            return None

    transport = USBTMCTransport(mock=False)
    transport._resource = _Resource()
    transport._rm = _Manager()
    task = asyncio.create_task(transport.query("first"))
    assert await asyncio.to_thread(started.wait, 1.0)

    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert transport._query_desynchronized is False
    assert await transport.query("second") == "next-response"
    await transport.close()


@pytest.mark.asyncio
async def test_usbtmc_query_quarantine_clears_only_after_clean_close_and_successful_open(monkeypatch) -> None:
    from cryodaq.drivers.transport.usbtmc import USBTMCTransport

    class _FailedResource:
        timeout = 0

        def query(self, _command: str) -> str:
            raise OSError("query framing lost")

        def close(self) -> None:
            return None

    class _Manager:
        def close(self) -> None:
            return None

    class _ReopenedResource:
        timeout = 0

        def __init__(self) -> None:
            self.query_calls = 0
            self.writes: list[str] = []

        def query(self, _command: str) -> str:
            self.query_calls += 1
            return "recovered"

        def write(self, command: str) -> None:
            self.writes.append(command)

        def close(self) -> None:
            return None

    transport = USBTMCTransport(mock=False)
    transport._resource = _FailedResource()
    transport._rm = _Manager()
    with pytest.raises(OSError, match="framing lost"):
        await transport.query("first")
    await transport.close()

    reopened = _ReopenedResource()

    async def _reopen(_resource_str: str) -> None:
        transport._resource = reopened
        transport._rm = _Manager()

    monkeypatch.setattr(transport, "_settle_open", _reopen)
    await transport.open("USB0::REOPENED::INSTR")

    assert transport._query_desynchronized is False
    assert await transport.query("second") == "recovered"
    assert reopened.query_calls == 1
    await transport.write("ordinary-write")
    assert reopened.writes == ["ordinary-write"]
    await transport.close()


@pytest.mark.asyncio
async def test_usbtmc_quarantine_allows_only_exact_off_traffic_and_fresh_challenges() -> None:
    from cryodaq.drivers.transport.usbtmc import USBTMCTransport

    query_calls: list[str] = []
    writes: list[str] = []
    raw_writes: list[bytes] = []

    class _Resource:
        timeout = 0

        def query(self, command: str) -> str:
            query_calls.append(command)
            nonce = command.split("|")[1]
            if nonce == "d" * 32:
                raise OSError("fresh challenge failed after transmission")
            return f"CRYODAQ_OFF_V1|{nonce}|0"

        def write(self, command: str) -> None:
            writes.append(command)

        def write_raw(self, data: bytes) -> None:
            raw_writes.append(data)

        def close(self) -> None:
            return None

    class _Manager:
        def close(self) -> None:
            return None

    transport = USBTMCTransport(mock=False)
    transport._resource = _Resource()
    transport._rm = _Manager()
    stale_nonce = "a" * 32
    stale_challenge = f'print(string.format("CRYODAQ_OFF_V1|{stale_nonce}|%g", smua.source.output))'
    assert await transport.query(stale_challenge) == f"CRYODAQ_OFF_V1|{stale_nonce}|0"
    transport._mark_query_desynchronized()

    allowed = [
        "smua.source.levelv = 0",
        "smub.source.levelv = 0",
        "smua.source.output = smua.OUTPUT_OFF",
        "smub.source.output = smub.OUTPUT_OFF",
    ]
    for command in allowed:
        await transport.write(command)

    rejected_writes = [
        " smua.source.levelv = 0",
        "smua.source.levelv = 0 ",
        "smua.source.levelv=0",
        "smua.source.levelv = 0.0",
        "smua.source.levelv = +0",
        "smua.source.levelv = 0 -- OFF",
        "smua.source.levelv = 0;smua.source.output = smua.OUTPUT_OFF",
        "prefix smua.source.output = smua.OUTPUT_OFF",
        "smua.source.output = smua.OUTPUT_OFF suffix",
        "SMUA.source.output = SMUA.OUTPUT_OFF",
        "smua.source.output = smub.OUTPUT_OFF",
    ]
    for command in rejected_writes:
        with pytest.raises(RuntimeError, match="quarantined"):
            await transport.write(command)
    with pytest.raises(RuntimeError, match="quarantined"):
        await transport.write_raw(b"smua.source.output = smua.OUTPUT_OFF")

    with pytest.raises(RuntimeError, match="quarantined"):
        await transport.query(stale_challenge)
    fresh_nonce = "b" * 32
    fresh_challenge = f'print(string.format("CRYODAQ_OFF_V1|{fresh_nonce}|%g", smub.source.output))'
    assert await transport.query(fresh_challenge) == f"CRYODAQ_OFF_V1|{fresh_nonce}|0"
    with pytest.raises(RuntimeError, match="quarantined"):
        await transport.query(fresh_challenge)
    failed_nonce = "d" * 32
    failed_challenge = f'print(string.format("CRYODAQ_OFF_V1|{failed_nonce}|%g", smua.source.output))'
    with pytest.raises(OSError, match="failed after transmission"):
        await transport.query(failed_challenge)
    with pytest.raises(RuntimeError, match="quarantined"):
        await transport.query(failed_challenge)

    rejected_queries = [
        "print(smua.source.output)",
        f" {fresh_challenge}",
        f"{fresh_challenge} ",
        f"{fresh_challenge};print(errorqueue.count)",
        f"{fresh_challenge} -- verify",
        f'print(string.format("CRYODAQ_OFF_V1|{"c" * 31}|%g", smua.source.output))',
        f'print(string.format("CRYODAQ_OFF_V1|{"C" * 32}|%g", smua.source.output))',
        f'print(string.format("CRYODAQ_OFF_V1|{"c" * 32}|%g", smuc.source.output))',
    ]
    for command in rejected_queries:
        with pytest.raises(RuntimeError, match="quarantined"):
            await transport.query(command)

    assert writes == allowed
    assert raw_writes == []
    assert query_calls == [stale_challenge, fresh_challenge, failed_challenge]
    await transport.close()


@pytest.mark.asyncio
async def test_usbtmc_quarantine_rejects_string_subclasses_before_resource_access() -> None:
    from cryodaq.drivers.transport.usbtmc import USBTMCTransport

    accesses: list[str] = []
    allowed_write = "smua.source.output = smua.OUTPUT_OFF"
    nonce = "e" * 32
    allowed_query = f'print(string.format("CRYODAQ_OFF_V1|{nonce}|%g", smua.source.output))'

    class _SpoofedWrite(str):
        def __hash__(self) -> int:
            return hash(allowed_write)

        def __eq__(self, other: object) -> bool:
            return other == allowed_write

    class _SpoofedQuery(str):
        def encode(self, *_args, **_kwargs) -> bytes:
            return b"smua.source.output = smua.OUTPUT_ON"

    class _Resource:
        def __getattribute__(self, name: str):
            if name in {"query", "write", "write_raw"}:
                accesses.append(name)
            return object.__getattribute__(self, name)

        def query(self, _command: str) -> str:
            return "must-not-run"

        def write(self, _command: str) -> None:
            return None

        def close(self) -> None:
            return None

    class _Manager:
        def close(self) -> None:
            return None

    transport = USBTMCTransport(mock=False)
    transport._resource = _Resource()
    transport._rm = _Manager()
    transport._mark_query_desynchronized()

    with pytest.raises(RuntimeError, match="quarantined"):
        await transport.write(_SpoofedWrite("smua.source.output = smua.OUTPUT_ON"))
    with pytest.raises(RuntimeError, match="quarantined"):
        await transport.query(_SpoofedQuery(allowed_query))
    assert accesses == []
    await transport.close()


@pytest.mark.asyncio
async def test_usbtmc_failed_cancelled_and_handleless_open_cannot_clear_quarantine(monkeypatch) -> None:
    import asyncio

    from cryodaq.drivers.transport.usbtmc import USBTMCTransport

    class _FailedResource:
        timeout = 0

        def query(self, _command: str) -> str:
            raise OSError("query framing lost")

        def close(self) -> None:
            return None

    class _Manager:
        def close(self) -> None:
            return None

    transport = USBTMCTransport(mock=False)
    transport._resource = _FailedResource()
    transport._rm = _Manager()
    with pytest.raises(OSError, match="framing lost"):
        await transport.query("poison")
    await transport.close()
    assert transport._quarantine_clean_close is True

    async def _failed_open(_resource_str: str) -> None:
        raise OSError("open failed")

    monkeypatch.setattr(transport, "_settle_open", _failed_open)
    with pytest.raises(OSError, match="open failed"):
        await transport.open("USB0::FAILED::INSTR")
    assert transport._query_desynchronized is True

    async def _cancelled_open(_resource_str: str) -> None:
        raise asyncio.CancelledError()

    monkeypatch.setattr(transport, "_settle_open", _cancelled_open)
    with pytest.raises(asyncio.CancelledError):
        await transport.open("USB0::CANCELLED::INSTR")
    assert transport._query_desynchronized is True

    async def _handleless_open(_resource_str: str) -> None:
        return None

    monkeypatch.setattr(transport, "_settle_open", _handleless_open)
    with pytest.raises(RuntimeError, match="without resource handles"):
        await transport.open("USB0::HANDLELESS::INSTR")
    assert transport._query_desynchronized is True

    for missing in ("resource", "manager"):
        partial = USBTMCTransport(mock=False)
        partial._mark_query_desynchronized()
        partial._quarantine_clean_close = True

        async def _partial_open(_resource_str: str, *, missing=missing) -> None:
            partial._resource = None if missing == "resource" else _FailedResource()
            partial._rm = None if missing == "manager" else _Manager()

        monkeypatch.setattr(partial, "_settle_open", _partial_open)
        with pytest.raises(RuntimeError, match="without resource handles"):
            await partial.open(f"USB0::MISSING-{missing.upper()}::INSTR")
        assert partial._query_desynchronized is True


@pytest.mark.asyncio
async def test_usbtmc_incomplete_or_noop_close_cannot_enable_quarantine_recovery() -> None:
    from cryodaq.drivers.transport.usbtmc import USBTMCIncompleteCloseError, USBTMCTransport

    class _Resource:
        timeout = 0

        def query(self, _command: str) -> str:
            raise OSError("query failed")

        def close(self) -> None:
            raise OSError("close failed")

    class _Manager:
        def close(self) -> None:
            return None

    transport = USBTMCTransport(mock=False)
    transport._resource = _Resource()
    transport._rm = _Manager()
    with pytest.raises(OSError, match="query failed"):
        await transport.query("poison")
    with pytest.raises(USBTMCIncompleteCloseError, match="retained VISA handle"):
        await transport.close()
    assert transport._quarantine_clean_close is False
    assert transport._close_incomplete is True
    with pytest.raises(RuntimeError, match="terminal"):
        await transport.open("USB0::UNSAFE::INSTR")

    noop = USBTMCTransport(mock=False)
    noop._mark_query_desynchronized()
    await noop.close()
    assert noop._quarantine_clean_close is False
    with pytest.raises(RuntimeError, match="completed clean close"):
        await noop.open("USB0::UNSAFE-NOOP::INSTR")


@pytest.mark.asyncio
async def test_usbtmc_cancelled_close_is_terminal_even_after_handle_settlement() -> None:
    import asyncio

    from cryodaq.drivers.transport.usbtmc import USBTMCIncompleteCloseError, USBTMCTransport

    close_started = threading.Event()
    close_release = threading.Event()

    class _Resource:
        timeout = 0

        def query(self, _command: str) -> str:
            raise OSError("query failed")

        def close(self) -> None:
            close_started.set()
            assert close_release.wait(3.0)

    class _Manager:
        def close(self) -> None:
            return None

    transport = USBTMCTransport(mock=False)
    transport._resource = _Resource()
    transport._rm = _Manager()
    with pytest.raises(OSError, match="query failed"):
        await transport.query("poison")

    close_task = asyncio.create_task(transport.close())
    assert await asyncio.to_thread(close_started.wait, 1.0)
    close_task.cancel()
    close_release.set()
    with pytest.raises(USBTMCIncompleteCloseError, match="terminally quarantined"):
        await close_task
    assert transport._close_incomplete is True
    with pytest.raises(RuntimeError, match="terminal"):
        await transport.open("USB0::UNSAFE-RECOVERY::INSTR")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["query", "write", "write_raw"])
async def test_usbtmc_cancelled_failed_executor_io_quarantines(operation: str) -> None:
    import asyncio

    from cryodaq.drivers.transport.usbtmc import USBTMCTransport

    started = threading.Event()
    release = threading.Event()

    class _Resource:
        timeout = 0

        def _fail(self) -> None:
            started.set()
            assert release.wait(3.0)
            raise OSError("cancelled worker failed")

        def query(self, _command: str) -> str:
            self._fail()
            raise AssertionError("unreachable")

        def write(self, _command: str) -> None:
            self._fail()

        def write_raw(self, _data: bytes) -> None:
            self._fail()

        def close(self) -> None:
            return None

    class _Manager:
        def close(self) -> None:
            return None

    transport = USBTMCTransport(mock=False)
    transport._resource = _Resource()
    transport._rm = _Manager()
    call = {
        "query": lambda: transport.query("failing-query"),
        "write": lambda: transport.write("ordinary-write"),
        "write_raw": lambda: transport.write_raw(b"ordinary-raw"),
    }[operation]
    task = asyncio.create_task(call())
    assert await asyncio.to_thread(started.wait, 1.0)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert transport._query_desynchronized is True
    await transport.close()


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
async def test_gpib_late_failed_query_is_quarantined_but_recovery_remains_available(
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
    assert await asyncio.to_thread(transport._open_settled.wait, 2.0)
    assert transport._query_desynchronized is True

    writes_before_refusal = list(resource.writes)
    with pytest.raises(RuntimeError, match="quarantined"):
        await transport.query("KRDG? 1")
    assert resource.writes == writes_before_refusal

    off_command = "OUTPUT 0"
    with pytest.raises(RuntimeError, match="quarantined"):
        await transport.write(off_command)
    assert resource.writes == writes_before_refusal
    assert await transport.clear_bus() is True
    monkeypatch.setattr(transport, "_blocking_ifc", lambda: True)
    assert await transport.send_ifc() is True
    await transport.close()


@pytest.mark.asyncio
async def test_gpib_cancelled_successful_query_does_not_poison_next_query() -> None:
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
    assert await asyncio.to_thread(transport._open_settled.wait, 2.0)

    assert transport._query_desynchronized is False
    assert await transport.query("second") == "next-response"
    await transport.close()


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

    assert await asyncio.to_thread(transport._open_settled.wait, 2.0)
    assert transport._query_desynchronized is False
    assert calls == [("write", "queued"), ("read", None)]
    assert await transport.query("next") == "settled-response"
    await transport.close()


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
