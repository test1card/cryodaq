from __future__ import annotations

import json

from tools import diag_zmq_b1_capture


class _FakeBridge:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def shutdown(self) -> None:
        self.stopped = True

    def poll_readings(self):
        return []

    def send_command(self, cmd):
        assert cmd == {"cmd": "safety_status"}
        return {"ok": True, "source": "bridge"}


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
