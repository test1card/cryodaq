"""Three things visible in seven live reports and in no test.

The operator pasted the hourly reports from the deployed build on 2026-09-08.
Reading them showed what the test suite could not:

- Summaries ended mid-word: "пока скорость не уй…", "давление чуть дышит,…".
  A sentence broken inside a word reads as a fault in the message rather than a
  summary that ran long.
- The caption said "Давление: 2.09e+00 мбар" and the summary directly beneath it
  said 2.051 — the same quantity, twenty-four minutes apart, with nothing
  explaining why. The bulletin free-ran from process start while the report's
  slot runs from the clock, so their hours drifted apart by however long ago the
  assistant happened to be restarted.
"""

from __future__ import annotations

import datetime as dt

from cryodaq.agents.assistant_main import _PERIODIC_TICK_LEAD_S, _seconds_until_next_tick
from cryodaq.reporting.periodic_renderer import MAX_CAPTION_CODEPOINTS, _with_summary

_HOUR = 3600.0


def _at(hhmmss: str) -> float:
    return dt.datetime.strptime("2026-09-08 " + hhmmss, "%Y-%m-%d %H:%M:%S").timestamp()


def _fires_at(now: float, interval: float = _HOUR) -> str:
    return dt.datetime.fromtimestamp(now + _seconds_until_next_tick(interval, now)).strftime("%M:%S")


# --- the tick is on the clock ----------------------------------------------


def test_the_bulletin_fires_at_the_same_minute_whenever_it_started() -> None:
    """Free-running, the hour depended on when the process last restarted."""
    assert _fires_at(_at("07:00:00")) == _fires_at(_at("07:23:41"))
    assert _fires_at(_at("07:00:00")) == _fires_at(_at("07:41:07"))


def test_it_fires_before_the_hour_so_its_note_is_on_disk() -> None:
    """The report renders on the hour and reads the note; a bulletin firing at
    the same instant races it."""
    fired = _seconds_until_next_tick(_HOUR, _at("07:00:00")) + _at("07:00:00")
    boundary = _at("08:00:00")
    lead = boundary - fired
    assert 0 < lead <= _PERIODIC_TICK_LEAD_S


def test_a_restart_just_after_the_tick_does_not_fire_twice() -> None:
    just_after = _at("07:55:01")
    delay = _seconds_until_next_tick(_HOUR, just_after)
    assert delay > _HOUR / 2, "a restart would have produced two bulletins in a minute"


def test_the_lead_never_swallows_a_short_interval() -> None:
    """A five-minute lead on a ten-minute interval would fire almost at once."""
    for interval in (600.0, 900.0, 1800.0, _HOUR):
        delay = _seconds_until_next_tick(interval, _at("07:00:00"))
        assert 0 < delay <= interval


def test_a_disabled_interval_asks_for_no_sleep() -> None:
    assert _seconds_until_next_tick(0.0, _at("07:00:00")) == 0.0


# --- the caption stops at a word -------------------------------------------


def test_a_long_summary_is_cut_at_a_word() -> None:
    """The caption length is DERIVED so the character cut lands inside a word.

    The first version of this test guessed a length, the guess happened to fall
    on a space, and it passed with the fix removed. The operator's own example
    ended "пока скорость не уй…", mid-word, which is the case worth pinning.
    """
    summary = (
        "Коротко: давление на VSP63D_1 чуть дышит, всё остальное спит. Наблюдать, пока скорость не уйдёт за предел."
    )
    inside = summary.index("уйдёт") + 2  # two characters into the word
    caption = "x" * (MAX_CAPTION_CODEPOINTS - inside - 3)
    assert summary[inside - 1] != " " and summary[inside] != " ", "the cut is not mid-word"

    tail = _with_summary(caption, summary)[len(caption) :]

    assert tail.endswith("…")
    body = tail.rstrip("…").rstrip()
    assert body.split()[-1] in summary.split(), f"cut mid-word: {body[-20:]!r}"


def test_a_summary_that_fits_is_untouched() -> None:
    caption = "Отчёт"
    summary = "На стенде тихо, давление растёт ровно."

    assert _with_summary(caption, summary).endswith(summary)


def test_one_very_long_word_is_cut_rather_than_dropped() -> None:
    """Backing off to a word boundary must not throw away the whole clause."""
    caption = "x" * (MAX_CAPTION_CODEPOINTS - 70)
    summary = "Й" * 200

    tail = _with_summary(caption, summary)[len(caption) :]

    assert "Й" in tail and tail.endswith("…")


# --- what review found in the repairs --------------------------------------


def test_a_cut_that_already_lands_on_a_word_keeps_that_word() -> None:
    """Backing off unconditionally dropped a complete word for nothing.

    A prefix ending in "Температура стабильна" became "Температура…" — a word
    thrown away because the code retreated to the previous space whether or not
    the cut had broken anything. The boundary is chosen past the forty-character
    floor below which the summary is dropped entirely.
    """
    summary = (
        "Температура держится ровно, разброс в пределах сотых кельвина, "
        "и давление растёт с прежней скоростью уже двенадцатый час подряд."
    )
    at_boundary = summary.index(" и давление")
    assert at_boundary > 40, "the cut must sit above the drop-the-summary floor"
    caption = "x" * (MAX_CAPTION_CODEPOINTS - at_boundary - 3)

    tail = _with_summary(caption, summary)[len(caption) :]

    assert tail, "the summary was dropped entirely"
    assert "кельвина" in tail, f"a complete word was dropped: {tail!r}"


def test_the_tick_rechecks_the_clock_after_sleeping() -> None:
    """The delay comes from the WALL clock and the sleep is monotonic.

    A step back fires the bulletin twice for one report boundary; a step forward
    fires it after the report has already rendered. Neither is visible without
    looking at the clock again.
    """
    import inspect

    from cryodaq.agents import assistant_main

    source = inspect.getsource(assistant_main._periodic_report_tick)
    assert "_TICK_RECHECKS" in source, "the tick sleeps once and never looks again"
    at = source.index("_seconds_until_next_tick")
    assert "break" in source[at : at + 300]

    from cryodaq.agents.assistant_main import _TICK_RECHECKS

    assert 1 < _TICK_RECHECKS <= 10, "an unbounded re-check spins whenever the sleep returns without time passing"


async def test_a_clock_step_backwards_does_not_fire_twice() -> None:
    """Simulated: the clock jumps back while the tick sleeps."""
    import asyncio

    from cryodaq.agents import assistant_main
    from cryodaq.agents.assistant_main import _seconds_until_next_tick

    fired: list[float] = []
    clock = {"t": _at("07:54:00")}

    async def fake_sleep(delay: float) -> None:
        clock["t"] += delay
        if len(fired) == 0:
            clock["t"] -= 1800.0  # the clock steps back half an hour mid-sleep
        fired.append(delay)
        await asyncio.sleep(0)
        if len(fired) > 6:
            raise asyncio.CancelledError

    delays = []
    try:
        while len(delays) < 3:
            delay = _seconds_until_next_tick(_HOUR, clock["t"])
            if delay <= assistant_main._TICK_ARRIVAL_TOLERANCE_S:
                break
            await fake_sleep(delay)
            delays.append(delay)
    except asyncio.CancelledError:
        pass

    assert len(delays) >= 2, "the step back was not noticed"
    assert sum(delays) > 1800.0, "the tick fired as though no time had been lost"
