# Final Review Report — Design System v1.0.0

## Executive summary

**Overall health:** HAS_ISSUES

Design-system v1.0.0 is usable as a design direction reference, but not yet trustworthy as a single source of truth for Phase II implementation. The weakest points are not philosophical; they are traceability and truthfulness defects. The three blockers are: broken accessibility math and resulting false WCAG claim, component/pattern specs that still compose around obsolete or nonexistent primitives, and governance/token registries that no longer describe the shipped `theme.py` and shortcut reality.

This does **not** require a redesign. It requires a targeted v1.0.1 doc repair pass. The codebase ground truth is stable enough: `src/cryodaq/gui/theme.py`, current dashboard widgets, `config/channels.yaml`, and `config/safety.yaml` make the intended reality readable. The design-system docs need to catch up to that reality and stop mixing current-state guidance with future-state proposals without labeling.

- Total issues reviewed: 31
- Confirmed CRITICAL: 1
- Confirmed HIGH: 15
- Confirmed MEDIUM: 5
- Confirmed LOW: 5
- False positives filtered: 2
- New issues found in this review: 3

## Part 1 — Audit reconciliation

### 1.1 Confirmed issues (by severity)

#### CRITICAL

- **[FR-001]** `[source: C2.1]` [accessibility/contrast-matrix.md](/Users/vladimir/Projects/cryodaq/docs/design-system/accessibility/contrast-matrix.md):28-55,89-96 — published WCAG ratios are materially wrong against `theme.py`, including stale `ON_DESTRUCTIVE` input and false `BORDER` math. `theme.py:45` defines `ON_DESTRUCTIVE = "#e8eaf0"`, but the matrix still reasons from `#f5f5f7`; `theme.py:43` gives `BORDER = "#2d3038"`, whose actual contrast vs `BACKGROUND #0d0e12` is `1.46:1`, not `3.11:1`. **Fix:** recompute the full matrix from current `theme.py` tokens and regenerate all downstream conclusions. **Blast radius:** high — all accessibility claims built on this file are currently untrusted.

#### HIGH

- **[FR-002]** `[source: C3.1]` [accessibility/wcag-baseline.md](/Users/vladimir/Projects/cryodaq/docs/design-system/accessibility/wcag-baseline.md):58-64 — criterion **1.4.11 Non-text Contrast** is marked `Met` using false evidence: `BORDER #2d3038 vs BACKGROUND #0d0e12 = 3.1:1 ✓`. Actual ratio is `1.46:1`. **Fix:** downgrade or qualify the criterion until the contrast matrix is repaired and the supporting token pair changes. **Blast radius:** high — formal compliance language is currently false.

- **[FR-003]** `[source: A1.1, dup: C9.1]` [tokens/motion.md](/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/motion.md):13-15,148-161 — the doc says motion tokens are “NOT yet in `theme.py`” and tells widget code to use literals, but `src/cryodaq/gui/theme.py:157-159` already ships `TRANSITION_FAST_MS`, `TRANSITION_BASE_MS`, and `TRANSITION_SLOW_MS`. **Fix:** rewrite `tokens/motion.md` as a partial-landed story: current runtime timing tokens exist, broader motion system remains proposed. **Blast radius:** medium — implementers are currently instructed to bypass the actual source of truth.

- **[FR-004]** `[source: A7.1]` [rules/surface-rules.md](/Users/vladimir/Projects/cryodaq/docs/design-system/rules/surface-rules.md):448-460,464-470,475-484 — three fenced `python` blocks under `RULE-SURF-008` are ASCII trees, not Python. **Fix:** re-fence as `text` or rewrite into valid pseudocode. **Blast radius:** medium — breaks promised “syntax-valid examples” guarantee.

- **[FR-005]** `[source: A7.2]` [rules/content-voice-rules.md](/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md):246-258 — invalid `python` block under `RULE-COPY-004`. **Fix:** rewrite as valid string assignments or re-fence as `text`. **Blast radius:** low-medium — same trust problem as FR-004, narrower scope.

