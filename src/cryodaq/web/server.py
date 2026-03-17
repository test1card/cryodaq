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
        version="0.12.0",
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
        """Главная страница — self-contained HTML dashboard."""
        return HTMLResponse(content=_DASHBOARD_HTML)

    @application.get("/status")
    async def status() -> dict[str, Any]:
        """JSON-статус системы."""
        return _state.status_json()

    @application.get("/api/status")
    async def api_status() -> dict[str, Any]:
        """Полный JSON-статус: readings + experiment + shift."""
        base = _state.status_json()
        base["readings"] = _state.last_readings
        # Experiment/shift data via ZMQ command (sync, ok for web server)
        try:
            from cryodaq.gui.zmq_client import send_command
            exp = send_command({"cmd": "experiment_status"})
            base["experiment"] = exp if exp.get("ok") else None
        except Exception:
            base["experiment"] = None
        return base

    @application.get("/api/log")
    async def api_log(limit: int = 10) -> dict[str, Any]:
        """Последние записи журнала."""
        try:
            from cryodaq.gui.zmq_client import send_command
            result = send_command({"cmd": "log_get", "limit": limit})
            if result.get("ok"):
                return {"ok": True, "entries": result.get("entries", [])}
        except Exception:
            pass
        return {"ok": False, "entries": []}

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


_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CryoDAQ Monitor</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0d1117;color:#c9d1d9;font-family:system-ui,-apple-system,sans-serif;padding:8px}
.header{display:flex;justify-content:space-between;align-items:center;padding:8px 12px;background:#161b22;border:1px solid #30363d;border-radius:6px;margin-bottom:8px}
.header h1{font-size:16px;color:#f0f6fc}
.header .ver{color:#8b949e;font-size:12px}
.status-bar{display:flex;gap:16px;padding:8px 12px;background:#161b22;border:1px solid #30363d;border-radius:6px;margin-bottom:8px;flex-wrap:wrap}
.status-bar .item{font-size:13px}
.section{background:#161b22;border:1px solid #30363d;border-radius:6px;padding:10px 12px;margin-bottom:8px}
.section-title{font-size:12px;color:#8b949e;margin-bottom:6px;text-transform:uppercase}
.temps{display:grid;grid-template-columns:repeat(8,1fr);gap:4px}
@media(max-width:600px){.temps{grid-template-columns:repeat(4,1fr)}}
.temp-card{background:#21262d;border-radius:4px;padding:4px 6px;text-align:center}
.temp-card .name{font-size:10px;color:#8b949e}
.temp-card .val{font-size:16px;font-weight:bold}
.cold{color:#58a6ff} .mid{color:#c9d1d9} .warm{color:#f0883e} .hot{color:#f85149}
.log-entry{font-size:12px;color:#8b949e;padding:2px 0;border-bottom:1px solid #21262d}
.log-entry .ts{color:#58a6ff}
#updated{font-size:11px;color:#484f58;text-align:right;padding:4px}
</style>
</head>
<body>
<div class="header"><h1>CryoDAQ Monitor</h1><span class="ver">v0.12.0</span></div>
<div class="status-bar">
 <span class="item" id="safety">SAFE_OFF</span>
 <span class="item" id="uptime">Аптайм: --:--:--</span>
 <span class="item" id="alarms">0 алармов</span>
 <span class="item" id="channels">0 каналов</span>
</div>
<div class="section"><div class="section-title">Эксперимент</div><div id="experiment">—</div></div>
<div class="section"><div class="section-title">Температуры</div><div class="temps" id="temps"></div></div>
<div class="section"><div class="section-title">Давление</div><div id="pressure">—</div></div>
<div class="section"><div class="section-title">Keithley</div><div id="keithley">—</div></div>
<div class="section"><div class="section-title">Журнал</div><div id="log"></div></div>
<div id="updated"></div>
<script>
function tempColor(v){if(v<10)return'cold';if(v<100)return'mid';if(v<250)return'warm';return'hot'}
async function refresh(){
 try{
  const r=await fetch('/api/status');const d=await r.json();
  document.getElementById('uptime').textContent='Аптайм: '+(d.uptime||'--');
  document.getElementById('channels').textContent=(d.channels||0)+' каналов';
  // Readings
  const readings=d.readings||{};
  let temps='',pressure='—',kA='ВЫКЛ',kB='ВЫКЛ';
  const sorted=Object.entries(readings).sort((a,b)=>a[0].localeCompare(b[0]));
  for(const[ch,r]of sorted){
   if(r.unit==='K'&&ch.match(/^\\u0422|^T/)){
    const c=tempColor(r.value);
    temps+=`<div class="temp-card"><div class="name">${ch.split(' ')[0]}</div><div class="val ${c}">${r.value.toFixed(2)}</div></div>`;
   }
   if(r.unit==='mbar')pressure=r.value.toExponential(2)+' mbar';
   if(ch.includes('/smua/'))kA=ch.endsWith('power')?'ВКЛ '+r.value.toFixed(1)+'W':kA;
   if(ch.includes('/smub/'))kB=ch.endsWith('power')?'ВКЛ '+r.value.toFixed(1)+'W':kB;
  }
  document.getElementById('temps').innerHTML=temps||'Нет данных';
  document.getElementById('pressure').textContent=pressure;
  document.getElementById('keithley').textContent='A: '+kA+' │ B: '+kB;
  // Experiment
  const exp=d.experiment;
  if(exp&&exp.active_experiment){
   const e=exp.active_experiment;
   const phase=exp.current_phase?' ['+exp.current_phase+']':'';
   document.getElementById('experiment').textContent=(e.name||'—')+phase;
  }else{document.getElementById('experiment').textContent='Нет активного эксперимента'}
 }catch(e){document.getElementById('updated').textContent='Ошибка: '+e.message}
 // Log
 try{
  const lr=await fetch('/api/log?limit=5');const ld=await lr.json();
  let html='';
  for(const e of(ld.entries||[])){
   const ts=(e.timestamp||'').split('T')[1]||'';
   html+=`<div class="log-entry"><span class="ts">${ts.substring(0,8)}</span> [${e.author||e.source||'?'}] ${e.message||''}</div>`;
  }
  document.getElementById('log').innerHTML=html||'Нет записей';
 }catch(e){}
 document.getElementById('updated').textContent='Обновлено: '+new Date().toLocaleTimeString();
}
refresh();setInterval(refresh,5000);
</script>
</body>
</html>"""

# Инстанс для uvicorn: `uvicorn cryodaq.web.server:app`
app = create_app()
