from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from cryodaq.analytics.cooldown_service import CooldownService
from cryodaq.analytics.plugin_loader import PluginPipeline
from cryodaq.core.disk_monitor import DiskMonitor
from cryodaq.core.housekeeping import HousekeepingService
from cryodaq.core.interlock import InterlockEngine
from cryodaq.core.shutdown_settlement import (
    ShutdownOwnerSettledError,
    cancel_and_settle_tasks,
)
from cryodaq.notifications.composition_photo_handler import CompositionPhotoHandler
from cryodaq.notifications.periodic_report import PeriodicReporter
from cryodaq.notifications.telegram_commands import TelegramCommandBot


async def _terminal_failure(failure: BaseException) -> None:
    raise failure


async def test_cancel_and_settle_tasks_deduplicates_observes_failure_and_cancels_live_peer() -> None:
    exact_failure = ValueError("terminal child failure")
    failed = asyncio.create_task(_terminal_failure(exact_failure))
    await asyncio.sleep(0)
    cancellation_observed = asyncio.Event()

    async def live_peer() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancellation_observed.set()
            raise

    live = asyncio.create_task(live_peer())
    await asyncio.sleep(0)

    settlement = await cancel_and_settle_tasks((failed, live, failed))

    assert cancellation_observed.is_set()
    assert live.cancelled()
    assert settlement.failures == (exact_failure,)
    assert settlement.cancellation is None
    with pytest.raises(ShutdownOwnerSettledError, match="settled with failure") as raised:
        settlement.raise_if_unsuccessful()
    assert raised.value.failure is exact_failure


async def test_cancel_and_settle_tasks_defers_repeated_caller_cancellation_until_child_terminal() -> None:
    cancellation_observed = asyncio.Event()
    release = asyncio.Event()
    exact_failure = OSError("cancel handler failed")

    async def cancellation_resistant_child() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancellation_observed.set()
            await release.wait()
            raise exact_failure

    child = asyncio.create_task(cancellation_resistant_child())
    await asyncio.sleep(0)
    owner = asyncio.create_task(cancel_and_settle_tasks((child,)))
    await asyncio.wait_for(cancellation_observed.wait(), timeout=0.5)

    owner.cancel()
    await asyncio.sleep(0)
    owner.cancel()
    await asyncio.sleep(0)
    assert not owner.done()

    release.set()
    settlement = await asyncio.wait_for(owner, timeout=0.5)
    assert settlement.failures == (exact_failure,)
    assert isinstance(settlement.cancellation, asyncio.CancelledError)
    with pytest.raises(ShutdownOwnerSettledError) as raised:
        settlement.raise_if_unsuccessful()
    assert raised.value.failure is exact_failure


async def test_cancel_and_settle_tasks_rejects_ambiguous_owner_collections() -> None:
    empty = await cancel_and_settle_tasks(())
    assert empty.failures == ()
    assert empty.cancellation is None
    with pytest.raises(TypeError, match="exact tuple"):
        await cancel_and_settle_tasks([])  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="asyncio.Task"):
        await cancel_and_settle_tasks((object(),))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("owner_type", "task_attribute"),
    [
        (DiskMonitor, "_task"),
        (HousekeepingService, "_task"),
        (CompositionPhotoHandler, "_cleanup_task"),
    ],
)
async def test_single_task_stop_adapter_observes_done_failure_once_and_clears_exact_reference(
    owner_type: type[Any],
    task_attribute: str,
) -> None:
    owner = object.__new__(owner_type)
    owner._running = True
    exact_failure = RuntimeError(f"{owner_type.__name__} terminal failure")
    failed = asyncio.create_task(_terminal_failure(exact_failure))
    await asyncio.sleep(0)
    setattr(owner, task_attribute, failed)

    with pytest.raises(ShutdownOwnerSettledError) as raised:
        await owner.stop()
    assert raised.value.failure is exact_failure
    assert getattr(owner, task_attribute) is None

    await owner.stop()
    assert getattr(owner, task_attribute) is None


class _Broker:
    def __init__(self, *, remove_result: bool = True) -> None:
        self.calls: list[tuple[str, object | None]] = []
        self.remove_result = remove_result

    async def unsubscribe(self, name: str, *, expected_queue: object | None = None) -> bool:
        self.calls.append((name, expected_queue))
        return self.remove_result


