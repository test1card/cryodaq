"""II.6 post-review: verify MainWindowV2 pushes connection + safety state
into the Keithley overlay.

The regression showed that the shell never invoked
``KeithleyPanel.set_connected`` or ``set_safety_ready`` after the II.6
rewrite — so in production the overlay showed permanent «Нет связи»
and controls stayed disabled. These tests exercise the host wiring
end-to-end, not the overlay setters in isolation.
"""

from __future__ import annotations

import os
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from cryodaq.core.broker import PUBLISHER_AUTHORITY_METADATA_KEY
from cryodaq.drivers.base import Reading
from cryodaq.gui.shell import main_window_v2 as main_window_module
from cryodaq.gui.shell.main_window_v2 import MainWindowV2
from cryodaq.gui.shell.overlays.keithley_panel import SafetyGateCause
from cryodaq.gui.state.operator_view_models import OperatorSnapshotStore
from cryodaq.gui.zmq_client import ZmqBridge
from cryodaq.operator_snapshot import (
    AttentionQueue,
    AvailabilityTruth,
    CooldownHistorySummary,
    CooldownSample,
    DataIntegritySummary,
    ExperimentOperatingState,
    InfrastructureNode,
    InfrastructureNodeHealth,
    OperatorPresentationState,
    OperatorSnapshot,
    PlantHealthItem,
    PlantHealthSummary,
    ReadinessBlocker,
    ReadinessSummary,
    ReadinessTruth,
    RecordingTruth,
    SafetyLifecycle,
    SnapshotCut,
    SnapshotMode,
    SummaryStatus,
    SupportBundleEntry,
    SupportBundleManifest,
    SupportBundleSummary,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _stop_timers(w: MainWindowV2) -> None:
    for timer in w.findChildren(QTimer):
        try:
            timer.stop()
        except RuntimeError:
            pass


def _controlled_measurement_clock(monkeypatch: pytest.MonkeyPatch, w: MainWindowV2) -> list[float]:
    clock = [100.0]
    monkeypatch.setattr(main_window_module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    w._last_reading_time = clock[0]
    return clock


def _safety_reading(
    state: str,
    reason: str = "",
    *,
    observed_at: datetime | None = None,
    bridge_id: str | None = None,
    experiment_id: str | None = None,
) -> Reading:
    metadata = {"state": state, "reason": reason}
    if bridge_id is not None:
        metadata["bridge_instance_id"] = bridge_id
    if experiment_id is not None:
        metadata["experiment_id"] = experiment_id
    return Reading(
        timestamp=observed_at or datetime.now(UTC),
        instrument_id="safety_manager",
        channel="analytics/safety_state",
        value=0.0,
        unit="",
        metadata=metadata,
    )


def _source_state_reading(
    channel: str,
    state: str,
    *,
    observed_at: datetime | None = None,
    authoritative: bool = True,
) -> Reading:
    metadata = {"state": state}
    if authoritative:
        metadata[PUBLISHER_AUTHORITY_METADATA_KEY] = "safety_manager_source_state_v1"
    return Reading(
        timestamp=observed_at or datetime.now(UTC),
        instrument_id="safety_manager",
        channel=f"analytics/keithley_channel_state/{channel}",
        value=0.0,
        unit="",
        metadata=metadata,
    )


def _measurement_reading() -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="lakeshore",
        channel="lakeshore/input_a/temperature",
        value=4.2,
        unit="K",
    )


class _TransportRestartBridge:
    """Minimal exact-generation bridge for the launcher watchdog path."""

    def __init__(self) -> None:
        self.bridge_instance_id = "a" * 32
        self._alive = True
        self._restart_count = 1

    def restart_count(self) -> int:
        return self._restart_count

    def shutdown(self) -> None:
        self._alive = False

    def start(self) -> None:
        assert not self._alive
        self._restart_count += 1
        self.bridge_instance_id = "f" * 32
        self._alive = True

    def is_alive(self) -> bool:
        return self._alive

    def is_healthy(self) -> bool:
        return self._alive

    def process_pid(self) -> int:
        return 12345 if self._alive else 0

    def close(self) -> None:
        if self._alive:
            self.shutdown()


def _new_transport_shutdown_standby() -> _TransportRestartBridge:
    standby = _TransportRestartBridge()
    standby.shutdown()
    return standby


def _typed_ready_snapshot(
    *,
    revision: int = 42,
    mode: SnapshotMode = SnapshotMode.LIVE,
    observed_at: datetime | None = None,
    received_at: datetime | None = None,
    experiment_id: str = "exp-1",
    safety_ready: bool = True,
) -> OperatorSnapshot:
    observed = observed_at or datetime.now(UTC) - timedelta(seconds=1)
    received = received_at or observed
    cut = SnapshotCut(revision, observed, received, "engine-v1", mode, experiment_id, "engine-v1")
    state = (
        OperatorPresentationState.OK
        if mode is SnapshotMode.LIVE and safety_ready
        else OperatorPresentationState.CAUTION
    )
    status = SummaryStatus(state, 1.0, 0.0, ("authoritative",), "Подтверждено")
    manifest = SupportBundleManifest(
        "bundle-42",
        cut.received_at,
        (SupportBundleEntry("status/status.json", 123, "a" * 64),),
    )
    readiness = ReadinessTruth.READY if mode is SnapshotMode.LIVE and safety_ready else ReadinessTruth.UNKNOWN
    lifecycle = SafetyLifecycle.READY if mode is SnapshotMode.LIVE and safety_ready else SafetyLifecycle.UNKNOWN
    recording = RecordingTruth.RECORDING if mode is SnapshotMode.LIVE else RecordingTruth.REPLAY_ONLY
    recording_session_id = "rec-1" if mode is SnapshotMode.LIVE else None
    availability = AvailabilityTruth.AVAILABLE if mode is SnapshotMode.LIVE else AvailabilityTruth.UNKNOWN
    support_manifest = manifest if mode is SnapshotMode.LIVE else None
    return OperatorSnapshot(
        cut,
        ReadinessSummary(cut, status, readiness, (), lifecycle),
        PlantHealthSummary(
            cut,
            status,
            (PlantHealthItem("plant", "Установка", OperatorPresentationState.OK, ()),),
        ),
        InfrastructureNodeHealth(
            cut,
            status,
            (InfrastructureNode("ups", "ИБП", OperatorPresentationState.OK, ()),),
        ),
        AttentionQueue(cut, status, ()),
        ExperimentOperatingState(
            cut,
            status,
            experiment_id,
            "Эксперимент",
            "cooldown",
            recording,
            recording_session_id,
        ),
        DataIntegritySummary(cut, status, 42, 41, 0, 0, availability),
        CooldownHistorySummary(cut, status, (CooldownSample(0, 300),), None, ()),
        SupportBundleSummary(cut, status, availability, support_manifest),
    )


def _typed_interlock_snapshot(*, revision: int = 43) -> OperatorSnapshot:
    snapshot = _typed_ready_snapshot(revision=revision)
    status = SummaryStatus(
        OperatorPresentationState.CAUTION,
        1.0,
        0.0,
        ("readiness_not_ready",),
        "Backend readiness authority",
    )
    readiness = ReadinessSummary(
        snapshot.cut,
        status,
        ReadinessTruth.BLOCKED,
        (
            ReadinessBlocker(
                "safety_state_safe_off",
                OperatorPresentationState.CAUTION,
                "Interlock stop_source: detector_warmup",
                "Review the active interlock before choosing Start",
            ),
        ),
        SafetyLifecycle.SAFE_OFF,
    )
    return replace(snapshot, readiness=readiness)


def _typed_unknown_snapshot(*, revision: int = 44) -> OperatorSnapshot:
    snapshot = _typed_ready_snapshot(revision=revision)
    readiness = ReadinessSummary(
        snapshot.cut,
        SummaryStatus(
            OperatorPresentationState.CAUTION,
            1.0,
            0.0,
            ("readiness_not_ready",),
            "Backend readiness authority",
        ),
        ReadinessTruth.UNKNOWN,
        (),
        SafetyLifecycle.UNKNOWN,
    )
    return replace(snapshot, readiness=readiness)


# ----------------------------------------------------------------------
# Host wiring — connection state
# ----------------------------------------------------------------------


def test_keithley_overlay_receives_connection_state_on_open():
    _app()
    w = MainWindowV2()
    try:
        # Simulate a recent reading — overlay should open as connected.
        w._last_reading_time = time.monotonic()
        w._ensure_overlay("source")
        assert w._keithley_panel is not None
        # Visible contract: connected → emergency button enabled on both channels.
        assert w._keithley_panel._smua_block._emergency_btn.isEnabled() is True
        assert w._keithley_panel._smub_block._emergency_btn.isEnabled() is True
    finally:
        _stop_timers(w)


def test_keithley_overlay_receives_disconnection_on_open_with_no_readings():
    _app()
    w = MainWindowV2()
    try:
        # Cold-start: _last_reading_time == 0.0 — overlay should open disconnected.
        w._ensure_overlay("source")
        assert w._keithley_panel is not None
        # Visible contract: disconnected → emergency button disabled on both channels.
        assert w._keithley_panel._smua_block._emergency_btn.isEnabled() is False
        assert w._keithley_panel._smub_block._emergency_btn.isEnabled() is False
    finally:
        _stop_timers(w)


def test_keithley_overlay_receives_connection_state_via_tick():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("source")
        # Simulate recent data → tick flips connected to True.
        w._last_reading_time = time.monotonic()
        w._tick_status()
        # Visible contract: connected → emergency button enabled.
        assert w._keithley_panel._smua_block._emergency_btn.isEnabled() is True
        # Advance silence past the 3 s threshold → tick flips to False.
        w._last_reading_time = time.monotonic() - 10.0
        w._tick_status()
        # Visible contract: disconnected → emergency button disabled.
        assert w._keithley_panel._smua_block._emergency_btn.isEnabled() is False
    finally:
        _stop_timers(w)


# ----------------------------------------------------------------------
# Host wiring — safety state
# ----------------------------------------------------------------------


def test_current_typed_interlock_is_warning_only_on_lazy_open(
    live_zmq_bridge: ZmqBridge,
) -> None:
    _app()
    w = MainWindowV2(bridge=live_zmq_bridge)
    try:
        assert live_zmq_bridge.bridge_instance_id is not None
        w._latest_experiment_status = {"active_experiment": {"experiment_id": "exp-1"}}
        w.render_operator_snapshot(_typed_interlock_snapshot())
        assert w._keithley_panel is None

        w._last_reading_time = time.monotonic()
        w._ensure_overlay("source")
        panel = w._keithley_panel
        assert panel is not None
        panel._smua_block.apply_state("off")
        panel._update_both_buttons_enablement()

        assert w._current_keithley_safety_gate()[0] is False
        assert panel._safety_ready is False
        assert panel._smua_block._start_btn.isEnabled()
        assert panel._smua_block._p_spin.isEnabled()
        assert panel._smua_block._v_spin.isEnabled()
        assert panel._smua_block._i_spin.isEnabled()
        assert panel._smua_block._emergency_btn.isEnabled()
        assert "ПРЕДУПРЕЖДЕНИЕ" in panel._gate_reason_label.text()
        assert "Interlock stop_source: detector_warmup" in panel._gate_reason_label.text()
        assert "заблокировано" not in panel._gate_reason_label.text()
    finally:
        _stop_timers(w)


def test_unknown_typed_safety_authority_disables_start_and_parameters(
    live_zmq_bridge: ZmqBridge,
) -> None:
    _app()
    w = MainWindowV2(bridge=live_zmq_bridge)
    try:
        w._latest_experiment_status = {"active_experiment": {"experiment_id": "exp-1"}}
        w._last_reading_time = time.monotonic()
        w._ensure_overlay("source")
        panel = w._keithley_panel
        assert panel is not None
        panel._smua_block.apply_state("off")

        w.render_operator_snapshot(_typed_unknown_snapshot())

        assert panel._safety_gate_cause is SafetyGateCause.AUTHORITY_UNAVAILABLE
        assert not panel._smua_block._start_btn.isEnabled()
        assert not panel._smua_block._p_spin.isEnabled()
        assert not panel._smua_block._v_spin.isEnabled()
        assert not panel._smua_block._i_spin.isEnabled()
        assert "Управление заблокировано" in panel._gate_reason_label.text()
    finally:
        _stop_timers(w)


def test_transport_stale_typed_safety_stays_unavailable_on_lazy_open(
    live_zmq_bridge: ZmqBridge,
) -> None:
    _app()
    w = MainWindowV2(bridge=live_zmq_bridge)
    store = OperatorSnapshotStore()
    try:
        w._latest_experiment_status = {"active_experiment": {"experiment_id": "exp-1"}}
        store.accept_snapshot(_typed_ready_snapshot())
        stale = store.observe_transport(connected=True, transport_age_s=11.0, stale_after_s=10.0)
        w.render_operator_snapshot(stale)
        assert w._keithley_panel is None

        w._last_reading_time = time.monotonic()
        w._ensure_overlay("source")
        panel = w._keithley_panel
        assert panel is not None
        panel._smua_block.apply_state("off")

        assert panel._safety_gate_cause is SafetyGateCause.AUTHORITY_UNAVAILABLE
        assert not panel._smua_block._start_btn.isEnabled()
        assert not panel._smua_block._p_spin.isEnabled()
        assert "Управление заблокировано" in panel._gate_reason_label.text()
    finally:
        _stop_timers(w)


def test_legacy_safe_off_cannot_promote_unavailable_typed_authority(
    live_zmq_bridge: ZmqBridge,
) -> None:
    _app()
    w = MainWindowV2(bridge=live_zmq_bridge)
    store = OperatorSnapshotStore()
    try:
        assert live_zmq_bridge.bridge_instance_id is not None
        w._latest_experiment_status = {"active_experiment": {"experiment_id": "exp-1"}}
        w._last_reading_time = time.monotonic()
        w._ensure_overlay("source")
        panel = w._keithley_panel
        assert panel is not None
        panel._smua_block.apply_state("off")

        store.accept_snapshot(_typed_ready_snapshot())
        unavailable = store.observe_transport(connected=True, transport_age_s=11.0, stale_after_s=10.0)
        w.render_operator_snapshot(unavailable)

        assert w._accepted_safety_bridge_instance_id == live_zmq_bridge.bridge_instance_id
        assert w._accepted_safety_experiment_id == "exp-1"
        assert w._last_safety_gate_cause is SafetyGateCause.AUTHORITY_UNAVAILABLE

        w._dispatch_reading(
            _safety_reading(
                SafetyLifecycle.SAFE_OFF.value,
                "Interlock stop_source: detector_warmup",
                observed_at=datetime.now(UTC),
                bridge_id=live_zmq_bridge.bridge_instance_id,
                experiment_id="exp-1",
            )
        )

        assert w._last_safety_state == SafetyLifecycle.SAFE_OFF.value
        assert w._last_safety_gate_cause is SafetyGateCause.AUTHORITY_UNAVAILABLE
        assert panel._safety_gate_cause is SafetyGateCause.AUTHORITY_UNAVAILABLE
        assert not panel._smua_block._start_btn.isEnabled()
        assert not panel._smua_block._p_spin.isEnabled()
        assert not panel._smua_block._v_spin.isEnabled()
        assert not panel._smua_block._i_spin.isEnabled()
        assert panel._smua_block._emergency_btn.isEnabled()
    finally:
        _stop_timers(w)


def test_composer_shaped_interlock_uses_blocker_text_in_warning_and_start_receipt(
    live_zmq_bridge: ZmqBridge,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _app()
    w = MainWindowV2(bridge=live_zmq_bridge)
    captured: list[dict] = []

    class _FakeSignal:
        def connect(self, _slot) -> None:  # noqa: ANN001
            pass

    class _FakeWorker:
        def __init__(self, command: dict, parent=None) -> None:  # noqa: ANN001
            captured.append(command)
            self.finished = _FakeSignal()

        def start(self) -> None:
            pass

    import cryodaq.gui.shell.overlays.keithley_panel as panel_module

    monkeypatch.setattr(panel_module, "ZmqCommandWorker", _FakeWorker)
    try:
        w._latest_experiment_status = {"active_experiment": {"experiment_id": "exp-1"}}
        w._last_reading_time = time.monotonic()
        w._ensure_overlay("source")
        panel = w._keithley_panel
        assert panel is not None
        panel._smua_block.apply_state("off")

        w.render_operator_snapshot(_typed_interlock_snapshot())
        panel._smua_block._start_btn.click()

        actual_blocker = "Interlock stop_source: detector_warmup"
        assert actual_blocker in panel._gate_reason_label.text()
        assert "Backend readiness authority" not in panel._gate_reason_label.text()
        assert len(captured) == 1
        assert captured[0]["operator_warning_choice"]["warning"] == actual_blocker
    finally:
        _stop_timers(w)


@pytest.mark.parametrize(
    ("active_experiment", "start_enabled"),
    (("exp-1", True), ("different-experiment", False)),
)
def test_typed_interlock_only_warns_for_current_experiment_binding(
    active_experiment: str,
    start_enabled: bool,
    live_zmq_bridge: ZmqBridge,
) -> None:
    _app()
    w = MainWindowV2(bridge=live_zmq_bridge)
    try:
        w._latest_experiment_status = {"active_experiment": {"experiment_id": active_experiment}}
        w._last_reading_time = time.monotonic()
        w._ensure_overlay("source")
        panel = w._keithley_panel
        assert panel is not None
        panel._smua_block.apply_state("off")

        w.render_operator_snapshot(_typed_interlock_snapshot())

        assert panel._safety_ready is False
        assert panel._smua_block._start_btn.isEnabled() is start_enabled
        if start_enabled:
            assert "ПРЕДУПРЕЖДЕНИЕ" in panel._gate_reason_label.text()
        else:
            assert "Управление заблокировано" in panel._gate_reason_label.text()
    finally:
        _stop_timers(w)


def test_current_safe_off_telemetry_keeps_interlock_as_warning(
    live_zmq_bridge: ZmqBridge,
) -> None:
    _app()
    w = MainWindowV2(bridge=live_zmq_bridge)
    store = OperatorSnapshotStore()
    try:
        assert live_zmq_bridge.bridge_instance_id is not None
        w._latest_experiment_status = {"active_experiment": {"experiment_id": "exp-1"}}
        w._last_reading_time = time.monotonic()
        w._ensure_overlay("source")
        panel = w._keithley_panel
        assert panel is not None
        panel._smua_block.apply_state("off")
        w.render_operator_snapshot(store.accept_snapshot(_typed_ready_snapshot()))

        w._dispatch_reading(
            _safety_reading(
                SafetyLifecycle.SAFE_OFF.value,
                "Interlock stop_source: detector_warmup",
                bridge_id=live_zmq_bridge.bridge_instance_id,
            )
        )

        assert w._current_keithley_safety_gate()[0] is False
        assert panel._safety_ready is False
        assert panel._smua_block._start_btn.isEnabled()
        assert "ПРЕДУПРЕЖДЕНИЕ" in panel._gate_reason_label.text()
        assert "Interlock stop_source: detector_warmup" in panel._gate_reason_label.text()
    finally:
        _stop_timers(w)


def test_keithley_overlay_receives_safety_state_via_dispatch():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("source")
        w._dispatch_reading(_safety_reading("fault_latched", "test reason"))
        assert w._keithley_panel._safety_ready is False
        assert "test reason" in w._keithley_panel._gate_reason_label.text()
        assert "Управление заблокировано" in w._keithley_panel._gate_reason_label.text()
    finally:
        _stop_timers(w)


def test_exact_internal_source_state_event_updates_real_panel():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("source")
        block = w._keithley_panel._smua_block
        assert block._channel_state == "unknown"

        # A queued event cannot resurrect truth while the host is disconnected.
        w._dispatch_reading(_source_state_reading("smua", "on"))
        assert block._channel_state == "unknown"

        # Once the host has a live link, the exact internal state channel is
        # authoritative for this connection generation.
        w._keithley_panel.set_connected(True)
        w._dispatch_reading(_source_state_reading("smua", "on"))
        assert block._channel_state == "on"

        w._dispatch_reading(_source_state_reading("smua_extra", "fault"))
        assert block._channel_state == "on"
    finally:
        _stop_timers(w)


@pytest.mark.parametrize(
    "invalid_bridge_id",
    [
        "A" * 32,
        "g" * 32,
        "a" * 31,
        "a" * 33,
        "a" * 31 + "\n",
        b"a" * 32,
        True,
        None,
    ],
)
def test_noncanonical_bridge_identity_cannot_bind_typed_safety_authority(
    invalid_bridge_id: object,
) -> None:
    _app()
    bridge = ZmqBridge()
    bridge._bridge_instance_id = invalid_bridge_id
    w = MainWindowV2(bridge=bridge)
    try:
        w._ensure_overlay("source")
        assert w._current_bridge_instance_id() is None

        w._apply_operator_snapshot_safety(_typed_ready_snapshot())

        assert not w._typed_safety_ready
        assert w._accepted_safety_bridge_instance_id is None
        assert w._keithley_panel is not None
        assert not w._keithley_panel._safety_ready
        assert not w._keithley_panel._smua_block._start_btn.isEnabled()
        assert not w._keithley_panel._start_both_btn.isEnabled()
    finally:
        _stop_timers(w)


def test_ready_analytics_is_display_only_before_typed_authority(
    live_zmq_bridge: ZmqBridge,
) -> None:
    _app()
    w = MainWindowV2(bridge=live_zmq_bridge)
    try:
        assert live_zmq_bridge.bridge_instance_id is not None
        w._latest_experiment_status = {"active_experiment": {"experiment_id": "exp-1"}}
        w._ensure_overlay("source")
        w._last_reading_time = time.monotonic()
        w._tick_status()
        assert w._keithley_panel._connected is True

        w._dispatch_reading(
            _safety_reading(
                "ready",
                bridge_id=live_zmq_bridge.bridge_instance_id,
            )
        )

        assert w._keithley_panel._safety_ready is False
        assert w._keithley_panel._smua_block._start_btn.isEnabled() is False
        assert w._keithley_panel._start_both_btn.isEnabled() is False
        assert w._accepted_safety_bridge_instance_id is None
        assert w._accepted_safety_experiment_id is None
    finally:
        _stop_timers(w)


def test_ready_analytics_after_negative_cannot_restore_authority(
    live_zmq_bridge: ZmqBridge,
) -> None:
    _app()
    w = MainWindowV2(bridge=live_zmq_bridge)
    try:
        assert live_zmq_bridge.bridge_instance_id is not None
        w._ensure_overlay("source")
        w._last_reading_time = time.monotonic()
        w._tick_status()
        assert w._keithley_panel._connected is True

        observed = datetime.now(UTC) - timedelta(seconds=1)
        w._dispatch_reading(
            _safety_reading(
                "fault_latched",
                "negative evidence",
                observed_at=observed,
                bridge_id=live_zmq_bridge.bridge_instance_id,
            )
        )
        w._dispatch_reading(
            _safety_reading(
                "ready",
                observed_at=observed + timedelta(milliseconds=500),
                bridge_id=live_zmq_bridge.bridge_instance_id,
            )
        )

        assert w._keithley_panel._safety_ready is False
        assert w._current_keithley_safety_gate()[0] is False
    finally:
        _stop_timers(w)


def test_bridge_and_experiment_changes_never_create_telemetry_authority(
    live_zmq_bridge: ZmqBridge,
) -> None:
    _app()
    w = MainWindowV2(bridge=live_zmq_bridge)
    try:
        assert live_zmq_bridge.bridge_instance_id is not None
        w._latest_experiment_status = {"active_experiment": {"experiment_id": "exp-a"}}
        w._ensure_overlay("source")
        w._dispatch_reading(_safety_reading("ready", bridge_id=live_zmq_bridge.bridge_instance_id))
        assert w._keithley_panel._safety_ready is False

        live_zmq_bridge._bridge_instance_id = "f" * 32
        w._on_experiment_status_received(
            {
                "active_experiment": {"experiment_id": "exp-b"},
                "phases": [],
            }
        )
        w._last_reading_time = time.monotonic()
        w._tick_status()
        w._dispatch_reading(_safety_reading("ready", bridge_id=live_zmq_bridge.bridge_instance_id))

        assert w._keithley_panel._safety_ready is False
        assert w._accepted_safety_bridge_instance_id is None
        assert w._accepted_safety_experiment_id is None
    finally:
        _stop_timers(w)


def test_negative_analytics_revokes_typed_ready(
    live_zmq_bridge: ZmqBridge,
) -> None:
    _app()
    w = MainWindowV2(bridge=live_zmq_bridge)
    store = OperatorSnapshotStore()
    try:
        assert live_zmq_bridge.bridge_instance_id is not None
        w._latest_experiment_status = {"active_experiment": {"experiment_id": "exp-1"}}
        w._ensure_overlay("source")
        w.render_operator_snapshot(store.accept_snapshot(_typed_ready_snapshot()))
        assert w._keithley_panel._safety_ready is True

        w._dispatch_reading(
            _safety_reading(
                "fault_latched",
                "negative telemetry",
                bridge_id=live_zmq_bridge.bridge_instance_id,
            )
        )

        assert w._keithley_panel._safety_ready is False
        assert w._current_keithley_safety_gate()[0] is False
    finally:
        _stop_timers(w)


@pytest.mark.parametrize("state_name", ["run_permitted", "running"])
def test_active_analytics_lifecycle_revokes_typed_ready(
    state_name: str,
    live_zmq_bridge: ZmqBridge,
) -> None:
    """Active-source telemetry is blocking evidence, never READY authority."""

    _app()
    w = MainWindowV2(bridge=live_zmq_bridge)
    store = OperatorSnapshotStore()
    try:
        assert live_zmq_bridge.bridge_instance_id is not None
        w._latest_experiment_status = {"active_experiment": {"experiment_id": "exp-1"}}
        w._ensure_overlay("source")
        w.render_operator_snapshot(store.accept_snapshot(_typed_ready_snapshot()))
        assert w._keithley_panel._safety_ready is True

        w._dispatch_reading(
            _safety_reading(
                state_name,
                bridge_id=live_zmq_bridge.bridge_instance_id,
            )
        )

        assert w._last_safety_state == state_name
        assert w._typed_safety_ready is False
        assert w._accepted_safety_bridge_instance_id is None
        assert w._accepted_safety_experiment_id is None
        assert w._keithley_panel._safety_ready is False
        assert w._current_keithley_safety_gate()[0] is False
    finally:
        _stop_timers(w)


@pytest.mark.parametrize(
    ("replay_mode", "expected_mode", "opposite_mode"),
    [
        (False, SnapshotMode.LIVE, SnapshotMode.REPLAY),
        (True, SnapshotMode.REPLAY, SnapshotMode.LIVE),
    ],
)
def test_main_window_never_renders_or_authorizes_opposite_runtime_domain(
    replay_mode: bool,
    expected_mode: SnapshotMode,
    opposite_mode: SnapshotMode,
    live_zmq_bridge: ZmqBridge,
) -> None:
    _app()
    w = MainWindowV2(bridge=live_zmq_bridge, replay_mode=replay_mode)
    try:
        assert live_zmq_bridge.bridge_instance_id is not None
        w._latest_experiment_status = {"active_experiment": {"experiment_id": "exp-1"}}
        expected = _typed_ready_snapshot(revision=42, mode=expected_mode)
        w.render_operator_snapshot(expected)
        rendered = w._operator_display.snapshot
        assert rendered is expected

        opposite = _typed_ready_snapshot(revision=999, mode=opposite_mode)
        w.render_operator_snapshot(opposite)

        assert w._operator_display.snapshot is rendered
        assert w._overview_panel._authority_valid is False
        assert w._typed_safety_ready is False
        assert w._accepted_safety_bridge_instance_id is None
        assert w._current_keithley_safety_gate()[0] is False
    finally:
        _stop_timers(w)


def test_same_cut_and_analytics_ready_cannot_restore_but_newer_typed_cut_can(
    live_zmq_bridge: ZmqBridge,
) -> None:
    _app()
    w = MainWindowV2(bridge=live_zmq_bridge)
    store = OperatorSnapshotStore()
    try:
        assert live_zmq_bridge.bridge_instance_id is not None
        w._latest_experiment_status = {"active_experiment": {"experiment_id": "exp-1"}}
        w._ensure_overlay("source")
        original = store.accept_snapshot(_typed_ready_snapshot(revision=42))
        w.render_operator_snapshot(original)
        assert w._keithley_panel._safety_ready is True

        w._dispatch_reading(
            _safety_reading(
                "fault_latched",
                "negative telemetry",
                bridge_id=live_zmq_bridge.bridge_instance_id,
            )
        )
        assert w._keithley_panel._safety_ready is False

        w.render_operator_snapshot(original)
        w._dispatch_reading(_safety_reading("ready", bridge_id=live_zmq_bridge.bridge_instance_id))
        assert w._keithley_panel._safety_ready is False

        newer = store.accept_snapshot(_typed_ready_snapshot(revision=43))
        w.render_operator_snapshot(newer)
        assert w._keithley_panel._safety_ready is True
    finally:
        _stop_timers(w)


def test_foreign_ready_destroys_prior_legacy_replay_binding(
    live_zmq_bridge: ZmqBridge,
) -> None:
    _app()
    w = MainWindowV2(bridge=live_zmq_bridge)
    try:
        assert live_zmq_bridge.bridge_instance_id is not None
        w._ensure_overlay("source")
        observed = datetime.now(UTC) - timedelta(seconds=1)
        w._dispatch_reading(
            _safety_reading(
                "fault_latched",
                observed_at=observed,
                bridge_id=live_zmq_bridge.bridge_instance_id,
            )
        )
        w._dispatch_reading(
            _safety_reading(
                "ready",
                observed_at=observed + timedelta(milliseconds=500),
                bridge_id="f" * 32,
            )
        )

        assert w._keithley_panel._safety_ready is False
        assert w._accepted_safety_bridge_instance_id is None
        assert w._current_keithley_safety_gate()[0] is False
    finally:
        _stop_timers(w)


def test_typed_snapshot_staleness_revokes_gate_and_legacy_ready_cannot_resurrect_it(
    live_zmq_bridge: ZmqBridge,
) -> None:
    _app()
    w = MainWindowV2(bridge=live_zmq_bridge)
    store = OperatorSnapshotStore()
    try:
        assert live_zmq_bridge.bridge_instance_id is not None
        w._latest_experiment_status = {"active_experiment": {"experiment_id": "exp-1"}}
        w._ensure_overlay("source")
        ready = store.accept_snapshot(_typed_ready_snapshot())
        w.render_operator_snapshot(ready)
        assert w._keithley_panel._safety_ready is True

        w._apply_operator_snapshot_safety(object())
        assert w._keithley_panel._safety_ready is False

        stale = store.observe_transport(connected=True, transport_age_s=11.0, stale_after_s=10.0)
        w._apply_operator_snapshot_safety(stale)
        assert w._keithley_panel._safety_ready is False

        w._dispatch_reading(_safety_reading("ready", bridge_id=live_zmq_bridge.bridge_instance_id))
        assert w._keithley_panel._safety_ready is False
        assert w._last_safety_state == SafetyLifecycle.UNKNOWN.value
    finally:
        _stop_timers(w)


def test_malformed_typed_snapshot_permanently_disables_legacy_ready_fallback(
    live_zmq_bridge: ZmqBridge,
) -> None:
    _app()
    w = MainWindowV2(bridge=live_zmq_bridge)
    try:
        assert live_zmq_bridge.bridge_instance_id is not None
        w._ensure_overlay("source")

        w._apply_operator_snapshot_safety(object())
        w._dispatch_reading(_safety_reading("ready", bridge_id=live_zmq_bridge.bridge_instance_id))

        assert w._typed_safety_authority_seen is True
        assert w._keithley_panel._safety_ready is False
        assert w._current_keithley_safety_gate()[0] is False
    finally:
        _stop_timers(w)


def test_keithley_overlay_safety_replay_on_lazy_open():
    _app()
    w = MainWindowV2()
    try:
        # Dispatch safety reading BEFORE overlay is constructed.
        assert w._keithley_panel is None
        w._dispatch_reading(_safety_reading("fault_latched", "stale sensor"))
        # Cache populated but overlay still lazy.
        assert w._last_safety_state == "fault_latched"
        assert w._last_safety_reason == "stale sensor"
        assert w._keithley_panel is None

        # Open overlay — cached state should be replayed.
        w._ensure_overlay("source")
        assert w._keithley_panel is not None
        assert w._keithley_panel._safety_ready is False
        assert "stale sensor" in w._keithley_panel._gate_reason_label.text()
    finally:
        _stop_timers(w)


def test_keithley_overlay_channel_state_replay_on_lazy_open(
    live_zmq_bridge: ZmqBridge,
) -> None:
    _app()
    w = MainWindowV2(bridge=live_zmq_bridge)
    store = OperatorSnapshotStore()
    try:
        assert live_zmq_bridge.bridge_instance_id is not None
        w._latest_experiment_status = {"active_experiment": {"experiment_id": "exp-1"}}
        w._last_reading_time = time.monotonic()
        w.render_operator_snapshot(store.accept_snapshot(_typed_ready_snapshot()))

        assert w._keithley_panel is None
        w._dispatch_reading(_source_state_reading("smua", "off"))
        assert w._keithley_panel is None

        w._ensure_overlay("source")

        assert w._keithley_panel is not None
        block = w._keithley_panel._smua_block
        assert block._channel_state == "off"
        assert block._start_btn.isEnabled() is True
    finally:
        _stop_timers(w)


def test_keithley_overlay_does_not_replay_state_from_replaced_engine_incarnation(
    live_zmq_bridge: ZmqBridge,
) -> None:
    _app()
    w = MainWindowV2(bridge=live_zmq_bridge)
    try:
        assert live_zmq_bridge.bridge_instance_id is not None
        w._on_experiment_status_received(
            {
                "active_experiment": {"experiment_id": "exp-1"},
                "phases": [],
            }
        )
        w._last_reading_time = time.monotonic()
        w._dispatch_reading(_source_state_reading("smua", "off"))

        # The experiment is unchanged, but the bridge now represents a new
        # engine incarnation. Opening the panel must not make the dead
        # incarnation's OFF observation look current.
        w.invalidate_engine_producer()
        live_zmq_bridge._bridge_instance_id = "f" * 32
        w._ensure_overlay("source")

        assert w._keithley_panel is not None
        block = w._keithley_panel._smua_block
        assert block._channel_state == "unknown"
        assert block._start_btn.isEnabled() is False
    finally:
        _stop_timers(w)


def test_keithley_overlay_keeps_state_when_experiment_starts_before_lazy_open(
    live_zmq_bridge: ZmqBridge,
) -> None:
    _app()
    w = MainWindowV2(bridge=live_zmq_bridge)
    store = OperatorSnapshotStore()
    try:
        assert live_zmq_bridge.bridge_instance_id is not None
        w._last_reading_time = time.monotonic()
        w._dispatch_reading(_source_state_reading("smua", "off"))

        # Starting an experiment does not create a new engine incarnation and
        # SafetyManager does not republish the unchanged OFF state here.
        w._on_experiment_status_received(
            {
                "active_experiment": {"experiment_id": "exp-1"},
                "phases": [],
            }
        )
        w.render_operator_snapshot(store.accept_snapshot(_typed_ready_snapshot()))
        w._ensure_overlay("source")

        assert w._keithley_panel is not None
        block = w._keithley_panel._smua_block
        assert block._channel_state == "off"
        assert block._start_btn.isEnabled() is True
    finally:
        _stop_timers(w)


def test_keithley_overlay_replays_cached_state_when_measurement_flow_recovers(
    live_zmq_bridge: ZmqBridge,
) -> None:
    _app()
    w = MainWindowV2(bridge=live_zmq_bridge)
    store = OperatorSnapshotStore()
    try:
        assert live_zmq_bridge.bridge_instance_id is not None
        w._latest_experiment_status = {"active_experiment": {"experiment_id": "exp-1"}}
        w.render_operator_snapshot(store.accept_snapshot(_typed_ready_snapshot()))
        w._dispatch_reading(_source_state_reading("smua", "off"))

        # No measurement has arrived, so lazy-open is honestly disconnected.
        # The panel must remain fail-closed until measurement flow is live.
        w._ensure_overlay("source")
        assert w._keithley_panel is not None
        block = w._keithley_panel._smua_block
        assert block._channel_state == "unknown"
        assert block._start_btn.isEnabled() is False

        # Drive the real shell ingress + status-tick path. The source-state
        # producer is event-driven and emits nothing on this transition.
        w._dispatch_reading(_measurement_reading())
        w._tick_status()

        assert block._channel_state == "off"
        assert block._start_btn.isEnabled() is True
    finally:
        _stop_timers(w)


@pytest.mark.parametrize("cached_state", ["on", "off"])
def test_keithley_overlay_revokes_cached_source_state_at_measurement_gap_recovery(
    cached_state: str,
    live_zmq_bridge: ZmqBridge,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _app()
    w = MainWindowV2(bridge=live_zmq_bridge)
    try:
        clock = _controlled_measurement_clock(monkeypatch, w)
        w._ensure_overlay("source")
        assert w._keithley_panel is not None
        block = w._keithley_panel._smua_block
        clock[0] = 101.0
        w._dispatch_reading(_source_state_reading("smua", cached_state))
        assert block._channel_state == cached_state
        clock[0] = 102.0
        w._dispatch_reading(_measurement_reading())

        # The per-channel transition is missed while measurement delivery is
        # silent. The first generic measurement must reveal the crossed gap
        # before it overwrites the old ingress timestamp.
        clock[0] = 112.0
        w._dispatch_reading(_measurement_reading())
        w._tick_status()

        assert block._channel_state == "unknown"
        assert block._start_btn.isEnabled() is False
    finally:
        _stop_timers(w)


def test_keithley_overlay_resynchronizes_off_from_newer_ready_cut_after_gap(
    live_zmq_bridge: ZmqBridge,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _app()
    w = MainWindowV2(bridge=live_zmq_bridge)
    store = OperatorSnapshotStore()
    try:
        w._latest_experiment_status = {"active_experiment": {"experiment_id": "exp-1"}}
        clock = _controlled_measurement_clock(monkeypatch, w)
        prior_ready = _typed_ready_snapshot(
            revision=42,
            observed_at=datetime.now(UTC) - timedelta(seconds=20),
        )
        w.render_operator_snapshot(store.accept_snapshot(prior_ready))
        w._ensure_overlay("source")
        assert w._keithley_panel is not None
        block = w._keithley_panel._smua_block
        clock[0] = 101.0
        w._dispatch_reading(_source_state_reading("smua", "on"))
        assert block._channel_state == "on"
        clock[0] = 102.0
        w._dispatch_reading(_measurement_reading())

        clock[0] = 112.0
        w._dispatch_reading(_measurement_reading())
        w._tick_status()
        assert block._channel_state == "unknown"

        # Re-delivering the pre-gap READY cut is retained presentation, not
        # revalidation: its Safety observation predates the last-measurement
        # boundary even though it is delivered again after recovery.
        w.render_operator_snapshot(prior_ready)
        assert block._channel_state == "unknown"

        # A cut received after the gap is exact READY. OperatorSnapshot's
        # constructor/composer contract makes READY impossible without
        # current verified-OFF evidence for both channels.
        fresh_ready = _typed_ready_snapshot(
            revision=43,
            observed_at=datetime.now(UTC),
        )
        w.render_operator_snapshot(store.accept_snapshot(fresh_ready))

        assert block._channel_state == "off"
        assert block._start_btn.isEnabled() is True
    finally:
        _stop_timers(w)


@pytest.mark.parametrize("newer_state", ["on", "fault"])
def test_ready_resync_preserves_a_newer_channel_observation(
    newer_state: str,
    live_zmq_bridge: ZmqBridge,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An older cross-topic READY cut cannot erase newer active/fault truth."""

    _app()
    w = MainWindowV2(bridge=live_zmq_bridge)
    store = OperatorSnapshotStore()
    try:
        w._latest_experiment_status = {"active_experiment": {"experiment_id": "exp-1"}}
        clock = _controlled_measurement_clock(monkeypatch, w)
        w._ensure_overlay("source")
        clock[0] = 101.0
        w._dispatch_reading(_measurement_reading())
        gap_boundary = w._last_measurement_received_at
        assert gap_boundary is not None

        clock[0] = 111.0
        w._dispatch_reading(_measurement_reading())
        w._tick_status()
        block_a = w._keithley_panel._smua_block
        block_b = w._keithley_panel._smub_block
        assert block_a._channel_state == "unknown"

        channel_observed_at = datetime.now(UTC)
        w._dispatch_reading(_source_state_reading("smua", newer_state, observed_at=channel_observed_at))
        delayed_ready = _typed_ready_snapshot(
            revision=43,
            observed_at=max(
                gap_boundary + timedelta(microseconds=1),
                channel_observed_at - timedelta(milliseconds=1),
            ),
        )
        w.render_operator_snapshot(store.accept_snapshot(delayed_ready))

        assert block_a._channel_state == newer_state
        assert block_b._channel_state == "off"
    finally:
        _stop_timers(w)


def test_unknown_source_observation_remains_pending_for_newer_ready_recovery(
    live_zmq_bridge: ZmqBridge,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UNKNOWN is visible evidence, but it cannot satisfy actionable recovery."""

    _app()
    w = MainWindowV2(bridge=live_zmq_bridge)
    store = OperatorSnapshotStore()
    try:
        w._latest_experiment_status = {"active_experiment": {"experiment_id": "exp-1"}}
        clock = _controlled_measurement_clock(monkeypatch, w)
        w._ensure_overlay("source")
        clock[0] = 101.0
        w._dispatch_reading(_measurement_reading())
        clock[0] = 111.0
        w._dispatch_reading(_measurement_reading())
        w._tick_status()

        w._dispatch_reading(_source_state_reading("smub", "off"))
        w._dispatch_reading(_source_state_reading("smua", "unknown"))
        block = w._keithley_panel._smua_block
        assert block._channel_state == "unknown"

        w.render_operator_snapshot(
            store.accept_snapshot(_typed_ready_snapshot(revision=43, observed_at=datetime.now(UTC)))
        )

        assert block._channel_state == "off"
        assert block._start_btn.isEnabled() is True
    finally:
        _stop_timers(w)


def test_ready_cut_for_previous_experiment_cannot_authorize_or_resynchronize_source(
    live_zmq_bridge: ZmqBridge,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The experiment binding is checked before either READY side effect."""

    _app()
    w = MainWindowV2(bridge=live_zmq_bridge)
    store = OperatorSnapshotStore()
    try:
        w._latest_experiment_status = {"active_experiment": {"experiment_id": "exp-new"}}
        clock = _controlled_measurement_clock(monkeypatch, w)
        w._ensure_overlay("source")
        clock[0] = 101.0
        w._dispatch_reading(_measurement_reading())
        clock[0] = 111.0
        w._dispatch_reading(_measurement_reading())
        w._tick_status()
        block = w._keithley_panel._smua_block
        assert block._channel_state == "unknown"

        w.render_operator_snapshot(
            store.accept_snapshot(
                _typed_ready_snapshot(
                    revision=43,
                    observed_at=datetime.now(UTC),
                    experiment_id="exp-old",
                )
            )
        )

        assert w._keithley_panel._safety_ready is False
        assert block._channel_state == "unknown"
        assert block._start_btn.isEnabled() is False
    finally:
        _stop_timers(w)


def test_newer_nonready_snapshot_revokes_off_when_on_publication_is_lost(
    live_zmq_bridge: ZmqBridge,
) -> None:
    """Periodic typed cuts cover isolated loss of the best-effort state topic."""

    _app()
    w = MainWindowV2(bridge=live_zmq_bridge)
    store = OperatorSnapshotStore()
    try:
        w._latest_experiment_status = {"active_experiment": {"experiment_id": "exp-1"}}
        w._last_reading_time = time.monotonic()
        first_ready = _typed_ready_snapshot(revision=42)
        w.render_operator_snapshot(store.accept_snapshot(first_ready))
        w._dispatch_reading(_source_state_reading("smua", "off"))
        w._ensure_overlay("source")
        block = w._keithley_panel._smua_block
        assert block._channel_state == "off"
        assert block._start_btn.isEnabled() is True

        # Unrelated producer measurements continue normally; no generic-flow
        # gap can reveal the independently dropped source-state publication.
        w._dispatch_reading(_measurement_reading())
        w._tick_status()
        assert w._keithley_panel._connected is True
        assert block._channel_state == "off"

        # The ON publication is deliberately absent: only the next periodic
        # authoritative cut reveals that retained OFF is no longer covered.
        w.render_operator_snapshot(
            store.accept_snapshot(
                _typed_ready_snapshot(
                    revision=43,
                    observed_at=datetime.now(UTC),
                    safety_ready=False,
                )
            )
        )

        assert block._channel_state == "unknown"
        assert block._start_btn.isEnabled() is False
    finally:
        _stop_timers(w)


def test_ready_derived_off_is_revoked_by_the_next_measurement_gap(
    live_zmq_bridge: ZmqBridge,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A READY projection is presentation, not a producer receipt for later gaps."""

    _app()
    w = MainWindowV2(bridge=live_zmq_bridge)
    store = OperatorSnapshotStore()
    try:
        w._latest_experiment_status = {"active_experiment": {"experiment_id": "exp-1"}}
        clock = _controlled_measurement_clock(monkeypatch, w)
        w._ensure_overlay("source")
        clock[0] = 101.0
        w._dispatch_reading(_measurement_reading())

        clock[0] = 109.0
        ready_during_first_gap = _typed_ready_snapshot(
            revision=43,
            observed_at=datetime.now(UTC),
        )
        w.render_operator_snapshot(store.accept_snapshot(ready_during_first_gap))

        clock[0] = 111.0
        w._dispatch_reading(_measurement_reading())
        w._tick_status()
        block = w._keithley_panel._smua_block
        assert block._channel_state == "off"

        # No new source observation or READY cut follows the one recovered
        # measurement. The second gap must revoke the derived OFF again.
        clock[0] = 121.0
        w._dispatch_reading(_measurement_reading())
        w._tick_status()

        assert block._channel_state == "unknown"
        assert block._start_btn.isEnabled() is False
    finally:
        _stop_timers(w)


def test_keithley_overlay_rejects_ready_cut_observed_before_gap_boundary(
    live_zmq_bridge: ZmqBridge,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _app()
    w = MainWindowV2(bridge=live_zmq_bridge)
    store = OperatorSnapshotStore()
    try:
        w._latest_experiment_status = {"active_experiment": {"experiment_id": "exp-1"}}
        clock = _controlled_measurement_clock(monkeypatch, w)
        w._ensure_overlay("source")
        assert w._keithley_panel is not None
        block = w._keithley_panel._smua_block
        clock[0] = 101.0
        w._dispatch_reading(_source_state_reading("smua", "on"))
        clock[0] = 102.0
        w._dispatch_reading(_measurement_reading())
        assert w._last_measurement_received_at is not None
        pre_gap_observation = w._last_measurement_received_at - timedelta(seconds=1)

        clock[0] = 112.0
        w._dispatch_reading(_measurement_reading())
        w._tick_status()
        assert block._channel_state == "unknown"

        # Allocation/delivery can be newer while the Safety observation is
        # still pre-gap. Only the observation time carries source evidence.
        delayed_ready = _typed_ready_snapshot(
            revision=43,
            observed_at=pre_gap_observation,
            received_at=datetime.now(UTC),
        )
        w.render_operator_snapshot(store.accept_snapshot(delayed_ready))

        assert block._channel_state == "unknown"
        assert block._start_btn.isEnabled() is False
    finally:
        _stop_timers(w)


def test_keithley_overlay_uses_ready_cut_received_during_gap_on_recovery(
    live_zmq_bridge: ZmqBridge,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _app()
    w = MainWindowV2(bridge=live_zmq_bridge)
    store = OperatorSnapshotStore()
    try:
        w._latest_experiment_status = {"active_experiment": {"experiment_id": "exp-1"}}
        clock = _controlled_measurement_clock(monkeypatch, w)
        w._ensure_overlay("source")
        assert w._keithley_panel is not None
        block = w._keithley_panel._smua_block
        clock[0] = 101.0
        w._dispatch_reading(_source_state_reading("smua", "on"))
        clock[0] = 102.0
        w._dispatch_reading(_measurement_reading())

        # Safety reaches a coherent verified-OFF READY cut after the last
        # generic measurement but before measurement delivery recovers.
        clock[0] = 110.0
        ready_during_gap = _typed_ready_snapshot(
            revision=43,
            observed_at=datetime.now(UTC),
        )
        w.render_operator_snapshot(store.accept_snapshot(ready_during_gap))
        assert block._channel_state == "on"

        clock[0] = 112.0
        w._dispatch_reading(_measurement_reading())
        w._tick_status()

        assert block._channel_state == "off"
        assert block._start_btn.isEnabled() is True
    finally:
        _stop_timers(w)


def test_keithley_overlay_retains_channel_state_received_during_gap_before_detection(
    live_zmq_bridge: ZmqBridge,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _app()
    w = MainWindowV2(bridge=live_zmq_bridge)
    try:
        clock = _controlled_measurement_clock(monkeypatch, w)
        w._ensure_overlay("source")
        assert w._keithley_panel is not None
        block = w._keithley_panel._smua_block
        clock[0] = 101.0
        w._dispatch_reading(_source_state_reading("smua", "on"))
        clock[0] = 102.0
        w._dispatch_reading(_measurement_reading())

        # The exact OFF observation arrives after the last generic reading but
        # before the silence is old enough for the status tick to declare a
        # gap. Recovery must retain this post-boundary evidence.
        clock[0] = 110.0
        w._dispatch_reading(_source_state_reading("smua", "off"))
        clock[0] = 112.0
        w._dispatch_reading(_measurement_reading())
        w._tick_status()

        assert block._channel_state == "off"
        assert block._start_btn.isEnabled() is False  # Safety remains fail-closed.
    finally:
        _stop_timers(w)


def test_watchdog_transport_replacement_keeps_source_state_and_start_available() -> None:
    from cryodaq.launcher import LauncherWindow

    _app()
    bridge = _TransportRestartBridge()
    w = MainWindowV2(bridge=bridge)
    store = OperatorSnapshotStore()
    try:
        w._latest_experiment_status = {"active_experiment": {"experiment_id": "exp-1"}}
        w._last_reading_time = time.monotonic()
        w.render_operator_snapshot(store.accept_snapshot(_typed_ready_snapshot(revision=42)))
        w._dispatch_reading(_source_state_reading("smua", "off"))
        w._ensure_overlay("source")
        block = w._keithley_panel._smua_block
        assert block._start_btn.isEnabled() is True

        launcher = SimpleNamespace(
            _bridge=bridge,
            _bridge_watchdog_generation=0,
            _bridge_restart_fault=False,
            _bridge_restart_hold=False,
            _invalidate_descriptor_transport=w.invalidate_descriptor_transport,
            _soak_bridge_handshake=None,
            _replay_source=None,
            _watchdog_shutdown_bridge_factory=_new_transport_shutdown_standby,
        )
        assert LauncherWindow._replace_bridge_from_watchdog(launcher, reason="heartbeat") is True

        # The watchdog replaced only the transport. A fresh typed Safety cut
        # may re-bind to it, while the unchanged engine's retained OFF remains
        # the source-state fact that permits Start.
        w._tick_status()
        w.render_operator_snapshot(store.accept_snapshot(_typed_ready_snapshot(revision=43)))

        assert block._channel_state == "off"
        assert block._start_btn.isEnabled() is True
    finally:
        _stop_timers(w)


def test_cached_replay_cannot_reconcile_unknown_start_outcome(
    monkeypatch,
    live_zmq_bridge: ZmqBridge,
) -> None:
    _app()
    w = MainWindowV2(bridge=live_zmq_bridge)
    store = OperatorSnapshotStore()
    try:
        w._latest_experiment_status = {"active_experiment": {"experiment_id": "exp-1"}}
        w._last_reading_time = time.monotonic()
        w.render_operator_snapshot(store.accept_snapshot(_typed_ready_snapshot(revision=42)))
        w._dispatch_reading(_source_state_reading("smua", "off"))
        w._ensure_overlay("source")
        block = w._keithley_panel._smua_block
        assert block._start_btn.isEnabled() is True

        class _FakeSignal:
            def __init__(self) -> None:
                self._slot = None

            def connect(self, slot) -> None:
                self._slot = slot

            def emit(self, result: dict) -> None:
                assert self._slot is not None
                self._slot(result)

        workers = []

        class _FakeWorker:
            def __init__(self, command: dict, parent=None) -> None:
                self.command = command
                self.finished = _FakeSignal()
                workers.append(self)

            def start(self) -> None:
                pass

        import cryodaq.gui.shell.overlays.keithley_panel as keithley_panel_module

        monkeypatch.setattr(keithley_panel_module, "ZmqCommandWorker", _FakeWorker)
        block._start_btn.click()
        assert len(workers) == 1
        workers[0].finished.emit({"ok": False, "outcome_unknown": True})
        assert block._start_btn.isEnabled() is False

        # Lose and recover measurement flow. Recovery replays the cached OFF,
        # then a newer Safety cut arrives, but neither is a new source event.
        w._last_reading_time = time.monotonic() - 10.0
        w._tick_status()
        w._dispatch_reading(_measurement_reading())
        w._tick_status()
        w.render_operator_snapshot(store.accept_snapshot(_typed_ready_snapshot(revision=43)))

        assert block._channel_state == "off"
        assert block._start_btn.isEnabled() is False
        block._start_btn.click()
        assert len(workers) == 1

        # Only a genuine new producer observation completes reconciliation.
        w._dispatch_reading(_source_state_reading("smua", "off"))
        assert block._start_btn.isEnabled() is True
    finally:
        _stop_timers(w)


def test_keithley_overlay_channel_state_replay_cleared_on_lifecycle_reset(
    live_zmq_bridge: ZmqBridge,
) -> None:
    _app()
    w = MainWindowV2(bridge=live_zmq_bridge)
    try:
        assert live_zmq_bridge.bridge_instance_id is not None
        w._last_reading_time = time.monotonic()
        assert w._keithley_panel is None
        w._dispatch_reading(_source_state_reading("smua", "off"))
        assert w._keithley_channel_state_snapshot["smua"].metadata["state"] == "off"
        assert w._keithley_panel is None

        w.invalidate_engine_producer()
        assert w._keithley_channel_state_snapshot == {}
        w._ensure_overlay("source")

        assert w._keithley_panel is not None
        block = w._keithley_panel._smua_block
        assert block._channel_state == "unknown"
        assert block._start_btn.isEnabled() is False
    finally:
        _stop_timers(w)


def test_passive_source_state_packet_cannot_seed_lazy_start_authority(
    live_zmq_bridge: ZmqBridge,
) -> None:
    _app()
    w = MainWindowV2(bridge=live_zmq_bridge)
    try:
        assert live_zmq_bridge.bridge_instance_id is not None
        w._last_reading_time = time.monotonic()
        w._dispatch_reading(_source_state_reading("smua", "off", authoritative=False))

        assert w._keithley_channel_state_snapshot == {}
        w._ensure_overlay("source")
        assert w._keithley_panel is not None
        block = w._keithley_panel._smua_block
        assert block._channel_state == "unknown"
        assert block._start_btn.isEnabled() is False
    finally:
        _stop_timers(w)


def test_keithley_overlay_connection_replay_on_lazy_open():
    _app()
    w = MainWindowV2()
    try:
        # No reading yet → cold-start disconnected.
        w._ensure_overlay("source")
        # Visible contract: cold-open → emergency button disabled (no connection).
        assert w._keithley_panel._smua_block._emergency_btn.isEnabled() is False
        assert w._keithley_panel._smub_block._emergency_btn.isEnabled() is False
    finally:
        _stop_timers(w)


# ----------------------------------------------------------------------
# SAFETY GAP: exact keithley command dict forwarding
# ----------------------------------------------------------------------


def test_smua_start_dispatches_exact_command_dict(monkeypatch):
    """SAFETY PATH: clicking Start on channel smua must dispatch the exact
    keithley_start command dict with p_target / v_comp / i_comp to the engine.

    Patches ZmqCommandWorker at the panel-module level so the ZMQ socket is
    never opened and the spawned command dict is captured synchronously.
    """
    _app()
    w = MainWindowV2()
    try:
        # Open overlay connected + safety ready, then provide an exact OFF
        # observation. Connectivity alone must never enable energization.
        w._last_reading_time = time.monotonic()
        w._ensure_overlay("source")
        w._keithley_panel.set_connected(True)
        w._keithley_panel.set_safety_ready(True)

        block = w._keithley_panel._smua_block
        block.apply_state("off")
        # Set known spin values.
        block._p_spin.setValue(0.050)
        block._v_spin.setValue(10.0)
        block._i_spin.setValue(0.005)

        captured_cmds: list[dict] = []

        class _FakeSignal:
            def __init__(self):
                self._slot = None

            def connect(self, slot):
                self._slot = slot

            def emit(self, result):
                assert self._slot is not None
                self._slot(result)

        workers = []

        class _FakeWorker:
            def __init__(self, cmd: dict, parent=None):
                captured_cmds.append(cmd)
                self.finished = _FakeSignal()
                workers.append(self)

            def start(self):
                pass

        import cryodaq.gui.shell.overlays.keithley_panel as _kp_mod

        monkeypatch.setattr(_kp_mod, "ZmqCommandWorker", _FakeWorker)

        # Click the REAL Start button (enabled by connected + safety-ready) so
        # the rendered clicked → _on_start_clicked → _dispatch_command wiring is
        # exercised end-to-end, not a private handler call.
        assert block._start_btn.isEnabled(), "Start requires connected + safety-ready + exact OFF observation"
        block._start_btn.click()

        assert len(captured_cmds) == 1, "exactly one command must be dispatched"
        cmd = captured_cmds[0]
        assert cmd["cmd"] == "keithley_start"
        assert cmd["channel"] == "smua"
        assert abs(cmd["p_target"] - 0.050) < 1e-9
        assert abs(cmd["v_comp"] - 10.0) < 1e-9
        assert abs(cmd["i_comp"] - 0.005) < 1e-9

        # Drive Stop on the SAME hosted panel (no second MainWindowV2 — keeps the
        # test's QThread churn at baseline). Put the channel in the running state
        # so Stop becomes enabled, click the real Stop button, assert keithley_stop.
        workers[-1].finished.emit({"ok": True})
        captured_cmds.clear()
        block.apply_state("on")
        assert block._stop_btn.isEnabled(), "Stop must be enabled when channel is running"
        block._stop_btn.click()

        assert len(captured_cmds) == 1, "exactly one stop command must be dispatched"
        stop_cmd = captured_cmds[0]
        assert stop_cmd["cmd"] == "keithley_stop"
        assert stop_cmd["channel"] == "smua"
    finally:
        _stop_timers(w)
