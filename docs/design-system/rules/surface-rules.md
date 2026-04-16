---
title: Surface Composition Rules
keywords: surface, card, background, transparent, nested, hierarchy, radius, modal, overlay, padding, header
applies_to: all container widgets
enforcement: strict
priority: critical
last_updated: 2026-04-17
---

# Surface Composition Rules

Rules governing how multiple QWidget surfaces stack inside a composition. These rules exist because Qt stylesheet cascading creates subtle visual bugs (nested rectangles, radius mismatches, padding asymmetries) that are not caught by functional tests — only by visual review.

Several rules in this file were extracted from Phase I.1 regressions (commits `e25bbd9`, `d87c24b`, fixed in `cf72942`). Do not recreate those bugs.

Enforce in code via `# DESIGN: RULE-SURF-XXX` comment marker.

**Rule index:**
- RULE-SURF-001 — Single visible surface per card
- RULE-SURF-002 — No sharp corners inside rounded card
- RULE-SURF-003 — Symmetric card padding
- RULE-SURF-004 — Header and close button on single baseline
- RULE-SURF-005 — No nested cards of same category
- RULE-SURF-006 — Radius hierarchy cascade
- RULE-SURF-007 — Content host background transparent
- RULE-SURF-008 — Max nesting depth 3 surface levels
- RULE-SURF-009 — Overlay max width constraint
- RULE-SURF-010 — Elevation via surface tokens only (no drop shadows except modal)

---

## RULE-SURF-001: Single visible surface per card

**TL;DR:** A card widget renders as exactly ONE visual surface. Child widgets inside MUST have transparent backgrounds unless they are themselves deliberate sub-components (tiles, inputs, buttons).

**Statement:** When a composition presents itself as "one card," only the outermost card widget paints background, border, and radius. All child container widgets (content hosts, header rows, layout wrappers) MUST have `background: transparent` and `border: none` explicitly set via stylesheet.

**Rationale:** Nested painted surfaces create visual hierarchy confusion. Operators interpret two stacked rectangles as two separate containers, splitting attention. A card is one cognitive unit — render it as one surface.

**Phase I.1 regression:** ModalCard's `_content_host` had implicit painted background (inherited from QWidget default), creating visible "inner sharp rectangle" nested inside "outer rounded card." Fixed in `cf72942` by adding explicit transparent stylesheet.

**Applies to:** ModalCard, PanelCard, any card-like container with child QWidgets

**Example (good):**

```python
# DESIGN: RULE-SURF-001
class ModalCard(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        # Outer card — THE single painted surface
        self._card = QFrame(self)
        self._card.setObjectName("modalCardBody")
        self._card.setStyleSheet(
            f"#modalCardBody {{"
            f"  background: {theme.SURFACE_ELEVATED};"
            f"  border: 1px solid {theme.BORDER};"
            f"  border-radius: {theme.RADIUS_LG}px;"
            f"}}"
        )

        # Content host — explicit transparent
        self._content_host = QWidget(self._card)
        self._content_host.setObjectName("modalCardContentHost")
        self._content_host.setStyleSheet(
            "#modalCardContentHost { background: transparent; border: none; }"
        )

        # Header row — explicit transparent
        self._header_row = QWidget(self._card)
        self._header_row.setObjectName("modalCardHeader")
        self._header_row.setStyleSheet(
            "#modalCardHeader { background: transparent; border: none; }"
        )
```

**Example (bad):**

```python
# Both card AND content_host have painted backgrounds → nested rectangles
self._card.setStyleSheet(f"background: {theme.SURFACE_ELEVATED}; ...")
self._content_host.setStyleSheet(f"background: {theme.SURFACE_PANEL}; ...")
# Result: outer rounded card + inner sharp rectangle = Phase I.1 bug

# Equally bad — content_host has no stylesheet but QWidget default paints
self._content_host = QWidget(self._card)
# ↑ without explicit "background: transparent" Qt may paint default bg
# depending on WA_StyledBackground attribute state
```

