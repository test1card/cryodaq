# Batch 07 — tier 0 — core: ZMQ bridge/subprocess/safety + etalon (96 tests, 9 files)

Codex gpt-5.5 high, read-only. 1 CRIT / 4 HIGH / 9 MED / 5 LOW. 2 files clean.

## CRITICAL — CONFIRMED production regression (architect decision on fix)
- test_zmq_bridge.py:319 `test_subprocess_req_timeout_exceeds_server_slow_ceiling` —
  greps zmq_subprocess.py for "35000" and passes. CONFIRMED BUG by reading production:
  - server slow cap `HANDLER_TIMEOUT_SLOW_S = 55.0` (zmq_bridge.py:41, "H7: bumped from 30 — Ollama cold-start")
  - subprocess REQ timeout `RCVTIMEO/SNDTIMEO = 35000` (zmq_subprocess.py:195-196)
  - The code comment (zmq_subprocess.py:188-194) documents the INTENDED invariant:
    "Server's 30 s ceiling + 5 s slack stays inside the client's 35 s ... timeouts at
    each layer fire in predictable order: server → subprocess → GUI future."
  - Memory (F34 audit, 2026-05-07): verified "helper 25s < server 30s < client 35s".
  - The H7 bump (30→55) raised the server ceiling above the 35s REQ timeout WITHOUT
    updating REQ. Layering is now INVERTED: a slow command (35-55s, e.g. Ollama
    cold-start / experiment_finalize / report-gen) trips the subprocess REQ timeout at
    35s FIRST, emitting cmd_timeout to the GUI while the engine is still working.
  - FIX (architect call): either raise REQ/SND timeout above 55s+slack (e.g. 60s) AND
    the GUI future wait above that, OR lower HANDLER_TIMEOUT_SLOW_S back — depends on the
    real Ollama cold-start budget. Then make the test assert the ordering BEHAVIORALLY /
    via imported constants, not a "35000" grep. **Surfaced to architect — not auto-fixed.**

## HIGH
- test_vacuum_guard.py:229 `test_alarm_message_contains_factual_data_only` — assertions
  inside `if event is not None`; passes if guard never fires. Fix: assert event not None
  + channels/values/substrings + banned-word absence unconditionally.
- test_zmq_bridge_subprocess_threading.py:261 `test_shutdown_during_command_timeout...`
  — sleeps 0.2s, never proves the command thread reached recv_string(). Fix: sync/
  instrument that REQ recv entered, or fake recv_string blocking on event.
- test_zmq_safety.py:97 `test_overflow_counter_exists_in_subprocess` — inspect.getsource
  grep; "dropped_count" matches "dropped_counter" by substring. Fix: fill data queue,
  publish enough, assert structured overflow warning + increasing dropped count.

## MED (mostly source-grep + real-timeout flakiness)
- test_zmq_command_server_supervision.py:129 `..._inner_timeouts_wired` — greps engine.py.
- test_zmq_safety.py:53/114/130/177 — serialization-error / cancelled-error / warning
  handling all grep source or race on mp.Queue flush. Fix: drive _serve_loop / poll via
  fake socket or blocking put.
- test_zmq_subprocess.py:127 `test_launcher_poll_checks_is_healthy` — greps method-call
  strings; doesn't prove restart branches.
- Real-timeout FLAKE risks (35s REQ / 5-6s heartbeat deadlines on slow CI):
  test_zmq_bridge_subprocess_threading.py:154,195; test_zmq_bridge_subscribe.py:63;
  test_zmq_safety.py:14,53. Fix: inject short timeouts/intervals or fake sockets.

## LOW
- test_zmq_bridge.py:155 `..._slow_commands_set...` — membership-only; docstring says 30s,
  prod is 55s. Fix: assert _timeout_for(cmd)==HANDLER_TIMEOUT_SLOW_S.
- test_zmq_safety.py:148 `test_zmq_bridge_is_healthy_initial` — STALE: body asserts NOT
  healthy, contradicts docstring. Fix: rename or start/fake live process.
- test_zmq_subprocess.py:107 `test_heartbeat_interval_value` / :117
  `test_is_healthy_threshold_generous` — grep literals. Fix: assert module
  constant / signature default.

Clean: test_zmq_subprocess_ephemeral, test_etalon_multiline.
