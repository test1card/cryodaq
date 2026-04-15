# Phase 0 Audit Report

Scope: `docs/legacy-inventory/*.md` cross-checked against source under `src/cryodaq/gui/widgets/`.

1. **[LOW] `alarms.md`**
- LOC: claimed `378`; actual `wc -l` on `src/cryodaq/gui/widgets/alarm_panel.py` is `378`.
- ZMQ listed: `alarm_acknowledge`, `alarm_v2_status`, `alarm_v2_ack`.
- ZMQ in source via `rg -n "cmd.*:"`: same three commands at lines `281`, `303`, `368`.
- Fabricated classes/methods: none found; `_AlarmRow`, `AlarmPanel`, `_acknowledge_v2`, `update_v2_status`, and the documented signal names exist.
- ZMQ commands in source not listed in inventory: none.

2. **[MEDIUM] `analytics.md`**
- LOC: claimed total `934`; actual is `521` in `analytics_panel.py` plus `413` in `vacuum_trend_panel.py` = `934`.
- ZMQ listed: `get_vacuum_trend`.
- ZMQ in source via `rg -n "cmd.*:"`: `get_vacuum_trend` at `src/cryodaq/gui/widgets/vacuum_trend_panel.py:239`; no commands in `analytics_panel.py`.
- Fabricated classes/methods: `VacuumTrendPrediction` is not declared in either source file. Source defines `AnalyticsPanel` and `VacuumTrendPanel`; the vacuum payload is handled as a plain `dict`.
- ZMQ commands in source not listed in inventory: none.

3. **[LOW] `archive.md`**
- LOC: claimed `529`; actual `wc -l` on `src/cryodaq/gui/widgets/archive_panel.py` is `529`.
- ZMQ listed: `experiment_archive_list`, `experiment_generate_report`.
- ZMQ in source via `rg -n "cmd.*:"`: same two commands at lines `196` and `498`.
- Fabricated classes/methods: none found; `ArchivePanel` and the documented action methods exist.
- ZMQ commands in source not listed in inventory: none.

4. **[MEDIUM] `calibration.md`**
- LOC: claimed `499`; actual `wc -l` on `src/cryodaq/gui/widgets/calibration_panel.py` is `499`.
- ZMQ listed: `experiment_start`, `calibration_acquisition_status`.
- ZMQ in source via `rg -n "cmd.*:"`: same two commands at lines `246` and `485`.
- Fabricated classes/methods: no invented class names, but the documented `CalibrationResultsWidget` table (`[Канал | Зоны | Остаток | R² | Файл]`) does not exist. In source, `CalibrationResultsWidget` is a metric form (`class` at `347`, `update_metrics()` at `421`); the file’s only `QTableWidget` is the setup-page `_curves_table` at `222`.
- ZMQ commands in source not listed in inventory: none.

5. **[LOW] `conductivity.md`**
- LOC: claimed `1068`; actual `wc -l` on `src/cryodaq/gui/widgets/conductivity_panel.py` is `1068`.
- ZMQ listed: `keithley_set_target`, `keithley_stop`.
- ZMQ in source via `rg -n "cmd.*:"`: actual command payloads are `keithley_set_target` at lines `792` and `865`, and `keithley_stop` at lines `805` and `908`.
- Fabricated classes/methods: none found; `ConductivityPanel` and the documented auto-measurement methods exist.
- ZMQ commands in source not listed in inventory: none. Note: raw `cmd.*:` grep also matches helper identifiers at lines `143`, `749`, and `757`, but those are not command payloads.

6. **[MEDIUM] `instruments.md`**
- LOC: claimed `308`; actual `wc -l` on `src/cryodaq/gui/widgets/instrument_status.py` is `308`.
- ZMQ listed: none.
- ZMQ in source via `rg -n "cmd.*:"`: no command payloads found.
- Fabricated classes/methods: no invented class names, but the inventory overstates `_InstrumentCard`. Source `_InstrumentCard` only renders status, last-response time, and counters (`instrument_status.py:89-98`); it does not render per-channel value rows as documented.
- ZMQ commands in source not listed in inventory: none.

7. **[MEDIUM] `keithley.md`**
- LOC: claimed `586`; actual `wc -l` on `src/cryodaq/gui/widgets/keithley_panel.py` is `586`.
- ZMQ listed: `keithley_start`, `keithley_stop`, `keithley_emergency_off`, `keithley_set_target`, `keithley_set_limits`.
- ZMQ in source via `rg -n "cmd.*:"`: same five commands at lines `322`, `354`, `385`, `413`, `434`.
- Fabricated classes/methods: none invented, but the inventory statement “No combined A+B actions at panel level” is false. Source wires header buttons to `_on_start_both`, `_on_stop_both`, and `_on_emergency_both` (`keithley_panel.py:491-552`).
- ZMQ commands in source not listed in inventory: none.

8. **[LOW] `operator_log.md`**
- LOC: claimed `171`; actual `wc -l` on `src/cryodaq/gui/widgets/operator_log_panel.py` is `171`.
- ZMQ listed: `log_get`, `log_entry`.
- ZMQ in source via `rg -n "cmd.*:"`: same two commands at lines `88` and `129`.
- Fabricated classes/methods: none found; `OperatorLogPanel`, `refresh_entries()`, `_on_submit()`, and `_format_entry()` exist.
- ZMQ commands in source not listed in inventory: none.

9. **[LOW] `overview.md`**
- LOC: claimed `1729`; actual `wc -l` on `src/cryodaq/gui/widgets/overview_panel.py` is `1729`.
- ZMQ listed: `experiment_status`, `log_entry`, `log_get`, `readings_history`.
- ZMQ in source via `rg -n "cmd.*:"`: same four commands at lines `853`, `964`, `986`, `1609`.
- Fabricated classes/methods: none found; `StatusStrip`, `CompactTempCard`, `TempCardGrid`, `PressureCard`, `KeithleyStrip`, `ExperimentStatusWidget`, `QuickLogWidget`, and `OverviewPanel` all exist.
- ZMQ commands in source not listed in inventory: none.

10. **[MEDIUM] `sensor_diag.md`**
- LOC: claimed `211`; actual `wc -l` on `src/cryodaq/gui/widgets/sensor_diag_panel.py` is `211`.
- ZMQ listed: `get_sensor_diagnostics`.
- ZMQ in source via `rg -n "cmd.*:"`: `get_sensor_diagnostics` at line `115`.
- Fabricated classes/methods: no invented class names, but the documented response contract is wrong. Source expects fields such as `health_score`, `current_T`, `noise_mK`, `drift_mK_per_min`, `outlier_count`, and `correlation` (`sensor_diag_panel.py:142-155`), not `{health, noise_sigma, drift, last_value}`.
- ZMQ commands in source not listed in inventory: none.
