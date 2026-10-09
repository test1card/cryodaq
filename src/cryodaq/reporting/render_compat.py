"""Construct a render snapshot that tolerates an older loaded contract.

Report builders are imported lazily, inside the command handlers that use
them, so in a long-lived engine they are loaded from disk long after
``periodic_input`` was loaded at startup. Adding a field to the contract
therefore puts fresh builder code in front of an older snapshot class until
that process restarts, and passing the new field unconditionally raises
``TypeError`` — turning a working report into "внутренняя ошибка" over what is
usually a cosmetic option.

Optional presentation fields are dropped when the loaded class does not have
them; absent always means the behaviour that existed before the field. Required
fields are never dropped: a builder that cannot supply those is a real bug and
must fail loudly.

This lives beside the callers rather than in ``periodic_input`` on purpose — a
helper inside the module that might itself be stale could not be relied on.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any

from cryodaq.reporting.periodic_input import PeriodicRenderSnapshot

logger = logging.getLogger(__name__)

# Fields a report may supply that older contracts will not accept.
_OPTIONAL_FIELDS = frozenset({"channel_labels", "focus_cold"})


def build_render_snapshot(**fields: Any) -> PeriodicRenderSnapshot:
    """Build a PeriodicRenderSnapshot, dropping optional fields it cannot take."""
    supported = {field.name for field in dataclasses.fields(PeriodicRenderSnapshot)}
    unsupported = _OPTIONAL_FIELDS & (set(fields) - supported)
    if unsupported:
        logger.info(
            "Отчёт строится без полей %s: загруженный контракт их не поддерживает "
            "(процесс запущен до обновления)",
            ", ".join(sorted(unsupported)),
        )
        fields = {name: value for name, value in fields.items() if name not in unsupported}
    return PeriodicRenderSnapshot(**fields)
