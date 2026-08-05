"""OC-028 — the alarm-narration ledger must have a floor as well as a ceiling.

The dedup gate solved a real problem: a flapping alarm produced one narrative
per re-fire and buried the operator.  It solved it without a floor.  ``_seen``
was refreshed on every attempt INCLUDING suppressed ones, so the "quiet for a
full window" condition can never be reached while the alarm keeps firing:

    t=0s   fires -> narrated, _seen = 0
    t=10s  fires -> suppressed, _seen = 10   (clock restarts)
    t=20s  fires -> suppressed, _seen = 20   (clock restarts)
    ...

A continuously flapping CRITICAL was therefore narrated exactly ONCE, for as
long as it lasted.  Two further holes rode on top: a narration lost to a broken
transport still bought a full window of silence, and ``mark_delivered`` -- the
API that would have reported the outcome -- was called only by tests.  It
appeared exactly once in ``src/``: its own definition.

Owner decision of 2026-08-05 (A+B): re-arm on transport recovery, AND
re-narrate a still-active CRITICAL after a bounded interval.

**The interval is ELAPSED TIME, not a count of suppressed events.**  An alarm
re-firing every second reaches any event count almost immediately, which is not
what "after N windows" means to an operator watching a cryostat.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from cryodaq.agents.assistant.live.agent import _EventDedup

WINDOW = 30.0
ESCALATE = 300.0


@pytest.fixture
def clock():
    """A monotonic clock the test drives, so no test sleeps for five minutes."""

    with patch("cryodaq.agents.assistant.live.agent.time.monotonic") as monotonic:
        monotonic.return_value = 1000.0
        yield monotonic


def _ledger() -> _EventDedup:
    return _EventDedup(window_s=WINDOW, escalate_after_s=ESCALATE)


def test_a_continuously_flapping_critical_is_re_narrated_not_silenced_forever(clock) -> None:
    """The defect this row exists for, stated as a behaviour.

    Before the floor: 300 seconds of a CRITICAL re-firing every 10 s produced
    exactly ONE narration.  The operator stopped being told about a live
    CRITICAL and nothing in the system said so.
    """

    ledger = _ledger()
    start = 1000.0
    assert ledger.should_dispatch("alarm:vacuum_loss") is True
    ledger.note_outcome("alarm:vacuum_loss", delivered=True)

    narrated_at = [start]
    for step in range(1, 181):  # 30 minutes of a CRITICAL re-firing every 10 s
        clock.return_value = start + step * 10.0
        if ledger.should_dispatch("alarm:vacuum_loss"):
            narrated_at.append(clock.return_value)
            ledger.note_outcome("alarm:vacuum_loss", delivered=True)

    # The property that matters is not how many messages arrive; it is how long
    # an operator can be left hearing nothing about a live CRITICAL.  A silence
    # cannot exceed one escalation interval plus the window that starts it.
    gaps = [later - earlier for earlier, later in zip(narrated_at, narrated_at[1:], strict=False)]
    longest_silence = max(gaps)
    assert longest_silence <= ESCALATE + WINDOW, (
        f"operator heard nothing for {longest_silence:.0f}s about a live CRITICAL"
    )
    # And the ceiling the dedup window exists for must still hold.
    assert min(gaps) >= ESCALATE, f"re-narrated after only {min(gaps):.0f}s -- the spam bound is gone"


def test_the_dedup_window_still_suppresses_an_ordinary_flap_burst(clock) -> None:
    """The original problem must stay fixed; this is the regression direction."""

    ledger = _ledger()
    assert ledger.should_dispatch("alarm:flap") is True
    ledger.note_outcome("alarm:flap", delivered=True)

    for step in range(1, 6):  # five re-fires inside one window
        clock.return_value = 1000.0 + step * 5.0
        assert ledger.should_dispatch("alarm:flap") is False


def test_quiet_for_a_full_window_still_re_arms(clock) -> None:
    ledger = _ledger()
    assert ledger.should_dispatch("alarm:quiet") is True
    ledger.note_outcome("alarm:quiet", delivered=True)

    clock.return_value = 1000.0 + WINDOW + 1.0
    assert ledger.should_dispatch("alarm:quiet") is True


def test_a_narration_that_reached_nobody_buys_no_silence(clock) -> None:
    """Half A of the owner decision.

    The transport was broken when the only narration went out.  Suppressing the
    next occurrence would trade the operator's sole notice for silence.
    """

    ledger = _ledger()
    assert ledger.should_dispatch("alarm:lost") is True
    ledger.note_outcome("alarm:lost", delivered=False)

    clock.return_value = 1000.0 + 1.0
    assert ledger.should_dispatch("alarm:lost") is True, (
        "a narration no target accepted must not suppress the next occurrence"
    )


def test_delivery_recovering_restores_ordinary_suppression(clock) -> None:
    """Re-arming is not a permanent bypass: once delivery works, dedup resumes."""

    ledger = _ledger()
    ledger.should_dispatch("alarm:recover")
    ledger.note_outcome("alarm:recover", delivered=False)

    clock.return_value = 1001.0
    assert ledger.should_dispatch("alarm:recover") is True
    ledger.note_outcome("alarm:recover", delivered=True)

    clock.return_value = 1002.0
    assert ledger.should_dispatch("alarm:recover") is False


def test_escalation_is_elapsed_time_not_a_count_of_suppressed_events(clock) -> None:
    """The correction to the decision as first phrased.

    Ten suppressed EVENTS from an alarm re-firing every second is ten seconds,
    not five minutes.  This asserts the fast-flapping case stays suppressed well
    past any plausible event count, and breaks silence on the clock instead.
    """

    ledger = _ledger()
    ledger.should_dispatch("alarm:fast")
    ledger.note_outcome("alarm:fast", delivered=True)

    for step in range(1, 101):  # 100 re-fires, 1 s apart
        clock.return_value = 1000.0 + step
        assert ledger.should_dispatch("alarm:fast") is False, (
            f"escalated after {step} s -- that is an event count, not elapsed time"
        )

    clock.return_value = 1000.0 + ESCALATE + 1.0
    assert ledger.should_dispatch("alarm:fast") is True


def test_independent_alarms_do_not_share_a_floor(clock) -> None:
    ledger = _ledger()
    for name in ("alarm:a", "alarm:b"):
        assert ledger.should_dispatch(name) is True
        ledger.note_outcome(name, delivered=True)

    clock.return_value = 1005.0
    assert ledger.should_dispatch("alarm:a") is False
    assert ledger.should_dispatch("alarm:b") is False


def test_bookkeeping_does_not_grow_without_bound(clock) -> None:
    """Entries for alarms that stopped firing must be pruned.

    The prune horizon has to be the ESCALATION horizon, not the dedup window:
    an entry pruned at 30 s could never reach a 300 s escalation.
    """

    ledger = _ledger()
    for index in range(50):
        clock.return_value = 1000.0 + index
        ledger.should_dispatch(f"alarm:{index}")

    clock.return_value = 1000.0 + ESCALATE * 2
    ledger.should_dispatch("alarm:final")
    assert len(ledger._seen) <= 2, f"ledger retained {len(ledger._seen)} entries after the horizon"
