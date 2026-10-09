"""F31 — SinkRegistry: load sinks from YAML, dispatch exports concurrently."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import yaml

from cryodaq.sinks.base import ExperimentExport, Sink, SinkResult
from cryodaq.sinks.rag_index_sink import RAGIndexSink
from cryodaq.sinks.vault_sink import VaultSink
from cryodaq.sinks.webhook_sink import WebhookSink

logger = logging.getLogger(__name__)


class SinkRegistry:
    """Holds configured sinks and dispatches exports to all enabled ones."""

    def __init__(self, max_log: int = 1000) -> None:
        self._sinks: list[Sink] = []
        self._results_log: list[SinkResult] = []
        self._max_log = max_log

    @property
    def sinks(self) -> list[Sink]:
        return list(self._sinks)

    def load_config(self, config_path: Path) -> None:
        """Load sinks from YAML.

        Format::

            sinks:
              vault:
                enabled: true
                directory: "~/CryoDAQ-Vault/experiments"
              webhooks:
                - enabled: true
                  url: "http://localhost:3001/api/ingest"
                  timeout_s: 10.0
                  verify_ssl: true
                  extra_headers:
                    Authorization: "Bearer ..."
              rag_index:           # F32 Stage 2 (v0.55.7)
                enabled: true
                rag_config_path: "config/rag.yaml"
                experiments_dir: "data/experiments"
                vault_dir: "~/CryoDAQ-Vault/experiments"  # optional
                sqlite_path: "data/cryodaq.db"            # optional
        """
        if not config_path.exists():
            logger.info("Sinks config not found: %s — sinks disabled", config_path)
            return
        with config_path.open(encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        sinks_cfg = raw.get("sinks", {}) or {}

        vault_cfg = sinks_cfg.get("vault") or {}
        if vault_cfg.get("enabled", False):
            vault_dir = Path(vault_cfg.get("directory", "~/CryoDAQ-Vault/experiments"))
            self._sinks.append(VaultSink(vault_dir))
            logger.info("VaultSink registered: %s", vault_dir)

        for wh in sinks_cfg.get("webhooks", []) or []:
            if not wh.get("enabled", False):
                continue
            url = wh.get("url")
            if not url:
                continue
            self._sinks.append(
                WebhookSink(
                    url=str(url),
                    timeout_s=float(wh.get("timeout_s", 10.0)),
                    verify_ssl=bool(wh.get("verify_ssl", True)),
                    extra_headers=wh.get("extra_headers") or {},
                )
            )
            logger.info("WebhookSink registered: %s", url)

        # F32 Stage 2 (v0.55.7) — auto-rebuild the RAG index after each
        # finalize. Skipped silently when missing or disabled so legacy
        # sinks.yaml files keep working.
        rag_cfg = sinks_cfg.get("rag_index") or {}
        if rag_cfg.get("enabled", False):
            experiments_dir_raw = rag_cfg.get("experiments_dir")
            if not experiments_dir_raw:
                logger.warning(
                    "RAGIndexSink config missing experiments_dir; skipping"
                )
            else:
                rag_yaml = Path(rag_cfg.get("rag_config_path", "config/rag.yaml"))
                vault_raw = rag_cfg.get("vault_dir")
                sqlite_raw = rag_cfg.get("sqlite_path")
                self._sinks.append(
                    RAGIndexSink(
                        rag_config_path=rag_yaml,
                        experiments_dir=Path(str(experiments_dir_raw)).expanduser(),
                        vault_dir=(
                            Path(str(vault_raw)).expanduser() if vault_raw else None
                        ),
                        sqlite_path=(
                            Path(str(sqlite_raw)).expanduser() if sqlite_raw else None
                        ),
                    )
                )
                logger.info("RAGIndexSink registered: rag_config=%s", rag_yaml)

    async def dispatch(self, export: ExperimentExport) -> list[SinkResult]:
        """Fire all sinks concurrently. Failures captured in SinkResult; never raises.

        Uses `return_exceptions=True` and converts any sink that misbehaves
        (raises instead of returning a SinkResult) into a failure entry, so
        a buggy third-party Sink subclass cannot break the engine.
        """
        if not self._sinks:
            return []
        coros = [sink.write(export) for sink in self._sinks]
        raw = await asyncio.gather(*coros, return_exceptions=True)
        results: list[SinkResult] = []
        for sink, item in zip(self._sinks, raw, strict=True):
            if isinstance(item, BaseException):
                logger.warning(
                    "Sink %s raised %s — converting to failure",
                    sink.name,
                    type(item).__name__,
                )
                results.append(
                    SinkResult(
                        sink_name=sink.name,
                        success=False,
                        target="",
                        error=f"{type(item).__name__}: {item}",
                    )
                )
            else:
                results.append(item)
        for r in results:
            self._results_log.append(r)
            if not r.success:
                logger.warning("Sink %s failed: %s", r.sink_name, r.error)
        if len(self._results_log) > self._max_log:
            self._results_log = self._results_log[-self._max_log :]
        return results

    @property
    def recent_results(self) -> list[SinkResult]:
        return list(self._results_log)
