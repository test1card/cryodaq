# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# CryoDAQ

LabVIEW replacement for cryogenic lab (АКЦ ФИАН, Millimetron).

## Build & Development Commands

```bash
pip install -e ".[dev]"        # Install in editable mode with dev deps
cryodaq-engine                 # Run the engine (headless)
cryodaq-gui                    # Run the GUI
pytest                         # Run all tests
pytest tests/drivers/          # Run driver tests only
pytest tests/core/             # Run core tests only
pytest -k test_lakeshore       # Run a single test by name
ruff check src/ tests/         # Lint
ruff format src/ tests/        # Format
```

## Architecture

Two-process system: **cryodaq-engine** (headless, asyncio) + **cryodaq-gui** (PySide6).

### Engine data flow

```
InstrumentDriver.read_channels()
  → Scheduler (per-instrument async tasks, exponential backoff reconnect)
    → DataBroker (fan-out, bounded asyncio.Queue, DROP_OLDEST)
      → SQLiteWriter (WAL, batch insert 1s, data_YYYY-MM-DD.db)
      → ZMQPublisher (PUB tcp://127.0.0.1:5555, msgpack)
      → InterlockEngine (regex channel matching → emergency_off/stop_source)
```

### GUI data flow

```
ZMQSubscriber (SUB, msgpack deserialize)
  → Qt Signal (thread-safe crossing)
    → TemperaturePanel (24x ChannelCard + pyqtgraph, deque(3600) ring buffers, 2Hz refresh)
```

### Key modules

- `src/cryodaq/drivers/base.py` — Reading (frozen dataclass) + InstrumentDriver ABC
- `src/cryodaq/drivers/transport/gpib.py` — async pyvisa wrapper (GPIB, run_in_executor)
- `src/cryodaq/drivers/transport/usbtmc.py` — async pyvisa wrapper (USB-TMC)
- `src/cryodaq/drivers/instruments/lakeshore_218s.py` — LakeShore 218S: KRDG? 0, 8ch SCPI
- `src/cryodaq/drivers/instruments/keithley_2604b.py` — Keithley 2604B: TSP/Lua supervisor, heartbeat, emergency_off
- `src/cryodaq/core/broker.py` — DataBroker: bounded queues, overflow policies
- `src/cryodaq/core/scheduler.py` — per-instrument polling, isolated tasks, backoff
- `src/cryodaq/core/zmq_bridge.py` — ZMQPublisher + ZMQSubscriber (msgpack)
- `src/cryodaq/core/interlock.py` — InterlockEngine: ARMED/TRIPPED/ACKNOWLEDGED, regex matching
- `src/cryodaq/storage/sqlite_writer.py` — SQLiteWriter: WAL, daily rotation, batch insert
- `src/cryodaq/gui/widgets/temp_panel.py` — TemperaturePanel + ChannelCard
- `tsp/p_const_single.lua` — Keithley TSP: P=const feedback, watchdog 30s, compliance check

### Config files

- `config/instruments.yaml` — instrument definitions (resource strings, channel labels)
- `config/interlocks.yaml` — safety interlocks (thresholds, actions, cooldowns)

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
