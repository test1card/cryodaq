from __future__ import annotations

import asyncio
import re
import time
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.core.broker import DataBroker
from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import (
    SafetyManager,
    SafetyShutdownUnverifiedError,
    SafetyState,
)
from cryodaq.core.scheduler import InstrumentConfig, Scheduler
from cryodaq.drivers.contracts import (
    AcquisitionTiming,
    DriverTrustClass,
    SourceOffResult,
    VerifiedOffSource,
    _issue_registry_runtime_binding,
)
from cryodaq.drivers.instruments.keithley_2604b import Keithley2604B
from cryodaq.engine_wiring.operator_safety_snapshot import (
    OperatorSafetySnapshot,
    SafetyLifecycle,
)
from cryodaq.engine_wiring.operator_snapshot_authorities import (
    AuthorityAvailability,
    CommonCut,
)
from cryodaq.engine_wiring.operator_snapshot_live_authorities import (
    LiveSafetyReadinessAuthority,
)
from cryodaq.operator_snapshot import OperatorPresentationState, ReadinessTruth
from tests.qualification_support import issued_test_qualification_receipt

_CREATED_MANAGERS: list[SafetyManager] = []


def _manager(
    *,
    mock: bool = False,
    driver: object | None = None,
    safety_broker: SafetyBroker | None = None,
    data_broker: DataBroker | None = None,
) -> SafetyManager:
    if isinstance(driver, MagicMock):
        # A MagicMock attribute is callable but not awaitable. Give every
        # started fixture the real async driver lifecycle shape so teardown
        # exercises SafetyManager.stop() instead of failing on a test double.
        if not isinstance(getattr(driver, "stop_source", None), AsyncMock):
            driver.stop_source = AsyncMock(return_value=True)
        if not isinstance(getattr(driver, "emergency_off", None), AsyncMock):
            driver.emergency_off = AsyncMock(return_value=SourceOffResult.DEVICE_REPORTED_OFF)
        if type(getattr(driver, "output_state_unverified", None)) is not bool:
            driver.output_state_unverified = False
        if type(getattr(driver, "mock", None)) is not bool:
            driver.mock = mock
    binding = None
    if driver is not None:
        if mock and not isinstance(driver, MagicMock) and type(getattr(driver, "mock", None)) is not bool:
            driver.mock = True
        binding = _issue_registry_runtime_binding(
            driver=driver,
            timing=AcquisitionTiming(1.0, 1.0, 1.0),
            registry_provenance="test:safety-operator-owner",
            trust_class=DriverTrustClass.REVIEWED_SOURCE,
            simulation=mock,
        )
    manager = SafetyManager(
        safety_broker or SafetyBroker(),
        keithley_driver=driver,
        reviewed_source_runtime_binding=binding,
        qualification_receipt=(
            issued_test_qualification_receipt()
            if not mock or (driver is not None and getattr(driver, "mock", None) is False)
            else None
        ),
        mock=mock,
        data_broker=data_broker,
    )
    _CREATED_MANAGERS.append(manager)
    return manager


@pytest.fixture(autouse=True)
async def _settle_started_managers() -> None:
    """Give every real fixture the same explicit start/stop lifecycle as production."""

    first = len(_CREATED_MANAGERS)
    try:
        yield
    finally:
        created = _CREATED_MANAGERS[first:]
        errors: list[Exception] = []
        try:
            for manager in reversed(created):
                if (
                    manager._collect_task is not None
                    or manager._monitor_task is not None
                    or manager._pending_child_fault_settlements
                ):
                    try:
                        await manager.stop()
                    except Exception as exc:
                        errors.append(exc)
        finally:
            del _CREATED_MANAGERS[first:]
        if errors:
            raise ExceptionGroup("SafetyManager fixture teardown failures", errors)


def _codes(snapshot: OperatorSafetySnapshot) -> set[str]:
    return {item.code for item in snapshot.blockers}


async def _qualify_generation(
    manager: SafetyManager,
    driver: object,
    *,
    expected_verified_off: bool,
) -> None:
    if manager._child_generation == 0:
        await manager.start()
    generation = await manager.begin_reviewed_source_connect(
        driver,
        manager._reviewed_source_runtime_binding,  # type: ignore[arg-type]
        "test qualification",
    )
    committed = await manager.complete_reviewed_source_connect(
        driver,
        manager._reviewed_source_runtime_binding,  # type: ignore[arg-type]
        generation,
        "test qualification",
    )
    assert committed.verified_off is expected_verified_off


class _KeithleyObservationPlant:
    """Deterministic transport plant for output-observation authority tests."""

    resource = "USB0::0x05E6::0x2604::04089762::INSTR"
    identity = "Keithley Instruments Inc., Model 2604B, 04089762, 4.0.8"

    def __init__(self) -> None:
        self.output_state = {"smua": 0, "smub": 0}
        self.output_reply_override: dict[str, str] = {}
        self.block_idle_channel: str | None = None
        self.idle_query_entered = asyncio.Event()
        self.idle_query_release = asyncio.Event()
        self._idle_query_blocked = False
        self._off_nonce = re.compile(r"CRYODAQ_OFF_V1\|([0-9a-f]{32})\|%g")

    def apply_write(self, command: str) -> None:
        if ".source.output =" not in command:
            return
        channel = "smua" if command.startswith("smua.") else "smub"
        self.output_state[channel] = 1 if command.endswith(".OUTPUT_ON") else 0

    async def query(self, command: str, timeout_ms: int | None = None) -> str:
        del timeout_ms
        if command == "*IDN?":
            return self.identity
        match = self._off_nonce.search(command)
        if match is not None:
            channel = "smua" if "smua.source.output" in command else "smub"
            return f"CRYODAQ_OFF_V1|{match.group(1)}|{self.output_state[channel]}"
        for channel, state in self.output_state.items():
            if command == f"print({channel}.source.output)":
                reply = self.output_reply_override.get(channel, str(state))
                if self.block_idle_channel == channel and not self._idle_query_blocked:
                    self._idle_query_blocked = True
                    self.idle_query_entered.set()
                    await self.idle_query_release.wait()
                return reply
        if ".measure.iv()" in command:
            return "1e-3\t10.0"
        if ".source.compliance" in command:
            return "false"
        return "0"


async def _connected_observation_driver() -> tuple[
    Keithley2604B,
    _KeithleyObservationPlant,
    MagicMock,
]:
    plant = _KeithleyObservationPlant()
    driver = Keithley2604B("k2604", plant.resource, mock=False)
    transport = MagicMock()
    transport.open = AsyncMock()
    transport.close = AsyncMock()
    transport.query = AsyncMock(side_effect=plant.query)
    transport.write = AsyncMock(side_effect=plant.apply_write)
    driver._transport = transport
    await driver.connect()
    assert driver.output_state_unverified is False
    return driver, plant, transport


async def _yield_until(predicate, *, message: str) -> None:
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(0)
    pytest.fail(message)


_CUT = CommonCut(
    generation=1,
    token="cut-v1:1:" + "1" * 64,
    observed_at=datetime(2026, 7, 12, tzinfo=UTC),
)


def test_initial_cut_is_exact_unknown_false_and_disconnected() -> None:
    manager = _manager()
    snapshot = manager.snapshot_operator_safety()
    assert type(snapshot) is OperatorSafetySnapshot
    assert snapshot.revision == 1
    assert snapshot.lifecycle is SafetyLifecycle.UNKNOWN
    assert snapshot.readiness is ReadinessTruth.UNKNOWN
    assert snapshot.verified_off is False
    assert _codes(snapshot) == {"safety_authority_unavailable"}
    assert snapshot.plant_health[0].state is OperatorPresentationState.DISCONNECTED


def test_getter_is_identity_stable_and_performs_no_sampling_or_driver_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = MagicMock()
    driver.emergency_off = AsyncMock(side_effect=AssertionError("driver I/O"))
    manager = _manager(driver=driver)
    cached = manager.snapshot_operator_safety()
    monkeypatch.setattr(
        time,
        "monotonic",
        lambda: (_ for _ in ()).throw(AssertionError("time sampled")),
    )
    assert manager.snapshot_operator_safety() is cached
    driver.emergency_off.assert_not_awaited()


def test_explicit_connection_evidence_advances_exactly_one_revision_and_never_regresses_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(mock=True)
    first = manager.snapshot_operator_safety()
    monkeypatch.setattr(time, "monotonic", lambda: first.observed_monotonic_s - 100.0)
    manager.record_reviewed_source_connected(verified_off=False)
    connected = manager.snapshot_operator_safety()
    assert connected.revision == first.revision + 1
    assert connected.observed_monotonic_s == first.observed_monotonic_s
    assert connected.verified_off is False
    assert "reviewed_source_off_unverified" in _codes(connected)

    manager.record_reviewed_source_connected(verified_off=True)
    proved = manager.snapshot_operator_safety()
    assert proved.revision == connected.revision + 1
    assert proved.observed_monotonic_s == connected.observed_monotonic_s
    with pytest.raises(TypeError, match="exact bool"):
        manager.record_reviewed_source_connected(verified_off=1)  # type: ignore[arg-type]

    manager._active_sources.add("smua")
    with pytest.raises(ValueError, match="source lifecycle is active"):
        manager.record_reviewed_source_connected(verified_off=True)


def test_safe_off_name_and_empty_active_set_do_not_imply_ready() -> None:
    manager = _manager(mock=True)
    manager._safety_monitor_active = True
    manager.record_reviewed_source_connected(verified_off=True)
    snapshot = manager.snapshot_operator_safety()
    assert snapshot.lifecycle is SafetyLifecycle.SAFE_OFF
    assert snapshot.readiness is ReadinessTruth.BLOCKED
    assert snapshot.verified_off is True
    assert "safety_state_safe_off" in _codes(snapshot)


def test_state_change_observer_sees_the_matching_new_owner_cut() -> None:
    manager = _manager(mock=True)
    manager._safety_monitor_active = True
    manager.record_reviewed_source_connected(verified_off=True)
    observed: list[SafetyLifecycle] = []
    manager.on_state_change(lambda _old, _new, _reason: observed.append(manager.snapshot_operator_safety().lifecycle))
    manager._transition(SafetyState.READY, "qualified")
    assert observed == [SafetyLifecycle.READY]


def test_ready_requires_monitor_current_inputs_connection_and_exact_off_proof() -> None:
    manager = _manager(mock=True)
    manager._safety_monitor_active = True
    manager._config.critical_channels = [re.compile("critical/temperature")]
    manager._latest[("test", "critical/temperature")] = (time.monotonic(), 4.2, "ok")
    manager.record_reviewed_source_connected(verified_off=True)
    manager._transition(SafetyState.READY, "qualified")
    ready = manager.snapshot_operator_safety()
    assert ready.lifecycle is SafetyLifecycle.READY
    assert ready.readiness is ReadinessTruth.READY
    assert ready.verified_off is True
    assert ready.blockers == ()

    manager.record_reviewed_source_connected(verified_off=False)
    unproved = manager.snapshot_operator_safety()
    assert unproved.lifecycle is SafetyLifecycle.UNKNOWN
    assert unproved.readiness is ReadinessTruth.UNKNOWN
    assert unproved.verified_off is False
    assert "reviewed_source_off_unverified" in _codes(unproved)


