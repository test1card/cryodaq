"""Reusable helpers for the B1 truth-recovery diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
import threading
import time


DEFAULT_B1_COMMAND: dict[str, str] = {"cmd": "safety_status"}
DEFAULT_SEQUENTIAL_COUNT = 5
DEFAULT_CONCURRENT_COUNT = 10
DEFAULT_SOAK_SECONDS = 60.0
DEFAULT_SOAK_INTERVAL_S = 1.0
SLOW_REPLY_THRESHOLD_S = 0.5


class _CommandBridge(Protocol):
    def send_command(self, cmd: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class B1Sample:
    phase: str
    index: int
    elapsed_s: float
    reply: dict[str, Any]


@dataclass(frozen=True, slots=True)
class B1PhaseSummary:
    phase: str
    total: int
    ok: int
    failed: int
    slow: int
    max_elapsed_s: float


@dataclass(frozen=True, slots=True)
class B1CaptureReport:
    samples: list[B1Sample]
    summaries: list[B1PhaseSummary]

    @property
    def has_failures(self) -> bool:
        return any(summary.failed for summary in self.summaries)


def format_reply_summary(reply: dict[str, Any]) -> str:
    if reply.get("ok", False):
        detail = reply.get("state")
        if detail is None:
            detail = reply.get("echo")
        if detail is None:
            detail = "ok"
        return f"ok=True state={detail}"
    error = reply.get("error", "unknown error")
    return f"ok=False error={error}"


def _emit(emit, line: str) -> None:
    if emit is None:
        print(line)
    else:
        emit(line)


def _sample_command(
    bridge: _CommandBridge,
    *,
    phase: str,
    index: int,
    command: dict[str, Any],
) -> B1Sample:
    started = time.monotonic()
    reply = bridge.send_command(dict(command))
    elapsed_s = time.monotonic() - started
    if not isinstance(reply, dict):
        reply = {"ok": False, "error": f"unexpected reply type: {type(reply).__name__}"}
    return B1Sample(phase=phase, index=index, elapsed_s=elapsed_s, reply=reply)


def summarize_samples(
    samples: list[B1Sample],
    *,
    slow_threshold_s: float = SLOW_REPLY_THRESHOLD_S,
) -> B1PhaseSummary:
    if not samples:
        return B1PhaseSummary(phase="unknown", total=0, ok=0, failed=0, slow=0, max_elapsed_s=0.0)
    ok = sum(1 for sample in samples if sample.reply.get("ok", False))
    failed = len(samples) - ok
    slow = sum(1 for sample in samples if sample.reply.get("ok", False) and sample.elapsed_s > slow_threshold_s)
    max_elapsed_s = max(sample.elapsed_s for sample in samples)
    return B1PhaseSummary(
        phase=samples[0].phase,
        total=len(samples),
        ok=ok,
        failed=failed,
        slow=slow,
        max_elapsed_s=max_elapsed_s,
    )


def run_sequential_phase(
    bridge: _CommandBridge,
    *,
    count: int = DEFAULT_SEQUENTIAL_COUNT,
    command: dict[str, Any] | None = None,
    phase: str = "sequential",
    emit=None,
) -> list[B1Sample]:
    command = dict(DEFAULT_B1_COMMAND if command is None else command)
    _emit(emit, f"[b1] phase={phase} sequential count={count}")
    samples: list[B1Sample] = []
    for index in range(count):
        sample = _sample_command(bridge, phase=phase, index=index, command=command)
        samples.append(sample)
        _emit(
            emit,
            f"[b1] {phase} #{index + 1}: {sample.elapsed_s * 1000:.1f}ms "
            f"{format_reply_summary(sample.reply)}",
        )
    return samples


def run_concurrent_phase(
    bridge: _CommandBridge,
    *,
    count: int = DEFAULT_CONCURRENT_COUNT,
    command: dict[str, Any] | None = None,
    phase: str = "concurrent",
    emit=None,
) -> list[B1Sample]:
    command = dict(DEFAULT_B1_COMMAND if command is None else command)
    _emit(emit, f"[b1] phase={phase} concurrent count={count}")
    samples: list[B1Sample | None] = [None] * count
    emit_lock = threading.Lock()

    def worker(index: int) -> None:
        sample = _sample_command(bridge, phase=phase, index=index, command=command)
        samples[index] = sample
        with emit_lock:
            _emit(
                emit,
                f"[b1] {phase} #{index + 1}: {sample.elapsed_s * 1000:.1f}ms "
                f"{format_reply_summary(sample.reply)}",
            )

    threads = [
        threading.Thread(target=worker, args=(index,), daemon=True, name=f"b1-{phase}-{index}")
        for index in range(count)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5.0)

    if any(sample is None for sample in samples):
        raise RuntimeError(f"{phase} capture did not complete cleanly")
    return [sample for sample in samples if sample is not None]


def run_soak_phase(
    bridge: _CommandBridge,
    *,
    seconds: float = DEFAULT_SOAK_SECONDS,
    interval_s: float = DEFAULT_SOAK_INTERVAL_S,
    command: dict[str, Any] | None = None,
    phase: str = "soak",
    emit=None,
) -> list[B1Sample]:
    command = dict(DEFAULT_B1_COMMAND if command is None else command)
    _emit(emit, f"[b1] phase={phase} soak seconds={seconds:g} interval={interval_s:g}")
    samples: list[B1Sample] = []
    iterations = max(1, int(seconds / interval_s))
    for index in range(iterations):
        started = time.monotonic()
        sample = _sample_command(bridge, phase=phase, index=index, command=command)
        samples.append(sample)
        _emit(
            emit,
            f"[b1] {phase} #{index + 1}: {sample.elapsed_s * 1000:.1f}ms "
            f"{format_reply_summary(sample.reply)}",
        )
        remaining = interval_s - (time.monotonic() - started)
        if remaining > 0:
            time.sleep(remaining)
    return samples


def render_report(report: B1CaptureReport, *, emit=None) -> None:
    _emit(emit, "[b1] summary")
    for summary in report.summaries:
        _emit(
            emit,
            "[b1] summary "
            f"{summary.phase}: total={summary.total} ok={summary.ok} "
            f"failed={summary.failed} slow={summary.slow} "
            f"max={summary.max_elapsed_s * 1000:.1f}ms",
        )
    verdict = "failures detected" if report.has_failures else "no failures observed"
    _emit(emit, f"[b1] summary verdict: {verdict}")


def capture_b1_truth(
    bridge: _CommandBridge,
    *,
    sequential_count: int = DEFAULT_SEQUENTIAL_COUNT,
    concurrent_count: int = DEFAULT_CONCURRENT_COUNT,
    soak_seconds: float = DEFAULT_SOAK_SECONDS,
    soak_interval_s: float = DEFAULT_SOAK_INTERVAL_S,
    start_delay_s: float = 1.0,
    command: dict[str, Any] | None = None,
    emit=None,
) -> B1CaptureReport:
    if start_delay_s > 0:
        _emit(emit, f"[b1] warmup delay {start_delay_s:g}s")
        time.sleep(start_delay_s)
    samples: list[B1Sample] = []
    samples.extend(
        run_sequential_phase(
            bridge,
            count=sequential_count,
            command=command,
            phase="sequential",
            emit=emit,
        )
    )
    samples.extend(
        run_concurrent_phase(
            bridge,
            count=concurrent_count,
            command=command,
            phase="concurrent",
            emit=emit,
        )
    )
    samples.extend(
        run_soak_phase(
            bridge,
            seconds=soak_seconds,
            interval_s=soak_interval_s,
            command=command,
            phase="soak",
            emit=emit,
        )
    )
    summaries = [
        summarize_samples([sample for sample in samples if sample.phase == phase_name])
        for phase_name in ("sequential", "concurrent", "soak")
    ]
    report = B1CaptureReport(samples=samples, summaries=summaries)
    render_report(report, emit=emit)
    return report

