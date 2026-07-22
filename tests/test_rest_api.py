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
        "Т1": {"timestamp": "2026-03-17T10:00:00+00:00", "channel": "Т1", "value": 4.2, "unit": "K", "status": "ok"},
        "P1": {
            "timestamp": "2026-03-17T10:00:00+00:00",
            "channel": "P1",
            "value": 1e-5,
            "unit": "mbar",
            "status": "ok",
        },
    }
    resp = client.get("/api/v1/temperatures")
    assert resp.status_code == 200
    data = resp.json()
    units = {r["unit"] for r in data}
    assert units == {"K"}
    channels = {r["channel"] for r in data}
    assert channels == {"Т1"}


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize(
    ("path", "unit"),
    [
        ("/api/v1/readings", "K"),
        ("/api/v1/temperatures", "K"),
        ("/api/v1/pressure", "mbar"),
    ],
)
def test_live_read_endpoints_emit_strict_json_null(client, path: str, unit: str, value: float) -> None:
    """Pydantic is a second defense if a malformed cache bypasses ingress."""
    from cryodaq.web import server

    server._state.last_readings = {
        "bad": {
            "timestamp": "2026-07-19T00:00:00+00:00",
            "channel": "bad",
            "value": value,
            "unit": unit,
            "status": "sensor_error",
        }
    }

    response = client.get(path)

    assert response.status_code == 200
    assert response.json()[0]["value"] is None
    assert "NaN" not in response.text
    assert "Infinity" not in response.text


def test_legacy_api_status_masks_nonfinite_cache_defensively(client) -> None:
    """The unmodelled legacy aggregate also guarantees strict public JSON."""
    from cryodaq.web import server

    server._state.last_readings = {
        "bad": {"channel": "bad", "value": float("nan"), "unit": "K", "status": "sensor_error"}
    }

    async def _unavailable(_cmd: dict) -> dict:
        return {"ok": False}

    with patch("cryodaq.web.server._async_engine_command", side_effect=_unavailable):
        response = client.get("/api/status")

    assert response.status_code == 200
    assert response.json()["readings"]["bad"]["value"] is None
    assert "NaN" not in response.text


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
    for leak in (
        "SECRET_OPERATOR",
        "SECRET_SAMPLE",
        "SECRET_NOTES",
        "SECRET_KEY",
        "SECRET_VALUE",
        "SECRET_CF",
        "/secret/",
    ):
        assert leak not in body, f"leaked {leak!r}"
    exp = resp.json()["active_experiment"]
    assert exp["experiment_id"] == "exp-1"
    assert "operator" not in exp
    assert "config_snapshot" not in exp
    assert "artifact_dir" not in exp


def test_log_response_redacts_author(client) -> None:
    """Operator-log authors must not leak through the REST facade."""
    entries = [
        {
            "id": 1,
            "timestamp": "2026-03-17T10:00:00+00:00",
            "experiment_id": "exp-1",
            "author": "SECRET_AUTHOR",
            "source": "gui",
            "message": "hello",
            "tags": ["note"],
        }
    ]

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


def test_legacy_log_route_shares_public_projection(client) -> None:
    """The embedded dashboard route cannot bypass operator-log redaction."""
    entry = {
        "id": 7,
        "timestamp": "2026-07-18T01:02:03+00:00",
        "experiment_id": "exp-7",
        "author": "SECRET_OPERATOR",
        "source": "gui",
        "message": "проверка",
        "tags": ["note"],
        "unexpected": "SECRET_EXTRA",
    }

    async def _fake(req: dict) -> dict:
        assert req == {"cmd": "log_get", "limit": 5}
        return {"ok": True, "entries": [entry]}

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        response = client.get("/api/log?limit=5")

    assert response.status_code == 200
    assert "SECRET_OPERATOR" not in response.text
    assert "SECRET_EXTRA" not in response.text
    assert response.json()["entries"][0] == {
        "id": 7,
        "timestamp": "2026-07-18T01:02:03+00:00",
        "experiment_id": "exp-7",
        "source": "gui",
        "message": "проверка",
        "tags": ["note"],
    }


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
@pytest.mark.parametrize("path", ["/api/v1/state", "/api/v1/experiment", "/api/v1/readings", "/api/v1/alarms"])
def test_write_verbs_are_rejected(client, method: str, path: str) -> None:
    """Mutating verbs on read-only GET paths never mutate. Auth runs before
    routing (WriteAuthMiddleware), so with no token configured the write-auth
    gate fail-closes (403) before the router would report 405 — either way the
    request is refused. The only real write verbs are the two allowlisted
    POSTs (see P4-2 block below)."""
    resp = client.request(method, path)
    assert resp.status_code == 403


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

    server._state.active_alarms = {"T1_high": {"level": "warning", "acknowledged_by": "SECRET_OPERATOR"}}
    resp = client.get("/api/v1/state")
    assert resp.status_code == 200
    assert "SECRET_OPERATOR" not in resp.text
    alarm = resp.json()["active_alarms"]["T1_high"]
    assert "acknowledged_by" not in alarm
    assert alarm["level"] == "warning"


