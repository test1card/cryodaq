from __future__ import annotations

import asyncio
import inspect
import math
from dataclasses import FrozenInstanceError

import pytest

from cryodaq.core.broker import DataBroker
from cryodaq.core.scheduler import InstrumentConfig, Scheduler
from cryodaq.drivers import registry as driver_registry
from cryodaq.drivers.base import InstrumentDriver, Reading
from cryodaq.drivers.contracts import (
    AcquisitionTiming,
    BusDescriptor,
    BusRecoveryLevel,
    DriverRuntimeBinding,
    DriverTrustClass,
    _issue_registry_runtime_binding,
)
from cryodaq.drivers.registry import (
    DriverConstructionContext,
    DriverRegistryError,
    construct_driver,
    runtime_binding_for_driver,
    validate_instrument_entry,
)


class _Driver(InstrumentDriver):
    def __init__(
        self,
        name: str,
        *,
        fail: bool = False,
        delay_s: float = 0.0,
        concurrency: list[int] | None = None,
    ) -> None:
        super().__init__(name, mock=True)
        self.fail = fail
        self.delay_s = delay_s
        self.reads = 0
        self.read_times: list[float] = []
        self.concurrency = concurrency

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def read_channels(self) -> list[Reading]:
        if self.concurrency is not None:
            self.concurrency[0] += 1
            self.concurrency[1] = max(self.concurrency[1], self.concurrency[0])
        try:
            self.reads += 1
            self.read_times.append(asyncio.get_running_loop().time())
            if self.delay_s:
                await asyncio.sleep(self.delay_s)
            if self.fail:
                raise RuntimeError("injected read failure")
            return [Reading.now("CH", 1.0, "K", instrument_id=self.name)]
        finally:
            if self.concurrency is not None:
                self.concurrency[0] -= 1


class _Participant:
    def __init__(self, descriptor: BusDescriptor, driver: _Driver) -> None:
        self.bus_descriptor = descriptor
        self.driver = driver
        self.recoveries = 0
        self.marked = 0
        self.block_recovery: asyncio.Event | None = None
        self.recovery_started = asyncio.Event()

    async def mark_disconnected(self) -> None:
        self.marked += 1
        await self.driver.disconnect()

    async def recover_device(self) -> None:
        self.recoveries += 1
        self.recovery_started.set()
        if self.block_recovery is not None:
            await self.block_recovery.wait()


class _Coordinator:
    def __init__(
        self,
        descriptor: BusDescriptor,
        *,
        result: bool = True,
        delay_s: float = 0.0,
    ) -> None:
        self.bus_descriptor = descriptor
        self.ifc = 0
        self.reopens = 0
        self.result = result
        self.delay_s = delay_s

    async def interface_clear(self) -> bool:
        self.ifc += 1
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        return self.result

    async def reopen_bus(self) -> bool:
        self.reopens += 1
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        return self.result


class _VirtualClock:
    def __init__(self, *, duration_s: float) -> None:
        self.now = 0.0
        self.duration_s = duration_s
        self.finished = asyncio.Event()

    def __call__(self) -> float:
        return self.now

    async def sleep(self, delay_s: float) -> None:
        self.now += delay_s
        if self.now >= self.duration_s:
            self.finished.set()
        await asyncio.sleep(0)


def _binding(
    driver: _Driver,
    bus_id: str,
    *,
    poll: float = 0.01,
    connect: float = 0.2,
    read: float = 0.2,
    participant: _Participant | None = None,
    coordinator: _Coordinator | None = None,
) -> DriverRuntimeBinding:
    descriptor = (
        participant.bus_descriptor
        if participant
        else coordinator.bus_descriptor
        if coordinator
        else BusDescriptor(bus_id)
    )
    binding = _issue_registry_runtime_binding(
        driver=driver,
        timing=AcquisitionTiming(connect, read, poll),
        registry_provenance="test:registry-bound",
        trust_class=DriverTrustClass.PASSIVE_EXTENSION,
        bus_descriptor=descriptor,
        participant=participant,
        coordinator=coordinator,
    )
    with driver_registry._RUNTIME_BINDINGS_LOCK:
        if driver in driver_registry._RUNTIME_BINDINGS:
            raise DriverRegistryError("driver already has an exact runtime binding")
        driver_registry._RUNTIME_BINDINGS[driver] = binding
    return binding


