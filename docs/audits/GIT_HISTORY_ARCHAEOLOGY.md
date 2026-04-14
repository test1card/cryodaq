# GIT_HISTORY_ARCHAEOLOGY.md

**Generated:** 2026-04-14
**Method:** `git log master --first-parent --format=...` + per-commit `--stat` + test file counts at phase boundaries
**Scope:** All 200 first-parent commits on master (229 total including merge parents)

---

## Timeline overview

```
2026-03-14       Foundation: initial system, all subsystems scaffolded (27 commits)
2026-03-14       Safety: persistence-first, audit fixes, P0/P1 deployment (14 commits)
2026-03-15..17   Codex RC: merge CRYODAQ-CODEX into master (1 merge + 1 chore)
2026-03-17       Post-merge: calibration v2, shift handover, experiment phases (25 commits)
2026-03-18       v0.12.0 release + post-release features (alarm v2, web, preflight) (16 commits)
2026-03-18..19   Hardware deployment: GPIB iterations, Thyracont V1, Keithley host P=const (17 commits)
2026-03-19..20   ZMQ + Analytics: subprocess isolation, SensorDiag, VacuumTrend (10 commits)
2026-03-20..21   Safety phases 2-3 + feature/ui-refactor merge (8 commits)
2026-03-21       feature/final-batch merge + post-merge fixes (11 commits)
2026-03-22       audit-v2 merge + Parquet v1 + CI + reporting ГОСТ (9 commits)
2026-03-23..24   GPIB recovery + preflight fixes (5 commits)
2026-03-24       GUI non-blocking + single-instance + deployment hardening (11 commits)
2026-03-25..04-01 Codex audit + dead code cleanup (2 commits)
2026-04-08       Phase 1/2a/2b/2c: 4 structured hardening passes (5 commits)
2026-04-09       Audit cycle: 11 deep-dive documents (13 commits)
2026-04-12..13   Documentation discovery: DOC_REALITY_MAP, skill rewrite, CLAUDE.md (4 commits)
2026-04-13..14   Phase 2d: safety + persistence + config fail-closed (16 commits)
2026-04-14       Phase 2e: Parquet streaming + audit docs (3 commits)
```

---

## Phase-by-phase breakdown

## Phase: Foundation (2026-03-14)

**Commit range:** `be52137`..`dc5f3c6`
**Date range:** 2026-03-14 00:29 → 2026-03-14 18:13
**Number of commits:** 32
**Test files at end:** 0 (tests added later in dedicated commit)

### Key commits

| SHA | Time | Title | +/- |
|---|---|---|---|
| be52137 | 00:29 | Add CLAUDE.md with project architecture and constraints | +35 |
| f7cdc00 | 00:35 | Add project foundation: pyproject.toml, directory structure, driver ABC, DataBroker | +257/17f |
| 2882845 | 00:39 | Add SQLiteWriter, ZMQ bridge, and instrument Scheduler | +565/4f |
| 0c54010 | 00:43 | Add LakeShore 218S driver, temperature panel GUI, and tests | +1255/9f |
| 577b02f | 01:18 | Keithley 2604B: TSP P=const, driver, interlocks | +1780/5f |
| 75ebdc1 | 01:23 | Add AlarmEngine, analytics plugin pipeline, and two plugins | +1606/8f |
| 0b79fa1 | 01:48 | Engine + GUI: entry points, main window, alarm panel, instrument status | +1167/5f |
| baaec03 | 01:53 | Experiment lifecycle, data export, replay, Telegram notifications | +1124/6f |
| 167eb7d | 03:13 | Thyracont VSP63D driver, periodic reports, live web dashboard | +1898/-200 |
| 603a472 | 13:29 | Safety architecture: SafetyManager, SafetyBroker, fail-on-silence | +1093/-40 |
| 9217489 | 18:49 | Cooldown predictor integration: library refactor, service, GUI, tests | +2272/-335 |

