# CHANGELOG.md

Все заметные изменения в проекте CryoDAQ документируются в этом файле.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/).
Проект использует [Semantic Versioning](https://semver.org/lang/ru/).

---

## [0.13.0] — 2026-03-21

### Safety & Reliability

**Critical:**
- SafetyManager fault race: `_transition(FAULT_LATCHED)` set synchronously BEFORE `await emergency_off()` — prevents channel start during fault handling
- SQLiteWriter: `executor.shutdown(wait=True)` before `conn.close()` — last batch no longer lost
- `float('inf')` caught by `math.isfinite()` — no more SQLite/JSON crashes

**High:**
- Keithley 2604B: 0.5V/step slew rate limit, compliance detection, `_I_MIN_A` raised to 100nA
- ZMQ heartbeat (3s) + queue overflow handling + REP socket guaranteed reply on CancelledError
- GPIB ResourceManager lifecycle: `close_all_managers()` at engine shutdown
- Engine delegates channel mutations to SafetyManager (`update_target`/`update_limits`)
- Phase detector: `reset()` on configure, LakeShore *IDN? validation, reversible KRDG fallback
- Sensor diagnostics: float timestamp rounding for correlation, safety_manager write-before-mutate

**Medium:**
- Thyracont checksum validation (opt-in), cooldown estimator deque cap, GPIB resource leak fix

### Новые аналитические модули

- **SensorDiagnosticsEngine** — MAD-noise, OLS drift, Pearson correlation, health score 0-100, GUI таблица на вкладке Приборы
- **VacuumTrendPredictor** — 3 модели откачки (exp/power/combined), BIC model selection, ETA, GUI на вкладке Аналитика
- **PhaseDetector** — plugin автоопределения фаз эксперимента (preparation→vacuum→cooldown→measurement→warmup→teardown)

### UI Refactor

- Overview: 3×8 temperature grid, channel editor hot-reload
- "Автоизмерение" merged into "Теплопроводность" (11→10 tabs), QSplitter layout
- Auto-sweep: start/step/count spin boxes, percent_settled stabilization
- Forecast: ML cooldown prediction curve + CI band on Overview chart, conductivity flight recorder CSV
- Archive: QDateEdit calendar popup, operator log author persistence, Keithley units (В/А/Ом/Вт)
- Adaptive liveness timeout, shift status colored icons, Russian calibration policy names
- CSV export with UTF-8 BOM, empty overlays hidden on first reading, prediction filtering (confidence>50%, T>0K)

### Configuration

- `report_enabled: true` for calibration and debug_checkout templates
- Launcher scripts: `start.bat`, `start_mock.bat`, `start.sh`, `start_mock.sh`

---

## [Unreleased]

### Alarm Engine v2

- **RateEstimator** — OLS-based dX/dt оценка скорости изменения (K/мин) с подавлением шума; скользящее окно, get_rate_custom_window
- **ChannelStateTracker** — отслеживание актуального состояния каналов, stale detection, fault history (deque)
- **AlarmEvaluator** — composite (AND/OR), threshold, rate, stale alarm types; deviation_from_setpoint, outside_range, fault_count_in_window checks
- **AlarmStateManager** — dedup, sustained_s, гистерезис, история переходов, acknowledge
- **PhaseProvider / SetpointProvider** — конкретные реализации через ExperimentManager; setpoints из experiment_metadata custom_fields
- **alarm_config.py** — парсинг alarms_v3.yaml; раскрытие channel_group, phase_filter, EngineConfig
- **config/alarms_v3.yaml** — полная конфигурация физических алармов Миллиметрон: vacuum_loss, excessive_cooling, detector_drift, stale, sensor_fault, phase-dependent alarms
- **engine.py** — интеграция v2: DataBroker subscriber для обновления state/rate, периодический alarm_tick с фазовым фильтром, команды alarm_v2_status / alarm_v2_ack
- **GUI alarm panel** — секция "Алармы v2" с цветовыми уровнями, ACK, поллинг каждые 3 с; сигнал v2_alarm_count_changed → overview dashboard indicator
- **config/interlocks.yaml** — удалён undercool_shield (ложное срабатывание при cooldown), detector_warmup переведён на T12

### T1 Features (Web / Telegram / Pre-flight / Auto-fill)

- **Web Dashboard** — FastAPI + self-contained HTML, auto-refresh 5 с, `/api/status`, `/api/log`, `/ws`
- **Telegram Bot v2** — `/log <text>`, `/phase <phase>`, `/temps`; EscalationService (delayed multi-level chain)
- **Pre-Flight Checklist** — диалог перед созданием эксперимента: engine, safety, инструменты, алармы, давление, диск
- **Experiment auto-fill** — UserPreferences, QCompleter на operator/sample/cryostat, автоимя с инкрементом

---

## [0.12.0] — 2026-03-17

Первый полнофункциональный релиз. Calibration v2, фазы экспериментов, смены операторов, автоматическое логирование, автоотчёты, переработанный dashboard.

### Калибровка v2

- **Непрерывный сбор SRDG** — `CalibrationAcquisitionService` автоматически записывает SRDG параллельно с KRDG при калибровочном эксперименте
- **Post-run pipeline** — `CalibrationFitter`: извлечение пар из SQLite, адаптивный downsample, Douglas-Peucker breakpoints, Chebyshev fit
- **Трёхрежимный GUI** — вкладка «Калибровка»: Setup (выбор каналов, импорт) → Acquisition (live stats, coverage bar) → Results (метрики, export)
- **Кнопка запуска** — «Начать калибровочный прогон» прямо на вкладке «Калибровка»
- Удалён legacy `CalibrationSessionStore` и ручной workflow

### Фазы эксперимента

- **ExperimentPhase** — preparation, vacuum, cooldown, measurement, warmup, teardown
- Переход между фазами через `experiment_advance_phase`
- Горизонтальная полоса фаз на вкладке «Эксперимент»

### Смена операторов

- **ShiftBar** — заступление, периодические проверки (2ч), сдача смены
- Все данные смен хранятся через существующий operator log с tags

### Автоматическое логирование

- **EventLogger** — автоматическая запись в журнал: Keithley start/stop/e-off, эксперимент start/finalize/abort, смена фазы
- Авто-записи отображаются серым цветом в журнале

### Автоматический отчёт

- При завершении эксперимента автоматически генерируется отчёт (если шаблон включает report_enabled)

### Горячие клавиши

- Ctrl+L — фокус на быстрый журнал
- Ctrl+E — вкладка «Эксперимент»
- Ctrl+1..9/0 — переключение вкладок
- Ctrl+Shift+X — аварийное отключение Keithley
- F5 — обновление

### Обзор — новый layout

- Двухколоночный layout: графики температуры и давления (связанная ось X)
- Кликабельные карточки температур (toggle видимости на графике)
- DateAxisItem (HH:MM) на всех графиках проекта
- Async ZMQ polling (ZmqCommandWorker) вместо синхронного send_command на таймерах

### Launcher

- Восстановлено меню MainWindow в launcher
- Поддержка `--mock` флага
- Исправлен дубликат tray icon (embedded=True)

### UX

- Все labels на русском (шаблоны, архив, документация)
- Прижатие layout к верху на вкладке «Приборы»
- Empty state overlay на вкладках «Аналитика» и «Теплопроводность»
- Вкладка «Эксперимент» выделена как отдельная вкладка (11 вкладок)

---

## [0.11.0-rc1] — 2026-03-16

### Сверка docs / spec

- Root task/spec/docs сверены с текущим кодом и актуальными продуктовыми решениями.
- Устаревшие ожидания про отключение, скрытие или удаление `smub` явно выведены из актуального контракта; dual-channel Keithley остаётся рабочей моделью.
- Документация по экспериментам переписана вокруг experiment-card lifecycle: одна активная карточка, закрытие по завершении, архивирование при закрытии, новый эксперимент создаёт новую карточку.
- Спецификация главной страницы теперь явно требует режимы `Эксперимент / Отладка`; `Отладка` не должна создавать архивные записи и автоматические отчёты по эксперименту.
- Контракт и реализация внешних отчётов синхронизированы на `report_raw.pdf` и `report_editable.docx`, при этом `report_raw.docx` остаётся machine-generated intermediate source для PDF-конвертации.
- Документация по calibration теперь отражает реализованный контур: `.330` / `.340`, task-level Chebyshev FIT, runtime apply и per-channel policy присутствуют; оставшаяся работа относится к follow-on rollout/polish, а не к отсутствующему core backend.

### Известные caveat'ы после сверки

- Best-effort PDF-конвертация по-прежнему зависит от внешнего `soffice` / `LibreOffice`.
- На новых версиях Python сохраняются `WindowsSelectorEventLoopPolicy` deprecation warnings.

---

## [0.11.0-rc1] — 2026-03-16

### Стабилизация

- **Operator workflow stack completed** — operator log, experiment templates/metadata, report generator MVP, archive browser, calibration backend и calibration GUI интегрированы и покрыты тестами
- **Keithley dual-channel model** — backend, driver и GUI поддерживают `smua`, `smub` и одновременную работу `smua+smub` на одном 2604B
- **GUI contract cleanup** — путь acknowledge для alarms опубликован end-to-end, lowercase safety-state contract исправлен, backend-driven Keithley channel state используется как источник истины для GUI
- **Housekeeping** — добавлены conservative adaptive throttle для non-safety archival writes и retention/compression для старых unlinked daily DB
- **GUI shell/UX passes** — выровнены shared widgets, согласованность вкладок, tray status, archive/report/log и единая обратная связь по статусам и ошибкам
- **Calibration** — реализованы LakeShore SRDG/raw acquisition, calibration session artifacts, multi-zone Chebyshev fit, `.330` / `.340` / JSON / CSV import/export и calibration GUI workflow

### Известные ограничения

- Runtime calibration использует global on/off и per-channel policy с консервативным fallback к `KRDG`.
- PDF для отчётов остаётся best-effort и зависит от внешнего инструмента; гарантированным артефактом остаётся DOCX.
- Python 3.14+ сейчас продолжает выдавать `WindowsSelectorEventLoopPolicy` deprecation warnings.

### Verification

- Required regression matrix: **326 passed**

---

## [0.10.0] — 2026-03-15

### P1 Lab Deployment Fixes (8 defects)

- **P1-01: Async ZMQ** — `zmq_client.py` with persistent socket + `ZmqCommandWorker(QThread)` for non-blocking emergency off; keithley_panel and autosweep share zmq_client
- **P1-02: AutoSweep compliance** — V_comp (default 10V) and I_comp (default 0.1A) spinboxes added; hardcoded 40V/3A removed
- **P1-03: Heartbeat regex** — configurable `keithley_channels` patterns from safety.yaml; checks both freshness AND status (SENSOR_ERROR ≠ fresh)
- **P1-04: Centralized paths** — `paths.py` with `get_data_dir()`; all `Path("data")` replaced (main_window, autosweep, overview, web/server)
- **P1-05: Experiment menu** — dialog with name/operator/sample/description → ZMQ command → ExperimentManager in engine
- **P1-06: Persistent aiohttp** — `_get_session()` + `close()` in TelegramNotifier, TelegramCommandBot, PeriodicReporter
- **P1-07: SQLite REAL timestamp** — new DBs use `REAL` (epoch float); `_parse_timestamp()` handles both REAL and legacy TEXT
- **P1-08: Composite index** — `idx_channel_ts ON readings (channel, timestamp)`

### Статистика
- 236 тестов, ~24 000 строк

---

## [0.9.0] — 2026-03-15

### P0 Critical Fixes (external audit — 5 defects)

- **P0-01: Alarm pipeline end-to-end** — AlarmEngine publishes alarm events (`alarm/{name}`) and `analytics/alarm_count` to DataBroker; filter_fn prevents feedback loops; initial count=0 on start; GUI canonicalizes "activated"→"active"; metadata values are strings (not enums)
- **P0-02: SafetyManager publishes `analytics/safety_state`** — Reading on every transition + initial snapshot (safe_off); data_broker param added to constructor; publish failure doesn't crash safety path
- **P0-03: P/V/I backend limits** — max_power_w=5W, max_voltage_v=40V, max_current_a=1A validated in request_run() BEFORE RUN_PERMITTED; `>` rejects, `==` allows; loaded from safety.yaml source_limits
- **P0-04: emergency_off latched flag** — returns `{latched: true, warning: "..."}` when FAULT_LATCHED (operator knows fault preserved)
- **P0-05: smub cleanup** — tab disabled in GUI, removed from autosweep dropdown, hidden in overview, docs updated

### Статистика
- 96 файлов, 22 700+ строк, 217 тестов

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
- **TSP script** `p_const.lua` — P=const feedback loop for `smua`/`smub`, watchdog 30с, compliance
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