def test_contracts_are_immutable_bounded_and_reject_nonfinite_or_bool_timing() -> None:
    descriptor = BusDescriptor("GPIB0", supported_recovery=frozenset({BusRecoveryLevel.DEVICE_CLEAR}))
    with pytest.raises(FrozenInstanceError):
        descriptor.bus_id = "GPIB1"  # type: ignore[misc]
    for invalid in ("", "bad\n", "x" * 129, "e\u0301"):
        with pytest.raises(ValueError):
            BusDescriptor(invalid)
    for invalid in (True, 0, -1, math.nan, math.inf, 10**1000):
        with pytest.raises((TypeError, ValueError, OverflowError)):
            AcquisitionTiming(invalid, 1.0, 1.0)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        InstrumentConfig(_Driver("invalid"), poll_interval_s=math.nan)
    with pytest.raises(TypeError, match="issued by a registry"):
        DriverRuntimeBinding()  # type: ignore[call-arg]


async def test_resource_prefix_has_no_authority_but_explicit_non_gpib_binding_serializes() -> None:
    broker = DataBroker()
    prefixed_a = _Driver("prefix-a")
    prefixed_b = _Driver("prefix-b")
    scheduler = Scheduler(broker)
    scheduler.add(InstrumentConfig(prefixed_a, poll_interval_s=0.01, resource_str="GPIB9::1::INSTR"))
    scheduler.add(InstrumentConfig(prefixed_b, poll_interval_s=0.01, resource_str="GPIB9::2::INSTR"))
    await scheduler.start()
    assert scheduler._instruments[prefixed_a.name].task is not scheduler._instruments[prefixed_b.name].task
    await scheduler.stop()

    explicit_a = _Driver("explicit-a")
    explicit_b = _Driver("explicit-b")
    scheduler = Scheduler(broker)
    scheduler.add(InstrumentConfig(explicit_a, runtime_binding=_binding(explicit_a, "optical-bus")))
    scheduler.add(InstrumentConfig(explicit_b, runtime_binding=_binding(explicit_b, "optical-bus")))
    await scheduler.start()
    assert scheduler._instruments[explicit_a.name].task is scheduler._instruments[explicit_b.name].task
    await scheduler.stop()


async def test_mixed_cadence_is_serialized_per_bus_without_slowest_device_flattening() -> None:
    concurrency = [0, 0]
    fast = _Driver("fast", delay_s=0.001, concurrency=concurrency)
    slow = _Driver("slow", delay_s=0.001, concurrency=concurrency)
    clock = _VirtualClock(duration_s=0.16)
    scheduler = Scheduler(DataBroker(), shared_bus_clock=clock, shared_bus_sleep=clock.sleep)
    scheduler.add(InstrumentConfig(fast, runtime_binding=_binding(fast, "bus-a", poll=0.01)))
    scheduler.add(InstrumentConfig(slow, runtime_binding=_binding(slow, "bus-a", poll=0.04)))
    await scheduler.start()
    await asyncio.wait_for(clock.finished.wait(), timeout=1.0)
    await scheduler.stop()
    assert concurrency[1] == 1
    assert fast.reads >= 3 * slow.reads
    assert fast.reads <= 6 * slow.reads


async def test_different_explicit_buses_progress_independently_and_missed_deadlines_do_not_burst() -> None:
    concurrency = [0, 0]
    first = _Driver("first", delay_s=0.03, concurrency=concurrency)
    second = _Driver("second", delay_s=0.03, concurrency=concurrency)
    scheduler = Scheduler(DataBroker())
    scheduler.add(InstrumentConfig(first, runtime_binding=_binding(first, "bus-a", poll=0.005)))
    scheduler.add(InstrumentConfig(second, runtime_binding=_binding(second, "bus-b", poll=0.005)))
    await scheduler.start()
    await asyncio.sleep(0.11)
    await scheduler.stop()
    assert concurrency[1] == 2
    assert all(later - earlier >= 0.025 for earlier, later in zip(first.read_times, first.read_times[1:]))


