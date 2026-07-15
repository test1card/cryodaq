from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from cryodaq.engine import (
    EngineCommandContext,
    _feed_recording_experiment_lifecycle,
    _run_engine,
    _seed_recording_lifecycle,
    _start_scheduler_with_recording_feed,
    _stop_scheduler_with_recording_feed,
)


def _context(manager: object, feed: object) -> EngineCommandContext:
    values = {
        field: MagicMock()
        for field in EngineCommandContext.__dataclass_fields__
        if field
        not in {
            "leak_cfg",
            "alarm_dispatch_tasks",
            "drivers_by_name",
            "multiline_burst_auto_stop_meta",
            "multiline_burst_auto_stop_tasks",
        }
    }
    values.update(
        leak_cfg={},
        alarm_dispatch_tasks=set(),
        drivers_by_name={},
        multiline_burst_auto_stop_meta={},
        multiline_burst_auto_stop_tasks={},
        experiment_manager=manager,
        recording_lifecycle_feed=feed,
    )
    return EngineCommandContext(**values)


async def test_active_lifecycle_mapping_runs_on_the_engine_loop() -> None:
    loop = asyncio.get_running_loop()
    manager = MagicMock()
    manager.snapshot_operator_experiment.return_value = SimpleNamespace(
        revision=7,
        experiment_id="exp-7",
        experiment_name="Cooldown",
        phase="vacuum",
    )
    feed = MagicMock()
    observed_loops: list[bool] = []
    feed.experiment_active.side_effect = lambda *_args: observed_loops.append(asyncio.get_running_loop() is loop)
    context = _context(manager, feed)

    for action in ("experiment_create", "experiment_start", "experiment_update"):
        _feed_recording_experiment_lifecycle(
            context,
            action,
            {"ok": True, "experiment": {"experiment_id": "exp-7"}},
        )
    _feed_recording_experiment_lifecycle(context, "experiment_advance_phase", {"ok": True, "phase": {}})

    assert feed.experiment_active.call_args_list == [call(7, "exp-7", "Cooldown", "vacuum")] * 4
    assert observed_loops == [True] * 4


@pytest.mark.parametrize(
    ("action", "expected_method"),
    [
        ("experiment_finalize", "experiment_finalized"),
        ("experiment_stop", "experiment_finalized"),
        ("experiment_abort", "experiment_aborted"),
    ],
)
async def test_terminal_mapping_uses_exact_result_identity(action: str, expected_method: str) -> None:
    manager = MagicMock()
    manager.snapshot_operator_experiment.return_value = SimpleNamespace(
        revision=8,
        experiment_id=None,
        experiment_name=None,
        phase=None,
    )
    feed = MagicMock()

    _feed_recording_experiment_lifecycle(
        _context(manager, feed),
        action,
        {"ok": True, "experiment": {"experiment_id": "exp-7"}},
    )

    getattr(feed, expected_method).assert_called_once_with(8, "exp-7")


async def test_feed_fault_cannot_roll_back_a_successful_command(caplog: pytest.LogCaptureFixture) -> None:
    manager = MagicMock()
    manager.snapshot_operator_experiment.return_value = SimpleNamespace(
        revision=2,
        experiment_id="exp-2",
        experiment_name="Run",
        phase=None,
    )
    feed = MagicMock()
    feed.experiment_active.side_effect = RuntimeError("feed fault")
    result = {"ok": True, "experiment": {"experiment_id": "exp-2"}}

    _feed_recording_experiment_lifecycle(_context(manager, feed), "experiment_update", result)

    assert result == {"ok": True, "experiment": {"experiment_id": "exp-2"}}
    assert "feed fault" in caplog.text


async def test_boot_seed_preserves_active_or_inactive_manager_truth() -> None:
    feed = MagicMock()
    manager = MagicMock()
    manager.snapshot_operator_experiment.return_value = SimpleNamespace(
        revision=3,
        experiment_id="exp-3",
        experiment_name="Warmup",
        phase="prepare",
    )
    _seed_recording_lifecycle(feed, manager)
    feed.experiment_active.assert_called_once_with(3, "exp-3", "Warmup", "prepare")

    feed.reset_mock()
    manager.snapshot_operator_experiment.return_value = SimpleNamespace(
        revision=4,
        experiment_id=None,
        experiment_name=None,
        phase=None,
    )
    _seed_recording_lifecycle(feed, manager)
    feed.experiment_inactive.assert_called_once_with(4)


