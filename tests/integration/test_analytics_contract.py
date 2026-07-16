"""Analytics tab structural contract tests (T8 — v0.52.6).

End-to-end coverage of the descriptor-qualified dispatch path::

    MainWindowV2.dispatch_qualified_reading(qualified)
        → _dispatch_descriptor_reading(reading, descriptor)
        → AnalyticsView.set_*(...)
        → concrete widget internal state

Existing analytics tests inject at the AnalyticsView boundary. These
tests drive the real path so the fixes for T1–T7 cannot regress without
visibly breaking a test:

- T3 (CooldownPredictionWidget): viewBox X range must not include 1970.
- T4 (cooldown future_t conversion): central trajectory timestamps must be
  absolute Unix seconds.
- T5 (PressurePlot frozen X window): X range must scroll with live data.
- T7 (append-style widget self-fetch): on construction, widgets issue a
  ``readings_history`` ZMQ command (mocked) so the new instance is not
  empty after a phase swap.
- T1 (set_fault removed + WARNING on silent setter skip): AnalyticsView
  must not expose ``set_fault`` and ``_forward`` must log when no active
  widget implements the requested setter.
- set_experiment_status: routed all the way to ExperimentSummaryWidget
  in disassembly phase.
- VacuumPredictionWidget now-line is anchored at the wall clock, not
  Unix epoch.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from cryodaq.channels.descriptors import (
    ChannelDescriptorV1,
    ChannelQuantity,
    ChannelRole,
    ChannelSafetyClass,
)
from cryodaq.core.descriptor_transport import DescriptorQualifiedReading
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.gui.shell.main_window_v2 import MainWindowV2
from cryodaq.gui.shell.views import analytics_widgets as aw
from cryodaq.gui.shell.views.analytics_view import AnalyticsView
from cryodaq.gui.state.time_window import reset_time_window_controller


@pytest.fixture(scope="session")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _reset(qt_app):
    reset_time_window_controller()
    yield
    reset_time_window_controller()


def _stop_timers(w: MainWindowV2) -> None:
    for timer in w.findChildren(QTimer):
        try:
            timer.stop()
        except RuntimeError:
            pass


def _qualified(
    reading: Reading,
    quantity: ChannelQuantity,
    *,
    display_name: str | None = None,
) -> DescriptorQualifiedReading:
    descriptor = ChannelDescriptorV1(
        schema_version=1,
        channel_id=reading.channel,
        instrument_id=reading.instrument_id,
        source_key=f"test.{quantity.value}",
        quantity=quantity,
        unit=reading.unit,
        role=ChannelRole.PRIMARY_MEASUREMENT,
        safety_class=ChannelSafetyClass.OBSERVATIONAL,
        display_group="analytics",
        display_name=display_name or reading.channel,
        visible_by_default=True,
        display_order=0,
        descriptor_revision=1,
    )
    return DescriptorQualifiedReading(reading=reading, descriptor=descriptor)


def _temperature_reading(channel: str, value: float, *, ts: float | None = None) -> Reading:
    timestamp = datetime.fromtimestamp(ts, tz=UTC) if ts is not None else datetime.now(UTC)
    return Reading(
        timestamp=timestamp,
        instrument_id="LS218_1",
        channel=channel,
        value=value,
        unit="K",
        status=ChannelStatus.OK,
        metadata={},
    )


def _pressure_reading(value: float, *, ts: float | None = None) -> Reading:
    timestamp = datetime.fromtimestamp(ts, tz=UTC) if ts is not None else datetime.now(UTC)
    return Reading(
        timestamp=timestamp,
        instrument_id="VSP63D_1",
        channel="VSP63D_1/pressure",
        value=value,
        unit="mbar",
        status=ChannelStatus.OK,
        metadata={},
    )


def _cooldown_reading(future_hours: list[float]) -> Reading:
    """Build a cooldown_predictor reading with the exact plugin payload shape."""
    n = len(future_hours)
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="cooldown_predictor",
        channel="analytics/cooldown_predictor/cooldown_eta",
        value=2.5,
        unit="h",
        status=ChannelStatus.OK,
        metadata={
            "t_remaining_hours": 2.5,
            "t_remaining_ci68": (2.0, 3.0),
            "progress": 0.4,
            "phase": "phase1",
            "future_t": future_hours,
            "future_T_cold_mean": [200.0 - 50.0 * i for i in range(n)],
            "future_T_cold_upper": [205.0 - 50.0 * i for i in range(n)],
            "future_T_cold_lower": [195.0 - 50.0 * i for i in range(n)],
        },
    )


# ──────────────────────────────────────────────────────────────────────
# T7 — Temperature panel receives data in cooldown phase via dispatch
# ──────────────────────────────────────────────────────────────────────


def test_temperature_panel_receives_data_in_cooldown_phase(qt_app):
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_cls.return_value = MagicMock()
        w = MainWindowV2()
        _stop_timers(w)
        try:
            w._ensure_overlay("analytics")
            w._on_experiment_status_received({"active_experiment": {}, "current_phase": "cooldown"})
            now = time.time()
            for i in range(5):
                reading = _temperature_reading("stage_temp", 295.0 - 5.0 * i, ts=now + i)
                w.dispatch_qualified_reading(
                    _qualified(
                        reading,
                        ChannelQuantity.TEMPERATURE,
                        display_name="Т1 Криостат верх",
                    )
                )
                qt_app.processEvents()

            # In cooldown, top_right is temperature_overview.
            slots = w._analytics_view.active_widgets()
            top_right = slots.get("top_right")
            assert isinstance(top_right, aw.TemperatureOverviewWidget)
            series = top_right._series.get("stage_temp")
            assert series is not None and len(series.xs) >= 5

            # X-axis right edge must be in the recent past, not 1970.
            pi = top_right._plot.getPlotItem()
            x_lo, x_hi = pi.getViewBox().viewRange()[0]
            assert x_hi > now - 2 * 24 * 3600, f"X-axis right edge {x_hi} is older than 2 days; expected ~now"
        finally:
            w.close()


# ──────────────────────────────────────────────────────────────────────
# T5 — Pressure panel renders, X-window scrolls with live data
# ──────────────────────────────────────────────────────────────────────


def test_pressure_panel_renders_in_vacuum_phase(qt_app):
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_cls.return_value = MagicMock()
        w = MainWindowV2()
        _stop_timers(w)
        try:
            w._ensure_overlay("analytics")
            w._on_experiment_status_received({"active_experiment": {}, "current_phase": "vacuum"})
            now = time.time()
            for i in range(5):
                reading = _pressure_reading(1e-5 * (i + 1), ts=now + i)
                w.dispatch_qualified_reading(_qualified(reading, ChannelQuantity.PRESSURE))
                qt_app.processEvents()

            # In vacuum, pressure_current is bottom_right.
            slots = w._analytics_view.active_widgets()
            pressure = slots.get("bottom_right")
            assert isinstance(pressure, aw.PressureCurrentWidget)
            assert len(pressure._series) >= 5

            # PressurePlot X range right-edge must be at "now" (T5 fix).
            pi = pressure._plot.plot_item.getPlotItem()
            _, x_hi = pi.getViewBox().viewRange()[0]
            assert x_hi >= now - 10, f"PressurePlot X right edge {x_hi} is frozen earlier than now ({now})"
        finally:
            w.close()


# ──────────────────────────────────────────────────────────────────────
# T3 + T4 — CooldownPredictionWidget: no 1970 epoch in X-axis
# ──────────────────────────────────────────────────────────────────────


def test_cooldown_widget_no_1970_epoch_in_xaxis(qt_app):
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_cls.return_value = MagicMock()
        w = MainWindowV2()
        _stop_timers(w)
        try:
            w._ensure_overlay("analytics")
            w._on_experiment_status_received({"active_experiment": {}, "current_phase": "cooldown"})
            reading = _cooldown_reading([0.5, 1.0, 1.5])
            w._reading_received.emit(reading)
            qt_app.processEvents()

            slots = w._analytics_view.active_widgets()
            cooldown_widget = slots.get("main")
            assert isinstance(cooldown_widget, aw.CooldownPredictionWidget)
            inner = cooldown_widget._inner
            # T4: predicted trajectory entries are absolute Unix seconds.
            assert inner._central, "central prediction must be populated"
            min_ts = min(t for t, _ in inner._central)
            assert min_ts > 1_500_000_000, f"Cooldown central trajectory contains pre-2017 timestamp {min_ts}"
            # T3: viewBox X range must not include the Unix epoch.
            pi = inner._plot.getPlotItem()
            x_lo, _ = pi.getViewBox().viewRange()[0]
            assert x_lo > 1e9, f"Cooldown X range starts at {x_lo} (≈ 1970)"
        finally:
            w.close()


# ──────────────────────────────────────────────────────────────────────
# T1 — set_fault removed
# ──────────────────────────────────────────────────────────────────────


def test_set_fault_not_present_on_analytics_view(qt_app):
    view = AnalyticsView()
    assert not hasattr(view, "set_fault"), "AnalyticsView must no longer expose set_fault — it was deleted in T1."


# ──────────────────────────────────────────────────────────────────────
# set_experiment_status reaches ExperimentSummaryWidget
# ──────────────────────────────────────────────────────────────────────


def test_set_experiment_status_reaches_experiment_summary_widget(qt_app):
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_cls.return_value = MagicMock()
        view = AnalyticsView()
        view.set_phase("disassembly")
        status = {
            "active_experiment": {
                "experiment_id": "exp_T8",
                "sample": "Si",
                "operator": "Тестов",
                "start_time": "2026-04-15T10:00:00+00:00",
                "end_time": "2026-04-15T20:00:00+00:00",
                "artifact_dir": "",
                "status": "COMPLETED",
            },
            "phases": [],
        }
        view.set_experiment_status(status)
        widget = view.active_widgets().get("main")
        assert isinstance(widget, aw.ExperimentSummaryWidget)
        # Populated content surface visible — id label updated.
        assert widget._id_label.text() == "exp_T8"


# ──────────────────────────────────────────────────────────────────────
# T7 — phase swap preserves accumulated series
# ──────────────────────────────────────────────────────────────────────


def test_phase_swap_preserves_series_count_in_temperature_overview(qt_app):
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_cls.return_value = MagicMock()
        view = AnalyticsView()
        # Vacuum: top_right == temperature_overview.
        view.set_phase("vacuum")
        readings_batch = {"Т1 Криостат верх": _temperature_reading("Т1 Криостат верх", 80.0)}
        for _ in range(10):
            view.set_temperature_readings(readings_batch)

        slots_before = view.active_widgets()
        temp_widget = slots_before["top_right"]
        assert isinstance(temp_widget, aw.TemperatureOverviewWidget)
        before = len(temp_widget._series.get("Т1 Криостат верх", aw._ChannelSeries()).xs)
        assert before >= 10

        # Cooldown: top_right is also temperature_overview → preserved.
        view.set_phase("cooldown")
        slots_after = view.active_widgets()
        same_widget = slots_after["top_right"]
        assert isinstance(same_widget, aw.TemperatureOverviewWidget), (
            f"Expected TemperatureOverviewWidget in top_right after phase swap to cooldown, "
            f"got {type(same_widget).__name__}"
        )
        after = len(same_widget._series.get("Т1 Криостат верх", aw._ChannelSeries()).xs)
        assert after >= before, f"Series count dropped after phase swap: before={before}, after={after}"


# ──────────────────────────────────────────────────────────────────────
# T3 — VacuumPredictionWidget now-line is not at Unix epoch
# ──────────────────────────────────────────────────────────────────────


def test_vacuum_prediction_now_marker_not_at_epoch(qt_app):
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_cls.return_value = MagicMock()
        widget = aw.VacuumPredictionWidget()
        reading = _pressure_reading(5e-6)
        widget.set_pressure_reading(reading)
        now_pos = widget._inner._now_line.value()
        assert now_pos > 1_500_000_000, (
            f"VacuumPredictionWidget now-line is at {now_pos}; must be a recent Unix timestamp, not the 1970 epoch."
        )


# ──────────────────────────────────────────────────────────────────────
# T1 — WARNING when a setter call has zero recipients
# ──────────────────────────────────────────────────────────────────────


def test_forward_warning_on_setter_with_no_recipient(qt_app, caplog):
    """Fallback layout has [TemperatureOverviewWidget, PressureCurrentWidget,
    SensorHealthSummaryWidget] — none implement set_cooldown_data. The
    forward must log a WARNING describing the dropped call."""
    view = AnalyticsView()
    view.set_phase(None)  # new contract: layout applied on first set_phase call
    # The fallback layout is now mounted; assert we have
    # active widgets but none implement set_cooldown_data.
    assert view.active_widgets()
    with caplog.at_level(logging.WARNING, logger="cryodaq.gui.shell.views.analytics_view"):
        view.set_cooldown(None)
    messages = [rec.getMessage() for rec in caplog.records]
    assert any("set_cooldown_data" in m for m in messages), f"Expected WARNING about set_cooldown_data; got: {messages}"


# ──────────────────────────────────────────────────────────────────────
# T1 — WARNING fires only ONCE per (method, phase), not per reading
# ──────────────────────────────────────────────────────────────────────


def test_forward_warning_fires_once_per_phase_not_per_reading(qt_app, caplog):
    """Calling a setter 100 times with no recipient in the active phase
    must produce exactly ONE WARNING, not 100."""
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_cls.return_value = MagicMock()
        view = AnalyticsView()
        # disassembly: only ExperimentSummaryWidget active — no temperature handler.
        view.set_phase("disassembly")
        assert view.active_widgets()
        with caplog.at_level(logging.WARNING, logger="cryodaq.gui.shell.views.analytics_view"):
            reading = _temperature_reading("Т1 Криостат верх", 80.0)
            for _ in range(100):
                view.set_temperature_readings({"Т1 Криостат верх": reading})
    temp_warnings = [r for r in caplog.records if "set_temperature_readings" in r.getMessage()]
    assert len(temp_warnings) == 1, f"Expected exactly 1 WARNING for set_temperature_readings; got {len(temp_warnings)}"


# ──────────────────────────────────────────────────────────────────────
# T7 — append-style widgets issue readings_history on construction
# ──────────────────────────────────────────────────────────────────────


def test_temperature_overview_widget_issues_readings_history_on_construction(qt_app):
    """TemperatureOverviewWidget must call ZmqCommandWorker with
    cmd='readings_history' during __init__ so it can backfill history
    after a phase swap."""
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        instance = MagicMock()
        mock_cls.return_value = instance
        _widget = aw.TemperatureOverviewWidget()
    # At least one ZmqCommandWorker was constructed.
    assert mock_cls.called, "ZmqCommandWorker was never instantiated"
    # The first call must have been for readings_history.
    call_args = mock_cls.call_args_list[0]
    cmd_dict = call_args[0][0] if call_args[0] else call_args[1].get("cmd_dict", {})
    assert cmd_dict.get("cmd") == "readings_history", (
        f"Expected first ZmqCommandWorker call to be readings_history; got {cmd_dict}"
    )
    # The worker's finished signal must have been connected and start() called.
    instance.finished.connect.assert_called_once()
    instance.start.assert_called_once()


def test_pressure_current_widget_issues_readings_history_on_construction(qt_app):
    """PressureCurrentWidget must call ZmqCommandWorker with
    cmd='readings_history' during __init__."""
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        instance = MagicMock()
        mock_cls.return_value = instance
        _widget = aw.PressureCurrentWidget()
    assert mock_cls.called, "ZmqCommandWorker was never instantiated"
    call_args = mock_cls.call_args_list[0]
    cmd_dict = call_args[0][0] if call_args[0] else call_args[1].get("cmd_dict", {})
    assert cmd_dict.get("cmd") == "readings_history", (
        f"Expected first ZmqCommandWorker call to be readings_history; got {cmd_dict}"
    )
    instance.finished.connect.assert_called_once()
    instance.start.assert_called_once()


# ──────────────────────────────────────────────────────────────────────
# v0.52.7 regression — lazy-open crash: no double construction
# ──────────────────────────────────────────────────────────────────────


def test_lazy_open_with_active_experiment_does_not_construct_then_destroy(qt_app, monkeypatch):
    """v0.52.7 regression: clicking Analytics during vacuum/cooldown/etc
    used to construct fallback widgets then immediately destroy them via
    set_phase, killing in-flight ZmqCommandWorkers parented to the
    destroyed widgets.

    With the structural fix, AnalyticsView's first set_phase call applies
    the active phase layout directly — no fallback widgets built only to
    be torn down immediately.
    """
    from collections import Counter

    constructed_widget_ids: list[str] = []
    original_create = aw.create

    def tracking_create(widget_id: str):
        constructed_widget_ids.append(widget_id)
        return original_create(widget_id)

    monkeypatch.setattr(aw, "create", tracking_create)

    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_cls.return_value = MagicMock()
        w = MainWindowV2()
        _stop_timers(w)
        try:
            w._latest_experiment_status = {
                "current_phase": "vacuum",
                "active_experiment": {"experiment_id": "test_v0.52.7"},
            }
            w._ensure_overlay("analytics")
            qt_app.processEvents()
        finally:
            w.close()

    counts = Counter(constructed_widget_ids)
    # Each widget constructed at most once — no fallback-then-phase double construction.
    assert all(n == 1 for n in counts.values()), (
        f"Some widgets constructed more than once — fallback-then-phase race: {counts}"
    )
    # sensor_health_summary only lives in fallback and preparation; must NOT
    # appear when active phase is vacuum.
    assert "sensor_health_summary" not in counts, (
        "sensor_health_summary was constructed — fallback was applied before vacuum phase"
    )


def test_lazy_open_without_active_experiment_uses_fallback(qt_app):
    """When no active experiment, _ensure_overlay must apply fallback layout
    (temperature_overview, pressure_current, sensor_health_summary)."""
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_cls.return_value = MagicMock()
        w = MainWindowV2()
        _stop_timers(w)
        try:
            # Default: _latest_experiment_status is None
            assert w._latest_experiment_status is None
            w._ensure_overlay("analytics")
            qt_app.processEvents()
            view = w._analytics_view
            assert view is not None
            active = view.active_widgets()
            widget_types = {type(widget).__name__ for widget in active.values()}
            assert "TemperatureOverviewWidget" in widget_types
            assert "PressureCurrentWidget" in widget_types
            assert "SensorHealthSummaryWidget" in widget_types
        finally:
            w.close()
