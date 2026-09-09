"""The vLLM backend: what actually goes on the wire, checked at the call site.

The migration from Ollama to vLLM changes the HTTP surface, and the thing most
likely to break quietly is the intent stage. It is a separate, deliberately
cheap call -- a reasoning model once spent 33.6 s choosing one category word --
and it stays cheap only if ``think=False`` becomes ``reasoning_effort: "none"``
on the wire.

The existing classifier tests replace ``generate()`` with an AsyncMock, so they
cannot see the wire at all and would stay green if the mapping were dropped.
These drive a REAL OllamaClient over a mocked HTTP session instead, so the
assertion is on the request the server would have received.
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from cryodaq.agents import assistant_main
from cryodaq.agents.assistant.live.agent import AssistantConfig
from cryodaq.agents.assistant.query.intent_classifier import IntentClassifier
from cryodaq.agents.assistant.shared.ollama_client import (
    OllamaClient,
    OllamaModelMissingError,
    OllamaUnavailableError,
)

_ORIGIN = "http://100.87.73.25:28001"


def _openai_response(
    content: str | None = "status",
    *,
    finish_reason: str = "stop",
    status: int = 200,
    body: dict | None = None,
    use_body: bool = False,
) -> MagicMock:
    payload = (
        body
        if (use_body or body is not None)
        else {
            "model": "qwen38",
            "choices": [{"message": {"content": content, "reasoning_content": ""}, "finish_reason": finish_reason}],
            "usage": {"prompt_tokens": 41, "completion_tokens": 2},
        }
    )
    resp = AsyncMock()
    resp.status = status
    resp.json = AsyncMock(return_value=payload)
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _session(cm) -> MagicMock:
    s = AsyncMock()
    s.closed = False
    s.post = MagicMock(return_value=cm)
    return s


def _client(cm, *, api: str = "openai") -> OllamaClient:
    client = OllamaClient(base_url=_ORIGIN, default_model="qwen38", api=api)
    client._session = _session(cm)
    return client


def _posted(client: OllamaClient) -> tuple[str, dict]:
    call = client._session.post.call_args
    return call[0][0], call[1]["json"]


# ---------------------------------------------------------------------------
# The call site that matters
# ---------------------------------------------------------------------------


async def test_intent_classification_asks_the_server_not_to_think() -> None:
    """Driven through IntentClassifier, not through generate() directly."""
    client = _client(_openai_response('{"category": "status"}'))

    await IntentClassifier(client).classify("какое сейчас давление?")

    url, payload = _posted(client)
    assert url == f"{_ORIGIN}/v1/chat/completions"
    assert payload["reasoning_effort"] == "none"


async def test_intent_classification_never_reaches_the_ollama_endpoint() -> None:
    client = _client(_openai_response('{"category": "status"}'))

    await IntentClassifier(client).classify("какое сейчас давление?")

    url, payload = _posted(client)
    assert "/api/generate" not in url
    # keep_alive and num_ctx mean nothing to a server that holds its weights
    # and fixes its context at startup; forwarding them would be rejected.
    assert "keep_alive" not in payload
    assert "options" not in payload


async def test_the_operator_question_actually_reaches_the_server() -> None:
    """A wire test that passes on an empty prompt would be worthless.

    Asserting on str(messages) was not enough: renaming the field from
    "content" to "text" left the word visible in the repr while the server
    would have received no question at all. The question has to be found inside
    a user message's content.
    """
    question = "какое сейчас давление?"
    client = _client(_openai_response('{"category": "status"}'))

    await IntentClassifier(client).classify(question)

    _, payload = _posted(client)
    user_contents = [m["content"] for m in payload["messages"] if m.get("role") == "user"]

    assert user_contents, "no user message was sent"
    assert any(question in content for content in user_contents)


# ---------------------------------------------------------------------------
# The ollama backend must not start speaking OpenAI
# ---------------------------------------------------------------------------


async def test_the_ollama_backend_is_untouched() -> None:
    client = OllamaClient(base_url=_ORIGIN, default_model="qwen3.8:27b", api="ollama")
    client._session = _session(
        _openai_response(body={"model": "qwen3.8:27b", "response": "ok", "prompt_eval_count": 1, "eval_count": 1})
    )

    await client.generate("привет", think=False)

    url, payload = _posted(client)
    assert url == f"{_ORIGIN}/api/generate"
    assert payload["think"] is False
    assert "reasoning_effort" not in payload


def test_an_unknown_backend_is_refused_before_any_io() -> None:
    with pytest.raises(ValueError, match="api must be one of"):
        OllamaClient(base_url=_ORIGIN, api="vllm")


# ---------------------------------------------------------------------------
# The null-content trap
# ---------------------------------------------------------------------------


async def test_a_budget_exhausted_answer_is_truncated_not_empty_text() -> None:
    """max_tokens too small on a reasoning model returns content=None."""
    client = _client(_openai_response(None, finish_reason="length"))

    result = await client.generate("вопрос", max_tokens=64)

    assert result.truncated is True
    assert result.text == ""


async def test_a_missing_answer_is_truncated_even_when_the_reason_says_stop() -> None:
    """The two reasons are independent, so each must be caught alone.

    Asserting only their conjunction was the original defect here: deleting the
    null-content half left every test green, which is the shape of a test that
    preserves a defect instead of catching it.
    """
    client = _client(_openai_response(None, finish_reason="stop"))

    result = await client.generate("вопрос")

    assert result.truncated is True


async def test_an_aborted_answer_is_truncated_even_though_text_arrived() -> None:
    """vLLM can abort mid-generation, and the partial text looks like an answer.

    This is the dangerous direction: half a diagnosis handed to someone standing
    at a cryostat reads exactly like a whole one.
    """
    client = _client(_openai_response("Давление растёт, немедленно", finish_reason="abort"))

    result = await client.generate("что происходит?")

    assert result.truncated is True


async def test_an_unknown_ending_is_treated_as_incomplete() -> None:
    """Unknown terminal reasons fail closed, not open."""
    client = _client(_openai_response("частичный ответ", finish_reason="content_filter"))

    result = await client.generate("вопрос")

    assert result.truncated is True


async def test_a_complete_answer_is_not_marked_truncated() -> None:
    client = _client(_openai_response("всё в норме"))

    result = await client.generate("вопрос")

    assert result.truncated is False
    assert result.text == "всё в норме"
    assert result.tokens_in == 41


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


async def test_a_missing_model_is_named_as_missing() -> None:
    client = _client(_openai_response(status=404, body={"error": {"message": "The model `qwen39` does not exist."}}))

    with pytest.raises(OllamaModelMissingError):
        await client.generate("вопрос")


async def test_a_rejected_request_is_reported_as_unavailable() -> None:
    """reasoning_effort='high' is refused with 400 by this server."""
    client = _client(_openai_response(status=400, body={"error": {"message": "invalid reasoning_effort"}}))

    with pytest.raises(OllamaUnavailableError, match="invalid reasoning_effort"):
        await client.generate("вопрос", reasoning_effort="high")


async def test_a_non_json_body_is_reported_as_unavailable() -> None:
    """A proxy answering with HTML must not surface as a JSONDecodeError."""
    resp = AsyncMock()
    resp.status = 502
    resp.json = AsyncMock(side_effect=ValueError("Expecting value: line 1 column 1 (char 0)"))
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    client = _client(cm)

    with pytest.raises(OllamaUnavailableError, match="non-JSON body"):
        await client.generate("вопрос")


async def test_a_null_body_is_reported_as_unavailable() -> None:
    client = _client(_openai_response(body=None, use_body=True))

    with pytest.raises(OllamaUnavailableError, match="non-object body"):
        await client.generate("вопрос")


async def test_an_error_object_without_a_string_message_still_announces_an_outage() -> None:
    """{"error": {"message": null}} must not become an AttributeError.

    Crashing here would skip the typed unavailable path entirely, so the
    operator would be told "внутренняя ошибка" instead of that the model is
    down -- which points them at the wrong thing to fix.
    """
    client = _client(_openai_response(status=503, body={"error": {"message": None}}))

    with pytest.raises(OllamaUnavailableError):
        await client.generate("вопрос")


async def test_an_error_message_that_is_a_list_is_handled_too() -> None:
    client = _client(_openai_response(status=400, body={"error": {"message": ["bad", "request"]}}))

    with pytest.raises(OllamaUnavailableError):
        await client.generate("вопрос")


async def test_a_null_choice_is_an_outage_not_an_attribute_error() -> None:
    client = _client(_openai_response(body={"choices": [None]}))

    with pytest.raises(OllamaUnavailableError, match="choice is not an object"):
        await client.generate("вопрос")


async def test_an_object_valued_choices_field_is_an_outage() -> None:
    client = _client(_openai_response(body={"choices": {"0": {"message": {"content": "x"}}}}))

    with pytest.raises(OllamaUnavailableError, match="no usable choices"):
        await client.generate("вопрос")


async def test_a_garbled_usage_block_is_refused_rather_than_guessed_at() -> None:
    """A server that sends counts is claiming to know them."""
    client = _client(
        _openai_response(
            body={
                "choices": [{"message": {"content": "ответ"}, "finish_reason": "stop"}],
                "usage": "нет",
            }
        )
    )

    with pytest.raises(OllamaUnavailableError, match="usage is not an object"):
        await client.generate("вопрос")


async def test_an_absent_usage_block_is_not_a_violation() -> None:
    """Missing optional fields are missing, not malformed."""
    client = _client(_openai_response(body={"choices": [{"message": {"content": "ответ"}, "finish_reason": "stop"}]}))

    result = await client.generate("вопрос")

    assert result.text == "ответ"
    assert result.tokens_in == 0
    assert result.truncated is False


@pytest.mark.parametrize(
    ("usage", "offender"),
    [
        ({"prompt_tokens": -5, "completion_tokens": 7}, "prompt_tokens"),
        ({"prompt_tokens": 7, "completion_tokens": -5}, "completion_tokens"),
    ],
)
async def test_a_negative_token_count_is_refused(usage: dict, offender: str) -> None:
    """One case per count: making them both bad hides a dropped check.

    With both negative, removing the validation from either count alone left
    every test green, because the other one still raised.
    """
    client = _client(
        _openai_response(
            body={
                "choices": [{"message": {"content": "ответ"}, "finish_reason": "stop"}],
                "usage": usage,
            }
        )
    )

    with pytest.raises(OllamaUnavailableError, match=f"{offender} is not a token count"):
        await client.generate("вопрос")


async def test_a_null_model_does_not_become_the_string_None() -> None:
    client = _client(
        _openai_response(
            body={
                "model": None,
                "choices": [{"message": {"content": "ответ"}, "finish_reason": "stop"}],
            }
        )
    )

    result = await client.generate("вопрос", model="qwen38")

    assert result.model == "qwen38"


async def test_a_numeric_content_is_refused_but_a_null_one_is_not() -> None:
    """The boundary must separate a protocol violation from a partial answer."""
    bad = _client(_openai_response(body={"choices": [{"message": {"content": 42}, "finish_reason": "stop"}]}))
    with pytest.raises(OllamaUnavailableError, match="neither text nor null"):
        await bad.generate("вопрос")

    partial = _client(_openai_response(None, finish_reason="length"))
    result = await partial.generate("вопрос")
    assert result.truncated is True


async def test_a_dict_finish_reason_is_refused() -> None:
    client = _client(
        _openai_response(body={"choices": [{"message": {"content": "ответ"}, "finish_reason": {"why": "x"}}]})
    )

    with pytest.raises(OllamaUnavailableError, match="finish_reason is not a string"):
        await client.generate("вопрос")


async def test_an_explicit_null_usage_is_a_violation_not_an_absence() -> None:
    """Saying nothing and answering "null" are different claims."""
    client = _client(
        _openai_response(body={"choices": [{"message": {"content": "ответ"}, "finish_reason": "stop"}], "usage": None})
    )

    with pytest.raises(OllamaUnavailableError, match="usage is not an object"):
        await client.generate("вопрос")


async def test_a_missing_model_on_vllm_is_not_told_to_run_ollama_pull() -> None:
    """`ollama pull` cannot repair a server that serves one fixed model."""
    client = _client(_openai_response(status=404, body={"error": {"message": "The model does not exist."}}))

    with pytest.raises(OllamaModelMissingError) as caught:
        await client.generate("вопрос")

    assert "ollama pull" not in str(caught.value)
    assert "/v1/models" in str(caught.value)


async def test_an_explicit_effort_overrides_the_think_mapping() -> None:
    client = _client(_openai_response("ответ"))

    await client.generate("вопрос", think=False, reasoning_effort="medium")

    _, payload = _posted(client)
    assert payload["reasoning_effort"] == "medium"


async def test_thinking_on_does_not_silently_pick_a_level() -> None:
    """The levels change the diagnosis, so the client must not choose one."""
    client = _client(_openai_response("ответ"))

    await client.generate("вопрос", think=True)

    _, payload = _posted(client)
    assert "reasoning_effort" not in payload


# ---------------------------------------------------------------------------
# The backend has to be selectable from the file the operator edits
# ---------------------------------------------------------------------------


def test_the_backend_comes_from_the_config_file() -> None:
    assert AssistantConfig.from_dict({"ollama": {"api": "openai"}}).llm_api == "openai"


def test_a_config_without_the_key_stays_on_ollama() -> None:
    """No existing deployment may move underneath itself."""
    assert AssistantConfig.from_dict({"ollama": {}}).llm_api == "ollama"
    assert AssistantConfig().llm_api == "ollama"


def _shipped_text() -> str:
    return (Path(__file__).resolve().parents[3] / "config" / "agent.yaml").read_text(encoding="utf-8")


def test_the_shipped_config_states_its_backend_rather_than_defaulting() -> None:
    """A misspelled key must fail here, not silently fall back.

    from_dict() supplies "ollama" for a missing key, so asserting on the parsed
    config alone passes just as happily when the key is called `apii` -- the
    assertion would be comparing the default against itself. The raw mapping is
    what has to be checked.
    """
    ollama_section = yaml.safe_load(_shipped_text())["agent"]["ollama"]

    assert "api" in ollama_section, "config/agent.yaml must name its backend explicitly"

    cfg = AssistantConfig.from_dict({"ollama": ollama_section})
    client = OllamaClient(base_url=cfg.ollama_base_url, default_model=cfg.default_model, api=cfg.llm_api)

    assert client._api == ollama_section["api"]


_SWITCHED_KEYS = ("base_url:", "default_model:", "api:", "intent_model:", "format_model:")


def _apply_the_documented_switch(text: str) -> str:
    """Do exactly what the comment in agent.yaml tells the operator to do.

    Whitespace is preserved deliberately. An earlier version of this helper
    rebuilt each switched line at four spaces, which silently REPAIRED the
    misalignment it was supposed to detect -- the test was checking its own
    normalisation instead of the file. Here the only thing that changes is the
    comment marker; every space the file has, the result keeps.
    """
    switched = []
    for line in text.splitlines():
        active = re.match(rf"^(\s*)({'|'.join(_SWITCHED_KEYS)})", line)
        if active:
            indent = active.group(1)
            switched.append(f"{indent}# {line[len(indent) :]}")
            continue
        commented = re.match(rf"^(\s*)# ({'|'.join(_SWITCHED_KEYS)})", line)
        if commented:
            indent = commented.group(1)
            switched.append(f"{indent}{line[len(indent) + 2 :]}")
            continue
        switched.append(line)
    return "\n".join(switched) + "\n"


def test_the_shipped_config_selects_vllm() -> None:
    """Switched 2026-09-10 on the operator's instruction: vLLM only.

    All five keys, not three: the query stages override default_model, so a
    switch that forgets them points the two interactive stages at a model the
    server does not have.
    """
    cfg = AssistantConfig.from_dict(yaml.safe_load(_shipped_text())["agent"])

    assert cfg.llm_api == "openai"
    assert cfg.ollama_base_url == "http://100.87.73.25:28001"
    assert cfg.default_model == "qwen38"
    assert cfg.query_intent_model == "qwen38"
    assert cfg.query_format_model == "qwen38"

    client = OllamaClient(base_url=cfg.ollama_base_url, default_model=cfg.default_model, api=cfg.llm_api)

    assert client._api == "openai"
    # The origin guard must accept the literal address the comment specifies.
    assert client._base_url == "http://100.87.73.25:28001"


def test_the_documented_rollback_actually_produces_a_working_ollama_config() -> None:
    """The instructions in the comment are executed, not merely read.

    Ollama is still running and the comment says how to go back. Indentation is
    the trap: a commented block whose keys sit two spaces deeper than their
    neighbours parses fine while commented and raises a YAML ParserError the
    moment someone follows the instructions -- which is exactly when they are
    least able to debug it.
    """
    rolled_back = yaml.safe_load(_apply_the_documented_switch(_shipped_text()))
    cfg = AssistantConfig.from_dict(rolled_back["agent"])

    assert cfg.llm_api == "ollama"
    assert cfg.ollama_base_url == "http://100.87.73.25:11437"
    assert cfg.default_model == "qwen3.8:27b"
    assert cfg.query_intent_model == "qwen3.8:27b"
    assert cfg.query_format_model == "qwen3.8:27b"


def test_assistant_main_hands_the_configured_backend_to_the_client() -> None:
    """A source guard, and it is worth saying exactly what it does not prove.

    Standing up assistant_main() to observe the constructed client would mean
    faking ZMQ, Telegram and the engine, so this reads the construction site
    instead. It catches the wiring being dropped -- the failure that would
    leave the config key inert while every other test stayed green -- and it
    proves nothing about runtime behaviour.

    It parses rather than greps. A substring check is satisfied by
    `# api=config.llm_api`, which is exactly the disabled wiring this is meant
    to catch, so the assertion is on a real keyword of a real call.
    """
    tree = ast.parse(inspect.getsource(assistant_main))
    constructions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "OllamaClient"
    ]

    assert constructions, "assistant_main no longer constructs an OllamaClient"
    for call in constructions:
        passed = {kw.arg: kw for kw in call.keywords}
        assert "api" in passed, "the configured backend is not passed to the client"
        value = passed["api"].value
        # Not merely "an attribute called llm_api": `api=object().llm_api`
        # would satisfy that and raise at runtime. The receiver is checked too.
        assert isinstance(value, ast.Attribute), "the backend must come from the config object"
        assert value.attr == "llm_api"
        assert isinstance(value.value, ast.Name) and value.value.id == "config"
