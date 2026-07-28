"""Browser-free guards for the unavailable-reading contract.

DEFERRED-BROWSER-01 (2026-07-26):
  The dashboards decide how an unavailable reading looks in CLIENT-SIDE
  JavaScript, so proving the rendered text requires a headless browser.
  tests/web/test_dashboard_unavailable_readings.py drives the real thing under
  Playwright, but Playwright is not a declared dependency of this project and is
  absent from CI, so that file cannot be the guard that protects the contract.

  These guards run everywhere and hold the two halves the browser test would
  otherwise be the only witness to:

    1. the API half, executed for real -- a non-finite Reading must cross the
       wire as strict-JSON ``null`` and never as ``NaN``/``Infinity``;
    2. the rendering half, checked structurally -- EVERY numeric formatting call
       site in either dashboard must carry an unavailable guard on its own line.

  The second guard is deliberately exhaustive over call sites rather than a list
  of known lines: a new channel display added by a future lab is covered the
  moment it is written, which is the property that matters here. It cannot prove
  the guard is CORRECT -- only that no site is unguarded. Executing the JS stays
  the browser test's job.
"""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from starlette.testclient import TestClient

import cryodaq.web.server as server
from cryodaq.drivers.base import ChannelStatus, Reading

SERVED_DASHBOARD = Path("src/cryodaq/web/server.py")
STATIC_DASHBOARD = Path("src/cryodaq/web/static/index.html")

# A JS call that turns a number into display text. ``Number(`` is included
# because coercing an unavailable value is the same defect wearing a different
# hat; the negative lookbehind keeps ``Number.isFinite`` out of the match.
_FORMATTING_CALL = re.compile(r"\.to(?:Fixed|Precision|Exponential)\(|(?<![.\w])Number\(")

# Any one of these on the same line means the value was proven usable first.
_UNAVAILABLE_GUARDS = ("usable", "finiteNumber", "=== null", "!== null")


def _source(path: Path) -> str:
    """Read as bytes so CRLF files keep their endings and anchors still match."""
    return path.read_bytes().decode("utf-8")


@pytest.mark.parametrize("path", [SERVED_DASHBOARD, STATIC_DASHBOARD], ids=lambda p: p.name)
def test_every_numeric_formatting_site_carries_an_unavailable_guard(path: Path) -> None:
    """No dashboard may format a number it has not first proven is available."""
    unguarded = [
        f"{path.as_posix()}:{number}: {line.strip()}"
        for number, line in enumerate(_source(path).splitlines(), 1)
        if _FORMATTING_CALL.search(line) and not any(guard in line for guard in _UNAVAILABLE_GUARDS)
    ]
    assert not unguarded, "numeric formatting without an unavailable guard:\n" + "\n".join(unguarded)


def test_both_dashboards_still_define_an_unavailable_helper() -> None:
    """The guards above are only meaningful while the helpers they name exist."""
    assert "function isUsableReading" in _source(SERVED_DASHBOARD)
    assert "function finiteNumber" in _source(STATIC_DASHBOARD)


def test_served_dashboard_distinguishes_unavailable_experiment_from_none() -> None:
    """The served dashboard must not render an unreachable engine as
    'Нет активного эксперимента'. The ``experiment_available`` signal must gate
    the experiment branch and must precede the no-experiment fallback, so an
    unavailable experiment status is rendered as a connectivity fault, not an
    authoritative empty. (The static dashboard consumes ``/status``, which
    carries no experiment field, so it is out of scope here.)"""
    src = _source(SERVED_DASHBOARD)
    assert "experiment_available" in src, "served dashboard lacks the experiment availability signal"
    availability = src.index("experiment_available")
    no_experiment = src.index("Нет активного эксперимента")
    assert availability < no_experiment, "availability check must precede the no-experiment fallback"


def test_served_dashboard_distinguishes_unavailable_log_from_empty() -> None:
    """The dashboard must render the log availability discriminator distinctly."""
    src = _source(SERVED_DASHBOARD)
    unavailable = src.index("ld.available===false")
    empty = src.index("ld.ok?'Нет записей'")
    assert unavailable < empty, "unavailable log check must precede the empty-log fallback"


@pytest.fixture
def unavailable_readings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Push non-finite readings through the production callback, not a stub."""

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
    monkeypatch.setattr(server._state, "active_alarms", {})
    for channel, value, unit in (
        ("T1", float("nan"), "K"),
        ("vacuum", float("inf"), "mbar"),
        ("keithley/smua/power", float("-inf"), "W"),
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


def test_api_reports_a_non_finite_reading_as_strict_json_null(unavailable_readings: None) -> None:
    """NaN and +/-inf must leave the server as null, which every JSON parser accepts."""
    app = server.create_app()

    @asynccontextmanager
    async def _no_background_workers(_app):
        """Serve the routes without connecting this regression to ZMQ."""
        yield

    app.router.lifespan_context = _no_background_workers
    with TestClient(app) as client:
        response = client.get("/api/status")

    assert response.status_code == 200
    assert "NaN" not in response.text
    assert "Infinity" not in response.text
    readings = response.json()["readings"]
    assert readings["T1"]["value"] is None
    assert readings["vacuum"]["value"] is None
    assert readings["keithley/smua/power"]["value"] is None
