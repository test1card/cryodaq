[English](README.md) · **Русский**

# CryoDAQ

Стек сбора данных, управления и анализа для криогенной лаборатории.
Заменяет 3-летний LabVIEW VI, управлявший приборами и отправлявший email-алерты.
Добавлено: скриптовые FSM-циклы экспериментов, автоматическая калибровка с мульти-форматным
экспортом, автогенерация DOCX-отчётов, ролевые Telegram-алерты, детекция аномалий
датчиков с аларм-конвейером, plugin-аналитика, локальный слой операторских
запросов с базой знаний (RAG), режим replay исторических данных,
интерферометрическая метрология (Etalon MultiLine), регрессионный тест-сьют
(3500 тест-функций в 324 файлах).

Разработано для АКЦ ФИАН (проект Millimetron).

## Статус

- **Последний релиз:** v0.64.1 (2026-07-08)
- **Тесты:** 3500 тест-функций в 324 файлах
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
- Etalon MultiLine (TCP/IP) — интерферометрическая метрология длины;
  averaged- и continuous-режимы, burst-захват вибрации в Parquet

## Реализованные рабочие процессы

Полностью функциональны в v0.64.0:

- **База знаний (RAG):** локальный семантический поиск по архиву экспериментов,
  vault-заметкам, оператор-логу и корпусу `data/knowledge/`
  (`equipment_manuals` — PDF приборов через pypdf; `procedures` — Markdown;
  `reference` — operator manual / README / CHANGELOG). RAG-модуль:
  loader -> LanceDB indexer -> top-K searcher; embeddings `qwen3-embedding:0.6b`
  (1024-dim) через Ollama. CLI `cryodaq-rag-index` / `cryodaq-rag-search`,
  ZMQ `rag.rebuild_index` / `rag.rebuild_status`, кнопка «Обновить индекс» в
  KnowledgeBasePanel. Bootstrap при пустом индексе на старте engine.
- **Локальный сервис операторских запросов:** локальный Ollama-сервис (без внешних
  API) классифицирует намерение оператора (IntentClassifier), маршрутизирует
  запрос (QueryRouter) и отвечает по live-данным (BrokerSnapshot) и базе знаний
  (KNOWLEDGE_QUERY). Read-only; полный audit-trail каждого model-вызова.
- **Replay исторических данных:** воспроизведение записей через DataBroker;
  predictor поверх replay-потока с decoupled-часами для ускоренного прогона;
  `cryodaq-replay-curve` для трансформации кривых; legacy channel-map для
  до-2025 записей.
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
- **Fail-closed safety discipline:** Keithley output OFF проверяется readback'ом;
  неподтверждённый OFF становится fault или блокирующим RUN-предусловием, а не
  ложным SAFE_OFF. VacuumGuard может опционально эскалировать в SafetyManager
  через `vacuum_guard.escalate_to_safety`.
- **Оператор-лог:** SQLite-backed; доступ через GUI + ZMQ.
- **Шаблоны экспериментов, lifecycle-метаданные, архивация артефактов:** каталог
  `data/experiments/<id>/` с `metadata.json`, `reports/`, опциональный Parquet-архив.
- **Plugin-архитектура:** ABC-изоляция; сбои callback помечают плагин degraded
  без краша engine.
- **Housekeeping:** адаптивный throttle + retention + compression.
- **Cold-storage rotation (F17):** включена по умолчанию
  (`cold_rotation.enabled: true`). `ColdRotationService` подключён к движку и
  запускается раз в сутки в `schedule_time` (03:00): ежедневные SQLite-файлы
  старше 30 дней ротируются в Parquet/Zstd. Каждый читатель идёт через
  `ArchiveReader` (hot SQLite ∪ cold Parquet) — GUI-история, живой журнал
  оператора, отчёты, экспорт CSV/XLSX/HDF5/Parquet, replay и калибровка видят
  ротированные дни. Единственный kill-switch — `cold_rotation.enabled`; ротация
  идемпотентна, а дочистка застрявших .db удаляет только байт-идентичный
  оригинал (`source_md5`).
- **SQLite self-heal на Linux:** все runtime-подключения к БД идут через
  `storage/_sqlite.py`; если stdlib SQLite попадает в небезопасный WAL-reset
  диапазон, shim откатывается на bundled Linux `pysqlite3-binary`.
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

- Аналитика — phase-aware виджеты: траектория температур, история охлаждений,
  сводка эксперимента (статистика каналов, топ-аларм, ссылки на артефакты),
  прогноз охлаждения (cooldown predictor, ансамбль по progress-variable с ETA)
  и прогноз установившейся температуры (T∞ через экспоненциальный фит).
- Архив — прошлые эксперименты + отчёты + Parquet-экспорты
- Калибровка — рабочий процесс capture / fit / export
- База знаний — RAG-поиск + встроенный операторский чат
- MultiLine — интерферометрическая метрология + «Захват вибрации» (burst)
- Оператор-лог
- Другие overlay по иконкам ToolRail

