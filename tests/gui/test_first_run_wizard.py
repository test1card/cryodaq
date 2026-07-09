"""Offscreen Qt tests for the first-run wizard."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import yaml
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QMessageBox, QWizard

from cryodaq.gui import first_run_config as cfg
from cryodaq.gui.first_run_wizard import (
    FirstRunWizard,
    _InstrumentsPage,
    _SafetyPage,
    _TelegramPage,
    run_first_run_wizard,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _write_valid_config(config_dir: Path, *, local: bool = False) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "instruments.yaml").write_text(
        "instruments:\n  - type: lakeshore_218s\n    name: LS\n    resource: BASE\ncustom_top: base\n",
        encoding="utf-8",
    )
    (config_dir / "safety.yaml").write_text(
        "critical_channels: ['T1']\nstale_timeout_s: 10.0\nrate_limits:\n  max_dT_dt_K_per_min: 5.0\n",
        encoding="utf-8",
    )
    if local:
        (config_dir / "instruments.local.yaml").write_text(
            "# KEEP OPERATOR COMMENT\n"
            "instruments:\n"
            "  - type: lakeshore_218s\n"
            "    name: LS\n"
            "    resource: LIVE\n"
            "    operator_field: keep\n"
            "custom_top: live\n",
            encoding="utf-8",
        )


def test_telegram_token_is_masked_and_requires_nonzero_chat_id() -> None:
    _app()
    page = _TelegramPage()
    assert page._token_edit.echoMode() == QLineEdit.EchoMode.Password

    page._token_edit.setText("secret")
    assert page.isComplete() is False
    page._chat_id_edit.setText("0")
    assert page.isComplete() is False
    page._chat_id_edit.setText("-100123")
    assert page.isComplete() is True
    assert page.get_values() == ("secret", "-100123")


def test_safety_page_missing_config_is_visibly_invalid(tmp_path: Path) -> None:
    _app()
    page = _SafetyPage(tmp_path)
    assert page._ack_check.isEnabled() is False
    assert page.isComplete() is False
    assert "недействительна" in page._error_label.text().lower()


def test_instrument_page_rejects_invalid_baudrate(tmp_path: Path) -> None:
    _app()
    _write_valid_config(tmp_path)
    path = tmp_path / "instruments.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("    resource: BASE\n", "    resource: BASE\n    baudrate: 9600\n"),
        encoding="utf-8",
    )
    page = _InstrumentsPage(tmp_path)
    page._baudrate_edits["LS"].setText("invalid")
    assert page.isComplete() is False
    assert "LS" in page._validation_label.text()
    page._baudrate_edits["LS"].setText("115200")
    assert page.isComplete() is True


def test_forced_wizard_seeds_existing_local_and_preserves_unedited_fields(tmp_path: Path) -> None:
    _app()
    _write_valid_config(tmp_path, local=True)
    original = (tmp_path / "instruments.local.yaml").read_text(encoding="utf-8")
    wizard = FirstRunWizard(tmp_path, force=True)

    assert wizard._instruments_page._resource_edits["LS"].text() == "LIVE"
    wizard._instruments_page._resource_edits["LS"].setText("NEW")

    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
        assert wizard.apply_results() is True

    saved = yaml.safe_load((tmp_path / "instruments.local.yaml").read_text(encoding="utf-8"))
    assert saved["instruments"][0]["resource"] == "NEW"
    assert saved["instruments"][0]["operator_field"] == "keep"
    assert saved["custom_top"] == "live"
    assert (tmp_path / "instruments.local.yaml.bak").read_text(encoding="utf-8") == original


def test_forced_wizard_unchanged_finish_does_not_rewrite_existing_local(tmp_path: Path) -> None:
    _app()
    _write_valid_config(tmp_path, local=True)
    path = tmp_path / "instruments.local.yaml"
    original = path.read_bytes()
    wizard = FirstRunWizard(tmp_path, force=True)

    assert wizard.apply_results() is True
    assert path.read_bytes() == original


def test_forced_telegram_change_preserves_existing_notification_semantics(tmp_path: Path) -> None:
    _app()
    _write_valid_config(tmp_path, local=True)
    notification_path = tmp_path / "notifications.local.yaml"
    original = (
        "# KEEP NOTIFICATION COMMENT\n"
        "telegram:\n"
        "  bot_token: old-secret\n"
        "  chat_id: 41\n"
        "  allowed_chat_ids: [41]\n"
        "periodic_report:\n"
        "  enabled: false\n"
        "commands:\n"
        "  enabled: false\n"
        "custom_sender:\n"
        "  enabled: false\n"
    )
    notification_path.write_text(original, encoding="utf-8")
    wizard = FirstRunWizard(tmp_path, force=True)
    wizard._telegram_page._token_edit.setText("new-secret")
    wizard._telegram_page._chat_id_edit.setText("42")

    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
        assert wizard.apply_results() is True

    saved = yaml.safe_load(notification_path.read_text(encoding="utf-8"))
    assert saved["telegram"]["bot_token"] == "new-secret"
    assert saved["telegram"]["chat_id"] == 42
    assert saved["telegram"]["allowed_chat_ids"] == [41]
    assert saved["periodic_report"]["enabled"] is False
    assert saved["custom_sender"]["enabled"] is False
    assert notification_path.with_name("notifications.local.yaml.bak").read_text(encoding="utf-8") == original


def test_cancel_continues_without_writes_or_completion_marker(tmp_path: Path) -> None:
    _app()
    _write_valid_config(tmp_path)
    with patch.object(FirstRunWizard, "exec", return_value=QDialog.DialogCode.Rejected):
        assert run_first_run_wizard(None, tmp_path) is False
    assert not (tmp_path / cfg.FIRST_RUN_MARKER_NAME).exists()
    assert not (tmp_path / "instruments.local.yaml").exists()


def test_cancel_button_explains_that_startup_continues(tmp_path: Path) -> None:
    _app()
    _write_valid_config(tmp_path)
    wizard = FirstRunWizard(tmp_path)
    assert "продолжить" in wizard.buttonText(QWizard.WizardButton.CancelButton).lower()


def test_read_only_save_error_is_visible_and_non_destructive(tmp_path: Path, caplog) -> None:
    _app()
    _write_valid_config(tmp_path)
    with (
        patch.object(FirstRunWizard, "exec", return_value=QDialog.DialogCode.Accepted),
        patch.object(
            FirstRunWizard,
            "apply_results",
            side_effect=PermissionError("TOPSECRET read-only"),
        ),
        patch.object(QMessageBox, "critical") as critical,
        caplog.at_level(logging.ERROR, logger="cryodaq.gui.first_run_wizard"),
    ):
        assert run_first_run_wizard(None, tmp_path) is False

    critical.assert_called_once()
    assert "TOPSECRET" not in str(critical.call_args)
    assert "TOPSECRET" not in caplog.text
    assert not (tmp_path / cfg.FIRST_RUN_MARKER_NAME).exists()
