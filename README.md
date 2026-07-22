**English** · [Русский](README.ru.md)

# CryoDAQ

Data acquisition, control, and analysis stack for a cryogenics laboratory.
Replaces a 3-year-old LabVIEW VI that drove the instruments and sent email alerts.
Adds: scripted FSM campaigns, automated calibration with multi-format export,
auto-generated DOCX reports, role-based Telegram alerts, sensor anomaly detection
with an alarm pipeline, plugin analytics, a local operator-query layer with a
knowledge base (RAG), historical-data replay mode,
interferometric length metrology (Etalon MultiLine), and a large cross-platform
regression test suite.

Built for ASC LPI (the Millimetron project).

## Status

- **Latest release:** v0.64.1 (2026-07-08)
- **Released baseline:** the latest locally available release tag is `v0.64.1`
  (2026-07-08).
- **Active candidate:** `feat/montana-phase-a` is a large, unreleased
  software-side laboratory-readiness refactor. It is not accepted merely because
  its mock tests or CI pass.
- **Evidence boundary:** physical instrument, dummy-load, independent final-element,
  and laboratory acceptance gates remain open until the procedures in
  [`docs/lab_verification_checklist.md`](docs/lab_verification_checklist.md) are
  executed and recorded.
- **Current truth:** see [`PROJECT_STATUS.md`](PROJECT_STATUS.md). A working
  before/after narrative, metrics, design decisions, and architecture maps are
  in [`docs/MONTANA_REFACTOR_REPORT.md`](docs/MONTANA_REFACTOR_REPORT.md); the
  status document defines the current acceptance boundary.

## Montana refactor: what changed

Montana is the unreleased laboratory-readiness refactor on
`feat/montana-phase-a`. It is moving CryoDAQ toward narrower ownership, explicit
evidence, and visible failure boundaries while preserving the information-dense
operator workflow. Several boundaries remain open below, so this is a design
direction and partially implemented candidate, not an accepted system property.

The most important changes are:

- **Narrower ownership, with an open exception.** Acquisition, safety state,
  recording, periodic delivery, archive rotation, and operator snapshots have
  explicit owners. The current assistant still instantiates a second
  `SQLiteWriter` for operator-log output, so the one-writer boundary is not yet
  complete.
- **Persistence before ordinary data publication.** In the production
  acquisition path, the archive-selected batch commits before `DataBroker`
  publication. `SafetyBroker` separately receives the full raw batch for safety
  evaluation after the archive-selection/persistence branch; adaptive-throttle
  omissions and synthetic broker events are not claimed to be durably stored.
- **Fail-closed hazardous output.** Source authority is capability-gated.
  Verified OFF, emergency shutdown, interlocks, and bounded process cleanup were
  strengthened; passive extension mechanisms cannot acquire actuator authority.
- **Descriptor-qualified channel identity.** Canonical descriptors are carried
  through acquisition, SQLite, cold archive, replay, reports, and GUI paths.
  Startup validation of every safety/alarm/interlock pattern against that
  authority is still temporarily fail-open and remains an acceptance gate.
- **Process isolation and recovery.** The launcher supervises the engine, GUI
  bridge, assistant, and bounded report children with explicit lifecycle
  machinery. The assistant is process-isolated but does not yet satisfy the
  repository's strict observational boundary because it still holds delivery
  credentials and mutation/write paths.
- **Periodic reporting without control authority.** Rendering and delivery are
  observational. Durable state and receipts distinguish rendering, delivery,
  acknowledgement, ambiguity, retry, and terminal success across crashes.
- **Operator-centred GUI governance.** The panoramic dashboard remains primary
  and summaries are additive. The design contract requires current values,
  stale/disconnected state, provenance, active hazards, and acknowledgement
  state to remain reachable; shared freshness/provenance/lifecycle wiring and
  operator-scenario acceptance are still open.
- **Reproducible evidence.** CI is split across Windows and Ubuntu; installer and
  runtime SQLite policy share a tested contract; Windows ONEDIR and Linux soak
  procedures bind evidence to exact commits. Mock evidence never claims to be
  physical-hardware evidence.

Montana is large, but its governing idea is simple: make authority narrow,
state explicit, failure visible, and every acceptance claim traceable to the
environment that actually produced it.

