# CryoDAQ — Feature Roadmap

> **Living document.** Updated 2026-04-28 after v0.39.0 release (HEAD `955bb71`, B1 closed).
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
| F1 | Parquet archive wire-up | ✅ DONE (shipped v0.34.0) | S | H |
| F2 | Debug mode toggle (verbose logging) | ✅ DONE (shipped v0.34.0) | S | H |
| F3 | Analytics placeholder widgets → data wiring | ✅ DONE (W1–W3; W4 deferred F8) | M | M |
| F4 | Analytics lazy-open snapshot replay | ✅ DONE (merged in F3-Cycle1) | S | M |
| F5 | Engine events → Hermes webhook | ⬜ | M | M |
| F6 | Auto-report on experiment finalize | ✅ DONE (shipped v0.34.0) | S | H |
| F7 | Web API readings query extension | ⬜ | L | M |
| F8 | Cooldown ML prediction upgrade | 🔬 | L | M |
| F9 | Thermal conductivity auto-report (TIM) | 🔬 | M | H |
| F10 | Sensor diagnostics → alarm integration | ✅ DONE (shipped v0.41.0) | M | M |
| F11 | Shift handover enrichment | ✅ DONE (v0.34.0; Telegram export deferred) | S | H |
| F12 | Experiment templates UI editor | ⬜ | M | L |
| F13 | Vacuum leak rate estimator | ⬜ | M | M |
| F14 | Remote command approval (Telegram) | ⬜ | M | L |
| F15 | Linux AppImage / .deb package | ⬜ | L | L |
| F16 | Plugin hot-reload SDK + examples | ⬜ | M | L |
| F17 | SQLite → Parquet cold-storage rotation | ⬜ | M | M |
| F18 | CI/CD upgrade (coverage, matrix, releases) | ⬜ | M | L |
| F19 | F3.W3 experiment_summary enriched content | ✅ DONE (shipped v0.43.0) | S–M | M |
| F20 | Diagnostic alarm notification polish | ✅ DONE (shipped v0.43.0) | S | L |
| F21 | Alarm hysteresis deadband | ✅ DONE (shipped v0.43.0) | S | M |
| F22 | Diagnostic alarm severity escalation | ✅ DONE (shipped v0.43.0) | S | M |
| F23 | RateEstimator measurement timestamp | ✅ DONE (shipped v0.43.0) | S | M |
| F24 | Interlock acknowledge ZMQ command | ✅ DONE (shipped v0.43.0) | S | M |
| F25 | SQLite WAL corruption startup gate | ✅ DONE (shipped v0.43.0) | S | M |
| F26 | SQLite WAL gate backport whitelist | ⬜ | XS | L |

Effort: **S** ≤200 LOC, **M** 200-600 LOC, **L** >600 LOC.
ROI: **H** user value immediate, **M** clear but deferred, **L** nice-to-have.

---

## Planned batches

Ordered by when we intend to ship them. Status at 2026-04-28.

### IV.4 — Safe features batch

**Target:** ✅ tag `v0.34.0` (retroactive, applied 2026-04-27).

**Status:** ✅ SHIPPED v0.34.0 (commit `256da7a`, released 2026-04-27 retroactive tag).
All 4 findings PASS. Retroactive versioning chain: v0.34.0..v0.39.0.

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

**Target:** next minor version after v0.39.0 production-stable period.
B1 blocker resolved (see B1 RESOLVED stub below).

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

F7, F10, F12, F13, F14, F15, F16, F18, F19 — see individual entries below.

---

## Detailed feature entries

### F1 — Parquet archive wire-up

**Status:** ✅ DONE. Shipped v0.34.0.

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

**Status:** ✅ DONE. Shipped v0.34.0.

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

**Status:** ✅ DONE (W1–W3 + F4 wired; W4 r_thermal deferred to F8).

Phase III.C shipped 4 placeholder cards — layout correct, no data flow.
Used in warmup + disassembly phases + one cooldown slot.
F3 completed across 5 cycles (2026-04-29):
- W1 `temperature_trajectory`: live multi-channel history plot (warmup/main)
- W2 `cooldown_history`: scatter of past cooldown durations (warmup/bottom_right)
- W3 `experiment_summary`: header/duration/alarms/artifacts (disassembly/main)
- W4 `r_thermal_placeholder`: kept as placeholder; text updated (depends F8)
- F4 lazy-open replay: shell-level snapshot cache for AnalyticsView

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

**Status:** ✅ DONE. Shipped v0.34.0. Verification passed.

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

**Status:** ✅ DONE. Shipped v0.41.0.

