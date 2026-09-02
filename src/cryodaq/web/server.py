"""Веб-панель удалённого мониторинга CryoDAQ.

Лёгкий FastAPI-сервер для доступа к данным engine из браузера:
- WebSocket ``/ws`` — поток показаний в реальном времени
- GET ``/status`` — JSON со статусом приборов, тревог, uptime
- GET ``/history`` — JSON с историческими данными из SQLite (последние N минут)
- GET ``/`` — статическая HTML-страница (single-page dashboard)

Запуск::

    uvicorn cryodaq.web.server:app --host 127.0.0.1 --port 8080

For LAN access route via SSH tunnel; never bind 0.0.0.0 directly.

Или программно::

    from cryodaq.web.server import create_app
    app = create_app()
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version as _get_version

try:
    _VERSION = _get_version("cryodaq")
except Exception:
    _VERSION = "dev"
import json
import logging
import math
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import zmq
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from cryodaq.core.zmq_bridge import PROTOCOL_VERSION, ZMQSubscriber
from cryodaq.drivers.base import Reading
from cryodaq.paths import get_data_dir
from cryodaq.storage._sqlite import sqlite3
from cryodaq.storage.sentinel import decode

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"

# ---------------------------------------------------------------------------
# Standalone ZMQ command client (no GUI dependency)
# ---------------------------------------------------------------------------

_CMD_ADDR = "tcp://127.0.0.1:5556"  # REP port = PUB + 1

# Bounds for unauthenticated read endpoints — a too-large value would scan
# every data_*.db into memory (/history) or pull an unbounded log (/api/log)
# and can OOM the web process. Clamp rather than 500.
_HISTORY_MAX_MINUTES = 1440  # 24 h — covers the dashboard's longest window
_LOG_MAX_LIMIT = 2000
_STATUS_FRESHNESS_S = 10.0
_MUTATION_PROTOCOL_MAJOR = 1
_MUTATION_CAPABILITY = "cryodaq_mutation_v1"
_MUTATION_RECEIPT_SCHEMA = "mutation_compatibility_v1"
_MUTATION_RECEIPT_KEYS = frozenset(
    {
        "schema",
        "accepted",
        "server_protocol_major",
        "required_capability",
        "capability_token",
    }
)
_MUTATION_ENVELOPE_KEYS = frozenset({"protocol_major", "mutation_capability", "capability_token"})
_WEB_READ_ONLY_COMMANDS = frozenset(
    {
        "mutation_capabilities",
        "safety_status",
        "alarm_v2_status",
        "experiment_status",
        "log_get",
    }
)
_mutation_lock = threading.Lock()
_mutation_receipt: dict[str, Any] | None = None


def _json_safe_value(value: Any) -> Any:
    """Return a strict-JSON projection with non-finite floats masked.

    JSON's ``NaN``/``Infinity`` extensions are not valid RFC 8259 values and
    browsers disagree about how to handle them.  Public monitoring surfaces
    therefore preserve the reading/status evidence but represent an unknown
    numeric value as ``null``.
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe_value(item) for item in value]
    return value


def _requires_mutation_envelope(action: object) -> bool:
    """Default unknown web commands to the fail-closed mutation path."""
    return type(action) is not str or not action or action not in _WEB_READ_ONLY_COMMANDS


def _send_engine_command_once(cmd: dict[str, Any]) -> dict[str, Any]:
    """Send exactly one REQ and classify whether a mutation may have landed."""
    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.REQ)
    sock.setsockopt(zmq.RCVTIMEO, 5000)
    sock.setsockopt(zmq.SNDTIMEO, 5000)
    sock.setsockopt(zmq.LINGER, 0)
    send_started = False
    try:
        sock.connect(_CMD_ADDR)
        send_started = True
        sock.send_json(cmd)
        response = sock.recv_json()
        if type(response) is not dict:
            raise ValueError("engine response is not an object")
        return response
    except Exception as exc:  # noqa: BLE001 - turn transport/codec faults into evidence
        logger.warning("Web engine command transport failed for %s: %s", cmd.get("cmd"), exc)
        if send_started and _requires_mutation_envelope(cmd.get("cmd")):
            return {
                "ok": False,
                "error_code": "mutation_outcome_unknown",
                "error": "Engine did not return a valid mutation receipt; outcome is unknown",
                "delivery_state": "unknown",
                "commit_state": "unknown",
                "retry_safe": False,
            }
        return {
            "ok": False,
            "error_code": "engine_unavailable",
            "error": "Engine не отвечает",
            "delivery_state": "not_confirmed",
            "retry_safe": True,
        }
    finally:
        sock.close()


