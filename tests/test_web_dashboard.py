"""Tests for the web dashboard."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from cryodaq.core.zmq_bridge import PROTOCOL_VERSION
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.web import server
from cryodaq.web.server import _query_history, create_app


@pytest.fixture()
def client():
    """TestClient with ZMQ bridge mocked out."""
    with patch("cryodaq.web.server._zmq_to_ws_bridge"):
        app = create_app()
        with TestClient(app) as c:
            yield c


def test_root_returns_html(client) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "CryoDAQ Monitor" in resp.text
    assert "text/html" in resp.headers["content-type"]


def test_api_status_returns_json(client) -> None:
    """_async_engine_command is called for status sub-queries; response has expected shape."""

    async def _fake(req: dict) -> dict:
        cmd = req.get("cmd", "")
        if cmd == "safety_status":
            return {"ok": True, "state": "SAFE_OFF"}
        if cmd == "alarm_v2_status":
            return {"ok": True, "active": {}}
        if cmd == "experiment_status":
            return {"ok": True}
        return {"ok": False}

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        resp = client.get("/api/status")

    assert resp.status_code == 200
    data = resp.json()
    assert "uptime" in data
    assert isinstance(data["uptime"], str)  # formatted HH:MM:SS string
    assert "uptime_s" in data
    assert isinstance(data["uptime_s"], (int, float))
    assert "readings" in data
    assert data.get("safety", {}).get("state") == "SAFE_OFF"
    assert "active_alarms" in data


def test_api_status_distinguishes_unavailable_experiment_from_none(client) -> None:
    """An unreachable experiment_status must not render identically to a
    reachable engine with no active experiment — the dashboard must be able
    to tell them apart, so /api/status carries an explicit signal."""

    async def _unavailable_experiment(req: dict) -> dict:
        cmd = req.get("cmd", "")
        if cmd == "safety_status":
            return {"ok": True, "state": "safe"}
        if cmd == "alarm_v2_status":
            return {"ok": True, "active": {}}
        if cmd == "experiment_status":
            return {"ok": False}
        raise AssertionError(f"unexpected request: {req!r}")

    async def _raising_experiment(req: dict) -> dict:
        cmd = req.get("cmd", "")
        if cmd == "safety_status":
            return {"ok": True, "state": "safe"}
        if cmd == "alarm_v2_status":
            return {"ok": True, "active": {}}
        if cmd == "experiment_status":
            raise RuntimeError("down")
        raise AssertionError(f"unexpected request: {req!r}")

    async def _ok_no_experiment(req: dict) -> dict:
        cmd = req.get("cmd", "")
        if cmd == "safety_status":
            return {"ok": True, "state": "safe"}
        if cmd == "alarm_v2_status":
            return {"ok": True, "active": {}}
        if cmd == "experiment_status":
            return {"ok": True}
        raise AssertionError(f"unexpected request: {req!r}")

    with patch("cryodaq.web.server._async_engine_command", side_effect=_unavailable_experiment):
        unavailable = client.get("/api/status").json()
    with patch("cryodaq.web.server._async_engine_command", side_effect=_raising_experiment):
        raised = client.get("/api/status").json()
    with patch("cryodaq.web.server._async_engine_command", side_effect=_ok_no_experiment):
        ok_none = client.get("/api/status").json()

    assert unavailable.get("experiment_available") is False
    assert raised.get("experiment_available") is False
    assert ok_none.get("experiment_available") is True
    assert unavailable.get("experiment") is None
    assert ok_none.get("experiment") == {
        "active_experiment": None,
        "current_phase": None,
        "phase_started_at": None,
    }


def test_api_version_returns_proto_server_app_version(client) -> None:
    """GET /api/version is unauthenticated (same trust as other reads)
    and returns the {proto, server, app_version} triple, `server: "web"`."""
    resp = client.get("/api/version")
    assert resp.status_code == 200
    data = resp.json()
    assert data == {
        "proto": PROTOCOL_VERSION,
        "server": "web",
        "app_version": data["app_version"],
    }
    assert isinstance(data["app_version"], str) and data["app_version"]


def test_api_log_returns_entries(client) -> None:
    """The legacy dashboard receives the canonical author-free projection."""
    received: list[dict] = []
    expected_entries = [{"message": "test", "timestamp": "2026-03-17T10:00:00Z"}]

    async def _fake(req: dict) -> dict:
        received.append(req)
        return {"ok": True, "entries": expected_entries}

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        resp = client.get("/api/log?limit=5")

    assert resp.status_code == 200
    data = resp.json()
    assert data == {
        "ok": True,
        "entries": [
            {
                "id": None,
                "timestamp": "2026-03-17T10:00:00Z",
                "experiment_id": None,
                "source": None,
                "message": "test",
                "tags": [],
            }
        ],
    }
    assert len(received) == 1
    assert received[0] == {"cmd": "log_get", "limit": 5}


def test_api_log_distinguishes_unavailable_from_authoritative_empty(client) -> None:
    """Dashboard consumers must not read an unreachable log as zero entries."""

    async def _unavailable(_req: dict) -> dict:
        return {"ok": False}

    async def _empty(_req: dict) -> dict:
        return {"ok": True, "entries": []}

    with patch("cryodaq.web.server._async_engine_command", side_effect=_unavailable):
        unavailable = client.get("/api/log")
    with patch("cryodaq.web.server._async_engine_command", side_effect=_empty):
        empty = client.get("/api/log")

    assert unavailable.status_code == 200
    assert unavailable.json() == {
        "ok": False,
        "entries": [],
        "available": False,
        "stale": True,
        "reason": "operator log unavailable",
    }
    assert empty.status_code == 200
    assert empty.json() == {"ok": True, "entries": []}


def test_status_endpoint_returns_json(client) -> None:
    """/status is an alias for /api/status; verify uptime is a non-negative number."""

    async def _fake(req: dict) -> dict:
        return {"ok": False}

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        resp = client.get("/status")

    assert resp.status_code == 200
    data = resp.json()
    assert "uptime" in data
    assert isinstance(data["uptime"], str)  # formatted HH:MM:SS string
    assert "uptime_s" in data
    assert data["uptime_s"] >= 0


def _bridge_death() -> None:
    """Run the production bridge through its termination path."""
    started = asyncio.Event()

    class _Subscriber:
        def __init__(self, **_kwargs) -> None:
            return None

        async def start(self) -> None:
            started.set()

        async def stop(self) -> None:
            return None

    async def _run() -> None:
        with patch("cryodaq.web.server.ZMQSubscriber", _Subscriber):
            task = asyncio.create_task(server._zmq_to_ws_bridge())
            await asyncio.wait_for(started.wait(), timeout=1)
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    asyncio.run(_run())


def _fresh_server_state(monkeypatch) -> None:
    monkeypatch.setattr(server, "_state", server._ServerState())


def _without_bridge():
    async def _pending_bridge() -> None:
        await asyncio.Future()

    return patch("cryodaq.web.server._zmq_to_ws_bridge", _pending_bridge)


def test_bridge_death_marks_http_status_and_dashboard_unavailable(monkeypatch) -> None:
    """A dead producer leaves cached values last-known, never current."""

    async def _engine_unavailable(_command: dict) -> dict:
        return {"ok": False}

    _fresh_server_state(monkeypatch)
    server._on_reading_callback(
        Reading(
            timestamp=datetime.now(UTC),
            instrument_id="test",
            channel="T1",
            value=4.2,
            unit="K",
            status=ChannelStatus.OK,
        )
    )
    _bridge_death()
    with _without_bridge(), patch("cryodaq.web.server._async_engine_command", _engine_unavailable):
        with TestClient(create_app()) as status_client:
            response = status_client.get("/status")
            api_response = status_client.get("/api/status")
            dashboard = status_client.get("/")

    for payload in (response.json(), api_response.json()):
        assert payload["available"] is False
        assert payload["stale"] is True
        assert isinstance(payload["reason"], str) and payload["reason"]
    assert dashboard.status_code == 200


def test_authoritative_reading_makes_status_live(monkeypatch) -> None:
    """Only an authoritative reading may make a bridge-backed cache live."""
    _fresh_server_state(monkeypatch)
    server._on_reading_callback(
        Reading(
            timestamp=datetime.now(UTC),
            instrument_id="test",
            channel="T1",
            value=4.2,
            unit="K",
            status=ChannelStatus.OK,
        )
    )
    with _without_bridge():
        with TestClient(create_app()) as status_client:
            payload = status_client.get("/status").json()

    assert payload["available"] is True
    assert payload["stale"] is False
    assert payload["reason"] is None


def test_expired_cache_is_stale_but_still_available(monkeypatch) -> None:
    """A silent, otherwise-live producer exposes last-known data as stale."""
    _fresh_server_state(monkeypatch)
    server._on_reading_callback(
        Reading(
            timestamp=datetime.now(UTC),
            instrument_id="test",
            channel="T1",
            value=4.2,
            unit="K",
            status=ChannelStatus.OK,
        )
    )
    server._state._last_authoritative_reading_at -= 11
    with _without_bridge():
        with TestClient(create_app()) as status_client:
            payload = status_client.get("/status").json()

    assert payload["available"] is True
    assert payload["stale"] is True
    assert isinstance(payload["reason"], str) and payload["reason"]


def test_respawn_without_authoritative_reading_remains_unavailable(monkeypatch) -> None:
    """Starting a replacement bridge does not restore authority by itself."""
    _fresh_server_state(monkeypatch)
    _bridge_death()
    # This is the same state assignment made at bridge startup.  It must
    # not turn a dead cache live before the new callback receives a Reading.
    server._state.subscriber = object()
    payload = server._state.status_json()

    assert payload["available"] is False
    assert payload["stale"] is True
    assert isinstance(payload["reason"], str) and payload["reason"]


def test_query_history_closes_connection_on_exception(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / f"data_{datetime.now(UTC).date().isoformat()}.db"
    db_path.write_text("")
    closed: list[bool] = []

    class _Conn:
        row_factory = None

        def execute(self, *_args, **_kwargs):
            raise RuntimeError("boom")

        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr("cryodaq.web.server._DATA_DIR", tmp_path)
    monkeypatch.setattr("cryodaq.web.server.sqlite3.connect", lambda *args, **kwargs: _Conn())

    assert _query_history(5) == {}
    assert closed == [True]


def test_api_status_logs_alarm_failure(client, caplog) -> None:
    """H4: alarm fetch exception logs WARNING with endpoint context."""
    import logging

    async def _boom(req):
        if req.get("cmd") == "alarm_v2_status":
            raise RuntimeError("zmq bridge down")
        return {"ok": False}

    with patch("cryodaq.web.server._async_engine_command", side_effect=_boom):
        with caplog.at_level(logging.WARNING, logger="cryodaq.web.server"):
            resp = client.get("/api/status")
            assert resp.status_code == 200
    assert any("alarm fetch failed" in rec.message for rec in caplog.records)


def test_api_log_logs_failure(client, caplog) -> None:
    """H4: api_log exception logs WARNING."""
    import logging

    async def _boom(req):
        raise RuntimeError("engine offline")

    with patch("cryodaq.web.server._async_engine_command", side_effect=_boom):
        with caplog.at_level(logging.WARNING, logger="cryodaq.web.server"):
            resp = client.get("/api/log")
            assert resp.status_code == 200
            assert resp.json() == {
                "ok": False,
                "entries": [],
                "available": False,
                "stale": True,
                "reason": "operator log unavailable",
            }
    assert any("api_log fetch failed" in rec.message for rec in caplog.records)


def test_no_public_bind_in_docs() -> None:
    """S1: operator-facing bind instruction must be 127.0.0.1, not 0.0.0.0."""
    import re
    from pathlib import Path

    server_src = Path(__file__).parent.parent / "src/cryodaq/web/server.py"
    text = server_src.read_text(encoding="utf-8")
    # Allow only the warning line that mentions 0.0.0.0 in a "never bind" context.
    bind_examples = re.findall(r"--host\s+(\S+)", text)
    assert bind_examples, "expected at least one --host example in docstring"
    for host in bind_examples:
        assert host == "127.0.0.1", f"public bind {host!r} found in docs"

    main_src = Path(__file__).parent.parent / "src/cryodaq/gui/shell/main_window_v2.py"
    main_text = main_src.read_text(encoding="utf-8")
    main_examples = re.findall(r"--host\s+(\S+?)\s", main_text)
    for host in main_examples:
        assert host == "127.0.0.1", f"public bind {host!r} in operator help"
