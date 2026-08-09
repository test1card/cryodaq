"""Passive infrastructure-health contracts and deterministic test support."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cryodaq.drivers.contracts import HealthTelemetryDevice

from cryodaq.health.contract import (
    HEALTH_IMPLEMENTATION_PUBLIC_SURFACE,
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
from cryodaq.health.simulator import (
    DeterministicFleetHealthSimulator,
    FleetHealthFrame,
    FleetHealthSummary,
    estimate_fleet_frame_payload_bytes,
)

__all__ = [
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
]


def __getattr__(name: str) -> Any:
    if name == "HealthTelemetryDevice":
        from cryodaq.drivers.contracts import HealthTelemetryDevice

        globals()[name] = HealthTelemetryDevice
        return HealthTelemetryDevice
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
