from __future__ import annotations

import asyncio
import gc
import tracemalloc
from datetime import UTC, datetime
from typing import get_type_hints

import pytest

import cryodaq.drivers.contracts as driver_contracts
import cryodaq.drivers.registry as driver_registry
from cryodaq.engine_wiring.operator_snapshot_authorities import AuthorityAvailability, CommonCut
from cryodaq.health.infra_authority import ReaderPoolHealthAuthority
from cryodaq.operator_snapshot import OperatorPresentationState

_FORBIDDEN_COMMAND_TOKENS = ("start", "stop", "reset", "vent", "purge", "set", "remediate")


def _registry_reader(*, heartbeat_frames: int = 4):
    factory = getattr(driver_registry, "construct_health_telemetry_reader", None)
    assert callable(factory), "driver registry must construct allowlisted health telemetry readers"
    return factory(
        "deterministic_health_node",
        device_id="compressor.primary",
        component_type="compressor",
        cadence_hz=2.0,
        start_time_s=10.0,
        heartbeat_frames=heartbeat_frames,
        stale_after_s=0.5,
        disconnected_after_s=1.0,
    )


def _cut(revision: int, observed_time_s: float) -> CommonCut:
    return CommonCut(revision, f"cut-v1:{revision}:{'a' * 64}", datetime.fromtimestamp(observed_time_s, tz=UTC))


def test_health_protocol_lives_with_driver_capabilities_and_is_snapshot_only() -> None:
    protocol = getattr(driver_contracts, "HealthTelemetryDevice", None)
    assert protocol is not None, "HealthTelemetryDevice must live in cryodaq.drivers.contracts"
    members = driver_contracts.declared_protocol_members(protocol)
    assert members == (
        "health_descriptor",
        "read_health_snapshot",
    )
    assert not any(token in member for member in members for token in _FORBIDDEN_COMMAND_TOKENS)
    descriptor_hints = get_type_hints(protocol.health_descriptor.fget)
    snapshot_hints = get_type_hints(protocol.read_health_snapshot)
    assert descriptor_hints["return"].__name__ == "HealthDeviceDescriptor"
    assert snapshot_hints["return"].__name__ == "HealthTelemetrySnapshot"


def test_health_simulator_is_an_exact_static_driver_registry_allowlist_entry() -> None:
    capability = getattr(driver_registry.DriverCapability, "HEALTH_TELEMETRY_DEVICE", None)
    specs = getattr(driver_registry, "BUILTIN_HEALTH_TELEMETRY_SPECS", {})
    assert capability is not None, "driver capability metadata must name passive health telemetry"
    assert set(specs) == {"deterministic_health_node"}
    spec = specs["deterministic_health_node"]
    assert spec.capabilities == frozenset({capability})
    assert spec.authority is driver_registry.DriverAuthority.PASSIVE_EXTENSION
    assert spec.module == "cryodaq.health.simulator"
    assert spec.class_name == "DeterministicHealthTelemetryNode"
    assert spec.grants_control_authority is False


def test_registry_reader_cannot_be_coerced_into_command_capability() -> None:
    reader = _registry_reader()
    public = {name for name in dir(reader) if not name.startswith("_")}
    assert public == {"descriptor", "grants_control_authority", "snapshot"}
    assert reader.grants_control_authority is False
    assert not isinstance(reader, driver_contracts.ControlledSource)
    assert not any(token in member for member in public for token in _FORBIDDEN_COMMAND_TOKENS)
    assert not hasattr(reader, "__dict__")


def test_configured_ordinary_lab_support_node_types_are_deterministic_at_two_hz() -> None:
    factory = getattr(driver_registry, "construct_health_telemetry_reader", None)
    assert callable(factory), "driver registry must construct allowlisted health telemetry readers"
    component_types = ("compressor", "pump_station", "cryocooler", "support_node")
    readers = tuple(
        factory(
            "deterministic_health_node",
            device_id=f"lab.{component_type}.01",
            component_type=component_type,
            cadence_hz=2.0,
            start_time_s=10.0,
            heartbeat_frames=8,
        )
        for component_type in component_types
    )
    mirror_readers = tuple(
        factory(
            "deterministic_health_node",
            device_id=f"lab.{component_type}.01",
            component_type=component_type,
            cadence_hz=2.0,
            start_time_s=10.0,
            heartbeat_frames=8,
        )
        for component_type in component_types
    )
    first = tuple(reader.snapshot(observed_time_s=10.0) for reader in readers)
    second = tuple(reader.snapshot(observed_time_s=10.5) for reader in readers)
    mirror_first = tuple(reader.snapshot(observed_time_s=10.0) for reader in mirror_readers)
    mirror_second = tuple(reader.snapshot(observed_time_s=10.5) for reader in mirror_readers)
    assert (first, second) == (mirror_first, mirror_second)
    assert tuple(item.descriptor.component_type for item in first) == component_types
    assert all(later.observed_time_s - earlier.observed_time_s == 0.5 for earlier, later in zip(first, second))
    assert all(later.revision == earlier.revision + 1 for earlier, later in zip(first, second))
    assert all(later.descriptor.provenance == "driver-registry:deterministic-health-node/v1" for later in second)


