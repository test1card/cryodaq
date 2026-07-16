"""Tests for DynamicSensorGrid (Phase UI-1 v2 Block B.3)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from PySide6.QtWidgets import QVBoxLayout, QWidget

from cryodaq.gui.dashboard.dynamic_sensor_grid import DynamicSensorGrid
from cryodaq.gui.state.descriptor_store import IdentityStatus


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


def test_grid_reflows_from_logical_width_without_hiding_selected_sensors(app, mock_channel_mgr, buffer_store):
    grid = DynamicSensorGrid(mock_channel_mgr, buffer_store)
    selected = tuple(grid._cells)
    host = QWidget()
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(grid)

    host.resize(330, 320)
    host.show()
    app.processEvents()
    grid._relayout_cells()

    narrow_positions = [grid._grid_layout.getItemPosition(index)[:2] for index in range(grid._grid_layout.count())]
    assert narrow_positions == [(0, 0), (1, 0), (2, 0)]
    assert tuple(grid._cells) == selected
    assert all(cell.isVisible() for cell in grid._cells.values())

    host.resize(700, 320)
    app.processEvents()
    grid._relayout_cells()

    wide_positions = [grid._grid_layout.getItemPosition(index)[:2] for index in range(grid._grid_layout.count())]
    assert wide_positions == [(0, 0), (0, 1), (0, 2)]
    assert tuple(grid._cells) == selected


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
        assert expected in actual, f"Cell {ch_id!r} must display '{expected}' after refresh, got {actual!r}"


def test_grid_dispatch_coalesces_until_tick_and_renders_latest(app, mock_channel_mgr, buffer_store):
    from cryodaq.drivers.base import ChannelStatus, Reading

    grid = DynamicSensorGrid(mock_channel_mgr, buffer_store)
    cell = grid._cells.get("\u04221")
    assert cell is not None
    before = cell._value_widget.text()

    for value in (77.1, 77.2, 77.3):
        reading = Reading(
            channel="\u04221 \u041a\u0440\u0438\u043e\u0441\u0442\u0430\u0442 \u0432\u0435\u0440\u0445",
            value=value,
            unit="K",
            timestamp=datetime.now(UTC),
            status=ChannelStatus.OK,
            instrument_id="lakeshore_218s",
        )
        grid.dispatch_reading(reading, IdentityStatus.AUTHORITATIVE)
        assert cell._value_widget.text() == before

    grid.refresh()

    assert "77.30" in cell._value_widget.text()
    assert grid._pending_readings == {}


def test_coalesced_cut_uses_source_timestamp_for_staleness(app, mock_channel_mgr, buffer_store):
    from cryodaq.drivers.base import ChannelStatus, Reading

    grid = DynamicSensorGrid(mock_channel_mgr, buffer_store)
    grid.dispatch_reading(
        Reading(
            channel="\u04221 \u041a\u0440\u0438\u043e\u0441\u0442\u0430\u0442 \u0432\u0435\u0440\u0445",
            value=77.3,
            unit="K",
            timestamp=datetime.now(UTC) - timedelta(seconds=30),
            status=ChannelStatus.OK,
            instrument_id="lakeshore_218s",
        ),
        IdentityStatus.AUTHORITATIVE,
    )

    grid.refresh()

    cell = grid._cells["\u04221"]
    assert cell._value_widget.text() == "77.30"
    assert cell._data_stale is True
    assert cell._status_hint_widget.text() == "\u0423\u0441\u0442\u0430\u0440\u0435\u043b\u043e"


def test_grid_read_only_survives_cell_rebuild(app, mock_channel_mgr, buffer_store):
    grid = DynamicSensorGrid(mock_channel_mgr, buffer_store)
    grid.set_read_only(True)
    assert all(cell._read_only for cell in grid._cells.values())

    mock_channel_mgr.set_visible("Т2", False)
    mock_channel_mgr._notify()

    assert grid._read_only is True
    assert all(cell._read_only for cell in grid._cells.values())


def test_grid_close_event_cleans_up(app, mock_channel_mgr, buffer_store):
    grid = DynamicSensorGrid(mock_channel_mgr, buffer_store)
    assert grid._on_channels_changed in mock_channel_mgr._callbacks
    from PySide6.QtGui import QCloseEvent

    grid.closeEvent(QCloseEvent())
    assert grid._on_channels_changed not in mock_channel_mgr._callbacks