def test_legacy_status_routes_share_public_redaction_contract(client) -> None:
    """Legacy dashboard reads must not bypass the /api/v1 field whitelist."""
    from cryodaq.web import server

    secret_alarm = {
        "T1_high": {
            "level": "warning",
            "acknowledged": True,
            "acknowledged_by": "SECRET_OPERATOR",
        }
    }
    secret_experiment = {
        "ok": True,
        "current_phase": "cooldown",
        "active_experiment": {
            "experiment_id": "exp-1",
            "name": "run",
            "status": "running",
            "operator": "SECRET_OPERATOR",
            "sample": "SECRET_SAMPLE",
            "notes": "SECRET_NOTES",
            "config_snapshot": {"SECRET_KEY": "SECRET_VALUE"},
            "custom_fields": {"SECRET_CF": "x"},
            "artifact_dir": "/secret/artifacts",
            "metadata_path": "/secret/meta.json",
        },
    }

    async def _fake(req: dict) -> dict:
        if req == {"cmd": "safety_status"}:
            return {"ok": True, "state": "safe"}
        if req == {"cmd": "alarm_v2_status"}:
            return {"ok": True, "active": secret_alarm}
        if req == {"cmd": "experiment_status"}:
            return secret_experiment
        raise AssertionError(f"unexpected request: {req!r}")

    server._state.active_alarms = secret_alarm
    status_response = client.get("/status")
    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        dashboard_response = client.get("/api/status")

    assert status_response.status_code == 200
    assert dashboard_response.status_code == 200
    for response in (status_response, dashboard_response):
        for leak in (
            "SECRET_OPERATOR",
            "SECRET_SAMPLE",
            "SECRET_NOTES",
            "SECRET_KEY",
            "SECRET_VALUE",
            "SECRET_CF",
            "/secret/",
        ):
            assert leak not in response.text, f"{response.url.path} leaked {leak!r}"

    dashboard = dashboard_response.json()
    assert dashboard["active_alarms"]["T1_high"]["level"] == "warning"
    assert dashboard["experiment"]["active_experiment"]["experiment_id"] == "exp-1"
    assert dashboard["experiment"]["current_phase"] == "cooldown"


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
    (config_dir / "web.local.yaml").write_text(f'web:\n  api_token: "{token}"\n', encoding="utf-8")


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


# ---------------------------------------------------------------------------
# P4-2: allowlisted write endpoints (POST /log, POST /alarms/{id}/ack)
#
# Each forwards ONE existing engine command through the same
# server._async_engine_command path the reads use, behind require_write_token.
# The operator-identity field is server-set (never client-supplied): no
# impersonation. The write surface is closed — no other mutating route exists.
# ---------------------------------------------------------------------------

_REST_IDENTITY = "REST API"


@pytest.fixture()
def auth_client(monkeypatch, tmp_path):
    """Production app with a configured write token (config dir = tmp_path)."""
    monkeypatch.setattr("cryodaq.web.rest_api.get_config_dir", lambda: tmp_path)
    (tmp_path / "web.local.yaml").write_text(f'web:\n  api_token: "{_TOKEN}"\n', encoding="utf-8")
    with patch("cryodaq.web.server._zmq_to_ws_bridge"):
        app = create_app()
        with TestClient(app) as c:
            yield c


