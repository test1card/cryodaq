"""Public capability contracts for built-in CryoDAQ instrument drivers.

These protocols describe narrow behavior only.  In particular, structural
conformance to a source protocol never grants command or safety authority;
that authority is assigned by the static reviewed registry.
"""

from __future__ import annotations

import math
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum, StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable

from cryodaq.drivers.base import Reading
from cryodaq.health.contract import HealthDeviceDescriptor, HealthTelemetrySnapshot


@runtime_checkable
class PassiveSensor(Protocol):
    """A measurement-only device with an asynchronous lifecycle."""

    @property
    def connected(self) -> bool: ...

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def read_channels(self) -> list[Reading]: ...


@runtime_checkable
class HealthTelemetryDevice(Protocol):
    """A snapshot-only passive infrastructure-health device.

    Structural conformance grants no authority; construction still requires an
    exact entry in the static driver registry.
    """

    @property
    def health_descriptor(self) -> HealthDeviceDescriptor: ...

    def read_health_snapshot(self, *, observed_time_s: float) -> HealthTelemetrySnapshot: ...


@runtime_checkable
class CalibratableSensor(Protocol):
    """Future explicit calibration adapter contract.

    The version marker intentionally prevents an existing method with the same
    name from accidentally advertising this capability.
    """

    @property
    def calibration_contract_version(self) -> int: ...

    async def read_calibration_pair(self, channel: int) -> tuple[float, float]: ...


@runtime_checkable
class BurstSensor(Protocol):
    """A measurement device with explicit, bounded burst capture control."""

    async def burst_start(self, *, experiment_id: str | None = None) -> None: ...

    async def burst_stop(self, *, experiments_root: Path | None = None) -> Path | None: ...

    def burst_status(self) -> Mapping[str, object]: ...


class BusAccessMode(StrEnum):
    SERIALIZED_SHARED = "serialized_shared"


class BusRecoveryLevel(StrEnum):
    DEVICE_CLEAR = "device_clear"
    INTERFACE_CLEAR = "interface_clear"
    REOPEN_BUS = "reopen_bus"


class DriverTrustClass(StrEnum):
    PASSIVE_MEASUREMENT = "passive_measurement"
    REVIEWED_SOURCE = "reviewed_source"
    PASSIVE_EXTENSION = "passive_extension"


def _bounded_identifier(value: str, *, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    normalized = unicodedata.normalize("NFC", value)
    if not normalized or len(normalized) > 128 or normalized != value:
        raise ValueError(f"{label} must be non-empty, NFC-normalized, and at most 128 characters")
    if any(unicodedata.category(character).startswith("C") for character in normalized):
        raise ValueError(f"{label} contains control characters")
    return normalized


@dataclass(frozen=True, slots=True)
class BusDescriptor:
    bus_id: str
    access_mode: BusAccessMode = BusAccessMode.SERIALIZED_SHARED
    supported_recovery: frozenset[BusRecoveryLevel] = frozenset()
    recovery_contract_version: int = 1
    recovery_timeout_s: float = 5.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "bus_id", _bounded_identifier(self.bus_id, label="bus_id"))
        if not isinstance(self.access_mode, BusAccessMode):
            raise TypeError("access_mode must be a BusAccessMode")
        levels = frozenset(self.supported_recovery)
        if any(not isinstance(level, BusRecoveryLevel) for level in levels):
            raise TypeError("supported_recovery must contain BusRecoveryLevel values")
        if isinstance(self.recovery_contract_version, bool) or self.recovery_contract_version != 1:
            raise ValueError("unsupported bus recovery contract version")
        if (
            isinstance(self.recovery_timeout_s, bool)
            or not isinstance(self.recovery_timeout_s, (int, float))
            or not math.isfinite(float(self.recovery_timeout_s))
            or not 0 < float(self.recovery_timeout_s) <= 300
        ):
            raise ValueError("recovery_timeout_s must be finite and in (0, 300]")
        object.__setattr__(self, "recovery_timeout_s", float(self.recovery_timeout_s))
        object.__setattr__(self, "supported_recovery", levels)


@dataclass(frozen=True, slots=True)
class AcquisitionTiming:
    connect_timeout_s: float
    read_timeout_s: float
    poll_interval_s: float

    def __post_init__(self) -> None:
        for label in ("connect_timeout_s", "read_timeout_s", "poll_interval_s"):
            value = getattr(self, label)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{label} must be a number")
            try:
                normalized = float(value)
            except (OverflowError, TypeError, ValueError) as exc:
                raise ValueError(f"{label} must be a finite representable number") from exc
            if not math.isfinite(normalized) or not 0 < normalized <= 86_400:
                raise ValueError(f"{label} must be finite and in (0, 86400]")
            object.__setattr__(self, label, normalized)


