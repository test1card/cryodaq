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
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable

from cryodaq.drivers.base import Reading


@runtime_checkable
class PassiveSensor(Protocol):
    """A measurement-only device with an asynchronous lifecycle."""

    @property
    def connected(self) -> bool: ...

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def read_channels(self) -> list[Reading]: ...


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

    async def emergency_off(self, channel: str | None = None) -> bool: ...

    @property
    def output_state_unverified(self) -> bool: ...


def declared_protocol_members(protocol: type[object]) -> Sequence[str]:
    """Return the public members declared directly by a capability protocol.

    This is diagnostic metadata for conformance tooling; authority decisions
    must use the reviewed registry, never this helper.
    """

    return tuple(sorted(name for name in protocol.__dict__ if not name.startswith("_")))