### Current acceptance boundary

Historical checkpoint: commit
`503c8bf8d884654256ede4f08a9e44ab7b382242` is associated with reported
eight-job GitHub Actions run `29662599972`. That evidence covers only that
commit. The current working tree is large and dirty and has no immutable
candidate SHA or covering CI result; current remote and pull-request state must
be checked on GitHub.

The latest review of the local SafetyManager shutdown/HOLD work is **REJECTED**:
settlement tasks are not yet bounded and one terminal safety-child outcome can
be consumed again. Local passing tests do not override that finding; the slice
must be corrected, re-frozen, re-tested, and pass both mandatory reviews.

The remaining software work is explicit: quarantine USBTMC after ambiguous
exchanges; seal and validate safety configuration transactionally; bind safety
patterns to exact channel descriptors; coalesce shutdown-HOLD settlement and
contain monitor/writer death; preserve operator-log identity through hot/cold
rotation, REST, replay, reports, and the assistant; remove write ownership and
mutation credentials from the observational assistant; finish shared GUI
freshness/provenance/lifecycle truth; decide conductivity freshness behavior;
and reconcile protocol, architecture, report metrics, and SVG maps. The
Keithley/transport focused checks must be rerun and recorded against the eventual
frozen candidate; no moving-worktree result closes physical gates.

After those engineering gates close, one frozen commit must still pass native
Windows and WSL partitions, lock/static/package/source-install checks, the
sealed short soak, Windows ONEDIR, fresh eight-job hosted CI, a fresh-context
review, and the coordinating agent's separate line-by-line review. External
model review is additive, not a prerequisite for opening the PR. Physical
instrument, dummy-load, host-death, independent final-element, long-duration
soak, and laboratory operator acceptance remain separate and open until their
prescribed evidence is recorded. The future 100+ sensor / 4K projector and
semantic-zoom view is deferred and does not block ordinary lab readiness.

## Interview guide for another agent

Use this section when an agent must interview a maintainer, reviewer, operator,
or cryogenic engineer about CryoDAQ. Start with plain operational questions;
only then descend into modules and protocols. Do not use internal campaign
labels as substitutes for explaining behavior.

### Copy-paste assignment for the interviewing agent

> Interview the CryoDAQ maintainer and laboratory stakeholders to produce a
> factual, operator-centred account of the system and the Montana refactor.
> Establish the real experiment workflow first, then trace authority, data,
> failure recovery, GUI truth, and acceptance evidence. Separate released
> behavior, Montana candidate behavior, planned work, and physical claims that
> remain unverified. Challenge vague answers with concrete scenarios and ask
> for the owning process, persisted record, operator-visible state, relevant
> source or test, and exact evidence for every important claim. Do not treat CI,
> simulation, mocks, screenshots, or documentation as proof of hardware
> behavior. Do not recommend weakening fail-closed behavior or hiding operator
> information to simplify the design. End with: (1) a plain-language system
> summary; (2) a before/Montana comparison; (3) an authority and data-flow map;
> (4) unresolved safety and operability questions; (5) open software, Windows,
> WSL, packaging, dummy-load, and physical-lab gates; and (6) contradictions
> between interviews, code, tests, and documentation.

Interview people separately where practical. Operators describe actual work and
failure visibility; cryogenic engineers describe the apparatus and hazards;
maintainers describe implementation and ownership; reviewers challenge the
evidence. Record who supplied each operational claim, but do not put private
personal data or raw private transcripts in the repository.

Read these sources first, in order:

1. This README for the product and Montana overview.
2. [`PROJECT_STATUS.md`](PROJECT_STATUS.md) for the exact current evidence and
   open gates.
3. [`docs/MONTANA_REFACTOR_REPORT.md`](docs/MONTANA_REFACTOR_REPORT.md) for the
   full before/after narrative, metrics, decisions, and architecture diagrams.
4. [`docs/architecture.md`](docs/architecture.md) for runtime ownership and data
   flow.
5. [`docs/lab_verification_checklist.md`](docs/lab_verification_checklist.md) for
   what software tests cannot prove.
6. [`docs/design-system/README.md`](docs/design-system/README.md) before asking
   about GUI changes.

Recommended interview questions:

### Product and laboratory workflow

