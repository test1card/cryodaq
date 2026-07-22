from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.gui.state.operator_snapshot_ingress import start_operator_snapshot_ingress

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
