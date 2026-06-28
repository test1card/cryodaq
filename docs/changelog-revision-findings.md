# Changelog & CLAUDE.md Revision Findings

Analysis date: 2026-06-28
Based on: 59 commits total, 58 commits after initial merge (9e2ce5b)

---

## 1. Current State Summary

- **pyproject.toml version:** `0.13.0`
- **Last CHANGELOG.md entry:** `[0.13.0] — 2026-03-21`
- **[Unreleased] section exists** with Alarm Engine v2 + T1 Features — but these were already shipped in 0.13.0 or earlier; the section is stale
- **48 commits after 0.13.0** (2026-03-22 through 2026-04-09) have NO changelog coverage
- **CLAUDE.md** (in-repo version) is stale relative to the injected version in the system prompt — missing ~40 entries from the module index, design-system references, Codex self-review loop, CI budget discipline, file encoding policy, release discipline rules, and graphify integration

---

## 2. Commits Not Covered by CHANGELOG.md

### Batch 1 — Audit v2 Fixes (2026-03-22, 10 commits)
| Hash | Summary |
|------|---------|
| 44c399f | feat: audit v2 fixes — flock, housekeeping thread, preflight API, conductivity ID, web client, docs |
| 8f50ff4 | fix: bridge restart with engine, open GUI-only from tray, legend rename sync |
| 3185e3a | fix(engine): helpful lock errors, --force flag, stale auto-cleanup, tray safety state |
| 0171ca0 | hotfix: fix _is_port_busy, Windows lock probe, gui __main__.py |
| de4f6e4 | fix: web non-blocking commands + multi-DB history + overview decimated history + card staleness |
| a177b2d | fix(conductivity): full rebuild on channel change, CSV utf-8-sig |
| 2e80634 | fix: channel fallback sync, docs cleanup, architecture notes |
| 9286fd6 | fix(zmq): robust reply consumer, overflow logging, error messages |
| 4bef250 | fix: preflight sensor check, canonical ID resolve, test soffice tolerance |
| 0fdc507 | merge: audit-v2 fixes (29 defects, 9 commits) |

### Batch 2 — Storage, Archive, CI (2026-03-22, 4 commits)
| Hash | Summary |
|------|---------|
| fc1c61b | feat(storage): Parquet experiment archive — write readings.parquet alongside CSV on finalize |
| ccf98c9 | Add CI workflow for CryoDAQ with testing and linting |
| f0c68c6 | feat(archive): Parquet column in table, human-readable artifacts, parquet read fix |
| 423c6d5 | fix(archive): inclusive end-date filter, add end time column |

### Batch 3 — Professional Reporting (2026-03-22, 3 commits)
| Hash | Summary |
|------|---------|
| 8dc07f7 | feat(reporting): professional human-readable reports for all experiment types |
| a066cd7 | feat(reporting): ГОСТ Р 2.105-2019 formatting, all graphs in all reports |
| b7265bb | fix(reporting): multi-channel graphs, black headings, smart page breaks |

### Batch 4 — GPIB Recovery (2026-03-23, 3 commits)
| Hash | Summary |
|------|---------|
| ab57e01 | fix(gpib): auto-recovery from hung instruments — clear bus on timeout, preventive clear |
| ea5a8da | fix(gpib): IFC bus reset, enable unaddressing, escalating recovery |
| 29d2215 | fix: audit regression — preflight severity, multi-day DB, overview resolver, parquet docstring |

### Batch 5 — Preflight, Scheduler, GUI Hardening (2026-03-23 to 2026-03-24, 12 commits)
| Hash | Summary |
|------|---------|
| 86e8e8c | fix(preflight): sensor health is warning not error |
| c10e617 | fix(scheduler): standalone instrument disconnect+reconnect on consecutive errors |
| dfd6021 | fix(preflight): restore encoding + sensor health warning not error |
| 8bac038 | fix(gui): non-blocking alarm v2 status poll |
| 6d0f5ba | fix(gui): bridge heartbeat false kills + launcher blocking send_command |
| bab4d8a | feat: single-instance protection for launcher and standalone GUI |
| 4eb5f1a | fix(gui): launcher bridge health gap + conductivity blocking send_command |
| 3c46dfb | fix(gui): keithley spinbox debounce + non-blocking live update |
| e7d4fc5 | fix(gui): experiment workspace 1080p layout — phase bar + passport forms |
| f47762d | fix: launcher non-blocking engine restart + deployment hardening |
| f217427 | fix: shift modal re-entrancy + engine --force PermissionError |

