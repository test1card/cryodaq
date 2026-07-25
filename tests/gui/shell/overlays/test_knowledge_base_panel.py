"""v0.55.6 — KnowledgeBasePanel overlay tests."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from cryodaq.gui.shell.overlays.knowledge_base_panel import (
    _CHAT_ITEM_ID,
    _PAGE_CHAT,
    _PAGE_EMPTY,
    _PAGE_RAG,
    KnowledgeBasePanel,
    _builtin_categories,
    _load_categories,
)


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------------------
# _load_categories
# ---------------------------------------------------------------------------


def test_load_categories_returns_builtin_when_file_missing(tmp_path: Path) -> None:
    missing = tmp_path / "nope.yaml"
    cats = _load_categories(missing)
    assert cats == _builtin_categories()


def test_load_categories_parses_valid_yaml(tmp_path: Path) -> None:
    f = tmp_path / "cats.yaml"
    f.write_text(
        "categories:\n  - id: x\n    label: 'X'\n    query: 'q'\n    limit: 3\n",
        encoding="utf-8",
    )
    cats = _load_categories(f)
    assert len(cats) == 1
    # LOW: assert full category dict values, not just presence.
    assert cats[0]["id"] == "x"
    assert cats[0]["label"] == "X"
    assert cats[0]["query"] == "q"
    assert cats[0]["limit"] == 3


def test_load_categories_skips_invalid_entries(tmp_path: Path) -> None:
    f = tmp_path / "cats.yaml"
    f.write_text(
        "categories:\n"
        "  - id: ok\n"
        "    label: 'OK'\n"
        "    query: 'q'\n"
        "  - just a string\n"
        "  - id: missing_query\n"
        "    label: 'broken'\n",
        encoding="utf-8",
    )
    cats = _load_categories(f)
    assert len(cats) == 1
    assert cats[0]["id"] == "ok"


def test_load_categories_falls_back_on_parse_error(tmp_path: Path) -> None:
    f = tmp_path / "broken.yaml"
    f.write_text("categories: [\n", encoding="utf-8")  # invalid YAML
    cats = _load_categories(f)
    assert cats == _builtin_categories()


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------


def _custom_categories():
    return [
        {"id": "alpha", "label": "Alpha", "query": "a", "limit": 5},
        {"id": "beta", "label": "Beta", "query": "b", "limit": 7},
    ]


def test_panel_constructs_with_categories(app: QApplication) -> None:
    panel = KnowledgeBasePanel(categories=_custom_categories())
    # 2 categories + separator + chat entry = 4 items.
    assert panel._list.count() == 4
    # Default page is the empty welcome.
    assert panel._stack.currentIndex() == _PAGE_EMPTY
    # LOW: assert item texts + UserRole ids.
    item0 = panel._list.item(0)
    assert item0.text() == "Alpha"
    assert item0.data(Qt.ItemDataRole.UserRole) == "alpha"
    item1 = panel._list.item(1)
    assert item1.text() == "Beta"
    assert item1.data(Qt.ItemDataRole.UserRole) == "beta"
    panel.deleteLater()


def test_clicking_category_switches_to_rag_page(app: QApplication) -> None:
    """MED: drive real itemClicked signal path; spy exact rag.search command."""
    from cryodaq.gui.shell.overlays import knowledge_base_panel

    ZmqCommandWorker = knowledge_base_panel.ZmqCommandWorker

    panel = KnowledgeBasePanel(categories=_custom_categories())
    dispatched: list[dict] = []

    # Intercept ZmqCommandWorker construction to capture the command dict.
    original_init = ZmqCommandWorker.__init__

    def _fake_init(self_w, cmd, **kwargs):
        dispatched.append(dict(cmd))
        # Prevent actual ZMQ connection; stub start/finished.
        original_init(self_w, cmd, **kwargs)

    with patch.object(knowledge_base_panel, "ZmqCommandWorker", ZmqCommandWorker):
        with patch.object(ZmqCommandWorker, "__init__", _fake_init):
            with patch.object(ZmqCommandWorker, "start", lambda self_w: None):
                # Click first item via the real list itemClicked signal.
                item = panel._list.item(0)
                panel._list.setCurrentItem(item)
                panel._list.itemClicked.emit(item)

    assert panel._stack.currentIndex() == _PAGE_RAG
    # Loading state visible.
    assert "Alpha" in panel._snippet_pane._title.text()
    # MED: assert exact rag.search command dispatched.
    assert len(dispatched) >= 1
    assert dispatched[0] == {"cmd": "rag.search", "query": "a", "limit": 5}
    panel.deleteLater()


def test_clicking_chat_switches_to_chat_page(app: QApplication) -> None:
    """MED: trigger item via itemClicked signal, not direct handler call."""
    panel = KnowledgeBasePanel(categories=_custom_categories())
    # Chat item is the last one.
    chat_idx = panel._list.count() - 1
    item = panel._list.item(chat_idx)
    assert item.data(Qt.ItemDataRole.UserRole) == _CHAT_ITEM_ID
    # Trigger via real signal path.
    panel._list.setCurrentItem(item)
    panel._list.itemClicked.emit(item)
    assert panel._stack.currentIndex() == _PAGE_CHAT
    panel.deleteLater()


def test_separator_item_is_not_clickable(app: QApplication) -> None:
    panel = KnowledgeBasePanel(categories=_custom_categories())
    sep_idx = len(_custom_categories())  # separator follows the categories
    sep = panel._list.item(sep_idx)
    assert not (sep.flags() & Qt.ItemFlag.ItemIsSelectable)
    panel.deleteLater()


def test_set_connected_runs_without_error(app: QApplication) -> None:
    panel = KnowledgeBasePanel(categories=_custom_categories())
    panel.set_connected(True)
    panel.set_connected(False)
    panel.deleteLater()


def test_snippet_pane_renders_results(app: QApplication) -> None:
    """MED: assert displayed body text, source label, and score — not just count."""
    panel = KnowledgeBasePanel(categories=_custom_categories())
    result = {
        "chunk_id": "c1",
        "source_kind": "vault",
        "source_id": "doc1",
        "text": "Это текст документа.",
        "metadata": {},
        "score": 0.5,
    }
    panel._snippet_pane.set_results("Alpha", [result])
    # 1 card + trailing stretch
    assert panel._snippet_pane._scroll_layout.count() == 2
    # MED: assert rendered body text and score inside the card widget.
    card = panel._snippet_pane._scroll_layout.itemAt(0).widget()
    assert card is not None
    # Find body label (second child QLabel in the card).
    from PySide6.QtWidgets import QLabel

    labels = card.findChildren(QLabel)
    texts = [lbl.text() for lbl in labels]
    # Body text must appear.
    assert any("Это текст документа." in t for t in texts)
    # Score must appear.
    assert any("0.500" in t for t in texts)
    panel.deleteLater()


def test_snippet_pane_set_error(app: QApplication) -> None:
    panel = KnowledgeBasePanel(categories=_custom_categories())
    panel._snippet_pane.set_error("Alpha", "RAG индекс не построен")
    assert "Ошибка" in panel._snippet_pane._status.text()
    assert "RAG индекс не построен" in panel._snippet_pane._status.text()
    panel.deleteLater()


def test_snippet_pane_empty_results(app: QApplication) -> None:
    panel = KnowledgeBasePanel(categories=_custom_categories())
    panel._snippet_pane.set_results("Alpha", [])
    assert "Ничего не найдено" in panel._snippet_pane._status.text()
    panel.deleteLater()


# ---------------------------------------------------------------------------
# Live panel is observational; index construction is offline-only
# ---------------------------------------------------------------------------


def test_panel_exposes_only_read_only_actions_and_offline_guidance(
    app: QApplication,
) -> None:
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QAbstractButton, QLabel

    panel = KnowledgeBasePanel(categories=_custom_categories())
    with patch("cryodaq.gui.shell.overlays.knowledge_base_panel.ZmqCommandWorker") as worker_type:
        for index in range(panel._list.count()):
            item = panel._list.item(index)
            if item.flags() & Qt.ItemFlag.ItemIsSelectable:
                panel._list.setCurrentItem(item)
                panel._on_item_clicked(item)
        for button in panel.findChildren(QAbstractButton):
            if button.isEnabled():
                button.click()
        for action in panel.findChildren(QAction):
            if action.isEnabled():
                action.trigger()
        for timer in panel.findChildren(QTimer):
            timer.timeout.emit()

    dispatched = [call.kwargs["cmd"] for call in worker_type.call_args_list]

    assert any(command["cmd"] == "rag.search" for command in dispatched)
    assert {command["cmd"] for command in dispatched} <= {"rag.search", "assistant.query"}
    label_text = " ".join(label.text() for label in panel.findChildren(QLabel))
    assert "cryodaq-rag-index" in label_text
    panel.deleteLater()
