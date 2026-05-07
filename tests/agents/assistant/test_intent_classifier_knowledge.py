"""F32 Stage 2 (v0.55.7) — IntentClassifier KNOWLEDGE_QUERY tests.

Verifies the new schema field ``target_source_kind`` is parsed correctly
and that knowledge-leaning queries are not silently mis-routed to
out_of_scope_general by ``_parse_intent``. Live LLM behaviour is
exercised through mocked OllamaClient — gating prompt-engineering
quality is the operator's job, not pytest's.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

from cryodaq.agents.assistant.query.intent_classifier import (
    IntentClassifier,
    _parse_intent,
)
from cryodaq.agents.assistant.query.schemas import QueryCategory


def _knowledge_json(*, source_kind: str | None = None, quantity: str = "") -> str:
    return json.dumps(
        {
            "category": "knowledge_query",
            "target_channels": None,
            "time_window_minutes": None,
            "quantity": quantity,
            "target_source_kind": source_kind,
        }
    )


# ---------------------------------------------------------------------------
# _parse_intent — direct
# ---------------------------------------------------------------------------


def test_parse_intent_knowledge_query_category() -> None:
    intent = _parse_intent(_knowledge_json(quantity="процедура калибровки"))
    assert intent.category == QueryCategory.KNOWLEDGE_QUERY


def test_parse_intent_extracts_target_source_kind_vault() -> None:
    intent = _parse_intent(_knowledge_json(source_kind="vault"))
    assert intent.target_source_kind == "vault"


def test_parse_intent_extracts_target_source_kind_experiment_metadata() -> None:
    intent = _parse_intent(_knowledge_json(source_kind="experiment_metadata"))
    assert intent.target_source_kind == "experiment_metadata"


def test_parse_intent_target_source_kind_null_normalised_to_none() -> None:
    intent = _parse_intent(_knowledge_json(source_kind=None))
    assert intent.target_source_kind is None


def test_parse_intent_target_source_kind_string_null_normalised_to_none() -> None:
    """Gemma occasionally emits the literal string 'null' — must collapse."""
    intent = _parse_intent(_knowledge_json(source_kind="null"))
    assert intent.target_source_kind is None


def test_parse_intent_target_source_kind_none_string_normalised_to_none() -> None:
    intent = _parse_intent(_knowledge_json(source_kind="none"))
    assert intent.target_source_kind is None


def test_parse_intent_target_source_kind_empty_string_normalised_to_none() -> None:
    intent = _parse_intent(_knowledge_json(source_kind=""))
    assert intent.target_source_kind is None


def test_parse_intent_target_source_kind_lowercased() -> None:
    intent = _parse_intent(_knowledge_json(source_kind="VAULT"))
    assert intent.target_source_kind == "vault"


def test_parse_intent_target_source_kind_absent_field_returns_none() -> None:
    """A pre-v0.55.7 IntentClassifier response (no field) must keep working."""
    raw = json.dumps(
        {
            "category": "current_value",
            "target_channels": ["T1"],
            "time_window_minutes": None,
            "quantity": "температура",
        }
    )
    intent = _parse_intent(raw)
    assert intent.target_source_kind is None


# ---------------------------------------------------------------------------
# IntentClassifier.classify() — mocked Ollama
# ---------------------------------------------------------------------------


def _make_ollama(text: str) -> MagicMock:
    r = MagicMock()
    r.text = text
    r.truncated = False
    client = MagicMock()
    client.generate = AsyncMock(return_value=r)
    return client


async def test_classifier_emits_knowledge_query_with_vault_kind() -> None:
    ollama = _make_ollama(_knowledge_json(source_kind="vault", quantity="процедура"))
    clf = IntentClassifier(ollama)
    intent = await clf.classify("как делать калибровку датчика?")
    assert intent.category == QueryCategory.KNOWLEDGE_QUERY
    assert intent.target_source_kind == "vault"


async def test_classifier_emits_knowledge_query_with_experiment_metadata_kind() -> None:
    ollama = _make_ollama(_knowledge_json(source_kind="experiment_metadata"))
    clf = IntentClassifier(ollama)
    intent = await clf.classify("какие у нас были проблемы в архивных экспериментах?")
    assert intent.category == QueryCategory.KNOWLEDGE_QUERY
    assert intent.target_source_kind == "experiment_metadata"


async def test_classifier_handles_knowledge_query_without_source_kind_field() -> None:
    raw = json.dumps(
        {
            "category": "knowledge_query",
            "target_channels": None,
            "time_window_minutes": None,
            "quantity": "общий вопрос",
        }
    )
    ollama = _make_ollama(raw)
    clf = IntentClassifier(ollama)
    intent = await clf.classify("расскажи о cryodaq")
    assert intent.category == QueryCategory.KNOWLEDGE_QUERY
    assert intent.target_source_kind is None
