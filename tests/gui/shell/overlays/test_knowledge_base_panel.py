"""v0.55.6 — KnowledgeBasePanel overlay tests."""

from __future__ import annotations

import os
from pathlib import Path

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
        "categories:\n"
        "  - id: x\n"
        "    label: 'X'\n"
        "    query: 'q'\n"
        "    limit: 3\n",
        encoding="utf-8",
    )
    cats = _load_categories(f)
    assert len(cats) == 1
    assert cats[0]["id"] == "x"
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
    panel.deleteLater()


def test_clicking_category_switches_to_rag_page(app: QApplication) -> None:
    panel = KnowledgeBasePanel(categories=_custom_categories())
    item = panel._list.item(0)
    panel._on_item_clicked(item)
    assert panel._stack.currentIndex() == _PAGE_RAG
    # Loading state visible.
    assert "Alpha" in panel._snippet_pane._title.text()
    panel.deleteLater()


def test_clicking_chat_switches_to_chat_page(app: QApplication) -> None:
    panel = KnowledgeBasePanel(categories=_custom_categories())
    # Chat item is the last one.
    chat_idx = panel._list.count() - 1
    item = panel._list.item(chat_idx)
    assert item.data(Qt.ItemDataRole.UserRole) == _CHAT_ITEM_ID
    panel._on_item_clicked(item)
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
    panel = KnowledgeBasePanel(categories=_custom_categories())
    panel._snippet_pane.set_results(
        "Alpha",
        [
            {
                "chunk_id": "c1",
                "source_kind": "vault",
                "source_id": "doc1",
                "text": "Это текст документа.",
                "metadata": {},
                "score": 0.5,
            }
        ],
    )
    # 1 card + trailing stretch
    assert panel._snippet_pane._scroll_layout.count() == 2
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
