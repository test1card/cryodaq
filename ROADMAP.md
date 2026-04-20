# CryoDAQ — Feature Roadmap

> **Living document.** Updated 2026-04-20 after IV.2 close (HEAD `df43081`).
> Companion to `PROJECT_STATUS.md` (infrastructure state) and
> `docs/phase-ui-1/phase_ui_v2_roadmap.md` (UI rebuild phases).
>
> **Scope:** forward-looking **feature work** (new code, new capabilities).
> NOT review / bugfix backlog — those live in batch specs
> (`CC_PROMPT_IV_*_BATCH.md`).

---

## Status key

- ✅ **DONE** — shipped and working
- 🔧 **PARTIAL** — code exists, missing wiring / UI / tests
- ⬜ **NOT STARTED** — spec only
- 🔬 **RESEARCH** — requires physics / methodology work before code

---

## Quick index

| # | Feature | Status | Effort | ROI |
|---|---|---|---|---|
| F1 | Parquet archive wire-up | ✅ DONE (UI + base dep, IV.4.F1) | S | H |
| F2 | Debug mode toggle (verbose logging) | ✅ DONE (IV.4.F2) | S | H |
| F3 | Analytics placeholder widgets → data wiring | ⬜ | M | M |
| F4 | Analytics lazy-open snapshot replay | ⬜ | S | M |
| F5 | Engine events → Hermes webhook | ⬜ | M | M |
| F6 | Auto-report on experiment finalize | ✅ DONE (verified + per-experiment override, IV.4.F6) | S | H |
| F7 | Web API readings query extension | ⬜ | L | M |
| F8 | Cooldown ML prediction upgrade | 🔬 | L | M |
| F9 | Thermal conductivity auto-report (TIM) | 🔬 | M | H |
| F10 | Sensor diagnostics → alarm integration | ⬜ | M | M |
| F11 | Shift handover enrichment | ✅ DONE (IV.4.F11, Telegram export deferred) | S | H |
| F12 | Experiment templates UI editor | ⬜ | M | L |
| F13 | Vacuum leak rate estimator | ⬜ | M | M |
| F14 | Remote command approval (Telegram) | ⬜ | M | L |
| F15 | Linux AppImage / .deb package | ⬜ | L | L |
| F16 | Plugin hot-reload SDK + examples | ⬜ | M | L |
| F17 | SQLite → Parquet cold-storage rotation | ⬜ | M | M |
| F18 | CI/CD upgrade (coverage, matrix, releases) | ⬜ | M | L |

Effort: **S** ≤200 LOC, **M** 200-600 LOC, **L** >600 LOC.
ROI: **H** user value immediate, **M** clear but deferred, **L** nice-to-have.

---

## Planned batches

Ordered by when we intend to ship them. Status at 2026-04-20.

### IV.4 — Safe features batch

**Target:** tag `0.34.0` (next increment after current `0.33.0`).

**Status:** ✅ CLOSED at HEAD `7cb5634` (2026-04-20).
All 4 findings PASS. Pending: real `git tag` command.

Scope:
- **F1** — Parquet UI export button + default pyarrow install
- **F2** — Debug mode toggle
- **F6** — Auto-report verification + report_enabled UI toggle
- **F11** — Shift handover auto-sections

Shipped: ~800 LOC, 4 commits, 5 amend cycles total, 863 GUI tests
passing. No engine refactor.

Spec: `CC_PROMPT_IV_4_BATCH.md` (closed).

Commit SHAs:
- F1 Parquet UI: `bf584ed` (2 amends)
- F6 auto-report verify: `0ec842f` (0 amends)
- F2 debug mode: `5f8b394` (2 amends)
- F11 shift handover: `7cb5634` (2 amends)

Telegram export in F11 deferred (out of IV.4 scope per Rule 4).

### IV.5 — Stretch features batch

**Target:** tag `0.35.0` after IV.4 closes, smoke passes, and ZMQ
subprocess bug (see "Known broken" below) resolved.

Scope:
- **F3** — Analytics placeholder widgets data wiring
  (requires engine-side `cooldown_history_get` command; non-trivial)
