"""The agent's own emphasis must reach the operator as formatting, not asterisks.

On 2026-09-08 the operator received an hourly caption reading, verbatim,
`**Сводка за 60 мин**` and `*Датчики:*` — asterisks and all. The cause was
mine on both ends: the prompt asks for markdown, and the caption escapes
everything it is handed, so the markers arrived as punctuation.

The caption is already sent with `parse_mode=HTML`. What was missing is the
translation, and a tag set worth translating into: bold alone cannot make a
channel name or a number stand out in a sentence.
"""

from __future__ import annotations

import pytest

from cryodaq.reporting.periodic_input import (
    CAPTION_TAGS,
    PeriodicInputError,
    validate_caption_html,
)
from cryodaq.reporting.periodic_renderer import _render_summary_markup, _with_summary


def test_the_three_markers_become_the_three_tags() -> None:
    rendered = _render_summary_markup(
        "**Вывод:** растёт. *Датчики:* 11, канал `VSP63D_1/pressure`."
    )

    assert "<b>Вывод:</b>" in rendered
    assert "<i>Датчики:</i>" in rendered
    assert "<code>VSP63D_1/pressure</code>" in rendered
    validate_caption_html(rendered)


def test_no_asterisk_survives_into_the_message() -> None:
    """What the operator actually complained about."""

    rendered = _render_summary_markup("**Сводка за 60 мин** · *Датчики:* 11 всего")

    assert "*" not in rendered, f"asterisks reached the operator: {rendered!r}"


def test_an_unpaired_marker_is_dropped_not_shown() -> None:
    for raw in ("**без пары", "конец**", "`код без пары", "**через\nстроку**"):
        rendered = _render_summary_markup(raw)
        assert "**" not in rendered and "`" not in rendered, repr(rendered)
        validate_caption_html(rendered)


def test_the_model_cannot_write_its_own_markup() -> None:
    """Every tag in the result was written here. The text is a model's output
    and the caption is HTML at Telegram, so this is the boundary."""

    rendered = _render_summary_markup(
        "<b>не моё</b> <script>alert(1)</script> 5 < 7 & 8 > 6"
    )

    assert "<script" not in rendered
    assert "&lt;b&gt;" in rendered, "a tag from the model survived as markup"
    assert "5 &lt; 7 &amp; 8 &gt; 6" in rendered
    validate_caption_html(rendered)


@pytest.mark.parametrize("tag", CAPTION_TAGS)
def test_the_validator_accepts_each_tag_and_refuses_it_unclosed(tag: str) -> None:
    validate_caption_html(f"текст <{tag}>внутри</{tag}> дальше")

    with pytest.raises(PeriodicInputError):
        validate_caption_html(f"текст <{tag}>внутри")


def test_the_validator_refuses_bad_nesting() -> None:
    with pytest.raises(PeriodicInputError):
        validate_caption_html("<b>раз <i>два</b> три</i>")
    with pytest.raises(PeriodicInputError):
        validate_caption_html("<b>раз <b>два</b></b>")
    with pytest.raises(PeriodicInputError):
        validate_caption_html("<u>подчёркнутый</u>")


def test_a_tag_may_not_span_a_line() -> None:
    with pytest.raises(PeriodicInputError):
        validate_caption_html("<b>первая\nвторая</b>")


def test_the_whole_caption_path_still_validates() -> None:
    """The call site: `_build_caption` hands this straight to the validator."""

    caption = "x" * 700
    summary = (
        "**Вывод:** давление растёт ровно, `VSP63D_1/pressure` даёт "
        "*+0.14/ч*, вмешательство не требуется. 5 < 7."
    )

    rendered = _with_summary(caption, summary)
    validate_caption_html(rendered)

    # Validating is not enough: escaped markdown validates perfectly well and is
    # exactly what the operator was shown. The formatting has to be THERE.
    assert "<b>Вывод:</b>" in rendered
    assert "<code>VSP63D_1/pressure</code>" in rendered
    assert "<i>+0.14/ч</i>" in rendered
    assert "*" not in rendered and "`" not in rendered
