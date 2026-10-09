"""Responsive grid of SensorCell widgets for visible channels.

Layout adapts to available width: cell minimum width 160px,
columns = floor(width / min_width), rows = ceil(n / cols).
Subscribes to ChannelManager.on_change for runtime updates
with proper cleanup via off_change.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGridLayout, QVBoxLayout, QWidget

from cryodaq.core.channel_manager import ChannelManager
from cryodaq.drivers.base import Reading
from cryodaq.gui import theme
from cryodaq.gui.dashboard.channel_buffer import ChannelBufferStore
from cryodaq.gui.dashboard.sensor_cell import SensorCell

logger = logging.getLogger(__name__)


class DynamicSensorGrid(QWidget):
    """Responsive grid of SensorCell widgets for visible channels."""

    rename_requested = Signal(str, str)  # channel_id, new_name
    hide_requested = Signal(str)  # channel_id
    show_on_plot_requested = Signal(str)  # channel_id
    history_requested = Signal(str)  # channel_id

    _MIN_CELL_WIDTH = 160
    _CELL_HEIGHT = 80

    def __init__(
        self,
        channel_manager: ChannelManager,
        buffer_store: ChannelBufferStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._channel_mgr = channel_manager
        self._buffer = buffer_store
        self._cells: dict[str, SensorCell] = {}
        self._build_ui()
        self._rebuild_cells()
        self._channel_mgr.on_change(self._on_channels_changed)
        # Backup cleanup: destroyed fires even when closeEvent is
        # bypassed during parent-driven destruction.
        mgr = self._channel_mgr
        cb = self._on_channels_changed
        self.destroyed.connect(lambda: mgr.off_change(cb))

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.setObjectName("dynamicSensorGrid")
        root = QVBoxLayout(self)
        root.setContentsMargins(
            theme.SPACE_2,
            theme.SPACE_2,
            theme.SPACE_2,
            theme.SPACE_2,
        )
        root.setSpacing(theme.SPACE_2)

        self._grid_widget = QWidget()
        self._grid_widget.setObjectName("sensorGridContainer")
        self._grid_layout = QGridLayout(self._grid_widget)
        self._grid_layout.setSpacing(theme.SPACE_2)
        self._grid_layout.setContentsMargins(0, 0, 0, 0)

        root.addWidget(self._grid_widget)

    # ------------------------------------------------------------------
    # Cell management
    # ------------------------------------------------------------------

    def _rebuild_cells(self) -> None:
        """Remove all existing cells and create fresh ones from
        current visible channel set."""
        for cell in self._cells.values():
            self._grid_layout.removeWidget(cell)
            cell.deleteLater()
        self._cells.clear()

        visible_ids = [
            ch
            for ch in self._channel_mgr.get_all_visible()
            if ch.startswith("\u0422")  # cyrillic Т
        ]

        for ch_id in visible_ids:
            cell = SensorCell(ch_id, self._channel_mgr, self._buffer, self)
            cell.rename_requested.connect(self.rename_requested)
            cell.hide_requested.connect(self.hide_requested)
            cell.show_on_plot_requested.connect(self.show_on_plot_requested)
            cell.history_requested.connect(self.history_requested)
            self._cells[ch_id] = cell

        self._relayout_cells()

    def _relayout_cells(self) -> None:
        """Compute optimal column count from current width and place
        cells in the grid layout."""
        n_cells = len(self._cells)
        if n_cells == 0:
            return

        available_width = self._grid_widget.width()
        if available_width <= 0:
            cols = min(7, n_cells)
        else:
            cols = max(
                1,
                available_width // (self._MIN_CELL_WIDTH + self._grid_layout.spacing()),
            )
            cols = min(cols, n_cells)

        # Clear current grid placement
        while self._grid_layout.count() > 0:
            self._grid_layout.takeAt(0)

        for idx, (ch_id, cell) in enumerate(self._cells.items()):
            row = idx // cols
            col = idx % cols
            self._grid_layout.addWidget(cell, row, col)
            cell.setMinimumWidth(self._MIN_CELL_WIDTH)
            cell.setMinimumHeight(self._CELL_HEIGHT)

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def resizeEvent(self, event):  # noqa: ANN001
        super().resizeEvent(event)
        self._relayout_cells()

    # ------------------------------------------------------------------
    # Refresh / dispatch
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Refresh all cells from buffer store (called at 1 Hz)."""
        for cell in self._cells.values():
            cell.refresh_from_buffer()

    def dispatch_reading(self, reading: Reading) -> None:
        """Push a reading to the relevant cell (if any)."""
        short_id = reading.channel.split(" ")[0]
        cell = self._cells.get(short_id)
        if cell is not None:
            cell.update_value(reading)

    # ------------------------------------------------------------------
    # Channel manager hooks
    # ------------------------------------------------------------------

    def _on_channels_changed(self) -> None:
        """Visible channel set changed — rebuild cells."""
        self._rebuild_cells()

    def closeEvent(self, event):  # noqa: ANN001
        """Clean up ChannelManager subscription on close."""
        try:
            self._channel_mgr.off_change(self._on_channels_changed)
        except Exception:
            pass
        super().closeEvent(event)
