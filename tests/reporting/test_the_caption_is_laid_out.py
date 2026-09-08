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
    MAX_CAPTION_CODEPOINTS,
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


def test_an_unpaired_marker_is_left_alone_not_guessed_at() -> None:
    """The contract changed on purpose, after guessing failed three times.

    Stripping "leftover" markers turned `10**-3` into `10-3` and `2*3` into
    `23`: numbers silently changed on their way to the operator. There is no
    local rule that tells an orphaned emphasis marker from an arithmetic one,
    so nothing is guessed any more — an unpaired marker is passed through as
    the character it is, and the caption still validates.

    The orphans that mattered came from truncation halving a pair, and those
    are gone at the source: see the truncation tests below.
    """

    for raw in ("**без пары", "конец**", "`код без пары", "**через\nстроку**"):
        rendered = _render_summary_markup(raw)
        validate_caption_html(rendered)
        assert "<" not in rendered.replace("&lt;", ""), f"a stray marker opened a tag: {rendered!r}"


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


# --- what the review found in the first version -----------------------------


@pytest.mark.parametrize(
    "raw, kept",
    [
        ("Давление `10**-3` мбар", "10**-3"),
        ("степень `2**3` равна восьми", "2**3"),
        ("канал `a*b` и `x`", "a*b"),
    ],
)
def test_monospace_is_verbatim(raw: str, kept: str) -> None:
    """Stripping unpaired markers across the finished HTML reached inside code.

    `10**-3` came out as `10-3` — a number quietly changed on its way to the
    operator, with the validator perfectly happy about it. Inside monospace an
    asterisk is an asterisk.
    """

    rendered = _render_summary_markup(raw)

    assert f"<code>{kept}</code>" in rendered, rendered
    validate_caption_html(rendered)


def test_a_marker_orphaned_by_truncation_is_dropped() -> None:
    """The contract says markers do not reach the operator, and a lone `*`
    survived it. This is not exotic: it happens whenever the cut lands inside
    correct emphasis, which is exactly what truncation does."""

    caption = "x" * 950
    summary = "*" + "Давление стабильно " * 10 + "*"

    rendered = _with_summary(caption, summary)

    validate_caption_html(rendered)
    assert "*" not in rendered, f"markdown leftovers reached the operator: {rendered[-60:]!r}"
    assert "<i>" in rendered, "the pair was broken instead of being closed at the cut"


@pytest.mark.parametrize(
    "raw, kept",
    [
        ("Давление 10**-3 мбар", "10**-3"),
        ("коэффициент 2*3 равен шести", "2*3"),
        ("файл a*b*c", "a*b*c"),
    ],
)
def test_arithmetic_outside_monospace_is_not_markup(raw: str, kept: str) -> None:
    """The second half of the same defect, found after the first was fixed.

    Keeping monospace verbatim saved `10**-3` only when the agent had put it in
    backticks. Written plainly it still came out as `10-3`, and `2*3` as `23` —
    a number silently changed on its way to the operator. Emphasis attaches to a
    word boundary; a marker with text pressed against it on both sides is
    arithmetic, not markup.
    """

    rendered = _render_summary_markup(raw)

    assert kept in rendered, rendered
    validate_caption_html(rendered)


@pytest.mark.parametrize("room", [42, 60, 120, 300])
def test_truncation_never_orphans_a_marker(room: int) -> None:
    """Whatever the budget, a cut inside a pair closes it rather than halving it.

    The first attempt closed the pair and then the shrink loop chopped the
    closing marker straight back off, one character at a time, so the orphan
    returned an iteration later. The loop shrinks a LENGTH now and re-derives
    the cut, which keeps every pair whole at every step.
    """

    caption = "x" * (MAX_CAPTION_CODEPOINTS - len("\n\n") - room)
    summary = "**Вывод:** " + "давление растёт ровно и " * 12 + "конец."

    rendered = _with_summary(caption, summary)

    validate_caption_html(rendered)
    assert "*" not in rendered, f"a halved pair reached the operator: {rendered[-70:]!r}"


# --- absence has to be said, not implied ------------------------------------


def _snapshot_with_summary(summary: str):
    """A validated input whose only interesting field is the summary."""

    import copy

    from cryodaq.reporting.periodic_input import serialize_periodic_input
    from tests.reporting.test_periodic_child import _payload

    payload = copy.deepcopy(_payload())
    payload["render"]["summary"] = summary
    _, validated = serialize_periodic_input(payload, expected_max_input_bytes=65_536)
    return validated


def test_a_missing_summary_is_stated_in_the_caption() -> None:
    """The producer's comment said an absent summary was "already visible".

    It was not. On 2026-09-08 the operator received three hourly reports with
    no summary and no explanation, could not tell a quiet hour from a failed
    agent, and had to send them to someone to ask. That is exactly the work
    this assistant exists to take off him.
    """

    from cryodaq.reporting.periodic_renderer import _NO_SUMMARY_LINE, _build_caption

    caption = _build_caption(_snapshot_with_summary(""), [])

    assert _NO_SUMMARY_LINE in caption, "the caption said nothing about the missing summary"
    validate_caption_html(caption)


def test_a_present_summary_says_nothing_about_absence() -> None:
    from cryodaq.reporting.periodic_renderer import _NO_SUMMARY_LINE, _build_caption

    caption = _build_caption(_snapshot_with_summary("**Вывод:** всё спокойно."), [])

    assert _NO_SUMMARY_LINE not in caption
    assert "<b>Вывод:</b>" in caption
    validate_caption_html(caption)
