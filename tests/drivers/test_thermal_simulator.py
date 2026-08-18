"""Integration checks for the external thermal mock instrument."""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

import cryodaq.engine as engine_module
from cryodaq.analytics.plugin_loader import PluginPipeline
from cryodaq.core.broker import DataBroker
from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager
from cryodaq.core.scheduler import InstrumentConfig, Scheduler
from cryodaq.drivers.base import Reading
from cryodaq.drivers.instruments.keithley_2604b import Keithley2604B
from cryodaq.drivers.instruments.lakeshore_218s import LakeShore218S
from cryodaq.drivers.registry import (
    DriverConstructionContext,
    DriverRegistryError,
    construct_driver,
    runtime_binding_for_driver,
    validate_instrument_entry,
)
from cryodaq.drivers.transport.mock_instrument import (
    ExternalMockInstrumentClient,
    MockInstrumentEndpoint,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def external_simulator(tmp_path: Path) -> Iterator[ExternalMockInstrumentClient]:
    ready_path = tmp_path / "ready.json"
    truth_path = tmp_path / "truth.json"
    process = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "tools/thermal_conductivity_simulator.py"),
            "--ready-file",
            str(ready_path),
            "--truth-output",
            str(truth_path),
            "--time-constant-s",
            "0.02",
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 5.0
    while not ready_path.is_file() and process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    if not ready_path.is_file():
        stdout, stderr = process.communicate(timeout=2.0)
        pytest.fail(f"external simulator did not become ready; stdout={stdout!r}; stderr={stderr!r}")

    ready = json.loads(ready_path.read_text(encoding="utf-8"))
    endpoint = MockInstrumentEndpoint(host=ready["host"], port=ready["port"])
    client = ExternalMockInstrumentClient(endpoint, timeout_s=1.0)
    yield client

    if process.poll() is None:
        with socket.create_connection((endpoint.host, endpoint.port), timeout=1.0) as connection:
            connection.sendall(b"MOCK:SHUTDOWN\n")
            assert connection.makefile("rb").readline() == b"OK\n"
    process.wait(timeout=5.0)
    stdout, stderr = process.communicate()
    assert process.returncode == 0, f"stdout={stdout!r}; stderr={stderr!r}"
    assert truth_path.is_file()
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    assert truth["model"] == "nonlinear_thermal_link_v1"


def _lakeshore_config():
    return validate_instrument_entry(
        {
            "type": "lakeshore_218s",
            "name": "LS218_1",
            "resource": "GPIB0::12::INSTR",
            "poll_interval_s": 0.01,
            "channels": {1: "Т1 Криостат верх", 7: "Т7 Детектор"},
        }
    )


def _keithley_config():
    return validate_instrument_entry(
        {
            "type": "keithley_2604b",
            "name": "Keithley_1",
            "resource": "USB0::0x05E6::0x2604::MOCK00001::INSTR",
            "poll_interval_s": 0.01,
        }
    )


async def _wait_for_reading(
    queue: asyncio.Queue[Reading],
    *,
    channel: str,
    predicate: Callable[[Reading], bool],
    not_before: datetime | None = None,
) -> Reading:
    deadline = time.monotonic() + 2.0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0.0:
            pytest.fail(f"no acceptable reading for {channel!r}")
        reading = await asyncio.wait_for(queue.get(), timeout=remaining)
        if (
            reading.channel == channel
            and (not_before is None or reading.timestamp >= not_before)
            and predicate(reading)
        ):
            return reading


async def _wait_for_truth_point(
    client: ExternalMockInstrumentClient,
    *,
    prior_count: int,
    requested_power_w: float,
    timeout_s: float = 2.0,
) -> dict[str, float]:
    deadline = time.monotonic() + timeout_s
    while True:
        truth = json.loads(await client.query("MOCK:TRUTH?"))
        points = truth["commanded_points"]
        if len(points) > prior_count:
            assert len(points) == prior_count + 1
            point = points[prior_count]
            assert point["power_w"] == pytest.approx(requested_power_w)
            return point
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"external simulator did not append requested power {requested_power_w} after point {prior_count}"
            )
        await asyncio.sleep(0.01)


