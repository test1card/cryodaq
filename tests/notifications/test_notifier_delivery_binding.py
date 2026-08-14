"""OC-026: the engine notifier must bind its delivery claim to the requested chat.

WHY THIS EXISTS. `TelegramNotifier` in `cryodaq.notifications.telegram` is live: the engine
constructs it at `src/cryodaq/engine.py:7113`. Before this change `send_message` returned
`service_reported_delivered` for any 200 carrying `ok: true` and an integer
`result.message_id`, without ever comparing `result.chat` to the destination it asked for.

A message id proves that SOME message was created. It does not prove the message reached the
operator. So an acknowledgement describing a message posted to a different chat was reported
as delivered -- for an alarm notifier, the worst available wrong answer, because it states
that the operator was told when they were not.

The sibling sender `cryodaq.agents.assistant_main._acknowledged_message_id` already bound the
chat and already accepted only `1..2**63-1`. Its own docstring says two senders disagreeing
about what counts as an acknowledgement is itself a defect. They disagreed until this change.

THESE TESTS DRIVE `send_message`, NOT A PRIVATE HELPER. An earlier draft asserted on the
helper directly; reverting production then removed the symbol and the suite failed to COLLECT,
which proves only that a name is referenced. This repository has shipped that defect twice --
a guard exercising the helper rather than the production path -- so the response is stubbed
and the public method's returned tier is the assertion.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from cryodaq.notifications.telegram import TelegramNotifier

MAX_JSON_INTEGER = 2**63 - 1
REQUESTED_CHAT = -1001234567890


class _Response:
    """The minimum of aiohttp's response that `send_message` actually uses.

    IT SERVES TEXT, NOT AN OBJECT, and that is load-bearing.  `send_message` decodes the body
    itself with a unique-key hook, so a stub returning an already-decoded dict would step over
    the decoder under test and every assertion below would be about a path production does not
    take.  `raw_text` exists because a duplicate key CANNOT be expressed as a Python dict -- by
    the time the body is a dict the ambiguity has already been resolved, silently, in favour of
    whichever pair came last.
    """

    def __init__(
        self,
        payload: Any = None,
        status: int = 200,
        raw_text: str | None = None,
        content_type: str = "application/json",
    ) -> None:
        self.status = status
        self.content_type = content_type
        self._text = raw_text if raw_text is not None else json.dumps(payload)

    async def __aenter__(self) -> _Response:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def text(self) -> str:
        return self._text


class _Session:
    def __init__(self, response: _Response) -> None:
        self._response = response
        self.closed = False

    def post(self, _url: str, **_kwargs: Any) -> _Response:
        return self._response


def _notifier(
    payload: Any,
    monkeypatch: pytest.MonkeyPatch,
    *,
    raw_text: str | None = None,
    content_type: str = "application/json",
) -> TelegramNotifier:
    notifier = TelegramNotifier(bot_token="token", chat_id=REQUESTED_CHAT)
    session = _Session(_Response(payload, raw_text=raw_text, content_type=content_type))

    async def _stub_session(self: TelegramNotifier) -> _Session:
        return session

    monkeypatch.setattr(TelegramNotifier, "_get_session", _stub_session)
    return notifier


def _ack(message: Any) -> dict[str, Any]:
    return {"ok": True, "result": message}


async def test_a_well_formed_acknowledgement_for_the_wrong_chat_is_not_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """This is the finding itself, not a boundary case.

    Everything about this body is valid except the destination.
    """
    notifier = _notifier(
        _ack({"message_id": 12345, "chat": {"id": -1009999999999, "title": "Somebody else"}}), monkeypatch
    )

    assert await notifier.send_message(REQUESTED_CHAT, "alarm") == "transport_accepted"


async def test_an_acknowledgement_for_the_requested_chat_is_delivery(monkeypatch: pytest.MonkeyPatch) -> None:
    notifier = _notifier(_ack({"message_id": 7, "chat": {"id": REQUESTED_CHAT}}), monkeypatch)

    assert await notifier.send_message(REQUESTED_CHAT, "alarm") == "service_reported_delivered"


@pytest.mark.parametrize(
    ("message", "why"),
    [
        ({"message_id": 7}, "an acknowledgement naming no chat proves no destination"),
        ({"message_id": 7, "chat": None}, "a null chat is not a destination"),
        ({"message_id": True, "chat": {"id": REQUESTED_CHAT}}, "bool subclasses int; True is not message 1"),
        ({"message_id": 0, "chat": {"id": REQUESTED_CHAT}}, "message ids start at 1"),
        ({"message_id": -1, "chat": {"id": REQUESTED_CHAT}}, "a negative id is not a message"),
        (
            {"message_id": MAX_JSON_INTEGER + 1, "chat": {"id": REQUESTED_CHAT}},
            "beyond the 63-bit range the sibling sender accepts",
        ),
    ],
)
async def test_unprovable_acknowledgements_do_not_claim_delivery(
    monkeypatch: pytest.MonkeyPatch, message: Any, why: str
) -> None:
    notifier = _notifier(_ack(message), monkeypatch)

    assert await notifier.send_message(REQUESTED_CHAT, "alarm") == "transport_accepted", why


async def test_the_upper_bound_the_sibling_sender_accepts_is_accepted_here_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pins the agreement between the two senders at its exact edge."""
    notifier = _notifier(_ack({"message_id": MAX_JSON_INTEGER, "chat": {"id": REQUESTED_CHAT}}), monkeypatch)

    assert await notifier.send_message(REQUESTED_CHAT, "alarm") == "service_reported_delivered"


