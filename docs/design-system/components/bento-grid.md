---
title: BentoGrid
keywords: bento, grid, layout, dashboard, tile, responsive, columns, spans
applies_to: modular dashboard layouts with heterogeneous tile sizes
status: active
implements: src/cryodaq/gui/shell/overlays/_design_system/bento_grid.py
last_updated: 2026-04-17
---

# BentoGrid

Modular grid layout for arranging heterogeneous tiles in a dashboard composition. Named after the Japanese bento box metaphor: compartments of varying sizes forming a coherent whole.

**When to use:**
- Dashboard layouts with mixed tile sizes (big chart + small KPIs + medium status panel)
- Any page where content cells have different widths or heights
- Overlay panels that need to organize multiple information tiles

**When NOT to use:**
- Uniform grids with equal-sized cells — use `QGridLayout` directly, no need for bento structure
- Linear layouts (single column or single row of items) — use `QVBoxLayout` / `QHBoxLayout`
- Flow layouts that wrap — use `QFlowLayout` or equivalent
- Scroll-through content (lists) — use `QListView` / `QAbstractItemView`

## Visual model

```
  col 0  1  2  3  4  5  6  7
 ┌───┬───┬───┬───┬───┬───┬───┬───┐
 │ A │ A │ A │ A │ B │ B │ B │ B │ row 0   A: col=0, row=0, col_span=4
 ├───┼───┼───┼───┼───┼───┼───┼───┤           B: col=4, row=0, col_span=4
 │ C │ C │ C │ C │ D │ D │ D │ D │ row 1   C: col=0, row=1, col_span=4
 ├───┼───┼───┼───┼───┼───┼───┼───┤           D: col=4, row=1, col_span=4
 │ E │ E │ E │ E │ F │ F │ G │ G │ row 2   E: col=0, row=2, col_span=4
 └───┴───┴───┴───┴───┴───┴───┴───┘           F: col=4, row=2, col_span=2
                                              G: col=6, row=2, col_span=2
  ◀── GRID_GAP (8px) between all tiles
```

The grid is **8 columns wide** by default — narrow enough to maintain readable tile widths at 1920 viewport, wide enough to mix 2/3/4/8-column tiles for visual variety.

## Parts

| Part | Required | Description |
|---|---|---|
| **Grid container** | Yes | `QWidget` hosting `QGridLayout` |
| **Tile cells** | Yes | `BentoTile` children positioned via `add_tile()` API |
| **Horizontal spacing** | Yes | `GRID_GAP` (8px) between columns (RULE-SPACE-003) |
| **Vertical spacing** | Yes | `GRID_GAP` (8px) between rows |
| **Outer margins** | Yes | `SPACE_0` (0px) — grid itself has no margin. Outer spacing comes from parent container (RULE-SPACE-002) |

## Invariants

1. **8-column canonical width.** Default column count. Changes to column count require product decision — do not change per-viewport to stay close to design language consistency.
2. **GRID_GAP for spacing.** Use `theme.GRID_GAP` token (semantic alias for `SPACE_2 = 8`), not raw. (RULE-SPACE-003)
3. **Tiles span integer columns/rows.** Fractional spans not supported. Valid: 1, 2, 3, 4, 6, 8 columns. (4+4 = 8 most common split)
4. **Grid itself has no margin.** Outer margins belong to the parent container. (RULE-SPACE-004)
5. **Tile placement validated.** `col + col_span <= num_columns`, no overlapping placements.
6. **Row heights follow content.** Row heights not fixed; tiles size to content with minimum. For fixed-height regions use `QGridLayout.setRowMinimumHeight()`.

## API

Reference implementation in `src/cryodaq/gui/shell/overlays/_design_system/bento_grid.py`:

```python
class BentoGrid(QWidget):
    """Modular grid layout for heterogeneous tile compositions."""
    
    DEFAULT_COLUMNS = 8
    
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        columns: int = DEFAULT_COLUMNS,
    ) -> None:
        super().__init__(parent)
        self._columns = columns
        
        # DESIGN: RULE-SURF-007 — transparent container (not its own surface)
        self.setStyleSheet("background: transparent; border: none;")
        
        self._layout = QGridLayout(self)
        # DESIGN: RULE-SPACE-003
        self._layout.setHorizontalSpacing(theme.GRID_GAP)
        self._layout.setVerticalSpacing(theme.GRID_GAP)
        # DESIGN: RULE-SPACE-002 — no outer margin on grid itself
        self._layout.setContentsMargins(0, 0, 0, 0)
        
        # Track placements to detect overlaps
        self._placements: list[tuple[int, int, int, int]] = []  # (col, row, cs, rs)
    
    def add_tile(
        self,
        tile: QWidget,
        *,
        col: int,
        row: int,
        col_span: int = 1,
        row_span: int = 1,
    ) -> None:
        """Place a tile at grid position with span.
        
        Raises ValueError on out-of-bounds or overlap.
        """
        if col < 0 or col + col_span > self._columns:
            raise ValueError(
                f"Tile col={col} col_span={col_span} out of bounds "
                f"(columns={self._columns})"
            )
        if row < 0:
            raise ValueError(f"Tile row={row} negative")
        
        new_placement = (col, row, col_span, row_span)
        for existing in self._placements:
            if self._overlaps(new_placement, existing):
                raise ValueError(
                    f"Tile placement {new_placement} overlaps existing {existing}"
                )
        
        self._placements.append(new_placement)
        self._layout.addWidget(tile, row, col, row_span, col_span)
    
    @staticmethod
    def _overlaps(
        a: tuple[int, int, int, int],
        b: tuple[int, int, int, int],
    ) -> bool:
        ac, ar, acs, ars = a
        bc, br, bcs, brs = b
        # Check column ranges and row ranges overlap
        col_overlap = not (ac + acs <= bc or bc + bcs <= ac)
        row_overlap = not (ar + ars <= br or br + brs <= ar)
        return col_overlap and row_overlap
    
    def clear_tiles(self) -> None:
        """Remove all tiles from the grid."""
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._placements.clear()
    
    @property
    def columns(self) -> int:
        return self._columns
```