@pytest.mark.parametrize("unsafe_kind", ("output_on", "invalid_readback"))
async def test_scheduler_observation_faults_external_sibling_of_managed_source(
    unsafe_kind: str,
) -> None:
    driver, plant, _transport = await _connected_observation_driver()
    data_broker = DataBroker()
    channel_states = await data_broker.subscribe(
        "unsafe_sibling_channel_states",
        maxsize=100,
        filter_fn=lambda reading: reading.channel.startswith("analytics/keithley_channel_state/"),
    )
    safety_broker = SafetyBroker()
    safety_tap = safety_broker.subscribe("unsafe_sibling_production_path", maxsize=100)
    writer = MagicMock()
    writer.is_disk_full = False
    writer.descriptor_authoritative = False
    writer.write_immediate = AsyncMock(return_value=True)
    scheduler = Scheduler(
        data_broker,
        safety_broker=safety_broker,
        sqlite_writer=writer,
    )
    scheduler.add(InstrumentConfig(driver=driver))
    state = scheduler._instruments[driver.name]
    manager = _manager(
        driver=driver,
        safety_broker=safety_broker,
        data_broker=data_broker,
    )
    manager._config.critical_channels = []
    try:
        await _qualify_generation(manager, driver, expected_verified_off=True)
        manager._transition(SafetyState.READY, "qualified before managed run")
        started = await manager.request_run(0.1, 1.0, 0.1, channel="smua")
        assert started["ok"] is True
        assert manager._active_sources == {"smua"}
        assert driver.active_channels == ["smua"]

        if unsafe_kind == "output_on":
            plant.output_state["smub"] = 1
        else:
            plant.output_reply_override["smub"] = "not-an-output-state"
        readings = await driver.read_channels()
        await scheduler._process_readings(state, readings)

        assert any(reading.channel == "k2604/smub/voltage" for reading in readings)
        assert any(
            observation.channel == "smub" and observation.kind == unsafe_kind
            for observation in driver.unsafe_output_observations
        )
        assert driver.output_state_unverified is True
        safety_channels = []
        while not safety_tap.empty():
            safety_reading = safety_tap.get_nowait()
            safety_channels.append(safety_reading.channel)
            safety_tap.task_done()
        assert "k2604/smub/voltage" in safety_channels
        writer.write_immediate.assert_awaited_once()

        await manager._run_checks()

        assert manager.state is SafetyState.FAULT_LATCHED
        assert f"positively observed unmanaged {unsafe_kind} on smub" in manager.fault_reason
        assert plant.output_state == {"smua": 0, "smub": 0}
        assert driver.output_state_unverified is False
        assert driver.active_channels == []
        assert manager._active_sources == set()
        assert driver.unsafe_output_observations == ()

        published = []
        while not channel_states.empty():
            published.append(channel_states.get_nowait())
            channel_states.task_done()
        final_states = {reading.metadata["channel"]: reading.metadata["state"] for reading in published[-2:]}
        assert final_states == {"smua": "off", "smub": "fault"}
    finally:
        await manager.stop()
        await driver.disconnect()


@pytest.mark.parametrize(
    "operation",
    ("targeted_stop", "targeted_emergency_off", "manager_stop"),
)
async def test_hazardous_success_reconciles_production_driver_sibling_on(
    operation: str,
) -> None:
    driver, plant, _transport = await _connected_observation_driver()
    data_broker = DataBroker()
    channel_states = await data_broker.subscribe(
        f"l05_hazardous_success_{operation}",
        maxsize=100,
        filter_fn=lambda reading: reading.channel.startswith("analytics/keithley_channel_state/"),
    )
    audit = AsyncMock()
    manager = _manager(driver=driver, data_broker=data_broker)
    manager._fault_log_callback = audit
    manager._config.critical_channels = []
    try:
        await _qualify_generation(manager, driver, expected_verified_off=True)
        manager._transition(SafetyState.READY, "qualified before L05 sibling observation")
        started = await manager.request_run(0.1, 1.0, 0.1, channel="smua")
        assert started["ok"] is True
        assert manager._active_sources == {"smua"}
        assert driver.active_channels == ["smua"]

        plant.output_state["smub"] = 1
        await driver.read_channels()
        assert any(
            observation.channel == "smub" and observation.kind == "output_on"
            for observation in driver.unsafe_output_observations
        )

        if operation == "targeted_stop":
            result = await manager.request_stop(channel="smua")
            assert result["ok"] is False
        elif operation == "targeted_emergency_off":
            result = await manager.emergency_off(channel="smua")
            assert result["ok"] is False
        else:
            with pytest.raises(SafetyShutdownUnverifiedError, match="unmanaged output_on on smub"):
                await manager.stop()

        assert manager.state is SafetyState.FAULT_LATCHED
        assert "positively observed unmanaged output_on on smub" in manager.fault_reason
        assert audit.await_count >= 1
        assert "positively observed unmanaged output_on on smub" in audit.await_args.kwargs["message"]
        assert plant.output_state == {"smua": 0, "smub": 0}
        assert driver.active_channels == []
        assert driver.unsafe_output_observations == ()
        assert driver.output_state_unverified is False
        assert manager._active_sources == set()
        assert manager._reviewed_source_off_evidence.verified_off is True

        final_states: dict[str, str] = {}
        while not channel_states.empty():
            reading = channel_states.get_nowait()
            final_states[reading.metadata["channel"]] = reading.metadata["state"]
            channel_states.task_done()
        assert final_states == {"smua": "off", "smub": "off"}
    finally:
        if (
            manager._collect_task is not None
            or manager._monitor_task is not None
            or manager._pending_child_fault_settlements
        ):
            await manager.stop()
        if driver.connected:
            await driver.disconnect()


async def test_observations_replace_per_channel_and_reconnect_rejects_late_generation() -> None:
    driver, plant, _transport = await _connected_observation_driver()
    try:
        plant.output_state["smua"] = 1
        await driver.read_channels()
        first = driver.unsafe_output_observations
        assert len(first) == 1
        assert first[0].channel == "smua"
        assert first[0].kind == "output_on"

        await driver.read_channels()
        repeated = driver.unsafe_output_observations
        assert len(repeated) == 1
        assert repeated[0].channel == "smua"
        assert repeated[0].sequence > first[0].sequence

        plant.output_reply_override["smub"] = "not-an-output-state"
        await driver.read_channels()
        by_channel = {observation.channel: observation for observation in driver.unsafe_output_observations}
        assert by_channel["smua"].kind == "output_on"
        assert by_channel["smub"].kind == "invalid_readback"

        stale_generation = by_channel["smua"].connection_generation
        stale_epoch = by_channel["smua"].command_epoch
        await driver.disconnect()
        assert driver.unsafe_output_observations == ()
        plant.output_reply_override.clear()
        await driver.connect()
        assert driver.source_connection_generation != stale_generation
        assert (
            driver._record_unsafe_output_observation(
                "smua",
                connection_generation=stale_generation,
                command_epoch=stale_epoch,
                operation="read_channels_idle_output_query",
                kind="output_on",
            )
            is False
        )
        assert driver.unsafe_output_observations == ()
    finally:
        if driver.connected:
            await driver.disconnect()


@pytest.mark.parametrize(
    "invalid_provenance",
    (
        "connection_generation",
        "command_epoch",
        "operation",
        "kind",
        "start_operation",
        "off_operation",
        "active_channel",
        "connect_transition",
        "disconnect_transition",
        "disconnected",
    ),
)
async def test_positive_observation_requires_every_current_idle_read_condition(
    invalid_provenance: str,
) -> None:
    driver, _plant, _transport = await _connected_observation_driver()
    generation = driver.source_connection_generation
    epoch = driver._source_command_epoch["smua"]
    operation = "read_channels_idle_output_query"
    kind = "output_on"
    try:
        if invalid_provenance == "connection_generation":
            generation -= 1
        elif invalid_provenance == "command_epoch":
            epoch -= 1
        elif invalid_provenance == "operation":
            operation = "start_source"
        elif invalid_provenance == "kind":
            kind = "off"
        elif invalid_provenance == "start_operation":
            driver._source_start_token["smua"] = epoch
        elif invalid_provenance == "off_operation":
            driver._source_off_depth["smua"] = 1
        elif invalid_provenance == "active_channel":
            driver._channels["smua"].active = True
        elif invalid_provenance == "connect_transition":
            driver._connect_in_progress = True
        elif invalid_provenance == "disconnect_transition":
            driver._disconnect_in_progress = True
        else:
            driver._connected = False

        assert (
            driver._record_unsafe_output_observation(
                "smua",
                connection_generation=generation,
                command_epoch=epoch,
                operation=operation,
                kind=kind,
            )
            is False
        )
        assert driver.unsafe_output_observations == ()
    finally:
        driver._source_start_token["smua"] = None
        driver._source_off_depth["smua"] = 0
        driver._channels["smua"].active = False
        driver._connect_in_progress = False
        driver._disconnect_in_progress = False
        driver._connected = True
        await driver.disconnect()


async def test_manager_owned_off_rejects_late_on_read_without_false_ready_fault() -> None:
    driver, plant, _transport = await _connected_observation_driver()
    manager = _manager(driver=driver)
    manager._config.critical_channels = []
    try:
        await _qualify_generation(manager, driver, expected_verified_off=True)
        manager._transition(SafetyState.READY, "qualified before owned OFF")
        plant.output_state["smua"] = 1
        plant.block_idle_channel = "smua"
        read_task = asyncio.create_task(driver.read_channels())
        await plant.idle_query_entered.wait()

        off_task = asyncio.create_task(manager.emergency_off(channel=None))
        await _yield_until(
            lambda: driver._source_off_depth["smua"] > 0,
            message="manager-owned OFF did not preclaim the driver command epoch",
        )
        assert driver.output_state_unverified is True
        await manager._run_checks()
        assert manager.state is SafetyState.READY
        assert driver.unsafe_output_observations == ()

        plant.idle_query_release.set()
        await asyncio.wait_for(read_task, timeout=2.0)
        off_result = await asyncio.wait_for(off_task, timeout=2.0)
        assert off_result["ok"] is True
        assert manager.state is SafetyState.SAFE_OFF
        assert plant.output_state == {"smua": 0, "smub": 0}
        assert driver.unsafe_output_observations == ()

        prior_generation = driver.source_connection_generation
        assert (
            await manager.disconnect_reviewed_source(
                driver,
                manager._reviewed_source_runtime_binding,  # type: ignore[arg-type]
                None,
                "observation generation replacement",
            )
            is True
        )
        await driver.connect()
        await _qualify_generation(manager, driver, expected_verified_off=True)
        assert driver.source_connection_generation != prior_generation
        await manager._run_checks()
        assert manager.state is not SafetyState.FAULT_LATCHED
        assert driver.unsafe_output_observations == ()
    finally:
        plant.idle_query_release.set()
        await manager.stop()
        if driver.connected:
            await driver.disconnect()


async def test_two_managed_channels_have_no_unmanaged_positive_observation() -> None:
    driver, _plant, _transport = await _connected_observation_driver()
    safety_broker = SafetyBroker()
    writer = MagicMock()
    writer.is_disk_full = False
    writer.descriptor_authoritative = False
    writer.write_immediate = AsyncMock(return_value=True)
    scheduler = Scheduler(
        DataBroker(),
        safety_broker=safety_broker,
        sqlite_writer=writer,
    )
    scheduler.add(InstrumentConfig(driver=driver))
    state = scheduler._instruments[driver.name]
    manager = _manager(driver=driver, safety_broker=safety_broker)
    manager._config.critical_channels = []
    manager._keithley_heartbeat_bindings = {
        "smua": frozenset({("k2604", "k2604/smua/voltage")}),
        "smub": frozenset({("k2604", "k2604/smub/voltage")}),
    }
    try:
        await _qualify_generation(manager, driver, expected_verified_off=True)
        manager._transition(SafetyState.READY, "qualified before dual managed run")
        assert (await manager.request_run(0.1, 1.0, 0.1, channel="smua"))["ok"] is True
        assert (await manager.request_run(0.1, 1.0, 0.1, channel="smub"))["ok"] is True
        readings = await driver.read_channels()
        await scheduler._process_readings(state, readings)
        await asyncio.sleep(0)

        assert driver.active_channels == ["smua", "smub"]
        assert manager._active_sources == {"smua", "smub"}
        assert driver.unsafe_output_observations == ()
        assert manager._current_unmanaged_output_hazard() is None
        await manager._run_checks()
        assert manager.state is SafetyState.RUNNING
        assert manager._active_sources == {"smua", "smub"}
    finally:
        await manager.stop()
        await driver.disconnect()


