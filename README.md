**English** · [Русский](README.ru.md)

# CryoDAQ

Data acquisition, control, and analysis stack for a cryogenics laboratory.
Replaces a 3-year-old LabVIEW VI that drove the instruments and sent email alerts.
Adds: scripted FSM campaigns, automated calibration with multi-format export,
auto-generated DOCX reports, role-based Telegram alerts, sensor anomaly detection
with an alarm pipeline, plugin analytics, a local operator-query layer with a
knowledge base (RAG), historical-data replay mode,
interferometric length metrology (Etalon MultiLine), and a regression test suite
(3500 test functions across 324 files).

Built for ASC LPI (the Millimetron project).

## Status

- **Latest release:** v0.64.1 (2026-07-08)
- **Tests:** 3500 test functions across 324 files
- **Production status:** stable; the LabVIEW VI is fully replaced

## Architecture

Three runtime processes:

- `cryodaq-engine` — headless asyncio runtime. Drives the instruments, runs the
  safety-manager FSM, evaluates alarm rules and interlocks, persists data, and
  serves GUI commands over ZMQ.
- `cryodaq-gui` — Qt desktop client. Connects over ZMQ; can restart without
  stopping data acquisition.
- `cryodaq.web.server:app` — optional FastAPI monitoring dashboard.

Plus a Windows launcher: `cryodaq`.

Data flow:

```
Instrument → Driver → Scheduler → SQLiteWriter → DataBroker → {GUI, SafetyBroker,
                                                                Telegram, Analytics}
```

IPC: ZeroMQ PUB/SUB `:5555` (msgpack) + REP/REQ `:5556` (JSON commands).

## Supported instruments

- 3× LakeShore 218S (GPIB) — 24 temperature channels
- Keithley 2604B (USB-TMC) — dual-channel SMU (`smua` + `smub`)
- Thyracont VSP63D (RS-232) — 1 pressure channel
- Etalon MultiLine (TCP/IP) — interferometric length metrology; averaged and
  continuous modes, vibration burst capture to Parquet

## Implemented workflows

Fully functional in v0.64.0:

- **Knowledge base (RAG):** local semantic search over the experiment archive,
  vault notes, the operator log, and the `data/knowledge/` corpus
  (`equipment_manuals` — instrument PDFs via pypdf; `procedures` — Markdown;
  `reference` — operator manual / README / CHANGELOG). The RAG module:
  loader -> LanceDB indexer -> top-K searcher; embeddings `qwen3-embedding:0.6b`
  (1024-dim) via Ollama. CLI `cryodaq-rag-index` / `cryodaq-rag-search`,
  ZMQ `rag.rebuild_index` / `rag.rebuild_status`, and an "Update index" button in
  the KnowledgeBasePanel. Bootstraps on engine start when the index is empty.
- **Local operator-query service:** a local Ollama service (no external APIs)
  classifies operator intent (IntentClassifier), routes the query
  (QueryRouter), and answers from live data (BrokerSnapshot) and the knowledge
  base (KNOWLEDGE_QUERY). Read-only; full audit trail for every model call.
- **Historical-data replay:** replays records through the DataBroker; a predictor
  runs on top of the replay stream with a decoupled clock for accelerated
  playback; `cryodaq-replay-curve` for curve transforms; a legacy channel map
  for pre-2025 records.
- **Experiment FSM:** a 6-phase lifecycle (idle → cooldown → measurement →
  warmup → disassembly → idle, plus aborted). Templated scripted runs.
- **Calibration v2:** continuous SRDG acquisition during calibration experiments;
  post-processing (extract → downsample → Chebyshev fit per zone); export to
  `.cof` (raw coefficients) / `.340` / JSON / CSV; import from `.340` / JSON;
  runtime application with a global / per-channel policy.
- **Auto-generated reports:** templated sections; a guaranteed
  `report_editable.docx`; best-effort PDF via `soffice` / LibreOffice.
- **Telegram alerts:** role-based filtering. Operators receive the full alarm
  stream; managers get a curated subset with on-demand queries via bot commands.
