"""Semantic probes for the cached F36.4 infrastructure authority."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from cryodaq.engine_wiring.operator_snapshot_authorities import AuthorityAvailability, CommonCut
from cryodaq.health.contract import (
    HealthAlarm,
    HealthAlarmSeverity,
    HealthDeviceDescriptor,
    HealthMetric,
    HealthMetricDescriptor,
    HealthMetricKind,
    HealthQuality,
    HealthTelemetrySnapshot,
    StaticHealthTelemetryAllowlistEntry,
    issue_health_telemetry_reader,
)
from cryodaq.health.infra_authority import ReaderPoolHealthAuthority, SimulatorHealthAuthority
from cryodaq.health.simulator import DeterministicFleetHealthSimulator
from cryodaq.operator_snapshot import OperatorPresentationState

NOW = datetime(2026, 7, 14, tzinfo=UTC)


def cut(generation: int = 1, when: datetime = NOW) -> CommonCut:
    return CommonCut(generation, f"cut-v1:{generation}:{'a' * 64}", when)


class Device:
    __slots__ = ("_alarms", "_calls", "_descriptor", "_metrics", "_raise", "_revision")

    def __init__(self, device_id: str = "rack.health.01", *, alarms=(), metrics=(), revision=1, raises=False):
        self._descriptor = HealthDeviceDescriptor(device_id, "support_node", "test/v1")
        self._alarms = alarms
        self._metrics = metrics
        self._revision = revision
        self._raise = raises
        self._calls = 0

    @property
    def health_descriptor(self):
        return self._descriptor

    def read_health_snapshot(self, *, observed_time_s: float):
        self._calls += 1
        if self._raise:
            raise RuntimeError("reader blocked or failed")
        return HealthTelemetrySnapshot(
            self._descriptor,
            self._revision,
            observed_time_s,
            observed_time_s,
            "running",
            self._metrics,
            self._alarms,
        )


def reader(device: Device):
    entry = StaticHealthTelemetryAllowlistEntry(device.health_descriptor.device_id, type(device))
    return issue_health_telemetry_reader(device, entry=entry)


def metric(quality: HealthQuality):
    descriptor = HealthMetricDescriptor(
        "health.temperature", HealthMetricKind.QUANTITY, "K", "device_health", "Infrastructure"
    )
    return HealthMetric(descriptor, 4.2, quality, NOW.timestamp())


def alarm(severity: HealthAlarmSeverity):
    return HealthAlarm("health.cooling", severity, True, "Cooling degraded", NOW.timestamp())


def test_unissued_structural_reader_is_rejected() -> None:
    class ForgedReader:
        grants_control_authority = False
        descriptor = HealthDeviceDescriptor("rack.forged", "support_node", "test/v1")

        def snapshot(self, *, observed_time_s: float):
            raise AssertionError("must not be sampled")

    with pytest.raises(TypeError, match="factory-issued"):
        ReaderPoolHealthAuthority([ForgedReader()])


def test_snapshot_cut_never_polls_and_presample_exception_is_unavailable() -> None:
    device = Device(raises=True)
    authority = ReaderPoolHealthAuthority([reader(device)])
    initial = authority.snapshot_for_cut(cut())
    assert device._calls == 0
    authority.presample(observed_time_s=NOW.timestamp())
    assert device._calls == 1
    failed = authority.snapshot_for_cut(cut())

    for receipt in (initial, failed):
        assert receipt.availability is AuthorityAvailability.UNAVAILABLE
        assert receipt.unavailable_reason == "infrastructure_authority_unavailable"
        assert receipt.nodes == ()


@pytest.mark.parametrize(
    ("severity", "expected"),
    [
        (HealthAlarmSeverity.CAUTION, OperatorPresentationState.CAUTION),
        (HealthAlarmSeverity.WARNING, OperatorPresentationState.WARNING),
        (HealthAlarmSeverity.FAULT, OperatorPresentationState.FAULT),
    ],
)
def test_alarm_severity_is_not_downgraded(severity, expected) -> None:
    authority = ReaderPoolHealthAuthority([reader(Device(alarms=(alarm(severity),)))])
    authority.presample(observed_time_s=NOW.timestamp())
    node = authority.snapshot_for_cut(cut()).nodes[0]
    assert node.state is expected
    assert node.reason_code == f"health_alarm_{severity.value}"


@pytest.mark.parametrize(
    ("quality", "expected"),
    [
        (HealthQuality.DEGRADED, OperatorPresentationState.CAUTION),
        (HealthQuality.FAULT, OperatorPresentationState.FAULT),
        (HealthQuality.UNKNOWN, OperatorPresentationState.STALE),
    ],
)
def test_metric_quality_is_conservative(quality, expected) -> None:
    authority = ReaderPoolHealthAuthority([reader(Device(metrics=(metric(quality),)))])
    authority.presample(observed_time_s=NOW.timestamp())
    assert authority.snapshot_for_cut(cut()).nodes[0].state is expected


def test_cached_freshness_ages_at_cut_without_polling() -> None:
    device = Device()
    authority = ReaderPoolHealthAuthority([reader(device)])
    authority.presample(observed_time_s=NOW.timestamp())

    fresh = authority.snapshot_for_cut(cut())
    stale = authority.snapshot_for_cut(cut(2, NOW + timedelta(seconds=2)))
    disconnected = authority.snapshot_for_cut(cut(3, NOW + timedelta(seconds=10)))

    assert device._calls == 1
    assert fresh.nodes[0].state is OperatorPresentationState.OK
    assert stale.nodes[0].state is OperatorPresentationState.STALE
    assert stale.nodes[0].reason_code == "health_stale"
    assert disconnected.nodes[0].state is OperatorPresentationState.DISCONNECTED
    assert disconnected.nodes[0].reason_code == "health_disconnected"
    assert len({fresh.token, stale.token, disconnected.token}) == 3


def test_duplicate_reader_identity_is_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate device identities"):
        ReaderPoolHealthAuthority([reader(Device()), reader(Device())])


def test_token_binds_cut_and_source_revision() -> None:
    device = Device()
    authority = ReaderPoolHealthAuthority([reader(device)])
    authority.presample(observed_time_s=NOW.timestamp())
    first = authority.snapshot_for_cut(cut())
    other_cut = authority.snapshot_for_cut(cut(2, NOW + timedelta(seconds=1)))
    device._revision = 2
    authority.presample(observed_time_s=(NOW + timedelta(seconds=1)).timestamp())
    next_source = authority.snapshot_for_cut(cut(3, NOW + timedelta(seconds=1)))
    assert len({first.token, other_cut.token, next_source.token}) == 3
    assert (first.revision, next_source.revision) == (1, 2)


def test_source_revision_replay_invalidates_cached_authority() -> None:
    authority = ReaderPoolHealthAuthority([reader(Device())])
    authority.presample(observed_time_s=NOW.timestamp())
    assert authority.snapshot_for_cut(cut()).availability is AuthorityAvailability.AVAILABLE
    authority.presample(observed_time_s=(NOW + timedelta(seconds=1)).timestamp())
    replay = authority.snapshot_for_cut(cut(2, NOW + timedelta(seconds=1)))
    assert replay.availability is AuthorityAvailability.UNAVAILABLE
    assert replay.unavailable_reason == "infrastructure_authority_unavailable"


def test_simulator_is_exact_typed_and_pre_sampled() -> None:
    with pytest.raises(TypeError, match="exact DeterministicFleetHealthSimulator"):
        SimulatorHealthAuthority(object())
    authority = SimulatorHealthAuthority(DeterministicFleetHealthSimulator(seed=36))
    assert authority.snapshot_for_cut(cut()).availability is AuthorityAvailability.UNAVAILABLE
    authority.presample()
    assert len(authority.snapshot_for_cut(cut()).nodes) == 100
    assert authority.grants_control_authority is False
