from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

import cryodaq.health as health_package
import cryodaq.health.contract as health_contract
from cryodaq.health.contract import (
    MAX_ALARMS_PER_DEVICE,
    MAX_METRICS_PER_DEVICE,
    HealthAlarm,
    HealthAlarmSeverity,
    HealthDeviceDescriptor,
    HealthFreshness,
    HealthMetric,
    HealthMetricDescriptor,
    HealthMetricKind,
    HealthQuality,
    HealthTelemetryError,
    HealthTelemetryReader,
    HealthTelemetrySnapshot,
    StaticHealthTelemetryAllowlistEntry,
    issue_health_telemetry_reader,
)


def _metric_descriptor(
    metric_id: str = "health.temperature",
    *,
    kind: HealthMetricKind = HealthMetricKind.QUANTITY,
) -> HealthMetricDescriptor:
    units = {
        HealthMetricKind.QUANTITY: "K",
        HealthMetricKind.COUNTER: "count",
        HealthMetricKind.CONDITION: "bool",
        HealthMetricKind.STATE: "state",
    }
    return HealthMetricDescriptor(
        metric_id=metric_id,
        kind=kind,
        unit=units[kind],
        role="device_health",
        display_group="Infrastructure",
    )


def _metric(
    metric_id: str = "health.temperature",
    *,
    kind: HealthMetricKind = HealthMetricKind.QUANTITY,
    value: object = 4.2,
    source_time_s: float = 10.0,
) -> HealthMetric:
    return HealthMetric(
        descriptor=_metric_descriptor(metric_id, kind=kind),
        value=value,  # type: ignore[arg-type]
        quality=HealthQuality.OK,
        source_time_s=source_time_s,
    )


def _alarm(alarm_id: str = "health.cooling") -> HealthAlarm:
    return HealthAlarm(
        alarm_id=alarm_id,
        severity=HealthAlarmSeverity.WARNING,
        active=True,
        message="Cooling degraded",
        source_time_s=10.0,
    )


class PassiveFixtureDevice:
    __slots__ = ("_counter", "_health_descriptor", "_heartbeat_offset", "_revision")

    def __init__(self) -> None:
        self._health_descriptor = HealthDeviceDescriptor(
            device_id="rack.health.01",
            component_type="support_node",
            provenance="fixture/v1",
            stale_after_s=1.0,
            disconnected_after_s=5.0,
        )
        self._revision = 0
        self._counter = 0
        self._heartbeat_offset = 0.0

    @property
    def health_descriptor(self) -> HealthDeviceDescriptor:
        return self._health_descriptor

    def read_health_snapshot(self, *, observed_time_s: float) -> HealthTelemetrySnapshot:
        self._revision += 1
        self._counter += 1
        return HealthTelemetrySnapshot(
            descriptor=self.health_descriptor,
            revision=self._revision,
            observed_time_s=observed_time_s,
            heartbeat_time_s=observed_time_s - self._heartbeat_offset,
            mode="running",
            metrics=(
                _metric(
                    "health.cycles",
                    kind=HealthMetricKind.COUNTER,
                    value=self._counter,
                    source_time_s=observed_time_s,
                ),
            ),
        )


def _issue(device: PassiveFixtureDevice):
    return issue_health_telemetry_reader(
        device,
        entry=StaticHealthTelemetryAllowlistEntry(
            device_id="rack.health.01",
            implementation_type=PassiveFixtureDevice,
        ),
    )


def test_snapshot_detaches_mutable_aliases_and_is_deeply_immutable() -> None:
    metrics = (_metric(),)
    alarms = (_alarm(),)
    snapshot = HealthTelemetrySnapshot(
        descriptor=HealthDeviceDescriptor("rack.health.01", "support_node", "fixture/v1"),
        revision=1,
        observed_time_s=10.0,
        heartbeat_time_s=10.0,
        mode="running",
        metrics=metrics,
        alarms=alarms,
    )
    assert len(snapshot.metrics) == len(snapshot.alarms) == 1
    assert snapshot.freshness is HealthFreshness.FRESH
    assert snapshot.grants_control_authority is False
    with pytest.raises(FrozenInstanceError):
        snapshot.mode = "stopped"  # type: ignore[misc]


