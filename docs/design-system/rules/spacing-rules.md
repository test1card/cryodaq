---
title: Spacing Rules
keywords: spacing, gap, padding, margin, symmetry, hierarchy, icon, alignment, row
applies_to: all layouts and containers
enforcement: strict
priority: high
last_updated: 2026-04-17
---

# Spacing Rules

Enforcement rules for spacing token usage from `tokens/spacing.md`. Spacing drift accumulates silently across widgets and is the primary cause of "doesn't feel right" complaints.

Enforce in code via `# DESIGN: RULE-SPACE-XXX` comment marker.

**Rule index:**
- RULE-SPACE-001 — Inline row gaps (4-8px for icon+text, 12-16px for controls)
- RULE-SPACE-002 — Dashboard grid outer margin
- RULE-SPACE-003 — Grid gap uses `GRID_GAP` semantic alias
- RULE-SPACE-004 — Outer margin ≥ inner gap (hierarchy rule)
- RULE-SPACE-005 — Adjacent clickable minimum 4px gap
- RULE-SPACE-006 — Chrome dimensions coupled (HEADER_HEIGHT = TOOL_RAIL_WIDTH)
- RULE-SPACE-007 — Row height default `ROW_HEIGHT = 36`
- RULE-SPACE-008 — Icon vertical alignment with text (AlignVCenter)

---

## RULE-SPACE-001: Inline row gaps

**TL;DR:** Icon + text gap = `SPACE_1` (4px). Adjacent controls (label + field, button + button) = `SPACE_2` (8px). Text + inline value = `SPACE_3` (12px) for breathing room.

**Statement:** When composing a horizontal row of elements, the `setSpacing()` value on the layout depends on element relationship:

| Context | Token | Value | Example |
|---|---|---|---|
| Icon tight to text (icon represents text) | `SPACE_1` | 4px | `[⚠] Внимание` |
| Adjacent controls (form field + button) | `SPACE_2` | 8px | `[label] [input]` |
| Label + value in data row | `SPACE_2` | 8px | `Т мин:  3.90 K` |
| Button group (related actions) | `SPACE_2` | 8px | `[Cancel] [Apply]` |
| Section items with breathing | `SPACE_3` | 12px | List items with descriptions |

**Rationale:** Tight gaps signal "these elements are one unit" (icon+text, label+value). Wider gaps signal "these are peers" (separate actions). Correct gap choice communicates structure without explicit dividers.

**Applies to:** `QHBoxLayout.setSpacing()`, `QGridLayout.setSpacing()` for row-like compositions

**Example (good):**

```python
# DESIGN: RULE-SPACE-001
# Icon + text — tight
warning_row = QHBoxLayout()
warning_row.setSpacing(theme.SPACE_1)  # 4px — icon belongs with text
warning_row.setContentsMargins(0, 0, 0, 0)
warning_row.addWidget(warning_icon)
warning_row.addWidget(warning_label)

# Label + value in data display — moderate
data_row = QHBoxLayout()
data_row.setSpacing(theme.SPACE_2)  # 8px
data_row.addWidget(QLabel("Т мин"))
data_row.addWidget(value_display)

# Button group — moderate
button_row = QHBoxLayout()
button_row.setSpacing(theme.SPACE_2)  # 8px between related buttons
button_row.addWidget(cancel_button)
button_row.addWidget(apply_button)
```

**Example (bad):**

```python
# Icon + text with large gap — looks disconnected
warning_row.setSpacing(theme.SPACE_4)  # 16px — WRONG, icon and text feel unrelated

# Adjacent buttons with tight gap — looks like single wide button
button_row.setSpacing(theme.SPACE_0)  # 0px — WRONG, merges visually
```

**Related rules:** RULE-SPACE-008 (icon vertical alignment), `tokens/spacing.md` semantic aliases

---

## RULE-SPACE-002: Dashboard grid outer margin

**TL;DR:** Dashboard-level layout (below TopWatchBar, right of ToolRail) uses `theme.SPACE_5` (24px) outer margin. Between major dashboard zones use `theme.SPACE_6` (32px).