async def test_one_bad_participant_does_not_reset_healthy_peer_or_escalate_bus() -> None:
    descriptor = BusDescriptor(
        "bus-a",
        supported_recovery=frozenset(
            {BusRecoveryLevel.DEVICE_CLEAR, BusRecoveryLevel.INTERFACE_CLEAR, BusRecoveryLevel.REOPEN_BUS}
        ),
    )
    bad = _Driver("bad", fail=True)
    good = _Driver("good")
    bad_participant = _Participant(descriptor, bad)
    good_participant = _Participant(descriptor, good)
    coordinator = _Coordinator(descriptor)
    scheduler = Scheduler(DataBroker())
    scheduler.add(
        InstrumentConfig(
            bad,
            runtime_binding=_binding(bad, "bus-a", participant=bad_participant, coordinator=coordinator),
        )
    )
    scheduler.add(
        InstrumentConfig(
            good,
            runtime_binding=_binding(good, "bus-a", participant=good_participant, coordinator=coordinator),
        )
    )
    await scheduler.start()
    await asyncio.sleep(0.09)
    await scheduler.stop()
    assert bad_participant.recoveries > 0
    assert good.reads > 0
    assert coordinator.ifc == coordinator.reopens == 0


async def test_correlated_failure_escalates_only_bound_bus_and_stop_cancels_recovery() -> None:
    levels = frozenset({BusRecoveryLevel.DEVICE_CLEAR, BusRecoveryLevel.INTERFACE_CLEAR, BusRecoveryLevel.REOPEN_BUS})
    descriptor = BusDescriptor("failed-bus", supported_recovery=levels)
    other_descriptor = BusDescriptor("healthy-bus", supported_recovery=levels)
    coordinator = _Coordinator(descriptor)
    other = _Coordinator(other_descriptor)
    first = _Driver("first", fail=True)
    second = _Driver("second", fail=True)
    scheduler = Scheduler(DataBroker())
    for driver in (first, second):
        participant = _Participant(descriptor, driver)
        scheduler.add(
            InstrumentConfig(
                driver,
                runtime_binding=_binding(
                    driver,
                    "failed-bus",
                    poll=0.005,
                    participant=participant,
                    coordinator=coordinator,
                ),
            )
        )
    healthy = _Driver("healthy")
    healthy_participant = _Participant(other_descriptor, healthy)
    scheduler.add(
        InstrumentConfig(
            healthy,
            runtime_binding=_binding(
                healthy,
                "healthy-bus",
                poll=0.005,
                participant=healthy_participant,
                coordinator=other,
            ),
        )
    )
    await scheduler.start()
    await asyncio.sleep(0.45)
    await scheduler.stop()
    assert coordinator.ifc >= 1
    assert coordinator.reopens >= 1
    assert other.ifc == other.reopens == 0


async def test_mixed_cadence_permanent_failures_complete_correlated_epochs() -> None:
    levels = frozenset({BusRecoveryLevel.DEVICE_CLEAR, BusRecoveryLevel.INTERFACE_CLEAR})
    descriptor = BusDescriptor("mixed-fail", supported_recovery=levels)
    coordinator = _Coordinator(descriptor)
    fast = _Driver("fast-fail", fail=True)
    slow = _Driver("slow-fail", fail=True)
    scheduler = Scheduler(DataBroker())
    for driver, cadence in ((fast, 0.005), (slow, 0.04)):
        participant = _Participant(descriptor, driver)
        scheduler.add(
            InstrumentConfig(
                driver,
                runtime_binding=_binding(
                    driver,
                    "mixed-fail",
                    poll=cadence,
                    participant=participant,
                    coordinator=coordinator,
                ),
            )
        )
    await scheduler.start()
    await asyncio.sleep(0.4)
    await scheduler.stop()
    assert fast.reads >= slow.reads >= 3
    assert fast.reads <= 10
    assert coordinator.ifc >= 1


