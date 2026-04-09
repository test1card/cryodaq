# CryoDAQ Master Triage

**Date:** 2026-04-09  
**Working tree:** `master`  
**Commit under review:** `1698150`  
**Source note:** `HARDENING_PASS_CODEX.md` was no longer present at `feat/ui-phase-1` tip because it was later removed there; I read the authoritative version from commit `98a57c5`.

## 1. Executive summary

### Top 5 issues to fix before deployment

1. **Keithley watchdog is still host-only** (`DEEP_AUDIT_CODEX_POST_2C.md:M.1`).  
   If the engine or launcher dies while sourcing is active, the bundled TSP watchdog is not actually enforcing output-off on the instrument.  
   **Fix direction:** make the Keithley watchdog script part of the real production contract, or explicitly block deployment until an equivalent hardware-side fail-safe exists.

2. **SafetyManager still has edge-case blind spots during source start and fault actuation** (`SAFETY_MANAGER_DEEP_DIVE.md:F1`, `SAFETY_MANAGER_DEEP_DIVE.md:F2`).  
   `RUN_PERMITTED` suppresses periodic safety checks during `await start_source(...)`, and `_fault()` can be cancelled before hardware shutdown completes.  
   **Fix direction:** eliminate the `RUN_PERMITTED` monitoring gap and shield or otherwise harden the physical emergency-off path so “fault latched” and “output off” cannot drift apart.

3. **Persistence is ordered correctly, but not atomic end-to-end** (`PERSISTENCE_INVARIANT_DEEP_DIVE.md:P1`, `DEEP_AUDIT_CODEX_POST_2C.md:A.2`, `REPORTING_ANALYTICS_DEEP_DIVE.md:C1`, `HARDENING_PASS_CODEX.md:H.10`).  
   SQLite commit can succeed while broker delivery or calibration companion writes are still pending, and several sidecars/indexes are still non-atomic.  
   **Fix direction:** harden shutdown semantics, make sidecars/indexes atomic, and make calibration poll cycles durable as one logical unit or mark them incomplete explicitly.

4. **The web/monitoring surface is still too weak for production** (`DEEP_AUDIT_CODEX_POST_2C.md:G.1`, `HARDENING_PASS_CODEX.md:H.14`, `DEEP_AUDIT_CODEX_POST_2C.md:G.2`).  
   The dashboard is unauthenticated, query size is unbounded, and stored operator text can execute as HTML/JS in the browser.  
   **Fix direction:** add auth or force loopback-only deployment, bound expensive queries, and replace all raw `innerHTML` sinks with escaped/text-only rendering.

5. **Configuration is a real safety surface and currently too permissive** (`CONFIG_FILES_AUDIT.md:C.1`, `CONFIG_FILES_AUDIT.md:C.2`, `CONFIG_FILES_AUDIT.md:C.3`, `CONFIG_FILES_AUDIT.md:C.4`).  
   Partial `.local.yaml` files replace full configs instead of merging, `safety.yaml` can fail open, and `alarms_v3.yaml` contains live-looking interlocks that are not enforced.  
   **Fix direction:** add schema validation plus effective-config logging, make safety config load fail closed, and collapse split-brain safety config into one authoritative source.

## 2. Findings consolidation by category

Rows below are **de-duplicated issue clusters**. Every source ID cited maps to one of these rows. `Status` meanings:

- `NEW`: only one source doc raised it
- `VERIFIED`: later pass explicitly re-checked it
- `DUPLICATE`: independently raised by multiple docs
- `DISPUTED`: later pass narrowed or challenged the original claim

### Safety logic

| ID | Severity | Title | Source doc | Status |
|---|---|---|---|---|
| `M.1` | CRITICAL | Keithley watchdog script is shipped but not part of the production safety path | `DEEP_AUDIT_CODEX_POST_2C.md:M.1` | NEW |
| `F1` | HIGH | `RUN_PERMITTED` suppresses periodic safety checks while source start is awaiting I/O | `SAFETY_MANAGER_DEEP_DIVE.md:F1` | VERIFIED |
| `F2` | HIGH | `_fault()` latches immediately, but the actual hardware shutdown path is still cancellable | `SAFETY_MANAGER_DEEP_DIVE.md:F2` | VERIFIED |
| `H.6` | HIGH | Safety faults do not propagate into experiment lifecycle or metadata | `HARDENING_PASS_CODEX.md:H.6`, `VERIFICATION_PASS_HIGHS.md:H.6` | VERIFIED |
| `A.1 / A.2 / A.3` | HIGH / MEDIUM / MEDIUM | Alarm v2 acknowledge/hysteresis/channel-group behavior is incomplete or misleading | `DEEP_AUDIT_CC_POST_2C.md:A.1-A.3` | NEW |
| `A.8 / F3` | MEDIUM | Interlock action path is serialized and one escalation path still runs under `_cmd_lock` | `DEEP_AUDIT_CC_POST_2C.md:A.8`, `SAFETY_MANAGER_DEEP_DIVE.md:F3` | DUPLICATE |
| `A.6 / P4` | MEDIUM / LOW | SafetyBroker overflow behavior can create misleading or partial downstream semantics | `DEEP_AUDIT_CC_POST_2C.md:A.6`, `PERSISTENCE_INVARIANT_DEEP_DIVE.md:P4` | DUPLICATE |
| `F4` | MEDIUM | SafetyManager itself still relies on upstream discipline for Cyrillic/Latin `T` normalization | `SAFETY_MANAGER_DEEP_DIVE.md:F4` | NEW |
| `F5` | LOW | `SafetyManager.stop()` stops tasks but does not normalize the final FSM state | `SAFETY_MANAGER_DEEP_DIVE.md:F5` | NEW |

