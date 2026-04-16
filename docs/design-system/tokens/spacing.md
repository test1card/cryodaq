---
title: Spacing Tokens
keywords: spacing, gap, padding, margin, space, card-padding, grid-gap
applies_to: all layouts and containers
enforcement: strict
priority: high
last_updated: 2026-04-17
---

# Spacing Tokens

Spacing in CryoDAQ uses a **4-pixel base unit**. All spacing values are multiples of 4. No arbitrary `margin: 13px` or `padding: 7px` — use tokens.

Total: **9 spacing tokens** (7 scale primitives + 2 semantic aliases).

## Scale (primitives)

| Token | Value (px) | Typical use |
|---|---|---|
| `SPACE_0` | `0` | Zero-spacing marker (explicit "no gap"), clearing inherited margins |
| `SPACE_1` | `4` | Inline icon + text gap, minimal breathing room inside compact controls |
| `SPACE_2` | `8` | Adjacent control spacing, grid gap default, compact form field gap |
| `SPACE_3` | `12` | Paragraph gap, comfortable inline gap, default card padding value |
| `SPACE_4` | `16` | Between section elements within card, default between form rows |
| `SPACE_5` | `24` | Between major sections, card margins in dashboard grid |
| `SPACE_6` | `32` | Large section separator, dashboard-level gap |

**Scale ratio:** geometric 1.5× then linear — 4, 8, 12, 16, 24, 32. Supports typical layouts without wasted tokens. No `SPACE_7` (48) or `SPACE_8` (64) — use `SPACE_6 * 2` if genuinely needed, but most such uses indicate over-spacing.

## Semantic aliases

| Token | Resolves to | Use |
|---|---|---|
| `CARD_PADDING` | `12` (= `SPACE_3`) | Default internal padding for cards, tiles, panels |
| `GRID_GAP` | `8` (= `SPACE_2`) | Default gap in BentoGrid, sensor grids, tile collections |

**Use aliases when intent is semantic**, not when intent is "12 pixels." If the value happens to be 12 but the purpose isn't "card padding," use `SPACE_3` directly.

## Usage patterns

### Card internal structure

```python
# DESIGN: RULE-SURF-003 (symmetric padding)
card_layout = QVBoxLayout(self._card)
card_layout.setContentsMargins(
    theme.SPACE_5, theme.SPACE_5, theme.SPACE_5, theme.SPACE_5  # symmetric
)
card_layout.setSpacing(theme.SPACE_4)  # between sections

# Inner section spacing
section_layout.setContentsMargins(0, 0, 0, 0)  # inherit from card
section_layout.setSpacing(theme.SPACE_3)  # tighter than card-level
```

### Inline row (label + value)

```python
# DESIGN: RULE-SPACE-001 (inline gap = SPACE_1 for icon, SPACE_2 for text)
row = QHBoxLayout()
row.setSpacing(theme.SPACE_2)  # 8px between label and value
row.setContentsMargins(0, 0, 0, 0)
row.addWidget(QLabel("Т мин"))
row.addWidget(value_display)
```

### Grid of tiles

```python
# DESIGN: RULE-SPACE-003 (grid gap)
grid = QGridLayout()
grid.setHorizontalSpacing(theme.GRID_GAP)  # 8px
grid.setVerticalSpacing(theme.GRID_GAP)    # 8px
grid.setContentsMargins(0, 0, 0, 0)
```

### Dashboard-level

```python
# DESIGN: RULE-SPACE-002 (dashboard sections)
dashboard_layout.setContentsMargins(
    theme.SPACE_5, theme.SPACE_5, theme.SPACE_5, theme.SPACE_5
)
dashboard_layout.setSpacing(theme.SPACE_6)  # between major dashboard zones
```

## Symmetry rule

**Card internal padding MUST be symmetric on all 4 sides** unless explicitly argued. Default: `theme.SPACE_5` all four.

Asymmetric padding (e.g., less top than sides) is a code smell. It usually indicates:
- An attempt to "fix" header spacing by reducing top padding (fix the header instead — see RULE-SURF-004)
- A workaround for content clipping (fix the content sizing instead)

Exceptions are valid but must be documented:

```python
# DESIGN: RULE-SURF-003 exception
# Footer needs asymmetric bottom padding for primary CTA breathing room.
# Standard 24/24/24/24 makes the CTA feel cramped against the bottom edge.
card_layout.setContentsMargins(
    theme.SPACE_5, theme.SPACE_5, theme.SPACE_5, theme.SPACE_6  # bottom deeper
)
```

See `rules/surface-rules.md` RULE-SURF-003.

## Hierarchy rule

**Outer margin MUST be ≥ inner gap.** Elements inside a card should cluster closer than the card's edge-to-content distance. Violation creates "tight card with lots of air" appearance.

```python
# GOOD — outer margin (24) > inner gap (16)
card_layout.setContentsMargins(SPACE_5, SPACE_5, SPACE_5, SPACE_5)  # 24
card_layout.setSpacing(SPACE_4)  # 16

# BAD — inner gap (32) > outer margin (16)
card_layout.setContentsMargins(SPACE_4, SPACE_4, SPACE_4, SPACE_4)  # 16
card_layout.setSpacing(SPACE_6)  # 32 — looks disconnected
```

See `rules/spacing-rules.md` RULE-SPACE-004.

## Touch target considerations (desktop)

CryoDAQ is **desktop-only** — lab PC with mouse + keyboard. Touch targets don't apply. Minimum clickable element size is **32×32px** (see `components/button.md` for button sizing), achieved through button's inherent height rather than explicit spacing padding.

However, **minimum spacing between adjacent interactive elements is `SPACE_1` (4px)** to prevent mis-click. For closely-placed buttons (e.g., phase stepper navigation arrows), ensure at least 4px gap between clickable regions.

## Dashboard grid

12-column BentoGrid uses GRID_GAP (8px) by default. Tile internal padding uses CARD_PADDING (12px). This yields visual rhythm:

```
[ outer dashboard margin 24 ]
  [ row of tiles with 8px gap between ]
    [ tile with 12px internal padding ]
       ← content →
    [ /tile ]
  [ /row ]
[ /outer ]
```

Three distinct spacing tiers: outer frame 24, tile-to-tile 8, inside-tile 12. Visual density correct for data dashboard.

## Anti-patterns

- **Arbitrary pixel values** — `setContentsMargins(10, 14, 11, 9)` should never appear. Use scale tokens.
- **Inner gap larger than outer margin** — breaks hierarchy perception
- **Zero spacing between clickable elements** — mis-click risk
- **Asymmetric card padding without documented exception**
- **Using `SPACE_0` as default** instead of explicitly meaning "no space" — adds noise

See `ANTI_PATTERNS.md#spacing`.

## Rule references

- `RULE-SPACE-001` — Inline row gaps (`rules/spacing-rules.md`)
- `RULE-SPACE-002` — Dashboard grid spacing (`rules/spacing-rules.md`)
- `RULE-SPACE-003` — Grid gap semantics (`rules/spacing-rules.md`)
- `RULE-SPACE-004` — Outer ≥ inner hierarchy (`rules/spacing-rules.md`)
- `RULE-SURF-003` — Symmetric card padding (`rules/surface-rules.md`)

## Related files

- `tokens/radius.md` — radius tokens often paired with padding
- `tokens/layout.md` — fixed-height layout tokens
- `rules/spacing-rules.md` — full enforcement rules
- `rules/surface-rules.md` — padding symmetry

## Changelog

- 2026-04-17: Initial version from theme.py inventory (7 scale + 2 semantic aliases)
