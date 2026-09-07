"""The model decides when the corpus would help — a rule would be bucket sixteen.

Measured 2026-09-07: "почему давление растёт, если насос выключен? натекание
или газовыделение MLI?" was classified `knowledge_query`, so the router ran the
corpus search and only that. It found nothing and asked the OPERATOR to send
the pressure value — which the assistant was already holding. The question
needed the readings AND the manuals; one category can fetch one adapter.
"""

from __future__ import annotations

import pytest

from cryodaq.agents.assistant.query.agent import (
    _format_retrieved_documents,
    _parse_retrieval_decision,
)


@pytest.mark.parametrize(
    "reply",
    [
        "НЕТ",
        "нет",
        "  НЕТ  ",
        "`НЕТ`",
        "НЕТ, данных достаточно",
    ],
)
def test_a_refusal_asks_for_nothing(reply: str) -> None:
    assert _parse_retrieval_decision(reply) is None


def test_a_request_carries_the_query_the_model_chose() -> None:
    decision = _parse_retrieval_decision("ПОИСК: критерии отличия натекания от газовыделения")
    assert decision == "критерии отличия натекания от газовыделения"


def test_the_marker_is_required_so_an_answer_is_never_mistaken_for_a_query() -> None:
    """A model that answers instead of deciding must not have its prose searched."""
    prose = "Давление растёт линейно, это похоже на натекание, но за час не различить."
    assert _parse_retrieval_decision(prose) is None


def test_a_runaway_query_is_bounded() -> None:
    decision = _parse_retrieval_decision("ПОИСК: " + "натекание " * 200)
    assert decision is not None
    assert len(decision) <= 200


def test_nothing_asked_for_means_no_document_section() -> None:
    """An empty section invites the model to comment on absent documents."""
    assert _format_retrieved_documents(None) == ""


def test_an_empty_result_says_so_rather_than_vanishing() -> None:
    """The model asked; silence would look like it never asked."""

    class _Result:
        hits: list = []
        query = "критерии отличия натекания"

    text = _format_retrieved_documents(_Result())
    assert "ничего не нашлось" in text
    assert "критерии отличия натекания" in text


def test_hits_are_numbered_for_citation() -> None:
    class _Hit:
        def __init__(self, source_id: str, text: str) -> None:
            self.source_id = source_id
            self.text = text

    class _Result:
        query = "натекание"
        hits = [_Hit("dylla-2006.pdf", "Water outgassing on SS"), _Hit("cern-99-05.pdf", "leak rate")]

    text = _format_retrieved_documents(_Result())
    assert "[1] dylla-2006.pdf" in text
    assert "[2] cern-99-05.pdf" in text
