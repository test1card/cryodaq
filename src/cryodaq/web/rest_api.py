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
import math
from datetime import UTC, datetime
from typing import Annotated, Any

import yaml
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Security
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.middleware.base import BaseHTTPMiddleware

from cryodaq.core.alarm_ack_codec import (
    is_canonical_engine_instance_id,
    validate_alarm_ack_wire_result,
)
from cryodaq.core.command_authority import (
    ENGINE_MUTATION_CAPABILITY,
    MUTATION_PROTOCOL_MAJOR,
    MUTATION_RECEIPT_SCHEMA,
)
from cryodaq.core.zmq_bridge import PROTOCOL_VERSION
from cryodaq.notifications._secrets import SecretStr
from cryodaq.paths import get_config_dir

# Imported as a module (not names) so handlers read live state and the patched
# _async_engine_command used by tests, and to keep the import non-circular:
# server imports this module inside create_app().
from cryodaq.web import server

# Maximum request body for the read-only facade and its two strict-token write
# routes. Writes require an explicit finite length; large read bodies are abuse.
# 1 MiB is generous headroom for the bounded write schemas.
MAX_BODY_BYTES = 1 * 1024 * 1024
MAX_LOG_MESSAGE_CHARS = 4096
MAX_LOG_TAGS = 16
MAX_LOG_TAG_CHARS = 64

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

    @field_validator("value", mode="before")
    @classmethod
    def mask_non_finite_value(cls, value: Any) -> Any:
        """Never serialize NaN/Infinity as if they were measurements."""
        if value is None:
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return value  # let normal Pydantic validation reject malformed data
        return value if math.isfinite(numeric) else None


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
    oversize request. Authenticated write routes deliberately require a finite
    Content-Length and reject transfer encodings rather than buffering an
    unbounded stream in the web process.
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        cl = request.headers.get("content-length")
        bounded_write = request.method not in _SAFE_METHODS and request.url.path.startswith("/api/v1")
        if bounded_write and (cl is None or request.headers.get("transfer-encoding") is not None):
            return JSONResponse({"detail": "Content-Length required"}, status_code=411)
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


def _unavailable_readings_response() -> JSONResponse | None:
    """Return the canonical unavailable envelope when the cache lost authority."""
    status = server._state.status_json()
    if status["available"]:
        return None
    return JSONResponse(
        {key: status[key] for key in ("available", "stale", "reason")},
        status_code=503,
    )


_REDACT_KEYS = frozenset({"acknowledged_by"})


def redact_public_payload(obj: Any, keys: frozenset[str] = _REDACT_KEYS) -> Any:
    """Recursively strip operator-identity keys from a plain dict/list payload.

    ``/state`` and ``/alarms`` return engine dicts verbatim (no Pydantic model),
    so active alarms would otherwise leak ``acknowledged_by`` — the operator who
    acknowledged an alarm — over the unauthenticated facade.
    """
    if isinstance(obj, dict):
        return {k: redact_public_payload(v, keys) for k, v in obj.items() if k not in keys}
    if isinstance(obj, list):
        return [redact_public_payload(v, keys) for v in obj]
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


def project_public_experiment(obj: Any) -> dict[str, Any]:
    """Return the canonical unauthenticated experiment projection.

    Both the versioned facade and the legacy dashboard route must expose the
    same whitelisted fields. Keeping the projection here prevents either read
    surface from silently re-introducing operator or configuration metadata.
    """
    return ExperimentOut.model_validate(obj).model_dump(mode="json")


def project_public_log_entries(obj: Any) -> list[dict[str, Any]]:
    """Return the canonical author-free projection for every public log route."""
    if not isinstance(obj, list):
        return []
    projected: list[dict[str, Any]] = []
    for entry in obj:
        try:
            projected.append(LogEntryOut.model_validate(entry).model_dump(mode="json"))
        except Exception:  # noqa: BLE001 — malformed engine rows are omitted, never exposed
            server.logger.warning("Ignoring malformed public operator-log entry")
    return projected


# ---------------------------------------------------------------------------
# Endpoints — all GET, all read-only, all field-whitelisted
# ---------------------------------------------------------------------------


@router.get("/state")
async def get_state() -> dict[str, Any]:
    """System status snapshot (uptime, instruments, safety, alarm counts)."""
    return redact_public_payload(server._state.status_json())


