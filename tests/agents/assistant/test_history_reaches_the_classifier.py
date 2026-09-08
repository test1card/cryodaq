"""Two defects in how the assistant uses what was already said.

FIRST: the history reached only the FORMAT prompt. The classifier saw the bare
query, so a follow-up like "а сейчас?" or "почему?" carried no subject, was
categorised blind, and the ROUTER then fetched data for the wrong category.
Injecting the transcript after routing cannot repair that — by then the wrong
numbers are in hand, and a fluent answer over the wrong numbers is worse than an
honest "не знаю".

SECOND: the exchange was remembered the moment the format call returned, before
the audit. An audit failure makes the caller report `not_dispatched` and
`not_committed`, so the operator never sees that text — and the agent still
carried it into the next turn, answering follow-ups about a message that, for
the operator, was never said.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

from cryodaq.agents.assistant.query.prompts import (
    INTENT_CLASSIFIER_CONVERSATION,
    INTENT_CLASSIFIER_USER,
)


class _Store:
    def __init__(self, transcript: str = "") -> None:
        self.transcript = transcript
        self.remembered: list[tuple[Any, str, str]] = []

    def replay(self, _chat_id: Any) -> str:
        return self.transcript

    def remember(self, chat_id: Any, question: str, answer: str) -> None:
        self.remembered.append((chat_id, question, answer))


# --- the prompt carries a slot at all -------------------------------------


def test_the_classifier_prompt_has_a_place_for_the_conversation() -> None:
    assert "{conversation}" in INTENT_CLASSIFIER_USER
    assert "{transcript}" in INTENT_CLASSIFIER_CONVERSATION


def test_the_block_says_to_classify_the_LAST_query() -> None:
    """Without that, the history invites classifying the wrong turn."""
    assert "последний запрос" in INTENT_CLASSIFIER_CONVERSATION


# --- the classifier actually receives it ----------------------------------


async def test_the_transcript_reaches_the_classifier_prompt() -> None:
    from cryodaq.agents.assistant.query.intent_classifier import IntentClassifier

    ollama = AsyncMock()
    ollama.generate = AsyncMock(side_effect=RuntimeError("stop here"))
    classifier = IntentClassifier(ollama_client=ollama, model="m")

    await classifier.classify("а сейчас?", conversation="Оператор: какая температура Т12?")

    sent = ollama.generate.await_args.args[0]
    assert "Т12" in sent, "the classifier still decides the category blind"
    assert "а сейчас?" in sent


async def test_no_history_leaves_the_prompt_as_it_was() -> None:
    from cryodaq.agents.assistant.query.intent_classifier import IntentClassifier

    ollama = AsyncMock()
    ollama.generate = AsyncMock(side_effect=RuntimeError("stop here"))
    classifier = IntentClassifier(ollama_client=ollama, model="m")

    await classifier.classify("какая температура?")

    sent = ollama.generate.await_args.args[0]
    assert "Предыдущие реплики" not in sent


async def test_a_long_history_is_trimmed_from_the_FRONT() -> None:
    """A follow-up refers to the END of the conversation."""
    from cryodaq.agents.assistant.query.intent_classifier import IntentClassifier

    ollama = AsyncMock()
    ollama.generate = AsyncMock(side_effect=RuntimeError("stop here"))
    classifier = IntentClassifier(ollama_client=ollama, model="m")
    history = "СТАРОЕ " * 400 + "СВЕЖЕЕ-ПРО-Т12"

    await classifier.classify("а сейчас?", conversation=history)

    sent = ollama.generate.await_args.args[0]
    assert "СВЕЖЕЕ-ПРО-Т12" in sent, "the trim dropped the turn the follow-up refers to"
    assert len(sent) < len(history), "nothing was trimmed at all"


# --- the transcript helper never costs an answer --------------------------


async def test_a_broken_store_yields_no_transcript_rather_than_raising() -> None:
    from cryodaq.agents.assistant.query.agent import AssistantQueryAgent

    class _Broken:
        def replay(self, _chat_id: Any) -> str:
            raise RuntimeError("disk gone")

    agent = object.__new__(AssistantQueryAgent)
    agent._conversation = _Broken()
    assert await AssistantQueryAgent._conversation_transcript(agent, 1) == ""


async def test_no_store_at_all_yields_no_transcript() -> None:
    from cryodaq.agents.assistant.query.agent import AssistantQueryAgent

    agent = object.__new__(AssistantQueryAgent)
    agent._conversation = None
    assert await AssistantQueryAgent._conversation_transcript(agent, 1) == ""


# --- remembering happens past the audit -----------------------------------


def test_remember_is_not_called_inside_the_generation_branch() -> None:
    """Structural: the call must sit after the audit, not beside the LLM call.

    Asserted on the source because the ordering IS the fix; a behavioural test
    would need the whole pipeline to prove where one call sits relative to
    another.
    """
    import inspect

    from cryodaq.agents.assistant.query import agent as module

    source = inspect.getsource(module.AssistantQueryAgent._handle_query_inner)
    remember_at = source.index("_conversation.remember")
    audit_at = source.index("await self._audit.log")
    assert remember_at > audit_at, "the exchange is remembered before the audit that can withhold it"


def test_the_fallback_answer_is_never_remembered() -> None:
    """A pipeline that failed said nothing worth carrying forward."""
    import inspect

    from cryodaq.agents.assistant.query import agent as module

    source = inspect.getsource(module.AssistantQueryAgent._handle_query_inner)
    guard = source[source.index("_conversation is not None and") : source.index("_conversation.remember")]
    assert "_FALLBACK" in guard


def test_the_agent_actually_passes_the_conversation_to_the_classifier() -> None:
    """The classifier ACCEPTING a transcript is worthless if nobody sends one.

    Written after a negative control failed to fail: reverting the agent to
    `classify(query)` left every other test in this file green, because they
    exercise the classifier directly. The defect was never in the classifier —
    it was in the call site.
    """
    import inspect

    from cryodaq.agents.assistant.query import agent as module

    source = inspect.getsource(module.AssistantQueryAgent._handle_query_inner)
    start = source.index("self._classifier.classify(")
    call = source[start : source.index(")", start) + 1]
    assert "conversation=" in call, "the classifier is called without the conversation; follow-ups are classified blind"