**Detection:**

```bash
# Content hosts and header rows should have explicit transparent declarations
rg -n "setObjectName\(\"modalCard" src/cryodaq/gui/shell/overlays/_design_system/
# Then check each named object has "background: transparent" in its stylesheet
rg -n "background: transparent|background:transparent" src/cryodaq/gui/shell/overlays/_design_system/
```

**Related rules:** RULE-SURF-002, RULE-SURF-007, RULE-COLOR-001

---

## RULE-SURF-002: No sharp corners inside rounded card

**TL;DR:** If parent card has `border-radius > 0`, no visible child surface may have `border-radius: 0`.

**Statement:** When a container has border-radius, all visible children that are themselves painted surfaces (have their own background) MUST have border-radius > 0 as well. Combining sharp-cornered children with rounded parents breaks the convex-hull visual consistency.

**Rationale:** Mixing sharp and rounded corners in one composition signals lack of design intention. Radius is a hierarchy property (see RULE-SURF-006): parent ≥ child > 0. Zero inside positive is broken hierarchy.

**Phase I.1 regression:** Initial ModalCard with `RADIUS_LG` outer contained content_host with `border-radius: 0`, rendered as sharp dark rectangle inside rounded card.

**Applies to:** any child container with own background inside a rounded parent

**Example (good):**

```python
# DESIGN: RULE-SURF-002
# Card: RADIUS_LG (8px)
self._card.setStyleSheet(f"border-radius: {theme.RADIUS_LG}px;")

# Tile inside card: RADIUS_MD (6px) — smaller than parent
tile.setStyleSheet(f"border-radius: {theme.RADIUS_MD}px;")

# Input inside tile: RADIUS_SM (4px) — smaller than tile
input_field.setStyleSheet(f"border-radius: {theme.RADIUS_SM}px;")
```

**Example (bad):**

```python
# Card rounded, inner surface sharp → visual break
self._card.setStyleSheet(f"border-radius: {theme.RADIUS_LG}px;")
self._inner_frame.setStyleSheet("border-radius: 0px;")  # WRONG
```

**Exception:** Transparent content hosts and header row wrappers have no visible surface, therefore no radius concern. This rule applies only to children that paint background.

**Related rules:** RULE-SURF-001 (single surface), RULE-SURF-006 (radius cascade)

---

## RULE-SURF-003: Symmetric card padding

**TL;DR:** Card internal padding equal on all 4 sides. Default `theme.SPACE_5` (24px). Asymmetry requires documented exception comment.

**Statement:** Card `card_layout.setContentsMargins(left, top, right, bottom)` MUST satisfy `left == right` and `top == bottom == left` unless an inline `# DESIGN: RULE-SURF-003 exception` comment documents the justification.

**Rationale:** Asymmetric padding (e.g., less top than sides) is almost always a workaround for a different problem — usually "header row too close to content" or "content feels too far from bottom." The right fix is to address the root cause (restructure header, add intra-section spacing), not to skew card padding.

**Phase I.1 regression:** Commit `d87c24b` introduced `(SPACE_5, SPACE_3, SPACE_5, SPACE_5)` — reducing top to 12px — as a quick fix for "too much empty space above breadcrumb." Actually the problem was chrome row structure. Fixed in `cf72942` by restructuring header + reverting to symmetric margins.

**Applies to:** `setContentsMargins()` calls on card-level layouts, layout managers wrapping card content

**Example (good):**

```python
# DESIGN: RULE-SURF-003
card_layout = QVBoxLayout(self._card)
card_layout.setContentsMargins(
    theme.SPACE_5, theme.SPACE_5, theme.SPACE_5, theme.SPACE_5  # all four equal
)
card_layout.setSpacing(theme.SPACE_4)  # between sections, smaller than outer padding
```

**Example (bad):**