@router.get("/readings", response_model=list[ReadingOut])
async def get_readings() -> list[dict[str, Any]] | JSONResponse:
    """Latest reading per channel from the live cache."""
    if unavailable := _unavailable_readings_response():
        return unavailable
    return list(server._state.last_readings.values())


@router.get("/temperatures", response_model=list[ReadingOut])
async def get_temperatures() -> list[dict[str, Any]] | JSONResponse:
    """Latest temperature (K-unit) readings."""
    if unavailable := _unavailable_readings_response():
        return unavailable
    return _readings_with_unit("K")


@router.get("/pressure", response_model=list[ReadingOut])
async def get_pressure() -> list[dict[str, Any]] | JSONResponse:
    """Latest pressure (mbar-unit) readings."""
    if unavailable := _unavailable_readings_response():
        return unavailable
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
                "active": redact_public_payload(result.get("active", {})),
            }
    except Exception:
        server.logger.warning("api/v1 alarms fetch failed")
    return {"ok": False, "active": {}}


_UNAVAILABLE_EXPERIMENT_ENVELOPE = {
    "available": False,
    "stale": True,
    "reason": "experiment status unavailable",
}


@router.get("/experiment", response_model=ExperimentOut)
async def get_experiment() -> dict[str, Any] | JSONResponse:
    """Active experiment status — sensitive fields redacted by the model.

    A genuine "no active experiment" (engine reachable, ``ok`` true) is
    returned as 200 with ``active_experiment=null``. Engine unavailability
    (exception or non-``ok`` reply) is returned as 503 with the
    ``{available:false, stale:true, reason}`` envelope below, which does NOT
    share a shape with the authoritative empty above — a client can tell them
    apart. Returning 200 with ``active_experiment=null`` on an unreachable
    engine would let a client treat a dropped engine as "no experiment".
    """
    try:
        result = await server._async_engine_command({"cmd": "experiment_status"})
        if result.get("ok"):
            return result
        server.logger.warning("api/v1 experiment fetch non-ok")
    except Exception:
        server.logger.warning("api/v1 experiment fetch failed")
    return JSONResponse(_UNAVAILABLE_EXPERIMENT_ENVELOPE, status_code=503)


_UNAVAILABLE_LOG_ENVELOPE = {
    "available": False,
    "stale": True,
    "reason": "operator log unavailable",
}