### Batch 6 — Codex Audit Fixes (2026-03-31 to 2026-04-01, 2 commits)
| Hash | Summary |
|------|---------|
| 9676165 | fix: Codex audit — plugins.yaml Latin T, sensor_diagnostics resolution, GUI non-blocking |
| 9feaf3e | fix: audit - GUI non-blocking send_command + dead code cleanup |

### Batch 7 — Phase 1-2c Pre-Deployment Hardening (2026-04-08, 5 commits)
| Hash | Summary |
|------|---------|
| a60abc0 | fix: Phase 1 pre-deployment — unblock PyInstaller build |
| 0333e52 | fix: Phase 2a safety hardening — close 4 HIGH findings |
| 8a24ead | fix: Phase 2b observability & resilience — close 8 MEDIUM findings |
| b185fd3 | fix: Phase 2c final hardening — close 8 findings before Phase 3 |
| 1698150 | ui: replace Overview "Сутки" preset with "Всё" |

### Batch 8 — Audit Documentation (2026-04-09, 9 commits)
| Hash | Summary |
|------|---------|
| 380df96 | audit: deep audit pass (CC) post-2c |
| fd99631 | audit: deep audit pass (Codex overnight) post-2c |
| fd8c8bf | chore: gitignore local audit artifacts |
| 847095c | audit: cherry-pick hardening pass document |
| 5d618db | audit: verification pass - re-check 5 HIGH findings |
| 10667df | audit: SafetyManager exhaustive FSM analysis |
| 31dbbe8 | audit: persistence-first invariant exhaustive trace |
| 3e20e86 | audit: driver layer fault injection scenarios |
| 916fae4 | audit: full dependency CVE sweep with version verification |
| a108519 | audit: reporting + analytics + plugins deep dive |
| 24b928d | audit: configuration files security and consistency audit |
| 7aaeb2b | audit: master triage synthesis of all audit documents |

---

## 3. CLAUDE.md Findings — What Needs Updating

The in-repo `CLAUDE.md` (216 lines) is significantly behind the injected version in the system prompt (~385 lines). Key deltas:

### 3.1 Stale / incorrect entries
- **Calibration v2:** in-repo says `.330 / .340 / JSON export`; injected version says `.330` format removed (architect decision 2026-04-25), `.cof` format added. Both are potentially stale — need architect clarification on current format set
- **SafetyManager FSM:** in-repo shows 5 states (missing `MANUAL_RECOVERY`); injected version has 6 states with `MANUAL_RECOVERY` documented
- **GUI module index:** in-repo still references `src/cryodaq/gui/main_window.py` — retired in Phase II.13; replaced by `gui/shell/main_window_v2.py`
- **GUI widgets:** still lists `autosweep_panel.py` as DEPRECATED, plus several panels deleted in II.13
- **Parquet archive:** in-repo says `pyarrow optional`; injected says pyarrow is now base dep since IV.4
- **pip install line:** in-repo shows `[dev,web,archive]` as separate extra; injected says `archive` extra is a no-op alias
- **Package metadata:** says `0.13.0` — potentially stale depending on version bump decision
- **Missing "no blocking I/O" exception:** injected version adds `(known exception: reporting/generator.py uses sync subprocess.run() for LibreOffice PDF conversion — DEEP_AUDIT finding E.2)`
- **Crash-recovery guard:** in-repo says "known-safe state is guaranteed"; injected version correctly says "best-effort: if force-OFF fails, logs CRITICAL and continues — not guaranteed"