```python
# Asymmetric — top shorter than sides — looks cut off
card_layout.setContentsMargins(
    theme.SPACE_5, theme.SPACE_3, theme.SPACE_5, theme.SPACE_5  # WRONG
)
```

**Example (documented exception):**

```python
# DESIGN: RULE-SURF-003 exception
# Footer needs extra bottom padding for primary CTA breathing room.
# Standard 24/24/24/24 makes the emergency stop button feel cramped.
card_layout.setContentsMargins(
    theme.SPACE_5, theme.SPACE_5, theme.SPACE_5, theme.SPACE_6  # bottom deeper
)
```

Exceptions require:
1. `# DESIGN: RULE-SURF-003 exception` marker
2. Comment explaining why asymmetry is necessary
3. What the "natural symmetric" solution would be (for review)

**Related rules:** RULE-SPACE-004 (hierarchy: outer ≥ inner), RULE-SURF-004 (header restructuring)

---

## RULE-SURF-004: Header and close button on single baseline

**TL;DR:** When a card has both a header element (breadcrumb, title) AND a close button, they MUST share one horizontal row at the same vertical baseline. Two stacked rows is forbidden. Absolute-positioned close button is forbidden.

**Statement:** Card header structure MUST be a single `QHBoxLayout` containing: `[header_slot (expanding) | close_button (fixed size, AlignVCenter)]`. Breadcrumb, title, or any header content goes in the expanding slot. Close button sits on the right, vertically centered with the slot.

**Do NOT:**
- Place close button in its own row above breadcrumb
- Use `widget.move(x, y)` for absolute positioning (fragile on resize)
- Use `QGraphicsItem` or overlay widget tricks to float close button

**Rationale:** Operators scan top of card left-to-right for context ("what is this?") and top-right for dismiss ("how do I exit?"). Those pieces of information belong on one visual line. Stacking wastes vertical space and splits attention. Absolute positioning creates fragility: when card resizes, close button position desyncs until manual reposition in repaint cycle.

**Phase I.1 regressions:**
- Commit `e25bbd9` placed close button in own chrome row above breadcrumb — wasted ~40px vertical space, created two stacked bands.
- Commit `d87c24b` attempted fix via absolute positioning `self._close_button.move(...)` — broke geometry on resize, button disappeared when card stretched.
- Fixed in `cf72942` via single HBox header pattern.

**Applies to:** ModalCard, PanelCard, any card with close affordance. Also applies to drawers and multi-step dialogs.

**Example (good):**

```python
# DESIGN: RULE-SURF-004
# Single header row — expanding slot + close button on one baseline
self._header_row = QWidget(self._card)
self._header_row.setObjectName("modalCardHeader")
self._header_row.setFixedHeight(32)  # matches close button height
self._header_row.setStyleSheet(
    "#modalCardHeader { background: transparent; border: none; }"
)

header_layout = QHBoxLayout(self._header_row)
header_layout.setContentsMargins(0, 0, 0, 0)
header_layout.setSpacing(theme.SPACE_3)

# Left slot: breadcrumb, title, or other header content
self._header_slot = QWidget(self._header_row)
self._header_slot.setStyleSheet("background: transparent;")
header_layout.addWidget(self._header_slot, 1)  # expanding

# Right: close button, vertically centered
self._close_button = QPushButton("\u2715", self._header_row)
self._close_button.setFixedSize(32, 32)
header_layout.addWidget(
    self._close_button, 0, Qt.AlignmentFlag.AlignVCenter
)

card_layout.addWidget(self._header_row)
```

**Example (bad — two rows):**

```python
# Two stacked rows — close alone in chrome row above breadcrumb
chrome_row = QHBoxLayout()
chrome_row.addStretch()
chrome_row.addWidget(self._close_button)
card_layout.addLayout(chrome_row)  # row 1: close only — WRONG

breadcrumb_row = QHBoxLayout()
breadcrumb_row.addWidget(self._breadcrumb)
card_layout.addLayout(breadcrumb_row)  # row 2: breadcrumb
```

