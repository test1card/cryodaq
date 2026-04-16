# Design System Changelog

All notable changes to the CryoDAQ design system are recorded here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [Semantic Versioning 2.0.0](https://semver.org/) with
the design-system-specific definitions of "breaking" from
`governance/versioning.md`.

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
