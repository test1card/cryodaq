"""Offscreen Qt tests for the first-run wizard."""

from __future__ import annotations

import logging
import os
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
import yaml
from PySide6.QtWidgets import QApplication, QCheckBox, QDialog, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QWizard

from cryodaq.drivers.registry import (
    BUILTIN_DRIVER_SPECS,
    ConfigField,
    DriverRegistryError,
    UnknownDriverTypeError,
    ValueKind,
    get_driver_spec,
)
from cryodaq.gui import first_run_config as cfg
from cryodaq.gui import theme
from cryodaq.gui.first_run_wizard import (
    FirstRunWizard,
    _bounded_compound_value,
    _field_label,
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
        "instruments:\n  - type: lakeshore_218s\n    name: LS\n    resource: GPIB0::12::INSTR\ncustom_top: base\n",
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
            "    resource: GPIB0::13::INSTR\n"
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
        "instruments:\n  - type: thyracont_vsp63d\n    name: VSP\n    resource: COM3\n    baudrate: 9600\n",
        encoding="utf-8",
    )
    page = _InstrumentsPage(tmp_path)
    page._baudrate_edits["VSP"].setText("invalid")
    assert page.isComplete() is False
    assert "VSP" in page._validation_error()
    page._baudrate_edits["VSP"].setText("115200")
    assert page.isComplete() is True


def test_instrument_page_renders_distinct_registry_schemas_and_round_trips(tmp_path: Path) -> None:
    _app()
    _write_valid_config(tmp_path)
    (tmp_path / "instruments.yaml").write_text(
        "instruments:\n"
        "  - type: thyracont_vsp63d\n"
        "    name: VSP\n"
        "    resource: COM3\n"
        "    baudrate: 9600\n"
        "    address: '001'\n"
        "    validate_checksum: true\n"
        "  - type: etalon_multiline\n"
        "    name: Etalon\n"
        "    host: localhost\n"
        "    port: 2001\n"
        "    channels: [1, 2]\n"
        "    mode: averaged\n"
        "custom_top: preserved\n",
        encoding="utf-8",
    )
    wizard = FirstRunWizard(tmp_path)
    page = wizard._instruments_page

    assert set(page._field_widgets["VSP"]) == {
        key for key, field in get_driver_spec("thyracont_vsp63d").config_fields.items() if field.setup_visible
    }
    assert set(page._field_widgets["Etalon"]) == {
        key for key, field in get_driver_spec("etalon_multiline").config_fields.items() if field.setup_visible
    }
    assert isinstance(page._field_widgets["VSP"]["validate_checksum"], QCheckBox)
    assert isinstance(page._field_widgets["Etalon"]["channels"], QPlainTextEdit)

    page._baudrate_edits["VSP"].setText("115200")
    channels = page._field_widgets["Etalon"]["channels"]
    assert isinstance(channels, QPlainTextEdit)
    channels.setPlainText("[2, 3]")
    assert page.isComplete()
    assert wizard.apply_results()

    saved = yaml.safe_load((tmp_path / "instruments.local.yaml").read_text(encoding="utf-8"))
    assert saved["instruments"][0]["baudrate"] == 115200
    assert saved["instruments"][0]["validate_checksum"] is True
    assert saved["instruments"][1]["channels"] == [2, 3]
    assert saved["instruments"][1]["mode"] == "averaged"
    assert saved["custom_top"] == "preserved"


def test_instrument_page_rejects_unknown_driver_type(tmp_path: Path) -> None:
    _app()
    _write_valid_config(tmp_path)
    (tmp_path / "instruments.yaml").write_text(
        "instruments:\n  - type: unreviewed_plugin\n    name: unknown\n",
        encoding="utf-8",
    )
    with pytest.raises(UnknownDriverTypeError, match="unreviewed_plugin"):
        _InstrumentsPage(tmp_path)


def test_reviewed_source_never_gains_default_on_or_hidden_authority_fields(tmp_path: Path) -> None:
    _app()
    _write_valid_config(tmp_path)
    (tmp_path / "instruments.yaml").write_text(
        "instruments:\n  - type: keithley_2604b\n    name: Keithley\n    resource: USB0::1::INSTR\n",
        encoding="utf-8",
    )
    page = _InstrumentsPage(tmp_path)
    widgets = page._field_widgets["Keithley"]

    assert "type" not in widgets
    assert not any(isinstance(widget, QCheckBox) and widget.isChecked() for widget in widgets.values())
    assert {"source_enabled", "output_enabled", "enabled"}.isdisjoint(widgets)
    assert page.get_overrides() == {}


def test_reviewed_source_rejects_control_field_even_when_default_is_false(tmp_path: Path) -> None:
    _app()
    _write_valid_config(tmp_path)
    (tmp_path / "instruments.yaml").write_text(
        "instruments:\n  - type: keithley_2604b\n    name: Keithley\n    resource: USB0::1::INSTR\n",
        encoding="utf-8",
    )
    source = get_driver_spec("keithley_2604b")
    unsafe_schema = replace(
        source,
        config_fields={
            **source.config_fields,
            "output_enabled": ConfigField(ValueKind.BOOLEAN, default=False),
        },
    )

    with (
        patch("cryodaq.gui.first_run_wizard.get_driver_spec", return_value=unsafe_schema),
        pytest.raises(DriverRegistryError, match="управляющие параметры.*output_enabled"),
    ):
        _InstrumentsPage(tmp_path)


