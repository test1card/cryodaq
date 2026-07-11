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
