> **HISTORICAL.** Snapshot from commit `7aaeb2b`. See `docs/REPO_AUDIT_REPORT.md` for current state.
>
> **Addendum 2026-04-30 (repo cleanup):** notable changes since 2026-04-17 snapshot.
> See CHANGELOG.md for full details. A fresh full audit against `35f2798` (v0.42.0) is pending.

---

## Addendum — changes since 2026-04-17 (v0.42.0 / 2026-04-30)

### New modules (not in original snapshot)

**GUI — Shell views (Phase II analytics + F3/F4)**
- `src/cryodaq/gui/shell/views/analytics_view.py` — AnalyticsView primary-view QWidget (II.1, shipped v0.34.0-era; `860ecf3`)
- `src/cryodaq/gui/shell/views/analytics_widgets.py` — F3 analytics widget set: W1 temperature_trajectory, W2 cooldown_history, W3 experiment_summary, W4 r_thermal_placeholder (v0.40.0)

**GUI — Shell overlays (Phase II blocks)**
- `src/cryodaq/gui/shell/overlays/alarm_panel.py` — AlarmPanel overlay
- `src/cryodaq/gui/shell/overlays/archive_panel.py` — ArchivePanel overlay (II.2, v0.34.0-era)
- `src/cryodaq/gui/shell/overlays/calibration_panel.py` — CalibrationPanel overlay
- `src/cryodaq/gui/shell/overlays/conductivity_panel.py` — ConductivityPanel overlay
- `src/cryodaq/gui/shell/overlays/instruments_panel.py` — InstrumentsPanel overlay
- `src/cryodaq/gui/shell/overlays/keithley_panel.py` — KeithleyPanel overlay (II.6, v0.34.0-era)
- `src/cryodaq/gui/shell/overlays/operator_log_panel.py` — OperatorLogPanel overlay (II.3, v0.34.0-era)

### Modified modules with significant additions since snapshot

| Module | Change | Release |
|---|---|---|
| `src/cryodaq/core/sensor_diagnostics.py` | Added `publish_diagnostic_alarm` / `clear_diagnostic_alarm` interface; `_AnomalyState` per-channel tracker; alarm_publisher injection | v0.41.0 |
| `src/cryodaq/core/alarm_v2.py` | `AlarmStateManager.publish_diagnostic_alarm()`, `clear_diagnostic_alarm()` — F10 alarm integration | v0.41.0 |
| `src/cryodaq/core/safety_manager.py` | HF1: `update_target()` docstring — delayed-update design documented | v0.42.0 |
| `src/cryodaq/core/zmq_bridge.py` | HF2: `keithley_emergency_off`, `keithley_stop` added to `_SLOW_COMMANDS` frozenset | v0.42.0 |
| `src/cryodaq/gui/shell/main_window_v2.py` | F3/F4 wiring: `_analytics_snapshot_cache`, `set_cooldown()` + analytics widget push methods; `active.get("experiment_id")` key fix | v0.40.0 |

### Vault subsystem notes (new in v0.41.0)

6 Obsidian vault notes added via CC_PROMPT_VAULT_SUBSYSTEM_QUARTET + subsequent dispatches:
Analytics view, F4 lazy replay, Web dashboard, Cooldown predictor, Experiment manager, Interlock engine.
Location: `~/Vault/CryoDAQ/` (not in git repo).

### Calibration module (v1.0, 2026-04-25+)

`src/cryodaq/analytics/calibration_fitter.py` shipped with full post-run pipeline
(extract → downsample → breakpoints → Chebyshev fit). `.330` format removed per
architect decision 2026-04-25. See CLAUDE.md `## Снимок сверки` for calibration v2 invariants.

---

# CryoDAQ Documentation Reality Map

**Date:** 2026-04-12
**Branch:** master
**Commit under review:** 7aaeb2b
**Scope:** runtime code + org docs, GUI excluded
**Method:** CC discovery + Codex review at three checkpoints

---

## Section 1 — Org document inventory

