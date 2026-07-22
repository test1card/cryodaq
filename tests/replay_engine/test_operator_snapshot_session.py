from __future__ import annotations

import ast
import asyncio
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cryodaq.core.zmq_bridge import ZMQPublisher
from cryodaq.gui.state.operator_snapshot_ingress import OperatorSnapshotIngressOwner
from cryodaq.gui.state.operator_view_models import OperatorSnapshotStore
from cryodaq.operator_snapshot import (
    AvailabilityTruth,
    CooldownSample,
    OperatorPresentationState,
    ReadinessTruth,
    RecordingTruth,
    SnapshotMode,
)
from cryodaq.operator_snapshot_transport import decode_operator_snapshot_frames
from cryodaq.replay_engine.operator_snapshot_session import (
    ReplayOperatorSnapshotSession,
    ReplaySnapshotEvidence,
    ReplaySnapshotPublicationError,
)

NOW = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)
FINGERPRINT = "a" * 64
NONCE_A = "1" * 32
NONCE_B = "2" * 32


class _Clock:
    def __init__(self, *values: datetime) -> None:
        self.values = list(values)

    def __call__(self) -> datetime:
        return self.values.pop(0)


def _evidence(observed_at: datetime = NOW) -> ReplaySnapshotEvidence:
    return ReplaySnapshotEvidence(
        observed_at,
        experiment_id="archive-exp-1",
        experiment_name="Historical cooldown",
        phase="cooldown",
        cooldown_samples=(CooldownSample(0, 300), CooldownSample(60, 250)),
        cooldown_reference_id="reference-1",
        cooldown_reference=(CooldownSample(0, 300), CooldownSample(60, 245)),
    )


def _session(*times: datetime, nonce: str = NONCE_A, initial_revision: int = 0):
    return ReplayOperatorSnapshotSession(
        archive_fingerprint=FINGERPRINT,
        session_nonce=nonce,
        initial_revision=initial_revision,
        clock=_Clock(*times),
    )


def test_conservative_complete_replay_cut_never_claims_live_authority() -> None:
    session = _session(NOW + timedelta(hours=1))
    snapshot = session.compose(_evidence())

    assert snapshot.cut.mode is SnapshotMode.REPLAY
    assert snapshot.cut.revision == 1
    assert len(snapshot.summaries()) == 8
    assert all(summary.cut is snapshot.cut for summary in snapshot.summaries())
    assert all(summary.state is not OperatorPresentationState.OK for summary in snapshot.summaries())
    assert snapshot.readiness.readiness is ReadinessTruth.UNKNOWN
    assert snapshot.experiment.recording is RecordingTruth.REPLAY_ONLY
    assert snapshot.data_integrity.storage is AvailabilityTruth.UNKNOWN
    assert snapshot.support_bundle.availability is AvailabilityTruth.UNKNOWN
    assert snapshot.attention.reason_codes == ("attention_authority_unavailable",)
    assert snapshot.infrastructure.reason_codes == ("infrastructure_authority_unavailable",)
    assert snapshot.support_bundle.reason_codes == ("support_authority_unavailable",)


class _Socket:
    def __init__(self) -> None:
        self.messages: list[list[bytes]] = []

    async def send_multipart(self, frames: list[bytes]) -> None:
        self.messages.append(frames)


