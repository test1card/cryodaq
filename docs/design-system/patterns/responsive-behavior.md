---
title: Responsive Behavior
keywords: responsive, viewport, breakpoints, reflow, desktop-only, minimum-width, scaling
applies_to: how layouts adapt to different viewport dimensions
status: canonical
references: tokens/breakpoints.md, tokens/layout.md, components/bento-grid.md
last_updated: 2026-04-17
---

# Responsive Behavior

Rules for layout adaptation across viewport dimensions. CryoDAQ is a desktop industrial tool — operator's display is typically 1920×1080 or 2560×1440. Phone and tablet layouts are out of scope. But even within desktop range, viewports vary (1280 laptop → 1920 standard → 4K wide), and the layout must handle all of them gracefully.

> **Note:** This document references two names that are not yet shipped
> tokens/primitives. **Panel maximum width** is clamped at roughly
> 1400px to prevent line-length readability problems on wide monitors —
> this value is **not yet a formal token**; see
> `governance/contribution.md` for proposing it as `OVERLAY_MAX_WIDTH`.
> **`PanelCard`** mentioned in downstream specs is a proposed extraction
> of the generic card base; current code uses `ModalCard` (the shipped
> `Card` variant). BentoGrid references below use the canonical
> 8-column target per AD-001; current code runs at 12 columns — see
> `components/bento-grid.md` for implementation status.

## Scope boundaries

**CryoDAQ targets:**
- Desktop viewports: 1280×800 minimum → 3840×2160 maximum
- Single-window operation (no floating panels, no multi-window docking)
- Mouse + keyboard input (touch interaction is out of scope)

**NOT supported:**
- Phone / small-tablet viewports (< 1280 width)
- Touch-first gestures (pinch, swipe, long-press)
- Portrait orientation (< 720 height is truncated, not reflowed)
- Split-screen side-by-side with other apps taking < 50% of screen

If operator tries to run CryoDAQ at <1280 width, the shell stays as-is with horizontal scroll; chrome does not collapse. This is intentional — industrial tool, not marketing site.

## Three viewport bands

| Band | Width range | Typical hardware | Adjustment |
|---|---|---|---|
| **Laptop** | 1280–1599px | Lab laptop, old secondary monitor | Tight — cards at minimum useful size |
| **Standard** | 1600–2559px | Lab PC, standard operator monitor | Target — all specs designed here |
| **Wide** | 2560px+ | 4K monitor, ultra-wide | Relaxed — cards expand, content breathes |

**Specs are designed for Standard band.** Other bands are accommodations, not first-class targets.

## What adapts, what stays fixed

### Stays fixed across all viewports

- **Chrome dimensions:** TopWatchBar height 56px, ToolRail width 56px, BottomStatusBar height 28px.
- **Corner square.** Always 56×56 at top-left, always owned by chrome.
- **Font sizes.** No font scaling with viewport. FONT_BODY is 14px at 1280 and at 4K.
- **Border thickness.** 1px borders stay 1px. 3px fault borders stay 3px.
- **Radii.** RADIUS_LG = 8 everywhere, always.
- **Padding.** `SPACE_5` (24) inside cards at all viewports.

### Adapts with viewport

- **Main content area width:** expands to fill viewport minus chrome.
- **BentoGrid total width:** expands proportionally; each column gets more pixels.
- **Card widths inside a BentoGrid:** col_span stays fixed; pixel width scales.
- **Chart content area:** plot widget expands to available width.
- **Text wrapping:** long experiment names, long log entries wrap at wider viewports.

### Adapts only at extreme viewports

- **Below 1280:** chrome stays, main content gets horizontal scroll (no responsive collapse).
- **Above 3840 (rare):** BentoGrid still 8 columns, but single-pane Scaffold 2 panels clamp to roughly 1400px (the proposed `OVERLAY_MAX_WIDTH`, not yet a formal token) to avoid "line-stretched-across-4K" readability problem.

## BentoGrid responsive behavior

BentoGrid is the primary layout primitive. Its rules:

1. **Column count is fixed at 8.** Does not reduce to 4 on narrow viewports or expand to 12 on wide.
2. **Column width scales proportionally.** At 1280px viewport with 56px ToolRail and 48px margins, main area ~1128px. Each of 8 columns ~141px. At 1920px viewport, each column ~230px.
3. **Tiles keep their col_span.** A `col_span=4` tile is half the grid at both 1280 and 1920.
4. **No auto-flow reordering.** Tiles stay where declared, regardless of viewport.
5. **Tile content is responsible for its own internal responsiveness.** A ChartTile inside col_span=4 decides how its legend behaves at 564px actual pixel width vs 920px.

## Panel Scaffold 2 responsive behavior

Single-panel screens (Keithley, Alarms, Journal) in Scaffold 2:

1. **Panel fills available width** up to a maximum of roughly 1400px (the proposed `OVERLAY_MAX_WIDTH`, not yet a formal token — see `governance/contribution.md`).
2. **On viewports >1400 content pixels, panel is centered** with blank space on sides (not stretched).
3. **Panel height fills viewport height** minus chrome minus `SPACE_5` padding.
4. **Scroll handling:** panel content exceeding height → internal `QScrollArea`, never page-level scroll.

## Split Scaffold 3 responsive behavior

Split-view (Analytics, Conductivity):

