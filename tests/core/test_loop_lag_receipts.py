"""A loop stall must leave a record an operator can read.

The overload transitions already wrote log lines. A log line is not a receipt:
nothing downstream can count exceedances, report the worst lag, or say what was
scheduled when the loop went late. These tests hold the transitions to emitting
one structured record on entry and exactly one on recovery.

Deliberately NOT a safety latch: degraded analytics is not a fault, and the
receipt is emitted from `observe_lag`, which the loop's own probe drives, so no
sink is ever called from a worker thread.
"""

import pytest

from cryodaq.core.analytics_admission import AnalyticsAdmission


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _admission(receipts: list[dict], clock: _Clock) -> AnalyticsAdmission:
    return AnalyticsAdmission(
        enter_overload_s=0.5,
        leave_overload_s=0.15,
        reduce_at_s=0.25,
        recovery_s=30.0,
        clock=clock,
        receipt_sink=receipts.append,
    )


def _degrade_then_recover(admission, clock, *, peak=0.9):
    admission.observe_lag(0.6)
    admission.observe_lag(peak)
    admission.observe_lag(0.05)
    clock.advance(31.0)
    admission.observe_lag(0.05)


def test_entering_overload_emits_one_degraded_receipt():
    clock = _Clock()
    receipts: list[dict] = []
    admission = _admission(receipts, clock)

    admission.observe_lag(0.6)
    admission.observe_lag(0.7)  # still overloaded: no second receipt

    degraded = [r for r in receipts if r["state"] == "degraded"]
    assert len(degraded) == 1, "one transition, one receipt"
    record = degraded[0]
    assert record["event"] == "event_loop_lag"
    assert record["lag_s"] == pytest.approx(0.6)
    assert record["enter_threshold_s"] == pytest.approx(0.5)
    assert record["exceedances"] == 1


def test_the_degraded_receipt_names_what_was_scheduled():
    clock = _Clock()
    receipts: list[dict] = []
    _admission(receipts, clock).observe_lag(0.6)

    owners = receipts[0]["periodic_owners"]
    assert owners, "a lag number alone does not say where to look"
    assert "loop_owned_safety" in owners
    assert "offloaded_best_effort" in owners
    assert "sensor_diag_tick" in owners["offloaded_best_effort"]


def test_recovery_emits_exactly_one_receipt_with_the_peak():
    clock = _Clock()
    receipts: list[dict] = []
    admission = _admission(receipts, clock)
    _degrade_then_recover(admission, clock, peak=0.9)

    recovered = [r for r in receipts if r["state"] == "recovered"]
    assert len(recovered) == 1
    record = recovered[0]
    assert record["peak_lag_s"] == pytest.approx(0.9), "the worst lag of the episode"
    assert record["held_s"] > 0
    assert record["exceedances"] == 1


def test_a_brief_dip_does_not_count_as_recovery():
    clock = _Clock()
    receipts: list[dict] = []
    admission = _admission(receipts, clock)
    admission.observe_lag(0.6)
    admission.observe_lag(0.05)
    clock.advance(5.0)
    admission.observe_lag(0.6)  # back above: the calm window restarts
    clock.advance(31.0)
    admission.observe_lag(0.6)

    assert not [r for r in receipts if r["state"] == "recovered"]
    assert admission.overloaded is True


def test_repeated_episodes_accumulate_exceedances():
    clock = _Clock()
    receipts: list[dict] = []
    admission = _admission(receipts, clock)
    for _ in range(3):
        _degrade_then_recover(admission, clock)

    degraded = [r for r in receipts if r["state"] == "degraded"]
    assert [r["exceedances"] for r in degraded] == [1, 2, 3]
    assert admission.snapshot()["lag_exceedances"] == 3


def test_a_failing_sink_never_breaks_the_probe():
    clock = _Clock()

    def _explode(_receipt):
        raise RuntimeError("sink is down")

    admission = AnalyticsAdmission(
        enter_overload_s=0.5,
        leave_overload_s=0.15,
        reduce_at_s=0.25,
        clock=clock,
        receipt_sink=_explode,
    )
    admission.observe_lag(0.6)  # must not raise
    assert admission.overloaded is True


def test_no_receipts_and_no_error_without_a_sink():
    clock = _Clock()
    admission = AnalyticsAdmission(
        enter_overload_s=0.5, leave_overload_s=0.15, reduce_at_s=0.25, clock=clock
    )
    _degrade_then_recover(admission, clock)
    assert admission.overloaded is False


def test_degradation_is_not_a_safety_latch():
    """Overload pauses analytics and clears itself; it never latches."""
    clock = _Clock()
    receipts: list[dict] = []
    admission = _admission(receipts, clock)
    _degrade_then_recover(admission, clock)
    assert admission.overloaded is False
    assert admission.snapshot()["overloaded_for_s"] is None