| Path | Lines | Last modified | Purpose |
|---|---|---|---|
| `CLAUDE.md` | 215 | 2026-04-08 | Primary CC instructions: architecture, module index, build commands, key rules |
| `README.md` | 259 | 2026-03-22 | Project overview, install instructions, feature list |
| `CHANGELOG.md` | 384 | 2026-03-21 | Release history from 0.1.0 through 0.13.0 |
| `RELEASE_CHECKLIST.md` | 155 | 2026-03-21 | Pre-release verification steps |
| `docs/architecture.md` | 349 | 2026-03-22 | Detailed architecture: asyncio model, data flow, ZMQ protocol |
| `docs/deployment.md` | 277 | 2026-04-08 | Lab PC deployment steps, systemd, firewall, USB rules |
| `docs/first_deployment.md` | 207 | 2026-03-21 | First-time setup guide for a fresh lab PC |
| `docs/operator_manual.md` | 257 | 2026-03-22 | Operator-facing workflow guide (Russian) |
| `.claude/skills/cryodaq-team-lead.md` | 475 | 2026-03-14 | CC skill definition for team lead agent role |
| `DEEP_AUDIT_CC.md` | 940 | untracked | CC deep audit (Phase 1, 15 areas A-O) |
| `DEEP_AUDIT_CC_POST_2C.md` | 1240 | 2026-04-09 | CC deep audit post-Phase 2c (51 findings) |
| `DEEP_AUDIT_CODEX.md` | 438 | untracked | Codex audit companion to DEEP_AUDIT_CC |
| `DEEP_AUDIT_CODEX_POST_2C.md` | 763 | 2026-04-09 | Codex audit companion post-Phase 2c |
| `CONFIG_FILES_AUDIT.md` | 719 | 2026-04-09 | Config file security and completeness audit |
| `DEPENDENCY_CVE_SWEEP.md` | 286 | 2026-04-09 | CVE scan of all Python dependencies |
| `DRIVER_FAULT_INJECTION.md` | 1366 | 2026-04-09 | Fault injection test results for all three drivers |
| `HARDENING_PASS_CODEX.md` | 985 | 2026-04-09 | Codex hardening review findings |
| `MASTER_TRIAGE.md` | 307 | 2026-04-09 | Triage of all open audit findings |
| `PERSISTENCE_INVARIANT_DEEP_DIVE.md` | 1090 | 2026-04-09 | Deep analysis of SQLite persistence guarantees |
| `REPORTING_ANALYTICS_DEEP_DIVE.md` | 572 | 2026-04-09 | Deep analysis of reporting + analytics pipelines |
| `SAFETY_MANAGER_DEEP_DIVE.md` | 1062 | 2026-04-09 | Deep analysis of safety FSM + interlock system |
| `VERIFICATION_PASS_HIGHS.md` | 1005 | 2026-04-09 | Verification that HIGH-severity fixes landed correctly |
| `docs/phase-ui-1/SPEC_AUTHORING_CHECKLIST.md` | 368 | untracked | UI spec authoring checklist (QSS, timers, etc) |
| `docs/phase-ui-1/PHASE_UI1_V2_BLOCK_*` | 5 files | untracked | UI Phase 1 v2 block specs (A.8, A.9, B.1, B.1.1, B.2) |

**Total org docs:** 28 files, ~14,600 lines

---

## Section 2 — Code module inventory

### Entry points (5 files, 2,759 lines)

| File | Lines | Summary |
|---|---|---|
| `src/cryodaq/__main__.py` | 5 | Delegates to `launcher.main()` |
| `src/cryodaq/_frozen_main.py` | 99 | PyInstaller entry point, `freeze_support()` before imports |
| `src/cryodaq/engine.py` | 1749 | Headless asyncio runtime: instrument scheduling, safety, storage, commands |
| `src/cryodaq/launcher.py` | 827 | Operator launcher: engine lifecycle, embedded GUI, tray icon |
| `src/cryodaq/instance_lock.py` | 59 | File-lock based single-instance guard (flock/msvcrt) |

### Core (24 files, 6,187 lines)

