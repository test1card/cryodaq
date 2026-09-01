"""A chart of a run that lost data must show that it lost data.

Exercised through the production path — ``_series`` then ``_drawable`` — not
against ``_drawable`` alone. An earlier version of these tests called
``_drawable`` directly and passed while the real renderer still joined straight
through a missing reading, because ``_series`` had already filtered it out.

On 2026-09-01 every LakeShore channel stopped for 6 h 46 min and the whole-run
chart drew one straight line across it. The report looked healthy through the
worst outage of the run.
"""

import math

import pytest

from cryodaq.reporting.periodic_input import PeriodicReadingSnapshot
from cryodaq.reporting.periodic_renderer import _drawable, _series

# The instrument sentinel. Finite, so nothing rejects it numerically: plotted
# as a value it rescales the axis to 1e88.
SENTINEL = -8.888e88


class _Snapshot:
    """Minimal stand-in for ValidatedPeriodicInput's shape used by _series."""

    class render:
        channel_labels = ()

    def __init__(self, rows):
        self.readings = tuple(rows)


def _row(ts: float, value: float | None, *, status: str = "ok", unit: str = "K"):
    return PeriodicReadingSnapshot(ts, "ls218", "Т1", value, unit, status)


def _plotted(rows):
    """Timestamps and values as the renderer itself would produce them."""
    series = _series(_Snapshot(rows))
    if not series:
        return None, []
    item = series[0]
    return item, _drawable(item.rows, item.unit)[1]


def _breaks(values) -> int:
    return sum(1 for value in values if math.isnan(value))


def _steady(count: int, *, start: float = 0.0, step: float = 2.0, value: float = 295.0):
    return [_row(start + i * step, value) for i in range(count)]


# ---------------------------------------------------------------------------
# Readings that are not measurements become gaps, not points and not silence
# ---------------------------------------------------------------------------


def test_a_missing_reading_breaks_the_line():
    _item, values = _plotted([_row(0.0, 295.0), _row(2.0, None), _row(4.0, 295.5)])
    assert _breaks(values) == 1
    assert len(values) == 3, "the missing reading keeps its place in time"


def test_a_finite_sentinel_is_never_plotted_as_a_value():
    """The status says the instrument could not measure; the value field lies."""
    _item, values = _plotted([_row(0.0, 295.0), _row(2.0, SENTINEL, status="timeout"), _row(4.0, 295.5)])
    assert _breaks(values) == 1
    assert all(math.isnan(value) or value > 0 for value in values), "sentinel reached the axis"


def test_a_channel_reporting_only_sentinels_plots_nothing():
    """It keeps its place — and its axis — but contributes no point.

    The channel is deliberately not dropped from the series: a pressure channel
    that reports nothing usable must still get its panel, showing "Нет данных",
    instead of the panel vanishing from the figure.
    """
    item, values = _plotted([_row(float(i) * 2.0, SENTINEL, status="timeout") for i in range(10)])
    assert item is not None
    assert _breaks(values) == len(values), "no sentinel may be drawn as a value"


def test_a_non_positive_pressure_cannot_reach_a_log_axis():
    _item, values = _plotted(
        [
            _row(0.0, 1e-1, unit="mbar"),
            _row(2.0, 0.0, unit="mbar"),
            _row(4.0, 9e-2, unit="mbar"),
        ]
    )
    assert _breaks(values) == 1


# ---------------------------------------------------------------------------
# Outages
# ---------------------------------------------------------------------------


def test_an_outage_after_steady_sampling_breaks_the_line():
    rows = _steady(40) + [_row(40 * 2.0 + 6 * 3600, 297.0)]
    _item, values = _plotted(rows)
    assert _breaks(values) == 1


def test_uninterrupted_sampling_is_never_broken():
    _item, values = _plotted(_steady(200))
    assert _breaks(values) == 0
    assert len(values) == 200


def test_ordinary_jitter_is_not_an_outage():
    rows = _steady(100)
    rows.append(_row(rows[-1].timestamp + 9.0, 295.0))
    rows += [_row(rows[-1].timestamp + 2.0 * i, 295.0) for i in range(1, 50)]
    _item, values = _plotted(rows)
    assert _breaks(values) == 0


# ---------------------------------------------------------------------------
# Sparse data: the outage must not become the inferred cadence
# ---------------------------------------------------------------------------


def test_two_samples_six_hours_apart_are_not_one_line():
    _item, values = _plotted([_row(0.0, 295.0), _row(6 * 3600, 297.0)])
    assert _breaks(values) == 1, "with no cadence evidence, six hours is still an outage"


def test_one_normal_interval_then_a_six_hour_hole():
    _item, values = _plotted([_row(0.0, 295.0), _row(2.0, 295.0), _row(2.0 + 6 * 3600, 297.0)])
    assert _breaks(values) == 1


def test_a_channel_down_for_half_the_window_still_shows_the_hole():
    """The median interval sits inside the outage; the cadence must not.

    Ten samples, a six-hour hole, ten more: with the median as the cadence
    estimate the hole defines "normal" and no break is drawn.
    """
    rows = _steady(10) + _steady(10, start=10 * 2.0 + 6 * 3600, value=297.0)
    _item, values = _plotted(rows)
    assert _breaks(values) == 1


@pytest.mark.parametrize("count", [1, 2, 3])
def test_very_short_series_are_drawable(count: int):
    item, values = _plotted(_steady(count))
    assert item is not None
    assert len(values) == count
    assert _breaks(values) == 0


# ---------------------------------------------------------------------------
# Alignment
# ---------------------------------------------------------------------------


def test_timestamps_and_values_always_align():
    rows = _steady(50) + [_row(200.0, None), _row(400.0, SENTINEL, status="fault")] + _steady(50, start=100_000.0)
    series = _series(_Snapshot(rows))[0]
    timestamps, values = _drawable(series.rows, series.unit)
    assert len(timestamps) == len(values)
