"""Tests for the read-only REST facade at /api/v1.

The facade is a thin, field-whitelisted layer over the same cache/command
path the dashboard uses. These tests pin the two security properties that
matter: field whitelisting (no operator/sample/notes/config leakage) and the
request-size limit, plus the read-only contract (no write verbs).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import MISSING, fields
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from cryodaq.core.alarm_ack_codec import alarm_ack_request_fingerprint
from cryodaq.core.command_authority import ENGINE_MUTATION_CAPABILITY, MUTATION_PROTOCOL_MAJOR
from cryodaq.core.operator_log import OperatorLogEntry
from cryodaq.core.zmq_bridge import PROTOCOL_VERSION, ZMQCommandServer
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.engine import EngineCommandContext, _handle_gui_command, _operator_log_committed_pending
from cryodaq.storage.sqlite_writer import SQLiteWriter
from cryodaq.web.server import create_app


@pytest.fixture()
def client():
    """TestClient with the ZMQ bridge mocked out."""
    with patch("cryodaq.web.server._zmq_to_ws_bridge"):
        app = create_app()
        with TestClient(app) as c:
            yield c


def _mark_readings_producer_live() -> None:
    """Establish fresh producer authority before directly exercising its cache."""
    from cryodaq.web import server

    server._on_reading_callback(
        Reading(
            timestamp=datetime.now(UTC),
            instrument_id="test",
            channel="availability-proof",
            value=1.0,
            unit="K",
            status=ChannelStatus.OK,
        )
    )


async def test_app_lifespan_owns_and_settles_all_background_tasks(monkeypatch) -> None:
    from cryodaq.web import server

    started: set[str] = set()
    settled: set[str] = set()

    async def _background_owner(label: str) -> None:
        started.add(label)
        try:
            await asyncio.Future()
        finally:
            settled.add(label)

    monkeypatch.setattr(server, "_broadcast_pump", lambda: _background_owner("pump"))
    monkeypatch.setattr(server, "_zmq_to_ws_bridge", lambda: _background_owner("zmq"))
    app = create_app()

    async with app.router.lifespan_context(app):
        await asyncio.sleep(0)
        assert started == {"pump", "zmq"}
        assert server._state.broadcast_q is not None
        assert server._state.broadcast_q.maxsize == 200
        live_names = {task.get_name() for task in asyncio.all_tasks() if not task.done()}
        assert {"broadcast_pump", "zmq_ws_bridge"} <= live_names

    assert settled == {"pump", "zmq"}
    assert server._state.broadcast_q is None


async def test_web_zmq_bridge_cancellation_settles_exact_subscriber(monkeypatch) -> None:
    from cryodaq.web import server

    started = asyncio.Event()

    class _Subscriber:
        def __init__(self) -> None:
            self.stop_calls = 0

        async def start(self) -> None:
            started.set()

        async def stop(self) -> None:
            self.stop_calls += 1

    subscriber = _Subscriber()
    monkeypatch.setattr(server, "ZMQSubscriber", lambda **_kwargs: subscriber)
    task = asyncio.create_task(server._zmq_to_ws_bridge())
    await asyncio.wait_for(started.wait(), timeout=1.0)
    assert server._state.subscriber is subscriber

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert subscriber.stop_calls == 1
    assert server._state.subscriber is None


def test_temperatures_returns_kelvin_readings(client) -> None:
    """/api/v1/temperatures exposes only K-unit readings from the cache."""
    from cryodaq.web import server

    _mark_readings_producer_live()
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


@pytest.mark.parametrize(
    "path",
    ["/api/v1/readings", "/api/v1/temperatures", "/api/v1/pressure"],
)
def test_reading_endpoints_do_not_present_dead_producer_cache_as_current(client, monkeypatch, path: str) -> None:
    """A dead reading producer must make cached values visibly unavailable."""
    from cryodaq.web import server

    monkeypatch.setattr(server, "_state", server._ServerState())
    server._on_reading_callback(
        Reading(
            timestamp=datetime.now(UTC),
            instrument_id="test",
            channel="T-proof",
            value=4.2,
            unit="K",
            status=ChannelStatus.OK,
        )
    )
    server._on_reading_callback(
        Reading(
            timestamp=datetime.now(UTC),
            instrument_id="test",
            channel="P-proof",
            value=1e-5,
            unit="mbar",
            status=ChannelStatus.OK,
        )
    )
    server._state.invalidate_producer("proof producer died")

    response = client.get(path)

    assert response.json() == {
        "available": False,
        "stale": True,
        "reason": "proof producer died",
    }
    assert response.status_code == 503


@pytest.mark.parametrize(
    ("path", "channels"),
    [
        ("/api/v1/readings", {"T-proof", "P-proof"}),
        ("/api/v1/temperatures", {"T-proof"}),
        ("/api/v1/pressure", {"P-proof"}),
    ],
)
def test_reading_endpoints_keep_reachable_producer_payloads_ordinary(
    client, monkeypatch, path: str, channels: set[str]
) -> None:
    """Reachable producer data remains the pre-existing 200 list response."""
    from cryodaq.web import server

    monkeypatch.setattr(server, "_state", server._ServerState())
    server._on_reading_callback(
        Reading(
            timestamp=datetime.now(UTC),
            instrument_id="test",
            channel="T-proof",
            value=4.2,
            unit="K",
            status=ChannelStatus.OK,
        )
    )
    server._on_reading_callback(
        Reading(
            timestamp=datetime.now(UTC),
            instrument_id="test",
            channel="P-proof",
            value=1e-5,
            unit="mbar",
            status=ChannelStatus.OK,
        )
    )

    response = client.get(path)

    assert response.status_code == 200
    assert isinstance(response.json(), list)
    assert {reading["channel"] for reading in response.json()} == channels


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

    _mark_readings_producer_live()
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


def test_get_experiment_distinguishes_unavailable_from_no_experiment(client) -> None:
    """Engine unavailability must not share a shape with a genuine empty.

    A dropped/non-ok engine yields 503 + ``{available:false, stale, reason}``;
    a reachable engine with no active experiment stays 200 + the authoritative
    ``active_experiment=null`` projection. A client can tell them apart.
    """
    envelope = {"available": False, "stale": True, "reason": "experiment status unavailable"}

    async def _non_ok(req: dict) -> dict:
        assert req == {"cmd": "experiment_status"}
        return {"ok": False}

    async def _raises(req: dict) -> dict:
        assert req == {"cmd": "experiment_status"}
        raise RuntimeError("engine offline")

    async def _ok_no_experiment(req: dict) -> dict:
        assert req == {"cmd": "experiment_status"}
        return {"ok": True}

    with patch("cryodaq.web.server._async_engine_command", side_effect=_non_ok):
        non_ok = client.get("/api/v1/experiment")
    with patch("cryodaq.web.server._async_engine_command", side_effect=_raises):
        raised = client.get("/api/v1/experiment")
    with patch("cryodaq.web.server._async_engine_command", side_effect=_ok_no_experiment):
        empty = client.get("/api/v1/experiment")

    assert non_ok.status_code == 503
    assert non_ok.json() == envelope
    assert raised.status_code == 503
    assert raised.json() == envelope
    assert empty.status_code == 200
    assert empty.json() == {"active_experiment": None, "current_phase": None, "phase_started_at": None}


def test_get_log_distinguishes_unavailable_from_empty(client) -> None:
    """Engine unavailability must not share a shape with a genuine empty log."""
    envelope = {"available": False, "stale": True, "reason": "operator log unavailable"}

    async def _non_ok(req: dict) -> dict:
        assert req == {"cmd": "log_get", "limit": 10}
        return {"ok": False}

    async def _raises(req: dict) -> dict:
        assert req == {"cmd": "log_get", "limit": 10}
        raise RuntimeError("engine offline")

    async def _ok_empty(req: dict) -> dict:
        assert req == {"cmd": "log_get", "limit": 10}
        return {"ok": True, "entries": []}

    with patch("cryodaq.web.server._async_engine_command", side_effect=_non_ok):
        non_ok = client.get("/api/v1/log")
    with patch("cryodaq.web.server._async_engine_command", side_effect=_raises):
        raised = client.get("/api/v1/log")
    with patch("cryodaq.web.server._async_engine_command", side_effect=_ok_empty):
        empty = client.get("/api/v1/log")

    assert non_ok.status_code == 503
    assert non_ok.json() == envelope
    assert raised.status_code == 503
    assert raised.json() == envelope
    assert empty.status_code == 200
    assert empty.json() == []


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


def _log_headers(request_id: str = "a" * 32) -> dict[str, str]:
    """Bind each operator-log write to a caller-owned retry identity."""

    return {**_AUTH, "Idempotency-Key": request_id}


def _published_log_result(command: dict, *, entry_id: int = 1) -> dict:
    """Return one complete receipt bound to the exact REST submission."""

    experiment_id = command.get("experiment_id")
    entry = {
        "id": entry_id,
        "timestamp": "2026-07-23T00:00:00+00:00",
        "experiment_id": experiment_id,
        "author": _REST_IDENTITY,
        "source": "rest",
        "message": command["message"],
        "tags": list(command.get("tags", [])),
    }
    return {
        "ok": True,
        "committed": True,
        "retry_safe": False,
        "publication_state": "published",
        "proto": PROTOCOL_VERSION,
        "entry": entry,
        "commit_receipt": {
            "schema": "operator_log_commit_v1",
            "request_id": command["request_id"],
            "entry_id": entry_id,
            "experiment_id": experiment_id,
            "committed": True,
        },
    }


def _wire_command_reply(reply: dict[str, object]) -> dict[str, object]:
    """Exercise the ZMQ producer's one authoritative reply envelope."""

    return json.loads(ZMQCommandServer(handler=None)._encode_reply(reply))


