# Preserve Features Verification

Date: 2026-04-16  
Branch: `master`  
HEAD at verification start: `efcd764`

This document verifies the three preserve features that remained unanchored
after the Phase 0 legacy-inventory fixes:

- K7: phase detector
- K6: HDF5 + Excel export paths
- K4: Keithley custom commands

The goal here is factual verification against source code, not re-audit.

---

## K7 — Phase Detector plugin

### What exists in code

K7 exists in the repository as a root-level analytics plugin, not as a module
under `src/cryodaq/plugins/`.

- `plugins/phase_detector.py:1-6` describes the component as an automatic
  experiment phase detector that is read-only and publishes `DerivedMetric`
  values for GUI display.
- `plugins/phase_detector.py:31-47` defines `PhaseDetector` with
  `plugin_id = "phase_detector"`.
- `plugins/phase_detector.py:136-149` publishes:
  - `detected_phase`
  - `dT_dt_K_per_min`
  - `phase_confidence`
  - `stable_at_target_s`
- `plugins/phase_detector.yaml:1-10` provides runtime configuration for
  temperature channel, pressure channel, target temperature, and thresholds.

The engine-side analytics pipeline does load root-level plugins:

- `src/cryodaq/analytics/plugin_loader.py:75-90` loads every `*.py` file from
  the configured plugins directory.
- `src/cryodaq/analytics/plugin_loader.py:263-287` republishes plugin output as
  `Reading` objects on `analytics/<plugin_id>/<metric>`.
- `src/cryodaq/engine.py:1353-1457` constructs and starts `PluginPipeline`.

### What does not exist in GUI

The current GUI does not consume `analytics/phase_detector/*`.

- Repo search found no GUI/web consumers of `phase_detector`,
  `detected_phase`, or `phase_confidence`.
- `src/cryodaq/gui/dashboard/dashboard_view.py:181-183` forwards all
  `analytics/*` readings to `PhaseAwareWidget`, but
  `src/cryodaq/gui/dashboard/phase_aware_widget.py:342-356` only uses:
  - `/cooldown_eta`
  - `/R_thermal`
  - `/pressure`
- `src/cryodaq/gui/dashboard/phase_aware_widget.py:308-336` derives the shown
  phase strip from `experiment_status.current_phase`, not from
  `phase_detector` metrics.

So the plugin exists, but the specific “phase progression suggestion” surface
described in `ui_refactor_context.md` is not currently implemented in GUI.

### Verdict

**K7 = EXISTS+ENGINE-ONLY**

### File:line evidence

