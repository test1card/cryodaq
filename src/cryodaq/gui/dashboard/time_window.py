"""Time window selector enum for dashboard plots.

Shared between TempPlotWidget (interactive picker) and TopWatchBar
(read-only echo). Modifying this single source updates both surfaces.
"""
from __future__ import annotations

from enum import Enum


class TimeWindow(Enum):
    """Time window options for plot X-axis range."""

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
        return cls.HOUR_1

    @classmethod
    def all_options(cls) -> list[TimeWindow]:
        return [cls.MIN_1, cls.HOUR_1, cls.HOUR_6, cls.HOUR_24, cls.ALL]
