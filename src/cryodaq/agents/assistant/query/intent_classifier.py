"""Intent classifier for F30 Live Query Agent.

Classifies operator free-text queries into QueryCategory using a small
LLM call (gemma4:e2b, temperature=0.1 for structured output).
Falls back to UNKNOWN on JSON parse failure or timeout.
"""

from __future__ import annotations

import asyncio
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
    from cryodaq.core.channel_manager import ChannelManager

logger = logging.getLogger(__name__)

_UNKNOWN_INTENT = QueryIntent(category=QueryCategory.UNKNOWN)


def _build_landmark_hint(channel_manager: ChannelManager) -> str:
    """Render the system-level landmark section of the classifier prompt.

    Landmark channels (Т11/Т12) are physically pinned to GM-cooler stages
    and never migrate between experiments, so the classifier must always
    resolve their aliases (e.g. "азотная плита") to the same channel_id —
    even when an experiment-level channels.yaml entry happens to drift
    onto a similar phrasing. Returns an empty string when no landmarks
    are installed (backward-compat fallback).

    2026-05-08: stronger formatting — landmark block приоритетнее EVERYTHING
    else в prompt (поднят к топу system_prompt в ``classify``), aliases
    listed exhaustively per channel так что Gemma e2b может pattern-match
    каждую фразу к channel_id.
    """
    landmarks = channel_manager.get_landmarks()
    if not landmarks:
        return ""
    lines: list[str] = [
        "═══ ВАЖНЕЙШЕЕ ПРАВИЛО — LANDMARK КАНАЛЫ ═══",
        "Эти каналы физически закреплены и НИКОГДА не меняются:",
        "",
    ]
    for ch_id in sorted(landmarks):
        entry = landmarks[ch_id]
        aliases = list(entry.get("aliases", []))
        physical = entry.get("physical", "")
        lines.append(f"▶ {ch_id} ({physical})")
        if aliases:
            lines.append(f'  Любая из этих фраз → target_channels=["{ch_id}"]:')
            for alias in aliases:
                lines.append(f"    • «{alias}»")
        lines.append("")
    lines.append(
        "Если запрос содержит ЛЮБУЮ из перечисленных фраз выше — "
        "ОБЯЗАТЕЛЬНО положи соответствующий channel_id в target_channels."
    )
    lines.append("Категория для таких запросов = current_value (если спрашивают значение/температуру/сейчас).")
    lines.append("═" * 50)
    return "\n".join(lines)


def _build_channel_hint(channel_manager: ChannelManager | None) -> str:
    """Build channel reference table for classifier prompt.

    Reads CURRENT ChannelManager state on every call — reflects all renames
    done via GUI ChannelEditor since engine startup (late binding). Emits a
    two-tier list when landmarks are installed:

      1. Hardware-pinned landmark channels (Т11/Т12 with aliases) first.
      2. Experiment-level channels.yaml entries below, with an explicit
         note that landmarks take priority on alias collisions.
    """
    if channel_manager is None:
        return ""
    landmark_block = _build_landmark_hint(channel_manager)
    rows: list[str] = []
    for ch_id, ch_data in channel_manager.get_all().items():
        if not channel_manager.is_visible(ch_id):
            continue
        name = ch_data.get("name", "")
        rows.append(f'  {ch_id} → "{name}"' if name else f"  {ch_id}")
    if not rows and not landmark_block:
        return ""

    parts: list[str] = ["\n"]
    if landmark_block:
        parts.append("\n" + landmark_block + "\n")
    if rows:
        header = (
            "\nКАНАЛЫ ТЕКУЩЕГО ЭКСПЕРИМЕНТА (имена меняются от эксперимента к эксперименту):"
            if landmark_block
            else "\nДоступные каналы (channel_id → название):"
        )
        parts.append(header + "\n" + "\n".join(rows) + "\n")
    if landmark_block:
        parts.append(
            "\nВАЖНО: landmark-каналы приоритетнее experiment-каналов "
            "при матчинге названий. Если оператор говорит фразу из списка "
            "алиасов landmark — отдавай landmark channel_id, даже если в "
            "текущем эксперименте какое-то имя совпадает.\n"
        )
    parts.append(
        "\nКогда оператор называет канал по имени (например "
        '"азотная плита", "болометр", "детектор"), '
        "найди соответствующий channel_id и положи в target_channels.\n"
    )
    return "".join(parts)


_VALID_CATEGORIES = frozenset(c.value for c in QueryCategory)


