---
title: Design System Manifest
status: canonical
last_updated: 2026-08-10
version: 4.2.0
---

# CryoDAQ Design System — Manifest

**Generated:** 2026-08-10
**Session:** v4.2.0 design-system governance gate
**Scope:** Design system v4.2.0 — foundation tokens + 79 widget rules + 5 governance rules + generic components + CryoDAQ domain primitives + cross-surface patterns + accessibility commitments + governance policies.

## Structure

```
design-system/
├── README.md                           # Entry point, navigation, precedence rules
├── MANIFEST.md                         # This file
├── CHANGELOG.md                        # Design-system release history
├── VERSION                             # Authoritative version marker
├── GUI_MIGRATION_INVENTORY.md          # Auditable v3 production-surface backlog
├── ANTI_PATTERNS.md                    # 40+ forbidden patterns with historical refs
├── DEEP_AUDIT_REPORT.md                # Retained v1.0.0 audit evidence
├── adr/                                # 2 accepted design decisions
│   ├── 001-light-theme-status-unlock.md
│   └── 002-accent-status-decoupling.md
│
├── tokens/                             # Foundation: 12 files, what exists and why
│   ├── colors.md                       # 77 color/runtime-color constants
│   ├── typography.md                   # 36 typography tokens, Fira fonts, Cyrillic rules
│   ├── spacing.md                      # 9 spacing tokens + semantic aliases
│   ├── radius.md                       # 5 radius tokens, tight scale
│   ├── layout.md                       # 7 layout tokens, including coupled constants
│   ├── chart-tokens.md                 # pyqtgraph integration
│   ├── runtime-authority.md            # theme.py token-category authority map
│   ├── motion.md                       # 3 shipped durations; easing/expanded scale proposed
│   ├── elevation.md                    # zero-shadow policy + z-index levels
│   ├── icons.md                        # Lucide bundle + emoji prohibition
│   ├── breakpoints.md                  # desktop-only responsive
│   └── keyboard-shortcuts.md           # canonical bindings; Python constants proposed
│
├── rules/                              # Enforcement: 9 files, 84 rules total with code examples
│   ├── color-rules.md                  # COLOR-001..011
│   ├── surface-rules.md                # SURF-001..010
│   ├── typography-rules.md             # TYPO-001..010
│   ├── spacing-rules.md                # SPACE-001..008
│   ├── interaction-rules.md            # INTER-001..012
│   ├── data-display-rules.md           # DATA-001..010
│   ├── accessibility-rules.md          # A11Y-001..008
│   ├── content-voice-rules.md          # COPY-001..008
│   └── governance-rules.md             # GOV-001..005 (thin pointers to governance/*)
│
├── components/                         # Generic primitives: 15 files, anatomy + invariants + code
    ├── legacy-common-runtime.md        # widgets/common.py compatibility authority
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

├── cryodaq-primitives/                 # Domain-specific: 19 files
    ├── top-watch-bar.md                # pressure + T12 + T11 + mode badge
    ├── tool-rail.md                    # left icon nav (Phase 0)
    ├── bottom-status-bar.md            # system status strip
    ├── sensor-cell.md                  # single-channel cell (B.3)
    ├── phase-stepper.md                # 6-phase stepper (B.5/B.5.5/B.5.6)
    ├── alarm-badge.md                  # header alarm indicator
    ├── tray-status.md                  # coarse, non-authoritative tray summary
    ├── alarm-panel.md                  # alarm detail surface
    ├── analytics-panel.md              # analysis surface
    ├── archive-panel.md                # persisted-data surface
    ├── calibration-panel.md            # calibration surface
    ├── conductivity-panel.md           # conductivity surface
    ├── experiment-card.md              # active-experiment dashboard tile + overlay
    ├── experiment-panel.md             # experiment detail surface
    ├── instruments-panel.md            # instrument detail surface
    ├── quick-log-block.md              # inline operator log widget
    ├── keithley-panel.md               # dual-channel SMU control
    ├── operator-log-panel.md            # operator-log surface
    └── operator-snapshot-components.md # F36 pure status/attention/readiness/card atoms

├── patterns/                           # Cross-surface patterns: 13 files, composition recipes
    ├── page-scaffolds.md               # 3 canonical scaffolds (Bento / Single-panel / Split)
    ├── information-hierarchy.md        # 3-tier model + F-pattern scan order
    ├── cross-surface-consistency.md    # 5 consistency dimensions + two-surface test
    ├── responsive-behavior.md          # desktop-only, 3 viewport bands, what adapts
    ├── state-visualization.md          # 6-state vocabulary + two-channel rule
    ├── real-time-data.md               # coalescing, stale detection, update pipeline
    ├── numeric-formatting.md           # per-quantity format reference + tabular-nums
    ├── destructive-actions.md          # 3-severity classification + two-layer pattern
    ├── copy-voice.md                   # Russian vocabulary lexicon + imperative/descriptive
    ├── operator-snapshot-presentation.md # coherent revision and authority composition
    ├── operator-display-composition.md # root-owned eight-card supplemental briefing
    ├── operator-evidence-and-retention.md # panoramic truth, severity, audio, cadence, responsive decisions
    └── command-outcome-unknown.md      # mutation-outcome uncertainty, 9-instance table, enforcement guard

├── accessibility/                      # Accessibility commitments: 5 files
    ├── wcag-baseline.md                # WCAG 2.2 AA target, scope, per-criterion commitment
    ├── contrast-matrix.md              # measured ratios all tokens vs all surfaces
    ├── keyboard-navigation.md          # tab order, shortcut registry, focus trap
    ├── focus-management.md             # 2px ACCENT ring, restoration, autofocus policy
    └── reduced-motion.md               # MotionPolicy, prefers-reduced-motion, HoldConfirm exception

└── governance/                         # System self-governance: 7 files
    ├── token-naming.md                 # closes RULE-GOV-001, naming conventions + prefix registry
    ├── deprecation-policy.md           # closes RULE-GOV-003, lifecycle + STONE_* case
    ├── versioning.md                   # SemVer 2.0.0 with design-system breaking definitions
    ├── testing-strategy.md             # 3 enforcement layers (lint / review / manual) + tooling
    ├── performance-budget.md           # 60 FPS / 16ms / ≤2Hz / 100ms input budget
    ├── change-impact.md                # mandatory five-field operator/safety review
    └── contribution.md                 # proposal process, 6 types, review gates
```

