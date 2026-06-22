# Fix Report — Batch 21

## Finding Table

| File | Line(s) | Sev | What Was Weak | What Changed | Pass Count |
|------|---------|-----|--------------|--------------|-----------|
| test_web_dashboard.py | 37 | HIGH | Patched stale `cryodaq.gui.zmq_client.send_command`; real prod path (`_async_engine_command`) never ran; asserted only `"entries" in data` | Patched `cryodaq.web.server._async_engine_command`; captured received payload; assert exact `{"cmd":"log_get","limit":5}` + exact entries round-trip | 8 passed |
| test_web_dashboard.py | 29 | LOW | Key-existence only (`"uptime" in data`, `"readings" in data`) | Patched `_async_engine_command` with typed fake; assert `uptime` is str (HH:MM:SS), `uptime_s` is numeric, `safety.state == "SAFE_OFF"`, `active_alarms` present | 8 passed |
| test_web_dashboard.py | 51 | LOW | Key-existence only (`"uptime" in data`) | Patched `_async_engine_command`; assert `uptime` is str, `uptime_s >= 0` | 8 passed |
| test_launcher_signals.py | 124/137 | HIGH | Asserted `_restart_engine` NOT called — prod never calls `_restart_engine` (uses `QTimer.singleShot→_start_engine`); real regression passes silently | Patched `cryodaq.launcher.QTimer`; assert `singleShot` not called + `_start_engine` not called when `_shutdown_requested=True` or `_restart_pending=True` | 11 passed |
| test_launcher_signals.py | 26–67 | LOW | 6 structural `inspect.getsource` substring checks | Converted 3 method-level tests to real behavioral calls: `hasattr(mod, "signal")` runtime check; `_do_shutdown` sets flag on real call; `_handle_engine_exit` returns early via QTimer spy; kept 2 `main()` source checks (require QApp); replaced `_shutdown_requested` init check with mock-based behavioral test | 11 passed |
| test_launcher_engine_stderr.py | 56 | MED | Proved removal only (`handler1 not in handlers`); did not prove close (Windows file-lock bug) | Write through handler1 first; assert `handler1.stream is not None`; call helper again; assert `handler1.stream is None` (proves `close()` called, not just detach) | 3 passed |
| test_logging_setup.py | 198 | MED | Monkeypatched the function under test to `lambda:False`; real import/except branch never ran | Block `PySide6.QtCore` and `PySide6` via `sys.modules[...] = None`; reload `logging_setup`; call real `read_debug_mode_from_qsettings()`; assert returns `False` | 13 passed |
| test_diag_zmq_direct_req.py | 41/50 | MED | Re-derived `main()` addr logic in test (re-implementing prod logic); never called `main()` | Patch `run` on module; call `main([])` / `main(["--transport","ipc"])` / `main(["--addr",...])` / `main(["--duration","60"])`; assert `run.assert_called_once_with(cmd_addr=..., duration=...)` | 9 passed |
| test_zmq_bind_recovery.py | module | MED | No test drove `_bind_with_retry` through EADDRINUSE; no retry path covered | Added `test_bind_with_retry_retries_on_eaddrinuse_then_succeeds`: fake socket raises EADDRINUSE twice then succeeds; assert `bind.call_count==3`, `sleep.call_count==2`. Added `test_bind_with_retry_raises_after_max_attempts`: always-fail fake; assert raises after `_BIND_MAX_ATTEMPTS` calls | 8 passed |
| test_zmq_bind_recovery.py | 43/57 | MED | `inspect.getsource` order grep for LINGER position vs `_bind_with_retry` position | Replaced with: (a) `inspect.getsource(ZMQPublisher.start)` positional check on method source (not whole module), plus (b) runtime `_TrackedSocket` that records `setsockopt(LINGER,0)` → `_bind_with_retry` call sequence; assert `call_log[0]=="LINGER_0"` precedes bind | 8 passed |
| test_launcher_backoff.py | 11/37/53 | MED | Source-literal/substring checks on `read_text()`; never called `_handle_engine_exit` | Replaced with 5 behavioral tests calling `LauncherWindow._handle_engine_exit(mock)`: config-error code → `_restart_giving_up=True` + modal called + no timer; max-attempts → give-up modal + no timer; normal crash → `singleShot` called once with positive delay + `_restart_pending=True`; `_restart_pending` guard returns immediately; `_check_engine_health` source check retained for direct-restart regression | 5 passed |
| test_launcher_theme_menu.py | 16–151 | LOW | Almost entirely `read_text` substring | Added `test_restart_gui_calls_os_execv_with_correct_args`: patches `os.execv` on the module; calls `LauncherWindow._restart_gui_with_theme_change(mock)`; asserts `execv` called once with `sys.executable` and args containing `"-m"`, `"cryodaq.launcher"`, `"--mock"` | 15 passed |

## DEFERRED-PRODUCTION-BUG Items

None. All findings addressed. No production bugs discovered during test strengthening.

## Per-File pytest Pass Counts (final run — all files together)

```
tests/test_web_dashboard.py                    8 passed
tests/test_launcher_signals.py                11 passed
tests/test_launcher_engine_stderr.py           3 passed
tests/test_logging_setup.py                   13 passed
tests/tools/test_diag_zmq_direct_req.py        9 passed
tests/test_zmq_bind_recovery.py                8 passed
tests/test_launcher_backoff.py                 5 passed
tests/test_launcher_theme_menu.py             15 passed
TOTAL                                         72 passed, 0 failed
```

Combined run: `72 passed, 28 warnings in 2.00s`

All files ruff-clean (`ruff check` → 0 errors, `ruff format` applied).
