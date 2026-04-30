# CHANGELOG.md

Все заметные изменения в проекте CryoDAQ документируются в этом файле.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/).
Проект использует [Semantic Versioning](https://semver.org/lang/ru/).

---

## [Unreleased]

## [0.46.1] — 2026-05-01 — F29 fix-up (swarm audit CF-2/CF-3/CF-5)

Patch release incorporating three fixes found by the 8-model swarm audit
of v0.46.0 (commit `ef0a1eb`). No new functionality; no engine wiring changes.

### Fixed
- CF-2: SQLite read failure during periodic report context build no longer silently
  suppresses the hourly report. Failure now logs at WARNING and sets
  `context_read_failed=True`; handler bypasses `skip_if_idle` so operators receive
  an empty-data report rather than silence (`context_builder.py`, `agent.py`).
- CF-3: Phase transitions tagged `"phase"` by the engine were not matching the
  context builder's `"phase_transition"` filter — phase section always showed
  `(нет)`. Both tags now accepted; `other_entries` filter updated to exclude
  `"phase"` entries to avoid double-classification (`context_builder.py`).
- CF-5: `PERIODIC_REPORT_SYSTEM` now explicitly prohibits LaTeX notation and
  `$...$` formulas. Removed `\rightarrow` backslash notation which was a Python
  string escape bug (rendered as CR + `ightarrow` at runtime, `prompts.py`).

### Tests
- `test_periodic_report_context_read_failure_sets_flag`
- `test_periodic_report_context_read_failure_bypasses_idle_skip`
- `test_periodic_report_context_phase_tag_classified_correctly`
- `test_periodic_report_prompt_prohibits_latex` strengthened (no `\r` control char)

### Test baseline
- 27 tests passing (3 new vs v0.46.0 baseline of 24)

### Tags
- `v0.46.1` → 70bb588

### Selected commits in this release
- `70bb588` fix(f29): swarm audit findings CF-2 CF-3 CF-5

## [0.46.0] — 2026-04-30 — F29 Periodic narrative reports

### Added
- F29: configurable Russian-language narrative summary of recent engine activity.
- New EventBus event type: `periodic_report_request`.
- Engine timer task `_periodic_report_tick`, controlled by
  `agent.triggers.periodic_report`.
- AssistantLiveAgent handler `_handle_periodic_report`.
- Prompt templates `PERIODIC_REPORT_SYSTEM` / `PERIODIC_REPORT_USER`.
- Context builder method `build_periodic_report_context`.
- Skip-if-idle filtering when a window has fewer than
  `min_events_for_dispatch` events.
- Output prefix variation: `🤖 Гемма (отчёт за час):`.
- GUI insight panel chip for periodic reports.
- F29 smoke harness:
  `artifacts/scripts/smoke_f29_periodic_report.py`.

### Changed
- Default assistant model in `config/agent.yaml`: `gemma4:e4b` →
  `gemma4:e2b` for M5 24GB compatibility.
- Periodic prompt wording now respects configurable `window_minutes`
  instead of hardcoding the last hour.

### Configuration
- `config/agent.yaml`: new `triggers.periodic_report` section with
  `enabled`, `interval_minutes`, `skip_if_idle`, and
  `min_events_for_dispatch`.

### Tests
- Added Phase D engine timer tests for publish, disabled no-op, and shutdown
  cancellation.
- Added context/prompt regressions for calibration section formatting and
  non-hourly window wording.
- Focused F29 slice: 34 tests passing.
- Smoke: real `gemma4:e2b`, 19.2s wall latency, 94.8% Russian,
  Telegram/log/GUI/audit dispatch verified, idle skip verified.

### Reference
- Architecture: `artifacts/architecture/assistant-v2-vision.md` §5 Phase 1
- Spec: `CC_PROMPT_F29_PERIODIC_REPORTS.md`
- Smoke: `artifacts/handoffs/2026-04-30-f29-cycle1-smoke.md`
- Audit: `artifacts/consultations/2026-04-30/f29-cycle1-audit/synthesis.md`

## [0.45.0] — 2026-05-01 — F28 Гемма complete (assistant v1)

### Highlights
- F28 Гемма local LLM agent fully shipped: Slice A (4 notification
  triggers) + Slice B (diagnostic suggestions) + Slice C (campaign
  report intro)
- Foundation EventBus primitive (Cycle 0) for non-Reading engine events
- Local Ollama integration with gemma4:e4b model
- Russian-language operator-facing dispatch (Telegram, operator log,
  GUI insight panel)
- DOCX campaign report intro auto-generation (formal Russian, 200-400 words)
- Audit log discipline: every LLM call recorded for review
- Brand abstraction: future model migrations are config-only

### Added
- `src/cryodaq/agents/assistant/` — complete assistant module family
  - `live/agent.py` — AssistantLiveAgent (was GemmaAgent)
  - `live/prompts.py` — {brand_name} interpolated system prompts
  - `live/output_router.py` — brand-aware prefix, assistant_insight events
  - `live/context_builder.py` — engine state → LLM context
  - `shared/audit.py` — per-call JSON audit records
  - `shared/ollama_client.py` — async Ollama /api/generate wrapper
  - `shared/report_intro.py` — sync DOCX intro generator
  - `shared/retention.py` — 90-day audit log cleanup
- `src/cryodaq/gui/shell/views/assistant_insight_panel.py`
  — AssistantInsightPanel with brand_name/brand_emoji params
- `config/agent.yaml` — new `agent.*` namespace with brand_name, brand_emoji
- `artifacts/architecture/assistant-v2-vision.md` — full architecture spec
  for F29-F33 assistant v2 phases

### Changed
- `config/agent.yaml`: `gemma:` namespace → `agent:` namespace
  (backward compat: `gemma:` still loads with deprecation warning until v0.46.0)
- AssistantConfig: `from_yaml_path()` / `from_yaml_string()` for namespace detection
- Audit log path: `data/agents/gemma/audit` → `data/agents/assistant/audit`
- EventBus event_type: `gemma_insight` → `assistant_insight`
- ROADMAP: F28 ✅ DONE; F5/F9 RETIRED; F29-F33 added (assistant v2 phases)

### F28 cycles
- Cycle 0: EventBus foundation
- Cycle 1: Ollama client + audit + context builder
- Cycle 2: AssistantLiveAgent + alarm summary (Slice A first)
- Cycle 3: Slice A complete (4 triggers + GUI panel)
- Cycle 4: Slice B diagnostic suggestions
- Cycle 5: Slice C campaign report
- Cycle 6: brand abstraction + module rename + polish + this release

### Architecture
- Module: `src/cryodaq/agents/assistant/{live,shared}/`
- Class: `AssistantLiveAgent` (was `GemmaAgent`)
- Config namespace: `agent.*` (was `gemma.*`, backward compat with warning)
- Storage: `data/agents/assistant/audit/`
- Brand-name interpolation throughout prompts and outputs

### Tests
- 71 agent tests (smoke + unit + integration)
- Full suite green (~2 090 passing)
- 11 brand abstraction tests
- 4 audit retention tests

### Calibration data
- 6 multi-model audit sessions in `artifacts/calibration/log.jsonl`
- Empirical: Codex reliable; GLM strong on review (max_tokens=8192);
  Qwen3-Coder over-flags; MiniMax deteriorating; Kimi failures

### Documentation
- README: "Местный AI-ассистент" section
- Vault note: `~/Vault/CryoDAQ/10 Subsystems/Assistant agent.md`
- Operator manual: new section 10 (assistant behavior + on/off)
- Architecture: `artifacts/architecture/assistant-v2-vision.md`

### Tags
- `v0.45.0` → release commit (see Phase G)

### Selected commits in this release
- `adc40d7` — refactor(f28): rename agents/gemma → agents/assistant (Phase A)
- `00bd20f` — refactor(f28): rename GemmaAgent → AssistantLiveAgent (Phase B)
- `a1f2811` — feat(f28): brand-name abstraction for assistant (Phase C)
- `2fed36c` — docs(f28): polish — README, vault note, operator manual, retention (Phase D)
- `7148432` — test(f28): rename insight panel test + smoke doc (Phase E)

## [0.44.0] — 2026-05-01 — Storage maturity + leak rate

### Highlights
- F17: SQLite → Parquet cold rotation with day-by-day archive layout.
  ArchiveReader replay across both sources.
- F13: Vacuum leak rate estimator (LeakRateEstimator) with sliding-window OLS,
  ZMQ commands, atomic history persistence.
- F26: SQLite WAL gate backport whitelist (3.44.6, 3.50.7) per official SQLite advisory.

### Storage (F17, F26)
- **F17 — ColdRotationService**: rotates SQLite files older than 30 days to Parquet/Zstd;
  verifies row count before deletion; daemon mode (86400s). Corrupt index.json aborts
  rotation rather than overwriting. asyncio.Lock guards concurrent runs.
- **F17 — ArchiveReader**: unified query across SQLite (recent) + Parquet (archive);
  UTC-normalized day iteration; fails loudly on corrupt index.
- **F26 — SQLITE_BACKPORT_SAFE whitelist**: `{(3,44,6),(3,50,7)}` bypass the startup gate
  without env var; adjacent versions still raise. Source: sqlite.org/wal.html advisory.

### Vacuum analytics (F13)
- **LeakRateEstimator**: sliding-window OLS with FIFO trim, numpy-free regression,
  R²=0.0 on degenerate input, atomic history persistence to `data/leak_rate_history.json`.
- **Engine ZMQ commands**: `leak_rate_start` (duration_s validated), `leak_rate_stop`
  (returns asdict(LeakRateMeasurement)).
- **Engine broker task**: `_leak_rate_feed()` subscribes pressure samples (unit==mbar),
  auto-finalizes on window expiry.
- **Config**: `chamber.volume_l` (operator must set), `chamber.leak_rate.*`.

### Operator action required
- `chamber.volume_l` must be set in `config/instruments.local.yaml` before first
  leak rate measurement; `finalize()` raises ValueError if volume_l == 0.0.

### Tests
- 49 new tests across F26 (6) + F17 (16) + F13 (19).
- Full suite ~2 019 passing.

### Tags
- `v0.44.0` → F13 merge commit

### Closing commits
- F26 merge: see `git log --oneline --merges`
- F17 merge: see `git log --oneline --merges`
- F13 merge: see `git log --oneline --merges`

## [0.43.0] — 2026-04-30 — Overnight feature sprint (F19-F25)

### Highlights
- 7 features shipped from a single overnight Sonnet sprint (F19-F25), closing all
  deferred Task A findings and the F3 polish backlog.
- Phase A doc/process updates landed direct to master earlier in the session:
  ORCHESTRATION v1.3 + multi-model-consultation skill v1.1 + plugin disposition.
- Both feature branches Codex-audited (gpt-5.5 high-reasoning): alarm cluster
  FAIL→PASS (2 MEDIUM fixes); misc cluster CONDITIONAL→PASS (1 P2 fix).

### Alarm pipeline (F20, F21, F22)
- **F20 — Sensor diagnostics aggregation + cooldown**: `_channel_last_notified`
  dict tracks per-channel state; first notification never suppressed; critical always
  bypasses cooldown; engine batches >3 simultaneous events into a single Telegram
  message. Config: `plugins.yaml` `aggregation_threshold: 3`,
  `escalation_cooldown_s: 120.0`.
- **F21 — Alarm hysteresis deadband**: `AlarmEvaluator.evaluate()` gains `is_active`
  + `active_channels: frozenset` params. Deadband filters to originally-triggering
  channels only (Codex fix: non-triggering channel could inherit alarm state).
- **F22 — Severity upgrade in-place**: `WARNING→CRITICAL` on same `alarm_id`
  (`AlarmEvent.level` mutation, `frozen=False`). `SEVERITY_UPGRADED` history event
  for audit. Prevents duplicate operator notifications per physical anomaly.

### Independent features (F19, F23, F24, F25)
- **F19 — ExperimentSummaryWidget enrichment**: clickable DOCX/PDF labels via
  `_ClickableLabel` + `QDesktopServices`; top-3 alarm names by frequency;
  per-channel min/max/mean stats (`limit_per_channel=50000` covers ~7 h at 0.5 s
  cadence; Codex P2 fix from 5000 which covered only ~42 min).
- **F23 — RateEstimator measurement timestamp**: `safety_manager._collect_loop` now
  uses `reading.timestamp.timestamp()` instead of `time.monotonic()` (dequeue time),
  giving correct dT/dt estimates under queue backlog.
- **F24 — Interlock acknowledge ZMQ command**: `interlock_acknowledge` action exposes
  `InterlockEngine.acknowledge(name)` — transitions `TRIPPED→ARMED`, `KeyError` for
  unknown name. Operator re-arms interlock without process restart.
- **F25 — SQLite WAL startup gate**: `_check_sqlite_version()` raises `RuntimeError`
  on affected versions `[3.7.0, 3.51.3)` (March 2026 WAL corruption bug).
  `CRYODAQ_ALLOW_BROKEN_SQLITE=1` bypasses with `WARNING` log. Module flag
  `_SQLITE_VERSION_CHECKED` prevents repeated checks per process. Backport whitelist
  refinement deferred to F26 (XS).

### Doc/process (Phase A — direct to master)
- ORCHESTRATION v1.3: §14.6 hallucination verification + §15 multi-model dispatch
  realities (6 subsections on routing, delays, budget, anti-patterns).
- multi-model-consultation skill v1.1: §2.1 calibrated routing matrix, §3.7
  formation pattern, §6 budget updates, §7.8 anti-pattern (high-reasoning over-flag).
- HF3: `update_target()` docstring — slew-rate convergence clarification (Codex T2
  re-run CONDITIONAL→PASS).
- Plugin disposition: oh-my-claudecode auto-load disabled for CryoDAQ engine process.

### Tests
- 39 new tests across F19-F25 (16 F19, 5 F20, 7 F21, 3 F22, 1 F23, 3 F24, 5 F25).
- Alarm cluster targeted: 60 passed.
- Misc cluster targeted: 13 passed.
- All pass including SQLite 3.50.4 regression fix (fixture teardown isolation).

### Tags
- `v0.43.0` → `678aa64c` (misc-cluster merge)
- alarm-cluster merge → `e0a8f140`

### Selected commits in this release
- `2e5f34b` — HF3: update_target docstring slew-rate clarification
- `aaaa38f` — multi-model-consultation v1.1 routing matrix
- `4115703` — ORCHESTRATION v1.3
- `20b464b` — plugin disposition (oh-my-claudecode disabled)
- `42f681d` — F20+F21+F22 alarm cluster
- `4716219` — F22 severity-upgrade in-place documentation (architect annotation)
- `673a428` — F19+F23+F24+F25 misc cluster

## [0.42.0] — 2026-04-29 — Safety hotfix HF1+HF2

### Highlights
- **HF1**: `update_target()` docstring clarification — verified delayed-update design. GLM's CRITICAL finding refuted by hypothesis verification: P=const regulation loop in `Keithley2604B.read_channels()` reads `runtime.p_target` every poll cycle, recomputes `target_v = sqrt(p_target * R)`, and issues SCPI. `update_target()` is delayed-update (≤1 s), not a no-op. Direct SCPI write explicitly rejected to preserve slew-rate limiting and compliance checks.
- **HF2**: `keithley_emergency_off` + `keithley_stop` added to `_SLOW_COMMANDS` in `zmq_bridge.py`. These safety commands now use `HANDLER_TIMEOUT_SLOW_S` (30 s) instead of the fast 2 s envelope. USBTMC slow-path cancellation during fault events is no longer possible.

### Source
2026-04-29 overnight metaswarm session — Task A architectural blind spots audit (6 models × 4 tasks). GLM and Codex flagged these findings. Both findings architect-verified against actual source code before any fix applied.

Verification ledger: `artifacts/handoffs/2026-04-29-task-a-verification.md`

### Changed
- `src/cryodaq/core/safety_manager.py` — `update_target()` docstring documents delayed-update design and rejected alternative (direct SCPI write)
- `src/cryodaq/core/zmq_bridge.py` — `"keithley_emergency_off"` and `"keithley_stop"` added to `_SLOW_COMMANDS` frozenset with explanatory comment

### Tests
- 2 new: `test_slow_commands_covers_safety_critical_hardware_ops` (zmq_bridge), `test_update_target_updates_runtime_p_target_immediately` (safety_manager)
- Full suite: 1931 passed, 4 skipped, 0 failures

### Known Issues
- 5 deferred Task A findings added to ROADMAP as F21–F25 (not implemented in this release): hysteresis deadband (#1.3), F10 escalation (#1.4), RateEstimator timestamp (#1.7), interlock re-arm (#1.8), SQLite WAL gate (#1.10)

### Tags
- `v0.42.0` → merge commit `751b4cf`

### Selected commits in this release
- `189c4b7` fix(safety): HF1 update_target docstring + HF2 emergency_off slow timeout
- `751b4cf` merge: HF1+HF2 safety hotfix (Task A verified findings)

---

## [0.41.0] — 2026-04-29 — F10 sensor diagnostics → alarm integration

### Highlights

F10 complete. Sensor diagnostics anomaly events now flow through Alarm
Engine v2: warning alarm at 5 min sustained anomaly, critical at 15 min,
auto-clear when channel returns to ok. Telegram dispatch for diagnostic
alarms follows the existing `_alarm_v2_tick` pattern.

Implementation: 3-cycle overnight Sonnet batch with Codex audit per cycle.
Gemini quota exhausted overnight (MODEL_CAPACITY_EXHAUSTED on all 4
dispatches); architect performed manual structural pass for Cycle 3.

Spec deviation ratified: alarm-publishing config lives in `plugins.yaml`
(existing `sensor_diagnostics` convention) rather than `alarms_v3.yaml`.

F20 added for future polish: Telegram notification aggregation for
simultaneous multi-channel diagnostic alarms + per-channel escalation
cooldown. Not blocking; in normal ops ≤16 channels, simultaneous
criticals indicate genuine catastrophe where flood is preferable to
silence.

### Added

- `SensorDiagnosticsEngine.__init__` gains `alarm_publisher`,
  `warning_duration_s` (default 300 s), `critical_duration_s`
  (default 900 s) parameters
- `_AnomalyState` dataclass for per-channel sustained-anomaly tracking
  (monotonic clock; one-shot publish guards per severity level)
- `_health_to_status()` bridge maps health_score (0–100) → ok / warning
  / critical (spec called for status enum; existing engine uses numeric
  health score)
- `SensorDiagnosticsEngine.update()` now returns `list[AlarmEvent]` of
  newly published events so engine tick can dispatch Telegram
- `AlarmStateManager.publish_diagnostic_alarm(channel_id, severity,
  age_seconds)` — idempotent per channel, creates alarm in same shape as
  rule-evaluated alarms; inherits ACK workflow
- `AlarmStateManager.clear_diagnostic_alarm(channel_id)` — removes from
  active and records CLEARED in history
- Engine wiring: `alarm_v2_state_mgr` injected as `alarm_publisher` into
  `SensorDiagnosticsEngine`; graceful degradation when
  `alarm_publishing_enabled: false`
- `_sensor_diag_tick` dispatches Telegram for returned diagnostic
  AlarmEvents via `_alarm_dispatch_tasks` (strong-ref management)
- `config/plugins.yaml` sensor_diagnostics block: `alarm_publishing_enabled`,
  `warning_duration_s`, `critical_duration_s`, `notify_telegram`
- 17 new tests: 11 unit (Cycle 1, sensor_diagnostics publishing) +
  4 unit (Cycle 2, AlarmStateManager) + 2 integration (Cycle 3, pipeline)
- Vault: 6 new subsystem notes (Analytics view, F4 lazy replay, Web
  dashboard, Cooldown predictor, Experiment manager, Interlock engine)

### Test baseline

Pre: 0.40.0 — ~300 tests
Post: 81 passing (+17 new), 0 regressions

### Tags

- `v0.41.0` — see closing commit below

### Closing commit

See `merge: F10 Cycle 3` on master.

---

## [0.40.0] — 2026-04-29 — F3 Analytics widgets data wiring

### Highlights

F3 + F4 features complete. 5-cycle overnight Opus batch with dual-verifier
audits per cycle. 86 new tests, ~1000 LOC. All four analytics widgets
wired; W4 r_thermal kept as placeholder pending F8.

Architecture fix caught by audit: `active.get("id")` → `active.get("experiment_id")`
in `MainWindowV2` cache invalidation — `ExperimentInfo.to_payload()` emits
`"experiment_id"`, not `"id"`.

F19 added to ROADMAP for deferred W3 enrichment (channel min/max, top-3
alarms, clickable artifact links).

Closing commit: 3b626a2 (merge: F3 Cycle 5).

### Added

- **F3 analytics data wiring — W1…W3 + F4 lazy replay** — Five-cycle batch
  completing Phase III.C analytics placeholder → live data wiring:
  - **W5 / F4** (Cycle 1): shell-level F4 lazy-open snapshot replay.
    `MainWindowV2._push_analytics` caches last-value per setter; replayed into
    `AnalyticsView` on lazy open. 19 new tests. (`feat/f3-cycle1`, merged)
  - **W1 `temperature_trajectory`** (Cycle 2): `TemperatureTrajectoryWidget` —
    multi-group `pg.GraphicsLayoutWidget` with per-group PlotItems for
    independent Y-axis scaling. Fetches 7-day history via `readings_history`
    ZMQ command on construction. 14 new tests. (`feat/f3-cycle2`)
  - **W2 `cooldown_history`** (Cycle 3): `CooldownHistoryWidget` — one-shot
    scatter plot of past cooldown durations. New `cooldown_history_get` engine
    command mines JSON metadata files per experiment. `list_archive_entries`
    wrapped in `asyncio.to_thread` (event-loop safety). 21 new tests.
    (`feat/f3-cycle3`)
  - **W3 `experiment_summary`** (Cycle 4): `ExperimentSummaryWidget` — header,
    duration, phase breakdown, alarm count (via existing `alarm_v2_history`
    command), artifact links. `set_experiment_status` setter added to
    `AnalyticsView` + `MainWindowV2` routing. 23 new tests. (`feat/f3-cycle4`)
  - **Cycle 5**: W4 `r_thermal_placeholder` text updated (F8 dependency note);
    cross-widget lifecycle integration tests (`tests/integration/`, 9 tests);
    CHANGELOG + ROADMAP updated; F19 added to ROADMAP. (`feat/f3-cycle5`)
- **New engine command `cooldown_history_get`** — async handler
  `_run_cooldown_history_command`; reads JSON metadata files, returns past
  cooldown durations with T1 boundary temperatures.
- **F19 added to ROADMAP** — deferred W3 enrichment items (channel min/max,
  top-3 alarm names, clickable artifact links).

### Fixed

- **`active.get("experiment_id")` cache invalidation** — pre-existing bug
  where `active.get("id")` always returned `None` (key mismatch with
  `ExperimentInfo.to_payload()` which emits `"experiment_id"`). Analytics
  snapshot never invalidated on experiment boundary. Caught by F3-Cycle4
  audit. Applied to both `_on_experiment_status_received` and
  `_active_experiment_id` in `main_window_v2.py`.

### Known gaps (deferred to F19)

- W3 channel min/max/mean table per critical channel
- W3 top-3 most-triggered alarm names
- W3 clickable artifact links via `QDesktopServices`
- W4 (`r_thermal_placeholder`) remains placeholder — depends on F8

### Test baseline

86 new tests across F3 cycles. Full suite green on master after all 5 merges.
Pre-existing failures: timezone-drift in `test_experiment_overlay.py` (known),
flaky ZMQ timing test (passes in isolation).

- **`.cof` Chebyshev coefficient export** — `export_curve_cof()` added to
  `CalibrationStore`. Portable text format: per-zone raw Chebyshev
  coefficients re-evaluatable via `numpy.polynomial.chebyshev.chebval()`
  without CryoDAQ schema dependency.
  (`feat(calibration)` `0fed332`, `fix(cof)` `d0e1c7f`)

### Removed

- **`.330` calibration export removed** — `export_curve_330()` deleted;
  `import_curve_file()` rejects `.330` suffix with `ValueError`.
  Existing `.330` files in production data trees are NOT auto-migrated;
  use manual CSV read or `git restore` for legacy access.
  `engine.py` `calibration_curve_export` action updated: `curve_330_path`
  → `curve_cof_path`; `points` arg dropped.
  GUI calibration overlay updated: `.330` import button removed, `.330`
  export button replaced with `.cof`.
  (architect decision 2026-04-25; `0fed332`, `d0e1c7f`, merge `097a26d`,
  GUI `ba6b997`, `b254de2`)

---

## [0.39.0] — 2026-04-27 — B1 ZMQ idle-death fixed (H5 confirmed)

### Highlights

Closes the 7-day B1 investigation. Root cause: `asyncio.wait_for(socket.recv(),
timeout=1.0)` cancels the inner pyzmq coroutine every second; after ~50
cancellations, libzmq reactor state wedges the REP socket permanently.
Fix: `poll(timeout=1000)` + conditional `recv()` after `POLLIN`.

### Fixed

- `fix(zmq)` `1f88d2e` — `ZMQCommandServer._serve_loop` and
  `ZMQSubscriber._receive_loop` replaced with poll+recv pattern.
  Verified: macOS 180/180 commands clean; Ubuntu lab PC verified.

### Added

- `feat(diag)` `5e7eeac` — `tools/diag_zmq_direct_req.py`: direct REQ to
  engine REP bypassing bridge subprocess. D3 experiment tool proving
  engine-side causation. Regression gate: clean 180s = pass.

### Investigation closed

- **B1 ZMQ idle-death** — H5 CONFIRMED + FIXED. See
  `docs/bug_B1_zmq_idle_death_handoff.md` and
  `docs/decisions/2026-04-27-d{1,2,3,4}-*.md`.

### Closing commit

`21a3a28` — release: v0.34.0 (retroactively relabelled v0.39.0)

---

## [0.38.0] — 2026-04-27 — Production hardening: alarms, drivers, launcher

### Highlights

Production hardening from the overnight Codex batch (Codex-03/04/05).
Tightens alarm_v2 validation, fixes Thyracont probe inconsistency, and
adds clean SIGTERM handling so the engine no longer orphans on
`systemd stop` or Ctrl+C.

### Fixed

- `fix(alarms)` `1869910` — alarm_v2 threshold validation rejects
  missing/wrong-type `threshold` fields; eliminates `KeyError` log spam.
- `fix(thyracont)` `7230c9f` — V1 probe checksum-validates on connect,
  matching read-path behavior; prevents silent NaN-forever on
  non-VSP63D hardware.
- `3215580` — channels.yaml header recovered from stale state.

### Added

- `feat(launcher)` `9a8412e` — SIGTERM/SIGINT handler; engine subprocess
  receives SIGTERM and exits cleanly on systemd stop / Ctrl+C.

### Closing commit

`9a8412e` — feat(launcher): SIGTERM/SIGINT handler prevents engine orphan on shutdown

---

## [0.37.0] — 2026-04-24 — R1 probe retry repair

### Highlights

Bounded-backoff retry in `_validate_bridge_startup()` repairs the
b2b4fb5 race: the single-shot probe rejected healthy ipc:// bridges
during engine bind-startup, falsely attributing IV.7's failure to the
transport layer.

### Fixed

- `fix(diag)` `c3f4f86` — `_validate_bridge_startup()` in
  `diag_zmq_b1_capture.py` now retries with bounded exponential backoff
  instead of failing on the first non-OK response.

### Closing commit

`cabd854` — docs: Q4 equivalence check synthesis + D1 close

---

## [0.36.0] — 2026-04-21 — B1 investigation tooling (merged 2026-04-24)

> Authored 2026-04-21 on `codex/safe-merge-b1-truth-recovery` branch,
> merged to master 2026-04-24. Tag follows topological order, not
> authorship date.

### Highlights

Reusable diagnostic helpers and canonical B1 capture CLI for structured
ZMQ bridge investigation. JSONL output enables post-hoc analysis and
cross-run comparison.

### Added

- `8b9ce4a` — `tools/_b1_diagnostics.py`: `bridge_snapshot` +
  `direct_engine_probe` reusable helpers.
- `cc090be` — `tools/diag_zmq_b1_capture.py`: canonical B1 capture CLI
  with JSONL output and structured timing.
- `40553ea`, `033f87b` — alignment passes syncing helpers and CLI with
  bridge API changes.
- `62314be` — record direct probe timeouts for post-analysis.

### Closing commit

`62314be` — tools: record direct probe timeouts in B1 capture CLI

---

## [0.35.0] — 2026-04-24 — Agent orchestration governance

### Highlights

Governance infrastructure after the 2026-04-21 agent-swarm chaos
(duplicate branches, root-markdown flood, no-leader multi-agent drift).
Establishes the CC-centric swarm model with explicit STOP discipline,
autonomy band, and artifact layout rules.

### Added

- `5286fa2` — `docs/ORCHESTRATION.md` v1.1: CC-centric role matrix,
  branch discipline, artifact layout, STOP discipline (§13), autonomy
  band (§13.5).
- `9a1a100` — `.claude/skills/`: multi-model-consultation +
  negative-space skills.
- `587bea8` — `.gitignore`: exclude agent orchestration workspaces
  (`.omc/`, `.swarm/`, `.audit-run/`, `agentswarm/`, `.worktrees/`).

### Closing commit

`af77095` — recon: safe-merge branch commit classification

---

## [0.34.0] — 2026-04-20 — ZMQ cmd-plane hardening + field fixes

### Highlights

IV.6 ZMQ command-plane hardening: ephemeral REQ-per-command pattern +
launcher command-channel watchdog. Field fixes from the 2026-04-20
Ubuntu lab PC session.

### Today — 2026-04-20 session (handoff → GLM-5.1)

This is a tight working record, not a formal release. Full
handoff context is in `HANDOFF_2026-04-20_GLM.md`; next formal
release is `0.34.0` once B1 is resolved via IV.7.

**Fixed / shipped:**

- `aabd75f` — `engine: wire validate_checksum through Thyracont
  driver loader`. Fixes TopWatchBar pressure em-dash on Ubuntu lab
  PC when VSP206 hardware is connected. `_create_instruments()`
  was ignoring the YAML key entirely; driver defaulted to strict
  checksum validation regardless of config. One-line loader fix;
  config-side `validate_checksum: false` in
  `instruments.local.yaml` now actually applies.

- `74dbbc7` — `reporting: xml_safe sanitizer for python-docx
  compatibility`. Fixes `experiment_generate_report` failure when
  real Keithley 2604B is connected (VISA resource contains `\x00`
  per NI-VISA spec; python-docx rejects XML 1.0 control chars).
  New `src/cryodaq/utils/xml_safe.py` with 10 unit tests. Applied
  at all `add_paragraph()` / `cell.text` sites in
  `src/cryodaq/reporting/sections.py`. `core/experiment.py:782`
  logger upgraded from `log.warning` to `log.exception` — future
  report-gen failures will include tracebacks (how this bug
  survived: only the exception message was ever logged).

- `be51a24` — `zmq: ephemeral REQ per command + cmd-channel
  watchdog (IV.6 partial B1 mitigation)`. Landed the full
  Codex-proposed B1 fix plan: per-command ephemeral REQ socket in
  `zmq_subprocess.cmd_forward_loop`, launcher-side
  `command_channel_stalled()` watchdog in `_poll_bridge_data`,
  `TCP_KEEPALIVE` reverted on command + PUB paths (kept on
  `sub_drain_loop` as orthogonal safeguard). 60/60 unit tests
  green, full subtree 1775/1776 (1 pre-existing flaky).
  **Does NOT fix B1 — Stage 3 diag tools still reproduce it.**
  Committed anyway as architectural improvement matching ZeroMQ
  Guide ch.4 canonical reliable req-reply pattern. Codex's
  shared-REQ-state hypothesis falsified by this experiment.

- Config edits on Ubuntu lab PC (some in git, some local):
  - `interlocks.yaml` — `overheat_cryostat` regex tightened from
    `Т[1-8] .*` to `Т(1|2|3|5|6|7|8) .*`. Т4 sensor is physically
    disconnected (reads 380 K open-circuit), was triggering
    `emergency_off` on Keithley during normal operation.
  - `alarms_v3.yaml` — Т4 added to `uncalibrated` and `all_temp`
    channel groups so `sensor_fault` still publishes WARNING
    without hardware lockout.
  - `instruments.local.yaml` — `validate_checksum: false` on
    Thyracont block (per-machine override; NOT in git).

- Operational on Ubuntu lab PC: `ModemManager` disabled
  (was transiently grabbing `/dev/ttyUSB0`).

**Open / known issues carrying into 0.34.0:**

- **B1 still unresolved.** GUI command channel silently dies
  ~30-120 s after bridge startup on both platforms. IV.7 `ipc://`
  transport experiment is the next attempt — spec at
  `CC_PROMPT_IV_7_IPC_TRANSPORT.md`. Workaround in place:
  watchdog cooldown (TBD commit) prevents the IV.6 restart storm
  regression, system works in 60-120 s cycles with single
  restarts between.

- `alarm_v2.py::_eval_condition` raises `KeyError 'threshold'`
  when evaluating `cooldown_stall` composite. One sub-condition
  is missing a `threshold` field. Log spam, not crash. Pending
  mini-fix.

- Thyracont `_try_v1_probe` probe-vs-read inconsistency. Probe
  always succeeds; read checksum-validates. Driver can "connect"
  and emit NaN forever on non-VSP63D hardware. Pending
  hardening fix.

**Infrastructure:**

- Multi-model development stack adopted (2026-04-20 afternoon).
  Anthropic weekly limit exhausted. Claude Code now routes
  through `claude-code-router` proxy to Chutes (GLM-5.1 primary,
  DeepSeek-V3.2 background, Kimi-K2.5 long-context) for the
  coming ~4-5 days. Codex (ChatGPT subscription) and Gemini
  (Google subscription) remain on their own quotas for
  delegation. See `HANDOFF_2026-04-20_GLM.md` for operational
  details and identity-leakage warnings.

### Changed

- **Phase III.C — Phase-aware AnalyticsView rebuild.** Rewrote
  `src/cryodaq/gui/shell/views/analytics_view.py` around a
  2 × 2 QGridLayout (main slot `rowspan=2, colspan=1, col=0`;
  top_right and bottom_right 1/4 each). Layout swaps per experiment
  phase according to a new config file `config/analytics_layout.yaml`
  — preparation → temperature overview; vacuum → прогноз вакуума
  (main), temperature + pressure (right column); cooldown → прогноз
  охлаждения (main); measurement → R_тепл live + keithley power;
  warmup / disassembly have their own mappings; unknown / missing
  phase falls back to temperature + pressure + sensor health.
  New widget registry at
  `src/cryodaq/gui/shell/views/analytics_widgets.py`:
  `TemperatureOverviewWidget` (subscribes to the III.B global time
  controller), `VacuumPredictionWidget` + `CooldownPredictionWidget`
  (wrap III.B `PredictionWidget`), `RThermalLiveWidget`,
  `PressureCurrentWidget` (wraps III.B shared `PressurePlot`),
  `SensorHealthSummaryWidget` (reuses II.4 `SeverityChip`),
  `KeithleyPowerWidget`, plus 4 placeholder cards for the widget IDs
  whose data pipelines are not wired yet. Shell wiring: phase string
  from `current_phase` in `TopWatchBar.experiment_status_received`
  propagates into `AnalyticsView.set_phase` via
  `MainWindowV2._on_experiment_status_received`. Public setters
  preserved (`set_cooldown`, `set_r_thermal`, `set_fault`) plus new
  ones (`set_temperature_readings`, `set_pressure_reading`,
  `set_keithley_readings`, `set_instrument_health`,
  `set_vacuum_prediction`). Data forwarding uses duck-typing — each
  setter iterates active widgets and calls a matching method if
  present; inactive widgets are discarded on layout swap. Last
  pushes are cached and replayed into fresh widgets on phase
  transition so the new layout never starts empty. ACCENT / status
  decoupling (III.A) preserved across new widgets; no widget hits
  the legacy status tier in non-status contexts. Tests: 37 new
  cases across `test_analytics_view_phase_aware.py` (17) and
  `test_analytics_widgets.py` (20) plus 2 new wiring cases in
  `test_main_window_v2_analytics_adapter.py` (9 total). Deletes
  obsolete `test_analytics_view.py` (28 hero/rthermal/vacuum-strip
  geometry cases, rendered meaningless by the rebuild).

- **Phase III.B — GlobalTimeWindow + shared PressurePlot +
  PredictionWidget.** `TimeWindow` enum promoted from dashboard-local
  to `cryodaq.gui.state.time_window` with a
  `GlobalTimeWindowController` singleton. Every historical plot
  subscribes — clicking 1мин / 1ч / 6ч / 24ч / Всё on any plot's
  selector updates every subscribed plot across the app. Prediction
  plots do NOT subscribe; they have their own forward horizon
  (1/3/6/12/24/48ч) with uncertainty bands.
  New shared `cryodaq.gui.widgets.shared.PressurePlot` with
  `ScientificLogAxisItem` — scientific-notation log-Y tick labels
  (fixes the missing Y labels in the compact dashboard pressure
  panel). Dashboard `PressurePlotWidget` now delegates to the shared
  component (composition — `_plot` proxy preserved for the
  dashboard-view `setXLink` wiring). Dashboard `TempPlotWidget`
  migrated to `TimeWindowSelector` — local state removed; single
  broadcast-driven controller is the source of truth.
  New shared `cryodaq.gui.widgets.shared.PredictionWidget` skeleton:
  always-full history + 6-button forward horizon + CI band rendered
  as `FillBetweenItem` with `STATUS_INFO` at ~25 % alpha (neutral
  informational tint, never safety colors). «Через N ч» readout
  updates from interpolated central/lower/upper CI series. Full
  analytics integration deferred to III.C — III.B only ships the
  components + tests. ACCENT decoupling (III.A) preserved: selector
  and horizon buttons render checked state in ACCENT, not STATUS_OK.

- **Phase III.A — DS accent/status decoupling.** Fixed semantic
  collision where `STATUS_OK` (safety-green) rendered UI states
  (selected rows, active tabs, primary buttons, mode badge) and read
  to operators as «this is healthy» when the actual meaning was
  «this is selected / active». Introduced two neutral interaction
  tokens: `SELECTION_BG` (subtle tint for selected rows) and
  `FOCUS_RING` (neutral outline for focused elements). Added to all
  12 bundled theme packs and required by `_theme_loader.REQUIRED_TOKENS`.
  Migrated sites: `_style_button("primary")` helpers in 5 overlays
  (operator_log, archive, calibration, conductivity, keithley) now
  use `ACCENT + ON_ACCENT` instead of `STATUS_OK + ON_PRIMARY`;
  `TopWatchBar` mode badge «Эксперимент» now renders as low-emphasis
  `SURFACE_ELEVATED` chip with `FOREGROUND` text + `BORDER_SUBTLE`
  outline (prior filled `STATUS_OK` pill); `ExperimentCard` mode
  badge mirrors TopWatchBar; «Отладка» keeps `STATUS_CAUTION` colour
  because it IS an operator-attention signal but renders as bordered
  chip; `conductivity_panel` auto-sweep progress chunk migrated to
  `ACCENT`. Per-theme ACCENT recalibrated: `warm_stone` `#4a8a5e`
  (identical to STATUS_OK) → `#b89e7a` warm sand; `taupe_quiet`
  `#4a8a5e` (with obsolete «matches STATUS_OK by design» comment) →
  `#a39482` warm taupe (comment removed); `braun` `#476f20` (olive
  hue ≈90°, violated ≥60° invariant) → `#6a7530` moss-olive ≈70°.
  `default_cool` kept at `#7c8cff` indigo (historical baseline).
  All 9 other themes' ACCENT verified hue-distant from STATUS_OK
  and preserved. New tool `python -m tools.theme_previewer` renders
  all 12 themes side-by-side for architect visual review. ADR 002
  captures the decoupling rationale + hue-distance invariants. No
  operator-facing API changes; all Phase II wiring preserved.

### Removed

- **Phase II.13 legacy cleanup.** All DEPRECATED-marked Phase I-era
  widgets deleted now that their shell-v2 overlay replacements
  (II.1-II.9) ship with Host Integration Contract. Removed source
  files:
  - `src/cryodaq/gui/widgets/alarm_panel.py` (superseded by II.4).
  - `src/cryodaq/gui/widgets/archive_panel.py` (superseded by II.2).
  - `src/cryodaq/gui/widgets/calibration_panel.py` (superseded by II.7).
  - `src/cryodaq/gui/widgets/conductivity_panel.py` (superseded by II.5).
  - `src/cryodaq/gui/widgets/instrument_status.py` (superseded by II.8).
  - `src/cryodaq/gui/widgets/sensor_diag_panel.py` (superseded by II.8 — folded into `InstrumentsPanel._SensorDiagSection`).
  - `src/cryodaq/gui/widgets/keithley_panel.py` (superseded by II.6).
  - `src/cryodaq/gui/widgets/operator_log_panel.py` (superseded by II.3).
  - `src/cryodaq/gui/widgets/experiment_workspace.py` (superseded by II.9; shell overlay retained at `shell/experiment_overlay.py` per Path A).
  - `src/cryodaq/gui/widgets/autosweep_panel.py` (pre-Phase-II DEPRECATED).
  - `src/cryodaq/gui/main_window.py` (v1 tab-based main window; `cryodaq-gui` entry point was already on `MainWindowV2` via `gui/app.py` since Phase I.1).
  Removed test files: 7 legacy widget-specific tests (archive,
  calibration, experiment_workspace, keithley_panel_contract,
  main_window_calibration_integration, operator_log_panel,
  sensor_diag_panel). `widgets/common.py` retained — still consumed
  by non-DEPRECATED widgets (shift_handover, pressure_panel,
  overview_panel, connection_settings, vacuum_trend_panel,
  analytics_panel, channel_editor, temp_panel, experiment_dialogs).

### Changed

- **Phase II.9 ExperimentOverlay harmonized — DS v1.0.1 (Path A).**
  Stage 0 audit of `src/cryodaq/gui/shell/experiment_overlay.py`
  showed the overlay was already DS v1.0.1-compliant (zero forbidden
  tokens, zero emoji, zero hardcoded hex — shipped clean from B.8).
  Path A surgical harmonization delivered the one remaining gap:
  Host Integration Contract. New `set_connected(bool)` method
  disables `_save_btn`, `_finalize_btn`, `_prev_btn`, `_next_btn`
  on engine silence; `_refresh_display` now respects the connected
  flag when re-rendering after `set_experiment`. Default state is
  connected=True (preserves pre-first-tick functionality). Host
  wiring: `MainWindowV2._tick_status` mirrors connection state;
  `_ensure_overlay("experiment")` replays it on first open (same
  pattern as II.4 / II.8 and earlier overlays). Zero engine command
  signature changes, zero callback interface changes, zero layout
  reordering — Path A diff is mechanically reversible. Path choice
  rationale (Path A over Path B) recorded in
  `docs/design-system/cryodaq-primitives/experiment-panel.md`.
  Tests: 7 new cases in `test_experiment_overlay.py` (17 total) +
  6 new wiring cases.

- **Phase II.8 InstrumentsOverlay (cards + SensorDiag) — DS v1.0.1.**
  Merged two legacy modules (`instrument_status.py` +
  `sensor_diag_panel.py`) into a single overlay at
  `src/cryodaq/gui/shell/overlays/instruments_panel.py`. Both sections
  preserved verbatim: instrument card grid with adaptive liveness
  (median × 5 timeout, 10 s floor, 300 s default, 3-reading adaptive
  threshold), sensor diagnostics table with 10 s polling of
  `get_sensor_diagnostics`. Unicode circle (⬤) in card status
  indicator replaced by painted `_StatusIndicator` (QFrame with QSS
  `border-radius` — no glyph dependency). Summary emoji (✓ ⚠ ✘)
  replaced by `SeverityChip` widgets imported from the II.4 alarm
  overlay, using DS status tokens and Russian labels («N ОК / N ПРЕД
  / N КРИТ»). Hardcoded `QColor(r, g, b, a)` row tints replaced by
  `QColor(theme.STATUS_*)` + alpha. `apply_panel_frame_style` helper
  and deprecated `TEXT_MUTED` / `TEXT_PRIMARY` tokens removed. Host
  Integration Contract wired: `MainWindowV2._tick_status` connection
  mirror + `_ensure_overlay("instruments")` replay. Adaptive liveness
  constants NOT tuned — verified against real instruments. Legacy
  widgets marked DEPRECATED in module docstrings; deletion slated
  for Phase II.13. Tests: 41 overlay cases + 7 host-wiring cases.

- **Phase II.4 AlarmOverlay rebuilt (K1 safety surface).** New
  overlay at `src/cryodaq/gui/shell/overlays/alarm_panel.py` replaces
  the legacy v1 widget in `MainWindowV2`. Dual-engine layout preserved:
  v1 threshold-based table (fed via `on_reading` + `metadata["alarm_name"]`
  filter) and v2 YAML-driven phase-aware table (populated via 3 s
  polling of `alarm_v2_status`). Emoji severity icons (🔴 / 🟡 / 🔵)
  replaced by in-module `SeverityChip` widget using DS status tokens
  (`STATUS_FAULT` / `STATUS_WARNING` / `STATUS_INFO`) with Russian short
  labels (`КРИТ` / `ПРЕД` / `ИНФО`). ACK button styling migrated from
  deprecated `STONE_400` / `TEXT_INVERSE` to `SURFACE_MUTED` /
  `MUTED_FOREGROUND` (disabled) and status-colored active state.
  Host Integration Contract wired: `MainWindowV2._tick_status` mirrors
  connection state into the overlay (pauses v2 polling + disables
  ACK buttons on disconnect). `_dispatch_reading` routes readings
  through `on_reading`. `v2_alarm_count_changed = Signal(int)`
  signature preserved — still consumed by `TopWatchBar.set_alarm_count`.
  New public API: `update_v2_status(payload)`, `get_active_v1_count()`,
  `get_active_v2_count()`. Fail-OPEN preserved (disconnect keeps rows
  visible; engine errors preserve last-known v2 map). Legacy widget
  at `src/cryodaq/gui/widgets/alarm_panel.py` marked DEPRECATED in
  its module docstring; slated for deletion in Phase II.13. Zero legacy
  tokens / zero emoji / zero hardcoded hex (pre-commit gates pass).
  Tests: 51 overlay cases + 7 host-wiring cases.

- **Phase II.7 CalibrationOverlay rebuilt + command wiring.**
  Three-mode overlay at
  `src/cryodaq/gui/shell/overlays/calibration_panel.py` replaces the
  legacy v1 widget. QStackedWidget (Setup / Acquisition / Results)
  auto-switch preserved verbatim (3 s engine poll on
  `calibration_acquisition_status`). CoverageBar migrated from
  hardcoded hex (`#2ECC40` / `#FFDC00` / `#FF851B` / `#333333`) to
  DS tokens (dense → STATUS_OK, medium → STATUS_CAUTION, sparse →
  STATUS_WARNING, empty → MUTED_FOREGROUND). **K3 mandate completed:**
  all six previously-unwired import / export / runtime-apply buttons
  now dispatch real engine commands via `ZmqCommandWorker`:
  `calibration_curve_import` (with `QFileDialog.getOpenFileName`
  picker per format), `calibration_curve_export` (with
  `QFileDialog.getSaveFileName` picker, format-specific path parameter),
  `calibration_runtime_set_global`,
  `calibration_runtime_set_channel_policy` (chained via
  `calibration_curve_lookup` to resolve `curve_id`). Acquisition
  widget's `_experiment_label` / `_elapsed_label` now populated from
  poll result (v1 declared them but never wrote). Public accessors
  `get_current_mode()` / `is_acquisition_active()` added for future
  finalize guards. Host Integration Contract wired:
  `MainWindowV2._tick_status` connection mirror +
  `_ensure_overlay("calibration")` replay; readings routing (shell
  dispatches `unit=="K"` to overlay, overlay filters for
  `_raw` / `sensor_unit` in acquisition mode) preserved from v1. Zero
  legacy tokens / zero emoji / zero hardcoded hex (pre-commit gates
  clean). Legacy widget at
  `src/cryodaq/gui/widgets/calibration_panel.py` marked DEPRECATED;
  removal in Phase III.3.

### Added

- **Six new themes: signal, instrument, amber (dark); gost, xcode,
  braun (light).** STATUS palette hue-locked with lightness unlocked
  for light substrates per ADR 001
  (`docs/design-system/adr/001-light-theme-status-unlock.md`). Dark
  packs continue to ship the verbatim STATUS hex set; new light packs
  (gost / xcode / braun) ship a shifted-lightness variant that
  preserves hue and restores WCAG AA (≥4.5:1) contrast against their
  light `SURFACE_CARD`. Semantic identity («amber = WARNING, red =
  FAULT») preserved 1:1 across mode switches. Settings → Тема menu
  now surfaces all 12 bundled packs in a dark-group / light-group
  layout with a visual separator between groups. Full rationale,
  per-pack design axis, metrics, and pre-release smoke points:
  `docs/design-system/HANDOFF_THEMES_V2.md`.

### Changed

- **Phase II.5 ConductivityOverlay rebuilt.** Full-featured thermal
  conductivity surface in
  `src/cryodaq/gui/shell/overlays/conductivity_panel.py` replaces the
  legacy v1 widget. Auto-sweep state machine preserved verbatim
  (`idle` / `stabilizing` / `done`, 1 Hz tick, `SteadyStatePredictor`
  driving settling detection with `percent_settled` threshold +
  `min_wait` gate, Keithley power stepping via `ZmqCommandWorker`
  against `keithley_set_target` / `keithley_stop` — unchanged from v1).
  R/G table (11 columns with ИТОГО summary row), stability indicator
  (`dT/dt > 0.01 К/мин` threshold), steady-state banner adapting to
  predictor output, chain selection with reorder buttons + manual
  CSV export. Flight recorder schema preserved (18 columns,
  `utf-8-sig`, `get_data_dir() / conductivity_logs /
  conductivity_<ts>.csv`). Public accessors
  `get_auto_state() -> str` + `is_auto_sweep_active() -> bool`
  replace direct `_auto_state` attribute access for external finalize
  guards (II.9 follow-up wiring). DS v1.0.1 tokens throughout — zero
  legacy tokens, zero emoji, zero hardcoded hex colors (plot pens come
  from `PLOT_LINE_PALETTE` via `series_pen` indexing). Host
  Integration Contract wired: `MainWindowV2._tick_status` connection
  mirror + `_ensure_overlay("conductivity")` replay; readings routing
  (T-prefix + `/smu*/power`) unchanged from v1 shell contract.
  Plugin-duplication concern from project memory: investigated — no
  engine-side R/G publisher exists (grep returns zero matches),
  GUI-side compute is the only path. Legacy widget at
  `src/cryodaq/gui/widgets/conductivity_panel.py` marked DEPRECATED;
  removal in Phase III.3.

- **Phase II.2 ArchiveOverlay rebuilt + K6 bulk export migration.**
  Full-featured experiment archive surface in
  `src/cryodaq/gui/shell/overlays/archive_panel.py` replaces the legacy
  v1 widget. Filter bar (template combo, operator / sample text, start
  / end date range, report presence, sort), 9-column list table with
  FONT_MONO timestamps, details panel with summary / metadata / notes /
  stats / runs / artifacts / results views, action buttons
  (folder / PDF / DOCX / regenerate). K6 mandate: bulk CSV / HDF5 /
  Excel export migrated from the legacy `main_window.py` File menu
  into a dedicated «Экспорт данных» card at the bottom of the overlay
  — `MainWindowV2` has no menu bar, so this was the only path to
  restore global data export. Exports run in a `QThread` worker that
  wraps the existing `cryodaq.storage.{csv_export,hdf5_export,xlsx_export}`
  classes verbatim (no exporter re-implementation); GUI never blocks.
  Emoji pictograms `📊` / `📋` in the legacy artifact view replaced
  with ASCII bracketed tags `[ДАННЫЕ]` / `[ИЗМЕРЕНИЯ]` / `[УСТАВКИ]`
  per RULE-COPY-005; report / data column markers switched from ✓ to
  «Да» for the same reason. DS v1.0.1 tokens exclusively. Host
  Integration Contract wired via `MainWindowV2._tick_status` connection
  mirror + `_ensure_overlay("archive")` replay; `on_reading` is a
  contract no-op (no engine experiment-finalize broker event). Legacy
  widget at `src/cryodaq/gui/widgets/archive_panel.py` marked
  DEPRECATED; removal in Phase III.3. `main_window.py` File menu
  export actions remain intact for the transitional legacy path.

- **Phase II.3 OperatorLog overlay rebuilt.** Full-featured operator
  journal surface in `src/cryodaq/gui/shell/overlays/operator_log_panel.py`
  replaces the legacy v1 widget. Timeline grouped by calendar day,
  quick filter chips (all / current experiment / 8h / 24h), client-side
  text / author / tag filters with 250 ms debounce, composer card with
  tags + experiment binding, append-only with optimistic prepend on
  `log_entry` success, load-more pagination (50-entry steps), DS
  v1.0.1 compliant tokens throughout. Composer author persists via
  `QSettings("FIAN", "CryoDAQ")` key `last_log_author`. Host
  integration contract: `MainWindowV2._tick_status()` mirrors
  connection state, `_on_experiment_status_received()` pushes current
  experiment id, `_ensure_overlay("log")` replays cached state on lazy
  open. Legacy widget at `src/cryodaq/gui/widgets/operator_log_panel.py`
  marked DEPRECATED; removal in Phase III.3. `QuickLogBlock`
  (dashboard) unchanged.

- **Phase II.6 Keithley overlay rebuilt.** Replaces the dead B.7
  mode-based shell overlay (never wired into `MainWindowV2`) and
  supersedes the legacy v1 widget surface visible via Ctrl+K. Full
  power-control semantics matching the engine ZMQ API (`p_target` +
  `v_comp` + `i_comp` only; no `mode=current/voltage`). Per channel:
  P target / V compliance / I compliance `QDoubleSpinBox` with 300 ms
  debounce, 4 live readouts (V / I / R / P) in Fira Mono with tabular
  figures, 2×2 rolling plot grid (V / I / R / P), state badge
  (ВЫКЛ / ВКЛ / АВАРИЯ) driven by
  `analytics/keithley_channel_state/{smua,smub}`. Panel-level «Старт A+B»
  / «Стоп A+B» / «АВАР. ОТКЛ. A+B» (single confirmation dialog for
  A+B emergency), time-window toolbar (10м / 1ч / 6ч) shared across
  channels, safety gate label, connection indicator, transient status
  banner. Design System v1.0.1 compliant — legacy `TEXT_PRIMARY` /
  `QUANTITY_*` tokens replaced throughout; plots use
  `apply_plot_style()` and `PLOT_LINE_PALETTE[0]` for smua,
  `PLOT_LINE_PALETTE[1]` for smub. Stale detection applies only when
  channel state is `"on"`. Emergency confirmation uses
  `QMessageBox.warning` per RULE-INTER-004 destructive variant.
  MainWindowV2 now imports the overlay from
  `cryodaq.gui.shell.overlays.keithley_panel`. Legacy v1 widget at
  `src/cryodaq/gui/widgets/keithley_panel.py` marked DEPRECATED;
  removal scheduled for Phase III.3. K4 custom-command popup (FU.4)
  and HoldConfirm 1 s hold for emergency buttons (FU.5) deliberately
  deferred. Tests: 30 new cases in
  `tests/gui/shell/overlays/test_keithley_panel.py`.

### Добавлено

- **Runtime theme switcher — 6 bundled theme packs.**
  GUI color tokens now load at import time from
  `config/themes/<selected>.yaml` via `src/cryodaq/gui/_theme_loader.py`.
  Bundled packs: `default_cool` (pre-switcher look), `warm_stone` (new
  default — Pantone Warm Gray dark), `anthropic_mono` (brand terracotta),
  `ochre_bloom` (Ableton Ochre, olive accent), `taupe_quiet` (subtle
  warm shift with forest accent), `rose_dusk` (dusty rose, late-night).
  Selection persisted in `config/settings.local.yaml` (gitignored).
  «Настройки → Тема» menu in the launcher offers radio-exclusive
  selection; confirmation dialog warns the GUI restarts in ~1 s while
  engine and data recording continue in the detached engine subprocess.
  The launcher re-execs itself via `os.execv` on theme change — no
  `importlib.reload` cascade (fragile with Qt widget trees and
  module-level pyqtgraph config). New design token `COLD_HIGHLIGHT`
  for cryogenic-channel accent surfaces.

- **Phase I.1 — Overlay Design System primitives (foundational shell).**
  ModalCard (centered card + backdrop dim + 3 close mechanisms),
  DrillDownBreadcrumb (sticky top bar with back navigation),
  BentoGrid (12-column container for Bento tile layout).
  Located at `src/cryodaq/gui/shell/overlays/_design_system/`.
  No application to existing overlays in this block — Phase II applies these
  primitives systematically. Visual showcase at
  `_design_system/_showcase.py` for review before Phase I.2
  (BentoTile + ExecutiveKpi + DataDenseTile + LiveTile).

### Изменено

- **`src/cryodaq/gui/theme.py` — color tokens load from YAML pack at import.**
  Module-level color constants (BACKGROUND, SURFACE_PANEL, ACCENT, status
  tiers, accent scale, text variants) are now read from the active theme
  pack via `_theme_loader.load_theme()`. Non-color tokens (typography,
  spacing, layout, radius, motion, plot palette, legacy STONE_* unique
  stops) remain hardcoded — they do not theme. Downstream consumers still
  use the same `from cryodaq.gui import theme; theme.ACCENT` API.

- **Status palette — one-time semantic refresh (LOCKED across all themes).**
  `STATUS_CAUTION` shifts from `#c47a30` (amber) to `#b35a38` (red-orange)
  to be clearly distinct from `STATUS_WARNING` (`#c4862e`); `STATUS_INFO`
  `#4a7ba8` → `#6490c4` for slightly higher legibility on dark surfaces;
  `COLD_HIGHLIGHT` `#5b8db8` → `#7ab8c4` for better cryogenic-channel
  differentiation. These values are identical across every bundled pack
  including `default_cool` — safety semantics do not shift with style,
  and the refresh is a deliberate improvement, not a regression. Verified
  by `tests/gui/test_theme_loader.py::test_status_palette_identical_across_all_themes`.

- **`apply_panel_frame_style` callers strip GitHub-Primer-dark hex overrides.**
  9 call-sites in `widgets/` (sensor_diag_panel, overview_panel,
  experiment_workspace mode/phase frames, shift_handover, keithley_panel,
  vacuum_trend_panel) previously pinned cold-gray background/border hexes
  (`#11151d` / `#30363d` / `#141821` etc.) that bypassed theme.py and
  prevented theme packs from taking effect. They now inherit
  `theme.SURFACE_PANEL` / `theme.BORDER_SUBTLE` defaults. Semantic hexes
  (debug-panel amber, group-box status accents, `_set_bg` heat-tier
  cases) deliberately retained pending proper STATUS_* tokenization.

### Исправлено

- **Phase I.1 modal layout regression after visual fix round.**
  ModalCard again uses an in-layout chrome row instead of absolute close-button
  positioning, card height once more respects `max_height_vh_pct`, side
  backdrop margins remain visible, and inner content padding is explicit so
  breadcrumb and tiles do not touch the card border. Added regression tests
  for side margins and max-height clamping.

- **Phase UI-1 v2 Block B.6** — ModeBadge widget в TopWatchBar zone 2.
  Показывает текущий AppMode (ЭКСПЕРИМЕНТ / ОТЛАДКА). DEBUG state
  использует amber attention styling потому что режим отключает
  создание архивных записей и отчётов. Badge скрыт пока нет backend
  status (per product rule R1). Закрывает Strategy R1 mode visibility
  safety gap.
- **`src/cryodaq/core/phase_labels.py`** — канонические русские метки
  для ExperimentPhase enum. Единый source of truth для TopWatchBar,
  PhaseAwareWidget и ExperimentWorkspace. Закрывает Strategy R9.
- **B.6.1 hotfix:** Regression-тесты для ModeBadge через full handler
  path `_on_experiment_result` (с и без active_experiment). L8 lesson.
- **B.8.0.2 — ExperimentOverlay + NewExperimentDialog full rebuild.**
  NewExperimentDialog: templates dropdown from backend, operator/sample/
  cryostat autocomplete from QSettings, dynamic custom fields per
  template, name auto-suggest, full legacy payload (template_id, sample,
  cryostat, description, notes, custom_fields). ExperimentOverlay:
  phase pills с past durations + current 2px STATUS_OK highlight,
  prev/next navigation buttons, КАРТОЧКА column (editable sample/
  описание/заметки/custom fields + Сохранить), ХРОНИКА column (last 50
  log entries filtered by experiment, live updates), footer Завершить +
  ⋯ menu с Прервать. Finalize saves card fields first (legacy parity).
- **B.8.0.1 — ExperimentOverlay critical hotfix.** Phase transition
  controls (Назад / Перейти к / Вперёд) добавлены в overlay. Phase
  stepper (reuse PhaseStepper) показывает текущую фазу. Current phase
  indicator в header info line. Status forwarding injects current_phase
  и app_mode в experiment dict для overlay. Operators can now advance
  phase, go back, jump to any phase from overlay.
- **Phase UI-1 v2 Block B.8 — ExperimentWorkspace rebuild as overlay.**
  NewExperimentDialog (modal) с полями name, operator, template,
  description, target_T_cold, tags + validation. ExperimentOverlay
  (full-screen drill-down) с editable inline name, header
  (elapsed/phase/operator/mode), MilestoneList (reuse B.5.5),
  Finalize с destructive confirmation (L9). Triggers: exp_label
  click, tray flask icon, + Создать button; ESC closes overlay.
  Legacy ExperimentWorkspace removed from MainWindowV2.
- **Phase UI-1 v2 Block B.7 — QuickLogBlock dashboard widget.**
  Закрывает последний placeholder `[ЖУРНАЛ — будет в B.6]`. Compact
  peripheral awareness ~55-65px: inline composer + последние 1-2
  entries. Не reading surface — для чтения OperatorLogPanel через
  tray rail. Empty state мотивирует первую запись. 10-second poll
  cycle для обновления + immediate refresh после отправки.
- **B.5.7.3 — Fira fonts load from launcher entry point.** B.5.7.2
  wired font loading only in `cryodaq-gui` entry (`gui/app.py:main`).
  The `cryodaq` launcher creates QApplication + MainWindowV2 directly
  без gui/app.py — font registration bypassed. Fix: call
  `_load_bundled_fonts()` в `launcher.py:main` after QApplication.
  Verified by real launch + QFontInfo resolution check.
- **B.5.7.2 — Fira font loading fix.** `addApplicationFont(path)`
  fails на macOS PySide6/Qt6. Заменён на `addApplicationFontFromData`
  который работает. Fira Sans + Fira Code теперь реально загружены
  в QFontDatabase. До этого Qt делал silent font substitution на
  system default при каждом запуске GUI.
- **B.5.7.1 — TopWatchBar separator normalization.** Унифицирован
  separator mechanism: zone VLine wrappers с consistent spacing
  (contentsMargins), context strip QFrame separators заменены на
  middle dot `·` text labels. Layout spacing = 0, all gaps via
  separator wrapper margins.
- **B.5.7 — Visual polish pass on dashboard.** Plot Y-axis alignment
  (fixed 60px left axis width), pressure plot height ratio tuned (18
  vs 50 stretch), TopWatchBar zone separators (VLines), PhaseStepper
  short Russian labels return (Под/Вак/Зах/Изм/Раст/Раз inline),
  transient state «Ожидание фазы» subdued to italic Body, experiment
  name elide + tooltip.
- **B.5.6 — Compact PhaseAwareWidget.** Phase widget сжат с ~210px
  до ~55px (одна строка). HeroReadout / EtaDisplay / MilestoneList
  primitives сохранены для B.10 Analytics overlay. Stepper pills
  24px, только номер фазы, Russian name в tooltip. Освобождает ~150px
  для графиков (95% операторского внимания).
- **Phase UI-1 v2 Block B.5.5 — 7-mode PhaseAwareWidget extension.**
  PhaseAwareWidget переходит от generic stepper к phase-specific
  content. Cherry-pick scope: cooldown (ETA + R_thermal hero),
  preparation (hint text), measurement (R_thermal hero) с реальным
  content. Vacuum/warmup/teardown показывают placeholder с ссылкой на
  Аналитика overlay. Reason: 5 NEEDS_WIRING + 1 MISSING (warmup
  predictor не существует). PhaseStepper извлечён как отдельный widget.
  Новый package `phase_content/` с HeroReadout, EtaDisplay, MilestoneList.
  Analytics readings (cooldown_eta, R_thermal) роутятся через
  DashboardView в PhaseAwareWidget.
- **B.6.2 — ModeBadge clickable.** Click на badge → confirmation
  dialog → set_app_mode ZMQ command. EXPERIMENT → DEBUG требует
  явного подтверждения (destructive: отключает архив и отчёты).
  Default button = Отмена для обоих направлений переключения.
- **Phase UI-1 v2 Block B.4.5** — Adoption design system из UI UX Pro
  Max skill v2.5.0 (MIT, Next Level Builder). Гибрид Real-Time
  Monitoring + Data-Dense Dashboard. Палитра Smart Home/IoT Dashboard
  расширенная пятью status-тирами. Шрифты Fira Code (display, цифры)
  и Fira Sans (prose, меню) заменяют Inter и JetBrains Mono. 8px grid
  spacing, 4px sharp radius. Backwards-compatible alias'ы в theme.py.
  Документация в docs/design-system/MASTER.md и FINDINGS.md.
- **Phase UI-1 v2 Block B.4.5.1** — Tone-down фикс цветов после
  визуальной оценки B.4.5. Desaturation status tier цветов на 30-40%,
  warmer background `#0d0e12`, видимая card elevation, возврат к
  оригинальному indigo `#7c8cff` accent. Architecture B.4.5 (aliases,
  Fira fonts, документация) полностью сохранены — изменены только
  конкретные hex значения в `theme.py`.
- **Phase UI-1 v2 Block B.4.5.2** — Shell chrome consistency fix.
  Три chrome widgets (TopWatchBar, BottomStatusBar, ToolRail) теперь
  рендерятся как cohesive frame: `WA_StyledBackground` атрибут,
  удалён bubble эффект `_context_frame`, ToolRail мигрирован на
  `#ToolRail` object selector (A.7 compliance), видимый hover state.
- **Phase UI-1 v2 Block B.5** — PhaseAwareWidget. Заменён placeholder
  фазы эксперимента на реальный widget с stepper UI (6 фаз: Подготовка
  / Вакуум / Охлаждение / Измерение / Нагрев / Завершение). Текущая
  фаза подсвечена `theme.ACCENT`, прошедшие muted, будущие dim. Hero
  display с large current phase name + duration counter. Manual
  transition controls: кнопки Назад / Вперёд + dropdown. Backend:
  расширение `/status` payload с `phase_started_at`. Widget получает
  данные через TopWatchBar → MainWindowV2 → DashboardView forwarding.
- **Phase UI-1 v2 Block B.4** — Persistent context strip в
  TopWatchBar. Четыре ключевых значения (давление, T мин, T макс
  холодных каналов, мощность нагревателя) видны постоянно — даже
  когда дашборд закрыт overlay-панелью. T мин и T макс рассчитываются
  только по холодным каналам (новый флаг `is_cold` в channels.yaml),
  чтобы корпусные датчики (вакуумный кожух, фланец, зеркала) не
  загрязняли индикатор. Stale-индикация через 30 секунд.
- **Phase UI-1 v2 Block B.3** — DynamicSensorGrid. Адаптивная сетка
  ячеек датчиков заменяет placeholder в zone дашборда. Inline rename
  по двойному клику, контекстное меню по правому клику, цветной
  border по статусу канала, обновления через ChannelBufferStore +
  push path от DashboardView. ChannelManager получил симметричный
  off_change() для корректной отписки callback'ов.
- **`ChannelManager.get_cold_channels()`** и
  **`get_visible_cold_channels()`** — публичный API для запроса
  cryogenic-classified каналов из конфигурации.
- **Поле `is_cold`** в `config/channels.yaml` для всех 24 каналов.
  Default: `true` (sensible для cryosystem).

### Исправлено

- **`engine.py:35`** — отсутствовал импорт `load_alarm_config`,
  использовался на строке 969. Регрессия от `8070b2db`. Engine падал
  с `NameError` при каждом запуске почти месяц, маскировалось циклом
  перезапуска launcher.

### Изменено

- **Phase I.1 visual polish after Vladimir review.** Showcase placeholder
  labels now render without dark background artifacts, card chrome reduced to
  a single header band, `ModalCard` default max width widened from 1100 to
  1280, `BentoGrid` row-span now affects rendered height (with geometry test),
  breadcrumb back link tightened, and placeholder copy made content-specific.
- **Шрифты** — Inter заменён на Fira Sans, JetBrains Mono заменён на
  Fira Code. Старые файлы остаются в `resources/fonts/` до B.7 cleanup.
- **theme.py** — полностью переработан под новые design tokens.
  Backwards-compatible alias'ы сохранены для постепенной миграции.

### Adopted from

- **UI UX Pro Max skill** v2.5.0 — design tokens, typography pairings,
  UX guidelines. MIT licensed by Next Level Builder.
  https://github.com/nextlevelbuilder/ui-ux-pro-max-skill

### Selected commits

- `ae7d8d4` fix(engine): add missing load_alarm_config import
- `c4396a8` ui(phase-1-v2): block B.3 — DynamicSensorGrid

---

## [0.33.0] — 2026-04-14

Первый tagged release. Hardened backend и Phase UI-1 v2 shell с dashboard
foundation, shipped одним merge commit `7b453d5`. Закрывает 20-версионный
gap в changelog с последнего v0.13.0.

### Added

- **Phase UI-1 v2 shell (блоки A через A.9).** Новый `MainWindowV2`
  (`gui/shell/main_window_v2.py`) с `TopWatchBar`, `ToolRail`,
  `BottomStatusBar` и `OverlayContainer` заменяют tab-based legacy
  `MainWindow`. Ambient information radiator layout для недельных
  экспериментов. Russian localization throughout. Блоки A.5 (icon
  visibility, launcher wiring), A.6 (chrome consolidation, RU
  localization), A.7 (layout collision fix), A.8 (child widget
  background seam fix), A.9 (orphan widget stubs, worker stacking
  guard, ChannelManager zone 3 channel summary).
- **Phase UI-1 v2 dashboard (блоки B.1, B.1.1, B.2).**
  `DashboardView` (`gui/dashboard/dashboard_view.py`) с пятью зонами
  (10/22/44/20/4 stretch ratios после B.1.1 reorder). Shared
  `ChannelBufferStore` (`gui/dashboard/channel_buffer.py`) для rolling
  per-channel history. `TimeWindow` enum (1мин/1ч/6ч/24ч/Всё).
  `TempPlotWidget` — multi-channel temperature plot с clickable legend
  и Lin/Log toggle. `PressurePlotWidget` — compact log-Y pressure
  plot, X-linked to temperature. Time window echo в `TopWatchBar`
  zone 2.
- **Phase UI-1 v1 theming foundation (блоки 1-7).** `theme.py`
  design tokens (colors, fonts, spacing). Inter + JetBrains Mono
  fonts bundled. 10 Lucide SVG icons. `pyqtdarktheme-fork`
  dependency. Systematic `setStyleSheet` classification и
  application across all widget panels. pyqtgraph `setBackground`
  cleanup.
- **Phase 2e Stage 1.** Streaming Parquet archive written at
  experiment finalize (`storage/parquet_archive.py`). Enables
  long-term archival и offline analytics. Confirmed shipped per
  CODEX_FULL_AUDIT H.7 (streaming writes, compression, midnight
  iteration, UTC timestamps, finalize integration).
- **Graphify knowledge graph integration.** Persistent structural
  memory via `graphify-out/`. Automatic rebuild on every commit и
  branch switch via git hooks. Top god nodes: `Reading` (789 edges),
  `ChannelStatus` (375), `DataBroker` (246), `ZmqCommandWorker`
  (195), `SafetyManager` (156). Injected в Claude Code sessions via
  `UserPromptSubmit` hook (62ms execution).

### Changed

- **Tier 1 Fix A — calibration channel canonicalization (`a5cd8b7`).**
  `CalibrationAcquisitionService.activate()` canonicalizes channel
  references через new `ChannelManager.resolve_channel_reference()`.
  Accepts short IDs (`"Т1"`) или full labels (`"Т1 Криостат верх"`).
  Raises new `CalibrationCommandError` on unknown or ambiguous refs.
  Engine returns structured failure response instead of crashing.
  Closes Codex round 2 NEW finding: "Calibration channel identity is
  not canonicalized before activation"
  (`engine.py:370-375`, `calibration_acquisition.py:92-108`).
- **Tier 1 Fix B — DataBroker subscriber exception isolation
  (`cbaa7f2`).** `DataBroker.publish()` wraps per-subscriber
  operations в try/except. One failing subscriber no longer aborts
  fan-out to siblings. `asyncio.CancelledError` still propagates.
  Protects new v2 dashboard subscribers from each other. Closes
  Codex round 1 finding B.1 / round 2 confirmed HIGH: "DataBroker
  subscriber exceptions sit on critical path before SafetyBroker"
  (`broker.py:85-109`, `scheduler.py:385-389`).
- **Tier 1 Fix C — alarm acknowledged state serialization
  (`d9e2fdf`).** `AlarmStateManager.acknowledge()` returns event dict
  or `None` (previously `bool`). Engine publishes event через
  `DataBroker` на channel `alarm_v2/acknowledged`. Enables future
  v2 alarm badge. `alarm_v2_status` response включает
  `acknowledged`, `acknowledged_at`, `acknowledged_by` fields.
  Closes Phase 2d deferred item A.9.1 (CODEX_FULL_AUDIT H.3).
- **Phase 2d safety и persistence hardening (14 commits).** Web
  stored XSS escape. `_fault()` hardware emergency_off shielded from
  cancellation. `_fault()` ordering: callback BEFORE publish (Jules
  R2). RUN_PERMITTED heartbeat monitoring. Fail-closed config for
  all 5 safety-adjacent configs. Atomic file writes via
  `core/atomic_write`. WAL mode verification. OVERRANGE/UNDERRANGE
  persist. Calibration KRDG+SRDG atomic per poll cycle. Scheduler
  graceful drain. AlarmStateManager.acknowledge real implementation
  with idempotent re-ack guard. Ruff lint debt 830 → 445.
- **Launcher и `gui/app.py`.** Entry point `cryodaq-gui` routes to
  `MainWindowV2` as primary shell. Legacy `MainWindow` и tab panels
  remain active for fallback until Block B.7.

### Fixed

- **Calibration panel instrument prefix bug (`621f98a`).** Pre-existing:
  `gui/widgets/calibration_panel.py` built channel refs в
  `"LS218_1:Т1 Криостат верх"` format from combobox. Pre-Tier-1
  this caused silent data loss; post-Tier-1 resolver rejects prefix
  format. Added `_strip_instrument_prefix()` helper applied to
  `reference_channel` и each `target_channel`.
- **Duplicate imports from rebase conflict (`621f98a`).**
  `gui/main_window.py` и `gui/widgets/experiment_workspace.py` had
  duplicate `ZmqBridge` и `get_data_dir` imports from v1 block 6
  merge conflict resolution. Removed duplicates.
- **`inject_context.py` broken pytest invocation (`f6fe4b9`).**
  `UserPromptSubmit` hook ran `pytest` against system `python3`
  без pytest module, silently failed, injected `"Tests: no output"`
  on every Claude Code prompt. Replaced с 62ms version using git
  metadata + graphify god nodes.
- **Codex R1 finding A.1 — calibration throttle atomicity
  regression.** Initially CRITICAL, downgraded to MEDIUM in R2 after
  verification showed common channels protected by config.

### Infrastructure

- **RTK (Rust Token Killer)** — pre-existing bash compression hook.
  60-90% token compression on dev operations. Note: strips `--no-ff`
  flag from `git merge` — workaround: `/usr/bin/git` directly.
- **Graphify skill 0.3.12 → 0.4.13.** First graph build indexed 294
  files into 4,304 nodes, 10,602 edges, 169 Leiden communities.
  ~3.1x token reduction for structural queries.
- **Git hooks:** `post-commit` и `post-checkout` for automatic
  incremental graph rebuild.
- **Project-level CC hook.** `.claude/settings.json` contains
  `PreToolUse` for `Glob|Grep` reminding Claude to read
  `graphify-out/GRAPH_REPORT.md` first.
- **Three-layer review pipeline** established in Phase 2d: CC
  tactical + Codex second-opinion + Jules architectural. 14 commits,
  17 Codex reviews, 2 Jules rounds.

### Known Issues

- **RTK strips `--no-ff` flag** from `git merge`. Workaround:
  `/usr/bin/git`.
- **~500 ruff lint errors** в `src/` и `tests/`. Pre-existing
  technical debt.
- **Dual-shell transition state.** Legacy `MainWindow`, `OverviewPanel`
  и tab panels remain active alongside `MainWindowV2` until Block B.7.
- **Wall-clock sensitivity** in `alarm_providers.py` и
  `channel_state.py` (`time.time()` vs `monotonic()`). Codex R2
  confirmed finding, not yet addressed.
- **Reporting generator blocking** — sync `subprocess.run()` for
  LibreOffice. Codex R1 E.1, still open.
- **Gap между v0.13.0 и v0.33.0.** Versions 0.14.0-0.32.x developed
  but not individually tagged. Retroactive research в
  `docs/changelog/RETRO_ANALYSIS_V3.md`.

### Test baseline

- 934 passed, 2 skipped
- +39 tests since Phase 2d start (895 baseline)
- +11 from Tier 1 fixes (5 calibration canon, 4 broker isolation,
  2 alarm ack serialization)
- +28 from v2 shell и dashboard merge
- Zero regressions

### Tags

- `v0.33.0` — merge commit `7b453d5`
- `pre-tier1-merge-backup-2026-04-14` — rollback anchor

### Selected commits in this release

- `a5cd8b7` tier1-a: canonicalize calibration channel identities
- `cbaa7f2` tier1-b: isolate DataBroker subscriber exceptions
- `d9e2fdf` tier1-c: serialize alarm acknowledged state through broker
- `7b453d5` merge: Phase UI-1 v2 shell и dashboard through Block B.2
- `621f98a` post-merge fixes: calibration prefix strip + dedupe imports
- `dafdd99` docs: post-merge PROJECT_STATUS и CLAUDE.md updates
- `f6fe4b9` infra: graphify setup + inject_context hook efficiency fix

Phase 2d detailed commit trail (14 commits): see `PROJECT_STATUS.md`
Phase 2d commits section. Codex audit trail: `docs/audits/CODEX_FULL_AUDIT.md`
и `docs/audits/CODEX_ROUND_2_AUDIT.md`.

### Upgrade notes

Не applicable — internal release.

---

## [0.32.0] — 14-04-26 — Phase 2d: закрытие и fail-closed

Завершающая часть Phase 2d. Очистка lint-долга, закрытие замечаний
Jules Round 2, завершение fail-closed конфигурации, официальное
объявление Phase 2d завершённым.

### Исправлено

- **Ruff lint** — накопленный долг сокращён с 830 до 445 ошибок
  (`efe6b49`, 132 файла).
- **Jules R2: `_fault()` ordering** — post-mortem log callback вызывается
  ДО optional broker publish, устраняя escape path при отмене.
- **Jules R2: calibration state mutation** — `prepare_srdg_readings()`
  вычисляет pending state, `on_srdg_persisted()` применяет атомарно
  после успешной записи. Устраняет расхождение `t_min`/`t_max`
  при сбое записи.

### Изменено

- **Fail-closed завершён** — `interlocks.yaml`, `housekeeping.yaml`,
  `channels.yaml` теперь вызывают `InterlockConfigError` /
  `HousekeepingConfigError` / `ChannelConfigError` при отсутствии
  или повреждении. Engine exit code 2.
- **`scheduler_drain_timeout_s`** — вынесен в `safety.yaml` (default 5s).
- **Phase 2d объявлен COMPLETE**, открыт Phase 2e.
- Удалён случайно закоммиченный каталог `logs/`, добавлен в `.gitignore`.

Диапазон коммитов: `efe6b49`..`0cd8a94` (5 commits)

---

## [0.31.0] — 13-04-26 — Phase 2d: безопасность и целостность данных

Основная часть Phase 2d — структурированная закалка безопасности
и целостности. Block A (safety) и Block B (persistence) объединены
в один релиз с промежуточным checkpoint.

### Добавлено

- **`core/atomic_write.py`** — атомарная запись файлов через
  `os.replace()` для experiment sidecars и calibration index/curve.
- **WAL mode verification** — engine отказывается запускаться если
  `PRAGMA journal_mode=WAL` вернул не `'wal'`.
- **OVERRANGE/UNDERRANGE persist** — `±inf` сохраняются как REAL в
  SQLite. NaN-valued statuses (`SENSOR_ERROR`, `TIMEOUT`)
  отфильтровываются для избежания `IntegrityError`.
- **SafetyConfigError / AlarmConfigError** — typed exception hierarchy
  для fail-closed конфигурации safety и alarm.

### Изменено

- **Web XSS** — `escapeHtml()` helper для stored XSS escape.
- **`_fault()` cancellation shielding** — `emergency_off`,
  `_fault_log_callback`, `_ensure_output_off` в `_safe_off`
  обёрнуты в `asyncio.shield()`.
- **RUN_PERMITTED heartbeat** — мониторинг застрявшего `start_source`
  detection.
- **Safety→operator_log bridge** — fault events публикуются через broker.
- **AlarmStateManager.acknowledge** — реальная реализация с idempotent
  re-ack guard.
- **KRDG+SRDG atomic** — calibration readings persist в одной
  транзакции per poll cycle.
- **Scheduler.stop()** — graceful drain (configurable, default 5s)
  перед forced cancel.

Диапазон коммитов: `88feee5`..`23929ca` (10 commits)

---

## [0.30.0] — 12-04-26 — Карта реальности и документация

Сверка документации с кодом по результатам аудит-корпуса. Построение
карты «документ vs реальность», перезапись guidance, расширение
модульного индекса CLAUDE.md.

### Добавлено

- **DOC_REALITY_MAP** — сверка 28 организационных документов
  против 62 non-GUI модулей (CC + Codex review).
- **CLAUDE.md module index** — расширение покрытия с ~34% до ~70%.
- **CLAUDE.md safety FSM** — исправлены инварианты и добавлено
  состояние `MANUAL_RECOVERY`.

### Изменено

- **Skill `cryodaq-team-lead`** — полная перезапись под текущую
  реальность репозитория.
- **Config list** — добавлены недостающие файлы конфигурации.

Диапазон коммитов: `995f7bc`..`1d71ecc` (4 commits)

---

## [0.29.0] — 09-04-26 — Аудит-корпус

Проект тратит целую главу на самоаудит. 11 глубинных документов
общим объёмом ~9 400 строк покрывают каждую крупную подсистему.

### Добавлено

- **CC deep audit** — 1 240 строк post-2c анализа.
- **Codex deep audit** — 763 строки overnight-анализа.
- **Verification pass** — повторная проверка 5 HIGH findings.
- **SafetyManager deep dive** — исчерпывающий FSM-анализ (1 062 строки).
- **Persistence trace** — exhaustive проверка persistence-first
  инварианта (1 090 строк).
- **Driver fault injection** — сценарии инъекции сбоев для драйверов
  (1 366 строк).
- **CVE sweep** — полный анализ зависимостей (286 строк).
- **Analytics/reporting deep dive** — 572 строки.
- **Config audit** — 719 строк.
- **Master triage** — синтез всех аудит-документов (307 строк).

Диапазон коммитов: `380df96`..`7aaeb2b` (12 commits)

---

## [0.28.0] — 31-03-26 — Подготовка к Phase 2d

Явная подготовительная волна перед структурированной закалкой.
Очистка поверхностных проблем чтобы Phase 2d мог сосредоточиться
на глубинных инвариантах.

### Исправлено

- **Codex audit findings** — `plugins.yaml` латинская T,
  `sensor_diagnostics` resolution, GUI non-blocking paths.
- **GUI non-blocking** — `send_command` + dead code cleanup (57 файлов).
- **Phase 1** — разблокировка сборки PyInstaller.
- **Phase 2a** — закрытие 4 HIGH findings (safety hardening).
- **Phase 2b** — закрытие 8 MEDIUM findings (observability и resilience).
- **Phase 2c** — закрытие 8 findings (финальная закалка).

### Изменено

- **Overview preset** — "Сутки" переименован в "Всё".

Диапазон коммитов: `9676165`..`1698150` (7 commits)

---

## [0.27.0] — 24-03-26 — Неблокирующий GUI и singleton

Устранение блокирующего поведения GUI и launcher при deployment stress.
Singleton protection для предотвращения двойного запуска.

### Добавлено

- **Single-instance protection** — для launcher и standalone GUI
  через атомарный lock-файл.

### Исправлено

- **Alarm v2 status poll** — убрана блокировка из polling path.
- **Bridge heartbeat** — false kills + blocking `send_command`
  в launcher.
- **Conductivity panel** — blocking `send_command` заменён на async.
- **Keithley spinbox** — debounce + non-blocking live update.
- **Experiment workspace** — 1080p layout для phase bar и passport forms.
- **Launcher** — non-blocking engine restart + deployment hardening.
- **Shift modal** — re-entrancy + engine `--force` `PermissionError`.

Диапазон коммитов: `8bac038`..`f217427` (8 commits)

---

## [0.26.0] — 23-03-26 — GPIB-восстановление и preflight

Улучшение восстановления после зависания аппаратуры и настройка
поведения preflight checklist под операционную реальность.

### Добавлено

- **GPIB auto-recovery** — очистка шины по timeout, preventive clear.
- **GPIB escalating recovery** — IFC bus reset, enable unaddressing.
- **Scheduler disconnect+reconnect** — автоматическое при серии ошибок.

### Изменено

- **Preflight sensor health** — понижен с error до warning (не должен
  блокировать эксперимент).

Диапазон коммитов: `ab57e01`..`dfd6021` (5 commits)

---

## [0.25.0] — 22-03-26 — Аудит v2, Parquet v1 и отчётность

Слияние audit-v2, первая версия Parquet-архива, CI pipeline и
профессиональная отчётность по ГОСТ Р 2.105-2019.

### Добавлено

- **Parquet archive v1** — `readings.parquet` рядом с CSV при
  финализации эксперимента. Столбец Parquet в таблице архива.
- **CI workflow** — тестирование и линтинг.
- **Отчётность** — professional human-readable reports для всех типов
  экспериментов. Форматирование по ГОСТ Р 2.105-2019, все графики
  во всех отчётах, smart page breaks.

### Исправлено

- **Audit-v2 merge** — 29 дефектов закрыты (9 коммитов в ветке).
- **Archive filter** — inclusive end-date, добавлен столбец end time.
- **Audit regression** — preflight severity, multi-day DB, overview
  resolver, parquet docstring.

Диапазон коммитов: `0fdc507`..`29d2215` (9 commits)

---

## [0.24.0] — 21-03-26 — Интеграция финального батча

Слияние ветки final-batch с single-instance lock, ZMQ request/reply
routing, experiment I/O threading и fixes для overview/history.

### Добавлено

- **ZMQ correlation ID** — для command-reply routing.
- **Future-per-request dispatcher** — dedicated reply consumer.

### Исправлено

- **Telegram** — natural channel sort, compact text, pressure log-Y.
- **Single-instance lock** — атомарный через `O_CREAT|O_EXCL`.
- **Experiment I/O** — перенесён в thread, удалена двойная генерация
  отчётов.
- **UI history** — proportional load, overview plot sync, CSV BOM.
- **Graph X-axis** — snap к началу данных на всех 7 панелях.

Диапазон коммитов: `9e2ce5b`..`dd42632` (9 commits)

---

## [0.23.0] — 21-03-26 — Слияние UI-рефакторинга

Слияние ветки `feature/ui-refactor` и немедленная стабилизация
интегрированного состояния.

### Добавлено

- **Вкладка Keithley** — переименована, добавлены кнопки time window
  и forecast zone.

### Изменено

- **UI-refactor merge** — `1ec93a6`, значительная переработка UI.
- **Default channels** — обновлены, web version синхронизирована.
- **`autosweep_panel`** — помечен как deprecated.

### Исправлено

- **Thyracont MV00 fallback** + SQLite read/write split + SafetyManager
  transition + Keithley disconnect.
- **UI cards** — toggle signals, history load, axis alignment, channel
  refresh.
- **QuickStart buttons** — удалены из overview (вызывали FAULT с P=0).
- **Audit wave 3** — `build_ensemble` guard, launcher ping, phase gap,
  RDGST, docs.

Диапазон коммитов: `1ec93a6`..`f08e6bb` (8 commits)

---

## [0.22.0] — 20-03-26 — Углубление безопасности и ревью

Безопасность и корректность углубляются после выхода аналитических
поверхностей. Закрытие результатов deep review и audit batch.

### Добавлено

- **Phase 2 safety** — тесты + bugfixes + LakeShore `RDGST?`.
- **Phase 3** — safety correctness, reliability, phase detector.

### Исправлено

- **ZMQ datetime** — сериализация + REP socket stuck на ошибке.
- **Deep review** — 2 бага исправлены, 2 теста добавлены.
- **Audit batch** — 6 bugов: safety race, SQLite shutdown, Inf filter,
  phase reset, GPIB leak, deque cap.
- **UI** — CSV BOM, sensor diag stretch, calibration stretch, reports
  toggle, adaptive liveness.

Диапазон коммитов: `afabfe5`..`af94285` (6 commits)

---

## [0.21.0] — 20-03-26 — Аналитика и безопасность Keithley

Feature-growth релиз: новые аналитические модули и расширение
runtime-диагностики. Трёхэтапный rollout для каждого модуля:
backend → engine → GUI.

### Добавлено

- **Keithley safety** — slew rate limit, compliance detection +
  ZMQ subprocess hardening.
- **SensorDiagnosticsEngine** — MAD-noise, OLS drift, Pearson
  correlation, health score 0-100. Backend (Stage 1) + engine
  integration + config (Stage 2) + GUI panel + status bar (Stage 3).
  20 unit tests.
- **VacuumTrendPredictor** — 3 модели откачки (exp/power/combined),
  BIC model selection, ETA. Backend (Stage 1) + engine (Stage 2) +
  GUI panel на вкладке Аналитика (Stage 3). 20 unit tests.

Диапазон коммитов: `856ad19`..`50e30e3` (7 commits)

---

## [0.20.0] — 19-03-26 — GPIB-стабилизация и ZMQ-изоляция

Непрерывный инженерный марафон: добиться надёжности транспорта
для непрерывного автоматического опроса, затем изолировать
последнюю хрупкую зависимость.

### Изменено

- **GPIB bus lock** — расширен scope: покрытие `open_resource()` и
  `close()`, атомарная верификация.
- **GPIB стратегии** — последовательно опробованы open-per-query,
  IFC reset, sequential polling, hot-path clear; в итоге persistent
  sessions (LabVIEW-стиль open-once).
- **`KRDG?`** — уточнения команды + GUI visual fixes.

### Добавлено

- **ZMQ subprocess isolation** — GUI больше не импортирует `zmq`
  напрямую. `zmq_subprocess.py` запускается в отдельном процессе.

Диапазон коммитов: `5bc640c`..`f64d981` (9 commits)

---

## [0.19.0] — 18-03-26 — Первое аппаратное развёртывание

Программное обеспечение впервые встречается с реальными приборами
и исправляется ими. Широкий sweep аппаратных проблем: GPIB, Thyracont,
Keithley, алармы, давление.

### Исправлено

- **GPIB bus lock** — покрытие `open_resource()` и `close()`, а не
  только query/write. Устранение гонки `-420 Query UNTERMINATED`.
- **Keithley source-off** — NaN при выключенном источнике приводил к
  `SQLite NOT NULL` crash. Добавлена обработка `float('nan')`.
- **Thyracont VSP63D** — протокол V1 вместо SCPI `*IDN?`; формула
  давления исправлена: 6 цифр (4 мантисса + 2 экспонента),
  `(ABCD/1000) × 10^(EF-20)`. Три итерации коррекции.
- **Rate check** — ограничен scope до critical channels only,
  отключённые датчики исключены из проверки.

### Изменено

- **Keithley P=const** — перенесён с TSP/Lua на host-side control loop
  в `keithley_2604b.py`. Удалён blocking TSP скрипт.
- **Keithley live update** — `P_target` обновляется на лету + исправлена
  кнопка Stop.

Диапазон коммитов: `d7c843f`..`1b5c099` (9 commits)

---

## [0.18.0] — 18-03-26 — Стабилизация после релиза

Небольшой стабилизационный релиз сразу после волны remote ops
и alarm v2.

### Исправлено

- **Memory leak** — broadcast task explosion, rate estimator trim,
  history cap.
- **Empty plots** — после GUI reconnect + wrong experiment status key.

### Добавлено

- **Tray-only mode** — headless engine monitoring без main window.

Диапазон коммитов: `92e1369`..`c7ae2ed` (3 commits)

---

## [0.17.0] — 18-03-26 — Alarm v2

Полный rollout alarm engine v2. Шесть коммитов за 22 минуты:
фундамент → evaluator → провайдеры → интеграция → fix → GUI.

### Добавлено

- **RateEstimator** — OLS-based dX/dt оценка скорости изменения (K/мин)
  с подавлением шума, скользящее окно.
- **ChannelStateTracker** — отслеживание актуального состояния каналов,
  stale detection, fault history.
- **AlarmEvaluator** — composite (AND/OR), threshold, rate, stale alarm
  types; `deviation_from_setpoint`, `outside_range`, `fault_count_in_window`.
- **AlarmStateManager** — dedup, sustained_s, гистерезис, история
  переходов, acknowledge.
- **Alarm v2 providers** — `ExperimentPhaseProvider`, `ExperimentSetpointProvider`
  через `ExperimentManager`. Config parser для `alarms_v3.yaml`.
- **Alarm v2 GUI** — секция с цветовыми уровнями, ACK, поллинг каждые 3с.
- **Engine integration** — `DataBroker` subscriber для обновления state/rate,
  периодический `alarm_tick` с фазовым фильтром.

### Исправлено

- **`interlocks.yaml`** — удалён `undercool_shield` (ложное срабатывание
  при cooldown), `detector_warmup` переведён на T12.

Диапазон коммитов: `88357b8`..`d3b58bd` (6 commits)

---

## [0.16.0] — 18-03-26 — Удалённый мониторинг и preflight

Расширение операционной поверхности без изменения alarm engine.
Первый real remote-ops релиз.

### Добавлено

- **Web dashboard** — read-only мониторинг с auto-refresh 5с,
  FastAPI + self-contained HTML, `/api/status`, `/api/log`, `/ws`.
- **Telegram bot v2** — `/log <text>`, `/phase <phase>`, `/temps`;
  `EscalationService` (delayed multi-level chain).
- **Pre-flight checklist** — диалог перед созданием эксперимента:
  engine, safety, инструменты, алармы, давление, диск.
- **Experiment auto-fill** — `UserPreferences`, `QCompleter` на
  operator/sample/cryostat, автоимя с инкрементом.

### Исправлено

- **Telegram polling** — debug startup + ensure task started.

Диапазон коммитов: `7ee15de`..`4405348` (5 commits)

---

## [0.15.0] — 18-03-26 — Первый лабораторный релиз

Явный release commit. Даже без сохранившегося тега, этот коммит
остаётся чётким маркером «первая система, готовая для лаборатории».

### Изменено

- **Release v0.12.0** — первый production release commit.

Диапазон коммитов: `c22eca9` (1 commit)

---

## [0.14.0] — 17-03-26 — Фазы экспериментов и авто-отчёты

Дисциплина экспериментов: фазы, автоматическое логирование,
авто-отчёты при финализации, polish UX.

### Добавлено

- **ExperimentPhase** — preparation → vacuum → cooldown → measurement →
  warmup → teardown. Переход через `experiment_advance_phase`.
- **EventLogger** — автоматическая запись: Keithley start/stop/e-off,
  эксперимент start/finalize/abort, смена фазы.
- **Авто-отчёт** — генерация при финализации если шаблон включает
  `report_enabled`.
- **Calibration start button** — запуск калибровки прямо с вкладки.

### Исправлено

- **P1 audit** — phase widget, empty states, auto-entry styling,
  `DateAxisItem` everywhere.
- **Russian labels** — полная синхронизация документации.

Диапазон коммитов: `bc41589`..`3b6a175` (5 commits)

---

## [0.13.0] — 17-03-26 — Калибровка v2

Полный pipeline калибровки v2: непрерывный сбор SRDG при
калибровочных экспериментах, post-run pipeline, трёхрежимный GUI.

### Добавлено

- **`CalibrationAcquisitionService`** — непрерывный сбор SRDG
  параллельно с KRDG при калибровочном эксперименте.
- **`CalibrationFitter`** — post-run pipeline: извлечение пар из SQLite,
  адаптивный downsample, Douglas-Peucker breakpoints, Chebyshev fit.
- **Калибровка GUI** — трёхрежимная вкладка: Setup (выбор каналов,
  импорт) → Acquisition (live stats, coverage bar) → Results (метрики,
  export). `.330` / `.340` / JSON export.
  *(Note: `.330` format removed post-v0.39.0; `.cof` Chebyshev coefficient
  export added — see [Unreleased].)*

### Изменено

- Удалён legacy `CalibrationSessionStore` и ручной workflow.

Диапазон коммитов: `81ef8a6`..`98a5951` (4 commits)

---

## [0.12.0] — 17-03-26 — Итерация обзора

Итерация производительности и layout overview panel. Горячие клавиши,
async ZMQ polling, переработка launcher.

### Добавлено

- **Горячие клавиши** — Ctrl+L (журнал), Ctrl+E (эксперимент),
  Ctrl+1..9/0 (вкладки), Ctrl+Shift+X (аварийное отключение Keithley),
  F5 (обновление).
- **Async ZMQ polling** — `ZmqCommandWorker` вместо синхронного
  `send_command` на таймерах.

### Изменено

- **Overview layout** — двухколоночный: графики температуры и давления
  (связанная ось X). Кликабельные карточки температур (toggle видимости).
  `DateAxisItem` (HH:MM) на всех графиках.
- **Launcher** — восстановлено меню, поддержка `--mock`,
  исправлен дубликат tray icon (`embedded=True`).
- **UX** — все labels на русском, прижатие layout к верху на вкладке
  Приборы, empty state overlays на Аналитика и Теплопроводность.

Диапазон коммитов: `3dea162`..`2136623` (9 commits)

---

## [0.11.0] — 17-03-26 — Dashboard hub и смены

Dashboard hub с quick-actions для Keithley, quick log, experiment
status. Структурированная система смены операторов.

### Добавлено

- **Dashboard hub** — Keithley quick-actions, quick log, experiment
  status на overview.
- **Shift handover** — `ShiftBar` с заступлением, периодическими
  проверками (2ч) и сдачей смены. Данные смен через operator log
  с tags.

Диапазон коммитов: `29652a2`..`f910c40` (4 commits)

---

## [0.10.0] — 17-03-26 — RC-слияние Codex

Одиночный merge commit, интегрирующий работу из ветки `CRYODAQ-CODEX`.
+14 690 / -6 632 строк через 83 файла. Backend workflows (experiments,
reports, housekeeping, calibration), GUI workflows (tray status,
operator hardening), packaging metadata.

### Изменено

- **Codex RC merge** — `dc2ea6a`, масштабное слияние всех backend и
  GUI workflow из параллельной ветки разработки.

Диапазон коммитов: `dc2ea6a` (1 commit)

---

## [0.9.0] — 15-03-26 — P1-исправления и instrument_id

Исправления развёртывания P1 (8 дефектов) и BREAKING изменение
контракта данных: `instrument_id` становится first-class полем
на `Reading` dataclass.

### Исправлено

- **P1-01: Async ZMQ** — persistent socket + `ZmqCommandWorker(QThread)`
  для non-blocking emergency off.
- **P1-02: AutoSweep compliance** — V_comp (10V) и I_comp (0.1A)
  spinboxes; удалены hardcoded 40V/3A.
- **P1-03: Heartbeat regex** — configurable `keithley_channels` patterns
  из `safety.yaml`; проверка freshness AND status.
- **P1-04: Centralized paths** — `paths.py` с `get_data_dir()`.
- **P1-05: Experiment menu** — dialog с name/operator/sample/description.
- **P1-06: Persistent aiohttp** — `_get_session()` + `close()` в
  Telegram notifier/bot/reporter.
- **P1-07: SQLite REAL timestamp** — новые БД используют `REAL`;
  `_parse_timestamp()` поддерживает оба формата.
- **P1-08: Composite index** — `idx_channel_ts ON readings (channel, timestamp)`.

### Изменено

- **BREAKING: `instrument_id`** — промотирован в first-class поле
  `Reading` dataclass. 37 затронутых файлов.

Диапазон коммитов: `de715dc`..`0078d57` (6 commits)

---

## [0.8.0] — 14-03-26 — Аудит и P0-исправления

Первая волна аудита безопасности (14 fixes) и 5 критических P0
дефектов. Тестовая база: 118 тестов.

### Исправлено

- **Safety audit (14 fixes)** — `FAULT_LATCHED` latch, status checks,
  heartbeat, state transitions.
- **P0-01: Alarm pipeline** — `AlarmEngine` публикует события и
  `analytics/alarm_count` через `DataBroker`; `filter_fn` предотвращает
  feedback loops.
- **P0-02: Safety state publish** — `analytics/safety_state` Reading
  на каждом переходе + initial snapshot.
- **P0-03: P/V/I limits** — `max_power_w=5W`, `max_voltage_v=40V`,
  `max_current_a=1A` валидируются в `request_run()` ДО `RUN_PERMITTED`.
- **P0-04: Emergency_off latched** — возвращает `{latched: true}` при
  `FAULT_LATCHED`.
- **P0-05: smub cleanup** — вкладка отключена в GUI, удалена из
  autosweep dropdown (впоследствии восстановлена в dual-channel модели).

### Добавлено

- **Тестовая база** — 118 тестов через все модули (`734f641`).

Диапазон коммитов: `e9a538f`..`0f8dd59` (4 commits)

---

## [0.7.0] — 14-03-26 — Cooldown predictor и обзор

Интеграция ensemble-предиктора охлаждения. Overview panel, экспорт,
DiskMonitor.

### Добавлено

- **Cooldown predictor** — `cooldown_predictor.py` (~900 строк):
  dual-channel progress variable, rate-adaptive weighting, LOO
  validation, quality-gated ingest.
- **`cooldown_service.py`** — asyncio-сервис: `CooldownDetector`
  (IDLE→COOLING→STABILIZING→COMPLETE), периодический predict (30с),
  автоматический ingest.
- **GUI** — ETA ±CI, progress bar, фаза, пунктирная траектория с CI
  band на вкладке Аналитика.
- **CLI** — `cryodaq-cooldown build|predict|validate|demo|update`.
- **`config/cooldown.yaml`** — конфигурация каналов, детекции, модели.
- **Overview panel** — объединение температур + давления в единый
  dashboard с StatusStrip, 24 карточками, графиками.
- **Экспорт** — CSV, Excel (openpyxl), HDF5 через меню Файл.
- **DiskMonitor** — проверка свободного места каждые 5 мин,
  WARNING <10 GB, CRITICAL <2 GB.
- 26 новых тестов (16 предиктор + 10 сервис).

Диапазон коммитов: `9217489`..`9390419` (7 commits)

---

## [0.6.0] — 14-03-26 — SafetyManager и безопасность данных

Архитектура безопасности и persistence-first ordering.

### Добавлено

- **SafetyManager** — 6-state FSM: SAFE_OFF → READY → RUN_PERMITTED →
  RUNNING → FAULT_LATCHED → MANUAL_RECOVERY. Fail-on-silence: устаревшие
  данные (>10с) → FAULT + `emergency_off`. Rate limit: dT/dt >5 K/мин
  → FAULT. Two-step recovery с указанием причины + 60с cooldown.
- **SafetyBroker** — выделенный канал безопасности, overflow=FAULT
  (не drop).
- **Persistence-first ordering** — `SQLiteWriter.write_immediate()` WAL
  commit ПЕРЕД публикацией в `DataBroker`. Гарантия: если данные видны
  оператору — они уже на диске. 7 новых тестов.

### Изменено

- **SQLiteWriter** — вызывается напрямую из Scheduler (не через broker).

Диапазон коммитов: `603a472`..`a8e8bbf` (8 commits)

---

## [0.5.0] — 14-03-26 — Launcher и двухканальный Keithley

Operator launcher, dual-channel Keithley, workflow теплопроводности,
централизованное управление каналами.

### Добавлено

- **Launcher** (`cryodaq`) — operator launcher: engine + GUI + system
  tray, auto-restart.
- **Dual-channel Keithley** — backend, driver и GUI поддерживают `smua`,
  `smub` и одновременную работу `smua+smub`.
- **Вкладка Теплопроводность** — выбор цепочки датчиков, R/G, T∞
  прогноз. Автоизмерение (развёрт P₁→P₂→…→Pₙ) интегрировано.
- **ChannelManager** — централизованные имена и видимость каналов,
  YAML persistence.
- **ConnectionSettingsDialog** — настройка адресов приборов из GUI.

Диапазон коммитов: `77638b0`..`b2b4d97` (5 commits)

---

## [0.4.0] — 14-03-26 — Третий прибор и тестовая база

Thyracont VSP63D (третий прибор), все вкладки GUI активны,
руководство оператора, полная тестовая база.

### Добавлено

- **Thyracont VSP63D driver** — RS-232, протокол MV00, вакуумметр.
- **Serial transport** — async pyserial wrapper.
- **Вкладка Давление** — лог-шкала, цветовая индикация.
- **Все 10 GUI вкладок** — полностью функциональны.
- **`docs/operator_manual.md`** — руководство оператора на русском.
- **Agent Teams Skill v2** — `.claude/skills/cryodaq-team-lead.md`
  для Claude Code (6 ролей, 4 инварианта).
- **Code review (13 пунктов)** — CRITICAL: отозван утёкший Telegram bot
  token. Удалён `__del__` из Keithley driver. `asyncio.create_task()`
  вместо deprecated `get_event_loop()`. InterlockCondition regex
  pre-compiled. DataBroker tuple snapshot iteration.
- `install.bat`, `create_shortcut.py` — Windows installer helpers.
- `docs/deployment.md`, `docs/first_deployment.md`.

Диапазон коммитов: `33e51f3`..`da825f1` (9 commits)

---

## [0.3.0] — 14-03-26 — Скелет workflow

Entry points engine и GUI, experiment lifecycle, Telegram уведомления,
web dashboard, периодические отчёты.

### Добавлено

- **Engine + GUI entry points** — `cryodaq-engine`, `cryodaq-gui`
  в `pyproject.toml`. Main window с панелью алармов и статусом приборов.
- **Experiment lifecycle** — `ExperimentManager` с start/stop, config
  snapshot, SQLite persistence.
- **Data export** — CSV, HDF5 экспорт из SQLite. `ReplaySource` для
  воспроизведения исторических данных.
- **TelegramNotifier** — alarm events → Telegram Bot API.
- **PeriodicReporter** — matplotlib графики + текстовая сводка в
  Telegram каждые 30 мин.
- **Web dashboard** — FastAPI + WebSocket + Chart.js, тёмная тема.

Диапазон коммитов: `e64b516`..`e4bbcb6` (4 commits)

---

## [0.2.0] — 14-03-26 — Инструменты и аналитика

LakeShore 218S и Keithley 2604B drivers, первые alarm и analytics
abstractions, plugin pipeline.

### Добавлено

- **LakeShore 218S driver** — GPIB, SCPI, `KRDG?` без аргумента
  для batch считывания 8 каналов, 3 прибора = 24 канала.
- **Keithley 2604B driver** — USB-TMC, TSP/Lua supervisor (`p_const.lua`),
  heartbeat, `emergency_off`.
- **AlarmEngine** — state machine (OK → ACTIVE → ACKNOWLEDGED),
  hysteresis, severity levels.
- **PluginPipeline** — hot-reload `.py` из `plugins/`, watchdog
  filesystem events, error isolation.
- **ThermalCalculator plugin** — R_thermal = (T_hot - T_cold) / P.
- **CooldownEstimator plugin** — exponential decay fit → cooldown ETA.
- **InterlockEngine** — threshold detection, regex channel matching.
- **Вкладка Температуры** — 24 ChannelCard + pyqtgraph, ring buffer.
- **Вкладка Алармы** — severity table, acknowledge.
- **Вкладка Keithley** — smua/smub: V/I/R/P графики + управление.
- **Вкладка Аналитика** — R_thermal plot + cooldown ETA.
- `config/interlocks.yaml`, `config/alarms.yaml`,
  `config/notifications.yaml`.

Диапазон коммитов: `0c54010`..`75ebdc1` (4 commits)

---

## [0.1.0] — 14-03-26 — Начальная архитектура

Первые коммиты проекта. Базовая двухпроцессная архитектура с headless
engine и PySide6 GUI, связанными через ZeroMQ. Первый скелет сбора
данных, персистентности и межпроцессного взаимодействия.

### Добавлено

- **Архитектурный контракт** в `CLAUDE.md` — описание двухпроцессной
  модели, инвариантов безопасности, правил разработки.
- **Пакетная структура** — `pyproject.toml`, каталоги `src/cryodaq/`,
  driver ABC, `DataBroker` (fan-out pub/sub с bounded `asyncio.Queue`
  и политикой `DROP_OLDEST`).
- **SQLiteWriter** — WAL mode, crash-safe, batch insert, daily rotation.
- **Scheduler** — per-instrument polling с exponential backoff и
  автоматическим реконнектом.
- **ZMQ bridge** — PUB/SUB на порту :5555 (msgpack) + REP/REQ :5556
  (JSON) для команд GUI → engine.

Диапазон коммитов: `be52137`..`2882845` (4 commits)
