# CryoDAQ Hardening Pass — Codex (overnight, Mode 2-5)

**Commit:** 1698150  
**Date:** 2026-04-09  
**Agent:** Codex CLI (gpt-5.4 high reasoning)  
**Runtime:** ~3h  
**Previous audit:** `DEEP_AUDIT_CODEX_POST_2C.md` (commit `fd99631`) — DO NOT DUPLICATE  
**Modes used:** 2 (hypothesis verification), 3 (scenario stress testing), 4 (cross-module interaction), 5 (incident matching)  
**Counter-claims tested:** 16  
**Scenarios traced end-to-end:** 10  
**Cross-module interactions analyzed:** 8  
**Incident patterns checked:** 10  
**Web lookups performed:** 115 searches, 24 fetches  
**New findings (not in previous audit):** 0 CRITICAL, 5 HIGH, 4 MEDIUM, 1 LOW, 12 OK

## Methodology notes

This pass was deliberately different from the prior inventory audit. I started by re-reading `CLAUDE.md` and my own previous report to avoid reheating already-known findings, then switched to system claims, failure scenarios, and boundary contracts. The highest-yield areas were:

- `Scheduler -> DataBroker -> alarm_v2 / analytics` because the persistence-first and adaptive-throttle design is correct locally but changes semantics across consumers.
- `SafetyManager -> ExperimentManager` because the codebase has strong local safety behavior but weak experiment-provenance coupling.
- `Telegram/Web` because trusted-operator input is treated as harmless in some places and as HTML in others.
- Timebase handling across `SafetyManager`, `alarm_v2`, `CooldownService`, and `VacuumTrendPredictor`.

This pass is still below the requested 4-8h wall-clock target. Rather than pad, I focused on proving or disproving the most operationally dangerous hypotheses and I list remaining gaps honestly at the end.

## Mode 2: Hypothesis-driven verification

### H.1: Persistence-first has a hidden publish-before-write path

**Origin:** `CLAUDE.md` claim: SQLite write happens before broker publish.  
**Counter-claim:** There exists a path where readings hit `DataBroker` before `SQLiteWriter.write_immediate()`.  
**Investigation:** Read `src/cryodaq/core/scheduler.py:311-377` and `src/cryodaq/storage/sqlite_writer.py:525-540`.  
**Evidence:**

```python
# src/cryodaq/core/scheduler.py
if self._sqlite_writer is not None and persisted_readings:
    await self._sqlite_writer.write_immediate(persisted_readings)
...
if persisted_readings:
    await self._broker.publish_batch(persisted_readings)
if self._safety_broker is not None:
    await self._safety_broker.publish_batch(readings)
```

**Web research:**
- https://github.com/python/cpython/issues/107505 — confirms cancelled executor work can keep running, relevant to the prior pass's timeout issue, but not to write-before-publish ordering.

**Verdict:** **DISPROVEN.** For the ordinary archive/live path, publish follows `write_immediate()`. The separate `SafetyBroker` path intentionally receives the full batch after the archive path is handled.

---

### H.2: Something outside `SafetyManager` can still turn the Keithley output on/off

**Origin:** `CLAUDE.md` claim: `SafetyManager` is the single authority for source enable/disable.  
**Counter-claim:** At least one non-safety path can directly issue on/off commands.  
**Investigation:** Traced `engine.py`, `gui/widgets/keithley_panel.py`, `core/safety_manager.py`, and repo-wide searches for `keithley_start`, `keithley_stop`, `emergency_off`, `output_on`, `output_off`.  
**Evidence:**

```python
# src/cryodaq/gui/widgets/keithley_panel.py
worker = ZmqCommandWorker({"cmd": "keithley_emergency_off", "channel": self._smu})

# src/cryodaq/engine.py
if action == "keithley_start":
    return await _run_keithley_command("start", cmd, safety_manager)

# src/cryodaq/core/safety_manager.py
await self._keithley.start_source(smu_channel, p_target, v_comp, i_comp)
await self._keithley.stop_source(smu_channel)
await self._keithley.emergency_off()
```

**Web research:**
- https://doc.qt.io/qt-6.9/threads-modules.html — relevant for GUI command threading, not for authority.

**Verdict:** **DISPROVEN.** Enable/disable still routes through `SafetyManager`. I did re-confirm one internal abstraction leak: `update_limits()` writes directly to `self._keithley._transport.write(...)` in `src/cryodaq/core/safety_manager.py:377-393`, but that stays inside the safety boundary and does not violate the authority claim.

---

### H.3: The GUI still assumes Keithley state changes succeeded before the engine confirms them

**Origin:** `CLAUDE.md` claim: GUI is not the source of truth.  
**Counter-claim:** GUI flips its state optimistically on button press.  
**Investigation:** Read `src/cryodaq/gui/widgets/keithley_panel.py:254-380`.  
**Evidence:**

```python
def apply_channel_state(self, state: str) -> None:
    self._channel_state = state.lower()
...
def _on_start_result(self, result: dict, emit_feedback: bool) -> None:
    self._start_btn.setEnabled(self._channel_state != "on")
    ...
    self._show_info("Команда запуска ... отправлена. Дождитесь подтверждения состояния.")
```

**Web research:**
- https://doc.qt.io/qt-6.9/threads-modules.html — “We recommend using signals and slots to pass data between threads...” Relevant because the panel waits for backend-confirmed state updates rather than mutating shared hardware state itself.

**Verdict:** **DISPROVEN.** The panel disables buttons while the request is outstanding, but it does not mark the channel `on` locally. The actual state comes back through backend-driven readings and `apply_channel_state()`.

---

### H.4: The adaptive-throttle runtime-signal path is dead code

**Origin:** `CLAUDE.md` claim: adaptive throttle is gated by live safety/Keithley/alarm signals.  
**Counter-claim:** The runtime-signal observer exists but is never fed.  
**Investigation:** Read `src/cryodaq/engine.py:1007-1013` and `src/cryodaq/core/housekeeping.py:238-249`.  
**Evidence:**

```python
# src/cryodaq/engine.py
queue = await broker.subscribe("adaptive_throttle_runtime", maxsize=2000)
while True:
    adaptive_throttle.observe_runtime_signal(await queue.get())

# src/cryodaq/core/housekeeping.py
if channel == "analytics/alarm_count":
    self._active_alarm_count = max(0, int(round(reading.value)))
...
if channel == "analytics/safety_state":
    if state != "running":
        self._transition_until = reading.timestamp + timedelta(seconds=self._transition_holdoff_s)
```

**Web research:**
- https://docs.python.org/tr/3.13/library/time.html — used for monotonic-time reasoning elsewhere in this pass.

**Verdict:** **DISPROVEN.** The hook is live.

---

### H.5: Adaptive throttle cannot distort `alarm_v2` stale/rate semantics

