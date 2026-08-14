"""Descriptor-owned identity regressions for RUN-critical inputs."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyConfigError, SafetyManager, SafetyState
from cryodaq.core.safety_pattern_liveness import validate_safety_pattern_liveness
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.drivers.contracts import (
    AcquisitionTiming,
    DriverTrustClass,
    SourceOffResult,
    _issue_registry_runtime_binding,
)
from cryodaq.storage.channel_descriptors import load_live_channel_descriptor_catalog
from tests.qualification_support import issued_test_qualification_receipt


class _ReviewedSource:
    def __init__(self) -> None:
        self.name = "Reviewed_1"
        self.connected = True
        self.output_state_unverified = False
        self.emergency_off_calls = 0

    async def emergency_off(self, _channel: str | None = None) -> SourceOffResult:
        self.emergency_off_calls += 1
        return SourceOffResult.DEVICE_REPORTED_OFF

    async def start_source(
        self,
        _channel: str,
        _power_w: float,
        _voltage_v: float,
        _current_a: float,
    ) -> None:
        return None

    async def stop_source(self, _channel: str) -> SourceOffResult:
        return SourceOffResult.DEVICE_REPORTED_OFF


def _descriptor(
    *,
    channel_id: str,
    instrument_id: str,
    source_key: str,
    display_order: int,
    source_readback: bool = False,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "channel_id": channel_id,
        "instrument_id": instrument_id,
        "source_key": source_key,
        "quantity": "voltage" if source_readback else "temperature",
        "unit": "V" if source_readback else "K",
        "role": "source_readback" if source_readback else "primary_measurement",
        "safety_class": "hazardous_source_readback" if source_readback else "safety_critical_input",
        "display_group": "test",
        "display_name": channel_id,
        "visible_by_default": True,
        "display_order": display_order,
        "descriptor_revision": 1,
    }


def _write_fixture(
    tmp_path: Path,
    *,
    critical_ids: list[str] | None = None,
    critical_emitted: str = "guard raw",
    include_second_critical: bool = False,
) -> tuple[Path, Path, Path]:
    descriptors = [
        _descriptor(
            channel_id="guard",
            instrument_id="Sensor_1",
            source_key="input.1.temperature",
            display_order=1,
        ),
        _descriptor(
            channel_id="source.feedback.a",
            instrument_id="Reviewed_1",
            source_key="output.a.feedback",
            display_order=2,
            source_readback=True,
        ),
        _descriptor(
            channel_id="source.feedback.b",
            instrument_id="Reviewed_1",
            source_key="output.b.feedback",
            display_order=3,
            source_readback=True,
        ),
    ]
    bindings = [
        {
            "instrument_id": "Sensor_1",
            "emitted_channel": critical_emitted,
            "channel_id": "guard",
        },
        {
            "instrument_id": "Reviewed_1",
            "emitted_channel": "Reviewed_1/smua/voltage",
            "channel_id": "source.feedback.a",
        },
        {
            "instrument_id": "Reviewed_1",
            "emitted_channel": "Reviewed_1/smub/voltage",
            "channel_id": "source.feedback.b",
        },
    ]
    if include_second_critical:
        descriptors.append(
            _descriptor(
                channel_id="guard.backup",
                instrument_id="Sensor_2",
                source_key="input.2.temperature",
                display_order=4,
            )
        )
        bindings.append(
            {
                "instrument_id": "Sensor_2",
                "emitted_channel": "guard backup raw",
                "channel_id": "guard.backup",
            }
        )

    descriptor_path = tmp_path / "channel_descriptors.yaml"
    descriptor_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "descriptors": descriptors,
                "bindings": bindings,
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    safety_path = tmp_path / "safety.yaml"
    safety_path.write_text(
        yaml.safe_dump(
            {
                "critical_channels": ["guard"] if critical_ids is None else critical_ids,
                "stale_timeout_s": 10.0,
                "heartbeat_timeout_s": 15.0,
                "keithley_heartbeat_channels": {
                    "smua": ["source.feedback.a"],
                    "smub": ["source.feedback.b"],
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    interlocks_path = tmp_path / "interlocks.yaml"
    interlocks_path.write_text("interlocks: []\n", encoding="utf-8")
    (tmp_path / "alarms_v3.yaml").write_text("{}\n", encoding="utf-8")
    return descriptor_path, safety_path, interlocks_path


def _configured_manager(
    descriptor_path: Path,
    safety_path: Path,
    interlocks_path: Path,
) -> tuple[SafetyManager, SafetyBroker, _ReviewedSource, object]:
    driver = _ReviewedSource()
    binding = _issue_registry_runtime_binding(
        driver=driver,
        timing=AcquisitionTiming(1.0, 1.0, 1.0),
        registry_provenance="test:safety-critical-input-identity",
        trust_class=DriverTrustClass.REVIEWED_SOURCE,
    )
    broker = SafetyBroker()
    manager = SafetyManager(
        broker,
        keithley_driver=driver,
        reviewed_source_runtime_binding=binding,
        qualification_receipt=issued_test_qualification_receipt(),
        mock=False,
    )
    manager.load_config(safety_path)
    validate_safety_pattern_liveness(
        descriptor_catalog=load_live_channel_descriptor_catalog(descriptor_path),
        interlocks_config_path=interlocks_path,
        safety_manager=manager,
        adaptive_throttle_patterns=set(),
    )
    return manager, broker, driver, binding


async def _start_and_connect(
    manager: SafetyManager,
    driver: _ReviewedSource,
    binding: object,
) -> None:
    await manager.start()
    generation = await manager.begin_reviewed_source_connect(
        driver,
        binding,  # type: ignore[arg-type]
        "test setup",
    )
    evidence = await manager.complete_reviewed_source_connect(
        driver,
        binding,  # type: ignore[arg-type]
        generation,
        "test setup",
    )
    assert evidence.verified_off


async def _publish(
    broker: SafetyBroker,
    *,
    instrument_id: str,
    channel: str,
    value: float = 4.0,
    unit: str = "K",
    status: ChannelStatus = ChannelStatus.OK,
    timestamp: datetime | None = None,
) -> None:
    await broker.publish(
        Reading(
            timestamp=datetime.now(UTC) if timestamp is None else timestamp,
            channel=channel,
            value=value,
            unit=unit,
            instrument_id=instrument_id,
            status=status,
        )
    )


async def _wait_for_readings(manager: SafetyManager, count: int) -> None:
    for _ in range(100):
        if manager.get_status()["channels_tracked"] == count:
            return
        await asyncio.sleep(0.001)
    raise AssertionError(f"collector tracked {manager.get_status()['channels_tracked']} readings, expected {count}")


async def test_a_foreign_critical_label_does_not_authorize_run(tmp_path: Path) -> None:
    descriptor_path, safety_path, interlocks_path = _write_fixture(tmp_path)
    manager, broker, driver, binding = _configured_manager(descriptor_path, safety_path, interlocks_path)
    await _start_and_connect(manager, driver, binding)
    try:
        await _publish(broker, instrument_id="Foreign_1", channel="guard raw")
        await _wait_for_readings(manager, 1)

        result = await manager.request_run(0.5, 10.0, 0.1, channel="smua")

        assert result["ok"] is False
        assert manager.state is SafetyState.SAFE_OFF
        assert manager._active_sources == set()
        assert driver.emergency_off_calls == 0
    finally:
        await manager.stop()


async def test_b_foreign_substitution_faults_and_commands_emergency_off(tmp_path: Path) -> None:
    descriptor_path, safety_path, interlocks_path = _write_fixture(tmp_path)
    manager, broker, driver, binding = _configured_manager(descriptor_path, safety_path, interlocks_path)
    await _start_and_connect(manager, driver, binding)
    try:
        await _publish(broker, instrument_id="Foreign_1", channel="guard raw")
        await _publish(
            broker,
            instrument_id="Reviewed_1",
            channel="Reviewed_1/smua/voltage",
            unit="V",
        )
        await _wait_for_readings(manager, 2)
        manager._state = SafetyState.RUNNING
        manager._active_sources = {"smua"}

        await manager._run_checks()

        assert manager.state is SafetyState.FAULT_LATCHED
        assert manager._active_sources == set()
        assert driver.emergency_off_calls == 1
    finally:
        await manager.stop()


@pytest.mark.parametrize("condition", ["stale", "bad_status"])
async def test_b_present_unhealthy_declared_input_still_faults(
    tmp_path: Path,
    condition: str,
) -> None:
    descriptor_path, safety_path, interlocks_path = _write_fixture(tmp_path)
    manager, broker, driver, binding = _configured_manager(descriptor_path, safety_path, interlocks_path)
    await _start_and_connect(manager, driver, binding)
    try:
        await _publish(
            broker,
            instrument_id="Sensor_1",
            channel="guard raw",
            status=ChannelStatus.SENSOR_ERROR if condition == "bad_status" else ChannelStatus.OK,
        )
        await _publish(broker, instrument_id="Foreign_1", channel="guard raw")
        await _publish(
            broker,
            instrument_id="Reviewed_1",
            channel="Reviewed_1/smua/voltage",
            unit="V",
        )
        await _wait_for_readings(manager, 3)
        if condition == "stale":
            manager._latest[("Sensor_1", "guard raw")] = (
                time.monotonic() - 20.0,
                4.0,
                "ok",
            )
        manager._state = SafetyState.RUNNING
        manager._active_sources = {"smua"}

        await manager._run_checks()

        assert manager.state is SafetyState.FAULT_LATCHED
        assert manager._active_sources == set()
        assert driver.emergency_off_calls == 1
    finally:
        await manager.stop()


@pytest.mark.parametrize(
    ("ramp_instrument", "expected_state", "expected_off_calls"),
    [
        ("Foreign_1", SafetyState.RUNNING, 0),
        ("Sensor_1", SafetyState.FAULT_LATCHED, 1),
    ],
    ids=["foreign-rate-ignored", "declared-rate-faults"],
)
async def test_critical_rate_selection_uses_exact_declared_identity(
    tmp_path: Path,
    ramp_instrument: str,
    expected_state: SafetyState,
    expected_off_calls: int,
) -> None:
    descriptor_path, safety_path, interlocks_path = _write_fixture(tmp_path)
    manager, broker, driver, binding = _configured_manager(descriptor_path, safety_path, interlocks_path)
    await _start_and_connect(manager, driver, binding)
    try:
        base = datetime.now(UTC) - timedelta(seconds=35)
        await _publish(
            broker,
            instrument_id="Sensor_1",
            channel="guard raw",
            value=4.0,
            timestamp=base,
        )
        for index in range(8):
            await _publish(
                broker,
                instrument_id=ramp_instrument,
                channel="guard raw",
                value=4.0 + index * 10.0,
                timestamp=base + timedelta(seconds=5 * index),
            )
        await _publish(
            broker,
            instrument_id="Reviewed_1",
            channel="Reviewed_1/smua/voltage",
            unit="V",
        )
        expected_readings = 2 if ramp_instrument == "Sensor_1" else 3
        await _wait_for_readings(manager, expected_readings)
        manager._state = SafetyState.RUNNING
        manager._active_sources = {"smua"}

        await manager._run_checks()

        assert manager.state is expected_state
        assert driver.emergency_off_calls == expected_off_calls
    finally:
        await manager.stop()


async def test_c_authorized_critical_input_rename_still_works(tmp_path: Path) -> None:
    descriptor_path, safety_path, interlocks_path = _write_fixture(
        tmp_path,
        critical_emitted="renamed critical input",
    )
    manager, broker, driver, binding = _configured_manager(descriptor_path, safety_path, interlocks_path)
    await _start_and_connect(manager, driver, binding)
    try:
        await _publish(
            broker,
            instrument_id="Sensor_1",
            channel="renamed critical input",
        )
        await _wait_for_readings(manager, 1)

        result = await manager.request_run(0.5, 10.0, 0.1, channel="smua")

        assert result["ok"] is True
        assert manager.state is SafetyState.RUNNING
        assert manager._active_sources == {"smua"}
        assert driver.emergency_off_calls == 0
    finally:
        await manager.stop()


def test_d_startup_rejects_misspelled_declared_critical_identity(tmp_path: Path) -> None:
    descriptor_path, safety_path, interlocks_path = _write_fixture(
        tmp_path,
        critical_ids=["gaurd"],
    )

    with pytest.raises(SafetyConfigError) as exc_info:
        _configured_manager(descriptor_path, safety_path, interlocks_path)

    message = str(exc_info.value)
    assert "gaurd" in message
    assert "canonical identity resolution to raw emitted label" in message


@pytest.mark.parametrize(
    ("critical_ids", "include_second_critical"),
    [
        ([], False),
        (["guard", "guard"], True),
        (["source.feedback.a"], False),
    ],
    ids=["missing", "ambiguous", "cross-output"],
)
def test_d_startup_rejects_invalid_critical_input_binding(
    tmp_path: Path,
    critical_ids: list[str],
    include_second_critical: bool,
) -> None:
    descriptor_path, safety_path, interlocks_path = _write_fixture(
        tmp_path,
        critical_ids=critical_ids,
        include_second_critical=include_second_critical,
    )

    with pytest.raises(SafetyConfigError):
        _configured_manager(descriptor_path, safety_path, interlocks_path)


async def test_e_healthy_production_style_path_reaches_run_without_fault(tmp_path: Path) -> None:
    descriptor_path, safety_path, interlocks_path = _write_fixture(tmp_path)
    manager, broker, driver, binding = _configured_manager(descriptor_path, safety_path, interlocks_path)
    await _start_and_connect(manager, driver, binding)
    try:
        await _publish(broker, instrument_id="Sensor_1", channel="guard raw")
        await _publish(
            broker,
            instrument_id="Reviewed_1",
            channel="Reviewed_1/smua/voltage",
            unit="V",
        )
        await _wait_for_readings(manager, 2)

        result = await manager.request_run(0.5, 10.0, 0.1, channel="smua")
        await manager._run_checks()

        assert result["ok"] is True
        assert manager.state is SafetyState.RUNNING
        assert manager._active_sources == {"smua"}
        assert driver.emergency_off_calls == 0
    finally:
        await manager.stop()
