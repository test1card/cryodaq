from __future__ import annotations

import pytest

from tools import _b1_diagnostics


class _FakeBridge:
    def __init__(self) -> None:
        self._last_heartbeat = 148.0
        self._last_reading_time = 140.0
        self._last_cmd_timeout = 145.0

    def is_alive(self) -> bool:
        return True

    def is_healthy(self) -> bool:
        return True

    def heartbeat_stale(self, *, timeout_s: float = 30.0) -> bool:
        return False

    def data_flow_stalled(self, *, timeout_s: float = 30.0) -> bool:
        return False

    def command_channel_stalled(self, *, timeout_s: float = 10.0) -> bool:
        return True

    def restart_count(self) -> int:
        return 2


def test_bridge_snapshot_exposes_runtime_state():
    bridge = _FakeBridge()

    snapshot = _b1_diagnostics.bridge_snapshot(bridge, now=150.0)

    assert snapshot["bridge_alive"] is True
    assert snapshot["bridge_healthy"] is True
    assert snapshot["heartbeat_stale"] is False
    assert snapshot["data_flow_stalled"] is False
    assert snapshot["command_channel_stalled"] is True
    assert snapshot["restart_count"] == 2
    assert snapshot["last_heartbeat_age_s"] == pytest.approx(2.0)
    assert snapshot["last_reading_age_s"] == pytest.approx(10.0)
    assert snapshot["last_cmd_timeout_age_s"] == pytest.approx(5.0)


def test_direct_engine_probe_sends_safety_status(monkeypatch):
    captured: dict[str, object] = {}

    def fake_send_command(cmd, *, address, timeout_s):
        captured["cmd"] = cmd
        captured["address"] = address
        captured["timeout_s"] = timeout_s
        return {"ok": True, "source": "direct"}

    monkeypatch.setattr(_b1_diagnostics, "send_command", fake_send_command)

    reply = _b1_diagnostics.direct_engine_probe(
        address="tcp://127.0.0.1:5556",
        timeout_s=7.0,
    )

    assert reply == {"ok": True, "source": "direct"}
    assert captured == {
        "cmd": {"cmd": "safety_status"},
        "address": "tcp://127.0.0.1:5556",
        "timeout_s": 7.0,
    }
