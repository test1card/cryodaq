"""Ollama HTTP client for local LLM inference."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

_GENERATE_PATH = "/api/generate"


class OllamaUnavailableError(Exception):
    """Ollama server unreachable (connection refused or network error)."""


class OllamaModelMissingError(Exception):
    """Requested model is not pulled on this Ollama instance."""

    def __init__(self, model: str) -> None:
        self.model = model
        super().__init__(f"Model '{model}' not found. Run: ollama pull {model}")


@dataclass
class GenerationResult:
    """Result of a single LLM generate call."""

    text: str
    tokens_in: int
    tokens_out: int
    latency_s: float
    model: str
    truncated: bool = False


class OllamaClient:
    """Async HTTP wrapper around Ollama /api/generate.

    Manages one aiohttp.ClientSession; call close() on shutdown.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        default_model: str = "gemma4:e4b",
        *,
        timeout_s: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._timeout_s = timeout_s
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        """Close the underlying HTTP session."""
        if self._session is not None and not self._session.closed:
            await self._session.close()
            self._session = None

    async def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.3,
        system: str | None = None,
        num_ctx: int | None = None,
    ) -> GenerationResult:
        """Call Ollama /api/generate and return a GenerationResult.

        On timeout: returns truncated=True with empty text (does not raise).

        Raises:
            OllamaUnavailableError: server not reachable
            OllamaModelMissingError: model not pulled
        """
        effective_model = model or self._default_model
        url = f"{self._base_url}{_GENERATE_PATH}"
        options: dict[str, Any] = {
            "num_predict": max_tokens,
            "temperature": temperature,
        }
        if num_ctx is not None:
            options["num_ctx"] = num_ctx
        payload: dict[str, Any] = {
            "model": effective_model,
            "prompt": prompt,
            "stream": False,
            "options": options,
        }
        if system is not None:
            payload["system"] = system

        session = await self._get_session()
        t0 = time.monotonic()

        try:
            async with asyncio.timeout(self._timeout_s):
                async with session.post(url, json=payload) as resp:
                    data: dict[str, Any] = await resp.json(content_type=None)
        except TimeoutError:
            latency_s = time.monotonic() - t0
            logger.warning(
                "OllamaClient: timeout after %.1fs for model %s",
                latency_s,
                effective_model,
            )
            return GenerationResult(
                text="",
                tokens_in=0,
                tokens_out=0,
                latency_s=latency_s,
                model=effective_model,
                truncated=True,
            )
        except aiohttp.ClientConnectorError as exc:
            raise OllamaUnavailableError(
                f"Cannot connect to Ollama at {self._base_url}: {exc}"
            ) from exc
        except aiohttp.ClientError as exc:
            raise OllamaUnavailableError(f"Ollama HTTP error: {exc}") from exc

        latency_s = time.monotonic() - t0

        if "error" in data:
            err = str(data["error"])
            if "not found" in err.lower():
                raise OllamaModelMissingError(effective_model)
            raise OllamaUnavailableError(f"Ollama error: {err}")

        return GenerationResult(
            text=data.get("response", ""),
            tokens_in=data.get("prompt_eval_count", 0),
            tokens_out=data.get("eval_count", 0),
            latency_s=latency_s,
            model=data.get("model", effective_model),
        )
