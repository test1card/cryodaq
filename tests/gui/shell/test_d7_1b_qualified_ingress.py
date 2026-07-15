"""Production-level tests for descriptor-qualified GUI ingress."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

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
from cryodaq.gui.app import _drain_bridge_readings, _shutdown_gui_runtime
from cryodaq.gui.shell.main_window_v2 import MainWindowV2
from cryodaq.gui.state.descriptor_store import IdentityStatus, TransportState
from cryodaq.launcher import LauncherWindow


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _reading(channel: str = "T01", unit: str = "K") -> Reading:
    return Reading(
        timestamp=datetime.fromtimestamp(0, tz=UTC),
        instrument_id="test_inst",
        channel=channel,
        value=4.2,
        unit=unit,
        status=ChannelStatus.OK,
    )


def _descriptor(reading: Reading) -> ChannelDescriptorV1:
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


def _qualified(reading: Reading, *, described: bool = False) -> DescriptorQualifiedReading:
    return DescriptorQualifiedReading(
        reading=reading,
        descriptor=_descriptor(reading) if described else None,
    )


@pytest.mark.parametrize("described", [False, True])
def test_main_window_ingests_then_dispatches_valid_reading_once(described: bool) -> None:
    _app()
    window = MainWindowV2()
    reading = _reading()
    qualified = _qualified(reading, described=described)

    with patch.object(window, "_dispatch_reading") as dispatch:
        window.dispatch_qualified_reading(qualified)

    assert window._descriptor_store.identity_status(reading.channel) is (
        IdentityStatus.AUTHORITATIVE if described else IdentityStatus.LEGACY_ABSENT
    )
    dispatch.assert_called_once_with(reading)


def test_main_window_drops_malformed_carrier_before_store_or_legacy_sinks() -> None:
    _app()
    window = MainWindowV2()
    malformed = DescriptorQualifiedReading(reading=object(), descriptor=None)  # type: ignore[arg-type]

    with (
        patch.object(window._descriptor_store, "ingest") as ingest,
        patch.object(window, "_dispatch_reading") as dispatch,
    ):
        window.dispatch_qualified_reading(malformed)

    ingest.assert_not_called()
    dispatch.assert_not_called()


def test_main_window_preserves_valid_reading_after_unexpected_ingest_failure() -> None:
    _app()
    window = MainWindowV2()
    qualified = _qualified(_reading())

    with (
        patch.object(window._descriptor_store, "ingest", side_effect=ValueError("broken")),
        patch.object(window, "_dispatch_reading") as dispatch,
    ):
        window.dispatch_qualified_reading(qualified)

    dispatch.assert_called_once_with(qualified.reading)


def test_main_window_never_hides_store_thread_ownership_violation() -> None:
    _app()
    window = MainWindowV2()
    qualified = _qualified(_reading())

    with (
        patch.object(window, "_dispatch_reading") as dispatch,
        ThreadPoolExecutor(max_workers=1) as executor,
    ):
        future = executor.submit(window.dispatch_qualified_reading, qualified)
        with pytest.raises(RuntimeError, match="owning GUI thread"):
            future.result()

    dispatch.assert_not_called()


def test_transport_invalidation_marks_existing_identity_disconnected() -> None:
    _app()
    window = MainWindowV2()
    qualified = _qualified(_reading())
    with patch.object(window, "_dispatch_reading"):
        window.dispatch_qualified_reading(qualified)

    window.invalidate_descriptor_transport()

    view = window._descriptor_store.view(qualified.reading.channel)
    assert view is not None
    assert view.transport_state is TransportState.DISCONNECTED


def test_app_drain_preserves_mixed_batch_order_and_drops_malformed() -> None:
    first = _qualified(_reading("T01"))
    malformed = DescriptorQualifiedReading(reading=object(), descriptor=None)  # type: ignore[arg-type]
    second = _qualified(_reading("T02"))
    bridge = MagicMock()
    bridge.poll_readings_with_descriptor.return_value = [first, malformed, second]
    _app()
    window = MainWindowV2()

    with patch.object(window, "_dispatch_reading") as dispatch:
        _drain_bridge_readings(bridge, window)

    bridge.poll_readings_with_descriptor.assert_called_once_with()
    bridge.poll_readings.assert_not_called()
    assert [call.args[0] for call in dispatch.call_args_list] == [first.reading, second.reading]


def test_launcher_drain_calls_production_method_and_exact_type_guard() -> None:
    first = _qualified(_reading("T01"))
    malformed = DescriptorQualifiedReading(reading=object(), descriptor=None)  # type: ignore[arg-type]
    second = _qualified(_reading("T02"))
    bridge = MagicMock()
    bridge.poll_readings_with_descriptor.return_value = [first, malformed, second]
    bridge.is_healthy.return_value = True
    bridge.data_flow_stalled.return_value = False
    bridge.command_channel_stalled.return_value = False
    window = MagicMock()
    launcher = SimpleNamespace(
        _bridge=bridge,
        _main_window=window,
        _reading_count=0,
        _last_reading_time=0.0,
        _soak_bridge_handshake=None,
        _on_reading_qt=lambda item: LauncherWindow._on_reading_qt(launcher, item),
        _invalidate_descriptor_transport=lambda: None,
    )

    LauncherWindow._poll_bridge_data(launcher)
    bridge.poll_readings_with_descriptor.assert_called_once_with()
    bridge.poll_readings.assert_not_called()
    assert [call.args[0] for call in window.dispatch_qualified_reading.call_args_list] == [first, second]
    assert launcher._reading_count == 2


def test_standalone_shutdown_stops_timer_before_invalidation_and_no_late_drain() -> None:
    qualified = _qualified(_reading())
    bridge = MagicMock()
    bridge.poll_readings_with_descriptor.return_value = [qualified]
    window = MagicMock()
    calls: list[str] = []

    class _Timer:
        active = True

        def stop(self) -> None:
            calls.append("timer.stop")
            self.active = False

        def fire(self) -> None:
            if self.active:
                _drain_bridge_readings(bridge, window)

    timer = _Timer()
    snapshot = MagicMock()
    snapshot.stop.side_effect = lambda: calls.append("snapshot.stop")
    window.invalidate_descriptor_transport.side_effect = lambda: calls.append("invalidate")

    timer.fire()
    window.dispatch_qualified_reading.reset_mock()
    with patch("cryodaq.gui.app.shutdown", side_effect=lambda: calls.append("shutdown")):
        _shutdown_gui_runtime(timer, snapshot, window)
    timer.fire()

    assert calls == ["timer.stop", "invalidate", "snapshot.stop", "shutdown"]
    window.dispatch_qualified_reading.assert_not_called()
