"""II.8 host integration: MainWindowV2 ↔ InstrumentsPanel wiring.

Verifies:
- Connection mirror (_tick_status + _ensure_overlay replay).
- Readings routing (LakeShore + Keithley → cards).
- Analytics readings do NOT create cards.
- Public accessor callable from host.
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QTimer
from PySide6.QtWidgets import QApplication

from cryodaq.channels.descriptors import (
    ChannelDescriptorV1,
    ChannelQuantity,
    ChannelRole,
    ChannelSafetyClass,
)
from cryodaq.core.descriptor_transport import DescriptorEnvelopeIssue, DescriptorQualifiedReading
from cryodaq.drivers.base import Reading
from cryodaq.gui.shell.main_window_v2 import MainWindowV2
from cryodaq.gui.state.descriptor_store import DescriptorStore


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _stop_timers(w: MainWindowV2) -> None:
    for timer in w.findChildren(QTimer):
        try:
            timer.stop()
        except RuntimeError:
            pass


def _k_reading(channel: str, value: float = 1.0, instrument_id: str = "") -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id=instrument_id,
        channel=channel,
        value=value,
        unit="K",
        metadata={},
    )


def _qualified(reading: Reading) -> DescriptorQualifiedReading:
    return DescriptorQualifiedReading(
        reading=reading,
        descriptor=ChannelDescriptorV1(
            schema_version=1,
            channel_id=reading.channel,
            instrument_id=reading.instrument_id,
            source_key="measurement.primary",
            quantity=ChannelQuantity.TEMPERATURE,
            unit=reading.unit,
            role=ChannelRole.PRIMARY_MEASUREMENT,
            safety_class=ChannelSafetyClass.OBSERVATIONAL,
            display_group="generic",
            display_name="Generic channel",
            visible_by_default=True,
            display_order=1,
            descriptor_revision=1,
        ),
    )


# ----------------------------------------------------------------------
# Connection mirror
# ----------------------------------------------------------------------


def test_tick_sets_overlay_connected_true_when_recent():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("instruments")
        w._last_reading_time = time.monotonic()
        w._tick_status()
        # Visible contract: set_connected(True) starts the diagnostics poll timer.
        assert w._instrument_panel._diag_poll_timer.isActive() is True
    finally:
        _stop_timers(w)


def test_tick_sets_overlay_connected_false_when_stale():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("instruments")
        # First connect so state flips from False → True → False.
        w._last_reading_time = time.monotonic()
        w._tick_status()
        w._last_reading_time = time.monotonic() - 10.0
        w._tick_status()
        # Visible contract: set_connected(False) stops the diagnostics poll timer.
        assert w._instrument_panel._diag_poll_timer.isActive() is False
    finally:
        _stop_timers(w)


# ----------------------------------------------------------------------
# Readings routing
# ----------------------------------------------------------------------


def test_provider_neutral_qualified_reading_creates_card():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("instruments")
        reading = _k_reading("opaque-channel", instrument_id="asc-reference-42")
        w.dispatch_qualified_reading(_qualified(reading))
        QCoreApplication.processEvents()
        assert w._instrument_panel.get_instrument_count() == 1
        assert "asc-reference-42" in w._instrument_panel._cards
        # Visible contract: the rendered card shows the instrument name label.
        card = w._instrument_panel._cards["asc-reference-42"]
        assert card._name_label.text() == "asc-reference-42"
        assert card.total_readings == 1
    finally:
        _stop_timers(w)


def test_bare_reading_with_vendor_shaped_channel_does_not_create_card():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("instruments")
        w._dispatch_reading(_k_reading("Keithley_1/smua/voltage", instrument_id="Keithley_1"))
        QCoreApplication.processEvents()
        assert w._instrument_panel.get_instrument_count() == 0
    finally:
        _stop_timers(w)


def test_refused_descriptor_is_visible_and_does_not_create_card():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("instruments")
        reading = _k_reading("opaque-channel", instrument_id="claimed")
        w.dispatch_qualified_reading(
            DescriptorQualifiedReading(
                reading=reading,
                descriptor=None,
                descriptor_issue=DescriptorEnvelopeIssue.MALFORMED,
            )
        )
        QCoreApplication.processEvents()
        assert w._instrument_panel.get_instrument_count() == 0
        assert "отклонено" in w._instrument_panel._empty_cards_label.text()
    finally:
        _stop_timers(w)


def test_descriptor_store_capacity_exhaustion_is_visible_and_never_attributed():
    _app()
    w = MainWindowV2()
    try:
        w._descriptor_store = DescriptorStore(max_entries=1)
        w._ensure_overlay("instruments")
        first = _k_reading("channel-one", instrument_id="instrument-one")
        second = _k_reading("channel-two", instrument_id="instrument-two")
        w.dispatch_qualified_reading(_qualified(first))
        w.dispatch_qualified_reading(_qualified(second))
        QCoreApplication.processEvents()
        assert set(w._instrument_panel._cards) == {"instrument-one"}
        assert "отклонено" in w._instrument_panel._empty_cards_label.text()
    finally:
        _stop_timers(w)


# ----------------------------------------------------------------------
# Lazy replay on first open
# ----------------------------------------------------------------------


def test_lazy_open_replays_connection_when_recent():
    _app()
    w = MainWindowV2()
    try:
        w._last_reading_time = time.monotonic()
        w._ensure_overlay("instruments")
        # Visible contract: recent reading replayed → diag poll timer started.
        assert w._instrument_panel._diag_poll_timer.isActive() is True
    finally:
        _stop_timers(w)


def test_lazy_open_disconnected_on_cold_start():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("instruments")
        # Visible contract: cold-open → diag poll timer not started.
        assert w._instrument_panel._diag_poll_timer.isActive() is False
    finally:
        _stop_timers(w)


# ----------------------------------------------------------------------
# Public accessor callable from host
# ----------------------------------------------------------------------


def test_get_sensor_summary_text_callable_from_host():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("instruments")
        assert w._instrument_panel.get_sensor_summary_text() == "—"
    finally:
        _stop_timers(w)
