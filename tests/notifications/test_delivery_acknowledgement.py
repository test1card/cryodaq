"""Delivery is claimed only when Telegram acknowledges a concrete message id.

OC-026. ``TelegramSender`` reported success from the HTTP layer alone:

* ``_send`` returned ``"delivered"`` for any ``ok: true`` body, even one carrying
  no ``result.message_id``;
* ``send_photo`` inspected only ``resp.status``, so a 200 whose body said
  ``ok: false`` passed silently and produced no record at all.

A 200 is evidence that the request arrived, not that a message exists. Claiming
delivery from it replaces a real outcome with a determined-looking one, which is
the false-authoritative-claim class this repository does not accept.

SCOPE, and why it shrank. The OC-026 entry also names
``notifications/periodic_report.py::_send_photo``. That module is DEAD on the
live path, and the repository enforces it: ``tests/core/test_periodic_legacy_cutover.py``
asserts the engine holds zero references to ``PeriodicReporter`` and
characterises the module as importable-but-dead. The live periodic chain is
``assistant/periodic_runtime.py`` -> ``assistant/periodic_telegram.py``, which
already implements the bounded, destination-bound acknowledgement contract. So
there is no production defect on that path to fix, and guarding the dead one
would have produced tests that can never protect a running system. The register
entry is what needs correcting, not the code.

This file therefore covers ``TelegramSender`` only, which IS live: ``launcher.py``
spawns ``python -m cryodaq.agents.assistant_bootstrap``, which imports
``assistant_main``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import pytest

import cryodaq.agents.assistant_main as assistant_main
from cryodaq.agents.assistant_main import TelegramSender


class _Headers:
    """Minimal case-insensitive multi-mapping mimicking ``CIMultiDictProxy.getall``."""

    def __init__(self, pairs: tuple[tuple[str, str], ...] = ()) -> None:
        self._pairs = pairs

    def getall(self, key: str, default: list[str] | None = None) -> list[str]:
        folded = key.casefold()
        matches = [value for name, value in self._pairs if name.casefold() == folded]
        return matches if matches else list(default or [])


class _Response:
    def __init__(
        self,
        status: int,
        payload: Any,
        *,
        content_length: Any = None,
        chunks: list[bytes] | None = None,
        headers: _Headers | None = None,
    ) -> None:
        self.status = status
        self._payload = payload
        self.content_length = content_length
        self.headers = headers if headers is not None else _Headers()
        self.content = _Content(payload, chunks=chunks)

    async def __aenter__(self) -> _Response:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def json(self) -> Any:
        raise AssertionError("TelegramSender must not use response.json()")

    async def text(self) -> str:
        raise AssertionError("TelegramSender must stream bounded response bodies")


class _Content:
    def __init__(self, payload: Any, *, chunks: list[bytes] | None = None) -> None:
        self._body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self._chunks = chunks
        self.consumed_chunks = 0
        self.consumed_bytes = 0

    async def iter_chunked(self, size: int):
        chunks = self._chunks
        if chunks is None:
            chunks = [self._body[offset : offset + size] for offset in range(0, len(self._body), size)]
        for chunk in chunks:
            self.consumed_chunks += 1
            self.consumed_bytes += len(chunk)
            yield chunk


class _StallingRequest:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def __aenter__(self):
        self.started.set()
        await self.release.wait()
        raise AssertionError("timed-out request entry resumed")

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _DribblingContent:
    def __init__(self) -> None:
        self.stalled = asyncio.Event()
        self.release = asyncio.Event()

    async def iter_chunked(self, _size: int):
        yield b'{"ok":true,"result":'
        self.stalled.set()
        await self.release.wait()
        raise AssertionError("timed-out response body resumed")


class _DribblingResponse(_Response):
    def __init__(self) -> None:
        super().__init__(200, b"")
        self.content = _DribblingContent()


class _Session:
    """Minimal stand-in for the aiohttp session the sender acquires."""

    def __init__(self, response: Any) -> None:
        self._response = response
        self.closed = False
        self.requests: list[str] = []

    def post(self, url: str, **_kwargs: object) -> _Response:
        self.requests.append(url)
        return self._response


def _sender(response: Any, monkeypatch: pytest.MonkeyPatch) -> tuple[TelegramSender, _Session]:
    sender = TelegramSender("token", [4242])
    session = _Session(response)

    async def _get_session() -> _Session:
        return session

    monkeypatch.setattr(sender, "_get_session", _get_session)
    return sender, session


def _acknowledged(message_id: int = 77) -> dict[str, Any]:
    return {"ok": True, "result": {"message_id": message_id, "chat": {"id": 4242}}}


MALFORMED_ACKNOWLEDGEMENTS = [
    pytest.param({"ok": True}, id="no-result-member"),
    pytest.param({"ok": True, "result": {}}, id="result-without-message-id"),
    pytest.param({"ok": True, "result": None}, id="null-result"),
    pytest.param({"ok": True, "result": "77"}, id="result-not-an-object"),
]
"""Structurally incomplete acknowledgements with a literal acceptance flag."""


INVALID_MESSAGE_ID_ACKNOWLEDGEMENTS = [
    pytest.param({"ok": True, "result": {"message_id": None, "chat": {"id": 4242}}}, id="null-message-id"),
    pytest.param({"ok": True, "result": {"message_id": "77", "chat": {"id": 4242}}}, id="message-id-not-an-integer"),
    pytest.param({"ok": True, "result": {"message_id": True, "chat": {"id": 4242}}}, id="message-id-is-a-bool"),
    pytest.param({"ok": True, "result": {"message_id": 0, "chat": {"id": 4242}}}, id="message-id-zero"),
    pytest.param({"ok": True, "result": {"message_id": -1, "chat": {"id": 4242}}}, id="message-id-negative"),
]
"""Otherwise-valid acknowledgements that never name a usable message.

