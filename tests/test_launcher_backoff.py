"""Verify launcher exit-code handling and exponential backoff (Phase 2b H.3)."""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


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
    # Backoff is exercised through an explicit non-actuating replay process.
    # Removing that explicit mode makes this fixture fail closed as live or
    # ambiguous acquisition authority.
    w._engine_external = False
    w._mock = False
    w._engine_unsettled_incarnation = None
    # A MagicMock answers every attribute, so this one has to be said out loud: a launcher
    # that has not dispatched a shutdown has NO worker, and leaving it auto-vivified made
    # the fixture claim one that was permanently "still running".
    w._engine_shutdown_worker = None
    w._replay_source = Path("replay.db")
    w._engine_instance_id = None
    w._engine_shutdown_capability = None
    w._engine_shutdown_request_id = None
    w._engine_shutdown_transport_identity = None
    w._engine_shutdown_receipt = None
    w._restart_attempts = restart_attempts
    w._max_restart_attempts = max_restart_attempts
    w._restart_backoff_s = restart_backoff_s if restart_backoff_s is not None else [3, 10, 30, 60, 120]
    w._restart_giving_up = False
    w._config_error_modal_shown = config_error_modal_shown
    w._tray_only = True  # avoid _engine_label.setText branch
    w._last_restart_time = 0.0
    w._runtime_callbacks_open = True
    w._runtime_callback_epoch = 1
    w._restart_generation = 0
    w._replay_session_verified = False
    w._bridge = MagicMock()

    # Fake engine proc that reports the given returncode.
    if returncode is not None:
        proc = MagicMock()
        proc.poll.return_value = returncode
        w._engine_proc = proc
    else:
        w._engine_proc = None

    return w


def _make_assistant_launcher_mock() -> MagicMock:
    """Return the exact mutable state used by assistant restart scheduling."""
    w = MagicMock()
    w._runtime_callbacks_open = True
    w._runtime_callback_epoch = 1
    w._shutdown_requested = False
    w._assistant_enabled = True
    w._assistant_periodic_requested = False
    w._assistant_proc = None
    w._assistant_shutdown_path = None
    w._assistant_shutdown_authority = None
    w._assistant_soak_duplicate_owner = None
    w._assistant_unsettled_start_failure = None
    w._assistant_restart_attempts = 0
    w._assistant_last_restart_time = 0.0
    w._assistant_restart_pending = False
    w._assistant_restart_generation = 0
    w._restart_backoff_s = [3, 10, 30]
    w._soak_artifact_capability = None
    w._tray = None
    return w


def test_owned_config_error_exit_refuses_restart_without_latching_an_unsettled_incarnation():
    """Exit code 2 still refuses to restart, and no longer blocks launcher exit.

    Retrying a configuration error would re-enter the identical failure, so the
    reviewed config-error path keeps its refusal, records the reason, and tells
    the operator which files to fix. What it must NOT do any more is latch
    ``_engine_unsettled_incarnation``: that latch is also read by
    ``_stop_engine``, so latching it here trapped the operator inside a
    launcher that would not quit, over an engine that had provably exited.

    ``_engine_proc`` is a process *handle*, not HOLD evidence. Its clearing
    here follows the reviewed crash path, which settles the crashed child's
    readers first and refuses to advance if that settlement fails.
    """
    from cryodaq.engine import ENGINE_CONFIG_ERROR_EXIT_CODE
    from cryodaq.launcher import LauncherWindow

    w = _make_launcher_mock(returncode=ENGINE_CONFIG_ERROR_EXIT_CODE)
    w._replay_source = None
    w._engine_instance_id = "a" * 32
    w._engine_shutdown_capability = "b" * 64

    with patch("cryodaq.launcher.QTimer") as mock_qtimer:
        LauncherWindow._handle_engine_exit(w)

    assert w._engine_unsettled_incarnation is None
    assert w._engine_proc is None
    # The incarnation is retired here too. No restart is SCHEDULED after a configuration
    # error, but the modal tells the operator to fix config/*.yaml and press the restart
    # button, and that button reaches the same spawn preflight -- which refuses while the
    # dead incarnation's identity is still published.
    assert w._engine_instance_id is None
    assert w._engine_shutdown_capability is None
    assert w._restart_giving_up is True
    assert w._config_error_modal_shown is True
    mock_qtimer.singleShot.assert_not_called()
    assert w._restart_attempts == 0


