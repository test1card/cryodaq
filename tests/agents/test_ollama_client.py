"""Tests for OllamaClient — mock HTTP + smoke test."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cryodaq.agents.ollama_client import (
    GenerationResult,
    OllamaClient,
    OllamaModelMissingError,
    OllamaUnavailableError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(data: dict) -> MagicMock:
    """Build a mock aiohttp async context manager returning data."""
    resp = AsyncMock()
    resp.json = AsyncMock(return_value=data)
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _mock_session(response_cm) -> MagicMock:
    s = AsyncMock()
    s.closed = False
    s.post = MagicMock(return_value=response_cm)
    return s


def _success_data(
    text: str = "Гемма: всё в норме.",
    tokens_in: int = 100,
    tokens_out: int = 30,
    model: str = "gemma3:e4b",
) -> dict:
    return {
        "model": model,
        "response": text,
        "prompt_eval_count": tokens_in,
        "eval_count": tokens_out,
        "done": True,
    }


# ---------------------------------------------------------------------------
# GenerationResult dataclass
# ---------------------------------------------------------------------------


def test_generation_result_fields() -> None:
    r = GenerationResult(
        text="response", tokens_in=10, tokens_out=5, latency_s=1.2, model="gemma3:e4b"
    )
    assert r.text == "response"
    assert r.tokens_in == 10
    assert r.tokens_out == 5
    assert r.latency_s == 1.2
    assert r.model == "gemma3:e4b"
    assert r.truncated is False


def test_generation_result_truncated_default_false() -> None:
    r = GenerationResult(text="", tokens_in=0, tokens_out=0, latency_s=0.1, model="m")
    assert r.truncated is False


# ---------------------------------------------------------------------------
# Successful generation
# ---------------------------------------------------------------------------


async def test_generate_returns_text_and_counts() -> None:
    client = OllamaClient(default_model="gemma3:e4b")
    client._session = _mock_session(_mock_response(_success_data()))

    result = await client.generate("Summarize alarm")

    assert result.text == "Гемма: всё в норме."
    assert result.tokens_in == 100
    assert result.tokens_out == 30
    assert result.model == "gemma3:e4b"
    assert not result.truncated


async def test_generate_uses_default_model() -> None:
    client = OllamaClient(default_model="qwen3:14b")
    client._session = _mock_session(_mock_response(_success_data(model="qwen3:14b")))

    await client.generate("test")

    payload = client._session.post.call_args[1]["json"]
    assert payload["model"] == "qwen3:14b"


async def test_generate_overrides_model() -> None:
    client = OllamaClient(default_model="gemma3:e4b")
    client._session = _mock_session(_mock_response(_success_data(model="qwen3:14b")))

    await client.generate("test", model="qwen3:14b")

    payload = client._session.post.call_args[1]["json"]
    assert payload["model"] == "qwen3:14b"


async def test_generate_includes_system_prompt() -> None:
    client = OllamaClient()
    client._session = _mock_session(_mock_response(_success_data()))

    await client.generate("prompt", system="Ты — Гемма.")

    payload = client._session.post.call_args[1]["json"]
    assert payload["system"] == "Ты — Гемма."


async def test_generate_omits_system_when_none() -> None:
    client = OllamaClient()
    client._session = _mock_session(_mock_response(_success_data()))

    await client.generate("prompt")

    payload = client._session.post.call_args[1]["json"]
    assert "system" not in payload


async def test_generate_passes_options() -> None:
    client = OllamaClient()
    client._session = _mock_session(_mock_response(_success_data()))

    await client.generate("p", max_tokens=512, temperature=0.1)

    options = client._session.post.call_args[1]["json"]["options"]
    assert options["num_predict"] == 512
    assert options["temperature"] == 0.1


async def test_generate_stream_false() -> None:
    client = OllamaClient()
    client._session = _mock_session(_mock_response(_success_data()))

    await client.generate("p")

    assert client._session.post.call_args[1]["json"]["stream"] is False


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


async def test_generate_raises_unavailable_on_connector_error() -> None:
    import aiohttp

    client = OllamaClient()
    mock_session = AsyncMock()
    mock_session.closed = False
    mock_session.post = MagicMock(
        side_effect=aiohttp.ClientError("connection refused")
    )
    client._session = mock_session

    with pytest.raises(OllamaUnavailableError):
        await client.generate("test")


async def test_generate_raises_model_missing_on_not_found_error() -> None:
    client = OllamaClient(default_model="no-such-model:latest")
    err_data = {"error": "model 'no-such-model:latest' not found, try pulling it first"}
    client._session = _mock_session(_mock_response(err_data))

    with pytest.raises(OllamaModelMissingError) as exc_info:
        await client.generate("test")

    assert "no-such-model:latest" in str(exc_info.value)
    assert "ollama pull" in str(exc_info.value)


async def test_generate_model_missing_error_has_model_attr() -> None:
    exc = OllamaModelMissingError("gemma3:e4b")
    assert exc.model == "gemma3:e4b"
    assert "ollama pull" in str(exc)


async def test_generate_raises_unavailable_on_generic_error_response() -> None:
    client = OllamaClient()
    client._session = _mock_session(_mock_response({"error": "internal server error"}))

    with pytest.raises(OllamaUnavailableError, match="internal server error"):
        await client.generate("test")


async def test_generate_returns_truncated_on_timeout() -> None:
    client = OllamaClient(timeout_s=30.0)
    client._session = _mock_session(_mock_response(_success_data()))  # prevent real session

    timeout_cm = AsyncMock()
    timeout_cm.__aenter__ = AsyncMock(side_effect=TimeoutError())
    timeout_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("cryodaq.agents.ollama_client.asyncio.timeout", return_value=timeout_cm):
        result = await client.generate("test")

    assert result.truncated is True
    assert result.text == ""
    assert result.tokens_in == 0
    assert result.tokens_out == 0


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------


async def test_close_clears_session() -> None:
    client = OllamaClient()
    mock_session = AsyncMock()
    mock_session.closed = False
    client._session = mock_session

    await client.close()

    mock_session.close.assert_awaited_once()
    assert client._session is None


async def test_close_noop_when_no_session() -> None:
    client = OllamaClient()
    await client.close()  # should not raise


# ---------------------------------------------------------------------------
# Smoke test — requires running Ollama + gemma4:4b (or configured model)
# ---------------------------------------------------------------------------


@pytest.mark.smoke
async def test_smoke_real_ollama() -> None:
    """Real Ollama inference — requires: ollama serve + model pulled.

    Run with: pytest -m smoke tests/agents/test_ollama_client.py -v
    """
    import subprocess

    try:
        result_ls = subprocess.run(  # noqa: ASYNC221
            ["ollama", "list"], capture_output=True, text=True, timeout=5
        )
        available = result_ls.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pytest.skip("ollama not installed or not responding")

    if "gemma4:e4b" in available:
        model = "gemma4:e4b"
    elif "gemma4" in available:
        model = "gemma4:26b"
    elif "qwen3:14b" in available:
        model = "qwen3:14b"
    else:
        pytest.skip("No known model available in ollama list")

    client = OllamaClient(
        base_url="http://localhost:11434",
        default_model=model,
        timeout_s=120.0,
    )
    try:
        result = await client.generate(
            "Reply with exactly the word: PASS",
            system="You are a test assistant. Reply with only the exact word requested.",
            max_tokens=10,
            temperature=0.0,
        )
        assert not result.truncated, f"Timed out. model={model}"
        assert result.tokens_out > 0, f"No tokens generated. model={model}"
        assert len(result.text.strip()) > 0, f"Empty response. model={model}"
    finally:
        await client.close()
