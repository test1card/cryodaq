---
title: Design System Manifest
status: canonical
last_updated: 2026-04-17
---

# CryoDAQ Design System — Manifest

**Generated:** 2026-04-17
**Session:** Phase UI-1 v2 design system creation
**Scope:** Batches 1-6 complete. Full design system v1.0.1 — foundation tokens + enforcement rules + generic components + CryoDAQ domain primitives + cross-surface patterns + accessibility commitments + governance policies.

## Structure

```
design-system/
├── README.md                           # Entry point, navigation, precedence rules
├── MANIFEST.md                         # This file
├── ANTI_PATTERNS.md                    # 40+ forbidden patterns with historical refs
│
├── tokens/                             # Foundation: 11 files, what exists and why
│   ├── colors.md                       # 71 color tokens across 9 namespaces
│   ├── typography.md                   # 36 typography tokens, Fira fonts, Cyrillic rules
│   ├── spacing.md                      # 9 spacing tokens + semantic aliases
│   ├── radius.md                       # 5 radius tokens, tight scale
│   ├── layout.md                       # 5 layout tokens, coupled constants
│   ├── chart-tokens.md                 # pyqtgraph integration
│   ├── motion.md                       # PROPOSED — duration/easing tokens
│   ├── elevation.md                    # zero-shadow policy + z-index levels
│   ├── icons.md                        # Lucide bundle + emoji prohibition
│   ├── breakpoints.md                  # desktop-only responsive
│   └── keyboard-shortcuts.md           # PROPOSED — shortcut registry
│
├── rules/                              # Enforcement: 9 files, 79 rules with code examples
│   ├── color-rules.md                  # COLOR-001..010
│   ├── surface-rules.md                # SURF-001..010
│   ├── typography-rules.md             # TYPO-001..010
│   ├── spacing-rules.md                # SPACE-001..008
│   ├── interaction-rules.md            # INTER-001..012
│   ├── data-display-rules.md           # DATA-001..010
│   ├── accessibility-rules.md          # A11Y-001..008
│   ├── content-voice-rules.md          # COPY-001..008
│   └── governance-rules.md             # GOV-001..003 (thin pointers to governance/*)
│
└── components/                         # Generic primitives: 14 files, anatomy + invariants + code
    ├── card.md                         # generic rounded container
    ├── button.md                       # secondary/ghost/destructive/icon/hold-confirm
    ├── input-field.md                  # text/numeric/search/password + validation
    ├── badge.md                        # filled/outline/count/inline/phase
    ├── bento-grid.md                   # 8-column layout engine
    ├── bento-tile.md                   # grid child primitive + KPI/DataDense/Live subclasses
    ├── modal.md                        # centered overlay with backdrop
    ├── popover.md                      # anchored floating panel
    ├── dialog.md                       # title/body/actions Q&A
    ├── drawer.md                       # edge-attached sliding panel
    ├── toast.md                        # transient notifications
    ├── breadcrumb.md                   # drill-down navigation trail
    ├── tab-group.md                    # sibling view switcher
    └── chart-tile.md                   # BentoTile + pyqtgraph variant

└── cryodaq-primitives/                 # Domain-specific: 9 files, Phase II implementation guides
    ├── top-watch-bar.md                # 4 vitals + mode badge (B.4 + B.4.5.2)
    ├── tool-rail.md                    # left icon nav (Phase 0)
    ├── bottom-status-bar.md            # system status strip
    ├── sensor-cell.md                  # single-channel cell (B.3)
    ├── phase-stepper.md                # 6-phase stepper (B.5/B.5.5/B.5.6)
    ├── alarm-badge.md                  # header alarm indicator
    ├── experiment-card.md              # active-experiment dashboard tile + overlay
    ├── quick-log-block.md              # inline operator log widget
    └── keithley-panel.md               # dual-channel SMU control

└── patterns/                           # Cross-surface patterns: 9 files, composition recipes
    ├── page-scaffolds.md               # 3 canonical scaffolds (Bento / Single-panel / Split)
    ├── information-hierarchy.md        # 3-tier model + F-pattern scan order
    ├── cross-surface-consistency.md    # 5 consistency dimensions + two-surface test
    ├── responsive-behavior.md          # desktop-only, 3 viewport bands, what adapts
    ├── state-visualization.md          # 6-state vocabulary + two-channel rule
    ├── real-time-data.md               # coalescing, stale detection, update pipeline
    ├── numeric-formatting.md           # per-quantity format reference + tabular-nums
    ├── destructive-actions.md          # 3-severity classification + two-layer pattern
    └── copy-voice.md                   # Russian vocabulary lexicon + imperative/descriptive

└── accessibility/                      # Accessibility commitments: 5 files
    ├── wcag-baseline.md                # WCAG 2.2 AA target, scope, per-criterion commitment
    ├── contrast-matrix.md              # measured ratios all tokens vs all surfaces
    ├── keyboard-navigation.md          # tab order, shortcut registry, focus trap
    ├── focus-management.md             # 2px ACCENT ring, restoration, autofocus policy
    └── reduced-motion.md               # MotionPolicy, prefers-reduced-motion, HoldConfirm exception

└── governance/                         # System self-governance: 6 files
    ├── token-naming.md                 # closes RULE-GOV-001, naming conventions + prefix registry
    ├── deprecation-policy.md           # closes RULE-GOV-003, lifecycle + STONE_* case
    ├── versioning.md                   # SemVer 2.0.0 with design-system breaking definitions
    ├── testing-strategy.md             # 3 enforcement layers (lint / Codex / manual) + tooling
    ├── performance-budget.md           # 60 FPS / 16ms / ≤2Hz / 100ms input budget
    └── contribution.md                 # proposal process, 6 types, review gates
```

