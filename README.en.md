# CryoDAQ

Data acquisition, control, and analysis stack for a cryogenic laboratory.
Replaces a 3-year-old LabVIEW VI that drove the instruments and sent
email alerts. Adds: scripted FSM campaigns, automated calibration with
multi-format export, DOCX report auto-generation, role-based Telegram
alerts, sensor anomaly detection with alarm pipeline, plugin analytics,
local AI assistant (Гемма / Gemma), predictor-based physical alarms,
historical data replay, Etalon MultiLine interferometer integration,
regression test suite (~2,450+ tests).

Developed for ASC FIAN (Lebedev Physical Institute Astro Space Center,
Millimetron project).

## Status

- **Latest release:** v0.55.4 (2026-05-07, local tag)
- **In progress:** v0.55.5 (Telegram one-shot policy + Гемма quality)
- **Tests:** ~2,450+ passing
- **Production status:** stable; LabVIEW VI fully replaced
- **Languages:** GUI and logs in Russian; code, commit messages —
  English

## Architecture

Three runtime processes:

- `cryodaq-engine` — headless asyncio runtime. Drives instruments, runs
  the safety manager FSM, evaluates alarm rules and interlocks,
  persists data, serves GUI commands over ZMQ.
- `cryodaq-gui` — Qt desktop client. Connects via ZMQ; can restart
  without interrupting data acquisition.
- `cryodaq.web.server:app` — optional FastAPI monitoring dashboard.

Plus the Windows launcher: `cryodaq` (single-instance protected via
kernel-level lock).

Data flow:

```
Instrument → Driver → Scheduler → SQLiteWriter → DataBroker → {GUI, SafetyBroker,
                                                                Telegram, Analytics,
                                                                Sinks, RAG indexer}
```

**Persistence-first invariant:** SQLite write completes BEFORE the
broker publish — if the operator can see the data, it's already on
disk.

IPC: ZeroMQ PUB/SUB on `:5555` (msgpack) + REP/REQ on `:5556` (JSON
commands).

## Supported instruments

- 3× LakeShore 218S (GPIB) — 24 temperature channels; calibration
  curves, persistent sessions (LabVIEW-style open-once), GPIB
  auto-recovery with IFC reset
- Keithley 2604B (USB-TMC) — dual-channel SMU (`smua` + `smub`);
  P=const host-side loop, slew-rate limit, compliance detection,
  emergency_off latched
- Thyracont VSP63D (RS-232) — 1 pressure channel; V1 protocol,
  formula validation
- Etalon MultiLine (TCP/IP) — interferometric length measurement
  system (Stage 1 driver shipped in v0.54.0; GUI overlay in flight
  for v0.55.6)

The channel model is built around hardware-fixed landmarks:
**Т11** = 1st-stage GM-cooler (~40 K floor), **Т12** = 2nd stage
(~2.9 K floor). They are tagged `is_cold: true` and serve as
positionally-fixed references for the safety FSM, cooldown predictor,
and alarms. Other channels (Т1–Т8, Т13–Т24) are mobile between
experiments.

## Implemented workflows

- **Experiment FSM:** 6-phase lifecycle (preparation → vacuum →
  cooldown → measurement → warmup → teardown → idle, plus aborted).
  Templated scripted runs. Auto-advance phase + manual transition
  controls.
- **Calibration v2:** continuous SRDG capture during calibration
  experiments; post-run pipeline (extract → downsample → Chebyshev fit
  by zone); export to `.cof` (raw coefficients) / `.340` / JSON / CSV;
  import from `.340` / JSON; runtime application with global / per-
  channel policy.
- **Auto-generated reports:** template-driven sections; guaranteed
  `report_editable.docx` + `report_raw.pdf` (best-effort via
  `soffice` / LibreOffice). Гемма generates a Russian intro paragraph.
- **Telegram alerts + interactive bot:** role-based filtering. Commands:
  `/log`, `/phase`, `/temps`, `/chart`, `/ask <query>`, free-text
  queries. Composition photos (F27): the operator sends a photo, the
  bot uses an inline keyboard to confirm which experiment to attach to.
- **Sensor diagnostics → alarm pipeline:** MAD-outlier + cross-channel
  correlation drift detection. Sustained anomaly publishes an alarm:
  warning at 5 min, critical at 15 min, auto-clear on recovery.
  Concurrent events are aggregated into a single Telegram message;
  cold-start grace period; per-channel escalation cooldown.
- **Alarm engine v2:** YAML-driven threshold / rate / composite /
  phase-dependent rules; hysteresis deadband; in-place severity upgrade
  (WARNING→CRITICAL); ack/clear publish path.
