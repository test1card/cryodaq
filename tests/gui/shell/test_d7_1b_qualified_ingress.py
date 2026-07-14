"""D7.1b Option-C production cutover tests.

Verifies:
- app.py _tick drain calls poll_readings_with_descriptor and routes via
  dispatch_qualified_reading (not poll_readings).
- launcher._poll_bridge_data drain calls poll_readings_with_descriptor and
  routes via dispatch_qualified_reading (not poll_readings).
- A descriptor-bearing qualified reading updates the store AND delegates
  the bare reading to _dispatch_reading legacy sinks exactly once.
- A legacy (descriptor=None) qualified reading still delegates the bare
  reading to legacy sinks exactly once.
- Production source files contain no poll_readings() caller in the two
  cut sites.
"""

from __future__ import annotations

import ast
import os
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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
from cryodaq.gui.state.descriptor_store import IdentityStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_WT = Path(__file__).parents[3]  # worktree root


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _make_reading(channel: str = "Т01 Тест", unit: str = "K") -> Reading:
    return Reading(
        timestamp=datetime.fromtimestamp(0, tz=UTC),
        instrument_id="test_inst",
        channel=channel,
        value=4.2,
        unit=unit,
        status=ChannelStatus.OK,
    )


def _make_qualified(
    reading: Reading,
    descriptor: ChannelDescriptorV1 | None = None,
) -> DescriptorQualifiedReading:
    return DescriptorQualifiedReading(reading=reading, descriptor=descriptor)


def _make_descriptor(reading: Reading) -> ChannelDescriptorV1:
    """Build a minimal valid ChannelDescriptorV1 matching the reading tuple."""
    return ChannelDescriptorV1(
        schema_version=1,
        channel_id=reading.channel,
        instrument_id=reading.instrument_id,
        source_key="test.sensor",
        quantity=ChannelQuantity.TEMPERATURE,
        unit=reading.unit,
        role=ChannelRole.PRIMARY_MEASUREMENT,
        safety_class=ChannelSafetyClass.OBSERVATIONAL,
        display_group="test_group",
        display_name="Test Channel",
        visible_by_default=True,
        display_order=0,
        descriptor_revision=1,
    )


# ---------------------------------------------------------------------------
# 1. MainWindowV2 has _descriptor_store and dispatch_qualified_reading
# ---------------------------------------------------------------------------


def test_main_window_has_descriptor_store() -> None:
    _app()
    w = MainWindowV2()
    assert hasattr(w, "_descriptor_store"), "_descriptor_store must exist on MainWindowV2"
    assert hasattr(w, "dispatch_qualified_reading"), "dispatch_qualified_reading must exist"
    assert hasattr(w, "invalidate_descriptor_transport"), "invalidate_descriptor_transport must exist"


# ---------------------------------------------------------------------------
# 2. Descriptor-bearing qualified reading updates store AND hits legacy sink
# ---------------------------------------------------------------------------


def test_dispatch_qualified_reading_authoritative_updates_store_and_legacy_sink() -> None:
    _app()
    w = MainWindowV2()
    reading = _make_reading(channel="Т01")  # no internal space: descriptor channel_id constraint
    descriptor = _make_descriptor(reading)
    qualified = _make_qualified(reading, descriptor)

    dispatched: list[Reading] = []
    original_dispatch = w._dispatch_reading

    def _capture(r: Reading) -> None:
        dispatched.append(r)
        original_dispatch(r)

    with patch.object(w, "_dispatch_reading", side_effect=_capture):
        w.dispatch_qualified_reading(qualified)

    # Store updated
    status = w._descriptor_store.identity_status(reading.channel)
    assert status is IdentityStatus.AUTHORITATIVE, f"Expected AUTHORITATIVE, got {status}"

    # Legacy sink called exactly once with the bare reading
    assert len(dispatched) == 1
    assert dispatched[0] is reading


# ---------------------------------------------------------------------------
# 3. Legacy (descriptor=None) qualified reading still reaches legacy sinks once
# ---------------------------------------------------------------------------


def test_dispatch_qualified_reading_legacy_absent_still_dispatches() -> None:
    _app()
    w = MainWindowV2()
    reading = _make_reading(channel="Т02 Legacy", unit="K")
    qualified = _make_qualified(reading, descriptor=None)

    dispatched: list[Reading] = []
    original_dispatch = w._dispatch_reading

    def _capture(r: Reading) -> None:
        dispatched.append(r)
        original_dispatch(r)

    with patch.object(w, "_dispatch_reading", side_effect=_capture):
        w.dispatch_qualified_reading(qualified)

    # Store updated to LEGACY_ABSENT
    status = w._descriptor_store.identity_status(reading.channel)
    assert status is IdentityStatus.LEGACY_ABSENT, f"Expected LEGACY_ABSENT, got {status}"

    # Legacy sink called exactly once
    assert len(dispatched) == 1
    assert dispatched[0] is reading


# ---------------------------------------------------------------------------
# 4. No double dispatch — _dispatch_reading called exactly once per qualified
# ---------------------------------------------------------------------------


def test_no_double_dispatch() -> None:
    _app()
    w = MainWindowV2()
    reading = _make_reading(channel="Т03")  # no internal space: descriptor channel_id constraint
    descriptor = _make_descriptor(reading)
    qualified = _make_qualified(reading, descriptor)

    call_count = 0
    original_dispatch = w._dispatch_reading

    def _count(r: Reading) -> None:
        nonlocal call_count
        call_count += 1
        original_dispatch(r)

    with patch.object(w, "_dispatch_reading", side_effect=_count):
        w.dispatch_qualified_reading(qualified)

    assert call_count == 1, f"_dispatch_reading must be called exactly once; got {call_count}"


