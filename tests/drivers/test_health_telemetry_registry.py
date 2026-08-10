from __future__ import annotations

import asyncio
import gc
import tracemalloc
from datetime import UTC, datetime
from typing import get_type_hints

import pytest

import cryodaq.drivers.contracts as driver_contracts
import cryodaq.drivers.registry as driver_registry
import cryodaq.health as health_package
import cryodaq.health.contract as health_contract
from cryodaq.engine_wiring.operator_snapshot_authorities import AuthorityAvailability, CommonCut
from cryodaq.health.contract import HealthDeviceDescriptor, HealthTelemetrySnapshot
from cryodaq.health.infra_authority import ReaderPoolHealthAuthority
from cryodaq.operator_snapshot import OperatorPresentationState

_FORBIDDEN_COMMAND_TOKENS = ("start", "stop", "reset", "vent", "purge", "set", "remediate")


def _registry_reader(*, heartbeat_frames: int = 4, **overrides: object):
    factory = getattr(driver_registry, "construct_health_telemetry_reader", None)
    assert callable(factory), "driver registry must construct allowlisted health telemetry readers"
    configuration: dict[str, object] = {
        "type": "deterministic_health_node",
        "name": "compressor.primary",
        "component_type": "compressor",
        "cadence_hz": 2.0,
        "start_time_s": 10.0,
        "heartbeat_frames": heartbeat_frames,
        "stale_after_s": 0.5,
        "disconnected_after_s": 1.0,
    }
    configuration.update(overrides)
    validated = driver_registry.validate_instrument_entry(configuration, path="health_nodes[0]")
    context = driver_registry.DriverConstructionContext(mock=True)
    return factory(validated, context)


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
    assert capability is not None, "driver capability metadata must name passive health telemetry"
    assert not hasattr(driver_registry, "BUILTIN_HEALTH_TELEMETRY_SPECS")
    spec = driver_registry.get_driver_spec("deterministic_health_node")
    assert driver_registry.BUILTIN_DRIVER_SPECS[spec.type_name] is spec
    assert driver_registry.PASSIVE_DRIVER_SPECS[spec.type_name] is spec
    assert driver_registry.BUILTIN_DRIVER_METADATA[spec.type_name].capabilities == spec.capabilities
    assert spec.module in driver_registry.ALLOWLISTED_DRIVER_MODULES
    assert spec.capabilities == frozenset({capability})
    assert spec.authority is driver_registry.DriverAuthority.PASSIVE_EXTENSION
    assert spec.module == "cryodaq.health.simulator"
    assert spec.class_name == "DeterministicHealthTelemetryNode"
    assert spec.reviewed_source_binding is None


def test_unregistered_snapshot_implementation_cannot_execute_hidden_remediation() -> None:
    class RogueHealthNode:
        __slots__ = ("_commanded", "_descriptor")

        def __init__(self) -> None:
            self._commanded = False
            self._descriptor = HealthDeviceDescriptor(
                "compressor.rogue",
                "compressor",
                "unregistered-test/v1",
            )

        @property
        def health_descriptor(self) -> HealthDeviceDescriptor:
            return self._descriptor

        def _remediate(self) -> None:
            self._commanded = True

        def read_health_snapshot(self, *, observed_time_s: float) -> HealthTelemetrySnapshot:
            self._remediate()
            return HealthTelemetrySnapshot(
                self._descriptor,
                1,
                observed_time_s,
                observed_time_s,
                "running",
            )

    rogue = RogueHealthNode()
    entry = health_contract._StaticHealthTelemetryAllowlistEntry(
        rogue.health_descriptor.device_id,
        type(rogue),
    )
    directly_issued = health_contract._issue_health_telemetry_reader(rogue, entry=entry)
    assert driver_registry.health_telemetry_spec_for_reader(directly_issued) is None
    with pytest.raises(TypeError, match="registry-issued"):
        ReaderPoolHealthAuthority((directly_issued,))
    assert rogue._commanded is False, "unregistered health sampling executed hidden remediation"
    assert not hasattr(health_package, "StaticHealthTelemetryAllowlistEntry")
    assert not hasattr(health_package, "issue_health_telemetry_reader")
    assert not hasattr(health_contract, "StaticHealthTelemetryAllowlistEntry")
    assert not hasattr(health_contract, "issue_health_telemetry_reader")


