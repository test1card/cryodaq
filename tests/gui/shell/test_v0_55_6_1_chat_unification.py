"""v0.55.6.1 — chat unification regression guards.

Architect 2026-05-07: «база знаний уже в ToolRail … чат с геммой убираем
вообще». The standalone «Помощник Гемма» overlay disappears; the
embedded chat inside KnowledgeBasePanel becomes the single chat surface.
"""

from __future__ import annotations

import importlib
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.gui.shell import tool_rail


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_knowledge_base_in_main_overlay_items() -> None:
    """KnowledgeBasePanel was promoted from More menu to the main rail.
    MED: instantiate ToolRail and assert rendered button presence/tooltip/
    signal-key/active styling — not just private _OVERLAY_ITEMS list.
    """
    _app()
    from cryodaq.gui.shell.tool_rail import ToolRail

    rail = ToolRail()
    # Button must exist in the rendered rail.
    assert "knowledge_base" in rail._buttons, (
        f"knowledge_base button absent from rail; buttons: {list(rail._buttons)}"
    )
    btn = rail._buttons["knowledge_base"]
    # Tooltip matches the label from _OVERLAY_ITEMS.
    assert btn.toolTip() == "База знаний", (
        f"Unexpected tooltip: {btn.toolTip()!r}"
    )
    # Clicking the button emits tool_clicked with the correct overlay key.
    seen: list[str] = []
    rail.tool_clicked.connect(seen.append)
    btn.click()
    assert seen == ["knowledge_base"], (
        f"tool_clicked emitted wrong key: {seen}"
    )
    # Setting active must render the specific border-left declaration.
    # Assert the exact declaration (not token-anywhere) so hover/bg colours
    # cannot produce a false positive.
    from cryodaq.gui import theme

    rail.set_active("knowledge_base")
    ss = btn.styleSheet()
    _active_border = f"border-left: 3px solid {theme.ACCENT_400}"
    assert _active_border in ss, (
        f"Active knowledge_base button missing border-left declaration: {ss!r}"
    )
    # Also verify the source list for completeness (existing contract).
    names = [name for name, _, _ in tool_rail._OVERLAY_ITEMS]
    assert "knowledge_base" in names, (
        f"knowledge_base must be a main ToolRail entry; got {names}"
    )


def test_knowledge_base_removed_from_more_menu() -> None:
    more_names = [name for name, _ in tool_rail._MORE_ITEMS if name != "__separator__"]
    assert "knowledge_base" not in more_names, (
        "knowledge_base must not appear in More menu after v0.55.6.1 promotion"
    )


def test_assistant_chat_overlay_entry_removed() -> None:
    names = [name for name, _, _ in tool_rail._OVERLAY_ITEMS]
    assert "assistant_chat" not in names, (
        "F34 standalone assistant_chat overlay must be removed in v0.55.6.1"
    )
    assert "assistant_chat" not in tool_rail._PHOSPHOR_ICONS, (
        "Phosphor icon mapping for the deleted overlay must be removed too"
    )


def test_assistant_chat_panel_module_deleted() -> None:
    """The standalone overlay module is gone; the widget code lives in
    `_assistant_chat_widget` (private helper for KnowledgeBasePanel).
    """
    with pytest.raises(ImportError):
        importlib.import_module("cryodaq.gui.shell.overlays.assistant_chat_panel")


def test_assistant_chat_widget_helper_still_importable() -> None:
    """KnowledgeBasePanel still embeds the chat widget via the renamed module."""
    mod = importlib.import_module("cryodaq.gui.shell.overlays._assistant_chat_widget")
    assert hasattr(mod, "AssistantChatPanel")


def test_knowledge_base_panel_imports_chat_widget_from_helper_module() -> None:
    from cryodaq.gui.shell.overlays import knowledge_base_panel as kb

    # Trace the import path: the embedded chat must come from the renamed
    # private helper, not the deleted overlay module.
    assert kb.AssistantChatPanel.__module__ == (
        "cryodaq.gui.shell.overlays._assistant_chat_widget"
    )