def test_preserved_unknown_instrument_key_is_visibly_rejected(tmp_path: Path) -> None:
    _app()
    _write_valid_config(tmp_path)
    path = tmp_path / "instruments.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("    resource:", "    invented_namespace: keep\n    resource:"),
        encoding="utf-8",
    )

    page = _InstrumentsPage(tmp_path)

    assert page.isComplete() is False
    assert "invented_namespace" in page._validation_error()
    page._skip_check.setChecked(True)
    assert page.isComplete() is False
    with pytest.raises(DriverRegistryError, match="invented_namespace"):
        page.get_overrides()


def test_secret_registry_field_is_not_rendered_without_owner_contract(tmp_path: Path) -> None:
    _app()
    _write_valid_config(tmp_path)
    source = get_driver_spec("lakeshore_218s")
    secret_schema = replace(
        source,
        config_fields={
            **source.config_fields,
            "api_token": ConfigField(ValueKind.STRING, default="do-not-render", secret=True),
        },
    )

    with patch("cryodaq.gui.first_run_wizard.get_driver_spec", return_value=secret_schema):
        page = _InstrumentsPage(tmp_path)

    assert "api_token" not in page._field_widgets["LS"]
    assert "do-not-render" not in " ".join(label.text() for label in page.findChildren(QLabel))


def test_preserved_secret_registry_field_is_rejected_before_non_secret_copy(tmp_path: Path) -> None:
    _app()
    _write_valid_config(tmp_path)
    path = tmp_path / "instruments.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("    resource:", "    api_token: existing-secret\n    resource:"),
        encoding="utf-8",
    )
    source = get_driver_spec("lakeshore_218s")
    secret_schema = replace(
        source,
        config_fields={
            **source.config_fields,
            "api_token": ConfigField(ValueKind.STRING, secret=True),
        },
    )

    with patch("cryodaq.gui.first_run_wizard.get_driver_spec", return_value=secret_schema):
        with pytest.raises(DriverRegistryError, match="api_token"):
            _InstrumentsPage(tmp_path)


def test_boolean_seed_requires_exact_bool(tmp_path: Path) -> None:
    _app()
    _write_valid_config(tmp_path)
    (tmp_path / "instruments.yaml").write_text(
        "instruments:\n  - type: thyracont_vsp63d\n    name: VSP\n    resource: COM3\n    validate_checksum: 'false'\n",
        encoding="utf-8",
    )

    with pytest.raises(DriverRegistryError, match="логическое значение"):
        _InstrumentsPage(tmp_path)


@pytest.mark.parametrize(
    ("text", "kind", "message"),
    [
        ("base: &base value\ncopy: *base", ValueKind.STRING_MAP, "ссылки"),
        (
            "a:\n  b:\n    c:\n      d:\n        e:\n"
            "          f:\n            g:\n              h:\n                i: x",
            ValueKind.STRING_MAP,
            "вложенность",
        ),
        ("[" + ", ".join("1" for _ in range(300)) + "]", ValueKind.INTEGER_LIST, "слишком много"),
        ("[1, [2]]", ValueKind.INTEGER_LIST, "плоский список"),
    ],
)
def test_compound_parser_rejects_alias_depth_node_and_shape_attacks(
    text: str,
    kind: ValueKind,
    message: str,
) -> None:
    with pytest.raises(DriverRegistryError, match=message):
        _bounded_compound_value(text, kind)


def test_compound_parser_bounds_utf8_bytes_before_yaml_parse() -> None:
    with (
        patch("cryodaq.gui.first_run_wizard.yaml.scan") as scan,
        pytest.raises(DriverRegistryError, match="размер"),
    ):
        _bounded_compound_value("я" * 9_000, ValueKind.STRING_MAP)
    scan.assert_not_called()


def test_registry_fields_follow_input_accessibility_and_focus_contract(tmp_path: Path) -> None:
    _app()
    _write_valid_config(tmp_path)
    page = _InstrumentsPage(tmp_path)

    for widgets in page._field_widgets.values():
        for widget in widgets.values():
            assert widget.accessibleName()
            assert widget.height() >= theme.ROW_HEIGHT
            assert theme.ACCENT in widget.styleSheet()
            if isinstance(widget, QPlainTextEdit):
                assert widget.tabChangesFocus() is True


def test_registry_inventory_has_reviewed_russian_labels_and_progressive_card_hierarchy(tmp_path: Path) -> None:
    _app()
    _write_valid_config(tmp_path)
    for spec in BUILTIN_DRIVER_SPECS.values():
        for key, field in spec.config_fields.items():
            if field.setup_visible and not field.secret:
                assert _field_label(key)

    page = _InstrumentsPage(tmp_path)
    visible = " ".join(label.text() for label in page.findChildren(QLabel))
    assert "ПРИБОР И ПОДКЛЮЧЕНИЕ" in visible
    assert "Термометр Lake Shore 218S" in visible
    assert "Тип драйвера:" in visible


def test_forced_wizard_seeds_existing_local_and_preserves_valid_unedited_fields(tmp_path: Path) -> None:
    _app()
    _write_valid_config(tmp_path, local=True)
    original = (tmp_path / "instruments.local.yaml").read_text(encoding="utf-8")
    wizard = FirstRunWizard(tmp_path, force=True)

    assert wizard._instruments_page._resource_edits["LS"].text() == "GPIB0::13::INSTR"
    wizard._instruments_page._resource_edits["LS"].setText("GPIB0::14::INSTR")

    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
        assert wizard.apply_results() is True

    saved = yaml.safe_load((tmp_path / "instruments.local.yaml").read_text(encoding="utf-8"))
    assert saved["instruments"][0]["resource"] == "GPIB0::14::INSTR"
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
