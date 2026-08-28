---
title: CryoDAQ Design Language
keywords: design-system, index, navigation, lookup, overview, cryodaq
enforcement: strict
priority: critical
last_updated: 2026-08-28
status: canonical
version: 4.2.0
---

# CryoDAQ Design Language

**Current design-system version:** `4.2.0`

Authoritative design specification for CryoDAQ GUI. Single source of truth for colors, typography, spacing, component anatomy, and interaction patterns. All widgets MUST conform.

## Operator-first observability

### Unreadable cooldown baseline and partial history

The cooldown history card treats an unreadable baseline as a distinct
unavailable state: valid rows show `эталон недоступен`, while the selected-row
detail explains the unavailable baseline. If some history files cannot be
parsed, the valid table remains visible with a persistent partial-history cue.
Counts use Russian 1 / 2–4 / 5+ forms. Tests cover corrupt, structurally
invalid, and mixed-history fixtures.

**Presentation examples** (state → operator-visible text → tokens):

| State | Surface | Text / cue | Tokens |
|---|---|---|---|
| History empty | card empty label | `История охлаждений пуста.` | `MUTED_FOREGROUND` |
| History unreadable, no rows | card empty label | `История недоступна (1 файл не читается).` / `(2 файла не читаются).` / `(5 файлов не читаются).` | `MUTED_FOREGROUND` |
| Baseline unreadable, no rows | card empty label | `Эталон недоступен (1 файл не читается).` | `MUTED_FOREGROUND` |
| Partial history | card persistent cue | `История неполна (1 файл не читается).` + valid table stays visible | `MUTED_FOREGROUND` |
| Baseline unreadable | verdict cell | `эталон недоступен` | `FOREGROUND` |
| No baseline | verdict cell | `нет эталона` | `MUTED_FOREGROUND` |
| Baseline unreadable | selected-row detail | `Эталонное охлаждение недоступно (1 файл не читается).` | `MUTED_FOREGROUND` |
| No baseline | selected-row detail | `Эталонное охлаждение не задано.` | `MUTED_FOREGROUND` |
| Verdict ok / degraded / unknown | badge | `Эталон: НОРМА` / `Эталон: ДЕГРАДАЦИЯ` / `Эталон: НЕТ ДАННЫХ` | fill `STATUS_OK` / `STATUS_WARNING` / `STATUS_STALE`, text `ON_DESTRUCTIVE` |

The verdict badge hides only when the feature is disabled, no baseline is
pinned, or the history is empty. An unreadable baseline or unreadable history
records resolve to the explicit `Эталон: НЕТ ДАННЫХ` chip: the badge never
hides as if no baseline were configured, and never presents an optimistic
verdict derived from an older readable record while the latest cooldown cannot
be established.

**Accessibility evidence** (measured 2026-08-18 against live `theme.py`):

- Every state carries a Russian text label; color is never the sole channel
  (RULE-A11Y-002 multi-channel redundancy): `эталон недоступен`,
  `нет эталона`, `НЕТ ДАННЫХ`, and the full-sentence count messages.
- Unreadable states resolve to the canonical stale/unavailable presentation:
  the badge keeps the `STATUS_STALE` fill while the verdict-cell text renders
  in readable `FOREGROUND` (`НЕТ ДАННЫХ` / `эталон недоступен`), never
  optimistic green/ready (root `AGENTS.md` stale/unavailable rule;
  RULE-COLOR-002 / RULE-COLOR-008).
- Measured WCAG 2.x contrast (warm_stone pack, live `theme.py`): badge fill
  `STATUS_STALE` + `ON_DESTRUCTIVE` text = 6.23:1 (AA body); `STATUS_OK` +
  `ON_DESTRUCTIVE` = 3.92:1; `STATUS_WARNING` + `ON_DESTRUCTIVE` = 2.93:1;
  verdict-cell `FOREGROUND` text on `SURFACE_CARD` = 11.51:1. The prior
  verdict-cell `STATUS_STALE` text (2.26:1) failed AA body (RULE-A11Y-003) and
  was replaced by the readable `FOREGROUND` pairing. The remaining filled-pill
  classes are the documented AA gaps in `accessibility/contrast-matrix.md`; the
  stale cue is therefore never the sole signal — the badge/cell label and the
  card's sentence messages carry the meaning.

**Performance evidence** (measured 2026-08-28):

