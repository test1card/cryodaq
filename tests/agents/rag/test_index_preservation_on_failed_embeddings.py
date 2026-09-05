"""A failed rebuild must not cost the operator the index they already had.

Before this, `build_index` substituted a zero vector for every chunk whose
embedding failed, promoted that corpus over the canonical table, and only then
did the CLI exit 5. Review of 2026-09-05 put it exactly right: a non-zero exit
"makes the failure visible after the damage, not subject to an operator
decision". A zero vector is not searchable, so the trade was a working index
for one that silently answers nothing.

The rebuild is now abandoned instead, and the previous corpus is left alone.
Partial promotion remains available, but only by asking for it.
"""

from __future__ import annotations

from pathlib import Path

import lancedb
import pytest

from cryodaq.agents.rag.indexer import build_index

DIM = 256


class _GoodEmbeddings:
    async def embed(self, text: str) -> list[float]:
        return [(hash(text) % 100) / 100.0] * DIM


class _FailsOnOneChunk:
    """Returns [] for one chunk — an Ollama timeout, the real-world case."""

    def __init__(self, failing_substring: str) -> None:
        self._failing = failing_substring
        self.calls = 0

    async def embed(self, text: str) -> list[float]:
        self.calls += 1
        if self._failing in text:
            return []
        return [0.5] * DIM


def _seed(root: Path, body: str) -> Path:
    d = root / "procedures"
    d.mkdir(parents=True, exist_ok=True)
    (d / "protocol.md").write_text(body, encoding="utf-8")
    return d


async def _build(tmp_path: Path, procedures: Path, client, **kw):
    return await build_index(
        experiments_dir=tmp_path / "none",
        vault_dir=None,
        sqlite_path=None,
        db_path=tmp_path / "db",
        embeddings_client=client,
        embedding_dim=DIM,
        procedures_dir=procedures,
        **kw,
    )


def _rows(tmp_path: Path) -> int:
    db = lancedb.connect(str(tmp_path / "db"))
    if "cryodaq_corpus" not in db.list_tables().tables:
        return 0
    return db.open_table("cryodaq_corpus").count_rows()


@pytest.mark.asyncio
async def test_a_working_index_survives_a_rebuild_whose_embeddings_fail(
    tmp_path: Path,
):
    procedures = _seed(tmp_path, "# Good\n\nThe original corpus, fully embedded.")
    first = await _build(tmp_path, procedures, _GoodEmbeddings())
    assert first["promoted"] is True
    baseline = _rows(tmp_path)
    assert baseline > 0

    # A second rebuild over different content, where one chunk cannot embed.
    _seed(tmp_path, "# Replacement\n\nSOMETHING UNEMBEDDABLE lives in this corpus.")
    second = await _build(tmp_path, procedures, _FailsOnOneChunk("UNEMBEDDABLE"))

    assert second["failed"] >= 1
    assert second["promoted"] is False, "a damaged corpus was promoted"
    assert _rows(tmp_path) == baseline, "the previously working index was replaced"


@pytest.mark.asyncio
async def test_the_preserved_index_is_still_the_old_content(tmp_path: Path):
    """Preserved must mean untouched, not merely 'a table of the same size'."""
    procedures = _seed(tmp_path, "# Good\n\nHelium valve opens before the compressor.")
    await _build(tmp_path, procedures, _GoodEmbeddings())

    _seed(tmp_path, "# Replacement\n\nUNEMBEDDABLE replacement text entirely.")
    await _build(tmp_path, procedures, _FailsOnOneChunk("UNEMBEDDABLE"))

    db = lancedb.connect(str(tmp_path / "db"))
    texts = " ".join(r["text"] for r in db.open_table("cryodaq_corpus").search().limit(50).to_list())
    assert "Helium valve" in texts
    assert "UNEMBEDDABLE" not in texts


@pytest.mark.asyncio
async def test_partial_promotion_remains_possible_but_must_be_asked_for(
    tmp_path: Path,
):
    procedures = _seed(tmp_path, "# Good\n\nThe original corpus.")
    await _build(tmp_path, procedures, _GoodEmbeddings())

    _seed(tmp_path, "# Replacement\n\nUNEMBEDDABLE but wanted anyway.")
    stats = await _build(
        tmp_path,
        procedures,
        _FailsOnOneChunk("UNEMBEDDABLE"),
        promote_on_partial=True,
    )

    assert stats["failed"] >= 1
    assert stats["promoted"] is True

    db = lancedb.connect(str(tmp_path / "db"))
    texts = " ".join(r["text"] for r in db.open_table("cryodaq_corpus").search().limit(50).to_list())
    assert "UNEMBEDDABLE" in texts
