"""Verify launcher exit-code handling and exponential backoff (Phase 2b H.3)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def _make_launcher_mock(
    *,
    returncode: int | None = 1,
    restart_attempts: int = 0,
    max_restart_attempts: int = 5,
    restart_backoff_s: list | None = None,
    config_error_modal_shown: bool = False,
) -> MagicMock:
    """Return a minimal MagicMock configured as a LauncherWindow substitute."""
    w = MagicMock()
    w._restart_pending = False
    w._shutdown_requested = False
    w._restart_attempts = restart_attempts
    w._max_restart_attempts = max_restart_attempts
    w._restart_backoff_s = restart_backoff_s if restart_backoff_s is not None else [3, 10, 30, 60, 120]
    w._restart_giving_up = False
    w._config_error_modal_shown = config_error_modal_shown
    w._tray_only = True  # avoid _engine_label.setText branch
    w._last_restart_time = 0.0

    # Fake engine proc that reports the given returncode.
    if returncode is not None:
        proc = MagicMock()
        proc.poll.return_value = returncode
        w._engine_proc = proc
    else:
        w._engine_proc = None

    return w


def test_handle_engine_exit_config_error_shows_banner_no_restart():
    """Exit code ENGINE_CONFIG_ERROR_EXIT_CODE must block restart and alarm/banner.

    This proves the exit-code branch runs the REAL production logic:
    _restart_giving_up must be set, the audible/visible engine-down banner is
    shown, and QTimer.singleShot must NOT be called (no auto-restart).
    """
    from cryodaq.engine import ENGINE_CONFIG_ERROR_EXIT_CODE
    from cryodaq.launcher import LauncherWindow

    w = _make_launcher_mock(returncode=ENGINE_CONFIG_ERROR_EXIT_CODE)

    with patch("cryodaq.launcher.QTimer") as mock_qtimer:
        LauncherWindow._handle_engine_exit(w)

    assert w._restart_giving_up is True, "_restart_giving_up must be latched on config error"
    w._show_engine_down_banner.assert_called_once()
    mock_qtimer.singleShot.assert_not_called()
    assert w._restart_attempts == 0, "restart_attempts must not increment on config error"


def test_handle_engine_exit_retries_forever_never_gives_up():
    """A4: past the last backoff slot the launcher must KEEP retrying, capped at 120s.

    No max-attempts surrender — a silently dead overnight acquisition is the
    hazard being designed out. Must schedule a 120s timer, never latch
    _restart_giving_up, and keep the alarm/banner up.
    """
    from cryodaq.launcher import LauncherWindow

    # 50 prior crashes — way past the old max of 5.
    w = _make_launcher_mock(returncode=1, restart_attempts=50)

    with patch("cryodaq.launcher.QTimer") as mock_qtimer:
        with patch("cryodaq.launcher.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            LauncherWindow._handle_engine_exit(w)

    assert w._restart_giving_up is False, "must NEVER give up on ordinary crashes"
    mock_qtimer.singleShot.assert_called_once()
    # Backoff caps at the last slot (120s).
    assert mock_qtimer.singleShot.call_args[0][0] == 120 * 1000
    w._show_engine_down_banner.assert_called_once()
    assert w._restart_pending is True


def test_handle_engine_exit_schedules_backoff_timer_on_normal_crash():
    """Normal crash must schedule a QTimer.singleShot restart, not restart immediately."""
    from cryodaq.launcher import LauncherWindow

    w = _make_launcher_mock(returncode=1, restart_attempts=0)

    with patch("cryodaq.launcher.QTimer") as mock_qtimer:
        with patch("cryodaq.launcher.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            LauncherWindow._handle_engine_exit(w)

    # Must schedule a timer — not call _start_engine directly.
    mock_qtimer.singleShot.assert_called_once()
    timer_delay_ms = mock_qtimer.singleShot.call_args[0][0]
    assert timer_delay_ms > 0, "backoff delay must be positive"
    assert w._restart_pending is True
    assert w._restart_attempts == 1


def test_handle_engine_exit_restart_pending_guard_is_noop():
    """When _restart_pending is True, _handle_engine_exit must return immediately."""
    from cryodaq.launcher import LauncherWindow

    w = _make_launcher_mock(returncode=1)
    w._restart_pending = True

    with patch("cryodaq.launcher.QTimer") as mock_qtimer:
        LauncherWindow._handle_engine_exit(w)

    mock_qtimer.singleShot.assert_not_called()
    # Counters must be unchanged.
    assert w._restart_attempts == 0


def test_check_engine_health_does_not_call_start_engine_directly():
    """_check_engine_health must not contain a direct _start_engine(wait=False) call.

    The only auto-restart path is via _handle_engine_exit → QTimer.singleShot.
    """
    import inspect

    from cryodaq import launcher as mod

    src = inspect.getsource(mod.LauncherWindow._check_engine_health)
    assert "_start_engine(wait=False)" not in src, (
        "_check_engine_health still contains direct _start_engine call — should delegate to _handle_engine_exit"
    )
