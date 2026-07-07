"""Tests for the read-only REST facade at /api/v1.

The facade is a thin, field-whitelisted layer over the same cache/command
path the dashboard uses. These tests pin the two security properties that
matter: field whitelisting (no operator/sample/notes/config leakage) and the
request-size limit, plus the read-only contract (no write verbs).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from cryodaq.web.server import create_app


@pytest.fixture()
def client():
    """TestClient with the ZMQ bridge mocked out."""
    with patch("cryodaq.web.server._zmq_to_ws_bridge"):
        app = create_app()
        with TestClient(app) as c:
            yield c


def test_temperatures_returns_kelvin_readings(client) -> None:
    """/api/v1/temperatures exposes only K-unit readings from the cache."""
    from cryodaq.web import server

    server._state.last_readings = {
        "Т1": {"timestamp": "2026-03-17T10:00:00+00:00", "channel": "Т1",
               "value": 4.2, "unit": "K", "status": "ok"},
        "P1": {"timestamp": "2026-03-17T10:00:00+00:00", "channel": "P1",
               "value": 1e-5, "unit": "mbar", "status": "ok"},
    }
    resp = client.get("/api/v1/temperatures")
    assert resp.status_code == 200
    data = resp.json()
    units = {r["unit"] for r in data}
    assert units == {"K"}
    channels = {r["channel"] for r in data}
    assert channels == {"Т1"}


def test_experiment_response_redacts_sensitive_fields(client) -> None:
    """/api/v1/experiment must not leak operator/sample/notes/config/artifacts."""
    full_payload = {
        "ok": True,
        "current_phase": "cooldown",
        "phase_started_at": 1710670800.0,
        "active_experiment": {
            "experiment_id": "exp-1",
            "name": "run",
            "title": "Run 1",
            "template_id": "custom",
            "operator": "SECRET_OPERATOR",
            "cryostat": "cryo-A",
            "sample": "SECRET_SAMPLE",
            "description": "desc",
            "notes": "SECRET_NOTES",
            "status": "running",
            "config_snapshot": {"SECRET_KEY": "SECRET_VALUE"},
            "custom_fields": {"SECRET_CF": "x"},
            "artifact_dir": "/secret/artifacts",
            "metadata_path": "/secret/meta.json",
        },
    }

    async def _fake(req: dict) -> dict:
        assert req == {"cmd": "experiment_status"}
        return full_payload

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        resp = client.get("/api/v1/experiment")

    assert resp.status_code == 200
    body = resp.text
    for leak in ("SECRET_OPERATOR", "SECRET_SAMPLE", "SECRET_NOTES",
                 "SECRET_KEY", "SECRET_VALUE", "SECRET_CF", "/secret/"):
        assert leak not in body, f"leaked {leak!r}"
    exp = resp.json()["active_experiment"]
    assert exp["experiment_id"] == "exp-1"
    assert "operator" not in exp
    assert "config_snapshot" not in exp
    assert "artifact_dir" not in exp


def test_log_response_redacts_author(client) -> None:
    """Operator-log authors must not leak through the REST facade."""
    entries = [{
        "id": 1,
        "timestamp": "2026-03-17T10:00:00+00:00",
        "experiment_id": "exp-1",
        "author": "SECRET_AUTHOR",
        "source": "gui",
        "message": "hello",
        "tags": ["note"],
    }]

    async def _fake(req: dict) -> dict:
        assert req["cmd"] == "log_get"
        return {"ok": True, "entries": entries}

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        resp = client.get("/api/v1/log?limit=5")

    assert resp.status_code == 200
    assert "SECRET_AUTHOR" not in resp.text
    entry = resp.json()[0]
    assert "author" not in entry
    assert entry["message"] == "hello"


def test_oversize_body_returns_413_before_engine(client) -> None:
    """A too-large body is rejected with 413 before any engine call."""
    called = False

    async def _fake(req: dict) -> dict:
        nonlocal called
        called = True
        return {"ok": True}

    big = b"x" * (2 * 1024 * 1024)  # 2 MiB
    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        resp = client.request("GET", "/api/v1/experiment", content=big)

    assert resp.status_code == 413
    assert called is False


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
@pytest.mark.parametrize("path", ["/api/v1/state", "/api/v1/experiment", "/api/v1/log"])
def test_write_verbs_are_rejected(client, method: str, path: str) -> None:
    """The facade is read-only: no mutating verb is allowed on any path."""
    resp = client.request(method, path)
    assert resp.status_code == 405


def test_state_endpoint_shape(client) -> None:
    resp = client.get("/api/v1/state")
    assert resp.status_code == 200
    data = resp.json()
    assert "uptime" in data
    assert "channels" in data


def test_alarms_redacts_acknowledged_by(client) -> None:
    """/api/v1/alarms must not leak the operator who acknowledged an alarm."""
    active = {
        "T1_high": {
            "level": "warning",
            "message": "T1 high",
            "acknowledged": True,
            "acknowledged_by": "SECRET_OPERATOR",
        }
    }

    async def _fake(req: dict) -> dict:
        assert req == {"cmd": "alarm_v2_status"}
        return {"ok": True, "active": active}

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        resp = client.get("/api/v1/alarms")

    assert resp.status_code == 200
    assert "SECRET_OPERATOR" not in resp.text
    alarm = resp.json()["active"]["T1_high"]
    assert "acknowledged_by" not in alarm
    assert alarm["level"] == "warning"
    assert alarm["acknowledged"] is True


def test_state_redacts_acknowledged_by(client) -> None:
    """/api/v1/state must not leak acknowledged_by via active_alarms."""
    from cryodaq.web import server

    server._state.active_alarms = {
        "T1_high": {"level": "warning", "acknowledged_by": "SECRET_OPERATOR"}
    }
    resp = client.get("/api/v1/state")
    assert resp.status_code == 200
    assert "SECRET_OPERATOR" not in resp.text
    alarm = resp.json()["active_alarms"]["T1_high"]
    assert "acknowledged_by" not in alarm
    assert alarm["level"] == "warning"


def test_docs_available(client) -> None:
    """Swagger UI is served (FastAPI default)."""
    resp = client.get("/docs")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# P4-1: write-auth token infrastructure (require_write_token dependency)
#
# The dependency is exercised through a throwaway app so no production probe
# surface exists (write endpoints arrive in P4-2). Config is loaded from a
# per-test tmp dir by monkeypatching rest_api.get_config_dir.
# ---------------------------------------------------------------------------

_TOKEN = "s3cr3t-operator-token-xyz-987654321"


def _make_write_app():
    """Throwaway app: one write route behind require_write_token, one read."""
    from fastapi import Depends, FastAPI

    from cryodaq.web.rest_api import require_write_token

    app = FastAPI()

    @app.post("/_probe", dependencies=[Depends(require_write_token)])
    async def _probe() -> dict[str, bool]:  # pragma: no cover - trivial
        return {"ok": True}

    @app.get("/_read")
    async def _read() -> dict[str, bool]:  # pragma: no cover - trivial
        return {"ok": True}

    return app


def _write_local_config(config_dir, token: str) -> None:
    (config_dir / "web.local.yaml").write_text(
        f'web:\n  api_token: "{token}"\n', encoding="utf-8"
    )


@pytest.fixture()
def write_client(monkeypatch, tmp_path):
    """TestClient over the throwaway write app with config dir = tmp_path."""
    monkeypatch.setattr("cryodaq.web.rest_api.get_config_dir", lambda: tmp_path)
    with TestClient(_make_write_app()) as c:
        yield c, tmp_path


def test_no_token_configured_returns_403(write_client) -> None:
    """Fail-closed: no web.local.yaml ⇒ every write route returns 403."""
    client, _tmp = write_client  # no config written
    resp = client.post("/_probe", headers={"Authorization": f"Bearer {_TOKEN}"})
    assert resp.status_code == 403
    assert resp.json()["detail"] == "API token не настроен"


def test_missing_auth_header_returns_401(write_client) -> None:
    """Token configured but no Authorization header ⇒ 401."""
    client, tmp = write_client
    _write_local_config(tmp, _TOKEN)
    resp = client.post("/_probe")
    assert resp.status_code == 401


def test_wrong_token_returns_401(write_client) -> None:
    """Token configured, wrong bearer ⇒ 401."""
    client, tmp = write_client
    _write_local_config(tmp, _TOKEN)
    resp = client.post("/_probe", headers={"Authorization": "Bearer nope-wrong"})
    assert resp.status_code == 401


def test_correct_token_passes(write_client) -> None:
    """Correct bearer ⇒ dependency passes, route runs."""
    client, tmp = write_client
    _write_local_config(tmp, _TOKEN)
    resp = client.post("/_probe", headers={"Authorization": f"Bearer {_TOKEN}"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_reads_never_require_token(write_client) -> None:
    """GET routes never touch the dependency — no token, still 200."""
    client, tmp = write_client
    _write_local_config(tmp, _TOKEN)  # even with a token configured
    resp = client.get("/_read")
    assert resp.status_code == 200


def test_token_absent_from_logs(write_client, caplog) -> None:
    """The token value must never reach the logs (SecretStr + no-log path)."""
    import logging

    client, tmp = write_client
    _write_local_config(tmp, _TOKEN)
    with caplog.at_level(logging.DEBUG):
        # both an authenticated hit and a rejected one
        client.post("/_probe", headers={"Authorization": f"Bearer {_TOKEN}"})
        client.post("/_probe", headers={"Authorization": "Bearer wrong"})
    assert _TOKEN not in caplog.text


def test_secret_str_masks_token_repr() -> None:
    """The loaded token is a SecretStr — repr/str never expose the value."""
    from cryodaq.notifications._secrets import SecretStr

    s = SecretStr(_TOKEN)
    assert _TOKEN not in repr(s)
    assert _TOKEN not in str(s)