- **F5** — Hermes webhook integration
  (depends on Hermes service deployment on lab PC — coordinate with Vladimir)
- **F17** — SQLite → Parquet cold rotation in housekeeping

Estimated: ~1100-1300 LOC, 3 commits, ~7-8h CC. Includes engine changes.

Spec: not yet drafted; pending IV.4 outcomes + Hermes service readiness.

### Collaboration blocks (not autonomous)

- **F9** TIM auto-report — requires physics review with Vladimir for
  uncertainty budget correctness, GOST Р 54500.3-2011 compliance, methodology
  cross-check against existing protocol documents.
- **F8** Cooldown ML upgrade — requires training dataset curation from
  historical SQLite files + model evaluation notebook.

### Deferred (not scheduled)

F4, F7, F10, F12, F13, F14, F15, F16, F18 — see individual entries below.

---

## Detailed feature entries

### F1 — Parquet archive wire-up

**Status:** 🔧 PARTIAL.

Backend already works: `src/cryodaq/storage/parquet_archive.py` ships
`export_experiment_readings_to_parquet()`, and
`ExperimentManager.finalize_experiment()` already calls it best-effort
on every experiment close — the file lands at
`data/experiments/<id>/readings.parquet`. `pyarrow` is an optional
dependency (`pip install -e ".[archive]"`).

Missing pieces:

1. **Default install.** Move `pyarrow` from `[archive]` extra into
   base runtime deps in `pyproject.toml`. Cost: +60 MB install size.
   Benefit: finalize Parquet hook never silently skips.
2. **Archive UI export button.** The v2 ArchiveOverlay already has a
   global bulk-export card (CSV / HDF5 / Excel). Add «Parquet» as the
   fourth button, calling the same function as the finalize hook but
   targeting a user-chosen output path via `QFileDialog.getSaveFileName`.
3. **Per-experiment export button.** In ArchiveOverlay's details pane,
   for each archived experiment add «Скачать Parquet» that links to
   the existing `data/experiments/<id>/readings.parquet`.

Tests: 10 new cases covering UI button wiring + file-dialog flow.

### F2 — Debug mode toggle

**Status:** ⬜ NOT STARTED.

Operator needs to enable verbose file logging post-deployment to diagnose
issues without recompiling or editing `logging_setup.py`.

Implementation:

1. `QSettings` key `logging/debug_mode` (persistent across sessions).
2. QAction in Settings menu «Подробные логи (перезапуск)» with checkmark
   reflecting current state.
3. `logging_setup.setup_logging()` reads setting before configuring level:
   `logging.DEBUG if debug_mode else logging.INFO`.
4. Dialog informs operator that change requires launcher restart.
5. Engine also respects the setting — via environment variable
   `CRYODAQ_LOG_LEVEL=DEBUG` set by launcher before spawning engine.

Tests: 5 new cases covering setting persist, menu toggle, env var pass-through.

### F3 — Analytics placeholder widgets data wiring

**Status:** ⬜ NOT STARTED.

Phase III.C shipped 4 placeholder cards — layout correct, no data flow.
Used in warmup + disassembly phases + one cooldown slot.

Four widgets to wire:

- **`r_thermal_placeholder`** (cooldown/bottom_right) — prediction of
  when R_thermal stabilizes. Needs new engine service (R_thermal
  predictor) or derivable from existing cooldown_service.
- **`temperature_trajectory`** (warmup/main) — all temp channels on
  shared axis, full-experiment time window. Reuses existing
  `readings_history` command; just needs widget.
- **`cooldown_history`** (warmup/bottom_right) — past cooldown durations
  for comparison. Needs new engine command `cooldown_history_get` that
  mines past experiment metadata + phase transitions.
- **`experiment_summary`** (disassembly/main) — final summary card:
  total duration, phase breakdown, min/max values, alarm count, artifact
  links. Assembled from existing `experiment_status` + `readings_history`.

Engine-side additions:
- `cooldown_history_get` command (returns list of `{experiment_id,
  duration_s, start_T, end_T, timestamp}` for past cooldowns)
- Optional: `r_thermal_prediction` command if R_thermal predictor built
  (else defer to F8)