_AUTH = {"Authorization": f"Bearer {_TOKEN}"}


# --- POST /api/v1/log -------------------------------------------------------


def test_post_log_forwards_log_entry_command(auth_client) -> None:
    """An unscoped POST carries one exact idempotency key and explicit scope."""
    captured: dict = {}

    async def _fake(cmd: dict) -> dict:
        captured.update(cmd)
        return {"ok": True, "entry": {"id": 1, "message": cmd["message"]}}

    with (
        patch("cryodaq.web.rest_api.secrets.token_hex", return_value="a" * 32) as token_hex,
        patch("cryodaq.web.server._async_engine_command", side_effect=_fake),
    ):
        resp = auth_client.post("/api/v1/log", headers=_AUTH, json={"message": "проверка насоса"})

    assert resp.status_code == 200
    token_hex.assert_called_once_with(16)
    assert captured == {
        "cmd": "log_entry",
        "request_id": "a" * 32,
        "message": "проверка насоса",
        "author": _REST_IDENTITY,
        "source": "rest",
        "experiment_unbound": True,
    }
    assert "current_experiment" not in captured


def test_post_log_forwards_exact_experiment_scope(auth_client) -> None:
    """A caller-supplied experiment identity is forwarded exactly, never inferred."""
    captured: dict = {}

    async def _fake(cmd: dict) -> dict:
        captured.update(cmd)
        return {"ok": True, "entry": {"id": 1}}

    with (
        patch("cryodaq.web.rest_api.secrets.token_hex", return_value="b" * 32),
        patch("cryodaq.web.server._async_engine_command", side_effect=_fake),
    ):
        response = auth_client.post(
            "/api/v1/log",
            headers=_AUTH,
            json={"message": "scoped", "experiment_id": "exp-exact"},
        )

    assert response.status_code == 200
    assert captured["request_id"] == "b" * 32
    assert captured["experiment_id"] == "exp-exact"
    assert "experiment_unbound" not in captured
    assert "current_experiment" not in captured


def test_post_log_author_is_server_set_not_spoofable(auth_client) -> None:
    """The author forwarded to the engine is the REST identity, never client
    input — and a client-supplied author key is rejected (422), not honored."""
    captured: dict = {}

    async def _fake(cmd: dict) -> dict:
        captured.update(cmd)
        return {"ok": True, "entry": {"id": 1}}

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        ok = auth_client.post("/api/v1/log", headers=_AUTH, json={"message": "hi"})
        spoof = auth_client.post(
            "/api/v1/log",
            headers=_AUTH,
            json={"message": "hi", "author": "victim"},
        )

    assert ok.status_code == 200
    assert captured["author"] == _REST_IDENTITY
    assert spoof.status_code == 422  # extra field forbidden — no impersonation


def test_post_log_extra_field_rejected(auth_client) -> None:
    """Unknown keys → 422 (strict request model)."""
    with patch("cryodaq.web.server._async_engine_command", side_effect=AssertionError):
        resp = auth_client.post("/api/v1/log", headers=_AUTH, json={"message": "x", "bogus": 1})
    assert resp.status_code == 422


def test_post_log_empty_message_rejected(auth_client) -> None:
    """Empty message → 422 before any engine call."""
    with patch("cryodaq.web.server._async_engine_command", side_effect=AssertionError):
        resp = auth_client.post("/api/v1/log", headers=_AUTH, json={"message": ""})
    assert resp.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"message": "x" * 4097},
        {"message": "ok", "tags": [f"tag-{index}" for index in range(17)]},
        {"message": "ok", "tags": ["x" * 65]},
    ],
)
def test_post_log_rejects_oversized_fields(auth_client, payload: dict) -> None:
    """Authenticated writes remain bounded below the global body cap."""
    with patch("cryodaq.web.server._async_engine_command", side_effect=AssertionError):
        resp = auth_client.post("/api/v1/log", headers=_AUTH, json=payload)
    assert resp.status_code == 422


def test_post_log_rejects_chunked_transfer_before_body_parse(auth_client) -> None:
    """The facade does not accept an unbounded body without Content-Length."""
    headers = {
        **_AUTH,
        "Content-Type": "application/json",
        "Transfer-Encoding": "chunked",
    }
    with patch("cryodaq.web.server._async_engine_command", side_effect=AssertionError):
        resp = auth_client.post(
            "/api/v1/log",
            headers=headers,
            content=b'{"message":"ok"}',
        )
    assert resp.status_code == 411


