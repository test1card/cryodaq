from __future__ import annotations

import asyncio
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from cryodaq.engine_wiring.operator_snapshot_authorities import (
    AlarmAttentionReceipt,
    AlarmEvidence,
    AttentionEvidence,
    AuthorityAvailability,
    CommonCut,
    CooldownPoint,
    CooldownReceipt,
    ExperimentReceipt,
    InfrastructureEvidence,
    InfrastructureReceipt,
    IntegrityPersistenceReceipt,
    PlantHealthEvidence,
    SafetyReadinessReceipt,
    SupportEntryEvidence,
    SupportManifestEvidence,
    SupportReceipt,
    UnavailableAlarmAttentionAuthority,
    UnavailableCooldownAuthority,
    UnavailableInfrastructureAuthority,
    UnavailableSupportAuthority,
)
from cryodaq.engine_wiring.operator_snapshot_composer import OperatorSnapshotComposer
from cryodaq.operator_snapshot import (
    AvailabilityTruth,
    OperatorPresentationState,
    ReadinessTruth,
    RecordingTruth,
    SafetyLifecycle,
    SnapshotMode,
)
from cryodaq.storage.operator_snapshot_revision import OperatorSnapshotRevisionAllocator, SnapshotRevision

NOW = datetime(2026, 7, 12, 4, 0, tzinfo=UTC)
HASH = "b" * 64
LEADERSHIP = "1" * 32


def _base(cut: CommonCut, revision: int = 1) -> dict[str, object]:
    return {
        "cut": cut,
        "revision": revision,
        "token": f"authority-v1:{revision}:{HASH}",
        "availability": AuthorityAvailability.AVAILABLE,
    }


class _Authority:
    def __init__(self, factory: Any, calls: list[CommonCut] | None = None) -> None:
        self.factory = factory
        self.calls = [] if calls is None else calls

    def snapshot_for_cut(self, cut: CommonCut) -> Any:
        self.calls.append(cut)
        return self.factory(cut)


class _Allocator:
    def __init__(self, revisions: list[SnapshotRevision | BaseException], events: list[str] | None = None) -> None:
        self.revisions = revisions
        self.calls = 0
        self.events = events

    async def allocate_async(self, *, not_before: datetime | None = None) -> SnapshotRevision:
        self.calls += 1
        if self.events is not None:
            self.events.append("allocate")
        result = self.revisions.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def _safety(cut: CommonCut) -> SafetyReadinessReceipt:
    return SafetyReadinessReceipt(
        **_base(cut),
        readiness=ReadinessTruth.READY,
        lifecycle=SafetyLifecycle.READY,
        verified_off=True,
        plant_health=(PlantHealthEvidence("storage", "Storage", OperatorPresentationState.OK, "storage_ok"),),
    )


def _attention(cut: CommonCut) -> AlarmAttentionReceipt:
    return AlarmAttentionReceipt(
        **_base(cut),
        alarms=(AlarmEvidence("pressure_high", "WARNING", cut.observed_at, False),),
        attention=(
            AttentionEvidence(
                "inspect-vacuum",
                OperatorPresentationState.CAUTION,
                "Inspect vacuum",
                "Review the vacuum trend",
                cut.observed_at,
            ),
        ),
    )


def _experiment(cut: CommonCut) -> ExperimentReceipt:
    return ExperimentReceipt(
        **_base(cut),
        experiment_id="exp-1",
        experiment_name="Cooldown",
        phase="cooldown",
        recording=RecordingTruth.NOT_RECORDING,
    )


def _integrity(cut: CommonCut) -> IntegrityPersistenceReceipt:
    return IntegrityPersistenceReceipt(
        **_base(cut),
        persisted_revision=8,
        archive_revision=7,
        pending_records=0,
        dropped_records=0,
        storage=AvailabilityTruth.AVAILABLE,
    )


def _cooldown(cut: CommonCut) -> CooldownReceipt:
    return CooldownReceipt(
        **_base(cut),
        samples=(CooldownPoint(0.0, 300.0), CooldownPoint(1.0, 299.0)),
    )


def _infrastructure(cut: CommonCut) -> InfrastructureReceipt:
    return InfrastructureReceipt(
        **_base(cut),
        nodes=(InfrastructureEvidence("ups-1", "UPS", OperatorPresentationState.OK, "ups_ok"),),
    )


