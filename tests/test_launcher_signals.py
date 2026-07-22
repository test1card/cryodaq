"""Launcher signal and retry-safe shutdown state-machine contracts."""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from cryodaq.launcher import LauncherWindow, _ShutdownPhase


class _Loop:
    def __init__(self) -> None:
        self.closed = False
        self.close_calls = 0

    def is_closed(self) -> bool:
        return self.closed

    def close(self) -> None:
        self.close_calls += 1
        self.closed = True


class _Bridge:
    def __init__(self, *, fail_once: bool = False) -> None:
        self.fail_once = fail_once
        self.shutdown_calls = 0
        self.close_calls = 0

    def shutdown(self) -> None:
        self.shutdown_calls += 1
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("bridge still alive")

    def close(self) -> None:
        self.close_calls += 1


def _host(*, bridge: _Bridge | None = None) -> SimpleNamespace:
    events: list[str] = []
    tray = MagicMock(name="tray")
    loop = _Loop()
    app = SimpleNamespace(quit=lambda: events.append("app.quit"))
    host = SimpleNamespace(
        _shutdown_requested=False,
        _restart_pending=True,
        _assistant_restart_pending=True,
        _health_timer=MagicMock(name="health_timer"),
        _data_timer=MagicMock(name="data_timer"),
        _async_timer=MagicMock(name="async_timer"),
        _tray=tray,
        _tray_icon_red=None,
        _tray_icon_yellow=None,
        _stop_engine_down_alarm=lambda: events.append("alarm.stop"),
        _invalidate_descriptor_transport=lambda: events.append("descriptor.invalidate"),
        _snapshot_ingress=None,
        _stop_assistant=lambda: events.append("assistant.stop"),
        _bridge=bridge or _Bridge(),
        _safety_worker=None,
        _stop_engine=lambda: events.append("engine.stop"),
        _soak_artifact_capability=None,
        _soak_bridge_handshake=None,
        _loop=loop,
        _app=app,
        events=events,
    )
    return host


def test_launcher_imports_signal_module() -> None:
    import signal as stdlib_signal

    import cryodaq.launcher as module

    assert module.signal is stdlib_signal


def test_main_registers_sigint_and_sigterm_handlers() -> None:
    import cryodaq.launcher as module

    source = inspect.getsource(module.main)
    assert "signal.signal" in source
    assert "SIGINT" in source
    assert "SIGTERM" in source


def test_shutdown_success_is_monotonic_and_quits_once() -> None:
    host = _host()

    assert LauncherWindow._do_shutdown(host) is True

    assert host._shutdown_requested is True
    assert host._shutdown_phase is _ShutdownPhase.COMPLETE
    assert host._restart_pending is False
    assert host._assistant_restart_pending is False
    assert host._bridge.shutdown_calls == 1
    assert host._bridge.close_calls == 1
    assert host._loop.closed is True
    assert host.events[-1] == "app.quit"
    host._tray.hide.assert_called_once_with()

    assert LauncherWindow._do_shutdown(host) is True
    assert host._bridge.shutdown_calls == 1
    assert host.events.count("app.quit") == 1


def test_incomplete_owner_keeps_app_and_tray_live_then_retries_only_unsettled_owner() -> None:
    bridge = _Bridge(fail_once=True)
    host = _host(bridge=bridge)
    callbacks: list[object] = []

    with patch("cryodaq.launcher.QTimer.singleShot", side_effect=lambda _delay, callback: callbacks.append(callback)):
        assert LauncherWindow._do_shutdown(host) is False

        assert host._shutdown_phase is _ShutdownPhase.RETRY_WAIT
        assert host._loop.closed is False
        assert "app.quit" not in host.events
        host._tray.hide.assert_not_called()
        host._tray.show.assert_called()
        assert len(callbacks) == 1
        assert host.events.count("assistant.stop") == 1
        assert host.events.count("engine.stop") == 1

        callbacks.pop()()

    assert host._shutdown_phase is _ShutdownPhase.COMPLETE
    assert bridge.shutdown_calls == 2
    assert bridge.close_calls == 1
    assert host.events.count("assistant.stop") == 1
    assert host.events.count("engine.stop") == 1
    assert host.events.count("app.quit") == 1


def test_reentrant_shutdown_call_is_coalesced() -> None:
    host = _host()
    LauncherWindow._ensure_shutdown_state(host)
    host._shutdown_attempt_active = True

    assert LauncherWindow._do_shutdown(host) is False
    assert host._bridge.shutdown_calls == 0
    assert host.events == []


def test_handle_engine_exit_skips_restart_when_shutdown_requested() -> None:
    host = _host()
    host._shutdown_requested = True
    host._restart_pending = False
    host._start_engine = MagicMock()

    with patch("cryodaq.launcher.QTimer") as timer:
        LauncherWindow._handle_engine_exit(host)

    timer.singleShot.assert_not_called()
    host._start_engine.assert_not_called()


def test_pending_restart_callback_cannot_respawn_after_shutdown_latch() -> None:
    host = _host()
    host._restart_pending = False
    host._shutdown_requested = False
    host._engine_proc = SimpleNamespace(poll=lambda: 1)
    host._engine_external = False
    host._restart_giving_up = False
    host._restart_attempts = 0
    host._restart_backoff_s = [0]
    host._last_restart_time = 0.0
    host._invalidate_descriptor_transport = MagicMock()
    host._close_engine_stderr_stream = MagicMock()
    host._show_engine_down_banner = MagicMock()
    host._start_engine = MagicMock()
    callbacks: list[object] = []

    with (
        patch("cryodaq.launcher.QTimer.singleShot", side_effect=lambda _delay, callback: callbacks.append(callback)),
        patch("cryodaq.launcher.time.monotonic", return_value=1.0),
    ):
        LauncherWindow._handle_engine_exit(host)
        host._shutdown_requested = True
        callbacks.pop()()

    assert host._restart_pending is False
    host._start_engine.assert_not_called()
