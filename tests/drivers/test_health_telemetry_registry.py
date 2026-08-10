from __future__ import annotations

import asyncio
import gc
import os
import subprocess
import sys
import tracemalloc
from datetime import UTC, datetime
from typing import get_type_hints

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

import cryodaq.drivers.contracts as driver_contracts
import cryodaq.drivers.registry as driver_registry
import cryodaq.health as health_package
import cryodaq.health.contract as health_contract
from cryodaq.engine_wiring.operator_snapshot_authorities import AuthorityAvailability, CommonCut
from cryodaq.health.contract import HealthDeviceDescriptor, HealthTelemetrySnapshot
from cryodaq.health.infra_authority import ReaderPoolHealthAuthority
from cryodaq.health.simulator import DeterministicHealthTelemetryNode
from cryodaq.operator_snapshot import OperatorPresentationState

_FORBIDDEN_COMMAND_TOKENS = ("start", "stop", "reset", "vent", "purge", "set", "remediate")


def _health_configuration(**overrides: object) -> dict[str, object]:
    configuration: dict[str, object] = {
        "type": "deterministic_health_node",
        "name": "compressor.primary",
        "component_type": "compressor",
        "cadence_hz": 2.0,
        "start_time_s": 10.0,
        "heartbeat_frames": 4,
        "stale_after_s": 0.5,
        "disconnected_after_s": 1.0,
    }
    configuration.update(overrides)
    return configuration


def _registry_reader(*, heartbeat_frames: int = 4, **overrides: object):
    factory = getattr(driver_registry, "construct_health_telemetry_reader", None)
    assert callable(factory), "driver registry must construct allowlisted health telemetry readers"
    configuration = _health_configuration(heartbeat_frames=heartbeat_frames, **overrides)
    validated = driver_registry.validate_health_telemetry_entry(configuration, path="health_nodes[0]")
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
    assert getattr(health_contract, "HealthTelemetryDevice", None) is protocol


@pytest.mark.parametrize("contract_first", [True, False])
def test_health_protocol_compatibility_alias_is_cycle_safe_in_fresh_process(contract_first: bool) -> None:
    first_import = (
        "import cryodaq.health.contract as health_contract\n"
        "contract_protocol = health_contract.HealthTelemetryDevice\n"
        "from cryodaq.drivers.contracts import HealthTelemetryDevice as driver_protocol\n"
        if contract_first
        else "from cryodaq.drivers.contracts import HealthTelemetryDevice as driver_protocol\n"
        "import cryodaq.health.contract as health_contract\n"
        "contract_protocol = health_contract.HealthTelemetryDevice\n"
    )
    script = (
        first_import
        + "from cryodaq.health import HealthTelemetryDevice as package_protocol\n"
        + "assert contract_protocol is driver_protocol is package_protocol\n"
    )

    completed = subprocess.run(
        [sys.executable, "-B", "-c", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


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
    assert not hasattr(driver_registry, "_register_health_telemetry_reader")
    with pytest.raises(TypeError, match="registry-issued"):
        ReaderPoolHealthAuthority((directly_issued,))
    assert rogue._commanded is False, "unregistered health sampling executed hidden remediation"
    assert not hasattr(health_package, "StaticHealthTelemetryAllowlistEntry")
    assert not hasattr(health_package, "issue_health_telemetry_reader")
    assert not hasattr(health_contract, "StaticHealthTelemetryAllowlistEntry")
    assert not hasattr(health_contract, "issue_health_telemetry_reader")


def test_registry_has_no_callable_provenance_minting_seam() -> None:
    node = DeterministicHealthTelemetryNode(
        device_id="compressor.direct",
        component_type="compressor",
        heartbeat_frames=4,
    )
    entry = health_contract._StaticHealthTelemetryAllowlistEntry(node.health_descriptor.device_id, type(node))
    directly_issued = health_contract._issue_health_telemetry_reader(node, entry=entry)

    assert driver_registry.health_telemetry_spec_for_reader(directly_issued) is None
    assert not hasattr(driver_registry, "_register_health_telemetry_reader"), (
        "canonical registry provenance must be minted only inside validated construction"
    )
    with pytest.raises(TypeError, match="registry-issued"):
        ReaderPoolHealthAuthority((directly_issued,))


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


@pytest.mark.parametrize("start_time_s", [1e308, float(2**52 - 1024)])
def test_registry_rejects_clock_ranges_that_collapse_distinct_cadence_ticks(start_time_s: float) -> None:
    with pytest.raises(driver_registry.DriverRegistryError, match=r"health_nodes\[0\]\.start_time_s"):
        driver_registry.validate_health_telemetry_entry(
            _health_configuration(start_time_s=start_time_s),
            path="health_nodes[0]",
        )


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"cadence_hz": 0.0}, "cadence_hz"),
        ({"cadence_hz": -1.0}, "cadence_hz"),
        ({"stale_after_s": 0.0}, "stale_after_s"),
        ({"stale_after_s": 1.0, "disconnected_after_s": 1.0}, "disconnected_after_s"),
        ({"stale_after_s": 2.0, "disconnected_after_s": 1.0}, "disconnected_after_s"),
    ],
)
def test_health_validation_rejects_invalid_semantics_before_construction(
    overrides: dict[str, object],
    field: str,
) -> None:
    with pytest.raises(driver_registry.DriverRegistryError, match=rf"health_nodes\[0\]\.{field}"):
        driver_registry.validate_health_telemetry_entry(
            _health_configuration(**overrides),
            path="health_nodes[0]",
        )