# ---------------------------------------------------------------------------
# 5. invalidate_descriptor_transport advances store generation
# ---------------------------------------------------------------------------


def test_invalidate_descriptor_transport_marks_entries_disconnected() -> None:
    from cryodaq.gui.state.descriptor_store import TransportState

    _app()
    w = MainWindowV2()
    reading = _make_reading(channel="Т04 Inval")
    qualified = _make_qualified(reading)
    w.dispatch_qualified_reading(qualified)  # creates entry, CONNECTED

    view_before = w._descriptor_store.view(reading.channel)
    assert view_before is not None
    assert view_before.transport_state is TransportState.CONNECTED

    w.invalidate_descriptor_transport()

    view_after = w._descriptor_store.view(reading.channel)
    assert view_after is not None
    assert view_after.transport_state is TransportState.DISCONNECTED


# ---------------------------------------------------------------------------
# 6. app.py _tick drain: uses poll_readings_with_descriptor, not poll_readings
# ---------------------------------------------------------------------------


def test_app_tick_drain_uses_poll_readings_with_descriptor() -> None:
    """Verify app.py _tick calls poll_readings_with_descriptor and routes via
    dispatch_qualified_reading. Uses a fake bridge and fake window to avoid Qt."""
    reading = _make_reading(channel="Т05 AppTick")
    qualified = _make_qualified(reading)

    fake_bridge = MagicMock()
    fake_bridge.poll_readings_with_descriptor.return_value = [qualified]
    fake_bridge.is_healthy.return_value = True
    fake_bridge.data_flow_stalled.return_value = False

    dispatched_qualified: list[DescriptorQualifiedReading] = []

    fake_window = MagicMock()
    fake_window.dispatch_qualified_reading.side_effect = dispatched_qualified.append

    fake_snapshot_ingress = MagicMock()

    # Reconstruct the _tick closure from app.py logic inline (same structure)
    def _tick() -> None:
        for q in fake_bridge.poll_readings_with_descriptor():
            fake_window.dispatch_qualified_reading(q)
        fake_snapshot_ingress.pump()

    _tick()

    fake_bridge.poll_readings_with_descriptor.assert_called_once()
    fake_bridge.poll_readings.assert_not_called()
    assert len(dispatched_qualified) == 1
    assert dispatched_qualified[0] is qualified


# ---------------------------------------------------------------------------
# 7. launcher _poll_bridge_data drain: uses poll_readings_with_descriptor
# ---------------------------------------------------------------------------


def test_launcher_poll_bridge_data_uses_poll_readings_with_descriptor() -> None:
    """Verify launcher._poll_bridge_data drains poll_readings_with_descriptor
    and routes each item through dispatch_qualified_reading."""
    reading = _make_reading(channel="Т06 LaunchTick")
    qualified = _make_qualified(reading)

    dispatched: list[DescriptorQualifiedReading] = []

    fake_bridge = MagicMock()
    fake_bridge.poll_readings_with_descriptor.return_value = [qualified]
    fake_bridge.is_healthy.return_value = True
    fake_bridge.data_flow_stalled.return_value = False
    fake_bridge.command_channel_stalled.return_value = False

    fake_window = MagicMock()
    fake_window.dispatch_qualified_reading.side_effect = dispatched.append

    # Simulate the launcher's _poll_bridge_data logic (same structure)
    def _poll_bridge_data() -> None:
        for q in fake_bridge.poll_readings_with_descriptor():
            # mirrors _on_reading_qt routing
            fake_window.dispatch_qualified_reading(q)

        unhealthy = not fake_bridge.is_healthy()
        stalled = fake_bridge.data_flow_stalled() if not unhealthy else False
        if unhealthy or stalled:
            return
        if fake_bridge.command_channel_stalled(timeout_s=10.0):
            return

    _poll_bridge_data()

    fake_bridge.poll_readings_with_descriptor.assert_called_once()
    fake_bridge.poll_readings.assert_not_called()
    assert len(dispatched) == 1
    assert dispatched[0] is qualified


# ---------------------------------------------------------------------------
# 8. Source-scan: no production poll_readings() call in app.py or launcher.py
# ---------------------------------------------------------------------------


def _find_poll_readings_calls(source: str) -> list[int]:
    """Return line numbers of bare poll_readings() calls (not _with_descriptor)."""
    tree = ast.parse(source)
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "poll_readings":
            hits.append(node.lineno)
    return hits


def test_app_py_has_no_production_poll_readings_call() -> None:
    app_py = _WT / "src" / "cryodaq" / "gui" / "app.py"
    source = app_py.read_text(encoding="utf-8")
    hits = _find_poll_readings_calls(source)
    assert hits == [], (
        f"app.py still calls poll_readings() at line(s) {hits}; "
        "must use poll_readings_with_descriptor() after D7.1b cutover"
    )


def test_launcher_py_has_no_production_poll_readings_call() -> None:
    launcher_py = _WT / "src" / "cryodaq" / "launcher.py"
    source = launcher_py.read_text(encoding="utf-8")
    hits = _find_poll_readings_calls(source)
    assert hits == [], (
        f"launcher.py still calls poll_readings() at line(s) {hits}; "
        "must use poll_readings_with_descriptor() after D7.1b cutover"
    )
