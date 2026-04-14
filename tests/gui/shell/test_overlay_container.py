"""Smoke tests for OverlayContainer (Phase UI-1 v2 Block A)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from cryodaq.gui.shell.overlay_container import OverlayContainer


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_register_and_switch() -> None:
    _app()
    c = OverlayContainer()
    home = QLabel("home")
    panel = QLabel("source")
    c.register("home", home)
    c.register("source", panel)
    c.show_dashboard()
    assert c.currentWidget() is home
    assert c.current_overlay == "home"
    c.show_overlay("source")
    assert c.currentWidget() is panel
    assert c.current_overlay == "source"


def test_show_overlay_unknown_name_is_noop() -> None:
    _app()
    c = OverlayContainer()
    home = QLabel("home")
    c.register("home", home)
    c.show_dashboard()
    c.show_overlay("nonexistent")
    # still on home
    assert c.currentWidget() is home
