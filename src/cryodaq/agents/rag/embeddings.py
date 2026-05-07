"""F32 — Embeddings client.

Thin wrapper around the existing OllamaClient.embed() so the RAG module
owns its own dependency surface and tests can swap in a deterministic
mock without touching the assistant agent.
"""

from __future__ import annotations

from cryodaq.agents.assistant.shared.ollama_client import OllamaClient


class EmbeddingsClient:
    """Compute embeddings via a local Ollama instance.

    Owns a private OllamaClient — call `close()` on shutdown.
    """

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:11434",
        model: str = "qwen3-embedding:0.6b",
        timeout_s: float = 30.0,
    ) -> None:
        self._model = model
        self._client = OllamaClient(
            base_url=base_url,
            default_model=model,
            timeout_s=timeout_s,
        )

    @property
    def model(self) -> str:
        return self._model

    async def embed(self, text: str) -> list[float]:
        return await self._client.embed(text, model=self._model)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed(t) for t in texts]

    async def close(self) -> None:
        await self._client.close()