### Themes
- Complete system scaffolding in ~18 hours: 3 drivers, safety FSM, experiment lifecycle, GUI tabs, web dashboard, Telegram, analytics plugins, cooldown predictor
- "Add files via upload" commits (6 total) — binary/large files uploaded via GitHub web UI
- persistence-first ordering established (`a8e8bbf`)

---

## Phase: Test suite + deployment (2026-03-14..03-15)

**Commit range:** `734f641`..`61dca77`
**Date range:** 2026-03-14 02:27 → 2026-03-15 03:48
**Number of commits:** 15
**Test files at end:** ~16 (initial test suite)

### Key commits

| SHA | Time | Title | +/- |
|---|---|---|---|
| 734f641 | 03-14 02:27 | Add comprehensive test suite: 118 tests across all modules | +2972/16f |
| e9a538f | 03-14 23:17 | SAFETY: 14 audit fixes — FAULT_LATCHED latch, status checks, heartbeat | +517/-81 |
| 1bd6c4e | 03-15 02:39 | P0: 5 critical fixes — alarm pipeline, safety state, P/V/I limits | +608/-19 |
| de715dc | 03-15 03:02 | P1: 8 lab deployment fixes — async ZMQ, REAL timestamps, paths, sessions | +993/-173 |
| 61dca77 | 03-15 03:48 | BREAKING: instrument_id is now a first-class field on Reading dataclass | +106/-69/37f |

### Themes
- Initial test suite (118 tests)
- First safety audit (14 fixes)
- P0 critical fixes before first lab test
- P1 deployment fixes discovered during first hardware run
- BREAKING change: instrument_id promoted to Reading field (touched 37 files)

---

## Phase: Codex RC merge (2026-03-17)

**Commit:** `dc2ea6a`
**Date:** 2026-03-17 15:33
**Stats:** +14690/-6632/83f (massive merge)

A large merge commit integrating work from `CRYODAQ-CODEX` branch (Codex-assisted development). This single merge brought in backend workflows (experiments, reports, housekeeping, calibration), GUI workflows (tray status, operator hardening), and packaging metadata sync.

---

## Phase: Post-merge features (2026-03-17)

**Commit range:** `29652a2`..`98a5951`
**Date range:** 2026-03-17 16:00 → 2026-03-17 20:11
**Number of commits:** 18

### Key commits

| SHA | Time | Title |
|---|---|---|
| b6ddb4e | 17:03 | feat: dashboard hub — Keithley quick-actions, quick log, experiment status |
| f910c40 | 17:14 | feat: structured shift handover — start, periodic prompts, end summary |
| 81ef8a6 | 19:42 | feat: continuous SRDG acquisition during calibration experiments |
| e694d2d | 19:52 | feat: calibration v2 post-run pipeline — extract, downsample, breakpoints, fit |
| 38aca4f | 19:57 | feat: calibration v2 GUI — three-mode panel with coverage and auto-fit |
| aad5eab | 20:41 | feat: experiment phase tracking — preparation through teardown |
| d8421e6 | 20:53 | feat: auto-log system events, auto-generate report on finalize |

### Themes
- Calibration v2 full pipeline (acquisition → fitter → GUI)
- Shift handover system
- Experiment phase tracking
- Overview layout iterations (5 commits of layout changes)

---

## Phase: v0.12.0 release + alarm v2 (2026-03-18)

**Commit range:** `c22eca9`..`c7ae2ed`
**Date range:** 2026-03-18 00:10 → 2026-03-18 10:59
**Number of commits:** 14

### Key commits

| SHA | Time | Title |
|---|---|---|
| c22eca9 | 00:10 | release: v0.12.0 — first production release |
| 7ee15de | 00:52 | feat: web dashboard — read-only monitoring page with auto-refresh |
| e553f11 | 00:58 | feat: telegram bot v2 — /status, /log, /temps, /phase, escalation chain |
| ae70158 | 01:00 | feat: pre-flight checklist before experiment start |
| 88357b8 | 02:16 | feat: alarm v2 foundation — RateEstimator and ChannelStateTracker |
| 046ab6f | 02:22 | feat: alarm v2 evaluator — composite, rate, threshold, stale checks |
| 3f86b42 | 02:26 | feat: alarm v2 providers and config parser |
| 8070b2d | 02:30 | feat: alarm v2 integration in engine |

