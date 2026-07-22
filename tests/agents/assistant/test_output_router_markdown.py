"""F-BotPolish — Markdown→HTML conversion in OutputRouter (Stage 1).

The OPERATOR_LOG and GUI_INSIGHT targets keep the raw Markdown that Gemma
emits per the ALARM_SUMMARY_SYSTEM prompt instruction; only the TELEGRAM
target converts ``**...**`` / ``*...*`` / `` `...` `` into HTML so the
Telegram bot's ``parse_mode=HTML`` does not show literal asterisks.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from cryodaq.agents.assistant.live.output_router import (
    OutputRouter,
    OutputTarget,
    _markdown_to_html_for_telegram,
)

# ---------------------------------------------------------------------------
# Pure helper
# ---------------------------------------------------------------------------


def test_bold_and_italic_converted_without_mutual_eating():
    out = _markdown_to_html_for_telegram("**сильно** и *мягко*, плюс **жирный** хвост")
    assert "<b>сильно</b>" in out
    assert "<i>мягко</i>" in out
    assert "<b>жирный</b>" in out
    # No leftover markdown markers.
    assert "*" not in out


def test_bold_around_italic_keeps_outer_bold():
    out = _markdown_to_html_for_telegram("**жирный *внутри* конец**")
    assert out == "<b>жирный <i>внутри</i> конец</b>" or "<b>жирный <i>внутри</i> конец</b>" in out
    assert "*" not in out


def test_inline_code_converted():
    out = _markdown_to_html_for_telegram("значение `Т12=4.5` ок")
    assert "<code>Т12=4.5</code>" in out


def test_headers_stripped_in_place():
    out = _markdown_to_html_for_telegram("# Заголовок\nтело сообщения")
    assert "Заголовок\nтело сообщения" in out
    assert "#" not in out


def test_plain_text_pass_through_unchanged():
    out = _markdown_to_html_for_telegram("Простой текст без разметки.")
    assert out == "Простой текст без разметки."


def test_bullet_asterisk_marker_left_alone():
    """Lines starting with ``*<space>`` are bullets, not italic delimiters —
    the italic regex requires word characters between markers, so ``* item``
    is intentionally not converted."""
    raw = "* первый\n* второй"
    assert _markdown_to_html_for_telegram(raw) == raw


# ---------------------------------------------------------------------------
# Dispatch — only TELEGRAM is normalized
# ---------------------------------------------------------------------------


@pytest.fixture
def trigger_event():
    class _Ev:
        event_type = "alarm_fired"
        experiment_id = "exp1"

    return _Ev()


def test_telegram_dispatch_normalizes_markdown(trigger_event):
    telegram = AsyncMock()
    event_bus = AsyncMock()
    router = OutputRouter(
        telegram_bot=telegram,
        event_bus=event_bus,
    )
    body = "**Аларм!** канал *Т12* в норме."

    import asyncio

    asyncio.run(
        router.dispatch(
            trigger_event,
            body,
            targets=[OutputTarget.TELEGRAM],
            audit_id="aud-1",
        )
    )

    telegram._send_to_all.assert_awaited_once()
    sent: str = telegram._send_to_all.await_args.args[0]
    assert "<b>Аларм!</b>" in sent
    assert "<i>Т12</i>" in sent
    assert "*" not in sent
    # Brand prefix preserved.
    assert sent.startswith("🤖 Гемма:")


def test_gui_insight_keeps_raw_markdown(trigger_event):
    telegram = AsyncMock()
    event_bus = AsyncMock()
    router = OutputRouter(
        telegram_bot=telegram,
        event_bus=event_bus,
    )
    body = "**Аларм!** канал *Т12*"

    import asyncio

    asyncio.run(
        router.dispatch(
            trigger_event,
            body,
            targets=[OutputTarget.GUI_INSIGHT],
            audit_id="aud-1",
        )
    )

    event_bus.publish.assert_awaited_once()
    published: Any = event_bus.publish.await_args.args[0]
    assert published.payload["text"] == body  # raw Markdown preserved


def test_telegram_skipped_when_bot_none(trigger_event):
    event_bus = AsyncMock()
    router = OutputRouter(
        telegram_bot=None,
        event_bus=event_bus,
    )

    import asyncio

    dispatched = asyncio.run(
        router.dispatch(
            trigger_event,
            "**bold**",
            targets=[OutputTarget.TELEGRAM],
            audit_id="aud-1",
        )
    )

    assert dispatched == []  # silently skipped; no exception raised


def test_failed_telegram_is_not_reported_as_dispatched(trigger_event):
    telegram = AsyncMock()
    telegram._send_to_all = AsyncMock(return_value=False)
    router = OutputRouter(
        telegram_bot=telegram,
        event_bus=AsyncMock(),
    )

    import asyncio

    outcomes = asyncio.run(
        router.dispatch_detailed(
            trigger_event,
            "alarm",
            targets=[OutputTarget.TELEGRAM],
            audit_id="aud-failed",
        )
    )

    assert outcomes == {"telegram": "failed"}
    assert (
        asyncio.run(
            router.dispatch(
                trigger_event,
                "alarm",
                targets=[OutputTarget.TELEGRAM],
                audit_id="aud-failed",
            )
        )
        == []
    )
