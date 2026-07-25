"""Self-tests and one real-mock application of passive conformance."""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from cryodaq.channels.descriptors import (
    ChannelDescriptorV1,
    ChannelQuantity,
    ChannelRole,
    ChannelSafetyClass,
)
from cryodaq.drivers.base import ChannelStatus, InstrumentDriver, Reading
from cryodaq.drivers.instruments.lakeshore_218s import LakeShore218S
from tests.driver_conformance.passive import (
    DeferredPassiveInterfaces,
    PassiveConformanceCase,
    PassiveConformanceScenario,
    PassiveConformanceTimeout,
    run_passive_conformance,
)


@dataclass(slots=True)
class _Probe:
    resources: int = 0
    calls_outside_process: int = 0
    reads: int = 0
    maximum_reads: int = 0
    connect_event: asyncio.Event = field(default_factory=asyncio.Event)
    read_event: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def active_resources(self) -> int:
        return self.resources

    @property
    def external_calls(self) -> int:
        return self.calls_outside_process

    @property
    def concurrent_reads(self) -> int:
        return self.reads

    @property
    def maximum_concurrent_reads(self) -> int:
        return self.maximum_reads

    async def connect_entered(self) -> None:
        await self.connect_event.wait()

    async def read_entered(self) -> None:
        await self.read_event.wait()


class _FakePassiveDriver(InstrumentDriver):
    def __init__(self, scenario: PassiveConformanceScenario, probe: _Probe) -> None:
        super().__init__("fake-passive", mock=True)
        self.scenario = scenario
        self.probe = probe
        self.connection_count = 0

    async def connect(self) -> None:
        if self.connected:
            return
        self.probe.resources += 1
        self.probe.connect_event.set()
        try:
            if self.scenario is PassiveConformanceScenario.CANCELLED_CONNECT:
                await asyncio.Event().wait()
            self._connected = True
            self.connection_count += 1
        except asyncio.CancelledError:
            self.probe.resources -= 1
            raise

    async def disconnect(self) -> None:
        if self.connected:
            self._connected = False
            self.probe.resources -= 1

    async def read_channels(self) -> list[Reading]:
        self.probe.reads += 1
        self.probe.maximum_reads = max(self.probe.maximum_reads, self.probe.reads)
        self.probe.read_event.set()
        try:
            if self.scenario is PassiveConformanceScenario.CANCELLED_READ:
                await asyncio.Event().wait()
            if self.scenario is PassiveConformanceScenario.SERIALIZED_SAFE_READ:
                await asyncio.sleep(0.01)
            return _readings(self.scenario)
        finally:
            self.probe.reads -= 1


class _UnsafeDuckTypedDriver(_FakePassiveDriver):
    async def start_source(
        self,
        channel: str,
        p_target: float,
        v_compliance: float,
        i_compliance: float,
    ) -> None:
        raise AssertionError("passive conformance must never call source methods")

    async def stop_source(self, channel: str) -> None:
        raise AssertionError("passive conformance must never call source methods")


class _LeakyDisconnectDriver(_FakePassiveDriver):
    async def disconnect(self) -> None:
        self._connected = False


class _OverlappingSafeReadDriver(_FakePassiveDriver):
    async def safe_read(self) -> list[Reading]:
        return await self.read_channels()


class _UsableMalformedDriver(_FakePassiveDriver):
    async def read_channels(self) -> list[Reading]:
        return [_reading("Operator channel A", 4.2)]


class _ExternalCallingDriver(_FakePassiveDriver):
    async def read_channels(self) -> list[Reading]:
        self.probe.calls_outside_process += 1
        return await super().read_channels()


class _DisplayAliasDriver(_FakePassiveDriver):
    async def read_channels(self) -> list[Reading]:
        return [
            _reading("Stage 1 display name", 4.2),
            _reading("Stage 2 display name", 5.0),
        ]


class _ReconnectMutationDriver(_FakePassiveDriver):
    def __init__(
        self,
        scenario: PassiveConformanceScenario,
        probe: _Probe,
        *,
        drift: bool,
    ) -> None:
        super().__init__(scenario, probe)
        self.drift = drift

    async def read_channels(self) -> list[Reading]:
        readings = await super().read_channels()
        if self.connection_count < 2:
            return readings
        if self.drift:
            return [*readings[:-1], _reading("Drifted label", 5.0)]
        return list(reversed(readings))


class _MalformedFrame(ValueError):
    pass


class _EmptyMalformedDriver(_FakePassiveDriver):
    async def read_channels(self) -> list[Reading]:
        await super().read_channels()
        return []