def _support(cut: CommonCut) -> SupportReceipt:
    manifest = SupportManifestEvidence(
        "bundle-1",
        cut.observed_at,
        (SupportEntryEvidence("logs/engine.txt", 10, "c" * 64),),
        "d" * 64,
    )
    return SupportReceipt(**_base(cut), capture_available=True, manifest=manifest)


def _composer(
    allocator: Any,
    *,
    safety: Any = _safety,
    attention: Any = _attention,
    experiment: Any = _experiment,
    integrity: Any = _integrity,
    cooldown: Any = _cooldown,
    infrastructure: Any = _infrastructure,
    support: Any = _support,
    calls: dict[str, list[CommonCut]] | None = None,
) -> OperatorSnapshotComposer:
    calls = {} if calls is None else calls

    def authority(name: str, factory: Any) -> _Authority:
        calls[name] = []
        return _Authority(factory, calls[name])

    return OperatorSnapshotComposer(
        safety=authority("safety", safety),
        attention=authority("attention", attention),
        experiment=authority("experiment", experiment),
        integrity=authority("integrity", integrity),
        cooldown=authority("cooldown", cooldown),
        infrastructure=authority("infrastructure", infrastructure),
        support=authority("support", support),
        revision_allocator=allocator,
        leadership_id=LEADERSHIP,
        clock=lambda: NOW + timedelta(seconds=1),
    )


@pytest.mark.asyncio
async def test_complete_snapshot_has_one_cut_eight_detached_summaries_and_stable_leadership() -> None:
    allocation = SnapshotRevision(41, NOW + timedelta(seconds=2))
    allocator = _Allocator([allocation, SnapshotRevision(42, NOW + timedelta(seconds=3))])
    calls: dict[str, list[CommonCut]] = {}
    composer = _composer(allocator, calls=calls)

    first = await composer.compose(NOW)
    second = await composer.compose(NOW + timedelta(seconds=1))

    assert first.cut.revision == 41
    assert first.cut.source == second.cut.source == f"engine/operator-snapshot-v1/{LEADERSHIP}"
    assert composer.mode is first.cut.mode is second.cut.mode is SnapshotMode.LIVE
    assert len(first.summaries()) == 8
    assert all(summary.cut is first.cut for summary in first.summaries())
    assert all(summary.source_age_s == 2.0 for summary in first.summaries())
    assert len({values[0] for values in calls.values()}) == 1
    assert {values[0].generation for values in calls.values()} == {1}
    assert {values[1].generation for values in calls.values()} == {2}
    assert first.plant_health.subsystems[0] is not _safety(calls["safety"][0]).plant_health[0]
    assert first.attention.items[0].detail == "pressure_high"
    assert first.attention.items[0].state is OperatorPresentationState.WARNING
    assert first.support_bundle.manifest is not None
    assert first.support_bundle.manifest.entries[0].path == "logs/engine.txt"


@pytest.mark.asyncio
async def test_all_authorities_are_sampled_synchronously_before_one_allocation() -> None:
    events: list[str] = []

    def recorded(name: str, factory: Any) -> Any:
        def sample(cut: CommonCut) -> Any:
            events.append(name)
            return factory(cut)

        return sample

    allocator = _Allocator([SnapshotRevision(1, NOW)], events)
    composer = _composer(
        allocator,
        safety=recorded("safety", _safety),
        attention=recorded("attention", _attention),
        experiment=recorded("experiment", _experiment),
        integrity=recorded("integrity", _integrity),
        cooldown=recorded("cooldown", _cooldown),
        infrastructure=recorded("infrastructure", _infrastructure),
        support=recorded("support", _support),
    )

    await composer.compose(NOW)
    assert events == [
        "safety",
        "attention",
        "experiment",
        "integrity",
        "cooldown",
        "infrastructure",
        "support",
        "allocate",
    ]