**Origin:** Project claim implied by “protected channels” and runtime-signal wiring.  
**Counter-claim:** At least one `alarm_v2` path consumes intentionally thinned data and can alarm on the thinning itself.  
**Investigation:** Read `src/cryodaq/core/scheduler.py:331-377`, `src/cryodaq/engine.py:1015-1027`, `src/cryodaq/core/housekeeping.py:216-307`, and `config/alarms_v3.yaml:128-149`.  
**Evidence:**

```python
# src/cryodaq/core/scheduler.py
persisted_readings = self._adaptive_throttle.filter_for_archive(readings)
...
await self._broker.publish_batch(persisted_readings)

# src/cryodaq/engine.py
queue = await broker.subscribe("alarm_v2_state_feed", maxsize=2000)
...
_alarm_v2_state_tracker.update(reading)

# config/alarms_v3.yaml
data_stale_temperature:
  alarm_type: stale
  timeout_s: 30
  level: WARNING
```

```python
# src/cryodaq/core/housekeeping.py
self._stable_duration_s = float(cfg.get("stable_duration_s", 120.0))
self._max_interval_s = float(cfg.get("max_interval_s", 30.0))
...
if since_emit >= self._max_interval_s:
    return True
return False
```

**Web research:**
- https://docs.python.org/tr/3.13/library/time.html — Python documents `time.monotonic()` as “a clock that cannot go backwards”; relevant because `alarm_v2` does **not** use monotonic time here.
- https://sqlite.org/wal.html — consulted for scenario work, not directly causal here.

**Verdict:** **PROVEN.**

**If proven — finding details:**  
`H.5 [HIGH] Adaptive throttle can self-trigger 30s warning stale alarms`  
**Location:** `src/cryodaq/core/scheduler.py:331-377`, `src/cryodaq/engine.py:1015-1027`, `src/cryodaq/core/housekeeping.py:223-307`, `config/alarms_v3.yaml:128-133`  
**Impact:** A stable temperature channel can be intentionally emitted only every 30s while the warning stale alarm also trips at 30s. That makes `alarm_v2` vulnerable to false “Нет данных > 30с” warnings during normal throttled operation, eroding operator trust precisely in the alarm tier that should surface early data-path degradation.  
**Proposed fix:** Do not feed `alarm_v2` from the throttled `DataBroker`. Either feed it from the full `SafetyBroker`, or introduce a separate full-rate `alarm_broker` path. At minimum, make stale-warning thresholds strictly larger than adaptive-throttle `max_interval_s` with margin.

---

### H.6: Safety faults automatically update experiment lifecycle state

**Origin:** Architectural expectation in a safety-critical experiment system.  
**Counter-claim:** `FAULT_LATCHED` does not notify `ExperimentManager` at all.  
**Investigation:** Searched for `SafetyManager.on_state_change(...)` registrations and traced experiment mutations in `src/cryodaq/core/experiment.py` plus command handling in `src/cryodaq/engine.py`.  
**Evidence:**

```python
# src/cryodaq/core/safety_manager.py
def on_state_change(self, callback: Callable[[SafetyState, SafetyState, str], Any]) -> None:
    self._on_state_change.append(callback)

# src/cryodaq/core/experiment.py
def finalize_experiment(...):
    ...
def abort_experiment(...):
    return self.finalize_experiment(...)
```

Repo-wide search found no call site registering `on_state_change(...)`.

**Web research:**
- https://docs.python.org/tr/3.13/library/time.html — used for fault-duration timing analysis.

**Verdict:** **PROVEN.**

**If proven — finding details:**  
`H.6 [HIGH] Safety faults do not propagate into experiment lifecycle or metadata`  
**Location:** `src/cryodaq/core/safety_manager.py:447-533`, `src/cryodaq/core/experiment.py:682-770`, `src/cryodaq/engine.py:1177-1220`  
**Impact:** A fault-latched experiment can continue to appear “active/running” in metadata for hours, even though Keithley output is already forced off. That breaks experiment provenance, confuses morning handoff, and leaves reports/journal data without an authoritative fault boundary unless an operator remembers to add one manually.  
**Proposed fix:** Register an engine-level safety-state callback that writes a fault marker into the operator journal and, for active experiments, records a machine-generated experiment event with fault reason/time. Decide explicitly whether certain fault classes should auto-abort, auto-stop, or keep the experiment open in a “faulted” substate.

---

### H.7: Engine restart loses the active experiment card completely

**Origin:** Fresh-engine recovery claim implied by the architecture.  
**Counter-claim:** Engine restart always comes back “blank” and forgets the active experiment.  
**Investigation:** Read `src/cryodaq/core/experiment.py:856-909`.  
**Evidence:**

```python
def _load_state(self) -> None:
    ...
    if active_experiment_id:
        active = self._read_experiment_from_metadata(active_experiment_id)
        if active is not None and active.status is ExperimentStatus.RUNNING:
            self._active = active
        else:
            self._clear_active()
```

**Web research:**
- https://pyinstaller.org/en/v3.2/runtime-information.html — relevant to frozen-path recovery, not to experiment metadata itself.

**Verdict:** **DISPROVEN.** The new engine instance will restore an active experiment from `experiment_state.json` plus metadata if the status was still `RUNNING`.

---

### H.8: Two simultaneous experiment starts can race each other

**Origin:** Scenario requirement from the prompt.  
**Counter-claim:** Two clients can concurrently enter `ExperimentManager.create_experiment()` and both win.  
**Investigation:** Read `src/cryodaq/core/zmq_bridge.py:282-343`, `src/cryodaq/core/experiment.py:557-608`.  
**Evidence:**

```python
# src/cryodaq/core/zmq_bridge.py
raw = await asyncio.wait_for(self._socket.recv(), timeout=1.0)
...
result = self._handler(cmd)
if asyncio.iscoroutine(result):
    result = await result
await self._socket.send(json.dumps(reply, default=str).encode())
```

```python
# src/cryodaq/core/experiment.py
if self._active is not None:
    raise RuntimeError("... already active.")
```

**Web research:**
- https://pyzmq.readthedocs.io/en/v25.1.2/api/zmq.html — REP socket semantics and close behavior consulted.

**Verdict:** **DISPROVEN.** The REP server processes one request to completion before receiving the next, so the start commands are serialized before they reach `ExperimentManager`.

---

### H.9: Runtime calibration policy can change inside one LakeShore poll batch

**Origin:** Scenario requirement from the prompt.  
**Counter-claim:** A calibration apply races with `read_channels()` and splits a single batch across old and new policies.  
**Investigation:** Read `src/cryodaq/drivers/instruments/lakeshore_218s.py:452-545` and engine calibration command dispatch in `src/cryodaq/engine.py:1256-1275`.  
**Evidence:**

```python
# lakeshore_218s.py
policies = self._runtime_channel_policies(active_channels)
...
merged.extend(self._merge_runtime_readings(krdg, srdg, policies))
```