Estimated: ~600 LOC (400 GUI + 200 engine) + 30 tests.

### F4 — Analytics lazy-open snapshot replay

**Status:** ⬜ NOT STARTED. Residual from III.C.

When operator opens Analytics overlay mid-experiment, fresh replay is
empty — `set_cooldown()` was called before overlay existed. Widgets
see no initial data until next snapshot push.

Fix: shell caches last-known snapshot per widget ID (similar to existing
pattern for `set_experiment`). On overlay construction, replay cached
snapshots into newly-created widgets.

Estimated: ~150 LOC + 10 tests.

### F5 — Engine events → Hermes webhook

**Status:** ⬜ NOT STARTED. Depends on Hermes service deployment.

Configurable HTTP POST from `event_logger.log_event()`:

```yaml
# config/notifications.yaml
webhooks:
  - url: http://localhost:37777/cryodaq-event
    events: [phase_change, fault_latched, experiment_finalize]
    timeout_s: 2.0
    retry_attempts: 0
```

Best-effort: timeout + swallow on failure (Hermes may be down).
Payload shape: `{event, timestamp, experiment_id, phase, metadata}`.

Unlocks: Obsidian campaign notes, GraphRAG indexing, Telegram Q&A
about lab state.

Estimated: ~200 LOC + 15 tests.

**Blocker:** Hermes service must be deployed on lab Ubuntu first.

### F6 — Auto-report on experiment finalize

**Status:** ✅ DONE — verify only.

`ExperimentManager.finalize_experiment()` already calls
`ReportGenerator(data_dir).generate(experiment_id)` when
`report_enabled=True` on the experiment template.

Remaining verification:
1. Confirm current templates have `report_enabled: true` by default.
2. Confirm `NewExperimentDialog` exposes a UI checkbox for
   `report_enabled` override per-run (may already exist — check).
3. Confirm LibreOffice path works on lab Ubuntu 22.04 for PDF generation.

If all three pass, F6 is already shipped. No code changes needed.

### F7 — Web API readings query extension

**Status:** ⬜ NOT STARTED. Noted as GAP in PROJECT_STATUS.

Extend `src/cryodaq/web/server.py` with:

- `GET /api/readings?channels=T1,T2&from=<ts>&to=<ts>` — JSON/CSV response
- `GET /api/experiment/<id>` — summary
- `GET /api/experiment/<id>/readings.parquet` — Parquet stream
- `WebSocket /ws` — live readings stream (verify if already exists)
- Auth or loopback-only default per deferred G.1

Estimated: ~400 LOC + 25 tests + OpenAPI spec doc.

### F8 — Cooldown ML prediction upgrade

**Status:** 🔬 RESEARCH.

Current `cooldown_predictor.py` uses simple regression. Upgrade to
gradient boosted model (xgboost/lightgbm) with:
- Feature engineering from 30+ historical cooldowns (extract from SQLite)
- Uncertainty quantification via quantile regression
- A/B comparison notebook

Deliverables: new predictor class, training script, evaluation notebook.

Estimated: ~600 LOC + 40 tests + notebook. Non-blocking for operations.

### F9 — Thermal conductivity auto-report (TIM characterization)

**Status:** 🔬 RESEARCH. Physics collaboration with Vladimir required.

After conductivity experiment finalize, auto-generate report with:
- G(T) plot per sensor pair
- Uncertainty budget per GOST Р 54500.3-2011
- Comparison to previous samples (materials DB)
- Raw data Parquet export (F1 dependency)

Blockers:
- Vladimir's uncertainty budget methodology needs to be formalized as code
- Materials comparison DB structure TBD
- Report templates TBD

Estimated: ~500 LOC + 25 tests + DOCX templates. Close Vladimir interaction.

**Value:** direct support for publication-worthy TIM characterization data.

### F10 — Sensor diagnostics → alarm integration

**Status:** ⬜ NOT STARTED.

`sensor_diagnostics.py` shipped (MAD, correlation). Currently displays
only. Upgrade to publish anomaly events into Alarm Engine v2:

