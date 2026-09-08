"""The rule that judged the segment rates now has to live in the prompt.

`ChannelTrend.segment_trend` compared the first and last third against the root
of the sum of their squared standard errors and returned "держится", "падает"
or "растёт". It was deleted on 2026-09-08 because that error model does not
hold on sensor data, and because its "держится" branch reported a failure to
measure as constancy.

Deleting it moved the judgement to the model reading the text. The text now
carries each third's rate WITH its error, so the rule must be stated where the
model can act on it — otherwise the same wrong conclusion is simply drawn one
layer up, from the same numbers, with nothing to stop it.
"""

from __future__ import annotations

from cryodaq.agents.assistant.query.prompts import FORMAT_RESPONSE_SYSTEM


def test_the_prompt_forbids_calling_an_overlap_a_change() -> None:
    assert "перекрыва" in FORMAT_RESPONSE_SYSTEM, (
        "nothing tells the model what overlapping intervals mean"
    )
    assert "НЕ УСТАНОВЛЕНО" in FORMAT_RESPONSE_SYSTEM


def test_the_prompt_forbids_reading_no_change_as_constancy() -> None:
    """The branch that did the most damage said the rate holds."""

    assert "держится" in FORMAT_RESPONSE_SYSTEM, (
        "the word the deleted code produced is not warned against"
    )
    assert "постоянства" in FORMAT_RESPONSE_SYSTEM


def test_the_prompt_says_the_errors_are_optimistic() -> None:
    """Astra's correction on 2026-09-08: independent residuals are assumed and
    the sensor does not supply them, so the stated spread is usually narrow."""

    assert "независимых остатков" in FORMAT_RESPONSE_SYSTEM


def test_the_prompt_compares_the_ends_not_the_neighbours() -> None:
    """Review's correction: adjacent thirds overlapping proves nothing on its
    own. A wide middle third can overlap both neighbours while the first and
    last are cleanly apart — a change that IS established, which a rule about
    adjacent pairs would order the model to hide."""

    assert "ПЕРВУЮ И ПОСЛЕДНЮЮ" in FORMAT_RESPONSE_SYSTEM
    assert "Широкая средняя треть" in FORMAT_RESPONSE_SYSTEM


def test_the_prompt_does_not_state_the_correlation_as_a_law() -> None:
    """Positive autocorrelation is the usual case, not a certainty: alternating
    residuals make the independent estimate conservative instead. The sign is
    never measured here, so the text must say so rather than assert."""

    assert "правило, а не закон" in FORMAT_RESPONSE_SYSTEM


def test_no_code_path_still_hands_out_the_verdict() -> None:
    """The rule belongs in one place. If a categorical shape word comes back
    into the schema, this text becomes advice competing with an assertion."""

    from cryodaq.agents.assistant.query import schemas

    assert not hasattr(schemas.ChannelTrend, "segment_trend")
    assert not hasattr(schemas.ChannelTrend, "direction")