class _IngressBridge:
    def poll_operator_snapshots(self):
        return []

    def snapshot_flow_age_s(self) -> float:
        return 0.1

    def is_alive(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_same_publisher_codec_decoder_and_store_accept_replay_without_gui_synthesis() -> None:
    session = _session(NOW + timedelta(hours=1))
    publisher = ZMQPublisher()
    socket = _Socket()
    publisher._socket = socket  # type: ignore[assignment]
    publisher._running = True

    published = await session.compose_and_publish(_evidence(), publisher)

    assert len(socket.messages) == 1
    decoded = decode_operator_snapshot_frames(socket.messages[0])
    assert decoded == published
    store = OperatorSnapshotStore()
    assert store.accept_snapshot(decoded) == published
    assert store.cut.mode is SnapshotMode.REPLAY

    owner = OperatorSnapshotIngressOwner(_IngressBridge())
    owner.start()
    owner._apply_snapshot_batch(owner._epoch, (decoded,))
    assert owner.snapshot is not None
    assert owner.snapshot.cut == decoded.cut
    assert owner.snapshot.cut.mode is SnapshotMode.REPLAY
    assert all(summary.transport_age_s >= 0.1 for summary in owner.snapshot.summaries())


def test_seek_epoch_changes_source_but_revision_and_receipt_order_continue() -> None:
    session = _session(
        NOW + timedelta(hours=2),
        NOW + timedelta(hours=2, seconds=1),
    )
    store = OperatorSnapshotStore()
    first = session.compose(_evidence(NOW + timedelta(hours=1)))
    store.accept_snapshot(first)
    old_source = first.cut.source

    new_source = session.begin_seek_epoch()
    second = session.compose(_evidence(NOW - timedelta(days=10)))
    store.accept_snapshot(second)

    assert session.epoch == 1
    assert new_source != old_source
    assert second.cut.source == new_source
    assert second.cut.revision == first.cut.revision + 1
    assert second.cut.observed_at < first.cut.observed_at
    assert second.cut.received_at > first.cut.received_at
    assert store.cut == second.cut


def test_restart_requires_explicit_revision_floor_and_new_session_identity() -> None:
    old = _session(
        NOW + timedelta(hours=1),
        NOW + timedelta(hours=1, seconds=1),
        nonce=NONCE_A,
    )
    store = OperatorSnapshotStore()
    store.accept_snapshot(old.compose(_evidence()))
    last = old.compose(_evidence())
    store.accept_snapshot(last)
    old.close()

    restarted = _session(
        NOW + timedelta(hours=1, seconds=2),
        nonce=NONCE_B,
        initial_revision=last.cut.revision,
    )
    resumed = restarted.compose(_evidence())
    store.accept_snapshot(resumed)

    assert resumed.cut.revision == last.cut.revision + 1
    assert resumed.cut.source != last.cut.source
    ambiguous_reset = _session(
        NOW + timedelta(hours=1, seconds=3),
        nonce="3" * 32,
    ).compose(_evidence())
    with pytest.raises(ValueError, match="revision must be strictly newer"):
        store.accept_snapshot(ambiguous_reset)


def test_repeated_evidence_gets_new_revision_and_never_duplicates_wire_identity() -> None:
    session = _session(
        NOW + timedelta(hours=1),
        NOW + timedelta(hours=1, seconds=1),
    )
    evidence = _evidence()
    first = session.compose(evidence)
    second = session.compose(evidence)
    assert (first.cut.revision, second.cut.revision) == (1, 2)
    assert first.cut != second.cut


def test_invalid_adapter_or_failed_composition_does_not_consume_revision() -> None:
    session = _session(NOW + timedelta(hours=1))

    class BadAdapter:
        def snapshot_evidence(self, *, epoch: int):
            assert epoch == 0
            return {"observed_at": NOW}

    with pytest.raises(TypeError, match="exact ReplaySnapshotEvidence"):
        session.compose_from(BadAdapter())
    assert session.revision == 0
    assert session.compose(_evidence()).cut.revision == 1


def test_adapter_receives_explicit_seek_epoch() -> None:
    seen: list[int] = []

    class Adapter:
        def snapshot_evidence(self, *, epoch: int) -> ReplaySnapshotEvidence:
            seen.append(epoch)
            return _evidence(NOW - timedelta(days=epoch))

    session = _session(
        NOW + timedelta(hours=1),
        NOW + timedelta(hours=1, seconds=1),
    )
    session.compose_from(Adapter())
    session.begin_seek_epoch()
    session.compose_from(Adapter())
    assert seen == [0, 1]


def test_adapter_cannot_reenter_seek_compose_or_close_and_epoch_stays_bound() -> None:
    blocked: list[str] = []
    session = _session(NOW + timedelta(hours=1))

    class Adapter:
        def snapshot_evidence(self, *, epoch: int) -> ReplaySnapshotEvidence:
            assert epoch == 0
            for name, action in (
                ("seek", session.begin_seek_epoch),
                ("compose", lambda: session.compose(_evidence())),
                ("close", session.close),
            ):
                with pytest.raises(RuntimeError, match="already in progress"):
                    action()
                blocked.append(name)
            return _evidence()

    snapshot = session.compose_from(Adapter())
    assert blocked == ["seek", "compose", "close"]
    assert session.epoch == 0
    assert snapshot.cut.source.endswith("/0000000000000000")


def test_uncaught_adapter_reentrancy_rejects_without_revision_or_epoch_change() -> None:
    session = _session(NOW + timedelta(hours=1))

    class Adapter:
        def snapshot_evidence(self, *, epoch: int) -> ReplaySnapshotEvidence:
            session.begin_seek_epoch()
            raise AssertionError("unreachable")

    with pytest.raises(RuntimeError, match="already in progress"):
        session.compose_from(Adapter())
    assert session.epoch == 0
    assert session.revision == 0


def test_concurrent_thread_seek_cannot_split_adapter_epoch_and_composed_source() -> None:
    entered = threading.Event()
    release = threading.Event()
    results = []
    session = _session(NOW + timedelta(hours=1))

    class Adapter:
        def snapshot_evidence(self, *, epoch: int) -> ReplaySnapshotEvidence:
            assert epoch == 0
            entered.set()
            assert release.wait(2)
            return _evidence()

    worker = threading.Thread(target=lambda: results.append(session.compose_from(Adapter())))
    worker.start()
    assert entered.wait(2)
    with pytest.raises(RuntimeError, match="already in progress"):
        session.begin_seek_epoch()
    release.set()
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert len(results) == 1
    assert results[0].cut.source.endswith("/0000000000000000")
    assert session.epoch == 0


@pytest.mark.asyncio
async def test_publish_failure_or_cancellation_never_retries_or_reuses_revision() -> None:
    entered = asyncio.Event()

    class Publisher:
        def __init__(self) -> None:
            self.snapshots = []

        async def publish_operator_snapshot(self, snapshot):
            self.snapshots.append(snapshot)
            if len(self.snapshots) == 1:
                entered.set()
                await asyncio.Event().wait()
            return False

    session = _session(
        NOW + timedelta(hours=1),
        NOW + timedelta(hours=1, seconds=1),
    )
    publisher = Publisher()
    task = asyncio.create_task(session.compose_and_publish(_evidence(), publisher))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert session.revision == 1

    with pytest.raises(ReplaySnapshotPublicationError):
        await session.compose_and_publish(_evidence(), publisher)
    assert session.revision == 2
    assert [snapshot.cut.revision for snapshot in publisher.snapshots] == [1, 2]


@pytest.mark.asyncio
async def test_seek_close_and_sync_compose_reject_during_publish_then_settle_after_cancel() -> None:
    entered = asyncio.Event()

    class Publisher:
        async def publish_operator_snapshot(self, _snapshot):
            entered.set()
            await asyncio.Event().wait()

    session = _session(NOW + timedelta(hours=1))
    task = asyncio.create_task(session.compose_and_publish(_evidence(), Publisher()))
    await entered.wait()
    for action in (
        session.begin_seek_epoch,
        session.close,
        lambda: session.compose(_evidence()),
    ):
        with pytest.raises(RuntimeError, match="already in progress"):
            action()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert session.begin_seek_epoch().endswith("/0000000000000001")
    session.close()


@pytest.mark.asyncio
async def test_concurrent_publications_are_serial_and_strictly_ordered() -> None:
    class Publisher:
        def __init__(self) -> None:
            self.revisions: list[int] = []

        async def publish_operator_snapshot(self, snapshot) -> bool:
            self.revisions.append(snapshot.cut.revision)
            await asyncio.sleep(0)
            return True

    session = _session(
        NOW + timedelta(hours=1),
        NOW + timedelta(hours=1, seconds=1),
    )
    publisher = Publisher()
    await asyncio.gather(
        session.compose_and_publish(_evidence(), publisher),
        session.compose_and_publish(_evidence(), publisher),
    )
    assert publisher.revisions == [1, 2]


def test_received_at_regression_fails_without_consuming_revision() -> None:
    session = _session(
        NOW + timedelta(hours=1),
        NOW + timedelta(hours=1),
        NOW + timedelta(hours=1, seconds=1),
    )
    assert session.compose(_evidence()).cut.revision == 1
    with pytest.raises(ValueError, match="increase strictly"):
        session.compose(_evidence())
    assert session.revision == 1
    assert session.compose(_evidence()).cut.revision == 2


def test_future_replay_evidence_is_rejected_without_clamping_or_revision_consumption() -> None:
    session = _session(
        NOW,
        NOW + timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="cannot be later"):
        session.compose(_evidence(NOW + timedelta(seconds=1)))
    assert session.revision == 0
    snapshot = session.compose(_evidence(NOW))
    assert snapshot.cut.revision == 1
    assert {summary.source_age_s for summary in snapshot.summaries()} == {1.0}


def test_end_of_stream_close_is_idempotent_and_prevents_seek_compose_or_publish() -> None:
    session = _session(NOW + timedelta(hours=1))
    session.close()
    session.close()
    with pytest.raises(RuntimeError, match="closed"):
        session.compose(_evidence())
    with pytest.raises(RuntimeError, match="closed"):
        session.begin_seek_epoch()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"archive_fingerprint": "A" * 64, "session_nonce": NONCE_A},
        {"archive_fingerprint": "a" * 63, "session_nonce": NONCE_A},
        {"archive_fingerprint": FINGERPRINT, "session_nonce": "x" * 32},
        {"archive_fingerprint": FINGERPRINT, "session_nonce": NONCE_A, "initial_revision": True},
    ],
)
def test_identity_and_revision_inputs_are_exact_and_bounded(kwargs) -> None:
    with pytest.raises(ValueError):
        ReplayOperatorSnapshotSession(**kwargs)


