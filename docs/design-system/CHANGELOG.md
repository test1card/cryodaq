---
title: Design System Changelog
status: canonical
last_updated: 2026-08-10
version: 4.2.0
---

# Design System Changelog

All notable changes to the CryoDAQ design system are recorded here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [Semantic Versioning 2.0.0](https://semver.org/) with
the design-system-specific definitions of "breaking" from
`governance/versioning.md`.

## [4.2.0] — 2026-08-10

### Added

- `MANIFEST.md` — one machine-readable contract containing schema-v2 exact
  source/specification routes, narrow release-only triggers, 13 fixed WCAG 2.2
  contrast cases, non-weakening per-theme exception floors, and canonical
  non-color states.
- Exact-checkout F36.6 enforcement in
  `tests/docs/test_docs_freshness.py::test_design_system_governed_sources_are_coversioned`.
  It loads the strict-ancestor trusted contract, permits only the immutable
  first-release bootstrap to lack a marker, rejects candidate narrowing or
  repointing, accumulates every overlapping exact route, and requires the
  applicable specifications plus `VERSION` and `CHANGELOG.md` changes.
- Real-pack accessibility checks in `tests/gui/test_theme_loader.py` covering
  all bundled theme YAML files, the production state visual mapper and painter,
  and `CanonicalStatusLabel` accessibility properties.

### Changed

- Added RULE-GOV-005: reusable token, shared-component, pattern, and state
  semantic owners are co-versioned through additive exact routes and release
  evidence. Ordinary GUI consumers remain under the existing GUI review gate
  and do not trigger a design-system release for every code edit.
- Removed caller-supplied trusted-base inputs from both docs and main CI.
  Pull requests use their base, pushes use event authority, and manual runs use
  the merge base with `origin/<default-branch>`; every result is canonicalized
  and must be a strict ancestor of the tested candidate.
- Reconciled stale v4.0.3/v4.1.0 marker prose onto the v4.2.0 release without
  changing runtime tokens, components, state behavior, or performance budgets.

### Accessibility evidence

- WCAG 2.2 AA text (4.5:1) and non-text (3:1) ratios are recomputed from every
  real bundled theme. The 13 required case IDs, token pairs, and minima cannot
  be removed or repointed; exception membership must equal the real failures,
  and each measured ratio must remain above its non-weakening per-theme floor.
- Canonical `ok | caution | warning | fault | stale | disconnected` inputs are
  checked against exact production Russian labels and accessible labels,
  `CanonicalStatusLabel` names/descriptions, token values, and five pinned
  geometries rendered through `paint_state_shape` into real `QImage` masks.
  Legacy `warning` remains the `caution` presentation alias.

### Open evidence

- Whole-shell keyboard/focus traversal, NVDA on the real Windows build,
  scripted operator task acceptance, visual judgment, and runtime
  frame/startup/memory measurements remain human or target-environment gates.
  This release does not claim those measurements from static checks.

## [4.1.0] — 2026-08-05

### Added

- `patterns/state-visualization.md` — the **classification axis**: whether a
  channel's reading is backed by a matched descriptor, by none
  (`IdentityStatus.LEGACY_ABSENT`), or by one that was refused
  (`IdentityStatus.REFUSED`). Orthogonal to severity and to freshness, like
  connectivity. Owner decision of 2026-08-05, recorded in `docs/DECISIONS.md`;
  cross-referenced from `rules/data-display-rules.md` RULE-DATA-005.

### Corrected

- **This state already ships, and an earlier draft of this entry called it
  unimplemented.** `gui/dashboard/sensor_cell.py::_apply_identity_state` renders
  both the absent and refused cases today, and
  `tests/gui/dashboard/test_sensor_cell.py` asserts the value stays visible
  alongside the cue. What the entry adds is the TARGET treatment — the `н/о`
  in-field marker with `без дескриптора` in tooltip and accessible name — and
  the record that the shipped treatment diverges from it in two ways worth
  migrating: it has no in-field marker, and it borrows `STATUS_STALE` for the
  chrome, which is the freshness axis's token. Calling the state unimplemented
  would have let the OC-008/OC-030 site migrations skip the surface that
  already renders it.
- Version bumped 4.0.3 → 4.1.0. A reusable state semantic changed, and the root
  contract requires the version to move with it in the same slice; an earlier
  draft argued for no bump from the `command-outcome-unknown` precedent below,
  which is a precedent for the entry's shape and not for skipping the version.

## [4.0.3] — 2026-07-20

### Added

- 2026-07-25: `patterns/command-outcome-unknown.md` — new cross-surface pattern
  for mutation-outcome uncertainty (`_outcome_unknown` / `delivery_state` /
  `commit_state`, the `_close_locked()` raise-on-non-empty invariant, and a
  nine-instance table across `QuickLogBlock`, `PhaseAwareWidget`,
  `OperatorLogPanel`, `CalibrationPanel`, `KeithleyPanel`, `ConductivityPanel`,
  `MultiLinePanel`, `AlarmPanel`, and `ExperimentOverlay`). Names the canonical
  treatment (`STATUS_CAUTION` + text + accessibility, colour never the sole
  carrier), one sanctioned per-row variant, and two recorded deviations with
  migration notes rather than silently blessing four coexisting treatments as
  equivalent. Enforced by
  `tests/docs/test_docs_freshness.py::test_outcome_unknown_gui_instances_are_documented_in_design_system`.

### Corrected

- Reserved `STATUS_OK` for demonstrated health or safety truth in the remaining
  bottom-bar safety activity, conductivity settling/stability, and assistant
  shift-handover paths. Ordinary activity and progress now use `ACCENT` or
  neutral informational presentation without removing any operator data.
- Normalized instrument summaries and new F36 operator-presentation fixtures to
  the one visible caution rung. Legacy backend/history `warning` remains an
  accepted compatibility input and still renders exactly as caution.
- Reconciled stale color-rule examples and component references with the v4
  semantic lock. Added focused regressions for running/authorized states,
  settling percentages, shift handover, instrument wording, and F36 fixtures.

## [4.0.2] — 2026-07-17

### Corrected

- Reconciled the release marker, README, manifest, changelog front matter, and
  migration inventory on one v4.0.2 contract. Canonical referenced design
  artifacts must be present in the Git index; an untracked local draft cannot
  silently satisfy the design-system manifest.
- Reserved safety colors for safety/health truth. Active phases, ordinary
  actions, running/coverage identity, and measurement series use neutral or
  accent/data tokens with non-color cues; current production exceptions remain
  explicit migration gaps rather than normative examples.
- Kept the shipped Keithley emergency interaction as a visible cancel-default
  modal and the alternative hold/global gesture as an open hazard decision.
  Documentation no longer promotes a proposed gesture to current behavior.
- Removed stale links to deleted v1 widgets, superseded analytics modules/tests,
  and retired handoff files. Proposed future modules are now named as proposals,
  not represented as live repository paths.
- Corrected the remaining hover/focus rule contradiction: focus, selection, and
  ordinary activity use ACCENT; STATUS_OK is reserved for independently proven
  health or safety truth.

- Replaced automatic theme re-exec with a validated, atomic next-launch
  selection. The checked menu action remains the theme actually loaded in the
  current process, while a disabled line names the pending selection. Theme
  choice no longer stops ingress, assistant, bridge, engine, or acquisition.
- Made theme-pack inventory and persistence use the same strict identifier,
  token, metadata, color, and caution-alias validation. Malformed existing
  settings are preserved and refused instead of being overwritten.
- Extended coarse tray truth with data freshness and periodic-reporting
  evidence. Green now requires affirmative connection, accepted safety state,
  exact zero alarms, fresh data, and known-good reporting. Tooltip text is
  Russian, non-authoritative, and bounded to the Windows 127 UTF-16-unit limit.
- Added a fail-visible shutdown override for the tray. The launcher now keeps
  the application, tray, exact resource handles, and single-instance lock alive
  while any process, worker, queue, descriptor, capability, or loop remains
  unsettled; capped retries cannot respawn children after the shutdown latch.

## [4.0.1] — 2026-07-17

### Corrected

- Replaced the unshipped global `Ctrl+Shift+X`, one-second hold, and
  `Shift+Enter` emergency instructions with the current `Ctrl+K` navigation,
  visible Keithley emergency action, and cancel-default modal. Alternative
  emergency gestures remain an open hazard decision.
- Aligned calibration import/export documentation with `.cof`, `.340`, JSON,
  and CSV, and recorded safety-color reuse in the coverage display as an open
  production migration rather than compliant behavior.
- Added a canonical coarse, non-authoritative tray contract: missing alarm
  authority is unknown, never zero, and green cannot prove readiness,
  verified-OFF, or absence of alarms.
- Implemented that tray contract in the resolver: malformed/unknown alarm
  authority is fail-visible caution, fault takes precedence, and distinct
  check/triangle/octagon silhouettes plus Russian tooltip duplicate color.
  Launcher alarm-count authority and Windows visual acceptance remain open.
- Defined the alarm badge as an unacknowledged active-attention count while
  keeping acknowledged-active hazards visible in the alarm panel; corrected
  alarm navigation to `Ctrl+M` and retained one caution rung.
- Reconciled responsive bento behavior with automatic reflow, deliberate
  evidence scrolling, and the prohibition on clipped current truth.
- Removed stale four-vital and Tmin/Tmax language in favor of pressure, T12
  second-stage, and T11 nitrogen-plate references; made experiment identity
  neutral rather than safety green.
- Defined theme application as an operational cold restart and prohibited any
  automatic-resumption promise without measured end-to-end evidence.

## [4.0.0] — 2026-07-15

### Changed

- Restored panoramic observability as a mandatory property of the primary
  operating surface. Curated summaries and prioritization are additive and may
  not hide comprehensive channel, trend, experiment, provenance, or state
  evidence.
- Added a mandatory per-change tradeoff record: operator benefit, operator
  cost, safety/workflow justification, mitigation/evidence, and revert trigger.
- Reclassified the atomic «Сводка смены» as a supplemental briefing rather
  than the sole home truth surface.
- Recorded laboratory operator decisions for information retention, a
  three-step `safe | caution | fault` severity ladder, orthogonal state axes,
  acknowledgement responsibility, the current audible-alarm behavior and its
  open single-owner consolidation gate, 2 Hz
  display cadence, manual plot windows, cross-channel skew, DPI-aware automatic
  reflow, and deferred 100+ sensor/4K projector mode.
- Hardened alarm acknowledgement around exact engine-instance and activation
  identity. Delayed, restarted-engine, name-only, and out-of-order actions fail
  closed; rows remain visible as evidence. Acknowledgement changes
  attention/audible responsibility only and cannot clear a hazard, start safety
  recovery, or acquire control authority. REST clients must migrate from an
  empty/name-only ACK body to the identity returned by the accepted alarms GET
  snapshot.

## [3.0.2] — 2026-07-15

### Changed

- Aligned the ToolRail home destination, tooltip, and exact contract test with
  the Primary Operator Display term «Сводка смены».

## [3.0.1] — 2026-07-15

### Changed

- Completed the software POD home cutover for both launch roots through one
  shared ingress composition and settled it before theme re-exec.
- Made POD the only visible current-truth surface on home, flattened normal
  cards, consolidated visual provenance, and retained canonical non-color
  exception cues.

### Open evidence

- Real Windows ONEDIR DPI/NVDA, keyboard-only whole-shell traversal, operator
  task timing, long-session memory, and physical/laboratory gates.

## [3.0.0] — 2026-07-14

### Added

- Established informative and intentionally beautiful composition as the two
  primary GUI acceptance qualities. Visual craft is assessed through hierarchy,
  proportion, spacing rhythm, typography, restraint, and recognisable CryoDAQ
  identity rather than token compliance alone.
- Added the generic LabVIEW-style dashboard assembly anti-pattern: uniform box
  grids, default-looking controls, dense chrome, and equal visual weight are
  unacceptable when they erase task hierarchy or product identity.

### Changed

- Clarified that safety truth, data legibility, freshness, provenance,
  uncertainty, and the next safe action always take precedence over aesthetics.
- Extended the design-system gate from F36 surfaces to every CryoDAQ GUI/UI/UX
  change in the roadmap.

### Breaking

- The complete existing GUI corpus is now subject to the informative/beautiful
  composition gate. Previously token-compliant generic screens are not
  grandfathered: each touched surface must migrate in-slice, and the remaining
  corpus stays an explicit audited migration backlog until reviewed. This
  expanded compliance boundary requires a major version under
  `governance/versioning.md`.

## [2.0.0] — 2026-07-14

### Changed

- Replaced the public `InstrumentsPanel.on_reading(reading)` API with
  `on_descriptor_reading(reading, view)`. Generic instrument cards now require
  an exact authoritative, connected `DescriptorView` matching the Reading
  identity tuple. This is a deliberate caller-breaking identity hardening.
- Missing, refused, malformed, mismatched, and capacity-exhausted identity now
  renders fixed bounded Russian unavailable/fault text with foreground text
  plus status border; raw channel, vendor, diagnostic, and payload text is
  never echoed or used as identity.
- Identity-notice presentation is transition-driven. Steady authoritative or
  refused readings do not repeat label text, visibility, or stylesheet work.

### Removed

- Removed bare-Reading instrument attribution, slash-prefix extraction, and
  LakeShore `Т1…Т24` range inference from the generic InstrumentsPanel.

### Security

- Refused or retained descriptors cannot update a named/green instrument card;
  only later authoritative requalification can restore current attribution.

### Evidence

- Automated tests cover fixed non-color Russian cues, hostile-text exclusion,
  transition-only QSS mutation, the 4,096-entry descriptor bound, O(1) issue
  bookkeeping, and absence of blocking file/network/sleep calls on ingress.
- Real Windows ONEDIR DPI/NVDA, operator task timing, full-shell screenshots,
  and long-session performance remain open physical/external gates.

## [1.2.0] — 2026-07-11

### Added

- Added `patterns/operator-display-composition.md` for the composed F36
  Primary Operator Display: eight-card hierarchy, root-owned atomic render,
  irreversible integrity barrier, attention geometry, replay limitations,
  accessibility/performance budgets, and open evidence.

### Changed

- POD-owned snapshot cards now reject standalone rendering; the root rechecks
  whole-display coherence after synchronous child signals before accepting a
  snapshot.
- Attention presentation shows complete two-line rows, bounds the viewport at
  four rows, and scrolls a deterministic projection of at most eight items.
- Handover navigation now requires the exact backend `handover_pending` reason
  instead of inferring shift semantics from generic caution state.
- Failed-closed POD instances now discard delayed or queued child navigation;
  generic experiment severity stays on the experiment surface, and only the
  sole exact `handover_pending` reason selects the handover log.
- Reconciled the complete README tree and MANIFEST corpus/count annotations
  with the v1.2.0 files and current runtime contracts.
- POD tests describe their actual composition subset and no longer claim that
  all twelve operator scenarios are behaviorally closed.
- Legacy-shell replay now pins archive identity and removes configuration,
  source, experiment, alarm-acknowledgement, operator/dashboard-log, settings,
  calibration and live-control Engine-restart authority in the embedded shell
  across mouse, keyboard, lazy-open, refresh and direct/queued handler paths.
  The launcher tray may still restart the isolated replay subprocess; it does
  not acquire live plant-control authority. Cold start and unknown Safety render
  unavailable/blocked truth rather than optimistic OK/source readiness.

### Open evidence

- Legacy-shell replay gating is implemented for the enumerated operational and
  configuration surfaces. Final POD-to-shell cutover, whole-shell screenshots,
  Windows ONEDIR DPI/NVDA, full keyboard traversal, operator task timing, and
  long-session memory remain unclaimed acceptance gates.

## [1.1.0] — 2026-07-11

### Added

- Implemented pure F36 operator-snapshot presentation atoms: canonical
  six-state label, freshness/provenance footer, readiness blocker row,
  attention row and virtualized list, navigation-intent control, and atomic
  snapshot card shell.
- Added `cryodaq-primitives/operator-snapshot-components.md` with public APIs,
  state anatomy, accessibility contract, examples, and performance evidence.
- Added `patterns/operator-snapshot-presentation.md` for coherent-revision,
  authority-preserving composition across future Primary Operating Display
  surfaces.

### Changed

- Design-system manifest now records F36 immutable snapshot presentation,
  navigation-only output, bounded hostile text, and fleet virtualization.
- Independent review tightened card rendering to preflight/recheck every child
  before mutation, HTML-escaped all Qt tooltip payloads, exposed control/bidi
  characters visibly, and restricted navigation IDs/copy to normalized safe
  forms.
- Composed-card review removed the arbitrary `set_content(QWidget)` path and
  added owner-bound transactional `AttentionList` content so header, rows,
  freshness, and provenance commit from one `AttentionQueue` revision or do
  not change.
- Cold-start review added a first-presentation barrier: pre-rendered bound rows
  and footer remain hidden behind explicit disconnected/unavailable shell truth
  until a successful coherent transaction; unexpected Qt reveal failure hides
  and permanently fails the card instance closed.

### Open evidence

- Real Windows ONEDIR DPI/NVDA, composed-POD screenshots, operator task timing,
  and 12-hour memory measurements remain unclaimed acceptance gates.

## [1.0.1] — 2026-04-17

Audit fix pass — reconciles documentation with shipped reality. No
token additions, no rule additions, no widget changes. Purely corrective.

### Fixed

- Recomputed contrast matrix from actual `theme.py` hex values (FR-001).
- Corrected traceability paths for `phase-stepper`, `sensor-cell`, `card`
  (FR-002).
- Aligned grid and pattern docs with the 8-column canonical layout
  (FR-006 / FR-007).
- Rebuilt the token prefix registry in `governance/token-naming.md` to
  match `theme.py` — adds previously-undocumented `SURFACE_*`, `TEXT_*`,
  `TRANSITION_*`, `QUANTITY_*`, `QDARKTHEME_*`, `ACCENT_*`, `BORDER_*`,
  `CARD_*`, `MUTED_*`, `SUCCESS_*`, `WARNING_*`, `DANGER_*` families;
  moves `OVERLAY_*` and `ICON_SIZE_*` to the proposed-prefixes table
  (FR-012).
- Corrected spacing scale in `governance/token-naming.md` from
  `SPACE_1`…`SPACE_9` to the shipped `SPACE_0`…`SPACE_6` (FR-012).
- `tokens/motion.md` — removed stale "NOT yet in theme.py" claim and
  added a "Current tokens" section documenting the shipped
  `TRANSITION_FAST_MS` / `TRANSITION_BASE_MS` / `TRANSITION_SLOW_MS`
  values (FR-003).
- Resolved shortcut-registry conflicts between
  `tokens/keyboard-shortcuts.md`, `accessibility/keyboard-navigation.md`,
  and `cryodaq-primitives/tool-rail.md`. Per architect decision AD-002,
  mnemonic shortcuts (Ctrl+L, Ctrl+E, …) are the canonical scheme;
  numeric Ctrl+[1-9] is demoted to transitional fallback (FR-011).
- Added screen-reader considerations to the v1.0 accessibility scope.

### Added

- `docs/design-system/VERSION` — plain-text single-line version marker
  referenced by `governance/versioning.md` (FR-013).
- `docs/design-system/CHANGELOG.md` — this file. Previously the versioning
  process referenced a changelog that did not exist (FR-013).

## [1.0.0] — 2026-04-17

Initial design system release.

### Added

- 66 markdown documents across `tokens/`, `rules/`, `components/`,
  `cryodaq-primitives/`, `patterns/`, `accessibility/`, and `governance/`.
- 79 enforcement rules across 9 categories.
- 126 design tokens inventoried from `src/cryodaq/gui/theme.py`.
- `MANIFEST.md` (65 encoded decisions) and `README.md` entry points.
- Three audit reports (`AUDIT_REPORT_A/B/C.md`) and `FINAL_REVIEW_REPORT.md`.

### Tags

- `design-system-v1.0.0` — initial release.
- `design-system-v1.0.1` — audit fix pass (this release).
