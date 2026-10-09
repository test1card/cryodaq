"""Tests for DynamicSensorGrid (Phase UI-1 v2 Block B.3)."""

from __future__ import annotations

from datetime import UTC

from cryodaq.gui.dashboard.dynamic_sensor_grid import DynamicSensorGrid


def test_grid_constructs(app, mock_channel_mgr, buffer_store):
    grid = DynamicSensorGrid(mock_channel_mgr, buffer_store)
    assert grid is not None
    assert grid.objectName() == "dynamicSensorGrid"


def test_grid_creates_cells_for_visible_channels(app, mock_channel_mgr, buffer_store):
    grid = DynamicSensorGrid(mock_channel_mgr, buffer_store)
    assert len(grid._cells) == 3
    assert "\u04221" in grid._cells
    assert "\u04222" in grid._cells
    assert "\u04223" in grid._cells


def test_grid_rebuilds_on_channel_change(app, mock_channel_mgr, buffer_store):
    grid = DynamicSensorGrid(mock_channel_mgr, buffer_store)
    initial_count = len(grid._cells)
    mock_channel_mgr.set_visible("\u04222", False)
    mock_channel_mgr._notify()
    assert len(grid._cells) == initial_count - 1
    assert "\u04222" not in grid._cells


def test_grid_refresh_calls_each_cell(app, mock_channel_mgr, buffer_store):
    grid = DynamicSensorGrid(mock_channel_mgr, buffer_store)
    grid.refresh()  # should not raise


def test_grid_dispatch_reading(app, mock_channel_mgr, buffer_store):
    from datetime import datetime

    from cryodaq.drivers.base import ChannelStatus, Reading

    grid = DynamicSensorGrid(mock_channel_mgr, buffer_store)
    reading = Reading(
        channel="\u04221 \u041a\u0440\u0438\u043e\u0441\u0442\u0430\u0442 \u0432\u0435\u0440\u0445",
        value=77.3,
        unit="K",
        timestamp=datetime.now(UTC),
        status=ChannelStatus.OK,
        instrument_id="lakeshore_218s",
    )
    grid.dispatch_reading(reading)
    cell = grid._cells.get("\u04221")
    assert cell is not None
    assert "77.30" in cell._value_widget.text()


def test_grid_close_event_cleans_up(app, mock_channel_mgr, buffer_store):
    grid = DynamicSensorGrid(mock_channel_mgr, buffer_store)
    assert grid._on_channels_changed in mock_channel_mgr._callbacks
    from PySide6.QtGui import QCloseEvent

    grid.closeEvent(QCloseEvent())
    assert grid._on_channels_changed not in mock_channel_mgr._callbacks
