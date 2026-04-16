---
title: Page Scaffolds
keywords: scaffold, layout, page, shell, chrome, main-area, structure, three-zone, composition
applies_to: how to compose a full screen from chrome + content zones
status: canonical
references: cryodaq-primitives/top-watch-bar.md, cryodaq-primitives/tool-rail.md, cryodaq-primitives/bottom-status-bar.md, components/bento-grid.md
last_updated: 2026-04-17
---

# Page Scaffolds

How to compose a full CryoDAQ screen from chrome (TopWatchBar + ToolRail + BottomStatusBar) and main content area. All operator-facing screens follow one of three scaffolds.

## The three-zone shell

Every screen has the same three chrome zones, always in the same positions:

```
┌───────────────────────────────────────────────────────────────────┐
│                                                                   │
│  [TopWatchBar — 4 vitals + mode badge]                            │  ◀── HEADER_HEIGHT (56)
│                                                                   │
├──────┬────────────────────────────────────────────────────────────┤
│      │                                                            │
│ Tool │                                                            │
│ Rail │           Main content area                                │
│      │           (scaffold-specific)                              │
│      │                                                            │
│ 56   │                                                            │
│      │                                                            │
│      │                                                            │
├──────┴────────────────────────────────────────────────────────────┤
│                                                                   │
│  [BottomStatusBar — Engine / Safety / ZMQ / Time]                 │  ◀── BOTTOM_BAR_HEIGHT (28)
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

Chrome never disappears, never resizes per content, never animates. It is infrastructure — not product. Every screen inherits all three zones; only the main content area changes.

## Chrome zone invariants

1. **Three chrome zones always present** on every screen: TopWatchBar (top), ToolRail (left), BottomStatusBar (bottom).
2. **Modal overlays do NOT hide chrome.** Operator retains situational awareness even during drill-down.
3. **Dashboard overlays (Modals) sit above the main content but below chrome** in z-order. Chrome remains visible at edges.
4. **Corner square intact.** TopWatchBar height = ToolRail width (per RULE-SPACE-006). Corner 56×56 at top-left visually owned by chrome, not content.
5. **Main content area padding:** `SPACE_5` (24) on all sides from chrome edges. Content never touches chrome.

## Three main-area scaffolds

### Scaffold 1 — Bento dashboard (Обзор)

Multi-tile overview composition. Primary home screen; operator's default starting place.

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│   [ExperimentCard   ]  [ChartTile          ]                    │
│   [dashboard variant]  [multi-series temps ]                    │
│   [4 col_span       ]  [4 col_span         ]                    │
│                                                                 │
│   [DataDenseTile sensor grid                 ]                  │
│   [8 col_span — all visible channels          ]                 │
│                                                                 │
│   [ChartTile  ] [ExecKPI] [ExecKPI ] [QuickLog]                 │
│   [pressure  ] [heater ] [safety  ] [ 2 col_s]                  │
│   [2 col_span] [2 col_s] [2 col_s ]                             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
 ◀── 8-column BentoGrid composition
```

Components: `BentoGrid` + mix of `ChartTile`, `ExecutiveKpiTile`, `DataDenseTile`, `QuickLogBlock`, `ExperimentCard`.

Padding from chrome: `SPACE_5` (24). Grid gap between tiles: `GRID_GAP` (8).

### Scaffold 2 — Single-panel full-bleed (Keithley, Alarms, Journal, Settings)

One panel filling main-area. Used when a single task owns the whole screen — operator is doing one thing, not overviewing multiple.

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│   ╔══════════════════════════════════════════════════════════╗  │
│   ║  Panel title / breadcrumb                                ║  │
│   ║                                                          ║  │
│   ║                                                          ║  │
│   ║    Panel content — form / table / dual-channel view /    ║  │
│   ║    time-series chart / configuration panel / etc.        ║  │
│   ║                                                          ║  │
│   ║                                                          ║  │
│   ║                                                          ║  │
│   ╚══════════════════════════════════════════════════════════╝  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
 ◀── single PanelCard filling main area