**Web research:**
- https://docs.python.org/tr/3.13/library/time.html — used for timebase reasoning only.

**Verdict:** **DISPROVEN.** Policy lookup is performed once per `read_channels()` call, so a runtime change takes effect on the next poll, not mid-batch.

---

### H.10: Calibration acquisition preserves KRDG and SRDG atomically for each poll

**Origin:** Calibration-run integrity expectation.  
**Counter-claim:** A poll can persist main KRDG values and lose the matching SRDG companion points.  
**Investigation:** Read `src/cryodaq/core/scheduler.py:338-366` and `src/cryodaq/core/calibration_acquisition.py:71-122`.  
**Evidence:**

```python
# src/cryodaq/core/scheduler.py
await self._sqlite_writer.write_immediate(persisted_readings)
...
srdg = await driver.read_srdg_channels()
await self._calibration_acquisition.on_readings(readings, srdg)

# src/cryodaq/core/calibration_acquisition.py
if to_write:
    await self._writer.write_immediate(to_write)
```

**Web research:**
- https://sqlite.org/wal.html — WAL protects commit atomicity, but only per transaction; separate commits remain separate failure boundaries.

**Verdict:** **PROVEN.**

**If proven — finding details:**  
`H.10 [HIGH] Calibration poll cycles are not atomically persisted`  
**Location:** `src/cryodaq/core/scheduler.py:338-366`, `src/cryodaq/core/calibration_acquisition.py:95-122`  
**Impact:** A crash or forced shutdown between the main reading commit and the SRDG write leaves an apparently valid calibration experiment with missing raw partner points for some cycles. That is silent calibration-data loss, not just a cosmetic mismatch.  
**Proposed fix:** Treat one calibration poll cycle as one persistence unit. Either write KRDG+SRDG together in a single transaction, or persist an explicit cycle id and completeness marker so downstream tooling can detect and reject incomplete pairs.

---

### H.11: Cooldown analytics are monotonic end-to-end

**Origin:** Internal comments in `CooldownDetector.update()` say `ts` is monotonic.  
**Counter-claim:** The live pipeline feeds wall-clock timestamps and later mixes them with `time.time()`.  
**Investigation:** Read `src/cryodaq/analytics/cooldown_service.py:96-161`, `src/cryodaq/analytics/cooldown_service.py:286-384`.  
**Evidence:**

```python
# src/cryodaq/analytics/cooldown_service.py
def update(self, ts: float, T_cold: float) -> CooldownPhase:
    """ts: монотонное время (time.monotonic())"""

# same file, actual call site
reading_ts = reading.timestamp.timestamp()
self._detector.update(reading_ts, reading.value)
...
t_elapsed = (time.time() - self._cooldown_wall_start) / 3600.0
```

**Web research:**
- https://docs.python.org/tr/3.13/library/time.html — Python documents monotonic clocks as clocks that “cannot go backwards.”

**Verdict:** **PROVEN.**

**If proven — finding details:**  
`H.11 [HIGH] Cooldown predictor mixes wall-clock and pseudo-monotonic time`  
**Location:** `src/cryodaq/analytics/cooldown_service.py:96-161`, `src/cryodaq/analytics/cooldown_service.py:297-354`  
**Impact:** An NTP backward jump or manual clock correction can regress `t_elapsed`, break detector confirmation windows, and publish physically nonsensical ETAs during long cooldowns. This is exactly the class of overnight drift bug that no operator notices until the displayed forecast suddenly becomes implausible.  
**Proposed fix:** Use `time.monotonic()` consistently for detector state and elapsed-duration math. Keep wall-clock timestamps only as metadata for presentation, not for live state transitions or elapsed calculations.

---

### H.12: Vacuum trend prediction is robust to backward timestamps

**Origin:** General analytics expectation.  
**Counter-claim:** `VacuumTrendPredictor` assumes append order is chronological and does not sort or reject clock regressions.  
**Investigation:** Read `src/cryodaq/engine.py:1095-1112` and `src/cryodaq/analytics/vacuum_trend.py:125-153`.  
**Evidence:**

```python
# src/cryodaq/engine.py
vacuum_trend.push(reading.timestamp.timestamp(), reading.value)

# src/cryodaq/analytics/vacuum_trend.py
self._buffer.append((timestamp, log_p))
...
points = list(self._buffer)
t0 = points[0][0]
t_arr = np.array([t - t0 for t, _ in points])
```

**Web research:**
- https://docs.python.org/tr/3.13/library/time.html — relevant because the safe alternative is a monotonic timebase, not wall clock.

**Verdict:** **PROVEN.**

**If proven — finding details:**  
`H.12 [MEDIUM] VacuumTrendPredictor accepts backward timestamps and can fit nonsense`  
**Location:** `src/cryodaq/engine.py:1095-1112`, `src/cryodaq/analytics/vacuum_trend.py:125-153`  
**Impact:** A clock step backward produces non-monotonic `t_arr`, so model selection and ETA-to-target become unstable or wrong exactly when operators most want confidence in the vacuum trend.  
**Proposed fix:** Reject or reorder out-of-order points before fitting. Prefer a monotonic accumulation timebase for fitting and keep UTC timestamps separately for display only.

---

### H.13: Automatic event logging is durable enough for safety transitions

**Origin:** Implied by the system’s reliance on the operator journal for provenance.  
**Counter-claim:** Automatic events can disappear silently.  
**Investigation:** Read `src/cryodaq/core/event_logger.py:18-35`.  
**Evidence:**

```python
async def log_event(...):
    try:
        await self._writer.append_operator_log(...)
    except Exception:
        logger.warning("Failed to auto-log event: %s", message, exc_info=True)
```

**Web research:**
- https://sqlite.org/wal.html — consulted to distinguish DB atomicity from application-level “best effort” logging.

**Verdict:** **PROVEN.**

**If proven — finding details:**  
`H.13 [MEDIUM] Auto-generated experiment events are best-effort and can vanish silently`  
**Location:** `src/cryodaq/core/event_logger.py:18-35`  
**Impact:** Start/stop/phase events can disappear while the experiment otherwise continues, leaving a clean-looking but incomplete journal. In a safety-critical lab this weakens reconstruction after exactly the sort of overnight anomaly that later needs post-mortem review.  
**Proposed fix:** Treat system-generated lifecycle events as critical metadata, not optional convenience logging. Either propagate failures to the caller for operator visibility or persist them in a separate mandatory event table with retry/backpressure.

---

### H.14: Operator text rendered in the web dashboard is harmless

**Origin:** General web-monitor expectation.  
**Counter-claim:** Trusted-operator text flows into `innerHTML` without escaping.  
**Investigation:** Traced Telegram `/log` -> engine `log_entry` -> SQLite operator log -> `/api/log` -> dashboard DOM update.  
**Evidence:**