- What experiment does CryoDAQ support from preparation through cooldown,
  measurement, warmup, reporting, and archive?
- Which information must an operator see continuously, and which information is
  acceptable in an overlay or drill-down?
- What did the old LabVIEW workflow do well, and which operational habits must
  CryoDAQ preserve?
- Which failures have actually occurred in the lab, and which are currently only
  anticipated by tests or hazard analysis?

### Authority and safety

- Which process owns instruments and safety state? What happens if the GUI,
  assistant, report renderer, or launcher dies?
- What evidence is required before the software may say a hazardous source is
  OFF? What happens when OFF readback is unavailable or contradictory?
- How do alarm acknowledgement, alarm clearing, safety recovery, and interlock
  reset differ? Which of them can change physical authority?
- Why can a passive driver plugin never become a source driver through duck
  typing or configuration alone?
- Which physical claims remain impossible to close with mocks, CI, replay, or a
  screenshot?

### Data truth and persistence

- Where is the persistence-before-publication order enforced?
- What is the canonical identity of a channel, and how does it survive hot
  SQLite data, cold Parquet rotation, replay, reports, and GUI display?
- How are partial writes, storage backpressure, corrupt metadata, archive races,
  and cancellation represented without creating a second writer?
- What does the GUI show when a reading is stale, disconnected, unavailable, or
  from a different timestamp than a comparison channel?

### Processes, reports, and recovery

- Which long-running and ephemeral processes exist, who starts them, and who is
  responsible for reaping their descendants?
- How does CryoDAQ distinguish a rendered periodic report from a durably
  delivered and acknowledged one?
- What prevents a restarted assistant from duplicating delivery or accepting an
  old owner token, slot, process identity, or acknowledgement?
- How are blocking LibreOffice/report operations kept off the engine loop, and
  what useful artifact remains when PDF conversion times out?

### GUI and operator experience

- Why is the panoramic dashboard still primary, and why must a summary display
  remain additive?
- Which colors are reserved for safety meaning, and how are state differences
  communicated without color alone?
- What becomes better and what becomes worse for the operator with each proposed
  GUI change?
- Can any responsive breakpoint, clipping rule, filter, acknowledgement, or
  auto-ranging choice hide current value, status, provenance, or an active
  hazard?
- How should the future 100+ sensor / 4K projector view aggregate information
  without turning the application into a black box?

### Verification and release honesty

- Which exact commit, operating system, Python, SQLite, dependency lock, and
  artifact hashes produced the claimed result?
- Did the test exercise real loopback/process/filesystem behavior, or was the
  property mocked away?
- What do the Windows ONEDIR, WSL short soak, hosted CI, long soak, dummy-load,
  and physical-lab gates each prove—and explicitly not prove?
- What evidence would make you reject the candidate even if every unit test were
  green?

Ask for concrete examples, file paths, state transitions, and evidence records.
An answer such as “the tests pass” is incomplete unless it identifies the exact
candidate, environment, gate, pass/skip counts, and the claims that remain open.

## Architecture

CryoDAQ exposes four primary operator deployment surfaces/modes:

- `cryodaq` — the full cross-platform operator launcher. Its process hosts the
  Qt GUI and supervises the engine, GUI bridge, and optional assistant candidate.
  Bounded report children are owned by the engine or assistant
  component that requested them, not directly by the launcher.
- `cryodaq-engine` — the standalone headless asyncio runtime. It drives the
  instruments, runs the safety-manager FSM, evaluates alarm rules and
  interlocks, persists data, and serves GUI commands over ZMQ.
- `cryodaq-gui` — a reduced standalone Qt client for an already-running engine.
  It can restart without stopping data acquisition. A standalone engine still
  supports on-demand reports; this reduced path does not provide the launcher's
  assistant/periodic-delivery lifecycle.
- `cryodaq.web.server:app` — the optional FastAPI monitoring dashboard.

Only the engine owns instruments and safety authority. Report workers have no
control authority. The assistant is intended to be observational, but its
current second operator-log writer, RAG mutation path, and Telegram credential
must be removed or reassigned before that boundary is complete. GUI paths remain
clients of backend truth rather than control owners.

Data flow:

