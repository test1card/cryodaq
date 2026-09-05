"""`rag.embedding_dim` must reach the indexer, and a mismatch must be fatal.

Two defects, found by actually running a rebuild on 2026-09-05 rather than by
any test:

1. `embedding_dim` was documented in `rag.yaml.example`, read into `rag_cfg` by
   `index_main`, and never passed to `build_index`. The indexer always used its
   own 1024 default, so changing the embedding model could not work through
   configuration at all.

2. A wrong-width vector was treated as a per-chunk failure: warn, substitute a
   zero vector, continue. With the model and config disagreeing that is true of
   EVERY chunk, so the run produced 3638 zero vectors and would have swapped
   that index in — `_swap_table_atomically` validates row COUNT, not content.

The distinction that matters: an EMPTY vector is one failed call and the next
may succeed, so degrading by one chunk is right. A WRONG-LENGTH vector is a
property of the model, cannot improve, and must stop the run before it costs
the index.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
import yaml

from cryodaq.agents.rag.indexer import RagEmbeddingDimensionError, build_index

_ROOT = Path(__file__).resolve().parents[2]


class _FixedWidthEmbedder:
    def __init__(self, width: int) -> None:
        self._width = width

    async def embed(self, text: str) -> list[float]:
        return [0.01] * self._width

    async def close(self) -> None:
        # index_main closes the client in a finally block; a double that omits
        # this makes the CLI raise AttributeError rather than exercise the path.
        return None


def test_the_cli_passes_the_configured_dimension(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The key must reach build_index, not merely be read into a dict.

    Rewritten 2026-09-05 after review. This test used to read index_main's
    source with `inspect.getsource` and assert the substring "embedding_dim="
    appeared in it. Review put it exactly right: checking that the CLI source
    contains embedding_dim= cannot establish that the dimension is carried
    through. It would pass for a call that passed the wrong value, for one
    inside dead code, and for a comment — this file's own docstring mentions
    the key several times.

    It now runs index_main and records what build_index was actually called
    with.
    """
    config = tmp_path / "rag.yaml"
    config.write_text(
        f"rag:\n  embedding_model: qwen3-embedding:8b\n  embedding_dim: 4096\n  db_path: {tmp_path / 'idx'}\n",
        encoding="utf-8",
    )

    seen: dict[str, object] = {}

    async def _fake_build_index(**kwargs):
        seen.update(kwargs)
        return {
            "chunks": 0,
            "embedded": 0,
            "failed": 0,
            "indexed": 0,
            "promoted": False,
            "db_path": str(kwargs.get("db_path")),
            "table": "cryodaq_corpus",
        }

    from cryodaq.agents.rag import cli as rag_cli

    monkeypatch.setattr(rag_cli, "build_index", _fake_build_index)
    monkeypatch.setattr(rag_cli, "_make_embeddings", lambda cfg: _FixedWidthEmbedder(4096))
    monkeypatch.setattr(rag_cli, "_find_latest_sqlite", lambda: None)
    monkeypatch.setattr(sys, "argv", ["cryodaq-rag-index", "--config", str(config), "--no-sqlite"])

    rag_cli.index_main()

    assert seen.get("embedding_dim") == 4096, (
        f"index_main passed embedding_dim={seen.get('embedding_dim')!r}; the configured 4096 did not reach build_index"
    )


def test_a_wrong_width_model_stops_the_run(tmp_path: Path) -> None:
    with pytest.raises(RagEmbeddingDimensionError) as excinfo:
        asyncio.run(
            build_index(
                experiments_dir=_ROOT / "data" / "experiments",
                vault_dir=None,
                sqlite_path=None,
                db_path=tmp_path / "idx",
                embeddings_client=_FixedWidthEmbedder(4096),
                embedding_dim=1024,
                pdf_dir=None,
                procedures_dir=None,
                reference_root=_ROOT,
            )
        )
    message = str(excinfo.value)
    # It must name both numbers and the remedy, or the operator is left guessing.
    assert "4096" in message and "1024" in message
    assert "embedding_dim" in message


def test_the_failed_run_leaves_no_index_behind(tmp_path: Path) -> None:
    """Stopping early must not create a half-built table."""

    db_path = tmp_path / "idx"
    with pytest.raises(RagEmbeddingDimensionError):
        asyncio.run(
            build_index(
                experiments_dir=_ROOT / "data" / "experiments",
                vault_dir=None,
                sqlite_path=None,
                db_path=db_path,
                embeddings_client=_FixedWidthEmbedder(4096),
                embedding_dim=1024,
                pdf_dir=None,
                procedures_dir=None,
                reference_root=_ROOT,
            )
        )
    import lancedb

    if db_path.exists():
        assert not list(lancedb.connect(str(db_path)).table_names()), "a refused rebuild must not leave a table behind"


def test_the_shipped_config_matches_the_shipped_model() -> None:
    """config/rag.yaml must not claim a width its model does not produce.

    Pins the pairing, not the number: change both together or this fails.
    """

    cfg = yaml.safe_load((_ROOT / "config" / "rag.yaml").read_text(encoding="utf-8"))["rag"]
    known_widths = {
        "qwen3-embedding:8b": 4096,
        "qwen3-embedding:4b": 2560,
        "qwen3-embedding:0.6b": 1024,
    }
    model = cfg["embedding_model"]
    if model in known_widths:
        assert int(cfg["embedding_dim"]) == known_widths[model], (
            f"{model} produces {known_widths[model]}-dim vectors but embedding_dim is {cfg['embedding_dim']}"
        )