### Persistence integrity

| ID | Severity | Title | Source doc | Status |
|---|---|---|---|---|
| `P1` | HIGH | `Scheduler.stop()` can cancel after SQLite commit but before broker delivery | `PERSISTENCE_INVARIANT_DEEP_DIVE.md:P1` | VERIFIED |
| `A.2` | HIGH | Experiment metadata/state sidecars are still written non-atomically | `DEEP_AUDIT_CODEX_POST_2C.md:A.2` | NEW |
| `D.1 / C1` | HIGH | Calibration index/curve files are non-atomic and unlocked | `DEEP_AUDIT_CODEX_POST_2C.md:D.1`, `REPORTING_ANALYTICS_DEEP_DIVE.md:C1` | DUPLICATE |
| `H.10` | HIGH | Calibration poll cycles persist KRDG and SRDG in separate failure windows | `HARDENING_PASS_CODEX.md:H.10`, `VERIFICATION_PASS_HIGHS.md:H.10` | VERIFIED |
| `B.1 / C.1` | HIGH / MEDIUM | LakeShore OVERRANGE and other non-finite values are dropped from SQLite history | `DEEP_AUDIT_CC_POST_2C.md:B.1`, `DEEP_AUDIT_CC_POST_2C.md:C.1` | DUPLICATE |
| `C.1` | HIGH | Ubuntu 22.04 target SQLite is still in the WAL-reset danger range | `DEEP_AUDIT_CODEX_POST_2C.md:C.1` | NEW |
| `C.2` | HIGH | Code assumes WAL is enabled but never checks SQLite’s actual returned journal mode | `DEEP_AUDIT_CODEX_POST_2C.md:C.2` | NEW |
| `C.3` | MEDIUM | `synchronous=NORMAL` still allows recent data loss on power failure | `DEEP_AUDIT_CODEX_POST_2C.md:C.3` | NEW |
| `P2` | MEDIUM | `DataBroker.publish_batch()` failure can block `SafetyBroker` after persistence already succeeded | `PERSISTENCE_INVARIANT_DEEP_DIVE.md:P2` | VERIFIED |
| `P3` | MEDIUM | One logical scheduler batch can commit as multiple SQLite transactions across day boundaries | `PERSISTENCE_INVARIANT_DEEP_DIVE.md:P3` | VERIFIED |
| `C.2 / C.3` | LOW / LOW | Reader/query-only and Parquet export paths have avoidable integrity/performance debt | `DEEP_AUDIT_CC_POST_2C.md:C.2-C.3` | NEW |

### Driver / hardware fault handling

| ID | Severity | Title | Source doc | Status |
|---|---|---|---|---|
| `A.1 / Driver-2` | HIGH | Poll timeout does not stop already-running executor work; a stuck VISA call can brick the transport lane | `DEEP_AUDIT_CODEX_POST_2C.md:A.1`, `DRIVER_FAULT_INJECTION.md:[HIGH] GPIB timeout/cable-fault path is not cancellable at transport level` | DUPLICATE |
| `B.3 / Driver-3` | HIGH | Keithley `start_source()` is non-atomic and has no rollback on partial failure | `DEEP_AUDIT_CC_POST_2C.md:B.3`, `DRIVER_FAULT_INJECTION.md:[HIGH] Keithley start_source() is non-atomic and has no rollback` | DUPLICATE |
| `Driver-4` | HIGH | Keithley has a real multi-call race on `start_source()` | `DRIVER_FAULT_INJECTION.md:[HIGH] Keithley has a real multi-call race on start_source()` | NEW |
| `Driver-7` | HIGH | Serial transport has no request/response serialization | `DRIVER_FAULT_INJECTION.md:[HIGH] Serial transport has no request/response serialization` | NEW |
| `Driver-1` | HIGH | LakeShore parser handles `+OVL` but not `-OVL` symmetrically | `DRIVER_FAULT_INJECTION.md:[HIGH] LakeShore parser handles +OVL but not -OVL` | NEW |
| `B.4` | MEDIUM | Serial `wait_closed()` has no timeout | `DEEP_AUDIT_CC_POST_2C.md:B.4` | NEW |
| `Driver-5 / Driver-6` | MEDIUM | Keithley disconnect/off semantics depend on exception class and connection flag correctness | `DRIVER_FAULT_INJECTION.md:[MEDIUM] Keithley disconnect detection depends on exception class`, `DRIVER_FAULT_INJECTION.md:[MEDIUM] emergency_off() on a logically disconnected Keithley does not attempt hardware I/O` | DUPLICATE |
| `Driver-8` | MEDIUM | Thyracont parser accepts `inf` as `OK` pressure | `DRIVER_FAULT_INJECTION.md:[MEDIUM] Thyracont MV00 parser accepts inf as status OK` | NEW |
| `B.2 / B.5 / B.6 / Driver-9` | LOW | Driver residuals: dead code, short-lived runtime drift, checksum/logging, generic post-close errors | `DEEP_AUDIT_CC_POST_2C.md:B.2,B.5,B.6`, `DRIVER_FAULT_INJECTION.md:[LOW] post-close behavior` | NEW |

