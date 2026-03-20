from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cryodaq.drivers.base import Reading
from cryodaq.gui.widgets.common import PanelHeader, StatusBanner, build_action_row, create_panel_root
from cryodaq.gui.zmq_client import send_command


class OperatorLogPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._entries: list[dict] = []

        layout = create_panel_root(self)
        layout.addWidget(
            PanelHeader(
                "Служебный журнал",
                "Вторичный технический лог для совместимости и сервисных заметок. Основная карточка эксперимента ведётся на главной странице.",
            )
        )

        from PySide6.QtCore import QSettings
        self._settings = QSettings("FIAN", "CryoDAQ")
        self._author_edit = QLineEdit()
        self._author_edit.setPlaceholderText("Автор")
        self._author_edit.setMaximumWidth(220)
        saved_author = self._settings.value("last_log_author", "")
        if saved_author:
            self._author_edit.setText(saved_author)
        self._current_only = QCheckBox("Только текущий эксперимент")
        self._current_only.setChecked(False)
        self._refresh_button = QPushButton("Обновить список")
        self._refresh_button.clicked.connect(self.refresh_entries)
        controls_row = build_action_row(
            QLabel("Автор:"),
            self._author_edit,
            self._current_only,
            self._refresh_button,
            add_stretch=True,
        )
        layout.addLayout(controls_row)

        self._message_edit = QPlainTextEdit()
        self._message_edit.setPlaceholderText("Введите операторскую запись")
        self._message_edit.setMaximumBlockCount(1000)
        self._message_edit.setFixedHeight(120)
        layout.addWidget(self._message_edit)

        self._submit_button = QPushButton("Сохранить запись")
        self._submit_button.clicked.connect(self._on_submit)
        self._status_label = StatusBanner()
        action_row = build_action_row(self._submit_button, self._status_label)
        layout.addLayout(action_row)

        self._entries_list = QListWidget()
        layout.addWidget(self._entries_list, 1)

        self.refresh_entries()

    def on_reading(self, reading: Reading) -> None:
        if reading.channel != "analytics/operator_log_entry":
            return
        self.refresh_entries()

    @Slot()
    def refresh_entries(self) -> None:
        payload: dict[str, object] = {"cmd": "log_get", "limit": 50}
        if self._current_only.isChecked():
            payload["current_experiment"] = True
        result = send_command(payload)
        if not result.get("ok"):
            self._entries_list.clear()
            self._status_label.show_error(str(result.get("error", "Не удалось загрузить журнал.")))
            return

        self._entries = list(result.get("entries", []))
        self._entries_list.clear()
        if not self._entries:
            self._entries_list.addItem(
                QListWidgetItem("Записи отсутствуют. Нажмите «Обновить список» или добавьте новую запись.")
            )
            self._status_label.show_warning("Записей по текущему фильтру нет.")
            return

        for entry in self._entries:
            item = QListWidgetItem(self._format_entry(entry))
            if str(entry.get("author", "")).strip() == "system":
                item.setForeground(QColor("#666666"))
            self._entries_list.addItem(item)
        self._status_label.show_info(f"Показано записей: {len(self._entries)}")

    @Slot()
    def _on_submit(self) -> None:
        message = self._message_edit.toPlainText().strip()
        if not message:
            self._status_label.show_warning("Введите текст записи.")
            return

        payload = {
            "cmd": "log_entry",
            "message": message,
            "author": self._author_edit.text().strip(),
            "source": "gui",
        }
        if self._current_only.isChecked():
            payload["current_experiment"] = True

        result = send_command(payload)
        if not result.get("ok"):
            self._status_label.show_error(str(result.get("error", "Не удалось сохранить запись.")))
            return

        self._settings.setValue("last_log_author", self._author_edit.text().strip())
        self._message_edit.clear()
        self._status_label.show_success("Запись сохранена.")
        self.refresh_entries()

    @staticmethod
    def _format_entry(entry: dict) -> str:
        raw_ts = str(entry.get("timestamp", ""))
        try:
            stamp = datetime.fromisoformat(raw_ts.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            stamp = raw_ts
        author = str(entry.get("author", "")).strip()
        source = str(entry.get("source", "")).strip()
        who = author or source or "system"
        experiment_id = str(entry.get("experiment_id") or "").strip()
        prefix = f"[{stamp}] {who}"
        if experiment_id:
            prefix += f" ({experiment_id})"
        tags = entry.get("tags") or []
        suffix = f" [{', '.join(tags)}]" if tags else ""
        return f"{prefix}: {entry.get('message', '')}{suffix}"
