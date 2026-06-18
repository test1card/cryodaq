"""F31 — WebhookSink: POST experiment payload to configured URL."""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime

import aiohttp

from cryodaq.sinks.base import ExperimentExport, Sink, SinkResult

logger = logging.getLogger(__name__)


def _serialize_export(export: ExperimentExport) -> dict:
    """Serialize an ExperimentExport to a JSON-safe dict."""
    payload = asdict(export)
    for key in ("started_at", "ended_at"):
        value = payload.get(key)
        if isinstance(value, datetime):
            payload[key] = value.isoformat()
        elif value is not None:
            payload[key] = str(value)
    return payload


class WebhookSink(Sink):
    """POSTs JSON to a configured URL on experiment finalize."""

    name = "webhook"

    def __init__(
        self,
        url: str,
        *,
        timeout_s: float = 10.0,
        verify_ssl: bool = True,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self._url = url
        self._timeout_s = timeout_s
        self._verify_ssl = verify_ssl
        self._extra_headers = dict(extra_headers or {})

    @property
    def url(self) -> str:
        return self._url

    async def write(self, export: ExperimentExport) -> SinkResult:
        payload = _serialize_export(export)
        headers = {"Content-Type": "application/json"}
        headers.update(self._extra_headers)
        sink_name = f"webhook:{self._url}"
        try:
            timeout = aiohttp.ClientTimeout(total=self._timeout_s)
            connector = aiohttp.TCPConnector(verify_ssl=self._verify_ssl)
            async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
                async with session.post(self._url, json=payload, headers=headers) as resp:
                    body_preview = (await resp.text())[:200]
                    if resp.status >= 400:
                        return SinkResult(
                            sink_name=sink_name,
                            success=False,
                            target=self._url,
                            error=f"HTTP {resp.status}: {body_preview}",
                        )
                    return SinkResult(
                        sink_name=sink_name,
                        success=True,
                        target=self._url,
                    )
        except (aiohttp.ClientError, TimeoutError) as exc:
            logger.warning("WebhookSink %s failed: %s", self._url, exc)
            return SinkResult(
                sink_name=sink_name,
                success=False,
                target=self._url,
                error=str(exc),
            )
