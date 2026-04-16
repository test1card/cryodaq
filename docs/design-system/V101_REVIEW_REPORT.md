# v1.0.1 Full Review Report

## Verdict: FAIL

v1.0.1 is materially better than the pre-fix-pass state: the sampled token values now match `theme.py`, the recomputed contrast ratios in `contrast-matrix.md` are correct, WCAG baseline claims are honest, and the corpus is structurally clean (stats, fences, RULE refs). It is not ready to tag yet because three blocking problem classes remain: unqualified ghost references to non-shipped primitives/tokens, domain-invariant drift in normative examples, and a shortcut registry that is not coherent across the canonical registry, navigation guidance, ToolRail spec, and the shipped ToolRail implementation.

## Check results

| Check | Status | Notes |
|---|---|---|
| R1 Token values | PASS | Spot-check matched `theme.py`: `STATUS_OK #4a8a5e`, `STATUS_FAULT #c44545`, `ACCENT #7c8cff`, `FOREGROUND #e8eaf0`, `BACKGROUND #0d0e12`; `SPACE_0/3/6 = 0/12/32`; `FONT_BODY_SIZE/FONT_MONO_VALUE_SIZE/FONT_DISPLAY_SIZE = 14/15/32`; `HEADER_HEIGHT/TOOL_RAIL_WIDTH = 56/56`; `TRANSITION_FAST_MS/TRANSITION_BASE_MS = 150/200`. |
| R2 Contrast math | PASS | Recomputed from `theme.py` with Python: FG/BG `16.04`, FAULT/BG `3.94`, BORDER/BG `1.46`, ON_DESTRUCTIVE on FAULT `4.07`, MUTED_FOREGROUND on SECONDARY `4.72`. All match `contrast-matrix.md` within tolerance. |
| R3 WCAG claims | PASS | `wcag-baseline.md` now honestly marks 1.4.11 as `Partial`, points 1.4.3 to the contrast data, and keeps 2.1.1 / 4.1.3 as `Met`. |
| R4 Ghost refs | FAIL | Unqualified shipped-style references to `OVERLAY_MAX_WIDTH`, `ICON_SIZE_*`, and `PanelCard` remain outside historical/proposed-only contexts. |
| R5 Domain accuracy | FAIL | Normative docs still contain uppercase FSM labels and operator-facing Latin `T` / `mbar` examples. T11/T12 metrology, Keithley TSP/dual-channel, and SafetyManager authority are otherwise correct. |
| R6 Shortcuts | FAIL | `tokens/keyboard-shortcuts.md` and `accessibility/keyboard-navigation.md` agree, but `cryodaq-primitives/tool-rail.md` diverges from them and from shipped `src/cryodaq/gui/shell/tool_rail.py`. |
| R7 Motion | PASS | `tokens/motion.md` correctly acknowledges `TRANSITION_*_MS` as shipped and does not claim in body text that they are missing from `theme.py`. |
| R8 Impl paths | PASS | `phase-stepper.md`, `sensor-cell.md`, and `card.md` all point at existing current paths; `card.md` correctly states `modal_card.py` is current and `PanelCard` is proposed. |
| R9 BentoGrid | PASS | `bento-grid.md`, `breakpoints.md`, `spacing.md`, `page-scaffolds.md`, and `responsive-behavior.md` consistently treat 8 columns as canonical and explicitly note current code is 12-column. |
| R10 SR scope | PASS | Screen-reader support is in scope per AD-003; no current doc claims CryoDAQ is not screen-reader accessible. |
| R11 Statistics | PASS | Actual corpus is `71` markdown files / `21 577` lines; MANIFEST statistics match exactly. |
| R12 Code blocks | PASS | No unbalanced triple-backtick fences found outside historical audit/review files. |
| R13 RULE refs | PASS | All referenced `RULE-*` IDs resolve to definitions in `rules/*.md`. |

## Issues found

- **[V-001]** Check R4: [docs/design-system/components/modal.md:76] — proposed `OVERLAY_MAX_WIDTH` was presented as a live invariant and the API example then used `theme.OVERLAY_MAX_WIDTH` at line 93, but no such token exists in `src/cryodaq/gui/theme.py`. Severity: HIGH.
- **[V-002]** Check R4: [docs/design-system/cryodaq-primitives/tool-rail.md:160] — normative ToolRail code uses `theme.ICON_SIZE_MD`; the token family is not shipped in `theme.py`. Similar unqualified usages remain in component/primitives examples, including `ICON_SIZE_XS` in [docs/design-system/cryodaq-primitives/sensor-cell.md:307], even though `tokens/icons.md` explicitly says the size tokens are proposed and that `ICON_SIZE_XS` should not exist. Severity: HIGH.
- **[V-003]** Check R4: [docs/design-system/cryodaq-primitives/experiment-card.md:103] — `ExperimentCard` is specified as `class ExperimentCard(PanelCard)` and the surrounding anatomy/invariants also treat `PanelCard` as current, but `PanelCard` does not exist in the codebase. `components/card.md` correctly marks it as proposed; downstream docs do not. Severity: HIGH.
- **[V-004]** Check R5: [docs/design-system/tokens/colors.md:83] — status-token guidance uses uppercase `READY` as normative UI vocabulary (`safety READY`), but the codebase invariant is lowercase FSM state names only. Severity: CRITICAL.
- **[V-005]** Check R5: [docs/design-system/tokens/motion.md:127] — motion guidance uses uppercase `FAULT_LATCHED` as a normative state label, which violates the lowercase FSM-state invariant (`fault_latched`). Severity: CRITICAL.
- **[V-006]** Check R5: [docs/design-system/tokens/colors.md:89] — normative operator-facing example uses Latin `T5` (`T5 Экран 77К badge`); the same drift appears in [docs/design-system/rules/color-rules.md:500] (`T5`, `T6`). Operator-facing channel IDs must use Cyrillic `Т`. Severity: CRITICAL.
- **[V-007]** Check R5: [docs/design-system/rules/surface-rules.md:305] — a good example renders operator-facing pressure text as `1.23e-06 mbar`; operator-facing prose/examples must use `мбар`. Severity: CRITICAL.
- **[V-008]** Check R6: [docs/design-system/cryodaq-primitives/tool-rail.md:31] — ToolRail’s slot/shortcut story does not match the canonical registry in [docs/design-system/tokens/keyboard-shortcuts.md:47] and [docs/design-system/accessibility/keyboard-navigation.md:54]. The registry says `Ctrl+R` opens archive and `Ctrl+D` opens sensor diagnostics; the ToolRail spec instead centers on Dashboard/Create Experiment/Card/Diagnostics slots, and shipped `src/cryodaq/gui/shell/tool_rail.py` currently has an `instruments` slot with archive moved into the More menu. Severity: HIGH.

## Recommendation

Do not tag `design-system-v1.0.1` yet.

Fix before tag:
- Remove or explicitly qualify all non-shipped references to proposed `PanelCard`, proposed `OVERLAY_MAX_WIDTH`, and `ICON_SIZE_*` in normative docs/examples.
- Normalize domain invariants everywhere: lowercase FSM states only, Cyrillic `Т` in operator-facing channel examples, `мбар` in operator-facing pressure examples.
- Reconcile the shortcut story across `tokens/keyboard-shortcuts.md`, `accessibility/keyboard-navigation.md`, `cryodaq-primitives/tool-rail.md`, and the shipped `src/cryodaq/gui/shell/tool_rail.py`.