### Numerical correctness

| ID | Severity | Title | Source doc | Status |
|---|---|---|---|---|
| `H.11 / D.2 / A2 / A.7` | HIGH / MEDIUM / MEDIUM / LOW | Cooldown analytics mix wall-clock and monotonic assumptions | `HARDENING_PASS_CODEX.md:H.11`, `VERIFICATION_PASS_HIGHS.md:H.11`, `DEEP_AUDIT_CODEX_POST_2C.md:D.2`, `REPORTING_ANALYTICS_DEEP_DIVE.md:A2`, `DEEP_AUDIT_CC_POST_2C.md:A.7` | VERIFIED |
| `H.12 / A3 / A4 / A5 / D.3` | MEDIUM | Vacuum trend paths accept backward timestamps, NaNs, and invalid targets too easily | `HARDENING_PASS_CODEX.md:H.12`, `REPORTING_ANALYTICS_DEEP_DIVE.md:A3-A5`, `DEEP_AUDIT_CC_POST_2C.md:D.3` | DUPLICATE |
| `A1 / D.2` | MEDIUM / LOW | `cooldown_predictor.predict()` can generate NaN weights / divide-by-zero style failures | `REPORTING_ANALYTICS_DEEP_DIVE.md:A1`, `DEEP_AUDIT_CC_POST_2C.md:D.2` | DUPLICATE |
| `D.4 / OK3` | LOW / OK | Sensor diagnostics are mostly conservative, but correlation alignment is still lossy | `DEEP_AUDIT_CC_POST_2C.md:D.4`, `REPORTING_ANALYTICS_DEEP_DIVE.md:OK3` | DUPLICATE |

### Web / notification security

| ID | Severity | Title | Source doc | Status |
|---|---|---|---|---|
| `G.1 / G.1` | HIGH | Web dashboard/API is unauthenticated | `DEEP_AUDIT_CC_POST_2C.md:G.1`, `DEEP_AUDIT_CODEX_POST_2C.md:G.1` | DUPLICATE |
| `H.14` | HIGH | Stored XSS via operator log text in dashboard `innerHTML` | `HARDENING_PASS_CODEX.md:H.14`, `VERIFICATION_PASS_HIGHS.md:H.14` | VERIFIED |
| `F.1` | HIGH | Telegram command bot replays stale pending commands after restart | `DEEP_AUDIT_CODEX_POST_2C.md:F.1` | NEW |
| `G.2 / G.4 / G.5` | HIGH / MEDIUM / MEDIUM | History/log query size is effectively unbounded and can consume shared executor resources | `DEEP_AUDIT_CODEX_POST_2C.md:G.2`, `DEEP_AUDIT_CC_POST_2C.md:G.4-G.5` | DUPLICATE |
| `F.1 / G.3` | MEDIUM | HTML escaping is missing in Telegram messages and channel-name dashboard rendering | `DEEP_AUDIT_CC_POST_2C.md:F.1`, `DEEP_AUDIT_CC_POST_2C.md:G.3` | DUPLICATE |
| `G.6 / I.8` | LOW | WebSocket/dashboard semantics still leak state too freely and blur “offline” vs “unknown fault” | `DEEP_AUDIT_CC_POST_2C.md:G.6`, `HARDENING_PASS_CODEX.md:I.8` | NEW |

### Configuration / schema gaps

| ID | Severity | Title | Source doc | Status |
|---|---|---|---|---|
| `C.1` | HIGH | Partial `.local.yaml` overrides replace whole files instead of merging | `CONFIG_FILES_AUDIT.md:C.1` | NEW |
| `C.2` | HIGH | `safety.yaml` can fail open to zero critical channels | `CONFIG_FILES_AUDIT.md:C.2` | NEW |
| `C.3` | HIGH | `alarms_v3.yaml` contains live-looking interlocks that are not runtime-authoritative | `CONFIG_FILES_AUDIT.md:C.3` | NEW |
| `C.4` | HIGH | Malformed `alarms_v3.yaml` silently disables v2 alarms | `CONFIG_FILES_AUDIT.md:C.4` | NEW |
| `H.5 / C.6` | HIGH / MEDIUM | Adaptive-throttle vs stale-alarm config coupling is real, but the original high-severity claim was overstated | `HARDENING_PASS_CODEX.md:H.5`, `VERIFICATION_PASS_HIGHS.md:H.5`, `CONFIG_FILES_AUDIT.md:C.6` | DISPUTED |
| `C.5 / F4` | MEDIUM | Latin `T` / Cyrillic `Т` mismatch still exists in config and SafetyManager assumptions | `CONFIG_FILES_AUDIT.md:C.5`, `SAFETY_MANAGER_DEEP_DIVE.md:F4` | DUPLICATE |
| `C.7 / P3` | MEDIUM / LOW | Plugin config is split between `plugins.yaml` and per-plugin sidecars; malformed plugin YAML can still leave plugins active | `CONFIG_FILES_AUDIT.md:C.7`, `REPORTING_ANALYTICS_DEEP_DIVE.md:P3` | DUPLICATE |
| `C.8 / C.9 / J.1` | MEDIUM / LOW / LOW | General config debt: dead keys, silent GUI fallbacks, no schema validation | `CONFIG_FILES_AUDIT.md:C.8-C.9`, `DEEP_AUDIT_CC_POST_2C.md:J.1` | DUPLICATE |

