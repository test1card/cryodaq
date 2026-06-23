"""TemperatureTrajectoryWidget — unit tests (F3-Cycle2, spec §4.1).

Covers acceptance criteria:
1. Construction with no data → empty state shown.
2. Snapshot replay (F4): set_temperature_readings with accumulated snapshot
   populates widget immediately.
3. Live append: new readings append and trim to max 5000.
4. Channel grouping: legend labels use channel_manager names.
5. Layout swap: widget is discarded when AnalyticsView phase changes
   (verified via existing test_analytics_view_phase_aware.py patterns;
   this file tests the widget in isolation).
6. History fetch: ZmqCommandWorker issued on construction with correct cmd.
7. History response: _on_history_loaded merges historical data.
8. Error response: _on_history_loaded with ok=False is silent no-op.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.gui.shell.views.analytics_widgets import TemperatureTrajectoryWidget
from cryodaq.gui.state.time_window import reset_time_window_controller


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _reset(app):
    reset_time_window_controller()
    yield
    reset_time_window_controller()


def _reading(channel: str, value: float, ts: float | None = None) -> Reading:
    if ts is not None:
        timestamp = datetime.fromtimestamp(ts, tz=UTC)
    else:
        timestamp = datetime.now(UTC)
    return Reading(
        timestamp=timestamp,
        instrument_id="LS218S_1",
        channel=channel,
        value=value,
        unit="K",
        status=ChannelStatus.OK,
        metadata={},
    )


def _make_widget() -> TemperatureTrajectoryWidget:
    """Construct widget with ZmqCommandWorker mocked to a no-op."""
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        w = TemperatureTrajectoryWidget()
    return w


# ──────────────────────────────────────────────────────────────────────────────
# Construction and empty state
# ──────────────────────────────────────────────────────────────────────────────


def test_construction_no_data_shows_empty_label(app):
    """Fresh widget with no data must show the empty-state label."""
    w = _make_widget()
    assert not w._empty_label.isHidden()
    assert w._graphics.isHidden()


def test_construction_has_graphics_layout(app):
    w = _make_widget()
    assert w._graphics is not None


# ──────────────────────────────────────────────────────────────────────────────
# History fetch — ZMQ command dispatched on construction
# ──────────────────────────────────────────────────────────────────────────────


def test_history_fetch_triggers_zmq_worker_on_construction(app):
    """TemperatureTrajectoryWidget must issue a readings_history ZMQ command
    when first constructed."""
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        w = TemperatureTrajectoryWidget()

    mock_cls.assert_called_once()
    cmd = mock_cls.call_args[0][0]
    assert cmd["cmd"] == "readings_history"
    assert cmd["limit_per_channel"] == 5000
    assert "from_ts" in cmd
    assert "to_ts" in cmd
    mock_instance.start.assert_called_once()
    assert w._history_worker is mock_instance


def test_history_fetch_uses_7_day_window(app):
    """The from_ts must be ~7 days before to_ts."""
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_cls.return_value = MagicMock()
        TemperatureTrajectoryWidget()

    cmd = mock_cls.call_args[0][0]
    window_seconds = cmd["to_ts"] - cmd["from_ts"]
    expected = 7 * 24 * 3600
    assert abs(window_seconds - expected) < 5


# ──────────────────────────────────────────────────────────────────────────────
# History response — _on_history_loaded
# ──────────────────────────────────────────────────────────────────────────────


def test_history_loaded_populates_curves(app):
    """_on_history_loaded with a successful response must populate series,
    create group plots, make graphics visible, and render exact curve data."""
    w = _make_widget()

    result = {
        "ok": True,
        "data": {
            "Т1": [[1000.0, 295.0], [2000.0, 250.0], [3000.0, 200.0]],
            "Т2": [[1000.0, 290.0], [2000.0, 240.0]],
        },
    }
    w._on_history_loaded(result)

    assert "Т1" in w._series
    assert len(w._series["Т1"].xs) == 3
    assert "Т2" in w._series
    assert len(w._series["Т2"].xs) == 2
    assert "Т1" in w._curves
    assert "Т2" in w._curves
    assert len(w._group_plots) >= 1
    assert not w._graphics.isHidden()
    assert w._empty_label.isHidden()

    # Assert rendered curve data exactly
    xs1, ys1 = w._curves["Т1"].getData()
    assert list(xs1) == pytest.approx([1000.0, 2000.0, 3000.0], rel=1e-6)
    assert list(ys1) == pytest.approx([295.0, 250.0, 200.0], rel=1e-6)

    xs2, ys2 = w._curves["Т2"].getData()
    assert list(xs2) == pytest.approx([1000.0, 2000.0], rel=1e-6)
    assert list(ys2) == pytest.approx([290.0, 240.0], rel=1e-6)


def test_channels_from_different_groups_get_separate_plotitems(app):
    """Channels in different channel groups must each have their own PlotItem
    for independent Y-axis scaling (spec §4.1 criterion 3)."""
    from cryodaq.core.channel_manager import get_channel_manager

    mgr = get_channel_manager()
    # Register two channels in distinct groups.
    mgr._channels.setdefault("Т_cryostat_test", {})["group"] = "cryostat"
    mgr._channels.setdefault("Т_compressor_test", {})["group"] = "compressor"
    try:
        w = _make_widget()
        w.set_temperature_readings({
            "Т_cryostat_test": _reading("Т_cryostat_test", 4.2),
            "Т_compressor_test": _reading("Т_compressor_test", 280.0),
        })
        assert "cryostat" in w._group_plots
        assert "compressor" in w._group_plots
        # Each group has its own PlotItem — they must be distinct objects.
        assert w._group_plots["cryostat"] is not w._group_plots["compressor"]
    finally:
        mgr._channels.pop("Т_cryostat_test", None)
        mgr._channels.pop("Т_compressor_test", None)


def test_history_sorted_by_timestamp_after_load(app):
    """After _on_history_loaded, series must be sorted by timestamp even if
    the engine returned out-of-order points; rendered curve must reflect that order."""
    w = _make_widget()
    w._on_history_loaded({
        "ok": True,
        "data": {
            "Т1": [[3000.0, 200.0], [1000.0, 295.0], [2000.0, 250.0]],
        },
    })
    series = w._series["Т1"]
    assert series.xs == sorted(series.xs)

    # Rendered curve xs must be sorted and ys mapped correctly
    xs, ys = w._curves["Т1"].getData()
    assert list(xs) == pytest.approx([1000.0, 2000.0, 3000.0], rel=1e-6)
    assert list(ys) == pytest.approx([295.0, 250.0, 200.0], rel=1e-6)


def test_history_loaded_error_response_is_silent(app):
    """A failed engine response (ok=False) must leave widget in empty state."""
    w = _make_widget()
    w._on_history_loaded({"ok": False, "error": "ZMQ timeout"})
    assert not w._series
    assert not w._empty_label.isHidden()


def test_history_loaded_skips_empty_channel(app):
    """Channels with no data points in the response must not create entries in series or curves."""
    w = _make_widget()
    w._on_history_loaded({"ok": True, "data": {"Т3": [], "Т4": [[1.0, 100.0]]}})
    assert "Т3" not in w._series
    assert "Т3" not in w._curves
    assert "Т4" in w._series
    assert "Т4" in w._curves


# ──────────────────────────────────────────────────────────────────────────────
# Live stream — set_temperature_readings
# ──────────────────────────────────────────────────────────────────────────────


def test_live_append_adds_to_series(app):
    """set_temperature_readings must append readings to the existing series and curve."""
    w = _make_widget()
    r = _reading("Т1", 150.0, ts=1000.0)
    w.set_temperature_readings({"Т1": r})
    assert "Т1" in w._series
    assert len(w._series["Т1"].xs) == 1
    assert w._series["Т1"].ys[0] == 150.0
    # Rendered curve must also contain that point
    xs, ys = w._curves["Т1"].getData()
    assert len(xs) == 1
    assert xs[0] == pytest.approx(1000.0, rel=1e-6)
    assert ys[0] == pytest.approx(150.0, rel=1e-6)


def test_live_append_hides_empty_label(app):
    """First live reading must switch from empty state to visible plot."""
    w = _make_widget()
    assert not w._empty_label.isHidden()
    w.set_temperature_readings({"Т1": _reading("Т1", 120.0)})
    assert not w._graphics.isHidden()
    assert w._empty_label.isHidden()


def test_live_append_updates_existing_curve(app):
    """Appending a second reading to an existing channel must update its curve with exact data."""
    w = _make_widget()
    w.set_temperature_readings({"Т1": _reading("Т1", 200.0, ts=1000.0)})
    w.set_temperature_readings({"Т1": _reading("Т1", 190.0, ts=2000.0)})
    assert len(w._series["Т1"].xs) == 2
    xs, ys = w._curves["Т1"].getData()
    assert list(xs) == pytest.approx([1000.0, 2000.0], rel=1e-6)
    assert list(ys) == pytest.approx([200.0, 190.0], rel=1e-6)


def test_live_append_trims_to_5000_points(app):
    """When a channel exceeds 5000 points, older entries must be dropped; curve reflects trim."""
    w = _make_widget()
    for ts_val in range(1, 5002):
        w.set_temperature_readings({"Т1": _reading("Т1", float(ts_val), ts=float(ts_val))})

    series = w._series["Т1"]
    assert len(series.xs) == 5000
    # Oldest (ts=1) trimmed; retained window is [2, 5001]
    assert series.xs[0] == pytest.approx(2.0, rel=1e-6)
    assert series.xs[-1] == pytest.approx(5001.0, rel=1e-6)

    # Rendered curve must also have 5000 points with same retained range
    xs, ys = w._curves["Т1"].getData()
    assert len(xs) == 5000
    assert xs[0] == pytest.approx(2.0, rel=1e-6)
    assert xs[-1] == pytest.approx(5001.0, rel=1e-6)
    assert ys[-1] == pytest.approx(5001.0, rel=1e-6)


def test_live_multi_channel_single_call(app):
    """A readings dict with multiple channels must update all of them with exact curve data."""
    w = _make_widget()
    w.set_temperature_readings({
        "Т1": _reading("Т1", 100.0, ts=1000.0),
        "Т2": _reading("Т2", 200.0, ts=1001.0),
        "Т3": _reading("Т3", 300.0, ts=1002.0),
    })
    assert set(w._series.keys()) == {"Т1", "Т2", "Т3"}
    assert set(w._curves.keys()) == {"Т1", "Т2", "Т3"}

    # Each curve must have the exact plotted value
    _, ys1 = w._curves["Т1"].getData()
    assert ys1[0] == pytest.approx(100.0, rel=1e-6)
    _, ys2 = w._curves["Т2"].getData()
    assert ys2[0] == pytest.approx(200.0, rel=1e-6)
    _, ys3 = w._curves["Т3"].getData()
    assert ys3[0] == pytest.approx(300.0, rel=1e-6)


# ──────────────────────────────────────────────────────────────────────────────
# F4 snapshot replay
# ──────────────────────────────────────────────────────────────────────────────


def test_snapshot_replay_via_set_temperature_readings(app):
    """F4 replay: shell passes accumulated temperature snapshot via
    set_temperature_readings — widget receives it and displays with exact plotted values."""
    w = _make_widget()

    # Simulate F4 replay: merged dict of last-known readings per channel.
    snapshot = {
        "Т1": _reading("Т1", 77.0, ts=1_000_000.0),
        "Т2": _reading("Т2", 4.2, ts=1_000_001.0),
    }
    w.set_temperature_readings(snapshot)

    assert not w._graphics.isHidden()
    assert "Т1" in w._curves
    assert "Т2" in w._curves

    # Rendered curve must contain the plotted values
    xs1, ys1 = w._curves["Т1"].getData()
    assert len(xs1) == 1
    assert ys1[0] == pytest.approx(77.0, rel=1e-6)

    xs2, ys2 = w._curves["Т2"].getData()
    assert len(xs2) == 1
    assert ys2[0] == pytest.approx(4.2, rel=1e-6)


# ──────────────────────────────────────────────────────────────────────────────
# Channel manager integration
# ──────────────────────────────────────────────────────────────────────────────


def test_curve_legend_uses_channel_manager_name(app):
    """If channel_manager has a human name for a channel, the curve legend
    must use it rather than the raw channel ID."""
    from cryodaq.core.channel_manager import get_channel_manager

    mgr = get_channel_manager()
    mgr.set_name("Т_legend_test", "Детектор")
    try:
        w = _make_widget()
        w.set_temperature_readings({"Т_legend_test": _reading("Т_legend_test", 5.0, ts=1000.0)})
        assert "Т_legend_test" in w._curves
        # The curve must be registered in the plot legend under the human name "Детектор",
        # not the raw channel id. Check the curve's name (used for legend display).
        curve = w._curves["Т_legend_test"]
        assert curve.name() == "Детектор"
    finally:
        # Clean up: remove test channel name.
        mgr.set_name("Т_legend_test", "")


def test_fetch_history_sends_full_channel_labels(app):
    """_fetch_history must send full labels ('Т7 Детектор'), not short IDs
    ('Т7'). SQLiteWriter stores readings under full labels; short IDs yield
    zero results. Gemini bonus finding from F-X v3 audit, closed in v0.52.4."""
    from cryodaq.core.channel_manager import get_channel_manager

    mgr = get_channel_manager()
    mgr._channels["Т_label_test"] = {
        "name": "Тестовый Label",
        "is_cold": True,
        "visible": True,
        "group": "криостат",
    }
    try:
        with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
            mock_cls.return_value = MagicMock()
            TemperatureTrajectoryWidget()

        cmd = mock_cls.call_args[0][0]
        channels = cmd.get("channels", [])

        # Named channels must appear as full labels (short_id + space + name).
        # Channels with no registered name legitimately appear as short IDs
        # (get_display_name returns short_id when name is absent).
        assert "Т_label_test Тестовый Label" in channels, (
            f"Named channel not sent as full label. channels={channels}"
        )
        assert "Т_label_test" not in channels, (
            "Named channel sent as bare short ID — SQLite query would return 0 rows."
        )
    finally:
        mgr._channels.pop("Т_label_test", None)