## Statistics

- **67 files, ~20 906 lines, ~1064 KB markdown**
- **79 rule IDs** across 9 rule categories (Batches 1+2+6)
- **14 generic components** specified (Batch 3)
- **9 CryoDAQ domain primitives** specified (Batch 4)
- **9 cross-surface patterns** specified (Batch 5)
- **5 accessibility documents** (Batch 6)
- **6 governance documents** (Batch 6)
- **74 color tokens** inventoried from theme.py (includes RING + SUCCESS_400 / WARNING_400 / DANGER_400 chart series additions; Phase III.A added SELECTION_BG + FOCUS_RING neutral-interaction tokens to every bundled theme pack — see `adr/002-accent-status-decoupling.md`)
- **141 tokens total** (colors 76 + typography 36 + spacing 9 + layout 7 + radius 5 + motion 3 + quantity 4 + corner-shape 1)

## Cross-reference health

- All RULE-COLOR, RULE-SURF, RULE-TYPO, RULE-SPACE, RULE-INTER, RULE-DATA, RULE-A11Y, RULE-COPY, RULE-GOV references **satisfied** (no forward refs)
- All code blocks balanced
- All hex values either reference theme.py tokens, appear in bad-example context, or are documented exceptions (e.g. `#a53838` DESTRUCTIVE_PRESSED placeholder tracked for promotion to token)
- Latin T in channel-ID context appears only in lint-pattern documentation (`testing-strategy.md`) and explicit bad-example counterexamples

## Key design decisions encoded

