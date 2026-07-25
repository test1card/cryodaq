"""II.5 host integration: verify MainWindowV2 pushes connection state
into the Conductivity overlay and that temperature / power readings
route correctly.
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from cryodaq.channels.descriptors import (
    ChannelDescriptorV1,
    ChannelQuantity,
    ChannelRole,
    ChannelSafetyClass,
)
from cryodaq.core.descriptor_transport import DescriptorQualifiedReading
from cryodaq.drivers.base import Reading
from cryodaq.gui.shell.main_window_v2 import MainWindowV2


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _stop_timers(w: MainWindowV2) -> None:
    for timer in w.findChildren(QTimer):
        try:
            timer.stop()
        except RuntimeError:
            pass


def _temp_reading(channel: str, value: float) -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="LakeShore_1",
        channel=channel,
        value=value,
        unit="K",
        metadata={},
    )


def _power_reading(value: float) -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="Keithley_1",
        channel="Keithley_1/smua/power",
        value=value,
        unit="W",
        metadata={},
    )


def _dispatch_described(
    w: MainWindowV2,
    reading: Reading,
    quantity: ChannelQuantity,
    *,
    source: bool = False,
) -> None:
    descriptor = ChannelDescriptorV1(
        schema_version=1,
        channel_id=reading.channel,
        instrument_id=reading.instrument_id,
        source_key="test.conductivity",
        quantity=quantity,
        unit=reading.unit,
        role=ChannelRole.SOURCE_READBACK if source else ChannelRole.PRIMARY_MEASUREMENT,
        safety_class=(ChannelSafetyClass.HAZARDOUS_SOURCE_READBACK if source else ChannelSafetyClass.OBSERVATIONAL),
        display_group="test",
        display_name="Test conductivity channel",
        visible_by_default=True,
        display_order=0,
        descriptor_revision=1,
    )
    w.dispatch_qualified_reading(DescriptorQualifiedReading(reading=reading, descriptor=descriptor))


# ----------------------------------------------------------------------
# Connection mirror
# ----------------------------------------------------------------------


def test_tick_sets_overlay_connected_true_when_recent():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("conductivity")
        w._last_reading_time = time.monotonic()
        w._tick_status()
        # Visible contract: set_connected(True) enables the auto-sweep Start
        # button (idle state → start_ok = connected and not stabilizing).
        assert w._conductivity_panel._auto_start_btn.isEnabled() is True
    finally:
        _stop_timers(w)


def test_tick_sets_overlay_connected_false_when_stale():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("conductivity")
        w._last_reading_time = time.monotonic() - 10.0
        w._tick_status()
        # Visible contract: set_connected(False) disables the auto-sweep Start
        # button.
        assert w._conductivity_panel._auto_start_btn.isEnabled() is False
    finally:
        _stop_timers(w)


# ----------------------------------------------------------------------
# Readings routing
# ----------------------------------------------------------------------


def test_temperature_reading_reaches_overlay():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("conductivity")
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtWidgets import QCheckBox

        panel = w._conductivity_panel

        # Inject two visible channels so _chain has ≥2 elements and _update_table
        # actually produces at least one data row with t_hot / t_cold cells.
        for col, ch in enumerate(("Т1", "Т2")):
            cb = QCheckBox(ch)
            panel._checkboxes[ch] = cb
            panel._ch_layout.addWidget(cb, 0, col)
            cb.stateChanged.connect(lambda state, _ch=ch: panel._on_check(_ch, state))
            cb.setChecked(True)

        QCoreApplication.processEvents()

        # Dispatch both readings through the shell.
        _dispatch_described(w, _temp_reading("Т1", 77.3), ChannelQuantity.TEMPERATURE)
        _dispatch_described(w, _temp_reading("Т2", 4.2), ChannelQuantity.TEMPERATURE)
        QCoreApplication.processEvents()

        # Assert stored values (feeds table on next _refresh tick).
        assert panel._temps.get("Т1") == 77.3
        assert panel._temps.get("Т2") == 4.2

        # Call _refresh() to drive _update_table and verify rendered cells.
        panel._refresh()
        QCoreApplication.processEvents()

        table = panel._table
        assert table.rowCount() >= 1, "_refresh() produced no table rows"
        # Column 1 = t_hot formatted as .4f, column 2 = t_cold formatted as .4f.
        t_hot_item = table.item(0, 1)
        t_cold_item = table.item(0, 2)
        assert t_hot_item is not None, "t_hot cell (col 1) is None after _refresh()"
        assert t_cold_item is not None, "t_cold cell (col 2) is None after _refresh()"
        assert t_hot_item.text() == f"{77.3:.4f}", f"t_hot cell text wrong: {t_hot_item.text()!r}"
        assert t_cold_item.text() == f"{4.2:.4f}", f"t_cold cell text wrong: {t_cold_item.text()!r}"
    finally:
        _stop_timers(w)


def test_power_reading_reaches_overlay():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("conductivity")
        _dispatch_described(w, _power_reading(0.037), ChannelQuantity.POWER, source=True)
        from PySide6.QtCore import QCoreApplication

        QCoreApplication.processEvents()
        # Assert stored value AND that it renders into the power label.
        assert w._conductivity_panel._power == 0.037
        w._conductivity_panel._update_power_label()
        assert "0.037" in w._conductivity_panel._power_label.text()
    finally:
        _stop_timers(w)


def test_unrelated_reading_does_not_affect_overlay():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("conductivity")
        w._dispatch_reading(
            Reading(
                timestamp=datetime.now(UTC),
                instrument_id="x",
                channel="analytics/safety_state",
                value=0.0,
                unit="",
                metadata={"state": "ready"},
            )
        )
        from PySide6.QtCore import QCoreApplication

        QCoreApplication.processEvents()
        # No mutation.
        assert w._conductivity_panel._temps == {}
        assert w._conductivity_panel._power == 0.0
    finally:
        _stop_timers(w)


# ----------------------------------------------------------------------
# Lazy replay
# ----------------------------------------------------------------------


def test_lazy_open_replays_connection_when_recent():
    _app()
    w = MainWindowV2()
    try:
        w._last_reading_time = time.monotonic()
        w._ensure_overlay("conductivity")
        assert w._conductivity_panel is not None
        # Visible contract: lazy-open with recent reading → Start button enabled.
        assert w._conductivity_panel._auto_start_btn.isEnabled() is True
    finally:
        _stop_timers(w)


def test_lazy_open_disconnected_on_cold_start():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("conductivity")
        # Visible contract: cold-open → Start button disabled.
        assert w._conductivity_panel._auto_start_btn.isEnabled() is False
    finally:
        _stop_timers(w)


# ----------------------------------------------------------------------
# Auto-state accessor
# ----------------------------------------------------------------------


def test_get_auto_state_accessible_from_host():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("conductivity")
        # The future finalize guard wiring (II.9) will call this.
        assert w._conductivity_panel.get_auto_state() == "idle"
        assert w._conductivity_panel.is_auto_sweep_active() is False
    finally:
        _stop_timers(w)