```python
# src/cryodaq/notifications/telegram_commands.py
result = await self._command_handler({
    "cmd": "log_entry",
    "message": text,
    "author": username,
    "source": "telegram",
})

# src/cryodaq/core/operator_log.py
"message": self.message,
```

```javascript
// src/cryodaq/web/server.py
html += `<div class="log-entry">... ${e.message||''}</div>`;
document.getElementById('log').innerHTML = html || 'Нет записей';
```

**Web research:**
- https://developer.mozilla.org/es/docs/Web/API/Element/innerHTML — MDN documents `innerHTML` as an HTML parser/sink, relevant to stored XSS if fed unescaped text.

**Verdict:** **PROVEN.**

**If proven — finding details:**  
`H.14 [HIGH] Stored XSS in web dashboard via operator log messages`  
**Location:** `src/cryodaq/notifications/telegram_commands.py:392-406`, `src/cryodaq/core/operator_log.py:30-38`, `src/cryodaq/web/server.py:497-503`  
**Impact:** Any allowed Telegram operator, or any GUI/web log-entry source, can store HTML/JS that executes in every browser opening the dashboard. The prior audit already established the dashboard is unauthenticated; this turns “monitoring only” into a browser compromise surface.  
**Proposed fix:** Render log text with `textContent`, not `innerHTML`, or HTML-escape on the server. Apply the same rule to author/source fields and review the rest of the dashboard template literals for raw insertion.

---

### H.15: GUI experiment-state refresh is non-blocking

**Origin:** The general “no blocking I/O on critical loops” expectation.  
**Counter-claim:** The experiment workspace performs a synchronous 5-second REQ/REP call on the GUI thread.  
**Investigation:** Read `src/cryodaq/gui/widgets/experiment_workspace.py:81-99` and `src/cryodaq/gui/zmq_client.py:148-167,238-242`.  
**Evidence:**

```python
# src/cryodaq/gui/widgets/experiment_workspace.py
def refresh_state(self) -> bool:
    result = send_command({"cmd": "experiment_status"})

# src/cryodaq/gui/zmq_client.py
def send_command(self, cmd: dict) -> dict:
    self._cmd_queue.put(cmd, timeout=2.0)
    return future.result(timeout=_CMD_REPLY_TIMEOUT_S)
```

**Web research:**
- https://doc.qt.io/qt-6.9/threads-modules.html — Qt recommends cross-thread data transfer via signals/slots; blocking the GUI thread on external work is the opposite of that model.

**Verdict:** **PROVEN.**

**If proven — finding details:**  
`H.15 [MEDIUM] Experiment workspace can freeze the GUI for up to 5s on engine trouble`  
**Location:** `src/cryodaq/gui/widgets/experiment_workspace.py:81-99`, `src/cryodaq/gui/zmq_client.py:148-167,238-242`  
**Impact:** During engine restart, port contention, or bridge trouble, opening or refreshing the experiment workspace can lock the whole GUI thread instead of degrading locally. That is not a hardware-safety failure by itself, but it materially worsens operator recovery during an incident.  
**Proposed fix:** Convert `refresh_state()` to `ZmqCommandWorker`/signal-based async flow like the newer panels. Keep synchronous `send_command()` off the UI thread.

---

### H.16: `stop_source` interlocks still collapse into full faults

**Origin:** Previous audit found this before Phase 2a; this pass re-checks the fix.  
**Counter-claim:** The code still routes both actions through the same fault path.  
**Investigation:** Read `src/cryodaq/engine.py:872-923` and `src/cryodaq/core/safety_manager.py:719-789`.  
**Evidence:**

```python
# src/cryodaq/core/safety_manager.py
if action == "emergency_off":
    await self._fault(...)
...
if action == "stop_source":
    ...
    self._transition(SafetyState.SAFE_OFF, f"Interlock stop_source: {interlock_name}", ...)
```

**Web research:**
- https://pyzmq.readthedocs.io/en/v25.1.2/api/zmq.html — consulted for command-path transport guarantees.

**Verdict:** **DISPROVEN.** The distinction is present now. This is a re-verification of a prior area, not a new finding.

## Mode 3: Scenario stress testing

### S.1: Power flicker mid-experiment

**Initial state:** Engine running, active experiment open, LakeShore polling through scheduler, SQLite WAL active, Keithley sourcing.  
**Event:** Brief 200 ms power flicker; host stays alive on UPS.  
**Trace step by step:**
1. T+0 ms: If the host remains alive, in-flight SQLite commits either complete or do not; `Scheduler._process_readings()` only publishes after `write_immediate()` returns (`src/cryodaq/core/scheduler.py:338-355`).
2. T+0-200 ms: A poll that was between main-write and calibration SRDG write can commit KRDG and lose its matching SRDG partner because those are separate writes (`src/cryodaq/core/scheduler.py:357-366`, `src/cryodaq/core/calibration_acquisition.py:120-122`).
3. T+200 ms: On the next scheduled poll, device-side errors surface through scheduler reconnect/backoff logic (`src/cryodaq/core/scheduler.py:127-168`, `178-309`).
4. T+1-10 s: If critical channels stop updating, SafetyManager stale checks are based on monotonic arrival time, not wall clock (`src/cryodaq/core/safety_manager.py:631-717`).
5. T+5 s: Experiment metadata is still “running”; no automatic fault/incident marker is injected into experiment lifecycle (`src/cryodaq/core/safety_manager.py:447-533`, `src/cryodaq/core/experiment.py:682-770`).

**Code references:** `src/cryodaq/core/scheduler.py:338-377`, `src/cryodaq/core/calibration_acquisition.py:71-122`, `src/cryodaq/core/safety_manager.py:631-717`

**Issues identified:**
- `H.10 [HIGH]` Calibration SRDG/KRDG cycle can be torn across a crash or power event.
- `H.6 [HIGH]` Fault/provenance boundary is not recorded in experiment lifecycle automatically.

**Verdict:** **Has issues.**

---

### S.2: GPIB cable unplugged during run

**Initial state:** One LakeShore on shared GPIB bus, critical channels feeding SafetyManager, experiment running.  
**Event:** Operator physically unplugs the cable.  
**Trace step by step:**
1. Next poll enters `driver.safe_read()` under `asyncio.wait_for(... timeout=3.0)` for the GPIB bus loop (`src/cryodaq/core/scheduler.py:241-245`).
2. Errors increment per device and per bus; after the first failures the scheduler sends device clear, then IFC, then eventually resets the ResourceManager (`src/cryodaq/core/scheduler.py:257-293`).
3. After repeated failures the device is disconnected and only retried every 30 seconds (`src/cryodaq/core/scheduler.py:215-228`, `295-301`).
4. SafetyManager sees no fresh critical-channel arrivals and faults on monotonic stale timeout (`src/cryodaq/core/safety_manager.py:669-673`).
5. When the cable is reinserted, the scheduler will reconnect on the next rate-limited attempt; no full engine restart is required.

