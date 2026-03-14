# CHANGELOG.md

Все заметные изменения в проекте CryoDAQ документируются в этом файле.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/).
Проект использует [Semantic Versioning](https://semver.org/lang/ru/).

---

## [0.8.0] — 2026-03-14

### Добавлено
- **Домашняя вкладка «Обзор»** — объединение температур + давления в единый dashboard
  - StatusStrip: safety state, аптайм, алармы, Keithley ON/OFF, cooldown ETA, свободное место на диске
  - 24 компактных карточки температур с трендами (▲▼=) и цветовой индикацией
  - Основной график температур с переключением масштаба [1ч/6ч/24ч], лог/лин
  - Полоса давления с числом и мини-графиком
  - Полоса Keithley (скрыта при SAFE_OFF)
- **Экспорт данных**
  - Кнопки 📷 PNG и 📊 CSV на каждом графике
  - Экспорт Excel (.xlsx) через openpyxl: pivoted time×channel, 2 листа (Данные + Информация)
  - Завершены TODO экспорта CSV и HDF5 в меню Файл (были заглушки)
- **DiskMonitor** — проверка свободного места каждые 5 мин, WARNING <10 GB, CRITICAL <2 GB
- TODO записан: режим калибровки (KRDG + SRDG + эталонный датчик)

### Изменено
- Вкладки «Температуры» и «Давление» удалены — заменены на «Обзор»
- 7 вкладок вместо 8
- `openpyxl>=3.1` добавлен в dependencies

### Статистика
- 94 файла, 21 700+ строк, 194 теста, 7 вкладок

---

## [0.7.0] — 2026-03-14

### Добавлено
- **Cooldown Predictor** — интеграция ensemble-предиктора в engine и GUI
  - `cooldown_predictor.py` — библиотека: dual-channel progress variable, rate-adaptive weighting, LOO validation, quality-gated ingest (~900 строк, без CLI)
  - `cooldown_service.py` — asyncio-сервис: CooldownDetector (IDLE→COOLING→STABILIZING→COMPLETE), периодический predict каждые 30с, автоматический ingest новых кривых
  - GUI: виджет ETA ±CI, progress bar, фаза, пунктирная траектория с CI band на графике вкладки «Аналитика»
  - `config/cooldown.yaml` — конфигурация каналов, детекции, модели
  - CLI: `cryodaq-cooldown build|predict|validate|demo|update`
  - 26 новых тестов (16 предиктор + 10 сервис)

### Статистика
- 89 файлов, 20 100+ строк, 184 теста

---

## [0.6.0] — 2026-03-14

### Добавлено
- **Persistence-first ordering** — архитектурный инвариант безопасности данных
  - SQLiteWriter.write_immediate() — WAL commit через ThreadPoolExecutor, await до завершения
  - Scheduler: пишет в SQLite ПЕРЕД публикацией в DataBroker
  - Гарантия: если данные видны оператору в GUI — они уже на диске
  - 7 новых тестов (ordering, failure, timeout)

### Изменено
- SQLiteWriter больше не подписчик DataBroker — вызывается напрямую из Scheduler
- engine.py: изменён wiring (writer передаётся в Scheduler, не подписывается на broker)

### Статистика
- 81 файл, 16 600+ строк, 158 тестов

---

## [0.5.0] — 2026-03-14

### Добавлено
- **Agent Teams Skill v2** — `.claude/skills/cryodaq-team-lead.md` для Claude Code
  - 6 ролей: Driver, Backend, GUI, Analytics/ML, Test, TSP
  - 4 архитектурных инварианта (crash-safe persistence, SAFE_OFF default, engine/GUI split, no unbounded growth)
  - Spawn prompts с полным контекстом текущего состояния проекта

### Статистика
- 81 файл, 16 600+ строк, 151 тест

---

## [0.4.0] — 2026-03-13

### Добавлено
- **Код-ревью: 13 пунктов** — исправления по результатам аудита
  - CRITICAL: отозван утёкший Telegram bot token
  - Удалён `__del__` из Keithley driver (broken в Python 3.12+)
  - `get_event_loop().create_task()` → `asyncio.create_task()`
  - InterlockCondition: regex pre-compiled в `__post_init__`
  - ZMQCommandServer: handler через конструктор, не `_handler` attr
  - DataBroker.publish(): tuple snapshot iteration
  - SQLiteWriter: dedicated ThreadPoolExecutor(max_workers=1)
  - ChannelManager: удалён singleton, добавлен `get_channel_manager()`
  - `CRYODAQ_ROOT` env var support
  - Notifications YAML парсится один раз
  - `_get_memory_mb()` вынесен на уровень модуля
  - `py.typed` marker
  - 10 новых тестов Keithley driver

### Статистика
- 81 файл, 16 600+ строк, 151 тест

---

## [0.3.0] — 2026-03

### Добавлено
- **SafetyManager** — 6-state machine (SAFE_OFF → READY → RUN_PERMITTED → RUNNING → FAULT_LATCHED → MANUAL_RECOVERY)
  - Fail-on-silence: stale data >10с → FAULT + emergency_off
  - Rate limit: dT/dt >5 K/мин → FAULT
  - Two-step recovery с указанием причины + 60с cooldown
- **SafetyBroker** — выделенный канал безопасности, overflow=FAULT (не drop)
- **Thyracont VSP63D driver** — RS-232, протокол MV00, вакуумметр
- **Serial transport** — async pyserial wrapper
- **Вкладка «Давление»** — лог-шкала, цветовая индикация
- **Вкладка «Теплопроводность»** — выбор цепочки датчиков, R/G, T∞ прогноз
- **Вкладка «Автоизмерение»** — автоматический развёрт по мощности P₁→P₂→…→Pₙ
- **SteadyStatePredictor** — T∞ prediction via scipy curve_fit
- **PeriodicReporter** — matplotlib графики + текстовая сводка в Telegram каждые 30 мин
- **TelegramCommandBot** — /status /temps /pressure /keithley /alarms /help
- **ChannelManager** — централизованные имена и видимость каналов, YAML persistence
- **ConnectionSettingsDialog** — настройка адресов приборов из GUI
- **ChannelEditorDialog** — редактор имён и видимости каналов
- **Launcher** (`cryodaq`) — operator launcher: engine + GUI + system tray, auto-restart
- **Web dashboard** — FastAPI + WebSocket + Chart.js, тёмная тема, GET /status, GET /history
- `config/safety.yaml`, `config/channels.yaml`, `config/*.local.yaml.example`
- `install.bat` — one-click установка на Windows
- `create_shortcut.py` — создание ярлыка на рабочем столе
- `docs/deployment.md` — инструкция развёртывания
- `docs/operator_manual.md` — руководство оператора (русский)

### Статистика
- ~75 файлов, ~14 000 строк, ~120 тестов

---

## [0.2.0] — 2026-02

### Добавлено
- **Keithley 2604B driver** — USB-TMC, TSP/Lua supervisor, heartbeat, emergency_off
- **TSP script** `p_const_single.lua` — P=const feedback loop, watchdog 30с, compliance
- **Вкладка Keithley** — smua/smub: V/I/R/P графики + управление
- **PluginPipeline** — hot-reload .py из plugins/, watchdog filesystem events, error isolation
- **ThermalCalculator plugin** — R_thermal = (T_hot - T_cold) / P
- **CooldownEstimator plugin** — exponential decay fit → cooldown ETA
- **AlarmEngine** — state machine (OK → ACTIVE → ACKNOWLEDGED), hysteresis, severity
- **InterlockEngine** — threshold detection, regex channel matching, cooldown
- **ExperimentManager** — start/stop lifecycle, config snapshot, SQLite persistence
- **TelegramNotifier** — alarm events → Telegram Bot API
- **HDF5Exporter**, **CSVExporter** — экспорт из SQLite
- **ReplaySource** — воспроизведение исторических данных через DataBroker
- **CalibrationStore** (заглушка) — для ГОСТ Р 8.879-2014
- **Вкладка «Аналитика»** — R_thermal plot + cooldown ETA
- `config/interlocks.yaml`, `config/alarms.yaml`, `config/notifications.yaml`

### Статистика
- ~55 файлов, ~8 000 строк, ~80 тестов

---

## [0.1.0] — 2026-01

### Добавлено
- **Начальная архитектура** — двухпроцессная система engine + GUI
- **DataBroker** — fan-out pub/sub, bounded asyncio.Queue, DROP_OLDEST
- **Scheduler** — per-instrument polling, exponential backoff, reconnect
- **SQLiteWriter** — WAL mode, crash-safe, batch insert, daily rotation
- **ZMQ bridge** — PUB/SUB :5555 (msgpack) + REP/REQ (JSON)
- **LakeShore 218S driver** — GPIB, SCPI, KRDG? 0, 8 каналов, 3 прибора = 24 канала
- **GPIB transport** — async pyvisa wrapper
- **USB-TMC transport** — async pyvisa wrapper
- **Вкладка «Температуры»** — 24 ChannelCard + pyqtgraph, ring buffer
- **Вкладка «Алармы»** — severity table, acknowledge
- **Вкладка «Статус приборов»** — per-instrument cards
- Mock mode для всех драйверов
- `config/instruments.yaml`
- `pyproject.toml`, entry points: `cryodaq-engine`, `cryodaq-gui`

### Статистика
- ~35 файлов, ~4 500 строк, ~50 тестов
