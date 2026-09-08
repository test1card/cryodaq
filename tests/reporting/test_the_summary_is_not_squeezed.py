"""The caption stopped squeezing the summary, and cuts on a finished thought.

The deployed build sent a caption ending "Коротко: д…" — a section titled "In
short" reduced to one letter. Funny once, useless every hour. Two things were
wrong: the summary was capped tighter than the caption ever needed, and when it
did have to be cut, the cut fell wherever the character count ran out.

The operator's steer on 2026-09-08: "не нужно так заморачиваться на
коротковизну", and "лучше вместо коротко вывод сделать".
"""

from __future__ import annotations

from cryodaq.agents.assistant.live.prompts import PERIODIC_REPORT_SYSTEM
from cryodaq.reporting.periodic_input import MAX_SUMMARY_CHARS
from cryodaq.reporting.periodic_renderer import MAX_CAPTION_CODEPOINTS, _with_summary

_BASE = "x" * 330  # roughly what temperatures, pressure and alarms occupy


def test_the_stored_cap_is_no_longer_tighter_than_the_caption() -> None:
    """420 squeezed the summary for no reason: the caption's own budget, after
    the temperatures, is larger than that."""
    assert MAX_SUMMARY_CHARS > MAX_CAPTION_CODEPOINTS - len(_BASE) - 2


def test_an_ordinary_summary_now_fits_whole() -> None:
    summary = (
        "Вывод: давление растёт ровно, 0.10 мбар/ч тринадцатый час подряд, без спада — "
        "это натекание. Температуры стоят, разброс в пределах сотых кельвина. Тревог "
        "нет, фаз не менялось, журнал пуст. Датчики: 11 всего, 10 OK, 1 не оценён."
    )

    assert _with_summary(_BASE, summary).endswith(summary)


def test_a_summary_that_must_be_cut_ends_on_a_finished_sentence() -> None:
    """ "Коротко: д…" is what cutting by character count produces."""
    summary = (
        "Вывод: всё спокойно, вмешательство не требуется. "
        "Единственное движение за окно — VSP63D_1/pressure, ползёт вверх со скоростью "
        "около 0.09 мбар/ч. Остальные 22 канала держат уровень, дрейфа не видно. "
        "Тревог нет, фазы не переключались, операторский журнал пуст. "
        "Коротко: давление чуть дышит, остальное спит."
    )
    caption = "x" * (MAX_CAPTION_CODEPOINTS - 200)

    tail = _with_summary(caption, summary)[len(caption) :].strip()

    assert tail, "the summary was dropped entirely"
    assert tail.endswith("…"), "truncation must stay visible"
    body = tail.rstrip("… ").rstrip()
    assert body[-1] in ".!?", f"the caption ends mid-thought: {body[-40:]!r}"


def test_the_conclusion_survives_because_it_comes_first() -> None:
    """Cutting takes the tail, so a conclusion in the tail is the thing lost."""
    summary = "Вывод: вмешательство не требуется. " + "Подробности, которые можно потерять без ущерба. " * 12
    caption = "x" * (MAX_CAPTION_CODEPOINTS - 260)

    tail = _with_summary(caption, summary)[len(caption) :]

    assert "Вывод: вмешательство не требуется." in tail


def test_a_single_long_paragraph_is_cut_rather_than_dropped() -> None:
    """No sentence to fall back to; a cut clause still beats nothing."""
    caption = "x" * (MAX_CAPTION_CODEPOINTS - 150)
    summary = "слово " * 60

    tail = _with_summary(caption, summary)[len(caption) :]

    assert tail.strip().endswith("…")


def test_the_prompt_asks_for_the_conclusion_first_and_calls_it_a_conclusion() -> None:
    assert "Вывод:" in PERIODIC_REPORT_SYSTEM
    assert "НАЧИНАЙ С ВЫВОДА" in PERIODIC_REPORT_SYSTEM
    assert "400 символов" not in PERIODIC_REPORT_SYSTEM, "the squeeze is back"
