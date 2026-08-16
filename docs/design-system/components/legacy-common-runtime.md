---
title: Legacy Common Runtime Authority
keywords: legacy, common, widget, helper, status, button, panel, table, plot
applies_to: src/cryodaq/gui/widgets/common.py
status: canonical
implements: src/cryodaq/gui/widgets/common.py
last_updated: 2026-08-10
references: card.md, button.md, input-field.md, ../patterns/state-visualization.md, ../patterns/real-time-data.md, ../tokens/chart-tokens.md
---

# Legacy Common Runtime Authority

`src/cryodaq/gui/widgets/common.py` is a compatibility module containing several unrelated shipped helpers. This file is its exact co-versioned specification; it does not pretend those helpers are operator-snapshot components.

| Runtime owner | Canonical contract |
|---|---|
| `setup_standard_table` | Read-only, single-row table interaction; `input-field.md` interaction conventions apply |
| `build_action_row`, `add_form_rows`, `create_panel_root` | Existing layout order and spacing semantics; `button.md` / `input-field.md` apply to their children |
| `StatusBanner`, `apply_status_label_style` | `state-visualization.md`; text remains present and color is not sole state authority |
| `apply_button_style` | `button.md`; neutral/primary/warning/danger compatibility variants stay explicit |
| `apply_group_box_style`, `apply_panel_frame_style`, `PanelHeader` | `card.md`; token-based surface, border, radius, title, and subtitle treatment |
| `snap_x_range` | `real-time-data.md` and `chart-tokens.md`; bounded live-window range without leading empty space |

A semantic or API change to any listed class/helper must update this authority map in the same design-system release and update the referenced component/pattern spec when that public contract changes. New helpers belong in a precise component module when one exists; this compatibility aggregate is not a destination for new architecture.