These are the DEFINING case for OC-026 and are distinct from ``ok: false``. Both
outbound paths guard them separately from rejection, so a suite that only sends
``ok: false`` leaves the acknowledgement guard unexercised: it can be deleted and
every test still passes. That escape was real and is what these bodies close.

The range cases mirror the ``1..2**63-1`` bound the live client already enforces
in ``assistant/periodic_telegram.py``; two senders disagreeing about what counts
as an acknowledgement is itself a defect. ``message_id: True`` is included
because ``bool`` is an ``int`` subclass, so an ``isinstance`` check would read it
as message 1.
"""


INVALID_OK_ENVELOPES = [
    pytest.param({"result": {"message_id": 77, "chat": {"id": 4242}}}, id="missing-ok"),
    pytest.param({"ok": None, "result": {"message_id": 77, "chat": {"id": 4242}}}, id="null-ok"),
    pytest.param({"ok": 1, "result": {"message_id": 77, "chat": {"id": 4242}}}, id="integer-ok"),
    pytest.param({"ok": "true", "result": {"message_id": 77, "chat": {"id": 4242}}}, id="string-ok"),
]
"""Valid-looking message identifiers with invalid acknowledgement envelopes.

The message id is deliberately ``77`` in every case: only a literal Boolean
``ok: true`` may distinguish delivery from an unknown outcome.  Keeping these
cases on both real sender paths makes removal of the strict envelope guard fail
instead of silently broadening the definition of acknowledgement.
"""

INVALID_CHAT_ENVELOPES = [
    pytest.param({"ok": True, "result": {"message_id": 77}}, id="no-chat-named"),
    pytest.param(
        {"ok": True, "result": {"message_id": 77, "chat": {"id": 9999}}},
        id="chat-is-a-different-chat",
    ),
    pytest.param(
        {"ok": True, "result": {"message_id": 77, "chat": {"id": "4242"}}},
        id="chat-id-is-a-string",
    ),
]
"""Otherwise-valid acknowledgements that do not bind the requested chat."""


INVALID_ACKNOWLEDGEMENTS = (
    MALFORMED_ACKNOWLEDGEMENTS + INVALID_MESSAGE_ID_ACKNOWLEDGEMENTS + INVALID_OK_ENVELOPES + INVALID_CHAT_ENVELOPES
)


def _padded_acknowledgement(size: int) -> bytes:
    encoded = json.dumps(_acknowledged(), separators=(",", ":")).encode()
    assert len(encoded) <= size
    return encoded + b" " * (size - len(encoded))


EXACT_AMBIGUOUS_ACKNOWLEDGEMENTS = [
    pytest.param(
        b'{"ok":false,"ok":true,"result":{"message_id":77,"chat":{"id":4242}}}',
        id="duplicate-ok",
    ),
    pytest.param(
        b'{"ok":true,"result":{"message_id":77,"chat":{"id":4242}},"ignored":NaN}',
        id="nan",
    ),
]
"""Bodies that plain ``json.loads`` accepts as otherwise valid delivery proof."""


NESTED_DUPLICATE_AUTHORITY_ACKNOWLEDGEMENTS = [
    pytest.param(
        b'{"ok":true,"result":{"message_id":0,"chat":{"id":9999}},"result":{"message_id":77,"chat":{"id":4242}}}',
        id="duplicate-result",
    ),
    pytest.param(
        b'{"ok":true,"result":{"message_id":0,"message_id":77,"chat":{"id":4242}}}',
        id="duplicate-message-id",
    ),
    pytest.param(
        b'{"ok":true,"result":{"message_id":77,"chat":{"id":9999},"chat":{"id":4242}}}',
        id="duplicate-chat",
    ),
    pytest.param(
        b'{"ok":true,"result":{"message_id":77,"chat":{"id":9999,"id":4242}}}',
        id="duplicate-chat-id",
    ),
    pytest.param(
        b'{"ok":true,"result":{"message_id":0,"message_id":77,"chat":{"id":9999,"id":4242}}}',
        id="duplicate-message-id-and-chat-id-exploit",
    ),
]
"""Nested authority collisions whose superficially valid value appears last."""


STRICTLY_INVALID_ACKNOWLEDGEMENTS = [
    pytest.param(
        b'{"ok":true,"result":{"message_id":77,"chat":{"id":4242}},"ignored":Infinity}',
        id="positive-infinity",
    ),
    pytest.param(
        b'{"ok":true,"result":{"message_id":77,"chat":{"id":4242}},"ignored":-Infinity}',
        id="negative-infinity",
    ),
    pytest.param(
        b'{"ok":true,"result":{"message_id":77,"chat":{"id":4242}},"ignored":9223372036854775808}',
        id="integer-out-of-range",
    ),
    pytest.param(
        b'{"ok":true,"result":{"message_id":9223372036854775808,"chat":{"id":4242}}}',
        id="message-id-out-of-json-range",
    ),
    pytest.param(
        b'{"ok":true,"result":{"message_id":77,"chat":{"id":4242}},"ignored":1e309}',
        id="overflowing-float",
    ),
    pytest.param(
        b'{"ok":true,"result":{"message_id":77,"chat":{"id":4242}},"ignored":' + b"1." + b"0" * 63 + b"}",
        id="oversized-float-form",
    ),
    pytest.param(
        b'{"ok":true,"result":{"message_id":77,"chat":{"id":4242}},"ignored":' + b"[" * 16 + b"0" + b"]" * 16 + b"}",
        id="excessive-nesting",
    ),
    pytest.param(
        b'{"ok":true,"result":{"message_id":77,"chat":{"id":4242}},"ignored":"\xff"}',
        id="invalid-utf8",
    ),
]
"""Periodic-Telegram strict JSON rejects these before acknowledgement use."""


async def test_send_reports_service_delivered_when_a_message_id_is_acknowledged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender, session = _sender(_Response(200, _acknowledged()), monkeypatch)

    assert await sender._send(4242, "text") == "service_reported_delivered"
    assert session.requests == ["https://api.telegram.org/bottoken/sendMessage"]


@pytest.mark.parametrize("payload", INVALID_ACKNOWLEDGEMENTS)
async def test_send_refuses_to_claim_delivery_without_an_acknowledged_message_id(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]
) -> None:
    """``ok: true`` alone is the API saying it read the request, not that a message exists."""

    sender, _session = _sender(_Response(200, payload), monkeypatch)

    assert await sender._send(4242, "text") == "outcome_unknown"


async def test_send_treats_a_200_false_acknowledgement_as_an_unknown_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 200 response contradicting itself does not prove rejection or delivery."""

    sender, _session = _sender(_Response(200, {"ok": False, "description": "chat not found"}), monkeypatch)

    assert await sender._send(4242, "text") == "outcome_unknown"


