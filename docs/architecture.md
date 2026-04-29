# CryoDAQ Architecture

**Version:** v0.43.0
**Date:** 2026-04-30

---

## Overview

CryoDAQ is a Python asyncio application for cryogenic test laboratory data
acquisition and control. It replaces a LabVIEW VI stack and adds a scripted
FSM-driven experiment lifecycle, multi-format calibration export, automated
DOCX reports, Telegram notifications, and a sensor-anomaly alarm pipeline.

The system runs as two cooperating processes — a headless engine and a Qt
desktop client — connected by ZeroMQ. A third optional process serves a
FastAPI monitoring dashboard. All three share the same Python package
(`cryodaq`) and are started as separate entry points.

Per-subsystem implementation details are maintained in vault notes at
`~/Vault/CryoDAQ/10 Subsystems/`. This document is intentionally high-level.

---

## Process model

### cryodaq-engine (headless asyncio)

The engine owns all instruments, data, and safety logic. The GUI has no
direct instrument access and is NOT the source of truth for any runtime
state. Key responsibilities:

- Drive instrument drivers (LakeShore 218S, Keithley 2604B, Thyracont VSP63D)
- Persistence-first ordering: write to SQLite before publishing to brokers
- Run SafetyManager FSM (6 states)
- Evaluate alarm rules (alarm_v2) and interlock conditions
- Run sensor diagnostics pipeline (MAD + cross-channel correlation)
- Serve ZMQ REP/REQ command plane for GUI + Telegram bot commands
- Publish ZMQ PUB telemetry for GUI + archive

### cryodaq-gui (Qt desktop client)

Connects to the engine via ZMQ subprocess bridge. Restartable without
stopping data acquisition. Primary surface: `MainWindowV2` (5-zone
dashboard + overlay system). Legacy `MainWindow` (10-tab) remains as
permanent fallback. Phase III complete as of v0.40.0.

### cryodaq.web.server (optional FastAPI)

Monitoring dashboard on `:8080`. Read-only view of current engine state.
Requires `.[web]` install extra.

---

## Data flow

```
Instrument
  → InstrumentDriver.read_channels()
  → Scheduler (persistence-first)
      1. SQLiteWriter.write_immediate()   ← data on disk before anyone sees it
      2. DataBroker.publish_batch()       ← GUI, analytics, alarm engine
      3. SafetyBroker.publish_batch()     ← SafetyManager
```

ZMQ IPC:
- PUB `:5555` — msgpack telemetry (readings, events, status)
- REP `:5556` — JSON commands (GUI → engine, Telegram bot → engine)

---

## Subsystem map

Subsystems in `src/cryodaq/core/` (unless noted). Vault notes listed as
authoritative per-subsystem references.

| Subsystem | Key modules | Vault note |
|---|---|---|
| Safety FSM | `safety_manager.py`, `safety_broker.py` | `Safety FSM.md` |
| Alarm engine v2 | `alarm_v2.py`, `alarm_config.py`, `alarm_providers.py` | `Alarm engine v2.md` |
| Interlock | `interlock.py` | `Interlock engine.md` |
| Sensor diagnostics | `sensor_diagnostics.py` | `Sensor diagnostics alarm.md` |
| Scheduler | `scheduler.py` | — |
| Data broker | `broker.py` | — |
| ZMQ bridge | `zmq_bridge.py`, `zmq_subprocess.py` | `ZMQ bridge.md` |
| Experiment manager | `experiment.py` | `Experiment manager.md` |
| Storage | `storage/sqlite_writer.py`, `storage/parquet_archive.py`, `storage/cold_rotation.py`, `storage/archive_reader.py` | `Persistence-first.md` |
| Reporting | `reporting/generator.py` | `Reporting.md` |
| Calibration | `analytics/calibration.py`, `analytics/calibration_fitter.py`, `core/calibration_acquisition.py` | `Calibration v2.md` |
| Cooldown predictor | `analytics/cooldown_predictor.py`, `analytics/cooldown_service.py` | `Cooldown predictor.md` |
| Plugin architecture | `analytics/base_plugin.py`, `analytics/plugin_loader.py` | `Plugin architecture.md` |
| Drivers | `drivers/instruments/`, `drivers/transport/` | `Keithley 2604B.md`, `LakeShore 218S.md`, `Thyracont VSP63D.md` |
| GUI shell | `gui/shell/main_window_v2.py`, `gui/dashboard/` | — |
| Web dashboard | `web/server.py` | `Web dashboard.md` |

