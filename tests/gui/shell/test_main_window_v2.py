"""Smoke tests for MainWindowV2 (Phase UI-1 v2 Block A)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.core.descriptor_transport import DescriptorQualifiedReading
from cryodaq.drivers.base import Reading
from cryodaq.gui.shell.main_window_v2 import MainWindowV2
from cryodaq.gui.shell.operator_components import NavigationIntent
from cryodaq.gui.shell.views.operator_display import OperatorDisplay


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _stop_timers(w: MainWindowV2) -> None:
    """Stop every QTimer in the window subtree.

    The default Qt cleanup is async and the test fixture would otherwise
    leave periodic timers (TopWatchBar 1 s, AlarmPanel 3 s,
    ExperimentStatusWidget 5 s) firing into subsequent tests, where they
    spawn workers that hit later monkeypatched ``send_command``.
    """
    from PySide6.QtCore import QTimer

    for timer in w.findChildren(QTimer):
        try:
            timer.stop()
        except RuntimeError:
            pass


def test_main_window_v2_constructs_with_shell_components() -> None:
    _app()
    w = MainWindowV2()
    _stop_timers(w)
    assert w._top_bar is not None
    assert w._tool_rail is not None
    assert w._bottom_bar is not None
    assert w._overlay is not None
    assert w._overlay.current_overlay == "home"
    assert w._overlay.currentWidget() is w._overview_panel
    assert isinstance(w._operator_display, OperatorDisplay)
    assert not w._top_bar.isHidden()
    assert not w._bottom_bar.isHidden()
    assert w.windowTitle() == "CryoDAQ"


def test_main_window_cold_start_qualified_reading_buffered_before_status_tick() -> None:
    """Dashboard ingress opens when a current reading passes qualified ingress,
    without waiting for the composition root's first status tick."""
    _app()
    window = MainWindowV2()
    _stop_timers(window)

    window.dispatch_qualified_reading(
        DescriptorQualifiedReading(
            reading=Reading.now(
                channel="Т1",
                value=8.8,
                unit="K",
                instrument_id="test_inst",
            ),
            descriptor=None,
        )
    )
    window._overview_panel._sensor_grid.refresh()

    assert window._overview_panel._connection_generation == 2
    assert window._overview_panel._connected is True
    assert window._overview_panel._buffer_store.get_last("Т1") is not None
    assert window._overview_panel._buffer_store.get_last("Т1")[1] == 8.8
    cell = window._overview_panel._sensor_grid._cells["Т1"]
    assert cell._value_widget.text() == "8.80"
    assert "dashed" not in cell.styleSheet()


def test_successor_reading_opens_dashboard_ingress_before_status_tick() -> None:
    """A current-incarnation reading is buffered immediately after a bridge cut,
    while a retired bridge incarnation's reading is still rejected."""
    _app()
    window = MainWindowV2()
    _stop_timers(window)

    class _FakeBridge:
        def __init__(self, instance_id: str) -> None:
            self.bridge_instance_id = instance_id

    old_id = "a" * 32
    new_id = "b" * 32
    window._bridge = _FakeBridge(old_id)

    def bound(value: float, bridge_id: str) -> DescriptorQualifiedReading:
        return DescriptorQualifiedReading(
            reading=Reading.now(
                channel="Т1",
                value=value,
                unit="K",
                instrument_id="test_inst",
                metadata={"bridge_instance_id": bridge_id},
            ),
            descriptor=None,
        )

    window.dispatch_qualified_reading(bound(1.0, old_id))
    window._overview_panel._sensor_grid.refresh()
    assert window._overview_panel._connected is True
    assert window._overview_panel._buffer_store.get_last("Т1")[1] == 1.0

    window.invalidate_descriptor_transport()
    assert window._overview_panel._connected is False

    window.dispatch_qualified_reading(bound(2.0, old_id))
    window._overview_panel._sensor_grid.refresh()
    assert window._overview_panel._connected is False
    assert window._overview_panel._buffer_store.get_last("Т1")[1] == 1.0

    window._bridge.bridge_instance_id = new_id
    window.dispatch_qualified_reading(bound(3.0, new_id))
    window._overview_panel._sensor_grid.refresh()
    assert window._overview_panel._connected is True
    assert window._overview_panel._buffer_store.get_last("Т1")[1] == 3.0


