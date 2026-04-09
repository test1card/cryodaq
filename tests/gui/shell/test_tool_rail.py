"""Smoke tests for ToolRail (Phase UI-1 v2 Block A)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from cryodaq.gui.shell.tool_rail import ToolRail


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_tool_rail_constructs() -> None:
    _app()
    rail = ToolRail()
    expected = {
        "home", "new_experiment", "experiment", "source", "analytics",
        "conductivity", "alarms", "log", "instruments", "more",
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