| File | Lines | Summary |
|---|---|---|
| `alarm.py` | 618 | v1 alarm engine — threshold + rate-of-change per channel |
| `alarm_v2.py` | 510 | v2 alarm engine — YAML-driven, phase-aware, multi-channel |
| `alarm_config.py` | 182 | alarms_v3.yaml parser → AlarmConfig + EngineConfig |
| `alarm_providers.py` | 117 | Phase/setpoint providers wiring alarm_v2 to ExperimentManager |
| `atomic_write.py` | 78 | Atomic file writes via temp + rename |
| `broker.py` | 120 | DataBroker — asyncio pub/sub for readings |
| `calibration_acquisition.py` | 122 | Continuous SRDG collection during calibration experiments |
| `channel_manager.py` | 208 | Singleton managing channel names, visibility, display |
| `channel_state.py` | 140 | Per-channel state tracker for alarm evaluator (staleness, fault history) |
| `disk_monitor.py` | 115 | Disk space monitor with graceful degradation |
| `event_logger.py` | 35 | Automatic system event logging to experiment log |
| `experiment.py` | 1681 | ExperimentManager — lifecycle, phases, finalization, reporting |
| `housekeeping.py` | 420 | Periodic maintenance: log rotation, stale cleanup, adaptive throttle |
| `interlock.py` | 521 | Safety interlock evaluation: thresholds → actions (emergency_off/stop_source) |
| `operator_log.py` | 39 | Operator journal storage API |
| `rate_estimator.py` | 121 | Rolling dT/dt estimator for safety rate limiting |
| `safety_broker.py` | 126 | Dedicated broker for safety readings (overflow → FAULT) |
| `safety_manager.py` | 806 | Safety FSM: states, fault detection, rate limiting, source control |
| `scheduler.py` | 483 | Instrument polling scheduler with persistence-first ordering |
| `sensor_diagnostics.py` | 451 | Read-only analytics: noise, drift, correlation, health score |
| `smu_channel.py` | 14 | Type alias: `SmuChannel = Literal["smua", "smub"]` |
| `user_preferences.py` | 129 | Persistent user preferences for experiment creation forms |
| `zmq_bridge.py` | 369 | ZMQ command server (REP/REQ) + data publisher (PUB/SUB) |
| `zmq_subprocess.py` | 156 | GUI-side ZMQ subprocess bridge wrapper |

### Analytics (8 files, 4,343 lines)

| File | Lines | Summary |
|---|---|---|
| `base_plugin.py` | 129 | Base class for analytics plugins (register, init, process) |
| `calibration.py` | 1245 | CalibrationStore + Chebyshev fit + runtime apply policy |
| `calibration_fitter.py` | 391 | Post-run calibration pipeline: extract → downsample → breakpoints → fit |
| `cooldown_predictor.py` | 1103 | DTW-based cooldown ETA prediction from reference curves |
| `cooldown_service.py` | 476 | Runtime cooldown orchestration (wall-clock vs monotonic mix noted) |
| `plugin_loader.py` | 362 | Plugin discovery and loading from plugins.yaml |
| `steady_state.py` | 204 | Steady-state predictor for thermal conductivity measurements |
| `vacuum_trend.py` | 433 | Vacuum pump-down trend analysis and ETA prediction |

### Drivers (7 files, 2,452 lines)

| File | Lines | Summary |
|---|---|---|
| `base.py` | 94 | Reading dataclass, ChannelStatus enum, InstrumentDriver base |
| `instruments/keithley_2604b.py` | 511 | Keithley 2604B dual-SMU driver (TSP, P=const host-side) |
| `instruments/lakeshore_218s.py` | 607 | LakeShore 218S 8-channel thermometer driver |
| `instruments/thyracont_vsp63d.py` | 417 | Thyracont VSP63D vacuum gauge driver (serial) |
| `transport/gpib.py` | 359 | GPIB transport via PyVISA |
| `transport/serial.py` | 203 | Async serial transport via pyserial-asyncio |
| `transport/usbtmc.py` | 261 | USB-TMC transport via PyVISA |

### Storage (6 files, 1,737 lines)

| File | Lines | Summary |
|---|---|---|
| `sqlite_writer.py` | 728 | WAL-mode SQLite writer, daily rotation, disk-full handling |
| `csv_export.py` | 183 | CSV export from SQLite archives |
| `hdf5_export.py` | 236 | HDF5 export (h5py) |
| `parquet_archive.py` | 124 | Parquet archive read/write (pyarrow optional) |
| `replay.py` | 212 | Historical data replay from SQLite |
| `xlsx_export.py` | 254 | Excel export (openpyxl) |

### Notifications (5 files, 1,354 lines)

| File | Lines | Summary |
|---|---|---|
| `telegram.py` | 236 | Telegram bot for alarm notifications |
| `telegram_commands.py` | 463 | Telegram command handler (/status, /readings, /plot) |
| `escalation.py` | 110 | Alarm escalation policy (repeat intervals, severity tiers) |
| `periodic_report.py` | 502 | Periodic experiment summary reports via Telegram |
| `_secrets.py` | 43 | SecretStr wrapper to prevent accidental token leaks |