- **Sensor diagnostics → alarm pipeline:** MAD-outlier + cross-channel
  correlation-drift detection. A persistent anomaly publishes an alarm: warning
  after 5 min, critical after 15 min, auto-clear on recovery. Concurrent events
  are aggregated into a single Telegram message; configurable cooldown.
- **Alarm engine v2:** threshold / rate / composite / phase-dependent rules; a
  hysteresis deadband; in-place severity escalation (WARNING→CRITICAL); an
  ack/clear publish path.
- **Interlocks:** 3 hard-protection rules (cryostat / compressor / detector). A
  trip → `emergency_off` + transition to TRIPPED. The operator acknowledges via
  the `interlock_acknowledge` ZMQ command without a restart.
- **Fail-closed safety discipline:** Keithley output OFF is readback-verified;
  unverified OFF becomes a fault or a blocking RUN precondition instead of a
  false SAFE_OFF. VacuumGuard escalates to SafetyManager by default via
  `vacuum_guard.escalate_to_safety` (set `false` for attended/debug runs).
- **Operator log:** SQLite-backed; accessed via the GUI + ZMQ.
- **Experiment templates, lifecycle metadata, artifact archiving:** a
  `data/experiments/<id>/` directory with `metadata.json`, `reports/`, and an
  optional Parquet archive.
- **Plugin architecture:** ABC isolation; a failing callback marks the plugin
  degraded without crashing the engine.
- **Housekeeping:** adaptive throttle + retention + compression.
- **Cold-storage rotation (F17):** enabled by default
  (`cold_rotation.enabled: true`). `ColdRotationService` is wired into the
  engine and runs daily at `schedule_time` (03:00): daily SQLite files older
  than 30 days rotate into Parquet/Zstd. Every reader goes through
  `ArchiveReader` (hot SQLite ∪ cold Parquet) — GUI history, live operator
  journal, reports, CSV/XLSX/HDF5/Parquet exports, replay, and calibration all
  see rotated days. The only kill-switch is `cold_rotation.enabled`; rotation
  is idempotent and the stranded-DB sweep deletes only a byte-identical
  original (`source_md5`).
- **SQLite self-heal on Linux:** all runtime DB connections go through
  `storage/_sqlite.py`; if the stdlib SQLite is in the unsafe WAL-reset range,
  the shim falls back to the bundled Linux `pysqlite3-binary`.
- **Leak-rate estimation (F13):** `LeakRateEstimator` — a rolling window, OLS
  regression without numpy, history in `data/leak_rate_history.json`. Commands:
  `leak_rate_start` / `leak_rate_stop` (ZMQ). Requires `chamber.volume_l` in
  `instruments.local.yaml`.

## GUI

Primary shell: `MainWindowV2` — Phase III completed in v0.40.0.

Layout — an ambient information radiator for week-long experiments:

- **TopWatchBar** — engine indicator, experiment status, time-window echo
- **ToolRail** — navigation across overlay panels
- **DashboardView** — 5 live zones:
  1. Sensor grid (temperature + pressure overview)
  2. Temperature plot (multi-channel, clickable legend, window selection)
  3. Pressure plot (compact log-Y)
  4. Phase widget (experiment-phase indicator + transition)
  5. Quick log (inline operator-log view)
- **BottomStatusBar** — safety-state indicator
- **OverlayContainer** — host for analytics and archive

Overlay panels (from the ToolRail):

- Analytics — phase-aware widgets: temperature trajectory, cooldown history,
  experiment summary (channel statistics, top alarm, artifact links), cooldown
  forecast (cooldown predictor, a progress-variable ensemble with ETA), and
  steady-state temperature forecast (T∞ via an exponential fit).
- Archive — past experiments + reports + Parquet exports
- Calibration — the capture / fit / export workflow
- Knowledge base — RAG search + embedded operator chat
- MultiLine — interferometric metrology + "Vibration capture" (burst)
- Operator log
- Other overlays via ToolRail icons

