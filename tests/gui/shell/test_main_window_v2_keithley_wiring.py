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
from datetime import UTC, datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from cryodaq.drivers.base import Reading
from cryodaq.gui.shell.main_window_v2 import MainWindowV2, _map_safety_state
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


def _safety_reading(
    state: str,
    reason: str = "",
    *,
    observed_at: datetime | None = None,
    bridge_id: str | None = None,
) -> Reading:
    metadata = {"state": state, "reason": reason}
    if bridge_id is not None:
        metadata["bridge_instance_id"] = bridge_id
    return Reading(
        timestamp=observed_at or datetime.now(UTC),
        instrument_id="safety_manager",
        channel="analytics/safety_state",
        value=0.0,
        unit="",
        metadata=metadata,
    )


def _source_state_reading(channel: str, state: str) -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="safety_manager",
        channel=f"analytics/keithley_channel_state/{channel}",
        value=0.0,
        unit="",
        metadata={"state": state},
    )


def _typed_ready_snapshot(*, revision: int = 42) -> OperatorSnapshot:
    observed = datetime.now(UTC) - timedelta(seconds=1)
    cut = SnapshotCut(revision, observed, observed, "engine-v1", SnapshotMode.LIVE, "exp-1", "engine-v1")
    status = SummaryStatus(OperatorPresentationState.OK, 1.0, 0.0, ("authoritative",), "Подтверждено")
    manifest = SupportBundleManifest(
        "bundle-42",
        cut.received_at,
        (SupportBundleEntry("status/status.json", 123, "a" * 64),),
    )
    return OperatorSnapshot(
        cut,
        ReadinessSummary(cut, status, ReadinessTruth.READY, (), SafetyLifecycle.READY),
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
            "exp-1",
            "Эксперимент",
            "cooldown",
            RecordingTruth.RECORDING,
            "rec-1",
        ),
        DataIntegritySummary(cut, status, 42, 41, 0, 0, AvailabilityTruth.AVAILABLE),
        CooldownHistorySummary(cut, status, (CooldownSample(0, 300),), None, ()),
        SupportBundleSummary(cut, status, AvailabilityTruth.AVAILABLE, manifest),
    )


# ----------------------------------------------------------------------
# Pure helper tests — no Qt needed
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "state, reason, expected",
    [
        ("ready", "any", (True, "")),
        ("run_permitted", "", (True, "")),
        ("running", "", (True, "")),
        ("safe_off", "system stop", (False, "system stop")),
        ("fault_latched", "", (False, "fault_latched")),
        ("unknown_state", "", (False, "unknown_state")),
        (None, "", (False, "unknown")),
    ],
)
def test_map_safety_state_cases(state, reason, expected):
    assert _map_safety_state(state, reason) == expected


def test_map_safety_state_truncates_long_reason():
    long_reason = "x" * 200
    ready, text = _map_safety_state("safe_off", long_reason)
    assert ready is False
    # 120 chars preserved + ellipsis character.
    assert text == "x" * 120 + "…"


def test_map_safety_state_empty_reason_falls_back_to_state():
    ready, text = _map_safety_state("fault_latched", "")
    assert ready is False
    assert text == "fault_latched"


def test_map_safety_state_whitespace_reason_falls_back():
    ready, text = _map_safety_state("safe_off", "   \t  ")
    assert ready is False
    assert text == "safe_off"


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


def test_ready_analytics_is_display_only_before_typed_authority():
    _app()
    bridge = ZmqBridge()
    w = MainWindowV2(bridge=bridge)
    try:
        assert bridge.bridge_instance_id is not None
        w._latest_experiment_status = {"active_experiment": {"experiment_id": "exp-1"}}
        w._ensure_overlay("source")
        w._last_reading_time = time.monotonic()
        w._tick_status()
        assert w._keithley_panel._connected is True

        w._dispatch_reading(
            _safety_reading(
                "ready",
                bridge_id=bridge.bridge_instance_id,
            )
        )

        assert w._keithley_panel._safety_ready is False
        assert w._keithley_panel._smua_block._start_btn.isEnabled() is False
        assert w._keithley_panel._start_both_btn.isEnabled() is False
        assert w._accepted_safety_bridge_instance_id is None
        assert w._accepted_safety_experiment_id is None
    finally:
        _stop_timers(w)


def test_ready_analytics_after_negative_cannot_restore_authority() -> None:
    _app()
    bridge = ZmqBridge()
    w = MainWindowV2(bridge=bridge)
    try:
        assert bridge.bridge_instance_id is not None
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
                bridge_id=bridge.bridge_instance_id,
            )
        )
        w._dispatch_reading(
            _safety_reading(
                "ready",
                observed_at=observed + timedelta(milliseconds=500),
                bridge_id=bridge.bridge_instance_id,
            )
        )

        assert w._keithley_panel._safety_ready is False
        assert w._current_keithley_safety_gate()[0] is False
    finally:
        _stop_timers(w)