`MainWindowV2` — единственная операторская оболочка. Легаси tab-based
`MainWindow` и все overlay'и эпохи вкладок удалены в Phase II.13;
`cryodaq-gui` использует `MainWindowV2` с Phase I.1.

Системный трей: `healthy / warning / fault`. `healthy` не отображается без
достаточного backend-подтверждения. `fault` — при неснятых алармах или
safety-state `fault` / `fault_latched`.

## Установка

### Требования

- Windows 10/11 или Linux
- Python `>=3.12` (должен линковаться с SQLite `>=3.51.3` либо с backport-безопасной
  версией 3.44.6 / 3.50.7 — см. «Известные ограничения»)
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
uvicorn cryodaq.web.server:app --host 127.0.0.1 --port 8080  # опциональный web (loopback)
```

GET-поверхность web-дашборда без аутентификации — биндите только `127.0.0.1`;
публичный доступ требует reverse proxy с авторизацией (или SSH-туннель). Два
write-endpoint'а `/api/v1` (`POST /log`, `POST /alarms/{id}/ack`) требуют
bearer-токен из gitignored `config/web.local.yaml`.

Вспомогательные CLI:

```bash
cryodaq-cooldown build/predict   # cooldown ML: обучение и прогноз ETA
cryodaq-replay-curve             # трансформация кривых для replay
cryodaq-rag-index                # построение индекса базы знаний
cryodaq-rag-search               # семантический поиск по базе знаний
```

## Конфигурация

Активные конфигурационные файлы на v0.64.0:

- `config/instruments.yaml` — GPIB/serial/USB адреса, каналы LakeShore,
  `chamber.volume_l` для F13 leak rate
- `config/instruments.local.yaml.example` — шаблон машино-специфических
  переопределений приборов (`instruments.local.yaml` — gitignored)
- `config/safety.yaml` — таймауты FSM, rate limits, drain timeout
- `config/alarms.yaml` — legacy определения алармов
- `config/alarms_v3.yaml` — правила аларм-движка v2 (threshold/rate/composite/phase)
- `config/interlocks.yaml` — условия interlocks + действия
- `config/physical_alarms.yaml` — параметры физических защит холодного криостата
  (CooldownAlarm, VacuumGuard, включая опциональную защёлку
  `vacuum_guard.escalate_to_safety`)
- `config/channels.yaml` — отображаемые имена, видимость, группировка
- `config/notifications.yaml` — Telegram bot_token, chat_ids, escalation
- `config/notifications.local.yaml.example` — шаблон локальных Telegram
  credentials (`notifications.local.yaml` — gitignored)
- `config/housekeeping.yaml` — throttle, retention, compression, `cold_rotation`
- `config/plugins.yaml` — sensor_diagnostics + vacuum_trend; `aggregation_threshold` + `escalation_cooldown_s`
- `config/cooldown.yaml` — параметры cooldown predictor
- `config/analytics_layout.yaml` — phase-aware раскладка analytics-виджетов
- `config/shifts.yaml` — reserved/unused (нет загрузчика в src; shift handover
  идёт через operator-query command surface, не из этого файла)
- `config/agent.yaml` — локальный сервис операторских запросов (модель Ollama,
  триггеры, rate limit)
- `config/rag.yaml.example` — база знаний / RAG (embedding-модель, корпус)
- `config/rag_categories.yaml` — presets запросов боковой панели KnowledgeBasePanel
- `config/sinks.yaml.example` — sinks (vault-заметки, webhook) на finalize
- `config/web.local.yaml.example` — шаблон токена FastAPI write-endpoint'ов
  (`web.local.yaml` — gitignored)
- `config/themes/*.yaml` — bundled GUI theme packs; выбор хранится в gitignored
  `config/settings.local.yaml`
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

`tsp/cryodaq_wdog.lua` — прошивочный dead-man watchdog TSP, firmware-бэкстоп
под host-side SafetyManager. P=const по-прежнему работает на стороне хоста в
`keithley_2604b.py`. Watchdog выбирается оператором через
`config/instruments.yaml` → `keithley.watchdog.mode`: `off` (по умолчанию —
скрипт не загружается, хост — единственный авторитет), `best_effort` (взвод на
connect, при неудаче взвода — откат к host-only), `required` (fail-closed —
неудачный взвод заставляет `connect()` бросить, так что `SAFE_OFF` держится).
Текущий механизм покрывает только stall-recovery; автономный прошивочный
run-механизм (`trigger.timer`) остаётся не проверенным на стенде.

## Структура проекта

```text
src/cryodaq/
  agents/        # локальный query-сервис + RAG база знаний
  analytics/     # calibration fitter, cooldown predictor, plugins, vacuum trend,
                 # leak_rate estimator (F13)
  core/          # safety FSM, scheduler, broker, alarms v2, interlocks,
                 # sensor_diagnostics, experiments, zmq_bridge
  drivers/       # LakeShore, Keithley, Thyracont, Etalon MultiLine + transports
  gui/           # MainWindowV2, dashboard, overlays
  notifications/ # Telegram-алерты + интерактивный бот + escalation
  replay/        # replay исторических данных + curve transforms
  replay_engine/ # ZMQ-совместимый replay-движок (ускоренный прогон)
  reporting/     # template-driven DOCX generator
  sinks/         # vault-заметки + webhook на finalize эксперимента
  storage/       # SQLite, Parquet, CSV, HDF5, XLSX,
                 # cold_rotation (F17), archive_reader (F17)
  tools/         # CLI-утилиты (cooldown_cli)
  utils/         # общие хелперы
  web/           # FastAPI monitoring
tsp/             # Keithley TSP watchdog (cryodaq_wdog.lua; загружается по watchdog.mode)
tests/           # 3500 тест-функций в 324 файлах
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
машинах, где выбранная SQLite попадает в `[3.7.0, 3.51.3)`, кроме
backport-безопасных версий 3.44.6 и 3.50.7.

## Локальный сервис операторских запросов

В CryoDAQ работает локальный text-generation сервис (текущий бренд: Гемма,
по умолчанию модель gemma4:e4b через Ollama; на dev-машинах с малым
VRAM даунгрейд до gemma4:e2b). Никаких внешних API.

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
экспериментов.

**Отвечает на запросы оператора.** IntentClassifier определяет намерение,
QueryRouter маршрутизирует запрос к адаптерам: live-данные через
BrokerSnapshot и семантический поиск по базе знаний (KNOWLEDGE_QUERY →
RAG). Доступно из встроенного чата в overlay «База знаний» и через
Telegram-бот.

### Что НЕ делает

- Не имеет доступа к engine командам. Только чтение данных и текстовые каналы.
- Не модифицирует state. Read-only.

### Конфигурация

См. `config/agent.yaml`. Ключевые параметры:
- `agent.enabled`: вкл/выкл сервис
- `agent.brand_name`: имя для оператора (можно менять при
  миграции на другую модель)
- `agent.ollama.default_model`: модель Ollama
- `agent.triggers.*`: какие события активируют сервис
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

Без изменений кода.

### Архитектура

Два контура: live-наблюдатель (подписан на engine events, выдаёт summary) и
query-router (классифицирует намерение оператора, маршрутизирует к read-only
адаптерам). Системная архитектура — в `docs/architecture.md`.

### Audit log

Каждый model call записан под `data/agents/.../audit/<YYYY-MM-DD>/`.
Полный context, prompt, response, tokens, latency, output targets.
Verifiable trail для post-hoc review.

## Известные ограничения

На v0.64.0. Перечисленные ниже лабораторные проверки собраны в turnkey-протокол
в `docs/lab_verification_checklist.md`.

- **SQLite WAL gate:** engine при старте падает на версиях SQLite из диапазона
  `[3.7.0, 3.51.3)` по F25. Backport-безопасные: 3.44.6, 3.50.7 (проходят без
  переменной). На Linux это самоисцеляется: `storage/_sqlite.py` прозрачно
  откатывается на встроенный `pysqlite3-binary` (базовая зависимость), когда
  линкованный SQLite попадает в диапазон, так что гейт проходит из коробки.
  Ручное вмешательство (`CRYODAQ_ALLOW_BROKEN_SQLITE=1` или Python, слинкованный
  с безопасным SQLite) нужно только если небезопасны/отсутствуют ОБА —
  и stdlib, и fallback. macOS не поставляет wheels для pysqlite3; его stdlib
  ожидаемо безопасен.
- **Верификация lab Ubuntu PC:** H5 ZMQ fix из v0.39.0 проверен только на macOS.
  Физический доступ к лаб. ПК ожидается (см. чек-лист).
- **Warning при shutdown engine:** при завершении engine в логе может появиться
  один ERROR `Unclosed client session`, потому что `aiohttp`-сессия не закрыта
  на этом exit path. Это косметика shutdown; данные и safety-state не затронуты.
- **PDF-отчёты:** best-effort. Гарантированный артефакт — DOCX.
- **Runtime calibration policy:** глобальный on/off + поканальный KRDG/SRDG+curve.
  Консервативный fallback на KRDG при отсутствии curve / SRDG / ошибке вычисления.
  Реальное поведение LakeShore требует лаб. верификации.
- **Leak rate (F13):** `chamber.volume_l` должен быть задан в
  `config/instruments.local.yaml` перед первым измерением; `finalize()` бросает
  `ValueError` при `volume_l == 0.0`.
- **Прошивочный run-механизм TSP watchdog:** автономный firmware dead-man
  (`trigger.timer`) не проверен на стенде. Текущий watchdog покрывает только
  stall-recovery; режим `required` гейтит на host-наблюдаемом взводе, а не на
  доказанном поведении прошивочного таймера.

## Лицензия

See `LICENSE`. Third-party notices: `THIRD_PARTY_NOTICES.md`.
