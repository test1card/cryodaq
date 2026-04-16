---
title: Card
keywords: card, panel, container, surface, tile, primitive
applies_to: generic container widget with one surface
status: partial
implements: src/cryodaq/gui/shell/overlays/_design_system/modal_card.py (current; PanelCard is a proposed future extraction)
last_updated: 2026-04-17
---

# Card

Generic rounded container with one visible surface. The foundational composition primitive for CryoDAQ UI.

> **Proposed:** `PanelCard` is a future extraction target — a generic card base factored out of `ModalCard`. The current implementation uses `ModalCard` at `src/cryodaq/gui/shell/overlays/_design_system/modal_card.py`. `panel_card.py` does not yet exist. See `governance/contribution.md` for the extraction process. Every mention of `PanelCard` below (including the API, variants, and implementation sketch) describes the proposed generic primitive, not shipped code.

**When to use:**
- Grouping related content into a visually distinct unit on a dashboard or panel
- Creating a self-contained display region (sensor readings, a chart, a form section)
- Any container that should read as "one thing" visually

**When NOT to use:**
- When the container has no own purpose beyond layout grouping — use a transparent `QWidget` per RULE-SURF-007
- When the container is an overlay with backdrop — use `Modal` (`components/modal.md`)
- When the container is anchored to a trigger element — use `Popover` (`components/popover.md`)
- When the container fills the entire viewport — it's a page scaffold, not a card

## Anatomy

```
┌───────────────────────────────────────────┐
│ ◀── border: 1px solid BORDER             │
│ ◀── background: SURFACE_CARD              │
│ ◀── border-radius: RADIUS_LG (8px)        │
│                                           │
│  ┌─────────────────────────────────────┐  │
│  │  [optional] Header row              │  │
│  └─────────────────────────────────────┘  │
│                                           │
│  ┌─────────────────────────────────────┐  │
│  │                                     │  │
│  │  Content host (transparent)         │  │
│  │                                     │  │
│  └─────────────────────────────────────┘  │
│                                           │
│  ┌─────────────────────────────────────┐  │
│  │  [optional] Footer / actions row    │  │
│  └─────────────────────────────────────┘  │
│                                           │
└───────────────────────────────────────────┘
  ◀── padding: SPACE_5 all sides (symmetric)
```

## Parts

| Part | Required | Description |
|---|---|---|
| **Card frame** | Yes | Outer `QFrame` with painted surface, border, radius |
| **Card layout** | Yes | `QVBoxLayout` with symmetric `SPACE_5` contentsMargins |
| **Header row** | No | `QWidget` (transparent) containing title, breadcrumb, or header controls |
| **Content host** | Yes | `QWidget` (transparent) holding the body content |
| **Footer row** | No | `QWidget` (transparent) for actions, CTAs, or metadata |

## Invariants

1. **Single painted surface.** Only the card frame paints background/border/radius. Header/content/footer wrappers are transparent. (RULE-SURF-001, RULE-SURF-007)
2. **Symmetric padding.** `setContentsMargins(SPACE_5, SPACE_5, SPACE_5, SPACE_5)`. Asymmetry requires documented exception. (RULE-SURF-003)
3. **Radius cascade.** Card `RADIUS_LG = 8`. Any painted child surface (nested tile, inset panel) must use smaller radius (`RADIUS_MD = 6` or `RADIUS_SM = 4`). (RULE-SURF-002, RULE-SURF-006)
4. **One primary accent.** Only one status color, accent color, or distinctive hue may dominate inside a single card. (RULE-COLOR-003)
5. **Zero shadow.** No `QGraphicsDropShadowEffect`. Elevation comes from surface brightness and border. (RULE-SURF-010)
6. **Max nesting 3 surface levels.** Card cannot contain another card containing another card with painted surfaces. (RULE-SURF-008)

## API (proposed `PanelCard` class)

```python
class PanelCard(QWidget):
    """Generic rounded container with one visible surface.
    
    Slot-based composition: consumers populate header_slot, content_host,
    and footer_slot via API methods. The card guarantees surface invariants.
    """
    
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        surface: str = "card",         # "card" (SURFACE_CARD) | "elevated" (SURFACE_ELEVATED)
        padding: int | None = None,    # defaults to SPACE_5; must stay symmetric
    ) -> None:
        ...
    
    def set_header(self, widget: QWidget) -> None:
        """Install widget into header slot. Replaces any prior header."""
    
    def set_content(self, widget: QWidget) -> None:
        """Install widget into content host. Replaces any prior content."""
    
    def set_footer(self, widget: QWidget) -> None:
        """Install widget into footer slot. Replaces any prior footer."""
    
    def set_surface(self, surface: str) -> None:
        """Switch between 'card' and 'elevated' surface tones at runtime."""
```

Consumers compose:

```python
card = PanelCard(surface="card")
card.set_header(header_row_widget)
card.set_content(chart_widget)
card.set_footer(actions_widget)
```

