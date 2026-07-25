"""Live finalization must never expose the offline RAG index mutation."""

from __future__ import annotations

import asyncio
import importlib
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from cryodaq.sinks import SinkRegistry
from cryodaq.sinks.base import ExperimentExport


def _export() -> ExperimentExport:
    return ExperimentExport(
        experiment_id="exp-1",
        title="Completed run",
        sample="sample-A",
        operator="operator",
        status="completed",
        started_at=datetime(2025, 12, 1, 8, 0, tzinfo=UTC),
        ended_at=datetime(2025, 12, 1, 16, 0, tzinfo=UTC),
        duration_h=8.0,
    )


def test_rag_index_sink_module_is_not_importable() -> None:
    with pytest.raises(ModuleNotFoundError) as caught:
        importlib.import_module("cryodaq.sinks.rag_index_sink")
    assert caught.value.name == "cryodaq.sinks.rag_index_sink"


def test_registry_rejects_live_rag_index_when_enabled(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forbidden_target = tmp_path / "live-index-must-not-exist"
    build_index = AsyncMock(return_value={"indexed": 1})
    monkeypatch.setattr("cryodaq.agents.rag.indexer.build_index", build_index)
    sinks_yaml = tmp_path / "sinks.yaml"
    sinks_yaml.write_text(
        f"sinks:\n  rag_index:\n    enabled: true\n    db_path: '{forbidden_target}'\n",
        encoding="utf-8",
    )

    registry = SinkRegistry()
    with caplog.at_level("WARNING"):
        registry.load_config(sinks_yaml)
    results = asyncio.run(registry.dispatch(_export()))

    assert registry.sinks == []
    assert results == []
    build_index.assert_not_awaited()
    assert not forbidden_target.exists()
    assert any("live RAG index rebuild is disabled" in record.message for record in caplog.records)


def test_registry_skips_disabled_rag_index(tmp_path: Path) -> None:
    sinks_yaml = tmp_path / "sinks.yaml"
    sinks_yaml.write_text(
        "sinks:\n  rag_index:\n    enabled: false\n",
        encoding="utf-8",
    )

    registry = SinkRegistry()
    registry.load_config(sinks_yaml)

    assert registry.sinks == []
    assert asyncio.run(registry.dispatch(_export())) == []


def test_registry_legacy_yaml_without_rag_index_section_still_loads(tmp_path: Path) -> None:
    sinks_yaml = tmp_path / "sinks.yaml"
    sinks_yaml.write_text(
        f"sinks:\n  vault:\n    enabled: true\n    directory: '{tmp_path / 'vault'}'\n",
        encoding="utf-8",
    )

    registry = SinkRegistry()
    registry.load_config(sinks_yaml)

    assert len(registry.sinks) == 1
    assert registry.sinks[0].name == "vault"
