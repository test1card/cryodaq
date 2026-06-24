# CryoDAQ Polish Assessment 3 — CONVERGENCE audit (cross-module / leaks / security / regression / config)

**Read-only architect pass, 2026-06-24.** Distinct angle from the two prior
module-by-module rounds (`POLISH_ASSESSMENT.md`, `POLISH_ASSESSMENT_2_{web,analytics,gui}.md`,
`POLISH_PROOF.md`): cross-module seams, error-path resource leaks, security across
boundaries, regression of the 8 just-fixed commits (98c90ac e9e66ce 88c4fbd d206297
1132a4b 10239cf 15d952a d33b019), and config fail-closed gaps beyond alarm_v2.
Nothing already found/fixed/rejected in the prior rounds is re-reported. Every claim
below was verified against the cited source line.

---

## VERDICT

**Converged. Nothing CRIT / HIGH / MED actionable.** One LOW finding (a stale,
now-unreachable log message left behind by the alarm fail-closed fix). The
cross-module seams, the command/control trust boundary, the resource-release paths,
and the 8 just-fixed areas are all sound under this audit's angle.

## DO FIRST

1. **[LOW] Stale/misleading log message orphaned by the d206297 alarm fail-closed
   fix.** `engine.py:2107`. The `else` branch logs
   `"Alarm Engine v2: config/alarms_v3.yaml не найден, v2 отключён"` ("not found,
   v2 disabled"). After d206297, `load_alarm_config` **raises `AlarmConfigError`**
   for a missing file (`alarm_config.py:102-106`) — it never returns empty for the
   not-found case anymore — and that error aborts the engine via the central catcher
   (`engine.py:3850-3856` → `sys.exit(ENGINE_CONFIG_ERROR_EXIT_CODE)`). So this
   `else` is now reachable ONLY when the file exists, parses, and contains zero
   alarm definitions ("found but empty"), yet its text still says "не найден"
   ("not found"). Behavior is correct and fail-closed; the message is just wrong for
   the only condition that now reaches it. **Fix:** change the text to "config
   present but no alarm definitions — v2 engine has no alarms to evaluate" (or
   similar). One-line, display/triage only, no behavior change. Trade-off: none.

---

## Per-angle detail

### 1. Cross-module / integration seams — TRACED, SOUND

