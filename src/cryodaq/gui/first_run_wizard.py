"""First-run setup wizard shown by the launcher on a genuinely fresh install.

Instrument addresses and Telegram are skippable; the read-only safety.yaml
review is mandatory and uses the production validator. Cancelling leaves the
launcher's existing startup path untouched (see ``maybe_show_first_run_wizard``
— the single guarded call point in ``cryodaq.launcher``).
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from cryodaq.gui import first_run_config as cfg
from cryodaq.gui import theme
from cryodaq.paths import get_config_dir

logger = logging.getLogger(__name__)

_INSTRUMENT_LABELS = {
    "lakeshore_218s": "LakeShore 218S",
    "keithley_2604b": "Keithley 2604B",
    "thyracont_vsp63d": "Thyracont VSP63D",
}


class _InstrumentsPage(QWizardPage):
    """Page (a): GPIB/VISA/COM addresses, defaulted from instruments.yaml."""

    def __init__(self, config_dir: Path, parent: QWidget | None = None, *, prefer_local: bool = False) -> None:
        super().__init__(parent)
        self.setTitle("Приборы")
        source_name = "instruments.local.yaml" if prefer_local else "instruments.yaml"
        self.setSubTitle(
            f"Адреса приборов из config/{source_name}. Отредактируйте под фактический ПК или оставьте как есть."
        )
        self._defaults = cfg.extract_instrument_defaults(
            cfg.load_instruments_config(config_dir, prefer_local=prefer_local)
        )
        self._resource_edits: dict[str, QLineEdit] = {}
        self._baudrate_edits: dict[str, QLineEdit] = {}

        root = QVBoxLayout(self)
        root.setSpacing(theme.SPACE_3)

        form = QFormLayout()
        form.setSpacing(theme.SPACE_2)
        for name, fields in self._defaults.items():
            type_label = _INSTRUMENT_LABELS.get(fields["type"], fields["type"])
            resource_edit = QLineEdit(str(fields.get("resource", "")))
            self._resource_edits[name] = resource_edit
            form.addRow(f"{name} ({type_label}):", resource_edit)
            if "baudrate" in fields:
                baud_edit = QLineEdit(str(fields["baudrate"]))
                baud_edit.setValidator(QIntValidator(1, 4_000_000, baud_edit))
                baud_edit.textChanged.connect(self._update_validation)
                self._baudrate_edits[name] = baud_edit
                form.addRow(f"{name} baudrate:", baud_edit)
        root.addLayout(form)

        self._skip_check = QCheckBox("Пропустить — не создавать instruments.local.yaml сейчас")
        self._skip_check.toggled.connect(self._update_validation)
        root.addWidget(self._skip_check)
        self._validation_label = QLabel()
        self._validation_label.setWordWrap(True)
        self._validation_label.setStyleSheet("color: #ff6b6b;")
        root.addWidget(self._validation_label)
        self._update_validation()

    def _invalid_baud_names(self) -> list[str]:
        if self._skip_check.isChecked():
            return []
        return [
            name for name, edit in self._baudrate_edits.items() if edit.text().strip() and not edit.hasAcceptableInput()
        ]

    def _update_validation(self) -> None:
        invalid = self._invalid_baud_names()
        self._validation_label.setText(f"Некорректный baudrate: {', '.join(invalid)}" if invalid else "")
        self.completeChanged.emit()

    def isComplete(self) -> bool:  # noqa: N802 — Qt override
        return not self._invalid_baud_names()

    def get_overrides(self) -> dict[str, dict]:
        """Return per-instrument overrides, or {} if the operator skipped this page."""
        if self._skip_check.isChecked():
            return {}
        overrides: dict[str, dict] = {}
        for name in self._defaults:
            resource = self._resource_edits[name].text().strip()
            patch: dict = {}
            if resource:
                patch["resource"] = resource
            if name in self._baudrate_edits:
                raw_baud = self._baudrate_edits[name].text().strip()
                if raw_baud:
                    if not self._baudrate_edits[name].hasAcceptableInput():
                        raise ValueError(f"invalid baudrate for {name}")
                    patch["baudrate"] = int(raw_baud)
            if patch:
                overrides[name] = patch
        return overrides


class _SafetyPage(QWizardPage):
    """Page (b): read-only safety.yaml review gate — no editing, ack only."""

    def __init__(self, config_dir: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTitle("Безопасность — обзор")
        self.setSubTitle(
            "Текущие параметры config/safety.yaml (только чтение). Изменения "
            "safety.yaml делаются осознанно, отдельно, файлом — не через мастер."
        )
        root = QVBoxLayout(self)
        root.setSpacing(theme.SPACE_3)

        form = QFormLayout()
        form.setSpacing(theme.SPACE_2)
        self._error_label = QLabel()
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet("color: #ff6b6b;")
        try:
            summary = cfg.read_safety_summary(config_dir)
        except cfg.FirstRunConfigError as exc:
            self._safety_valid = False
            self._error_label.setText(
                f"Конфигурация безопасности недействительна. Исправьте config/safety.yaml перед подтверждением.\n{exc}"
            )
            root.addWidget(self._error_label)
        else:
            self._safety_valid = True
            self._error_label.hide()
            rate_limit = summary.get("rate_limit")
            form.addRow(
                "Лимит скорости нагрева:",
                QLabel(f"{rate_limit} K/мин" if rate_limit is not None else "не задано"),
            )
            stale_timeout = summary.get("stale_timeout_s")
            form.addRow(
                "Таймаут устаревания канала:",
                QLabel(f"{stale_timeout} с" if stale_timeout is not None else "не задано"),
            )
            watchdog_mode = summary.get("watchdog_mode")
            form.addRow("Режим watchdog (Keithley):", QLabel(str(watchdog_mode or "не задано")))
        root.addLayout(form)

        self._ack_check = QCheckBox("Я прочитал(а) и понимаю")
        self._ack_check.setEnabled(self._safety_valid)
        self._ack_check.stateChanged.connect(self.completeChanged)
        root.addWidget(self._ack_check)
        self.registerField("safety_ack*", self._ack_check)

    def isComplete(self) -> bool:  # noqa: N802 — Qt override
        return self._safety_valid and self._ack_check.isChecked()


class _TelegramPage(QWizardPage):
    """Page (c): optional Telegram bot token. Blank token == skipped."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTitle("Уведомления Telegram")
        self.setSubTitle(
            "Необязательно. Оставьте поля пустыми, чтобы настроить позже вручную в config/notifications.local.yaml."
        )
        self._token_edit = QLineEdit()
        self._token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._token_edit.setPlaceholderText("токен от @BotFather")
        self._chat_id_edit = QLineEdit()
        self._chat_id_edit.setPlaceholderText("chat_id (ненулевое число)")
        self._validation_label = QLabel()
        self._validation_label.setWordWrap(True)
        self._validation_label.setStyleSheet("color: #ff6b6b;")

        root = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(theme.SPACE_2)
        form.addRow("Bot token:", self._token_edit)
        form.addRow("Chat ID:", self._chat_id_edit)
        root.addLayout(form)
        root.addWidget(self._validation_label)
        self._token_edit.textChanged.connect(self._update_validation)
        self._chat_id_edit.textChanged.connect(self._update_validation)
        self._update_validation()

    def _validation_error(self) -> str:
        token = self._token_edit.text().strip()
        chat_id = self._chat_id_edit.text().strip()
        if not token and not chat_id:
            return ""
        if not token:
            return "Укажите Bot token или очистите Chat ID, чтобы пропустить Telegram."
        try:
            parsed_chat_id = int(chat_id)
        except ValueError:
            return "Для Telegram нужен числовой ненулевой Chat ID."
        if parsed_chat_id == 0:
            return "Для Telegram нужен ненулевой Chat ID."
        return ""

    def _update_validation(self) -> None:
        self._validation_label.setText(self._validation_error())
        self.completeChanged.emit()

    def isComplete(self) -> bool:  # noqa: N802 — Qt override
        return not self._validation_error()

    def get_values(self) -> tuple[str, str] | None:
        """Return (token, chat_id) or None if the operator left it blank (skip)."""
        token = self._token_edit.text().strip()
        chat_id = self._chat_id_edit.text().strip()
        if not token and not chat_id:
            return None
        error = self._validation_error()
        if error:
            raise ValueError(error)
        return token, chat_id


