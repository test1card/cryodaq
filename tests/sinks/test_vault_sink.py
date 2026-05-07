"""F31 — VaultSink tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from cryodaq.sinks.base import ExperimentExport
from cryodaq.sinks.vault_sink import VaultSink, _format_experiment_markdown


def _sample_export(**overrides) -> ExperimentExport:
    base = dict(
        experiment_id="abc12345-deadbeef",
        title="Тестовый эксперимент",
        sample="S-001",
        operator="Vladimir",
        status="COMPLETED",
        started_at=datetime(2026, 5, 7, 10, 0, tzinfo=UTC),
        ended_at=datetime(2026, 5, 7, 14, 0, tzinfo=UTC),
        duration_h=4.0,
        template_id="cooldown_basic",
    )
    base.update(overrides)
    return ExperimentExport(**base)


def test_format_markdown_includes_frontmatter():
    md = _format_experiment_markdown(_sample_export())
    assert md.startswith("---")
    assert "experiment_id: abc12345-deadbeef" in md
    assert "sample: S-001" in md
    assert "started_at: 2026-05-07T10:00:00+00:00" in md
    assert "ended_at: 2026-05-07T14:00:00+00:00" in md


def test_format_markdown_includes_title_h1():
    md = _format_experiment_markdown(_sample_export(title="Моя проба"))
    assert "\n# Моя проба\n" in md


def test_format_markdown_includes_phases():
    export = _sample_export()
    export = ExperimentExport(
        **{
            **export.__dict__,
            "phases": [
                {
                    "phase": "preparation",
                    "started_at": "2026-05-07T10:00:00Z",
                    "ended_at": "2026-05-07T10:30:00Z",
                },
                {
                    "phase": "cooldown",
                    "started_at": "2026-05-07T10:30:00Z",
                    "ended_at": "2026-05-07T13:00:00Z",
                },
            ],
        }
    )
    md = _format_experiment_markdown(export)
    assert "## Фазы" in md
    assert "preparation" in md
    assert "cooldown" in md


def test_format_markdown_includes_artifact_index():
    export = ExperimentExport(
        **{
            **_sample_export().__dict__,
            "artifact_index": [
                {"category": "report", "role": "docx", "path": "reports/report_raw.docx"},
                {"category": "table", "role": "result", "path": "tables/iv_curve.csv"},
            ],
        }
    )
    md = _format_experiment_markdown(export)
    assert "## Артефакты" in md
    assert "reports/report_raw.docx" in md


def test_format_markdown_no_ended_at_when_missing():
    export = _sample_export(ended_at=None, duration_h=None)
    md = _format_experiment_markdown(export)
    assert "ended_at:" not in md
    assert "duration_h:" not in md


@pytest.mark.asyncio
async def test_vault_sink_writes_file(tmp_path):
    sink = VaultSink(tmp_path)
    result = await sink.write(_sample_export())
    assert result.success
    assert result.sink_name == "vault"
    written = list(tmp_path.glob("*.md"))
    assert len(written) == 1
    content = written[0].read_text(encoding="utf-8")
    assert "experiment_id: abc12345-deadbeef" in content


@pytest.mark.asyncio
async def test_vault_sink_filename_pattern(tmp_path):
    sink = VaultSink(tmp_path)
    await sink.write(_sample_export(sample="S-042"))
    files = list(tmp_path.glob("*.md"))
    assert files[0].name.startswith("2026-05-07_S-042_")
    assert files[0].name.endswith(".md")


@pytest.mark.asyncio
async def test_vault_sink_idempotent_overwrite(tmp_path):
    sink = VaultSink(tmp_path)
    await sink.write(_sample_export())
    result = await sink.write(_sample_export(notes="updated note"))
    assert result.success
    files = list(tmp_path.glob("*.md"))
    assert len(files) == 1
    assert "updated note" in files[0].read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_vault_sink_failure_returns_error_result(tmp_path, monkeypatch):
    """If write fails, sink returns a failure SinkResult instead of raising."""
    sink = VaultSink(tmp_path)

    def _explode(*_a, **_kw):
        raise OSError("disk full")

    monkeypatch.setattr("pathlib.Path.write_text", _explode)
    result = await sink.write(_sample_export())
    assert not result.success
    assert "disk full" in (result.error or "")
