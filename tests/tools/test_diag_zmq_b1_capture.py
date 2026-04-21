"""Tests for tools.diag_zmq_b1_capture."""

from __future__ import annotations

from types import SimpleNamespace

from tools import diag_zmq_b1_capture as capture


class _FakeBridge:
    def __init__(self, pub_addr: str, cmd_addr: str):
        self.pub_addr = pub_addr
        self.cmd_addr = cmd_addr
        self.started = False
        self.shutdown_called = False

    def start(self) -> None:
        self.started = True

    def shutdown(self) -> None:
        self.shutdown_called = True


def test_parse_args_exposes_capture_controls():
    args = capture._parse_args(
        [
            "--sequential-count",
            "2",
            "--concurrent-count",
            "4",
            "--soak-seconds",
            "3",
            "--soak-interval",
            "0.5",
            "--start-delay",
            "0",
        ]
    )
    assert args.sequential_count == 2
    assert args.concurrent_count == 4
    assert args.soak_seconds == 3.0
    assert args.soak_interval == 0.5
    assert args.start_delay == 0.0


def test_main_bridges_cli_to_capture(monkeypatch, capsys):
    fake_bridge = _FakeBridge("pub://a", "cmd://b")
    captured_kwargs: dict | None = None

    def fake_capture(bridge, **kwargs):
        nonlocal captured_kwargs
        captured_kwargs = kwargs
        assert bridge is fake_bridge
        return SimpleNamespace(samples=[], summaries=[], has_failures=False)

    monkeypatch.setattr(capture, "ZmqBridge", lambda pub_addr, cmd_addr: fake_bridge)
    monkeypatch.setattr(capture, "capture_b1_truth", fake_capture)

    rc = capture.main(
        [
            "--pub-address",
            "pub://a",
            "--cmd-address",
            "cmd://b",
            "--start-delay",
            "0",
            "--sequential-count",
            "1",
            "--concurrent-count",
            "1",
            "--soak-seconds",
            "1",
            "--soak-interval",
            "1",
        ]
    )

    out = capsys.readouterr().out
    assert rc == 0
    assert fake_bridge.started is True
    assert fake_bridge.shutdown_called is True
    assert captured_kwargs == {
        "sequential_count": 1,
        "concurrent_count": 1,
        "soak_seconds": 1.0,
        "soak_interval_s": 1.0,
        "start_delay_s": 0.0,
        "emit": print,
    }
    assert "B1 capture" in out


def test_main_runs_help_without_touching_bridge(capsys):
    try:
        capture._parse_args(["--help"])
    except SystemExit as exc:
        assert exc.code == 0
    out = capsys.readouterr().out
    assert "B1" in out