- **[FR-006]** `[source: B4.1, dup: A6.2]` [components/bento-grid.md](/Users/vladimir/Projects/cryodaq/docs/design-system/components/bento-grid.md):40-59,63-75,213-217,242 — spec says shipped Phase I.1 BentoGrid is 8-column, explicit-placement-only, overlap-validating. Actual implementation at [bento_grid.py](/Users/vladimir/Projects/cryodaq/src/cryodaq/gui/shell/overlays/_design_system/bento_grid.py):16,39-52 is 12-column, supports auto-flow, and validates only bounds. **Fix:** either align the spec to current implementation or relabel the 8-column explicit-only model as future-state. **Blast radius:** high — layout implementation guidance is currently wrong.

- **[FR-007]** `[source: C1.1, dup: A6.2]` [patterns/page-scaffolds.md](/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/page-scaffolds.md):70,96,99, [patterns/responsive-behavior.md](/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/responsive-behavior.md):61,67-71,77,149,155,176, and [patterns/cross-surface-consistency.md](/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/cross-surface-consistency.md) — pattern layer composes around `PanelCard`, `OVERLAY_MAX_WIDTH`, and an 8-column BentoGrid, none of which match shipped code. `theme.py` has no `OVERLAY_*` tokens; no `PanelCard` exists in `src/cryodaq/gui/`. **Fix:** rewrite patterns against current primitives or mark these artifacts as future-state proposals. **Blast radius:** high — Phase II scaffold guidance is currently non-composable.

- **[FR-008]** `[source: B6.2]` [components/card.md](/Users/vladimir/Projects/cryodaq/docs/design-system/components/card.md):6,70-100,188-205,340 — the file mixes “implemented via `modal_card.py`”, “proposed `PanelCard`”, and “reference implementation `panel_card.py`”, but `src/cryodaq/gui/shell/overlays/_design_system/panel_card.py` does not exist. **Fix:** mark `PanelCard` proposal-only or point exclusively to `modal_card.py` until extraction exists. **Blast radius:** medium-high — wrong traceability on a foundational component.

- **[FR-009]** `[source: B6.3]` [cryodaq-primitives/phase-stepper.md](/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/phase-stepper.md):6,94 — wrong implementation path. The file claims `_design_system/phase_aware_widget.py`; actual implementation is [dashboard/phase_stepper.py](/Users/vladimir/Projects/cryodaq/src/cryodaq/gui/dashboard/phase_stepper.py) and [dashboard/phase_aware_widget.py](/Users/vladimir/Projects/cryodaq/src/cryodaq/gui/dashboard/phase_aware_widget.py). **Fix:** point at the real dashboard path or explicitly label overlay extraction as future work. **Blast radius:** medium.

- **[FR-010]** `[source: B6.4]` [cryodaq-primitives/sensor-cell.md](/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/sensor-cell.md):6,326 — wrong implementation path and wrong surrounding grid story. Real implementation is [dashboard/sensor_cell.py](/Users/vladimir/Projects/cryodaq/src/cryodaq/gui/dashboard/sensor_cell.py) plus [dashboard/dynamic_sensor_grid.py](/Users/vladimir/Projects/cryodaq/src/cryodaq/gui/dashboard/dynamic_sensor_grid.py), and the current grid is width-driven, not “responsive 8-column”. **Fix:** correct both path and behavior description. **Blast radius:** high — domain primitive traceability is currently misleading.

- **[FR-011]** `[source: C8.1]` [tokens/keyboard-shortcuts.md](/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/keyboard-shortcuts.md):26-43,48-53 conflicts with [accessibility/keyboard-navigation.md](/Users/vladimir/Projects/cryodaq/docs/design-system/accessibility/keyboard-navigation.md):48-66 and [cryodaq-primitives/tool-rail.md](/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/tool-rail.md):28-38. One registry says `Ctrl+E/Ctrl+K/Ctrl+M/Ctrl+R/Ctrl+C/Ctrl+D`; the other says `Ctrl+1..9`, `Ctrl+L`, `Ctrl+A`, `Ctrl+Shift+X`, `F5`, `F11`. **Fix:** select a canonical registry and clearly label the other as proposal or remove it. **Blast radius:** high — operator shortcut docs currently disagree.

