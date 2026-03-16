# CryoDAQ

Система сбора данных для криогенной лаборатории АКЦ ФИАН (проект «Миллиметрон»).

Замена LabVIEW: полностью на Python 3.12+, asyncio, PySide6.

## Архитектура

```
┌──────────────────────────────────────────────────────────────────────────┐
│                           cryodaq-engine                                 │
│                                                                          │
│  LakeShore 218S ×3 ──┐                                                  │
│  (GPIB, 24 канала)    │                                                  │
│  Keithley 2604B ×1 ───┤──► Scheduler ──► DataBroker ──► SQLiteWriter    │
│  (USB-TMC, smua + smub) │    (backoff)  │               ──► ZMQPublisher  │
│  Thyracont VSP63D ×1 ─┘              │               ──► AlarmEngine   │
│  (RS-232, вакуум)                     │               ──► PluginPipeline│
│                                       │                                  │
│                                       └──► SafetyBroker ──► SafetyManager│
│                                            (fail-on-silence)   (SAFE_OFF │
│                                                                 → READY  │
│  ZMQCommandServer ◄──── GUI команды ◄──── SafetyManager        → RUNNING│
│  (REP :5556)           (start/stop)       (единая точка        → FAULT) │
│                                            управления)                   │
│  InterlockEngine ──────► SafetyManager (делегирование действий)          │
└──────────────────────────────────────────────────────────────────────────┘
          │ ZMQ PUB/SUB (msgpack, :5555)
          ▼
┌──────────────────────┐  ┌──────────────────────┐  ┌──────────────────┐
│  cryodaq (лаунчер)   │  │  cryodaq-gui         │  │ web-дашборд      │
│  Engine + GUI + tray  │  │  (PySide6)           │  │ (FastAPI + WS)   │
│                      │  │                      │  │                  │
│  8 вкладок:          │  │  Температуры (24ch)  │  │ Chart.js графики │
│  Температуры         │  │  Keithley (smua/smub)│  │ GET /status      │
│  Keithley (контроль) │  │  Давление (лог.)     │  │ GET /history     │
│  Давление            │  │  Аналитика (R, ETA)  │  │ WebSocket /ws    │
│  Аналитика           │  │  Теплопроводность    │  │ Тёмная тема      │
│  Теплопроводность    │  │  Автоизмерение       │  │ Алармы, приборы  │
│  Автоизмерение       │  │  Алармы              │  │                  │
│  Алармы              │  │  Статус приборов     │  │                  │
│  Статус приборов     │  │                      │  │                  │
└──────────────────────┘  └──────────────────────┘  └──────────────────┘
```

## Система безопасности

**Безопасное состояние (нагреватель ВЫКЛЮЧЕН) — это DEFAULT.**

SafetyManager — единая точка управления источником тока:
- `SAFE_OFF` → `READY` → `RUNNING` → `FAULT_LATCHED` → восстановление
- Нет данных 10 секунд → авария + аварийное отключение (fail-on-silence)
- Двойная защита: SafetyManager (Python) + TSP watchdog (аппаратный, 30с)
- Восстановление: подтверждение с причиной + 60с ожидание + проверка предусловий

## Быстрый старт

```bash
# Установка (или запустите install.bat на Windows)
git clone https://github.com/test1card/cryodaq.git
cd cryodaq
pip install -e ".[dev,web]"

# Запуск для оператора (engine + GUI в одном окне, иконка в трее)
cryodaq

# Или по отдельности:
cryodaq-engine --mock            # engine с имитацией 5 приборов
cryodaq-gui                      # GUI (в другом терминале)
uvicorn cryodaq.web.server:app --host 0.0.0.0 --port 8080  # web

# Тесты
cryodaq-cooldown build --data cooldown_v5/ --output model/  # модель cooldown
pytest tests/ -v                 # 328 collected, 327 passed, 1 skipped
ruff check src/ tests/           # линтинг
```

## Развёртывание на лабораторном ПК

```bash
# 1. Клонировать и установить
git clone https://github.com/test1card/cryodaq.git
cd cryodaq
install.bat                      # или: pip install -e ".[dev,web]"

# 2. Настроить приборы (адреса COM/GPIB/USB)
copy config\instruments.local.yaml.example config\instruments.local.yaml
# Отредактировать instruments.local.yaml

# 3. Настроить Telegram (опционально)
copy config\notifications.local.yaml.example config\notifications.local.yaml
# Указать bot_token и chat_id

# 4. Запустить
cryodaq                          # или дважды кликнуть по ярлыку CryoDAQ
```

Подробнее: [docs/deployment.md](docs/deployment.md) | [docs/operator_manual.md](docs/operator_manual.md)

## Приборы

| Прибор | Интерфейс | Каналы | Описание |
|--------|-----------|--------|----------|
| LakeShore 218S ×3 | GPIB | 24 температуры (K) | Кремниевые диоды DT-670B1-CU |
| Keithley 2604B ×1 | USB-TMC | V, I, R, P по smua и smub | TSP/Lua, dual-channel runtime, watchdog 30s |
| Thyracont VSP63D ×1 | RS-232 | давление (мбар) | Протокол MV00, 1e-6…1e3 мбар |

