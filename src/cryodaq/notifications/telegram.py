"""Отправка сообщений через Telegram Bot API.

TelegramNotifier — транспорт для :class:`EscalationService`: рассылает
готовый текст в указанный chat_id.

Конфигурация (config/notifications.yaml):

    telegram:
      bot_token: "123456:ABC-DEF..."
      chat_id: -1001234567890
      send_cleared: true           # зарезервировано (см. EscalationService)
      timeout_s: 10.0              # таймаут HTTP-запроса
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import aiohttp
import yaml

from cryodaq.notifications._secrets import SecretStr

logger = logging.getLogger(__name__)

# Telegram message ids are JSON integers; the live adapters accept 1..2**63-1.
_MAX_JSON_INTEGER = 2**63 - 1

# `await resp.json()` refuses a body whose media type is not JSON -- it raises
# `aiohttp.ContentTypeError` and this sender then answers `transport_accepted`.  Decoding the
# text ourselves is what the duplicate-key hook requires, and it drops that refusal unless the
# check is made again here; otherwise an HTTP 200 carrying `text/html` or `text/plain` from
# Telegram or an intervening proxy becomes delivery evidence.  This is `aiohttp.helpers.json_re`
# verbatim, applied to `resp.content_type` (already lowercased, parameters stripped), so the
# accepted set is the one this sender accepted before the hook was introduced.
_JSON_ACKNOWLEDGEMENT_MEDIA_TYPE = re.compile(r"^application/(?:[\w.+-]+?\+)?json")


def _reject_duplicate_acknowledgement_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Refuse an acknowledgement object that names any key twice.

    `resp.json()` silently keeps the LAST value for a repeated key, so a body carrying
    ``"chat": {"id": 222}, "chat": {"id": 111}`` decodes to the requested chat and passes the
    destination check -- while the acknowledgement itself establishes nothing about where the
    message went.  An ambiguous answer must not resolve to the convenient one.

    Raising rather than returning a sentinel is deliberate: the caller already treats an
    unparseable acknowledgement as `transport_accepted`, which is the honest tier for "the
    transport took it and the service told us nothing we can rely on".

    `cryodaq.agents.assistant_main._unique_telegram_acknowledgement_object` enforces the same
    rule for the sibling sender.  FOLLOW-UP, not done here: there are now four near-copies of
    this decoder across the notification surfaces, and they should be one.
    """

    seen: set[str] = set()
    for key, _ in pairs:
        if key in seen:
            raise ValueError(f"duplicate key in Telegram acknowledgement: {key!r}")
        seen.add(key)
    return dict(pairs)


def _acknowledges_delivery(message: object, chat_id: int | str) -> bool:
    """Return True only when the acknowledgement names OUR destination.

    OC-026, second independent review. This sender previously accepted any 200
    carrying ``ok: true`` and an integer ``result.message_id`` as
    ``service_reported_delivered``. A message id proves that SOME message was
    created, not that it reached the chat we asked for, so a body describing a
    message posted to a different chat -- or naming no chat at all -- was reported
    to the operator as delivered. For an alarm notifier that is the worst kind of
    wrong answer: it says the operator was told when they were not.

    THE RULES HERE ARE COPIED FROM THE ESTABLISHED CONTRACT, NOT INVENTED.
    ``cryodaq.agents.assistant_main._acknowledged_message_id`` and the live
    periodic adapter already bind the acknowledgement to the requested chat and
    already accept ``1..2**63-1``. Its docstring states the reason plainly: two
    senders disagreeing about what counts as an acknowledgement is itself a
    defect. They disagreed until this change; now they do not.

    ``type(...) is not int`` rather than ``isinstance`` because ``bool`` subclasses
    ``int`` and ``True`` must not read as message 1.
    """

    if not isinstance(message, dict):
        return False
    message_id = message.get("message_id")
    if type(message_id) is not int or not 1 <= message_id <= _MAX_JSON_INTEGER:
        return False
    chat = message.get("chat")
    if not isinstance(chat, dict):
        return False
    if type(chat_id) is int:
        return type(chat.get("id")) is int and chat.get("id") == chat_id
    username = chat.get("username")
    return type(username) is str and str(chat_id).startswith("@") and username.casefold() == str(chat_id)[1:].casefold()


