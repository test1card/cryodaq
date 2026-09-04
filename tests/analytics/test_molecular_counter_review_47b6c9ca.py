"""Regressions for the six blockers raised against 47b6c9ca.

Each test names the gap it closes. None of these were covered by the 336-pass
analytics partition or the 46-pass focused selection the reviewer ran — the
problems were semantic, not arithmetic.
"""

from __future__ import annotations

import asyncio
import math
from datetime import UTC, datetime, timedelta

import pytest

from cryodaq.drivers.base import ChannelStatus, Reading

pytest.importorskip("plugins.molecular_counter", reason="plugins/ not importable")

from plugins.molecular_counter import MolecularCounter  # noqa: E402

_BULK = ["Т1", "Т2"]
_P = "VSP63D_1/pressure"


def _rd(channel: str, value: float, *, age_s: float = 0.0) -> Reading:
    return Reading(
        timestamp=datetime.now(UTC) - timedelta(seconds=age_s),
        instrument_id="t",
        channel=channel,
        value=value,
        unit="",
        status=ChannelStatus.OK,
        metadata={},
    )


def _batch(p: float, t: float, *, age_s: float = 0.0):
    return [_rd(_P, p, age_s=age_s)] + [_rd(ch, t, age_s=age_s) for ch in _BULK]


def _counter() -> MolecularCounter:
    c = MolecularCounter()
    c.configure({"pressure_channel": _P, "bulk_sensors": _BULK, "update_interval_s": 0.0})
    return c


# The pipeline delivers an authoritative PhaseEntry by plain attribute
# assignment and the plugin consumes it inside process(); there is no hook to
# call. These helpers drive that real path.
_PHASE_SEQ = [0]


def _enter_phase(counter, phase: str, *, started_at: float | None = None):
    from cryodaq.core.phase_event import PhaseEntry

    _PHASE_SEQ[0] += 1
    counter.pending_phase_event = PhaseEntry(
        experiment_id="exp-test",
        phase=phase,
        started_at=(datetime.now(UTC).timestamp() - 1.0) if started_at is None else started_at,
    )


def _run(c, batch):
    return asyncio.run(c.process(batch))


# ==========================================================================
# BLOCKER 2 — the baseline contract
# ==========================================================================
def test_duplicate_notification_of_the_same_phase_is_idempotent() -> None:
    """A repeated command is not a new entry.

    Re-zeroing on it would discard a measurement in progress on nothing but a
    duplicated message.
    """

    from cryodaq.core.phase_event import PhaseEntry

    started = datetime.now(UTC).timestamp() - 1.0
    entry = PhaseEntry(experiment_id="exp-test", phase="cooldown", started_at=started)

    c = _counter()
    c.pending_phase_event = entry
    _run(c, _batch(0.10, 300.0))
    epoch = c.baseline_epoch
    assert epoch is not None

    # The pipeline holds a latest-only value, so the SAME entry is republished
    # on every batch. Re-zeroing on that would discard a measurement in
    # progress on nothing but a repeated assignment.
    c.pending_phase_event = entry
    _run(c, _batch(0.05, 300.0))

    assert c.baseline_epoch == epoch, "the same entry twice must not move the zero"


def test_re_entering_a_phase_is_a_new_entry() -> None:
    """vacuum -> cooldown -> vacuum must not read as no change.

    A bare latest-only STRING collapses that sequence; the identity triple
    carries started_at, so the second vacuum is distinct.
    """

    from cryodaq.core.phase_event import PhaseEntry

    c = _counter()
    base = datetime.now(UTC).timestamp() - 100.0
    c.pending_phase_event = PhaseEntry("exp", "vacuum", base)
    _run(c, _batch(0.10, 300.0))
    first = c.baseline_epoch

    c.pending_phase_event = PhaseEntry("exp", "vacuum", base + 50.0)
    _run(c, _batch(0.05, 300.0))

    assert c.baseline_epoch != first, "a later started_at is a different entry"