@pytest.mark.parametrize("payload", [None, [], "ok", 1], ids=["null", "array", "string", "integer"])
async def test_send_treats_a_non_object_acknowledgement_as_exact_unknown(
    monkeypatch: pytest.MonkeyPatch, payload: Any
) -> None:
    sender, _session = _sender(_Response(200, payload), monkeypatch)

    assert await sender._send(4242, "text") == "outcome_unknown"


async def test_send_treats_an_unparseable_body_as_exact_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender, _session = _sender(_Response(200, b"not JSON"), monkeypatch)

    assert await sender._send(4242, "text") == "outcome_unknown"


@pytest.mark.parametrize("sender_method", ["sendMessage", "sendPhoto"])
async def test_both_sender_paths_bound_the_entire_acknowledgement_operation(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    sender_method: str,
) -> None:
    request = _StallingRequest()
    sender, session = _sender(request, monkeypatch)
    monkeypatch.setattr(assistant_main, "_TELEGRAM_ACKNOWLEDGEMENT_TIMEOUT_S", 0.01)

    operation = (
        sender._send(4242, "text")
        if sender_method == "sendMessage"
        else sender.send_photo(4242, b"png-bytes", "caption")
    )
    task = asyncio.create_task(operation)
    try:
        with caplog.at_level(logging.ERROR):
            done, _pending = await asyncio.wait({task}, timeout=0.2)
        assert task in done, f"{sender_method} acknowledgement read exceeded its deadline"
        send_outcome = await task
    finally:
        request.release.set()
        await asyncio.gather(task, return_exceptions=True)

    if sender_method == "sendMessage":
        assert send_outcome == "outcome_unknown"
    else:
        assert send_outcome is None
    assert session.requests == [f"https://api.telegram.org/bottoken/{sender_method}"]
    messages = [record.getMessage() for record in caplog.records]
    assert any(f"{sender_method} acknowledgement timed out; outcome unknown" in message for message in messages)


