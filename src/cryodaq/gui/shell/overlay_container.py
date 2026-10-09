"""OverlayContainer — QStackedWidget hosting dashboard + overlay panels.

Phase UI-1 v2 Block A. The dashboard is the existing OverviewPanel for
now (Block B will rewrite the dashboard internals). Overlays are the
existing detail panels hosted as full-takeover stack pages.

v0.55.15 (Codex audit SCOPE 5 finding 5.6) — added ``unregister`` and
``clear_all`` so overlays can be released on shutdown / re-init
instead of accumulating ``_pages`` entries forever. Existing
``register()`` now also schedules ``deleteLater()`` on the displaced
widget when overwriting an entry; previously the old QWidget stayed
parented to the stack but was orphaned in ``_pages``.
"""

from __future__ import annotations

from PySide6.QtWidgets import QStackedWidget, QWidget


class OverlayContainer(QStackedWidget):
    """Stacked widget switching between dashboard and overlay panels.

    Method ``register(name, widget)`` adds a page. ``show_dashboard()``
    switches to the page registered as ``"home"``. ``show_overlay(name)``
    switches to the named overlay. ``current_overlay`` returns the name
    of whatever is currently shown. ``unregister(name)`` releases a
    page and schedules the widget for deletion. ``clear_all()`` is the
    shutdown helper.
    """

    DASHBOARD_NAME = "home"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pages: dict[str, QWidget] = {}
        self._current: str | None = None

    def register(self, name: str, widget: QWidget) -> None:
        """Add a page under ``name``. Overwrites any existing entry."""
        existing = self._pages.get(name)
        if existing is not None:
            self.removeWidget(existing)
            # v0.55.15 — schedule deletion so the displaced widget's
            # signal connections, child timers, and child widgets are
            # released; otherwise it stays alive parentless under the
            # stacked widget's previous bookkeeping.
            existing.deleteLater()
        self._pages[name] = widget
        self.addWidget(widget)

    def unregister(self, name: str) -> bool:
        """v0.55.15 — release a page from the container.

        Removes the widget from the stack, drops the ``_pages`` entry,
        and schedules the widget for deletion. If ``name`` was the
        currently-displayed overlay, the dashboard takes over. Returns
        True if the page existed.
        """
        widget = self._pages.pop(name, None)
        if widget is None:
            return False
        if self._current == name:
            self._current = None
            self.show_dashboard()
        self.removeWidget(widget)
        widget.deleteLater()
        return True

    def clear_all(self) -> None:
        """v0.55.15 — release every overlay (called on shutdown).

        The dashboard page (``DASHBOARD_NAME``) is exempt — it stays
        registered because the container's invariant is that there is
        always something to show.
        """
        for name in list(self._pages):
            if name == self.DASHBOARD_NAME:
                continue
            self.unregister(name)

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

    @property
    def page_names(self) -> list[str]:
        """v0.55.15 — list registered page names (for tests / introspection)."""
        return list(self._pages)
