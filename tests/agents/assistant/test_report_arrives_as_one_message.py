"""Two charts, one message.

The hourly report arrived as two separate messages — the windowed chart, then
a whole-run companion announced after delivery. On a phone that is two screens
for one hourly glance. Operator's request, 2026-09-07: keep them as separate
pictures, they are different charts, but send them together.

The companion stays outside the fence on purpose. The fenced state machine owns
exactly one artifact per slot, with a receipt and a retry ladder, and a
supplementary picture must never be able to make the report itself less
reliable. So it is rendered immediately before the send, and every failure of
it means the operator gets exactly what they got before: one photo.
"""

from __future__ import annotations

import hashlib
import uuid

import pytest

from cryodaq.agents.assistant.periodic_delivery import PeriodicDeliveryContext

#: The delivery contract refuses an artifact under 33 bytes, so the fakes are
#: long enough to be plausible payloads rather than markers.
_REPORT = b"report-png-bytes-" + b"r" * 32
_OVERVIEW = b"overview-png-bytes-" + b"o" * 32


def _context(photo: bytes, caption: str) -> PeriodicDeliveryContext:
    caption_bytes = caption.encode("utf-8")
    return PeriodicDeliveryContext(
        slot_id="sha256:" + hashlib.sha256(b"slot").hexdigest(),
        generation_id=uuid.uuid4().hex,
        owner_token=uuid.uuid4().hex,
        artifact_sha256="sha256:" + hashlib.sha256(photo).hexdigest(),
        artifact_size=len(photo),
        caption_sha256="sha256:" + hashlib.sha256(caption_bytes).hexdigest(),
        caption_size=len(caption_bytes),
    )


class _Client:
    def __init__(self) -> None:
        self.photo_calls: list[tuple[bytes, str]] = []
        self.group_calls: list[tuple[list[bytes], str]] = []

    async def send_photo(self, photo, caption):
        self.photo_calls.append((photo, caption))
        return _Accepted()

    async def send_media_group(self, photos, caption):
        self.group_calls.append((photos, caption))
        return _Accepted()

    async def close(self) -> None:
        return None


class _Accepted:
    from cryodaq.agents.assistant.periodic_telegram import TelegramOutcome as _Outcome

    outcome = _Outcome.ACCEPTED
    message_id = 1
    retry_after_s = None
    error_code = None
    error_text = ""


def _delivery(companion, client):
    from cryodaq.agents.assistant.periodic_runtime import _TelegramPeriodicDelivery

    delivery = _TelegramPeriodicDelivery.__new__(_TelegramPeriodicDelivery)
    delivery._client = client
    delivery._close_task = None
    delivery._companion = companion
    return delivery


async def test_both_charts_travel_as_one_message() -> None:
    client = _Client()

    async def companion() -> bytes:
        return _OVERVIEW

    delivery = _delivery(companion, client)
    await delivery.send_artifact(_REPORT, "подпись", _context(_REPORT, "подпись"))

    assert client.group_calls, "the two charts were not sent together"
    photos, caption = client.group_calls[0]
    assert photos == [_REPORT, _OVERVIEW], "the report must lead the group"
    assert caption == "подпись", "the caption belongs to the first item"
    assert not client.photo_calls, "a second message was sent as well"


async def test_a_missing_companion_still_delivers_the_report() -> None:
    """One fewer picture is not an incident."""
    client = _Client()

    async def companion() -> None:
        return None

    delivery = _delivery(companion, client)
    await delivery.send_artifact(_REPORT, "подпись", _context(_REPORT, "подпись"))

    assert client.photo_calls and not client.group_calls


async def test_a_raising_companion_still_delivers_the_report() -> None:
    """The report must not be lost to a supplementary chart's failure."""
    client = _Client()

    async def companion() -> bytes:
        raise RuntimeError("renderer died")

    delivery = _delivery(companion, client)
    result = await delivery.send_artifact(_REPORT, "подпись", _context(_REPORT, "подпись"))

    assert client.photo_calls, "the report was not sent"
    assert result.outcome.value == "accepted"


async def test_a_hanging_companion_does_not_hold_the_report_forever() -> None:
    """It now blocks the send, so its patience is the report's, and bounded."""
    import asyncio

    from cryodaq.agents.assistant import periodic_runtime

    client = _Client()

    async def companion() -> bytes:
        await asyncio.sleep(3600)
        raise AssertionError("unreachable")

    delivery = _delivery(companion, client)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(periodic_runtime, "_COMPANION_RENDER_TIMEOUT_S", 0.05)
        await delivery.send_artifact(_REPORT, "подпись", _context(_REPORT, "подпись"))

    assert client.photo_calls, "a hanging companion cost the report"


async def test_a_corrupt_companion_is_refused_rather_than_sent() -> None:
    client = _Client()

    async def companion() -> str:
        return "not bytes"

    delivery = _delivery(companion, client)
    await delivery.send_artifact(_REPORT, "подпись", _context(_REPORT, "подпись"))

    assert client.photo_calls and not client.group_calls