- **[FR-012]** `[source: C5.1]` [governance/token-naming.md](/Users/vladimir/Projects/cryodaq/docs/design-system/governance/token-naming.md):91-107,182-200,246 — prefix registry and scale do not match `theme.py`. The doc claims `SPACE_1..SPACE_9`, `OVERLAY_*`, and nine spacing steps; `theme.py:114-120` ships `SPACE_0..SPACE_6`, and no `OVERLAY_*` family exists. Many live families are omitted. **Fix:** rebuild the registry from current `theme.py`, separating canonical, deprecated, and internal families. **Blast radius:** high — governance policy is currently not an accurate map of the system it governs.

- **[FR-013]** `[source: C5.2]` [governance/versioning.md](/Users/vladimir/Projects/cryodaq/docs/design-system/governance/versioning.md):23-29,91-123,205-209 — versioning process refers to `docs/design-system/VERSION` and `docs/design-system/CHANGELOG.md`, but neither file exists. **Fix:** either add the promised artifacts or rewrite the release process to match actual repository reality. **Blast radius:** medium-high — governance workflow is partly fictional.

- **[FR-014]** `[source: final review, new]` [rules/accessibility-rules.md](/Users/vladimir/Projects/cryodaq/docs/design-system/rules/accessibility-rules.md):12-15 says “CryoDAQ is not currently screen-reader accessible”, while [accessibility/keyboard-navigation.md](/Users/vladimir/Projects/cryodaq/docs/design-system/accessibility/keyboard-navigation.md):165-172 specifies `accessibleName`, `accessibleDescription`, and `QAccessible.Event.ValueChanged` behavior, and [accessibility/wcag-baseline.md](/Users/vladimir/Projects/cryodaq/docs/design-system/accessibility/wcag-baseline.md):138-140,163 claims manual screen-reader sanity checks and warns against “claiming AA without testing”. **Fix:** choose one truthful scope statement and align all accessibility docs around it. **Blast radius:** high — current accessibility scope is self-contradictory.

- **[FR-015]** `[source: final review, new]` Accessibility commitments do not propagate into interactive component specs. [focus-management.md](/Users/vladimir/Projects/cryodaq/docs/design-system/accessibility/focus-management.md):17-21,236-240 says every interactive element needs a visible 2px ACCENT focus ring; [keyboard-navigation.md](/Users/vladimir/Projects/cryodaq/docs/design-system/accessibility/keyboard-navigation.md):178-185 requires focus testing on every panel. Yet [components/dialog.md](/Users/vladimir/Projects/cryodaq/docs/design-system/components/dialog.md):78-120 has no states matrix, and [cryodaq-primitives/sensor-cell.md](/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/sensor-cell.md):64-78 defines an interactive component with no hover/focus states. **Fix:** propagate focus/hover/active requirements into each interactive component spec, not just accessibility docs. **Blast radius:** high — accessibility layer is not enforceable from component specs.

- **[FR-016]** `[source: final review, new]` Pressure-unit policy splits across layers. [rules/content-voice-rules.md](/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md):368-371 says operator-facing pressure unit is `мбар`, not `mbar`. But [rules/data-display-rules.md](/Users/vladimir/Projects/cryodaq/docs/design-system/rules/data-display-rules.md):174,182,320,331,425,430,446, [tokens/typography.md](/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md):128, [tokens/chart-tokens.md](/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/chart-tokens.md):126,140, and [cryodaq-primitives/top-watch-bar.md](/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/top-watch-bar.md):53 currently use or exemplify `mbar`. **Fix:** canonicalize one operator-facing unit spelling and update every example and invariant to match. **Blast radius:** high — copy, chart, and widget docs currently point in two directions.

#### MEDIUM

- **[FR-017]** `[source: A6.1]` [rules/data-display-rules.md](/Users/vladimir/Projects/cryodaq/docs/design-system/rules/data-display-rules.md):245-250 conflicts with [rules/accessibility-rules.md](/Users/vladimir/Projects/cryodaq/docs/design-system/rules/accessibility-rules.md):153-173. One rule says stale body text uses `STATUS_STALE`; the other says `STATUS_STALE` must not be used for body-size text because it fails AA. **Fix:** pick one canonical stale rendering treatment and remove the contradiction. **Blast radius:** medium — implementers get mutually exclusive instructions.

