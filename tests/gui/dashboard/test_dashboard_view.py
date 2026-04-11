"""Smoke tests for DashboardView skeleton (Phase UI-1 v2 Block B.1)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QFrame

from cryodaq.core.channel_manager import ChannelManager
from cryodaq.gui.dashboard import DashboardView


@pytest.fixture(scope="module")
def app():
    qapp = QApplication.instance() or QApplication([])
    yield qapp


def test_dashboard_view_constructs(app):
    """DashboardView instantiates without error."""
    mgr = ChannelManager()
    view = DashboardView(mgr)
    assert view is not None


def test_dashboard_view_has_five_zones(app):
    """All five placeholder zones are present with expected object names."""
    mgr = ChannelManager()
    view = DashboardView(mgr)
    expected = {"phaseZone", "tempPlotZone", "pressurePlotZone",
                "sensorGridZone", "quickLogZone"}
    actual = {
        c.objectName() for c in view.findChildren(QFrame)
        if c.objectName() in expected
    }
    assert expected == actual, f"Missing: {expected - actual}"


def test_dashboard_view_on_reading_is_noop(app):
    """on_reading() accepts a reading without raising (B.1 stub)."""
    from datetime import datetime, timezone

    from cryodaq.drivers.base import ChannelStatus, Reading

    mgr = ChannelManager()
    view = DashboardView(mgr)
    reading = Reading(
        channel="Т1",
        value=4.2,
        unit="K",
        timestamp=datetime.now(timezone.utc),
        status=ChannelStatus.OK,
        instrument_id="lakeshore_218s",
    )
    view.on_reading(reading)  # should not raise
