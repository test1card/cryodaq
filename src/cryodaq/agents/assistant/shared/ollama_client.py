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

# vLLM serves generation on the OpenAI surface: measured 2026-09-09, its
# /api/generate, /api/chat and /api/tags all answer 404, so the Ollama client
# cannot talk to it at all. One client covers both backends because the
# operator keeps Ollama running as the rollback, so switching back is a config
# edit and not a code revert. Note what that edit actually is: three keys, not
# one -- `api`, `base_url` and `default_model` -- because the two deployments
# differ in port and model name as well as in protocol. Calling it a single
# switch would be the kind of convenient overstatement this codebase is
# supposed to refuse.
_CHAT_COMPLETIONS_PATH = "/v1/chat/completions"
_API_OLLAMA = "ollama"
_API_OPENAI = "openai"
_SUPPORTED_APIS = frozenset({_API_OLLAMA, _API_OPENAI})

# Measured 2026-09-09 against qwen38 on the owner's vLLM server. The migration
# brief said both "none" and "high" are refused with HTTP 400; only "high" is.
# "none" is accepted AND honoured — three runs gave 2 output tokens in 0.49 s,
# against 106-120 tokens in 1.9 s at "low". That difference decides whether the
# intent stage stays cheap: it exists as a separate call precisely because a
# reasoning model once spent 33.6 s choosing one category word, and it costs
# 578 ms on Ollama with think=false. "low" would have tripled it.
_REASONING_EFFORT_OFF = "none"

# An ALLOW-list, not a deny-list of "length". vLLM can abort an in-flight
# generation, and an aborted answer arrives with text already written and a
# finish_reason that is neither "stop" nor "length" -- so a deny-list hands the
# operator half a diagnosis as though it were the whole one. Anything that is
# not a known-good ending is therefore reported as truncated, which costs a
# fallback at worst; the reverse mistake costs a wrong instruction to a person
# standing at a cryostat. "tool_calls" is deliberately absent: this client is
# text-only, so a tool-call reply has no answer in it either.
_COMPLETE_FINISH_REASONS = frozenset({"stop"})


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

# RFC 6598 shared address space, which NetBird and Tailscale draw overlay peer
# addresses from. Note precisely what admitting this range does and does not
# buy: it keeps the endpoint off the public internet, and it is where the
# owner's mesh peers live. It does NOT establish that the responder is a mesh
# peer, that WireGuard authenticated it, or that it is the owner's server.
# RFC 6598 defines shared address space for CGNAT; an address in it can be
# reachable over a provider or local route that has nothing to do with the
# mesh. Corrected 2026-09-05 after review found the original comment here
# claiming mesh authentication as though the code enforced it.
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
    further: 100.64.0.0/10, the RFC 6598 shared address space that NetBird and
    Tailscale draw overlay peer addresses from.

    What this function guarantees is an ADDRESS-RANGE RESTRICTION, and saying
    more than that would be false. It refuses public hosts and refuses names,
    so the endpoint cannot be silently repointed at the internet by whoever
    answers DNS. It does NOT prove the responder is a WireGuard peer, that the
    mesh authenticated it, or that it is the owner's server — RFC 6598 is
    shared address space for CGNAT, not an authentication mechanism, and its
    lack of global routability does not make it unreachable by other local or
    provider routes.

    Confirming that the configured endpoint really is the owner's server is a
    deployment matter — the approved address, the host route and the NetBird
    access policy — and is verified there, not here. The tests below pin the
    range check; they do not and cannot demonstrate authentication.

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
        raise ValueError("Ollama base URL must target a literal loopback or private-mesh (100.64.0.0/10) host") from exc
    rendered_host = f"[{host}]" if ":" in host else host
    suffix = "" if port is None else f":{port}"
    return f"http://{rendered_host}{suffix}"


class OllamaUnavailableError(Exception):
    """Ollama server unreachable (connection refused or network error)."""


class OllamaModelMissingError(Exception):
    """The server does not have the requested model.

    The remedy differs by backend and a wrong one wastes the operator's time:
    `ollama pull` cannot fix a vLLM deployment, which serves whatever model it
    was started with and cannot fetch another on request.
    """

    def __init__(self, model: str, *, remedy: str | None = None) -> None:
        self.model = model
        super().__init__(f"Model '{model}' not found. {remedy or f'Run: ollama pull {model}'}")


@dataclass
class GenerationResult:
    """Result of a single LLM generate call."""

    text: str
    tokens_in: int
    tokens_out: int
    latency_s: float
    model: str
    truncated: bool = False


