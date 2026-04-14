# Codex Full Semantic Audit — Master Branch Phase 2d/2e Closure

## REGRESSION ALERT

### HIGH — Adaptive throttle can break the Phase 2d calibration atomicity guarantee

**Location:** `src/cryodaq/core/scheduler.py:333-365`, `src/cryodaq/core/scheduler.py:379-382`, `src/cryodaq/core/calibration_acquisition.py:71-145`

Phase 2d established a stronger invariant than simple persistence-first ordering: for a calibration poll cycle, the KRDG reading and the synthetic SRDG reading must persist together in one SQLite transaction, and calibration state mutation must happen only after that persistence succeeds. Current master still defers state mutation correctly, but it now computes `persisted_readings` through `adaptive_throttle.filter_for_archive(readings)` before calibration handling, while `prepare_srdg_readings(readings, srdg)` still consumes the full unthrottled KRDG list. The persisted batch is then assembled as `persisted_readings + srdg_to_persist`.

That means a throttled-away KRDG can be absent from the SQLite transaction while the derived SRDG for that same poll is present, and `on_srdg_persisted(...)` will still commit calibration state for the cycle. This is a semantic regression against the stated Phase 2d invariant: the transaction remains atomic as a transaction, but it is no longer atomic with respect to the logical KRDG/SRDG pair that produced the calibration update. If this lands in production, downstream calibration analysis can see an SRDG sample whose source KRDG sample never made it to storage.

## Executive summary

Master at `445c056` is materially stronger than the pre-2d system. The critical Phase 2d hardening themes are largely real in code: fail-closed loading exists for the primary safety configs, `SafetyManager` fault cleanup is now broadly shielded, SQLite WAL verification exists in the writer, state-carrying infinities are preserved while NaN statuses are filtered before NOT NULL persistence, and the new Parquet stage 1 exporter is implemented as a genuinely streaming writer rather than an in-memory accumulator.

The remaining issues are no longer broad “architecture is unsafe” problems. They are narrower semantic gaps, cross-module contract leaks, and a few deferred items that still deserve attention before calling Phase 2d/2e fully closed. The most serious one is a regression candidate in the calibration path: adaptive archive throttling is now positioned early enough in `Scheduler` that it can separate the persisted KRDG/SRDG pair that Phase 2d explicitly tried to keep together.

Outside that regression, the strongest open items are consistency issues rather than outright safety failure. Alarm config parsing is structurally fail-closed but still semantically permissive in places that can silently drop alarms. `DataBroker` subscriber/filter exceptions still are not isolated from the `Scheduler` publish path, so a non-safety consumer can prevent `SafetyBroker` delivery after persistence has already succeeded. The new Parquet export path is implemented correctly at the data plane level, but it is still not represented in artifact metadata written earlier in finalization, so the archive index can lag real artifacts on disk.

I did not find evidence that Phase 2d reintroduced the older catastrophic bugs around direct Keithley control outside `SafetyManager`, silent fallback for the primary safety configs, or the earlier `_fault()` cancellation holes that were already fixed in 2d plus the follow-up shield patches. Those areas look materially improved. My confidence is highest in the deep-scope modules and lower in the skim-only optional subsystems such as plugins and notifications.

If the calibration regression is accepted as real, the overall verdict is `BLOCKING` for closure. If that issue is disproven or intentionally accepted, the remainder of master looks closer to `SIGNIFICANT_ISSUES` than “unsafe by default”: the system is largely coherent, but several deferred semantic gaps are still visible directly in code.

## Master branch stats

- Master HEAD audited: `445c056`
- Non-GUI Python files surveyed under `src/cryodaq/`: `75`
- Deep-dive modules read carefully: `16`
- Deep-dive module LoC reviewed: `10,069`
- Test files present under `tests/`: `113`
- Inventory references requested in prompt:
  - `docs/audits/BRANCH_INVENTORY.md`: not present at audit time
  - `docs/audits/REPO_INVENTORY.md`: not present at audit time
- Reported test count mismatch:
  - prompt context says `895`
  - current `PROJECT_STATUS.md` still says `890 passed, 6 skipped`
  - I did not rerun the test suite in this audit

## Findings by category

### Category A — Invariant violations

#### A.1 HIGH — Calibration atomicity is violated semantically when adaptive throttling drops the source KRDG

