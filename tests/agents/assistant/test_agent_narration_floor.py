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

    # TIGHTENED IN REVIEW.  The rule was first written as "buys no silence",
    # which let every refire through while delivery kept failing -- a transport
    # outage became the same storm the window exists to prevent, arriving via
    # the recovery path.  It is now "buys no MORE THAN ONE WINDOW of silence".
    clock.return_value = 1000.0 + 1.0
    assert ledger.should_dispatch("alarm:lost") is False, "the retry must still be window-bounded"

    clock.return_value = 1000.0 + WINDOW + 0.1
    assert ledger.should_dispatch("alarm:lost") is True, (
        "a narration no target accepted must not buy a full escalation interval of silence"
    )


def test_delivery_recovering_restores_ordinary_suppression(clock) -> None:
    """Re-arming is not a permanent bypass: once delivery works, dedup resumes."""

    ledger = _ledger()
    ledger.should_dispatch("alarm:recover")
    ledger.note_outcome("alarm:recover", delivered=False)

    clock.return_value = 1000.0 + WINDOW + 0.1
    assert ledger.should_dispatch("alarm:recover") is True
    ledger.note_outcome("alarm:recover", delivered=True)

    clock.return_value = 1000.0 + WINDOW + 1.1
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


# ---------------------------------------------------------------------------
# Round 2 — four findings against 7efd6879, two of them P1.
# ---------------------------------------------------------------------------


def test_the_silence_bound_holds_for_a_refire_just_inside_the_window(clock) -> None:
    """The bound this module claims was false for an interval it never tested.

    ``test_a_continuously_flapping_critical...`` asserts
    ``longest_silence <= ESCALATE + WINDOW`` and passed only because it used a
    10 s refire interval.  With the escalation anchored at the FIRST SUPPRESSED
    REFIRE, an alarm re-firing every 29.9 s is first suppressed at 29.9 s and
    only escalates at 329.9 s -- so the operator's silence is
    ``ESCALATE + interval``, which exceeds the claimed bound as the interval
    approaches the window.  Anchoring at the LAST NARRATION removes the term.

    A guard that asserts a bound the implementation does not hold is worse than
    no guard: it is cited as coverage.
    """

    ledger = _ledger()
    start = 1000.0
    interval = WINDOW - 0.1

    assert ledger.should_dispatch("alarm:edge") is True
    ledger.note_outcome("alarm:edge", delivered=True)
    narrated_at = [start]

    for step in range(1, 121):  # ~1 hour of refires just inside the window
        clock.return_value = start + step * interval
        if ledger.should_dispatch("alarm:edge"):
            narrated_at.append(clock.return_value)
            ledger.note_outcome("alarm:edge", delivered=True)

    gaps = [later - earlier for earlier, later in zip(narrated_at, narrated_at[1:], strict=False)]
    assert max(gaps) <= ESCALATE + WINDOW, (
        f"silence reached {max(gaps):.1f}s, above the claimed {ESCALATE + WINDOW:.0f}s bound"
    )


def test_a_failed_delivery_does_not_license_unbounded_retries(clock) -> None:
    """Re-arming must not become its own storm.

    While delivery keeps failing, every refire used to pass the gate, so a
    transport outage turned recovery into the same flood the window exists to
    prevent -- bounded only by the semaphore and the hourly rate limit.
    """

    ledger = _ledger()
    start = 1000.0
    assert ledger.should_dispatch("alarm:outage") is True
    ledger.note_outcome("alarm:outage", delivered=False)

    allowed = 0
    for step in range(1, 61):  # 60 refires, 1 s apart, transport still down
        clock.return_value = start + step
        if ledger.should_dispatch("alarm:outage"):
            allowed += 1
            ledger.note_outcome("alarm:outage", delivered=False)

    # One window elapsed over 60 s, so at most one retry may have been allowed.
    assert allowed <= 2, f"{allowed} retries in 60 s of outage -- the window bound is gone"
    assert allowed >= 1, "a persistent outage must still retry eventually"


def test_a_partially_delivered_narration_counts_as_seen() -> None:
    """One broken chat among several must not trigger a resend to everyone.

    ``_is_delivered_outcome`` requires EVERY recipient of a target to succeed,
    which is right for the audit trail and wrong for suppression: if one of two
    Telegram chats received the narration, an operator has read it.
    """

    from cryodaq.agents.assistant.live.agent import _reached_any_recipient
    from cryodaq.agents.assistant.live.output_router import _is_delivered_outcome

    partial = {"telegram": {"-100111": "delivered", "-100222": "failed"}}
    assert _is_delivered_outcome(partial["telegram"]) is False, "premise: the audit view rejects partial"
    assert _reached_any_recipient(partial) is True, "suppression must treat a partial delivery as seen"

    nobody = {"telegram": {"-100111": "failed", "-100222": "outcome_unknown"}}
    assert _reached_any_recipient(nobody) is False

    assert _reached_any_recipient({"operator_log": "delivered"}) is True
    assert _reached_any_recipient({}) is False