def _decode_chat_completion(
    data: dict[str, Any],
    *,
    latency_s: float,
    requested_model: str,
) -> GenerationResult:
    """Turn one OpenAI-shaped response body into a GenerationResult, or refuse it.

    This is a BOUNDARY, and it exists because guarding each field where it
    happened to be read did not work. Three review rounds each found another
    field that had been trusted -- an aborted finish reason, a null error
    message, a null choice, an object-valued ``choices``, a non-mapping
    ``usage`` -- and each was fixed where it was found, which is what let the
    next one through. Nothing downstream of this function may assume a shape,
    because everything is checked here and only here.

    Two outcomes, and the distinction is the point:

    * A body that VIOLATES the protocol raises OllamaUnavailableError, because
      the caller has a path for "the model is unavailable" and no path for a
      TypeError. Announcing an outage is honest here: a server that answers
      with a list where a mapping belongs is not serving.
    * A body that is well formed but reports an INCOMPLETE answer -- null
      content, a finish reason that is not "stop" -- is returned as a normal
      result with ``truncated=True``. That is not a malformed response; it is a
      correctly reported partial one, and it must not be confused with an
      outage.

    Absent optional fields are not violations. A missing ``usage`` block yields
    zero counts; a present but malformed one is a violation, because a server
    that sends counts is claiming to know them.
    """

    def _refuse(what: str) -> OllamaUnavailableError:
        return OllamaUnavailableError(f"LLM returned a malformed response: {what}")

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise _refuse("no usable choices")
    choice = choices[0]
    if not isinstance(choice, dict):
        raise _refuse("choice is not an object")

    message = choice.get("message")
    if not isinstance(message, dict):
        raise _refuse("message is not an object")

    # None is legitimate -- it is how a budget-exhausted reasoning model reports
    # that no answer was written. A number or a list is not.
    content = message.get("content")
    if content is not None and not isinstance(content, str):
        raise _refuse("content is neither text nor null")

    finish_reason = choice.get("finish_reason")
    if finish_reason is not None and not isinstance(finish_reason, str):
        raise _refuse("finish_reason is not a string")

    # Absence and an explicit null are different claims. No "usage" key means
    # the server said nothing about counts; "usage": null means it answered the
    # question with a non-answer, which is a protocol violation like any other.
    if "usage" not in data:
        usage: dict[str, Any] = {}
    else:
        reported_usage = data["usage"]
        if not isinstance(reported_usage, dict):
            raise _refuse("usage is not an object")
        usage = reported_usage

    def _count(key: str) -> int:
        if key not in usage:
            return 0
        value = usage[key]
        # bool is an int subclass, and a negative token count is not a count.
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise _refuse(f"{key} is not a token count")
        return value

    reported_model = data.get("model")
    if reported_model is not None and not isinstance(reported_model, str):
        raise _refuse("model is not a string")

    # Two independent reasons an answer is not whole, and either alone is
    # enough. Content is None when the budget ran out before the answer was
    # written -- confirmed 2026-09-09 against the live server, where max_tokens
    # of 16 and 64 both returned out==max_tokens. Separately, the generation
    # may have ended for a reason that is not a completed answer: an aborted
    # one arrives WITH text, and a null one can arrive with "stop", so checking
    # only their conjunction would let each pass alone.
    answer_was_written = isinstance(content, str)
    generation_completed = finish_reason in _COMPLETE_FINISH_REASONS
    return GenerationResult(
        text=strip_reasoning(content) if isinstance(content, str) else "",
        tokens_in=_count("prompt_tokens"),
        tokens_out=_count("completion_tokens"),
        latency_s=latency_s,
        model=reported_model or requested_model,
        truncated=not (answer_was_written and generation_completed),
    )


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
        api: str = _API_OLLAMA,
    ) -> None:
        if api not in _SUPPORTED_APIS:
            raise ValueError(f"api must be one of {sorted(_SUPPORTED_APIS)}, got {api!r}")
        self._base_url = validate_private_llm_origin(base_url)
        self._default_model = default_model
        self._timeout_s = timeout_s
        self._api = api
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
        reasoning_effort: str | None = None,
    ) -> GenerationResult:
        """Generate one completion and return a GenerationResult.

        On timeout: returns truncated=True with empty text (does not raise).

        Raises:
            OllamaUnavailableError: server not reachable
            OllamaModelMissingError: model not pulled
        """
        effective_model = model or self._default_model
        if self._api == _API_OPENAI:
            return await self._generate_openai(
                prompt,
                model=effective_model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                think=think,
                reasoning_effort=reasoning_effort,
            )
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

    async def _generate_openai(
        self,
        prompt: str,
        *,
        model: str,
        max_tokens: int,
        temperature: float,
        system: str | None,
        think: bool | None,
        reasoning_effort: str | None,
    ) -> GenerationResult:
        """Call an OpenAI-compatible /v1/chat/completions and return the same result type.

        Deliberately NOT handled here, because the backend makes them
        meaningless rather than merely optional:

        - ``keep_alive``: vLLM holds the weights on the cards for as long as it
          runs, so there is no eviction to schedule and no cold load to pay.
          The hourly warm-up that Ollama needed goes away with it.
        - ``num_ctx``: the context length is fixed when the server starts
          (131072 for this deployment) and a request cannot shrink it.

        Both are accepted and ignored so a caller written for Ollama keeps
        working; silently ignoring them is safe, whereas forwarding them would
        be rejected by the server.
        """
        url = f"{self._base_url}{_CHAT_COMPLETIONS_PATH}"
        messages: list[dict[str, str]] = []
        if system is not None:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        # An explicit effort wins; otherwise think=False is the only mapping
        # that is unambiguous. think=True is NOT mapped to a level here: the
        # levels are not merely faster or slower, they change the answer. Asked
        # the same pressure question on 2026-09-09, "low" replied that the
        # system had reached dynamic equilibrium with outgassing and "medium"
        # replied that it indicated a leak or the pump's limit -- two different
        # diagnoses leading the operator to two different actions. Picking a
        # level silently on the caller's behalf would be choosing physics.
        effective_effort = reasoning_effort
        if effective_effort is None and think is False:
            effective_effort = _REASONING_EFFORT_OFF
        if effective_effort is not None:
            payload["reasoning_effort"] = effective_effort

        session = await self._get_session()
        t0 = time.monotonic()
        try:
            async with asyncio.timeout(self._timeout_s):
                async with session.post(
                    url,
                    json=payload,
                    allow_redirects=False,
                    headers={"Authorization": "Bearer cryodaq"},
                ) as resp:
                    if 300 <= resp.status < 400:
                        raise OllamaUnavailableError("LLM server refused an HTTP redirect")
                    status = resp.status
                    # A proxy or an overloaded server answers with HTML or
                    # plain text, and json() then raises ValueError from inside
                    # the aiohttp handlers' blind spot -- the caller would see
                    # a JSONDecodeError instead of "the LLM is unavailable",
                    # and the assistant announces an outage on that class.
                    try:
                        decoded = await resp.json(content_type=None)
                    except ValueError as exc:
                        raise OllamaUnavailableError(f"LLM returned a non-JSON body (HTTP {status}): {exc}") from exc
                    if not isinstance(decoded, dict):
                        raise OllamaUnavailableError(f"LLM returned a non-object body (HTTP {status})")
                    data: dict[str, Any] = decoded
        except TimeoutError:
            latency_s = time.monotonic() - t0
            logger.warning(
                "OllamaClient: timeout after %.1fs for model %s",
                latency_s,
                model,
            )
            return GenerationResult(
                text="",
                tokens_in=0,
                tokens_out=0,
                latency_s=latency_s,
                model=model,
                truncated=True,
            )
        except aiohttp.ClientConnectorError as exc:
            raise OllamaUnavailableError(f"Cannot connect to LLM server at {self._base_url}: {exc}") from exc
        except aiohttp.ClientError as exc:
            raise OllamaUnavailableError(f"LLM HTTP error: {exc}") from exc

        latency_s = time.monotonic() - t0

        # OpenAI-shaped errors arrive with a non-2xx status and an "error"
        # object, not the bare string Ollama returns.
        if status >= 400 or "error" in data:
            raw = data.get("error", f"HTTP {status}")
            # Not guaranteed to be a string: a server can send
            # {"error": {"message": null}} or a list, and .casefold() on that
            # raises AttributeError -- which escapes the typed outage path, so
            # the operator is told "internal error" instead of that the model
            # is down. Fall back to the whole object rather than crash.
            candidate = raw.get("message") if isinstance(raw, dict) else raw
            message = candidate if isinstance(candidate, str) else str(raw)
            lowered = message.casefold()
            if "does not exist" in lowered or "not found" in lowered:
                raise OllamaModelMissingError(
                    model,
                    remedy="This server serves only the model it was started with; check GET /v1/models.",
                )
            raise OllamaUnavailableError(f"LLM error: {message}")

        return _decode_chat_completion(data, latency_s=latency_s, requested_model=model)

    async def embed(
        self,
        text: str,
        *,
        model: str = "qwen3-embedding:0.6b",
        keep_alive: float | str | None = None,
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
            # How long the server keeps the embedder resident after answering.
            #
            # The default releases it immediately, and that is RIGHT for the
            # deployment this was written for: a 4 GB GTX 1050 Ti with no room
            # to hold the embedder beside the answering model — three resident
            # models pushed LFM2.5 to 83% CPU and every answer blew its stage
            # deadline. Reloading a 0.6b embedder cost ~2.9 s and bought the
            # generator its full GPU residency.
            #
            # It is WRONG for a server with room. Measured 2026-09-05 on the
            # owner's box with qwen3-embedding:8b: releasing after every call
            # made each embedding take 20-34 s, because each one reloaded 8B of
            # weights. Held resident, the same call takes 0.9-1.1 s — roughly
            # 25x. Across the 16,118-chunk corpus that is the difference
            # between days and hours.
            #
            # So it is a per-deployment fact, not a constant, and the caller
            # supplies it. The default is unchanged so no existing deployment
            # shifts underneath itself.
            "keep_alive": _RELEASE_IMMEDIATELY if keep_alive is None else keep_alive,
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
