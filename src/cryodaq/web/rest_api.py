"""REST facade for CryoDAQ (``/api/v1``) with Swagger docs.

A thin layer over the SAME cache/command path the dashboard uses
(``server._state.last_readings``, ``server._query_history``, existing
commands). Read endpoints are open on loopback and unauthenticated by design.
There are exactly TWO write endpoints — both authenticated and allowlisted:
operator-log append (``POST /log``) and alarm acknowledgement
(``POST /alarms/{id}/ack``). The write token lives in local config
(``config/web.local.yaml`` → ``web.api_token``); no other route mutates
engine state.

Security payload (do not remove):
- **Field whitelist.** Every response goes through a Pydantic ``response_model``
  that declares ONLY safe fields. The model *is* the redaction: fields it does
  not declare (operator, sample, notes, config_snapshot, artifact paths,
  operator-log authors) are dropped before serialization.
- **Auth before body parsing.** ``WriteAuthMiddleware`` runs the token check on
  every mutating ``/api/v1`` request *before* routing — so an unauthenticated
  client can never reach the JSON body parser (FastAPI otherwise resolves the
  body model in the same dependency pass as the route-level guard, 422-ing
  malformed JSON before auth runs). The route dependency stays as
  defense-in-depth.
- **Request-size limit.** ``BodySizeLimitMiddleware`` rejects oversize bodies
  with 413 before the request is routed — i.e. before any engine call.

Loopback-only for reads (SSH tunnel for LAN); see the ``server`` module
docstring.
"""

from __future__ import annotations

import hmac
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request, Security
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.base import BaseHTTPMiddleware

from cryodaq.notifications._secrets import SecretStr
from cryodaq.paths import get_config_dir

# Imported as a module (not names) so handlers read live state and the patched
# _async_engine_command used by tests, and to keep the import non-circular:
# server imports this module inside create_app().
from cryodaq.web import server

# Max request body for the unauthenticated facade. All endpoints are GET and
# take no body; a large body is only ever abuse. 1 MiB is generous headroom.
MAX_BODY_BYTES = 1 * 1024 * 1024

router = APIRouter(prefix="/api/v1", tags=["read-only"])


# ---------------------------------------------------------------------------
# Write-auth token (P4-1) — fail-closed Bearer check for FUTURE write routes
#
# The token lives ONLY in config/web.local.yaml (gitignored, never the tracked
# yaml) under web.api_token, mirroring the *.local.yaml override pattern the
# engine uses and the SecretStr wrapping the Telegram token uses. GET routes
# never depend on this; reads stay open on loopback.
# ---------------------------------------------------------------------------


def _load_api_token() -> SecretStr | None:
    """Return the configured write-API token, or None if unset/unreadable.

    None ⇒ fail closed (403). Read fresh per call: write traffic is
    operator-rate, so re-reading the small local yaml is cheap and lets the
    operator drop in a token without restarting the web process.
    """
    path = get_config_dir() / "web.local.yaml"
    if not path.exists():
        return None
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        web = raw.get("web") or {}
        token = web.get("api_token")
    except Exception:
        return None  # malformed config ⇒ fail closed
    if not token:
        return None
    return SecretStr(str(token))


# HTTPBearer (auto_error=False) so a missing/malformed header returns None and
# we own the 401 — AND so the scheme shows up in the OpenAPI/Swagger security
# section (the lock icon) on every route that Depends on require_write_token.
_bearer_scheme = HTTPBearer(
    auto_error=False,
    description="web.api_token из config/web.local.yaml",
)


# Auth error bodies, keyed by the status _check_bearer returns. Carry no
# secret material.
_AUTH_ERROR_DETAIL = {
    403: "API token не настроен",
    401: "Неверный API token",
}


