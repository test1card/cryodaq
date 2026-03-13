# CryoDAQ

Система сбора данных для криогенной лаборатории АКЦ ФИАН (проект «Миллиметрон»).

Замена LabVIEW: полностью на Python 3.12+, asyncio, PySide6.

## Архитектура

Двухпроцессная система: **engine** (headless, asyncio) + **GUI** (PySide6).
Опционально: **web-дашборд** (FastAPI + WebSocket).

```
┌─────────────────────────────────────────────────────────────────────┐
│                         cryodaq-engine                              │
│                                                                     │
│  LakeShore 218S ×3 ──┐                                             │
│  (GPIB, 24 канала)    ├──► Scheduler ──► DataBroker (fan-out)      │
│  Keithley 2604B ×1 ──┘    (backoff)      │  │  │  │  │            │
│  (USB-TMC, TSP/Lua)                      │  │  │  │  │            │
│                                          │  │  │  │  │            │
│                          SQLiteWriter ◄──┘  │  │  │  │            │
│                          (WAL, daily)       │  │  │  │            │
│                          ZMQPublisher ◄─────┘  │  │  │            │
│                          (PUB :5555)           │  │  │            │
│                          AlarmEngine ◄─────────┘  │  │            │
│                          (гистерезис, Telegram)   │  │            │
│                          InterlockEngine ◄────────┘  │            │
│                          (emergency_off)             │            │
│                          PluginPipeline ◄────────────┘            │
│                          (hot-reload)                              │
└─────────────────────────────────────────────────────────────────────┘
          │ ZMQ PUB/SUB (msgpack)
          ▼
┌──────────────────────┐  ┌──────────────────────┐
│    cryodaq-gui       │  │  web-дашборд         │
│    (PySide6)         │  │  (FastAPI + WS)      │
│                      │  │                      │
│  Температуры (24ch)  │  │  GET /status (JSON)  │
│  Keithley (V/I/R/P)  │  │  WebSocket /ws       │
│  Алармы (таблица)    │  │  Авто-обновление     │
│  Статус приборов     │  │                      │
│  Экспорт CSV/HDF5   │  │                      │
└──────────────────────┘  └──────────────────────┘
```

## Быстрый старт

```bash
# Установка
git clone https://github.com/test1card/cryodaq.git
cd cryodaq
pip install -e ".[dev]"          # основные + dev зависимости
pip install -e ".[web]"          # + FastAPI/uvicorn для web-дашборда

# Запуск engine (имитация приборов)
cryodaq-engine --mock

# Запуск GUI (в другом терминале)
cryodaq-gui

# Запуск web-дашборда (в третьем терминале)
uvicorn cryodaq.web.server:app --host 0.0.0.0 --port 8080

# Тесты
pytest tests/ -v                 # 118 тестов
ruff check src/ tests/           # линтинг
ruff format src/ tests/          # форматирование
```

## Приборы

| Прибор | Интерфейс | Каналы | Описание |
|--------|-----------|--------|----------|
| LakeShore 218S ×3 | GPIB | 24 температуры (K) | Кремниевые диоды DT-670B1-CU |
| Keithley 2604B ×1 | USB-TMC | V, I, R, P (smua) | TSP/Lua, P=const, watchdog 30s |
| Вакуумметр | TBD | — | Планируется |

## Структура проекта

```
src/cryodaq/
├── engine.py                — точка входа engine (headless)
├── core/
│   ├── broker.py            — DataBroker: fan-out pub/sub
│   ├── scheduler.py         — планировщик опроса приборов
│   ├── alarm.py             — AlarmEngine: пороги + гистерезис
│   ├── interlock.py         — InterlockEngine: аварийная защита
│   ├── experiment.py        — ExperimentManager: жизненный цикл
│   └── zmq_bridge.py        — ZMQ PUB/SUB (msgpack)
├── drivers/
│   ├── base.py              — Reading + InstrumentDriver ABC
│   ├── instruments/
│   │   ├── lakeshore_218s.py — LakeShore 218S (SCPI, KRDG? 0)
│   │   └── keithley_2604b.py — Keithley 2604B (TSP/Lua)
│   └── transport/
│       ├── gpib.py          — async pyvisa (GPIB)
│       └── usbtmc.py        — async pyvisa (USB-TMC)
├── storage/
│   ├── sqlite_writer.py     — SQLite WAL, daily rotation
│   ├── hdf5_export.py       — экспорт в HDF5
│   ├── csv_export.py        — экспорт в CSV
│   └── replay.py            — воспроизведение данных
├── analytics/
│   ├── base_plugin.py       — AnalyticsPlugin ABC
│   ├── plugin_loader.py     — PluginPipeline (hot-reload)
│   └── calibration.py       — CalibrationStore (заглушка)
├── gui/
│   ├── app.py               — точка входа GUI
│   ├── main_window.py       — MainWindow (вкладки, меню)
│   └── widgets/
│       ├── temp_panel.py    — 24 канала + pyqtgraph
│       ├── alarm_panel.py   — таблица тревог
│       └── instrument_status.py — статус приборов
├── web/
│   ├── server.py            — FastAPI + WebSocket
│   └── static/index.html    — SPA-дашборд
└── notifications/
    └── telegram.py          — Telegram Bot API

plugins/
├── thermal_calculator.py    — R_thermal = ΔT / P
└── cooldown_estimator.py    — ETA охлаждения (exp fit)

config/
├── instruments.yaml         — конфигурация приборов
├── interlocks.yaml          — аварийные блокировки
├── alarms.yaml              — пороги тревог
└── notifications.yaml       — Telegram бот
```

## Ключевые правила

- Engine работает неделями без перезапуска. Нет утечек памяти. Нет неограниченных буферов.
- GUI — отдельный процесс. Можно закрыть/открыть без потери данных.
- Keithley TSP: обязателен watchdog → source OFF.
- Никакого блокирующего I/O в engine (pyvisa через run_in_executor).
- Интерфейс оператора на русском языке.
- Каждый драйвер: async, mock-режим, timeout+retry, Reading dataclass.
- `disconnect()` Keithley **всегда** вызывает `emergency_off()` первым.

## Стандарты

- Калибровка по ГОСТ Р 8.879-2014
- Кремниевые диоды DT-670B1-CU, индивидуальные кривые на каждый датчик

## Статус проекта

- **10 600+** строк Python, **61** файл
- **118** тестов (pytest, все проходят)
- Engine работает в mock-режиме (4 прибора, 28 каналов)
- GUI: температуры, алармы, статус приборов
- Web-дашборд: реальное время через WebSocket
- Экспорт: SQLite → CSV, HDF5
- Уведомления: Telegram Bot API