**Example (bad — absolute positioning):**

```python
# Close button absolute-positioned — fragile on resize
self._close_button = QPushButton("\u2715", self._card)
self._close_button.setFixedSize(32, 32)

def _reposition_card(self):
    # Called on every resize — error-prone, desyncs easily
    self._close_button.move(
        self._card.width() - 32 - theme.SPACE_3,
        theme.SPACE_3,
    )
    self._close_button.raise_()  # hopes parent-child stacking works
```

**Related rules:** RULE-SURF-003 (symmetric padding — no fix via skew), RULE-SURF-001 (transparent header row)

---

## RULE-SURF-005: No nested cards of same category

**TL;DR:** ModalCard cannot contain another ModalCard. PanelCard cannot contain PanelCard. Sub-components inside a card must be a different semantic category (Tile, SensorCell, Chart, etc.).

**Statement:** Composition hierarchy is semantic. Categories:
- **Card** — top-level container with own surface (ModalCard, PanelCard)
- **Tile** — mid-level subdivision inside card (BentoTile, ExecutiveKpiTile)
- **Primitive** — lowest-level display element (SensorCell, StatusBadge, Button)

A card contains tiles (or primitives directly). A tile contains primitives. Nesting same categories is forbidden.

**Rationale:** Same-category nesting implies hierarchy where none exists. "Card inside card" creates visual recursion — operators cannot determine which is "the container" and which is "the content." Using distinct semantic categories communicates structure.

**Applies to:** composition of card primitives, overlay layouts, dashboard tiles

**Example (good):**

```python
# DESIGN: RULE-SURF-005
# Modal → Grid → Tile — three distinct semantic categories
modal = ModalCard()
grid = BentoGrid()
tile = ExecutiveKpiTile(label="Давление", value="1.23e-06 mbar")
grid.add_tile(tile, row=0, col=0, col_span=4)
modal.set_content(grid)
```

**Example (bad):**

```python
# Modal contains Modal — semantic nesting violation
outer_modal = ModalCard()
inner_modal = ModalCard()  # WRONG — no "nested modal" concept
outer_modal.set_content(inner_modal)
```

**Exception (valid):** Transient popover stacked above modal (e.g., confirmation popover over dialog) — the popover is a DIFFERENT category (popover, not modal). It sits at higher z-index and is dismissed independently. Z-stacking is not nesting.

```python
# Valid: confirmation popover above modal
modal.show()
confirm_popover = Popover(parent=modal, anchor=modal._card)
confirm_popover.show()  # appears over modal, different category
```

**Related rules:** RULE-SURF-008 (max nesting depth), `components/modal.md` (stacking rules)

---

## RULE-SURF-006: Radius hierarchy cascade

**TL;DR:** Parent radius ≥ child radius. Card (RADIUS_LG=8) → Tile (RADIUS_MD=6) → Input (RADIUS_SM=4). Never equal or inverted.

**Statement:** In nested surface compositions, each nesting level must have strictly smaller radius than its parent, or be transparent (no own radius). Valid cascade:

```
Card        RADIUS_LG (8px)
  ├─ Tile   RADIUS_MD (6px)
  │   └─ Input  RADIUS_SM (4px)
  └─ Badge  RADIUS_SM (4px)
```

Invalid:
- Child radius == parent radius (no visual hierarchy)
- Child radius > parent radius (inverted, broken convex hull)
- Child radius == 0 while parent > 0 (violates RULE-SURF-002)

**Rationale:** Radius is a hierarchy signal. Smaller-inside-larger communicates containment. Same-inside-same or larger-inside-smaller breaks the spatial metaphor.

**Applies to:** any nested surface composition with child widgets having own backgrounds

**Example (good):**

