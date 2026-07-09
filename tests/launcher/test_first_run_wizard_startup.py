"""Launcher ordering, recovery, and nonblocking tray regressions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _run_launcher(
    argv: list[str],
    *,
    lock_result: object = 123,
    recovery_error: Exception | None = None,
) -> tuple[list[str], MagicMock]:
    from cryodaq import launcher

    events: list[str] = []
    app = MagicMock()

    def acquire(_name: str) -> object:
        events.append("lock")
        return lock_result

    def show_wizard(*_args, **_kwargs) -> bool:
        events.append("wizard")
        return True

    def recover(*_args, **_kwargs) -> None:
        events.append("recover")
        if recovery_error is not None:
            raise recovery_error

    def build_window(*_args, **_kwargs):
        events.append("window")
        raise SystemExit(91)

    with (
        patch("sys.argv", argv),
        patch("cryodaq.logging_setup.setup_logging"),
        patch("cryodaq.logging_setup.resolve_log_level", return_value="INFO"),
        patch("cryodaq.launcher.QApplication", return_value=app),
        patch("cryodaq.gui.app._load_bundled_fonts"),
        patch("cryodaq.gui.app.apply_fusion_dark_palette"),
        patch("cryodaq.launcher.try_acquire_lock", side_effect=acquire),
        patch("cryodaq.gui.first_run_config.recover_pending_setup", side_effect=recover),
        patch(
            "cryodaq.gui.first_run_wizard.maybe_show_first_run_wizard",
            side_effect=show_wizard,
        ) as wizard,
        patch("cryodaq.launcher.LauncherWindow", side_effect=build_window),
        patch("cryodaq.launcher.QMessageBox.critical"),
    ):
        with pytest.raises(SystemExit):
            launcher.main()

    return events, wizard


def test_launcher_acquires_single_instance_lock_before_wizard() -> None:
    events, wizard = _run_launcher(["cryodaq"])
    assert wizard.called
    assert events[:3] == ["lock", "recover", "wizard"]


def test_fresh_tray_startup_does_not_open_modal_wizard() -> None:
    events, wizard = _run_launcher(["cryodaq", "--tray"])
    assert events == ["lock", "recover", "window"]
    wizard.assert_not_called()


def test_explicit_setup_wizard_remains_interactive_in_tray_mode() -> None:
    events, wizard = _run_launcher(["cryodaq", "--tray", "--setup-wizard"])
    assert events == ["lock", "recover", "wizard", "window"]
    wizard.assert_called_once_with(force=True)


def test_duplicate_launcher_exits_without_showing_wizard() -> None:
    events, wizard = _run_launcher(["cryodaq", "--setup-wizard"], lock_result=None)
    assert events == ["lock"]
    wizard.assert_not_called()


def test_recovery_failure_stops_before_wizard_and_engine() -> None:
    events, wizard = _run_launcher(
        ["cryodaq"],
        recovery_error=RuntimeError("corrupt recovery manifest"),
    )
    assert events == ["lock", "recover"]
    wizard.assert_not_called()