### Themes
- v0.12.0 tagged as first production release
- Alarm v2 full stack (4 commits in 15 minutes: foundation → evaluator → providers → integration)
- Telegram bot v2, web dashboard v2, pre-flight checklist
- Post-release memory leak fixes

---

## Phase: Hardware deployment (2026-03-18..19)

**Commit range:** `d7c843f`..`f64d981`
**Date range:** 2026-03-18 17:12 → 2026-03-19 16:41
**Number of commits:** 15

### Key commits

| SHA | Time | Title |
|---|---|---|
| d7c843f | 03-18 17:12 | fix: first hardware deployment — GPIB bus lock, Thyracont V1, Keithley source-off |
| 4f717a5 | 03-18 17:23 | fix: keithley source-off NaN → SQLite NOT NULL crash |
| 8605a52 | 03-19 11:14 | fix: thyracont VSP63D connect via V1 protocol probe |
| d94e361 | 03-19 12:41 | fix: VISA bus lock to prevent -420 Query UNTERMINATED race |
| 94ec2b6 | 03-19 13:15 | refactor: keithley P=const host-side control loop, remove blocking TSP |
| bb59488 | 03-19 14:29 | fix: GPIB open-per-query + IFC bus reset on timeout |
| 946b454 | 03-19 14:50 | refactor: GPIB sequential polling — single task per bus |
| 7efb8b7 | 03-19 16:21 | refactor: GPIB persistent sessions — LabVIEW-style open-once |
| f64d981 | 03-19 16:41 | feat: isolate ZMQ into subprocess — GUI never imports zmq |

### Themes
- 8 GPIB-related commits in 2 days — iterative bus locking/recovery strategy
- Thyracont V1 protocol reverse-engineering (3 formula corrections)
- Keithley NaN crash fix, host-side P=const migration
- ZMQ subprocess isolation

---

## Phase: Analytics + Safety phases 2-3 (2026-03-20..21)

**Commit range:** `856ad19`..`1ec93a6`
**Date range:** 2026-03-20 13:04 → 2026-03-21 02:39
**Number of commits:** 14

### Key commits

| SHA | Time | Title |
|---|---|---|
| 757f59e | 03-20 13:22 | feat: SensorDiagnosticsEngine — backend + 20 unit tests |
| 5d7fe2b | 03-20 13:56 | feat: VacuumTrendPredictor — backend + 20 unit tests |
| 6ef43df | 03-20 20:12 | feat: Phase 2 safety hardening — tests + bugfixes + LakeShore RDGST? |
| bbb5809 | 03-20 20:42 | feat: Phase 3 — safety correctness, reliability, phase detector |
| 10d4d76 | 03-20 22:39 | fix(audit): 6 bugs — safety race, SQLite shutdown, Inf filter |
| 1ec93a6 | 03-21 02:39 | merge: feature/ui-refactor |

### Themes
- SensorDiagnostics 3-stage rollout (backend → engine → GUI)
- VacuumTrendPredictor 3-stage rollout
- Safety phases 2 & 3 (correctness, reliability)
- feature/ui-refactor merge

---

## Phase: Merges + Parquet v1 + reporting (2026-03-21..22)

**Commit range:** `c427247`..`29d2215`
**Date range:** 2026-03-21 02:54 → 2026-03-23 00:37
**Number of commits:** 20

### Key commits