**Location:** `src/cryodaq/core/scheduler.py:333-365`, `src/cryodaq/core/scheduler.py:379-382`, `src/cryodaq/core/calibration_acquisition.py:71-145`

This is the regression alert above. The invariant was not just “SRDG and whatever remains after filtering are in one transaction”; it was “the KRDG/SRDG pair from one calibration cycle is persisted together, and state mutation happens only after persistence.” Current code satisfies only the second half.

The issue is caused by the sequence:

1. `persisted_readings = self._adaptive_throttle.filter_for_archive(readings)` in `Scheduler`
2. `prepare_srdg_readings(readings, srdg)` still analyzes the full unthrottled cycle
3. the persisted SQLite batch becomes `persisted_readings + srdg_to_persist`
4. `on_srdg_persisted(...)` applies calibration state after the write succeeds

That leaves a path where the derived SRDG survives persistence but the originating KRDG from the same cycle does not. This directly violates the Phase 2d calibration atomicity intent.

#### A.2 No violation found — Persistence-first ordering still holds in the narrow sense

**Location:** `src/cryodaq/core/scheduler.py:362-389`, `src/cryodaq/storage/sqlite_writer.py:641-759`

For the main read path, `Scheduler` still writes to SQLite before publishing to `DataBroker`, and only after that does it publish to `SafetyBroker`. The transaction boundary in `SQLiteWriter.write_immediate()` is still ahead of both publish calls. The system therefore still honors the narrow persistence-first invariant: there is no direct path where a reading reaches either broker before the relevant persistence attempt.

The more ambitious all-or-none interpretation remains false, but that is a separate issue already recognized in prior audits.

#### A.3 No violation found — SafetyManager remains the sole production authority for source on/off

**Location:** `src/cryodaq/core/safety_manager.py:207-244`, `src/cryodaq/engine.py:1508-1543`

I did not find a production path on master where any module other than `SafetyManager` decides source start/stop. Engine command handling routes start/stop requests through `SafetyManager.request_run()`, `SafetyManager.request_safe_off()`, `SafetyManager.acknowledge_fault()`, and the interlock/fault paths also terminate in `SafetyManager`.

There are still direct transport writes in `SafetyManager.update_limits()` for limit-setting operations, but those are not source on/off authority violations.

#### A.4 No violation found — Fail-closed loading is real for the primary safety configs

**Location:** `src/cryodaq/core/safety_manager.py:102-164`, `src/cryodaq/core/alarm_config.py:63-116`, `src/cryodaq/core/interlock.py:68-122`, `src/cryodaq/core/housekeeping.py:56-121`, `src/cryodaq/core/channel_manager.py:38-112`, `src/cryodaq/engine.py:1767-1776`

`SafetyConfigError`, `AlarmConfigError`, `InterlockConfigError`, `HousekeepingConfigError`, and `ChannelConfigError` all exist and are mapped in `engine.py` startup. Missing or malformed `safety.yaml`, `alarms_v3.yaml`, `interlocks.yaml`, `housekeeping.yaml`, and `channels.yaml` now fail startup instead of silently substituting operational defaults.

This closure is real. The remaining config problems are semantic consistency issues rather than a reversion to silent startup fallback for those files.

### Category B — Concurrency correctness

#### B.1 MEDIUM — DataBroker subscriber/filter exceptions are still on the Scheduler critical path

**Location:** `src/cryodaq/core/broker.py:85-109`, `src/cryodaq/core/scheduler.py:385-389`

`DataBroker.publish()` still iterates subscribers synchronously and executes `filter_fn(reading)` inline with no exception isolation. `Scheduler._process_readings()` calls `self._data_broker.publish_batch(persisted_readings)` and then separately `self._safety_broker.publish_batch(readings)`.

If any ordinary `DataBroker` subscriber filter or callback raises, the `publish_batch()` call aborts and the `SafetyBroker` publish step is never reached. Persistence has already succeeded, so the data is not lost, but the safety/control side sees a dropped cycle for a reason unrelated to safety data validity. That is an open concurrency and fault-isolation problem, and it keeps deferred item `P2` real.

#### B.2 MEDIUM — Interlock action execution still serializes the processing queue

**Location:** `src/cryodaq/core/interlock.py:405-470`