def _assert_unknown_settlement_response(response, request_id: str) -> None:
    """Unknown replies may expose only the bounded reconciliation evidence keys."""

    assert response.status_code == 502
    body = response.json()
    assert body["ok"] is False
    assert body["error_code"] == "operator_log_settlement_malformed"
    assert body["error"] == "engine returned an unknown or malformed operator-log settlement"
    assert body["commit_state"] == "unknown"
    assert body["retry_safe"] is False
    assert body["caller_request_id"] == request_id
    assert set(body["engine_settlement"]) <= {
        "ok",
        "committed",
        "retry_safe",
        "publication_state",
        "commit_state",
        "delivery_state",
        "error_code",
        "proto",
        "schema",
        "request_id",
    }
    assert "error" not in body["engine_settlement"]


def _shutdown_latched_producer_reply() -> dict[str, object]:
    """Produce the shutdown-latch refusal through the live engine handler."""

    required: dict[str, object] = {}
    for item in fields(EngineCommandContext):
        if item.default is MISSING and item.default_factory is MISSING:
            required[item.name] = MagicMock(name=item.name)
    context = EngineCommandContext(**required)
    context.shutdown_request_id = "a" * 32
    context.mutation_capability_token = "m" * 32
    return _wire_command_reply(
        asyncio.run(
            _handle_gui_command(
                {
                    "cmd": "keithley_start",
                    "channel": "smua",
                    "protocol_major": MUTATION_PROTOCOL_MAJOR,
                    "mutation_capability": ENGINE_MUTATION_CAPABILITY,
                    "capability_token": context.mutation_capability_token,
                },
                context=context,
            )
        )
    )


# --- POST /api/v1/log -------------------------------------------------------


def test_post_log_forwards_log_entry_command(auth_client) -> None:
    """An unscoped POST carries one exact idempotency key and explicit scope."""
    captured: dict = {}

    async def _fake(cmd: dict) -> dict:
        captured.update(cmd)
        return _published_log_result(cmd)

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        resp = auth_client.post(
            "/api/v1/log",
            headers=_log_headers("a" * 32),
            json={"message": "проверка насоса"},
        )

    assert resp.status_code == 200
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
        return _published_log_result(cmd)

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        response = auth_client.post(
            "/api/v1/log",
            headers=_log_headers("b" * 32),
            json={"message": "scoped", "experiment_id": "exp-exact"},
        )

    assert response.status_code == 200
    assert captured["request_id"] == "b" * 32
    assert captured["experiment_id"] == "exp-exact"
    assert "experiment_unbound" not in captured
    assert "current_experiment" not in captured


def test_post_log_canonicalizes_before_sqlite_admission_and_exact_receipt_reconciliation(auth_client) -> None:
    captured: list[dict[str, object]] = []

    async def _real_admission(cmd: dict) -> dict:
        admission = SQLiteWriter.validate_operator_log_publication_admission(
            request_id=cmd["request_id"],
            message=cmd["message"],
            author=cmd["author"],
            source=cmd["source"],
            experiment_id=cmd.get("experiment_id"),
            tags=cmd.get("tags"),
        )
        captured.append(dict(cmd))
        assert cmd["message"] == admission.message
        assert cmd["experiment_id"] == admission.experiment_id
        assert cmd["tags"] == list(admission.tags)
        return _published_log_result(cmd)

    raw = {
        "message": "  observed locally  ",
        "experiment_id": "  exp-exact  ",
        "tags": ["  reviewed  ", "   "],
    }
    with patch("cryodaq.web.server._async_engine_command", side_effect=_real_admission):
        first = auth_client.post("/api/v1/log", headers=_log_headers("9" * 32), json=raw)
        replay = auth_client.post("/api/v1/log", headers=_log_headers("9" * 32), json=raw)

    assert first.status_code == replay.status_code == 200
    assert captured == [
        {
            "cmd": "log_entry",
            "request_id": "9" * 32,
            "message": "observed locally",
            "author": _REST_IDENTITY,
            "source": "rest",
            "experiment_id": "exp-exact",
            "tags": ["reviewed"],
        },
        {
            "cmd": "log_entry",
            "request_id": "9" * 32,
            "message": "observed locally",
            "author": _REST_IDENTITY,
            "source": "rest",
            "experiment_id": "exp-exact",
            "tags": ["reviewed"],
        },
    ]


