"""BentoGrid — 12-column grid container for Bento tile layout."""
from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QSizePolicy, QWidget

from cryodaq.gui import theme


class BentoGrid(QWidget):
    """Lightweight 12-column grid wrapper for future Bento tiles."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        columns: int = 12,
        gap: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.columns = columns
        self.gap = theme.SPACE_3 if gap is None else gap
        self._auto_index = 0
        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setHorizontalSpacing(self.gap)
        self._layout.setVerticalSpacing(self.gap)
        for column in range(self.columns):
            self._layout.setColumnStretch(column, 1)

    def add_tile(
        self,
        tile: QWidget,
        col: int | None = None,
        row: int | None = None,
        col_span: int = 1,
        row_span: int = 1,
    ) -> None:
        """Place tile into the grid with optional row-major auto-flow."""
        if col is None or row is None:
            row = self._auto_index // self.columns
            col = self._auto_index % self.columns
            self._auto_index += col_span

        if col < 0 or row < 0:
            raise ValueError("Grid coordinates must be non-negative")
        if col + col_span > self.columns:
            raise ValueError("col + col_span must be <= columns")

        tile.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._layout.addWidget(tile, row, col, row_span, col_span)
        for row_index in range(row, row + row_span):
            self._layout.setRowStretch(row_index, 1)

    def clear_tiles(self) -> None:
        """Remove all tiles from the grid."""
        row_count = self._layout.rowCount()
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        self._auto_index = 0
        for row_index in range(row_count):
            self._layout.setRowStretch(row_index, 0)
