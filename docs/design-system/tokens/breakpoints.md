---
title: Viewport Breakpoints
keywords: breakpoint, viewport, width, minimum, target, overlay, responsive, desktop-only
applies_to: window resizing, responsive logic, overlay sizing
enforcement: recommended
priority: medium
status: partially-proposed
last_updated: 2026-04-17
---

# Viewport Breakpoints

CryoDAQ is **desktop-only** — lab PC with single monitor, mouse, keyboard. There is no mobile layout, no tablet layout, no touch target sizing. This simplifies responsive design enormously.

Breakpoint tokens are PROPOSED. Currently most widgets hardcode minimum widths or use `sizeHint()`. This document specifies the target constant set.

## Hardware context

**Lab PC (production target):**
- Monitor: 1920×1080 typical (sometimes 1600×900 on older units)
- OS: Ubuntu 22.04 transitioning from Windows 10
- Display: non-retina LCD, 96 DPI
- Distance from operator: ~60cm (arm's length)

**Dev machine:**
- Vladimir's MacBook Pro: 1440×900 (scaled from retina)
- Occasionally 1680×1050 in docked mode

**Minimum supported viewport: 1280×720.** Below this, layout breaks and some tiles cannot display. This is the hard lower bound — not a responsive breakpoint, a system requirement.

## Proposed constants

| Token (proposed) | Value (px) | Use |
|---|---|---|
| `VIEWPORT_MIN_WIDTH` | `1280` | Hard minimum — below this, warn operator and reject layout |
| `VIEWPORT_MIN_HEIGHT` | `720` | Hard minimum |
| `VIEWPORT_TARGET_WIDTH` | `1920` | Design optimization target |
| `VIEWPORT_TARGET_HEIGHT` | `1080` | Design optimization target |
| `OVERLAY_MAX_WIDTH` (proposed) | `1400` | Max width for modal overlays — keeps backdrop visible on all sides |
| `OVERLAY_MAX_HEIGHT` (proposed) | `900` | Max height for modal overlays |
| `DASHBOARD_GRID_COLUMNS` | `8` | Logical grid column count for BentoGrid layout (canonical per AD-001) |

## Design target vs minimum

Design is optimized for **1920×1080** — tiles sized, spacing calibrated, typography tuned for this viewport.

At **1280×720** (minimum), expect:
- Fewer tiles visible simultaneously (dashboard may scroll)
- Some content truncated with ellipsis
- Overlays using nearly full viewport width

Below 1280×720 CryoDAQ should **refuse to render** and display:

```
Минимальный размер окна: 1280×720
Текущий: 1024×768
Пожалуйста увеличьте размер окна или разрешение.
```

Not responsive — fixed minimum.

## No mobile, no tablet

Explicitly out of scope:
- No `@media (max-width: 768px)` equivalent in Qt stylesheets
- No touch-target sizing (32×32 minimum is fine for mouse)
- No swipe gestures
- No orientation changes (no landscape/portrait)
- No hamburger nav (tool rail is always visible)
- No collapsible sidebar on narrow screens (not applicable)

If CryoDAQ is ever deployed on tablet (not planned), a separate responsive strategy is required — current design is strictly desktop.

## Overlay sizing

Modal overlays and drill-downs have max dimensions to keep backdrop visible:

```python
# DESIGN: RULE-SURF-009 (overlay max size)
overlay_width = min(
    viewport_width * 0.9,      # 90% viewport
    1400,                      # proposed OVERLAY_MAX_WIDTH; not yet in theme.py
)
overlay_height = min(
    viewport_height * 0.9,
    900,                       # proposed OVERLAY_MAX_HEIGHT; not yet in theme.py
)
```

At 1920×1080 viewport: overlay clamped to 1400×900, leaving ~260px margin on sides and ~90px top/bottom. At 1280×720: overlay at 1152×648 (90% of viewport).

See `components/modal.md` for overlay positioning.

## BentoGrid columns

Dashboard uses an **8-column logical grid** (`DASHBOARD_GRID_COLUMNS = 8`) as the canonical target per AD-001. Tiles span 1–8 columns:

| Tile type | Columns | Visual |
|---|---|---|
| SensorCell | 1 | Single sensor channel |
| SensorGroup | 2 | Group of related sensors |
| Chart tile (small) | 2 | Compact chart |
| Chart tile (medium) | 4 | Half-width chart |
| Chart tile (large) | 6 | Dominant chart |
| Full-width banner | 8 | Fault banner, emergency alert |

Column gap: `GRID_GAP = 8px`.
Grid width at 1920 viewport: (1920 − 56 toolrail − 48 margin) = 1816 / 8 ≈ 227px per column + 8 gap.

At 1280 viewport, columns become narrower (~142px + 8 gap). Dense content may clip — use responsive tile logic (future work, see `patterns/responsive-behavior.md`).

> **Implementation status (AD-001).** The Phase I.1 code at
> `src/cryodaq/gui/shell/overlays/_design_system/bento_grid.py` currently
> runs at 12 columns with auto-flow. This doc and `components/bento-grid.md`
> define the canonical 8-column target; alignment of the runtime grid is
> tracked as a future Phase II block. Design new dashboard layouts against
> the 8-column model.

## Font scaling at non-standard DPI

Qt supports `QT_SCALE_FACTOR` env var for HiDPI. If operator runs at 125% or 150% scale:

```
QT_SCALE_FACTOR=1.25 python -m cryodaq.launcher
```

All tokens (spacing, radius, font sizes) scale proportionally — no additional token changes needed. This is a system-level concern, not design-system.

## Anti-patterns

- **Hardcoded window sizes** — `setGeometry(100, 100, 1366, 768)` — use minimum/target tokens
- **"Mobile mode" logic** — not applicable
- **Collapsible tool rail** — ToolRail is always visible
- **Horizontal scrollbar** — ever, anywhere. Content must fit or clip, not scroll sideways.
- **Rendering at <1280 without warning** — surfaces layout bugs to operators

## Rule references

- `RULE-SURF-009` — Overlay max width constraint (`rules/surface-rules.md`)

## Related files

- `tokens/layout.md` — chrome dimensions subtract from viewport
- `tokens/spacing.md` — grid gap
- `components/bento-grid.md` — 8-column canonical grid (Phase I.1 code currently 12-column; see callout)
- `components/modal.md` — overlay sizing
- `patterns/responsive-behavior.md` — responsive strategy

## Changelog

- 2026-04-17: Initial version. PROPOSED tokens. Desktop-only scope clarified.
