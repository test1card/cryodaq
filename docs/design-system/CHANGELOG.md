---
title: Design System Changelog
status: canonical
last_updated: 2026-07-12
---

# Design System Changelog

All notable changes to the CryoDAQ design system are recorded here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [Semantic Versioning 2.0.0](https://semver.org/) with
the design-system-specific definitions of "breaking" from
`governance/versioning.md`.

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