def test_snapshot_rejects_mutable_and_unbounded_iterables_without_consuming_them() -> None:
    descriptor = HealthDeviceDescriptor("rack.health.01", "support_node", "fixture/v1")
    with pytest.raises(TypeError, match="exact bounded tuple"):
        HealthTelemetrySnapshot(descriptor, 1, 10.0, 10.0, "running", [_metric()])  # type: ignore[arg-type]

    class InfiniteMetrics:
        def __init__(self) -> None:
            self.consumed = 0

        def __iter__(self):
            while True:
                self.consumed += 1
                yield _metric(f"metric.{self.consumed}")

    infinite = InfiniteMetrics()
    with pytest.raises(TypeError, match="exact bounded tuple"):
        HealthTelemetrySnapshot(descriptor, 1, 10.0, 10.0, "running", infinite)  # type: ignore[arg-type]
    assert infinite.consumed == 0
    assert infinite.consumed <= MAX_METRICS_PER_DEVICE + 1


def test_snapshot_rejects_subclassed_nested_contract_values() -> None:
    class DescriptorSubclass(HealthDeviceDescriptor):
        __slots__ = ()

    class MetricDescriptorSubclass(HealthMetricDescriptor):
        __slots__ = ()

    class MetricSubclass(HealthMetric):
        __slots__ = ()

    class AlarmSubclass(HealthAlarm):
        __slots__ = ()

    descriptor = HealthDeviceDescriptor("rack.health.01", "support_node", "fixture/v1")
    with pytest.raises(TypeError, match="exact HealthDeviceDescriptor"):
        HealthTelemetrySnapshot(DescriptorSubclass("rack.health.01", "support_node", "fixture/v1"), 1, 10, 10, "x")
    with pytest.raises(TypeError, match="exact HealthMetricDescriptor"):
        HealthMetric(
            MetricDescriptorSubclass("health.temperature", HealthMetricKind.QUANTITY, "K", "health", "Health"),
            1.0,
            HealthQuality.OK,
            10.0,
        )
    with pytest.raises(TypeError, match="exact HealthMetric"):
        metric = MetricSubclass(_metric().descriptor, 1.0, HealthQuality.OK, 10)
        HealthTelemetrySnapshot(descriptor, 1, 10, 10, "x", (metric,))
    with pytest.raises(TypeError, match="exact HealthAlarm"):
        HealthTelemetrySnapshot(
            descriptor,
            1,
            10,
            10,
            "x",
            (),
            (AlarmSubclass("health.cooling", HealthAlarmSeverity.WARNING, True, "fault", 10),),
        )


@pytest.mark.parametrize(
    ("offset", "expected"),
    [
        (0.0, HealthFreshness.FRESH),
        (1.0, HealthFreshness.FRESH),
        (1.01, HealthFreshness.STALE),
        (5.0, HealthFreshness.STALE),
        (5.01, HealthFreshness.DISCONNECTED),
    ],
)
def test_freshness_is_derived_at_exact_boundaries(offset: float, expected: HealthFreshness) -> None:
    snapshot = HealthTelemetrySnapshot(
        descriptor=HealthDeviceDescriptor("rack.health.01", "support_node", "fixture/v1"),
        revision=1,
        observed_time_s=10.0,
        heartbeat_time_s=10.0 - offset,
        mode="running",
    )

    assert snapshot.freshness is expected


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_quantities_are_rejected(value: float) -> None:
    with pytest.raises((HealthTelemetryError, TypeError), match="finite number"):
        _metric(value=value)


def test_signed_finite_quantities_are_supported() -> None:
    assert _metric(value=-40.0).value == -40.0


@pytest.mark.parametrize(
    ("kind", "value", "message"),
    [
        (HealthMetricKind.STATE, "x" * 65, "1..64"),
        (HealthMetricKind.CONDITION, 1, "boolean"),
        (HealthMetricKind.COUNTER, True, "integer"),
    ],
)
def test_typed_metric_values_are_exact_and_bounded(
    kind: HealthMetricKind,
    value: object,
    message: str,
) -> None:
    with pytest.raises(HealthTelemetryError, match=message):
        _metric(kind=kind, value=value)