@pytest.mark.parametrize("begin_ready", (False, True))
async def test_request_run_requires_current_exact_reviewed_off_proof(
    begin_ready: bool,
) -> None:
    driver = MagicMock()
    driver.connected = True
    driver.output_state_unverified = False
    driver.watchdog_trip_pending = False
    driver.start_source = AsyncMock()
    manager = _manager(driver=driver)
    manager._config.critical_channels = []
    manager._safety_monitor_active = True
    if begin_ready:
        manager._transition(SafetyState.READY, "previously qualified")

    # Explicitly invalidating OFF proof must dominate both a READY FSM name
    # and a driver's non-affirmative ``output_state_unverified=False`` cache.
    driver.output_state_unverified = True
    await _qualify_generation(manager, driver, expected_verified_off=False)
    before = manager.snapshot_operator_safety()
    result = await manager.request_run(0.1, 1.0, 0.1)

    assert result == {
        "ok": False,
        "state": manager.state.value,
        "channel": "smua",
        "error": "Reviewed source OFF state is UNVERIFIED - confirm exact OFF before RUN",
    }
    driver.start_source.assert_not_awaited()
    assert manager.snapshot_operator_safety() is before
    assert before.verified_off is False
    expected_readiness = ReadinessTruth.UNKNOWN if begin_ready else ReadinessTruth.BLOCKED
    assert before.readiness is expected_readiness


async def test_second_channel_requires_ordered_exact_target_off_proof() -> None:
    order: list[tuple[str, str]] = []
    driver = MagicMock()
    driver.connected = True
    # A real dual-channel driver reports global OFF as unverified while smua
    # is intentionally active; that global fact must not replace smub proof.
    driver.output_state_unverified = True
    driver.watchdog_trip_pending = False

    async def _target_off(channel: str | None = None) -> SourceOffResult:
        order.append(("off", str(channel)))
        return SourceOffResult.DEVICE_REPORTED_OFF

    async def _start(channel: str, *_settings: float) -> None:
        order.append(("start", channel))

    driver.emergency_off = AsyncMock(side_effect=_target_off)
    driver.start_source = AsyncMock(side_effect=_start)
    manager = _manager(driver=driver)
    manager._config.critical_channels = []
    manager._safety_monitor_active = True
    await _qualify_generation(manager, driver, expected_verified_off=False)
    manager._state = SafetyState.RUNNING
    manager._active_sources.add("smua")
    manager._reviewed_source_off_evidence = manager._unknown_global_off_evidence()
    manager._refresh_operator_safety_snapshot()

    result = await manager.request_run(0.1, 1.0, 0.1, channel="smub")

    assert result["ok"] is True
    assert order == [("off", "smub"), ("start", "smub")]
    assert manager._active_sources == {"smua", "smub"}
    assert manager.snapshot_operator_safety().verified_off is False


@pytest.mark.parametrize(
    "target_result",
    (
        pytest.param(SourceOffResult.PHYSICAL_STATE_UNKNOWN, id="physical-state-unknown"),
        pytest.param(1, id="truthy-non-bool"),
        pytest.param(OSError("readback failed"), id="exception"),
    ),
)
async def test_second_channel_unverified_target_fails_closed(target_result: object) -> None:
    calls: list[str | None] = []

    async def _off(channel: str | None = None) -> object:
        calls.append(channel)
        if channel == "smub":
            if isinstance(target_result, BaseException):
                raise target_result
            return target_result
        driver.output_state_unverified = False
        return SourceOffResult.DEVICE_REPORTED_OFF

    driver = MagicMock()
    driver.connected = True
    driver.output_state_unverified = True
    driver.watchdog_trip_pending = False
    driver.emergency_off = AsyncMock(side_effect=_off)
    driver.start_source = AsyncMock()
    manager = _manager(driver=driver)
    manager._config.critical_channels = []
    manager._safety_monitor_active = True
    await _qualify_generation(manager, driver, expected_verified_off=False)
    manager._state = SafetyState.RUNNING
    manager._active_sources.add("smua")
    manager._reviewed_source_off_evidence = manager._unknown_global_off_evidence()

    result = await manager.request_run(0.1, 1.0, 0.1, channel="smub")

    assert result["ok"] is False
    assert result["state"] == SafetyState.FAULT_LATCHED.value
    assert result["error"] == "Target smub OFF state is UNVERIFIED before RUN"
    assert calls == ["smub", None]
    driver.start_source.assert_not_awaited()
    assert manager._active_sources == set()
    assert manager.snapshot_operator_safety().verified_off is True


async def test_cancelled_second_channel_proof_settles_full_fault_shutdown() -> None:
    entered = asyncio.Event()
    global_shutdown = asyncio.Event()

    async def _off(channel: str | None = None) -> SourceOffResult:
        if channel == "smub":
            entered.set()
            await asyncio.Future()
        global_shutdown.set()
        return SourceOffResult.DEVICE_REPORTED_OFF

    driver = MagicMock()
    driver.connected = True
    driver.output_state_unverified = True
    driver.watchdog_trip_pending = False
    driver.emergency_off = AsyncMock(side_effect=_off)
    driver.start_source = AsyncMock()
    manager = _manager(driver=driver)
    manager._config.critical_channels = []
    await _qualify_generation(manager, driver, expected_verified_off=False)
    manager._state = SafetyState.RUNNING
    manager._active_sources.add("smua")
    manager._reviewed_source_off_evidence = manager._unknown_global_off_evidence()

    task = asyncio.create_task(manager.request_run(0.1, 1.0, 0.1, channel="smub"))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert global_shutdown.is_set()
    assert manager.state is SafetyState.FAULT_LATCHED
    assert manager._active_sources == set()
    driver.start_source.assert_not_awaited()


async def test_same_turn_target_proof_completion_and_cancellation_still_force_full_fault() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    target_returned = asyncio.Event()
    global_shutdown = asyncio.Event()

    async def _off(channel: str | None = None) -> SourceOffResult:
        if channel == "smub":
            entered.set()
            await release.wait()
            target_returned.set()
            return SourceOffResult.DEVICE_REPORTED_OFF
        global_shutdown.set()
        return SourceOffResult.DEVICE_REPORTED_OFF

    driver = MagicMock()
    driver.connected = True
    driver.output_state_unverified = True
    driver.watchdog_trip_pending = False
    driver.emergency_off = AsyncMock(side_effect=_off)
    driver.start_source = AsyncMock()
    manager = _manager(driver=driver)
    manager._config.critical_channels = []
    await _qualify_generation(manager, driver, expected_verified_off=False)
    manager._state = SafetyState.RUNNING
    manager._active_sources.add("smua")
    manager._reviewed_source_off_evidence = manager._unknown_global_off_evidence()

    task = asyncio.create_task(manager.request_run(0.1, 1.0, 0.1, channel="smub"))
    await entered.wait()
    # Schedule the proof's successful completion before cancelling its owner.
    # The helper may therefore observe both device-reported OFF and caller
    # cancellation; cancellation must invalidate the scoped proof regardless.
    release.set()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert target_returned.is_set()
    assert global_shutdown.is_set()
    assert manager.state is SafetyState.FAULT_LATCHED
    assert manager._active_sources == set()
    driver.start_source.assert_not_awaited()


async def test_keithley_dual_channel_uses_scoped_proof_despite_global_active_flag() -> None:
    from cryodaq.drivers.instruments.keithley_2604b import Keithley2604B

    driver = Keithley2604B("source", "USB::MOCK", mock=True)
    await driver.connect()
    manager = _manager(driver=driver)
    manager._config.critical_channels = []
    await _qualify_generation(manager, driver, expected_verified_off=True)
    try:
        first = await manager.request_run(0.1, 1.0, 0.1, channel="smua")
        assert first["ok"] is True
        assert driver.output_state_unverified is True

        second = await manager.request_run(0.1, 1.0, 0.1, channel="smub")
        assert second["ok"] is True
        assert manager._active_sources == {"smua", "smub"}
        assert manager.snapshot_operator_safety().verified_off is False
    finally:
        await manager.emergency_off()
        await driver.disconnect()


@pytest.mark.parametrize(
    "state",
    (
        SafetyState.RUN_PERMITTED,
        SafetyState.RUNNING,
        SafetyState.FAULT_LATCHED,
        SafetyState.MANUAL_RECOVERY,
    ),
)
def test_active_fault_and_recovery_matrix_is_blocked(state: SafetyState) -> None:
    manager = _manager(mock=True)
    manager._safety_monitor_active = True
    manager.record_reviewed_source_connected(verified_off=True)
    if state in {SafetyState.RUN_PERMITTED, SafetyState.RUNNING}:
        manager._reviewed_source_off_evidence = manager._unknown_global_off_evidence()
        manager._active_sources.add("smua")
    manager._transition(state, "matrix")
    snapshot = manager.snapshot_operator_safety()
    assert snapshot.lifecycle is SafetyLifecycle(state.value)
    assert snapshot.readiness is ReadinessTruth.BLOCKED
    assert snapshot.blockers
    if state in {SafetyState.RUN_PERMITTED, SafetyState.RUNNING}:
        assert snapshot.verified_off is False
        assert "source_operation_active" in _codes(snapshot)


async def test_stale_invalid_and_missing_critical_inputs_are_explicit_blockers() -> None:
    driver = MagicMock()
    driver.connected = True
    driver.output_state_unverified = False
    manager = _manager(driver=driver)
    manager._safety_monitor_active = True
    await _qualify_generation(manager, driver, expected_verified_off=True)
    manager._config.critical_channels = [re.compile("critical/temperature")]
    manager._critical_input_bindings = {("test", "critical/temperature"): "critical.temperature"}

    manager._refresh_operator_safety_snapshot()
    assert "critical_input_missing" in _codes(manager.snapshot_operator_safety())

    manager._latest[("test", "critical/temperature")] = (
        time.monotonic() - manager._config.stale_timeout_s - 1.0,
        4.2,
        "ok",
    )
    manager._refresh_operator_safety_snapshot()
    assert "critical_input_stale" in _codes(manager.snapshot_operator_safety())

    manager._latest[("test", "critical/temperature")] = (time.monotonic(), float("nan"), "ok")
    manager._refresh_operator_safety_snapshot()
    assert "critical_input_invalid" in _codes(manager.snapshot_operator_safety())


async def test_persistence_fault_recovery_and_source_start_stop_each_refresh_owner_cut() -> None:
    driver = MagicMock()
    driver.start_source = AsyncMock()
    driver.stop_source = AsyncMock()
    driver.emergency_off = AsyncMock(return_value=SourceOffResult.DEVICE_REPORTED_OFF)
    driver.watchdog_trip_pending = False
    driver.output_state_unverified = False
    driver.connected = True
    manager = _manager(mock=True, driver=driver)
    await manager.start()
    try:
        before_run = manager.snapshot_operator_safety()
        result = await manager.request_run(0.1, 1.0, 0.1)
        running = manager.snapshot_operator_safety()
        assert result["ok"] is True
        assert running.revision > before_run.revision
        assert running.lifecycle is SafetyLifecycle.RUNNING
        assert running.verified_off is False

        result = await manager.request_stop()
        stopped = manager.snapshot_operator_safety()
        assert result["ok"] is True
        assert stopped.revision > running.revision
        assert stopped.verified_off is False
        assert stopped.device_readback_off is False

        await manager.on_persistence_failure("disk unavailable")
        faulted = manager.snapshot_operator_safety()
        assert faulted.revision > stopped.revision
        assert "persistence_fault_active" in _codes(faulted)

        manager._config.cooldown_before_rearm_s = 0.0
        recovered = await manager.acknowledge_fault("storage restored")
        recovery_cut = manager.snapshot_operator_safety()
        assert recovered["ok"] is True
        assert recovery_cut.revision > faulted.revision
        assert "persistence_fault_active" not in _codes(recovery_cut)
        assert recovery_cut.lifecycle is SafetyLifecycle.MANUAL_RECOVERY
    finally:
        before_stop = manager.snapshot_operator_safety().revision
        await manager.stop()
        assert manager.snapshot_operator_safety().revision > before_stop


async def test_confirmed_off_and_disconnect_are_separate_explicit_mutations() -> None:
    driver = MagicMock()
    driver.connected = True
    driver.emergency_off = AsyncMock(return_value=SourceOffResult.DEVICE_REPORTED_OFF)

    async def _disconnect() -> None:
        driver.connected = False

    driver.disconnect = AsyncMock(side_effect=_disconnect)
    manager = _manager(driver=driver)
    manager._safety_monitor_active = True
    before = manager.snapshot_operator_safety()
    assert (
        await manager.disconnect_reviewed_source(
            driver,
            manager._reviewed_source_runtime_binding,  # type: ignore[arg-type]
            None,
            "test",
        )
        is True
    )
    disconnected = manager.snapshot_operator_safety()
    assert disconnected.revision >= before.revision + 3
    assert disconnected.verified_off is False
    assert "reviewed_source_disconnected" in _codes(disconnected)
    driver.emergency_off.assert_awaited_once()
    driver.disconnect.assert_awaited_once()


