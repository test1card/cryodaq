"""NaN-доктрина: sentinel-persistence helper (P2-2).

SQLite REAL cannot store NaN faithfully — ``sqlite3`` maps NaN to NULL, which
violates the ``NOT NULL`` constraint on ``readings.value``. A non-finite Reading
is therefore persisted as a finite ``SENTINEL`` value paired with its (non-OK)
:class:`~cryodaq.drivers.base.ChannelStatus`. The **status** is the discriminator
(NaN-доктрина): the float value alone never distinguishes a real measurement from
an error state.

Two pure functions form the whole contract:

- :func:`encode` — Reading ``(value, status)`` → stored ``(value, status)`` pair.
  Any non-finite value collapses to ``SENTINEL``; the status passes through
  verbatim (the driver has already paired the non-finite value with a non-OK
  status).
- :func:`decode` — stored ``(value, status)`` → presentation value. A non-OK
  status (or a raw sentinel/non-finite) presents as ``NaN`` — a non-finite
  reading must never surface downstream as a real number.

Round-trip: ``decode(*encode(x, s))`` is ``x`` for a usable reading (finite + OK)
and ``NaN`` for any non-finite/error reading.
"""

from __future__ import annotations

import math

from cryodaq.drivers.base import ChannelStatus

# Finite stand-in for any non-finite reading value. No physical CryoDAQ channel
# (temperature in K, pressure in mbar, V / A / Ω / W, interferometric length in m)
# produces a value anywhere near ±1e88: cryogenic magnitudes top out around 1e5.
# The sentinel is finite (so SQLite stores it in a NOT NULL REAL column),
# unmistakably non-physical, and — being a plain IEEE-754 double literal — it
# round-trips bit-exactly through SQLite REAL, so ``value == SENTINEL`` is a
# reliable test rather than an approximate one.
SENTINEL = -8.888e88


def is_sentinel(value: float | None) -> bool:
    """True iff ``value`` is exactly the persistence sentinel."""
    return value == SENTINEL


def encode(value: float | None, status: ChannelStatus) -> tuple[float, str]:
    """Reading ``(value, status)`` → stored ``(value, status)`` pair.

    A non-finite (or missing) value becomes ``SENTINEL``; a finite value is
    stored as-is. The status string is stored verbatim as the discriminator.
    """
    if value is None or not math.isfinite(value):
        return SENTINEL, status.value
    return float(value), status.value


def decode(value: float, status: str) -> float:
    """Stored ``(value, status)`` → presentation value.

    Returns ``NaN`` whenever the row cannot be a real measurement — a non-OK
    status, a raw sentinel, or a non-finite stored value. Otherwise the finite
    value passes through. Callers present ``NaN`` as "no reading", never as a
    number.
    """
    if status.lower() != ChannelStatus.OK.value or is_sentinel(value) or not math.isfinite(value):
        return math.nan
    return float(value)