### Reporting (3 files, 1,140 lines)

| File | Lines | Summary |
|---|---|---|
| `data.py` | 200 | Data extraction from SQLite for report generation |
| `generator.py` | 224 | Report generator: DOCX + best-effort PDF via LibreOffice |
| `sections.py` | 713 | Report section renderers (overview, phases, readings, plots) |

### Web (1 file, 513 lines)

| File | Lines | Summary |
|---|---|---|
| `server.py` | 513 | FastAPI dashboard: /status, /history, /ws, static HTML |

### Tools (1 file, 253 lines)

| File | Lines | Summary |
|---|---|---|
| `cooldown_cli.py` | 253 | CLI for cooldown model training and prediction |

### Utility (2 files, 230 lines)

| File | Lines | Summary |
|---|---|---|
| `logging_setup.py` | 151 | TimedRotatingFileHandler + token redact filter |
| `paths.py` | 79 | Path resolution: sys.frozen, CRYODAQ_ROOT, defaults |

### Config files (18 files)

| File | Modified | Purpose |
|---|---|---|
| `config/instruments.yaml` | 2026-04-01 | Instrument connection parameters |
| `config/instruments.local.yaml.example` | 2026-03-24 | Local override template for instruments |
| `config/safety.yaml` | 2026-04-01 | Safety FSM parameters, rate limits |
| `config/interlocks.yaml` | 2026-04-01 | Interlock thresholds → actions |
| `config/alarms.yaml` | 2026-03-18 | v1 alarm definitions |
| `config/alarms_v3.yaml` | 2026-04-01 | v2/v3 alarm definitions (phase-aware) |
| `config/channels.yaml` | 2026-04-01 | Channel names, visibility, groups |
| `config/cooldown.yaml` | 2026-03-14 | Cooldown predictor parameters |
| `config/housekeeping.yaml` | 2026-03-16 | Adaptive throttle, log rotation, stale cleanup |
| `config/notifications.yaml` | 2026-03-14 | Telegram bot/notification parameters (template) |
| `config/notifications.local.yaml.example` | 2026-04-08 | Local override template for notifications |
| `config/plugins.yaml` | 2026-03-31 | Analytics plugin registration |
| `config/shifts.yaml` | 2026-03-17 | Shift handover configuration |
| `config/experiment_templates/*.yaml` | 2026-03-17..21 | 5 experiment templates (cooldown, calibration, etc.) |

### Other files

| File | Purpose |
|---|---|
| `build_scripts/cryodaq.spec` | PyInstaller ONEDIR spec |
| `tsp/p_const.lua` | Draft Keithley TSP supervisor script (not loaded at runtime) |
| `.claude/hooks/inject_context.py` | Claude Code hook for branch-aware context injection |
| `.claude/skills/cryodaq-team-lead.md` | CC skill definition for CryoDAQ team lead |

**Total non-GUI runtime modules:** 62 .py files (excluding `__init__.py`), ~20,968 lines

---

## Section 3 — Correspondence matrix

### 3.1 CLAUDE.md

#### Module Index (lines 114–175)

| CLAUDE.md claim | Status | Evidence |
|---|---|---|
| L117: `src/cryodaq/engine.py` — headless engine | ✓ MATCH | File exists, 1749 lines, matches description |
| L118: `src/cryodaq/launcher.py` — operator launcher | ✓ MATCH | File exists, 827 lines |
| L119: `src/cryodaq/gui/app.py` — standalone GUI entry point | ✓ MATCH | File exists (GUI, not verified in detail) |
| L121–131: 10 core modules listed | ⚠ INCOMPLETE | Lists 10 of 24 core modules. Missing: alarm_v2, alarm_config, alarm_providers, atomic_write, broker, channel_manager, channel_state, disk_monitor, interlock, rate_estimator, sensor_diagnostics, smu_channel, user_preferences, zmq_subprocess |
| L133–137: 2 analytics modules listed | ⚠ INCOMPLETE | Lists 2 of 8. Missing: base_plugin, cooldown_predictor, cooldown_service, plugin_loader, steady_state, vacuum_trend |
| L158–163: 2 storage modules listed | ⚠ INCOMPLETE | Lists 2 of 6. Missing: csv_export, hdf5_export, replay, xlsx_export |
| L165–168: 3 reporting modules listed | ✓ MATCH | All 3 exist |
| L170: web/server.py | ✓ MATCH | Exists |
| L172–175: tools/cooldown_cli.py | ✓ MATCH | Exists |
| L176–179: tsp/p_const.lua | ✓ MATCH | Exists, not loaded at runtime as documented |
| No drivers module index section | ⚠ INCOMPLETE | 7 driver files (base + 3 instruments + 3 transports) not in index |
| No notifications module index section | ⚠ INCOMPLETE | 5 notification files not in index |
| No utility module index section | ⚠ INCOMPLETE | paths.py, logging_setup.py, instance_lock.py, _frozen_main.py not in index |