- The card defers its first directory glob+parse to the first `showEvent`,
  keeping the read off the shell-construction path and off operators who never
  open the Архив overlay.
- The badge throttles re-reads to one glob+parse per 5 s window
  (`_READ_THROTTLE_S = 5.0`), so phase-change-driven refreshes do not re-scan
  the history directory on every call.
- Reads are bounded local-disk JSON globs of a single history directory; no
  engine round-trip.
- The offscreen GUI module `tests/gui/test_cooldown_history_card.py` (26 tests,
  including corrupt, structurally invalid, and mixed-history fixtures) runs in
  0.62 s. Bound receipt, RE-MEASURED on 2026-08-28 because this round added a
  test and a carried-over receipt would describe a different module:
  `QT_QPA_PLATFORM=offscreen` with
  `PYTHONPATH=/home/cryodaq/lanes/pr49-r-8811f48a/src`,
  `/home/cryodaq/miniforge3/envs/cryodaq-lab/bin/python -m pytest -q tests/gui/test_cooldown_history_card.py --durations=0`
  → `26 passed in 0.62s`; Python 3.14.6, PySide6 6.11.0, pytest 9.0.3,
  Ubuntu 22.04. Measured against test-file blob
  `82fdf7812bcc9a11e4bb2d8532912b2ba56830a9` and card-module blob
  `87dd114411b6fdfa7e4f661ea47428abaf0586e4`; any edit to either file
  invalidates this receipt.

The primary operating surface MUST preserve panoramic observability: current
channel values, trends, experiment context, provenance, and explicit
stale/disconnected/fault state remain discoverable even when the software did
not anticipate the condition. Summaries and prioritization may guide attention,
but they are additive and MUST NOT replace or hide the comprehensive evidence
view. A visually calmer screen is not an improvement if it reduces anomaly
discovery, provenance, or operator agency.

Every GUI change records five items in its reviewed evidence:

1. what becomes easier, clearer, faster, or safer for the operator;
2. what becomes harder, less visible, slower, or less flexible;
3. which operator workflow and safety goal justify the tradeoff;
4. how the downside is mitigated and tested; and
5. the observable condition that requires reverting or revising the change.

If the benefit is purely aesthetic while the cost reduces panoramic awareness,
unexpected-condition discovery, raw evidence, provenance, or truthful state,
the change fails the design-system gate.

This document is written for both automated tooling and human developers. Every rule has a unique ID, grep-friendly keywords, and concrete code examples.

## Design philosophy

CryoDAQ is **industrial precision instrumentation UI** for a cryogenic laboratory (АКЦ ФИАН Millimetron space telescope). It replaces LabVIEW on a lab PC running 24/7. Operators are physicists and engineers working in low-light conditions during shifts that can span 12+ hours.

**Operating principles, ranked by priority:**

1. **Informative before everything else.** The interface must make current truth,
   change, uncertainty, and the next safe action understandable at a glance.
   Sensor readings are life-critical; beauty never obscures temperature,
   pressure, safety state, provenance, or freshness.
2. **Beautiful by deliberate composition.** Beauty is a functional quality:
   purposeful hierarchy, proportion, spacing rhythm, typography, restraint,
   and a recognisable CryoDAQ visual identity reduce fatigue and make important
   differences easier to perceive. Token compliance alone is insufficient.
   A generic LabVIEW-style grid of equally weighted boxes, default controls,
   and dense chrome is a design failure even when it is technically usable.
3. **Deliberate desaturation.** Our palette is intentionally desaturated dark. This reduces eye strain during long shifts and avoids the "toy" appearance of bright neon dashboards. Sharp primary colors are signal loss to the eye.
4. **Static by default, motion only for state transition.** UI is still. Motion indicates change, never decoration. Pulsing alarms, count-up numbers, parallax — all forbidden.
5. **Consistency over cleverness.** The same concept must render the same way
   across every surface. An active phase uses the canonical ACCENT progress
   treatment everywhere; green remains reserved for safe/healthy truth. No
   per-surface variation.
6. **Discoverability via layout, not via interaction.** Everything an operator needs must be visible or at most one click away. Hover-only affordances fail in stress operations.
7. **Operator clarity and bounded autonomy.** No magic: operators can see what the system is doing and why, and may override only where the safety architecture explicitly permits it. Ordinary UI actions require an explicit operator trigger; automatic fail-closed, interlock, verified-OFF, persistence, and bounded-shutdown actions retain their independent authority.
8. **Quiet normalcy, loud exceptions.** Normal state is invisible (muted tones). Abnormal state is impossible to miss (loud red, prominent placement, persistent badge).

