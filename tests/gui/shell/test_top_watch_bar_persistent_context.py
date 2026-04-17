"""Tests for TopWatchBar persistent context strip (B.4)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.gui.shell.top_watch_bar import TopWatchBar, _format_pressure


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def mock_channel_mgr():
    mgr = MagicMock()
    mgr.get_visible_cold_channels.return_value = [
        "\u04221",
        "\u04227",
        "\u042212",
    ]
    mgr.get_all_visible.return_value = [
        "\u04221",
        "\u04227",
        "\u042212",
    ]
    mgr.get_cold_channels.return_value = [
        "\u04221",
        "\u04227",
        "\u042212",
    ]
    mgr.on_change = MagicMock()
    mgr.off_change = MagicMock()
    return mgr


def _stop_timers(bar: TopWatchBar) -> None:
    bar._fast_timer.stop()
    bar._slow_timer.stop()
    bar._channel_refresh_timer.stop()
    bar._stale_timer.stop()


def _make_reading(channel: str, value: float, unit: str = "K") -> Reading:
    return Reading(
        channel=channel,
        value=value,
        unit=unit,
        timestamp=datetime.now(UTC),
        status=ChannelStatus.OK,
        instrument_id="test",
    )


def test_constructs_with_channel_mgr(app, mock_channel_mgr):
    bar = TopWatchBar(mock_channel_mgr)
    _stop_timers(bar)
    assert bar._ctx_pressure_value is not None
    assert bar._ctx_tmin_value is not None
    assert bar._ctx_tmax_value is not None


def test_initial_state_shows_dashes(app, mock_channel_mgr):
    bar = TopWatchBar(mock_channel_mgr)
    _stop_timers(bar)
    assert "\u2014" in bar._ctx_pressure_value.text()
    assert "\u2014" in bar._ctx_tmin_value.text()
    assert "\u2014" in bar._ctx_tmax_value.text()


def test_no_heater_cell_in_top_watch_bar(app, mock_channel_mgr):
    # Heater removed from TopWatchBar anatomy — header now shows only
    # pressure + T min + T max (plus outer zones). Heater concept
    # still exists on the Keithley panel.
    bar = TopWatchBar(mock_channel_mgr)
    _stop_timers(bar)
    assert not hasattr(bar, "_ctx_heater_value")
    assert not hasattr(bar, "_ctx_heater_label")
    assert not hasattr(bar, "_update_heater_display")


def test_no_time_window_picker_in_top_watch_bar(app, mock_channel_mgr):
    # Picker lives on TempPlotWidget — must not surface in the header.
    from PySide6.QtWidgets import QPushButton

    bar = TopWatchBar(mock_channel_mgr)
    _stop_timers(bar)
    btns = bar.findChildren(QPushButton)
    labels_to_reject = {"1мин", "1ч", "6ч", "24ч", "Всё"}
    for b in btns:
        assert b.text() not in labels_to_reject, (
            f"unexpected time-window button: {b.text()}"
        )
    assert not hasattr(bar, "_time_window_echo_label")
    assert not hasattr(bar, "set_time_window_echo")


def test_pressure_reading_updates_display(app, mock_channel_mgr):
    # Operator-facing unit is Cyrillic "мбар" (RULE-COPY-006).
    # Internal variable / upstream Reading.unit remains Latin "mbar"
    # because that's what the driver emits; the TopWatchBar re-labels
    # for display only.
    bar = TopWatchBar(mock_channel_mgr)
    _stop_timers(bar)
    bar.on_reading(_make_reading("VSP63D_1/pressure", 1.2e-3, "mbar"))
    text = bar._ctx_pressure_value.text()
    # Compact scientific — no leading zeros in exponent ("1.2e-3" not
    # "1.20e-03"). See _format_pressure.
    assert "1.2e-3" in text
    assert "\u043c\u0431\u0430\u0440" in text  # мбар


def test_cold_temp_updates_tmin_tmax(app, mock_channel_mgr):
    # T-min / T-max are locked to positionally-fixed reference channels
    # Т11 and Т12 (design system invariant #21). Arbitrary cold channels
    # like Т1 / Т7 must NOT populate the min/max cells.
    bar = TopWatchBar(mock_channel_mgr)
    _stop_timers(bar)
    # Т11 -> T min cell
    bar.on_reading(
        _make_reading(
            "\u042211 \u0420\u0435\u0444\u0435\u0440\u0435\u043d\u0446 1", 4.2
        )
    )
    # Т12 -> T max cell
    bar.on_reading(
        _make_reading(
            "\u042212 \u0420\u0435\u0444\u0435\u0440\u0435\u043d\u0446 2", 76.5
        )
    )
    assert "4.20" in bar._ctx_tmin_value.text()
    assert "76.50" in bar._ctx_tmax_value.text()


def test_non_reference_cold_channel_ignored_for_tmin_tmax(app, mock_channel_mgr):
    # Reading from a non-reference cold channel (e.g. Т1) must not affect
    # T min / T max — those are locked to Т11 / Т12 regardless of what
    # other channels report.
    bar = TopWatchBar(mock_channel_mgr)
    _stop_timers(bar)
    bar.on_reading(
        _make_reading(
            "\u04221 \u041a\u0440\u0438\u043e\u0441\u0442\u0430\u0442", 4.2
        )
    )
    bar.on_reading(
        _make_reading(
            "\u04227 \u0414\u0435\u0442\u0435\u043a\u0442\u043e\u0440", 76.5
        )
    )
    assert "\u2014" in bar._ctx_tmin_value.text()
    assert "\u2014" in bar._ctx_tmax_value.text()


def test_warm_channel_ignored_for_tmin_tmax(app, mock_channel_mgr):
    bar = TopWatchBar(mock_channel_mgr)
    _stop_timers(bar)
    bar.on_reading(
        _make_reading(
            "\u042215 \u0412\u0430\u043a\u0443\u0443\u043c\u043d\u044b\u0439 \u043a\u043e\u0436\u0443\u0445",  # noqa: E501
            295.0,
        )
    )
    assert "\u2014" in bar._ctx_tmin_value.text()
    assert "\u2014" in bar._ctx_tmax_value.text()


def test_nan_value_ignored(app, mock_channel_mgr):
    bar = TopWatchBar(mock_channel_mgr)
    _stop_timers(bar)
    bar.on_reading(_make_reading("\u04221 X", float("nan")))
    assert "\u2014" in bar._ctx_tmin_value.text()


# --- _format_pressure helper (Batch A) ---


def test_format_pressure_compact_scientific():
    assert _format_pressure(1.45e-6) == "1.5e-6"
    assert _format_pressure(3.2e-3) == "3.2e-3"
    assert _format_pressure(9.87e-1) == "9.9e-1"


def test_format_pressure_non_positive_returns_dash():
    assert _format_pressure(0.0) == "\u2014"
    assert _format_pressure(-1.0) == "\u2014"