`MainWindowV2` is the sole operator shell. The legacy tab-based `MainWindow` and
all tab-era overlays were removed in Phase II.13; `cryodaq-gui` has used
`MainWindowV2` since Phase I.1.

System tray: `healthy / warning / fault`. `healthy` is not shown without
sufficient backend confirmation. `fault` — on unacknowledged alarms or a
safety state of `fault` / `fault_latched`.

## Installation

### Requirements

- Windows 10/11 or Linux
- Python `>=3.12` (must link SQLite `>=3.51.3`, or a backport-safe 3.44.6 / 3.50.7
  — see "Known limitations")
- Git
- A VISA backend / instrument drivers as needed

### Install

```bash
pip install -e ".[dev,web]"
```

Minimal runtime install:

```bash
pip install -e .
```

Supported workflow: install from the repository root into an active venv.
Running `pytest` without `pip install -e ...` is not supported.

Key runtime dependencies: `PySide6`, `pyqtgraph`, `pyvisa`, `pyserial-asyncio`,
`pyzmq`, `python-docx`, `scipy`, `matplotlib`, `openpyxl`, `pyarrow`.

## Running

```bash
cryodaq-engine        # headless engine (real instruments)
cryodaq-gui           # GUI only (connects to a running engine)
cryodaq               # Windows operator launcher
cryodaq-engine --mock # mock mode (simulated instruments)
uvicorn cryodaq.web.server:app --host 127.0.0.1 --port 8080  # optional web (loopback)
```

The web dashboard's GET surface has no authentication — bind it to `127.0.0.1`
only; public access requires a reverse proxy with authorization (or an SSH
tunnel). The two `/api/v1` write endpoints (`POST /log`, `POST /alarms/{id}/ack`)
require a bearer token from the gitignored `config/web.local.yaml`.

Helper CLIs:

```bash
cryodaq-cooldown build/predict   # cooldown ML: training and ETA prediction
cryodaq-replay-curve             # curve transforms for replay
cryodaq-rag-index                # build the knowledge-base index
cryodaq-rag-search               # semantic search over the knowledge base
```

## Configuration

Active configuration files as of v0.64.0:

- `config/instruments.yaml` — GPIB/serial/USB addresses, LakeShore channels,
  `chamber.volume_l` for the F13 leak rate
- `config/instruments.local.yaml.example` — template for machine-specific
  instrument overrides (`instruments.local.yaml` is gitignored)
- `config/safety.yaml` — FSM timeouts, rate limits, drain timeout
- `config/alarms_v3.yaml` — alarm engine rules (threshold/rate/composite/phase)
- `config/interlocks.yaml` — interlock conditions + actions
- `config/physical_alarms.yaml` — tunables for the cold-cryostat physical
  guards (CooldownAlarm, VacuumGuard, including the
  `vacuum_guard.escalate_to_safety` latch — on by default)
- `config/channels.yaml` — display names, visibility, grouping
- `config/notifications.yaml` — Telegram bot_token, chat_ids, escalation
- `config/notifications.local.yaml.example` — template for local Telegram
  credentials (`notifications.local.yaml` is gitignored)
- `config/housekeeping.yaml` — throttle, retention, compression, `cold_rotation`
- `config/plugins.yaml` — sensor_diagnostics + vacuum_trend; `aggregation_threshold` + `escalation_cooldown_s`
- `config/cooldown.yaml` — cooldown-predictor parameters
- `config/analytics_layout.yaml` — phase-aware analytics widget layout
- `config/agent.yaml` — local operator-query service (Ollama model, triggers, rate limit)
- `config/rag.yaml.example` — knowledge base / RAG (embedding model, corpus)
- `config/rag_categories.yaml` — KnowledgeBasePanel sidebar query presets
- `config/sinks.yaml.example` — sinks (vault notes, webhook) on finalize
- `config/web.local.yaml.example` — template for the FastAPI write-token
  (`web.local.yaml` is gitignored)
- `config/themes/*.yaml` — bundled GUI theme packs; selected via gitignored
  `config/settings.local.yaml`
