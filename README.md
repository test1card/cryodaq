# CryoDAQ

Стек сбора данных, управления и анализа для криогенной лаборатории.
Заменяет 3-летний LabVIEW VI, управлявший приборами и отправлявший email-алерты.
Добавлено: скриптовые FSM-кампании, автоматическая калибровка с мульти-форматным
экспортом, автогенерация DOCX-отчётов, ролевые Telegram-алерты, детекция аномалий
датчиков с аларм-конвейером, plugin-аналитика, регрессионный тест-сьют (~2 019 тестов).

Разработано для АКЦ ФИАН (проект Millimetron).

## Статус

- **Последний релиз:** v0.44.0 (2026-05-01)
- **Master:** `184d461`
- **Тесты:** ~2 019 passing
- **Производственный статус:** stable; LabVIEW VI полностью заменён

## Архитектура

Три runtime-процесса:

- `cryodaq-engine` — headless asyncio runtime. Управляет приборами, запускает
  safety manager FSM, оценивает аларм-правила и interlocks, сохраняет данные,
  обслуживает команды GUI через ZMQ.
- `cryodaq-gui` — Qt desktop-клиент. Подключается через ZMQ; перезапускается
  без остановки сбора данных.
- `cryodaq.web.server:app` — опциональный FastAPI monitoring-дашборд.

Плюс Windows-лончер: `cryodaq`.

Поток данных:

```
Instrument → Driver → Scheduler → SQLiteWriter → DataBroker → {GUI, SafetyBroker,
                                                                Telegram, Analytics}
```

IPC: ZeroMQ PUB/SUB `:5555` (msgpack) + REP/REQ `:5556` (JSON-команды).

## Поддерживаемые приборы

- 3× LakeShore 218S (GPIB) — 24 температурных канала
- Keithley 2604B (USB-TMC) — двухканальный SMU (`smua` + `smub`)
- Thyracont VSP63D (RS-232) — 1 канал давления

## Реализованные рабочие процессы

Полностью функциональны в v0.44.0:

- **Эксперимент FSM:** 6-фазный жизненный цикл (idle → cooldown → measurement →
  warmup → disassembly → idle, плюс aborted). Шаблонные скриптовые прогоны.
- **Калибровка v2:** непрерывная запись SRDG во время калибровочных экспериментов;
  постобработка (extract → downsample → Chebyshev fit по зонам); экспорт в
  `.cof` (сырые коэффициенты) / `.340` / JSON / CSV; импорт из `.340` / JSON;
  runtime-применение с глобальной / поканальной политикой.
- **Автогенерация отчётов:** секции по шаблону; гарантированный `report_editable.docx`;
  PDF best-effort через `soffice` / LibreOffice.
- **Telegram-алерты:** ролевая фильтрация. Операторы получают полный аларм-поток;
  менеджеры — курированное подмножество с on-demand запросами через бот-команды.
- **Диагностика датчиков → аларм-конвейер:** MAD-outlier + кросс-канальное
  обнаружение дрейфа корреляций. Устойчивая аномалия публикует аларм: warning
  через 5 мин, critical через 15 мин, auto-clear при восстановлении. Одновременные
  события объединяются в одно Telegram-сообщение; конфигурируемый cooldown.
- **Аларм-движок v2:** threshold / rate / composite / phase-dependent правила;
  гистерезисный deadband; повышение severity на месте (WARNING→CRITICAL);
  ack/clear publish-путь.
- **Interlocks:** 3 правила жёсткой защиты (криостат / компрессор / детектор).
  Срабатывание → `emergency_off` + переход в TRIPPED. Оператор подтверждает
  через `interlock_acknowledge` ZMQ-команду без перезапуска.
- **Оператор-лог:** SQLite-backed; доступ через GUI + ZMQ.
- **Шаблоны экспериментов, lifecycle-метаданные, архивация артефактов:** каталог
  `data/experiments/<id>/` с `metadata.json`, `reports/`, опциональный Parquet-архив.
- **Plugin-архитектура:** ABC-изоляция; сбои callback помечают плагин degraded
  без краша engine.
- **Housekeeping:** адаптивный throttle + retention + compression.
- **Cold-storage rotation (F17):** ежедневные SQLite-файлы старше 30 дней
  автоматически ротируются в Parquet/Zstd. `ArchiveReader` прозрачно читает
  оба источника по UTC-дням.
- **Оценка утечки (F13):** `LeakRateEstimator` — скользящее окно, OLS-регрессия
  без numpy, история в `data/leak_rate_history.json`. Команды: `leak_rate_start` /
  `leak_rate_stop` (ZMQ). Требует: `chamber.volume_l` в `instruments.local.yaml`.

## GUI

Основной: `MainWindowV2` — Phase III завершена в v0.40.0.

Компоновка — ambient information radiator для недельных экспериментов:

