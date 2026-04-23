from __future__ import annotations

import argparse
import json

import pytest

from tools import diag_zmq_b1_capture


class _FakeBridge:
    def __init__(self, *, alive: bool = True, reply: dict | None = None) -> None:
        self._alive = alive
        self._reply = reply or {"ok": True, "source": "bridge"}
        self.started = False
        self.stopped = False
        self.commands: list[dict] = []

    def start(self) -> None:
        self.started = True

    def is_alive(self) -> bool:
        return self._alive

    def shutdown(self) -> None:
        self.stopped = True

    def poll_readings(self):
        return []

    def send_command(self, cmd):
        assert cmd == {"cmd": "safety_status"}
        self.commands.append(cmd)
        return self._reply


def test_parse_args_defaults(tmp_path):
    output = tmp_path / "capture.jsonl"
    args = diag_zmq_b1_capture._parse_args(["--output", str(output)])
    assert args.duration == 180.0
    assert args.interval == 1.0
    assert args.output == output
    assert args.skip_direct_probe is False


def test_sample_once_merges_bridge_and_direct_probe(monkeypatch):
    bridge = _FakeBridge()

    monkeypatch.setattr(
        diag_zmq_b1_capture,
        "bridge_snapshot",
        lambda bridge, *, now=None: {"restart_count": 3, "bridge_alive": True},
    )
    monkeypatch.setattr(
        diag_zmq_b1_capture,
        "direct_engine_probe",
        lambda *, address, timeout_s: {"ok": True, "source": "direct"},
    )

    sample = diag_zmq_b1_capture._sample_once(
        bridge,
        address="tcp://127.0.0.1:5556",
        direct_timeout_s=5.0,
        skip_direct_probe=False,
    )

    assert sample["restart_count"] == 3
    assert sample["bridge_reply"] == {"ok": True, "source": "bridge"}
    assert sample["direct_reply"] == {"ok": True, "source": "direct"}


def test_sample_once_records_direct_probe_timeout(monkeypatch):
    bridge = _FakeBridge()

    monkeypatch.setattr(
        diag_zmq_b1_capture,
        "bridge_snapshot",
        lambda bridge, *, now=None: {"restart_count": 3, "bridge_alive": True},
    )

    def raise_timeout(*, address, timeout_s):
        raise TimeoutError("Engine did not reply within 5s")

    monkeypatch.setattr(
        diag_zmq_b1_capture,
        "direct_engine_probe",
        raise_timeout,
    )

    sample = diag_zmq_b1_capture._sample_once(
        bridge,
        address="tcp://127.0.0.1:5556",
        direct_timeout_s=5.0,
        skip_direct_probe=False,
    )

    assert sample["bridge_reply"] == {"ok": True, "source": "bridge"}
    assert sample["direct_reply"] == {
        "ok": False,
        "error": "Engine did not reply within 5s",
        "exception_type": "TimeoutError",
    }


def test_validate_bridge_startup_accepts_ready_bridge():
    bridge = _FakeBridge(alive=True, reply={"ok": True, "source": "bridge"})

    diag_zmq_b1_capture._validate_bridge_startup(bridge)

    assert bridge.commands == [{"cmd": "safety_status"}]


def test_validate_bridge_startup_rejects_dead_bridge():
    bridge = _FakeBridge(alive=False)

    with pytest.raises(RuntimeError, match="ZMQ bridge subprocess failed to start"):
        diag_zmq_b1_capture._validate_bridge_startup(bridge)


def test_validate_bridge_startup_rejects_error_reply():
    bridge = _FakeBridge(alive=True, reply={"ok": False, "error": "bridge unavailable"})

    with pytest.raises(
        RuntimeError,
        match=r"Bridge startup probe failed: .*'error': 'bridge unavailable'",
    ):
        diag_zmq_b1_capture._validate_bridge_startup(bridge)


def test_main_returns_nonzero_when_bridge_startup_fails(tmp_path, monkeypatch, capsys):
    output = tmp_path / "capture.jsonl"
    bridge = _FakeBridge(alive=True, reply={"ok": False, "error": "bridge unavailable"})

    monkeypatch.setattr(diag_zmq_b1_capture, "_parse_args", lambda argv=None: argparse.Namespace(
        output=output,
        duration=180.0,
        interval=1.0,
        address="tcp://127.0.0.1:5556",
        direct_timeout=5.0,
        skip_direct_probe=False,
    ))
    monkeypatch.setattr(diag_zmq_b1_capture, "ZmqBridge", lambda: bridge)
    monkeypatch.setattr(diag_zmq_b1_capture.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        diag_zmq_b1_capture,
        "run_capture",
        lambda *args, **kwargs: pytest.fail("run_capture should not be called"),
    )

    rc = diag_zmq_b1_capture.main()

    captured = capsys.readouterr()
    assert rc == 1
    assert "B1 capture aborted: Bridge startup probe failed:" in captured.err
    assert bridge.started is True
    assert bridge.stopped is True
    assert output.exists() is False


def test_run_capture_writes_jsonl(tmp_path, monkeypatch):
    bridge = _FakeBridge()
    output = tmp_path / "capture.jsonl"

    samples = iter(
        [
            {"seq": 1, "bridge_reply": {"ok": True}},
            {"seq": 2, "bridge_reply": {"ok": False}},
        ]
    )
    timeline = iter([0.0, 0.0, 1.0, 1.0, 2.1])

    monkeypatch.setattr(
        diag_zmq_b1_capture,
        "_sample_once",
        lambda *args, **kwargs: next(samples),
    )

    count = diag_zmq_b1_capture.run_capture(
        bridge,
        duration_s=2.0,
        interval_s=1.0,
        output_path=output,
        address="tcp://127.0.0.1:5556",
        direct_timeout_s=5.0,
        skip_direct_probe=False,
        now_fn=lambda: next(timeline),
        sleep_fn=lambda _: None,
    )

    assert count == 2
    lines = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert [line["seq"] for line in lines] == [1, 2]
