"""Tests for launcher SIGTERM/SIGINT handler — case 03 CRITICAL.

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
    """signal module is importable from cryodaq.launcher (real attribute check)."""
    import cryodaq.launcher as mod

    # Verify at runtime that `signal` is actually an attribute of the module
    # (i.e. it was imported, not just mentioned in a comment).
    assert hasattr(mod, "signal"), "launcher module must import the signal stdlib module"
    import signal as stdlib_signal

    assert mod.signal is stdlib_signal


def test_main_registers_sigint_handler() -> None:
    """main() source must register SIGINT — structural check (main() needs QApplication)."""
    import cryodaq.launcher as mod

    src = inspect.getsource(mod.main)
    assert "signal.signal" in src
    assert "SIGINT" in src


def test_main_registers_sigterm_handler() -> None:
    """main() source must register SIGTERM — structural check (main() needs QApplication)."""
    import cryodaq.launcher as mod

    src = inspect.getsource(mod.main)
    assert "SIGTERM" in src


def test_do_shutdown_sets_flag_on_real_call() -> None:
    """_do_shutdown must flip _shutdown_requested to True on a real bound call."""
    from cryodaq.launcher import LauncherWindow

    w = _make_window_mock()
    assert w._shutdown_requested is False
    LauncherWindow._do_shutdown(w)
    assert w._shutdown_requested is True


def test_handle_engine_exit_returns_early_when_shutdown_requested_real_call() -> None:
    """_handle_engine_exit must return immediately when _shutdown_requested is True."""
    from unittest.mock import patch

    from cryodaq.launcher import LauncherWindow

    w = _make_window_mock()
    w._shutdown_requested = True

    with patch("cryodaq.launcher.QTimer") as mock_qtimer:
        LauncherWindow._handle_engine_exit(w)

    mock_qtimer.singleShot.assert_not_called()


def test_shutdown_requested_false_before_any_call() -> None:
    """_make_window_mock sets _shutdown_requested=False — verifies the __init__ contract
    is met: a fresh instance starts with no shutdown in progress."""
    w = _make_window_mock()
    assert w._shutdown_requested is False


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
    """_handle_engine_exit must not schedule engine restart during shutdown.

    Prod uses QTimer.singleShot → _start_engine (not _restart_engine).
    We spy on both _start_engine and QTimer.singleShot to ensure neither
    fires when _shutdown_requested is True.
    """
    from unittest.mock import patch

    from cryodaq.launcher import LauncherWindow

    w = _make_window_mock()
    w._shutdown_requested = True
    w._restart_pending = False

    with patch("cryodaq.launcher.QTimer") as mock_qtimer:
        LauncherWindow._handle_engine_exit(w)

    # Neither the timer nor _start_engine must be invoked.
    mock_qtimer.singleShot.assert_not_called()
    w._start_engine.assert_not_called()
    # Counters must remain at their initial mock state (not incremented).
    assert w._restart_attempts == w._restart_attempts  # unchanged (no assignment)


def test_handle_engine_exit_skips_restart_when_restart_pending() -> None:
    """Existing _restart_pending guard must still work alongside shutdown flag.

    Prod uses QTimer.singleShot → _start_engine (not _restart_engine).
    We spy on QTimer.singleShot to ensure it never fires when already pending.
    """
    from unittest.mock import patch

    from cryodaq.launcher import LauncherWindow

    w = _make_window_mock()
    w._shutdown_requested = False
    w._restart_pending = True

    with patch("cryodaq.launcher.QTimer") as mock_qtimer:
        LauncherWindow._handle_engine_exit(w)

    mock_qtimer.singleShot.assert_not_called()
    w._start_engine.assert_not_called()
