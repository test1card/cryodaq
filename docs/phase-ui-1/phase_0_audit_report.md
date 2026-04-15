# Phase 0 Legacy Inventory — Codex Adversarial Audit Report

Date: 2026-04-16
Auditor: Codex CLI gpt-5.4 high reasoning
Scope: 10 inventories at `docs/legacy-inventory/` vs source code at `src/cryodaq/gui/widgets/`

## Overall verdict

FIX FIRST.

These inventories are not garbage, but they are not trustworthy enough to serve as Phase I primitive input without cleanup. The strongest failures are not line-range drift; they are factual errors about live UI surface, missing control paths, and invented data contracts. The most problematic docs are `alarms.md`, `analytics.md`, `calibration.md`, `keithley.md`, `instruments.md`, and `sensor_diag.md`.

## Per-inventory findings

### overview.md
- LOC accuracy: pass. Claimed `1729`; actual `1729`.
- Section ranges: pass. Major class boundaries are broadly correct.
- Class/method existence: pass. `StatusStrip`, `CompactTempCard`, `TempCardGrid`, `PressureCard`, `KeithleyStrip`, `ExperimentStatusWidget`, `QuickLogWidget`, `OverviewPanel` all exist.
- ZMQ commands: partial. `experiment_status`, `log_entry`, `log_get`, `readings_history` exist, but `experiment_status` is not a `2Hz` `StatusStrip` poll. It is a `5000 ms` poll in `ExperimentStatusWidget` at `src/cryodaq/gui/widgets/overview_panel.py:838-855`.
- Russian text drift: fail. Inventory describes quick log as `[QLineEdit "Запись..."] [QPushButton "↵"]`; actual UI is `Журнал:`, placeholder `Заметка оператора...`, button `Записать` at `src/cryodaq/gui/widgets/overview_panel.py:918-939`. Inventory also says status strip shows `Time`; actual widget shows `Аптайм`.
- Live subscriptions accurate: partial. `analytics/cooldown_eta`, `analytics/cooldown_eta_hours`, `analytics/safety_state`, `analytics/alarm_count`, Keithley channels are accurate. Pressure is not strict `*/pressure`; code updates pressure on any reading with `unit == "mbar"` at `src/cryodaq/gui/widgets/overview_panel.py:1358-1364`.
- Workflows plausible: partial. Quick note and time window workflows are real, but the inventory under-describes the recent-entry strip and over-simplifies log UI.
- Recommendations grounded: partial. ML curve and card-toggle preservation are grounded; “TopWatchBar/BottomStatusBar already cover duplicates” is directionally right.
- Coverage claims accurate: partial. `TempPlotWidget`, `PressurePlotWidget`, `DynamicSensorGrid`, `TopWatchBar` coverage claims are broadly right. Quick log parity is overstated because legacy shows 5 current-experiment entries with inline submit, while dashboard `QuickLogBlock` shows only 2 global entries and no author/tags.
- Issues: HIGH=0 MEDIUM=2 LOW=1

### keithley.md
- LOC accuracy: pass. Claimed `586`; actual `586`.
- Section ranges: pass. `_SmuPanel` and `KeithleyPanel` ranges are broadly correct.
- Class/method existence: partial. `_SmuPanel` and `KeithleyPanel` exist, but inventory explicitly states “No combined A+B actions at panel level”, which is false.
- ZMQ commands: fail. Inventory lists only per-channel commands. Source also exposes top-level A+B dispatch actions through `_on_start_both`, `_on_stop_both`, `_on_emergency_both` at `src/cryodaq/gui/widgets/keithley_panel.py:489-555`, which are operator-visible controls and omitted from the inventory.
- Russian text drift: pass. Main panel labels generally match.
- Live subscriptions accurate: pass. `/smua/*`, `/smub/*`, and `analytics/keithley_channel_state/*` handling matches `src/cryodaq/gui/widgets/keithley_panel.py:566-581`.
- Workflows plausible: fail. “Compare A vs B” is real, but the inventory omits the actual A+B workflow completely.
- Recommendations grounded: partial. Core per-channel preserve list is grounded. K4 anchoring is incomplete because the inventory itself does not identify any actual custom-command surface.
- Coverage claims accurate: n/a. No substantive new-shell coverage table in this inventory.
- Issues: HIGH=1 MEDIUM=1 LOW=0