def test_post_log_without_token_is_401(auth_client) -> None:
    """No Authorization header → 401, engine never called."""
    with patch("cryodaq.web.server._async_engine_command", side_effect=AssertionError):
        resp = auth_client.post("/api/v1/log", json={"message": "x"})
    assert resp.status_code == 401


def test_post_log_wrong_token_is_401(auth_client) -> None:
    with patch("cryodaq.web.server._async_engine_command", side_effect=AssertionError):
        resp = auth_client.post(
            "/api/v1/log",
            headers={"Authorization": "Bearer nope"},
            json={"message": "x"},
        )
    assert resp.status_code == 401


def test_post_log_no_token_configured_is_403(monkeypatch, tmp_path) -> None:
    """No web.local.yaml ⇒ fail-closed 403 for writes."""
    monkeypatch.setattr("cryodaq.web.rest_api.get_config_dir", lambda: tmp_path)
    with patch("cryodaq.web.server._zmq_to_ws_bridge"):
        app = create_app()
        with TestClient(app) as c:
            resp = c.post("/api/v1/log", headers=_AUTH, json={"message": "x"})
    assert resp.status_code == 403


# --- POST /api/v1/alarms/{alarm_id}/ack ------------------------------------


def test_post_ack_forwards_alarm_v2_ack_command(auth_client) -> None:
    """POST /alarms/{id}/ack forwards cmd=alarm_v2_ack for that alarm."""
    captured: dict = {}

    async def _fake(cmd: dict) -> dict:
        captured.update(cmd)
        return {"ok": True, "alarm_name": cmd["alarm_name"], "event_emitted": True}

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        resp = auth_client.post(
            "/api/v1/alarms/T1_high/ack",
            headers=_AUTH,
            json={"engine_instance_id": "engine-a", "activation_id": "a1"},
        )

    assert resp.status_code == 200
    assert captured["cmd"] == "alarm_v2_ack"
    assert captured["alarm_name"] == "T1_high"
    assert captured["engine_instance_id"] == "engine-a"
    assert captured["activation_id"] == "a1"


def test_post_ack_operator_is_server_set_not_spoofable(auth_client) -> None:
    """acknowledged_by (operator) is the REST identity, never client input;
    a client-supplied operator key is rejected (422)."""
    captured: dict = {}

    async def _fake(cmd: dict) -> dict:
        captured.update(cmd)
        return {"ok": True}

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        ok = auth_client.post(
            "/api/v1/alarms/T1_high/ack",
            headers=_AUTH,
            json={"engine_instance_id": "engine-a", "activation_id": "a1"},
        )
        spoof = auth_client.post(
            "/api/v1/alarms/T1_high/ack",
            headers=_AUTH,
            json={
                "engine_instance_id": "engine-a",
                "activation_id": "a1",
                "operator": "victim",
            },
        )

    assert ok.status_code == 200
    assert captured["operator"] == _REST_IDENTITY
    assert spoof.status_code == 422


def test_post_ack_without_expected_activation_fails_closed(auth_client) -> None:
    with patch("cryodaq.web.server._async_engine_command", side_effect=AssertionError):
        response = auth_client.post("/api/v1/alarms/T1_high/ack", headers=_AUTH)

    assert response.status_code == 422


def test_post_ack_rejects_reason_over_engine_limit(auth_client) -> None:
    with patch("cryodaq.web.server._async_engine_command", side_effect=AssertionError):
        response = auth_client.post(
            "/api/v1/alarms/T1_high/ack",
            headers=_AUTH,
            json={
                "engine_instance_id": "engine-a",
                "activation_id": "a1",
                "reason": "x" * 257,
            },
        )
    assert response.status_code == 422


