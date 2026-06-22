# Batch 07 — Fix Report

Date: 2026-06-22  
Files touched: test_zmq_bridge.py, test_zmq_command_server_supervision.py, test_zmq_safety.py, test_zmq_subprocess.py, test_vacuum_guard.py  
No src/ changes.

---

## Per-Finding Table

| # | Severity | Test | Status | Action |
|---|----------|------|--------|--------|
| 1 | CRIT | test_zmq_bridge.py:319 `test_subprocess_req_timeout_exceeds_server_slow_ceiling` | **DEFERRED-PRODUCTION-BUG** | Real inversion: server slow cap 55s > subprocess REQ 35s. Test currently passes via source grep. Left exactly as-is per instructions. Architect fix required: raise REQ/SND above 55s+slack OR lower HANDLER_TIMEOUT_SLOW_S. |
| 2 | HIGH | test_vacuum_guard.py:229 `test_alarm_message_contains_factual_data_only` | **FIXED** | Removed `if event is not None:` guard. Added pre-condition asserts: `guard.state == ARMED` after tick 1, `guard.state == FIRED` after tick 2, `event is not None` unconditional, plus `event.level == "CRITICAL"`. |
| 3 | HIGH | test_zmq_bridge_subprocess_threading.py:261 `test_shutdown_during_command_timeout` | **DEFERRED** | Requires src/ instrumentation to prove cmd thread entered recv_string(). Cannot inject fake socket into zmq_bridge_main without src/ change. Test still passes as-is (behavioral shutdown assertion is valid). |
| 4 | HIGH | test_zmq_safety.py:97 `test_overflow_counter_exists_in_subprocess` | **FIXED** | Replaced source grep with behavioral test `test_overflow_counter_emits_warning_on_queue_full`. Floods tiny queue (maxsize=20) with no-sleep publisher; waits 3s for 100+ drops to accumulate; then drains one item at a time in 1ms cycles so subprocess can insert warning on drop 101+. Verified reliable across 3 consecutive full-suite runs. |
| 5 | MED | test_zmq_command_server_supervision.py:129 `test_engine_commands_keep_inner_timeouts_wired` | **FIXED** | Replaced file-read + source grep with `importlib.import_module("cryodaq.engine")` + `hasattr` + positive-value assertions on `_LOG_GET_TIMEOUT_S` and `_EXPERIMENT_STATUS_TIMEOUT_S`. Removed unused `Path` import. |
| 6 | MED | test_zmq_safety.py:53 `test_serve_loop_sends_reply_on_serialization_error` | **FIXED** | Replaced source grep with async behavioral test. Handler returns `{"ok": True, "bad": object()}` (non-serializable). Asserts server sends a dict reply AND is still serving on the next command (REP not wedged). |
| 7 | MED | test_zmq_safety.py:114 `test_serve_loop_handles_cancelled_error` | **FIXED** | Replaced source grep with async behavioral test. Starts slow handler (sleep 60s), waits for handler_entered event, stops server, asserts client receives error reply (not silence/hang). CancelledError path exercised at the ZMQCommandServer level. |
| 8 | MED | test_zmq_safety.py:130 `test_zmq_bridge_is_healthy_initial` | **FIXED** | Renamed (docstring fix) + added explicit `is_alive()=False` pre-assert. Production: unstarted bridge has `_process=None` → `is_alive()=False` → `is_healthy()=False`. Old docstring claimed "returns True right after start (grace period)" — that was wrong; the test body was always correct. |
| 9 | MED | test_zmq_bridge_subprocess_threading.py:154 `test_cmd_timeout_emits_warning` | **NOT-A-BUG** | 40s deadline already accommodates 35s REQ RCVTIMEO + 5s slack. Not flaky. |
| 10 | MED | test_zmq_bridge_subprocess_threading.py:195 `test_cmd_socket_recovers_after_timeout` | **NOT-A-BUG** | 40s deadline already accommodates 35s REQ RCVTIMEO. Not flaky. |
| 11 | MED | test_zmq_bridge_subscribe.py:63 `test_bridge_subprocess_receives_published_readings` | **NOT-A-BUG** | 2s deadline for ≥3 readings at 100ms interval is sound. Not flaky. |
| 12 | MED | test_zmq_safety.py:14,53 heartbeat flake risk | **NOT-A-BUG** | 6s window for 5s HEARTBEAT_INTERVAL has 1s slack; adequate for CI. |
| 13 | LOW | test_zmq_bridge.py:155 `test_slow_commands_set_covers_experiment_lifecycle` | **FIXED** | Added `assert _timeout_for({"cmd": cmd}) == HANDLER_TIMEOUT_SLOW_S` for every checked command. Now also asserts the routing function produces the correct timeout, not just set membership. |
| 14 | LOW | test_zmq_subprocess.py:107 `test_heartbeat_interval_value` | **FIXED** | Replaced source grep for `"HEARTBEAT_INTERVAL = 5.0"` with behavioral test `test_heartbeat_interval_reasonable`. Starts a real bridge, asserts first heartbeat arrives within 10s AND within 15s elapsed (proves interval not unreasonably large). HEARTBEAT_INTERVAL is a local var inside zmq_bridge_main — cannot import it directly without src/ change. |
| 15 | LOW | test_zmq_subprocess.py:117 `test_is_healthy_threshold_generous` | **FIXED** | Replaced source grep for `"30.0"` with behavioral test. Directly sets `bridge._last_heartbeat` to 5s ago (not stale), 31s ago (stale), 20s ago (not stale with default 30s threshold). Verifies the contract, not the literal. |