**Statement:** Top-level dashboard layouts MUST use:
- `setContentsMargins(SPACE_5, SPACE_5, SPACE_5, SPACE_5)` — 24px breathing room from TopWatchBar / ToolRail / viewport edges
- `setSpacing(SPACE_6)` — 32px between major zones (sensor grid vs chart area vs sidebar)

Within individual zones (inside a grid, inside a card), tighter spacing applies per other rules.

**Rationale:** The 24px outer margin visually separates "app chrome" (chromeis persistent) from "dashboard content" (changes per context). The 32px inter-zone gap creates distinct perceptual groups — operators see the dashboard as 2-3 major zones, not an undifferentiated mass.

**Applies to:** dashboard container layout, full-viewport layouts

**Example (good):**

```python
# DESIGN: RULE-SPACE-002
# Dashboard root layout
dashboard_layout = QHBoxLayout(dashboard_root)
dashboard_layout.setContentsMargins(
    theme.SPACE_5, theme.SPACE_5, theme.SPACE_5, theme.SPACE_5  # 24px all sides
)
dashboard_layout.setSpacing(theme.SPACE_6)  # 32px between zones

# Zone 1: sensor grid area
sensor_zone = QWidget()
dashboard_layout.addWidget(sensor_zone, 2)  # 2/3 width

# Zone 2: chart area
chart_zone = QWidget()
dashboard_layout.addWidget(chart_zone, 1)  # 1/3 width
```

**Example (bad):**

```python
# No outer margin — content touches TopWatchBar / ToolRail
dashboard_layout.setContentsMargins(0, 0, 0, 0)  # WRONG

# Too-tight inter-zone — zones feel merged
dashboard_layout.setSpacing(theme.SPACE_2)  # 8px — WRONG, breaks zone perception
```

**Related rules:** RULE-SPACE-003 (grid gap within zones), RULE-SPACE-004 (hierarchy)

---

## RULE-SPACE-003: Grid gap uses `GRID_GAP` semantic alias

**TL;DR:** BentoGrid / sensor grid / tile collections use `theme.GRID_GAP` (8px) — the semantic alias. Not `theme.SPACE_2` (same value, wrong intent).

**Statement:** When laying out grids of tiles, sensor cells, or repeating items, `setHorizontalSpacing()` / `setVerticalSpacing()` values MUST use `theme.GRID_GAP` token (not raw `SPACE_2`). Both resolve to 8px — the distinction is semantic clarity.

Same for `CARD_PADDING` vs `SPACE_3` (both 12px): inside card use `CARD_PADDING`, not `SPACE_3`.

**Rationale:** Semantic aliases communicate intent. `GRID_GAP` says "this is grid-specific spacing; changes to grid rhythm should update this alias." `SPACE_2` is primitive — if global spacing scale changes, `SPACE_2` meaning shifts, potentially breaking grid. Aliases insulate widgets from scale redefinition.

**Applies to:** grid-like layouts, tile collections, BentoGrid

**Example (good):**

```python
# DESIGN: RULE-SPACE-003
grid = QGridLayout()
grid.setHorizontalSpacing(theme.GRID_GAP)  # semantic
grid.setVerticalSpacing(theme.GRID_GAP)    # semantic
grid.setContentsMargins(0, 0, 0, 0)

# Inside each tile: CARD_PADDING
tile_layout = QVBoxLayout(tile)
tile_layout.setContentsMargins(
    theme.CARD_PADDING, theme.CARD_PADDING,
    theme.CARD_PADDING, theme.CARD_PADDING
)
```

**Example (bad):**

```python
# Raw primitive for grid gap — semantic lost
grid.setHorizontalSpacing(theme.SPACE_2)  # functionally correct but semantic unclear
grid.setVerticalSpacing(theme.SPACE_2)

# Raw primitive for card padding
tile_layout.setContentsMargins(
    theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3  # use CARD_PADDING
)
```

**Related rules:** `tokens/spacing.md` semantic aliases

---

## RULE-SPACE-004: Outer margin ≥ inner gap

**TL;DR:** Inside a card, the card's own margin (edge-to-content) MUST be ≥ the spacing between content items inside. Outer 24 + inner 16 = correct. Outer 16 + inner 32 = broken hierarchy.