- **[FR-018]** `[source: A4.1]` [ANTI_PATTERNS.md](/Users/vladimir/Projects/cryodaq/docs/design-system/ANTI_PATTERNS.md) — multiple anti-pattern entries still have no explicit `Violates RULE-*` anchor, e.g. the cases cited in Audit A at lines 106, 144, 314, 435, 479. **Fix:** add rule anchors or downgrade the file from enforcement language to advisory catalog. **Blast radius:** medium — weaker enforcement, not direct implementation drift.

- **[FR-019]** `[source: A9.1]` [README.md](/Users/vladimir/Projects/cryodaq/docs/design-system/README.md):68 says `chart-tokens.md` covers 12 tokens, while [tokens/chart-tokens.md](/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/chart-tokens.md):14 says 10 tokens and omits part of the real `PLOT_*` runtime surface in `theme.py:165-174`. **Fix:** recount and sync root docs, token doc, and theme export surface. **Blast radius:** medium — inventory drift.

- **[FR-020]** `[source: B8.1]` [components/dialog.md](/Users/vladimir/Projects/cryodaq/docs/design-system/components/dialog.md):89-295 — interactive component has no explicit states matrix. **Fix:** add default / focus-trap / disabled / destructive-safe-default states. **Blast radius:** medium — narrower instance of FR-015.

- **[FR-021]** `[source: B8.2]` [cryodaq-primitives/sensor-cell.md](/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/sensor-cell.md):64-78 — state matrix covers domain states only, but the primitive is interactive and lacks hover/focus/press treatment. **Fix:** extend matrix for interaction states. **Blast radius:** medium — narrower instance of FR-015.

#### LOW

- **[FR-022]** `[source: A5.1]` Many root/token/rule docs miss the promised front-matter contract. Examples called out in Audit A include [README.md](/Users/vladimir/Projects/cryodaq/docs/design-system/README.md), [ANTI_PATTERNS.md](/Users/vladimir/Projects/cryodaq/docs/design-system/ANTI_PATTERNS.md), multiple token docs, and many rule docs; `MANIFEST.md` has no front matter at all. **Fix:** normalize front matter once structure stabilizes. **Blast radius:** low — tooling/readability issue.

- **[FR-023]** `[source: A9.2]` [MANIFEST.md](/Users/vladimir/Projects/cryodaq/docs/design-system/MANIFEST.md):95 — stale line-count statistics. **Fix:** refresh or mark generated/approximate. **Blast radius:** low.

- **[FR-024]** `[source: A5.2]` [README.md](/Users/vladimir/Projects/cryodaq/docs/design-system/README.md):75-83 omits `rules/governance-rules.md` from the `rules/` tree. **Fix:** add it. **Blast radius:** low.

- **[FR-025]** `[source: A.OTHER.1]` [theme.py](/Users/vladimir/Projects/cryodaq/src/cryodaq/gui/theme.py):10-11 still references deleted `docs/design-system/MASTER.md` and `FINDINGS.md`. **Fix:** point to `README.md` and `MANIFEST.md`. **Blast radius:** low — but it keeps pointing developers at dead docs.

- **[FR-026]** `[source: B1.1/B5.1]` Component/primitives layer consistently lacks `references:` front-matter key. **Fix:** add it systematically. **Blast radius:** low — traceability enhancement, not behavior.

### 1.2 False positives

- **[FP-001]** `[source: A8.1]` Audit A flagged untraced hex `#090a0d` in [tokens/elevation.md](/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/elevation.md):24. **Not a defect:** this is explanatory prose about what 30% black shadow would visually approximate, not a normative token or recommended value. The file’s actual policy is “zero-shadow” and the hex is not presented as runtime guidance.

- **[FP-002]** `[source: B7.1]` Audit B flagged hardcoded `#a53838` in [components/button.md](/Users/vladimir/Projects/cryodaq/docs/design-system/components/button.md):214-227. **Not a defect in v1.0.0 docs:** the example explicitly labels it `RULE-COLOR-001 exception` and says it should be promoted to `DESTRUCTIVE_PRESSED`; [MANIFEST.md](/Users/vladimir/Projects/cryodaq/docs/design-system/MANIFEST.md):189-194 tracks that exact governance follow-up. This is technical debt, but not undocumented drift.

