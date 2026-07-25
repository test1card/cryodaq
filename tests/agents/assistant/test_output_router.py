from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import cryodaq.agents.assistant_main as assistant_main
from cryodaq.agents.assistant.live.agent import AssistantConfig, AssistantLiveAgent
from cryodaq.agents.assistant.live.output_router import OutputRouter, OutputTarget
from cryodaq.agents.assistant.query.chart_dispatcher import ChartDispatcher
from cryodaq.agents.assistant.shared.audit import AuditLogger
from cryodaq.agents.assistant_main import TelegramSender


class _Event:
    event_type = "assistant_test"
    experiment_id = "exp-1"


@pytest.mark.asyncio
async def test_http_failure_is_not_reported_as_dispatched() -> None:
    telegram = TelegramSender("token", [101])
    telegram._send = AsyncMock(return_value="failed")
    router = OutputRouter(telegram_bot=telegram, event_bus=AsyncMock())

    outcomes = await router.dispatch_detailed(
        _Event(),
        "response",
        targets=[OutputTarget.TELEGRAM],
        audit_id="audit-1",
    )

    assert outcomes == {"telegram": "failed"}
    telegram._send.assert_awaited_once()
    chat_id, text = telegram._send.await_args.args
    assert chat_id == 101
    assert text.endswith(": response")


@pytest.mark.asyncio
async def test_audit_failure_prevents_external_egress(tmp_path, monkeypatch) -> None:
    audit = AuditLogger(tmp_path / "audit")
    monkeypatch.setattr(
        "cryodaq.agents.assistant.shared.audit._write_audit_record",
        lambda *_args: (_ for _ in ()).throw(OSError("fsync failed")),
    )
    telegram = AsyncMock()
    event_bus = AsyncMock()
    router = OutputRouter(telegram_bot=telegram, event_bus=event_bus)
    agent = AssistantLiveAgent(
        config=AssistantConfig(),
        event_bus=AsyncMock(),
        ollama_client=AsyncMock(),
        context_builder=MagicMock(),
        audit_logger=audit,
        output_router=router,
    )

    with pytest.raises(OSError, match="fsync"):
        await agent._dispatch_with_audit(
            event=SimpleNamespace(
                event_type="alarm_fired",
                experiment_id="exp-1",
            ),
            audit_id="audit-2",
            payload={"alarm_id": "alarm-1"},
            context_assembled="",
            prompt_template="",
            model="",
            system_prompt="",
            user_prompt="",
            response="",
            tokens={},
            latency_s=0.0,
            errors=[],
            targets=[OutputTarget.TELEGRAM, OutputTarget.GUI_INSIGHT],
        )
    telegram._send_to_all.assert_not_awaited()
    event_bus.publish.assert_not_awaited()
    await audit.close()


@pytest.mark.asyncio
async def test_production_sender_retains_per_destination_terminal_outcomes() -> None:
    sender = TelegramSender("token", [101, 202, 303])
    sender._send = AsyncMock(
        side_effect=["delivered", "failed", "outcome_unknown"],
    )
    router = OutputRouter(telegram_bot=sender, event_bus=AsyncMock())

    outcomes = await router.dispatch_detailed(
        _Event(),
        "message",
        targets=[OutputTarget.TELEGRAM],
        audit_id="audit-destinations",
    )

    assert outcomes == {
        "telegram": {
            "101": "delivered",
            "202": "failed",
            "303": "outcome_unknown",
        }
    }


@pytest.mark.asyncio
async def test_untrusted_telegram_text_is_escaped_before_markup() -> None:
    telegram = AsyncMock()
    telegram._send_to_all = AsyncMock(return_value={101: "delivered"})
    router = OutputRouter(
        telegram_bot=telegram,
        event_bus=AsyncMock(),
        brand_name="Assistant",
        brand_emoji="",
    )

    await router.dispatch_detailed(
        _Event(),
        "<a href='https://attacker.invalid'>click</a> **reviewed** & raw",
        targets=[OutputTarget.TELEGRAM],
        audit_id="audit-markup",
    )

    sent = telegram._send_to_all.await_args.args[0]
    assert "<a " not in sent
    assert "&lt;a href='https://attacker.invalid'&gt;" in sent
    assert "<b>reviewed</b>" in sent
    assert "&amp; raw" in sent


