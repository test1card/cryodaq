"""Source OFF consumers accept only fresh device-reported OFF evidence."""

from __future__ import annotations

from collections.abc import Callable

from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager, SafetyState
from cryodaq.drivers.contracts import (
    AcquisitionTiming,
    DriverTrustClass,
    SourceOffResult,
    SourceOffTier,
    _issue_registry_runtime_binding,
)
from cryodaq.drivers.instruments.keithley_2604b import Keithley2604B

_OUTCOMES = (
    SourceOffResult.DEVICE_REPORTED_OFF,
    SourceOffResult.PHYSICAL_STATE_UNKNOWN,
    SourceOffResult.COMMAND_ACCEPTED,
    True,
)


class _OffDriver:
    def __init__(self, result: object) -> None:
        self.result = result
        self.connected = True
        self.output_state_unverified = False
        self.disconnect_calls = 0
        self.start_calls = 0

    async def emergency_off(self, channel: str | None = None) -> object:
        del channel
        return self.result

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.connected = False

    async def start_source(
        self,
        channel: str,
        p_target: float,
        v_compliance: float,
        i_compliance: float,
    ) -> None:
        del channel, p_target, v_compliance, i_compliance
        self.start_calls += 1


def _manager(result: object) -> tuple[SafetyManager, _OffDriver, object]:
    driver = _OffDriver(result)
    binding = _issue_registry_runtime_binding(
        driver=driver,
        timing=AcquisitionTiming(1.0, 1.0, 1.0),
        registry_provenance="test:source-off-result-consumers",
        trust_class=DriverTrustClass.REVIEWED_SOURCE,
    )
    manager = SafetyManager(
        SafetyBroker(),
        keithley_driver=driver,
        reviewed_source_runtime_binding=binding,
        mock=False,
    )
    manager._safety_children_authoritative = lambda: True  # type: ignore[method-assign]
    manager._reviewed_source_generation = object()
    manager._reviewed_source_connected = True
    return manager, driver, binding


async def test_target_run_preflight_accepts_only_device_reported_off() -> None:
    accepted: list[bool] = []
    for outcome in _OUTCOMES:
        manager, driver, _binding = _manager(outcome)
        manager._state = SafetyState.RUNNING
        manager._active_sources.add("smub")
        manager._config.critical_channels = ()

        await manager.request_run(0.5, 40.0, 1.0, channel="smua")
        accepted.append(driver.start_calls == 1)

    assert accepted == [True, False, False, False]


async def test_reviewed_disconnect_accepts_only_device_reported_off() -> None:
    accepted: list[bool] = []
    for outcome in _OUTCOMES:
        manager, driver, binding = _manager(outcome)
        accepted.append(await manager.disconnect_reviewed_source(driver, binding, None, "test"))

    assert accepted == [True, False, False, False]


async def test_fault_settlement_accepts_only_device_reported_off() -> None:
    accepted: list[bool] = []
    for outcome in _OUTCOMES:
        manager, _driver, _binding = _manager(outcome)
        manager._active_sources.add("smua")

        await manager._fault("test")
        accepted.append(not manager._active_sources)

    assert accepted == [True, False, False, False]


async def test_operator_emergency_off_accepts_only_device_reported_off() -> None:
    accepted: list[bool] = []
    for outcome in _OUTCOMES:
        manager, _driver, _binding = _manager(outcome)
        manager._state = SafetyState.RUNNING
        manager._active_sources.add("smua")

        result = await manager.emergency_off()
        accepted.append(result["ok"] is True)

    assert accepted == [True, False, False, False]


async def test_unknown_off_is_never_promoted_in_manager_connect_or_snapshot() -> None:
    manager, driver, binding = _manager(SourceOffResult.PHYSICAL_STATE_UNKNOWN)
    driver.output_state_unverified = True

    evidence = await manager.complete_reviewed_source_connect(
        driver,
        binding,
        manager._reviewed_source_generation,
        "test",
    )
    snapshot = manager.snapshot_operator_safety()
    result = await manager.emergency_off()

    assert evidence.off_tier is SourceOffTier.VERIFIED_OFF
    assert evidence.receipt_payload()["verified_off"] is False
    assert snapshot.device_readback_off is False
    assert snapshot.verified_off is False
    assert result["off_evidence"]["verified_off"] is False


async def test_interlock_stop_source_accepts_only_device_reported_off() -> None:
    accepted: list[bool] = []
    for outcome in _OUTCOMES:
        manager, _driver, _binding = _manager(outcome)
        manager._state = SafetyState.RUNNING
        manager._active_sources.add("smua")

        await manager._on_interlock_trip_owned("test", "smua", 1.0, action="stop_source")
        accepted.append(manager.state is SafetyState.SAFE_OFF)

    assert accepted == [True, False, False, False]


async def test_watchdog_ack_accepts_only_device_reported_off() -> None:
    accepted: list[bool] = []
    for outcome in _OUTCOMES:
        driver = Keithley2604B(
            "k",
            "USB0::0x05E6::0x2604::04089762::INSTR",
            mock=False,
            watchdog_mode="best_effort",
        )
        driver._connected = True
        driver._instrument_id = "Keithley Instruments Inc., Model 2604B, 04089762, 4.0.8"
        driver._wdog_armed = True
        driver._wdog_trip_pending = True
        trip_readbacks = iter(("1", "0"))

        async def emergency_off() -> object:
            return outcome

        async def query(command: str, timeout_ms: int | None = None) -> str:
            del timeout_ms
            if command == "print(cryodaq_wdog_tripped)":
                return next(trip_readbacks)
            if command == "print(CRYODAQ_WDOG_VERSION)":
                return "3"
            if command == "print(cryodaq_wdog_active)":
                return "1"
            raise AssertionError(f"unexpected watchdog query: {command}")

        async def write(command: str, authority_check: Callable[[], None] | None = None) -> None:
            del command
            if authority_check is not None:
                authority_check()

        driver.emergency_off = emergency_off  # type: ignore[method-assign]
        driver._operational_query = query  # type: ignore[method-assign]
        driver._operational_write = write  # type: ignore[method-assign]

        accepted.append(await driver.acknowledge_wdog_trip())

    assert accepted == [True, False, False, False]
