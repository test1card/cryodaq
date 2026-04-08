"""Диалог настройки подключения приборов.

Позволяет редактировать адреса, порты и параметры подключения
приборов. Сохраняет в instruments.local.yaml.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from PySide6.QtCore import Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

from cryodaq.paths import get_config_dir as _get_config_dir

_CONFIG_DIR = _get_config_dir()
_LOCAL_CONFIG = _CONFIG_DIR / "instruments.local.yaml"
_DEFAULT_CONFIG = _CONFIG_DIR / "instruments.yaml"

_INSTRUMENT_TYPES = ["lakeshore_218s", "keithley_2604b", "thyracont_vsp63d"]
_CONN_TYPES = {"lakeshore_218s": "GPIB", "keithley_2604b": "USB-TMC", "thyracont_vsp63d": "Serial"}


class ConnectionSettingsDialog(QDialog):
    """Диалог настройки подключения приборов."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Подключение приборов — CryoDAQ")
        self.setMinimumSize(900, 500)

        self._instruments: list[dict[str, Any]] = []
        self._rows: list[dict[str, QWidget]] = []

        self._load_config()
        self._build_ui()

    def _load_config(self) -> None:
        """Загрузить конфигурацию (local → default)."""
        cfg_path = _LOCAL_CONFIG if _LOCAL_CONFIG.exists() else _DEFAULT_CONFIG
        if cfg_path.exists():
            with cfg_path.open(encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            self._instruments = raw.get("instruments", [])
        logger.info("Загружена конфигурация: %s (%d приборов)", cfg_path.name, len(self._instruments))

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("Настройка подключения приборов")
        title.setFont(QFont("", 11, QFont.Weight.Bold))
        title.setStyleSheet("color: #58a6ff;")
        layout.addWidget(title)

        hint = QLabel(
            "Изменения сохраняются в instruments.local.yaml (не затрагивают шаблон).\n"
            "После изменений перезапустите Engine."
        )
        hint.setStyleSheet("color: #8b949e;")
        layout.addWidget(hint)

        # Таблица
        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels([
            "Имя", "Тип", "Адрес", "Бод", "Интервал (с)", "Действия",
        ])
        self._table.verticalHeader().setVisible(False)
        h = self._table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self._table, stretch=1)

        self._populate()

        # Кнопки
        btns = QHBoxLayout()

        add_btn = QPushButton("Добавить прибор")
        add_btn.setStyleSheet(
            "QPushButton { background: #238636; color: white; border: none; "
            "padding: 6px 14px; border-radius: 4px; }"
        )
        add_btn.clicked.connect(self._on_add)
        btns.addWidget(add_btn)

        btns.addStretch()

        apply_btn = QPushButton("Применить")
        apply_btn.setStyleSheet(
            "QPushButton { background: #1f6feb; color: white; border: none; "
            "padding: 6px 16px; border-radius: 4px; }"
            "QPushButton:hover { background: #388bfd; }"
        )
        apply_btn.clicked.connect(self._on_apply)
        btns.addWidget(apply_btn)

        layout.addLayout(btns)

    def _populate(self) -> None:
        """Заполнить таблицу из конфигурации."""
        self._table.setRowCount(len(self._instruments))
        self._rows.clear()

        for row, inst in enumerate(self._instruments):
            self._add_row(row, inst)

    def _add_row(self, row: int, inst: dict[str, Any]) -> None:
        """Добавить строку прибора в таблицу."""
        widgets: dict[str, QWidget] = {}

        # Имя
        name_edit = QLineEdit(inst.get("name", ""))
        self._table.setCellWidget(row, 0, name_edit)
        widgets["name"] = name_edit

        # Тип
        type_combo = QComboBox()
        type_combo.addItems(_INSTRUMENT_TYPES)
        current_type = inst.get("type", "lakeshore_218s")
        if current_type in _INSTRUMENT_TYPES:
            type_combo.setCurrentText(current_type)
        self._table.setCellWidget(row, 1, type_combo)
        widgets["type"] = type_combo

        # Адрес
        addr_edit = QLineEdit(inst.get("resource", ""))
        addr_edit.setPlaceholderText("GPIB0::12::INSTR / COM3 / USB0::...")
        self._table.setCellWidget(row, 2, addr_edit)
        widgets["resource"] = addr_edit

        # Бод
        baud_spin = QSpinBox()
        baud_spin.setRange(300, 115200)
        baud_spin.setValue(inst.get("baudrate", 9600))
        self._table.setCellWidget(row, 3, baud_spin)
        widgets["baudrate"] = baud_spin

        # Интервал
        poll_spin = QDoubleSpinBox()
        poll_spin.setRange(0.1, 60.0)
        poll_spin.setValue(inst.get("poll_interval_s", 1.0))
        poll_spin.setDecimals(1)
        self._table.setCellWidget(row, 4, poll_spin)
        widgets["poll"] = poll_spin

        # Кнопки действий
        action_widget = QWidget()
        al = QHBoxLayout(action_widget)
        al.setContentsMargins(2, 2, 2, 2)
        al.setSpacing(4)

        del_btn = QPushButton("Удалить")
        del_btn.setStyleSheet(
            "QPushButton { background: #da3633; color: white; border: none; "
            "padding: 3px 8px; border-radius: 3px; font-size: 11px; }"
        )
        del_btn.clicked.connect(lambda checked=False, r=row: self._on_delete(r))
        al.addWidget(del_btn)

        self._table.setCellWidget(row, 5, action_widget)
        widgets["actions"] = action_widget

        self._rows.append(widgets)

    @Slot()
    def _on_add(self) -> None:
        """Добавить новый прибор."""
        new_inst = {
            "type": "lakeshore_218s",
            "name": f"Прибор_{len(self._instruments) + 1}",
            "resource": "",
            "poll_interval_s": 1.0,
        }
        self._instruments.append(new_inst)
        row = self._table.rowCount()
        self._table.setRowCount(row + 1)
        self._add_row(row, new_inst)

    def _on_delete(self, row: int) -> None:
        """Удалить прибор."""
        if row < len(self._instruments):
            name = self._instruments[row].get("name", "?")
            reply = QMessageBox.question(
                self, "Удалить прибор",
                f"Удалить {name}?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._instruments.pop(row)
                self._populate()

    @Slot()
    def _on_apply(self) -> None:
        """Сохранить в instruments.local.yaml."""
        # Собрать данные из таблицы
        instruments = []
        for row in range(self._table.rowCount()):
            if row >= len(self._rows):
                break
            w = self._rows[row]
            inst: dict[str, Any] = {
                "type": w["type"].currentText(),
                "name": w["name"].text(),
                "resource": w["resource"].text(),
                "poll_interval_s": w["poll"].value(),
            }
            if inst["type"] == "thyracont_vsp63d":
                inst["baudrate"] = w["baudrate"].value()
            # Preserve channels for lakeshore
            if row < len(self._instruments) and "channels" in self._instruments[row]:
                inst["channels"] = self._instruments[row]["channels"]
            instruments.append(inst)

        # Save
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with _LOCAL_CONFIG.open("w", encoding="utf-8") as fh:
            yaml.dump(
                {"instruments": instruments},
                fh, allow_unicode=True, default_flow_style=False, sort_keys=False,
            )
        logger.info("Конфигурация приборов сохранена: %s", _LOCAL_CONFIG)

        QMessageBox.information(
            self, "Сохранено",
            f"Конфигурация сохранена в:\n{_LOCAL_CONFIG}\n\n"
            "Перезапустите Engine для применения изменений.",
        )
        self.accept()