def test_snapshot_rejects_oversize_duplicate_and_future_inputs() -> None:
    descriptor = HealthDeviceDescriptor("rack.health.01", "support_node", "fixture/v1")
    with pytest.raises(HealthTelemetryError, match="duplicate metric"):
        HealthTelemetrySnapshot(descriptor, 1, 10.0, 10.0, "running", (_metric(), _metric()))
    with pytest.raises(HealthTelemetryError, match="duplicate alarm"):
        HealthTelemetrySnapshot(descriptor, 1, 10.0, 10.0, "running", (), (_alarm(), _alarm()))
    with pytest.raises(HealthTelemetryError, match="exceeds"):
        HealthTelemetrySnapshot(
            descriptor,
            1,
            10.0,
            10.0,
            "running",
            tuple(_metric(f"metric.{index}") for index in range(MAX_METRICS_PER_DEVICE + 1)),
        )
    with pytest.raises(HealthTelemetryError, match="exceeds"):
        HealthTelemetrySnapshot(
            descriptor,
            1,
            10.0,
            10.0,
            "running",
            (),
            tuple(_alarm(f"alarm.{index}") for index in range(MAX_ALARMS_PER_DEVICE + 1)),
        )
    with pytest.raises(HealthTelemetryError, match="future"):
        HealthTelemetrySnapshot(descriptor, 1, 10.0, 10.01, "running")
    with pytest.raises(HealthTelemetryError, match="future"):
        HealthTelemetrySnapshot(descriptor, 1, 10.0, 10.0, "running", (_metric(source_time_s=10.01),))


def test_static_issuance_rejects_subclasses_callables_identity_mismatch_and_actions() -> None:
    class Subclass(PassiveFixtureDevice):
        pass

    class CallableFixture(PassiveFixtureDevice):
        def __call__(self) -> None:
            raise AssertionError("must never be invoked")

    class DangerousFixture(PassiveFixtureDevice):
        def reset_device(self) -> None:
            raise AssertionError("must never be available")

    entry = StaticHealthTelemetryAllowlistEntry("rack.health.01", PassiveFixtureDevice)
    with pytest.raises(HealthTelemetryError, match="exact allowlisted"):
        issue_health_telemetry_reader(Subclass(), entry=entry)
    with pytest.raises(HealthTelemetryError, match="exact allowlisted"):
        issue_health_telemetry_reader(CallableFixture(), entry=entry)
    mismatched = PassiveFixtureDevice()
    mismatched._health_descriptor = HealthDeviceDescriptor("rack.health.02", "support_node", "fixture/v1")
    with pytest.raises(HealthTelemetryError, match="identity"):
        issue_health_telemetry_reader(mismatched, entry=entry)
    with pytest.raises(HealthTelemetryError, match="exact public surface.*reset_device"):
        StaticHealthTelemetryAllowlistEntry("rack.health.01", DangerousFixture)
    with pytest.raises(HealthTelemetryError, match="exact public surface.*__call__"):
        StaticHealthTelemetryAllowlistEntry("rack.health.01", CallableFixture)


def test_allowlist_rejects_inherited_call_dynamic_storage_and_full_control_vocabulary() -> None:
    class CallableBase:
        __slots__ = ()

        def __call__(self) -> None:
            raise AssertionError("must never be invoked")

        def send_packet(self) -> None:
            raise AssertionError("must never be available")

    class InheritedCallable(CallableBase):
        __slots__ = ()

    class DynamicStorage:
        pass

    with pytest.raises(HealthTelemetryError, match="__call__"):
        StaticHealthTelemetryAllowlistEntry("rack.health.01", InheritedCallable)
    with pytest.raises(HealthTelemetryError, match="instance __dict__"):
        StaticHealthTelemetryAllowlistEntry("rack.health.01", DynamicStorage)

    for action_name in (
        "network_discovery",
        "actuate",
        "write_output",
        "enable",
        "disable",
        "open",
        "close",
        "frobnicate",
        "start_device",
        "stop_device",
        "reset_device",
        "vent_line",
        "purge_line",
        "set_value",
        "remediate_fault",
        "discover_nodes",
        "api_credentials",
        "register_callback",
        "send_packet",
        "control_output",
    ):
        implementation = type(
            f"Forbidden_{action_name}",
            (),
            {"__slots__": (), action_name: lambda self: None},
        )
        with pytest.raises(HealthTelemetryError, match=action_name):
            StaticHealthTelemetryAllowlistEntry("rack.health.01", implementation)


