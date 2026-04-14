# CC_FINDINGS_SUMMARY.md

**Generated:** 2026-04-14
**Purpose:** Orientation document for Codex semantic review and Jules architectural review tracks.

---

## Repository at a glance

- **50 commits** on master, **v0.12.0** tag, current **v0.13.0** (unreleased)
- **102 source files** (~34K LOC), **113 test files** (~21K LOC), **895 tests passing**
- **Phase 2d** COMPLETE (14 commits, safety hardening + persistence integrity + config fail-closed)
- **Phase 2e** IN PROGRESS (Parquet archive stage 1 committed, operational hardening pending)
- **3 active branches:** master, feat/ui-phase-1-v2 (GUI rewrite, 19 behind master), feat/ui-phase-1 (superseded)
- **5 remote-only branches:** historical, fully integrated into master, safe to delete

---

## Architecture summary

```
Instruments → Scheduler → SQLiteWriter → DataBroker → ZMQ → GUI
                                       → SafetyBroker → SafetyManager
                                       → CalibrationAcquisition
```

Three runtime processes: headless engine (asyncio), desktop GUI (PySide6), optional web dashboard (FastAPI).

**Key invariants:**
1. Persistence-first: SQLite write BEFORE broker publish
2. SAFE_OFF default: source ON requires continuous health proof
3. SafetyState FSM: 6 states including MANUAL_RECOVERY
4. Fail-closed config: 5 config types → subsystem-specific ConfigError → engine exit code 2
5. Cancellation shielding: emergency_off, fault callback, safe_off cleanup all shield'd
6. OVERRANGE/UNDERRANGE persist as ±inf; NaN (SENSOR_ERROR/TIMEOUT) dropped

---

## What Codex should focus on

### 1. Phase 2e Parquet export (445c056)

**Files:** `storage/parquet_archive.py`, `core/experiment.py`, `tests/storage/test_parquet_export.py`

Key questions:
- Is the streaming ParquetWriter correctly bounded (memory, file handles)?
- Does the day-boundary iteration cover edge cases (DST transitions, empty days mid-range)?
- Is the experiment.py integration best-effort safe (does a parquet failure affect experiment finalize)?
- Does `read_experiment_parquet()` handle schema evolution gracefully?

### 2. Config fail-closed completeness (89ed3c1)

**Files:** `core/channel_manager.py`, `core/interlock.py`, `core/housekeeping.py`, `engine.py`

Key questions:
- Are all 5 config error types caught by engine.py?
- Can any config load path silently return defaults instead of raising?
- Is the engine exit code 2 path reachable for every config error?

### 3. Test coverage gaps

**Zero-test modules (high risk):**
- `reporting/generator.py` — uses blocking subprocess.run() for LibreOffice (known DEEP_AUDIT E.2)
- `notifications/escalation.py` — timed escalation service
- `notifications/periodic_report.py` — scheduled Telegram reports
- `core/alarm_providers.py` — alarm provider implementations
- `core/channel_manager.py` — singleton with fail-closed config
- `core/safety_broker.py` — dedicated safety channel with overflow=FAULT semantics

### 4. Unused import

`storage/parquet_archive.py:14` — `date` imported but unused. Trivial but should be cleaned.

---

## What Jules should focus on

### 1. Cross-cutting cancellation analysis

Phase 2d established shield patterns in three locations:
- `safety_manager.py:_fault()` — emergency_off + fault_log_callback
- `safety_manager.py:_safe_off()` — _ensure_output_off in fault-latched branch
- `scheduler.py:stop()` — graceful drain before forced cancel

**Question:** Are there other async paths where CancelledError could interrupt hardware safety operations? Check:
- `calibration_acquisition.py` — does calibration stop properly shield SRDG writes?
- `scheduler.py` instrument polling tasks — does a CancelledError during `write_immediate()` leave SQLite in a consistent state?
- `zmq_bridge.py` / `zmq_subprocess.py` — can ZMQ cleanup be interrupted?

### 2. Persistence ordering under failure

