"""The dimension contract has to survive build -> stored index -> query.

Review of 2026-09-05 reproduced the gap this file closes: config and indexer
were moved to 4096 dimensions together, the index built correctly, and every
search returned nothing, because ``RagSearcher.search`` still measured the
query against a hardcoded ``expected_dim = 1024``. Both halves were internally
consistent and the whole was broken.

The lesson encoded here is that a test asserting the CLI *passes* an
``embedding_dim`` cannot establish any of this. Only building an index at a
dimension and then searching it can, so that is what these tests do — against
a real LanceDB table, at a dimension that is deliberately not 1024.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cryodaq.agents.rag.indexer import build_index
from cryodaq.agents.rag.searcher import RagSearcher

# Deliberately not 1024. A regression that reintroduces any hardcoded width
# has to fail here rather than pass by coincidence.
NON_DEFAULT_DIM = 4096


class _FixedWidthEmbeddings:
    """Deterministic vectors of a chosen width, so retrieval is checkable."""

    def __init__(self, dim: int) -> None:
        self.dim = dim

    async def embed(self, text: str) -> list[float]:
        # A crude but stable text->vector map: identical text embeds
        # identically, so the nearest neighbour of a query is its own chunk.
        vec = [0.0] * self.dim
        for i, ch in enumerate(text[: self.dim]):
            vec[i] = (ord(ch) % 32) / 32.0
        return vec


def _seed_procedures(root: Path) -> Path:
    d = root / "procedures"
    d.mkdir(parents=True)
    (d / "cooldown.md").write_text(
        "# Cooldown protocol\n\nOpen the helium valve before starting the compressor.",
        encoding="utf-8",
    )
    (d / "vacuum.md").write_text(
        "# Vacuum protocol\n\nPump to below ten to the minus four millibar first.",
        encoding="utf-8",
    )
    return d


@pytest.mark.asyncio
@pytest.mark.parametrize("dim", [1024, NON_DEFAULT_DIM])
async def test_an_index_built_at_a_dimension_can_be_searched_at_it(tmp_path: Path, dim: int):
    """The whole point: build at `dim`, then actually get results back."""
    procedures = _seed_procedures(tmp_path)
    db_path = tmp_path / "db"
    client = _FixedWidthEmbeddings(dim)

    stats = await build_index(
        experiments_dir=tmp_path / "none",
        vault_dir=None,
        sqlite_path=None,
        db_path=db_path,
        embeddings_client=client,
        embedding_dim=dim,
        procedures_dir=procedures,
    )
    assert stats["indexed"] > 0
    assert stats["promoted"] is True

    searcher = RagSearcher(db_path=db_path, embeddings_client=client)
    results = await searcher.search("Open the helium valve", top_k=3)

    assert results, (
        f"index built at {dim} dimensions returned no search results — the "
        "dimension contract is broken between build and query"
    )


@pytest.mark.asyncio
async def test_a_genuine_mismatch_is_still_refused(tmp_path: Path):
    """Reading the width from the index must not mean accepting anything."""
    procedures = _seed_procedures(tmp_path)
    db_path = tmp_path / "db"

    await build_index(
        experiments_dir=tmp_path / "none",
        vault_dir=None,
        sqlite_path=None,
        db_path=db_path,
        embeddings_client=_FixedWidthEmbeddings(NON_DEFAULT_DIM),
        embedding_dim=NON_DEFAULT_DIM,
        procedures_dir=procedures,
    )

    # Query with a model of a different width than the index was built at.
    searcher = RagSearcher(db_path=db_path, embeddings_client=_FixedWidthEmbeddings(768))
    assert await searcher.search("Open the helium valve") == []
