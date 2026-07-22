"""OperatorLogPanel — Phase II.3 operator journal overlay.

Supersedes the v1 widget at ``src/cryodaq/gui/widgets/operator_log_panel.py``.
Aligned with Design System v1.0.1 tokens and shift-handover workflow.

Layout (top to bottom):
    Header (ЖУРНАЛ ОПЕРАТОРА + close)
    Status banner (transient info/warning/error, auto-clear 4 s)
    Composer card (author + tags + message + bind-experiment + save)
    Filter bar card (quick chips + text/author/tag search)
    Timeline card (entries grouped by calendar day)
    Footer (loaded count + «Загрузить ещё 50»)

Public API (host push points):
- ``on_reading(reading)`` — triggers refresh on ``analytics/operator_log_entry``.
- ``set_connected(bool)`` — gates composer; timeline stays readable when offline.
- ``set_current_experiment(id)`` — binds the «Текущий экспт.» chip to the active experiment.

Out of scope (follow-ups):
- CSV export of filtered timeline.
- Per-entry edit/delete (journal is append-only).
- Server-side pagination cursors (load-more increments client-side ``limit``).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from PySide6.QtCore import QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from cryodaq.core.operator_log import normalize_operator_log_tags
from cryodaq.drivers.base import Reading
from cryodaq.gui import theme
from cryodaq.gui.zmq_client import ZmqCommandWorker

logger = logging.getLogger(__name__)

_LIMIT_STEP = 50
_DEFAULT_LIMIT = 50
_SEARCH_DEBOUNCE_MS = 250
_BANNER_AUTO_CLEAR_MS = 4000
_LOG_ENTRY_CHANNEL = "analytics/operator_log_entry"
_LOG_COMMIT_SCHEMA = "operator_log_commit_v1"
_LOG_READ_SCOPE_SCHEMA = "operator_log_read_scope_v1"

_KNOWN_UNCOMMITTED_LOG_ERRORS = frozenset(
    {
        "mutation_protocol_incompatible",
        "operator_log_request_id_invalid",
        "operator_log_scope_invalid",
        "stale_experiment_command",
        "operator_log_message_invalid",
        "operator_log_persistence_failed",
        "idempotency_key_conflict",
        "operator_log_busy",
    }
)

_FILTER_CHIP_ALL = "all"
_FILTER_CHIP_CURRENT = "current"
_FILTER_CHIP_LAST_8H = "last_8h"
_FILTER_CHIP_LAST_24H = "last_24h"
_FILTER_CHIPS: tuple[tuple[str, str], ...] = (
    (_FILTER_CHIP_ALL, "Все"),
    (_FILTER_CHIP_CURRENT, "Текущий экспт."),
    (_FILTER_CHIP_LAST_8H, "Последние 8ч"),
    (_FILTER_CHIP_LAST_24H, "За сутки"),
)
_DEFAULT_FILTER = _FILTER_CHIP_LAST_8H

_DAY_HEADER_FORMAT = "%Y-%m-%d"
_TIME_FORMAT = "%H:%M"


def _label_font() -> QFont:
    font = QFont(theme.FONT_BODY)
    font.setPixelSize(theme.FONT_LABEL_SIZE)
    font.setWeight(QFont.Weight(theme.FONT_LABEL_WEIGHT))
    return font


def _body_font() -> QFont:
    font = QFont(theme.FONT_BODY)
    font.setPixelSize(theme.FONT_BODY_SIZE)
    return font


def _mono_time_font() -> QFont:
    font = QFont(theme.FONT_MONO)
    font.setPixelSize(theme.FONT_LABEL_SIZE)
    font.setWeight(QFont.Weight(theme.FONT_LABEL_WEIGHT))
    try:
        font.setFeature(QFont.Tag("tnum"), 1)
    except (AttributeError, TypeError):
        pass
    return font


def _title_font() -> QFont:
    font = QFont(theme.FONT_BODY)
    font.setPixelSize(theme.FONT_SIZE_LG)
    font.setWeight(QFont.Weight(theme.FONT_WEIGHT_SEMIBOLD))
    return font


def _style_button(btn: QPushButton, variant: str) -> None:
    radius = theme.RADIUS_MD
    if variant == "primary":
        # Phase III.A: primary uses ACCENT (UI activation), not STATUS_OK
        # (safety-green, reserved for status display only).
        bg, fg = theme.ACCENT, theme.ON_ACCENT
    elif variant == "warning":
        bg, fg = theme.STATUS_WARNING, theme.ON_PRIMARY
    elif variant == "accent":
        bg, fg = theme.ACCENT, theme.ON_ACCENT
    elif variant == "ghost":
        bg, fg = theme.SURFACE_CARD, theme.FOREGROUND
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


def _style_input(widget: QLineEdit | QPlainTextEdit) -> None:
    widget.setStyleSheet(
        f"QLineEdit, QPlainTextEdit {{"
        f" background-color: {theme.SURFACE_SUNKEN};"
        f" color: {theme.FOREGROUND};"
        f" border: 1px solid {theme.BORDER_SUBTLE};"
        f" border-radius: {theme.RADIUS_SM}px;"
        f" padding: {theme.SPACE_1}px {theme.SPACE_2}px;"
        f"}}"
        f" QLineEdit:disabled, QPlainTextEdit:disabled {{"
        f" color: {theme.MUTED_FOREGROUND};"
        f"}}"
    )


def _parse_entry_timestamp(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone()


def _sort_entries(entries: Iterable[dict]) -> list[dict]:
    """Defensive: sort by timestamp descending regardless of server order."""

    def key(entry: dict) -> datetime:
        parsed = _parse_entry_timestamp(str(entry.get("timestamp", "")))
        return parsed or datetime.min.replace(tzinfo=UTC)

    return sorted(entries, key=key, reverse=True)


def _result_is_unknown(result: object) -> bool:
    """Return whether a command reply cannot prove commit or non-commit.

    Transport timeouts and malformed replies may arrive after the engine has
    already committed the append.  They must never be presented as an ordinary
    retryable failure.
    """

    if not isinstance(result, dict):
        return True
    if result.get("_handler_timeout") or result.get("_unknown"):
        return True
    if result.get("committed") is True:
        return False
    error_code = result.get("error_code")
    return not (result.get("ok") is False and error_code in _KNOWN_UNCOMMITTED_LOG_ERRORS)


class OperatorLogPanel(QWidget):
    """Full operator journal overlay (Phase II.3)."""

    entry_submitted = Signal(str, str, list, bool)
    filter_changed = Signal(str)
    entries_loaded = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._connected: bool = False
        self._read_only: bool = False
        self._current_experiment_id: str | None = None
        self._entries_all: list[dict] = []
        self._filtered_entries: list[dict] = []
        self._active_filter: str = _DEFAULT_FILTER
        self._limit: int = _DEFAULT_LIMIT
        self._state_generation: int = 0
        self._inflight_refresh: ZmqCommandWorker | None = None
        self._refresh_context: dict[str, Any] | None = None
        self._refresh_pending: bool = False
        self._refresh_sequence: int = 0
        self._submit_worker: ZmqCommandWorker | None = None
        self._submit_context: dict[str, Any] | None = None
        self._unresolved_submit: dict[str, Any] | None = None
        self._workers: list[ZmqCommandWorker] = []
        self._filter_buttons: dict[str, QPushButton] = {}

        self.setObjectName("operatorLogPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"#operatorLogPanel {{ background-color: {theme.BACKGROUND}; }}")

        self._settings = QSettings("FIAN", "CryoDAQ")

        self._banner_timer = QTimer(self)
        self._banner_timer.setSingleShot(True)
        self._banner_timer.setInterval(_BANNER_AUTO_CLEAR_MS)
        self._banner_timer.timeout.connect(self.clear_message)

        self._search_debounce = QTimer(self)
        self._search_debounce.setSingleShot(True)
        self._search_debounce.setInterval(_SEARCH_DEBOUNCE_MS)
        self._search_debounce.timeout.connect(self._apply_filters)

        self._build_ui()
        # Initial state: composer disabled until shell pushes connected=True.
        self._update_composer_enablement()
        self.refresh_entries()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, theme.SPACE_3)
        root.setSpacing(theme.SPACE_3)

        root.addWidget(self._build_header())
        root.addWidget(self._build_banner())
        root.addWidget(self._build_composer_card())
        root.addWidget(self._build_filter_bar_card())
        root.addWidget(self._build_timeline_card(), stretch=1)
        root.addWidget(self._build_footer())

    def _build_header(self) -> QWidget:
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_2)

        title = QLabel("ЖУРНАЛ ОПЕРАТОРА")
        title_font = _title_font()
        title_font.setPixelSize(theme.FONT_SIZE_XL)
        title.setFont(title_font)
        title.setStyleSheet(f"color: {theme.FOREGROUND}; background: transparent; border: none; letter-spacing: 1px;")
        layout.addWidget(title)
        layout.addStretch()
        return header

    def _build_banner(self) -> QWidget:
        self._banner_label = QLabel("")
        self._banner_label.setFont(_label_font())
        self._banner_label.setObjectName("operatorLogBanner")
        self._banner_label.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._banner_label.setContentsMargins(theme.SPACE_3, theme.SPACE_1, theme.SPACE_3, theme.SPACE_1)
        self._banner_label.setVisible(False)
        return self._banner_label

    def _build_composer_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("composerCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setStyleSheet(
            f"#composerCard {{"
            f" background-color: {theme.SURFACE_CARD};"
            f" border: 1px solid {theme.BORDER_SUBTLE};"
            f" border-radius: {theme.RADIUS_MD}px;"
            f"}}"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        layout.setSpacing(theme.SPACE_2)

        caption = QLabel("Новая запись")
        caption.setFont(_label_font())
        caption.setStyleSheet(f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;")
        layout.addWidget(caption)

        fields_row = QHBoxLayout()
        fields_row.setContentsMargins(0, 0, 0, 0)
        fields_row.setSpacing(theme.SPACE_2)
        fields_row.addWidget(self._caption("Автор:"))
        self._author_edit = QLineEdit()
        self._author_edit.setPlaceholderText("Имя оператора")
        # v0.55.2 ds-012: 13 * SPACE_4 + SPACE_3 = 208 + 12 = 220 keeps the
        # cap on the spacing scale.
        self._author_edit.setMaximumWidth(13 * theme.SPACE_4 + theme.SPACE_3)
        saved_author = self._settings.value("last_log_author", "")
        if saved_author:
            self._author_edit.setText(str(saved_author))
        _style_input(self._author_edit)
        fields_row.addWidget(self._author_edit)
        fields_row.addWidget(self._caption("Теги:"))
        self._tags_edit = QLineEdit()
        self._tags_edit.setPlaceholderText("через запятую")
        _style_input(self._tags_edit)
        fields_row.addWidget(self._tags_edit, stretch=1)
        layout.addLayout(fields_row)

        self._message_edit = QPlainTextEdit()
        self._message_edit.setPlaceholderText("Введите запись")
        # IV.3 F3: composer claimed ~1/3 of the overlay by default,
        # squeezing the timeline below. Halve the minimum height; the
        # stretch=1 and Expanding size policy below still let the
        # operator drag the splitter for more composition room when
        # they need it.
        # v0.55.2 ds-011: SPACE_4 + SPACE_5 = 16 + 24 = 40.
        self._message_edit.setMinimumHeight(theme.SPACE_4 + theme.SPACE_5)
        self._message_edit.setMaximumBlockCount(2000)
        _style_input(self._message_edit)
        layout.addWidget(self._message_edit, stretch=1)

        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(0, 0, 0, 0)
        bottom_row.setSpacing(theme.SPACE_2)
        self._bind_experiment_check = QCheckBox("Привязать к текущему эксперименту")
        self._bind_experiment_check.setStyleSheet(f"color: {theme.FOREGROUND}; background: transparent;")
        bottom_row.addWidget(self._bind_experiment_check)
        bottom_row.addStretch()

        self._submit_btn = QPushButton("Сохранить")
        _style_button(self._submit_btn, "primary")
        self._submit_btn.clicked.connect(self._on_submit_clicked)
        bottom_row.addWidget(self._submit_btn)
        layout.addLayout(bottom_row)

        return card

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

        chip_row = QHBoxLayout()
        chip_row.setContentsMargins(0, 0, 0, 0)
        chip_row.setSpacing(theme.SPACE_1)
        for key, label in _FILTER_CHIPS:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _checked, k=key: self._on_chip_selected(k))
            self._filter_buttons[key] = btn
            chip_row.addWidget(btn)
        chip_row.addStretch()
        layout.addLayout(chip_row)
        self._highlight_active_chip(self._active_filter)

        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.setSpacing(theme.SPACE_2)
        search_row.addWidget(self._caption("Поиск:"))
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("подстрока в сообщении")
        self._search_edit.textChanged.connect(self._on_search_changed)
        _style_input(self._search_edit)
        search_row.addWidget(self._search_edit, stretch=2)

        search_row.addWidget(self._caption("Автор:"))
        self._author_filter_edit = QLineEdit()
        self._author_filter_edit.setPlaceholderText("точное совпадение")
        self._author_filter_edit.textChanged.connect(self._on_search_changed)
        _style_input(self._author_filter_edit)
        search_row.addWidget(self._author_filter_edit, stretch=1)

        search_row.addWidget(self._caption("Тег:"))
        self._tag_filter_edit = QLineEdit()
        self._tag_filter_edit.setPlaceholderText("один тег")
        self._tag_filter_edit.textChanged.connect(self._on_search_changed)
        _style_input(self._tag_filter_edit)
        search_row.addWidget(self._tag_filter_edit, stretch=1)
        layout.addLayout(search_row)

        return card

    def _build_timeline_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("timelineCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setStyleSheet(
            f"#timelineCard {{"
            f" background-color: {theme.SURFACE_CARD};"
            f" border: 1px solid {theme.BORDER_SUBTLE};"
            f" border-radius: {theme.RADIUS_MD}px;"
            f"}}"
        )
        outer = QVBoxLayout(card)
        outer.setContentsMargins(theme.SPACE_2, theme.SPACE_2, theme.SPACE_2, theme.SPACE_2)
        outer.setSpacing(0)

        self._timeline_scroll = QScrollArea()
        self._timeline_scroll.setWidgetResizable(True)
        self._timeline_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._timeline_scroll.setStyleSheet(
            "QScrollArea { background-color: transparent; border: none; }"
            " QScrollArea QWidget { background-color: transparent; }"
        )

        self._timeline_container = QWidget()
        self._timeline_container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._timeline_container.setStyleSheet("background-color: transparent;")
        self._timeline_layout = QVBoxLayout(self._timeline_container)
        self._timeline_layout.setContentsMargins(theme.SPACE_2, theme.SPACE_2, theme.SPACE_2, theme.SPACE_2)
        self._timeline_layout.setSpacing(theme.SPACE_1)
        self._timeline_layout.addStretch()

        self._timeline_scroll.setWidget(self._timeline_container)
        outer.addWidget(self._timeline_scroll)

        self._empty_state_label = QLabel("Записей нет")
        self._empty_state_label.setFont(_body_font())
        self._empty_state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_state_label.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none; padding: {theme.SPACE_4}px;"
        )
        outer.addWidget(self._empty_state_label)
        self._empty_state_label.setVisible(False)

        return card

    def _build_footer(self) -> QWidget:
        footer = QWidget()
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_2)

        self._loaded_label = QLabel("")
        self._loaded_label.setFont(_label_font())
        self._loaded_label.setStyleSheet(f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;")
        layout.addWidget(self._loaded_label)
        layout.addStretch()

        self._load_more_btn = QPushButton(f"Загрузить ещё {_LIMIT_STEP}")
        _style_button(self._load_more_btn, "neutral")
        self._load_more_btn.clicked.connect(self._on_load_more_clicked)
        layout.addWidget(self._load_more_btn)
        return footer

    # ------------------------------------------------------------------
    # Small primitives
    # ------------------------------------------------------------------

    @staticmethod
    def _caption(text: str) -> QLabel:
        label = QLabel(text)
        label.setFont(_label_font())
        label.setStyleSheet(f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;")
        return label

    # ------------------------------------------------------------------
    # Composer
    # ------------------------------------------------------------------

    def _on_submit_clicked(self) -> None:
        # The enabled state is presentation only.  Repeat the authority checks
        # in the direct slot so keyboard/programmatic invocation cannot bypass
        # a disconnect or replay transition.
        if self._read_only or not self._connected or self._submit_worker is not None:
            return
        if self._unresolved_submit is not None:
            # The engine idempotency key makes this an evidence lookup as well
            # as a safe retry: identical content returns the cached receipt and
            # different content is rejected.
            self._start_submit(self._unresolved_submit)
            return
        message = self._message_edit.toPlainText().strip()
        if not message:
            self.show_warning("Введите текст записи.")
            return
        author = self._author_edit.text().strip()
        tags = list(normalize_operator_log_tags(self._tags_edit.text()))
        bind_experiment = self._bind_experiment_check.isChecked()
        experiment_id = self._current_experiment_id if bind_experiment else None
        if bind_experiment and experiment_id is None:
            self.show_error("Нет точного идентификатора текущего эксперимента; запись не отправлена.")
            return
        self.entry_submitted.emit(message, author, tags, bind_experiment)

        payload: dict = {
            "cmd": "log_entry",
            "request_id": uuid.uuid4().hex,
            "message": message,
            "author": author,
            "source": "gui",
            "tags": tags,
        }
        if experiment_id is None:
            payload["experiment_unbound"] = True
        else:
            payload["experiment_id"] = experiment_id
        context: dict[str, Any] = {
            "payload": payload,
            "request_id": payload["request_id"],
            "experiment_id": experiment_id,
            "message": message,
            "author": author,
            "tags_text": self._tags_edit.text(),
        }
        self._start_submit(context)

    def _start_submit(self, context: dict[str, Any]) -> None:
        if self._read_only or not self._connected or self._submit_worker is not None:
            return
        context["attempt_generation"] = self._state_generation
        self._submit_context = context
        self._submit_btn.setEnabled(False)
        worker = ZmqCommandWorker(dict(context["payload"]), parent=self)
        worker.finished.connect(
            lambda result, expected=context, completed_worker=worker: self._on_submit_result(
                result, expected, completed_worker
            )
        )
        self._submit_worker = worker
        self._workers.append(worker)
        self._update_composer_enablement()
        worker.start()

    @staticmethod
    def _commit_receipt_matches(result: object, context: dict[str, Any]) -> bool:
        if not isinstance(result, dict) or result.get("committed") is not True:
            return False
        receipt = result.get("commit_receipt")
        entry = result.get("entry")
        if not isinstance(receipt, dict) or not isinstance(entry, dict):
            return False
        return (
            receipt.get("schema") == _LOG_COMMIT_SCHEMA
            and receipt.get("request_id") == context.get("request_id")
            and receipt.get("experiment_id") == context.get("experiment_id")
            and receipt.get("committed") is True
            and receipt.get("entry_id") is not None
            and receipt.get("entry_id") == entry.get("id")
        )

    def _on_submit_result(
        self,
        result: dict,
        context: dict[str, Any] | None = None,
        worker: ZmqCommandWorker | None = None,
    ) -> None:
        expected = context or self._submit_context or self._unresolved_submit
        if expected is None:
            self.show_error("Получен ответ журнала без идентификатора операции.", persistent=True)
            return
        if worker is not None and worker is not self._submit_worker:
            return
        if worker is not None:
            self._submit_worker = None
        if self._submit_context is expected:
            self._submit_context = None
        self._prune_workers()

        if self._commit_receipt_matches(result, expected):
            if self._unresolved_submit is expected:
                self._unresolved_submit = None
            self._settings.setValue("last_log_author", str(expected.get("author", "")))
            if self._message_edit.toPlainText().strip() == expected.get("message"):
                self._message_edit.clear()
            if self._tags_edit.text() == expected.get("tags_text"):
                self._tags_edit.clear()
            if result.get("ok") is True:
                self.show_info("Запись подтверждена журналом.")
            else:
                self.show_warning(
                    "Запись сохранена, но публикация подтверждения требует сверки. Содержимое не потеряно.",
                    persistent=True,
                )
            self._update_composer_enablement()
            self.refresh_entries()
            return

        if result.get("committed") is True or _result_is_unknown(result):
            self._mark_submit_unknown(
                expected,
                "Engine не подтвердил, сохранена ли запись. Текст сохранён; "
                "нажмите «Сверить сохранение» после восстановления связи.",
            )
            return

        if self._unresolved_submit is expected:
            self._unresolved_submit = None
        error = result.get("error", "Не удалось сохранить запись.")
        self.show_error(str(error))
        self._update_composer_enablement()

    def _mark_submit_unknown(self, context: dict[str, Any], message: str) -> None:
        self._unresolved_submit = context
        self.show_unknown(message)
        self._update_composer_enablement()

    def _prune_workers(self) -> None:
        remaining: list[ZmqCommandWorker] = []
        for item in self._workers:
            try:
                if item.isRunning():
                    remaining.append(item)
            except (AttributeError, RuntimeError):
                continue
        self._workers = remaining

    # ------------------------------------------------------------------
    # Filters
    # ------------------------------------------------------------------

    def _on_chip_selected(self, key: str) -> None:
        if key == self._active_filter:
            # Re-check the button — avoid an accidental toggle-off click.
            self._filter_buttons[key].setChecked(True)
            return
        self._active_filter = key
        self._highlight_active_chip(key)
        self.filter_changed.emit(key)
        if key == _FILTER_CHIP_CURRENT:
            # Server-side filter: refetch bound to current experiment.
            self.refresh_entries()
        else:
            # Other chips are client-side — refetch to get fresh data then filter.
            self.refresh_entries()

    def _highlight_active_chip(self, active_key: str) -> None:
        for key, btn in self._filter_buttons.items():
            is_active = key == active_key
            btn.setChecked(is_active)
            _style_button(btn, "accent" if is_active else "neutral")

    def _on_search_changed(self, _text: str) -> None:
        self._search_debounce.start()

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    def refresh_entries(self) -> None:
        if not self._connected:
            return
        if self._inflight_refresh is not None:
            self._refresh_pending = True
            return

        payload: dict = {"cmd": "log_get", "limit": self._limit}
        experiment_id: str | None = None
        if self._active_filter == _FILTER_CHIP_CURRENT:
            experiment_id = self._current_experiment_id
            if experiment_id is None:
                self._entries_all = []
                self._apply_filters()
                self.show_warning("Нет активного эксперимента: текущий журнал пуст.")
                return
            payload.update(
                {
                    "log_scope": "experiment",
                    "experiment_id": experiment_id,
                }
            )
        else:
            payload["log_scope"] = "all"

        self._refresh_sequence += 1
        context: dict[str, Any] = {
            "sequence": self._refresh_sequence,
            "generation": self._state_generation,
            "filter": self._active_filter,
            "log_scope": payload["log_scope"],
            "experiment_id": experiment_id,
        }
        worker = ZmqCommandWorker(payload, parent=self)
        worker.finished.connect(
            lambda result, expected=context, completed_worker=worker: self._on_refresh_result(
                result, expected, completed_worker
            )
        )
        self._inflight_refresh = worker
        self._refresh_context = context
        self._workers.append(worker)
        worker.start()

    @staticmethod
    def _scope_receipt_matches(result: object, context: dict[str, Any]) -> bool:
        if not isinstance(result, dict):
            return False
        receipt = result.get("scope_receipt")
        return (
            isinstance(receipt, dict)
            and receipt.get("schema") == _LOG_READ_SCOPE_SCHEMA
            and receipt.get("log_scope") == context.get("log_scope")
            and receipt.get("experiment_id") == context.get("experiment_id")
        )

    def _on_refresh_result(
        self,
        result: dict,
        context: dict[str, Any] | None = None,
        worker: ZmqCommandWorker | None = None,
    ) -> None:
        expected = context or self._refresh_context
        if worker is not None and worker is not self._inflight_refresh:
            return
        if worker is not None:
            self._inflight_refresh = None
            self._refresh_context = None
        self._prune_workers()
        if expected is None:
            self.show_error("Получен ответ журнала без области чтения.", persistent=True)
            return

        current_request = (
            expected.get("generation") == self._state_generation
            and self._connected
            and expected.get("filter") == self._active_filter
            and (
                expected.get("log_scope") != "experiment"
                or expected.get("experiment_id") == self._current_experiment_id
            )
        )
        if not current_request:
            self._finish_refresh_cycle()
            return
        if not result.get("ok", False):
            error = result.get("error", "Не удалось загрузить журнал.")
            self.show_warning(f"Журнал не обновлён; показаны последние данные. {error}", persistent=True)
            # Keep existing timeline — don't wipe on failure.
            self._finish_refresh_cycle()
            return
        if not self._scope_receipt_matches(result, expected):
            self.show_warning(
                "Engine вернул журнал без точного подтверждения области; показаны последние данные.",
                persistent=True,
            )
            self._finish_refresh_cycle()
            return
        raw_entries = result.get("entries")
        if not isinstance(raw_entries, list) or not all(isinstance(entry, dict) for entry in raw_entries):
            self.show_warning("Engine вернул повреждённый журнал; показаны последние данные.", persistent=True)
            self._finish_refresh_cycle()
            return
        entries = list(raw_entries)
        self._entries_all = _sort_entries(entries)
        self._apply_filters()
        self.entries_loaded.emit(len(self._entries_all))
        if self._unresolved_submit is None:
            self.clear_message()
        self._finish_refresh_cycle()

    def _finish_refresh_cycle(self) -> None:
        if not self._refresh_pending:
            return
        self._refresh_pending = False
        QTimer.singleShot(0, self.refresh_entries)

    def _on_load_more_clicked(self) -> None:
        self._limit += _LIMIT_STEP
        self.refresh_entries()

    # ------------------------------------------------------------------
    # Filter + render pipeline
    # ------------------------------------------------------------------

    def _apply_filters(self) -> None:
        search = self._search_edit.text().strip().lower()
        author_q = self._author_filter_edit.text().strip().lower()
        tag_q = self._tag_filter_edit.text().strip().lower()
        chip = self._active_filter

        now = datetime.now().astimezone()
        cutoff: datetime | None = None
        if chip == _FILTER_CHIP_LAST_8H:
            cutoff = now - timedelta(hours=8)
        elif chip == _FILTER_CHIP_LAST_24H:
            cutoff = now - timedelta(hours=24)

        filtered: list[dict] = []
        for entry in self._entries_all:
            if cutoff is not None:
                ts = _parse_entry_timestamp(str(entry.get("timestamp", "")))
                if ts is None or ts < cutoff:
                    continue
            if search:
                message = str(entry.get("message", "")).lower()
                if search not in message:
                    continue
            if author_q:
                author = str(entry.get("author", "")).lower()
                if author != author_q:
                    continue
            if tag_q:
                tags = [str(t).lower() for t in (entry.get("tags") or [])]
                if tag_q not in tags:
                    continue
            filtered.append(entry)
        self._filtered_entries = filtered
        self._render_timeline()
        self._loaded_label.setText(f"Загружено: {len(self._entries_all)} записей · отфильтровано: {len(filtered)}")

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------

    def _clear_timeline(self) -> None:
        # Remove everything except the trailing stretch.
        while self._timeline_layout.count() > 1:
            item = self._timeline_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _render_timeline(self) -> None:
        self._clear_timeline()
        if not self._filtered_entries:
            self._empty_state_label.setVisible(True)
            return
        self._empty_state_label.setVisible(False)

        current_day: str | None = None
        # Entries already sorted newest-first; insert before the trailing stretch.
        insert_at = 0
        for entry in self._filtered_entries:
            ts = _parse_entry_timestamp(str(entry.get("timestamp", "")))
            day = ts.strftime(_DAY_HEADER_FORMAT) if ts is not None else "—"
            if day != current_day:
                self._timeline_layout.insertWidget(insert_at, self._build_day_header(day))
                insert_at += 1
                current_day = day
            self._timeline_layout.insertWidget(insert_at, self._build_entry_row(entry, ts))
            insert_at += 1

    def _build_day_header(self, day_text: str) -> QWidget:
        label = QLabel(f"── {day_text} ──")
        label.setFont(_label_font())
        label.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND};"
            f" background: transparent; border: none;"
            f" letter-spacing: 1px;"
            f" padding-top: {theme.SPACE_2}px;"
            f" padding-bottom: {theme.SPACE_1}px;"
        )
        return label

    def _build_entry_row(self, entry: dict, ts: datetime | None) -> QWidget:
        row = QWidget()
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row.setStyleSheet("background-color: transparent;")
        layout = QVBoxLayout(row)
        layout.setContentsMargins(theme.SPACE_2, theme.SPACE_1, theme.SPACE_2, theme.SPACE_1)
        layout.setSpacing(theme.SPACE_0 if theme.SPACE_0 else 0)

        is_system = str(entry.get("author", "")).strip().lower() == "system"
        primary_color = theme.MUTED_FOREGROUND if is_system else theme.FOREGROUND

        head_row = QHBoxLayout()
        head_row.setContentsMargins(0, 0, 0, 0)
        head_row.setSpacing(theme.SPACE_2)

        time_label = QLabel(ts.strftime(_TIME_FORMAT) if ts is not None else "—")
        time_label.setFont(_mono_time_font())
        time_label.setStyleSheet(f"color: {primary_color}; background: transparent; border: none;")
        time_label.setFixedWidth(52)
        head_row.addWidget(time_label)

        author_text = str(entry.get("author") or entry.get("source") or "system")
        author_label = QLabel(author_text)
        author_label.setFont(_label_font())
        author_label.setStyleSheet(
            f"color: {primary_color}; background: transparent; border: none; font-weight: {theme.FONT_WEIGHT_SEMIBOLD};"
        )
        head_row.addWidget(author_label)
        head_row.addStretch()
        layout.addLayout(head_row)

        message_label = QLabel(str(entry.get("message", "")))
        message_label.setFont(_body_font())
        message_label.setWordWrap(True)
        message_label.setStyleSheet(
            f"color: {primary_color}; background: transparent; border: none; padding-left: 56px;"
        )
        layout.addWidget(message_label)

        chips_row = QHBoxLayout()
        chips_row.setContentsMargins(56, 0, 0, 0)
        chips_row.setSpacing(theme.SPACE_1)
        experiment_id = entry.get("experiment_id")
        if experiment_id:
            chips_row.addWidget(self._build_chip(f"experiment: {experiment_id}"))
        tags = entry.get("tags") or []
        for tag in tags:
            chips_row.addWidget(self._build_chip(f"tag: {tag}"))
        chips_row.addStretch()
        if experiment_id or tags:
            layout.addLayout(chips_row)

        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        return row

    def _build_chip(self, text: str) -> QLabel:
        chip = QLabel(text)
        chip.setFont(_label_font())
        chip.setStyleSheet(
            f"QLabel {{"
            f" color: {theme.FOREGROUND};"
            f" background-color: {theme.SURFACE_CARD};"
            f" border: 1px solid {theme.BORDER_SUBTLE};"
            f" border-radius: {theme.RADIUS_SM}px;"
            f" padding: {theme.SPACE_0}px {theme.SPACE_2}px;"
            f"}}"
        )
        return chip

    # ------------------------------------------------------------------
    # Public state pushers
    # ------------------------------------------------------------------

    def on_reading(self, reading: Reading) -> None:
        if reading.channel != _LOG_ENTRY_CHANNEL:
            return
        self.refresh_entries()

    def set_connected(self, connected: bool) -> None:
        connected = bool(connected)
        if connected == self._connected:
            return
        self._connected = connected
        self._state_generation += 1
        if not connected and self._submit_context is not None:
            self._mark_submit_unknown(
                self._submit_context,
                "Связь потеряна до подтверждения записи. Исход неизвестен; текст и ключ операции сохранены.",
            )
        self._update_composer_enablement()
        if not connected:
            if self._unresolved_submit is None:
                self.show_error("Нет связи с engine; показаны последние данные журнала.", persistent=True)
        else:
            if self._unresolved_submit is not None:
                self.show_unknown(
                    "Предыдущая запись имеет неизвестный исход. "
                    "Нажмите «Сверить сохранение»; новый текст не отправляется.",
                )
            else:
                self.clear_message()
            self.refresh_entries()

    def set_read_only(self, read_only: bool) -> None:
        """Keep the timeline searchable while disabling replay log writes."""

        read_only = bool(read_only)
        if read_only == self._read_only:
            return
        self._read_only = read_only
        self._state_generation += 1
        if read_only and self._submit_context is not None:
            self._mark_submit_unknown(
                self._submit_context,
                "Режим изменился до подтверждения записи. Исход неизвестен; повторная мутация заблокирована.",
            )
        self._update_composer_enablement()

    def set_current_experiment(self, exp_id: str | None) -> None:
        exp_id = str(exp_id) if exp_id is not None else None
        if exp_id == self._current_experiment_id:
            return
        self._current_experiment_id = exp_id
        self._state_generation += 1
        has_active = exp_id is not None
        self._bind_experiment_check.setEnabled(
            has_active
            and self._connected
            and not self._read_only
            and self._submit_worker is None
            and self._unresolved_submit is None
        )
        if not has_active:
            self._bind_experiment_check.setChecked(False)
        else:
            self._bind_experiment_check.setChecked(True)
        # The "current experiment" chip is only meaningful when there's
        # an active experiment. Keep it clickable regardless — server
        # returns empty list otherwise and that's a valid state.
        if self._active_filter == _FILTER_CHIP_CURRENT:
            self.refresh_entries()

    def _update_composer_enablement(self) -> None:
        mutable = (
            self._connected and not self._read_only and self._submit_worker is None and self._unresolved_submit is None
        )
        self._bind_experiment_check.setEnabled(mutable and self._current_experiment_id is not None)
        self._author_edit.setEnabled(mutable)
        self._tags_edit.setEnabled(mutable)
        self._message_edit.setEnabled(mutable)
        can_reconcile = (
            self._connected
            and not self._read_only
            and self._submit_worker is None
            and self._unresolved_submit is not None
        )
        self._submit_btn.setText("Сверить сохранение" if self._unresolved_submit is not None else "Сохранить")
        self._submit_btn.setEnabled(mutable or can_reconcile)

    # ------------------------------------------------------------------
    # Banner
    # ------------------------------------------------------------------

    def show_info(self, text: str) -> None:
        self._set_banner(text, theme.STATUS_INFO)

    def show_warning(self, text: str, *, persistent: bool = False) -> None:
        self._set_banner(text, theme.STATUS_CAUTION, persistent=persistent)

    def show_unknown(self, text: str) -> None:
        self._set_banner(text, theme.STATUS_CAUTION, persistent=True)

    def show_error(self, text: str, *, persistent: bool = False) -> None:
        self._set_banner(text, theme.STATUS_FAULT, persistent=persistent)

    def clear_message(self) -> None:
        self._banner_label.setText("")
        self._banner_label.setVisible(False)
        self._banner_timer.stop()

    def _set_banner(self, text: str, color: str, *, persistent: bool = False) -> None:
        self._banner_label.setText(text)
        self._banner_label.setStyleSheet(
            f"#operatorLogBanner {{"
            f" color: {theme.FOREGROUND};"
            f" background-color: {theme.SURFACE_CARD};"
            f" border: 1px solid {color};"
            f" border-radius: {theme.RADIUS_SM}px;"
            f"}}"
        )
        self._banner_label.setVisible(True)
        if persistent:
            self._banner_timer.stop()
        else:
            self._banner_timer.start()
