# CryoDAQ Architecture

**Version:** v0.64.1
**Date:** 2026-07-15

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

This document is intentionally high-level; per-subsystem details live in
module docstrings and the design system (`docs/design-system/`).

---

## Process model

### cryodaq-engine (headless asyncio)

The engine owns all instruments, data, and safety logic. The GUI has no
direct instrument access and is NOT the source of truth for any runtime
state. Key responsibilities:

- Drive instrument drivers (LakeShore 218S, Keithley 2604B, Thyracont VSP63D,
  Etalon MultiLine)
- Persistence-first ordering: write to SQLite before publishing to brokers
- Run SafetyManager FSM (6 states)
- Evaluate alarm rules (alarm_v2) and interlock conditions
- Run sensor diagnostics pipeline (MAD + cross-channel correlation)
- Serve ZMQ REP/REQ command plane for GUI + Telegram bot commands
- Publish ZMQ PUB telemetry for GUI + archive
- Compose and publish one revisioned observational operator snapshot from the
  SafetyManager and loop-owned recording/persistence feeds

### cryodaq-gui (Qt desktop client)

Connects to the engine via ZMQ subprocess bridge. Restartable without
stopping data acquisition. Sole surface: `MainWindowV2` — shell chrome
(TopWatchBar + ToolRail + BottomStatusBar) around a 5-zone dashboard and
an overlay system. The legacy 10-tab `MainWindow` was retired in
Phase II.13; there is no v1 fallback.

### cryodaq.web.server (optional FastAPI)

Monitoring dashboard on `:8080` (loopback bind only; LAN access via SSH
tunnel). REST facade `/api/v1`: read-only GET surface plus exactly two
authenticated write endpoints (`POST /log`, `POST /alarms/{id}/ack`) behind
a write token in gitignored `config/web.local.yaml`. Requires `.[web]`
install extra.

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

### Operator snapshot publication

The operator-snapshot lane is observational and has one engine-loop lifecycle
owner. It samples the cached SafetyManager proof and the exact
`RecordingLifecycleFeed`, allocates one durable global revision only after a
complete cut validates, and sends the cut on the existing PUB socket. Cold or
disconnected mandatory authorities publish nothing; stale or ambiguous
persistence publishes explicit `NOT_RECORDING`/unavailable-storage truth. The
lane has no command, driver, actuator, or fallback-writer capability.

---

## Subsystem map

Subsystems in `src/cryodaq/core/` (unless noted).

| Subsystem | Key modules |
|---|---|
| Safety FSM | `safety_manager.py`, `safety_broker.py` |
| Alarm engine v2 | `alarm_v2.py`, `alarm_config.py`, `alarm_providers.py` |
| Physical alarms | `vacuum_guard.py`, `cooldown_alarm.py`, `physical_alarms_config.py` |
| Interlock | `interlock.py` |
| Sensor diagnostics | `sensor_diagnostics.py` |
| Scheduler | `scheduler.py` |
| Data broker | `broker.py` |
| ZMQ bridge | `zmq_bridge.py`, `zmq_subprocess.py` |
| Experiment manager | `experiment.py` |
| Storage | `storage/_sqlite.py`, `storage/sqlite_writer.py`, `storage/parquet_archive.py`, `storage/cold_rotation.py`, `storage/archive_reader.py` |
| Reporting | `reporting/generator.py` |
| Calibration | `analytics/calibration.py`, `analytics/calibration_fitter.py`, `core/calibration_acquisition.py` |
| Cooldown predictor | `analytics/cooldown_predictor.py`, `analytics/cooldown_service.py` |
| Plugin architecture | `analytics/base_plugin.py`, `analytics/plugin_loader.py` |
| Drivers | `drivers/instruments/`, `drivers/transport/` |
| GUI shell | `gui/shell/main_window_v2.py`, `gui/dashboard/` |
| Web dashboard | `web/server.py`, `web/rest_api.py` |

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
- Verified-off discipline (v0.64.0): an OFF command whose readback cannot
  confirm the output actually turned off raises → `FAULT_LATCHED`; the system
  never reports `SAFE_OFF` over a possibly-live output, and RUN is blocked
  while the output state is unverified.

---

