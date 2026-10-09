"""Y-axis focus on the coldest cluster of channels.

During a cooldown some sensors reach their target while others stay near room
temperature. Plotted on one axis spanning both, every cold trace is squashed
into the bottom few pixels of the figure — which is the part of the run the
operator actually needs to read.
"""

from cryodaq.reporting.periodic_input import PeriodicReadingSnapshot
from cryodaq.reporting.periodic_renderer import _cold_focus_limits, _Series


def _series(channel: str, *values: float) -> _Series:
    rows = tuple(
        PeriodicReadingSnapshot(1000.0 + index, "ls", channel, value, "K", "ok")
        for index, value in enumerate(values)
    )
    return _Series(channel, "K", rows)


def test_zooms_to_the_cold_cluster_when_channels_split():
    # Three sensors down at ~80 K, two still at room temperature.
    series = [
        _series("Т1", 300.0, 80.0),
        _series("Т2", 300.0, 82.0),
        _series("Т3", 300.0, 85.0),
        _series("Т4", 294.0, 294.0),
        _series("Т5", 296.0, 296.0),
    ]
    limits = _cold_focus_limits(series)
    assert limits is not None
    low, high = limits
    # The cold group's own history spans 80..300 (they cooled during the
    # window), so the frame covers that and excludes the room-temperature pair.
    assert low < 80.0
    assert high >= 300.0


def test_no_zoom_when_channels_are_evenly_spread():
    # No gap dominates: an honest full-scale axis is the right answer.
    series = [_series(f"Т{i}", float(v)) for i, v in enumerate((100.0, 140.0, 180.0, 220.0, 260.0), start=1)]
    assert _cold_focus_limits(series) is None


def test_no_zoom_when_everything_sits_together():
    series = [_series("Т1", 294.0), _series("Т2", 294.5), _series("Т3", 295.0)]
    assert _cold_focus_limits(series) is None


def test_cold_cluster_frame_excludes_the_warm_sitters():
    # Cold sensors that have been cold for the whole window: the frame must
    # not stretch up to the warm ones.
    series = [
        _series("Т1", 4.2, 4.3),
        _series("Т2", 5.0, 5.1),
        _series("Т3", 293.0, 294.0),
    ]
    limits = _cold_focus_limits(series)
    assert limits is not None
    low, high = limits
    assert low < 4.2
    assert high < 20.0


def test_single_channel_is_left_alone():
    assert _cold_focus_limits([_series("Т1", 4.2)]) is None


def test_channels_without_values_are_ignored():
    empty = _Series("Т9", "K", ())
    assert _cold_focus_limits([empty]) is None