class _DeclaredMalformedDriver(_FakePassiveDriver):
    async def read_channels(self) -> list[Reading]:
        self.probe.read_event.set()
        raise _MalformedFrame("invalid frame")


class _WrongShapeMalformedDriver(_FakePassiveDriver):
    async def read_channels(self) -> list[Reading]:
        return {"status": "malformed"}  # type: ignore[return-value]


class _CancellationResistantReadDriver(_FakePassiveDriver):
    def __init__(self, scenario: PassiveConformanceScenario, probe: _Probe) -> None:
        super().__init__(scenario, probe)
        self.release = asyncio.Event()

    async def read_channels(self) -> list[Reading]:
        self.probe.reads += 1
        self.probe.maximum_reads = max(self.probe.maximum_reads, self.probe.reads)
        self.probe.read_event.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await self.release.wait()
            return [_reading("Operator channel A", math.nan)]
        finally:
            self.probe.reads -= 1


class _CancellationResistantConnectDriver(_FakePassiveDriver):
    def __init__(self, scenario: PassiveConformanceScenario, probe: _Probe) -> None:
        super().__init__(scenario, probe)
        self.release = asyncio.Event()

    async def connect(self) -> None:
        self.probe.resources += 1
        self.probe.connect_event.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await self.release.wait()
        self._connected = True
        self.connection_count += 1


def _descriptor(index: int, *, instrument_id: str = "fake-passive") -> ChannelDescriptorV1:
    return ChannelDescriptorV1(
        schema_version=1,
        channel_id=f"{instrument_id}.temperature.stage-{index}",
        instrument_id=instrument_id,
        source_key=f"temperature-{index}",
        quantity=ChannelQuantity.TEMPERATURE,
        unit="K",
        role=ChannelRole.PRIMARY_MEASUREMENT,
        safety_class=ChannelSafetyClass.OBSERVATIONAL,
        display_group="Cryostat",
        display_name=f"Stage {index} display name",
        visible_by_default=True,
        display_order=index,
        descriptor_revision=1,
    )


def _reading(channel: str, value: object, status: ChannelStatus = ChannelStatus.OK) -> Reading:
    return Reading(
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        instrument_id="fake-passive",
        channel=channel,
        value=value,  # type: ignore[arg-type]
        unit="K",
        status=status,
    )


def _readings(scenario: PassiveConformanceScenario) -> list[Reading]:
    if scenario is PassiveConformanceScenario.UNUSABLE_MALFORMED:
        return [
            _reading("Operator channel A", math.nan),
            _reading("Operator channel B", math.inf),
            _reading("Operator channel A", "not-a-number"),
            _reading("Operator channel B", 4.2, ChannelStatus.SENSOR_ERROR),
        ]
    return [
        _reading("Operator channel A", 4.2),
        _reading("Operator channel B", 5.0),
    ]


def _bindings(*, instrument_id: str = "fake-passive") -> dict[tuple[str, str], ChannelDescriptorV1]:
    return {
        (instrument_id, "Operator channel A"): _descriptor(1, instrument_id=instrument_id),
        (instrument_id, "Operator channel B"): _descriptor(2, instrument_id=instrument_id),
    }


def _case(
    scenario: PassiveConformanceScenario,
    driver_type: type[_FakePassiveDriver] = _FakePassiveDriver,
    *,
    malformed_exceptions: tuple[type[Exception], ...] = (),
) -> PassiveConformanceCase:
    probe = _Probe()
    return PassiveConformanceCase(
        driver=driver_type(scenario, probe),
        probe=probe,
        emitted_bindings=_bindings(),
        malformed_exceptions=malformed_exceptions,
        timeout_s=0.5,
    )


async def test_fake_passive_driver_passes_complete_conformance_contract() -> None:
    await run_passive_conformance(_case)


async def test_malformed_contract_accepts_empty_batch_or_declared_exception() -> None:
    await run_passive_conformance(
        lambda scenario: _case(scenario, _EmptyMalformedDriver),
        scenarios=(PassiveConformanceScenario.UNUSABLE_MALFORMED,),
    )
    await run_passive_conformance(
        lambda scenario: _case(
            scenario,
            _DeclaredMalformedDriver,
            malformed_exceptions=(_MalformedFrame,),
        ),
        scenarios=(PassiveConformanceScenario.UNUSABLE_MALFORMED,),
    )


@pytest.mark.parametrize(
    "broad_error",
    [
        BaseException,
        Exception,
        AssertionError,
        TimeoutError,
        asyncio.CancelledError,
        PassiveConformanceTimeout,
    ],
)
def test_malformed_contract_rejects_broad_harness_or_control_exceptions(
    broad_error: type[BaseException],
) -> None:
    with pytest.raises((TypeError, ValueError)):
        PassiveConformanceCase(
            driver=_WrongShapeMalformedDriver(PassiveConformanceScenario.UNUSABLE_MALFORMED, _Probe()),
            probe=_Probe(),
            emitted_bindings=_bindings(),
            malformed_exceptions=(broad_error,),  # type: ignore[arg-type]
        )