### 3.2 Missing sections (present in injected, absent in-repo)
- `## Чтение перед началом сессии (READ FIRST — mandatory)` — priority reading order
- `## Источник истины по UI/визуальному дизайну` — design system reference
- `## Снимок сверки` update — Calibration v2 details with `.cof` format
- `## Дисциплина релизов` — release boundary documentation rules
- `## Codex self-review loop` — full autonomous review workflow
- `## CI budget discipline` — test suite rules for block vs amend commits
- `## Кодировка файлов` — UTF-8 without BOM policy
- `## graphify` — knowledge graph integration
- **30+ module index entries** — shell/, dashboard/, overlays/, design system primitives, theme.py, zmq_client.py, instance_lock.py, logging_setup.py, paths.py, etc.
- **New config files:** `config/alarms_v3.yaml`, `config/plugins.yaml`, `config/shifts.yaml`
- **New core modules:** alarm_v2.py, alarm_config.py, alarm_providers.py, atomic_write.py, channel_state.py, disk_monitor.py, phase_labels.py, rate_estimator.py, smu_channel.py, user_preferences.py, zmq_subprocess.py

### 3.3 Missing modules from index (code exists, not listed)
- `src/cryodaq/__main__.py`
- `src/cryodaq/_frozen_main.py`
- `src/cryodaq/gui/__main__.py`
- `src/cryodaq/instance_lock.py`
- `src/cryodaq/logging_setup.py`
- `src/cryodaq/paths.py`
- `src/cryodaq/notifications/escalation.py`
- `src/cryodaq/notifications/_secrets.py`
- `src/cryodaq/analytics/cooldown_predictor.py`
- `src/cryodaq/analytics/cooldown_service.py`
- `src/cryodaq/analytics/steady_state.py`
- `src/cryodaq/analytics/vacuum_trend.py`
- `src/cryodaq/analytics/plugin_loader.py`
- `src/cryodaq/analytics/base_plugin.py`
- `src/cryodaq/storage/parquet_archive.py` (listed but described as optional)
- `src/cryodaq/storage/csv_export.py`
- `src/cryodaq/storage/hdf5_export.py`
- `src/cryodaq/storage/xlsx_export.py`
- `src/cryodaq/storage/replay.py`
- All `gui/shell/` modules (main_window_v2, top_watch_bar, tool_rail, bottom_status_bar, overlay_container, new_experiment_dialog, experiment_overlay)
- All `gui/dashboard/` modules
- All `gui/shell/overlays/_design_system/` modules

---

## 4. [Unreleased] Section — Stale Content

The current `[Unreleased]` block in CHANGELOG.md describes:
- Alarm Engine v2
- T1 Features (Web / Telegram / Pre-flight / Auto-fill)

These features appear to have been part of the 0.13.0 release or earlier development. The `[Unreleased]` section should either be:
1. Merged into `[0.13.0]` if they shipped with that release, or
2. Re-tagged under a new version number

---

## 5. Proposed Revised Changelog — Alternative Versioning

The current scheme uses 0.x.0 increments for every release. Below are three alternative proposals.

---

### Proposal A — Granular SemVer (PATCH for fixes, MINOR for features)

This scheme respects semantic versioning strictly. Feature additions get MINOR bumps; pure bugfix/hardening batches get PATCH bumps. Groups by natural delivery date.