def test_evidence_rejects_naive_time_subclasses_and_malformed_reference() -> None:
    with pytest.raises(TypeError, match="timezone-aware"):
        ReplaySnapshotEvidence(datetime(2026, 1, 1))

    class DateSubclass(datetime):
        pass

    with pytest.raises(TypeError, match="exact"):
        ReplaySnapshotEvidence(DateSubclass(2026, 1, 1, tzinfo=UTC))
    with pytest.raises(ValueError, match="reference samples require"):
        ReplaySnapshotEvidence(NOW, cooldown_reference=(CooldownSample(0, 1),))


def test_session_atom_is_unwired_and_has_no_reading_gui_command_or_control_authority() -> None:
    root = Path(__file__).resolve().parents[2]
    module_path = root / "src/cryodaq/replay_engine/operator_snapshot_session.py"
    server_path = root / "src/cryodaq/replay_engine/server.py"
    tree = ast.parse(module_path.read_text())
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module is not None}
    assert not any(
        module.startswith(
            (
                "cryodaq.gui",
                "cryodaq.drivers",
                "cryodaq.safety",
                "cryodaq.core.broker",
                "cryodaq.replay_engine.sources",
            )
        )
        for module in imports
    )
    assert "operator_snapshot_session" not in server_path.read_text()
    calls = {
        node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not {"send_command", "start", "stop", "source_on", "source_off"} & calls