**Statement:** Spacing hierarchy rule:

```
card.contentsMargins (outer, edge-to-first-item) ≥
  layout.spacing (between first-level items) ≥
    row.spacing (between inline elements inside item)
```

Violating this makes content feel "pushed apart" from the card border — items inside seem disconnected. Maintaining it creates correct containment perception.

**Rationale:** If items inside a card are spaced further apart than the card's own border padding, they visually escape the card's containment — they don't feel "held" by the card. This is a specific Gestalt proximity principle: elements closer to each other group more strongly than elements closer to container edge.

**Applies to:** any nested spacing configuration (card → section → row → inline)

**Example (good):**

```python
# DESIGN: RULE-SPACE-004
# Card: outer 24
card_layout.setContentsMargins(
    theme.SPACE_5, theme.SPACE_5, theme.SPACE_5, theme.SPACE_5  # 24
)
# Card: between sections 16 (< 24) ✓
card_layout.setSpacing(theme.SPACE_4)  # 16

# Section: between rows 12 (< 16) ✓
section_layout.setSpacing(theme.SPACE_3)  # 12

# Row: between inline elements 8 (< 12) ✓
row.setSpacing(theme.SPACE_2)  # 8
```

**Example (bad):**

```python
# Outer 16, inner 24 — inverted hierarchy
card_layout.setContentsMargins(
    theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_4  # 16
)
card_layout.setSpacing(theme.SPACE_5)  # 24 — WRONG, larger than outer
# Result: content items feel more distant from each other than from card edge,
# breaking containment perception
```

**Detection:**

```bash
# Pattern: setContentsMargins followed by setSpacing with larger value
# Not trivially grep-able — requires reading. Review during PR.
```

**Related rules:** RULE-SURF-003 (symmetric padding), `tokens/spacing.md` hierarchy rule

---

## RULE-SPACE-005: Adjacent clickable minimum 4px gap

**TL;DR:** Two adjacent interactive elements (buttons, clickable rows, tool rail icons) MUST have at least `SPACE_1` (4px) gap between their clickable regions. Prevents mis-click.

**Statement:** When placing multiple interactive elements in close proximity (side-by-side buttons, tool rail icon buttons, close button next to other control), maintain minimum 4px separation between hit-regions. This applies even if the elements appear visually unified (e.g., segmented button group).

Tighter than 4px (touching or 0px gap) risks mis-click when cursor hovers at boundary pixel. 4px provides a small "miss zone" where neither element claims the click.

**Rationale:** CryoDAQ is desktop-only with mouse input. Mouse precision on typical lab PC is ~1 pixel, but operators under stress may be less precise. 4px buffer prevents expensive mis-clicks (wrong button pressed during emergency).

**Applies to:** button groups, tool rail icon collections, close+action button pairs, any adjacent clickable element

**Example (good):**

```python
# DESIGN: RULE-SPACE-005
# Button group with clickable gap
button_group = QHBoxLayout()
button_group.setSpacing(theme.SPACE_2)  # 8px — safely > minimum 4
button_group.addWidget(cancel_button)
button_group.addWidget(apply_button)

# Tool rail icons — 4px min
toolrail_layout = QVBoxLayout()
toolrail_layout.setSpacing(theme.SPACE_1)  # 4px — minimum, acceptable
toolrail_layout.addWidget(dashboard_icon)
toolrail_layout.addWidget(experiment_icon)
toolrail_layout.addWidget(analytics_icon)
```

**Example (bad):**

```python
# Touching buttons — no hit-region separation
button_group.setSpacing(0)  # WRONG — mis-click risk
# Or via individual geometry:
cancel_button.setGeometry(QRect(0, 0, 100, 36))
apply_button.setGeometry(QRect(100, 0, 100, 36))  # touches cancel at x=100
```

**Exception:** Visually-unified segmented button groups (e.g., toggle button row where "Day / Week / Month") MAY render with zero visible gap if the **hit-regions** remain distinguishable via Qt's widget boundaries. This is tool-specific; consult `components/button.md` for segmented pattern.

**Related rules:** RULE-INTER-008 (interactive affordance), `components/button.md`

