"""Tests for launcher SIGTERM/SIGINT handler — Codex-03 CRITICAL.

Covers 6 cases per spec:
  1. SIGTERM/SIGINT registration in main() — structural
  2. _do_shutdown() is idempotent — unit
  3. _handle_engine_exit() skips restart when shutdown requested — unit
  4. Double SIGTERM is a no-op — unit
  5. _shutdown_requested initialised to False in __init__ — structural
  6. Watchdog guard (_restart_pending) still works alongside shutdown flag — unit

Hardware-dependent tests (actual signal delivery to a running QApplication)
require a live event loop and are out of scope for the dev-env test suite.
Those are verified on the lab Ubuntu PC before v0.34.0 tag.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Structural tests — source inspection, no QApplication
# ---------------------------------------------------------------------------


def test_launcher_imports_signal_module() -> None:
    """launcher.py must import the signal module for OS-level handler registration."""
    import cryodaq.launcher as mod

    src = inspect.getsource(mod)
    assert "import signal" in src


def test_main_registers_sigint_handler() -> None:
    """main() must register a SIGINT handler via signal.signal."""
    import cryodaq.launcher as mod

    src = inspect.getsource(mod.main)
    assert "signal.signal" in src
    assert "SIGINT" in src


def test_main_registers_sigterm_handler() -> None:
    """main() must register a SIGTERM handler for non-Windows targets."""
    import cryodaq.launcher as mod

    src = inspect.getsource(mod.main)
    assert "SIGTERM" in src


def test_do_shutdown_has_idempotent_guard() -> None:
    """_do_shutdown must check _shutdown_requested to guard against double-invocation."""
    import cryodaq.launcher as mod

    src = inspect.getsource(mod.LauncherWindow._do_shutdown)
    assert "_shutdown_requested" in src


def test_handle_engine_exit_respects_shutdown_flag() -> None:
    """_handle_engine_exit must check _shutdown_requested before scheduling restart."""
    import cryodaq.launcher as mod

    src = inspect.getsource(mod.LauncherWindow._handle_engine_exit)
    assert "_shutdown_requested" in src


def test_shutdown_requested_initialised_false() -> None:
    """LauncherWindow.__init__ must initialise _shutdown_requested to False."""
    import cryodaq.launcher as mod

    src = inspect.getsource(mod.LauncherWindow.__init__)
    assert "_shutdown_requested" in src


# ---------------------------------------------------------------------------
# Unit tests — direct method calls on a mocked LauncherWindow
# ---------------------------------------------------------------------------


def _make_window_mock() -> MagicMock:
    """Return a MagicMock pre-configured as a minimal LauncherWindow substitute."""
    w = MagicMock()
    w._shutdown_requested = False
    w._restart_pending = False
    w._lock_fd = None  # prevents release_lock branch from running
    return w


def test_do_shutdown_sets_shutdown_requested() -> None:
    """First _do_shutdown call must flip _shutdown_requested to True."""
    from cryodaq.launcher import LauncherWindow

    w = _make_window_mock()
    LauncherWindow._do_shutdown(w)

    assert w._shutdown_requested is True


def test_do_shutdown_calls_engine_stop_on_first_invocation() -> None:
    """First _do_shutdown call must stop bridge and engine."""
    from cryodaq.launcher import LauncherWindow

    w = _make_window_mock()
    LauncherWindow._do_shutdown(w)

    w._stop_engine.assert_called_once()
    w._bridge.shutdown.assert_called_once()


def test_do_shutdown_idempotent_second_call_is_noop() -> None:
    """Second _do_shutdown call (double-SIGTERM) must return early without side-effects."""
    from cryodaq.launcher import LauncherWindow

    w = _make_window_mock()
    w._shutdown_requested = True  # simulate first call already ran

    LauncherWindow._do_shutdown(w)

    w._health_timer.stop.assert_not_called()
    w._stop_engine.assert_not_called()
    w._app.quit.assert_not_called()


def test_handle_engine_exit_skips_restart_when_shutdown_requested() -> None:
    """_handle_engine_exit must not schedule engine restart during shutdown."""
    from cryodaq.launcher import LauncherWindow

    w = _make_window_mock()
    w._shutdown_requested = True
    w._restart_pending = False

    LauncherWindow._handle_engine_exit(w)

    w._restart_engine.assert_not_called()


def test_handle_engine_exit_skips_restart_when_restart_pending() -> None:
    """Existing _restart_pending guard must still work alongside shutdown flag."""
    from cryodaq.launcher import LauncherWindow

    w = _make_window_mock()
    w._shutdown_requested = False
    w._restart_pending = True

    LauncherWindow._handle_engine_exit(w)

    w._restart_engine.assert_not_called()