def test_allowlist_accepts_private_helpers_but_no_additional_public_data_or_callable() -> None:
    class PrivateHelperFixture(PassiveFixtureDevice):
        __slots__ = ()

        def _diagnose_locally(self) -> str:
            return "passive"

    entry = StaticHealthTelemetryAllowlistEntry("rack.health.01", PrivateHelperFixture)
    reader = issue_health_telemetry_reader(PrivateHelperFixture(), entry=entry)
    assert reader.snapshot(observed_time_s=10.0).revision == 1

    class PublicDataFixture(PassiveFixtureDevice):
        __slots__ = ()
        vendor_label = "benign-looking but outside the exact contract"

    with pytest.raises(HealthTelemetryError, match="exact public surface.*vendor_label"):
        StaticHealthTelemetryAllowlistEntry("rack.health.01", PublicDataFixture)


def test_allowlist_requires_an_exact_read_only_descriptor_property() -> None:
    class MutableDescriptorFixture(PassiveFixtureDevice):
        __slots__ = ()

        @PassiveFixtureDevice.health_descriptor.setter
        def health_descriptor(self, value: HealthDeviceDescriptor) -> None:
            self._health_descriptor = value

    with pytest.raises(HealthTelemetryError, match="exact read-only property"):
        StaticHealthTelemetryAllowlistEntry("rack.health.01", MutableDescriptorFixture)


def test_issuance_rechecks_class_and_instance_surface_after_entry_creation() -> None:
    class InitiallyPassiveFixture(PassiveFixtureDevice):
        __slots__ = ()

    entry = StaticHealthTelemetryAllowlistEntry("rack.health.01", InitiallyPassiveFixture)
    device = InitiallyPassiveFixture()

    InitiallyPassiveFixture.network_discovery = lambda self: None  # type: ignore[attr-defined]
    with pytest.raises(HealthTelemetryError, match="exact public surface.*network_discovery"):
        issue_health_telemetry_reader(device, entry=entry)


def test_issued_reader_pins_bound_snapshot_method_against_later_class_replacement() -> None:
    class ReplaceableFixture(PassiveFixtureDevice):
        __slots__ = ()

    entry = StaticHealthTelemetryAllowlistEntry("rack.health.01", ReplaceableFixture)
    reader = issue_health_telemetry_reader(ReplaceableFixture(), entry=entry)

    def replacement(self: ReplaceableFixture, *, observed_time_s: float) -> HealthTelemetrySnapshot:
        raise AssertionError("later class mutation must not replace the issued read capability")

    ReplaceableFixture.read_health_snapshot = replacement
    assert reader.snapshot(observed_time_s=10.0).revision == 1


def test_issued_reader_exposes_no_control_callback_credential_or_discovery_surface() -> None:
    reader = _issue(PassiveFixtureDevice())

    assert reader.grants_control_authority is False
    assert reader.snapshot(observed_time_s=10.0).revision == 1
    for name in (
        "start",
        "stop",
        "reset",
        "vent",
        "purge",
        "set",
        "remediate",
        "register_callback",
        "credentials",
        "discover",
    ):
        assert not hasattr(reader, name)
    assert isinstance(reader, HealthTelemetryReader)
    assert type(reader).__name__ == "_IssuedHealthTelemetryReader"
    assert not hasattr(reader, "__dict__")
    assert {name for name in dir(reader) if not name.startswith("_")} == {
        "descriptor",
        "grants_control_authority",
        "snapshot",
    }
    with pytest.raises(TypeError, match="sealed"):

        class ReaderSubclass(type(reader)):
            pass


def test_reader_is_not_publicly_exported_and_package_surface_is_exact() -> None:
    assert not hasattr(health_package, "IssuedHealthTelemetryReader")
    assert set(health_package.__all__) == {
        "HEALTH_IMPLEMENTATION_PUBLIC_SURFACE",
        "DeterministicFleetHealthSimulator",
        "FleetHealthFrame",
        "FleetHealthSummary",
        "HealthAlarm",
        "HealthAlarmSeverity",
        "HealthDeviceDescriptor",
        "HealthFreshness",
        "HealthMetric",
        "HealthMetricDescriptor",
        "HealthMetricKind",
        "HealthQuality",
        "HealthTelemetryDevice",
        "HealthTelemetryError",
        "HealthTelemetryReader",
        "HealthTelemetrySnapshot",
        "StaticHealthTelemetryAllowlistEntry",
        "estimate_fleet_frame_payload_bytes",
        "issue_health_telemetry_reader",
    }


