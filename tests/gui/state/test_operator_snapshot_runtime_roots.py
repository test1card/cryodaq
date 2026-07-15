from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QMainWindow

from cryodaq.gui.state.operator_snapshot_ingress import start_operator_snapshot_ingress
from cryodaq.launcher import LauncherWindow

from .test_operator_snapshot_ingress import _Bridge, _events_until, _snapshot


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    return app


class _RuntimeBridge(_Bridge):
    def start(self) -> None:
        pass

    def shutdown(self) -> None:
        pass

    def poll_readings_with_descriptor(self) -> list[object]:
        return []

    def is_healthy(self) -> bool:
        return True

    def data_flow_stalled(self) -> bool:
        return False


def test_app_main_runs_one_retained_owner_to_real_pod_and_stops_once(qapp, monkeypatch) -> None:
    import cryodaq.gui.app as module

    bridge = _RuntimeBridge()
    bridge.snapshots = [_snapshot(1), _snapshot(2)]
    owners = []
    timers = []

    class Timer:
        def __init__(self) -> None:
            self.timeout = SimpleNamespace(connect=lambda callback: setattr(self, "callback", callback))
            self.stop = MagicMock()
            timers.append(self)

        def setInterval(self, _interval: int) -> None:
            pass

        def start(self) -> None:
            pass

    class Application:
        def setFont(self, _font) -> None:
            pass

        def setApplicationName(self, _name: str) -> None:
            pass

        def setOrganizationName(self, _name: str) -> None:
            pass

        def exec(self) -> int:
            timers[0].callback()
            _events_until(lambda: owners[0].snapshot is not None)
            pod_snapshot = owners[0].parent()._operator_display.snapshot
            assert pod_snapshot is not None and pod_snapshot.cut.revision == 2
            return 0

    real_start = start_operator_snapshot_ingress

    def record_owner(runtime_bridge, window):
        owner = real_start(runtime_bridge, window)
        owner.stop = MagicMock(wraps=owner.stop)
        owners.append(owner)
        return owner

    monkeypatch.setattr(module, "QApplication", lambda _argv: Application())
    monkeypatch.setattr(module, "QTimer", Timer)
    monkeypatch.setattr(module, "ZmqBridge", lambda: bridge)
    monkeypatch.setattr(module, "start_operator_snapshot_ingress", record_owner)
    monkeypatch.setattr(module, "_load_bundled_fonts", lambda: None)
    monkeypatch.setattr(module.qdarktheme, "setup_theme", lambda **_kwargs: None)
    monkeypatch.setattr(module, "apply_fusion_dark_palette", lambda _app: None)
    monkeypatch.setattr(module, "try_acquire_lock", lambda _name: 7)
    monkeypatch.setattr(module, "release_lock", lambda _fd, _name: None)
    monkeypatch.setattr(module, "set_bridge", lambda _bridge: None)
    monkeypatch.setattr(module, "shutdown", lambda: None)
    monkeypatch.setattr("cryodaq.logging_setup.setup_logging", lambda *_args, **_kwargs: None)

    with pytest.raises(SystemExit) as exc:
        module.main()

    assert exc.value.code == 0
    assert len(owners) == 1
    owners[0].stop.assert_called_once_with()


def test_launcher_build_ui_runs_real_pod_newest_cut_and_theme_stop_once(qapp, monkeypatch) -> None:
    bridge = _RuntimeBridge()
    bridge.snapshots = [_snapshot(1), _snapshot(2)]

    class Host(QMainWindow):
        _build_ui = LauncherWindow._build_ui

        def _on_open_web(self) -> None:
            pass

        def _on_restart_engine(self) -> None:
            pass

        def _merge_main_window_menus(self) -> None:
            pass

        def _build_settings_menu(self) -> None:
            pass

    host = Host()
    host._bridge = bridge
    host._replay_source = None
    host._build_ui()
    owner = host._snapshot_ingress
    real_stop = owner.stop
    owner.stop = MagicMock()

    owner.pump()
    _events_until(lambda: host._main_window._operator_display.snapshot is not None)
    assert owner.parent() is host._main_window
    assert host._main_window._operator_display.snapshot.cut.revision == 2

    events: list[str] = []
    owner.stop.side_effect = lambda: (events.append("snapshot.stop"), real_stop())[1]
    host._shutdown_requested = False
    host._stop_assistant = lambda: events.append("assistant")
    host._invalidate_descriptor_transport = lambda: events.append("descriptor")
    bridge.shutdown = lambda: events.append("bridge")
    host._stop_engine = lambda: events.append("engine")
    host._engine_external = True
    host._lock_fd = None
    monkeypatch.setattr(sys, "argv", ["cryodaq-launcher"])
    monkeypatch.setattr("cryodaq.launcher.os.execv", lambda *_args: events.append("exec"))

    LauncherWindow._restart_gui_with_theme_change(host)

    owner.stop.assert_called_once_with()
    assert events == ["snapshot.stop", "assistant", "descriptor", "bridge", "engine", "exec"]
    host.close()
    QCoreApplication.processEvents()


def test_launcher_assistant_stop_failure_reactivates_same_owner_and_real_pod(qapp, monkeypatch) -> None:
    bridge = _RuntimeBridge()
    bridge.snapshots = [_snapshot(1)]

    class Host(QMainWindow):
        _build_ui = LauncherWindow._build_ui

        def _on_open_web(self) -> None:
            pass

        def _on_restart_engine(self) -> None:
            pass

        def _merge_main_window_menus(self) -> None:
            pass

        def _build_settings_menu(self) -> None:
            pass

    host = Host()
    host._bridge = bridge
    host._replay_source = None
    host._build_ui()
    owner = host._snapshot_ingress
    owner.pump()
    _events_until(lambda: host._main_window._operator_display.snapshot is not None)

    events: list[str] = []
    real_stop = owner.stop
    real_start = owner.start
    owner.stop = MagicMock(side_effect=lambda: (events.append("snapshot.stop"), real_stop())[1])
    owner.start = MagicMock(side_effect=lambda: (events.append("snapshot.start"), real_start())[1])
    host._shutdown_requested = False
    host._stop_assistant = lambda: (events.append("assistant"), (_ for _ in ()).throw(RuntimeError("child survived")))[
        1
    ]
    host._invalidate_descriptor_transport = lambda: events.append("descriptor")
    bridge.shutdown = lambda: events.append("bridge")
    host._stop_engine = lambda: events.append("engine")
    host._engine_external = True
    host._lock_fd = None
    execv = MagicMock()
    monkeypatch.setattr("cryodaq.launcher.os.execv", execv)

    with pytest.raises(RuntimeError, match="child survived"):
        LauncherWindow._restart_gui_with_theme_change(host)

    assert host._shutdown_requested is False
    assert owner.active is True
    assert events == ["snapshot.stop", "assistant", "snapshot.start"]
    execv.assert_not_called()
    bridge.snapshots = [_snapshot(2)]
    owner.pump()
    _events_until(lambda: host._main_window._operator_display.snapshot.cut.revision == 2)
    assert owner.parent() is host._main_window
    owner.stop()
    host.close()
    QCoreApplication.processEvents()
