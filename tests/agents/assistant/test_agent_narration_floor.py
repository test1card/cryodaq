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


def _flap_quietly(
    ledger: _EventDedup,
    event_id: str,
    clock,
    *,
    frm: float,
    to: float,
    interval: float = 5.0,
) -> None:
    """Refire continuously from ``frm`` to ``to`` and assert nothing was admitted.

    THIS EXISTS BECAUSE THE SAME MISTAKE HAS BEEN MADE THREE TIMES in this
    file.  ``_seen`` is refreshed on every call, so a test that simply jumps the
    clock forward leaves the alarm looking QUIET -- and the ordinary
    quiet-for-a-full-window branch then admits the dispatch, while the branch
    actually under test is never reached.  The node passes, or fails, for a
    reason unrelated to its name.

    Every suppression assertion in this file should go through here rather than
    stepping the clock by hand, so the refires cannot be forgotten again.
    """

    at = frm
    while at < to:
        clock.return_value = at
        assert ledger.should_dispatch(event_id) is False, (
            f"{event_id} was admitted at t={at:.1f}, inside the interval this test expects to be quiet"
        )
        at += interval


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


# --------------------------------------------------------------------------
# Outcomes belong to the ATTEMPT that produced them.
#
# `timeout_s: 120` with two concurrent inferences and a 30 s window means the
# same alarm can have two narrations in flight.  An outcome carrying only the
# alarm id then lands on whichever state happens to be current, and the four
# findings on `988413e8` were all this one seam seen from different sides.
# --------------------------------------------------------------------------


def test_a_late_failure_from_a_superseded_attempt_does_not_re_arm_the_alarm(clock) -> None:
    """Attempt A fails AFTER attempt B has already reached the operator.

    Without scoping, A's failure re-adds the alarm to `_undelivered` and the
    next eligible refire narrates a third time -- to an operator who has read
    the second one.
    """

    ledger = _ledger()
    start = 1000.0

    assert ledger.should_dispatch("alarm:slow") is True
    attempt_a = ledger.current_attempt("alarm:slow")

    # A is still generating a full window later, and the alarm goes quiet long
    # enough for B to be admitted on the ordinary path.
    clock.return_value = start + WINDOW + 1.0
    assert ledger.should_dispatch("alarm:slow") is True
    attempt_b = ledger.current_attempt("alarm:slow")
    assert attempt_b != attempt_a, "premise: the two admissions must be distinguishable"

    ledger.note_outcome("alarm:slow", delivered=True, attempt=attempt_b)

    # A finally times out and reports, long after B was read.
    clock.return_value = start + 120.0
    ledger.note_outcome("alarm:slow", delivered=False, attempt=attempt_a)

    assert "alarm:slow" not in ledger._undelivered, (
        "a superseded attempt's failure re-armed an alarm a newer attempt had delivered"
    )


def test_an_attempt_settles_once_so_cancellation_cannot_undo_a_delivery(clock) -> None:
    """Slice B is optional follow-up work that runs AFTER the summary landed.

    ``stop()`` during it cancels the handler, and the blanket cancellation
    report would otherwise overwrite the summary's confirmed delivery.
    """

    ledger = _ledger()
    assert ledger.should_dispatch("alarm:sliceb") is True
    attempt = ledger.current_attempt("alarm:sliceb")

    ledger.note_outcome("alarm:sliceb", delivered=True, attempt=attempt)
    ledger.note_outcome("alarm:sliceb", delivered=False, attempt=attempt)

    assert "alarm:sliceb" not in ledger._undelivered, (
        "a cancellation after a successful send overwrote the delivery the operator received"
    )


def test_an_unscoped_report_is_still_accepted(clock) -> None:
    """The pre-existing call shape must keep working.

    Scoping is opt-in precisely so that adding it did not silently turn every
    older caller into a no-op -- which would disable the ledger rather than
    tighten it.
    """

    ledger = _ledger()
    assert ledger.should_dispatch("alarm:legacy") is True
    ledger.note_outcome("alarm:legacy", delivered=False)
    assert "alarm:legacy" in ledger._undelivered