```
## [0.13.0] — 2026-03-21 (existing, unchanged)

## [0.13.1] — 2026-03-22  "Audit v2 Stabilization"
### Fixed
- Engine lock upgraded to flock/msvcrt (kernel-level exclusive) (44c399f)
- Housekeeping gzip moved to asyncio.to_thread (no event loop block) (44c399f)
- PreFlight rewritten against real engine API (safety_status, alarm_v2_status) (44c399f)
- ZMQ robust reply consumer with overflow logging (9286fd6)
- Web non-blocking commands + multi-DB history + overview decimated history (de4f6e4)
- Bridge restart with engine, open GUI-only from tray (8f50ff4)
- Engine helpful lock errors, --force flag, stale auto-cleanup (3185e3a)
- Windows _is_port_busy fix + lock probe (0171ca0)
- Conductivity full rebuild on channel change, CSV utf-8-sig (a177b2d)
- Channel fallback sync (2e80634)
- Preflight sensor check, canonical ID resolve (4bef250)

## [0.14.0] — 2026-03-22  "Storage & Reporting"
### Added
- Parquet experiment archive — readings.parquet alongside CSV on finalize (fc1c61b)
- Archive panel: Parquet column, human-readable artifacts (f0c68c6)
- CI workflow for CryoDAQ with testing and linting (ccf98c9)
- Professional human-readable reports for all experiment types (8dc07f7)
- ГОСТ Р 2.105-2019 report formatting, all graphs in all reports (a066cd7)
### Fixed
- Archive inclusive end-date filter, add end time column (423c6d5)
- Reporting multi-channel graphs, black headings, smart page breaks (b7265bb)
- Audit regression — preflight severity, multi-day DB, overview resolver, parquet docstring (29d2215)

## [0.14.1] — 2026-03-23  "GPIB Auto-Recovery"
### Fixed
- GPIB auto-recovery from hung instruments — clear bus on timeout, preventive clear (ab57e01)
- GPIB IFC bus reset, enable unaddressing, 3-level escalating recovery (ea5a8da)

## [0.14.2] — 2026-03-24  "GUI Hardening"
### Added
- Single-instance protection for launcher and standalone GUI (bab4d8a)
### Fixed
- Preflight sensor health is warning not error (86e8e8c, dfd6021)
- Scheduler standalone instrument disconnect+reconnect on consecutive errors (c10e617)
- GUI non-blocking alarm v2 status poll (8bac038)
- Bridge heartbeat false kills + launcher blocking send_command (6d0f5ba)
- Launcher bridge health gap + conductivity blocking send_command (4eb5f1a)
- Keithley spinbox debounce + non-blocking live update (3c46dfb)
- Experiment workspace 1080p layout — phase bar + passport forms (e7d4fc5)
- Launcher non-blocking engine restart + deployment hardening (f47762d)
- Shift modal re-entrancy + engine --force PermissionError (f217427)

## [0.14.3] — 2026-04-01  "Codex Audit Round"
### Fixed
- plugins.yaml Latin T, sensor_diagnostics resolution, GUI non-blocking (9676165)
- GUI non-blocking send_command + dead code cleanup (9feaf3e)

## [0.15.0] — 2026-04-08  "Pre-Deployment Hardening"
### Added
- PyInstaller build readiness: _frozen_main.py, cryodaq.spec, build scripts (a60abc0)
- Frozen-mode subprocess dispatch for launcher (a60abc0)
- Centralized paths.py: is_frozen(), get_logs_dir(), get_plugins_dir(), get_tsp_dir() (a60abc0)
- atomic_write.py — atomic file write via os.replace() (a60abc0)
- Log rotation via TimedRotatingFileHandler (14-day backup) (8a24ead)
- Token redaction filter for Telegram secrets in logs (8a24ead)
- SecretStr wrapper for token leak prevention (8a24ead)
- Engine config error exit code 2 + launcher restart backoff (8a24ead)
- ZMQ bind retry with exponential backoff + LINGER=0 (8a24ead)
- VISA executor isolation for GPIB/USB-TMC transports (8a24ead)
- Apache 2.0 LICENSE file (b185fd3)
- requirements-lock.txt for reproducible builds (b185fd3)
- Upper bounds on all 14 runtime deps (b185fd3)
### Changed
- Overview preset: "Сутки" replaced with "Всё" (1698150)
- Thyracont checksum validation default flipped to True (b185fd3)
### Fixed
- Keithley crash-recovery: connect() forces OUTPUT_OFF on both channels (0333e52)
- emergency_off readback verification via _verify_output_off() (0333e52)
- Disk-full graceful degradation in SQLiteWriter (0333e52)
- Interlock action dispatch: emergency_off / stop_source / latch_fault (0333e52)
- SafetyManager MANUAL_RECOVERY state, timer-guarded re-entry (0333e52)
- LakeShore IDN validation with retry-after-clear (b185fd3)
- Telegram command bot: allowlisted chats, phase vocabulary (8a24ead)
- 6 baseline test failures resolved — 819 passed / 0 failed (b185fd3)
### Infrastructure
- 9 audit documents committed (380df96 through 7aaeb2b)
- Master triage synthesis of all findings (7aaeb2b)
- .gitignore for local audit artifacts (fd8c8bf)
### Test baseline
- 819 passed, 0 failed (Phase 2c milestone)
```