class TelegramNotifier:
    """Отправка сообщений через Telegram.

    Используется как транспорт для :class:`EscalationService`::

        notifier = TelegramNotifier.from_config(Path("config/notifications.yaml"))
        escalation = EscalationService(notifier, notifications_config)

    Параметры
    ----------
    bot_token:
        Токен Telegram-бота (от @BotFather).
    chat_id:
        ID чата или группы по умолчанию.
    send_cleared:
        Зарезервировано; читается из конфигурации, поведение не задаёт.
    timeout_s:
        Таймаут HTTP-запроса к Telegram API.  По умолчанию 10 с.
    """

    def __init__(
        self,
        bot_token: str | SecretStr,
        chat_id: int | str,
        *,
        send_cleared: bool = True,
        timeout_s: float = 10.0,
        verify_ssl: bool = True,
    ) -> None:
        # Phase 2b K.1: store the token in a SecretStr wrapper so accidental
        # repr/str/f-string never leaks it. The API URL is computed on demand.
        self._bot_token = bot_token if isinstance(bot_token, SecretStr) else SecretStr(bot_token)
        self._chat_id = chat_id
        self._send_cleared = send_cleared
        self._timeout_s = timeout_s
        self._verify_ssl = verify_ssl
        self._session: aiohttp.ClientSession | None = None
        if not verify_ssl:
            logger.warning(
                "TelegramNotifier SSL verification DISABLED. "
                "Use only for dev environments behind VPN/SSL-inspection. "
                "Production deployments must keep verify_ssl=true."
            )

    def _build_api_url(self, method: str = "sendMessage") -> str:
        """Compute the Telegram API URL on demand. Never store as attribute."""
        return f"https://api.telegram.org/bot{self._bot_token.get_secret_value()}/{method}"

    @classmethod
    def from_config(cls, config_path: Path) -> TelegramNotifier:
        """Создать notifier из YAML-файла конфигурации.

        Ожидаемая структура::

            telegram:
              bot_token: "..."
              chat_id: ...
              send_cleared: true
              timeout_s: 10.0

        Параметры
        ----------
        config_path:
            Путь к config/notifications.yaml.

        Исключения
        ----------
        FileNotFoundError:  Файл не найден.
        KeyError:           Отсутствуют обязательные поля.
        """
        if not config_path.exists():
            raise FileNotFoundError(f"Файл конфигурации уведомлений не найден: {config_path}")

        with config_path.open(encoding="utf-8") as fh:
            raw: dict[str, Any] = yaml.safe_load(fh)

        tg = raw["telegram"]
        return cls(
            bot_token=str(tg["bot_token"]),
            chat_id=tg["chat_id"],
            send_cleared=bool(tg.get("send_cleared", True)),
            timeout_s=float(tg.get("timeout_s", 10.0)),
            verify_ssl=bool(tg.get("verify_ssl", True)),
        )

    # ------------------------------------------------------------------
    # Отправка HTTP-запроса
    # ------------------------------------------------------------------

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ssl=self._verify_ssl)
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self._timeout_s),
                connector=connector,
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def send_message(self, chat_id: int | str, text: str) -> str:
        """Отправить произвольное сообщение в указанный chat_id."""
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        try:
            session = await self._get_session()
            async with session.post(self._build_api_url("sendMessage"), json=payload) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error("Telegram API ответил %d: %s", resp.status, body[:200])
                    return "failed" if not 300 <= resp.status < 400 else "outcome_unknown"
                try:
                    body_text = await resp.text()
                    if not _JSON_ACKNOWLEDGEMENT_MEDIA_TYPE.match(resp.content_type):
                        raise ValueError(f"acknowledgement media type is not JSON: {resp.content_type!r}")
                    result = json.loads(body_text, object_pairs_hook=_reject_duplicate_acknowledgement_keys)
                except Exception:
                    logger.warning("Telegram API accepted sendMessage without a parseable service acknowledgement")
                    return "transport_accepted"
                if not isinstance(result, dict):
                    logger.warning("Telegram API accepted sendMessage without an object acknowledgement")
                    return "transport_accepted"
                if result.get("ok") is False:
                    logger.error("Telegram API rejected sendMessage: %s", result.get("description", "unknown error"))
                    return "failed"
                message = result.get("result")
                if result.get("ok") is True and _acknowledges_delivery(message, chat_id):
                    return "service_reported_delivered"
                logger.warning("Telegram API accepted sendMessage without a posted-message acknowledgement")
                return "transport_accepted"
        except Exception as exc:
            logger.error("Ошибка отправки Telegram-уведомления: %s", exc)
            return "outcome_unknown"
