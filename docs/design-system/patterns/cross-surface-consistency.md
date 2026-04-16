---
title: Cross-Surface Consistency
keywords: consistency, cross-surface, uniformity, siblings, visual-coherence, design-language, predictability
applies_to: ensuring panels, overlays, and tiles feel like parts of the same product
status: canonical
references: all tokens, all rules, all components
last_updated: 2026-04-17
---

# Cross-Surface Consistency

Rules for making different panels, overlays, and tiles feel like parts of the same product. Addresses the pain point that triggered this entire design system: after Phase 0 dashboard + Phase I.1 experiment overlay + recent tool rail panels, surfaces drifted visually (different borders, different paddings, different radii, different status colors) because each was built independently.

## The source of drift

Drift happens when:
- Each spec allows small "looks fine" choices — SPACE_3 here, SPACE_4 there, RADIUS_MD here, RADIUS_SM there
- Colors are chosen by approximate semantic — "green-ish for OK" but different greens per panel
- Padding is tuned to "what looks right in isolation" without cross-panel test
- New widgets invent their own patterns instead of reusing the ones from adjacent panels

Each local decision is innocent. Accumulated across ten panels, the product reads as ten different tools stitched together.

## The cure

**Every visual decision comes from tokens + rules + components.** Not from judgment. Not from "what looks right". Token lookup tables and rule numbers are the non-negotiable source of truth.

If a panel needs something the tokens don't support, the response is either:
- Use the nearest token and accept the minor compromise, OR
- Propose a new token through governance (Batch 6) — not add an ad-hoc value

There is no third option.

## Five consistency dimensions

### 1. Surface dimensions

Same card shape across panels. Every panel uses `RADIUS_LG` (8). Every tile uses `RADIUS_MD` (6). Every input uses `RADIUS_SM` (4). Period.

When Panel A has RADIUS 8 cards and Panel B has RADIUS 10 cards — the panels feel like they come from different designers even if the operator can't name why. The cascade (Card > Tile > Input) must be identical everywhere.

### 2. Spacing

Padding `SPACE_5` (24) inside cards. `GRID_GAP` (8) between tiles. `SPACE_2` (8) inline gap between related items. `SPACE_1` (4) label-to-value gap.

When Panel A has 20px card padding and Panel B has 24px — visual rhythm breaks. Even if both are fine in isolation, looking at them side by side exposes the inconsistency.

### 3. Typography

Category labels UPPERCASE + letter-spacing 0.05em. Hero values FONT_MONO_VALUE (15). Titles FONT_TITLE (22). Labels FONT_LABEL_SIZE (12).

The easiest drift: one panel uses «Температуры» sentence case as a section header; another uses «ТЕМПЕРАТУРЫ» uppercase. They look like different features. Fix: RULE-TYPO-008 says UPPERCASE for category labels, always.

### 4. Color semantics

STATUS_OK means healthy. STATUS_WARNING means attention. STATUS_FAULT means problem. ACCENT means focus/selection. These are LOCKED per RULE-COLOR-002 and RULE-COLOR-004.

When one panel uses blue for "OK active" and another uses green — operators build incorrect mental model. When ACCENT is reserved for focus here but used as brand accent there — the focus ring loses its meaning.

### 5. Interaction conventions

Destructive actions require confirmation (hold-confirm or dialog). Escape dismisses overlays. Enter submits. Tab navigates forward. Ctrl+[1-9] opens ToolRail slots. These are product-wide conventions, not per-panel choices.

When Panel A dismisses on Escape but Panel B doesn't — operator hesitates ("did it save?"). Consistency removes hesitation.

## The two-surface test

Before shipping any new panel, perform the **two-surface test**:

1. Open the new panel side by side with an existing panel (e.g., Dashboard + new Analytics panel).
2. Look for visual discontinuities: "this thing looks smaller/bigger/different" in:
   - Border thickness
   - Corner radius
   - Padding inside cards
   - Label font weight / size
   - Status color on similar states
   - Button heights
3. If any discontinuity exists AND it cannot be traced to a deliberate token/rule difference — fix the new panel to match the existing one.

"Deliberate token difference" = e.g., compact variant explicitly using `ROW_HEIGHT = 32` not `36`. Not allowed: "I thought 28 looked nicer here".

## Sibling-panel inheritance

Panels that do similar work should look similar:

- **Dashboard Scaffold 1 screens** (Dashboard, Archive) feel like siblings: BentoGrid, same tile densities, same padding.
- **Single-panel Scaffold 2 screens** (Keithley, Alarms, Journal, Settings) feel like siblings: PanelCard, same title treatment, same padding, same scroll behavior.
- **Split-view Scaffold 3 screens** (Analytics, Conductivity) feel like siblings: 70/30 split (or matching ratio), same gap between panes.

Within a family, first look at adjacent siblings before making new decisions.

## Component reuse as consistency mechanism

Every re-implementation of the same pattern is a drift opportunity. If two panels both have a "numeric input with unit", reach for the shared `InputField` with `unit="K"` — don't build a local variant per panel.

Phase II task: identify legacy panels that duplicate the composable primitive patterns and replace with shared components. Each such replacement reduces drift surface.

## Cross-checking via cold reading

Operator cold-reading test — does a panel the operator has never seen work the way they expect based on panels they have?

- They press Escape → does this new panel dismiss? (It should, if it's an overlay.)
- They click a faulted sensor cell → does it show details? (Yes, because they did that in dashboard.)
- They see a filled amber pill → do they know it means "warning"? (Yes, because that's what it means everywhere.)
- They scan for the mode badge → is it in TopWatchBar top-right? (Yes, same place always.)

Every "no" is a consistency failure. Every "yes" saves training time and reduces operator errors.

## Where drift is ACCEPTABLE

Consistency has one escape hatch: documented intentional divergence.

Examples:
- **BottomStatusBar height = 28** deliberately != TopWatchBar height = 56. Documented in `tokens/layout.md`.
- **Pressure in log scale** in charts; temperatures in linear. Documented in `rules/data-display-rules.md`.
- **Active PhaseStepper phase uses STATUS_OK**; active tab in TabGroup uses ACCENT. Both are "active" but different semantic — phase IS healthy running; tab IS selected. Documented in respective component specs.

These divergences are legitimate because they express distinct meanings. The difference has to carry actual information.

## Rules applied

- **All RULE-* refs** — the rules are the consistency mechanism; cross-surface consistency IS the rule system being enforced
- **RULE-COLOR-002** — status colors locked → identical status semantics everywhere
- **RULE-SURF-006** — radius cascade → identical card-tile-input shape relationship everywhere
- **RULE-INTER-002, RULE-INTER-008** — interaction conventions (Escape, tooltip) → identical keyboard and hover behavior everywhere

## Common mistakes

1. **Building a new panel in isolation.** "Let me finish the panel first, then I'll check consistency." Wrong order. Consistency check happens at spec time, not at review time. Pick tokens BEFORE writing code.

2. **Copying from legacy panels.** Legacy panels predate the design system. Copying them propagates drift. Always use the new tokens + rules, not legacy stylesheets.

3. **"This panel is special, rules don't apply."** No panel is special. If a panel truly needs a new token, propose one through governance. 95% of "special" panels can use existing tokens.

4. **Tuning padding by pixel-pushing.** "I'll use 20px here because 24 looks too loose." Wrong — 24 is `SPACE_5`. 20 has no token. Use `SPACE_5` OR document why this panel needs `SPACE_4` = 16.

5. **Per-panel status color shades.** "This panel's warnings should be a brighter amber." No. STATUS_WARNING is STATUS_WARNING. Brightness is a token, not a local choice.

6. **Different empty states.** «Нет записей» in one panel, «No data» in another, «Пусто» in a third. Pick one Russian idiom and use it everywhere. Standardize via `patterns/copy-voice.md`.

7. **Inconsistent close button positions.** Modal A has close in header right; Modal B has close in footer center. Operator's hand develops muscle memory for whichever pattern they see first; the inconsistent modal feels broken.

8. **Shifting the ToolRail slot meaning.** Slot 5 is «Аналитика» on dashboard, but opens Keithley in experiment overlay. Never — slots are global and stable.

## Related patterns

- `patterns/page-scaffolds.md` — three scaffolds provide the first layer of consistency
- `patterns/information-hierarchy.md` — tier system keeps visual prominence rules consistent
- `patterns/copy-voice.md` — consistent operator vocabulary across panels

## Changelog

- 2026-04-17: Initial version. Five consistency dimensions (surface, spacing, typography, color, interaction). Two-surface test. Sibling-panel inheritance. Documented escape hatch for deliberate divergences.