```python
# DESIGN: RULE-SURF-006
# Modal card outer
card.setStyleSheet(f"border-radius: {theme.RADIUS_LG}px;")  # 8

# Tile inside modal
tile.setStyleSheet(f"border-radius: {theme.RADIUS_MD}px;")  # 6

# Input field inside tile
input_field.setStyleSheet(f"border-radius: {theme.RADIUS_SM}px;")  # 4
```

**Example (bad — equal):**

```python
# Tile same radius as card — no hierarchy
card.setStyleSheet(f"border-radius: {theme.RADIUS_LG}px;")  # 8
tile.setStyleSheet(f"border-radius: {theme.RADIUS_LG}px;")  # 8 — WRONG
```

**Example (bad — inverted):**

```python
# Tile larger radius than card — breaks convex hull
card.setStyleSheet(f"border-radius: {theme.RADIUS_MD}px;")  # 6
tile.setStyleSheet(f"border-radius: {theme.RADIUS_LG}px;")  # 8 — WRONG
```

**Related rules:** RULE-SURF-002 (no sharp inside rounded), `tokens/radius.md`

---

## RULE-SURF-007: Content host background transparent

**TL;DR:** Widgets that exist purely to host other widgets (QWidget containers used as layout wrappers) MUST have `background: transparent` explicitly set.

**Statement:** When a QWidget serves as a layout container (holds QVBoxLayout/QHBoxLayout/QGridLayout, contains child widgets, does not itself display content) — it MUST have explicit `background: transparent` in its stylesheet. Even if parent card paints the surface, Qt's default `QWidget` paint behavior may draw platform-default background.

This is a specific instance of RULE-SURF-001 focused on the common "layout wrapper QWidget" pattern.

**Rationale:** Qt's default for custom QWidget is often implicit platform-default paint. On some systems (depending on `WA_StyledBackground` attribute state, QStyle, widget type), a wrapper that "should" be invisible paints its own background, creating surprise nested surfaces. Explicit `transparent` guarantees no paint.

**Applies to:** content_host, header_slot, section_wrapper, any container QWidget whose purpose is grouping, not display

**Example (good):**

```python
# DESIGN: RULE-SURF-007
# Layout wrapper widget — explicit transparent
self._content_host = QWidget(self._card)
self._content_host.setObjectName("contentHost")
self._content_host.setStyleSheet(
    "#contentHost { background: transparent; border: none; }"
)

content_layout = QVBoxLayout(self._content_host)
content_layout.setContentsMargins(0, 0, 0, 0)
```

**Example (bad):**

```python
# No stylesheet — Qt may paint default
self._content_host = QWidget(self._card)
# Result: platform-dependent. On Linux/Qt default may paint ~#f0f0f0 (light gray)
# even on dark theme. Visible as unexpected background patch.
```

**Alternative fix (valid):** `setAttribute(Qt.WA_NoSystemBackground, True)` + `setAttribute(Qt.WA_TranslucentBackground, True)` — but stylesheet `background: transparent` is more explicit and readable.

**Related rules:** RULE-SURF-001 (single surface principle), RULE-SURF-002 (no sharp corners)

---

## RULE-SURF-008: Max nesting depth 3 surface levels

**TL;DR:** Visual surface hierarchy has 3 levels max: BACKGROUND → CARD → SECONDARY. Do not create fourth. If you need more depth, use popover or separate overlay.

**Statement:** CryoDAQ theme defines exactly 3 distinct surface brightness levels (see `tokens/colors.md` Surface hierarchy):
1. `BACKGROUND #0d0e12` — viewport base
2. `CARD #181a22` — dashboard tiles, panels (SURFACE_PANEL/CARD/SUNKEN all alias to this)
3. `SECONDARY #22252f` — modal cards, popovers (SURFACE_ELEVATED aliases to this)

Nesting more than 3 levels of painted surfaces creates either:
- Invisible hierarchy (4th level indistinguishable from 3rd on dark mode)
- Cognitive overload (operator cannot parse 4+ nesting levels)