| SHA | Time | Title |
|---|---|---|
| 9e2ce5b | 03-21 15:20 | merge: final-batch |
| 4df40c3 | 03-21 16:15 | fix(critical): atomic single-instance lock via O_CREAT|O_EXCL |
| 6d39a08 | 03-21 17:34 | fix(critical): move experiment I/O to thread |
| 0fdc507 | 03-22 16:11 | merge: audit-v2 fixes (29 defects, 9 commits) |
| fc1c61b | 03-22 16:35 | feat(storage): Parquet experiment archive v1 |
| 8dc07f7 | 03-22 19:18 | feat(reporting): professional human-readable reports |
| a066cd7 | 03-22 20:51 | feat(reporting): ГОСТ Р 2.105-2019 formatting |

### Themes
- Two branch merges (final-batch, audit-v2)
- Parquet v1 (load-all approach, later replaced by streaming in Phase 2e)
- Report formatting to ГОСТ standard
- Critical fixes (atomic lock, experiment I/O threading)

---

## Phase: Pre-hardening fixes (2026-03-23..04-01)

**Commit range:** `ab57e01`..`9feaf3e`
**Date range:** 2026-03-23 14:59 → 2026-04-01 03:57
**Number of commits:** 13

### Key commits

| SHA | Time | Title |
|---|---|---|
| ab57e01 | 03-23 14:59 | fix(gpib): auto-recovery from hung instruments |
| ea5a8da | 03-23 15:15 | fix(gpib): IFC bus reset, enable unaddressing, escalating recovery |
| bab4d8a | 03-24 14:15 | feat: single-instance protection for launcher and GUI |
| 9676165 | 03-31 03:17 | fix: Codex audit — plugins.yaml Latin T, sensor_diagnostics resolution |
| 9feaf3e | 04-01 03:57 | fix: audit - GUI non-blocking send_command + dead code cleanup (57f) |

### Themes
- GPIB escalating recovery (clear → IFC → unaddress)
- GUI non-blocking audit (largest single commit at 57 files changed)
- Single-instance protection
- Codex-driven Latin T / Cyrillic Т fix

---

## Phase 1/2a/2b/2c (2026-04-08)

**Commit range:** `a60abc0`..`1698150`
**Date range:** 2026-04-08 16:58 → 2026-04-08 22:16
**Number of commits:** 5
**Test files before → after:** 91 → 108 (+17 test files)

### Key commits

| SHA | Time | Title | +/- |
|---|---|---|---|
| a60abc0 | 16:58 | fix: Phase 1 pre-deployment — unblock PyInstaller build | +1249/-182/23f |
| 0333e52 | 17:47 | fix: Phase 2a safety hardening — close 4 HIGH findings | +1028/-291/12f |
| 8a24ead | 21:17 | fix: Phase 2b observability & resilience — close 8 MEDIUM | +1727/-92/23f |
| b185fd3 | 21:58 | fix: Phase 2c final hardening — close 8 findings | +1044/-83/24f |
| 1698150 | 22:16 | ui: replace Overview "Сутки" preset with "Всё" | +232/-8 |

### Themes
- 4 structured hardening passes in 5 hours
- PyInstaller build unblocked
- 4 HIGH, 8 MEDIUM, 8 mixed findings closed
- Total: +4049 lines of hardening

---

## Audit cycle (2026-04-09)

**Commit range:** `380df96`..`7aaeb2b`
**Date range:** 2026-04-09 00:45 → 2026-04-09 04:20
**Number of commits:** 13
**Test files:** unchanged at 108

### Documents produced

| SHA | Title | Lines |
|---|---|---|
| 380df96 | audit: deep audit pass (CC) post-2c | 1240 |
| fd99631 | audit: deep audit pass (Codex overnight) post-2c | 763 |
| 847095c | audit: cherry-pick hardening pass document | 985 |
| 5d618db | audit: verification pass - re-check 5 HIGH | 1005 |
| 10667df | audit: SafetyManager exhaustive FSM analysis | 1062 |
| 31dbbe8 | audit: persistence-first invariant exhaustive trace | 1090 |
| 3e20e86 | audit: driver layer fault injection scenarios | 1366 |
| 916fae4 | audit: full dependency CVE sweep | 286 |
| a108519 | audit: reporting + analytics + plugins deep dive | 572 |
| 24b928d | audit: configuration files security and consistency | 719 |
| 7aaeb2b | audit: master triage synthesis | 307 |

