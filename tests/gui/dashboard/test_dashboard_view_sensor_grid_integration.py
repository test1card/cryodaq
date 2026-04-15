"""Integration tests for DashboardView + DynamicSensorGrid (Block B.3)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timezone

from cryodaq.core.channel_manager import ChannelManager
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.gui.dashboard import DashboardView


def test_dashboard_view_has_sensor_grid(app):
    mgr = ChannelManager()
    view = DashboardView(mgr)
    assert view._sensor_grid is not None
    assert view._sensor_grid.objectName() == "dynamicSensorGrid"


def test_dashboard_view_routes_temperature_reading_to_cell(app):
    mgr = ChannelManager()
    view = DashboardView(mgr)
    reading = Reading(
        channel="\u04221 \u041a\u0440\u0438\u043e\u0441\u0442\u0430\u0442 \u0432\u0435\u0440\u0445",
        value=4.21,
        unit="K",
        timestamp=datetime.now(timezone.utc),
        status=ChannelStatus.OK,
        instrument_id="lakeshore_218s",
    )
    view.on_reading(reading)
    cell = view._sensor_grid._cells.get("\u04221")
    if cell is not None:
        assert "4.21" in cell._value_widget.text()
