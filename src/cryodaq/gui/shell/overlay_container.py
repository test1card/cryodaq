"""OverlayContainer — QStackedWidget hosting dashboard + overlay panels.

Phase UI-1 v2 Block A. The dashboard is the existing OverviewPanel for
now (Block B will rewrite the dashboard internals). Overlays are the
existing detail panels hosted as full-takeover stack pages.
"""
from __future__ import annotations

from PySide6.QtWidgets import QStackedWidget, QWidget


class OverlayContainer(QStackedWidget):
    """Stacked widget switching between dashboard and overlay panels.

    Method ``register(name, widget)`` adds a page. ``show_dashboard()``
    switches to the page registered as ``"home"``. ``show_overlay(name)``
    switches to the named overlay. ``current_overlay`` returns the name
    of whatever is currently shown.
    """

    DASHBOARD_NAME = "home"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pages: dict[str, QWidget] = {}
        self._current: str | None = None

    def register(self, name: str, widget: QWidget) -> None:
        """Add a page under ``name``. Overwrites any existing entry."""
        if name in self._pages:
            self.removeWidget(self._pages[name])
        self._pages[name] = widget
        self.addWidget(widget)

    def show_dashboard(self) -> None:
        self.show_overlay(self.DASHBOARD_NAME)

    def show_overlay(self, name: str) -> None:
        widget = self._pages.get(name)
        if widget is None:
            return
        self.setCurrentWidget(widget)
        self._current = name

    @property
    def current_overlay(self) -> str | None:
        return self._current
