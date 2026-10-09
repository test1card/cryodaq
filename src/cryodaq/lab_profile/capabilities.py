"""Capability derivation for a Lab Profile v1 document.

Derivation from the registered driver specifications (``INSTRUMENT_DRIVER_METADATA``)
is the ONLY source of capability truth for a lab profile.  A profile never
declares capabilities; it declares instruments, and the INERT METADATA TABLE alone decides
what those instruments can do and which trust class they carry.
"""

from __future__ import annotations

from cryodaq.drivers.capability_metadata import INSTRUMENT_DRIVER_METADATA, DriverAuthority, DriverCapability

from .schema import LabCapabilities, ProfileInstrument


def derive_capabilities(instruments: tuple[ProfileInstrument, ...]) -> LabCapabilities:
    """Derive the capability truth of a lab profile from the inert driver metadata.

    Reads only ``INSTRUMENT_DRIVER_METADATA``.  The union of each declared
    instrument's ``spec.capabilities`` and ``spec.authority`` is the whole
    answer.  ``LabCapabilities.__post_init__`` independently recomputes that
    union and rejects any instance — derived or hand-built — whose values
    disagree with that table or reach source authority.
    """

    instrument_types = tuple(item.type_name for item in instruments)
    capabilities: set[DriverCapability] = set()
    trust_classes: set[DriverAuthority] = set()
    for type_name in instrument_types:
        spec = INSTRUMENT_DRIVER_METADATA[type_name]
        capabilities |= spec.capabilities
        trust_classes.add(spec.authority)
    return LabCapabilities(
        instrument_types=instrument_types,
        capabilities=frozenset(capabilities),
        trust_classes=frozenset(trust_classes),
    )
