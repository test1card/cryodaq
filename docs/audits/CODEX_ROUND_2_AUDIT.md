# Codex Round 2 Extended Semantic Audit

## Executive summary

Round 2 changes the round 1 headline. The earlier `BLOCKING` verdict was driven primarily by a suspected calibration atomicity regression: adaptive throttling looked able to drop the source KRDG reading while the derived SRDG reading still persisted and advanced calibration state. After reading the throttle implementation, scheduler call site, calibration acquisition service, and the shipped production config, that exact `T1`-style production scenario is not supported by current master.

The finding is not fully gone. It becomes narrower and more concrete: the throttle is still calibration-unaware, and the engine still activates calibration acquisition from raw `custom_fields` strings without canonicalizing them against runtime channel labels. In the current config, the common `Т1` through `Т8` channels are exempt from throttling by `housekeeping.yaml`, and `Т9` through `Т12` are additionally protected by interlock-derived patterns, so the round 1 blocking case is refuted for the normal reference-channel choices. But if an experiment uses an unprotected throttled channel such as `Т13` through `Т20` as its calibration reference, or if the caller supplies short IDs that do not match runtime full labels, the logical KRDG/SRDG pairing contract is still weak.

Outside that regression check, round 2 mostly confirms round 1’s medium-severity seam problems rather than finding new catastrophic ones. `DataBroker` subscriber exceptions still sit on the critical path before `SafetyBroker`, so one ordinary consumer can suppress safety delivery after SQLite persistence. Wall-clock time remains in secondary logic that Phase 2d did not touch: `ExperimentPhaseProvider`, `ChannelStateTracker`, and parts of `CooldownService` still respond badly to backward NTP corrections. The new Parquet stage is structurally sound, but artifact metadata still lags the actual artifact set when export succeeds after the archive index is already written.

The overall state of master is stronger than pre-2d and stronger than round 1 implied. The primary safety-config fail-closed work is real, the `SafetyManager` shield work is real, the persistence-first invariant still holds in its narrow sense, and the new archive writer is genuinely streaming. The remaining issues are mainly cross-module contract gaps, test debt on critical semantic paths, and a few subsystems that Phase 2d never normalized to the same discipline as the main safety and persistence path.

Top concerns for immediate follow-up are:

1. The calibration path still lacks explicit protection and normalization for reference/target channel identities.
2. `DataBroker` exception isolation remains open and still can suppress `SafetyBroker` delivery after successful persistence.
3. Secondary wall-clock consumers were left behind by the main safety hardening and still need either monotonic semantics or explicit acceptance tests.

## REGRESSION VERIFICATION — Calibration throttle interaction

**Round 1 finding:** `BLOCKING` — calibration atomicity violated via adaptive throttle.

**Round 2 verdict:** `PARTIALLY REAL`

### Evidence

The scheduler still applies archive throttling before calibration SRDG preparation:

```python
# src/cryodaq/core/scheduler.py:333-365
persisted_readings = list(readings)
if self._adaptive_throttle is not None:
    persisted_readings = self._adaptive_throttle.filter_for_archive(readings)

# Step 1a: If calibration acquisition active, read SRDG BEFORE persisting
srdg_to_persist: list = []
srdg_pending_state = None
...
srdg_to_persist, srdg_pending_state = (
    self._calibration_acquisition.prepare_srdg_readings(readings, srdg)
)
...
combined = list(persisted_readings) + srdg_to_persist
await self._sqlite_writer.write_immediate(combined)
```

The calibration service still computes pending calibration state from the full unthrottled KRDG set and only later applies that state after persistence:

```python
# src/cryodaq/core/calibration_acquisition.py:90-129
pending: dict[str, float] = {}
for r in krdg:
    if r.channel == self._reference_channel and r.status == ChannelStatus.OK:
        t = r.value
        if not math.isfinite(t) or t < 1.0:
            continue
        ...

for reading in srdg:
    if reading.channel not in self._target_channels:
        continue
    ...
    to_write.append(
        Reading(
            ...
            channel=f"{reading.channel}_raw",
            ...
        )
    )

return (to_write, pending if pending else None)
```

The throttle itself is not calibration-aware. It only knows alarms, state transitions, status, include/exclude regexes, and externally injected protected patterns:

```python
# src/cryodaq/core/housekeeping.py:257-293
def observe_runtime_signal(self, reading: Reading) -> None:
    ...
    if channel == "analytics/safety_state":
        state = str(reading.metadata.get("state", "")).lower()
        if state != "running":
            self._transition_until = reading.timestamp + timedelta(seconds=self._transition_holdoff_s)

def _should_emit(self, reading: Reading) -> bool:
    if self._active_alarm_count > 0:
        return True
    if reading.status is not ChannelStatus.OK:
        return True
    if self._transition_until is not None and reading.timestamp <= self._transition_until:
        return True
    if self._matches_any(reading.channel, self._protected):
        return True
    if self._matches_any(reading.channel, self._exclude):
        return True
    if self._include and not self._matches_any(reading.channel, self._include):
        return True
```

