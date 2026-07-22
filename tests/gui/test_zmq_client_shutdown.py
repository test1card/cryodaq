from __future__ import annotations

import contextlib
import os
import queue
import subprocess
import sys
import threading
from concurrent.futures import Future
from pathlib import Path

import pytest

import cryodaq.gui.zmq_client as zmq_client
from cryodaq.gui.zmq_client import ZmqBridge


def test_restart_settles_old_reply_consumer_before_queue_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = ZmqBridge()
    bridge._last_snapshot_time = 123.0
    assert bridge.bridge_instance_id is not None
    close_attempted = threading.Event()

    class BlockingReplyQueue:
        def __init__(self) -> None:
            self.entered = threading.Event()
            self.release = threading.Event()

        def get(self, timeout=None):
            self.entered.set()
            self.release.wait()
            raise queue.Empty

        def get_nowait(self):
            raise queue.Empty

        def cancel_join_thread(self) -> None:
            pass

        def close(self) -> None:
            close_attempted.set()

    old_queue = BlockingReplyQueue()
    bridge._reply_queue = old_queue
    consumer = threading.Thread(target=bridge._consume_replies, daemon=True)
    bridge._reply_consumer = consumer
    consumer.start()
    assert old_queue.entered.wait(1.0)

    real_join = consumer.join
    consumer.join = lambda timeout=None: real_join(0)  # type: ignore[method-assign]
    monkeypatch.setattr(
        "cryodaq.gui.zmq_client.mp.Process",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("restart reached process spawn before old reply owner settled")
        ),
    )

    try:
        with pytest.raises(RuntimeError, match="reply consumer.*settle"):
            bridge.start()
        assert bridge._last_snapshot_time == 0.0
        assert bridge.bridge_instance_id is None
        assert bridge._reply_queue is old_queue
        assert not close_attempted.is_set()
        assert consumer.is_alive()
    finally:
        bridge._reply_stop.set()
        old_queue.release.set()
        real_join(1.0)
        assert not consumer.is_alive()
        for owned_queue in (
            bridge._data_queue,
            bridge._cmd_queue,
            bridge._reply_queue,
            bridge._snapshot_queue,
        ):
            with contextlib.suppress(Exception):
                owned_queue.cancel_join_thread()
            with contextlib.suppress(Exception):
                owned_queue.close()


def test_shutdown_drains_reply_emitted_during_terminal_child_join() -> None:
    bridge = ZmqBridge()
    retired_reply_queue: queue.Queue = queue.Queue()
    bridge._reply_queue = retired_reply_queue
    request_id = "late-terminal-reply"
    generation = bridge._generation
    owner: Future = Future()
    bridge._pending[request_id] = owner
    bridge._request_generation[request_id] = generation

    class TerminalProcess:
        exitcode = 0

        def join(self, timeout=None) -> None:
            del timeout
            retired_reply_queue.put({"_rid": request_id, "ok": True, "settled": "terminal"})

        def is_alive(self) -> bool:
            return False

    bridge._process = TerminalProcess()
    bridge.shutdown()

    result = bridge.reconcile_late_result(request_id, generation=generation)
    assert result is not None
    assert result.reply == {"ok": True, "settled": "terminal"}


def test_restart_routes_reply_arriving_during_retired_queue_settlement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = ZmqBridge()
    retired_reply_queue: queue.Queue = queue.Queue()
    bridge._reply_queue = retired_reply_queue
    request_id = "between-drains"
    generation = bridge._generation
    owner: Future = Future()
    bridge._pending[request_id] = owner
    bridge._request_generation[request_id] = generation

    class TriggerQueue:
        def __init__(self) -> None:
            self.triggered = False

        def get_nowait(self):
            if not self.triggered:
                self.triggered = True
                retired_reply_queue.put({"_rid": request_id, "ok": True, "settled": "during-retirement"})
            raise queue.Empty

        def cancel_join_thread(self) -> None:
            pass

        def close(self) -> None:
            pass

    class FakeProcess:
        pid = 123

        def __init__(self, *_args, **_kwargs) -> None:
            self._alive = False

        def start(self) -> None:
            self._alive = True

        def is_alive(self) -> bool:
            return self._alive

    class FakeThread:
        def __init__(self, *_args, **_kwargs) -> None:
            self._alive = False

        def start(self) -> None:
            self._alive = True

        def is_alive(self) -> bool:
            return self._alive

        def join(self, timeout=None) -> None:
            del timeout
            self._alive = False

    bridge._data_queue = TriggerQueue()
    monkeypatch.setattr(zmq_client.mp, "Process", FakeProcess)
    monkeypatch.setattr(zmq_client.threading, "Thread", FakeThread)

    try:
        bridge.start()
        replacement = owner.result(timeout=1.0)
        assert replacement["request_id"] == request_id
        assert replacement["generation"] == generation
        assert replacement["outcome_unknown"] is True
        result = bridge.reconcile_late_result(request_id, generation=generation)
        assert result is not None
        assert result.reply == {"ok": True, "settled": "during-retirement"}
    finally:
        if bridge._reply_consumer is not None:
            bridge._reply_consumer.join()
        for owned_queue in (
            bridge._data_queue,
            bridge._cmd_queue,
            bridge._reply_queue,
            bridge._snapshot_queue,
        ):
            with contextlib.suppress(Exception):
                owned_queue.cancel_join_thread()
            with contextlib.suppress(Exception):
                owned_queue.close()


