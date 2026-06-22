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


def test_parse_intent_extracts_target_source_kind_vault_note() -> None:
    """v0.55.14 — canonical kind matches the loader (vault_note, not vault)."""
    intent = _parse_intent(_knowledge_json(source_kind="vault_note"))
    assert intent.target_source_kind == "vault_note"


def test_parse_intent_rejects_non_canonical_vault_alias() -> None:
    """v0.55.14 (Codex audit SCOPE 6 finding 6.4) — the legacy "vault"
    string is NOT in the canonical allow-list; it collapses to None so
    the WHERE clause matches nothing rather than silently."""
    intent = _parse_intent(_knowledge_json(source_kind="vault"))
    assert intent.target_source_kind is None


def test_parse_intent_rejects_arbitrary_string() -> None:
    """v0.55.14 — only canonical kinds survive validation."""
    intent = _parse_intent(_knowledge_json(source_kind="random_made_up_kind"))
    assert intent.target_source_kind is None


def test_parse_intent_rejects_comma_separated_multi_hint() -> None:
    """v0.55.14 — Gemma sometimes emits "vault, operator_log"; refuse
    to guess between contradictory hints."""
    intent = _parse_intent(_knowledge_json(source_kind="vault_note, operator_log"))
    assert intent.target_source_kind is None


def test_parse_intent_rejects_list_target_source_kind() -> None:
    """v0.55.14 — a JSON list shape is multi-hint; collapse to None."""
    raw = json.dumps(
        {
            "category": "knowledge_query",
            "target_channels": None,
            "time_window_minutes": None,
            "quantity": "",
            "target_source_kind": ["vault_note", "operator_log"],
        }
    )
    intent = _parse_intent(raw)
    assert intent.target_source_kind is None


def test_parse_intent_rejects_dict_target_source_kind() -> None:
    raw = json.dumps(
        {
            "category": "knowledge_query",
            "target_channels": None,
            "time_window_minutes": None,
            "quantity": "",
            "target_source_kind": {"primary": "vault_note"},
        }
    )
    intent = _parse_intent(raw)
    assert intent.target_source_kind is None


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
    """Case-insensitive matching against the canonical allow-list."""
    intent = _parse_intent(_knowledge_json(source_kind="VAULT_NOTE"))
    assert intent.target_source_kind == "vault_note"


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


async def test_classifier_parses_mocked_knowledge_query_with_vault_note_kind() -> None:
    """Parser extracts knowledge_query + vault_note from a mocked generate() response.

    Ollama is unconditionally mocked — LLM semantics are not tested here.
    What IS tested: the query text reaches generate() (catches broken
    prompt-construction paths), and vault_note is correctly parsed from
    the mocked JSON response.
    """
    query = "как делать калибровку датчика?"
    ollama = _make_ollama(_knowledge_json(source_kind="vault_note", quantity="процедура"))
    clf = IntentClassifier(ollama)
    intent = await clf.classify(query)
    assert intent.category == QueryCategory.KNOWLEDGE_QUERY
    assert intent.target_source_kind == "vault_note"
    call_kwargs = ollama.generate.call_args
    assert query in str(call_kwargs)


async def test_classifier_parses_mocked_knowledge_query_with_experiment_metadata_kind() -> None:
    """Parser extracts knowledge_query + experiment_metadata from a mocked generate() response.

    Ollama is unconditionally mocked — LLM semantics are not tested here.
    What IS tested: the query text reaches generate() (catches broken
    prompt-construction paths), and experiment_metadata is correctly parsed.
    """
    query = "какие у нас были проблемы в архивных экспериментах?"
    ollama = _make_ollama(_knowledge_json(source_kind="experiment_metadata"))
    clf = IntentClassifier(ollama)
    intent = await clf.classify(query)
    assert intent.category == QueryCategory.KNOWLEDGE_QUERY
    assert intent.target_source_kind == "experiment_metadata"
    call_kwargs = ollama.generate.call_args
    assert query in str(call_kwargs)


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