async def test_false_or_timed_out_bus_recovery_never_claims_success_or_strands_stop() -> None:
    levels = frozenset({BusRecoveryLevel.DEVICE_CLEAR, BusRecoveryLevel.INTERFACE_CLEAR, BusRecoveryLevel.REOPEN_BUS})
    descriptor = BusDescriptor("false-bus", supported_recovery=levels, recovery_timeout_s=0.01)
    driver = _Driver("false-recovery", fail=True)
    participant = _Participant(descriptor, driver)
    coordinator = _Coordinator(descriptor, result=False)
    scheduler = Scheduler(DataBroker(), drain_timeout_s=0.05)
    scheduler.add(
        InstrumentConfig(
            driver,
            runtime_binding=_binding(
                driver,
                "false-bus",
                poll=0.005,
                participant=participant,
                coordinator=coordinator,
            ),
        )
    )
    await scheduler.start()
    await asyncio.sleep(0.45)
    first_reopens = coordinator.reopens
    await asyncio.sleep(0.35)
    await asyncio.wait_for(scheduler.stop(), timeout=0.5)
    assert coordinator.ifc >= 1
    assert coordinator.reopens > first_reopens >= 1

    timeout_descriptor = BusDescriptor("timeout-bus", supported_recovery=levels, recovery_timeout_s=0.01)
    timeout_driver = _Driver("timeout-recovery", fail=True)
    timeout_participant = _Participant(timeout_descriptor, timeout_driver)
    timeout_coordinator = _Coordinator(timeout_descriptor, delay_s=1.0)
    timeout_scheduler = Scheduler(DataBroker(), drain_timeout_s=0.05)
    timeout_scheduler.add(
        InstrumentConfig(
            timeout_driver,
            runtime_binding=_binding(
                timeout_driver,
                "timeout-bus",
                poll=0.005,
                participant=timeout_participant,
                coordinator=timeout_coordinator,
            ),
        )
    )
    await timeout_scheduler.start()
    await asyncio.sleep(0.45)
    await asyncio.wait_for(timeout_scheduler.stop(), timeout=0.5)
    assert timeout_coordinator.ifc >= 1
    assert timeout_coordinator.reopens >= 1


async def test_cancellation_resistant_coordinator_becomes_terminal_without_overlap() -> None:
    descriptor = BusDescriptor(
        "resistant-bus",
        supported_recovery=frozenset({BusRecoveryLevel.DEVICE_CLEAR, BusRecoveryLevel.INTERFACE_CLEAR}),
        recovery_timeout_s=0.01,
    )
    driver = _Driver("resistant-driver", fail=True)
    participant = _Participant(descriptor, driver)

    class _ResistantCoordinator:
        bus_descriptor = descriptor

        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.finished = asyncio.Event()
            self.calls = 0
            self.active = 0
            self.max_active = 0

        async def interface_clear(self) -> bool:
            self.calls += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.started.set()
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                await asyncio.sleep(0.2)
                return False
            finally:
                self.active -= 1
                self.finished.set()

        async def reopen_bus(self) -> bool:
            raise AssertionError("terminal IFC must prohibit later recovery")

    coordinator = _ResistantCoordinator()
    scheduler = Scheduler(DataBroker(), drain_timeout_s=0.02)
    scheduler.add(
        InstrumentConfig(
            driver,
            runtime_binding=_binding(
                driver,
                "resistant-bus",
                poll=0.005,
                participant=participant,
                coordinator=coordinator,
            ),
        )
    )
    await scheduler.start()
    await asyncio.wait_for(coordinator.started.wait(), timeout=0.5)
    await asyncio.sleep(0.04)
    shared_task = scheduler._instruments[driver.name].task
    assert shared_task is not None and shared_task.done()
    marked_before_stop = participant.marked
    await asyncio.wait_for(scheduler.stop(), timeout=0.1)
    assert coordinator.calls == coordinator.max_active == 1
    assert coordinator.active == 1
    assert participant.marked == marked_before_stop
    await asyncio.wait_for(coordinator.finished.wait(), timeout=0.3)
    assert coordinator.active == 0


