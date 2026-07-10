from __future__ import annotations

import asyncio
import importlib
import json
import logging
import struct
import subprocess
import sys
import zlib
from collections import deque

import pytest

import cryodaq.agents.assistant.periodic_telegram as module
from cryodaq.agents.assistant.periodic_telegram import (
    PeriodicTelegramClient,
    TelegramDeliveryResult,
    TelegramOutcome,
    _AiohttpPeriodicTransport,
    _check_json_depth,
    _classify_response,
    _CompleteHttpResponse,
    _read_response,
)
from cryodaq.notifications._secrets import SecretStr
from cryodaq.periodic_config import PeriodicPngConfig

TOKEN = "7701234567:SENTINEL_TOK_9f3a_ABCDEFGHIJKLMNOP"


def _config(**overrides: object) -> PeriodicPngConfig:
    values: dict[str, object] = {
        "enabled": True,
        "interval_s": 1800,
        "chart_window_s": 7200,
        "include_channels": None,
        "max_points_per_channel": 20000,
        "max_total_points": 100000,
        "max_input_bytes": 8 * 1024 * 1024,
        "render_timeout_s": 120.0,
        "max_render_attempts": 5,
        "max_delivery_attempts": 5,
        "backoff_base_s": 30.0,
        "backoff_cap_s": 3600.0,
        "telegram_token": SecretStr(TOKEN),
        "telegram_chat_id": -100123,
        "telegram_timeout_s": 10.0,
        "telegram_verify_ssl": True,
        "config_fingerprint": "sha256:" + "a" * 64,
    }
    values.update(overrides)
    return PeriodicPngConfig(**values)  # type: ignore[arg-type]


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)


def _png(width: int = 640, height: int = 480) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", b"data") + _chunk(b"IEND", b"")


def _body(payload: object) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode()


def _accepted(chat: object = -100123, message_id: object = 42) -> _CompleteHttpResponse:
    chat_payload = {"id": chat} if isinstance(chat, int) else {"username": chat}
    return _CompleteHttpResponse(200, _body({"ok": True, "result": {"message_id": message_id, "chat": chat_payload}}))


class ScriptedTransport:
    def __init__(self, *results: object) -> None:
        self.results = deque(results)
        self.calls: list[dict[str, object]] = []
        self.close_calls = 0
        self.gate: asyncio.Event | None = None

    async def send_photo(self, **kwargs: object):
        self.calls.append({**kwargs, "token": isinstance(kwargs["token"], SecretStr)})
        if self.gate is not None:
            await self.gate.wait()
        value = self.results.popleft()
        if isinstance(value, BaseException):
            raise value
        return value

    async def close(self) -> None:
        self.close_calls += 1


async def _send(result: object, *, config: PeriodicPngConfig | None = None):
    transport = ScriptedTransport(result)
    client = PeriodicTelegramClient(config or _config(), _transport=transport)
    return await client.send_photo(_png(), "<b>Report</b>"), client, transport


def test_result_contract_rejects_impossible_field_products() -> None:
    with pytest.raises(ValueError):
        TelegramDeliveryResult(TelegramOutcome.ACCEPTED, True, 200, None, None, "")
    with pytest.raises(ValueError):
        TelegramDeliveryResult(
            TelegramOutcome.NOT_SENT, None, 500, None, "client_busy", "periodic Telegram client is busy"
        )
    with pytest.raises(ValueError):
        TelegramDeliveryResult(
            TelegramOutcome.REJECTED,
            None,
            400,
            None,
            "client_busy",
            "periodic Telegram client is busy",
        )


async def test_valid_accepted_numeric_response() -> None:
    result, _, _ = await _send(_accepted())
    assert result.outcome is TelegramOutcome.ACCEPTED and result.message_id == 42


async def test_valid_accepted_channel_username_casefold() -> None:
    result, _, _ = await _send(_accepted("channelname"), config=_config(telegram_chat_id="@ChannelName"))
    assert result.outcome is TelegramOutcome.ACCEPTED


