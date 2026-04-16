---
title: Layout Tokens
keywords: layout, height, width, header, toolrail, row, bottom-bar, chrome, fixed
applies_to: app shell chrome, main containers
enforcement: strict
priority: high
last_updated: 2026-04-17
---

# Layout Tokens

Fixed dimensions for application shell chrome. These values are load-bearing for alignment — changing one without the other can visually break corner alignment.

Total: **5 layout tokens**.

## Chrome dimensions

| Token | Value (px) | Use |
|---|---|---|
| `HEADER_HEIGHT` | `56` | TopWatchBar height, application title bar |
| `TOOL_RAIL_WIDTH` | `56` | ToolRail width (vertical icon nav, left side) |
| `BOTTOM_BAR_HEIGHT` | `28` | Status bar at bottom of window |
| `ROW_HEIGHT` | `36` | Default row height for list/table rows, button heights |
| `PLOT_AXIS_WIDTH_PX` | `60` | pyqtgraph Y-axis reserved width for multi-digit numeric labels |

## Coupled constants

**`HEADER_HEIGHT == TOOL_RAIL_WIDTH` (both 56px) is intentional.**

This creates a square in the top-left corner where the header bar and tool rail meet. If one changes, the other must change in lockstep — otherwise the corner becomes a rectangle and visual alignment breaks.

```
+---------+-----------------------+
|  56×56  |    Header (56 high)   |
|  square |                       |
+---------+-----------------------+
|         |                       |
|  Tool   |    Content area       |
|  Rail   |                       |
|  (56    |                       |
|  wide)  |                       |
|         |                       |
|         |                       |
+---------+-----------------------+
|   Bottom status bar (28 high)   |
+---------------------------------+
```

Rule enforcement: if changing `HEADER_HEIGHT`, update `TOOL_RAIL_WIDTH` in same commit. See `rules/spacing-rules.md` RULE-SPACE-006.

## Hierarchy rationale

**BOTTOM_BAR_HEIGHT (28) < HEADER_HEIGHT (56)** — deliberate asymmetry. The top bar carries primary persistent context (temperatures, pressure, phase, alarms); the bottom bar carries secondary info (connection status, notifications). Giving them equal weight would dilute hierarchy.

**ROW_HEIGHT (36)** balances:
- Large enough for 14px text with comfortable vertical padding (36 − 20 = 16px = 8 top + 8 bottom)
- Tall enough for mouse cursor targeting (32px minimum, 36 gives 4px safety margin)
- Small enough for 15+ rows visible in a typical panel without scrolling

**PLOT_AXIS_WIDTH_PX (60)** reserved for pyqtgraph Y-axis:
- Accommodates 4-digit temperature labels (`293.15`)
- Accommodates scientific notation pressure (`1.2e-6`)
- Gives 4px breathing between axis and plot content

## Content area sizing

Content area dimensions derive from viewport and chrome:

```
content_width  = viewport_width − TOOL_RAIL_WIDTH
content_height = viewport_height − HEADER_HEIGHT − BOTTOM_BAR_HEIGHT
```

For minimum viewport 1280×720:
- content_width = 1280 − 56 = 1224px
- content_height = 720 − 56 − 28 = 636px

For target viewport 1920×1080:
- content_width = 1920 − 56 = 1864px
- content_height = 1080 − 56 − 28 = 996px

See `tokens/breakpoints.md` for viewport minimum / target / max constraints.

## Row height applications

`ROW_HEIGHT = 36` is the **default minimum height for most interactive controls**, not only rows:

| Element | Height | Rationale |
|---|---|---|
| List row, table row | `ROW_HEIGHT` (36) | Default |
| Default button | `ROW_HEIGHT` (36) | Matches input/form rhythm |
| Input field | `ROW_HEIGHT` (36) | Pairs with button |
| ToolRail icon button | `ROW_HEIGHT + some` (usually 48) | More breathing room in nav strip |
| Badge | ~24 (not `ROW_HEIGHT`) | Smaller than rows; uses `FONT_SIZE_SM` |
| Status chip | ~28 (not `ROW_HEIGHT`) | Medium size between badge and button |

Not all interactive controls are exactly ROW_HEIGHT — use it as default baseline, deviate with reason.

## Anti-patterns

- **Changing `HEADER_HEIGHT` without matching `TOOL_RAIL_WIDTH`** — breaks corner square
- **Ad-hoc heights** — `setFixedHeight(40)` when `ROW_HEIGHT` is 36. Either use ROW_HEIGHT or add a semantic token.
- **Equal top and bottom bar heights** — dilutes hierarchy
- **Content assuming viewport size** — use viewport - chrome arithmetic, not hardcoded dimensions

## Rule references

- `RULE-SPACE-006` — Coupled chrome constants (`rules/spacing-rules.md`)
- `RULE-SPACE-007` — Row height defaults (`rules/spacing-rules.md`)

## Related files

- `tokens/spacing.md` — inner padding pairs with layout
- `tokens/breakpoints.md` — viewport constraints
- `cryodaq-primitives/top-watch-bar.md` — uses `HEADER_HEIGHT`
- `cryodaq-primitives/tool-rail.md` — uses `TOOL_RAIL_WIDTH`
- `cryodaq-primitives/bottom-status-bar.md` — uses `BOTTOM_BAR_HEIGHT`

## Changelog

- 2026-04-17: Initial version from theme.py inventory (5 layout tokens)
