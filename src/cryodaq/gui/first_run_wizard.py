"""First-run setup wizard shown by the launcher on a genuinely fresh install.

Instrument addresses and Telegram are skippable; the read-only safety.yaml
review is mandatory and uses the production validator. Cancelling leaves the
launcher's existing startup path untouched (see ``maybe_show_first_run_wizard``
— the single guarded call point in ``cryodaq.launcher``).
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Mapping
from pathlib import Path

import yaml
from PySide6.QtCore import QEvent
from PySide6.QtGui import QFont, QIntValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode
from yaml.tokens import AliasToken, AnchorToken

from cryodaq.drivers.registry import (
    ConfigField,
    DriverAuthority,
    DriverRegistryError,
    ValueKind,
    get_driver_spec,
    validate_instrument_entries,
)
from cryodaq.gui import first_run_config as cfg
from cryodaq.gui import theme
from cryodaq.paths import get_config_dir

logger = logging.getLogger(__name__)

_MISSING = object()
_COMPOUND_KINDS = {
    ValueKind.STRING_MAP,
    ValueKind.INTEGER_LIST,
    ValueKind.ASC_REFERENCE_CHANNELS,
}
_MAX_COMPOUND_UTF8_BYTES = 16_384
_MAX_COMPOUND_NODES = 256
_MAX_COMPOUND_DEPTH = 8
_REVIEWED_SOURCE_SETUP_FIELDS = frozenset(
    {
        "name",
        "resource",
        "poll_interval_s",
        "connect_timeout_s",
        "read_timeout_s",
    }
)
_FIELD_LABELS = {
    "name": "Имя прибора",
    "resource": "Адрес подключения",
    "poll_interval_s": "Интервал опроса, с",
    "connect_timeout_s": "Таймаут подключения, с",
    "read_timeout_s": "Таймаут чтения, с",
    "host": "Сетевой узел",
    "port": "Сетевой порт",
    "channels": "Каналы",
    "channel_count": "Количество каналов",
    "baudrate": "Скорость порта, бод",
    "address": "Адрес прибора",
    "validate_checksum": "Проверять контрольную сумму",
    "mode": "Режим",
    "target_rate_hz": "Целевая частота, Гц",
    "close_timeout_s": "Таймаут закрытия, с",
    "max_frame_bytes": "Максимальный размер кадра, байт",
}
_DRIVER_TITLES = {
    "lakeshore_218s": "Термометр Lake Shore 218S",
    "thyracont_vsp63d": "Вакуумметр Thyracont VSP63D",
    "etalon_multiline": "Многоканальный измеритель Etalon",
    "asc_reference_tcp": "Эталонный канал ASC",
    "keithley_2604b": "Источник-измеритель Keithley 2604B",
}
_DRIVER_DESCRIPTIONS = {
    DriverAuthority.PASSIVE_MEASUREMENT: "Пассивное измерение: мастер меняет только параметры опроса и подключения.",
    DriverAuthority.PASSIVE_EXTENSION: "Пассивное расширение: управление оборудованием не предоставляется.",
    DriverAuthority.REVIEWED_SOURCE: (
        "Источник с отдельным контуром безопасности: здесь доступны только параметры подключения и опроса."
    ),
}

SetupWidget = QLineEdit | QPlainTextEdit | QCheckBox


def _field_label(key: str) -> str:
    try:
        return _FIELD_LABELS[key]
    except KeyError as exc:
        raise DriverRegistryError(f"для параметра {key!r} нет проверенной русской подписи") from exc


def _style_setup_widget(widget: SetupWidget, accessible_name: str) -> None:
    """Apply the established input rhythm and keyboard focus contract."""

    widget.setAccessibleName(accessible_name)
    # DESIGN: RULE-SPACE-007, RULE-INTER-001, RULE-COLOR-001
    height = theme.ROW_HEIGHT * 3 if isinstance(widget, QPlainTextEdit) else theme.ROW_HEIGHT
    widget.setFixedHeight(height)
    widget.setStyleSheet(
        f"QLineEdit, QPlainTextEdit, QCheckBox {{"
        f"background: {theme.SURFACE_CARD}; border: 1px solid {theme.BORDER};"
        f"border-radius: {theme.RADIUS_SM}px; color: {theme.FOREGROUND};"
        f"padding: 0 {theme.SPACE_2}px; }}"
        f"QLineEdit:focus, QPlainTextEdit:focus, QCheckBox:focus {{"
        f"border: 2px solid {theme.ACCENT}; }}"
    )


def _plain_schema_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain_schema_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain_schema_value(item) for item in value]
    return value


def _format_field_value(value: object, schema: ConfigField) -> str:
    if value is _MISSING or value is None:
        return ""
    if schema.kind in _COMPOUND_KINDS:
        return yaml.safe_dump(
            _plain_schema_value(value),
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        ).strip()
    return str(value)


def _bounded_compound_value(text: str, kind: ValueKind) -> object:
    """Parse one small alias-free YAML value after bounding its syntax tree."""

    if len(text.encode("utf-8")) > _MAX_COMPOUND_UTF8_BYTES:
        raise DriverRegistryError("структурированное значение превышает допустимый размер")
    tokens = yaml.scan(text, Loader=yaml.SafeLoader)
    if any(isinstance(token, (AliasToken, AnchorToken)) for token in tokens):
        raise DriverRegistryError("YAML-ссылки и псевдонимы в мастере запрещены")
    node = yaml.compose(text, Loader=yaml.SafeLoader)
    if node is None:
        return None

    node_count = 0

    def inspect(current: Node, depth: int) -> None:
        nonlocal node_count
        node_count += 1
        if node_count > _MAX_COMPOUND_NODES:
            raise DriverRegistryError("структурированное значение содержит слишком много элементов")
        if depth > _MAX_COMPOUND_DEPTH:
            raise DriverRegistryError("структурированное значение имеет слишком большую вложенность")
        if isinstance(current, MappingNode):
            for key_node, value_node in current.value:
                inspect(key_node, depth + 1)
                inspect(value_node, depth + 1)
        elif isinstance(current, SequenceNode):
            for item in current.value:
                inspect(item, depth + 1)

    inspect(node, 1)
    if kind is ValueKind.STRING_MAP:
        if not isinstance(node, MappingNode) or any(
            not isinstance(key, ScalarNode) or not isinstance(value, ScalarNode) for key, value in node.value
        ):
            raise DriverRegistryError("ожидается плоский словарь строк")
    elif kind is ValueKind.INTEGER_LIST:
        if not isinstance(node, SequenceNode) or any(not isinstance(item, ScalarNode) for item in node.value):
            raise DriverRegistryError("ожидается плоский список номеров каналов")
    elif kind is ValueKind.ASC_REFERENCE_CHANNELS:
        if not isinstance(node, SequenceNode) or any(
            not isinstance(item, MappingNode)
            or any(not isinstance(key, ScalarNode) or not isinstance(value, ScalarNode) for key, value in item.value)
            for item in node.value
        ):
            raise DriverRegistryError("ожидается список плоских описаний каналов ASC")
    return yaml.safe_load(text)


def _parse_field_value(widget: SetupWidget, schema: ConfigField) -> object:
    if schema.kind is ValueKind.BOOLEAN:
        assert isinstance(widget, QCheckBox)
        return widget.isChecked()
    assert isinstance(widget, (QLineEdit, QPlainTextEdit))
    text = (widget.text() if isinstance(widget, QLineEdit) else widget.toPlainText()).strip()
    if not text:
        return _MISSING
    if schema.kind is ValueKind.STRING:
        return text
    if schema.kind is ValueKind.INTEGER:
        return int(text)
    if schema.kind is ValueKind.NUMBER:
        return float(text.replace(",", "."))
    return _bounded_compound_value(text, schema.kind)


def _apply_schema_overrides(data: dict, overrides: dict[str, dict[str, object]]) -> dict:
    """Patch only registry-rendered leaves while preserving the source file."""

    result = copy.deepcopy(data)
    for entry in result.get("instruments") or []:
        if isinstance(entry, dict):
            for key, value in overrides.get(entry.get("name"), {}).items():
                if value is _MISSING:
                    entry.pop(key, None)
                else:
                    entry[key] = value
    return result


class _InstrumentsPage(QWizardPage):
    """Page (a): registry-declared setup fields from instruments.yaml."""

    def __init__(self, config_dir: Path, parent: QWidget | None = None, *, prefer_local: bool = False) -> None:
        super().__init__(parent)
        self.setTitle("Приборы")
        source_name = "instruments.local.yaml" if prefer_local else "instruments.yaml"
        self.setSubTitle(
            f"Параметры приборов из config/{source_name}. Проверьте их для этого ПК или оставьте без изменений."
        )
        data = cfg.load_instruments_config(config_dir, prefer_local=prefer_local)
        entries = data.get("instruments") or []
        if not isinstance(entries, list):
            raise DriverRegistryError("instruments must be a sequence")
        self._defaults: dict[str, dict[str, object]] = {}
        self._specs = {}
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise DriverRegistryError(f"instruments[{index}] must be a mapping")
            spec = get_driver_spec(entry.get("type"))
            name = entry.get("name")
            if not isinstance(name, str) or not name:
                raise DriverRegistryError(f"instruments[{index}].name must be a non-empty string")
            if name in self._defaults:
                raise DriverRegistryError(f"instruments[{index}].name duplicates {name!r}")
            preserved_secrets = sorted(
                key for key, field in spec.config_fields.items() if field.secret and key in entry
            )
            if preserved_secrets:
                raise DriverRegistryError(
                    f"{name}: мастер не может переносить секретные параметры в instruments.local.yaml: "
                    f"{', '.join(preserved_secrets)}"
                )
            self._defaults[name] = entry
            self._specs[name] = spec
        self._field_widgets: dict[str, dict[str, SetupWidget]] = {}
        self._initial_values: dict[str, dict[str, object]] = {}
        self._multiline_widgets: set[QPlainTextEdit] = set()
        self._resource_edits: dict[str, QLineEdit] = {}
        self._baudrate_edits: dict[str, QLineEdit] = {}

        root = QVBoxLayout(self)
        root.setSpacing(theme.SPACE_3)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        form = QVBoxLayout(content)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(theme.SPACE_5)
        for name, entry in self._defaults.items():
            spec = self._specs[name]
            if spec.authority is DriverAuthority.REVIEWED_SOURCE:
                forbidden = sorted(
                    key
                    for key, schema in spec.config_fields.items()
                    if schema.setup_visible and key not in _REVIEWED_SOURCE_SETUP_FIELDS
                )
                if forbidden:
                    raise DriverRegistryError(
                        f"{name}: мастер не может показывать управляющие параметры источника: {', '.join(forbidden)}"
                    )
            widgets: dict[str, SetupWidget] = {}
            self._field_widgets[name] = widgets
            self._initial_values[name] = {}
            section = QFrame()
            section.setObjectName("instrumentSetupCard")
            section.setAccessibleName(f"Настройка прибора {name}")
            # DESIGN: RULE-SURF-001, RULE-COLOR-001 - one quiet card per instrument.
            section.setStyleSheet(
                "QFrame#instrumentSetupCard {"
                f"background: {theme.SURFACE_ELEVATED}; border: 1px solid {theme.BORDER};"
                f"border-radius: {theme.RADIUS_MD}px; }}"
            )
            section_layout = QVBoxLayout(section)
            section_layout.setContentsMargins(theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_4)
            section_layout.setSpacing(theme.SPACE_3)
            eyebrow = QLabel("ПРИБОР И ПОДКЛЮЧЕНИЕ")
            eyebrow.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
            section_layout.addWidget(eyebrow)
            heading = QLabel(f"{_DRIVER_TITLES[spec.type_name]} — {name}")
            heading_font = QFont(theme.FONT_BODY, theme.FONT_HEADING_SIZE)
            heading_font.setWeight(QFont.Weight(theme.FONT_HEADING_WEIGHT))
            heading.setFont(heading_font)
            section_layout.addWidget(heading)
            technical = QLabel(f"Тип драйвера: {spec.type_name} · класс {spec.class_name}")
            technical.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
            section_layout.addWidget(technical)
            authority_note = QLabel(_DRIVER_DESCRIPTIONS[spec.authority])
            authority_note.setWordWrap(True)
            authority_note.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
            section_layout.addWidget(authority_note)
            for key, schema in spec.config_fields.items():
                if not schema.setup_visible or schema.secret:
                    continue
                current = entry.get(key, _MISSING)
                initial = schema.default if current is _MISSING else current
                if schema.kind is ValueKind.BOOLEAN:
                    if type(initial) is not bool:
                        raise DriverRegistryError(f"{name}.{key}: логическое значение должно быть задано явно")
                    widget = QCheckBox()
                    widget.setChecked(initial)
                    widget.toggled.connect(self._update_validation)
                elif schema.kind in _COMPOUND_KINDS:
                    widget = QPlainTextEdit(_format_field_value(initial, schema))
                    widget.setTabChangesFocus(True)
                    self._multiline_widgets.add(widget)
                    widget.installEventFilter(self)
                else:
                    widget = QLineEdit(_format_field_value(initial, schema))
                    if schema.secret:
                        widget.setEchoMode(QLineEdit.EchoMode.Password)
                    if schema.kind is ValueKind.INTEGER:
                        minimum = int(schema.minimum) if schema.minimum is not None else -2_147_483_648
                        maximum = int(schema.maximum) if schema.maximum is not None else 2_147_483_647
                        widget.setValidator(QIntValidator(minimum, maximum, widget))
                    widget.editingFinished.connect(self._update_validation)
                widgets[key] = widget
                accessible_name = f"{name}: {_field_label(key)}"
                _style_setup_widget(widget, accessible_name)
                self._initial_values[name][key] = _parse_field_value(widget, schema)
                field_box = QWidget()
                field_layout = QVBoxLayout(field_box)
                field_layout.setContentsMargins(0, 0, 0, 0)
                field_layout.setSpacing(theme.SPACE_1)
                label = QLabel(_field_label(key))
                label_font = QFont(theme.FONT_BODY, theme.FONT_LABEL_SIZE)
                label_font.setWeight(QFont.Weight(theme.FONT_LABEL_WEIGHT))
                label.setFont(label_font)
                label.setBuddy(widget)
                field_layout.addWidget(label)
                field_layout.addWidget(widget)
                section_layout.addWidget(field_box)
                if key == "resource" and isinstance(widget, QLineEdit):
                    self._resource_edits[name] = widget
                if key == "baudrate" and isinstance(widget, QLineEdit):
                    self._baudrate_edits[name] = widget
            form.addWidget(section)
        form.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        self._skip_check = QCheckBox("Пропустить — не создавать instruments.local.yaml сейчас")
        _style_setup_widget(self._skip_check, "Пропустить настройку приборов")
        self._skip_check.toggled.connect(self._update_validation)
        root.addWidget(self._skip_check)
        self._validation_label = QLabel()
        self._validation_label.setWordWrap(True)
        # DESIGN: RULE-A11Y-003 - readable body text; the message names the error.
        self._validation_label.setStyleSheet(f"color: {theme.FOREGROUND};")
        root.addWidget(self._validation_label)
        self._update_validation()

    def _candidate_entries(self) -> list[dict[str, object]]:
        candidates: list[dict[str, object]] = []
        for name, original in self._defaults.items():
            spec = self._specs[name]
            candidate = copy.deepcopy(original)
            for key, widget in self._field_widgets[name].items():
                try:
                    value = _parse_field_value(widget, spec.config_fields[key])
                except (TypeError, ValueError, yaml.YAMLError) as exc:
                    raise DriverRegistryError(f"{name}.{key}: недопустимое значение") from exc
                if value is _MISSING:
                    candidate.pop(key, None)
                else:
                    candidate[key] = value
            candidates.append(candidate)
        return candidates

    def eventFilter(self, watched: object, event: QEvent) -> bool:  # noqa: N802 - Qt override
        if watched in self._multiline_widgets and event.type() is QEvent.Type.FocusOut:
            self._update_validation()
        return super().eventFilter(watched, event)

    def _validation_error(self) -> str:
        try:
            entries = (
                [copy.deepcopy(entry) for entry in self._defaults.values()]
                if self._skip_check.isChecked()
                else self._candidate_entries()
            )
            validate_instrument_entries(entries)
        except (DriverRegistryError, TypeError, ValueError, yaml.YAMLError) as exc:
            return str(exc)
        return ""

    def _update_validation(self) -> None:
        error = self._validation_error()
        self._validation_label.setText(f"Некорректная настройка: {error}" if error else "")
        self.completeChanged.emit()

    def isComplete(self) -> bool:  # noqa: N802 - Qt override
        return not self._validation_error()

    def get_overrides(self) -> dict[str, dict[str, object]]:
        """Return changed schema fields, or {} when the operator skips."""

        if self._skip_check.isChecked():
            validate_instrument_entries([copy.deepcopy(entry) for entry in self._defaults.values()])
            return {}
        candidates = self._candidate_entries()
        validate_instrument_entries(candidates)
        overrides: dict[str, dict[str, object]] = {}
        for (name, _original), candidate in zip(self._defaults.items(), candidates, strict=True):
            patch = {}
            for key, widget in self._field_widgets[name].items():
                current = _parse_field_value(widget, self._specs[name].config_fields[key])
                if current != self._initial_values[name][key]:
                    patch[key] = candidate.get(key, _MISSING)
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
        self._error_label.setStyleSheet(f"color: {theme.FOREGROUND};")
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
        _style_setup_widget(self._ack_check, "Подтвердить чтение параметров безопасности")
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
        _style_setup_widget(self._token_edit, "Telegram: токен бота")
        _style_setup_widget(self._chat_id_edit, "Telegram: идентификатор чата")
        self._validation_label.setStyleSheet(f"color: {theme.FOREGROUND};")

        root = QVBoxLayout(self)
        form = QVBoxLayout()
        form.setSpacing(theme.SPACE_1)
        token_label = QLabel("Токен бота")
        token_label.setBuddy(self._token_edit)
        chat_label = QLabel("Идентификатор чата")
        chat_label.setBuddy(self._chat_id_edit)
        form.addWidget(token_label)
        form.addWidget(self._token_edit)
        form.addSpacing(theme.SPACE_3)
        form.addWidget(chat_label)
        form.addWidget(self._chat_id_edit)
        root.addLayout(form)
        root.addWidget(self._validation_label)
        self._token_edit.editingFinished.connect(self._update_validation)
        self._chat_id_edit.editingFinished.connect(self._update_validation)
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
            patched = _apply_schema_overrides(base, instrument_overrides)
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