def test_a_pre_transition_reading_cannot_become_the_new_zero() -> None:
    """The hook used to only clear; the next batch could rebuild from cache.

    A reading acquired BEFORE the operator advanced the phase would then be
    stamped with a post-transition baseline time.
    """

    c = _counter()
    _run(c, _batch(0.10, 300.0))  # cache is warm, pre-transition
    _enter_phase(c, "vacuum")

    # Only stale (pre-fence) readings available: no baseline may be taken.
    assert _run(c, _batch(0.05, 300.0, age_s=120.0)) == []
    assert c.baseline_epoch is None

    # A genuinely post-transition reading establishes it.
    out = _run(c, _batch(0.05, 300.0))
    assert out and out[0].value == pytest.approx(100.0)


def test_phase_entry_time_is_distinct_from_the_first_sample_time() -> None:
    """Conflating them overstates what the baseline is anchored to."""

    c = _counter()
    _enter_phase(c, "cooldown")
    meta = _run(c, _batch(0.10, 300.0))[0].metadata

    assert meta["phase_entry_epoch"] is not None
    assert meta["baseline_epoch"] is not None
    assert meta["baseline_epoch"] >= meta["phase_entry_epoch"]


def test_a_reload_reports_a_session_baseline_not_a_phase_one() -> None:
    """No durable reconstruction exists, so the wording must not imply one."""

    c = _counter()
    _enter_phase(c, "cooldown")
    _run(c, _batch(0.10, 300.0))
    assert "захолаживания" in c.baseline_reason

    c.configure({"pressure_channel": _P, "bulk_sensors": _BULK, "update_interval_s": 0.0})
    meta = _run(c, _batch(0.10, 300.0))[0].metadata
    assert "сессия" in meta["baseline_reason"], "a reload is a new observation session"
    assert meta["phase_entry_epoch"] is None, "no phase entry is being claimed"


# ==========================================================================
# BLOCKER 4 — the physics claim
# ==========================================================================
def test_no_lower_bound_or_direction_guarantee_is_published() -> None:
    """The mean of selected sensors is not the volume-weighted gas temperature,
    and a Pirani reading is composition dependent. Neither guarantee holds."""

    c = _counter()
    meta = _run(c, _batch(0.10, 300.0))[0].metadata

    assert "is_lower_bound" not in meta
    assert meta["quantity"] == "apparent_temperature_corrected_pirani_equivalent"
    assert meta["model"] == "single_zone_apparent"


def test_the_rate_definition_travels_with_the_value() -> None:
    """-69.3 %/h is a halving per hour, not a bounded 69.3% loss."""

    c = _counter()
    meta = _run(c, _batch(0.10, 300.0))[0].metadata
    assert meta["rate_definition"] == "100*d(ln N)/dt"


# ==========================================================================
# BLOCKER 5 — rate validity
# ==========================================================================
class _Clock:
    def __init__(self, start):
        self.t = start

    def now(self, tz=None):
        return self.t


def _spaced(counter, samples, *, step_s: float):
    import plugins.molecular_counter as mod

    clock = _Clock(datetime.now(UTC))
    original = mod.datetime
    mod.datetime = clock
    try:
        out = []
        for p, t in samples:
            batch = [
                Reading(
                    timestamp=clock.t,
                    instrument_id="t",
                    channel=ch,
                    value=v,
                    unit="",
                    status=ChannelStatus.OK,
                    metadata={},
                )
                for ch, v in [(_P, p)] + [(s, t) for s in _BULK]
            ]
            out = asyncio.run(counter.process(batch))
            clock.t = clock.t + timedelta(seconds=step_s)
        return out
    finally:
        mod.datetime = original