**Summary: CLAUDE.md module index covers 21 of 62 non-GUI modules (34%). 41 modules undocumented.**

#### Config File List (lines 184–193)

| CLAUDE.md claim | Status | Evidence |
|---|---|---|
| L184: `config/instruments.yaml` | ✓ MATCH | Exists |
| L185: `config/interlocks.yaml` | ✓ MATCH | Exists |
| L186: `config/alarms.yaml` | ⚠ INCOMPLETE | Exists, but `config/alarms_v3.yaml` not listed |
| L187: `config/safety.yaml` | ✓ MATCH | Exists |
| L188: `config/notifications.yaml` | ✓ MATCH | Exists |
| L189: `config/channels.yaml` | ✓ MATCH | Exists |
| L190: `config/cooldown.yaml` | ✓ MATCH | Exists |
| L191: `config/experiment_templates/*.yaml` | ✓ MATCH | 5 templates exist |
| L192: `config/housekeeping.yaml` | ✓ MATCH | Exists |
| L193: `config/*.local.yaml.example` | ✓ MATCH | 2 example files exist |
| Not listed: `config/plugins.yaml` | ⚠ INCOMPLETE | Exists (plugin_loader reads it) |
| Not listed: `config/shifts.yaml` | ⚠ INCOMPLETE | Exists (shift_handover reads it) |

**3 config files missing from CLAUDE.md list.**

#### Architecture Claims (lines 55–88)

| CLAUDE.md claim | Status | Evidence |
|---|---|---|
| L55–59: Three runtime contours (engine, gui, web) | ✓ MATCH | All three exist as described |
| L63–77: Safety architecture (SafetyBroker → SafetyManager, states) | ✓ MATCH | SafetyState enum at safety_manager.py:30-35 matches exactly |
| L69: `request_run() can shortcut SAFE_OFF -> RUNNING` | ✓ MATCH | safety_manager.py:198-201 implements this |
| L70: `stale data -> FAULT + emergency_off` | ✓ MATCH | safety_manager.py stale handling confirmed |
| L71: `dT/dt > 5 K/min -> FAULT` | ✓ MATCH | safety_manager.py:56,700 — default 5.0 K/min |
| L73–74: `Crash-recovery guard: Keithley2604B.connect() forces OUTPUT_OFF` | ✓ MATCH | keithley_2604b.py:101-102 forces OUTPUT_OFF on both channels |
| L79–88: Persistence-first ordering | ✓ MATCH | scheduler.py:341→375→377 — write → broker → safety_broker |

#### Key Rules (lines 200–209)

| CLAUDE.md claim | Status | Evidence |
|---|---|---|
| L201: `SAFE_OFF` — default state | ✓ MATCH | safety_manager.py:80 |
| L202: GUI separate process, not source of truth | ✓ MATCH | ZMQ-bridge pattern enforced |
| L203: Keithley disconnect calls emergency_off | ✓ MATCH | keithley_2604b.py:120 |
| L204: No blocking I/O on engine event loop | ⚠ DRIFT | reporting/generator.py uses sync subprocess.run in async context (DEEP_AUDIT finding E.2) |
| L206: No numpy/scipy in drivers/core | ✓ MATCH | Only sensor_diagnostics.py imports numpy, as documented |
| L207: Scheduler writes to SQLite before publishing | ✓ MATCH | scheduler.py:341→375 confirmed |

#### Build and Version (lines 14–38)

