"""F-KnowledgeBaseExpansion (v0.55.7.1) — engine rag.rebuild_* command tests.

PHASE 8: dispatch helper for the GUI «Обновить индекс» button.
Mirrors the test pattern of test_engine_assistant_query_command and
test_engine_rag_search_command — exercise the module-level helper
directly without spinning up the engine.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import cryodaq.engine as engine_mod
from cryodaq.agents.rag.indexer import _EMBEDDING_DIM
from cryodaq.engine import (
    _handle_rag_rebuild_command,
    _rag_rebuild_state,
)


class _MockEmbeddings:
    def __init__(self) -> None:
        self.dim = _EMBEDDING_DIM
        self.calls: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        seed = (hash(text) % 100) / 100.0
        return [seed] * self.dim


@pytest.fixture(autouse=True)
def _reset_state():
    """Reset module-level state between tests so they don't share a buffer."""
    _rag_rebuild_state.update(
        {
            "state": "idle",
            "started_at": None,
            "finished_at": None,
            "chunks_indexed": 0,
            "error": None,
        }
    )
    engine_mod._rag_rebuild_task = None
    yield
    if engine_mod._rag_rebuild_task is not None and not engine_mod._rag_rebuild_task.done():
        engine_mod._rag_rebuild_task.cancel()


def _seed_corpus(root: Path) -> Path:
    knowledge = root / "knowledge"
    procedures = knowledge / "procedures"
    procedures.mkdir(parents=True)
    (procedures / "p.md").write_text("# Title\nbody", encoding="utf-8")
    return knowledge


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# rag.rebuild_status
# ---------------------------------------------------------------------------


def test_rebuild_status_initial_idle():
    out = _run(
        _handle_rag_rebuild_command(
            "rag.rebuild_status",
            {},
            db_path=None,
            embeddings_client=None,
            knowledge_dir=None,
            experiments_dir=None,
            sqlite_path=None,
            repo_root=None,
        )
    )
    assert out["ok"] is True
    assert out["state"] == "idle"
    assert out["chunks_indexed"] == 0


# ---------------------------------------------------------------------------
# rag.rebuild_index
# ---------------------------------------------------------------------------


def test_rebuild_starts_task_returns_running(tmp_path: Path):
    """Manual rebuild kicks off a task and returns state=running."""
    knowledge = _seed_corpus(tmp_path)
    embeddings = _MockEmbeddings()

    async def _scenario():
        out = await _handle_rag_rebuild_command(
            "rag.rebuild_index",
            {},
            db_path=tmp_path / "rag_db",
            embeddings_client=embeddings,
            knowledge_dir=knowledge,
            experiments_dir=tmp_path / "experiments",
            sqlite_path=None,
            repo_root=tmp_path,
        )
        assert out["ok"] is True
        assert out["state"] == "running"
        assert _rag_rebuild_state["state"] == "running"
        # Wait для task to finish before assertion / cleanup.
        if engine_mod._rag_rebuild_task is not None:
            await engine_mod._rag_rebuild_task
        assert _rag_rebuild_state["state"] == "complete"
        assert _rag_rebuild_state["chunks_indexed"] >= 1

    asyncio.run(_scenario())


def test_rebuild_rejects_concurrent_start():
    """Second start while running returns ok=False с running-message."""
    _rag_rebuild_state["state"] = "running"
    _rag_rebuild_state["started_at"] = 1.0
    out = _run(
        _handle_rag_rebuild_command(
            "rag.rebuild_index",
            {},
            db_path=Path("/tmp/db"),
            embeddings_client=_MockEmbeddings(),
            knowledge_dir=Path("/tmp/k"),
            experiments_dir=Path("/tmp/e"),
            sqlite_path=None,
            repo_root=Path("/tmp"),
        )
    )
    assert out["ok"] is False
    assert "Rebuild" in out["error"] or "rebuild" in out["error"].lower()


def test_rebuild_rejects_when_rag_unconfigured():
    """Engine starting без RAG config — explicit Russian error."""
    out = _run(
        _handle_rag_rebuild_command(
            "rag.rebuild_index",
            {},
            db_path=None,
            embeddings_client=None,
            knowledge_dir=None,
            experiments_dir=None,
            sqlite_path=None,
            repo_root=None,
        )
    )
    assert out["ok"] is False
    assert "не сконфигурирован" in out["error"]


def test_rebuild_unknown_action():
    out = _run(
        _handle_rag_rebuild_command(
            "rag.rebuild_explode",
            {},
            db_path=None,
            embeddings_client=None,
            knowledge_dir=None,
            experiments_dir=None,
            sqlite_path=None,
            repo_root=None,
        )
    )
    assert out["ok"] is False
    assert "unknown" in out["error"].lower()


def test_rebuild_failure_logged_in_state(tmp_path: Path, caplog):
    """build_index raising must populate state.error, not propagate."""
    knowledge = _seed_corpus(tmp_path)

    class _BoomEmb:
        async def embed(self, text: str) -> list[float]:
            raise RuntimeError("ollama unreachable")

    async def _scenario():
        out = await _handle_rag_rebuild_command(
            "rag.rebuild_index",
            {},
            db_path=tmp_path / "rag_db",
            embeddings_client=_BoomEmb(),
            knowledge_dir=knowledge,
            experiments_dir=tmp_path / "experiments",
            sqlite_path=None,
            repo_root=tmp_path,
        )
        assert out["ok"] is True
        if engine_mod._rag_rebuild_task is not None:
            await engine_mod._rag_rebuild_task
        assert _rag_rebuild_state["state"] == "failed"
        assert _rag_rebuild_state["error"] is not None
        assert "ollama unreachable" in _rag_rebuild_state["error"]

    asyncio.run(_scenario())


def test_rebuild_status_reports_progress(tmp_path: Path):
    """After start, status reflects running; after completion, complete."""
    knowledge = _seed_corpus(tmp_path)
    embeddings = _MockEmbeddings()

    async def _scenario():
        await _handle_rag_rebuild_command(
            "rag.rebuild_index",
            {},
            db_path=tmp_path / "rag_db",
            embeddings_client=embeddings,
            knowledge_dir=knowledge,
            experiments_dir=tmp_path / "experiments",
            sqlite_path=None,
            repo_root=tmp_path,
        )
        snap_running = await _handle_rag_rebuild_command(
            "rag.rebuild_status",
            {},
            db_path=None,
            embeddings_client=None,
            knowledge_dir=None,
            experiments_dir=None,
            sqlite_path=None,
            repo_root=None,
        )
        assert snap_running["state"] == "running"
        if engine_mod._rag_rebuild_task is not None:
            await engine_mod._rag_rebuild_task
        snap_done = await _handle_rag_rebuild_command(
            "rag.rebuild_status",
            {},
            db_path=None,
            embeddings_client=None,
            knowledge_dir=None,
            experiments_dir=None,
            sqlite_path=None,
            repo_root=None,
        )
        assert snap_done["state"] == "complete"
        assert snap_done["chunks_indexed"] >= 1
        assert snap_done["finished_at"] is not None

    asyncio.run(_scenario())
