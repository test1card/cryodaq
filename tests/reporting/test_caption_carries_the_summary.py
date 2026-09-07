"""One message: the readings and the assistant's words about them.

The hourly report sent a chart with a caption of readings, and the assistant's
summary went out as its own message. Operator's request, 2026-09-07: values as
text and the agent's note underneath, in the same message as the charts.

The readings are never sacrificed for the prose. They are the measurement; the
summary is commentary on it, and a report must not become unsendable because a
language model was verbose.
"""

from __future__ import annotations

from cryodaq.reporting.periodic_input import MAX_CAPTION_BYTES, MAX_CAPTION_CODEPOINTS
from cryodaq.reporting.periodic_renderer import _with_summary


def test_the_summary_is_appended_under_the_readings() -> None:
    caption = "<b>Температуры:</b>\n  Т12: 298.6 К"

    result = _with_summary(caption, "Давление растёт ровно, спада нет.")

    assert result.startswith(caption), "the readings must stay first and intact"
    assert "Давление растёт ровно" in result


def test_no_summary_leaves_the_caption_exactly_as_it_was() -> None:
    caption = "<b>Температуры:</b>\n  Т12: 298.6 К"

    assert _with_summary(caption, "") == caption


def test_html_from_the_model_cannot_break_the_caption() -> None:
    """It came from a model in another process, and the caption is HTML.

    An unescaped angle bracket would fail at Telegram's parser hours after
    anyone could connect the two events.
    """
    result = _with_summary("<b>Т</b>", "давление <b>резко</b> & выше 1e-1 <sensor>")

    assert "<b>резко</b>" not in result
    assert "&lt;sensor&gt;" in result or "&lt;" in result


def test_a_verbose_model_loses_its_tail_not_the_readings() -> None:
    caption = "<b>Температуры:</b>\n  Т12: 298.6 К"

    result = _with_summary(caption, "очень длинная сводка. " * 200)

    assert result.startswith(caption)
    assert len(result) <= MAX_CAPTION_CODEPOINTS
    assert len(result.encode("utf-8")) <= MAX_CAPTION_BYTES
    assert result.endswith("…"), "truncation must be visible, not silent"


def test_a_caption_with_no_room_left_drops_the_summary_entirely() -> None:
    """Better no commentary than a report Telegram refuses."""
    caption = "x" * (MAX_CAPTION_CODEPOINTS - 10)

    result = _with_summary(caption, "сводка, которой некуда поместиться")

    assert result == caption


def test_the_contract_bounds_the_summary_before_the_renderer_sees_it() -> None:
    """Untrusted text is bounded where it enters, not only where it is used."""
    from cryodaq.reporting.periodic_input import MAX_SUMMARY_CHARS, _summary_text

    assert _summary_text(None) == ""
    assert _summary_text(12) == ""
    assert _summary_text("  ") == ""
    assert _summary_text("текст\x00с\x07управляющими") == "текстсуправляющими"
    long = _summary_text("я" * (MAX_SUMMARY_CHARS + 500))
    assert len(long) <= MAX_SUMMARY_CHARS
    assert long.endswith("…")
