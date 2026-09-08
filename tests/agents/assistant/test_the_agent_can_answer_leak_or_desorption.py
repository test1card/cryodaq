"""The operator asked the assistant why the pressure was rising. It could not say.

2026-09-08, verbatim: "я не вижу, замедляется ли темп (экспоненциальный спад →
десорбция влаги, источник исчерпывается) или он ровный (постоянный натек через
щель/соединение)". It had one slope over one window and no history of that slope.

Two things were in the way.

The window was not what it claimed. Ten thousand rows against a channel written
every two seconds reach back five and a half hours, so a six-hour request came
back covering 5.6 — and a twenty-four-hour request would have come back covering
the same 5.6. Measured against the running engine: unbucketed, 9996 points over
5.6 h; bucketed at 29 s, 2956 points over 24.0 h.

And one slope cannot show a shape. A leak holds its rate; desorption exhausts
its source and decays. Three consecutive rates say which.
"""

from __future__ import annotations

from cryodaq.agents.assistant.query.adapters.sqlite_adapter import (
    _TREND_POINT_BUDGET,
    _segment_rates,
    _trend_bucket,
)
from cryodaq.agents.assistant.query.agent import _format_trends
from cryodaq.agents.assistant.query.schemas import ChannelTrend

_H = 3600.0


def _ramp(hours: float, rate: float, start: float = 0.0, step: float = 60.0, t0: float = 0.0):
    n = int(hours * _H / step)
    return [(t0 + i * step, start + rate * (i * step) / _H) for i in range(n + 1)]


# --- the window is real ----------------------------------------------------


def test_a_day_long_window_fits_the_budget() -> None:
    for window in (360, 720, 1440):
        assert window * 60 / _trend_bucket(window) <= _TREND_POINT_BUDGET


def test_the_trend_asks_for_a_bucket() -> None:
    import inspect

    from cryodaq.agents.assistant.query.adapters import sqlite_adapter

    source = inspect.getsource(sqlite_adapter)
    at = source.index('"cmd": "readings_history"')
    assert "bucket_s" in source[at : at + 1400], "the trend still buys the last N rows"


def test_the_composite_asks_for_a_day() -> None:
    from cryodaq.agents.assistant.query.adapters.composite_adapter import _TREND_WINDOW_MINUTES

    assert _TREND_WINDOW_MINUTES >= 1440, "six hours cannot show whether a rate decays"


# --- the shape ------------------------------------------------------------


def test_a_constant_rate_reads_as_holding() -> None:
    trend = ChannelTrend(
        channel="P",
        window_minutes=1440,
        n_samples=100,
        first_value=0.0,
        last_value=1.0,
        span_s=18 * _H,
        rate_per_hour=0.1,
        slope_stderr_per_hour=0.001,
        segments=((0.1054, 0.0011), (0.1049, 0.0020), (0.1051, 0.0017)),
    )
    text = _format_trends({"P": trend})

    for rate, err in trend.segments:
        assert f"{rate:+.3g}" in text, f"segment rate {rate} never reached the operator"
        assert f"{err:.2g}" in text, f"segment error {err} was dropped"


def test_a_decaying_rate_reads_as_falling() -> None:
    """The chamber's own numbers on 2026-09-08."""
    trend = ChannelTrend(
        channel="P",
        window_minutes=1440,
        n_samples=100,
        first_value=0.0,
        last_value=1.0,
        span_s=18 * _H,
        rate_per_hour=0.1,
        slope_stderr_per_hour=0.001,
        segments=((0.1054, 0.0011), (0.1016, 0.0020), (0.0971, 0.0017)),
    )
    text = _format_trends({"P": trend})

    # The numbers say it falls; the text must carry the numbers rather than a
    # word computed from an error model that does not hold on sensor data.
    for rate, err in trend.segments:
        assert f"{rate:+.3g}" in text
        assert f"{err:.2g}" in text


def test_a_change_inside_the_noise_is_not_called_a_trend() -> None:
    trend = ChannelTrend(
        channel="P",
        window_minutes=1440,
        n_samples=100,
        first_value=0.0,
        last_value=1.0,
        span_s=18 * _H,
        rate_per_hour=0.1,
        slope_stderr_per_hour=0.05,
        segments=((0.105, 0.02), (0.101, 0.02), (0.098, 0.02)),
    )

    text = _format_trends({"P": trend})

    # These intervals permit a fall of about a third. Saying the rate "holds"
    # turns a failure to measure into a claim of constancy, which is how a
    # decaying source gets mistaken for a steady leak.
    for verdict in ("темп держится", "темп падает", "темп растёт"):
        assert verdict not in text, f"a change inside the noise was reported as {verdict!r}"
    for rate, err in trend.segments:
        assert f"{rate:+.3g}" in text
        assert f"{err:.2g}" in text


