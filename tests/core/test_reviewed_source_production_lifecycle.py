"""Canonical registry -> SafetyManager -> Scheduler reviewed-source lifecycle."""

from __future__ import annotations

import asyncio
import logging

from cryodaq.core.broker import DataBroker
from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager
from cryodaq.core.scheduler import InstrumentConfig, Scheduler
from cryodaq.drivers import registry as driver_registry
from cryodaq.drivers.base import InstrumentDriver, Reading
from cryodaq.drivers.contracts import (
    AcquisitionTiming,
    DriverTrustClass,
    _issue_registry_runtime_binding,
    is_issued_runtime_binding,
)
from cryodaq.drivers.registry import (
    DriverConstructionContext,
    construct_driver,
    runtime_binding_for_driver,
    validate_instrument_entry,
)
from cryodaq.engine_wiring.supervision import stop_safety_manager_with_hold


class _ConnectedProofSource(InstrumentDriver):
    """Non-mock software source whose OFF proof requires a live connection."""

    def __init__(self) -> None:
        super().__init__("connected-proof-source", mock=False)
        self._connected = False
        self._output_state_unverified = False
        self.off_call_connected: list[bool] = []
        self.disconnect_calls = 0

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        self._connected = False

    async def read_channels(self) -> list[Reading]:
        return []

    async def emergency_off(self, channel: str | None = None) -> bool:
        del channel
        connected = self.connected is True
        self.off_call_connected.append(connected)
        return connected

    async def start_source(self, *_args: object, **_kwargs: object) -> None:
        return None

    async def stop_source(self, _channel: str) -> None:
        return None

    @property
    def output_state_unverified(self) -> bool:
        return self._output_state_unverified


def _bind_connected_proof_source(driver: InstrumentDriver):
    binding = _issue_registry_runtime_binding(
        driver=driver,
        timing=AcquisitionTiming(1.0, 1.0, 0.01),
        registry_provenance="test:production-shutdown-order",
        trust_class=DriverTrustClass.REVIEWED_SOURCE,
        bus_descriptor=None,
        lifecycle=None,
    )
    with driver_registry._RUNTIME_BINDINGS_LOCK:
        driver_registry._RUNTIME_BINDINGS[driver] = binding
    return binding


async def test_canonical_reviewed_source_qualifies_through_scheduler_start() -> None:
    async def _wait_until_qualified(state, manager, driver) -> None:
        while True:
            if (
                driver.connected
                and state.reviewed_source_attempt is None
                and state.reviewed_source_generation is not None
                and state.reviewed_source_generation is manager._reviewed_source_generation
                and state.total_reads > 0
            ):
                return
            if state.task is not None and state.task.done():
                state.task.result()
            await asyncio.sleep(0)

    validated = validate_instrument_entry(
        {
            "type": "keithley_2604b",
            "name": "reviewed-source-integration",
            "resource": "USB0::0x05E6::0x2604::MOCK00001::INSTR",
            "poll_interval_s": 0.01,
            "connect_timeout_s": 1.0,
            "read_timeout_s": 1.0,
        }
    )
    driver = construct_driver(validated, DriverConstructionContext(mock=True))
    binding = runtime_binding_for_driver(driver)
    assert binding is not None
    assert is_issued_runtime_binding(binding)
    assert binding.driver is driver
    assert binding.trust_class is DriverTrustClass.REVIEWED_SOURCE
    assert binding.bus_descriptor is None
    assert binding.lifecycle is None

    data_broker = DataBroker()
    safety_broker = SafetyBroker()
    manager = SafetyManager(
        safety_broker,
        keithley_driver=driver,
        reviewed_source_runtime_binding=binding,
        data_broker=data_broker,
        mock=False,
    )
    scheduler = Scheduler(
        data_broker,
        safety_broker=safety_broker,
        drain_timeout_s=0.5,
        reviewed_source_connect_begin=manager.begin_reviewed_source_connect,
        reviewed_source_connect_complete=manager.complete_reviewed_source_connect,
        reviewed_source_uncertain=manager.mark_reviewed_source_uncertain,
        reviewed_source_connect_abandon=manager.abandon_reviewed_source_connect,
        reviewed_source_disconnect=manager.disconnect_reviewed_source,
    )
    config = InstrumentConfig(driver=driver)
    assert config.runtime_binding is binding
    scheduler.add(config)
    state = scheduler._instruments[driver.name]

    manager_started = False
    scheduler_started = False
    try:
        await manager.start()
        manager_started = True
        assert manager._safety_children_authoritative()
        await scheduler.start()
        scheduler_started = True
        await asyncio.wait_for(
            _wait_until_qualified(state, manager, driver),
            timeout=2.0,
        )
        assert manager._reviewed_source_connected is True
        assert manager._reviewed_source_verified_off is True
        assert manager.snapshot_operator_safety().verified_off is True
        assert state.reviewed_source_disconnect_required is False
        assert state.total_reads > 0
        assert state.total_errors == 0
        assert driver.any_active is False
        assert scheduler._shared_bus_tasks == {}
    finally:
        try:
            if scheduler_started:
                await scheduler.stop()
        finally:
            if manager_started or manager._collect_task is not None or manager._monitor_task is not None:
                await manager.stop()

    assert driver.connected is False
    assert state.reviewed_source_generation is None
    assert manager._safety_children_authoritative() is False


