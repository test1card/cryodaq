"""SeverityChip acknowledged styling — v0.55.2 A1 (visual habituation guard).

Architect-flagged: backend kept the alarm in `_active` until the physical
condition cleared (correct), but the GUI rendered acknowledged alarms
identically to fresh ones. Operator habituation = safety regression.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from cryodaq.gui import theme
from cryodaq.gui.shell.overlays.alarm_panel import SeverityChip


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_severity_chip_fresh_uses_status_token() -> None:
    _app()
    chip = SeverityChip("CRITICAL")
    assert chip.text() == "КРИТ"
    assert theme.STATUS_FAULT in chip.styleSheet()


def test_severity_chip_acknowledged_uses_muted_palette() -> None:
    _app()
    chip = SeverityChip("CRITICAL", acknowledged=True)
    assert chip.text().startswith("✓")
    qss = chip.styleSheet()
    assert theme.SURFACE_MUTED in qss
    assert theme.MUTED_FOREGROUND in qss
    assert theme.STATUS_FAULT not in qss


def test_severity_chip_acknowledged_warning_too() -> None:
    _app()
    chip = SeverityChip("WARNING", acknowledged=True)
    qss = chip.styleSheet()
    assert theme.STATUS_WARNING not in qss
    assert theme.SURFACE_MUTED in qss
