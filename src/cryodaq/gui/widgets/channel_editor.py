"""Диалог редактирования каналов.

Позволяет оператору изменять отображаемые имена датчиков,
включать/выключать их видимость. Сохраняет в channels.yaml.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cryodaq.core.channel_manager import get_channel_manager
from cryodaq.gui import theme
from cryodaq.gui.widgets.common import apply_button_style

logger = logging.getLogger(__name__)


class ChannelEditorDialog(QDialog):
    """Диалог редактирования имён и видимости каналов."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Редактор каналов — CryoDAQ")
        self.setMinimumSize(600, 500)

        self._mgr = get_channel_manager()
        self._edits: dict[str, QLineEdit] = {}
        self._checks: dict[str, QCheckBox] = {}

        self._build_ui()
        self._populate()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("Настройка имён и видимости температурных каналов")
        title.setFont(QFont("", 11, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {theme.TEXT_ACCENT};")
        layout.addWidget(title)

        hint = QLabel(
            "Отключите видимость для неиспользуемых каналов.\n"
            "Имена отображаются на всех панелях и в Telegram."
        )
        hint.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        layout.addWidget(hint)

        # Таблица
        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Канал", "Имя", "Видимый"])
        self._table.verticalHeader().setVisible(False)
        h = self._table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self._table, stretch=1)

        # Кнопки
        btns = QHBoxLayout()
        btns.addStretch()

        reset_btn = QPushButton("Сбросить")
        apply_button_style(reset_btn, "neutral")
        reset_btn.clicked.connect(self._on_reset)
        btns.addWidget(reset_btn)

        apply_btn = QPushButton("Применить")
        apply_button_style(apply_btn, "primary")
        apply_btn.clicked.connect(self._on_apply)
        btns.addWidget(apply_btn)

        layout.addLayout(btns)

    def _populate(self) -> None:
        """Заполнить таблицу из ChannelManager."""
        channels = self._mgr.get_all()
        self._table.setRowCount(len(channels))
        self._edits.clear()
        self._checks.clear()

        for row, (ch_id, info) in enumerate(channels.items()):
            # ID
            id_item = QTableWidgetItem(ch_id)
            id_item.setFlags(id_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, 0, id_item)

            # Имя
            edit = QLineEdit(info.get("name", ""))
            self._edits[ch_id] = edit
            self._table.setCellWidget(row, 1, edit)

            # Видимый
            cb = QCheckBox()
            cb.setChecked(info.get("visible", True))
            self._checks[ch_id] = cb
            container = QWidget()
            cl = QHBoxLayout(container)
            cl.setAlignment(Qt.AlignCenter)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.addWidget(cb)
            self._table.setCellWidget(row, 2, container)

    @Slot()
    def _on_apply(self) -> None:
        """Сохранить изменения."""
        for ch_id, edit in self._edits.items():
            self._mgr.set_name(ch_id, edit.text())
        for ch_id, cb in self._checks.items():
            self._mgr.set_visible(ch_id, cb.isChecked())
        self._mgr.save()
        logger.info("Конфигурация каналов сохранена")
        self.accept()

    @Slot()
    def _on_reset(self) -> None:
        """Перезагрузить из файла."""
        self._mgr.load()
        self._populate()
