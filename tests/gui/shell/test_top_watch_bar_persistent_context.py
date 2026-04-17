"""Tests for TopWatchBar persistent context strip (B.4)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.gui.shell.top_watch_bar import TopWatchBar


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
    assert bar._ctx_heater_value is not None


def test_initial_state_shows_dashes(app, mock_channel_mgr):
    bar = TopWatchBar(mock_channel_mgr)
    _stop_timers(bar)
    assert "\u2014" in bar._ctx_pressure_value.text()
    assert "\u2014" in bar._ctx_tmin_value.text()
    assert "\u2014" in bar._ctx_tmax_value.text()
    assert "\u2014" in bar._ctx_heater_value.text()


def test_pressure_reading_updates_display(app, mock_channel_mgr):
    bar = TopWatchBar(mock_channel_mgr)
    _stop_timers(bar)
    bar.on_reading(_make_reading("VSP63D_1/pressure", 1.2e-3, "mbar"))
    text = bar._ctx_pressure_value.text()
    assert "1.20e-03" in text or "1.2e-03" in text
    assert "mbar" in text


def test_cold_temp_updates_tmin_tmax(app, mock_channel_mgr):
    bar = TopWatchBar(mock_channel_mgr)
    _stop_timers(bar)
    bar.on_reading(
        _make_reading(
            "\u04221 \u041a\u0440\u0438\u043e\u0441\u0442\u0430\u0442 \u0432\u0435\u0440\u0445", 4.2
        )
    )
    bar.on_reading(_make_reading("\u04227 \u0414\u0435\u0442\u0435\u043a\u0442\u043e\u0440", 76.5))
    assert "4.20" in bar._ctx_tmin_value.text()
    assert "76.50" in bar._ctx_tmax_value.text()


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


def test_heater_zero_shows_dash(app, mock_channel_mgr):
    bar = TopWatchBar(mock_channel_mgr)
    _stop_timers(bar)
    bar.on_reading(_make_reading("Keithley_1/smua/power", 0.0, "W"))
    assert "\u2014" in bar._ctx_heater_value.text()


def test_heater_active_shows_watts(app, mock_channel_mgr):
    bar = TopWatchBar(mock_channel_mgr)
    _stop_timers(bar)
    bar.on_reading(_make_reading("Keithley_1/smua/power", 2.5, "W"))
    assert "2.50" in bar._ctx_heater_value.text()
    assert "\u0412\u0442" in bar._ctx_heater_value.text()


def test_heater_milliwatts(app, mock_channel_mgr):
    bar = TopWatchBar(mock_channel_mgr)
    _stop_timers(bar)
    bar.on_reading(_make_reading("Keithley_1/smua/power", 0.05, "W"))
    assert "50" in bar._ctx_heater_value.text()
    assert "\u043c\u0412\u0442" in bar._ctx_heater_value.text()


def test_nan_value_ignored(app, mock_channel_mgr):
    bar = TopWatchBar(mock_channel_mgr)
    _stop_timers(bar)
    bar.on_reading(_make_reading("\u04221 X", float("nan")))
    assert "\u2014" in bar._ctx_tmin_value.text()