The production throttle config exempts `Т1` through `Т8` from throttling entirely, because only channels matching the `include_patterns` are candidates for suppression:

```yaml
# config/housekeeping.yaml:1-19
adaptive_throttle:
  enabled: true
  include_patterns:
    - "^[TТ](?![1-8] ).*"
    - "pressure"
```

Engine wiring also injects protected patterns derived from both legacy interlocks and `alarms_v3.yaml`, which protects `Т9` through `Т12` in the shipped config:

```python
# src/cryodaq/engine.py:820-836
legacy_patterns = load_protected_channel_patterns(alarms_cfg, interlocks_cfg)
alarms_v3_path = _CONFIG_DIR / "alarms_v3.yaml"
v3_patterns = load_critical_channels_from_alarms_v3(alarms_v3_path)
merged_patterns = list({*legacy_patterns, *v3_patterns})
adaptive_throttle = AdaptiveThrottle(
    housekeeping_raw.get("adaptive_throttle", {}),
    protected_patterns=merged_patterns,
)
```

And the interlock config does in fact cover `Т9` through `Т12`:

```yaml
# config/interlocks.yaml:17-45
- name: "overheat_cryostat"
  channel_pattern: "Т[1-8] .*"
...
- name: "overheat_compressor"
  channel_pattern: "Т(9|10|11|12) .*"
...
- name: "detector_warmup"
  channel_pattern: "Т12 .*"
```

### Is reference channel protected?

**Yes for the common production reference choices, but not by calibration awareness.**

- `Т1` through `Т8` are protected indirectly because they do not match the throttle’s `include_patterns`, so they are always emitted.
- `Т9` through `Т12` are protected indirectly because engine injects interlock- and alarm-derived protected regexes.
- `Т13` through `Т20` are not protected by the shipped config and remain throttle candidates.

The important distinction is that the protection comes from generic channel regex configuration, not from any explicit calibration contract. `AdaptiveThrottle` does not know which channel is the active calibration reference.

### Is the violation scenario reachable in production configuration?

**Not for the round 1 `T1`-style scenario. Potentially yes for other reference channels or malformed custom fields.**

The specific scenario described in round 1 was:

1. Calibration active with `reference_channel = "T1"`.
2. Scheduler polls a KRDG batch containing the reference channel.
3. Throttle drops the reference reading.
4. SRDG still persists and calibration state advances.

Current production config does not support step 3 for `Т1` through `Т8`, so that exact blocking scenario is refuted.

Two narrower scenarios remain real:

1. **Unprotected reference channel:** if calibration uses `Т13` through `Т20` as the reference channel, the throttle can still suppress the KRDG source while SRDG persists from the full unthrottled batch.
2. **Channel identity mismatch:** engine activates calibration acquisition from raw `custom_fields` strings without canonicalizing them to runtime full channel names:

```python
# src/cryodaq/engine.py:370-375
custom_fields = _normalize_custom_fields_payload(cmd.get("custom_fields"))
reference = str(custom_fields.get("reference_channel", "")).strip()
targets_raw = str(custom_fields.get("target_channels", "")).strip()
targets = [t.strip() for t in targets_raw.split(",") if t.strip()]
if reference and targets:
    service.activate(reference, targets)
```

The calibration service then uses exact string equality against runtime `Reading.channel` values:

```python
# src/cryodaq/core/calibration_acquisition.py:92-107
for r in krdg:
    if r.channel == self._reference_channel and r.status == ChannelStatus.OK:
        ...

for reading in srdg:
    if reading.channel not in self._target_channels:
        continue
```

That means short IDs such as `Т1` or `Т2` only work if the runtime channel names are also short IDs. In production, channel names are full labels from `config/instruments.yaml`, so the current path relies on the caller already supplying full runtime strings.

### Conclusion

Round 1’s blocking statement was too broad. The shipped config protects the usual reference-channel cases, so the exact production `Т1` scenario is not reproducible on current master.

The issue is still worth fixing, but it is no longer a release-blocking proof of broken calibration persistence. The real remaining problem is a weaker and more actionable contract gap:

- `AdaptiveThrottle` has no calibration-awareness and therefore provides no invariant-level protection for arbitrary reference channels.
- `engine.py` does not canonicalize calibration `custom_fields` against runtime channel names, so correctness depends on callers passing exact display labels.

**Priority:** `MEDIUM`

**Recommended direction:** make reference/target channels explicit runtime-resolved entities before activation, and either exempt active calibration reference/targets from throttling or prove by validation that only protected channels may be used in calibration acquisition.

## Secondary module deep review

### Module: src/cryodaq/core/broker.py

**LoC:** 120  
**Purpose:** async fan-out broker for non-safety readings.  
**Test coverage:** has direct tests (`tests/core/test_broker.py`) plus integration coverage.  
**Round 1 status:** deep-dive.