Sensor diagnostics anomaly events now flow through Alarm Engine v2.
Warning at 5 min sustained anomaly, critical at 15 min, auto-clear on
return to ok. Telegram dispatch via `_sensor_diag_tick`. Config in
`plugins.yaml`. 17 new tests; 3-cycle overnight implementation.

See CHANGELOG [0.41.0] for full details. F20 added for notification
polish (aggregation + escalation cooldown).

### F11 — Shift handover enrichment

**Status:** ✅ DONE. Shipped v0.34.0. Telegram export deferred.

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

### F19 — F3.W3 experiment_summary enriched content

**Status:** ✅ DONE. Shipped v0.43.0 (overnight 2026-04-30).
**Effort:** S–M (~150–250 LOC).
**Source:** Deferred from F3 Cycle 4 audit (master summary 2026-04-29, items #2–4).

Enrichment for `experiment_summary` widget (disassembly phase main slot).
Three independent sub-items, each shippable as a separate commit:

1. **Channel min/max/mean table** — for critical channels (T1..T8,
   pressure, Keithley power) computed via `readings_history` range
   queries over the experiment timespan.
2. **Top-3 most-triggered alarm names** — extract from
   `alarm_v2_history` (already wired in F3 for total count).
3. **Clickable artifact links** — DOCX / PDF / Parquet / JSON
   metadata paths via `QDesktopServices.openUrl`.

Recommend: post-v0.40.0 stable period or after operator feedback
identifies top priority among the three.

### F20 — Diagnostic alarm notification polish

**Status:** ✅ DONE. Shipped v0.43.0 (overnight 2026-04-30).
**Effort:** S (~80–150 LOC).
**Source:** Deferred from F10 Cycle 3 review (overnight 2026-04-29 finding #3).

Two independent enhancements for diagnostic alarm Telegram notifications
introduced in F10 (v0.41.0):

1. **Aggregation** — when N > 3 channels go warning/critical in the same
   tick, send a single message ("5 channels critical: T1, T3, T5, T7, T9")
   instead of N separate messages. Prevents Telegram flood during
   multi-channel simultaneous anomaly (e.g., shield group all going noisy).
2. **Per-channel escalation cooldown** — prevent rapid warning→critical→
   warning re-firing if a channel oscillates near the threshold. Configurable
   cooldown window per escalation level (separate from the interlock cooldown).

Edge case currently bounded: in normal ops ≤16 channels, simultaneous
criticals indicate genuine catastrophe where flood is preferable to silence.
Not blocking F10 shipment.

Recommend: implement after first production observation of multi-channel
diagnostic alarms; user feedback will clarify aggregation threshold.

---

### F21 — Alarm hysteresis deadband (was Task A #1.3)

**Status:** ✅ DONE. Shipped v0.43.0 (overnight 2026-04-30).
**Effort:** S (~80–150 LOC).
**Source:** Task A verification 2026-04-29 finding #1.3.

`AlarmStateManager._check_hysteresis_cleared()` in `src/cryodaq/core/alarm_v2.py`
is currently a stub returning `True` unconditionally. Config schema already
accepts a `hysteresis` key but it is not evaluated. Implement deadband logic:
alarm clears only when channel value crosses threshold minus hysteresis margin.

---

### F22 — F10 diagnostic alarm severity escalation (was Task A #1.4)

**Status:** ✅ DONE. Shipped v0.43.0 (overnight 2026-04-30).
**Effort:** S (~80 LOC).
**Source:** Task A verification 2026-04-29 finding #1.4.

`AlarmStateManager.publish_diagnostic_alarm()` uses `alarm_id = f"diag:{channel_id}"`
for both warning and critical levels. If warning is active, critical can never
fire (early return on existing alarm_id). Fix: either separate alarm IDs per
severity (`diag-warning:` / `diag-critical:`) or implement severity-upgrade
semantics where critical replaces warning in-place.

---

### F23 — RateEstimator measurement timestamp (was Task A #1.7)

**Status:** ✅ DONE. Shipped v0.43.0 (overnight 2026-04-30).
**Effort:** S (~30 LOC + tests).
**Source:** Task A verification 2026-04-29 finding #1.7.

`SafetyManager._collect_loop` calls `rate_estimator.push(channel, now, value)` where
`now = time.monotonic()` (queue dequeue time), not `reading.timestamp`. Under queue
backlog, `now` values cluster, distorting computed rate. Use
`reading.timestamp.timestamp()` for true measurement-time-based rate computation.

---

### F24 — Interlock acknowledge ZMQ command (was Task A #1.8)

**Status:** ✅ DONE. Shipped v0.43.0 (overnight 2026-04-30).
**Effort:** S (~100 LOC).
**Source:** Task A verification 2026-04-29 finding #1.8.

`InterlockEngine.acknowledge()` exists but is not exposed as ZMQ command. Once
an interlock trips, it stops monitoring its condition indefinitely until process
restart. Expose `interlock_acknowledge` as ZMQ verb so operator can re-arm an
interlock after the underlying condition has cleared.

---

### F25 — SQLite WAL corruption startup gate (was Task A #1.10)

**Status:** ✅ DONE. Shipped v0.43.0 (overnight 2026-04-30).
**Effort:** S (~50 LOC).
**Source:** Task A verification 2026-04-29 finding #1.10.

`SQLiteWriter._check_sqlite_version()` currently issues `logger.warning(...)` for
affected SQLite versions (3.7.0–3.51.2 WAL corruption bug, March 2026). Decision
needed: hard-fail startup on affected versions, or opt-in env var bypass with
explicit acknowledgment. Either way: must NOT silently continue.

---

### F26 — SQLite WAL gate backport whitelist

**Status:** ⬜ NOT STARTED.
**Effort:** XS (~20 LOC).
**Source:** F25 architect note 2026-04-30. Conservative gate in F25 blocks
versions [3.7.0, 3.51.3) but per SQLite docs, backports (3.44.6, 3.50.7) are
safe. Add per-version whitelist to `_check_sqlite_version()` to allow those
specific patch builds without requiring `CRYODAQ_ALLOW_BROKEN_SQLITE=1`.

---

## Collaboration guidelines

**Autonomous (CC batch work):** F1, F2, F3, F4, F5, F7, F10, F11, F12,
F13, F14, F16, F17, F18.

**Physics collab with Vladimir:** F8, F9, F13.

**Infrastructure collab (deployment side):** F5 (Hermes), F15 (Linux
packaging).

---

## Known issues

### B1 — ZMQ idle-death (RESOLVED v0.39.0)

**Status:** ✅ CLOSED 2026-04-27.

7-day investigation closed. Root cause: asyncio cancellation polling
pattern (`asyncio.wait_for(socket.recv(), timeout)`) in
`ZMQCommandServer._serve_loop` accumulated pyzmq reactor state,
wedging REP after ~50 cancellations.

Fix: `poll(timeout) + conditional recv()` pattern in
`src/cryodaq/core/zmq_bridge.py`. Verified 180/180 clean on macOS
dev and Ubuntu lab PC.

Investigation chain:
- H1 falsified — macOS idle reap
- H2 falsified — shared REQ state (IV.6 mitigation)
- H3 partially falsified — TCP loopback (IV.7 ipc:// experiment
  remains as open worktree, not blocking)
- H4 falsified — shared zmq.Context (D2 split-context experiment)
- H5 confirmed + fixed (D3 direct-REQ + D4 fix)

Decision ledger: `docs/decisions/2026-04-27-d{1,2,3,4}-*.md`.
Full handoff: `docs/bug_B1_zmq_idle_death_handoff.md`.

---

## Post-v0.39.0 known issues

### Cooldown_stall threshold_error

**Status:** mitigated, not fully resolved.

`alarm_v2.py:_eval_condition` defensive `cond.get("threshold")`
handling shipped v0.38.0 (commit `1869910`). Log spam eliminated.
Underlying config issue in `config/alarms_v3.yaml` (cooldown_stall
composite alarm sub-condition without threshold) deferred —
operational alarm definitions need physics review.

### IV.7 ipc:// transport experiment worktree

**Status:** worktree at `experiment/iv7-ipc-transport`, not in master.

Pre-H5-fix exploration of Unix-domain socket fallback. Now superseded
by H5 fix (no longer blocks anything). Worktree retained for
reference; can be deleted on future cleanup pass.

---

## References

- `PROJECT_STATUS.md` — infrastructure state, safety invariants, commit
  history, Phase II block status
- `docs/phase-ui-1/phase_ui_v2_roadmap.md` — UI rebuild phases (Phase
  II / III continuation)
- `CHANGELOG.md` — shipped feature history
- `CC_PROMPT_IV_*_BATCH.md` — active / queued batch specs
- `docs/CODEX_SELF_REVIEW_PLAYBOOK.md` — autonomous workflow
- `docs/ORCHESTRATION.md` — agent governance contract v1.2 (CC-centric
  swarm model, STOP discipline, autonomy band, artifact layout)
- `docs/decisions/2026-04-27-d{1,2,3,4}-*.md` — B1 investigation
  decision ledger (D1 R1 probe retry, D2 H4 split-context, D3 H5
  direct-REQ, D4 H5 fix)
- `~/Vault/CryoDAQ/` — Obsidian knowledge base
- Memory slot 10 — TODO backlog (parts obsoleted by this doc)
