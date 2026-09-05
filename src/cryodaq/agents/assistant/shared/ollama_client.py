"""Ollama HTTP client for local LLM inference."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import aiohttp

logger = logging.getLogger(__name__)

_GENERATE_PATH = "/api/generate"
# May 2026: switched к new Ollama API. /api/embeddings (legacy) still
# accepts requests but causes subprocess EOF crashes для some newer
# models. /api/embed introduced in Ollama 0.1.36 (2024) is the modern
# endpoint, accepts batched input, returns embeddings as nested list.
_EMBEDDINGS_PATH = "/api/embed"


# ---------------------------------------------------------------------------
# Reasoning-trace stripping
# ---------------------------------------------------------------------------

# See embed(): sized to the largest text ever embedded (a 1000-char chunk),
# not to the server default, so the embedder co-resides with the generator.
_EMBED_NUM_CTX = 512
# Ollama keep_alive=0: unload as soon as the call returns.
_RELEASE_IMMEDIATELY = 0

_REASONING_BLOCK = re.compile(
    r"<(?:think|thinking|reasoning)\s*>.*?</(?:think|thinking|reasoning)\s*>",
    re.IGNORECASE | re.DOTALL,
)
_REASONING_CLOSE = re.compile(r"</(?:think|thinking|reasoning)\s*>", re.IGNORECASE)

# RFC 6598 shared address space. NetBird and Tailscale assign overlay peers
# from it; it is not routable on the public internet, so an address here is
# only reachable from inside the authenticated WireGuard mesh.
_PRIVATE_MESH_NETWORK = ipaddress.ip_network("100.64.0.0/10")


def strip_reasoning(text: str) -> str:
    """Drop a thinking-first model's chain of thought, keeping only the answer.

    Reasoning models emit their scratchpad before the reply. LFM2.5 in
    particular closes the block with ``</think>`` while the *opening* tag is
    consumed as a control token and never reaches the HTTP response, so a
    naive paired-tag strip leaves the whole monologue in place — the operator
    then reads it in Telegram ahead of the two sentences they asked for.

    Everything before the last closing tag is therefore treated as reasoning.
    An unterminated block means the answer never arrived: the raw text is more
    useful to a human than an empty bubble, so it is returned unchanged.
    """
    if not text:
        return text
    cleaned = _REASONING_BLOCK.sub("", text)
    closes = list(_REASONING_CLOSE.finditer(cleaned))
    if closes:
        cleaned = cleaned[closes[-1].end() :]
    stripped = cleaned.strip()
    return stripped if stripped else text.strip()


def validate_private_llm_origin(base_url: str) -> str:
    """Return a normalized private HTTP origin, or reject it before any I/O.

    The assistant sends lab material to this endpoint — readings, alarm text,
    operator-log lines. Until 2026-09-05 the only address it would accept was a
    literal loopback IP, which made "the data never leaves this machine" an
    enforced fact rather than a promise.

    The owner moved inference to their own server, so loopback alone no longer
    covers the deployment. The rule is widened by exactly one range and no
    further: 100.64.0.0/10, the shared address space of RFC 6598, which
    NetBird and Tailscale use for overlay peers.

    That range is chosen because it is not routable on the public internet.
    Reaching an address inside it requires membership of the authenticated
    WireGuard mesh, so the invariant becomes "loopback, or a peer on the
    private mesh" — never a public host, and never DNS-resolved.

    Everything else the original check enforced is kept deliberately: http
    only, a LITERAL address rather than a hostname (a name can be repointed by
    whoever answers DNS), no userinfo, and no path, query or fragment.
    """

    if type(base_url) is not str or not base_url.strip():
        raise ValueError("Ollama base URL must be a non-empty loopback HTTP origin")
    candidate = base_url.strip()
    if any(char in candidate for char in "\r\n"):
        raise ValueError("Ollama base URL must not contain control characters")
    try:
        parsed = urlsplit(candidate)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Ollama base URL is malformed") from exc
    if parsed.scheme.casefold() != "http" or hostname is None:
        raise ValueError("Ollama base URL must use http on a loopback or private-mesh host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Ollama base URL must not contain userinfo")
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("Ollama base URL must be an origin without path or query")
    host = hostname.casefold()
    try:
        address = ipaddress.ip_address(host)
        if not (address.is_loopback or address in _PRIVATE_MESH_NETWORK):
            raise ValueError
    except ValueError as exc:
        raise ValueError(
            "Ollama base URL must target a literal loopback or private-mesh (100.64.0.0/10) host"
        ) from exc
    rendered_host = f"[{host}]" if ":" in host else host
    suffix = "" if port is None else f":{port}"
    return f"http://{rendered_host}{suffix}"


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
        base_url: str = "http://127.0.0.1:11434",
        default_model: str = "gemma4:e4b",
        *,
        timeout_s: float = 30.0,
    ) -> None:
        self._base_url = validate_private_llm_origin(base_url)
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
        keep_alive: str | int | None = None,
        think: bool | None = None,
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
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive
        if think is not None:
            # Ollama's own switch for a reasoning model's chain of thought.
            # `_strip_reasoning` cleans the OUTPUT, which costs the tokens
            # anyway; this stops them being generated. Measured 2026-09-05 on
            # qwen3.8:27b: a one-word intent answer takes 578 ms warm with
            # think=false. The stage exists as a separate cheap call precisely
            # because a reasoning model once spent 33.6 s on that decision.
            payload["think"] = think

        session = await self._get_session()
        t0 = time.monotonic()

        try:
            async with asyncio.timeout(self._timeout_s):
                async with session.post(url, json=payload, allow_redirects=False) as resp:
                    if 300 <= resp.status < 400:
                        raise OllamaUnavailableError("Ollama refused an HTTP redirect")
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
            raise OllamaUnavailableError(f"Cannot connect to Ollama at {self._base_url}: {exc}") from exc
        except aiohttp.ClientError as exc:
            raise OllamaUnavailableError(f"Ollama HTTP error: {exc}") from exc

        latency_s = time.monotonic() - t0

        if "error" in data:
            err = str(data["error"])
            if "not found" in err.lower():
                raise OllamaModelMissingError(effective_model)
            raise OllamaUnavailableError(f"Ollama error: {err}")

        # done_reason == "length" means num_predict cut generation off. For a
        # reasoning model that is not a slightly short answer: the trace ate
        # the budget and the answer was never written, so the text is raw
        # scratchpad. Reported as truncated so callers fall back instead of
        # showing the operator a half-finished thought.
        hit_token_ceiling = str(data.get("done_reason", "")) == "length"
        return GenerationResult(
            text=strip_reasoning(data.get("response", "")),
            tokens_in=data.get("prompt_eval_count", 0),
            tokens_out=data.get("eval_count", 0),
            latency_s=latency_s,
            model=data.get("model", effective_model),
            truncated=hit_token_ceiling,
        )

    async def embed(
        self,
        text: str,
        *,
        model: str = "qwen3-embedding:0.6b",
    ) -> list[float]:
        """Call Ollama /api/embed and return the raw vector.

        F32: distinct from generate() — uses /api/embed (modern endpoint),
        returns the raw vector. Embedding model defaults to
        qwen3-embedding:0.6b (May 2026 default, top of MTEB multilingual
        leaderboard) but is overridable per call. Embedding model is *not*
        the same as the generation model; pass it per-call.
        """
        url = f"{self._base_url}{_EMBEDDINGS_PATH}"
        # New /api/embed expects "input" (str or list[str]); returns
        # "embeddings": [[float,...]] (always batched, even for one input).
        # Cap the embedder's context. Ollama sizes a model's VRAM reservation
        # from num_ctx, and the server default (4096) makes qwen3-embedding
        # claim 2.5 GB — which on a 4 GB card evicts the generation model on
        # every retrieval, so each documentation question paid a reload of the
        # embedder AND a reload of the answering model. At 512 the same
        # embedder occupies 1.0 GB and both stay resident. Nothing is
        # truncated: index chunks are capped at 1000 chars (~350 tokens) by
        # rag chunk_max_chars, and a query is shorter still.
        payload = {
            "model": model,
            "input": text,
            "options": {"num_ctx": _EMBED_NUM_CTX},
            # Release the embedder the moment the vector is returned. It is
            # needed only to turn one question into one vector (~0.1s warm),
            # and this card has no room to keep it alongside the answering
            # model: three resident models pushed LFM2.5 to 83% CPU and every
            # answer then blew its stage deadline. Reloading costs ~2.9s and
            # buys the generator its full GPU residency and context budget.
            "keep_alive": _RELEASE_IMMEDIATELY,
        }
        session = await self._get_session()
        t0 = time.monotonic()
        try:
            async with asyncio.timeout(self._timeout_s):
                async with session.post(url, json=payload, allow_redirects=False) as resp:
                    if 300 <= resp.status < 400:
                        raise OllamaUnavailableError("Ollama refused an HTTP redirect")
                    if resp.status == 404:
                        raise OllamaModelMissingError(model)
                    data: dict[str, Any] = await resp.json(content_type=None)
        except TimeoutError:
            # Mirror generate(): on timeout return empty (no raise) so a stalled
            # embedding degrades to "no embedding" rather than propagating up.
            logger.warning(
                "OllamaClient: embed timeout after %.1fs for model %s",
                time.monotonic() - t0,
                model,
            )
            return []
        except aiohttp.ClientConnectorError as exc:
            raise OllamaUnavailableError(f"Cannot connect to Ollama at {self._base_url}: {exc}") from exc
        except aiohttp.ClientError as exc:
            raise OllamaUnavailableError(f"Ollama HTTP error: {exc}") from exc

        if "error" in data:
            err = str(data["error"])
            if "not found" in err.lower():
                raise OllamaModelMissingError(model)
            raise OllamaUnavailableError(f"Ollama embed error: {err}")

        # New API: data["embeddings"] is list[list[float]] (batched response)
        embeddings = data.get("embeddings", [])
        if embeddings:
            return list(embeddings[0])
        # Fallback к legacy single-vector format в case of mixed responses
        return list(data.get("embedding", []))