## Variants

### Variant 1: Content-only card

Plain card with just content host. Default use case.

```python
# DESIGN: RULE-SURF-001, RULE-SURF-003
card = PanelCard(surface="card")
card.set_content(sensor_grid_widget)
```

### Variant 2: Titled card

Card with header row containing a title label.

```python
# DESIGN: RULE-SURF-004
header = QWidget()
header_layout = QHBoxLayout(header)
header_layout.setContentsMargins(0, 0, 0, 0)
header_layout.setSpacing(theme.SPACE_2)

title_font = QFont(theme.FONT_BODY, theme.FONT_LABEL_SIZE)
title_font.setWeight(theme.FONT_WEIGHT_MEDIUM)
title_font.setLetterSpacing(
    QFont.SpacingType.AbsoluteSpacing, 0.05 * theme.FONT_LABEL_SIZE
)
title = QLabel("ДАВЛЕНИЕ")  # DESIGN: RULE-TYPO-008, RULE-TYPO-005
title.setFont(title_font)
title.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
header_layout.addWidget(title)
header_layout.addStretch()

card.set_header(header)
```

### Variant 3: Card with footer actions

Card with action buttons in footer.

```python
footer = QWidget()
footer_layout = QHBoxLayout(footer)
footer_layout.setContentsMargins(0, 0, 0, 0)
footer_layout.setSpacing(theme.SPACE_2)  # DESIGN: RULE-SPACE-001
footer_layout.addStretch()
footer_layout.addWidget(cancel_button)
footer_layout.addWidget(apply_button)

card.set_footer(footer)
```

### Variant 4: Elevated card

Use `surface="elevated"` for cards that must visually separate from dashboard context (e.g., floating preview, emphasized region).

```python
emphasized_card = PanelCard(surface="elevated")
# background becomes SURFACE_ELEVATED (SECONDARY = #22252f), one shade lighter
```

## States

| State | Visual treatment | Code trigger |
|---|---|---|
| **Default** | `SURFACE_CARD`, 1px `BORDER`, `RADIUS_LG` | — |
| **Interactive hover** (if clickable) | `MUTED` background overlay | `:hover` in QSS (RULE-COLOR-006) |
| **Interactive focus** (if clickable) | 2px `ACCENT` border replacing 1px `BORDER` | `:focus` in QSS (RULE-INTER-001) |
| **Loading** (content not ready) | Content host shows spinner / skeleton; card chrome unchanged | content-specific |
| **Disabled** | Reduce whole card opacity to 0.55; cursor becomes arrow | via `setEnabled(False)` |
| **Fault-bound** (card displays data about a faulted channel) | Left border 3px `STATUS_FAULT`; card otherwise normal | content-specific |

**States NOT supported:**
- "Expanded / collapsed" — a card is not a disclosure control; use a separate widget
- "Selected" — cards are not list items; if selection semantics are needed, build a tile that handles it explicitly

## Proposed implementation sketch

> **Not yet implemented.** The snippet below is a proposed sketch for the
> `PanelCard` extraction. The path `panel_card.py` does not exist today;
> the live card surface is `modal_card.py` (a specialized variant).
> Retained here as a target for future extraction per governance process.