async def test_stop_during_cancellation_resistant_recovery_terminalizes_without_disconnect() -> None:
    descriptor = BusDescriptor(
        "stop-resistant-bus",
        supported_recovery=frozenset({BusRecoveryLevel.DEVICE_CLEAR, BusRecoveryLevel.INTERFACE_CLEAR}),
        recovery_timeout_s=0.05,
    )
    driver = _Driver("stop-resistant-driver", fail=True)
    participant = _Participant(descriptor, driver)

    class _Coordinator:
        bus_descriptor = descriptor

        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.finished = asyncio.Event()
            self.active = 0
            self.max_active = 0

        async def interface_clear(self) -> bool:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.started.set()
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                await asyncio.sleep(0.2)
                return False
            finally:
                self.active -= 1
                self.finished.set()

        async def reopen_bus(self) -> bool:
            raise AssertionError("stop cancellation must prohibit later recovery")

    coordinator = _Coordinator()
    scheduler = Scheduler(DataBroker(), drain_timeout_s=0.005)
    scheduler.add(
        InstrumentConfig(
            driver,
            runtime_binding=_binding(
                driver,
                descriptor.bus_id,
                poll=0.005,
                participant=participant,
                coordinator=coordinator,
            ),
        )
    )
    await scheduler.start()
    await asyncio.wait_for(coordinator.started.wait(), timeout=0.5)
    marked_before_stop = participant.marked
    await asyncio.wait_for(scheduler.stop(), timeout=0.15)
    assert coordinator.max_active == 1
    assert coordinator.active == 1
    assert participant.marked == marked_before_stop
    assert descriptor.bus_id in scheduler._terminal_bus_authority
    await asyncio.wait_for(coordinator.finished.wait(), timeout=0.3)


async def test_cancellation_during_public_device_recovery_settles_bounded() -> None:
    descriptor = BusDescriptor("cancel-bus", supported_recovery=frozenset({BusRecoveryLevel.DEVICE_CLEAR}))
    driver = _Driver("blocked", fail=True)
    participant = _Participant(descriptor, driver)
    participant.block_recovery = asyncio.Event()
    scheduler = Scheduler(DataBroker(), drain_timeout_s=0.02)
    scheduler.add(
        InstrumentConfig(
            driver,
            runtime_binding=_binding(driver, "cancel-bus", poll=0.005, participant=participant),
        )
    )
    await scheduler.start()
    await asyncio.wait_for(participant.recovery_started.wait(), timeout=0.5)
    await asyncio.wait_for(scheduler.stop(), timeout=0.5)
    assert scheduler._running is False
    assert scheduler._instruments[driver.name].task is None


async def test_cancellation_resistant_device_recovery_terminalizes_bus_by_second_bound() -> None:
    descriptor = BusDescriptor(
        "resistant-device-bus",
        supported_recovery=frozenset({BusRecoveryLevel.DEVICE_CLEAR}),
    )
    driver = _Driver("resistant-device", fail=True)

    class _ResistantParticipant(_Participant):
        def __init__(self) -> None:
            super().__init__(descriptor, driver)
            self.finished = asyncio.Event()
            self.active = 0
            self.max_active = 0

        async def recover_device(self) -> None:
            self.recoveries += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.recovery_started.set()
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                await asyncio.sleep(0.2)
            finally:
                self.active -= 1
                self.finished.set()

    participant = _ResistantParticipant()
    scheduler = Scheduler(DataBroker(), drain_timeout_s=0.01)
    scheduler.add(
        InstrumentConfig(
            driver,
            runtime_binding=_binding(
                driver,
                descriptor.bus_id,
                poll=0.005,
                connect=0.01,
                participant=participant,
            ),
        )
    )
    await scheduler.start()
    await asyncio.wait_for(participant.recovery_started.wait(), timeout=0.5)
    await asyncio.sleep(0.05)
    shared_task = scheduler._instruments[driver.name].task
    assert shared_task is not None and shared_task.done()
    assert participant.recoveries == participant.max_active == participant.active == 1
    marked_before_stop = participant.marked
    await asyncio.wait_for(scheduler.stop(), timeout=0.1)
    assert participant.marked == marked_before_stop
    assert descriptor.bus_id in scheduler._terminal_bus_authority
    await asyncio.wait_for(participant.finished.wait(), timeout=0.3)
    assert participant.active == 0


