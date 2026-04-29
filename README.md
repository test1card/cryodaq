# CryoDAQ

Software stack for cryogenic test laboratory data acquisition, control, and analysis.
Replaces a 3-year-old LabVIEW VI used to drive instruments and push email alerts.
Adds: scripted FSM-driven campaigns, automated calibration with multi-format export,
auto-generated DOCX reports, role-filtered Telegram alerts, sensor-anomaly detection
with alarm pipeline, plugin-based analytics, regression test suite (~1 970 tests).

Developed for АКЦ ФИАН (проект Millimetron).

## Status

- **Latest release:** v0.43.0 (2026-04-30)
- **Master:** `c44c575`
- **Tests:** ~1 970 passing
- **Production status:** stable; LabVIEW VI fully replaced

## Architecture overview

Three runtime processes:

- `cryodaq-engine` — headless asyncio runtime. Drives instruments, runs the safety
  manager FSM, evaluates alarms and interlocks, persists data, serves GUI commands
  via ZMQ.
- `cryodaq-gui` — Qt desktop client. Connects via ZMQ; restartable without stopping
  data acquisition.
- `cryodaq.web.server:app` — optional FastAPI monitoring dashboard.

Plus Windows launcher: `cryodaq`.

Data flow:

```
Instrument → Driver → Scheduler → SQLiteWriter → DataBroker → {GUI, SafetyBroker,
                                                                Telegram, Analytics}
```

IPC: ZeroMQ PUB/SUB `:5555` (msgpack) + REP/REQ `:5556` (JSON commands).

## Hardware (currently supported)

- 3× LakeShore 218S (GPIB) — 24 temperature channels
- Keithley 2604B (USB-TMC) — dual-channel SMU (`smua` + `smub`)
- Thyracont VSP63D (RS-232) — 1 pressure channel

## Implemented workflows

End-to-end functional as of v0.43.0:

- **Experiment FSM:** 6-phase lifecycle (idle → cooldown → measurement → warmup →
  disassembly → idle, plus aborted). Template-driven scripted runs.
- **Calibration v2:** continuous SRDG capture during calibration experiments;
  post-run pipeline (extract → downsample → multi-zone Chebyshev fit); export to
  `.cof` (raw Chebyshev coefficients) / `.340` / JSON / CSV; import from `.340` /
  JSON; runtime apply with global / per-channel policy.
- **Auto-report generation:** template-defined sections; guaranteed
  `report_editable.docx`; best-effort PDF via `soffice` / LibreOffice.
- **Telegram alerts:** role-filtered. Operators get full alarm stream; managers
  get curated subset queryable on-demand via bot commands.
- **Sensor diagnostics → alarm pipeline:** MAD-based outlier + cross-channel
  correlation drift detection. Sustained anomaly publishes alarm: warning at 5 min,
  critical at 15 min, auto-clear on recovery. Simultaneous events batched into a
  single Telegram message; configurable per-channel escalation cooldown.
- **Alarm engine v2:** threshold / rate / composite / phase-dependent rules;
  hysteresis deadband; severity upgrade in-place (WARNING→CRITICAL); ack/clear
  publish path.
- **Interlocks:** 3 hard-safety rules (cryostat / compressor / detector). Trip
  fires emergency_off and transitions interlock to TRIPPED state. Operator
  acknowledges via `interlock_acknowledge` ZMQ command to re-arm without restart.
- **Operator log:** SQLite-backed; GUI + ZMQ access.
- **Experiment templates, lifecycle metadata, artifact archival:** per-experiment
  directory with `metadata.json`, `reports/`, optional Parquet archive.
- **Plugin architecture:** ABC-based isolation; callback failures mark plugin
  degraded without crashing engine.
- **Housekeeping:** conservative adaptive throttle + retention + compression policy.

## GUI

Primary: `MainWindowV2` — Phase III complete as of v0.40.0.

Layout — ambient information radiator for week-long experiments:

- **TopWatchBar** — engine indicator, experiment status, time window echo
- **ToolRail** — overlay navigation
- **DashboardView** — 5 live zones:
  1. Sensor grid (temperature + pressure overview)
  2. Temperature plot (multi-channel, clickable legend, time window picker)
  3. Pressure plot (compact log-Y)
  4. Phase widget (experiment phase indicator + transition)
  5. Quick log (operator log inline view)
- **BottomStatusBar** — safety state indicator
- **OverlayContainer** — host for analytics and archive overlays

Overlay views (from ToolRail):

- Analytics — phase-aware widgets: W1 temperature trajectory, W2 cooldown history,
  W3 experiment summary (channel stats, top alarms, artifact links). W4 R_thermal
  remains placeholder pending F8 cooldown ML upgrade.
- Archive — past experiments + reports + Parquet exports
- Calibration — capture / fit / export workflow
- Operator log
- Other overlays per ToolRail icons

Legacy `MainWindow` (10-tab shell) remains as **permanent fallback**. Operators
see `MainWindowV2` only. Phase III closed the active migration plan.

System tray: `healthy / warning / fault`. `healthy` not shown without sufficient
backend-truth. `fault` set on unresolved alarms or safety-state `fault` /
`fault_latched`.

