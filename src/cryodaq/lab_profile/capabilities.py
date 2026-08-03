"""Capability derivation for a Lab Profile v1 document.

Derivation from the registered driver specifications (``BUILTIN_DRIVER_SPECS``)
is the ONLY source of capability truth for a lab profile.  A profile never
declares capabilities; it declares instruments, and the registry alone decides
what those instruments can do and which trust class they carry.
"""

from __future__ import annotations

from cryodaq.drivers.registry import BUILTIN_DRIVER_SPECS, DriverAuthority, DriverCapability

from .schema import LabCapabilities, ProfileInstrument


def derive_capabilities(instruments: tuple[ProfileInstrument, ...]) -> LabCapabilities:
    """Derive the capability truth of a lab profile from the driver registry.

    Reads only ``BUILTIN_DRIVER_SPECS``.  The union of each declared
    instrument's ``spec.capabilities`` and ``spec.authority`` is the whole
    answer.  ``LabCapabilities.__post_init__`` independently recomputes that
    union and rejects any instance — derived or hand-built — whose values
    disagree with the registry or reach source authority.
    """

    instrument_types = tuple(item.type_name for item in instruments)
    capabilities: set[DriverCapability] = set()
    trust_classes: set[DriverAuthority] = set()
    for type_name in instrument_types:
        spec = BUILTIN_DRIVER_SPECS[type_name]
        capabilities |= spec.capabilities
        trust_classes.add(spec.authority)
    return LabCapabilities(
        instrument_types=instrument_types,
        capabilities=frozenset(capabilities),
        trust_classes=frozenset(trust_classes),
    )