@pytest.mark.parametrize("sender_method", ["sendMessage", "sendPhoto"])
async def test_both_sender_paths_bound_a_dribbling_200_acknowledgement_body(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    sender_method: str,
) -> None:
    response = _DribblingResponse()
    sender, session = _sender(response, monkeypatch)
    monkeypatch.setattr(assistant_main, "_TELEGRAM_ACKNOWLEDGEMENT_TIMEOUT_S", 0.01)

    operation = (
        sender._send(4242, "text")
        if sender_method == "sendMessage"
        else sender.send_photo(4242, b"png-bytes", "caption")
    )
    task = asyncio.create_task(operation)
    try:
        await asyncio.wait_for(response.content.stalled.wait(), timeout=0.2)
        with caplog.at_level(logging.ERROR):
            done, _pending = await asyncio.wait({task}, timeout=0.2)
        assert task in done, f"{sender_method} stalled 200 body exceeded its deadline"
        send_outcome = await task
    finally:
        response.content.release.set()
        await asyncio.gather(task, return_exceptions=True)

    if sender_method == "sendMessage":
        assert send_outcome == "outcome_unknown"
    else:
        assert send_outcome is None
    assert session.requests == [f"https://api.telegram.org/bottoken/{sender_method}"]
    messages = [record.getMessage() for record in caplog.records]
    assert any(f"{sender_method} acknowledgement timed out; outcome unknown" in message for message in messages)


