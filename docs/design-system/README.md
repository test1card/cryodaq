---
title: CryoDAQ Design Language
keywords: design-system, index, navigation, lookup, overview, cryodaq
enforcement: strict
priority: critical
last_updated: 2026-04-17
status: canonical
---

# CryoDAQ Design Language

Authoritative design specification for CryoDAQ GUI. Single source of truth for colors, typography, spacing, component anatomy, and interaction patterns. All widgets MUST conform.

This document is written for LLM consumers (Claude Code, Codex CLI) and human developers. Every rule has a unique ID, grep-friendly keywords, and concrete code examples.

## Design philosophy

CryoDAQ is **industrial precision instrumentation UI** for a cryogenic laboratory (АКЦ ФИАН Millimetron space telescope). It replaces LabVIEW on a lab PC running 24/7. Operators are physicists and engineers working in low-light conditions during shifts that can span 12+ hours.

**Operating principles, ranked by priority:**

1. **Data legibility over decoration.** Sensor readings are life-critical. Nothing visual may impair reading of temperature, pressure, or safety state. No animation on data flow, no decoration near readouts.
2. **Deliberate desaturation.** Our palette is intentionally desaturated dark. This reduces eye strain during long shifts and avoids the "toy" appearance of bright neon dashboards. Sharp primary colors are signal loss to the eye.
3. **Static by default, motion only for state transition.** UI is still. Motion indicates change, never decoration. Pulsing alarms, count-up numbers, parallax — all forbidden.
4. **Consistency over cleverness.** The same concept must render the same way across every surface. If "active phase" is green border in dashboard, it must be green border in overlay. No per-surface variation.
5. **Discoverability via layout, not via interaction.** Everything an operator needs must be visible or at most one click away. Hover-only affordances fail in stress operations.
6. **Operator autonomy.** No magic. Operators can see what the system is doing, why, and override if needed. No actions happen without explicit operator trigger.
7. **Quiet normalcy, loud exceptions.** Normal state is invisible (muted tones). Abnormal state is impossible to miss (loud red, prominent placement, persistent badge).

**Anti-philosophies explicitly rejected:**
- Material Design playfulness (ripples, elevation transitions) — we are not Google Calendar.
- Apple HIG soft-touch aesthetic (translucent blur, dock bounce) — we are not iOS.
- Enterprise SaaS gradient CTAs (Indigo→Violet buttons) — we are not Stripe.
- Gaming/cyberpunk neon (glow, chromatic aberration) — we are not a crypto dashboard.

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
| Check WCAG contrast | `accessibility/contrast-matrix.md` |
| Write Russian copy | `patterns/copy-voice.md` |
| Add a new token | `governance/contribution.md` |

### File structure

```
docs/design-system/
├── README.md                        # this file
├── ANTI_PATTERNS.md                 # catalog of forbidden patterns with historical refs
│
├── tokens/                          # what values to use
│   ├── colors.md                    # 71 color tokens
│   ├── typography.md                # 36 typography tokens
│   ├── spacing.md                   # 9 spacing tokens
│   ├── radius.md                    # 5 radius tokens
│   ├── layout.md                    # 5 layout tokens
│   ├── chart-tokens.md              # 12 pyqtgraph-specific tokens
│   ├── motion.md                    # proposed motion tokens (not in theme.py yet)
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
│   ├── experiment-card.md
│   ├── quick-log-block.md
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

If precedence still ambiguous, decision is Vladimir's.

## How LLM consumers should use this document

When given a task touching GUI:

1. **Start at this README** — locate relevant rules by lookup table.
2. **Open specific rule files** — read only sections needed for task. Files are <5KB each; loading one costs little.
3. **Check component anatomy** — if building a widget category that already exists (card/button/etc.), read corresponding `components/*.md`.
4. **Check CryoDAQ primitives** — if building something domain-specific (sensor display, alarm, Keithley control), check `cryodaq-primitives/*.md`.
5. **Apply enforcement markers** — when code implements a rule, add `# DESIGN: RULE-XXX` comment.
6. **Check ANTI_PATTERNS.md** — confirm the approach isn't historically forbidden.

When in doubt: **read the rule, not my code**. If my code contradicts a rule, code is wrong.

## Token count summary

From `src/cryodaq/gui/theme.py` inventory (commit 53e258c):

| Category | Count | File |
|---|---:|---|
| Colors | 71 | `tokens/colors.md` |
| Typography | 36 | `tokens/typography.md` |
| Spacing | 9 | `tokens/spacing.md` |
| Radius | 5 | `tokens/radius.md` |
| Layout | 5 | `tokens/layout.md` |
| Chart-specific | (subset of colors) | `tokens/chart-tokens.md` |

## Related project docs

- `docs/phase-ui-1/ui_refactor_context.md` — UI refactor pain points (P1-P7) and preserve features (K1-K7)
- `docs/phase-ui-1/phase_ui_v2_roadmap.md` — Phase I/II/III execution plan
- `docs/legacy-inventory/*.md` — pre-refactor widget inventory (for Phase II reference)
- `CLAUDE.md` — project overview, build commands, key rules
- `src/cryodaq/gui/theme.py` — runtime token constant table (authoritative source for VALUES; this document is authoritative source for USAGE)

## Changelog

- 2026-04-17: Initial version. Written during Phase I.1 after Vladimir visual review revealed cross-surface inconsistency. Based on real `theme.py` token inventory (126 tokens across 5 categories).