- [plugins/phase_detector.py:1](/Users/vladimir/Projects/cryodaq/plugins/phase_detector.py#L1)
- [plugins/phase_detector.py:31](/Users/vladimir/Projects/cryodaq/plugins/phase_detector.py#L31)
- [plugins/phase_detector.py:136](/Users/vladimir/Projects/cryodaq/plugins/phase_detector.py#L136)
- [plugins/phase_detector.yaml:1](/Users/vladimir/Projects/cryodaq/plugins/phase_detector.yaml#L1)
- [plugin_loader.py:75](/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/plugin_loader.py#L75)
- [plugin_loader.py:263](/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/plugin_loader.py#L263)
- [engine.py:1353](/Users/vladimir/Projects/cryodaq/src/cryodaq/engine.py#L1353)
- [dashboard_view.py:181](/Users/vladimir/Projects/cryodaq/src/cryodaq/gui/dashboard/dashboard_view.py#L181)
- [phase_aware_widget.py:342](/Users/vladimir/Projects/cryodaq/src/cryodaq/gui/dashboard/phase_aware_widget.py#L342)

### Implication for roadmap

Do not treat K7 as a current GUI preserve anchor. The codebase contains the
analytics plugin, but not the promised overlay highlight / suggested-next-phase
surface. Roadmap language should describe K7 as a background analytics feature
that still needs explicit UI integration if Phase I/II intends to preserve it
visibly.

---

## K6 — Export CSV / HDF5 / Excel

### What exists in code

CSV/HDF5/Excel export does exist, but the HDF5 and Excel paths live in the
legacy main window File menu, outside the 10 audited legacy tab inventories.

Legacy File menu actions:

- `src/cryodaq/gui/main_window.py:174-186`
  - `Экспорт CSV...`
  - `Экспорт HDF5...`
  - `Экспорт Excel...`

Legacy export handlers:

- `src/cryodaq/gui/main_window.py:432-449` → CSV export via `CSVExporter`
- `src/cryodaq/gui/main_window.py:452-463` → HDF5 export via `HDF5Exporter`
- `src/cryodaq/gui/main_window.py:466-476` → Excel export via `XLSXExporter`

Storage implementations:

- `src/cryodaq/storage/hdf5_export.py:37-107` exports one daily SQLite file to
  one `.h5` file.
- `src/cryodaq/storage/xlsx_export.py:19-139` exports SQLite data to an Excel
  workbook via `openpyxl`.

There is also a separate widget-local CSV export path:

- `src/cryodaq/gui/widgets/conductivity_panel.py:218-220` wires `Экспорт CSV`
  button to `_on_export`.

### Format-by-format verdict

- **CSV:** EXISTS+LOCATED
- **HDF5:** EXISTS+LOCATED
- **Excel:** EXISTS+LOCATED

### File:line evidence

- [main_window.py:174](/Users/vladimir/Projects/cryodaq/src/cryodaq/gui/main_window.py#L174)
- [main_window.py:432](/Users/vladimir/Projects/cryodaq/src/cryodaq/gui/main_window.py#L432)
- [main_window.py:452](/Users/vladimir/Projects/cryodaq/src/cryodaq/gui/main_window.py#L452)
- [main_window.py:466](/Users/vladimir/Projects/cryodaq/src/cryodaq/gui/main_window.py#L466)
- [hdf5_export.py:37](/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/hdf5_export.py#L37)
- [xlsx_export.py:19](/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/xlsx_export.py#L19)
- [conductivity_panel.py:218](/Users/vladimir/Projects/cryodaq/src/cryodaq/gui/widgets/conductivity_panel.py#L218)

### Implication for roadmap

K6 should not be modeled as “only conductivity CSV” and should not be attached
only to Archive overlay. Legacy K6 is split across:

- File-menu exports for CSV/HDF5/Excel
- widget-local CSV export in Conductivity

Roadmap language should preserve the legacy File-menu export surface explicitly,
or explicitly plan where those global exports move in the new shell.

---

## K4 — Keithley custom commands

### What exists in code

The Keithley GUI does provide direct structured control:

- per-channel `P цель`, `V предел`, `I предел`
- per-channel `Старт` / `Стоп` / `АВАР. ОТКЛ.`
- panel-level `Старт A+B` / `Стоп A+B` / `АВАР. ОТКЛ. A+B`

Evidence:

- `src/cryodaq/gui/widgets/keithley_panel.py:127-149` defines structured
  setpoint/limit controls.
- `src/cryodaq/gui/widgets/keithley_panel.py:316-380` sends structured
  `keithley_start`, `keithley_stop`, and emergency commands through
  `ZmqCommandWorker`.
- `src/cryodaq/gui/widgets/keithley_panel.py:489-559` defines the A+B controls.

### What does not exist in code

I did not find a GUI surface for arbitrary custom Keithley commands.

- `src/cryodaq/gui/widgets/keithley_panel.py:12-20` imports no `QLineEdit` or
  text editor widget for raw command entry.
- Repo searches found no GUI methods named `send_raw`, `execute_command`,
  `raw_command`, `custom_command`, or similar command-console pattern.
- `autosweep_panel.py` does send Keithley commands, but only structured
  `keithley_start` / `keithley_stop` payloads for the autosweep workflow, not
  arbitrary TSP/SCPI input (`src/cryodaq/gui/widgets/autosweep_panel.py:387`,
  `src/cryodaq/gui/widgets/autosweep_panel.py:411-417`,
  `src/cryodaq/gui/widgets/autosweep_panel.py:426`).

### Verdict

**K4 custom-command subfeature = NOT FOUND IN GUI**

### File:line evidence

- [keithley_panel.py:12](/Users/vladimir/Projects/cryodaq/src/cryodaq/gui/widgets/keithley_panel.py#L12)
- [keithley_panel.py:127](/Users/vladimir/Projects/cryodaq/src/cryodaq/gui/widgets/keithley_panel.py#L127)
- [keithley_panel.py:316](/Users/vladimir/Projects/cryodaq/src/cryodaq/gui/widgets/keithley_panel.py#L316)
- [keithley_panel.py:489](/Users/vladimir/Projects/cryodaq/src/cryodaq/gui/widgets/keithley_panel.py#L489)
- [autosweep_panel.py:387](/Users/vladimir/Projects/cryodaq/src/cryodaq/gui/widgets/autosweep_panel.py#L387)
- [autosweep_panel.py:411](/Users/vladimir/Projects/cryodaq/src/cryodaq/gui/widgets/autosweep_panel.py#L411)

### Implication for roadmap

Roadmap text should stop claiming that legacy GUI already preserves a visible
custom-command surface. What exists is direct operational control, not a raw
command console. If operators still need arbitrary TSP/SCPI entry, that is a
separate backlog item that must be explicitly designed rather than “preserved”.