## Функции GUI (10 вкладок)

| Вкладка | Описание |
|---------|----------|
| **Обзор** | Домашняя: строка состояния (safety/аптайм/алармы/Keithley/cooldown/диск), 24 карточки температур с трендами (▲▼=), график ([1ч/6ч/24ч], лог/лин, 📷PNG/📊CSV), полоса давления, dual-channel Keithley strip |
| Keithley | smua + smub: независимые 4 графика (V/I/R/P) и управление по обоим каналам, включая A+B |
| Аналитика | R_thermal (К/Вт) + прогноз охлаждения: ETA ±CI, progress bar, фаза, пунктир траектории с CI-band, автодетекция cooldown |
| Теплопроводность | Выбор цепочки датчиков → R, G, T∞ прогноз, «Стабильно» индикатор |
| Автоизмерение | Автоматический развёрт по мощности: P₁→P₂→…→Pₙ, стабилизация, CSV+PNG |
| Алармы | Таблица тревог по severity, подтверждение оператором |
| Журнал оператора | Ручные заметки оператора с привязкой к текущему эксперименту |
| Архив | Поиск по экспериментам, открытие артефактов и пересборка отчёта |
| Калибровка | Запись calibration session, fit multi-zone curves, экспорт JSON/CSV |
| Статус приборов | Карточки: подключён/отключён, счётчик показаний/ошибок |

**Меню:** Файл (экспорт CSV / HDF5 / Excel) | Эксперимент (начать/остановить) | Настройки (редактор каналов, подключение приборов)

## Telegram-бот

| Команда | Описание |
|---------|----------|
| /status | Аптайм, приборы, активные тревоги |
| /temps | Таблица всех температур |
| /pressure | Уровень вакуума |
| /keithley | V, I, R, P по каналам |
| /alarms | Активные тревоги |
| /help | Список команд |

Периодические отчёты: PNG-график + текстовая сводка каждые 30 мин.

## Структура проекта

```
src/cryodaq/
├── engine.py                    — engine (headless)
├── launcher.py                  — оператор-лаунчер (engine + GUI + tray)
├── core/
│   ├── safety_manager.py        — SafetyManager: 6 состояний, fail-on-silence
│   ├── safety_broker.py         — SafetyBroker: выделенный канал безопасности
│   ├── broker.py                — DataBroker: fan-out pub/sub
│   ├── scheduler.py             — планировщик опроса приборов
│   ├── alarm.py                 — AlarmEngine: пороги + гистерезис
│   ├── interlock.py             — InterlockEngine → SafetyManager
│   ├── experiment.py            — ExperimentManager
│   ├── zmq_bridge.py            — ZMQ PUB/SUB + CommandServer
│   ├── channel_manager.py       — имена и видимость каналов
│   └── disk_monitor.py          — мониторинг диска (shutil.disk_usage)
├── drivers/
│   ├── base.py                  — Reading + InstrumentDriver ABC
│   ├── instruments/
│   │   ├── lakeshore_218s.py    — LakeShore 218S (SCPI)
│   │   ├── keithley_2604b.py    — Keithley 2604B (TSP/Lua)
│   │   └── thyracont_vsp63d.py  — Thyracont VSP63D (RS-232)
│   └── transport/
│       ├── gpib.py              — async pyvisa (GPIB)
│       ├── usbtmc.py            — async pyvisa (USB-TMC)
│       └── serial.py            — async pyserial (RS-232)
├── storage/
│   ├── sqlite_writer.py         — SQLite WAL, daily rotation
│   ├── hdf5_export.py           — экспорт в HDF5
│   ├── csv_export.py            — экспорт в CSV
│   ├── xlsx_export.py           — экспорт в Excel (openpyxl)
│   └── replay.py                — воспроизведение данных
├── analytics/
│   ├── base_plugin.py           — AnalyticsPlugin ABC
│   ├── plugin_loader.py         — PluginPipeline (hot-reload)
│   ├── steady_state.py          — T∞ прогноз (scipy curve_fit)
│   ├── cooldown_predictor.py    — ensemble predictor (dual-channel, ~900 строк)
│   ├── cooldown_service.py      — CooldownService (автодетекция, predict, auto-ingest)
│   └── calibration.py           — CalibrationSessionStore + CalibrationStore (SRDG capture, fit, import/export)
├── reporting/
│   ├── generator.py             — template-driven DOCX report generator
│   ├── data.py                  — извлечение данных для отчётов из SQLite/artifacts
│   └── sections.py              — modular report sections registry
├── gui/
│   ├── app.py                   — standalone GUI
│   ├── main_window.py           — MainWindow (7 вкладок, 3 меню)
│   └── widgets/
│       ├── overview_panel.py    — домашняя вкладка «Обзор» (объединение T + P + статус)
│       ├── keithley_panel.py    — dual-channel smua/smub + backend-driven status
│       ├── operator_log_panel.py — журнал оператора
│       ├── archive_panel.py     — архив экспериментов и отчётов
│       ├── calibration_panel.py — GUI калибровки датчиков
│       ├── experiment_dialogs.py — запуск/завершение template-based experiment
│       └── common.py            — общие UI helpers/status banners
│       ├── analytics_panel.py   — R_thermal + ETA + cooldown predictor
│       ├── conductivity_panel.py — цепочка R/G + T∞
│       ├── autosweep_panel.py   — автоизмерение по мощности
│       ├── alarm_panel.py       — таблица тревог
│       ├── instrument_status.py — статус приборов
│       ├── channel_editor.py    — редактор каналов
│       └── connection_settings.py — подключение приборов
├── web/
│   ├── server.py                — FastAPI + WebSocket + /history
│   └── static/index.html        — Chart.js дашборд
├── notifications/
│   ├── telegram.py              — Telegram алармы
│   ├── telegram_commands.py     — Telegram бот-команды
│   └── periodic_report.py       — отчёты с графиками
└── tools/
    └── cooldown_cli.py          — CLI: cryodaq-cooldown build/predict/validate

plugins/                         — hot-reloadable аналитика
├── thermal_calculator.py        — R_thermal = ΔT / P
└── cooldown_estimator.py        — ETA охлаждения

config/
├── instruments.yaml             — приборы (шаблон)
├── interlocks.yaml              — аварийные блокировки
├── alarms.yaml                  — пороги тревог
├── safety.yaml                  — SafetyManager
├── channels.yaml                — имена и видимость каналов
├── experiment_templates/        — YAML templates экспериментов
├── housekeeping.yaml            — adaptive throttle + retention/compression policy
├── notifications.yaml           — Telegram (шаблон, без токена!)
├── cooldown.yaml                — CooldownService (каналы, детекция, auto-ingest)
├── *.local.yaml.example         — шаблоны для машино-специфичных настроек
└── *.local.yaml                 — машино-специфичные (gitignored)

docs/
├── architecture.md              — архитектура системы
├── operator_manual.md           — руководство оператора (русский)
└── deployment.md                — развёртывание на новом ПК

tests/                           — 328 collected tests
├── core/                        — broker, alarm, interlock, safety, scheduler, zmq, experiment, persistence, disk_monitor
├── drivers/                     — lakeshore, keithley, thyracont
├── analytics/                   — thermal, cooldown_estimator, cooldown_predictor, cooldown_service, plugins
├── storage/                     — hdf5, csv, xlsx, replay
└── notifications/               — telegram
```