def test_owned_live_observed_exit_latches_permanent_hold_before_reaping():
    """Process death is not a receipt that descendant or USB I/O settled."""
    from cryodaq.launcher import LauncherWindow

    w = _make_launcher_mock(returncode=1, restart_attempts=50)
    w._replay_source = None
    w._engine_instance_id = "a" * 32
    w._engine_shutdown_capability = "b" * 64

    process = w._engine_proc
    with patch("cryodaq.launcher.QTimer") as mock_qtimer:
        with patch("cryodaq.launcher.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            LauncherWindow._handle_engine_exit(w)
            assert w._engine_proc is process
            state = w._engine_reader_settlement_state
            assert state["done"].wait(1.0)
            mock_qtimer.singleShot.call_args.args[1]()

    assert w._engine_unsettled_incarnation == ("a" * 32, 1)
    assert w._restart_giving_up is True
    assert w._restart_pending is False
    assert w._restart_attempts == 50
    assert w._engine_proc is None
    mock_qtimer.singleShot.assert_called_once()
    w._start_engine.assert_not_called()


def test_ambiguous_live_missing_handle_never_authorizes_replacement():
    """Missing process and authority fields make a live-mode loss less knowable, not safer."""
    from cryodaq.launcher import LauncherWindow

    w = _make_launcher_mock(returncode=None, restart_attempts=7)
    w._replay_source = None
    w._engine_proc = None
    w._engine_instance_id = None
    w._engine_shutdown_capability = None

    with patch("cryodaq.launcher.QTimer") as mock_qtimer:
        with patch("cryodaq.launcher.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            LauncherWindow._handle_engine_exit(w)

    assert w._engine_unsettled_incarnation == ("<unknown>", None)
    assert w._restart_giving_up is True
    assert w._restart_pending is False
    assert w._restart_attempts == 7
    mock_qtimer.singleShot.assert_not_called()
    w._start_engine.assert_not_called()


def test_explicit_mock_observed_exit_keeps_bounded_restart_backoff():
    """Explicit mock is non-actuating, so unattended recovery remains useful."""
    from cryodaq.launcher import LauncherWindow

    w = _make_launcher_mock(returncode=1, restart_attempts=50)
    w._replay_source = None
    w._mock = True
    w._engine_instance_id = "a" * 32
    w._engine_shutdown_capability = "b" * 64

    with patch("cryodaq.launcher.QTimer") as mock_qtimer:
        with patch("cryodaq.launcher.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            LauncherWindow._handle_engine_exit(w)

    assert w._engine_unsettled_incarnation is None
    assert w._restart_giving_up is False
    assert w._restart_pending is True
    mock_qtimer.singleShot.assert_called_once()
    assert mock_qtimer.singleShot.call_args[0][0] == 120 * 1000


def test_missing_owned_process_handle_latches_hold_before_invalidation() -> None:
    from cryodaq.launcher import LauncherWindow

    w = _make_launcher_mock(returncode=None)
    w._replay_source = None
    w._engine_instance_id = "a" * 32
    w._engine_shutdown_capability = "b" * 64
    w._engine_shutdown_request_id = "c" * 32
    receipt = {"retained": "evidence"}
    w._engine_shutdown_receipt = receipt
    events: list[str] = []
    w._invalidate_engine_producer.side_effect = lambda: events.append("invalidate")
    w._show_engine_down_banner.side_effect = lambda _message: events.append("banner")

    with patch("cryodaq.launcher.QTimer") as mock_qtimer:
        LauncherWindow._handle_engine_exit(w)

    assert w._engine_unsettled_incarnation == ("a" * 32, None)
    assert w._restart_giving_up is True
    assert events == ["invalidate", "banner"]
    assert w._engine_instance_id == "a" * 32
    assert w._engine_shutdown_capability == "b" * 64
    assert w._engine_shutdown_request_id == "c" * 32
    assert w._engine_shutdown_receipt is receipt
    assert w._restart_attempts == 0
    mock_qtimer.singleShot.assert_not_called()


def test_retryable_exit_invalidation_failure_latches_audible_hold_before_reader_settlement() -> None:
    """Authority invalidation failure cannot bypass HOLD or discard the crashed owner."""
    from cryodaq.launcher import LauncherWindow

    w = _make_launcher_mock(returncode=1)
    w._replay_session_id = "c" * 32
    process = w._engine_proc
    events: list[str] = []
    banner = MagicMock()
    w._engine_down_banner = banner

    def _fail_invalidation() -> None:
        events.append("invalidate")
        raise RuntimeError("producer authority remained live")

    def _show_hold(message: str) -> None:
        LauncherWindow._show_engine_down_banner(w, message)
        events.append("banner")

    w._invalidate_engine_producer.side_effect = _fail_invalidation
    w._start_engine_down_alarm.side_effect = lambda: events.append("alarm")
    w._show_engine_down_banner.side_effect = _show_hold
    w._close_engine_stderr_stream.side_effect = lambda: events.append("readers")

    with patch("cryodaq.launcher.QTimer") as mock_qtimer:
        LauncherWindow._handle_engine_exit(w)

    assert events == ["invalidate", "alarm", "banner", "readers"]
    assert w._restart_giving_up is True
    assert w._restart_pending is False
    assert w._engine_proc is process
    assert w._replay_session_verified is False
    banner.show.assert_called_once_with()
    w._data_timer.start.assert_called_once_with()
    w._health_timer.start.assert_called_once_with()
    w._bridge.shutdown.assert_not_called()
    w._bridge.start.assert_not_called()
    w._start_engine.assert_not_called()
    mock_qtimer.singleShot.assert_not_called()


def test_live_invalidation_failure_cannot_be_cleared_by_manual_restart() -> None:
    """A failed live-source invalidation keeps manual replacement impossible."""
    from cryodaq.launcher import LauncherWindow

    w = _make_launcher_mock(returncode=9)
    w._replay_source = None
    w._engine_instance_id = "a" * 32
    w._engine_shutdown_capability = "b" * 64
    w._invalidate_engine_producer.side_effect = RuntimeError("producer authority remained live")

    LauncherWindow._handle_engine_exit(w)

    assert w._engine_unsettled_incarnation == ("a" * 32, 9)
    with pytest.raises(RuntimeError, match="manual restart remains in HOLD"):
        LauncherWindow._restart_engine(w)

    w._start_engine.assert_not_called()
    w._bridge.start.assert_not_called()
    assert w._invalidate_engine_producer.call_count == 1


def test_clean_pre_spawn_live_restart_recovery_stays_operator_retryable() -> None:
    """A settled old child plus recovered bridge cleanup is not an unknown live loss."""
    from cryodaq.launcher import LauncherWindow

    w = _make_launcher_mock(returncode=None)
    w._replay_source = None
    w._mock = False
    w._engine_proc = None
    w._engine_instance_id = None
    w._engine_shutdown_capability = None
    w._engine_shutdown_request_id = None
    w._engine_shutdown_transport_identity = None
    w._engine_shutdown_receipt = None
    w._stop_engine = MagicMock()
    w._bridge.shutdown.side_effect = [RuntimeError("first bridge shutdown failed"), None, None]

    with patch("cryodaq.launcher.QTimer") as mock_qtimer, patch("cryodaq.launcher.time.sleep"):
        LauncherWindow._restart_engine(w)

        assert w._engine_unsettled_incarnation is None
        assert w._restart_giving_up is True
        assert w._restart_pending is False
        w._start_engine.assert_not_called()
        w._bridge.start.assert_not_called()
        mock_qtimer.singleShot.assert_not_called()

        # The first attempt settled the commanded stop and bridge cleanup. The
        # operator may explicitly retry; no unknown incarnation was invented.
        LauncherWindow._restart_engine(w)

    w._start_engine.assert_called_once_with()
    w._bridge.start.assert_called_once_with()
    assert w._bridge.shutdown.call_count == 3
    assert w._engine_unsettled_incarnation is None
    assert w._restart_giving_up is False


def test_live_hold_reader_settlement_returns_before_blocked_reader_close() -> None:
    """The Qt health callback must not join terminal-child readers inline."""
    from cryodaq.launcher import LauncherWindow

    w = _make_launcher_mock(returncode=9)
    w._replay_source = None
    w._mock = False
    w._engine_instance_id = "a" * 32
    w._engine_shutdown_capability = "b" * 64
    w._engine_reader_settlement_state = None
    process = w._engine_proc
    close_started = threading.Event()
    release_close = threading.Event()
    callback_returned = threading.Event()
    callback_failures: list[BaseException] = []

    def _blocked_close() -> None:
        close_started.set()
        if not release_close.wait(2.0):
            raise RuntimeError("test did not release reader settlement")

    def _invoke_health_callback() -> None:
        try:
            LauncherWindow._handle_engine_exit(w)
        except BaseException as exc:  # the test must release the blocker before reporting
            callback_failures.append(exc)
        finally:
            callback_returned.set()

    w._close_engine_stderr_stream.side_effect = _blocked_close
    callback_thread = threading.Thread(target=_invoke_health_callback, daemon=True)
    try:
        with patch("cryodaq.launcher.QTimer") as mock_qtimer:
            callback_thread.start()
            assert close_started.wait(1.0), "the production reader-close side effect must run"
            returned_while_close_blocked = callback_returned.wait(0.25)
            handle_retained_while_close_blocked = w._engine_proc is process
            release_close.set()
            callback_thread.join(timeout=1.0)

            state = getattr(w, "_engine_reader_settlement_state", None)
            if type(state) is dict:
                assert state["done"].wait(1.0)
                mock_qtimer.singleShot.call_args.args[1]()
    finally:
        release_close.set()
        callback_thread.join(timeout=1.0)

    assert callback_failures == []
    assert returned_while_close_blocked, "the Qt callback waited for the reader close"
    assert handle_retained_while_close_blocked
    assert w._engine_proc is None
    assert w._engine_unsettled_incarnation == ("a" * 32, 9)
    assert w._restart_giving_up is True
    w._close_engine_stderr_stream.assert_called_once_with()
    w._start_engine.assert_not_called()
    w._bridge.start.assert_not_called()


def test_retryable_exit_reader_settlement_failure_retains_owner_and_blocks_restart() -> None:
    """Reader settlement runs after visible HOLD and cannot become an optimistic retry."""
    from cryodaq.launcher import LauncherWindow

    w = _make_launcher_mock(returncode=1)
    w._replay_session_id = "d" * 32
    process = w._engine_proc
    events: list[str] = []
    banner = MagicMock()
    w._engine_down_banner = banner

    def _show_hold(message: str) -> None:
        LauncherWindow._show_engine_down_banner(w, message)
        events.append("banner")

    def _fail_reader_settlement() -> None:
        events.append("readers")
        raise RuntimeError("stderr reader remained alive")

    w._invalidate_engine_producer.side_effect = lambda: events.append("invalidate")
    w._start_engine_down_alarm.side_effect = lambda: events.append("alarm")
    w._show_engine_down_banner.side_effect = _show_hold
    w._close_engine_stderr_stream.side_effect = _fail_reader_settlement

    with patch("cryodaq.launcher.QTimer") as mock_qtimer:
        LauncherWindow._handle_engine_exit(w)

    assert events[:4] == ["invalidate", "alarm", "banner", "readers"]
    assert events[4:] == ["alarm", "banner"]
    assert w._engine_unsettled_incarnation == ("d" * 32, 1)
    assert w._restart_giving_up is True
    assert w._restart_pending is False
    assert w._engine_proc is process
    assert w._replay_session_verified is False
    assert banner.show.call_count == 2
    w._bridge.shutdown.assert_not_called()
    w._bridge.start.assert_not_called()
    w._start_engine.assert_not_called()
    mock_qtimer.singleShot.assert_not_called()


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


def test_observed_exit_without_worker_evidence_reaches_hold_without_backoff():
    """Health polls must not consume backoff before missing worker evidence reaches HOLD."""
    from cryodaq.launcher import LauncherWindow

    class _PendingWorker:
        def __init__(self) -> None:
            self.finished = False

        def isFinished(self) -> bool:  # noqa: N802 -- Qt API spelling
            return self.finished

    w = _make_launcher_mock(returncode=1, restart_attempts=0)
    w._replay_source = None
    w._engine_instance_id = "a" * 32
    w._engine_shutdown_capability = "b" * 64
    worker = _PendingWorker()
    w._engine_shutdown_worker = worker
    w._stop_engine = lambda: LauncherWindow._stop_engine(w)

    with (
        patch("cryodaq.launcher.QTimer") as mock_qtimer,
        patch("cryodaq.launcher.time") as mock_time,
    ):
        mock_time.monotonic.return_value = 0.0
        LauncherWindow._handle_engine_exit(w)
        LauncherWindow._handle_engine_exit(w)

        assert w._restart_attempts == 0
        assert w._restart_pending is False
        mock_qtimer.singleShot.assert_not_called()

        worker.finished = True
        LauncherWindow._handle_engine_exit(w)

    assert w._restart_attempts == 0
    assert w._restart_pending is False
    assert w._restart_giving_up is True
    assert w._engine_shutdown_worker is worker
    assert getattr(w, "_engine_shutdown_unreadable_evidence_worker", None) is worker
    mock_qtimer.singleShot.assert_not_called()


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


def test_stale_restart_shot_cannot_clear_a_later_live_source_hold():
    """A replay timer admitted earlier has no authority over a later HOLD."""
    from cryodaq.launcher import LauncherWindow

    w = _make_launcher_mock(returncode=1)
    with patch("cryodaq.launcher.QTimer") as mock_qtimer:
        with patch("cryodaq.launcher.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            LauncherWindow._handle_engine_exit(w)

    scheduled = mock_qtimer.singleShot.call_args.args[1]
    w._replay_source = None
    w._engine_unsettled_incarnation = ("live-owner", 17)
    w._restart_giving_up = True
    scheduled()

    w._start_engine.assert_not_called()
    w._bridge.shutdown.assert_not_called()
    assert w._engine_unsettled_incarnation == ("live-owner", 17)
    assert w._restart_giving_up is True
    assert w._restart_pending is True


def test_stale_restart_shot_noops_after_manual_restart():
    """F2 (Phase A gate, HIGH): if the operator manually restarts (which
    resets _restart_pending=False) before the scheduled singleShot fires, the
    stale shot must no-op — NOT call _start_engine and misclassify the fresh
    engine as external, leaving it alive at shutdown."""
    from cryodaq.launcher import LauncherWindow

    w = _make_launcher_mock(returncode=1, restart_attempts=0)

    with patch("cryodaq.launcher.QTimer") as mock_qtimer:
        with patch("cryodaq.launcher.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            LauncherWindow._handle_engine_exit(w)

    assert w._restart_pending is True
    do_restart = mock_qtimer.singleShot.call_args[0][1]

    # Operator manually restarts meanwhile — resets _restart_pending.
    w._restart_pending = False

    # The stale singleShot now fires.
    do_restart()

    w._start_engine.assert_not_called()
    assert w._restart_pending is False, "manual restart's state must not be clobbered"


def test_restart_shot_fires_when_still_pending():
    """Sanity: the F2 guard must not break the normal (non-stale) restart."""
    from cryodaq.launcher import LauncherWindow

    w = _make_launcher_mock(returncode=1, restart_attempts=0)

    with patch("cryodaq.launcher.QTimer") as mock_qtimer:
        with patch("cryodaq.launcher.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            LauncherWindow._handle_engine_exit(w)

    do_restart = mock_qtimer.singleShot.call_args[0][1]
    do_restart()

    w._start_engine.assert_called_once_with()
    assert w._restart_pending is False


def test_stale_restart_generation_cannot_consume_a_new_crash_restart() -> None:
    """Timer A cannot clear or start the replacement owned by crash B."""
    from cryodaq.launcher import LauncherWindow

    w = _make_launcher_mock(returncode=1)
    events: list[str] = []
    w._invalidate_engine_producer.side_effect = lambda: events.append("invalidate")
    w._bridge.shutdown.side_effect = lambda: events.append("bridge.shutdown")
    w._start_engine.side_effect = lambda: events.append("start_engine")
    w._bridge.start.side_effect = lambda: events.append("bridge.start")

    with patch("cryodaq.launcher.QTimer") as mock_qtimer:
        with patch("cryodaq.launcher.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            LauncherWindow._handle_engine_exit(w)
            timer_a = mock_qtimer.singleShot.call_args_list[-1].args[1]

            # A manual recovery supersedes A, then that replacement crashes.
            w._restart_pending = False
            LauncherWindow._advance_restart_generation(w)
            process_b = MagicMock()
            process_b.poll.return_value = 1
            w._engine_proc = process_b
            LauncherWindow._handle_engine_exit(w)
            timer_b = mock_qtimer.singleShot.call_args_list[-1].args[1]

            events.clear()
            timer_a()
            assert events == []
            assert w._restart_pending is True

            timer_b()

    assert events == ["invalidate", "bridge.shutdown", "start_engine", "bridge.start"]
    assert w._restart_pending is False


def test_scheduled_restart_shutdown_latch_after_bridge_retirement_blocks_engine_spawn() -> None:
    """A signal during old-bridge settlement must win over the queued restart."""
    from cryodaq.launcher import LauncherWindow

    w = _make_launcher_mock(returncode=1)
    injected = False

    def _retire_bridge_and_latch_shutdown() -> None:
        nonlocal injected
        injected = True
        w._shutdown_requested = True

    w._bridge.shutdown.side_effect = _retire_bridge_and_latch_shutdown

    with (
        patch("cryodaq.launcher.QTimer") as mock_qtimer,
        patch("cryodaq.launcher.time") as mock_time,
        patch.object(LauncherWindow, "_do_shutdown", return_value=True) as finish_shutdown,
    ):
        mock_time.monotonic.return_value = 0.0
        LauncherWindow._handle_engine_exit(w)
        callback = mock_qtimer.singleShot.call_args_list[-1].args[1]
        callback()

    assert injected is True
    w._start_engine.assert_not_called()
    w._bridge.start.assert_not_called()
    finish_shutdown.assert_called_once_with(w)


def test_scheduled_restart_shutdown_latch_during_engine_start_settles_without_bridge_attach() -> None:
    """A replacement child cannot acquire transport after shutdown latches."""
    from cryodaq.launcher import LauncherWindow

    w = _make_launcher_mock(returncode=1)
    injected = False

    def _start_engine_and_latch_shutdown() -> None:
        nonlocal injected
        injected = True
        w._shutdown_requested = True

    w._start_engine.side_effect = _start_engine_and_latch_shutdown

    with (
        patch("cryodaq.launcher.QTimer") as mock_qtimer,
        patch("cryodaq.launcher.time") as mock_time,
        patch.object(LauncherWindow, "_do_shutdown", return_value=True) as finish_shutdown,
    ):
        mock_time.monotonic.return_value = 0.0
        LauncherWindow._handle_engine_exit(w)
        callback = mock_qtimer.singleShot.call_args_list[-1].args[1]
        callback()

    assert injected is True
    w._bridge.start.assert_not_called()
    finish_shutdown.assert_called_once_with(w)


def test_manual_restart_shutdown_latch_during_pause_blocks_engine_spawn() -> None:
    """A signal during the restart pause must win before replacement spawn."""
    from cryodaq.launcher import LauncherWindow

    w = _make_launcher_mock(returncode=None)
    injected = False

    def _pause_and_latch_shutdown(_seconds: float) -> None:
        nonlocal injected
        injected = True
        w._shutdown_requested = True

    with (
        patch("cryodaq.launcher.time.sleep", side_effect=_pause_and_latch_shutdown),
        patch.object(LauncherWindow, "_do_shutdown", return_value=True) as finish_shutdown,
    ):
        LauncherWindow._restart_engine(w)

    assert injected is True
    w._start_engine.assert_not_called()
    w._bridge.start.assert_not_called()
    finish_shutdown.assert_called_once_with(w)


def test_manual_restart_shutdown_latch_during_engine_start_settles_without_bridge_attach() -> None:
    """A manually spawned replacement cannot attach after shutdown latches."""
    from cryodaq.launcher import LauncherWindow

    w = _make_launcher_mock(returncode=None)
    injected = False

    def _start_engine_and_latch_shutdown() -> None:
        nonlocal injected
        injected = True
        w._shutdown_requested = True

    w._start_engine.side_effect = _start_engine_and_latch_shutdown

    with (
        patch("cryodaq.launcher.time.sleep"),
        patch.object(LauncherWindow, "_do_shutdown", return_value=True) as finish_shutdown,
    ):
        LauncherWindow._restart_engine(w)

    assert injected is True
    w._bridge.start.assert_not_called()
    finish_shutdown.assert_called_once_with(w)


def test_stale_assistant_restart_generation_cannot_consume_new_slot() -> None:
    """Assistant timer A cannot clear or start the replacement owned by timer B."""
    from cryodaq.launcher import LauncherWindow

    w = _make_assistant_launcher_mock()

    with patch("cryodaq.launcher.QTimer") as mock_qtimer:
        with patch("cryodaq.launcher.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            LauncherWindow._check_assistant_health(w)
            timer_a = mock_qtimer.singleShot.call_args_list[-1].args[1]

            # A successful manual intervention supersedes A. The assistant then
            # fails again and reserves a distinct restart generation B.
            w._assistant_restart_pending = False
            LauncherWindow._advance_assistant_restart_generation(w)
            LauncherWindow._check_assistant_health(w)
            timer_b = mock_qtimer.singleShot.call_args_list[-1].args[1]

            timer_a()
            w._start_assistant.assert_not_called()
            assert w._assistant_restart_pending is True

            timer_b()

    w._start_assistant.assert_called_once_with()
    assert w._assistant_restart_pending is False


def test_shutdown_owned_clean_exit_stays_with_exact_shutdown_path():
    """The health callback never reclassifies an exit during exact shutdown."""
    from cryodaq.launcher import LauncherWindow

    w = _make_launcher_mock(returncode=0)
    w._replay_source = None
    w._engine_instance_id = "a" * 32
    w._engine_shutdown_capability = "b" * 64
    w._shutdown_requested = True

    with patch("cryodaq.launcher.QTimer") as mock_qtimer:
        LauncherWindow._handle_engine_exit(w)

    assert w._engine_unsettled_incarnation is None
    assert w._engine_proc is not None
    assert w._restart_giving_up is False
    mock_qtimer.singleShot.assert_not_called()


def test_shutdown_invalidates_scheduled_assistant_restart_callback() -> None:
    """A callback retained by Qt cannot resurrect the assistant after quiesce."""
    from cryodaq.launcher import LauncherWindow

    w = _make_assistant_launcher_mock()

    with patch("cryodaq.launcher.QTimer") as mock_qtimer:
        LauncherWindow._check_assistant_health(w)
        scheduled = mock_qtimer.singleShot.call_args.args[1]

    LauncherWindow._revoke_runtime_callbacks(w)
    LauncherWindow._advance_assistant_restart_generation(w)
    w._assistant_restart_pending = False
    w._shutdown_requested = True

    scheduled()

    w._start_assistant.assert_not_called()
    assert w._assistant_restart_pending is False


def test_replay_readiness_failure_settles_child_before_scheduling_next_generation() -> None:
    """A live but unverified replay child is settled before any retry exists."""
    from cryodaq.launcher import LauncherWindow

    w = _make_launcher_mock(returncode=1)
    events: list[str] = []
    live_child = MagicMock()
    live_child.poll.return_value = None

    def _failed_start() -> None:
        events.append("start_engine")
        w._engine_proc = live_child
        raise RuntimeError("readiness receipt rejected")

    def _settle_child() -> None:
        events.append("stop_engine")
        assert w._engine_proc is live_child
        w._engine_proc = None

    w._start_engine.side_effect = _failed_start
    w._stop_engine.side_effect = _settle_child
    w._bridge.shutdown.side_effect = lambda: events.append("bridge.shutdown")
    w._bridge.start.side_effect = lambda: events.append("bridge.start")
    w._invalidate_engine_producer.side_effect = lambda: events.append("invalidate")

    with patch("cryodaq.launcher.QTimer") as mock_qtimer:
        with patch("cryodaq.launcher.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            LauncherWindow._handle_engine_exit(w)
            first_timer = mock_qtimer.singleShot.call_args_list[-1].args[1]

            events.clear()
            first_timer()

    assert events[:5] == [
        "invalidate",
        "bridge.shutdown",
        "start_engine",
        "stop_engine",
        "bridge.shutdown",
    ]
    assert "bridge.start" not in events
    assert w._engine_proc is None
    assert w._replay_session_verified is False
    assert w._restart_pending is True
    assert mock_qtimer.singleShot.call_count == 2


def test_replay_readiness_failure_with_unsettled_child_latches_hold_without_retry() -> None:
    """Failed settlement cannot be converted into an optimistic restart."""
    from cryodaq.launcher import LauncherWindow

    w = _make_launcher_mock(returncode=1)
    w._start_engine.side_effect = RuntimeError("readiness receipt rejected")
    w._stop_engine.side_effect = RuntimeError("child remained alive")

    with patch("cryodaq.launcher.QTimer") as mock_qtimer:
        with patch("cryodaq.launcher.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            LauncherWindow._handle_engine_exit(w)
            first_timer = mock_qtimer.singleShot.call_args_list[-1].args[1]

            with pytest.raises(
                RuntimeError,
                match="readiness failed and ownership remains unsettled",
            ):
                first_timer()

    assert w._restart_giving_up is True
    assert w._replay_session_verified is False
    assert w._restart_pending is False
    assert mock_qtimer.singleShot.call_count == 1
    w._bridge.start.assert_not_called()
    w._show_engine_down_banner.assert_called()


def test_manual_live_restart_startup_failure_settles_new_child_before_backoff() -> None:
    """Manual restart cannot abandon a post-spawn child behind a stopped bridge."""
    from cryodaq.launcher import LauncherWindow

    w = _make_launcher_mock(returncode=None)
    w._replay_source = None
    # This registered historical node exercises cleanup/backoff, not live-source
    # restart authority. Keep its replacement explicitly non-actuating.
    w._mock = True
    live_child = MagicMock()
    live_child.poll.return_value = None
    stop_calls = 0

    def _stop_engine() -> None:
        nonlocal stop_calls
        stop_calls += 1
        if stop_calls == 2:
            assert w._engine_proc is live_child
            w._engine_proc = None
            w._engine_instance_id = None
            w._engine_shutdown_capability = None
            w._engine_shutdown_request_id = None
            w._engine_shutdown_transport_identity = None
            w._engine_shutdown_receipt = None

    def _failed_start() -> None:
        w._engine_proc = live_child
        w._engine_instance_id = "a" * 32
        w._engine_shutdown_capability = "b" * 64
        raise RuntimeError("readiness receipt rejected")

    w._stop_engine.side_effect = _stop_engine
    w._start_engine.side_effect = _failed_start

    with patch("cryodaq.launcher.QTimer") as mock_qtimer:
        with patch("cryodaq.launcher.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            LauncherWindow._restart_engine(w)

    assert stop_calls == 2
    assert w._engine_proc is None
    assert w._engine_instance_id is None
    assert w._engine_shutdown_capability is None
    assert w._engine_shutdown_transport_identity is None
    assert w._restart_pending is True
    assert mock_qtimer.singleShot.call_count == 1
    w._data_timer.start.assert_not_called()
    w._health_timer.start.assert_not_called()


def test_manual_restart_old_child_stop_failure_latches_visible_hold_and_rearms_supervision() -> None:
    """Failure to settle the old owner cannot become a silent stopped-timer state."""
    from cryodaq.launcher import LauncherWindow

    w = _make_launcher_mock(returncode=None)
    w._replay_source = None
    w._stop_engine.side_effect = RuntimeError("old child lacks exact settlement")

    with patch("cryodaq.launcher.time"):
        LauncherWindow._restart_engine(w)

    assert w._restart_giving_up is True
    assert w._restart_pending is False
    w._show_engine_down_banner.assert_called()
    w._start_engine.assert_not_called()
    w._bridge.shutdown.assert_not_called()
    w._bridge.start.assert_not_called()
    w._data_timer.start.assert_called()
    w._health_timer.start.assert_called()


def test_manual_replay_bridge_attach_failure_settles_new_child_before_backoff() -> None:
    """Manual replay restart owns bridge attachment in the same transaction."""
    from cryodaq.launcher import LauncherWindow

    w = _make_launcher_mock(returncode=None)
    live_child = MagicMock()
    live_child.poll.return_value = None
    stop_calls = 0

    def _stop_engine() -> None:
        nonlocal stop_calls
        stop_calls += 1
        if stop_calls == 2:
            assert w._engine_proc is live_child
            w._engine_proc = None
            w._replay_session_verified = False

    def _start_engine() -> None:
        w._engine_proc = live_child
        w._replay_session_verified = True

    w._stop_engine.side_effect = _stop_engine
    w._start_engine.side_effect = _start_engine
    w._bridge.start.side_effect = RuntimeError("bridge process did not start")

    with patch("cryodaq.launcher.QTimer") as mock_qtimer:
        with patch("cryodaq.launcher.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            LauncherWindow._restart_engine(w)

    assert stop_calls == 2
    assert w._engine_proc is None
    assert w._replay_session_verified is False
    assert w._restart_pending is True
    assert w._restart_giving_up is False
    assert mock_qtimer.singleShot.call_count == 1
    w._data_timer.start.assert_not_called()
    w._health_timer.start.assert_not_called()


def test_replay_bridge_attach_failure_settles_verified_child_before_retry() -> None:
    """A verified child without a live bridge is not a healthy restart."""
    from cryodaq.launcher import LauncherWindow

    w = _make_launcher_mock(returncode=1)
    live_child = MagicMock()
    live_child.poll.return_value = None

    def _start_engine() -> None:
        w._engine_proc = live_child
        w._replay_session_verified = True

    def _settle_child() -> None:
        assert w._engine_proc is live_child
        w._engine_proc = None
        w._replay_session_verified = False

    w._start_engine.side_effect = _start_engine
    w._stop_engine.side_effect = _settle_child
    w._bridge.start.side_effect = RuntimeError("bridge process did not start")

    with patch("cryodaq.launcher.QTimer") as mock_qtimer:
        with patch("cryodaq.launcher.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            LauncherWindow._handle_engine_exit(w)
            restart = mock_qtimer.singleShot.call_args_list[-1].args[1]
            restart()

    assert w._engine_proc is None
    assert w._replay_session_verified is False
    assert w._restart_pending is True
    assert w._restart_giving_up is False
    assert mock_qtimer.singleShot.call_count == 2
    w._stop_engine.assert_called_once_with()


def test_start_engine_has_no_readiness_bypass_and_health_does_not_call_it_directly():
    """No caller can bypass readiness, and health delegates restart scheduling.

    The only auto-restart path is via _handle_engine_exit → QTimer.singleShot.
    """
    import inspect

    from cryodaq import launcher as mod

    assert list(inspect.signature(mod.LauncherWindow._start_engine).parameters) == ["self"]
    src = inspect.getsource(mod.LauncherWindow._check_engine_health)
    assert "_start_engine(" not in src, (
        "_check_engine_health still contains direct _start_engine call — should delegate to _handle_engine_exit"
    )
