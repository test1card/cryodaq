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

**Target:** retroactive release line `0.34.0` within the reconstructed
post-`v0.33.0` history. The next formal version line now continues from
`0.36.0`; see `CHANGELOG.md`.

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

### B1 — ZMQ subprocess command channel dies (not idle-related)

**Status:** 🔧 IV.6 partial mitigation shipped, root cause still unresolved.
Blocks the next formal tag line (`0.36.0`) and therefore blocks IV.5 feature execution as the
next safe repo phase.

**Current master includes:**
- `be51a24` — per-command ephemeral REQ + command-channel watchdog
  (IV.6 partial mitigation, not a fix)
- `af0b2a0` — watchdog cooldown preventing restart storm
- `c3a4a49` — bridge restart-count / exit-code diagnostics
- `256da7a` — docs + control-plane sync for the next phase

**Next step:** run a disciplined evidence pass against current `master`
using the canonical B1 capture tool and runbook. IV.7 `ipc://` remains
an experiment candidate, not a committed migration path.

**Symptom:** GUI command plane (REQ/REP on `tcp://127.0.0.1:5556`)
works for some time then hangs permanently. Data plane (SUB on 5555)
unaffected — readings continue flowing.

- macOS: first failure at 4-92s uptime (stochastic, rate-dependent)
- Ubuntu: first failure at **exactly 120s** after subprocess start
  (deterministic — single data point, may vary)

**NOT macOS-specific.** Confirmed on Ubuntu 22.04 lab machine
(Python 3.12.13, pyzmq 26.4.0, libzmq 4.3.5). Reproduces in live
`./start.sh` run, not just diagnostic tools.

**Root cause (Codex-confirmed 2026-04-20 afternoon):** single
long-lived REQ socket in `cmd_forward_loop()` eventually enters
unrecoverable state. Shared state across all commands means one
bad socket poisons the entire command channel permanently.

**Original "macOS idle-reap" hypothesis proved WRONG:**
- Linux default `tcp_keepalive_time = 7200s` rules out kernel reaping.
- Active polling at 1 Hz never goes idle for 10s (our keepalive
  threshold), so probes never fire — TCP_KEEPALIVE fix doesn't
  participate in failure mode.
- TCP_KEEPALIVE fix (commit `f5f9039`) was not the failure mechanism;
  IV.6 shipped the mitigation package instead.

**IV.6 mitigation package:**
1. **Primary:** per-command ephemeral REQ socket in
   `zmq_subprocess.py::cmd_forward_loop()`. Shipped in `be51a24`.
2. **Secondary:** command-channel watchdog in `launcher.py` with
   restart cooldown. Shipped in `af0b2a0`.

**Full evidence + Codex analysis:**
`docs/bug_B1_zmq_idle_death_handoff.md`.

**Implementation spec:**
`CC_PROMPT_IV_6_ZMQ_BRIDGE_FIX.md`.

**Diagnostics kept in tree** (will remain after fix for
regression testing):
- `tools/diag_zmq_subprocess.py` — subprocess alone
- `tools/diag_zmq_bridge.py` — full ZmqBridge 60s soak
- `tools/diag_zmq_bridge_extended.py` — 180s past-first-failure
- `tools/diag_zmq_idle_hypothesis.py` — rate-dependence

#### IV.6 partial mitigation outcome (2026-04-20)

IV.6 shipped the Codex-proposed mitigation package: per-command
ephemeral REQ socket in `zmq_subprocess.cmd_forward_loop`,
launcher-side `command_channel_stalled()` watchdog in
`_poll_bridge_data`, and `TCP_KEEPALIVE` adjustments on the command +
PUB paths (kept on `sub_drain_loop` as orthogonal safeguard). 60/60
unit tests green, full subtree 1775/1776 (1 unrelated flaky).
Committed as `be51a24` as partial mitigation rather than a fix.

**Shared-REQ-state hypothesis FALSIFIED.** Post-fix diag runs on
macOS reproduce B1 with structurally identical timing to pre-fix
master:

