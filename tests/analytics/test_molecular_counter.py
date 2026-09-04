"""The counter has to say "you are not pumping" while the gauge looks good.

That is the entire reason it exists. On 2026-09-03 the pressure gauge fell from
0.0758 to 0.0523 mbar over ten hours — a 31% decline that reads as steady
progress — while the chamber was actually gaining molecules the whole time,
because every sensor was also falling to 0.70 of its starting temperature. The
operator stopped the run on that reasoning, reconstructed by hand at hour nine.
These tests hold the plugin to producing it continuously, and to the real
numbers from that run.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from cryodaq.drivers.base import ChannelStatus, Reading

pytest.importorskip("plugins.molecular_counter", reason="plugins/ not importable")

from plugins.molecular_counter import MolecularCounter  # noqa: E402

_BULK = ["Т1", "Т2", "Т3", "Т7"]
_P = "VSP63D_1/pressure"


def _reading(channel: str, value: float, *, age_s: float = 0.0, status=ChannelStatus.OK) -> Reading:
    return Reading(
        timestamp=datetime.now(UTC) - timedelta(seconds=age_s),
        instrument_id="test",
        channel=channel,
        value=value,
        unit="",
        status=status,
        metadata={},
    )


def _counter(*, bulk=None, interval=0.0) -> MolecularCounter:
    c = MolecularCounter()
    c.configure(
        {
            "pressure_channel": _P,
            "bulk_sensors": _BULK if bulk is None else bulk,
            "update_interval_s": interval,
        }
    )
    return c


def _batch(p: float, t: float, *, age_s: float = 0.0) -> list[Reading]:
    return [_reading(_P, p, age_s=age_s)] + [_reading(ch, t, age_s=age_s) for ch in _BULK]


def _run(counter: MolecularCounter, batch: list[Reading]):
    return asyncio.run(counter.process(batch))


# ==========================================================================
# the case the instrument exists for
# ==========================================================================
def test_falling_pressure_that_is_only_cooling_reports_no_gas_removed() -> None:
    """Pressure down 31%, temperature down 30%, and NOTHING has been pumped.

    This is the 2026-09-03 signature. A pressure readout alone calls this
    progress; the counter has to call it standing still.
    """

    c = _counter()
    first = _run(c, _batch(0.07579, 295.4))
    assert first and first[0].value == pytest.approx(100.0), "baseline is 100%"

    later = _run(c, _batch(0.05234, 211.8))
    assert later
    n = later[0].value

    assert n == pytest.approx(96.3, abs=0.5), "the real h=7 figure from that run"
    assert n > 90.0, "a 31% pressure fall must NOT read as 31% of the gas removed"


def test_the_real_run_shows_the_chamber_refilling() -> None:
    """Replays measured (P, T_bulk) pairs from 2026-09-03 hour by hour.

    The inventory bottoms out near hour one and climbs back past its starting
    value — the finding that ended the run. If this ever goes monotonic, the
    temperature correction has been lost.
    """

    # (elapsed_h, P mbar, T_bulk K) as recorded, and the hand-computed answer.
    measured = [
        (0.0, 0.07579, 295.4, 100.0),
        (1.0, 0.05979, 289.9, 80.4),
        (3.0, 0.05613, 264.6, 82.7),
        (5.0, 0.05365, 236.7, 88.4),
        (7.0, 0.05234, 211.8, 96.3),
    ]

    c = _counter()
    seen = []
    for _h, p, t, _expected in measured:
        out = _run(c, _batch(p, t))
        assert out, "every valid sample must produce a reading"
        seen.append(out[0].value)

    for (_h, _p, _t, expected), got in zip(measured, seen, strict=True):
        assert got == pytest.approx(expected, abs=0.6)

    assert seen[1] < seen[0], "gas is genuinely removed early — the water dump"
    assert seen[2] > seen[1] and seen[3] > seen[2] and seen[4] > seen[3], "then it comes back"
    assert seen[4] > 95.0, "back to where it started while the gauge showed a 31% fall"


def test_pumping_at_constant_temperature_is_reported_as_pumping() -> None:
    """The counter must not explain away real progress either."""

    c = _counter()
    _run(c, _batch(0.10, 295.0))
    out = _run(c, _batch(0.05, 295.0))
    assert out[0].value == pytest.approx(50.0, abs=0.1)


class _Clock:
    """Drives the plugin's notion of now, so samples can be spaced in time."""

    def __init__(self, start: datetime) -> None:
        self.t = start

    def now(self, tz=None):  # noqa: ANN001 - mirrors datetime.now(UTC)
        return self.t

    def advance(self, seconds: float) -> None:
        self.t = self.t + timedelta(seconds=seconds)