def test_delayed_rest_ack_never_substitutes_latest_activation(auth_client) -> None:
    active = {"activation_id": "a1", "acknowledged": False}

    async def _fake(cmd: dict) -> dict:
        if cmd == {"cmd": "alarm_v2_status"}:
            return {
                "ok": True,
                "engine_instance_id": "engine-a",
                "snapshot_revision": 1,
                "active": {"T1_high": dict(active)},
            }
        assert cmd["cmd"] == "alarm_v2_ack"
        if cmd["activation_id"] == active["activation_id"]:
            active["acknowledged"] = True
        return {"ok": False, "error": "stale_or_unknown_activation"}

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        snapshot_response = auth_client.get("/api/v1/alarms")
        snapshot = snapshot_response.json()

        # The first activation clears and the same named alarm fires again
        # before the operator submits the acknowledgement.
        active = {"activation_id": "a2", "acknowledged": False}
        response = auth_client.post(
            "/api/v1/alarms/T1_high/ack",
            headers=_AUTH,
            json={
                "engine_instance_id": snapshot["engine_instance_id"],
                "activation_id": snapshot["active"]["T1_high"]["activation_id"],
            },
        )

    assert snapshot_response.status_code == 200
    assert snapshot["snapshot_revision"] == 1
    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert active["activation_id"] == "a2"
    assert active["acknowledged"] is False


def test_post_ack_without_token_is_401(auth_client) -> None:
    with patch("cryodaq.web.server._async_engine_command", side_effect=AssertionError):
        resp = auth_client.post("/api/v1/alarms/T1_high/ack")
    assert resp.status_code == 401


# --- Swagger + allowlist closure -------------------------------------------


def test_write_endpoints_declare_bearer_security(auth_client) -> None:
    """/docs (OpenAPI) shows the bearer scheme on the write endpoints."""
    schema = auth_client.get("/openapi.json").json()
    assert "HTTPBearer" in schema["components"]["securitySchemes"]
    for path in ("/api/v1/log", "/api/v1/alarms/{alarm_id}/ack"):
        security = schema["paths"][path]["post"].get("security", [])
        assert any("HTTPBearer" in req for req in security), path


def test_api_v1_write_surface_is_closed() -> None:
    """Only the two allowlisted POSTs carry a mutating verb on the facade.

    Grep-style closure guard: iterate every route the rest_api router
    registers and assert no other write-method path exists (no generic
    command proxy, no accidental exposure of source/setpoint/calibration/
    experiment-lifecycle commands)."""
    from cryodaq.web import rest_api

    write_routes = set()
    for route in rest_api.router.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", None) or set()
        for verb in methods & {"POST", "PUT", "PATCH", "DELETE"}:
            write_routes.add((path, verb))
    assert write_routes == {
        ("/api/v1/log", "POST"),
        ("/api/v1/alarms/{alarm_id}/ack", "POST"),
    }


def test_post_to_unlisted_api_path_is_not_a_command(monkeypatch, tmp_path) -> None:
    """POST to a non-allowlisted /api/v1 path never reaches an engine command.

    With no token configured the write-auth middleware fail-closes (403)
    before the router runs — never 200, engine never touched."""
    monkeypatch.setattr("cryodaq.web.rest_api.get_config_dir", lambda: tmp_path)
    with patch("cryodaq.web.server._zmq_to_ws_bridge"):
        app = create_app()
        with TestClient(app) as c, patch("cryodaq.web.server._async_engine_command", side_effect=AssertionError):
            assert c.post("/api/v1/experiment").status_code == 403
            assert c.post("/api/v1/state").status_code == 403
            assert c.post("/api/v1/experiment/note").status_code == 403


# ---------------------------------------------------------------------------
# H1: auth runs BEFORE body parsing (WriteAuthMiddleware)
#
# FastAPI resolves body models in the same dependency pass as
# require_write_token, so invalid JSON on a write route would 422 before the
# route dependency runs — an unauthenticated parser path. The middleware moves
# the token check ahead of routing/parsing. The route dependency stays as
# defense-in-depth.
# ---------------------------------------------------------------------------


def _no_token_app(monkeypatch, tmp_path):
    monkeypatch.setattr("cryodaq.web.rest_api.get_config_dir", lambda: tmp_path)
    return create_app()


_BAD_JSON = {"content": "{", "headers": {"Content-Type": "application/json"}}