## Canonical layout patterns

### Pattern 1: 4+4 split

Two equal-width tiles side by side. Most common for overview dashboards.

```python
grid = BentoGrid()
grid.add_tile(chart_tile, col=0, row=0, col_span=4)
grid.add_tile(kpi_tile, col=4, row=0, col_span=4)
```

### Pattern 2: 6+2 split

Primary content with sidebar detail.

```python
grid = BentoGrid()
grid.add_tile(main_chart, col=0, row=0, col_span=6, row_span=2)
grid.add_tile(kpi_1, col=6, row=0, col_span=2)
grid.add_tile(kpi_2, col=6, row=1, col_span=2)
```

### Pattern 3: 2+2+2+2 row (four equal)

Row of four small KPI tiles.

```python
grid = BentoGrid()
grid.add_tile(tile_1, col=0, row=0, col_span=2)
grid.add_tile(tile_2, col=2, row=0, col_span=2)
grid.add_tile(tile_3, col=4, row=0, col_span=2)
grid.add_tile(tile_4, col=6, row=0, col_span=2)
```

### Pattern 4: Asymmetric with tall tile

Big chart on left, stack of small tiles on right.

```python
grid = BentoGrid()
grid.add_tile(chart, col=0, row=0, col_span=5, row_span=3)
grid.add_tile(stat_1, col=5, row=0, col_span=3)
grid.add_tile(stat_2, col=5, row=1, col_span=3)
grid.add_tile(stat_3, col=5, row=2, col_span=3)
```

### Pattern 5: Mixed spans

Demonstrates asymmetric composition — 4+4 top row, 4+2+2 bottom row.

```python
grid = BentoGrid()
grid.add_tile(big_a, col=0, row=0, col_span=4)
grid.add_tile(big_b, col=4, row=0, col_span=4)
grid.add_tile(big_c, col=0, row=1, col_span=4)
grid.add_tile(small_a, col=4, row=1, col_span=2)
grid.add_tile(small_b, col=6, row=1, col_span=2)
```

## Reference implementation notes

Phase I.1 implementation (`bento_grid.py`) is functional but has these deliberate limitations documented here:

- **No drag-to-reorder.** Tile layout is declarative at construction time. Operators cannot rearrange tiles by dragging. If dashboard customization becomes a requirement, that's a separate feature requiring state persistence.
- **No responsive column reduction.** At narrow viewport widths, tiles with large `col_span` remain their assigned width — grid does not collapse to fewer columns. Because CryoDAQ is desktop-only (1280+ min viewport per `tokens/breakpoints.md`), this is acceptable.
- **No auto-placement.** All tiles require explicit `col, row, col_span, row_span`. There is no "auto-flow" mode that finds next free cell. Explicit placement prevents surprise layouts.

## Common mistakes

1. **Raw `SPACE_2` instead of `GRID_GAP`.** Both resolve to 8px but semantic intent differs. Use `theme.GRID_GAP`. (RULE-SPACE-003)

2. **Outer margin on grid itself.** `grid.setContentsMargins(SPACE_5, ...)` — should be zero. Outer spacing belongs to parent container. (RULE-SPACE-002)

3. **Overlapping placements.** Without the overlap check, two tiles placed at same cell would Z-stack unpredictably. The API raises `ValueError` at `add_tile()` time.

4. **`col + col_span > columns`.** Placing a 6-wide tile at column 4 in an 8-column grid would overflow. API raises at placement.

5. **Nesting BentoGrid inside BentoGrid.** Don't. A child tile should not itself contain a BentoGrid — it creates visual noise and column-alignment ambiguity. If you need sub-grouping within a tile, use a simpler layout (VBox/HBox) inside the tile.

6. **Using for uniform layouts.** If all tiles are same size, BentoGrid is overkill. Use `QGridLayout` or the straightforward `QGridLayout.addWidget(w, row, col)` pattern.

## Related components

- `components/bento-tile.md` — The child primitive that sits inside BentoGrid cells
- `components/chart-tile.md` — Specialized BentoTile variant for pyqtgraph charts
- `cryodaq-primitives/experiment-card.md` — Uses BentoGrid internally for phase+metadata layout
- `patterns/page-scaffolds.md` — Where BentoGrid fits in page composition patterns

## Changelog

- 2026-04-17: Initial version documenting the Phase I.1 implementation. 8-column default, GRID_GAP spacing, explicit placement, no auto-flow. Limitations around drag-reorder and responsive collapse documented as accepted trade-offs for desktop-only industrial context.
