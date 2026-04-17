"""BentoGrid — canonical 8-column grid container for Bento tile layout.

Per AD-001 (docs/design-system/components/bento-grid.md): 8 columns,
explicit placement, overlap validated, no auto-flow. Moving from the
earlier 12-column auto-flow variant is the Phase II alignment.
"""

from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QSizePolicy, QWidget

from cryodaq.gui import theme

DEFAULT_COLUMNS = 8


class BentoGrid(QWidget):
    """Canonical 8-column grid for dashboard Bento compositions.

    Tiles MUST be placed explicitly with `row`, `col`, `col_span`,
    `row_span`. Out-of-bounds placement and overlap with existing tiles
    raise ValueError immediately — silent layout bugs are worse than
    loud ones at dev time.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        columns: int = DEFAULT_COLUMNS,
        gap: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.columns = columns
        self.gap = theme.SPACE_3 if gap is None else gap
        # Track occupied cells as a set of (row, col) coordinate pairs
        # so overlap validation is O(tile_area) per add_tile.
        self._occupied: set[tuple[int, int]] = set()

        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setHorizontalSpacing(self.gap)
        self._layout.setVerticalSpacing(self.gap)
        for column in range(self.columns):
            self._layout.setColumnStretch(column, 1)

    def add_tile(
        self,
        tile: QWidget,
        *,
        col: int,
        row: int,
        col_span: int = 1,
        row_span: int = 1,
    ) -> None:
        """Place tile at (row, col) spanning (col_span × row_span) cells.

        `col` and `row` are required — there is no auto-flow. Raises
        ValueError on negative coordinates, out-of-bounds span, or
        overlap with an already-placed tile.
        """
        if col < 0 or row < 0:
            raise ValueError(
                f"Grid coordinates must be non-negative, got col={col} row={row}"
            )
        if col_span < 1 or row_span < 1:
            raise ValueError(
                f"Spans must be >= 1, got col_span={col_span} row_span={row_span}"
            )
        if col + col_span > self.columns:
            raise ValueError(
                f"Tile at col={col} with col_span={col_span} exceeds grid width "
                f"{self.columns}"
            )

        cells = [
            (r, c)
            for r in range(row, row + row_span)
            for c in range(col, col + col_span)
        ]
        clash = next((cell for cell in cells if cell in self._occupied), None)
        if clash is not None:
            raise ValueError(
                f"Tile at (row={row}, col={col}, col_span={col_span}, "
                f"row_span={row_span}) overlaps existing tile at "
                f"(row={clash[0]}, col={clash[1]})"
            )

        tile.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._layout.addWidget(tile, row, col, row_span, col_span)
        for row_index in range(row, row + row_span):
            self._layout.setRowStretch(row_index, 1)
        self._occupied.update(cells)

    def clear_tiles(self) -> None:
        """Remove all tiles from the grid and clear the occupancy map."""
        row_count = self._layout.rowCount()
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        self._occupied.clear()
        for row_index in range(row_count):
            self._layout.setRowStretch(row_index, 0)
