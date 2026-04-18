"""Verify GPIB/USBTMC transports use dedicated executors (Phase 2b F.2 + F.1)."""

from __future__ import annotations

import inspect
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest


def test_gpib_transport_no_default_executor():
    from cryodaq.drivers.transport.gpib import GPIBTransport

    src = inspect.getsource(GPIBTransport)
    assert "ThreadPoolExecutor" in src, "GPIBTransport must use a dedicated ThreadPoolExecutor"
    assert "run_in_executor(None" not in src, (
        "GPIBTransport must NOT use the default executor for VISA calls"
    )
    assert "_get_executor" in src


def test_usbtmc_transport_no_default_executor():
    from cryodaq.drivers.transport.usbtmc import USBTMCTransport

    src = inspect.getsource(USBTMCTransport)
    assert "ThreadPoolExecutor" in src
    assert "run_in_executor(None" not in src
    assert "_get_executor" in src


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


def test_gpib_close_shuts_down_executor():
    """The class source must call _executor.shutdown in the close path."""
    from cryodaq.drivers.transport import gpib

    src = inspect.getsource(gpib)
    assert "self._executor.shutdown" in src or "_executor.shutdown" in src


def test_usbtmc_close_shuts_down_executor():
    from cryodaq.drivers.transport import usbtmc

    src = inspect.getsource(usbtmc)
    assert "self._executor.shutdown" in src or "_executor.shutdown" in src


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
    assert all(r is first for r in results), (
        "Workers received different RM instances despite the lock"
    )
    assert len(GPIBTransport._resource_managers) == 1
    GPIBTransport._resource_managers.clear()


def test_close_all_managers_holds_rm_lock():
    """Codex Phase 2b Block B P1: close_all_managers must take _rm_lock."""
    import inspect

    from cryodaq.drivers.transport.gpib import GPIBTransport

    src = inspect.getsource(GPIBTransport.close_all_managers)
    assert "_rm_lock" in src, (
        "close_all_managers must hold _rm_lock — otherwise scheduler L3 "
        "recovery on one bus can race with _get_rm on healthy buses"
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
