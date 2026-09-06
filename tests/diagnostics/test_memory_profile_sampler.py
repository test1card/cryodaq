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


# ---------------------------------------------------------------------------
# The installation boundary, exercised rather than read.
#
# The first version of this asserted that the env guard appeared before the
# construction in launcher.py's SOURCE. Review pointed out that source order
# does not establish conditional execution, and that the initialization — unlike
# capture() — did not contain its failures: an obstructed diagnostics directory
# propagated FileExistsError out of the constructor. Both are tested directly.
# ---------------------------------------------------------------------------


def test_installation_is_skipped_when_not_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    import cryodaq.launcher as launcher

    monkeypatch.delenv(ENABLE_ENV, raising=False)
    sampler, timer = launcher._install_memory_profile(None, lambda: None)
    assert sampler is None and timer is None


def test_an_obstructed_directory_disables_profiling_instead_of_failing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Reviewer finding: this used to abort launcher construction."""
    import cryodaq.launcher as launcher

    data_dir = tmp_path / "data"
    (data_dir / "diagnostics").mkdir(parents=True)
    # The path the profiler wants to create as a directory already exists as a
    # FILE, which is what makes mkdir(exist_ok=True) raise.
    (data_dir / "diagnostics" / "memprofile").write_text("", encoding="utf-8")

    monkeypatch.setenv(ENABLE_ENV, "1")
    monkeypatch.setattr("cryodaq.paths.get_data_dir", lambda: data_dir)

    with caplog.at_level("WARNING"):
        sampler, timer = launcher._install_memory_profile(None, lambda: None)

    assert sampler is None and timer is None, "profiling must switch itself off, not raise"
    assert any("memory profile" in record.message for record in caplog.records), (
        "and it must say so rather than disappear silently"
    )


def test_the_shutdown_path_stops_the_profiler_first() -> None:
    """The timer belongs to quiescence, and admission stops before it."""
    source = (Path(__file__).parents[2] / "src" / "cryodaq" / "launcher.py").read_text(encoding="utf-8")
    quiesce = source.index("def _quiesce_for_shutdown(")
    body = source[quiesce : source.index("\n    def ", quiesce + 10)]
    assert "_memory_profile_timer" in body, "the profiler timer must be stopped during quiescence"
    assert "memory_profile_sampler.stop()" in body, "and further captures must not be admitted"


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



def test_a_second_capture_is_skipped_while_one_is_running(tmp_path: Path) -> None:
    """Reviewer's sequence, 2026-09-06.

    The launcher starts a thread per timer tick. With overlapping captures, #1
    can pause after dumping, #2 complete, and #1 then finish late and move the
    previous-snapshot pointer BACKWARDS from #2 to #1 — so #3 diffs against the
    older snapshot and reports growth over the wrong interval. Unique filenames
    fixed overwriting; they never addressed ordering.
    """
    import threading

    sampler = MemoryProfileSampler(tmp_path, process_label="launcher")
    sampler.prepare()

    entered = threading.Event()
    release = threading.Event()
    calls: list[int] = []
    original = sampler._capture_locked

    def _slow() -> None:
        calls.append(1)
        entered.set()
        release.wait(10)
        original()

    sampler._capture_locked = _slow  # type: ignore[method-assign]

    first = threading.Thread(target=sampler.capture, daemon=True)
    first.start()
    assert entered.wait(10), "the first capture must have started"

    # Two more ticks arrive while the first is still inside the capture. Neither
    # may enter, and neither may block its caller — this is the GUI thread.
    sampler.capture()
    sampler.capture()
    assert calls == [1], f"a capture must not overlap another: {len(calls)} entered"

    release.set()
    first.join(10)
    assert not first.is_alive()

    # And once it is free, the next tick is admitted normally.
    sampler._capture_locked = original  # type: ignore[method-assign]
    sampler.capture()
    assert len(list(tmp_path.glob("launcher-*"))) >= 2


def test_stop_refuses_further_captures(tmp_path: Path) -> None:
    sampler = MemoryProfileSampler(tmp_path, process_label="launcher")
    sampler.prepare()
    sampler.capture()
    written = len(list(tmp_path.iterdir()))
    sampler.stop()
    sampler.capture()
    sampler.capture()
    assert len(list(tmp_path.iterdir())) == written, "nothing may be admitted after stop()"
    sampler.stop()  # idempotent


# ---------------------------------------------------------------------------
# Reviewer P2, 2026-09-06: a failed installation could leave tracing enabled.
#
# The obstructed-directory case returned (None, None) before tracing started, so
# it never exercised cleanup. With CRYODAQ_MEMORY_PROFILE_INTERVAL_S=inf the
# millisecond conversion raised OverflowError AFTER start_tracing(), the failure
# was caught, and the launcher then carried tracemalloc's overhead for its whole
# life while reporting profiling disabled and producing no snapshots.
#
# Two fixes, and both are pinned: the interval can no longer be non-finite, and
# a failure after tracing starts undoes it.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["inf", "-inf", "nan", "0", "-5", "не число", ""])
def test_an_unusable_interval_falls_back_instead_of_exploding_later(
    raw: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`inf` parses as a float and is > 0; it detonates at the conversion."""
    monkeypatch.setenv(INTERVAL_ENV, raw)
    value = interval_s()
    assert value == 3600.0, f"{raw!r} must fall back, got {value!r}"
    # And the value must survive the conversion the installer performs.
    assert isinstance(max(1, int(value * 1000)), int)


def test_a_failure_after_tracing_starts_undoes_the_tracing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cleanup path, exercised where the old test could not reach."""
    import cryodaq.launcher as launcher

    monkeypatch.setenv(ENABLE_ENV, "1")
    monkeypatch.delenv(INTERVAL_ENV, raising=False)
    monkeypatch.setattr("cryodaq.paths.get_data_dir", lambda: tmp_path)

    class _ExplodingTimer:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("no event dispatcher")

    monkeypatch.setattr(launcher, "QTimer", _ExplodingTimer)
    assert not tracemalloc.is_tracing(), "precondition: nothing is tracing yet"

    sampler, timer = launcher._install_memory_profile(None, lambda: None)

    assert (sampler, timer) == (None, None)
    assert not tracemalloc.is_tracing(), (
        "a failed installation must not leave the process paying tracing "
        "overhead while reporting profiling disabled"
    )


def test_cleanup_does_not_stop_tracing_it_did_not_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Undo only what this installation turned on.

    Tracing already running belongs to something else — stopping it would be a
    second defect wearing the first one's clothes.
    """
    import cryodaq.launcher as launcher

    monkeypatch.setenv(ENABLE_ENV, "1")
    monkeypatch.delenv(INTERVAL_ENV, raising=False)
    monkeypatch.setattr("cryodaq.paths.get_data_dir", lambda: tmp_path)

    class _ExplodingTimer:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("no event dispatcher")

    monkeypatch.setattr(launcher, "QTimer", _ExplodingTimer)

    tracemalloc.start(2)
    try:
        sampler, timer = launcher._install_memory_profile(None, lambda: None)
        assert (sampler, timer) == (None, None)
        assert tracemalloc.is_tracing(), "someone else's tracing must survive our failure"
    finally:
        tracemalloc.stop()


def test_start_tracing_reports_whether_it_started_anything(tmp_path: Path) -> None:
    sampler = MemoryProfileSampler(tmp_path, process_label="launcher")
    assert not tracemalloc.is_tracing()
    try:
        assert sampler.start_tracing() is True, "the first start is this sampler's"
        assert sampler.start_tracing() is False, "an already-tracing process is not ours to claim"
    finally:
        tracemalloc.stop()