**Code references:** `src/cryodaq/core/scheduler.py:178-309`, `src/cryodaq/core/safety_manager.py:669-673`, `src/cryodaq/drivers/transport/gpib.py` (reconnect/clear path read separately during this pass)

**Issues identified:**
- Previous audit `A.1` remains relevant: executor-side poll work is not force-cancelled just because the outer coroutine timed out.

**Verdict:** **Handles safely but recovery is slow.** The safety path is correct; the operator experience is degraded and the older executor-cancellation issue still matters.

---

### S.3: Disk fills during `finalize_experiment`

**Initial state:** Experiment ends normally, `finalize_experiment()` runs.  
**Event:** Filesystem fills while report generation is running.  
**Trace step by step:**
1. `finalize_experiment()` builds the archive snapshot and writes end metadata before report generation (`src/cryodaq/core/experiment.py:722-731`).
2. Report generation runs after metadata writes, inside a `try/except` (`src/cryodaq/core/experiment.py:732-738`).
3. Any report-generation exception is logged as warning; experiment active state is still cleared (`src/cryodaq/core/experiment.py:739`).
4. The next experiment can start because experiment state is no longer active.
5. Partial report artifacts may remain, but the experiment’s primary metadata and SQLite readings are already committed.

**Code references:** `src/cryodaq/core/experiment.py:682-740`

**Issues identified:**
- Previous audit findings about partial sidecars and soffice failure remain re-confirmed, but I do not duplicate them here.

**Verdict:** **Handles correctly at the lifecycle boundary.** Reporting can fail, but the experiment itself is not left half-open.

---

### S.4: Operator closes GUI during active experiment

**Initial state:** Launcher or standalone GUI is open, engine running, experiment active.  
**Event:** Operator clicks the window close button.  
**Trace step by step:**
1. In launcher mode, `LauncherWindow.closeEvent()` ignores the close and hides to tray (`src/cryodaq/launcher.py:752-763`).
2. Engine process is not stopped by that action; launcher timers and tray control keep running (`src/cryodaq/launcher.py:334-345,671-723`).
3. In standalone GUI mode, there is no launcher shell; closing the window exits the GUI process and runs GUI cleanup (`src/cryodaq/gui/app.py:82-89`).
4. Standalone GUI shutdown stops only the GUI bridge subprocess and releases `.gui.lock`; it does not command Keithley or experiment lifecycle (`src/cryodaq/gui/app.py:85-88`).
5. In both cases, hardware authority remains with the engine/SafetyManager, not the closing GUI window.

**Code references:** `src/cryodaq/launcher.py:334-345,671-723,752-763`, `src/cryodaq/gui/app.py:82-89`

**Issues identified:** None new.

**Verdict:** **Handles correctly in launcher mode; standalone GUI exits cleanly but leaves the engine running headless.**

---

### S.5: `FAULT_LATCHED` with operator absent for 8 hours

**Initial state:** Active experiment, overnight run, no operator present.  
**Event:** A fault trips at 02:00 and nobody acknowledges until 10:00.  
**Trace step by step:**
1. `_fault()` latches state immediately, clears active sources, and forces Keithley `emergency_off()` (`src/cryodaq/core/safety_manager.py:538-556`).
2. Scheduler continues polling non-failed instruments; there is no global experiment abort path tied to safety state.
3. `ExperimentManager` active state remains unchanged because no safety callback is registered (`src/cryodaq/core/safety_manager.py:447-448`; no call site found).
4. EventLogger does not automatically log the fault transition; it only logs lifecycle commands when explicitly called by engine command handling (`src/cryodaq/core/event_logger.py:18-35`, `src/cryodaq/engine.py:1202-1219`).
5. By morning, the experiment may still look “active” even though the source has been off for eight hours.

**Code references:** `src/cryodaq/core/safety_manager.py:538-556`, `src/cryodaq/core/event_logger.py:18-35`, `src/cryodaq/engine.py:1202-1219`

**Issues identified:**
- `H.6 [HIGH]` Safety faults do not propagate into experiment lifecycle.
- `H.13 [MEDIUM]` Automatic event logging is best-effort and incomplete.

**Verdict:** **Has issues.**

---

### S.6: Two simultaneous experiments attempted

**Initial state:** One operator already starts an experiment.  
**Event:** A second client tries to start another almost simultaneously.  
**Trace step by step:**
1. Both requests reach the single REP command server (`src/cryodaq/core/zmq_bridge.py:282-343`).
2. The first completes before the second is received.
3. The first `create_experiment()` sets `_active` and writes state (`src/cryodaq/core/experiment.py:557-608`, `843-849`).
4. The second sees `_active is not None` and fails (`src/cryodaq/core/experiment.py:572-575`).
5. Crash-stale launcher/GUI locks do not override the engine’s experiment guard.

**Code references:** `src/cryodaq/core/zmq_bridge.py:282-343`, `src/cryodaq/core/experiment.py:557-608`

**Issues identified:** None new.

**Verdict:** **Handles correctly.**

---

### S.7: Calibration runtime apply during active measurement

**Initial state:** LakeShore channel is being polled; operator applies a runtime calibration policy.  
**Event:** `calibration_runtime_set_channel_policy` arrives mid-run.  
**Trace step by step:**
1. Calibration command is handled in a worker thread via `asyncio.to_thread(...)` (`src/cryodaq/engine.py:1256-1275`).
2. LakeShore `read_channels()` resolves runtime policies once per call (`src/cryodaq/drivers/instruments/lakeshore_218s.py:452-464`).
3. The current poll stays consistent under the old policy set.
4. The next poll uses the new policy.
5. If calibration acquisition is active, SRDG is still written in a separate post-main-write transaction (`src/cryodaq/core/scheduler.py:357-366`).

**Code references:** `src/cryodaq/engine.py:1256-1275`, `src/cryodaq/drivers/instruments/lakeshore_218s.py:452-545`, `src/cryodaq/core/calibration_acquisition.py:95-122`

**Issues identified:**
- `H.10 [HIGH]` Calibration persistence remains non-atomic even though the policy switch itself is batch-consistent.

**Verdict:** **Mostly correct, with a persistence-integrity hole.**

---

### S.8: Engine restarts while GUI is connected

**Initial state:** GUI/launcher is up, engine dies and is restarted.  
**Event:** Engine crashes or is killed.  
**Trace step by step:**
1. GUI bridge subprocess continues running and watching heartbeats (`src/cryodaq/gui/app.py:64-78`, `src/cryodaq/gui/zmq_client.py:140-146`).
2. Launcher health timer notices engine failure and restarts it (`src/cryodaq/launcher.py:334-345`, `671-723`, verified during this pass).
3. ZMQ subscriber reconnect behavior is enabled with `RECONNECT_IVL`/`RECONNECT_IVL_MAX` (`src/cryodaq/core/zmq_bridge.py:227-235`).
4. The active experiment can be restored by the new engine from metadata/state (`src/cryodaq/core/experiment.py:856-909`).
5. Some GUI command surfaces block while the engine is down; the experiment workspace is the clearest example (`H.15`).