## Part 2 — Cross-batch issues (new)

These are issues no single audit could fully see because they sit between batches.

### 2.1 Tokens ↔ Rules inconsistencies

- **[FR-016] Pressure-unit split.** Token and chart examples still say `mbar`, while copy rules require `мбар`. This is not just wording drift; it creates two incompatible operator-facing conventions.
- **[FR-003] Motion current-state split.** Tokens say “not in `theme.py` yet”; governance/accessibility prose assumes a centralized motion policy; code already ships `TRANSITION_*_MS`. One truthful current-state story is missing.

### 2.2 Rules ↔ Components gaps

- **[FR-015] Accessibility rules are not translatable into component behavior because interactive specs omit focus/hover states.** Accessibility docs require the ring; component docs do not always expose where it should appear.
- **[FR-017] Stale-state rule conflict.** Components that try to obey both data-display and accessibility layers cannot do so without making an arbitrary choice.

### 2.3 Primitives ↔ Patterns breaks

- **[FR-007] Pattern layer is still composed around obsolete primitives and tokens.** `PanelCard`, `OVERLAY_MAX_WIDTH`, and 8-column BentoGrid are not just stale names; they produce impossible compositions against current Phase I.1 code.

### 2.4 Governance chain gaps

- **[FR-012] Token naming policy is not generated from `theme.py`.** The governance registry is currently descriptive fiction, not a trustworthy authority.
- **[FR-013] Release/versioning process names artifacts that do not exist.** The governance chain is incomplete at the operational level.

### 2.5 Domain-safety violations

- No CRITICAL domain-safety drift of the type feared in the prompt was found. I did **not** find “only certified T11/T12”, Latin `T11` in operator-facing guidance, uppercase FSM states as normative UI labels, or linear-pressure guidance in chart specs.
- The nearest domain-facing defect is **[FR-016]**: pressure unit spelling is inconsistent across operator-facing examples. That is not a safety-authority break, but it is a real copy-rule breach.

## Part 3 — Prioritized patch plan

### Batch 1 — CRITICAL fixes (block v1.0.0 → v1.0.1)

#### File: [accessibility/contrast-matrix.md](/Users/vladimir/Projects/cryodaq/docs/design-system/accessibility/contrast-matrix.md)
- [FR-001] Recompute every published ratio from current `theme.py`
- [FR-001] Replace stale `ON_DESTRUCTIVE` assumptions with `#e8eaf0`
- [FR-001] Re-evaluate all filled-pill rows and non-text contrast rows

#### File: [accessibility/wcag-baseline.md](/Users/vladimir/Projects/cryodaq/docs/design-system/accessibility/wcag-baseline.md)
- [FR-002] Remove or downgrade the 1.4.11 `Met` claim based on false `3.1:1`
- [FR-002] Re-check any other criterion claims that cite contrast-derived evidence

### Batch 2 — HIGH fixes (v1.0.1 → v1.1.0)

#### File: [tokens/motion.md](/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/motion.md)
- [FR-003] Rewrite the current-state section around shipped `TRANSITION_*_MS`
- [FR-003] Remove “use literals until tokens land” instruction

#### File: [rules/surface-rules.md](/Users/vladimir/Projects/cryodaq/docs/design-system/rules/surface-rules.md)
- [FR-004] Re-fence non-Python diagrams under `RULE-SURF-008`

#### File: [rules/content-voice-rules.md](/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md)
- [FR-005] Repair invalid example block under `RULE-COPY-004`
- [FR-016] Keep pressure-unit examples aligned with the chosen canonical spelling

#### File: [components/bento-grid.md](/Users/vladimir/Projects/cryodaq/docs/design-system/components/bento-grid.md)
- [FR-006] Fix default columns, auto-flow story, and overlap-validation claim
- [FR-006] Update changelog entry so it no longer misstates Phase I.1 behavior