```

Components: `PanelCard` (surface="card") at full available width/height.

Padding: panel itself uses `SPACE_5` internally. Exterior gap from chrome: `SPACE_5`.

### Scaffold 3 — Split view (Analytics, Conductivity)

Two coupled regions — typically primary large content + secondary narrower controls/legend. Not a drawer; both regions are equal citizens of the page.

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│   ╔════════════════════════════════════╗  ╔═══════════════════╗ │
│   ║                                    ║  ║                   ║ │
│   ║                                    ║  ║                   ║ │
│   ║        Primary region              ║  ║  Secondary        ║ │
│   ║        (e.g. large chart,          ║  ║  (controls,       ║ │
│   ║        table, conductivity map)    ║  ║   legend,         ║ │
│   ║                                    ║  ║   parameters)     ║ │
│   ║                                    ║  ║                   ║ │
│   ║                                    ║  ║                   ║ │
│   ║                                    ║  ║                   ║ │
│   ╚════════════════════════════════════╝  ╚═══════════════════╝ │
│    ◀── 70% width ──▶                         ◀── 30% width ──▶  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

Components: two `PanelCard` instances side by side. Typical split 60/40 or 70/30.

Gap between cards: `GRID_GAP` (8) or `SPACE_5` (24) for more visual separation. Choose per panel — document choice in panel's spec.

## Scaffold choice decision

```
Is the screen an overview of multiple independent things?
  → Yes: Scaffold 1 (Bento dashboard)
  → No: does the task need two coupled regions side by side?
    → Yes: Scaffold 3 (Split view)
    → No: Scaffold 2 (Single-panel full-bleed)
```

Never mix scaffolds on the same screen (e.g., "BentoGrid inside one half of a split view"). If you need a split where one half is a BentoGrid — the whole thing IS a BentoGrid, not a split. Pick one.

## Overlay vs page

Drill-down overlays (`Modal`) are NOT page scaffolds. They float above a scaffold without replacing it. The scaffold beneath remains visible (behind backdrop) and intact.

If drill-down has its own substantial content with multiple regions — it still uses Modal + whatever composition fits inside the modal card (often a mini-BentoGrid). The page scaffold below the modal is not affected.

## Rules applied

- **RULE-SURF-001..010** — surface invariants apply to each PanelCard / BentoTile in the main area
- **RULE-SPACE-002** — outer margins come from the main-area container, not the chrome
- **RULE-SPACE-006** — chrome dimensions coupled (HEADER_HEIGHT / TOOL_RAIL_WIDTH / BOTTOM_BAR_HEIGHT)
- **RULE-SURF-009** — overlay max width clamped for modals that open from scaffolds

## Common mistakes

1. **Hiding chrome on a specialized screen.** "Settings is full-screen, so let's hide ToolRail." Wrong — operator loses nav. Chrome is invariant.

2. **Scaffold 1 on a single-task screen.** Using BentoGrid for the Keithley panel because "grids look modern". If there's one task, use Scaffold 2. BentoGrid is for overviews.

3. **Split scaffold with three+ regions.** Three columns becomes unreadable at 1280px. If truly three peers — use Scaffold 1 with explicit 3×N BentoGrid.

4. **Main area touching chrome.** No padding between dashboard's first tile and TopWatchBar bottom edge. Always `SPACE_5` gap.

5. **Different scaffold per ToolRail slot transition.** Dashboard is Scaffold 1; Keithley is Scaffold 2; Analytics is Scaffold 3. The page type switches — that's fine. What's NOT fine is the chrome rearranging.

6. **Modal replacing chrome.** Modal backdrop covers TopWatchBar. Wrong — chrome stays above modal z-order (or at least beside its backdrop on the edges).

7. **Pushing main content into corner to "make room" for wide chrome.** Chrome is fixed-width. Content starts exactly at `TOOL_RAIL_WIDTH + SPACE_5` from left.

## Related patterns

- `patterns/information-hierarchy.md` — how to rank tiles by prominence within a scaffold
- `patterns/cross-surface-consistency.md` — ensuring two Scaffold-2 screens feel like siblings
- `patterns/responsive-behavior.md` — what scaffolds do at narrower viewports

## Changelog

- 2026-04-17: Initial version. Three canonical scaffolds (Bento / Single-panel / Split). Chrome invariants codified. Modal-over-scaffold z-order rules specified.