@pytest.mark.parametrize("body", EXACT_AMBIGUOUS_ACKNOWLEDGEMENTS)
async def test_both_sender_paths_reject_duplicate_and_nan_acknowledgements(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    body: bytes,
) -> None:
    """The exact plain-``json.loads`` escape is unknown on both live paths."""

    sender, _session = _sender(_Response(200, body), monkeypatch)

    with caplog.at_level(logging.ERROR):
        send_outcome = await sender._send(4242, "text")
        await sender.send_photo(4242, b"png-bytes", "caption")

    messages = [record.getMessage() for record in caplog.records]
    failures = []
    if send_outcome != "outcome_unknown":
        failures.append(f"sendMessage settled {send_outcome!r}")
    if not any("sendMessage 200 with unparseable response" in message for message in messages):
        failures.append("sendMessage did not record strict parse failure")
    if not any("sendPhoto 200 with unparseable response" in message for message in messages):
        failures.append("sendPhoto passed without recording strict parse failure")
    assert not failures, failures


@pytest.mark.parametrize("body", NESTED_DUPLICATE_AUTHORITY_ACKNOWLEDGEMENTS)
async def test_both_sender_paths_reject_nested_duplicate_authority_keys(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    body: bytes,
) -> None:
    """Reject nested last-key-wins delivery evidence on both production senders."""

    sender, _session = _sender(_Response(200, body), monkeypatch)

    with caplog.at_level(logging.ERROR):
        send_outcome = await sender._send(4242, "text")
        await sender.send_photo(4242, b"png-bytes", "caption")

    messages = [record.getMessage() for record in caplog.records]
    failures = []
    if send_outcome != "outcome_unknown":
        failures.append(f"sendMessage settled {send_outcome!r}")
    if not any("sendMessage 200 with unparseable response" in message for message in messages):
        failures.append("sendMessage accepted nested duplicate authority")
    if not any("sendPhoto 200 with unparseable response" in message for message in messages):
        failures.append("sendPhoto accepted nested duplicate authority")
    assert not failures, failures


@pytest.mark.parametrize("body", STRICTLY_INVALID_ACKNOWLEDGEMENTS)
async def test_both_sender_paths_match_periodic_strict_json_rejections(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    body: bytes,
) -> None:
    """Unused hostile members cannot ride beside otherwise valid delivery proof."""

    sender, _session = _sender(_Response(200, body), monkeypatch)

    with caplog.at_level(logging.ERROR):
        send_outcome = await sender._send(4242, "text")
        await sender.send_photo(4242, b"png-bytes", "caption")

    messages = [record.getMessage() for record in caplog.records]
    assert send_outcome == "outcome_unknown"
    assert any("sendMessage 200 with unparseable response" in message for message in messages), messages
    assert any("sendPhoto 200 with unparseable response" in message for message in messages), messages


@pytest.mark.parametrize("encoding", ["gzip", "deflate", "br", "x-bzip2"], ids=["gzip", "deflate", "brotli", "bzip2"])
@pytest.mark.parametrize("sender_method", ["sendMessage", "sendPhoto"])
async def test_both_sender_paths_reject_non_identity_content_encoding_before_reading(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    sender_method: str,
    encoding: str,
) -> None:
    """A compressed envelope can expand past the byte cap before chunked reading.

    With ``auto_decompress=False`` the transport never inflates it, and the
    encoding is rejected before any body byte is buffered. This mirrors the live
    periodic adapter and makes the advertised 64 KiB bound real rather than a
    layer that a compressed ``Content-Length`` silently bypasses.
    """

    response = _Response(200, _acknowledged(), headers=_Headers((("Content-Encoding", encoding),)))
    sender, _session = _sender(response, monkeypatch)

    with caplog.at_level(logging.ERROR):
        outcome = (
            await sender._send(4242, "text")
            if sender_method == "sendMessage"
            else await sender.send_photo(4242, b"png-bytes", "caption")
        )

    if sender_method == "sendMessage":
        assert outcome == "outcome_unknown"
    else:
        assert outcome is None
    assert response.content.consumed_chunks == 0, "compressed body must not be buffered"
    messages = [record.getMessage() for record in caplog.records]
    assert any("non-identity Content-Encoding" in message for message in messages), messages