- **Physical alarms (F-X v3):** predictor-based trajectory deviation —
  `CooldownAlarm` uses the ensemble cooldown predictor to detect when
  the trajectory falls behind expected. Auto-arms on cooldown phase,
  gated by `SteadyStatePredictor` quasi-steady detection.
  `VacuumGuard` — fully automatic P × T_ref alarm (P > 1e-2 mbar
  while T_ref < 260 K).
- **Interlocks:** hardware safety (cryostat / compressor / detector).
  Trip → `emergency_off` + transition to TRIPPED. Operator
  acknowledges via the `interlock_acknowledge` ZMQ command without a
  process restart.
- **Operator log:** SQLite-backed; Telegram + GUI + ZMQ interfaces.
  Shifts (`ShiftBar`) with start, periodic 2-hour check-ins, and
  end-of-shift handover.
- **Experiment templates, lifecycle metadata, artifact archive:** the
  `data/experiments/<id>/` directory with `metadata.json`, `reports/`,
  `composition/` (photos), `readings.parquet` (Parquet snapshot).
- **Plugin architecture:** ABC-isolated; callback failures mark a
  plugin degraded without crashing the engine.
- **Housekeeping:** adaptive throttle + retention + compression.
- **Cold-storage rotation (F17):** daily SQLite files older than 30
  days auto-rotate to Parquet/Zstd. `ArchiveReader` reads both sources
  transparently by UTC day.
- **Vacuum trend predictor:** 3 pump-down models (exp/power/combined),
  BIC model selection, ETA. Leak rate estimation via
  `LeakRateEstimator` — sliding window, OLS regression without numpy.
- **Cooldown predictor:** ensemble model over reference curves,
  dual-channel progress variable, rate-adaptive weighting, LOO
  validation, quality-gated ingest. Quasi-steady regime detection via
  residual + slope gate.
- **Replay mode (F-Replay):** playback of historical SQLite, Parquet,
  or curve JSON. Replay engine with PUB+REP+heartbeat parity.
  CooldownService runs over the replay stream, so the predictor widget
  activates on historical curves. Legacy channel maps for thermal-
  bridge era data.
- **Sinks (F31):** experiment finalize fan-out — `VaultSink` writes a
  Markdown + frontmatter note to a filesystem vault, `WebhookSink`
  POSTs JSON to a configured URL. Fire-and-forget, failures captured
  via the `sinks_status` ZMQ command.
- **RAG indexer (F32 Stage 1):** standalone semantic search over the
  experiment archive, vault notes, operator log. LanceDB persistence,
  multilingual-e5-small embeddings via Ollama. CLI:
  `cryodaq-rag-index`, `cryodaq-rag-search`. Stage 2 (integration into
  QueryAgent) lands in v0.55.6.

## GUI

`MainWindowV2` — phase-aware dashboard for week-long experiments
(operators see only v2; legacy `MainWindow` was removed in v0.34.0
Phase II.13).

Layout — ambient information radiator:

- **TopWatchBar** — engine status, experiment, pressure, T_min / T_max
  (computed only over cold channels), per-channel ok/waiting counter,
  active alarm counter.
- **ToolRail** — overlay-panel navigation (Phosphor icon set).
- **DashboardView** — 5 live zones: DynamicSensorGrid, multi-channel
  temperature plot with TimeWindowSelector (1m/1h/6h/24h/All), compact
  log-Y pressure plot, PhaseAwareWidget with phase-specific content,
  QuickLogBlock.
- **BottomStatusBar** — safety state indicator.
- **OverlayContainer** — lazily-initialized overlays.

Overlay panels:

- **Аналитика** (Analytics, phase-aware): cooldown trajectory + ETA +
  CI band (F-P1), vacuum leak projection (F-P2), thermal conductivity
  asymptote (F-P3). W3 experiment summary with per-channel min/max/mean
  + top-3 alarms.
- **Архив** (Archive) — past experiments + reports + Parquet exports,
  composition photo gallery, bulk export CSV/HDF5/Excel.
- **Калибровка** (Calibration) — Setup → Acquisition → Results, `.cof`
  import/export, runtime apply.
- **Тревоги** (Alarms, renamed from «Алармы» in v0.55.4) — dual-engine
  (v1 threshold + v2 YAML-driven), SeverityChip with status tokens
  (КРИТ/ПРЕД/ИНФО), acknowledge button, "Контроль захолаживания"
  footer for CooldownAlarm.
- **Помощник Гемма** (Гемма Assistant, F34, v0.54.0) — chat overlay
  for free-form queries to the QueryAgent.
- **Оператор-лог** (Operator log), **Приборы** (Instruments — cards +
  sensor diagnostics), **Источник мощности** (Power source —
  Keithley smua/smub), **Теплопроводность** (Thermal conductivity —
  autosweep + R/G).

