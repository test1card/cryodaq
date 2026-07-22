"""Optional Гемма/RAG runtime loaded by the lightweight assistant bootstrap.

B1 (roadmap: extract Гемма + RAG out of the safety-critical engine
process). This module is the *only* place agents/ code runs now — the
engine process no longer imports it (see ``scratchpad/montana/exec/impl_b1.md``
for the full coupling map and design).

This process talks to the engine over the same trust-bounded ZMQ sockets
the GUI already uses:

- SUBSCRIBES to the engine's PUB feed (``tcp://127.0.0.1:5555``): the
  existing ``readings`` topic (live channel values, for
  ``BrokerSnapshot``) and the new additive ``events`` topic (EngineEvent
  notifications alarm_fired/experiment_finalize/... for
  ``AssistantLiveAgent`` — see ``core/zmq_bridge.py``).
- CALLS the engine's existing read-only REP commands
  (``tcp://127.0.0.1:5556``) for on-demand state — the exact same
  commands the GUI uses to render its panels (``experiment_status``,
  ``alarm_v2_status``, ``get_vacuum_trend``, ``cooldown_eta_get``,
  ``readings_history``, ``get_sensor_diagnostics``,
  ``experiment_archive_list``, ``experiment_get_archive_item``,
  ``alarm_v2_history``).
- HOSTS its OWN REP socket (``tcp://127.0.0.1:5557``, loopback-only,
  same trust model as the engine's :5556 — see ``core/zmq_bridge.py``
  module docstring) serving ``assistant.query`` and read-only ``rag.search``.

Read-only by construction: this process never sends a write/control
command to the engine — only the query actions above, and it never
authenticates or is granted one; there is no code path here that could
send e.g. ``keithley_stop`` or ``experiment_abort``. That is what
satisfies the text-only/no-commands constraint for B1 — the process
boundary plus the shape of what this process is allowed to ask for is
the enforcement mechanism, not a runtime permission check.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import types
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from cryodaq.agents.assistant.live.agent import AssistantConfig, AssistantLiveAgent
from cryodaq.agents.assistant.live.context_builder import ContextBuilder
from cryodaq.agents.assistant.live.output_router import OutputRouter
from cryodaq.agents.assistant.query.adapters.alarm_adapter import AlarmAdapter
from cryodaq.agents.assistant.query.adapters.archive_adapter import ArchiveAdapter
from cryodaq.agents.assistant.query.adapters.broker_snapshot import BrokerSnapshot
from cryodaq.agents.assistant.query.adapters.composite_adapter import CompositeAdapter
from cryodaq.agents.assistant.query.adapters.cooldown_adapter import CooldownAdapter
from cryodaq.agents.assistant.query.adapters.experiment_adapter import ExperimentAdapter
from cryodaq.agents.assistant.query.adapters.rag_adapter import RAGAdapter
from cryodaq.agents.assistant.query.adapters.sqlite_adapter import SQLiteAdapter
from cryodaq.agents.assistant.query.adapters.vacuum_adapter import VacuumAdapter
from cryodaq.agents.assistant.query.agent import AssistantQueryAgent
from cryodaq.agents.assistant.query.chart_dispatcher import ChartDispatcher
from cryodaq.agents.assistant.query.schemas import QueryAdapters
from cryodaq.agents.assistant.shared.audit import AuditLogger
from cryodaq.agents.assistant.shared.context_reader import EngineContextReader, _validate_context_receipt
from cryodaq.agents.assistant.shared.engine_client import (
    DEFAULT_ENGINE_CMD_ADDR,
    EngineQueryClient,
)
from cryodaq.agents.assistant.shared.ollama_client import OllamaClient, validate_loopback_origin
from cryodaq.core.channel_manager import ChannelManager
from cryodaq.core.event_bus import EngineEvent, EventBus
from cryodaq.core.zmq_bridge import (
    DEFAULT_PUB_ADDR,
    ZMQCommandServer,
    ZMQEventSubscriber,
)
from cryodaq.paths import get_config_dir, get_data_dir

logger = logging.getLogger("cryodaq.assistant")

_CONFIG_DIR = get_config_dir()
_DATA_DIR = get_data_dir()

DEFAULT_ASSISTANT_CMD_ADDR = "tcp://127.0.0.1:5557"

# Same relay set the engine forwards on the "events" topic
# (engine.py's _ASSISTANT_RELAY_EVENT_TYPES) — kept here only as an
# assertion aid for tests; AssistantLiveAgent itself filters via
# _should_handle so this module doesn't need to filter again.


def _cfg(name: str) -> Path:
    return _CONFIG_DIR / f"{name}.yaml"


# ---------------------------------------------------------------------------
# Duck-typed shims — let ContextBuilder / EventLogger / adapters run
# unmodified against a remote engine instead of an in-process object.
# ---------------------------------------------------------------------------


class _RemoteEngineStateCache:
    """Background-refreshed cache of engine state for the synchronous
    ``ExperimentManager``-shaped / ``sensor_diag_provider``-shaped duck
    types that :class:`ContextBuilder` and :class:`EventLogger` expect.

    ``ContextBuilder`` calls ``experiment_manager.active_experiment_id``
    / ``.get_current_phase()`` / ``.get_phase_history()`` *synchronously*
    (no ``await``) — the same "poll periodically, cache, read
    synchronously" pattern already used by ``CooldownService`` /
    ``VacuumTrendPredictor`` elsewhere in this codebase, applied here
    because a synchronous method can't make a ZMQ round-trip itself.
    """

    def __init__(self, client: EngineQueryClient, *, poll_interval_s: float = 3.0) -> None:
        self._client = client
        self._poll_interval_s = poll_interval_s
        self._experiment_status: dict[str, Any] = {}
        self._experiment_receipt: dict[str, Any] | None = None
        self._sensor_diagnostics: dict[str, Any] | None = None
        self._sensor_receipt: dict[str, Any] | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._poll_loop(), name="assistant_state_cache")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _poll_loop(self) -> None:
        while True:
            try:
                exp_reply = await self._client.call({"cmd": "experiment_status"})
                active = (exp_reply.get("active_experiment") or {}).get("experiment_id")
                experiment_receipt_valid = False
                if exp_reply.get("ok") and isinstance(active, str) and active:
                    try:
                        _validate_context_receipt(
                            exp_reply.get("scope_receipt"),
                            expected_scope="experiment_status",
                            expected_experiment_id=active,
                            query_start=None,
                            query_end=None,
                        )
                    except Exception:
                        self._experiment_status = {}
                        self._experiment_receipt = None
                        self._sensor_diagnostics = None
                        self._sensor_receipt = None
                    else:
                        experiment_receipt_valid = True
                        self._experiment_status = exp_reply
                        self._experiment_receipt = exp_reply.get("scope_receipt")
                else:
                    self._experiment_status = {}
                    self._experiment_receipt = None
                    self._sensor_diagnostics = None
                    self._sensor_receipt = None
                diag_reply = await self._client.call({"cmd": "get_sensor_diagnostics"})
                if experiment_receipt_valid and diag_reply.get("ok") and isinstance(active, str) and active:
                    _validate_context_receipt(
                        diag_reply.get("scope_receipt"),
                        expected_scope="sensor_diagnostics",
                        expected_experiment_id=active,
                        query_start=None,
                        query_end=None,
                    )
                    self._sensor_diagnostics = diag_reply.get("summary")
                    self._sensor_receipt = diag_reply.get("scope_receipt")
                else:
                    self._sensor_diagnostics = None
                    self._sensor_receipt = None
            except Exception:
                self._experiment_status = {}
                self._experiment_receipt = None
                self._sensor_diagnostics = None
                self._sensor_receipt = None
                logger.debug("assistant state cache poll failed", exc_info=True)
            await asyncio.sleep(self._poll_interval_s)

    def _invalidate(self) -> None:
        self._experiment_status = {}
        self._experiment_receipt = None
        self._sensor_diagnostics = None
        self._sensor_receipt = None

    def _experiment_is_current(self) -> bool:
        active = self._experiment_status.get("active_experiment") or {}
        experiment_id = active.get("experiment_id")
        if not isinstance(experiment_id, str) or not experiment_id:
            self._invalidate()
            return False
        try:
            _validate_context_receipt(
                self._experiment_receipt,
                expected_scope="experiment_status",
                expected_experiment_id=experiment_id,
                query_start=None,
                query_end=None,
            )
        except Exception:
            self._invalidate()
            return False
        return True

    # --- ExperimentManager-shaped duck type (sync, per module docstring) ---
    @property
    def active_experiment_id(self) -> str | None:
        if not self._experiment_is_current():
            return None
        active = self._experiment_status.get("active_experiment")
        return active.get("experiment_id") if active else None

    def get_current_phase(self) -> str | None:
        if not self._experiment_is_current():
            return None
        return self._experiment_status.get("current_phase")

    def get_phase_history(self) -> list[dict]:
        if not self._experiment_is_current():
            return []
        return self._experiment_status.get("phases", [])

    # --- sensor_diag_provider callable (sync, zero-arg) ---
    def get_summary(self) -> Any | None:
        if self._sensor_diagnostics is None or not self._experiment_is_current():
            return None
        try:
            _validate_context_receipt(
                self._sensor_receipt,
                expected_scope="sensor_diagnostics",
                expected_experiment_id=self._experiment_status["active_experiment"]["experiment_id"],
                query_start=None,
                query_end=None,
            )
        except Exception:
            self._invalidate()
            return None
        return types.SimpleNamespace(**self._sensor_diagnostics)


class TelegramSender:
    """Outbound-only Telegram client: ``_send_to_all`` + ``send_photo``.

    B1: ``TelegramCommandBot`` (notifications/telegram_commands.py, engine
    process) also polls ``getUpdates`` and dispatches arbitrary engine
    commands (``/phase``, keithley control, ...) — that write-capable
    surface stays in the engine, unrelated to Гемма. This class is just
    the send half, extracted so the assistant process can push Гемма's
    narratives / RAG chart images to Telegram without needing a write
    path back into the engine: it talks to the Telegram Bot API directly
    over the internet using the same bot token from config, and has no
    connection to the engine at all.
    """

    def __init__(
        self,
        bot_token: str,
        allowed_chat_ids: list[int],
        *,
        verify_ssl: bool = True,
    ) -> None:
        self._bot_token = bot_token
        self._allowed_ids = list(allowed_chat_ids)
        self._verify_ssl = verify_ssl
        self._session: Any | None = None

    @property
    def _api(self) -> str:
        return f"https://api.telegram.org/bot{self._bot_token}"

    async def _get_session(self):
        import aiohttp  # noqa: PLC0415

        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ssl=self._verify_ssl)
            self._session = aiohttp.ClientSession(connector=connector)
        return self._session

    async def _send(self, chat_id: int, text: str) -> str:
        session = await self._get_session()
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        try:
            async with session.post(f"{self._api}/sendMessage", json=payload, allow_redirects=False) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error("Telegram sendMessage %d: %s", resp.status, body[:200])
                    return "failed" if not 300 <= resp.status < 400 else "outcome_unknown"
                return "delivered"
        except Exception as exc:
            logger.error("Ошибка отправки Telegram: %s", exc)
            return "outcome_unknown"

    async def _send_to_all(self, text: str) -> dict[int, str]:
        if not self._allowed_ids:
            return {}
        return {chat_id: await self._send(chat_id, text) for chat_id in self._allowed_ids}

    async def send_photo(self, chat_id: int | str, photo: bytes, caption: str = "") -> None:
        import aiohttp  # noqa: PLC0415

        try:
            session = await self._get_session()
            form = aiohttp.FormData()
            form.add_field("chat_id", str(chat_id))
            form.add_field("photo", photo, filename="chart.png", content_type="image/png")
            if caption:
                form.add_field("caption", caption)
            async with session.post(f"{self._api}/sendPhoto", data=form, allow_redirects=False) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error("Telegram sendPhoto %d: %s", resp.status, body[:200])
        except Exception as exc:
            logger.error("Ошибка отправки Telegram фото: %s", exc)

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()


def _load_telegram_sender() -> TelegramSender | None:
    """Read bot_token/allowed_chat_ids from notifications config.

    Independent parse of the same config files the engine reads —
    deliberately not shared state, so the assistant process has no
    dependency on the engine process to talk to Telegram.
    """
    notifications_cfg = _cfg("notifications")
    if not notifications_cfg.exists():
        return None
    try:
        raw = yaml.safe_load(notifications_cfg.read_text(encoding="utf-8")) or {}
        tg_cfg = raw.get("telegram", {})
        bot_token = str(tg_cfg.get("bot_token", ""))
        if not bot_token or bot_token == "YOUR_BOT_TOKEN_HERE":
            return None
        cmd_cfg = raw.get("commands", {})
        allowed_raw = tg_cfg.get("allowed_chat_ids") or cmd_cfg.get("allowed_chat_ids") or []
        allowed_ids = [int(x) for x in allowed_raw]
        if not allowed_ids:
            return None
        verify_ssl = bool(tg_cfg.get("verify_ssl", True))
        return TelegramSender(bot_token, allowed_ids, verify_ssl=verify_ssl)
    except Exception as exc:
        logger.warning("TelegramSender: config load failed — %s", exc)
        return None


def _resolve_rag_config() -> dict[str, Any] | None:
    """Resolve rag.local.yaml → rag.yaml → rag.yaml.example, same priority
    order engine.py used to apply."""
    for name in ("rag.local.yaml", "rag.yaml", "rag.yaml.example"):
        path = _CONFIG_DIR / name
        if path.exists():
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            cfg = dict(raw.get("rag", {}))
            cfg["_source"] = name
            return cfg
    return None


# ---------------------------------------------------------------------------
# assistant.query / rag.search command dispatch (this process's own REP)
# ---------------------------------------------------------------------------


async def _handle_assistant_query_command(
    query_agent: Any,
    cmd: dict[str, Any],
    *,
    timeout_s: float = 50.0,
) -> dict[str, Any]:
    query = str(cmd.get("query", "")).strip()
    chat_id = cmd.get("chat_id", "gui")
    if not query:
        return {"ok": False, "error": "Пустой запрос."}
    if query_agent is None:
        return {
            "ok": False,
            "error": "AssistantQueryAgent не сконфигурирован (query_enabled=false в agent.yaml).",
        }
    try:
        response = await asyncio.wait_for(query_agent.handle_query(query, chat_id=chat_id), timeout=timeout_s)
        if getattr(query_agent, "last_audit_error", False) is True:
            return {
                "ok": False,
                "error_code": "audit_unavailable",
                "delivery_state": "not_dispatched",
                "commit_state": "not_committed",
                "retry_safe": False,
            }
        return {"ok": True, "response": response}
    except TimeoutError:
        return {
            "ok": False,
            "error": (
                f"Запрос обрабатывался слишком долго (>{timeout_s:g}s). Попробуй ещё раз — модель уже прогрелась."
            ),
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("assistant.query error: %s", exc, exc_info=True)
        return {"ok": False, "error": str(exc)}


async def _handle_rag_search_command(
    rag_searcher: Any, cmd: dict[str, Any], *, timeout_s: float = 30.0
) -> dict[str, Any]:
    if rag_searcher is None:
        return {"ok": False, "error": "RAG индекс не построен. Запустите cryodaq-rag-index."}
    query = str(cmd.get("query", "")).strip()
    if not query:
        return {"ok": False, "error": "Пустой запрос."}
    top_k = int(cmd.get("limit", cmd.get("top_k", 10)))
    raw_filter = cmd.get("source_kind_filter")
    if raw_filter is None:
        source_kind_filter: list[str] | None = None
    elif isinstance(raw_filter, list):
        source_kind_filter = [str(x) for x in raw_filter]
    else:
        source_kind_filter = [str(raw_filter)]
    try:
        results = await asyncio.wait_for(
            rag_searcher.search(query, top_k=top_k, source_kind_filter=source_kind_filter),
            timeout=timeout_s,
        )
        return {
            "ok": True,
            "results": [
                {
                    "chunk_id": r.chunk_id,
                    "source_kind": r.source_kind,
                    "source_id": r.source_id,
                    "text": r.text,
                    "metadata": r.metadata,
                    "score": r.score,
                }
                for r in results
            ],
        }
    except TimeoutError:
        return {"ok": False, "error": f"RAG-поиск занял больше {timeout_s:g}с — возможно Ollama зависла."}
    except Exception as exc:  # noqa: BLE001
        logger.error("rag.search error: %s", exc, exc_info=True)
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Periodic report tick (moved from engine.py — pure self-trigger, needs no
# engine involvement at all; publishes onto this process's own EventBus).
# ---------------------------------------------------------------------------


async def _periodic_report_tick(
    config: AssistantConfig,
    event_bus: EventBus,
    state_cache: _RemoteEngineStateCache,
    *,
    sleep=asyncio.sleep,
) -> None:
    interval_s = float(config.get_periodic_report_interval_s())
    if interval_s <= 0:
        logger.info("Periodic assistant reports disabled (interval=0)")
        return
    window_minutes = int(config.periodic_report_interval_minutes)
    while True:
        await sleep(interval_s)
        try:
            await event_bus.publish(
                EngineEvent(
                    event_type="periodic_report_request",
                    timestamp=datetime.now(UTC),
                    payload={"window_minutes": window_minutes, "trigger": "scheduled"},
                    experiment_id=state_cache.active_experiment_id,
                )
            )
        except Exception as exc:
            logger.error("Periodic assistant report tick error: %s", exc)


# ---------------------------------------------------------------------------
# Process lifecycle
# ---------------------------------------------------------------------------


async def _run_llm_runtime(
    *,
    engine_cmd_addr: str = DEFAULT_ENGINE_CMD_ADDR,
    engine_pub_addr: str = DEFAULT_PUB_ADDR,
    assistant_cmd_addr: str = DEFAULT_ASSISTANT_CMD_ADDR,
    shutdown_event: asyncio.Event,
) -> None:
    """Build and run the optional LLM/RAG portion of the assistant."""
    engine_client = EngineQueryClient(engine_cmd_addr)
    event_bus = EventBus()

    agent_cfg_path = _CONFIG_DIR / "agent.yaml"
    if not agent_cfg_path.exists():
        logger.info("cryodaq-assistant: config/agent.yaml не найден — нечего запускать, выхожу")
        return
    config = AssistantConfig.from_yaml_path(agent_cfg_path)
    config.ollama_base_url = validate_loopback_origin(config.ollama_base_url)
    if not config.enabled:
        logger.info("cryodaq-assistant: agent.enabled=false — нечего запускать, выхожу")
        return

    # --- ZMQ: events relay engine -> local EventBus (feeds AssistantLiveAgent) ---
    async def _on_zmq_event(event: dict[str, Any]) -> None:
        await event_bus.publish(
            EngineEvent(
                event_type=str(event.get("event_type", "")),
                timestamp=datetime.fromtimestamp(float(event.get("ts", time.time())), tz=UTC),
                payload=dict(event.get("payload") or {}),
                experiment_id=event.get("experiment_id"),
            )
        )

    event_sub = ZMQEventSubscriber(engine_pub_addr, callback=_on_zmq_event)

    # --- Remote state cache (ExperimentManager / sensor diag duck types) ---
    state_cache = _RemoteEngineStateCache(engine_client)

    # --- Гемма (AssistantLiveAgent) ---
    ollama = OllamaClient(
        base_url=config.ollama_base_url,
        default_model=config.default_model,
        timeout_s=config.timeout_s,
    )
    telegram_sender: Any | None = None
    try:
        reader = EngineContextReader(engine_client)
        context_builder = ContextBuilder(reader, state_cache, sensor_diag_provider=state_cache.get_summary)
        audit_logger = AuditLogger(
            _DATA_DIR / "agents" / "assistant" / "audit",
            enabled=config.audit_enabled,
            retention_days=config.audit_retention_days,
        )
        telegram_sender = _load_telegram_sender()
        output_router = OutputRouter(
            telegram_bot=telegram_sender,
            event_bus=event_bus,
            brand_name=config.brand_name,
            brand_emoji=config.brand_emoji,
        )
        live_agent = AssistantLiveAgent(
            config=config,
            event_bus=event_bus,
            ollama_client=ollama,
            context_builder=context_builder,
            audit_logger=audit_logger,
            output_router=output_router,
        )
    except Exception:
        with contextlib.suppress(Exception):
            await ollama.close()
        if telegram_sender is not None:
            with contextlib.suppress(Exception):
                await telegram_sender.close()
        raise

    # --- RAG searcher ---
    rag_searcher: Any = None
    rag_emb_client: Any | None = None
    try:
        rag_cfg = _resolve_rag_config()
    except Exception:
        with contextlib.suppress(Exception):
            await ollama.close()
        if telegram_sender is not None:
            with contextlib.suppress(Exception):
                await telegram_sender.close()
        raise
    if rag_cfg is not None:
        try:
            from cryodaq.agents.rag.embeddings import EmbeddingsClient  # noqa: PLC0415
            from cryodaq.agents.rag.searcher import RagSearcher  # noqa: PLC0415

            rag_db_path = Path(  # noqa: ASYNC240 — .expanduser() does no I/O; one-time startup config load
                str(rag_cfg.get("db_path", "data/rag_index"))
            ).expanduser()
            rag_table = str(rag_cfg.get("table_name", "cryodaq_corpus"))
            rag_emb_url = str(rag_cfg.get("ollama_base_url", "http://localhost:11434"))
            rag_emb_model = str(rag_cfg.get("embedding_model", "qwen3-embedding:0.6b"))
            if not await asyncio.to_thread(rag_db_path.is_dir):
                raise FileNotFoundError(f"offline RAG index is absent at {rag_db_path}; run cryodaq-rag-index")
            rag_emb = EmbeddingsClient(base_url=rag_emb_url, model=rag_emb_model)
            rag_emb_client = rag_emb
            rag_searcher = RagSearcher(db_path=rag_db_path, embeddings_client=rag_emb, table_name=rag_table)
            logger.info("RAG searcher: инициализирован (config=%s, db=%s)", rag_cfg["_source"], rag_db_path)
        except Exception as exc:
            logger.warning("RAG searcher: ошибка инициализации — %s", exc)
            rag_searcher = None
    else:
        logger.info("RAG searcher: rag.local.yaml/rag.yaml/rag.yaml.example не найдены — отключён")

    # --- AssistantQueryAgent (F30 live chat) ---
    query_agent: Any = None
    broker_snapshot: BrokerSnapshot | None = None
    if config.query_enabled:
        try:
            channel_manager = ChannelManager()
            broker_snapshot = BrokerSnapshot(engine_pub_addr, channel_manager=channel_manager)

            q_cooldown = CooldownAdapter(engine_client)
            q_vacuum = VacuumAdapter(engine_client)
            q_sqlite = SQLiteAdapter(engine_client)
            q_alarms = AlarmAdapter(engine_client)
            q_experiment = ExperimentAdapter(engine_client)
            q_archive = ArchiveAdapter(
                engine_client,
                archive_root=_DATA_DIR / "experiments",
            )
            q_rag = RAGAdapter(rag_searcher)
            q_composite = CompositeAdapter(
                broker_snapshot=broker_snapshot,
                cooldown=q_cooldown,
                vacuum=q_vacuum,
                alarms=q_alarms,
                experiment=q_experiment,
            )
            chart_dispatcher: ChartDispatcher | None = None
            if telegram_sender is not None:
                chart_dispatcher = ChartDispatcher(send_photo=telegram_sender.send_photo)

            query_agent = AssistantQueryAgent(
                ollama_client=ollama,
                audit_logger=audit_logger,
                config=config,
                adapters=QueryAdapters(
                    broker_snapshot=broker_snapshot,
                    cooldown=q_cooldown,
                    vacuum=q_vacuum,
                    sqlite=q_sqlite,
                    alarms=q_alarms,
                    experiment=q_experiment,
                    composite=q_composite,
                    archive=q_archive,
                    rag=q_rag,
                ),
                intent_model=config.query_intent_model,
                format_model=config.query_format_model,
                intent_temperature=config.query_intent_temperature,
                format_temperature=config.query_format_temperature,
                intent_timeout_s=config.query_intent_timeout_s,
                format_timeout_s=config.query_format_timeout_s,
                max_queries_per_chat_per_hour=config.query_max_per_chat_per_hour,
                channel_manager=channel_manager,
                chart_dispatcher=chart_dispatcher,
            )
            logger.info("AssistantQueryAgent (F30): инициализирован")
        except Exception as exc:
            logger.warning("AssistantQueryAgent: ошибка инициализации — %s", exc, exc_info=True)

    # --- This process's own REP: assistant.query / rag.* ---
    async def _handle_assistant_command(cmd: dict[str, Any]) -> dict[str, Any]:
        action = str(cmd.get("cmd", ""))
        try:
            if action == "assistant.query":
                return await _handle_assistant_query_command(query_agent, cmd)
            if action == "rag.search":
                return await _handle_rag_search_command(rag_searcher, cmd)
            return {"ok": False, "error": f"unknown command: {action}"}
        except Exception as exc:
            logger.error("Ошибка выполнения команды ассистента '%s': %s", action, exc)
            return {"ok": False, "error": str(exc)}

    try:
        cmd_server = ZMQCommandServer(
            address=assistant_cmd_addr,
            handler=_handle_assistant_command,
            server_label="assistant",
        )
    except Exception:
        with contextlib.suppress(Exception):
            await ollama.close()
        if rag_emb_client is not None:
            with contextlib.suppress(Exception):
                await rag_emb_client.close()
        if telegram_sender is not None:
            with contextlib.suppress(Exception):
                await telegram_sender.close()
        raise

    # --- Start everything ---
    state_started = False
    event_started = False
    command_started = False
    broker_started = False
    periodic_task: asyncio.Task[None] | None = None

    async def _cleanup(label: str, operation) -> None:
        try:
            await operation()
        except Exception:
            logger.exception("Optional assistant cleanup failed: %s", label)

    try:
        if broker_snapshot is not None:
            broker_started = True
            await broker_snapshot.start()
        state_started = True
        await state_cache.start()
        event_started = True
        await event_sub.start()
        command_started = True
        await cmd_server.start()
        await live_agent.start()

        periodic_task = asyncio.create_task(
            _periodic_report_tick(config, event_bus, state_cache),
            name="assistant_periodic_report_tick",
        )
        logger.info("═══ cryodaq-assistant запущен ═══ (REP=%s)", assistant_cmd_addr)
        await shutdown_event.wait()
    finally:
        logger.info("═══ Завершение cryodaq-assistant ═══")
        if periodic_task is not None:
            periodic_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await periodic_task
        if query_agent is not None:
            await _cleanup("query agent", query_agent.close)
        await _cleanup("live agent", live_agent.stop)
        await _cleanup("output router", output_router.close)
        await _cleanup("audit logger", audit_logger.close)
        if command_started:
            await _cleanup("command server", cmd_server.stop)
        if event_started:
            await _cleanup("event subscriber", event_sub.stop)
        if state_started:
            await _cleanup("state cache", state_cache.stop)
        if broker_started and broker_snapshot is not None:
            await _cleanup("broker snapshot", broker_snapshot.stop)
        await _cleanup("Ollama client", ollama.close)
        if rag_emb_client is not None:
            await _cleanup("RAG embeddings client", rag_emb_client.close)
        if telegram_sender is not None:
            await _cleanup("Telegram sender", telegram_sender.close)
        logger.info("cryodaq-assistant остановлен")


async def run(
    *,
    engine_cmd_addr: str = DEFAULT_ENGINE_CMD_ADDR,
    engine_pub_addr: str = DEFAULT_PUB_ADDR,
    assistant_cmd_addr: str = DEFAULT_ASSISTANT_CMD_ADDR,
) -> None:
    """Compatibility wrapper; the real process entrypoint is the bootstrap."""
    from cryodaq.agents.assistant_bootstrap import run as bootstrap_run  # noqa: PLC0415

    await bootstrap_run(
        engine_cmd_addr=engine_cmd_addr,
        engine_pub_addr=engine_pub_addr,
        assistant_cmd_addr=assistant_cmd_addr,
    )


def main() -> None:
    """Compatibility wrapper for historical module invocation."""
    from cryodaq.agents.assistant_bootstrap import main as bootstrap_main  # noqa: PLC0415

    bootstrap_main()


if __name__ == "__main__":
    main()