async def test_disconnect_cancellation_settles_proof_and_lifecycle_revisions() -> None:
    off_started = asyncio.Event()
    off_release = asyncio.Event()
    disconnect_started = asyncio.Event()
    disconnect_release = asyncio.Event()

    class Driver:
        def __init__(self) -> None:
            self.connected = True
            self.output_state_unverified = False

        async def emergency_off(self) -> SourceOffResult:
            off_started.set()
            await off_release.wait()
            return SourceOffResult.DEVICE_REPORTED_OFF

        async def disconnect(self) -> None:
            disconnect_started.set()
            await disconnect_release.wait()
            self.connected = False

    driver = Driver()
    assert isinstance(driver, VerifiedOffSource)
    manager = _manager(driver=driver)
    manager._safety_monitor_active = True
    before = manager.snapshot_operator_safety()
    task = asyncio.create_task(
        manager.disconnect_reviewed_source(
            driver,
            manager._reviewed_source_runtime_binding,  # type: ignore[arg-type]
            None,
            "cancelled",
        )
    )
    await off_started.wait()
    task.cancel()
    off_release.set()
    await disconnect_started.wait()
    disconnect_release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    settled = manager.snapshot_operator_safety()
    assert settled.revision >= before.revision + 3
    assert settled.lifecycle is SafetyLifecycle.SAFE_OFF
    assert settled.verified_off is False
    assert "reviewed_source_disconnected" in _codes(settled)


def test_non_ok_plant_fact_is_not_implicitly_a_readiness_blocker() -> None:
    manager = _manager(mock=True)
    manager._safety_monitor_active = True
    manager.record_reviewed_source_connected(verified_off=True)
    manager._transition(SafetyState.READY, "qualified")
    snapshot = manager.snapshot_operator_safety()
    assert snapshot.blockers == ()
    # Plant health remains an independent typed collection; only explicit
    # SafetyBlocker values participate in readiness.
    assert all(fact.subsystem_id for fact in snapshot.plant_health)


@pytest.mark.parametrize("role", ("collect", "monitor"))
@pytest.mark.parametrize("outcome", ("completed", "failed", "cancelled"))
async def test_exact_child_death_invalidates_ready_off_and_available_ready_receipt(
    monkeypatch: pytest.MonkeyPatch,
    role: str,
    outcome: str,
) -> None:
    release = asyncio.Event()
    keep_alive = asyncio.Event()

    async def terminal_child() -> None:
        await release.wait()
        if outcome == "failed":
            raise RuntimeError("deterministic child failure")

    async def live_child() -> None:
        await keep_alive.wait()

    manager = _manager(mock=True)
    monkeypatch.setattr(
        manager,
        "_collect_loop",
        terminal_child if role == "collect" else live_child,
    )
    monkeypatch.setattr(
        manager,
        "_monitor_loop",
        terminal_child if role == "monitor" else live_child,
    )
    await manager.start()
    try:
        manager._transition(SafetyState.READY, "qualified child-liveness test")
        ready = manager.snapshot_operator_safety()
        assert ready.readiness is ReadinessTruth.READY
        assert ready.verified_off is True
        abort_before = manager._abort_generation

        task = manager._collect_task if role == "collect" else manager._monitor_task
        assert task is not None
        if outcome == "cancelled":
            task.cancel()
        else:
            release.set()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)

        failed = manager.snapshot_operator_safety()
        assert failed.revision > ready.revision
        assert failed.lifecycle is SafetyLifecycle.FAULT_LATCHED
        assert failed.readiness is ReadinessTruth.BLOCKED
        assert failed.verified_off is False
        assert manager.state is SafetyState.FAULT_LATCHED
        assert manager._abort_generation == abort_before + 1
        assert manager._full_abort_generation == manager._abort_generation
        assert manager._reviewed_source_generation is None
        assert manager._reviewed_source_connected is False
        assert not manager._reviewed_source_off_evidence.verified_off
        assert f"safety_{role}_{outcome}" in _codes(failed)
        failed_fact = next(fact for fact in failed.plant_health if fact.subsystem_id == f"safety_{role}")
        assert failed_fact.state is OperatorPresentationState.DISCONNECTED
        receipt = LiveSafetyReadinessAuthority(manager).snapshot_for_cut(_CUT)
        assert not (
            receipt.availability is AuthorityAvailability.AVAILABLE and receipt.readiness is ReadinessTruth.READY
        )
        assert receipt.verified_off is False
    finally:
        await manager.stop()


async def test_done_child_is_caught_before_done_callback_and_run_is_refused() -> None:
    never = asyncio.Event()

    async def done_child() -> None:
        return None

    async def live_child() -> None:
        await never.wait()

    driver = MagicMock()
    driver.start_source = AsyncMock()
    manager = _manager(mock=True, driver=driver)
    manager._child_generation = 1
    manager._collect_task = asyncio.create_task(done_child())
    manager._monitor_task = asyncio.create_task(live_child())
    manager._safety_monitor_active = True
    await manager._collect_task

    result = await manager.request_run(0.1, 1.0, 0.1)

    assert result["ok"] is False
    assert "monitor/collector authority" in result["error"]
    driver.start_source.assert_not_awaited()


async def test_child_death_during_inflight_start_forces_full_off_and_never_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child_release = asyncio.Event()
    live_release = asyncio.Event()
    start_entered = asyncio.Event()
    start_release = asyncio.Event()

    async def terminal_child() -> None:
        await child_release.wait()
        raise RuntimeError("monitoring lost during start")

    async def live_child() -> None:
        await live_release.wait()

    async def blocked_start(*_args: object) -> None:
        start_entered.set()
        await start_release.wait()

    driver = MagicMock()
    driver.start_source = AsyncMock(side_effect=blocked_start)
    driver.emergency_off = AsyncMock(return_value=SourceOffResult.DEVICE_REPORTED_OFF)
    manager = _manager(mock=True, driver=driver)
    monkeypatch.setattr(manager, "_collect_loop", terminal_child)
    monkeypatch.setattr(manager, "_monitor_loop", live_child)
    await manager.start()

    run = asyncio.create_task(manager.request_run(0.1, 1.0, 0.1, channel="smua"))
    try:
        await asyncio.wait_for(start_entered.wait(), 1.0)
    except TimeoutError:
        assert run.done(), "request_run neither reached the driver nor completed"
        pytest.fail(f"request_run returned before reaching the driver: {await run!r}")
    child_release.set()
    assert manager._collect_task is not None
    await asyncio.wait_for(
        asyncio.gather(manager._collect_task, return_exceptions=True),
        1.0,
    )
    await asyncio.sleep(0)
    assert manager.state is SafetyState.FAULT_LATCHED

    start_release.set()
    result = await asyncio.wait_for(run, 1.0)

    assert result["ok"] is False
    assert result["state"] == SafetyState.FAULT_LATCHED.value
    assert manager._active_sources == set()
    assert driver.emergency_off.await_count >= 1
    assert all(call.args in {(), (None,)} for call in driver.emergency_off.await_args_list)


