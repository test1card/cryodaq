"""Audit logger — persists every GemmaAgent LLM call for post-hoc review."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryodaq.core.atomic_write import atomic_write_text

logger = logging.getLogger(__name__)


def _write_audit_record(path: Path, record: dict[str, Any]) -> None:
    """Create and atomically persist one strict-JSON audit record."""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False)
    atomic_write_text(path, content)


class AuditLogger:
    """Writes one JSON file per LLM call under audit_dir/<YYYY-MM-DD>/.

    Schema per file matches docs/ORCHESTRATION.md, "Audit evidence".
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
        _legacy = Path("data/agents/gemma/audit")
        if _legacy.exists():
            logger.warning(
                "Legacy audit log path %s found. New path is %s. "
                "Manual migration required: mv data/agents/gemma/audit "
                "data/agents/assistant/audit — NEVER auto-deleted.",
                _legacy,
                self._audit_dir,
            )

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
            # JSON encoding, directory creation, fsync and replacement are all
            # filesystem work and must not stall the assistant event loop.
            await asyncio.to_thread(_write_audit_record, path, record)
        except Exception:
            logger.warning("AuditLogger: failed to write %s", path, exc_info=True)
            return None

        return path