## Machine gate contract

The JSON block below is canonical data, not illustrative prose. Tests parse it directly from this real manifest. It defines the narrow governed-source map, exact WCAG 2.2 AA cases and exceptions, and canonical non-color state redundancy.

<!-- MACHINE_GATES:BEGIN -->
```json
{
  "schema_version": 1,
  "co_versioning": {
    "schema_version": 3,
    "required_release_paths": [
      "docs/design-system/VERSION",
      "docs/design-system/CHANGELOG.md"
    ],
    "release_only_patterns": [
      ".github/workflows/docs-gate.yml",
      ".github/workflows/main.yml",
      "docs/design-system/ANTI_PATTERNS.md",
      "docs/design-system/GUI_MIGRATION_INVENTORY.md",
      "docs/design-system/MANIFEST.md",
      "docs/design-system/README.md",
      "docs/design-system/accessibility/*.md",
      "docs/design-system/adr/*.md",
      "docs/design-system/components/*.md",
      "docs/design-system/cryodaq-primitives/*.md",
      "docs/design-system/governance/*.md",
      "docs/design-system/patterns/*.md",
      "docs/design-system/rules/*.md",
      "docs/design-system/tokens/*.md",
      "tests/docs/test_docs_freshness.py",
      "tests/gui/test_theme_loader.py",
      "tests/test_ci_candidate_evidence.py"
    ],
    "python_semantic_routes": [
      {
        "source_path": "src/cryodaq/gui/theme.py",
        "aggregate_spec_path": "docs/design-system/tokens/runtime-authority.md",
        "fallback_spec_paths": [
          "docs/design-system/tokens/colors.md",
          "docs/design-system/tokens/typography.md",
          "docs/design-system/tokens/spacing.md",
          "docs/design-system/tokens/layout.md",
          "docs/design-system/tokens/radius.md",
          "docs/design-system/tokens/motion.md",
          "docs/design-system/tokens/chart-tokens.md"
        ],
        "assignment_routes": [
          {
            "name_patterns": [
              "BACKGROUND",
              "FOREGROUND",
              "SURFACE_*",
              "PRIMARY",
              "SECONDARY",
              "CARD",
              "MUTED",
              "CARD_FOREGROUND",
              "BORDER*",
              "ACCENT*",
              "RING",
              "SELECTION_BG",
              "FOCUS_RING",
              "ON_*",
              "MUTED_FOREGROUND",
              "STATUS_*",
              "COLD_HIGHLIGHT",
              "DESTRUCTIVE",
              "QUANTITY_*",
              "TEXT_*",
              "STONE_*",
              "SUCCESS_*",
              "WARNING_*",
              "DANGER_*",
              "QDARKTHEME_ACCENT",
              "PLOT_BG",
              "PLOT_FG",
              "PLOT_GRID_COLOR",
              "PLOT_GRID_ALPHA",
              "PLOT_LABEL_COLOR",
              "PLOT_TICK_COLOR",
              "PLOT_REGION_WARN_ALPHA",
              "PLOT_REGION_FAULT_ALPHA",
              "PLOT_LINE_PALETTE"
            ],
            "required_spec_paths": [
              "docs/design-system/tokens/colors.md"
            ]
          },
          {
            "name_patterns": [
              "FONT_*"
            ],
            "required_spec_paths": [
              "docs/design-system/tokens/typography.md"
            ]
          },
          {
            "name_patterns": [
              "SPACE_*",
              "CARD_PADDING",
              "GRID_GAP"
            ],
            "required_spec_paths": [
              "docs/design-system/tokens/spacing.md"
            ]
          },
          {
            "name_patterns": [
              "HEADER_HEIGHT",
              "TOOL_RAIL_WIDTH",
              "BOTTOM_BAR_HEIGHT",
              "ROW_HEIGHT"
            ],
            "required_spec_paths": [
              "docs/design-system/tokens/layout.md"
            ]
          },
          {
            "name_patterns": [
              "RADIUS_*",
              "QDARKTHEME_CORNER_SHAPE"
            ],
            "required_spec_paths": [
              "docs/design-system/tokens/radius.md"
            ]
          },
          {
            "name_patterns": [
              "TRANSITION_*_MS"
            ],
            "required_spec_paths": [
              "docs/design-system/tokens/motion.md"
            ]
          },
          {
            "name_patterns": [
              "PLOT_*"
            ],
            "required_spec_paths": [
              "docs/design-system/tokens/chart-tokens.md"
            ]
          }
        ]
      }
    ],    "routes": [

      {
        "source_pattern": "src/cryodaq/gui/_plot_style.py",
        "required_spec_paths": [
          "docs/design-system/tokens/chart-tokens.md"
        ]
      },
      {
        "source_pattern": "src/cryodaq/gui/_theme_loader.py",
        "required_spec_paths": [
          "docs/design-system/accessibility/contrast-matrix.md",
          "docs/design-system/tokens/colors.md"
        ]
      },
      {
        "source_pattern": "config/themes/*.yaml",
        "required_spec_paths": [
          "docs/design-system/accessibility/contrast-matrix.md",
          "docs/design-system/tokens/colors.md"
        ]
      },
      {
        "source_pattern": "src/cryodaq/gui/widgets/common.py",
        "required_spec_paths": [
          "docs/design-system/components/legacy-common-runtime.md"
        ]
      },
      {
        "source_pattern": "src/cryodaq/gui/shell/operator_components/*.py",
        "required_spec_paths": [
          "docs/design-system/cryodaq-primitives/operator-snapshot-components.md"
        ]
      },
      {
        "source_pattern": "src/cryodaq/gui/shell/overlays/_design_system/bento_grid.py",
        "required_spec_paths": [
          "docs/design-system/components/bento-grid.md"
        ]
      },
      {
        "source_pattern": "src/cryodaq/gui/shell/overlays/_design_system/drill_down_breadcrumb.py",
        "required_spec_paths": [
          "docs/design-system/components/breadcrumb.md"
        ]
      },
      {
        "source_pattern": "src/cryodaq/gui/shell/overlays/_design_system/modal_card.py",
        "required_spec_paths": [
          "docs/design-system/components/modal.md"
        ]
      },
      {
        "source_pattern": "src/cryodaq/gui/shell/overlays/_design_system/__init__.py",
        "required_spec_paths": [
          "docs/design-system/components/bento-grid.md",
          "docs/design-system/components/breadcrumb.md",
          "docs/design-system/components/modal.md"
        ]
      },
      {
        "source_pattern": "src/cryodaq/gui/shell/overlays/_design_system/_showcase.py",
        "required_spec_paths": [
          "docs/design-system/components/bento-grid.md",
          "docs/design-system/components/breadcrumb.md",
          "docs/design-system/components/modal.md"
        ]
      },
      {
        "source_pattern": "src/cryodaq/gui/presentation_severity.py",
        "required_spec_paths": [
          "docs/design-system/MANIFEST.md",
          "docs/design-system/patterns/state-visualization.md"
        ]
      },
      {
        "source_pattern": "src/cryodaq/gui/shell/operator_components/_visuals.py",
        "required_spec_paths": [
          "docs/design-system/MANIFEST.md",
          "docs/design-system/patterns/state-visualization.md"
        ]
      },
      {
        "source_pattern": "src/cryodaq/gui/shell/operator_components/status.py",
        "required_spec_paths": [
          "docs/design-system/MANIFEST.md",
          "docs/design-system/patterns/state-visualization.md"
        ]
      },
      {
        "source_pattern": "src/cryodaq/operator_snapshot.py",
        "required_spec_paths": [
          "docs/design-system/MANIFEST.md",
          "docs/design-system/patterns/state-visualization.md"
        ]
      },
      {
        "source_pattern": "src/cryodaq/gui/state/operator_view_models.py",
        "required_spec_paths": [
          "docs/design-system/MANIFEST.md",
          "docs/design-system/patterns/state-visualization.md"
        ]
      },
      {
        "source_pattern": "src/cryodaq/gui/tray_status.py",
        "required_spec_paths": [
          "docs/design-system/cryodaq-primitives/tray-status.md"
        ]
      },
      {
        "source_pattern": "src/cryodaq/gui/shell/views/operator_display.py",
        "required_spec_paths": [
          "docs/design-system/patterns/operator-display-composition.md"
        ]
      },
      {
        "source_pattern": "src/cryodaq/gui/shell/command_outcome.py",
        "required_spec_paths": [
          "docs/design-system/patterns/command-outcome-unknown.md"
        ]
      }
    ],
    "retired_routes": []
  },  "mechanical_accessibility": {
    "target": "WCAG 2.2 AA",
    "contrast_cases": [
      {
        "id": "body_foreground_card",
        "criterion": "1.4.3",
        "role": "body_text",
        "foreground": "FOREGROUND",
        "background": "SURFACE_CARD",
        "minimum": 4.5
      },
      {
        "id": "body_secondary_card",
        "criterion": "1.4.3",
        "role": "body_text",
        "foreground": "TEXT_SECONDARY",
        "background": "SURFACE_CARD",
        "minimum": 4.5
      },
      {
        "id": "body_muted_card",
        "criterion": "1.4.3",
        "role": "supplementary_text",
        "foreground": "MUTED_FOREGROUND",
        "background": "SURFACE_CARD",
        "minimum": 4.5
      },
      {
        "id": "focus_elevated",
        "criterion": "1.4.11",
        "role": "focus_boundary",
        "foreground": "FOCUS_RING",
        "background": "SURFACE_ELEVATED",
        "minimum": 3.0
      },
      {
        "id": "status_ok_card",
        "criterion": "1.4.11",
        "role": "status_chrome",
        "foreground": "STATUS_OK",
        "background": "SURFACE_CARD",
        "minimum": 3.0
      },
      {
        "id": "status_caution_card",
        "criterion": "1.4.11",
        "role": "status_chrome",
        "foreground": "STATUS_CAUTION",
        "background": "SURFACE_CARD",
        "minimum": 3.0
      },
      {
        "id": "status_fault_card",
        "criterion": "1.4.11",
        "role": "status_chrome",
        "foreground": "STATUS_FAULT",
        "background": "SURFACE_CARD",
        "minimum": 3.0
      },
      {
        "id": "status_info_card",
        "criterion": "1.4.11",
        "role": "status_chrome",
        "foreground": "STATUS_INFO",
        "background": "SURFACE_CARD",
        "minimum": 3.0
      },
      {
        "id": "status_stale_card",
        "criterion": "1.4.11",
        "role": "status_chrome",
        "foreground": "STATUS_STALE",
        "background": "SURFACE_CARD",
        "minimum": 3.0
      },
      {
        "id": "filled_fault",
        "criterion": "1.4.3",
        "role": "filled_pill_text",
        "foreground": "ON_DESTRUCTIVE",
        "background": "STATUS_FAULT",
        "minimum": 4.5
      },
      {
        "id": "filled_accent",
        "criterion": "1.4.3",
        "role": "primary_action_text",
        "foreground": "BACKGROUND",
        "background": "ACCENT",
        "minimum": 4.5
      },
      {
        "id": "legacy_caution_inverse",
        "criterion": "1.4.3",
        "role": "legacy_caution_fill_text",
        "foreground": "ON_PRIMARY",
        "background": "STATUS_CAUTION",
        "minimum": 4.5
      },
      {
        "id": "border_background",
        "criterion": "1.4.11",
        "role": "grouping_stroke",
        "foreground": "BORDER",
        "background": "BACKGROUND",
        "minimum": 3.0
      }
    ],
    "contrast_exceptions": [
      {
        "id": "A11Y-EX-001",
        "case_id": "body_muted_card",
        "themes": [
          "amber",
          "anthropic_mono",
          "braun",
          "gost",
          "instrument",
          "ochre_bloom",
          "rose_dusk",
          "signal",
          "taupe_quiet",
          "warm_stone",
          "xcode"
        ],
        "scope": "Supplementary or explicitly unavailable text only; never critical truth or action text.",
        "rationale": "The muted token intentionally de-emphasizes secondary evidence and is not a general body-text color.",
        "fallback_channels": [
          "FOREGROUND text",
          "explicit unavailable semantics"
        ],
        "human_verification": "Keyboard and NVDA walkthrough must confirm no required meaning depends on muted text alone.",
        "ratio_floors": {
          "amber": 3.7069,
          "anthropic_mono": 2.950593,
          "braun": 4.222376,
          "gost": 4.109723,
          "instrument": 3.725763,
          "ochre_bloom": 2.966639,
          "rose_dusk": 3.018188,
          "signal": 3.268795,
          "taupe_quiet": 3.210661,
          "warm_stone": 3.094435,
          "xcode": 3.851237
        }
      },
      {
        "id": "A11Y-EX-002",
        "case_id": "focus_elevated",
        "themes": [
          "amber",
          "anthropic_mono",
          "default_cool",
          "instrument",
          "ochre_bloom",
          "rose_dusk",
          "taupe_quiet",
          "warm_stone"
        ],
        "scope": "Known focus-ring gap on elevated operator controls.",
        "rationale": "FOCUS_RING does not reach 3:1 on the listed real packs and cannot be the only focus cue.",
        "fallback_channels": [
          "2px focus geometry",
          "ACCENT where the component contract permits"
        ],
        "human_verification": "Keyboard-only focus traversal remains required on the real Windows build.",
        "ratio_floors": {
          "amber": 2.170522,
          "anthropic_mono": 2.401728,
          "default_cool": 2.570572,
          "instrument": 2.10437,
          "ochre_bloom": 1.962009,
          "rose_dusk": 1.919218,
          "taupe_quiet": 2.354748,
          "warm_stone": 2.086325
        }
      },
      {
        "id": "A11Y-EX-003",
        "case_id": "status_fault_card",
        "themes": [
          "instrument",
          "ochre_bloom",
          "rose_dusk",
          "taupe_quiet"
        ],
        "scope": "Fault hue is chrome, never body or numeric text.",
        "rationale": "The listed packs miss 3:1 against card while preserving the canonical fault hue family.",
        "fallback_channels": [
          "\u0410\u0412\u0410\u0420\u0418\u042f text in FOREGROUND",
          "square or fault-border geometry"
        ],
        "human_verification": "Operator scenarios must confirm fault recognition without color.",
        "ratio_floors": {
          "instrument": 2.702978,
          "ochre_bloom": 2.946179,
          "rose_dusk": 2.951782,
          "taupe_quiet": 2.956365
        }
      },
      {
        "id": "A11Y-EX-004",
        "case_id": "status_stale_card",
        "themes": [
          "amber",
          "anthropic_mono",
          "default_cool",
          "instrument",
          "ochre_bloom",
          "rose_dusk",
          "signal",
          "taupe_quiet",
          "warm_stone"
        ],
        "scope": "Stale hue is de-emphasized chrome, never body or numeric text.",
        "rationale": "The stale token is deliberately quiet on dark cards, so text and hollow geometry are load-bearing.",
        "fallback_channels": [
          "\u0423\u0421\u0422\u0410\u0420\u0415\u041b\u041e text in FOREGROUND",
          "hollow-circle geometry"
        ],
        "human_verification": "Operator scenarios must distinguish stale from disconnected and current values.",
        "ratio_floors": {
          "amber": 2.297509,
          "anthropic_mono": 2.360812,
          "default_cool": 2.6456,
          "instrument": 2.019105,
          "ochre_bloom": 2.200774,
          "rose_dusk": 2.20496,
          "signal": 2.961427,
          "taupe_quiet": 2.208383,
          "warm_stone": 2.25824
        }
      },
      {
        "id": "A11Y-EX-005",
        "case_id": "filled_fault",
        "themes": [
          "default_cool"
        ],
        "scope": "Filled fault-pill text is supplementary in the affected pack.",
        "rationale": "ON_DESTRUCTIVE on STATUS_FAULT measures below 4.5:1 in default_cool.",
        "fallback_channels": [
          "adjacent FOREGROUND label",
          "fault icon or shape"
        ],
        "human_verification": "NVDA/manual review must confirm the adjacent label names the fault.",
        "ratio_floors": {
          "default_cool": 4.074971
        }
      },
      {
        "id": "A11Y-EX-006",
        "case_id": "filled_accent",
        "themes": [
          "braun"
        ],
        "scope": "Primary-action text on the Braun accent requires redundant action naming.",
        "rationale": "BACKGROUND on ACCENT measures below 4.5:1 only in the Braun pack.",
        "fallback_channels": [
          "accessible action name",
          "stable button geometry"
        ],
        "human_verification": "Manual keyboard and visual review must verify the primary action remains readable.",
        "ratio_floors": {
          "braun": 4.086638
        }
      },
      {
        "id": "A11Y-EX-007",
        "case_id": "legacy_caution_inverse",
        "themes": [
          "default_cool"
        ],
        "scope": "Legacy ON_PRIMARY caution-fill text is not a generally safe pair.",
        "rationale": "The default_cool pair measures below 4.5:1 and must remain supplementary pending migration.",
        "fallback_channels": [
          "adjacent FOREGROUND label",
          "caution triangle or text"
        ],
        "human_verification": "Manual review must confirm caution meaning without relying on the filled label.",
        "ratio_floors": {
          "default_cool": 2.568701
        }
      },
      {
        "id": "A11Y-EX-008",
        "case_id": "border_background",
        "themes": [
          "amber",
          "anthropic_mono",
          "braun",
          "default_cool",
          "gost",
          "instrument",
          "ochre_bloom",
          "rose_dusk",
          "signal",
          "taupe_quiet",
          "warm_stone",
          "xcode"
        ],
        "scope": "BORDER is grouping chrome only, never a functional boundary.",
        "rationale": "Every bundled pack keeps the quiet grouping stroke below the 3:1 functional-boundary threshold.",
        "fallback_channels": [
          "ACCENT focus boundary",
          "measured STATUS boundary",
          "surface luminance step"
        ],
        "human_verification": "Manual review must confirm grouping loss does not hide a control or state boundary.",
        "ratio_floors": {
          "amber": 1.418847,
          "anthropic_mono": 1.557383,
          "braun": 2.134742,
          "default_cool": 1.461852,
          "gost": 2.407457,
          "instrument": 1.856912,
          "ochre_bloom": 1.635669,
          "rose_dusk": 1.576828,
          "signal": 1.118236,
          "taupe_quiet": 1.438573,
          "warm_stone": 1.527526,
          "xcode": 1.385558
        }
      }
    ],
    "states": [
      {
        "source": "ok",
        "canonical": "ok",
        "token": "STATUS_OK",
        "label": "\u041d\u041e\u0420\u041c\u0410",
        "shape": "circle",
        "accessible_label": "\u041d\u043e\u0440\u043c\u0430"
      },
      {
        "source": "caution",
        "canonical": "caution",
        "token": "STATUS_CAUTION",
        "label": "\u0412\u041d\u0418\u041c\u0410\u041d\u0418\u0415",
        "shape": "triangle",
        "accessible_label": "\u0422\u0440\u0435\u0431\u0443\u0435\u0442 \u0432\u043d\u0438\u043c\u0430\u043d\u0438\u044f"
      },
      {
        "source": "warning",
        "canonical": "caution",
        "token": "STATUS_CAUTION",
        "label": "\u0412\u041d\u0418\u041c\u0410\u041d\u0418\u0415",
        "shape": "triangle",
        "accessible_label": "\u0422\u0440\u0435\u0431\u0443\u0435\u0442 \u0432\u043d\u0438\u043c\u0430\u043d\u0438\u044f"
      },
      {
        "source": "fault",
        "canonical": "fault",
        "token": "STATUS_FAULT",
        "label": "\u0410\u0412\u0410\u0420\u0418\u042f",
        "shape": "square",
        "accessible_label": "\u0410\u0432\u0430\u0440\u0438\u044f"
      },
      {
        "source": "stale",
        "canonical": "stale",
        "token": "STATUS_STALE",
        "label": "\u0423\u0421\u0422\u0410\u0420\u0415\u041b\u041e",
        "shape": "hollow_circle",
        "accessible_label": "\u0414\u0430\u043d\u043d\u044b\u0435 \u0443\u0441\u0442\u0430\u0440\u0435\u043b\u0438"
      },
      {
        "source": "disconnected",
        "canonical": "disconnected",
        "token": "STATUS_STALE",
        "label": "\u041d\u0415\u0422 \u0421\u0412\u042f\u0417\u0418",
        "shape": "diamond",
        "accessible_label": "\u041d\u0435\u0442 \u0441\u0432\u044f\u0437\u0438"
      }
    ]
  }
}
```
<!-- MACHINE_GATES:END -->

