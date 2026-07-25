"""Output routing for GemmaAgent LLM responses.

Dispatches generated text to configured output channels.
Every output is prefixed with "🤖 Гемма:" so operators immediately
distinguish AI-generated content from human input.
"""

from __future__ import annotations

import enum
import html
import logging
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cryodaq.core.event_bus import EngineEvent, EventBus

logger = logging.getLogger(__name__)

# F-BotPolish — Markdown→HTML normalizer for the TELEGRAM target only.
# Gemma is explicitly instructed (ALARM_SUMMARY_SYSTEM, prompts.py) to emit
# Telegram-friendly Markdown (bold/italic, no headers). TelegramCommandBot
# sends with parse_mode=HTML, so raw "*"/"**" markers leak as literal
# asterisks. The OPERATOR_LOG and GUI_INSIGHT targets keep raw Markdown.
#
# Order matters: bold (**...**) is parsed before italic (*...*) so that
# the italic pattern below (which deliberately rejects the "**" boundary)
# only matches single-asterisk runs left over after the bold pass.
_MD_BOLD_RE = re.compile(r"\*\*([^\n*][^\n]*?)\*\*")
_MD_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)([^\n*][^\n]*?)(?<!\*)\*(?!\*)")
_MD_INLINE_CODE_RE = re.compile(r"`([^\n`]+?)`")
_MD_HEADERS_RE = re.compile(r"^#{1,6}\s+", flags=re.MULTILINE)


def _markdown_to_html_for_telegram(text: str) -> str:
    """Convert basic Markdown to Telegram HTML (bold / italic / inline code).

    Gemma emits Markdown per the ALARM_SUMMARY_SYSTEM prompt instruction;
    the Telegram bot uses parse_mode=HTML, so without conversion the
    asterisks render literally. Conversions:

    - ``**text**`` → ``<b>text</b>``
    - ``*text*``   → ``<i>text</i>``
    - `` `text` `` → ``<code>text</code>``
    - ``# Header`` (line prefix) → stripped

    Bullet ``*`` markers ("* item", "  * item") are intentionally untouched
    because the italic regex requires word characters between the markers.
    """
    text = html.escape(text, quote=False)
    text = _MD_BOLD_RE.sub(r"<b>\1</b>", text)
    text = _MD_ITALIC_RE.sub(r"<i>\1</i>", text)
    text = _MD_INLINE_CODE_RE.sub(r"<code>\1</code>", text)
    text = _MD_HEADERS_RE.sub("", text)
    return text


class OutputTarget(enum.Enum):
    TELEGRAM = "telegram"
    GUI_INSIGHT = "gui_insight"


class OutputRouter:
    """Dispatches AssistantLiveAgent LLM output to configured channels."""

    def __init__(
        self,
        *,
        telegram_bot: Any | None,
        event_bus: EventBus,
        brand_name: str = "Гемма",
        brand_emoji: str = "🤖",
    ) -> None:
        self._telegram = telegram_bot
        self._event_bus = event_bus
        self._brand_base = f"{brand_emoji} {brand_name}"
        self._prefix = f"{self._brand_base}:"

    async def dispatch_detailed(
        self,
        trigger_event: EngineEvent,
        llm_output: str,
        *,
        targets: list[OutputTarget],
        audit_id: str,
        prefix_suffix: str = "",
    ) -> dict[str, Any]:
        """Send llm_output to all configured targets.

        prefix_suffix: optional text inserted before the colon, e.g. "(отчёт за час)".
        Returns one explicit settlement state per requested target.
        """
        outcomes: dict[str, str] = {}
        if prefix_suffix:
            prefix = f"{self._brand_base} {prefix_suffix}:"
        else:
            prefix = self._prefix
        for target in targets:
            try:
                if target == OutputTarget.TELEGRAM:
                    if self._telegram is not None:
                        # F-BotPolish: convert Markdown→HTML only for the
                        # Telegram target. The prefix is plain ASCII and
                        # already HTML-safe, so we only normalize the body.
                        telegram_text = f"{prefix} {_markdown_to_html_for_telegram(llm_output)}"
                        sent = await self._telegram._send_to_all(telegram_text)
                        if isinstance(sent, dict):
                            states = tuple(sent.values())
                            if len(sent) == 1:
                                outcomes["telegram"] = next(iter(states), "failed")
                            else:
                                outcomes["telegram"] = {str(chat_id): str(state) for chat_id, state in sent.items()}
                        elif sent is True:
                            outcomes["telegram"] = "delivered"
                        else:
                            outcomes["telegram"] = "failed"
                    else:
                        logger.debug("OutputRouter: Telegram bot not configured, skipping")
                        outcomes["telegram"] = "not_configured"

                elif target == OutputTarget.GUI_INSIGHT:
                    from datetime import UTC, datetime

                    from cryodaq.core.event_bus import EngineEvent as _EngineEvent

                    await self._event_bus.publish(
                        _EngineEvent(
                            event_type="assistant_insight",
                            timestamp=datetime.now(UTC),
                            payload={
                                "text": llm_output,
                                "trigger_event_type": trigger_event.event_type,
                                "audit_id": audit_id,
                            },
                            experiment_id=trigger_event.experiment_id,
                        )
                    )
                    outcomes["gui_insight"] = "delivered"

            except Exception:
                outcomes[target.value] = "outcome_unknown"
                logger.warning(
                    "OutputRouter: failed to dispatch to %s (audit_id=%s)",
                    target.value,
                    audit_id,
                    exc_info=True,
                )

        return outcomes

    async def dispatch(
        self,
        trigger_event: EngineEvent,
        llm_output: str,
        *,
        targets: list[OutputTarget],
        audit_id: str,
        prefix_suffix: str = "",
    ) -> list[str]:
        """Compatibility wrapper returning only targets proven delivered."""
        outcomes = await self.dispatch_detailed(
            trigger_event,
            llm_output,
            targets=targets,
            audit_id=audit_id,
            prefix_suffix=prefix_suffix,
        )
        delivered: list[str] = []
        for target, state in outcomes.items():
            if state == "delivered":
                delivered.append(target)
            elif (
                isinstance(state, dict)
                and state
                and all(recipient_state == "delivered" for recipient_state in state.values())
            ):
                delivered.append(target)
        return delivered

    async def close(self) -> None:
        """Settle and close the owned Telegram transport, if configured."""
        close = getattr(self._telegram, "close", None)
        if callable(close):
            await close()