def test_one_segment_says_nothing() -> None:
    trend = ChannelTrend(
        channel="P",
        window_minutes=1440,
        n_samples=100,
        first_value=0.0,
        last_value=1.0,
        span_s=_H,
        rate_per_hour=0.1,
        slope_stderr_per_hour=0.001,
        segments=((0.1, 0.001),),
    )

    text = _format_trends({"P": trend})

    for verdict in ("темп держится", "темп падает", "темп растёт"):
        assert verdict not in text, "one segment cannot describe a shape"


# --- the segments are split by TIME ---------------------------------------


def test_segments_are_split_by_time_not_by_sample_count() -> None:
    """An uneven write rate would otherwise make one third cover twice the hours
    of another, and look like a change that is really a difference in coverage."""
    dense = _ramp(2.0, 0.1, step=10.0)
    sparse = _ramp(4.0, 0.1, start=0.2, step=600.0, t0=dense[-1][0] + 600.0)
    rates = _segment_rates(dense + sparse, parts=3)

    assert len(rates) == 3
    for rate, _ in rates:
        assert abs(rate - 0.1) < 0.02, f"a segment measured {rate}, not the true 0.1"


def test_a_window_too_thin_to_split_returns_nothing() -> None:
    assert _segment_rates(_ramp(1.0, 0.1, step=900.0), parts=3) == ()


def test_a_decaying_ramp_shows_falling_segments() -> None:
    pairs = []
    t, value = 0.0, 0.0
    for hour in range(18):
        rate = 0.11 - 0.001 * hour
        for _ in range(60):
            value += rate / 60.0
            t += 60.0
            pairs.append((t, value))
    rates = _segment_rates(pairs, parts=3)

    assert len(rates) == 3
    assert rates[0][0] > rates[-1][0], "a decaying ramp did not show as decaying"


# --- what the agent is shown ----------------------------------------------


def test_the_rendered_trend_carries_the_shape() -> None:
    trend = ChannelTrend(
        channel="VSP63D_1/pressure",
        window_minutes=1440,
        n_samples=2956,
        first_value=1.5,
        last_value=2.4,
        span_s=24 * _H,
        rate_per_hour=0.1017,
        slope_stderr_per_hour=0.00007,
        segments=((0.1054, 0.0011), (0.1016, 0.0020), (0.0971, 0.0017)),
    )
    rendered = _format_trends({"давление": trend})

    assert "по третям окна" in rendered
    # THE NUMBERS AND THEIR ERRORS, NOT A WORD. A leak holds its rate and
    # desorption decays, and this line is where the operator reads which. It
    # used to end "— темп падает", a verdict built from OLS standard errors on
    # autocorrelated samples; the numbers say the same thing without claiming
    # a confidence the error model cannot support.
    for rate, err in trend.segments:
        assert f"{rate:+.3g}" in rendered
        assert f"{err:.2g}" in rendered
    assert "темп падает" not in rendered


def test_an_absurd_sigma_is_words_not_digits() -> None:
    """The assistant told an operator "сигнал 1495σ" — noise in the costume of
    precision. Past ten sigma the only honest content is "not noise"."""
    trend = ChannelTrend(
        channel="P",
        window_minutes=1440,
        n_samples=9000,
        first_value=0.0,
        last_value=1.0,
        span_s=18 * _H,
        rate_per_hour=0.1,
        slope_stderr_per_hour=0.00007,
    )
    rendered = _format_trends({"давление": trend})

    assert "1428" not in rendered and "σ" not in rendered
    assert "уверенн" in rendered


def test_an_ordinary_sigma_is_still_a_number() -> None:
    trend = ChannelTrend(
        channel="P",
        window_minutes=60,
        n_samples=100,
        first_value=0.0,
        last_value=1.0,
        span_s=_H,
        rate_per_hour=0.1,
        slope_stderr_per_hour=0.033,
    )
    assert "3σ" in _format_trends({"давление": trend})


async def test_the_adapter_actually_fills_the_segments() -> None:
    """Written after a negative control failed to fail.

    Every other test here builds a `ChannelTrend` by hand, so removing the call
    that populates `segments` in the adapter left them all green. The defect
    would have been in the one line nothing exercised.
    """
    from cryodaq.agents.assistant.query.adapters.sqlite_adapter import SQLiteAdapter

    pairs = []
    t, value = 1_000_000.0, 0.0
    for hour in range(18):
        rate = 0.11 - 0.001 * hour
        for _ in range(60):
            value += rate / 60.0
            t += 60.0
            pairs.append([t, value])

    class _Client:
        async def call(self, _cmd: dict) -> dict:
            return {"ok": True, "data": {"VSP63D_1/pressure": pairs}}

    trend = await SQLiteAdapter(_Client()).trend("VSP63D_1/pressure", 1440)

    assert trend is not None and trend.available
    assert len(trend.segments) == 3, "the adapter did not compute the segments"
    # The data above was built with a rate decaying 0.001/ч per hour, so the
    # first third must sit well above the last. Asserted on the numbers, not on
    # a verdict: the verdict is what this review removed.
    first, last = trend.segments[0][0], trend.segments[-1][0]
    assert first - last > 0.010, f"the decay did not survive segmentation: {trend.segments}"
    # And the quadratic, for the same reason the segments are checked here: a
    # control that removed this line from the adapter left every hand-built
    # ChannelTrend test green.
    assert trend.slope_change is not None, "the adapter did not fit the quadratic"
    change, _ = trend.slope_change
    assert abs(change - (-0.018)) < 0.003, f"slope change measured {change}"


