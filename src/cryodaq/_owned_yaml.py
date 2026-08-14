"""One owned PyYAML loader, shared by every module that must not inherit host state.

Subclassing ``yaml.SafeLoader`` shares five mutable class attributes BY
REFERENCE.  Any library that calls ``yaml.SafeLoader.add_constructor(...)`` or
``add_implicit_resolver(...)`` -- documented public PyYAML APIs, ordinary use and
not an attack -- then decides what those loaders parse.  Measured on the shipped
alarm configuration before this module existed: a resolver for ``^Т[0-9]+$``
made the CRITICAL ``vacuum_loss_cold`` and ``calibrated_sensor_fault`` channel
lists load as a substituted string, with no diagnostic.

This lives at the package root deliberately.  The affected loaders are in
``cryodaq.core``, ``cryodaq.storage`` and at the root, so a home inside any one
of those subpackages would force an import edge in a direction the layering does
not otherwise have.

**The vocabulary is NOT narrowed.**  The shipped configurations require float,
so dropping constructors -- the ``cryodaq.lab_profile`` approach -- would reject
legitimate lab configuration.  The defect is shared mutable STATE, not an
over-broad grammar, and this class parses exactly what ``yaml.SafeLoader``
parses today.

**KNOWN LIMIT, stated rather than implied.**  The copies below are taken when
this module is first imported.  That closes registration happening AFTER the
import -- the realistic case, including registration by ordering accident -- and
NOT a host that poisons ``yaml.SafeLoader`` before it.  Closing that needs
constructors defined in the package rather than copied.  Tracked as OC-040 in
``docs/OPEN_CELLS.md``.
"""

from __future__ import annotations

import yaml

__all__ = ["OwnedSafeLoader", "owned_safe_load"]


class OwnedSafeLoader(yaml.SafeLoader):
    """``yaml.SafeLoader``'s grammar, without sharing its mutable tables.

    *** DO NOT define a subclass of this inside a function. ***  A class body
    executes when its statement executes, so a subclass declared inside a
    function takes its snapshot at CALL time, from whatever the host table holds
    then.  That defect shipped once here already: the production physical-alarms
    loader was declared inside its own loader function, and the comment on those
    lines described the mechanism while the code performed it.

    *** ``add_constructor`` IS COPY-ON-WRITE. ***  A test asserting
    ``Loader.yaml_constructors is not yaml.SafeLoader.yaml_constructors`` PASSES
    on the defective code, because the identity differs while the CONTENT was
    copied from a poisoned table.  Assert on parsed values, not identities.
    """

    yaml_constructors = dict(yaml.SafeLoader.yaml_constructors)
    yaml_multi_constructors = dict(yaml.SafeLoader.yaml_multi_constructors)
    yaml_implicit_resolvers = {key: list(value) for key, value in yaml.SafeLoader.yaml_implicit_resolvers.items()}
    yaml_path_resolvers = dict(yaml.SafeLoader.yaml_path_resolvers)
    bool_values = dict(yaml.SafeLoader.bool_values)


def owned_safe_load(stream: object) -> object:
    """Parse with the package-owned SafeLoader snapshot."""

    loader = OwnedSafeLoader(stream)
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()