- Anomaly > 5 min → WARNING
- Anomaly > 15 min → CRITICAL
- ACK + auto-mute with configurable retry window

Estimated: ~250 LOC + 20 tests.

### F11 — Shift handover enrichment

**Status:** 🔧 PARTIAL. Legacy widget at `gui/widgets/shift_handover.py`
ships with form dialog + operator log integration.

Missing auto-sections:
- «Что случилось за смену» — filter `event_logger` by last 8/12/24h
- Active + acknowledged alarms list
- Max/min temperatures per channel over shift window
- Experiment progress (start phase → current phase)
- Export handover → Markdown / PDF / Telegram

Implementation note: legacy widget can be extended in-place OR rewritten
as `shell/overlays/shift_handover_panel.py` Phase II block. Pick extension
first (faster), rewrite later if Phase II reaches this widget.

Estimated: ~300 LOC + 15 tests.

### F12 — Experiment templates UI editor

**Status:** ⬜ NOT STARTED.

Templates live in `config/experiment_templates/*.yaml`, editable only by
hand. Add:
- GUI editor for custom_fields
- Preview card before save
- Import / export templates via `.yaml`

Estimated: ~400 LOC + 25 tests. Non-blocking.

### F13 — Vacuum leak rate estimator

**Status:** ⬜ NOT STARTED.

After valve close, measure pressure rise rate:
`dP/dt × V_chamber = leak rate (mbar·L/s)`.

Warning threshold configurable. Historical leak rate as criostat health
metric.

Estimated: ~200 LOC + 15 tests + physical calibration.

### F14 — Remote command approval (Telegram)

**Status:** ⬜ NOT STARTED. Safety-sensitive — requires security review.

Telegram command `/emergency_off confirm` → CryoDAQ emergency stop.
Two-factor: command + confirmation within 30s. Rate-limited,
chat_id-whitelisted.

Estimated: ~250 LOC + 20 tests + threat model doc.

### F15 — Linux AppImage / .deb package

**Status:** ⬜ NOT STARTED. Post-0.18.0.

Current deployment: `git clone` + `pip install -e .` works on Ubuntu.
PyInstaller + PySide6 + linux-gpib introduces complexity.

Options: AppImage (standalone exec), `.deb` package, Docker image.
Preferred: AppImage for desktop deployment simplicity.

Estimated: 1-2 days dev + cross-version testing.

### F16 — Plugin hot-reload SDK + examples

**Status:** ⬜ NOT STARTED.

`plugin_loader.py` shipped. Hot-reload assumed to work but not tested.

Add:
- `docs/plugins.md` SDK documentation
- 3-4 example plugins (Google Sheets uploader, webhook publisher,
  custom alarm rule)
- Hot-reload test suite

Estimated: ~300 LOC plugins + docs.

### F17 — SQLite → Parquet cold-storage rotation

**Status:** ⬜ NOT STARTED. Depends on F1.

`data/data_*.db` files accumulate forever. Housekeeping:
- Daily SQLite older than N days → Parquet (Zstd)
- Layout: `data/archive/year=YYYY/month=MM/`
- Original SQLite deleted after successful Parquet write
- Replay service reads both (SQLite recent, Parquet archive)

Estimated: ~350 LOC + 20 tests.

### F18 — CI/CD upgrade

**Status:** ⬜ NOT STARTED. Phase 2e residual.

Current `.github/workflows/main.yml`: pytest + ruff on push.

Add:
- Coverage reporting
- Cross-platform matrix (Ubuntu + Windows + macOS)
- Auto-tag + GitHub release on version bump
- Artifact publishing (wheels + F15 AppImage)

Estimated: ~200 LOC workflow.

---

## Collaboration guidelines

**Autonomous (CC batch work):** F1, F2, F3, F4, F5, F7, F10, F11, F12,
F13, F14, F16, F17, F18.

**Physics collab with Vladimir:** F8, F9, F13.

**Infrastructure collab (deployment side):** F5 (Hermes), F15 (Linux
packaging).

---

## Known broken (blocking next tag)

### B1 — ZMQ subprocess REQ socket dies after idle > 30s

