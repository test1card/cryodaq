"""Веб-панель удалённого мониторинга CryoDAQ.

Лёгкий FastAPI-сервер для доступа к данным engine из браузера:
- WebSocket ``/ws`` — поток показаний в реальном времени
- GET ``/status`` — JSON со статусом приборов, тревог, uptime
- GET ``/history`` — JSON с историческими данными из SQLite (последние N минут)
- GET ``/`` — статическая HTML-страница (single-page dashboard)

Запуск::

    uvicorn cryodaq.web.server:app --host 0.0.0.0 --port 8080

Или программно::

    from cryodaq.web.server import create_app
    app = create_app()
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from cryodaq.core.zmq_bridge import ZMQSubscriber
from cryodaq.drivers.base import Reading
from cryodaq.paths import get_data_dir
from cryodaq.storage.sqlite_writer import _parse_timestamp

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"

# Директория с файлами данных SQLite (data_YYYY-MM-DD.db)
_DATA_DIR = get_data_dir()

# ---------------------------------------------------------------------------
# Глобальное состояние сервера
# ---------------------------------------------------------------------------

class _ServerState:
    """Общее состояние для всех WebSocket-клиентов."""

    def __init__(self) -> None:
        self.start_time: float = time.monotonic()
        self.total_readings: int = 0
        self.last_readings: dict[str, dict[str, Any]] = {}  # channel → serialized reading
        self.active_alarms: dict[str, dict[str, Any]] = {}
        self.instrument_status: dict[str, dict[str, Any]] = {}
        self.clients: set[WebSocket] = set()
        self.subscriber: ZMQSubscriber | None = None
        self._lock = asyncio.Lock()

    def on_reading(self, reading: Reading) -> None:
        """Обработать входящее показание (вызывается из ZMQ callback)."""
        self.total_readings += 1

        data = {
            "timestamp": reading.timestamp.isoformat(),
            "channel": reading.channel,
            "value": reading.value,
            "unit": reading.unit,
            "status": reading.status.value,
        }
        self.last_readings[reading.channel] = data

        # Определить прибор
        inst_id = reading.metadata.get("instrument_id", "")
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
                "total_readings": self.instrument_status.get(inst_id, {}).get(
                    "total_readings", 0
                ) + 1,
            }

    def status_json(self) -> dict[str, Any]:
        """Собрать JSON-статус для GET /status."""
        uptime_s = time.monotonic() - self.start_time
        hours, rem = divmod(int(uptime_s), 3600)
        mins, secs = divmod(rem, 60)
        return {
            "uptime": f"{hours:02d}:{mins:02d}:{secs:02d}",
            "uptime_s": round(uptime_s, 1),
            "total_readings": self.total_readings,
            "channels": len(self.last_readings),
            "instruments": self.instrument_status,
            "active_alarms": self.active_alarms,
            "ws_clients": len(self.clients),
        }


_state = _ServerState()


# ---------------------------------------------------------------------------
# Broadcast к WebSocket-клиентам
# ---------------------------------------------------------------------------

async def _broadcast(data: dict[str, Any]) -> None:
    """Отправить JSON всем подключённым WebSocket-клиентам."""
    if not _state.clients:
        return
    message = json.dumps(data, ensure_ascii=False)
    disconnected: list[WebSocket] = []
    for ws in _state.clients:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        _state.clients.discard(ws)


async def _zmq_to_ws_bridge() -> None:
    """Фоновая задача: получает Reading от ZMQ, рассылает по WebSocket."""
    sub = ZMQSubscriber(callback=_on_reading_callback)
    _state.subscriber = sub
    await sub.start()
    logger.info("ZMQ→WS мост запущен")
    # Задача живёт вечно — остановка через lifespan
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        await sub.stop()


def _on_reading_callback(reading: Reading) -> None:
    """Sync callback от ZMQSubscriber — обновляет состояние и ставит broadcast."""
    _state.on_reading(reading)

    data = {
        "type": "reading",
        "timestamp": reading.timestamp.isoformat(),
        "channel": reading.channel,
        "value": reading.value,
        "unit": reading.unit,
        "status": reading.status.value,
    }
    # Планируем broadcast в event loop
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_broadcast(data))
    except RuntimeError:
        pass


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

    Возвращает словарь: channel → [{"t": iso, "v": float, "u": unit}, ...]
    """
    db_path = _find_recent_db(_DATA_DIR)
    if db_path is None:
        return {}

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    cutoff_epoch = cutoff.timestamp()

    result: dict[str, list[dict[str, Any]]] = {}
    try:
        conn = sqlite3.connect(str(db_path), timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT timestamp, channel, value, unit FROM readings "
                "WHERE timestamp >= ? ORDER BY timestamp ASC",
                (cutoff_epoch,),
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        logger.exception("Ошибка чтения истории из %s", db_path)
        return {}

    for row in rows:
        ch = row["channel"]
        if ch not in result:
            result[ch] = []
        ts = _parse_timestamp(row["timestamp"])
        result[ch].append({
            "t": ts.isoformat(),
            "v": row["value"],
            "u": row["unit"],
        })

    return result


# ---------------------------------------------------------------------------
# FastAPI приложение
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    """Создать и настроить FastAPI-приложение."""
    application = FastAPI(
        title="CryoDAQ Web Dashboard",
        description="Удалённый мониторинг криогенной системы",
        version="0.1.0",
    )

    _zmq_task: asyncio.Task[None] | None = None

    @application.on_event("startup")
    async def _startup() -> None:
        nonlocal _zmq_task
        _zmq_task = asyncio.create_task(_zmq_to_ws_bridge(), name="zmq_ws_bridge")
        logger.info("Веб-сервер CryoDAQ запущен")

    @application.on_event("shutdown")
    async def _shutdown() -> None:
        if _zmq_task and not _zmq_task.done():
            _zmq_task.cancel()
            try:
                await _zmq_task
            except asyncio.CancelledError:
                pass
        logger.info("Веб-сервер CryoDAQ остановлен")

    # Статические файлы
    if _STATIC_DIR.exists():
        application.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @application.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        """Главная страница — HTML-дашборд."""
        index_path = _STATIC_DIR / "index.html"
        if index_path.exists():
            return HTMLResponse(content=index_path.read_text(encoding="utf-8"))
        return HTMLResponse(content="<h1>CryoDAQ</h1><p>index.html не найден</p>")

    @application.get("/status")
    async def status() -> dict[str, Any]:
        """JSON-статус системы."""
        return _state.status_json()

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
        channels = await loop.run_in_executor(None, _query_history, minutes)
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


# Инстанс для uvicorn: `uvicorn cryodaq.web.server:app`
app = create_app()
