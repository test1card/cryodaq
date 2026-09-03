"""A latch may refuse a state change. It may not make the fault disappear.

On 2026-09-03 the SafetyManager latched at 11:19 on a vacuum threshold that fires
on every cooldown this stand has run. When the operator stopped the cryocooler at
22:07 and the cooldown CRITICAL arrived, it left as a single INFO line:

    _fault() re-entry ignored (already latched); new reason=Захолаживание не идёт
    по плану ... Т12 = 58.5 K

The first fault of a session was deciding what the whole session could report —
eleven hours of it. Refusing the STATE change is correct; that is what a latch
is. Discarding the EVENT is not.
"""

from __future__ import annotations

from cryodaq.core.safety_manager import SafetyState


def _latched_manager():
    """A real SafetyManager, so the production _transition path is exercised.

    Built the way the rest of tests/core builds one — a hand-rolled __new__ stub
    silently omits state that _transition reaches into, and would test a
    different object than the one that ships.
    """

    from cryodaq.core.safety_broker import SafetyBroker
    from cryodaq.core.safety_manager import SafetyManager

    return SafetyManager(SafetyBroker(), mock=True)


def test_a_fault_arriving_while_latched_is_recorded() -> None:
    mgr = _latched_manager()
    assert mgr._begin_fault_latch("vacuum loss while cold", source="vacuum_guard") is True
    assert mgr.state is SafetyState.FAULT_LATCHED

    accepted = mgr._begin_fault_latch(
        "Захолаживание не идёт по плану. Т12 = 58.5 K",
        source="cooldown_alarm",
    )

    assert accepted is False, "the latch still refuses the state change"
    recorded = mgr.suppressed_faults
    assert len(recorded) == 1
    assert "Захолаживание" in recorded[0]["reason"]
    assert recorded[0]["source"] == "cooldown_alarm"
    assert recorded[0]["latched_reason"] == "vacuum loss while cold", (
        "the record says what was already holding the latch"
    )


def test_the_latched_state_and_reason_are_unchanged() -> None:
    """Recording must not become a back door to overwriting the latch."""

    mgr = _latched_manager()
    mgr._begin_fault_latch("first", source="a")
    mgr._begin_fault_latch("second", source="b")

    assert mgr.state is SafetyState.FAULT_LATCHED
    assert mgr.fault_reason == "first", "the original fault still owns the latch"


def test_several_suppressed_faults_are_kept_in_order() -> None:
    mgr = _latched_manager()
    mgr._begin_fault_latch("first", source="a")
    for i in range(4):
        mgr._begin_fault_latch(f"later-{i}", source=f"s{i}")

    reasons = [entry["reason"] for entry in mgr.suppressed_faults]
    assert reasons == ["later-0", "later-1", "later-2", "later-3"]


def test_the_record_is_bounded_and_keeps_the_earliest() -> None:
    """A stuck source must not push out the fault that explains the episode.

    The earliest fault after a latch is the one most likely to say what actually
    went wrong, so the bound drops the newest rather than the oldest.
    """

    from cryodaq.core.safety_manager import _MAX_SUPPRESSED_FAULTS

    mgr = _latched_manager()
    mgr._begin_fault_latch("first", source="a")
    for i in range(_MAX_SUPPRESSED_FAULTS + 50):
        mgr._begin_fault_latch(f"repeat-{i}", source="stuck")

    recorded = mgr.suppressed_faults
    assert len(recorded) == _MAX_SUPPRESSED_FAULTS
    assert recorded[0]["reason"] == "repeat-0", "the earliest evidence survives"


def test_a_new_latched_episode_starts_clean() -> None:
    """The retained faults describe the episode that just ended."""

    mgr = _latched_manager()
    mgr._begin_fault_latch("first", source="a")
    mgr._begin_fault_latch("during", source="b")
    assert mgr.suppressed_faults

    mgr._state = SafetyState.READY  # recovered
    mgr._begin_fault_latch("a new problem entirely", source="c")

    assert mgr.suppressed_faults == (), "no carry-over between episodes"
    assert mgr.fault_reason == "a new problem entirely"


def test_the_accessor_cannot_be_used_to_mutate_the_record() -> None:
    mgr = _latched_manager()
    mgr._begin_fault_latch("first", source="a")
    mgr._begin_fault_latch("during", source="b")

    snapshot = mgr.suppressed_faults
    snapshot[0]["reason"] = "tampered"
    assert mgr.suppressed_faults[0]["reason"] == "during"


def test_nothing_is_recorded_when_not_latched() -> None:
    """The first fault owns the latch; it is not its own suppressed event."""

    mgr = _latched_manager()
    assert mgr._begin_fault_latch("first", source="a") is True
    assert mgr.suppressed_faults == ()


def test_it_is_logged_at_critical_not_info(caplog) -> None:
    """An INFO line is how eleven hours of deafness went unnoticed."""

    import logging

    mgr = _latched_manager()
    mgr._begin_fault_latch("first", source="a")
    with caplog.at_level(logging.CRITICAL, logger="cryodaq.core.safety_manager"):
        mgr._begin_fault_latch("cryocooler stopped", source="cooldown_alarm")

    critical = [r for r in caplog.records if r.levelno >= logging.CRITICAL]
    assert critical, "a fault arriving while latched is still a CRITICAL condition"
    assert any("cryocooler stopped" in r.getMessage() for r in critical)
