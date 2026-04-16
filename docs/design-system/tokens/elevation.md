---
title: Elevation Tokens
keywords: elevation, shadow, z-index, stacking, depth, surface, layer, proposed
applies_to: all surface and overlay compositions
enforcement: strict
priority: high
status: partially-proposed
last_updated: 2026-04-17
---

# Elevation Tokens

CryoDAQ has a **zero-shadow policy** for dark mode. Elevation (depth perception) is conveyed through surface brightness delta, not through shadows. Z-index stacking is conveyed through explicit semantic levels, not magic numbers.

## Status

- **Surface-delta elevation**: currently in `theme.py` (via `SURFACE_*` tokens, see `tokens/colors.md`). Defined, enforced.
- **Z-index stack semantic names**: PROPOSED, not yet in `theme.py`. Widgets currently use raw integers. This document specifies the proposed semantic constants.

## Why zero shadows

On dark mode (`BACKGROUND #0d0e12`), shadows are ineffective:

1. Shadow color is typically `rgba(0, 0, 0, 0.3)` — against `#0d0e12`, alpha 0.3 black renders as ~`#090a0d`, imperceptibly different from background.
2. Increasing shadow alpha to be visible makes it look unnatural — shadows "floating" on dark background without a realistic light source.
3. Shadow blur radius increases rendering cost (Qt blur is CPU, not GPU) — expensive on 24 sensor-grid tiles updating at 2Hz.
4. Shadows are anti-pattern for industrial aesthetic — they belong to Material Design "paper elevation" metaphor, which we reject.

**Instead:** elevation is communicated via **surface brightness ramp**.

## Surface-delta elevation

Three distinct surface levels (see `tokens/colors.md` Surface Hierarchy):

```
Level 0 (deepest)   BACKGROUND #0d0e12   Viewport base
Level 1 (panel)     CARD #181a22         Dashboard tiles, side panels, SURFACE_PANEL/CARD/SUNKEN
Level 2 (elevated)  SECONDARY #22252f    Modal cards, popovers, SURFACE_ELEVATED
```

Modal over dashboard:
- Dashboard tile: `SURFACE_CARD` (Level 1)
- Modal backdrop: `SURFACE_OVERLAY_RGBA` (semi-transparent dim over viewport)
- Modal card: `SURFACE_ELEVATED` (Level 2)

The modal card is 1 step brighter than dashboard tiles. Small delta (~3 RGB points per channel), but in combination with backdrop dim it communicates "this is on top of everything else."

**Do not invent a Level 3.** If you need more depth, you're doing too much. Use popover or nested component instead of creating a new surface.

## Optional shadow for modals (single exception)

A single subtle shadow IS permitted on modal cards, for one reason: it slightly separates the modal card from backdrop-dimmed content even when brightness delta is minimal.

Proposed token:

```python
# DESIGN: not yet in theme.py
SHADOW_MODAL = "0 8px 24px rgba(0, 0, 0, 0.4)"
```

Use:

```python
self._card.setStyleSheet(
    f"background: {theme.SURFACE_ELEVATED};"
    f"border: 1px solid {theme.BORDER};"
    f"border-radius: {theme.RADIUS_LG}px;"
    # Only modal surface carries shadow
    # (Note: Qt stylesheet shadow via box-shadow NOT supported; use QGraphicsDropShadowEffect)
)

shadow = QGraphicsDropShadowEffect()
shadow.setBlurRadius(24)
shadow.setOffset(0, 8)
shadow.setColor(QColor(0, 0, 0, int(255 * 0.4)))
self._card.setGraphicsEffect(shadow)
```

**This is the ONLY shadow permitted in CryoDAQ GUI.** No card shadows in dashboard. No button shadows. No popover shadows. Just modal cards.

## Z-index semantic stack

Qt uses `widget.raise_()` / `widget.lower()` for explicit stacking, and within stylesheets there's no z-index property. But for logical layering (especially when widgets overlap in a single parent), we need semantic levels.

**PROPOSED constants:**

| Token (proposed) | Value | Semantic level |
|---|---|---|
| `Z_DASHBOARD` | `0` | Default — dashboard content, tiles, plots |
| `Z_TOOLRAIL` | `100` | Tool rail (left nav) stays above dashboard |
| `Z_HEADER` | `100` | TopWatchBar stays above dashboard (same level as toolrail) |
| `Z_BOTTOM_BAR` | `100` | Bottom status bar, same chrome level |
| `Z_POPOVER` | `200` | Tooltips, popovers, transient floating content |
| `Z_OVERLAY` | `300` | Drill-down overlays (ExperimentOverlay, ArchiveOverlay) |
| `Z_MODAL` | `400` | Modal dialogs blocking interaction |
| `Z_TOAST` | `500` | Toast notifications, transient status messages |
| `Z_TOOLTIP` | `600` | Tooltips over everything (including modals) |
| `Z_EMERGENCY` | `999` | Emergency fault banner — overrides everything |

**Within same level, widget order is painter-defined** (last-raised wins).

**Use as `setProperty` for CSS-like cascade:**

```python
# DESIGN: using semantic Z value
widget.setProperty("z_level", theme.Z_MODAL)
widget.raise_()
```

Or more directly in Qt, `raise_()` after all peers have been added.

## Stacking consistency rule

When multiple overlays coexist (rare but possible):

1. Tooltip over modal: modal at Z_MODAL (400), tooltip at Z_TOOLTIP (600) — tooltip visible.
2. Toast over modal: modal at Z_MODAL (400), toast at Z_TOAST (500) — toast visible.
3. Emergency banner over everything: Z_EMERGENCY (999) — always visible.

**Modals do NOT stack with other modals.** Only one modal at a time (RULE-SURF-005). If a modal needs confirmation, use a popover from within modal (Z_POPOVER relative-to-modal), not another modal.

## Focus "elevation"

Keyboard-focused element does NOT change stacking level. Focus is indicated by **focus ring** (`ACCENT` color), not by raising. Focus is a property, not a layer.

```python
# DESIGN: RULE-INTER-001 (focus ring, no z change)
widget.setStyleSheet(
    f"QLineEdit:focus {{ border: 2px solid {theme.ACCENT}; }}"
)
# widget.raise_() — DO NOT call on focus
```

## Anti-patterns

- **Adding card shadows** — not in CryoDAQ aesthetic (only exception: modal)
- **Z-index magic numbers** — `raise_()` with `setZValue(42)` instead of semantic constant
- **Stacking multiple modals** — confusion; use popover from within
- **Using shadow to separate tiles** — tiles separate via gap + surface delta, not shadow
- **"Hover lift" effects** — moving element up on hover (reject Material's "paper lifts to meet finger")

See `ANTI_PATTERNS.md#elevation`.

## Rule references

- `RULE-SURF-005` — No nested modals (`rules/surface-rules.md`)
- `RULE-INTER-001` — Focus indicated via ring, not z-change (`rules/interaction-rules.md`)

## Related files

- `tokens/colors.md` — Surface hierarchy tokens
- `rules/surface-rules.md` — Surface composition rules
- `components/modal.md` — Modal card uses Z_MODAL + single-shadow exception
- `components/popover.md` — Popover uses Z_POPOVER or Z_MODAL+1 if inside modal
- `components/toast.md` — Toast uses Z_TOAST

## Changelog

- 2026-04-17: Initial version. Zero-shadow policy and surface-delta elevation formalized from existing theme.py. Z-index semantic names PROPOSED (not yet in theme.py).