DUPLICATE_AUTHORITY_ACKNOWLEDGEMENTS = [
    pytest.param(
        f'{{"ok": false, "ok": true, "result": {{"message_id": 7, "chat": {{"id": {REQUESTED_CHAT}}}}}}}',
        id="duplicate-ok",
    ),
    pytest.param(
        f'{{"ok": true, "result": {{"message_id": 0, "chat": {{"id": 222}}}}, '
        f'"result": {{"message_id": 7, "chat": {{"id": {REQUESTED_CHAT}}}}}}}',
        id="duplicate-result",
    ),
    pytest.param(
        f'{{"ok": true, "result": {{"message_id": 0, "message_id": 7, "chat": {{"id": {REQUESTED_CHAT}}}}}}}',
        id="duplicate-message-id",
    ),
    pytest.param(
        f'{{"ok": true, "result": {{"message_id": 7, "chat": {{"id": 222}}, "chat": {{"id": {REQUESTED_CHAT}}}}}}}',
        id="duplicate-chat",
    ),
    pytest.param(
        f'{{"ok": true, "result": {{"message_id": 7, "chat": {{"id": 222, "id": {REQUESTED_CHAT}}}}}}}',
        id="duplicate-chat-id",
    ),
    pytest.param(
        f'{{"ok": true, "result": {{"message_id": 0, "message_id": 7, '
        f'"chat": {{"id": 222, "id": {REQUESTED_CHAT}}}}}}}',
        id="duplicate-message-id-and-chat-id-exploit",
    ),
]
"""Every authority position on this path, each one delivery-shaped under last-key-wins.

Drop the duplicate from any body here and it is a valid acknowledgement for `REQUESTED_CHAT`,
which is exactly what makes each one a false-green candidate rather than a malformed body.
The identifiers match `tests/notifications/test_delivery_acknowledgement.py`, which enumerates
the same class for the two sibling sender methods; naming them identically is deliberate, so
that a position covered there and missing here is visible by comparison.
"""


