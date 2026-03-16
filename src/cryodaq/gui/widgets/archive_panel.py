from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QUrl, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from cryodaq.gui.widgets.common import (
    PanelHeader,
    StatusBanner,
    add_form_rows,
    build_action_row,
    create_panel_root,
    setup_standard_table,
)
from cryodaq.gui.zmq_client import send_command


class ArchivePanel(QWidget):
    _COLUMNS = ["Начало", "Эксперимент", "Шаблон", "Оператор", "Образец", "Статус", "Отчёт"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._entries: list[dict[str, Any]] = []
        self._build_ui()
        self.refresh_archive()

    def _build_ui(self) -> None:
        layout = create_panel_root(self)
        layout.addWidget(
            PanelHeader(
                "Архив экспериментов",
                "Поиск, проверка артефактов и открытие сохранённых отчётов.",
            )
        )

        filters = QGridLayout()
        self._template_filter = QComboBox()
        self._template_filter.addItem("Все шаблоны", "")
        self._operator_filter = QLineEdit()
        self._sample_filter = QLineEdit()
        self._start_filter = QLineEdit()
        self._end_filter = QLineEdit()
        self._report_filter = QComboBox()
        self._report_filter.addItem("Все", "")
        self._report_filter.addItem("Есть отчёт", "true")
        self._report_filter.addItem("Нет отчёта", "false")
        self._sort_filter = QComboBox()
        self._sort_filter.addItem("Сначала новые", ("start_time", True))
        self._sort_filter.addItem("Сначала старые", ("start_time", False))
        self._sort_filter.addItem("Оператор А-Я", ("operator", False))
        self._sort_filter.addItem("Образец А-Я", ("sample", False))
        self._refresh_button = QPushButton("Обновить")
        self._refresh_button.clicked.connect(self.refresh_archive)

        filters.addWidget(QLabel("Шаблон:"), 0, 0)
        filters.addWidget(self._template_filter, 0, 1)
        filters.addWidget(QLabel("Оператор:"), 0, 2)
        filters.addWidget(self._operator_filter, 0, 3)
        filters.addWidget(QLabel("Образец:"), 0, 4)
        filters.addWidget(self._sample_filter, 0, 5)
        filters.addWidget(QLabel("Начало >="), 1, 0)
        filters.addWidget(self._start_filter, 1, 1)
        filters.addWidget(QLabel("Конец <="), 1, 2)
        filters.addWidget(self._end_filter, 1, 3)
        filters.addWidget(QLabel("Отчёт:"), 1, 4)
        filters.addWidget(self._report_filter, 1, 5)
        filters.addWidget(QLabel("Сортировка:"), 2, 0)
        filters.addWidget(self._sort_filter, 2, 1)
        filters.addWidget(self._refresh_button, 2, 5)
        layout.addLayout(filters)

        body = QHBoxLayout()
        self._table = QTableWidget(0, len(self._COLUMNS))
        setup_standard_table(self._table, self._COLUMNS)
        self._table.itemSelectionChanged.connect(self._update_details)
        body.addWidget(self._table, 2)

        details_box = QGroupBox("Сведения")
        details_layout = QVBoxLayout(details_box)
        self._summary_label = QLabel("Эксперимент не выбран.")
        self._summary_label.setWordWrap(True)
        details_layout.addWidget(self._summary_label)

        meta_form = QFormLayout()
        self._template_label = QLabel("—")
        self._operator_label = QLabel("—")
        self._sample_label = QLabel("—")
        self._date_label = QLabel("—")
        self._artifact_label = QLabel("—")
        self._artifact_label.setWordWrap(True)
        self._report_label = QLabel("—")
        self._report_label.setWordWrap(True)
        add_form_rows(
            meta_form,
            [
                ("Шаблон:", self._template_label),
                ("Оператор:", self._operator_label),
                ("Образец:", self._sample_label),
                ("Диапазон:", self._date_label),
                ("Папка артефактов:", self._artifact_label),
                ("Файл отчёта:", self._report_label),
            ],
        )
        details_layout.addLayout(meta_form)

        self._notes_view = QTextEdit()
        self._notes_view.setReadOnly(True)
        self._notes_view.setMaximumHeight(140)
        self._notes_view.setPlaceholderText("Заметки по эксперименту отсутствуют.")
        details_layout.addWidget(self._notes_view)

        self._open_folder_button = QPushButton("Открыть папку")
        self._open_report_button = QPushButton("Открыть отчёт")
        self._regenerate_button = QPushButton("Сформировать отчёт")
        self._open_folder_button.clicked.connect(self._open_selected_folder)
        self._open_report_button.clicked.connect(self._open_selected_report)
        self._regenerate_button.clicked.connect(self._regenerate_selected_report)
        details_layout.addLayout(
            build_action_row(self._open_folder_button, self._open_report_button, self._regenerate_button)
        )

        self._status_label = StatusBanner()
        details_layout.addWidget(self._status_label)
        body.addWidget(details_box, 1)

        layout.addLayout(body, 1)
        self._clear_details()

    @Slot()
    def refresh_archive(self) -> None:
        sort_by, descending = self._sort_filter.currentData()
        payload: dict[str, Any] = {
            "cmd": "experiment_archive_list",
            "template_id": self._template_filter.currentData(),
            "operator": self._operator_filter.text().strip(),
            "sample": self._sample_filter.text().strip(),
            "start_date": self._start_filter.text().strip(),
            "end_date": self._end_filter.text().strip(),
            "sort_by": sort_by,
            "descending": descending,
        }
        report_value = self._report_filter.currentData()
        if report_value == "true":
            payload["report_present"] = True
        elif report_value == "false":
            payload["report_present"] = False

        result = send_command(payload)
        if not result.get("ok"):
            self._status_label.show_error(str(result.get("error", "Не удалось загрузить архив.")))
            return

        self._entries = list(result.get("entries", []))
        self._reload_template_choices()
        self._populate_table()
        if self._entries:
            self._status_label.show_info(f"Найдено экспериментов: {len(self._entries)}")
        else:
            self._status_label.show_warning("Эксперименты по текущему фильтру не найдены.")
        if self._table.rowCount() > 0:
            self._table.selectRow(0)
        else:
            self._clear_details("Эксперименты по текущему фильтру не найдены.")

    def _reload_template_choices(self) -> None:
        current_value = self._template_filter.currentData()
        labels = [self._template_filter.itemData(i) for i in range(self._template_filter.count())]
        seen = {value for value in labels if value}
        for entry in self._entries:
            template_id = str(entry.get("template_id", ""))
            template_name = str(entry.get("template_name", template_id))
            if template_id and template_id not in seen:
                self._template_filter.addItem(template_name, template_id)
                seen.add(template_id)
        index = self._template_filter.findData(current_value)
        if index >= 0:
            self._template_filter.setCurrentIndex(index)

    def _populate_table(self) -> None:
        self._table.setRowCount(0)
        for row, entry in enumerate(self._entries):
            self._table.insertRow(row)
            values = [
                self._format_datetime(entry.get("start_time")),
                str(entry.get("title", "")),
                str(entry.get("template_name", entry.get("template_id", ""))),
                str(entry.get("operator", "")),
                str(entry.get("sample", "")),
                str(entry.get("status", "")),
                "есть" if entry.get("report_present") else "нет",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, entry)
                self._table.setItem(row, col, item)
        self._table.resizeColumnsToContents()

    def _selected_entry(self) -> dict[str, Any] | None:
        row = self._table.currentRow()
        if row < 0:
            return None
        item = self._table.item(row, 0)
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    @Slot()
    def _update_details(self) -> None:
        entry = self._selected_entry()
        if not entry:
            self._clear_details()
            return

        report_enabled = bool(entry.get("report_enabled", True))
        report_path = self.resolve_report_path(entry)
        folder_path = self.resolve_folder_path(entry)
        self._summary_label.setText(
            f"{entry.get('title', '')}\n"
            f"Идентификатор: {entry.get('experiment_id', '')}\n"
            f"Статус: {entry.get('status', '—')}"
        )
        self._template_label.setText(str(entry.get("template_name", entry.get("template_id", ""))))
        self._operator_label.setText(str(entry.get("operator", "")))
        self._sample_label.setText(str(entry.get("sample", "")) or "—")
        self._date_label.setText(
            f"{self._format_datetime(entry.get('start_time'))} → {self._format_datetime(entry.get('end_time'))}"
        )
        self._artifact_label.setText(str(folder_path) if folder_path else "Папка артефактов не найдена")
        if report_path is not None:
            self._report_label.setText(str(report_path))
        elif report_enabled:
            self._report_label.setText("Файл отчёта отсутствует")
        else:
            self._report_label.setText("Отчёт не предусмотрен шаблоном")
        raw_notes = entry.get("notes")
        notes = "" if raw_notes is None else str(raw_notes).strip()
        self._notes_view.setPlainText(notes or "Заметки отсутствуют.")
        self._open_folder_button.setEnabled(folder_path is not None)
        self._open_report_button.setEnabled(report_path is not None)
        self._regenerate_button.setEnabled(report_enabled)
        self._regenerate_button.setText("Пересобрать отчёт" if report_path is not None else "Сформировать отчёт")

    def _clear_details(self, summary: str = "Эксперимент не выбран.") -> None:
        self._summary_label.setText(summary)
        self._template_label.setText("—")
        self._operator_label.setText("—")
        self._sample_label.setText("—")
        self._date_label.setText("—")
        self._artifact_label.setText("—")
        self._report_label.setText("—")
        self._notes_view.setPlainText("Выберите эксперимент, чтобы увидеть сведения и артефакты.")
        self._open_folder_button.setEnabled(False)
        self._open_report_button.setEnabled(False)
        self._regenerate_button.setEnabled(False)
        self._regenerate_button.setText("Сформировать отчёт")

    @staticmethod
    def resolve_report_path(entry: dict[str, Any]) -> Path | None:
        pdf_path = str(entry.get("pdf_path", "")).strip()
        if pdf_path:
            path = Path(pdf_path)
            if path.exists():
                return path
        docx_path = str(entry.get("docx_path", "")).strip()
        if docx_path:
            path = Path(docx_path)
            if path.exists():
                return path
        return None

    @staticmethod
    def resolve_folder_path(entry: dict[str, Any]) -> Path | None:
        root = str(entry.get("artifact_dir", "")).strip()
        if not root:
            return None
        path = Path(root)
        return path if path.exists() else None

    @staticmethod
    def _open_path(path: Path) -> bool:
        return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    @Slot()
    def _open_selected_folder(self) -> None:
        entry = self._selected_entry()
        if not entry:
            return
        folder = self.resolve_folder_path(entry)
        if folder is None or not self._open_path(folder):
            QMessageBox.warning(
                self,
                "Архив экспериментов",
                "Папка артефактов отсутствует или не открывается. Проверьте запись архива.",
            )

    @Slot()
    def _open_selected_report(self) -> None:
        entry = self._selected_entry()
        if not entry:
            return
        report = self.resolve_report_path(entry)
        if report is None or not self._open_path(report):
            QMessageBox.warning(
                self,
                "Архив экспериментов",
                "Файл отчёта отсутствует или не открывается. Сначала сформируйте отчёт или откройте папку артефактов.",
            )

    @Slot()
    def _regenerate_selected_report(self) -> None:
        entry = self._selected_entry()
        if not entry:
            return
        if not bool(entry.get("report_enabled", True)):
            self._status_label.show_warning("Для этого шаблона формирование отчёта отключено.")
            return
        result = send_command(
            {"cmd": "experiment_generate_report", "experiment_id": entry.get("experiment_id", "")}
        )
        if not result.get("ok"):
            error_text = str(result.get("error", "Не удалось сформировать отчёт."))
            self._status_label.show_error(error_text)
            return
        report = result.get("report", {})
        if report.get("skipped"):
            self._status_label.show_warning(str(report.get("reason", "Формирование отчёта пропущено.")))
        else:
            self._status_label.show_success(f"Отчёт обновлён: {report.get('docx_path', '')}")
        self.refresh_archive()

    @staticmethod
    def _format_datetime(raw: Any) -> str:
        text = str(raw or "").strip()
        if not text:
            return "—"
        try:
            if text.endswith("Z"):
                text = f"{text[:-1]}+00:00"
            return datetime.fromisoformat(text).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return text