def test_broad_exception_cannot_certify_cancellation_resistant_malformed_read() -> None:
    probe = _Probe()
    with pytest.raises(ValueError, match="harness or control-flow"):
        PassiveConformanceCase(
            driver=_CancellationResistantReadDriver(
                PassiveConformanceScenario.UNUSABLE_MALFORMED,
                probe,
            ),
            probe=probe,
            emitted_bindings=_bindings(),
            malformed_exceptions=(Exception,),
        )


async def test_malformed_contract_does_not_certify_wrong_result_shape() -> None:
    with pytest.raises(AssertionError):
        await run_passive_conformance(
            lambda scenario: _case(
                scenario,
                _WrongShapeMalformedDriver,
                malformed_exceptions=(_MalformedFrame,),
            ),
            scenarios=(PassiveConformanceScenario.UNUSABLE_MALFORMED,),
        )


async def test_malformed_contract_propagates_undeclared_device_exception() -> None:
    with pytest.raises(_MalformedFrame, match="invalid frame"):
        await run_passive_conformance(
            lambda scenario: _case(scenario, _DeclaredMalformedDriver),
            scenarios=(PassiveConformanceScenario.UNUSABLE_MALFORMED,),
        )


@pytest.mark.parametrize(
    ("driver_type", "scenario"),
    [
        (_LeakyDisconnectDriver, PassiveConformanceScenario.BOUNDED_CONNECT),
        (_OverlappingSafeReadDriver, PassiveConformanceScenario.SERIALIZED_SAFE_READ),
        (_UsableMalformedDriver, PassiveConformanceScenario.UNUSABLE_MALFORMED),
        (_ExternalCallingDriver, PassiveConformanceScenario.MOCK_IS_LOCAL),
    ],
)
async def test_harness_rejects_behavioral_mutants(
    driver_type: type[_FakePassiveDriver],
    scenario: PassiveConformanceScenario,
) -> None:
    with pytest.raises(AssertionError):
        await run_passive_conformance(
            lambda selected: _case(selected, driver_type),
            scenarios=(scenario,),
        )


async def test_reconnect_accepts_reordering_but_rejects_identity_drift() -> None:
    def factory(drift: bool):
        def build(scenario: PassiveConformanceScenario) -> PassiveConformanceCase:
            probe = _Probe()
            return PassiveConformanceCase(
                driver=_ReconnectMutationDriver(scenario, probe, drift=drift),
                probe=probe,
                emitted_bindings=_bindings(),
            )

        return build

    await run_passive_conformance(
        factory(False),
        scenarios=(PassiveConformanceScenario.RECONNECT_IDENTITY,),
    )
    with pytest.raises(AssertionError):
        await run_passive_conformance(
            factory(True),
            scenarios=(PassiveConformanceScenario.RECONNECT_IDENTITY,),
        )


async def test_descriptor_binding_rejects_display_alias_fallback() -> None:
    def alias_only_factory(scenario: PassiveConformanceScenario) -> PassiveConformanceCase:
        probe = _Probe()
        first = _descriptor(1)
        second = _descriptor(2)
        return PassiveConformanceCase(
            driver=_DisplayAliasDriver(scenario, probe),
            probe=probe,
            emitted_bindings={
                ("fake-passive", "Operator channel A"): first,
                ("fake-passive", "Operator channel B"): second,
            },
        )

    with pytest.raises(AssertionError, match="exact explicit runtime binding"):
        await run_passive_conformance(
            alias_only_factory,
            scenarios=(PassiveConformanceScenario.EXACT_DESCRIPTOR_BINDING,),
        )


async def test_bounded_operation_fails_promptly_and_exposes_unsettled_task() -> None:
    holder: list[_CancellationResistantConnectDriver] = []

    def factory(scenario: PassiveConformanceScenario) -> PassiveConformanceCase:
        probe = _Probe()
        driver = _CancellationResistantConnectDriver(scenario, probe)
        holder.append(driver)
        return PassiveConformanceCase(
            driver=driver,
            probe=probe,
            emitted_bindings=_bindings(),
            timeout_s=0.02,
        )

    with pytest.raises(PassiveConformanceTimeout) as raised:
        await run_passive_conformance(
            factory,
            scenarios=(PassiveConformanceScenario.BOUNDED_CONNECT,),
        )
    assert raised.value.settled is False
    assert not raised.value.task.done()
    holder[0].release.set()
    settled, _ = await asyncio.wait({raised.value.task}, timeout=0.5)
    assert settled
    raised.value.task.result()
    await holder[0].disconnect()
    assert holder[0].probe.active_resources == 0


