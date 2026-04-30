"""Audit logger — persists every GemmaAgent LLM call for post-hoc review."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class AuditLogger:
    """Writes one JSON file per LLM call under audit_dir/<YYYY-MM-DD>/.

    Schema per file matches docs/ORCHESTRATION spec §2.8 audit record.
    Retention housekeeping (deleting old files) is handled by HousekeepingService.
    """

    def __init__(
        self,
        audit_dir: Path,
        *,
        enabled: bool = True,
        retention_days: int = 90,
    ) -> None:
        self._audit_dir = Path(audit_dir)
        self._enabled = enabled
        self._retention_days = retention_days

    def make_audit_id(self) -> str:
        """Return a short unique ID for one audit record."""
        return uuid.uuid4().hex[:12]

    async def log(
        self,
        *,
        audit_id: str,
        trigger_event: dict[str, Any],
        context_assembled: str,
        prompt_template: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        response: str,
        tokens: dict[str, int],
        latency_s: float,
        outputs_dispatched: list[str],
        errors: list[str],
    ) -> Path | None:
        """Persist an audit record. Returns the file path, or None if disabled or failed."""
        if not self._enabled:
            return None

        now = datetime.now(UTC)
        date_dir = self._audit_dir / now.strftime("%Y-%m-%d")
        date_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{now.strftime('%Y%m%dT%H%M%S%f')}_{audit_id}.json"
        path = date_dir / filename

        record: dict[str, Any] = {
            "audit_id": audit_id,
            "timestamp": now.isoformat(),
            "trigger_event": trigger_event,
            "context_assembled": context_assembled,
            "prompt_template": prompt_template,
            "model": model,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "response": response,
            "tokens": tokens,
            "latency_s": round(latency_s, 3),
            "outputs_dispatched": outputs_dispatched,
            "errors": errors,
        }

        try:
            path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            logger.warning("AuditLogger: failed to write %s", path, exc_info=True)
            return None

        return path