def test_post_log_author_is_server_set_not_spoofable(auth_client) -> None:
    """The author forwarded to the engine is the REST identity, never client
    input — and a client-supplied author key is rejected (422), not honored."""
    captured: dict = {}

    async def _fake(cmd: dict) -> dict:
        captured.update(cmd)
        return _published_log_result(cmd)

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        ok = auth_client.post("/api/v1/log", headers=_log_headers("c" * 32), json={"message": "hi"})
        spoof = auth_client.post(
            "/api/v1/log",
            headers=_log_headers("d" * 32),
            json={"message": "hi", "author": "victim"},
        )

    assert ok.status_code == 200
    assert captured["author"] == _REST_IDENTITY
    assert spoof.status_code == 422  # extra field forbidden — no impersonation


@pytest.mark.parametrize(
    "corruption",
    [
        "missing_publication",
        "wrong_request",
        "wrong_author",
        "missing_proto",
        "wrong_proto",
        "bool_proto",
        "extra_key",
    ],
)
def test_post_log_rejects_incomplete_or_misbound_success_receipt(auth_client, corruption: str) -> None:
    async def _fake(cmd: dict) -> dict:
        result = _published_log_result(cmd)
        if corruption == "missing_publication":
            result.pop("publication_state")
        elif corruption == "wrong_request":
            result["commit_receipt"]["request_id"] = "f" * 32
        elif corruption == "wrong_author":
            result["entry"]["author"] = "forged"
        elif corruption == "missing_proto":
            result.pop("proto")
        elif corruption == "wrong_proto":
            result["proto"] = PROTOCOL_VERSION + 1
        elif corruption == "bool_proto":
            result["proto"] = True
        else:
            result["unexpected"] = True
        return result

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        response = auth_client.post(
            "/api/v1/log",
            headers=_log_headers("e" * 32),
            json={"message": "exact"},
        )

    assert response.status_code == 502


@pytest.mark.parametrize(
    ("entry_id", "receipt_entry_id", "expected_status"),
    [
        pytest.param(True, 1, 502, id="entry-bool"),
        pytest.param(1.0, 1, 502, id="entry-float"),
        pytest.param(2**63, 2**63, 502, id="entry-above-sqlite-rowid-range"),
        pytest.param(1, True, 502, id="receipt-bool"),
        pytest.param(1, 1.0, 502, id="receipt-float"),
        pytest.param(1, 2**63, 502, id="receipt-above-sqlite-rowid-range"),
        pytest.param(1, 2, 502, id="entry-receipt-mismatch"),
        pytest.param(2**63 - 1, 2**63 - 1, 200, id="sqlite-rowid-upper-boundary"),
    ],
)
def test_post_log_requires_exact_sqlite_rowid_receipt_identities(
    auth_client,
    entry_id: object,
    receipt_entry_id: object,
    expected_status: int,
) -> None:
    async def _fake(cmd: dict) -> dict:
        result = _published_log_result(cmd)
        result["entry"]["id"] = entry_id
        result["commit_receipt"]["entry_id"] = receipt_entry_id
        return result

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        response = auth_client.post(
            "/api/v1/log",
            headers=_log_headers("b" * 32),
            json={"message": "strict row id"},
        )

    assert response.status_code == expected_status


def test_post_log_accepts_commit_from_real_zmq_reply_encoder(auth_client) -> None:
    async def _fake(cmd: dict) -> dict:
        handler_result = _published_log_result(cmd)
        handler_result.pop("proto")
        return json.loads(ZMQCommandServer(handler=None)._encode_reply(handler_result))

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        response = auth_client.post(
            "/api/v1/log",
            headers=_log_headers("f" * 32),
            json={"message": "real encoded receipt"},
        )

    assert response.status_code == 200


@pytest.mark.parametrize(
    ("settlement", "expected_status"),
    [
        pytest.param(
            {
                "ok": False,
                "committed": True,
                "retry_safe": False,
                "publication_state": "pending",
                "proto": PROTOCOL_VERSION,
                "error_code": "committed_reconciliation_failed",
                "error": "operator log committed, but required publication remains pending",
            },
            503,
            id="committed-publication-pending",
        ),
        pytest.param(
            {
                "ok": False,
                "committed": False,
                "retry_safe": True,
                "error_code": "operator_log_busy",
                "error": "another durable experiment mutation is still authoritative",
                "request_id": "d" * 32,
                "proto": PROTOCOL_VERSION,
            },
            409,
            id="definite-rejection",
        ),
        pytest.param(
            {
                "ok": False,
                "error_code": "command_request_invalid",
                "error": "Command request is invalid.",
                "delivery_state": "not_dispatched",
                "commit_state": "not_committed",
                "retry_safe": True,
                "proto": PROTOCOL_VERSION,
            },
            409,
            id="bridge-not-dispatched",
        ),
        pytest.param(
            {
                "ok": False,
                "retry_safe": False,
                "error_code": "operator_log_commit_outcome_unknown",
                "error": "operator log commit outcome is unknown; reconcile this exact request key",
                "commit_state": "unknown",
                "request_id": "d" * 32,
                "proto": PROTOCOL_VERSION,
            },
            502,
            id="outcome-unknown",
        ),
    ],
)
def test_post_log_non_success_settlement_keeps_body_and_uses_non_2xx(
    auth_client,
    settlement: dict[str, object],
    expected_status: int,
) -> None:
    request_id = "d" * 32

    async def _fake(cmd: dict) -> dict:
        if settlement.get("publication_state") == "pending":
            pending = _published_log_result(cmd)
            pending.update(settlement)
            return pending
        return dict(settlement)

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        response = auth_client.post(
            "/api/v1/log",
            headers=_log_headers(request_id),
            json={"message": "settlement"},
        )

    assert response.status_code == expected_status
    expected_body = dict(settlement)
    if settlement.get("publication_state") == "pending":
        expected_body = _published_log_result(
            {
                "request_id": request_id,
                "message": "settlement",
                "experiment_unbound": True,
            }
        )
        expected_body.update(settlement)
        expected_body["caller_request_id"] = request_id
    elif expected_status == 409:
        expected_body["caller_request_id"] = request_id
    else:
        expected_body = {
            "ok": False,
            "error_code": "operator_log_settlement_malformed",
            "error": "engine returned an unknown or malformed operator-log settlement",
            "commit_state": "unknown",
            "retry_safe": False,
            "caller_request_id": request_id,
            "engine_settlement": {
                "ok": False,
                "retry_safe": False,
                "error_code": "operator_log_commit_outcome_unknown",
                "commit_state": "unknown",
                "request_id": request_id,
                "proto": PROTOCOL_VERSION,
            },
        }
    assert response.json() == expected_body