12 bundled themes (6 dark + 6 light); status palette is hue-locked
across all themes. Runtime theme switcher via the «Настройки → Тема»
(Settings → Theme) menu.

## Installation

### Requirements

- Windows 10/11 / Linux (Ubuntu 22.04 deployment target) / macOS (dev)
- Python `>=3.12`
- Git
- VISA backend / instrument drivers as needed
- Ollama + `gemma4:e2b` or `gemma4:e4b` (for the AI assistant; optional)

### Install

```bash
pip install -e ".[dev,web]"
# Or with archive extras:
pip install -e ".[dev,web,archive]"
```

Supported workflow: install from the repository root into an active
venv. Running `pytest` without `pip install -e ...` is unsupported.

Key runtime dependencies: `PySide6`, `pyqtgraph`, `pyvisa`,
`pyserial-asyncio`, `pyzmq`, `python-docx`, `scipy`, `matplotlib`,
`openpyxl`, `pyarrow`, `lancedb` (for RAG).

## Run

```bash
cryodaq                    # Launcher: engine + GUI + tray, auto-restart
cryodaq-engine             # Headless engine (real instruments)
cryodaq-engine --mock      # Mock mode (simulated instruments)
cryodaq-engine --force     # Kill old engine + start (lock override)
cryodaq-engine --replay <path>     # Replay mode
cryodaq-gui                # GUI only (connects to a running engine)
cryodaq-cooldown build|predict|validate|demo|update    # Predictor CLI
cryodaq-rag-index | cryodaq-rag-search                 # RAG CLI
uvicorn cryodaq.web.server:app --host 127.0.0.1 --port 8080  # Web (opt.)
```

## Configuration

Active configuration files:

- `config/instruments.yaml` — GPIB/serial/USB/TCP addresses, LakeShore
  channels, `chamber.volume_l` for leak rate, MultiLine host
- `config/instruments.local.yaml` — machine-specific overrides
  (gitignored)
- `config/safety.yaml` — FSM timeouts, rate limits, drain timeout,
  `critical_channels` (Т11/Т12 only after v0.55.4)
- `config/alarms_v3.yaml` — alarm engine v2 rules; the `notify:` field
  drives dispatch (gui/telegram/sound)
- `config/interlocks.yaml` — interlock conditions + actions
- `config/physical_alarms.yaml` — CooldownAlarm + VacuumGuard
  tunables; `landmarks:` section (F-ChannelLandmarks)
- `config/channels.yaml` — display names, visibility, `is_cold` flag
- `config/notifications.yaml` — Telegram bot_token, chat_ids,
  escalation
- `config/cooldown.yaml` — cooldown predictor parameters + steady_state
  sub-block (v0.55.3)
- `config/agent.yaml` — Гемма (AssistantLiveAgent +
  AssistantQueryAgent): triggers, brand, Ollama model, rate limit,
  query enabled
- `config/sinks.yaml` — F31 vault writer + webhook
- `config/rag.yaml` — F32 RAG indexer
- `config/themes/<name>.yaml` — bundled theme packs
- `config/experiment_templates/*.yaml` — experiment-type templates
- `config/housekeeping.yaml` — throttle, retention, compression,
  cold_rotation
- `config/plugins.yaml` — sensor_diagnostics + vacuum_trend
- `config/shifts.yaml` — shift definitions (GUI)

`*.local.yaml` files override the base files for machine-specific
settings.

## Experiment artifacts

```text
data/experiments/<experiment_id>/
  metadata.json                  # phases, sample, operator, status
  readings.parquet               # snapshot of all readings (Stage 1)
  reports/
    report_editable.docx
    report_raw.pdf               # opt., best-effort
    report_raw.docx
    assets/                      # plots
  composition/                   # operator-supplied photos (F27)
data/calibration/sessions/<session_id>/
data/calibration/curves/<sensor_id>/<curve_id>/
data/archive/year=YYYY/month=MM/   # Parquet cold storage (F17)
data/leak_rate_history.json        # leak measurement history (F13)
data/cooldown_model/               # ensemble predictor model
data/agents/assistant/audit/       # LLM call audit log per day
```

## Local AI assistant

CryoDAQ ships a local AI agent (brand: **Гемма** / Gemma, model
`gemma4:e2b` via Ollama). No external APIs.

### What it does

**Live agent** (`AssistantLiveAgent`) subscribes to engine events
(alarms, phase transitions, finalize, sensor anomalies, shift
handovers). When an alarm fires or an experiment finalizes, it
generates a human-readable summary for the operator in Telegram,
operator log, and the GUI insight panel. It also generates diagnostic
suggestions and intro paragraphs for DOCX campaign reports.

