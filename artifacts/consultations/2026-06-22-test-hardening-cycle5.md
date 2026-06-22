# Test-hardening Codex review — cycle 5 (independent re-verify)

Date: 2026-06-22. Model: gpt-5.5 high reasoning, read-only.
Context: prior 4 cycles (Jun 19-20) claimed convergence but verdicts were never
persisted (died with the cleared conversation). This is the independent 5th pass.

## Codex raw findings

CRITICAL: none.

- **HIGH** | tests/drivers/test_keithley_safety.py:46 | claims slew-rate-limited
  normal regulation | uses `mock=True`; `read_channels()` returns via the mock
  branch before the P=const/slew limiter runs; asserts only `_last_v` finite &
  nonnegative | fix: drive `mock=False` + fake transport, record `source.levelv`
  writes across cycles, assert each delta <= MAX_DELTA_V_PER_STEP.
- **MED** | tests/core/test_scheduler.py:235 | claims drain timeout forces
  cancellation | sets unused `sched._DRAIN_TIMEOUT_S`; production uses
  `_drain_timeout_s`. Driver doesn't hang; test only proves `stop()` returned |
  fix: `Scheduler(..., drain_timeout_s=0.01)` with a read that blocks past
  timeout; assert cancellation path ran + disconnect attempted.
- **MED** | tests/drivers/test_gpib_bus_lock.py:69 | claims IFC recovery removed |
  checks only absent private `_send_ifc`; production has public
  `GPIBTransport.send_ifc()` and scheduler calls it | fix: delete/rename to match
  current design, OR assert real Level-2 recovery invokes public `send_ifc()`.
- **MED** | tests/drivers/test_visa_executors.py:14 | claims GPIB VISA calls avoid
  default executor | greps class source strings; doesn't prove open/query/write
  pass the dedicated executor to run_in_executor | fix: spy event-loop
  run_in_executor under fake non-mock resource, assert executor arg ==
  transport._get_executor().
- **LOW** | tests/core/test_safety_manager.py:645 | `_fault_log_callback` shielded
  | reads source strings | fix: remove / rely on adjacent behavioral cancellation
  tests.
- **LOW** | tests/drivers/test_keithley_safety.py:110 | single-channel
  emergency_off resets only that channel | asserts only smua resets; never proves
  smub preserved | fix: seed both _last_v, call emergency_off("smua"), assert smua
  == 0 and smub unchanged.
- **LOW** | tests/storage/test_multiline_persistence.py:101 | SQLiteWriter
  channel-agnostic | inspect.getsource instead of behavior | fix: delete or
  runtime write/query with MultiLine channels.
- **LOW** | tests/core/test_interlock.py:387 | interlocks config pattern matches
  detector channel names | hard-codes regex, tests Python `re` not the real
  config/InterlockEngine | fix: load real config/YAML fixture through
  InterlockEngine, publish matching Reading, assert interlock trips.

Codex found NONE remaining in: WAL, persistence-first ordering, SafetyBroker
overflow, RateEstimator numeric, Thyracont fallback, Alarm Engine v2 tick/phase.

## CC verification status — ALL 8 fixed, all verified

Independent baseline check first: CI run #342 on HEAD e723654 is green (gh), and a
local full-suite run of pre-edit master exited 0 — so the prior loop's "3247 passed"
baseline is real, not just self-reported.

All 8 findings verified genuine against production code (not by-design false
positives), then fixed:

1. **HIGH** keithley slew normal-regulation → rewritten to non-mock fake transport;
   asserts each consecutive levelv step delta <= MAX_DELTA_V_PER_STEP over 5 cycles
   and that the ramp moves. (prod clamp keithley_2604b.py:191-205)
2. **LOW** emergency_off single-channel → non-mock; seeds both channels, asserts smua
   zeroed+inactive, smub preserved, only smua gets OUTPUT_OFF write. (prod :298-317)
3. **MED** scheduler drain timeout → real drain_timeout_s ctor param + BlockingDriver
   (30s read); asserts forced cancel (CancelledError) + disconnect. (prod :507-518)
4. **MED** gpib send_ifc → stale false claim removed; now a real recovery-integration
   test drives _gpib_poll_loop to the Level-2 escalation and spies the transport,
   asserting send_ifc() + clear_bus() are actually awaited. (prod scheduler.py:289-303)
5. **MED** visa executors → inspect.getsource replaced with a run_in_executor spy
   proving query AND write pass transport._get_executor(). (prod gpib.py:203,228)
6. **LOW** safety_manager shield grep → deleted; behavioral coverage already exists
   (test_fault_log_callback_survives_outer_cancellation:583, runs_even_if_publish_fails).
7. **LOW** multiline channel-agnostic → grep replaced with runtime mixed-batch
   write+query asserting all channels persist. (prod sqlite_writer.py:355)
8. **LOW** interlock detector pattern → standalone `re` replaced with real
   InterlockEngine: Latin 'T12' stays ARMED, Cyrillic 'Т12 ...' trips once.
   (prod start-anchored .match() interlock.py:107)

### Codex re-verification (gpt-5.5 high, read-only)
First pass: 7/8 GENUINE; #4 STILL-WEAK because the replacement still grepped
scheduler source. Fixed #4 → now a behavioral recovery-integration test (passes in
0.05s). All 8 now GENUINE.

### Local verification
- ruff: clean on all 7 touched files.
- 7 touched test files: 100 passed (after fixing a visa-test fake-resource attr).
- gpib file incl. new recovery test: 9 passed in 0.05s.
- Full post-edit suite: see commit message / CI run.

### Lesson for next time
The prior 4 cycles' Codex verdicts were NEVER persisted — they died with the cleared
conversation, leaving only MORNING_TRIAGE.md prose. This artifact is the durable
record this cycle. Persist consultant output to artifacts/ per ORCHESTRATION.md.
