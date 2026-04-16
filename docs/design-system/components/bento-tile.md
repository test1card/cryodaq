---
title: BentoTile
keywords: tile, bento, cell, card, sub-surface, executive-kpi, data-dense, live, chart
applies_to: child widgets sitting inside BentoGrid
status: partial
implements: generic tiles scattered across legacy; Phase I.2 will formalize BentoTile class hierarchy
last_updated: 2026-04-17
---

# BentoTile

Child widget that sits inside a `BentoGrid` cell. Semantically **not** a standalone card — always a member of a grid composition.

**When to use:**
- As children inside a `BentoGrid` (this is the only valid context)
- For dashboard "panels" that display related content in a grid composition
- When the widget represents "one unit of information" within a larger dashboard

**When NOT to use:**
- As a standalone widget outside BentoGrid — use `Card` (`components/card.md`) instead
- For deeply nested compositions (tile inside tile) — violates RULE-SURF-005 / RULE-SURF-008
- For clickable navigation — tiles can contain interactive elements, but the tile frame itself should not be the click target; use embedded `Button` or make the tile explicitly interactive (then it IS a button)

## Semantic distinction: Tile vs Card

| Property | Card | BentoTile |
|---|---|---|
| Standalone? | Yes | No — always in a BentoGrid |
| Radius | RADIUS_LG (8) | RADIUS_MD (6) per hierarchy cascade |
| Padding | SPACE_5 (24) | CARD_PADDING (12) — tighter |
| Surface | SURFACE_CARD or SURFACE_ELEVATED | SURFACE_CARD |
| Can nest another card? | Not same category (RULE-SURF-005) | Not same category |
| Typical content | Full feature region | One KPI, one chart, one list, one status region |

The radius and padding differences enforce the hierarchy: Card contains Tile contains Content.

## Anatomy

```
┌────────────────────────────────┐
│  ◀── border: 1px BORDER        │
│  ◀── background: SURFACE_CARD  │
│  ◀── border-radius: RADIUS_MD  │
│     (6px — smaller than Card)  │
│                                │
│   ┌──── Optional ────┐         │
│   │  Title / header  │         │
│   └──────────────────┘         │
│                                │
│   ┌──────────────────┐         │
│   │                  │         │
│   │  Primary content │         │
│   │                  │         │
│   └──────────────────┘         │
│                                │
└────────────────────────────────┘
  ◀── padding: CARD_PADDING (12) all sides
```

## Parts

| Part | Required | Description |
|---|---|---|
| **Tile frame** | Yes | `QFrame` with painted surface per invariants |
| **Tile layout** | Yes | `QVBoxLayout` with `CARD_PADDING` symmetric margins |
| **Title row** | Optional | Small header, `FONT_LABEL_SIZE`, `MUTED_FOREGROUND` or UPPERCASE category label |
| **Primary content** | Yes | The meaningful payload — KPI number, chart, list, status widget |

## Invariants

1. **Radius RADIUS_MD = 6.** Subordinate to Card RADIUS_LG = 8 per hierarchy cascade. (RULE-SURF-006)
2. **Padding CARD_PADDING (12).** Tighter than Card's SPACE_5 (24). Use semantic alias. (RULE-SPACE-003)
3. **Single surface.** Only the tile frame paints. Internal content host transparent. (RULE-SURF-001, RULE-SURF-007)
4. **Symmetric padding.** All 4 sides equal. (RULE-SURF-003)
5. **Only inside BentoGrid.** Parent must be a BentoGrid. Standalone use is a design violation — use Card instead.
6. **Title is UPPERCASE category label** when present, per RULE-TYPO-008. Not sentence case body phrase.
7. **Max one primary accent.** Don't fill tile with three competing status colors. (RULE-COLOR-003)
8. **No shadow.** (RULE-SURF-010)

## API (proposed base class + subclasses)

Phase I.2 will formalize:

```python
# src/cryodaq/gui/shell/overlays/_design_system/bento_tile.py  (proposed)

class BentoTile(QWidget):
    """Base tile primitive for BentoGrid composition."""
    
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        title: str = "",
    ) -> None: ...
    
    def set_content(self, widget: QWidget) -> None: ...
    def set_title(self, title: str) -> None: ...


class ExecutiveKpiTile(BentoTile):
    """Large-number + small-label tile.
    Displays one key metric prominently (big display font).
    
    Example: "Pressure" / "1.23e-06 мбар"
    """
    
    def __init__(
        self,
        label: str,           # "ДАВЛЕНИЕ" — UPPERCASE category
        value: str,           # "1.23e-06 мбар" — formatted display
        parent: QWidget | None = None,
        *,
        status: str = "ok",   # color hint for value (optional)
    ) -> None: ...
    
    def set_value(self, value: str, status: str = "ok") -> None: ...


class DataDenseTile(BentoTile):
    """Grid or list of many data points.
    
    Example: sensor cell grid with 24 channels.
    """
    
    def __init__(
        self,
        title: str,
        parent: QWidget | None = None,
    ) -> None: ...
    
    def set_content(self, grid_widget: QWidget) -> None: ...


class LiveTile(BentoTile):
    """Time-series sparkline or live-updating numeric region."""
    
    def __init__(
        self,
        title: str,
        parent: QWidget | None = None,
    ) -> None: ...
```