def test_the_escalation_clock_starts_when_the_operator_was_told(clock) -> None:
    """Admission is not delivery, and generation can take up to ``timeout_s``.

    Stamped at admission, the silence an operator experiences depends on how
    long the PREVIOUS narration took to generate -- a term the bound never
    accounted for.  Anchoring at delivery removes that dependence: the clock
    starts when they were told, which is what "300 seconds of silence" means.
    """

    ledger = _ledger()
    start = 1000.0
    latency = 120.0
    assert ledger.should_dispatch("alarm:latency") is True

    # The alarm keeps firing throughout -- see `_flap_quietly` for why every
    # suppression assertion in this file has to.
    _flap_quietly(ledger, "alarm:latency", clock, frm=start + 5.0, to=start + latency)

    # Generation takes 120 s -- the shipped `timeout_s` -- and only then lands.
    clock.return_value = start + latency
    ledger.note_outcome("alarm:latency", delivered=True, attempt=ledger.current_attempt("alarm:latency"))
    delivered = start + latency

    # Anchored at ADMISSION, escalation would fire at start+300, i.e. 180 s
    # after delivery.  Anchored at DELIVERY it must stay quiet until +300 s.
    _flap_quietly(ledger, "alarm:latency", clock, frm=delivered + 5.0, to=delivered + ESCALATE)

    clock.return_value = delivered + ESCALATE
    assert ledger.should_dispatch("alarm:latency") is True


def test_the_ledger_bounds_admissions_and_claims_nothing_about_delivery(clock) -> None:
    """Assert the bound this class OWNS, and refuse to assert the one it does not.

    An earlier version of this node manufactured a delivery at
    ``admission + 120`` and then asserted a received-to-received maximum from
    it.  That is circular: it fabricated the very quantity in dispute and never
    touched the production path, so it could not have failed however slow real
    delivery became.  Codex named it on ``96e5a878``.

    What the ledger genuinely bounds is the interval between ADMISSIONS,
    measured from the last confirmed delivery.  Everything after admission --
    the hourly rate limit, the semaphore, context assembly, audit-intent
    persistence, generation, sequential transport acknowledgements -- belongs to
    a pipeline with no end-to-end deadline, and is asserted nowhere in this file
    precisely because nothing here can hold it.
    """

    ledger = _ledger()
    start = 1000.0
    interval = WINDOW - 0.1

    admitted_at: list[float] = []
    for step in range(0, 400):
        clock.return_value = start + step * interval
        if ledger.should_dispatch("alarm:live"):
            admitted_at.append(clock.return_value)
            ledger.note_outcome("alarm:live", delivered=True, attempt=ledger.current_attempt("alarm:live"))

    gaps = [later - earlier for earlier, later in zip(admitted_at, admitted_at[1:], strict=False)]
    bound = ESCALATE + interval
    assert admitted_at, "the alarm was never admitted at all"
    assert max(gaps) <= bound, f"admission gap reached {max(gaps):.1f}s, above the bound {bound:.1f}s"


def test_a_stale_delivery_still_counts_as_the_operator_having_been_told(clock) -> None:
    """The inverse ordering: attempt A DELIVERS after attempt B was admitted.

    The scoping rule as first written discarded every report from a superseded
    attempt.  That is right for a failure and wrong for a success: the operator
    really did read A's narration, at the moment reported, and throwing it away
    lets B's failure license a resend seconds after they read it.
    """

    ledger = _ledger()
    start = 1000.0

    assert ledger.should_dispatch("alarm:ordering") is True
    attempt_a = ledger.current_attempt("alarm:ordering")

    clock.return_value = start + WINDOW + 1.0
    assert ledger.should_dispatch("alarm:ordering") is True
    attempt_b = ledger.current_attempt("alarm:ordering")
    assert attempt_b != attempt_a, "premise: the two admissions must be distinguishable"

    # B fails first; A then succeeds -- the slow attempt reached someone.
    ledger.note_outcome("alarm:ordering", delivered=False, attempt=attempt_b)
    delivery = start + WINDOW + 10.0
    clock.return_value = delivery
    ledger.note_outcome("alarm:ordering", delivered=True, attempt=attempt_a)

    assert "alarm:ordering" not in ledger._undelivered, (
        "a confirmed delivery from the older attempt was discarded, so B's failure still re-arms the alarm"
    )

    # And the clock moved to the DELIVERY, so the next narration is measured
    # from when the operator was told rather than from B's admission.
    _flap_quietly(ledger, "alarm:ordering", clock, frm=delivery + 5.0, to=delivery + ESCALATE)
    clock.return_value = delivery + ESCALATE
    assert ledger.should_dispatch("alarm:ordering") is True


def test_a_newer_failure_does_not_undo_an_older_confirmed_delivery(clock) -> None:
    """The opposite ordering to the node above: A DELIVERS, then B FAILS.

    Scoping alone does not cover it.  B is the current attempt, so its failure
    is not stale and settles normally -- and it re-armed the alarm even though
    A had told the operator seconds earlier, admitting a resend one window
    later.  The rule that closes it is about the OPERATOR, not about attempt
    numbers: a failure cannot re-arm when someone has been told since this
    attempt was admitted.
    """

    ledger = _ledger()
    start = 1000.0

    assert ledger.should_dispatch("alarm:inverse") is True
    attempt_a = ledger.current_attempt("alarm:inverse")

    clock.return_value = start + WINDOW + 1.0
    assert ledger.should_dispatch("alarm:inverse") is True
    attempt_b = ledger.current_attempt("alarm:inverse")

    # A -- admitted first, still in flight -- reaches the operator.
    clock.return_value = start + WINDOW + 5.0
    ledger.note_outcome("alarm:inverse", delivered=True, attempt=attempt_a)
    told = clock.return_value

    # B then fails.  It is the CURRENT attempt, so this is not the stale case.
    clock.return_value = start + WINDOW + 8.0
    ledger.note_outcome("alarm:inverse", delivered=False, attempt=attempt_b)

    assert "alarm:inverse" not in ledger._undelivered, (
        "a failure re-armed an alarm the operator had been told about after that attempt was admitted"
    )
    _flap_quietly(ledger, "alarm:inverse", clock, frm=told + 5.0, to=told + ESCALATE)