---

### Proposal B — Milestone-Based (Fewer Versions, Larger Scope)

Consolidates all post-0.13.0 work into two milestone releases aligned to
the actual development phases: stabilization (March) and hardening (April).

```
## [0.13.0] — 2026-03-21  (existing, unchanged)

## [0.14.0] — 2026-03-24  "Post-Audit Stabilization"
### Added
- Parquet experiment archive — readings.parquet alongside CSV on finalize
- CI workflow for CryoDAQ with testing and linting
- Professional human-readable ГОСТ Р 2.105-2019 reports for all experiment types
- Archive panel: Parquet column, human-readable artifacts
- Single-instance protection for launcher and standalone GUI
- GPIB 3-level escalating recovery (SDC → IFC → full disconnect cycle)
### Fixed
- 29 audit-v2 defects (engine lock, housekeeping, preflight, ZMQ, web, conductivity)
- Archive inclusive end-date filter
- Reporting multi-channel graphs, page breaks
- Preflight sensor health severity downgraded to warning
- Scheduler instrument auto-reconnect on consecutive errors
- 11 GUI non-blocking fixes (alarm poll, bridge heartbeat, keithley spinbox, experiment workspace 1080p)
- Launcher non-blocking restart + deployment hardening
- Shift modal re-entrancy

## [0.15.0] — 2026-04-09  "Lab Deployment Readiness"
### Added
- PyInstaller frozen bundle: _frozen_main.py, cryodaq.spec, build.sh/build.bat, post_build.py
- Centralized path resolution: is_frozen(), get_logs_dir(), get_plugins_dir()
- Structured logging with rotation (TimedRotatingFileHandler, 14-day)
- Token redaction filter (Telegram bot tokens in logs)
- SecretStr wrapper for credential hygiene
- Engine config error exit code + launcher restart backoff (5 attempts, exponential)
- ZMQ bind retry with backoff + LINGER=0
- VISA executor isolation for transports
- Apache 2.0 LICENSE
- requirements-lock.txt (reproducible builds, pip-compile, upper bounds on 14 deps)
- atomic_write.py (os.replace)
### Changed
- Overview time preset: "Сутки" → "Всё"
- Thyracont checksum validation default: off → on
- SafetyManager: 5-state → 6-state FSM (added MANUAL_RECOVERY)
### Fixed
- Keithley crash-recovery: force OUTPUT_OFF on connect + readback verification on emergency_off
- Disk-full graceful degradation in SQLiteWriter
- Interlock action dispatch (emergency_off / stop_source / latch_fault distinction)
- LakeShore *IDN? validation with retry-after-clear
- Telegram bot: allowlisted chats, phase vocabulary corrections
- Codex audit: plugins.yaml, sensor_diagnostics resolution, dead code removal
- 6 inherited test failures resolved
### Infrastructure
- 9 deep audit documents (SafetyManager FSM, persistence invariant, driver fault injection, CVE sweep, config audit, reporting deep dive, hardening pass, verification pass, master triage)
- .gitignore for audit artifacts and graphify-out/
### Test baseline
- 819 passed / 0 failed (first clean baseline)
```

---

### Proposal C — Date-Tagged RC Cadence (Release Candidate Flow to 1.0)

Reframes the project as approaching 1.0 readiness. Each batch is an RC
towards the first lab deployment release.

