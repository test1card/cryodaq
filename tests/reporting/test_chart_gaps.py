"""A chart of a run that lost data must show that it lost data.

On 2026-09-01 every LakeShore channel stopped for 6 h 46 min. The whole-run
chart joined the last sample before the outage to the first one after it, and
drew a clean straight line the operator read as measurement — the report looked
healthy through the worst outage of the run.
"""

import math

from cryodaq.reporting.periodic_input import PeriodicReadingSnapshot
from cryodaq.reporting.periodic_renderer import _drawable


def _row(ts: float, value: float | None) -> PeriodicReadingSnapshot:
    return PeriodicReadingSnapshot(ts, "ls", "Т1", value, "K", "ok")


def _steady(count: int, *, start: float = 0.0, step: float = 2.0):
    return [_row(start + i * step, 295.0) for i in range(count)]


def test_an_outage_breaks_the_line():
    # 2 s sampling, then a six-hour hole, then sampling resumes.
    rows = _steady(200) + [_row(400.0 + 6 * 3600 + i * 2.0, 297.0) for i in range(200)]
    timestamps, values = _drawable(tuple(rows))
    assert any(math.isnan(v) for v in values), "the outage must be drawn as a break"
    # The break sits between the two real samples, not at either end.
    first_nan = next(i for i, v in enumerate(values) if math.isnan(v))
    assert 0 < first_nan < len(values) - 1


def test_uninterrupted_sampling_is_never_broken():
    timestamps, values = _drawable(tuple(_steady(500)))
    assert not any(math.isnan(v) for v in values)
    assert len(timestamps) == len(values) == 500


def test_ordinary_jitter_is_not_an_outage():
    # A few samples arriving late must not fragment the trace.
    rows = _steady(100)
    rows.append(_row(rows[-1].timestamp + 9.0, 295.0))
    rows += [_row(rows[-1].timestamp + 2.0 * i, 295.0) for i in range(1, 50)]
    _timestamps, values = _drawable(tuple(rows))
    assert not any(math.isnan(v) for v in values)


def test_a_reading_without_a_value_is_a_break_not_a_dropped_point():
    # Dropping it silently joined the samples either side, and desynchronised
    # timestamps from values because only the values list skipped it.
    rows = _steady(10) + [_row(20.0, None)] + [_row(22.0 + i * 2.0, 295.0) for i in range(10)]
    timestamps, values = _drawable(tuple(rows))
    assert len(timestamps) == len(values)
    assert sum(1 for v in values if math.isnan(v)) == 1


def test_timestamps_and_values_always_align():
    rows = _steady(50) + [_row(200.0, None), _row(400.0, float("nan"))] + _steady(50, start=100000.0)
    timestamps, values = _drawable(tuple(rows))
    assert len(timestamps) == len(values)


def test_a_single_sample_is_drawable():
    timestamps, values = _drawable((_row(0.0, 295.0),))
    assert len(timestamps) == len(values) == 1
    assert not math.isnan(values[0])
