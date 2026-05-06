"""F34 — engine ``assistant.query`` command dispatch helper.

The full ``_handle_gui_command`` lives as a closure inside ``_run_engine``,
so the spec's required tests target the extracted module-level helper
:func:`_handle_assistant_query_command` directly. The closure simply
delegates to this helper, so anything proved here also covers the
shipped command path.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from cryodaq.engine import _handle_assistant_query_command


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


def test_returns_response_when_agent_available():
    agent = AsyncMock()
    agent.handle_query.return_value = "Т12 показывает 4.5 K, охлаждение стабильно."

    result = _run(
        _handle_assistant_query_command(
            agent,
            {"query": "какая температура?", "chat_id": "gui"},
            timeout_s=5.0,
        )
    )

    assert result == {"ok": True, "response": "Т12 показывает 4.5 K, охлаждение стабильно."}
    agent.handle_query.assert_awaited_once_with("какая температура?", chat_id="gui")


def test_default_chat_id_is_gui():
    agent = AsyncMock()
    agent.handle_query.return_value = "ok"

    _run(_handle_assistant_query_command(agent, {"query": "test"}, timeout_s=5.0))

    agent.handle_query.assert_awaited_once_with("test", chat_id="gui")


def test_returns_error_when_agent_none():
    result = _run(
        _handle_assistant_query_command(
            None,
            {"query": "что у нас", "chat_id": "gui"},
            timeout_s=5.0,
        )
    )

    assert result["ok"] is False
    assert "не сконфигурирован" in result["error"]
    assert "query_enabled" in result["error"]


def test_returns_error_on_empty_query():
    agent = AsyncMock()
    result = _run(
        _handle_assistant_query_command(agent, {"query": "   ", "chat_id": "gui"}, timeout_s=5.0)
    )

    assert result == {"ok": False, "error": "Пустой запрос."}
    agent.handle_query.assert_not_called()


def test_returns_error_on_missing_query_key():
    agent = AsyncMock()
    result = _run(_handle_assistant_query_command(agent, {"chat_id": "gui"}, timeout_s=5.0))
    assert result == {"ok": False, "error": "Пустой запрос."}
    agent.handle_query.assert_not_called()


def test_returns_timeout_error():
    async def slow_handle_query(query, *, chat_id):
        await asyncio.sleep(10.0)  # exceeds the 0.05 s timeout below
        return "never"

    agent = AsyncMock()
    agent.handle_query.side_effect = slow_handle_query

    result = _run(
        _handle_assistant_query_command(
            agent,
            {"query": "какая температура?", "chat_id": "gui"},
            timeout_s=0.05,
        )
    )

    assert result["ok"] is False
    assert "слишком долго" in result["error"]


def test_returns_error_on_handler_exception():
    agent = AsyncMock()
    agent.handle_query.side_effect = RuntimeError("Ollama недоступна")

    result = _run(
        _handle_assistant_query_command(
            agent,
            {"query": "какая температура?", "chat_id": "gui"},
            timeout_s=5.0,
        )
    )

    assert result["ok"] is False
    assert "Ollama недоступна" in result["error"]


def test_default_timeout_is_60s():
    """Default timeout_s argument is 60.0 (matches F-TimeoutRelax convention)."""
    import inspect

    sig = inspect.signature(_handle_assistant_query_command)
    assert sig.parameters["timeout_s"].default == 60.0


@pytest.mark.parametrize("chat_id", ["gui", "telegram", 12345, None])
def test_chat_id_propagated(chat_id):
    agent = AsyncMock()
    agent.handle_query.return_value = "ok"

    cmd = {"query": "проверь алармы"}
    if chat_id is not None:
        cmd["chat_id"] = chat_id

    _run(_handle_assistant_query_command(agent, cmd, timeout_s=5.0))

    expected = chat_id if chat_id is not None else "gui"
    agent.handle_query.assert_awaited_once_with("проверь алармы", chat_id=expected)
