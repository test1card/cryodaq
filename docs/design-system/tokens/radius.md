---
title: Radius Tokens
keywords: radius, border-radius, corners, rounded, pill, hierarchy
applies_to: all widgets with border-radius
enforcement: strict
priority: high
last_updated: 2026-04-17
status: canonical
---

# Radius Tokens

Border-radius scale is **deliberately tight**. Maximum non-pill radius is 8px. This is intentional — industrial aesthetic favors moderate rounding. "Over-rounded" (12-16px cards) feels mobile/app-like, wrong for instrumentation UI.

Total: **5 radius tokens**.

## Scale

| Token | Value (px) | Use |
|---|---|---|
| `RADIUS_NONE` | `0` | Explicit "no rounding" — plot axis lines, separator rules, full-width banners |
| `RADIUS_SM` | `4` | Inputs, buttons, small chips, badge backgrounds |
| `RADIUS_MD` | `6` | Tiles inside cards, secondary panels, sub-components |
| `RADIUS_LG` | `8` | Cards, modals, top-level container surfaces |
| `RADIUS_FULL` | `9999` | Pills, circular buttons, status dots, avatar placeholders |

**There is no `RADIUS_XL`.** Do not add one without product decision. The intentional maximum for non-circular elements is 8px.

## Hierarchy rule (critical)

**Parent radius ≥ child radius.** A container with `RADIUS_LG` (8px) can contain elements with `RADIUS_MD` (6px) or `RADIUS_SM` (4px), but NOT with `RADIUS_LG` or larger.

Why: nested same-radius creates visual "doll" effect. Nested larger-than-parent breaks the convex-hull perception of the outer container.

```
Card (RADIUS_LG = 8)
  └── Tile (RADIUS_MD = 6)        ✅ smaller than parent
        └── Input (RADIUS_SM = 4) ✅ smaller than parent

Card (RADIUS_LG = 8)
  └── Inner panel (RADIUS_LG = 8) ❌ same as parent
  └── Feature block (RADIUS_MD = 6, WIDTH matches card) ⚠️ acceptable only if no visible border
```

See `rules/surface-rules.md` RULE-SURF-002 for enforcement.

## No-sharp-inside-rounded rule

**If parent has `border-radius > 0`, no visible child surface may have `border-radius: 0`.**

The visual regression that caused Phase I.1 rework: ModalCard with `RADIUS_LG` outer card contained a content_host with `border-radius: 0`, rendered as sharp dark rectangle inside rounded card. Broken hierarchy.

Either:
- Remove child background (transparent content_host) — preferred
- Give child matching or smaller radius (`RADIUS_MD` if visible panel)

`RADIUS_NONE` (= 0) is valid only in contexts where no border-radius is expected — flat separator lines, plot axes, full-width fault banners that span the viewport edge-to-edge.

## Semantic assignment

| Widget type | Radius token | Rationale |
|---|---|---|
| ModalCard, Card, TileCard (and proposed PanelCard extractions) | `RADIUS_LG` (8) | Top-level containers, max allowed |
| BentoTile, sub-panel, section | `RADIUS_MD` (6) | Inside top-level containers |
| Input field, text area, select | `RADIUS_SM` (4) | Small interactive controls |
| Button (default shape) | `RADIUS_SM` (4) | Matches input for form rhythm |
| Badge, chip (rectangular) | `RADIUS_SM` (4) | Small label container |
| Pill button (e.g., filter chip) | `RADIUS_FULL` (9999) | Pill shape |
| Status dot, avatar placeholder | `RADIUS_FULL` (9999) | Circular element |
| Plot axis, separator rule, full-width banner | `RADIUS_NONE` (0) | No rounding expected |

## Circular elements

`RADIUS_FULL = 9999` produces pill-shaped container. For true circular element (e.g., status dot 8px diameter), combine with equal width and height:

```python
# Status dot, 8px circle
dot = QFrame()
dot.setFixedSize(8, 8)
dot.setStyleSheet(
    f"background: {theme.STATUS_OK};"
    f"border-radius: {theme.RADIUS_FULL}px;"  # effectively 4px — half of 8
)
```

For pill button (wider than tall):

```python
# Filter chip, 32px tall
chip = QPushButton("Фильтр")
chip.setFixedHeight(32)
chip.setStyleSheet(
    f"background: {theme.MUTED};"
    f"color: {theme.FOREGROUND};"
    f"border-radius: {theme.RADIUS_FULL}px;"  # effectively 16 — half of 32
    f"padding: 0 {theme.SPACE_4}px;"          # horizontal breathing room
)
```

## Radius + border interaction

When a surface has both `background` and `border`, ensure the border respects the radius. Qt handles this correctly by default:

```python
widget.setStyleSheet(
    f"background: {theme.SURFACE_ELEVATED};"
    f"border: 1px solid {theme.BORDER};"
    f"border-radius: {theme.RADIUS_LG}px;"  # border follows radius
)
```

**Pitfall:** if you set border-radius but content overflows (e.g., inline image), corners may clip incorrectly. Use `setAttribute(Qt.WA_StyledBackground)` on the widget to ensure clipping:

```python
widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
widget.setStyleSheet(
    f"background: {theme.SURFACE_ELEVATED};"
    f"border-radius: {theme.RADIUS_LG}px;"
)
```

## Anti-patterns

- **Radius 12 or 16** — does not exist in scale. Adding ad-hoc values breaks consistency.
- **Sharp rectangle inside rounded card** — hierarchy break (Phase I.1 regression)
- **All elements RADIUS_FULL for "soft" look** — creates toy/mobile aesthetic inappropriate for instrumentation UI
- **RADIUS_NONE on interactive surfaces** — unexpected sharp buttons in otherwise rounded UI
- **Child radius ≥ parent radius** — visual disharmony

See `ANTI_PATTERNS.md#radius`.

## Rule references

- `RULE-SURF-002` — No sharp corners inside rounded card (`rules/surface-rules.md`)
- `RULE-SURF-006` — Radius hierarchy cascade (`rules/surface-rules.md`)

## Related files

- `tokens/spacing.md` — padding pairs with radius
- `rules/surface-rules.md` — radius enforcement in composition
- `components/card.md` — card radius usage
- `components/button.md` — button radius usage

## Changelog

- 2026-04-17: Initial version from theme.py inventory (5 radius tokens)