@router.get("/log", response_model=list[LogEntryOut])
async def get_log(limit: int = 10) -> list[dict[str, Any]] | JSONResponse:
    """Recent operator-log entries — authors redacted by the model.

    A genuine empty log (engine reachable, ``ok`` true, no entries) is 200
    with ``[]``. Engine unavailability (exception or non-``ok`` reply) is 503
    with the ``{available:false, stale:true, reason}`` envelope below — a
    distinct shape from the authoritative empty list, so a client never reads
    "no entries" when the engine is in fact unreachable.
    """
    limit = max(1, min(limit, server._LOG_MAX_LIMIT))
    try:
        result = await server._async_engine_command({"cmd": "log_get", "limit": limit})
        if result.get("ok"):
            return project_public_log_entries(result.get("entries", []))
        server.logger.warning("api/v1 log fetch non-ok")
    except Exception:
        server.logger.warning("api/v1 log fetch failed")
    return JSONResponse(_UNAVAILABLE_LOG_ENVELOPE, status_code=503)


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
_OPERATOR_LOG_SUCCESS_KEYS = frozenset(
    {"ok", "committed", "retry_safe", "publication_state", "entry", "commit_receipt", "proto"}
)
_OPERATOR_LOG_PENDING_KEYS = _OPERATOR_LOG_SUCCESS_KEYS | {"error_code", "error"}
_OPERATOR_LOG_PENDING_ERROR_CODE = "committed_reconciliation_failed"
_OPERATOR_LOG_PENDING_ERROR = "operator log committed, but required publication remains pending"
_OPERATOR_LOG_ENTRY_KEYS = frozenset({"id", "timestamp", "experiment_id", "author", "source", "message", "tags"})
_OPERATOR_LOG_RECEIPT_KEYS = frozenset({"schema", "request_id", "entry_id", "experiment_id", "committed"})
_SQLITE_MAX_ROWID = 2**63 - 1
_UNKNOWN_SETTLEMENT_EVIDENCE_KEYS = frozenset(
    {
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
)
_UNKNOWN_SETTLEMENT_SAFE_ERROR_CODES = frozenset(
    {
        "committed_reconciliation_failed",
        "operator_log_admission_invalid",
        "operator_log_commit_outcome_unknown",
        "operator_log_persistence_failed",
        "operator_log_state_invalid",
    }
)
_UNKNOWN_SETTLEMENT_SAFE_SCHEMAS = frozenset({"operator_log_commit_v1", "mutation_compatibility_v1"})
_UNKNOWN_SETTLEMENT_SENSITIVE_KEY_PARTS = frozenset(
    {
        "artifact",
        "author",
        "capability",
        "config",
        "credential",
        "message",
        "note",
        "operator",
        "password",
        "path",
        "sample",
        "secret",
        "snapshot",
        "token",
    }
)
_UNKNOWN_SETTLEMENT_MAX_DEPTH = 4
_UNKNOWN_SETTLEMENT_MAX_ITEMS = 16
_UNKNOWN_SETTLEMENT_MAX_STRING_CHARS = 128
_UNKNOWN_SETTLEMENT_OMIT = object()
_OPERATOR_LOG_ENGINE_REJECTION_KEYS = frozenset({"ok", "committed", "error_code", "error", "retry_safe", "proto"})
_OPERATOR_LOG_ENGINE_REJECTION_WITH_REQUEST_ID_KEYS = _OPERATOR_LOG_ENGINE_REJECTION_KEYS | {"request_id"}
_OPERATOR_LOG_TRANSPORT_REJECTION_KEYS = frozenset(
    {"ok", "error_code", "error", "delivery_state", "commit_state", "retry_safe", "proto"}
)
_OPERATOR_LOG_MUTATION_PROTOCOL_REJECTION_KEYS = _OPERATOR_LOG_TRANSPORT_REJECTION_KEYS | {"compatibility_receipt"}
_OPERATOR_LOG_WEB_MUTATION_DISCOVERY_REJECTION_KEYS = frozenset(
    {
        "ok",
        "error_code",
        "error",
        "delivery_state",
        "commit_state",
        "retry_safe",
        "compatibility_receipt",
    }
)
_MUTATION_COMPATIBILITY_REJECTION_RECEIPT_KEYS = frozenset(
    {"schema", "accepted", "server_protocol_major", "required_capability"}
)
_OPERATOR_LOG_ENGINE_REJECTIONS = frozenset(
    {
        ("engine_shutting_down", "operator log submissions are frozen for shutdown", True),
        (
            "operator_log_request_id_invalid",
            "request_id must be exactly 32 lowercase hexadecimal characters",
            True,
        ),
        ("operator_log_busy", "the bounded operator log commit lane is full", True),
        ("idempotency_key_conflict", "request_id was already committed with different content", False),
        ("idempotency_key_conflict", "request_id is already in flight with different content", False),
        ("idempotency_key_conflict", "request_id is reconciling different committed content", False),
    }
)
_OPERATOR_LOG_ENGINE_REJECTIONS_WITH_REQUEST_ID = frozenset(
    {
        ("operator_log_admission_invalid", "Operator-log command or publication fields are invalid.", True),
        ("stale_experiment_command", "Experiment identity changed before the operator log could commit.", False),
        ("operator_log_busy", "another durable experiment mutation is still authoritative", True),
        ("idempotency_key_conflict", "request_id was already committed with different content", False),
    }
)
_OPERATOR_LOG_TRANSPORT_REJECTIONS = frozenset(
    {
        ("command_request_invalid", "Command request is invalid.", True),
        ("command_endpoint_action_rejected", "Command is not admitted by this endpoint.", False),
        (
            "command_authority_quarantined",
            "A prior command outcome is still uncertain; mutation is quarantined.",
            False,
        ),
    }
)
_OPERATOR_LOG_DISPATCHED_TRANSPORT_REJECTIONS = frozenset(
    {
        (
            "engine_shutdown_latched",
            "engine shutdown owns mutation admission; later state changes are refused",
            False,
        ),
    }
)

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
        "system",
        "machine",
    }
)