| CLAUDE.md claim | Status | Evidence |
|---|---|---|
| L16: `Python 3.12+, asyncio, PySide6. Current package metadata: 0.13.0` | ✓ MATCH | pyproject.toml version = "0.13.0" |
| L20-28: Build commands | ✓ MATCH | All entry points in pyproject.toml confirmed |
| L42: `CRYODAQ_ROOT` env var | ✓ MATCH | paths.py:40 checks this |
| L43: `CRYODAQ_MOCK=1` | ✓ MATCH | engine.py checks this |
| L46: `config/*.local.yaml` overrides `config/*.yaml` | ✓ MATCH | Pattern used in instruments, notifications |
| L10: `Dual-channel Keithley (smua, smub, smua + smub)` | ✓ MATCH | keithley_2604b.py supports both channels |

#### Known Limitations (lines 211–215)

| CLAUDE.md claim | Status | Evidence |
|---|---|---|
| L212: PDF depends on external soffice/LibreOffice | ✓ MATCH | generator.py:180-200 calls subprocess for soffice |
| L213: WindowsSelectorEventLoopPolicy Python 3.14+ warnings | ✓ MATCH | Known Python issue, cannot verify on Mac but claim is plausible |
| L215: Wheel-install not self-contained | ✓ MATCH | configs outside package, CRYODAQ_ROOT needed |

#### Instruments (line 196–199)

| Claim | Status |
|---|---|
| LakeShore 218S | ✓ MATCH — lakeshore_218s.py |
| Keithley 2604B | ✓ MATCH — keithley_2604b.py |
| Thyracont VSP63D | ✓ MATCH — thyracont_vsp63d.py |

#### Calibration v2 (line 13)

| Claim | Status | Evidence |
|---|---|---|
| Continuous SRDG acquisition during calibration | ✓ MATCH | calibration_acquisition.py |
| Post-run pipeline (extract → downsample → breakpoints → Chebyshev fit) | ✓ MATCH | calibration_fitter.py |
| Three-mode GUI (Setup → Acquisition → Results) | ✓ MATCH (GUI) | calibration_panel.py (not verified in detail) |
| .330 / .340 / JSON export | ✓ MATCH | calibration.py:395 (JSON), :419 (.330), :434 (.340) — all three formats confirmed |
| Runtime apply with per-channel policy | ✓ MATCH | calibration.py has runtime apply with policy |

### 3.2 docs/architecture.md

| Claim area | Status | Notes |
|---|---|---|
| Three-layer architecture (engine/gui/web) | ⚠ DRIFT | architecture.md:21 actually defines six layers, not three. CLAUDE.md's three-contour model is a simplification. (Codex correction) |
| ZMQ PUB/SUB + REQ/REP protocol | ✓ MATCH | zmq_bridge.py implements both |
| Asyncio event loop model | ✓ MATCH | engine.py is asyncio-based |
| Reading dataclass structure | ⚠ DRIFT | architecture.md may not mention `instrument_id` field added later |

### 3.3 docs/deployment.md

| Claim area | Status | Notes |
|---|---|---|
| systemd unit file instructions | ✗ STALE | deployment.md has NO systemd or udev content. Covers launch/build and Windows USB selective-suspend only. (Codex correction — my original MATCH was wrong) |
| USB rules for instruments | ⚠ DRIFT | Covers Windows USB selective-suspend, not Linux udev rules |
| Firewall for web dashboard | ✗ STALE | No firewall guidance in the file |

### 3.4 CHANGELOG.md

| Check | Status | Notes |
|---|---|---|
| Latest entry (0.13.0) matches pyproject.toml | ✓ MATCH | Both say 0.13.0 |
| Latest entry claims accurate | ⚠ INCOMPLETE | Changelog lists Phase 2c features but many post-2c commits not reflected |

### 3.5 Audit documents (DEEP_AUDIT_CC_POST_2C.md etc.)

These 10+ audit documents are **point-in-time snapshots** from 2026-04-09. They are not living documents and are not expected to stay current. No DRIFT/STALE analysis needed — they serve as historical records.

---

## Section 4 — Hardware-verified invariants check