**Rationale:** Dark mode surface delta is intentionally subtle (~6% relative luminance per step). Three levels are the maximum the eye can reliably distinguish without explicit separators. Beyond that, either use popover (separate Z-layer) or flatten the structure.

**Applies to:** overlay layouts, modal content compositions, deeply nested dashboards

**Example (good):**

```text
# DESIGN: RULE-SURF-008
# 3 levels:
# 1. Viewport BACKGROUND
# 2. Modal card SURFACE_ELEVATED
# 3. Tile SURFACE_CARD (nested inside modal)
# Input inside tile is transparent — not a 4th surface level

viewport  # Level 1: BACKGROUND
modal     # Level 2: SURFACE_ELEVATED
  tile    # Level 3: SURFACE_CARD (one shade below SURFACE_ELEVATED)
    input # Level 3.5? NO — input is transparent overlay on tile
```

**Example (bad):**

```text
# 4+ nesting levels — visually incomprehensible
viewport    # BACKGROUND
  modal     # SURFACE_ELEVATED
    tile    # SURFACE_CARD
      subpanel  # WHAT surface color? We only have 3 — any choice breaks hierarchy
        input_group # 5th level — definitely wrong
```

**Fix pattern:** Flatten via grouping, or use popover:

```text
# Option A: Flatten — subpanel becomes a section within tile, transparent
tile
  ├─ section_header (transparent)
  ├─ section_content (transparent — contains inputs)

# Option B: Move 4th level to popover — different Z-layer, not nesting
tile
  └─ settings_button → triggers popover (separate Z-layer)
     popover contains the subpanel content
```

**Related rules:** RULE-SURF-005 (no nested same-category), RULE-SURF-007 (transparent hosts)

---

## RULE-SURF-009: Overlay max width constraint

**TL;DR:** Modal overlays have max width `theme.OVERLAY_MAX_WIDTH = 1400`. Overlays must leave visible backdrop margin on all sides, never extend edge-to-edge.

**Statement:** ModalCard, drill-down overlays, and full-screen panels MUST respect:
- Max width: `min(viewport_width * 0.9, theme.OVERLAY_MAX_WIDTH)` (proposed token, see `tokens/breakpoints.md`)
- Max height: `min(viewport_height * 0.9, theme.OVERLAY_MAX_HEIGHT)` (proposed)
- Visible backdrop margin: at least `theme.SPACE_5` (24px) on all sides

Extending overlay edge-to-edge eliminates backdrop visibility and breaks the "floating modal" visual metaphor — user sees a fullscreen replacement, not an overlay.

**Rationale:** Backdrop dim (`SURFACE_OVERLAY_RGBA rgba(13,14,18,0.6)`) is the signal that "content below is temporarily inaccessible." If overlay touches edges, backdrop invisible, signal lost. At 1920×1080 viewport, clamping to 1400 gives ~260px side margins = clearly a floating modal.

**Phase I.1 regression:** Commit `d87c24b` changed max_width to 1280 without clamping to viewport max_width; at resize to narrower viewports, card stretched edge-to-edge. Fixed in `cf72942` by restoring viewport-bounded clamping.

**Applies to:** ModalCard, full-screen overlays, drill-down panels

**Example (good):**

```python
# DESIGN: RULE-SURF-009
def _reposition_card(self) -> None:
    if self.width() <= 0 or self.height() <= 0:
        return

    outer_margin = theme.SPACE_5  # minimum margin on each side
    available_width = max(0, self.width() - 2 * outer_margin)
    available_height = max(0, self.height() - 2 * outer_margin)

    # Width clamped by both available and max_width
    card_width = min(self._max_width, available_width)
    card_height = min(available_height, self._max_height)

    x = (self.width() - card_width) // 2
    y = (self.height() - card_height) // 2
    self._card.setGeometry(QRect(x, y, card_width, card_height))
```