**Query agent** (`AssistantQueryAgent`) handles free-form queries:

- Via Telegram (`/ask` or free-text)
- Via the GUI chat overlay (F34, "Помощник Гемма")
- Categories: current value, ETA cooldown, ETA vacuum, range stats,
  phase info, alarm status, composite status, archive list/detail,
  alarm history.

**Periodic reports** (F29) — hourly narrative summary of engine
activity (skip-if-idle filter).

### What it does NOT do

- It has no access to engine commands. Text channels only.
- It does not modify state. Read-only.
- It does not answer out-of-scope queries.

### Configuration

See `config/agent.yaml`. Key parameters:

- `agent.enabled` — agent on/off
- `agent.brand_name`, `agent.brand_emoji` — operator-facing identity
- `agent.ollama.default_model` — Ollama model
- `agent.triggers.*` — events that activate the live agent
- `agent.query.enabled` — enable the query agent
- `agent.rate_limit` — limits (60 calls/hour by default)

### Audit log

Every LLM call is recorded in
`data/agents/assistant/audit/<YYYY-MM-DD>/`. Full context, prompt,
response, tokens, latency, output targets — a verifiable trail for
post-hoc review.

## Project layout

```text
src/cryodaq/
  agents/        # AssistantLiveAgent + AssistantQueryAgent + RAG
  analytics/     # calibration fitter, cooldown predictor, plugins,
                 # vacuum trend, leak_rate, steady_state
  core/          # safety FSM, scheduler, broker, alarms v2, cooldown_alarm,
                 # vacuum_guard, interlocks, sensor_diagnostics, experiments
  drivers/       # LakeShore, Keithley, Thyracont, MultiLine + transports
  gui/           # MainWindowV2, dashboard, shell, overlays
  notifications/ # Telegram bot + commands + periodic reports + escalation
  replay_engine/ # F-Replay standalone replay PUB+REP+heartbeat
  reporting/     # template-driven DOCX generator
  sinks/         # F31 VaultSink, WebhookSink
  storage/       # SQLite, Parquet, CSV, HDF5, XLSX, cold_rotation
  web/           # FastAPI monitoring
  tools/         # CLI: cooldown, replay alarm history
tsp/             # Keithley TSP scripts (draft)
tests/           # ~2,450+ tests
config/          # YAML configurations
docs/            # design system, decisions, operator manual
```

## Tests

```bash
pytest                                    # Full suite
pytest -m 'not ollama'                    # Without live Ollama smoke
pytest tests/core -q
pytest tests/agents -q
pytest tests/gui/shell/overlays -q
ruff check src/ tests/
ruff format src/ tests/
```

GUI tests require `PySide6` + `pyqtgraph`. Some storage tests require
`CRYODAQ_ALLOW_BROKEN_SQLITE=1` on machines with SQLite < 3.51.3
(except backport-safe versions 3.44.6 and 3.50.7).

## Known limitations

- **SQLite WAL gate (F25):** the engine refuses to start on SQLite
  versions in `[3.7.0, 3.51.3)`. Backport-safe: 3.44.6, 3.50.7.
  Workaround: `CRYODAQ_ALLOW_BROKEN_SQLITE=1` (logs a warning).
- **Push gate:** ~25 local tags v0.51.0..v0.55.4 are not pushed to
  origin/master (master lags behind). Resolution requires architecture
  review; work continues on feature branches.
- **PDF reports:** best-effort via `soffice`/LibreOffice. The
  guaranteed artifact is DOCX.
- **MultiLine GUI:** Stage 1 driver shipped in v0.54.0, the GUI
  overlay is in flight for v0.55.6. Channel data is already published
  to the broker.
- **Lab Ubuntu PC:** last physical smoke 2026-04-20. Next planned for
  the 2026-05-14 contest release verification.
- **Deprecation warnings:** `asyncio.WindowsSelectorEventLoopPolicy`
  on Python 3.14+.
- **Leak rate (F13):** `chamber.volume_l` is required in
  `config/instruments.local.yaml`; `finalize()` raises `ValueError`
  when `volume_l == 0.0`.

## Documentation

- `CHANGELOG.md` — full release history
- `CLAUDE.md` — architectural contract + development rules
- `docs/operator_manual.md` — operator manual (Russian)
- `docs/design-system/MASTER.md` — design system v1.0.1
- `docs/decisions/` — ADRs (architecture decision records)
- `docs/deployment.md`, `docs/first_deployment.md` — deployment

## License

See `LICENSE`. Third-party notices: `THIRD_PARTY_NOTICES.md`.

---

*Русская версия: см. [README.md](README.md).*
