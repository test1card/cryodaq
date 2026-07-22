"""Live assistant RAG capability boundary."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import cryodaq.agents.assistant_main as assistant_main
from cryodaq.agents.assistant.live.agent import AssistantConfig


@pytest.mark.asyncio
async def test_live_runtime_has_no_rag_rebuild_capability(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]] = {}

    class _StartStop:
        def __init__(self, *_args, **_kwargs) -> None:
            self.start = AsyncMock()
            self.stop = AsyncMock()

    class _CommandServer(_StartStop):
        def __init__(self, *, handler, **_kwargs) -> None:
            super().__init__()
            captured["handler"] = handler

    config = AssistantConfig(
        enabled=True,
        ollama_base_url="http://127.0.0.1:11434",
        query_enabled=False,
        periodic_report_enabled=False,
    )
    monkeypatch.setattr(
        assistant_main.AssistantConfig,
        "from_yaml_path",
        classmethod(lambda _cls, _path: config),
    )
    assert (assistant_main._CONFIG_DIR / "agent.yaml").exists()

    engine_client = MagicMock()
    ollama = MagicMock(close=AsyncMock())
    telegram = MagicMock(close=AsyncMock())
    state = _StartStop()
    state.active_experiment_id = None
    state.get_summary = MagicMock(return_value=None)
    live = _StartStop()
    output_router = MagicMock(close=AsyncMock())
    audit_logger = MagicMock(close=AsyncMock())
    build_index = AsyncMock(return_value={"indexed": 1})

    monkeypatch.setattr(
        assistant_main,
        "EngineQueryClient",
        lambda *_args, **_kwargs: engine_client,
    )
    monkeypatch.setattr(
        assistant_main,
        "OllamaClient",
        lambda *_args, **_kwargs: ollama,
    )
    monkeypatch.setattr(
        assistant_main,
        "EngineContextReader",
        lambda *_args, **_kwargs: MagicMock(),
    )
    monkeypatch.setattr(
        assistant_main,
        "ContextBuilder",
        lambda *_args, **_kwargs: MagicMock(),
    )
    monkeypatch.setattr(
        assistant_main,
        "AuditLogger",
        lambda *_args, **_kwargs: audit_logger,
    )
    monkeypatch.setattr(
        assistant_main,
        "OutputRouter",
        lambda **_kwargs: output_router,
    )
    monkeypatch.setattr(
        assistant_main,
        "AssistantLiveAgent",
        lambda **_kwargs: live,
    )
    monkeypatch.setattr(
        assistant_main,
        "_RemoteEngineStateCache",
        lambda *_args, **_kwargs: state,
    )
    monkeypatch.setattr(assistant_main, "_load_telegram_sender", lambda: telegram)
    monkeypatch.setattr(assistant_main, "_resolve_rag_config", lambda: None)
    monkeypatch.setattr(assistant_main, "ZMQEventSubscriber", _StartStop)
    monkeypatch.setattr(assistant_main, "ZMQCommandServer", _CommandServer)
    monkeypatch.setattr("cryodaq.agents.rag.indexer.build_index", build_index)

    async def _parked_tick(*_args, **_kwargs) -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(assistant_main, "_periodic_report_tick", _parked_tick)
    shutdown = asyncio.Event()
    shutdown.set()
    await assistant_main._run_llm_runtime(
        engine_cmd_addr="tcp://127.0.0.1:1",
        engine_pub_addr="tcp://127.0.0.1:2",
        assistant_cmd_addr="tcp://127.0.0.1:3",
        shutdown_event=shutdown,
    )

    handler = captured["handler"]
    forbidden_target = tmp_path / "live-index-must-not-exist"
    for action in ("rag.rebuild_index", "rag.rebuild_status"):
        reply = await handler({"cmd": action, "target": str(forbidden_target)})
        assert reply == {"ok": False, "error": f"unknown command: {action}"}
    build_index.assert_not_awaited()
    assert not forbidden_target.exists()
