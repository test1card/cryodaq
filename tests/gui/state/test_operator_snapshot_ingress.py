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
    SafetyLifecycle,
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
    producer_id: str | None = None,
    experiment_id: str = "experiment-1",
) -> OperatorSnapshot:
    received = NOW + timedelta(seconds=revision) if received_at is None else received_at
    cut = SnapshotCut(revision, observed_at, received, source, mode, experiment_id, producer_id or source)
    state = OperatorPresentationState.STALE if mode is SnapshotMode.REPLAY else OperatorPresentationState.CAUTION
    status = SummaryStatus(state, 0.0, 0.0, (), "Backend authority")
    return OperatorSnapshot(
        cut,
        ReadinessSummary(
            cut,
            status,
            ReadinessTruth.UNKNOWN,
            (),
            SafetyLifecycle.UNKNOWN,
        ),
        PlantHealthSummary(cut, status, ()),
        InfrastructureNodeHealth(cut, status, ()),
        AttentionQueue(cut, status, ()),
        ExperimentOperatingState(
            cut,
            status,
            experiment_id,
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


def test_owner_requires_explicit_snapshot_mode_authority(qapp) -> None:
    with pytest.raises(TypeError, match="expected_mode"):
        OperatorSnapshotIngressOwner(_Bridge())  # type: ignore[call-arg]


def test_owner_constructs_exactly_one_store_and_direct_slot_accepts_complete_cut(qapp) -> None:
    owner = OperatorSnapshotIngressOwner(_Bridge(), expected_mode=SnapshotMode.LIVE)
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
    owner = OperatorSnapshotIngressOwner(bridge, expected_mode=SnapshotMode.LIVE)
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
    owner = OperatorSnapshotIngressOwner(bridge, expected_mode=SnapshotMode.LIVE, stale_after_s=5)
    emitted: list[OperatorSnapshot] = []
    owner.snapshot_changed.connect(emitted.append)
    owner.start()

    owner.pump()
    _events_until(lambda: len(emitted) == 1)

    assert len(emitted) == 1
    assert emitted[0].cut.revision == 1
    assert all(summary.transport_age_s >= 6 for summary in emitted[0].summaries())
    assert all(summary.transport_reason_codes == ("snapshot_stale",) for summary in emitted[0].summaries())
    assert emitted[0].readiness.readiness is ReadinessTruth.UNKNOWN
    assert emitted[0].readiness.lifecycle is SafetyLifecycle.UNKNOWN


def test_two_queued_cuts_coalesce_to_one_newest_qualified_revision(qapp) -> None:
    bridge = _Bridge()
    bridge.snapshots = [_snapshot(1), _snapshot(2)]
    bridge.age = 0.2
    owner = OperatorSnapshotIngressOwner(bridge, expected_mode=SnapshotMode.LIVE)
    emitted: list[OperatorSnapshot] = []
    owner.snapshot_changed.connect(emitted.append)
    owner.start()

    owner.pump()
    _events_until(lambda: len(emitted) == 1)

    assert [snapshot.cut.revision for snapshot in emitted] == [2]
    assert owner.accepted_count == 1
    assert owner.snapshot == emitted[0]


def test_invalid_member_quarantines_the_entire_drained_batch_before_replacement(qapp) -> None:
    bridge = _Bridge()
    bridge.age = 0.2
    owner = OperatorSnapshotIngressOwner(bridge, expected_mode=SnapshotMode.LIVE)
    owner.start()
    owner._apply_snapshot(owner._epoch, _snapshot(1))
    bridge.snapshots = [_snapshot(2), {"not": "a snapshot"}]

    owner.pump()
    _events_until(lambda: owner.rejected_count == 1)

    assert owner.snapshot is not None
    assert owner.snapshot.cut.revision == 1
    assert owner.snapshot.readiness.lifecycle is SafetyLifecycle.UNKNOWN
    assert {summary.transport_reason_codes for summary in owner.snapshot.summaries()} == {("transport_disconnected",)}


def test_mixed_identity_batch_is_quarantined_atomically(qapp) -> None:
    owner = OperatorSnapshotIngressOwner(_Bridge(), expected_mode=SnapshotMode.LIVE)
    owner.start()
    owner._apply_snapshot(owner._epoch, _snapshot(1, producer_id="engine-a"))

    owner._apply_snapshot_batch(
        owner._epoch,
        (
            _snapshot(2, producer_id="engine-b"),
            _snapshot(3, producer_id="engine-a"),
        ),
    )

    assert owner.accepted_count == 1
    assert owner.rejected_count == 1
    assert owner.snapshot is not None
    assert owner.snapshot.cut.revision == 1
    assert owner.snapshot.readiness.lifecycle is SafetyLifecycle.UNKNOWN
    assert {summary.transport_reason_codes for summary in owner.snapshot.summaries()} == {("transport_disconnected",)}


def test_wrong_thread_direct_mutation_rejected_but_signal_delivery_is_queued(qapp) -> None:
    owner = OperatorSnapshotIngressOwner(_Bridge(), expected_mode=SnapshotMode.LIVE)
    owner.start()
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            owner._apply_snapshot(owner._epoch, _snapshot(1))
        except BaseException as exc:
            errors.append(exc)
        owner._snapshot_queued.emit(owner._epoch, (_snapshot(1),))

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
    owner = OperatorSnapshotIngressOwner(bridge, expected_mode=SnapshotMode.LIVE)
    owner.start()
    owner._apply_snapshot(owner._epoch, _snapshot(1))
    owner._apply_transport(owner._epoch)
    old_epoch = owner._epoch
    owner._snapshot_queued.emit(old_epoch, (_snapshot(2),))
    bridge.snapshots = [_snapshot(3)]

    owner.invalidate_transport()
    QCoreApplication.processEvents()

    assert bridge.snapshots == []
    assert owner.snapshot is not None
    assert owner.snapshot.cut.revision == 1
    assert {summary.transport_reason_codes for summary in owner.snapshot.summaries()} == {("transport_disconnected",)}

    owner._apply_snapshot(owner._epoch, _snapshot(2))
    assert owner.accepted_count == 2
    assert owner.rejected_count == 0
    assert owner.snapshot.cut.revision == 2


def test_bridge_only_restart_still_rejects_foreign_engine_producer(qapp) -> None:
    owner = OperatorSnapshotIngressOwner(_Bridge(), expected_mode=SnapshotMode.LIVE)
    owner.start()
    owner._apply_snapshot(owner._epoch, _snapshot(1, producer_id="engine-a"))

    owner.invalidate_transport()
    owner._apply_snapshot(owner._epoch, _snapshot(2, producer_id="engine-b"))

    assert owner.accepted_count == 1
    assert owner.rejected_count == 1
    assert owner.snapshot is not None
    assert owner.snapshot.cut.producer_id == "engine-a"
    assert owner.snapshot.readiness.lifecycle is SafetyLifecycle.UNKNOWN


def test_explicit_engine_replacement_accepts_new_and_never_resurrects_retired_producer(qapp) -> None:
    owner = OperatorSnapshotIngressOwner(_Bridge(), expected_mode=SnapshotMode.LIVE)
    owner.start()
    owner._apply_snapshot(owner._epoch, _snapshot(7, producer_id="engine-a"))

    owner.invalidate_producer()
    owner._apply_snapshot(owner._epoch, _snapshot(1, producer_id="engine-b"))
    assert owner.accepted_count == 2
    assert owner.snapshot is not None
    assert owner.snapshot.cut.producer_id == "engine-b"

    owner.invalidate_producer()
    owner._apply_snapshot(owner._epoch, _snapshot(99, producer_id="engine-a"))

    assert owner.accepted_count == 2
    assert owner.rejected_count == 1
    assert owner.snapshot.cut.producer_id == "engine-b"
    assert owner.snapshot.readiness.lifecycle is SafetyLifecycle.UNKNOWN


def test_stale_and_disconnected_health_are_snapshot_only_and_never_restart(qapp) -> None:
    bridge = _Bridge()
    owner = OperatorSnapshotIngressOwner(bridge, expected_mode=SnapshotMode.LIVE, stale_after_s=5)
    owner.start()
    owner._apply_snapshot(owner._epoch, _snapshot(1))

    bridge.age = 6.0
    owner._apply_transport(owner._epoch)
    assert owner.snapshot is not None
    assert {summary.state for summary in owner.snapshot.summaries()} == {OperatorPresentationState.CAUTION}
    assert {summary.transport_reason_codes for summary in owner.snapshot.summaries()} == {("snapshot_stale",)}
    assert owner.snapshot.readiness.readiness is ReadinessTruth.UNKNOWN
    assert owner.snapshot.readiness.lifecycle is SafetyLifecycle.UNKNOWN

    bridge.alive = False
    owner._apply_transport(owner._epoch)
    assert owner.snapshot is not None
    assert {summary.transport_reason_codes for summary in owner.snapshot.summaries()} == {("transport_disconnected",)}
    assert owner.snapshot.readiness.readiness is ReadinessTruth.UNKNOWN
    assert owner.snapshot.readiness.lifecycle is SafetyLifecycle.UNKNOWN


def test_nonmonotonic_or_wrong_type_candidate_rejects_and_fails_closed(qapp) -> None:
    owner = OperatorSnapshotIngressOwner(_Bridge(), expected_mode=SnapshotMode.LIVE)
    owner.start()
    owner._apply_snapshot(owner._epoch, _snapshot(2, received_at=NOW + timedelta(seconds=99)))

    owner._apply_snapshot(owner._epoch, _snapshot(2))
    owner._apply_snapshot(owner._epoch, {"ready": True})

    assert owner.accepted_count == 1
    assert owner.rejected_count == 2
    assert owner.snapshot is not None
    assert owner.snapshot.cut.revision == 2
    assert all("transport_disconnected" in summary.transport_reason_codes for summary in owner.snapshot.summaries())


def test_identical_duplicate_revision_is_idempotent_without_authority_flap(qapp) -> None:
    owner = OperatorSnapshotIngressOwner(_Bridge(), expected_mode=SnapshotMode.LIVE)
    owner.start()
    original = _snapshot(2)
    assert owner._apply_snapshot(owner._epoch, original) is True
    epoch = owner._epoch
    presented = owner.snapshot

    assert owner._apply_snapshot(owner._epoch, _snapshot(2)) is False

    assert owner._epoch == epoch
    assert owner.accepted_count == 1
    assert owner.rejected_count == 0
    assert owner.snapshot is presented


def test_same_revision_equivocation_rejects_and_fails_closed(qapp) -> None:
    owner = OperatorSnapshotIngressOwner(_Bridge(), expected_mode=SnapshotMode.LIVE)
    owner.start()
    assert owner._apply_snapshot(owner._epoch, _snapshot(2)) is True

    conflicting = _snapshot(2, received_at=NOW + timedelta(seconds=99))
    assert owner._apply_snapshot(owner._epoch, conflicting) is False

    assert owner.accepted_count == 1
    assert owner.rejected_count == 1
    assert owner.snapshot is not None
    assert owner.snapshot.cut.received_at != conflicting.cut.received_at
    assert all("transport_disconnected" in summary.transport_reason_codes for summary in owner.snapshot.summaries())


def test_opposite_mode_high_revision_is_quarantined_without_poisoning_high_water(qapp) -> None:
    owner = OperatorSnapshotIngressOwner(_Bridge(), expected_mode=SnapshotMode.LIVE)
    owner.start()
    live_a = _snapshot(1, source="live/a")
    replay = _snapshot(
        99,
        source="replay/session-a",
        mode=SnapshotMode.REPLAY,
        observed_at=NOW - timedelta(days=1),
    )
    live_b = _snapshot(
        2,
        source="live/b",
        observed_at=NOW + timedelta(seconds=1),
        producer_id="live/a",
    )

    assert owner._apply_snapshot(owner._epoch, live_a) is True
    assert owner._apply_snapshot(owner._epoch, replay) is False
    assert owner.snapshot is not None
    assert owner.snapshot.cut.revision == 1
    assert all("transport_disconnected" in summary.transport_reason_codes for summary in owner.snapshot.summaries())
    assert owner._apply_snapshot(owner._epoch, live_b) is True

    assert owner.accepted_count == 2
    assert owner.rejected_count == 1
    assert owner.snapshot is not None
    assert owner.snapshot.cut.source == "live/b"
    assert owner.snapshot.cut.mode is SnapshotMode.LIVE


@pytest.mark.parametrize(
    ("expected_mode", "opposite_mode"),
    [
        (SnapshotMode.LIVE, SnapshotMode.REPLAY),
        (SnapshotMode.REPLAY, SnapshotMode.LIVE),
    ],
)
def test_opposite_mode_batch_is_rejected_before_store_acceptance(
    qapp,
    expected_mode: SnapshotMode,
    opposite_mode: SnapshotMode,
) -> None:
    owner = OperatorSnapshotIngressOwner(_Bridge(), expected_mode=expected_mode)
    owner.start()
    expected = _snapshot(1, mode=expected_mode)
    opposite = _snapshot(999, mode=opposite_mode)

    owner._apply_snapshot_batch(owner._epoch, (expected, opposite))

    assert owner.accepted_count == 0
    assert owner.rejected_count == 1
    assert owner.snapshot is None
    assert owner._apply_snapshot(owner._epoch, expected) is True
    assert owner.snapshot is not None
    assert owner.snapshot.cut.mode is expected_mode


def test_foreign_live_producer_is_quarantined_without_replacing_current_truth(qapp) -> None:
    owner = OperatorSnapshotIngressOwner(_Bridge(), expected_mode=SnapshotMode.LIVE)
    owner.start()
    owner._apply_snapshot(owner._epoch, _snapshot(1, producer_id="engine-a"))
    owner._apply_snapshot(owner._epoch, _snapshot(2, producer_id="engine-b"))

    assert owner.rejected_count == 1
    assert owner.snapshot is not None
    assert owner.snapshot.cut.revision == 1
    assert owner.snapshot.readiness.lifecycle is SafetyLifecycle.UNKNOWN
    assert {summary.transport_reason_codes for summary in owner.snapshot.summaries()} == {("transport_disconnected",)}


def test_stop_cancels_queued_epoch_drains_bridge_and_leaves_store_disconnected(qapp) -> None:
    bridge = _Bridge()
    owner = OperatorSnapshotIngressOwner(bridge, expected_mode=SnapshotMode.LIVE)
    owner.start()
    owner._apply_snapshot(owner._epoch, _snapshot(1))
    owner._snapshot_queued.emit(owner._epoch, (_snapshot(2),))
    bridge.snapshots = [_snapshot(3)]

    owner.stop()
    QCoreApplication.processEvents()

    assert owner.active is False
    assert owner.accepted_count == 1
    assert bridge.snapshots == []
    assert owner.snapshot is not None
    assert owner.snapshot.cut.revision == 1
    assert all("transport_disconnected" in summary.transport_reason_codes for summary in owner.snapshot.summaries())


def test_malformed_old_epoch_after_stop_has_zero_side_effects(qapp) -> None:
    owner = OperatorSnapshotIngressOwner(_Bridge(), expected_mode=SnapshotMode.LIVE)
    owner.start()
    owner._apply_snapshot(owner._epoch, _snapshot(1))
    old_epoch = owner._epoch
    owner.stop()
    before = (
        owner._epoch,
        owner.active,
        owner.accepted_count,
        owner.rejected_count,
        owner.snapshot,
    )

    owner._apply_snapshot_batch(old_epoch, ({"optimistic": "ready"},))
    owner._apply_failure(old_epoch)

    assert (
        owner._epoch,
        owner.active,
        owner.accepted_count,
        owner.rejected_count,
        owner.snapshot,
    ) == before


def test_stop_failure_keeps_owner_active_and_epoch_current(qapp, monkeypatch) -> None:
    bridge = _Bridge()
    owner = OperatorSnapshotIngressOwner(bridge, expected_mode=SnapshotMode.LIVE)
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
    owner = OperatorSnapshotIngressOwner(bridge, expected_mode=SnapshotMode.LIVE)

    owner.pump()

    assert owner.snapshot is None
    assert bridge.poll_calls == 0
    assert owner.accepted_count == 0


def test_queue_or_health_failure_only_degrades_presentation_and_never_restarts(qapp) -> None:
    bridge = _Bridge()
    owner = OperatorSnapshotIngressOwner(bridge, expected_mode=SnapshotMode.LIVE)
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
        OperatorSnapshotIngressOwner(
            _Bridge(),
            expected_mode=SnapshotMode.LIVE,
            stale_after_s=threshold,
        )


def test_app_composition_root_has_one_owner_and_visible_pod_cutover() -> None:
    root = Path(__file__).resolve().parents[3]
    app_path = root / "src/cryodaq/gui/app.py"
    launcher_path = root / "src/cryodaq/launcher.py"
    owner_path = root / "src/cryodaq/gui/state/operator_snapshot_ingress.py"
    app_source = app_path.read_text(encoding="utf-8")
    launcher_source = launcher_path.read_text(encoding="utf-8")
    app_tree = ast.parse(app_source)
    launcher_tree = ast.parse(launcher_source)
    owner_tree = ast.parse(owner_path.read_text(encoding="utf-8"))

    compositions = [
        node
        for node in ast.walk(app_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "start_operator_snapshot_ingress"
    ]
    assert len(compositions) == 1
    app_composition = compositions[0]
    assert len(app_composition.args) == 2
    assert {keyword.arg for keyword in app_composition.keywords} == {"anchor", "expected_mode"}
    app_mode = next(keyword.value for keyword in app_composition.keywords if keyword.arg == "expected_mode")
    assert ast.unparse(app_mode) == "SnapshotMode.LIVE"
    launcher_compositions = [
        node
        for node in ast.walk(launcher_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "start_operator_snapshot_ingress"
    ]
    assert len(launcher_compositions) == 1
    launcher_composition = launcher_compositions[0]
    assert len(launcher_composition.args) == 2
    assert {keyword.arg for keyword in launcher_composition.keywords} == {"anchor", "expected_mode"}
    launcher_mode = next(keyword.value for keyword in launcher_composition.keywords if keyword.arg == "expected_mode")
    assert ast.unparse(launcher_mode) == (
        "SnapshotMode.REPLAY if self._replay_source is not None else SnapshotMode.LIVE"
    )
    anchor = next(keyword.value for keyword in launcher_composition.keywords if keyword.arg == "anchor")
    assert isinstance(anchor, ast.Lambda)
    assert isinstance(anchor.body, ast.Call)
    assert isinstance(anchor.body.func, ast.Name)
    assert anchor.body.func.id == "setattr"
    assert len(anchor.body.args) == 3
    assert isinstance(anchor.body.args[1], ast.Constant)
    assert anchor.body.args[1].value == "_snapshot_ingress"
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
    owner = start_operator_snapshot_ingress(
        bridge,
        window,
        expected_mode=SnapshotMode.LIVE,
    )

    owner.pump()
    _events_until(lambda: owner.snapshot is not None)

    assert owner.parent() is window
    assert owner.snapshot is not None
    assert owner.snapshot.cut == _snapshot(2).cut
    assert window.rendered == [owner.snapshot]