def test_bridge_and_engine_retirement_reach_top_watch_live_authority_once() -> None:
    """Every bridge cut retires TopWatch, without a double engine increment."""
    from cryodaq.gui import theme

    _app()
    window = MainWindowV2()
    _stop_timers(window)
    window._top_bar.set_engine_state(True)
    generation = window._top_bar._live_status_generation

    window.invalidate_descriptor_transport()

    assert window._top_bar._live_status_generation == generation + 1
    assert window._top_bar._engine_alive is False
    assert theme.STATUS_CAUTION in window._top_bar._exp_label.styleSheet()

    window._top_bar.set_engine_state(True)
    window.invalidate_engine_producer()

    assert window._top_bar._live_status_generation == generation + 2
    assert window._top_bar._engine_alive is False
    assert theme.STATUS_CAUTION in window._top_bar._exp_label.styleSheet()


@pytest.mark.parametrize(
    "failed_names",
    [
        ("descriptor",),
        ("descriptor", "top"),
    ],
)
def test_engine_retirement_attempts_every_authority_cut_after_failures(
    monkeypatch,
    failed_names: tuple[str, ...],
) -> None:
    """One passive invalidator cannot prevent independent authority cuts."""
    _app()
    window = MainWindowV2()
    _stop_timers(window)
    events: list[str] = []
    failures = {name: RuntimeError(f"{name} failed") for name in failed_names}

    def action(name: str):
        def run() -> None:
            events.append(name)
            failure = failures.get(name)
            if failure is not None:
                raise failure

        return run

    monkeypatch.setattr(window._descriptor_store, "invalidate_transport", action("descriptor"))
    monkeypatch.setattr(window._annunciation_controller, "invalidate_transport", action("annunciation"))
    monkeypatch.setattr(window._top_bar, "invalidate_engine_producer", action("top"))
    monkeypatch.setattr(window._overview_panel, "invalidate_operator_snapshot_producer", action("overview"))

    with pytest.raises(Exception) as captured:
        window.invalidate_engine_producer()

    assert events == ["descriptor", "annunciation", "top", "overview"]
    if len(failed_names) == 1:
        assert captured.value is failures[failed_names[0]]
    else:
        assert isinstance(captured.value, ExceptionGroup)
        assert captured.value.exceptions == tuple(failures[name] for name in failed_names)


def test_operator_display_is_fail_closed_home_and_routes_to_drill_down(monkeypatch) -> None:
    _app()
    w = MainWindowV2()
    _stop_timers(w)

    assert w._operator_display.snapshot is None
    assert w._operator_display.accessibleName() == "Сводка смены"
    assert "недоступны" in w._operator_display.accessibleDescription()

    accepted = []
    monkeypatch.setattr(w._operator_display, "render", accepted.append)
    snapshot = object()
    w.render_operator_snapshot(snapshot)
    assert accepted == [snapshot]

    typed: list[NavigationIntent] = []
    w._operator_display.navigation_requested.connect(typed.append)
    w._operator_display._forward_navigation(w._operator_display.next_action.intent)
    assert typed == [w._operator_display.next_action.intent]
    assert isinstance(typed[0], NavigationIntent)

    w._operator_display.route_requested.emit("alarms")
    assert w._overlay.currentWidget() is w._alarm_panel
    assert w._tool_rail._buttons["alarms"]._active is True
    assert not w._top_bar.isHidden()
    assert not w._bottom_bar.isHidden()

    w._on_tool_clicked("summary")
    assert w._overlay.currentWidget() is w._operator_display
    assert w._overlay.current_overlay == "summary"
    assert w._tool_rail._buttons["more"]._active is True


def test_tool_rail_click_switches_overlay() -> None:
    _app()
    w = MainWindowV2()
    _stop_timers(w)
    # "alarms" is eagerly registered (it feeds the watch bar count), so
    # opening it doesn't trigger lazy construction of any other panel.
    # Drive via the real ToolRail button click so tool_clicked signal fires.
    w._tool_rail._buttons["alarms"].click()
    assert w._overlay.currentWidget() is w._alarm_panel
    assert w._overlay.current_overlay == "alarms"
    assert w._tool_rail._buttons["alarms"]._active is True
    w._tool_rail._buttons["home"].click()
    assert w._overlay.currentWidget() is w._overview_panel
    assert w._overlay.current_overlay == "home"
    assert w._tool_rail._buttons["home"]._active is True
    assert not w._top_bar.isHidden()
    assert not w._bottom_bar.isHidden()


