"""Smoke tests for DashboardView skeleton (Phase UI-1 v2 Block B.1)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import UTC

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
    expected = {"phaseZone", "tempPlotZone", "pressurePlotZone", "sensorGridZone", "quickLogZone"}
    actual = {c.objectName() for c in view.findChildren(QFrame) if c.objectName() in expected}
    assert expected == actual, f"Missing: {expected - actual}"


def test_dashboard_view_on_reading_accepts(app):
    """on_reading() accepts a reading without raising."""
    from datetime import datetime

    from cryodaq.drivers.base import ChannelStatus, Reading

    mgr = ChannelManager()
    view = DashboardView(mgr)
    reading = Reading(
        channel="\u04221 \u041a\u0440\u0438\u043e\u0441\u0442\u0430\u0442 \u0432\u0435\u0440\u0445",
        value=4.2,
        unit="K",
        timestamp=datetime.now(UTC),
        status=ChannelStatus.OK,
        instrument_id="lakeshore_218s",
    )
    view.on_reading(reading)  # should not raise


def test_on_reading_temperature_stores_short_id(app):
    """Temperature reading stored under short ID (Т1) in buffer."""
    from datetime import datetime

    from cryodaq.drivers.base import ChannelStatus, Reading

    mgr = ChannelManager()
    view = DashboardView(mgr)
    reading = Reading(
        channel="\u04221 \u041a\u0440\u0438\u043e\u0441\u0442\u0430\u0442 \u0432\u0435\u0440\u0445",
        value=77.5,
        unit="K",
        timestamp=datetime.now(UTC),
        status=ChannelStatus.OK,
        instrument_id="lakeshore_218s",
    )
    view.on_reading(reading)
    last = view._buffer_store.get_last("\u04221")
    assert last is not None
    assert last[1] == 77.5


def test_on_reading_pressure_stores_full_id(app):
    """Pressure reading stored under full channel ID."""
    from datetime import datetime

    from cryodaq.drivers.base import ChannelStatus, Reading

    mgr = ChannelManager()
    view = DashboardView(mgr)
    reading = Reading(
        channel="VSP63D_1/pressure",
        value=1e-4,
        unit="mbar",
        timestamp=datetime.now(UTC),
        status=ChannelStatus.OK,
        instrument_id="thyracont_vsp63d",
    )
    view.on_reading(reading)
    last = view._buffer_store.get_last("VSP63D_1/pressure")
    assert last is not None
    assert last[1] == 1e-4