## Configuration

Config files in `config/`:

| File | Purpose |
|---|---|
| `instruments.yaml` + `instruments.local.yaml` | GPIB/serial/USB addresses |
| `safety.yaml` | FSM timeouts, rate limits, drain timeout |
| `alarms_v3.yaml` | Alarm engine rules |
| `physical_alarms.yaml` | VacuumGuard + CooldownAlarm tunables |
| `interlocks.yaml` | Interlock conditions + actions |
| `channels.yaml` | Display names, visibility, groupings |
| `channel_descriptors.yaml` + `channel_descriptors.local.yaml` | Canonical channel-identity descriptor authority (see below) |
| `notifications.yaml` | Telegram credentials + escalation |
| `housekeeping.yaml` | Throttle, retention, cold rotation |
| `plugins.yaml` | sensor_diagnostics + vacuum_trend config |
| `cooldown.yaml` | Cooldown predictor parameters |
| `analytics_layout.yaml` | Analytics view widget layout |
| `agent.yaml` | Local-assistant runtime settings |
| `experiment_templates/*.yaml` | Experiment type templates |
| `web.local.yaml` | Web write token (gitignored) |

`*.local.yaml` overrides base files. Local configs are gitignored and intended
for machine-specific deployment settings (COM ports, GPIB addresses, tokens).

### Channel descriptor authority

`config/channel_descriptors.yaml` is the whole-file **descriptor authority**:
it assigns every acquired reading a stable canonical identity, independent of
the raw label an instrument happens to emit. It is distinct from `channels.yaml`
(which only governs display names, visibility, and GUI grouping).

- **Bindings.** Each `(instrument_id, emitted_channel)` pair maps to exactly one
  canonical `channel_id` — e.g. a LakeShore emitting `"Т1 Криостат верх"` binds
  to `"Т1"`. Bindings are one-to-one: no two raw channels share a `channel_id`,
  and no `channel_id` is bound twice.
- **Canonical identity, not display text.** Downstream consumers — persistence,
  interlocks, replay, reporting — key on the canonical `channel_id`; human-facing
  text comes from the descriptor's `display_name`, never from the raw emitted
  label.
- **Whole-file replacement.** A machine-local `channel_descriptors.local.yaml`
  (copied from the tracked `.example`) is a *complete* replacement of the base
  manifest, never a partial merge. If present it must exist and validate; a
  malformed or incomplete local file fails closed and never falls back to the
  base.
- **Fail-closed loading.** The manifest is parsed under a strict bounded grammar
  with symlink-free, single-link, TOCTOU-checked reads; any schema, identity, or
  integrity violation raises rather than loading a partial authority.
- **Identity only, not capability.** A descriptor confers channel identity alone
  — it does not grant hazardous-source authority (that lives in the safety
  subsystem).
- **Reconcile before lab use.** The tracked base roster and the machine-local
  physical roster must be reconciled before a deployment drives real hardware.

Loader: `src/cryodaq/storage/channel_descriptors.py`
(`load_live_channel_descriptor_catalog`).

The shell's generic instrument-health presentation consumes the frozen
GUI-owned `DescriptorView` produced after qualified ingress. It attributes a
card only while identity is authoritative and transport is connected; a bare
`Reading.instrument_id`, vendor/model text, channel prefix, or LakeShore
channel range is never a presentation identity fallback. Missing or refused
identity remains visible as bounded operator text and grants no control
authority. Specialized legacy feature routing elsewhere in the shell still
uses channel/unit adapters and is tracked separately.

---

## Test architecture

~3 600 tests under `tests/` (per-release baseline in `CHANGELOG.md`).
Structure mirrors `src/cryodaq/`:

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
running on Python, multi-station federation. Safety regulation is host-side;
the Keithley TSP v3 script (`tsp/cryodaq_wdog.lua`) is an operator-selectable
software late-pet check (`keithley.watchdog.mode: off | best_effort |
required`). It is explicitly non-autonomous: `best_effort` covers only
stall-then-recover, while `required` refuses v3 because its independent
autonomous contract bit is 0. Host-death energy removal remains a physical
architecture and proof-test gate, preferably using an independent latching
cutout rather than another path inside the same SMU.