@pytest.mark.parametrize("missing", ["attention", "cooldown", "infrastructure", "support"])
@pytest.mark.asyncio
async def test_reviewed_missing_f36_authorities_are_explicit_and_never_empty_ok(missing: str) -> None:
    factories = {
        "attention": lambda cut: UnavailableAlarmAttentionAuthority().snapshot_for_cut(cut),
        "cooldown": lambda cut: UnavailableCooldownAuthority().snapshot_for_cut(cut),
        "infrastructure": lambda cut: UnavailableInfrastructureAuthority().snapshot_for_cut(cut),
        "support": lambda cut: UnavailableSupportAuthority().snapshot_for_cut(cut),
    }
    allocator = _Allocator([SnapshotRevision(1, NOW)])
    composer = _composer(allocator, **{missing: factories[missing]})

    snapshot = await composer.compose(NOW)
    summary = {
        "attention": snapshot.attention,
        "cooldown": snapshot.cooldown_history,
        "infrastructure": snapshot.infrastructure,
        "support": snapshot.support_bundle,
    }[missing]
    assert summary.state is OperatorPresentationState.CAUTION
    assert summary.reason_codes == (f"{missing}_authority_unavailable",)
    assert summary.state is not OperatorPresentationState.OK
    if missing == "support":
        assert snapshot.support_bundle.availability is AvailabilityTruth.UNKNOWN


@pytest.mark.asyncio
async def test_validation_failure_does_not_allocate_for_mismatch_unavailable_future_or_subclass() -> None:
    allocator = _Allocator([SnapshotRevision(1, NOW)])

    def mandatory_unavailable(cut: CommonCut) -> SafetyReadinessReceipt:
        return SafetyReadinessReceipt(
            cut=cut,
            revision=0,
            token=f"authority-v1:0:{HASH}",
            availability=AuthorityAvailability.UNAVAILABLE,
            unavailable_reason="safety_not_sampled",
        )

    with pytest.raises(ValueError, match="mandatory.*unavailable"):
        await _composer(allocator, safety=mandatory_unavailable).compose(NOW)
    assert allocator.calls == 0

    other_cut = CommonCut(99, f"cut-v1:99:{'a' * 64}", NOW)
    with pytest.raises(ValueError, match="same common cut"):
        await _composer(allocator, attention=lambda _cut: _attention(other_cut)).compose(NOW)
    assert allocator.calls == 0

    with pytest.raises(ValueError, match="future"):
        await _composer(allocator).compose(NOW + timedelta(seconds=2))
    assert allocator.calls == 0

    class ReceiptSubclass(SafetyReadinessReceipt):
        pass

    def subclass(cut: CommonCut) -> ReceiptSubclass:
        source = _safety(cut)
        return ReceiptSubclass(
            cut=source.cut,
            revision=source.revision,
            token=source.token,
            availability=source.availability,
            readiness=source.readiness,
            lifecycle=source.lifecycle,
            verified_off=source.verified_off,
            blockers=source.blockers,
            plant_health=source.plant_health,
        )

    with pytest.raises(TypeError, match="exact detached"):
        await _composer(allocator, safety=subclass).compose(NOW)
    assert allocator.calls == 0


@pytest.mark.asyncio
async def test_ready_without_verified_off_and_unreviewed_optional_unavailable_reason_fail_before_allocation() -> None:
    allocator = _Allocator([SnapshotRevision(1, NOW)])

    def unsafe_ready(cut: CommonCut) -> SafetyReadinessReceipt:
        return SafetyReadinessReceipt(
            **_base(cut), readiness=ReadinessTruth.READY, lifecycle=SafetyLifecycle.READY, verified_off=False
        )

    with pytest.raises(ValueError, match="verified-OFF"):
        await _composer(allocator, safety=unsafe_ready).compose(NOW)

    def unreviewed_attention(cut: CommonCut) -> AlarmAttentionReceipt:
        return AlarmAttentionReceipt(
            cut=cut,
            revision=0,
            token=f"authority-v1:0:{HASH}",
            availability=AuthorityAvailability.UNAVAILABLE,
            unavailable_reason="temporary_error",
        )

    with pytest.raises(ValueError, match="unreviewed reason"):
        await _composer(allocator, attention=unreviewed_attention).compose(NOW)
    assert allocator.calls == 0


@pytest.mark.asyncio
async def test_allocator_cancellation_after_commit_leaves_gap_and_next_cut_never_reuses_it(tmp_path: Path) -> None:
    class BlockingAfterCommit(OperatorSnapshotRevisionAllocator):
        def __init__(self, root: Path) -> None:
            super().__init__(root, clock=lambda: NOW + timedelta(seconds=1))
            self.entered = threading.Event()
            self.release = threading.Event()

        def allocate(self, *, not_before: datetime | None = None) -> SnapshotRevision:
            result = super().allocate(not_before=not_before)
            self.entered.set()
            assert self.release.wait(5)
            return result

    allocator = BlockingAfterCommit(tmp_path)
    calls: dict[str, list[CommonCut]] = {}
    composer = _composer(allocator, calls=calls)

    task = asyncio.create_task(composer.compose(NOW))
    assert await asyncio.to_thread(allocator.entered.wait, 5)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    follower = asyncio.create_task(composer.compose(NOW))
    await asyncio.sleep(0)
    assert [cut.generation for cut in calls["safety"]] == [1]
    allocator.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    snapshot = await follower

    assert snapshot.cut.revision == 2
    assert [cut.generation for cut in calls["safety"]] == [1, 2]
    assert calls["safety"][0].token != calls["safety"][1].token


