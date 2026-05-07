"""KnowledgeBasePanel — RAG knowledge base + embedded Гемма chat (v0.55.6 PART C).

Architectural note: the original v0.55.6 spec proposed embedding the RAG
sidebar inside the existing ``archive_panel.py``. Reconnaissance found
archive_panel.py at 1181 lines with deep ZMQ wiring — out of scope for
this tag — so this overlay is a sibling surface instead. ToolRail entry
"knowledge_base" lives in the More menu and renders this panel as a
full-takeover overlay; Архив stays untouched.

Layout:

    QSplitter (horizontal)
        LEFT (~220 px): QListWidget categories (loaded from config)
            Categories drive `rag.search` ZMQ commands.
            "🤖 Помощник Гемма" item switches the right pane to the
            embedded AssistantChatPanel.
        RIGHT: QStackedWidget
            Page 0: RAG snippet pane — cards rendered from search results.
            Page 1: AssistantChatPanel (F34 reused, NOT a separate
                    ToolRail entry to avoid duplicate surfaces).

Engine ZMQ contract:
    {"cmd": "rag.search", "query": str, "limit": int}
        → {"ok": True, "results": [{"chunk_id", "source_kind",
                                    "source_id", "text", "metadata",
                                    "score"}, ...]}
        or {"ok": False, "error": str}.

Out of scope (v0.55.7+):
    file://-open buttons on snippet cards (operator-action only,
    deferred), per-result thumbnail extraction, full-text search
    fallback when RAG index is missing.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from cryodaq.gui import theme
from cryodaq.gui.shell.overlays.assistant_chat_panel import AssistantChatPanel
from cryodaq.gui.zmq_client import ZmqCommandWorker

logger = logging.getLogger(__name__)


# Right-pane stacked-widget page indices. Module constants instead of
# free integers so callers can pass a meaningful argument.
_PAGE_RAG = 0
_PAGE_CHAT = 1
_PAGE_EMPTY = 2

_CHAT_ITEM_ID = "__chat__"
# __file__ → src/cryodaq/gui/shell/overlays/knowledge_base_panel.py.
# parents[5] is the repo root; the config file lives at <root>/config/.
_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[5] / "config" / "rag_categories.yaml"


def _load_categories(config_path: Path | None = None) -> list[dict[str, Any]]:
    """Load RAG sidebar categories from config/rag_categories.yaml.

    Reads ``rag_categories.local.yaml`` first (operator-customised) and
    falls back to ``rag_categories.yaml`` (shipped defaults). Returns a
    sane built-in list when neither file exists so the panel still
    constructs in a fresh checkout.
    """
    if config_path is None:
        candidate = _DEFAULT_CONFIG_PATH.parent / "rag_categories.local.yaml"
        config_path = candidate if candidate.exists() else _DEFAULT_CONFIG_PATH
    if not config_path.exists():
        return _builtin_categories()
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        logger.warning("rag_categories.yaml: parse error, using built-ins", exc_info=True)
        return _builtin_categories()
    cats = raw.get("categories") or []
    if not isinstance(cats, list):
        return _builtin_categories()
    cleaned: list[dict[str, Any]] = []
    for entry in cats:
        if not isinstance(entry, dict):
            continue
        if "id" not in entry or "label" not in entry or "query" not in entry:
            continue
        cleaned.append(
            {
                "id": str(entry["id"]),
                "label": str(entry["label"]),
                "query": str(entry["query"]),
                "limit": int(entry.get("limit", 10)),
            }
        )
    return cleaned or _builtin_categories()


def _builtin_categories() -> list[dict[str, Any]]:
    return [
        {"id": "safety", "label": "📚 Безопасность", "query": "safety regulations cryogenic", "limit": 10},
        {"id": "cryostat", "label": "❄️ Криостат", "query": "cryostat operation manual", "limit": 10},
        {"id": "procedures", "label": "📋 Procedures", "query": "experimental procedure CryoDAQ", "limit": 10},
        {"id": "manuals", "label": "📖 Manuals", "query": "operator manual instruction", "limit": 10},
    ]


class _SnippetCard(QFrame):
    """One RAG result card: source_kind/source_id header + excerpt body."""

    def __init__(
        self,
        result: dict[str, Any],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("RagSnippetCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#RagSnippetCard {{ background: {theme.SURFACE_CARD}; "
            f"border: 1px solid {theme.BORDER_SUBTLE}; "
            f"border-radius: {theme.RADIUS_SM}px; "
            f"padding: {theme.SPACE_3}px; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_2)

        kind = str(result.get("source_kind", "?"))
        source_id = str(result.get("source_id", "?"))
        score = result.get("score", 0.0)
        try:
            score_str = f" · score {float(score):.3f}"
        except (TypeError, ValueError):
            score_str = ""
        header = QLabel(f"<b>{kind}</b> · {source_id}{score_str}")
        header.setTextFormat(Qt.TextFormat.RichText)
        header.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
        layout.addWidget(header)

        text = str(result.get("text", ""))
        body = QLabel(text)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body.setStyleSheet(f"color: {theme.FOREGROUND};")
        layout.addWidget(body)


class _RagSnippetPane(QWidget):
    """Right-pane page for RAG snippet results (header + scrollable card list)."""

    rag_search_requested = Signal(str, int)  # query, limit

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._workers: list[ZmqCommandWorker] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        outer.setSpacing(theme.SPACE_2)

        self._title = QLabel("Выберите категорию слева")
        tfont: QFont = self._title.font()
        tfont.setBold(True)
        tfont.setPointSize(tfont.pointSize() + 1)
        self._title.setFont(tfont)
        self._title.setStyleSheet(f"color: {theme.FOREGROUND};")
        outer.addWidget(self._title)

        self._status = QLabel("")
        self._status.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
        outer.addWidget(self._status)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_inner = QWidget()
        self._scroll_layout = QVBoxLayout(self._scroll_inner)
        self._scroll_layout.setContentsMargins(0, 0, 0, 0)
        self._scroll_layout.setSpacing(theme.SPACE_2)
        self._scroll_layout.addStretch(1)
        self._scroll.setWidget(self._scroll_inner)
        outer.addWidget(self._scroll, stretch=1)

    # --- public API ---
    def set_loading(self, label: str) -> None:
        self._title.setText(label)
        self._status.setText("Загрузка…")
        self._clear_cards()

    def set_results(self, label: str, results: list[dict[str, Any]]) -> None:
        self._title.setText(label)
        if not results:
            self._status.setText("Ничего не найдено.")
            self._clear_cards()
            return
        self._status.setText(f"Найдено: {len(results)}")
        self._clear_cards()
        for r in results:
            card = _SnippetCard(r, self)
            self._scroll_layout.insertWidget(self._scroll_layout.count() - 1, card)

    def set_error(self, label: str, message: str) -> None:
        self._title.setText(label)
        self._status.setText(f"Ошибка: {message}")
        self._status.setStyleSheet(f"color: {theme.STATUS_FAULT};")
        self._clear_cards()

    def _clear_cards(self) -> None:
        # Iterate from the front and stop at the trailing stretch.
        while self._scroll_layout.count() > 1:
            item = self._scroll_layout.takeAt(0)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()


class KnowledgeBasePanel(QWidget):
    """Top-level overlay: categories sidebar + RAG snippets + embedded chat."""

    def __init__(
        self,
        *,
        categories: list[dict[str, Any]] | None = None,
        config_path: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._connected = False
        self._categories = categories if categories is not None else _load_categories(config_path)
        self._workers: list[ZmqCommandWorker] = []
        # v0.55.7.1 PHASE 8 — manual rebuild bookkeeping. Workers retained
        # so QThread GC doesn't race the reply; status poll timer ticks
        # every 1 s while a rebuild is running.
        self._rebuild_workers: list[ZmqCommandWorker] = []
        self._rebuild_running: bool = False
        self._rebuild_poll_timer = QTimer(self)
        self._rebuild_poll_timer.setInterval(1000)
        self._rebuild_poll_timer.timeout.connect(self._poll_rebuild_status)
        # Confirm dialogs are skipped в test mode (driven by `_confirm_rebuild`).
        self._confirm_rebuild: bool = True

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- Top toolbar: rebuild button + status label ---
        toolbar = QFrame()
        toolbar.setObjectName("KnowledgeBaseToolbar")
        toolbar.setStyleSheet(
            f"#KnowledgeBaseToolbar {{ background: {theme.SURFACE_PANEL}; "
            f"border-bottom: 1px solid {theme.BORDER_SUBTLE}; "
            f"padding: {theme.SPACE_2}px {theme.SPACE_3}px; }}"
        )
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(theme.SPACE_2, 0, theme.SPACE_2, 0)
        toolbar_layout.setSpacing(theme.SPACE_3)
        title = QLabel("База знаний CryoDAQ")
        title_font = title.font()
        title_font.setBold(True)
        title.setFont(title_font)
        title.setStyleSheet(f"color: {theme.FOREGROUND};")
        toolbar_layout.addWidget(title)
        toolbar_layout.addStretch(1)
        self._rebuild_status_label = QLabel("Готов")
        self._rebuild_status_label.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; "
            f"font-family: '{theme.FONT_MONO}'; "
            f"font-feature-settings: 'tnum';"
        )
        toolbar_layout.addWidget(self._rebuild_status_label)
        self._rebuild_button = QPushButton("Обновить индекс")
        self._rebuild_button.setToolTip(
            "Перестроить индекс базы знаний после нового PDF / процедуры. "
            "Может занять несколько минут."
        )
        self._rebuild_button.clicked.connect(self._on_rebuild_clicked)
        toolbar_layout.addWidget(self._rebuild_button)
        root.addWidget(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, stretch=1)

        # --- LEFT: categories list ---
        self._list = QListWidget()
        self._list.setMinimumWidth(180)
        self._list.setMaximumWidth(280)
        self._list.setStyleSheet(
            f"QListWidget {{ background: {theme.SURFACE_PANEL}; "
            f"border: none; border-right: 1px solid {theme.BORDER_SUBTLE}; "
            f"color: {theme.FOREGROUND}; padding: {theme.SPACE_2}px; }}"
            f"QListWidget::item {{ padding: {theme.SPACE_2}px; }}"
            f"QListWidget::item:selected {{ background: {theme.ACCENT}; "
            f"color: {theme.ON_ACCENT}; border-radius: {theme.RADIUS_SM}px; }}"
        )
        for cat in self._categories:
            item = QListWidgetItem(cat["label"])
            item.setData(Qt.ItemDataRole.UserRole, cat["id"])
            self._list.addItem(item)
        # Separator + chat entry
        sep = QListWidgetItem("─── Помощник ───")
        sep.setFlags(Qt.ItemFlag.NoItemFlags)
        sep.setForeground(self.palette().mid())
        self._list.addItem(sep)
        chat_item = QListWidgetItem("🤖 Помощник Гемма")
        chat_item.setData(Qt.ItemDataRole.UserRole, _CHAT_ITEM_ID)
        self._list.addItem(chat_item)

        self._list.itemClicked.connect(self._on_item_clicked)

        # --- RIGHT: stacked widget ---
        self._stack = QStackedWidget()
        self._snippet_pane = _RagSnippetPane()
        self._chat_panel = AssistantChatPanel()
        self._empty_pane = self._build_empty_pane()
        self._stack.insertWidget(_PAGE_RAG, self._snippet_pane)
        self._stack.insertWidget(_PAGE_CHAT, self._chat_panel)
        self._stack.insertWidget(_PAGE_EMPTY, self._empty_pane)
        self._stack.setCurrentIndex(_PAGE_EMPTY)

        splitter.addWidget(self._list)
        splitter.addWidget(self._stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([220, 800])

    def _build_empty_pane(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_4)
        layout.addStretch(1)
        title = QLabel("База знаний CryoDAQ")
        f = title.font()
        f.setBold(True)
        f.setPointSize(f.pointSize() + 4)
        title.setFont(f)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"color: {theme.FOREGROUND};")
        sub = QLabel(
            "Выберите категорию слева, чтобы посмотреть документы по теме, "
            "или откройте «Помощник Гемма» для свободного диалога."
        )
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
        layout.addWidget(title)
        layout.addSpacing(theme.SPACE_2)
        layout.addWidget(sub)
        layout.addStretch(2)
        w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        return w

    # ------------------------------------------------------------------
    # Host-wired API
    # ------------------------------------------------------------------

    def set_connected(self, connected: bool) -> None:
        self._connected = bool(connected)

    # ------------------------------------------------------------------
    # Internal handlers
    # ------------------------------------------------------------------

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        if item is None:
            return
        kind = item.data(Qt.ItemDataRole.UserRole)
        if kind == _CHAT_ITEM_ID:
            self._stack.setCurrentIndex(_PAGE_CHAT)
            return
        cat = next((c for c in self._categories if c["id"] == kind), None)
        if cat is None:
            return
        self._stack.setCurrentIndex(_PAGE_RAG)
        self._snippet_pane.set_loading(cat["label"])
        self._dispatch_rag_query(cat)

    def _dispatch_rag_query(self, cat: dict[str, Any]) -> None:
        """Fire `rag.search` via ZmqCommandWorker; results land in the snippet pane."""
        worker = ZmqCommandWorker(
            cmd={
                "cmd": "rag.search",
                "query": cat["query"],
                "limit": int(cat.get("limit", 10)),
            },
        )
        # Strong-ref retention: ZmqCommandWorker would otherwise be GC'd
        # before reply arrives because we don't keep the QThread alive.
        self._workers.append(worker)

        def _on_finished(reply: dict[str, Any] | None) -> None:
            try:
                self._workers.remove(worker)
            except ValueError:
                pass
            if reply is None:
                self._snippet_pane.set_error(cat["label"], "Engine не ответил.")
                return
            if not reply.get("ok"):
                self._snippet_pane.set_error(cat["label"], reply.get("error", "unknown"))
                return
            results = reply.get("results", [])
            if not isinstance(results, list):
                results = []
            self._snippet_pane.set_results(cat["label"], results)

        worker.finished.connect(_on_finished)
        worker.start()

    # ------------------------------------------------------------------
    # v0.55.7.1 PHASE 8 — manual rebuild dispatch
    # ------------------------------------------------------------------

    def _on_rebuild_clicked(self) -> None:
        """Confirm + dispatch rag.rebuild_index, switch к polling status."""
        if self._rebuild_running:
            # Operator clicked while engine still working — surface
            # current status instead of attempting concurrent start.
            self._poll_rebuild_status()
            return
        if self._confirm_rebuild:
            res = QMessageBox.question(
                self,
                "Перестроить индекс знаний?",
                "Перестроить индекс? Может занять несколько минут на больших PDF.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if res != QMessageBox.StandardButton.Yes:
                return
        self._send_rebuild_command("rag.rebuild_index")

    def _send_rebuild_command(self, action: str) -> None:
        worker = ZmqCommandWorker({"cmd": action}, parent=self)
        worker.finished.connect(
            lambda result, c=action: self._on_rebuild_response(c, result)
        )
        self._rebuild_workers.append(worker)
        worker.start()

    def _on_rebuild_response(self, action: str, result: dict | None) -> None:
        # Drop finished workers so the list does not grow unbounded.
        self._rebuild_workers = [
            w for w in self._rebuild_workers if w.isRunning()
        ]
        if not isinstance(result, dict):
            self._rebuild_running = False
            self._rebuild_button.setEnabled(True)
            self._rebuild_status_label.setText("Engine не ответил")
            self._rebuild_poll_timer.stop()
            return
        if not result.get("ok"):
            self._rebuild_running = False
            self._rebuild_button.setEnabled(True)
            self._rebuild_status_label.setText(str(result.get("error", "ошибка"))[:80])
            self._rebuild_poll_timer.stop()
            return
        if action == "rag.rebuild_index":
            self._rebuild_running = True
            self._rebuild_button.setEnabled(False)
            self._rebuild_status_label.setText("Индексация…")
            if not self._rebuild_poll_timer.isActive():
                self._rebuild_poll_timer.start()
            return
        if action == "rag.rebuild_status":
            state = str(result.get("state", "idle"))
            chunks = int(result.get("chunks_indexed", 0) or 0)
            err = result.get("error")
            if state == "running":
                self._rebuild_running = True
                self._rebuild_button.setEnabled(False)
                self._rebuild_status_label.setText("Индексация…")
            elif state == "complete":
                self._rebuild_running = False
                self._rebuild_button.setEnabled(True)
                self._rebuild_poll_timer.stop()
                self._rebuild_status_label.setText(
                    f"Индекс обновлён: {chunks} chunks"
                )
            elif state == "failed":
                self._rebuild_running = False
                self._rebuild_button.setEnabled(True)
                self._rebuild_poll_timer.stop()
                self._rebuild_status_label.setText(
                    (str(err) if err else "Сборка не удалась")[:80]
                )
            else:  # idle и unknown
                self._rebuild_running = False
                self._rebuild_button.setEnabled(True)
                self._rebuild_poll_timer.stop()
                self._rebuild_status_label.setText("Готов")

    def _poll_rebuild_status(self) -> None:
        if not self._rebuild_running:
            self._rebuild_poll_timer.stop()
            return
        self._send_rebuild_command("rag.rebuild_status")