### analytics.md
- LOC accuracy: pass. Claimed total `934`; actual `521 + 413 = 934`.
- Section ranges: pass. `analytics_panel.py` and `vacuum_trend_panel.py` regioning is reasonable.
- Class/method existence: fail. Inventory claims `VacuumTrendPrediction dataclass`; source declares no such dataclass. `vacuum_trend_panel.py` stores raw `dict[str, Any]` prediction payload in `self._prediction` and exposes `set_prediction(self, prediction: dict[str, Any])` at `src/cryodaq/gui/widgets/vacuum_trend_panel.py:81-87, 246-250`.
- ZMQ commands: pass. Only `get_vacuum_trend` is sent, at `src/cryodaq/gui/widgets/vacuum_trend_panel.py:239`.
- Russian text drift: pass.
- Live subscriptions accurate: partial. `R_thermal`, `cooldown_eta`, `cooldown_eta_s`, and `"Детектор"` handling match `src/cryodaq/gui/widgets/analytics_panel.py:315-357`. The vacuum ETA section is not hardcoded to 3 fixed thresholds in code; labels are built dynamically from response payload.
- Workflows plausible: partial. Operator workflows are directionally right, but the inventory over-commits on a fixed backend contract it cannot prove from GUI code.
- Recommendations grounded: pass. K5 plot preservation is grounded.
- Coverage claims accurate: pass. Dashboard only carries fragments; full analytics overlay is still missing.
- Issues: HIGH=1 MEDIUM=1 LOW=0

### conductivity.md
- LOC accuracy: pass. Claimed `1068`; actual `1068`.
- Section ranges: pass. Major buckets are approximately right.
- Class/method existence: partial. `ConductivityPanel`, auto state machine, predictor integration all exist.
- ZMQ commands: pass. `keithley_set_target` and `keithley_stop` are the only commands emitted from this panel.
- Russian text drift: partial. Inventory says auto form uses `P начало`, `P конец`, `Шаг`; actual UI uses `Начальная P`, `Шаг P`, `Кол-во шагов` at `src/cryodaq/gui/widgets/conductivity_panel.py:224-246`.
- Live subscriptions accurate: pass. `Т*` and selected Keithley power channel behavior matches `src/cryodaq/gui/widgets/conductivity_panel.py:507-520`.
- Workflows plausible: partial. Auto-measurement exists, but inventory says completion “offers CSV export”; code only shows a completion dialog and leaves CSV export as a separate button (`_on_export`) on the left panel.
- Recommendations grounded: partial. Preserving auto-measurement, predictor integration, chain ordering, and CSV export is grounded. The layout description is materially wrong: there is no horizontal `QSplitter`, there is a fixed-width vertical splitter on the left and a separate right column. The results table is not 6 columns; it is 11 columns (`_COL_HEADERS`) at `src/cryodaq/gui/widgets/conductivity_panel.py:82-85`.
- Coverage claims accurate: pass. New dashboard only covers fragments.
- Issues: HIGH=0 MEDIUM=2 LOW=0

### alarms.md
- LOC accuracy: pass. Claimed `378`; actual `378`.
- Section ranges: pass. Layout, v1 logic, v2 polling buckets are roughly right.
- Class/method existence: pass. `_AlarmRow`, `AlarmPanel`, `update_v2_status`, `_acknowledge_v2` exist.
- ZMQ commands: pass. `alarm_acknowledge`, `alarm_v2_status`, `alarm_v2_ack` exactly match code.
- Russian text drift: pass.
- Live subscriptions accurate: partial. Inventory says implicit channel pattern `alarm/*`; source does not filter by channel prefix. It accepts any reading with `metadata.alarm_name` set at `src/cryodaq/gui/widgets/alarm_panel.py:175-205`.
- Workflows plausible: pass for legacy panel itself.
- Recommendations grounded: fail. The recommendation says “full solution requires this alarm overlay to be accessible via badge click”; that is already true in `MainWindowV2`.
- Coverage claims accurate: fail. Inventory says v1/v2 tables and acknowledge actions are “not in new overlay / not accessible from dashboard”. Current shell registers `AlarmPanel` as overlay and routes alarm badge click to it at `src/cryodaq/gui/shell/main_window_v2.py:136-145`. This is a false coverage gap.
- Issues: HIGH=1 MEDIUM=1 LOW=0

