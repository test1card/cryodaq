"""C-5 rate-clock guard: reset-not-drop on NTP / clock jumps.

The rate estimator feeds the 5 K/min protection using measurement-time
timestamps. An NTP step makes those timestamps jump backward (or far
forward). Under the old append-and-trim logic a backward step left stale
"future" samples in the buffer, driving the min_span_s span negative so
get_rate() returned None *forever* (until maxlen eviction) — the 5 K/min
protection went blind permanently.

Ratified doctrine (reset-not-drop): on any backward gap, or a forward gap
larger than 4x the channel's established poll period, CLEAR that channel's
buffer and make the current sample the new anchor. Blindness is then bounded
by the min_span_s refill window (~30 s at the deployed 2 s poll), not forever.
Measurement-time is kept (no revert to monotonic).
"""

from __future__ import annotations

from cryodaq.core.rate_estimator import RateEstimator

T0 = 1_000_000.0
POLL_S = 2.0
RATE_PER_SEC = 100.0 / 60.0  # +100 K/min, well above the 5 K/min threshold
CH = "Т12 Холодная точка"


def _fill(est: RateEstimator, n: int, *, t0: float = T0, ch: str = CH, step: float = POLL_S) -> float:
    """Push n steep-ramp samples at `step` spacing; return the last timestamp."""
    t = t0
    for i in range(n):
        t = t0 + step * i
        est.push(ch, t, 4.0 + RATE_PER_SEC * (t - t0))
    return t


def test_backward_step_resets_buffer_and_reanchors():
    """NTP step backward -> buffer cleared, current sample is the new anchor,
    no false rate-fault (get_rate None on the single anchor)."""
    est = RateEstimator(window_s=120.0, min_points=8, min_span_s=30.0)
    _fill(est, 16)  # 30 s span, armed
    assert est.get_rate(CH) is not None

    est.push(CH, T0 - 50.0, 4.0)  # NTP step 50 s backward
    assert est.buffer_size(CH) == 1, "backward step must clear the buffer (reset-not-drop)"
    assert est.get_rate(CH) is None, "single anchor sample must not produce a rate/false fault"


def test_forward_jump_beyond_4x_poll_resets_buffer():
    """Forward jump > 4x poll period -> buffer cleared, current sample anchors."""
    est = RateEstimator(window_s=120.0, min_points=8, min_span_s=30.0)
    last = _fill(est, 16)  # median gap = 2 s -> threshold 8 s
    est.push(CH, last + 9.0, 4.0)  # 9 s > 4 x 2 s
    assert est.buffer_size(CH) == 1, "forward jump > 4x poll must clear the buffer"


def test_normal_jitter_does_not_reset():
    """+/-50% poll jitter must NOT reset and rate must stay computable."""
    est = RateEstimator(window_s=120.0, min_points=8, min_span_s=30.0)
    t = T0
    gaps = [1.0, 3.0, 2.0, 1.0, 3.0, 2.0, 1.0, 3.0, 2.0, 1.0, 3.0, 2.0, 1.0, 3.0, 2.0]
    est.push(CH, t, 4.0)
    for g in gaps:  # 16 samples total, all gaps within +/-50% of 2 s
        t += g
        est.push(CH, t, 4.0 + RATE_PER_SEC * (t - T0))
    assert est.buffer_size(CH) == 16, "normal jitter must not trigger a reset"
    rate = est.get_rate(CH)
    assert rate is not None and rate > 5.0, "jitter path must stay armed and read the ramp"


def test_protection_rearms_within_refill_window():
    """After a reset, a genuine steep ramp becomes computable again (>5 K/min)
    once the min_span_s window refills (~30 s at 2 s poll)."""
    est = RateEstimator(window_s=120.0, min_points=8, min_span_s=30.0)
    _fill(est, 16)
    anchor = T0 - 50.0
    est.push(CH, anchor, 4.0)  # backward step -> reset, anchor here
    assert est.get_rate(CH) is None

    first_armed_after = None
    for i in range(1, 40):
        t = anchor + POLL_S * i
        est.push(CH, t, 4.0 + RATE_PER_SEC * (t - anchor))  # genuine steep ramp
        r = est.get_rate(CH)
        if r is not None:
            first_armed_after = t - anchor
            assert r > 5.0, "steep ramp after reset must fault once armed"
            break
    assert first_armed_after is not None, "protection never re-armed after reset"
    assert 28.0 <= first_armed_after <= 34.0, f"refill window ~30 s, got {first_armed_after}"


def test_reset_is_per_channel():
    """A jump on one channel must not touch another channel's buffer."""
    est = RateEstimator(window_s=120.0, min_points=8, min_span_s=30.0)
    _fill(est, 16, ch="A")
    _fill(est, 16, ch="B")
    est.push("A", T0 - 50.0, 4.0)  # backward step on A only
    assert est.buffer_size("A") == 1, "channel A must reset"
    assert est.buffer_size("B") == 16, "channel B must stay intact"


# ---------------------------------------------------------------------------
# S4 (HIGH): benign sub-tolerance backward jitter must DROP the single sample,
# not reset-storm the buffer below min_points (which silently disables the
# 5 K/min protection). A genuine NTP step still resets.
# ---------------------------------------------------------------------------


def test_small_backward_jitter_drops_sample_keeps_buffer():
    """Repeated ~0.2 s backward jitter/reordering on a 2 s cadence must not reset
    the buffer. The offending sample is dropped; the buffer keeps growing from
    the forward samples and the rate stays available."""
    est = RateEstimator(window_s=120.0, min_points=8, min_span_s=30.0)
    est.push(CH, T0, 4.0)
    for i in range(1, 40):
        t_forward = T0 + POLL_S * i
        est.push(CH, t_forward, 4.0 + RATE_PER_SEC * (t_forward - T0))
        # a backward-jittered duplicate 0.2 s before the last accepted sample
        t_back = t_forward - 0.2
        est.push(CH, t_back, 4.0 + RATE_PER_SEC * (t_back - T0))
    assert est.buffer_size(CH) >= 30, (
        f"sub-tolerance backward jitter must not reset the buffer, got {est.buffer_size(CH)}"
    )
    rate = est.get_rate(CH)
    assert rate is not None and rate > 5.0, "rate must stay available through jitter"


def test_large_backward_step_still_resets():
    """A genuine NTP step (backward beyond the jitter tolerance) still resets."""
    est = RateEstimator(window_s=120.0, min_points=8, min_span_s=30.0)
    _fill(est, 16)
    est.push(CH, T0 - 60.0, 4.0)  # -60 s step, far beyond tolerance
    assert est.buffer_size(CH) == 1, "a -60 s step must still reset (NTP step)"
