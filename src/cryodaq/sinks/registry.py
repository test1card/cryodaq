"""F31 — SinkRegistry: load sinks from YAML, dispatch exports concurrently."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import yaml

from cryodaq.sinks.base import ExperimentExport, Sink, SinkResult
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

    async def dispatch(self, export: ExperimentExport) -> list[SinkResult]:
        """Fire all sinks concurrently. Failures logged; never raises."""
        if not self._sinks:
            return []
        tasks = [sink.write(export) for sink in self._sinks]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        for r in results:
            self._results_log.append(r)
            if not r.success:
                logger.warning("Sink %s failed: %s", r.sink_name, r.error)
        if len(self._results_log) > self._max_log:
            self._results_log = self._results_log[-self._max_log :]
        return list(results)

    @property
    def recent_results(self) -> list[SinkResult]:
        return list(self._results_log)
