# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# CryoDAQ

LabVIEW replacement for cryogenic lab (АКЦ ФИАН, Millimetron).

## Build & Development Commands

```bash
pip install -e ".[dev,web]"    # Install all deps
cryodaq                        # Operator launcher (auto-starts engine + GUI)
cryodaq-engine                 # Run engine headless (real instruments)
cryodaq-engine --mock          # Run engine with simulated data
cryodaq-gui                    # Run GUI only (connects to engine via ZMQ)
uvicorn cryodaq.web.server:app --host 0.0.0.0 --port 8080  # Web dashboard
install.bat                    # One-click Windows installer
python create_shortcut.py      # Create desktop shortcut
pytest                         # Run all tests
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

Two-process system: **cryodaq-engine** (headless, asyncio) + **cryodaq-gui** (PySide6).
Optional: **web dashboard** (FastAPI + WebSocket) for remote monitoring.

### Engine data flow

```
InstrumentDriver.read_channels()
  → Scheduler (per-instrument async tasks, exponential backoff reconnect)
    → DataBroker (fan-out, bounded asyncio.Queue, DROP_OLDEST)
      → SQLiteWriter (WAL, batch insert 1s, data_YYYY-MM-DD.db)
      → ZMQPublisher (PUB tcp://127.0.0.1:5555, msgpack)
      → AlarmEngine (threshold + hysteresis → notifiers)
      → InterlockEngine (regex channel matching → emergency_off/stop_source)
      → PluginPipeline (hot-reload analytics → DerivedMetric → back to broker)
```

### GUI data flow

```
ZMQSubscriber (SUB, msgpack deserialize)
  → Qt Signal (thread-safe crossing)
    → MainWindow (tabs: Температуры, Keithley, Аналитика, Алармы, Статус)
      → TemperaturePanel (24x ChannelCard + pyqtgraph, deque(3600), 2Hz refresh)
      → AlarmPanel (severity-sorted table, acknowledge buttons)
      → InstrumentStatusPanel (per-instrument cards, liveness timeout)
```

### Module index

**Entry points:**
- `src/cryodaq/engine.py` — headless engine: loads config, wires subsystems, graceful shutdown, watchdog
- `src/cryodaq/gui/app.py` — GUI entry point: QApplication + asyncio + ZMQSubscriber

**Core:**
- `src/cryodaq/core/broker.py` — DataBroker: bounded queues, overflow policies, fan-out
- `src/cryodaq/core/scheduler.py` — per-instrument polling, isolated tasks, exponential backoff
- `src/cryodaq/core/alarm.py` — AlarmEngine: OK/ACTIVE/ACKNOWLEDGED, hysteresis, severity, notifiers
- `src/cryodaq/core/interlock.py` — InterlockEngine: ARMED/TRIPPED/ACKNOWLEDGED, regex matching, cooldown
- `src/cryodaq/core/experiment.py` — ExperimentManager: start/stop, config snapshot, SQLite persistence
- `src/cryodaq/core/zmq_bridge.py` — ZMQPublisher + ZMQSubscriber (msgpack)

**Drivers:**
- `src/cryodaq/drivers/base.py` — Reading (frozen dataclass) + InstrumentDriver ABC
- `src/cryodaq/drivers/transport/gpib.py` — async pyvisa wrapper (GPIB, run_in_executor)
- `src/cryodaq/drivers/transport/usbtmc.py` — async pyvisa wrapper (USB-TMC)
- `src/cryodaq/drivers/instruments/lakeshore_218s.py` — LakeShore 218S: KRDG? 0, 8ch SCPI
- `src/cryodaq/drivers/instruments/keithley_2604b.py` — Keithley 2604B: TSP/Lua supervisor, heartbeat, emergency_off

**Storage:**
- `src/cryodaq/storage/sqlite_writer.py` — SQLiteWriter: WAL, daily rotation, batch insert
- `src/cryodaq/storage/hdf5_export.py` — HDF5Exporter: SQLite → HDF5 (groups per instrument/channel)
- `src/cryodaq/storage/csv_export.py` — CSVExporter: time-range export with filters
- `src/cryodaq/storage/replay.py` — ReplaySource: historical data → DataBroker with speed control

**Analytics:**
- `src/cryodaq/analytics/base_plugin.py` — AnalyticsPlugin ABC + DerivedMetric dataclass
- `src/cryodaq/analytics/plugin_loader.py` — PluginPipeline: hot-reload, batch processing, error isolation
- `src/cryodaq/analytics/calibration.py` — CalibrationStore (stub for ГОСТ Р 8.879 recalibration)

**Plugins (hot-reloadable):**
- `plugins/thermal_calculator.py` — R_thermal = (T_hot - T_cold) / P
- `plugins/cooldown_estimator.py` — exponential decay fit → cooldown ETA

**GUI:**
- `src/cryodaq/gui/main_window.py` — MainWindow: tabs, menu (export CSV/HDF5), status bar
- `src/cryodaq/gui/widgets/temp_panel.py` — TemperaturePanel + ChannelCard (24ch, pyqtgraph)
- `src/cryodaq/gui/widgets/alarm_panel.py` — AlarmPanel: severity table, acknowledge
- `src/cryodaq/gui/widgets/instrument_status.py` — InstrumentStatusPanel: per-instrument cards

**Web:**
- `src/cryodaq/web/server.py` — FastAPI: WebSocket stream, GET /status, static dashboard
- `src/cryodaq/web/static/index.html` — single-page dashboard (temperatures, alarms, auto-refresh)

**Notifications:**
- `src/cryodaq/notifications/telegram.py` — TelegramNotifier: alarm → Telegram Bot API (aiohttp)
- `src/cryodaq/notifications/telegram_commands.py` — TelegramCommandBot: /status, /temps, /pressure, /keithley, /alarms
- `src/cryodaq/launcher.py` — Operator launcher: auto-starts engine, embeds GUI, system tray

**TSP (Keithley instrument scripts):**
- `tsp/p_const_single.lua` — P=const feedback, watchdog 30s, compliance check

### Config files

- `config/instruments.yaml` — instrument definitions (resource strings, channel labels)
- `config/interlocks.yaml` — safety interlocks (thresholds, actions, cooldowns)
- `config/alarms.yaml` — alarm thresholds (severity, hysteresis)
- `config/notifications.yaml` — Telegram bot token, chat_id

## Instruments

- 3x LakeShore 218S (GPIB, 24 temperature channels, SCPI: KRDG? 0)
- 1x Keithley 2604B (USB-TMC, TSP/Lua, P=const feedback loop inside instrument)
- Vacuum gauge (TBD, will be added as module)

## Key Rules

- Engine must run weeks without restart. No memory leaks. No unbounded buffers.
- GUI is separate process. Can be closed/opened without data loss.
- Keithley TSP scripts MUST have watchdog timeout -> source OFF.
- No blocking I/O anywhere in engine (all pyvisa via run_in_executor).
- All operator-facing text in Russian.
- No platform-specific code in business logic (pathlib, config-driven).
- Every driver: async, mock mode, timeout+retry, Reading dataclass output.
- Keithley: disconnect() ALWAYS calls emergency_off() first.
- InterlockEngine: action executes synchronously (blocks until complete) before continuing.

## Standards

- Calibration per ГОСТ Р 8.879-2014
- DT-670B1-CU silicon diodes, individual curves per sensor
