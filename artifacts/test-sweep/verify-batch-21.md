# Verify (amend cycle) — Batch 21 — launcher/web/logging/zmq-bind/tools (FINAL verify batch)

NOTE: Codex usage-limited (resets ~6:14 AM) — reviewed INLINE by Claude, same criteria.

VERDICT: **VERIFY PASS — 0 fix-introduced problems.** The batch-21 FIX work (committed ad4a879) holds.

## Reviewed (all CLEAN — real behavioral coverage)
- **test_web_dashboard.py** — patches the REAL `cryodaq.web.server._async_engine_command` (not the stale
  gui.zmq_client.send_command), asserts exact payload `{"cmd":"log_get","limit":5}` + entries.
- **test_launcher_signals.py** — spies `QTimer.singleShot` + `_start_engine`, asserts neither called on
  shutdown/restart-pending (prod uses singleShot→_start_engine, NOT _restart_engine — the real regression).
- **test_launcher_engine_stderr.py** — proves `handler.close()` (stream is None), not just removal.
- **test_logging_setup.py** — `importlib.reload` to run the real import/except branch (was monkeypatching
  the function-under-test).
- **test_diag_zmq_direct_req.py** — calls the real `main([])` and asserts `run.assert_called_once_with(
  cmd_addr=..., duration=...)` (not re-derived addr logic).
- **test_zmq_bind_recovery.py** — fake socket raises EADDRINUSE twice then succeeds → asserts
  bind.call_count==3 + backoff; non-EADDRINUSE propagates immediately (pytest.raises); LINGER=0 before bind
  at runtime.
- **test_launcher_backoff.py** — calls `LauncherWindow._handle_engine_exit(w)` behaviorally: config-error
  latches _restart_giving_up + modal + no timer; max-attempts give-up; normal crash schedules singleShot.
- **test_launcher_theme_menu.py** — added a behavioral `os.execv` test (patches execv, calls
  `_restart_gui_with_theme_change` as an unbound method on a mock, asserts execv once with -m / cryodaq.launcher
  / --mock).

## Documented limitation (NOT a new defect)
theme_menu still asserts the menu WIRING via source-level (`"_build_settings_menu" in src`) checks, and
launcher_signals / launcher_backoff / zmq_bind retain a couple of supplementary inspect.getsource positional
checks. These are the SAME constraint as the batch-18 launcher deferral (ledger item 10): a full offscreen
`LauncherWindow` can't be constructed test-only because `__init__` acquires file locks / creates a tray /
calls `_start_engine`. The fix added behavioral coverage everywhere it was feasible (execv, singleShot,
_handle_engine_exit, runtime socket); the residual source checks await the same constructable-seam src work.

Independently re-verified: 72 pass (all 8 files, -m "not ollama") + ruff-clean. No fixes needed.
