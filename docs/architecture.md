# Архитектура CryoDAQ

Версия документа: 0.12.0, март 2026

Этот документ описывает реализованную систему, а не исторический проектный план.

## 0. Сверка с продуктовым контрактом

- Один эксперимент равен одной experiment card.
- Во время активного эксперимента открыта ровно одна experiment card.
- Завершение эксперимента закрывает карточку и переводит её в архивную запись.
- Следующий эксперимент создаёт новую карточку.
- Основной workflow различает режимы `Эксперимент` и `Отладка`.
- Режим `Отладка` не создаёт архивные карточки и автоматические отчёты по эксперименту.
- Dual-channel `smua` / `smub` остаётся текущей и целевой Keithley-моделью; старые ожидания про disable/hide/remove `smub` устарели.
- Внешний отчётный контракт: `report_raw.pdf` + `report_editable.docx`.
- Calibration-контракт текущего RC: `.330` / `.340`, Chebyshev FIT по task, runtime apply и per-channel apply. Оставшиеся пробелы относятся к дальнейшему operator rollout и lab verification, а не к отсутствующему core backend.

## 1. Общая модель

CryoDAQ состоит из независимых слоёв:

- `engine` — headless runtime
- `GUI` — desktop operator client
- `storage` — SQLite + artifact folders
- `reporting` — DOCX-first report generator
- `archive` — GUI access to stored experiment artifacts
- `calibration` — backend + GUI workflow for sensor calibration

Главный принцип: GUI не должен быть источником истины для runtime state. Источник истины находится в backend readings, analytics channels и command replies.

## 2. Runtime-контур

### 2.1. Engine

`cryodaq.engine`:

- поднимает драйверы приборов
- маршрутизирует readings через broker
- пишет данные в SQLite
- обслуживает REQ/REP command path для GUI
- публикует analytics / alarm / safety channels
- обслуживает experiments, reports, archive listing, operator log и calibration commands

### 2.2. GUI

`src/cryodaq/gui/main_window.py` содержит 11 вкладок:

1. `Обзор`
2. `Эксперимент`
3. `Keithley 2604B`
4. `Аналитика`
5. `Теплопроводность`
6. `Автоизмерение`
7. `Алармы`
8. `Служебный лог`
9. `Архив`
10. `Калибровка`
11. `Приборы`

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

## 3. Backend-контракты

### 3.1. Alarm-контракт

Alarm backend event types:

- `activated`
- `acknowledged`
- `cleared`

Состояния строк в GUI:

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
    report_editable.docx
    report_raw.pdf      # optional, best effort if soffice/libreoffice is available
    report_raw.docx
    assets/
```

`metadata.json` содержит:

- `experiment`
- `template`
- `data_range`
- `artifacts`

Archive GUI строится поверх этого artifact contract, а не поверх отдельной archive DB.

Target operator-facing report artifacts:

- `report_raw.pdf`
- `report_editable.docx`


### 5.2. Operator log

Operator log:

- сохраняется в SQLite
- доступен по `log_entry` / `log_get`
- отображается в GUI
- используется в report generation

## 6. Reporting

Reporting subsystem lives in `src/cryodaq/reporting/`.

Основные части:

- `data.py` — извлечение данных из архивной карточки и её артефактов, с текущим fallback в SQLite для части секций
- `sections.py` — модульный реестр секций
- `generator.py` — текущая сборка DOCX / PDF

- `report_editable.docx`
- `report_raw.pdf`
- `report_raw.docx` как machine-generated intermediate source для PDF-конвертации

Реализованные sections:

- `title_page`
- `cooldown_section`
- `thermal_section`
- `pressure_section`
- `operator_log_section`
- `alarms_section`
- `config_section`

Текущая гарантия:

- генерация DOCX работает

Текущий caveat:

- PDF-конвертация остаётся best-effort и зависит от внешнего инструмента

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
- `.330` / `.340` / JSON / CSV import/export

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
- export `.330` / `.340` / JSON / CSV

Runtime calibration behavior:

- global `off` uses `KRDG`
- global `on` uses `SRDG + curve` where assignment and curve are ready
- per-channel policy may override to `off` / `on` / `inherit`
- conservative fallback returns `KRDG` and logs the reason when assignment/curve/raw SRDG input is unavailable

`CalibrationStore` поднимается до wiring LakeShore drivers, чтобы runtime policy была доступна уже на startup contour.

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

## 11. Известные ограничения

- PDF-конвертация остаётся best-effort и зависит от внешнего `LibreOffice` / `soffice`.
- На новых версиях Python возможны deprecation warnings вокруг `WindowsSelectorEventLoopPolicy`.

## 12. Примечание про источник истины

Для текущего поведения ориентируйтесь на контракты кода в:

- `src/cryodaq/engine.py`
- `src/cryodaq/core/experiment.py`
- `src/cryodaq/core/calibration_acquisition.py`
- `src/cryodaq/analytics/calibration_fitter.py`
- `src/cryodaq/reporting/`
- `src/cryodaq/gui/main_window.py`
- `src/cryodaq/gui/widgets/calibration_panel.py`
- `src/cryodaq/gui/widgets/experiment_workspace.py`
- `src/cryodaq/gui/widgets/shift_handover.py`

Этот документ описывает текущее реализованное состояние и должен обновляться при изменении контрактов.
