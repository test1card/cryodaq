"""Real process, thread, queue-owner, and lock proof for launcher shutdown."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
import threading
from types import MethodType, SimpleNamespace
from unittest.mock import MagicMock

import pytest

from cryodaq.instance_lock import release_lock_exact, try_acquire_lock
from cryodaq.launcher import LauncherWindow, _pump_engine_stderr


class _Timer:
    def stop(self) -> None:
        return None


class _ThreadWorker:
    """Small QThread-shaped owner backed by a real non-daemon thread."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.thread = threading.Thread(target=self.release.wait, name="launcher-safety-worker")
        self.thread.start()

    def isFinished(self) -> bool:  # noqa: N802 - mirrors QThread
        return not self.thread.is_alive()

    def wait(self, timeout_ms: int) -> None:
        self.thread.join(timeout_ms / 1000)


class _Bridge:
    def __init__(self, worker: _ThreadWorker) -> None:
        self.worker = worker
        self.shutdown_calls = 0
        self.close_calls = 0

    def shutdown(self) -> None:
        self.shutdown_calls += 1
        self.worker.release.set()

    def close(self) -> None:
        if not self.worker.isFinished():
            raise RuntimeError("worker was not settled before bridge terminal close")
        self.close_calls += 1


def _sleeping_process(*, stderr: bool = False) -> subprocess.Popen[bytes]:
    script = "import sys,time; sys.stderr.write('ready\\n'); sys.stderr.flush(); time.sleep(60)"
    return subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE if stderr else subprocess.DEVNULL,
    )


def _settle_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


@pytest.mark.parametrize("iteration", range(3))
def test_real_launcher_shutdown_settles_every_owner_before_releasing_lock(tmp_path, iteration: int) -> None:
    lock_name = f".launcher-{iteration}.lock"
    lock_fd = try_acquire_lock(lock_name, lock_dir=tmp_path)
    assert lock_fd is not None
    replacement_fd: int | None = None
    engine: subprocess.Popen[bytes] | None = None
    assistant: subprocess.Popen[bytes] | None = None
    worker = _ThreadWorker()
    loop = asyncio.new_event_loop()
    handler = logging.NullHandler()
    stderr_logger = logging.getLogger(f"cryodaq.test.shutdown.{iteration}")
    stderr_logger.propagate = False
    stderr_logger.addHandler(handler)
    stderr_thread: threading.Thread | None = None

    try:
        engine = _sleeping_process(stderr=True)
        assert engine.stderr is not None
        stderr_thread = threading.Thread(
            target=_pump_engine_stderr,
            args=(engine.stderr, stderr_logger),
            name="engine-stderr-pump",
            daemon=True,
        )
        stderr_thread.start()
        assistant = _sleeping_process()
        bridge = _Bridge(worker)
        app = MagicMock(name="application")
        tray = MagicMock(name="tray")
        host = SimpleNamespace(
            _shutdown_requested=False,
            _restart_pending=True,
            _assistant_restart_pending=True,
            _health_timer=_Timer(),
            _data_timer=_Timer(),
            _status_timer=_Timer(),
            _async_timer=_Timer(),
            _tray=tray,
            _tray_icon_red=None,
            _tray_icon_yellow=None,
            _stop_engine_down_alarm=lambda: None,
            _invalidate_descriptor_transport=lambda: None,
            _snapshot_ingress=None,
            _assistant_proc=assistant,
            _assistant_shutdown_path=None,
            _assistant_shutdown_authority=None,
            _bridge=bridge,
            _safety_worker=worker,
            _engine_proc=engine,
            _engine_external=False,
            _engine_stderr_thread=stderr_thread,
            _engine_stderr_logger=stderr_logger,
            _engine_stderr_handler=handler,
            _soak_artifact_capability=None,
            _soak_bridge_handshake=None,
            _loop=loop,
            _app=app,
        )
        host._stop_assistant = MethodType(LauncherWindow._stop_assistant, host)
        host._stop_engine = MethodType(LauncherWindow._stop_engine, host)
        host._close_engine_stderr_stream = MethodType(LauncherWindow._close_engine_stderr_stream, host)

        assert try_acquire_lock(lock_name, lock_dir=tmp_path) is None
        assert LauncherWindow._do_shutdown(host) is True

        assert assistant.poll() is not None
        assert engine.poll() is not None
        assert not worker.thread.is_alive()
        assert not stderr_thread.is_alive()
        assert host._safety_worker is None
        assert host._engine_stderr_thread is None
        assert bridge.shutdown_calls == 1
        assert bridge.close_calls == 1
        assert loop.is_closed()
        app.quit.assert_called_once_with()
        tray.hide.assert_called_once_with()

        # The launcher lock belongs to main(), outside LauncherWindow. It must
        # remain held even after owner settlement until the Qt loop returns.
        assert try_acquire_lock(lock_name, lock_dir=tmp_path) is None
        release_lock_exact(lock_fd, lock_name, lock_dir=tmp_path)
        lock_fd = None
        replacement_fd = try_acquire_lock(lock_name, lock_dir=tmp_path)
        assert replacement_fd is not None
    finally:
        worker.release.set()
        worker.thread.join(timeout=3)
        _settle_process(assistant)
        _settle_process(engine)
        if stderr_thread is not None:
            stderr_thread.join(timeout=3)
        if handler in stderr_logger.handlers:
            stderr_logger.removeHandler(handler)
            handler.close()
        if replacement_fd is not None:
            release_lock_exact(replacement_fd, lock_name, lock_dir=tmp_path)
        if lock_fd is not None:
            release_lock_exact(lock_fd, lock_name, lock_dir=tmp_path)