`InterlockEngine._process_reading()` awaits `_trip()` inline, and `_trip()` awaits both the configured `action_callable` and the optional `trip_handler`. There is no timeout or off-queue execution boundary for those callbacks. One slow action therefore delays evaluation of all later readings queued behind it.

This is not new, but it remains an operational blind spot. If an interlock action blocks on hardware or on an external callback, interlock evaluation latency can stretch exactly when fast response is most valuable.

#### B.3 No violation found — SafetyManager post-fault cleanup is materially better shielded than pre-2d

**Location:** `src/cryodaq/core/safety_manager.py:630-744`, `src/cryodaq/core/safety_manager.py:746-811`

The critical post-fault cleanup path is now intentionally shielded. `_fault()` latches state first, then uses `asyncio.shield(...)` around `_ensure_output_off()` and again around the fault log callback. `_safe_off()` in the latched path also uses the hardened cleanup path. That closes the earlier cancellation holes well enough that I did not identify a direct reversion on current master.

I still would not call the entire module cancellation-proof in the abstract, but the specific 2d/2d-followup shield work looks real.

### Category C — Error handling completeness

#### C.1 MEDIUM — Alarm config loader is structurally fail-closed but semantically fail-open in `_expand_alarm` and `channel_group` expansion

**Location:** `src/cryodaq/core/alarm_config.py:119-142`, `src/cryodaq/core/alarm_config.py:151-205`

Two deferred semantic gaps remain visible:

1. `_expand_alarm()` returns `None` when the alarm payload is not a mapping, instead of raising `AlarmConfigError`.
2. `_expand_channel_group()` quietly skips unknown `channel_group` names instead of treating them as startup-fatal semantic errors.

That means a syntactically valid but semantically wrong `alarms_v3.yaml` can still disable intended alarms without tripping the fail-closed startup path. The parser now protects against missing or malformed top-level config, but not against all safety-meaningful content errors.

#### C.2 MEDIUM — `_load_drivers()` still raises generic runtime errors instead of typed config failures

**Location:** `src/cryodaq/engine.py:673-719`, `src/cryodaq/engine.py:1767-1776`

Phase 2d standardized several config loaders on typed startup errors, but driver loading is still ad hoc. `_load_drivers()` uses raw YAML reads and direct indexing into configuration structure, and it can fail via `KeyError`, `TypeError`, or `ValueError` without being normalized into the same fail-closed error taxonomy as the other critical startup configs.

The effect is not silent fallback, but it is inconsistent and harder to operate. Operators get a generic startup exception instead of a clearly labeled configuration failure class.

#### C.3 LOW — Best-effort exception patterns are mostly localized and look deliberate

**Location:** `src/cryodaq/core/safety_manager.py:699-744`, `src/cryodaq/core/experiment.py:732-759`

The main places using best-effort exception swallowing are the ones that should be best-effort: Keithley channel-state publish after a latched fault, and optional Parquet export during experiment finalization. In both cases the code logs the failure and preserves the primary correctness contract. I did not find the earlier “best-effort spread” concern leaking through the whole codebase.

### Category D — Fail-closed config consistency

#### D.1 MEDIUM — `.local.yaml` still replaces, rather than merges with, the base config

**Location:** `src/cryodaq/engine.py:779-782`

The `_cfg(name)` helper still chooses `name.local.yaml` if it exists and otherwise falls back to `name.yaml`. It does not merge overlay semantics into the base file. That means a partial local override file effectively replaces the full config and can silently drop unrelated settings.

This is not a reversion of the typed fail-closed work, but it remains an important consistency gap. It is especially awkward now that the project has invested heavily in schema-like startup validation elsewhere.

#### D.2 MEDIUM — Optional configs still use inconsistent loader discipline

**Location:** `src/cryodaq/engine.py:985-989`, `src/cryodaq/notifications/telegram.py:83-133`, `src/cryodaq/notifications/escalation.py:33-82`

Critical safety configs are now loaded through typed validators, but optional configs such as `plugins.yaml` and the notification settings still use ad hoc YAML loading. That is defensible because they are optional features, but it means the codebase no longer has a uniform “bad config always produces a labeled startup failure” rule.

This matters less for safety correctness than for operator comprehension. Right now the project mixes strict and loose config semantics depending on subsystem.

### Category E — Cross-module consumer discovery