def test_a_settled_attempt_reporting_twice_does_not_drag_the_clock(clock) -> None:
    """The router reports at acknowledgement; the audit write finishes later.

    Both call `note_outcome` for the same attempt.  If the second one applied,
    the clock would move from the moment of delivery to the moment the
    filesystem finished -- postponing the next admission by unbounded audit
    latency, on the alarm path.
    """

    ledger = _ledger()
    start = 1000.0
    assert ledger.should_dispatch("alarm:twice") is True
    attempt = ledger.current_attempt("alarm:twice")

    clock.return_value = start + 2.0
    ledger.note_outcome("alarm:twice", delivered=True, attempt=attempt)
    first = ledger._last_allowed["alarm:twice"]

    clock.return_value = start + 90.0  # a slow audit settlement
    ledger.note_outcome("alarm:twice", delivered=True, attempt=attempt)

    assert ledger._last_allowed["alarm:twice"] == first, (
        "a second report for the same attempt moved the clock to the audit-completion time"
    )


def test_an_attempt_id_is_never_reused_after_pruning(clock) -> None:
    """A per-alarm counter is pruned with its alarm; a global one cannot be.

    The delivery path has no end-to-end bound, so a task can still report after
    its alarm has gone quiet and been pruned.  With per-alarm numbering the next
    occurrence of that alarm is numbered 1 again, and the old task's outcome
    settles the NEW attempt -- so the genuine new delivery is then ignored as a
    duplicate.
    """

    ledger = _ledger()
    start = 1000.0
    assert ledger.should_dispatch("alarm:pruned") is True
    stale_attempt = ledger.current_attempt("alarm:pruned")

    # The alarm stops firing for longer than the prune horizon.
    clock.return_value = start + ESCALATE + WINDOW + 60.0
    assert ledger.should_dispatch("alarm:pruned") is True
    fresh_attempt = ledger.current_attempt("alarm:pruned")

    assert fresh_attempt != stale_attempt, (
        f"attempt id {fresh_attempt} was reused after pruning; the stalled task can now settle a new attempt"
    )

    # The stalled task finally reports failure. It must not touch the new attempt.
    ledger.note_outcome("alarm:pruned", delivered=False, attempt=stale_attempt)
    ledger.note_outcome("alarm:pruned", delivered=True, attempt=fresh_attempt)
    assert "alarm:pruned" not in ledger._undelivered


@pytest.mark.asyncio
async def test_cancellation_during_the_audit_write_does_not_discard_the_delivery() -> None:
    """``stop()`` landing inside ``_audit.complete``, after the send succeeded.

    ``_dispatch_with_audit`` never returns, so the caller never learns the
    narration was delivered, and the cancellation fallback would settle a
    delivered attempt as undelivered -- resending to an operator who has read
    it.  The outcome is therefore recorded the moment the router reports, before
    the audit settlement write.
    """

    import asyncio
    from typing import Any
    from unittest.mock import AsyncMock, MagicMock

    from cryodaq.agents.assistant.live.agent import AssistantLiveAgent

    agent = AssistantLiveAgent.__new__(AssistantLiveAgent)
    agent._audit = MagicMock()
    agent._audit.prepare = AsyncMock(return_value="intent.json")

    async def cancelled_settlement(**_: Any) -> None:
        raise asyncio.CancelledError()

    agent._audit.complete = cancelled_settlement
    agent._router = MagicMock()
    agent._router.dispatch_detailed = AsyncMock(return_value={"telegram": {"-100111": "delivered"}})

    ledger = _EventDedup(window_s=WINDOW, escalate_after_s=ESCALATE)
    assert ledger.should_dispatch("alarm:audit") is True
    attempt = ledger.current_attempt("alarm:audit")

    from cryodaq.agents.assistant.live.agent import _reached_any_recipient

    with pytest.raises(asyncio.CancelledError):
        await agent._dispatch_with_audit(
            event=MagicMock(event_type="alarm_fired", payload={}, experiment_id=None),
            audit_id="a1",
            payload={},
            context_assembled="",
            prompt_template="alarm_summary",
            model="m",
            system_prompt="",
            user_prompt="",
            response="text",
            tokens={"in": 1, "out": 1},
            latency_s=0.1,
            errors=[],
            targets=[],
            on_outcomes=lambda reported: ledger.note_outcome(
                "alarm:audit", delivered=_reached_any_recipient(reported), attempt=attempt
            ),
        )

    assert "alarm:audit" not in ledger._undelivered, (
        "cancellation inside the audit write discarded a delivery the operator had already received"
    )
    # And the blanket cancellation fallback must not be able to undo it.
    ledger.note_outcome("alarm:audit", delivered=False, attempt=attempt)
    assert "alarm:audit" not in ledger._undelivered


