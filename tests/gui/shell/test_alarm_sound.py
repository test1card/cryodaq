"""A3b — plan_from_response decision logic (no Qt needed)."""

from __future__ import annotations

from cryodaq.gui.shell.alarm_sound import plan_from_response


def test_first_poll_establishes_baseline_without_beeping() -> None:
    resp = {"seq": 7, "alarms": [{"seq": i, "level": "WARNING"} for i in range(1, 8)]}
    plan = plan_from_response(resp, last_seq=0, have_baseline=False)
    assert plan.next_seq == 7
    assert plan.new_levels == ()


def test_new_alarms_are_reported_in_order() -> None:
    resp = {
        "seq": 3,
        "alarms": [
            {"seq": 2, "level": "WARNING"},
            {"seq": 3, "level": "CRITICAL"},
        ],
    }
    plan = plan_from_response(resp, last_seq=1, have_baseline=True)
    assert plan.next_seq == 3
    assert plan.new_levels == ("WARNING", "CRITICAL")


def test_no_new_alarms_yields_empty_plan() -> None:
    resp = {"seq": 5, "alarms": []}
    plan = plan_from_response(resp, last_seq=5, have_baseline=True)
    assert plan.next_seq == 5
    assert plan.new_levels == ()


def test_missing_level_defaults_to_empty_string_not_critical() -> None:
    resp = {"seq": 1, "alarms": [{"seq": 1}]}
    plan = plan_from_response(resp, last_seq=0, have_baseline=True)
    assert plan.new_levels == ("",)


def test_level_is_uppercased() -> None:
    resp = {"seq": 1, "alarms": [{"seq": 1, "level": "critical"}]}
    plan = plan_from_response(resp, last_seq=0, have_baseline=True)
    assert plan.new_levels == ("CRITICAL",)


def test_engine_restart_rebaselines_silently() -> None:
    # Engine restarted -> its ring buffer seq counter reset to a small
    # number. Must not beep, and must not get stuck waiting for the fresh
    # seq to claw back past the stale last_seq.
    resp = {"seq": 2, "alarms": [{"seq": 1, "level": "CRITICAL"}, {"seq": 2, "level": "CRITICAL"}]}
    plan = plan_from_response(resp, last_seq=999, have_baseline=True)
    assert plan.next_seq == 2
    assert plan.new_levels == ()


def test_missing_seq_defaults_to_zero() -> None:
    resp = {"alarms": []}
    plan = plan_from_response(resp, last_seq=0, have_baseline=False)
    assert plan.next_seq == 0