**Invariant violations:** none new. Round 1 persistence-first analysis still stands.  
**Concurrency correctness issues:** `publish()` executes subscriber filters inline and does not isolate exceptions; this is still the real `P2` seam (`src/cryodaq/core/broker.py:85-109`).  
**Error handling gaps:** `filter_fn` and `put_nowait` path do not log which subscriber caused failure because filter exceptions simply escape.  
**Cross-module contract issues:** because `Scheduler` publishes to `DataBroker` before `SafetyBroker`, a failing ordinary subscriber can suppress later safety delivery (`src/cryodaq/core/scheduler.py:385-389`).  
**Hidden dependencies:** none.  
**Safety blind spots:** this remains the cleanest way for a non-safety consumer to interfere with safety visibility after persistence.  
**Overall severity:** `HIGH`

### Module: src/cryodaq/core/safety_broker.py

**LoC:** 127  
**Purpose:** separate safety-data fan-out with fail-on-overflow semantics.  
**Test coverage:** direct and integration coverage exists.  
**Round 1 status:** deep-dive.

**Invariant violations:** none.  
**Concurrency correctness issues:** no new issue found; `_last_update` uses `time.monotonic()` and overflow callback is awaited inline by design (`src/cryodaq/core/safety_broker.py:78-110`).  
**Error handling gaps:** overflow callback errors are logged and suppressed, which is appropriate because the overflow condition itself is already terminal.  
**Cross-module contract issues:** still depends on scheduler reaching it after `DataBroker.publish_batch()`.  
**Hidden dependencies:** none.  
**Safety blind spots:** none beyond the already-known dependency on broker ordering.  
**Overall severity:** `MINOR`

### Module: src/cryodaq/core/zmq_bridge.py

**LoC:** 370  
**Purpose:** PUB/SUB and REP socket bridge between engine and external clients.  
**Test coverage:** direct tests exist.  
**Round 1 status:** skim.

**Invariant violations:** none.  
**Concurrency correctness issues:** `_bind_with_retry()` uses blocking `time.sleep()` in startup retry logic (`src/cryodaq/core/zmq_bridge.py:39-74`). This is startup-only, but it still violates the “no blocking on event loop” discipline if called from async startup.  
**Error handling gaps:** the REP server loop is robust and always tries to send a reply even on handler exceptions or cancellation (`src/cryodaq/core/zmq_bridge.py:283-340`).  
**Cross-module contract issues:** none new.  
**Hidden dependencies:** relies on socket `LINGER=0` being set before `_bind_with_retry()`, documented but not enforced by type or API.  
**Safety blind spots:** startup bind storms can stall engine startup retries synchronously.  
**Overall severity:** `LOW`

### Module: src/cryodaq/core/zmq_subprocess.py

**LoC:** 156  
**Purpose:** isolated subprocess bridge for ZMQ clients.  
**Test coverage:** direct tests exist.  
**Round 1 status:** skim.

**Invariant violations:** none.  
**Concurrency correctness issues:** none obvious; isolation boundary is the main protection.  
**Error handling gaps:** cleanup and process-stop paths look explicit and are covered by dedicated tests.  
**Cross-module contract issues:** none found in this pass.  
**Hidden dependencies:** none.  
**Safety blind spots:** no new ones beyond known operational dependence on ZMQ availability.  
**Overall severity:** `CLEAN`

### Module: src/cryodaq/core/event_logger.py

**LoC:** 35  
**Purpose:** append events into operator/event storage.  
**Test coverage:** direct tests exist.  
**Round 1 status:** skim.

**Invariant violations:** none.  
**Concurrency correctness issues:** no mutable shared-state complexity.  
**Error handling gaps:** nothing significant in the tiny surface area.  
**Cross-module contract issues:** none.  
**Hidden dependencies:** none.  
**Safety blind spots:** none.  
**Overall severity:** `CLEAN`

### Module: src/cryodaq/core/operator_log.py

**LoC:** 39  
**Purpose:** operator log append/query helper.  
**Test coverage:** direct tests plus reporting/web consumers.  
**Round 1 status:** skim.

**Invariant violations:** none.  
**Concurrency correctness issues:** no internal concurrency complexity found.  
**Error handling gaps:** no substantive gap visible in this small wrapper.  
**Cross-module contract issues:** none beyond the already-closed web XSS work.  
**Hidden dependencies:** consumed by reporting and web layers.  
**Safety blind spots:** none new.  
**Overall severity:** `CLEAN`

### Module: src/cryodaq/core/alarm_providers.py

**LoC:** 118  
**Purpose:** provide phase and setpoint context to alarm engine v2.  
**Test coverage:** partial integration coverage; no obvious direct unit tests for elapsed-time edge cases.  
**Round 1 status:** skim.

