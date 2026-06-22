# Batch 21 — tier 1 — launcher/web/logging/zmq-bind/tools (92 tests, 12 files)

Codex gpt-5.5 high, read-only. 0 CRIT / 3 HIGH / 10 MED / 4 LOW. 4 files clean.

## HIGH
- test_web_dashboard.py:37 `test_api_log_returns_entries` — patches stale
  cryodaq.gui.zmq_client.send_command; prod uses cryodaq.web.server._async_engine_command,
  so the real reply path is never exercised; asserts only "entries" exists. Fix: patch
  _async_engine_command, assert {"cmd":"log_get","limit":5} + exact entries.
- test_launcher_signals.py:124/137 `..._skips_restart_when_shutdown/restart_pending` —
  assert _restart_engine NOT called, but prod doesn't use _restart_engine (uses
  QTimer.singleShot→_start_engine); a real regression passes. Fix: spy QTimer.singleShot +
  _start_engine, assert not called + counters unchanged.

## MED
- test_launcher_engine_stderr.py:56 `..._closes_prior_handlers` — proves removal, not close
  (the Windows file-lock bug). Fix: open stream via handler1, recall, assert stream is None.
- test_logging_setup.py:198 `..._without_pyside_returns_false` — monkeypatches the function
  under test to lambda:False; real import/except never runs. Fix: block PySide6.QtCore via
  sys.modules, call real fn.
- test_diag_zmq_direct_req.py:41/50 — re-derive main() addr logic instead of calling main().
  Fix: patch run, call main([...]), assert run(cmd_addr=..., duration=...).
- test_zmq_bind_recovery.py (module) — no test drives _bind_with_retry through EADDRINUSE.
  Fix: fake socket raising ZMQError(EADDRINUSE) N times then succeed, assert retry+backoff.
- test_zmq_bind_recovery.py:43/57 `..._sets_linger_before_bind` — inspect.getsource order
  grep. Fix: fake socket, assert setsockopt(LINGER,0) before bind at runtime.
- test_launcher_backoff.py:11/37/53 — source-literal/substring checks for exit-code handling,
  restart-pending guard, no-blind-restart. Fix: call _handle_engine_exit with fakes, assert
  modal/give-up/no-timer + counters.

## LOW
- test_launcher_signals.py:26-67 (6 structural tests) — inspect.getsource substring. Fix:
  patch signal.signal/QTimer.singleShot, assert real registration.
- test_launcher_theme_menu.py:16-151 — almost entirely read_text substring. Fix: instantiate
  menu builder w/ Qt mocks, assert QAction/QSettings/env/execv.
- test_web_dashboard.py:29/51 `/api/status`,`/status` — key existence only. Fix: patch
  _async_engine_command, assert exact JSON + computed values.

Clean: test_paths_frozen, test_b1_diagnostics, test_diag_zmq_b1_capture, test_force_phase.
