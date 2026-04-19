"""Global historical-window state — one source of truth for all
history plots across the app.

The enum values retain the (label, seconds) tuple shape from the
dashboard-local definition so existing consumers can migrate
without touching downstream code.

The controller is a QObject singleton (not a module-level attribute)
because tests need to reset it and Qt signal handling requires
QObject parentage. Access via :func:`get_time_window_controller` —
it is created lazily on first call and cached. Tests can reset via
:func:`reset_time_window_controller`.

Prediction plots (cooldown predictor, vacuum trend forecast) do
NOT subscribe to this controller — they display forward-looking
horizons with their own selectors. See :class:`PredictionWidget`.
"""

from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QObject, Signal


class TimeWindow(Enum):
    """Historical time-window options for plot X-axis range."""

    MIN_1 = ("1мин", 60.0)
    HOUR_1 = ("1ч", 3600.0)
    HOUR_6 = ("6ч", 21600.0)
    HOUR_24 = ("24ч", 86400.0)
    ALL = ("Всё", float("inf"))

    @property
    def label(self) -> str:
        return self.value[0]

    @property
    def seconds(self) -> float:
        return self.value[1]

    @classmethod
    def default(cls) -> TimeWindow:
        # Cryo experiments run for hours/days; the operator's default
        # question is "how has this trended since we started running"
        # (especially for pressure, which moves over decades). "1ч" as
        # the initial window hid the long-horizon signal.
        return cls.ALL

    @classmethod
    def all_options(cls) -> list[TimeWindow]:
        return [cls.MIN_1, cls.HOUR_1, cls.HOUR_6, cls.HOUR_24, cls.ALL]


class GlobalTimeWindowController(QObject):
    """Singleton controller broadcasting time-window changes.

    Historical plots subscribe to :attr:`window_changed`. Prediction
    plots do NOT subscribe — they have their own forward-horizon
    selectors.
    """

    window_changed = Signal(object)  # emits TimeWindow

    def __init__(self) -> None:
        super().__init__()
        self._current: TimeWindow = TimeWindow.default()

    def get_window(self) -> TimeWindow:
        return self._current

    def set_window(self, window: TimeWindow) -> None:
        if self._current is window:
            return
        self._current = window
        self.window_changed.emit(window)


_controller: GlobalTimeWindowController | None = None


def get_time_window_controller() -> GlobalTimeWindowController:
    """Return the cached singleton controller, creating on first call."""
    global _controller
    if _controller is None:
        _controller = GlobalTimeWindowController()
    return _controller


def reset_time_window_controller() -> None:
    """Drop the cached singleton — for tests only.

    Next :func:`get_time_window_controller` call will create a fresh
    instance with a fresh signal-subscription table.
    """
    global _controller
    _controller = None
