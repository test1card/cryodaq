"""Shared formatting policy for operator-facing measurement readouts."""

from __future__ import annotations

import math
from typing import Final

from PySide6.QtCore import QSettings

from cryodaq.channels.descriptors import ChannelQuantity

_SETTINGS_ORGANIZATION: Final = "FIAN"
_SETTINGS_APPLICATION: Final = "CryoDAQ"
PRECISION_MODE_SETTINGS_KEY: Final = "display/precision_mode"
MISSING_VALUE_TEXT: Final = "—"


def _settings() -> QSettings:
    return QSettings(_SETTINGS_ORGANIZATION, _SETTINGS_APPLICATION)


def precision_mode_enabled(settings: QSettings | None = None) -> bool:
    """Read the persisted operator preference, defaulting fail-safe to concise."""

    value = (settings or _settings()).value(PRECISION_MODE_SETTINGS_KEY, False)
    if type(value) is bool:
        return value
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "on"}
    return value == 1


def set_precision_mode(enabled: bool, settings: QSettings | None = None) -> bool:
    """Persist precision mode through the application's existing preference store."""

    store = settings or _settings()
    store.setValue(PRECISION_MODE_SETTINGS_KEY, bool(enabled))
    store.sync()
    return store.status() == QSettings.Status.NoError


def format_display_value(
    value: object,
    *,
    quantity: ChannelQuantity = ChannelQuantity.LEGACY_UNKNOWN,
    precision_mode: bool | None = None,
) -> str:
    """Format one measurement for display without changing the source value."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return MISSING_VALUE_TEXT
    numeric = float(value)
    if not math.isfinite(numeric):
        return MISSING_VALUE_TEXT
    precise = precision_mode_enabled() if precision_mode is None else bool(precision_mode)
    if precise:
        return str(value)
    places = quantity.display_decimal_places
    fixed_point_floor = 10.0**-places
    if quantity.display_scientific or abs(numeric) >= 1000 or 0 < abs(numeric) < fixed_point_floor:
        return f"{numeric:.{places}e}"
    return f"{numeric:.{places}f}"
