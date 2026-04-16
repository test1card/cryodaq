---
title: Information Hierarchy
keywords: hierarchy, priority, emphasis, visual-weight, scan-order, prominence, critical-info, chrome
applies_to: ranking content by importance on every screen
status: canonical
references: tokens/typography.md, tokens/colors.md, rules/typography-rules.md, rules/color-rules.md
last_updated: 2026-04-17
---

# Information Hierarchy

Rules for ranking content by operator importance. Governs how a screen answers "what does the operator see first?" — purely via visual weight, not via documentation or training.

## The three tiers

Every screen has operator information split into three priority tiers. The design system applies distinct visual weight per tier.

### Tier 1 — Critical vitals (at-a-glance)

Information an operator must see without conscious effort. These are the «одновзглядовые» values that answer "is anything wrong right now?"

**Contains:**
- The 4 TopWatchBar vitals: Pressure, T-min, T-max, Heater
- Mode badge (Эксперимент / Отладка)
- Active fault indicators (STATUS_FAULT coloring on any vital)
- Active alarm count

**Visual weight:**
- `FONT_MONO_VALUE_SIZE` (15) for values — off-scale protected size
- Mode badge uses filled status color + semibold weight
- Placed in chrome (TopWatchBar) — always visible, always in the same position
- Fault transitions instant, no animation (RULE-INTER-006)

**Rule:** Tier 1 lives in chrome. Main content area never competes with chrome for Tier 1 attention.

### Tier 2 — Active task content

Information the operator is currently working with. The reason this particular screen is open.

**Contains:**
- Dashboard's active `ExperimentCard` (the experiment that's running)
- Charts showing trends relevant to the current phase
- The panel content on a Scaffold-2 screen (Keithley controls, Alarms list)
- Sensor grid with current channel readings

**Visual weight:**
- `FONT_DISPLAY_SIZE` (32) for hero KPI numbers (e.g., ExecutiveKpiTile)
- `FONT_TITLE_SIZE` (22) for major section titles (experiment name, phase name when active)
- `FOREGROUND` text color (highest contrast)
- Primary cards use `SURFACE_CARD`
- Positioned top-left quadrant or center — the first place eyes land in main area

**Rule:** Main content area top-left is claimed by Tier-2. Scan order in F-pattern reading.

### Tier 3 — Supporting context

Information that explains or accompanies the active task but is not the focus. Operator reads it when they have questions, not constantly.

**Contains:**
- Channel friendly names («Теплообменник 1» in sensor cells)
- Timestamps of last updates
- Unit labels and category captions
- System status in BottomStatusBar (`engine: connected`, FSM state, ZMQ heartbeat)
- Tooltips
- Empty-state explanations («Нет записей», «Нет активных тревог»)

**Visual weight:**
- `FONT_LABEL_SIZE` (12) or `FONT_SIZE_XS` (11)
- `MUTED_FOREGROUND` color
- Letter-spacing for UPPERCASE categories
- Placed in periphery: footer, below values, in tooltips, in BottomStatusBar

**Rule:** Tier-3 must be legible without effort (WCAG AA passes at MUTED_FOREGROUND 5.95:1 contrast) but visually subordinate.

## Tier conflict resolution

When a screen has competing signals:

1. **Tier 1 always wins.** A fault on a TopWatchBar vital overrides everything beneath.
2. **Tier 2 wins over Tier 3.** Active experiment trumps last-week's calibration reminder.
3. **Within the same tier, recency wins.** Newer is more prominent than older (per `patterns/real-time-data.md`).
4. **Active state wins over passive state.** «Running» phase is more visually prominent than «Ready» phase.

## F-pattern scan order

Latin-script readers scan content in an F-shape: top-left first, then top-right, then down-left. Place Tier-2 content accordingly:

- **Top-left quadrant of main area** — most important active task content
- **Top-right quadrant** — secondary at-a-glance info (e.g., elapsed time, mode echo)
- **Center-left strip** — chart or table body
- **Bottom strip** — actions, links, deferred info

This is why:
- ExperimentCard sits top-left on dashboard
- Mode badge sits top-right in TopWatchBar (secondary to vitals on left)
- Open-overlay link sits bottom of experiment card (deferred action)

Breaking F-pattern without reason creates operator friction.

## Visual weight toolbox

From highest weight to lowest, techniques available:

| Technique | Use case | Example |
|---|---|---|
| FONT_DISPLAY_SIZE (32) | Hero KPI number | ExecutiveKpiTile value |
| FONT_TITLE_SIZE (22) + semibold | Major section title | Experiment name, panel title |
| Active-state color (STATUS_OK, STATUS_FAULT) | Status change signal | Faulted sensor value border |
| Filled background (e.g., mode badge) | Lookup-table category | «Эксперимент» pill |
| FOREGROUND vs MUTED_FOREGROUND | Foreground/background text distinction | Active vs pending phase label |
| Uppercase + letter-spacing | Category label | ДАВЛЕНИЕ |
| Border thickness 1→2→3px | Progressive attention | Fault cell left border 3px |
| Placement in scan order | Relative importance | Top-left = primary |
| Chrome vs content | Constant vs contextual | TopWatchBar vs main-area |

Apply minimum weight sufficient. If operator is confused about what to look at, hierarchy is too flat OR two items compete. Reduce one.

## Anti-pattern: flat dashboard

When every tile uses same font size, same color, same border — operator's eye has nowhere to land. Everything "important" = nothing important.

Fix: elevate Tier-2 (ExperimentCard, primary chart) using:
- Bigger tile (higher col_span)
- FONT_DISPLAY value instead of FONT_BODY
- Subtle elevation (SURFACE_ELEVATED vs SURFACE_CARD)

Reduce Tier-3 to the minimum — don't echo the same info in five places.

## Anti-pattern: shouting dashboard

All tiles have filled status-color backgrounds, or all have thick borders, or all have animated indicators. Operator's eye gets fatigued; fault state no longer stands out (everything already screaming).

Fix: default tile state is neutral (SURFACE_CARD + 1px BORDER). Status color and emphasis are RESERVED for actual state change events.

## Practical guidance for each scaffold

### On Bento dashboard (Scaffold 1)

- One Tier-2 tile dominates (bigger, top-left). Usually `ExperimentCard`.
- Two-three Tier-2 supporting tiles (charts, KPIs).
- Tier-3 chrome: channel names, units, timestamps.
- Maximum one "alert" presentation at a time (e.g., if fault is live, mute other decorative tile borders).

### On single-panel scaffold (Scaffold 2)

- Panel title at top is Tier-2 (FONT_TITLE).
- Panel body is primarily Tier-2 (active task content).
- Panel chrome (labels, unit suffixes, helper text) is Tier-3.
- No competing Tier-2 inside the panel beyond the main task.

### On split-view (Scaffold 3)

- Primary region is Tier-2. Secondary region is Tier-2 but visually subordinate (either thinner width, or less dense content, or muted surface).
- Don't make both sides visually loud. The "main work" side is the featured side.

## Rules applied

- **RULE-TYPO-007** — off-scale protected font sizes (FONT_MONO_VALUE_SIZE, FONT_DISPLAY_SIZE) reserved for Tier 1 & 2
- **RULE-TYPO-008** — uppercase category labels in Tier-3 context only
- **RULE-COLOR-002** — status colors reserved for state-signal use, not decoration
- **RULE-COLOR-003** — max one primary accent per card / region
- **RULE-INTER-006** — fault events render instantly; this is hierarchy enforcement

## Common mistakes

1. **Equal font sizes across tiers.** Every label is 14px. Nothing stands out. Break hierarchy via font size delta.

2. **Decorative color where status color belongs.** Green tile border "just because green is nice" consumes STATUS_OK semantic. Keep status colors reserved.

3. **Tier-3 in Tier-1 slot.** Putting "last update 3s ago" in TopWatchBar instead of BottomStatusBar. Chrome hierarchy matters.

4. **Animated everything.** Every update animates in. Operator's eye can't find what changed. Animations reserved for rare events or user actions; live data snaps.

5. **Redundant Tier-2 echoes.** Experiment name on TopWatchBar AND ExperimentCard AND in breadcrumb AND in window title. Pick one canonical place; don't echo.

6. **Tier-3 louder than Tier-2.** Uppercase «ПОСЛЕДНЕЕ ОБНОВЛЕНИЕ: 14:32:15» in bold FOREGROUND color is louder than the chart data itself. Keep Tier-3 subordinate.

7. **Hero number formatted as body text.** Pressure value in FONT_BODY instead of FONT_MONO_VALUE. Reduces at-a-glance readability. Use off-scale protected font sizes.

8. **Silent Tier-1.** No visible fault indication when system is faulted; all color stays neutral. Tier-1 must communicate even in passive state (empty alarm badge is dim, not absent).

## Related patterns

- `patterns/state-visualization.md` — how state (OK / warning / fault) expresses through visual weight
- `patterns/cross-surface-consistency.md` — keeping hierarchy consistent across panels
- `patterns/real-time-data.md` — hierarchy of real-time data updates

## Changelog

- 2026-04-17: Initial version. Three-tier model (critical vitals / active task / supporting context) codified. F-pattern scan order. Visual weight toolbox. Scaffold-specific guidance.
