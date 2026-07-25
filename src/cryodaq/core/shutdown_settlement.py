"""Cancellation-resistant settlement primitives for retained asyncio owners."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any


class ShutdownOwnerSettledError(RuntimeError):
    """A retained owner is terminal, but its terminal result was failure."""

    def __init__(self, failure: BaseException) -> None:
        super().__init__("shutdown owner settled with failure")
        self.failure = failure


@dataclass(frozen=True, slots=True)
class CancelledTaskSettlement:
    """Exact terminal results after cancelling and observing retained tasks."""

    failures: tuple[BaseException, ...] = ()
    cancellation: asyncio.CancelledError | None = None

    def raise_if_unsuccessful(self) -> None:
        if self.failures:
            raise ShutdownOwnerSettledError(self.failures[0])
        if self.cancellation is not None:
            raise self.cancellation


async def cancel_and_settle_tasks(
    tasks: tuple[asyncio.Task[object], ...],
) -> CancelledTaskSettlement:
    """Cancel live tasks, observe every terminal result, and survive caller cancellation."""

    if type(tasks) is not tuple or any(not isinstance(task, asyncio.Task) for task in tasks):
        raise TypeError("shutdown tasks must be an exact tuple of asyncio.Task owners")
    unique_tasks = tuple(dict.fromkeys(tasks))
    for task in unique_tasks:
        if not task.done():
            task.cancel()
    if not unique_tasks:
        return CancelledTaskSettlement()

    async def collect() -> list[object]:
        return await asyncio.gather(*unique_tasks, return_exceptions=True)

    settlement = asyncio.create_task(collect(), name="cancelled-task-terminal-settlement")
    cancellation: asyncio.CancelledError | None = None
    while not settlement.done():
        try:
            await asyncio.shield(settlement)
        except asyncio.CancelledError as exc:
            if cancellation is None:
                cancellation = exc
    results = settlement.result()
    failures = tuple(
        result
        for result in results
        if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError)
    )
    return CancelledTaskSettlement(failures=failures, cancellation=cancellation)


async def settle_without_cancelling(
    owners: tuple[asyncio.Future[Any], ...],
    *,
    name: str,
) -> CancelledTaskSettlement:
    """Observe retained owners without allowing caller cancellation to abandon them."""

    unique_owners = tuple(dict.fromkeys(owners))
    if not unique_owners:
        return CancelledTaskSettlement()

    async def collect() -> list[object]:
        return await asyncio.gather(*unique_owners, return_exceptions=True)

    drain = asyncio.create_task(collect(), name=name)
    cancellation: asyncio.CancelledError | None = None
    while not drain.done():
        try:
            await asyncio.shield(drain)
        except asyncio.CancelledError as exc:
            if cancellation is None:
                cancellation = exc
    failures = tuple(
        result
        for result in drain.result()
        if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError)
    )
    return CancelledTaskSettlement(failures=failures, cancellation=cancellation)


async def settle_executor_operation[ExecutorResult](
    operation: asyncio.Future[ExecutorResult],
) -> ExecutorResult:
    """Retain an executor wrapper until its worker is terminal."""

    cancellation: asyncio.CancelledError | None = None
    while not operation.done():
        try:
            await asyncio.shield(operation)
        except asyncio.CancelledError as exc:
            if cancellation is None:
                cancellation = exc
        except BaseException:
            break
    try:
        result = operation.result()
    except BaseException as operation_error:
        if cancellation is not None and not isinstance(operation_error, asyncio.CancelledError):
            raise operation_error from cancellation
        raise
    if cancellation is not None:
        raise cancellation
    return result


async def await_executor_owner[ExecutorResult](
    owner: asyncio.Task[ExecutorResult],
) -> ExecutorResult:
    """Await retained executor settlement before propagating caller cancellation."""

    cancellation: asyncio.CancelledError | None = None
    while not owner.done():
        try:
            await asyncio.shield(owner)
        except asyncio.CancelledError as exc:
            if cancellation is None:
                cancellation = exc
            if owner.done():
                break
        except BaseException:
            break
    try:
        result = owner.result()
    except BaseException as owner_error:
        if cancellation is not None and not isinstance(owner_error, asyncio.CancelledError):
            raise owner_error from cancellation
        raise
    if cancellation is not None:
        raise cancellation
    return result


def combine_settlements(*settlements: CancelledTaskSettlement) -> CancelledTaskSettlement:
    """Combine exact failures and the first caller cancellation without duplication."""

    failures: list[BaseException] = []
    cancellation: asyncio.CancelledError | None = None
    for settlement in settlements:
        for failure in settlement.failures:
            if all(failure is not retained for retained in failures):
                failures.append(failure)
        if cancellation is None and settlement.cancellation is not None:
            cancellation = settlement.cancellation
    return CancelledTaskSettlement(failures=tuple(failures), cancellation=cancellation)
