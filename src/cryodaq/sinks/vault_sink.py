"""F31 — VaultSink: write a Markdown note to a filesystem vault directory."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from cryodaq.sinks.base import ExperimentExport, Sink, SinkResult

logger = logging.getLogger(__name__)


def _format_experiment_markdown(export: ExperimentExport) -> str:
    """Render an `ExperimentExport` as a Markdown note with YAML frontmatter."""
    lines: list[str] = [
        "---",
        f"experiment_id: {export.experiment_id}",
        f"title: {export.title}",
        f"sample: {export.sample}",
        f"operator: {export.operator}",
        f"status: {export.status}",
        f"started_at: {export.started_at.isoformat()}",
    ]
    if export.ended_at is not None:
        lines.append(f"ended_at: {export.ended_at.isoformat()}")
    if export.duration_h is not None:
        lines.append(f"duration_h: {export.duration_h:.2f}")
    lines.append(f"template_id: {export.template_id}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {export.title or export.experiment_id}")
    lines.append("")

    if export.description:
        lines.append("## Описание")
        lines.append(export.description)
        lines.append("")

    if export.notes:
        lines.append("## Заметки оператора")
        lines.append(export.notes)
        lines.append("")

    if export.phases:
        lines.append("## Фазы")
        for ph in export.phases:
            phase_name = ph.get("phase", "?")
            started = ph.get("started_at", "—")
            ended = ph.get("ended_at", "(in progress)")
            lines.append(f"- **{phase_name}**: {started} → {ended}")
        lines.append("")

    if export.summary:
        lines.append("## Summary")
        for key, value in export.summary.items():
            lines.append(f"- **{key}**: {value}")
        lines.append("")

    if export.artifact_index:
        lines.append("## Артефакты")
        for art in export.artifact_index:
            cat = art.get("category", "")
            role = art.get("role", "")
            path = art.get("path", "")
            lines.append(f"- ({cat}) {role} — `{path}`")
        lines.append("")

    if export.custom_fields:
        lines.append("## Параметры эксперимента")
        for key, value in export.custom_fields.items():
            lines.append(f"- **{key}**: {value}")
        lines.append("")

    return "\n".join(lines)


def _safe_filename_part(text: str) -> str:
    """Make a filesystem-safe slug from arbitrary user input."""
    if not text:
        return "unknown"
    return text.replace("/", "_").replace("\\", "_").replace(" ", "_")


class VaultSink(Sink):
    """Writes experiment exports as Markdown notes to a filesystem vault."""

    name = "vault"

    def __init__(self, vault_dir: Path) -> None:
        self._vault_dir = Path(vault_dir).expanduser().resolve()

    @property
    def vault_dir(self) -> Path:
        return self._vault_dir

    async def write(self, export: ExperimentExport) -> SinkResult:
        try:
            content = _format_experiment_markdown(export)
            target = await asyncio.to_thread(
                self._write_file_sync, export, content
            )
            logger.info("VaultSink wrote %s (%d bytes)", target, len(content))
            return SinkResult(
                sink_name=self.name,
                success=True,
                target=str(target),
            )
        except OSError as exc:
            logger.error("VaultSink write failed: %s", exc, exc_info=True)
            return SinkResult(
                sink_name=self.name,
                success=False,
                target=str(self._vault_dir),
                error=str(exc),
            )

    def _write_file_sync(self, export: ExperimentExport, content: str) -> Path:
        """H2: sync helper for to_thread offload — local writes block ms,
        network mounts (AnythingLLM target) can block seconds."""
        self._vault_dir.mkdir(parents=True, exist_ok=True)
        date_str = export.started_at.strftime("%Y-%m-%d")
        safe_sample = _safe_filename_part(export.sample)
        short_id = (export.experiment_id or "noid")[:8]
        filename = f"{date_str}_{safe_sample}_{short_id}.md"
        target = self._vault_dir / filename
        target.write_text(content, encoding="utf-8")
        return target