**Status:** 🔥 TCP_KEEPALIVE fix did NOT resolve (delayed failure
from 4s → 55s uptime but still occurs), Codex handoff prepared.
Blocks `0.34.0` tag.

**Symptom:** GUI sends commands via `ZmqBridge`, works for some time
(first command after bridge start always OK), then after >30s idle
any subsequent command hangs for exactly 35s (= `RCVTIMEO`). After
that **every subsequent command** hangs the same 35s. Subprocess
doesn't recover.

**Diagnostic timeline (2026-04-20):**
1. `diag_zmq_subprocess.py` — raw subprocess works fine.
2. `diag_zmq_bridge.py` — phase 1 (5 seq), phase 2 (10 concurrent)
   all OK; phase 3 (1 Hz soak) → first FAIL at cmd #28.
3. `diag_zmq_bridge_extended.py` — commands 1-4 OK (1s interval),
   cmd #5 FAIL at uptime=39s, then 0/5 recovery.
4. `diag_zmq_idle_hypothesis.py` — **SMOKING GUN**:
   - 5 Hz (200ms idle): **291/291 OK** over 60s
   - 0.33 Hz (3s idle): 9 OK, cmd #10 FAIL
   - 5 Hz after sparse: 1/1 FAIL immediately — socket permanently dead

**Root cause CONFIRMED:** macOS kernel reaps idle loopback TCP
connections after ~30s inactivity. Once reaped, REQ socket is
permanently degraded because the pyzmq ZMQ context retains the
dead peer mapping — recreating the Python socket object doesn't
reset the kernel-side TCP state.

**Fix applied (2026-04-20, uncommitted):**

TCP keepalive on ALL four sockets so the kernel does not reap
the connection:

```python
sock.setsockopt(zmq.TCP_KEEPALIVE, 1)
sock.setsockopt(zmq.TCP_KEEPALIVE_IDLE, 10)   # probe every 10s
sock.setsockopt(zmq.TCP_KEEPALIVE_INTVL, 5)   # retry interval 5s
sock.setsockopt(zmq.TCP_KEEPALIVE_CNT, 3)     # 3 fails = dead
```

Applied to:
- `src/cryodaq/core/zmq_subprocess.py` — SUB (`sub_drain_loop`) + REQ
  (`_new_req_socket`)
- `src/cryodaq/core/zmq_bridge.py` — `ZMQPublisher` PUB + `ZMQCommandServer` REP

Kernel-reap happens from either side of a TCP connection, so the
fix must be mirrored on engine + subprocess sockets. `zmq_bridge.py::
ZMQSubscriber` (legacy, unused in production) NOT patched.

**Verification result (2026-04-20):** TCP_KEEPALIVE partially helped
but bug persists:
- Run A: cmds 1-55 OK (55s), cmd #58 FAIL at uptime 92s, 0/3 recovery
- Run B: cmds 1-20 OK (20s), cmd #22 FAIL at uptime 56s, 0/4 recovery

Keepalive moved the failure point later but didn't eliminate it.
First-failure time is stochastic (variable across runs). Something
other than simple idle reaping is at play.

**Next step:** Codex review with full handoff doc in
`docs/bug_B1_zmq_idle_death_handoff.md`.

**Fallback candidates after Codex weighs in:**
- Switch loopback transport `tcp://127.0.0.1:5555/5556` → `ipc:///tmp/...`
  (Unix domain sockets, no TCP kernel layer, no idle reaping)
- Or: replace `mp.Process` + `mp.Queue` architecture with in-process
  threads (Windows libzmq-crash rationale doesn't apply on macOS/Linux)

---

## References

- `PROJECT_STATUS.md` — infrastructure state, safety invariants, commit
  history, Phase II block status
- `docs/phase-ui-1/phase_ui_v2_roadmap.md` — UI rebuild phases (Phase
  II / III continuation)
- `CHANGELOG.md` — shipped feature history
- `CC_PROMPT_IV_*_BATCH.md` — active / queued batch specs
- `docs/CODEX_SELF_REVIEW_PLAYBOOK.md` — autonomous workflow
- Memory slot 10 — TODO backlog (parts obsoleted by this doc)