def test_registry_reader_cannot_be_coerced_into_command_capability() -> None:
    reader = _registry_reader()
    public = {name for name in dir(reader) if not name.startswith("_")}
    assert public == {"descriptor", "grants_control_authority", "snapshot"}
    assert reader.grants_control_authority is False
    assert driver_registry.health_telemetry_spec_for_reader(reader) is driver_registry.get_driver_spec(
        "deterministic_health_node"
    )
    assert not isinstance(reader, driver_contracts.ControlledSource)
    assert not any(token in member for member in public for token in _FORBIDDEN_COMMAND_TOKENS)
    assert not hasattr(reader, "__dict__")


def test_configured_ordinary_lab_support_node_types_are_deterministic_at_two_hz() -> None:
    factory = getattr(driver_registry, "construct_health_telemetry_reader", None)
    assert callable(factory), "driver registry must construct allowlisted health telemetry readers"
    component_types = ("compressor", "pump_station", "cryocooler", "support_node")
    readers = tuple(
        _registry_reader(
            name=f"lab.{component_type}.01",
            component_type=component_type,
            heartbeat_frames=8,
        )
        for component_type in component_types
    )
    mirror_readers = tuple(
        _registry_reader(
            name=f"lab.{component_type}.01",
            component_type=component_type,
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
        _registry_reader(name="compressor.too_fast", cadence_hz=2.0001)


def test_registry_rejects_clock_ranges_that_collapse_distinct_cadence_ticks() -> None:
    with pytest.raises(ValueError, match="start_time_s"):
        _registry_reader(start_time_s=1e308)


def test_registry_rejects_unknown_health_type() -> None:
    factory = getattr(driver_registry, "construct_health_telemetry_reader", None)
    assert callable(factory), "driver registry must construct allowlisted health telemetry readers"
    with pytest.raises(driver_registry.UnknownDriverTypeError, match="unknown instrument type"):
        driver_registry.validate_instrument_entry(
            {"type": "plugin.health", "name": "compressor.unknown"},
            path="health_nodes[0]",
        )


def test_silent_node_projects_explicit_disconnected_instead_of_healthy() -> None:
    reader = _registry_reader(heartbeat_frames=1)
    authority = ReaderPoolHealthAuthority((reader,))
    authority.presample(observed_time_s=10.0)
    fresh = authority.snapshot_for_cut(_cut(1, 10.0))
    authority.presample(observed_time_s=10.5)
    authority.presample(observed_time_s=11.0)
    stale = authority.snapshot_for_cut(_cut(2, 11.0))
    authority.presample(observed_time_s=11.5)
    silent = authority.snapshot_for_cut(_cut(3, 11.5))
    assert fresh.availability is AuthorityAvailability.AVAILABLE
    assert fresh.nodes[0].state is OperatorPresentationState.OK
    assert stale.nodes[0].state is OperatorPresentationState.STALE
    assert stale.nodes[0].reason_code == "health_stale"
    assert silent.availability is AuthorityAvailability.AVAILABLE
    assert silent.nodes[0].state is OperatorPresentationState.DISCONNECTED
    assert silent.nodes[0].reason_code == "health_disconnected"
    assert silent.nodes[0].state is not OperatorPresentationState.OK


@pytest.mark.asyncio
async def test_repeated_registry_updates_have_bounded_resources_and_retained_memory() -> None:
    reader = _registry_reader(heartbeat_frames=20_000)
    receipt_count = len(driver_registry._HEALTH_TELEMETRY_BINDINGS)
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
    assert len(driver_registry._HEALTH_TELEMETRY_BINDINGS) == receipt_count
    assert after_widgets == before_widgets
    assert not any(isinstance(value, (asyncio.Queue, asyncio.Task)) for value in retained_values)
    assert len(retained_slots["_metric_schema"]) == 1
    assert retained_slots["_counter_values"] == {}
    assert len(retained_node_slots) == 7
    assert not any(isinstance(value, (dict, list, set)) for value in retained_node_slots.values())
    assert final_current - baseline_current <= 32_768
    assert peak - baseline_current <= 131_072