#### E.1 MEDIUM — `alarms_v3.yaml` still has more than one production reader

**Location:** `src/cryodaq/engine.py:947-970`, `src/cryodaq/core/housekeeping.py:259-315`

Phase 2d already taught that `alarms_v3.yaml` is not owned only by alarm code. Current master still has at least two production readers:

- `engine.py` loads it for alarm configuration
- `housekeeping.py` reads the `interlocks` section to derive retention/throttle-related behavior

That is not automatically wrong, but it is easy to miss and should stay explicitly documented. The file is functioning as a shared control-plane config, not a single-subsystem config.

#### E.2 No violation found — `ChannelManager._DEFAULT_CHANNELS` does not appear to leak into production startup

**Location:** `src/cryodaq/core/channel_manager.py:18-36`, `src/cryodaq/core/channel_manager.py:177-230`

The legacy default channel list still exists for tests and convenience construction, but I did not find a production startup path on master that falls back to it after C-1. `engine.py` now loads channel definitions explicitly and will fail startup on channel config load errors.

This was worth checking because the fallback list surviving in the module would have been a classic fail-closed leak. I did not find one.

#### E.3 No violation found — `SafetyManager.acknowledge_fault()` and `AlarmStateManager.acknowledge()` caller surfaces are narrow

**Location:** `src/cryodaq/engine.py:1508-1543`, `src/cryodaq/core/alarm_v2.py:354-388`

The acknowledgement APIs are not widely scattered through the codebase. On master they remain effectively centralized behind engine command handling, which reduces the risk of hidden state transitions.

### Category F — Parquet stage 1 correctness

#### F.1 MEDIUM — The Parquet data plane is sound, but artifact metadata still lags the real artifact set

**Location:** `src/cryodaq/core/experiment.py:722-759`, `src/cryodaq/storage/parquet_archive.py:31-141`

The Parquet writer itself looks correct for stage 1:

- writer opened once per export
- `snappy` compression requested
- chunked export via `cursor.fetchmany(chunk_size)`
- UTC microsecond timestamps
- `experiment_id` added to every row
- missing day files skipped into a `skipped_days` list
- `writer.close()` guaranteed in `finally`

The remaining gap is integration metadata. `ExperimentManager.finalize_experiment()` writes archive metadata and artifact index first, then later invokes the Parquet export hook as a best-effort step, and does not rewrite the artifact index after Parquet succeeds. The file can therefore exist on disk without being represented in the metadata snapshot.

This is not a data corruption issue, but it is a real correctness gap for downstream tooling that trusts the artifact index as authoritative.

#### F.2 No violation found — Streaming export and timestamp conversion are implemented correctly enough for stage 1

**Location:** `src/cryodaq/storage/parquet_archive.py:52-141`

I did not find evidence of the usual stage-1 Parquet mistakes. The exporter does not accumulate all rows in memory, it does not use naive `datetime.fromtimestamp()` without UTC, and it does not silently skip `experiment_id` population. The chunk-based writer is a good fit for the stated stage.

### Category G — Untested critical paths

I could not use the requested CC coverage map because the referenced inventory docs were absent, so this section is based on direct test-name/code-path inspection rather than a complete coverage database.

#### G.1 MEDIUM — Semantic alarm-config failure paths still look undertested

**Location:** `src/cryodaq/core/alarm_config.py:151-205`

I found tests for missing/malformed top-level alarm config, but not obvious coverage for the semantic cases that matter here: non-mapping alarm entries, unknown `channel_group` references, and malformed expansion behavior that currently returns `None` or silently skips. These are exactly the residual fail-closed gaps in the module.

**Needed test class:** unit tests for semantic config rejection, not just syntax/shape rejection.

#### G.2 MEDIUM — DataBroker exception isolation path remains effectively untested

**Location:** `src/cryodaq/core/broker.py:85-109`, `src/cryodaq/core/scheduler.py:385-389`

I did not see evidence of a test that injects a failing `DataBroker` filter/callback and verifies that `SafetyBroker` still receives the cycle. That is the critical behavior if deferred `P2` is ever implemented, and the absence of the test is part of why the issue remains open.

**Needed test class:** integration test around `Scheduler._process_readings()` with a deliberately raising `DataBroker` subscriber and a probe on `SafetyBroker`.

