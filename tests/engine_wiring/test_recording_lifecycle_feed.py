from __future__ import annotations

import asyncio
import copy
import inspect
import pickle
import threading

import pytest

import cryodaq.engine_wiring.recording_lifecycle_feed as module
from cryodaq.engine_wiring.experiment_recording_owner import ExperimentOperation
from cryodaq.engine_wiring.recording_lifecycle_feed import RecordingLifecycleFeed
from cryodaq.operator_snapshot import RecordingTruth


@pytest.fixture
async def feed() -> RecordingLifecycleFeed:
    return RecordingLifecycleFeed()


def test_requires_a_running_loop() -> None:
    with pytest.raises(RuntimeError, match="running engine loop"):
        RecordingLifecycleFeed()


async def test_create_phase_finalize_and_replay_are_monotonic_and_dark(
    feed: RecordingLifecycleFeed,
) -> None:
    cold = feed.snapshot()
    created = feed.experiment_active(1, "exp-1", "Cooldown", "vacuum")
    assert created.generation_id == cold.generation_id
    assert created.experiment_revision == 1
    assert created.recording is RecordingTruth.NOT_RECORDING
    assert feed.experiment_active(1, "exp-1", "Cooldown", "vacuum") is created

    phased = feed.experiment_active(2, "exp-1", "Cooldown", "cooldown")
    assert phased.experiment_revision == 2
    assert phased.phase == "cooldown"
    assert feed.experiment_active(2, "exp-1", "Cooldown", "cooldown") is phased

    finalized = feed.experiment_finalized(3, "exp-1")
    assert finalized.experiment_revision == 3
    assert finalized.experiment_operation is ExperimentOperation.FINALIZED
    assert finalized.recording is RecordingTruth.NOT_RECORDING
    assert feed.experiment_finalized(3, "exp-1") is finalized
    with pytest.raises(ValueError, match="revision regression"):
        feed.experiment_active(1, "exp-1", "stale replay")


async def test_abort_and_inactive_are_idempotent_and_reject_wrong_identity(
    feed: RecordingLifecycleFeed,
) -> None:
    inactive = feed.experiment_inactive(1)
    assert inactive.revision == 1
    assert inactive.reason == "experiment_inactive"
    assert feed.experiment_inactive(1) is inactive
    feed.experiment_active(2, "exp-1", "Run")
    with pytest.raises(ValueError, match="exact active experiment"):
        feed.experiment_aborted(3, "exp-other")
    aborted = feed.experiment_aborted(3, "exp-1")
    assert aborted.experiment_operation is ExperimentOperation.INACTIVE
    assert aborted.experiment_revision == 3
    assert feed.experiment_aborted(3, "exp-1") is aborted
    inactive_again = feed.experiment_inactive(4)
    assert feed.experiment_inactive(4) is inactive_again


async def test_active_identity_cannot_regress_or_be_replaced(feed: RecordingLifecycleFeed) -> None:
    feed.experiment_active(1, "exp-1", "Run", "one")
    feed.experiment_active(2, "exp-1", "Run", "two")
    with pytest.raises(ValueError, match="revision regression"):
        feed.experiment_active(1, "exp-0", "stale", "one")
    with pytest.raises(ValueError, match="cannot be replaced"):
        feed.experiment_active(3, "exp-0", "replacement", "one")
    with pytest.raises(ValueError, match="exact active experiment"):
        feed.experiment_finalized(3, "exp-0")
    assert feed.snapshot().experiment_revision == 2
    assert feed.snapshot().phase == "two"


