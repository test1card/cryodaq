"""The temperature axis follows the data until the operator takes it.

The Y range was seeded once and every later call returned early:

    if self._y_cache_lo is not None and self._y_cache_hi is not None:
        return

The intent was not to override a deliberate zoom, but it could not tell a zoom
from an untouched axis, so it refused forever. Across a cooldown from 295 K
toward 4 K the curves walked out of view and the operator had to press the
auto-range button again and again to see their own data. Owner: "currently i
have to click auto calibrate axis button every time. i want to not do that".

Following is now the default, and stops when the operator changes the view
themselves -- which pyqtgraph reports separately from ranges the widget sets.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from cryodaq.core.channel_manager import ChannelManager  # noqa: E402
from cryodaq.gui.dashboard.channel_buffer import ChannelBufferStore  # noqa: E402
from cryodaq.gui.dashboard.temp_plot_widget import TempPlotWidget  # noqa: E402


@pytest.fixture
def plot(app):
    return TempPlotWidget(ChannelBufferStore(), ChannelManager())


def _y_range(widget: TempPlotWidget) -> tuple[float, float]:
    return tuple(widget._plot.getPlotItem().getViewBox().viewRange()[1])


def test_the_axis_follows_a_cooldown_without_being_asked(plot):
    """295 K to 4 K is the case that made this necessary."""
    plot._update_y_range_with_deadband([294.0, 296.0])
    warm_lo, warm_hi = _y_range(plot)
    assert warm_lo < 295.0 < warm_hi

    plot._update_y_range_with_deadband([3.9, 4.1])
    cold_lo, cold_hi = _y_range(plot)

    assert cold_lo < 4.0 < cold_hi, "the cold data must be in view without pressing anything"
    assert cold_hi < 100.0, "and the axis must actually have come down, not merely contain 4 K"


def test_small_wander_inside_the_view_does_not_move_the_axis(plot):
    """A deadband is the difference between following and twitching."""
    plot._update_y_range_with_deadband([294.0, 296.0])
    before = _y_range(plot)

    plot._update_y_range_with_deadband([294.4, 295.6])

    assert _y_range(plot) == before


def test_the_axis_stops_following_once_the_operator_moves_it(plot):
    plot._update_y_range_with_deadband([294.0, 296.0])
    plot._on_y_range_changed_manually()
    taken = _y_range(plot)

    plot._update_y_range_with_deadband([3.9, 4.1])

    assert _y_range(plot) == taken, "a deliberate zoom must not be overridden by later data"


def test_a_range_the_widget_sets_is_not_mistaken_for_the_operator(plot):
    """Otherwise following would switch itself off on its first move."""
    plot._update_y_range_with_deadband([294.0, 296.0])
    assert plot._y_follow is True
    plot._update_y_range_with_deadband([3.9, 4.1])
    assert plot._y_follow is True


def test_the_auto_range_button_hands_the_axis_back(plot):
    plot._update_y_range_with_deadband([294.0, 296.0])
    plot._on_y_range_changed_manually()
    assert plot._y_follow is False

    plot._on_auto_range_requested()
    assert plot._y_follow is True

    plot._update_y_range_with_deadband([3.9, 4.1])
    lo, hi = _y_range(plot)
    assert lo < 4.0 < hi


def test_switching_scale_resumes_following(plot):
    plot._update_y_range_with_deadband([294.0, 296.0])
    plot._on_y_range_changed_manually()
    plot._on_log_y_toggled(True)
    assert plot._y_follow is True


def test_no_usable_values_leaves_the_axis_alone(plot):
    plot._update_y_range_with_deadband([294.0, 296.0])
    before = _y_range(plot)
    plot._update_y_range_with_deadband([])
    assert _y_range(plot) == before
