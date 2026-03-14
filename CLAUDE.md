# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# CryoDAQ

LabVIEW replacement for cryogenic lab (АКЦ ФИАН, Millimetron).
Python 3.12+, asyncio, PySide6, 16k+ lines, 151 tests.

## Build & Development Commands

```bash
pip install -e ".[dev,web]"    # Install all deps (incl. scipy, matplotlib, aiohttp)
cryodaq                        # Operator launcher (auto-starts engine + GUI, tray icon)
cryodaq-engine                 # Run engine headless (real instruments)
cryodaq-engine --mock          # Run engine with simulated data (5 instruments)
cryodaq-gui                    # Run GUI only (connects to running engine via ZMQ)
uvicorn cryodaq.web.server:app --host 0.0.0.0 --port 8080  # Web dashboard
install.bat                    # One-click Windows installer
python create_shortcut.py      # Create desktop shortcut (CryoDAQ.lnk)
pytest                         # Run all 151 tests (~38s)
pytest tests/core/             # Core subsystem tests only
pytest -k test_safety          # Run safety manager tests
ruff check src/ tests/         # Lint
ruff format src/ tests/        # Format
```

## Environment Variables

- `CRYODAQ_ROOT` — override project root directory (default: auto-detected from `engine.py` location)
- `CRYODAQ_MOCK=1` — start engine in mock mode (same as `--mock` flag)

## Deployment

Config override: `config/*.local.yaml` takes priority over `config/*.yaml`.
Local configs are gitignored — machine-specific (COM ports, GPIB addresses, Telegram tokens).
See `docs/deployment.md` for step-by-step lab PC setup.

## Architecture

Three-tier system:
- **cryodaq-engine** (headless, asyncio) — data acquisition, safety, storage
- **cryodaq-gui** (PySide6) or **cryodaq** (launcher with embedded GUI + engine management)
- **web dashboard** (FastAPI + WebSocket + Chart.js) — optional remote monitoring

### Safety architecture (CRITICAL)

SafetyManager is the single authority for source on/off decisions.
Source OFF is the DEFAULT. Running requires continuous proof of health.

```
SafetyBroker (dedicated, overflow=FAULT)
  → SafetyManager (state machine, 1Hz monitoring)
    States: SAFE_OFF → READY → RUN_PERMITTED → RUNNING → FAULT_LATCHED
    Fail-on-silence: stale data (10s) → FAULT + emergency_off
    Rate limit: dT/dt > 5 K/min → FAULT
    Recovery: two-step (acknowledge with reason + precondition re-check + 60s cooldown)
    Double protection: SafetyManager (Python) + TSP watchdog (hardware, 30s)
```

### Engine data flow

```
InstrumentDriver.read_channels()
  → Scheduler ──► DataBroker (fan-out, DROP_OLDEST)       → SQLiteWriter, ZMQ, Alarms, Plugins
              └──► SafetyBroker (dedicated, overflow=FAULT) → SafetyManager (continuous monitoring)
  → InterlockEngine (threshold detection → SafetyManager action delegation)
  → ZMQCommandServer (REP :5556, GUI commands → SafetyManager)
```

### GUI tabs

Температуры | Keithley (smua+smub, controls) | Давление (log scale) | Аналитика (R_thermal, ETA) | Теплопроводность (chain R/G + predictor) | Автоизмерение (power sweep) | Алармы | Статус приборов

Menu: Файл (экспорт CSV/HDF5) | Эксперимент (начать/остановить) | Настройки (редактор каналов, подключение приборов)

### Module index

**Entry points:**
- `src/cryodaq/engine.py` — headless engine: config loading, subsystem wiring, graceful shutdown, watchdog
- `src/cryodaq/launcher.py` — operator launcher: auto-starts engine, embeds GUI, system tray, auto-restart
- `src/cryodaq/gui/app.py` — standalone GUI entry point

**Safety (CRITICAL — changes require review):**
- `src/cryodaq/core/safety_manager.py` — SafetyManager: 6-state machine, fail-on-silence, rate limits, two-step recovery
- `src/cryodaq/core/safety_broker.py` — SafetyBroker: dedicated safety channel, overflow=FAULT, staleness tracking

**Core:**
- `src/cryodaq/core/broker.py` — DataBroker: bounded queues, overflow policies, fan-out (tuple snapshot iteration)
- `src/cryodaq/core/scheduler.py` — per-instrument polling, exponential backoff, dual-broker publish
- `src/cryodaq/core/alarm.py` — AlarmEngine: OK/ACTIVE/ACKNOWLEDGED, hysteresis, severity, notifiers
- `src/cryodaq/core/interlock.py` — InterlockEngine: ARMED/TRIPPED/ACKNOWLEDGED, pre-compiled regex, cooldown
- `src/cryodaq/core/experiment.py` — ExperimentManager: start/stop, config snapshot, SQLite persistence
- `src/cryodaq/core/zmq_bridge.py` — ZMQPublisher + ZMQSubscriber (msgpack) + ZMQCommandServer (JSON REP)
- `src/cryodaq/core/channel_manager.py` — ChannelManager: centralized channel names/visibility, YAML persistence

**Drivers:**
- `src/cryodaq/drivers/base.py` — Reading (frozen dataclass) + InstrumentDriver ABC
- `src/cryodaq/drivers/transport/gpib.py` — async pyvisa wrapper (GPIB)
- `src/cryodaq/drivers/transport/usbtmc.py` — async pyvisa wrapper (USB-TMC)
- `src/cryodaq/drivers/transport/serial.py` — async pyserial wrapper (RS-232)
- `src/cryodaq/drivers/instruments/lakeshore_218s.py` — LakeShore 218S: KRDG? 0, 8ch SCPI
- `src/cryodaq/drivers/instruments/keithley_2604b.py` — Keithley 2604B: TSP/Lua, heartbeat, no __del__
- `src/cryodaq/drivers/instruments/thyracont_vsp63d.py` — Thyracont VSP63D: MV00 protocol, pressure

