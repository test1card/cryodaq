"""One rendering of the apparent gas inventory, shared by every consumer.

The top bar and the analytics card previously formatted the same number
independently, and disagreed: a deep pump-down read `-5.0 дек` on the card and
`0%` in the chrome at the same instant, because one adapted to scale and the
other did not. Two places showing one quantity must not be able to drift.

Naming, deliberately careful. This is an **apparent** inventory: pressure
divided by an arithmetic mean of operator-selected sensor temperatures. That
mean is not the volume-weighted effective gas temperature, and the gauge is a
Pirani calibrated for N2, so the quantity is a temperature-corrected
Pirani-equivalent proxy — not a literal molecule count, and not a bounded
quantity in either direction.
"""

from __future__ import annotations

import math
from typing import Final

__all__ = [
    "ABSENT",
    "GAS_INVENTORY_CHANNEL",
    "MAX_FUTURE_SKEW_S",
    "format_inventory",
    "format_rate",
]

MAX_FUTURE_SKEW_S: Final = 300.0
"""How far ahead of now a sample may be dated before it is unusable.

Freshness is measured from the MEASUREMENT time, so a sample dated in the
future would otherwise never age: ``now - ts`` stays negative and the value
reads current forever. That is the failure mode ageing-from-arrival was
replaced to avoid, arriving from the other direction.

The bound matches the launcher's ``_PERIODIC_HEALTH_FUTURE_SKEW_S`` rather
than inventing a second number: both answer the same question about the same
clocks. Modest skew is tolerated; a sample beyond it is refused, not shown.
"""

GAS_INVENTORY_CHANNEL: Final = "analytics/molecular_counter/gas_inventory"
"""The one place this identity is written on the consumer side.

The plugin COMPOSES it from its own ``plugin_id`` and the metric name, so the
string here is a mirror of a value produced elsewhere. It was previously
mirrored twice — a named constant in ``top_watch_bar`` and a bare inline
literal in ``main_window_v2`` — which is the failure this module already exists
to prevent for formatting: two consumers of one quantity that can silently
disagree. Rename the plugin or its metric and a single mismatch here makes one
consumer go quiet while the other keeps working, with nothing raised.

Kept beside the formatters deliberately: every consumer that renders this
quantity already imports from this module, so there is no new coupling.
"""

ABSENT: Final = "—"
"""Rendered when there is no usable value. Never a zero, never a guess."""


def format_inventory(pct: float | None) -> str:
    """Percent near the baseline, decades far from it.

    A pump-down legitimately crosses five decades: zeroed at 1 bar, 1e-2 mbar is
    0.001% of baseline, where a further full decade — the most important thing
    that can happen — is invisible on a linear percent. A cooldown moves
    80 -> 118%, where percent reads perfectly. One format cannot serve both, so
    the format follows the value.
    """

    if pct is None or not isinstance(pct, (int, float)):
        return ABSENT
    value = float(pct)
    if not math.isfinite(value) or value <= 0.0:
        return ABSENT
    if 10.0 <= value <= 1000.0:
        return f"{value:.0f}%"
    if 1.0 <= value < 10.0:
        return f"{value:.1f}%"
    decades = math.log10(value / 100.0)
    return f"{decades:+.1f} дек"


def format_rate(pct_per_h: float | None) -> str:
    """The apparent logarithmic rate, 100·d(ln N)/dt, in %/h.

    NOT a bounded fractional loss: -69.3 %/h is a halving per hour, not "69.3%
    of the contents gone". The unit is a continuous log slope and can exceed
    100 in magnitude.
    """

    if pct_per_h is None or not isinstance(pct_per_h, (int, float)):
        return ""
    value = float(pct_per_h)
    if not math.isfinite(value):
        return ""
    return f"{abs(value):.1f} %/ч"