- **TopWatchBar** — индикатор engine, статус эксперимента, эхо временно́го окна
- **ToolRail** — навигация по overlay-панелям
- **DashboardView** — 5 live-зон:
  1. Сетка датчиков (температура + давление, обзор)
  2. График температуры (мульти-канал, кликабельная легенда, выбор окна)
  3. График давления (компактный log-Y)
  4. Phase widget (индикатор фазы эксперимента + переход)
  5. Quick log (inline-просмотр оператор-лога)
- **BottomStatusBar** — индикатор safety state
- **OverlayContainer** — хост для аналитики и архива

Overlay-панели (из ToolRail):

- Аналитика — phase-aware виджеты: W1 траектория температур, W2 история
  охлаждений, W3 сводка эксперимента (статистика каналов, топ-аларм, ссылки
  на артефакты). W4 R_thermal — placeholder до F8 (cooldown ML).
- Архив — прошлые эксперименты + отчёты + Parquet-экспорты
- Калибровка — рабочий процесс capture / fit / export
- Оператор-лог
- Другие overlay по иконкам ToolRail

Легаси `MainWindow` (10-вкладок) остаётся как **постоянный fallback**. Операторы
видят только `MainWindowV2`. Phase III закрыла активный план миграции.

Системный трей: `healthy / warning / fault`. `healthy` не отображается без
достаточного backend-подтверждения. `fault` — при неснятых алармах или
safety-state `fault` / `fault_latched`.

## Установка

### Требования

- Windows 10/11 или Linux
- Python `>=3.12`
- Git
- VISA backend / драйверы приборов по необходимости

### Установка

```bash
pip install -e ".[dev,web]"
```

Минимальная runtime-установка:

```bash
pip install -e .
```

Поддерживаемый workflow: установка из корня репозитория в активный venv.
Запуск `pytest` без `pip install -e ...` не поддерживается.

Ключевые runtime-зависимости: `PySide6`, `pyqtgraph`, `pyvisa`, `pyserial-asyncio`,
`pyzmq`, `python-docx`, `scipy`, `matplotlib`, `openpyxl`, `pyarrow`.

## Запуск

```bash
cryodaq-engine        # headless engine (реальные приборы)
cryodaq-gui           # только GUI (подключается к работающему engine)
cryodaq               # Windows оператор-лончер
cryodaq-engine --mock # mock-режим (симулированные приборы)
uvicorn cryodaq.web.server:app --host 0.0.0.0 --port 8080  # опциональный web
```

## Конфигурация

Активные конфигурационные файлы на v0.44.0:

- `config/instruments.yaml` — GPIB/serial/USB адреса, каналы LakeShore,
  `chamber.volume_l` для F13 leak rate
- `config/instruments.local.yaml` — машино-специфические переопределения (gitignored)
- `config/safety.yaml` — таймауты FSM, rate limits, drain timeout
- `config/alarms.yaml` — legacy определения алармов
- `config/alarms_v3.yaml` — правила аларм-движка v2 (threshold/rate/composite/phase)
- `config/interlocks.yaml` — условия interlocks + действия
- `config/channels.yaml` — отображаемые имена, видимость, группировка
- `config/notifications.yaml` — Telegram bot_token, chat_ids, escalation
- `config/housekeeping.yaml` — throttle, retention, compression, `cold_rotation`
- `config/plugins.yaml` — sensor_diagnostics + vacuum_trend; `aggregation_threshold` + `escalation_cooldown_s`
- `config/cooldown.yaml` — параметры cooldown predictor
- `config/shifts.yaml` — определения смен (GUI)
- `config/experiment_templates/*.yaml` — шаблоны типов экспериментов

`*.local.yaml` переопределяют базовые файлы для машино-специфических настроек.

## Артефакты экспериментов

```text
data/experiments/<experiment_id>/
  metadata.json
  reports/
    report_editable.docx
    report_raw.pdf      # опционально, best-effort (soffice/LibreOffice)
    report_raw.docx
    assets/
data/calibration/sessions/<session_id>/
data/calibration/curves/<sensor_id>/<curve_id>/
data/archive/year=YYYY/month=MM/  # Parquet cold storage (F17)
data/leak_rate_history.json        # история измерений утечки (F13)
```

## Отчёты

Секции по шаблону: `title_page`, `cooldown_section`, `thermal_section`,
`pressure_section`, `operator_log_section`, `alarms_section`, `config_section`.
Гарантированный артефакт: `report_editable.docx`. Опционально: `report_raw.pdf`
(best-effort, требует `soffice` / LibreOffice).

## Keithley TSP

`tsp/p_const.lua` — черновой TSP-супервизор для P=const обратной связи.
**Не загружается на прибор.** P=const работает на стороне хоста в
`keithley_2604b.py`. TSP-супервизор запланирован на Phase 3 (требует
верификации на оборудовании).

## Структура проекта