- `config/experiment_templates/*.yaml` — experiment-type templates

`*.local.yaml` files override the base files for machine-specific settings.

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
data/archive/year=YYYY/month=MM/  # Parquet cold storage (F17)
data/leak_rate_history.json        # leak-measurement history (F13)
```

## Reports

Templated sections: `title_page`, `cooldown_section`, `thermal_section`,
`pressure_section`, `operator_log_section`, `alarms_section`, `config_section`.
Guaranteed artifact: `report_editable.docx`. Optional: `report_raw.pdf`
(best-effort, requires `soffice` / LibreOffice).

## Keithley TSP

`tsp/cryodaq_wdog.lua` — a TSP software late-pet checker below the host
SafetyManager. P=const still runs host-side in `keithley_2604b.py`.
The watchdog is operator-selectable via `config/instruments.yaml` →
`keithley.watchdog.mode`: `off` (driver default — script not loaded, host is the
sole authority), `best_effort` (activate on connect, fall back to host-only on
failure), `required` (fail-closed — requires the explicit autonomous bit and
makes `connect()` raise while it is absent, so `SAFE_OFF` holds). Version 3
explicitly reports `cryodaq_wdog_autonomous=0`:
it covers only stall-then-recover when a later pet arrives and has zero
full-host-death coverage. The previous timer implementation was removed because
it used commands and action values that the 2600B reference manual does not
document as valid. A true host-death OFF path requires a documented redesign
and physical proof; an independent latching cutout/interlock is preferred.
`watchdog.timeout_s` must be a finite number from 1 to 300 seconds; the TSP
clock has one-second granularity and uses a strict `elapsed > timeout` test.

## Project structure

```text
src/cryodaq/
  agents/        # local query service + RAG knowledge base
  analytics/     # calibration fitter, cooldown predictor, plugins, vacuum trend,
                 # leak_rate estimator (F13)
  core/          # safety FSM, scheduler, broker, alarms v2, interlocks,
                 # sensor_diagnostics, experiments, zmq_bridge
  drivers/       # LakeShore, Keithley, Thyracont, Etalon MultiLine + transports
  gui/           # MainWindowV2, dashboard, overlays
  notifications/ # Telegram alerts + interactive bot + escalation
  replay/        # historical-data replay + curve transforms
  replay_engine/ # ZMQ-compatible replay engine (accelerated playback)
  reporting/     # template-driven DOCX generator
  sinks/         # vault notes + webhook on experiment finalize
  storage/       # SQLite, Parquet, CSV, HDF5, XLSX,
                 # cold_rotation (F17), archive_reader (F17)
  tools/         # CLI utilities (cooldown_cli)
  utils/         # shared helpers
  web/           # FastAPI monitoring
tsp/             # Keithley TSP watchdog (cryodaq_wdog.lua; loaded per watchdog.mode)
tests/           # 3500 test functions across 324 files
config/          # YAML configuration
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

Run after `pip install -e ".[dev,web]"`. GUI tests require `PySide6` +
`pyqtgraph`. Some storage tests require `CRYODAQ_ALLOW_BROKEN_SQLITE=1` on
machines whose selected SQLite falls in `[3.7.0, 3.51.3)`, except the
backport-safe versions 3.44.6 and 3.50.7.

## Local Operator-Query Service

CryoDAQ runs a local text-generation service (current brand: Gemma, default
model gemma4:e4b via Ollama; downgraded to gemma4:e2b on low-VRAM dev
machines). No external APIs.

### What it does

Subscribes to engine events (alarms, phase transitions, finalize, sensor
anomalies, shift handovers). When an alarm fires or an experiment finalizes, it
generates a human-readable summary for the operator in:
- Telegram (the bot chat)
- Operator log
- GUI insight panel (an overlay in MainWindowV2)

It also generates diagnostic suggestions (alarms + sensor_anomaly_critical) and
intro paragraphs for campaign DOCX reports.

