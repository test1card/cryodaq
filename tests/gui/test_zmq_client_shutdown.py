from __future__ import annotations

import contextlib
import os
import queue
import subprocess
import sys
import threading
from concurrent.futures import Future
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import cryodaq.gui.zmq_client as zmq_client
from cryodaq.gui.zmq_client import ZmqBridge


@dataclass
class _FakeProcess:
    exit_after: str | None
    calls: list[str] = field(default_factory=list)
    exitcode: int | None = None
    _alive: bool = True

    def is_alive(self) -> bool:
        self.calls.append("is_alive")
        return self._alive

    def join(self, timeout: float) -> None:
        self.calls.append(f"join:{timeout:g}")
        if self.exit_after == "join" and self.calls.count("join:3") == 1:
            self._exit(0)
        elif self.exit_after == "terminate" and "terminate" in self.calls:
            self._exit(-15)
        elif self.exit_after == "kill" and "kill" in self.calls:
            self._exit(-9)

    def terminate(self) -> None:
        self.calls.append("terminate")

    def kill(self) -> None:
        self.calls.append("kill")

    def _exit(self, exitcode: int) -> None:
        self._alive = False
        self.exitcode = exitcode


class _FakeReplyConsumer:
    def __init__(self, *, stops: bool = True) -> None:
        self._alive = True
        self._stops = stops
        self.calls: list[str] = []

    def is_alive(self) -> bool:
        self.calls.append("is_alive")
        return self._alive

    def join(self, timeout: float) -> None:
        self.calls.append(f"join:{timeout:g}")
        if self._stops:
            self._alive = False


def _bridge(process: _FakeProcess, *, reply_stops: bool = True) -> tuple[ZmqBridge, _FakeReplyConsumer]:
    bridge = ZmqBridge()
    reply = _FakeReplyConsumer(stops=reply_stops)
    bridge._process = process  # type: ignore[assignment]
    bridge._reply_consumer = reply  # type: ignore[assignment]
    bridge._last_snapshot_time = 123.0
    return bridge, reply


@pytest.mark.parametrize(
    ("exit_after", "expected_process_calls"),
    [
        ("join", ["join:3"]),
        ("terminate", ["join:3", "terminate", "join:2"]),
        ("kill", ["join:3", "terminate", "join:2", "kill", "join:2"]),
    ],
)
def test_shutdown_clears_ownership_only_after_process_and_reply_consumer_settle(
    exit_after: str,
    expected_process_calls: list[str],
) -> None:
    process = _FakeProcess(exit_after=exit_after)
    bridge, reply = _bridge(process)

    bridge.shutdown()

    assert [call for call in process.calls if call != "is_alive"] == expected_process_calls
    assert reply.calls == ["is_alive", "join:3", "is_alive"]
    assert bridge._process is None
    assert bridge._reply_consumer is None
    assert bridge._last_snapshot_time == 0.0

    # A proven shutdown remains idempotent.
    bridge.shutdown()


def test_shutdown_retains_process_handle_when_child_survives_kill() -> None:
    process = _FakeProcess(exit_after=None)
    bridge, _reply = _bridge(process)

    with pytest.raises(RuntimeError, match="subprocess remained alive after kill and join"):
        bridge.shutdown()

    assert [call for call in process.calls if call != "is_alive"] == [
        "join:3",
        "terminate",
        "join:2",
        "kill",
        "join:2",
    ]
    assert process.exitcode is None
    assert bridge._process is process
    assert bridge._last_snapshot_time == 0.0


def test_shutdown_retains_ownership_when_reply_consumer_does_not_stop() -> None:
    process = _FakeProcess(exit_after="join")
    bridge, reply = _bridge(process, reply_stops=False)

    with pytest.raises(RuntimeError, match="reply consumer remained alive after join"):
        bridge.shutdown()

    assert reply._alive is True
    assert process._alive is False
    assert bridge._reply_consumer is reply
    assert bridge._process is process


def test_start_refuses_to_replace_ownership_when_old_reply_consumer_survives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _FakeProcess(exit_after=None)
    process._exit(0)
    bridge, reply = _bridge(process, reply_stops=False)
    old_snapshot_queue = bridge._snapshot_queue
    process_factory = MagicMock(name="Process")
    thread_factory = MagicMock(name="Thread")
    monkeypatch.setattr("cryodaq.gui.zmq_client.mp.Process", process_factory)
    monkeypatch.setattr("cryodaq.gui.zmq_client.threading.Thread", thread_factory)

    with pytest.raises(
        RuntimeError,
        match="previous reply consumer remained alive after stop and join",
    ):
        bridge.start()

    assert bridge._last_snapshot_time == 0.0
    assert bridge._reply_consumer is reply
    assert bridge._reply_stop.is_set()
    assert bridge._process is process
    assert bridge._snapshot_queue is old_snapshot_queue
    assert reply.calls == ["is_alive", "join:1", "is_alive"]
    process_factory.assert_not_called()
    thread_factory.assert_not_called()


def test_terminal_close_settles_then_closes_all_parent_queues() -> None:
    process = _FakeProcess(exit_after="join")
    bridge, _reply = _bridge(process)

    bridge.close()

    assert bridge._terminal_closed is True
    assert bridge._terminal_queues_closed == {"data", "command", "reply", "snapshot"}
    assert bridge._terminal_queues_joined == {"data", "command", "reply", "snapshot"}
    assert bridge._process is None
    assert bridge._reply_consumer is None
    bridge.close()  # exact terminal close is idempotent
    with pytest.raises(RuntimeError, match="terminally closed"):
        bridge.start()


def test_terminal_close_retains_queues_when_process_survives() -> None:
    process = _FakeProcess(exit_after=None)
    bridge, _reply = _bridge(process)

    with pytest.raises(RuntimeError, match="subprocess remained alive"):
        bridge.close()

    assert bridge._terminal_closed is False
    assert bridge._terminal_queues_closed == set()
    assert bridge._terminal_queues_joined == set()
    assert bridge._process is process


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
