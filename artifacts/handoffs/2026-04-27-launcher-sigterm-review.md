# Codex-03 SIGTERM handler — architect review

## Branch

`feat/launcher-sigterm-handler` at `9a8412e`

## What it does

Registers `SIGTERM` and `SIGINT` handlers in `main()` before `app.exec()` so
that OS-level shutdown signals (systemd stop, operator Ctrl+C, OOM kill) invoke
`_do_shutdown()` via `QTimer.singleShot(0, …)` onto the Qt main thread rather
than leaving the engine subprocess running as an orphan. `_do_shutdown()` is
made idempotent via a `_shutdown_requested` flag so double-signals don't
double-kill. `_handle_engine_exit()` checks the same flag so a SIGTERM arriving
mid-watchdog-cycle does not trigger an engine restart storm.

## Files changed

| File | Lines | Change |
|---|---|---|
| `src/cryodaq/launcher.py` | +20 | signal import, `_shutdown_requested` flag, handler registration in `main()`, guards in `_do_shutdown()` and `_handle_engine_exit()` |
| `tests/test_launcher_signals.py` | +147 | 11 new tests (new file) |

## What to review

1. **Signal handler registration order** — handler is registered AFTER
   `LauncherWindow(…)` is fully constructed (line ~1290) but BEFORE `app.exec()`.
   Verify this is the right place vs. earlier startup steps (lock, font load, etc).

2. **Qt thread dispatch** — `QTimer.singleShot(0, window._do_shutdown)` from
   a Python signal handler. This is the standard Python+Qt pattern; verify it's
   acceptable for this codebase's Qt usage (PySide6, not PyQt5).

3. **Shutdown ordering** — `_do_shutdown()` stops timers → bridge → engine
   (`_stop_engine`: SIGTERM → 10s wait → SIGKILL) → asyncio loop → lock release
   → `app.quit()`. Verify this ordering is correct for the lab shutdown sequence.

4. **SIGTERM on Windows** — registration skipped on `win32`; only `SIGINT`
   registered there. Verify this is appropriate given Windows deployment is via
   `install.bat` / tray Exit (not systemd).

5. **Race: SIGTERM during engine startup** — `_shutdown_requested=True` will
   prevent `_handle_engine_exit()` from restarting. But `_start_engine()` may
   still be running when the signal arrives. `_stop_engine()` handles
   `self._engine_proc is None` (no-op). Verify you're comfortable with this
   window.

6. **Exit code** — `sys.exit(app.exec())` still controls final exit code.
   `app.exec()` returns 0 on clean quit. For a SIGTERM, the process exits 0.
   Unix convention for SIGTERM is exit code 128+15=143. Verify 0 is acceptable
   or whether the handler should call `sys.exit(143)` after `_do_shutdown()`.

## Test coverage

| Test | Type | What it verifies |
|---|---|---|
| `test_launcher_imports_signal_module` | Structural | `import signal` present in launcher.py |
| `test_main_registers_sigint_handler` | Structural | `signal.signal(signal.SIGINT, …)` in `main()` |
| `test_main_registers_sigterm_handler` | Structural | `SIGTERM` reference in `main()` |
| `test_do_shutdown_has_idempotent_guard` | Structural | `_shutdown_requested` in `_do_shutdown()` source |
| `test_handle_engine_exit_respects_shutdown_flag` | Structural | `_shutdown_requested` in `_handle_engine_exit()` source |
| `test_shutdown_requested_initialised_false` | Structural | `_shutdown_requested` initialised in `__init__` |
| `test_do_shutdown_sets_shutdown_requested` | Unit | First call sets flag to True |
| `test_do_shutdown_calls_engine_stop_on_first_invocation` | Unit | First call stops bridge + engine |
| `test_do_shutdown_idempotent_second_call_is_noop` | Unit | Second call (double-SIGTERM) is a no-op |
| `test_handle_engine_exit_skips_restart_when_shutdown_requested` | Unit | No restart scheduled during shutdown |
| `test_handle_engine_exit_skips_restart_when_restart_pending` | Unit | Existing `_restart_pending` guard still works |

**Not covered by dev-env tests** (hardware-dependent):
- Actual SIGTERM delivery to a running `app.exec()` loop
- `QTimer.singleShot` correctly dispatching `_do_shutdown` in a live event loop
- 10s grace timeout + SIGKILL path with a live unresponsive engine subprocess

These must be verified on the lab Ubuntu PC before v0.34.0 tag.

## What NOT in this branch

- No engine-side changes (graceful shutdown via existing ZMQ command path is
  unused by this handler — `_stop_engine()` uses `Popen.terminate()` directly)
- No GUI changes
- No config changes (10s grace timeout is hardcoded in the existing `_stop_engine()`)
- No fix for the Codex-03 HIGH findings (engine auto-restart bridge race,
  external attach without ping) — those are separate decisions

## Merge decision options

- **APPROVE** → merge `feat/launcher-sigterm-handler` to `master`
- **REQUEST CHANGES** → list concerns; CC iterates on this branch
- **REJECT** → would mean Codex-03 CRITICAL spec wrong (unlikely given
  the concrete reproducer: `kill -TERM <launcher-pid>` leaves orphan engine)

## Residual risks

1. **Exit code 0 on SIGTERM** — process exits 0 via `app.quit()`. If systemd
   or the supervisor expects 143, add `sys.exit(128 + signal.SIGTERM)` after
   `_do_shutdown()` in the handler. Architect decision.
2. **10s grace may be short** — engine shutdown involves SQLite WAL flush,
   ZMQ unbind, Keithley OUTPUT_OFF. On a slow lab PC under load, 10s may
   expire. Telemetry from production will indicate if SIGKILL fires routinely.
3. **SIGKILL fallback** — if engine ignores SIGTERM and the 10s expires,
   `_stop_engine()` sends SIGKILL and waits another 5s. If that 5s wait also
   times out, `TimeoutExpired` propagates (Codex-03 MEDIUM: `_do_shutdown()`
   is not fully exception-safe). Not addressed in this branch.
4. **Hardware integration not tested in dev env** — structural and unit tests
   pass; live signal delivery depends on the Qt event loop processing Python
   signals promptly (standard behaviour, but lab verification needed).