### Supply chain / dependency

| ID | Severity | Title | Source doc | Status |
|---|---|---|---|---|
| `K.1 / I.1 / 1` | HIGH / LOW / HIGH | Lockfile/build path does not actually enforce hash verification | `DEEP_AUDIT_CODEX_POST_2C.md:K.1`, `DEEP_AUDIT_CC_POST_2C.md:I.1`, `DEPENDENCY_CVE_SWEEP.md:1` | DUPLICATE |
| `2` | MEDIUM | Build backend `hatchling` is unpinned | `DEPENDENCY_CVE_SWEEP.md:2` | NEW |
| `Dependency summary` | INFO | No pinned runtime dependency was confirmed vulnerable at the reviewed versions | `DEPENDENCY_CVE_SWEEP.md:Final verdict` | VERIFIED |

### Build / packaging / deployment

| ID | Severity | Title | Source doc | Status |
|---|---|---|---|---|
| `J.1` | HIGH | Runtime root is assumed writable next to the frozen executable | `DEEP_AUDIT_CODEX_POST_2C.md:J.1` | NEW |
| `K.2` | HIGH | `post_build.py` copies plugin code but forgets plugin YAML sidecars | `DEEP_AUDIT_CODEX_POST_2C.md:K.2` | NEW |
| `E.3` | MEDIUM | Frozen builds launch external `soffice` without environment sanitization | `DEEP_AUDIT_CODEX_POST_2C.md:E.3` | NEW |
| `K.3` | MEDIUM | POSIX `onedir` PyInstaller bundle depends on preserved symlinks, but deployment flow does not surface that requirement | `DEEP_AUDIT_CODEX_POST_2C.md:K.3` | NEW |
| `I.2` | LOW | Spec excludes remain hand-maintained and fragile | `DEEP_AUDIT_CC_POST_2C.md:I.2` | NEW |

### Concurrency / async / threading

| ID | Severity | Title | Source doc | Status |
|---|---|---|---|---|
| `A.4 / R1 / E.1 / E.2` | HIGH / HIGH / HIGH / MEDIUM | Experiment finalize/report generation is blocking and brittle; one bad section or hung `soffice` can stall the engine | `DEEP_AUDIT_CC_POST_2C.md:A.4,E.1`, `DEEP_AUDIT_CODEX_POST_2C.md:E.2`, `REPORTING_ANALYTICS_DEEP_DIVE.md:R1-R2` | DUPLICATE |
| `H.1 / H.15` | HIGH / MEDIUM | GUI thread still blocks on engine lifecycle and some synchronous command paths | `DEEP_AUDIT_CC_POST_2C.md:H.1`, `HARDENING_PASS_CODEX.md:H.15` | DUPLICATE |
| `D.1 / G.5` | MEDIUM | Default executor is still used for heavy analytics and web-history work | `DEEP_AUDIT_CC_POST_2C.md:D.1,G.5` | DUPLICATE |
| `G.2 / G.5 / P1` | HIGH / MEDIUM / HIGH | Shared async/process boundaries make overload and shutdown ordering more fragile than the local code suggests | `DEEP_AUDIT_CODEX_POST_2C.md:G.2`, `DEEP_AUDIT_CC_POST_2C.md:G.5`, `PERSISTENCE_INVARIANT_DEEP_DIVE.md:P1` | DUPLICATE |
| `H.2 / I.1` | MEDIUM / LOW | Launcher-side observability is still weak; async loop failures and early engine crashes can be hard to diagnose | `DEEP_AUDIT_CC_POST_2C.md:H.2`, `DEEP_AUDIT_CODEX_POST_2C.md:I.1` | NEW |

### UX / operator workflow

| ID | Severity | Title | Source doc | Status |
|---|---|---|---|---|
| `H.13` | MEDIUM | Auto-generated lifecycle/fault events are best-effort and can vanish silently | `HARDENING_PASS_CODEX.md:H.13` | NEW |
| `H.4` | MEDIUM | No authoritative engine wall-clock start time is exposed to the UI | `DEEP_AUDIT_CC_POST_2C.md:H.4` | NEW |
| `A.5 / F.4 / H.5` | LOW | UX/ops nits: short experiment IDs, Telegram log spam, unconditional watchdog/info logging | `DEEP_AUDIT_CC_POST_2C.md:A.5,F.4,H.5` | NEW |
| `C.9 / I.8` | LOW | GUI/dashboard can mask config invalidity or ambiguous remote state | `CONFIG_FILES_AUDIT.md:C.9`, `HARDENING_PASS_CODEX.md:I.8` | NEW |

