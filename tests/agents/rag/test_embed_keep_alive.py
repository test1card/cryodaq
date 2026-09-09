"""Whether the embedder stays resident is a deployment fact, not a constant.

`OllamaClient.embed` sent `keep_alive: 0` unconditionally — release the model
the instant the vector comes back. That was correct for the deployment it was
written for: a 4 GB GTX 1050 Ti with no room to hold the embedder beside the
answering model.

It became expensive when retrieval moved to the owner's server. Measured on
2026-09-05 with qwen3-embedding:8b, same machine, same corpus:

    released after every call    20-34 s per embedding
    held resident                0.9-1.1 s per embedding

Every call was reloading 8B of weights. `/api/ps` reports 5.0 GB resident once
it is held. Across the 16,118-chunk literature corpus that is the difference
between days and hours — and it is also why an earlier reading of "the server
is simply slow" was wrong: a concurrent rebuild was evicting the model between
the probe calls that were meant to measure it.

The client default is deliberately unchanged, so no existing deployment shifts
underneath itself; the stand states its own policy in config/rag.yaml. That
policy was reversed on 2026-09-10 when the chat model moved to vLLM and the
cards no longer had room for both — see the shipped-config test below, which
carries the cost of the reversal so it is not undone by accident.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from cryodaq.agents.assistant.shared.ollama_client import OllamaClient
from cryodaq.agents.rag.cli import _make_embeddings
from cryodaq.agents.rag.embeddings import EmbeddingsClient


class _CapturingClient:
    """Stands in for OllamaClient and records what embed() was told."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def embed(self, text, *, model, keep_alive=None):
        self.calls.append({"text": text, "model": model, "keep_alive": keep_alive})
        return [0.1, 0.2]

    async def close(self) -> None:
        return None


def _with_capturing(client: EmbeddingsClient) -> _CapturingClient:
    capture = _CapturingClient()
    client._client = capture
    return capture


@pytest.mark.asyncio
async def test_the_default_still_releases_the_model_immediately() -> None:
    """No existing deployment may shift underneath itself."""
    client = EmbeddingsClient(model="qwen3-embedding:0.6b")
    capture = _with_capturing(client)

    await client.embed("что с давлением")

    assert capture.calls[0]["keep_alive"] is None, (
        "the default must stay None so OllamaClient applies its historical release-immediately behaviour"
    )


@pytest.mark.asyncio
async def test_a_configured_residency_reaches_the_call() -> None:
    client = EmbeddingsClient(model="qwen3-embedding:8b", keep_alive="30m")
    capture = _with_capturing(client)

    await client.embed("что с давлением")

    assert capture.calls[0]["keep_alive"] == "30m"


def test_the_cli_passes_the_configured_residency() -> None:
    client = _make_embeddings(
        {
            "ollama_base_url": "http://127.0.0.1:11434",
            "embedding_model": "qwen3-embedding:8b",
            "embed_keep_alive": "30m",
        }
    )
    assert client._keep_alive == "30m"


def test_the_cli_default_is_unchanged_when_config_is_silent() -> None:
    assert _make_embeddings({})._keep_alive is None


def test_the_shipped_config_releases_the_embedder() -> None:
    """The residency decision was reversed on 2026-09-10, and it cost something.

    This test used to assert the opposite -- that the shipped config HOLDS the
    embedder resident, because the server had room. It stopped having room: the
    chat model moved to vLLM, which pins its weights on the same cards for as
    long as it runs, and 5.0 GB of resident embedder beside it left the two
    elbowing each other for video memory. The operator observed that and called
    the trade.

    The price is stated so nobody reverses it back unaware: released, an
    embedding costs 20-34 s instead of 0.9-1.1 s, because each call reloads 8B
    of weights. That is paid only while retrieval or indexing actually runs, and
    it must be raised again before any RAG rebuild -- across the 16,118-chunk
    corpus it is the difference between hours and days.
    """
    root = Path(__file__).resolve().parents[3]
    rag = yaml.safe_load((root / "config" / "rag.yaml").read_text(encoding="utf-8"))["rag"]

    assert "embed_keep_alive" in rag, "config/rag.yaml must state its residency policy explicitly"
    assert rag["embed_keep_alive"] == 0


def test_the_retrieval_path_shares_the_residency_policy() -> None:
    """A query that evicts the model makes the next indexed chunk pay the reload.

    This used to read `assistant_main.py` and look for the string
    `embed_keep_alive`, because — as its own comment said — a behavioural check
    was impossible without booting the whole assistant. That stopped being true
    on 2026-09-07: indexing and retrieval had drifted (retrieval passed
    keep_alive but not the timeout), and both now go through one builder, so
    the policy can simply be read off the object.
    """
    from cryodaq.agents.rag.embeddings import make_embeddings_client

    client = make_embeddings_client({"embed_keep_alive": "30m"})

    assert client._keep_alive == "30m", "retrieval would evict the model on every query"


# ---------------------------------------------------------------------------
# The payload itself. The tests above swap out the inner OllamaClient, so they
# would all still pass with embed() sending a hardcoded keep_alive — a negative
# control caught exactly that. These exercise the real payload construction.
# ---------------------------------------------------------------------------


def _session_capturing_payload() -> tuple[MagicMock, dict]:
    seen: dict = {}
    resp = AsyncMock()
    resp.status = 200
    resp.json = AsyncMock(return_value={"embeddings": [[0.1, 0.2]]})
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=False)

    def _post(url, *, json=None, **kwargs):
        seen.update(json or {})
        return cm

    session = AsyncMock()
    session.closed = False
    session.post = MagicMock(side_effect=_post)
    return session, seen


@pytest.mark.asyncio
async def test_the_posted_payload_carries_the_requested_residency() -> None:
    client = OllamaClient(base_url="http://127.0.0.1:11434")
    session, seen = _session_capturing_payload()
    client._get_session = AsyncMock(return_value=session)

    await client.embed("тест", model="qwen3-embedding:8b", keep_alive="30m")

    assert seen.get("keep_alive") == "30m", (
        f"embed() posted keep_alive={seen.get('keep_alive')!r}; the configured "
        "residency never reached the server, so the model is still evicted "
        "after every call"
    )


@pytest.mark.asyncio
async def test_the_posted_payload_still_releases_by_default() -> None:
    client = OllamaClient(base_url="http://127.0.0.1:11434")
    session, seen = _session_capturing_payload()
    client._get_session = AsyncMock(return_value=session)

    await client.embed("тест", model="qwen3-embedding:0.6b")

    assert seen.get("keep_alive") == 0


@pytest.mark.asyncio
async def test_residency_survives_the_whole_chain_from_config() -> None:
    """Config -> EmbeddingsClient -> OllamaClient -> the wire."""
    embeddings = _make_embeddings({"embedding_model": "qwen3-embedding:8b", "embed_keep_alive": "30m"})
    session, seen = _session_capturing_payload()
    embeddings._client._get_session = AsyncMock(return_value=session)

    await embeddings.embed("тест")

    assert seen.get("keep_alive") == "30m"
