"""Report rendering package with a lightweight import boundary.

Legacy ``from cryodaq.reporting import ReportGenerator`` remains supported,
but renderer dependencies are imported only when those attributes are used.
This is required because ``python -m cryodaq.reporting`` imports the package
before executing ``reporting.__main__``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .generator import ReportGenerationResult, ReportGenerator

__all__ = ["ReportGenerationResult", "ReportGenerator"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from .generator import ReportGenerationResult, ReportGenerator

        return {
            "ReportGenerationResult": ReportGenerationResult,
            "ReportGenerator": ReportGenerator,
        }[name]
    raise AttributeError(name)