| # | Invariant | Verdict | Evidence |
|---|---|---|---|
| 1 | SAFE_OFF is default state | ✓ HOLDS | safety_manager.py:80 `self._state = SafetyState.SAFE_OFF` |
| 2 | GUI not source of truth for runtime state | ✓ HOLDS | ZMQ REQ/REP pattern — GUI sends commands, engine owns state |
| 3 | Keithley disconnect calls emergency_off first | ✓ HOLDS | keithley_2604b.py:120 `await self.emergency_off()` in disconnect |
| 4 | No blocking I/O on engine event loop | ⚠ PARTIALLY | reporting/generator.py:180 uses `subprocess.run()` (sync) — called from async context. Known audit finding. |
| 5 | No numpy/scipy in drivers/core (except sensor_diagnostics) | ✓ HOLDS | Only `sensor_diagnostics.py:19` imports numpy |
| 6 | Scheduler writes SQLite before publishing to brokers | ✓ HOLDS | scheduler.py:341→375→377 order confirmed |
| 7 | SafetyState FSM: SAFE_OFF→READY→RUN_PERMITTED→RUNNING→FAULT_LATCHED | ⚠ PARTIALLY | safety_manager.py:30 also has MANUAL_RECOVERY state (transitions at :424, :654) not mentioned in CLAUDE.md. (Codex correction) |
| 8 | Fail-on-silence: stale data → FAULT + emergency_off | ⚠ PARTIALLY | Only fires while state=RUNNING (safety_manager.py:666). Outside RUNNING, stale data blocks readiness via preconditions (:601). (Codex correction) |
| 9 | Rate limit: dT/dt > 5 K/min → FAULT | ⚠ PARTIALLY | 5 K/min is configurable default in safety.yaml:29 and safety_manager.py:56, not a hard invariant. (Codex correction) |
| 10 | Keithley connect forces OUTPUT_OFF on both channels | ⚠ PARTIALLY | keithley_2604b.py:97 — attempts force-OFF but logs and continues on failure, not truly "guaranteed". (Codex correction) |
| 11 | Persistence-first: SQLite → DataBroker → SafetyBroker | ✓ HOLDS | scheduler.py ordering confirmed |
| 12 | Safety regulation host-side only (no TSP watchdog) | ✓ HOLDS | tsp/p_const.lua exists as draft, not loaded |

**Result: 7/12 HOLDS, 5 PARTIALLY_HOLDS (blocking I/O in reporting; FSM has 6th state; stale-fault only while RUNNING; rate limit is configurable not fixed; Keithley force-OFF not guaranteed)**

---

## Section 5 — Slash commands and rules check

### .claude/hooks/inject_context.py

Branch-aware context injection hook. Checks `git branch --show-current` and injects context accordingly. No claims about specific modules — this is infrastructure.

### .claude/skills/cryodaq-team-lead.md

Team lead agent skill definition (475 lines). References project structure and conventions. Not audited in detail — it's an agent prompt, not a code-reality claim.

---

## Section 6 — Quick wins (< 10 min each)

*Per Codex review: only items 1-2 are true quick wins. Items 3-7 were reclassified as part of structural change 7.1.*

1. **File:** `CLAUDE.md:186`
   Current text: `- config/alarms.yaml`
   Proposed change: Add `- config/alarms_v3.yaml` on next line
   Reason: alarms_v3 exists and is the primary alarm config for v2 engine

2. **File:** `CLAUDE.md:192` (after housekeeping.yaml)
   Current text: (end of config list)
   Proposed change: Add `- config/plugins.yaml` and `- config/shifts.yaml`
   Reason: Both configs exist and are used by runtime code

---

## Section 7 — Structural changes

### 7.1 CLAUDE.md module index expansion

**Gap:** Module index covers 34% of non-GUI modules. Safety-critical modules (interlock, alarm_v2, rate_estimator, channel_state) are missing.

**New content:** Expand module index to cover all 62 non-GUI modules, grouped by directory. Add one-line description per module.

**Effort:** 2-3 hours
**Priority:** MUST-HAVE — CLAUDE.md is the primary CC instructions file

### 7.2 Config documentation file

**Gap:** No dedicated documentation for config file formats, valid keys, defaults, and interactions. The existing `CONFIG_FILES_AUDIT.md` is a one-time audit, not a living reference.

**New content:** `docs/config_reference.md` documenting each YAML file's schema and defaults.

**Effort:** 4-6 hours
**Priority:** SHOULD-HAVE — operators currently have to read code to understand config options

### 7.3 Notifications architecture doc

**Gap:** No documentation for the Telegram bot, escalation policy, periodic reports, or SecretStr usage. These are operator-facing features with security implications.

**New content:** Section in architecture.md or standalone `docs/notifications.md`

**Effort:** 2 hours
**Priority:** SHOULD-HAVE