**Code references:** `src/cryodaq/gui/app.py:64-78`, `src/cryodaq/gui/zmq_client.py:140-167`, `src/cryodaq/core/zmq_bridge.py:227-235`, `src/cryodaq/core/experiment.py:856-909`

**Issues identified:**
- `H.15 [MEDIUM]` Synchronous GUI command calls worsen recovery UX.

**Verdict:** **Recovers functionally, but with avoidable UI freezing.**

---

### S.9: NTP correction during cooldown

**Initial state:** Cooldown predictor and vacuum trend have hours of data.  
**Event:** System clock jumps backwards by 30 seconds.  
**Trace step by step:**
1. Cooldown feed uses `reading.timestamp.timestamp()` as the detector input (`src/cryodaq/analytics/cooldown_service.py:297-303`).
2. `CooldownDetector.update()` comments assume monotonic `ts`, but the actual value is wall clock (`src/cryodaq/analytics/cooldown_service.py:96-105`).
3. `_do_predict()` computes `t_elapsed` from `time.time() - self._cooldown_wall_start`, so elapsed time can regress (`src/cryodaq/analytics/cooldown_service.py:351-354`).
4. Vacuum trend appends raw wall-clock timestamps without sorting or rejection (`src/cryodaq/analytics/vacuum_trend.py:125-153`, `src/cryodaq/engine.py:1095-1112`).
5. Alarm v2 state tracking also uses wall-clock age checks via `time.time()` and reading timestamps (`src/cryodaq/core/channel_state.py:65-136`).

**Code references:** `src/cryodaq/analytics/cooldown_service.py:96-161,297-354`, `src/cryodaq/analytics/vacuum_trend.py:125-153`, `src/cryodaq/core/channel_state.py:65-136`

**Issues identified:**
- `H.11 [HIGH]` Cooldown predictor mixes wall clock and “monotonic” assumptions.
- `H.12 [MEDIUM]` Vacuum trend fitting is not robust to backward timestamps.

**Verdict:** **Has issues.**

---

### S.10: Telegram bot token leaked

**Initial state:** Attacker has the bot token.  
**Event:** Attacker sends `/phase`, `/log`, or monitoring commands from an unauthorized chat.  
**Trace step by step:**
1. Bot constructor rejects empty allowlists when commands are enabled (`src/cryodaq/notifications/telegram_commands.py:87-96`).
2. `_fetch_updates()` filters by chat id (`src/cryodaq/notifications/telegram_commands.py:242-247`).
3. `_handle_message()` re-checks the same allowlist defensively (`src/cryodaq/notifications/telegram_commands.py:249-266`).
4. `/phase` only accepts canonical enum values or explicit aliases (`src/cryodaq/notifications/telegram_commands.py:412-435`).
5. The real residual blast radius is not allowlist bypass; it is what an **authorized** operator can do with `/log` and other commands (`H.14`).

**Code references:** `src/cryodaq/notifications/telegram_commands.py:87-96,242-266,412-435`

**Issues identified:**
- `H.14 [HIGH]` Authorized operator text becomes stored XSS in the web dashboard.

**Verdict:** **Allowlist holds, secondary surfaces do not.**

## Mode 4: Cross-module interaction analysis

### I.1: Scheduler ↔ SafetyManager reading order

**Boundary:** `Scheduler` publishes full readings to `SafetyBroker`; `SafetyManager` consumes them.  
**Contract (implicit or explicit):** Safety should not depend on wall-clock ordering of driver timestamps.  
**Investigation:** `src/cryodaq/core/scheduler.py:373-377`, `src/cryodaq/core/safety_manager.py:631-717`  
**Findings:**
- SafetyManager records arrival time with `time.monotonic()` on ingestion, so stale detection is based on local arrival freshness, not device timestamp.
- That contract holds for safety stale/heartbeat behavior.
- It does **not** hold for `alarm_v2`, which is fed from throttled broker data and uses wall-clock timestamps.

**Verdict:** **Contract holds for SafetyManager, diverges for alarm_v2.**

---

### I.2: SafetyManager ↔ ExperimentManager

**Boundary:** Safety state transitions vs experiment lifecycle state.  
**Contract (implicit or explicit):** A faulted experiment should have an explicit lifecycle/provenance reflection.  
**Investigation:** `src/cryodaq/core/safety_manager.py:447-533`, repo-wide search for `on_state_change(`, `src/cryodaq/core/experiment.py:682-770`  
**Findings:**
- `SafetyManager` supports callbacks.
- No engine code registers one.
- Therefore safety faults do not touch experiment metadata automatically.

**Verdict:** **Contract violated.** This is `H.6`.

---

### I.3: InterlockEngine ↔ SafetyManager

**Boundary:** Interlock action semantics (`stop_source` vs `emergency_off`).  
**Contract (implicit or explicit):** Soft stop should not fault-latch unless escalation is needed.  
**Investigation:** `src/cryodaq/engine.py:872-923`, `src/cryodaq/core/safety_manager.py:719-789`  
**Findings:**
- `trip_handler` passes through the action string.
- `stop_source` now transitions to `SAFE_OFF` without latching fault unless `emergency_off()` itself fails.

**Verdict:** **Contract holds.**

---

### I.4: AdaptiveThrottle ↔ alarm_v2

**Boundary:** Archive/live throttling vs derived alarm evaluation.  
**Contract (implicit or explicit):** Alarm evaluation should not be distorted by archive-thinning policy.  
**Investigation:** `src/cryodaq/core/scheduler.py:331-377`, `src/cryodaq/engine.py:1015-1027`, `config/housekeeping.yaml`, `config/alarms_v3.yaml:128-149`  
**Findings:**
- `alarm_v2` is fed from `DataBroker`, not `SafetyBroker`.
- `DataBroker` receives throttled `persisted_readings`.
- `data_stale_temperature` warning timeout equals throttle `max_interval_s`.

**Verdict:** **Contract violated.** This is `H.5`.

---

### I.5: CalibrationStore ↔ LakeShore runtime

**Boundary:** Runtime calibration policy updates while reads are in progress.  
**Contract (implicit or explicit):** One read batch should be internally consistent.  
**Investigation:** `src/cryodaq/drivers/instruments/lakeshore_218s.py:452-545`, `src/cryodaq/engine.py:1256-1275`  
**Findings:**
- Policy lookup happens once per read cycle.
- The current batch is internally consistent; changes take effect next poll.

**Verdict:** **Contract holds.**

---

### I.6: ExperimentManager ↔ ReportGenerator

