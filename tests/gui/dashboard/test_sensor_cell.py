"""Tests for SensorCell (Phase UI-1 v2 Block B.3)."""
from __future__ import annotations

from datetime import datetime, timezone

from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.gui.dashboard.sensor_cell import SensorCell


def test_sensor_cell_constructs(app, mock_channel_mgr, buffer_store):
    cell = SensorCell("\u04221", mock_channel_mgr, buffer_store)
    assert cell is not None
    assert cell.objectName() == "sensorCell"


def test_sensor_cell_displays_label(app, mock_channel_mgr, buffer_store):
    cell = SensorCell("\u04221", mock_channel_mgr, buffer_store)
    assert "\u04221" in cell._label_widget.text()


def test_sensor_cell_update_value_with_reading(
    app, mock_channel_mgr, buffer_store
):
    cell = SensorCell("\u04221", mock_channel_mgr, buffer_store)
    reading = Reading(
        channel="\u04221 \u041a\u0440\u0438\u043e\u0441\u0442\u0430\u0442 \u0432\u0435\u0440\u0445",
        value=4.21,
        unit="K",
        timestamp=datetime.now(timezone.utc),
        status=ChannelStatus.OK,
        instrument_id="lakeshore_218s",
    )
    cell.update_value(reading)
    assert "4.21" in cell._value_widget.text()
    assert cell._unit_widget.text() == "K"
    assert cell._last_status == ChannelStatus.OK


def test_sensor_cell_refresh_from_empty_buffer_marks_stale(
    app, mock_channel_mgr, buffer_store
):
    cell = SensorCell("\u04221", mock_channel_mgr, buffer_store)
    cell.refresh_from_buffer()
    assert cell._data_stale is True


def test_sensor_cell_inline_rename_signals(
    app, mock_channel_mgr, buffer_store
):
    cell = SensorCell("\u04221", mock_channel_mgr, buffer_store)
    received = []
    cell.rename_requested.connect(
        lambda ch, name: received.append((ch, name))
    )
    cell._enter_rename_mode()
    assert cell._is_renaming is True
    cell._rename_edit.setText("\u041d\u043e\u0432\u043e\u0435 \u0438\u043c\u044f")
    cell._commit_rename()
    assert received == [("\u04221", "\u041d\u043e\u0432\u043e\u0435 \u0438\u043c\u044f")]
    assert cell._is_renaming is False


def test_sensor_cell_rename_escape_cancels(
    app, mock_channel_mgr, buffer_store
):
    cell = SensorCell("\u04221", mock_channel_mgr, buffer_store)
    cell._enter_rename_mode()
    assert cell._is_renaming is True
    cell._exit_rename_mode()
    assert cell._is_renaming is False
    assert cell._rename_edit is None


def test_sensor_cell_update_value_large_number(
    app, mock_channel_mgr, buffer_store
):
    cell = SensorCell("\u04221", mock_channel_mgr, buffer_store)
    reading = Reading(
        channel="\u04221 \u041a\u0440\u0438\u043e\u0441\u0442\u0430\u0442 \u0432\u0435\u0440\u0445",
        value=1500.0,
        unit="K",
        timestamp=datetime.now(timezone.utc),
        status=ChannelStatus.OK,
        instrument_id="lakeshore_218s",
    )
    cell.update_value(reading)
    assert "e" in cell._value_widget.text().lower()


def test_sensor_cell_stale_recovery(app, mock_channel_mgr, buffer_store):
    """After refresh marks cell stale, update_value with OK must restore style."""
    cell = SensorCell("\u04221", mock_channel_mgr, buffer_store)
    # Push a reading to set status to OK
    reading = Reading(
        channel="\u04221 \u041a\u0440\u0438\u043e\u0441\u0442\u0430\u0442 \u0432\u0435\u0440\u0445",
        value=4.2,
        unit="K",
        timestamp=datetime.now(timezone.utc),
        status=ChannelStatus.OK,
        instrument_id="lakeshore_218s",
    )
    cell.update_value(reading)
    assert cell._last_status == ChannelStatus.OK
    assert cell._data_stale is False
    # Simulate stale via empty buffer refresh
    cell._data_stale = False  # reset guard
    cell._buffer = buffer_store  # empty
    cell.refresh_from_buffer()
    assert cell._data_stale is True
    # Push another OK reading — must re-apply OK border (Finding 2 fix)
    cell.update_value(reading)
    assert cell._data_stale is False
    assert cell._last_status == ChannelStatus.OK
    # Verify border is not stale anymore
    ss = cell.styleSheet()
    from cryodaq.gui import theme

    assert theme.STATUS_OK in ss


def test_sensor_cell_update_value_small_number(
    app, mock_channel_mgr, buffer_store
):
    cell = SensorCell("\u04221", mock_channel_mgr, buffer_store)
    reading = Reading(
        channel="\u04221 \u041a\u0440\u0438\u043e\u0441\u0442\u0430\u0442 \u0432\u0435\u0440\u0445",
        value=0.005,
        unit="K",
        timestamp=datetime.now(timezone.utc),
        status=ChannelStatus.OK,
        instrument_id="lakeshore_218s",
    )
    cell.update_value(reading)
    assert "e" in cell._value_widget.text().lower()