def _spaced_run(counter, samples, *, step_s: float):
    """Feed samples step_s apart, with readings dated to match."""

    import plugins.molecular_counter as mod

    clock = _Clock(datetime.now(UTC))
    original = mod.datetime
    mod.datetime = clock  # type: ignore[assignment]
    try:
        out = []
        for p, t in samples:
            batch = [
                Reading(
                    timestamp=clock.t,
                    instrument_id="test",
                    channel=ch,
                    value=v,
                    unit="",
                    status=ChannelStatus.OK,
                    metadata={},
                )
                for ch, v in [(_P, p)] + [(s, t) for s in _BULK]
            ]
            out = asyncio.run(counter.process(batch))
            clock.advance(step_s)
        return out
    finally:
        mod.datetime = original  # type: ignore[assignment]


def test_rate_is_positive_while_the_chamber_fills() -> None:
    c = _counter()
    filling = [(0.0500, 250.0), (0.0520, 250.0), (0.0540, 250.0), (0.0560, 250.0), (0.0580, 250.0)]
    out = _spaced_run(c, filling, step_s=120.0)

    rate = out[0].metadata["rate_pct_per_h"]
    assert rate is not None, "480 s of history is enough to speak about a rate"
    assert rate > 0.0, "filling must read as a positive rate"


def test_a_burst_of_samples_reports_no_rate_rather_than_a_wild_one() -> None:
    """Regression: replaying the 2026-09-03 database printed -105096647 %/h.

    Twenty-three samples arrived inside one second, so the least-squares slope
    was fitted over a span of milliseconds. Real acquisition at 60 s cannot do
    this, but a replay or a backfill can — and a readout that can print nonsense
    under any input is not an instrument. The value is still published; only the
    rate is withheld.
    """

    c = _counter()
    burst = [(0.050 + 0.001 * i, 250.0) for i in range(23)]
    out = _spaced_run(c, burst, step_s=0.01)

    assert out, "the inventory value itself is still reported"
    assert out[0].metadata["rate_pct_per_h"] is None, "no time span, no rate"


def test_the_rate_appears_once_the_span_is_real() -> None:
    """Just under the span reports nothing; just over it reports a number."""

    from plugins.molecular_counter import _MIN_RATE_SPAN_S

    short = _spaced_run(_counter(), [(0.05, 250.0)] * 4, step_s=_MIN_RATE_SPAN_S / 10.0)
    assert short[0].metadata["rate_pct_per_h"] is None

    long = _spaced_run(_counter(), [(0.05, 250.0)] * 4, step_s=_MIN_RATE_SPAN_S / 2.0)
    assert long[0].metadata["rate_pct_per_h"] is not None


# ==========================================================================
# refusing to compute
# ==========================================================================
def test_it_ships_unbound_and_computes_nothing() -> None:
    """Which sensors represent the gas volume is a per-run choice.

    Same rule as ThermalCalculator: a hardcoded default would keep emitting a
    confident number for whichever channels were written down last.
    """

    c = MolecularCounter()
    c.configure({"pressure_channel": _P, "bulk_sensors": []})
    assert _run(c, _batch(0.05, 250.0)) == []


def test_a_stale_input_produces_nothing() -> None:
    """Fails closed: one old input corrupts a derived quantity, not just ages it."""

    c = _counter()
    _run(c, _batch(0.0758, 295.0))
    assert _run(c, _batch(0.0523, 211.0, age_s=600.0)) == []


def test_the_no_reading_sentinel_is_not_a_temperature() -> None:
    """-8.888e+88 is persisted for dead channels and must never reach the mean."""

    c = _counter()
    _run(c, _batch(0.0758, 295.0))

    batch = [_reading(_P, 0.0523)]
    batch.append(_reading("Т1", -8.888e88))
    batch += [_reading(ch, 211.8) for ch in _BULK[1:]]
    out = _run(c, batch)

    assert out
    assert out[0].metadata["sensors_used"] == 3, "the sentinel channel is excluded"
    assert out[0].value == pytest.approx(96.3, abs=0.6), "and does not distort the mean"