@pytest.mark.parametrize("username", ["@channel", "1channel", "channel-name", "канал", "a" * 128])
async def test_invalid_returned_channel_username_shape_is_unknown(username: str) -> None:
    result, _, _ = await _send(_accepted(username), config=_config(telegram_chat_id="@channel"))
    assert result.error_code == "telegram_acceptance_unknown"


@pytest.mark.parametrize("message_id", [True, 0, -1, None, "1", 2**63])
async def test_bool_zero_negative_missing_or_wrong_message_id_is_unknown(message_id: object) -> None:
    result, _, _ = await _send(_accepted(message_id=message_id))
    assert result.outcome is TelegramOutcome.UNKNOWN


@pytest.mark.parametrize(
    "response,config", [(_accepted(-2), _config()), (_accepted("other"), _config(telegram_chat_id="@channel"))]
)
async def test_accepted_chat_mismatch_is_unknown(response, config) -> None:
    result, _, _ = await _send(response, config=config)
    assert result.error_code == "telegram_acceptance_unknown"


@pytest.mark.parametrize(
    "retry,expected", [(None, None), (False, None), (0, None), (1, 1.0), (86400, 86400.0), (86401, None), ("1", None)]
)
async def test_complete_429_rejection_has_bounded_retry_after(retry: object, expected: float | None) -> None:
    parameters = {} if retry is None else {"retry_after": retry}
    response = _CompleteHttpResponse(
        429, _body({"ok": False, "error_code": 429, "description": "rate", "parameters": parameters})
    )
    result, _, _ = await _send(response)
    assert result.outcome is TelegramOutcome.REJECTED and result.retry_after_s == expected


@pytest.mark.parametrize("status", [500, 599])
async def test_complete_bot_api_5xx_is_retryable_rejected(status: int) -> None:
    result, _, _ = await _send(
        _CompleteHttpResponse(status, _body({"ok": False, "error_code": status, "description": "no"}))
    )
    assert result.error_code == "telegram_retryable_rejection"


@pytest.mark.parametrize("raw", [b"<html>", b"{", _body({"ok": False})])
async def test_raw_or_malformed_5xx_is_unknown(raw: bytes) -> None:
    result, _, _ = await _send(_CompleteHttpResponse(500, raw))
    assert result.outcome is TelegramOutcome.UNKNOWN


@pytest.mark.parametrize("status", [400, 401, 403, 404])
async def test_complete_ordinary_4xx_is_permanent_rejected(status: int) -> None:
    result, _, _ = await _send(
        _CompleteHttpResponse(status, _body({"ok": False, "error_code": status, "description": "no"}))
    )
    assert result.error_code == "telegram_permanent_rejection"


@pytest.mark.parametrize("status", [408, 409, 425, 429])
async def test_exact_transient_4xx_set_is_retryable(status: int) -> None:
    result, _, _ = await _send(
        _CompleteHttpResponse(status, _body({"ok": False, "error_code": status, "description": "later"}))
    )
    assert result.error_code == "telegram_retryable_rejection"


@pytest.mark.parametrize(
    "payload",
    [
        {"ok": False, "error_code": 401, "description": "x"},
        {"ok": False, "error_code": True, "description": "x"},
        {"ok": False, "error_code": "400", "description": "x"},
        {"ok": False, "error_code": 400, "description": ""},
        {"ok": False, "error_code": 400, "description": "x", "parameters": None},
        {"ok": False, "error_code": 400, "description": "x", "parameters": []},
    ],
)
async def test_status_error_code_mismatch_or_bad_description_is_unknown(payload: dict) -> None:
    result, _, _ = await _send(_CompleteHttpResponse(400, _body(payload)))
    assert result.outcome is TelegramOutcome.UNKNOWN


@pytest.mark.parametrize("status", [100, 199, 200, 201, 299])
async def test_ok_false_outside_complete_rejection_statuses_is_unknown(status: int) -> None:
    response = _CompleteHttpResponse(
        status,
        _body({"ok": False, "error_code": status, "description": "no"}),
    )
    result, _, _ = await _send(response)
    assert result.outcome is TelegramOutcome.UNKNOWN


