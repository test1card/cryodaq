"""Standalone GUI entry preserves the launcher mock provenance."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from cryodaq.gui import app as gui_app
from cryodaq.operator_snapshot import SnapshotMode


class _Signal:
    def connect(self, _callback) -> None:  # noqa: ANN001
        return None


@pytest.mark.parametrize(
    ("argv", "mock_env", "expected_mock"),
    [
        (["cryodaq-gui", "--mock"], None, True),
        (["cryodaq-gui"], "1", True),
        (["cryodaq-gui"], "true", True),
        (["cryodaq-gui"], "TRUE", True),
        (["cryodaq-gui"], None, False),
    ],
)
def test_standalone_gui_entry_passes_existing_mock_provenance_to_shell(
    monkeypatch,
    argv: list[str],
    mock_env: str | None,
    expected_mock: bool,
) -> None:
    captured: list[bool] = []
    ingress_modes: list[SnapshotMode] = []
    fake_app = MagicMock()
    fake_app.aboutToQuit = _Signal()
    fake_app.exec.return_value = 0
    bridge = MagicMock()

    class Shell:
        def __init__(self, *, bridge, owner_anchor, shutdown_request, **kwargs) -> None:  # noqa: ANN001
            _ = (bridge, shutdown_request)
            captured.append(kwargs.get("mock_mode", False))
            owner_anchor(self)

        def show(self) -> None:
            return None

    monkeypatch.setattr(gui_app, "QApplication", lambda _argv: fake_app)
    monkeypatch.setattr(gui_app, "_load_bundled_fonts", lambda: None)
    monkeypatch.setattr(gui_app, "apply_fusion_dark_palette", lambda _app: None)
    monkeypatch.setattr(gui_app.qdarktheme, "setup_theme", lambda **_kwargs: None)
    monkeypatch.setattr(gui_app, "try_acquire_lock", lambda _name: 1)
    monkeypatch.setattr(gui_app, "release_lock_exact", lambda _fd, _name: None)
    monkeypatch.setattr(gui_app, "open_gui_command_worker_admission", lambda: 1)
    monkeypatch.setattr(gui_app, "revoke_gui_command_worker_admission", lambda _epoch: None)
    monkeypatch.setattr(gui_app, "ZmqBridge", lambda: bridge)
    monkeypatch.setattr(gui_app, "set_bridge", lambda _bridge: None)
    monkeypatch.setattr(gui_app, "MainWindow", Shell)
    monkeypatch.setattr(
        gui_app,
        "start_operator_snapshot_ingress",
        lambda _bridge, _window, *, expected_mode, anchor: (
            ingress_modes.append(expected_mode),
            anchor(SimpleNamespace(pump=lambda: None)),
        ),
    )
    monkeypatch.setattr(gui_app, "QTimer", MagicMock())
    monkeypatch.setattr(gui_app, "_hold_gui_runtime", lambda _app, _owners: None)
    monkeypatch.setattr("cryodaq.logging_setup.setup_logging", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("cryodaq.logging_setup.resolve_log_level", lambda: "INFO")
    monkeypatch.setattr(gui_app.sys, "argv", argv)
    if mock_env is None:
        monkeypatch.delenv("CRYODAQ_MOCK", raising=False)
    else:
        monkeypatch.setenv("CRYODAQ_MOCK", mock_env)

    with pytest.raises(SystemExit) as exited:
        gui_app.main()

    assert exited.value.code == 0
    assert captured == [expected_mock]
    assert ingress_modes == [SnapshotMode.LIVE]