async def test_stop_during_cancellation_resistant_device_recovery_owns_late_task() -> None:
    descriptor = BusDescriptor(
        "stop-resistant-device-bus",
        supported_recovery=frozenset({BusRecoveryLevel.DEVICE_CLEAR}),
    )
    driver = _Driver("stop-resistant-device", fail=True)

    class _ResistantParticipant(_Participant):
        def __init__(self) -> None:
            super().__init__(descriptor, driver)
            self.finished = asyncio.Event()
            self.active = 0
            self.max_active = 0

        async def recover_device(self) -> None:
            self.recoveries += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.recovery_started.set()
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                await asyncio.sleep(0.2)
            finally:
                self.active -= 1
                self.finished.set()

    participant = _ResistantParticipant()
    scheduler = Scheduler(DataBroker(), drain_timeout_s=0.005)
    scheduler.add(
        InstrumentConfig(
            driver,
            runtime_binding=_binding(
                driver,
                descriptor.bus_id,
                poll=0.005,
                connect=0.05,
                participant=participant,
            ),
        )
    )
    await scheduler.start()
    await asyncio.wait_for(participant.recovery_started.wait(), timeout=0.5)
    marked_before_stop = participant.marked
    await asyncio.wait_for(scheduler.stop(), timeout=0.15)
    assert participant.recoveries == participant.max_active == participant.active == 1
    assert participant.marked == marked_before_stop
    assert descriptor.bus_id in scheduler._terminal_bus_authority
    await asyncio.wait_for(participant.finished.wait(), timeout=0.3)
    assert participant.active == 0


async def test_cancellation_resistant_read_terminalizes_bus_without_peer_overlap() -> None:
    descriptor = BusDescriptor("resistant-read-bus")

    class _CountedDriver(_Driver):
        def __init__(self, name: str) -> None:
            super().__init__(name)
            self.disconnects = 0

        async def disconnect(self) -> None:
            self.disconnects += 1
            await super().disconnect()

    class _ResistantReadDriver(_CountedDriver):
        def __init__(self) -> None:
            super().__init__("resistant-reader")
            self.started = asyncio.Event()
            self.finished = asyncio.Event()
            self.active = 0
            self.max_active = 0

        async def read_channels(self) -> list[Reading]:
            self.reads += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.started.set()
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                await asyncio.sleep(0.2)
                return [Reading.now("late", 1.0, "K", instrument_id=self.name)]
            finally:
                self.active -= 1
                self.finished.set()

    resistant = _ResistantReadDriver()
    peer = _CountedDriver("peer")
    scheduler = Scheduler(DataBroker(), drain_timeout_s=0.01)
    scheduler.add(
        InstrumentConfig(
            resistant,
            runtime_binding=_binding(
                resistant,
                descriptor.bus_id,
                poll=0.005,
                read=0.01,
            ),
        )
    )
    scheduler.add(
        InstrumentConfig(
            peer,
            runtime_binding=_binding(
                peer,
                descriptor.bus_id,
                poll=0.005,
                read=0.01,
            ),
        )
    )

    await scheduler.start()
    await asyncio.wait_for(resistant.started.wait(), timeout=0.5)
    await asyncio.sleep(0.05)
    shared_task = scheduler._instruments[resistant.name].task
    assert shared_task is not None and shared_task.done()
    assert descriptor.bus_id in scheduler._terminal_bus_authority
    assert resistant.reads == resistant.max_active == resistant.active == 1
    assert peer.reads == 0

    await asyncio.wait_for(scheduler.stop(), timeout=0.1)
    assert resistant.disconnects == peer.disconnects == 0
    assert peer.reads == 0
    await asyncio.wait_for(resistant.finished.wait(), timeout=0.3)
    assert resistant.active == 0
    assert peer.reads == 0