async def test_acquisition_start_stop_unavailable_preserve_epoch_and_idempotence(
    feed: RecordingLifecycleFeed,
) -> None:
    running = feed.acquisition_running(1, "acquisition-epoch-1")
    assert running.acquisition_epoch_id == "acquisition-epoch-1"
    assert running.acquisition_revision == 1
    assert feed.acquisition_running(1, "acquisition-epoch-1") is running
    with pytest.raises(ValueError, match="cannot be replaced"):
        feed.acquisition_running(2, "acquisition-epoch-2")

    stopped = feed.acquisition_stopped(2)
    assert stopped.acquisition_epoch_id is None
    assert stopped.acquisition_revision == 2
    assert feed.acquisition_stopped(2) is stopped
    after_experiment = feed.experiment_inactive(1)
    assert feed.acquisition_stopped(2) is after_experiment
    assert feed.snapshot().acquisition_revision == 2
    with pytest.raises(ValueError, match="revision regression"):
        feed.acquisition_running(1, "acquisition-epoch-1")
    unavailable = feed.acquisition_unavailable(3)
    assert unavailable.acquisition_revision == 3
    assert unavailable.reason == "acquisition_unavailable"
    assert feed.acquisition_unavailable(3) is unavailable


async def test_multi_cycle_replay_and_same_revision_equivocation_fail_closed(
    feed: RecordingLifecycleFeed,
) -> None:
    feed.experiment_active(1, "exp-1", "One")
    feed.experiment_finalized(2, "exp-1")
    feed.experiment_active(3, "exp-2", "Two")
    feed.experiment_inactive(4)
    with pytest.raises(ValueError, match="revision regression"):
        feed.experiment_active(1, "exp-1", "One")
    with pytest.raises(ValueError, match="same-revision equivocation"):
        feed.experiment_active(4, "exp-1", "One")

    feed.acquisition_running(1, "epoch-1")
    feed.acquisition_stopped(2)
    feed.acquisition_running(3, "epoch-2")
    feed.acquisition_unavailable(4)
    with pytest.raises(ValueError, match="revision regression"):
        feed.acquisition_running(1, "epoch-1")
    with pytest.raises(ValueError, match="same-revision equivocation"):
        feed.acquisition_stopped(4)


async def test_missing_persistence_can_never_claim_recording(feed: RecordingLifecycleFeed) -> None:
    feed.experiment_active(1, "exp-1", "Run")
    feed.acquisition_running(1, "acquisition-epoch-1")
    snapshot = feed.snapshot()
    assert snapshot.persistence_revision == 0
    assert snapshot.persistence_epoch_id is None
    assert snapshot.recording is RecordingTruth.NOT_RECORDING
    assert RecordingLifecycleFeed.grants_control_authority is False


async def _call_from_other_loop(feed: RecordingLifecycleFeed) -> None:
    feed.snapshot()


async def test_rejects_other_thread_and_event_loop(feed: RecordingLifecycleFeed) -> None:
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            asyncio.run(_call_from_other_loop(feed))
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeError)
    assert "thread" in str(errors[0])


async def test_rejects_process_identity_change(feed: RecordingLifecycleFeed, monkeypatch: pytest.MonkeyPatch) -> None:
    creator_pid = module.os.getpid()
    monkeypatch.setattr(module.os, "getpid", lambda: creator_pid + 1)
    with pytest.raises(RuntimeError, match="process boundary"):
        feed.snapshot()


async def test_cancelled_adjacent_callback_cannot_publish(feed: RecordingLifecycleFeed) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    async def delayed_callback() -> None:
        entered.set()
        await release.wait()
        feed.experiment_active(1, "exp-1", "late")

    task = asyncio.create_task(delayed_callback())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert feed.snapshot().revision == 0


async def test_bridge_is_noncloneable_and_has_no_async_or_control_surface(
    feed: RecordingLifecycleFeed,
) -> None:
    for operation in (copy.copy, copy.deepcopy, pickle.dumps):
        with pytest.raises(TypeError):
            operation(feed)
    public = {name for name, _ in inspect.getmembers(RecordingLifecycleFeed) if not name.startswith("_")}
    assert public == {
        "acquisition_running",
        "acquisition_stopped",
        "acquisition_unavailable",
        "experiment_aborted",
        "experiment_active",
        "experiment_finalized",
        "experiment_inactive",
        "grants_control_authority",
        "persistence_ambiguous",
        "persistence_committed",
        "persistence_rejected",
        "persistence_snapshot",
        "persistence_started",
        "persistence_stopped",
        "snapshot",
    }
    assert not any(inspect.iscoroutinefunction(value) for value in RecordingLifecycleFeed.__dict__.values())
