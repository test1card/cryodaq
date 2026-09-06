"""The launcher can be profiled, and pays nothing when it is not.

Review's next step for the launcher's growth was to profile ONE correctly
identified launcher and establish whether the growing allocations are Python
objects at all. That could not be done: the profiler existed and was wired into
the engine — the process measured flat across every incarnation — while the
launcher, the one that keeps rising, had no hook.

These pin the sampler's output and, more importantly, that the launcher path is
genuinely inert when CRYODAQ_MEMORY_PROFILE is unset. A diagnostic that costs
something when switched off is a diagnostic nobody leaves in.
"""

from __future__ import annotations

import tracemalloc
from pathlib import Path

import pytest

from cryodaq.diagnostics.memory_profile import (
    ENABLE_ENV,
    INTERVAL_ENV,
    MemoryProfileSampler,
    interval_s,
    profiling_requested,
)


def test_it_is_off_unless_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENABLE_ENV, raising=False)
    assert profiling_requested() is False
    for disabled in ("", "0", "false", "False"):
        monkeypatch.setenv(ENABLE_ENV, disabled)
        assert profiling_requested() is False, f"{disabled!r} must not enable profiling"
    monkeypatch.setenv(ENABLE_ENV, "1")
    assert profiling_requested() is True


def test_a_sample_without_tracing_still_records_the_process(tmp_path: Path) -> None:
    """RSS rising while Python's traced memory does not IS the finding.

    So a sample taken without tracing is written rather than skipped: process
    totals alone answer the question that matters most.
    """
    sampler = MemoryProfileSampler(tmp_path, process_label="launcher")
    sampler.prepare()
    assert not tracemalloc.is_tracing(), "precondition: this test must not trace"
    sampler.capture()

    written = list(tmp_path.glob("launcher-*-process.txt"))
    assert len(written) == 1, f"expected one process record, got {[p.name for p in written]}"
    text = written[0].read_text(encoding="utf-8")
    for field in ("rss_kb:", "pss_kb:", "threads:", "open_fds:"):
        assert field in text
    assert "launcher #1" in text, "the label must name the process and the sample index"


def test_the_label_distinguishes_the_processes(tmp_path: Path) -> None:
    """Comparing the launcher against the engine is the whole point."""
    MemoryProfileSampler(tmp_path, process_label="engine").capture()
    MemoryProfileSampler(tmp_path, process_label="launcher").capture()
    names = sorted(p.name.split("-")[0] for p in tmp_path.glob("*-process.txt"))
    assert names == ["engine", "launcher"]


def test_a_failing_sample_does_not_raise(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Diagnostics must never take the host down."""
    sampler = MemoryProfileSampler(tmp_path / "never-created", process_label="launcher")
    # prepare() deliberately not called: the directory does not exist.
    sampler.capture()  # must not raise


def test_the_interval_defaults_and_is_overridable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(INTERVAL_ENV, raising=False)
    assert interval_s() == 3600.0
    monkeypatch.setenv(INTERVAL_ENV, "120")
    assert interval_s() == 120.0
    monkeypatch.setenv(INTERVAL_ENV, "не число")
    assert interval_s() == 3600.0, "a malformed interval must fall back, not crash a boot"


def test_the_launcher_wires_the_sampler_only_when_asked() -> None:
    """Read the construction path rather than build a window in a test.

    Constructing LauncherWindow starts subprocesses. What matters here is that
    the sampler is created under the env guard and nowhere else.
    """
    source = (Path(__file__).parents[2] / "src" / "cryodaq" / "launcher.py").read_text(encoding="utf-8")
    assert source.count("MemoryProfileSampler(") == 1, "one construction site only"
    guard = source.index("if memory_profiling_requested():")
    construction = source.index("self._memory_profile_sampler = MemoryProfileSampler(")
    assert guard < construction, "the sampler must be built inside the env guard"
    # And the capture runs off the GUI thread.
    capture = source.index("def _capture_memory_profile(")
    assert "threading.Thread(" in source[capture : capture + 900]


def test_two_samples_in_one_second_do_not_collide(tmp_path: Path) -> None:
    """Found while verifying this change, not by review.

    With only a second-resolution timestamp in the filename, two captures inside
    one second write the same path — and the second then diffs against a dump it
    has just overwritten, reporting no growth at all. A silently wrong answer,
    reachable as soon as someone lowers the interval to watch something happen.
    """
    sampler = MemoryProfileSampler(tmp_path, process_label="launcher")
    sampler.prepare()
    sampler.start_tracing()
    try:
        held = [object() for _ in range(20_000)]
        sampler.capture()
        held += [object() for _ in range(200_000)]
        sampler.capture()
    finally:
        tracemalloc.stop()

    snapshots = sorted(tmp_path.glob("launcher-*.snapshot"))
    assert len(snapshots) == 2, f"each sample needs its own file: {[p.name for p in snapshots]}"

    diffs = list(tmp_path.glob("launcher-*-diff.txt"))
    assert len(diffs) == 1
    body = diffs[0].read_text(encoding="utf-8")
    assert "#2" in body, "the diff belongs to the second sample"
    growth_lines = [line for line in body.splitlines() if "KB" in line and "+" in line]
    assert growth_lines, f"the diff must record the growth between the two samples:\n{body}"
    assert any("+0.0 KB" not in line for line in growth_lines), (
        "every entry reads +0.0 KB, which is what a snapshot diffed against "
        f"itself looks like:\n{body}"
    )
    assert len(held) == 220_000