1. **Desaturated industrial dark palette** — NOT Tailwind-like. STATUS_OK=#4a8a5e forest green, not green-500.
2. **ACCENT is UI-activation affordance** (Phase III.A decoupling; prior: «locked to focus/selection only»). Primary button background, active tab underline, active ToolRail slot indicator, progress chunks for user-triggered tasks, focused-input border. NOT a status (use STATUS_*), NOT a phase indicator (phase active = STATUS_OK border via phase_stepper), NOT a hover state (use MUTED background). `SELECTION_BG` / `FOCUS_RING` (Phase III.A neutrals) carry selection / focus when accent bleed would collide with chrome. See `adr/002-accent-status-decoupling.md`.
3. **STONE_* legacy tokens — read-only in new code** — zero breaking change policy.
4. **3 surface brightness levels max** — BACKGROUND, CARD, SECONDARY. No 4th level.
5. **Radius scale tight** — NONE=0, SM=4, MD=6, LG=8, FULL=9999. No RADIUS_XL.
6. **Zero-shadow policy** — single exception for modal cards.
7. **STATUS_OK (4.67:1) passes WCAG AA body; STATUS_FAULT (3.94:1), STATUS_INFO (4.31:1), STATUS_STALE (2.94:1) FAIL** — measured.
8. **HEADER_HEIGHT == TOOL_RAIL_WIDTH = 56** — coupled constant.
9. **Off-scale font sizes 15 and 32 protected** — FONT_MONO_VALUE_SIZE and FONT_DISPLAY_SIZE.
10. **Fira fonts bundled via QFontDatabase** — Mac/Ubuntu fallback otherwise.
11. **Cyrillic Т (U+0422) in user-facing temperature channel IDs** — never Latin T.
12. **No emoji in UI chrome** — per Phase 0 decision after bell emoji removal.
13. **Point decimal, space thousands** — technical consistency over pure Russian convention.
14. **Filled-ACCENT primary button is canonical** (Phase III.A; prior decision «no filled-ACCENT primary button» is retired — it was a consequence of ACCENT-as-focus-only which collapsed primary actions onto STATUS_OK and caused the safety-green UI collision ADR 002 fixes). CryoDAQ primary actions («Сохранить», «Экспорт CSV», «Применить», etc) now render filled `ACCENT` + `ON_ACCENT`. Destructive actions continue to use STATUS_FAULT + HoldConfirm (never filled ACCENT).
15. **Destructive actions never single-click** — Hold-confirm OR modal confirmation (RULE-INTER-004).
16. **Toasts never for faults** — faults use Dialog or persistent banner (RULE-INTER-006).
17. **Pressure plots mandatory log-scale** — RULE-DATA-008.
18. **Card RADIUS_LG (8) > Tile RADIUS_MD (6) > Input RADIUS_SM (4)** — hierarchy cascade.
19. **Modal close button in single-row header**, AlignVCenter with breadcrumb — NOT own row, NOT absolute-positioned (Phase I.1 regression avoided).
20. **BentoTile only inside BentoGrid** — standalone = Card instead.
21. **TopWatchBar T-min/T-max locked to Т11/Т12** — the only positionally fixed reference channels (physically immovable on the second stage / nitrogen plate; cannot be relocated without dismantling the rheostat). All temperature channels are metrologically calibrated, but other channels may change position between experiments, disqualifying them as fixed quantitative reference points.
22. **Mode badge (Эксперимент / Отладка)** always visible — operator always knows whether actions have real-world effect vs debug-only.
23. **ToolRail is icon-only + tooltip mandatory** — 9 slots, Ctrl+[1-9] shortcuts, Ctrl+L alias for Journal.
24. **FSM states displayed lowercase** in BottomStatusBar — `safe_off`, `fault_latched` — per absolute codebase rule.
25. **SensorCell value stays FOREGROUND in fault** — uses border + icon for fault signal (avoids RULE-A11Y-003 contrast fail on STATUS_FAULT body text).
26. **Active phase uses STATUS_OK, not ACCENT** — corrected Phase 0 violet violation. Active phase IS a status, not a selection.
27. **PhaseStepper compact=True for dashboard inline; full stepper in overlay** — per Phase B.5.6.
28. **AlarmBadge uses Lucide bell, never emoji** — per Phase 0 decision after bell emoji removal.
29. **AlarmBadge empty state stays visible (dim)** — operator situational awareness: must see system is watching.
30. **Keithley dual-channel always visible** — both smua and smub as «Канал А» / «Канал B»; single-channel view is a violation.
31. **Keithley TSP-only, not SCPI** — absolute codebase invariant propagated into UI spec.
32. **Enable-output requires Dialog confirmation; disable is safe direction** — destructive-ness is directional.
33. **SafetyManager is the only output authority** — UI requests, never directly commands hardware on/off.
34. **Experiment abort = HoldConfirmButton + Dialog** — two layers of protection.
35. **Three scaffolds only** — Bento dashboard / Single-panel full-bleed / Split view. No mixing within one screen.
36. **Chrome invariant across scaffolds** — TopWatchBar + ToolRail + BottomStatusBar always visible; only main content area changes.
37. **3-tier info hierarchy** — critical vitals (chrome) / active task (main area top-left) / supporting context (periphery).
38. **F-pattern scan order** — top-left most important, top-right secondary, bottom deferred.
39. **Two-channel status signaling** — color never alone; pair with shape (border/icon) or text per RULE-A11Y-002.
40. **Six-state vocabulary** — ok/caution/warning/fault/stale/disconnected. No gradients, no sub-states.
41. **2 Hz UI update cap** — regardless of engine sample rate; coalesce via QTimer per `patterns/real-time-data.md`.
42. **Stale ≠ hidden** — stale values keep last-known + dim color + tooltip explaining freshness age.
43. **Initial-empty ≠ stale** — «Ожидание первого измерения» (TEXT_DISABLED) vs «Устарело NN с» (STATUS_STALE).
44. **Desktop-only scope** — no phone, no tablet, no touch. Minimum 1280px width; chrome fixed regardless.
45. **BentoGrid stays 8 columns at all viewports** — no responsive collapse; tiles keep their col_span.
46. **Two-layer protection for safety-critical destructive** — HoldConfirmButton (1s gesture) + Dialog (cognitive confirmation).
47. **Directional safety in toggles** — enable destructive (confirm), disable safe (no confirm).
48. **No «Don't show again» checkboxes** — creates state divergence + training regressions. Fix root cause instead.
49. **Ctrl+Shift+X global emergency stop** — one exception to «shortcut without visible affordance» rule.
50. **Canonical vocabulary table** — same concept = same word across all panels (see `patterns/copy-voice.md`).
51. **Subsystem names stay Latin** — Engine, ZMQ, Safety, Keithley. Domain vocabulary exception.
52. **FSM states displayed lowercase as-is** — `safe_off`, `fault_latched`. Operators learn from logs; don't translate.

