"""F32 — Embeddings client.

Thin wrapper around the existing OllamaClient.embed() so the RAG module
owns its own dependency surface and tests can swap in a deterministic
mock without touching the assistant agent.
"""

from __future__ import annotations

import math

from cryodaq.agents.assistant.shared.ollama_client import OllamaClient


class EmbeddingsClient:
    """Compute embeddings via a local Ollama instance.

    Owns a private OllamaClient — call `close()` on shutdown.
    """

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "qwen3-embedding:0.6b",
        timeout_s: float = 30.0,
        keep_alive: float | str | None = None,
        api: str = "ollama",
    ) -> None:
        self._model = model
        # Which HTTP surface the embedding server speaks. Separate from the
        # chat model's setting on purpose: the two can live on different
        # servers, and for most of this project's life they have.
        self._api = api
        # None keeps the historical behaviour: release the embedder as soon as
        # the vector is returned. Deployments with room to hold it pass a
        # duration; see OllamaClient.embed for the measurements.
        self._keep_alive = keep_alive
        self._base_url = base_url
        self._timeout_s = timeout_s
        self._client = OllamaClient(
            base_url=base_url,
            default_model=model,
            timeout_s=timeout_s,
            api=api,
        )

    @property
    def api(self) -> str:
        return self._api

    @property
    def model(self) -> str:
        return self._model

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def timeout_s(self) -> float:
        """What this client will ACTUALLY wait. Log this, not the config value.

        The two were allowed to disagree: rag.yaml said 180 s while the
        retrieval client silently kept the 30 s default, and no log line said
        so because every one of them reported the configuration rather than
        the object built from it.
        """
        return self._timeout_s

    async def embed(self, text: str) -> list[float]:
        return await self._client.embed(text, model=self._model, keep_alive=self._keep_alive)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed(t) for t in texts]

    async def close(self) -> None:
        await self._client.close()


DEFAULT_EMBED_TIMEOUT_S = 180.0


def _positive_float(value: object, fallback: float) -> float:
    """Coerce a config value, falling back rather than raising.

    A malformed `embed_timeout_s` — an empty string, a stray list, a typo —
    must not stop a rebuild before it starts. Bare float() raises on all
    three, which would turn a one-character config error into a traceback at
    the top of a multi-hour job.
    """
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(parsed) or parsed <= 0:
        return fallback
    return parsed


def make_embeddings_client(rag_cfg: dict) -> EmbeddingsClient:
    """The ONE way to build this client from configuration.

    The timeout is not decoration. A single embed call against this stand's
    server was MEASURED at 20-34 s, straddling the client's 30 s default, so
    calls timed out at random: during indexing each one became an unsearchable
    zero vector, and the 19:53 rebuild on 2026-09-05 lost six chunks exactly
    that way. `embed_timeout_s: 180.0` has been in rag.yaml since.

    It was passed on the indexing path and NOT on the retrieval path, which
    kept the 30 s default while its own config said 180 — so a cold model
    could fail an operator's question with nothing but a warning, which is
    what review found on 2026-09-07. Two call sites, one of them right, is how
    that survived; there is now one builder, so a third caller cannot repeat
    it.
    """
    return EmbeddingsClient(
        base_url=rag_cfg.get("ollama_base_url", "http://127.0.0.1:11434"),
        model=rag_cfg.get("embedding_model", "qwen3-embedding:0.6b"),
        timeout_s=_positive_float(rag_cfg.get("embed_timeout_s"), DEFAULT_EMBED_TIMEOUT_S),
        keep_alive=rag_cfg.get("embed_keep_alive"),
        # Defaults to ollama so no existing deployment moves underneath itself.
        api=str(rag_cfg.get("api", "ollama")),
    )