**Example (bad):**

```python
# No clamping — card extends to viewport edges on narrow screens
card_width = self._max_width  # hardcoded 1280 regardless of viewport
# Result: at 1200-wide viewport, card overflows by 80px, clipped or edge-to-edge
```

**Related rules:** `tokens/breakpoints.md`, `components/modal.md`

---

## RULE-SURF-010: Elevation via surface tokens only

**TL;DR:** Depth perception on dark mode comes from surface brightness delta (BACKGROUND → CARD → SECONDARY). NO `QGraphicsDropShadowEffect` anywhere except the single permitted modal shadow exception.

**Statement:** CryoDAQ has a **zero-shadow policy** for dark mode. Cards, tiles, panels, and all UI chrome do NOT use drop shadows. Elevation is communicated purely through:
1. Surface token selection (higher = lighter: BACKGROUND → CARD → SECONDARY)
2. Border color (`BORDER`) for visual separation
3. Position (modal is centered with backdrop dim = depth signal)

**Single exception:** Modal cards MAY apply one subtle drop shadow (see `tokens/elevation.md` for exact parameters). Required because backdrop dim + surface delta alone provide insufficient depth perception for modals over dashboard.

**Rationale:**
1. Dark-mode shadows are ineffective (`rgba(0,0,0,0.3)` on `#0d0e12` is imperceptibly darker)
2. Shadows are CPU-expensive (Qt blur is software, not GPU) — 24-tile dashboard updating at 2Hz with shadows = performance concern
3. Shadows are anti-pattern for industrial aesthetic (Material Design's "paper lifts to finger" metaphor is wrong here)

**Applies to:** all dashboard tiles, sidebar panels, buttons, inputs, cards — everything except modal overlays

**Example (good):**

```python
# DESIGN: RULE-SURF-010
# Dashboard tile — elevation through surface + border, no shadow
tile.setStyleSheet(
    f"background: {theme.SURFACE_CARD};"       # elevation via color
    f"border: 1px solid {theme.BORDER};"       # separation via border
    f"border-radius: {theme.RADIUS_MD}px;"
)
# NO QGraphicsDropShadowEffect applied
```

**Example (good — modal exception):**

```python
# DESIGN: RULE-SURF-010 exception
# Modal MAY use single shadow for depth over backdrop
self._card.setStyleSheet(
    f"background: {theme.SURFACE_ELEVATED};"
    f"border: 1px solid {theme.BORDER};"
    f"border-radius: {theme.RADIUS_LG}px;"
)

shadow = QGraphicsDropShadowEffect()
shadow.setBlurRadius(24)
shadow.setOffset(0, 8)
shadow.setColor(QColor(0, 0, 0, int(255 * 0.4)))
self._card.setGraphicsEffect(shadow)
# This shadow is the ONLY permitted one in CryoDAQ
```

**Example (bad):**

```python
# Dashboard tile with shadow — zero-shadow policy violation
shadow = QGraphicsDropShadowEffect()
shadow.setBlurRadius(12)
shadow.setOffset(0, 4)
tile.setGraphicsEffect(shadow)  # WRONG — no tile shadows in CryoDAQ
```

**Detection:**

```bash
# Find all QGraphicsDropShadowEffect usage
rg -n "QGraphicsDropShadowEffect" src/cryodaq/gui/
# Should match only modal-card file (whitelisted) — any other match is violation
```

**Related rules:** `tokens/elevation.md`, `tokens/colors.md` Surface hierarchy

---

## Changelog

- 2026-04-17: Initial version. 10 rules: 6 extracted from Phase I.1 regressions (commits `e25bbd9`, `d87c24b`, `cf72942`), 4 newly formalized (SURF-007 transparent wrapper explicit, SURF-008 max nesting depth, SURF-009 overlay max width, SURF-010 zero-shadow policy).
