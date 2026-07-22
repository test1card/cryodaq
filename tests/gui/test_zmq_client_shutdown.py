from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest

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
