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


def test_default_timeout_fires_inside_server_envelope():
    """Default timeout_s must fire BEFORE the server's ``HANDLER_TIMEOUT_SLOW_S``
    envelope (30 s) so the helper's own Russian error wins over the generic
    ``handler timeout`` reply from the REP server. Cycle-3 fix for Codex
    finding on commit 0ab42f2."""
    import inspect

    from cryodaq.core.zmq_bridge import HANDLER_TIMEOUT_SLOW_S

    sig = inspect.signature(_handle_assistant_query_command)
    default = sig.parameters["timeout_s"].default
    assert default == 25.0
    assert default < HANDLER_TIMEOUT_SLOW_S, (
        f"helper timeout {default}s must be < server slow envelope "
        f"{HANDLER_TIMEOUT_SLOW_S}s"
    )


def test_assistant_query_routed_to_slow_envelope_at_transport_layer():
    """Cycle-3 fix: ``assistant.query`` is registered as a slow command so
    the REP server gives the handler the 30 s envelope instead of the 2 s
    fast default. Without this registration the helper's 25 s wait_for
    is masked by the server returning ``handler timeout (2s)`` first."""
    from cryodaq.core.zmq_bridge import (
        _SLOW_COMMANDS,
        HANDLER_TIMEOUT_FAST_S,
        HANDLER_TIMEOUT_SLOW_S,
        _timeout_for,
    )

    assert "assistant.query" in _SLOW_COMMANDS
    assert _timeout_for({"cmd": "assistant.query"}) == HANDLER_TIMEOUT_SLOW_S
    # Sanity: an unknown command stays on the fast envelope.
    assert _timeout_for({"cmd": "totally_unknown"}) == HANDLER_TIMEOUT_FAST_S


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