# --- what the review with astra changed ------------------------------------


def test_a_straight_line_shows_no_change_in_slope() -> None:
    from cryodaq.agents.assistant.query.adapters.sqlite_adapter import _centred_quadratic

    change, _ = _centred_quadratic([(i * 60.0, 0.1 * i / 60.0) for i in range(400)])
    assert abs(change) < 1e-6


def test_a_decaying_ramp_shows_the_slope_change_it_was_built_with() -> None:
    """0.11 falling by 0.001 per hour over 18 hours is −0.018 mbar/h across it."""
    from cryodaq.agents.assistant.query.adapters.sqlite_adapter import _centred_quadratic

    pairs = []
    t, value = 0.0, 0.0
    for hour in range(18):
        rate = 0.11 - 0.001 * hour
        for _ in range(60):
            value += rate / 60.0
            t += 60.0
            pairs.append((t, value))

    change, _ = _centred_quadratic(pairs)
    assert abs(change - (-0.018)) < 0.002, f"measured {change}, expected about -0.018"


def test_a_window_too_thin_for_a_quadratic_returns_nothing() -> None:
    from cryodaq.agents.assistant.query.adapters.sqlite_adapter import _centred_quadratic

    assert _centred_quadratic([(0.0, 1.0), (60.0, 1.1), (120.0, 1.2)]) is None


def test_the_rendered_trend_states_the_uncertainty_assumption() -> None:
    """Pointwise intervals under an independent-residual model, re-examined
    hourly, do not give simultaneous coverage. Said once, where the numbers are.
    """
    trend = ChannelTrend(
        channel="P",
        window_minutes=1440,
        n_samples=2956,
        first_value=1.5,
        last_value=2.4,
        span_s=24 * _H,
        rate_per_hour=0.1017,
        slope_stderr_per_hour=0.00007,
        slope_change=(-0.0083, 0.0031),
    )
    rendered = _format_trends({"давление": trend})

    assert "изменение темпа по окну" in rendered
    assert "независимых остатков" in rendered
    assert "одновременного покрытия" in rendered


def test_the_prompt_forbids_naming_a_mechanism_from_the_curve() -> None:
    """A nearly straight curve does not exclude a slowly decaying source, and an
    8% slope change is not an 8% share of one. The agent may describe the shape;
    it may not name the cause."""
    from cryodaq.agents.assistant.query.prompts import FORMAT_RESPONSE_SYSTEM

    assert "механизм по этим данным не разделяется" in FORMAT_RESPONSE_SYSTEM
    assert "не исключает медленно спадающий" in FORMAT_RESPONSE_SYSTEM


def test_the_prompt_offers_the_experiment_that_would_discriminate() -> None:
    """Refusing to answer is only half an answer; the operator can be told what
    would settle it, with its own caveats."""
    from cryodaq.agents.assistant.query.prompts import FORMAT_RESPONSE_SYSTEM

    assert "повторить откачку" in FORMAT_RESPONSE_SYSTEM
    assert "адсорбироваться" in FORMAT_RESPONSE_SYSTEM, "the caveat is missing"
    assert "трогать железо — нет" in FORMAT_RESPONSE_SYSTEM


def test_consecutive_thirds_do_not_share_a_sample(monkeypatch) -> None:
    """The docstring promises NON-OVERLAPPING; the slicing was inclusive at both
    ends, so a sample sitting exactly on an internal boundary was fitted into
    two thirds at once. Sharing it correlates the errors the caller then treats
    as independent, and lets one boundary outlier bend two of the three rates.
    """

    from cryodaq.agents.assistant.query.adapters import sqlite_adapter

    # The parts divide the span between the FIRST and LAST samples, so a
    # boundary lands on a sample only when that span divides evenly: 31 points
    # spaced 60 s span 1800 s, and the thirds fall exactly on samples 10 and 20.
    pairs = [(float(index) * 60.0, 0.1 * index) for index in range(31)]
    seen: list[int] = []
    real_fit = sqlite_adapter._fit_rate

    def _counting_fit(chunk):
        seen.append(len(chunk))
        return real_fit(chunk)

    monkeypatch.setattr(sqlite_adapter, "_fit_rate", _counting_fit)
    sqlite_adapter._segment_rates(pairs, parts=3)

    assert sum(seen) == len(pairs), (
        f"the thirds used {sum(seen)} samples out of {len(pairs)}: {seen}"
    )