**Answers operator queries.** IntentClassifier determines intent, QueryRouter
routes the query to adapters: live data via BrokerSnapshot and semantic search
over the knowledge base (KNOWLEDGE_QUERY → RAG). Available from the embedded chat
in the "Knowledge base" overlay and via the Telegram bot.

### What it does NOT do

- Has no access to engine commands. Read-only data and text channels only.
- Does not modify state. Read-only.

### Configuration

See `config/agent.yaml`. Key parameters:
- `agent.enabled`: enable/disable the service
- `agent.brand_name`: the operator-facing name (can change when migrating to
  another model)
- `agent.ollama.default_model`: the Ollama model
- `agent.triggers.*`: which events activate the service
- `agent.rate_limit`: limits (60 calls/hour by default)

### Migrating to another model

1. `ollama pull <new_model>`
2. Edit `config/agent.yaml`:
   ```yaml
   agent:
     brand_name: "New name"
     brand_emoji: "🦉"
     ollama:
       default_model: <new_model>
   ```
3. Restart the engine
4. Smoke test: trigger an alarm in mock mode

No code changes.

### Architecture

Two lanes: a live observer (subscribes to engine events, emits summaries) and a
query router (classifies operator intent, routes to read-only adapters). See
`docs/architecture.md` for the system architecture.

### Audit log

Every model call is recorded under `data/agents/.../audit/<YYYY-MM-DD>/`.
Full context, prompt, response, tokens, latency, output targets. A verifiable
trail for post-hoc review.

## Known limitations

As of v0.64.0. The lab-only checks below are collected as a turnkey protocol in
`docs/lab_verification_checklist.md`.

- **SQLite WAL gate:** the engine hard-fails on startup on SQLite versions in the
  range `[3.7.0, 3.51.3)` (F25). Backport-safe: 3.44.6, 3.50.7 (pass without the
  variable). On Linux this self-heals: `storage/_sqlite.py` transparently falls
  back to the bundled `pysqlite3-binary` (a base dependency) when the linked
  SQLite is in-range, so the gate passes out of the box. Manual remediation
  (`CRYODAQ_ALLOW_BROKEN_SQLITE=1`, or a Python linked against a safe SQLite) is
  only needed if BOTH the stdlib and the fallback are unsafe/absent. macOS ships
  no pysqlite3 wheels; its stdlib is expected safe.
- **Lab Ubuntu PC verification:** the H5 ZMQ fix from v0.39.0 was verified only on
  macOS. Physical access to the lab PC is pending (see the checklist).
- **Engine shutdown warning:** one `Unclosed client session` ERROR can appear at
  engine shutdown because an `aiohttp` session is not closed on that exit path.
  This is cosmetic on shutdown; data and safety state are not affected.
- **PDF reports:** best-effort. The guaranteed artifact is DOCX.
- **Runtime calibration policy:** global on/off + per-channel KRDG/SRDG+curve. A
  conservative fallback to KRDG when a curve / SRDG is missing or a computation
  fails. Real LakeShore behavior requires lab verification.
- **Leak rate (F13):** `chamber.volume_l` must be set in
  `config/instruments.local.yaml` before the first measurement; `finalize()`
  raises `ValueError` when `volume_l == 0.0`.
- **Keithley host-death protection:** the TSP v3 script is intentionally
  non-autonomous and covers only a late pet after a host stall. `required` mode
  therefore refuses v3; `best_effort` logs a CRITICAL degraded warning and uses
  the late-pet check. No software status bit proves physical terminal OFF.
  Host-death removal of terminal energy and any external interlock remain lab
  gates measured with independent instruments.

## Contributor and developer-agent guidance

Repository-wide engineering and safety rules live in [`AGENTS.md`](AGENTS.md).
[`CLAUDE.md`](CLAUDE.md) is only a compatibility pointer; the detailed,
tool-neutral workflow is [`docs/ORCHESTRATION.md`](docs/ORCHESTRATION.md).
Historical prompts, handoffs, generated memory, and agent-run artifacts are not
current policy unless an active task explicitly selects them.

## License

See `LICENSE`. Third-party notices: `THIRD_PARTY_NOTICES.md`.