**Boundary:** Experiment finalization vs report generation.  
**Contract (implicit or explicit):** A report failure should not keep the experiment open.  
**Investigation:** `src/cryodaq/core/experiment.py:722-740`  
**Findings:**
- Metadata and archive snapshot are written before report generation.
- Report errors are caught and logged.
- Active experiment state is cleared regardless.

**Verdict:** **Contract holds for lifecycle closure.**

---

### I.7: GUI ↔ Engine via ZMQ

**Boundary:** Engine restart, GUI subscriber reconnect, synchronous command surfaces.  
**Contract (implicit or explicit):** GUI should reconnect without becoming misleading or frozen.  
**Investigation:** `src/cryodaq/core/zmq_bridge.py:227-235`, `src/cryodaq/gui/zmq_client.py:140-167`, `src/cryodaq/gui/widgets/experiment_workspace.py:81-99`  
**Findings:**
- Subscriber reconnect is configured.
- Some panels use worker threads and degrade cleanly.
- `ExperimentWorkspace.refresh_state()` still blocks the GUI thread.

**Verdict:** **Contract partially holds.** Functional recovery exists, but UX under restart is worse than it should be.

---

### I.8: Web dashboard ↔ Engine

**Boundary:** `/api/status` command RPC vs dashboard meaning shown to operators.  
**Contract (implicit or explicit):** “Engine offline” and “engine faulted” should not collapse into the same UI symbol.  
**Investigation:** `src/cryodaq/web/server.py:335-362,459-466`  
**Findings:**
- On RPC exception, `base["safety"] = None`.
- The frontend renders `—` when `d.safety` is absent.
- Faulted and disconnected states are therefore visually separable only when the RPC works.

**Verdict:** **Contract ambiguous.** This is a low-severity but real operational ambiguity.

## Mode 5: Incident pattern matching

### P.1: Therac-25 race condition

**Pattern:** UI state changes faster than backend can confirm.  
**Search method:** Read Keithley panel command flows and button/result handling.  
**Result:** **Pattern not present** in the main Keithley controls.  
**Evidence:** `src/cryodaq/gui/widgets/keithley_panel.py:305-358` waits for result and explicitly tells the operator to wait for confirmed state.  
**Finding:** None.

---

### P.2: Mars Climate Orbiter unit confusion

**Pattern:** Mixed units without explicit boundaries.  
**Search method:** Read `Reading` model and the driver/analytics paths that construct readings.  
**Result:** **Mostly not present.**  
**Evidence:** `src/cryodaq/drivers/base.py:30-49` carries explicit `unit` on every `Reading`.  
**Finding:** No physical-unit confusion found in scoped modules. The real cross-cutting issue was timebase confusion, not Kelvin/mbar confusion.

---

### P.3: Knight Capital old-path still live

**Pattern:** Deprecated code remains imported.  
**Search method:** Repo-wide search for `autosweep_panel`.  
**Result:** **Pattern not present.**  
**Evidence:** Search hit only the deprecated file itself: `src/cryodaq/gui/widgets/autosweep_panel.py:1,642`. No imports from live code paths were found.  
**Finding:** None.

---

### P.4: AWS S3 outage style over-broad manual command

**Pattern:** Operator command with insufficient input validation can affect more than intended.  
**Search method:** Read Telegram `/phase` and experiment command handlers.  
**Result:** **Mostly not present** on the exposed remote path.  
**Evidence:** `src/cryodaq/notifications/telegram_commands.py:412-435` canonicalizes and validates phases against `ExperimentPhase`.  
**Finding:** None in the audited remote command surface.

---

### P.5: Cloudflare regex catastrophic backtracking from user input

**Pattern:** Runtime regex compilation from untrusted user text.  
**Search method:** Repo-wide search for `re.compile` and regex use.  
**Result:** **Pattern not present** from Telegram/web/operator input.  
**Evidence:** Regex compilation comes from config and internal patterns (`src/cryodaq/core/alarm.py`, `src/cryodaq/core/interlock.py`, `src/cryodaq/core/housekeeping.py`, `src/cryodaq/logging_setup.py`), not remote free text.  
**Finding:** None.

---

### P.6: Heartbleed-style serial buffer over-read

**Pattern:** Trusting packet-declared length or unbounded parser reads.  
**Search method:** Read `ThyracontVSP63D` and `SerialTransport`.  
**Result:** **Pattern not present** in the current parser.  
**Evidence:** `src/cryodaq/drivers/transport/serial.py:136-167` reads until a terminator; `src/cryodaq/drivers/instruments/thyracont_vsp63d.py:338-364` validates checksum/structure before decoding the V1 payload.  
**Finding:** None.

---

### P.7: Microsoft Tay style prompt injection / trusted text reuse

**Pattern:** User text flows into another interpreter or HTML sink without sanitization.  
**Search method:** Traced `/log` text from Telegram into the web dashboard.  
**Result:** **Pattern present.**  
**Evidence:** `src/cryodaq/web/server.py:499-503` uses `innerHTML` with operator log text.  
**Finding:** `H.14 [HIGH] Stored XSS in web dashboard via operator log messages`.

---

### P.8: NTPD time jump bugs

**Pattern:** Logic assumes wall clock never moves backward.  
**Search method:** Repo-wide timestamp/timebase search; read cooldown, vacuum trend, `alarm_v2`, and `channel_state`.  
**Result:** **Pattern present.**  
**Evidence:** `src/cryodaq/analytics/cooldown_service.py:297-354`, `src/cryodaq/analytics/vacuum_trend.py:125-153`, `src/cryodaq/core/channel_state.py:65-136`.  
**Finding:** `H.11 [HIGH]` and `H.12 [MEDIUM]`.

---

### P.9: Heisenbug from logging

**Pattern:** Debug logging triggers side effects via `__repr__`/`__str__`.  
**Search method:** Repo-wide search for `__repr__` / `__str__`.  
**Result:** **Pattern not present.**  
**Evidence:** The only custom implementations are the masking methods on `SecretStr` in `src/cryodaq/notifications/_secrets.py:25-29`, and they are pure.  
**Finding:** None.

---

### P.10: Y2K / epoch overflow style timestamp failure

**Pattern:** Narrow integer timestamp arithmetic or fixed-epoch truncation.  
**Search method:** Repo-wide scan for timestamp handling in scoped modules.  
**Result:** **Pattern not found** in the audited Python paths.  
**Evidence:** Timestamps are handled as Python `datetime` or float epoch seconds, not 32-bit ints.  
**Finding:** None.

## New findings consolidated list