#### File: [patterns/page-scaffolds.md](/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/page-scaffolds.md)
- [FR-007] Remove or relabel `PanelCard` scaffold and 8-column assumption

#### File: [patterns/responsive-behavior.md](/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/responsive-behavior.md)
- [FR-007] Remove or relabel `OVERLAY_MAX_WIDTH`
- [FR-007] Resolve 8-column BentoGrid claim and “no auto-flow” claim

#### File: [patterns/cross-surface-consistency.md](/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/cross-surface-consistency.md)
- [FR-007] Stop treating `PanelCard` as a live primitive unless it is one

#### File: [components/card.md](/Users/vladimir/Projects/cryodaq/docs/design-system/components/card.md)
- [FR-008] Resolve “implemented vs proposed” contradiction for `PanelCard`

#### File: [cryodaq-primitives/phase-stepper.md](/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/phase-stepper.md)
- [FR-009] Fix `implements:` path and API comment path

#### File: [cryodaq-primitives/sensor-cell.md](/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/sensor-cell.md)
- [FR-010] Fix implementation path and remove “responsive 8-column” story
- [FR-021] Add hover/focus/press states to the state matrix

#### File: [tokens/keyboard-shortcuts.md](/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/keyboard-shortcuts.md)
- [FR-011] Mark as canonical or future-state proposal, not both

#### File: [accessibility/keyboard-navigation.md](/Users/vladimir/Projects/cryodaq/docs/design-system/accessibility/keyboard-navigation.md)
- [FR-011] Align global shortcut table with canonical registry
- [FR-014] Align screen-reader scope language with actual commitment

#### File: [cryodaq-primitives/tool-rail.md](/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/tool-rail.md)
- [FR-011] Keep shortcut examples aligned with the chosen registry

#### File: [governance/token-naming.md](/Users/vladimir/Projects/cryodaq/docs/design-system/governance/token-naming.md)
- [FR-012] Rebuild prefix registry and spacing scale from real `theme.py`

#### File: [governance/versioning.md](/Users/vladimir/Projects/cryodaq/docs/design-system/governance/versioning.md)
- [FR-013] Either create VERSION/CHANGELOG release artifacts or remove them from process

#### File: [rules/accessibility-rules.md](/Users/vladimir/Projects/cryodaq/docs/design-system/rules/accessibility-rules.md)
- [FR-014] Resolve the screen-reader scope statement

#### File: [components/dialog.md](/Users/vladimir/Projects/cryodaq/docs/design-system/components/dialog.md)
- [FR-015] Add explicit interaction/focus states

#### File: [tokens/typography.md](/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md)
- [FR-016] Fix TopWatchBar pressure example unit spelling

#### File: [tokens/chart-tokens.md](/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/chart-tokens.md)
- [FR-016] Fix `units='mbar'` example if operator-facing canonical unit is `мбар`
- [FR-019] Recount actual chart-token surface

#### File: [cryodaq-primitives/top-watch-bar.md](/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/top-watch-bar.md)
- [FR-016] Fix `mбар`/`mbar` invariant language and API example

### Batch 3 — MEDIUM fixes (v1.1.x)

#### File: [rules/data-display-rules.md](/Users/vladimir/Projects/cryodaq/docs/design-system/rules/data-display-rules.md)
- [FR-017] Resolve stale rendering contradiction with accessibility rules
- [FR-016] Align unit language and examples with canonical pressure spelling

#### File: [ANTI_PATTERNS.md](/Users/vladimir/Projects/cryodaq/docs/design-system/ANTI_PATTERNS.md)
- [FR-018] Add explicit `Violates RULE-*` anchors to currently floating anti-patterns

#### File: [README.md](/Users/vladimir/Projects/cryodaq/docs/design-system/README.md)
- [FR-019] Sync chart-token count
- [FR-024] Add `governance-rules.md` to the file tree

#### File: [components/dialog.md](/Users/vladimir/Projects/cryodaq/docs/design-system/components/dialog.md)
- [FR-020] Add missing state matrix section

### Batch 4 — LOW / polish (as-needed)

#### File group: root + tokens + rules docs
- [FR-022] Normalize front matter where missing