def _drive(counter, script, *, step_s: float):
    """Feed real batches through process() on ONE controlled timeline.

    `script` entries are either `(pressure, temperature)` for a good sample or
    `None` for an interval in which a configured sensor simply does not arrive
    — the production shape of an unavailable input, which appends no point at
    all. The whole sequence runs on a single clock, so an outage in the middle
    is a real gap rather than a restarted timeline.

    Readings carry `clock.t`, not wall time: the plugin reads its own now from
    the patched module, and a batch stamped with real time would not sit on the
    same axis as the history it is extending.
    """

    import plugins.molecular_counter as mod

    clock = _Clock(datetime.now(UTC))
    original = mod.datetime
    mod.datetime = clock

    def _reading(channel: str, value: float) -> Reading:
        return Reading(
            timestamp=clock.t,
            instrument_id="t",
            channel=channel,
            value=value,
            unit="",
            status=ChannelStatus.OK,
            metadata={},
        )

    try:
        out: list = []
        for item in script:
            if item is None:
                # One configured sensor absent: process() returns [] and
                # appends nothing. Only the clock moves.
                asyncio.run(counter.process([_reading(_P, 0.05)]))
            else:
                pressure, temperature = item
                batch = [_reading(_P, pressure)] + [_reading(ch, temperature) for ch in _BULK]
                produced = asyncio.run(counter.process(batch))
                if produced:
                    out = produced
            clock.t = clock.t + timedelta(seconds=step_s)
        return out
    finally:
        mod.datetime = original


def _outage_steps(step_s: float) -> int:
    from plugins.molecular_counter import _MAX_SAMPLE_GAP_S

    return int(_MAX_SAMPLE_GAP_S // step_s) + 2


def test_a_real_outage_breaks_the_run_through_the_production_path() -> None:
    """good readings -> genuinely unavailable input -> recovery, via process().

    The previous version appended `float("nan")` straight into `_history`.
    Production cannot do that: an invalid or missing input appends NOTHING, so
    the point the test relied on never exists. It proved a behaviour the code
    has no way to reach, which is worse than no test — the real defence went
    unexercised while the suite looked green.

    The real defence is the inter-sample interval. Silence longer than
    `_MAX_SAMPLE_GAP_S` breaks the trailing run, because after an outage the
    GAP is the only evidence the series was interrupted; nothing is left behind
    to find.
    """

    c = _counter()
    script = (
        [(0.05, 250.0)] * 8  # a healthy run, so a rate exists
        + [None] * _outage_steps(120.0)  # the sensor stops arriving
        + [(0.05, 250.0)] * 2  # recovery, too short to span a rate
    )
    out = _drive(c, script, step_s=120.0)

    assert out, "the counter must resume publishing a value after the outage"
    assert out[0].metadata["rate_pct_per_h"] is None, (
        "a rate was fitted across the outage — the gap did not break the run"
    )


def test_the_value_still_publishes_during_and_after_an_outage() -> None:
    """Breaking the RATE must not silence the level.

    The value and the slope are separate promises: an interrupted series makes
    the slope unknowable, but the current inventory is still measured and still
    worth showing. Withholding both would hide a number the operator has.
    """

    c = _counter()
    script = [(0.05, 250.0)] * 8 + [None] * _outage_steps(120.0) + [(0.05, 250.0)] * 2
    out = _drive(c, script, step_s=120.0)

    assert out[0].value is not None
    assert math.isfinite(float(out[0].value))


def test_an_uninterrupted_run_of_the_same_length_does_report_a_rate() -> None:
    """The control: the same sample count WITHOUT the outage does have a rate.

    Without this, the test above would pass just as happily if the counter had
    simply stopped producing rates at all.
    """

    c = _counter()
    out = _drive(c, [(0.05, 250.0)] * 12, step_s=120.0)
    assert out[0].metadata["rate_pct_per_h"] is not None


def test_the_span_is_measured_on_the_retained_run_not_the_buffer() -> None:
    """A long buffer ending in a short valid run must not report a rate."""

    c = _counter()
    _spaced(c, [(0.05, 250.0)] * 8, step_s=120.0)
    base = c._history[-1][0]
    c._history.append((base + 60.0, -1.0))  # breaks the run
    for i in range(1, 4):
        c._history.append((base + 60.0 + i * 10.0, 0.05))  # 3 pts, 20 s span
    assert c._rate_pct_per_h() is None


def test_a_non_monotonic_timestamp_breaks_the_run() -> None:
    c = _counter()
    _spaced(c, [(0.05, 250.0)] * 8, step_s=120.0)
    c._history.append((c._history[-1][0] - 600.0, 0.05))
    c._history.append((c._history[-1][0] + 10.0, 0.05))
    assert c._rate_pct_per_h() is None