@pytest.mark.parametrize("ok", [None, 0, 1, "true", [], {}])
async def test_ok_must_be_exact_json_boolean(ok: object) -> None:
    result, _, _ = await _send(_CompleteHttpResponse(200, _body({"ok": ok})))
    assert result.outcome is TelegramOutcome.UNKNOWN


@pytest.mark.parametrize(
    "result",
    [
        None,
        [],
        {"message_id": 1, "chat": None},
        {"message_id": 1, "chat": []},
        {"message_id": 1, "chat": {"id": True}},
    ],
)
async def test_success_requires_result_and_chat_mappings(result: object) -> None:
    response = _CompleteHttpResponse(200, _body({"ok": True, "result": result}))
    observed, _, _ = await _send(response)
    assert observed.error_code == "telegram_acceptance_unknown"


def test_description_utf8_boundary_is_validated_then_discarded() -> None:
    accepted = _classify_response(
        _CompleteHttpResponse(
            400,
            _body({"ok": False, "error_code": 400, "description": "é" * 1_024}),
        ),
        -100123,
    )
    oversized = _classify_response(
        _CompleteHttpResponse(
            400,
            _body({"ok": False, "error_code": 400, "description": "é" * 1_024 + "x"}),
        ),
        -100123,
    )
    assert accepted.outcome is TelegramOutcome.REJECTED
    assert oversized.outcome is TelegramOutcome.UNKNOWN
    assert "é" not in repr(accepted)


def test_unpaired_surrogate_description_is_unknown_without_escape() -> None:
    raw = b'{"ok":false,"error_code":400,"description":"\\ud800"}'
    result = _classify_response(_CompleteHttpResponse(400, raw), -100123)
    assert result.outcome is TelegramOutcome.UNKNOWN