def _mutation_discovery_failure() -> dict[str, Any]:
    return {
        "ok": False,
        "error_code": "mutation_protocol_incompatible",
        "error": "Web mutation compatibility discovery failed; command was not dispatched",
        "delivery_state": "not_dispatched",
        "commit_state": "not_committed",
        "retry_safe": True,
        "compatibility_receipt": {
            "schema": _MUTATION_RECEIPT_SCHEMA,
            "accepted": False,
            "server_protocol_major": _MUTATION_PROTOCOL_MAJOR,
            "required_capability": _MUTATION_CAPABILITY,
        },
    }


def _ensure_mutation_compatibility() -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Discover one strict receipt; concurrent web writes share the flight."""
    global _mutation_receipt
    with _mutation_lock:
        if _mutation_receipt is not None:
            return dict(_mutation_receipt), None
        discovery = _send_engine_command_once({"cmd": "mutation_capabilities"})
        receipt = discovery.get("compatibility_receipt") if type(discovery) is dict else None
        token = receipt.get("capability_token") if type(receipt) is dict else None
        valid = (
            discovery.get("ok") is True
            and type(receipt) is dict
            and set(receipt) == _MUTATION_RECEIPT_KEYS
            and receipt.get("schema") == _MUTATION_RECEIPT_SCHEMA
            and receipt.get("accepted") is True
            and type(receipt.get("server_protocol_major")) is int
            and receipt.get("server_protocol_major") == _MUTATION_PROTOCOL_MAJOR
            and receipt.get("required_capability") == _MUTATION_CAPABILITY
            and type(token) is str
            and 16 <= len(token) <= 512
            and token.isprintable()
        )
        if not valid:
            _mutation_receipt = None
            return None, _mutation_discovery_failure()
        _mutation_receipt = {
            "schema": receipt["schema"],
            "accepted": True,
            "server_protocol_major": receipt["server_protocol_major"],
            "required_capability": receipt["required_capability"],
            "capability_token": token,
        }
        return dict(_mutation_receipt), None


def _invalidate_mutation_compatibility() -> None:
    global _mutation_receipt
    with _mutation_lock:
        _mutation_receipt = None


def _send_engine_command(cmd: dict) -> dict:
    """Dispatch one web command with fail-closed mutation negotiation."""
    if type(cmd) is not dict:
        return {
            "ok": False,
            "error_code": "command_invalid",
            "error": "Web engine command must be a plain mapping",
            "retry_safe": True,
        }
    action = cmd.get("cmd")
    if type(action) is not str or not action:
        return {
            "ok": False,
            "error_code": "command_invalid",
            "error": "Web engine command requires a non-empty string cmd",
            "retry_safe": True,
        }
    command = {key: value for key, value in cmd.items() if key not in _MUTATION_ENVELOPE_KEYS}
    if not _requires_mutation_envelope(action):
        return _send_engine_command_once(command)

    receipt, failure = _ensure_mutation_compatibility()
    if failure is not None:
        return failure
    assert receipt is not None
    command.update(
        {
            "protocol_major": receipt["server_protocol_major"],
            "mutation_capability": receipt["required_capability"],
            "capability_token": receipt["capability_token"],
        }
    )
    result = _send_engine_command_once(command)
    if result.get("error_code") == "mutation_protocol_incompatible":
        # Refresh only for the next explicit HTTP request; never replay here.
        _invalidate_mutation_compatibility()
    return result


async def _async_engine_command(cmd: dict) -> dict:
    """Non-blocking engine command via thread pool."""
    return await asyncio.to_thread(_send_engine_command, cmd)


# Директория с файлами данных SQLite (data_YYYY-MM-DD.db)
_DATA_DIR = get_data_dir()

# ---------------------------------------------------------------------------
# Глобальное состояние сервера
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Availability:
    available: bool
    stale: bool
    reason: str | None

    def __post_init__(self) -> None:
        if type(self.available) is not bool or type(self.stale) is not bool:
            raise ValueError("availability fields must be bool")
        if not self.available and not self.stale:
            raise ValueError("unavailable availability must be stale")
        if self.available and not self.stale:
            if self.reason is not None:
                raise ValueError("live availability cannot have a reason")
        elif not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("stale or unavailable availability requires a reason")


class HistoryUnavailable(RuntimeError):
    """A requested history window could not be fully read from its daily archive."""


class _ServerState:
    """Общее состояние для всех WebSocket-клиентов."""

    def __init__(self) -> None:
        self.start_time: float = time.monotonic()
        self.total_readings: int = 0
        self.last_readings: dict[str, dict[str, Any]] = {}  # channel → serialized reading
        self.active_alarms: dict[str, dict[str, Any]] = {}
        self.safety_state: str = "unknown"
        self.instrument_status: dict[str, dict[str, Any]] = {}
        self.clients: set[WebSocket] = set()
        self.subscriber: ZMQSubscriber | None = None
        self._last_authoritative_reading_at: float | None = None
        self._availability = _Availability(False, True, "awaiting authoritative ZMQ reading")
        self._safety_availability = _Availability(False, True, "safety status unavailable")
        self._alarms_availability = _Availability(False, True, "alarm status unavailable")
        self._lock = asyncio.Lock()
        # Bounded broadcast queue — prevents task explosion under load.
        # Initialised in startup (requires running event loop).
        self.broadcast_q: asyncio.Queue[dict[str, Any]] | None = None

    def on_reading(self, reading: Reading) -> None:
        """Обработать входящее показание (вызывается из ZMQ callback)."""
        self.total_readings += 1

        data = {
            "timestamp": reading.timestamp.isoformat(),
            "channel": reading.channel,
            "value": _json_safe_value(reading.value),
            "unit": reading.unit,
            "status": reading.status.value,
        }
        self.last_readings[reading.channel] = data
        self._last_authoritative_reading_at = time.monotonic()
        self._availability = _Availability(True, False, None)

        # Определить прибор
        inst_id = reading.instrument_id or ""
        if not inst_id and "/" in reading.channel:
            inst_id = reading.channel.split("/")[0]
        elif not inst_id and reading.channel.startswith("Т"):
            try:
                num = int(reading.channel[1:].split(" ")[0])
                if 1 <= num <= 8:
                    inst_id = "LS218_1"
                elif 9 <= num <= 16:
                    inst_id = "LS218_2"
                elif 17 <= num <= 24:
                    inst_id = "LS218_3"
            except (ValueError, IndexError):
                pass

        if inst_id:
            self.instrument_status[inst_id] = {
                "last_seen": reading.timestamp.isoformat(),
                "status": reading.status.value,
                "total_readings": self.instrument_status.get(inst_id, {}).get("total_readings", 0) + 1,
            }

    def invalidate_producer(self, reason: str) -> None:
        """Retain cached diagnostics while withdrawing producer authority."""
        self._availability = _Availability(False, True, reason)

    def _availability_json(self) -> _Availability:
        availability = self._availability
        if not availability.available:
            return availability
        last_reading_at = self._last_authoritative_reading_at
        if last_reading_at is None:
            return _Availability(False, True, "awaiting authoritative ZMQ reading")
        age_s = time.monotonic() - last_reading_at
        if age_s > _STATUS_FRESHNESS_S:
            return _Availability(True, True, f"ZMQ reading age exceeds {_STATUS_FRESHNESS_S:g} seconds")
        return availability

    def _safety_json(self) -> dict[str, Any]:
        availability = self._safety_availability
        return {
            "state": self.safety_state,
            "available": availability.available,
            "stale": availability.stale,
            "reason": availability.reason,
        }

    def _alarms_json(self) -> dict[str, Any]:
        availability = self._alarms_availability
        return {
            "active": self.active_alarms,
            "available": availability.available,
            "stale": availability.stale,
            "reason": availability.reason,
        }

    def status_json(self) -> dict[str, Any]:
        """Собрать JSON-статус для GET /status."""
        availability = self._availability_json()
        uptime_s = time.monotonic() - self.start_time
        hours, rem = divmod(int(uptime_s), 3600)
        mins, secs = divmod(rem, 60)
        return {
            "uptime": f"{hours:02d}:{mins:02d}:{secs:02d}",
            "uptime_s": round(uptime_s, 1),
            "total_readings": self.total_readings,
            "channels": len(self.last_readings),
            "instruments": self.instrument_status,
            "safety_state": self.safety_state,
            "active_alarms": self.active_alarms,
            "safety": self._safety_json(),
            "alarms": self._alarms_json(),
            "ws_clients": len(self.clients),
            "available": availability.available,
            "stale": availability.stale,
            "reason": availability.reason,
        }


_state = _ServerState()


# ---------------------------------------------------------------------------
# Broadcast к WebSocket-клиентам
# ---------------------------------------------------------------------------


async def _broadcast(data: dict[str, Any]) -> None:
    """Отправить JSON всем подключённым WebSocket-клиентам."""
    if not _state.clients:
        return
    message = json.dumps(_json_safe_value(data), ensure_ascii=False, allow_nan=False)
    disconnected: list[WebSocket] = []
    for ws in _state.clients:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        _state.clients.discard(ws)


async def _broadcast_pump() -> None:
    """Одна фоновая задача вместо N fire-and-forget tasks.

    Читает из ограниченной очереди _state.broadcast_q и рассылает
    по WebSocket. Если нет клиентов — сообщение просто отбрасывается.
    Это предотвращает накопление тысяч Task-объектов в event loop.
    """
    q = _state.broadcast_q
    assert q is not None
    while True:
        data = await q.get()
        if _state.clients:
            await _broadcast(data)


async def _zmq_to_ws_bridge() -> None:
    """Фоновая задача: получает Reading от ZMQ, рассылает по WebSocket."""
    sub = ZMQSubscriber(callback=_on_reading_callback)
    _state.subscriber = sub
    try:
        await sub.start()
        logger.info("ZMQ→WS мост запущен")
        # Задача живёт вечно — остановка через lifespan
        while True:  # noqa: ASYNC110
            await asyncio.sleep(3600)
    finally:
        try:
            await sub.stop()
        finally:
            if _state.subscriber is sub:
                _state.invalidate_producer("ZMQ readings producer stopped")
                _state.subscriber = None


def _on_reading_callback(reading: Reading) -> None:
    """Sync callback от ZMQSubscriber — обновляет состояние и ставит broadcast."""
    _state.on_reading(reading)

    if not _state.clients:
        return  # Нет клиентов — не создавать очередные задачи

    q = _state.broadcast_q
    if q is None:
        return

    # Build the event from the already-normalised cache entry so the REST and
    # WebSocket surfaces cannot drift on missing/non-finite value semantics.
    data = {"type": "reading", **_state.last_readings[reading.channel]}
    try:
        q.put_nowait(data)
    except asyncio.QueueFull:
        pass  # Отбрасываем показание, очередь переполнена


# ---------------------------------------------------------------------------
# История из SQLite
# ---------------------------------------------------------------------------


def _find_recent_db(data_dir: Path) -> Path | None:
    """Найти самый свежий файл data_YYYY-MM-DD.db в директории."""
    if not data_dir.exists():
        return None
    db_files = sorted(data_dir.glob("data_????-??-??.db"))
    return db_files[-1] if db_files else None


def _query_history(minutes: int) -> dict[str, list[dict[str, Any]]]:
    """Запросить данные из SQLite за последние N минут.

    Сканирует все DB-файлы, чей date-суффикс может пересекаться с окном запроса,
    чтобы корректно обрабатывать cross-midnight запросы.

    Возвращает словарь: channel → [{"t": iso, "v": float, "u": unit}, ...]
    """
    # Clamp to a sane window — an unauthenticated caller must not be able to
    # scan the entire archive into memory via ?minutes=99999999.
    minutes = max(1, min(minutes, _HISTORY_MAX_MINUTES))
    cutoff = datetime.now(UTC) - timedelta(minutes=minutes)
    cutoff_epoch = cutoff.timestamp()

    result: dict[str, list[dict[str, Any]]] = {}

    if not _DATA_DIR.exists():
        return result

    # Daily filenames use the writer's wall-clock date. Include one preceding
    # day conservatively for timezone/cross-midnight overlap, but never open
    # the entire archive for a short dashboard request.
    oldest_candidate_date = (cutoff - timedelta(days=1)).date()
    latest_candidate_date = (datetime.now(UTC) + timedelta(days=1)).date()
    for db_path in sorted(_DATA_DIR.glob("data_????-??-??.db")):
        try:
            db_date = datetime.strptime(db_path.stem.removeprefix("data_"), "%Y-%m-%d").date()
        except ValueError:
            logger.warning("Ignoring malformed daily SQLite filename: %s", db_path.name)
            continue
        if not oldest_candidate_date <= db_date <= latest_candidate_date:
            continue
        conn = None
        try:
            # Read-only: this SELECT-only consumer must not hold write authority on a
            # database the writer owns. A read-write connection's clean close is what
            # unlinked the live WAL on 2026-09-02 (see sqlite_writer._control_stat_identity_at).
            conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT timestamp, channel, value, unit, status FROM readings "
                "WHERE timestamp >= ? ORDER BY timestamp ASC",
                (cutoff_epoch,),
            ).fetchall()
        except Exception as exc:
            logger.warning("History query failed for %s: %s", db_path.name, exc)
            raise HistoryUnavailable("history database unavailable") from exc
        finally:
            if conn is not None:
                conn.close()
        for row in rows:
            ch = row["channel"]
            # NaN-доктрина: mask sentinel / error / legacy ±inf to null — an
            # unusable reading must never reach the dashboard/REST feed as a number.
            v = decode(row["value"], row["status"])
            result.setdefault(ch, []).append(
                {
                    "t": datetime.fromtimestamp(row["timestamp"], tz=UTC).isoformat(),
                    "v": v if math.isfinite(v) else None,
                    "u": row["unit"],
                }
            )

    return result


# ---------------------------------------------------------------------------
# FastAPI приложение
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    """Создать и настроить FastAPI-приложение."""

    @asynccontextmanager
    async def _lifespan(_application: FastAPI) -> AsyncIterator[None]:
        # Initialize loop-owned state only while this application is live.
        _state.broadcast_q = asyncio.Queue(maxsize=200)
        pump_task = asyncio.create_task(_broadcast_pump(), name="broadcast_pump")
        zmq_task = asyncio.create_task(_zmq_to_ws_bridge(), name="zmq_ws_bridge")
        tasks = (zmq_task, pump_task)
        logger.info("Веб-сервер CryoDAQ запущен")
        try:
            yield
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            _state.broadcast_q = None
            failures = [
                result
                for result in results
                if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError)
            ]
            logger.info("Веб-сервер CryoDAQ остановлен")
            if failures:
                raise RuntimeError("web background task settlement failed") from failures[0]

    application = FastAPI(
        title="CryoDAQ Web Dashboard",
        description="Удалённый мониторинг криогенной системы",
        version=_VERSION,
        lifespan=_lifespan,
    )

    # Read-only REST facade + Swagger. Imported here (not at module top) to
    # keep the server<->rest_api import non-circular.
    from cryodaq.web.rest_api import (
        BodySizeLimitMiddleware,
        WriteAuthMiddleware,
        project_public_experiment,
        project_public_log_entries,
        redact_public_payload,
    )
    from cryodaq.web.rest_api import router as rest_router

    application.add_middleware(BodySizeLimitMiddleware)
    # Auth before body parsing on every mutating /api/v1 request (H1).
    application.add_middleware(WriteAuthMiddleware)
    application.include_router(rest_router)

    # Статические файлы
    if _STATIC_DIR.exists():
        application.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @application.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        """Главная страница — self-contained HTML dashboard."""
        return HTMLResponse(content=_DASHBOARD_HTML.replace("__VERSION__", _VERSION))

    @application.get("/status")
    async def status() -> dict[str, Any]:
        """JSON-статус системы."""
        return redact_public_payload(_state.status_json())

    @application.get("/api/status")
    async def api_status() -> dict[str, Any]:
        """Полный JSON-статус: readings + experiment + shift."""
        base = redact_public_payload(_state.status_json())
        base["readings"] = _state.last_readings
        # Safety status via engine command
        try:
            safety = await _async_engine_command({"cmd": "safety_status"})
            if safety.get("ok"):
                _state.safety_state = safety.get("state", "unknown")
                _state._safety_availability = _Availability(True, False, None)
                base["safety"] = {
                    **{key: value for key, value in safety.items() if key != "ok"},
                    **_state._safety_json(),
                }
            else:
                logger.warning("api_status safety fetch non-ok")
                _state._safety_availability = _Availability(False, True, "safety status unavailable")
                base["safety"] = _state._safety_json()
        except Exception as exc:
            logger.warning("api_status safety fetch failed: %s", exc)
            _state._safety_availability = _Availability(False, True, "safety status unavailable")
            base["safety"] = _state._safety_json()
        # Alarm status via engine command
        try:
            alarms = await _async_engine_command({"cmd": "alarm_v2_status"})
            if alarms.get("ok"):
                _state.active_alarms = alarms.get("active", {})
                base["active_alarms"] = redact_public_payload(alarms.get("active", {}))
                _state._alarms_availability = _Availability(True, False, None)
                base["alarms"] = redact_public_payload(_state._alarms_json())
            else:
                logger.warning("api_status alarm fetch non-ok")
                _state._alarms_availability = _Availability(False, True, "alarm status unavailable")
                base["alarms"] = redact_public_payload(_state._alarms_json())
        except Exception as exc:
            logger.warning("api_status alarm fetch failed: %s", exc)
            _state._alarms_availability = _Availability(False, True, "alarm status unavailable")
            base["alarms"] = redact_public_payload(_state._alarms_json())
        # Experiment/shift data via ZMQ command. ``experiment`` keeps its
        # projected shape (object or None) for back-compat, and the separate
        # ``experiment_available`` flag lets the dashboard tell an unreachable
        # engine (False) from a reachable engine with no active experiment
        # (True, ``experiment`` None) — they must not share one shape.
        try:
            exp = await _async_engine_command({"cmd": "experiment_status"})
            if exp.get("ok"):
                base["experiment"] = project_public_experiment(exp)
                base["experiment_available"] = True
            else:
                base["experiment"] = None
                base["experiment_available"] = False
        except Exception as exc:
            logger.warning("api_status experiment fetch failed: %s", exc)
            base["experiment"] = None
            base["experiment_available"] = False
        return redact_public_payload(base)

    @application.get("/api/version")
    async def api_version() -> dict[str, Any]:
        """Protocol + app version triple — unauthenticated read, same trust
        as the other GET routes (see docs/protocol.md)."""
        return {"proto": PROTOCOL_VERSION, "server": "web", "app_version": _VERSION}

    @application.get("/api/log")
    async def api_log(limit: int = 10) -> dict[str, Any]:
        """Последние записи журнала."""
        # Clamp the unauthenticated limit before forwarding to the engine.
        limit = max(1, min(limit, _LOG_MAX_LIMIT))
        try:
            result = await _async_engine_command({"cmd": "log_get", "log_scope": "all", "limit": limit})
            if result.get("ok"):
                return {
                    "ok": True,
                    "entries": project_public_log_entries(result.get("entries", [])),
                }
        except Exception as exc:
            logger.warning("api_log fetch failed: %s", exc)
        return {
            "ok": False,
            "entries": [],
            "available": False,
            "stale": True,
            "reason": "operator log unavailable",
        }

    @application.get("/history")
    async def history(minutes: int = 60) -> dict[str, Any]:
        """Исторические данные из SQLite за последние N минут.

        Возвращает::

            {
              "channels": {
                "Т1": [{"t": "2026-03-14T10:00:00+00:00", "v": 4.2, "u": "K"}, ...],
                ...
              }
            }
        """
        loop = asyncio.get_running_loop()
        try:
            channels = await loop.run_in_executor(None, _query_history, minutes)
        except HistoryUnavailable:
            return JSONResponse(
                {
                    "available": False,
                    "stale": True,
                    "reason": "history unavailable",
                },
                status_code=503,
            )
        return {"channels": channels}

    @application.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        """WebSocket — поток показаний в реальном времени."""
        await ws.accept()
        _state.clients.add(ws)
        logger.info("WebSocket клиент подключён (всего: %d)", len(_state.clients))
        try:
            while True:
                # Ждём ping/pong или команды от клиента
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            _state.clients.discard(ws)
            logger.info("WebSocket клиент отключён (всего: %d)", len(_state.clients))

    return application


_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CryoDAQ Monitor</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0d1117;color:#c9d1d9;font-family:system-ui,-apple-system,sans-serif;padding:8px}
.header{display:flex;justify-content:space-between;align-items:center;padding:8px 12px;
background:#161b22;border:1px solid #30363d;border-radius:6px;margin-bottom:8px}
.header h1{font-size:16px;color:#f0f6fc}
.header .ver{color:#8b949e;font-size:12px}
.status-bar{display:flex;gap:16px;padding:8px 12px;background:#161b22;
border:1px solid #30363d;border-radius:6px;margin-bottom:8px;flex-wrap:wrap}
.status-bar .item{font-size:13px}
.section{background:#161b22;border:1px solid #30363d;border-radius:6px;
padding:10px 12px;margin-bottom:8px}
.section-title{font-size:12px;color:#8b949e;margin-bottom:6px;text-transform:uppercase}
.temps{display:grid;grid-template-columns:repeat(8,1fr);gap:4px}
@media(max-width:600px){.temps{grid-template-columns:repeat(4,1fr)}}
.temp-card{background:#21262d;border-radius:4px;padding:4px 6px;text-align:center}
.temp-card .name{font-size:10px;color:#8b949e}
.temp-card .val{font-size:16px;font-weight:bold}
.cold{color:#58a6ff} .mid{color:#c9d1d9} .warm{color:#f0883e} .hot{color:#f85149}
.unavailable{color:#8b949e}
.availability{display:none;padding:10px 12px;margin-bottom:8px;border:2px solid #f0883e;
background:#161b22;color:#f0f6fc;font-weight:bold}
.availability.unavailable{border-color:#f85149}
#cached-label{display:none;color:#8b949e;font-size:12px;margin:-2px 0 8px}
.log-entry{font-size:12px;color:#8b949e;padding:2px 0;border-bottom:1px solid #21262d}
.log-entry .ts{color:#58a6ff}
#updated{font-size:11px;color:#484f58;text-align:right;padding:4px}
body.dashboard-stale #updated{color:#f0883e;font-weight:bold}
</style>
</head>
<body>
<div class="header"><h1>CryoDAQ Monitor</h1>
 <span class="ver"><a href="/docs" style="color:#58a6ff;text-decoration:none">API docs</a> · v__VERSION__</span></div>
<div class="status-bar">
 <span class="item" id="safety">—</span>
 <span class="item" id="uptime">Аптайм: --:--:--</span>
 <span class="item" id="alarms">—</span>
 <span class="item" id="channels">0 каналов</span>
</div>
<div class="availability" id="availability" role="alert"></div>
<div id="cached-label"></div>
<div class="section"><div class="section-title">Эксперимент</div><div id="experiment">—</div></div>
<div class="section"><div class="section-title">Температуры</div>
<div class="temps" id="temps"></div></div>
<div class="section"><div class="section-title">Давление</div><div id="pressure">—</div></div>
<div class="section">
<div class="section-title">Прочие показания (не классифицированы как температура или давление)</div>
<div id="other-readings">—</div></div>
<div class="section"><div class="section-title">Keithley (слоты не настроены)</div><div id="keithley">—</div></div>
<div class="section"><div class="section-title">Журнал</div><div id="log"></div></div>
<div id="updated"></div>
<script>
function escapeHtml(s){if(s==null)return '';return String(s)
 .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
 .replace(/"/g,'&quot;').replace(/'/g,'&#39;')}
function tempColor(v){if(v<10)return'cold';if(v<100)return'mid';if(v<250)return'warm';return'hot'}
function isUsableReading(r){return r&&typeof r.value==='number'&&Number.isFinite(r.value)}
function displayChannelCount(value){return typeof value==='number'&&Number.isFinite(value)?value+' каналов':'— каналов'}
async function fetchJson(url){const response=await fetch(url);
 if(!response.ok)throw new Error('HTTP '+response.status);
 return response.json()}
function markRefreshStale(error){
 document.body.classList.add('dashboard-stale');
 document.getElementById('updated').textContent='Данные устарели: '
  +(error.message||'нет связи')+'. Показаны последние полученные значения.';
}
function setAvailability(d){
 const unavailable=d.available===false;
 const stale=d.available===true&&d.stale===true;
 const warning=document.getElementById('availability');
 const cached=document.getElementById('cached-label');
 if(!unavailable&&!stale){
  warning.style.display='none';warning.textContent='';warning.classList.remove('unavailable');
  cached.style.display='none';cached.textContent='';return false;
 }
 const label=unavailable?'UNAVAILABLE':'STALE';
 const reason=typeof d.reason==='string'&&d.reason?d.reason:'availability unknown';
 warning.textContent=label+' — '+reason;
 warning.style.display='block';warning.classList.toggle('unavailable',unavailable);
 cached.textContent='last-known values below';cached.style.display='block';
 document.body.classList.add('dashboard-stale');
 return true;
}
async function refresh(){
 try{
  const[d,ld]=await Promise.all([fetchJson('/api/status'),fetchJson('/api/log?limit=5')]);
  const lastKnown=setAvailability(d);
  document.getElementById('uptime').textContent='Аптайм: '+(d.uptime||'--');
  document.getElementById('channels').textContent=displayChannelCount(d.channels);
  // Safety state
  const safety=d.safety;
  if(safety&&safety.available!==false&&safety.state){
   const st=safety.state;
   const el=document.getElementById('safety');
   el.textContent=(lastKnown?'LAST-KNOWN: ':'')+st.toUpperCase();
   el.style.color=(st==='fault'||st==='fault_latched')?'#f85149':'#3fb950';
  }else{document.getElementById('safety').textContent=lastKnown?'LAST-KNOWN: —':'—'}
  // Alarms
  const alarmSection=d.alarms;
  const aa=d.active_alarms||{};
  const ac=Object.keys(aa).length;
  const alarmsUnavailable=alarmSection&&alarmSection.available===false;
  const alarmsText=alarmsUnavailable?'UNAVAILABLE':(lastKnown?'LAST-KNOWN: ':'')+ac+' алармов';
  document.getElementById('alarms').textContent=alarmsText;
  // Readings
  const readings=d.readings||{};
  let temps='',pressure='—',other='';
  const sorted=Object.entries(readings).sort((a,b)=>a[0].localeCompare(b[0]));
  for(const[ch,r]of sorted){
   const usable=isUsableReading(r);
   if(r&&r.unit==='K'){
    const c=usable?tempColor(r.value):'unavailable';
    const value=usable?r.value.toFixed(2):'—';
    temps+=`<div class="temp-card"><div class="name">${escapeHtml(ch.split(' ')[0])}</div>`+
      `<div class="val ${c}"${usable?'':' title="Нет данных"'}>${value}</div></div>`;
   }else if(r&&r.unit==='mbar'){
    pressure=usable?r.value.toExponential(2)+' mbar':'— mbar';
   }else if(r){
    const value=usable?String(r.value):'—';
    const unit=typeof r.unit==='string'&&r.unit?r.unit:'единица не объявлена';
    other+=`<div>${escapeHtml(ch)}: ${escapeHtml(value)} ${escapeHtml(unit)}</div>`;
   }
  }
  document.getElementById('temps').innerHTML=temps||'Нет данных';
  document.getElementById('pressure').textContent=pressure;
  document.getElementById('other-readings').innerHTML=other||'Нет данных';
  document.getElementById('keithley').textContent='A: НЕИЗВЕСТНО │ B: НЕИЗВЕСТНО';
   // Experiment — distinguish "unavailable" from "no experiment"; an
   // unreachable engine must never render as an authoritative empty.
   const exp=d.experiment;
   if(d.experiment_available===false){
    document.getElementById('experiment').textContent='Эксперимент: нет связи';
   }else if(lastKnown){
    document.getElementById('experiment').textContent=exp&&exp.active_experiment
     ?'LAST-KNOWN: '+(exp.active_experiment.name||'—')
     :'Эксперимент: последнее известное состояние недоступно';
   }else if(exp&&exp.active_experiment){
    const e=exp.active_experiment;
    const phase=exp.current_phase?' ['+exp.current_phase+']':'';
    document.getElementById('experiment').textContent=(e.name||'—')+phase;
   }else{document.getElementById('experiment').textContent='Нет активного эксперимента'}
  const logUnavailable=ld.available===false;
  let html='';
  for(const e of(!logUnavailable&&ld.ok?ld.entries||[]:[])){
   const ts=(e.timestamp||'').split('T')[1]||'';
   html+=`<div class="log-entry"><span class="ts">${ts.substring(0,8)}</span> `+
     `[${escapeHtml(e.author||e.source||'?')}] ${escapeHtml(e.message||'')}</div>`;
  }
  const logPlaceholder=logUnavailable?'Журнал: недоступен':(ld.ok?'Нет записей':'Журнал недоступен');
  document.getElementById('log').innerHTML=html||logPlaceholder;
  if(!lastKnown){document.body.classList.remove('dashboard-stale');
   document.getElementById('updated').textContent='Обновлено: '+new Date().toLocaleTimeString();}
 }catch(e){markRefreshStale(e)}
}
refresh();setInterval(refresh,5000);
</script>
</body>
</html>"""

# Инстанс для uvicorn: `uvicorn cryodaq.web.server:app`
app = create_app()