def test_registry_rejects_faster_than_two_hz() -> None:
    factory = getattr(driver_registry, "construct_health_telemetry_reader", None)
    assert callable(factory), "driver registry must construct allowlisted health telemetry readers"
    with pytest.raises(ValueError, match="cadence_hz"):
        factory(
            "deterministic_health_node",
            device_id="compressor.too_fast",
            component_type="compressor",
            cadence_hz=2.0001,
        )


def test_registry_rejects_unknown_health_type() -> None:
    factory = getattr(driver_registry, "construct_health_telemetry_reader", None)
    assert callable(factory), "driver registry must construct allowlisted health telemetry readers"
    with pytest.raises(driver_registry.UnknownDriverTypeError, match="unknown health telemetry type"):
        factory(
            "plugin.health",
            device_id="compressor.unknown",
            component_type="compressor",
        )


def test_silent_node_projects_explicit_disconnected_instead_of_healthy() -> None:
    reader = _registry_reader(heartbeat_frames=1)
    authority = ReaderPoolHealthAuthority((reader,))
    authority.presample(observed_time_s=10.0)
    fresh = authority.snapshot_for_cut(_cut(1, 10.0))
    for observed in (10.5, 11.0, 11.5):
        authority.presample(observed_time_s=observed)
    silent = authority.snapshot_for_cut(_cut(2, 11.5))
    assert fresh.availability is AuthorityAvailability.AVAILABLE
    assert fresh.nodes[0].state is OperatorPresentationState.OK
    assert silent.availability is AuthorityAvailability.AVAILABLE
    assert silent.nodes[0].state is OperatorPresentationState.DISCONNECTED
    assert silent.nodes[0].reason_code == "health_disconnected"
    assert silent.nodes[0].state is not OperatorPresentationState.OK


@pytest.mark.asyncio
async def test_repeated_registry_updates_have_bounded_resources_and_retained_memory() -> None:
    reader = _registry_reader(heartbeat_frames=20_000)
    before_tasks = set(asyncio.all_tasks())
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:  # pragma: no cover - core-only developer environments
        application = None
        before_widgets = 0
    else:
        application = QApplication.instance()
        before_widgets = 0 if application is None else len(application.allWidgets())
    for index in range(128):
        reader.snapshot(observed_time_s=10.0 + index * 0.5)
    gc.collect()
    tracemalloc.start()
    baseline_current, _baseline_peak = tracemalloc.get_traced_memory()
    tracemalloc.reset_peak()
    snapshot = None
    for index in range(128, 10_128):
        snapshot = reader.snapshot(observed_time_s=10.0 + index * 0.5)
    del snapshot
    gc.collect()
    final_current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    after_widgets = 0 if application is None else len(application.allWidgets())
    retained_slots = {
        slot: object.__getattribute__(reader, slot)
        for slot in type(reader).__slots__
        if slot not in {"_entry", "_read_snapshot"}
    }
    read_snapshot = object.__getattribute__(reader, "_read_snapshot")
    node = read_snapshot.__self__
    retained_node_slots = {slot: object.__getattribute__(node, slot) for slot in type(node).__slots__}
    retained_values = (*retained_slots.values(), *retained_node_slots.values())
    assert set(asyncio.all_tasks()) == before_tasks
    assert after_widgets == before_widgets
    assert not any(isinstance(value, (asyncio.Queue, asyncio.Task)) for value in retained_values)
    assert len(retained_slots["_metric_schema"]) == 1
    assert retained_slots["_counter_values"] == {}
    assert len(retained_node_slots) == 7
    assert not any(isinstance(value, (dict, list, set)) for value in retained_node_slots.values())
    assert final_current - baseline_current <= 32_768
    assert peak - baseline_current <= 131_072