#### G.3 LOW — Dedicated `channels.yaml` fail-closed coverage still appears missing

**Location:** `src/cryodaq/core/channel_manager.py:38-112`

The production path looks correct, but the specific deferred minor item about dedicated `channels.yaml` fail-closed tests still appears real. This is a test gap rather than a code gap.

**Needed test class:** unit tests for missing/malformed/empty channel config files through production loader wiring.

#### G.4 LOW — Scheduler drain timeout test still references the old constant path

**Location:** `tests/core/test_scheduler.py:231`

The deferred minor note that a scheduler test still mutates the dead `_DRAIN_TIMEOUT_S` class constant rather than the instance `_drain_timeout_s` still appears real. This does not undermine runtime behavior, but it weakens confidence in the shutdown-drain test’s relevance.

**Needed test class:** update the existing unit test rather than add new coverage.

### Category H — Deferred items sanity check

#### H.1 `A.7.5` — Still open and real

**Location:** `src/cryodaq/core/alarm_config.py:119-205`

As noted above, the remaining semantic parse gaps are still visible directly in code. This is urgent enough to keep in the next hardening block because it affects safety logic activation, not just ergonomics.

#### H.2 `A.8.1` — Still open but genuinely minor

**Location:** test-only concern around shield timeout bounding

I did not audit this deeply because it is explicitly cosmetic and test-oriented. Nothing in current runtime code suggests it grew into a semantic production risk.

#### H.3 `A.9.1` — Still open

**Location:** engine command handler / ZMQ acknowledged state serialization path

I did not find evidence that this was silently closed. The ack state still appears to be handled operationally rather than through a stronger serialized end-to-end command-state contract. This looks deferrable unless the web/remote control surface is expanding immediately.

#### H.4 `B.1.2` — Still open by design

**Location:** `src/cryodaq/storage/sqlite_writer.py:52-74`, `src/cryodaq/storage/sqlite_writer.py:530-601`

The current code clearly chose one side of the tradeoff: persist state-carrying infinities, drop NaN-valued timeout/sensor-error statuses before the NOT NULL insert. That resolves the immediate integrity failure, but it still leaves the longer-term question of whether NaN-state rows need sentinel/schema support. This remains open, not silently closed.

#### H.5 `C-1.1 minor` — Still open

**Location:** `tests/core/test_scheduler.py:231`

See G.4. This is still a stale-test issue, not a runtime issue.

#### H.6 `C-1.2 minor` — Still open as a test gap, not a code gap

**Location:** `src/cryodaq/core/channel_manager.py:38-112`

The fail-closed behavior looks real; the dedicated coverage still appears missing.

#### H.7 `2e-parquet-1.a..d` — Partially closed

**Location:** `src/cryodaq/storage/parquet_archive.py:31-141`, `src/cryodaq/core/experiment.py:722-759`

Stage 1 closes much of the technical core:

- streaming writes: closed
- compression: closed via `snappy`
- midnight/day iteration: closed in exporter logic
- timestamp precision: closed at microsecond UTC conversion

What remains open is finalize integration and artifact metadata coherence. The exporter works, but finalization still treats it as best-effort add-on rather than first-class artifact inventory.

#### H.8 `P2` — Still open and real

**Location:** `src/cryodaq/core/broker.py:85-109`, `src/cryodaq/core/scheduler.py:385-389`

No silent closure. Subscriber exception isolation is still missing on the `DataBroker` side.

#### H.9 `P3` — Still open

**Location:** `src/cryodaq/core/scheduler.py:362-365`, `src/cryodaq/storage/sqlite_writer.py:676-759`

Day-boundary splitting exists in `SQLiteWriter`, but `Scheduler` still hands a single logical batch into the writer and does not itself expose day-split semantics to downstream consumers. I did not find evidence that the broader “scheduler-level day-boundary behavior” deferred item was silently closed elsewhere.

#### H.10 `C.1` — Still open and appropriately deferred to deployment/hardware packaging

**Location:** deployment/runtime, not purely code-local

Nothing in master changes the fact that Ubuntu SQLite version gating remains a packaging/deployment question rather than a pure Python code fix. This still belongs in Phase 3.

#### H.11 `C.3` — Still open and policy-level

**Location:** `src/cryodaq/storage/sqlite_writer.py` pragmas