### 7.4 Consolidate audit documents

**Gap:** 10+ audit/deep-dive documents at repo root create visual noise. They are point-in-time snapshots, not living docs.

**Change:** Move all audit docs to `docs/audits/` subdirectory. No content changes.

**Effort:** 30 minutes
**Priority:** NICE-TO-HAVE

### 7.5 CHANGELOG.md update

**Gap:** Latest entry is 0.13.0 but many Phase 2a/2b/2c hardening commits landed after. CHANGELOG doesn't reflect current state.

**Change:** Add 0.13.1 entry covering Phase 2a-2c hardening work.

**Effort:** 1 hour
**Priority:** SHOULD-HAVE — release checklist references CHANGELOG

---

### 7.6 Codex review of recommendations

Codex (gpt-5.4, 123k tokens) reviewed Sections 6 and 7:

1. **7.1 should not aim for exhaustive 62-module parity.** CLAUDE.md's role is high-signal orientation, not an encyclopedia. Add safety-critical and frequently-referenced modules (interlock, alarm_v2, broker, rate_estimator, channel_manager, drivers, notifications/telegram), but not every helper. Codex estimates ~15-20 modules added, not 41.

2. **7.4 (audit doc consolidation) is more invasive than stated.** Root-level audit filenames are referenced from code comments (e.g. atomic_write.py:11 references DEEP_AUDIT_CC.md D.3) and from MASTER_TRIAGE.md. Moving files requires updating cross-references.

3. **7.5 (CHANGELOG update) should only happen if a release is being cut.** CHANGELOG.md already has an `Unreleased` bucket at line 53. Adding a 0.13.1 entry prematurely would be incorrect.

4. **Quick wins 3-7 were correctly reclassified** as structural changes (part of 7.1).

5. **Missing org doc:** `.github/workflows/main.yml` exists and was not inventoried in Section 1.

6. **Missing CLAUDE.md claims not checked:** product-model snapshot (L9-12), helper command block (L21-37), "local configs are gitignored" (L48), GUI tab/menu block (L92-111), "GUI text in Russian" rule (L207), Python warning claim (L214). The experiment/debug/report claims at L9-12 are supported by code (experiment.py:347,571,682 and generator.py:57).

---

## Section 8 — What this pass could not verify

1. **Hardware-dependent claims:** KRDG? query format for LakeShore, Thyracont checksum behavior, Keithley TSP execution — require physical instruments
2. **End-to-end data flow:** persistence-first ordering under real load — verified structurally but not under timing pressure
3. **Web dashboard HTML/JS:** `web/server.py` includes embedded HTML template with JavaScript — not audited for XSS or correctness
4. **PyInstaller bundle:** `cryodaq.spec` references paths and hidden imports — cannot verify without building
5. **GUI tab list accuracy:** CLAUDE.md lists 10 GUI tabs (lines 94-105) — GUI is excluded from this audit
6. **Deployment docs on Ubuntu:** deployment.md references systemd and udev — cannot verify on Mac
7. **Reporting PDF generation:** claims about LibreOffice subprocess — cannot verify without soffice installed
8. **Telegram bot behavior:** notification module claims — cannot verify without bot token and network access

---

## Section 9 — Codex checkpoint summaries

### 9.1-9.3 Combined Codex review (gpt-5.4, 123,879 tokens)

Single comprehensive audit covering inventory, correspondence, and recommendations.

**Inventory corrections:** Found `.github/workflows/main.yml` missing from Section 1. No missing Python modules. Noted `web/static/index.html` as non-Python runtime asset.

**Correspondence corrections:** Downgraded 3 MATCH verdicts to DRIFT/STALE (architecture.md layers, deployment.md systemd/udev/firewall claims). Upgraded calibration export DRIFT to MATCH (all three formats confirmed in code). Softened 4 invariant HOLDS verdicts to PARTIALLY_HOLDS with precise line-number evidence.

**Recommendation corrections:** Reclassified quick wins 3-7 as structural. Warned against making CLAUDE.md exhaustively mirror all 62 modules. Advised against premature CHANGELOG entry. Flagged audit-doc-move as more invasive than estimated due to cross-references in code comments.

**Unchecked claims identified:** 6 CLAUDE.md claim blocks that CC did not verify (product model, helper commands, gitignore, GUI tabs, Russian rule, Python warnings).