## Statistics

- **87 Markdown files in the design-system tree**: 83 contract/specification
  documents plus README, MANIFEST, CHANGELOG, and the GUI migration inventory;
  `VERSION` is the additional non-Markdown release marker; the executable gate data is embedded below in this tracked manifest.
- **84 rule IDs** across 9 rule categories (79 widget rules plus 5 governance rules)
- **14 generic components** specified (Batch 3)
- **19 CryoDAQ domain primitives** specified (Batch 4 + F36 + tray contract)
- **13 cross-surface patterns** specified (including operator evidence
  retention and the command-outcome-unknown mutation-uncertainty pattern)
- **5 accessibility documents** (Batch 6)
- **7 governance documents** (including mandatory change-impact review)
- **77 color/runtime-color constants** inventoried from theme.py (includes RING + SUCCESS_400 / WARNING_400 / DANGER_400 chart series additions; Phase III.A added ON_ACCENT, SELECTION_BG, and FOCUS_RING — see `adr/002-accent-status-decoupling.md`)
- **142 exported uppercase runtime constants** (colors 77 + typography 36 + spacing 9 + layout 7 + radius 5 + motion 3 + quantity 4 + corner-shape 1)

## Cross-reference health

- All RULE-COLOR, RULE-SURF, RULE-TYPO, RULE-SPACE, RULE-INTER, RULE-DATA, RULE-A11Y, RULE-COPY, RULE-GOV references **satisfied** (no forward refs)
- All code blocks balanced
- All hex values either reference theme.py tokens, appear in bad-example context, or are documented exceptions (e.g. `#a53838` DESTRUCTIVE_PRESSED placeholder tracked for promotion to token)
- Latin T in channel-ID context appears only in lint-pattern documentation (`testing-strategy.md`) and explicit bad-example counterexamples