---

## RULE-SPACE-006: Chrome dimensions coupled

**TL;DR:** `HEADER_HEIGHT` and `TOOL_RAIL_WIDTH` are both 56px. They are coupled — changing one without the other breaks the corner-square alignment.

**Statement:** The top-left corner of the CryoDAQ app shell is a 56×56 square where TopWatchBar meets ToolRail. Both dimensions are defined in `tokens/layout.md` as `HEADER_HEIGHT = 56` and `TOOL_RAIL_WIDTH = 56`. Any modification to one REQUIRES simultaneous modification to the other.

```
+---------+-----------------------+
|  56×56  |    TopWatchBar (56)   |
| corner  |                       |
+---------+-----------------------+
|         |                       |
| ToolRail|    Content area       |
|  (56)   |                       |
|         |                       |
```

If HEADER_HEIGHT changes to 48 but TOOL_RAIL_WIDTH stays 56, the corner becomes 56×48 rectangle — alignment breaks and visual rhythm is disrupted. Same for the reverse.

**Rationale:** Coupled constants exist in the codebase but are not enforced at type level. Only explicit rule + review discipline catches violations. Documented here so future developers know the coupling.

**Applies to:** changes to `theme.HEADER_HEIGHT`, `theme.TOOL_RAIL_WIDTH`

**Example (good):**

```python
# DESIGN: RULE-SPACE-006
# Coupled change — both updated together
# In theme.py:
HEADER_HEIGHT: Final[int] = 64  # was 56
TOOL_RAIL_WIDTH: Final[int] = 64  # was 56 — UPDATED IN SAME COMMIT
# Corner square maintained at new 64×64 dimension
```

**Example (bad):**

```python
# Decoupled change — breaks corner
# In theme.py:
HEADER_HEIGHT: Final[int] = 48  # reduced
TOOL_RAIL_WIDTH: Final[int] = 56  # unchanged — WRONG
# Corner becomes 56×48 rectangle; visual alignment broken
```

**Test (proposed):**

```python
def test_header_toolrail_coupled():
    """HEADER_HEIGHT must equal TOOL_RAIL_WIDTH (corner square)."""
    from cryodaq.gui import theme
    assert theme.HEADER_HEIGHT == theme.TOOL_RAIL_WIDTH, (
        f"Chrome corner not square: "
        f"HEADER_HEIGHT={theme.HEADER_HEIGHT}, "
        f"TOOL_RAIL_WIDTH={theme.TOOL_RAIL_WIDTH}"
    )
```

**Related rules:** `tokens/layout.md` coupled constants, RULE-SURF-009 (overlay geometry)

---

## RULE-SPACE-007: Row height default

**TL;DR:** Default height for most interactive controls (buttons, inputs, list rows, table rows) is `theme.ROW_HEIGHT = 36`. Deviations require reason.

**Statement:** Interactive controls MUST default to 36px height (`theme.ROW_HEIGHT`). This includes:
- Default buttons (non-icon-only)
- Input fields (QLineEdit, QTextEdit first line)
- Select combobox
- List rows, table rows
- Menu items

**Exceptions (valid with reason):**
- Icon-only tool rail buttons: 48px (more breathing in nav strip)
- Hero CTA button: 40-48px (dominant action emphasis)
- Compact chip / badge: 24-28px (not a row, smaller element)
- Destructive "АВАР. ОТКЛ." button: may exceed ROW_HEIGHT for emphasis (documented)

**Rationale:** 36px balances:
- Legibility of 14px body text with vertical padding (36 − 20 = 16, balanced 8/8)
- Mouse targeting (minimum 32px, 4px safety margin)
- Density (15+ rows visible in typical panel at 720 min-height)

Ad-hoc heights (34, 38, 40 for no reason) break vertical rhythm.

**Applies to:** buttons, inputs, list / table / menu items

**Example (good):**

```python
# DESIGN: RULE-SPACE-007
# Default button — ROW_HEIGHT
button = QPushButton("Сохранить")
button.setFixedHeight(theme.ROW_HEIGHT)  # 36

# Input field — ROW_HEIGHT
input_field = QLineEdit()
input_field.setFixedHeight(theme.ROW_HEIGHT)  # 36

# Data table row
table.verticalHeader().setDefaultSectionSize(theme.ROW_HEIGHT)
```