def _active_experiment_status_for_retirement() -> dict:
    experiment_id = "a" * 12
    return {
        "ok": True,
        "app_mode": "experiment",
        "active_experiment": {
            "experiment_id": experiment_id,
            "name": "outgoing experiment",
            "title": "Outgoing experiment",
            "template_id": "template-1",
            "operator": "",
            "cryostat": "",
            "sample": "",
            "description": "",
            "notes": "",
            "start_time": "2026-07-23T00:00:00+00:00",
            "end_time": None,
            "status": "RUNNING",
            "config_snapshot": {},
            "custom_fields": {},
            "report_enabled": True,
            "sections": [],
            "artifact_dir": "",
            "metadata_path": "",
            "retroactive": False,
        },
        "current_phase": "preparation",
        "phase_started_at": 0.0,
        "phases": [
            {
                "phase": "preparation",
                "started_at": "2026-07-23T00:00:00+00:00",
                "ended_at": None,
                "operator": "",
            }
        ],
        "run_records": [],
        "templates": [{"id": "template-1", "name": "Template 1"}],
    }


def _populate_real_experiment_consumers(window: MainWindowV2) -> dict:
    status = _active_experiment_status_for_retirement()
    window._on_experiment_status_received(status)
    for name in ("experiment", "log", "analytics"):
        window._ensure_overlay(name)
    assert window._experiment_overlay is not None
    assert window._operator_log_panel is not None
    assert window._analytics_view is not None
    return status


def test_bridge_retirement_disconnects_every_experiment_consumer(monkeypatch) -> None:
    """Bridge authority retirement keeps the overlay card as last-known and disconnects it."""
    _app()
    window = MainWindowV2()
    _stop_timers(window)
    status = _populate_real_experiment_consumers(window)
    experiment_id = status["active_experiment"]["experiment_id"]
    monkeypatch.setattr(window, "_current_bridge_instance_id", lambda: "bridge-a")
    window._typed_safety_authority_seen = True
    window._typed_safety_ready = True
    window._accepted_safety_bridge_instance_id = "bridge-a"
    window._accepted_safety_experiment_id = experiment_id

    assert window._latest_experiment_status is status
    assert window._overview_panel._phase_widget.active_experiment_id == experiment_id
    assert window._experiment_overlay._experiment is not None
    assert window._experiment_overlay._templates_by_id
    assert window._operator_log_panel._current_experiment_id == experiment_id
    assert window._analytics_view.current_phase() == "preparation"
    assert window._analytics_view._last_experiment_status is status
    assert window._current_keithley_safety_gate()[0] is True

    window.invalidate_descriptor_transport()

    assert window._latest_experiment_status is None
    assert window._analytics_last_exp_id is None
    assert "set_experiment_status" not in window._analytics_snapshot
    assert window._overview_panel._phase_widget.active_experiment_id is None
    operation_label = window._overview_panel._phase_widget._operation_label
    assert not operation_label.isHidden()
    assert operation_label.text()
    assert operation_label.accessibleDescription()
    assert window._experiment_overlay._experiment is not None
    assert window._experiment_overlay._phase_history
    assert set(window._experiment_overlay._templates_by_id) == {"template-1"}
    assert window._experiment_overlay._connected is False
    assert window._operator_log_panel._current_experiment_id is None
    assert window._operator_log_panel._bind_experiment_check.isChecked() is False
    assert window._analytics_view._last_experiment_status is None
    assert window._analytics_view.current_phase() == "preparation"
    assert window._typed_safety_ready is False
    assert window._accepted_safety_bridge_instance_id is None
    assert window._accepted_safety_experiment_id is None
    assert window._current_keithley_safety_gate()[0] is False


def test_experiment_truth_retirement_attempts_siblings_after_renderer_failure(monkeypatch) -> None:
    """One failed renderer cannot leave independent experiment consumers current."""
    _app()
    window = MainWindowV2()
    _stop_timers(window)
    _populate_real_experiment_consumers(window)
    failure = RuntimeError("overview experiment retirement failed")
    top_generation = window._top_bar._live_status_generation

    def fail_overview(_status: dict) -> None:
        raise failure

    monkeypatch.setattr(window._overview_panel, "on_experiment_status", fail_overview)
    window._typed_safety_authority_seen = True
    window._typed_safety_ready = True
    window._accepted_safety_bridge_instance_id = "bridge-a"
    window._accepted_safety_experiment_id = "a" * 12

    with pytest.raises(RuntimeError, match="overview experiment retirement failed") as captured:
        window.invalidate_descriptor_transport()

    assert captured.value is failure
    assert window._latest_experiment_status is None
    assert window._typed_safety_ready is False
    assert window._experiment_overlay._experiment is not None
    assert set(window._experiment_overlay._templates_by_id) == {"template-1"}
    assert window._operator_log_panel._current_experiment_id is None
    assert window._analytics_view._last_experiment_status is None
    assert window._analytics_view.current_phase() == "preparation"
    assert "set_experiment_status" not in window._analytics_snapshot
    assert window._top_bar._live_status_generation == top_generation + 1


