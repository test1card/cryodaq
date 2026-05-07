"""F32 Stage 2 (v0.55.7) — RAGIndexSink: rebuild the RAG corpus on finalize.

The F32 Stage 1 indexer (``cryodaq.agents.rag.indexer.build_index``) only
exposes a full-corpus rebuild — there is no public ``add_documents`` /
``upsert`` API yet. So this sink simply re-runs ``build_index`` after each
experiment finalize, picking up the freshly archived experiment metadata
along with everything the indexer already covered (vault notes, operator
log entries).

Cost: a full rebuild walks every experiment in the archive directory plus
the vault and operator-log SQLite. For the small CryoDAQ corpus this
finishes within tens of seconds; for very large archives this becomes a
real cost. An incremental indexer is tracked as future work — once
``RAGIndexer.add_documents_for_experiment`` exists, this sink should
switch to it without touching its public ``write()`` contract.

Failures are absorbed into :class:`SinkResult` (``success=False``) rather
than raised so the engine's finalize path never blocks on a flaky
embedding model or a transient LanceDB lock.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from cryodaq.sinks.base import ExperimentExport, Sink, SinkResult

logger = logging.getLogger(__name__)


_DEFAULT_DB_PATH = "data/rag_index"
_DEFAULT_TABLE = "cryodaq_corpus"
_DEFAULT_OLLAMA_URL = "http://localhost:11434"
_DEFAULT_EMBEDDING_MODEL = "multilingual-e5-small"


class RAGIndexSink(Sink):
    """Trigger a full RAG-index rebuild after experiment finalize.

    Parameters mirror the keys in ``config/rag.yaml`` so a freshly cloned
    repo can wire this sink without any extra config:

    - ``rag_config_path`` points at the YAML the engine already parses.
    - ``experiments_dir`` is the archive root that ``build_index`` walks.
    - ``vault_dir`` / ``sqlite_path`` are passed through verbatim; both
      may be ``None`` to skip those corpus walkers.
    """

    name = "rag_index"

    def __init__(
        self,
        *,
        rag_config_path: Path,
        experiments_dir: Path,
        vault_dir: Path | None = None,
        sqlite_path: Path | None = None,
    ) -> None:
        self._rag_config_path = Path(rag_config_path)
        self._experiments_dir = Path(experiments_dir)
        self._vault_dir = Path(vault_dir) if vault_dir is not None else None
        self._sqlite_path = Path(sqlite_path) if sqlite_path is not None else None

    @property
    def rag_config_path(self) -> Path:
        return self._rag_config_path

    async def write(self, export: ExperimentExport) -> SinkResult:
        try:
            cfg = self._load_rag_config()
        except OSError as exc:
            logger.warning("RAGIndexSink: cannot read %s: %s", self._rag_config_path, exc)
            return SinkResult(
                sink_name=self.name,
                success=False,
                target=str(self._rag_config_path),
                error=f"config read failed: {exc}",
            )
        except yaml.YAMLError as exc:
            logger.warning("RAGIndexSink: malformed YAML in %s: %s", self._rag_config_path, exc)
            return SinkResult(
                sink_name=self.name,
                success=False,
                target=str(self._rag_config_path),
                error=f"yaml parse failed: {exc}",
            )

        try:
            stats = await self._rebuild_index(cfg)
        except Exception as exc:  # noqa: BLE001 — never raise out of a sink.
            logger.warning(
                "RAGIndexSink: rebuild failed after finalize of %s: %s",
                export.experiment_id,
                exc,
                exc_info=True,
            )
            return SinkResult(
                sink_name=self.name,
                success=False,
                target=str(cfg.get("db_path", _DEFAULT_DB_PATH)),
                error=str(exc),
            )

        logger.info(
            "RAGIndexSink: rebuilt index for %s — chunks=%s embedded=%s indexed=%s",
            export.experiment_id,
            stats.get("chunks"),
            stats.get("embedded"),
            stats.get("indexed"),
        )
        return SinkResult(
            sink_name=self.name,
            success=True,
            target=str(stats.get("db_path", "")),
        )

    # ------------------------------------------------------------------
    # Internals — kept private so unit tests can monkey-patch them.
    # ------------------------------------------------------------------

    def _load_rag_config(self) -> dict[str, Any]:
        if not self._rag_config_path.exists():
            return {}
        text = self._rag_config_path.read_text(encoding="utf-8")
        raw = yaml.safe_load(text) or {}
        return raw.get("rag", {}) or {}

    async def _rebuild_index(self, cfg: dict[str, Any]) -> dict[str, Any]:
        # Lazy imports so projects without lancedb/pyarrow installed never
        # pay the import cost just because the sink module is registered.
        from cryodaq.agents.rag.embeddings import EmbeddingsClient
        from cryodaq.agents.rag.indexer import build_index

        # Path manipulation here is pure string handling (expanduser does
        # not hit the filesystem); ASYNC240 false-positives on it.
        db_path = Path(str(cfg.get("db_path", _DEFAULT_DB_PATH))).expanduser()  # noqa: ASYNC240
        table_name = str(cfg.get("table_name", _DEFAULT_TABLE))
        emb_url = str(cfg.get("ollama_base_url", _DEFAULT_OLLAMA_URL))
        emb_model = str(cfg.get("embedding_model", _DEFAULT_EMBEDDING_MODEL))

        embeddings = EmbeddingsClient(base_url=emb_url, model=emb_model)
        return await build_index(
            experiments_dir=self._experiments_dir,
            vault_dir=self._vault_dir,
            sqlite_path=self._sqlite_path,
            db_path=db_path,
            embeddings_client=embeddings,
            table_name=table_name,
        )
