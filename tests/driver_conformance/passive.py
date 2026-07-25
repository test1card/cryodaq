"""Black-box conformance harness for passive measurement drivers.

The harness observes only public driver contracts and factory-owned probes. It
never inspects driver transport state. Each scenario receives a fresh driver,
probe, and explicit runtime descriptor binding.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from cryodaq.channels.descriptors import ChannelDescriptorV1
from cryodaq.drivers.base import Reading
from cryodaq.drivers.contracts import (
    ControlledSource,
    PassiveSensor,
    VerifiedOffSource,
    declared_protocol_members,
)


class PassiveConformanceScenario(StrEnum):
    BOUNDED_CONNECT = "bounded_connect"
    CANCELLED_CONNECT = "cancelled_connect"
    EXACT_READING = "exact_reading"
    SERIALIZED_SAFE_READ = "serialized_safe_read"
    CANCELLED_READ = "cancelled_read"
    UNUSABLE_MALFORMED = "unusable_malformed"
    RECONNECT_IDENTITY = "reconnect_identity"
    MOCK_IS_LOCAL = "mock_is_local"
    IDEMPOTENT_DISCONNECT = "idempotent_disconnect"
    EXACT_DESCRIPTOR_BINDING = "exact_descriptor_binding"
    NO_CONTROL_AUTHORITY = "no_control_authority"


class DeferredPassiveInterfaces(StrEnum):
    """Downstream interfaces intentionally outside driver conformance."""

    PERSISTENCE = "blocked_until_live_descriptor_activation:persistence"
    REPLAY = "blocked_until_descriptor_wire_contract:replay"
    REPORTING = "blocked_until_descriptor_wire_contract:reporting"
    OPERATOR_UI = "blocked_until_descriptor_wire_contract:operator_ui"


class PassiveDriver(Protocol):
    @property
    def connected(self) -> bool: ...

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def read_channels(self) -> list[Reading]: ...

    async def safe_read(self) -> list[Reading]: ...


class PassiveExternalProbe(Protocol):
    """Factory-owned observations, never a view of private driver fields."""

    @property
    def active_resources(self) -> int: ...

    @property
    def external_calls(self) -> int: ...

    @property
    def concurrent_reads(self) -> int: ...

    @property
    def maximum_concurrent_reads(self) -> int: ...

    async def connect_entered(self) -> None: ...

    async def read_entered(self) -> None: ...


class PassiveConformanceTimeout(AssertionError):
    """A bounded operation exceeded both execution and settlement windows.

    ``task`` is retained so a test can release an external fault-injection gate
    and explicitly observe final settlement instead of leaking background work.
    """

    def __init__(self, task: asyncio.Future[object], *, settled: bool) -> None:
        super().__init__("driver operation exceeded its bounded execution window")
        self.task = task
        self.settled = settled


def _validate_malformed_exception(error: object) -> None:
    if not isinstance(error, type) or not issubclass(error, Exception):
        raise TypeError("malformed_exceptions must contain narrow Exception types")
    prohibited = (AssertionError, TimeoutError, asyncio.CancelledError, PassiveConformanceTimeout)
    if error in {BaseException, Exception} or any(
        issubclass(error, control) or issubclass(control, error) for control in prohibited
    ):
        raise ValueError("malformed_exceptions must not catch harness or control-flow failures")


@dataclass(frozen=True, slots=True)
class PassiveConformanceCase:
    driver: PassiveDriver
    probe: PassiveExternalProbe
    emitted_bindings: Mapping[tuple[str, str], ChannelDescriptorV1]
    malformed_exceptions: tuple[type[Exception], ...] = ()
    timeout_s: float = 1.0

    def __post_init__(self) -> None:
        if not self.emitted_bindings:
            raise ValueError("emitted_bindings must be explicit and non-empty")
        if not 0 < self.timeout_s <= 30:
            raise ValueError("timeout_s must be in (0, 30]")
        for error in self.malformed_exceptions:
            _validate_malformed_exception(error)
        if len(set(self.malformed_exceptions)) != len(self.malformed_exceptions):
            raise ValueError("malformed_exceptions must not contain duplicates")


PassiveDriverFactory = Callable[[PassiveConformanceScenario], PassiveConformanceCase]
_ScenarioCheck = Callable[[PassiveConformanceCase], Awaitable[None]]


def _observe_late_task(task: asyncio.Future[object]) -> None:
    if task.cancelled():
        return
    try:
        task.exception()
    except (asyncio.CancelledError, asyncio.InvalidStateError):
        return


@dataclass(frozen=True, slots=True)
class _OperationOutcome:
    value: object | None = None
    error: Exception | None = None


async def _bounded(awaitable: Awaitable[object], timeout_s: float) -> object:
    task = asyncio.ensure_future(awaitable)
    done, _ = await asyncio.wait({task}, timeout=timeout_s)
    if done:
        return task.result()

    task.cancel()
    settled, _ = await asyncio.wait({task}, timeout=timeout_s)
    if settled:
        _observe_late_task(task)
        raise PassiveConformanceTimeout(task, settled=True)

    task.add_done_callback(_observe_late_task)
    raise PassiveConformanceTimeout(task, settled=False)


async def _bounded_outcome(awaitable: Awaitable[object], timeout_s: float) -> _OperationOutcome:
    """Bound an operation while returning, not classifying, its device error."""

    task = asyncio.ensure_future(awaitable)
    done, _ = await asyncio.wait({task}, timeout=timeout_s)
    if done:
        if task.cancelled():
            raise asyncio.CancelledError
        error = task.exception()
        if error is not None:
            if not isinstance(error, Exception):
                raise error
            return _OperationOutcome(error=error)
        return _OperationOutcome(value=task.result())

    task.cancel()
    settled, _ = await asyncio.wait({task}, timeout=timeout_s)
    if settled:
        _observe_late_task(task)
        raise PassiveConformanceTimeout(task, settled=True)

    task.add_done_callback(_observe_late_task)
    raise PassiveConformanceTimeout(task, settled=False)


async def _settle_cancelled(task: asyncio.Task[object], timeout_s: float) -> None:
    task.cancel()
    settled, _ = await asyncio.wait({task}, timeout=timeout_s)
    if not settled:
        task.add_done_callback(_observe_late_task)
        raise PassiveConformanceTimeout(task, settled=False)
    if task.cancelled():
        return
    task.result()
    raise AssertionError("cancelled driver operation completed without cancellation")


async def _cleanup(case: PassiveConformanceCase) -> None:
    await _bounded(case.driver.disconnect(), case.timeout_s)
    assert not case.driver.connected
    assert case.probe.active_resources == 0


async def _bounded_connect(case: PassiveConformanceCase) -> None:
    await _bounded(case.driver.connect(), case.timeout_s)
    assert case.driver.connected
    await _cleanup(case)


async def _cancelled_connect(case: PassiveConformanceCase) -> None:
    task = asyncio.create_task(case.driver.connect())
    await _bounded(case.probe.connect_entered(), case.timeout_s)
    await _settle_cancelled(task, case.timeout_s)
    assert not case.driver.connected
    assert case.probe.active_resources == 0
    await _cleanup(case)


def _reading_identity(reading: Reading) -> tuple[str, str, str]:
    return reading.instrument_id, reading.channel, reading.unit


def _assert_exact_readings(readings: object, *, nonempty: bool = True) -> list[Reading]:
    assert type(readings) is list
    if nonempty:
        assert readings
    assert all(type(reading) is Reading for reading in readings)
    return readings


async def _exact_reading(case: PassiveConformanceCase) -> None:
    await _bounded(case.driver.connect(), case.timeout_s)
    readings = _assert_exact_readings(await _bounded(case.driver.safe_read(), case.timeout_s))
    assert len({_reading_identity(reading) for reading in readings}) == len(readings)
    assert all(reading.is_usable() for reading in readings)
    await _cleanup(case)


async def _serialized_safe_read(case: PassiveConformanceCase) -> None:
    await _bounded(case.driver.connect(), case.timeout_s)
    first = asyncio.create_task(case.driver.safe_read())
    await _bounded(case.probe.read_entered(), case.timeout_s)
    second = asyncio.create_task(case.driver.safe_read())
    first_result, second_result = await _bounded(asyncio.gather(first, second), case.timeout_s)
    _assert_exact_readings(first_result)
    _assert_exact_readings(second_result)
    assert case.probe.maximum_concurrent_reads == 1
    assert case.probe.concurrent_reads == 0
    await _cleanup(case)


async def _cancelled_read(case: PassiveConformanceCase) -> None:
    await _bounded(case.driver.connect(), case.timeout_s)
    task = asyncio.create_task(case.driver.safe_read())
    await _bounded(case.probe.read_entered(), case.timeout_s)
    await _settle_cancelled(task, case.timeout_s)
    assert case.probe.concurrent_reads == 0
    await _cleanup(case)


async def _unusable_malformed(case: PassiveConformanceCase) -> None:
    await _bounded(case.driver.connect(), case.timeout_s)
    outcome = await _bounded_outcome(case.driver.safe_read(), case.timeout_s)
    if outcome.error is not None:
        if type(outcome.error) not in case.malformed_exceptions:
            raise outcome.error
        await _cleanup(case)
        return
    readings = _assert_exact_readings(outcome.value, nonempty=False)
    assert not readings or all(not reading.is_usable() for reading in readings)
    await _cleanup(case)


async def _reconnect_identity(case: PassiveConformanceCase) -> None:
    await _bounded(case.driver.connect(), case.timeout_s)
    first = _assert_exact_readings(await _bounded(case.driver.safe_read(), case.timeout_s))
    await _cleanup(case)
    await _bounded(case.driver.connect(), case.timeout_s)
    second = _assert_exact_readings(await _bounded(case.driver.safe_read(), case.timeout_s))
    assert Counter(map(_reading_identity, first)) == Counter(map(_reading_identity, second))
    await _cleanup(case)


async def _mock_is_local(case: PassiveConformanceCase) -> None:
    assert case.probe.external_calls == 0
    await _bounded(case.driver.connect(), case.timeout_s)
    _assert_exact_readings(await _bounded(case.driver.safe_read(), case.timeout_s))
    await _cleanup(case)
    assert case.probe.external_calls == 0


async def _idempotent_disconnect(case: PassiveConformanceCase) -> None:
    await _bounded(case.driver.connect(), case.timeout_s)
    await _bounded(case.driver.disconnect(), case.timeout_s)
    await _bounded(case.driver.disconnect(), case.timeout_s)
    assert not case.driver.connected
    assert case.probe.active_resources == 0


async def _exact_descriptor_binding(case: PassiveConformanceCase) -> None:
    await _bounded(case.driver.connect(), case.timeout_s)
    readings = _assert_exact_readings(await _bounded(case.driver.safe_read(), case.timeout_s))
    for reading in readings:
        descriptor = case.emitted_bindings.get((reading.instrument_id, reading.channel))
        assert descriptor is not None, "reading requires an exact explicit runtime binding"
        assert descriptor.instrument_id == reading.instrument_id
        assert descriptor.unit == reading.unit
        assert descriptor.grants_control_authority is False
    await _cleanup(case)


async def _no_control_authority(case: PassiveConformanceCase) -> None:
    driver = case.driver
    assert isinstance(driver, PassiveSensor)
    assert not isinstance(driver, ControlledSource)
    assert not isinstance(driver, VerifiedOffSource)
    hazardous_members = {
        *declared_protocol_members(ControlledSource),
        *declared_protocol_members(VerifiedOffSource),
    }
    assert all(not hasattr(driver, member) for member in hazardous_members)
    assert getattr(driver, "grants_control_authority", False) is False
    assert all(descriptor.grants_control_authority is False for descriptor in case.emitted_bindings.values())
    await _cleanup(case)


_CHECKS: Mapping[PassiveConformanceScenario, _ScenarioCheck] = {
    PassiveConformanceScenario.BOUNDED_CONNECT: _bounded_connect,
    PassiveConformanceScenario.CANCELLED_CONNECT: _cancelled_connect,
    PassiveConformanceScenario.EXACT_READING: _exact_reading,
    PassiveConformanceScenario.SERIALIZED_SAFE_READ: _serialized_safe_read,
    PassiveConformanceScenario.CANCELLED_READ: _cancelled_read,
    PassiveConformanceScenario.UNUSABLE_MALFORMED: _unusable_malformed,
    PassiveConformanceScenario.RECONNECT_IDENTITY: _reconnect_identity,
    PassiveConformanceScenario.MOCK_IS_LOCAL: _mock_is_local,
    PassiveConformanceScenario.IDEMPOTENT_DISCONNECT: _idempotent_disconnect,
    PassiveConformanceScenario.EXACT_DESCRIPTOR_BINDING: _exact_descriptor_binding,
    PassiveConformanceScenario.NO_CONTROL_AUTHORITY: _no_control_authority,
}


async def run_passive_conformance(
    factory: PassiveDriverFactory,
    *,
    scenarios: Sequence[PassiveConformanceScenario] = tuple(PassiveConformanceScenario),
) -> None:
    """Run selected passive checks, rejecting reused mutable cases/drivers."""

    retained_cases: list[PassiveConformanceCase] = []
    for scenario in scenarios:
        case = factory(scenario)
        assert all(case is not prior for prior in retained_cases), "factory must return a fresh case per scenario"
        assert all(case.driver is not prior.driver for prior in retained_cases), (
            "factory must return a fresh driver per scenario"
        )
        retained_cases.append(case)
        await _CHECKS[scenario](case)


__all__ = [
    "DeferredPassiveInterfaces",
    "PassiveConformanceCase",
    "PassiveConformanceScenario",
    "PassiveConformanceTimeout",
    "PassiveDriverFactory",
    "run_passive_conformance",
]
