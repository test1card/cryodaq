"""Regressions for the six blockers raised against 47b6c9ca.

Each test names the gap it closes. None of these were covered by the 336-pass
analytics partition or the 46-pass focused selection the reviewer ran — the
problems were semantic, not arithmetic.
"""

from __future__ import annotations

import asyncio
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

    c = _counter()
    c.notify_phase_change("cooldown")
    _run(c, _batch(0.10, 300.0))
    epoch = c.baseline_epoch
    assert epoch is not None

    c.notify_phase_change("cooldown")
    _run(c, _batch(0.05, 300.0))

    assert c.baseline_epoch == epoch, "the same phase twice must not move the zero"


def test_a_pre_transition_reading_cannot_become_the_new_zero() -> None:
    """The hook used to only clear; the next batch could rebuild from cache.

    A reading acquired BEFORE the operator advanced the phase would then be
    stamped with a post-transition baseline time.
    """

    c = _counter()
    _run(c, _batch(0.10, 300.0))            # cache is warm, pre-transition
    c.notify_phase_change("vacuum")

    # Only stale (pre-fence) readings available: no baseline may be taken.
    assert _run(c, _batch(0.05, 300.0, age_s=120.0)) == []
    assert c.baseline_epoch is None

    # A genuinely post-transition reading establishes it.
    out = _run(c, _batch(0.05, 300.0))
    assert out and out[0].value == pytest.approx(100.0)


def test_phase_entry_time_is_distinct_from_the_first_sample_time() -> None:
    """Conflating them overstates what the baseline is anchored to."""

    c = _counter()
    c.notify_phase_change("cooldown")
    meta = _run(c, _batch(0.10, 300.0))[0].metadata

    assert meta["phase_entry_epoch"] is not None
    assert meta["baseline_epoch"] is not None
    assert meta["baseline_epoch"] >= meta["phase_entry_epoch"]


def test_a_reload_reports_a_session_baseline_not_a_phase_one() -> None:
    """No durable reconstruction exists, so the wording must not imply one."""

    c = _counter()
    c.notify_phase_change("cooldown")
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
    def __init__(self, start): self.t = start
    def now(self, tz=None): return self.t


def _spaced(counter, samples, *, step_s: float):
    import plugins.molecular_counter as mod

    clock = _Clock(datetime.now(UTC))
    original = mod.datetime
    mod.datetime = clock
    try:
        out = []
        for p, t in samples:
            batch = [
                Reading(timestamp=clock.t, instrument_id="t", channel=ch, value=v,
                        unit="", status=ChannelStatus.OK, metadata={})
                for ch, v in [(_P, p)] + [(s, t) for s in _BULK]
            ]
            out = asyncio.run(counter.process(batch))
            clock.t = clock.t + timedelta(seconds=step_s)
        return out
    finally:
        mod.datetime = original


def test_a_gap_is_not_bridged_by_the_regression() -> None:
    """Filtering bad points out of the middle and fitting across the hole
    invents a slope. The run must be contiguous and trailing."""

    c = _counter()
    out = _spaced(c, [(0.05, 250.0)] * 8, step_s=120.0)
    assert out[0].metadata["rate_pct_per_h"] is not None

    # Inject an unusable inventory point, then only two good ones after it.
    c._history.append((c._history[-1][0] + 120.0, float("nan")))
    c._history.append((c._history[-1][0] + 120.0, 0.05))
    c._history.append((c._history[-1][0] + 120.0, 0.05))
    assert c._rate_pct_per_h() is None, "only 2 points after the break — no rate"


def test_the_span_is_measured_on_the_retained_run_not_the_buffer() -> None:
    """A long buffer ending in a short valid run must not report a rate."""

    c = _counter()
    _spaced(c, [(0.05, 250.0)] * 8, step_s=120.0)
    base = c._history[-1][0]
    c._history.append((base + 60.0, -1.0))          # breaks the run
    for i in range(1, 4):
        c._history.append((base + 60.0 + i * 10.0, 0.05))   # 3 pts, 20 s span
    assert c._rate_pct_per_h() is None


def test_a_non_monotonic_timestamp_breaks_the_run() -> None:
    c = _counter()
    _spaced(c, [(0.05, 250.0)] * 8, step_s=120.0)
    c._history.append((c._history[-1][0] - 600.0, 0.05))
    c._history.append((c._history[-1][0] + 10.0, 0.05))
    assert c._rate_pct_per_h() is None
