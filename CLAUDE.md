# CLAUDE.md

Этот файл задаёт рабочие ориентиры для Claude Code при работе с данным репозиторием.

# CryoDAQ

## Снимок сверки

- Источник истины по продуктовой модели: один эксперимент равен одной experiment card, и во время активного эксперимента открыта ровно одна карточка.
- Основной операторский workflow различает `Эксперимент` и `Отладка`; `Отладка` не должна создавать архивные записи и автоматические отчёты по эксперименту.
- Dual-channel Keithley (`smua`, `smub`, `smua + smub`) остаётся актуальной моделью. Старые ожидания про disable/hide/remove `smub` устарели.
- Контракт внешних отчётов и текущий код используют `report_raw.pdf` и `report_editable.docx`, а `report_raw.docx` остаётся machine-generated intermediate input для best-effort PDF-конвертации.
- Calibration v2: continuous SRDG acquisition during calibration experiments (CalibrationAcquisitionService), post-run pipeline (CalibrationFitter: extract → downsample → breakpoints → Chebyshev fit), three-mode GUI (Setup → Acquisition → Results), `.330` / `.340` / JSON export, runtime apply с per-channel policy.

Замена LabVIEW для cryogenic laboratory workflow (Millimetron / АКЦ ФИАН).
Python 3.12+, asyncio, PySide6. Current package metadata: `0.13.0`.

## Команды сборки и разработки

```bash
pip install -e ".[dev,web]"    # Install runtime, dev, and optional web dependencies
pip install -e ".[dev,web,archive]"  # + Parquet archive support (pyarrow)
cryodaq                        # Operator launcher
cryodaq-engine                 # Run engine headless (real instruments)
cryodaq-engine --mock          # Run engine with simulated data
cryodaq-gui                    # Run GUI only (connects to engine over ZMQ)
uvicorn cryodaq.web.server:app --host 0.0.0.0 --port 8080
install.bat                    # Windows installer helper
python create_shortcut.py      # Create desktop shortcut
cryodaq-cooldown build --data cooldown_v5/ --output model/
cryodaq-cooldown predict --model model/ --T_cold 50 --T_warm 120 --t_elapsed 8
pytest
pytest tests/core/
pytest -k test_safety
pytest -k test_cooldown
ruff check src/ tests/
ruff format src/ tests/
```

## Переменные окружения

- `CRYODAQ_ROOT` — переопределяет корневой каталог проекта
- `CRYODAQ_MOCK=1` — запускает engine в mock mode

## Развёртывание

`config/*.local.yaml` overrides `config/*.yaml`.
Local configs are gitignored and intended for machine-specific deployment data such as COM ports, GPIB addresses, and notification credentials.

See `docs/deployment.md` for operator-PC deployment steps.

## Архитектура

Три основных runtime-контура:

- `cryodaq-engine` — headless asyncio runtime: acquisition, safety, storage, commands
- `cryodaq-gui` или `cryodaq` — desktop operator client / launcher
- web dashboard — optional FastAPI monitoring surface

### Архитектура safety

SafetyManager is the single authority for source on/off decisions.
Source OFF is the default. Running requires continuous proof of health.

```text
SafetyBroker (dedicated, overflow=FAULT)
  -> SafetyManager
     States: SAFE_OFF -> READY -> RUN_PERMITTED -> RUNNING -> FAULT_LATCHED
     Note: request_run() can shortcut SAFE_OFF -> RUNNING when all preconditions met
     Fail-on-silence: stale data -> FAULT + emergency_off
     Rate limit: dT/dt > 5 K/min -> FAULT
     Recovery: acknowledge + precondition re-check + cooldown
     Double protection: Python safety path + hardware watchdog
```

### Persistence-first ordering

```text
InstrumentDriver.read_channels()
  -> Scheduler
     1. SQLiteWriter.write_immediate()
     2. THEN DataBroker.publish_batch()
     3. THEN SafetyBroker.publish_batch()
```

Invariant: if DataBroker has a reading, it has already been written to SQLite.

### Вкладки GUI

Текущие вкладки `MainWindow`:

- `Обзор` — двухколоночный layout (графики слева, sidebar справа)
- `Эксперимент` — ExperimentWorkspace (создание, управление, финализация)
- `Источник мощности`
- `Аналитика`
- `Теплопроводность` — включает встроенное автоизмерение (ранее отдельная вкладка)
- `Алармы`
- `Служебный лог`
- `Архив`
- `Калибровка`
- `Приборы`

Меню:

- `Файл` — экспорт CSV / HDF5 / Excel
- `Эксперимент` — запуск и завершение эксперимента
- `Настройки` — редактор каналов и параметры подключений

### Индекс модулей

**Точки входа**