| ID | Severity | Title | Origin mode | Location |
|----|----------|-------|-------------|----------|
| H.5 | HIGH | Adaptive throttle can self-trigger 30s warning stale alarms | Mode 2 / 4 | `src/cryodaq/core/scheduler.py:331-377`, `src/cryodaq/engine.py:1015-1027`, `src/cryodaq/core/housekeeping.py:223-307`, `config/alarms_v3.yaml:128-133` |
| H.6 | HIGH | Safety faults do not propagate into experiment lifecycle or metadata | Mode 2 / 3 / 4 | `src/cryodaq/core/safety_manager.py:447-533`, `src/cryodaq/core/experiment.py:682-770` |
| H.10 | HIGH | Calibration poll cycles are not atomically persisted | Mode 2 / 3 | `src/cryodaq/core/scheduler.py:338-366`, `src/cryodaq/core/calibration_acquisition.py:95-122` |
| H.11 | HIGH | Cooldown predictor mixes wall clock and pseudo-monotonic time | Mode 2 / 3 / 5 | `src/cryodaq/analytics/cooldown_service.py:96-161,297-354` |
| H.14 | HIGH | Stored XSS in web dashboard via operator log messages | Mode 2 / 3 / 5 | `src/cryodaq/notifications/telegram_commands.py:392-406`, `src/cryodaq/web/server.py:497-503` |
| H.12 | MEDIUM | VacuumTrendPredictor accepts backward timestamps and can fit nonsense | Mode 2 / 3 / 5 | `src/cryodaq/engine.py:1095-1112`, `src/cryodaq/analytics/vacuum_trend.py:125-153` |
| H.13 | MEDIUM | Auto-generated experiment events are best-effort and can vanish silently | Mode 2 / 3 | `src/cryodaq/core/event_logger.py:18-35` |
| H.15 | MEDIUM | Experiment workspace can freeze the GUI for up to 5s on engine trouble | Mode 2 / 3 / 4 | `src/cryodaq/gui/widgets/experiment_workspace.py:81-99`, `src/cryodaq/gui/zmq_client.py:148-167` |
| I.8 | LOW | Web dashboard collapses “fault unknown” and “engine offline” into the same blank state | Mode 4 | `src/cryodaq/web/server.py:335-362,459-466` |

## Web research log

- https://github.com/python/cpython/issues/107505 — `run_in_executor` cancellation does not stop the underlying thread; used to re-frame the old GPIB timeout problem without re-raising it as new.
- https://pyvisa.readthedocs.io/en/1.8/api/visalibrarybase.html — `clear(session)` “Clears a device.” Used to verify what CryoDAQ’s VISA clear path actually does.
- https://pyzmq.readthedocs.io/en/v25.1.2/api/zmq.html — consulted for `LINGER`, REP/Context termination, reconnect options.
- https://pyserial.readthedocs.io/en/stable/url_handlers.html — notes `PosixPollSerial` has “better handling of errors, such as a device disconnecting while it’s in use”.
- https://pyinstaller.org/en/v3.2/runtime-information.html — runtime meaning of `sys.frozen`, `sys._MEIPASS`, and `sys.executable`.
- https://docs.python.org/tr/3.13/library/time.html — monotonic-clock semantics; used for time-jump findings.
- https://doc.qt.io/qt-6.9/threads-modules.html — Qt threading guidance; used for GUI blocking analysis.
- https://developer.mozilla.org/es/docs/Web/API/Element/innerHTML — `innerHTML` as HTML sink; used for stored-XSS finding.
- https://docs.aiohttp.org/ — consulted for `ClientSession` lifecycle and connection reuse when reviewing Telegram code.
- https://sqlite.org/wal.html — WAL durability/checkpoint semantics; used heavily for power-loss and transaction-boundary reasoning.
- https://pyserial.readthedocs.io/en/stable/pyserial_api.html — serial timeout/write semantics reference.
- https://zguide2.zeromq.org/hx%3Achapter1 — slow-joiner / PUB-SUB background context consulted during restart-path reasoning.
- https://libzmq.readthedocs.io/en/latest/zmq_ctx_set.html — linger/termination guidance for socket shutdown.
- https://pyvisa.readthedocs.io/_/downloads/en/1.11.3/pdf/ — thread-safety release-note reference consulted while re-checking GPIB transport assumptions.

## What the previous audit missed and why

The previous audit was mostly module-local. That was good for obvious hazards, but it systematically underweighted three classes of failures:

- **Throttled vs full-rate consumers.** The first pass treated `Scheduler`, `AdaptiveThrottle`, `alarm_v2`, and analytics mostly as separate modules. The real bug is in the contract between them: one consumer sees the thinned stream while another sees the full stream.
- **Safety vs provenance.** The prior pass focused on whether `SafetyManager` turns outputs off. This pass found the equally important question of whether the experiment record reflects that safety event at all.
- **Trusted-input security.** The first pass correctly identified unauthenticated web exposure, but it did not follow trusted operator text all the way into browser HTML sinks.

In short: pass 1 found bad local code. This pass found good local code with bad global composition.

## What this pass still missed

- I did not fully re-read every reporting module in this pass; I only traced the report/finalize boundary again.
- I did not perform a fresh dependency-by-dependency CVE sweep because the prompt for this pass emphasized hardening and cross-module failure modes over package inventory.
- I did not validate Linux kernel 5.15 USB-TMC behavior against the exact Keithley usage path deeply enough to write a defensible new finding.
- I did not fully audit every root plugin in `plugins/`; I focused on the hot-reload pipeline rather than plugin-specific math.
- I did not prove whether `sensor_diagnostics` and `cooldown_service` should also bypass adaptive throttling the way `SafetyManager` should; that looks worth a future focused pass.

## Cross-cutting observations

- CryoDAQ’s strongest design choice is the **separation between the safety path and the ordinary data path**. The weakest design choice is that newer analytics and alarm consumers are attached to the ordinary path without always re-checking whether “ordinary” now means “throttled”.
- The codebase is generally careful about **hardware authority** and much less careful about **experiment provenance authority**. Safety events are well-handled electrically, but not yet first-class in experiment metadata.
- Timebase discipline is inconsistent. `SafetyManager` is monotonic and robust; several newer analytics/features are wall-clock based and inherit all the usual NTP/manual-clock-jump failure modes.
- Trusted-operator input is still treated as inherently safe in the web layer. In a lab environment that assumption is too weak: compromised chat accounts and insider mistakes are both realistic.

## Security surface summary

The safety-critical hardware-control surface is much better defended than the peripheral surfaces: source enable/disable still routes through `SafetyManager`, Telegram command allowlisting is implemented correctly, and the frozen-entry/path logic is materially stronger than it was before Phase 2. The remaining security weakness is at the monitoring/provenance edge: the web dashboard still trusts stored operator text too much, and experiment metadata still trusts manual cleanup too much after safety faults.

## Modules skipped / unable to audit

- No scoped source module was intentionally skipped.
- I did not deep-read `tests/`, `docs/`, `graphify-out/`, `build/`, or `dist/` because they were explicitly out of scope.
- I did not promote any new finding about root `plugins/*.py` because the hot-reload pipeline, not the plugin formulas, was the material hardening topic for this pass.
