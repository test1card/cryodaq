"""Operator controls for engine-owned software-interlock optionality."""

from __future__ import annotations

import unicodedata
import uuid
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QSettings, Qt, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from cryodaq.gui import theme
from cryodaq.gui.shell.overlays._base_panel import OverlayPanelBase
from cryodaq.gui.widgets.common import StatusBanner, apply_button_style
from cryodaq.gui.zmq_client import ZmqCommandWorker

_MAX_INTERLOCKS = 128
_MAX_CHANNELS_PER_INTERLOCK = 256
_MAX_NAME_BYTES = 256
_MAX_DESCRIPTION_BYTES = 2048
_MAX_CHANNEL_BYTES = 512
_MAX_ACTION_BYTES = 128


def _bounded_text(value: object, *, limit: int, allow_empty: bool = False) -> str | None:
    if type(value) is not str or (not value and not allow_empty):
        return None
    try:
        encoded = value.encode("utf-8")
    except UnicodeError:
        return None
    if len(encoded) > limit or any(unicodedata.category(character) in {"Cc", "Cf"} for character in value):
        return None
    return value


def canonical_interlock_snapshot(value: object) -> tuple[dict[str, Any], ...] | None:
    """Validate and detach the engine-owned presentation rows."""
    if type(value) not in (list, tuple) or len(value) > _MAX_INTERLOCKS:
        return None
    rows: list[dict[str, Any]] = []
    names: set[str] = set()
    for candidate in value:
        if type(candidate) is not dict:
            return None
        name = _bounded_text(candidate.get("name"), limit=_MAX_NAME_BYTES)
        description = _bounded_text(candidate.get("description"), limit=_MAX_DESCRIPTION_BYTES)
        action = _bounded_text(candidate.get("action"), limit=_MAX_ACTION_BYTES)
        enabled = candidate.get("enabled")
        disableable = candidate.get("operator_disableable")
        channels = candidate.get("channel_ids")
        if (
            name is None
            or name in names
            or description is None
            or action is None
            or type(enabled) is not bool
            or type(disableable) is not bool
            or type(channels) not in (list, tuple)
            or not channels
            or len(channels) > _MAX_CHANNELS_PER_INTERLOCK
        ):
            return None
        canonical_channels: list[str] = []
        for channel in channels:
            bounded = _bounded_text(channel, limit=_MAX_CHANNEL_BYTES)
            if bounded is None:
                return None
            canonical_channels.append(bounded)
        if canonical_channels != sorted(set(canonical_channels)):
            return None
        names.add(name)
        rows.append(
            {
                "name": name,
                "description": description,
                "channel_ids": tuple(canonical_channels),
                "enabled": enabled,
                "operator_disableable": disableable,
                "action": action,
            }
        )
    return tuple(rows)


def disabled_names_from_snapshot(snapshot: tuple[dict[str, Any], ...]) -> tuple[str, ...]:
    return tuple(sorted(row["name"] for row in snapshot if row["enabled"] is False))


def _title_font() -> QFont:
    font = QFont(theme.FONT_BODY)
    font.setPixelSize(theme.FONT_SIZE_XL)
    font.setWeight(QFont.Weight(theme.FONT_WEIGHT_SEMIBOLD))
    return font


def _row_title_font() -> QFont:
    font = QFont(theme.FONT_BODY)
    font.setPixelSize(theme.FONT_BODY_SIZE)
    font.setWeight(QFont.Weight(theme.FONT_WEIGHT_SEMIBOLD))
    return font