## 3. Verification status of every HIGH severity finding

This section tracks **every high-severity cluster** that survived synthesis. “Code reference” values below are taken from the source audit documents and therefore correspond to commit `1698150`.

| High issue | Verified by | Disputed by | Code reference current as of `1698150` | Recommended Phase 2d action |
|---|---|---|---|---|
| Keithley watchdog not in production path (`M.1`) | `DEEP_AUDIT_CODEX_POST_2C.md:M.1` | None | `src/cryodaq/drivers/instruments/keithley_2604b.py:1,239`; `tsp/p_const.lua:1` | Decide now whether Phase 2d includes real watchdog upload/heartbeat or explicitly blocks deployment without it. |
| `RUN_PERMITTED` blind state (`F1`) | `SAFETY_MANAGER_DEEP_DIVE.md:F1` | None | `src/cryodaq/core/safety_manager.py:218-267,651-667` | Remove the blind state or keep safety checks active while source start is pending. |
| `_fault()` hardware-off path cancellable (`F2`) | `SAFETY_MANAGER_DEEP_DIVE.md:F2` | None | `src/cryodaq/core/safety_manager.py:538-556` | Shield or otherwise harden emergency-off so cancellation cannot preempt the physical shutdown step. |
| Safety faults do not reach experiment lifecycle (`H.6`) | `VERIFICATION_PASS_HIGHS.md:H.6`, `HARDENING_PASS_CODEX.md:H.6` | None | `src/cryodaq/core/safety_manager.py:447-545`; `src/cryodaq/core/experiment.py:682-770`; `src/cryodaq/engine.py:806-857` | Add engine-level safety callback that records fault reason/time into experiment metadata and operator log. |
| Shutdown can commit SQLite but miss broker delivery (`P1`) | `PERSISTENCE_INVARIANT_DEEP_DIVE.md:P1` | None | `src/cryodaq/core/scheduler.py:338-377,446-470`; `src/cryodaq/storage/sqlite_writer.py:525-540,604-623` | Add graceful drain/flush semantics or explicit “persisted but not published” recovery markers on stop. |
| Poll timeout does not kill transport work (`A.1` / driver duplicate) | `DEEP_AUDIT_CODEX_POST_2C.md:A.1`, `DRIVER_FAULT_INJECTION.md:[HIGH] GPIB timeout...` | None | `src/cryodaq/core/scheduler.py:127,198`; `src/cryodaq/drivers/transport/gpib.py:59,168-193`; `src/cryodaq/drivers/transport/usbtmc.py:39,169-205` | Add transport-level abort/reset on timeout and make executor replacement part of timeout recovery. |
| Experiment metadata sidecars non-atomic (`A.2`) | `DEEP_AUDIT_CODEX_POST_2C.md:A.2` | None | `src/cryodaq/core/experiment.py:874,1054,1149,1355` | Route all experiment JSON sidecars through atomic write helper. |
| SQLite target version unsafe (`C.1`) | `DEEP_AUDIT_CODEX_POST_2C.md:C.1` | None | `src/cryodaq/storage/sqlite_writer.py:97` | Gate startup on safe SQLite in deployment mode or bundle a known-good libsqlite. |
| WAL mode not verified (`C.2`) | `DEEP_AUDIT_CODEX_POST_2C.md:C.2` | None | `src/cryodaq/storage/sqlite_writer.py:248`; `src/cryodaq/core/experiment.py:983` | Check returned `journal_mode` and fail if not `wal`. |
| Calibration index/curve writes non-atomic (`D.1` / `C1`) | `REPORTING_ANALYTICS_DEEP_DIVE.md:C1`, `DEEP_AUDIT_CODEX_POST_2C.md:D.1` | None | `src/cryodaq/analytics/calibration.py:201-213,339-345,731-759` | Add atomic temp-file replacement and inter-process locking around calibration metadata writes. |
| Calibration poll cycle not atomic (`H.10`) | `VERIFICATION_PASS_HIGHS.md:H.10`, `HARDENING_PASS_CODEX.md:H.10` | None | `src/cryodaq/core/scheduler.py:338-366`; `src/cryodaq/core/calibration_acquisition.py:71-122` | Persist KRDG+SRDG as one logical cycle or mark incomplete pair writes explicitly. |
| Telegram replays stale pending commands (`F.1`) | `DEEP_AUDIT_CODEX_POST_2C.md:F.1` | None | `src/cryodaq/notifications/telegram_commands.py:113,208` | Persist last update id or explicitly discard backlog on startup. |
| Web dashboard unauthenticated (`G.1`) | `DEEP_AUDIT_CC_POST_2C.md:G.1`, `DEEP_AUDIT_CODEX_POST_2C.md:G.1` | None | `src/cryodaq/web/server.py:325-406` | Add auth or force loopback-only default before deployment. |
| Web query size effectively unbounded (`G.2`) | `DEEP_AUDIT_CODEX_POST_2C.md:G.2`, `DEEP_AUDIT_CC_POST_2C.md:G.4-G.5` | None | `src/cryodaq/web/server.py:247,365,376` | Bound `minutes` and `limit`, paginate results, isolate history work from shared executor. |
| Plugin directory is executable code in-process (`H.1`) | `DEEP_AUDIT_CODEX_POST_2C.md:H.1`, `REPORTING_ANALYTICS_DEEP_DIVE.md:P1` | None | `src/cryodaq/analytics/plugin_loader.py:145-156,263-287`; `src/cryodaq/paths.py:66` | Disable runtime plugin loading in production or make plugin source read-only/trusted. |
| Runtime root assumed writable next to bundle (`J.1`) | `DEEP_AUDIT_CODEX_POST_2C.md:J.1` | None | `src/cryodaq/paths.py:37,52,59`; `src/cryodaq/web/server.py:81` | Move data/log/runtime dirs out of bundle directory and reject unsafe/network-share deployments. |
| Hash verification not actually enforced (`K.1` / `1`) | `DEEP_AUDIT_CODEX_POST_2C.md:K.1`, `DEPENDENCY_CVE_SWEEP.md:1` | None | `build_scripts/build.sh:9`; `build_scripts/build.bat:5`; `requirements-lock.txt` | Generate hashes and fail builds on hash-check failure instead of falling back. |
| `post_build.py` misses plugin YAML sidecars (`K.2`) | `DEEP_AUDIT_CODEX_POST_2C.md:K.2` | None | `build_scripts/post_build.py:53`; `src/cryodaq/analytics/plugin_loader.py:186` | Copy plugin code and same-stem sidecars as one unit. |
| Stored XSS via operator log (`H.14`) | `VERIFICATION_PASS_HIGHS.md:H.14`, `HARDENING_PASS_CODEX.md:H.14` | None | `src/cryodaq/notifications/telegram_commands.py:392-406`; `src/cryodaq/web/server.py:497-503` | Replace `innerHTML` with escaped text rendering for log content immediately. |
| Report finalization blocks engine and is brittle (`A.4 / R1 / E.1`) | `DEEP_AUDIT_CC_POST_2C.md:A.4,E.1`, `REPORTING_ANALYTICS_DEEP_DIVE.md:R1`, `DEEP_AUDIT_CODEX_POST_2C.md:E.2` | None | `src/cryodaq/core/experiment.py:732-738`; `src/cryodaq/reporting/generator.py:71-109,207-224` | Move reporting/PDF conversion off the engine loop, add timeout, and isolate per-section failures. |
| Alarm acknowledge does not suppress active alarm (`A.1`) | `DEEP_AUDIT_CC_POST_2C.md:A.1` | None | `src/cryodaq/core/alarm_v2.py:505-509` | Implement real acknowledged state in AlarmStateManager. |
| LakeShore OVERRANGE dropped from SQLite (`B.1`) | `DEEP_AUDIT_CC_POST_2C.md:B.1` | None | `src/cryodaq/storage/sqlite_writer.py:299`; `src/cryodaq/drivers/instruments/lakeshore_218s.py:368-377` | Persist sensor fault/overrange as explicit status-bearing records instead of dropping them. |
| Keithley `start_source()` non-atomic / no rollback (`B.3`) | `DEEP_AUDIT_CC_POST_2C.md:B.3`, `DRIVER_FAULT_INJECTION.md:[HIGH] start_source non-atomic` | None | `src/cryodaq/drivers/instruments/keithley_2604b.py:221-250` | Add rollback/off on failure and/or post-write verification before `OUTPUT_ON`. |
| Keithley multi-call race on `start_source()` | `DRIVER_FAULT_INJECTION.md:[HIGH] multi-call race` | None | `src/cryodaq/drivers/instruments/keithley_2604b.py:221-250`; `src/cryodaq/drivers/transport/usbtmc.py:123-135` | Add driver-level operation lock around whole start/stop sequences. |
| Serial transport has no request/response serialization | `DRIVER_FAULT_INJECTION.md:[HIGH] Serial transport ...` | None | `src/cryodaq/drivers/transport/serial.py:91-167` | Add `asyncio.Lock` around query/write/read transaction boundaries. |
| Partial `.local.yaml` overrides replace whole configs (`C.1`) | `CONFIG_FILES_AUDIT.md:C.1` | None | `src/cryodaq/engine.py:775-783`; `src/cryodaq/core/safety_manager.py:124-155` | Make overrides merge-aware or forbid local overrides for safety-critical configs. |
| `safety.yaml` can fail open (`C.2`) | `CONFIG_FILES_AUDIT.md:C.2` | None | `src/cryodaq/core/safety_manager.py:124-155,601-619` | Treat missing/invalid/empty safety config as startup-fatal. |
| `alarms_v3.yaml` dead `interlocks:` section (`C.3`) | `CONFIG_FILES_AUDIT.md:C.3` | None | `src/cryodaq/core/alarm_config.py:71-111`; `src/cryodaq/engine.py:862-925` | Remove the dead section or wire it into the actual interlock engine. |
| Malformed `alarms_v3.yaml` silently disables v2 (`C.4`) | `CONFIG_FILES_AUDIT.md:C.4` | None | `src/cryodaq/core/alarm_config.py:81-90`; `src/cryodaq/engine.py:938-959` | Make malformed alarms config startup-fatal instead of silently disabling. |
| Cooldown predictor timebase mix (`H.11`) | `VERIFICATION_PASS_HIGHS.md:H.11`, `HARDENING_PASS_CODEX.md:H.11`, `REPORTING_ANALYTICS_DEEP_DIVE.md:A2` | None | `src/cryodaq/analytics/cooldown_service.py:96-161,297-354`; `plugins/cooldown_estimator.py:165-175,288-290` | Standardize cooldown analytics on monotonic intervals or sample-time-only logic. |
| Adaptive throttle vs stale alarm (`H.5`) | `HARDENING_PASS_CODEX.md:H.5` | `VERIFICATION_PASS_HIGHS.md:H.5` narrowed it to an edge-condition issue | `src/cryodaq/core/scheduler.py:331-377`; `src/cryodaq/engine.py:1015-1027`; `src/cryodaq/core/housekeeping.py:223-307`; `config/alarms_v3.yaml:128-133` | Separate alarm feed from throttled broker, but treat severity as “high-confidence edge-case” rather than deterministic false positive. |