def test_bridge_and_experiment_changes_never_create_telemetry_authority() -> None:
    _app()
    bridge = ZmqBridge()
    w = MainWindowV2(bridge=bridge)
    try:
        assert bridge.bridge_instance_id is not None
        w._latest_experiment_status = {"active_experiment": {"experiment_id": "exp-a"}}
        w._ensure_overlay("source")
        w._dispatch_reading(_safety_reading("ready", bridge_id=bridge.bridge_instance_id))
        assert w._keithley_panel._safety_ready is False

        bridge._bridge_instance_id = "f" * 32
        w._on_experiment_status_received(
            {
                "active_experiment": {"experiment_id": "exp-b"},
                "phases": [],
            }
        )
        w._last_reading_time = time.monotonic()
        w._tick_status()
        w._dispatch_reading(_safety_reading("ready", bridge_id=bridge.bridge_instance_id))

        assert w._keithley_panel._safety_ready is False
        assert w._accepted_safety_bridge_instance_id is None
        assert w._accepted_safety_experiment_id is None
    finally:
        _stop_timers(w)


def test_negative_analytics_revokes_typed_ready() -> None:
    _app()
    bridge = ZmqBridge()
    w = MainWindowV2(bridge=bridge)
    store = OperatorSnapshotStore()
    try:
        assert bridge.bridge_instance_id is not None
        w._latest_experiment_status = {"active_experiment": {"experiment_id": "exp-1"}}
        w._ensure_overlay("source")
        w.render_operator_snapshot(store.accept_snapshot(_typed_ready_snapshot()))
        assert w._keithley_panel._safety_ready is True

        w._dispatch_reading(
            _safety_reading(
                "fault_latched",
                "negative telemetry",
                bridge_id=bridge.bridge_instance_id,
            )
        )

        assert w._keithley_panel._safety_ready is False
        assert w._current_keithley_safety_gate()[0] is False
    finally:
        _stop_timers(w)


def test_same_cut_and_analytics_ready_cannot_restore_but_newer_typed_cut_can() -> None:
    _app()
    bridge = ZmqBridge()
    w = MainWindowV2(bridge=bridge)
    store = OperatorSnapshotStore()
    try:
        assert bridge.bridge_instance_id is not None
        w._latest_experiment_status = {"active_experiment": {"experiment_id": "exp-1"}}
        w._ensure_overlay("source")
        original = store.accept_snapshot(_typed_ready_snapshot(revision=42))
        w.render_operator_snapshot(original)
        assert w._keithley_panel._safety_ready is True

        w._dispatch_reading(
            _safety_reading(
                "fault_latched",
                "negative telemetry",
                bridge_id=bridge.bridge_instance_id,
            )
        )
        assert w._keithley_panel._safety_ready is False

        w.render_operator_snapshot(original)
        w._dispatch_reading(_safety_reading("ready", bridge_id=bridge.bridge_instance_id))
        assert w._keithley_panel._safety_ready is False

        newer = store.accept_snapshot(_typed_ready_snapshot(revision=43))
        w.render_operator_snapshot(newer)
        assert w._keithley_panel._safety_ready is True
    finally:
        _stop_timers(w)


def test_foreign_ready_destroys_prior_legacy_replay_binding() -> None:
    _app()
    bridge = ZmqBridge()
    w = MainWindowV2(bridge=bridge)
    try:
        assert bridge.bridge_instance_id is not None
        w._ensure_overlay("source")
        observed = datetime.now(UTC) - timedelta(seconds=1)
        w._dispatch_reading(
            _safety_reading(
                "fault_latched",
                observed_at=observed,
                bridge_id=bridge.bridge_instance_id,
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


def test_typed_snapshot_staleness_revokes_gate_and_legacy_ready_cannot_resurrect_it() -> None:
    _app()
    bridge = ZmqBridge()
    w = MainWindowV2(bridge=bridge)
    store = OperatorSnapshotStore()
    try:
        assert bridge.bridge_instance_id is not None
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

        w._dispatch_reading(_safety_reading("ready", bridge_id=bridge.bridge_instance_id))
        assert w._keithley_panel._safety_ready is False
        assert w._last_safety_state == SafetyLifecycle.UNKNOWN.value
    finally:
        _stop_timers(w)


def test_malformed_typed_snapshot_permanently_disables_legacy_ready_fallback() -> None:
    _app()
    bridge = ZmqBridge()
    w = MainWindowV2(bridge=bridge)
    try:
        assert bridge.bridge_instance_id is not None
        w._ensure_overlay("source")

        w._apply_operator_snapshot_safety(object())
        w._dispatch_reading(_safety_reading("ready", bridge_id=bridge.bridge_instance_id))

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
