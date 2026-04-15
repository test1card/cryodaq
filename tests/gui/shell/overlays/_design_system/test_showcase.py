from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.gui.shell.overlays._design_system import (
    BentoGrid,
    DrillDownBreadcrumb,
    ModalCard,
)
from cryodaq.gui.shell.overlays._design_system._showcase import build_showcase


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def test_showcase_builds_all_phase_i1_primitives(app):
    window = build_showcase()
    window.show()
    app.processEvents()

    assert window.windowTitle() == "CryoDAQ Overlay Design System Showcase"
    assert window.findChild(ModalCard) is not None
    assert window.findChild(DrillDownBreadcrumb) is not None
    assert window.findChild(BentoGrid) is not None