**Anti-philosophies explicitly rejected:**
- Material Design playfulness (ripples, elevation transitions) — we are not Google Calendar.
- Apple HIG soft-touch aesthetic (translucent blur, dock bounce) — we are not iOS.
- Enterprise SaaS gradient CTAs (Indigo→Violet buttons) — we are not Stripe.
- Gaming/cyberpunk neon (glow, chromatic aberration) — we are not a crypto dashboard.
- Generic LabVIEW-style dashboard assembly (uniform box grids, default widgets,
  dense chrome, equal visual weight everywhere) — instrumentation does not have
  to look accidental or interchangeable.

## Navigation

### Quick lookup by concern

| I need to... | Start here |
|---|---|
| Pick a color | `tokens/colors.md` |
| Pick a font size | `tokens/typography.md` |
| Apply spacing | `tokens/spacing.md` + `rules/spacing-rules.md` |
| Round a corner | `tokens/radius.md` + `rules/surface-rules.md` (RULE-SURF-002) |
| Build a card | `components/card.md` |
| Build a modal | `components/modal.md` |
| Build a button | `components/button.md` |
| Wire a destructive action | `patterns/destructive-actions.md` |
| Format a number (temperature/pressure/time) | `patterns/numeric-formatting.md` |
| Display stale data | `patterns/real-time-data.md` |
| Compose the supplemental operator briefing | `patterns/operator-display-composition.md` |
| Preserve operator evidence and reviewed workflow decisions | `patterns/operator-evidence-and-retention.md` |
| Check or update GUI v3 migration status | `GUI_MIGRATION_INVENTORY.md` |
| Check WCAG contrast | `accessibility/contrast-matrix.md` |
| Write Russian copy | `patterns/copy-voice.md` |
| Add a new token | `governance/contribution.md` |

### File structure

```
docs/design-system/
├── README.md                        # this file
├── MANIFEST.md                      # exact corpus inventory and encoded decisions
├── GUI_MIGRATION_INVENTORY.md       # auditable v3 surface migration backlog
├── CHANGELOG.md                     # design-system release history
├── VERSION                          # authoritative version marker
├── ANTI_PATTERNS.md                 # catalog of forbidden patterns with historical refs
├── DEEP_AUDIT_REPORT.md             # retained v1.0.0 audit evidence
├── adr/                             # accepted architecture/design decisions
│   ├── 001-light-theme-status-unlock.md
│   └── 002-accent-status-decoupling.md
│
├── tokens/                          # what values to use
│   ├── colors.md                    # 77 color tokens
│   ├── typography.md                # 36 typography tokens
│   ├── spacing.md                   # 9 spacing tokens
│   ├── radius.md                    # 5 radius tokens
│   ├── layout.md                    # 7 layout tokens
│   ├── chart-tokens.md              # 12 pyqtgraph-specific tokens
│   ├── motion.md                    # 3 transition tokens
│   ├── elevation.md                 # zero-shadow policy
│   ├── icons.md                     # proposed icon sizing tokens
│   ├── breakpoints.md               # viewport constraints
│   └── keyboard-shortcuts.md        # shortcut registry
│
├── rules/                           # how tokens combine
│   ├── color-rules.md
│   ├── surface-rules.md
│   ├── typography-rules.md
│   ├── spacing-rules.md
│   ├── interaction-rules.md
│   ├── data-display-rules.md
│   ├── accessibility-rules.md
│   ├── content-voice-rules.md
│   └── governance-rules.md             # GOV-001..003
│
├── components/                      # generic UI primitives
│   ├── card.md
│   ├── button.md
│   ├── input-field.md
│   ├── badge.md
│   ├── modal.md
│   ├── popover.md
│   ├── toast.md
│   ├── dialog.md
│   ├── drawer.md
│   ├── breadcrumb.md
│   ├── tab-group.md
│   ├── bento-grid.md
│   ├── bento-tile.md
│   └── chart-tile.md
│
├── cryodaq-primitives/              # domain-specific widgets
│   ├── top-watch-bar.md
│   ├── tool-rail.md
│   ├── bottom-status-bar.md
│   ├── sensor-cell.md
│   ├── phase-stepper.md
│   ├── alarm-badge.md
│   ├── tray-status.md
│   ├── alarm-panel.md
│   ├── analytics-panel.md
│   ├── archive-panel.md
│   ├── calibration-panel.md
│   ├── conductivity-panel.md
│   ├── experiment-card.md
│   ├── experiment-panel.md
│   ├── instruments-panel.md
│   ├── quick-log-block.md
│   ├── operator-log-panel.md
│   ├── operator-snapshot-components.md
│   └── keithley-panel.md
│
├── patterns/                        # multi-component compositions
│   ├── page-scaffolds.md
│   ├── information-hierarchy.md
│   ├── state-visualization.md
│   ├── real-time-data.md
│   ├── numeric-formatting.md
│   ├── cross-surface-consistency.md
│   ├── destructive-actions.md
│   ├── copy-voice.md
│   ├── operator-snapshot-presentation.md
│   ├── operator-display-composition.md
│   ├── operator-evidence-and-retention.md
│   └── responsive-behavior.md
│
├── accessibility/                   # WCAG + keyboard + motion
│   ├── wcag-baseline.md
│   ├── keyboard-navigation.md
│   ├── focus-management.md
│   ├── reduced-motion.md
│   └── contrast-matrix.md
│
└── governance/                      # how design system evolves
    ├── token-naming.md
    ├── deprecation-policy.md
    ├── testing-strategy.md
    ├── performance-budget.md
    ├── change-impact.md
    ├── versioning.md
    └── contribution.md
```

