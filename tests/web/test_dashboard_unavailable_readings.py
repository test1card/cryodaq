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

import cryodaq.web.server as server
from cryodaq.drivers.base import ChannelStatus, Reading

# Playwright is not a declared dependency and is absent from CI, so importing it
# at module scope turned this file into a collection error on every partition.
# Skipping keeps the harness usable where a browser exists; the contract itself
# is held everywhere by tests/web/test_dashboard_unavailable_contract.py.
sync_playwright = pytest.importorskip(
    "playwright.sync_api",
    reason="browser harness (DEFERRED-BROWSER-01); contract guarded by test_dashboard_unavailable_contract.py",
).sync_playwright


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
def _browser():
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


def test_dashboard_renders_unavailable_cache_as_last_known(dashboard_payload) -> None:
    """A dead bridge must never leave its cached reading looking current."""
    server._on_reading_callback(
        Reading(
            timestamp=datetime.now(UTC),
            instrument_id="test",
            channel="T2",
            value=4.2,
            unit="K",
            status=ChannelStatus.OK,
        )
    )
    server._state.invalidate_producer("ZMQ readings producer stopped")

    with _served_dashboard() as base_url:
        with _browser() as browser:
            page = browser.new_page()
            page.goto(base_url + "/", wait_until="networkidle")

            assert page.locator("#availability").inner_text().startswith("UNAVAILABLE — ZMQ readings producer stopped")
            assert page.locator("#cached-label").inner_text() == "last-known values below"
            assert "T2\n4.20" in page.locator("#temps").inner_text()
            assert page.locator("#alarms").inner_text().startswith("LAST-KNOWN:")
            assert "последнее известное" in page.locator("#experiment").inner_text()


def test_dashboards_do_not_infer_temperature_from_channel_spelling(monkeypatch) -> None:
    """Only the declared unit, never the channel spelling, selects temperature."""

    async def _engine_reply(command: dict[str, object]) -> dict[str, object]:
        replies: dict[str, dict[str, object]] = {
            "safety_status": {"ok": True, "state": "safe"},
            "alarm_v2_status": {"ok": True, "active": {}},
            "experiment_status": {"ok": True},
            "log_get": {"ok": True, "entries": []},
        }
        return replies[str(command["cmd"])]

    monkeypatch.setattr(server, "_async_engine_command", _engine_reply)
    monkeypatch.setattr(server._state, "last_readings", {})
    server._on_reading_callback(
        Reading(
            timestamp=datetime.now(UTC),
            instrument_id="test",
            channel="Т power",
            value=1.2,
            unit="W",
            status=ChannelStatus.OK,
        )
    )

    with _served_dashboard() as base_url:
        with _browser() as browser:
            page = browser.new_page()
            page.goto(base_url + "/", wait_until="networkidle")
            assert page.locator("#temps").inner_text() == "Нет данных"
            assert "Т power: 1.2 W" in page.locator("#other-readings").inner_text()

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
            static_page.evaluate(
                """() => {
                    handleReading({timestamp: '2026-07-28T00:00:00Z', channel: 'Т power', value: 1.2, unit: 'W'});
                    handleReading({timestamp: '2026-07-28T00:00:01Z', channel: 'sample', value: 4.2, unit: 'K'});
                    updateCharts();
                }"""
            )
            assert "Т power" not in static_page.locator("#legend-temp").inner_text()
            assert "sample" in static_page.locator("#legend-temp").inner_text()
            other_readings = static_page.locator("#other-readings").inner_text()
            assert "Т power" in other_readings
            assert "1.2 W" in other_readings


def test_dashboard_renders_unavailable_log_distinctly(dashboard_payload, monkeypatch) -> None:
    """A failed log query must not render as an authoritatively empty log."""

    async def _engine_reply(command: dict[str, object]) -> dict[str, object]:
        command_name = command["cmd"]
        if command_name == "safety_status":
            return {"ok": True, "state": "safe"}
        if command_name == "alarm_v2_status":
            return {"ok": True, "active": {}}
        if command_name == "experiment_status":
            return {"ok": True}
        if command_name == "log_get":
            return {"ok": False}
        raise AssertionError(f"unexpected engine command: {command_name}")

    monkeypatch.setattr(server, "_async_engine_command", _engine_reply)

    with _served_dashboard() as base_url:
        with _browser() as browser:
            page = browser.new_page()
            page.goto(base_url + "/", wait_until="networkidle")

            assert page.locator("#log").inner_text() == "Журнал: недоступен"