#### File: [MANIFEST.md](/Users/vladimir/Projects/cryodaq/docs/design-system/MANIFEST.md)
- [FR-023] Refresh stale statistics

#### File: [theme.py](/Users/vladimir/Projects/cryodaq/src/cryodaq/gui/theme.py)
- [FR-025] Replace dead design-system doc references

#### File group: components + cryodaq-primitives
- [FR-026] Add `references:` front matter keys

## Part 4 — Issues requiring architect decision

- **[AD-001]** 8-column vs 12-column BentoGrid.  
  Context: current code is 12-column with auto-flow; multiple docs still describe 8-column explicit-placement-only.  
  Two interpretations:
  A) docs are stale and should follow shipped Phase I.1 code;
  B) code drifted from intended design language and should later be brought back.  
  Recommendation: for immediate v1.0.1 integrity, patch docs to truthfully describe current code unless Vladimir explicitly wants the code reverted in a near-term block.

- **[AD-002]** Canonical global shortcut registry.  
  Context: one document set reflects current `Ctrl+1..9` navigation, another proposes mnemonic shortcuts.  
  Two interpretations:
  A) current implemented shortcuts remain canonical;
  B) mnemonic registry is the intended future model and current docs should mark existing behavior transitional.  
  Recommendation: Vladimir should choose one before Phase II overlays begin relying on shortcut prose.

- **[AD-003]** Screen-reader commitment scope.  
  Context: `accessibility-rules.md` says screen readers are out of scope; baseline and keyboard docs partially pull them into scope.  
  Two interpretations:
  A) v1.0.x is keyboard/visual AA only, and SR references should be downgraded to future work;
  B) the product is making a basic SR commitment already, and the rules doc is stale.  
  Recommendation: decide explicitly, because this affects both compliance wording and component requirements.

## Part 5 — Structural recommendations (beyond issue-level)

1. **Separate “current state” from “proposed/future state” with a consistent callout pattern.** A large fraction of current defects are not wrong ideas; they are unlabeled future-state ideas presented as if already shipped.
2. **Generate inventories from code where possible.** Contrast matrix, token family registry, chart-token counts, and perhaps shortcut registry should be script-generated from `theme.py` / current implementation, not hand-maintained prose.
3. **Make implementation traceability schema strict.** `implements:`, `references:`, and “reference implementation” sections should be linted against filesystem reality.
4. **Treat accessibility commitments as contract-first.** If a requirement exists in `accessibility/`, it must appear in every relevant interactive component spec; otherwise it is aspirational text, not an enforceable system.

## Part 6 — Success criteria

- [ ] All CRITICAL from Part 3 Batch 1 fixed
- [ ] Re-run Audit C critical sections and confirm `contrast-matrix.md` + `wcag-baseline.md` are clean
- [ ] Re-run Audit A high sections that touch `tokens/motion.md` and cross-check against `theme.py`
- [ ] Re-run Audit B high sections that touch `bento-grid.md`, `card.md`, `phase-stepper.md`, and `sensor-cell.md`
- [ ] Shortcut registry conflict resolved in exactly one canonical place
- [ ] MANIFEST.md statistics match reality after patches
- [ ] Version bump to v1.0.1

## Appendix — Raw reconciled issues table