@pytest.mark.parametrize(
    "producer_reply",
    [
        pytest.param(
            lambda request_id: {
                "ok": False,
                "committed": False,
                "error_code": "operator_log_admission_invalid",
                "error": "Operator-log command or publication fields are invalid.",
                "retry_safe": True,
                "request_id": request_id,
            },
            id="engine-refusal-with-request-id",
        ),
        pytest.param(
            lambda _request_id: {
                "ok": False,
                "error_code": "command_request_invalid",
                "error": "Command request is invalid.",
                "delivery_state": "not_dispatched",
                "commit_state": "not_committed",
                "retry_safe": True,
            },
            id="bridge-pre-dispatch-refusal",
        ),
        pytest.param(
            lambda _request_id: {
                "ok": False,
                "error_code": "mutation_protocol_incompatible",
                "error": "mutating command refused; perform mutation_capabilities discovery and retry explicitly",
                "delivery_state": "dispatched",
                "commit_state": "not_committed",
                "retry_safe": True,
                "compatibility_receipt": {
                    "schema": "mutation_compatibility_v1",
                    "accepted": False,
                    "server_protocol_major": 1,
                    "required_capability": "cryodaq_mutation_v1",
                },
            },
            id="exact-compatibility-refusal",
        ),
    ],
)
def test_post_log_accepts_only_wire_enveloped_producer_refusals(auth_client, producer_reply) -> None:
    request_id = "c" * 32
    settlement = _wire_command_reply(producer_reply(request_id))

    async def _fake(_cmd: dict) -> dict[str, object]:
        return settlement

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        response = auth_client.post(
            "/api/v1/log",
            headers=_log_headers(request_id),
            json={"message": "refusal"},
        )

    assert response.status_code == 409
    assert response.json() == {**settlement, "caller_request_id": request_id}


def test_post_log_accepts_real_web_mutation_discovery_refusal(auth_client) -> None:
    from cryodaq.web import server

    request_id = "c" * 32
    settlement = server._mutation_discovery_failure()

    async def _fake(_cmd: dict) -> dict[str, object]:
        return settlement

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        response = auth_client.post(
            "/api/v1/log",
            headers=_log_headers(request_id),
            json={"message": "discovery refusal"},
        )

    assert response.status_code == 409
    assert response.json() == {**settlement, "caller_request_id": request_id}


@pytest.mark.parametrize(
    "mutation",
    (
        "missing-field",
        "extra-field",
        "invented-code",
        "invented-error",
        "wrong-error-code-type",
        "wrong-error-type",
        "wrong-delivery-type",
        "wrong-commit-type",
        "wrong-retry-type",
        "injected-proto",
        "contradictory-commit",
        "contradictory-retry",
        "contradictory-dispatch",
        "mismatched-caller-identity",
    ),
)
def test_post_log_rejects_near_miss_web_mutation_discovery_refusals(auth_client, mutation: str) -> None:
    from cryodaq.web import server

    request_id = "c" * 32
    settlement = server._mutation_discovery_failure()
    if mutation == "missing-field":
        settlement.pop("compatibility_receipt")
    elif mutation == "extra-field":
        settlement["unexpected"] = True
    elif mutation == "invented-code":
        settlement["error_code"] = "invented_discovery_failure"
    elif mutation == "invented-error":
        settlement["error"] = "invented discovery failure"
    elif mutation == "wrong-error-code-type":
        settlement["error_code"] = 0
    elif mutation == "wrong-error-type":
        settlement["error"] = 0
    elif mutation == "wrong-delivery-type":
        settlement["delivery_state"] = 0
    elif mutation == "wrong-commit-type":
        settlement["commit_state"] = 0
    elif mutation == "wrong-retry-type":
        settlement["retry_safe"] = 1
    elif mutation == "injected-proto":
        settlement["proto"] = PROTOCOL_VERSION
    elif mutation == "contradictory-commit":
        settlement["commit_state"] = "committed"
    elif mutation == "contradictory-retry":
        settlement["retry_safe"] = False
    elif mutation == "contradictory-dispatch":
        settlement["delivery_state"] = "dispatched"
    else:
        settlement["request_id"] = "d" * 32

    async def _fake(_cmd: dict) -> dict[str, object]:
        return settlement

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        response = auth_client.post(
            "/api/v1/log",
            headers=_log_headers(request_id),
            json={"message": "discovery near miss"},
        )

    _assert_unknown_settlement_response(response, request_id)
    if mutation == "mismatched-caller-identity":
        assert "request_id" not in response.json()["engine_settlement"]


def test_post_log_accepts_real_engine_shutdown_latch_refusal(auth_client) -> None:
    request_id = "d" * 32
    settlement = _shutdown_latched_producer_reply()

    assert PROTOCOL_VERSION == 2
    assert settlement == {
        "ok": False,
        "error_code": "engine_shutdown_latched",
        "error": "engine shutdown owns mutation admission; later state changes are refused",
        "delivery_state": "dispatched",
        "commit_state": "not_committed",
        "retry_safe": False,
        "proto": 2,
    }

    async def _fake(_cmd: dict) -> dict[str, object]:
        return settlement

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        response = auth_client.post(
            "/api/v1/log",
            headers=_log_headers(request_id),
            json={"message": "shutdown latch"},
        )

    assert response.status_code == 409
    assert response.json() == {**settlement, "caller_request_id": request_id}