async def test_scheduler_feed_follows_success_and_uses_one_bounded_epoch() -> None:
    events: list[str] = []
    scheduler = MagicMock()
    scheduler.start = AsyncMock(side_effect=lambda: events.append("start"))
    scheduler.stop = AsyncMock(side_effect=lambda: events.append("stop"))
    feed = MagicMock()
    feed.persistence_started.side_effect = lambda *_args: events.append("persistence_started")
    feed.acquisition_running.side_effect = lambda *_args: events.append("running")
    feed.acquisition_stopped.side_effect = lambda *_args: events.append("stopped")
    feed.persistence_stopped.side_effect = lambda *_args: events.append("persistence_stopped")

    sequence = await _start_scheduler_with_recording_feed(scheduler, feed, 0)
    sequence = await _stop_scheduler_with_recording_feed(scheduler, feed, sequence)

    assert sequence == 2
    assert events == ["persistence_started", "start", "running", "stop", "stopped", "persistence_stopped"]
    epoch = feed.acquisition_running.call_args.args[1]
    assert len(epoch) == 32
    assert all(character in "0123456789abcdef" for character in epoch)
    feed.persistence_started.assert_called_once_with(epoch)
    feed.acquisition_stopped.assert_called_once_with(2)


async def test_persistence_feed_failure_cannot_block_scheduler_start(caplog: pytest.LogCaptureFixture) -> None:
    scheduler = MagicMock()
    scheduler.start = AsyncMock()
    feed = MagicMock()
    feed.persistence_started.side_effect = RuntimeError("dark feed failed")

    sequence = await _start_scheduler_with_recording_feed(scheduler, feed, 0)

    assert sequence == 1
    scheduler.start.assert_awaited_once_with()
    feed.acquisition_running.assert_called_once()
    feed.persistence_ambiguous.assert_called_once_with()
    assert "dark feed failed" in caplog.text


async def test_stop_callbacks_are_isolated_and_acquisition_failure_is_terminalized() -> None:
    scheduler = MagicMock()
    scheduler.stop = AsyncMock()
    feed = MagicMock()
    feed.acquisition_stopped.side_effect = RuntimeError("acquisition observer failed")

    sequence = await _stop_scheduler_with_recording_feed(scheduler, feed, 1)

    assert sequence == 3
    feed.acquisition_stopped.assert_called_once_with(2)
    feed.acquisition_unavailable.assert_called_once_with(3)
    feed.persistence_stopped.assert_called_once_with()


async def test_persistence_stop_failure_cannot_skip_its_terminal_fallback() -> None:
    scheduler = MagicMock()
    scheduler.stop = AsyncMock()
    feed = MagicMock()
    feed.persistence_stopped.side_effect = RuntimeError("persistence observer failed")

    sequence = await _stop_scheduler_with_recording_feed(scheduler, feed, 1)

    assert sequence == 2
    feed.acquisition_stopped.assert_called_once_with(2)
    feed.persistence_stopped.assert_called_once_with()
    feed.persistence_ambiguous.assert_called_once_with()


@pytest.mark.parametrize(("operation", "sequence"), [("start", 0), ("stop", 1)])
async def test_scheduler_failure_feeds_unavailable_and_preserves_failure(operation: str, sequence: int) -> None:
    scheduler = MagicMock()
    scheduler.start = AsyncMock()
    scheduler.stop = AsyncMock()
    original = RuntimeError(f"{operation} failed")
    getattr(scheduler, operation).side_effect = original
    feed = MagicMock()

    helper = _start_scheduler_with_recording_feed if operation == "start" else _stop_scheduler_with_recording_feed
    with pytest.raises(RuntimeError) as caught:
        await helper(scheduler, feed, sequence)

    assert caught.value is original
    feed.acquisition_unavailable.assert_called_once_with(sequence + 1)
    feed.persistence_ambiguous.assert_called_once_with()
    feed.acquisition_running.assert_not_called()
    feed.acquisition_stopped.assert_not_called()


def test_production_wiring_uses_direct_persistence_observation_without_publication_or_control() -> None:
    source = inspect.getsource(_run_engine)
    assert source.index("recording_lifecycle_feed = RecordingLifecycleFeed(") < source.index("EngineCommandContext(")
    assert "persistence_freshness_s=persistence_freshness_s" in source
    assert "persistence_commit_observer=recording_lifecycle_feed.persistence_committed" in source
    assert "_start_scheduler_with_recording_feed(" in source
    assert "_stop_scheduler_with_recording_feed(" in source

    bridge_source = "\n".join(
        inspect.getsource(operation)
        for operation in (
            _feed_recording_experiment_lifecycle,
            _start_scheduler_with_recording_feed,
            _stop_scheduler_with_recording_feed,
        )
    )
    assert "persistence_started" in bridge_source
    assert "persistence_stopped" in bridge_source
    for forbidden in ("publisher", "zmq", "gui", "control"):
        assert forbidden not in bridge_source.lower()
