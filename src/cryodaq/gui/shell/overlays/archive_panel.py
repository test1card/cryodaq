"""ArchivePanel — Phase II.2 experiment archive overlay.

Supersedes the v1 widget at ``src/cryodaq/gui/widgets/archive_panel.py``.
Aligned with Design System v1.0.1 tokens and integrates K6 bulk export
migration (CSV / HDF5 / Excel) into a dedicated «Экспорт данных» card
— the legacy File menu was the only export pathway, but ``MainWindowV2``
has no menu bar.

Layout (top to bottom):
    Header (АРХИВ ЭКСПЕРИМЕНТОВ)
    Status banner (transient info/warning/error, auto-clear 4 s)
    Filter bar card (template / operator / sample / date range / report / sort + refresh)
    Content split (list card | details card)
    Export card (CSV / HDF5 / Excel buttons, QThread workers)

Public API (host push points):
- ``on_reading(reading)`` — contract no-op (engine has no broker event on
  experiment finalization; manual refresh + post-regenerate refresh only).
- ``set_connected(bool)`` — gates refresh / regenerate / export buttons;
  folder / report open actions stay enabled (local filesystem).

Out of scope (follow-ups):
- Per-experiment data export (this card exports ALL SQLite data globally).
- Auto-refresh on engine finalization event (no such event exists yet).
- Ranged export with date filter (exporters support it; UI omits for now).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QDate, QObject, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cryodaq.drivers.base import Reading
from cryodaq.gui import theme
from cryodaq.gui.zmq_client import ZmqCommandWorker

logger = logging.getLogger(__name__)

_BANNER_AUTO_CLEAR_MS = 4000

_SORT_OPTIONS: tuple[tuple[str, str, bool], ...] = (
    # (label, sort_by, descending)
    ("Сначала новые", "start_time", True),
    ("Сначала старые", "start_time", False),
    ("Оператор А-Я", "operator", False),
    ("Образец А-Я", "sample", False),
)

_REPORT_OPTIONS: tuple[tuple[str, str], ...] = (
    # (label, payload_value) — payload_value maps to engine's report_present flag
    ("Все", ""),
    ("Есть отчёт", "true"),
    ("Нет отчёта", "false"),
)

_TABLE_COLUMNS: tuple[str, ...] = (
    "Начало",
    "Конец",
    "Эксперимент",
    "Шаблон",
    "Оператор",
    "Образец",
    "Статус",
    "Отчёт",
    "Данные",
)


def _label_font() -> QFont:
    font = QFont(theme.FONT_BODY)
    font.setPixelSize(theme.FONT_LABEL_SIZE)
    font.setWeight(QFont.Weight(theme.FONT_LABEL_WEIGHT))
    return font


def _body_font() -> QFont:
    font = QFont(theme.FONT_BODY)
    font.setPixelSize(theme.FONT_BODY_SIZE)
    return font


def _title_font() -> QFont:
    font = QFont(theme.FONT_BODY)
    font.setPixelSize(theme.FONT_SIZE_XL)
    font.setWeight(QFont.Weight(theme.FONT_WEIGHT_SEMIBOLD))
    return font


def _mono_cell_font() -> QFont:
    font = QFont(theme.FONT_MONO)
    font.setPixelSize(theme.FONT_LABEL_SIZE)
    try:
        font.setFeature(QFont.Tag("tnum"), 1)
    except (AttributeError, TypeError):
        pass
    return font


def _style_button(btn: QPushButton, variant: str) -> None:
    radius = theme.RADIUS_MD
    if variant == "primary":
        # Phase III.A: primary uses ACCENT (UI activation), not STATUS_OK.
        bg, fg = theme.ACCENT, theme.ON_ACCENT
    elif variant == "warning":
        bg, fg = theme.STATUS_WARNING, theme.ON_PRIMARY
    elif variant == "accent":
        bg, fg = theme.ACCENT, theme.ON_ACCENT
    else:  # "neutral"
        bg, fg = theme.SURFACE_MUTED, theme.FOREGROUND
    btn.setStyleSheet(
        f"QPushButton {{"
        f" background-color: {bg};"
        f" color: {fg};"
        f" border: 1px solid {theme.BORDER_SUBTLE};"
        f" border-radius: {radius}px;"
        f" padding: {theme.SPACE_1}px {theme.SPACE_3}px;"
        f" font-weight: {theme.FONT_WEIGHT_SEMIBOLD};"
        f"}}"
        f" QPushButton:disabled {{"
        f" background-color: {theme.SURFACE_MUTED};"
        f" color: {theme.MUTED_FOREGROUND};"
        f" border: 1px solid {theme.BORDER_SUBTLE};"
        f"}}"
    )


def _style_input(widget: QLineEdit | QPlainTextEdit | QComboBox | QDateEdit) -> None:
    widget.setStyleSheet(
        f"QLineEdit, QPlainTextEdit, QComboBox, QDateEdit {{"
        f" background-color: {theme.SURFACE_SUNKEN};"
        f" color: {theme.FOREGROUND};"
        f" border: 1px solid {theme.BORDER_SUBTLE};"
        f" border-radius: {theme.RADIUS_SM}px;"
        f" padding: {theme.SPACE_1}px {theme.SPACE_2}px;"
        f"}}"
        f" QLineEdit:disabled, QPlainTextEdit:disabled,"
        f" QComboBox:disabled, QDateEdit:disabled {{"
        f" color: {theme.MUTED_FOREGROUND};"
        f"}}"
    )


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


def resolve_pdf_path(entry: dict[str, Any]) -> Path | None:
    for path in _report_candidate_paths(entry, "pdf_path", "report_raw.pdf", "report.pdf"):
        if path.exists():
            return path
    return None


def resolve_docx_path(entry: dict[str, Any]) -> Path | None:
    for path in _report_candidate_paths(entry, "docx_path", "report_editable.docx", "report.docx"):
        if path.exists():
            return path
    return None


def resolve_folder_path(entry: dict[str, Any]) -> Path | None:
    root = str(entry.get("artifact_dir", "")).strip()
    if not root:
        return None
    path = Path(root)
    return path if path.exists() else None


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


def _format_run_records(entry: dict[str, Any]) -> str:
    records = [item for item in entry.get("run_records", []) if isinstance(item, dict)]
    if not records:
        return "Записей прогонов нет."
    return "\n".join(
        (
            f"{str(item.get('record_id', '')).strip() or 'run'} | "
            f"start={str(item.get('started_at', '')).strip() or '—'} | "
            f"finish={str(item.get('finished_at', '')).strip() or '—'} | "
            f"artifacts="
            f"{len([p for p in item.get('artifact_paths', []) if str(p).strip()])}"
        )
        for item in records
    )


def _format_artifacts(entry: dict[str, Any]) -> str:
    """Format artifact index. DS v1.0.1: no emoji per RULE-COPY-005.

    Legacy convention used pictographic role glyphs; replaced with ASCII
    bracketed tags [ДАННЫЕ] / [ИЗМЕРЕНИЯ] / [УСТАВКИ] that convey the
    same role without an emoji dependency.
    """
    artifacts = [item for item in entry.get("artifact_index", []) if isinstance(item, dict)]
    if not artifacts:
        return "Артефакты отсутствуют."
    lines: list[str] = []
    for item in artifacts:
        role = str(item.get("role", "")).strip() or "unknown"
        summary = item.get("summary", {}) if isinstance(item.get("summary"), dict) else {}
        if role == "experiment_data":
            row_count = summary.get("row_count", "?")
            fmt = summary.get("format", "?")
            channels = summary.get("channels", [])
            ch_count = len(channels) if isinstance(channels, list) else "?"
            path = Path(str(item.get("path", "")))
            size_str = ""
            if path.exists():
                size_kb = path.stat().st_size / 1024
                size_str = (
                    f" | {size_kb / 1024:.1f} MB" if size_kb > 1024 else f" | {size_kb:.0f} KB"
                )
            lines.append(f"[ДАННЫЕ] | {fmt} | {row_count} строк | {ch_count} каналов{size_str}")
        elif role == "measured_values":
            lines.append(f"[ИЗМЕРЕНИЯ] | {summary.get('rows', '?')} строк | CSV")
        elif role == "setpoint_values":
            lines.append(f"[УСТАВКИ] | {summary.get('rows', '?')} строк | CSV")
        else:
            category = str(item.get("category", "")).strip() or "artifact"
            path_text = str(item.get("path", "")).strip() or "—"
            lines.append(f"{category} | {role} | {path_text}")
    return "\n".join(lines)


def _format_results(entry: dict[str, Any]) -> str:
    results = [item for item in entry.get("result_tables", []) if isinstance(item, dict)]
    summary = dict(entry.get("summary_metadata") or {})
    if not results and not summary:
        return "Таблиц результатов нет."
    lines = [
        f"{str(item.get('table_id', '')).strip() or 'table'} | "
        f"rows={item.get('row_count', 0)} | "
        f"{str(item.get('path', '')).strip() or '—'}"
        for item in results
    ]
    if summary:
        lines.append(
            "summary | " + ", ".join(f"{key}={value}" for key, value in sorted(summary.items()))
        )
    return "\n".join(lines)


class _ExportWorker(QThread):
    """QThread that runs a bulk-exporter call and emits the result.

    Exporters (``CSVExporter`` / ``HDF5Exporter`` / ``XLSXExporter``) are
    blocking and can take seconds to minutes over GB-scale SQLite. We
    run them on a dedicated QThread so the GUI thread stays responsive.

    Implemented as a QThread subclass with ``parent=self`` ownership so
    Qt tracks the lifecycle (mirroring the ``ZmqCommandWorker`` pattern).
    The earlier QObject+moveToThread+deleteLater chain produced GC races
    that segfaulted inside ``QThread::started`` signal delivery.

    ``result_ready(kind, count, error)`` is the completion signal. The
    inherited ``finished()`` signal (no args) fires after run() returns,
    which callers can use for lifecycle cleanup.
    """

    result_ready = Signal(str, int, str)  # kind, count, error_text

    def __init__(
        self,
        kind: str,
        runner: Callable[[], int],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._kind = kind
        self._runner = runner

    def run(self) -> None:
        try:
            count = int(self._runner())
        except Exception as exc:  # noqa: BLE001 — broad catch acceptable at worker boundary
            logger.exception("Export failed (%s)", self._kind)
            self.result_ready.emit(self._kind, 0, str(exc))
            return
        self.result_ready.emit(self._kind, count, "")


class ArchivePanel(QWidget):
    """Experiment archive overlay (Phase II.2)."""

    entry_selected = Signal(dict)
    regenerate_requested = Signal(str)
    export_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._connected: bool = False
        self._entries: list[dict] = []
        self._workers: list[ZmqCommandWorker] = []
        # Keep Python refs to export QThread workers alive while they run.
        # Qt ownership (parent=self) also guards; the list gives the slot
        # a way to prune finished workers on the next tick.
        self._export_workers: list[_ExportWorker] = []
        self._export_in_flight: bool = False
        # II.2 post-review fix #2: refresh in-flight flag. Prevents a
        # reconnect flap (set_connected False → True rapidly) from
        # enqueueing a duplicate refresh while the first is still
        # resolving — two workers would race and the second could
        # overwrite the first's entries.
        self._refresh_in_flight: bool = False

        self.setObjectName("archivePanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"#archivePanel {{ background-color: {theme.BACKGROUND}; }}")

        from PySide6.QtCore import QTimer

        self._banner_timer = QTimer(self)
        self._banner_timer.setSingleShot(True)
        self._banner_timer.setInterval(_BANNER_AUTO_CLEAR_MS)
        self._banner_timer.timeout.connect(self.clear_message)

        self._build_ui()
        self._update_control_enablement()
        self._clear_details("Эксперимент не выбран.")
        # II.2 post-review: do NOT refresh in __init__(). That fires a
        # ZmqCommandWorker before MainWindowV2 has replayed the real
        # connection state, producing an avoidable timeout on cold-start
        # / disconnected engine. Deferred to the first set_connected(True)
        # transition when no data is loaded yet.

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, theme.SPACE_3)
        root.setSpacing(theme.SPACE_3)

        root.addWidget(self._build_header())
        root.addWidget(self._build_banner())
        root.addWidget(self._build_filter_bar_card())
        root.addWidget(self._build_content_split(), stretch=1)
        root.addWidget(self._build_export_card())

    def _build_header(self) -> QWidget:
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_2)

        title = QLabel("АРХИВ ЭКСПЕРИМЕНТОВ")
        title.setFont(_title_font())
        title.setStyleSheet(
            f"color: {theme.FOREGROUND}; background: transparent; border: none;"
            f" letter-spacing: 1px;"
        )
        layout.addWidget(title)
        layout.addStretch()
        return header

    def _build_banner(self) -> QWidget:
        self._banner_label = QLabel("")
        self._banner_label.setFont(_label_font())
        self._banner_label.setObjectName("archiveBanner")
        self._banner_label.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._banner_label.setContentsMargins(
            theme.SPACE_3, theme.SPACE_1, theme.SPACE_3, theme.SPACE_1
        )
        self._banner_label.setVisible(False)
        return self._banner_label

    def _build_filter_bar_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("filterBarCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setStyleSheet(
            f"#filterBarCard {{"
            f" background-color: {theme.SURFACE_CARD};"
            f" border: 1px solid {theme.BORDER_SUBTLE};"
            f" border-radius: {theme.RADIUS_MD}px;"
            f"}}"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(theme.SPACE_3, theme.SPACE_2, theme.SPACE_3, theme.SPACE_2)
        layout.setSpacing(theme.SPACE_2)

        row1 = QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        row1.setSpacing(theme.SPACE_2)
        row1.addWidget(self._caption("Шаблон:"))
        self._template_combo = QComboBox()
        self._template_combo.addItem("Все", "")
        _style_input(self._template_combo)
        row1.addWidget(self._template_combo, stretch=1)
        row1.addWidget(self._caption("Оператор:"))
        self._operator_edit = QLineEdit()
        _style_input(self._operator_edit)
        row1.addWidget(self._operator_edit, stretch=1)
        row1.addWidget(self._caption("Образец:"))
        self._sample_edit = QLineEdit()
        _style_input(self._sample_edit)
        row1.addWidget(self._sample_edit, stretch=1)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        row2.setSpacing(theme.SPACE_2)
        row2.addWidget(self._caption("С:"))
        self._start_date = QDateEdit()
        self._start_date.setCalendarPopup(True)
        self._start_date.setDisplayFormat("yyyy-MM-dd")
        self._start_date.setDate(QDate.currentDate().addDays(-30))
        _style_input(self._start_date)
        row2.addWidget(self._start_date)
        row2.addWidget(self._caption("По:"))
        self._end_date = QDateEdit()
        self._end_date.setCalendarPopup(True)
        self._end_date.setDisplayFormat("yyyy-MM-dd")
        self._end_date.setDate(QDate.currentDate())
        _style_input(self._end_date)
        row2.addWidget(self._end_date)

        row2.addWidget(self._caption("Отчёт:"))
        self._report_combo = QComboBox()
        for label, value in _REPORT_OPTIONS:
            self._report_combo.addItem(label, value)
        _style_input(self._report_combo)
        row2.addWidget(self._report_combo)

        row2.addWidget(self._caption("Сортировка:"))
        self._sort_combo = QComboBox()
        for label, sort_by, desc in _SORT_OPTIONS:
            self._sort_combo.addItem(label, (sort_by, desc))
        _style_input(self._sort_combo)
        row2.addWidget(self._sort_combo)

        row2.addStretch()
        self._refresh_btn = QPushButton("Обновить")
        _style_button(self._refresh_btn, "accent")
        self._refresh_btn.clicked.connect(self.refresh_archive)
        row2.addWidget(self._refresh_btn)
        layout.addLayout(row2)

        return card

    def _build_content_split(self) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_3)

        layout.addWidget(self._build_list_card(), stretch=2)
        layout.addWidget(self._build_details_card(), stretch=1)
        return container

    def _build_list_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("listCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setStyleSheet(
            f"#listCard {{"
            f" background-color: {theme.SURFACE_CARD};"
            f" border: 1px solid {theme.BORDER_SUBTLE};"
            f" border-radius: {theme.RADIUS_MD}px;"
            f"}}"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(theme.SPACE_2, theme.SPACE_2, theme.SPACE_2, theme.SPACE_2)
        layout.setSpacing(theme.SPACE_1)

        self._table = QTableWidget(0, len(_TABLE_COLUMNS))
        self._table.setHorizontalHeaderLabels(list(_TABLE_COLUMNS))
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(False)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setFont(_body_font())
        self._table.setStyleSheet(
            f"QTableWidget {{"
            f" background-color: {theme.SURFACE_CARD};"
            f" color: {theme.FOREGROUND};"
            f" gridline-color: {theme.BORDER_SUBTLE};"
            f" border: none;"
            f"}} "
            f"QHeaderView::section {{"
            f" background-color: {theme.SURFACE_MUTED};"
            f" color: {theme.MUTED_FOREGROUND};"
            f" border: 0px;"
            f" border-bottom: 1px solid {theme.BORDER_SUBTLE};"
            f" padding: {theme.SPACE_1}px {theme.SPACE_2}px;"
            f"}}"
        )
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._table, stretch=1)

        self._empty_state_label = QLabel("Эксперименты по текущему фильтру не найдены")
        self._empty_state_label.setFont(_body_font())
        self._empty_state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_state_label.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND};"
            f" background: transparent; border: none;"
            f" padding: {theme.SPACE_4}px;"
        )
        self._empty_state_label.setVisible(False)
        layout.addWidget(self._empty_state_label)
        return card

    def _build_details_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("detailsCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setStyleSheet(
            f"#detailsCard {{"
            f" background-color: {theme.SURFACE_CARD};"
            f" border: 1px solid {theme.BORDER_SUBTLE};"
            f" border-radius: {theme.RADIUS_MD}px;"
            f"}}"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        layout.setSpacing(theme.SPACE_2)

        self._summary_label = QLabel("Эксперимент не выбран.")
        self._summary_label.setFont(_title_font())
        self._summary_label.setWordWrap(True)
        self._summary_label.setStyleSheet(
            f"color: {theme.FOREGROUND}; background: transparent; border: none;"
        )
        layout.addWidget(self._summary_label)

        metadata = QFrame()
        metadata.setObjectName("metadataBlock")
        metadata.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        metadata.setStyleSheet("background: transparent;")
        meta_layout = QVBoxLayout(metadata)
        meta_layout.setContentsMargins(0, 0, 0, 0)
        meta_layout.setSpacing(theme.SPACE_1)
        self._template_label = self._make_metadata_row(meta_layout, "Шаблон:")
        self._operator_label = self._make_metadata_row(meta_layout, "Оператор:")
        self._sample_label = self._make_metadata_row(meta_layout, "Образец:")
        self._date_label = self._make_metadata_row(meta_layout, "Диапазон:")
        self._artifact_label = self._make_metadata_row(meta_layout, "Папка:")
        self._report_label = self._make_metadata_row(meta_layout, "Отчёт:")
        layout.addWidget(metadata)

        layout.addWidget(self._caption("Заметки:"))
        self._notes_view = QPlainTextEdit()
        self._notes_view.setReadOnly(True)
        self._notes_view.setMaximumBlockCount(500)
        self._notes_view.setFixedHeight(72)
        _style_input(self._notes_view)
        layout.addWidget(self._notes_view)

        self._archive_stats_label = QLabel("Состав: —")
        self._archive_stats_label.setFont(_label_font())
        self._archive_stats_label.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;"
        )
        layout.addWidget(self._archive_stats_label)

        layout.addWidget(self._caption("Прогоны:"))
        self._runs_view = QPlainTextEdit()
        self._runs_view.setReadOnly(True)
        self._runs_view.setFixedHeight(72)
        _style_input(self._runs_view)
        layout.addWidget(self._runs_view)

        layout.addWidget(self._caption("Артефакты:"))
        self._artifacts_view = QPlainTextEdit()
        self._artifacts_view.setReadOnly(True)
        self._artifacts_view.setFixedHeight(72)
        _style_input(self._artifacts_view)
        layout.addWidget(self._artifacts_view)

        layout.addWidget(self._caption("Результаты:"))
        self._results_view = QPlainTextEdit()
        self._results_view.setReadOnly(True)
        self._results_view.setFixedHeight(56)
        _style_input(self._results_view)
        layout.addWidget(self._results_view)

        actions_row = QHBoxLayout()
        actions_row.setContentsMargins(0, 0, 0, 0)
        actions_row.setSpacing(theme.SPACE_1)
        self._open_folder_btn = QPushButton("Папка")
        _style_button(self._open_folder_btn, "neutral")
        self._open_folder_btn.clicked.connect(self._on_open_folder)
        actions_row.addWidget(self._open_folder_btn)
        self._open_pdf_btn = QPushButton("PDF")
        _style_button(self._open_pdf_btn, "neutral")
        self._open_pdf_btn.clicked.connect(self._on_open_pdf)
        actions_row.addWidget(self._open_pdf_btn)
        self._open_docx_btn = QPushButton("DOCX")
        _style_button(self._open_docx_btn, "neutral")
        self._open_docx_btn.clicked.connect(self._on_open_docx)
        actions_row.addWidget(self._open_docx_btn)
        actions_row.addStretch()
        self._regenerate_btn = QPushButton("Перегенерировать")
        _style_button(self._regenerate_btn, "primary")
        self._regenerate_btn.clicked.connect(self._on_regenerate_clicked)
        actions_row.addWidget(self._regenerate_btn)
        layout.addLayout(actions_row)

        return card

    def _make_metadata_row(self, parent_layout: QVBoxLayout, caption: str) -> QLabel:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE_2)
        cap = QLabel(caption)
        cap.setFont(_label_font())
        cap.setFixedWidth(96)
        cap.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;"
        )
        row.addWidget(cap)
        value = QLabel("—")
        value.setFont(_body_font())
        value.setWordWrap(True)
        value.setStyleSheet(f"color: {theme.FOREGROUND}; background: transparent; border: none;")
        value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        row.addWidget(value, stretch=1)
        parent_layout.addLayout(row)
        return value

    def _build_export_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("exportCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setStyleSheet(
            f"#exportCard {{"
            f" background-color: {theme.SURFACE_CARD};"
            f" border: 1px solid {theme.BORDER_SUBTLE};"
            f" border-radius: {theme.RADIUS_MD}px;"
            f"}}"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(theme.SPACE_3, theme.SPACE_2, theme.SPACE_3, theme.SPACE_2)
        layout.setSpacing(theme.SPACE_1)

        caption = QLabel("Экспортировать все данные из SQLite (полный временной ряд):")
        caption.setFont(_label_font())
        caption.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;"
        )
        layout.addWidget(caption)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE_2)
        self._export_csv_btn = QPushButton("CSV...")
        _style_button(self._export_csv_btn, "neutral")
        self._export_csv_btn.clicked.connect(self._on_export_csv_clicked)
        row.addWidget(self._export_csv_btn)
        self._export_hdf5_btn = QPushButton("HDF5...")
        _style_button(self._export_hdf5_btn, "neutral")
        self._export_hdf5_btn.clicked.connect(self._on_export_hdf5_clicked)
        row.addWidget(self._export_hdf5_btn)
        self._export_xlsx_btn = QPushButton("Excel...")
        _style_button(self._export_xlsx_btn, "neutral")
        self._export_xlsx_btn.clicked.connect(self._on_export_xlsx_clicked)
        row.addWidget(self._export_xlsx_btn)
        # IV.4 F1: fourth format — Parquet (Snappy-compressed columnar).
        # Backend already exports Parquet best-effort on experiment
        # finalize; this is the first UI surface for arbitrary-range
        # bulk export.
        self._export_parquet_btn = QPushButton("Parquet...")
        _style_button(self._export_parquet_btn, "neutral")
        self._export_parquet_btn.setToolTip(
            "Экспорт всех SQLite данных в Parquet (Snappy compression)"
        )
        self._export_parquet_btn.clicked.connect(self._on_export_parquet_clicked)
        row.addWidget(self._export_parquet_btn)
        row.addStretch()
        layout.addLayout(row)
        return card

    @staticmethod
    def _caption(text: str) -> QLabel:
        label = QLabel(text)
        label.setFont(_label_font())
        label.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;"
        )
        return label

    # ------------------------------------------------------------------
    # Refresh / payload
    # ------------------------------------------------------------------

    def refresh_archive(self) -> None:
        if self._refresh_in_flight:
            return
        self._refresh_in_flight = True
        payload = self._build_list_payload()
        worker = ZmqCommandWorker(payload, parent=self)
        worker.finished.connect(self._on_refresh_result)
        self._workers.append(worker)
        worker.start()

    def _build_list_payload(self) -> dict:
        template_id = str(self._template_combo.currentData() or "").strip()
        sort_by, descending = self._sort_combo.currentData() or ("start_time", True)
        report_value = str(self._report_combo.currentData() or "")
        payload: dict = {
            "cmd": "experiment_archive_list",
            "template_id": template_id,
            "operator": self._operator_edit.text().strip(),
            "sample": self._sample_edit.text().strip(),
            "start_date": self._start_date.date().toString("yyyy-MM-dd"),
            "end_date": self._end_date.date().toString("yyyy-MM-dd"),
            "sort_by": sort_by,
            "descending": bool(descending),
        }
        if report_value:
            payload["report_present"] = report_value
        return payload

    def _on_refresh_result(self, result: dict) -> None:
        # Clear the in-flight flag BEFORE any branch so failure paths
        # don't leave the overlay locked out of future refreshes.
        self._refresh_in_flight = False
        self._workers = [w for w in self._workers if w.isRunning()]
        if not result.get("ok", False):
            error = result.get("error", "Не удалось загрузить архив.")
            self.show_error(str(error))
            return
        entries = list(result.get("entries", []))
        self._entries = entries
        self._populate_table()

    def _populate_table(self) -> None:
        self._table.setRowCount(0)
        if not self._entries:
            self._empty_state_label.setVisible(True)
            self._table.setVisible(False)
            self._clear_details("Эксперимент не выбран.")
            return
        self._empty_state_label.setVisible(False)
        self._table.setVisible(True)
        self._table.setRowCount(len(self._entries))
        for row, entry in enumerate(self._entries):
            self._set_cell(row, 0, _format_datetime(entry.get("start_time")), mono=True)
            self._set_cell(row, 1, _format_datetime(entry.get("end_time")), mono=True)
            self._set_cell(row, 2, str(entry.get("title") or entry.get("experiment_id", "")))
            self._set_cell(row, 3, str(entry.get("template_name") or entry.get("template_id", "")))
            self._set_cell(row, 4, str(entry.get("operator", "")))
            self._set_cell(row, 5, str(entry.get("sample", "")))
            self._set_cell(row, 6, str(entry.get("status", "")))
            has_report = bool(entry.get("pdf_path") or entry.get("docx_path"))
            report_text = "Да" if has_report else "—"
            self._set_cell(row, 7, report_text)
            artifacts = entry.get("artifact_index", []) or []
            has_data = any(
                isinstance(item, dict) and item.get("role") == "experiment_data"
                for item in artifacts
            )
            data_text = "Да" if has_data else "—"
            self._set_cell(row, 8, data_text)
        if self._table.rowCount() > 0:
            self._table.selectRow(0)

    def _set_cell(self, row: int, col: int, text: str, *, mono: bool = False) -> None:
        item = QTableWidgetItem(text)
        if mono:
            item.setFont(_mono_cell_font())
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, col, item)

    # ------------------------------------------------------------------
    # Selection + details
    # ------------------------------------------------------------------

    def _on_selection_changed(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            self._clear_details("Эксперимент не выбран.")
            return
        self.entry_selected.emit(entry)
        self._update_details(entry)

    def _selected_entry(self) -> dict | None:
        rows = self._table.selectionModel().selectedRows() if self._table.selectionModel() else []
        if not rows:
            return None
        idx = rows[0].row()
        if idx < 0 or idx >= len(self._entries):
            return None
        return self._entries[idx]

    def _update_details(self, entry: dict) -> None:
        folder_path = resolve_folder_path(entry)
        pdf_path = resolve_pdf_path(entry)
        docx_path = resolve_docx_path(entry)
        report_enabled = bool(entry.get("report_enabled", True))

        title = str(entry.get("title") or entry.get("experiment_id", "")).strip()
        self._summary_label.setText(
            f"{title}\nID: {entry.get('experiment_id', '')}\nСтатус: {entry.get('status', '—')}"
        )
        self._template_label.setText(
            str(entry.get("template_name", entry.get("template_id", ""))) or "—"
        )
        self._operator_label.setText(str(entry.get("operator", "")) or "—")
        self._sample_label.setText(str(entry.get("sample", "")) or "—")
        self._date_label.setText(
            f"{_format_datetime(entry.get('start_time'))} → "
            f"{_format_datetime(entry.get('end_time'))}"
        )
        self._artifact_label.setText(
            str(folder_path) if folder_path else "Папка артефактов не найдена"
        )
        if pdf_path or docx_path:
            self._report_label.setText(f"PDF: {pdf_path or 'нет'}\nDOCX: {docx_path or 'нет'}")
        elif report_enabled:
            self._report_label.setText("Файлы отчёта отсутствуют")
        else:
            self._report_label.setText("Отчёт не предусмотрен шаблоном")

        raw_notes = entry.get("notes")
        notes = "" if raw_notes is None else str(raw_notes).strip()
        self._notes_view.setPlainText(notes or "Заметки отсутствуют.")
        self._archive_stats_label.setText(
            f"Состав: runs={int(entry.get('run_record_count', 0) or 0)}, "
            f"artifacts={int(entry.get('artifact_count', 0) or 0)}, "
            f"результаты={int(entry.get('result_table_count', 0) or 0)}"
        )
        self._runs_view.setPlainText(_format_run_records(entry))
        self._artifacts_view.setPlainText(_format_artifacts(entry))
        self._results_view.setPlainText(_format_results(entry))
        self._open_folder_btn.setEnabled(folder_path is not None)
        self._open_pdf_btn.setEnabled(pdf_path is not None)
        self._open_docx_btn.setEnabled(docx_path is not None)
        self._regenerate_btn.setEnabled(self._connected and report_enabled)

    def _clear_details(self, summary: str = "Эксперимент не выбран.") -> None:
        self._summary_label.setText(summary)
        self._template_label.setText("—")
        self._operator_label.setText("—")
        self._sample_label.setText("—")
        self._date_label.setText("—")
        self._artifact_label.setText("—")
        self._report_label.setText("—")
        self._notes_view.setPlainText("Выберите эксперимент, чтобы увидеть сведения и артефакты.")
        self._archive_stats_label.setText("Состав: —")
        self._runs_view.setPlainText("Записей прогонов нет.")
        self._artifacts_view.setPlainText("Артефактов ещё нет.")
        self._results_view.setPlainText("Таблиц результатов нет.")
        self._open_folder_btn.setEnabled(False)
        self._open_pdf_btn.setEnabled(False)
        self._open_docx_btn.setEnabled(False)
        self._regenerate_btn.setEnabled(False)

    # ------------------------------------------------------------------
    # Actions: open folder / PDF / DOCX / regenerate
    # ------------------------------------------------------------------

    @staticmethod
    def _open_path(path: Path) -> bool:
        return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _on_open_folder(self) -> None:
        entry = self._selected_entry()
        if not entry:
            return
        path = resolve_folder_path(entry)
        if path is None or not self._open_path(path):
            self.show_warning("Папка артефактов отсутствует или не открывается.")

    def _on_open_pdf(self) -> None:
        entry = self._selected_entry()
        if not entry:
            return
        path = resolve_pdf_path(entry)
        if path is None or not self._open_path(path):
            self.show_warning("PDF отсутствует или не открывается.")

    def _on_open_docx(self) -> None:
        entry = self._selected_entry()
        if not entry:
            return
        path = resolve_docx_path(entry)
        if path is None or not self._open_path(path):
            self.show_warning("DOCX отсутствует или не открывается.")

    def _on_regenerate_clicked(self) -> None:
        entry = self._selected_entry()
        if not entry:
            return
        if not bool(entry.get("report_enabled", True)):
            self.show_warning("Для этого шаблона формирование отчёта отключено.")
            return
        experiment_id = str(entry.get("experiment_id", "")).strip()
        if not experiment_id:
            self.show_error("Не удалось определить ID эксперимента.")
            return
        self.regenerate_requested.emit(experiment_id)
        self._regenerate_btn.setEnabled(False)
        self.show_info("Генерация отчёта...")
        worker = ZmqCommandWorker(
            {"cmd": "experiment_generate_report", "experiment_id": experiment_id},
            parent=self,
        )
        worker.finished.connect(self._on_regenerate_result)
        self._workers.append(worker)
        worker.start()

    def _on_regenerate_result(self, result: dict) -> None:
        self._workers = [w for w in self._workers if w.isRunning()]
        entry = self._selected_entry()
        report_enabled = bool(entry.get("report_enabled", True)) if entry else True
        self._regenerate_btn.setEnabled(self._connected and report_enabled)
        if not result.get("ok"):
            self.show_error(str(result.get("error", "Не удалось сформировать отчёт.")))
            return
        report = result.get("report") or {}
        if report.get("skipped"):
            self.show_warning(str(report.get("reason", "Формирование отчёта пропущено.")))
        else:
            pdf = report.get("pdf_path") or "нет"
            docx = report.get("docx_path") or "нет"
            self.show_info(f"Отчёты обновлены: PDF={pdf}, DOCX={docx}")
        self.refresh_archive()

    # ------------------------------------------------------------------
    # Actions: bulk export (K6 migration)
    # ------------------------------------------------------------------

    def _on_export_csv_clicked(self) -> None:
        self.export_requested.emit("csv")
        path_str, _ = QFileDialog.getSaveFileName(self, "Экспорт в CSV", "", "CSV файлы (*.csv)")
        if not path_str:
            return
        output = Path(path_str)

        from cryodaq.paths import get_data_dir
        from cryodaq.storage.csv_export import CSVExporter

        data_dir = get_data_dir()

        def runner() -> int:
            return CSVExporter(data_dir=data_dir).export(output)

        self._start_export_worker("csv", runner, unit="записей")

    def _on_export_hdf5_clicked(self) -> None:
        self.export_requested.emit("hdf5")
        directory = QFileDialog.getExistingDirectory(self, "Выберите папку для HDF5")
        if not directory:
            return
        out_root = Path(directory)

        from cryodaq.paths import get_data_dir
        from cryodaq.storage.hdf5_export import HDF5Exporter

        data_dir = get_data_dir()

        def runner() -> int:
            exporter = HDF5Exporter()
            total = 0
            for db_file in sorted(data_dir.glob("data_*.db")):
                out = out_root / db_file.name.replace(".db", ".h5")
                total += exporter.export(db_file, out)
            return total

        self._start_export_worker("hdf5", runner, unit="записей")

    def _on_export_xlsx_clicked(self) -> None:
        self.export_requested.emit("xlsx")
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Экспорт в Excel", "", "Excel файлы (*.xlsx)"
        )
        if not path_str:
            return
        output = Path(path_str)

        from cryodaq.paths import get_data_dir
        from cryodaq.storage.xlsx_export import XLSXExporter

        data_dir = get_data_dir()

        def runner() -> int:
            return XLSXExporter(data_dir).export(output)

        self._start_export_worker("xlsx", runner, unit="записей")

    def _on_export_parquet_clicked(self) -> None:
        """Bulk Parquet export — IV.4 F1.

        Mirrors CSV / HDF5 / Excel handlers: emits export_requested,
        opens QFileDialog, and runs the exporter in an in-process
        _ExportWorker thread. The underlying helper (Phase 2e stage 1)
        streams daily SQLite files chunk by chunk via
        ``pyarrow.ParquetWriter`` so large archives don't load into
        memory all at once.
        """
        self.export_requested.emit("parquet")
        from datetime import UTC, datetime

        default_name = f"cryodaq_export_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.parquet"
        path_str, _ = QFileDialog.getSaveFileName(
            self,
            "Экспорт в Parquet",
            default_name,
            "Parquet файлы (*.parquet)",
        )
        if not path_str:
            return
        output = Path(path_str)

        from cryodaq.paths import get_data_dir
        from cryodaq.storage.parquet_archive import (
            export_experiment_readings_to_parquet,
        )

        data_dir = get_data_dir()

        def runner() -> int:
            # Bulk export — no per-experiment scoping. [2000-01-01, now]
            # covers the full historical range; the exporter skips
            # missing daily DBs cleanly.
            result = export_experiment_readings_to_parquet(
                experiment_id="bulk_export",
                start_time=datetime(2000, 1, 1, tzinfo=UTC),
                end_time=datetime.now(UTC),
                sqlite_root=data_dir,
                output_path=output,
            )
            return result.rows_written

        self._start_export_worker("parquet", runner, unit="строк")

    def _start_export_worker(self, kind: str, runner: Callable[[], int], *, unit: str) -> None:
        self._export_in_flight = True
        self._update_control_enablement()
        self.show_info(f"Экспорт {kind.upper()} выполняется в фоне...")

        worker = _ExportWorker(kind, runner, parent=self)

        def on_result(k: str, count: int, error: str, u: str = unit) -> None:
            self._export_in_flight = False
            self._update_control_enablement()
            if error:
                self.show_error(f"Экспорт {k.upper()}: {error}")
            else:
                self.show_info(f"Экспорт {k.upper()} завершён: {count} {u}.")

        worker.result_ready.connect(on_result)
        worker.finished.connect(lambda w=worker: self._prune_export_worker(w))
        self._export_workers.append(worker)
        worker.start()

    def _prune_export_worker(self, worker: _ExportWorker) -> None:
        if worker in self._export_workers:
            self._export_workers.remove(worker)

    # ------------------------------------------------------------------
    # Public state pushers
    # ------------------------------------------------------------------

    def on_reading(self, reading: Reading) -> None:
        """Contract no-op. Engine has no broker event on experiment finalize
        (2026-04-19). Kept for Host Integration Contract symmetry; manual
        refresh via the Обновить button is the only path today.
        """
        _ = reading  # explicit silence

    def set_connected(self, connected: bool) -> None:
        if connected == self._connected:
            return
        was_connected = self._connected
        self._connected = connected
        self._update_control_enablement()
        # II.2 post-review: auto-refresh on the first transition to
        # connected when no entries have been loaded yet. The overlay
        # no longer fires a refresh from __init__(), so this is the
        # entry point that populates the timeline once the shell has
        # confirmed the engine is reachable.
        if connected and not was_connected and not self._entries and not self._refresh_in_flight:
            self.refresh_archive()

    def _update_control_enablement(self) -> None:
        # Refresh + regenerate + bulk export gated on connection.
        # Export buttons also gated on no-in-flight-export.
        self._refresh_btn.setEnabled(self._connected)
        entry = self._selected_entry()
        report_enabled = bool(entry.get("report_enabled", True)) if entry else False
        self._regenerate_btn.setEnabled(self._connected and report_enabled)
        export_ok = self._connected and not self._export_in_flight
        self._export_csv_btn.setEnabled(export_ok)
        self._export_hdf5_btn.setEnabled(export_ok)
        self._export_xlsx_btn.setEnabled(export_ok)
        self._export_parquet_btn.setEnabled(export_ok)

    # ------------------------------------------------------------------
    # Banner
    # ------------------------------------------------------------------

    def show_info(self, text: str) -> None:
        self._set_banner(text, theme.STATUS_INFO)

    def show_warning(self, text: str) -> None:
        self._set_banner(text, theme.STATUS_WARNING)

    def show_error(self, text: str) -> None:
        self._set_banner(text, theme.STATUS_FAULT)

    def clear_message(self) -> None:
        self._banner_label.setText("")
        self._banner_label.setVisible(False)
        self._banner_timer.stop()

    def _set_banner(self, text: str, color: str) -> None:
        self._banner_label.setText(text)
        self._banner_label.setStyleSheet(
            f"#archiveBanner {{"
            f" color: {theme.FOREGROUND};"
            f" background-color: {theme.SURFACE_CARD};"
            f" border: 1px solid {color};"
            f" border-radius: {theme.RADIUS_SM}px;"
            f"}}"
        )
        self._banner_label.setVisible(True)
        self._banner_timer.start()
