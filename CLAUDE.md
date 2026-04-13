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
     States: SAFE_OFF -> READY -> RUN_PERMITTED -> RUNNING -> FAULT_LATCHED -> MANUAL_RECOVERY -> READY
     Note: request_run() can shortcut SAFE_OFF -> RUNNING when all preconditions met
     MANUAL_RECOVERY: entered after acknowledge_fault(), transitions to
     READY when preconditions restore.
     Fail-on-silence: stale data -> FAULT + emergency_off (fires only
     while state=RUNNING; outside RUNNING, stale data blocks readiness
     via preconditions, not via fault)
     Rate limit: dT/dt > 5 K/min -> FAULT (5 K/min is the configurable
     default in safety.yaml, not a hard-coded invariant)
     Recovery: acknowledge + precondition re-check + cooldown
     Safety regulation is host-side only (no Keithley TSP watchdog yet —
     planned for Phase 3, requires hardware verification).
     Crash-recovery guard: Keithley2604B.connect() forces OUTPUT_OFF on
     both SMU channels before assuming control (best-effort: if force-OFF
     fails, logs CRITICAL and continues — not guaranteed).
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

- `src/cryodaq/core/alarm.py` — v1 alarm engine (threshold + hysteresis)
- `src/cryodaq/core/alarm_v2.py` — v2 alarm engine (YAML-driven, phase-aware, composite conditions)
- `src/cryodaq/core/atomic_write.py` — atomic file write via os.replace()
- `src/cryodaq/core/broker.py` — DataBroker fan-out pub/sub
- `src/cryodaq/core/calibration_acquisition.py` — непрерывный сбор SRDG при калибровке
- `src/cryodaq/core/channel_manager.py` — channel name/visibility singleton (get_channel_manager())
- `src/cryodaq/core/channel_state.py` — per-channel state tracker for alarm evaluation (staleness, fault history)
- `src/cryodaq/core/event_logger.py` — автоматическое логирование системных событий
- `src/cryodaq/core/experiment.py` — управление экспериментами, фазы (ExperimentPhase)
- `src/cryodaq/core/housekeeping.py`
- `src/cryodaq/core/interlock.py` — threshold detection, delegates actions to SafetyManager
- `src/cryodaq/core/operator_log.py`
- `src/cryodaq/core/rate_estimator.py` — rolling dT/dt estimator with min_points gate
- `src/cryodaq/core/safety_broker.py` — dedicated safety channel (overflow=FAULT)
- `src/cryodaq/core/safety_manager.py` — 6-state FSM, fail-on-silence, rate limiting
- `src/cryodaq/core/scheduler.py` — instrument polling, persistence-first ordering
- `src/cryodaq/core/sensor_diagnostics.py` — noise/drift/correlation health scoring (numpy exception)
- `src/cryodaq/core/zmq_bridge.py` — ZMQ PUB/SUB + REP/REQ command server
- `src/cryodaq/core/zmq_subprocess.py` — subprocess isolation for ZMQ bridge

**Аналитика**

- `src/cryodaq/analytics/base_plugin.py` — AnalyticsPlugin ABC
- `src/cryodaq/analytics/calibration.py` — CalibrationStore, Chebyshev fit, runtime policy
- `src/cryodaq/analytics/calibration_fitter.py` — post-run pipeline (extract, downsample, breakpoints, fit)
- `src/cryodaq/analytics/cooldown_predictor.py` — progress-variable ensemble cooldown ETA
- `src/cryodaq/analytics/cooldown_service.py` — async cooldown orchestration
- `src/cryodaq/analytics/plugin_loader.py` — hot-reload plugin pipeline (5s mtime polling)
- `src/cryodaq/analytics/steady_state.py` — T∞ predictor via exponential decay fit
- `src/cryodaq/analytics/vacuum_trend.py` — BIC-selected vacuum pump-down extrapolation

**Драйверы**

- `src/cryodaq/drivers/base.py` — InstrumentDriver ABC, Reading dataclass, ChannelStatus enum
- `src/cryodaq/drivers/instruments/keithley_2604b.py` — Keithley 2604B dual-SMU (host-side P=const)
- `src/cryodaq/drivers/instruments/lakeshore_218s.py` — LakeShore 218S 8-channel thermometer
- `src/cryodaq/drivers/instruments/thyracont_vsp63d.py` — Thyracont VSP63D vacuum gauge (MV00 + V1)
- `src/cryodaq/drivers/transport/gpib.py` — async GPIB transport via PyVISA
- `src/cryodaq/drivers/transport/serial.py` — async serial transport via pyserial-asyncio
- `src/cryodaq/drivers/transport/usbtmc.py` — async USB-TMC transport via PyVISA

**Уведомления**

- `src/cryodaq/notifications/telegram.py` — TelegramNotifier (alarm callbacks)
- `src/cryodaq/notifications/telegram_commands.py` — interactive command bot (/status /temps /pressure)
- `src/cryodaq/notifications/escalation.py` — timed escalation service
- `src/cryodaq/notifications/periodic_report.py` — scheduled Telegram reports with charts
- `src/cryodaq/notifications/_secrets.py` — SecretStr wrapper for token leak prevention

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

- `tsp/p_const.lua` — draft TSP supervisor for Phase 3 hardware watchdog
  upload (currently NOT loaded — keithley_2604b.py runs P=const host-side)

## Конфигурационные файлы

- `config/instruments.yaml`
- `config/interlocks.yaml`
- `config/alarms.yaml`
- `config/alarms_v3.yaml`
- `config/safety.yaml`
- `config/notifications.yaml`
- `config/channels.yaml`
- `config/cooldown.yaml`
- `config/experiment_templates/*.yaml`
- `config/housekeeping.yaml`
- `config/plugins.yaml`
- `config/shifts.yaml`
- `config/*.local.yaml.example`

## Приборы

- LakeShore 218S
- Keithley 2604B
- Thyracont VSP63D

## Ключевые правила

- `SAFE_OFF` — состояние по умолчанию.
- GUI — отдельный процесс и не должен быть источником истины для runtime state.
- Keithley disconnect must call emergency off first.
- No blocking I/O on the engine event loop (known exception: `reporting/generator.py` uses sync `subprocess.run()` for LibreOffice PDF conversion — DEEP_AUDIT finding E.2).
- Operator-facing GUI text should remain in Russian.
- No numpy/scipy в drivers/core (исключение: core/sensor_diagnostics.py — MAD/корреляция).
- Scheduler writes to SQLite before publishing to brokers.

## Известные ограничения

- Best-effort PDF generation по-прежнему зависит от внешнего `soffice` / `LibreOffice`; отсутствие этого инструмента является ограничением окружения, а не code regression.
- `WindowsSelectorEventLoopPolicy` продолжает давать известные Python 3.14+ deprecation warnings.
- Supported deployment: `pip install -e .` из корня репозитория. Wheel-install не self-contained — config/, plugins/, data/ находятся вне пакета. Используйте CRYODAQ_ROOT для нестандартных layout.