## Key design decisions encoded

1. **Desaturated industrial dark palette** — NOT Tailwind-like. STATUS_OK=#4a8a5e forest green, not green-500.
2. **ACCENT is UI-activation affordance** (Phase III.A decoupling; prior: «locked to focus/selection only»). Primary button background, active tab underline, active ToolRail slot indicator, progress chunks for user-triggered tasks, focused-input border. NOT a status (use STATUS_*). Active phase may use ACCENT; completed phase stays neutral. NOT a hover state (use MUTED background). `SELECTION_BG` / `FOCUS_RING` (Phase III.A neutrals) carry selection / focus when accent bleed would collide with chrome. See `adr/002-accent-status-decoupling.md`.
3. **STONE_* legacy tokens — read-only in new code** — zero breaking change policy.
4. **3 surface brightness levels max** — BACKGROUND, CARD, SECONDARY. No 4th level.
5. **Radius scale tight** — NONE=0, SM=4, MD=6, LG=8, FULL=9999. No RADIUS_XL.
6. **Zero-shadow policy** — single exception for modal cards.
7. **Default-dark measured body contrast** — STATUS_OK (4.67:1), canonical caution (6.24:1), STATUS_INFO (5.81:1), and COLD_HIGHLIGHT (8.71:1) pass; STATUS_FAULT (3.94:1) and STATUS_STALE (2.94:1) fail and stay out of numeric value text.
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
21. **TopWatchBar names physical references, never comparative Tmin/Tmax** — `Т 2-й ступени` is Т12 and `Т плиты N₂` is Т11. Both are positionally fixed; other channels may move between experiments.
22. **Mode badge (Эксперимент / Отладка)** always visible — operator always knows whether actions have real-world effect vs debug-only.
23. **ToolRail is icon-only + tooltip mandatory** — 9 slots, Ctrl+[1-9] shortcuts, Ctrl+L alias for Journal.
24. **FSM states displayed lowercase** in BottomStatusBar — `safe_off`, `fault_latched` — per absolute codebase rule.
25. **SensorCell value stays FOREGROUND in fault** — uses border + icon for fault signal (avoids RULE-A11Y-003 contrast fail on STATUS_FAULT body text).
26. **Phase progress never consumes STATUS_OK** — active uses ACCENT and
    completed phases use neutral filled chrome; health remains a separate fact.
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
40. **Operator severity staircase** — safe/caution/fault. Legacy `warning` is accepted only as an explicit compatibility alias for caution; stale/disconnected and acknowledgement are orthogonal facts, never severity substitutions.
41. **2 Hz UI update cap** — regardless of engine sample rate; coalesce via QTimer per `patterns/real-time-data.md`.
42. **Stale ≠ hidden** — stale values keep last-known + dim color + tooltip explaining freshness age.
43. **Initial-empty ≠ stale** — «Ожидание первого измерения» (TEXT_DISABLED) vs «Устарело NN с» (STATUS_STALE).
44. **Desktop operator scope with responsive truth preservation** — logical DPI and available width drive vertical reflow/density; no value/status/provenance may be clipped without a complete accessible path.
45. **Grid density may adapt without hiding or reordering sensors** — deliberate evidence-region scrolling is allowed; automatic channel hiding is forbidden.
46. **Protection matches shipped authority** — use the implemented and tested
    cancel-default modal or, only where actually shipped, a reviewed
    HoldConfirm gesture. Never generalize a proposed hold to every emergency.
