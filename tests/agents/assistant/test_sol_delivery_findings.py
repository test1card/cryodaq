"""The seven defects sol found in the delivery path, each with its scenario.

Reviewed 2026-09-08 against the batch already running on the stand. Every one of
these loses or corrupts the hourly report; none would have shown up as a crash.
"""

from __future__ import annotations

import json

from cryodaq.agents.assistant.periodic_telegram import (
    TelegramOutcome,
    _classify_response,
    _CompleteHttpResponse,
)
from cryodaq.reporting.periodic_input import MAX_SUMMARY_CHARS, _summary_text
from cryodaq.reporting.periodic_renderer import MAX_CAPTION_CODEPOINTS, _with_summary

_CHAT = 4242


def _reply(result) -> _CompleteHttpResponse:
    return _CompleteHttpResponse(200, json.dumps({"ok": True, "result": result}).encode())


def _message(message_id: int, chat: int = _CHAT) -> dict:
    return {"message_id": message_id, "chat": {"id": chat}}


# --- 1. Critical: a successful media group was recorded as UNKNOWN ----------


def test_a_successful_media_group_is_accepted_not_unknown() -> None:
    """sendMediaGroup returns an ARRAY; sendPhoto returns an object.

    Read with the object's rules the array had no `chat` and no `message_id`,
    so every ordinary success became UNKNOWN. The unresolved ledger is bounded,
    so a run of good reports would eventually fill it and stop delivery.
    """
    result = _classify_response(_reply([_message(11), _message(12)]), _CHAT, group=True)

    assert result.outcome is TelegramOutcome.ACCEPTED, "a delivered report recorded as unknown"
    assert result.message_id == 11, "the group is identified by the item carrying the caption"


def test_a_single_photo_reply_is_still_read_as_an_object() -> None:
    result = _classify_response(_reply(_message(11)), _CHAT)
    assert result.outcome is TelegramOutcome.ACCEPTED
    assert result.message_id == 11


def test_a_group_reply_in_the_wrong_chat_is_not_accepted() -> None:
    result = _classify_response(_reply([_message(11), _message(12, chat=9)]), _CHAT, group=True)
    assert result.outcome is TelegramOutcome.UNKNOWN


def test_a_group_reply_that_is_not_a_list_is_not_accepted() -> None:
    assert _classify_response(_reply(_message(11)), _CHAT, group=True).outcome is TelegramOutcome.UNKNOWN


def test_a_group_reply_with_one_item_is_not_accepted() -> None:
    """Telegram groups hold two to ten. One item back is not the group we sent."""
    assert _classify_response(_reply([_message(11)]), _CHAT, group=True).outcome is TelegramOutcome.UNKNOWN


def test_a_group_item_that_is_not_a_message_is_not_accepted() -> None:
    assert _classify_response(_reply([_message(11), "нет"]), _CHAT, group=True).outcome is TelegramOutcome.UNKNOWN


# --- 4. High: truncation split an HTML entity and froze the caption ---------


def test_truncation_never_splits_an_escaped_entity() -> None:
    """Slicing escaped text can leave "&a", which Telegram's parser rejects.

    The caption is fenced, so the same broken text is re-sent on every retry
    until the report is lost.
    """
    caption = "x" * (MAX_CAPTION_CODEPOINTS - 60)
    summary = "y" * 37 + "&" + "z" * 300

    result = _with_summary(caption, summary)

    tail = result[len(caption) :]
    # The property is not "no & appears" — a whole &amp; is correct and expected.
    # It is that every & in the output BEGINS A COMPLETE entity.
    for index, char in enumerate(tail):
        if char != "&":
            continue
        rest = tail[index:]
        assert any(rest.startswith(entity) for entity in ("&amp;", "&lt;", "&gt;", "&quot;", "&#39;")), (
            f"a truncated entity survived at {index}: {rest[:8]!r}"
        )


def test_a_summary_that_cannot_fit_at_all_is_dropped_not_mangled() -> None:
    caption = "x" * (MAX_CAPTION_CODEPOINTS - 41)
    assert _with_summary(caption, "&" * 400) == caption


def test_an_ordinary_summary_still_reaches_the_caption() -> None:
    assert "тихо" in _with_summary("Отчёт", "На стенде тихо")


# --- 5. High: the summary was bounded only after the size gate -------------


def test_the_summary_is_bounded_before_it_enters_the_payload() -> None:
    """Producer-side bound. The reader's cap runs after the size check."""
    import inspect

    from cryodaq.agents.assistant import periodic_png

    source = inspect.getsource(periodic_png)
    assert "MAX_SUMMARY_CHARS" in source, "the payload can carry an unbounded summary past max_input_bytes"


# --- 6. Medium: DEL passed the sanitiser and failed the caption validator ---


def test_del_and_the_c1_block_are_stripped() -> None:
    """`char >= " "` kept them: they sort above space."""
    assert _summary_text("ok\x7fbad") == "okbad"
    assert _summary_text("ok\x9fbad") == "okbad"
    assert _summary_text("ok\x01bad") == "okbad"


def test_ordinary_text_and_newlines_survive() -> None:
    assert _summary_text("Давление растёт\nна 0.1 мбар/ч") == "Давление растёт\nна 0.1 мбар/ч"


def test_a_long_summary_is_still_capped() -> None:
    assert len(_summary_text("я" * (MAX_SUMMARY_CHARS * 3))) <= MAX_SUMMARY_CHARS