---

## Files Changed

| File | Changes |
|------|---------|
| `tests/core/test_zmq_bridge.py` | LOW-13: added `_timeout_for` behavioral assertion per command |
| `tests/core/test_zmq_command_server_supervision.py` | MED-5: replaced file-read grep with importlib + hasattr + value check; removed unused `Path` import |
| `tests/core/test_zmq_safety.py` | HIGH-4, MED-6, MED-7, MED-8: four tests rewritten; added `asyncio`, `pytest` imports |
| `tests/core/test_zmq_subprocess.py` | LOW-14, LOW-15: two source-grep tests replaced with behavioral tests |
| `tests/core/test_vacuum_guard.py` | HIGH-2: unconditional assertions + state pre-conditions + level check |

---

## Verification

```
pytest tests/core/test_zmq_bridge.py tests/core/test_zmq_bridge_subprocess_threading.py \
       tests/core/test_zmq_bridge_subscribe.py tests/core/test_zmq_command_server_supervision.py \
       tests/core/test_zmq_safety.py tests/core/test_zmq_subprocess.py tests/core/test_vacuum_guard.py \
       -q --no-header
```
**58 passed in 109.73s** (3 consecutive full-suite runs of test_zmq_safety.py all green)

```
ruff check <touched files>
```
**All checks passed**

---

## DEFERRED-PRODUCTION-BUG (CRITICAL)

**test_zmq_bridge.py:319 `test_subprocess_req_timeout_exceeds_server_slow_ceiling`**

- Production invariant INVERTED: `HANDLER_TIMEOUT_SLOW_S = 55.0` (server) > subprocess REQ `RCVTIMEO = 35000 ms` (35s)
- Layering should be: server → subprocess → GUI future, but 55s server cap > 35s REQ means a slow command (Ollama cold-start, experiment_finalize) trips subprocess REQ first at 35s, emitting `cmd_timeout` to GUI while engine is still working.
- Test left exactly as-is (passes via source grep for "35000").
- Fix requires architect decision: raise REQ/SND to ≥60s AND `_CMD_REPLY_TIMEOUT_S` above that, OR lower `HANDLER_TIMEOUT_SLOW_S` back toward 30s.
- Touch nothing in src/.