## Ключевые правила

- **SAFE_OFF — это DEFAULT.** Нагреватель включён только при непрерывном подтверждении здоровья.
- Engine работает неделями. Нет утечек памяти. Нет неограниченных буферов.
- GUI — отдельный процесс. Можно закрыть/открыть без потери данных.
- Keithley TSP: watchdog → source OFF. Нет `__del__`.
- Никакого блокирующего I/O в engine.
- Интерфейс оператора на русском языке.
- Telegram токен НИКОГДА не коммитится.

## Workflow additions

- **Журнал оператора** — SQLite-persistent operator notes, GUI entry, command path `log_entry/log_get`
- **Шаблоны экспериментов** — YAML templates, artifact folders, metadata.json, retroactive experiment creation
- **Отчёты (MVP)** — template-driven DOCX report generator with modular sections; PDF conversion best-effort
- **Архив экспериментов** — GUI archive browser, filters, artifact open, report regenerate
- **Калибровка** — SRDG/raw acquisition path, calibration sessions, multi-zone Chebyshev fit, GUI workflow
- **Housekeeping** — conservative adaptive throttle for non-safety archival writes and retention/compression for unlinked daily DBs

## Известные ограничения (RC freeze)

- **Calibration apply path** в runtime пока не реализован. GUI честно держит `Применить в CryoDAQ` disabled.
- **PDF export** для отчётов остаётся best-effort: DOCX является обязательным артефактом, PDF зависит от доступного внешнего конвертера.
- **Windows event loop policy** даёт 2 известных `DeprecationWarning` на Python 3.14+; это не блокирует текущий RC, но требует отдельного обновления до Python 3.16.
- **Keithley command failure UX** в `KeithleyPanel` пока в основном уходит в логирование, а не в operator-facing inline feedback.

## Статус проекта

| Метрика | Значение |
|---------|----------|
| Python-файлов | **96** |
| Строк Python | **22 700+** |
| Тестов | **328 collected / 327 passed / 1 skipped** |
| Приборов (mock) | **5** (3× LakeShore + Keithley + Thyracont) |
| Каналов данных | **29+** (24 температуры + Keithley dual-channel telemetry + давление + analytics/alarm channels) |
| GUI вкладок | **10** |
| Telegram команд | **6** |
| Коммитов | **42** |

## Стандарты

- Калибровка по ГОСТ Р 8.879-2014
- Кремниевые диоды DT-670B1-CU, индивидуальные кривые на каждый датчик