The code still uses the current synchronous mode decision. I did not find silent closure of the “should this be FULL?” question. This remains a deployment/performance tradeoff, not an unnoticed code change.

#### H.12 Jules fail-closed items for interlocks/housekeeping/channels — closed in code

**Location:** `src/cryodaq/core/interlock.py:68-122`, `src/cryodaq/core/housekeeping.py:56-121`, `src/cryodaq/core/channel_manager.py:38-112`, `src/cryodaq/engine.py:1767-1776`

These appear genuinely closed. The typed config errors exist, startup maps them, and I did not find a production fallback bypass.

### Category I — Safety blind spots

#### I.1 No unsafe behavior found — `stale_timeout_s: 0` fails hard, not open

**Location:** `src/cryodaq/core/safety_manager.py:333-382`, `src/cryodaq/core/safety_manager.py:812-921`

This configuration mistake would make the system effectively unusable, but it fails safe. Preconditions and ongoing checks would immediately consider readings stale or heartbeat-late rather than quietly disabling monitoring.

#### I.2 No unsafe behavior found — repeated GPIB failure still trends toward fail-stop

**Location:** `src/cryodaq/core/scheduler.py:172-330`, `src/cryodaq/core/safety_manager.py:812-921`

Repeated driver failures still go through scheduler error handling and then through stale/heartbeat safety checks. I did not find a path where continued hardware read failure silently keeps the experiment running as if data were healthy.

#### I.3 MEDIUM — Alarm and cooldown logic remain vulnerable to backward wall-clock jumps

**Location:** `src/cryodaq/core/channel_state.py:65-135`, `src/cryodaq/analytics/cooldown_service.py:297-353`

Phase 2d concentrated on `SafetyManager`, but not every time-sensitive subsystem moved to monotonic semantics. `ChannelStateTracker` still mixes reading timestamps with `time.time()`, and cooldown analytics also compare reading time with wall-clock. A backward NTP correction therefore can distort stale detection and rate estimates outside the primary safety FSM.

This is not the same severity as a SafetyManager timing bug, but it remains a real operational edge case.

#### I.4 No unsafe behavior found — disk-full path appears to escalate through persistence failure handling

**Location:** `src/cryodaq/storage/sqlite_writer.py:530-601`, `src/cryodaq/storage/sqlite_writer.py:641-759`

`SQLiteWriter` explicitly recognizes disk-full operational errors, sets its disk-full flag, and routes persistence failure into the higher-level failure handling. I did not find evidence of a silent continue-on-ENOSPC path in the main write route.

The only caveat is that Python-level bare `OSError(ENOSPC)` is not separately handled here, so this conclusion assumes the practical failure arrives through SQLite as `OperationalError`, which is the normal case.

#### I.5 No unsafe behavior found — duplicate experiment start is still operationally serialized

**Location:** `src/cryodaq/engine.py:1508-1543`, `src/cryodaq/core/experiment.py:209-328`

The control surface is serialized through the command server path, and `ExperimentManager` itself maintains active experiment state. I did not identify a straightforward master-branch path where two operators can create two simultaneous active experiments in one engine instance.

#### I.6 MEDIUM — `finalize_experiment()` remains sensitive to repeated invocation semantics

**Location:** `src/cryodaq/core/experiment.py:560-759`

I did not find a clearly dangerous double-finalize bug, but the method still combines metadata writes, report generation hooks, and the new Parquet best-effort export in a large imperative sequence. If some caller ever re-enters finalize after partial completion, behavior is likely “idempotent only by accident” rather than by a deliberately enforced contract.

This is a blind spot worth testing even though I did not prove an active bug from static reading alone.

## Cross-cutting observations

Three patterns stand out across master.

First, Phase 2d materially improved the codebase by moving several previously ad hoc behaviors into explicit invariants: typed config failures, shielded fault cleanup, explicit state-carrying-status rules, and post-persistence calibration state mutation. The code now reads like it has a stronger contract vocabulary than the earlier phases.

Second, the remaining problems are often not in the local code block that “owns” the feature. They appear at boundaries: throttling versus calibration persistence, ordinary broker subscribers versus safety delivery, metadata writing versus optional archive artifacts, or primary monotonic safety timing versus secondary wall-clock analytics/alarm timing. The project is now much more likely to fail at module seams than from obviously broken single-module code.