Batch 6 — accessibility + governance:

53. **WCAG 2.2 Level AA target** — AA floor with documented exceptions; AAA opportunistic not committed.
54. **Out-of-scope AA criteria explicit** — 1.2.x (media), 1.4.4 (resize text beyond OS DPI), 2.5.5 (touch target) — not applicable for desktop-only industrial context.
55. **Contrast matrix is the source of truth** — every token/surface combination measured. STATUS_FAULT 3.94:1 body text fails AA → border+icon carry signal, value stays FOREGROUND.
56. **2px ACCENT focus ring is canonical** — uniform across all focusable widgets; selection chrome (3px left-bar) + focus ring (2px outer border) coexist, not collapsed.
57. **No single-key shortcuts anywhere** — every shortcut uses Ctrl / Alt / Shift modifier. Function keys (F5, F11) OK as non-text-input.
58. **Focus restoration mandatory** on overlay close — return to opener, not document start.
59. **Destructive Dialog default-focus = Cancel** — operator Enter muscle-memory dismisses safely.
60. **Shift+Enter keyboard alternative for HoldConfirmButton** — full keyboard accessibility without requiring held-key.
61. **Reduced motion respect via MotionPolicy** — centralized helper; duration=0 under reduce. HoldConfirm becomes discrete-step progress (safety preserved).
62. **Design system stays flat tokens through v1.x** — three-layer (primitive→semantic→component) is v2.0 target per UXPM recommendation, not current.
63. **STONE_* deprecated in v1.0.0, removed in v2.0.0** — ~15 call sites being migrated at each panel's next refactor.
64. **SemVer independent from CryoDAQ package version** — design system evolves at its own cadence; CHANGELOG cross-references.
65. **Architect is singular approval gate for v1.x** — Claude drafts + Codex audits + Vladimir approves + Claude Code implements. No self-approval.
66. **ACCENT ≠ STATUS_OK — Phase III.A decoupling** — per `adr/002-accent-status-decoupling.md`. Primary buttons, mode badges, progress chunks, active tab indicators use ACCENT (UI activation). STATUS_OK reserved for safety / health / channel-OK indicators. `SELECTION_BG` + `FOCUS_RING` added as neutral interaction tokens. Per-theme ACCENT recalibrated to warm-neutral (11 themes; `default_cool` indigo preserved as historical baseline).

## Status

**Design system v1.0.1 — complete.** All 67 files, 79 rules, 139 tokens, 6 batches.

## Deployment to repo

This archive should be committed to `docs/design-system/` in the CryoDAQ repo via single Codex commit. After commit:

1. Update `CLAUDE.md` to reference `docs/design-system/README.md` as authoritative design-language source.
2. Phase I.1 ModalCard code should be retrofitted with `# DESIGN: RULE-XXX` enforcement markers per rules defined here.
3. Every Phase II spec prompt for Codex should include: "BEFORE coding, read: docs/design-system/README.md, docs/design-system/rules/<relevant>.md, docs/design-system/components/<relevant>.md per task."
4. Governance follow-up: add `DESTRUCTIVE_PRESSED` token to theme.py (currently `#a53838` placeholder in button.md Variant 3).
