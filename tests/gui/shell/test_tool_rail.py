"""Smoke tests for ToolRail (Phase UI-1 v2 Block A)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from cryodaq.gui import theme
from cryodaq.gui.shell.tool_rail import _MNEMONIC_SHORTCUTS, ToolRail


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_tool_rail_constructs() -> None:
    _app()
    rail = ToolRail()
    expected = {
        "home",
        "new_experiment",
        "experiment",
        "source",
        "analytics",
        "conductivity",
        "alarms",
        "log",
        "instruments",
        "more",
    }
    assert expected.issubset(rail._buttons.keys())


def test_buttons_emit_tool_clicked_with_name() -> None:
    _app()
    rail = ToolRail()
    seen: list[str] = []
    rail.tool_clicked.connect(lambda name: seen.append(name))
    for name in ("home", "experiment", "source", "alarms"):
        rail._buttons[name].click()
    assert seen == ["home", "experiment", "source", "alarms"]


def test_set_active_marks_one_button() -> None:
    _app()
    rail = ToolRail()
    rail.set_active("source")
    assert rail._buttons["source"]._active is True
    assert rail._buttons["home"]._active is False
    rail.set_active("home")
    assert rail._buttons["home"]._active is True
    assert rail._buttons["source"]._active is False


def test_rail_width_matches_design_token() -> None:
    # DESIGN: invariant TOOL_RAIL_WIDTH (56), couples to HEADER_HEIGHT.
    _app()
    rail = ToolRail()
    assert rail.width() == theme.TOOL_RAIL_WIDTH
    assert theme.TOOL_RAIL_WIDTH == 56


def test_buttons_are_square_56() -> None:
    # DESIGN: slots are 56×56 square per spec anatomy.
    _app()
    rail = ToolRail()
    for name, btn in rail._buttons.items():
        assert btn.width() == theme.TOOL_RAIL_WIDTH, f"{name} width != 56"
        assert btn.height() == theme.TOOL_RAIL_WIDTH, f"{name} height != 56"


def test_mnemonic_shortcuts_defined_for_canonical_panels() -> None:
    # DESIGN: docs/design-system/tokens/keyboard-shortcuts.md (AD-002).
    # Canonical mnemonic scheme must cover these eight panels at minimum.
    _app()
    ToolRail()
    for seq in ("Ctrl+L", "Ctrl+E", "Ctrl+A", "Ctrl+K",
                "Ctrl+M", "Ctrl+R", "Ctrl+C", "Ctrl+D"):
        assert seq in _MNEMONIC_SHORTCUTS, f"{seq} missing from ToolRail registry"


def test_mnemonic_shortcut_emits_tool_clicked() -> None:
    # A shortcut fire must go through the same tool_clicked channel as a
    # mouse click so the parent shell's single slot-activation handler
    # sees both paths identically.
    from PySide6.QtGui import QKeySequence

    _app()
    rail = ToolRail()
    seen: list[str] = []
    rail.tool_clicked.connect(lambda name: seen.append(name))
    # Find the QShortcut bound to Ctrl+L and activate it programmatically.
    ctrl_l = QKeySequence("Ctrl+L")
    from PySide6.QtGui import QShortcut
    shortcuts = [c for c in rail.children() if isinstance(c, QShortcut)]
    matches = [s for s in shortcuts if s.key() == ctrl_l]
    assert matches, "Ctrl+L shortcut not registered on rail"
    matches[0].activated.emit()
    assert seen == ["log"]