**Example (acceptable exception):**

```python
# DESIGN: RULE-SPACE-007 exception
# Emergency stop button — deliberately larger for prominence
# Emergency action must be easy to find and click; 36 insufficient
emergency_button.setFixedHeight(48)
```

**Example (bad):**

```python
# Ad-hoc height with no reason
button.setFixedHeight(40)  # WRONG — should be 36 (ROW_HEIGHT) or documented
input_field.setFixedHeight(34)  # WRONG — below 36, mouse targeting risk
```

**Related rules:** RULE-SPACE-005 (clickable gap), `tokens/layout.md`

---

## RULE-SPACE-008: Icon vertical alignment with text

**TL;DR:** When icon sits inline with text, align both via `AlignVCenter` in HBox layout. Icon size matches text cap-height region.

**Statement:** Icon + text compositions MUST use `Qt.AlignmentFlag.AlignVCenter` on the layout's alignment, and icon size SHOULD match the text context (see `tokens/icons.md` sizing scale):

- Inline with BODY (14px): `ICON_SIZE_SM` (16px)
- Inline with LABEL (12px): `ICON_SIZE_SM` (16px)
- Inline with HEADING (18px): `ICON_SIZE_MD` (20px)
- Inline with TITLE (22px): `ICON_SIZE_MD` (20px) or `ICON_SIZE_LG` (24px)
- Inline with DISPLAY (32px): `ICON_SIZE_LG` (24px) or `ICON_SIZE_XL` (32px)

Icon sitting above or below text baseline (misaligned) looks like a layout bug.

**Rationale:** Icons are typographic glyphs (see RULE-COLOR-005). They share baseline with text. If icon top-aligns while text baseline-aligns, they visually drift apart. Vertical centering keeps them perceived as one unit.

**Applies to:** any HBox containing both icon (QLabel with pixmap or similar) and text (QLabel)

**Example (good):**

```python
# DESIGN: RULE-SPACE-008
# Warning banner — icon + text inline
warning_row = QHBoxLayout()
warning_row.setSpacing(theme.SPACE_1)  # 4px (RULE-SPACE-001)
warning_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)  # MANDATORY
warning_row.setContentsMargins(0, 0, 0, 0)

icon = QLabel()
icon.setFixedSize(theme.ICON_SIZE_SM, theme.ICON_SIZE_SM)  # 16×16 for body
icon.setPixmap(
    load_colored_icon("alert-triangle", color=theme.STATUS_WARNING)
      .pixmap(theme.ICON_SIZE_SM, theme.ICON_SIZE_SM)
)
warning_row.addWidget(icon)

label = QLabel("Внимание: калибровка устарела")
body_font = QFont(theme.FONT_BODY, theme.FONT_BODY_SIZE)
label.setFont(body_font)
warning_row.addWidget(label)
warning_row.addStretch()
```

**Example (bad):**

```python
# No alignment — icon top-aligns while text baseline-aligns
warning_row = QHBoxLayout()
warning_row.addWidget(icon)
warning_row.addWidget(label)
# Visual: icon appears above text baseline on Qt/macOS

# Icon size mismatched to text — 32px icon next to 14px text looks like badge
icon.setFixedSize(theme.ICON_SIZE_XL, theme.ICON_SIZE_XL)  # WRONG for body text
```

**Alternative alignment (valid):**

For rows where icon should align with TEXT BASELINE (rare — typically only when icon is a letter-like glyph), use `AlignBaseline`. But for most icon+text cases, `AlignVCenter` is correct.

**Related rules:** RULE-SPACE-001 (inline row gaps), RULE-COLOR-005 (icon color inheritance), `tokens/icons.md`

---

## Changelog

- 2026-04-17: Initial version. 8 rules. RULE-SPACE-005 (adjacent clickable gap) fills the previously-empty slot. RULE-SPACE-008 (icon vertical alignment with text) absorbed from earlier proposed standalone "icon" category per audit decision.
