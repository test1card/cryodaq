"""The one place that decides whether a reading may be called *current*.

A reading has two independent axes of trust, and conflating them is how a stand
reports confident numbers about nothing:

* **usability** — is this a measurement at all? Status is OK and the value is
  finite. That is :meth:`cryodaq.drivers.base.Reading.is_usable`, and it does
  not change here.
* **freshness** — is this measurement still describing *now*? A perfectly
  usable reading taken two hours ago is not a current temperature.

On 2026-09-02 the writer stopped persisting at 22:45:45 and the stand kept
polling. The 23:00 periodic report printed a full table of temperatures and a
pressure as though they were current, while three data-loss alarms were active
in the same message. Every value in that table was the last one seen before the
failure. The report was reading the newest *usable* row and never asking how old
it was.

This module is that missing question, asked once. Callers must not carry their
own threshold: they had three (a 60 s rule in the Telegram commands, a
`_STALE_THRESHOLD_S` in the dashboard cells, and nothing at all in the periodic
report), which is precisely how the report came to disagree with the alarms
printed beside it.

A stale reading may still be *shown* — hiding it is its own kind of lie — but it
must be shown with its age, must not be presented as current, and must not feed
a new calculation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

READING_STALE_AFTER_S: Final = 60.0
"""Age beyond which a reading no longer describes *now*.

Instruments on this stand poll at 1-2 s, so a minute is many missed samples --
comfortably longer than any normal hiccup, and far shorter than the intervals
over which an operator makes decisions. It matches the threshold the Telegram
commands already applied, so adopting it here changes no existing behaviour.
"""

PREDICTION_STALE_AFTER_S: Final = 120.0
"""Age beyond which a cooldown prediction no longer describes *now*.

The predictor publishes every 30 s (``config/cooldown.yaml``:
``predict_interval_s``), so this is **four** missed publish cycles -- a clear
stall rather than a hiccup, and still far shorter than the interval over which
an ETA meaningfully changes.

Longer than :data:`READING_STALE_AFTER_S` on purpose: a raw sensor polls at
1-2 s, a forecast at 30 s, so the same bound would call every healthy
prediction stale.

This lives here, beside the judgement that consumes it, because it has two
displays -- the full Analytics view and the compact dashboard header -- and
when each owned a private copy they could drift apart and disagree about the
same number in the same window.
"""


@dataclass(frozen=True, slots=True)
class Freshness:
    """Whether a reading may be called current, and why not when it may not."""

    age_s: float | None
    """Seconds between the measurement and the reference moment, when knowable."""

    is_current: bool
    """True only when the age is known, non-negative and within the bound."""

    reason: str | None
    """Human-readable cause when not current; ``None`` when it is."""

    @property
    def is_stale(self) -> bool:
        return not self.is_current


def judge_freshness(
    timestamp_epoch: float | None,
    *,
    now_epoch: float,
    max_age_s: float = READING_STALE_AFTER_S,
) -> Freshness:
    """Judge one reading's freshness against a reference moment.

    ``now_epoch`` is the moment the answer is *about* — for a periodic report
    that is the slot it covers, not the wall clock at render time, so a report
    regenerated later does not silently mark its own contents stale.

    Fails closed: an unknown, non-finite or future-dated timestamp is not
    current, because none of them can establish that the reading describes now.
    """

    if timestamp_epoch is None:
        return Freshness(age_s=None, is_current=False, reason="время измерения неизвестно")
    try:
        age_s = float(now_epoch) - float(timestamp_epoch)
    except (TypeError, ValueError):
        return Freshness(age_s=None, is_current=False, reason="время измерения нечитаемо")
    if not math.isfinite(age_s):
        return Freshness(age_s=None, is_current=False, reason="время измерения нечитаемо")
    if age_s < 0:
        return Freshness(age_s=age_s, is_current=False, reason="время измерения в будущем")
    if age_s > max_age_s:
        return Freshness(age_s=age_s, is_current=False, reason=f"возраст {format_age(age_s)}")
    return Freshness(age_s=age_s, is_current=True, reason=None)


def format_age(age_s: float) -> str:
    """Render an age the way an operator reads it: seconds, minutes, hours."""

    if not math.isfinite(age_s) or age_s < 0:
        return "неизвестно"
    seconds = int(age_s)
    if seconds < 60:
        return f"{seconds} с"
    if seconds < 3600:
        return f"{seconds // 60} мин"
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    if hours < 24:
        return f"{hours} ч {minutes:02d} мин"
    days, hours = divmod(hours, 24)
    return f"{days} сут {hours} ч"