def _check_bearer(auth_header: str | None) -> int | None:
    """Shared bearer check for both the middleware and the route dependency.

    Returns the HTTP status to reject with, or None if the request is allowed:
    - No token configured  ⇒ 403 (fail-closed default).
    - Missing/wrong bearer ⇒ 401 (constant-time compare via hmac.compare_digest).

    ``auth_header`` is the raw ``Authorization`` header value (or None). Never
    logs or echoes the token; the SecretStr wrapper keeps it out of
    reprs/tracebacks.
    """
    token = _load_api_token()
    if token is None:
        return 403
    presented = ""
    if auth_header:
        scheme, _, param = auth_header.partition(" ")
        if scheme.lower() == "bearer":
            presented = param
    # Compare bytes: str compare_digest raises TypeError on non-ASCII input,
    # which an attacker could send in the header to force a 500.
    if not hmac.compare_digest(presented.encode(), token.get_secret_value().encode()):
        return 401
    return None


async def require_write_token(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
) -> None:
    """FastAPI dependency guarding write routes (defense-in-depth behind
    ``WriteAuthMiddleware`` — the middleware runs the same check before the
    body parser). Kept as a dependency so the bearer scheme shows in OpenAPI.
    """
    # Reconstruct the header form for the shared check. HTTPBearer already
    # parsed/validated it; this just re-normalizes for _check_bearer.
    header = f"{credentials.scheme} {credentials.credentials}" if credentials else None
    status = _check_bearer(header)
    if status is not None:
        raise HTTPException(status_code=status, detail=_AUTH_ERROR_DETAIL[status])


# ---------------------------------------------------------------------------
# Response models — whitelisted fields only (the model IS the redaction)
# ---------------------------------------------------------------------------


class ReadingOut(BaseModel):
    timestamp: str | None = None
    channel: str | None = None
    value: float | None = None
    unit: str | None = None
    status: str | None = None


class ActiveExperimentOut(BaseModel):
    """Whitelisted experiment fields. Omits operator, sample, notes,
    config_snapshot, custom_fields, artifact_dir, metadata_path."""

    experiment_id: str | None = None
    name: str | None = None
    title: str | None = None
    template_id: str | None = None
    cryostat: str | None = None
    status: str | None = None
    start_time: str | None = None
    end_time: str | None = None


class ExperimentOut(BaseModel):
    active_experiment: ActiveExperimentOut | None = None
    current_phase: str | None = None
    phase_started_at: float | None = None


class LogEntryOut(BaseModel):
    """Whitelisted operator-log fields. Omits ``author`` (who wrote it)."""

    id: int | None = None
    timestamp: str | None = None
    experiment_id: str | None = None
    source: str | None = None
    message: str | None = None
    tags: list[str] = []


