# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

# CryoDAQ

LabVIEW replacement for a cryogenic laboratory workflow (Millimetron / АКЦ ФИАН).
Python 3.12+, asyncio, PySide6. Current package metadata: `0.11.0rc1`.

## Build & Development Commands

```bash
pip install -e ".[dev,web]"    # Install runtime, dev, and optional web dependencies
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

## Environment Variables

- `CRYODAQ_ROOT` — override project root directory
- `CRYODAQ_MOCK=1` — start engine in mock mode

## Deployment

`config/*.local.yaml` overrides `config/*.yaml`.
Local configs are gitignored and intended for machine-specific deployment data such as COM ports, GPIB addresses, and notification credentials.

See `docs/deployment.md` for operator-PC deployment steps.

## Architecture

Three main runtime surfaces:

- `cryodaq-engine` — headless asyncio runtime: acquisition, safety, storage, commands
- `cryodaq-gui` or `cryodaq` — desktop operator client / launcher
- web dashboard — optional FastAPI monitoring surface

### Safety architecture

SafetyManager is the single authority for source on/off decisions.
Source OFF is the default. Running requires continuous proof of health.

```text
SafetyBroker (dedicated, overflow=FAULT)
  -> SafetyManager
     States: SAFE_OFF -> READY -> RUN_PERMITTED -> RUNNING -> FAULT_LATCHED
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

### GUI tabs

Current `MainWindow` tabs:

- `Обзор`
- `Keithley 2604B`
- `Аналитика`
- `Теплопроводность`
- `Автоизмерение`
- `Алармы`
- `Журнал оператора`
- `Архив`
- `Калибровка`
- `Приборы`

Menus:

- `Файл` — CSV / HDF5 / Excel export
- `Эксперимент` — start / finalize experiment
- `Настройки` — channel editor and connection settings

### Module index

**Entry points**

- `src/cryodaq/engine.py` — headless engine
- `src/cryodaq/launcher.py` — operator launcher
- `src/cryodaq/gui/app.py` — standalone GUI entry point

**Core**

- `src/cryodaq/core/alarm.py`
- `src/cryodaq/core/experiment.py`
- `src/cryodaq/core/housekeeping.py`
- `src/cryodaq/core/operator_log.py`
- `src/cryodaq/core/safety_broker.py`
- `src/cryodaq/core/safety_manager.py`
- `src/cryodaq/core/scheduler.py`
- `src/cryodaq/core/zmq_bridge.py`

**GUI**

- `src/cryodaq/gui/main_window.py`
- `src/cryodaq/gui/tray_status.py`
- `src/cryodaq/gui/widgets/archive_panel.py`
- `src/cryodaq/gui/widgets/calibration_panel.py`
- `src/cryodaq/gui/widgets/operator_log_panel.py`
- `src/cryodaq/gui/widgets/overview_panel.py`
- `src/cryodaq/gui/widgets/keithley_panel.py`

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
- `tsp/p_const_single.lua` — legacy/fallback artifact still present in the tree

## Config files

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

## Instruments

- LakeShore 218S
- Keithley 2604B
- Thyracont VSP63D

## Key Rules

- `SAFE_OFF` is the default.
- GUI is a separate process and must not be the source of truth for runtime state.
- Keithley disconnect must call emergency off first.
- No blocking I/O on the engine event loop.
- Operator-facing GUI text should remain in Russian.
- Scheduler writes to SQLite before publishing to brokers.

## Known limitations (RC)

- Calibration apply path into runtime is not implemented; the GUI keeps this action disabled.
- Report PDF conversion is best-effort; DOCX is the required artifact.
- `WindowsSelectorEventLoopPolicy` produces known Python 3.14+ deprecation warnings.