- **Persistence-first vs SafetyBroker (scheduler seam).** `scheduler.py:358-414`.
  The adaptive throttle filters only the **archive/DataBroker** stream
  (`persisted_readings = self._adaptive_throttle.filter_for_archive(readings)`,
  `:359-360`); the **SafetyBroker** is published the FULL unthrottled `readings`
  (`:413-414` `_safety_broker.publish_batch(readings)`), while DataBroker gets the
  throttled set (`:411-412`). The documented invariant ("if **DataBroker** has a
  reading it is already in SQLite", CLAUDE.md:149) holds: DataBroker only ever
  receives `persisted_readings`, and `combined` (persisted+srdg) is what gets
  written at `:386-390`. When the throttle drops every reading and there is no SRDG,
  `combined == []` so the SQLite write is skipped AND DataBroker publish is skipped
  (`:411` guarded on `persisted_readings`), but SafetyBroker still sees the readings
  (`:413`). That asymmetry is intentional and correct: safety must observe every
  reading regardless of archival throttling; the persistence-first invariant is
  scoped to DataBroker, not SafetyBroker. No ordering or atomicity gap.

- **Engine command-dispatch → SafetyManager → driver ordering.**
  `engine.py:156-205` (`_run_keithley_command`) routes every state-mutating Keithley
  command through `SafetyManager.request_run / update_target / update_limits`, never
  touching the driver directly. The finite-coercion guard (`_coerce_finite_setpoint`,
  `:142-154`) sits in front of all three, and SafetyManager re-checks independently
  (`safety_manager.py:292-311,475,524-560`). Single-authority ordering preserved.

- **ZMQ REP command serve loop.** `zmq_bridge.py:526-585` keeps strict
  one-send-per-recv discipline on **every** branch (decode error `:549-551`, handler
  exception `:563-565`, CancelledError `:555-562/569-575`, serialization failure
  `:576-585`). `_run_handler` (`:439-524`) validates payload shape (`:460-468`),
  bounds the handler with `asyncio.wait_for` (`:484`), and always returns a dict.
  No REP-wedge seam, no handler that can mutate state past the timeout envelope
  silently.

### 2. Error-path resource leaks — TRACED, SOUND

- `zmq_subprocess.zmq_bridge_main` — `ctx = zmq.Context()` (`:98`) is released in a
  try/finally that joins both worker threads and calls `ctx.term()`
  (`zmq_subprocess.py:258-271`); SUB socket has `finally: sub.close()` (`:166-167`),
  REQ socket has `finally: req.close()` (`:242-243`). No leak on the exception path.
- `reporting/generator._try_convert_pdf` — `subprocess.run(..., timeout=_SOFFICE_TIMEOUT_S)`
  (`generator.py:277-290`); on `TimeoutExpired` (`:291-299`) `subprocess.run` itself
  kills+reaps the child before raising, then returns None (docx-only degrade). No
  orphan. (This is the 15d952a fix; verified complete.)
- `telegram.TelegramNotifier` — session created lazily (`_get_session:199-206`),
  closed in `close()` (`:208-211`); every send is `async with session.post(...)`
  so the response is always released. `telegram_commands` `start/stop` cancels both
  poll/collect tasks and `unsubscribe()`s the broker queue (`:168-181`). No
  operational leak.
- `sqlite_writer`, `escalation`, engine shutdown path — confirmed released by the
  prior rounds and re-spot-checked; nothing new.

### 3. Security across boundaries — TRACED, SOUND

- **No unsafe deserialization anywhere.** `grep` for `pickle / eval( / exec( /
  yaml.load( / yaml.unsafe / marshal / shelve / __import__` over `src/cryodaq/`
  finds only Qt `*.exec()` event-loop calls and the sanctioned `exec_module` plugin
  loader. Every YAML read uses `yaml.safe_load` (engine.py:726,729,1293,1734,2076,
  2168,2975,3005,3170; alarm_config.py:110; interlock loader; etc.).
- **ZMQ command surface trust boundary.** Bridge binds loopback by default
  (`zmq_bridge.py:64-65` `tcp://127.0.0.1:5555/5556`). `_decode_command`
  (`zmq_bridge.py:48-62`) rejects NaN/Infinity literals AND `1e999`-overflow floats
  at the boundary (98c90ac). State-mutating commands that accept a filesystem path
  (`calibration_curve_import/export`, `engine.py:1202-1256`) pass the path to
  `CalibrationStore.import_curve_file`, which parses `.json/.340/.cof` as DATA (no
  exec/pickle); the practical exposure is bounded to loopback callers (GUI subprocess
  / a same-host web dashboard). Acceptable for the documented deployment posture; a
  path-allowlist would be an architect/product hardening, not a polish defect.
- **Secret redaction is installed, not just defined.** `logging_setup.setup_logging`
  attaches the Telegram-token redaction filter to the root-logger stream handler
  (`logging_setup.py:139-140`), idempotently. `_secrets.SecretStr` guards repr/str.
  ZMQ error replies surface `str(exc)` (`zmq_bridge.py:565`) from config/keithley
  handlers — no token is in scope on those paths.
- Web exposure + unbounded reads already covered (and fixed) in
  `POLISH_ASSESSMENT_2_web.md` / 15d952a — not re-reported.

### 4. Regression audit of the 8 just-fixed commits — TRACED, NO REGRESSION

- **98c90ac (non-finite setpoints).** Guards are layered and consistent
  (bridge decode → engine coerce → SafetyManager → driver). `update_limits` was made
  atomic: BOTH fields validated before EITHER SCPI write
  (`safety_manager.py:524-560`). The two transport writes remain sequential, but each
  `runtime.v_comp/i_comp` update is individually gated on its own successful write —
  a pre-existing property, not introduced here. No new edge case.
- **88c4fbd (interlock cooldown).** The new `_trip` runs the protective action on
  every triggered eval, but the eval loop short-circuits TRIPPED interlocks
  (`interlock.py:382` `if record.state != InterlockState.ARMED: continue`), so a
  latched interlock is not re-evaluated until operator acknowledge re-arms it — NO
  action storm. `suppress_notification` only skips the loud CRITICAL log + the
  `last_trip_time` anchor; the action and audit event always run. Behavior matches
  the commit's claim. No regression.
- **d206297 (alarm fail-closed).** Correct fail-closed wiring: `load_alarm_config`
  raises `AlarmConfigError` on missing/malformed config (`alarm_config.py:96-141`),
  caught centrally and `sys.exit`-ed (`engine.py:3850-3856`). The one artefact is the
  stale `else`-branch message (DO-FIRST #1, LOW). The `started_at`-parse WARNING and
  numeric range checks are display/load-only, no caller impact.
- **e9e66ce / 1132a4b (GUI non-finite render + safety-strip blanking).** `1132a4b`
  block is transition-guarded (`if self._last_safety_state is not None`),
  panel-existence-guarded, idempotent, and restores on next reading
  (`main_window_v2.py:679+`). No unhandled caller.
- **10239cf (watchdog cooldown) / 15d952a (web/soffice) / d33b019 (analytics).**
  Re-checked the touched seams (launcher restart cooldown, soffice timeout, plugin
  teardown). All carry tests and Codex PASS; no new caller-visible behavior change
  surfaced under this angle.

### 5. Config / startup fail-closed — TRACED, SOUND

- **interlocks.yaml** — `load_config` (`interlock.py:202-278`) validates required
  keys via `InterlockCondition` + `add_condition`, and critically validates that
  `action` exists in the actions dict AT LOAD (`:296-301`), converting any failure to
  `InterlockConfigError` (`:268-272`). A typo'd action name fails at startup, NOT at
  the moment of a protective trip. Fail-closed.
- **safety.yaml** — required limits validated at load (per prior round and the
  central catcher's `SafetyConfigError` handling at `engine.py:3850`).
- **channels.yaml** — validated at load (`ChannelConfigError` in the central
  catcher).
- **instruments.yaml** — `_load_instruments` (`engine.py:1733-1740`) hard-subscripts
  `entry["type"]` / `entry["name"]`. This raises `KeyError` during ENGINE STARTUP
  (the function builds the InstrumentConfig list at boot), so a missing field aborts
  startup = fail-closed. It is NOT a runtime-during-operation gap. (A friendlier
  `InstrumentConfigError` wrapper would improve the message, but the failure mode is
  already correct; not actionable as a robustness defect.)

---

## COVERAGE-TRACED (seams/paths actually walked, as convergence evidence)

- scheduler persist→DataBroker→SafetyBroker ordering + throttle asymmetry
  (`scheduler.py:343-414`).
- engine Keithley command dispatch → SafetyManager → driver
  (`engine.py:156-205`; `safety_manager.py:289-311,472,521-560`).
- ZMQ REP serve loop + handler envelope (`zmq_bridge.py:439-585`).
- ZMQ subprocess context/socket/thread lifecycle (`zmq_subprocess.py:68-272`).
- command JSON trust boundary / non-finite rejection (`zmq_bridge.py:28-62`).
- calibration import/export path-taking commands (`engine.py:1202-1256`).
- unsafe-deserialization grep across `src/cryodaq/` (pickle/eval/exec/yaml.load) — none.
- yaml.safe_load confirmed on every config read.
- secret-redaction filter install (`logging_setup.py:117-140`) + `_secrets.py`.
- telegram/escalation/periodic_report session + subscription lifecycle.
- reporting soffice subprocess timeout/reaping (`generator.py:271-302`).
- interlock load-time action validation (`interlock.py:202-301,382,472`).
- the 5 config loaders' load-vs-runtime field access + central `*ConfigError`
  catcher (`engine.py:3845-3860`).
- diffs of all 8 fix commits read in full.

## REJECTED (verified false / non-actionable — do not re-litigate)

- "zmq_subprocess leaks ctx/sockets on a thread-startup exception" — FALSE. try/finally
  joins threads + `ctx.term()` (`zmq_subprocess.py:258-271`); per-socket finally-close.
- "generator orphans the soffice subprocess on a non-Timeout exception" — FALSE.
  `subprocess.run` is synchronous and reaps the child; a spawn-time OSError means no
  child exists. Timeout path kills+reaps then returns None.
- "telegram TCPConnector / ClientSession leak if ClientSession() init raises" —
  NON-ACTIONABLE. Setup-time-only, constructor does no I/O, raises only on bad args;
  not an operational leak.
- "telegram_commands / periodic_report leak the broker subscription on a start()
  exception" — NON-ACTIONABLE. Bounded in-memory broker queue, one-shot init; an
  init failure aborts notifier startup. Not an OS resource leak. (Consistent with the
  prior rounds' disposition of bounded in-memory items.)
- "instruments.yaml hard-subscript is a fail-open runtime gap" — MISLABELED.
  `entry["type"]/["name"]` is read at engine startup; a missing field aborts boot =
  fail-closed, not a runtime gap.
- "SafetyBroker can receive a reading not yet persisted (persistence-first violation)"
  — FALSE for the documented invariant. The invariant is scoped to DataBroker;
  SafetyBroker is intentionally fed the full unthrottled stream so safety never
  starves.
- "calibration_curve_import path is an unsafe-deserialization / RCE surface" — FALSE.
  Parsed as data (json/.340/.cof), no exec/pickle; loopback-bound command surface.

---

## Worst-severity summary (for parent)

**Converged: nothing CRIT/HIGH/MED actionable.** Single LOW: stale "не найден" log
message at `engine.py:2107` orphaned by the d206297 missing-file→raise change
(`alarm_config.py:102-106`) — message-only, behavior is correct fail-closed. All
cross-module seams, the command/control trust boundary, error-path releases, the 8
just-fixed areas, and the 5 config loaders verified sound under this angle.