```python
# Proposed file (NOT yet present on disk — see callout above):
# src/cryodaq/gui/shell/overlays/_design_system/  →  panel_card.py
"""Generic rounded card container with one visible surface.

Implements RULE-SURF-001 (single surface), RULE-SURF-003 (symmetric padding),
RULE-SURF-007 (transparent content host), RULE-SURF-010 (zero shadow).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget

from cryodaq.gui import theme


class PanelCard(QWidget):
    """Generic rounded card. Slot-based composition."""
    
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        surface: str = "card",
        padding: int | None = None,
    ) -> None:
        super().__init__(parent)
        
        self._surface_key = surface
        self._padding = padding if padding is not None else theme.SPACE_5
        
        # Outer: fills self, takes no margin — the "card frame" is a child
        # QFrame so we can address it by objectName in stylesheet
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        
        # DESIGN: RULE-SURF-001 — the ONE painted surface
        self._card_frame = QFrame(self)
        self._card_frame.setObjectName("panelCardFrame")
        self._apply_surface_style()
        outer.addWidget(self._card_frame)
        
        # DESIGN: RULE-SURF-003 — symmetric padding
        card_layout = QVBoxLayout(self._card_frame)
        card_layout.setContentsMargins(
            self._padding, self._padding, self._padding, self._padding
        )
        card_layout.setSpacing(theme.SPACE_4)  # between header/content/footer
        
        # DESIGN: RULE-SURF-007 — transparent header slot
        self._header_slot = QWidget(self._card_frame)
        self._header_slot.setObjectName("panelCardHeader")
        self._header_slot.setStyleSheet(
            "#panelCardHeader { background: transparent; border: none; }"
        )
        self._header_slot.setVisible(False)
        card_layout.addWidget(self._header_slot)
        
        # DESIGN: RULE-SURF-007 — transparent content host
        self._content_host = QWidget(self._card_frame)
        self._content_host.setObjectName("panelCardContentHost")
        self._content_host.setStyleSheet(
            "#panelCardContentHost { background: transparent; border: none; }"
        )
        card_layout.addWidget(self._content_host, 1)  # expanding
        
        # DESIGN: RULE-SURF-007 — transparent footer slot
        self._footer_slot = QWidget(self._card_frame)
        self._footer_slot.setObjectName("panelCardFooter")
        self._footer_slot.setStyleSheet(
            "#panelCardFooter { background: transparent; border: none; }"
        )
        self._footer_slot.setVisible(False)
        card_layout.addWidget(self._footer_slot)
        
        # Slot layouts — will hold the user-provided widget
        for slot in (self._header_slot, self._content_host, self._footer_slot):
            slot_layout = QVBoxLayout(slot)
            slot_layout.setContentsMargins(0, 0, 0, 0)
            slot_layout.setSpacing(0)
    
    def _apply_surface_style(self) -> None:
        """Apply card frame stylesheet based on current surface key."""
        bg = theme.SURFACE_CARD if self._surface_key == "card" else theme.SURFACE_ELEVATED
        # DESIGN: RULE-COLOR-001 — all values from theme
        # DESIGN: RULE-SURF-006 — RADIUS_LG on card
        self._card_frame.setStyleSheet(
            f"#panelCardFrame {{"
            f"  background: {bg};"
            f"  border: 1px solid {theme.BORDER};"
            f"  border-radius: {theme.RADIUS_LG}px;"
            f"}}"
        )
    
    def set_surface(self, surface: str) -> None:
        if surface not in ("card", "elevated"):
            raise ValueError(f"Unknown surface: {surface!r}")
        self._surface_key = surface
        self._apply_surface_style()
    
    def _install_into_slot(self, slot: QWidget, widget: QWidget | None) -> None:
        layout = slot.layout()
        # Remove any prior child
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        if widget is None:
            slot.setVisible(False)
            return
        widget.setParent(slot)
        layout.addWidget(widget)
        slot.setVisible(True)
    
    def set_header(self, widget: QWidget | None) -> None:
        self._install_into_slot(self._header_slot, widget)
    
    def set_content(self, widget: QWidget | None) -> None:
        self._install_into_slot(self._content_host, widget)
    
    def set_footer(self, widget: QWidget | None) -> None:
        self._install_into_slot(self._footer_slot, widget)
```

## Common mistakes

1. **Painting the content_host background.** Accidentally giving content_host its own background produces the "sharp rectangle inside rounded card" regression (Phase I.1, commit `d87c24b`, fixed in `cf72942`). Always explicit `background: transparent` on content host. RULE-SURF-007.

2. **Asymmetric padding to fix spacing issues.** When content "feels too close to top", the fix is NOT `(SPACE_5, SPACE_3, SPACE_5, SPACE_5)` — it's restructuring header, adjusting intra-section spacing, or reviewing content composition. Asymmetric card padding is the wrong tool. RULE-SURF-003.

3. **Nesting cards.** Creating a `PanelCard` inside another `PanelCard` violates RULE-SURF-005. If the nested region is meant to be visually distinct, use a `BentoTile` (different semantic category). If it's just layout grouping, use a transparent `QWidget`.

4. **Applying drop shadow for "depth."** Dark-mode shadows are imperceptible and expensive. Depth on dark mode comes from surface brightness delta. RULE-SURF-010.

5. **Hardcoding colors.** Any `setStyleSheet` with raw hex is a violation. All values via `theme.*`. RULE-COLOR-001.

6. **Using RADIUS_LG on child tile.** Parent card has RADIUS_LG; child tile must use RADIUS_MD or smaller per hierarchy cascade. Equal radius on parent+child breaks visual containment. RULE-SURF-006.

## Related components

- `components/modal.md` — Modal is a Card + overlay behavior (backdrop, centered, Escape)
- `components/popover.md` — Popover is a smaller Card anchored to a trigger
- `components/dialog.md` — Dialog is a Card + Q&A semantic (title + body + actions)
- `components/bento-tile.md` — Tile is a child surface inside BentoGrid; related but distinct category
- `cryodaq-primitives/experiment-card.md` — Domain-specific card showing active experiment metadata

## Changelog

- 2026-04-17: Initial version. Base primitive for all card-shape compositions. Anatomy and invariants derived from Phase I.1 ModalCard implementation lessons (commits `e25bbd9`, `d87c24b`, `cf72942`). `PanelCard` is explicitly proposed / not yet implemented — `modal_card.py` currently owns the pattern, and extraction of a generic `PanelCard` base is a future governance item. Doc body clearly flags every `PanelCard` reference as proposed.
