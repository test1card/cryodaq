"""Dashboard re-export of the global :class:`TimeWindow` enum.

Original location moved to :mod:`cryodaq.gui.state.time_window` in
Phase III.B (one-source-of-truth controller). This shim preserves
existing import paths while repo consumers migrate to the canonical
module.
"""

from cryodaq.gui.state.time_window import TimeWindow

__all__ = ["TimeWindow"]
