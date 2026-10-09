"""v0.55.16.0.1 (smoke hotfix) — TemperatureOverviewWidget no-op setters.

The PART D measurement layout puts TemperatureOverviewWidget in
bottom_right. Without no-op setters, AnalyticsView._forward() logs
WARNINGs every tick for set_pressure_reading / set_keithley_readings /
set_experiment_status / set_cold_temperature_reading. The setters are
no-ops because those data types are rendered by other widgets — the
underlying readings still persist via the standard
Scheduler→SQLiteWriter→DataBroker path.
"""

from __future__ import annotations

import logging

import pytest
from PySide6.QtCore import QCoreApplication

from cryodaq.gui.shell.views.analytics_widgets import TemperatureOverviewWidget


@pytest.fixture
def qapp():
    app = QCoreApplication.instance()
    if app is None:
        from PySide6.QtWidgets import QApplication

        app = QApplication([])
    yield app


def test_temperature_overview_pressure_setter_is_noop(qapp) -> None:
    widget = TemperatureOverviewWidget()
    # No-op should not raise on any reasonable input
    widget.set_pressure_reading(None)


def test_temperature_overview_keithley_setter_is_noop(qapp) -> None:
    widget = TemperatureOverviewWidget()
    widget.set_keithley_readings({"smua": None})


def test_temperature_overview_experiment_status_setter_is_noop(qapp) -> None:
    widget = TemperatureOverviewWidget()
    widget.set_experiment_status({"phase": "measurement"})
    widget.set_experiment_status(None)


def test_temperature_overview_cold_temperature_setter_is_noop(qapp) -> None:
    widget = TemperatureOverviewWidget()
    widget.set_cold_temperature_reading(None)


def test_analytics_dispatch_no_warning_for_no_op_widgets(
    qapp, caplog: pytest.LogCaptureFixture
) -> None:
    """The AnalyticsView dispatcher logs WARNING when no active widget
    implements a setter. With the no-ops, calls to those setters
    forward successfully and do NOT trigger the warning."""
    from cryodaq.gui.shell.views.analytics_view import AnalyticsView

    view = AnalyticsView()
    # Simulate a layout where TemperatureOverviewWidget is the only
    # active member (worst-case: every "no-op" setter gets routed only
    # to TemperatureOverviewWidget and would otherwise log).
    view._active = {"bottom_right": TemperatureOverviewWidget()}
    view._phase = "measurement"

    with caplog.at_level(logging.WARNING):
        view._forward("set_pressure_reading", None)
        view._forward("set_keithley_readings", {})
        view._forward("set_experiment_status", None)
        view._forward("set_cold_temperature_reading", None)

    # No warning should have been logged for any of those four setters.
    assert not any(
        "no active widget" in rec.message for rec in caplog.records
    )


def test_analytics_dispatch_still_warns_for_truly_missing_setter(
    qapp, caplog: pytest.LogCaptureFixture
) -> None:
    """Regression check — the no-op fix must NOT swallow warnings for
    setters that genuinely have no implementer. A made-up setter name
    must still produce the WARNING so future dispatcher additions are
    visible during development."""
    from cryodaq.gui.shell.views.analytics_view import AnalyticsView

    view = AnalyticsView()
    view._active = {"bottom_right": TemperatureOverviewWidget()}
    view._phase = "measurement"

    with caplog.at_level(logging.WARNING):
        view._forward("set_completely_made_up_method", None)

    assert any(
        "no active widget" in rec.message for rec in caplog.records
    )
