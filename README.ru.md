[English](README.md) · **Русский**

# CryoDAQ

Стек сбора данных, управления и анализа для криогенной лаборатории.
Заменяет 3-летний LabVIEW VI, управлявший приборами и отправлявший email-алерты.
Добавлено: скриптовые FSM-циклы экспериментов, автоматическая калибровка с мульти-форматным
экспортом, автогенерация DOCX-отчётов, ролевые Telegram-алерты, детекция аномалий
датчиков с аларм-конвейером, plugin-аналитика, локальный слой операторских
запросов с базой знаний (RAG), режим replay исторических данных,
интерферометрическая метрология (Etalon MultiLine), регрессионный тест-сьют
для Windows и Linux.

Разработано для АКЦ ФИАН (проект Millimetron).

## Статус

- **Последний релиз:** v0.64.1 (2026-07-08)
- **Релизная основа:** последний локально доступный релизный тег — `v0.64.1`
  (2026-07-08).
- **Активный кандидат:** `feat/montana-phase-a` — крупный, ещё не выпущенный
  рефакторинг программной готовности к лаборатории. Зелёный CI или mock-тесты
  сами по себе не означают лабораторную приёмку.
- **Граница доказательств:** проверки на реальных приборах, dummy load,
  независимом конечном элементе и с оператором остаются открытыми, пока не
  выполнены и не записаны процедуры из
  [`docs/lab_verification_checklist.md`](docs/lab_verification_checklist.md).
- **Текущее состояние:** точные доказательства и открытые гейты — в
  [`PROJECT_STATUS.md`](PROJECT_STATUS.md). Рабочий отчёт о состоянии до/после,
  метриках, проектных решениях и картах архитектуры находится в
  [`docs/MONTANA_REFACTOR_REPORT.md`](docs/MONTANA_REFACTOR_REPORT.md); текущую
  границу приёмки определяет `PROJECT_STATUS.md`.

## Рефакторинг Montana

Montana сохраняет панорамный, насыщенный информацией операторский workflow и
движет CryoDAQ к более узким владельцам, явным доказательствам и видимым
границам отказа. Это направление и частично реализованный кандидат, а не уже
принятое системное свойство. В production acquisition выбранный для архива
batch фиксируется до обычной публикации в `DataBroker`; `SafetyBroker` отдельно
получает полный raw batch для safety-оценки. Граница observational assistant
остаётся открытой: текущий код содержит второй `SQLiteWriter`, RAG mutation-path
и Telegram credential, которые нужно удалить или передать правильному владельцу.