# v0.55.14 (audit SCOPE 6 finding 6.4) — allow-list of canonical
# corpus kinds emitted by ``cryodaq.agents.rag.document_loader``. Any
# value outside this set (including comma-separated multi-hints, list /
# dict shapes, or arbitrary strings) collapses to ``None`` so the
# RAGAdapter searches across the whole corpus rather than passing a
# malformed ``WHERE`` clause to LanceDB.
#
# 2026-05-08: expanded к full 8-kind set после v0.55.7.1 KB expansion.
# Pre-fix old set was {experiment_metadata, vault_note, operator_log}
# — оператор спрашивает «процедура захолаживания» → classifier хочет
# filter `procedure` → rejected → no filter → noisy retrieval с
# experiment metadata вместо procedure markdown.
_VALID_SOURCE_KINDS = frozenset(
    {
        "experiment_metadata",
        "vault_note",
        "operator_log",
        # v0.55.7.1 KB expansion (knowledge corpus):
        "equipment_manual",
        "procedure",
        "operator_manual",
        "readme",
        "readme_en",
        "changelog",
    }
)


def _normalise_source_kind(raw: Any) -> str | None:
    """Validate and normalise a classifier-provided ``target_source_kind``.

    Returns ``None`` for: missing/null, the literal strings "null" /
    "none" / "" (Gemma sometimes emits them), list / dict / multi-value
    inputs, and any single value not in the canonical corpus-kind
    allow-list. Otherwise returns the lower-cased canonical kind.
    """
    if raw is None:
        return None
    if isinstance(raw, (list, tuple, dict, set)):
        # Multi-hint or contradictory hint — refuse rather than picking
        # arbitrarily; whole-corpus search is the safe default.
        return None
    kind_str = str(raw).strip().lower()
    if not kind_str or kind_str in {"null", "none"}:
        return None
    if "," in kind_str or any(c.isspace() for c in kind_str):
        # Comma-separated or whitespace-glued hints from Gemma
        # ("vault, operator_log") are ambiguous; collapse rather than
        # guess at one.
        return None
    if kind_str not in _VALID_SOURCE_KINDS:
        logger.debug(
            "IntentClassifier: rejecting non-canonical target_source_kind %r",
            kind_str,
        )
        return None
    return kind_str


def _parse_intent(raw: str) -> QueryIntent:
    """Parse LLM JSON output into QueryIntent. Returns UNKNOWN on any error."""
    raw = raw.strip()
    if not raw:
        return _UNKNOWN_INTENT

    # Strip markdown code fences if present
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(line for line in lines if not line.startswith("```")).strip()

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

    target_source_kind = _normalise_source_kind(data.get("target_source_kind"))

    return QueryIntent(
        category=QueryCategory(category_str),
        target_channels=channels if channels else None,
        time_window_minutes=window,
        quantity=str(data.get("quantity", "")),
        target_source_kind=target_source_kind,
    )


class IntentClassifier:
    """Classifies operator queries via a small LLM call."""

    def __init__(
        self,
        ollama_client: OllamaClient,
        *,
        model: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
        timeout_s: float | None = None,
        channel_manager: ChannelManager | None = None,
    ) -> None:
        self._ollama = ollama_client
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._timeout_s = timeout_s
        self._channel_manager = channel_manager  # stored by reference, never cached

    async def classify(self, query: str) -> QueryIntent:
        """Classify query text into a QueryIntent. Never raises.

        2026-05-08: landmark hint moved к ТОЧНО ВЕРХ system prompt
        (BEFORE INTENT_CLASSIFIER_SYSTEM) — gemma4:e2b слабая модель и
        position bias significant: landmark instructions в конце были
        ignored, в начале — followed.
        """
        try:
            channel_hint = _build_channel_hint(self._channel_manager)
            # Landmark hint goes FIRST — gemma4:e2b position-biased,
            # critical instructions must lead.
            system_prompt = channel_hint + "\n\n" + INTENT_CLASSIFIER_SYSTEM
            user_prompt = INTENT_CLASSIFIER_USER.format(query=query)
            generation = self._ollama.generate(
                user_prompt,
                model=self._model,
                system=system_prompt,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            )
            if self._timeout_s is None:
                result = await generation
            else:
                result = await asyncio.wait_for(generation, timeout=self._timeout_s)
            if result.truncated or not result.text.strip():
                logger.warning("IntentClassifier: empty/truncated response for %r", query[:80])
                return _UNKNOWN_INTENT
            return _parse_intent(result.text)
        except Exception as exc:
            logger.warning("IntentClassifier: error classifying %r: %s", query[:80], exc)
            return _UNKNOWN_INTENT
