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
                "Поиск, проверка артефактов и открытие сырых PDF и редактируемых DOCX.",
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
                ("Файлы отчёта:", self._report_label),
            ],
        )
        details_layout.addLayout(meta_form)

        self._notes_view = QTextEdit()
        self._notes_view.setReadOnly(True)
        self._notes_view.setMaximumHeight(120)
        self._notes_view.setPlaceholderText("Заметки по эксперименту отсутствуют.")
        details_layout.addWidget(self._notes_view)

        self._archive_stats_label = QLabel("Состав архивной записи: —")
        self._archive_stats_label.setWordWrap(True)
        details_layout.addWidget(self._archive_stats_label)

        self._runs_view = QTextEdit()
        self._runs_view.setReadOnly(True)
        self._runs_view.setMaximumHeight(110)
        runs_box = QGroupBox("Runs")
        runs_layout = QVBoxLayout(runs_box)
        runs_layout.addWidget(self._runs_view)
        details_layout.addWidget(runs_box)

        self._artifacts_view = QTextEdit()
        self._artifacts_view.setReadOnly(True)
        self._artifacts_view.setMaximumHeight(130)
        artifacts_box = QGroupBox("Artifacts")
        artifacts_layout = QVBoxLayout(artifacts_box)
        artifacts_layout.addWidget(self._artifacts_view)
        details_layout.addWidget(artifacts_box)

        self._results_view = QTextEdit()
        self._results_view.setReadOnly(True)
        self._results_view.setMaximumHeight(110)
        results_box = QGroupBox("Results")
        results_layout = QVBoxLayout(results_box)
        results_layout.addWidget(self._results_view)
        details_layout.addWidget(results_box)

        self._open_folder_button = QPushButton("Открыть папку")
        self._open_pdf_button = QPushButton("Открыть PDF")
        self._open_docx_button = QPushButton("Открыть DOCX")
        self._regenerate_button = QPushButton("Перегенерировать отчёты")
        self._open_folder_button.clicked.connect(self._open_selected_folder)
        self._open_pdf_button.clicked.connect(self._open_selected_pdf)
        self._open_docx_button.clicked.connect(self._open_selected_docx)
        self._regenerate_button.clicked.connect(self._regenerate_selected_report)
        details_layout.addLayout(
            build_action_row(
                self._open_folder_button,
                self._open_pdf_button,
                self._open_docx_button,
                self._regenerate_button,
            )
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
        seen = {self._template_filter.itemData(i) for i in range(self._template_filter.count())}
        for entry in self._entries:
            template_id = str(entry.get("template_id", "")).strip()
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
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    @Slot()
    def _update_details(self) -> None:
        entry = self._selected_entry()
        if not entry:
            self._clear_details()
            return

        report_enabled = bool(entry.get("report_enabled", True))
        pdf_path = self.resolve_pdf_path(entry)
        docx_path = self.resolve_docx_path(entry)
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
        if pdf_path or docx_path:
            self._report_label.setText(
                f"PDF: {pdf_path or 'нет'}\nDOCX: {docx_path or 'нет'}"
            )
        elif report_enabled:
            self._report_label.setText("Файлы отчёта отсутствуют")
        else:
            self._report_label.setText("Отчёт не предусмотрен шаблоном")

        raw_notes = entry.get("notes")
        notes = "" if raw_notes is None else str(raw_notes).strip()
        self._notes_view.setPlainText(notes or "Заметки отсутствуют.")
        self._archive_stats_label.setText(
            "Состав архивной записи: "
            f"runs={int(entry.get('run_record_count', 0) or 0)}, "
            f"artifacts={int(entry.get('artifact_count', 0) or 0)}, "
            f"results={int(entry.get('result_table_count', 0) or 0)}"
        )
        self._runs_view.setPlainText(self._format_run_records(entry))
        self._artifacts_view.setPlainText(self._format_artifacts(entry))
        self._results_view.setPlainText(self._format_results(entry))
        self._open_folder_button.setEnabled(folder_path is not None)
        self._open_pdf_button.setEnabled(pdf_path is not None)
        self._open_docx_button.setEnabled(docx_path is not None)
        self._regenerate_button.setEnabled(report_enabled)

    def _clear_details(self, summary: str = "Эксперимент не выбран.") -> None:
        self._summary_label.setText(summary)
        self._template_label.setText("—")
        self._operator_label.setText("—")
        self._sample_label.setText("—")
        self._date_label.setText("—")
        self._artifact_label.setText("—")
        self._report_label.setText("—")
        self._notes_view.setPlainText("Выберите эксперимент, чтобы увидеть сведения и артефакты.")
        self._archive_stats_label.setText("Состав архивной записи: —")
        self._runs_view.setPlainText("Run records ещё нет.")
        self._artifacts_view.setPlainText("Артефактов ещё нет.")
        self._results_view.setPlainText("Result tables ещё нет.")
        self._open_folder_button.setEnabled(False)
        self._open_pdf_button.setEnabled(False)
        self._open_docx_button.setEnabled(False)
        self._regenerate_button.setEnabled(False)

    @staticmethod
    def _format_run_records(entry: dict[str, Any]) -> str:
        records = [item for item in entry.get("run_records", []) if isinstance(item, dict)]
        if not records:
            return "Run records отсутствуют."
        return "\n".join(
            (
                f"{str(item.get('run_type', '')).strip() or 'run'} | "
                f"{str(item.get('source_tab', '')).strip() or 'unknown'} | "
                f"{str(item.get('status', '')).strip() or 'UNKNOWN'} | "
                f"start={str(item.get('started_at', '')).strip() or '—'} | "
                f"finish={str(item.get('finished_at', '')).strip() or '—'} | "
                f"artifacts={len([path for path in item.get('artifact_paths', []) if str(path).strip()])}"
            )
            for item in records
        )

    @staticmethod
    def _format_artifacts(entry: dict[str, Any]) -> str:
        artifacts = [item for item in entry.get("artifact_index", []) if isinstance(item, dict)]
        if not artifacts:
            return "Артефакты отсутствуют."
        return "\n".join(
            f"{str(item.get('category', '')).strip() or 'artifact'} | "
            f"{str(item.get('role', '')).strip() or 'unknown'} | "
            f"{str(item.get('path', '')).strip() or '—'}"
            for item in artifacts
        )

    @staticmethod
    def _format_results(entry: dict[str, Any]) -> str:
        results = [item for item in entry.get("result_tables", []) if isinstance(item, dict)]
        summary = dict(entry.get("summary_metadata") or {})
        if not results and not summary:
            return "Result tables отсутствуют."
        lines = [
            f"{str(item.get('table_id', '')).strip() or 'table'} | rows={item.get('row_count', 0)} | {str(item.get('path', '')).strip() or '—'}"
            for item in results
        ]
        if summary:
            lines.append("summary | " + ", ".join(f"{key}={value}" for key, value in sorted(summary.items())))
        return "\n".join(lines)

    @staticmethod
    def _report_candidate_paths(entry: dict[str, Any], key: str, *fallbacks: str) -> list[Path]:
        paths: list[Path] = []
        primary = str(entry.get(key, "")).strip()
        if primary:
            paths.append(Path(primary))
        artifact_dir = str(entry.get("artifact_dir", "")).strip()
        if artifact_dir:
            root = Path(artifact_dir) / "reports"
            for name in fallbacks:
                paths.append(root / name)
        return paths

    @classmethod
    def resolve_pdf_path(cls, entry: dict[str, Any]) -> Path | None:
        for path in cls._report_candidate_paths(entry, "pdf_path", "report_raw.pdf", "report.pdf"):
            if path.exists():
                return path
        return None

    @classmethod
    def resolve_docx_path(cls, entry: dict[str, Any]) -> Path | None:
        for path in cls._report_candidate_paths(entry, "docx_path", "report_editable.docx", "report.docx"):
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
            QMessageBox.warning(self, "Архив экспериментов", "Папка артефактов отсутствует или не открывается.")

    @Slot()
    def _open_selected_pdf(self) -> None:
        entry = self._selected_entry()
        if not entry:
            return
        path = self.resolve_pdf_path(entry)
        if path is None or not self._open_path(path):
            QMessageBox.warning(self, "Архив экспериментов", "Сырой PDF отсутствует или не открывается.")

    @Slot()
    def _open_selected_docx(self) -> None:
        entry = self._selected_entry()
        if not entry:
            return
        path = self.resolve_docx_path(entry)
        if path is None or not self._open_path(path):
            QMessageBox.warning(self, "Архив экспериментов", "Редактируемый DOCX отсутствует или не открывается.")

    @Slot()
    def _regenerate_selected_report(self) -> None:
        entry = self._selected_entry()
        if not entry:
            return
        if not bool(entry.get("report_enabled", True)):
            self._status_label.show_warning("Для этого шаблона формирование отчёта отключено.")
            return
        result = send_command({"cmd": "experiment_generate_report", "experiment_id": entry.get("experiment_id", "")})
        if not result.get("ok"):
            self._status_label.show_error(str(result.get("error", "Не удалось сформировать отчёт.")))
            return
        report = result.get("report", {})
        if report.get("skipped"):
            message = str(report.get("reason", "Формирование отчёта пропущено."))
            self.refresh_archive()
            self._status_label.show_warning(message)
        else:
            message = f"Отчёты обновлены: PDF={report.get('pdf_path') or 'нет'}, DOCX={report.get('docx_path') or 'нет'}"
            self.refresh_archive()
            self._status_label.show_success(message)

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