**Storage:**
- `src/cryodaq/storage/sqlite_writer.py` — SQLiteWriter: WAL, daily rotation, dedicated ThreadPoolExecutor
- `src/cryodaq/storage/hdf5_export.py` — HDF5Exporter: groups per instrument/channel
- `src/cryodaq/storage/csv_export.py` — CSVExporter: time-range export with filters
- `src/cryodaq/storage/replay.py` — ReplaySource: historical data → DataBroker with speed control

**Analytics:**
- `src/cryodaq/analytics/base_plugin.py` — AnalyticsPlugin ABC + DerivedMetric dataclass
- `src/cryodaq/analytics/plugin_loader.py` — PluginPipeline: hot-reload, batch processing, error isolation
- `src/cryodaq/analytics/steady_state.py` — SteadyStatePredictor: T∞ prediction via scipy curve_fit
- `src/cryodaq/analytics/calibration.py` — CalibrationStore (stub for ГОСТ Р 8.879)

**Plugins (hot-reloadable):**
- `plugins/thermal_calculator.py` — R_thermal = (T_hot - T_cold) / P
- `plugins/cooldown_estimator.py` — exponential decay fit → cooldown ETA

**GUI widgets:**
- `src/cryodaq/gui/main_window.py` — MainWindow: 8 tabs, 3 menus, status bar
- `src/cryodaq/gui/widgets/temp_panel.py` — TemperaturePanel: 24ch cards + pyqtgraph
- `src/cryodaq/gui/widgets/keithley_panel.py` — KeithleyPanel: smua+smub tabs, controls, ZMQ commands
- `src/cryodaq/gui/widgets/pressure_panel.py` — PressurePanel: log-scale plot, color-coded value
- `src/cryodaq/gui/widgets/analytics_panel.py` — AnalyticsPanel: R_thermal plot + cooldown ETA
- `src/cryodaq/gui/widgets/conductivity_panel.py` — ConductivityPanel: chain R/G + T∞ prediction
- `src/cryodaq/gui/widgets/autosweep_panel.py` — AutoSweepPanel: automated power sweep measurement
- `src/cryodaq/gui/widgets/alarm_panel.py` — AlarmPanel: severity table, acknowledge
- `src/cryodaq/gui/widgets/instrument_status.py` — InstrumentStatusPanel: per-instrument cards
- `src/cryodaq/gui/widgets/channel_editor.py` — ChannelEditorDialog: edit names/visibility
- `src/cryodaq/gui/widgets/connection_settings.py` — ConnectionSettingsDialog: instrument addresses

**Web:**
- `src/cryodaq/web/server.py` — FastAPI: WebSocket, GET /status, GET /history, static dashboard
- `src/cryodaq/web/static/index.html` — Chart.js dashboard (temp + pressure + alarms + instruments)

**Notifications:**
- `src/cryodaq/notifications/telegram.py` — TelegramNotifier: alarm events → Telegram Bot API
- `src/cryodaq/notifications/telegram_commands.py` — TelegramCommandBot: /status /temps /pressure /keithley /alarms
- `src/cryodaq/notifications/periodic_report.py` — PeriodicReporter: matplotlib charts + text summary

**TSP (Keithley instrument scripts):**
- `tsp/p_const_single.lua` — P=const feedback, watchdog 30s, compliance check

### Config files

- `config/instruments.yaml` — instrument definitions (resource strings, channel labels)
- `config/interlocks.yaml` — safety interlocks (thresholds, actions, cooldowns)
- `config/alarms.yaml` — alarm thresholds (severity, hysteresis)
- `config/safety.yaml` — SafetyManager params (critical channels, stale timeout, rate limits, recovery)
- `config/notifications.yaml` — Telegram config TEMPLATE (real token in *.local.yaml)
- `config/channels.yaml` — channel display names and visibility
- `config/*.local.yaml.example` — templates for machine-specific overrides

## Instruments

- 3× LakeShore 218S (GPIB, 24 temperature channels, SCPI: KRDG? 0)
- 1× Keithley 2604B (USB-TMC, TSP/Lua, P=const feedback, smua+smub)
- 1× Thyracont VSP63D (RS-232, vacuum gauge, MV00 protocol)

## Key Rules

- **SAFE_OFF is the default.** Source ON requires continuous proof of health (SafetyManager).
- Engine must run weeks without restart. No memory leaks. No unbounded buffers.
- GUI is a separate process. Can be closed/opened without data loss.
- Keithley TSP scripts MUST have watchdog timeout → source OFF.
- No blocking I/O anywhere in engine (pyvisa via run_in_executor).
- All operator-facing text in Russian.
- Every driver: async, mock mode, timeout+retry, Reading dataclass output.
- Keithley disconnect() ALWAYS calls emergency_off() first. No __del__.
- InterlockEngine detects thresholds; SafetyManager executes actions (single authority).
- Telegram bot token NEVER committed — use config/*.local.yaml (gitignored).
- DataBroker.publish() iterates tuple snapshot (concurrent-safe).
- SQLiteWriter uses dedicated ThreadPoolExecutor (thread-safe day rotation).

## Standards

- Calibration per ГОСТ Р 8.879-2014
- DT-670B1-CU silicon diodes, individual curves per sensor