**Invariant violations:** none.  
**Concurrency correctness issues:** none.  
**Error handling gaps:** malformed timestamps fail closed to `0.0`, which is acceptable.  
**Cross-module contract issues:** `ExperimentPhaseProvider.get_phase_elapsed_s()` still uses `time.time() - dt.timestamp()` (`src/cryodaq/core/alarm_providers.py:42-64`).  
**Hidden dependencies:** depends on `ExperimentManager` storing ISO timestamps and on wall-clock continuity.  
**Safety blind spots:** backward NTP correction can make phase-duration alarms jump backward or forward even though Phase 2d hardened the main safety path elsewhere.  
**Overall severity:** `MEDIUM`

### Module: src/cryodaq/core/channel_state.py

**LoC:** 140  
**Purpose:** rolling state tracker for channels, staleness, and fault windows.  
**Test coverage:** direct tests exist.  
**Round 1 status:** skim.

**Invariant violations:** none.  
**Concurrency correctness issues:** none severe inside the single-threaded access model.  
**Error handling gaps:** none new.  
**Cross-module contract issues:** still uses `time.time()` for staleness and fault-window trimming (`src/cryodaq/core/channel_state.py:95-135`).  
**Hidden dependencies:** depends on wall-clock monotonicity even though the safety broker tracks updates with `monotonic()`.  
**Safety blind spots:** backward clock jumps can distort stale-channel and intermittent-fault logic outside `SafetyManager`.  
**Overall severity:** `MEDIUM`

### Module: src/cryodaq/analytics/cooldown_service.py

**LoC:** 476  
**Purpose:** consume readings, detect cooldown phase, buffer history, and publish predictions.  
**Test coverage:** direct tests exist.  
**Round 1 status:** skim.

**Invariant violations:** none.  
**Concurrency correctness issues:** CPU-heavy prediction is correctly offloaded via executor.  
**Error handling gaps:** model absence is handled gracefully.  
**Cross-module contract issues:** still mixes reading timestamps with `time.time()` when computing elapsed cooldown duration (`src/cryodaq/analytics/cooldown_service.py:297-315`, `351-365`).  
**Hidden dependencies:** assumes wall-clock continuity after `_cooldown_wall_start` is seeded from reading timestamps.  
**Safety blind spots:** backward NTP jumps can skew predictor elapsed time while the buffer history remains based on reading timestamps.  
**Overall severity:** `MEDIUM`

### Module: src/cryodaq/analytics/vacuum_trend.py

**LoC:** 434  
**Purpose:** pressure trend modeling and derived metrics.  
**Test coverage:** direct tests exist.  
**Round 1 status:** skim.

**Invariant violations:** none found in this pass.  
**Concurrency correctness issues:** none notable.  
**Error handling gaps:** guards around pressure-domain transforms appear stronger than earlier audits implied.  
**Cross-module contract issues:** none new.  
**Hidden dependencies:** depends on stable pressure channel naming and plugin pipeline timing.  
**Safety blind spots:** no new production-risk issue found beyond prior numerical caveats already documented elsewhere.  
**Overall severity:** `MINOR`

### Module: src/cryodaq/core/sensor_diagnostics.py

**LoC:** 450  
**Purpose:** classify sensor health and derived diagnostic states.  
**Test coverage:** direct tests exist.  
**Round 1 status:** skim.

**Invariant violations:** none found in this pass.  
**Concurrency correctness issues:** none obvious.  
**Error handling gaps:** substantial defensive checks are already present.  
**Cross-module contract issues:** none new.  
**Hidden dependencies:** relies on channel naming and history availability.  
**Safety blind spots:** no new issue strong enough to promote above round 1/earlier diagnostics findings.  
**Overall severity:** `MINOR`

### Module: src/cryodaq/analytics/plugin_loader.py

**LoC:** 362  
**Purpose:** in-process plugin loading, batching, execution, and hot reload.  
**Test coverage:** partial direct tests.  
**Round 1 status:** skim.

**Invariant violations:** none.  
**Concurrency correctness issues:** plugins execute serially in the main analytics loop and can block it indefinitely; there is no timeout boundary around `await plugin.process(batch)` (`src/cryodaq/analytics/plugin_loader.py:263-287`).  
**Error handling gaps:** plugin exceptions are contained, but import-time and config-time failures are only logged; malformed YAML sidecars do not stop load attempts.  
**Cross-module contract issues:** hot reload is unload-then-load, creating a window of unavailability (`src/cryodaq/analytics/plugin_loader.py:311-321`).  
**Hidden dependencies:** plugin code is fully trusted, in-process, and unsandboxed.  
**Safety blind spots:** a hung or malicious plugin still blocks analytics publication for the whole pipeline.  
**Overall severity:** `MEDIUM`

### Module: src/cryodaq/drivers/transport/gpib.py

**LoC:** 359  
**Purpose:** VISA-backed GPIB transport with single-worker executor.  
**Test coverage:** direct transport tests exist.  
**Round 1 status:** skim.

