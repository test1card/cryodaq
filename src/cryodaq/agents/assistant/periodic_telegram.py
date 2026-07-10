"""Outbound-only, duplicate-conservative Telegram transport for periodic PNGs."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import logging
import math
import re
import struct
import zlib
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from cryodaq.notifications._secrets import SecretStr
from cryodaq.periodic_config import PeriodicPngConfig
from cryodaq.reporting.periodic_input import (
    MAX_PNG_BYTES,
    PeriodicInputError,
    validate_caption_html,
)

logger = logging.getLogger(__name__)

_TELEGRAM_ROOT = "https://api.telegram.org"
_TOKEN = re.compile(r"[1-9][0-9]{5,19}:[A-Za-z0-9_-]{20,256}")
_CHANNEL = re.compile(r"@[A-Za-z][A-Za-z0-9_]{0,126}")
_USERNAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,126}")
_CODE = re.compile(r"[a-z][a-z0-9_.-]{0,127}")
_MAX_RESPONSE_BYTES = 65_536
_MAX_JSON_DEPTH = 16
_MAX_JSON_INTEGER = 2**63 - 1
_MAX_DESCRIPTION_BYTES = 2_048
_MAX_RETRY_AFTER = 86_400
_MAX_MULTIPART_OVERHEAD = 16 * 1024

_ERROR_TEXT = {
    "invalid_photo": "periodic PNG is invalid",
    "invalid_caption": "periodic caption is invalid",
    "invalid_token": "periodic Telegram token is invalid",
    "invalid_destination": "periodic Telegram destination is invalid",
    "invalid_request": "periodic Telegram request is invalid",
    "client_busy": "periodic Telegram client is busy",
    "client_closed": "periodic Telegram client is closed",
    "telegram_connect_failed": "Telegram connection was not established",
    "telegram_retryable_rejection": "Telegram rejected the report temporarily",
    "telegram_permanent_rejection": "Telegram rejected the report",
    "telegram_response_unknown": "Telegram response could not be proven",
    "telegram_acceptance_unknown": "Telegram acceptance evidence is incomplete",
    "telegram_transport_unknown": "Telegram delivery outcome is unknown",
    "telegram_timeout_unknown": "Telegram delivery timed out with unknown outcome",
    "telegram_cancelled_unknown": "Telegram delivery was cancelled with unknown outcome",
    "telegram_redirect_unknown": "Telegram returned an unexpected redirect",
    "telegram_internal_unknown": "Telegram delivery outcome is unknown",
}


class TelegramOutcome(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    NOT_SENT = "not_sent"
    UNKNOWN = "unknown"


_OUTCOME_ERROR_CODES = {
    TelegramOutcome.REJECTED: frozenset(
        {"telegram_retryable_rejection", "telegram_permanent_rejection"}
    ),
    TelegramOutcome.NOT_SENT: frozenset(
        {
            "invalid_photo",
            "invalid_caption",
            "invalid_token",
            "invalid_destination",
            "invalid_request",
            "client_busy",
            "client_closed",
            "telegram_connect_failed",
        }
    ),
    TelegramOutcome.UNKNOWN: frozenset(
        {
            "telegram_response_unknown",
            "telegram_acceptance_unknown",
            "telegram_transport_unknown",
            "telegram_timeout_unknown",
            "telegram_cancelled_unknown",
            "telegram_redirect_unknown",
            "telegram_internal_unknown",
        }
    ),
}


@dataclass(frozen=True, slots=True)
class TelegramDeliveryResult:
    outcome: TelegramOutcome
    message_id: int | None
    http_status: int | None
    retry_after_s: float | None
    error_code: str | None
    error_text: str

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, TelegramOutcome):
            raise TypeError("outcome must be TelegramOutcome")
        if self.http_status is not None and (type(self.http_status) is not int or not 100 <= self.http_status <= 599):
            raise ValueError("http_status is invalid")
        if self.outcome is TelegramOutcome.ACCEPTED:
            valid = (
                type(self.message_id) is int
                and 1 <= self.message_id <= _MAX_JSON_INTEGER
                and self.http_status == 200
                and self.retry_after_s is None
                and self.error_code is None
                and self.error_text == ""
            )
        else:
            valid = self.message_id is None and self.error_code in _ERROR_TEXT
            valid = valid and self.error_code in _OUTCOME_ERROR_CODES[self.outcome]
            valid = valid and self.error_text == _ERROR_TEXT.get(self.error_code)
            if self.outcome is TelegramOutcome.NOT_SENT:
                valid = valid and self.http_status is None and self.retry_after_s is None
            elif self.outcome is TelegramOutcome.UNKNOWN:
                valid = valid and self.retry_after_s is None
            else:
                valid = valid and self.http_status is not None and 400 <= self.http_status <= 599
                if self.retry_after_s is not None:
                    valid = (
                        valid
                        and self.http_status == 429
                        and type(self.retry_after_s) is float
                        and math.isfinite(self.retry_after_s)
                        and 1 <= self.retry_after_s <= _MAX_RETRY_AFTER
                    )
        if not valid:
            raise ValueError("Telegram delivery result fields are inconsistent")
        if self.error_code is not None and _CODE.fullmatch(self.error_code) is None:
            raise ValueError("error_code is invalid")
        if len(self.error_text.encode("utf-8", errors="strict")) > 512:
            raise ValueError("error_text is oversized")


def _fixed_result(
    outcome: TelegramOutcome,
    code: str,
    *,
    status: int | None = None,
    retry_after: float | None = None,
) -> TelegramDeliveryResult:
    return TelegramDeliveryResult(outcome, None, status, retry_after, code, _ERROR_TEXT[code])


@dataclass(frozen=True, slots=True)
class _CompleteHttpResponse:
    status: int
    body: bytes

    def __post_init__(self) -> None:
        if type(self.status) is not int or not 100 <= self.status <= 599:
            raise ValueError("response status is invalid")
        if type(self.body) is not bytes or len(self.body) > _MAX_RESPONSE_BYTES:
            raise ValueError("response body is invalid")


class _PeriodicTelegramTransport(Protocol):
    async def send_photo(
        self,
        *,
        token: SecretStr,
        chat_id: int | str,
        photo: bytes,
        caption: str,
        timeout_s: float,
    ) -> _CompleteHttpResponse | TelegramDeliveryResult: ...

    async def close(self) -> None: ...


type _TransportResult = _CompleteHttpResponse | TelegramDeliveryResult


class PeriodicTelegramClient:
    """One-destination client with no inbound/control Telegram surface."""

    def __init__(
        self,
        config: PeriodicPngConfig,
        *,
        _transport: _PeriodicTelegramTransport | None = None,
    ) -> None:
        if not isinstance(config, PeriodicPngConfig) or not config.enabled:
            raise TypeError("enabled PeriodicPngConfig is required")
        self._token = config.telegram_token
        self._chat_id = config.telegram_chat_id
        self._timeout_s = config.telegram_timeout_s
        self._verify_ssl = config.telegram_verify_ssl
        self._transport = _transport if _transport is not None else _AiohttpPeriodicTransport(self._verify_ssl)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._send_active = False
        self._active_task: asyncio.Task[Any] | None = None
        self._active_done: asyncio.Future[None] | None = None
        self._closing = False
        self._closed = False
        self._close_task: asyncio.Task[None] | None = None
        if not self._verify_ssl:
            logger.warning("Periodic Telegram SSL verification is disabled")

    def _bind_loop(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise RuntimeError("Periodic Telegram client belongs to another event loop")
        return loop

    async def send_photo(self, photo: bytes, caption: str) -> TelegramDeliveryResult:
        loop = self._bind_loop()
        if self._closing or self._closed:
            return _fixed_result(TelegramOutcome.NOT_SENT, "client_closed")
        if self._send_active:
            return _fixed_result(TelegramOutcome.NOT_SENT, "client_busy")
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("Periodic Telegram send requires an asyncio task")
        done = loop.create_future()
        self._send_active = True
        self._active_task = task
        self._active_done = done
        try:
            try:
                _validate_png(photo)
            except (TypeError, ValueError):
                return _fixed_result(TelegramOutcome.NOT_SENT, "invalid_photo")
            if type(caption) is not str or not caption:
                return _fixed_result(TelegramOutcome.NOT_SENT, "invalid_caption")
            try:
                validate_caption_html(caption)
            except PeriodicInputError:
                return _fixed_result(TelegramOutcome.NOT_SENT, "invalid_caption")
            if not isinstance(self._token, SecretStr) or _TOKEN.fullmatch(self._token.get_secret_value()) is None:
                return _fixed_result(TelegramOutcome.NOT_SENT, "invalid_token")
            if not _valid_destination(self._chat_id):
                return _fixed_result(TelegramOutcome.NOT_SENT, "invalid_destination")
            observed = await self._transport.send_photo(
                token=self._token,
                chat_id=self._chat_id,
                photo=photo,
                caption=caption,
                timeout_s=self._timeout_s,
            )
            if isinstance(observed, TelegramDeliveryResult):
                if observed.outcome not in {TelegramOutcome.NOT_SENT, TelegramOutcome.UNKNOWN}:
                    return _fixed_result(TelegramOutcome.UNKNOWN, "telegram_internal_unknown")
                return observed
            if not isinstance(observed, _CompleteHttpResponse):
                return _fixed_result(TelegramOutcome.UNKNOWN, "telegram_internal_unknown")
            return _classify_response(observed, self._chat_id)
        finally:
            if not done.done():
                done.set_result(None)
            if self._active_done is done:
                self._active_done = None
                self._active_task = None
                self._send_active = False

    async def close(self) -> None:
        loop = self._bind_loop()
        if asyncio.current_task() is self._active_task:
            raise RuntimeError("active send cannot close its Telegram client")
        if self._close_task is None:
            self._closing = True
            self._close_task = loop.create_task(self._close_impl(self._active_done))
        await asyncio.shield(self._close_task)

    async def _close_impl(self, done: asyncio.Future[None] | None) -> None:
        try:
            if done is not None:
                await done
        finally:
            try:
                await self._transport.close()
            finally:
                self._closed = True


class _AiohttpPeriodicTransport:
    def __init__(self, verify_ssl: bool) -> None:
        self._verify_ssl = verify_ssl
        self._aiohttp: Any | None = None
        self._session: Any | None = None

    async def _get_session(self, timeout_s: float) -> Any:
        if self._session is not None and not self._session.closed:
            return self._session
        aiohttp = _load_aiohttp()
        connector = aiohttp.TCPConnector(ssl=self._verify_ssl, limit=1, limit_per_host=1)
        try:
            session = aiohttp.ClientSession(
                connector=connector,
                connector_owner=True,
                timeout=aiohttp.ClientTimeout(
                    total=timeout_s,
                    connect=timeout_s,
                    sock_connect=timeout_s,
                    sock_read=timeout_s,
                ),
                trust_env=False,
                raise_for_status=False,
                auto_decompress=False,
                cookie_jar=aiohttp.DummyCookieJar(),
                headers={"Accept": "application/json", "Accept-Encoding": "identity"},
            )
        except Exception:
            closed = connector.close()
            if inspect.isawaitable(closed):
                await closed
            raise
        self._aiohttp = aiohttp
        self._session = session
        return session

    async def send_photo(
        self,
        *,
        token: SecretStr,
        chat_id: int | str,
        photo: bytes,
        caption: str,
        timeout_s: float,
    ) -> _TransportResult:
        try:
            session = await self._get_session(timeout_s)
            aiohttp = self._aiohttp
            assert aiohttp is not None
            form = aiohttp.FormData()
            form.add_field("chat_id", str(chat_id))
            form.add_field("photo", photo, filename="report.png", content_type="image/png")
            form.add_field("caption", caption)
            form.add_field("parse_mode", "HTML")
            payload = form()
            size = payload.size
            minimum = len(photo) + len(caption.encode("utf-8"))
            if type(size) is not int or size < minimum or size - minimum > _MAX_MULTIPART_OVERHEAD:
                return _fixed_result(TelegramOutcome.NOT_SENT, "invalid_request")
        except asyncio.CancelledError:
            raise
        except Exception:
            return _fixed_result(TelegramOutcome.NOT_SENT, "invalid_request")

        response_seen = False
        request_invoked = False
        url = f"{_TELEGRAM_ROOT}/bot{token.get_secret_value()}/sendPhoto"
        try:
            request_invoked = True
            async with asyncio.timeout(timeout_s):
                async with session.post(url, data=payload, allow_redirects=False) as response:
                    response_seen = True
                    return await _read_response(response)
        except asyncio.CancelledError:
            if request_invoked:
                return _fixed_result(TelegramOutcome.UNKNOWN, "telegram_cancelled_unknown")
            raise
        except aiohttp.ClientConnectorError:
            if not response_seen:
                return _fixed_result(TelegramOutcome.NOT_SENT, "telegram_connect_failed")
            return _fixed_result(TelegramOutcome.UNKNOWN, "telegram_transport_unknown")
        except TimeoutError:
            return _fixed_result(TelegramOutcome.UNKNOWN, "telegram_timeout_unknown")
        except (aiohttp.ClientError, OSError):
            return _fixed_result(TelegramOutcome.UNKNOWN, "telegram_transport_unknown")
        except Exception:
            return _fixed_result(TelegramOutcome.UNKNOWN, "telegram_internal_unknown")
        finally:
            url = ""
            payload = None
            form = None

    async def close(self) -> None:
        session = self._session
        self._session = None
        if session is not None and not session.closed:
            await session.close()


def _load_aiohttp() -> Any:
    return importlib.import_module("aiohttp")


async def _read_response(response: Any) -> _CompleteHttpResponse | TelegramDeliveryResult:
    status = response.status
    if type(status) is not int or not 100 <= status <= 599:
        return _fixed_result(TelegramOutcome.UNKNOWN, "telegram_response_unknown")
    encodings = response.headers.getall("Content-Encoding", [])
    if len(encodings) > 1 or (encodings and encodings[0].strip().casefold() != "identity"):
        return _response_unknown(status)
    length = response.content_length
    if length is not None and (type(length) is not int or not 0 <= length <= _MAX_RESPONSE_BYTES):
        return _response_unknown(status)
    body = bytearray()
    async for chunk in response.content.iter_chunked(4_096):
        if len(body) + len(chunk) > _MAX_RESPONSE_BYTES:
            return _response_unknown(status)
        body.extend(chunk)
    return _CompleteHttpResponse(status, bytes(body))


def _classify_response(response: _CompleteHttpResponse, configured_chat: int | str) -> TelegramDeliveryResult:
    status = response.status
    try:
        text = response.body.decode("utf-8", errors="strict")
        _check_json_depth(text)
        payload = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_int=_bounded_int,
            parse_float=_bounded_float,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, ValueError, OverflowError, RecursionError, json.JSONDecodeError):
        return _response_unknown(status)
    if not isinstance(payload, Mapping) or type(payload.get("ok")) is not bool:
        return _response_unknown(status)
    if payload["ok"] is True:
        if status != 200:
            return _response_unknown(status)
        result = payload.get("result")
        chat = result.get("chat") if isinstance(result, Mapping) else None
        message_id = result.get("message_id") if isinstance(result, Mapping) else None
        if (
            not isinstance(chat, Mapping)
            or type(message_id) is not int
            or not 1 <= message_id <= _MAX_JSON_INTEGER
            or not _chat_matches(chat, configured_chat)
        ):
            return _fixed_result(TelegramOutcome.UNKNOWN, "telegram_acceptance_unknown", status=200)
        return TelegramDeliveryResult(TelegramOutcome.ACCEPTED, message_id, 200, None, None, "")
    if not 400 <= status <= 599:
        return _response_unknown(status)
    code = payload.get("error_code")
    description = payload.get("description")
    parameters_present = "parameters" in payload
    parameters = payload.get("parameters")
    if (
        type(code) is not int
        or code != status
        or not isinstance(description, str)
        or not description
        or not _valid_description(description)
        or (parameters_present and not isinstance(parameters, Mapping))
    ):
        return _response_unknown(status)
    retryable = status in {408, 409, 425, 429} or status >= 500
    retry_after: float | None = None
    if status == 429 and isinstance(parameters, Mapping):
        value = parameters.get("retry_after")
        if type(value) is int and 1 <= value <= _MAX_RETRY_AFTER:
            retry_after = float(value)
    return _fixed_result(
        TelegramOutcome.REJECTED,
        "telegram_retryable_rejection" if retryable else "telegram_permanent_rejection",
        status=status,
        retry_after=retry_after,
    )


def _response_unknown(status: int) -> TelegramDeliveryResult:
    code = "telegram_redirect_unknown" if 300 <= status <= 399 else "telegram_response_unknown"
    return _fixed_result(TelegramOutcome.UNKNOWN, code, status=status)


def _chat_matches(chat: Mapping[str, object], configured: int | str) -> bool:
    if type(configured) is int:
        return type(chat.get("id")) is int and chat.get("id") == configured
    username = chat.get("username")
    return (
        type(username) is str
        and _USERNAME.fullmatch(username) is not None
        and username.casefold() == configured[1:].casefold()
    )


def _valid_destination(value: object) -> bool:
    return (type(value) is int and value != 0) or (type(value) is str and _CHANNEL.fullmatch(value) is not None)


def _valid_description(value: str) -> bool:
    try:
        return 0 < len(value.encode("utf-8", errors="strict")) <= _MAX_DESCRIPTION_BYTES
    except UnicodeError:
        return False


def _validate_png(raw: object) -> tuple[int, int]:
    if type(raw) is not bytes or not 33 <= len(raw) <= MAX_PNG_BYTES:
        raise ValueError("invalid PNG")
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("invalid PNG")
    offset = 8
    width = height = None
    saw_idat = False
    saw_iend = False
    while offset < len(raw):
        if len(raw) - offset < 12:
            raise ValueError("invalid PNG")
        length = struct.unpack(">I", raw[offset : offset + 4])[0]
        kind = raw[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(raw) or not all(chr(value).isalpha() and value < 128 for value in kind):
            raise ValueError("invalid PNG")
        payload_end = offset + 8 + length
        crc = struct.unpack(">I", raw[payload_end:end])[0]
        if zlib.crc32(raw[offset + 4 : payload_end]) & 0xFFFFFFFF != crc:
            raise ValueError("invalid PNG")
        if offset == 8:
            if kind != b"IHDR" or length != 13:
                raise ValueError("invalid PNG")
            width, height = struct.unpack(">II", raw[offset + 8 : offset + 16])
        elif kind == b"IHDR":
            raise ValueError("invalid PNG")
        if kind == b"IDAT":
            saw_idat = True
        if kind == b"IEND":
            if length != 0 or end != len(raw):
                raise ValueError("invalid PNG")
            saw_iend = True
        offset = end
    if width is None or height is None or not saw_idat or not saw_iend:
        raise ValueError("invalid PNG")
    if (
        not 100 <= width <= 10_000
        or not 100 <= height <= 10_000
        or width + height > 10_000
        or width * height > 50_000_000
        or max(width, height) > 20 * min(width, height)
    ):
        raise ValueError("invalid PNG")
    return width, height


def _check_json_depth(text: str) -> None:
    depth = 0
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            if depth > _MAX_JSON_DEPTH:
                raise ValueError("JSON is too deep")
        elif char in "]}":
            depth -= 1
            if depth < 0:
                raise ValueError("JSON nesting is invalid")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _bounded_int(value: str) -> int:
    digits = value[1:] if value.startswith("-") else value
    if len(digits) > 20:
        raise ValueError("JSON integer is oversized")
    result = int(value)
    if abs(result) > _MAX_JSON_INTEGER:
        raise ValueError("JSON integer is outside range")
    return result


def _bounded_float(value: str) -> float:
    if len(value) > 64:
        raise ValueError("JSON float is oversized")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("JSON float is non-finite")
    return result


def _reject_constant(_value: str) -> object:
    raise ValueError("non-finite JSON constant")
