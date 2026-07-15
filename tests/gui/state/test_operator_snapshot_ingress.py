from __future__ import annotations

import ast
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QCoreApplication, QObject, QThread
from PySide6.QtWidgets import QApplication

from cryodaq.gui.state.operator_snapshot_ingress import (
    OperatorSnapshotIngressOwner,
    start_operator_snapshot_ingress,
)
from cryodaq.gui.state.operator_view_models import OperatorSnapshotStore
from cryodaq.operator_snapshot import (
    AttentionQueue,
    AvailabilityTruth,
    CooldownHistorySummary,
    DataIntegritySummary,
    ExperimentOperatingState,
    InfrastructureNodeHealth,
    OperatorPresentationState,
    OperatorSnapshot,
    PlantHealthSummary,
    ReadinessSummary,
    ReadinessTruth,
    RecordingTruth,
    SnapshotCut,
    SnapshotMode,
    SummaryStatus,
    SupportBundleSummary,
)

NOW = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    return app


def _snapshot(
    revision: int,
    *,
    source: str = "engine/operator-snapshot-v1/source-a",
    mode: SnapshotMode = SnapshotMode.LIVE,
    observed_at: datetime = NOW,
    received_at: datetime | None = None,
) -> OperatorSnapshot:
    received = NOW + timedelta(seconds=revision) if received_at is None else received_at
    cut = SnapshotCut(revision, observed_at, received, source, mode)
    state = OperatorPresentationState.STALE if mode is SnapshotMode.REPLAY else OperatorPresentationState.CAUTION
    status = SummaryStatus(state, 0.0, 0.0, (), "Backend authority")
    return OperatorSnapshot(
        cut,
        ReadinessSummary(
            cut,
            status,
            ReadinessTruth.UNKNOWN,
            (),
        ),
        PlantHealthSummary(cut, status, ()),
        InfrastructureNodeHealth(cut, status, ()),
        AttentionQueue(cut, status, ()),
        ExperimentOperatingState(
            cut,
            status,
            "experiment-1",
            "Cooldown",
            "cooldown",
            RecordingTruth.REPLAY_ONLY if mode is SnapshotMode.REPLAY else RecordingTruth.UNKNOWN,
            None,
        ),
        DataIntegritySummary(
            cut,
            status,
            revision,
            revision,
            0,
            0,
            AvailabilityTruth.UNKNOWN,
        ),
        CooldownHistorySummary(cut, status, (), None, ()),
        SupportBundleSummary(cut, status, AvailabilityTruth.UNKNOWN, None),
    )


class _Bridge:
    def __init__(self) -> None:
        self.snapshots: list[object] = []
        self.age: float | None = None
        self.alive = True
        self.poll_calls = 0
        self.poll_error: BaseException | None = None
        self.age_error: BaseException | None = None

    def poll_operator_snapshots(self) -> list[object]:
        self.poll_calls += 1
        if self.poll_error is not None:
            raise self.poll_error
        result = list(self.snapshots)
        self.snapshots.clear()
        return result

    def snapshot_flow_age_s(self) -> float | None:
        if self.age_error is not None:
            raise self.age_error
        return self.age

    def is_alive(self) -> bool:
        return self.alive

    def data_flow_stalled(self) -> bool:
        raise AssertionError("reading age must not authorize snapshot presentation")

    def start(self) -> None:
        raise AssertionError("snapshot ingress must not restart the bridge")

    def shutdown(self) -> None:
        raise AssertionError("snapshot ingress must not stop the bridge")