def test_reader_rejects_direct_arbitrary_callable_and_unissued_shell_attacks() -> None:
    reader_type = health_contract._IssuedHealthTelemetryReader
    side_effects: list[str] = []

    def control_side_effect(*, observed_time_s: float) -> HealthTelemetrySnapshot:
        side_effects.append(f"vent:{observed_time_s}")
        raise AssertionError("control side effect must never run")

    descriptor = HealthDeviceDescriptor("rack.health.01", "support_node", "fixture/v1")
    with pytest.raises(TypeError, match="factory-issued only"):
        reader_type(control_side_effect, descriptor)
    with pytest.raises(TypeError, match="factory-issued only"):
        reader_type()

    shell = object.__new__(reader_type)
    with pytest.raises(TypeError, match="was not issued"):
        shell.snapshot(observed_time_s=10.0)
    with pytest.raises(TypeError, match="was not issued"):
        _ = shell.descriptor
    with pytest.raises(TypeError, match="was not issued"):
        _ = shell.grants_control_authority
    assert side_effects == []


def test_issued_reader_rejects_callable_or_descriptor_rebinding() -> None:
    reader = _issue(PassiveFixtureDevice())
    side_effects: list[str] = []

    def control_side_effect(*, observed_time_s: float) -> HealthTelemetrySnapshot:
        side_effects.append(f"open:{observed_time_s}")
        raise AssertionError("control side effect must never run")

    with pytest.raises(TypeError, match="state is sealed"):
        reader._read_snapshot = control_side_effect  # type: ignore[attr-defined]
    with pytest.raises(TypeError, match="state is sealed"):
        reader._descriptor = HealthDeviceDescriptor("forged", "control", "forged")  # type: ignore[attr-defined]
    assert reader.snapshot(observed_time_s=10.0).revision == 1
    assert side_effects == []


def test_private_issuer_rejects_forged_owner_and_cross_entry_tokens() -> None:
    reader_type = health_contract._IssuedHealthTelemetryReader
    device = PassiveFixtureDevice()
    entry = StaticHealthTelemetryAllowlistEntry("rack.health.01", PassiveFixtureDevice)
    other_entry = StaticHealthTelemetryAllowlistEntry("rack.health.01", PassiveFixtureDevice)
    method = device.read_health_snapshot

    with pytest.raises(TypeError, match="issuer is not authorized"):
        reader_type._issue_from_allowlist(
            issuer_key=object(),
            entry=entry,
            entry_token=entry._issuance_token,
            read_snapshot=method,
            descriptor=device.health_descriptor,
        )
    with pytest.raises(TypeError, match="token does not match"):
        reader_type._issue_from_allowlist(
            issuer_key=health_contract._HEALTH_READER_ISSUER_KEY,
            entry=entry,
            entry_token=other_entry._issuance_token,
            read_snapshot=method,
            descriptor=device.health_descriptor,
        )


def test_issued_reader_pins_exact_descriptor_and_rejects_later_candidate_swap() -> None:
    device = PassiveFixtureDevice()
    reader = _issue(device)
    issued = reader.descriptor
    device._health_descriptor = HealthDeviceDescriptor(
        "rack.health.01",
        "replacement_node",
        "fixture/replaced",
    )

    assert reader.descriptor is issued
    with pytest.raises(HealthTelemetryError, match="descriptor does not match issued"):
        reader.snapshot(observed_time_s=10.0)


def test_issued_reader_rejects_revision_time_heartbeat_and_counter_regressions() -> None:
    device = PassiveFixtureDevice()
    reader = _issue(device)
    reader.snapshot(observed_time_s=10.0)

    device._revision = -1
    with pytest.raises(HealthTelemetryError, match="revision"):
        reader.snapshot(observed_time_s=10.5)
    device._revision = 1
    with pytest.raises(HealthTelemetryError, match="observed_time_s regressed"):
        reader.snapshot(observed_time_s=9.0)
    device._revision = 2
    device._heartbeat_offset = 2.0
    with pytest.raises(HealthTelemetryError, match="heartbeat_time_s regressed"):
        reader.snapshot(observed_time_s=10.5)
    device._revision = 3
    device._heartbeat_offset = 0.0
    device._counter = -1
    with pytest.raises(HealthTelemetryError, match="counter.*regressed"):
        reader.snapshot(observed_time_s=11.0)


