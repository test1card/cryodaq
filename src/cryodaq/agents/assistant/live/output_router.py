"""Output routing for GemmaAgent LLM responses.

Dispatches generated text to configured output channels.
Every output is prefixed with "🤖 Гемма:" so operators immediately
distinguish AI-generated content from human input.
"""

from __future__ import annotations

import enum
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cryodaq.core.event_bus import EngineEvent, EventBus
    from cryodaq.core.event_logger import EventLogger

logger = logging.getLogger(__name__)

class OutputTarget(enum.Enum):
    TELEGRAM = "telegram"
    OPERATOR_LOG = "operator_log"
    GUI_INSIGHT = "gui_insight"


class OutputRouter:
    """Dispatches AssistantLiveAgent LLM output to configured channels."""

    def __init__(
        self,
        *,
        telegram_bot: Any | None,
        event_logger: EventLogger,
        event_bus: EventBus,
        brand_name: str = "Гемма",
        brand_emoji: str = "🤖",
    ) -> None:
        self._telegram = telegram_bot
        self._event_logger = event_logger
        self._event_bus = event_bus
        self._brand_base = f"{brand_emoji} {brand_name}"
        self._prefix = f"{self._brand_base}:"

    async def dispatch(
        self,
        trigger_event: EngineEvent,
        llm_output: str,
        *,
        targets: list[OutputTarget],
        audit_id: str,
        prefix_suffix: str = "",
    ) -> list[str]:
        """Send llm_output to all configured targets.

        prefix_suffix: optional text inserted before the colon, e.g. "(отчёт за час)".
        Returns list of successfully dispatched target names.
        """
        dispatched: list[str] = []
        if prefix_suffix:
            prefix = f"{self._brand_base} {prefix_suffix}:"
        else:
            prefix = self._prefix
        prefixed = f"{prefix} {llm_output}"

        for target in targets:
            try:
                if target == OutputTarget.TELEGRAM:
                    if self._telegram is not None:
                        await self._telegram._send_to_all(prefixed)
                        dispatched.append("telegram")
                    else:
                        logger.debug("OutputRouter: Telegram bot not configured, skipping")

                elif target == OutputTarget.OPERATOR_LOG:
                    await self._event_logger.log_event(
                        "assistant",
                        prefixed,
                        extra_tags=["ai", audit_id],
                    )
                    dispatched.append("operator_log")

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
                    dispatched.append("gui_insight")

            except Exception:
                logger.warning(
                    "OutputRouter: failed to dispatch to %s (audit_id=%s)",
                    target.value,
                    audit_id,
                    exc_info=True,
                )

        return dispatched
