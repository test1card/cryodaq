"""Behavioral tests for deferred, no-interruption theme selection."""

from __future__ import annotations

from types import MethodType, SimpleNamespace
from unittest.mock import MagicMock, patch

from cryodaq.launcher import LauncherWindow


def _stub() -> SimpleNamespace:
    active_action = MagicMock(name="active_theme_action")
    pending_action = MagicMock(name="pending_theme_action")
    stub = SimpleNamespace(
        _theme_active_id="warm_stone",
        _theme_actions={"warm_stone": active_action, "signal": MagicMock()},
        _theme_pending_action=pending_action,
        _tray=MagicMock(name="tray"),
        _stop_assistant=MagicMock(name="stop_assistant"),
        _stop_engine=MagicMock(name="stop_engine"),
        _bridge=MagicMock(name="bridge"),
    )
    stub._update_theme_pending_indicator = MethodType(
        LauncherWindow._update_theme_pending_indicator,
        stub,
    )
    stub._defer_theme_selection = MethodType(LauncherWindow._defer_theme_selection, stub)
    return stub


def _packs() -> list[dict[str, str]]:
    return [
        {"id": "warm_stone", "name": "Warm Stone", "description": ""},
        {"id": "signal", "name": "Signal", "description": ""},
    ]


def test_theme_selection_persists_without_stopping_runtime() -> None:
    stub = _stub()

    with (
        patch("cryodaq.gui._theme_loader.available_themes", return_value=_packs()),
        patch("cryodaq.gui._theme_loader.write_theme_selection") as write_selection,
    ):
        LauncherWindow._on_theme_selected(stub, "signal")

    write_selection.assert_called_once_with("signal")
    stub._stop_assistant.assert_not_called()
    stub._stop_engine.assert_not_called()
    stub._bridge.shutdown.assert_not_called()
    stub._theme_actions["warm_stone"].setChecked.assert_called_with(True)
    assert "Signal" in stub._theme_pending_action.setText.call_args.args[0]
    stub._tray.showMessage.assert_called_once()


def test_selecting_active_theme_cancels_pending_next_launch() -> None:
    stub = _stub()

    with (
        patch("cryodaq.gui._theme_loader.available_themes", return_value=_packs()),
        patch("cryodaq.gui._theme_loader.write_theme_selection") as write_selection,
    ):
        LauncherWindow._on_theme_selected(stub, "warm_stone")

    write_selection.assert_called_once_with("warm_stone")
    assert "current" not in stub._theme_pending_action.setText.call_args.args[0].lower()
    assert (
        "\u0442\u0435\u043a\u0443\u0449\u0430\u044f \u0442\u0435\u043c\u0430"
        in stub._theme_pending_action.setText.call_args.args[0]
    )


def test_persistence_failure_keeps_runtime_and_reports_sanitized_error() -> None:
    stub = _stub()

    with (
        patch("cryodaq.gui._theme_loader.available_themes", return_value=_packs()),
        patch("cryodaq.gui._theme_loader._selected_theme_name", return_value="warm_stone"),
        patch(
            "cryodaq.gui._theme_loader.write_theme_selection",
            side_effect=RuntimeError("C:/secret/operator/path"),
        ),
        patch("cryodaq.launcher.QMessageBox.critical") as critical,
    ):
        LauncherWindow._on_theme_selected(stub, "signal")

    stub._stop_engine.assert_not_called()
    critical.assert_called_once()
    operator_text = " ".join(str(arg) for arg in critical.call_args.args)
    assert "secret" not in operator_text
    assert "path" not in operator_text
    stub._tray.showMessage.assert_not_called()


def test_nonmapping_settings_do_not_break_failure_recovery(tmp_path, monkeypatch) -> None:
    from cryodaq.gui import _theme_loader as loader

    stub = _stub()
    settings_file = tmp_path / "settings.local.yaml"
    settings_file.write_text("- one\n- two\n")
    monkeypatch.setattr(loader, "SETTINGS_FILE", settings_file)

    with (
        patch("cryodaq.gui._theme_loader.available_themes", return_value=_packs()),
        patch(
            "cryodaq.gui._theme_loader.write_theme_selection",
            side_effect=RuntimeError("private detail"),
        ),
        patch("cryodaq.launcher.QMessageBox.critical") as critical,
    ):
        LauncherWindow._on_theme_selected(stub, "signal")

    critical.assert_called_once()
    stub._theme_actions["warm_stone"].setChecked.assert_called_with(True)
    stub._stop_engine.assert_not_called()