def test_shutdown_fails_closed_when_reply_consumer_does_not_settle() -> None:
    bridge = ZmqBridge()
    bridge._last_snapshot_time = 123.0

    class BlockingConsumer:
        def is_alive(self) -> bool:
            return True

        def join(self, timeout=None) -> None:
            del timeout

    bridge._reply_consumer = BlockingConsumer()

    with pytest.raises(RuntimeError, match="reply consumer.*settle"):
        bridge.shutdown()

    assert bridge._last_snapshot_time == 0.0
    assert bridge.bridge_instance_id is None
    bridge._reply_consumer = None
    for owned_queue in (
        bridge._data_queue,
        bridge._cmd_queue,
        bridge._reply_queue,
        bridge._snapshot_queue,
    ):
        with contextlib.suppress(Exception):
            owned_queue.cancel_join_thread()
        with contextlib.suppress(Exception):
            owned_queue.close()


def test_application_close_settles_all_real_qthreads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Deferred QObject deletion can abort the interpreter when this scenario
    # shares a QApplication polluted by hundreds of prior GUI tests.  Run the
    # real boundary in a fresh process: a Qt abort remains a hard non-zero test
    # failure, while unrelated suite-owned windows cannot corrupt the result.
    child_marker = "CRYODAQ_QTHREAD_SHUTDOWN_PROBE"
    if os.environ.get(child_marker) != "1":
        env = os.environ.copy()
        env[child_marker] = "1"
        env["QT_QPA_PLATFORM"] = "offscreen"
        repo_root = Path(__file__).resolve().parents[2]
        env["PYTHONPATH"] = str(repo_root / "src")
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "--basetemp",
                str(tmp_path / "isolated-shutdown"),
                f"{Path(__file__).resolve()}::test_application_close_settles_all_real_qthreads",
                "-q",
            ],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, (
            f"isolated QThread shutdown probe failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        return

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QCoreApplication, QEvent, QObject, QThread
    from PySide6.QtWidgets import QApplication
    from shiboken6 import isValid

    from cryodaq.gui.shell.main_window_v2 import MainWindowV2

    app = QApplication.instance() or QApplication([])
    window = MainWindowV2()
    nested_owner = QObject(window)
    deferred_owner = QObject(window)
    entered = threading.Event()
    entered_ids: set[str] = set()
    exited_ids: set[str] = set()
    callbacks: list[dict] = []
    state_lock = threading.Lock()

    def blocking_send(
        cmd: dict,
        *,
        cancellation_requested: threading.Event | None = None,
    ) -> dict:
        assert cancellation_requested is not None
        with state_lock:
            entered_ids.add(cmd["id"])
            if len(entered_ids) == 3:
                entered.set()
        assert cancellation_requested.wait(2.0)
        with state_lock:
            exited_ids.add(cmd["id"])
        return {"ok": False, "cancelled": True}

    monkeypatch.setattr(zmq_client, "send_command", blocking_send)
    workers = [
        zmq_client.ZmqCommandWorker({"cmd": "mutate", "id": "root"}, parent=window),
        zmq_client.ZmqCommandWorker(
            {"cmd": "mutate", "id": "nested-1"},
            parent=nested_owner,
        ),
        zmq_client.ZmqCommandWorker(
            {"cmd": "mutate", "id": "nested-2"},
            parent=deferred_owner,
        ),
    ]
    for worker in workers:
        worker.finished.connect(callbacks.append)
        worker.start()
    assert entered.wait(1.0)
    window.show()
    app.processEvents()
    deferred_owner.deleteLater()

    try:
        window.close()
        app.processEvents()
        assert not window.isVisible()
        assert entered_ids == {"root", "nested-1", "nested-2"}
        assert exited_ids == entered_ids
        assert callbacks == []
        assert all(worker.isFinished() and not worker.isRunning() for worker in workers)
        assert all(worker._cancellation_requested.is_set() for worker in workers)
        assert not any(thread.isRunning() for thread in window.findChildren(QThread))
        window.deleteLater()
        for _ in range(3):
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            app.processEvents()
        assert callbacks == []
        assert not isValid(deferred_owner)
        assert not isValid(window)
        assert all(not isValid(worker) for worker in workers)
    finally:
        for worker in workers:
            if isValid(worker) and worker.isRunning():
                worker.requestInterruption()
                worker.wait(2_000)
        if isValid(window):
            window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            app.processEvents()