async def test_malformed_declaration_cannot_swallow_cancellation_resistant_timeout() -> None:
    holder: list[_CancellationResistantReadDriver] = []

    def factory(scenario: PassiveConformanceScenario) -> PassiveConformanceCase:
        probe = _Probe()
        driver = _CancellationResistantReadDriver(scenario, probe)
        holder.append(driver)
        return PassiveConformanceCase(
            driver=driver,
            probe=probe,
            emitted_bindings=_bindings(),
            malformed_exceptions=(_MalformedFrame,),
            timeout_s=0.02,
        )

    with pytest.raises(PassiveConformanceTimeout) as raised:
        await run_passive_conformance(
            factory,
            scenarios=(PassiveConformanceScenario.UNUSABLE_MALFORMED,),
        )
    assert raised.value.settled is False
    holder[0].release.set()
    settled, _ = await asyncio.wait({raised.value.task}, timeout=0.5)
    assert settled
    assert all(not reading.is_usable() for reading in raised.value.task.result())
    await holder[0].disconnect()
    assert holder[0].probe.active_resources == 0


async def test_harness_rejects_a_reused_driver() -> None:
    shared_probe = _Probe()
    shared_driver = _FakePassiveDriver(PassiveConformanceScenario.BOUNDED_CONNECT, shared_probe)

    def reused_factory(scenario: PassiveConformanceScenario) -> PassiveConformanceCase:
        shared_driver.scenario = scenario
        return PassiveConformanceCase(
            driver=shared_driver,
            probe=shared_probe,
            emitted_bindings=_bindings(),
        )

    with pytest.raises(AssertionError, match="fresh driver"):
        await run_passive_conformance(reused_factory)


async def test_harness_rejects_duck_typed_source_capability_without_calling_it() -> None:
    with pytest.raises(AssertionError):
        await run_passive_conformance(
            lambda scenario: _case(scenario, _UnsafeDuckTypedDriver),
            scenarios=(PassiveConformanceScenario.NO_CONTROL_AUTHORITY,),
        )


class _LakeShorePublicProbe:
    def __init__(self, driver: LakeShore218S) -> None:
        self.driver = driver

    @property
    def active_resources(self) -> int:
        return int(self.driver.connected)

    @property
    def external_calls(self) -> int:
        raise AssertionError("external-call scenario is not claimed by this public-state probe")

    @property
    def concurrent_reads(self) -> int:
        raise AssertionError("concurrency scenario is not claimed by this public-state probe")

    @property
    def maximum_concurrent_reads(self) -> int:
        raise AssertionError("concurrency scenario is not claimed by this public-state probe")

    async def connect_entered(self) -> None:
        raise AssertionError("cancellation scenario is not claimed by this public-state probe")

    async def read_entered(self) -> None:
        raise AssertionError("cancellation scenario is not claimed by this public-state probe")


def _lakeshore_case(scenario: PassiveConformanceScenario) -> PassiveConformanceCase:
    driver = LakeShore218S("ls218s", "GPIB0::12::INSTR", mock=True)
    probe = _LakeShorePublicProbe(driver)
    bindings = {("ls218s", f"CH{index}"): _descriptor(index, instrument_id="ls218s") for index in range(1, 9)}
    return PassiveConformanceCase(
        driver=driver,
        probe=probe,
        emitted_bindings=bindings,
        timeout_s=0.5,
    )


async def test_real_lakeshore_mock_satisfies_public_contract_scenarios() -> None:
    await run_passive_conformance(
        _lakeshore_case,
        scenarios=(
            PassiveConformanceScenario.BOUNDED_CONNECT,
            PassiveConformanceScenario.EXACT_READING,
            PassiveConformanceScenario.RECONNECT_IDENTITY,
            PassiveConformanceScenario.IDEMPOTENT_DISCONNECT,
            PassiveConformanceScenario.EXACT_DESCRIPTOR_BINDING,
            PassiveConformanceScenario.NO_CONTROL_AUTHORITY,
        ),
    )


def test_downstream_interfaces_are_explicitly_deferred_not_simulated() -> None:
    assert {interface.name for interface in DeferredPassiveInterfaces} == {
        "PERSISTENCE",
        "REPLAY",
        "REPORTING",
        "OPERATOR_UI",
    }
    assert all(interface.value.startswith("blocked_until_") for interface in DeferredPassiveInterfaces)