- `diag_zmq_idle_hypothesis.py` SPARSE_0.33HZ: cmd #8 FAIL at
  uptime 56 s (pre-fix was cmd #10 FAIL at ~30 s).
- `diag_zmq_bridge_extended.py`: cmd #48 FAIL at uptime 82 s,
  0/3 recovery thereafter (pre-fix was cmd #28 FAIL at 92 s).
- RAPID_5HZ path still clean (295/295), matching pre-fix behaviour
  — rate-dependence preserved.

Removing shared REQ state did NOT eliminate the failure. Engine
REP goes silently unresponsive after ~30-90 s of bridge uptime
while the asyncio loop, data-plane PUB, heartbeats, scheduler
writes, and plugin ticks all remain healthy. Root cause is
elsewhere — likely libzmq loopback-TCP handling, pyzmq 25.x +
Python 3.14 asyncio integration, or engine-side REP task state
under rapid REQ connect/disconnect churn.

Diag logs preserved at `/tmp/diag_iv6_idle.log`,
`/tmp/diag_iv6_extended.log`, and `/tmp/engine_iv6_debug.log`
for architect review.

**Status:** still 🔧. B1 remains OPEN and blocks the next formal tag line (`0.36.0`).

**Next:** IV.7 `ipc://` transport experiment (spec
`CC_PROMPT_IV_7_IPC_TRANSPORT.md`). Fallback (a) from the original
handoff is now the working hypothesis — Unix-domain sockets bypass
the TCP-loopback layer entirely, which is the most likely remaining
culprit given everything above the transport has been ruled out.

IV.6 code stays in master as defense-in-depth: matches ZeroMQ
Guide ch.4 canonical poll/timeout/close/reopen pattern, removes
a real brittle point (shared REQ accumulated state), and gives
the launcher a genuine command-channel watchdog for any future
command-only failure shape — independent of whether B1 is
ultimately resolved at the transport layer.

#### IV.6 watchdog regression + cooldown hotfix (2026-04-20 evening)

The IV.6 `command_channel_stalled()` watchdog had a regression:
`_last_cmd_timeout` persisted across watchdog-triggered subprocess
restart, so the fresh subprocess immediately saw a stale
cmd_timeout signal on the very next `_poll_bridge_data` tick and
was restarted again — restart storm (30-40 restarts/minute
observed on Ubuntu lab PC).

Hotfix applied in `src/cryodaq/launcher.py`: 60 s cooldown between
command-watchdog restarts via `_last_cmd_watchdog_restart`
timestamp, plus missing `return` after restart so no further
checks run in the same poll cycle. Does not resolve B1 itself —
only prevents the watchdog from pathologically amplifying it.
System returns to "works ~60-120 s, one restart, works again"
cycle which is a usable workaround until IV.7 `ipc://` ships.

#### Related fixes shipped alongside IV.6 (2026-04-20)

- `aabd75f` — `engine: wire validate_checksum through Thyracont
  driver loader`. `_create_instruments()` was ignoring the YAML
  key; driver defaulted to `True` regardless of config. Fix
  resolves TopWatchBar pressure em-dash on Ubuntu lab PC (VSP206
  hardware has different checksum formula than VSP63D).
- `74dbbc7` — `reporting: xml_safe sanitizer for python-docx
  compatibility`. Keithley VISA resource strings contain `\x00`
  per NI-VISA spec; python-docx rejected them as XML 1.0
  incompatible when embedded in auto-reports. New
  `src/cryodaq/utils/xml_safe.py` strips XML-illegal control chars;
  applied at all `add_paragraph()` / `cell.text` sites in
  `src/cryodaq/reporting/sections.py`; `core/experiment.py:782`
  logger upgraded from `log.warning` to `log.exception` so future
  report-gen failures carry tracebacks.

**No-longer-broken bugs:** TopWatchBar pressure display (was
reading-driven, not B1-caused) is now resolved by `aabd75f` +
Ubuntu-side config (`validate_checksum: false` in
`instruments.local.yaml`).

**Orthogonal issue still open:** `alarm_v2.py:252` raises
`KeyError: 'threshold'` when evaluating the `cooldown_stall`
composite alarm (one sub-condition is missing a `threshold`
field — probably stale/rate-type where `threshold` is spurious).
Log spam every ~2 s. Engine does not crash. Fix candidate: config
adjustment in `config/alarms_v3.yaml` OR defensive
`cond.get("threshold")` check in `_eval_condition`.

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