---

## Persistence-first invariant

**If DataBroker has a reading, it has already been written to SQLite.**

Write order enforced in `Scheduler`: `SQLiteWriter.write_immediate()` completes
before `DataBroker.publish_batch()` is called. SafetyBroker receives after
DataBroker. This ordering is not negotiable.

---

## SafetyState FSM

Six states:

```
SAFE_OFF → READY → RUN_PERMITTED → RUNNING → FAULT_LATCHED → MANUAL_RECOVERY → READY
```

- `SAFE_OFF` is the default. Source ON requires continuous proof of health.
- `FAULT_LATCHED` entered on stale data, rate-limit breach, or explicit fault.
- `MANUAL_RECOVERY` entered after `acknowledge_fault()`; returns to READY when
  preconditions restore.
- `RUNNING` is the only state where stale-data fault fires; outside RUNNING,
  stale data blocks readiness via preconditions.
- Rate limit: `dT/dt > 5 K/min` → FAULT (configurable in `safety.yaml`).

---

## Configuration

Config files in `config/`:

| File | Purpose |
|---|---|
| `instruments.yaml` + `instruments.local.yaml` | GPIB/serial/USB addresses |
| `safety.yaml` | FSM timeouts, rate limits, drain timeout |
| `alarms.yaml` | Legacy alarm definitions |
| `alarms_v3.yaml` | v2 alarm engine rules |
| `interlocks.yaml` | Interlock conditions + actions |
| `channels.yaml` | Display names, visibility, groupings |
| `notifications.yaml` | Telegram credentials + escalation |
| `housekeeping.yaml` | Throttle, retention, compression |
| `plugins.yaml` | sensor_diagnostics + vacuum_trend config |
| `cooldown.yaml` | Cooldown predictor parameters |
| `shifts.yaml` | Shift definitions (GUI only) |
| `experiment_templates/*.yaml` | Experiment type templates |

`*.local.yaml` overrides base files. Local configs are gitignored and intended
for machine-specific deployment settings (COM ports, GPIB addresses, tokens).

---

## Test architecture

~1 970 tests under `tests/`. Structure mirrors `src/cryodaq/`:

```
tests/
  core/      # safety, alarms, interlocks, sensor_diag, rate_estimator, …
  storage/   # sqlite_writer, parquet, csv, xlsx
  drivers/   # instrument + transport mocks
  analytics/ # calibration, cooldown, plugins
  gui/       # dashboard, shell, widgets (PySide6 headless)
  reporting/ # DOCX template rendering
  web/       # FastAPI endpoints
```

Key fixture patterns: `@pytest.mark.asyncio` for engine components;
`SafetyBroker(mock=True)` / `SafetyManager(..., mock=True)` for safety FSM
tests without real instruments.

Full suite: `pytest -q`. GUI tests require `PySide6` + `pyqtgraph`.
Headless GUI testing uses `QApplication` fixture from `conftest.py`.

---

## Why these choices

**Python + asyncio over LabVIEW VI:** The LabVIEW VI had no version control, no
test suite, and no experiment-lifecycle tracking. A single person could not
extend it safely. Python + asyncio gives a reproducible, testable, Git-managed
codebase with the same or better instrument throughput at lab cadences (0.5 s
polling intervals, not microsecond real-time).

**ZMQ for IPC over shared state:** GUI and engine run as separate processes to
avoid a single-crash taking both down. ZMQ gives a clean async boundary;
the GUI can restart without disrupting acquisition. The engine never trusts
the GUI as a safety authority.

**Out of scope:** real-time DAQ at microsecond cadence, hardware PID loops
running on Python (TSP supervisor on Keithley is planned for Phase 3 but
not yet loaded), multi-station federation.