### Themes
- 11 audit documents totaling ~9,400 lines
- CC, Codex, and verification passes
- 6 deep-dive documents covering every major subsystem
- MASTER_TRIAGE synthesizes all findings into prioritized action items

---

## Documentation discovery (2026-04-12..13)

**Commit range:** `995f7bc`..`1d71ecc`
**Date range:** 2026-04-12 23:25 → 2026-04-13 16:09
**Number of commits:** 4

### Key commits

| SHA | Title |
|---|---|
| 995f7bc | discovery: build doc-vs-code reality map (CC + Codex review) |
| 6eb7d3e | docs: rewrite cryodaq-team-lead skill against current code reality |
| ddf6459 | docs(CLAUDE.md): add missing config files to list |
| 1d71ecc | docs(CLAUDE.md): expand module index, fix safety FSM and invariants |

### Themes
- DOC_REALITY_MAP: systematic verification of 28 org docs vs 62 non-GUI modules
- Skill rewrite with verified numbers
- CLAUDE.md module index expanded from 34% to ~70% coverage

---

## Phase 2d (2026-04-13..14)

**Commit range:** `88feee5`..`0cd8a94`
**Date range:** 2026-04-13 16:27 → 2026-04-14 02:36
**Number of commits:** 16
**Test files before → after:** 108 → 113 (+5 test files)

### Commit detail

| SHA | Time | Title | Block |
|---|---|---|---|
| 88feee5 | 16:27 | phase-2d-a1: web XSS + SafetyManager hardening + T regression | A.1 |
| 1446f48 | 17:18 | phase-2d-a1-fix: heartbeat gap in RUN_PERMITTED + config error class | A.1 fix |
| ebac719 | 17:44 | phase-2d-a1-fix2: wrap SafetyConfig coercion in SafetyConfigError | A.1 fix2 |
| 1b12b87 | 18:07 | phase-2d-a2: alarm config hardening + safety→experiment bridge | A.2 |
| e068cbf | 20:53 | phase-2d-a2-fix: close Codex findings on 1b12b87 | A.2 fix |
| d3abee7 | 21:50 | phase-2d-b1: atomic file writes + WAL verification | B.1 |
| 5cf369e | 22:08 | phase-2d-a8-followup: shield post-fault cancellation paths | A.8 followup |
| 104a268 | 22:30 | phase-2d-b2: persistence integrity | B.2 |
| 21e9c40 | 22:46 | phase-2d-b2-fix: drop NaN-valued statuses from persist set | B.2 fix |
| 23929ca | 23:22 | phase-2d: checkpoint — Block A+B complete | Checkpoint |
| efe6b49 | 01:14+1d | chore: ruff --fix accumulated lint debt | Cleanup |
| f4c256f | 01:14+1d | chore: remove accidentally committed logs/ | Cleanup |
| 74f6d21 | 01:44+1d | phase-2d-jules-r2-fix: close ordering and state mutation gaps | Jules R2 |
| 89ed3c1 | 02:18+1d | phase-2d-c1: config fail-closed completion + cleanup | C.1 |
| 0cd8a94 | 02:36+1d | phase-2d: declare COMPLETE, open Phase 2e | Closure |

### Themes
- Three-layer review: CC tactical + Codex semantic + Jules architectural
- Safety hardening: web XSS, _fault() ordering, cancellation shielding, RUN_PERMITTED heartbeat
- Persistence integrity: OVERRANGE persist, NaN filtering, KRDG+SRDG atomic, calibration state deferral
- Config fail-closed: 5 ConfigError classes (Safety, Alarm, Interlock, Housekeeping, Channel)
- Jules Round 2 fix: _fault() callback ordering + calibration state mutation deferral
- ruff cleanup: 830 → 445 errors (132 files changed, +5200/-473 — largest commit by file count)

---

## Phase 2e (2026-04-14, in progress)

