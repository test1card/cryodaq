"""Descriptor-owned identity regressions for hazardous-source heartbeats."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml

from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager, SafetyState
from cryodaq.core.safety_pattern_liveness import (
    SafetyPatternLivenessError,
    validate_safety_pattern_liveness,
)
from cryodaq.drivers.base import Reading
from cryodaq.drivers.contracts import (
    AcquisitionTiming,
    DriverTrustClass,
    SourceOffResult,
    _issue_registry_runtime_binding,
)
from cryodaq.storage.channel_descriptors import load_live_channel_descriptor_catalog
from tests.qualification_support import issued_test_qualification_receipt


class _ReviewedSource:
    def __init__(self, name: str) -> None:
        self.name = name
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
    source_readback: bool,
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
    smua_emitted: str = "Reviewed_1/smua/voltage",
    smub_emitted: str = "Reviewed_1/smub/voltage",
    smua_declared: list[str] | None = None,
    smub_declared: list[str] | None = None,
    smua_instrument: str = "Reviewed_1",
) -> tuple[Path, Path, Path]:
    smua_id = "source.feedback.a"
    smub_id = "source.feedback.b"
    manifest = {
        "schema_version": 1,
        "descriptors": [
            _descriptor(
                channel_id="guard",
                instrument_id="Sensor_1",
                source_key="input.1.temperature",
                display_order=1,
                source_readback=False,
            ),
            _descriptor(
                channel_id=smua_id,
                instrument_id=smua_instrument,
                source_key="output.a.feedback",
                display_order=2,
                source_readback=True,
            ),
            _descriptor(
                channel_id=smub_id,
                instrument_id="Reviewed_1",
                source_key="output.b.feedback",
                display_order=3,
                source_readback=True,
            ),
        ],
        "bindings": [
            {
                "instrument_id": "Sensor_1",
                "emitted_channel": "guard raw",
                "channel_id": "guard",
            },
            {
                "instrument_id": smua_instrument,
                "emitted_channel": smua_emitted,
                "channel_id": smua_id,
            },
            {
                "instrument_id": "Reviewed_1",
                "emitted_channel": smub_emitted,
                "channel_id": smub_id,
            },
        ],
    }
    descriptor_path = tmp_path / "channel_descriptors.yaml"
    descriptor_path.write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    safety = {
        "critical_channels": ["guard"],
        "heartbeat_timeout_s": 15.0,
        "keithley_channels": [".*"],
        "keithley_heartbeat_channels": {
            "smua": [smua_id] if smua_declared is None else smua_declared,
            "smub": [smub_id] if smub_declared is None else smub_declared,
        },
    }
    safety_path = tmp_path / "safety.yaml"
    safety_path.write_text(
        yaml.safe_dump(safety, allow_unicode=True, sort_keys=False),
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
) -> tuple[SafetyManager, SafetyBroker, _ReviewedSource]:
    driver = _ReviewedSource("Reviewed_1")
    binding = _issue_registry_runtime_binding(
        driver=driver,
        timing=AcquisitionTiming(1.0, 1.0, 1.0),
        registry_provenance="test:safety-heartbeat-identity",
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
    return manager, broker, driver


async def _exercise(
    manager: SafetyManager,
    broker: SafetyBroker,
    driver: _ReviewedSource,
    *,
    active: set[str],
    readings: list[tuple[str, str]],
) -> tuple[SafetyState, int, set[str]]:
    await manager.start()
    try:
        readings = [("Sensor_1", "guard raw"), *readings]
        for instrument_id, channel in readings:
            await broker.publish(
                Reading.now(
                    channel=channel,
                    value=1.0,
                    unit="V",
                    instrument_id=instrument_id,
                )
            )
        for _ in range(100):
            if manager.get_status()["channels_tracked"] == len(readings):
                break
            await asyncio.sleep(0.001)
        manager._state = SafetyState.RUNNING
        manager._active_sources = set(active)
        await manager._run_checks()
        return manager.state, driver.emergency_off_calls, set(manager._active_sources)
    finally:
        await manager.stop()


async def test_foreign_instrument_identical_heartbeat_spelling_faults_and_turns_off(
    tmp_path: Path,
) -> None:
    descriptor_path, safety_path, interlocks_path = _write_fixture(tmp_path)
    manager, broker, driver = _configured_manager(descriptor_path, safety_path, interlocks_path)

    state, off_calls, active = await _exercise(
        manager,
        broker,
        driver,
        active={"smua"},
        readings=[("Foreign_1", "Reviewed_1/smua/voltage")],
    )

    assert state is SafetyState.FAULT_LATCHED
    assert off_calls == 1
    assert active == set()


async def test_smub_descriptor_feedback_cannot_satisfy_smua(
    tmp_path: Path,
) -> None:
    descriptor_path, safety_path, interlocks_path = _write_fixture(
        tmp_path,
        smub_emitted="Reviewed_1/smua/alias/smub/voltage",
    )
    manager, broker, driver = _configured_manager(descriptor_path, safety_path, interlocks_path)

    state, off_calls, active = await _exercise(
        manager,
        broker,
        driver,
        active={"smua"},
        readings=[("Reviewed_1", "Reviewed_1/smua/alias/smub/voltage")],
    )

    assert state is SafetyState.FAULT_LATCHED
    assert off_calls == 1
    assert active == set()


async def test_descriptor_authorized_emitted_rename_remains_live(
    tmp_path: Path,
) -> None:
    descriptor_path, safety_path, interlocks_path = _write_fixture(
        tmp_path,
        smua_emitted="renamed-output-a-feedback",
    )
    manager, broker, driver = _configured_manager(descriptor_path, safety_path, interlocks_path)

    state, off_calls, active = await _exercise(
        manager,
        broker,
        driver,
        active={"smua"},
        readings=[("Reviewed_1", "renamed-output-a-feedback")],
    )

    assert state is SafetyState.RUNNING
    assert off_calls == 0
    assert active == {"smua"}


async def test_each_active_output_requires_its_own_declared_feedback(
    tmp_path: Path,
) -> None:
    descriptor_path, safety_path, interlocks_path = _write_fixture(
        tmp_path,
        smua_emitted="Reviewed_1/smua/shared/smub/voltage",
    )
    manager, broker, driver = _configured_manager(descriptor_path, safety_path, interlocks_path)

    state, off_calls, active = await _exercise(
        manager,
        broker,
        driver,
        active={"smua", "smub"},
        readings=[("Reviewed_1", "Reviewed_1/smua/shared/smub/voltage")],
    )

    assert state is SafetyState.FAULT_LATCHED
    assert off_calls == 1
    assert active == set()


async def test_healthy_declared_feedback_for_each_output_remains_running(
    tmp_path: Path,
) -> None:
    descriptor_path, safety_path, interlocks_path = _write_fixture(tmp_path)
    manager, broker, driver = _configured_manager(descriptor_path, safety_path, interlocks_path)

    state, off_calls, active = await _exercise(
        manager,
        broker,
        driver,
        active={"smua", "smub"},
        readings=[
            ("Reviewed_1", "Reviewed_1/smua/voltage"),
            ("Reviewed_1", "Reviewed_1/smub/voltage"),
        ],
    )

    assert state is SafetyState.RUNNING
    assert off_calls == 0
    assert active == {"smua", "smub"}


@pytest.mark.parametrize(
    ("fixture_kwargs", "needle"),
    [
        ({"smub_declared": []}, "smub"),
        ({"smua_declared": ["source.feedback.a", "source.feedback.a"]}, "ambiguous"),
        ({"smub_declared": ["source.feedback.a"]}, "cross-SMU"),
        ({"smua_instrument": "Foreign_1"}, "reviewed source"),
    ],
)
def test_startup_rejects_invalid_heartbeat_associations(
    tmp_path: Path,
    fixture_kwargs: dict[str, object],
    needle: str,
) -> None:
    descriptor_path, safety_path, interlocks_path = _write_fixture(tmp_path, **fixture_kwargs)

    with pytest.raises(SafetyPatternLivenessError, match=needle):
        _configured_manager(descriptor_path, safety_path, interlocks_path)
