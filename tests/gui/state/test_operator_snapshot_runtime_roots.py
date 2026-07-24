from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.gui.state.operator_snapshot_ingress import start_operator_snapshot_ingress
from cryodaq.operator_snapshot import SnapshotMode

from .test_operator_snapshot_ingress import _Bridge, _events_until, _snapshot


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    return app


class _RuntimeBridge(_Bridge):
    def __init__(self) -> None:
        super().__init__()
        self.shutdown_calls = 0
        self.close_calls = 0

    def start(self) -> None:
        pass

    def shutdown(self) -> None:
        self.shutdown_calls += 1

    def close(self) -> None:
        self.close_calls += 1

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
    lock_releases: list[tuple[int, str]] = []

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
        def __init__(self) -> None:
            self.aboutToQuit = SimpleNamespace(connect=lambda callback: setattr(self, "shutdown_callback", callback))

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

    def record_owner(runtime_bridge, window, *, expected_mode, anchor):
        assert expected_mode is SnapshotMode.LIVE
        owner = real_start(runtime_bridge, window, expected_mode=expected_mode, anchor=anchor)
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
    monkeypatch.setattr(
        module,
        "release_lock_exact",
        lambda fd, name: lock_releases.append((fd, name)),
    )
    monkeypatch.setattr(module, "set_bridge", lambda _bridge: None)
    monkeypatch.setattr("cryodaq.logging_setup.setup_logging", lambda *_args, **_kwargs: None)

    with pytest.raises(SystemExit) as exc:
        module.main()

    assert exc.value.code == 0
    assert len(owners) == 1
    owners[0].stop.assert_called_once_with()
    assert bridge.shutdown_calls == 1
    assert bridge.close_calls == 1
    assert lock_releases == [(7, ".gui.lock")]


def test_standalone_close_request_exits_event_loop_for_hold_settlement(monkeypatch) -> None:
    """One child close request must progress into the root-owned HOLD loop."""

    import cryodaq.gui.app as module

    applications = []
    windows = []
    lock_releases: list[tuple[int, str]] = []

    class Application:
        def __init__(self) -> None:
            self.quit_calls = 0
            self.aboutToQuit = SimpleNamespace(connect=lambda callback: setattr(self, "shutdown_callback", callback))
            applications.append(self)

        def setFont(self, _font) -> None:
            pass

        def setApplicationName(self, _name: str) -> None:
            pass

        def setOrganizationName(self, _name: str) -> None:
            pass

        def quit(self) -> None:
            self.quit_calls += 1

        def exec(self) -> int:
            windows[0].shutdown_request()
            return 0

    class Timer:
        def __init__(self) -> None:
            self.timeout = SimpleNamespace(connect=lambda callback: setattr(self, "callback", callback))

        @staticmethod
        def singleShot(_delay: int, callback) -> None:  # noqa: ANN001, N802
            callback()

        def setInterval(self, _interval: int) -> None:
            pass

        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

    class Window:
        def __init__(self, *, bridge, owner_anchor, shutdown_request) -> None:  # noqa: ANN001
            self.bridge = bridge
            self.shutdown_request = shutdown_request
            owner_anchor(self)
            windows.append(self)

        def show(self) -> None:
            pass

        def render_operator_snapshot(self, _snapshot) -> None:  # noqa: ANN001
            pass

        def invalidate_descriptor_transport(self) -> None:
            pass

        def settle_owned_workers(self) -> bool:
            return True

        def complete_root_shutdown(self) -> None:
            self.root_shutdown_calls = getattr(self, "root_shutdown_calls", 0) + 1

    class Ingress:
        def __init__(self) -> None:
            self.active = True

        def pump(self) -> None:
            pass

        def stop(self) -> None:
            self.active = False

        def invalidate_transport(self) -> None:
            pass

    bridge = _RuntimeBridge()

    def start_ingress(_bridge, _window, *, expected_mode, anchor):  # noqa: ANN001
        assert expected_mode is SnapshotMode.LIVE
        owner = Ingress()
        anchor(owner)
        return owner

    monkeypatch.setattr(module, "QApplication", lambda _argv: Application())
    monkeypatch.setattr(module, "QTimer", Timer)
    monkeypatch.setattr(module, "MainWindow", Window)
    monkeypatch.setattr(module, "ZmqBridge", lambda: bridge)
    monkeypatch.setattr(module, "start_operator_snapshot_ingress", start_ingress)
    monkeypatch.setattr(module, "_load_bundled_fonts", lambda: None)
    monkeypatch.setattr(module.qdarktheme, "setup_theme", lambda **_kwargs: None)
    monkeypatch.setattr(module, "apply_fusion_dark_palette", lambda _app: None)
    monkeypatch.setattr(module, "try_acquire_lock", lambda _name: 7)
    monkeypatch.setattr(
        module,
        "release_lock_exact",
        lambda fd, name: lock_releases.append((fd, name)),
    )
    monkeypatch.setattr(module, "set_bridge", lambda _bridge: None)
    monkeypatch.setattr("cryodaq.logging_setup.setup_logging", lambda *_args, **_kwargs: None)

    with pytest.raises(SystemExit) as exc:
        module.main()

    assert exc.value.code == 0
    assert len(applications) == 1
    assert applications[0].quit_calls == 1
    assert bridge.shutdown_calls == 1
    assert bridge.close_calls == 1
    assert windows[0].root_shutdown_calls == 1
    assert lock_releases == [(7, ".gui.lock")]