**Invariant violations:** none new.  
**Concurrency correctness issues:** no regression from Phase 2d found; the single-worker executor model remains the same known limitation.  
**Error handling gaps:** hung VISA calls remain unkillable from outer cancellation, but this was a known pre-round-2 issue rather than a newly introduced semantic regression.  
**Cross-module contract issues:** none new.  
**Hidden dependencies:** backend VISA semantics.  
**Safety blind spots:** repeated disconnect/reconnect remains operationally painful but not newly broken in master.  
**Overall severity:** `MINOR`

### Module: src/cryodaq/drivers/transport/serial.py

**LoC:** 203  
**Purpose:** async serial transport for RS-232 instruments.  
**Test coverage:** partial indirect coverage.  
**Round 1 status:** skim.

**Invariant violations:** none new.  
**Concurrency correctness issues:** no new round 2 regression found; prior audit already documented write/query serialization limitations.  
**Error handling gaps:** still relatively permissive at the transport boundary, but unchanged.  
**Cross-module contract issues:** none new.  
**Hidden dependencies:** pyserial/OS serial adapter behavior.  
**Safety blind spots:** same as prior driver-layer audit; no new master-specific issue.  
**Overall severity:** `MINOR`

### Module: src/cryodaq/drivers/transport/usbtmc.py

**LoC:** 261  
**Purpose:** VISA-backed USB-TMC transport for Keithley.  
**Test coverage:** direct executor tests exist.  
**Round 1 status:** skim.

**Invariant violations:** none new.  
**Concurrency correctness issues:** executor cancellation limitations remain but no new regression found.  
**Error handling gaps:** same practical limitation as GPIB transport.  
**Cross-module contract issues:** none new.  
**Hidden dependencies:** VISA backend and OS USB-TMC behavior.  
**Safety blind spots:** no new issue from round 2.  
**Overall severity:** `MINOR`

### Module: src/cryodaq/notifications/telegram.py

**LoC:** 236  
**Purpose:** Telegram bot transport and message delivery.  
**Test coverage:** direct tests exist.  
**Round 1 status:** skim.

**Invariant violations:** none.  
**Concurrency correctness issues:** reconnect/update loop appears bounded and explicit.  
**Error handling gaps:** nothing new stronger than prior operational notes.  
**Cross-module contract issues:** none new in this pass.  
**Hidden dependencies:** network/API availability.  
**Safety blind spots:** no new security or correctness issue from local code review.  
**Overall severity:** `CLEAN`

### Module: src/cryodaq/notifications/escalation.py

**LoC:** 110  
**Purpose:** delayed escalation of unacknowledged alarm/fault conditions.  
**Test coverage:** direct coverage is weak or indirect.  
**Round 1 status:** skim.

**Invariant violations:** none.  
**Concurrency correctness issues:** timer-based escalation is lightweight, but direct dedicated tests for restart/duplicate-event behavior are not obvious.  
**Error handling gaps:** no major runtime bug proven in this pass.  
**Cross-module contract issues:** depends on alarm lifecycle guarantees from other modules.  
**Hidden dependencies:** event ordering and acknowledgment semantics.  
**Safety blind spots:** under-tested for a safety-adjacent timed workflow.  
**Overall severity:** `MINOR`

### Module: src/cryodaq/notifications/periodic_report.py

**LoC:** 503  
**Purpose:** schedule and send periodic summary reports.  
**Test coverage:** direct tests are not obvious.  
**Round 1 status:** not covered.

**Invariant violations:** none.  
**Concurrency correctness issues:** larger async surface than its test footprint suggests, but no concrete new bug proven here.  
**Error handling gaps:** subsystem is permissive and best-effort, which is acceptable for notifications but worth noting.  
**Cross-module contract issues:** depends on report generation and message transport without tight end-to-end guarantees.  
**Hidden dependencies:** filesystem/reporting/Telegram.  
**Safety blind spots:** operationally useful but not central to safety; the main issue is sparse semantic test coverage.  
**Overall severity:** `MINOR`

### Module: src/cryodaq/notifications/telegram_commands.py

**LoC:** 464  
**Purpose:** parse Telegram commands and route them into engine actions.  
**Test coverage:** direct tests exist.  
**Round 1 status:** skim.

**Invariant violations:** none found.  
**Concurrency correctness issues:** none new.  
**Error handling gaps:** command parsing and allowlist handling remain explicit.  
**Cross-module contract issues:** command handler still forms the main authz boundary to experiment-control operations.  
**Hidden dependencies:** relies on upstream command handler semantics.  
**Safety blind spots:** no bypass path found in this pass.  
**Overall severity:** `CLEAN`

### Module: src/cryodaq/reporting/generator.py

**LoC:** 224  
**Purpose:** assemble DOCX report and optionally convert to PDF.  
**Test coverage:** direct tests exist.  
**Round 1 status:** skim.