@runtime_checkable
class SharedBusParticipant(Protocol):
    """Device-local public recovery boundary; it conveys no source authority."""

    @property
    def bus_descriptor(self) -> BusDescriptor: ...

    async def mark_disconnected(self) -> None: ...

    async def recover_device(self) -> None: ...


class SharedBusRecoveryCoordinator(Protocol):
    """One explicitly registry-bound coordinator for one shared bus."""

    @property
    def bus_descriptor(self) -> BusDescriptor: ...

    async def interface_clear(self) -> bool: ...

    async def reopen_bus(self) -> bool: ...


class ConnectionLifecycle(Protocol):
    """Registry-bound cleanup for a connect attempt that did not commit."""

    async def abort_connect(self) -> None: ...


_BINDING_SEAL = object()


@dataclass(frozen=True, slots=True, init=False)
class DriverRuntimeBinding:
    """Registry-owned runtime facts; this object never grants source authority."""

    driver: object
    timing: AcquisitionTiming
    registry_provenance: str
    trust_class: DriverTrustClass
    simulation: bool
    bus_descriptor: BusDescriptor | None = None
    participant: SharedBusParticipant | None = None
    coordinator: SharedBusRecoveryCoordinator | None = None
    lifecycle: ConnectionLifecycle | None = None
    _seal: object = None

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("DriverRuntimeBinding is issued by a registry; use the explicit test factory in tests")

    @classmethod
    def _issued(
        cls,
        *,
        driver: object,
        timing: AcquisitionTiming,
        registry_provenance: str,
        trust_class: DriverTrustClass,
        simulation: bool = False,
        bus_descriptor: BusDescriptor | None = None,
        participant: SharedBusParticipant | None = None,
        coordinator: SharedBusRecoveryCoordinator | None = None,
        lifecycle: ConnectionLifecycle | None = None,
    ) -> DriverRuntimeBinding:
        instance = object.__new__(cls)
        object.__setattr__(instance, "driver", driver)
        object.__setattr__(instance, "timing", timing)
        object.__setattr__(instance, "registry_provenance", registry_provenance)
        object.__setattr__(instance, "trust_class", trust_class)
        object.__setattr__(instance, "simulation", simulation)
        object.__setattr__(instance, "bus_descriptor", bus_descriptor)
        object.__setattr__(instance, "participant", participant)
        object.__setattr__(instance, "coordinator", coordinator)
        object.__setattr__(instance, "lifecycle", lifecycle)
        object.__setattr__(instance, "_seal", _BINDING_SEAL)
        instance.__post_init__()
        return instance

    def __post_init__(self) -> None:
        provenance = _bounded_identifier(self.registry_provenance, label="registry_provenance")
        object.__setattr__(self, "registry_provenance", provenance)
        if self._seal is not _BINDING_SEAL or not isinstance(self.trust_class, DriverTrustClass):
            raise ValueError("runtime binding provenance is not sealed")
        if type(self.simulation) is not bool:
            raise TypeError("runtime binding simulation fact must be a bool")
        if self.participant is not None:
            if self.bus_descriptor is None or self.participant.bus_descriptor != self.bus_descriptor:
                raise ValueError("participant bus descriptor contradicts runtime binding")
        if self.coordinator is not None:
            if self.bus_descriptor is None or self.coordinator.bus_descriptor != self.bus_descriptor:
                raise ValueError("coordinator bus descriptor contradicts runtime binding")
        if self.bus_descriptor is not None:
            levels = self.bus_descriptor.supported_recovery
            if BusRecoveryLevel.DEVICE_CLEAR in levels and self.participant is None:
                raise ValueError("device-clear recovery requires an explicit participant")
            if levels & {BusRecoveryLevel.INTERFACE_CLEAR, BusRecoveryLevel.REOPEN_BUS} and self.coordinator is None:
                raise ValueError("bus-wide recovery requires an explicit coordinator")


def _issue_registry_runtime_binding(**kwargs: object) -> DriverRuntimeBinding:
    """Internal registry issuance seam; scheduler still enforces exact object identity."""

    return DriverRuntimeBinding._issued(**kwargs)  # type: ignore[arg-type]


def is_issued_runtime_binding(value: object) -> bool:
    return isinstance(value, DriverRuntimeBinding) and value._seal is _BINDING_SEAL


# Compatibility name only; new code must use the split participant/coordinator contracts.
SharedBusDevice = SharedBusParticipant


@runtime_checkable
class ControlledSource(Protocol):
    """Hazardous source behavior; conformance alone conveys no authority."""

    async def start_source(
        self,
        channel: str,
        p_target: float,
        v_compliance: float,
        i_compliance: float,
    ) -> None: ...

    async def stop_source(self, channel: str) -> None: ...


@runtime_checkable
class VerifiedOffSource(Protocol):
    """A source with explicit readback-verified emergency OFF behavior."""

    async def emergency_off(self, channel: str | None = None) -> SourceOffResult: ...

    @property
    def output_state_unverified(self) -> bool: ...