@pytest.mark.parametrize("failure", ["connector", "connector_dns", "connector_tls"])
async def test_connector_allowlist_is_not_sent(monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
    transport, fake = _real_transport_fake(monkeypatch, failure)
    result = await transport.send_photo(token=SecretStr(TOKEN), chat_id=-1, photo=_png(), caption="x", timeout_s=1)
    assert result.outcome is TelegramOutcome.NOT_SENT and fake.posts == 1


@pytest.mark.parametrize(
    "failure",
    [
        "client",
        "client_oserror",
        "client_connection",
        "server_connection",
        "payload",
        "oserror",
        "timeout",
        "cancel",
        "ordinary",
    ],
)
async def test_post_invocation_transport_failures_are_unknown(monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
    transport, _ = _real_transport_fake(monkeypatch, failure)
    result = await transport.send_photo(token=SecretStr(TOKEN), chat_id=-1, photo=_png(), caption="x", timeout_s=1)
    assert result.outcome is TelegramOutcome.UNKNOWN


@pytest.mark.parametrize("raw", [b"{", b"\xff", _body({"ok": True}), _body({"ok": True, "result": {}})])
async def test_malformed_truncated_oversized_or_invalid_2xx_is_unknown(raw: bytes) -> None:
    result, _, _ = await _send(_CompleteHttpResponse(200, raw))
    assert result.outcome is TelegramOutcome.UNKNOWN


@pytest.mark.parametrize("status", [301, 307, 308])
async def test_redirects_are_not_followed_and_unknown(status: int) -> None:
    result, _, _ = await _send(_CompleteHttpResponse(status, _body({"ok": False})))
    assert result.error_code == "telegram_redirect_unknown"


async def test_exact_multipart_legacy_compatibility_and_finite_size(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    transport, fake = _real_transport_fake(monkeypatch, "response")
    await transport.send_photo(token=SecretStr(TOKEN), chat_id=-100, photo=_png(), caption="<b>x</b>", timeout_s=1)
    assert fake.fields == ["chat_id", "photo", "caption", "parse_mode"]
    assert fake.field_details == [
        ("chat_id", ("-100",), {}),
        (
            "photo",
            (_png(),),
            {"filename": "report.png", "content_type": "image/png"},
        ),
        ("caption", ("<b>x</b>",), {}),
        ("parse_mode", ("HTML",), {}),
    ]
    assert fake.post_kwargs["allow_redirects"] is False
    assert fake.url_shape_ok is True
    assert TOKEN not in repr(fake.__dict__)
    assert all(TOKEN not in record.getMessage() for record in caplog.records)


def test_real_aiohttp_formdata_has_finite_nonchunked_payload_mechanics() -> None:
    aiohttp = importlib.import_module("aiohttp")
    photo = _png()
    caption = "<b>x</b>"
    form = aiohttp.FormData()
    form.add_field("chat_id", "-100")
    form.add_field("photo", photo, filename="report.png", content_type="image/png")
    form.add_field("caption", caption)
    form.add_field("parse_mode", "HTML")

    assert type(photo) is bytes
    assert [field[0]["name"] for field in form._fields] == [
        "chat_id",
        "photo",
        "caption",
        "parse_mode",
    ]
    payload = form()
    minimum = len(photo) + len(caption.encode("utf-8"))
    assert type(payload.size) is int
    assert minimum <= payload.size <= minimum + 16 * 1024
    assert len(payload._parts) == 4
    assert payload.headers.get("Transfer-Encoding") is None


def test_client_exposes_only_outbound_send_photo_surface() -> None:
    public = {name for name in dir(PeriodicTelegramClient) if not name.startswith("_")}
    assert public == {"send_photo", "close"}


async def test_token_absent_from_attrs_repr_results_and_raw_logs(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        result, client, _ = await _send(_CompleteHttpResponse(500, b"bad"))
    assert TOKEN not in repr(client) and TOKEN not in repr(result)
    assert all(TOKEN not in record.getMessage() for record in caplog.records)


async def test_tls_verified_default_and_false_warning_and_connector(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert _config().telegram_verify_ssl is True
    with caplog.at_level(logging.WARNING):
        client = PeriodicTelegramClient(_config(telegram_verify_ssl=False))
    fake = _FakeAiohttp("response", 1_000)
    monkeypatch.setattr(module, "_load_aiohttp", lambda: fake)
    result = await client.send_photo(_png(), "x")
    await client.close()
    assert result.outcome is TelegramOutcome.ACCEPTED
    assert fake.connector_kwargs == {"ssl": False, "limit": 1, "limit_per_host": 1}
    assert any("SSL" in record.getMessage() for record in caplog.records)
    assert all(TOKEN not in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize("photo", [bytearray(_png()), b"x" * 32, b"x" * (10 * 1024 * 1024 + 1)])
async def test_png_size_boundaries_and_mutable_input_rejected(photo: object) -> None:
    transport = ScriptedTransport(_accepted())
    client = PeriodicTelegramClient(_config(), _transport=transport)
    result = await client.send_photo(photo, "x")  # type: ignore[arg-type]
    assert result.error_code == "invalid_photo" and not transport.calls


@pytest.mark.parametrize(
    "mutation",
    ["crc", "trailing", "duplicate_ihdr", "missing_ihdr", "missing_idat", "missing_iend", "truncated"],
)
async def test_png_complete_chunk_crc_and_terminal_structure(mutation: str) -> None:
    raw = _png()
    if mutation == "crc":
        data = bytearray(raw)
        data[45] ^= 1
        raw = bytes(data)
    elif mutation == "trailing":
        raw += b"x"
    elif mutation == "duplicate_ihdr":
        raw = raw[:33] + raw[8:33] + raw[33:]
    elif mutation == "missing_ihdr":
        raw = raw[:8] + raw[33:]
    elif mutation == "missing_idat":
        raw = raw[:33] + _chunk(b"IEND", b"")
    elif mutation == "missing_iend":
        raw = raw[:-12]
    else:
        raw = raw[:-1]
    client = PeriodicTelegramClient(_config(), _transport=ScriptedTransport(_accepted()))
    assert (await client.send_photo(raw, "x")).error_code == "invalid_photo"


@pytest.mark.parametrize("dims", [(99, 100), (5000, 5001), (2100, 100)])
async def test_png_dimension_sum_pixel_and_aspect_boundaries(dims: tuple[int, int]) -> None:
    client = PeriodicTelegramClient(_config(), _transport=ScriptedTransport(_accepted()))
    assert (await client.send_photo(_png(*dims), "x")).error_code == "invalid_photo"


@pytest.mark.parametrize("caption", ["", "x\x00", "<i>x</i>", "x" * 1025])
async def test_caption_nonempty_codepoint_byte_markup_and_control_boundaries(caption: str) -> None:
    transport = ScriptedTransport(_accepted())
    client = PeriodicTelegramClient(_config(), _transport=transport)
    assert (await client.send_photo(_png(), caption)).error_code == "invalid_caption"
    assert not transport.calls


async def test_caption_exact_codepoint_and_utf8_byte_boundaries_are_allowed() -> None:
    client = PeriodicTelegramClient(_config(), _transport=ScriptedTransport(_accepted()))
    result = await client.send_photo(_png(), "😀" * 1_024)
    assert result.outcome is TelegramOutcome.ACCEPTED


async def test_invalid_input_creates_no_session_or_request() -> None:
    transport = ScriptedTransport(_accepted())
    client = PeriodicTelegramClient(_config(), _transport=transport)
    await client.send_photo(b"bad", "x")
    assert not transport.calls


@pytest.mark.parametrize("payload_size", [None, len(_png()) + 1 + 16 * 1024 + 1])
async def test_unknown_or_oversized_materialized_multipart_size_is_not_sent(
    monkeypatch: pytest.MonkeyPatch,
    payload_size: int | None,
) -> None:
    transport, fake = _real_transport_fake(monkeypatch, "response", payload_size=payload_size)
    result = await transport.send_photo(token=SecretStr(TOKEN), chat_id=-1, photo=_png(), caption="x", timeout_s=1)
    assert result.error_code == "invalid_request" and fake.posts == 0


async def test_checked_multipart_payload_is_the_same_object_posted(monkeypatch: pytest.MonkeyPatch) -> None:
    transport, fake = _real_transport_fake(monkeypatch, "response")
    await transport.send_photo(token=SecretStr(TOKEN), chat_id=-1, photo=_png(), caption="x", timeout_s=1)
    assert fake.post_kwargs["data"] is fake.payload


class _Content:
    def __init__(self, chunks: list[bytes], failure: BaseException | None = None) -> None:
        self.chunks, self.failure = chunks, failure

    async def iter_chunked(self, _size: int):
        for chunk in self.chunks:
            yield chunk
        if self.failure:
            raise self.failure


class _Response:
    def __init__(self, status=200, chunks=None, encoding=None, length=None, failure=None):
        self.status = status
        self.content = _Content(chunks or [], failure)
        self.content_length = length
        self.headers = _Headers(encoding)


class _Headers:
    def __init__(self, encoding):
        self.encoding = encoding

    def getall(self, _key, default):
        if self.encoding is None:
            return default
        return self.encoding if isinstance(self.encoding, list) else [self.encoding]


async def test_response_body_65536_allowed_and_65537_unknown() -> None:
    good = await _read_response(_Response(200, [b"x" * 65536]))
    bad = await _read_response(_Response(200, [b"x" * 65537]))
    assert isinstance(good, _CompleteHttpResponse) and bad.outcome is TelegramOutcome.UNKNOWN


async def test_chunked_body_overflow_stops_without_unbounded_read() -> None:
    result = await _read_response(_Response(200, [b"x" * 40000, b"x" * 30000]))
    assert result.outcome is TelegramOutcome.UNKNOWN


async def test_nonidentity_encoding_and_oversized_content_length_are_unknown() -> None:
    identity = await _read_response(_Response(200, [b"{}"], encoding="IdEnTiTy", length=2))
    assert isinstance(identity, _CompleteHttpResponse)
    for response in (
        _Response(200, encoding="gzip"),
        _Response(200, encoding=["identity", "identity"]),
        _Response(200, length=65_537),
        _Response(200, length=True),
        _Response(200, length=-1),
        _Response(200, length="1"),
        _Response(True),
    ):
        assert (await _read_response(response)).outcome is TelegramOutcome.UNKNOWN

    redirect = await _read_response(_Response(307, encoding="gzip"))
    assert redirect.error_code == "telegram_redirect_unknown"


def test_json_depth_16_allowed_and_17_unknown() -> None:
    _check_json_depth("[" * 16 + "0" + "]" * 16)
    with pytest.raises(ValueError, match="too deep"):
        _check_json_depth("[" * 17 + "0" + "]" * 17)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"ok":true,"ok":false}',
        b'{"ok":true,"result":{"message_id":1,"message_id":2,"chat":{"id":-100123}}}',
        b'{"ok":NaN}',
        b'{"ok":false,"x":9223372036854775808}',
        b"\xff",
    ],
)
def test_duplicate_keys_invalid_utf8_nonfinite_and_huge_integer_are_unknown(raw: bytes) -> None:
    assert _classify_response(_CompleteHttpResponse(200, raw), -1).outcome is TelegramOutcome.UNKNOWN


async def test_response_reader_timeout_disconnect_payload_and_oserror_are_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for failure in (
        "response_timeout",
        "response_client",
        "response_client_oserror",
        "response_client_connection",
        "response_server_connection",
        "response_payload",
        "response_connector",
        "response_oserror",
        "response_cancel",
    ):
        transport, _ = _real_transport_fake(monkeypatch, failure)
        result = await transport.send_photo(
            token=SecretStr(TOKEN),
            chat_id=-1,
            photo=_png(),
            caption="x",
            timeout_s=1,
        )
        assert result.outcome is TelegramOutcome.UNKNOWN


async def test_second_send_returns_busy_without_validation_form_or_transport() -> None:
    transport = ScriptedTransport(_accepted())
    transport.gate = asyncio.Event()
    client = PeriodicTelegramClient(_config(), _transport=transport)
    first = asyncio.create_task(client.send_photo(_png(), "x"))
    await asyncio.sleep(0)
    second = await client.send_photo(b"bad", "")
    assert second.error_code == "client_busy" and len(transport.calls) == 1
    transport.gate.set()
    await first


async def test_close_waits_for_completion_future_then_closes_once() -> None:
    transport = ScriptedTransport(_accepted())
    transport.gate = asyncio.Event()
    client = PeriodicTelegramClient(_config(), _transport=transport)
    send = asyncio.create_task(client.send_photo(_png(), "x"))
    await asyncio.sleep(0)
    close = asyncio.create_task(client.close())
    await asyncio.sleep(0)
    assert not close.done()
    transport.gate.set()
    await send
    await close
    assert transport.close_calls == 1


async def test_cancelled_send_resolves_completion_and_cannot_poison_close() -> None:
    transport = ScriptedTransport(_accepted())
    transport.gate = asyncio.Event()
    client = PeriodicTelegramClient(_config(), _transport=transport)
    send = asyncio.create_task(client.send_photo(_png(), "x"))
    await asyncio.sleep(0)
    send.cancel()
    with pytest.raises(asyncio.CancelledError):
        await send
    await client.close()
    assert transport.close_calls == 1


async def test_pre_invocation_cancellation_propagates_and_releases_client_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def cancel_before_session() -> object:
        raise asyncio.CancelledError

    monkeypatch.setattr(module, "_load_aiohttp", cancel_before_session)
    client = PeriodicTelegramClient(_config())
    with pytest.raises(asyncio.CancelledError):
        await client.send_photo(_png(), "x")
    assert client._send_active is False
    await client.close()


async def test_process_level_baseexception_propagates_after_claim_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ProcessAbort(BaseException):
        pass

    def abort_before_session() -> object:
        raise ProcessAbort

    monkeypatch.setattr(module, "_load_aiohttp", abort_before_session)
    client = PeriodicTelegramClient(_config())
    with pytest.raises(ProcessAbort):
        await client.send_photo(_png(), "x")
    assert client._send_active is False
    await client.close()


async def test_cancelled_close_caller_does_not_cancel_shared_cleanup() -> None:
    transport = ScriptedTransport(_accepted())
    transport.gate = asyncio.Event()
    client = PeriodicTelegramClient(_config(), _transport=transport)
    send = asyncio.create_task(client.send_photo(_png(), "x"))
    await asyncio.sleep(0)
    close = asyncio.create_task(client.close())
    await asyncio.sleep(0)
    close.cancel()
    with pytest.raises(asyncio.CancelledError):
        await close
    transport.gate.set()
    await send
    await client.close()
    assert transport.close_calls == 1


async def test_concurrent_and_later_close_reuse_one_close_task() -> None:
    transport = ScriptedTransport(_accepted())
    client = PeriodicTelegramClient(_config(), _transport=transport)
    await asyncio.gather(client.close(), client.close())
    await client.close()
    assert transport.close_calls == 1


async def test_send_after_or_during_close_never_reopens() -> None:
    transport = ScriptedTransport(_accepted())
    client = PeriodicTelegramClient(_config(), _transport=transport)
    await client.close()
    assert (await client.send_photo(_png(), "x")).error_code == "client_closed"


async def test_close_from_active_send_is_rejected_without_deadlock() -> None:
    transport = ScriptedTransport(_accepted())
    client = PeriodicTelegramClient(_config(), _transport=transport)
    client._send_active = True
    client._active_task = asyncio.current_task()
    with pytest.raises(RuntimeError):
        await client.close()


async def test_client_rejects_cross_event_loop_reuse_before_resources() -> None:
    transport = ScriptedTransport(_accepted())
    client = PeriodicTelegramClient(_config(), _transport=transport)
    foreign_loop = asyncio.new_event_loop()
    client._loop = foreign_loop
    try:
        with pytest.raises(RuntimeError, match="another event loop"):
            await client.send_photo(_png(), "x")
    finally:
        foreign_loop.close()
    assert not transport.calls


async def test_session_lazy_reused_dummy_cookie_no_proxy_and_idempotent_transport_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, fake = _real_transport_fake(monkeypatch, "response")
    assert transport._session is None
    kwargs = dict(token=SecretStr(TOKEN), chat_id=-1, photo=_png(), caption="x", timeout_s=1)
    await transport.send_photo(**kwargs)
    await transport.send_photo(**kwargs)
    await transport.close()
    await transport.close()
    assert fake.sessions == 1 and fake.close_calls == 1 and fake.session_kwargs["trust_env"] is False
    assert fake.session_kwargs["cookie_jar"] == "dummy"
    assert fake.session_kwargs["timeout"] == {"total": 1, "connect": 1, "sock_connect": 1, "sock_read": 1}
    assert fake.session_kwargs["raise_for_status"] is False
    assert fake.session_kwargs["auto_decompress"] is False
    assert fake.session_kwargs["headers"] == {"Accept": "application/json", "Accept-Encoding": "identity"}


async def test_partial_connector_is_closed_when_session_construction_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    transport, fake = _real_transport_fake(monkeypatch, "session_failure")
    result = await transport.send_photo(
        token=SecretStr(TOKEN),
        chat_id=-1,
        photo=_png(),
        caption="x",
        timeout_s=1,
    )
    assert result.error_code == "invalid_request"
    assert fake.connector_closed == 1


def test_module_import_does_not_load_aiohttp_or_forbidden_surfaces() -> None:
    code = (
        "import sys; import cryodaq.agents.assistant.periodic_telegram; "
        "assert 'aiohttp' not in sys.modules; "
        "assert 'matplotlib' not in sys.modules; "
        "assert 'cryodaq.engine' not in sys.modules"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


class _Payload:
    def __init__(self, size):
        self.size = size


class _Form:
    def __init__(self, fake):
        self.fake = fake

    def add_field(self, name, *_args, **_kwargs):
        self.fake.fields.append(name)
        self.fake.field_details.append((name, _args, _kwargs))

    def __call__(self):
        return self.fake.payload


class _RequestCM:
    def __init__(self, fake):
        self.fake = fake

    async def __aenter__(self):
        if self.fake.failure == "connector":
            raise self.fake.ClientConnectorError()
        if self.fake.failure == "connector_dns":
            raise self.fake.ClientConnectorDNSError()
        if self.fake.failure == "connector_tls":
            raise self.fake.ClientConnectorCertificateError()
        if self.fake.failure == "client":
            raise self.fake.ClientError()
        if self.fake.failure == "client_oserror":
            raise self.fake.ClientOSError()
        if self.fake.failure == "client_connection":
            raise self.fake.ClientConnectionError()
        if self.fake.failure == "server_connection":
            raise self.fake.ServerConnectionError()
        if self.fake.failure == "payload":
            raise self.fake.ClientPayloadError()
        if self.fake.failure == "oserror":
            raise OSError("reset")
        if self.fake.failure == "timeout":
            raise TimeoutError()
        if self.fake.failure == "cancel":
            raise asyncio.CancelledError()
        if self.fake.failure == "ordinary":
            raise RuntimeError("unexpected")
        failure: BaseException | None = None
        if self.fake.failure == "response_timeout":
            failure = TimeoutError()
        elif self.fake.failure == "response_client":
            failure = self.fake.ClientError()
        elif self.fake.failure == "response_client_oserror":
            failure = self.fake.ClientOSError()
        elif self.fake.failure == "response_client_connection":
            failure = self.fake.ClientConnectionError()
        elif self.fake.failure == "response_server_connection":
            failure = self.fake.ServerConnectionError()
        elif self.fake.failure == "response_payload":
            failure = self.fake.ClientPayloadError()
        elif self.fake.failure == "response_connector":
            failure = self.fake.ClientConnectorError()
        elif self.fake.failure == "response_oserror":
            failure = OSError("reset")
        elif self.fake.failure == "response_cancel":
            failure = asyncio.CancelledError()
        return _Response(200, [_accepted().body], failure=failure)

    async def __aexit__(self, *_args):
        return False


class _Session:
    def __init__(self, fake):
        self.fake = fake
        self.closed = False

    def post(self, url, **kwargs):
        self.fake.posts += 1
        self.fake.url_shape_ok = url.endswith(f"/bot{TOKEN}/sendPhoto")
        self.fake.post_kwargs = kwargs
        return _RequestCM(self.fake)

    async def close(self):
        self.closed = True
        self.fake.close_calls += 1


class _FakeAiohttp:
    class ClientError(Exception):
        pass

    class ClientConnectorError(ClientError):
        pass

    class ClientConnectorDNSError(ClientConnectorError):
        pass

    class ClientConnectorCertificateError(ClientConnectorError):
        pass

    class ClientOSError(ClientError):
        pass

    class ClientConnectionError(ClientError):
        pass

    class ServerConnectionError(ClientConnectionError):
        pass

    class ClientPayloadError(ClientError):
        pass

    def __init__(self, failure, payload_size):
        self.failure = failure
        self.payload = _Payload(payload_size)
        self.fields = []
        self.field_details = []
        self.posts = 0
        self.sessions = 0
        self.close_calls = 0
        self.connector_closed = 0
        self.url_shape_ok = False
        self.post_kwargs = {}
        self.session_kwargs = {}
        self.connector_kwargs = {}

    def TCPConnector(self, **kwargs):
        fake = self
        self.connector_kwargs = kwargs

        class Connector:
            def close(self):
                fake.connector_closed += 1

        return Connector()

    def ClientTimeout(self, **kwargs):
        return kwargs

    def DummyCookieJar(self):
        return "dummy"

    def FormData(self):
        return _Form(self)

    def ClientSession(self, **kwargs):
        if self.failure == "session_failure":
            raise RuntimeError("session")
        self.sessions += 1
        self.session_kwargs = kwargs
        return _Session(self)


def _real_transport_fake(monkeypatch, failure, payload_size=1000):
    fake = _FakeAiohttp(failure, payload_size)
    monkeypatch.setattr(module, "_load_aiohttp", lambda: fake)
    return _AiohttpPeriodicTransport(True), fake
