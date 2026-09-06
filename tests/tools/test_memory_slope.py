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
    assert list(series) == [("gui", 42)]
    assert memory_slope._slope_mib_per_hour(series[("gui", 42)]) == pytest.approx(16.0)
