# CryoDAQ Polish Assessment (read-only architect pass, 2026-06-24)

**Scope:** safety / engine / driver / storage / alarm / interlock / notification paths.
**Method:** read the critical modules end-to-end; grepped for bare-except, non-finite
coercions, unbounded growth, missing timeouts, swallowed exceptions, TODO/FIXME;
cross-checked against `docs/ORCHESTRATION.md` invariants and `CLAUDE.md` rules.
All findings below were verified against source at the cited line — model-suggested
findings that did not survive a source read are listed at the end as REJECTED so they
are not re-litigated.

**Headline:** this is a high-quality, defensively-coded codebase. The safety FSM,
SafetyBroker overflow→FAULT, persistence-first ordering, Keithley crash-recovery
force-off, `_fault()` shielding, and disk-full degradation are all correct and
well-reasoned. The genuine polish surface is small. The single material gap is that
**command setpoints (P/V/I) are never finite-checked**, so a `NaN` payload bypasses
every limit comparison and reaches the hardware. Everything else is HIGH-or-below
robustness hardening.

---

## DO FIRST (top actionable items, ranked)

1. **[CRIT] NaN/Inf command setpoint reaches the power source.** `engine.py:151-153`
   coerces `p_target/v_comp/i_comp` with bare `float(...)`; `zmq_bridge.py:511`
   uses bare `json.loads` (Python accepts `NaN`/`Infinity` literals). `NaN`
   passes every guard downstream (`nan > max` is False at `safety_manager.py:292-311`;
   `nan <= 0` is False at `keithley_2604b.py:235`), then `math.sqrt(nan*R)` →
   `levelv = nan` is written via SCPI (`keithley_2604b.py:187-204`). Fix below.
2. **[HIGH] `update_target` / `update_limits` share the same NaN gap.**
   `safety_manager.py:457` (`if p_target <= 0`) and `:504/:517` (`v_comp/i_comp <= 0`)
   reject ≤0 but not `NaN`; a live NaN update writes `limitv/limiti = nan`
   (`safety_manager.py:512/524`).
3. **[HIGH] `zmq_bridge` JSON decode admits non-finite literals.** `zmq_bridge.py:511`
   `json.loads(raw)` with no `parse_constant`. Reject `NaN/Infinity` at the trust
   boundary so the whole command surface is finite-clean in one place.
4. **[HIGH] Alarm panel renders `NaN` for a faulted sensor.** `alarm_panel.py:609`
   `value = float(reading.value)` catches `TypeError/ValueError` but `float(nan)`
   succeeds; the NaN is stored in `_AlarmRow.value` and shown to the operator.
   (This is ESCALATION.md CRIT #1 / `DEFERRED-NAN-11`; restated here because the
   fix is now unambiguous given the finding-1 decision.)
5. **[MED] `interlock` cooldown can suppress a *worse* breach.** `interlock.py:388-399`
   skips a trip entirely while `cooldown_s` is active, even if the value has moved
   far past threshold. For a protective interlock, "already tripped recently" should
   not silence an escalating breach. Consider: cooldown suppresses re-logging, not
   re-tripping, OR re-trip if value crosses a second harder threshold.
6. **[MED] `alarm_v2` threshold reads `cfg["threshold"]` with a hard index.**
   `alarm_v2.py:225/227/229/233` use `cfg["threshold"]` / `cfg["range"]` /
   `cfg["setpoint_source"]` — a YAML alarm missing the key raises `KeyError` at
   *evaluate* time (caught at `:152` and logged, alarm silently returns None =
   never fires). Validate required keys at load (`alarm_config.py`) so a misconfigured
   safety alarm fails closed at startup, not silently at runtime.
7. **[LOW] `alarm_config` numeric config has no range/finite validation.**
   `alarm_config.py:156/160/161/162` coerce `default`, `poll_interval_s`,
   `rate_window_s`, `rate_min_points` with bare `float()/int()`. A negative
   `poll_interval_s` or zero `rate_window_s` loads cleanly and misbehaves later.
   Add fail-closed range checks in `_parse_engine_config`.
8. **[LOW] `alarm_providers` swallows a malformed phase timestamp → 0.0.**
   `alarm_providers.py:65-66` returns `0.0` (and `:54` on falsy) for an unparseable
   `started_at`, with no log. Effect: phase-elapsed gating treats the phase as
   "just started", silently suppressing elapsed-time alarms. Log at WARNING.