@pytest.mark.asyncio
async def test_concurrent_compositions_keep_sampling_and_revision_order() -> None:
    class ReorderingAllocator:
        def __init__(self) -> None:
            self.calls = 0
            self.committed = 0
            self.first_entered = asyncio.Event()
            self.release_first = asyncio.Event()

        async def allocate_async(self, *, not_before: datetime | None = None) -> SnapshotRevision:
            assert not_before is not None
            self.calls += 1
            if self.calls == 1:
                self.first_entered.set()
                await self.release_first.wait()
            self.committed += 1
            return SnapshotRevision(self.committed, not_before)

    allocator = ReorderingAllocator()
    calls: dict[str, list[CommonCut]] = {}
    composer = _composer(allocator, calls=calls)
    first = asyncio.create_task(composer.compose(NOW))
    await allocator.first_entered.wait()
    second = asyncio.create_task(composer.compose(NOW + timedelta(seconds=1)))
    await asyncio.sleep(0)

    assert allocator.calls == 1
    assert [cut.generation for cut in calls["safety"]] == [1]
    allocator.release_first.set()
    first_snapshot, second_snapshot = await asyncio.gather(first, second)

    assert [first_snapshot.cut.revision, second_snapshot.cut.revision] == [1, 2]
    assert first_snapshot.cut.observed_at < second_snapshot.cut.observed_at
    assert [cut.generation for cut in calls["safety"]] == [1, 2]


@pytest.mark.asyncio
async def test_slow_durable_allocation_does_not_delay_event_loop_timer(tmp_path: Path) -> None:
    class SlowAllocator(OperatorSnapshotRevisionAllocator):
        def allocate(self, *, not_before: datetime | None = None) -> SnapshotRevision:
            time.sleep(0.1)
            return super().allocate(not_before=not_before)

    composer = _composer(
        SlowAllocator(tmp_path, clock=lambda: NOW + timedelta(seconds=1)),
    )
    started = time.monotonic()
    task = asyncio.create_task(composer.compose(NOW))
    await asyncio.sleep(0.01)
    elapsed = time.monotonic() - started

    assert elapsed < 0.06
    assert not task.done()
    snapshot = await task
    assert snapshot.cut.revision == 1


def test_finalize_detaches_received_at_and_rejects_subclass_or_foreign_prepared_cut() -> None:
    allocation_time = NOW + timedelta(seconds=1)
    composer = _composer(_Allocator([]))
    prepared = composer.prepare(NOW)
    allocation = SnapshotRevision(5, allocation_time)

    snapshot = composer.finalize(prepared, allocation)
    assert snapshot.cut.received_at == allocation.received_at
    assert snapshot.cut.received_at is not allocation.received_at
    assert type(snapshot.cut.received_at) is datetime

    class RevisionSubclass(SnapshotRevision):
        pass

    hostile = RevisionSubclass(6, allocation_time)
    with pytest.raises(TypeError, match="exact SnapshotRevision"):
        composer.finalize(prepared, hostile)
    foreign = _composer(_Allocator([]))
    with pytest.raises(TypeError, match="belong"):
        foreign.finalize(prepared, allocation)


def test_leaf_import_does_not_activate_engine_runtime_gui_transport_or_drivers() -> None:
    project_root = Path(__file__).resolve().parents[2]
    source_root = project_root / "src"
    code = f"""
import json, sys
sys.path.insert(0, {str(source_root)!r})
import cryodaq.engine_wiring.operator_snapshot_composer
forbidden = [
    name for name in sys.modules
    if name.startswith(('cryodaq.engine_wiring.runtime_tasks', 'cryodaq.gui', 'cryodaq.core.zmq'))
    or name.startswith('cryodaq.drivers')
]
print(json.dumps(forbidden))
"""
    completed = __import__("subprocess").run(
        [sys.executable, "-I", "-c", code],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=True,
    )
    assert completed.stdout.strip() == "[]"