## Installation

### Requirements

- Windows 10/11 or Linux
- Python `>=3.12`
- Git
- VISA backend / instrument drivers as required

### Install

```bash
pip install -e ".[dev,web]"
```

Minimal runtime install:

```bash
pip install -e .
```

Supported workflow: install from repo root into an active venv. Running `pytest`
without `pip install -e ...` is not supported.

Key runtime dependencies: `PySide6`, `pyqtgraph`, `pyvisa`, `pyserial-asyncio`,
`pyzmq`, `python-docx`, `scipy`, `matplotlib`, `openpyxl`, `pyarrow`.

## Running

```bash
cryodaq-engine        # headless engine (real instruments)
cryodaq-gui           # GUI only (connects to running engine)
cryodaq               # Windows operator launcher
cryodaq-engine --mock # mock mode (simulated instruments)
uvicorn cryodaq.web.server:app --host 0.0.0.0 --port 8080  # optional web
```

## Configuration

Active config files as of v0.43.0:

- `config/instruments.yaml` — GPIB/serial/USB addresses, LakeShore channels
- `config/instruments.local.yaml` — machine-specific override (gitignored)
- `config/safety.yaml` — FSM timeouts, rate limits, drain timeout
- `config/alarms.yaml` — legacy alarm definitions
- `config/alarms_v3.yaml` — v2 alarm engine rules (threshold/rate/composite/phase)
- `config/interlocks.yaml` — interlock conditions + actions
- `config/channels.yaml` — display names, visibility, groupings
- `config/notifications.yaml` — Telegram bot_token, chat_ids, escalation
- `config/housekeeping.yaml` — throttle, retention, compression
- `config/plugins.yaml` — sensor_diagnostics + vacuum_trend; F20 `aggregation_threshold` + `escalation_cooldown_s`
- `config/cooldown.yaml` — cooldown predictor parameters
- `config/shifts.yaml` — shift definitions (GUI)
- `config/experiment_templates/*.yaml` — experiment type templates

`*.local.yaml` overrides base files for machine-specific settings.

## Experiment artifacts

```text
data/experiments/<experiment_id>/
  metadata.json
  reports/
    report_editable.docx
    report_raw.pdf      # optional, best-effort (soffice/LibreOffice)
    report_raw.docx
    assets/
data/calibration/sessions/<session_id>/
data/calibration/curves/<sensor_id>/<curve_id>/
```

## Reports

Template-defined section renderers: `title_page`, `cooldown_section`,
`thermal_section`, `pressure_section`, `operator_log_section`, `alarms_section`,
`config_section`. Guaranteed artifact: `report_editable.docx`. Optional:
`report_raw.pdf` (best-effort, requires `soffice` / LibreOffice).

## Keithley TSP

`tsp/p_const.lua` — draft TSP supervisor for P=const feedback. **Not loaded on
instrument.** P=const feedback runs host-side in `keithley_2604b.py`. TSP
supervisor planned for Phase 3 (requires hardware verification).

## Project structure

```text
src/cryodaq/
  analytics/     # calibration fitter, cooldown predictor, plugins, vacuum trend
  core/          # safety FSM, scheduler, broker, alarms v2, interlocks,
                 # sensor_diagnostics, experiments, zmq_bridge
  drivers/       # LakeShore, Keithley, Thyracont + transport adapters
  gui/           # MainWindowV2, dashboard, overlays, legacy widgets
  reporting/     # template-driven DOCX generator
  storage/       # SQLite, Parquet, CSV, HDF5, XLSX
  web/           # FastAPI monitoring
tsp/             # Keithley TSP scripts (draft, not loaded)
tests/           # ~1 970 tests
config/          # YAML configs
```

## Tests

```bash
python -m pytest tests/core -q
python -m pytest tests/storage -q
python -m pytest tests/drivers -q
python -m pytest tests/analytics -q
python -m pytest tests/gui -q
python -m pytest tests/reporting -q
```

Run after `pip install -e ".[dev,web]"`. GUI tests require `PySide6` + `pyqtgraph`.

## Known limitations

As of v0.43.0:

- **SQLite WAL gate:** engine startup hard-fails on SQLite versions in the
  WAL-reset corruption range `[3.7.0, 3.51.3)` per F25. Bypass:
  `CRYODAQ_ALLOW_BROKEN_SQLITE=1` (warning emitted). Ubuntu lab PC may have
  affected version — verify with `sqlite3 --version`.
- **Lab Ubuntu PC verification:** v0.39.0 H5 ZMQ fix verified on macOS dev only.
  Ubuntu lab box pending verification.
- **PDF reports:** best-effort only. Guaranteed artifact is DOCX.
- **Runtime calibration policy:** global on/off + per-channel KRDG/SRDG+curve.
  Conservative fallback to KRDG on missing curve / SRDG / compute error. Live
  LakeShore behavior requires lab verification.
- **Deprecation warnings:** `asyncio.WindowsSelectorEventLoopPolicy` on newer
  Python versions.

## License

See `LICENSE`. Third-party notices: `THIRD_PARTY_NOTICES.md`.