Third, the codebase still mixes strict and loose operational disciplines. Safety-critical configs are now typed and fail-closed, but optional configs still use permissive loaders. Primary shutdown paths are carefully shielded, but secondary pipelines still use best-effort patterns. Storage paths are increasingly transactional, but artifact metadata remains partly procedural. That split is rational, but it should stay explicit so operators do not assume the entire system has identical correctness guarantees everywhere.

## Verdict

`BLOCKING`

If the regression alert in the calibration path is accepted as real, I would not call Phase 2d/2e closure clean. The strongest reason is that the regression violates a recently established canonical invariant rather than exposing a merely cosmetic inconsistency.

If that regression is disproven or intentionally accepted, the remaining master issues look more like `SIGNIFICANT_ISSUES` than a deployment block: there are several medium-priority semantic gaps, but the major 2d hardening themes appear to have landed successfully.

## Top 10 actionable items

1. **Immediate** — Fix the calibration regression by ensuring the persisted KRDG/SRDG pair is formed before adaptive archive throttling, or by exempting calibration-reference KRDG rows from throttle suppression.
2. **Immediate** — Close deferred `A.7.5` by making `_expand_alarm()` and unknown `channel_group` expansion raise `AlarmConfigError` instead of silently dropping semantics.
3. **Immediate** — Close deferred `P2` by isolating `DataBroker` subscriber/filter exceptions so `SafetyBroker` delivery cannot be suppressed by non-safety consumers.
4. **Next Block** — Make Parquet export a first-class artifact in finalization metadata, or explicitly mark it as post-index best-effort in the artifact contract.
5. **Next Block** — Replace `_cfg()` override replacement semantics with explicit merge semantics or explicit “full replacement required” validation.
6. **Next Block** — Normalize `_load_drivers()` onto the same typed config-failure pattern as the other critical startup loaders.
7. **Next Block** — Add tests for semantic alarm-config rejection, `DataBroker` exception isolation, and the calibration/throttle regression path.
8. **Phase 3** — Revisit wall-clock-sensitive logic in `channel_state.py` and cooldown analytics for backward-clock resilience.
9. **Phase 3** — Revisit interlock action execution model if callback latency under trip conditions becomes a practical concern.
10. **Reject as urgent runtime work** — The stale scheduler drain timeout test constant mismatch should be fixed, but it is test debt, not production debt.

## Things I was uncertain about

- The prompt references `docs/audits/BRANCH_INVENTORY.md` and `docs/audits/REPO_INVENTORY.md`, but those files were not present, so I could not use CC’s promised coverage map for Category G.
- I did not rerun tests, so the exact `890` versus `895` test count discrepancy in prompt versus `PROJECT_STATUS.md` remains unresolved in this audit.
- The severity of the calibration regression depends on whether adaptive throttling is guaranteed to spare calibration-reference KRDG rows by configuration or calling convention. I did not find such a guarantee in code, but that assumption should still be checked against intended runtime policy.
- I only skimmed optional subsystems outside the named deep-scope files. I am confident in the stated flags there, but not at the same level as the deep-dive modules.

## Confidence ratings

- **Category A — HIGH.** The main invariants were checked directly in the owning code paths and the regression candidate is grounded in an explicit sequence of calls.
- **Category B — HIGH.** The remaining concurrency concerns are visible in straight-line control flow and do not depend on speculative runtime behavior.
- **Category C — HIGH.** The alarm config semantic gaps and driver-load inconsistency are direct parser/loader behaviors, not inferred side effects.
- **Category D — HIGH.** The `.local.yaml` replacement rule and optional-config inconsistency are explicit in the current loaders.
- **Category E — MEDIUM.** Cross-module consumer discovery is good for the deep-scope files, but I did not perform exhaustive whole-repo call-graph construction.
- **Category F — HIGH.** The Parquet exporter and finalize hook were read directly and the metadata gap is visible in code ordering.
- **Category G — MEDIUM.** Coverage assessment is weaker because the referenced CC inventory docs were absent and I did not run coverage tooling.
- **Category H — HIGH.** The deferred-item status checks are mostly direct code confirmations against the named backlog items.
- **Category I — MEDIUM.** The blind-spot analysis is code-grounded, but some scenarios would benefit from runtime fault-injection to confirm operational severity.
