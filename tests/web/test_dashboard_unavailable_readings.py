"""Browser regressions for unavailable values on the served dashboard."""

from __future__ import annotations

import socket
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime

import httpx
import pytest
import uvicorn
from playwright.sync_api import Browser, sync_playwright

import cryodaq.web.server as server
from cryodaq.drivers.base import ChannelStatus, Reading


@asynccontextmanager
async def _no_background_workers(_app):
    """Serve the page without connecting this browser regression to ZMQ."""
    yield


@contextmanager
def _served_dashboard() -> str:
    """Run the real FastAPI application on loopback for browser fetches."""
    app = server.create_app()
    app.router.lifespan_context = _no_background_workers
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    host, port = listener.getsockname()
    uvicorn_server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    thread = threading.Thread(target=uvicorn_server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    base_url = f"http://{host}:{port}"
    deadline = time.monotonic() + 5
    while True:
        try:
            if httpx.get(base_url + "/", timeout=0.2).is_success:
                break
        except httpx.HTTPError:
            pass
        if time.monotonic() >= deadline:
            uvicorn_server.should_exit = True
            thread.join(timeout=5)
            raise AssertionError("served dashboard did not start")
        time.sleep(0.05)
    try:
        yield base_url
    finally:
        uvicorn_server.should_exit = True
        thread.join(timeout=5)


@pytest.fixture
def dashboard_payload(monkeypatch) -> None:
    """Feed the public cache through its production non-finite-value path."""

    async def _engine_reply(command: dict[str, object]) -> dict[str, object]:
        command_name = command["cmd"]
        if command_name == "safety_status":
            return {"ok": True, "state": "safe"}
        if command_name == "alarm_v2_status":
            return {"ok": True, "active": {}}
        if command_name == "experiment_status":
            return {"ok": True}
        if command_name == "log_get":
            return {"ok": True, "entries": []}
        raise AssertionError(f"unexpected engine command: {command_name}")

    monkeypatch.setattr(server, "_async_engine_command", _engine_reply)
    monkeypatch.setattr(server._state, "last_readings", {})
    monkeypatch.setattr(server._state, "active_alarms", {})
    for channel, value, unit in (
        ("T1", float("nan"), "K"),
        ("vacuum", float("inf"), "mbar"),
        ("keithley/smua/power", float("nan"), "W"),
        ("keithley/smub/power", float("-inf"), "W"),
    ):
        server._on_reading_callback(
            Reading(
                timestamp=datetime.now(UTC),
                instrument_id="test",
                channel=channel,
                value=value,
                unit=unit,
                status=ChannelStatus.SENSOR_ERROR,
            )
        )


@contextmanager
def _browser() -> Browser:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            yield browser
        finally:
            browser.close()


def test_dashboard_renders_api_null_readings_as_unavailable(dashboard_payload) -> None:
    """A non-finite Reading becomes API null and never aborts the served refresh."""
    with _served_dashboard() as base_url:
        response = httpx.get(base_url + "/api/status", timeout=2)
        assert response.status_code == 200
        assert '"value":null' in response.text
        assert "NaN" not in response.text
        assert "Infinity" not in response.text
        unavailable_reading = response.json()["readings"]["T1"]

        with _browser() as browser:
            page = browser.new_page()
            page_errors: list[str] = []
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.goto(base_url + "/", wait_until="networkidle")

            assert page.locator("#temps").inner_text() == "T1\n—"
            assert page.locator("#pressure").inner_text() == "— mbar"
            assert page.locator("#keithley").inner_text() == "A: НЕИЗВЕСТНО │ B: НЕИЗВЕСТНО"
            assert page.locator("#updated").inner_text().startswith("Обновлено:")
            assert not page_errors

            static_page = browser.new_page()
            chart_stub = "class Chart{static defaults={};constructor(){this.data={datasets:[]}}update(){}}"
            static_page.route(
                "https://cdn.jsdelivr.net/npm/chart.js",
                lambda route: route.fulfill(
                    content_type="application/javascript",
                    body=chart_stub,
                ),
            )
            static_page.goto(base_url + "/static/index.html", wait_until="networkidle")
            static_page.evaluate("reading => handleReading(reading)", unavailable_reading)
            assert static_page.evaluate("tempBuffers.get('T1')[0].y") is None
            static_page.evaluate(
                "handleAlarm({alarm_id: 'sensor', state: 'ALARM', severity: 'critical', value: null, unit: 'K'})"
            )
            assert static_page.locator(".alarm-value").inner_text() == "— K"
            static_page.evaluate("renderInstruments({sensor: {total_readings: null}})")
            assert "Показаний: —" in static_page.locator("#instruments-grid").inner_text()


def test_dashboard_marks_last_values_stale_when_a_refresh_fails(dashboard_payload) -> None:
    """A failed refresh keeps context but cannot leave it looking current."""
    with _served_dashboard() as base_url:
        with _browser() as browser:
            page = browser.new_page()
            page.goto(base_url + "/", wait_until="networkidle")
            page.route("**/api/log?limit=5", lambda route: route.abort())
            page.evaluate("refresh()")

            assert page.locator("#updated").inner_text().startswith("Данные устарели:")