### operator_log.md
- LOC accuracy: pass. Claimed `171`; actual `171`.
- Section ranges: pass.
- Class/method existence: pass. `OperatorLogPanel`, `refresh_entries()`, `_on_submit()`, `_format_entry()` exist.
- ZMQ commands: pass. `log_get` and `log_entry` payloads match code.
- Russian text drift: pass.
- Live subscriptions accurate: pass. `analytics/operator_log_entry` triggers `refresh_entries()` at `src/cryodaq/gui/widgets/operator_log_panel.py:81-84`.
- Workflows plausible: pass.
- Recommendations grounded: pass. K1 preserve list is grounded.
- Coverage claims accurate: partial. Inventory marks “Live refresh” as `✓ COVERED` by `QuickLogBlock 10s poll`. That is not equivalent: dashboard polls `log_get` with `limit: 2` at `src/cryodaq/gui/dashboard/dashboard_view.py:258-275`; it does not receive push updates on `analytics/operator_log_entry`.
- Issues: HIGH=0 MEDIUM=1 LOW=0

### archive.md
- LOC accuracy: pass. Claimed `529`; actual `529`.
- Section ranges: pass.
- Class/method existence: pass. `ArchivePanel` and major action methods exist.
- ZMQ commands: pass. `experiment_archive_list` and `experiment_generate_report` match code.
- Russian text drift: pass.
- Live subscriptions accurate: n/a. Archive panel is command-driven, not reading-driven.
- Workflows plausible: pass.
- Recommendations grounded: partial. K2 archive preservation is grounded. K6 anchoring is not: opening PDF/DOCX is not the same preserve feature as CSV/HDF5/Excel export.
- Coverage claims accurate: pass. New dashboard/shell does not cover archive.
- Issues: HIGH=0 MEDIUM=1 LOW=0

### calibration.md
- LOC accuracy: pass. Claimed `499`; actual `499`.
- Section ranges: pass on rough ranges, fail on semantics. The file does contain 3 widgets and a stacked container.
- Class/method existence: partial. `CoverageBar`, `CalibrationSetupWidget`, `CalibrationAcquisitionWidget`, `CalibrationResultsWidget`, `CalibrationPanel` exist.
- ZMQ commands: partial. Commands listed are real, but payload is mis-stated: `target_channels` is sent as a comma-joined string, not a list, at `src/cryodaq/gui/widgets/calibration_panel.py:246-255`.
- Russian text drift: partial. Setup button text is `Начать калибровочный прогон`, not `Начать калибровку`.
- Live subscriptions accurate: partial. Inventory says no direct `on_reading`; actual `CalibrationPanel.on_reading()` appends `_raw` / `sensor_unit` lines into acquisition mode at `src/cryodaq/gui/widgets/calibration_panel.py:469-477`.
- Workflows plausible: fail. Inventory describes a results table and working export pipeline. Actual `CalibrationResultsWidget` is a selector + metrics form + dead export/apply buttons, with no `QTableWidget` and no button wiring at `src/cryodaq/gui/widgets/calibration_panel.py:347-419`.
- Recommendations grounded: fail. Preserve advice is based on a richer results/export workflow than the code actually implements.
- Coverage claims accurate: pass. New dashboard does not cover calibration.
- Issues: HIGH=2 MEDIUM=1 LOW=1

### instruments.md
- LOC accuracy: pass. Claimed `308`; actual `308`.
- Section ranges: pass.
- Class/method existence: partial. `_InstrumentCard` and `InstrumentStatusPanel` exist, but the inventory describes card capabilities that do not exist.
- ZMQ commands: pass. None, as documented.
- Russian text drift: pass.
- Live subscriptions accurate: partial. Readings are routed by `instrument_id`, but `analytics/*` are explicitly ignored and temperature channels without `instrument_id` are grouped under `"Температурные датчики"` at `src/cryodaq/gui/widgets/instrument_status.py:247-299`.
- Workflows plausible: fail. Inventory says operators can inspect “per-channel last value rows”. `_InstrumentCard` only shows name, status text, last response, and counters at `src/cryodaq/gui/widgets/instrument_status.py:69-98`.
- Recommendations grounded: partial. Adaptive timeout is grounded, but the documented state model is not. Inventory invents separate stale/offline tiers (`timeout` vs `3×timeout`). Code has one timeout transition to red “Нет связи”; yellow is used for non-OK reading status, not stale timeout.
- Coverage claims accurate: pass. New dashboard does not replace this surface.
- Issues: HIGH=1 MEDIUM=1 LOW=0

