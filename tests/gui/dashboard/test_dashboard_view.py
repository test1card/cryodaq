"""Smoke tests for DashboardView skeleton (Phase UI-1 v2 Block B.1)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import UTC

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFrame, QScrollArea

from cryodaq.core.channel_manager import ChannelManager
from cryodaq.gui.dashboard import DashboardView
from cryodaq.gui.dashboard.dashboard_view import _PRESENTATION_INTERVAL_MS


@pytest.fixture(scope="module")
def app():
    qapp = QApplication.instance() or QApplication([])
    yield qapp


def test_dashboard_view_constructs(app):
    """DashboardView instantiates without error."""
    mgr = ChannelManager()
    view = DashboardView(mgr)
    assert view is not None


def test_dashboard_connection_contract_disables_mutations_until_live_and_after_loss(app):
    view = DashboardView(ChannelManager())

    assert not view._connected
    assert not view._phase_widget._create_btn.isEnabled()
    assert not view._quick_log._send_btn.isEnabled()

    view.set_connected(True)
    view.set_authority_receipt(
        experiment_id=None,
        producer_id="engine-test",
        revision=1,
    )
    assert view._phase_widget._create_btn.isEnabled()
    assert view._quick_log._send_btn.isEnabled()

    view.set_connected(False)
    assert not view._phase_widget._create_btn.isEnabled()
    assert not view._quick_log._send_btn.isEnabled()


def test_dashboard_presentation_tick_is_bounded_to_two_hz(app):
    mgr = ChannelManager()
    view = DashboardView(mgr)

    assert _PRESENTATION_INTERVAL_MS == 500
    assert view._refresh_timer.interval() == _PRESENTATION_INTERVAL_MS


def test_dashboard_view_has_five_zones(app):
    """All five placeholder zones are present with expected object names."""
    mgr = ChannelManager()
    view = DashboardView(mgr)
    expected = {"phaseZone", "tempPlotZone", "pressurePlotZone", "sensorGridZone", "quickLogZone"}
    actual = {c.objectName() for c in view.findChildren(QFrame) if c.objectName() in expected}
    assert expected == actual, f"Missing: {expected - actual}"


def test_dashboard_scrolls_vertically_without_horizontal_clipping_or_sensor_hiding(app):
    mgr = ChannelManager()
    mgr._channels = {f"Т{index}": {"name": f"Датчик {index}", "visible": True} for index in range(1, 13)}
    view = DashboardView(mgr)
    view.resize(720, 360)
    view.show()
    app.processEvents()

    assert isinstance(view, QScrollArea)
    assert view.accessibleName() == "Панель мониторинга"
    assert view.focusPolicy() is Qt.FocusPolicy.StrongFocus
    assert view.horizontalScrollBarPolicy() is Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert view.horizontalScrollBar().maximum() == 0
    assert view.verticalScrollBar().maximum() > 0
    assert tuple(view._sensor_grid._cells) == tuple(f"Т{index}" for index in range(1, 13))
    assert view._sensor_grid._grid_layout.count() == 12
    assert view._sensor_grid.height() >= view._sensor_grid.minimumSizeHint().height()
    assert view._sensor_grid._grid_widget.geometry().bottom() <= view._sensor_grid.contentsRect().bottom()


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


def test_coalescing_preserves_every_sample_in_full_rate_buffer(app):
    from datetime import datetime

    from cryodaq.drivers.base import ChannelStatus, Reading
    from cryodaq.gui.state.descriptor_store import IdentityStatus

    mgr = ChannelManager()
    view = DashboardView(mgr)
    for value, status in (
        (77.0, ChannelStatus.OK),
        (500.0, ChannelStatus.OVERRANGE),
        (78.0, ChannelStatus.OK),
    ):
        view.on_reading(
            Reading(
                channel="\u04221 \u041a\u0440\u0438\u043e\u0441\u0442\u0430\u0442 \u0432\u0435\u0440\u0445",
                value=value,
                unit="K",
                timestamp=datetime.now(UTC),
                status=status,
                instrument_id="lakeshore_218s",
            ),
            IdentityStatus.AUTHORITATIVE,
        )

    assert [value for _, value in view._buffer_store.get_history("\u04221")] == [
        77.0,
        500.0,
        78.0,
    ]
    assert view._sensor_grid is not None
    pending = view._sensor_grid._pending_readings["\u04221"]
    assert pending.count == 3
    assert pending.minimum[0].value == 77.0
    assert pending.maximum[0].value == 500.0
    assert pending.last[0].value == 78.0
    assert pending.status_evidence[0].status is ChannelStatus.OVERRANGE

    view._refresh_plots()

    assert view._temp_plot is not None
    plotted = view._temp_plot._plot_items["\u04221"]
    assert list(plotted.yData) == [77.0, 500.0, 78.0]
    cell = view._sensor_grid._cells["\u04221"]
    assert cell._value_widget.text() == "78.00"
    assert cell._status_hint_widget.text() == "Перегрузка (за интервал)"

    view._sensor_grid.refresh()

    assert cell._status_hint_widget.text() == "Норма"


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


def test_dashboard_replay_direct_config_signals_fail_closed(app, monkeypatch):
    """Queued/direct grid signals cannot rename or hide channels in replay."""
    mgr = ChannelManager()
    mgr._channels = {"Т1": {"name": "Исходное", "visible": True}}
    saved: list[bool] = []
    monkeypatch.setattr(mgr, "save", lambda: saved.append(True))
    view = DashboardView(mgr)
    view.set_read_only(True)

    view._sensor_grid.rename_requested.emit("Т1", "Запрещено")
    view._sensor_grid.hide_requested.emit("Т1")
    app.processEvents()

    assert mgr.get_name("Т1") == "Исходное"
    assert mgr.is_visible("Т1") is True
    assert saved == []


def test_dashboard_live_config_signals_still_persist(app, monkeypatch):
    """The replay gate does not regress the live rename/hide contract."""
    mgr = ChannelManager()
    mgr._channels = {"Т1": {"name": "Исходное", "visible": True}}
    saved: list[bool] = []
    monkeypatch.setattr(mgr, "save", lambda: saved.append(True))
    view = DashboardView(mgr)
    view.set_connected(True)
    view.set_authority_receipt(
        experiment_id=None,
        producer_id="engine-test",
        revision=1,
    )

    view._sensor_grid.rename_requested.emit("Т1", "Новое")
    view._sensor_grid.hide_requested.emit("Т1")
    app.processEvents()

    assert mgr.get_name("Т1") == "Новое"
    assert mgr.is_visible("Т1") is False
    assert saved == [True, True]
