"""Tests for the web dashboard."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from cryodaq.core.zmq_bridge import PROTOCOL_VERSION
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
            assert resp.json() == {"ok": False, "entries": []}
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