class FirstRunWizard(QWizard):
    """The three-page first-run wizard. See module docstring for semantics."""

    def __init__(self, config_dir: Path, parent: QWidget | None = None, *, force: bool = False) -> None:
        super().__init__(parent)
        self._config_dir = config_dir
        self._force = force
        self.setWindowTitle("Первый запуск CryoDAQ")
        self._instruments_page = _InstrumentsPage(config_dir, prefer_local=force)
        self._safety_page = _SafetyPage(config_dir)
        self._telegram_page = _TelegramPage()
        self.addPage(self._instruments_page)
        self.addPage(self._safety_page)
        self.addPage(self._telegram_page)
        self.setButtonText(QWizard.WizardButton.CancelButton, "Отмена — продолжить без настройки")

    def apply_results(self) -> bool:
        """Write local yaml overrides collected from the pages. Finish-only —
        never called on Cancel (see ``run_first_run_wizard``)."""
        instruments_data: dict | None = None
        instrument_overrides = self._instruments_page.get_overrides()
        if instrument_overrides:
            base = cfg.load_instruments_config(self._config_dir, prefer_local=self._force)
            patched = cfg.apply_instrument_overrides(base, instrument_overrides)
            if patched != base:
                instruments_data = patched

        notifications_data: dict | None = None
        telegram_values = self._telegram_page.get_values()
        if telegram_values is not None:
            bot_token, chat_id = telegram_values
            template = cfg.load_notifications_template(self._config_dir, prefer_local=self._force)
            patched_notif = cfg.apply_telegram_overrides(template, bot_token, chat_id)
            if patched_notif != template:
                notifications_data = patched_notif

        changed_existing = []
        if instruments_data is not None and (self._config_dir / "instruments.local.yaml").exists():
            changed_existing.append("instruments.local.yaml")
        if notifications_data is not None and (self._config_dir / "notifications.local.yaml").exists():
            changed_existing.append("notifications.local.yaml")

        if changed_existing:
            names = ", ".join(changed_existing)
            answer = QMessageBox.question(
                self,
                "Подтвердите обновление локальной конфигурации",
                "Будут обновлены существующие файлы: "
                f"{names}. Неизменённые параметры сохранятся; исходные файлы "
                "с комментариями будут сохранены рядом с расширением .bak. Продолжить?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False

        cfg.write_setup_transaction(
            self._config_dir,
            instruments=instruments_data,
            notifications=notifications_data,
            backup_existing=bool(changed_existing),
        )
        return True


def run_first_run_wizard(parent: QWidget | None, config_dir: Path | None = None, *, force: bool = False) -> bool:
    """Show the wizard modally; Cancel continues startup and remains pending."""
    cfg_dir = config_dir or get_config_dir()
    try:
        wizard = FirstRunWizard(cfg_dir, parent, force=force)
    except Exception as exc:
        logger.error("First-run setup could not be opened safely (%s)", type(exc).__name__)
        QMessageBox.critical(
            parent,
            "Не удалось открыть настройку CryoDAQ",
            "Мастер не может безопасно прочитать конфигурацию. Проверьте файлы "
            "config/instruments*.yaml и config/safety.yaml. CryoDAQ продолжит "
            "запуск с существующими настройками.",
        )
        return False
    result = wizard.exec()
    finished = result == QDialog.DialogCode.Accepted
    if not finished:
        logger.info("First-run wizard cancelled; startup continues and setup remains pending")
        return False
    try:
        return wizard.apply_results()
    except Exception as exc:
        # YAML parser messages can quote source lines. Record only the class so
        # a Telegram token can never leak into launcher logs.
        logger.error(
            "First-run setup could not be saved; startup continues without changing completion state (%s)",
            type(exc).__name__,
        )
        QMessageBox.critical(
            parent,
            "Не удалось сохранить настройку CryoDAQ",
            "Локальная конфигурация не сохранена. Проверьте права записи в папку "
            "config и свободное место. CryoDAQ продолжит запуск с существующими "
            "настройками; мастер можно повторить с --setup-wizard.",
        )
        return False


def maybe_show_first_run_wizard(
    parent: QWidget | None = None, *, config_dir: Path | None = None, force: bool = False
) -> bool:
    """Guarded entry point for launcher startup — the ONE call site in
    ``cryodaq.launcher``. No-ops (returns False, no import side effects beyond
    this module) unless a fresh install is detected or ``force`` is set (the
    ``--setup-wizard`` CLI flag / a manual re-run).
    """
    cfg_dir = config_dir or get_config_dir()
    if not force and not cfg.needs_first_run(cfg_dir):
        return False
    return run_first_run_wizard(parent, cfg_dir, force=force)