### sensor_diag.md
- LOC accuracy: pass. Claimed `211`; actual `211`.
- Section ranges: pass.
- Class/method existence: pass. `SensorDiagPanel` exists.
- ZMQ commands: pass. `get_sensor_diagnostics` matches code.
- Russian text drift: pass.
- Live subscriptions accurate: n/a. Polling only.
- Workflows plausible: partial.
- Recommendations grounded: partial. Folding diagnostics into context-sensitive UI is a design call, but the inventory’s factual baseline is wrong.
- Coverage claims accurate: pass. New dashboard does not cover it.
- Structural/data accuracy: fail. Inventory states response fields `{health, noise_sigma, drift, last_value}` and table columns `[Канал | Здоровье | Шум (σ) | Дрифт | Последнее]`. Actual code expects `health_score`, `current_T`, `noise_mK`, `drift_mK_per_min`, `outlier_count`, `correlation`, and table headers `["Канал", "T (K)", "Шум (мК)", "Дрейф (мК/мин)", "Выбросы", "Корр.", "Здоровье"]` at `src/cryodaq/gui/widgets/sensor_diag_panel.py:38, 140-157`.
- Issues: HIGH=1 MEDIUM=1 LOW=0

## Critical issues (HIGH severity, must fix before Phase I)

1. `alarms.md`: false claim that alarm overlay / ACK workflow is not present in new UI
   - Evidence: `src/cryodaq/gui/shell/main_window_v2.py:136-145` registers `"alarms"` in `OverlayContainer` and routes `TopWatchBar.alarms_clicked` to `self._on_tool_clicked("alarms")`.
   - Impact: Phase I/II planning can wrongly treat alarm drill-down as missing and design around a gap that does not exist.

2. `analytics.md`: fabricated `VacuumTrendPrediction dataclass` / hard API contract
   - Evidence: `src/cryodaq/gui/widgets/vacuum_trend_panel.py:81-87` defines only `VacuumTrendPanel` with `self._prediction: dict[str, Any]`; there is no dataclass in the file.
   - Impact: Architect can design primitives and adapter contracts against a GUI-level type that does not exist in source.

3. `calibration.md`: results mode is overstated; inventory invents a table-driven review surface
   - Evidence: `src/cryodaq/gui/widgets/calibration_panel.py:347-419` builds a channel selector, metric labels, export buttons, and runtime-apply form. There is no results `QTableWidget` in this widget.
   - Impact: Phase I/II will preserve and redesign a table workflow that legacy users never actually had, while the real issue is that results mode is underpowered.

4. `calibration.md`: export/apply workflow is described as functional, but buttons are dead
   - Evidence: `src/cryodaq/gui/widgets/calibration_panel.py:382-408` creates `.330`, `.340`, `JSON`, `CSV`, and `Применить в CryoDAQ` buttons; `rg` shows no `clicked.connect(...)` wiring for these controls.
   - Impact: Phase I can falsely assume export/apply already exists and only needs visual modernization, instead of recognizing a real functional gap.

5. `keithley.md`: inventory omits combined A+B control surface and explicitly says it does not exist
   - Evidence: `src/cryodaq/gui/widgets/keithley_panel.py:489-555` defines `Старт A+B`, `Стоп A+B`, `АВАР. ОТКЛ. A+B` plus `_on_start_both`, `_on_stop_both`, `_on_emergency_both`.
   - Impact: A real operator control path would be missing from the primitive set and from Phase II preserve scope.

6. `instruments.md`: per-card feature set and liveness model are fabricated
   - Evidence: `_InstrumentCard` at `src/cryodaq/gui/widgets/instrument_status.py:69-98` only renders status, last response, and counters. Timeout logic at `:128-159` has one timeout threshold to red “Нет связи”, not a yellow stale then red offline 3× timeout ladder.
   - Impact: Instrument-card primitives would be designed for a UI and state model that legacy never shipped.

7. `sensor_diag.md`: response schema and table columns are wrong
   - Evidence: `src/cryodaq/gui/widgets/sensor_diag_panel.py:38` defines 7 headers including `T (K)`, `Выбросы`, `Корр.`; `:140-157` reads `health_score`, `current_T`, `noise_mK`, `drift_mK_per_min`, `outlier_count`, `correlation`.
   - Impact: Any replacement diagnostics overlay or popover built from this inventory would target the wrong backend contract.