**Commit range:** `445c056`..`5ad0156`
**Date range:** 2026-04-14 02:55 → 2026-04-14 03:31
**Number of commits:** 3
**Test files:** 113 (unchanged from Phase 2d)

### Commits

| SHA | Title |
|---|---|
| 445c056 | phase-2e-parquet-1: experiment archive via Parquet at finalize |
| 855870b | docs(audits): add BRANCH_INVENTORY.md for three-track review input |
| 5ad0156 | docs(audits): add repo inventory, dead code scan, and CC findings summary |

### Themes
- Parquet streaming rewrite (ParquetWriter with chunk-bounded memory, replaces load-all v1)
- Three-track audit infrastructure (CC structural + Codex semantic + Jules architectural)

---

## Most-modified files (top 20)

Files changed most frequently across master history:

| Changes | File | Subsystem |
|---|---|---|
| 2 | src/cryodaq/core/scheduler.py | Core |
| 2 | src/cryodaq/core/safety_manager.py | Core |
| 2 | src/cryodaq/core/calibration_acquisition.py | Core |
| 1 | src/cryodaq/engine.py | Root |
| 1 | src/cryodaq/storage/parquet_archive.py | Storage |
| 1 | src/cryodaq/core/experiment.py | Core |
| 1 | src/cryodaq/core/interlock.py | Core |
| 1 | src/cryodaq/core/housekeeping.py | Core |
| 1 | src/cryodaq/core/channel_manager.py | Core |
| 1 | src/cryodaq/analytics/cooldown_predictor.py | Analytics |
| 1 | src/cryodaq/analytics/calibration.py | Analytics |
| 1 | src/cryodaq/analytics/calibration_fitter.py | Analytics |
| 1 | PROJECT_STATUS.md | Docs |

**Note:** The low change counts (max 2) reflect the project's development pattern: large batch commits that touch many files at once rather than incremental changes to the same files. Most modules were created in their final form in a single commit and modified at most once during Phase 2d hardening.

The most-modified files are all core subsystem modules (scheduler, safety_manager, calibration_acquisition) — these are the complexity centers that required Phase 2d hardening.

---

## Test evolution

| Phase boundary | Test files | Delta |
|---|---|---|
| Foundation start | 0 | — |
| After test suite (734f641) | 16 | +16 |
| After pre-hardening (9feaf3e) | 87 | +71 |
| After Phase 1 (a60abc0) | 91 | +4 |
| After Phase 2a (0333e52) | 94 | +3 |
| After Phase 2b (8a24ead) | 102 | +8 |
| After Phase 2c (1698150) | 108 | +6 |
| After audit cycle (7aaeb2b) | 108 | 0 |
| After Phase 2d start (88feee5) | 112 | +4 |
| After Phase 2d complete (0cd8a94) | 113 | +1 |
| Current HEAD (5ad0156) | 113 | 0 |

---

## Project velocity summary

| Period | Duration | Commits | Avg commits/day |
|---|---|---|---|
| Foundation (03-14) | 1 day | 47 | 47 |
| Deployment + merges (03-15..17) | 3 days | 21 | 7 |
| Post-merge features (03-17) | 1 day | 18 | 18 |
| v0.12.0 + alarm v2 (03-18) | 1 day | 14 | 14 |
| Hardware deployment (03-18..19) | 2 days | 15 | 7.5 |
| Analytics + safety (03-20..21) | 2 days | 22 | 11 |
| Merges + Parquet + reporting (03-21..22) | 2 days | 20 | 10 |
| Pre-hardening (03-23..04-01) | 10 days | 13 | 1.3 |
| Phase 1/2a/2b/2c (04-08) | 1 day | 5 | 5 |
| Audit cycle (04-09) | 1 day | 13 | 13 |
| Documentation (04-12..13) | 2 days | 4 | 2 |
| Phase 2d (04-13..14) | 1 day | 16 | 16 |
| Phase 2e (04-14) | 1 day | 3 | 3 |
