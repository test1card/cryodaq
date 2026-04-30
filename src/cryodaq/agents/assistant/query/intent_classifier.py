"""Intent classifier for F30 Live Query Agent.

Classifies operator free-text queries into QueryCategory using a small
LLM call (gemma4:e2b, temperature=0.1 for structured output).
Falls back to UNKNOWN on JSON parse failure or timeout.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from cryodaq.agents.assistant.query.prompts import (
    INTENT_CLASSIFIER_SYSTEM,
    INTENT_CLASSIFIER_USER,
)
from cryodaq.agents.assistant.query.schemas import QueryCategory, QueryIntent

if TYPE_CHECKING:
    from cryodaq.agents.assistant.shared.ollama_client import OllamaClient

logger = logging.getLogger(__name__)

_UNKNOWN_INTENT = QueryIntent(category=QueryCategory.UNKNOWN)

_VALID_CATEGORIES = frozenset(c.value for c in QueryCategory)


def _parse_intent(raw: str) -> QueryIntent:
    """Parse LLM JSON output into QueryIntent. Returns UNKNOWN on any error."""
    raw = raw.strip()
    if not raw:
        return _UNKNOWN_INTENT

    # Strip markdown code fences if present
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(
            line for line in lines if not line.startswith("```")
        ).strip()

    try:
        data: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError:
        # Try to extract JSON object from text (model may add text around it)
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                data = json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                logger.debug("IntentClassifier: JSON parse failed: %r", raw[:200])
                return _UNKNOWN_INTENT
        else:
            logger.debug("IntentClassifier: no JSON object found: %r", raw[:200])
            return _UNKNOWN_INTENT

    category_str = str(data.get("category", "unknown")).lower()
    if category_str not in _VALID_CATEGORIES:
        logger.debug("IntentClassifier: unknown category %r", category_str)
        category_str = "unknown"

    channels = data.get("target_channels")
    if not isinstance(channels, list):
        channels = None
    else:
        channels = [str(c) for c in channels if c]

    window: int | None = None
    raw_window = data.get("time_window_minutes")
    if raw_window is not None:
        try:
            window = int(raw_window)
        except (TypeError, ValueError):
            pass

    return QueryIntent(
        category=QueryCategory(category_str),
        target_channels=channels if channels else None,
        time_window_minutes=window,
        quantity=str(data.get("quantity", "")),
    )


class IntentClassifier:
    """Classifies operator queries via a small LLM call."""

    def __init__(
        self,
        ollama_client: OllamaClient,
        *,
        model: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 256,
        timeout_s: float | None = None,
    ) -> None:
        self._ollama = ollama_client
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._timeout_s = timeout_s

    async def classify(self, query: str) -> QueryIntent:
        """Classify query text into a QueryIntent. Never raises."""
        try:
            user_prompt = INTENT_CLASSIFIER_USER.format(query=query)
            result = await self._ollama.generate(
                user_prompt,
                model=self._model,
                system=INTENT_CLASSIFIER_SYSTEM,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            )
            if result.truncated or not result.text.strip():
                logger.warning("IntentClassifier: empty/truncated response for %r", query[:80])
                return _UNKNOWN_INTENT
            return _parse_intent(result.text)
        except Exception as exc:
            logger.warning("IntentClassifier: error classifying %r: %s", query[:80], exc)
            return _UNKNOWN_INTENT