class LogAppendIn(BaseModel):
    """Operator-log append body. ``author``/``source`` are NOT accepted —
    extra="forbid" makes any such key a 422 (no author impersonation)."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=MAX_LOG_MESSAGE_CHARS)
    experiment_id: str | None = Field(default=None, min_length=1, max_length=256)
    tags: list[Annotated[str, Field(min_length=1, max_length=MAX_LOG_TAG_CHARS)]] | None = Field(
        default=None, max_length=MAX_LOG_TAGS
    )

    @field_validator("message")
    @classmethod
    def _normalize_message(cls, value: str) -> str:
        message = value.strip()
        if not message:
            raise ValueError("message must contain non-whitespace text")
        return message

    @field_validator("experiment_id")
    @classmethod
    def _normalize_experiment_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        experiment_id = value.strip()
        if not experiment_id:
            raise ValueError("experiment_id must contain non-whitespace text")
        return experiment_id

    @field_validator("tags")
    @classmethod
    def _normalize_tags(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        # Match SQLiteWriter publication admission exactly: whitespace-only
        # tags disappear and every retained tag is stripped before identity
        # fingerprinting, persistence, and receipt reconciliation.
        return [tag for item in value if (tag := item.strip())]


class AlarmAckIn(BaseModel):
    """Alarm-ack body. ``operator`` (→ acknowledged_by) is NOT accepted —
    extra="forbid" makes it a 422. Exact engine/activation identity is required
    so a delayed request cannot acknowledge a later recurrence."""

    model_config = ConfigDict(extra="forbid")

    engine_instance_id: str = Field(min_length=1, max_length=256)
    activation_id: str = Field(min_length=1, max_length=256)
    reason: str = Field(min_length=1, max_length=256)

    @field_validator("engine_instance_id")
    @classmethod
    def _validate_engine_instance_id(cls, value: str) -> str:
        if not is_canonical_engine_instance_id(value):
            raise ValueError("engine_instance_id must be exactly 32 lowercase hexadecimal characters")
        return value

    @field_validator("activation_id")
    @classmethod
    def _validate_activation_id(cls, value: str) -> str:
        if not value.isprintable():
            raise ValueError("activation_id must contain printable text")
        return value

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, value: str) -> str:
        reason = value.strip()
        if not reason or not reason.isprintable():
            raise ValueError("reason must contain printable non-whitespace text")
        return reason


async def _forward_write(cmd: dict[str, Any]) -> dict[str, Any]:
    """Forward one write command through the same path the reads use.

    On a transport/engine failure surface 502 (not a silent degrade — a write
    that did not land must not look like success)."""
    try:
        return await server._async_engine_command(cmd)
    except Exception as exc:  # noqa: BLE001 — map any transport failure to 502
        server.logger.warning("api/v1 write %s failed", cmd.get("cmd"))
        raise HTTPException(status_code=502, detail="Ошибка движка") from exc


def _is_sqlite_rowid(value: object) -> bool:
    """Accept one exact positive SQLite row-id value."""

    return type(value) is int and 1 <= value <= _SQLITE_MAX_ROWID


def _is_exact_mutation_compatibility_rejection_receipt(receipt: object) -> bool:
    """Accept only the complete exact compatibility rejection receipt."""

    return (
        type(receipt) is dict
        and set(receipt) == _MUTATION_COMPATIBILITY_REJECTION_RECEIPT_KEYS
        and type(receipt.get("schema")) is str
        and receipt["schema"] == MUTATION_RECEIPT_SCHEMA
        and receipt.get("accepted") is False
        and type(receipt.get("server_protocol_major")) is int
        and receipt["server_protocol_major"] == MUTATION_PROTOCOL_MAJOR
        and type(receipt.get("required_capability")) is str
        and receipt["required_capability"] == ENGINE_MUTATION_CAPABILITY
    )


def _bounded_json_safe_projection(
    value: object,
    *,
    depth: int = 0,
    ancestors: set[int] | None = None,
    allowed_keys: frozenset[str] | None = None,
) -> object:
    """Project untrusted values to a small, JSON-safe, identity-redacted shape."""

    if value is None or type(value) is bool:
        return value
    if type(value) is int:
        return value if -_SQLITE_MAX_ROWID <= value <= _SQLITE_MAX_ROWID else _UNKNOWN_SETTLEMENT_OMIT
    if type(value) is float:
        return value if math.isfinite(value) else _UNKNOWN_SETTLEMENT_OMIT
    if type(value) is str:
        return (
            value
            if len(value) <= _UNKNOWN_SETTLEMENT_MAX_STRING_CHARS and value.isprintable()
            else _UNKNOWN_SETTLEMENT_OMIT
        )
    if depth >= _UNKNOWN_SETTLEMENT_MAX_DEPTH or type(value) not in (dict, list, tuple):
        return _UNKNOWN_SETTLEMENT_OMIT
    ancestor_ids = ancestors or set()
    if id(value) in ancestor_ids:
        return _UNKNOWN_SETTLEMENT_OMIT
    child_ancestors = ancestor_ids | {id(value)}
    if type(value) is dict:
        projected: dict[str, object] = {}
        for index, (key, child) in enumerate(value.items()):
            if index >= _UNKNOWN_SETTLEMENT_MAX_ITEMS or len(projected) >= _UNKNOWN_SETTLEMENT_MAX_ITEMS:
                break
            if type(key) is not str or (allowed_keys is not None and key not in allowed_keys):
                continue
            normalized_key = "".join(char for char in key.casefold() if char.isalnum())
            if any(part in normalized_key for part in _UNKNOWN_SETTLEMENT_SENSITIVE_KEY_PARTS):
                continue
            projected_child = _bounded_json_safe_projection(
                child,
                depth=depth + 1,
                ancestors=child_ancestors,
            )
            if projected_child is not _UNKNOWN_SETTLEMENT_OMIT:
                projected[key] = projected_child
        return projected
    projected_list: list[object] = []
    for index, child in enumerate(value):
        if index >= _UNKNOWN_SETTLEMENT_MAX_ITEMS or len(projected_list) >= _UNKNOWN_SETTLEMENT_MAX_ITEMS:
            break
        projected_child = _bounded_json_safe_projection(child, depth=depth + 1, ancestors=child_ancestors)
        if projected_child is not _UNKNOWN_SETTLEMENT_OMIT:
            projected_list.append(projected_child)
    return projected_list


def _safe_unknown_settlement_evidence(result: object, caller_request_id: str) -> dict[str, object]:
    """Retain only bounded reconciliation status fields from an unknown reply."""

    projected = _bounded_json_safe_projection(result, allowed_keys=_UNKNOWN_SETTLEMENT_EVIDENCE_KEYS)
    if type(projected) is not dict:
        return {}
    safe: dict[str, object] = {}
    for key, value in projected.items():
        if key in {"ok", "committed", "retry_safe"} and type(value) is bool:
            safe[key] = value
        elif key == "proto" and type(value) is int:
            safe[key] = value
        elif (
            key == "request_id"
            and type(value) is str
            and len(value) == 32
            and all(char in "0123456789abcdef" for char in value)
            and value == caller_request_id
        ):
            safe[key] = value
        elif (
            key in {"publication_state", "commit_state", "delivery_state"}
            and type(value) is str
            and value
            in {
                "published",
                "pending",
                "aborted",
                "committed",
                "not_committed",
                "unknown",
                "dispatched",
                "not_dispatched",
            }
        ):
            safe[key] = value
        elif key == "error_code" and type(value) is str and value in _UNKNOWN_SETTLEMENT_SAFE_ERROR_CODES:
            safe[key] = value
        elif key == "schema" and type(value) is str and value in _UNKNOWN_SETTLEMENT_SAFE_SCHEMAS:
            safe[key] = value
    return safe


def _strict_rest_operator_log_commit(result: object, command: dict[str, Any]) -> bool:
    """Accept only a complete receipt bound to the exact REST submission."""

    if type(result) is not dict:
        return False
    publication_state = result.get("publication_state")
    if publication_state == "published":
        expected_keys = _OPERATOR_LOG_SUCCESS_KEYS
        expected_ok = True
    elif publication_state == "pending":
        expected_keys = _OPERATOR_LOG_PENDING_KEYS
        expected_ok = False
    else:
        return False
    if (
        set(result) != expected_keys
        or result.get("ok") is not expected_ok
        or result.get("committed") is not True
        or result.get("retry_safe") is not False
        or type(result.get("proto")) is not int
        or result.get("proto") != PROTOCOL_VERSION
    ):
        return False
    if publication_state == "pending" and (
        result.get("error_code") != _OPERATOR_LOG_PENDING_ERROR_CODE
        or result.get("error") != _OPERATOR_LOG_PENDING_ERROR
    ):
        return False
    entry = result.get("entry")
    receipt = result.get("commit_receipt")
    if (
        type(entry) is not dict
        or set(entry) != _OPERATOR_LOG_ENTRY_KEYS
        or type(receipt) is not dict
        or set(receipt) != _OPERATOR_LOG_RECEIPT_KEYS
    ):
        return False
    entry_id = entry.get("id")
    timestamp = entry.get("timestamp")
    if not _is_sqlite_rowid(entry_id) or type(timestamp) is not str or len(timestamp) > 128:
        return False
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError:
        return False
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed) or parsed.isoformat() != timestamp:
        return False
    expected_experiment_id = command.get("experiment_id")
    expected_tags = command.get("tags", [])
    return (
        receipt.get("schema") == "operator_log_commit_v1"
        and receipt.get("request_id") == command.get("request_id")
        and _is_sqlite_rowid(receipt.get("entry_id"))
        and receipt["entry_id"] == entry_id
        and receipt.get("experiment_id") == expected_experiment_id
        and receipt.get("committed") is True
        and entry.get("experiment_id") == expected_experiment_id
        and entry.get("author") == _REST_IDENTITY
        and entry.get("source") == "rest"
        and entry.get("message") == command.get("message")
        and entry.get("tags") == expected_tags
    )


def _definite_rest_operator_log_rejection(result: object, command: dict[str, Any]) -> bool:
    """Accept only exact engine/REP refusals that prove this write did not commit."""

    if type(result) is not dict:
        return False
    if set(result) == _OPERATOR_LOG_WEB_MUTATION_DISCOVERY_REJECTION_KEYS:
        return (
            result.get("ok") is False
            and type(result.get("error_code")) is str
            and result["error_code"] == "mutation_protocol_incompatible"
            and type(result.get("error")) is str
            and result["error"] == "Web mutation compatibility discovery failed; command was not dispatched"
            and type(result.get("delivery_state")) is str
            and result["delivery_state"] == "not_dispatched"
            and type(result.get("commit_state")) is str
            and result["commit_state"] == "not_committed"
            and result.get("retry_safe") is True
            and _is_exact_mutation_compatibility_rejection_receipt(result.get("compatibility_receipt"))
        )
    if (
        result.get("ok") is not False
        or type(result.get("proto")) is not int
        or result.get("proto") != PROTOCOL_VERSION
        or type(result.get("error_code")) is not str
        or not result["error_code"]
        or type(result.get("error")) is not str
        or not result["error"]
        or type(result.get("retry_safe")) is not bool
    ):
        return False
    rejection = (result["error_code"], result["error"], result["retry_safe"])
    if set(result) == _OPERATOR_LOG_ENGINE_REJECTION_KEYS:
        return result.get("committed") is False and rejection in _OPERATOR_LOG_ENGINE_REJECTIONS
    if set(result) == _OPERATOR_LOG_ENGINE_REJECTION_WITH_REQUEST_ID_KEYS:
        return (
            result.get("committed") is False
            and type(result["request_id"]) is str
            and result["request_id"] == command.get("request_id")
            and rejection in _OPERATOR_LOG_ENGINE_REJECTIONS_WITH_REQUEST_ID
        )
    if set(result) == _OPERATOR_LOG_TRANSPORT_REJECTION_KEYS:
        return result.get("commit_state") == "not_committed" and (
            (result.get("delivery_state") == "not_dispatched" and rejection in _OPERATOR_LOG_TRANSPORT_REJECTIONS)
            or (
                result.get("delivery_state") == "dispatched"
                and rejection in _OPERATOR_LOG_DISPATCHED_TRANSPORT_REJECTIONS
            )
        )
    if set(result) != _OPERATOR_LOG_MUTATION_PROTOCOL_REJECTION_KEYS:
        return False
    return (
        result.get("error_code") == "mutation_protocol_incompatible"
        and result.get("error")
        == "mutating command refused; perform mutation_capabilities discovery and retry explicitly"
        and result.get("delivery_state") == "dispatched"
        and result.get("commit_state") == "not_committed"
        and result.get("retry_safe") is True
        and _is_exact_mutation_compatibility_rejection_receipt(result.get("compatibility_receipt"))
    )


def _unknown_rest_operator_log_settlement(result: object, caller_request_id: str) -> dict[str, Any]:
    """Make an untrusted settlement visibly non-successful with safe evidence."""

    return {
        "ok": False,
        "error_code": "operator_log_settlement_malformed",
        "error": "engine returned an unknown or malformed operator-log settlement",
        "commit_state": "unknown",
        "retry_safe": False,
        "caller_request_id": caller_request_id,
        "engine_settlement": _safe_unknown_settlement_evidence(result, caller_request_id),
    }


@router.post("/log", dependencies=[Depends(require_write_token)], response_model=None)
async def post_log(
    payload: LogAppendIn,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> dict[str, Any] | JSONResponse:
    """Добавить запись в операторский журнал (author = «REST API»)."""
    if len(idempotency_key) != 32 or any(char not in "0123456789abcdef" for char in idempotency_key):
        raise HTTPException(
            status_code=422,
            detail="Idempotency-Key must be exactly 32 lowercase hexadecimal characters",
        )
    cmd: dict[str, Any] = {
        "cmd": "log_entry",
        # The caller owns this stable identity across transport retries. A
        # server-generated key would make an outcome-unknown retry duplicate
        # the durable operator-log entry.
        "request_id": idempotency_key,
        "message": payload.message,
        "author": _REST_IDENTITY,
        "source": "rest",
    }
    if payload.experiment_id is None:
        # Never bind a delayed request to whichever experiment happens to be
        # active when it arrives at the engine.
        cmd["experiment_unbound"] = True
    else:
        cmd["experiment_id"] = payload.experiment_id
    if payload.tags is not None:
        # Reject reserved system tags (impersonation guard). LogAppendIn has
        # already applied the same whitespace normalization as the durable
        # writer, so the security check, command fingerprint, and eventual
        # receipt all see one canonical tag list.
        reserved = _RESERVED_TAGS.intersection(t.strip().casefold() for t in payload.tags)
        if reserved:
            raise HTTPException(
                status_code=422,
                detail=f"Зарезервированные системные теги недопустимы: {', '.join(sorted(reserved))}",
            )
        cmd["tags"] = list(payload.tags)
    result = await _forward_write(cmd)
    if type(result) is not dict:
        return JSONResponse(_unknown_rest_operator_log_settlement(result, idempotency_key), status_code=502)
    if _strict_rest_operator_log_commit(result, cmd):
        if result["publication_state"] == "published":
            return {**result, "request_id": idempotency_key}
        return JSONResponse({**result, "caller_request_id": idempotency_key}, status_code=503)
    if _definite_rest_operator_log_rejection(result, cmd):
        return JSONResponse({**result, "caller_request_id": idempotency_key}, status_code=409)
    return JSONResponse(_unknown_rest_operator_log_settlement(result, idempotency_key), status_code=502)


@router.post(
    "/alarms/{alarm_id}/ack",
    dependencies=[Depends(require_write_token)],
    response_model=None,
)
async def post_alarm_ack(
    alarm_id: str,
    payload: AlarmAckIn,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> dict[str, Any] | JSONResponse:
    """Квитировать аларм (acknowledged_by = «REST API»)."""
    if len(idempotency_key) != 32 or any(char not in "0123456789abcdef" for char in idempotency_key):
        raise HTTPException(
            status_code=422,
            detail="Idempotency-Key must be exactly 32 lowercase hexadecimal characters",
        )
    if not alarm_id or len(alarm_id) > 256 or not alarm_id.isprintable():
        raise HTTPException(status_code=422, detail="alarm identity is invalid")
    command = {
        "cmd": "alarm_v2_ack",
        "alarm_name": alarm_id,
        "engine_instance_id": payload.engine_instance_id,
        "activation_id": payload.activation_id,
        "operator": _REST_IDENTITY,
        "reason": payload.reason,
        "request_id": idempotency_key,
    }
    result = await _forward_write(command)
    settlement = validate_alarm_ack_wire_result(
        result,
        command,
        expected_proto=PROTOCOL_VERSION,
    )
    if settlement == "published":
        assert type(result) is dict
        return dict(result)
    if settlement == "pending":
        raise HTTPException(
            status_code=503,
            detail="alarm acknowledgement committed; retry the same Idempotency-Key to settle publication",
        )
    if settlement == "aborted":
        assert type(result) is dict
        return JSONResponse(dict(result), status_code=409)
    # No open ``ok=False`` compatibility path exists. In particular, an
    # aborted-looking result with a missing protocol marker or mismatched
    # request identity must not be laundered into an HTTP 200 response after
    # the closed wire validator rejected it.
    raise HTTPException(status_code=502, detail="incomplete alarm acknowledgement receipt")