- `src/cryodaq/engine.py` — headless engine
- `src/cryodaq/launcher.py` — operator launcher
- `src/cryodaq/gui/app.py` — standalone GUI entry point

**Core**

- `src/cryodaq/core/alarm.py`
- `src/cryodaq/core/calibration_acquisition.py` — непрерывный сбор SRDG при калибровке
- `src/cryodaq/core/event_logger.py` — автоматическое логирование системных событий
- `src/cryodaq/core/experiment.py` — управление экспериментами, фазы (ExperimentPhase)
- `src/cryodaq/core/housekeeping.py`
- `src/cryodaq/core/operator_log.py`
- `src/cryodaq/core/safety_broker.py`
- `src/cryodaq/core/safety_manager.py`
- `src/cryodaq/core/scheduler.py`
- `src/cryodaq/core/zmq_bridge.py`

**Аналитика**

- `src/cryodaq/analytics/calibration.py` — CalibrationStore, Chebyshev fit, runtime policy
- `src/cryodaq/analytics/calibration_fitter.py` — post-run pipeline (extract, downsample, breakpoints, fit)

**GUI**

- `src/cryodaq/gui/main_window.py` — горячие клавиши (Ctrl+L/E/1-9, F5, Ctrl+Shift+X)
- `src/cryodaq/gui/tray_status.py`
- `src/cryodaq/gui/widgets/archive_panel.py`
- `src/cryodaq/gui/widgets/calibration_panel.py` — три режима (Setup/Acquisition/Results)
- `src/cryodaq/gui/widgets/experiment_workspace.py` — фазы, карточка эксперимента
- `src/cryodaq/gui/widgets/operator_log_panel.py`
- `src/cryodaq/gui/widgets/overview_panel.py` — двухколоночный: графики + карточки
- `src/cryodaq/gui/widgets/keithley_panel.py`
- `src/cryodaq/gui/widgets/conductivity_panel.py` — теплопроводность + автоизмерение
- `src/cryodaq/gui/widgets/sensor_diag_panel.py` — диагностика датчиков
- `src/cryodaq/gui/widgets/vacuum_trend_panel.py` — прогноз вакуума
- `src/cryodaq/gui/widgets/autosweep_panel.py` — DEPRECATED
- `src/cryodaq/gui/widgets/channel_editor.py` — редактор каналов (видимость, имена)
- `src/cryodaq/gui/widgets/preflight_dialog.py` — предполётная проверка перед экспериментом
- `src/cryodaq/gui/widgets/instrument_status.py` — вкладка приборов + адаптивный liveness
- `src/cryodaq/gui/widgets/shift_handover.py` — смены (ShiftBar, ShiftStartDialog, ShiftEndDialog)

**Storage**

- `src/cryodaq/storage/sqlite_writer.py` — WAL-mode SQLite, daily rotation, persistence-first
- `src/cryodaq/storage/parquet_archive.py` — Parquet export/read для архива экспериментов (pyarrow optional)

**Reporting**

- `src/cryodaq/reporting/data.py`
- `src/cryodaq/reporting/generator.py`
- `src/cryodaq/reporting/sections.py`

**Web**

- `src/cryodaq/web/server.py`

**Tools**

- `src/cryodaq/tools/cooldown_cli.py`

**TSP**

- `tsp/p_const.lua` — primary runtime script
- `tsp/p_const_single.lua` — legacy/fallback artifact, который всё ещё присутствует в дереве

## Конфигурационные файлы

- `config/instruments.yaml`
- `config/interlocks.yaml`
- `config/alarms.yaml`
- `config/safety.yaml`
- `config/notifications.yaml`
- `config/channels.yaml`
- `config/cooldown.yaml`
- `config/experiment_templates/*.yaml`
- `config/housekeeping.yaml`
- `config/*.local.yaml.example`

## Приборы

- LakeShore 218S
- Keithley 2604B
- Thyracont VSP63D

## Ключевые правила

- `SAFE_OFF` — состояние по умолчанию.
- GUI — отдельный процесс и не должен быть источником истины для runtime state.
- Keithley disconnect must call emergency off first.
- No blocking I/O on the engine event loop.
- Operator-facing GUI text should remain in Russian.
- No numpy/scipy в drivers/core (исключение: core/sensor_diagnostics.py — MAD/корреляция).
- Scheduler writes to SQLite before publishing to brokers.

## Известные ограничения

- Best-effort PDF generation по-прежнему зависит от внешнего `soffice` / `LibreOffice`; отсутствие этого инструмента является ограничением окружения, а не code regression.
- `WindowsSelectorEventLoopPolicy` продолжает давать известные Python 3.14+ deprecation warnings.
- Supported deployment: `pip install -e .` из корня репозитория. Wheel-install не self-contained — config/, plugins/, data/ находятся вне пакета. Используйте CRYODAQ_ROOT для нестандартных layout.