**Invariant violations:** none.  
**Concurrency correctness issues:** `_try_convert_pdf()` uses blocking `subprocess.run()` (`src/cryodaq/reporting/generator.py:207-224`). This remains safe only if called off the engine loop; if any future async path calls it inline, it will stall hard.  
**Error handling gaps:** conversion failure is best-effort and silent except through missing output artifact.  
**Cross-module contract issues:** still ties experiment finalization to a synchronous external office tool.  
**Hidden dependencies:** `soffice`/`libreoffice` availability.  
**Safety blind spots:** not a direct safety bug, but still a long-tail finalize robustness issue.  
**Overall severity:** `MEDIUM`

### Module: src/cryodaq/reporting/data.py

**LoC:** 200  
**Purpose:** collect experiment/report data from storage and metadata.  
**Test coverage:** direct tests exist via report generation.  
**Round 1 status:** skim.

**Invariant violations:** none found in this pass.  
**Concurrency correctness issues:** none meaningful.  
**Error handling gaps:** no new issue stronger than prior reporting audit results.  
**Cross-module contract issues:** still depends on experiment metadata and operator-log integrity.  
**Hidden dependencies:** storage schema.  
**Safety blind spots:** none new.  
**Overall severity:** `MINOR`

### Module: src/cryodaq/reporting/sections.py

**LoC:** 714  
**Purpose:** build individual report sections from assembled data.  
**Test coverage:** direct tests exist via report generator and experiment/report tests.  
**Round 1 status:** skim.

**Invariant violations:** none found in this pass.  
**Concurrency correctness issues:** none.  
**Error handling gaps:** still a large surface where one broken renderer can affect the whole report pipeline, but that was already captured in earlier reporting audits.  
**Cross-module contract issues:** depends on section registry and data-shape stability.  
**Hidden dependencies:** matplotlib/docx/report data contracts.  
**Safety blind spots:** reporting remains best-effort rather than transactionally isolated.  
**Overall severity:** `MINOR`

### Module: src/cryodaq/tools/cooldown_cli.py

**LoC:** 252  
**Purpose:** offline CLI around cooldown analytics.  
**Test coverage:** no obvious direct tests.  
**Round 1 status:** not covered.

**Invariant violations:** none.  
**Concurrency correctness issues:** CLI path, not engine-loop critical.  
**Error handling gaps:** ordinary CLI ergonomics only.  
**Cross-module contract issues:** mirrors analytics assumptions and may lag runtime behavior.  
**Hidden dependencies:** filesystem/model assets.  
**Safety blind spots:** low production risk because it is offline tooling.  
**Overall severity:** `LOW`

### Module: src/cryodaq/_frozen_main.py

**LoC:** 99  
**Purpose:** frozen PyInstaller entry point.  
**Test coverage:** direct tests exist.  
**Round 1 status:** skim.

**Invariant violations:** none found.  
**Concurrency correctness issues:** none.  
**Error handling gaps:** startup routing looks explicit and adequately defended.  
**Cross-module contract issues:** uses path/bootstrap helpers consistently with current packaging model.  
**Hidden dependencies:** frozen path conventions only.  
**Safety blind spots:** no new PyInstaller regression found in this pass.  
**Overall severity:** `CLEAN`

## Test file semantic review

### Tautological assertions

No obvious `assert True`, `assert 1 == ...`, or equivalent tautologies surfaced in the spot checks.

### Unbounded timing waits

| File:line | Wait type | Concern |
|---|---|---|
| `tests/core/test_scheduler.py:237` | `await asyncio.sleep(0.05)` | Timing-based drain test already has stale API debt; short sleep may hide races rather than prove shutdown semantics. |
| `tests/core/test_safety_manager.py` multiple | `await asyncio.sleep(...)` | Several safety tests still rely on real time progression instead of explicit clock control. |
| `tests/core/test_housekeeping.py` multiple | `await asyncio.sleep(...)` | Throttle/retention timing behavior remains time-sensitive and can false-green under load variance. |
| `tests/drivers/test_visa_executors.py` multiple | `time.sleep(...)` / structural timing | Hardware executor semantics still tested partly by source structure rather than pure behavior. |

### Wide exception swallowing

No broad `except Exception: pass` pattern stood out in the initial grep set. This is better than average for a suite of this size.

### Structural-only tests (potential false greens)

| File:line | Pattern | Recommendation |
|---|---|---|
| `tests/core/test_experiment.py:443-459` | reads source text to assert atomic-write / WAL strings exist | Replace with behavioral tests that exercise sidecar writing and WAL verification paths. |
| `tests/core/test_safety_manager.py:633-640` | source-text shield assertion | Keep one structural smoke test if needed, but add behavioral cancellation tests as primary guard. |
| `tests/drivers/test_visa_executors.py` multiple | `inspect.getsource(...)` checks | Useful as regression tripwires, but insufficient for proving runtime cancellation/serialization behavior. |
| `tests/core/test_zmq_subprocess.py` / `tests/core/test_zmq_safety.py` | source-inspection patterns | Prefer behavioral lifecycle tests over text checks. |

### Stale API references

