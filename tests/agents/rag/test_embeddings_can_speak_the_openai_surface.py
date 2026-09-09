"""RAG embeddings over the OpenAI surface, so Ollama can eventually go.

The operator's instruction on 2026-09-10 was to remove Ollama entirely and take
embeddings through vLLM. That is blocked on infrastructure, not on this code:
the vLLM instance at :28001 serves only `qwen38` and answers 404 on the
/v1/embeddings ROUTE itself, so there is no embedding service to point at yet.

This is the half that can be built now. When an embedding endpoint exists, RAG
moves with a config edit rather than a code change -- and the code is written
and tested before the endpoint arrives rather than in a hurry after it.

A wrong vector is worse than no vector here: the indexer sizes its schema from
the first width it sees, so a malformed response that decodes to something
plausible poisons the corpus instead of failing loudly. Hence a decode boundary
rather than guards at each use.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from cryodaq.agents.assistant.shared.ollama_client import (
    OllamaModelMissingError,
    OllamaUnavailableError,
)
from cryodaq.agents.rag.embeddings import EmbeddingsClient, make_embeddings_client

_ORIGIN = "http://100.87.73.25:28001"


def _response(body: dict | None = None, *, status: int = 200, raises: Exception | None = None) -> MagicMock:
    resp = AsyncMock()
    resp.status = status
    resp.json = AsyncMock(side_effect=raises) if raises else AsyncMock(return_value=body)
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _client(cm, *, api: str = "openai") -> EmbeddingsClient:
    client = EmbeddingsClient(base_url=_ORIGIN, model="qwen3-embedding", api=api)
    session = AsyncMock()
    session.closed = False
    session.post = MagicMock(return_value=cm)
    client._client._session = session
    return client


def _posted(client: EmbeddingsClient) -> tuple[str, dict]:
    call = client._client._session.post.call_args
    return call[0][0], call[1]["json"]


def _ok(vector: list) -> dict:
    return {"data": [{"embedding": vector, "index": 0}], "model": "qwen3-embedding"}


# ---------------------------------------------------------------------------
# The wire
# ---------------------------------------------------------------------------


async def test_the_openai_backend_posts_to_the_embeddings_route() -> None:
    client = _client(_response(_ok([0.1, 0.2, 0.3])))

    vector = await client.embed("проверка")

    url, payload = _posted(client)
    assert url == f"{_ORIGIN}/v1/embeddings"
    assert payload == {"model": "qwen3-embedding", "input": "проверка"}
    assert vector == [0.1, 0.2, 0.3]


async def test_the_ollama_backend_is_untouched() -> None:
    client = _client(_response({"embeddings": [[0.4, 0.5]]}), api="ollama")

    vector = await client.embed("проверка")

    url, payload = _posted(client)
    assert url == f"{_ORIGIN}/api/embed"
    assert "keep_alive" in payload
    assert vector == [0.4, 0.5]


async def test_the_text_actually_reaches_the_server() -> None:
    """A wire test that passes on an empty input would be worthless."""
    client = _client(_response(_ok([0.1])))

    await client.embed("вакуумный насос")

    _, payload = _posted(client)
    assert payload["input"] == "вакуумный насос"


# ---------------------------------------------------------------------------
# A wrong vector is worse than no vector
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "complaint"),
    [
        ({"data": []}, "no embedding data"),
        ({"data": "нет"}, "no embedding data"),
        ({}, "no embedding data"),
        ({"data": [None]}, "not an object"),
        ({"data": [{"embedding": None}]}, "non-empty list"),
        ({"data": [{"embedding": []}]}, "non-empty list"),
        ({"data": [{"embedding": ["0.1"]}]}, "non-numeric"),
        ({"data": [{"embedding": [True]}]}, "non-numeric"),
        ({"data": [{"embedding": [float("nan")]}]}, "non-finite"),
        ({"data": [{"embedding": [float("inf")]}]}, "non-finite"),
    ],
)
async def test_a_malformed_embedding_is_refused_rather_than_indexed(body: dict, complaint: str) -> None:
    client = _client(_response(body))

    with pytest.raises(OllamaUnavailableError, match=complaint):
        await client.embed("проверка")


async def test_a_well_formed_vector_survives_intact() -> None:
    """Integers are legal components and must not be dropped or rounded away."""
    client = _client(_response(_ok([1, -2.5, 0.0])))

    assert await client.embed("проверка") == [1.0, -2.5, 0.0]


# ---------------------------------------------------------------------------
# Failures
# ---------------------------------------------------------------------------


async def test_a_missing_embedding_model_says_what_to_check() -> None:
    """`ollama pull` is useless advice for a server that serves one model."""
    client = _client(_response({"error": {"message": "The model does not exist."}}, status=404))

    with pytest.raises(OllamaModelMissingError) as caught:
        await client.embed("проверка")

    assert "ollama pull" not in str(caught.value)
    assert "/v1/models" in str(caught.value)


async def test_a_non_json_body_is_reported_as_unavailable() -> None:
    client = _client(_response(status=502, raises=ValueError("Expecting value")))

    with pytest.raises(OllamaUnavailableError, match="non-JSON body"):
        await client.embed("проверка")


async def test_a_missing_route_is_reported_as_unavailable() -> None:
    """What the live vLLM actually answers today: 404 on the route itself."""
    client = _client(_response({"detail": "Not Found"}, status=404))

    with pytest.raises(OllamaUnavailableError):
        await client.embed("проверка")


# ---------------------------------------------------------------------------
# Selecting it from config
# ---------------------------------------------------------------------------


def test_the_backend_comes_from_the_rag_config() -> None:
    built = make_embeddings_client({"ollama_base_url": _ORIGIN, "embedding_model": "qwen3-embedding", "api": "openai"})

    assert built.api == "openai"
    assert built._client._api == "openai"


def test_a_rag_config_without_the_key_stays_on_ollama() -> None:
    """No existing deployment may move underneath itself."""
    built = make_embeddings_client({"ollama_base_url": _ORIGIN, "embedding_model": "qwen3-embedding"})

    assert built.api == "ollama"


def test_the_shipped_rag_config_states_its_backend_rather_than_defaulting() -> None:
    """A misspelled key must fail here, not silently fall back to ollama.

    make_embeddings_client() supplies "ollama" for a missing key, so asserting
    on the built client alone would pass just as happily when the key is called
    `apii` -- the assertion would compare the default against itself.
    """
    rag = yaml.safe_load((Path(__file__).resolve().parents[3] / "config" / "rag.yaml").read_text(encoding="utf-8"))[
        "rag"
    ]

    assert "api" in rag, "config/rag.yaml must name its embedding backend explicitly"
    assert make_embeddings_client(rag).api == rag["api"]


# ---------------------------------------------------------------------------
# The production construction paths, not just the builder
# ---------------------------------------------------------------------------


def _mock_http(client: EmbeddingsClient, body: dict) -> None:
    resp = AsyncMock()
    resp.status = 200
    resp.json = AsyncMock(return_value=body)
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    session = AsyncMock()
    session.closed = False
    session.post = MagicMock(return_value=cm)
    client._client._session = session


async def test_the_rag_cli_factory_reaches_the_embeddings_route() -> None:
    """Asserting on builder attributes was not enough.

    A reviewer mutated the CLI factory to drop `api` before calling the shared
    builder: the resulting client fell back to Ollama and every test here still
    passed, because none of them drove a production factory over HTTP.
    """
    from cryodaq.agents.rag.cli import _make_embeddings

    client = _make_embeddings({"ollama_base_url": _ORIGIN, "embedding_model": "e", "api": "openai"})
    _mock_http(client, _ok([0.1]))

    await client.embed("проверка")

    assert client._client._session.post.call_args[0][0] == f"{_ORIGIN}/v1/embeddings"


async def test_the_shared_builder_reaches_the_embeddings_route() -> None:
    """The path assistant_main uses to build retrieval's client."""
    client = make_embeddings_client({"ollama_base_url": _ORIGIN, "embedding_model": "e", "api": "openai"})
    _mock_http(client, _ok([0.1]))

    await client.embed("проверка")

    assert client._client._session.post.call_args[0][0] == f"{_ORIGIN}/v1/embeddings"