def _events_until(predicate, *, timeout_s: float = 1.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline and not predicate():
        QCoreApplication.processEvents()
        time.sleep(0.001)
    QCoreApplication.processEvents()
    assert predicate()


def test_owner_constructs_exactly_one_store_and_direct_slot_accepts_complete_cut(qapp) -> None:
    owner = OperatorSnapshotIngressOwner(_Bridge())
    assert type(owner._store) is OperatorSnapshotStore
    assert not hasattr(owner, "store")
    owner.start()

    snapshot = _snapshot(1)
    owner._apply_snapshot(owner._epoch, snapshot)

    assert owner.snapshot == snapshot
    assert owner.accepted_count == 1
    assert owner.rejected_count == 0


def test_pump_crosses_queued_signal_and_applies_only_on_gui_thread(qapp) -> None:
    bridge = _Bridge()
    bridge.snapshots = [_snapshot(1)]
    bridge.age = 0.25
    owner = OperatorSnapshotIngressOwner(bridge)
    applied_threads: list[QThread] = []
    owner.snapshot_changed.connect(lambda _snapshot: applied_threads.append(QThread.currentThread()))
    owner.start()

    owner.pump()
    assert owner.snapshot is None
    _events_until(lambda: owner.snapshot is not None)

    assert owner.accepted_count == 1
    assert applied_threads
    assert all(thread == owner.thread() for thread in applied_threads)
    assert owner.snapshot is not None
    assert owner.snapshot.readiness.transport_age_s >= 0.25


def test_new_cut_and_stale_transport_emit_once_as_one_atomic_presentation(qapp) -> None:
    bridge = _Bridge()
    bridge.snapshots = [_snapshot(1)]
    bridge.age = 6.0
    owner = OperatorSnapshotIngressOwner(bridge, stale_after_s=5)
    emitted: list[OperatorSnapshot] = []
    owner.snapshot_changed.connect(emitted.append)
    owner.start()

    owner.pump()
    _events_until(lambda: len(emitted) == 1)

    assert len(emitted) == 1
    assert emitted[0].cut.revision == 1
    assert all(summary.transport_age_s >= 6 for summary in emitted[0].summaries())
    assert all(summary.transport_reason_codes == ("snapshot_stale",) for summary in emitted[0].summaries())


def test_two_queued_cuts_coalesce_to_one_newest_qualified_revision(qapp) -> None:
    bridge = _Bridge()
    bridge.snapshots = [_snapshot(1), _snapshot(2)]
    bridge.age = 0.2
    owner = OperatorSnapshotIngressOwner(bridge)
    emitted: list[OperatorSnapshot] = []
    owner.snapshot_changed.connect(emitted.append)
    owner.start()

    owner.pump()
    _events_until(lambda: len(emitted) == 1)

    assert [snapshot.cut.revision for snapshot in emitted] == [2]
    assert owner.accepted_count == 1
    assert owner.snapshot == emitted[0]


def test_wrong_thread_direct_mutation_rejected_but_signal_delivery_is_queued(qapp) -> None:
    owner = OperatorSnapshotIngressOwner(_Bridge())
    owner.start()
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            owner._apply_snapshot(owner._epoch, _snapshot(1))
        except BaseException as exc:
            errors.append(exc)
        owner._snapshot_queued.emit(owner._epoch, _snapshot(1))

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeError)
    assert owner.snapshot is None

    _events_until(lambda: owner.snapshot is not None)
    assert owner.accepted_count == 1


def test_restart_invalidation_discards_queued_old_epoch_and_degrades_current_cut(qapp) -> None:
    bridge = _Bridge()
    bridge.age = 0.1
    owner = OperatorSnapshotIngressOwner(bridge)
    owner.start()
    owner._apply_snapshot(owner._epoch, _snapshot(1))
    owner._apply_transport(owner._epoch)
    old_epoch = owner._epoch
    owner._snapshot_queued.emit(old_epoch, _snapshot(2))
    bridge.snapshots = [_snapshot(3)]

    owner.invalidate_transport()
    QCoreApplication.processEvents()

    assert bridge.snapshots == []
    assert owner.snapshot is not None
    assert owner.snapshot.cut.revision == 1
    assert {summary.transport_reason_codes for summary in owner.snapshot.summaries()} == {("transport_disconnected",)}


def test_stale_and_disconnected_health_are_snapshot_only_and_never_restart(qapp) -> None:
    bridge = _Bridge()
    owner = OperatorSnapshotIngressOwner(bridge, stale_after_s=5)
    owner.start()
    owner._apply_snapshot(owner._epoch, _snapshot(1))

    bridge.age = 6.0
    owner._apply_transport(owner._epoch)
    assert owner.snapshot is not None
    assert {summary.state for summary in owner.snapshot.summaries()} == {OperatorPresentationState.CAUTION}
    assert {summary.transport_reason_codes for summary in owner.snapshot.summaries()} == {("snapshot_stale",)}

    bridge.alive = False
    owner._apply_transport(owner._epoch)
    assert owner.snapshot is not None
    assert {summary.transport_reason_codes for summary in owner.snapshot.summaries()} == {("transport_disconnected",)}


def test_nonmonotonic_or_wrong_type_candidate_rejects_and_fails_closed(qapp) -> None:
    owner = OperatorSnapshotIngressOwner(_Bridge())
    owner.start()
    owner._apply_snapshot(owner._epoch, _snapshot(2))

    owner._apply_snapshot(owner._epoch, _snapshot(2))
    owner._apply_snapshot(owner._epoch, {"ready": True})

    assert owner.accepted_count == 1
    assert owner.rejected_count == 2
    assert owner.snapshot is not None
    assert owner.snapshot.cut.revision == 2
    assert all("transport_disconnected" in summary.transport_reason_codes for summary in owner.snapshot.summaries())


def test_source_and_mode_transitions_preserve_store_protocol_authority(qapp) -> None:
    owner = OperatorSnapshotIngressOwner(_Bridge())
    owner.start()
    live_a = _snapshot(1, source="live/a")
    replay = _snapshot(
        2,
        source="replay/session-a",
        mode=SnapshotMode.REPLAY,
        observed_at=NOW - timedelta(days=1),
    )
    live_b = _snapshot(3, source="live/b", observed_at=NOW + timedelta(seconds=1))

    for snapshot in (live_a, replay, live_b):
        owner._apply_snapshot(owner._epoch, snapshot)

    assert owner.accepted_count == 3
    assert owner.snapshot is not None
    assert owner.snapshot.cut.source == "live/b"
    assert owner.snapshot.cut.mode is SnapshotMode.LIVE

    regressed_live_b = _snapshot(
        4,
        source="live/b",
        observed_at=NOW,
        received_at=NOW + timedelta(seconds=5),
    )
    owner._apply_snapshot(owner._epoch, regressed_live_b)
    assert owner.rejected_count == 1
    assert owner.snapshot.cut.revision == 3