@pytest.mark.asyncio
@pytest.mark.parametrize("duplicated", DUPLICATE_AUTHORITY_ACKNOWLEDGEMENTS)
async def test_a_duplicate_authority_key_is_not_a_delivery_claim(
    monkeypatch: pytest.MonkeyPatch,
    duplicated: str,
) -> None:
    """An acknowledgement that names an authority key TWICE proves nothing about the delivery.

    `resp.json()` keeps the LAST value for a repeated key, so a body carrying
    `"chat": {"id": 222}, "chat": {"id": 111}` decodes to the requested chat and satisfies the
    destination check added for OC-026 -- while the acknowledgement itself is ambiguous.  The
    convenient reading won by default.

    THE PARAMETERS ARE THE POINT, not one instance of it.  `ok`, `result`, `result.message_id`,
    `result.chat` and `result.chat.id` are each load-bearing for the delivery claim, so a
    decoder that special-cased only the repeated-`chat` spelling would keep a single-body guard
    green while the other four positions still collapsed to the convenient last value.

    The sibling sender already refused the whole class through
    `assistant_main._unique_telegram_acknowledgement_object`.  The two senders disagreeing about
    what counts as an acknowledgement is the defect OC-026 opened with, so this is the same
    finding recurring one layer down rather than a new hardening idea.

    `transport_accepted` is the correct answer, not `failed`: the transport DID take the
    message.  What is unknown is what the service did with it, and that tier exists to say so.
    """

    notifier = _notifier(None, monkeypatch, raw_text=duplicated)

    outcome = await notifier.send_message(REQUESTED_CHAT, "alarm")

    assert outcome == "transport_accepted", (
        "a duplicate authority key resolved to a delivery claim; the acknowledgement cannot "
        "establish that this message reached the requested chat, and an alarm notifier must not "
        "report that the operator was told when nothing establishes it"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content_type",
    ["text/html", "text/plain", "application/octet-stream", "text/json", ""],
)
async def test_a_non_json_media_type_is_not_a_delivery_claim(
    monkeypatch: pytest.MonkeyPatch,
    content_type: str,
) -> None:
    """A JSON-shaped body served under a non-JSON media type is not delivery evidence.

    `await resp.json()` raises `aiohttp.ContentTypeError` for these responses, so before the
    duplicate-key hook was introduced this sender answered `transport_accepted` for them.
    Decoding the text directly is what the hook requires and it silently dropped that refusal,
    which would let an HTTP 200 `text/html` page from an intervening proxy -- a captive portal,
    an error page, anything that happens to carry an acknowledgement-shaped body -- resolve to
    `service_reported_delivered`.  Hardening one ambiguity must not widen another.

    `application/octet-stream` is here because that is what aiohttp reports when the response
    carries no `Content-Type` header at all, and `text/json` because the accepted set is
    anchored at `application/`, not a substring search for "json".
    """

    body = json.dumps(_ack({"message_id": 7, "chat": {"id": REQUESTED_CHAT}}))
    notifier = _notifier(None, monkeypatch, raw_text=body, content_type=content_type)

    outcome = await notifier.send_message(REQUESTED_CHAT, "alarm")

    assert outcome == "transport_accepted", (
        "a non-JSON media type resolved to a delivery claim; the same body under "
        "`application/json` is the delivery case above, so what is being asserted is that the "
        "media type still gates the decode"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content_type",
    ["application/json", "application/vnd.api+json", "application/jsonx"],
)
async def test_the_json_media_types_aiohttp_accepts_are_still_accepted_here(
    monkeypatch: pytest.MonkeyPatch,
    content_type: str,
) -> None:
    """The control for the test above: the media-type gate must not have narrowed the set.

    `aiohttp`'s own `resp.json()` accepts `application/json` and the `+json` structured-suffix
    forms.  Without this the previous guard would also pass under a gate that refused every
    body, which would break the notifier while looking like hardening.

    `application/jsonx` IS ACCEPTED, and that is not an oversight to fix here.  aiohttp's
    `json_re` is unanchored at its right edge, so `resp.json()` accepted that media type before
    this branch existed; restoring the check means restoring exactly what it accepted, and
    narrowing it instead would make this sender refuse acknowledgements the transport has always
    honoured -- a behaviour change smuggled in under a hardening change.
    """

    notifier = _notifier(
        _ack({"message_id": 7, "chat": {"id": REQUESTED_CHAT}}), monkeypatch, content_type=content_type
    )

    assert await notifier.send_message(REQUESTED_CHAT, "alarm") == "service_reported_delivered"
