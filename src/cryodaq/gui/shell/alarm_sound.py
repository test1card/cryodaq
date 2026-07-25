"""A3b — decide what the GUI should beep for a ``recent_alarms`` poll reply.

The engine keeps a ring buffer of ``alarm_fired`` events (``_AlarmRingBuffer``
in engine.py) exposed as the ``recent_alarms`` ZMQ command. This module holds
the poll-response -> beep-plan decision, factored out of Qt so it is testable
without a QApplication (same rationale as the engine's
``_should_dispatch_dead_channel_alarm``). The Qt-side poller/beeper lives in
top_watch_bar.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AlarmSoundPlan:
    """What a ``recent_alarms`` poll reply means for the beeper.

    ``new_levels`` is empty whenever nothing should be beeped for: the
    baseline-establishing first poll, an unchanged/stale reply, or a
    reply with no new alarms.
    """

    next_seq: int
    new_levels: tuple[str, ...]


def plan_from_response(
    resp: dict[str, Any], last_seq: int, *, have_baseline: bool
) -> AlarmSoundPlan:
    """Turn a ``recent_alarms`` reply into a beep plan.

    ``have_baseline`` is False only for the very first successful poll after
    GUI start: the ring buffer can hold ~50 historical alarms and beeping
    through all of them would be startling and misleading (they may be old
    news) — the first poll only establishes the baseline seq, silently.

    If the engine restarted, its ring buffer seq resets to 0 — a reported
    ``seq`` lower than what we already have means "new engine process", not
    "nothing happened since"; rebaseline silently rather than beeping once
    the engine's fresh seq eventually claws back past our stale one.
    """
    seq = int(resp.get("seq", 0) or 0)
    if not have_baseline or seq < last_seq:
        return AlarmSoundPlan(next_seq=seq, new_levels=())
    alarms = resp.get("alarms") or []
    levels = tuple(str(a.get("level", "")).upper() for a in alarms)
    return AlarmSoundPlan(next_seq=seq, new_levels=levels)