def test_a_non_ok_reading_never_enters_the_calculation() -> None:
    """A faulted frame is discarded, not absorbed.

    The last good value keeps standing while it is still inside the freshness
    window — one bad frame should not blank the readout — but the faulted number
    itself must never reach the arithmetic.
    """

    c = _counter()
    _run(c, _batch(0.0758, 295.0))

    bad = [_reading(_P, 0.0523, status=ChannelStatus.SENSOR_ERROR)] + [_reading(ch, 211.8) for ch in _BULK]
    out = _run(c, bad)

    assert out
    assert out[0].metadata["pressure_mbar"] == pytest.approx(0.0758), (
        "the faulted pressure must be discarded, leaving the last good value"
    )


def test_when_the_last_good_value_ages_out_the_readout_stops() -> None:
    """The cache covers a hiccup, not an outage. Fails closed once it expires."""

    c = _counter()
    _run(c, _batch(0.0758, 295.0))
    stale = [_reading(_P, 0.0523, age_s=600.0)] + [_reading(ch, 211.8) for ch in _BULK]
    assert _run(c, stale) == []


# ==========================================================================
# the baseline is never ambiguous
# ==========================================================================
def test_every_value_carries_the_baseline_it_is_relative_to() -> None:
    c = _counter()
    out = _run(c, _batch(0.0758, 295.4))
    meta = out[0].metadata

    assert meta["baseline_epoch"] is not None
    assert meta["baseline_pressure_mbar"] == pytest.approx(0.0758)
    assert meta["baseline_t_bulk_k"] == pytest.approx(295.4, abs=0.1)
    assert meta["model"] == "single_zone_apparent"
    # No lower-bound guarantee is claimed any more: the mean of selected sensors
    # is not the volume-weighted effective gas temperature, and a Pirani reading
    # is composition dependent. See the 47b6c9ca review.
    assert "is_lower_bound" not in meta


def test_rebinding_the_sensors_drops_the_baseline() -> None:
    """A baseline taken against one sensor set means nothing against another."""

    c = _counter()
    _run(c, _batch(0.10, 295.0))
    assert c.baseline_epoch is not None

    c.configure({"pressure_channel": _P, "bulk_sensors": ["Т1", "Т2"], "update_interval_s": 0.0})
    assert c.baseline_epoch is None, "rebinding must not carry the old 100% across"

    out = _run(c, [_reading(_P, 0.05), _reading("Т1", 250.0), _reading("Т2", 250.0)])
    assert out[0].value == pytest.approx(100.0), "the next sample becomes the new baseline"


def test_reset_baseline_makes_the_next_sample_the_new_hundred() -> None:
    """The operator owns what 100% means — normally the start of a cooldown."""

    c = _counter()
    _run(c, _batch(0.10, 295.0))
    assert _run(c, _batch(0.05, 295.0))[0].value == pytest.approx(50.0, abs=0.1)

    c.reset_baseline()
    assert _run(c, _batch(0.05, 295.0))[0].value == pytest.approx(100.0)


def test_it_never_rebaselines_on_its_own() -> None:
    """A baseline that moves unasked makes every earlier reading incomparable."""

    c = _counter()
    _run(c, _batch(0.10, 295.0))
    epoch = c.baseline_epoch
    for p in (0.09, 0.08, 0.07, 0.20, 0.30):
        _run(c, _batch(p, 295.0))
    assert c.baseline_epoch == epoch, "even a large excursion must not move the zero"


# ==========================================================================
# it is an instrument, not a controller
# ==========================================================================
def test_it_emits_a_measurement_and_nothing_else() -> None:
    """No thresholds, no verdict, no action. A lab is run by its operator."""

    c = _counter()
    out = _run(c, _batch(0.0758, 295.4))
    metric = out[0]

    assert metric.metric == "gas_inventory"
    assert metric.unit == "%"
    forbidden = {"alarm", "severity", "action", "verdict", "ok", "ready", "go_no_go", "threshold"}
    assert forbidden.isdisjoint(metric.metadata), "the counter must not judge"


