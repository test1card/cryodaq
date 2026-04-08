"""Интерактивный Telegram-бот: команды для удалённого мониторинга.

Опрашивает getUpdates в async-цикле и отвечает на команды:
/status, /temps, /pressure, /keithley, /alarms, /help.
Работает только с chat_id из списка allowed_chat_ids.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import aiohttp

from cryodaq.core.alarm import AlarmEngine
from cryodaq.core.broker import DataBroker
from cryodaq.drivers.base import Reading
from cryodaq.notifications._secrets import SecretStr

logger = logging.getLogger(__name__)

_SUBSCRIBE_NAME = "telegram_commands"
_HELP_TEXT = (
    "<b>CryoDAQ — команды бота</b>\n\n"
    "/status — состояние системы\n"
    "/temps — таблица температур\n"
    "/log &lt;текст&gt; — записать в операторский журнал\n"
    "/phase &lt;фаза&gt; — перевести эксперимент в фазу\n"
    "/pressure — уровень вакуума\n"
    "/keithley — показания Keithley (V, I, R, P)\n"
    "/alarms — активные тревоги\n"
    "/help — список команд"
)

# Phase 2c Codex I.2: derive the accepted phase vocabulary from the canonical
# ExperimentPhase enum. Previously this was a hand-maintained list that
# drifted ("cooling"/"warming" instead of the enum's "cooldown"/"warmup",
# missing "vacuum") so remote operators received bogus "unknown phase"
# errors for phases that exist locally.
from cryodaq.core.experiment import ExperimentPhase as _ExperimentPhase

VALID_PHASES: frozenset[str] = frozenset(p.value for p in _ExperimentPhase)
# Backwards-compatible aliases for Telegram clients that learned the old
# vocabulary. Mapped to canonical enum values at command-handler entry.
_PHASE_ALIASES: dict[str, str] = {
    "cooling": "cooldown",
    "warming": "warmup",
}
# Legacy mutable list kept for any callers that import it. Prefer VALID_PHASES.
_VALID_PHASES = sorted(VALID_PHASES)


class _TelegramAuthError(Exception):
    """Raised when Telegram API returns 401 or 404 (bad token)."""


class TelegramCommandBot:
    """Бот для обработки Telegram-команд.

    Параметры
    ----------
    broker:       DataBroker для подписки на данные.
    alarm_engine: AlarmEngine для запроса состояния тревог.
    bot_token:    Токен Telegram-бота (str или SecretStr).
    allowed_chat_ids: Список разрешённых chat_id. Phase 2b Codex K.1:
        пустой список + commands_enabled=True → ValueError при создании
        (default-deny — пустой ALLOW_ALL для safety-sensitive команд
        /phase / /log недопустим).
    commands_enabled: Если False, конструктор не валидирует allowed_chat_ids
        и бот стартует только для чтения (без обработки команд).
    poll_interval_s: Интервал опроса getUpdates.
    """

    def __init__(
        self,
        broker: DataBroker | None = None,
        alarm_engine: AlarmEngine | None = None,
        *,
        bot_token: str | SecretStr,
        allowed_chat_ids: list[int] | None = None,
        poll_interval_s: float = 2.0,
        command_handler: Callable[[dict], Awaitable[dict]] | None = None,
        commands_enabled: bool = True,
    ) -> None:
        # Phase 2b Codex K.1: default-deny — empty allowlist with commands
        # enabled would let any chat issue /phase and /log (safety-sensitive
        # control surface). Refuse to construct in that state.
        if commands_enabled and not (allowed_chat_ids or []):
            raise ValueError(
                "Telegram commands are enabled but allowed_chat_ids is empty. "
                "This would allow ANY chat to issue /phase and /log commands. "
                "Add at least one chat ID to config/notifications.local.yaml, "
                "or set commands.enabled: false."
            )

        self._broker = broker
        self._alarm_engine = alarm_engine
        # Phase 2b K.1: SecretStr wrapper.
        self._bot_token = (
            bot_token if isinstance(bot_token, SecretStr) else SecretStr(bot_token)
        )
        self._allowed_ids: set[int] = set(allowed_chat_ids or [])
        self._poll_interval_s = poll_interval_s
        self._command_handler = command_handler
        self._commands_enabled = commands_enabled

        # Runtime state — restored from the original constructor (the Phase 2b
        # rewrite of __init__ accidentally dropped these initializers).
        self._latest: dict[str, Reading] = {}
        self._start_time = datetime.now(timezone.utc)
        self._last_update_id = 0
        self._collect_task: asyncio.Task[None] | None = None
        self._poll_task: asyncio.Task[None] | None = None
        self._queue: asyncio.Queue[Reading] | None = None
        self._session: aiohttp.ClientSession | None = None

    @property
    def _api(self) -> str:
        """Compute the Telegram API base URL on demand (no stored plain string)."""
        return f"https://api.telegram.org/bot{self._bot_token.get_secret_value()}"

    def _is_chat_allowed(self, chat_id: int) -> bool:
        """Default-deny chat permission check (Phase 2b Codex K.1)."""
        return chat_id in self._allowed_ids

    async def start(self) -> None:
        self._queue = await self._broker.subscribe(_SUBSCRIBE_NAME, maxsize=5000)
        self._collect_task = asyncio.create_task(self._collect_loop(), name="tg_cmd_collect")
        self._poll_task = asyncio.create_task(self._poll_loop(), name="tg_cmd_poll")
        logger.info(
            "TelegramCommandBot запущен | collect_task=%s poll_task=%s",
            self._collect_task.get_name(),
            self._poll_task.get_name(),
        )

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            # total=None чтобы long-poll (timeout=5 в params) не упирался в общий таймаут
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=None, connect=10, sock_read=30)
            )
        return self._session

    async def stop(self) -> None:
        for task in (self._collect_task, self._poll_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._collect_task = None
        self._poll_task = None
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
        await self._broker.unsubscribe(_SUBSCRIBE_NAME)
        logger.info("TelegramCommandBot остановлен")

    # ------------------------------------------------------------------
    # Data collection
    # ------------------------------------------------------------------

    async def _collect_loop(self) -> None:
        assert self._queue is not None
        try:
            while True:
                reading = await self._queue.get()
                self._latest[reading.channel] = reading
        except asyncio.CancelledError:
            return

    # ------------------------------------------------------------------
    # Telegram polling
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        logger.info("Telegram polling task started (interval=%.1fs)", self._poll_interval_s)
        iteration = 0
        backoff_s = self._poll_interval_s
        try:
            while True:
                iteration += 1
                logger.info(
                    "Telegram polling #%d, offset=%s", iteration, self._last_update_id
                )
                try:
                    await self._fetch_updates()
                    backoff_s = self._poll_interval_s  # сброс бэкоффа при успехе
                except _TelegramAuthError as exc:
                    # 401/404 — токен невалидный, не спамим
                    backoff_s = min(backoff_s * 2, 300)
                    logger.error(
                        "Telegram token error (#%d), backoff=%.0fs: %s",
                        iteration, backoff_s, exc,
                    )
                except Exception as exc:
                    logger.error(
                        "Telegram polling error (#%d): %s", iteration, exc, exc_info=True
                    )
                await asyncio.sleep(backoff_s)
        except asyncio.CancelledError:
            logger.info("Telegram polling task cancelled after %d iterations", iteration)
            return

    async def _fetch_updates(self) -> None:
        url = f"{self._api}/getUpdates"
        params: dict[str, Any] = {"timeout": 5}
        if self._last_update_id:
            params["offset"] = self._last_update_id + 1

        session = await self._get_session()
        async with session.get(url, params=params) as resp:
            if resp.status != 200:
                body = await resp.text()
                logger.error(
                    "Telegram getUpdates HTTP %d: %s", resp.status, body[:300]
                )
                if resp.status in (401, 404):
                    raise _TelegramAuthError(f"HTTP {resp.status}: {body[:100]}")
                return
            data = await resp.json()

        if not data.get("ok"):
            logger.error("Telegram getUpdates not ok: %s", data)
            return

        updates = data.get("result", [])
        logger.info("Telegram: получено %d обновлений", len(updates))

        for update in updates:
            self._last_update_id = max(self._last_update_id, update["update_id"])
            msg = update.get("message", {})
            text = msg.get("text", "")
            chat_id = msg.get("chat", {}).get("id")

            if not chat_id or not text.startswith("/"):
                continue

            # Security check (Phase 2b Codex K.1: default-deny on empty list).
            if not self._is_chat_allowed(chat_id):
                logger.warning("Отклонён запрос от chat_id=%s", chat_id)
                continue

            await self._handle_message(msg)

    async def _handle_message(self, msg: dict) -> None:
        """Обработать входящее сообщение с полным контекстом (текст + from + chat).

        Defense-in-depth (Phase 2b Codex K.1): re-checks ``_is_chat_allowed``
        even though ``_fetch_updates`` already filters. Direct callers
        (tests, future code paths) must NOT bypass the allowlist.
        """
        text = msg.get("text", "").strip()
        chat_id = msg.get("chat", {}).get("id")
        if not chat_id or not text.startswith("/"):
            return

        if not self._is_chat_allowed(chat_id):
            logger.warning(
                "Отклонён прямой вызов _handle_message от chat_id=%s", chat_id,
            )
            return

        command = text.split()[0].split("@")[0].lower()

        if command == "/status":
            await self._send(chat_id, self._cmd_status())
        elif command == "/temps":
            await self._send(chat_id, self._cmd_temps())
        elif command == "/pressure":
            await self._send(chat_id, self._cmd_pressure())
        elif command == "/keithley":
            await self._send(chat_id, self._cmd_keithley())
        elif command == "/alarms":
            await self._send(chat_id, self._cmd_alarms())
        elif command in ("/help", "/start"):
            await self._send(chat_id, _HELP_TEXT)
        elif command == "/log":
            log_text = text[len("/log"):].strip()
            await self._cmd_log(chat_id, log_text, msg)
        elif command == "/phase":
            phase_arg = text[len("/phase"):].strip()
            await self._cmd_phase(chat_id, phase_arg, msg)
        else:
            await self._send(chat_id, f"Неизвестная команда: {command}\n\n{_HELP_TEXT}")

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    def _cmd_status(self) -> str:
        uptime = datetime.now(timezone.utc) - self._start_time
        h, rem = divmod(int(uptime.total_seconds()), 3600)
        m, s = divmod(rem, 60)

        instruments: dict[str, int] = {}
        for ch, r in self._latest.items():
            inst = r.instrument_id or ""
            if inst:
                instruments[inst] = instruments.get(inst, 0) + 1

        alarms = self._alarm_engine.get_active_alarms()

        lines = [
            "<b>CryoDAQ — Статус</b>",
            f"Аптайм: {h:02d}:{m:02d}:{s:02d}",
            f"Каналов: {len(self._latest)}",
            "",
            "<b>Приборы:</b>",
        ]
        if instruments:
            for inst_id in sorted(instruments):
                lines.append(f"  {inst_id}: активен")
        else:
            lines.append("  Нет данных")

        lines.append("")
        if alarms:
            lines.append(f"<b>Активные тревоги: {len(alarms)}</b>")
            for name in alarms:
                lines.append(f"  {name}")
        else:
            lines.append("Тревоги: нет")

        return "\n".join(lines)

    def _cmd_temps(self) -> str:
        temps = {ch: r for ch, r in self._latest.items()
                 if r.unit == "K" and ch.startswith("Т")}

        if not temps:
            return "Нет температурных данных."

        lines = ["<b>Температуры</b>", "<pre>"]
        for ch in sorted(temps):
            r = temps[ch]
            lines.append(f"{ch:<22s} {r.value:>8.2f} K")
        lines.append("</pre>")
        return "\n".join(lines)

    def _cmd_pressure(self) -> str:
        pressure = {ch: r for ch, r in self._latest.items() if r.unit == "mbar"}

        if not pressure:
            return "Нет данных давления."

        lines = ["<b>Давление</b>", ""]
        for ch in sorted(pressure):
            r = pressure[ch]
            lines.append(f"{ch}: <b>{r.value:.2e}</b> мбар")
        return "\n".join(lines)

    def _cmd_keithley(self) -> str:
        keithley = {ch: r for ch, r in self._latest.items() if "/smu" in ch}

        if not keithley:
            return "Нет данных Keithley."

        lines = ["<b>Keithley 2604B</b>", "<pre>"]
        for ch in sorted(keithley):
            r = keithley[ch]
            short = ch.split("/", 1)[1] if "/" in ch else ch
            lines.append(f"{short:<20s} {r.value:>12.6g} {r.unit}")
        lines.append("</pre>")
        return "\n".join(lines)

    def _cmd_alarms(self) -> str:
        active = self._alarm_engine.get_active_alarms()
        states = self._alarm_engine.get_state()
        events = self._alarm_engine.get_events()

        if not active:
            return "Активных тревог нет."

        lines = ["<b>Активные тревоги</b>", ""]
        for name in active:
            state = states.get(name)
            recent = [e for e in events if e.alarm_name == name]
            last = recent[-1] if recent else None
            line = f"  <b>{name}</b> — {state.value if state else '?'}"
            if last:
                line += f"\n    Канал: {last.channel}, значение: {last.value:.4g}"
            lines.append(line)
        return "\n".join(lines)

    def _cmd_help(self) -> str:
        return _HELP_TEXT

    async def _cmd_log(self, chat_id: int, text: str, msg: dict) -> None:
        if not text:
            await self._send(chat_id, "❌ Укажите текст: /log &lt;текст&gt;")
            return
        if self._command_handler is None:
            await self._send(chat_id, "❌ Команды недоступны (нет command_handler)")
            return
        from_info = msg.get("from", {})
        username = from_info.get("username") or from_info.get("first_name", "telegram")
        result = await self._command_handler({
            "cmd": "log_entry",
            "message": text,
            "author": username,
            "source": "telegram",
        })
        if result.get("ok"):
            await self._send(chat_id, "✅ Записано в журнал")
        else:
            await self._send(chat_id, f"❌ Ошибка: {result.get('error', '?')}")

    async def _cmd_phase(self, chat_id: int, phase: str, msg: dict) -> None:
        # Phase 2c Codex I.2: accept legacy aliases (cooling/warming) and
        # canonicalise to ExperimentPhase enum values.
        normalized = phase.strip().lower()
        normalized = _PHASE_ALIASES.get(normalized, normalized)
        if normalized not in VALID_PHASES:
            phases_str = ", ".join(sorted(VALID_PHASES))
            await self._send(chat_id, f"❌ Неверная фаза. Доступные: {phases_str}")
            return
        phase = normalized
        if self._command_handler is None:
            await self._send(chat_id, "❌ Команды недоступны (нет command_handler)")
            return
        from_info = msg.get("from", {})
        username = from_info.get("username") or from_info.get("first_name", "telegram")
        result = await self._command_handler({
            "cmd": "experiment_advance_phase",
            "phase": phase,
            "operator": username,
        })
        if result.get("ok"):
            await self._send(chat_id, f"✅ Фаза: → {phase}")
        else:
            await self._send(chat_id, f"❌ Ошибка: {result.get('error', '?')}")

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    async def _send(self, chat_id: int, text: str) -> None:
        try:
            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
            session = await self._get_session()
            async with session.post(f"{self._api}/sendMessage", json=payload) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error("Telegram sendMessage %d: %s", resp.status, body[:200])
        except Exception as exc:
            logger.error("Ошибка отправки Telegram: %s", exc)

    async def _send_to_all(self, text: str) -> None:
        """Отправить текст всем разрешённым chat_id (или только первому если список пуст)."""
        if self._allowed_ids:
            for chat_id in self._allowed_ids:
                await self._send(chat_id, text)
        else:
            logger.debug("_send_to_all: нет allowed_chat_ids, сообщение не отправлено")