---

## Theme A — Non-finite values in the command/control path (the real gap)

The codebase rigorously rejects non-finite **reading** values
(`safety_manager.py:887,960`; `keithley_2604b.py:436-438`; `sqlite_writer.py:350-352`).
It does **not** apply the same discipline to **command setpoints**. The FSM's limit
checks are all `value > max`-style upper bounds, and IEEE-754 makes every comparison
against `NaN` return False, so `NaN` is the one input that defeats them all (`+Inf`
is actually caught because `inf > max` is True).

- **CRIT — `engine.py:151-154`** — `p = float(cmd.get("p_target", 0))`,
  `v = float(cmd.get("v_comp", 40))`, `i = float(cmd.get("i_comp", 1.0))` then
  `request_run(p, v, i, ...)`. No `math.isfinite`. Source of the payload is any REQ
  client (GUI subprocess, web dashboard, future CLI) and the JSON decoder upstream
  accepts `NaN`/`Infinity`.
- **CRIT — `safety_manager.py:292-311`** — `if p_target > self._config.max_power_w`
  / `if v_comp > ...` / `if i_comp > ...`. `nan > x` → False; all three pass.
- **CRIT — `keithley_2604b.py:235`** — `if p_target <= 0 or v_compliance <= 0 or
  i_compliance <= 0:` `nan <= 0` → False; passes. Then `start_source` writes
  `limitv = {v_compliance}` / `limiti = {i_compliance}` (`:255-256`) — `nan` formatted
  into SCPI.
- **CRIT — `keithley_2604b.py:187-204`** — regulation loop:
  `target_v = math.sqrt(runtime.p_target * resistance)` = `nan`;
  `max(0.0, min(nan, v_comp))` = `nan`; `levelv = {target_v}` written.

**Fix (single choke point + defense in depth):**
1. In `zmq_bridge.py:511`, decode with
   `json.loads(raw, parse_constant=_reject)` where `_reject` raises, so
   `NaN/Infinity/-Infinity` are rejected as "invalid JSON" exactly like a syntax
   error (the existing `:512-513` error path already handles this cleanly).
2. In `engine.py` `keithley_start`/`keithley_set_target`/`keithley_set_limits`,
   after coercion add `if not math.isfinite(p): return {"ok": False, "error": ...}`.
3. As the load-bearing backstop, add `math.isfinite(...)` guards inside
   `SafetyManager.request_run` and `update_target`/`update_limits` next to the
   existing `> max` / `<= 0` checks (`safety_manager.py:292,457,504,517`). This is
   the layer that must not be bypassable regardless of caller.

Trade-off: three small guards vs one. Recommend all three — the SafetyManager guard
is mandatory (it is the documented single authority); the bridge and engine guards
make the failure visible earlier and keep the rest of the command surface clean.

---

## Theme B — Fail-closed-at-load vs fail-silent-at-runtime (alarm config)

`safety.yaml` and `interlocks.yaml` loaders are exemplary: they validate types,
compile regexes, and raise a dedicated `*ConfigError` so startup aborts on bad
config (`safety_manager.py:136-214`, `interlock.py:226-270`). The **alarm v2/v3**
path is weaker:

- **MED — `alarm_v2.py:225-233`** — threshold/range/setpoint keys are read with
  hard subscripts during `evaluate`. Missing key → `KeyError` → caught at
  `alarm_v2.py:152-154` → `return None`. A misconfigured **safety-relevant** alarm
  therefore *never fires* and only leaves an ERROR log line. This violates the
  fail-closed spirit the safety/interlock loaders follow.
