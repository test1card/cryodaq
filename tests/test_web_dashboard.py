"""Tests for the web dashboard."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from cryodaq.web.server import create_app


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
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "uptime" in data
    assert "readings" in data


def test_api_log_returns_entries(client) -> None:
    with patch("cryodaq.gui.zmq_client.send_command", return_value={
        "ok": True, "entries": [{"message": "test", "timestamp": "2026-03-17T10:00:00Z"}]
    }):
        resp = client.get("/api/log?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert "entries" in data


def test_status_endpoint_returns_json(client) -> None:
    resp = client.get("/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "uptime" in data