# ---------------------------------------------------------------------------
# Request-size-limit middleware (413 before routing / any engine call)
# ---------------------------------------------------------------------------


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests whose body exceeds ``MAX_BODY_BYTES`` with 413.

    Runs before routing, so no handler (and no engine command) executes for an
    oversize request. ponytail: checks the Content-Length header only; a
    chunked upload without that header would slip past — add streaming
    enforcement if such clients ever appear (they won't on a GET-only facade).
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        cl = request.headers.get("content-length")
        if cl is not None:
            try:
                if int(cl) > MAX_BODY_BYTES:
                    return JSONResponse({"detail": "Request body too large"}, status_code=413)
            except ValueError:
                return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
        return await call_next(request)


_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class WriteAuthMiddleware(BaseHTTPMiddleware):
    """Run the write-token check BEFORE routing/body parsing.

    FastAPI resolves a route's body model in the same dependency pass as its
    ``require_write_token`` dependency, so malformed JSON on a write route
    would 422 *before* the token check — leaving an unauthenticated parser
    path. This middleware closes that: any mutating request under ``/api/v1``
    is auth-checked here, before the router runs. The route-level dependency
    stays as defense-in-depth (and to surface the bearer scheme in OpenAPI).
    GET/HEAD/OPTIONS and non-``/api/v1`` paths are untouched.
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if request.method not in _SAFE_METHODS and request.url.path.startswith("/api/v1"):
            status = _check_bearer(request.headers.get("authorization"))
            if status is not None:
                return JSONResponse({"detail": _AUTH_ERROR_DETAIL[status]}, status_code=status)
        return await call_next(request)


def _readings_with_unit(unit: str) -> list[dict[str, Any]]:
    return [r for r in server._state.last_readings.values() if r.get("unit") == unit]


_REDACT_KEYS = frozenset({"acknowledged_by"})


def _redact(obj: Any, keys: frozenset[str] = _REDACT_KEYS) -> Any:
    """Recursively strip operator-identity keys from a plain dict/list payload.

    ``/state`` and ``/alarms`` return engine dicts verbatim (no Pydantic model),
    so active alarms would otherwise leak ``acknowledged_by`` — the operator who
    acknowledged an alarm — over the unauthenticated facade.
    """
    if isinstance(obj, dict):
        return {k: _redact(v, keys) for k, v in obj.items() if k not in keys}
    if isinstance(obj, list):
        return [_redact(v, keys) for v in obj]
    return obj


# ---------------------------------------------------------------------------
# Endpoints — all GET, all read-only, all field-whitelisted
# ---------------------------------------------------------------------------


@router.get("/state")
async def get_state() -> dict[str, Any]:
    """System status snapshot (uptime, instruments, safety, alarm counts)."""
    return _redact(server._state.status_json())


@router.get("/readings", response_model=list[ReadingOut])
async def get_readings() -> list[dict[str, Any]]:
    """Latest reading per channel from the live cache."""
    return list(server._state.last_readings.values())


@router.get("/temperatures", response_model=list[ReadingOut])
async def get_temperatures() -> list[dict[str, Any]]:
    """Latest temperature (K-unit) readings."""
    return _readings_with_unit("K")


@router.get("/pressure", response_model=list[ReadingOut])
async def get_pressure() -> list[dict[str, Any]]:
    """Latest pressure (mbar-unit) readings."""
    return _readings_with_unit("mbar")


@router.get("/history")
async def get_history(minutes: int = 60) -> dict[str, Any]:
    """Historical readings from SQLite over the last N minutes (clamped)."""
    channels = await server.asyncio.to_thread(server._query_history, minutes)
    return {"channels": channels}


@router.get("/alarms")
async def get_alarms() -> dict[str, Any]:
    """Currently active alarms (from the engine)."""
    try:
        result = await server._async_engine_command({"cmd": "alarm_v2_status"})
        if result.get("ok"):
            return {
                "ok": True,
                "engine_instance_id": result.get("engine_instance_id"),
                "snapshot_revision": result.get("snapshot_revision"),
                "active": _redact(result.get("active", {})),
            }
    except Exception:
        server.logger.warning("api/v1 alarms fetch failed")
    return {"ok": False, "active": {}}


@router.get("/experiment", response_model=ExperimentOut)
async def get_experiment() -> dict[str, Any]:
    """Active experiment status — sensitive fields redacted by the model."""
    try:
        result = await server._async_engine_command({"cmd": "experiment_status"})
        if result.get("ok"):
            return result
    except Exception:
        server.logger.warning("api/v1 experiment fetch failed")
    return {"active_experiment": None, "current_phase": None, "phase_started_at": None}


@router.get("/log", response_model=list[LogEntryOut])
async def get_log(limit: int = 10) -> list[dict[str, Any]]:
    """Recent operator-log entries — authors redacted by the model."""
    limit = max(1, min(limit, server._LOG_MAX_LIMIT))
    try:
        result = await server._async_engine_command({"cmd": "log_get", "limit": limit})
        if result.get("ok"):
            return result.get("entries", [])
    except Exception:
        server.logger.warning("api/v1 log fetch failed")
    return []


# ---------------------------------------------------------------------------
# Write endpoints (P4-2) — each forwards ONE existing engine command behind
# require_write_token. No generic command proxy (that would be an open
# surface); no new engine logic; the operator-identity field is server-set,
# never client-supplied. Source control / setpoints / calibration /
# experiment lifecycle / config mutation are NOT reachable from here.
# ---------------------------------------------------------------------------

# Server-set identity for every REST-originated write. A client cannot supply
# it: the request models forbid the identity keys (extra="forbid" → 422), and
# the handlers overwrite them unconditionally. No impersonation.
_REST_IDENTITY = "REST API"

# Operator-log tags that downstream consumers treat as semantic SYSTEM
# categories, not free-form labels. A REST caller must not forge them
# (audit/event-stream impersonation). Sources (grep the literals):
#   - agents/assistant/live/context_builder.py — alarm / phase / phase_transition
#     / experiment / calibration / ai / auto classification buckets
#   - core/event_logger.py — auto + event_type tags on every logged event
#   - engine.py::_safety_fault_log_callback — safety_fault
#   - agents/assistant/live/output_router.py — ai
_RESERVED_TAGS = frozenset(
    {
        "ai",
        "auto",
        "alarm",
        "alarm_ack",
        "safety_fault",
        "phase",
        "phase_transition",
        "experiment",
        "calibration",
    }
)


class LogAppendIn(BaseModel):
    """Operator-log append body. ``author``/``source`` are NOT accepted —
    extra="forbid" makes any such key a 422 (no author impersonation)."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1)
    tags: list[str] | None = None


class AlarmAckIn(BaseModel):
    """Alarm-ack body. ``operator`` (→ acknowledged_by) is NOT accepted —
    extra="forbid" makes it a 422. Exact engine/activation identity is required
    so a delayed request cannot acknowledge a later recurrence."""

    model_config = ConfigDict(extra="forbid")

    engine_instance_id: str = Field(min_length=1, max_length=256)
    activation_id: str = Field(min_length=1, max_length=256)
    reason: str = Field(default="", max_length=256)


async def _forward_write(cmd: dict[str, Any]) -> dict[str, Any]:
    """Forward one write command through the same path the reads use.

    On a transport/engine failure surface 502 (not a silent degrade — a write
    that did not land must not look like success)."""
    try:
        return await server._async_engine_command(cmd)
    except Exception as exc:  # noqa: BLE001 — map any transport failure to 502
        server.logger.warning("api/v1 write %s failed", cmd.get("cmd"))
        raise HTTPException(status_code=502, detail="Ошибка движка") from exc


@router.post("/log", dependencies=[Depends(require_write_token)])
async def post_log(payload: LogAppendIn) -> dict[str, Any]:
    """Добавить запись в операторский журнал (author = «REST API»)."""
    cmd: dict[str, Any] = {
        "cmd": "log_entry",
        "message": payload.message,
        "author": _REST_IDENTITY,
        "source": "rest",
    }
    if payload.tags is not None:
        # Reject reserved system tags (impersonation guard) — genuinely
        # free-form tags pass through unchanged. Compare stripped, matching
        # how the engine normalizes tags (operator_log.normalize_operator_log_tags).
        reserved = _RESERVED_TAGS.intersection(t.strip() for t in payload.tags)
        if reserved:
            raise HTTPException(
                status_code=422,
                detail=f"Зарезервированные системные теги недопустимы: {', '.join(sorted(reserved))}",
            )
        cmd["tags"] = payload.tags
    return await _forward_write(cmd)


@router.post("/alarms/{alarm_id}/ack", dependencies=[Depends(require_write_token)])
async def post_alarm_ack(alarm_id: str, payload: AlarmAckIn) -> dict[str, Any]:
    """Квитировать аларм (acknowledged_by = «REST API»)."""
    return await _forward_write(
        {
            "cmd": "alarm_v2_ack",
            "alarm_name": alarm_id,
            "engine_instance_id": payload.engine_instance_id,
            "activation_id": payload.activation_id,
            "operator": _REST_IDENTITY,
            "reason": payload.reason,
        }
    )