def test_invalid_json_without_token_is_403_not_422(monkeypatch, tmp_path) -> None:
    """Invalid JSON + no token ⇒ 403 (fail-closed), not 422 — the parser is
    never reached by an unauthenticated client."""
    with (
        patch("cryodaq.web.server._zmq_to_ws_bridge"),
        patch("cryodaq.web.server._async_engine_command", side_effect=AssertionError),
    ):
        app = _no_token_app(monkeypatch, tmp_path)
        with TestClient(app) as c:
            resp = c.post("/api/v1/log", content="{", headers={"Content-Type": "application/json"})
    assert resp.status_code == 403


def test_invalid_json_wrong_token_is_401_not_422(monkeypatch, tmp_path) -> None:
    """Invalid JSON + wrong bearer ⇒ 401, not 422 — auth precedes the parser."""
    monkeypatch.setattr("cryodaq.web.rest_api.get_config_dir", lambda: tmp_path)
    (tmp_path / "web.local.yaml").write_text(f'web:\n  api_token: "{_TOKEN}"\n', encoding="utf-8")
    with (
        patch("cryodaq.web.server._zmq_to_ws_bridge"),
        patch("cryodaq.web.server._async_engine_command", side_effect=AssertionError),
    ):
        app = create_app()
        with TestClient(app) as c:
            resp = c.post(
                "/api/v1/log",
                content="{",
                headers={"Content-Type": "application/json", "Authorization": "Bearer wrong"},
            )
    assert resp.status_code == 401


def test_unauthorized_log_request_never_generates_mutation_identity(auth_client) -> None:
    """Middleware rejects before body parsing and before producer-side mutation setup."""
    with (
        patch("cryodaq.web.rest_api.secrets.token_hex", side_effect=AssertionError),
        patch("cryodaq.web.server._async_engine_command", side_effect=AssertionError),
    ):
        response = auth_client.post(
            "/api/v1/log",
            content="{",
            headers={"Content-Type": "application/json", "Authorization": "Bearer wrong"},
        )

    assert response.status_code == 401


def test_valid_auth_then_invalid_json_is_422(auth_client) -> None:
    """With valid auth the parser DOES run and rejects malformed JSON (422) —
    proving auth precedes, not replaces, body validation."""
    with patch("cryodaq.web.server._async_engine_command", side_effect=AssertionError):
        resp = auth_client.post(
            "/api/v1/log",
            content="{",
            headers={**_AUTH, "Content-Type": "application/json"},
        )
    assert resp.status_code == 422


def test_get_routes_bypass_write_auth_middleware(auth_client) -> None:
    """The write-auth middleware never touches GET routes (reads stay open on
    loopback even with a token configured)."""
    assert auth_client.get("/api/v1/state").status_code == 200


# ---------------------------------------------------------------------------
# M1: reserved-tag impersonation guard on POST /api/v1/log
#
# Certain tags are semantic system categories downstream (context_builder /
# event_logger / shift_handover / safety-fault log). A REST caller must not
# forge them; genuinely free-form tags still pass through.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reserved", "canonical"),
    [
        ("safety_fault", "safety_fault"),
        (" phase_transition ", "phase_transition"),
        ("Alarm", "alarm"),
        (" AI ", "ai"),
    ],
)
def test_post_log_rejects_reserved_tag(auth_client, reserved: str, canonical: str) -> None:
    """A reserved (system-semantic) tag ⇒ 422 naming the tag, engine untouched."""
    with patch("cryodaq.web.server._async_engine_command", side_effect=AssertionError):
        resp = auth_client.post(
            "/api/v1/log",
            headers=_AUTH,
            json={"message": "ok", "tags": [reserved]},
        )
    assert resp.status_code == 422
    assert canonical in resp.json()["detail"]


def test_post_log_freeform_tags_pass_through(auth_client) -> None:
    """Genuinely free-form tags are forwarded verbatim to the engine command."""
    captured: dict = {}

    async def _fake(cmd: dict) -> dict:
        captured.update(cmd)
        return {"ok": True, "entry": {"id": 1}}

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        resp = auth_client.post(
            "/api/v1/log",
            headers=_AUTH,
            json={"message": "ok", "tags": ["насос", "проверка"]},
        )
    assert resp.status_code == 200
    assert captured["tags"] == ["насос", "проверка"]