def test_stop_cancels_queued_epoch_drains_bridge_and_leaves_store_disconnected(qapp) -> None:
    bridge = _Bridge()
    owner = OperatorSnapshotIngressOwner(bridge)
    owner.start()
    owner._apply_snapshot(owner._epoch, _snapshot(1))
    owner._snapshot_queued.emit(owner._epoch, _snapshot(2))
    bridge.snapshots = [_snapshot(3)]

    owner.stop()
    QCoreApplication.processEvents()

    assert owner.active is False
    assert owner.accepted_count == 1
    assert bridge.snapshots == []
    assert owner.snapshot is not None
    assert owner.snapshot.cut.revision == 1
    assert all("transport_disconnected" in summary.transport_reason_codes for summary in owner.snapshot.summaries())


def test_stop_failure_keeps_owner_active_and_epoch_current(qapp, monkeypatch) -> None:
    bridge = _Bridge()
    owner = OperatorSnapshotIngressOwner(bridge)
    owner.start()
    owner._apply_snapshot(owner._epoch, _snapshot(1))
    epoch = owner._epoch
    monkeypatch.setattr(
        owner,
        "_degrade_current",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("render failed")),
    )

    with pytest.raises(RuntimeError, match="render failed"):
        owner.stop()

    assert owner.active is True
    assert owner._epoch == epoch
    assert bridge.poll_calls == 1


def test_cold_start_and_inactive_pump_never_synthesize_backend_truth(qapp) -> None:
    bridge = _Bridge()
    bridge.snapshots = [_snapshot(1)]
    owner = OperatorSnapshotIngressOwner(bridge)

    owner.pump()

    assert owner.snapshot is None
    assert bridge.poll_calls == 0
    assert owner.accepted_count == 0


def test_queue_or_health_failure_only_degrades_presentation_and_never_restarts(qapp) -> None:
    bridge = _Bridge()
    owner = OperatorSnapshotIngressOwner(bridge)
    owner.start()
    owner._apply_snapshot(owner._epoch, _snapshot(1))

    bridge.poll_error = RuntimeError("queue unavailable")
    owner.pump()
    _events_until(lambda: owner.rejected_count == 1)
    assert owner.snapshot is not None
    assert all("transport_disconnected" in summary.transport_reason_codes for summary in owner.snapshot.summaries())

    bridge.poll_error = None
    bridge.age_error = RuntimeError("age unavailable")
    owner._apply_transport(owner._epoch)
    assert owner.rejected_count == 2


@pytest.mark.parametrize("threshold", [0, -1, True, float("nan"), float("inf"), "5"])
def test_stale_threshold_is_exact_finite_and_positive(qapp, threshold: Any) -> None:
    with pytest.raises((TypeError, ValueError)):
        OperatorSnapshotIngressOwner(_Bridge(), stale_after_s=threshold)


def test_app_composition_root_has_one_owner_and_visible_pod_cutover() -> None:
    root = Path(__file__).resolve().parents[3]
    app_path = root / "src/cryodaq/gui/app.py"
    launcher_path = root / "src/cryodaq/launcher.py"
    owner_path = root / "src/cryodaq/gui/state/operator_snapshot_ingress.py"
    app_source = app_path.read_text(encoding="utf-8")
    launcher_source = launcher_path.read_text(encoding="utf-8")
    app_tree = ast.parse(app_source)
    owner_tree = ast.parse(owner_path.read_text(encoding="utf-8"))

    compositions = [
        node
        for node in ast.walk(app_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "start_operator_snapshot_ingress"
    ]
    assert len(compositions) == 1
    assert "start_operator_snapshot_ingress(self._bridge, self._main_window)" in launcher_source
    assert "OperatorSnapshotStore" not in app_source
    imports = {
        node.module for node in ast.walk(owner_tree) if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert not any(
        module.startswith(
            (
                "cryodaq.gui.shell",
                "cryodaq.safety",
                "cryodaq.drivers",
                "cryodaq.replay_engine",
            )
        )
        for module in imports
    )
    calls = {
        node.func.attr
        for node in ast.walk(owner_tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not {"shutdown", "send_command", "data_flow_stalled"} & calls


def test_shared_launch_composition_pumps_newest_typed_cut_once(qapp) -> None:
    class Window(QObject):
        def __init__(self) -> None:
            super().__init__()
            self.rendered: list[OperatorSnapshot] = []

        def render_operator_snapshot(self, snapshot: OperatorSnapshot) -> None:
            self.rendered.append(snapshot)

    bridge = _Bridge()
    bridge.snapshots = [_snapshot(1), _snapshot(2)]
    window = Window()
    owner = start_operator_snapshot_ingress(bridge, window)

    owner.pump()
    _events_until(lambda: owner.snapshot is not None)

    assert owner.parent() is window
    assert owner.snapshot is not None
    assert owner.snapshot.cut == _snapshot(2).cut
    assert window.rendered == [owner.snapshot]