class _AcceptingWriter:
    is_disk_full = False

    async def write_immediate(self, readings: list[Reading]) -> bool:
        assert readings
        return True


async def test_external_process_reaches_published_thermal_calculator_result(
    external_simulator: ExternalMockInstrumentClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = DriverConstructionContext(mock=True, mock_instrument_client=external_simulator)
    lakeshore = construct_driver(_lakeshore_config(), context)
    keithley = construct_driver(_keithley_config(), context)
    assert isinstance(lakeshore, LakeShore218S)
    assert isinstance(keithley, Keithley2604B)

    broker = DataBroker()
    raw_queue = await broker.subscribe(
        "thermal_simulator_raw",
        filter_fn=lambda reading: not reading.channel.startswith("analytics/"),
    )
    result_queue = await broker.subscribe(
        "thermal_simulator_result",
        filter_fn=lambda reading: reading.channel == "analytics/thermal_calculator/R_thermal",
    )
    pipeline = PluginPipeline(broker, ROOT / "plugins", batch_interval_s=0.01)
    safety_broker = SafetyBroker()
    binding = runtime_binding_for_driver(keithley)
    assert binding is not None
    safety_manager = SafetyManager(
        safety_broker,
        keithley_driver=keithley,
        reviewed_source_runtime_binding=binding,
        data_broker=broker,
        mock=True,
    )
    scheduler = Scheduler(
        broker,
        safety_broker=safety_broker,
        sqlite_writer=_AcceptingWriter(),
        reviewed_source_connect_begin=safety_manager.begin_reviewed_source_connect,
        reviewed_source_connect_complete=safety_manager.complete_reviewed_source_connect,
        reviewed_source_uncertain=safety_manager.mark_reviewed_source_uncertain,
        reviewed_source_connect_abandon=safety_manager.abandon_reviewed_source_connect,
        reviewed_source_disconnect=safety_manager.disconnect_reviewed_source,
    )
    scheduler.add(InstrumentConfig(driver=lakeshore))
    scheduler.add(InstrumentConfig(driver=keithley))

    await safety_manager.start()
    await pipeline.start()
    await scheduler.start()
    try:
        baseline_hot = await _wait_for_reading(
            raw_queue,
            channel="Т1 Криостат верх",
            predicate=lambda reading: reading.value == pytest.approx(4.2),
        )
        await _wait_for_reading(
            raw_queue,
            channel="Т7 Детектор",
            predicate=lambda reading: reading.value == pytest.approx(4.2),
        )
        assert baseline_hot.raw == pytest.approx(4.2)
        await _wait_for_reading(
            raw_queue,
            channel="Keithley_1/smua/power",
            predicate=lambda reading: reading.value == pytest.approx(0.0),
        )

        for power_w in (0.2, 0.35):
            truth_before = json.loads(await external_simulator.query("MOCK:TRUTH?"))
            prior_count = len(truth_before["commanded_points"])
            if power_w == 0.35:
                real_set_power = external_simulator.set_power

                async def skip_second_power(_power_w: float) -> None:
                    return None

                monkeypatch.setattr(external_simulator, "set_power", skip_second_power)
                skipped_result = await safety_manager.update_target(power_w, channel="smua")
                assert skipped_result["ok"] is True, skipped_result
                with pytest.raises(AssertionError, match="did not append requested power"):
                    await _wait_for_truth_point(
                        external_simulator,
                        prior_count=prior_count,
                        requested_power_w=power_w,
                        timeout_s=0.1,
                    )
                monkeypatch.setattr(external_simulator, "set_power", real_set_power)

            command_cut = datetime.now(UTC)
            if power_w == 0.2:
                result = await safety_manager.request_run(power_w, 10.0, 0.5, channel="smua")
            else:
                result = await safety_manager.update_target(power_w, channel="smua")
            assert result["ok"] is True, result
            expected = await _wait_for_truth_point(
                external_simulator,
                prior_count=prior_count,
                requested_power_w=power_w,
            )
            power_reading = await _wait_for_reading(
                raw_queue,
                channel="Keithley_1/smua/power",
                not_before=command_cut,
                predicate=lambda reading: reading.value == pytest.approx(power_w, rel=0.01),
            )
            expected_r_thermal = 1.0 / expected["expected_g_w_per_k"]
            product_result = await _wait_for_reading(
                result_queue,
                channel="analytics/thermal_calculator/R_thermal",
                not_before=power_reading.timestamp,
                predicate=lambda reading: (
                    reading.value == pytest.approx(expected_r_thermal, rel=0.02)
                    and reading.metadata["P"] == pytest.approx(power_w, rel=0.01)
                ),
            )
            assert expected["power_w"] == pytest.approx(power_w)
            assert product_result.unit == "K/W"
            assert product_result.metadata["source"] == "analytics"
            assert product_result.metadata["plugin_id"] == "thermal_calculator"
            assert product_result.metadata["hot_sensor"] == "Т1 Криостат верх"
            assert product_result.metadata["cold_sensor"] == "Т7 Детектор"
            assert product_result.metadata["heater_channel"] == "Keithley_1/smua/power"

        stop_result = await safety_manager.emergency_off(channel="smua")
        assert stop_result["ok"] is True
        truth = json.loads(await external_simulator.query("MOCK:TRUTH?"))
        assert truth["commanded_points"][-1]["power_w"] == 0.0
    finally:
        await scheduler.stop()
        await pipeline.stop()
        await safety_manager.stop()
        await broker.unsubscribe("thermal_simulator_raw")
        await broker.unsubscribe("thermal_simulator_result")


def test_engine_main_forwards_exact_external_simulator_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}
    sentinel_client = object()

    def construct_client(endpoint: MockInstrumentEndpoint) -> object:
        observed["endpoint"] = endpoint
        return sentinel_client

    async def record_run_engine(**kwargs: object) -> None:
        observed.update(kwargs)

    monkeypatch.delenv("CRYODAQ_MOCK", raising=False)
    monkeypatch.setattr(
        engine_module.sys,
        "argv",
        ["cryodaq-engine", "--mock", "--mock-thermal-simulator", "127.0.0.1:43123"],
    )
    monkeypatch.setattr(
        engine_module,
        "_consume_engine_launch_authority",
        lambda: ("a" * 32, "b" * 64, "c" * 64, 71),
    )
    monkeypatch.setattr(engine_module, "ExternalMockInstrumentClient", construct_client)
    monkeypatch.setattr(engine_module, "_acquire_engine_lock", lambda: 42)
    monkeypatch.setattr(engine_module, "_release_engine_lock", lambda _fd: None)
    monkeypatch.setattr(engine_module, "_run_engine", record_run_engine)
    monkeypatch.setattr("cryodaq.logging_setup.setup_logging", lambda *_args, **_kwargs: None)

    engine_module.main()

    assert observed["endpoint"] == MockInstrumentEndpoint("127.0.0.1", 43123)
    assert observed["mock"] is True
    assert observed["mock_instrument_client"] is sentinel_client
    assert observed["engine_instance_id"] == "a" * 32
    assert observed["shutdown_capability"] == "b" * 64
    assert observed["engine_ready_nonce"] == "c" * 64
    assert observed["engine_ready_channel_fd"] == 71