def test_allowing_a_retry_clears_the_marker_so_an_in_flight_attempt_is_not_retried_again(clock) -> None:
    """A stale failure marker describes an attempt that has been superseded.

    The retry branch fires on ``_undelivered`` plus one elapsed window.  The
    default Ollama timeout is longer than the 30 s window, so an alarm can
    refire while the retry narration is still being generated.  If allowing an
    attempt left the old marker in place, that refire would start a SECOND
    retry on the strength of a failure the in-flight attempt is already
    answering -- and neither has reported an outcome yet.
    """

    ledger = _ledger()
    start = 1000.0
    assert ledger.should_dispatch("alarm:slow") is True
    ledger.note_outcome("alarm:slow", delivered=False)

    # The alarm keeps firing every 5 s throughout.  That matters: `_seen` is
    # refreshed on every call, so continuous flapping keeps the ordinary
    # "quiet for a full window" branch out of the way and leaves the retry
    # branch as the only thing that can admit a dispatch here.
    retried_at: list[float] = []
    for step in range(1, 7):  # t+5 .. t+30, the first window
        clock.return_value = start + step * 5.0
        if ledger.should_dispatch("alarm:slow"):
            retried_at.append(clock.return_value)

    assert retried_at == [start + WINDOW], f"the bounded retry should land once, at t+{WINDOW:.0f}s; got {retried_at}"
    assert "alarm:slow" not in ledger._undelivered, (
        "allowing an attempt must clear the marker; the previous failure has been answered"
    )

    # That retry is still generating -- no outcome reported -- while the alarm
    # goes on firing for another full window.
    for step in range(7, 13):  # t+35 .. t+60
        clock.return_value = start + step * 5.0
        assert ledger.should_dispatch("alarm:slow") is False, (
            f"a refire at t+{step * 5.0:.0f}s started a second retry while the first was in flight"
        )

    # The attempt eventually fails; only THEN is the alarm re-armed.
    ledger.note_outcome("alarm:slow", delivered=False)
    clock.return_value = start + 65.0
    assert ledger.should_dispatch("alarm:slow") is True


def test_a_delivered_outcome_still_suppresses_after_the_marker_is_cleared(clock) -> None:
    """Clearing on allow must not weaken ordinary suppression.

    The obvious way to get the node above green is to stop honouring
    ``_undelivered`` at all, which would restore the original defect.  This
    asserts the ordinary path is unchanged: a DELIVERED narration still buys a
    full window of quiet.
    """

    ledger = _ledger()
    start = 1000.0
    assert ledger.should_dispatch("alarm:quiet") is True
    ledger.note_outcome("alarm:quiet", delivered=True)

    for step in (1.0, WINDOW - 0.1):
        clock.return_value = start + step
        assert ledger.should_dispatch("alarm:quiet") is False, f"suppression broke {step}s after a delivery"


@pytest.mark.asyncio
async def test_a_cancelled_alarm_attempt_is_recorded_as_undelivered() -> None:
    """``stop()`` must not let a killed narration buy silence.

    ``CancelledError`` is a ``BaseException``, so it passes straight through the
    ``except Exception`` handlers that report the outcome, while the gate has
    already advanced its clock.  ``_dedup`` is built in ``__init__``, so a
    stop/start cycle on the same instance keeps the ledger and the suppression
    survives with it.
    """

    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from cryodaq.agents.assistant.live.agent import AssistantLiveAgent

    agent = AssistantLiveAgent.__new__(AssistantLiveAgent)
    agent._config = MagicMock(max_calls_per_hour=100)
    agent._call_timestamps = __import__("collections").deque()
    agent._semaphore = asyncio.Semaphore(1)
    agent._dedup = _EventDedup(window_s=WINDOW, escalate_after_s=ESCALATE)
    agent._handle_alarm_fired = AsyncMock(side_effect=asyncio.CancelledError())

    event = MagicMock(event_type="alarm_fired")
    assert agent._dedup.should_dispatch("alarm:cancelled") is True

    with pytest.raises(asyncio.CancelledError):
        await agent._safe_handle(event, dedup_id="alarm:cancelled")

    assert "alarm:cancelled" in agent._dedup._undelivered, (
        "a cancelled attempt reached nobody, so it must not be treated as a delivered narration"
    )