The persistence-first invariant guarantees write→publish ordering. But:
- What happens if `write_immediate()` raises mid-batch? Does the partial batch get published?
- Does the `SafetyBroker` overflow→FAULT path work correctly when the SQLiteWriter is unavailable?
- Is there a race between `Scheduler.stop()` drain and `SQLiteWriter.stop()` closing the connection?

### 3. Fault state machine integrity

Phase 2d hardened _fault() ordering (callback before publish). But:
- Can `acknowledge_fault()` race with `_fault()` if both are called near-simultaneously?
- The MANUAL_RECOVERY→READY transition depends on precondition re-check — can preconditions be evaluated with stale data during the transition?
- Is the `_run_permitted_since` heartbeat properly cleared on state transitions out of RUN_PERMITTED?

### 4. Branch integration risk

`feat/ui-phase-1-v2` is 19 commits behind master. The merge-base predates all of Phase 2d. While file domains don't overlap (GUI vs core), check:
- Does the UI branch import from any module whose API changed in Phase 2d?
- `calibration_acquisition.py` API changed (on_readings deprecated) — does the UI branch's calibration_panel use the old API?
- Do any Phase 2d config changes (safety.yaml scheduler_drain_timeout_s) require UI awareness?

---

## Files changed in Phase 2d (for targeted review)

### Safety subsystem
- `core/safety_manager.py` — FSM hardening, _fault() ordering, config fail-closed, RUN_PERMITTED heartbeat
- `core/alarm_v2.py` — acknowledge() implementation with re-ack guard
- `core/alarm_config.py` — AlarmConfigError, fail-closed load
- `core/interlock.py` — InterlockConfigError, fail-closed load
- `core/housekeeping.py` — HousekeepingConfigError, fail-closed load
- `core/channel_manager.py` — ChannelConfigError, fail-closed load, removed DEFAULT_CHANNELS

### Persistence subsystem
- `storage/sqlite_writer.py` — OVERRANGE persist, WAL verification, ChannelStatus filter
- `core/atomic_write.py` — new module: atomic file writes via os.replace()
- `core/experiment.py` — 4 sidecar writes → atomic_write, WAL verification
- `core/scheduler.py` — KRDG+SRDG atomic write, two-phase stop with drain
- `core/calibration_acquisition.py` — prepare/persist/apply split (Jules R2)

### Engine integration
- `engine.py` — unified config error handler, safety fault log callback, scheduler drain wiring

### Web
- `web/server.py` — escapeHtml() XSS fix

### Config
- `config/alarms_v3.yaml` — phantom interlocks removed, keithley_overpower restored
- `config/housekeeping.yaml` — [TТ] Cyrillic/Latin character class
- `config/safety.yaml` — scheduler_drain_timeout_s: 5.0

---

## Known deferred items (Phase 2e candidates)

| ID | Item | Priority |
|---|---|---|
| K.1 | requirements-lock.txt hash verification | MEDIUM |
| K.2 | post_build.py plugin YAML sidecar copy | LOW |
| J.1 | Runtime root outside bundle directory | MEDIUM |
| H.1 | Runtime plugin loading trust boundary | MEDIUM |
| G.1 | Web dashboard auth or loopback-only | HIGH |
| G.2 | Web history/log query size bounds | MEDIUM |
| F.1 | Telegram bot persist update_id | LOW |
| C.1 | .local.yaml merge instead of replace | MEDIUM |
| A.7.5 | Semantic config errors | LOW |
| A.9.1 | ZMQ acknowledged state serialization | LOW |
| P2 | DataBroker exception isolation from SafetyBroker | HIGH |
| P3 | Day-boundary batch splitting | MEDIUM |

---

## Review protocol

Three-track parallel review established in Phase 2d:

1. **CC structural** (this document + REPO_INVENTORY + DEAD_CODE_AND_TODO + BRANCH_INVENTORY)
2. **Codex semantic** — per-file line-level analysis, focuses on type errors, wrong APIs, wrong filters, edge cases
3. **Jules architectural** — cross-cutting analysis, focuses on cancellation propagation, ordering dependencies, state machine integrity

Each track produces independent findings. Overlap is expected and validates severity. Conflicting findings escalate to manual review.