async def test_send_photo_records_a_200_false_acknowledgement_as_unknown(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A 200 whose body says ``ok: false`` is a contradictory unknown outcome."""

    sender, _session = _sender(_Response(200, {"ok": False, "description": "chat not found"}), monkeypatch)

    with caplog.at_level(logging.ERROR):
        await sender.send_photo(4242, b"png-bytes", "caption")

    messages = [record.getMessage() for record in caplog.records]
    assert any("sendPhoto 200 contradictory/unknown" in message for message in messages), messages
    assert not any("sendPhoto rejected" in message for message in messages), messages
    assert any("chat not found" in message for message in messages), messages


@pytest.mark.parametrize("payload", INVALID_ACKNOWLEDGEMENTS)
async def test_send_photo_refuses_to_report_success_without_an_acknowledged_message_id(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, payload: dict[str, Any]
) -> None:
    """``ok: true`` with no usable message id must not pass sendPhoto silently."""

    sender, _session = _sender(_Response(200, payload), monkeypatch)

    with caplog.at_level(logging.ERROR):
        await sender.send_photo(4242, b"png-bytes", "caption")

    messages = [record.getMessage() for record in caplog.records]
    assert any("without an acknowledged message id" in message for message in messages), messages


async def test_send_photo_is_quiet_when_a_message_id_is_acknowledged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Positive control: the acknowledged path must not become noisy.

    Without it, every refusal test above is satisfied by a sender that reports an
    error unconditionally.
    """

    sender, _session = _sender(_Response(200, _acknowledged(91)), monkeypatch)

    with caplog.at_level(logging.ERROR):
        await sender.send_photo(4242, b"png-bytes", "caption")

    assert not caplog.records, [record.getMessage() for record in caplog.records]


async def test_send_photo_records_an_unparseable_body(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A 200 that is not JSON is an unknown outcome, not a delivery."""

    sender, _session = _sender(_Response(200, b"not JSON"), monkeypatch)

    with caplog.at_level(logging.ERROR):
        await sender.send_photo(4242, b"png-bytes", "caption")

    messages = [record.getMessage() for record in caplog.records]
    assert any("unparseable" in message for message in messages), messages


@pytest.mark.parametrize(
    ("body_size", "expected"),
    [
        pytest.param(65_536, "delivered", id="exact-limit"),
        pytest.param(65_537, "outcome_unknown", id="one-byte-over"),
    ],
)
async def test_send_enforces_the_streamed_acknowledgement_boundary(
    monkeypatch: pytest.MonkeyPatch, body_size: int, expected: str
) -> None:
    response = _Response(200, _padded_acknowledgement(body_size))
    sender, _session = _sender(response, monkeypatch)

    assert await sender._send(4242, "text") == expected


@pytest.mark.parametrize("body_size", [65_536, 65_537], ids=["exact-limit", "one-byte-over"])
async def test_send_photo_enforces_the_streamed_acknowledgement_boundary(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    body_size: int,
) -> None:
    response = _Response(200, _padded_acknowledgement(body_size))
    sender, _session = _sender(response, monkeypatch)

    with caplog.at_level(logging.ERROR):
        await sender.send_photo(4242, b"png-bytes", "caption")

    messages = [record.getMessage() for record in caplog.records]
    if body_size == 65_536:
        assert not messages, messages
    else:
        assert any("unparseable" in message for message in messages), messages


@pytest.mark.parametrize(
    "content_length",
    [
        pytest.param(True, id="boolean"),
        pytest.param(-1, id="negative"),
        pytest.param(65_537, id="one-byte-over"),
        pytest.param("65536", id="non-integer"),
    ],
)
async def test_send_rejects_invalid_content_length_without_consuming_body(
    monkeypatch: pytest.MonkeyPatch, content_length: Any
) -> None:
    response = _Response(200, _acknowledged(), content_length=content_length)
    sender, _session = _sender(response, monkeypatch)

    assert await sender._send(4242, "text") == "outcome_unknown"
    assert response.content.consumed_chunks == 0
    assert response.content.consumed_bytes == 0


@pytest.mark.parametrize(
    "content_length",
    [
        pytest.param(True, id="boolean"),
        pytest.param(-1, id="negative"),
        pytest.param(65_537, id="one-byte-over"),
        pytest.param("65536", id="non-integer"),
    ],
)
async def test_send_photo_rejects_invalid_content_length_without_consuming_body(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    content_length: Any,
) -> None:
    response = _Response(200, _acknowledged(), content_length=content_length)
    sender, _session = _sender(response, monkeypatch)

    with caplog.at_level(logging.ERROR):
        await sender.send_photo(4242, b"png-bytes", "caption")

    assert response.content.consumed_chunks == 0
    assert response.content.consumed_bytes == 0
    messages = [record.getMessage() for record in caplog.records]
    assert any("unparseable" in message for message in messages), messages


async def test_send_stops_at_the_first_chunked_overflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chunks = [b" " * 65_536, b"x", b"must-not-be-consumed"]
    response = _Response(200, b"", chunks=chunks)
    sender, _session = _sender(response, monkeypatch)

    assert await sender._send(4242, "text") == "outcome_unknown"
    assert response.content.consumed_chunks == 2
    assert response.content.consumed_bytes == 65_537


async def test_send_photo_stops_at_the_first_chunked_overflow(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    chunks = [b" " * 65_536, b"x", b"must-not-be-consumed"]
    response = _Response(200, b"", chunks=chunks)
    sender, _session = _sender(response, monkeypatch)

    with caplog.at_level(logging.ERROR):
        await sender.send_photo(4242, b"png-bytes", "caption")

    assert response.content.consumed_chunks == 2
    assert response.content.consumed_bytes == 65_537
    messages = [record.getMessage() for record in caplog.records]
    assert any("unparseable" in message for message in messages), messages


@pytest.mark.parametrize(
    ("sender_method", "status", "expected_outcome", "log_prefix"),
    [
        pytest.param("sendMessage", 400, "failed", "Telegram sendMessage 400", id="message-client-error"),
        pytest.param("sendPhoto", 500, None, "Telegram sendPhoto 500", id="photo-server-error"),
    ],
)
async def test_non_200_response_diagnostics_are_bounded_and_streamed(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    sender_method: str,
    status: int,
    expected_outcome: str | None,
    log_prefix: str,
) -> None:
    """Failed endpoints cannot bypass the 64 KiB streamed response limit."""

    chunks = [b"error: " + b"x" * 65_529, b"y", b"must-not-be-consumed"]
    response = _Response(status, b"", chunks=chunks)
    sender, _session = _sender(response, monkeypatch)

    with caplog.at_level(logging.ERROR):
        outcome = (
            await sender._send(4242, "text")
            if sender_method == "sendMessage"
            else await sender.send_photo(4242, b"png-bytes", "caption")
        )

    assert outcome == expected_outcome
    assert response.content.consumed_chunks == 2
    assert response.content.consumed_bytes == 65_537
    messages = [record.getMessage() for record in caplog.records]
    assert any(log_prefix in message and "exceeds the 64 KiB limit" in message for message in messages), messages
