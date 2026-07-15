---
title: GUI v3 Migration Inventory
status: canonical
last_updated: 2026-07-15
references: README.md, governance/testing-strategy.md, governance/performance-budget.md, accessibility/wcag-baseline.md
---

# GUI v3 migration inventory

This is the auditable backlog for the design-system v3.0.1 corpus-wide
informative-and-beautiful composition contract. It inventories every
operator-visible production surface under `src/cryodaq/gui`; non-visual state,
transport, buffers, and package/bootstrap modules are covered through the
surface that renders them. A new operator-visible surface must be added here in
the same slice that introduces it.

Status values:

- `pending-v3-audit` — reachable production surface, not yet accepted against
  the complete v3 gate;
- `in-review` — a frozen implementation/evidence slice has an assigned
  independent reviewer;
- `v3-accepted` — operator scenarios, accessibility, performance, visual
  composition, and truthful state semantics have reviewed evidence linked in
  the Evidence column;
- `reference-only` — design-system showcase/helper, not a production operator
  surface.

No surface is grandfathered. Token use, unit tests, or a screenshot alone do
not qualify as `v3-accepted`.

| Surface | Production owner(s) | Status | Evidence required before v3 acceptance |
|---|---|---|---|
| Application shell and navigation | `shell/main_window_v2.py`, `shell/navigation.py`, `shell/overlay_container.py` | pending-v3-audit | Software POD home cutover and reviewed 1280x800 source visual QA complete at `5935575`; remaining: full-shell scenarios, focus order, DPI/ONEDIR visual QA, startup/frame/memory budgets |
| Top watch bar | `shell/top_watch_bar.py` | pending-v3-audit | Landmark truth; stale/disconnected states; contrast/non-color cues; visual hierarchy |
| Tool rail | `shell/tool_rail.py` | pending-v3-audit | Keyboard navigation; selected/disabled cues; target sizing; visual rhythm |
| Bottom status bar | `shell/bottom_status_bar.py` | pending-v3-audit | Provenance/freshness truth; clipping; quiet-normal/loud-exception hierarchy |
| Primary Operator Display | `shell/views/operator_display.py`, `shell/operator_components/*` | pending-v3-audit | Coherent-cut/one-owner runtime and source visual QA complete through `5935575`; remaining: all 12 F36 scenarios, zero false-safe operator evidence, keyboard/NVDA, bounded fleet, performance and ONEDIR whole-page visual QA |
| Dashboard composition | `dashboard/dashboard_view.py`, `dashboard/dynamic_sensor_grid.py` | pending-v3-audit | Fleet scaling; task hierarchy; empty/stale/fault states; visual composition |
| Experiment card and phase content | `dashboard/experiment_card.py`, `dashboard/phase_aware_widget.py`, `dashboard/phase_stepper.py`, `dashboard/phase_content/*` | pending-v3-audit | Experiment lifecycle scenarios; legibility; phase semantics; keyboard and layout QA |
| Dashboard plots and quick log | `dashboard/temp_plot_widget.py`, `dashboard/pressure_plot_widget.py`, `dashboard/quick_log_block.py` | pending-v3-audit | Sampling/aggregation; no misleading interpolation; keyboard/text alternatives; frame budget |
| Sensor cell | `dashboard/sensor_cell.py` | pending-v3-audit | Canonical states; unknown/stale rendering; contrast; dense-grid legibility |
| Experiment overlay | `shell/experiment_overlay.py` | pending-v3-audit | Create/start/phase/finalize scenarios; failure truth; focus containment; visual QA |
| New experiment dialog | `shell/new_experiment_dialog.py` | pending-v3-audit | Validation/error recovery; keyboard-only completion; destructive-action clarity |
| First-run wizard | `first_run_wizard.py` | pending-v3-audit | Registry-driven fields; source defaults OFF; labels/buddies/focus; visual composition and error states |
| Alarm panel | `shell/overlays/alarm_panel.py` | pending-v3-audit | Alarm/ack/recovery scenarios; non-color severity; keyboard/NVDA; loud-exception hierarchy |
| Archive panel | `shell/overlays/archive_panel.py` | pending-v3-audit | Empty/busy/error/export states; path clarity; keyboard; large-archive performance |
| Calibration panel | `shell/overlays/calibration_panel.py` | pending-v3-audit | Setup/acquisition/results scenarios; raw-data provenance; focus; plots and dense-state visual QA |
| Conductivity panel | `shell/overlays/conductivity_panel.py` | pending-v3-audit | Source-readback truth; no optimistic control state; keyboard; plot/readout hierarchy |
| Instruments panel | `shell/overlays/instruments_panel.py` | pending-v3-audit | Descriptor-qualified identity; refused/capacity/stale states; fleet scaling; visual QA |
| Keithley/source panel | `shell/overlays/keithley_panel.py` | pending-v3-audit | Verified-OFF and safety readiness; no optimistic state; keyboard; non-color cues; visual QA |
| MultiLine panel and selector | `shell/overlays/multiline_panel.py`, `shell/overlays/multiline_channel_selector.py` | pending-v3-audit | Descriptor routing; selection/search; stale states; fleet scaling; keyboard and visual QA |
| Knowledge and assistant chat | `shell/overlays/knowledge_base_panel.py`, `shell/overlays/_assistant_chat_widget.py` | pending-v3-audit | Observational-only boundary; hostile/bounded text; focus; empty/error states; visual QA |
| Operator log | `shell/overlays/operator_log_panel.py` | pending-v3-audit | Ordering/provenance; long-text behavior; keyboard; large-log performance |
| Cooldown baseline card | `shell/overlays/cooldown_baseline_card.py` | pending-v3-audit | Uncertainty and verdict semantics; non-color cues; clipping; visual QA |
| Composition photos and detail dialog | `shell/composition_photos_widget.py` | pending-v3-audit | Missing/failed image states; caption provenance; keyboard; memory and visual QA |
| Analytics view | `shell/views/analytics_view.py` | pending-v3-audit | Intent hierarchy; lazy replay; stale/error states; navigation/focus; whole-view visual QA |
| Analytics widgets | `shell/views/analytics_widgets.py` | pending-v3-audit | Per-widget truthful semantics; cold-stage authority; plot legibility; worker cleanup; frame/memory budgets |
| Assistant insight panel | `shell/views/assistant_insight_panel.py` | pending-v3-audit | Observational-only copy; provenance/freshness; bounded text; keyboard and visual QA |
| Channel editor | `widgets/channel_editor.py` | pending-v3-audit | Validation; keyboard; error recovery; no hidden state; visual QA |
| Shared prediction/pressure/time-window widgets | `widgets/shared/*`, `state/time_window_selector.py` | pending-v3-audit | Cross-surface consistency; plot/text alternatives; keyboard; performance |
| Common status banner and panel header | `widgets/common.py` | pending-v3-audit | Canonical states; contrast; accessible names; reusable visual anatomy |
| Tray status | `tray_status.py` | pending-v3-audit | State mapping; non-color/text cues; disconnect/fault behavior; platform visual QA |
| Design-system showcase helpers | `shell/overlays/_design_system/*` | reference-only | Examples must remain synchronized with accepted tokens/components/patterns |

## Acceptance update rule

A reviewed slice changes only the rows it actually proves. The row moves to
`v3-accepted` only with a stable evidence link naming exact tests, platform,
operator scenarios, accessibility checks, performance measurements, visual QA,
and unresolved external/physical gates. Partial evidence stays in the row as a
note while status remains `pending-v3-audit` or `in-review`.
