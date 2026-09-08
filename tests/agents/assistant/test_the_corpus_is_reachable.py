"""The retrieval decision must have room to reach its own answer.

The corpus is real and it works: 97 documents, and a hand-run search for the
knocking question returns the paragraph naming the plastic bushing on the motor
eccentric as the part whose wear "directly creates a loud clacking noise in the
head". None of it was reachable from the assistant.

`_RETRIEVAL_DECISION_MAX_TOKENS` was 120, under a comment claiming a small
budget "keeps a reasoning model from thinking its way past the answer". It does
the opposite: the deployed model reaches the one-line verdict AFTER a reasoning
preamble, the cap lands inside the preamble, and the call returns "". An empty
decision parses as "do not search" — so the corpus was unreachable for every
question ever asked.

Measured against qwen3.8:27b on 2026-09-09 at temperature 0, same question:
120 gave "", and 200, 300, 400 and 600 all gave
`ПОИСК: стук в криомашине возможные причины диагностика`.
"""

from __future__ import annotations

import pytest

from cryodaq.agents.assistant.query.agent import (
    _RETRIEVAL_DECISION_MAX_TOKENS,
    _parse_retrieval_decision,
)

#: The smallest budget observed to produce the verdict at all. Below this the
#: call returns nothing and the corpus goes unsearched.
_MEASURED_FLOOR = 200


def test_the_decision_has_room_to_answer() -> None:
    assert _RETRIEVAL_DECISION_MAX_TOKENS >= _MEASURED_FLOOR, (
        f"{_RETRIEVAL_DECISION_MAX_TOKENS} is at or under the budget measured to "
        f"return an empty decision; the corpus becomes unreachable silently"
    )


def test_an_empty_decision_means_no_search() -> None:
    """Which is why the truncation was silent: nothing raised, nothing logged,
    the enrichment simply never happened."""

    assert _parse_retrieval_decision("") is None
    assert _parse_retrieval_decision("   \n  ") is None


def test_a_verdict_after_a_preamble_is_still_read() -> None:
    """The budget is the fix, but the parser must also survive what the model
    actually emits: the verdict arrives after its reasoning, not instead of it."""

    text = (
        "Оператор спрашивает про стук. В показаниях этого нет,\n"
        "значит нужны документы.\n"
        "ПОИСК: стук в криомашине возможные причины диагностика\n"
    )

    assert _parse_retrieval_decision(text) == "стук в криомашине возможные причины диагностика"


@pytest.mark.parametrize(
    "text",
    [
        "Думаю, данных достаточно.\nНЕТ",
        "НЕТ",
    ],
)
def test_a_refusal_after_a_preamble_is_still_a_refusal(text: str) -> None:
    assert _parse_retrieval_decision(text) is None