@pytest.mark.parametrize(
    "mutation",
    (
        "missing-field",
        "extra-field",
        "schema-wrong-type",
        "schema-wrong-value",
        "accepted-int-zero",
        "accepted-wrong-value",
        "major-bool",
        "major-float",
        "major-wrong-value",
        "capability-wrong-type",
        "capability-wrong-value",
    ),
)
def test_post_log_rejects_nonexact_compatibility_refusal_receipt(auth_client, mutation: str) -> None:
    request_id = "e" * 32
    producer_reply: dict[str, object] = {
        "ok": False,
        "error_code": "mutation_protocol_incompatible",
        "error": "mutating command refused; perform mutation_capabilities discovery and retry explicitly",
        "delivery_state": "dispatched",
        "commit_state": "not_committed",
        "retry_safe": True,
        "compatibility_receipt": {
            "schema": "mutation_compatibility_v1",
            "accepted": False,
            "server_protocol_major": 1,
            "required_capability": "cryodaq_mutation_v1",
        },
    }
    receipt = producer_reply["compatibility_receipt"]
    assert type(receipt) is dict
    if mutation == "missing-field":
        receipt.pop("accepted")
    elif mutation == "extra-field":
        receipt["unexpected"] = True
    elif mutation == "schema-wrong-type":
        receipt["schema"] = True
    elif mutation == "schema-wrong-value":
        receipt["schema"] = "other"
    elif mutation == "accepted-int-zero":
        receipt["accepted"] = 0
    elif mutation == "accepted-wrong-value":
        receipt["accepted"] = True
    elif mutation == "major-bool":
        receipt["server_protocol_major"] = True
    elif mutation == "major-float":
        receipt["server_protocol_major"] = 1.0
    elif mutation == "major-wrong-value":
        receipt["server_protocol_major"] = 2
    elif mutation == "capability-wrong-type":
        receipt["required_capability"] = True
    else:
        receipt["required_capability"] = "other"
    settlement = _wire_command_reply(producer_reply)

    async def _fake(_cmd: dict) -> dict[str, object]:
        return settlement

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        response = auth_client.post(
            "/api/v1/log",
            headers=_log_headers(request_id),
            json={"message": "compatibility receipt"},
        )

    _assert_unknown_settlement_response(response, request_id)


def test_post_log_unknown_settlement_omits_other_canonical_request_id(auth_client) -> None:
    request_id = "a" * 32
    settlement: dict[str, object] = {
        "ok": False,
        "committed": False,
        "retry_safe": False,
        "error_code": "operator_log_state_invalid",
        "request_id": "b" * 32,
    }

    async def _fake(_cmd: dict) -> dict[str, object]:
        return settlement

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        response = auth_client.post(
            "/api/v1/log",
            headers=_log_headers(request_id),
            json={"message": "foreign correlation"},
        )

    _assert_unknown_settlement_response(response, request_id)
    assert "request_id" not in response.json()["engine_settlement"]


@pytest.mark.parametrize(
    "mutation",
    (
        "unknown-commit-with-injected-committed",
        "unknown-persistence-with-injected-committed",
        "made-up-code",
        "missing-proto",
        "bool-proto",
        "wrong-proto",
        "empty-error",
        "extra-key",
    ),
)
def test_post_log_malformed_refusal_variants_are_unknown_settlements(auth_client, mutation: str) -> None:
    request_id = "f" * 32
    producer_reply: dict[str, object] = {
        "ok": False,
        "committed": False,
        "error_code": "operator_log_admission_invalid",
        "error": "Operator-log command or publication fields are invalid.",
        "retry_safe": True,
        "request_id": request_id,
    }
    if mutation == "unknown-commit-with-injected-committed":
        producer_reply = {
            "ok": False,
            "error_code": "operator_log_commit_outcome_unknown",
            "error": "operator log commit outcome is unknown; reconcile this exact request key",
            "commit_state": "unknown",
            "retry_safe": False,
            "request_id": request_id,
        }
    elif mutation == "unknown-persistence-with-injected-committed":
        producer_reply = {
            "ok": False,
            "error_code": "operator_log_persistence_failed",
            "error": "operator log persistence outcome is unknown; reconcile this exact request key",
            "commit_state": "unknown",
            "retry_safe": False,
            "request_id": request_id,
        }
    settlement = _wire_command_reply(producer_reply)
    if mutation.startswith("unknown-"):
        settlement["committed"] = False
    elif mutation == "made-up-code":
        settlement["error_code"] = "operator_log_refused_by_magic"
    elif mutation == "missing-proto":
        settlement.pop("proto")
    elif mutation == "bool-proto":
        settlement["proto"] = True
    elif mutation == "wrong-proto":
        settlement["proto"] = PROTOCOL_VERSION + 1
    elif mutation == "empty-error":
        settlement["error"] = ""
    else:
        settlement["unexpected"] = True

    async def _fake(_cmd: dict) -> dict[str, object]:
        return settlement

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        response = auth_client.post(
            "/api/v1/log",
            headers=_log_headers(request_id),
            json={"message": "refusal"},
        )

    _assert_unknown_settlement_response(response, request_id)


def test_post_log_malformed_settlement_keeps_safe_evidence_and_caller_correlation(auth_client) -> None:
    request_id = "e" * 32

    async def _fake(_cmd: dict) -> list[object]:
        return []

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        response = auth_client.post(
            "/api/v1/log",
            headers=_log_headers(request_id),
            json={"message": "malformed"},
        )

    _assert_unknown_settlement_response(response, request_id)
    assert response.json()["engine_settlement"] == {}


@pytest.mark.parametrize(
    "settlement",
    [
        {
            "ok": False,
            "committed": False,
            "retry_safe": False,
            "error_code": "operator_log_commit_outcome_unknown",
            "error": "the result must be reconciled",
            "outcome_unknown": True,
            "delivery_state": "not_dispatched",
            "commit_state": "not_committed",
        },
        {
            "ok": False,
            "committed": False,
            "retry_safe": False,
            "error_code": "operator_log_state_invalid",
            "error": "the transport settlement is invalid",
            "delivery_state": True,
            "commit_state": "not_committed",
        },
        {
            "ok": False,
            "committed": False,
            "retry_safe": False,
            "error_code": "operator_log_state_invalid",
            "error": "the transport settlement is invalid",
            "delivery_state": "not_dispatched",
            "commit_state": True,
        },
        {
            "ok": False,
            "committed": False,
            "retry_safe": False,
            "error_code": "operator_log_state_invalid",
            "error": "the transport settlement contradicts itself",
            "delivery_state": "not_dispatched",
            "commit_state": "committed",
        },
        {
            "ok": False,
            "committed": False,
            "retry_safe": False,
            "error_code": "operator_log_state_invalid",
            "error": "the transport settlement has an invalid state",
            "delivery_state": "not_dispatched",
            "commit_state": "invalid",
        },
        {
            "ok": False,
            "committed": False,
            "retry_safe": False,
            "error_code": "operator_log_state_invalid",
            "error": "the settlement belongs to a different request",
            "request_id": "e" * 32,
        },
        {"ok": True},
    ],
    ids=(
        "explicit-outcome-unknown-precedence",
        "boolean-delivery-state",
        "boolean-commit-state",
        "contradictory-commit-state",
        "invalid-commit-state",
        "mismatched-engine-request-id",
        "optimistic-malformed-dict",
    ),
)
def test_post_log_unknown_or_malformed_settlement_is_wrapped_not_rejected(
    auth_client,
    settlement: dict[str, object],
) -> None:
    request_id = "f" * 32

    async def _fake(_cmd: dict) -> dict[str, object]:
        return settlement

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        response = auth_client.post(
            "/api/v1/log",
            headers=_log_headers(request_id),
            json={"message": "settlement"},
        )

    _assert_unknown_settlement_response(response, request_id)
    if settlement.get("request_id") != request_id:
        assert "request_id" not in response.json()["engine_settlement"]


