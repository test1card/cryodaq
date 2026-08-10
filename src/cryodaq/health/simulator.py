"""Deterministic, manually-clocked fleet health simulator.

The simulator owns no tasks, timers, queues, widgets, sockets, credentials, or
history.  Each call materializes one bounded immutable frame, making it useful
for pure projection and scale tests without pretending to be GUI evidence.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from cryodaq.health.contract import (
    HealthAlarm,
    HealthAlarmSeverity,
    HealthDeviceDescriptor,
    HealthFreshness,
    HealthMetric,
    HealthMetricDescriptor,
    HealthMetricKind,
    HealthQuality,
    HealthTelemetryError,
    HealthTelemetrySnapshot,
)

MAX_SIMULATOR_FRAMES = 2**52
MAX_DETERMINISTIC_HEALTH_NODE_FRAMES = 1_000_000
_ORDINARY_COMPONENT_TYPES = frozenset({"compressor", "pump_station", "cryocooler", "support_node"})
_MAX_SIMULATOR_SEED = 2**63 - 1


def _manual_clock_time(start_time_s: float, cadence_hz: float, zero_based_index: int) -> float:
    """Use the exact timestamp formula shared by admission and frame emission."""

    return start_time_s + zero_based_index / cadence_hz


def _validate_manual_clock_range(
    start_time_s: float,
    cadence_hz: float,
    maximum_frames: int,
) -> None:
    """Reject ranges whose first or bounded-horizon ticks collide."""

    try:
        first = _manual_clock_time(start_time_s, cadence_hz, 0)
        second = _manual_clock_time(start_time_s, cadence_hz, 1)
        penultimate = _manual_clock_time(start_time_s, cadence_hz, maximum_frames - 2)
        final = _manual_clock_time(start_time_s, cadence_hz, maximum_frames - 1)
    except OverflowError as exc:
        raise HealthTelemetryError(
            "start_time_s and cadence_hz must yield finite, distinct simulator ticks"
        ) from exc
    if (
        not all(math.isfinite(value) for value in (first, second, penultimate, final))
        or second <= first
        or final <= penultimate
    ):
        raise HealthTelemetryError("start_time_s and cadence_hz must yield finite, distinct simulator ticks")


@dataclass(frozen=True, slots=True)
class FleetHealthSummary:
    device_count: int
    metric_count: int
    fresh_count: int
    stale_count: int
    disconnected_count: int
    faulted_count: int
    active_alarm_count: int


@dataclass(frozen=True, slots=True)
class FleetHealthFrame:
    revision: int
    observed_time_s: float
    cadence_hz: float
    devices: tuple[HealthTelemetrySnapshot, ...]
    summary: FleetHealthSummary

    @property
    def grants_control_authority(self) -> bool:
        return False


class DeterministicFleetHealthSimulator:
    """Produce repeatable fleet cuts with fixed cardinality and O(fleet) memory."""

    __slots__ = (
        "_cadence_hz",
        "_descriptors",
        "_metric_descriptors",
        "_revision",
        "_seed",
        "_start_time_s",
    )

    grants_control_authority = False

    def __init__(
        self,
        *,
        seed: int = 36,
        device_count: int = 100,
        metrics_per_device: int = 20,
        cadence_hz: float = 2.0,
        start_time_s: float = 10.0,
    ) -> None:
        if type(seed) is not int or not 0 <= seed <= _MAX_SIMULATOR_SEED:
            raise HealthTelemetryError(f"seed must be an integer in [0, {_MAX_SIMULATOR_SEED}]")
        if type(device_count) is not int or not 1 <= device_count <= 1_000:
            raise HealthTelemetryError("device_count must be in [1, 1000]")
        if type(metrics_per_device) is not int or not 1 <= metrics_per_device <= 64:
            raise HealthTelemetryError("metrics_per_device must be in [1, 64]")
        if isinstance(cadence_hz, bool) or not isinstance(cadence_hz, (int, float)):
            raise TypeError("cadence_hz must be a number")
        try:
            cadence = float(cadence_hz)
        except (OverflowError, ValueError) as exc:
            raise HealthTelemetryError("cadence_hz must be a finite representable number") from exc
        if not 0 < cadence <= 2.0:
            raise HealthTelemetryError("human-readable cadence_hz must be in (0, 2]")
        if isinstance(start_time_s, bool) or not isinstance(start_time_s, (int, float)):
            raise TypeError("start_time_s must be a number")
        try:
            start = float(start_time_s)
        except (OverflowError, ValueError) as exc:
            raise HealthTelemetryError("start_time_s must be a finite representable number") from exc
        if not math.isfinite(start) or start < 10.0:
            raise HealthTelemetryError("start_time_s must be finite and >= 10 for deterministic stale cuts")
        _validate_manual_clock_range(start, cadence, MAX_SIMULATOR_FRAMES)

        self._seed = seed
        self._cadence_hz = cadence
        self._start_time_s = start
        self._revision = 0
        component_types = ("compressor", "pump_station", "cryocooler", "support_node")
        self._descriptors = tuple(
            HealthDeviceDescriptor(
                device_id=f"sim.health.{index:04d}",
                component_type=component_types[(index + seed) % len(component_types)],
                provenance=f"deterministic-fleet-simulator/v1;seed={seed}",
                stale_after_s=1.0,
                disconnected_after_s=5.0,
            )
            for index in range(device_count)
        )
        self._metric_descriptors = tuple(
            tuple(self._metric_descriptor(index) for index in range(metrics_per_device))
            for _device in range(device_count)
        )

    @staticmethod
    def _metric_descriptor(index: int) -> HealthMetricDescriptor:
        selector = index % 4
        kind = (
            HealthMetricKind.QUANTITY,
            HealthMetricKind.COUNTER,
            HealthMetricKind.CONDITION,
            HealthMetricKind.STATE,
        )[selector]
        unit = {
            HealthMetricKind.QUANTITY: "arb",
            HealthMetricKind.COUNTER: "count",
            HealthMetricKind.CONDITION: "bool",
            HealthMetricKind.STATE: "state",
        }[kind]
        return HealthMetricDescriptor(
            metric_id=f"health.metric.{index:03d}",
            kind=kind,
            unit=unit,
            role=f"health_role_{index:03d}",
            display_group=f"Health group {index // 5 + 1}",
        )

    @property
    def device_count(self) -> int:
        return len(self._descriptors)

    @property
    def metric_count(self) -> int:
        return sum(len(descriptors) for descriptors in self._metric_descriptors)

    @property
    def cadence_hz(self) -> float:
        return self._cadence_hz

    @property
    def retained_frame_count(self) -> int:
        """The simulator retains no emitted frames or snapshot history."""

        return 0

    def frame(self) -> FleetHealthFrame:
        """Advance the manual clock by one cadence interval and emit one cut."""

        if self._revision >= MAX_SIMULATOR_FRAMES:
            raise HealthTelemetryError("simulator exhausted its bounded frame revision space")
        self._revision += 1
        observed = _manual_clock_time(self._start_time_s, self._cadence_hz, self._revision - 1)
        devices = tuple(
            self._snapshot(device_index, descriptor, observed)
            for device_index, descriptor in enumerate(self._descriptors)
        )
        fresh = sum(device.freshness is HealthFreshness.FRESH for device in devices)
        stale = sum(device.freshness is HealthFreshness.STALE for device in devices)
        disconnected = sum(device.freshness is HealthFreshness.DISCONNECTED for device in devices)
        faulted = sum(any(metric.quality is HealthQuality.FAULT for metric in device.metrics) for device in devices)
        active_alarms = sum(sum(alarm.active for alarm in device.alarms) for device in devices)
        summary = FleetHealthSummary(
            device_count=len(devices),
            metric_count=sum(len(device.metrics) for device in devices),
            fresh_count=fresh,
            stale_count=stale,
            disconnected_count=disconnected,
            faulted_count=faulted,
            active_alarm_count=active_alarms,
        )
        return FleetHealthFrame(
            revision=self._revision,
            observed_time_s=observed,
            cadence_hz=self._cadence_hz,
            devices=devices,
            summary=summary,
        )

    def _snapshot(
        self,
        device_index: int,
        descriptor: HealthDeviceDescriptor,
        observed: float,
    ) -> HealthTelemetrySnapshot:
        stale = device_index % 10 == 0
        faulted = device_index % 50 == 1
        heartbeat = observed - 2.0 if stale else observed
        metrics = tuple(
            self._metric(device_index, metric_index, metric_descriptor, observed, faulted)
            for metric_index, metric_descriptor in enumerate(self._metric_descriptors[device_index])
        )
        alarms = (
            (
                HealthAlarm(
                    alarm_id="simulated.health.fault",
                    severity=HealthAlarmSeverity.FAULT,
                    active=True,
                    message="Deterministic simulated health fault",
                    source_time_s=observed,
                ),
            )
            if faulted
            else ()
        )
        return HealthTelemetrySnapshot(
            descriptor=descriptor,
            revision=self._revision,
            observed_time_s=observed,
            heartbeat_time_s=heartbeat,
            mode="fault" if faulted else "running",
            metrics=metrics,
            alarms=alarms,
        )

    def _metric(
        self,
        device_index: int,
        metric_index: int,
        descriptor: HealthMetricDescriptor,
        observed: float,
        faulted: bool,
    ) -> HealthMetric:
        quality = HealthQuality.FAULT if faulted and metric_index == 0 else HealthQuality.OK
        salt = self._seed + device_index * 17 + metric_index * 31
        if descriptor.kind is HealthMetricKind.QUANTITY:
            value: str | bool | int | float = float((salt % 10_000) + self._revision) / 100.0
        elif descriptor.kind is HealthMetricKind.COUNTER:
            value = salt + self._revision
        elif descriptor.kind is HealthMetricKind.CONDITION:
            value = not faulted
        else:
            value = "fault" if faulted else "nominal"
        return HealthMetric(
            descriptor=descriptor,
            value=value,
            quality=quality,
            source_time_s=observed,
        )


class DeterministicHealthTelemetryNode:
    """One manually-clocked ordinary-lab node with a stoppable heartbeat."""

    __slots__ = (
        "_cadence_hz",
        "_descriptor",
        "_heartbeat_frames",
        "_last_heartbeat_s",
        "_metric_descriptor",
        "_revision",
        "_start_time_s",
    )

    def __init__(
        self,
        *,
        device_id: str,
        component_type: str,
        cadence_hz: float = 2.0,
        start_time_s: float = 10.0,
        heartbeat_frames: int = MAX_DETERMINISTIC_HEALTH_NODE_FRAMES,
        stale_after_s: float = 1.0,
        disconnected_after_s: float = 5.0,
    ) -> None:
        if component_type not in _ORDINARY_COMPONENT_TYPES:
            raise HealthTelemetryError("component_type must be compressor, pump_station, cryocooler, or support_node")
        if isinstance(cadence_hz, bool) or not isinstance(cadence_hz, (int, float)):
            raise TypeError("cadence_hz must be a number")
        try:
            cadence = float(cadence_hz)
        except (OverflowError, ValueError) as exc:
            raise HealthTelemetryError("cadence_hz must be a finite representable number") from exc
        if not math.isfinite(cadence) or not 0 < cadence <= 2.0:
            raise HealthTelemetryError("human-readable cadence_hz must be in (0, 2]")
        if isinstance(start_time_s, bool) or not isinstance(start_time_s, (int, float)):
            raise TypeError("start_time_s must be a number")
        try:
            start = float(start_time_s)
        except (OverflowError, ValueError) as exc:
            raise HealthTelemetryError("start_time_s must be a finite representable number") from exc
        if not math.isfinite(start) or start < 0:
            raise HealthTelemetryError("start_time_s must be finite and non-negative")
        _validate_manual_clock_range(start, cadence, MAX_DETERMINISTIC_HEALTH_NODE_FRAMES)
        if type(heartbeat_frames) is not int or not 1 <= heartbeat_frames <= MAX_DETERMINISTIC_HEALTH_NODE_FRAMES:
            raise HealthTelemetryError("heartbeat_frames must be a positive bounded integer")
        self._descriptor = HealthDeviceDescriptor(
            device_id=device_id,
            component_type=component_type,
            provenance="driver-registry:deterministic-health-node/v1",
            stale_after_s=stale_after_s,
            disconnected_after_s=disconnected_after_s,
        )
        self._cadence_hz = cadence
        self._start_time_s = start
        self._heartbeat_frames = heartbeat_frames
        self._revision = 0
        self._last_heartbeat_s = start
        self._metric_descriptor = HealthMetricDescriptor(
            metric_id="health.load_percent",
            kind=HealthMetricKind.QUANTITY,
            unit="%",
            role="infrastructure_health",
            display_group="Health",
        )

    @property
    def health_descriptor(self) -> HealthDeviceDescriptor:
        return self._descriptor

    def read_health_snapshot(self, *, observed_time_s: float) -> HealthTelemetrySnapshot:
        if self._revision >= MAX_DETERMINISTIC_HEALTH_NODE_FRAMES:
            raise HealthTelemetryError("simulator exhausted its bounded revision space")
        expected = _manual_clock_time(self._start_time_s, self._cadence_hz, self._revision)
        if (
            isinstance(observed_time_s, bool)
            or not isinstance(observed_time_s, (int, float))
            or not math.isfinite(float(observed_time_s))
            or not math.isclose(float(observed_time_s), expected, rel_tol=0.0, abs_tol=1e-9)
        ):
            raise HealthTelemetryError(f"observed_time_s must follow the configured <=2 Hz cadence ({expected:g})")
        observed = float(observed_time_s)
        self._revision += 1
        if self._revision <= self._heartbeat_frames:
            self._last_heartbeat_s = observed
        metric = HealthMetric(
            descriptor=self._metric_descriptor,
            value=42.0,
            quality=HealthQuality.OK,
            source_time_s=self._last_heartbeat_s,
        )
        return HealthTelemetrySnapshot(
            descriptor=self._descriptor,
            revision=self._revision,
            observed_time_s=observed,
            heartbeat_time_s=self._last_heartbeat_s,
            mode="running",
            metrics=(metric,),
        )


def estimate_fleet_frame_payload_bytes(frame: FleetHealthFrame) -> int:
    """Return a deterministic payload-size proxy, not RSS or GUI-memory evidence."""

    total = 64
    for device in frame.devices:
        total += len(device.descriptor.device_id.encode()) + len(device.mode.encode()) + 64
        for metric in device.metrics:
            total += (
                len(metric.descriptor.metric_id.encode())
                + len(metric.descriptor.unit.encode())
                + len(metric.descriptor.role.encode())
                + len(metric.descriptor.display_group.encode())
                + len(str(metric.value).encode())
                + 64
            )
        for alarm in device.alarms:
            total += len(alarm.alarm_id.encode()) + len(alarm.message.encode()) + 64
    return total