| ID | Source | Audit severity | File(s) | Summary | Final verdict | Final severity |
|---|---|---:|---|---|---|---:|
| R-001 | A1.1, C9.1 | HIGH / MEDIUM | `tokens/motion.md` | Claims motion tokens absent from `theme.py` | CONFIRMED | HIGH |
| R-002 | A7.1 | HIGH | `rules/surface-rules.md` | Invalid `python` blocks | CONFIRMED | HIGH |
| R-003 | A7.2 | HIGH | `rules/content-voice-rules.md` | Invalid `python` block | CONFIRMED | HIGH |
| R-004 | A6.1 | MEDIUM | `rules/data-display-rules.md`, `rules/accessibility-rules.md` | Stale-color contradiction | CONFIRMED | MEDIUM |
| R-005 | A4.1 | MEDIUM | `ANTI_PATTERNS.md` | Missing direct `RULE-*` anchors | CONFIRMED | MEDIUM |
| R-006 | A6.2, B4.1 | MEDIUM / HIGH | `components/bento-grid.md`, `MANIFEST.md`, `tokens/breakpoints.md` | Grid model disagreement / shipped behavior drift | CONFIRMED | HIGH |
| R-007 | A9.1 | MEDIUM | `README.md`, `tokens/chart-tokens.md` | Chart-token inventory mismatch | CONFIRMED | MEDIUM |
| R-008 | A8.1 | MEDIUM | `tokens/elevation.md` | Untraced derived hex | FALSE POSITIVE | — |
| R-009 | A5.1 | LOW | multiple | Front-matter gaps | CONFIRMED | LOW |
| R-010 | A9.2 | LOW | `MANIFEST.md` | Statistics stale | CONFIRMED | LOW |
| R-011 | A5.2 | LOW | `README.md` | Omits `governance-rules.md` | CONFIRMED | LOW |
| R-012 | A.OTHER.1 | LOW | `theme.py` | Dead doc references | CONFIRMED | LOW |
| R-013 | B3.1 | HIGH | `components/toast.md` | Invalid Python signature | CONFIRMED | HIGH |
| R-014 | B6.2 | HIGH | `components/card.md` | Nonexistent `PanelCard` implementation presented as current | CONFIRMED | HIGH |
| R-015 | B6.3 | HIGH | `cryodaq-primitives/phase-stepper.md` | Wrong implementation path | CONFIRMED | HIGH |
| R-016 | B6.4 | HIGH | `cryodaq-primitives/sensor-cell.md` | Wrong implementation path / wrong grid story | CONFIRMED | HIGH |
| R-017 | B8.1 | MEDIUM | `components/dialog.md` | Missing state matrix | CONFIRMED | MEDIUM |
| R-018 | B8.2 | MEDIUM | `cryodaq-primitives/sensor-cell.md` | Missing hover/focus states | CONFIRMED | MEDIUM |
| R-019 | B7.1 | MEDIUM | `components/button.md` | Hardcoded destructive pressed hex | FALSE POSITIVE | — |
| R-020 | B1.1/B5.1 | LOW | components + primitives | Missing `references:` front matter | CONFIRMED | LOW |
| R-021 | C2.1 | CRITICAL | `accessibility/contrast-matrix.md` | Incorrect WCAG math / stale token inputs | CONFIRMED | CRITICAL |
| R-022 | C3.1 | HIGH | `accessibility/wcag-baseline.md` | False 1.4.11 `Met` claim | CONFIRMED | HIGH |
| R-023 | C1.1/C6.1 | HIGH | patterns | Composes around obsolete primitives/tokens | CONFIRMED | HIGH |
| R-024 | C8.1 | HIGH | `tokens/keyboard-shortcuts.md`, `keyboard-navigation.md`, `tool-rail.md` | Conflicting shortcut registries | CONFIRMED | HIGH |
| R-025 | C5.1 | HIGH | `governance/token-naming.md` | Prefix registry diverges from `theme.py` | CONFIRMED | HIGH |
| R-026 | C5.2 | HIGH | `governance/versioning.md` | Refers to nonexistent release artifacts | CONFIRMED | HIGH |
| R-027 | final review | — | `rules/content-voice-rules.md`, `rules/data-display-rules.md`, `tokens/*`, `top-watch-bar.md` | Pressure-unit convention split (`мбар` vs `mbar`) | CONFIRMED | HIGH |
| R-028 | final review | — | `rules/accessibility-rules.md`, `wcag-baseline.md`, `keyboard-navigation.md` | Screen-reader scope contradiction | CONFIRMED | HIGH |
| R-029 | final review | — | `focus-management.md`, `keyboard-navigation.md`, `components/dialog.md`, `sensor-cell.md` | A11y commitments not propagated into component specs | CONFIRMED | HIGH |
| R-030 | final review | — | design-system vs code | 8-column vs 12-column model direction | AMBIGUOUS | — |
| R-031 | final review | — | shortcut docs | Which shortcut scheme should be canonical | AMBIGUOUS | — |
| R-032 | final review | — | accessibility docs | Whether SR support is in or out of v1.0.x scope | AMBIGUOUS | — |