```text
src/cryodaq/
  analytics/     # calibration fitter, cooldown predictor, plugins, vacuum trend,
                 # leak_rate estimator (F13)
  core/          # safety FSM, scheduler, broker, alarms v2, interlocks,
                 # sensor_diagnostics, experiments, zmq_bridge
  drivers/       # LakeShore, Keithley, Thyracont + transport adapters
  gui/           # MainWindowV2, dashboard, overlays, legacy widgets
  reporting/     # template-driven DOCX generator
  storage/       # SQLite, Parquet, CSV, HDF5, XLSX,
                 # cold_rotation (F17), archive_reader (F17)
  web/           # FastAPI monitoring
tsp/             # Keithley TSP scripts (черновик, не загружен)
tests/           # ~2 019 тестов
config/          # YAML-конфигурации
```

## Тесты

```bash
python -m pytest tests/core -q
python -m pytest tests/storage -q
python -m pytest tests/drivers -q
python -m pytest tests/analytics -q
python -m pytest tests/gui -q
python -m pytest tests/reporting -q
```

Запускать после `pip install -e ".[dev,web]"`. GUI-тесты требуют `PySide6` +
`pyqtgraph`. Часть тестов storage требует `CRYODAQ_ALLOW_BROKEN_SQLITE=1` на
машинах с SQLite < 3.51.3 (кроме backport-безопасных версий 3.44.6 и 3.50.7).

## Местный AI-ассистент

В CryoDAQ работает локальный AI-агент (текущий бренд: Гемма,
основан на модели gemma4:e4b через Ollama). Никаких внешних API.

### Что делает

Подписан на engine events (alarms, phase transitions, finalize,
sensor anomalies, shift handovers). Когда срабатывает alarm или
завершается эксперимент, генерирует human-readable summary для
оператора в:
- Telegram (чат бота)
- Operator log (журнал)
- GUI insight panel (overlay в MainWindowV2)

Также генерирует диагностические предложения (alarms +
sensor_anomaly_critical) и intro-параграфы для DOCX отчётов
кампаний.

### Что НЕ делает

- Не имеет доступа к engine командам. Только текстовые каналы.
- Не модифицирует state. Read-only.
- Не отвечает на запросы (это будет добавлено в Phase 3 — Archive
  query interface).

### Конфигурация

См. `config/agent.yaml`. Ключевые параметры:
- `agent.enabled`: вкл/выкл агента
- `agent.brand_name`: имя для оператора (можно менять при
  миграции на другую модель)
- `agent.ollama.default_model`: модель Ollama
- `agent.triggers.*`: какие события активируют агента
- `agent.rate_limit`: ограничения (60 calls/hour по умолчанию)

### Миграция на другую модель

1. `ollama pull <new_model>`
2. Edit `config/agent.yaml`:
   ```yaml
   agent:
     brand_name: "Новое имя"
     brand_emoji: "🦉"
     ollama:
       default_model: <new_model>
   ```
3. Restart engine
4. Smoke test: trigger alarm в mock mode

Без изменений кода. См. `artifacts/architecture/assistant-v2-vision.md`
§1.6 для деталей.

### Архитектура

См. `artifacts/architecture/assistant-v2-vision.md` —
полная архитектурная картина включая planned Phases 1-3 (periodic
reports, sinks, archive query).

### Audit log

Каждый LLM call записан в `data/agents/assistant/audit/<YYYY-MM-DD>/`.
Полный context, prompt, response, tokens, latency, output targets.
Verifiable trail для post-hoc review.

## Известные ограничения

На v0.45.0:

- **SQLite WAL gate:** engine при старте падает на версиях SQLite из диапазона
  `[3.7.0, 3.51.3)` по F25. Backport-безопасные: 3.44.6, 3.50.7 (проходят без
  переменной). Обход: `CRYODAQ_ALLOW_BROKEN_SQLITE=1` (выводится предупреждение).
  Лаб. Ubuntu PC — проверьте `sqlite3 --version`.
- **Верификация lab Ubuntu PC:** H5 ZMQ fix из v0.39.0 проверен только на macOS.
  Физический доступ к лаб. ПК ожидается.
- **PDF-отчёты:** best-effort. Гарантированный артефакт — DOCX.
- **Runtime calibration policy:** глобальный on/off + поканальный KRDG/SRDG+curve.
  Консервативный fallback на KRDG при отсутствии curve / SRDG / ошибке вычисления.
  Реальное поведение LakeShore требует лаб. верификации.
- **Deprecation warnings:** `asyncio.WindowsSelectorEventLoopPolicy` на новых
  версиях Python.
- **Leak rate (F13):** `chamber.volume_l` должен быть задан в
  `config/instruments.local.yaml` перед первым измерением; `finalize()` бросает
  `ValueError` при `volume_l == 0.0`.
- **ArchiveReader replay (F28):** `ArchiveReader` существует, но не подключён
  к engine replay path. Запросы к данным старше 30 дней через replay пока не
  охватывают Parquet-архив. Запланировано в F28.

## Лицензия

See `LICENSE`. Third-party notices: `THIRD_PARTY_NOTICES.md`.