## Rule ID conventions

Every enforceable statement has a unique ID. Format: `RULE-<CATEGORY>-<3DIGIT>`.

| Category prefix | Domain | File |
|---|---|---|
| `RULE-COLOR` | Color usage, semantic lock | `rules/color-rules.md` |
| `RULE-SURF` | Surface composition, nesting, radius cascade | `rules/surface-rules.md` |
| `RULE-TYPO` | Typography, font features, text roles | `rules/typography-rules.md` |
| `RULE-SPACE` | Spacing system, symmetry, gaps | `rules/spacing-rules.md` |
| `RULE-INTER` | Interaction, cursors, focus, confirmation | `rules/interaction-rules.md` |
| `RULE-DATA` | Real-time data display, numbers, stale | `rules/data-display-rules.md` |
| `RULE-A11Y` | Accessibility, WCAG, keyboard, motion | `rules/accessibility-rules.md` |
| `RULE-COPY` | Russian UI text, terminology, tone | `rules/content-voice-rules.md` |
| `RULE-GOV` | Token naming, deprecation, versioning | `governance/*` |

Rules are numbered within category independently. `RULE-SURF-001` through `RULE-SURF-010` are the ten surface rules. Insertion of a new rule uses next available number; no gaps closed up.

## Enforcement levels

Each rule declares its enforcement level in front-matter:

- **`strict`** — violation is a bug. Must be fixed before merge. Enforced via tests where possible. Exceptions require documented `# DESIGN: RULE-XXX exception: <reason>` comment in code.
- **`recommended`** — violation is a code review discussion. Should be fixed unless there is clear reason. Not test-enforced by default.
- **`advisory`** — guidance. May adapt based on specific case. Not enforced.

Default assumption: if enforcement is not stated, the rule is `recommended`.

## Enforcement in code

Widgets applying rules mark the enforcement point with a comment:

```python
# DESIGN: RULE-SURF-001
self._content_host.setStyleSheet(
    "#modalCardContentHost { background: transparent; border: none; }"
)
```

This enables audit via `rg "DESIGN: RULE" src/`. Every enforcement comment is one rule application.

Exceptions explicit inline:

```python
# DESIGN: RULE-SURF-003 exception
# Footer needs asymmetric bottom padding for primary CTA breathing room.
# See ANTI_PATTERNS.md#footer-cta-padding-asymmetry
card_layout.setContentsMargins(SPACE_5, SPACE_5, SPACE_5, SPACE_6)
```

## Precedence when rules conflict

Rules can conflict in edge cases. When they do, this precedence applies:

1. **Safety rules** (anything referencing `safety_manager.py` or interlocks) override all others.
2. **Accessibility rules** (`RULE-A11Y-*`) override aesthetic rules.
3. **`strict` enforcement** overrides `recommended` overrides `advisory`.
4. **Newer rule** (by `last_updated`) overrides older rule within same enforcement level.
5. **More specific rule** overrides more general rule. E.g., `RULE-DATA-005` (sensor reading format) overrides `RULE-TYPO-003` (generic text formatting).