## 4. Phase 2d recommended scope

### Block A: do first

**Goal:** fix the highest-risk issues that are both safety-critical and relatively contained.

- Implement real Keithley watchdog strategy decision: either upload/verify TSP watchdog or block deployment until equivalent hardware-side fail-safe exists.
- Harden `SafetyManager`: close `RUN_PERMITTED` blind spot, shield/emergency-off fault path, and bridge fault transitions into experiment metadata/logging.
- Fix stored XSS and require auth or loopback-only deployment for the web dashboard.
- Fix `AlarmStateManager.acknowledge()` so operators can actually acknowledge alarms.
- Make `safety.yaml` load fail closed and remove or de-authorize dead `alarms_v3 interlocks`.

**Effort:** ~16-24 CC hours  
**Regression risk:** medium. Safety behavior changes need careful review, but most changes are localized and testable.

### Block B: do second

**Goal:** close data integrity gaps that need transaction, file-format, or lifecycle changes.

- Make experiment sidecars and calibration index/curve writes atomic.
- Make calibration KRDG/SRDG poll cycles durable as one logical unit or tag incomplete cycles.
- Add graceful stop/drain semantics so scheduler cannot commit a batch and skip broker delivery silently.
- Verify WAL mode at startup and gate production on a safe SQLite version.
- Persist OVERRANGE/fault readings instead of dropping them from SQLite history.

