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

from typing import Any

import pytest

from cryodaq.notifications.telegram import TelegramNotifier

MAX_JSON_INTEGER = 2**63 - 1
REQUESTED_CHAT = -1001234567890


class _Response:
    """The minimum of aiohttp's response that `send_message` actually uses."""

    def __init__(self, payload: Any, status: int = 200) -> None:
        self.status = status
        self._payload = payload

    async def __aenter__(self) -> _Response:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def json(self) -> Any:
        return self._payload

    async def text(self) -> str:
        return "stub"


class _Session:
    def __init__(self, response: _Response) -> None:
        self._response = response
        self.closed = False

    def post(self, _url: str, **_kwargs: Any) -> _Response:
        return self._response


def _notifier(payload: Any, monkeypatch: pytest.MonkeyPatch) -> TelegramNotifier:
    notifier = TelegramNotifier(bot_token="token", chat_id=REQUESTED_CHAT)
    session = _Session(_Response(payload))

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