async def test_child_death_during_second_channel_off_proof_never_starts_or_erases_fault(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child_release = asyncio.Event()
    monitor_release = asyncio.Event()
    target_entered = asyncio.Event()
    target_release = asyncio.Event()
    global_entered = asyncio.Event()
    global_release = asyncio.Event()

    async def terminal_child() -> None:
        await child_release.wait()

    async def live_monitor() -> None:
        await monitor_release.wait()

    async def blocked_off(channel: str | None = None) -> SourceOffResult:
        if channel == "smub":
            target_entered.set()
            await target_release.wait()
            return SourceOffResult.DEVICE_REPORTED_OFF
        global_entered.set()
        await global_release.wait()
        return SourceOffResult.DEVICE_REPORTED_OFF

    driver = MagicMock()
    driver.connected = True
    driver.output_state_unverified = False
    driver.watchdog_trip_pending = False
    driver.start_source = AsyncMock(return_value=None)
    driver.emergency_off = AsyncMock(side_effect=blocked_off)
    manager = _manager(driver=driver)
    manager._publish_keithley_channel_states = AsyncMock()  # type: ignore[method-assign]
    monkeypatch.setattr(manager, "_collect_loop", terminal_child)
    monkeypatch.setattr(manager, "_monitor_loop", live_monitor)
    await _qualify_generation(manager, driver, expected_verified_off=True)
    assert (await manager.request_run(0.1, 1.0, 0.1, channel="smua"))["ok"] is True

    second_start = asyncio.create_task(manager.request_run(0.1, 1.0, 0.1, channel="smub"))
    await target_entered.wait()
    child_release.set()
    assert manager._collect_task is not None
    await manager._collect_task
    await global_entered.wait()
    target_release.set()
    # Both the retained child-fault owner and the in-flight RUN owner are
    # allowed to repeat global OFF defensively. Release those OFF attempts
    # before awaiting the RUN result; otherwise the test itself deadlocks on
    # the very fail-closed settlement it is trying to observe.
    global_release.set()
    result = await second_start

    assert result["ok"] is False
    assert result["state"] == SafetyState.FAULT_LATCHED.value
    assert result["applied"] == {"output_off_confirmed": ["smub"]}
    assert [call.args[0] for call in driver.start_source.await_args_list] == ["smua"]
    events = manager.get_events()
    fault_index = next(i for i, event in enumerate(events) if event.to_state is SafetyState.FAULT_LATCHED)
    assert all(
        event.to_state not in {SafetyState.RUN_PERMITTED, SafetyState.RUNNING, SafetyState.SAFE_OFF}
        for event in events[fault_index + 1 :]
    )

    for _ in range(100):
        if not manager._pending_child_fault_settlements:
            break
        await asyncio.sleep(0)
    assert manager._pending_child_fault_settlements == set()


async def test_child_death_during_limit_write_prevents_commit_and_further_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child_release = asyncio.Event()
    live_release = asyncio.Event()
    write_entered = asyncio.Event()
    write_release = asyncio.Event()
    writes: list[str] = []

    async def terminal_child() -> None:
        await child_release.wait()

    async def live_child() -> None:
        await live_release.wait()

    async def blocked_write(
        channel: str,
        *,
        v_comp: float | None = None,
        i_comp: float | None = None,
    ) -> None:
        command = f"{channel}.source.limitv = {v_comp}" if v_comp is not None else f"{channel}.source.limiti = {i_comp}"
        writes.append(command)
        write_entered.set()
        await write_release.wait()

    runtime = MagicMock()
    runtime.active = True
    runtime.p_target = 0.5
    runtime.v_comp = 10.0
    runtime.i_comp = 0.1
    driver = MagicMock()
    driver.mock = False
    driver._channels = {"smua": runtime}
    driver.update_source_limit = AsyncMock(side_effect=blocked_write)
    driver.emergency_off = AsyncMock(return_value=SourceOffResult.DEVICE_REPORTED_OFF)
    manager = _manager(mock=True, driver=driver)
    monkeypatch.setattr(manager, "_collect_loop", terminal_child)
    monkeypatch.setattr(manager, "_monitor_loop", live_child)
    await manager.start()
    manager._state = SafetyState.RUNNING
    manager._active_sources.add("smua")

    update = asyncio.create_task(manager.update_limits(channel="smua", v_comp=20.0, i_comp=0.2))
    await write_entered.wait()
    child_release.set()
    assert manager._collect_task is not None
    await asyncio.gather(manager._collect_task, return_exceptions=True)
    await asyncio.sleep(0)
    write_release.set()
    result = await update

    assert result == {
        "ok": False,
        "error": "Safety authority was lost after a limit write reached hardware",
        "applied": {"v_comp": 20.0},
    }
    assert writes == ["smua.source.limitv = 20.0"]
    assert runtime.v_comp == 20.0
    assert runtime.i_comp == 0.1
    target = await manager.update_target(0.8, channel="smua")
    assert target == {"ok": False, "error": "Safety child authority is unavailable"}
    assert runtime.p_target == 0.5


async def test_replacement_and_reconnect_cannot_restore_faulted_child_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child_release = asyncio.Event()
    live_release = asyncio.Event()
    replacement_release = asyncio.Event()

    async def terminal_child() -> None:
        await child_release.wait()

    async def live_child() -> None:
        await live_release.wait()

    driver = MagicMock()
    driver.connected = True
    driver.output_state_unverified = False
    driver.watchdog_trip_pending = False
    driver.emergency_off = AsyncMock(return_value=SourceOffResult.DEVICE_REPORTED_OFF)
    manager = _manager(driver=driver)
    manager._config.critical_channels = []
    monkeypatch.setattr(manager, "_collect_loop", terminal_child)
    monkeypatch.setattr(manager, "_monitor_loop", live_child)
    await manager.start()
    generation = await manager.begin_reviewed_source_connect(
        driver,
        manager._reviewed_source_runtime_binding,  # type: ignore[arg-type]
        "initial proof",
    )
    assert (
        await manager.complete_reviewed_source_connect(
            driver,
            manager._reviewed_source_runtime_binding,  # type: ignore[arg-type]
            generation,
            "initial proof",
        )
    ).verified_off

    child_release.set()
    assert manager._collect_task is not None
    await asyncio.gather(manager._collect_task, return_exceptions=True)
    await asyncio.sleep(0)
    assert manager.snapshot_operator_safety().verified_off is False
    assert not (
        await manager.complete_reviewed_source_connect(
            driver,
            manager._reviewed_source_runtime_binding,  # type: ignore[arg-type]
            generation,
            "late proof",
        )
    ).verified_off

    async def replacement_child() -> None:
        await replacement_release.wait()

    replacement = asyncio.create_task(replacement_child())
    manager.replace_operator_child("collect", replacement)
    assert manager._collect_task is replacement
    assert manager._safety_children_authoritative() is False
    assert manager.snapshot_operator_safety().verified_off is False
    with pytest.raises(RuntimeError, match="without live safety children"):
        await manager.begin_reviewed_source_connect(
            driver,
            manager._reviewed_source_runtime_binding,  # type: ignore[arg-type]
            "replacement must not requalify",
        )

    replacement.cancel()
    await asyncio.gather(replacement, return_exceptions=True)
    await asyncio.sleep(0)
    assert manager._failed_child_reason == "safety_collect_cancelled"
    assert manager.state is SafetyState.FAULT_LATCHED
    assert manager.snapshot_operator_safety().verified_off is False


async def test_child_fault_off_settlement_is_retained_and_deadline_visible(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import cryodaq.core.safety_manager as safety_module

    child_release = asyncio.Event()
    live_release = asyncio.Event()
    off_entered = asyncio.Event()
    off_release = asyncio.Event()

    async def terminal_child() -> None:
        await child_release.wait()

    async def live_child() -> None:
        await live_release.wait()

    async def blocked_off(*_args: object) -> SourceOffResult:
        off_entered.set()
        await off_release.wait()
        return SourceOffResult.DEVICE_REPORTED_OFF

    driver = MagicMock()
    driver.emergency_off = AsyncMock(side_effect=blocked_off)
    manager = _manager(mock=True, driver=driver)
    monkeypatch.setattr(manager, "_collect_loop", terminal_child)
    monkeypatch.setattr(manager, "_monitor_loop", live_child)
    monkeypatch.setattr(safety_module, "_CHILD_FAULT_SETTLEMENT_DEADLINE_S", 0.01)
    await manager.start()
    child_release.set()
    assert manager._collect_task is not None
    await asyncio.gather(manager._collect_task, return_exceptions=True)
    await off_entered.wait()

    assert manager._pending_child_fault_settlements
    await asyncio.sleep(0.02)
    assert "remains strongly owned" in caplog.text
    assert manager._pending_child_fault_settlements

    off_release.set()
    for _ in range(100):
        if not manager._pending_child_fault_settlements:
            break
        await asyncio.sleep(0)
    assert manager._pending_child_fault_settlements == set()


async def test_expected_stop_settles_children_and_invalidates_ready_without_failure() -> None:
    manager = _manager(mock=True)
    await manager.start()
    manager._transition(SafetyState.READY, "qualified expected-stop test")
    before = manager.snapshot_operator_safety()

    await manager.stop()

    stopped = manager.snapshot_operator_safety()
    assert stopped.revision == before.revision + 1
    assert stopped.lifecycle is SafetyLifecycle.UNKNOWN
    assert stopped.readiness is ReadinessTruth.UNKNOWN
    assert stopped.verified_off is False
    assert "safety_manager_stopping" in _codes(stopped)
    assert manager._collect_task is None
    assert manager._monitor_task is None
    assert manager._consumed_child_tasks == set()


async def test_repeatedly_cancelled_stop_still_settles_both_exact_children_before_propagating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    never = asyncio.Event()
    cancellation_seen = asyncio.Event()
    release_settlement = asyncio.Event()
    cancellations = 0

    async def cancellation_delayed_child() -> None:
        nonlocal cancellations
        try:
            await never.wait()
        except asyncio.CancelledError:
            cancellations += 1
            if cancellations == 2:
                cancellation_seen.set()
            await release_settlement.wait()
            raise

    manager = _manager(mock=True)
    monkeypatch.setattr(manager, "_collect_loop", cancellation_delayed_child)
    monkeypatch.setattr(manager, "_monitor_loop", cancellation_delayed_child)
    await manager.start()
    manager._transition(SafetyState.READY, "qualified cancelled-stop test")

    stopping = asyncio.create_task(manager.stop())
    await cancellation_seen.wait()
    stopping.cancel()
    # Let stop() consume the first caller cancellation and enter its owned
    # child-settlement wait, then cancel it again. Repeated caller impatience
    # must not orphan either exact safety child or release the lifecycle cut.
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    stopping.cancel()
    release_settlement.set()
    with pytest.raises(asyncio.CancelledError):
        await stopping

    stopped = manager.snapshot_operator_safety()
    assert stopped.lifecycle is SafetyLifecycle.UNKNOWN
    assert stopped.readiness is ReadinessTruth.UNKNOWN
    assert stopped.verified_off is False
    assert manager._collect_task is None
    assert manager._monitor_task is None
    assert manager._stopping_child_generation is None


async def test_prior_generation_done_callback_cannot_invalidate_restarted_children(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    never = asyncio.Event()

    async def live_child() -> None:
        await never.wait()

    manager = _manager(mock=True)
    monkeypatch.setattr(manager, "_collect_loop", live_child)
    monkeypatch.setattr(manager, "_monitor_loop", live_child)
    await manager.start()
    old_collect = manager._collect_task
    old_generation = manager._child_generation
    assert old_collect is not None
    await manager.stop()

    await manager.start()
    try:
        manager._transition(SafetyState.READY, "qualified restarted generation")
        restarted = manager.snapshot_operator_safety()
        assert restarted.readiness is ReadinessTruth.READY
        manager._operator_child_done(
            old_collect,
            role="collect",
            generation=old_generation,
        )
        assert manager.snapshot_operator_safety() is restarted
        assert manager._safety_monitor_active is True
    finally:
        await manager.stop()


async def test_snapshot_consumes_terminal_child_before_queued_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child_release = asyncio.Event()
    monitor_release = asyncio.Event()
    settlement_release = asyncio.Event()
    settlement_sources: list[str] = []

    async def terminal_child() -> None:
        await child_release.wait()

    async def live_monitor() -> None:
        await monitor_release.wait()

    async def record_settlement(
        _reason: str,
        *,
        channel: str = "",
        value: float = 0.0,
        source: str = "safety_manager",
    ) -> None:
        del channel, value
        settlement_sources.append(source)
        await settlement_release.wait()

    manager = _manager(mock=True)
    manager._child_generation = 1
    manager._collect_task = asyncio.create_task(terminal_child())
    manager._monitor_task = asyncio.create_task(live_monitor())
    monkeypatch.setattr(manager, "_settle_latched_fault", record_settlement)
    manager._safety_monitor_active = True
    manager.record_reviewed_source_connected(verified_off=True)
    manager._transition(SafetyState.READY, "qualified before terminal child")
    assert manager.snapshot_operator_safety().verified_off is True

    child_release.set()
    await manager._collect_task
    manager._collect_task.add_done_callback(
        lambda completed: manager._operator_child_done(
            completed,
            role="collect",
            generation=1,
        )
    )
    # Adding a callback to an already-terminal task queues it for the next loop
    # turn. The synchronous snapshot must consume the exact child first, and the
    # queued callback must then observe the same de-dup marker.
    cut = manager.snapshot_operator_safety()
    await asyncio.sleep(0)

    assert cut.verified_off is False
    assert cut.lifecycle is SafetyLifecycle.FAULT_LATCHED
    assert cut.readiness is ReadinessTruth.BLOCKED
    assert manager._failed_child_reason == "safety_collect_completed"
    assert manager._fault_revision == 1
    assert settlement_sources == ["safety_collect"]
    assert len(manager._pending_child_fault_settlements) == 1

    settlement_release.set()
    for _ in range(100):
        if not manager._pending_child_fault_settlements:
            break
        await asyncio.sleep(0)
    monitor_release.set()
    await manager._monitor_task
    assert manager._pending_child_fault_settlements == set()


async def test_replacement_consumes_terminal_child_before_queued_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child_release = asyncio.Event()
    monitor_release = asyncio.Event()
    replacement_release = asyncio.Event()
    settlement_sources: list[str] = []

    async def terminal_child() -> None:
        await child_release.wait()

    async def live_monitor() -> None:
        await monitor_release.wait()

    async def replacement_child() -> None:
        await replacement_release.wait()

    async def record_settlement(
        _reason: str,
        *,
        channel: str = "",
        value: float = 0.0,
        source: str = "safety_manager",
    ) -> None:
        del channel, value
        settlement_sources.append(source)

    manager = _manager(mock=True)
    manager._child_generation = 1
    manager._collect_task = asyncio.create_task(terminal_child())
    manager._monitor_task = asyncio.create_task(live_monitor())
    monkeypatch.setattr(manager, "_settle_latched_fault", record_settlement)
    manager._safety_monitor_active = True
    manager.record_reviewed_source_connected(verified_off=True)
    manager._transition(SafetyState.READY, "qualified before replacement race")

    child_release.set()
    old_collect = manager._collect_task
    await old_collect
    old_collect.add_done_callback(
        lambda completed: manager._operator_child_done(
            completed,
            role="collect",
            generation=1,
        )
    )
    replacement = asyncio.create_task(replacement_child())
    # The queued callback above has not run yet. Replacement must consume the
    # exact terminal owner before swapping the role pointer.
    manager.replace_operator_child("collect", replacement)
    cut = manager.snapshot_operator_safety()
    await asyncio.sleep(0)

    assert manager._collect_task is replacement
    assert cut.lifecycle is SafetyLifecycle.FAULT_LATCHED
    assert cut.verified_off is False
    assert manager._failed_child_reason == "safety_collect_completed"
    assert manager._fault_revision == 1
    assert settlement_sources == ["safety_collect"]

    await manager.stop()


async def test_replacement_rejects_cross_role_task_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    never = asyncio.Event()

    async def live_child() -> None:
        await never.wait()

    manager = _manager(mock=True)
    monkeypatch.setattr(manager, "_collect_loop", live_child)
    monkeypatch.setattr(manager, "_monitor_loop", live_child)
    await manager.start()
    collect = manager._collect_task
    assert collect is not None

    with pytest.raises(RuntimeError, match="distinct task identities"):
        manager.replace_operator_child("monitor", collect)
    assert manager._collect_task is collect
    assert manager._monitor_task is not collect

    await manager.stop()


async def test_replacement_rejects_foreign_event_loop_task() -> None:
    monitor_release = asyncio.Event()

    async def live_monitor() -> None:
        await monitor_release.wait()

    def make_foreign_terminal_task() -> tuple[asyncio.AbstractEventLoop, asyncio.Task[None]]:
        foreign_loop = asyncio.new_event_loop()

        async def terminal() -> None:
            return None

        foreign_task = foreign_loop.create_task(terminal())
        foreign_loop.run_until_complete(foreign_task)
        return foreign_loop, foreign_task

    manager = _manager(mock=True)
    manager._child_generation = 1
    current = asyncio.create_task(asyncio.sleep(0))
    await current
    manager._collect_task = current
    manager._monitor_task = asyncio.create_task(live_monitor())
    foreign_loop, foreign_task = await asyncio.to_thread(make_foreign_terminal_task)

    try:
        with pytest.raises(RuntimeError, match="owner event loop"):
            manager.replace_operator_child("collect", foreign_task)
        assert manager._collect_task is current
    finally:
        monitor_release.set()
        await manager._monitor_task
        await asyncio.to_thread(foreign_loop.close)


async def test_stop_consumes_terminal_child_before_establishing_stop_cut(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child_release = asyncio.Event()
    monitor_release = asyncio.Event()
    settlement_sources: list[str] = []

    async def terminal_child() -> None:
        await child_release.wait()

    async def live_monitor() -> None:
        await monitor_release.wait()

    async def record_settlement(
        _reason: str,
        *,
        channel: str = "",
        value: float = 0.0,
        source: str = "safety_manager",
    ) -> None:
        del channel, value
        settlement_sources.append(source)

    manager = _manager(mock=True)
    manager._child_generation = 1
    manager._collect_task = asyncio.create_task(terminal_child())
    manager._monitor_task = asyncio.create_task(live_monitor())
    monkeypatch.setattr(manager, "_settle_latched_fault", record_settlement)
    manager._safety_monitor_active = True

    child_release.set()
    collect = manager._collect_task
    await collect
    collect.add_done_callback(
        lambda completed: manager._operator_child_done(
            completed,
            role="collect",
            generation=1,
        )
    )
    # The callback is queued but has not executed. stop() must consume the
    # terminal child before declaring this generation an expected stop.
    await manager.stop()

    assert manager.state is SafetyState.FAULT_LATCHED
    assert manager._failed_child_role == "collect"
    assert manager._failed_child_reason == "safety_collect_completed"
    assert manager._fault_revision == 1
    assert settlement_sources == ["safety_collect"]
    assert manager._pending_child_fault_settlements == set()


async def test_already_latched_child_death_revokes_snapshot_before_blocked_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child_release = asyncio.Event()
    monitor_release = asyncio.Event()
    off_entered = asyncio.Event()
    off_release = asyncio.Event()

    async def terminal_child() -> None:
        await child_release.wait()

    async def live_monitor() -> None:
        await monitor_release.wait()

    async def blocked_off(*_args: object) -> SourceOffResult:
        off_entered.set()
        await off_release.wait()
        return SourceOffResult.DEVICE_REPORTED_OFF

    driver = MagicMock()
    driver.emergency_off = AsyncMock(side_effect=blocked_off)
    fault_log = AsyncMock()
    manager = _manager(mock=True, driver=driver)
    manager._fault_log_callback = fault_log
    manager._publish_keithley_channel_states = AsyncMock()  # type: ignore[method-assign]
    monkeypatch.setattr(manager, "_collect_loop", terminal_child)
    monkeypatch.setattr(manager, "_monitor_loop", live_monitor)
    await manager.start()
    assert manager._begin_fault_latch("pre-existing fault", source="test") is True
    assert manager.snapshot_operator_safety().verified_off is True

    child_release.set()
    assert manager._collect_task is not None
    await manager._collect_task
    await off_entered.wait()

    cut = manager.snapshot_operator_safety()
    assert cut.verified_off is False
    assert manager.fault_reason == "pre-existing fault"
    assert manager._failed_child_reason == "safety_collect_completed"
    assert manager._pending_child_fault_settlements

    off_release.set()
    for _ in range(100):
        if not manager._pending_child_fault_settlements:
            break
        await asyncio.sleep(0)
    assert manager._pending_child_fault_settlements == set()
    fault_log.assert_awaited_once()
    assert fault_log.await_args.kwargs["source"] == "safety_collect"
    assert "exited unexpectedly" in fault_log.await_args.kwargs["message"]


async def test_stop_cut_does_not_suppress_child_exit_before_exact_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child_release = asyncio.Event()
    monitor_release = asyncio.Event()
    stop_entered = asyncio.Event()
    stop_release = asyncio.Event()

    async def terminal_child() -> None:
        await child_release.wait()

    async def live_monitor() -> None:
        await monitor_release.wait()

    async def blocked_stop(_channel: str) -> bool:
        stop_entered.set()
        await stop_release.wait()
        return True

    driver = MagicMock()
    driver.stop_source = AsyncMock(side_effect=blocked_stop)
    manager = _manager(mock=True, driver=driver)
    fault_log = AsyncMock()
    manager._fault_log_callback = fault_log
    manager._publish_keithley_channel_states = AsyncMock()  # type: ignore[method-assign]
    monkeypatch.setattr(manager, "_collect_loop", terminal_child)
    monkeypatch.setattr(manager, "_monitor_loop", live_monitor)
    await manager.start()
    manager._state = SafetyState.RUNNING
    manager._active_sources.add("smua")

    stopping = asyncio.create_task(manager.stop())
    await stop_entered.wait()
    child_release.set()
    assert manager._collect_task is not None
    await manager._collect_task
    await _yield_until(
        lambda: fault_log.await_count == 1 and not manager._pending_child_fault_settlements,
        message="stopping-window child exit did not settle its distinct fault audit",
    )

    assert manager.state is SafetyState.FAULT_LATCHED
    assert manager._failed_child_reason == "safety_collect_completed"
    assert manager._stopping_child_generation == manager._child_generation

    stop_release.set()
    await stopping
    assert manager.state is SafetyState.FAULT_LATCHED
    assert manager._active_sources == set()
    assert manager._failed_child_role == "collect"
    assert manager._pending_child_fault_settlements == set()
    assert manager._collect_task is None
    assert manager._monitor_task is None
    assert fault_log.await_args.kwargs["source"] == "safety_collect"


async def test_pending_old_child_settlement_blocks_new_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.core.safety_manager as safety_module

    child_release = asyncio.Event()
    monitor_release = asyncio.Event()
    off_entered = asyncio.Event()
    off_release = asyncio.Event()

    async def terminal_child() -> None:
        await child_release.wait()

    async def live_monitor() -> None:
        await monitor_release.wait()

    off_calls = 0

    async def blocked_off(*_args: object) -> SourceOffResult:
        nonlocal off_calls
        off_calls += 1
        if off_calls == 1:
            off_entered.set()
            await off_release.wait()
        return SourceOffResult.DEVICE_REPORTED_OFF

    driver = MagicMock()
    driver.emergency_off = AsyncMock(side_effect=blocked_off)
    manager = _manager(mock=True, driver=driver)
    manager._publish_keithley_channel_states = AsyncMock()  # type: ignore[method-assign]
    monkeypatch.setattr(manager, "_collect_loop", terminal_child)
    monkeypatch.setattr(manager, "_monitor_loop", live_monitor)
    monkeypatch.setattr(safety_module, "_CHILD_FAULT_SETTLEMENT_DEADLINE_S", 0.01)
    await manager.start()
    old_generation = manager._child_generation

    child_release.set()
    assert manager._collect_task is not None
    await manager._collect_task
    await off_entered.wait()
    with pytest.raises(SafetyShutdownUnverifiedError, match="fault settlement is still in progress"):
        await manager.stop()

    with pytest.raises(RuntimeError, match="fault settlement is still in progress"):
        await manager.start()

    off_release.set()
    for _ in range(100):
        if not manager._pending_child_fault_settlements:
            break
        await asyncio.sleep(0)
    assert manager._pending_child_fault_settlements == set()

    # The failed tentative stop deliberately retained the old children. A
    # fresh explicit stop must close that generation before restart; settlement
    # completion alone never transfers lifecycle ownership implicitly.
    await manager.stop()
    assert manager._collect_task is None
    assert manager._monitor_task is None

    await manager.start()
    assert manager._child_generation == old_generation + 1
    await manager.stop()


async def test_non_child_fault_stops_limit_update_after_first_applied_write() -> None:
    write_entered = asyncio.Event()
    write_release = asyncio.Event()
    writes: list[str] = []

    async def blocked_write(
        channel: str,
        *,
        v_comp: float | None = None,
        i_comp: float | None = None,
    ) -> None:
        command = f"{channel}.source.limitv = {v_comp}" if v_comp is not None else f"{channel}.source.limiti = {i_comp}"
        writes.append(command)
        write_entered.set()
        await write_release.wait()

    runtime = MagicMock()
    runtime.active = True
    runtime.p_target = 0.5
    runtime.v_comp = 10.0
    runtime.i_comp = 0.1
    driver = MagicMock()
    driver.mock = False
    driver._channels = {"smua": runtime}
    driver.update_source_limit = AsyncMock(side_effect=blocked_write)
    driver.emergency_off = AsyncMock(return_value=SourceOffResult.DEVICE_REPORTED_OFF)
    manager = _manager(mock=True, driver=driver)
    manager._publish_keithley_channel_states = AsyncMock()  # type: ignore[method-assign]
    await manager.start()
    manager._state = SafetyState.RUNNING
    manager._active_sources.add("smua")

    update = asyncio.create_task(manager.update_limits(channel="smua", v_comp=20.0, i_comp=0.2))
    await write_entered.wait()
    fault = asyncio.create_task(manager.latch_fault("rate fault", source="test"))
    for _ in range(100):
        if manager.state is SafetyState.FAULT_LATCHED:
            break
        await asyncio.sleep(0)
    assert manager.state is SafetyState.FAULT_LATCHED

    write_release.set()
    result = await update
    await fault

    assert result == {
        "ok": False,
        "error": "Safety authority was lost after a limit write reached hardware",
        "applied": {"v_comp": 20.0},
    }
    assert writes == ["smua.source.limitv = 20.0"]
    assert runtime.v_comp == 20.0
    assert runtime.i_comp == 0.1


@pytest.mark.parametrize("prelatched", [False, True])
async def test_stop_holds_live_safety_owner_until_global_off_is_verified(
    monkeypatch: pytest.MonkeyPatch,
    prelatched: bool,
) -> None:
    children_release = asyncio.Event()

    async def live_child() -> None:
        await children_release.wait()

    driver = MagicMock()
    driver.stop_source = AsyncMock(side_effect=RuntimeError("target OFF unverified"))
    driver.emergency_off = AsyncMock(return_value=SourceOffResult.PHYSICAL_STATE_UNKNOWN)
    manager = _manager(mock=True, driver=driver)
    monkeypatch.setattr(manager, "_collect_loop", live_child)
    monkeypatch.setattr(manager, "_monitor_loop", live_child)
    await manager.start()
    manager._state = SafetyState.RUNNING
    manager._active_sources.add("smua")
    if prelatched:
        assert manager._begin_fault_latch("pre-existing shutdown fault", source="test")

    with pytest.raises(SafetyShutdownUnverifiedError, match="global OFF could not be verified"):
        await manager.stop()

    assert manager._active_sources == {"smua"}
    held_cut = manager.snapshot_operator_safety()
    assert held_cut.verified_off is False
    assert "safety_manager_stopping" not in _codes(held_cut)
    assert manager._collect_task is not None and not manager._collect_task.done()
    assert manager._monitor_task is not None and not manager._monitor_task.done()
    assert manager._stopping_child_generation is None
    assert manager._safety_children_authoritative() is True
    assert manager.state is SafetyState.FAULT_LATCHED

    # An explicit later retry may close the HOLD only after the exact global
    # OFF operation returns DEVICE_REPORTED_OFF. The original safety children remain owned
    # until that proof exists, then settle as part of the same retry.
    driver.emergency_off = AsyncMock(return_value=SourceOffResult.DEVICE_REPORTED_OFF)
    await manager.stop()
    assert manager._active_sources == set()
    assert manager._collect_task is None
    assert manager._monitor_task is None


async def test_repeated_shutdown_hold_retries_coalesce_retained_owner_but_issue_fresh_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    children_release = asyncio.Event()
    retained_off_entered = asyncio.Event()
    retained_off_release = asyncio.Event()
    off_calls: list[int] = []

    async def live_child() -> None:
        await children_release.wait()

    async def controlled_off() -> SourceOffResult:
        call = len(off_calls) + 1
        off_calls.append(call)
        if call == 2:
            retained_off_entered.set()
            await retained_off_release.wait()
            return SourceOffResult.PHYSICAL_STATE_UNKNOWN
        return SourceOffResult.DEVICE_REPORTED_OFF if call >= 4 else SourceOffResult.PHYSICAL_STATE_UNKNOWN

    driver = MagicMock()
    driver.emergency_off = AsyncMock(side_effect=controlled_off)
    manager = _manager(mock=True, driver=driver)
    manager._publish_keithley_channel_states = AsyncMock()  # type: ignore[method-assign]
    monkeypatch.setattr(manager, "_collect_loop", live_child)
    monkeypatch.setattr(manager, "_monitor_loop", live_child)
    await manager.start()

    with pytest.raises(SafetyShutdownUnverifiedError, match="global OFF could not be verified"):
        await manager.stop()
    await retained_off_entered.wait()
    retained_owner = manager._shutdown_hold_fault_settlement
    assert retained_owner is not None and not retained_owner.done()
    assert manager._pending_child_fault_settlements == {retained_owner}

    with pytest.raises(SafetyShutdownUnverifiedError, match="global OFF could not be verified"):
        await manager.stop()
    assert off_calls == [1, 2, 3]
    assert manager._shutdown_hold_fault_settlement is retained_owner
    assert manager._pending_child_fault_settlements == {retained_owner}
    assert manager._collect_task is not None and not manager._collect_task.done()
    assert manager._monitor_task is not None and not manager._monitor_task.done()

    retained_off_release.set()
    for _ in range(100):
        if not manager._pending_child_fault_settlements:
            break
        await asyncio.sleep(0)
    assert manager._pending_child_fault_settlements == set()
    assert manager._shutdown_hold_fault_settlement is None

    await manager.stop()
    assert off_calls == [1, 2, 3, 4, 5]
    assert manager._collect_task is None
    assert manager._monitor_task is None


async def test_cancelled_shutdown_hold_restores_owner_cut_before_propagating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    children_release = asyncio.Event()
    off_entered = asyncio.Event()
    off_release = asyncio.Event()
    off_calls = 0

    async def live_child() -> None:
        await children_release.wait()

    async def controlled_off() -> bool:
        nonlocal off_calls
        off_calls += 1
        if off_calls == 1:
            off_entered.set()
            await off_release.wait()
        return False

    manager = _manager(mock=True)
    monkeypatch.setattr(manager, "_collect_loop", live_child)
    monkeypatch.setattr(manager, "_monitor_loop", live_child)
    monkeypatch.setattr(manager, "_ensure_output_off", controlled_off)
    await manager.start()

    stopping = asyncio.create_task(manager.stop())
    await off_entered.wait()
    stopping.cancel()
    await asyncio.sleep(0)
    assert not stopping.done()
    off_release.set()
    with pytest.raises(asyncio.CancelledError):
        await stopping

    held_cut = manager.snapshot_operator_safety()
    assert held_cut.verified_off is False
    assert "safety_manager_stopping" not in _codes(held_cut)
    assert manager._stopping_child_generation is None
    assert manager._safety_children_authoritative() is True
    assert manager._collect_task is not None and not manager._collect_task.done()
    assert manager._monitor_task is not None and not manager._monitor_task.done()

    monkeypatch.setattr(manager, "_ensure_output_off", AsyncMock(return_value=True))
    await manager.stop()


async def test_successful_retry_waits_for_older_inconclusive_hold_settlement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.core.safety_manager as safety_module

    children_release = asyncio.Event()
    retained_off_entered = asyncio.Event()
    retained_off_release = asyncio.Event()
    off_calls: list[int] = []

    async def live_child() -> None:
        await children_release.wait()

    async def controlled_off() -> SourceOffResult:
        call = len(off_calls) + 1
        off_calls.append(call)
        if call == 2:
            retained_off_entered.set()
            await retained_off_release.wait()
            return SourceOffResult.PHYSICAL_STATE_UNKNOWN
        return SourceOffResult.DEVICE_REPORTED_OFF if call >= 3 else SourceOffResult.PHYSICAL_STATE_UNKNOWN

    driver = MagicMock()
    driver.emergency_off = AsyncMock(side_effect=controlled_off)
    manager = _manager(mock=True, driver=driver)
    monkeypatch.setattr(manager, "_collect_loop", live_child)
    monkeypatch.setattr(manager, "_monitor_loop", live_child)
    monkeypatch.setattr(safety_module, "_CHILD_FAULT_SETTLEMENT_DEADLINE_S", 0.01)
    await manager.start()

    with pytest.raises(SafetyShutdownUnverifiedError, match="global OFF could not be verified"):
        await manager.stop()
    await retained_off_entered.wait()
    retained_owner = manager._shutdown_hold_fault_settlement
    assert retained_owner is not None and not retained_owner.done()

    # The retry's fresh global proof succeeds, but shutdown cannot release its
    # owner cut until the older retained settlement reaches a terminal result.
    with pytest.raises(SafetyShutdownUnverifiedError, match="fault settlement is still in progress"):
        await manager.stop()
    assert off_calls == [1, 2, 3]
    assert manager._active_sources == set()
    assert manager._collect_task is not None and not manager._collect_task.done()
    assert manager._monitor_task is not None and not manager._monitor_task.done()
    assert manager._stopping_child_generation is None

    retained_off_release.set()
    for _ in range(100):
        if not manager._pending_child_fault_settlements:
            break
        await asyncio.sleep(0)
    assert retained_owner.done()
    assert manager._pending_child_fault_settlements == set()
    assert manager._shutdown_hold_fault_settlement is None
    assert manager._stopping_child_generation is None

    await manager.stop()
    assert off_calls == [1, 2, 3, 4, 5]


async def test_older_inconclusive_hold_cannot_follow_newer_proof_into_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    children_release = asyncio.Event()
    retained_off_release = asyncio.Event()
    retry_proof_entered = asyncio.Event()
    off_calls: list[int] = []
    retained_owner: asyncio.Task[object] | None = None

    async def live_child() -> None:
        await children_release.wait()

    async def ordered_off() -> SourceOffResult:
        call = len(off_calls) + 1
        off_calls.append(call)
        if call == 2:
            await retained_off_release.wait()
            return SourceOffResult.PHYSICAL_STATE_UNKNOWN
        if call == 3:
            retry_proof_entered.set()
            retained_off_release.set()
            assert retained_owner is not None
            await retained_owner
            # Let its registered cleanup callbacks remove it from the live set
            # before this newer proof returns. The stop call must still retain
            # the frozen pre-proof identity and demand call 4.
            await asyncio.sleep(0)
            return SourceOffResult.DEVICE_REPORTED_OFF
        return SourceOffResult.PHYSICAL_STATE_UNKNOWN

    driver = MagicMock()
    driver.emergency_off = AsyncMock(side_effect=ordered_off)
    manager = _manager(mock=True, driver=driver)
    monkeypatch.setattr(manager, "_collect_loop", live_child)
    monkeypatch.setattr(manager, "_monitor_loop", live_child)
    await manager.start()

    with pytest.raises(SafetyShutdownUnverifiedError, match="global OFF could not be verified"):
        await manager.stop()
    retained_owner = manager._shutdown_hold_fault_settlement
    assert retained_owner is not None
    retry = asyncio.create_task(manager.stop())
    await retry_proof_entered.wait()
    with pytest.raises(SafetyShutdownUnverifiedError, match="global OFF could not be verified"):
        await retry

    assert off_calls[:4] == [1, 2, 3, 4]
    assert manager.snapshot_operator_safety().verified_off is False
    assert manager._collect_task is not None and not manager._collect_task.done()
    assert manager._monitor_task is not None and not manager._monitor_task.done()
    assert manager._stopping_child_generation is None

    driver.emergency_off = AsyncMock(return_value=SourceOffResult.DEVICE_REPORTED_OFF)
    for _ in range(100):
        if not manager._pending_child_fault_settlements:
            break
        await asyncio.sleep(0)
    await manager.stop()


async def test_cancelled_retry_with_pending_hold_restores_cut_then_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.core.safety_manager as safety_module

    children_release = asyncio.Event()
    retained_off_release = asyncio.Event()
    retry_proof_entered = asyncio.Event()
    off_calls: list[int] = []

    async def live_child() -> None:
        await children_release.wait()

    async def controlled_off() -> SourceOffResult:
        call = len(off_calls) + 1
        off_calls.append(call)
        if call == 2:
            await retained_off_release.wait()
            return SourceOffResult.PHYSICAL_STATE_UNKNOWN
        if call == 3:
            retry_proof_entered.set()
            return SourceOffResult.DEVICE_REPORTED_OFF
        return SourceOffResult.DEVICE_REPORTED_OFF if call >= 4 else SourceOffResult.PHYSICAL_STATE_UNKNOWN

    driver = MagicMock()
    driver.emergency_off = AsyncMock(side_effect=controlled_off)
    manager = _manager(mock=True, driver=driver)
    monkeypatch.setattr(manager, "_collect_loop", live_child)
    monkeypatch.setattr(manager, "_monitor_loop", live_child)
    monkeypatch.setattr(safety_module, "_CHILD_FAULT_SETTLEMENT_DEADLINE_S", 0.05)
    await manager.start()

    with pytest.raises(SafetyShutdownUnverifiedError, match="global OFF could not be verified"):
        await manager.stop()
    retry = asyncio.create_task(manager.stop())
    await retry_proof_entered.wait()
    retry.cancel()
    with pytest.raises(asyncio.CancelledError):
        await retry

    assert manager._stopping_child_generation is None
    assert manager._collect_task is not None and not manager._collect_task.done()
    assert manager._monitor_task is not None and not manager._monitor_task.done()

    retained_off_release.set()
    for _ in range(100):
        if not manager._pending_child_fault_settlements:
            break
        await asyncio.sleep(0)
    await manager.stop()


async def test_failed_stop_does_not_reconsume_child_processed_before_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child_release = asyncio.Event()
    monitor_release = asyncio.Event()
    settlement_sources: list[str] = []

    async def terminal_child() -> None:
        await child_release.wait()

    async def live_monitor() -> None:
        await monitor_release.wait()

    async def record_settlement(
        _reason: str,
        *,
        channel: str = "",
        value: float = 0.0,
        source: str = "safety_manager",
    ) -> None:
        del channel, value
        settlement_sources.append(source)

    manager = _manager(mock=True)
    monkeypatch.setattr(manager, "_collect_loop", terminal_child)
    monkeypatch.setattr(manager, "_monitor_loop", live_monitor)
    monkeypatch.setattr(manager, "_settle_latched_fault", record_settlement)
    await manager.start()

    child_release.set()
    assert manager._collect_task is not None
    collect_task = manager._collect_task
    await collect_task
    manager.snapshot_operator_safety()
    await asyncio.sleep(0)
    assert settlement_sources == ["safety_collect"]
    assert collect_task in manager._consumed_child_tasks

    monkeypatch.setattr(manager, "_ensure_output_off", AsyncMock(return_value=False))
    with pytest.raises(SafetyShutdownUnverifiedError, match="global OFF could not be verified"):
        await manager.stop()
    await asyncio.sleep(0)
    assert settlement_sources.count("safety_collect") == 1
    assert settlement_sources.count("safety_shutdown") == 1
    assert collect_task in manager._consumed_child_tasks

    monkeypatch.setattr(manager, "_ensure_output_off", AsyncMock(return_value=True))
    await manager.stop()
    assert manager._consumed_child_tasks == set()


async def test_failed_stop_preserves_child_consumed_under_stop_cut_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child_release = asyncio.Event()
    monitor_release = asyncio.Event()
    off_entered = asyncio.Event()
    off_release = asyncio.Event()
    settlement_sources: list[str] = []

    async def terminal_child() -> None:
        await child_release.wait()

    async def live_monitor() -> None:
        await monitor_release.wait()

    async def blocked_unverified_off() -> bool:
        off_entered.set()
        await off_release.wait()
        return False

    async def record_settlement(
        _reason: str,
        *,
        channel: str = "",
        value: float = 0.0,
        source: str = "safety_manager",
    ) -> None:
        del channel, value
        settlement_sources.append(source)

    manager = _manager(mock=True)
    monkeypatch.setattr(manager, "_collect_loop", terminal_child)
    monkeypatch.setattr(manager, "_monitor_loop", live_monitor)
    monkeypatch.setattr(manager, "_settle_latched_fault", record_settlement)
    monkeypatch.setattr(manager, "_ensure_output_off", blocked_unverified_off)
    await manager.start()

    stopping = asyncio.create_task(manager.stop())
    await off_entered.wait()
    child_release.set()
    assert manager._collect_task is not None
    await manager._collect_task
    await asyncio.sleep(0)
    assert settlement_sources == ["safety_collect"]

    off_release.set()
    with pytest.raises(SafetyShutdownUnverifiedError, match="global OFF could not be verified"):
        await stopping
    await asyncio.sleep(0)
    assert settlement_sources.count("safety_collect") == 1
    assert settlement_sources.count("safety_shutdown") == 1

    monkeypatch.setattr(manager, "_ensure_output_off", AsyncMock(return_value=True))
    await manager.stop()
    assert manager._consumed_child_tasks == set()


async def test_stop_latches_fault_when_target_off_succeeds_but_global_proof_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    children_release = asyncio.Event()

    async def live_child() -> None:
        await children_release.wait()

    driver = MagicMock()
    driver.stop_source = AsyncMock(return_value=True)
    driver.emergency_off = AsyncMock(return_value=SourceOffResult.PHYSICAL_STATE_UNKNOWN)
    manager = _manager(mock=True, driver=driver)
    fault_log = AsyncMock()
    manager._fault_log_callback = fault_log
    manager._publish_keithley_channel_states = AsyncMock()  # type: ignore[method-assign]
    monkeypatch.setattr(manager, "_collect_loop", live_child)
    monkeypatch.setattr(manager, "_monitor_loop", live_child)
    await manager.start()
    manager._state = SafetyState.RUNNING
    manager._active_sources.add("smua")

    with pytest.raises(SafetyShutdownUnverifiedError, match="global OFF could not be verified"):
        await manager.stop()

    cut = manager.snapshot_operator_safety()
    assert manager._active_sources == set()
    assert manager.state is SafetyState.FAULT_LATCHED
    assert manager.fault_reason == "SafetyManager shutdown HOLD: global OFF could not be verified"
    assert cut.lifecycle is SafetyLifecycle.FAULT_LATCHED
    assert cut.verified_off is False
    assert manager._collect_task is not None and not manager._collect_task.done()
    assert manager._monitor_task is not None and not manager._monitor_task.done()

    for _ in range(100):
        if not manager._pending_child_fault_settlements:
            break
        await asyncio.sleep(0)
    assert manager._pending_child_fault_settlements == set()
    fault_log.assert_awaited_once()
    assert fault_log.await_args.kwargs["source"] == "safety_shutdown"

    driver.emergency_off = AsyncMock(return_value=SourceOffResult.DEVICE_REPORTED_OFF)
    await manager.stop()
    assert manager._collect_task is None
    assert manager._monitor_task is None


@pytest.mark.parametrize(
    ("channel", "expected_calls", "expected_applied", "expected_active"),
    [
        (None, ["smua", "smub"], ["smua", "smub"], []),
        ("smua", ["smua"], ["smua"], ["smub"]),
    ],
)
async def test_child_death_during_stop_preserves_fault_and_reports_direct_off_truth(
    monkeypatch: pytest.MonkeyPatch,
    channel: str | None,
    expected_calls: list[str],
    expected_applied: list[str],
    expected_active: list[str],
) -> None:
    child_release = asyncio.Event()
    monitor_release = asyncio.Event()
    stop_entered = asyncio.Event()
    stop_release = asyncio.Event()
    global_entered = asyncio.Event()
    global_release = asyncio.Event()
    stop_calls: list[str] = []

    async def terminal_child() -> None:
        await child_release.wait()

    async def live_monitor() -> None:
        await monitor_release.wait()

    async def stop_source(smu_channel: str) -> None:
        stop_calls.append(smu_channel)
        if len(stop_calls) == 1:
            stop_entered.set()
            await stop_release.wait()

    async def blocked_global_off(*_args: object) -> SourceOffResult:
        global_entered.set()
        await global_release.wait()
        return SourceOffResult.DEVICE_REPORTED_OFF

    driver = MagicMock()
    driver.stop_source = AsyncMock(side_effect=stop_source)
    driver.emergency_off = AsyncMock(side_effect=blocked_global_off)
    manager = _manager(mock=True, driver=driver)
    manager._publish_keithley_channel_states = AsyncMock()  # type: ignore[method-assign]
    monkeypatch.setattr(manager, "_collect_loop", terminal_child)
    monkeypatch.setattr(manager, "_monitor_loop", live_monitor)
    await manager.start()
    manager._state = SafetyState.RUNNING
    manager._active_sources.update({"smua", "smub"})

    stopping = asyncio.create_task(manager.request_stop(channel=channel))
    await stop_entered.wait()
    child_release.set()
    assert manager._collect_task is not None
    await manager._collect_task
    await global_entered.wait()
    stop_release.set()
    result = await stopping

    assert result["ok"] is False
    assert result["state"] == SafetyState.FAULT_LATCHED.value
    assert result["applied_off_channels"] == expected_applied
    assert result["active_channels"] == expected_active
    assert stop_calls == expected_calls
    events = manager.get_events()
    fault_index = next(i for i, event in enumerate(events) if event.to_state is SafetyState.FAULT_LATCHED)
    assert all(event.to_state not in {SafetyState.RUNNING, SafetyState.SAFE_OFF} for event in events[fault_index + 1 :])

    global_release.set()
    for _ in range(100):
        if not manager._pending_child_fault_settlements:
            break
        await asyncio.sleep(0)
    assert manager._pending_child_fault_settlements == set()
    assert manager._active_sources == set()


async def test_cancelled_limit_write_settles_hardware_then_faults_before_return() -> None:
    write_entered = asyncio.Event()
    write_release = asyncio.Event()
    writes: list[str] = []

    async def blocked_write(
        channel: str,
        *,
        v_comp: float | None = None,
        i_comp: float | None = None,
    ) -> None:
        command = f"{channel}.source.limitv = {v_comp}" if v_comp is not None else f"{channel}.source.limiti = {i_comp}"
        writes.append(command)
        write_entered.set()
        await write_release.wait()

    runtime = MagicMock(active=True, p_target=0.5, v_comp=10.0, i_comp=0.1)
    driver = MagicMock()
    driver.mock = False
    driver._channels = {"smua": runtime}
    driver.update_source_limit = AsyncMock(side_effect=blocked_write)
    driver.emergency_off = AsyncMock(return_value=SourceOffResult.DEVICE_REPORTED_OFF)
    manager = _manager(mock=True, driver=driver)
    manager._publish_keithley_channel_states = AsyncMock()  # type: ignore[method-assign]
    await manager.start()
    manager._state = SafetyState.RUNNING
    manager._active_sources.add("smua")

    update = asyncio.create_task(manager.update_limits(channel="smua", v_comp=20.0, i_comp=0.2))
    await write_entered.wait()
    update.cancel()
    await asyncio.sleep(0)
    assert not update.done()
    write_release.set()
    with pytest.raises(asyncio.CancelledError):
        await update

    assert writes == ["smua.source.limitv = 20.0"]
    assert runtime.v_comp == 20.0
    assert runtime.i_comp == 0.1
    assert manager.state is SafetyState.FAULT_LATCHED
    assert manager._active_sources == set()
    driver.emergency_off.assert_awaited()


async def test_limit_write_transport_loss_demotes_driver_and_blocks_further_ordinary_traffic() -> None:
    resource = "USB0::0x05E6::0x2604::04089762::INSTR"
    identity = "Keithley Instruments Inc., Model 2604B, 04089762, 4.0.8"
    off_nonce = re.compile(r"CRYODAQ_OFF_V1\|([0-9a-f]{32})\|%g")
    output_state = {"smua": 0, "smub": 0}

    def _apply_output_write(command: str) -> None:
        if ".source.output =" not in command:
            return
        channel = "smua" if command.startswith("smua.") else "smub"
        output_state[channel] = 1 if command.endswith(".OUTPUT_ON") else 0

    def _query(command: str, timeout_ms: int | None = None) -> str:
        del timeout_ms
        if command == "*IDN?":
            return identity
        match = off_nonce.search(command)
        if match is not None:
            channel = "smua" if "smua.source.output" in command else "smub"
            return f"CRYODAQ_OFF_V1|{match.group(1)}|{output_state[channel]}"
        for channel in output_state:
            if command == f"print({channel}.source.output)":
                return str(output_state[channel])
        return "0"

    driver = Keithley2604B("k", resource, mock=False)
    transport = MagicMock()
    transport.open = AsyncMock()
    transport.close = AsyncMock()
    transport.query = AsyncMock(side_effect=_query)
    transport.write = AsyncMock(side_effect=_apply_output_write)
    driver._transport = transport
    await driver.connect()
    await driver.start_source("smua", 0.5, 40.0, 1.0)

    writes: list[str] = []

    async def _fail_limit_only(command: str) -> None:
        writes.append(command)
        if command == "smua.source.limitv = 20.0":
            raise OSError("ambiguous limit completion")
        _apply_output_write(command)

    transport.write = AsyncMock(side_effect=_fail_limit_only)
    queries_before = transport.query.await_count
    manager = _manager(mock=True, driver=driver)
    manager._publish_keithley_channel_states = AsyncMock()  # type: ignore[method-assign]
    await manager.start()
    manager._state = SafetyState.RUNNING
    manager._active_sources.add("smua")

    result = await manager.update_limits(channel="smua", v_comp=20.0, i_comp=0.2)

    assert result["ok"] is False
    assert result["uncertain"] == ["v_comp"]
    assert driver.connected is False
    assert driver._recovery_transport_open is True
    assert driver._instrument_id == ""
    assert manager.state is SafetyState.FAULT_LATCHED
    assert writes[0] == "smua.source.limitv = 20.0"
    assert all(
        command.endswith(".source.levelv = 0") or ".source.output = " in command and command.endswith(".OUTPUT_OFF")
        for command in writes[1:]
    )
    assert not any("OUTPUT_ON" in command or ".source.limiti" in command for command in writes)
    recovery_queries = [call.args[0] for call in transport.query.await_args_list[queries_before:]]
    assert recovery_queries
    assert all("CRYODAQ_OFF_V1" in command for command in recovery_queries)

    writes_after_fault = list(writes)
    query_count_after_fault = transport.query.await_count
    blocked = await manager.update_limits(channel="smua", i_comp=0.2)
    assert blocked["ok"] is False
    assert writes == writes_after_fault
    assert transport.query.await_count == query_count_after_fault
    await manager.stop()
    await driver.disconnect()


async def test_second_limit_write_error_reports_partial_truth_and_faults() -> None:
    writes: list[str] = []

    async def write(
        channel: str,
        *,
        v_comp: float | None = None,
        i_comp: float | None = None,
    ) -> None:
        command = f"{channel}.source.limitv = {v_comp}" if v_comp is not None else f"{channel}.source.limiti = {i_comp}"
        writes.append(command)
        if ".source.limiti" in command:
            raise OSError("ambiguous transport failure")

    runtime = MagicMock(active=True, p_target=0.5, v_comp=10.0, i_comp=0.1)
    driver = MagicMock()
    driver.mock = False
    driver._channels = {"smua": runtime}
    driver.update_source_limit = AsyncMock(side_effect=write)
    driver.emergency_off = AsyncMock(return_value=SourceOffResult.DEVICE_REPORTED_OFF)
    manager = _manager(mock=True, driver=driver)
    manager._publish_keithley_channel_states = AsyncMock()  # type: ignore[method-assign]
    await manager.start()
    manager._state = SafetyState.RUNNING
    manager._active_sources.add("smua")

    result = await manager.update_limits(channel="smua", v_comp=20.0, i_comp=0.2)

    assert result["ok"] is False
    assert result["applied"] == {"v_comp": 20.0}
    assert result["uncertain"] == ["i_comp"]
    assert writes == ["smua.source.limitv = 20.0", "smua.source.limiti = 0.2"]
    assert runtime.v_comp == 20.0
    assert runtime.i_comp == 0.1
    assert manager.state is SafetyState.FAULT_LATCHED
    assert manager._active_sources == set()