47. **Directional safety in toggles** — enable destructive (confirm), disable safe (no confirm).
48. **No «Don't show again» checkboxes** — creates state divergence + training regressions. Fix root cause instead.
49. **Current emergency action is visible, not global** — `Ctrl+K` opens the
    Keithley panel; its visible «АВАР. ОТКЛ.» action uses a cancel-default modal.
    A global or hold gesture remains an open hazard decision and MUST NOT be
    taught as shipped behavior.
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
60. **No unimplemented destructive-keyboard promise** — accessibility guidance
    documents only shipped activation. Any future HoldConfirm keyboard gesture
    requires implementation, discoverability, tests, and hazard review before
    becoming canonical.
61. **Reduced motion respect via MotionPolicy** — centralized helper; duration=0 under reduce. HoldConfirm becomes discrete-step progress (safety preserved).
62. **Design system remains flat-token in the current v4.2.0 line** — the v2.0.0
    instrument-identity major and v3.0.0 composition-contract major did not
    perform the separately reviewed future three-layer token migration.
63. **STONE_* remains deprecated/read-only in the current v4.2.0 line** — neither
    major claims or performs the unfinished cross-panel token migration.
64. **SemVer independent from CryoDAQ package version** — design system evolves at its own cadence; CHANGELOG cross-references.
65. **Architect is singular approval gate** — drafts and audits converge on Vladimir's approval before implementation. No self-approval.
66. **ACCENT ≠ STATUS_OK — Phase III.A decoupling** — per `adr/002-accent-status-decoupling.md`. Primary buttons, mode badges, progress chunks, active tab indicators use ACCENT (UI activation). STATUS_OK reserved for safety / health / channel-OK indicators. `SELECTION_BG` + `FOCUS_RING` added as neutral interaction tokens. Per-theme ACCENT recalibrated to warm-neutral (11 themes; `default_cool` indigo preserved as historical baseline).