| File:line | Reference | Fix |
|---|---|---|
| `tests/core/test_scheduler.py:231` | `sched._DRAIN_TIMEOUT_S = 0.1` | Update to the instance field introduced by Phase 2d (`_drain_timeout_s`). |
| `tests/core/test_calibration_acquisition.py:57-180` and onward | deprecated `on_readings(...)` still dominates tests | Migrate main coverage to `prepare_srdg_readings()` + `on_srdg_persisted()` split so contract regressions surface earlier. |

### Overall test health

The suite is not obviously fake-green, but it still contains too many structural assertions on source text and too much reliance on deprecated compatibility shims in exactly the areas Phase 2d changed semantically. The strongest actionable gap is not raw test count; it is that some of the most important new contracts still are not tested in their production form.

## Cross-module contract verification

### Contract 1: `CalibrationAcquisitionService.prepare_srdg_readings()`

**Callers:** production caller is `Scheduler`; deprecated shim calls it internally; tests call it directly.  
**Status:** production callers updated correctly.  
**Issues:** the production path is correct, but the engine does not normalize `reference_channel` / `target_channels` into runtime labels before activation, so the correctness contract now depends on caller-supplied strings matching `Reading.channel` exactly.

### Contract 2: `CalibrationAcquisitionService.on_srdg_persisted()`

**Callers:** production caller is `Scheduler`; deprecated shim calls it internally; tests call it directly.  
**Status:** all known callers updated.  
**Issues:** no stale production caller found.

### Contract 3: `ChannelManager.load()` now raising `ChannelConfigError`

**Callers:** engine startup path via channel-manager initialization.  
**Status:** updated.  
**Issues:** no production leak of `_DEFAULT_CHANNELS` fallback found; stale concern is mostly test coverage.

### Contract 4: `load_housekeeping_config()` raising `HousekeepingConfigError`

**Callers:** engine startup and housekeeping internals.  
**Status:** updated.  
**Issues:** typed fail-closed behavior is wired in `engine.py`; no silent startup fallback path found.

### Contract 5: `load_interlock_config()` raising `InterlockConfigError`

**Callers:** engine startup and interlock setup.  
**Status:** updated.  
**Issues:** fail-closed path is wired and looks genuinely closed.

### Contract 6: `SafetyConfig.scheduler_drain_timeout_s`

**Callers:** `Scheduler.stop()` consumes the instance drain timeout.  
**Status:** production wiring updated.  
**Issues:** stale test still references the removed `_DRAIN_TIMEOUT_S` constant.

### Contract 7: `Scheduler.stop()` instance timeout vs removed class constant

**Callers:** production code updated; tests partially stale.  
**Status:** production clean / test debt remains.  
**Issues:** `tests/core/test_scheduler.py:231`.

### Contract 8: `AlarmStateManager.acknowledge()`

**Callers:** engine command handler and tests.  
**Status:** no stale production caller found.  
**Issues:** none new in round 2.

### Contract 9: `_fault()` ordering after Jules R2

**Callers affected:** downstream consumers of fault event publication and callbacks.  
**Status:** no conflicting production caller assumption surfaced in round 2.  
**Issues:** none found from caller audit; keep behavioral tests as the main guard.

### Contract 10: deprecated `on_readings` shim

**Callers:** compatibility path and tests.  
**Status:** no production callers found; tests still rely on it heavily.  
**Issues:** this is now mostly a test migration problem rather than a runtime one.

## Git blame analysis

### `src/cryodaq/core/safety_manager.py`

- **Unique contributing commits:** 22  
- **Largest surviving line blocks:** `fix: Phase 1 pre-deployment — unblock PyInstaller build` (203 lines), `Safety architecture: SafetyManager, SafetyBroker, fail-on-silence` (200), `Add backend workflows...` (173), `fix: Phase 2a safety hardening` (106), `phase-2d-a1` (51)  
- **Observation:** this file has a stable older core plus layered hardening patches; Phase 2d extended an already central design rather than replacing it.

### `src/cryodaq/core/scheduler.py`

- **Unique contributing commits:** 17  
- **Largest surviving line blocks:** `refactor: GPIB sequential polling` (149), `Add SQLiteWriter...Scheduler` (143), `phase-2d-b2: persistence integrity` (46), `fix(gpib)...` (44)  
- **Observation:** scheduler semantics are concentrated in a small number of commits, so regressions here are more likely to be introduced by sequencing changes than by diffuse history.

### `src/cryodaq/core/experiment.py`

- **Unique contributing commits:** 10  
- **Largest surviving line blocks:** `fix: finalize RC...` (980), `Add backend workflows...` (456), `Experiment lifecycle...` (133), `phase-2e-parquet-1` (23)  
- **Observation:** finalize/report/archive behavior is dominated by one large late refactor, with the Parquet addition landing as a small add-on rather than a redesign.

### `src/cryodaq/storage/sqlite_writer.py`

