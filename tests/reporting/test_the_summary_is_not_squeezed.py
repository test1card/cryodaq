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
from cryodaq.reporting.periodic_input import MAX_SUMMARY_CHARS, MIN_INPUT_BYTES
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


# --- what review found in the relaxation -----------------------------------


def test_a_period_inside_a_number_is_not_a_sentence_end() -> None:
    """`rfind(".")` cut "давление 0.10 мбар" into "давление 0. …" — a value
    severed mid-number and presented as a finished thought."""
    from cryodaq.reporting.periodic_renderer import _last_sentence_end

    assert _last_sentence_end("давление 0.10 мбар") == -1
    assert _last_sentence_end("VSP63D_1.pressure растёт") == -1
    assert _last_sentence_end("Всё тихо. Давление 0.10") == len("Всё тихо")


def test_a_caption_cut_near_a_number_does_not_sever_it() -> None:
    caption = "x" * (MAX_CAPTION_CODEPOINTS - 150)
    summary = "Вывод: " + "состояние стабильное " * 5 + "давление 0.10 мбар в час " * 5

    tail = _with_summary(caption, summary)[len(caption) :]

    assert "0. …" not in tail, f"a number was cut in half: {tail[-30:]!r}"


def test_the_summary_yields_when_the_payload_would_not_fit() -> None:
    """A fixed character cap cannot know how much room the readings leave.

    868 readings and a 900-character summary serialise past a 65536-byte cap;
    input creation then fails and the WHOLE report is lost, for a decoration.
    """
    import inspect

    from cryodaq.agents.assistant import periodic_png

    source = inspect.getsource(periodic_png.PeriodicPngCoordinator)
    assert "_payload_fits" in source, "the payload size is never measured"
    at = source.index("_payload_fits")
    window = source[max(at - 300, 0) : at + 300]
    assert "summary" in window and "while" in window, "nothing shortens the summary when the payload is too large"


def test_the_fit_check_measures_what_the_writer_writes() -> None:
    """A guess at the encoding would answer a different question."""
    import inspect

    from cryodaq.agents.assistant.periodic_png import _payload_fits

    source = inspect.getsource(_payload_fits)
    assert 'separators=(",", ":")' in source
    assert "ensure_ascii=False" in source


def test_the_fit_check_never_raises_and_never_lies() -> None:
    """It runs while assembling a report; a failure here must not cost one.

    Not raising is half the requirement. The answer must also be usable: this
    value decides whether the summary is shortened, and the writer refuses
    anything it cannot serialise. Answering "fits" to a payload that will be
    refused stops the shrinking and loses the whole report over the one part
    of it that was optional. Answering "does not fit" shrinks the summary away
    and the report goes out without it.
    """

    from cryodaq.agents.assistant.periodic_png import _payload_fits

    class _Unserialisable:
        pass

    assert _payload_fits({"x": _Unserialisable()}, 10) is False

    # AND IT MUST STILL SAY YES TO A FIT. An implementation that answered
    # "does not fit" to everything would satisfy the line above and shrink
    # every summary to nothing, silently, forever.
    assert _payload_fits({"x": 1}, MIN_INPUT_BYTES) is True


# --- two edges the review found --------------------------------------------


def test_a_cut_that_lands_after_a_whole_word_keeps_that_word() -> None:
    """`trimmed = cut.rstrip()` removes the space the cut landed on, and the
    mid-word test then reads the result as a broken word and drops one more
    word that had fitted. The cut is mid-word only when the raw cut ends inside
    one — which is what the raw text, before the strip, still says.
    """

    from cryodaq.reporting.periodic_renderer import _with_summary

    summary = "Вывод: давление растёт ровно, вмешательство пока не требуется совсем"
    # Derive the caption length so the cut falls exactly on the space before
    # the last word, rather than guessing a length and hoping.
    keep = summary.index(" совсем") + 1
    caption = "x" * (MAX_CAPTION_CODEPOINTS - len("\n\n") - keep - 1)

    tail = _with_summary(caption, summary)[len(caption) :].strip()

    assert tail.startswith("Вывод:")
    assert "требуется" in tail, f"a whole word that fitted was dropped: {tail[-40:]!r}"


def test_a_sentence_ending_in_a_count_is_a_sentence() -> None:
    """A period after a digit is refused as a severed decimal. That guard is
    needed only when the period is the last thing there is: with whitespace
    after it, "Датчиков всего 11. " is an ordinary finished sentence, and
    refusing it throws away everything back to the previous one.
    """

    from cryodaq.reporting.periodic_renderer import _last_sentence_end

    text = "Всё спокойно. Датчиков всего 11. Из них десять в норме"

    assert _last_sentence_end(text) == text.index("11.") + 2


def test_a_severed_decimal_is_still_not_a_sentence() -> None:
    """The control for the test above: with nothing after it, a period on a
    digit may be a number cut in half, and "давление 0. …" is what that reads
    like to an operator.
    """

    from cryodaq.reporting.periodic_renderer import _last_sentence_end

    assert _last_sentence_end("Всё спокойно. давление 0.") == len("Всё спокойно")


def test_a_sentence_ending_in_a_count_survives_a_cut_right_after_it() -> None:
    """The earlier test handed `_last_sentence_end` a string that still had the
    space after "11.". The real caller hands it an rstripped prefix, where that
    space is gone and the period looks exactly like a severed decimal — so the
    sentence is still thrown away at the one place it matters.

    The prefix alone cannot tell "Датчиков всего 11." from "давление 0.". What
    can is the character the cut dropped: a digit means the period was inside a
    number, anything else means the sentence ended there.
    """

    from cryodaq.reporting.periodic_renderer import _MIN_SENTENCE_KEPT, _with_summary

    # The head must carry a sentence end at or past `_MIN_SENTENCE_KEPT`, or
    # the sentence branch never runs and the fall-through keeps the text by
    # accident — which is how the first version of this test passed while the
    # defect stood.
    head = "Всё спокойно, вмешательство пока не требуется, за исключением одного места, о котором ниже. "
    assert head.index(". ") >= _MIN_SENTENCE_KEPT
    summary = head + "Датчиков всего 11. Из них десять в норме и один не оценён."
    # Cut exactly after "11." — derive the caption length, do not guess it.
    keep = summary.index(" Из них")
    caption = "x" * (MAX_CAPTION_CODEPOINTS - len("\n\n") - keep - 1)

    tail = _with_summary(caption, summary)[len(caption) :].strip()

    assert "11." in tail, f"the sentence ending in a count was dropped: {tail!r}"


def test_a_decimal_severed_by_the_cut_is_still_not_a_sentence() -> None:
    """The control. Same shape, but the dropped character is a digit, so the
    period belongs to the number and the caption must not end on it."""

    from cryodaq.reporting.periodic_renderer import _with_summary

    head = "Всё спокойно, вмешательство не требуется. "
    summary = head + "Давление сейчас 0.10 мбар и медленно растёт."
    keep = summary.index("10 мбар")
    caption = "x" * (MAX_CAPTION_CODEPOINTS - len("\n\n") - keep - 1)

    tail = _with_summary(caption, summary)[len(caption) :].strip()

    body = tail.rstrip("… ").rstrip()
    assert not body.endswith("0."), f"a number was cut in half and shown as a thought: {tail!r}"