If precedence is still ambiguous, the project architect (currently Vladimir)
makes the decision.

## How LLM consumers should use this document

When given a task touching GUI:

1. **Start at this README** — locate relevant rules by lookup table.
2. **Open specific rule files** — read only sections needed for task. Files are <5KB each; loading one costs little.
3. **Check component anatomy** — if building a widget category that already exists (card/button/etc.), read corresponding `components/*.md`.
4. **Check CryoDAQ primitives** — if building something domain-specific (sensor display, alarm, Keithley control), check `cryodaq-primitives/*.md`.
5. **Apply enforcement markers** — when code implements a rule, add `# DESIGN: RULE-XXX` comment.
6. **Check ANTI_PATTERNS.md** — confirm the approach isn't historically forbidden.

For non-safety presentation behavior, start from the reviewed rule rather than
copying incidental legacy code. For software truth, safety authority, hardware
evidence, or a conflict with root `AGENTS.md`, inspect the reachable code and
tests and follow the higher-precedence repository contract; repair stale
design-system prose in the same reviewed slice.

## Token count summary

From `src/cryodaq/gui/theme.py` inventory (v3.0.0, 142 exported uppercase constants):

| Category | Count | File |
|---|---:|---|
| Colors | 77 | `tokens/colors.md` |
| Typography | 36 | `tokens/typography.md` |
| Spacing | 9 | `tokens/spacing.md` |
| Radius | 5 | `tokens/radius.md` |
| Layout | 7 | `tokens/layout.md` |
| Motion (transitions) | 3 | `tokens/motion.md` |
| Quantity codes | 4 | `tokens/chart-tokens.md` |
| Corner shape | 1 | `tokens/radius.md` |
| Chart-specific | (subset of colors) | `tokens/chart-tokens.md` |

## Related project docs

- `docs/architecture.md` — process model, subsystem map, key invariants
- `src/cryodaq/gui/theme.py` — runtime token constant table (authoritative source for VALUES; this document is authoritative source for USAGE)

## Changelog

- 2026-07-20: Released v4.0.3: removed remaining safety-green collisions from
  running/authorized, conductivity settling, and shift-handover presentation;
  normalized new operator-facing attention wording to the single caution rung
  while preserving legacy `warning` as an accepted source value.
- 2026-07-17: Released v4.0.2: theme selection is validated and atomically
  deferred to the next ordinary launch without touching acquisition; tray
  health now also requires fresh data and known reporting truth, and incomplete
  launcher shutdown remains visible and locked until exact owners settle.
- 2026-07-17: Released v4.0.1: corrected shipped emergency, calibration,
  tray, alarm, responsive, TopWatchBar, experiment-identity, and theme-selection
  contracts against current runtime behavior; open code migrations remain
  explicit rather than being described as complete.
- 2026-07-15: Released v4.0.0: restored panoramic observability as the
  mandatory primary-surface contract, made the shift briefing additive, and
  added an explicit operator/safety tradeoff gate for every GUI change.
- 2026-07-15: Released v3.0.2: aligned the ToolRail home destination and
  tooltip with the Primary Operator Display term «Сводка смены».
- 2026-07-15: Released v3.0.1: completed the software POD home cutover with
  one visible truth owner, consolidated provenance, and quiet-normal cards;
  physical, DPI/NVDA, long-session, and operator evidence remain open.
- 2026-07-14: Released v3.0.0: made informative and intentionally beautiful
  composition jointly mandatory across the complete GUI corpus, and explicitly
  rejected generic LabVIEW-style dashboard assembly. Safety truth, legibility,
  provenance, freshness, uncertainty, and the next safe action retain
  precedence over aesthetics.
- 2026-07-14: Released v2.0.0 for the breaking descriptor-qualified
  `InstrumentsPanel` ingress contract; tokens and visual anatomy are unchanged.
- 2026-07-11: Added the F36 snapshot and Primary Operator Display entry points;
  reconciled the root tree and runtime-token inventory with the v1.2.0 corpus.
- 2026-04-17: Initial version. Written during Phase I.1 after Vladimir visual review revealed cross-surface inconsistency. Based on real `theme.py` token inventory (126 tokens across 5 categories at v1.0.0; expanded to 139 tokens in v1.0.1).
