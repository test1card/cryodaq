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

The default is deliberately unchanged, so no existing deployment shifts
underneath itself; the stand states its own policy in config/rag.yaml.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from unittest.mock import AsyncMock, MagicMock

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


def test_the_shipped_config_holds_the_model_resident() -> None:
    """A default is not enough — this stand's server has the room and must use it."""
    root = Path(__file__).resolve().parents[3]
    rag = yaml.safe_load((root / "config" / "rag.yaml").read_text(encoding="utf-8"))["rag"]
    assert rag.get("embed_keep_alive"), (
        "config/rag.yaml does not hold the embedder resident; on this server that costs ~25x per embedding"
    )
    assert rag["embed_keep_alive"] != 0


def test_the_retrieval_path_shares_the_residency_policy() -> None:
    """A query that evicts the model makes the next indexed chunk pay the reload."""
    source = (Path(__file__).resolve().parents[3] / "src/cryodaq/agents/assistant_main.py").read_text(encoding="utf-8")
    # Behavioural check is impossible without booting the whole assistant; this
    # asserts the construction site was not left behind, which is the defect
    # that actually happened twice with the brand name.
    assert "embed_keep_alive" in source, (
        "assistant_main builds its own EmbeddingsClient and would still evict the model on every retrieval"
    )


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