@pytest.mark.asyncio
async def test_cancellation_while_queued_for_an_inference_slot_is_reported() -> None:
    """Every slot occupied, ``stop()`` arrives, nothing was ever generated.

    A handler that catches cancellation only after acquiring the semaphore
    never reports this one, and the gate has already advanced.
    """

    import asyncio
    from collections import deque
    from unittest.mock import AsyncMock, MagicMock

    from cryodaq.agents.assistant.live.agent import AssistantLiveAgent

    agent = AssistantLiveAgent.__new__(AssistantLiveAgent)
    agent._config = MagicMock(max_calls_per_hour=100)
    agent._call_timestamps = deque()
    agent._semaphore = asyncio.Semaphore(1)
    agent._dedup = _EventDedup(window_s=WINDOW, escalate_after_s=ESCALATE)
    agent._handle_alarm_fired = AsyncMock()

    await agent._semaphore.acquire()  # every slot taken by an in-flight inference

    assert agent._dedup.should_dispatch("alarm:queued") is True
    attempt = agent._dedup.current_attempt("alarm:queued")

    task = asyncio.create_task(
        agent._safe_handle(MagicMock(event_type="alarm_fired"), dedup_id="alarm:queued", attempt=attempt)
    )
    await asyncio.sleep(0)  # let it reach the semaphore and block there
    assert not task.done(), "premise: the handler must be waiting for a slot"

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    agent._handle_alarm_fired.assert_not_awaited()
    assert "alarm:queued" in agent._dedup._undelivered, (
        "cancellation while queued for a slot was not reported, yet the gate had advanced"
    )


@pytest.mark.asyncio
async def test_cancellation_before_the_handler_first_runs_is_reported() -> None:
    """The one cancellation no ``except`` inside the handler can see.

    A task cancelled before its coroutine is first scheduled never enters the
    body at all.  The event loop attaches a done-callback for exactly this, and
    this node drives the REAL ``_event_loop`` so the wiring is what is tested
    rather than a re-implementation of it.
    """

    import asyncio
    from collections import deque
    from unittest.mock import AsyncMock, MagicMock

    from cryodaq.agents.assistant.live.agent import AssistantLiveAgent

    agent = AssistantLiveAgent.__new__(AssistantLiveAgent)
    agent._config = MagicMock(
        slice_a_notification=True,
        alarm_fired_enabled=True,
        max_calls_per_hour=100,
    )
    agent._call_timestamps = deque()
    agent._semaphore = asyncio.Semaphore(1)
    agent._dedup = _EventDedup(window_s=WINDOW, escalate_after_s=ESCALATE)
    agent._handler_tasks = set()
    agent._queue = asyncio.Queue()
    agent._handle_alarm_fired = AsyncMock()

    # `_should_handle` reads `level`, not `severity`; a payload spelling it the
    # other way is silently filtered out and this node would pass vacuously.
    event = MagicMock(event_type="alarm_fired", payload={"alarm_id": "vacuum_loss", "level": "CRITICAL"})

    loop_task = asyncio.create_task(agent._event_loop())
    await agent._queue.put(event)
    # EXACTLY ONE yield: the loop wakes, gates the event and CREATES the handler
    # task, then suspends on an empty queue.  A second yield would let the
    # handler start running, which is a different scenario -- and one this file
    # already covers.
    await asyncio.sleep(0)

    handlers = [task for task in agent._handler_tasks if task is not loop_task]
    assert handlers, "premise: the event loop must have created a handler task"
    handler = handlers[0]
    assert agent._handle_alarm_fired.await_count == 0, "premise: the handler must not have started yet"

    handler.cancel()
    await asyncio.gather(handler, return_exceptions=True)
    await asyncio.sleep(0)

    loop_task.cancel()
    await asyncio.gather(loop_task, return_exceptions=True)

    agent._handle_alarm_fired.assert_not_awaited()
    assert "alarm:vacuum_loss" in agent._dedup._undelivered, (
        "a handler cancelled before it ever ran left the gate advanced with no outcome recorded"
    )