```
## [0.13.0] — 2026-03-21  (existing, unchanged — last feature release)

## [1.0.0-rc1] — 2026-03-22  "Audit Stabilization + Storage"
### Added
- Parquet experiment archive (readings.parquet on finalize, zstd compression)
- CI workflow (GitHub Actions: pytest + ruff)
- Professional ГОСТ Р 2.105-2019 reports with graphs for all experiment types
- Archive: Parquet column, human-readable artifacts, end time column
### Fixed
- 29 audit-v2 defects across engine, ZMQ, web, preflight, conductivity
- Reporting: multi-channel graphs, page breaks, headings
- Audit regression fixes (preflight severity, multi-day DB, parquet)

## [1.0.0-rc2] — 2026-03-24  "Reliability"
### Added
- GPIB 3-level escalating recovery (SDC → IFC → full reconnect)
- Single-instance protection (flock/msvcrt)
### Fixed
- 11 GUI non-blocking conversions (alarm, bridge, keithley, launcher, conductivity)
- Preflight sensor health: error → warning
- Scheduler auto-reconnect on consecutive instrument errors
- Experiment workspace 1080p layout
- Shift modal re-entrancy
- Launcher non-blocking restart + deployment hardening

## [1.0.0-rc3] — 2026-04-01  "Codex Audit"
### Fixed
- plugins.yaml encoding, sensor_diagnostics resolution
- Dead code removal
- GUI non-blocking send_command cleanup

## [1.0.0-rc4] — 2026-04-08  "Frozen Bundle + Safety Hardening"
### Added
- PyInstaller frozen bundle support (Windows ONEDIR)
- Structured log rotation (14-day, token redaction)
- SecretStr credential wrapper
- Engine config exit code + launcher backoff
- ZMQ bind retry, VISA executor isolation
- Apache 2.0 LICENSE, requirements-lock.txt (reproducible builds)
- atomic_write.py
### Changed
- SafetyManager: 6-state FSM (added MANUAL_RECOVERY)
- Overview: "Всё" replaces "Сутки"
- Thyracont checksum validation on by default
### Fixed
- Keithley crash-recovery (force-OFF on connect, readback on emergency_off)
- Disk-full SQLiteWriter graceful degradation
- Interlock action dispatch
- LakeShore IDN validation
- Telegram allowlisted chats + phase vocabulary
- 6 baseline test failures → 819 passed / 0 failed

## [1.0.0] — TBD  "First Lab Deployment"
### Infrastructure
- 9 deep audit documents committed and triaged
- Master triage synthesis (MASTER_TRIAGE.md)
- All CRITICAL/HIGH findings closed
- Phase 3 pending: Ubuntu deployment, real hardware verification
```

---

## 6. Recommendation

**Proposal A** is the most accurate and traceable option — each version maps to a natural commit batch with clear dates and commit hashes. It follows SemVer strictly.

**Proposal B** is pragmatic if the team prefers fewer version numbers and the project was never actually "released" between these batches.

**Proposal C** is appropriate if the team is targeting a 1.0 milestone for first real lab deployment. The current 0.x scheme implies pre-production, and the Phase 1-2c hardening work reads like release candidate stabilization.

### My recommendation:
- If lab deployment has already happened or is imminent → **Proposal C** (RC flow to 1.0)
- If the project continues iterating without a formal "production" milestone → **Proposal A** (granular SemVer)
- If minimal changelog overhead is the priority → **Proposal B** (milestone-based)

In all cases, the `[Unreleased]` section should be removed — its contents (Alarm Engine v2, T1 Features) are already shipped.

---

## 7. CLAUDE.md Update Scope (Summary)

When the time comes to update CLAUDE.md, the following categories of changes are needed:

1. **Add 7 new top-level sections** (READ FIRST, design system, release discipline, Codex self-review, CI budget, file encoding, graphify)
2. **Update SafetyManager FSM** (add MANUAL_RECOVERY state, fix crash-recovery guard wording)
3. **Update Calibration v2 snapshot** (remove .330, add .cof if architect confirms)
4. **Replace GUI module index** (~30 new entries for shell/, dashboard/, overlays/)
5. **Retire stale GUI references** (main_window.py → main_window_v2.py, remove deleted panels)
6. **Add ~15 new core module entries** (alarm_v2, atomic_write, channel_state, disk_monitor, etc.)
7. **Add ~8 new analytics/notification/storage entries**
8. **Update config file list** (add alarms_v3.yaml, plugins.yaml, shifts.yaml)
9. **Update pip install line** (pyarrow is base dep, archive extra is no-op)
10. **Add "no blocking I/O" exception** for reporting/generator.py
11. **Update known limitations** with crash-recovery guard best-effort caveat