def test_failed_read_does_not_mutate_reader_authority_cut() -> None:
    device = PassiveFixtureDevice()
    reader = _issue(device)
    assert reader.snapshot(observed_time_s=10.0).revision == 1
    device._revision = -1
    with pytest.raises(HealthTelemetryError):
        reader.snapshot(observed_time_s=10.5)
    device._revision = 1
    assert reader.snapshot(observed_time_s=11.0).revision == 2


class MutableMetricSchemaFixture:
    __slots__ = ("_alarms", "_health_descriptor", "_metrics", "_revision")

    def __init__(self) -> None:
        self._health_descriptor = HealthDeviceDescriptor(
            device_id="rack.health.schema",
            component_type="support_node",
            provenance="schema-fixture/v1",
        )
        self._revision = 0
        self._metrics: tuple[HealthMetric, ...] = ()
        self._alarms: tuple[HealthAlarm, ...] = ()

    @property
    def health_descriptor(self) -> HealthDeviceDescriptor:
        return self._health_descriptor

    def read_health_snapshot(self, *, observed_time_s: float) -> HealthTelemetrySnapshot:
        self._revision += 1
        metrics = tuple(
            HealthMetric(
                descriptor=metric.descriptor,
                value=metric.value,
                quality=metric.quality,
                source_time_s=observed_time_s,
            )
            for metric in self._metrics
        )
        alarms = tuple(
            HealthAlarm(
                alarm_id=alarm.alarm_id,
                severity=alarm.severity,
                active=alarm.active,
                message=alarm.message,
                source_time_s=observed_time_s,
            )
            for alarm in self._alarms
        )
        return HealthTelemetrySnapshot(
            descriptor=self.health_descriptor,
            revision=self._revision,
            observed_time_s=observed_time_s,
            heartbeat_time_s=observed_time_s,
            mode="running",
            metrics=metrics,
            alarms=alarms,
        )


def _issue_schema_fixture(device: MutableMetricSchemaFixture) -> HealthTelemetryReader:
    return issue_health_telemetry_reader(
        device,
        entry=StaticHealthTelemetryAllowlistEntry(
            device_id="rack.health.schema",
            implementation_type=MutableMetricSchemaFixture,
        ),
    )


def _schema_metric(
    metric_id: str,
    *,
    kind: HealthMetricKind,
    value: object,
    unit: str | None = None,
    role: str = "device_health",
    display_group: str = "Infrastructure",
) -> HealthMetric:
    descriptor = _metric_descriptor(metric_id, kind=kind)
    descriptor = HealthMetricDescriptor(
        metric_id=descriptor.metric_id,
        kind=descriptor.kind,
        unit=unit or descriptor.unit,
        role=role,
        display_group=display_group,
    )
    return HealthMetric(descriptor, value, HealthQuality.OK, 0.0)  # type: ignore[arg-type]


def test_reader_pins_bounded_metric_schema_and_rejects_rotating_ids_without_growth() -> None:
    device = MutableMetricSchemaFixture()
    device._metrics = (
        _schema_metric("health.cycles", kind=HealthMetricKind.COUNTER, value=1),
        _schema_metric("health.temperature", kind=HealthMetricKind.QUANTITY, value=4.2),
    )
    reader = _issue_schema_fixture(device)
    accepted = reader.snapshot(observed_time_s=1.0)
    reader_type = type(reader)
    pinned_schema = object.__getattribute__(reader, "_metric_schema")
    pinned_counters = object.__getattribute__(reader, "_counter_values")

    assert accepted.revision == 1
    assert len(pinned_schema) == 2
    assert pinned_counters == {"health.cycles": 1}

    for index in range(10_000):
        device._metrics = (
            _schema_metric(f"health.rotating.{index}", kind=HealthMetricKind.COUNTER, value=index + 2),
            _schema_metric("health.temperature", kind=HealthMetricKind.QUANTITY, value=5.0),
        )
        with pytest.raises(HealthTelemetryError, match="metric schema changed"):
            reader.snapshot(observed_time_s=2.0 + index)

        assert object.__getattribute__(reader, "_metric_schema") is pinned_schema
        assert object.__getattribute__(reader, "_counter_values") is pinned_counters
        assert object.__getattribute__(reader, "_last_revision") == 1
        assert object.__getattribute__(reader, "_last_observed") == 1.0
        assert object.__getattribute__(reader, "_last_heartbeat") == 1.0
        assert len(object.__getattribute__(reader, "_counter_values")) <= len(pinned_schema) <= MAX_METRICS_PER_DEVICE

    assert reader_type.__name__ == "_IssuedHealthTelemetryReader"

    device._metrics = (
        _schema_metric("health.cycles", kind=HealthMetricKind.COUNTER, value=2),
        _schema_metric("health.temperature", kind=HealthMetricKind.QUANTITY, value=-40.0),
    )
    recovered = reader.snapshot(observed_time_s=10_003.0)
    assert recovered.revision == 10_002
    assert recovered.metrics[0].value == 2
    assert recovered.metrics[1].value == -40.0
    assert object.__getattribute__(reader, "_counter_values") == {"health.cycles": 2}


