"""Capability derivation for a Lab Profile v1 document.

Derivation from the registered driver specifications (``BUILTIN_DRIVER_SPECS``)
is the ONLY source of capability truth for a lab profile.  A profile never
declares capabilities; it declares instruments, and the registry alone decides
what those instruments can do and which trust class they carry.
"""

from __future__ import annotations

from typing import Final

from cryodaq.drivers.registry import BUILTIN_DRIVER_SPECS, DriverAuthority, DriverCapability

from .schema import ActuationBoundaryError, LabCapabilities, ProfileInstrument

_SOURCE_CAPABILITIES: Final = frozenset({DriverCapability.CONTROLLED_SOURCE, DriverCapability.VERIFIED_OFF_SOURCE})


def derive_capabilities(instruments: tuple[ProfileInstrument, ...]) -> LabCapabilities:
    """Derive the capability truth of a lab profile from the driver registry.

    Reads only ``BUILTIN_DRIVER_SPECS``.  The union of each declared
    instrument's ``spec.capabilities`` and ``spec.authority`` is the whole
    answer; a defensive check rejects any source capability or reviewed-source
    trust class, which a validated profile can never produce.
    """

    instrument_types = tuple(item.type_name for item in instruments)
    capabilities: set[DriverCapability] = set()
    trust_classes: set[DriverAuthority] = set()
    for type_name in instrument_types:
        spec = BUILTIN_DRIVER_SPECS[type_name]
        capabilities |= spec.capabilities
        trust_classes.add(spec.authority)
    if capabilities & _SOURCE_CAPABILITIES or DriverAuthority.REVIEWED_SOURCE in trust_classes:
        raise ActuationBoundaryError(
            "derived lab capabilities include source authority: docs/new_lab_adaptation.md §8 states that "
            "adopting a hazardous actuator is not possible today — a hazardous actuator path does not exist"
        )
    return LabCapabilities(
        instrument_types=instrument_types,
        capabilities=frozenset(capabilities),
        trust_classes=frozenset(trust_classes),
    )