# ==========================================================================
# what 100% means is a property of the phase
# ==========================================================================
def test_entering_a_phase_rezeros_the_counter() -> None:
    """One fixed zero cannot answer both questions.

    During `vacuum` the useful zero is the start of pumping — how much of the
    load has been removed, which is the number for drying the MLI. During
    `cooldown` it is the start of cooling — whether the chamber is holding what
    it had, which is what made 2026-09-03 legible (100% -> 80% -> 118%, crossing
    back above its own start). Zeroed at pump-down, that run reads 3% -> 3.5%
    and the crossing is invisible.
    """

    c = _counter()
    _run(c, _batch(0.10, 295.0))
    assert _run(c, _batch(0.05, 295.0))[0].value == pytest.approx(50.0, abs=0.1)

    c.notify_phase_change("cooldown")

    out = _run(c, _batch(0.05, 295.0))
    assert out[0].value == pytest.approx(100.0), "the phase change is the new zero"
    assert out[0].metadata["baseline_reason"] == "начало захолаживания"


def test_the_zero_is_never_moved_by_the_data() -> None:
    """A phase change is an operator action. Readings are not."""

    c = _counter()
    _run(c, _batch(0.10, 295.0))
    epoch = c.baseline_epoch
    for p in (0.30, 0.01, 0.50):
        _run(c, _batch(p, 295.0))
    assert c.baseline_epoch == epoch, "no excursion may re-zero the counter"


def test_an_unknown_phase_leaves_a_good_baseline_alone() -> None:
    c = _counter()
    _run(c, _batch(0.10, 295.0))
    epoch = c.baseline_epoch

    for phase in ("preparation", "teardown", "", None, "нечто"):
        c.notify_phase_change(phase)
    assert c.baseline_epoch == epoch, "an irrelevant phase is not a reason to discard a measurement"


def test_every_value_says_what_its_hundred_percent_was() -> None:
    """A percentage against a forgotten reference is not a measurement."""

    c = _counter()
    c.notify_phase_change("vacuum")
    meta = _run(c, _batch(0.10, 295.0))[0].metadata

    assert meta["baseline_reason"] == "начало откачки"
    assert isinstance(meta["baseline_epoch"], float)


def test_each_phase_carries_its_own_meaning() -> None:
    c = _counter()
    for phase, label in (
        ("vacuum", "начало откачки"),
        ("cooldown", "начало захолаживания"),
        ("measurement", "начало измерения"),
        ("warmup", "начало отогрева"),
    ):
        c.notify_phase_change(phase)
        assert _run(c, _batch(0.05, 250.0))[0].metadata["baseline_reason"] == label


# ==========================================================================
# the rate must survive five decades
# ==========================================================================
# Sampled inside _RATE_WINDOW_S (1800 s) at a cadence a real run would produce.
_STEP_S = 300.0


def _halving_series(p0: float, *, n: int = 7, step_s: float = _STEP_S):
    """Pressure halving every hour, at constant temperature (so N ∝ P)."""

    return [(p0 * 0.5 ** ((i * step_s) / 3600.0), 250.0) for i in range(n)]


def test_the_rate_is_relative_to_what_is_in_the_chamber_now() -> None:
    """100·d(ln N)/dt, not a slope of percent-of-baseline.

    Zero at 1 bar and by 1e-2 mbar the inventory is 0.001% of baseline. A slope
    of percent-of-baseline is then a rounding error, and a further full decade of
    pumping — the most important thing that could happen — reads as a flat line.
    A log slope means the same thing at every scale.
    """

    # The same fractional decay — halving per hour — sampled inside the rate
    # window, once near the baseline and once five decades below it.
    near = _spaced_run(_counter(), _halving_series(0.10), step_s=_STEP_S)
    deep = _spaced_run(_counter(), _halving_series(1.0e-6), step_s=_STEP_S)

    r_near = near[0].metadata["rate_pct_per_h"]
    r_deep = deep[0].metadata["rate_pct_per_h"]
    assert r_near is not None and r_deep is not None
    assert r_near < 0 and r_deep < 0, "both are pumping down"
    assert r_near == pytest.approx(r_deep, rel=0.05), (
        "the same fractional decay must report the same rate at any absolute level"
    )


def test_a_halving_per_hour_reads_as_about_minus_69_percent() -> None:
    """ln(0.5) = -0.693, so 100·d(ln N)/dt is -69.3 %/h. Anchors the units."""

    out = _spaced_run(_counter(), _halving_series(0.10), step_s=_STEP_S)
    assert out[0].metadata["rate_pct_per_h"] == pytest.approx(-69.3, abs=1.0)


def test_the_rate_is_declared_fractional() -> None:
    """Consumers must not read it as percent-of-baseline."""

    out = _spaced_run(_counter(), [(0.05, 250.0)] * 4, step_s=600.0)
    assert out[0].metadata["rate_is_fractional"] is True