@pytest.mark.parametrize(
    "metrics",
    [
        (),
        (
            _schema_metric("health.temperature", kind=HealthMetricKind.QUANTITY, value=4.2),
            _schema_metric("health.cycles", kind=HealthMetricKind.COUNTER, value=2),
        ),
        (
            _schema_metric("health.cycles", kind=HealthMetricKind.COUNTER, value=2),
            _schema_metric("health.temperature", kind=HealthMetricKind.QUANTITY, value=4.2),
            _schema_metric("health.extra", kind=HealthMetricKind.QUANTITY, value=1.0),
        ),
        (
            _schema_metric("health.cycles", kind=HealthMetricKind.COUNTER, value=2),
            _schema_metric("health.temperature", kind=HealthMetricKind.QUANTITY, value=4.2, unit="C"),
        ),
        (
            _schema_metric("health.cycles", kind=HealthMetricKind.COUNTER, value=2),
            _schema_metric("health.temperature", kind=HealthMetricKind.STATE, value="warm"),
        ),
        (
            _schema_metric("health.cycles", kind=HealthMetricKind.COUNTER, value=2),
            _schema_metric(
                "health.temperature",
                kind=HealthMetricKind.QUANTITY,
                value=4.2,
                role="thermal_health",
            ),
        ),
        (
            _schema_metric("health.cycles", kind=HealthMetricKind.COUNTER, value=2),
            _schema_metric(
                "health.temperature",
                kind=HealthMetricKind.QUANTITY,
                value=4.2,
                display_group="Thermal",
            ),
        ),
    ],
    ids=("remove", "reorder", "add", "unit", "kind", "role", "display-group"),
)
def test_reader_rejects_every_metric_schema_drift_before_cut_mutation(
    metrics: tuple[HealthMetric, ...],
) -> None:
    device = MutableMetricSchemaFixture()
    device._metrics = (
        _schema_metric("health.cycles", kind=HealthMetricKind.COUNTER, value=1),
        _schema_metric("health.temperature", kind=HealthMetricKind.QUANTITY, value=4.2),
    )
    reader = _issue_schema_fixture(device)
    reader.snapshot(observed_time_s=1.0)
    before = tuple(
        object.__getattribute__(reader, name)
        for name in ("_metric_schema", "_counter_values", "_last_revision", "_last_observed", "_last_heartbeat")
    )

    device._metrics = metrics
    with pytest.raises(HealthTelemetryError, match="metric schema changed"):
        reader.snapshot(observed_time_s=2.0)

    after = tuple(
        object.__getattribute__(reader, name)
        for name in ("_metric_schema", "_counter_values", "_last_revision", "_last_observed", "_last_heartbeat")
    )
    assert after == before


def test_alarm_identities_remain_event_like_and_are_not_retained_by_reader() -> None:
    device = MutableMetricSchemaFixture()
    device._metrics = (_schema_metric("health.temperature", kind=HealthMetricKind.QUANTITY, value=4.2),)
    device._alarms = (_alarm("health.alarm.first"),)
    reader = _issue_schema_fixture(device)

    first = reader.snapshot(observed_time_s=10.0)
    device._alarms = (_alarm("health.alarm.replacement"),)
    second = reader.snapshot(observed_time_s=11.0)

    assert first.alarms[0].alarm_id == "health.alarm.first"
    assert second.alarms[0].alarm_id == "health.alarm.replacement"
    assert not any("alarm" in slot for slot in type(reader).__slots__)