## Medium issues

1. `overview.md`: `experiment_status` trigger is mis-stated.
   - Evidence: `src/cryodaq/gui/widgets/overview_panel.py:838-855`
   - Impact: New-shell parity work could reproduce the wrong polling owner/rate.

2. `overview.md`: QuickLogWidget structure and Russian labels are materially wrong.
   - Evidence: `src/cryodaq/gui/widgets/overview_panel.py:918-986`
   - Impact: Inventory underestimates the amount of quick-log UI that legacy actually had.

3. `alarms.md`: v1 alarm subscription is described as `alarm/*` channel-driven when it is metadata-driven.
   - Evidence: `src/cryodaq/gui/widgets/alarm_panel.py:175-205`
   - Impact: Wrong event contract for any future adapter or synthetic test harness.

4. `operator_log.md`: “Live refresh covered” is too generous.
   - Evidence: legacy uses push trigger at `src/cryodaq/gui/widgets/operator_log_panel.py:81-84`; dashboard uses polling `log_get limit:2` at `src/cryodaq/gui/dashboard/dashboard_view.py:258-275`.
   - Impact: Phase II could under-prioritize full log overlay parity.

5. `archive.md`: K6 preserve reference is mis-anchored.
   - Evidence: archive panel opens PDF/DOCX and folders at `src/cryodaq/gui/widgets/archive_panel.py:465-529`; that is not CSV/HDF5/Excel export.
   - Impact: Preserve map for export workflows remains muddy.

6. `calibration.md`: `experiment_start` payload shape is mis-stated.
   - Evidence: `src/cryodaq/gui/widgets/calibration_panel.py:246-255`
   - Impact: Wrong contract documented for backend integration.

7. `conductivity.md`: layout and data table are substantially simplified relative to code.
   - Evidence: fixed-width left vertical splitter and 11-column table at `src/cryodaq/gui/widgets/conductivity_panel.py:145-380`, `_COL_HEADERS` at `:82-85`
   - Impact: Primitive design may under-allocate space and miss key result fields.

8. `analytics.md`: vacuum panel target rows are documented as fixed 3-threshold UI, but GUI code builds ETA labels dynamically from payload.
   - Evidence: `src/cryodaq/gui/widgets/vacuum_trend_panel.py:133-141, 274-322`
   - Impact: Future overlay could overfit to a hardcoded 3-target assumption.

9. `sensor_diag.md`: summary row is wrong.
   - Evidence: `src/cryodaq/gui/widgets/sensor_diag_panel.py:171-181` summarizes `healthy / warning / critical`, not mean health / channel count / unhealthy count.
   - Impact: Diagnostics summary primitive would be designed around the wrong summary semantics.

## Low issues / nits

- `overview.md`: pressure subscription is described as `*/pressure`; code actually keys off `unit == "mbar"` and whatever channel becomes current pressure source.
- `calibration.md`: several exact labels drift (`Начать калибровочный прогон` vs shorter wording in inventory).

## Cross-tab inconsistencies

1. **K6 export semantics are inconsistent across inventories.**
   - `archive.md` treats opening PDF/DOCX as “K6 partial”.
   - `calibration.md` treats `.330/.340/JSON/CSV` as `K3 + K6 preserve`.
   - `conductivity.md` treats CSV export as `K6 preserve`.
   - None of the inventories map HDF5 or Excel to any actual surface. That means preserve feature K6 is not reliably represented in Phase 0 at all.

2. **Coverage claims against the new shell are inconsistent in strictness.**
   - `alarms.md` says the acknowledge workflow is not accessible in the new UI, which is false.
   - `operator_log.md` says live refresh is covered by `QuickLogBlock`, even though the new widget only polls two entries and does not subscribe to `analytics/operator_log_entry`.
   - `overview.md` treats quick-log coverage as full, while `operator_log.md` correctly recognizes major losses in author/tags/multi-line input.

3. **Preserve feature K4 is not properly inventoried.**
   - `keithley.md` is the only K4 inventory, but it misses the A+B action group and does not identify where the preserve-list “custom commands” workflow currently lives.

## Preserve feature coverage map

K1 (service log): mentioned in `operator_log.md`, partially in `overview.md`. Agreement: partial. Risk: medium — quick-log is not the full chronology surface.