async def test_public_recovery_exceptions_do_not_strand_scheduler_task() -> None:
    descriptor = BusDescriptor("faulty-recovery", supported_recovery=frozenset({BusRecoveryLevel.DEVICE_CLEAR}))
    driver = _Driver("faulty", fail=True)
    mark_attempted = asyncio.Event()

    class _RaisingParticipant(_Participant):
        async def recover_device(self) -> None:
            self.recoveries += 1
            raise RuntimeError("device recovery failed")

        async def mark_disconnected(self) -> None:
            self.marked += 1
            mark_attempted.set()
            raise RuntimeError("mark failed")

    participant = _RaisingParticipant(descriptor, driver)
    scheduler = Scheduler(DataBroker(), drain_timeout_s=0.05)
    scheduler.add(
        InstrumentConfig(
            driver,
            runtime_binding=_binding(driver, "faulty-recovery", poll=0.005, participant=participant),
        )
    )
    await scheduler.start()
    await asyncio.wait_for(mark_attempted.wait(), timeout=0.5)
    task = scheduler._instruments[driver.name].task
    assert task is not None and not task.done()
    await scheduler.stop()
    assert participant.recoveries > 0 and participant.marked > 0


def test_registry_binding_preserves_exact_timing_and_never_binds_reviewed_source_to_bus() -> None:
    context = DriverConstructionContext(mock=True)
    lakeshore_config = validate_instrument_entry(
        {
            "type": "lakeshore_218s",
            "name": "LS",
            "resource": "GPIB2::12::INSTR",
            "poll_interval_s": 0.5,
            "connect_timeout_s": 2.0,
            "read_timeout_s": 7.0,
        }
    )
    lakeshore = construct_driver(lakeshore_config, context)
    binding = runtime_binding_for_driver(lakeshore)
    assert binding is not None
    assert binding.bus_descriptor == BusDescriptor("GPIB2")
    assert binding.timing == AcquisitionTiming(2.0, 7.0, 0.5)
    assert binding.trust_class.value == "passive_measurement"

    source_config = validate_instrument_entry({"type": "keithley_2604b", "name": "K", "resource": "USB0::1"})
    source = construct_driver(source_config, context)
    source_binding = runtime_binding_for_driver(source)
    assert source_binding is not None and source_binding.bus_descriptor is None
    assert source_binding.trust_class.value == "reviewed_source"
    assert not hasattr(binding, "source_authority")

    forged_descriptor = BusDescriptor("forged-source-bus")
    forged = DriverRuntimeBinding._issued(
        driver=source,
        timing=source_binding.timing,
        registry_provenance="test:forged-source",
        trust_class=DriverTrustClass.PASSIVE_EXTENSION,
        bus_descriptor=forged_descriptor,
    )
    with pytest.raises(ValueError, match="cannot be replaced"):
        InstrumentConfig(source, runtime_binding=forged)
    canonical_config = InstrumentConfig(source)
    assert canonical_config.runtime_binding is source_binding
    assert canonical_config.runtime_binding.bus_descriptor is None

    from cryodaq.drivers.instruments.keithley_2604b import Keithley2604B

    direct_source = Keithley2604B("direct", "USB0::1", mock=True)
    direct_forgery = DriverRuntimeBinding._issued(
        driver=direct_source,
        timing=AcquisitionTiming(1.0, 1.0, 1.0),
        registry_provenance="test:direct-source-forgery",
        trust_class=DriverTrustClass.PASSIVE_EXTENSION,
        bus_descriptor=BusDescriptor("forged-source-bus"),
    )
    with pytest.raises(ValueError, match="unregistered driver"):
        InstrumentConfig(
            direct_source,
            runtime_binding=direct_forgery,
        )


