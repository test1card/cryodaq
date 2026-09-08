"""The caption that ends on a sentence must still fit the caption limit.

`_build_caption` hands `_with_summary`'s result straight to
`validate_caption_html`.  The sentence branch appends `" …"` — two codepoints
where the loop that sized the cut had budgeted one — and when the branch's own
guard rejects the oversized text, the oversized text is what stays in
`escaped`.  The final check measures bytes only, and Cyrillic reaches the
1024-codepoint limit at about 2048 of the 4096 permitted bytes, so the byte
check passes and an over-long caption reaches the validator.

The hourly report then raises instead of being sent, and because the slot is
fenced, every retry re-sends the same text.
"""

from __future__ import annotations

import pytest

from cryodaq.reporting.periodic_input import (
    MAX_CAPTION_CODEPOINTS,
    PeriodicInputError,
    validate_caption_html,
)
from cryodaq.reporting.periodic_renderer import _MIN_SENTENCE_KEPT, _with_summary


def _summary_whose_cut_lands_on_a_full_stop(caption: str) -> str:
    """Derive the input rather than guess it.

    The cut is ``summary[: remaining - 1]``.  Put a full stop on that exact
    character and a space just after it: the stop makes the sentence branch
    fire, and the space keeps the word-boundary branch from firing and
    replacing the oversized text the sentence branch left behind.
    """

    remaining = MAX_CAPTION_CODEPOINTS - len(caption) - len("\n\n")
    assert remaining - 2 >= _MIN_SENTENCE_KEPT, "the sentence must be long enough to keep"
    cut_length = remaining - 1
    return "А" * (cut_length - 1) + "." + " " + "Хвост, который не поместится."


def test_a_caption_cut_on_a_sentence_still_fits() -> None:
    caption = "x" * 822
    summary = _summary_whose_cut_lands_on_a_full_stop(caption)

    result = _with_summary(caption, summary)

    assert len(result) <= MAX_CAPTION_CODEPOINTS, (
        f"caption is {len(result)} codepoints, limit is {MAX_CAPTION_CODEPOINTS}"
    )


def test_the_call_site_composition_does_not_raise() -> None:
    """This is line 505 of the renderer, verbatim: the validator sees the result."""

    caption = "x" * 822
    summary = _summary_whose_cut_lands_on_a_full_stop(caption)

    try:
        validate_caption_html(_with_summary(caption, summary))
    except PeriodicInputError as exc:  # pragma: no cover - the defect
        pytest.fail(f"the hourly report cannot be built: {exc}")
