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
    import time

    grid = DynamicSensorGrid(mock_channel_mgr, buffer_store)

    # Seed the buffer with fresh data for each channel so refresh_from_buffer
    # actually updates the displayed value (not just calls through to stale path).
    seed_values = {"Т1": 77.5, "Т2": 55.3, "Т3": 42.1}
    now = time.time()
    for ch_id, val in seed_values.items():
        buffer_store.append(ch_id, now, val)

    # Spy on each cell's refresh_from_buffer to confirm it is called.
    call_counts: dict[str, int] = {ch_id: 0 for ch_id in grid._cells}
    original_methods: dict[str, object] = {}
    for ch_id, cell in grid._cells.items():
        original = cell.refresh_from_buffer
        original_methods[ch_id] = original

        def _make_spy(cid: str, orig):
            def _spy():
                call_counts[cid] += 1
                orig()
            return _spy

        cell.refresh_from_buffer = _make_spy(ch_id, original)

    grid.refresh()

    for ch_id in grid._cells:
        assert call_counts[ch_id] == 1, (
            f"cell {ch_id!r}.refresh_from_buffer() called {call_counts[ch_id]} times, expected 1"
        )

    # Restore originals.
    for ch_id, cell in grid._cells.items():
        cell.refresh_from_buffer = original_methods[ch_id]

    # Assert each cell's displayed value was updated through the real path.
    # Prod formats as f"{value:.2f}" for values in 0.01..1000 range.
    for ch_id, val in seed_values.items():
        cell = grid._cells[ch_id]
        expected = f"{val:.2f}"
        actual = cell._value_widget.text()
        assert expected in actual, (
            f"Cell {ch_id!r} must display '{expected}' after refresh, got {actual!r}"
        )


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
