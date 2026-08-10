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


def test_main_window_cold_start_quarantines_qualified_reading_before_status_tick() -> None:
    """The composition root closes dashboard ingress before its first status tick."""
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

    assert window._overview_panel._connection_generation == 1
    assert window._overview_panel._buffer_store.get_last("Т1") is None
    cell = window._overview_panel._sensor_grid._cells["Т1"]
    assert cell._value_widget.text() == "—"
    assert cell._status_hint_widget.text() == "Нет связи · данных нет"
    assert "dashed" in cell.styleSheet()


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


def test_bridge_retirement_clears_experiment_truth_from_every_real_consumer(monkeypatch) -> None:
    """Outgoing experiment status cannot survive bridge authority retirement."""
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
    assert window._experiment_overlay._experiment is None
    assert window._experiment_overlay._phase_history == []
    assert window._experiment_overlay._templates_by_id == {}
    assert window._experiment_overlay._connected is False
    assert window._operator_log_panel._current_experiment_id is None
    assert window._operator_log_panel._bind_experiment_check.isChecked() is False
    assert window._analytics_view._last_experiment_status is None
    assert window._analytics_view.current_phase() is None
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
    assert window._experiment_overlay._experiment is None
    assert window._experiment_overlay._templates_by_id == {}
    assert window._operator_log_panel._current_experiment_id is None
    assert window._analytics_view._last_experiment_status is None
    assert window._analytics_view.current_phase() is None
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


def test_successor_experiment_status_restores_cleared_template_truth() -> None:
    """A new accepted status repopulates every experiment overlay field."""
    _app()
    window = MainWindowV2()
    _stop_timers(window)
    outgoing = _active_experiment_status_for_retirement()
    window._on_experiment_status_received(outgoing)
    window._ensure_overlay("experiment")
    assert window._experiment_overlay is not None
    assert set(window._experiment_overlay._templates_by_id) == {"template-1"}

    window.invalidate_descriptor_transport()
    assert window._experiment_overlay._templates_by_id == {}

    successor = _active_experiment_status_for_retirement()
    successor["active_experiment"]["experiment_id"] = "b" * 12
    successor["active_experiment"]["template_id"] = "template-2"
    successor["templates"] = [{"id": "template-2", "name": "Template 2"}]
    window._on_experiment_status_received(successor)

    assert set(window._experiment_overlay._templates_by_id) == {"template-2"}
    assert window._experiment_overlay._experiment["experiment_id"] == "b" * 12
