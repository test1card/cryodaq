# Verify (amend cycle) — Batch 07 — ZMQ bridge/subprocess/safety + etalon

Codex gpt-5.5 high, READ-ONLY. 11 findings. 5 fixed (test-only), 6 DEFERRED (all need a src
change — injectable timeouts / engine seam / warning-helper refactor). The CRITICAL
timeout-inversion + shutdown-during-timeout stay deferred (untouched).

## FIXED (test-only)
- **F4 `test_zmq_safety.py` test_serve_loop_sends_reply_on_serialization_error** — a plain
  `object()` serializes via `json.dumps(default=str)` so the serialization-error fallback NEVER
  ran; test only asserted `first` is a dict. Now uses `_TrulyUnserializable` (raises in
  __str__/__repr__) → json.dumps throws → asserts fallback `{"ok":False,"error":"serialization
  error"}` + next request still replies ok. Teeth confirmed.
- **F5 `test_zmq_safety.py` test_serve_loop_handles_cancelled_error** — was non-falsifiable
  (`except TimeoutError: pass`, no assert). Investigated prod: CancelledError send is best-effort
  (`try socket.send() except Exception: pass`) — NO guaranteed reply. Corrected to contract: if a
  reply arrives assert ok=False+"error"; timeout/socket-error is within contract. (honest, not a
  false strengthening.)
- **F6 `test_vacuum_guard.py` test_alarm_message_contains_factual_data_only** — removed the
  `or "мбар"` escape-hatch; now asserts `event.channels` ⊇ {VSP63D_1/pressure, Т12}, `event.values`
  == 5e-2/245.0 (approx), formatted values in message. Teeth confirmed.
- **F8 `test_zmq_subprocess.py` test_launcher_poll_checks_is_healthy** — source-grep → real
  `LauncherWindow._poll_bridge_data(fake_self)`: alive-but-hung → shutdown()+start(); dead →
  start() only.
- **F9 `test_zmq_bridge.py` test_slow_commands_set_*** — dropped brittle private `_SLOW_COMMANDS`
  membership; assert only `_timeout_for(cmd) == HANDLER_TIMEOUT_SLOW_S` behavior.

## DEFERRED (need src change — added to TEST_SWEEP_STATUS ledger item 8)
- **F7 inner-timeouts-wired** — `_LOG_GET_TIMEOUT_S`/`_EXPERIMENT_STATUS_TIMEOUT_S` feed
  `asyncio.wait_for` inside engine command handlers; behavioral exercise needs a live engine+storage
  or an injectable seam. Constant-existence check retained (tautology acknowledged).
- **F1/F2 (threading) + F10/F11 (heartbeat/PUB-SUB)** — real-timeout wall-clock flakes: depend on
  the hardcoded 35s REQ timeout / 5s heartbeat / slow-joiner deadlines. Deterministic fix needs
  src-injectable timeouts/intervals. These are the fix-pass "adequate-slack/NOT-A-BUG" class.
- **F3 overflow-counter** — warning emission is a closure inside `zmq_bridge_main` with no seam;
  current drain-loop reliably opens warning slots but full determinism needs a src warning-emit helper.

Independently re-verified: 52 pass (5 files, -m "not ollama") + ruff-clean. ZMQ timeout CRITICAL
(deferred ledger item 1) untouched.