def test_engine_cli_rejects_external_simulator_without_mock(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("CRYODAQ_MOCK", raising=False)
    monkeypatch.setattr(
        engine_module,
        "_consume_engine_launch_authority",
        lambda: ("", "", "", None),
    )
    monkeypatch.setattr(
        engine_module.sys,
        "argv",
        ["cryodaq-engine", "--mock-thermal-simulator", "127.0.0.1:1234"],
    )
    with pytest.raises(SystemExit) as raised:
        engine_module.main()
    assert raised.value.code == 2
    assert "requires mock mode" in capsys.readouterr().err


def test_external_simulator_is_loopback_only_and_mock_only(
    external_simulator: ExternalMockInstrumentClient,
) -> None:
    assert MockInstrumentEndpoint.parse("127.0.0.1:1234") == MockInstrumentEndpoint("127.0.0.1", 1234)
    for host in ("localhost", "192.0.2.1"):
        with pytest.raises(ValueError, match="literal address"):
            MockInstrumentEndpoint.parse(f"{host}:1234")
    with pytest.raises(DriverRegistryError, match="only in mock mode"):
        DriverConstructionContext(mock=False, mock_instrument_client=external_simulator)


def test_direct_mock_endpoint_construction_enforces_loopback_and_port_bounds() -> None:
    assert MockInstrumentEndpoint("127.0.0.1", 65535) == MockInstrumentEndpoint.parse("127.0.0.1:65535")
    for host in ("localhost", "192.0.2.1"):
        with pytest.raises(ValueError, match="literal address"):
            MockInstrumentEndpoint(host, 1234)
    for invalid_port in (0, 65536, -1, True, 1.5, "1234"):
        with pytest.raises(ValueError, match="port"):
            MockInstrumentEndpoint("127.0.0.1", invalid_port)  # type: ignore[arg-type]


class _InitialZeroRetryClient(ExternalMockInstrumentClient):
    def __init__(self, mode: str) -> None:
        super().__init__(MockInstrumentEndpoint("127.0.0.1", 1))
        self.mode = mode
        self.attempted: list[float] = []
        self.applied: list[float] = []
        self.cleanup_entered = asyncio.Event()
        self.release_cleanup = asyncio.Event()

    async def set_power(self, power_w: float) -> None:
        self.attempted.append(power_w)
        if len(self.attempted) == 1:
            if self.mode == "cancel":
                raise asyncio.CancelledError
            raise RuntimeError("external zero unavailable before apply")
        if len(self.attempted) == 2:
            self.cleanup_entered.set()
            await self.release_cleanup.wait()
        self.applied.append(power_w)


@pytest.mark.parametrize("mode", ["fail_before", "cancel"])
async def test_scheduler_retries_after_initial_external_zero_connect_failure(mode: str) -> None:
    client = _InitialZeroRetryClient(mode)
    context = DriverConstructionContext(mock=True, mock_instrument_client=client)
    driver = construct_driver(_keithley_config(), context)
    assert isinstance(driver, Keithley2604B)
    binding = runtime_binding_for_driver(driver)
    assert binding is not None

    broker = DataBroker()
    power_queue = await broker.subscribe(
        "initial_zero_retry_power",
        filter_fn=lambda reading: reading.channel == "Keithley_1/smua/power",
    )
    safety_broker = SafetyBroker()
    manager = SafetyManager(
        safety_broker,
        keithley_driver=driver,
        reviewed_source_runtime_binding=binding,
        data_broker=broker,
        mock=True,
    )
    scheduler = Scheduler(
        broker,
        safety_broker=safety_broker,
        sqlite_writer=_AcceptingWriter(),
        reviewed_source_connect_begin=manager.begin_reviewed_source_connect,
        reviewed_source_connect_complete=manager.complete_reviewed_source_connect,
        reviewed_source_uncertain=manager.mark_reviewed_source_uncertain,
        reviewed_source_connect_abandon=manager.abandon_reviewed_source_connect,
        reviewed_source_disconnect=manager.disconnect_reviewed_source,
    )
    scheduler.add(InstrumentConfig(driver=driver))
    scheduler._instruments[driver.name].backoff_s = 0.01

    await manager.start()
    await scheduler.start()
    try:
        await asyncio.wait_for(client.cleanup_entered.wait(), timeout=2.0)
        assert client.attempted == [0.0, 0.0]
        assert client.applied == []
        assert driver.connected is False
        assert driver._connect_in_progress is False

        client.release_cleanup.set()
        power = await _wait_for_reading(
            power_queue,
            channel="Keithley_1/smua/power",
            predicate=lambda reading: reading.value == pytest.approx(0.0),
        )
        assert power.instrument_id
        assert client.attempted[:3] == [0.0, 0.0, 0.0]
        assert client.applied[:2] == [0.0, 0.0]
        assert driver.connected is True
        assert driver._connect_in_progress is False
        assert driver.output_state_unverified is False
        assert manager._reviewed_source_off_evidence.verified_off is True
        state = scheduler._instruments[driver.name]
        assert state.reviewed_source_attempt is None
        assert state.reviewed_source_disconnect_required is False
    finally:
        client.release_cleanup.set()
        await scheduler.stop()
        await manager.stop()
        await broker.unsubscribe("initial_zero_retry_power")


class _StartAckLossClient(ExternalMockInstrumentClient):
    def __init__(self) -> None:
        super().__init__(MockInstrumentEndpoint("127.0.0.1", 1))
        self.applied: list[float] = []
        self._lose_positive_ack = True

    async def set_power(self, power_w: float) -> None:
        self.applied.append(power_w)
        if power_w > 0.0 and self._lose_positive_ack:
            self._lose_positive_ack = False
            raise RuntimeError("reply lost after remote start apply")


async def test_failed_start_lost_ack_reconciles_external_zero() -> None:
    client = _StartAckLossClient()
    driver = Keithley2604B("K", "USB::MOCK", mock=True, mock_instrument_client=client)
    await driver.connect()

    with pytest.raises(RuntimeError, match="reply lost after remote start apply"):
        await driver.start_source("smua", 0.2, 10.0, 0.5)

    runtime = driver._channels["smua"]
    assert runtime.active is False
    assert runtime.p_target == 0.0
    assert client.applied[-2:] == [0.2, 0.0]


class _TargetOutcomeClient(ExternalMockInstrumentClient):
    def __init__(self, mode: str) -> None:
        super().__init__(MockInstrumentEndpoint("127.0.0.1", 1))
        self.mode = mode
        self.applied: list[float] = []
        self.target_entered = asyncio.Event()
        self.release_target = asyncio.Event()

    async def set_power(self, power_w: float) -> None:
        if power_w != pytest.approx(0.35):
            self.applied.append(power_w)
            return
        self.target_entered.set()
        if self.mode == "fail_before":
            raise RuntimeError("failed before remote apply")
        self.applied.append(power_w)
        if self.mode == "fail_after":
            raise RuntimeError("reply lost after remote apply")
        if self.mode == "block_after":
            await self.release_target.wait()


class _AlreadyLatchedTargetFailureClient(ExternalMockInstrumentClient):
    def __init__(self) -> None:
        super().__init__(MockInstrumentEndpoint("127.0.0.1", 1))
        self.applied: list[float] = []
        self.target_entered = asyncio.Event()
        self.release_target = asyncio.Event()
        self.target_failed = asyncio.Event()
        self.off_entered = asyncio.Event()
        self.release_off = asyncio.Event()
        self._armed = False

    def arm(self) -> None:
        self._armed = True

    async def set_power(self, power_w: float) -> None:
        if not self._armed:
            self.applied.append(power_w)
            return
        if power_w == pytest.approx(0.35):
            self.applied.append(power_w)
            self.target_entered.set()
            await self.release_target.wait()
            self.target_failed.set()
            raise RuntimeError("reply lost after remote target apply")
        if power_w == pytest.approx(0.0):
            self.off_entered.set()
            await self.release_off.wait()
            self.applied.append(power_w)
            return
        self.applied.append(power_w)


async def _running_external_safety_manager(
    client: ExternalMockInstrumentClient,
) -> tuple[SafetyManager, Keithley2604B]:
    context = DriverConstructionContext(mock=True, mock_instrument_client=client)
    driver = construct_driver(_keithley_config(), context)
    assert isinstance(driver, Keithley2604B)
    binding = runtime_binding_for_driver(driver)
    assert binding is not None
    manager = SafetyManager(
        SafetyBroker(),
        keithley_driver=driver,
        reviewed_source_runtime_binding=binding,
        mock=True,
    )
    await driver.connect()
    await manager.start()
    result = await manager.request_run(0.2, 10.0, 0.5, channel="smua")
    assert result["ok"] is True, result
    return manager, driver


@pytest.mark.parametrize("mode", ["fail_before", "fail_after"])
async def test_target_update_failure_forces_external_zero_and_latches_fault(mode: str) -> None:
    client = _TargetOutcomeClient(mode)
    manager, driver = await _running_external_safety_manager(client)
    try:
        result = await manager.update_target(0.35, channel="smua")
        runtime = driver._channels["smua"]
        assert result["ok"] is False
        assert result["uncertain"] == ["p_target"]
        assert manager.state.value == "fault_latched"
        assert manager._active_sources == set()
        assert runtime.active is False
        assert runtime.p_target == 0.0
        assert client.applied[-1] == 0.0
    finally:
        await manager.stop()


async def test_failed_target_update_waits_for_already_latched_external_off() -> None:
    client = _AlreadyLatchedTargetFailureClient()
    manager, driver = await _running_external_safety_manager(client)
    client.arm()
    update_task: asyncio.Task[dict[str, object]] | None = None
    fault_task: asyncio.Task[None] | None = None
    try:
        update_task = asyncio.create_task(manager.update_target(0.35, channel="smua"))
        await asyncio.wait_for(client.target_entered.wait(), timeout=1.0)
        fault_latched = asyncio.Event()
        begin_fault_latch = manager._begin_fault_latch

        def observe_fault_latch(*args: object, **kwargs: object) -> bool:
            latched = begin_fault_latch(*args, **kwargs)  # type: ignore[arg-type]
            fault_latched.set()
            return latched

        manager._begin_fault_latch = observe_fault_latch  # type: ignore[method-assign]
        fault_task = asyncio.create_task(manager._fault("concurrent fault", source="test"))
        await asyncio.wait_for(fault_latched.wait(), timeout=1.0)
        assert manager.state.value == "fault_latched"
        client.release_target.set()
        await asyncio.wait_for(client.target_failed.wait(), timeout=1.0)
        await asyncio.wait_for(client.off_entered.wait(), timeout=1.0)
        await asyncio.sleep(0)
        assert not update_task.done()

        client.release_off.set()
        result = await update_task
        await fault_task
        runtime = driver._channels["smua"]
        assert result["ok"] is False
        assert result["uncertain"] == ["p_target"]
        assert manager.state.value == "fault_latched"
        assert manager._active_sources == set()
        assert runtime.active is False
        assert runtime.p_target == 0.0
        assert client.applied[-2:] == [0.35, 0.0]
    finally:
        client.release_target.set()
        client.release_off.set()
        if update_task is not None and not update_task.done():
            await update_task
        if fault_task is not None and not fault_task.done():
            await fault_task
        await manager.stop()


async def test_cancelled_target_update_settles_external_zero_before_cancellation() -> None:
    client = _TargetOutcomeClient("block_after")
    manager, driver = await _running_external_safety_manager(client)
    try:
        update_task = asyncio.create_task(manager.update_target(0.35, channel="smua"))
        await asyncio.wait_for(client.target_entered.wait(), timeout=1.0)
        update_task.cancel()
        client.release_target.set()
        with pytest.raises(asyncio.CancelledError):
            await update_task
        runtime = driver._channels["smua"]
        assert manager.state.value == "fault_latched"
        assert manager._active_sources == set()
        assert runtime.active is False
        assert runtime.p_target == 0.0
        assert client.applied[-2:] == [0.35, 0.0]
    finally:
        await manager.stop()


async def test_target_update_cannot_report_success_after_emergency_off_authority() -> None:
    client = _TargetOutcomeClient("block_after")
    manager, driver = await _running_external_safety_manager(client)
    try:
        update_task = asyncio.create_task(manager.update_target(0.35, channel="smua"))
        await asyncio.wait_for(client.target_entered.wait(), timeout=1.0)
        abort_registered = asyncio.Event()
        register_abort_intent = manager._register_abort_intent

        def observe_abort_intent(*, full: bool) -> int:
            generation = register_abort_intent(full=full)
            abort_registered.set()
            return generation

        manager._register_abort_intent = observe_abort_intent  # type: ignore[method-assign]
        off_task = asyncio.create_task(manager.emergency_off(channel="smua"))
        await asyncio.wait_for(abort_registered.wait(), timeout=1.0)
        client.release_target.set()
        update_result, off_result = await asyncio.gather(update_task, off_task)
        runtime = driver._channels["smua"]
        assert update_result["ok"] is False
        assert "authority was lost" in update_result["error"]
        assert off_result["ok"] is True
        assert manager.state.value == "safe_off"
        assert manager._active_sources == set()
        assert runtime.active is False
        assert runtime.p_target == 0.0
        assert 0.35 in client.applied
        assert client.applied[-1] == 0.0
    finally:
        await manager.stop()


class _DelayedPowerClient(ExternalMockInstrumentClient):
    def __init__(self) -> None:
        super().__init__(MockInstrumentEndpoint("127.0.0.1", 1))
        self.applied: list[float] = []
        self.nonzero_started = asyncio.Event()
        self.release_nonzero = asyncio.Event()
        self._block_next_nonzero = False

    def arm(self) -> None:
        self.nonzero_started.clear()
        self.release_nonzero.clear()
        self._block_next_nonzero = True

    async def set_power(self, power_w: float) -> None:
        if power_w > 0.0 and self._block_next_nonzero:
            self._block_next_nonzero = False
            self.nonzero_started.set()
            await self.release_nonzero.wait()
        self.applied.append(power_w)


def _observe_mock_off_commit(driver: Keithley2604B) -> asyncio.Event:
    committed = asyncio.Event()
    original = driver._mark_channel_off_verified

    def observed(*args, **kwargs):
        result = original(*args, **kwargs)
        if result:
            committed.set()
        return result

    driver._mark_channel_off_verified = observed  # type: ignore[method-assign]
    return committed


async def test_delayed_mock_start_cannot_reheat_external_plant_after_stop() -> None:
    client = _DelayedPowerClient()
    driver = Keithley2604B("K", "USB::MOCK", mock=True, mock_instrument_client=client)
    await driver.connect()
    client.arm()

    start_task = asyncio.create_task(driver.start_source("smua", 0.2, 10.0, 0.5))
    await asyncio.wait_for(client.nonzero_started.wait(), timeout=1.0)
    off_committed = _observe_mock_off_commit(driver)
    stop_task = asyncio.create_task(driver.stop_source("smua"))
    await asyncio.wait_for(off_committed.wait(), timeout=1.0)
    assert driver._channels["smua"].active is False
    client.release_nonzero.set()
    start_result, stop_result = await asyncio.gather(start_task, stop_task, return_exceptions=True)

    assert isinstance(start_result, RuntimeError)
    assert stop_result is None
    assert 0.2 in client.applied
    assert client.applied[-1] == 0.0


async def test_delayed_mock_update_cannot_reheat_external_plant_after_stop() -> None:
    client = _DelayedPowerClient()
    driver = Keithley2604B("K", "USB::MOCK", mock=True, mock_instrument_client=client)
    await driver.connect()
    await driver.start_source("smua", 0.1, 10.0, 0.5)
    client.arm()

    update_task = asyncio.create_task(driver.update_source_target("smua", 0.3))
    await asyncio.wait_for(client.nonzero_started.wait(), timeout=1.0)
    off_committed = _observe_mock_off_commit(driver)
    stop_task = asyncio.create_task(driver.stop_source("smua"))
    await asyncio.wait_for(off_committed.wait(), timeout=1.0)
    assert driver._channels["smua"].active is False
    client.release_nonzero.set()
    update_result, stop_result = await asyncio.gather(update_task, stop_task, return_exceptions=True)

    assert isinstance(update_result, RuntimeError)
    assert stop_result is None
    assert client.applied[-2:] == [0.3, 0.0]


@pytest.mark.parametrize("operation", ["start", "update"])
async def test_cancelled_stop_settles_zero_after_delayed_external_power(operation: str) -> None:
    client = _DelayedPowerClient()
    driver = Keithley2604B("K", "USB::MOCK", mock=True, mock_instrument_client=client)
    await driver.connect()
    if operation == "update":
        await driver.start_source("smua", 0.1, 10.0, 0.5)
    client.arm()

    if operation == "start":
        stale_task = asyncio.create_task(driver.start_source("smua", 0.2, 10.0, 0.5))
        expected_positive = 0.2
    else:
        stale_task = asyncio.create_task(driver.update_source_target("smua", 0.3))
        expected_positive = 0.3
    await asyncio.wait_for(client.nonzero_started.wait(), timeout=1.0)
    off_committed = _observe_mock_off_commit(driver)
    stop_task = asyncio.create_task(driver.stop_source("smua"))
    await asyncio.wait_for(off_committed.wait(), timeout=1.0)
    stop_task.cancel()
    client.release_nonzero.set()
    stale_result, stop_result = await asyncio.gather(stale_task, stop_task, return_exceptions=True)

    assert isinstance(stale_result, RuntimeError)
    assert isinstance(stop_result, asyncio.CancelledError)
    assert driver._channels["smua"].active is False
    assert driver._channels["smua"].p_target == 0.0
    assert expected_positive in client.applied
    assert client.applied[-1] == 0.0


class _HeaterChannelTrackingClient(ExternalMockInstrumentClient):
    def __init__(self) -> None:
        super().__init__(MockInstrumentEndpoint("127.0.0.1", 1))
        self.applied: list[float] = []

    async def set_power(self, power_w: float) -> None:
        self.applied.append(power_w)


async def test_smua_only_drives_mock_thermal_plant_channel() -> None:
    calculator_config = yaml.safe_load((ROOT / "plugins" / "thermal_calculator.yaml").read_text(encoding="utf-8"))
    assert calculator_config["heater_channel"] == "Keithley_1/smua/power"

    client = _HeaterChannelTrackingClient()
    driver = Keithley2604B("Keithley_1", "USB::MOCK", mock=True, mock_instrument_client=client)
    await driver.connect()

    await driver.start_source("smua", 0.2, 10.0, 0.5)
    await driver.start_source("smub", 0.3, 10.0, 0.5)
    assert driver._channels["smua"].active is True
    assert driver._channels["smub"].active is True
    assert client.applied[-1] == pytest.approx(0.2)

    await driver.update_source_target("smub", 0.4)
    assert client.applied[-1] == pytest.approx(0.2)

    await driver.stop_source("smua")
    assert driver._channels["smua"].active is False
    assert driver._channels["smub"].active is True
    assert client.applied[-1] == 0.0

    renamed_client = _HeaterChannelTrackingClient()
    renamed_config = validate_instrument_entry(
        {
            "type": "keithley_2604b",
            "name": "Keithley_aux",
            "resource": "USB0::0x05E6::0x2604::MOCK00002::INSTR",
            "poll_interval_s": 0.01,
        }
    )
    renamed = construct_driver(
        renamed_config,
        DriverConstructionContext(mock=True, mock_instrument_client=renamed_client),
    )
    assert isinstance(renamed, Keithley2604B)
    await renamed.connect()
    await renamed.start_source("smua", 0.2, 10.0, 0.5)
    assert renamed_client.applied == []


class _NoExternalLakeShoreQueryClient(ExternalMockInstrumentClient):
    def __init__(self) -> None:
        super().__init__(MockInstrumentEndpoint("127.0.0.1", 1))
        self.queries = 0

    async def query(self, _command: str, timeout_ms: int | None = None) -> str:
        self.queries += 1
        raise AssertionError("external lakeshore query client was unexpectedly invoked")


async def test_auxiliary_lakeshore_uses_internal_mock_transport(
    tmp_path: Path,
) -> None:
    client = _NoExternalLakeShoreQueryClient()
    loaded = engine_module._load_drivers(
        ROOT / "config" / "instruments.yaml",
        mock=True,
        data_dir=tmp_path,
        mock_instrument_client=client,
    )
    lakeshores = [config.driver for config in loaded.instrument_configs if isinstance(config.driver, LakeShore218S)]
    assert [driver.name for driver in lakeshores] == ["LS218_1", "LS218_2", "LS218_3"]
    assert [driver.name for driver in lakeshores if driver._mock_instrument_client is client] == ["LS218_1"]
    assert all(driver._mock_instrument_client is None for driver in lakeshores if driver.name != "LS218_1")


@pytest.mark.parametrize(
    "channels",
    [
        {1: "Т2 Криостат низ", 7: "Т7 Детектор"},
        {1: "Т1 Криостат верх", 7: "Т6 Экран 4К"},
        {1: "Т1 Криостат верх"},
    ],
)
async def test_external_simulator_binding_requires_canonical_lakeshore_channels(channels: dict[int, str]) -> None:
    client = _HeaterChannelTrackingClient()
    remapped = validate_instrument_entry(
        {
            "type": "lakeshore_218s",
            "name": "LS218_1",
            "resource": "GPIB0::12::INSTR",
            "poll_interval_s": 0.01,
            "channels": channels,
        }
    )
    with pytest.raises(DriverRegistryError, match="external thermal simulator requires channel"):
        construct_driver(remapped, DriverConstructionContext(mock=True, mock_instrument_client=client))