1. **Split ratio maintained at viewport scaling.** 70/30 split remains 70/30 at 1280 and 1920.
2. **Minimum sizes:** primary region ≥ 600px, secondary region ≥ 280px. If viewport doesn't allow both, reduce gap or let content inside the smaller region scroll.
3. **No switching to stacked on narrow viewports** — CryoDAQ is desktop-only; split stays side by side.

## Modal responsive behavior

Modals:

1. **Max width clamped** to roughly 1400px (proposed `OVERLAY_MAX_WIDTH` — not yet a formal token).
2. **Min margin** from viewport edge = `SPACE_5` (24).
3. **Max height** = 90% of viewport height.
4. **Content overflow** → `QScrollArea` inside modal card, not modal growing past viewport.

## Text handling at different widths

- **Long experiment names** (e.g., `calibration_run_042_retry_v2_with_thermal_compensation`) use ellipsize-right with full tooltip at all viewports.
- **Log entries** wrap at card boundary; never force single-line with clip-off at right.
- **Category labels** UPPERCASE labels do NOT wrap — they're short by construction («ДАВЛЕНИЕ», not «ДАВЛЕНИЕ В ВАКУУМНОЙ КАМЕРЕ»). If a category label needs to wrap, the label is wrong.
- **Russian labels are longer than English equivalents** — budget ~30% extra width for any label that has an English design reference.

## Chart responsive behavior

Charts (pyqtgraph PlotWidget inside ChartTile):

1. **Plot area expands to available tile width** after CARD_PADDING.
2. **Y-axis width fixed** via `setWidth(PLOT_AXIS_WIDTH_PX)` — prevents reflow as values change.
3. **X-axis time range constant** per tile config — viewport doesn't change how much history is shown.
4. **Legend placement:** inside tile header row, not inside plot area. Header wraps at narrow widths if many series.
5. **No auto-zoom on resize.** Resize doesn't pan/zoom; current view stays.

## Chrome at constrained viewports

At minimum 1280px width, TopWatchBar's 4 vitals + mode badge fit comfortably. At < 1280px (unsupported but handled gracefully):

- Chrome stays at full width; horizontal scrollbar appears on main content area (not chrome).
- Mode badge may truncate to icon-only if < 800px (extreme unsupported edge case).
- BottomStatusBar items may drop least-critical (time) first if truly squeezed.

These are "best effort" fallbacks, not design targets.

## No breakpoint media queries

Unlike web UI design, there are no media queries per se. Breakpoints are implicit in the min/max constraints:

- Panel min widths (e.g., split-view primary ≥ 600px)
- Modal max width (~1400px; proposed `OVERLAY_MAX_WIDTH`, not yet a formal token)
- Column min widths inside BentoGrid (implicit ~100px per column)
- Chart minimum heights (~120px sparkline, ~240px full chart)

When constraints collide with small viewports, the response is:
1. Content scrolls inside its container if possible
2. Or truncates with ellipsize + tooltip if single-line
3. Never reflows to a different layout

## Rules applied

- **RULE-SPACE-006** — coupled constants (HEADER_HEIGHT, TOOL_RAIL_WIDTH) stay fixed regardless of viewport
- **RULE-TYPO-009** — font sizes fixed; don't scale with viewport
- **RULE-SURF-009** — overlay max widths enforced at all viewports
- **RULE-DATA-003** — stable widths via tabular numbers: chart axis widths don't drift with viewport either

## Common mistakes

1. **Responsive BentoGrid that drops columns.** 8 → 4 on narrow viewport. Breaks declared tile placements. Our grid stays 8.

2. **Auto-scaling fonts.** "Scale up fonts on wide monitors." No — font sizes are tokens; wide monitor shows more content, not bigger content.

3. **Mobile-first thinking.** Designing for phone first then scaling up. CryoDAQ never runs on phone; designing for it wastes effort and distorts desktop priorities.

4. **Stretching Scaffold 2 panel to full 4K width.** A form at 3800px wide has lines too long to read comfortably. Clamp to roughly 1400px (the proposed `OVERLAY_MAX_WIDTH` — not yet a formal token).

5. **Letting modal grow to match content.** Modal becomes taller than viewport, some content invisible. Clamp max_height to viewport and scroll inside.

6. **Hiding chrome at small viewports.** Losing TopWatchBar to "save space" defeats its purpose. Chrome is invariant; small viewports scroll content.

7. **Testing only at 1920.** Dashboard looks fine at 1920 but cards overlap at 1280. Test at Standard AND Laptop bands before shipping.

8. **Inventing in-between widths.** "This panel looks best at 1440-specific tuning." No — target the whole Standard band as one.

9. **Auto-wrapping category labels.** «ТЕПЛОПРОВОДНОСТЬ ОБРАЗЦА В АЗОТНОЙ ВАННЕ» as section header wraps to two lines. Shorten the label; don't handle the wrap.

## Related patterns

- `patterns/page-scaffolds.md` — responsive behavior is scaffold-specific
- `patterns/cross-surface-consistency.md` — responsive rules stay consistent across panels
- `tokens/breakpoints.md` — implicit breakpoints per specific size constraints
- `tokens/layout.md` — fixed layout constants

## Changelog

- 2026-04-17: Initial version. Desktop-only scope. Three viewport bands (Laptop / Standard / Wide). What adapts vs fixed. No mobile, no touch, no portrait. BentoGrid stays 8 columns at all viewports.