**Effort:** ~20-32 CC hours  
**Regression risk:** high. This touches storage, lifecycle, migrations, and shutdown behavior.

### Block C: do third

**Goal:** defense in depth, packaging reproducibility, and operational hardening.

- Enforce `requirements-lock.txt` hash verification and pin `hatchling`.
- Fix `post_build.py` to copy plugin sidecars and document POSIX symlink-preserving deployment.
- Move writable runtime state out of the bundle directory.
- Remove executable runtime plugin loading from production bundles or mark plugin source as trusted/read-only.
- Bound web history/log queries and isolate heavy background executor consumers.

**Effort:** ~12-20 CC hours  
**Regression risk:** low to medium. Mostly build/deploy changes with contained runtime fallout.

### Block D: defer to Phase 3

**Goal:** changes that are unsafe to validate without hardware or target deployment environment.

- Real Keithley watchdog upload/heartbeat validation on physical SMU.
- Linux/Ubuntu deployment validation for SQLite, USB-TMC, CH340 serial, and future `linux-gpib`.
- Keithley rollback/off semantics under injected bus faults on actual hardware.
- Full restart/power-loss/fault-latched overnight drills on the lab PC with the real device mix.

**Effort:** ~24-40 CC hours plus operator lab time  
**Regression risk:** high unless validated on hardware.

## 5. Phase 3 deferred items

These are important, but static audit alone is not enough to close them safely.

- **Keithley watchdog integration on real hardware**: the TSP watchdog issue (`M.1`) is the clearest Phase 3 hardware task.
- **SQLite 3.51.3+ strategy on Ubuntu 22.04**: decide whether to bundle SQLite, rebuild Python against a newer libsqlite, or gate startup on detected version.
- **`linux-gpib` migration validation**: current transport code assumes PyVISA backend behavior closer to NI-VISA; Linux backend semantics need live validation.
- **USBTMC on Linux 5.15 / Ubuntu 22.04**: verify timeout, clear, and reconnect behavior with the actual Keithley.
- **CH340 / Thyracont on Linux**: confirm serial close, dropped-byte, and reconnect behavior on the target USB-serial adapter and kernel.
- **Physical interlock and threshold tuning**: any changes to `safety.yaml`, `interlocks.yaml`, or `alarms_v3.yaml` need hardware sign-off, not just unit tests.
- **Power-flicker and restart drills**: validate the persist-before-publish and restart-recovery assumptions with real power/network disruption on the lab PC.