@pytest.mark.parametrize("bad_error", ("", "publication reconciliation is pending", True))
def test_post_log_committed_pending_requires_the_engine_diagnostic(auth_client, bad_error: object) -> None:
    """A committed-pending response is definite only with the producer literal."""

    request_id = "d" * 32

    async def _fake(cmd: dict) -> dict:
        pending = _published_log_result(cmd)
        pending.update(
            ok=False,
            publication_state="pending",
            error_code="committed_reconciliation_failed",
            error=bad_error,
        )
        return pending

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        response = auth_client.post(
            "/api/v1/log",
            headers=_log_headers(request_id),
            json={"message": "settlement"},
        )

    assert response.status_code == 502


def test_post_log_accepts_committed_pending_from_real_engine_helper_and_encoder(auth_client) -> None:
    """Bind the REST 503 branch to the actual operator-log pending producer."""

    request_id = "d" * 32

    async def _fake(cmd: dict) -> dict[str, object]:
        return _wire_command_reply(
            _operator_log_committed_pending(
                OperatorLogEntry(
                    id=1,
                    timestamp=datetime(2026, 7, 23, tzinfo=UTC),
                    experiment_id=None,
                    author="REST API",
                    source="rest",
                    message=cmd["message"],
                    tags=(),
                ),
                cmd["request_id"],
            )
        )

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        response = auth_client.post(
            "/api/v1/log",
            headers=_log_headers(request_id),
            json={"message": "producer pending"},
        )

    assert response.status_code == 503
    assert response.json()["error"] == "operator log committed, but required publication remains pending"
    assert response.json()["caller_request_id"] == request_id


def test_post_log_unknown_settlement_redacts_nested_sensitive_and_unsafe_values(auth_client) -> None:
    """The 502 route retains bounded status evidence without echoing opaque payloads."""

    request_id = "e" * 32
    settlement: dict[str, object] = {
        "ok": False,
        "committed": True,
        "retry_safe": False,
        "publication_state": "pending",
        "commit_state": "unknown",
        "error_code": "operator_log_state_invalid",
        "proto": PROTOCOL_VERSION,
        "schema": "operator_log_commit_v1",
        "request_id": request_id,
        "capability_token": "do-not-echo",
        "config_snapshot": {"nested": {"CAPABILITY_TOKEN": "do-not-echo"}},
        "entry": {"author": "operator", "message": "do-not-echo", "notes": ["do-not-echo"]},
        "artifact_path": "C:/secret/report.png",
        "bytes": b"do-not-echo",
    }
    settlement["cycle"] = settlement

    async def _fake(_cmd: dict) -> dict[str, object]:
        return settlement

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        response = auth_client.post(
            "/api/v1/log",
            headers=_log_headers(request_id),
            json={"message": "safe evidence"},
        )

    assert response.status_code == 502
    assert response.json() == {
        "ok": False,
        "error_code": "operator_log_settlement_malformed",
        "error": "engine returned an unknown or malformed operator-log settlement",
        "commit_state": "unknown",
        "retry_safe": False,
        "caller_request_id": request_id,
        "engine_settlement": {
            "ok": False,
            "committed": True,
            "retry_safe": False,
            "publication_state": "pending",
            "commit_state": "unknown",
            "error_code": "operator_log_state_invalid",
            "proto": PROTOCOL_VERSION,
            "schema": "operator_log_commit_v1",
            "request_id": request_id,
        },
    }


def test_post_log_unknown_settlement_bounds_deep_cyclic_and_huge_values(auth_client) -> None:
    """Adversarial unknown evidence cannot amplify or break the 502 response."""

    request_id = "f" * 32
    nested: dict[str, object] = {}
    cursor = nested
    for _ in range(8):
        child: dict[str, object] = {}
        cursor["next"] = child
        cursor = child
    cursor["cycle"] = nested
    settlement: dict[str, object] = {f"untrusted_{index}": "x" * 128 for index in range(1024)}
    settlement.update(
        {
            "schema": nested,
            "error_code": "x" * 1024,
            "proto": 10**100,
            "request_id": "not-a-request-id",
        }
    )

    async def _fake(_cmd: dict) -> dict[str, object]:
        return settlement

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        response = auth_client.post(
            "/api/v1/log",
            headers=_log_headers(request_id),
            json={"message": "bounded evidence"},
        )

    _assert_unknown_settlement_response(response, request_id)
    assert response.json()["engine_settlement"] == {}


def test_post_log_json_request_id_rejected_before_engine_call(auth_client) -> None:
    with patch("cryodaq.web.server._async_engine_command", side_effect=AssertionError):
        response = auth_client.post(
            "/api/v1/log",
            headers=_log_headers(),
            json={"message": "no JSON identity", "request_id": "f" * 32},
        )

    assert response.status_code == 422


def test_post_log_extra_field_rejected(auth_client) -> None:
    """Unknown keys → 422 (strict request model)."""
    with patch("cryodaq.web.server._async_engine_command", side_effect=AssertionError):
        resp = auth_client.post(
            "/api/v1/log",
            headers=_log_headers(),
            json={"message": "x", "bogus": 1},
        )
    assert resp.status_code == 422


def test_post_log_empty_message_rejected(auth_client) -> None:
    """Empty message → 422 before any engine call."""
    with patch("cryodaq.web.server._async_engine_command", side_effect=AssertionError):
        resp = auth_client.post("/api/v1/log", headers=_log_headers(), json={"message": ""})
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
        resp = auth_client.post("/api/v1/log", headers=_log_headers(), json=payload)
    assert resp.status_code == 422


