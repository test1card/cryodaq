---
title: Runtime Token Authority
keywords: runtime, theme, token, authority, ownership, mapping
applies_to: src/cryodaq/gui/theme.py
status: canonical
implements: src/cryodaq/gui/theme.py
last_updated: 2026-08-10
references: colors.md, typography.md, spacing.md, layout.md, radius.md, motion.md, chart-tokens.md
---

# Runtime Token Authority

`src/cryodaq/gui/theme.py` is the one monolithic runtime owner for several token families. This map is its exact co-versioned specification; it prevents a change in one family from being falsely covered by an unrelated category document.

| Runtime symbols or section | Canonical category specification |
|---|---|
| Theme-pack colors, surfaces, borders, interaction, status, quantity, `STONE_*`, and color aliases | `colors.md` |
| `FONT_*` families and typography aliases | `typography.md` |
| `SPACE_*`, `CARD_PADDING`, and `GRID_GAP` | `spacing.md` |
| `HEADER_HEIGHT`, `TOOL_RAIL_WIDTH`, `BOTTOM_BAR_HEIGHT`, and `ROW_HEIGHT` | `layout.md` |
| `RADIUS_*` and `QDARKTHEME_CORNER_SHAPE` | `radius.md` |
| `TRANSITION_*_MS` | `motion.md` |
| `PLOT_BG`, `PLOT_FG`, `PLOT_GRID_COLOR`, `PLOT_GRID_ALPHA`, `PLOT_LABEL_COLOR`, `PLOT_TICK_COLOR`, `PLOT_REGION_WARN_ALPHA`, `PLOT_REGION_FAULT_ALPHA`, and `PLOT_LINE_PALETTE` | `colors.md` and `chart-tokens.md` |
| Other `PLOT_*` chart geometry, including `PLOT_AXIS_WIDTH_PX`, `PLOT_LINE_WIDTH`, and `PLOT_LINE_WIDTH_HIGHLIGHTED` | `chart-tokens.md` |

The two PLOT routes intentionally overlap only for the nine symbols whose color aliases, palette, or alpha values are also canonical in `colors.md`. All `PLOT_*` symbols remain governed by `chart-tokens.md`; the three current geometry/width symbols above do not acquire an unrelated color-specification obligation.

A changed, added, or removed top-level public symbol operation in `theme.py` — `Assign`, annotated assignment, `AugAssign`, or `del NAME` — must update this aggregate and the category specification selected by the machine-readable symbol map in `MANIFEST.md`. Multiple changed categories accumulate. An unclassified public symbol conservatively requires every category in this table until the map is extended. Any other residual semantic AST change also requires this aggregate and every owned category, because a loop, call, or dynamic construct can mutate runtime tokens indirectly. An AST-equivalent comment-only edit adds no semantic specification requirement. Backward-compatibility aliases inherit the category of their canonical target; they do not create a separate authority family.

Helpers that load/configure the table (`_hex_to_rgba`, `qdarktheme_kwargs`, and pyqtgraph configuration) remain governed here because they determine how the listed runtime values are materialized.