K2 (archive): mentioned in `archive.md`. Agreement: yes. Risk: low.

K3 (calibration): mentioned in `calibration.md`. Agreement: no. Risk: high — results/export/apply workflow is overstated.

K4 (Keithley control): mentioned in `keithley.md`. Agreement: no. Risk: high — combined A+B controls omitted, custom-command preserve path not inventoried.

K5 (plot zoom/pan): mentioned in `overview.md` and `analytics.md`. Agreement: mostly yes. Risk: low.

K6 (export CSV/HDF5/Excel): mentioned in `archive.md`, `calibration.md`, `conductivity.md`. Agreement: no. Risk: high — HDF5/Excel are effectively lost in the inventory set, and PDF/DOCX is mislabeled as K6.

K7 (phase detector): mentioned in none of the 10 inventories. Agreement: n/a. Risk: high — preserve feature is missing from the Phase 0 map.

## Pain point anchoring

P1 (tab-switching): anchored by `overview.md` and `sensor_diag.md` recommendations. Verified: partial — new dashboard/shell reduces tab switching, but the inventory set does not give one coherent preservation story.

P2 (alarms missed): anchored by `alarms.md` and `overview.md`. Verified: yes — `TopWatchBar` badge exists and opens the alarm overlay in `MainWindowV2`.

P3 (shift handover): anchored by none of these 10 inventories. Verified: no.

P4 (form repetition): anchored by none of these 10 inventories. Verified: no. This is mostly in Experiment Workspace / new experiment flow, not in the audited 10 tabs.

P5 (phase elapsed): weakly visible in `overview.md`, but not actually anchored by recommendations. Verified: no clear Phase 0 path.

P6 (plot co-location): anchored by `overview.md`, `analytics.md`, `conductivity.md`. Verified: partial — dashboard co-locates temperature and pressure plots, but analytics/conductivity overlays are still absent.

P7 (notifications): anchored by none of these 10 inventories. Verified: no.

## Recommendation for next steps

FIX FIRST.

Re-audit these inventories before Phase I primitives are treated as authoritative input:
- `docs/legacy-inventory/alarms.md`
- `docs/legacy-inventory/analytics.md`
- `docs/legacy-inventory/calibration.md`
- `docs/legacy-inventory/keithley.md`
- `docs/legacy-inventory/instruments.md`
- `docs/legacy-inventory/sensor_diag.md`
- `docs/legacy-inventory/overview.md`

Highest-leverage fixes:
1. Rewrite comparison/coverage sections against current `MainWindowV2` and dashboard code, not against early B.x assumptions.
2. Rebuild `calibration.md` from the actual widget state: what is implemented, what is only scaffolded, and what is missing entirely.
3. Rebuild `keithley.md` and `instruments.md` from actual operator-visible controls and state logic, not intended abstractions.
4. Add an explicit preserve-feature appendix for K4/K6/K7, because the current inventories do not cover them reliably.
5. Add a “verified new-shell parity” footer or commit reference to each inventory so stale comparison tables are easy to detect later.

## Audit methodology notes

- Reviewed all 10 inventory markdown files under `docs/legacy-inventory/`.
- Cross-checked against all 11 referenced widget sources (`overview_panel.py`, `keithley_panel.py`, `analytics_panel.py`, `vacuum_trend_panel.py`, `conductivity_panel.py`, `alarm_panel.py`, `operator_log_panel.py`, `archive_panel.py`, `calibration_panel.py`, `instrument_status.py`, `sensor_diag_panel.py`) — `6413` legacy source LOC total.
- Verified new-shell/dashboard coverage claims against targeted current files: `src/cryodaq/gui/shell/main_window_v2.py`, `src/cryodaq/gui/shell/top_watch_bar.py`, `src/cryodaq/gui/shell/experiment_overlay.py`, `src/cryodaq/gui/dashboard/dashboard_view.py`, `src/cryodaq/gui/dashboard/quick_log_block.py`, `src/cryodaq/gui/dashboard/dynamic_sensor_grid.py`, `src/cryodaq/gui/dashboard/temp_plot_widget.py`.
- Used `wc -l`, `rg -n '^class'`, `rg -n '"cmd":'`, and targeted `sed` / `nl -ba` reads on each disputed section.
- All referenced source files existed. No missing-file substitutions were needed.