## 6. Disputed and inconclusive

| Item | Why it is disputed or incomplete | Recommended manual review |
|---|---|---|
| `H.5` adaptive throttle vs stale alarm | `HARDENING_PASS_CODEX.md:H.5` called it a HIGH deterministic false-alarm path; `VERIFICATION_PASS_HIGHS.md:H.5` reclassified it as a real but edge-condition hazard that needs jitter/slippage to fire. | Review actual poll cadence and event-loop jitter on the lab PC; likely still worth fixing, but severity can be treated as “high-confidence edge case” rather than “always broken”. |
| Hardening source path | The requested branch path no longer contained `HARDENING_PASS_CODEX.md`; the authoritative content was still available by commit `98a57c5`. | None for code; just note that future syntheses should pin documents by commit, not moving branch names. |
| Ubuntu SQLite risk | Static docs strongly support the risk, but final deployed behavior depends on what libsqlite the frozen build actually ships/loads. | On the target Ubuntu host, log `sqlite3.sqlite_version` from the frozen bundle before deployment sign-off. |
| Plugin trust boundary | Static code proves in-process loading; practical exploitability depends on whether production plugin directories are writable by operators. | Confirm deployment ACLs on the final bundle directory. |
| Web exposure severity | Static code proves no auth; actual network exposure depends on whether deployment binds to loopback or LAN. | Decide deployment stance explicitly and document it. |

## 7. What we still don’t know

- No audit pass included **runtime hardware fault injection** on the real lab stack. The most important unknowns are still host crash while sourcing, USB/GPIB fault recovery, and actual restart behavior on the target PC.
- Legacy modules still deserve targeted review if Phase 2d goes long: `core/alarm.py`, `analytics/calibration.py` in full, `reporting/sections.py` section-by-section, and `notifications/periodic_report.py`.
- No pass gave a true **external security review** of the web surface. The current issues are obvious enough to fix internally, but if LAN exposure is intended, an outside review is still warranted.
- We still do not know whether the final operator workflow will rely on the web dashboard, Telegram commands, launcher-only GUI, or a mix. That matters for prioritizing web auth vs GUI freeze vs command replay fixes.
- The packaging story is still partly theoretical until one frozen build is installed exactly how the lab will install it on Ubuntu 22.04 and Windows.

## 8. Audit pipeline meta-observations

### What worked best

- **Inventory passes** found the first wave: obvious unauthenticated surfaces, missing timeouts, non-atomic sidecars, and packaging mistakes.
- **Hypothesis/scenario/cross-module passes** found the most valuable subtle bugs: `H.6`, `H.10`, `H.11`, `H.14`, and `P1`.
- **Focused verification passes** were essential. Without `VERIFICATION_PASS_HIGHS.md`, `H.5` would still be overstated.
- **Single-file deep dives** were worth the time. `SAFETY_MANAGER_DEEP_DIVE.md` and `PERSISTENCE_INVARIANT_DEEP_DIVE.md` turned broad concerns into precise implementation tasks.

### Where Codex overclaimed or hallucinated

- The biggest example is `H.5`: the architecture concern was real, but the original hardening wording implied a guaranteed false stale alarm from static config alone. The later verification pass correctly narrowed it.
- The hardening run’s claimed wall-clock runtime was also clearly unreliable compared with actual interaction timing. The content still had value, but the runtime claim should not be trusted.

### Where CC caught things Codex missed

- CC caught several operator-facing and loop-blocking issues Codex had not prioritized early enough: broken alarm acknowledgment (`A.1`), `finalize_experiment` blocking the engine loop (`A.4`), and launcher `time.sleep()` on the Qt thread (`H.1`).
- CC also flagged LakeShore OVERRANGE history loss earlier and more directly than Codex’s later persistence-focused passes.

### Where Codex caught things CC missed

- Codex’s later passes were stronger on cross-module provenance and deep invariants: safety fault propagation into experiment lifecycle (`H.6`), calibration poll atomicity (`H.10`), shutdown-after-commit-before-publish (`P1`), the config safety surface (`C.1-C.4`), and the SafetyManager edge-state/cancellation analysis (`F1/F2`).
- Codex also did more on build/dependency/deployment hardening, especially the hash-verification and writable-runtime-root issues.

### Recommended audit pattern going forward

1. **Before each major phase:** one broad inventory pass to catch obvious regressions.
2. **Before deployment:** one cross-module scenario pass, one verification pass on all HIGHs, and one synthesis pass like this one.
3. **After hardware or deployment-environment changes:** targeted deep dives on `SafetyManager`, persistence/shutdown, and the affected driver/transport.
4. **At least once per release cycle:** dependency/build audit focused on hashes, build backends, frozen bundle behavior, and deployment ACLs.

The main lesson is simple: for CryoDAQ, the highest-value bugs were not local code smells. They were boundary bugs between safety, persistence, analytics, packaging, and operator surfaces. Future audit effort should spend more time there and less time re-reading already-clean local modules.