class SourceOffResult(Enum):
    PHYSICAL_STATE_UNKNOWN = "physical_state_unknown"
    COMMAND_ACCEPTED = "command_accepted"
    DEVICE_REPORTED_OFF = "device_reported_off"


class SourceOffTier(StrEnum):
    COMMAND_ONLY = "command_only"
    VERIFIED_OFF = "verified_off"


def off_result_satisfies_tier(tier: SourceOffTier, result: SourceOffResult) -> bool:
    return (tier is SourceOffTier.VERIFIED_OFF and result is SourceOffResult.DEVICE_REPORTED_OFF) or (
        tier is SourceOffTier.COMMAND_ONLY and result is SourceOffResult.COMMAND_ACCEPTED
    )


def physical_off_verified(tier: SourceOffTier, result: SourceOffResult) -> bool:
    return tier is SourceOffTier.VERIFIED_OFF and result is SourceOffResult.DEVICE_REPORTED_OFF


@dataclass(frozen=True, slots=True)
class SourceOffEvidence:
    """Exact global source-OFF evidence without collapsing its trust tier."""

    off_tier: SourceOffTier
    channel_off_results: tuple[tuple[str, SourceOffResult], ...]

    def __post_init__(self) -> None:
        if type(self.off_tier) is not SourceOffTier:
            raise TypeError("off_tier must be an exact SourceOffTier")
        if (
            type(self.channel_off_results) is not tuple
            or tuple(channel for channel, _result in self.channel_off_results) != ("smua", "smub")
            or not all(type(result) is SourceOffResult for _channel, result in self.channel_off_results)
        ):
            raise ValueError("channel_off_results must be exact smua/smub SourceOffResult values")

    @classmethod
    def from_global_result(cls, tier: SourceOffTier, result: SourceOffResult) -> SourceOffEvidence:
        return cls(tier, (("smua", result), ("smub", result)))

    @property
    def satisfies_tier(self) -> bool:
        return all(off_result_satisfies_tier(self.off_tier, result) for _channel, result in self.channel_off_results)

    @property
    def verified_off(self) -> bool:
        return all(physical_off_verified(self.off_tier, result) for _channel, result in self.channel_off_results)

    def receipt_payload(self) -> dict[str, object]:
        return {
            "off_tier": self.off_tier.value,
            "channel_off_results": {channel: result.value for channel, result in self.channel_off_results},
            "verified_off": self.verified_off,
        }


def parse_global_off_evidence(payload: object) -> SourceOffEvidence | None:
    """Accept one exact wire payload and reject any claimed derived truth."""
    if type(payload) is not dict or set(payload) != {"off_tier", "channel_off_results", "verified_off"}:
        return None
    tier_value = payload["off_tier"]
    results = payload["channel_off_results"]
    if type(tier_value) is not str or type(results) is not dict or set(results) != {"smua", "smub"}:
        return None
    try:
        evidence = SourceOffEvidence(
            SourceOffTier(tier_value),
            (("smua", SourceOffResult(results["smua"])), ("smub", SourceOffResult(results["smub"]))),
        )
    except (TypeError, ValueError):
        return None
    return evidence if payload["verified_off"] is evidence.verified_off else None


class SourceAdjustmentMode(StrEnum):
    START_STOP_ONLY = "start_stop_only"
    LIVE_UPDATE = "live_update"


@dataclass(frozen=True, slots=True)
class SourceSetpoint:
    p_target: float
    v_compliance: float
    i_compliance: float


@dataclass(frozen=True, slots=True)
class SourceDescriptor:
    off_tier: SourceOffTier
    adjustment_mode: SourceAdjustmentMode


@runtime_checkable
class AdjustableControlledSource(ControlledSource, Protocol):
    @property
    def source_connection_generation(self) -> int: ...

    @property
    def source_setpoints(self) -> Mapping[str, SourceSetpoint]: ...

    async def update_source_target(self, channel: str, p_target: float) -> None: ...

    async def update_source_limits(
        self,
        channel: str,
        *,
        v_compliance: float | None = None,
        i_compliance: float | None = None,
    ) -> None: ...


def describe_controlled_source(source: ControlledSource) -> SourceDescriptor:
    off_tier = SourceOffTier.VERIFIED_OFF if isinstance(source, VerifiedOffSource) else SourceOffTier.COMMAND_ONLY
    adjustment_mode = (
        SourceAdjustmentMode.LIVE_UPDATE
        if isinstance(source, AdjustableControlledSource)
        else SourceAdjustmentMode.START_STOP_ONLY
    )
    return SourceDescriptor(off_tier=off_tier, adjustment_mode=adjustment_mode)


def declared_protocol_members(protocol: type[object]) -> Sequence[str]:
    """Return the public members declared directly by a capability protocol.

    This is diagnostic metadata for conformance tooling; authority decisions
    must use the reviewed registry, never this helper.
    """

    return tuple(sorted(name for name in protocol.__dict__ if not name.startswith("_")))