async def test_an_http_error_carrying_a_valid_vector_is_still_an_outage() -> None:
    """Otherwise the status check can be deleted and the decoder hides it."""
    client = _client(_response(_ok([0.1, 0.2]), status=500))

    with pytest.raises(OllamaUnavailableError):
        await client.embed("проверка")


async def test_a_second_result_for_one_input_is_refused() -> None:
    client = _client(_response({"data": [{"embedding": [0.1], "index": 0}, {"embedding": [0.2], "index": 1}]}))

    with pytest.raises(OllamaUnavailableError, match="expected one embedding"):
        await client.embed("проверка")


async def test_a_result_indexed_elsewhere_is_refused() -> None:
    client = _client(_response({"data": [{"embedding": [0.1], "index": 5}]}))

    with pytest.raises(OllamaUnavailableError, match="indexed"):
        await client.embed("проверка")


async def test_a_component_that_overflows_float32_is_refused() -> None:
    """Finite in float64, infinite in the index's float32 storage."""
    client = _client(_response(_ok([1e100])))

    with pytest.raises(OllamaUnavailableError, match="float32"):
        await client.embed("проверка")


async def test_a_component_that_overflows_float64_is_refused_not_raised() -> None:
    """A JSON integer has no size limit and float() refuses 10**400."""
    client = _client(_response(_ok([10**400])))

    with pytest.raises(OllamaUnavailableError, match="out of floating-point range"):
        await client.embed("проверка")


async def test_the_largest_storable_component_is_still_accepted() -> None:
    """The guard must reject what float32 cannot hold, and nothing more."""
    client = _client(_response(_ok([3.4028234663852886e38, -3.4028234663852886e38])))

    assert await client.embed("проверка") == [3.4028234663852886e38, -3.4028234663852886e38]
