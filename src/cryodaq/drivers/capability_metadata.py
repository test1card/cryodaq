"""Inert driver capability metadata: trust taxonomy and factory-free projection.

This module is deliberately authority-free.  It defines the driver trust-class
and capability enums and the factory-free ``DriverTypeMetadata`` projection,
and it imports nothing from the registry, the engine, or any driver
implementation.  A downstream consumer (for example ``cryodaq.lab_profile``)
can derive capabilities without holding driver-construction authority, and
reflection (``inspect.getmodule`` and friends) against anything exported here
lands in this module — where no constructor, factory, or loader exists.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType


class DriverMetadataError(ValueError):
    """A driver metadata projection violates the inert contract."""


class DriverAuthority(StrEnum):
    PASSIVE_MEASUREMENT = "passive_measurement"
    PASSIVE_EXTENSION = "passive_extension"
    REVIEWED_SOURCE = "reviewed_source"


class DriverCapability(StrEnum):
    PASSIVE_SENSOR = "passive_sensor"
    CALIBRATABLE_SENSOR = "calibratable_sensor"
    BURST_SENSOR = "burst_sensor"
    SHARED_BUS_DEVICE = "shared_bus_device"
    CONTROLLED_SOURCE = "controlled_source"
    VERIFIED_OFF_SOURCE = "verified_off_source"


@dataclass(frozen=True, slots=True)
class DriverTypeMetadata:
    """Inert, factory-free projection of one registered driver type.

    Unlike ``cryodaq.drivers.registry.DriverSpec`` — whose public
    ``factory``/``normalizer`` fields are exact constructors — this projection
    carries only declarative facts, so a downstream consumer can derive
    capabilities without holding any driver-construction authority.
    """

    type_name: str
    authority: DriverAuthority
    capabilities: frozenset[DriverCapability]

    def __post_init__(self) -> None:
        if type(self.type_name) is not str or not self.type_name:
            raise DriverMetadataError("driver metadata type_name must be a non-empty string")
        if not isinstance(self.authority, DriverAuthority):
            raise DriverMetadataError("driver metadata authority must be a DriverAuthority")
        capabilities = frozenset(self.capabilities)
        if any(not isinstance(item, DriverCapability) for item in capabilities):
            raise DriverMetadataError("driver metadata capabilities must be DriverCapability values")
        object.__setattr__(self, "capabilities", capabilities)


def build_driver_metadata_projection(specs: Iterable[object]) -> Mapping[str, DriverTypeMetadata]:
    """Project registered driver specs into inert metadata keyed by type name.

    Each item must expose ``type_name``, ``authority`` and ``capabilities``
    attributes (the registry's ``DriverSpec`` does); the projection copies
    exactly those three declarative facts and nothing else.
    """

    projection: dict[str, DriverTypeMetadata] = {}
    for spec in specs:
        metadata = DriverTypeMetadata(
            type_name=spec.type_name,  # type: ignore[attr-defined]
            authority=spec.authority,  # type: ignore[attr-defined]
            capabilities=spec.capabilities,  # type: ignore[attr-defined]
        )
        if metadata.type_name in projection:
            raise DriverMetadataError(f"duplicate driver metadata projection for {metadata.type_name!r}")
        projection[metadata.type_name] = metadata
    return MappingProxyType(projection)