async def test_shutdown_proves_nonmock_source_off_before_scheduler_disconnect() -> None:
    """Production ordering keeps connection authority until terminal OFF proof."""

    async def _wait_until_qualified(state, manager, driver) -> None:
        while True:
            if (
                driver.connected
                and state.reviewed_source_attempt is None
                and state.reviewed_source_generation is not None
                and state.reviewed_source_generation is manager._reviewed_source_generation
            ):
                return
            if state.task is not None and state.task.done():
                state.task.result()
            await asyncio.sleep(0)

    driver = _ConnectedProofSource()
    binding = _bind_connected_proof_source(driver)
    data_broker = DataBroker()
    safety_broker = SafetyBroker()
    manager = SafetyManager(
        safety_broker,
        keithley_driver=driver,
        reviewed_source_runtime_binding=binding,
        data_broker=data_broker,
        mock=False,
    )
    scheduler = Scheduler(
        data_broker,
        safety_broker=safety_broker,
        drain_timeout_s=0.5,
        reviewed_source_connect_begin=manager.begin_reviewed_source_connect,
        reviewed_source_connect_complete=manager.complete_reviewed_source_connect,
        reviewed_source_uncertain=manager.mark_reviewed_source_uncertain,
        reviewed_source_connect_abandon=manager.abandon_reviewed_source_connect,
        reviewed_source_disconnect=manager.disconnect_reviewed_source,
    )
    scheduler.add(InstrumentConfig(driver=driver, runtime_binding=binding))
    state = scheduler._instruments[driver.name]
    manager_owned = False
    scheduler_owned = False

    try:
        manager_owned = True
        await manager.start()
        scheduler_owned = True
        await scheduler.start()
        await asyncio.wait_for(_wait_until_qualified(state, manager, driver), timeout=2.0)

        assert driver.connected is True
        await stop_safety_manager_with_hold(
            manager,
            logging.getLogger("test-production-shutdown-order"),
            retry_delay_s=0.0,
        )
        manager_owned = False

        # The terminal manager proof ran while the exact reviewed source was
        # still connected. Only after that receipt may Scheduler disconnect it.
        assert driver.connected is True
        assert driver.off_call_connected
        assert all(driver.off_call_connected)
        await scheduler.stop()
        scheduler_owned = False
    finally:
        if manager_owned and (manager._collect_task is not None or manager._monitor_task is not None):
            await stop_safety_manager_with_hold(
                manager,
                logging.getLogger("test-production-shutdown-order-cleanup"),
                retry_delay_s=0.0,
            )
        if scheduler_owned:
            await scheduler.stop()

    assert driver.disconnect_calls == 1
    assert driver.connected is False
    assert driver.off_call_connected
    assert all(driver.off_call_connected)
    assert manager._collect_task is None
    assert manager._monitor_task is None