class _InterlockRow(QFrame):
    """One engine-described interlock with a direct reversible action."""

    def __init__(self, state: dict[str, Any], on_toggle: Callable[[str, bool], None]) -> None:
        super().__init__()
        self._name = state["name"]
        self._description = state["description"]
        self._channels = state["channel_ids"]
        self._action = state["action"]
        self._enabled = state["enabled"]
        self._on_toggle = on_toggle

        self.setObjectName("interlockControlRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#interlockControlRow {{ background: {theme.SURFACE_CARD};"
            f" border: 1px solid {theme.BORDER_SUBTLE};"
            f" border-radius: {theme.RADIUS_MD}px; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, theme.SPACE_3)
        layout.setSpacing(theme.SPACE_2)

        heading = QHBoxLayout()
        heading.setSpacing(theme.SPACE_2)
        name_label = QLabel(self._name)
        name_label.setFont(_row_title_font())
        name_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        name_label.setStyleSheet(f"color: {theme.FOREGROUND};")
        heading.addWidget(name_label)
        heading.addStretch()

        self._status_label = QLabel()
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setMinimumWidth(130)
        heading.addWidget(self._status_label)

        self._toggle_button = QPushButton()
        self._toggle_button.setAccessibleName(f"Переключить блокировку {self._name}")
        self._toggle_button.setToolTip("Решение записывается Engine и применяется сразу, без подтверждающего диалога")
        # DESIGN: RULE-INTER-004 does not apply: this is a reversible operator
        # protection choice, and the current owner contract explicitly requires
        # a warning followed by immediate execution without a confirmation trap.
        self._toggle_button.clicked.connect(self._toggle)
        heading.addWidget(self._toggle_button)
        layout.addLayout(heading)

        description_label = QLabel(self._description)
        description_label.setWordWrap(True)
        description_label.setStyleSheet(f"color: {theme.FOREGROUND};")
        layout.addWidget(description_label)

        self._channels_label = QLabel("Каналы: " + ", ".join(self._channels))
        self._channels_label.setWordWrap(True)
        self._channels_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._channels_label.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
        layout.addWidget(self._channels_label)

        action_text = {
            "emergency_off": "аварийное отключение источников",
            "stop_source": "остановка источника",
        }.get(self._action, "защитное действие Engine")
        self._action_label = QLabel(f"Действие: {action_text} ({self._action})")
        self._action_label.setWordWrap(True)
        self._action_label.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
        layout.addWidget(self._action_label)
        self.set_state(self._enabled, stale=False)

    def descriptor_key(self) -> tuple[str, str, tuple[str, ...], str]:
        return self._name, self._description, self._channels, self._action

    def set_state(self, enabled: bool, *, stale: bool) -> None:
        self._enabled = enabled
        if stale:
            state_text = "ПОСЛЕДНЕЕ: ВКЛЮЧЕНА" if enabled else "⚠ ПОСЛЕДНЕЕ: ОТКЛЮЧЕНА"
            state_color = theme.MUTED_FOREGROUND
        elif enabled:
            state_text = "● ВКЛЮЧЕНА"
            state_color = theme.STATUS_OK
        else:
            state_text = "⚠ ОТКЛЮЧЕНА"
            state_color = theme.STATUS_CAUTION
        self._status_label.setText(state_text)
        self._status_label.setAccessibleName(f"{self._name}: {state_text}")
        self._status_label.setStyleSheet(
            f"color: {state_color}; border: 1px solid {state_color};"
            f" border-radius: {theme.RADIUS_SM}px; padding: {theme.SPACE_1}px {theme.SPACE_2}px;"
            f" font-weight: {theme.FONT_WEIGHT_SEMIBOLD};"
        )
        self._toggle_button.setText("Отключить" if enabled else "Включить")
        apply_button_style(self._toggle_button, "warning" if enabled else "primary", compact=True)

    @Slot()
    def _toggle(self) -> None:
        self._on_toggle(self._name, not self._enabled)


class InterlockPanel(OverlayPanelBase, QWidget):
    """Engine-fed interlock list with direct, receipted enable/disable controls."""

    interlock_committed = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = QSettings("FIAN", "CryoDAQ")
        self._rows: dict[str, _InterlockRow] = {}
        self._last_results: dict[str, dict[str, Any]] = {}

        self.setObjectName("interlockPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"#interlockPanel {{ background: {theme.SURFACE_WINDOW}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, theme.SPACE_3)
        root.setSpacing(theme.SPACE_3)

        title = QLabel("ПРОГРАММНЫЕ БЛОКИРОВКИ")
        title.setFont(_title_font())
        title.setStyleSheet(f"color: {theme.FOREGROUND}; letter-spacing: 1px;")
        root.addWidget(title)

        warning = QLabel(
            "⚠ Отключение снижает защиту при исправных датчиках. Engine запишет решение, "
            "продолжит оценивать условие и предупредит при его нарушении; включить блокировку можно здесь же."
        )
        warning.setWordWrap(True)
        warning.setAccessibleName(warning.text())
        warning.setStyleSheet(
            f"color: {theme.FOREGROUND}; border-left: 3px solid {theme.STATUS_CAUTION};"
            f" background: {theme.SURFACE_CARD}; padding: {theme.SPACE_3}px;"
        )
        root.addWidget(warning)

        operator_label = QLabel("Оператор")
        operator_label.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
        root.addWidget(operator_label)
        self._operator_edit = QLineEdit()
        self._operator_edit.setFixedHeight(theme.ROW_HEIGHT)
        self._operator_edit.setAccessibleName("Оператор, принимающий решение по блокировке")
        saved_operator = self._settings.value("last_log_author", "")
        self._operator_edit.setText(saved_operator if type(saved_operator) is str else "")
        self._operator_edit.setStyleSheet(
            f"QLineEdit {{ background: {theme.SURFACE_CARD}; color: {theme.FOREGROUND};"
            f" border: 1px solid {theme.BORDER}; border-radius: {theme.RADIUS_SM}px;"
            f" padding: 0 {theme.SPACE_2}px; }}"
            f"QLineEdit:focus {{ border: 2px solid {theme.ACCENT}; }}"
        )
        operator_label.setBuddy(self._operator_edit)
        root.addWidget(self._operator_edit)

        self._banner = StatusBanner("Ожидание подтверждённого списка блокировок")
        self._banner.setAccessibleName(self._banner.text())
        root.addWidget(self._banner)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._content = QWidget()
        self._rows_layout = QVBoxLayout(self._content)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(theme.SPACE_3)
        self._rows_layout.addStretch()
        scroll.setWidget(self._content)
        root.addWidget(scroll, stretch=1)

    def set_interlocks(self, value: object, *, stale: bool = False) -> bool:
        snapshot = canonical_interlock_snapshot(value)
        if snapshot is None:
            self._banner.show_warning("Нет подтверждённого списка программных блокировок")
            self._banner.setAccessibleName(self._banner.text())
            for row in self._rows.values():
                row.set_state(row._enabled, stale=True)
            return False

        descriptor_keys = {
            row["name"]: (row["name"], row["description"], row["channel_ids"], row["action"]) for row in snapshot
        }
        if set(descriptor_keys) != set(self._rows) or any(
            self._rows[name].descriptor_key() != descriptor for name, descriptor in descriptor_keys.items()
        ):
            self._rebuild_rows(snapshot)
        for state in snapshot:
            self._rows[state["name"]].set_state(state["enabled"], stale=stale)
        if stale:
            self._banner.show_warning("Показано последнее подтверждённое состояние; текущая связь с Engine отсутствует")
        else:
            self._banner.show_info("Состояние подтверждено Engine")
        self._banner.setAccessibleName(self._banner.text())
        return True

    def _rebuild_rows(self, snapshot: tuple[dict[str, Any], ...]) -> None:
        while self._rows_layout.count() > 1:
            item = self._rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._rows = {}
        for state in snapshot:
            row = _InterlockRow(state, self._dispatch_toggle)
            self._rows[state["name"]] = row
            self._rows_layout.insertWidget(self._rows_layout.count() - 1, row)

    def _dispatch_toggle(self, name: str, enabled: bool) -> None:
        command = {
            "cmd": "interlock_set_enabled",
            "interlock_name": name,
            "enabled": enabled,
            "operator": self._operator_edit.text().strip(),
            "request_id": uuid.uuid4().hex,
        }
        self._banner.show_warning("Решение отправлено в Engine; ожидается запись и применение")
        self._banner.setAccessibleName(self._banner.text())
        worker = ZmqCommandWorker(command, parent=self)
        self._register_worker(worker, lambda result, target=name: self._on_toggle_result(target, result))

    def _on_toggle_result(self, name: str, result: dict) -> None:
        self._last_results[name] = dict(result) if type(result) is dict else {}
        state = result.get("interlock") if type(result) is dict else None
        if result.get("ok") is True and type(state) is dict:
            entry = result.get("entry")
            author = entry.get("author") if type(entry) is dict else None
            if type(author) is str and author:
                self._settings.setValue("last_log_author", author)
                self._settings.sync()
            notice = state.get("notice")
            self._banner.show_success(str(notice) if type(notice) is str else "Engine подтвердил решение")
            self._banner.setAccessibleName(self._banner.text())
            self.interlock_committed.emit(dict(state))
            return
        error = result.get("error") if type(result) is dict else None
        self._banner.show_error(str(error) if type(error) is str and error else "Engine не подтвердил решение")
        self._banner.setAccessibleName(self._banner.text())