def test_post_log_rejects_chunked_transfer_before_body_parse(auth_client) -> None:
    """The facade does not accept an unbounded body without Content-Length."""
    headers = {
        **_AUTH,
        "Idempotency-Key": "a" * 32,
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
            resp = c.post("/api/v1/log", headers=_log_headers(), json={"message": "x"})
    assert resp.status_code == 403


# --- POST /api/v1/alarms/{alarm_id}/ack ------------------------------------


_ENGINE_A = "1" * 32
_ACK_REQUEST_ID = "a" * 32
_ACK_REASON = "operator verified the active alarm"


def _ack_headers(request_id: str = _ACK_REQUEST_ID) -> dict[str, str]:
    return {**_AUTH, "Idempotency-Key": request_id}


def _ack_payload(
    *,
    engine_instance_id: object = _ENGINE_A,
    activation_id: object = "activation-1",
    reason: object = _ACK_REASON,
) -> dict[str, object]:
    return {
        "engine_instance_id": engine_instance_id,
        "activation_id": activation_id,
        "reason": reason,
    }


def _alarm_ack_handler_result(command: dict, state: str) -> dict:
    fingerprint = alarm_ack_request_fingerprint(command)
    source_activation_id = "1"
    if state == "aborted":
        return {
            "ok": False,
            "committed": False,
            "retry_safe": False,
            "publication_state": "aborted",
            "event_emitted": False,
            "error_code": "alarm_ack_aborted",
            "error": "alarm acknowledgement was terminally aborted before durable commit",
            "alarm_name": command["alarm_name"],
            "activation_id": command["activation_id"],
            "engine_instance_id": command["engine_instance_id"],
            "source_activation_id": source_activation_id,
            "request_id": command["request_id"],
            "request_fingerprint": fingerprint,
            "terminal_code": "activation_changed_before_ack_commit",
            "terminal_engine_instance_id": command["engine_instance_id"],
        }
    result = {
        "ok": state == "published",
        "committed": True,
        "retry_safe": False,
        "publication_state": state,
        "event_emitted": state == "published",
        "alarm_name": command["alarm_name"],
        "activation_id": command["activation_id"],
        "engine_instance_id": command["engine_instance_id"],
        "source_activation_id": source_activation_id,
        "request_id": command["request_id"],
        "commit_receipt": {
            "schema": "alarm_ack_commit_v1",
            "request_id": command["request_id"],
            "request_fingerprint": fingerprint,
            "alarm_name": command["alarm_name"],
            "activation_id": command["activation_id"],
            "engine_instance_id": command["engine_instance_id"],
            "source_activation_id": source_activation_id,
            "acknowledged_at": 1.0,
            "committed": True,
        },
    }
    if state == "pending":
        result.update(
            error_code="alarm_ack_publication_pending",
            error="alarm acknowledgement is committed; publication settlement is pending",
        )
    return result


def _alarm_ack_wire_result(command: dict, state: str) -> dict:
    handler_result = _alarm_ack_handler_result(command, state)
    assert "proto" not in handler_result
    return json.loads(ZMQCommandServer(handler=None)._encode_reply(handler_result))


def test_post_ack_forwards_alarm_v2_ack_command(auth_client) -> None:
    """REST binds one exact command to caller-owned retry and engine identity."""
    captured: dict = {}

    async def _fake(cmd: dict) -> dict:
        captured.update(cmd)
        return _alarm_ack_wire_result(cmd, "published")

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        resp = auth_client.post(
            "/api/v1/alarms/T1_high/ack",
            headers=_ack_headers(),
            json=_ack_payload(reason="  operator verified the active alarm  "),
        )

    assert resp.status_code == 200
    assert captured == {
        "cmd": "alarm_v2_ack",
        "alarm_name": "T1_high",
        "engine_instance_id": _ENGINE_A,
        "activation_id": "activation-1",
        "operator": _REST_IDENTITY,
        "reason": _ACK_REASON,
        "request_id": _ACK_REQUEST_ID,
    }


def test_post_ack_accepts_complete_handler_result_only_after_real_zmq_encoding(auth_client) -> None:
    handler_results: list[dict] = []

    async def _fake(cmd: dict) -> dict:
        handler_result = _alarm_ack_handler_result(cmd, "published")
        assert "proto" not in handler_result
        handler_results.append(handler_result)
        return json.loads(ZMQCommandServer(handler=None)._encode_reply(handler_result))

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        response = auth_client.post(
            "/api/v1/alarms/T1_high/ack",
            headers=_ack_headers("7" * 32),
            json=_ack_payload(),
        )

    assert len(handler_results) == 1
    assert response.status_code == 200
    assert response.json()["proto"] == PROTOCOL_VERSION
    assert response.json()["request_id"] == "7" * 32


def test_post_ack_rejects_complete_but_unframed_handler_result(auth_client) -> None:
    async def _fake(cmd: dict) -> dict:
        handler_result = _alarm_ack_handler_result(cmd, "published")
        assert "proto" not in handler_result
        return handler_result

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        response = auth_client.post(
            "/api/v1/alarms/T1_high/ack",
            headers=_ack_headers("8" * 32),
            json=_ack_payload(),
        )

    assert response.status_code == 502
    assert response.json() == {"detail": "incomplete alarm acknowledgement receipt"}


def test_post_ack_operator_is_server_set_not_spoofable(auth_client) -> None:
    """acknowledged_by (operator) is the REST identity, never client input;
    a client-supplied operator key is rejected (422)."""
    captured: dict = {}

    async def _fake(cmd: dict) -> dict:
        captured.update(cmd)
        return _alarm_ack_wire_result(cmd, "published")

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        ok = auth_client.post(
            "/api/v1/alarms/T1_high/ack",
            headers=_ack_headers("b" * 32),
            json=_ack_payload(),
        )
        spoof = auth_client.post(
            "/api/v1/alarms/T1_high/ack",
            headers=_ack_headers("c" * 32),
            json={
                **_ack_payload(),
                "operator": "victim",
            },
        )

    assert ok.status_code == 200
    assert captured["operator"] == _REST_IDENTITY
    assert spoof.status_code == 422


def test_post_ack_without_expected_activation_fails_closed(auth_client) -> None:
    with patch("cryodaq.web.server._async_engine_command", side_effect=AssertionError):
        response = auth_client.post(
            "/api/v1/alarms/T1_high/ack",
            headers=_ack_headers(),
            json={"engine_instance_id": _ENGINE_A, "reason": _ACK_REASON},
        )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "engine_instance_id",
    [
        pytest.param("engine-a", id="noncanonical-text"),
        pytest.param("A" * 32, id="uppercase"),
        pytest.param("g" * 32, id="nonhex"),
        pytest.param("a" * 31, id="short"),
        pytest.param("a" * 33, id="long"),
        pytest.param("", id="empty"),
        pytest.param(None, id="null"),
        pytest.param(True, id="bool"),
    ],
)
def test_post_ack_rejects_noncanonical_engine_identity_without_forwarding(
    auth_client,
    engine_instance_id: object,
) -> None:
    with patch("cryodaq.web.server._async_engine_command", side_effect=AssertionError):
        response = auth_client.post(
            "/api/v1/alarms/T1_high/ack",
            headers=_ack_headers(),
            json=_ack_payload(engine_instance_id=engine_instance_id),
        )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "reason",
    [
        pytest.param("", id="empty"),
        pytest.param("   ", id="whitespace"),
        pytest.param("line one\nline two", id="control"),
        pytest.param("operator\u202eoverride", id="bidi-format"),
        pytest.param("x" * 257, id="over-limit"),
    ],
)
def test_post_ack_rejects_nonprintable_or_empty_reason_without_forwarding(
    auth_client,
    reason: str,
) -> None:
    with patch("cryodaq.web.server._async_engine_command", side_effect=AssertionError):
        response = auth_client.post(
            "/api/v1/alarms/T1_high/ack",
            headers=_ack_headers(),
            json=_ack_payload(reason=reason),
        )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({}, id="missing"),
        pytest.param({"Idempotency-Key": "a" * 31}, id="short"),
        pytest.param({"Idempotency-Key": "a" * 33}, id="long"),
        pytest.param({"Idempotency-Key": "A" * 32}, id="uppercase"),
        pytest.param({"Idempotency-Key": "g" * 32}, id="nonhex"),
    ],
)
def test_post_ack_rejects_noncanonical_idempotency_key_without_forwarding(
    auth_client,
    headers: dict[str, str],
) -> None:
    with patch("cryodaq.web.server._async_engine_command", side_effect=AssertionError):
        response = auth_client.post(
            "/api/v1/alarms/T1_high/ack",
            headers={**_AUTH, **headers},
            json=_ack_payload(),
        )
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("state", "expected_status"),
    [("published", 200), ("pending", 503), ("aborted", 409)],
)
def test_post_ack_requires_complete_bound_terminal_or_pending_reply(
    auth_client,
    state: str,
    expected_status: int,
) -> None:
    returned: dict = {}

    async def _fake(cmd: dict) -> dict:
        returned.update(_alarm_ack_wire_result(cmd, state))
        return returned

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        response = auth_client.post(
            "/api/v1/alarms/T1_high/ack",
            headers=_ack_headers("d" * 32),
            json=_ack_payload(),
        )

    assert response.status_code == expected_status
    if state == "pending":
        assert response.json() == {
            "detail": "alarm acknowledgement committed; retry the same Idempotency-Key to settle publication"
        }
    else:
        assert response.json() == returned