- **LOW — `alarm_config.py:156-162`** — numeric coercions without range checks
  (see DO-FIRST #7).

**Fix:** in `alarm_config._expand_alarm`, assert presence + type of the keys each
`alarm_type` requires (threshold needs `threshold`; outside_range needs a 2-tuple
`range`; deviation_from_setpoint needs `setpoint_source`) and raise `AlarmConfigError`.
Then the `evaluate`-time `except` at `:152` only ever catches genuine runtime
surprises, not config typos. Trade-off: slightly more load-time code; buys
fail-closed semantics for the alarm engine to match the rest of safety.

---

## Theme C — Protective-action suppression windows

- **MED — `interlock.py:388-399`** — `cooldown_s` short-circuits the trip with
  `continue` while the window is open. For a cryo-protection interlock this means a
  reading that has moved *further* past threshold during the cooldown is ignored.
  The cooldown is meant to prevent log/Telegram spam, not to blind the protection.
  Recommend: keep cooldown for notification dedup, but always re-evaluate the
  protective action (or add a hard second threshold that bypasses cooldown).
  Trade-off: more trips/log churn on a flapping sensor vs guaranteed response to a
  worsening breach — for safety, bias to respond.

---

## Theme D — Operator-facing display correctness

- **HIGH — `alarm_panel.py:609`** — NaN renders into the alarm value cell (DO-FIRST
  #4 / ESCALATION CRIT #1). Once Theme-A finding 1 is decided, the panel fix is:
  coerce non-finite to a clear fault marker (e.g. "—") rather than "0" or "nan", so a
  faulted sensor is visibly faulted, not shown as a plausible 0. Trade-off:
  "—"/fault-marker vs 0 is a safety-display choice; 0 can mislead, "—" cannot.
- **LOW — `engine.py:1565-1573`** — `try: started = _dt.fromisoformat(...); ... except
  Exception: pass` leaves `elapsed = 0.0` on a malformed `started_at`. Display-only
  (phase elapsed in a status reply), non-safety, but a WARNING log would aid triage.

---

## Theme E — Items reviewed and found SOUND (do NOT touch)

Recorded so future passes don't re-flag them:

- `safety_broker.py:89-109` overflow→FAULT, no silent drop. Correct.
- `safety_manager.py:736-812` `_fault()` re-entry guard + `asyncio.shield` around
  emergency_off and post-mortem log. Correct and subtle; leave it.
- `scheduler.py:386-414` persistence-first (write_immediate before publish), disk-full
  short-circuit. Matches the documented invariant. Correct.
- `keithley_2604b.py:97-112,298-333` force-off on connect + readback-verify in
  emergency_off. Correct (best-effort, logs CRITICAL on mismatch as designed).
- `sqlite_writer.py:107-146` SQLite WAL-corruption version gate. Correct and
  well-documented.
- `zmq_bridge.py:489-545` REP serve loop — poll-with-timeout, always-send-reply
  discipline on every exception branch including CancelledError. No REP deadlock. Sound.
- `telegram.py:199-245` aiohttp `ClientTimeout(total=timeout_s)` on the session.
  `telegram_commands.py:201-226` poll loop has capped exponential backoff (`min(...,300)`)
  and a sleep floor. Sound.
- `rate_estimator.py:117` guards `den==0 / isnan(den) / isnan(num)` → returns None.
  A NaN reading poisons `v_mean`→`num`→returns None = no rate = fails safe (not
  "false-safe"); plus `safety_manager` rejects NaN readings independently. Sound.
- `channel_state.py:115` and `rate_estimator.py:34` deque `maxlen` are bounded by
  config-derived caps, not user input; not an OOM vector. Sound.
- `vacuum_trend.py` / `steady_state.py` / `cooldown_predictor.py` — read-only GUI
  analytics (`vacuum_trend.py:112` "Read-only consumer"), already guard `P<=0`
  (`:133`), `t_safe=max(t,1)` (`:78`), `sigma_sq<=0` (`:93`). Not safety-path; the
  numpy-NaN-crash claims do not reproduce against the guards present.

---

## REJECTED model-suggested findings (verified false — do not action)

Per ORCHESTRATION §14.6 these were checked at the cited line and did not hold:

- "channel_state.py:115 unbounded maxlen → OOM" — FALSE; `max(200, int(window*20)+100)`
  is a finite cap and deque enforces it.
- "vacuum_trend math.log/extrapolation crash corrupts safety forecast" — FALSE;
  guarded (`:93` sigma, `:78` t_safe) and the module is non-safety read-only analytics.
- "rate_estimator NaN → false-safe dT/dt" — direction wrong; NaN → `None` (no rate),
  which is fail-safe, and SafetyManager independently faults on NaN readings.
- "alarm_config NaN default disables alarms" — overstated; requires literal `.nan`
  in operator-authored YAML. Captured at LOW (DO-FIRST #7) as a load-time range check,
  not a CRIT.

---

## Note on the test-sweep ESCALATION.md

Items there are NOT re-reported except CRIT #1 (`alarm_panel` NaN), which is the same
defect as DO-FIRST #4 and is now actionable given the Theme-A decision. The CALIB-ROUTING
and test-infra items (7/10/12) are product/seam decisions, out of scope for this
robustness pass.