```
Instrument → allowlisted Driver/Capability → Scheduler
           → SQLiteWriter (archive-selected batch)
           → DataBroker → {GUI, alarms, analytics}
           ↘ SafetyBroker (full raw batch; safety path)
```

IPC: ZeroMQ PUB/SUB `:5555` (msgpack) + REP/REQ `:5556` (JSON commands).

## Supported instruments

- 3× LakeShore 218S (GPIB) — 24 temperature channels
- Keithley 2604B (USB-TMC) — dual-channel SMU (`smua` + `smub`)
- Thyracont VSP63D (RS-232) — 1 pressure channel
- Etalon MultiLine (TCP/IP) — interferometric length metrology; averaged and
  continuous modes, vibration burst capture to Parquet

## Implemented workflows

The list below describes the active tree: released v0.64.1 workflows together
with explicitly unreleased Montana candidate behavior. Candidate defaults and
hardening are not release or physical-acceptance claims; see **Status** above.

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
- **Experiment FSM:** six canonical phases: preparation → vacuum → cooldown →
  measurement → warmup → teardown. Abort/fault is an outcome or state, not a
  seventh experiment phase. Templated scripted runs.
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
  false SAFE_OFF. `config/physical_alarms.yaml` explicitly sets
  `vacuum.escalate_to_safety: true`; the built-in missing-file default is
  alarm-only (`false`), while invalid existing configuration fails safer to
  `true`.
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
- **SQLite fail-closed runtime:** all runtime DB connections go through
  `storage/_sqlite.py`. The supported Windows/Linux environment pins a safe
  SQLite version; an unsafe selected implementation blocks startup.
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

The launcher tray is deliberately coarse. With current wiring, a known safety
fault can produce red; alarm count remains unknown, so alarms alone cannot drive
red and green is unreachable. All other connected/disconnected/unknown,
stale-data, or reporting-fault cases resolve to the amber caution shape. Shape
and Russian tooltip duplicate color. The tray is not an authoritative alarm or
readiness summary and must not replace the dashboard or alarm surface.

## Installation

### Requirements

- Windows 10/11 or Linux
- Python `>=3.12` (must link SQLite `>=3.51.3`, or a backport-safe 3.44.6 / 3.50.7
  — see "Known limitations")
- Git
- A VISA backend / instrument drivers as needed

### Install

```bash
conda env create --file environment.yml
conda activate cryodaq
pip install -r requirements-lock.txt
pip install -e . --no-deps --no-build-isolation
pip check
```

The lock includes the PEP 517 build-backend closure. The supported path disables
a second runtime or build resolver when installing the project itself.

The tracked environment pins the supported Python/SQLite runtime. The pip lock
pins resolved Python package versions but is not a hashed, bit-for-bit artifact
lock. A bare editable extras install is a developer convenience only and is
supported only inside an independently verified safe SQLite runtime:

```bash
pip install -e ".[dev,web]"
```

Supported workflow: install from the repository root into the active `cryodaq`
environment.
Running `pytest` without `pip install -e ...` is not supported.

Key runtime dependencies: `PySide6`, `pyqtgraph`, `pyvisa`, `pyserial-asyncio`,
`pyzmq`, `python-docx`, `scipy`, `matplotlib`, `openpyxl`, `pyarrow`.

## Running

```bash
cryodaq-engine        # headless engine (real instruments)
cryodaq-gui           # GUI only (connects to a running engine)
cryodaq               # full cross-platform operator launcher
cryodaq-engine --mock # mock mode (simulated instruments)
uvicorn cryodaq.web.server:app --host 127.0.0.1 --port 8080  # optional web (loopback)
```

The web dashboard's GET surface has no authentication — bind it to `127.0.0.1`
only; public access requires a reverse proxy with authorization (or an SSH
tunnel). The two `/api/v1` write endpoints (`POST /log`, `POST /alarms/{id}/ack`)
require a bearer token from the gitignored `config/web.local.yaml`.

`POST /api/v1/log` may include the exact `experiment_id`; if it is omitted the
entry is explicitly `experiment_unbound` and is never attached implicitly to
the current experiment. The server owns author/source and creates one
32-character lowercase hexadecimal `request_id` per request. Public live
readings encode `NaN` and infinities as JSON `null` while retaining their
identity and status, so unavailable data cannot masquerade as a valid number.

