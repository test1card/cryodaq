# F28 Cycle 1 audit — Ollama client + audit log + context builder

## Context

CryoDAQ v0.44.0, Python 3.12+, asyncio. Safety-critical cryogenic DAQ.
Branch feat/f28-hermes-agent, commit 164a8da.

Cycle 1 adds the Ollama HTTP client, audit logger, and context builder
skeleton for the upcoming GemmaAgent (Гемма) local LLM agent.
Default model updated from gemma3:e4b to gemma4:e4b (what is installed).

## Files changed

- src/cryodaq/agents/ollama_client.py (NEW, 145 LOC)
- src/cryodaq/agents/audit.py (NEW, 86 LOC)
- src/cryodaq/agents/context_builder.py (NEW, 110 LOC)
- src/cryodaq/core/event_bus.py (MODIFIED, +2 LOC — warn on duplicate subscribe)
- tests/agents/test_ollama_client.py (NEW, 281 LOC — 16 unit + 1 smoke)
- pyproject.toml (MODIFIED — registers "smoke" marker)

Smoke test PASSED against real gemma4:e4b in 24.94s.

## Diff

```
164a8da feat(f28): Cycle 1 — Ollama client + audit log + context builder skeleton (23 seconds ago) <Vladimir Fomenko>
pyproject.toml                        |   3 +
 src/cryodaq/agents/__init__.py        |   0
 src/cryodaq/agents/audit.py           |  86 +++++++++++
 src/cryodaq/agents/context_builder.py | 110 +++++++++++++
 src/cryodaq/agents/ollama_client.py   | 145 ++++++++++++++++++
 src/cryodaq/core/event_bus.py         |   2 +
 tests/agents/__init__.py              |   0
 tests/agents/test_ollama_client.py    | 281 ++++++++++++++++++++++++++++++++++
 8 files changed, 627 insertions(+)

pyproject.toml
  @@ -83,6 +83,9 @@ packages = ["src/cryodaq"]
  +markers = [
  +    "smoke: requires live external services (ollama, instruments); excluded from default CI",
  +]
   
   [tool.ruff]
   target-version = "py312"
  +3 -0

src/cryodaq/agents/__init__.py

src/cryodaq/agents/audit.py
  @@ -0,0 +1,86 @@
  +"""Audit logger — persists every GemmaAgent LLM call for post-hoc review."""
  +
  +from __future__ import annotations
  +
  +import json
  +import logging
  +import uuid
  +from datetime import UTC, datetime
  +from pathlib import Path
  +from typing import Any
  +
  +logger = logging.getLogger(__name__)
  +
  +
  +class AuditLogger:
  +    """Writes one JSON file per LLM call under audit_dir/<YYYY-MM-DD>/.
  +
  +    Schema per file matches docs/ORCHESTRATION spec §2.8 audit record.
  +    Retention housekeeping (deleting old files) is handled by HousekeepingService.
  +    """
  +
  +    def __init__(
  +        self,
  +        audit_dir: Path,
  +        *,
  +        enabled: bool = True,
  +        retention_days: int = 90,
  +    ) -> None:
  +        self._audit_dir = Path(audit_dir)
  +        self._enabled = enabled
  +        self._retention_days = retention_days
  +
  +    def make_audit_id(self) -> str:
  +        """Return a short unique ID for one audit record."""
  +        return uuid.uuid4().hex[:12]
  +
  +    async def log(
  +        self,
  +        *,
  +        audit_id: str,
  +        trigger_event: dict[str, Any],
  +        context_assembled: str,
  +        prompt_template: str,
  +        model: str,
  +        system_prompt: str,
  +        user_prompt: str,
  +        response: str,
  +        tokens: dict[str, int],
  +        latency_s: float,
  +        outputs_dispatched: list[str],
  +        errors: list[str],
  +    ) -> Path | None:
  +        """Persist an audit record. Returns the file path, or None if disabled or failed."""
  +        if not self._enabled:
  +            return None
  +
  +        now = datetime.now(UTC)
  +        date_dir = self._audit_dir / now.strftime("%Y-%m-%d")
  +        date_dir.mkdir(parents=True, exist_ok=True)
  +
  +        filename = f"{now.strftime('%Y%m%dT%H%M%S%f')}_{audit_id}.json"
  +        path = date_dir / filename
  +
  +        record: dict[str, Any] = {
  +            "audit_id": audit_id,
  +            "timestamp": now.isoformat(),
  +            "trigger_event": trigger_event,
  +            "context_assembled": context_assembled,
  +            "prompt_template": prompt_template,
  +            "model": model,
  +            "system_prompt": system_prompt,
  +            "user_prompt": user_prompt,
  +            "response": response,
  +            "tokens": tokens,
  +            "latency_s": round(latency_s, 3),
  +            "outputs_dispatched": outputs_dispatched,
  +            "errors": errors,
  +        }
  +
  +        try:
  +            path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
  +        except Exception:
  +            logger.warning("AuditLogger: failed to write %s", path, exc_info=True)
  +            return None
  +
  +        return path
  +86 -0

src/cryodaq/agents/context_builder.py
  @@ -0,0 +1,110 @@
  +"""Context assembler for GemmaAgent LLM prompts.
  +
  +Each task type (alarm summary, diagnostic, campaign report) requires
  +different context. Builders read SQLite state and format compact text
  +for LLM token budget.
  +
  +Cycle 1: AlarmContext dataclass + build_alarm_context interface.
  +SQLite queries and full context assembly wired in Cycle 2.
  +Slice B (diagnostic) and Slice C (campaign) contexts deferred.
  +"""
  +
  +from __future__ import annotations
  +
  +import logging
  +from dataclasses import dataclass, field
  +from typing import Any
  +
  +logger = logging.getLogger(__name__)
  +
  +
  +@dataclass
  +class AlarmContext:
  +    """Context for alarm summary generation (Slice A)."""
  +
  +    alarm_id: str
  +    level: str
  +    channels: list[str]
  +    values: dict[str, float]
  +    phase: str | None
  +    experiment_id: str | None
  +    experiment_age_s: float | None
  +    target_temp: float | None
  +    active_interlocks: list[str] = field(default_factory=list)
  +    recent_readings_text: str = ""
  +    recent_alarms_text: str = ""
  +
  +
  +class ContextBuilder:
  +    """Assembles engine state for LLM prompt construction."""
  +
  +    def __init__(self, sqlite_reader: Any, experiment_manager: Any) -> None:
  +        self._reader = sqlite_reader
  +        self._em = experiment_manager
  +
  +    async def build_alarm_context(
  +        self,
  +        alarm_payload: dict[str, Any],
  +        *,
  +        lookback_s: float = 60.0,
  +        recent_alarm_lookback_s: float = 3600.0,
  +    ) -> AlarmContext:
  +        """Assemble context for a Slice A alarm summary prompt.
  +
  +        Reads experiment state from ExperimentManager (in-memory, fast).
  +        SQLite reading history and alarm history wired in Cycle 2.
  +        """
  +        alarm_id = alarm_payload.get("alarm_id", "unknown")
  +        channels: list[str] = alarm_payload.get("channels", [])
  +        values: dict[str, float] = alarm_payload.get("values", {})
  +        level: str = alarm_payload.get("level", "WARNING")
  +
  +        experiment_id: str | None = getattr(self._em, "active_experiment_id", None)
  +
  +        phase: str | None = None
  +        if hasattr(self._em, "get_current_phase"):
  +            try:
  +                phase = self._em.get_current_phase()
  +            except Exception:
  +                pass
  +
  +        experiment_age_s: float | None = _compute_experiment_age(self._em)
  +
  +        return AlarmContext(
  +            alarm_id=alarm_id,
  +            level=level,
  +            channels=channels,
  +            values=values,
  +            phase=phase,
  +            experiment_id=experiment_id,
  +            experiment_age_s=experiment_age_s,
  +            target_temp=None,
  +            active_interlocks=[],
  +            recent_readings_text=_readings_stub(channels, lookback_s),
  +            recent_alarms_text=_alarms_stub(recent_alarm_lookback_s),
  +        )
  +
  +
  +def _compute_experiment_age(em: Any) -> float | None:
  +    try:
  +        history = em.get_phase_history()
  +        if not history:
  +            return None
  +        first = history[0].get("started_at")
  +        if not first:
  +            return None
  +        from datetime import UTC, datetime
  +
  +        started = datetime.fromisoformat(first)
  +        return (datetime.now(UTC) - started.astimezone(UTC)).total_seconds()
  +    except Exception:
  ... (10 lines truncated)
  +110 -0

src/cryodaq/agents/ollama_client.py
  @@ -0,0 +1,145 @@
  +"""Ollama HTTP client for local LLM inference."""
  +
  +from __future__ import annotations
  +
  +import asyncio
  +import logging
  +import time
  +from dataclasses import dataclass
  +from typing import Any
  +
  +import aiohttp
  +
  +logger = logging.getLogger(__name__)
  +
  +_GENERATE_PATH = "/api/generate"
  +
  +
  +class OllamaUnavailableError(Exception):
  +    """Ollama server unreachable (connection refused or network error)."""
  +
  +
  +class OllamaModelMissingError(Exception):
  +    """Requested model is not pulled on this Ollama instance."""
  +
  +    def __init__(self, model: str) -> None:
  +        self.model = model
  +        super().__init__(f"Model '{model}' not found. Run: ollama pull {model}")
  +
  +
  +@dataclass
  +class GenerationResult:
  +    """Result of a single LLM generate call."""
  +
  +    text: str
  +    tokens_in: int
  +    tokens_out: int
  +    latency_s: float
  +    model: str
  +    truncated: bool = False
  +
  +
  +class OllamaClient:
  +    """Async HTTP wrapper around Ollama /api/generate.
  +
  +    Manages one aiohttp.ClientSession; call close() on shutdown.
  +    """
  +
  +    def __init__(
  +        self,
  +        base_url: str = "http://localhost:11434",
  +        default_model: str = "gemma4:e4b",
  +        *,
  +        timeout_s: float = 30.0,
  +    ) -> None:
  +        self._base_url = base_url.rstrip("/")
  +        self._default_model = default_model
  +        self._timeout_s = timeout_s
  +        self._session: aiohttp.ClientSession | None = None
  +
  +    async def _get_session(self) -> aiohttp.ClientSession:
  +        if self._session is None or self._session.closed:
  +            self._session = aiohttp.ClientSession()
  +        return self._session
  +
  +    async def close(self) -> None:
  +        """Close the underlying HTTP session."""
  +        if self._session is not None and not self._session.closed:
  +            await self._session.close()
  +            self._session = None
  +
  +    async def generate(
  +        self,
  +        prompt: str,
  +        *,
  +        model: str | None = None,
  +        max_tokens: int = 1024,
  +        temperature: float = 0.3,
  +        system: str | None = None,
  +    ) -> GenerationResult:
  +        """Call Ollama /api/generate and return a GenerationResult.
  +
  +        On timeout: returns truncated=True with empty text (does not raise).
  +
  +        Raises:
  +            OllamaUnavailableError: server not reachable
  +            OllamaModelMissingError: model not pulled
  +        """
  +        effective_model = model or self._default_model
  +        url = f"{self._base_url}{_GENERATE_PATH}"
  +        payload: dict[str, Any] = {
  +            "model": effective_model,
  +            "prompt": prompt,
  +            "stream": False,
  +            "options": {
  +                "num_predict": max_tokens,
  +                "temperature": temperature,
  +            },
  +        }
  +        if system is not None:
  +            payload["system"] = system
  ... (45 lines truncated)
  +145 -0

src/cryodaq/core/event_bus.py
  @@ -34,6 +34,8 @@ class EventBus:
  +        if name in self._subscribers:
  +            logger.warning("EventBus: duplicate subscribe '%s' — replacing existing queue", name)
           q: asyncio.Queue[EngineEvent] = asyncio.Queue(maxsize=maxsize)
           self._subscribers[name] = q
           return q
  +2 -0

tests/agents/__init__.py

tests/agents/test_ollama_client.py
  @@ -0,0 +1,281 @@
  +"""Tests for OllamaClient — mock HTTP + smoke test."""
  +
  +from __future__ import annotations
  +
  +from unittest.mock import AsyncMock, MagicMock, patch
  +
  +import pytest
  +
  +from cryodaq.agents.ollama_client import (
  +    GenerationResult,
  +    OllamaClient,
  +    OllamaModelMissingError,
  +    OllamaUnavailableError,
  +)
  +
  +# ---------------------------------------------------------------------------
  +# Helpers
  +# ---------------------------------------------------------------------------
  +
  +
  +def _mock_response(data: dict) -> MagicMock:
  +    """Build a mock aiohttp async context manager returning data."""
  +    resp = AsyncMock()
  +    resp.json = AsyncMock(return_value=data)
  +    cm = AsyncMock()
  +    cm.__aenter__ = AsyncMock(return_value=resp)
  +    cm.__aexit__ = AsyncMock(return_value=False)
  +    return cm
  +
  +
  +def _mock_session(response_cm) -> MagicMock:
  +    s = AsyncMock()
  +    s.closed = False
  +    s.post = MagicMock(return_value=response_cm)
  +    return s
  +
  +
  +def _success_data(
  +    text: str = "Гемма: всё в норме.",
  +    tokens_in: int = 100,
  +    tokens_out: int = 30,
  +    model: str = "gemma3:e4b",
  +) -> dict:
  +    return {
  +        "model": model,
  +        "response": text,
  +        "prompt_eval_count": tokens_in,
  +        "eval_count": tokens_out,
  +        "done": True,
  +    }
  +
  +
  +# ---------------------------------------------------------------------------
  +# GenerationResult dataclass
  +# ---------------------------------------------------------------------------
  +
  +
  +def test_generation_result_fields() -> None:
  +    r = GenerationResult(
  +        text="response", tokens_in=10, tokens_out=5, latency_s=1.2, model="gemma3:e4b"
  +    )
  +    assert r.text == "response"
  +    assert r.tokens_in == 10
  +    assert r.tokens_out == 5
  +    assert r.latency_s == 1.2
  +    assert r.model == "gemma3:e4b"
  +    assert r.truncated is False
  +
  +
  +def test_generation_result_truncated_default_false() -> None:
  +    r = GenerationResult(text="", tokens_in=0, tokens_out=0, latency_s=0.1, model="m")
  +    assert r.truncated is False
  +
  +
  +# ---------------------------------------------------------------------------
  +# Successful generation
  +# ---------------------------------------------------------------------------
  +
  +
  +async def test_generate_returns_text_and_counts() -> None:
  +    client = OllamaClient(default_model="gemma3:e4b")
  +    client._session = _mock_session(_mock_response(_success_data()))
  +
  +    result = await client.generate("Summarize alarm")
  +
  +    assert result.text == "Гемма: всё в норме."
  +    assert result.tokens_in == 100
  +    assert result.tokens_out == 30
  +    assert result.model == "gemma3:e4b"
  +    assert not result.truncated
  +
  +
  +async def test_generate_uses_default_model() -> None:
  +    client = OllamaClient(default_model="qwen3:14b")
  +    client._session = _mock_session(_mock_response(_success_data(model="qwen3:14b")))
  +
  +    await client.generate("test")
  +
  +    payload = client._session.post.call_args[1]["json"]
  +    assert payload["model"] == "qwen3:14b"
  ... (181 lines truncated)
  +281 -0
[full diff: rtk git diff --no-compact]

```

## Review focus

1. OllamaClient: aiohttp session lifecycle (leaks?), timeout handling
   (asyncio.timeout + TimeoutError), all error paths correct?
2. Async correctness: blocking calls on event loop? Session management?
3. AuditLogger: silent fail on write — acceptable? Edge cases?
4. ContextBuilder skeleton: interface clean for Cycle 2 wiring?
5. Test coverage gaps?
6. EventBus duplicate subscribe warning — correct?

## Output

Verdict: PASS / CONDITIONAL / FAIL
Findings: Severity, file:line, description, fix. Under 2000 words.