def test_registry_rejects_unknown_health_type() -> None:
    factory = getattr(driver_registry, "construct_health_telemetry_reader", None)
    assert callable(factory), "driver registry must construct allowlisted health telemetry readers"
    with pytest.raises(driver_registry.UnknownDriverTypeError, match="unknown health telemetry type"):
        driver_registry.validate_health_telemetry_entry(
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
    from PySide6.QtWidgets import QApplication

    application = QApplication.instance() or QApplication([])
    reader = _registry_reader(heartbeat_frames=20_000)
    authority = ReaderPoolHealthAuthority((reader,))
    receipt_count = len(driver_registry._HEALTH_TELEMETRY_BINDINGS)
    before_tasks = set(asyncio.all_tasks())
    before_queues = sum(isinstance(value, asyncio.Queue) for value in gc.get_objects())
    before_widgets = len(application.allWidgets())

    for index in range(128):
        observed = 10.0 + index * 0.5
        authority.presample(observed_time_s=observed)
        receipt = authority.snapshot_for_cut(_cut(index + 1, observed))
        assert receipt.availability is AuthorityAvailability.AVAILABLE

    gc.collect()
    tracemalloc.start()
    baseline_current, _baseline_peak = tracemalloc.get_traced_memory()
    tracemalloc.reset_peak()
    receipt = None
    for index in range(128, 10_128):
        observed = 10.0 + index * 0.5
        authority.presample(observed_time_s=observed)
        receipt = authority.snapshot_for_cut(_cut(index + 1, observed))
    assert receipt is not None and len(receipt.nodes) == 1
    del receipt
    gc.collect()
    final_current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    after_queues = sum(isinstance(value, asyncio.Queue) for value in gc.get_objects())
    after_widgets = len(application.allWidgets())
    cached = object.__getattribute__(authority, "_cached")
    retained_readers = object.__getattribute__(authority, "_readers")
    retained_sources = object.__getattribute__(authority, "_last_sources")

    assert set(asyncio.all_tasks()) == before_tasks
    assert after_queues == before_queues
    assert after_widgets == before_widgets
    assert len(driver_registry._HEALTH_TELEMETRY_BINDINGS) == receipt_count
    assert len(retained_readers) == 1
    assert len(retained_sources) == 1
    assert cached is not None and len(cached.snapshots) == len(cached.source_evidence) == 1
    assert final_current - baseline_current <= 65_536, (baseline_current, final_current)
    assert peak - baseline_current <= 524_288, (baseline_current, peak)
