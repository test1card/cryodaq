"""F32 — CLI: `cryodaq-rag-index` and `cryodaq-rag-search`."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import yaml

from cryodaq.agents.assistant.shared.ollama_client import (
    OllamaModelMissingError,
    OllamaUnavailableError,
)
from cryodaq.agents.rag.embeddings import EmbeddingsClient
from cryodaq.agents.rag.indexer import build_index
from cryodaq.agents.rag.searcher import RagSearcher
from cryodaq.paths import get_config_dir, get_data_dir, get_project_root


def _resolve_rag_config_path(override: Path | None) -> tuple[Path | None, str]:
    """v0.55.14 (audit SCOPE 2 finding 2.5) — resolve the RAG
    config file for the CLI.

    Priority order:
      1. ``--config`` CLI flag (no fallback — explicit means explicit).
      2. ``config/rag.local.yaml`` (machine-specific override).
      3. ``config/rag.yaml`` (live config).
      4. ``config/rag.yaml.example`` (committed defaults — last resort).

    Returns (path, source_label). ``path`` is ``None`` only if the
    explicit ``--config`` was given and missing — that case is caller-
    surfaced as an error. The default path ALWAYS resolves to at least
    ``rag.yaml.example`` because the example ships in-repo.
    """
    if override is not None:
        return (override if override.exists() else None, f"--config {override}")
    config_dir = get_config_dir()
    for candidate, label in (
        (config_dir / "rag.local.yaml", "rag.local.yaml"),
        (config_dir / "rag.yaml", "rag.yaml"),
        (config_dir / "rag.yaml.example", "rag.yaml.example (defaults)"),
    ):
        if candidate.exists():
            return candidate, label
    return None, "no rag config found"


def _load_rag_config(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


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


def _add_config_flag(parser: argparse.ArgumentParser) -> None:
    """v0.55.14 (audit SCOPE 2 finding 2.5) — explicit --config flag."""
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=(
            "Path to a custom rag config YAML. If absent, falls back to "
            "config/rag.local.yaml → config/rag.yaml → "
            "config/rag.yaml.example."
        ),
    )


def index_main() -> None:
    parser = argparse.ArgumentParser(description="Build CryoDAQ RAG index")
    _add_config_flag(parser)
    parser.add_argument("--db-path", default=None, help="LanceDB directory path")
    parser.add_argument("--vault-dir", default=None, help="F31 vault directory")
    parser.add_argument(
        "--no-sqlite",
        action="store_true",
        help="Skip operator-log indexing",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    cfg_path, cfg_source = _resolve_rag_config_path(args.config)
    if args.config is not None and cfg_path is None:
        print(
            f"error: --config {args.config} does not exist",
            file=sys.stderr,
        )
        sys.exit(2)
    print(f"Config: {cfg_source}")

    cfg = _load_rag_config(cfg_path)
    rag_cfg = cfg.get("rag", {}) or {}

    db_path = Path(args.db_path or rag_cfg.get("db_path", get_data_dir() / "rag_index"))
    experiments_dir = get_data_dir() / "experiments"
    vault_dir: Path | None = None
    if args.vault_dir:
        vault_dir = Path(args.vault_dir).expanduser()
    elif rag_cfg.get("vault_dir"):
        vault_dir = Path(rag_cfg["vault_dir"]).expanduser()
    sqlite_path = None if args.no_sqlite else _find_latest_sqlite()

    # v0.55.7.1 — knowledge corpus paths. The defaults match the
    # PHASE 1 folder layout; rag.yaml's `knowledge_dir` overrides root,
    # subdir names follow the convention ${knowledge_dir}/{equipment_manuals,procedures}.
    knowledge_dir = Path(
        rag_cfg.get("knowledge_dir", get_data_dir() / "knowledge")
    ).expanduser()
    pdf_dir = knowledge_dir / "equipment_manuals"
    procedures_dir = knowledge_dir / "procedures"
    reference_root = get_project_root()

    embeddings_client = _make_embeddings(rag_cfg)

    def _progress(done: int, total: int) -> None:
        print(f"  embedded {done}/{total}")

    print(f"Indexing → {db_path}")
    print(f"  experiments: {experiments_dir}")
    print(f"  vault: {vault_dir}")
    print(f"  operator_log: {sqlite_path}")
    print(f"  knowledge.pdf_dir: {pdf_dir}")
    print(f"  knowledge.procedures_dir: {procedures_dir}")
    print(f"  knowledge.reference_root: {reference_root}")

    try:
        stats = asyncio.run(
            build_index(
                experiments_dir=experiments_dir,
                vault_dir=vault_dir,
                sqlite_path=sqlite_path,
                db_path=db_path,
                embeddings_client=embeddings_client,
                progress_cb=_progress,
                pdf_dir=pdf_dir,
                procedures_dir=procedures_dir,
                reference_root=reference_root,
            )
        )
    except OllamaModelMissingError as exc:
        # v0.55.14 (audit SCOPE 2 finding 2.2) — friendly message
        # instead of a bare traceback when the embedding model isn't
        # installed in the local Ollama instance.
        print(
            f"\nerror: embedding model not available in Ollama: {exc}\n"
            f"  hint: run `ollama pull "
            f"{rag_cfg.get('embedding_model', 'multilingual-e5-small')}` "
            f"on the host running ollama",
            file=sys.stderr,
        )
        sys.exit(3)
    except OllamaUnavailableError as exc:
        print(
            f"\nerror: cannot reach Ollama: {exc}\n"
            f"  hint: verify ollama_base_url in {cfg_source} "
            f"({rag_cfg.get('ollama_base_url', 'http://localhost:11434')})",
            file=sys.stderr,
        )
        sys.exit(4)
    finally:
        asyncio.run(embeddings_client.close())
    print(f"Done: {stats}")


def search_main() -> None:
    parser = argparse.ArgumentParser(description="Query CryoDAQ RAG index")
    _add_config_flag(parser)
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

    cfg_path, cfg_source = _resolve_rag_config_path(args.config)
    if args.config is not None and cfg_path is None:
        print(
            f"error: --config {args.config} does not exist",
            file=sys.stderr,
        )
        sys.exit(2)

    cfg = _load_rag_config(cfg_path)
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
    except OllamaModelMissingError as exc:
        print(
            f"\nerror: embedding model not available: {exc}\n"
            f"  hint: run `ollama pull "
            f"{rag_cfg.get('embedding_model', 'multilingual-e5-small')}`",
            file=sys.stderr,
        )
        sys.exit(3)
    except OllamaUnavailableError as exc:
        print(
            f"\nerror: cannot reach Ollama: {exc}\n"
            f"  hint: verify ollama_base_url in {cfg_source}",
            file=sys.stderr,
        )
        sys.exit(4)
    finally:
        asyncio.run(embeddings_client.close())

    print(f"Query: {args.query}")
    print(f"Found {len(results)} results:\n")
    for i, r in enumerate(results, 1):
        print(f"{i}. [{r.source_kind}] {r.source_id} (distance={r.score:.4f})")
        print(f"   {r.text[:200]}")
        print()
