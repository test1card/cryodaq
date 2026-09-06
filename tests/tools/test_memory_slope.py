"""The growth verdict rests entirely on this slope, so pin it.

A wrong number here would not fail loudly — it would quietly tell the operator
that a leaking process is fine, or that a healthy one is leaking.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).parents[2] / "tools" / "memory_slope.py"
_SPEC = importlib.util.spec_from_file_location("memory_slope", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
memory_slope = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = memory_slope
_SPEC.loader.exec_module(memory_slope)


def _points(pairs: list[tuple[float, float]]) -> list:
    return [
        memory_slope.Point(t=hours * 3600.0, rss_mib=mib, threads=19, fds=45, iso="2026-09-06T00:00:00")
        for hours, mib in pairs
    ]


def test_a_flat_series_reports_no_growth() -> None:
    slope = memory_slope._slope_mib_per_hour(_points([(0, 288.0), (1, 288.0), (2, 288.0), (3, 288.0)]))
    assert slope == pytest.approx(0.0, abs=1e-9)


def test_a_known_ramp_reports_its_own_rate() -> None:
    # 16 MiB per hour, the shape the launcher actually showed.
    slope = memory_slope._slope_mib_per_hour(_points([(0, 300.0), (1, 316.0), (2, 332.0), (3, 348.0)]))
    assert slope == pytest.approx(16.0)


def test_a_falling_series_reports_a_negative_rate() -> None:
    slope = memory_slope._slope_mib_per_hour(_points([(0, 230.0), (1, 228.0), (2, 226.0)]))
    assert slope == pytest.approx(-2.0)


def test_two_points_are_refused() -> None:
    """Two points define a line through themselves and imply no trend."""
    assert memory_slope._slope_mib_per_hour(_points([(0, 300.0), (1, 400.0)])) is None


def test_samples_at_one_instant_are_refused() -> None:
    assert memory_slope._slope_mib_per_hour(_points([(0, 300.0), (0, 310.0), (0, 320.0)])) is None


def test_the_trailing_window_separates_a_plateau_from_a_leak() -> None:
    """The distinction the whole report turns on."""
    # Grows fast for four hours, then flat for five: overall says it grows,
    # the trailing window says it stopped.
    plateau = _points([(h, 225.0 + 30.0 * h) for h in range(5)] + [(h, 345.0) for h in range(5, 11)])
    assert memory_slope._slope_mib_per_hour(plateau) > 5.0
    assert memory_slope._slope_mib_per_hour(memory_slope._window(plateau, last_hours=5.0)) == pytest.approx(0.0)

    # Grows at a steady rate throughout: both agree, and that is the leak.
    steady = _points([(h, 300.0 + 16.0 * h) for h in range(11)])
    assert memory_slope._slope_mib_per_hour(steady) == pytest.approx(16.0)
    assert memory_slope._slope_mib_per_hour(memory_slope._window(steady, last_hours=5.0)) == pytest.approx(16.0)


def test_a_truncated_row_does_not_discard_the_file(tmp_path: Path) -> None:
    """The sampler appends while this reads; a half-written tail is normal."""
    csv_path = tmp_path / "samples.csv"
    csv_path.write_text(
        "timestamp,iso,role,pid,etime_s,rss_kb,pss_kb,swap_kb,threads,open_fds,cmd\n"
        "1000.0,2026-09-06T00:00:00,gui,42,10,307200,290000,0,19,45,launcher\n"
        "4600.0,2026-09-06T01:00:00,gui,42,3610,323584,306000,0,19,45,launcher\n"
        "8200.0,2026-09-06T02:00:00,gui,42,7210,339968,322000,0,19,45,launcher\n"
        "11800.0,2026-09-06T03:00:00,gui,4",
        encoding="utf-8",
    )
    series = memory_slope.load(csv_path)
    assert list(series) == [("gui", 42, 0)]
    assert memory_slope._slope_mib_per_hour(series[("gui", 42, 0)]) == pytest.approx(16.0)


# ---------------------------------------------------------------------------
# PID reuse. Reviewer finding, 2026-09-06: grouping on (role, pid) alone merged
# two lifetimes of the same PID into one series and reported 77.142857 MiB/hour
# of growth for two runs that were each perfectly flat. A fabricated verdict is
# worse than no verdict, because it looks like evidence.
# ---------------------------------------------------------------------------


def _row(ts: float, pid: int, rss_mib: float, etime_s: float, role: str = "gui") -> str:
    return (
        f"{ts},2026-09-06T00:00:00,{role},{pid},{etime_s},{int(rss_mib * 1024)},"
        f"{int(rss_mib * 950)},0,19,45,launcher\n"
    )


def _csv(tmp_path: Path, rows: list[str]) -> Path:
    path = tmp_path / "samples.csv"
    path.write_text(
        "timestamp,iso,role,pid,etime_s,rss_kb,pss_kb,swap_kb,threads,open_fds,cmd\n" + "".join(rows),
        encoding="utf-8",
    )
    return path


def test_a_reused_pid_does_not_fabricate_growth(tmp_path: Path) -> None:
    """The reviewer's disposable CSV, in the shape they described."""
    rows = [_row(1000.0 + 60 * i, 42, 100.0, 10.0 + 60 * i) for i in range(10)]
    # Same PID, new process: elapsed time resets.
    rows += [_row(2000.0 + 60 * i, 42, 400.0, 10.0 + 60 * i) for i in range(10)]

    series = memory_slope.load(_csv(tmp_path, rows))

    assert len(series) == 2, f"two lifetimes of one PID must not merge: {list(series)}"
    for lifetime in series.values():
        slope = memory_slope._slope_mib_per_hour(lifetime)
        assert slope == pytest.approx(0.0, abs=1e-6), (
            f"each lifetime was flat; reporting {slope} invents growth that never happened"
        )


def test_one_lifetime_is_not_split_by_sampling_jitter(tmp_path: Path) -> None:
    """The tolerance must not shatter a single run into fragments.

    `timestamp - etime_s` is a float difference against a value the sampler
    rounds, so an exact identity key would split every lifetime.
    """
    rows = []
    for i in range(40):
        ts = 1000.0 + 60.0 * i + (0.37 if i % 3 else -0.42)
        rows.append(_row(ts, 42, 300.0 + 0.26 * i, round(10.0 + 60.0 * i)))
    series = memory_slope.load(_csv(tmp_path, rows))
    assert len(series) == 1, f"jitter must not look like a restart: {len(series)} lifetimes"


def test_a_fast_reuse_is_caught_by_the_elapsed_time_going_backwards(tmp_path: Path) -> None:
    """A PID reused quickly leaves the implied start close; elapsed time does not."""
    rows = [_row(1000.0 + 60 * i, 42, 100.0, 600.0 + 60 * i) for i in range(5)]
    # Reused ~20 s later: implied start moves by well under the start tolerance,
    # but elapsed time drops from ~840 s back to 5 s.
    rows += [_row(1320.0 + 60 * i, 42, 400.0, 5.0 + 60 * i) for i in range(5)]
    series = memory_slope.load(_csv(tmp_path, rows))
    assert len(series) == 2, f"an elapsed-time reset is a restart: {list(series)}"


def test_distinct_pids_stay_distinct(tmp_path: Path) -> None:
    rows = [_row(1000.0 + 60 * i, 42, 100.0, 10.0 + 60 * i) for i in range(5)]
    rows += [_row(1000.0 + 60 * i, 43, 400.0, 10.0 + 60 * i) for i in range(5)]
    assert len(memory_slope.load(_csv(tmp_path, rows))) == 2