F36 operator-snapshot additions:

67. **Pure snapshot presentation** — F36 components accept typed immutable summaries only; they do not import transport, routes, commands, or SafetyManager.
68. **Atomic revision render** — status, content, freshness, and provenance belong to one revision; lower revisions and same-revision changed truth are rejected.
69. **Navigation intent only** — the next-action control emits a bounded typed destination request and performs no route or plant action itself.
70. **Bounded text without hidden authority** — visible hostile text is bounded with both ends, an explicit marker, and digest; the complete plain value remains accessible.
71. **Fleet virtualization** — attention queues use Qt model/view and uniform delegate rows at the 2,000-item public bound.
72. **Transactional child preflight** — card and footer stage render plans and recheck every baseline before the first widget mutation; child rejection cannot tear parent/child truth.
73. **Plain-safe Qt text boundary** — backend markup/entities are HTML-escaped inside owned tooltip chrome, while C0/C1 and bidi-format controls become visible code-point markers.
74. **Strict navigation intent** — logical IDs use a bounded ASCII grammar; NFC operator copy rejects markup, control, and bidi-format characters.
75. **Owner-bound typed card body** — an optional `AttentionList` is constructor-bound to its card, consumes the same `AttentionQueue` plan, rejects independent render/model replacement, and commits with parent/footer as one revision; arbitrary QWidget bodies are prohibited.
76. **First-presentation barrier** — staged pre-rendered body/footer truth stays hidden behind explicit disconnected/unavailable shell state until the first coherent card commit; unexpected Qt reveal failure hides and permanently fails the card instance closed.
77. **Root-owned POD composition** — all eight composed cards reject standalone render; one root transaction rechecks and commits their exact immutable cut.
78. **Post-commit coherence barrier** — synchronous Qt callbacks cannot silently tear sibling truth; a mismatch permanently replaces the page with a non-authoritative failure barrier.
79. **Complete bounded attention geometry** — two-line rows remain fully legible, with four visible rows and deterministic scrolling across at most eight projected items.
80. **Truthful scenario scope** — composition tests do not claim later acknowledgement, recovery, capture, or human-performance tasks; software POD cutover and replay mutation gates are implemented, while scenario and external evidence remain open.
81. **Descriptor-qualified instrument identity** — the generic instrument-health
    panel attributes cards only from authoritative connected `DescriptorView`
    values; missing/refused identity uses fixed bounded Russian text and no
    vendor, model, channel-name, diagnostic, or payload fallback.

82. **Co-versioned semantic authority** — a change to a mapped shared token, theme pack, component, pattern, or state owner must change its canonical specification, `VERSION`, and `CHANGELOG.md` in the same immutable-base slice. `theme.py` public Assign/AnnAssign/AugAssign/Delete deltas select exact category specs and multiple categories accumulate; unclassified symbols and every other residual semantic AST delta require the aggregate plus full owned set. Real-theme WCAG exceptions live as exact machine data, while keyboard/NVDA/operator/performance evidence remains human.

## Status

**Design system v4.2.0 — the F36.6 co-versioning and mechanical accessibility gate is active for mapped shared semantic authorities; panoramic dashboard home, descriptor-qualified identity, and the supplemental atomic briefing remain implemented, while manual and target-environment evidence stays open in `GUI_MIGRATION_INVENTORY.md`.** Existing
84 rules (79 widget rules plus 5 governance rules) and the 142-constant runtime inventory are tracked. Real Windows
ONEDIR whole-shell/DPI/NVDA, keyboard walkthrough, scripted operator, operator-performance, and long-session evidence
remain open.