def test_post_ack_aborted_returns_409_with_preserved_receipt(auth_client) -> None:
    """A terminally-aborted ack was never applied (ok=False, committed=False).

    Returning 200 would let a REST client treat the operation as successful
    and stop retrying/escalating while the alarm stays unacknowledged. The
    exact abort receipt is preserved verbatim in the 409 body so a typed
    client can still read why it aborted. 409 matches the operator-log
    rejection convention (rest_api.py post_log); 503 is reserved for the
    committed-but-pending retry case.
    """
    returned: dict = {}

    async def _fake(cmd: dict) -> dict:
        returned.update(_alarm_ack_wire_result(cmd, "aborted"))
        return returned

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        response = auth_client.post(
            "/api/v1/alarms/T1_high/ack",
            headers=_ack_headers("d" * 32),
            json=_ack_payload(),
        )

    assert response.status_code == 409
    assert response.json() == returned
    assert response.json()["ok"] is False
    assert response.json()["publication_state"] == "aborted"


@pytest.mark.parametrize("state", ["published", "pending", "aborted"])
@pytest.mark.parametrize("corruption", ["wrong_request", "missing_proto"])
def test_post_ack_rejects_incomplete_or_misbound_settlement(
    auth_client,
    state: str,
    corruption: str,
) -> None:
    async def _fake(cmd: dict) -> dict:
        result = _alarm_ack_wire_result(cmd, state)
        if corruption == "wrong_request":
            result["request_id"] = "f" * 32
        else:
            result.pop("proto")
        return result

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        response = auth_client.post(
            "/api/v1/alarms/T1_high/ack",
            headers=_ack_headers("e" * 32),
            json=_ack_payload(),
        )

    assert response.status_code == 502


def test_delayed_rest_ack_never_substitutes_latest_activation(auth_client) -> None:
    active = {"activation_id": "activation-1", "acknowledged": False}

    async def _fake(cmd: dict) -> dict:
        if cmd == {"cmd": "alarm_v2_status"}:
            return {
                "ok": True,
                "engine_instance_id": _ENGINE_A,
                "snapshot_revision": 1,
                "active": {"T1_high": dict(active)},
            }
        assert cmd["cmd"] == "alarm_v2_ack"
        if cmd["activation_id"] == active["activation_id"]:
            active["acknowledged"] = True
        return _alarm_ack_wire_result(cmd, "aborted")

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        snapshot_response = auth_client.get("/api/v1/alarms")
        snapshot = snapshot_response.json()

        # The first activation clears and the same named alarm fires again
        # before the operator submits the acknowledgement.
        active = {"activation_id": "activation-2", "acknowledged": False}
        response = auth_client.post(
            "/api/v1/alarms/T1_high/ack",
            headers=_ack_headers("f" * 32),
            json={
                "engine_instance_id": snapshot["engine_instance_id"],
                "activation_id": snapshot["active"]["T1_high"]["activation_id"],
                "reason": _ACK_REASON,
            },
        )

    assert snapshot_response.status_code == 200
    assert snapshot["snapshot_revision"] == 1
    assert response.status_code == 409
    assert response.json()["ok"] is False
    assert response.json()["publication_state"] == "aborted"
    assert response.json()["error_code"] == "alarm_ack_aborted"
    assert active["activation_id"] == "activation-2"
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
    with patch("cryodaq.web.server._async_engine_command", side_effect=AssertionError):
        response = auth_client.post(
            "/api/v1/log",
            content="{",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer wrong",
                "Idempotency-Key": "a" * 32,
            },
        )

    assert response.status_code == 401


def test_valid_auth_then_invalid_json_is_422(auth_client) -> None:
    """With valid auth the parser DOES run and rejects malformed JSON (422) —
    proving auth precedes, not replaces, body validation."""
    with patch("cryodaq.web.server._async_engine_command", side_effect=AssertionError):
        resp = auth_client.post(
            "/api/v1/log",
            content="{",
            headers={**_log_headers(), "Content-Type": "application/json"},
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
            headers=_log_headers(),
            json={"message": "ok", "tags": [reserved]},
        )
    assert resp.status_code == 422
    assert canonical in resp.json()["detail"]


def test_post_log_freeform_tags_pass_through(auth_client) -> None:
    """Genuinely free-form tags are forwarded verbatim to the engine command."""
    captured: dict = {}

    async def _fake(cmd: dict) -> dict:
        captured.update(cmd)
        return _published_log_result(cmd)

    with patch("cryodaq.web.server._async_engine_command", side_effect=_fake):
        resp = auth_client.post(
            "/api/v1/log",
            headers=_log_headers(),
            json={"message": "ok", "tags": ["насос", "проверка"]},
        )
    assert resp.status_code == 200
    assert captured["tags"] == ["насос", "проверка"]