## Variants

### Variant 1: ExecutiveKpiTile

Big number, small label. Use for "the one thing operator should see."

```python
# DESIGN: RULE-TYPO-008 (UPPERCASE label)
# DESIGN: RULE-TYPO-007 (FONT_DISPLAY_SIZE = 32, protected off-scale)
# DESIGN: RULE-TYPO-003 (tnum for numeric)
class ExecutiveKpiTile(BentoTile):
    def __init__(self, label: str, value: str, parent=None, *, status: str = "ok"):
        super().__init__(parent)
        
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_1)
        
        # Category label — UPPERCASE, MUTED
        label_widget = QLabel(label)
        label_font = QFont(theme.FONT_BODY, theme.FONT_LABEL_SIZE)
        label_font.setWeight(theme.FONT_LABEL_WEIGHT)
        label_font.setLetterSpacing(
            QFont.SpacingType.AbsoluteSpacing, 0.05 * theme.FONT_LABEL_SIZE
        )
        label_widget.setFont(label_font)
        label_widget.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
        
        # Hero value — FONT_DISPLAY, big
        self._value_widget = QLabel(value)
        value_font = QFont(theme.FONT_DISPLAY, theme.FONT_DISPLAY_SIZE)  # 32px
        value_font.setWeight(theme.FONT_DISPLAY_WEIGHT)
        value_font.setFeature("tnum", 1)
        value_font.setFeature("liga", 0)
        self._value_widget.setFont(value_font)
        self._set_value_color(status)
        
        layout.addWidget(label_widget)
        layout.addWidget(self._value_widget)
        layout.addStretch()
        
        self.set_content(content)
    
    def _set_value_color(self, status: str) -> None:
        color = {
            "ok": theme.FOREGROUND,
            "warning": theme.STATUS_WARNING,
            "fault": theme.STATUS_FAULT,
            "stale": theme.STATUS_STALE,
        }.get(status, theme.FOREGROUND)
        self._value_widget.setStyleSheet(f"color: {color};")
    
    def set_value(self, value: str, status: str = "ok") -> None:
        self._value_widget.setText(value)
        self._set_value_color(status)
```

### Variant 2: DataDenseTile (e.g., sensor grid)

Content-heavy tile showing many data points.

```python
# Used for e.g. 24-channel sensor grid inside overview dashboard
tile = DataDenseTile(title="ДАТЧИКИ")
sensor_grid = QGridLayout()
# ... populate with SensorCell widgets
tile.set_content(sensor_grid_container)
```

### Variant 3: LiveTile (sparkline + current value)

Small plot + current readout.

```python
tile = LiveTile(title="ДИНАМИКА Т11")
sparkline = pg.PlotWidget()
sparkline.setFixedHeight(80)
# ... configure pyqtgraph per chart-tokens rules
tile.set_content(sparkline_container)
```

### Variant 4: Plain BentoTile (generic content)

Default base — any custom content.

```python
tile = BentoTile(title="ЖУРНАЛ")
log_list = QListWidget()
tile.set_content(log_list)
```

## States

Like `Card`, tiles generally have one visual state unless they are specifically interactive:

| State | Visual treatment |
|---|---|
| **Default** | `SURFACE_CARD`, 1px `BORDER`, `RADIUS_MD` |
| **Content-derived status** (e.g., tile for faulted channel) | Left border 3px in STATUS_FAULT; rest unchanged |
| **Stale content** (data hasn't refreshed) | Reduce value text opacity to `STATUS_STALE` color; add stale indicator |
| **Loading (initial)** | Skeleton placeholder inside content host |

**Tiles should NOT have:**
- Hover/press states — if clickable, it's a button that looks like a tile (different component)
- Selected state — tiles are not list items
- Disabled state — a tile that's "off" should be hidden or show a clear "Нет данных" state

## Reference implementation (base BentoTile)

```python
# DESIGN: RULE-SURF-001, RULE-SURF-003, RULE-SURF-006, RULE-SURF-007, RULE-SPACE-003
class BentoTile(QWidget):
    """Base tile for BentoGrid children."""
    
    def __init__(self, parent=None, *, title: str = ""):
        super().__init__(parent)
        
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        
        self._frame = QFrame(self)
        self._frame.setObjectName("bentoTileFrame")
        # RULE-SURF-006 — RADIUS_MD (6), smaller than Card RADIUS_LG (8)
        # RULE-COLOR-001
        self._frame.setStyleSheet(
            f"#bentoTileFrame {{"
            f"  background: {theme.SURFACE_CARD};"
            f"  border: 1px solid {theme.BORDER};"
            f"  border-radius: {theme.RADIUS_MD}px;"
            f"}}"
        )
        outer.addWidget(self._frame)
        
        # RULE-SPACE-003 — CARD_PADDING, RULE-SURF-003 — symmetric
        inner = QVBoxLayout(self._frame)
        inner.setContentsMargins(
            theme.CARD_PADDING, theme.CARD_PADDING,
            theme.CARD_PADDING, theme.CARD_PADDING,
        )
        inner.setSpacing(theme.SPACE_2)
        
        # Title (optional)
        self._title_widget: QLabel | None = None
        if title:
            self._title_widget = self._make_title(title)
            inner.addWidget(self._title_widget)
        
        # Content host
        self._content_host = QWidget(self._frame)
        self._content_host.setObjectName("bentoTileContent")
        self._content_host.setStyleSheet(
            "#bentoTileContent { background: transparent; border: none; }"
        )
        content_layout = QVBoxLayout(self._content_host)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        inner.addWidget(self._content_host, 1)
    
    def _make_title(self, title: str) -> QLabel:
        # RULE-TYPO-008 UPPERCASE category label + RULE-TYPO-005 letter-spacing
        label = QLabel(title)
        font = QFont(theme.FONT_BODY, theme.FONT_LABEL_SIZE)
        font.setWeight(theme.FONT_LABEL_WEIGHT)
        font.setLetterSpacing(
            QFont.SpacingType.AbsoluteSpacing, 0.05 * theme.FONT_LABEL_SIZE
        )
        label.setFont(font)
        label.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
        return label
    
    def set_content(self, widget: QWidget) -> None:
        content_layout = self._content_host.layout()
        while content_layout.count():
            item = content_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        if widget is not None:
            widget.setParent(self._content_host)
            content_layout.addWidget(widget)
    
    def set_title(self, title: str) -> None:
        if self._title_widget is None:
            # Add title row at top
            self._title_widget = self._make_title(title)
            self._frame.layout().insertWidget(0, self._title_widget)
        else:
            self._title_widget.setText(title)
```

## Common mistakes

1. **Using a Card inside a BentoGrid.** Card has `RADIUS_LG` (8) + `SPACE_5` padding (24); that breaks the tile hierarchy. Use `BentoTile` (`RADIUS_MD` + `CARD_PADDING`). Or use the raw `BentoTile` and put chart/content inside.

2. **Using a BentoTile outside BentoGrid.** Standalone BentoTile on dashboard looks like an under-padded Card. If you need "a rectangle with content" outside a grid, use `PanelCard`.

3. **Title as sentence case.** "Давление" as tile title — use UPPERCASE "ДАВЛЕНИЕ" per RULE-TYPO-008. (Exception: very long titles that don't work uppercase.)

4. **Painting content_host background.** Same regression pattern as Card. Use explicit `background: transparent`. RULE-SURF-007.

5. **Putting ExecutiveKpi value in FONT_BODY.** KPI hero number should be FONT_DISPLAY (32px) — that's why it's a KPI. At body size it's not "executive."

6. **Left border fault indicator mixed with filled tile.** Don't fill tile with STATUS_FAULT AND add left border — one signal channel is enough. If whole tile is "fault state," show it prominently via the value's color (not the tile surface).

7. **Mixing fixed and auto row heights carelessly.** Rows size to tallest tile. A `row_span=1` tile next to a `row_span=3` tile aligns to the `row_span=1` height of its row — plan geometries accordingly.

## Related components

- `components/bento-grid.md` — The parent layout
- `components/card.md` — Standalone alternative when not in a grid
- `components/chart-tile.md` — BentoTile variant with pyqtgraph chart
- `cryodaq-primitives/sensor-cell.md` — Cell-level widget that commonly appears inside DataDenseTile

## Changelog

- 2026-04-17: Initial version. 4 proposed subclasses (BentoTile base, ExecutiveKpiTile, DataDenseTile, LiveTile). Hierarchy decision: Card → BentoTile, distinguished by radius and padding. Phase I.2 task will formalize these classes.