@pytest.mark.parametrize(
    ("owner_type", "task_attributes", "subscription"),
    [
        (CooldownService, ("_consume_task", "_predict_task"), "cooldown_service"),
        (PluginPipeline, ("_process_task", "_watch_task"), "plugin_pipeline"),
    ],
)
async def test_multi_task_stop_adapter_attempts_dependency_cleanup_despite_terminal_child_failure(
    owner_type: type[Any],
    task_attributes: tuple[str, str],
    subscription: str,
) -> None:
    broker = _Broker()
    if owner_type is PluginPipeline:
        owner = PluginPipeline(broker, Path("unused"))
    else:
        owner = object.__new__(owner_type)
        owner._broker = broker
    owner._running = True
    exact_queue = object()
    owner._queue = exact_queue
    if owner_type is CooldownService:
        owner._executor_futures = set()
    exact_failure = RuntimeError(f"{owner_type.__name__} terminal failure")
    failed = asyncio.create_task(_terminal_failure(exact_failure))
    live = asyncio.create_task(asyncio.Event().wait())
    await asyncio.sleep(0)
    setattr(owner, task_attributes[0], failed)
    setattr(owner, task_attributes[1], live)

    with pytest.raises(ShutdownOwnerSettledError) as raised:
        await owner.stop()
    assert raised.value.failure is exact_failure
    assert live.cancelled()
    assert all(getattr(owner, attribute) is None for attribute in task_attributes)
    assert owner._queue is None
    assert owner._broker.calls == [(subscription, exact_queue)]

    await owner.stop()
    assert owner._broker.calls == [(subscription, exact_queue)]


async def test_interlock_stop_attempts_unsubscribe_before_reporting_terminal_child_failure() -> None:
    owner = object.__new__(InterlockEngine)
    owner._broker = _Broker()
    exact_queue = object()
    owner._queue = exact_queue
    exact_failure = RuntimeError("interlock terminal failure")
    owner._task = asyncio.create_task(_terminal_failure(exact_failure))
    await asyncio.sleep(0)

    with pytest.raises(ShutdownOwnerSettledError) as raised:
        await owner.stop()
    assert raised.value.failure is exact_failure
    assert owner._task is None
    assert owner._queue is None
    assert owner._broker.calls == [("interlock_engine", exact_queue)]


async def test_telegram_stop_settles_all_tasks_and_dependencies_before_reporting_child_failure() -> None:
    class _Session:
        closed = False
        close_calls = 0

        async def close(self) -> None:
            self.close_calls += 1
            self.closed = True

    owner = object.__new__(TelegramCommandBot)
    owner._broker = _Broker()
    exact_queue = object()
    owner._queue = exact_queue
    owner._session = _Session()
    owner._mutation_envelope = object()
    exact_failure = RuntimeError("telegram terminal failure")
    owner._collect_task = asyncio.create_task(_terminal_failure(exact_failure))
    owner._poll_task = asyncio.create_task(asyncio.Event().wait())
    owner._mutation_discovery_task = None
    await asyncio.sleep(0)

    with pytest.raises(ShutdownOwnerSettledError) as raised:
        await owner.stop()
    assert raised.value.failure is exact_failure
    assert owner._collect_task is None
    assert owner._poll_task is None
    assert owner._mutation_discovery_task is None
    assert owner._mutation_envelope is None
    assert owner._session is None
    assert owner._queue is None
    assert owner._broker.calls == [("telegram_commands", exact_queue)]


@pytest.mark.parametrize(
    ("owner_type", "subscription"),
    [
        (PluginPipeline, "plugin_pipeline"),
        (InterlockEngine, "interlock_engine"),
        (TelegramCommandBot, "telegram_commands"),
        (PeriodicReporter, "periodic_reporter"),
    ],
)
async def test_subscriber_stop_retains_exact_queue_when_replacement_owns_name(
    owner_type: type[Any],
    subscription: str,
) -> None:
    broker = _Broker(remove_result=False)
    if owner_type is PluginPipeline:
        owner = PluginPipeline(broker, Path("unused"))
    else:
        owner = object.__new__(owner_type)
        owner._broker = broker
    exact_queue = object()
    owner._queue = exact_queue

    if owner_type is PluginPipeline:
        owner._running = True
        owner._process_task = None
        owner._watch_task = None
    elif owner_type is InterlockEngine:
        owner._task = None
    elif owner_type is TelegramCommandBot:
        owner._collect_task = None
        owner._poll_task = None
        owner._mutation_discovery_task = None
        owner._mutation_envelope = None
        owner._session = None
    else:
        owner._collect_task = None
        owner._report_task = None
        owner._session = None

    with pytest.raises(RuntimeError) as raised:
        await owner.stop()

    if owner_type is TelegramCommandBot:
        assert "shutdown dependencies remain unsettled" in str(raised.value)
        assert raised.value.__cause__ is not None
        assert "exact queue owner" in str(raised.value.__cause__)
    else:
        assert "exact queue owner" in str(raised.value)
    assert owner._queue is exact_queue
    assert owner._broker.calls == [(subscription, exact_queue)]