- **Unique contributing commits:** 18  
- **Largest surviving line blocks:** `Add backend workflows...` (182), `Add SQLiteWriter...Scheduler` (171), `fix: Phase 2a safety hardening` (110), `fix: empty plots after GUI reconnect...` (95)  
- **Observation:** the writer still carries older broad functionality with hardening layered on top; it was touched heavily in 2d but still reflects multiple historical responsibilities.

### `src/cryodaq/engine.py`

- **Unique contributing commits:** 46  
- **Largest surviving line blocks:** `Add backend workflows...` (337), `Engine + GUI: entry points...` (242), `Fix engine startup calibration store initialization...` (203), `feat: alarm v2 integration...` (102)  
- **Observation:** `engine.py` remains the highest-risk integration hub. Phase 2d touched it often, but round 2’s new calibration custom-field mismatch is exactly the kind of hub-level contract gap that blame analysis would predict.

### Phase 2d touch pattern

Phase 2d heavily touched `safety_manager.py`, `scheduler.py`, `sqlite_writer.py`, `experiment.py`, and `engine.py`. It did **not** materially normalize secondary time-sensitive modules such as `alarm_providers.py`, which is why wall-clock sensitivity still leaks there even after the main safety path was hardened.

## Round 2 consolidated findings

### New findings not in round 1

1. **MEDIUM — Calibration channel identity is not canonicalized before activation.**  
   `src/cryodaq/engine.py:370-375`, `src/cryodaq/core/calibration_acquisition.py:92-108`  
   Engine passes raw `custom_fields` strings into calibration acquisition, while the service expects exact runtime `Reading.channel` equality.

2. **MEDIUM — Phase-duration alarm provider still depends on wall clock.**  
   `src/cryodaq/core/alarm_providers.py:42-64`  
   Phase elapsed time can jump under NTP corrections even though the main safety path has stronger timing discipline.

3. **LOW — ZMQ bind retry still blocks the event loop during startup retries.**  
   `src/cryodaq/core/zmq_bridge.py:39-74`  
   `time.sleep()` remains in the retry helper.

4. **LOW — Critical scheduler drain test still uses removed API.**  
   `tests/core/test_scheduler.py:231`  
   This weakens confidence in one shutdown regression guard.

5. **LOW — Calibration tests still overuse deprecated compatibility shim.**  
   `tests/core/test_calibration_acquisition.py`  
   Production split API is underrepresented in tests.

### Round 1 findings confirmed by round 2

1. **Round 1 B.1 / `P2`** — `DataBroker` subscriber exception isolation is still open and real.  
2. **Round 1 I.3** — wall-clock sensitivity remains in `channel_state.py` and is now additionally confirmed in `alarm_providers.py`.  
3. **Round 1 F.1** — Parquet exporter is sound, but artifact metadata still lags exported files.  
4. **Round 1 reporting robustness** — `reporting/generator.py` still uses blocking LibreOffice conversion.  
5. **Round 1 plugin trust boundary** — `plugin_loader.py` is still in-process, unsandboxed, serial, and timeout-free.

### Round 1 findings refuted by round 2

1. **Round 1 calibration throttle BLOCKING verdict** — refuted in its broad production form.  
   The shipped config already protects the usual `Т1` through `Т12` reference-channel cases. The residual issue is narrower and should be downgraded from `BLOCKING` to `MEDIUM` unless future config/templates intentionally use unprotected throttled channels as calibration references.

## Updated verdict

`SIGNIFICANT_ISSUES`

Round 2 does not support keeping the blanket `BLOCKING` verdict from round 1. The strongest new evidence refutes the main broad regression scenario that drove that status. Master still has real semantic seams to close, but they are now narrower:

- calibration channel normalization and explicit reference protection
- `DataBroker` exception isolation
- wall-clock cleanup in secondary alarm/analytics logic
- a handful of stale tests on the exact contracts Phase 2d changed

That is serious enough to keep master out of a “clean closure” status, but not serious enough to claim round 2 found a new deployment-blocking break in the common production path.

## Things I was uncertain about

1. The practical severity of the residual calibration/throttle issue depends on whether calibration templates or operator workflow ever select `Т13` through `Т20` as reference channels. The code does not prevent it, but I did not find a shipped template using that path.
2. I did not re-run the full suite, so the judgment about stale tests is based on static review rather than observed false-green behavior.
3. Notification modules such as `periodic_report.py` and `escalation.py` have relatively weak direct semantic coverage. I did not prove a bug there, but confidence is lower than in the core path.

## Confidence ratings

- **Regression verification:** `HIGH` — this was traced directly through scheduler, throttle, calibration service, engine wiring, and production YAML.
- **Secondary module deep review:** `MEDIUM` — the file review is real and broad, but some modules were summarized because no substantive new issue was found.
- **Test file review:** `MEDIUM` — strong enough to identify stale and structural tests, but not a full audit of all 113 test files.
- **Cross-module contract verification:** `HIGH` — the changed Phase 2d APIs were traced to their current callers.
- **Git blame analysis:** `MEDIUM` — useful for context and missed-file detection, but intentionally shallow compared with the semantic code review.
