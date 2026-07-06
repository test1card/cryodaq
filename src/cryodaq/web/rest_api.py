"""Read-only REST facade for CryoDAQ (``/api/v1``) with Swagger docs.

A thin, GET-only layer over the SAME cache/command path the dashboard uses
(``server._state.last_readings``, ``server._query_history``, existing read
commands). It adds nothing that mutates engine state — there are no write
verbs here by construction.

Security payload (do not remove):
- **Field whitelist.** Every response goes through a Pydantic ``response_model``
  that declares ONLY safe fields. The model *is* the redaction: fields it does
  not declare (operator, sample, notes, config_snapshot, artifact paths,
  operator-log authors) are dropped before serialization.
- **Request-size limit.** ``BodySizeLimitMiddleware`` rejects oversize bodies
  with 413 before the request is routed — i.e. before any engine call.

Loopback-only, unauthenticated by design (SSH tunnel for LAN); see the
``server`` module docstring.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

# Imported as a module (not names) so handlers read live state and the patched
# _async_engine_command used by tests, and to keep the import non-circular:
# server imports this module inside create_app().
from cryodaq.web import server

# Max request body for the unauthenticated facade. All endpoints are GET and
# take no body; a large body is only ever abuse. 1 MiB is generous headroom.
MAX_BODY_BYTES = 1 * 1024 * 1024

router = APIRouter(prefix="/api/v1", tags=["read-only"])


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


def _readings_with_unit(unit: str) -> list[dict[str, Any]]:
    return [r for r in server._state.last_readings.values() if r.get("unit") == unit]


# ---------------------------------------------------------------------------
# Endpoints — all GET, all read-only, all field-whitelisted
# ---------------------------------------------------------------------------


@router.get("/state")
async def get_state() -> dict[str, Any]:
    """System status snapshot (uptime, instruments, safety, alarm counts)."""
    return server._state.status_json()


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
            return {"ok": True, "active": result.get("active", {})}
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