Helper CLIs:

```bash
cryodaq-cooldown build --help    # cooldown ML: training options
cryodaq-cooldown predict --help  # cooldown ML: ETA-prediction options
cryodaq-trends scan --help       # cross-experiment feature-table options
cryodaq-trends drift --help      # cross-experiment drift-check options
cryodaq-replay-curve             # curve transforms for replay
cryodaq-rag-index                # build the knowledge-base index
cryodaq-rag-search               # semantic search over the knowledge base
```

## Configuration

Active configuration files in the Montana candidate:

- `config/instruments.yaml` — GPIB/serial/USB addresses, LakeShore channels,
  `chamber.volume_l` for the F13 leak rate
- `config/instruments.local.yaml.example` — template for machine-specific
  instrument overrides (`instruments.local.yaml` is gitignored)
- `config/channel_descriptors.yaml` — complete canonical descriptor/binding
  authority for every acquired channel
- `config/channel_descriptors.local.yaml.example` — machine-specific *whole-file
  replacement*, never a partial merge; reconcile it with the physical roster
  before real-hardware use
- `config/safety.yaml` — FSM timeouts, rate limits, drain timeout
- `config/alarms_v3.yaml` — alarm engine rules (threshold/rate/composite/phase)
- `config/interlocks.yaml` — interlock conditions + actions
- `config/physical_alarms.yaml` — tunables for the cold-cryostat physical
  guards; its tracked `vacuum.escalate_to_safety` value is `true`, while the
  built-in missing-file default is alarm-only (`false`)
- `config/channels.yaml` — display names, visibility, grouping
- `config/notifications.yaml` — tracked placeholder/schema; real credentials
  belong only in gitignored `config/notifications.local.yaml`. Engine and
  periodic loaders prefer the local file, but the current assistant Telegram
  sender still reads only the tracked base file; that candidate wiring is open.
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

Most `*.local.yaml` files override base settings. Channel descriptors are the
deliberate exception and are selected as a pair with the instrument authority:
when `instruments.local.yaml` is selected, `channel_descriptors.local.yaml` is
required and completely replaces the base manifest; with base
`instruments.yaml`, the base descriptor manifest is used even if a local
descriptor file happens to exist. Manifest/schema errors, ambiguous bindings, a
missing required local manifest, and instrument-set mismatch block startup.
Each accepted reading must then resolve exactly one
`(instrument_id, emitted_channel)` binding to a stable `channel_id`; an
undeclared emitted channel is rejected when it is first bound. A descriptor
grants identity only, never hazardous-source capability.

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
tests/           # cross-platform unit, integration, GUI, process, and evidence tests
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

Run after the supported installation above. GUI tests require `PySide6` +
`pyqtgraph`. Do not use `CRYODAQ_ALLOW_BROKEN_SQLITE=1` to claim storage-test or
deployment evidence; an unsafe runtime must be replaced.

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

These limitations apply at the current v0.64.1/Montana candidate boundary. The
software and laboratory checks are collected as a turnkey protocol in
`docs/lab_verification_checklist.md`.

- **SQLite WAL gate:** the engine hard-fails on startup on SQLite versions in the
  range `[3.7.0, 3.51.3)` (F25). Backport-safe: 3.44.6, 3.50.7 (pass without the
  variable). The supported Windows/Linux installation uses `environment.yml`
  to pin a safe SQLite version. No fallback package is installed by default;
  an unsafe or absent implementation remains a startup failure. The bypass is
  emergency acknowledgement only and is not acceptable deployment evidence.
- **Lab Ubuntu PC verification:** CI and WSL exercise the H5 ZMQ idle-death
  contract, but they do not close the physical laboratory-Ubuntu gate. Run and
  record the checklist procedure on the actual lab PC.
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
[`CLAUDE.md`](CLAUDE.md) contains subordinate ecosystem-specific convenience
guidance; it cannot override `AGENTS.md` or the detailed, tool-neutral workflow
in [`docs/ORCHESTRATION.md`](docs/ORCHESTRATION.md).
Historical prompts, handoffs, generated memory, and agent-run artifacts are not
current policy unless an active task explicitly selects them.

## License

See `LICENSE`. Third-party notices: `THIRD_PARTY_NOTICES.md`.