Кандидат проверяется на точном commit SHA раздельно в Windows, WSL/Linux,
ONEDIR и hosted CI. Эти программные проверки не заменяют физические. Для
интервью с разработчиком, оператором или криогенным инженером используйте
готовое задание и перечень вопросов в разделе
[`Interview guide for another agent`](README.md#interview-guide-for-another-agent)
английского README.

Исторический checkpoint: commit
`503c8bf8d884654256ede4f08a9e44ab7b382242` связан с заявленным зелёным
восьми-job GitHub Actions run `29662599972`. Эти данные относятся только к
этому commit. Текущее рабочее дерево существенно изменено и не имеет immutable
candidate SHA или покрывающего CI result; текущий remote/PR status нужно
отдельно проверить на GitHub.

До code-complete остаются: карантин USBTMC после неоднозначного обмена; строгая
неизменяемая safety-конфигурация и точные привязки каналов; ограниченный
shutdown-HOLD и containment смерти safety/writer; сквозная identity/idempotency
журнала оператора; строго наблюдательный assistant без write-authority;
общая GUI-модель freshness/provenance/lifecycle; решение по потере freshness в
conductivity auto-advance; согласование protocol/architecture/report/SVG.
Затем один frozen SHA должен пройти Windows, WSL, package/source-install, soak,
ONEDIR, восемь hosted CI jobs и два обязательных независимых внутренних review.
Внешний model-review полезен дополнительно, но не блокирует открытие PR.
Physical instrument, dummy-load, host-death, independent final element,
длительный soak и операторская приёмка закрываются только реальными
процедурами. Отдельный 100+ sensor / 4K projector fleet-view отложен и не
блокирует обычную лабораторную готовность.

## Архитектура

CryoDAQ предоставляет четыре основные операторские deployment-поверхности/режима:

- `cryodaq` — полный кроссплатформенный операторский launcher. В его процессе
  работает Qt GUI; launcher наблюдает отдельные engine, GUI bridge и
  assistant-кандидат с ещё открытой observational-границей. Bounded report
  children принадлежат engine или assistant-компоненту, который их запустил, а
  не самому launcher.
- `cryodaq-engine` — отдельный headless asyncio runtime. Управляет приборами,
  запускает safety manager FSM, оценивает alarm rules и interlocks, сохраняет
  данные и обслуживает команды GUI через ZMQ.
- `cryodaq-gui` — сокращённый отдельный Qt-клиент для уже работающего engine.
  Он перезапускается без остановки сбора. Standalone engine по-прежнему умеет
  строить on-demand reports; этот сокращённый путь не предоставляет launcher
  lifecycle для assistant/periodic delivery.
- `cryodaq.web.server:app` — опциональный FastAPI monitoring dashboard.

Целевая и обязательная граница: только engine владеет приборами, safety и
сохраняемым операторским состоянием; GUI, assistant и report workers лишь
потребляют backend truth. До удаления текущего второго writer и mutation/RAG
authority из assistant эта граница остаётся открытым engineering gate, а не
завершённым свойством кандидата.

Поток данных:

```
Instrument → Driver → Scheduler
           → SQLiteWriter (выбранный для архива batch)
           → DataBroker → {GUI, Telegram, Analytics}
           ↘ SafetyBroker (полный raw batch; safety-path)
```

IPC: ZeroMQ PUB/SUB `:5555` (msgpack) + REP/REQ `:5556` (JSON-команды).

## Поддерживаемые приборы

- 3× LakeShore 218S (GPIB) — 24 температурных канала
- Keithley 2604B (USB-TMC) — двухканальный SMU (`smua` + `smub`)
- Thyracont VSP63D (RS-232) — 1 канал давления
- Etalon MultiLine (TCP/IP) — интерферометрическая метрология длины;
  averaged- и continuous-режимы, burst-захват вибрации в Parquet

## Реализованные рабочие процессы

Список ниже описывает активное дерево: выпущенные workflows v0.64.1 вместе с
явно невыпущенным поведением Montana candidate. Candidate defaults и hardening
не являются утверждением о релизе или физической приёмке; см. раздел «Статус».

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
- **Эксперимент FSM:** шесть канонических фаз: preparation → vacuum → cooldown →
  measurement → warmup → teardown. Abort/fault — outcome или state, а не
  седьмая фаза эксперимента. Шаблонные скриптовые прогоны.
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
  ложным SAFE_OFF. Tracked `config/physical_alarms.yaml` явно задаёт
  `vacuum.escalate_to_safety: true`; built-in default при отсутствии файла
  alarm-only (`false`), а некорректный существующий config fail-safe даёт `true`.
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
- **SQLite fail-closed runtime:** все runtime-подключения к БД идут через
  `storage/_sqlite.py`. Поддерживаемое Windows/Linux environment фиксирует
  безопасную SQLite. Если stdlib небезопасна, shim может выбрать только отдельно
  установленный и тоже безопасный `pysqlite3`; fallback-пакет по умолчанию не
  устанавливается, поэтому без него startup gate честно останавливает engine.
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

Индикатор launcher в системном трее намеренно грубый. При текущем wiring
известный safety fault может дать красное состояние; число alarms остаётся
неизвестным, поэтому сами alarms не могут включить красное состояние, а зелёное
недостижимо. Все остальные случаи connected/disconnected/unknown, stale data и
reporting fault сводятся к янтарному caution-состоянию. Форма и русский tooltip
дублируют цвет. Tray не является авторитетным представлением alarms или
готовности и не заменяет dashboard/alarm surface.

## Установка

### Требования

- Windows 10/11 или Linux
- Python `>=3.12` (должен линковаться с SQLite `>=3.51.3` либо с backport-безопасной
  версией 3.44.6 / 3.50.7 — см. «Известные ограничения»)
- Git
- VISA backend / драйверы приборов по необходимости

### Установка

Канонический воспроизводимый workflow создаёт runtime с безопасной SQLite,
устанавливает зафиксированный набор зависимостей без повторного resolution и
проверяет его целостность:

```bash
conda env create --file environment.yml
conda activate cryodaq
python -m pip install -r requirements-lock.txt
python -m pip install -e . --no-deps --no-build-isolation
python -m pip check
```

`requirements-lock.txt` фиксирует resolved base/dev/web/build зависимости, но
не является hash-locked supply-chain manifest. `install.bat` проверяет текущий
Python/SQLite и устанавливает тот же lock в уже активный безопасный runtime; он
не создаёт Conda environment. `pip install -e ".[dev,web]"` допустим только как
developer convenience внутри независимо проверенного безопасного SQLite
runtime, а не как операторская или qualification-установка.

Ключевые runtime-зависимости: `PySide6`, `pyqtgraph`, `pyvisa`, `pyserial-asyncio`,
`pyzmq`, `python-docx`, `scipy`, `matplotlib`, `openpyxl`, `pyarrow`.

## Запуск

```bash
cryodaq-engine        # headless engine (реальные приборы)
cryodaq-gui           # только GUI (подключается к работающему engine)
cryodaq               # полный кроссплатформенный операторский launcher
cryodaq-engine --mock # mock-режим (симулированные приборы)
uvicorn cryodaq.web.server:app --host 127.0.0.1 --port 8080  # опциональный web (loopback)
```

GET-поверхность web-дашборда без аутентификации — биндите только `127.0.0.1`;
публичный доступ требует reverse proxy с авторизацией (или SSH-туннель). Два
write-endpoint'а `/api/v1` (`POST /log`, `POST /alarms/{id}/ack`) требуют
bearer-токен из gitignored `config/web.local.yaml`.

В `POST /api/v1/log` можно передать точный `experiment_id`; без него запись
явно помечается `experiment_unbound` и никогда не привязывается неявно к
«текущему» эксперименту. Author/source назначает сервер, он же создаёт один
`request_id` из 32 строчных шестнадцатеричных символов на запрос. Публичные
live readings передают `NaN` и бесконечности как JSON `null`, сохраняя identity
и status, поэтому недоступное значение не выглядит достоверным числом.

Вспомогательные CLI:

```bash
cryodaq-cooldown build --help    # cooldown ML: параметры обучения
cryodaq-cooldown predict --help  # cooldown ML: параметры прогноза ETA
cryodaq-trends scan --help       # параметры межэкспериментной feature-таблицы
cryodaq-trends drift --help      # параметры drift-проверки
cryodaq-replay-curve             # трансформация кривых для replay
cryodaq-rag-index                # построение индекса базы знаний
cryodaq-rag-search               # семантический поиск по базе знаний
```

## Конфигурация

Активные конфигурационные файлы Montana candidate:

- `config/instruments.yaml` — GPIB/serial/USB адреса, каналы LakeShore,
  `chamber.volume_l` для F13 leak rate
- `config/instruments.local.yaml.example` — шаблон машино-специфических
  переопределений приборов (`instruments.local.yaml` — gitignored)
- `config/channel_descriptors.yaml` — полная каноническая authority
  descriptor/binding для всех приобретаемых каналов
- `config/channel_descriptors.local.yaml.example` — machine-specific полная
  замена manifest, а не частичный merge; перед реальным запуском её нужно
  сверить с physical roster
- `config/safety.yaml` — таймауты FSM, rate limits, drain timeout
- `config/alarms_v3.yaml` — правила аларм-движка (threshold/rate/composite/phase)
- `config/interlocks.yaml` — условия interlocks + действия
- `config/physical_alarms.yaml` — параметры физических защит холодного криостата;
  tracked `vacuum.escalate_to_safety` равен `true`, а built-in missing-file
  default остаётся alarm-only (`false`)
- `config/channels.yaml` — отображаемые имена, видимость, группировка
- `config/notifications.yaml` — tracked-шаблон и схема; реальные credentials
  должны находиться только в gitignored `config/notifications.local.yaml`.
  Engine и periodic loaders предпочитают local-файл, но текущий Telegram sender
  assistant всё ещё читает только tracked base file; это открытый дефект wiring.
- `config/notifications.local.yaml.example` — шаблон локальных Telegram
  credentials (`notifications.local.yaml` — gitignored)
- `config/housekeeping.yaml` — throttle, retention, compression, `cold_rotation`
- `config/plugins.yaml` — sensor_diagnostics + vacuum_trend; `aggregation_threshold` + `escalation_cooldown_s`
- `config/cooldown.yaml` — параметры cooldown predictor
- `config/analytics_layout.yaml` — phase-aware раскладка analytics-виджетов
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

Большинство `*.local.yaml` переопределяет base-настройки. Для descriptors
правило намеренно строже и связано с выбранной instrument authority: если
engine выбрал `instruments.local.yaml`, файл `channel_descriptors.local.yaml`
обязателен и целиком заменяет base manifest; при base `instruments.yaml`
используется base descriptor manifest, даже если local descriptor-файл случайно
существует. Ошибки manifest/schema, неоднозначные bindings, отсутствие
обязательного local manifest и несовпадение instrument set блокируют startup.
Затем каждое принятое reading должно однозначно разрешить
`(instrument_id, emitted_channel)` в стабильный `channel_id`; необъявленный
emitted channel отклоняется при первом bind. Descriptor выдаёт только identity,
никогда не capability или hazardous-source authority.

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

`tsp/cryodaq_wdog.lua` — TSP-проверка запоздавшего pet под host-side
SafetyManager. P=const по-прежнему работает на стороне хоста в
`keithley_2604b.py`. Watchdog выбирается оператором через
`config/instruments.yaml` → `keithley.watchdog.mode`: `off` (дефолт драйвера —
скрипт не загружается, хост — единственный авторитет), `best_effort` (активация на
connect, при неудаче взвода — откат к host-only), `required` (fail-closed —
требует явный autonomous bit и заставляет `connect()` бросить, пока его нет,
так что `SAFE_OFF` держится).
Версия 3 явно сообщает `cryodaq_wdog_autonomous=0`: она покрывает только
stall-then-recover, когда поздний pet всё же пришёл, и совсем не покрывает
полную смерть хоста. Предыдущая реализация таймера удалена, потому что
использовала команды и значения action, не являющиеся допустимыми по справочнику
2600B. Настоящий OFF при смерти хоста требует документированного редизайна и
физического доказательства; предпочтителен независимый защёлкивающийся cutout.
`watchdog.timeout_s` — только конечное число от 1 до 300 секунд; TSP clock
имеет секундную гранулярность и использует строгое `elapsed > timeout`.

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
tests/           # unit, integration, GUI, process и evidence-тесты для Windows/Linux
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

Запускать после канонической установки выше. GUI-тесты требуют `PySide6` +
`pyqtgraph`. `CRYODAQ_ALLOW_BROKEN_SQLITE=1` может использоваться только для
осознанной локальной диагностики небезопасного runtime; результаты такого
прогона не являются storage, deployment или release-qualification evidence.

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

Целевая форма — два read-only контура: live-наблюдатель и query-router. Текущий
assistant ещё нарушает строгую observational-границу вторым writer, Telegram
credential и RAG mutation-path; это открытый gate. Системная архитектура — в
`docs/architecture.md`.

### Audit log

Каждый model call записан под `data/agents/.../audit/<YYYY-MM-DD>/`.
Полный context, prompt, response, tokens, latency, output targets.
Verifiable trail для post-hoc review.

## Известные ограничения

Ограничения ниже относятся к текущей границе v0.64.1/Montana candidate.
Software- и лабораторные проверки собраны в turnkey-протокол
`docs/lab_verification_checklist.md`.

- **SQLite WAL gate:** engine при старте падает на версиях SQLite из диапазона
  `[3.7.0, 3.51.3)`, кроме backport-safe 3.44.6 и 3.50.7. Поддерживаемое
  Windows/Linux environment фиксирует безопасную библиотеку. Никакой fallback
  пакет не устанавливается по умолчанию: если оператор независимо установил
  безопасный `pysqlite3`, shim может выбрать его; иначе startup fail-closed.
  `CRYODAQ_ALLOW_BROKEN_SQLITE=1` — аварийное осознанное подтверждение риска,
  а не исправление и не доказательство готовности deployment.
- **Верификация lab Ubuntu PC:** CI и WSL проверяют H5 ZMQ idle-death contract,
  но не закрывают physical gate на реальном лабораторном Ubuntu PC. Процедуру
  из чек-листа надо выполнить и записать именно на этой машине.
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
- **Защита Keithley при смерти хоста:** TSP-скрипт v3 намеренно неавтономен и
  покрывает только поздний pet после сталла. Поэтому `required` отказывает с
  v3, а `best_effort` пишет CRITICAL о деградации и использует late-pet check.
  Ни один программный status bit не доказывает физический OFF на клеммах.
  Host-death и внешний interlock остаются лабораторными гейтами с независимым
  измерением.

## Лицензия

See `LICENSE`. Third-party notices: `THIRD_PARTY_NOTICES.md`.
