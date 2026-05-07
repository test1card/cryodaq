"""F32 Stage 2 (v0.55.7) — RAGIndexSink tests.

Stubs ``_rebuild_index`` so the tests do not need lancedb / pyarrow at
runtime. Asserts on:

- A successful rebuild emits a SinkResult(success=True) with the LanceDB
  path and never raises.
- A rebuild exception collapses to SinkResult(success=False) instead of
  propagating into the engine's finalize path.
- Missing rag_config_path is tolerated (sink reads with empty config and
  the rebuild stub is still invoked with sane defaults).
- Malformed YAML in rag_config_path is reported as success=False without
  raising YAMLError out of write().
- SinkRegistry honours sinks.rag_index.enabled — disabled config does not
  register the sink.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cryodaq.sinks import RAGIndexSink, SinkRegistry
from cryodaq.sinks.base import ExperimentExport


def _run(coro):
    return asyncio.run(coro)


def _make_export() -> ExperimentExport:
    return ExperimentExport(
        experiment_id="exp-1",
        title="Test cooldown",
        sample="sample-A",
        operator="Иванов",
        status="completed",
        started_at=datetime(2025, 12, 1, 8, 0, tzinfo=UTC),
        ended_at=datetime(2025, 12, 1, 16, 0, tzinfo=UTC),
        duration_h=8.0,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_finalize_triggers_rebuild_and_reports_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rag_yaml = tmp_path / "rag.yaml"
    rag_yaml.write_text(
        "rag:\n"
        f"  db_path: '{tmp_path / 'index'}'\n"
        "  table_name: 'cryodaq_corpus'\n",
        encoding="utf-8",
    )

    sink = RAGIndexSink(
        rag_config_path=rag_yaml,
        experiments_dir=tmp_path / "experiments",
    )

    seen: list[dict] = []

    async def fake_rebuild(self, cfg):  # type: ignore[no-untyped-def]
        seen.append(cfg)
        return {"chunks": 7, "embedded": 7, "indexed": 7, "db_path": "fake/db"}

    monkeypatch.setattr(RAGIndexSink, "_rebuild_index", fake_rebuild)

    result = _run(sink.write(_make_export()))

    assert result.success is True
    assert result.sink_name == "rag_index"
    assert result.target == "fake/db"
    assert len(seen) == 1
    assert seen[0].get("table_name") == "cryodaq_corpus"


def test_finalize_uses_default_config_when_yaml_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing rag.yaml is recoverable — sink falls back to empty cfg dict
    and the rebuild stub still runs (in production, build_index uses its
    own defaults)."""
    sink = RAGIndexSink(
        rag_config_path=tmp_path / "does-not-exist.yaml",
        experiments_dir=tmp_path / "experiments",
    )

    async def fake_rebuild(self, cfg):  # type: ignore[no-untyped-def]
        return {"chunks": 0, "embedded": 0, "indexed": 0, "db_path": "x"}

    monkeypatch.setattr(RAGIndexSink, "_rebuild_index", fake_rebuild)

    result = _run(sink.write(_make_export()))
    assert result.success is True


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_rebuild_exception_does_not_block_finalize(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rag_yaml = tmp_path / "rag.yaml"
    rag_yaml.write_text("rag: {}\n", encoding="utf-8")

    sink = RAGIndexSink(
        rag_config_path=rag_yaml,
        experiments_dir=tmp_path / "experiments",
    )

    async def boom(self, cfg):  # type: ignore[no-untyped-def]
        raise RuntimeError("ollama unreachable")

    monkeypatch.setattr(RAGIndexSink, "_rebuild_index", boom)

    result = _run(sink.write(_make_export()))

    assert result.success is False
    assert "ollama unreachable" in (result.error or "")


def test_malformed_yaml_returns_failure_without_raising(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("rag: {unclosed\n", encoding="utf-8")

    sink = RAGIndexSink(
        rag_config_path=bad,
        experiments_dir=tmp_path / "experiments",
    )

    result = _run(sink.write(_make_export()))

    assert result.success is False
    assert "yaml parse failed" in (result.error or "")


def test_unreadable_config_returns_failure_without_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rag_yaml = tmp_path / "rag.yaml"
    rag_yaml.write_text("rag: {}\n", encoding="utf-8")

    sink = RAGIndexSink(
        rag_config_path=rag_yaml,
        experiments_dir=tmp_path / "experiments",
    )

    def boom(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "read_text", boom)

    result = _run(sink.write(_make_export()))

    assert result.success is False
    assert "config read failed" in (result.error or "")


# ---------------------------------------------------------------------------
# SinkRegistry wiring
# ---------------------------------------------------------------------------


def test_registry_loads_rag_index_when_enabled(tmp_path: Path) -> None:
    sinks_yaml = tmp_path / "sinks.yaml"
    sinks_yaml.write_text(
        "sinks:\n"
        "  rag_index:\n"
        "    enabled: true\n"
        f"    rag_config_path: '{tmp_path / 'rag.yaml'}'\n"
        f"    experiments_dir: '{tmp_path / 'experiments'}'\n",
        encoding="utf-8",
    )

    registry = SinkRegistry()
    registry.load_config(sinks_yaml)

    rag_sinks = [s for s in registry.sinks if isinstance(s, RAGIndexSink)]
    assert len(rag_sinks) == 1
    assert rag_sinks[0].name == "rag_index"


def test_registry_skips_rag_index_when_disabled(tmp_path: Path) -> None:
    sinks_yaml = tmp_path / "sinks.yaml"
    sinks_yaml.write_text(
        "sinks:\n"
        "  rag_index:\n"
        "    enabled: false\n"
        f"    rag_config_path: '{tmp_path / 'rag.yaml'}'\n"
        f"    experiments_dir: '{tmp_path / 'experiments'}'\n",
        encoding="utf-8",
    )

    registry = SinkRegistry()
    registry.load_config(sinks_yaml)

    assert not any(isinstance(s, RAGIndexSink) for s in registry.sinks)


def test_registry_skips_rag_index_when_experiments_dir_missing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    sinks_yaml = tmp_path / "sinks.yaml"
    sinks_yaml.write_text(
        "sinks:\n"
        "  rag_index:\n"
        "    enabled: true\n",
        encoding="utf-8",
    )

    registry = SinkRegistry()
    with caplog.at_level("WARNING"):
        registry.load_config(sinks_yaml)

    assert not any(isinstance(s, RAGIndexSink) for s in registry.sinks)
    assert any("experiments_dir" in rec.message for rec in caplog.records)


def test_registry_legacy_yaml_without_rag_index_section_still_loads(
    tmp_path: Path,
) -> None:
    """Pre-v0.55.7 sinks.yaml files (vault + webhooks only) keep working."""
    sinks_yaml = tmp_path / "sinks.yaml"
    sinks_yaml.write_text(
        "sinks:\n"
        "  vault:\n"
        "    enabled: true\n"
        f"    directory: '{tmp_path / 'vault'}'\n",
        encoding="utf-8",
    )

    registry = SinkRegistry()
    registry.load_config(sinks_yaml)

    # No rag_index sink, vault sink survives unchanged.
    assert not any(isinstance(s, RAGIndexSink) for s in registry.sinks)
    assert len(registry.sinks) == 1