def test_bridge_retirement_clears_outgoing_freshness_before_next_status_tick(monkeypatch) -> None:
    """A retired reading timestamp cannot reconnect the dashboard on the next tick."""
    import cryodaq.gui.shell.main_window_v2 as main_window_module

    _app()
    window = MainWindowV2()
    _stop_timers(window)
    monkeypatch.setattr(main_window_module.time, "monotonic", lambda: 100.0)
    window._last_reading_time = 99.0
    window._top_bar.set_engine_state(True)
    window._overview_panel._connected = True
    window._overview_panel._connection_generation = 1

    window.invalidate_descriptor_transport()
    window._tick_status()

    assert window._last_reading_time == 0.0
    assert window._top_bar._engine_alive is False
    assert window._overview_panel._connected is False


def test_bridge_retirement_clears_outgoing_freshness_before_lazy_overlay(monkeypatch) -> None:
    """Lazy panels opened after a cut cannot inherit outgoing connectivity."""
    import cryodaq.gui.shell.main_window_v2 as main_window_module

    _app()
    window = MainWindowV2()
    _stop_timers(window)
    monkeypatch.setattr(main_window_module.time, "monotonic", lambda: 100.0)
    window._last_reading_time = 99.0

    window.invalidate_descriptor_transport()
    window._ensure_overlay("experiment")
    window._ensure_overlay("log")
    _stop_timers(window)

    assert window._experiment_overlay is not None
    assert window._operator_log_panel is not None
    assert window._experiment_overlay._connected is False
    assert window._operator_log_panel._connected is False


def test_successor_experiment_status_refreshes_template_truth() -> None:
    """A new accepted status updates every experiment overlay field."""
    _app()
    window = MainWindowV2()
    _stop_timers(window)
    outgoing = _active_experiment_status_for_retirement()
    window._on_experiment_status_received(outgoing)
    window._ensure_overlay("experiment")
    assert window._experiment_overlay is not None
    assert set(window._experiment_overlay._templates_by_id) == {"template-1"}

    window.invalidate_descriptor_transport()
    assert set(window._experiment_overlay._templates_by_id) == {"template-1"}

    successor = _active_experiment_status_for_retirement()
    successor["active_experiment"]["experiment_id"] = "b" * 12
    successor["active_experiment"]["template_id"] = "template-2"
    successor["templates"] = [{"id": "template-2", "name": "Template 2"}]
    window._on_experiment_status_received(successor)

    assert set(window._experiment_overlay._templates_by_id) == {"template-2"}
    assert window._experiment_overlay._experiment["experiment_id"] == "b" * 12


def test_bridge_retirement_preserves_unsaved_experiment_card_edits(monkeypatch) -> None:
    """A transport cut keeps the overlay card and its unsaved edits; only a
    successor no-experiment status clears the card."""
    _app()
    window = MainWindowV2()
    _stop_timers(window)
    status = _active_experiment_status_for_retirement()
    window._on_experiment_status_received(status)
    window._ensure_overlay("experiment")
    overlay = window._experiment_overlay
    assert overlay is not None
    monkeypatch.setattr(overlay, "_reload_timeline", lambda: None)
    overlay.set_connected(True)
    overlay._sample_edit.setText("unsaved local sample")
    overlay._mark_card_dirty()
    assert overlay._card_dirty is True
    assert overlay._save_btn.isEnabled() is True

    window.invalidate_descriptor_transport()

    assert overlay._connected is False
    assert overlay._experiment is not None
    assert overlay._sample_edit.text() == "unsaved local sample"
    assert overlay._card_dirty is True
    assert overlay._save_btn.isEnabled() is False

    window._on_experiment_status_received(status)
    assert overlay._experiment is not None
    assert overlay._sample_edit.text() == "unsaved local sample"

    no_exp = dict(status)
    no_exp["active_experiment"] = None
    window._on_experiment_status_received(no_exp)
    assert overlay._experiment is None


