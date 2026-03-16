# Архитектура CryoDAQ

Версия документа: RC snapshot, март 2026

Этот документ описывает реализованную систему, а не исторический проектный план.

## 1. Общая модель

CryoDAQ состоит из независимых слоёв:

- `engine` — headless runtime
- `GUI` — desktop operator client
- `storage` — SQLite + artifact folders
- `reporting` — DOCX-first report generator
- `archive` — GUI access to stored experiment artifacts
- `calibration` — backend + GUI workflow for sensor calibration

Главный принцип: GUI не должен быть источником истины для runtime state. Источник истины находится в backend readings, analytics channels и command replies.

## 2. Runtime shape

### 2.1. Engine

`cryodaq.engine`:

- поднимает драйверы приборов
- маршрутизирует readings через broker
- пишет данные в SQLite
- обслуживает REQ/REP command path для GUI
- публикует analytics / alarm / safety channels
- обслуживает experiments, reports, archive listing, operator log и calibration commands

### 2.2. GUI

`src/cryodaq/gui/main_window.py` содержит 10 вкладок:

1. `Обзор`
2. `Keithley 2604B`
3. `Аналитика`
4. `Теплопроводность`
5. `Автоизмерение`
6. `Алармы`
7. `Журнал оператора`
8. `Архив`
9. `Калибровка`
10. `Приборы`

GUI получает данные из engine через ZMQ bridge и отправляет команды через command client. GUI можно перезапускать независимо от engine.

### 2.3. Tray status

Windows tray integration реализована в `src/cryodaq/gui/tray_status.py`.

Используемый mapping:

- `fault`:
  - unresolved alarms `> 0`
  - safety state `fault` / `fault_latched`
- `warning`:
  - нет связи
  - safety state неизвестен
  - состояние требует проверки
- `healthy`:
  - есть связь
  - `alarm_count == 0`
  - safety state в `safe_off`, `ready`, `run_permitted`, `running`

Unknown state deliberately не показывается как healthy.

## 3. Backend contracts

### 3.1. Alarm contract

Alarm backend event types:

- `activated`
- `acknowledged`
- `cleared`

GUI row states:

- `active`
- `acknowledged`
- `cleared`

`alarm_count` = unresolved alarms, то есть `active + acknowledged` до момента `cleared`.

### 3.2. Safety state contract

Backend canonical values are lowercase. GUI должен понимать именно их, а не собственный регистр.

### 3.3. Persistence-first

Safety semantics не throttled.

Adaptive throttle и housekeeping применяются только к non-safety archival/storage behavior. `SafetyBroker` и safety evaluation остаются full-fidelity.

## 4. Keithley 2604B

Текущая runtime модель поддерживает:

- `smua`
- `smub`
- одновременную работу `smua + smub`

Channel contract:

- `start smua`
- `start smub`
- `stop smua`
- `stop smub`
- `emergency_off smua`
- `emergency_off smub`

### 4.1. TSP

Текущий основной TSP path:

- `tsp/p_const.lua`

Это parameterized script для `smua` и `smub`.

В дереве также может присутствовать `tsp/p_const_single.lua` как legacy artifact, но актуальная архитектурная опора для runtime — `p_const.lua`.

### 4.2. GUI truth

Keithley GUI не должен считать канал `ON` только по ненулевым readings. Authoritative source — backend-owned channel status/state.

## 5. Experiments and artifacts

Experiment templates лежат в:

- `config/experiment_templates/*.yaml`

Template содержит как минимум:

- `id`
- `name`
- `sections`
- `report_enabled`
- `report_sections`
- optional `custom_fields`

### 5.1. Artifact layout

Эксперимент хранится в:

```text
data/experiments/<experiment_id>/
  metadata.json
  reports/
    report.docx
    report.pdf          # optional
    assets/
```

`metadata.json` содержит:

- `experiment`
- `template`
- `data_range`
- `artifacts`

Archive GUI строится поверх этого artifact contract, а не поверх отдельной archive DB.

### 5.2. Operator log

Operator log:

- сохраняется в SQLite
- доступен по `log_entry` / `log_get`
- отображается в GUI
- используется в report generation

## 6. Reporting

Reporting subsystem lives in `src/cryodaq/reporting/`.

Основные части:

- `data.py` — data extraction from metadata + SQLite
- `sections.py` — modular section registry
- `generator.py` — DOCX assembly + optional PDF conversion

Реализованные sections:

- `title_page`
- `cooldown_section`
- `thermal_section`
- `pressure_section`
- `operator_log_section`
- `alarms_section`
- `config_section`

Current guarantee:

- DOCX generation works

Current caveat:

- PDF conversion is best-effort only and depends on external tooling

## 7. Archive

Archive browser in GUI:

- scans `data/experiments/*/metadata.json`
- filters by template, operator, sample, date range, report presence
- opens artifact folder
- opens report file if present
- can regenerate report through existing backend command path

Missing or partial artifacts must not crash the archive flow.

## 8. Housekeeping

Housekeeping includes:

- conservative adaptive throttle for stable archival/storage paths
- retention/compression for old daily DB files

Protection rules:

- experiment-linked DBs are not compressed/deleted by retention
- experiment artifact folders are not deleted by this policy
- safety path is not throttled

Config file:

- `config/housekeeping.yaml`

## 9. Calibration

Calibration backend supports:

- LakeShore raw / SRDG acquisition
- calibration sessions
- multi-zone Chebyshev fit
- JSON/CSV export/import

Calibration artifacts:

```text
data/calibration/sessions/<session_id>/
data/calibration/curves/<sensor_id>/<curve_id>/
```

Calibration GUI supports:

- выбор reference channel
- выбор target channels
- start / capture / finalize session
- fit curve
- visualization of raw points and fitted curve
- export JSON/CSV

Important limitation:

- applying a calibration curve into runtime/instrument is not implemented in the current RC
- GUI correctly keeps `Применить в CryoDAQ` disabled

## 10. Dependencies that affect operator workflows

Key runtime / GUI dependencies from `pyproject.toml`:

- `PySide6`
- `pyqtgraph`
- `pyzmq`
- `python-docx`
- `matplotlib`
- `scipy`
- `openpyxl`

These dependencies are not optional if the corresponding workflows are expected to work.

## 11. Known RC limitations

- Calibration apply path is not implemented.
- Report PDF conversion is best-effort only.
- `asyncio.WindowsSelectorEventLoopPolicy` still emits deprecation warnings on newer Python versions.

## 12. Source-of-truth note

For current behavior, prefer the code contracts in:

- `src/cryodaq/engine.py`
- `src/cryodaq/core/experiment.py`
- `src/cryodaq/reporting/`
- `src/cryodaq/gui/main_window.py`
- `src/cryodaq/gui/tray_status.py`
- `src/cryodaq/gui/widgets/archive_panel.py`
- `src/cryodaq/gui/widgets/operator_log_panel.py`
- `src/cryodaq/gui/widgets/calibration_panel.py`

This document is intentionally scoped to the implemented RC branch state and should be updated if those contracts change.
