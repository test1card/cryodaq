"""Tests for tools._b1_diagnostics."""

from __future__ import annotations

import threading

from tools import _b1_diagnostics as b1


class _FakeBridge:
    def __init__(self, replies: list[dict]):
        self._replies = iter(replies)
        self.calls: list[dict] = []

    def send_command(self, cmd: dict) -> dict:
        self.calls.append(dict(cmd))
        return next(self._replies)


def test_format_reply_summary_handles_ok_and_error():
    assert b1.format_reply_summary({"ok": True, "state": "ready"}) == "ok=True state=ready"
    assert b1.format_reply_summary({"ok": False, "error": "boom"}) == "ok=False error=boom"


def test_summarize_samples_counts_failures_and_slow_calls():
    samples = [
        b1.B1Sample(phase="seq", index=0, elapsed_s=0.02, reply={"ok": True}),
        b1.B1Sample(phase="seq", index=1, elapsed_s=0.75, reply={"ok": True}),
        b1.B1Sample(phase="seq", index=2, elapsed_s=0.30, reply={"ok": False, "error": "x"}),
    ]
    summary = b1.summarize_samples(samples, slow_threshold_s=0.5)
    assert summary.phase == "seq"
    assert summary.total == 3
    assert summary.ok == 2
    assert summary.failed == 1
    assert summary.slow == 1
    assert summary.max_elapsed_s == 0.75


def test_run_sequential_phase_uses_bridge_in_order():
    bridge = _FakeBridge(
        [
            {"ok": True, "state": "a"},
            {"ok": True, "state": "b"},
            {"ok": False, "error": "c"},
        ]
    )
    samples = b1.run_sequential_phase(bridge, count=3, command={"cmd": "safety_status"})

    assert [sample.index for sample in samples] == [0, 1, 2]
    assert [sample.phase for sample in samples] == ["sequential"] * 3
    assert bridge.calls == [{"cmd": "safety_status"}] * 3
    assert [sample.reply for sample in samples][-1]["ok"] is False


def test_run_concurrent_phase_runs_calls_in_parallel():
    started = 0
    max_started = 0
    lock = threading.Lock()
    ready = threading.Event()
    release = threading.Event()

    class _ConcurrentBridge:
        def send_command(self, cmd: dict) -> dict:
            nonlocal started, max_started
            with lock:
                started += 1
                max_started = max(max_started, started)
                if started == 3:
                    ready.set()
            release.wait(timeout=1.0)
            with lock:
                started -= 1
            return {"ok": True, "echo": cmd["cmd"]}

    bridge = _ConcurrentBridge()

    def _release_when_ready():
        ready.wait(timeout=1.0)
        release.set()

    thread = threading.Thread(target=_release_when_ready, daemon=True)
    thread.start()
    samples = b1.run_concurrent_phase(bridge, count=3, command={"cmd": "safety_status"})
    thread.join(timeout=1.0)

    assert len(samples) == 3
    assert {sample.index for sample in samples} == {0, 1, 2}
    assert max_started >= 2


def test_capture_b1_truth_runs_all_phases_and_summarizes():
    replies = [
        {"ok": True, "state": "seq-0"},
        {"ok": True, "state": "seq-1"},
        {"ok": True, "state": "con-0"},
        {"ok": False, "error": "con-1"},
        {"ok": True, "state": "soak-0"},
        {"ok": True, "state": "soak-1"},
    ]
    bridge = _FakeBridge(replies)
    emitted: list[str] = []
    report = b1.capture_b1_truth(
        bridge,
        sequential_count=2,
        concurrent_count=2,
        soak_seconds=2.0,
        soak_interval_s=1.0,
        start_delay_s=0.0,
        emit=emitted.append,
    )

    assert [sample.phase for sample in report.samples] == [
        "sequential",
        "sequential",
        "concurrent",
        "concurrent",
        "soak",
        "soak",
    ]
    assert [summary.phase for summary in report.summaries] == [
        "sequential",
        "concurrent",
        "soak",
    ]
    assert any("sequential" in line for line in emitted)
    assert any("summary" in line.lower() for line in emitted)