async def test_structural_recovery_methods_never_create_an_implicit_bus_binding() -> None:
    class _BusShapedDriver(_Driver):
        bus_descriptor = BusDescriptor("forged")

        async def mark_disconnected(self) -> None:
            await self.disconnect()

        async def recover_device(self) -> None:
            raise AssertionError("implicit recovery must not be called")

    first = _BusShapedDriver("shaped-a")
    second = _BusShapedDriver("shaped-b")
    scheduler = Scheduler(DataBroker())
    scheduler.add(InstrumentConfig(first, poll_interval_s=0.01))
    scheduler.add(InstrumentConfig(second, poll_interval_s=0.01))
    await scheduler.start()
    assert scheduler._instruments[first.name].task is not scheduler._instruments[second.name].task
    await scheduler.stop()


async def test_duplicate_coordinators_and_legacy_timing_contradictions_fail_closed() -> None:
    descriptor = BusDescriptor("bus-a")
    first = _Driver("first")
    second = _Driver("second")
    with pytest.raises(ValueError, match="contradicts"):
        InstrumentConfig(first, poll_interval_s=2.0, runtime_binding=_binding(first, "bus-a"))

    first = _Driver("first-coordinator")
    scheduler = Scheduler(DataBroker())
    scheduler.add(
        InstrumentConfig(
            first,
            runtime_binding=_binding(first, "bus-a", coordinator=_Coordinator(descriptor)),
        )
    )
    scheduler.add(
        InstrumentConfig(
            second,
            runtime_binding=_binding(second, "bus-a", coordinator=_Coordinator(descriptor)),
        )
    )
    with pytest.raises(ValueError, match="contradictory recovery coordinators"):
        await scheduler.start()
    assert scheduler._running is False

    absent = _Driver("absent-coordinator")
    present = _Driver("present-coordinator")
    descriptor = BusDescriptor("optional-coordinator")
    scheduler = Scheduler(DataBroker())
    scheduler.add(InstrumentConfig(absent, runtime_binding=_binding(absent, "optional-coordinator")))
    scheduler.add(
        InstrumentConfig(
            present,
            runtime_binding=_binding(
                present,
                "optional-coordinator",
                coordinator=_Coordinator(descriptor),
            ),
        )
    )
    with pytest.raises(ValueError, match="contradictory recovery coordinators"):
        await scheduler.start()
    assert all(state.task is None for state in scheduler._instruments.values())


@pytest.mark.parametrize("reverse", [False, True])
async def test_same_bus_id_with_unequal_descriptor_fails_before_any_task(reverse: bool) -> None:
    plain = BusDescriptor("contradictory")
    recovering = BusDescriptor("contradictory", supported_recovery=frozenset({BusRecoveryLevel.INTERFACE_CLEAR}))
    first = _Driver("plain")
    second = _Driver("recovering")
    valid = _Driver("valid-first")
    scheduler = Scheduler(DataBroker())
    scheduler.add(InstrumentConfig(valid, runtime_binding=_binding(valid, "valid-bus")))
    pairs = [(first, plain), (second, recovering)]
    if reverse:
        pairs.reverse()
    for driver, descriptor in pairs:
        scheduler.add(
            InstrumentConfig(
                driver,
                runtime_binding=_binding(
                    driver,
                    descriptor.bus_id,
                    connect=0.2,
                    read=0.2,
                    poll=0.01,
                    coordinator=_Coordinator(descriptor)
                    if BusRecoveryLevel.INTERFACE_CLEAR in descriptor.supported_recovery
                    else None,
                ),
            )
        )
    with pytest.raises(ValueError, match="contradictory immutable descriptors"):
        await scheduler.start()
    assert scheduler._running is False
    assert all(state.task is None for state in scheduler._instruments.values())


def test_scheduler_shared_bus_path_uses_only_public_contracts() -> None:
    source = inspect.getsource(Scheduler)
    assert "_transport" not in source
    assert "._connected" not in source
    assert "GPIBTransport" not in source
    assert "resource_str.upper" not in source