@pytest.mark.asyncio
async def test_shutdown_settles_audit_chart_and_message_owners(tmp_path, monkeypatch) -> None:
    import threading

    audit_entered = threading.Event()
    audit_release = threading.Event()
    chart_entered = asyncio.Event()
    chart_release = asyncio.Event()
    message_close_entered = asyncio.Event()
    message_close_release = asyncio.Event()

    def blocked_audit_write(*_args) -> None:
        audit_entered.set()
        assert audit_release.wait(3.0)

    monkeypatch.setattr(
        "cryodaq.agents.assistant.shared.audit._write_audit_record",
        blocked_audit_write,
    )
    monkeypatch.setattr(
        "cryodaq.agents.assistant.query.chart_dispatcher.render_temperature_chart",
        lambda *_args, **_kwargs: b"png",
    )

    async def send_photo(_chat_id, _photo) -> None:
        chart_entered.set()
        await chart_release.wait()

    async def close_message() -> None:
        message_close_entered.set()
        await message_close_release.wait()

    charts = ChartDispatcher(send_photo)
    charts.dispatch(
        __import__("cryodaq.agents.assistant.query.schemas", fromlist=["QueryCategory"]).QueryCategory.RANGE_STATS,
        {"range_stats": {"T1": type("Stats", (), {"mean_value": 1.0})()}},
        "chat",
    )
    audit = AuditLogger(tmp_path / "audit")
    audit_task = asyncio.create_task(
        audit.log(
            audit_id="live-owner",
            trigger_event={"kind": "test"},
            context_assembled="context",
            prompt_template="template",
            model="model",
            system_prompt="system",
            user_prompt="user",
            response="response",
            tokens={"input": 1, "output": 1},
            latency_s=0.0,
            outputs_dispatched=[],
            errors=[],
        )
    )
    assert await asyncio.to_thread(audit_entered.wait, 1.0)
    await asyncio.wait_for(chart_entered.wait(), 1.0)

    message = MagicMock()
    message.close = AsyncMock(side_effect=close_message)
    router = OutputRouter(telegram_bot=message, event_bus=AsyncMock())

    async def shutdown() -> None:
        await asyncio.gather(charts.close(), audit.close(), router.close())

    shutdown_task = asyncio.create_task(shutdown())
    try:
        await asyncio.wait_for(message_close_entered.wait(), 1.0)
        assert shutdown_task.done() is False
        assert charts._tasks
        assert audit._owned_tasks

        chart_release.set()
        message_close_release.set()
        audit_release.set()
        await asyncio.wait_for(shutdown_task, 1.0)
        await asyncio.wait_for(audit_task, 1.0)

        assert not charts._tasks
        assert not audit._owned_tasks
        message.close.assert_awaited_once()
    finally:
        chart_release.set()
        message_close_release.set()
        audit_release.set()
        await asyncio.gather(audit_task, shutdown_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_production_shutdown_calls_and_joins_audit_chart_and_router_owners(
    tmp_path,
    monkeypatch,
) -> None:
    class StartStop:
        def __init__(self, *_args, **_kwargs) -> None:
            self.start = AsyncMock()
            self.stop = AsyncMock()

    config = AssistantConfig(
        enabled=True,
        ollama_base_url="http://127.0.0.1:11434",
        query_enabled=True,
        periodic_report_enabled=False,
    )
    monkeypatch.setattr(
        assistant_main.AssistantConfig,
        "from_yaml_path",
        classmethod(lambda _cls, _path: config),
    )
    assert (assistant_main._CONFIG_DIR / "agent.yaml").exists()

    engine_client = MagicMock()
    ollama = MagicMock()
    ollama.close = AsyncMock()
    telegram = MagicMock()
    telegram.send_photo = AsyncMock()
    telegram.close = AsyncMock()
    owners: dict[str, object] = {}
    joined: set[str] = set()

    def make_audit(*_args, **_kwargs):
        owner = AuditLogger(tmp_path / "audit")
        original = owner.close

        async def close() -> None:
            await asyncio.sleep(0)
            await original()
            joined.add("audit")

        owner.close = AsyncMock(side_effect=close)
        owners["audit"] = owner
        return owner

    def make_router(**kwargs):
        owner = OutputRouter(**kwargs)
        original = owner.close

        async def close() -> None:
            await asyncio.sleep(0)
            await original()
            joined.add("router")

        owner.close = AsyncMock(side_effect=close)
        owners["router"] = owner
        return owner

    def make_chart(*args, **kwargs):
        owner = ChartDispatcher(*args, **kwargs)
        original = owner.close

        async def close() -> None:
            await asyncio.sleep(0)
            await original()
            joined.add("chart")

        owner.close = AsyncMock(side_effect=close)
        owners["chart"] = owner
        return owner

    state = StartStop()
    state.active_experiment_id = None
    state.get_summary = MagicMock(return_value=None)
    live = StartStop()

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
    monkeypatch.setattr(assistant_main, "AuditLogger", make_audit)
    monkeypatch.setattr(assistant_main, "OutputRouter", make_router)
    monkeypatch.setattr(assistant_main, "ChartDispatcher", make_chart)
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
    monkeypatch.setattr(
        assistant_main,
        "_load_telegram_sender",
        lambda: telegram,
    )
    monkeypatch.setattr(assistant_main, "_resolve_rag_config", lambda: None)
    monkeypatch.setattr(assistant_main, "ZMQEventSubscriber", StartStop)
    monkeypatch.setattr(assistant_main, "ZMQCommandServer", StartStop)
    monkeypatch.setattr(assistant_main, "BrokerSnapshot", StartStop)
    monkeypatch.setattr(assistant_main, "ChannelManager", MagicMock)
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
    for name in (
        "CooldownAdapter",
        "VacuumAdapter",
        "SQLiteAdapter",
        "AlarmAdapter",
        "ExperimentAdapter",
        "ArchiveAdapter",
        "RAGAdapter",
        "CompositeAdapter",
    ):
        monkeypatch.setattr(
            assistant_main,
            name,
            lambda *_args, **_kwargs: MagicMock(),
        )

    async def parked_tick(*_args, **_kwargs) -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(
        assistant_main,
        "_periodic_report_tick",
        parked_tick,
    )
    shutdown = asyncio.Event()
    shutdown.set()

    await assistant_main._run_llm_runtime(
        engine_cmd_addr="tcp://127.0.0.1:1",
        engine_pub_addr="tcp://127.0.0.1:2",
        assistant_cmd_addr="tcp://127.0.0.1:3",
        shutdown_event=shutdown,
    )

    owners["audit"].close.assert_awaited_once()
    owners["router"].close.assert_awaited_once()
    owners["chart"].close.assert_awaited_once()
    assert joined == {"audit", "router", "chart"}
    assert not owners["chart"]._tasks
