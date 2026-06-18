"""F31 — WebhookSink tests (round-trip against a local aiohttp server)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from aiohttp import web

from cryodaq.sinks.base import ExperimentExport
from cryodaq.sinks.webhook_sink import WebhookSink, _serialize_export


def _sample_export() -> ExperimentExport:
    return ExperimentExport(
        experiment_id="abc",
        title="t",
        sample="s",
        operator="o",
        status="COMPLETED",
        started_at=datetime(2026, 5, 7, 10, 0, tzinfo=UTC),
        ended_at=datetime(2026, 5, 7, 14, 0, tzinfo=UTC),
        duration_h=4.0,
        template_id="custom",
    )


def test_serialize_export_converts_datetime_to_iso():
    payload = _serialize_export(_sample_export())
    assert payload["started_at"] == "2026-05-07T10:00:00+00:00"
    assert payload["ended_at"] == "2026-05-07T14:00:00+00:00"
    assert payload["experiment_id"] == "abc"


def test_serialize_export_handles_no_ended_at():
    export = ExperimentExport(
        experiment_id="abc",
        title="t",
        sample="s",
        operator="o",
        status="RUNNING",
        started_at=datetime(2026, 5, 7, 10, 0, tzinfo=UTC),
        ended_at=None,
    )
    payload = _serialize_export(export)
    assert payload["ended_at"] is None


@pytest.mark.asyncio
async def test_webhook_sink_posts_json():
    received: list[dict] = []

    async def handler(request: web.Request) -> web.Response:
        received.append(await request.json())
        return web.json_response({"ok": True})

    app = web.Application()
    app.router.add_post("/ingest", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]

    try:
        sink = WebhookSink(url=f"http://127.0.0.1:{port}/ingest", timeout_s=2.0)
        result = await sink.write(_sample_export())
        assert result.success
        assert len(received) == 1
        assert received[0]["experiment_id"] == "abc"
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_webhook_sink_records_4xx_as_failure():
    async def handler(request: web.Request) -> web.Response:
        return web.Response(status=400, text="bad request body")

    app = web.Application()
    app.router.add_post("/ingest", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]

    try:
        sink = WebhookSink(url=f"http://127.0.0.1:{port}/ingest", timeout_s=2.0)
        result = await sink.write(_sample_export())
        assert not result.success
        assert "HTTP 400" in (result.error or "")
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_webhook_sink_records_unreachable_host_as_failure():
    sink = WebhookSink(url="http://127.0.0.1:1/nope", timeout_s=0.5)
    result = await sink.write(_sample_export())
    assert not result.success
    assert result.error
