from __future__ import annotations

import argparse
import json

import pytest

from tools import diag_zmq_b1_capture


class _FakeBridge:
    """Minimal bridge double for unit tests.

    `alive=False` makes `is_alive()` return False — used by the R1
    startup probe's subprocess-spawn-failure short-circuit.
    `replies` (optional) is a list of dicts to return from successive
    `send_command()` calls; if exhausted, the last reply is reused.
    Default: single OK reply, used by capture-flow tests that don't
    care about the probe's retry behavior.
    """

    def __init__(
        self,
        *,
        alive: bool = True,
        replies: list[dict] | None = None,
    ) -> None:
        self.started = False
        self.stopped = False
        self._alive = alive
        self._replies = list(replies) if replies is not None else None
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
        self.commands.append(cmd)
        if self._replies is None:
            assert cmd == {"cmd": "safety_status"}
            return {"ok": True, "source": "bridge"}
        if self._replies:
            return self._replies.pop(0)
        # Exhausted: repeat last reply
        return {"ok": False, "error": "replies exhausted"}


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


# --------------------------------------------------------------------
# R1 repair — _validate_bridge_startup bounded-backoff tests
#
# These cover test cases 1-3 from Codex-01 Stream A synthesis. Cases
# 4-6 (real ipc:// loop, tcp:// fallback loop, delayed-REP harness)
# require a live engine + ZMQ context and are deferred to manual
# hardware verification per architect guidance — see
# docs/decisions/2026-04-24-d1-d4a-execution.md residual section.
# --------------------------------------------------------------------


def test_validate_bridge_startup_dead_bridge_raises_without_send_command() -> None:
    """Case 1: is_alive()=False short-circuits before any send_command()."""
    bridge = _FakeBridge(alive=False)

    with pytest.raises(RuntimeError, match="ZMQ bridge subprocess failed to start"):
        diag_zmq_b1_capture._validate_bridge_startup(bridge)

    assert bridge.commands == []


def test_validate_bridge_startup_succeeds_after_transient_non_ok() -> None:
    """Case 2: two non-OK replies, then OK → passes after 3 attempts."""
    bridge = _FakeBridge(
        alive=True,
        replies=[
            {"ok": False, "error": "not ready"},
            {"ok": False, "error": "still not ready"},
            {"ok": True, "state": "ready"},
        ],
    )
    sleeps: list[float] = []

    diag_zmq_b1_capture._validate_bridge_startup(
        bridge,
        attempts=5,
        backoff_s=0.2,
        sleep_fn=sleeps.append,
    )

    assert len(bridge.commands) == 3
    assert bridge.commands == [{"cmd": "safety_status"}] * 3
    # Two sleeps between three attempts; no sleep after the final OK.
    assert sleeps == [0.2, 0.2]


def test_validate_bridge_startup_all_non_ok_raises_with_last_reply() -> None:
    """Case 3: all attempts non-OK → raises with last reply; sleeps bounded."""
    bridge = _FakeBridge(
        alive=True,
        replies=[
            {"ok": False, "error": "first"},
            {"ok": False, "error": "second"},
            {"ok": False, "error": "third"},
            {"ok": False, "error": "fourth"},
            {"ok": False, "error": "fifth"},
        ],
    )
    sleeps: list[float] = []

    with pytest.raises(RuntimeError, match="Bridge startup probe failed") as exc_info:
        diag_zmq_b1_capture._validate_bridge_startup(
            bridge,
            attempts=5,
            backoff_s=0.2,
            sleep_fn=sleeps.append,
        )

    # Last reply's error text is surfaced in the exception message.
    assert "'fifth'" in str(exc_info.value) or "fifth" in str(exc_info.value)
    assert len(bridge.commands) == 5
    # Four inter-attempt sleeps (between 5 attempts); no sleep after the last.
    assert sleeps == [0.2, 0.2, 0.2, 0.2]


def test_main_returns_nonzero_when_bridge_startup_fails(tmp_path, monkeypatch, capsys):
    """Case 3 integration: main() surfaces probe failure as exit 1 + stderr."""
    output = tmp_path / "capture.jsonl"
    bridge = _FakeBridge(
        alive=True,
        replies=[{"ok": False, "error": "bridge unavailable"}] * 5,
    )

    monkeypatch.setattr(
        diag_zmq_b1_capture,
        "_parse_args",
        lambda argv=None: argparse.Namespace(
            output=output,
            duration=180.0,
            interval=1.0,
            address="tcp://127.0.0.1:5556",
            direct_timeout=5.0,
            skip_direct_probe=False,
        ),
    )
    monkeypatch.setattr(diag_zmq_b1_capture, "ZmqBridge", lambda: bridge)
    monkeypatch.setattr(diag_zmq_b1_capture.time, "sleep", lambda _: None)
    # run_capture must NOT be called when the probe fails.
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
