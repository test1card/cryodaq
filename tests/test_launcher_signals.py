"""Launcher signal and retry-safe shutdown state-machine contracts."""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from cryodaq.launcher import LauncherWindow, _LauncherConstructionHold, _ShutdownPhase


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
        _runtime_callbacks_open=True,
        _runtime_callback_epoch=1,
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
        _invalidate_engine_producer=lambda: events.append("producer.invalidate"),
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


def test_main_registers_sigint_sigterm_and_sigbreak_handlers() -> None:
    import cryodaq.launcher as module

    source = inspect.getsource(module.main)
    assert "signal.signal" in source
    assert "SIGINT" in source
    assert "SIGTERM" in source
    assert "SIGBREAK" in source


def test_main_registers_sigbreak_to_the_shutdown_handler_on_windows(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import cryodaq.launcher as module

    app = MagicMock()
    app.exec.return_value = 0
    window = SimpleNamespace(_do_shutdown=MagicMock())
    registrations: dict[int, object] = {}

    def register(signum: int, handler: object) -> None:
        registrations[signum] = handler

    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr(module.signal, "SIGBREAK", 21, raising=False)
    with (
        patch("sys.argv", ["cryodaq", "--tray", "--mock"]),
        patch("cryodaq.logging_setup.setup_logging"),
        patch("cryodaq.logging_setup.resolve_log_level", return_value="INFO"),
        patch("cryodaq.launcher._consume_soak_bridge_handshake", return_value=None),
        patch("cryodaq.launcher._consume_soak_artifact_capability", return_value=None),
        patch("cryodaq.launcher.QApplication", return_value=app),
        patch("cryodaq.gui.app._load_bundled_fonts"),
        patch("cryodaq.gui.app.apply_fusion_dark_palette"),
        patch("cryodaq.launcher.try_acquire_lock", return_value=73),
        patch("cryodaq.gui.first_run_config.recover_pending_setup"),
        patch("cryodaq.launcher.LauncherWindow", return_value=window),
        patch("cryodaq.launcher.signal.signal", side_effect=register),
        patch("cryodaq.launcher.release_lock_exact"),
    ):
        with pytest.raises(SystemExit) as exited:
            module.main()

        assert exited.value.code == 0
        assert module.signal.SIGINT in registrations
        assert module.signal.SIGBREAK in registrations
        assert module.signal.SIGTERM not in registrations
        assert registrations[module.signal.SIGBREAK] is registrations[module.signal.SIGINT]

        callbacks: list[object] = []
        with (
            caplog.at_level("INFO", logger=module.logger.name),
            patch(
                "cryodaq.launcher.QTimer.singleShot",
                side_effect=lambda _delay, callback: callbacks.append(callback),
            ),
        ):
            registrations[module.signal.SIGBREAK](module.signal.SIGBREAK, None)  # type: ignore[operator]

    assert callbacks == [window._do_shutdown]
    assert "Получен SIGBREAK" in caplog.text


def test_shutdown_success_is_monotonic_and_quits_once() -> None:
    host = _host()
    bridge = host._bridge

    assert LauncherWindow._do_shutdown(host) is True

    assert host._shutdown_requested is True
    assert host._shutdown_phase is _ShutdownPhase.COMPLETE
    assert host._restart_pending is False
    assert host._assistant_restart_pending is False
    assert bridge.shutdown_calls == 1
    assert bridge.close_calls == 1
    assert host._bridge is None
    assert host._loop.closed is True
    assert host.events[-1] == "app.quit"
    host._tray.hide.assert_called_once_with()

    assert LauncherWindow._do_shutdown(host) is True
    assert bridge.shutdown_calls == 1
    assert host.events.count("app.quit") == 1


def test_gui_workers_settle_before_assistant_engine_and_bridge() -> None:
    host = _host()

    class _MainWindow:
        def settle_owned_workers(self) -> bool:
            host.events.append("gui.settle")
            return True

        def complete_root_shutdown(self) -> None:
            host.events.append("gui.complete")

    host._main_window = _MainWindow()
    original_shutdown = host._bridge.shutdown

    def bridge_shutdown() -> None:
        host.events.append("bridge.shutdown")
        original_shutdown()

    host._bridge.shutdown = bridge_shutdown

    assert LauncherWindow._do_shutdown(host) is True
    assert host.events.index("gui.settle") < host.events.index("assistant.stop")
    assert host.events.index("gui.settle") < host.events.index("engine.stop")
    assert host.events.index("gui.settle") < host.events.index("bridge.shutdown")
    assert host.events.index("bridge.shutdown") < host.events.index("gui.complete")
    assert host.events.index("gui.complete") < host.events.index("app.quit")


def test_live_gui_worker_blocks_engine_and_bridge_teardown() -> None:
    host = _host()
    host._main_window = SimpleNamespace(settle_owned_workers=lambda: False)
    callbacks: list[object] = []

    with patch("cryodaq.launcher.QTimer.singleShot", side_effect=lambda _delay, callback: callbacks.append(callback)):
        assert LauncherWindow._do_shutdown(host) is False

    assert "assistant.stop" not in host.events
    assert "engine.stop" not in host.events
    assert host._bridge.shutdown_calls == 0
    assert host._loop.closed is False
    assert len(callbacks) == 1


@pytest.mark.parametrize(
    "phase",
    ["engine", "assistant", "soak_bridge_handshake", "ui", "tray", "data_timer", "health_timer", "status_timer"],
)
def test_construction_failure_transfers_exact_owner_to_hold(phase: str) -> None:
    identity = "a" * 32
    capability = "b" * 64
    host = SimpleNamespace(
        _construction_failure_phase=None,
        _engine_proc=object(),
        _engine_instance_id=identity,
        _engine_shutdown_capability=capability,
        setWindowTitle=MagicMock(),
        show=MagicMock(),
    )

    with (
        patch.object(LauncherWindow, "_do_shutdown", return_value=False) as settle,
        pytest.raises(_LauncherConstructionHold) as raised,
    ):
        LauncherWindow._run_construction_step(
            host,
            phase,
            lambda: (_ for _ in ()).throw(RuntimeError("injected")),
        )

    assert raised.value.window is host
    assert raised.value.phase == phase
    assert host._construction_failure_phase == phase
    assert host._engine_proc is not None
    assert host._engine_instance_id == identity
    assert host._engine_shutdown_capability == capability
    settle.assert_called_once_with(host)
    host.show.assert_called_once_with()


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
    # Only an unowned/external or replay startup may enter backoff. An owned
    # acquisition death is covered separately and must remain in HOLD.
    host._engine_external = True
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