def test_bridge_retirement_does_not_swap_analytics_layout() -> None:
    """Connectivity loss must not change the analytics phase layout, so
    phase-owned widgets (and their in-flight workers) are not deleted."""
    from cryodaq.gui.shell.views import analytics_widgets

    _app()
    window = MainWindowV2()
    _stop_timers(window)
    window._ensure_overlay("analytics")
    view = window._analytics_view
    assert view is not None
    window._on_experiment_status_received({"active_experiment": {}, "current_phase": "vacuum"})
    assert view.current_phase() == "vacuum"
    assert analytics_widgets.id_of(view._active["main"]) == "vacuum_prediction"
    vacuum_widget = view._active["main"]

    window.invalidate_descriptor_transport()

    assert view.current_phase() == "vacuum"
    assert analytics_widgets.id_of(view._active["main"]) == "vacuum_prediction"
    assert view._active["main"] is vacuum_widget


def test_bridge_retirement_synchronously_disconnects_every_instantiated_panel() -> None:
    """The bridge cut reaches every real connection-gated panel before a timer tick."""
    _app()
    window = MainWindowV2()
    _stop_timers(window)
    for route in (
        "source",
        "conductivity",
        "multiline",
        "knowledge_base",
        "log",
        "instruments",
        "archive",
        "calibration",
        "experiment",
    ):
        window._ensure_overlay(route)
    _stop_timers(window)

    panels = {
        "dashboard": window._overview_panel,
        "alarms": window._alarm_panel,
        "source": window._keithley_panel,
        "conductivity": window._conductivity_panel,
        "multiline": window._multiline_panel,
        "knowledge_base": window._knowledge_base_panel,
        "log": window._operator_log_panel,
        "instruments": window._instrument_panel,
        "archive": window._archive_panel,
        "calibration": window._calibration_panel,
        "experiment": window._experiment_overlay,
    }
    assert all(panel is not None for panel in panels.values())
    for panel in panels.values():
        panel.set_connected(True)
    _stop_timers(window)
    alarm_generation = window._alarm_panel._connection_generation
    dashboard_generation = window._overview_panel._connection_generation
    assert all(panel._connected is True for panel in panels.values())

    window.invalidate_descriptor_transport()

    assert all(panel._connected is False for panel in panels.values()), {
        name: panel._connected for name, panel in panels.items()
    }
    assert window._alarm_panel._connection_generation > alarm_generation
    assert window._overview_panel._connection_generation > dashboard_generation


def test_bridge_retirement_synchronously_marks_bottom_bar_disconnected() -> None:
    """Shell chrome must stop claiming live connection or current disk truth at the cut."""
    from datetime import UTC, datetime

    _app()
    window = MainWindowV2()
    _stop_timers(window)
    window._bottom_bar.set_connected(True, "Подключено")
    window._bottom_bar.set_data_rate(3.0)
    assert window._bottom_bar.set_disk_evidence(20.0, source="disk_monitor", state="ok")
    window._accepted_disk_bridge_instance_id = "a" * 32
    window._last_disk_observed_at = datetime.now(UTC)
    assert window._bottom_bar._conn_label.text() == "● Подключено"
    assert window._bottom_bar._rate_label.text() == "3 изм/с"
    assert window._bottom_bar._disk_label.text() == "Диск 20.0 ГБ"

    window.invalidate_descriptor_transport()

    assert window._bottom_bar._rate_label.text() == "~3 изм/с"
    assert "текущая входящая скорость недействительна" in window._bottom_bar._rate_label.accessibleDescription()
    assert window._bottom_bar._conn_label.text() == "● Engine потерян"
    assert "Состояние связи: Engine потерян" in window._bottom_bar._conn_label.accessibleDescription()
    assert window._bottom_bar._disk_label.text() == "Диск ~20.0 ГБ · нет связи"
    assert window._accepted_disk_bridge_instance_id is None
    assert window._last_disk_observed_at is None


def test_status_tick_restores_knowledge_base_connection_after_bridge_cut() -> None:
    """A current successor data flow re-enables RAG only through host authority."""
    import time

    _app()
    window = MainWindowV2()
    _stop_timers(window)
    window._ensure_overlay("knowledge_base")
    panel = window._knowledge_base_panel
    assert panel is not None
    panel.set_connected(True)
    window.invalidate_descriptor_transport()
    assert panel._connected is False

    window._last_reading_time = time.monotonic()
    window._tick_status()

    assert panel._connected is True
