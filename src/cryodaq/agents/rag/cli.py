"""F32 — CLI: `cryodaq-rag-index` and `cryodaq-rag-search`."""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

import yaml

from cryodaq.agents.rag.embeddings import EmbeddingsClient
from cryodaq.agents.rag.indexer import build_index
from cryodaq.agents.rag.searcher import RagSearcher
from cryodaq.paths import get_config_dir, get_data_dir


def _load_rag_config() -> dict:
    cfg_path = get_config_dir() / "rag.local.yaml"
    if not cfg_path.exists():
        cfg_path = get_config_dir() / "rag.yaml"
    if cfg_path.exists():
        return yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    return {}


def _find_latest_sqlite() -> Path | None:
    """Pick the newest data_*.db in the data dir as the operator-log source."""
    data_dir = get_data_dir()
    candidates = sorted(data_dir.glob("data_*.db"), reverse=True)
    return candidates[0] if candidates else None


def _make_embeddings(rag_cfg: dict) -> EmbeddingsClient:
    # May 2026: default switched к qwen3-embedding:0.6b — top of MTEB
    # multilingual leaderboard. Previous default (multilingual-e5-small)
    # deprecated due к Ollama 0.23+ incompatibility for community uploads.
    return EmbeddingsClient(
        base_url=rag_cfg.get("ollama_base_url", "http://localhost:11434"),
        model=rag_cfg.get("embedding_model", "qwen3-embedding:0.6b"),
    )


def index_main() -> None:
    parser = argparse.ArgumentParser(description="Build CryoDAQ RAG index")
    parser.add_argument("--db-path", default=None, help="LanceDB directory path")
    parser.add_argument("--vault-dir", default=None, help="F31 vault directory")
    parser.add_argument(
        "--no-sqlite",
        action="store_true",
        help="Skip operator-log indexing",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    cfg = _load_rag_config()
    rag_cfg = cfg.get("rag", {}) or {}

    db_path = Path(args.db_path or rag_cfg.get("db_path", get_data_dir() / "rag_index"))
    experiments_dir = get_data_dir() / "experiments"
    vault_dir: Path | None = None
    if args.vault_dir:
        vault_dir = Path(args.vault_dir).expanduser()
    elif rag_cfg.get("vault_dir"):
        vault_dir = Path(rag_cfg["vault_dir"]).expanduser()
    sqlite_path = None if args.no_sqlite else _find_latest_sqlite()

    embeddings_client = _make_embeddings(rag_cfg)

    def _progress(done: int, total: int) -> None:
        print(f"  embedded {done}/{total}")

    print(f"Indexing → {db_path}")
    print(f"  experiments: {experiments_dir}")
    print(f"  vault: {vault_dir}")
    print(f"  operator_log: {sqlite_path}")

    try:
        stats = asyncio.run(
            build_index(
                experiments_dir=experiments_dir,
                vault_dir=vault_dir,
                sqlite_path=sqlite_path,
                db_path=db_path,
                embeddings_client=embeddings_client,
                progress_cb=_progress,
            )
        )
    finally:
        asyncio.run(embeddings_client.close())
    print(f"Done: {stats}")


def search_main() -> None:
    parser = argparse.ArgumentParser(description="Query CryoDAQ RAG index")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--db-path", default=None)
    parser.add_argument(
        "--source-kind",
        action="append",
        default=None,
        help="Restrict to source_kind (repeatable)",
    )
    args = parser.parse_args()

    cfg = _load_rag_config()
    rag_cfg = cfg.get("rag", {}) or {}
    db_path = Path(args.db_path or rag_cfg.get("db_path", get_data_dir() / "rag_index"))

    embeddings_client = _make_embeddings(rag_cfg)
    searcher = RagSearcher(db_path=db_path, embeddings_client=embeddings_client)

    try:
        results = asyncio.run(
            searcher.search(
                args.query,
                top_k=args.top_k,
                source_kind_filter=args.source_kind,
            )
        )
    finally:
        asyncio.run(embeddings_client.close())

    print(f"Query: {args.query}")
    print(f"Found {len(results)} results:\n")
    for i, r in enumerate(results, 1):
        print(f"{i}. [{r.source_kind}] {r.source_id} (distance={r.score:.4f})")
        print(f"   {r.text[:200]}")
        print()
