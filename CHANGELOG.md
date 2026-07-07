# CHANGELOG.md

Все заметные изменения в проекте CryoDAQ документируются в этом файле.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/).
Проект использует [Semantic Versioning](https://semver.org/lang/ru/).

---

## [0.59.0] — 2026-07-07 — NaN-доктрина: статус как дискриминатор от Reading до экспорта

Сквозная доктрина обращения с non-finite значениями: один канонический предикат
`Reading.is_usable()` решает валидность по `status`, а не по float; sentinel-persistence
устраняет молчаливую потерю error-строк; каждый reader декодирует хранимые пары
`(value, status)` на read-boundary, так что sentinel или legacy `±inf` не всплывёт
числом. Плюс retrofit validity-guard’ов на rate/diagnostics/vacuum-путях, debounced
NaN-эскалация на интерлоках и reset-not-drop guard на rate-clock. Волны фиксов прошли
внешнее ревью и phase-gate re-check.

### Added

- **Канонический предикат `Reading.is_usable()` на границе Reading.** usable ⟺
  `status == OK` и значение finite — `status` дискриминатор на каждом слое, никогда
  float. OK-класс ровно `{OK}`: драйверы паруют каждый не-OK статус с non-finite
  sentinel, так что предикат совпадает со старыми float-guard’ами, добавляя
  defense-in-depth. Переведены ingest-edge’и: cooldown `_consume_loop` (был
  без guard — NaN отравлял детектор), sensor-diag и vacuum-trend (были
  `_push_if_finite` float-проверки). Non-usable readings по-прежнему обновляют
  staleness (liveness ≠ validity) (51044b8).
- **Sentinel-persistence для non-finite readings + writer-контракт.** Non-finite
  с error-статусом раньше молча дропались (sqlite3 маппит NaN в NULL против NOT NULL)
  — persistence-first инвариант был ложен для `SENSOR_ERROR`/`TIMEOUT`. Теперь все
  non-finite пишутся как единый finite sentinel (`-8.888e88`, вне физдиапазона любого
  канала, bit-exact через REAL), статус — дискриминатор. Контракт: sentinel-строка с
  OK-статусом CRITICAL-логируется и дропается per-row. Новый `storage/sentinel.py`
  даёт encode/decode; decode никогда не отдаёт non-usable строку числом
  (fde6ef5, dd31f21).
- **Декодирование sentinel-строк на всех read-boundary.** Десять read-boundary
  (xlsx pivot, archive reader sqlite+parquet, web `_query_history`, parquet
  export+read, csv, hdf5, replay, GUI history-feed) декодируют хранимые пары
  `(value, status)` — sentinel или legacy raw `±inf` не всплывёт числом. Ячейки
  таблиц пустеют, JSON → null, бинарные форматы несут NaN; колонка `status`
  сохраняется как дискриминатор. Второй проход добрал reports, replay-engine,
  calibration-fitter и experiment-readings; extraction калибровки теперь дропает
  error-статус пару, чей value в диапазоне (старые range-check её принимали)
  (4ad43ec, 876307e).
- **Debounced-эскалация для устойчиво non-usable интерлок-readings.** Non-usable
  reading (NaN / inf / error-статус — по `is_usable`, не по float) на
  interlock-protected канале больше не проваливается молча: каждый сэмпл
  CRITICAL-логируется + поднимает alarm-v2; ≥5 подряд на охвате ≥10 s (measurement
  time, config `nonusable_escalation`, strict-typed fail-closed parse) эскалируют
  через новый `SafetyManager.on_interlock_dead_channel`, который латчит FAULT только
  в RUNNING — idle dead-sensor не блокирует recovery, активно греемая зона с dead-sensor
  латчит FAULT. Т1–Т10 — interlock-only каналы; это закрывает их fail-open разрыв
  (77e9aa0).

### Changed

- **Retrofit HI-2 / D-C19 / ME-15 validity-guard’ов под доктрину.** Feed
  rate-estimator’а гейтится на `is_usable()` — finite value с error-статусом больше
  не доходит до эстиматора; orphaned `_push_if_finite` удалён. `sensor_diagnostics`,
  `vacuum_trend`, `rate_estimator` держат численно-нагруженные guard’ы (NaN
  health-floor, log-domain `P≤0` + finite-floor, OLS-знаменатель) — status-less
  float-API нужны локальные fail-closed floor’ы для прямых вызывающих; комментарии
  привязывают каждый к доктрине, чтобы будущие проходы их не сняли (cd74a7d).

### Fixed

- **rate-estimator clock-jump guard — reset-not-drop.** Backward NTP-шаг оставлял
  stale future-сэмплы в буфере (negative span → `min_span_s` gate возвращал None до
  maxlen-eviction) — 5 K/min защита слепла практически навсегда после permanent-шага.
  Теперь любой backward-gap, или forward-gap >4× медианного inter-sample периода
  буфера канала, чистит буфер канала и якорится на текущем сэмпле: слепота ограничена
  окном ~30 s (измерено в тесте). Measurement-time сохранён; per-channel; без нового
  config (фактор — ратифицированная константа) (6e630e2).
- **Закрытие phase-gate findings на escalation/rate-путях.** dead-channel эскалация
  латчит `escalated`-флаг только если SafetyManager реально faulted (канал, умерший в
  RUN_PERMITTED, больше не течёт escalated-окном, которое не faulted бы в RUNNING);
  non-usable `±inf`, чьё направление удовлетворяет matching interlock-условию,
  insta-trip’ает как до debounce (dangerous-side evidence), NaN и safe-side inf держат
  debounce; собственный rate-estimator SafetyManager гейтит ingest на `is_usable()`;
  backward-gap в пределах `max(1 s, 0.5× median poll)` дропает единичный сэмпл вместо
  reset (benign jitter не голодает эстиматор ниже `min_points`, genuine NTP-шаги всё
  ещё reset) (dd46122).
- **Закрытие phase-gate findings на presentation-путях.** replay_session декодирует
  строки до republish (raw sentinel доходил до PUB-порта); `curve_transforms` пишет
  lowercase-статус через `enum.value`, decode case-fold’ит статус как defense;
  pressure-plot рендерит NaN разрывом линии (`connect=finite`) вместо подстановки
  positive log-Y fallback; blank-ячейки archived-CSV парсятся в NaN, не 0.0
  (5b77ffd).
- **Drift-accumulator на rate-clock drops + case-folded replay-статусы.** Пять подряд
  within-tolerance backward-сэмплов эскалируют drop в buffer-reset (re-anchor +
  WARNING) — устойчивый backward measurement-time drift больше не голодает 5 K/min
  защиту молча; слепота ограничена refill-окном. Replay-пути case-fold’ят хранимые
  статусы до enum-реконструкции, так что legacy uppercase не-OK статус не падает в OK
  и escape masking (9d1e79b).

### Known Issues

- **Устойчивый backward measurement-time drift в пределах jitter-tolerance** сбрасывает
  эстиматор после 5 подряд drops (ограниченный ~30 s re-arm). До этого порога отдельные
  benign backward-jitter’ы дропаются пооднострочно — by design.
- **Decode case-folded.** Статус нормализуется к lowercase на чтении; legacy uppercase
  не-OK строки маскируются корректно, но канон хранимого статуса — lowercase
  (production никогда не пишет uppercase OK).
- **cold_rotation остаётся lossless by design.** Архивная копия не декодирует sentinel
  — маскирование делают все parquet-reader’ы на чтении; legacy-строки миграции не
  требуют (не-OK статус их маскирует).

### Test baseline

- Полный `pytest -q` — зелёный: 3541 passed, 2 skipped (+64 к 3477 в 0.58.0).
  ruff clean.

### Tags

- `v0.59.0` → см. merge-коммит на master.

### Selected commits in this release

- 51044b8 — `Reading.is_usable()` доктрина-предикат
- fde6ef5 — sentinel-persistence + writer-контракт
- 4ad43ec, 876307e — decode на всех read-boundary
- cd74a7d — retrofit HI-2 / D-C19 / ME-15 guard’ов
- 77e9aa0 — debounced NaN-эскалация на интерлоках
- 6e630e2 — rate-clock reset-not-drop guard
- dd46122, 5b77ffd — phase-gate findings (escalation/rate + presentation)
- 9d1e79b — drift-accumulator + case-folded replay-статусы
- dd31f21 — align persistence-pin’ов под sentinel-доктрину

---

---
## [0.58.0] — 2026-07-07 — периметр мониторинга: read-only REST, IPC-caps, path jail, cooldown-baseline

Пакет hardening-изменений по периферии: read-only REST-фасад для мониторинга,
socket-level ограничения на ZMQ, confinement путей калибровки, плюс новый
контур сравнения охлаждений с эталоном и inert-плумбинг аппаратного TSP-watchdog
для Keithley (по умолчанию выключен, go-live отдельной bench-фазой). Замыкающий
safety-фикс закрывает третий call-site класса CR-2. Волна прошла внешнее ревью;
edge-фиксы вошли отдельными коммитами.

### Added

- **Read-only REST-фасад `/api/v1`** поверх существующего dashboard-кэша:
  `state`, `readings`, `temperatures`, `pressure`, `history`, `alarms`,
  `experiment`, `log` — только GET, Pydantic-модели ответов работают как
  field-whitelist (operator / sample / notes / config_snapshot / пути
  артефактов / авторы лога не уходят в сеть), middleware отбивает тело >1 MiB
  до любого обращения к engine. Loopback-only posture без изменений; Swagger
  `/docs` подключён к дэшборду (cb2c235).
- **Per-cooldown fingerprint + сравнение с золотым эталоном (backend).**
  `CooldownFingerprint` (длительность, `T_cold_final`, время до базы и до 50 K,
  предельный вакуум), один JSON на охлаждение под `data/cooldown_history/`,
  указатель `baseline.json` на эталонное охлаждение, log-space сравнение вакуума
  с настраиваемыми порогами. Врезка в `_on_cooldown_end` до `_buffer.clear()`,
  под флагом `cooldown_baseline.enabled` (default false), глотает все ошибки —
  обработка конца охлаждения на ней сломаться не может (d2f9798).
- **GUI-карточка «История охлаждений» с overlay эталона.** Таблица fingerprint’ов
  в overlay `Архив` (дата / длительность / T_хол / до базы / вердикт), pin-as-эталон
  через backend’овый `baseline.json`, delta к эталону; компактный verdict-badge
  (НОРМА / ДЕГРАДАЦИЯ / НЕТ ДАННЫХ) в `Аналитика`, скрыт при выключенной фиче или
  без закреплённого эталона (3ef27cb).
- **Плумбинг Keithley TSP dead-man watchdog (inert, default-OFF).**
  `tsp/cryodaq_wdog.lua` — чистый watchdog для обоих SMU-каналов: по пропущенному
  deadline гасит оба выхода и латчит `cryodaq_wdog_tripped`. Драйвер получает
  arm-on-connect / pet-on-poll / disarm-on-stop под флагом
  `keithley.watchdog.enabled` (default false); при выключенном флаге поток команд
  байт-в-байт идентичен прежнему (test-proven). SafetyManager сверяет firmware-trip
  в `FAULT_LATCHED`, так что сработавший watchdog нельзя молча пере-взвести.
  Аппаратного взаимодействия нет; go-live — отдельная bench-фаза (195f6f0).

### Changed

- **stop_source-интерлок латчит FAULT при неподтверждённом OFF.** Ветка
  `stop_source` вызывала `emergency_off()`, но игнорировала возвращённый `bool`:
  неподтверждённый OFF (`False`) всё равно мягко останавливал в `SAFE_OFF`.
  Теперь `False` эскалирует в `_fault` (`FAULT_LATCHED`), зеркалируя два других
  call-site класса CR-2 (e2cdf83).
- **Socket-level size-caps на ZMQ REP/SUB + bounded msgpack.** `ZMQ_MAXMSGSIZE`
  на командном REP-сокете (256 KiB) и data-SUB (2 MiB), выставлен до bind/connect
  — libzmq отбрасывает oversize-кадры до аллокации. `_unpack_reading` получает
  defensive `len()`-guard и per-type `max_*_len` (у msgpack 1.x нет
  `max_buffer_size` на `unpackb`) (c8e6e1a).
- **Пути импорта/экспорта калибровки confined в exports-каталог.** Новый
  `core/path_jail.py` `resolve_within()`: realpath + commonpath + normcase,
  отбивает `~`, absolute-outside-base, traversal и symlink-escape (смешанные
  Windows-диски / UNC отбивает сам `commonpath` через `ValueError`). Все 5
  operator-supplied path-параметров в командах калибровки резолвятся внутри
  существующего exports-каталога CalibrationStore; escape возвращает
  `{ok: false}` (669abd7).

### Fixed

- **Clamp `readings_history` по каналам/лимиту + LIMIT в SQL.** Клампы в
  `_read_readings_history` — общем choke-point для ZMQ-обработчика и async-обёртки:
  строк-на-канал ≤100k, список каналов ≤64, LIMIT протолкнут в per-file запрос,
  чтобы unbounded `fetchall` не голодал engine. Non-positive limit floored к 1
  (`limit=0` раньше резал `result[-0:]` — весь список) (cd2e3ae).
- **Hardening edge’ей волны A по итогам внешнего ревью.** watchdog-enable требует
  литеральный boolean `true` (quoted YAML `"false"`/`"true"`/`"0"` мог взвести
  bench-blocked watchdog через `bool()`-truthiness — fail-closed parse);
  `readings_history` запрашивает LIMIT per-channel (общий LIMIT давал быстрому
  каналу голодить медленный до нуля строк); `/api/v1/state` и `/api/v1/alarms`
  рекурсивно редактят `acknowledged_by` (plain-dict endpoint’ы обходили
  field-whitelist и утекали identity оператора) (b132fab).
- **strict-bool флаг `cooldown_baseline` + defer/throttle дисковых чтений.**
  Quoted YAML `enabled: "false"` больше не включает карточку/badge (тот же
  fail-closed parse); populate карточки отложен до первого `showEvent`, badge
  пере-читает history-каталог не чаще раза в 5 s — убирает синхронный
  fingerprint-globbing из конструкции shell и смены фаз (7d09dae).

### Infrastructure

- Регенерация `requirements-lock.txt` (pip-compile из pyproject): добавлены
  недостающие pin’ы `lancedb`, `pypdf`, `tzdata`, `httpx`, найден stale
  `pytest-timeout`, `pillow` исправлен на 11.3.0 (старый pin нарушал `<12`).
  Новый stdlib-only `scripts/check_lock_drift.py` сравнивает PEP 503-нормализованные
  top-level имена с lock и валит CI на drift (ubuntu + windows раннеры) (730a263).
- Индекс модулей `CLAUDE.md` перестроен из docstring’ов (недоставало 80 живых
  модулей: целые подсистемы `agents/`, `sinks/`, `replay/`, `replay_engine/`,
  `utils/`, GUI `state`/`views`/`overlays`/`shared`); новый doc-lint тест требует,
  чтобы каждый живой модуль был проиндексирован, а каждый индексированный путь
  существовал (8d89f95, d4954ca).

### Known Issues

- **Windows frozen-build smoke для регенерированного lock — manual gate pending.**
  Проверка RAG lancedb-import + parquet `tz=UTC` на замороженной Windows-сборке
  ещё не прогнана; закрыть до следующего релиза.
- **TSP-watchdog inert за `keithley.watchdog.enabled=false`.** Go-live bench-gated:
  run-loop владеет однопоточным TSP-интерпретатором, pet’ы нельзя обслужить из
  того же FIFO — нужна `trigger.timer` / background-script переработка
  (задокументирована в header `tsp/cryodaq_wdog.lua`).
- **Hardlink-escape на truncating csv / `.340` экспортах — принято.** Экспортный
  каталог operator-controlled; риск ограничен доверенным периметром.

### Test baseline

- Полный `pytest -q` — зелёный: 3477 passed, 2 skipped (+84 к 3393 в 0.57.0).
  ruff clean.

### Tags

- `v0.58.0` → см. merge-коммит на master.

### Selected commits in this release

- e2cdf83 — stop_source-интерлок fail-closed (CR-2 третий call-site)
- c8e6e1a — ZMQ REP/SUB size-caps + bounded msgpack
- cd2e3ae — clamp readings_history + LIMIT в SQL
- cb2c235 — read-only REST `/api/v1` + Swagger
- 669abd7 — path_jail confinement путей калибровки
- 195f6f0 — Keithley TSP-watchdog плумбинг (inert, default-OFF)
- d2f9798 — per-cooldown fingerprint + golden-baseline (backend)
- 3ef27cb, 7d09dae — cooldown history card + strict-bool флаг
- 730a263 — регенерация lock + CI drift-gate
- b132fab — hardening edge’ей волны A (внешнее ревью)
- 8d89f95, d4954ca — перестроенный индекс `CLAUDE.md` + doc-lint

---

---
## [Unreleased]

---

## [0.57.0] — 2026-07-02 — аудит безопасности: fail-closed на краях

Пакет исправлений по итогам исчерпывающего adversarial-аудита от 2026-07-01.
Ядро safety-FSM подтверждено как надёжное; исправления закрывают места, где
периферия отказывала «в открытую» (fail-open) вместо fail-closed, плюс ряд
ошибок корректности в экспорте, аналитике и ротации холодного хранилища.
Каждое исправление сопровождается тестом, который падал на старом коде.

### Changed

- **emergency_off теперь fail-closed.** При невозможности подтвердить, что выход
  SMU выключен (ошибка записи или readback показывает «включено»), SafetyManager
  латчит `FAULT_LATCHED` вместо ложного перехода в `SAFE_OFF`. Раньше это молча
  останавливало весь мониторинг (stale/heartbeat/rate) при потенциально всё ещё
  подающем питание источнике. `Keithley2604B.emergency_off` возвращает `bool`
  (2ea47f4).
- **Rate-of-rise защита (5 K/min) взводится по временно́му охвату данных, а не по
  числу точек.** `min_span_s=30` вместо `min_points=60`: при реальном опросе
  LakeShore 2.0 s это убирает ~120-секундное «слепое окно» на входе в RUNNING и
  устойчиво к пропущенным опросам (a017358).
- **Runtime-калибровка вне диапазона откатывается на KRDG.** Значение SRDG за
  пределами калибровки больше не «замораживается» на границе с `status=OK` (что
  обнуляло dT/dt и слепило rate-защиту) — публикуется нативный KRDG (b38c360).
- **Детерминированный выбор активной калибровочной кривой после рестарта** — по
  сохранённому назначению, иначе по новейшему `fit_timestamp`, вместо порядка
  glob; `assign_curve` теперь учитывает явный `curve_id` (c55963e).
- Веб-дэшборд в документации привязан к loopback (127.0.0.1), а не 0.0.0.0
  (8701e88).

### Fixed

- **Ротация холодного хранилища больше не уничтожает `operator_log` и
  `source_data`.** Раньше экспортировалась только таблица `readings`, после чего
  весь дневной SQLite-файл удалялся. Теперь `operator_log` сохраняется в
  companion-Parquet с проверкой числа строк (fail-closed), а день с непере­несёнными
  `source_data` не ротируется вовсе; `index.json` пишется атомарно (902a194,
  61bfed3).
- **NaN больше не отравляет rolling-эстиматоры.** Non-finite отсекается перед
  подачей в alarm-v2 rate / sensor-diagnostics / vacuum-trend; один NaN не
  ослепляет оценку на всё окно (bb62193, 366fa18).
- Sensor-diagnostics не эскалирует в CRITICAL по одному лишь истёкшему времени —
  требуется фактический критический статус; канал из одних NaN больше не
  оценивается как «здоровый» (366fa18).
- Cooldown-предиктор не выдаёт NaN ETA при обнулении всех progress-весов;
  `VacuumTrendPredictor.push` отклоняет non-finite (366fa18).
- Экспорт: XLSX сохраняет малые значения (давление 1e-9 mbar больше не 0.000) и
  не падает на смешанных TEXT/REAL timestamp; CSV/XLSX/operator-log фильтруют
  дневные файлы по UTC-дню (а не по таймзоне вызывающего); HDF5 сохраняет колонку
  `status` и устойчив к коллизиям имён (0e01724).

### Infrastructure

- CI lint gate доведён до зелёного: ruff auto-fixes (F401/I001/UP), `line-length`
  поднят до 120, точечные `# noqa` (W291/E741/F841/ASYNC) с обоснованием.
- Python в CI workflow закреплён на 3.13 (3.14 был bleeding-edge, давал трения
  с pyzmq 27.x).
- Починены 7 ранее падавших тестов, которые CI не показывал, потому что
  обрывался на шаге линта до запуска pytest.

### Known Issues

- **Interlock + NaN:** пороговые интерлоки не срабатывают на NaN (сравнения с NaN
  ложны). Оставлено без изменений намеренно (риск ложных emergency-off);
  критические каналы уже покрыты NaN-fault в SafetyManager. Решение по политике —
  за архитектором.
- F17/F28 (`ColdRotationService`, `ArchiveReader`) остаются НЕ подключёнными к
  рантайму; документация приведена в соответствие (2c001ad). Логика ротации
  исправлена «на будущее».
- Отложено: регенерация `requirements-lock.txt`, base-dir jail для путей
  калибровки, удаление orphaned legacy-виджетов, sentinel для non-finite в
  persistence-first.

### Test baseline

- Полный `pytest -q` — зелёный. Затронутые срезы (core/storage/analytics/drivers)
  плюс новые audit-fix тесты проходят; ruff clean.

### Tags

- `v0.57.0` → merge-commit d187a46 (feat/audit-fixes → master).

### Selected commits in this release

- 2ea47f4 — emergency_off fail-closed
- b38c360 — calibration KRDG fallback
- 902a194, 61bfed3 — cold rotation preserves operator_log/source_data
- a017358 — rate-gate span-based
- bb62193 — NaN estimator guards
- c55963e — deterministic calibration curve selection
- 0e01724 — storage export correctness
- 366fa18 — analytics numerical guards
- 2c001ad, 8701e88 — doc accuracy (F17/ArchiveReader, loopback bind)

---

## [0.56.4] — 2026-05-08 — демо-хотфикс: Y-axis jitter + переполнение буфера предиктора

### Исправлено

- Дрожание оси Y на температурных графиках устранено через cache-driven
  deadband — виджет-сайд кэш диапазона заменяет нестабильный `pyqtgraph`
  `viewRange` (690e4ff).
- Переполнение буфера истории предиктора устранено через stride-2
  decimation вместо truncate-from-left (690e4ff).

## [0.56.3] — 2026-05-08 — Y-axis deadband + BrokerSnapshot canonical-id + predictor clock

### Исправлено

- Реальный Y-axis deadband + `BrokerSnapshot` lookup по каноническим
  id каналов вместо display-имён (`Т1 Криостат верх` и т.п.) (ab0c64f).
- `predictor.t_elapsed` считается от `reading_ts`, а не от wall clock —
  корректный ETA при ускоренном replay (841b067).

## [0.56.2] — 2026-05-08 — пост-0.56.1 хотфиксы (jitter + KB prompt + RAG)

### Исправлено

- GUI analytics jitter + landmark prompt v3 + version bump (c19663d).
- Post-v0.56.1 хотфиксы: jitter, prompt базы знаний, RAG tuning (6aff581).

## [0.56.1] — 2026-05-08 — аудит feature surface + REG-2

### Исправлено

- REG-2 — dual-channel asymptote на фазах cooldown и measurement (aa7d832).

### Изменено

- Предсказание `cooldown_prediction` унифицировано; phase-aware тесты
  выровнены под новый контракт (625621e, 4dbde78).
- CHANGELOG: аудит feature surface v0.56.1 + запись REG-2 (e06446c).

## [0.56.0] — 2026-05-08 — version bump

### Изменено

- Версия проекта поднята до 0.56.0 (version-bump commit `2d2ef32`;
  тег `v0.56.0` указывает на `d7b1df9`, `v0.56.1` — на `4dbde78`).

> Примечание: ниже в записях указаны content-коммиты (subject + diff),
> а не SHA, на которые указывают теги — теги ставились после
> housekeeping-/test-amend коммитов того же релиза.

## [0.55.5 — 0.55.16] — 2026-05-07/08 — autonomous run + Codex audit batch (теги `archive/v0.55.*`)

### Audit batch v0.55.12 — v0.55.16

Codex audit on shipped tags v0.54.0 / v0.55.4 / v0.55.6 / v0.55.7
surfaced six FAIL scopes (29 individual findings — 6 CRITICAL safety,
11 HIGH, 12+ MEDIUM). Architect chose Option B: full audit picture
before sprint planning, then sequential hotfix releases.

**v0.55.12** — CooldownAlarm safety (SCOPE 1, 5 PASS-blockers):
public `SafetyManager.latch_fault(reason, source)` API; CooldownAlarm
CRITICAL escalates safety FSM via the new entry point; engine
interlock-escalation path migrated from private `_fault()` to the
public API; `notify_phase_change()` disarms on phase skip past
cooldown; `_cycle_generation` guard aborts mid-tick CRITICAL emit on
stale state; `_COOLDOWN_DEFAULTS` extended with `auto_arm`,
`watchdog_*`, and `cold_start_skip_margin_K` so YAML overrides are
honoured (previously silently dropped); `_is_cold_start()` gate in
`arm()` skips auto-arm when the cryostat is already at base T at
engine restart, with optional SteadyStatePredictor quasi-steady
requirement.

**v0.55.14** — RAG indexer + integration (SCOPE 2 + 6, 9
PASS-blockers): merged v0.55.7 RAG integration into the v0.55.6.1
mainline (was on a parallel branch); CLI catches Ollama errors with
exit codes 3/4 and friendly stderr hints; LanceDB rebuild now uses
`create_table(mode="overwrite")` for atomic manifest commit
(crash-safe — old index stays canonical until new manifest commits)
with row-count validation post-commit; defensive parsing in
`document_loader` for non-dict phase entries and non-string operator
log messages; CLI gains `--config` flag with explicit
`rag.yaml.example` fallback; `_normalise_source_kind()` validates
`target_source_kind` against canonical
`{experiment_metadata, vault_note, operator_log}` allow-list
(rejects list / dict / multi-value / comma- and whitespace-glued
strings); side fix: prompt and `_kind_label` upgraded from buggy
`vault` to canonical `vault_note` (loader's actual emission);
`build_index()` offloads sync filesystem walks and LanceDB writes
via `asyncio.to_thread` so finalize-time rebuilds don't stall the
event loop; engine RAG fallback to `rag.yaml.example` actually
implemented (the v0.55.7 ship-report claim was previously code-drift).

**v0.55.15** — GUI overlay lifecycle (SCOPE 5, 5 PASS-blockers):
`MultiLinePanel(instrument_id=...)` for multi-instance scoping —
`channel_belongs_to_panel()` enforces the prefix and a future second
panel won't receive the first's readings; `set_connected(False)`
clears value/delta/window cells with the missing-value marker plus
a footer line; public `mark_all_stale()` exposed for shell-level
force-stale on lazy-open under disconnected engine;
`_assistant_chat_widget._on_response` now actually removes the
finished worker from `_workers` and schedules `deleteLater()` (was a
no-op `wait(0)` before — the QThread refs accumulated unbounded
across an operator session); `OverlayContainer.unregister(name)` +
`clear_all()` + `page_names` for dispose semantics, with
`register()` overwrite path also scheduling `deleteLater()` on the
displaced widget; new `_multiline_snapshot` cache at the shell level
replays into a freshly-opened MultiLine panel via the public
scoping helper, with force-stale after replay when the engine is
disconnected at lazy-open time.

**v0.55.16** — audit polish: archive-detail format prompt section
header «Cooldown:» → «Захолаживание:»; phase identifiers in the
prompt now flow through `phase_display_name` so operator output
shows «захолаживание» / «измерение» / «отогрев» / «подготовка»
instead of raw English; `cooldown_metrics` fallback string also
russified; defensive parsing tests added for malformed
`metadata.json` and invalid date strings in the F33 archive detail
path. Vault audit prompt corrected — F32 RAG and F-MultiLine driver
both first shipped at `v0.55.0`, not `v0.54.0` (the audit prompt's
target tags were off by one minor version).

Tests: 75+ new regression cases across the four releases. Pre-existing
flaky tests (test_zmq_bridge_subprocess_threading timing-sensitive
ZMQ subprocess threading) unchanged — separate from audit scope.

### Добавлено

- **F-MultiLineContinuous (v0.55.11)** — driver continuous mode for the
  Etalon MultiLine, replacing per-poll `latestlengthvalid` request /
  response with `startmeasnogui` server push. New optional config keys
  on the `etalon_multiline` instrument entry: `mode: averaged|continuous`
  (default `averaged` — backward compatible) and `target_rate_hz`
  (default `1.0`; sets the decimation rate for `Reading` emission so a
  fast cycle stream does not flood the ZMQ channel). Per-channel env
  (T/P/RH) arrives bundled inside `channeldata_` cycles in continuous
  mode — no separate `environmentdata` polling. New burst-capture
  mechanism for actuator workflows: ZMQ commands
  `multiline.burst_start` / `burst_stop` / `burst_status` and a GUI
  «Захват вибрации» row in the MultiLine overlay (1..600 s spinbox,
  start / stop button, mono status with elapsed + cycle count or saved
  path). Burst raw cycles persist as Parquet (full 17-field channeldata
  schema — length, env, intensity bounds, all 10 error flags) at
  `data/experiments/<id>/multiline_burst_<utc_iso>.parquet` when an
  experiment is active or `data/multiline_bursts/` otherwise.
  Persistence-first invariant intact — decimated cycles flow through
  the standard `Scheduler.write_immediate → SQLiteWriter → DataBroker`
  path; the burst Parquet blob is a separate auxiliary artifact written
  via `asyncio.to_thread` so the scheduler tick never blocks. The
  driver logs first-cycle latency on receipt at INFO so empirical cycle
  rate surfaces in smoke logs without extra instrumentation.
- **F-KnowledgeBaseExpansion (v0.55.7.1)** — operational knowledge
  base ready for fresh-deploy demo. New corpus root
  `data/knowledge/{equipment_manuals,procedures,reference}` tracks
  per-machine PDFs and Markdown procedures inside the repo (carved
  out of the global `data/` ignore so a clone gets the same RAG
  ingest the lab machine sees). Three new loaders extend the F32
  Stage 1 indexer through optional `build_index` kwargs: `pdf_dir`
  (pypdf, page-aware chunks с `page_number` / `document_name`
  metadata; encrypted / corrupt PDFs skip с warning),
  `procedures_dir` (markdown с H1 → title, subdir → category,
  README.md skipped), `reference_root` (operator_manual, README,
  README.en, CHANGELOG; latter section-aware per version).
  Engine startup fires `_bootstrap_rag_index_if_empty` as a
  fire-and-forget asyncio task so a fresh checkout populates the
  index без manual CLI; ready signal не блокируется.
  Operator-driven rebuild surfaces через new ZMQ commands
  `rag.rebuild_index` / `rag.rebuild_status` and «Обновить индекс»
  button в KnowledgeBasePanel toolbar (single-instance enforced;
  status-poll @1 Hz; engine error surfaces verbatim). Pretty
  source labels («Etalon MultiLine — стр. 5», «Процедура:
  Аварийное отключение», «CHANGELOG v0.55.7») унифицированы через
  `prettify_source_label` для GUI snippet card и
  `FORMAT_KNOWLEDGE_QUERY_USER` prompt. New
  `scripts/download_manuals.sh` best-effort downloader для public
  manual URLs; equipment_manuals/ ships с four PDFs (Etalon
  MultiLine v2.2, LakeShore 218S, Keithley 2600B Reference,
  Thyracont VSP63D — total ~1100 pages). Three seed procedures
  (`cooldown_protocol.md`, `emergency_shutdown.md`,
  `troubleshooting/gpib_disconnect.md`). Default embedding-model
  fallback в engine RAG init flipped `multilingual-e5-small` →
  `qwen3-embedding:0.6b` aligning с v0.55.7.0.1 modernization
  (1024-dim, /api/embed). Persistence-first invariant intact —
  все loaders read-only.
- **F32 Stage 1 RAG indexer** — standalone semantic search foundation
  over the experiment archive (metadata + F31 vault notes + operator
  log entries). New module `cryodaq.agents.rag` with `document_loader`
  (chunking + corpus walkers), `indexer` (LanceDB persistence), and
  `searcher` (top-K cosine lookup with optional `source_kind` filter).
  Embeddings come from Ollama `multilingual-e5-small` via a small
  `EmbeddingsClient` wrapping the existing `OllamaClient.embed()`
  (added in this commit). New CLI scripts `cryodaq-rag-index` and
  `cryodaq-rag-search`. Stage 2 (`AssistantQueryAgent` integration) is
  out of scope and lives in a separate spec. New deps: `lancedb` (Mac
  arm64 wheel verified). New config: `config/rag.yaml.example`.
- **F31 sinks foundation** — new `cryodaq.sinks` module with two sinks:
  `VaultSink` (writes a Markdown note with YAML frontmatter to a
  filesystem vault directory on experiment finalize / stop / abort) and
  `WebhookSink` (POSTs the JSON-serialized `ExperimentExport` to a
  configured URL). `SinkRegistry` loads sinks from `config/sinks.yaml`
  (or `sinks.local.yaml` override) and fans out concurrently. Dispatch
  is fire-and-forget — `experiment_finalize` does not block on sinks;
  failures are captured in `SinkResult` and exposed through the new
  `sinks_status` ZMQ command (last-20 results buffer). New config:
  `config/sinks.yaml.example`. Pre-requisite for F32 (RAG indexer).
- **F-MultiLine Stage 1** — Etalon MultiLine TCP/IP integration:
  interferometric length metrology over a new line-based ASCII TCP
  transport. New driver type `etalon_multiline` registered in the
  engine; readings publish on `<name>/length_ch<N>` (mm) plus
  `<name>/env_<temperature|pressure|humidity>`. Mock mode required for
  development without MultiLine.exe (lab-PC-only). Stage 2 features
  (deformation analysis, channel alignment, MLAC/AC operations,
  frontend splitter/shutter control) are out of scope and live in a
  separate spec. New module: `cryodaq.drivers.transport.tcp` (first new
  transport class since project inception, mirrors the `serial.py`
  asyncio cleanup + error-wrapping pattern).
- **F-LegacyChannelMap** — `--legacy-channel-era` flag on the launcher
  and the standalone replay engine. Loads a predefined channel-rename
  map (`pre-2025-02` covers the thermal-bridge era: Т10→Т12, Т9→Т10,
  Т8→Т9) and applies it on the SQLite/Directory replay path so old
  recordings publish under the post-bridge canonical labels (Т11/Т12).
  CurveReplay (`cooldown_v5/*.json`) is post-bridge era and is not
  touched. New module: `cryodaq.replay_engine.legacy_channel_maps`.

### Исправлено

- **F-ConfigChannelDrift** — `config/cooldown.yaml` channel mapping
  aligned with C6 / F-ChannelLandmarks canonical Т11/Т12. Pre-fix the
  file referenced pre-C6 names (`Т7 Детектор` / `Т5 Экран 77К`), which
  meant the cooldown predictor on the real lab PC watched detector
  temperature instead of the 2nd-stage GM cooler. Replay-mode was
  already correct via the v0.53.1 defensive override; this aligns the
  real-lab path.

---

## [0.55.4] — 2026-05-07 — политика CooldownAlarm + Т11/Т12 как critical channels + переименование «Алармы» → «Тревоги»

### Добавлено

- **Политика CooldownAlarm** — `auto_arm: True` по умолчанию, с
  фильтром через `SteadyStatePredictor` (не срабатывает пока идёт
  охлаждение); watchdog по умолчанию отключён до тонкой настройки
  под конкретное развёртывание (коммит `a1ba0b6`).

### Изменено

- **`critical_channels` в `safety.yaml`** — сужено до `Т11` / `Т12`
  (позиционно зафиксированные ступени GM-cooler-а). Остальные
  термометрические каналы больше не несущие для FSM безопасности
  (коммит `50909e3`).
- **Операторские строки** — «Алармы» → «Тревоги» в 11 точках
  (меню, тулбар, статус-бар, заголовки диалогов). Имена классов
  (`AlarmPanel`, `AlarmManager` и т.д.) и имена файлов сохранены —
  кодовые идентификаторы остаются на английском (`Alarm*`)
  (коммит `e642ba9`).

### Исправлено

- **Стиль подтверждённых тревог в SeverityChip** — теперь применяется
  и в v1-ветке alarm engine. В v0.55.2 фикс был внесён только в
  v2-ветку; v1 сохраняла яркий цвет, оставляя «всё ещё срабатывающий»
  чип на подтверждённых тревогах (коммит `0918a86`).
- **Формат счётчика в TopWatchBar** — несоответствие short_id и
  full_name приводило к зависанию «0/16 норма» на заполненных
  экспериментах. Теперь бар штампует показания под коротким id
  канала, согласованно с реестром источников счётчика
  (коммит `abfedb9`).

### Closing commit

- `1a196e6` (chore: bump версии 0.55.3 → 0.55.4).

---

## [0.55.3] — 2026-05-07 — квазистационарный режим + API `expected_value`

### Добавлено

- **Детектор квазистационарного режима в `SteadyStatePredictor`** —
  фильтр по остаткам и наклону определяет, что канал вышел в
  квазистационарный режим (охладился, но всё ещё дрейфует).
  Параметры вынесены в `config/cooldown.yaml`
  (коммиты `2ab8c5a`, `230571f`).
- **API `CooldownService.expected_value(channel, ts)`** — запрос
  предсказанного стационарного значения на будущий момент времени.
  Опирается на `SteadyStatePredictor` (коммит `8983f88`).
- **Метка квазистационарности в GUI** — `CooldownPredictionWidget`
  отображает метку «Стационарное состояние», когда предиктор
  сообщает об устойчивой подгонке в режиме IDLE (коммит `6036c9d`).

### Тесты

- `test_steady_state` — синтетические фикстуры квазистационарного
  режима (`e7d8b8d`).
- `test_cooldown_service.expected_value` — поведение API (`97e61e4`).
- `test_gui` — рендер виджета квазистационарного состояния
  (`8ded90b`).

### Closing commit

- `2da7e64` (chore: bump версии 0.55.2 → 0.55.3).

---

## [0.55.2] — 2026-05-07 — общий проход по дизайну и поведению GUI (16 исправлений)

Сводный проход по GUI: 16 исправлений (7 пунктов от архитектора,
14 пунктов по design system, 1 follow-up второго цикла). В основном
расчистка по токенам — удалены hex-литералы, фиксированные размеры
переведены на токены `theme.py`, чипы подтверждённых тревог
визуально приглушены.

### Исправлено

- **Диагностика датчиков — тёплые каналы** — тёплые опорные каналы
  больше не попадают в alarm-сводку и сводку диагностики; не
  считаются дважды (коммиты `c7030f5`, `475b2bf`).
- **Ширина метки в архиве и chat-bubble** — выводится из токенов
  `SPACE_*` (коммит `caa151f`).
- **Панель Keithley** — убрана арифметика над токеном
  `FONT_LABEL_SIZE` (коммит `417758b`).
- **Журнал оператора** — ширина колонки автора и высота сообщения
  выведены из токенов (коммит `01c3a3c`).
- **Quick log block** — отступы инпута и размер кнопки выведены из
  токенов (коммит `56330d3`).
- **Top watch bar** — тип шрифта и spacing для контекстной полосы
  выведены из токенов (коммит `d1e60a7`); видимые каналы помечаются
  «норма» при конструировании, чтобы бар не был пустым при холодном
  старте (коммит `62e2546`).
- **Sensor cell** — spacing, padding, hint-шрифт выведены из токенов
  (коммит `337c19d`).
- **Панель теплопроводности** — верхний тулбар + двухколоночная
  сетка каналов (коммит `2ea27ce`).
- **Phase stepper** — прошедшие «таблетки» заполняются `STATUS_OK`
  (раньше использовался прямой цветовой литерал) (коммит `5081319`).
- **Аналитика — фаза MEASUREMENT** — карточка Keithley убрана из
  layout-а MEASUREMENT (относится только к другим фазам)
  (коммит `10b86f5`).
- **Панель архива** — высоты текстовых view выведены из токенов
  `SPACE_*` (коммит `2942b2b`).
- **График аналитики** — hex-литералы для трасс и осей заменены на
  токены палитры (коммиты `c20a7ca`, `f603615`).
- **Панель тревог** — подтверждённые тревоги визуально приглушены
  (severity chip обесцвечивается) (коммит `9139b8a`).

### Closing commit

- `74b3bdb` (chore: bump версии 0.55.1 → 0.55.2).

---

## [0.55.1] — 2026-05-07 — батч аудит-фиксов (H1-H7 + H9 + S1 + V1)

Батч исправлений по аудиту: блокировка async-loop, fire-and-forget
GC, проглатывание ошибок и один пункт по безопасности из аудита
v0.55.0.

### Изменено

- **Окно холодного старта F-TimeoutRelax** — увеличено с 25 с до 50 с
  для cold-start Ollama на медленных операторских ноутбуках
  (коммит `51c1dd8`).
- **Bind веб-сервера** — `127.0.0.1` (было `0.0.0.0`);
  задокументировано как развёртывание только на loopback, не
  LAN-facing (коммит `eb84e44`).

### Исправлено

- **F31 sinks — async offload** — чтение метаданных и запись в vault
  вынесены через `asyncio.to_thread` (никакого блокирующего I/O в
  event loop) (коммит `ba11330`).
- **Replay — async offload** — загрузка из SQLite вынесена через
  `asyncio.to_thread` (коммит `75315eb`).
- **Поиск F32 RAG** — защита от расхождения размерностей embedding-ов
  запроса через защитную shape-проверку (избегаем исключения от
  LanceDB на устаревших корпусах) (коммит `36d15e2`).
- **ChartDispatcher** — сохраняем strong-ref на set fire-and-forget
  задач, чтобы GC не собирал диспатчи графиков на лету
  (коммит `eb023c1`).
- **Останов движка** — дренируем in-flight диспатчи sinks перед
  закрытием движка (была гонка на KeyboardInterrupt)
  (коммит `cfc847e`).
- **Ошибки команд в web** — логируем сбои engine-команд, не
  проглатываем их (коммит `040b6ab`).
- **Ключ summary в F31** — читаем `summary_metadata`, а не `summary`
  (переименование ключа было неполным в v0.55.0) (коммит `f44abf3`).
- **Версия пакета** — bump 0.52.9 → 0.55.1 в `pyproject.toml` (отстал
  от цепочки тегов) (коммит `cb6bff3`).

### Closing commit

- `51c1dd8`.

---

## [0.55.0] — 2026-05-07 — закрытие autonomous-run-2026-05-07 + аудит CHANGELOG

Tag-only релиз, закрепляющий работу autonomous-run-2026-05-07
(каталогизирована под [0.54.0] по правилу-зонтику архитектора) и
выкатывающий два дисциплинарных патча по CHANGELOG.

### Изменено

- **F-CHANGELOG-Audit** — заполнены пробелы для v0.52.10..v0.53.2
  (коммит `2771584`) и перераспределены подсекции Keep a Changelog
  (Added/Changed/Fixed) для v0.53.x ретроспективно
  (коммит `ff9bead`). Приводит исторический «хвост» к текущей
  дисциплине.

### Замечание

Основная масса фич autonomous-run-2026-05-07 (F31 sinks, F32 RAG
indexer, F-MultiLine Stage 1, F-LegacyChannelMap, F-ConfigChannelDrift)
закоммичена в диапазоне этой версии (`v0.54.0..v0.55.0`), но
каталогизирована под [0.54.0] по правилу-зонтику архитектора:
v0.54.0 = autonomous-run-2026-05-07. Сама v0.55.0 — это tag bump,
закрывающий run.

### Closing commit

- `1ee46a5` (test: F32 цикл 3 — детерминированные mock embeddings).

---

## [0.54.0] — 2026-05-07 — зонтик autonomous-run-2026-05-07 (channel landmarks + sinks + RAG + MultiLine + replay maps + bot polish + chat overlay)

Зонтичный релиз для работы autonomous-run-2026-05-07. Объединяет
фичи F-ChannelLandmarks / F-TimeoutRelax / F-MockPredictor / F33 /
F34 / F-BotPolish, помеченные тегом v0.54.0, с работой F31 / F32 /
F-MultiLine Stage 1 / F-LegacyChannelMap / F-ConfigChannelDrift,
закоммиченной под тегом v0.55.0. По правилу архитектора все фичи
autonomous-run сидят под одним зонтиком — v0.54.0.

### Добавлено

- **F-ChannelLandmarks** — слой системного тождества каналов. В
  `config/physical_alarms.yaml` появляется опциональная секция
  `landmarks:`, которая прикрепляет hardware-fixed каналы (Т11/Т12 —
  ступени GM-cooler-а) к каноническим ролям плюс к операторским
  алиасам (например, «азотная плита» → Т11).

  - Новая функция
    `cryodaq.core.physical_alarms_config.load_channel_landmarks()`
    парсит секцию; отсутствие или некорректность конфигурации даёт
    `{}` (движок не падает).
  - `ChannelManager.set_landmarks()` / `get_landmarks()` несут карту
    через движок; заполняется на старте, читается query-агентом.
  - `IntentClassifier._build_channel_hint()` теперь формирует
    двухуровневый список — сначала landmarks с алиасами, потом
    каналы эксперимента — и сообщает Гемме, что landmark-алиасы
    перевешивают именование на уровне эксперимента при коллизиях.

  Закрывает production-баг с классификацией «азотная плита → Т12».
  Обратная совместимость: пропуск секции `landmarks:` сохраняет
  старую структуру промпта v0.53.x (единый список «Доступные
  каналы») (коммит `8f0af9a`).

- **F33 — архивный query-агент** — `AssistantQueryAgent` теперь
  отвечает на вопросы об архиве экспериментов и истории тревог.
  Три новых значения `QueryCategory`:

  - `archive_list` — «какие эксперименты были на этой неделе» /
    «покажи архив за месяц». Возвращает список карточек
    (experiment_id, title, sample, operator, started, status). Окно
    по умолчанию — 7 дней.
  - `archive_detail` — «детали эксперимента <ID>» / «сколько часов
    длился cooldown в <ID>». Возвращает полную карточку (sample,
    operator, status, duration, фазы, метрики cooldown из
    metadata.json).
  - `alarm_history` — «сколько раз сработал overheat за неделю» /
    «статистика тревог». Возвращает счётчики triggered/cleared плюс
    разбивку по `alarm_id`.

  Все три категории — read-only через новый `ArchiveAdapter`,
  оборачивающий `ExperimentManager.list_archive_entries` /
  `get_archive_item` и `AlarmStateManager.get_history`. SQL-DSL и
  write-capabilities явно вне scope. Ядро F30 query-агента,
  алгоритм `IntentClassifier` и `experiment_adapter` без изменений.
  Цикл 2 (коммит `0a21cba`) вынес сканы файловой системы архива
  в `asyncio.to_thread` (коммит `dc5350b`, цикл 2 `0a21cba`).

- **F34 — GUI chat overlay** — новый `AssistantChatPanel`
  (`gui/shell/overlays/assistant_chat_panel.py`) переиспользует
  F30-бэкенд `AssistantQueryAgent`. Оператор печатает свободный
  вопрос; GUI шлёт ZMQ-команду `assistant.query` через
  неблокирующий `ZmqCommandWorker`; движок диспатчит в
  `_handle_assistant_query_command` (таймаут 25 с — укладывается
  в 30-секундный envelope медленных команд REP-сервера; команда
  добавлена в `_SLOW_COMMANDS` в `core/zmq_bridge.py`). Ответ
  рендерится в bubble-ах (оператор справа на `ACCENT`, ассистент
  слева на `SURFACE_CARD`, ошибки `STATUS_WARNING` с префиксом ⚠).
  История — только in-session (без диска). Иконка ToolRail — Phosphor
  `ph.chat-circle`, слот «Помощник Гемма» между «Служебный лог» и
  «Приборы». Telegram-путь сохраняет 60-секундный бюджет через
  `telegram_commands.py` (отдельный путь — не через ZMQ).
  `AssistantQueryAgent`, `IntentClassifier`, `QueryRouter`,
  `OutputRouter` и класс `ZMQCommandServer` без изменений
  (коммит `0ab42f2`, цикл 3 `a5eccb9`).

- **F-BotPolish** — четыре точечных исправления в pipeline Геммы по
  наблюдаемым лабораторным проблемам 2026-05-07.

  1. *Markdown → HTML в `OutputRouter`*: Гемма выдаёт Markdown по
     промптам (`ALARM_SUMMARY_SYSTEM`); Telegram-бот шлёт с
     `parse_mode=HTML`, поэтому до сих пор `*` и `**` рендерились
     буквально. Конверсия (`**bold**` → `<b>bold</b>`, `*it*` →
     `<i>it</i>`, `` `c` `` → `<code>c</code>`, заголовки `#`
     срезаются) применяется **только** к target `TELEGRAM`.
     `OPERATOR_LOG` и `GUI_INSIGHT` оставляют сырой Markdown. Маркеры
     bullet-ов (`* item`) не конвертируются — italic-regex требует
     символов между маркерами.
  2. *Форматирование float в `ContextBuilder`*: значения округляются
     один раз на стыке (`AlarmContext.values: dict[str, Any]`) —
     криоканалы (Т*) → 1 знак, давление (|v| < 1e-3 или > 1e6) →
     2 значащих в scientific, прочие → 2 знака. Убирает протекание
     12-разрядных «4.347123…» в промпт.
  3. *Sanity-hint на неправдоподобных значениях*: `T_cryo > 500 K`
     или `< −50 K` помечается в `recent_readings_text` как «вероятно
     сбой сенсора»; Гемма теперь формулирует ответ как сбой датчика,
     а не как «check cooling».
  4. *Дедуп на уровне событий в `AssistantLiveAgent._event_loop`*:
     одинаковые события `alarm_fired` в окне 30 с (по `alarm_id` +
     bucket) отбрасываются до slice-обработчика — тревоги, которые
     кратковременно сбрасываются и снова срабатывают, больше не
     порождают дубликаты Telegram-нарративов.

  Цикл 2 (коммит `bfe49d2`) расширил до скользящего окна дедупа
  плюс channel-aware определения давления. Slice-обработчики, путь
  F30 query-агента, промпт `ALARM_SUMMARY_SYSTEM`, `TelegramNotifier`
  и `parse_mode=HTML` в `TelegramCommandBot._send()` без изменений
  (коммит `53981a1`).

- **F-MockPredictor** — `CooldownPredictionWidget` рисует
  горизонтальную асимптоту + полосу ±σ + бейдж «Стационарное
  состояние ≈ X K», когда встроенный `SteadyStatePredictor`
  сообщает об устойчивой подгонке (`percent_settled ≥ 30 %`), а
  бэкенд `CooldownDetector` находится в IDLE. Заменяет пустой
  плейсхолдер «Охлаждение не активно» на Mac mock и на любом другом
  уже-охлаждённом потоке. Шаблон повторяет `RThermalLiveWidget`
  буквально (окно 600 с, обновление 30 с, порог settle 30 %,
  токены `STATUS_INFO`). Цикл 2 (коммит `f45bc42`) подаёт
  температуру холодной ступени через новый сеттер
  `CooldownPredictionWidget.set_cold_temperature_reading()`,
  который вызывается из `MainWindowV2._dispatch_reading` каждый раз,
  когда приходит K-показание на каноническом landmark-канале Т12.
  Устаревшие forecast-кривые теперь очищаются во внутреннем
  `PredictionWidget`, когда state machine уходит из active-prediction
  ветки. Бэкенд (`CooldownDetector`, `CooldownService`,
  `SteadyStatePredictor`) без изменений (коммит `5276fc1`,
  цикл 2 `f45bc42`).

- **F31 — операторские sinks** — новый модуль `cryodaq.sinks` с
  двумя sink-ами: `VaultSink` (пишет Markdown-заметку с YAML
  frontmatter в каталог vault-а файловой системы при experiment
  finalize / stop / abort) и `WebhookSink` (POST-ит
  JSON-сериализованный `ExperimentExport` на сконфигурированный URL).
  `SinkRegistry` грузит sinks из `config/sinks.yaml` (или override
  `sinks.local.yaml`) и веером шлёт параллельно. Диспатч —
  fire-and-forget — `experiment_finalize` не блокируется на sinks;
  сбои фиксируются в `SinkResult` и экспонируются через новую
  ZMQ-команду `sinks_status` (буфер последних 20 результатов).
  Новый конфиг: `config/sinks.yaml.example`. Предусловие для F32
  (RAG indexer). Цикл 2 (коммит `f456938`): `dispatch()` никогда
  не пробрасывает исключения от некорректно работающего sink-а
  (коммит `fb4c43b`, цикл 2 `f456938`).

- **F32 Stage 1 — RAG indexer** — самостоятельный фундамент
  семантического поиска по архиву экспериментов (метаданные +
  vault-заметки F31 + записи operator log). Новый модуль
  `cryodaq.agents.rag` c `document_loader` (чанкинг + walker-ы по
  корпусам), `indexer` (персистенс в LanceDB) и `searcher`
  (top-K cosine lookup с опциональным фильтром `source_kind`).
  Эмбеддинги — от Ollama `multilingual-e5-small` через тонкий
  `EmbeddingsClient`, оборачивающий существующий
  `OllamaClient.embed()`. Новые CLI-скрипты `cryodaq-rag-index` и
  `cryodaq-rag-search`. Stage 2 (интеграция с
  `AssistantQueryAgent`) вне scope-а и живёт в отдельной
  спецификации. Новые зависимости: `lancedb` (Mac arm64 wheel
  проверен). Новый конфиг: `config/rag.yaml.example`. Цикл 2
  (коммит `56e0f76`) спустил фильтр `source_kind` в `WHERE` LanceDB.
  Цикл 3 (коммит `1ee46a5`) добавил детерминированные mock
  embeddings и baseline-гарду (коммит `3cf3506`, цикл 2 `56e0f76`,
  цикл 3 `1ee46a5`).

- **F-MultiLine Stage 1** — интеграция Etalon MultiLine TCP/IP:
  интерферометрическая длинометрия через новый line-based ASCII TCP
  транспорт. Новый тип драйвера `etalon_multiline` зарегистрирован
  в движке; показания публикуются на `<name>/length_ch<N>` (мм)
  плюс `<name>/env_<temperature|pressure|humidity>`. Mock mode
  обязателен для разработки без `MultiLine.exe` (lab-PC-only).
  Stage 2 (анализ деформации, выравнивание каналов, MLAC/AC
  операции, управление frontend splitter/shutter) — вне scope-а и
  живёт в отдельной спецификации. Новый модуль:
  `cryodaq.drivers.transport.tcp` — первый новый транспортный
  класс с момента старта проекта, повторяет паттерн asyncio cleanup
  + error-wrapping из `serial.py`. Цикл 2 (коммит `7f190fa`)
  пометил все 10 полей ошибок как `SENSOR_ERROR` (коммит `2ebde3b`,
  цикл 2 `7f190fa`).

- **F-LegacyChannelMap** — флаг `--legacy-channel-era` на лончере и
  на standalone replay-движке. Грузит предзаданную карту
  переименования каналов (`pre-2025-02` покрывает эпоху
  thermal-bridge: Т10→Т12, Т9→Т10, Т8→Т9) и применяет её на
  SQLite/Directory replay-пути, чтобы старые записи публиковались
  под post-bridge каноническими метками (Т11/Т12). CurveReplay
  (`cooldown_v5/*.json`) относится к post-bridge эре и не
  затрагивается. Новый модуль:
  `cryodaq.replay_engine.legacy_channel_maps` (коммит `b096a2d`).

### Изменено

- **F-TimeoutRelax** — таймауты команд и запросов ослаблены под
  более медленное железо (cold-start Ollama на тормозящем
  операторском ноутбуке).

  - `engine.py`: `_LOG_GET_TIMEOUT_S` и
    `_EXPERIMENT_STATUS_TIMEOUT_S` подняты с 1.5 с до 5.0 с. Обе
    команды читают из SQLite + experiment manager (~50 мс типично,
    ~500 мс p99 под нагрузкой); 5 с дают ~10× запас на cold-cache
    или IO-конкуренцию без влияния на бюджет latency, видимый
    оператору.
  - `notifications/telegram_commands.py`: per-query Telegram dispatch
    `wait_for(...)` поднят с 30 с до 60 с, согласованно с текстом
    операторского сообщения. Cold-start Ollama может потратить
    20–40 с на загрузку модели в RAM; последующие запросы остаются
    быстрыми.
  - `agents/assistant/live/agent.py` `AssistantConfig` defaults
    подняты в 2 раза по всему фронту: `timeout_s` 30→60,
    `query_intent_timeout_s` 10→20, `query_format_timeout_s` 20→40.
    YAML-override-ы без изменений.

  Safety-критичные таймауты (ZMQ heartbeat-ы, watchdog-и, пороги
  fault-on-silence) НЕ затрагиваются (коммит `35e78ee`).

### Исправлено

- **F-ConfigChannelDrift** — мэппинг каналов в
  `config/cooldown.yaml` приведён к каноническим Т11/Т12 из C6 /
  F-ChannelLandmarks. До фикса файл ссылался на pre-C6 имена
  (`Т7 Детектор` / `Т5 Экран 77К`), что означало: cooldown predictor
  на реальном лабораторном PC смотрел температуру детектора вместо
  второй ступени GM-cooler-а. Replay-mode уже был корректен через
  defensive override v0.53.1; этот фикс выравнивает real-lab путь
  (коммит `3f0abeb`).

### Closing commit

- `0a21cba` (fix: F33 цикл 2 — offload архива).

---

## [0.53.2] — 2026-05-06 — стек считывания предиктора + проводка кнопок горизонта

Closing commit: `c48b501`.

### Добавлено

- **Стек считывания предиктора** — single-horizon readout заменён на
  стек из 6 горизонтов (1/3/6/12/24/48 ч). Каждая строка показывает
  значение и CI независимо. Цикл 1 (`88f7331`).

### Изменено

- **Проводка X-диапазона по кнопкам горизонта** — кнопки в заголовке
  управляют X-диапазоном графика через `_apply_x_range()` (цикл 2,
  `c48b501`). Правый край = `time.time() + horizon*3600`, левый край —
  первая выборка истории, fallback `now - 60 s` если пусто.
  Re-anchor на `set_horizon` / `set_history` / `set_prediction`.

### Исправлено

- **Скрытый баг с неактивными кнопками** — существовавший сигнал
  `horizon_changed` не имел production-консьюмера; цикл 2 завёл
  кнопки напрямую с сохранением сигнала для обратной совместимости.
  Поймал Codex в цикле 1 FAIL/HIGH.

### Тесты

- 6 новых widget-тестов (15 → 21); 188 пройдено в более широкой
  регрессии.
- Codex PASS цикл 2 из 3.

---

## [0.53.1] — 2026-05-06 — F-ReplayPredictor — CooldownService поверх replay-потока

Closing commit: `fcd717f`.

### Добавлено

- **F-ReplayPredictor** — `CooldownService` присоединён к
  `ReplayEngine`. Виджет предиктора активируется при replay-е
  реальных cooldown-кривых на Mac mock.

### Изменено

- **Инструментовка ReplayEngine** — `DataBroker` вставлен между
  источником и PUB-очередью. `CooldownService` подписывается на
  брокера, обрабатывает показания и публикует производные метрики
  обратно через broker → PUB → ZMQ-сокет.
- Defensive override каналов (Т12/Т11) в `ReplayEngine` гасит дрейф
  `cooldown.yaml`, не трогая конфиг реальной лаборатории.

### Исправлено

- Slow-joiner регрессия в `test_replay_engine_heartbeat`, всплыла
  когда вставка брокера сдвинула тайминги. Митигирована через
  паттерн subscribe-before-source (Stage 4b в v0.53.0).

### Заведено

- F-ConfigChannelDrift — выравнивание мэппинга в реал-лабораторном
  `cooldown.yaml` (закрыто в последующем unreleased-батче v0.55.0).

### Тесты

- 3 новых теста; 178/178 стабильно за 3 последовательных прогона.
- Codex PASS цикл 2 из 3 (цикл 1 — проблема с фикстурой на чистом
  checkout-е).
- Архитекторский smoke 2026-05-06 21:45: предиктор активируется
  end-to-end на `cooldown_v5` curve при `speed=50`, рендерится
  полная траектория ~17 ч + envelope CI 67% ±2.73 K; readout
  «Через 1 ч: 64.66 K» заполнен.

---

## [0.53.0] — 2026-05-06 — F-Replay — 5-stage replay mode + predictor bootstrap

Closing commit: `a502814` (late hotfix двинул тег от `1bd3b13`).

### Добавлено

- **Replay mode F-Replay** — 5-этапный operator-visible путь replay-а:
  - Этап 1 (`4efac0c`) — фикс схемы.
  - Этап 2 (`7795ab9`) — replay-трансформации + CLI.
  - Этап 4 (`fef291d`) — `--replay` на лончере, бейдж `TopWatchBar`,
    листинг источников.
  - Этап 4b (`33dc1b0`) — UX-полировка: сдвиг timestamp-а, dispatch
    бейджа, персистенс заголовка.
  - Этап 5 (`e4da30a`) — bootstrap-подсказка предиктора + операторская
    документация.

### Изменено

- **Паритет cmd-plane у `replay_engine`** — этап 3 (`7d0a22c`) принёс
  паритет PUB+REP+heartbeat с live-движком, обработку refuse порта
  и флаг `--force-replay`.

### Исправлено

- **Этап 4c** (`1bd3b13`) — edge case в `DirectoryReplay`, когда
  первый файл не пустой.
- **Late hotfix** (`a502814`) — фикс затенения `QTimer` из регрессии
  этапа 4b, пойманной в архитекторском smoke. Тег перенесён сюда с
  `1bd3b13`.

### Заведено

- F-ReplayPhases (закрыто в последующем unreleased-батче v0.55.0).
- F-LegacyChannelMap (закрыто в последующем unreleased-батче v0.55.0).

### Codex review

- P2-находки отклонены по архитекторскому колл-у: коллизия non-loopback,
  захардкоженный путь предиктора, комбинация `--force-replay`+live
  engine — все отложены в follow-up спецификации.

### Тесты

- 1472 пройдено в полной регрессии.

---

## [0.52.11] — 2026-05-06 — `cooldown_v5/` в `.gitignore`

Closing commit: `788cd27`.

### Изменено

- Опорные данные `cooldown_v5/` добавлены в `.gitignore` —
  кривые от оператора не должны жить в репозитории.

### Замечания

- Bootstrap модели предиктора (активация cooled-mock) отложен на
  v0.53.0 replay mode.

---

## [0.52.10] — 2026-05-06 — hotfix: откат инструментовки D2-TEMP

Closing commit: `bc36b1d`.

### Исправлено

- **autoRange по Y-оси на температурной панели** на Mac mock —
  4-коммитная серия; инструментовка D2-TEMP откачена.

---

## [0.52.9] — 2026-05-05 — chore(tests): маркер ollama

### Изменено

- **Тестовый набор больше не требует Ollama-демон по умолчанию.**
  Pytest теперь регистрирует маркер `ollama`; `addopts` исключает
  его (`-m 'not ollama'`). Единственный live-Ollama тест
  (`test_smoke_real_ollama`) собран как `@pytest.mark.smoke +
  @pytest.mark.ollama`. Все остальные тесты в
  `tests/agents/assistant/` используют `AsyncMock` / `MagicMock` —
  дополнительная маркировка не требуется.

  Запуск Ollama-зависимых тестов явно: `pytest -m ollama`.
  Полный набор (без Ollama): `pytest` — 2452 пройдено, 1 исключён.

  Замечание: фоновый демон `ollama serve` всё ещё, вероятно,
  реальный источник RAM-нагрузки во время pytest-а на dev-ноутах
  (lazy client init в `OllamaClient.__init__` означает, что импорты
  не идут в сеть). Это изменение — защитное: никакой тест не
  тащит live-зависимость молча.

## [0.52.8] — 2026-05-05 — per-widget селектор временного окна

### Исправлено

- **Live-данные TemperatureOverview и PressureCurrent невидимы при
  временном окне по умолчанию.** Оба виджета подписывались на
  `GlobalTimeWindowController`, чей дефолт `TimeWindow.ALL` возвращает
  бесконечный диапазон (7-дневная подгрузка истории). С autoRange
  на масштаб дней live-обновления масштаба минут были физически
  невидимы (~10 ppm сдвига по X на каждое новое измерение).

  Воспроизведено 2026-05-05 с инструментовкой [D3]: window=Всё,
  X-range ~351 730 с, Y-range 328 K. Серия T11 росла 26→28 за
  секунды (live-данные шли), но движение хвоста трассы было
  субпиксельным.

  Исправление: общий виджет `TimeWindowSelector` (5 кнопок:
  1 мин / 1 ч / 6 ч / 24 ч / Всё, по умолчанию 1 ч).
  TemperatureOverview и PressureCurrent имеют каждый свой локальный
  селектор; глобальный контроллер остаётся для будущих виджетов.
  Расширение окна триггерит debounced (1 с) повторную подгрузку
  через `readings_history`.

### Добавлено

- `cryodaq.gui.widgets.shared.time_window_selector.TimeWindowSelector` —
  переиспользуемый 5-кнопочный селектор временного окна, эмитит
  `TimeWindow` enum на изменение.

### Ссылки

- Инструментовка D1/D2 сохранена в `prediction_widget.py` и
  `VacuumPredictionWidget` для capture-сессии на лабораторном PC.
  Здесь не в scope.
- Инструментовка D3 удалена (дефект подтверждён и исправлен).

### Тестовая база

Тесты: 161+ пройдено (точное число — из полного прогона на момент
коммита).

### Теги

- `v0.52.8` — fix/analytics-v0.52.8-window-selector → master

## [0.52.7] — 2026-05-05 — hotfix падения при клике на вкладку аналитики

### Исправлено

- **Падение вкладки аналитики при клике** (SIGABRT: "QThread:
  Destroyed while thread is still running"), когда любой активный
  эксперимент находится в фазе vacuum, cooldown, measurement, warmup
  или disassembly.

  Корневая причина: T7 в v0.52.6 добавил вызовы `_fetch_history()`
  (порождающие QThread-ы `ZmqCommandWorker`) в конструкторы
  `TemperatureOverviewWidget` и `PressureCurrentWidget`. Эти два
  виджета занимают fallback-layout. Когда
  `_ensure_overlay("analytics")` нажимался при активном
  эксперименте, `AnalyticsView.__init__()` эагерно применял
  fallback-layout (создавая оба виджета и запуская их workers),
  после чего `_ensure_overlay` сразу вызывал
  `set_phase(active_phase)`, уничтожая fallback-виджеты через
  `deleteLater()` до завершения их QThread-workers.

  Структурный фикс: `AnalyticsView` больше не применяет никакого
  layout в `__init__`. Первый вызов `set_phase()` применяет layout
  прямо в нужный phase-слот. `_ensure_overlay` всегда вызывает
  `widget.set_phase(current_phase_or_None)` ровно один раз после
  создания. Виджеты строятся на финальной позиции и никогда не
  уничтожаются сразу.

### Ссылки

- Диагноз: `artifacts/regressions/v0.52.7-anal-crash/diagnosis.md`.
- Подтверждённый класс падения: H1 (QThread destroyed mid-flight).
- Подтверждены все 5 затронутых фаз: vacuum, cooldown, measurement,
  warmup, disassembly.
- Латентный S22/D.3 (паттерн worker-cleanup в `closeEvent`):
  отложен до v0.53.0.

### Тесты

- 7 существующих тестов обновлены под новый контракт:
  `view.set_phase(None)` обязателен перед доступом к
  `active_widgets()` (ранее предполагался эагерным layout-ом
  в `__init__`).
- 2 новых регрессионных теста: `test_lazy_open_with_active_experiment_*`
  и `test_lazy_open_without_active_experiment_uses_fallback`.

### Тестовая база

2444 пройдено (2442 baseline + 2 новых), 4 пропущено, 0 падений.

### Теги

- `v0.52.7` — fix/analytics-v0.52.7-eager-layout → master

## [0.52.6] — 2026-05-04 — Tier-1 фиксы по глубокому аудиту аналитики (T1-T5, T7-T8)

### Исправлено

- **T3 — X-ось `vacuum_prediction` 1970–2025**
  (`prediction_widget.py:226-231`). Маркер «now» (`InfiniteLine`)
  создавался с `pos=0` (Unix epoch) без `ignoreBounds=True`.
  autoRange захватывал 1970-й origin и растягивался на 55 лет.
  Исправлено: `pos=time.time()` в момент создания;
  `ignoreBounds=True` при `addItem`; `_update_now_marker()` теперь
  вызывается и из `set_history`, и из `set_prediction`.

- **T4 — X-ось cooldown-прогноза показывала 1970-01-01**
  (`main_window_v2.py`). `_cooldown_reading_to_data` строил
  прогнозную траекторию, зипая `future_t` (часы-от-сейчас) прямо
  в `CooldownData`-кортежи, которые потребляет `pg.DateAxisItem`
  (Unix-секунды). 2.5 ч рендерилось как 1970-01-01 00:00:02.
  Исправлено: `future_t_abs = [now_ts + h * 3600 for h in future_t]`.

- **T5 — замороженное X-окно у `PressurePlot`**
  (`pressure_plot.py:171-197`). `set_series()` обновлял Y-диапазон и
  данные кривой, но не переприменял временное окно. `_apply_window`
  срабатывал только при создании и по сигналу контроллера. Класс
  бага тот же, что у v0.52.5 Bug B — не пробросился до
  `PressurePlot`. Исправлено вызовом
  `_apply_window(get_time_window_controller().get_window())` в
  конце `set_series`, когда `not self._forward_looking`.

- **T7 — phase swap обнулял историю** (`analytics_widgets.py`).
  Append-style виджеты (`TemperatureOverviewWidget`,
  `PressureCurrentWidget`) при создании получали только последнее
  закэшированное показание (а не историю). Исправлено: оба
  виджета теперь вызывают `_fetch_history()` из `__init__`,
  посылая ZMQ-команду `readings_history` (асинхронный
  `ZmqCommandWorker`) для backfill-а сконфигурированного окна.

- **T2 — 4 канала аналитики не маршрутизировались**
  (`main_window_v2.py`). `_adapt_reading_to_analytics` обрабатывал
  только `cooldown_predictor/cooldown_eta`. `analytics/r_thermal*`,
  `analytics/instrument_health` и `analytics/vacuum_prediction`
  молча отбрасывались. Все три теперь идут через
  `_push_analytics`. `set_experiment_status` уже был заведён через
  `_on_experiment_status_received`.

- **T1 — мёртвый API `set_fault` удалён**
  (`analytics_view.py:187-189`). `set_fault` существовал в
  `AnalyticsView`, но ни один виджет в layout-ах его не
  реализовывал. `BottomStatusBar` и так показывает fault-состояние.
  Метод, кэш и replay-путь — все удалены. `_forward` теперь
  логирует WARNING (по разу на (setter, phase) пару — не на каждое
  показание), когда вызов сеттера не имеет ни одного получателя в
  активном layout-е.

### Добавлено

- **T8 — контрактный интеграционный тест**
  (`tests/integration/test_analytics_contract.py`). 11 тестов гоняют
  полный путь `_reading_received.emit → _dispatch_reading →
  AnalyticsView → widget` с реалистичными длинными именами каналов.
  Проверяют: число кривых, X-диапазон (без 1970 epoch), абсолютные
  cooldown-таймстемпы, self-fetch при создании, дедупликацию
  WARNING (1 предупреждение на (метод, фазу), не на каждое
  показание), отсутствие `set_fault` и доставку
  `set_experiment_status` до `ExperimentSummaryWidget`.

### Отложено до v0.53.0

- **T6** — нормализация channel-ID на границе dispatch-а
  (затрагивает calibration, conductivity и других потребителей —
  нужен этапный rollout с Protocol-based статическими проверками).

### Ссылки

- Сводка глубокого аудита:
  `artifacts/consultations/2026-05-04/analytics-deep-audit/synthesis.md`.
- Консенсус 4 из 4 консультантов по Tier-1 находкам
  (Codex, Gemini, GLM, Kimi).
- Ратификации архитектора: 8 вопросов, сессия 2026-05-04.
- Multi-verifier ship-аудит: Gemini PASS итерация 2; Codex
  итерация 2 заблокирована usage-лимитом.

### Тестовая база

152 пройдено (141 baseline + 11 новых контрактных), 0 пропущено.

### Теги

- `v0.52.6` — fix/analytics-v0.52.6-structural → master

## [0.52.5] — 2026-05-04 — реальный баг live-панели аналитики (metaswarm)

### Исправлено

- **`PressureCurrentWidget` никогда не получал live-данные**
  (`main_window_v2.py:437`). Guard диспатча проверял
  `reading.unit == "мбар"` (кириллица), но драйвер Thyracont VSP63D
  публикует `unit="mbar"` (латиница) во всех путях (real, mock,
  parse_v1). Условие guard-а расширено до
  `unit in ("мбар", "mbar")`. `channel.endswith("/pressure")` был
  корректен и не менялся. Корневая причина идентифицирована
  4-консультантской metaswarm (Codex + Gemini + GLM); подтверждена
  чтением исходника драйвера.

- **`TemperatureOverviewWidget` показывал пустой график при
  получении данных** (`analytics_widgets.py:207-214`).
  `_apply_window()` вызывался один раз при создании виджета
  (`__init__`) при отсутствии данных. `pi.autoRange()` в pyqtgraph
  внутри зовёт `setRange(disableAutoRange=True)`, отключая X
  autorange, который только что включили. Последующие live-показания
  (Unix-таймстемпы ~1.7×10⁹) полностью выпадали из замороженного
  дефолтного X-диапазона. Исправлено сохранением `_window_controller`
  как instance-атрибута и вызовом
  `_apply_window(self._window_controller.get_window())` в конце
  каждого батча `set_temperature_readings()` — правый край X
  катится за текущим временем. Корневая причина — от Codex в
  metaswarm; подтверждена исходником pyqtgraph
  `ViewBox.setRange(disableAutoRange=True)`.

### Тесты

- `test_mbar_latin_pressure_reading_reaches_analytics`: проверяет,
  что показание с `unit="mbar"` и `channel="VSP63D_1/pressure"`
  доходит до `_analytics_snapshot["set_pressure_reading"]` после
  диспатча.
- `test_temperature_overview_xaxis_scrolls_with_live_readings`:
  проверяет, что после `set_temperature_readings()` правый край
  X-оси находится в пределах 10 с от таймстемпа показания
  (не заморожен на дефолтном диапазоне для пустых данных).

### Процесс

Два предыдущих цикла CC-анализа кода пришли к неверным выводам
(«expected behavior», «correctly wired»). Эскалировано до
4-консультантской metaswarm согласно §v1.5.8.4. Консультанты:
Codex gpt-5.5 high (точная локализация бага), Gemini 2.5 Pro
(анализ архитектурного дрейфа), GLM-5.1 (вердикт о классе
нормализации), Kimi K2.6 (LOST — null API response). Синтез +
проверка по исходнику отменили все предыдущие анализы.

### Тестовая база

11 пройдено (9 baseline + 2 новых), 0 пропущено.

### Теги

- `v0.52.5` — fix/analytics-live-panel-real-bug → master

## [0.52.4] — 2026-05-04 — UX аналитики + warmup channel ID

### Исправлено

- **Idle-плейсхолдер `CooldownPredictionWidget`** теперь рендерится
  как `pg.TextItem` на canvas-е графика, а не как `QLabel` над
  графиком. График всегда занимает полную вертикаль. Однострочный
  текст: «Охлаждение не активно — прогноз недоступен». С
  data-driven предиктором v0.52.2 плейсхолдер показывается только
  в warm-idle (система тёплая, cryocooler выключен) — не на базе.
- **`TemperatureTrajectoryWidget._fetch_history()`** теперь
  отправляет полные метки каналов (например, `Т7 Детектор`), а не
  короткие ID (`Т7`). `SQLiteWriter` сохраняет показания под
  полными метками; короткие ID давали 0 строк для истории
  температур фазы warmup. Тот же класс, что у фикса BrokerSnapshot
  в v0.47.4. Бонус-находка Gemini из аудита F-X v3, закрыта.

### Расследование

Live-панели аналитики (`TemperatureOverviewWidget`,
`PressureCurrentWidget`) были объявлены «actually broken» в
CC_PROMPT. Анализ кода показал, что они **корректно подключены** —
≤2 с пустоты при открытии — это ожидаемое поведение live-only
виджетов. Pressure-виджет корректно отсутствует в layout-е фазы
cooldown. Изначальная сортировка (коммит `fb59916`) была верна.

### Ссылки

- Фикс `TemperatureTrajectoryWidget`: бонус-находка Gemini, аудит
  F-X v3 2026-05-02.
- Фикс плейсхолдера: UX-пробел из реализации idle-метки в `fb59916`.
- 4 новых теста, 130/130 тестов analytics-view пройдено.

## [0.52.3] — 2026-05-04 — корректное аппаратное соответствие Т11/Т12

### Исправлено

- **C6 (зависшая находка из аудита F-X v3)** — `physical_alarms.yaml`
  имел инвертированные cold/warm-каналы относительно реального
  лабораторного железа. Исправлено:
  - `cold_channel: "Т12"` (2-я ступень GM-cooler, пол ~2.9 K).
  - `warm_channel: "Т11"` (плита 1-й ступени, пол ~40 K).
  - Defaults в `cooldown_alarm.py` и `physical_alarms_config.py`
    перевёрнуты соответственно.
  - Fallback-ы в `replay_alarm_history.py` перевёрнуты.
- Display-метки в `channels.yaml` и `channel_manager.py`:
  «Теплообменник 1» → «Плита 1-й ступени» (Т11);
  «Теплообменник 2» → «2-я ступень» (Т12). Физически точно.
- `top_watch_bar.py`: `T_MIN_CHANNEL` Т11→Т12, `T_MAX_CHANNEL`
  Т12→Т11. Ячейка T_min теперь корректно показывает температуру
  cold-head 2-й ступени.
- В `interlocks.yaml` уточнено описание `detector_warmup`
  (Т12 = 2-я ступень). Порог (10 K, Т12) уже был корректен;
  без изменений.
- `vacuum_guard.py` `reference_temp_channel` (Т12) подтверждён;
  без изменений.

### Ссылки

- Зависшая находка C6 поднята в аудите F-X v3 итер. 4, 2026-05-02.
- Аппаратная верификация архитектором в лаборатории, 2026-05-03.
- Происхождение опорной кривой согласовано с Т12=cold (пол 2.9 K).
- **Push-гейт ОТКРЫТ** для v0.51.0 / v0.52.0 / v0.52.1 / v0.52.2 /
  v0.52.3.

## [0.52.2] — 2026-05-03 — cooldown-предиктор: data-driven пол + поддержка квазистационарного режима

### Изменено

- `CooldownPredictor` `T_cold_end` и `T_warm_end` теперь выводятся
  из минимумов опорной кривой во время сборки модели через
  `_derive_floors()`. Прежние захардкоженные значения (4.0 K,
  85.0 K) молча отбрасывали квазистационарный режим от ~4 K до
  реальной базы 2-й ступени.
- Гейт генерации траектории поднят с `p_now < 0.98` до
  `p_now < 0.999`; классификация steady-фазы аналогично поднята.
  Прогноз теперь покрывает весь квазистационарный режим (T_cold,
  выходящая на реальную базу, ~2.5–3 K в зависимости от железа).
- `compute_progress()` принимает явные `T_cold_end` / `T_warm_end`;
  defaults — новые fallback-константы (`T_COLD_END_FALLBACK = 2.5 K`,
  `T_WARM_END_FALLBACK = 75.0 K`).
- `EnsembleModel` получает поля `T_cold_end` / `T_warm_end`,
  заполняемые на этапе сборки.
- Удобная функция `build_model_from_curves()` консолидирует полный
  build-pipeline (derive floors → prepare → ensemble).
- `save_model()` — schema bump до версии 2.0; пишет производные
  значения пола.
- `load_model()` и `ingest_curve()` используют
  `build_model_from_curves()` — пол всегда выводится заново из
  данных кривой, не грузится из устаревшего JSON-поля.
- `validate_loo()` выводит per-fold пол из обучающих кривых.
- Команды `build` / `demo` / `validate` в `cooldown_cli.py`
  обновлены соответственно.
- Обратная совместимость: алиасы модульного уровня `T_COLD_END` /
  `T_WARM_END` сохранены.

### Замечание

На диске нет данных опорных кривых (`data/cooldown_model/`
отсутствует). Пол будет выведен автоматически при первой сборке
модели после того, как реальный cooldown будет ингестирован через
`auto_ingest`. До этого момента активны fallback-константы
(2.5 K / 75.0 K).

## [0.52.1] — 2026-05-03 — русификация интерфейса

### Изменено

- Кнопки переключения шкалы Y: «Lin Y» / «Log Y» → «Лин Y» /
  «Лог Y» (`dashboard/temp_plot_widget.py`,
  `widgets/overview_panel.py`).
- Документация оператора `docs/operator/analytics-tab.md` целиком
  переведена на русский.

## [0.52.0] — 2026-05-03 — F-P prediction overlay-и на вкладке аналитики

### Добавлено

- **F-P2 overlay прогноза вакуумной течи** (`VacuumPredictionWidget`):
  самостоятельный 10-секундный poll по ZMQ-команде
  `get_vacuum_trend`. Конвертирует относительные экстраполяционные
  массивы движка в абсолютные unix-таймстемпы и единицы давления
  мбар. Полоса ±1σ из `residual_std`. Сырая история давления
  накапливается через `set_pressure_reading()`. Корректно: чистится
  при no-data/error, виден только в фазе vacuum (через
  `analytics_layout.yaml`).
- **F-P3 overlay асимптоты теплопроводности TIM**
  (`RThermalLiveWidget`): `SteadyStatePredictor` (window=600 с,
  interval=30 с) поверх истории `R_thermal`. Горизонтальная
  пунктирная линия асимптоты + полоса ±σ рендерятся при
  `percent_settled ≥ 30%` и `valid=True`. Антидубль через
  `_last_r_ts`. Скрыто, если история пуста или предиктор не
  сошёлся. Виден только в фазе measurement.
- **F-P1 overlay траектории cooldown**: подтверждено как
  существовавшее. `CooldownPredictionWidget` уже рендерит
  prediction-линию + CI-полосу из данных траектории
  `cooldown_service.py` через
  `main_window_v2._cooldown_reading_to_data()`. Нового кода нет.

### Визуальный дизайн

Все overlay-и используют исключительно токены design system:
- Prediction-линия: `STATUS_INFO`, `PLOT_LINE_WIDTH`, `Qt.DashLine`.
- Полоса доверия: `STATUS_INFO` при alpha=64 (~25% непрозрачности).
Соответствует канонической конвенции `PredictionWidget`.

### Ссылки

Архитекторская сессия 2026-05-03 (выходные).
Multi-verifier аудит (Codex gpt-5.5 + Gemini 0.38.2) — 1 итерация.
Codex P2-фиксы применены (устаревший overlay чистится на путях
no-data/error).

### Тестовая база

2414 пройдено, 4 пропущено (baseline 2396 + 18 новых F-P-тестов).

### Теги

- `v0.52.0` → коммит `160f4ac` (commit feat(f-p), post-amend).
- `v0.51.0` → коммит `65b9f92` (предыдущий релиз, ЕЩЁ НЕ ЗАПУШЕН —
  гейтован на C6).

### Ключевые коммиты этого релиза

- `9f67ac4` docs(roadmap): retire F-A/F-B/F-C/F-D, plan F-P1/2/3.
- `160f4ac` feat(f-p): prediction overlays on Analytics tab.

## [0.51.0] — 2026-05-02 — F-X v3: тревоги физического состояния

### F-X v3: тревоги физического состояния (CooldownAlarm + VacuumGuard)

Заменяет модель тревог по zone-band (F-X v2, никогда не помечалась
тегом) двумя физически обоснованными тревогами, не связанными с
`ExperimentPhase`.

### Добавлено
- `CooldownAlarm` (`core/cooldown_alarm.py`): тревога по отклонению
  траектории на основе предиктора. Включается оператором. Загружает
  `model/predictor_model.json` лениво при arm-е. Срабатывает, если
  cooldown отстаёт от ожидаемого прогресса > 2.5σ на ≥5
  последовательных тиках. Slip ETA сообщается, если > 0.5 ч/ч.
  Авто-disarm при прогрессе ≥ 0.95 или T_cold ≤ база + ε. Оператор
  может перевключить после авто-disarm-а для следующего цикла
  cooldown.
  При достижении базы (порог авто-disarm-а) переходит в режим
  WATCHDOG (конфигурируется `watchdog_enabled`). WATCHDOG смотрит
  только на T11 и шлёт WARNING, если T11 поднимается выше
  `base_temp_K + watchdog_margin_K` непрерывно
  `watchdog_sustained_s` секунд. Сбрасывается при восстановлении
  T11. Disarm-ится на operator stop или experiment finalize.
  Закрывает пробел post-cooldown мониторинга, найденный в P1 ревью
  Codex.
- `VacuumGuard` (`core/vacuum_guard.py`): полностью автоматическая
  тревога P × T_ref. Включается при T_ref < 260 K; срабатывает при
  P > 1e-2 мбар непрерывно ≥ 30 с; deadband 260/270 K на T_ref,
  одна декада на давлении. Stale-сенсор в состоянии FIRED
  сохраняет тревогу, не сбрасывая её.
- `config/physical_alarms.yaml`: настройки обоих модулей. Все
  значения откатываются на захардкоженные defaults при отсутствии
  файла — движок всегда стартует.
- `core/physical_alarms_config.py`: fail-open YAML-загрузчик с
  per-key type-валидацией и guard-ом не-dict подсекций.
- Движок: задача `_physical_alarms_tick` с интервалом
  `min(cooldown_interval, vacuum_interval)`. Диспатчит события
  `alarm_fired`/`alarm_cleared` и Telegram-уведомления на
  переходах, как путь alarm_v2.
- ZMQ-команды: `cooldown_alarm.arm`, `cooldown_alarm.disarm`,
  `cooldown_alarm.status`, `vacuum_guard.status`.
- GUI: группа «Контроль захолаживания» в `AlarmPanel` (кнопка
  arm/disarm, метка статуса, ETA, progress bar). 5-секундный poll
  через существующий `ZmqCommandWorker`. В состояниях WATCHDOG
  вместо ETA/progress показывается live-показание T11.
- Replay harness переработан (`tools/replay_alarm_history.py`):
  сравнивает legacy threshold-модель `alarms_v3` против
  predictor-based решений на исторических данных SQLite.
  Сопоставление ближайшего таймстемпа температуры; парсит формы
  `outside_range`, `above`, `below`.
- 40+ новых тестов: `test_cooldown_alarm.py` (20),
  `test_vacuum_guard.py` (11), `test_physical_alarms_config.py` (7),
  `test_alarm_v2_legacy_cleanup.py` (2).

### Изменено
- `config/alarms_v3.yaml`: удалены 3 absolute-threshold правила на
  T11/T12 (`cooldown_stall`, `detector_drift`, `detector_unstable`) —
  заменены predictor-based оценкой `CooldownAlarm`.
  `calibrated_sensor_fault` сохранено — детектит невозможные raw-
  значения (< 1 K или > 350 K), сигнализирующие об отказе железа
  сенсора; не покрывается физическими тревогами. Сообщение
  переписано в фактологической формулировке по операторскому
  guidance. Канал `shield_warming` исправлен Т11 → Т12
  (Т12 = плита N₂).

### Ссылки
- Ветка: `feat/f-x-v3-physical-alarms`.
- Спецификация: `CC_PROMPT_F_X_V3_PHYSICAL_ALARMS.md`.
- Конфиг: `config/physical_alarms.yaml`.

## [0.50.0] — 2026-05-01 — F27 Фотографии композиции через Telegram-бот

### Добавлено
- Оператор отправляет фотографию композиции эксперимента через
  Telegram → бот подтверждает целевой эксперимент через inline-
  клавиатуру ([Да] / [Нет] / [Другой эксперимент]) → фото
  сохраняется в `<artifact_dir>/composition/<ts>_<seq>.{jpg,png}`
  с sidecar JSON-метаданными.
- GUI `ExperimentOverlay` показывает фотографии композиции в новом
  разделе «Композиция эксперимента» — с превьюшками и
  click-to-full-size диалогом.
- GUI `ArchivePanel` показывает галерею композиции для архивных
  экспериментов.
- LATE BINDING `ChannelManager` в парсинге caption-а — упоминания
  каналов резолвятся через свежее состояние `ChannelManager` на
  каждый вызов.
- ZMQ-событие `experiment.photo_attached` публикуется при
  присоединении, GUI авто-обновляется.
- Зависимость Pillow добавлена для валидации изображений.
- 50 новых тестов, покрывающих обработчик фото, attach API, GUI-
  рендер, извлечение каналов.

### Ссылки
- ARCHITECT REQUEST: 2026-05-01 post-v0.47.4.
- Спецификация: CC_PROMPT_F27_COMPOSITION_PHOTOS.md.

## [0.47.4] — 2026-05-01 — HF: комплексный фикс F30 query agent (треки A-F)

Агрегирует все накопленные регрессии F30 Live Query Agent и
ожидаемые фичи из реального тестирования 2026-05-01. Заменяет
запланированные хотфиксы v0.47.1 / v0.47.2 / v0.47.3 одним
комплексным бранчем.

### Добавлено
- **Трек A**: секция `query` в `agent.yaml` с `enabled: true` —
  query-агент теперь реально стартует (был выключен из-за
  отсутствия ключа конфига, что давало slash-only fallback).
- **Трек B**: late-binding резолв display name в
  `IntentClassifier` (`_build_channel_hint()` читает
  `ChannelManager` свежим на каждый вызов).
  `ChannelManager.find_by_name()` — case-insensitive exact +
  substring. Fallback в `QueryRouter._resolve_target_channels()`.
- **Трек C**: `BrokerSnapshot.oldest_age_s()`, `display_name()`,
  `latest_with_labels()`, параметр `channel_manager`.
  `CompositeStatus.snapshot_empty` + `snapshot_age_s`.
  `CompositeAdapter` использует динамическое обнаружение K-unit
  каналов. Ветка warming-up в агенте: «поток данных только
  запускается».
- **Трек D**: `render_temperature_chart()` → PNG через matplotlib.
  `ChartDispatcher.dispatch()` fire-and-forget с
  `add_done_callback(_log_task_exception)`. `send_photo()` на
  `TelegramCommandBot`. Графики прицепляются к
  composite_status + range_stats запросам.
- **Трек E**: `ru_labels.py` — `phase_display_name()`,
  `experiment_status_display()`, `ru_bool()`. Полная русификация
  всех FORMAT_*-промптов. Категория `GREETING` добавлена.
  Регрессионный тест `test_format_prompts_no_english_leakage`.
- **Трек F**: anti-pattern guard в `FORMAT_COMPOSITE_STATUS_USER` —
  «НЕ начинай» + метка «Прогноз захолаживания» + конкретный плохой
  пример («НЕ ДЕЛАЙ ТАК»).
- Регулятор SSL (инвариант v0.47.1): параметр `verify_ssl` заведён
  в `TelegramNotifier` и `TelegramCommandBot` через
  `aiohttp.TCPConnector(ssl=...)`. WARNING логируется при
  выключении. Создан `test_telegram_ssl_verification.py`.
- ≥90 новых тестов по всем трекам.

### Исправлено
- **CRITICAL**: «Я понимаю только slash-команды» на всех запросах —
  `query_enabled` был False (отсутствовала секция `query:` в
  `agent.yaml`). Исправлено добавлением `query: enabled: true`.
- «Что на азотной плите?» теперь резолвится в Т12 через late-binding
  `ChannelManager`.
- Composite-ответ больше не начинается с «Т7 Детектор,»
  (anti-pattern guard).
- «в фазе cooldown» → «в фазе захолаживания» (полная русификация).
- Пустой `BrokerSnapshot` при старте движка → «поток данных только
  запускается» вместо «температуры отсутствуют».
- Графики теперь прицепляются к composite_status-запросам
  (dispatcher + send_photo заведены).
- `ChannelManager.find_by_name`: guard на пустое имя предотвращает
  ложные substring-совпадения.

### Тестовая база
- ≥291 пройдено, 0 новых падений (предсуществовавшие падения без
  изменений).

### Ссылки
- CC_PROMPT_HF_V0.47.2_FIXUP_REGRESSION_BLOCK.md.

## [0.47.3] — 2026-05-01 — HF: резолв display name в Intent Classifier (LATE BINDING)

Хотфикс для реального UX-бага: оператор переименовал каналы через
GUI `ChannelEditor`, но Гемма не резолвила запросы по display name.
«Что на азотной плите?» игнорировало Т12 и возвращало generic-микс.

Ключевое архитектурное решение: **LATE BINDING** — классификатор
читает `ChannelManager` при КАЖДОМ вызове `classify()`. Restart
движка НЕ НУЖЕН. Оператор именует датчики на этапе подготовки,
затем спрашивает Гемму в measurement-фазе — все переименования
сразу же отражаются.

### Добавлено
- `IntentClassifier` принимает `channel_manager: ChannelManager |
  None`. Строит таблицу channel_id → display_name в system-промпте
  при КАЖДОМ вызове `classify()` (late binding). Переименования
  через GUI `ChannelEditor` подхватываются на следующем запросе
  без рестарта движка.
- `ChannelManager.find_by_name(name)` — case-insensitive exact +
  substring: display name → channel ID. Двухпроходной алгоритм,
  чтобы избежать substring-смещения.
- `QueryRouter` принимает `channel_manager`. Метод
  `_resolve_target_channels()` валидирует и fuzzy-матчит
  `target_channels` из классификатора против текущего состояния
  `ChannelManager` (late binding).
- 22 новых теста:
  `tests/agents/assistant/test_display_name_resolution.py` —
  покрывают перестроение hint классификатора, rename mid-session
  (LATE BINDING), резолв в роутере, `ChannelManager.find_by_name`.

### Исправлено
- «Что на азотной плите?» — Гемма резолвит операторскую
  терминологию (переименованную через `ChannelEditor`) в
  channel ID.
- Переименование датчиков через GUI `ChannelEditor` сразу же
  отражается в ответах Геммы на СЛЕДУЮЩИЙ запрос — restart движка
  НЕ требуется.
- `ChannelManager.find_by_name`: второй проход substring теперь пропускает
  каналы без поля `name` (пустая строка `""` всегда была подстрокой
  любого запроса — баг-фикс).

### Тестовая база
- 50 пройдено (22 новых + 28 существующих classifier/router).
- 0 падений.

### Теги
- `v0.47.3` — (ожидает Phase D tag).

### Ссылки
- ARCHITECT REQUEST: реальное тестирование 2026-05-01 13:06.
- HF-спецификация: CC_PROMPT_HF_V0.47.3_DISPLAY_NAME_RESOLUTION.md.

## [0.47.0] — 2026-05-01 — F30 Live Query Agent

Реализует Live Query Agent (F30): операторы могут слать произвольные
Telegram-сообщения или `/ask <query>`-команды для запроса текущего
состояния движка. Трёхэтапный pipeline: классификация интента
(gemma4:e2b, temp 0.1) → детерминированный fetch через
service-adapter → форматный русский ответ (temp 0.3).

### Добавлено
- Оркестратор `AssistantQueryAgent`: pipeline classify → fetch →
  format с rate-limit-ом (60/час на чат), audit log на каждый
  запрос, контракт «никогда не бросает».
- `IntentClassifier`: gemma4:e2b, temperature=0.1, max_tokens=2048,
  fallback на UNKNOWN при ошибке парса или таймауте.
- `QueryRouter`: детерминированный dispatch `QueryIntent` в 7
  ServiceAdapter-ов.
- 7 ServiceAdapter-ов: `BrokerSnapshot`, `CooldownAdapter`,
  `VacuumAdapter`, `SQLiteAdapter`, `AlarmAdapter`,
  `ExperimentAdapter`, `CompositeAdapter`. `CompositeAdapter`
  параллелит fetch через `asyncio.gather`.
- `BrokerSnapshot`: новый read-only subscriber-паттерн —
  latest-per-channel кэш поверх `DataBroker` (который остаётся
  чистым pub/sub без snapshot-API).
- Шаблоны русских format-промптов на каждую категорию
  (current_value, eta_cooldown, eta_vacuum, range_stats,
  phase_info, alarm_status, composite_status,
  out_of_scope_historical, out_of_scope_general, unknown).
  Анти-галлюцинационные инструкции, только Unicode (без LaTeX),
  разговорный тон.
- `TelegramCommandBot`: маршруты для свободного текста и
  `/ask <query>` к query-агенту. Allowlist как defense-in-depth
  в `_handle_text()`. Stub-fallback при отсутствии query-агента.
- `AssistantConfig`: секция конфига `query.*` (enabled,
  model-override-ы, температуры, таймауты, rate_limit).
  `query_enabled` по умолчанию False.
- Wiring движка: создаёт query-агента при `agent.query.enabled`,
  стартует `BrokerSnapshot`, делает late-bind к
  `TelegramCommandBot`, останавливает на shutdown-е.
- Метод `CooldownService.last_prediction()`, экспонирующий
  закэшированный dict прогноза.
- Метод `AlarmEngine.get_active_alarm_details()` для структурной
  информации об активных тревогах.

### Исправлено
- Проблема thinking-модели gemma4:e2b: `max_tokens` поднят
  256 → 2048, чтобы дать CoT-резонингу место перед выдачей
  JSON-ответа.
- `INTENT_CLASSIFIER_SYSTEM`: `{{`/`}}` → `{`/`}` (не
  format-строка — литеральные двойные скобки сбивали модель).
- Правило `current_value` в `INTENT_CLASSIFIER_SYSTEM`: добавлены
  bare-паттерны каналов (`T1?`, `channel?`), чтобы избежать
  misrouting в `out_of_scope_general`.

### Тестовая база
- 166 тестов проходит (49 новых против baseline-а v0.46.1 — 117).
- Новые test-файлы: `test_query_adapters.py` (19),
  `test_intent_classifier.py` (28), `test_query_agent.py` (12),
  `test_telegram_query_integration.py` (9).

### Аудит Phase F
- Codex gpt-5.5 (high reasoning): PASS после 3 fix-up циклов.
  Закрыто 6 находок (1 HIGH, 3 MEDIUM, 2 LOW). 0 остаточных
  CRITICAL/HIGH.

### Теги
- `v0.47.0` → TBD (выставляется при merge в master).

### Ключевые коммиты этого релиза
- `02aa9dd` docs(roadmap): renumber F30+ for Live Query Agent insertion.
- `e0254d9` feat(f30): query adapters + BrokerSnapshot.
- `f3d36d3` feat(f30): intent classifier + router.
- `dbb15d5` feat(f30): AssistantQueryAgent + format prompts.
- `09f78d5` feat(f30): Telegram free-text + /ask integration.
- `1731584` fix(f30): max_tokens 2048 for thinking model + prompt fixes.
- `4acfd48` fix(f30): Codex audit fix-up cycle 1.
- `8852786` fix(f30): Codex audit fix-up cycle 2.
- `4a9800c` fix(f30): Codex audit fix-up cycle 3.

## [0.46.1] — 2026-05-01 — F29 fix-up (swarm-аудит CF-2/CF-3/CF-5)

Patch-релиз с тремя фиксами, найденными в 8-модельном swarm-аудите
v0.46.0 (коммит `ef0a1eb`). Никакой новой функциональности; wiring
движка не менялся.

### Исправлено
- CF-2: сбой чтения SQLite во время сборки контекста периодического
  отчёта больше не глушит часовой отчёт молча. Сбой теперь логируется
  WARNING-ом и выставляет `context_read_failed=True`; обработчик
  обходит `skip_if_idle`, чтобы оператор получил empty-data отчёт,
  а не молчание (`context_builder.py`, `agent.py`).
- CF-3: переходы фаз, помеченные движком как `"phase"`, не матчили
  фильтр `"phase_transition"` в context-builder-е — секция фаз
  всегда показывала `(нет)`. Теперь принимаются оба тега; фильтр
  `other_entries` обновлён, чтобы исключать записи `"phase"` и
  избежать двойной классификации (`context_builder.py`).
- CF-5: `PERIODIC_REPORT_SYSTEM` теперь явно запрещает нотацию
  LaTeX и формулы `$...$`. Удалена нотация `\rightarrow` —
  Python-строковый escape-баг (на рантайме рендерилось как CR +
  `ightarrow`, `prompts.py`).

### Тесты
- `test_periodic_report_context_read_failure_sets_flag`.
- `test_periodic_report_context_read_failure_bypasses_idle_skip`.
- `test_periodic_report_context_phase_tag_classified_correctly`.
- `test_periodic_report_prompt_prohibits_latex` усилен (без управляющего
  символа `\r`).

### Тестовая база
- 27 тестов проходит (3 новых против baseline-а v0.46.0 — 24).

### Теги
- `v0.46.1` → `70bb588`.

### Ключевые коммиты этого релиза
- `70bb588` fix(f29): swarm audit findings CF-2 CF-3 CF-5.

## [0.46.0] — 2026-04-30 — F29 Периодические нарративные отчёты

### Добавлено
- F29: конфигурируемая русскоязычная нарративная сводка недавней
  активности движка.
- Новый тип события EventBus: `periodic_report_request`.
- Таймерная задача движка `_periodic_report_tick`, управляемая
  `agent.triggers.periodic_report`.
- Обработчик `_handle_periodic_report` в `AssistantLiveAgent`.
- Шаблоны промптов `PERIODIC_REPORT_SYSTEM` / `PERIODIC_REPORT_USER`.
- Метод context-builder-а `build_periodic_report_context`.
- Фильтр skip-if-idle: окно с числом событий меньше
  `min_events_for_dispatch` пропускается.
- Вариация префикса вывода: `🤖 Гемма (отчёт за час):`.
- Чип GUI insight panel для периодических отчётов.
- Smoke-харнесс F29:
  `artifacts/scripts/smoke_f29_periodic_report.py`.

### Изменено
- Модель ассистента по умолчанию в `config/agent.yaml`: `gemma4:e4b` →
  `gemma4:e2b` для совместимости с M5 24GB.
- Текст периодического промпта теперь учитывает конфигурируемое
  `window_minutes` вместо захардкоженного «последний час».

### Конфигурация
- `config/agent.yaml`: новая секция `triggers.periodic_report` с
  `enabled`, `interval_minutes`, `skip_if_idle` и
  `min_events_for_dispatch`.

### Тесты
- Добавлены Phase D engine-таймер тесты на publish, disabled no-op
  и cancellation на shutdown.
- Добавлены контекст/промпт регрессии для форматирования секции
  калибровки и текстов non-hourly окна.
- Фокусированный F29-срез: 34 теста проходит.
- Smoke: реальный `gemma4:e2b`, wall-latency 19.2 с, 94.8% русского,
  диспатч Telegram/log/GUI/audit подтверждён, idle-skip
  подтверждён.

### Ссылки
- Архитектура: `artifacts/architecture/assistant-v2-vision.md` §5 Phase 1.
- Спецификация: `CC_PROMPT_F29_PERIODIC_REPORTS.md`.
- Smoke: `artifacts/handoffs/2026-04-30-f29-cycle1-smoke.md`.
- Аудит: `artifacts/consultations/2026-04-30/f29-cycle1-audit/synthesis.md`.

## [0.45.0] — 2026-05-01 — F28 Гемма завершено (assistant v1)

### Главное
- F28 Гемма — локальный LLM-агент полностью отгружен: Slice A
  (4 уведомительных триггера) + Slice B (диагностические
  подсказки) + Slice C (intro к отчёту кампании).
- Фундаментальный примитив EventBus (Cycle 0) для non-Reading
  событий движка.
- Локальная интеграция с Ollama, модель `gemma4:e4b`.
- Русскоязычный операторский диспатч (Telegram, operator log,
  GUI insight panel).
- Автогенерация DOCX intro отчёта кампании (формальный русский,
  200–400 слов).
- Дисциплина audit log: каждый вызов LLM пишется в журнал.
- Бренд-абстракция: будущие миграции модели — изменения только
  в конфиге.

### Добавлено
- `src/cryodaq/agents/assistant/` — полное семейство модулей
  ассистента:
  - `live/agent.py` — `AssistantLiveAgent` (был `GemmaAgent`).
  - `live/prompts.py` — system-промпты с интерполяцией
    `{brand_name}`.
  - `live/output_router.py` — префикс с учётом бренда, события
    `assistant_insight`.
  - `live/context_builder.py` — состояние движка → контекст LLM.
  - `shared/audit.py` — JSON-записи аудита на каждый вызов.
  - `shared/ollama_client.py` — async-обёртка для Ollama
    `/api/generate`.
  - `shared/report_intro.py` — синхронный генератор DOCX-intro.
  - `shared/retention.py` — очистка audit log по 90-дневной
    политике.
- `src/cryodaq/gui/shell/views/assistant_insight_panel.py` —
  `AssistantInsightPanel` с параметрами `brand_name` /
  `brand_emoji`.
- `config/agent.yaml` — новый namespace `agent.*` с `brand_name`
  и `brand_emoji`.
- `artifacts/architecture/assistant-v2-vision.md` — полная
  спецификация архитектуры для фаз assistant v2 (F29-F33).

### Изменено
- `config/agent.yaml`: namespace `gemma:` → `agent:` (обратная
  совместимость: `gemma:` всё ещё грузится с deprecation-warning
  до v0.46.0).
- `AssistantConfig`: `from_yaml_path()` / `from_yaml_string()`
  для определения namespace-а.
- Путь audit log: `data/agents/gemma/audit` →
  `data/agents/assistant/audit`.
- EventBus `event_type`: `gemma_insight` → `assistant_insight`.
- ROADMAP: F28 ✅ DONE; F5/F9 RETIRED; F29-F33 добавлены
  (фазы assistant v2).

### Циклы F28
- Cycle 0: фундамент EventBus.
- Cycle 1: Ollama-клиент + audit + context-builder.
- Cycle 2: `AssistantLiveAgent` + alarm-summary (Slice A первая
  поставка).
- Cycle 3: Slice A полностью (4 триггера + GUI-панель).
- Cycle 4: Slice B — диагностические подсказки.
- Cycle 5: Slice C — отчёт кампании.
- Cycle 6: бренд-абстракция + переименование модулей + полировка
  + этот релиз.

### Архитектура
- Модуль: `src/cryodaq/agents/assistant/{live,shared}/`.
- Класс: `AssistantLiveAgent` (был `GemmaAgent`).
- Namespace конфига: `agent.*` (был `gemma.*`, обратная
  совместимость с warning-ом).
- Хранение: `data/agents/assistant/audit/`.
- Интерполяция бренд-имени по всем промптам и выводам.

### Тесты
- 71 тест агента (smoke + unit + integration).
- Полный набор зелёный (~2 090 проходит).
- 11 тестов бренд-абстракции.
- 4 теста audit-retention.

### Калибровочные данные
- 6 multi-модельных audit-сессий в
  `artifacts/calibration/log.jsonl`.
- Эмпирика: Codex надёжен; GLM силён на review-задаче
  (`max_tokens=8192`); Qwen3-Coder over-flags; MiniMax
  деградирует; Kimi падает.

### Документация
- README: раздел «Местный AI-ассистент».
- Vault-заметка: `~/Vault/CryoDAQ/10 Subsystems/Assistant agent.md`.
- Operator manual: новый раздел 10 (поведение ассистента +
  on/off).
- Архитектура: `artifacts/architecture/assistant-v2-vision.md`.

### Теги
- `v0.45.0` → release-коммит (см. Phase G).

### Ключевые коммиты этого релиза
- `adc40d7` — refactor(f28): rename agents/gemma → agents/assistant (Phase A).
- `00bd20f` — refactor(f28): rename GemmaAgent → AssistantLiveAgent (Phase B).
- `a1f2811` — feat(f28): brand-name abstraction for assistant (Phase C).
- `2fed36c` — docs(f28): polish — README, vault note, operator manual, retention (Phase D).
- `7148432` — test(f28): rename insight panel test + smoke doc (Phase E).

## [0.44.0] — 2026-05-01 — Зрелость хранилища + leak rate

### Главное
- F17: cold-ротация SQLite → Parquet с day-by-day разметкой
  архива. `ArchiveReader` для replay-а через оба источника.
- F13: оценщик скорости течи вакуума (`LeakRateEstimator`) c
  sliding-window OLS, ZMQ-командами, атомарным персистенсом
  истории.
- F26: backport-whitelist для гейта SQLite WAL (3.44.6, 3.50.7)
  по официальной advisory SQLite.

### Хранилище (F17, F26)
- **F17 — `ColdRotationService`**: ротирует SQLite-файлы старше
  30 дней в Parquet/Zstd; проверяет число строк перед удалением;
  daemon-режим (86400 с). Поломанный `index.json` обрывает
  ротацию вместо перезаписи. `asyncio.Lock` защищает от
  конкурентных запусков.
- **F17 — `ArchiveReader`**: единый запрос через SQLite (свежее)
  + Parquet (архив); UTC-нормализованная итерация по дням;
  громко падает на повреждённом индексе.
- **F26 — белый список `SQLITE_BACKPORT_SAFE`**: `{(3,44,6),
  (3,50,7)}` обходят startup-гейт без env-переменной; соседние
  версии всё равно падают. Источник: advisory с
  sqlite.org/wal.html.

### Аналитика вакуума (F13)
- **`LeakRateEstimator`**: sliding-window OLS с FIFO-обрезкой,
  numpy-free регрессия, R²=0.0 на вырожденном входе, атомарный
  персистенс истории в `data/leak_rate_history.json`.
- **ZMQ-команды движка**: `leak_rate_start` (`duration_s`
  валидируется), `leak_rate_stop` (возвращает
  `asdict(LeakRateMeasurement)`).
- **Broker-задача движка**: `_leak_rate_feed()` подписывается на
  показания давления (`unit==mbar`), авто-финализирует на
  истечении окна.
- **Конфиг**: `chamber.volume_l` (оператор обязан задать),
  `chamber.leak_rate.*`.

### Требуется действие оператора
- `chamber.volume_l` должно быть выставлено в
  `config/instruments.local.yaml` до первого замера скорости
  течи; `finalize()` бросает `ValueError`, если `volume_l == 0.0`.

### Тесты
- 49 новых тестов: F26 (6) + F17 (16) + F13 (19).
- Полный набор ~2 019 проходит.

### Теги
- `v0.44.0` → merge-коммит F13.

### Closing-коммиты
- Merge F26: см. `git log --oneline --merges`.
- Merge F17: см. `git log --oneline --merges`.
- Merge F13: см. `git log --oneline --merges`.

## [0.43.0] — 2026-04-30 — Overnight-спринт фич (F19-F25)

### Главное
- 7 фич отгружены за один Sonnet-спринт ночью (F19-F25), закрыты
  все отложенные находки Task A и backlog полировки F3.
- Doc/process Phase A приземлены прямо в master ранее в сессии:
  ORCHESTRATION v1.3 + skill multi-model-consultation v1.1 +
  plugin disposition.
- Обе feature-ветки прошли Codex-аудит (gpt-5.5 high-reasoning):
  alarm-кластер FAIL → PASS (2 MEDIUM-фикса); misc-кластер
  CONDITIONAL → PASS (1 P2-фикс).

### Alarm pipeline (F20, F21, F22)
- **F20 — агрегация sensor-диагностики + cooldown**: словарь
  `_channel_last_notified` отслеживает per-channel состояние;
  первое уведомление никогда не подавляется; critical всегда
  обходит cooldown; движок батчит >3 одновременных событий в одно
  Telegram-сообщение. Конфиг: `plugins.yaml`
  `aggregation_threshold: 3`, `escalation_cooldown_s: 120.0`.
- **F21 — гистерезисный deadband для тревог**:
  `AlarmEvaluator.evaluate()` принимает `is_active` +
  `active_channels: frozenset`. Deadband фильтрует только
  изначально-триггернувшие каналы (Codex-фикс: сторонний канал
  мог наследовать состояние тревоги).
- **F22 — повышение severity in-place**: `WARNING → CRITICAL` на
  одном `alarm_id` (мутация `AlarmEvent.level`, `frozen=False`).
  Событие истории `SEVERITY_UPGRADED` для аудита. Предотвращает
  дубликаты операторских уведомлений на одну физическую аномалию.

### Независимые фичи (F19, F23, F24, F25)
- **F19 — обогащение `ExperimentSummaryWidget`**: кликабельные
  метки DOCX/PDF через `_ClickableLabel` + `QDesktopServices`;
  топ-3 имени тревог по частоте; per-channel min/max/mean
  (`limit_per_channel=50000` покрывает ~7 ч при 0.5-с частоте;
  Codex P2-фикс с 5000, которое покрывало лишь ~42 мин).
- **F23 — таймстемп измерения в `RateEstimator`**:
  `safety_manager._collect_loop` теперь использует
  `reading.timestamp.timestamp()` вместо `time.monotonic()`
  (времени снятия из очереди), давая корректные dT/dt при
  бэклоге очереди.
- **F24 — ZMQ-команда `interlock_acknowledge`**: action
  `interlock_acknowledge` выставляет `InterlockEngine.acknowledge(name)`
  — переход `TRIPPED → ARMED`, `KeyError` для неизвестного имени.
  Оператор перевключает interlock без рестарта процесса.
- **F25 — стартовый гейт SQLite WAL**: `_check_sqlite_version()`
  бросает `RuntimeError` на затронутых версиях `[3.7.0, 3.51.3)`
  (баг WAL corruption март 2026). `CRYODAQ_ALLOW_BROKEN_SQLITE=1`
  обходит с `WARNING`-логом. Модульный флаг
  `_SQLITE_VERSION_CHECKED` предотвращает повторные проверки в
  процессе. Уточнение whitelist-а backport-ов отложено до
  F26 (XS).

### Doc/process (Phase A — прямо в master)
- ORCHESTRATION v1.3: §14.6 верификация галлюцинаций + §15
  реалии multi-model dispatch (6 подразделов: маршрутизация,
  задержки, бюджет, анти-паттерны).
- skill multi-model-consultation v1.1: §2.1 откалиброванная
  routing-matrix, §3.7 паттерн формирования, §6 обновления
  бюджета, §7.8 анти-паттерн (high-reasoning over-flag).
- HF3: docstring `update_target()` — уточнение по slew-rate
  сходимости (Codex T2 re-run CONDITIONAL → PASS).
- Disposition плагинов: автозагрузка oh-my-claudecode выключена
  для процесса движка CryoDAQ.

### Тесты
- 39 новых тестов по F19-F25 (16 F19, 5 F20, 7 F21, 3 F22, 1 F23,
  3 F24, 5 F25).
- Alarm-кластер таргетно: 60 пройдено.
- Misc-кластер таргетно: 13 пройдено.
- Всё проходит, включая регрессионный фикс SQLite 3.50.4
  (изоляция teardown фикстуры).

### Теги
- `v0.43.0` → `678aa64c` (merge misc-кластера).
- merge alarm-кластера → `e0a8f140`.

### Ключевые коммиты этого релиза
- `2e5f34b` — HF3: update_target docstring slew-rate clarification.
- `aaaa38f` — multi-model-consultation v1.1 routing matrix.
- `4115703` — ORCHESTRATION v1.3.
- `20b464b` — plugin disposition (oh-my-claudecode disabled).
- `42f681d` — F20+F21+F22 alarm cluster.
- `4716219` — F22 severity-upgrade in-place documentation.
- `673a428` — F19+F23+F24+F25 misc cluster.

## [0.42.0] — 2026-04-29 — Safety hotfix HF1+HF2

### Главное
- **HF1**: уточнение docstring-а `update_target()` —
  подтверждённый delayed-update дизайн. CRITICAL-находка GLM
  опровергнута проверкой гипотезы: цикл регуляции P=const в
  `Keithley2604B.read_channels()` читает `runtime.p_target` на
  каждый poll-цикл, пересчитывает `target_v = sqrt(p_target * R)`
  и выдаёт SCPI. `update_target()` — delayed-update (≤1 с), не
  no-op. Прямая SCPI-запись явно отклонена, чтобы сохранить
  slew-rate limiting и compliance-проверки.
- **HF2**: `keithley_emergency_off` + `keithley_stop` добавлены в
  `_SLOW_COMMANDS` в `zmq_bridge.py`. Эти safety-команды теперь
  используют `HANDLER_TIMEOUT_SLOW_S` (30 с) вместо быстрого
  envelope-а 2 с. Cancellation медленного USBTMC-пути во время
  fault-событий больше невозможен.

### Источник
Ночная metaswarm-сессия 2026-04-29 — аудит архитектурных слепых
зон Task A (6 моделей × 4 задачи). GLM и Codex отметили эти
находки. Обе верифицированы архитектором по реальному исходнику
до применения фикса.

Лог верификации: `artifacts/handoffs/2026-04-29-task-a-verification.md`.

### Изменено
- `src/cryodaq/core/safety_manager.py` — docstring
  `update_target()` документирует delayed-update дизайн и
  отклонённую альтернативу (прямая SCPI-запись).
- `src/cryodaq/core/zmq_bridge.py` — `"keithley_emergency_off"` и
  `"keithley_stop"` добавлены в frozenset `_SLOW_COMMANDS` с
  поясняющим комментарием.

### Тесты
- 2 новых: `test_slow_commands_covers_safety_critical_hardware_ops`
  (zmq_bridge), `test_update_target_updates_runtime_p_target_immediately`
  (safety_manager).
- Полный набор: 1931 пройдено, 4 пропущено, 0 падений.

### Известные ограничения
- 5 отложенных находок Task A добавлены в ROADMAP как F21–F25
  (не имплементированы в этом релизе): гистерезисный deadband
  (#1.3), эскалация F10 (#1.4), таймстемп RateEstimator (#1.7),
  re-arm interlock-а (#1.8), гейт SQLite WAL (#1.10).

### Теги
- `v0.42.0` → merge-коммит `751b4cf`.

### Ключевые коммиты этого релиза
- `189c4b7` fix(safety): HF1 update_target docstring + HF2 emergency_off slow timeout.
- `751b4cf` merge: HF1+HF2 safety hotfix (Task A verified findings).

---

## [0.41.0] — 2026-04-29 — F10: sensor-диагностика → интеграция в alarm

### Главное

F10 закрыто. Аномальные события sensor-диагностики теперь идут через
Alarm Engine v2: warning-тревога при 5 мин устойчивой аномалии,
critical при 15 мин, авто-сброс при возврате канала в ok.
Telegram-диспатч для диагностических тревог следует существующему
паттерну `_alarm_v2_tick`.

Реализация: 3-цикл ночной Sonnet-батч с Codex-аудитом на цикл.
Quota Gemini исчерпан ночью (MODEL_CAPACITY_EXHAUSTED на всех 4
dispatches); архитектор сделал ручной structural-проход для Cycle 3.

Ратифицированное отклонение от спека: конфиг публикации тревог
живёт в `plugins.yaml` (существующая конвенция
`sensor_diagnostics`), а не в `alarms_v3.yaml`.

F20 добавлен для будущей полировки: агрегация Telegram-уведомлений
для одновременных multi-channel диагностических тревог + per-channel
escalation cooldown. Не блокирующее; в обычной работе ≤16 каналов,
одновременные criticals — признак реальной катастрофы, где flood
предпочтительнее тишины.

### Добавлено

- `SensorDiagnosticsEngine.__init__` получает параметры
  `alarm_publisher`, `warning_duration_s` (default 300 с),
  `critical_duration_s` (default 900 с).
- Dataclass `_AnomalyState` для per-channel отслеживания устойчивой
  аномалии (монотонные часы; one-shot publish-guard-ы на уровень
  severity).
- Мост `_health_to_status()` маппит health_score (0–100) → ok /
  warning / critical (спек требовал status-enum; существующий
  движок использует численный health_score).
- `SensorDiagnosticsEngine.update()` теперь возвращает
  `list[AlarmEvent]` свежеопубликованных событий, чтобы engine
  tick мог диспатчить Telegram.
- `AlarmStateManager.publish_diagnostic_alarm(channel_id, severity,
  age_seconds)` — идемпотентен на канал, создаёт тревогу в той же
  форме, что rule-evaluated alarms; наследует ACK-workflow.
- `AlarmStateManager.clear_diagnostic_alarm(channel_id)` — удаляет
  из active и пишет CLEARED в историю.
- Wiring движка: `alarm_v2_state_mgr` инъектится как
  `alarm_publisher` в `SensorDiagnosticsEngine`; graceful-degradation
  при `alarm_publishing_enabled: false`.
- `_sensor_diag_tick` диспатчит Telegram для возвращённых
  диагностических `AlarmEvent`-ов через `_alarm_dispatch_tasks`
  (управление strong-ref-ами).
- Блок `sensor_diagnostics` в `config/plugins.yaml`:
  `alarm_publishing_enabled`, `warning_duration_s`,
  `critical_duration_s`, `notify_telegram`.
- 17 новых тестов: 11 unit (Cycle 1, публикация sensor_diagnostics)
  + 4 unit (Cycle 2, `AlarmStateManager`) + 2 integration
  (Cycle 3, pipeline).
- Vault: 6 новых subsystem-заметок (Analytics view, F4 lazy replay,
  Web-дашборд, Cooldown-предиктор, Experiment manager, Interlock
  engine).

### Тестовая база

Pre: 0.40.0 — ~300 тестов.
Post: 81 проходит (+17 новых), 0 регрессий.

### Теги

- `v0.41.0` — см. closing commit ниже.

### Closing commit

См. `merge: F10 Cycle 3` на master.

---

## [0.40.0] — 2026-04-29 — F3: проводка данных к виджетам аналитики

### Главное

Фичи F3 + F4 закрыты. 5-цикл ночной Opus-батч с dual-verifier
аудитом на цикл. 86 новых тестов, ~1000 LOC. Все четыре виджета
аналитики подключены; W4 `r_thermal` оставлен как плейсхолдер до
F8.

Архитектурный фикс, пойманный аудитом: `active.get("id")` →
`active.get("experiment_id")` в инвалидации кэша `MainWindowV2` —
`ExperimentInfo.to_payload()` эмитит `"experiment_id"`, не `"id"`.

F19 добавлен в ROADMAP для отложенного обогащения W3 (channel
min/max, top-3 alarms, кликабельные ссылки на артефакты).

Closing commit: `3b626a2` (merge: F3 Cycle 5).

### Добавлено

- **Проводка данных аналитики F3 — W1…W3 + F4 lazy replay** —
  5-цикл батч, закрывающий Phase III.C placeholder → live wiring:
  - **W5 / F4** (Cycle 1): shell-уровневый F4 lazy-open snapshot
    replay. `MainWindowV2._push_analytics` кэширует last-value на
    каждый сеттер; пересдаёт в `AnalyticsView` при lazy open.
    19 новых тестов. (`feat/f3-cycle1`, merged.)
  - **W1 `temperature_trajectory`** (Cycle 2):
    `TemperatureTrajectoryWidget` — multi-group
    `pg.GraphicsLayoutWidget` с per-group `PlotItem`-ами для
    независимого Y-масштаба. Фетчит 7-дневную историю через
    ZMQ-команду `readings_history` при создании. 14 новых тестов.
    (`feat/f3-cycle2`.)
  - **W2 `cooldown_history`** (Cycle 3): `CooldownHistoryWidget` —
    one-shot scatter-plot прошлых длительностей cooldown. Новая
    engine-команда `cooldown_history_get` собирает JSON-метаданные
    по экспериментам. `list_archive_entries` обёрнут в
    `asyncio.to_thread` (event-loop safety). 21 новый тест.
    (`feat/f3-cycle3`.)
  - **W3 `experiment_summary`** (Cycle 4):
    `ExperimentSummaryWidget` — заголовок, длительность, разбивка
    по фазам, число тревог (через существующую команду
    `alarm_v2_history`), ссылки на артефакты. Сеттер
    `set_experiment_status` добавлен в `AnalyticsView` +
    маршрутизация в `MainWindowV2`. 23 новых теста.
    (`feat/f3-cycle4`.)
  - **Cycle 5**: текст `r_thermal_placeholder` для W4 обновлён
    (нота про зависимость от F8); кросс-виджет lifecycle-
    интеграционные тесты (`tests/integration/`, 9 тестов);
    обновлены CHANGELOG + ROADMAP; F19 добавлен в ROADMAP.
    (`feat/f3-cycle5`.)
- **Новая engine-команда `cooldown_history_get`** — async-хендлер
  `_run_cooldown_history_command`; читает JSON-метаданные,
  возвращает прошлые длительности cooldown с граничными
  температурами T1.
- **F19 добавлен в ROADMAP** — отложенные пункты обогащения W3
  (channel min/max, top-3 alarm names, кликабельные ссылки на
  артефакты).

### Исправлено

- **Инвалидация кэша `active.get("experiment_id")`** —
  существовавший баг, в котором `active.get("id")` всегда
  возвращал `None` (несоответствие ключа с
  `ExperimentInfo.to_payload()`, эмитящим `"experiment_id"`).
  Snapshot аналитики никогда не инвалидировался на границе
  эксперимента. Поймано в аудите F3-Cycle 4. Применено и к
  `_on_experiment_status_received`, и к `_active_experiment_id`
  в `main_window_v2.py`.

### Известные пробелы (отложено в F19)

- Таблица min/max/mean per critical channel в W3.
- Топ-3 имени тревог по частоте в W3.
- Кликабельные ссылки на артефакты в W3 через `QDesktopServices`.
- W4 (`r_thermal_placeholder`) остаётся плейсхолдером — зависит
  от F8.

### Тестовая база

86 новых тестов по циклам F3. Полный набор зелёный на master
после всех 5 merge-ев. Существовавшие падения: timezone-drift в
`test_experiment_overlay.py` (известно), flaky ZMQ timing тест
(в изоляции проходит).

- **Экспорт коэффициентов Chebyshev `.cof`** — `export_curve_cof()`
  добавлен в `CalibrationStore`. Портативный текстовый формат:
  per-zone сырые Chebyshev-коэффициенты, переoценимые через
  `numpy.polynomial.chebyshev.chebval()` без зависимости от схемы
  CryoDAQ. (`feat(calibration)` `0fed332`, `fix(cof)` `d0e1c7f`.)

### Удалено

- **Экспорт калибровки `.330` удалён** — `export_curve_330()`
  удалён; `import_curve_file()` отвергает суффикс `.330` с
  `ValueError`. Существующие `.330` файлы в production-ветках
  данных НЕ авто-мигрируются; используйте ручное чтение CSV или
  `git restore` для legacy-доступа. Action
  `calibration_curve_export` в `engine.py` обновлён:
  `curve_330_path` → `curve_cof_path`; аргумент `points` убран.
  GUI calibration-overlay обновлён: кнопка импорта `.330` удалена,
  кнопка экспорта `.330` заменена на `.cof`. (Решение архитектора
  2026-04-25; `0fed332`, `d0e1c7f`, merge `097a26d`, GUI
  `ba6b997`, `b254de2`.)

---

## [0.39.0] — 2026-04-27 — Закрыт B1: ZMQ idle-death (H5 подтверждено)

### Главное

Закрывает 7-дневное расследование B1. Корневая причина:
`asyncio.wait_for(socket.recv(), timeout=1.0)` отменяет внутреннюю
pyzmq-корутину каждую секунду; после ~50 cancellation-ов состояние
libzmq-реактора заклинивает REP-сокет навсегда. Фикс:
`poll(timeout=1000)` + условный `recv()` после `POLLIN`.

### Исправлено

- `fix(zmq)` `1f88d2e` — `ZMQCommandServer._serve_loop` и
  `ZMQSubscriber._receive_loop` заменены на паттерн poll+recv.
  Подтверждено: macOS 180/180 команд чисто; Ubuntu lab PC
  подтверждён.

### Добавлено

- `feat(diag)` `5e7eeac` — `tools/diag_zmq_direct_req.py`: прямой
  REQ к REP движка в обход bridge-подпроцесса. Инструмент D3-
  эксперимента, доказавший engine-side причинность. Регрессионный
  гейт: чистые 180 с = pass.

### Расследование закрыто

- **B1 ZMQ idle-death** — H5 ПОДТВЕРЖДЕНО + ИСПРАВЛЕНО. См.
  `docs/bug_B1_zmq_idle_death_handoff.md` и
  `docs/decisions/2026-04-27-d{1,2,3,4}-*.md`.

### Closing commit

`21a3a28` — release: v0.34.0 (retroactively relabelled v0.39.0).

---

## [0.38.0] — 2026-04-27 — Production hardening: alarms, drivers, launcher

### Главное

Production hardening из ночного Codex-батча (Codex-03/04/05).
Подтягивает валидацию alarm_v2, фиксит несоответствие probe-а
Thyracont и добавляет чистую обработку SIGTERM, чтобы движок больше
не оставался orphan-ом на `systemd stop` или Ctrl+C.

### Исправлено

- `fix(alarms)` `1869910` — валидация порогов alarm_v2 отвергает
  отсутствующие/неверного типа `threshold`-поля; убирает спам
  `KeyError` в логах.
- `fix(thyracont)` `7230c9f` — V1 probe валидирует контрольную
  сумму на connect-е, согласованно с поведением read-path-а;
  предотвращает молчаливый NaN-навсегда на не-VSP63D железе.
- `3215580` — заголовок `channels.yaml` восстановлен из устаревшего
  состояния.

### Добавлено

- `feat(launcher)` `9a8412e` — обработчик SIGTERM/SIGINT;
  engine-подпроцесс получает SIGTERM и чисто выходит на
  systemd stop / Ctrl+C.

### Closing commit

`9a8412e` — feat(launcher): SIGTERM/SIGINT handler prevents engine orphan on shutdown.

---

## [0.37.0] — 2026-04-24 — Починка retry-логики R1 probe

### Главное

Bounded-backoff retry в `_validate_bridge_startup()` чинит гонку
b2b4fb5: однократный probe отвергал здоровые `ipc://`-bridge во
время startup-bind-а движка, ложно перекладывая отказ IV.7 на
transport-слой.

### Исправлено

- `fix(diag)` `c3f4f86` — `_validate_bridge_startup()` в
  `diag_zmq_b1_capture.py` теперь делает retry с bounded
  экспоненциальным backoff-ом вместо падения на первый non-OK ответ.

### Closing commit

`cabd854` — docs: Q4 equivalence check synthesis + D1 close.

---

## [0.36.0] — 2026-04-21 — Инструментарий расследования B1 (мерджнуто 2026-04-24)

> Авторство 2026-04-21 на ветке
> `codex/safe-merge-b1-truth-recovery`, мерджнуто в master
> 2026-04-24. Тег следует топологическому порядку, не дате
> авторства.

### Главное

Переиспользуемые диагностические хелперы и канонический CLI для
B1-захвата для структурного расследования ZMQ-bridge-а. Вывод JSONL
позволяет post-hoc анализ и сравнение между запусками.

### Добавлено

- `8b9ce4a` — `tools/_b1_diagnostics.py`: переиспользуемые хелперы
  `bridge_snapshot` + `direct_engine_probe`.
- `cc090be` — `tools/diag_zmq_b1_capture.py`: канонический CLI
  захвата B1 с JSONL-выводом и структурированными таймингами.
- `40553ea`, `033f87b` — alignment-проходы, синхронизирующие
  хелперы и CLI с изменениями bridge-API.
- `62314be` — пишем таймауты direct probe-а для пост-анализа.

### Closing commit

`62314be` — tools: record direct probe timeouts in B1 capture CLI.

---

## [0.35.0] — 2026-04-24 — Governance оркестрации агентов

### Главное

Governance-инфраструктура после агентского хаоса 2026-04-21
(дублирующие ветки, root-markdown поток, multi-agent drift без
ведущего). Закрепляет CC-центричную модель swarm-а с явной
STOP-дисциплиной, autonomy-band-ом и правилами раскладки
артефактов.

### Добавлено

- `5286fa2` — `docs/ORCHESTRATION.md` v1.1: CC-центричная
  role-матрица, branch-дисциплина, artifact-layout, STOP-дисциплина
  (§13), autonomy band (§13.5).
- `9a1a100` — `.claude/skills/`: multi-model-consultation +
  negative-space skills.
- `587bea8` — `.gitignore`: исключение workspace-ов оркестрации
  агентов (`.omc/`, `.swarm/`, `.audit-run/`, `agentswarm/`,
  `.worktrees/`).

### Closing commit

`af77095` — recon: safe-merge branch commit classification.

---

## [0.34.0] — 2026-04-20 — Hardening ZMQ cmd-plane + полевые фиксы

### Главное

Hardening IV.6 командной плоскости ZMQ: паттерн ephemeral REQ
на команду + watchdog командного канала на лончере. Полевые фиксы
из сессии на Ubuntu lab PC 2026-04-20.

### Сегодня — сессия 2026-04-20 (handoff → GLM-5.1)

Это плотная рабочая запись, не формальный релиз. Полный
handoff-контекст в `HANDOFF_2026-04-20_GLM.md`; следующий
формальный релиз — `0.34.0`, как только B1 будет разрешено через
IV.7.

**Fixed / shipped:**

- `aabd75f` — `engine: wire validate_checksum through Thyracont
  driver loader`. Fixes TopWatchBar pressure em-dash on Ubuntu lab
  PC when VSP206 hardware is connected. `_create_instruments()`
  was ignoring the YAML key entirely; driver defaulted to strict
  checksum validation regardless of config. One-line loader fix;
  config-side `validate_checksum: false` in
  `instruments.local.yaml` now actually applies.

- `74dbbc7` — `reporting: xml_safe sanitizer for python-docx
  compatibility`. Fixes `experiment_generate_report` failure when
  real Keithley 2604B is connected (VISA resource contains `\x00`
  per NI-VISA spec; python-docx rejects XML 1.0 control chars).
  New `src/cryodaq/utils/xml_safe.py` with 10 unit tests. Applied
  at all `add_paragraph()` / `cell.text` sites in
  `src/cryodaq/reporting/sections.py`. `core/experiment.py:782`
  logger upgraded from `log.warning` to `log.exception` — future
  report-gen failures will include tracebacks (how this bug
  survived: only the exception message was ever logged).

- `be51a24` — `zmq: ephemeral REQ per command + cmd-channel
  watchdog (IV.6 partial B1 mitigation)`. Landed the full
  Codex-proposed B1 fix plan: per-command ephemeral REQ socket in
  `zmq_subprocess.cmd_forward_loop`, launcher-side
  `command_channel_stalled()` watchdog in `_poll_bridge_data`,
  `TCP_KEEPALIVE` reverted on command + PUB paths (kept on
  `sub_drain_loop` as orthogonal safeguard). 60/60 unit tests
  green, full subtree 1775/1776 (1 pre-existing flaky).
  **Does NOT fix B1 — Stage 3 diag tools still reproduce it.**
  Committed anyway as architectural improvement matching ZeroMQ
  Guide ch.4 canonical reliable req-reply pattern. Codex's
  shared-REQ-state hypothesis falsified by this experiment.

- Config edits on Ubuntu lab PC (some in git, some local):
  - `interlocks.yaml` — `overheat_cryostat` regex tightened from
    `Т[1-8] .*` to `Т(1|2|3|5|6|7|8) .*`. Т4 sensor is physically
    disconnected (reads 380 K open-circuit), was triggering
    `emergency_off` on Keithley during normal operation.
  - `alarms_v3.yaml` — Т4 added to `uncalibrated` and `all_temp`
    channel groups so `sensor_fault` still publishes WARNING
    without hardware lockout.
  - `instruments.local.yaml` — `validate_checksum: false` on
    Thyracont block (per-machine override; NOT in git).

- Operational on Ubuntu lab PC: `ModemManager` disabled
  (was transiently grabbing `/dev/ttyUSB0`).

**Open / known issues carrying into 0.34.0:**

- **B1 still unresolved.** GUI command channel silently dies
  ~30-120 s after bridge startup on both platforms. IV.7 `ipc://`
  transport experiment is the next attempt — spec at
  `CC_PROMPT_IV_7_IPC_TRANSPORT.md`. Workaround in place:
  watchdog cooldown (TBD commit) prevents the IV.6 restart storm
  regression, system works in 60-120 s cycles with single
  restarts between.

- `alarm_v2.py::_eval_condition` raises `KeyError 'threshold'`
  when evaluating `cooldown_stall` composite. One sub-condition
  is missing a `threshold` field. Log spam, not crash. Pending
  mini-fix.

- Thyracont `_try_v1_probe` probe-vs-read inconsistency. Probe
  always succeeds; read checksum-validates. Driver can "connect"
  and emit NaN forever on non-VSP63D hardware. Pending
  hardening fix.

**Infrastructure:**

- Multi-model development stack adopted (2026-04-20 afternoon).
  Anthropic weekly limit exhausted. Claude Code now routes
  through `claude-code-router` proxy to Chutes (GLM-5.1 primary,
  DeepSeek-V3.2 background, Kimi-K2.5 long-context) for the
  coming ~4-5 days. Codex (ChatGPT subscription) and Gemini
  (Google subscription) remain on their own quotas for
  delegation. See `HANDOFF_2026-04-20_GLM.md` for operational
  details and identity-leakage warnings.

### Изменено

- **Phase III.C — Phase-aware AnalyticsView rebuild.** Rewrote
  `src/cryodaq/gui/shell/views/analytics_view.py` around a
  2 × 2 QGridLayout (main slot `rowspan=2, colspan=1, col=0`;
  top_right and bottom_right 1/4 each). Layout swaps per experiment
  phase according to a new config file `config/analytics_layout.yaml`
  — preparation → temperature overview; vacuum → прогноз вакуума
  (main), temperature + pressure (right column); cooldown → прогноз
  охлаждения (main); measurement → R_тепл live + keithley power;
  warmup / disassembly have their own mappings; unknown / missing
  phase falls back to temperature + pressure + sensor health.
  New widget registry at
  `src/cryodaq/gui/shell/views/analytics_widgets.py`:
  `TemperatureOverviewWidget` (subscribes to the III.B global time
  controller), `VacuumPredictionWidget` + `CooldownPredictionWidget`
  (wrap III.B `PredictionWidget`), `RThermalLiveWidget`,
  `PressureCurrentWidget` (wraps III.B shared `PressurePlot`),
  `SensorHealthSummaryWidget` (reuses II.4 `SeverityChip`),
  `KeithleyPowerWidget`, plus 4 placeholder cards for the widget IDs
  whose data pipelines are not wired yet. Shell wiring: phase string
  from `current_phase` in `TopWatchBar.experiment_status_received`
  propagates into `AnalyticsView.set_phase` via
  `MainWindowV2._on_experiment_status_received`. Public setters
  preserved (`set_cooldown`, `set_r_thermal`, `set_fault`) plus new
  ones (`set_temperature_readings`, `set_pressure_reading`,
  `set_keithley_readings`, `set_instrument_health`,
  `set_vacuum_prediction`). Data forwarding uses duck-typing — each
  setter iterates active widgets and calls a matching method if
  present; inactive widgets are discarded on layout swap. Last
  pushes are cached and replayed into fresh widgets on phase
  transition so the new layout never starts empty. ACCENT / status
  decoupling (III.A) preserved across new widgets; no widget hits
  the legacy status tier in non-status contexts. Tests: 37 new
  cases across `test_analytics_view_phase_aware.py` (17) and
  `test_analytics_widgets.py` (20) plus 2 new wiring cases in
  `test_main_window_v2_analytics_adapter.py` (9 total). Deletes
  obsolete `test_analytics_view.py` (28 hero/rthermal/vacuum-strip
  geometry cases, rendered meaningless by the rebuild).

- **Phase III.B — GlobalTimeWindow + shared PressurePlot +
  PredictionWidget.** `TimeWindow` enum promoted from dashboard-local
  to `cryodaq.gui.state.time_window` with a
  `GlobalTimeWindowController` singleton. Every historical plot
  subscribes — clicking 1мин / 1ч / 6ч / 24ч / Всё on any plot's
  selector updates every subscribed plot across the app. Prediction
  plots do NOT subscribe; they have their own forward horizon
  (1/3/6/12/24/48ч) with uncertainty bands.
  New shared `cryodaq.gui.widgets.shared.PressurePlot` with
  `ScientificLogAxisItem` — scientific-notation log-Y tick labels
  (fixes the missing Y labels in the compact dashboard pressure
  panel). Dashboard `PressurePlotWidget` now delegates to the shared
  component (composition — `_plot` proxy preserved for the
  dashboard-view `setXLink` wiring). Dashboard `TempPlotWidget`
  migrated to `TimeWindowSelector` — local state removed; single
  broadcast-driven controller is the source of truth.
  New shared `cryodaq.gui.widgets.shared.PredictionWidget` skeleton:
  always-full history + 6-button forward horizon + CI band rendered
  as `FillBetweenItem` with `STATUS_INFO` at ~25 % alpha (neutral
  informational tint, never safety colors). «Через N ч» readout
  updates from interpolated central/lower/upper CI series. Full
  analytics integration deferred to III.C — III.B only ships the
  components + tests. ACCENT decoupling (III.A) preserved: selector
  and horizon buttons render checked state in ACCENT, not STATUS_OK.

- **Phase III.A — DS accent/status decoupling.** Fixed semantic
  collision where `STATUS_OK` (safety-green) rendered UI states
  (selected rows, active tabs, primary buttons, mode badge) and read
  to operators as «this is healthy» when the actual meaning was
  «this is selected / active». Introduced two neutral interaction
  tokens: `SELECTION_BG` (subtle tint for selected rows) and
  `FOCUS_RING` (neutral outline for focused elements). Added to all
  12 bundled theme packs and required by `_theme_loader.REQUIRED_TOKENS`.
  Migrated sites: `_style_button("primary")` helpers in 5 overlays
  (operator_log, archive, calibration, conductivity, keithley) now
  use `ACCENT + ON_ACCENT` instead of `STATUS_OK + ON_PRIMARY`;
  `TopWatchBar` mode badge «Эксперимент» now renders as low-emphasis
  `SURFACE_ELEVATED` chip with `FOREGROUND` text + `BORDER_SUBTLE`
  outline (prior filled `STATUS_OK` pill); `ExperimentCard` mode
  badge mirrors TopWatchBar; «Отладка» keeps `STATUS_CAUTION` colour
  because it IS an operator-attention signal but renders as bordered
  chip; `conductivity_panel` auto-sweep progress chunk migrated to
  `ACCENT`. Per-theme ACCENT recalibrated: `warm_stone` `#4a8a5e`
  (identical to STATUS_OK) → `#b89e7a` warm sand; `taupe_quiet`
  `#4a8a5e` (with obsolete «matches STATUS_OK by design» comment) →
  `#a39482` warm taupe (comment removed); `braun` `#476f20` (olive
  hue ≈90°, violated ≥60° invariant) → `#6a7530` moss-olive ≈70°.
  `default_cool` kept at `#7c8cff` indigo (historical baseline).
  All 9 other themes' ACCENT verified hue-distant from STATUS_OK
  and preserved. New tool `python -m tools.theme_previewer` renders
  all 12 themes side-by-side for architect visual review. ADR 002
  captures the decoupling rationale + hue-distance invariants. No
  operator-facing API changes; all Phase II wiring preserved.

### Удалено

- **Phase II.13 legacy cleanup.** All DEPRECATED-marked Phase I-era
  widgets deleted now that their shell-v2 overlay replacements
  (II.1-II.9) ship with Host Integration Contract. Removed source
  files:
  - `src/cryodaq/gui/widgets/alarm_panel.py` (superseded by II.4).
  - `src/cryodaq/gui/widgets/archive_panel.py` (superseded by II.2).
  - `src/cryodaq/gui/widgets/calibration_panel.py` (superseded by II.7).
  - `src/cryodaq/gui/widgets/conductivity_panel.py` (superseded by II.5).
  - `src/cryodaq/gui/widgets/instrument_status.py` (superseded by II.8).
  - `src/cryodaq/gui/widgets/sensor_diag_panel.py` (superseded by II.8 — folded into `InstrumentsPanel._SensorDiagSection`).
  - `src/cryodaq/gui/widgets/keithley_panel.py` (superseded by II.6).
  - `src/cryodaq/gui/widgets/operator_log_panel.py` (superseded by II.3).
  - `src/cryodaq/gui/widgets/experiment_workspace.py` (superseded by II.9; shell overlay retained at `shell/experiment_overlay.py` per Path A).
  - `src/cryodaq/gui/widgets/autosweep_panel.py` (pre-Phase-II DEPRECATED).
  - `src/cryodaq/gui/main_window.py` (v1 tab-based main window; `cryodaq-gui` entry point was already on `MainWindowV2` via `gui/app.py` since Phase I.1).
  Removed test files: 7 legacy widget-specific tests (archive,
  calibration, experiment_workspace, keithley_panel_contract,
  main_window_calibration_integration, operator_log_panel,
  sensor_diag_panel). `widgets/common.py` retained — still consumed
  by non-DEPRECATED widgets (shift_handover, pressure_panel,
  overview_panel, connection_settings, vacuum_trend_panel,
  analytics_panel, channel_editor, temp_panel, experiment_dialogs).

### Изменено

- **Phase II.9 ExperimentOverlay harmonized — DS v1.0.1 (Path A).**
  Stage 0 audit of `src/cryodaq/gui/shell/experiment_overlay.py`
  showed the overlay was already DS v1.0.1-compliant (zero forbidden
  tokens, zero emoji, zero hardcoded hex — shipped clean from B.8).
  Path A surgical harmonization delivered the one remaining gap:
  Host Integration Contract. New `set_connected(bool)` method
  disables `_save_btn`, `_finalize_btn`, `_prev_btn`, `_next_btn`
  on engine silence; `_refresh_display` now respects the connected
  flag when re-rendering after `set_experiment`. Default state is
  connected=True (preserves pre-first-tick functionality). Host
  wiring: `MainWindowV2._tick_status` mirrors connection state;
  `_ensure_overlay("experiment")` replays it on first open (same
  pattern as II.4 / II.8 and earlier overlays). Zero engine command
  signature changes, zero callback interface changes, zero layout
  reordering — Path A diff is mechanically reversible. Path choice
  rationale (Path A over Path B) recorded in
  `docs/design-system/cryodaq-primitives/experiment-panel.md`.
  Tests: 7 new cases in `test_experiment_overlay.py` (17 total) +
  6 new wiring cases.

- **Phase II.8 InstrumentsOverlay (cards + SensorDiag) — DS v1.0.1.**
  Merged two legacy modules (`instrument_status.py` +
  `sensor_diag_panel.py`) into a single overlay at
  `src/cryodaq/gui/shell/overlays/instruments_panel.py`. Both sections
  preserved verbatim: instrument card grid with adaptive liveness
  (median × 5 timeout, 10 s floor, 300 s default, 3-reading adaptive
  threshold), sensor diagnostics table with 10 s polling of
  `get_sensor_diagnostics`. Unicode circle (⬤) in card status
  indicator replaced by painted `_StatusIndicator` (QFrame with QSS
  `border-radius` — no glyph dependency). Summary emoji (✓ ⚠ ✘)
  replaced by `SeverityChip` widgets imported from the II.4 alarm
  overlay, using DS status tokens and Russian labels («N ОК / N ПРЕД
  / N КРИТ»). Hardcoded `QColor(r, g, b, a)` row tints replaced by
  `QColor(theme.STATUS_*)` + alpha. `apply_panel_frame_style` helper
  and deprecated `TEXT_MUTED` / `TEXT_PRIMARY` tokens removed. Host
  Integration Contract wired: `MainWindowV2._tick_status` connection
  mirror + `_ensure_overlay("instruments")` replay. Adaptive liveness
  constants NOT tuned — verified against real instruments. Legacy
  widgets marked DEPRECATED in module docstrings; deletion slated
  for Phase II.13. Tests: 41 overlay cases + 7 host-wiring cases.

- **Phase II.4 AlarmOverlay rebuilt (K1 safety surface).** New
  overlay at `src/cryodaq/gui/shell/overlays/alarm_panel.py` replaces
  the legacy v1 widget in `MainWindowV2`. Dual-engine layout preserved:
  v1 threshold-based table (fed via `on_reading` + `metadata["alarm_name"]`
  filter) and v2 YAML-driven phase-aware table (populated via 3 s
  polling of `alarm_v2_status`). Emoji severity icons (🔴 / 🟡 / 🔵)
  replaced by in-module `SeverityChip` widget using DS status tokens
  (`STATUS_FAULT` / `STATUS_WARNING` / `STATUS_INFO`) with Russian short
  labels (`КРИТ` / `ПРЕД` / `ИНФО`). ACK button styling migrated from
  deprecated `STONE_400` / `TEXT_INVERSE` to `SURFACE_MUTED` /
  `MUTED_FOREGROUND` (disabled) and status-colored active state.
  Host Integration Contract wired: `MainWindowV2._tick_status` mirrors
  connection state into the overlay (pauses v2 polling + disables
  ACK buttons on disconnect). `_dispatch_reading` routes readings
  through `on_reading`. `v2_alarm_count_changed = Signal(int)`
  signature preserved — still consumed by `TopWatchBar.set_alarm_count`.
  New public API: `update_v2_status(payload)`, `get_active_v1_count()`,
  `get_active_v2_count()`. Fail-OPEN preserved (disconnect keeps rows
  visible; engine errors preserve last-known v2 map). Legacy widget
  at `src/cryodaq/gui/widgets/alarm_panel.py` marked DEPRECATED in
  its module docstring; slated for deletion in Phase II.13. Zero legacy
  tokens / zero emoji / zero hardcoded hex (pre-commit gates pass).
  Tests: 51 overlay cases + 7 host-wiring cases.

- **Phase II.7 CalibrationOverlay rebuilt + command wiring.**
  Three-mode overlay at
  `src/cryodaq/gui/shell/overlays/calibration_panel.py` replaces the
  legacy v1 widget. QStackedWidget (Setup / Acquisition / Results)
  auto-switch preserved verbatim (3 s engine poll on
  `calibration_acquisition_status`). CoverageBar migrated from
  hardcoded hex (`#2ECC40` / `#FFDC00` / `#FF851B` / `#333333`) to
  DS tokens (dense → STATUS_OK, medium → STATUS_CAUTION, sparse →
  STATUS_WARNING, empty → MUTED_FOREGROUND). **K3 mandate completed:**
  all six previously-unwired import / export / runtime-apply buttons
  now dispatch real engine commands via `ZmqCommandWorker`:
  `calibration_curve_import` (with `QFileDialog.getOpenFileName`
  picker per format), `calibration_curve_export` (with
  `QFileDialog.getSaveFileName` picker, format-specific path parameter),
  `calibration_runtime_set_global`,
  `calibration_runtime_set_channel_policy` (chained via
  `calibration_curve_lookup` to resolve `curve_id`). Acquisition
  widget's `_experiment_label` / `_elapsed_label` now populated from
  poll result (v1 declared them but never wrote). Public accessors
  `get_current_mode()` / `is_acquisition_active()` added for future
  finalize guards. Host Integration Contract wired:
  `MainWindowV2._tick_status` connection mirror +
  `_ensure_overlay("calibration")` replay; readings routing (shell
  dispatches `unit=="K"` to overlay, overlay filters for
  `_raw` / `sensor_unit` in acquisition mode) preserved from v1. Zero
  legacy tokens / zero emoji / zero hardcoded hex (pre-commit gates
  clean). Legacy widget at
  `src/cryodaq/gui/widgets/calibration_panel.py` marked DEPRECATED;
  removal in Phase III.3.

### Добавлено

- **Six new themes: signal, instrument, amber (dark); gost, xcode,
  braun (light).** STATUS palette hue-locked with lightness unlocked
  for light substrates per ADR 001
  (`docs/design-system/adr/001-light-theme-status-unlock.md`). Dark
  packs continue to ship the verbatim STATUS hex set; new light packs
  (gost / xcode / braun) ship a shifted-lightness variant that
  preserves hue and restores WCAG AA (≥4.5:1) contrast against their
  light `SURFACE_CARD`. Semantic identity («amber = WARNING, red =
  FAULT») preserved 1:1 across mode switches. Settings → Тема menu
  now surfaces all 12 bundled packs in a dark-group / light-group
  layout with a visual separator between groups. Full rationale,
  per-pack design axis, metrics, and pre-release smoke points:
  `docs/design-system/HANDOFF_THEMES_V2.md`.

### Изменено

- **Phase II.5 ConductivityOverlay rebuilt.** Full-featured thermal
  conductivity surface in
  `src/cryodaq/gui/shell/overlays/conductivity_panel.py` replaces the
  legacy v1 widget. Auto-sweep state machine preserved verbatim
  (`idle` / `stabilizing` / `done`, 1 Hz tick, `SteadyStatePredictor`
  driving settling detection with `percent_settled` threshold +
  `min_wait` gate, Keithley power stepping via `ZmqCommandWorker`
  against `keithley_set_target` / `keithley_stop` — unchanged from v1).
  R/G table (11 columns with ИТОГО summary row), stability indicator
  (`dT/dt > 0.01 К/мин` threshold), steady-state banner adapting to
  predictor output, chain selection with reorder buttons + manual
  CSV export. Flight recorder schema preserved (18 columns,
  `utf-8-sig`, `get_data_dir() / conductivity_logs /
  conductivity_<ts>.csv`). Public accessors
  `get_auto_state() -> str` + `is_auto_sweep_active() -> bool`
  replace direct `_auto_state` attribute access for external finalize
  guards (II.9 follow-up wiring). DS v1.0.1 tokens throughout — zero
  legacy tokens, zero emoji, zero hardcoded hex colors (plot pens come
  from `PLOT_LINE_PALETTE` via `series_pen` indexing). Host
  Integration Contract wired: `MainWindowV2._tick_status` connection
  mirror + `_ensure_overlay("conductivity")` replay; readings routing
  (T-prefix + `/smu*/power`) unchanged from v1 shell contract.
  Plugin-duplication concern from project memory: investigated — no
  engine-side R/G publisher exists (grep returns zero matches),
  GUI-side compute is the only path. Legacy widget at
  `src/cryodaq/gui/widgets/conductivity_panel.py` marked DEPRECATED;
  removal in Phase III.3.

- **Phase II.2 ArchiveOverlay rebuilt + K6 bulk export migration.**
  Full-featured experiment archive surface in
  `src/cryodaq/gui/shell/overlays/archive_panel.py` replaces the legacy
  v1 widget. Filter bar (template combo, operator / sample text, start
  / end date range, report presence, sort), 9-column list table with
  FONT_MONO timestamps, details panel with summary / metadata / notes /
  stats / runs / artifacts / results views, action buttons
  (folder / PDF / DOCX / regenerate). K6 mandate: bulk CSV / HDF5 /
  Excel export migrated from the legacy `main_window.py` File menu
  into a dedicated «Экспорт данных» card at the bottom of the overlay
  — `MainWindowV2` has no menu bar, so this was the only path to
  restore global data export. Exports run in a `QThread` worker that
  wraps the existing `cryodaq.storage.{csv_export,hdf5_export,xlsx_export}`
  classes verbatim (no exporter re-implementation); GUI never blocks.
  Emoji pictograms `📊` / `📋` in the legacy artifact view replaced
  with ASCII bracketed tags `[ДАННЫЕ]` / `[ИЗМЕРЕНИЯ]` / `[УСТАВКИ]`
  per RULE-COPY-005; report / data column markers switched from ✓ to
  «Да» for the same reason. DS v1.0.1 tokens exclusively. Host
  Integration Contract wired via `MainWindowV2._tick_status` connection
  mirror + `_ensure_overlay("archive")` replay; `on_reading` is a
  contract no-op (no engine experiment-finalize broker event). Legacy
  widget at `src/cryodaq/gui/widgets/archive_panel.py` marked
  DEPRECATED; removal in Phase III.3. `main_window.py` File menu
  export actions remain intact for the transitional legacy path.

- **Phase II.3 OperatorLog overlay rebuilt.** Full-featured operator
  journal surface in `src/cryodaq/gui/shell/overlays/operator_log_panel.py`
  replaces the legacy v1 widget. Timeline grouped by calendar day,
  quick filter chips (all / current experiment / 8h / 24h), client-side
  text / author / tag filters with 250 ms debounce, composer card with
  tags + experiment binding, append-only with optimistic prepend on
  `log_entry` success, load-more pagination (50-entry steps), DS
  v1.0.1 compliant tokens throughout. Composer author persists via
  `QSettings("FIAN", "CryoDAQ")` key `last_log_author`. Host
  integration contract: `MainWindowV2._tick_status()` mirrors
  connection state, `_on_experiment_status_received()` pushes current
  experiment id, `_ensure_overlay("log")` replays cached state on lazy
  open. Legacy widget at `src/cryodaq/gui/widgets/operator_log_panel.py`
  marked DEPRECATED; removal in Phase III.3. `QuickLogBlock`
  (dashboard) unchanged.

- **Phase II.6 Keithley overlay rebuilt.** Replaces the dead B.7
  mode-based shell overlay (never wired into `MainWindowV2`) and
  supersedes the legacy v1 widget surface visible via Ctrl+K. Full
  power-control semantics matching the engine ZMQ API (`p_target` +
  `v_comp` + `i_comp` only; no `mode=current/voltage`). Per channel:
  P target / V compliance / I compliance `QDoubleSpinBox` with 300 ms
  debounce, 4 live readouts (V / I / R / P) in Fira Mono with tabular
  figures, 2×2 rolling plot grid (V / I / R / P), state badge
  (ВЫКЛ / ВКЛ / АВАРИЯ) driven by
  `analytics/keithley_channel_state/{smua,smub}`. Panel-level «Старт A+B»
  / «Стоп A+B» / «АВАР. ОТКЛ. A+B» (single confirmation dialog for
  A+B emergency), time-window toolbar (10м / 1ч / 6ч) shared across
  channels, safety gate label, connection indicator, transient status
  banner. Design System v1.0.1 compliant — legacy `TEXT_PRIMARY` /
  `QUANTITY_*` tokens replaced throughout; plots use
  `apply_plot_style()` and `PLOT_LINE_PALETTE[0]` for smua,
  `PLOT_LINE_PALETTE[1]` for smub. Stale detection applies only when
  channel state is `"on"`. Emergency confirmation uses
  `QMessageBox.warning` per RULE-INTER-004 destructive variant.
  MainWindowV2 now imports the overlay from
  `cryodaq.gui.shell.overlays.keithley_panel`. Legacy v1 widget at
  `src/cryodaq/gui/widgets/keithley_panel.py` marked DEPRECATED;
  removal scheduled for Phase III.3. K4 custom-command popup (FU.4)
  and HoldConfirm 1 s hold for emergency buttons (FU.5) deliberately
  deferred. Tests: 30 new cases in
  `tests/gui/shell/overlays/test_keithley_panel.py`.

### Добавлено

- **Runtime theme switcher — 6 bundled theme packs.**
  GUI color tokens now load at import time from
  `config/themes/<selected>.yaml` via `src/cryodaq/gui/_theme_loader.py`.
  Bundled packs: `default_cool` (pre-switcher look), `warm_stone` (new
  default — Pantone Warm Gray dark), `anthropic_mono` (brand terracotta),
  `ochre_bloom` (Ableton Ochre, olive accent), `taupe_quiet` (subtle
  warm shift with forest accent), `rose_dusk` (dusty rose, late-night).
  Selection persisted in `config/settings.local.yaml` (gitignored).
  «Настройки → Тема» menu in the launcher offers radio-exclusive
  selection; confirmation dialog warns the GUI restarts in ~1 s while
  engine and data recording continue in the detached engine subprocess.
  The launcher re-execs itself via `os.execv` on theme change — no
  `importlib.reload` cascade (fragile with Qt widget trees and
  module-level pyqtgraph config). New design token `COLD_HIGHLIGHT`
  for cryogenic-channel accent surfaces.

- **Phase I.1 — Overlay Design System primitives (foundational shell).**
  ModalCard (centered card + backdrop dim + 3 close mechanisms),
  DrillDownBreadcrumb (sticky top bar with back navigation),
  BentoGrid (12-column container for Bento tile layout).
  Located at `src/cryodaq/gui/shell/overlays/_design_system/`.
  No application to existing overlays in this block — Phase II applies these
  primitives systematically. Visual showcase at
  `_design_system/_showcase.py` for review before Phase I.2
  (BentoTile + ExecutiveKpi + DataDenseTile + LiveTile).

### Изменено

- **`src/cryodaq/gui/theme.py` — color tokens load from YAML pack at import.**
  Module-level color constants (BACKGROUND, SURFACE_PANEL, ACCENT, status
  tiers, accent scale, text variants) are now read from the active theme
  pack via `_theme_loader.load_theme()`. Non-color tokens (typography,
  spacing, layout, radius, motion, plot palette, legacy STONE_* unique
  stops) remain hardcoded — they do not theme. Downstream consumers still
  use the same `from cryodaq.gui import theme; theme.ACCENT` API.

- **Status palette — one-time semantic refresh (LOCKED across all themes).**
  `STATUS_CAUTION` shifts from `#c47a30` (amber) to `#b35a38` (red-orange)
  to be clearly distinct from `STATUS_WARNING` (`#c4862e`); `STATUS_INFO`
  `#4a7ba8` → `#6490c4` for slightly higher legibility on dark surfaces;
  `COLD_HIGHLIGHT` `#5b8db8` → `#7ab8c4` for better cryogenic-channel
  differentiation. These values are identical across every bundled pack
  including `default_cool` — safety semantics do not shift with style,
  and the refresh is a deliberate improvement, not a regression. Verified
  by `tests/gui/test_theme_loader.py::test_status_palette_identical_across_all_themes`.

- **`apply_panel_frame_style` callers strip GitHub-Primer-dark hex overrides.**
  9 call-sites in `widgets/` (sensor_diag_panel, overview_panel,
  experiment_workspace mode/phase frames, shift_handover, keithley_panel,
  vacuum_trend_panel) previously pinned cold-gray background/border hexes
  (`#11151d` / `#30363d` / `#141821` etc.) that bypassed theme.py and
  prevented theme packs from taking effect. They now inherit
  `theme.SURFACE_PANEL` / `theme.BORDER_SUBTLE` defaults. Semantic hexes
  (debug-panel amber, group-box status accents, `_set_bg` heat-tier
  cases) deliberately retained pending proper STATUS_* tokenization.

### Исправлено

- **Phase I.1 modal layout regression after visual fix round.**
  ModalCard again uses an in-layout chrome row instead of absolute close-button
  positioning, card height once more respects `max_height_vh_pct`, side
  backdrop margins remain visible, and inner content padding is explicit so
  breadcrumb and tiles do not touch the card border. Added regression tests
  for side margins and max-height clamping.

- **Phase UI-1 v2 Block B.6** — ModeBadge widget в TopWatchBar zone 2.
  Показывает текущий AppMode (ЭКСПЕРИМЕНТ / ОТЛАДКА). DEBUG state
  использует amber attention styling потому что режим отключает
  создание архивных записей и отчётов. Badge скрыт пока нет backend
  status (per product rule R1). Закрывает Strategy R1 mode visibility
  safety gap.
- **`src/cryodaq/core/phase_labels.py`** — канонические русские метки
  для ExperimentPhase enum. Единый source of truth для TopWatchBar,
  PhaseAwareWidget и ExperimentWorkspace. Закрывает Strategy R9.
- **B.6.1 hotfix:** Regression-тесты для ModeBadge через full handler
  path `_on_experiment_result` (с и без active_experiment). L8 lesson.
- **B.8.0.2 — ExperimentOverlay + NewExperimentDialog full rebuild.**
  NewExperimentDialog: templates dropdown from backend, operator/sample/
  cryostat autocomplete from QSettings, dynamic custom fields per
  template, name auto-suggest, full legacy payload (template_id, sample,
  cryostat, description, notes, custom_fields). ExperimentOverlay:
  phase pills с past durations + current 2px STATUS_OK highlight,
  prev/next navigation buttons, КАРТОЧКА column (editable sample/
  описание/заметки/custom fields + Сохранить), ХРОНИКА column (last 50
  log entries filtered by experiment, live updates), footer Завершить +
  ⋯ menu с Прервать. Finalize saves card fields first (legacy parity).
- **B.8.0.1 — ExperimentOverlay critical hotfix.** Phase transition
  controls (Назад / Перейти к / Вперёд) добавлены в overlay. Phase
  stepper (reuse PhaseStepper) показывает текущую фазу. Current phase
  indicator в header info line. Status forwarding injects current_phase
  и app_mode в experiment dict для overlay. Operators can now advance
  phase, go back, jump to any phase from overlay.
- **Phase UI-1 v2 Block B.8 — ExperimentWorkspace rebuild as overlay.**
  NewExperimentDialog (modal) с полями name, operator, template,
  description, target_T_cold, tags + validation. ExperimentOverlay
  (full-screen drill-down) с editable inline name, header
  (elapsed/phase/operator/mode), MilestoneList (reuse B.5.5),
  Finalize с destructive confirmation (L9). Triggers: exp_label
  click, tray flask icon, + Создать button; ESC closes overlay.
  Legacy ExperimentWorkspace removed from MainWindowV2.
- **Phase UI-1 v2 Block B.7 — QuickLogBlock dashboard widget.**
  Закрывает последний placeholder `[ЖУРНАЛ — будет в B.6]`. Compact
  peripheral awareness ~55-65px: inline composer + последние 1-2
  entries. Не reading surface — для чтения OperatorLogPanel через
  tray rail. Empty state мотивирует первую запись. 10-second poll
  cycle для обновления + immediate refresh после отправки.
- **B.5.7.3 — Fira fonts load from launcher entry point.** B.5.7.2
  wired font loading only in `cryodaq-gui` entry (`gui/app.py:main`).
  The `cryodaq` launcher creates QApplication + MainWindowV2 directly
  без gui/app.py — font registration bypassed. Fix: call
  `_load_bundled_fonts()` в `launcher.py:main` after QApplication.
  Verified by real launch + QFontInfo resolution check.
- **B.5.7.2 — Fira font loading fix.** `addApplicationFont(path)`
  fails на macOS PySide6/Qt6. Заменён на `addApplicationFontFromData`
  который работает. Fira Sans + Fira Code теперь реально загружены
  в QFontDatabase. До этого Qt делал silent font substitution на
  system default при каждом запуске GUI.
- **B.5.7.1 — TopWatchBar separator normalization.** Унифицирован
  separator mechanism: zone VLine wrappers с consistent spacing
  (contentsMargins), context strip QFrame separators заменены на
  middle dot `·` text labels. Layout spacing = 0, all gaps via
  separator wrapper margins.
- **B.5.7 — Visual polish pass on dashboard.** Plot Y-axis alignment
  (fixed 60px left axis width), pressure plot height ratio tuned (18
  vs 50 stretch), TopWatchBar zone separators (VLines), PhaseStepper
  short Russian labels return (Под/Вак/Зах/Изм/Раст/Раз inline),
  transient state «Ожидание фазы» subdued to italic Body, experiment
  name elide + tooltip.
- **B.5.6 — Compact PhaseAwareWidget.** Phase widget сжат с ~210px
  до ~55px (одна строка). HeroReadout / EtaDisplay / MilestoneList
  primitives сохранены для B.10 Analytics overlay. Stepper pills
  24px, только номер фазы, Russian name в tooltip. Освобождает ~150px
  для графиков (95% операторского внимания).
- **Phase UI-1 v2 Block B.5.5 — 7-mode PhaseAwareWidget extension.**
  PhaseAwareWidget переходит от generic stepper к phase-specific
  content. Cherry-pick scope: cooldown (ETA + R_thermal hero),
  preparation (hint text), measurement (R_thermal hero) с реальным
  content. Vacuum/warmup/teardown показывают placeholder с ссылкой на
  Аналитика overlay. Reason: 5 NEEDS_WIRING + 1 MISSING (warmup
  predictor не существует). PhaseStepper извлечён как отдельный widget.
  Новый package `phase_content/` с HeroReadout, EtaDisplay, MilestoneList.
  Analytics readings (cooldown_eta, R_thermal) роутятся через
  DashboardView в PhaseAwareWidget.
- **B.6.2 — ModeBadge clickable.** Click на badge → confirmation
  dialog → set_app_mode ZMQ command. EXPERIMENT → DEBUG требует
  явного подтверждения (destructive: отключает архив и отчёты).
  Default button = Отмена для обоих направлений переключения.
- **Phase UI-1 v2 Block B.4.5** — Adoption design system из UI UX Pro
  Max skill v2.5.0 (MIT, Next Level Builder). Гибрид Real-Time
  Monitoring + Data-Dense Dashboard. Палитра Smart Home/IoT Dashboard
  расширенная пятью status-тирами. Шрифты Fira Code (display, цифры)
  и Fira Sans (prose, меню) заменяют Inter и JetBrains Mono. 8px grid
  spacing, 4px sharp radius. Backwards-compatible alias'ы в theme.py.
  Документация в docs/design-system/MASTER.md и FINDINGS.md.
- **Phase UI-1 v2 Block B.4.5.1** — Tone-down фикс цветов после
  визуальной оценки B.4.5. Desaturation status tier цветов на 30-40%,
  warmer background `#0d0e12`, видимая card elevation, возврат к
  оригинальному indigo `#7c8cff` accent. Architecture B.4.5 (aliases,
  Fira fonts, документация) полностью сохранены — изменены только
  конкретные hex значения в `theme.py`.
- **Phase UI-1 v2 Block B.4.5.2** — Shell chrome consistency fix.
  Три chrome widgets (TopWatchBar, BottomStatusBar, ToolRail) теперь
  рендерятся как cohesive frame: `WA_StyledBackground` атрибут,
  удалён bubble эффект `_context_frame`, ToolRail мигрирован на
  `#ToolRail` object selector (A.7 compliance), видимый hover state.
- **Phase UI-1 v2 Block B.5** — PhaseAwareWidget. Заменён placeholder
  фазы эксперимента на реальный widget с stepper UI (6 фаз: Подготовка
  / Вакуум / Охлаждение / Измерение / Нагрев / Завершение). Текущая
  фаза подсвечена `theme.ACCENT`, прошедшие muted, будущие dim. Hero
  display с large current phase name + duration counter. Manual
  transition controls: кнопки Назад / Вперёд + dropdown. Backend:
  расширение `/status` payload с `phase_started_at`. Widget получает
  данные через TopWatchBar → MainWindowV2 → DashboardView forwarding.
- **Phase UI-1 v2 Block B.4** — Persistent context strip в
  TopWatchBar. Четыре ключевых значения (давление, T мин, T макс
  холодных каналов, мощность нагревателя) видны постоянно — даже
  когда дашборд закрыт overlay-панелью. T мин и T макс рассчитываются
  только по холодным каналам (новый флаг `is_cold` в channels.yaml),
  чтобы корпусные датчики (вакуумный кожух, фланец, зеркала) не
  загрязняли индикатор. Stale-индикация через 30 секунд.
- **Phase UI-1 v2 Block B.3** — DynamicSensorGrid. Адаптивная сетка
  ячеек датчиков заменяет placeholder в zone дашборда. Inline rename
  по двойному клику, контекстное меню по правому клику, цветной
  border по статусу канала, обновления через ChannelBufferStore +
  push path от DashboardView. ChannelManager получил симметричный
  off_change() для корректной отписки callback'ов.
- **`ChannelManager.get_cold_channels()`** и
  **`get_visible_cold_channels()`** — публичный API для запроса
  cryogenic-classified каналов из конфигурации.
- **Поле `is_cold`** в `config/channels.yaml` для всех 24 каналов.
  Default: `true` (sensible для cryosystem).

### Исправлено

- **`engine.py:35`** — отсутствовал импорт `load_alarm_config`,
  использовался на строке 969. Регрессия от `8070b2db`. Engine падал
  с `NameError` при каждом запуске почти месяц, маскировалось циклом
  перезапуска launcher.

### Изменено

- **Phase I.1 visual polish after Vladimir review.** Showcase placeholder
  labels now render without dark background artifacts, card chrome reduced to
  a single header band, `ModalCard` default max width widened from 1100 to
  1280, `BentoGrid` row-span now affects rendered height (with geometry test),
  breadcrumb back link tightened, and placeholder copy made content-specific.
- **Шрифты** — Inter заменён на Fira Sans, JetBrains Mono заменён на
  Fira Code. Старые файлы остаются в `resources/fonts/` до B.7 cleanup.
- **theme.py** — полностью переработан под новые design tokens.
  Backwards-compatible alias'ы сохранены для постепенной миграции.

### Заимствовано

- **UI UX Pro Max skill** v2.5.0 — design tokens, typography pairings,
  UX guidelines. MIT-лицензия от Next Level Builder.
  https://github.com/nextlevelbuilder/ui-ux-pro-max-skill

### Ключевые коммиты

- `ae7d8d4` fix(engine): add missing load_alarm_config import.
- `c4396a8` ui(phase-1-v2): block B.3 — DynamicSensorGrid.

---

## [0.33.0] — 2026-04-14

Первый tagged-релиз. Hardened-бэкенд и Phase UI-1 v2 shell с
фундаментом dashboard, отгружено одним merge-коммитом `7b453d5`.
Закрывает 20-версионный пробел в changelog со времён v0.13.0.

### Добавлено

- **Phase UI-1 v2 shell (блоки A через A.9).** Новый `MainWindowV2`
  (`gui/shell/main_window_v2.py`) с `TopWatchBar`, `ToolRail`,
  `BottomStatusBar` и `OverlayContainer` заменяет tab-based legacy
  `MainWindow`. Ambient-information-radiator layout для недельных
  экспериментов. Русская локализация повсеместно. Блоки A.5
  (видимость иконок, wiring лончера), A.6 (consolidation chrome,
  русификация), A.7 (фикс layout-коллизии), A.8 (фикс шва фона
  child-виджета), A.9 (заглушки orphan-виджетов, guard стэкования
  worker-ов, summary каналов в зоне 3 ChannelManager).
- **Phase UI-1 v2 dashboard (блоки B.1, B.1.1, B.2).**
  `DashboardView` (`gui/dashboard/dashboard_view.py`) с пятью зонами
  (10/22/44/20/4 stretch ratio после реордера B.1.1). Общий
  `ChannelBufferStore` (`gui/dashboard/channel_buffer.py`) для
  rolling per-channel истории. Enum `TimeWindow`
  (1 мин / 1 ч / 6 ч / 24 ч / Всё). `TempPlotWidget` — multi-channel
  температурный график с кликабельной легендой и Lin/Log-toggle.
  `PressurePlotWidget` — компактный log-Y график давления,
  X-связанный с температурой. Эхо временного окна в зоне 2
  `TopWatchBar`.
- **Phase UI-1 v1 фундамент темы (блоки 1-7).** Дизайн-токены
  `theme.py` (цвета, шрифты, отступы). Шрифты Inter + JetBrains Mono
  в комплекте. 10 SVG-иконок Lucide. Зависимость
  `pyqtdarktheme-fork`. Систематическая классификация и применение
  `setStyleSheet` по всем widget-панелям. Чистка `setBackground`
  pyqtgraph.
- **Phase 2e Stage 1.** Стриминговый архив Parquet, пишется при
  experiment finalize (`storage/parquet_archive.py`). Открывает
  путь к долгосрочной архивации и offline-аналитике. Подтверждено
  отгруженным по CODEX_FULL_AUDIT H.7 (стриминговая запись,
  сжатие, итерация по полночи, UTC-таймстемпы, интеграция в
  finalize).
- **Интеграция Graphify knowledge graph.** Постоянная структурная
  память через `graphify-out/`. Автоматический ребилд на каждом
  коммите и переключении ветки через git-хуки. Top god-узлы:
  `Reading` (789 рёбер), `ChannelStatus` (375), `DataBroker` (246),
  `ZmqCommandWorker` (195), `SafetyManager` (156). Инъекция в
  сессии Claude Code через хук `UserPromptSubmit` (62 мс на запуск).

### Изменено

- **Tier 1 Fix A — канонизация канала калибровки (`a5cd8b7`).**
  `CalibrationAcquisitionService.activate()` канонизирует ссылки
  на каналы через новый
  `ChannelManager.resolve_channel_reference()`. Принимает короткие
  ID (`"Т1"`) или полные метки (`"Т1 Криостат верх"`). Бросает
  новый `CalibrationCommandError` на неизвестные или
  неоднозначные ссылки. Движок возвращает структурированный
  failure-ответ вместо падения. Закрывает Codex round 2 NEW
  finding: "Calibration channel identity is not canonicalized
  before activation" (`engine.py:370-375`,
  `calibration_acquisition.py:92-108`).
- **Tier 1 Fix B — изоляция исключений subscriber-ов DataBroker
  (`cbaa7f2`).** `DataBroker.publish()` оборачивает per-subscriber
  операции в try/except. Один сбойный subscriber больше не отменяет
  fan-out на остальных. `asyncio.CancelledError` всё ещё
  пробрасывается. Защищает subscriber-ов нового v2-dashboard друг
  от друга. Закрывает Codex round 1 finding B.1 / round 2
  подтверждённый HIGH: "DataBroker subscriber exceptions sit on
  critical path before SafetyBroker" (`broker.py:85-109`,
  `scheduler.py:385-389`).
- **Tier 1 Fix C — сериализация acknowledged-состояния тревоги
  (`d9e2fdf`).** `AlarmStateManager.acknowledge()` возвращает dict
  события или `None` (раньше `bool`). Движок публикует событие
  через `DataBroker` на канал `alarm_v2/acknowledged`. Открывает
  путь к будущему v2-бейджу тревог. Ответ `alarm_v2_status`
  включает поля `acknowledged`, `acknowledged_at`,
  `acknowledged_by`. Закрывает отложенный пункт A.9.1 Phase 2d
  (CODEX_FULL_AUDIT H.3).
- **Phase 2d hardening безопасности и персистенса (14 коммитов).**
  Escape stored XSS в web. Аппаратный `emergency_off` в `_fault()`
  защищён от cancellation. Порядок `_fault()`: callback ДО publish
  (Jules R2). Мониторинг heartbeat-а RUN_PERMITTED. Fail-closed
  конфиг для всех 5 safety-adjacent конфигов. Атомарная запись
  файлов через `core/atomic_write`. Верификация WAL mode.
  Персистенс OVERRANGE/UNDERRANGE. Атомарность KRDG+SRDG
  калибровки на poll-цикл. Graceful drain Scheduler-а. Реальная
  реализация `AlarmStateManager.acknowledge` с идемпотентным
  re-ack guard-ом. Долг ruff lint 830 → 445.
- **Лончер и `gui/app.py`.** Точка входа `cryodaq-gui` теперь
  ведёт в `MainWindowV2` как основной shell. Legacy `MainWindow`
  и tab-панели остаются активны для fallback-а до Block B.7.

### Исправлено

- **Баг префикса прибора в панели калибровки (`621f98a`).**
  Существовавший: `gui/widgets/calibration_panel.py` строил ссылки
  каналов в формате `"LS218_1:Т1 Криостат верх"` из combobox-а. До
  Tier-1 это давало молчаливую потерю данных; после Tier-1
  resolver отвергает префиксный формат. Добавлен helper
  `_strip_instrument_prefix()`, применяется к `reference_channel`
  и к каждому `target_channel`.
- **Дубликаты импортов из конфликта rebase (`621f98a`).**
  `gui/main_window.py` и `gui/widgets/experiment_workspace.py`
  имели дубликаты импортов `ZmqBridge` и `get_data_dir` после
  разрешения merge-конфликта v1 block 6. Дубликаты убраны.
- **Сломанный pytest-вызов в `inject_context.py` (`f6fe4b9`).**
  Хук `UserPromptSubmit` запускал `pytest` против системного
  `python3` без модуля pytest, молча падал и инжектил
  `"Tests: no output"` на каждом prompt-е Claude Code. Заменён на
  62-мс версию, использующую git-метаданные + god-узлы graphify.
- **Codex R1 finding A.1 — регрессия атомарности throttle-а
  калибровки.** Изначально CRITICAL, понижено до MEDIUM в R2 после
  проверки, показавшей: общие каналы защищены конфигом.

### Инфраструктура

- **RTK (Rust Token Killer)** — существовавший bash-compression
  hook. Сжатие токенов 60-90% на dev-операциях. Замечание:
  выкидывает флаг `--no-ff` у `git merge` — workaround:
  `/usr/bin/git` напрямую.
- **Graphify skill 0.3.12 → 0.4.13.** Первая сборка графа
  проиндексировала 294 файла в 4 304 узла, 10 602 ребра, 169
  Leiden-communities. ~3.1× сокращение токенов на структурных
  запросах.
- **Git-хуки:** `post-commit` и `post-checkout` для автоматического
  инкрементального ребилда графа.
- **Project-level CC-хук.** `.claude/settings.json` содержит
  `PreToolUse` для `Glob|Grep`, напоминающий Claude сначала читать
  `graphify-out/GRAPH_REPORT.md`.
- **Трёхслойный review-pipeline**, заведённый в Phase 2d: CC
  tactical + Codex second-opinion + Jules architectural. 14
  коммитов, 17 Codex-ревью, 2 Jules-раунда.

### Известные ограничения

- **RTK выкидывает флаг `--no-ff`** у `git merge`. Workaround:
  `/usr/bin/git`.
- **~500 ruff-lint ошибок** в `src/` и `tests/`. Накопленный
  технический долг.
- **Состояние перехода dual-shell.** Legacy `MainWindow`,
  `OverviewPanel` и tab-панели остаются активны параллельно с
  `MainWindowV2` до Block B.7.
- **Чувствительность к wall-clock** в `alarm_providers.py` и
  `channel_state.py` (`time.time()` vs `monotonic()`). Codex R2
  подтвердил находку, ещё не закрыта.
- **Блокирующая генерация отчётов** — синхронный
  `subprocess.run()` для LibreOffice. Codex R1 E.1, всё ещё
  открыт.
- **Пробел между v0.13.0 и v0.33.0.** Версии 0.14.0-0.32.x
  разрабатывались, но индивидуально не помечались тегом.
  Ретроспективное исследование в
  `docs/changelog/RETRO_ANALYSIS_V3.md`.

### Тестовая база

- 934 пройдено, 2 пропущено.
- +39 тестов с начала Phase 2d (baseline 895).
- +11 из Tier 1-фиксов (5 канонизация калибровки, 4 изоляция
  broker-а, 2 сериализация acknowledged тревоги).
- +28 из merge v2 shell и dashboard.
- Ноль регрессий.

### Теги

- `v0.33.0` — merge-коммит `7b453d5`.
- `pre-tier1-merge-backup-2026-04-14` — якорь для отката.

### Ключевые коммиты этого релиза

- `a5cd8b7` tier1-a: canonicalize calibration channel identities.
- `cbaa7f2` tier1-b: isolate DataBroker subscriber exceptions.
- `d9e2fdf` tier1-c: serialize alarm acknowledged state through broker.
- `7b453d5` merge: Phase UI-1 v2 shell и dashboard through Block B.2.
- `621f98a` post-merge fixes: calibration prefix strip + dedupe imports.
- `dafdd99` docs: post-merge PROJECT_STATUS и CLAUDE.md updates.
- `f6fe4b9` infra: graphify setup + inject_context hook efficiency fix.

Подробная коммит-история Phase 2d (14 коммитов): см. секцию
«Phase 2d commits» в `PROJECT_STATUS.md`. Audit-трейл Codex:
`docs/audits/CODEX_FULL_AUDIT.md` и
`docs/audits/CODEX_ROUND_2_AUDIT.md`.

### Заметки об обновлении

Не применимо — внутренний релиз.

---

## [0.32.0] — 14-04-26 — Phase 2d: закрытие и fail-closed

Завершающая часть Phase 2d. Очистка lint-долга, закрытие замечаний
Jules Round 2, завершение fail-closed конфигурации, официальное
объявление Phase 2d завершённым.

### Исправлено

- **Ruff lint** — накопленный долг сокращён с 830 до 445 ошибок
  (`efe6b49`, 132 файла).
- **Jules R2: `_fault()` ordering** — post-mortem log callback вызывается
  ДО optional broker publish, устраняя escape path при отмене.
- **Jules R2: calibration state mutation** — `prepare_srdg_readings()`
  вычисляет pending state, `on_srdg_persisted()` применяет атомарно
  после успешной записи. Устраняет расхождение `t_min`/`t_max`
  при сбое записи.

### Изменено

- **Fail-closed завершён** — `interlocks.yaml`, `housekeeping.yaml`,
  `channels.yaml` теперь вызывают `InterlockConfigError` /
  `HousekeepingConfigError` / `ChannelConfigError` при отсутствии
  или повреждении. Engine exit code 2.
- **`scheduler_drain_timeout_s`** — вынесен в `safety.yaml` (default 5s).
- **Phase 2d объявлен COMPLETE**, открыт Phase 2e.
- Удалён случайно закоммиченный каталог `logs/`, добавлен в `.gitignore`.

Диапазон коммитов: `efe6b49`..`0cd8a94` (5 commits)

---

## [0.31.0] — 13-04-26 — Phase 2d: безопасность и целостность данных

Основная часть Phase 2d — структурированная закалка безопасности
и целостности. Block A (safety) и Block B (persistence) объединены
в один релиз с промежуточным checkpoint.

### Добавлено

- **`core/atomic_write.py`** — атомарная запись файлов через
  `os.replace()` для experiment sidecars и calibration index/curve.
- **WAL mode verification** — engine отказывается запускаться если
  `PRAGMA journal_mode=WAL` вернул не `'wal'`.
- **OVERRANGE/UNDERRANGE persist** — `±inf` сохраняются как REAL в
  SQLite. NaN-valued statuses (`SENSOR_ERROR`, `TIMEOUT`)
  отфильтровываются для избежания `IntegrityError`.
- **SafetyConfigError / AlarmConfigError** — typed exception hierarchy
  для fail-closed конфигурации safety и alarm.

### Изменено

- **Web XSS** — `escapeHtml()` helper для stored XSS escape.
- **`_fault()` cancellation shielding** — `emergency_off`,
  `_fault_log_callback`, `_ensure_output_off` в `_safe_off`
  обёрнуты в `asyncio.shield()`.
- **RUN_PERMITTED heartbeat** — мониторинг застрявшего `start_source`
  detection.
- **Safety→operator_log bridge** — fault events публикуются через broker.
- **AlarmStateManager.acknowledge** — реальная реализация с idempotent
  re-ack guard.
- **KRDG+SRDG atomic** — calibration readings persist в одной
  транзакции per poll cycle.
- **Scheduler.stop()** — graceful drain (configurable, default 5s)
  перед forced cancel.

Диапазон коммитов: `88feee5`..`23929ca` (10 commits)

---

## [0.30.0] — 12-04-26 — Карта реальности и документация

Сверка документации с кодом по результатам аудит-корпуса. Построение
карты «документ vs реальность», перезапись guidance, расширение
модульного индекса CLAUDE.md.

### Добавлено

- **DOC_REALITY_MAP** — сверка 28 организационных документов
  против 62 non-GUI модулей (CC + Codex review).
- **CLAUDE.md module index** — расширение покрытия с ~34% до ~70%.
- **CLAUDE.md safety FSM** — исправлены инварианты и добавлено
  состояние `MANUAL_RECOVERY`.

### Изменено

- **Skill `cryodaq-team-lead`** — полная перезапись под текущую
  реальность репозитория.
- **Config list** — добавлены недостающие файлы конфигурации.

Диапазон коммитов: `995f7bc`..`1d71ecc` (4 commits)

---

## [0.29.0] — 09-04-26 — Аудит-корпус

Проект тратит целую главу на самоаудит. 11 глубинных документов
общим объёмом ~9 400 строк покрывают каждую крупную подсистему.

### Добавлено

- **CC deep audit** — 1 240 строк post-2c анализа.
- **Codex deep audit** — 763 строки overnight-анализа.
- **Verification pass** — повторная проверка 5 HIGH findings.
- **SafetyManager deep dive** — исчерпывающий FSM-анализ (1 062 строки).
- **Persistence trace** — exhaustive проверка persistence-first
  инварианта (1 090 строк).
- **Driver fault injection** — сценарии инъекции сбоев для драйверов
  (1 366 строк).
- **CVE sweep** — полный анализ зависимостей (286 строк).
- **Analytics/reporting deep dive** — 572 строки.
- **Config audit** — 719 строк.
- **Master triage** — синтез всех аудит-документов (307 строк).

Диапазон коммитов: `380df96`..`7aaeb2b` (12 commits)

---

## [0.28.0] — 31-03-26 — Подготовка к Phase 2d

Явная подготовительная волна перед структурированной закалкой.
Очистка поверхностных проблем чтобы Phase 2d мог сосредоточиться
на глубинных инвариантах.

### Исправлено

- **Codex audit findings** — `plugins.yaml` латинская T,
  `sensor_diagnostics` resolution, GUI non-blocking paths.
- **GUI non-blocking** — `send_command` + dead code cleanup (57 файлов).
- **Phase 1** — разблокировка сборки PyInstaller.
- **Phase 2a** — закрытие 4 HIGH findings (safety hardening).
- **Phase 2b** — закрытие 8 MEDIUM findings (observability и resilience).
- **Phase 2c** — закрытие 8 findings (финальная закалка).

### Изменено

- **Overview preset** — "Сутки" переименован в "Всё".

Диапазон коммитов: `9676165`..`1698150` (7 commits)

---

## [0.27.0] — 24-03-26 — Неблокирующий GUI и singleton

Устранение блокирующего поведения GUI и launcher при deployment stress.
Singleton protection для предотвращения двойного запуска.

### Добавлено

- **Single-instance protection** — для launcher и standalone GUI
  через атомарный lock-файл.

### Исправлено

- **Alarm v2 status poll** — убрана блокировка из polling path.
- **Bridge heartbeat** — false kills + blocking `send_command`
  в launcher.
- **Conductivity panel** — blocking `send_command` заменён на async.
- **Keithley spinbox** — debounce + non-blocking live update.
- **Experiment workspace** — 1080p layout для phase bar и passport forms.
- **Launcher** — non-blocking engine restart + deployment hardening.
- **Shift modal** — re-entrancy + engine `--force` `PermissionError`.

Диапазон коммитов: `8bac038`..`f217427` (8 commits)

---

## [0.26.0] — 23-03-26 — GPIB-восстановление и preflight

Улучшение восстановления после зависания аппаратуры и настройка
поведения preflight checklist под операционную реальность.

### Добавлено

- **GPIB auto-recovery** — очистка шины по timeout, preventive clear.
- **GPIB escalating recovery** — IFC bus reset, enable unaddressing.
- **Scheduler disconnect+reconnect** — автоматическое при серии ошибок.

### Изменено

- **Preflight sensor health** — понижен с error до warning (не должен
  блокировать эксперимент).

Диапазон коммитов: `ab57e01`..`dfd6021` (5 commits)

---

## [0.25.0] — 22-03-26 — Аудит v2, Parquet v1 и отчётность

Слияние audit-v2, первая версия Parquet-архива, CI pipeline и
профессиональная отчётность по ГОСТ Р 2.105-2019.

### Добавлено

- **Parquet archive v1** — `readings.parquet` рядом с CSV при
  финализации эксперимента. Столбец Parquet в таблице архива.
- **CI workflow** — тестирование и линтинг.
- **Отчётность** — professional human-readable reports для всех типов
  экспериментов. Форматирование по ГОСТ Р 2.105-2019, все графики
  во всех отчётах, smart page breaks.

### Исправлено

- **Audit-v2 merge** — 29 дефектов закрыты (9 коммитов в ветке).
- **Archive filter** — inclusive end-date, добавлен столбец end time.
- **Audit regression** — preflight severity, multi-day DB, overview
  resolver, parquet docstring.

Диапазон коммитов: `0fdc507`..`29d2215` (9 commits)

---

## [0.24.0] — 21-03-26 — Интеграция финального батча

Слияние ветки final-batch с single-instance lock, ZMQ request/reply
routing, experiment I/O threading и fixes для overview/history.

### Добавлено

- **ZMQ correlation ID** — для command-reply routing.
- **Future-per-request dispatcher** — dedicated reply consumer.

### Исправлено

- **Telegram** — natural channel sort, compact text, pressure log-Y.
- **Single-instance lock** — атомарный через `O_CREAT|O_EXCL`.
- **Experiment I/O** — перенесён в thread, удалена двойная генерация
  отчётов.
- **UI history** — proportional load, overview plot sync, CSV BOM.
- **Graph X-axis** — snap к началу данных на всех 7 панелях.

Диапазон коммитов: `9e2ce5b`..`dd42632` (9 commits)

---

## [0.23.0] — 21-03-26 — Слияние UI-рефакторинга

Слияние ветки `feature/ui-refactor` и немедленная стабилизация
интегрированного состояния.

### Добавлено

- **Вкладка Keithley** — переименована, добавлены кнопки time window
  и forecast zone.

### Изменено

- **UI-refactor merge** — `1ec93a6`, значительная переработка UI.
- **Default channels** — обновлены, web version синхронизирована.
- **`autosweep_panel`** — помечен как deprecated.

### Исправлено

- **Thyracont MV00 fallback** + SQLite read/write split + SafetyManager
  transition + Keithley disconnect.
- **UI cards** — toggle signals, history load, axis alignment, channel
  refresh.
- **QuickStart buttons** — удалены из overview (вызывали FAULT с P=0).
- **Audit wave 3** — `build_ensemble` guard, launcher ping, phase gap,
  RDGST, docs.

Диапазон коммитов: `1ec93a6`..`f08e6bb` (8 commits)

---

## [0.22.0] — 20-03-26 — Углубление безопасности и ревью

Безопасность и корректность углубляются после выхода аналитических
поверхностей. Закрытие результатов deep review и audit batch.

### Добавлено

- **Phase 2 safety** — тесты + bugfixes + LakeShore `RDGST?`.
- **Phase 3** — safety correctness, reliability, phase detector.

### Исправлено

- **ZMQ datetime** — сериализация + REP socket stuck на ошибке.
- **Deep review** — 2 бага исправлены, 2 теста добавлены.
- **Audit batch** — 6 bugов: safety race, SQLite shutdown, Inf filter,
  phase reset, GPIB leak, deque cap.
- **UI** — CSV BOM, sensor diag stretch, calibration stretch, reports
  toggle, adaptive liveness.

Диапазон коммитов: `afabfe5`..`af94285` (6 commits)

---

## [0.21.0] — 20-03-26 — Аналитика и безопасность Keithley

Feature-growth релиз: новые аналитические модули и расширение
runtime-диагностики. Трёхэтапный rollout для каждого модуля:
backend → engine → GUI.

### Добавлено

- **Keithley safety** — slew rate limit, compliance detection +
  ZMQ subprocess hardening.
- **SensorDiagnosticsEngine** — MAD-noise, OLS drift, Pearson
  correlation, health score 0-100. Backend (Stage 1) + engine
  integration + config (Stage 2) + GUI panel + status bar (Stage 3).
  20 unit tests.
- **VacuumTrendPredictor** — 3 модели откачки (exp/power/combined),
  BIC model selection, ETA. Backend (Stage 1) + engine (Stage 2) +
  GUI panel на вкладке Аналитика (Stage 3). 20 unit tests.

Диапазон коммитов: `856ad19`..`50e30e3` (7 commits)

---

## [0.20.0] — 19-03-26 — GPIB-стабилизация и ZMQ-изоляция

Непрерывный инженерный марафон: добиться надёжности транспорта
для непрерывного автоматического опроса, затем изолировать
последнюю хрупкую зависимость.

### Изменено

- **GPIB bus lock** — расширен scope: покрытие `open_resource()` и
  `close()`, атомарная верификация.
- **GPIB стратегии** — последовательно опробованы open-per-query,
  IFC reset, sequential polling, hot-path clear; в итоге persistent
  sessions (LabVIEW-стиль open-once).
- **`KRDG?`** — уточнения команды + GUI visual fixes.

### Добавлено

- **ZMQ subprocess isolation** — GUI больше не импортирует `zmq`
  напрямую. `zmq_subprocess.py` запускается в отдельном процессе.

Диапазон коммитов: `5bc640c`..`f64d981` (9 commits)

---

## [0.19.0] — 18-03-26 — Первое аппаратное развёртывание

Программное обеспечение впервые встречается с реальными приборами
и исправляется ими. Широкий sweep аппаратных проблем: GPIB, Thyracont,
Keithley, алармы, давление.

### Исправлено

- **GPIB bus lock** — покрытие `open_resource()` и `close()`, а не
  только query/write. Устранение гонки `-420 Query UNTERMINATED`.
- **Keithley source-off** — NaN при выключенном источнике приводил к
  `SQLite NOT NULL` crash. Добавлена обработка `float('nan')`.
- **Thyracont VSP63D** — протокол V1 вместо SCPI `*IDN?`; формула
  давления исправлена: 6 цифр (4 мантисса + 2 экспонента),
  `(ABCD/1000) × 10^(EF-20)`. Три итерации коррекции.
- **Rate check** — ограничен scope до critical channels only,
  отключённые датчики исключены из проверки.

### Изменено

- **Keithley P=const** — перенесён с TSP/Lua на host-side control loop
  в `keithley_2604b.py`. Удалён blocking TSP скрипт.
- **Keithley live update** — `P_target` обновляется на лету + исправлена
  кнопка Stop.

Диапазон коммитов: `d7c843f`..`1b5c099` (9 commits)

---

## [0.18.0] — 18-03-26 — Стабилизация после релиза

Небольшой стабилизационный релиз сразу после волны remote ops
и alarm v2.

### Исправлено

- **Memory leak** — broadcast task explosion, rate estimator trim,
  history cap.
- **Empty plots** — после GUI reconnect + wrong experiment status key.

### Добавлено

- **Tray-only mode** — headless engine monitoring без main window.

Диапазон коммитов: `92e1369`..`c7ae2ed` (3 commits)

---

## [0.17.0] — 18-03-26 — Alarm v2

Полный rollout alarm engine v2. Шесть коммитов за 22 минуты:
фундамент → evaluator → провайдеры → интеграция → fix → GUI.

### Добавлено

- **RateEstimator** — OLS-based dX/dt оценка скорости изменения (K/мин)
  с подавлением шума, скользящее окно.
- **ChannelStateTracker** — отслеживание актуального состояния каналов,
  stale detection, fault history.
- **AlarmEvaluator** — composite (AND/OR), threshold, rate, stale alarm
  types; `deviation_from_setpoint`, `outside_range`, `fault_count_in_window`.
- **AlarmStateManager** — dedup, sustained_s, гистерезис, история
  переходов, acknowledge.
- **Alarm v2 providers** — `ExperimentPhaseProvider`, `ExperimentSetpointProvider`
  через `ExperimentManager`. Config parser для `alarms_v3.yaml`.
- **Alarm v2 GUI** — секция с цветовыми уровнями, ACK, поллинг каждые 3с.
- **Engine integration** — `DataBroker` subscriber для обновления state/rate,
  периодический `alarm_tick` с фазовым фильтром.

### Исправлено

- **`interlocks.yaml`** — удалён `undercool_shield` (ложное срабатывание
  при cooldown), `detector_warmup` переведён на T12.

Диапазон коммитов: `88357b8`..`d3b58bd` (6 commits)

---

## [0.16.0] — 18-03-26 — Удалённый мониторинг и preflight

Расширение операционной поверхности без изменения alarm engine.
Первый real remote-ops релиз.

### Добавлено

- **Web dashboard** — read-only мониторинг с auto-refresh 5с,
  FastAPI + self-contained HTML, `/api/status`, `/api/log`, `/ws`.
- **Telegram bot v2** — `/log <text>`, `/phase <phase>`, `/temps`;
  `EscalationService` (delayed multi-level chain).
- **Pre-flight checklist** — диалог перед созданием эксперимента:
  engine, safety, инструменты, алармы, давление, диск.
- **Experiment auto-fill** — `UserPreferences`, `QCompleter` на
  operator/sample/cryostat, автоимя с инкрементом.

### Исправлено

- **Telegram polling** — debug startup + ensure task started.

Диапазон коммитов: `7ee15de`..`4405348` (5 commits)

---

## [0.15.0] — 18-03-26 — Первый лабораторный релиз

Явный release commit. Даже без сохранившегося тега, этот коммит
остаётся чётким маркером «первая система, готовая для лаборатории».

### Изменено

- **Release v0.12.0** — первый production release commit.

Диапазон коммитов: `c22eca9` (1 commit)

---

## [0.14.0] — 17-03-26 — Фазы экспериментов и авто-отчёты

Дисциплина экспериментов: фазы, автоматическое логирование,
авто-отчёты при финализации, polish UX.

### Добавлено

- **ExperimentPhase** — preparation → vacuum → cooldown → measurement →
  warmup → teardown. Переход через `experiment_advance_phase`.
- **EventLogger** — автоматическая запись: Keithley start/stop/e-off,
  эксперимент start/finalize/abort, смена фазы.
- **Авто-отчёт** — генерация при финализации если шаблон включает
  `report_enabled`.
- **Calibration start button** — запуск калибровки прямо с вкладки.

### Исправлено

- **P1 audit** — phase widget, empty states, auto-entry styling,
  `DateAxisItem` everywhere.
- **Russian labels** — полная синхронизация документации.

Диапазон коммитов: `bc41589`..`3b6a175` (5 commits)

---

## [0.13.0] — 17-03-26 — Калибровка v2

Полный pipeline калибровки v2: непрерывный сбор SRDG при
калибровочных экспериментах, post-run pipeline, трёхрежимный GUI.

### Добавлено

- **`CalibrationAcquisitionService`** — непрерывный сбор SRDG
  параллельно с KRDG при калибровочном эксперименте.
- **`CalibrationFitter`** — post-run pipeline: извлечение пар из SQLite,
  адаптивный downsample, Douglas-Peucker breakpoints, Chebyshev fit.
- **Калибровка GUI** — трёхрежимная вкладка: Setup (выбор каналов,
  импорт) → Acquisition (live stats, coverage bar) → Results (метрики,
  export). `.330` / `.340` / JSON export.
  *(Note: `.330` format removed post-v0.39.0; `.cof` Chebyshev coefficient
  export added — see [Unreleased].)*

### Изменено

- Удалён legacy `CalibrationSessionStore` и ручной workflow.

Диапазон коммитов: `81ef8a6`..`98a5951` (4 commits)

---

## [0.12.0] — 17-03-26 — Итерация обзора

Итерация производительности и layout overview panel. Горячие клавиши,
async ZMQ polling, переработка launcher.

### Добавлено

- **Горячие клавиши** — Ctrl+L (журнал), Ctrl+E (эксперимент),
  Ctrl+1..9/0 (вкладки), Ctrl+Shift+X (аварийное отключение Keithley),
  F5 (обновление).
- **Async ZMQ polling** — `ZmqCommandWorker` вместо синхронного
  `send_command` на таймерах.

### Изменено

- **Overview layout** — двухколоночный: графики температуры и давления
  (связанная ось X). Кликабельные карточки температур (toggle видимости).
  `DateAxisItem` (HH:MM) на всех графиках.
- **Launcher** — восстановлено меню, поддержка `--mock`,
  исправлен дубликат tray icon (`embedded=True`).
- **UX** — все labels на русском, прижатие layout к верху на вкладке
  Приборы, empty state overlays на Аналитика и Теплопроводность.

Диапазон коммитов: `3dea162`..`2136623` (9 commits)

---

## [0.11.0] — 17-03-26 — Dashboard hub и смены

Dashboard hub с quick-actions для Keithley, quick log, experiment
status. Структурированная система смены операторов.

### Добавлено

- **Dashboard hub** — Keithley quick-actions, quick log, experiment
  status на overview.
- **Shift handover** — `ShiftBar` с заступлением, периодическими
  проверками (2ч) и сдачей смены. Данные смен через operator log
  с tags.

Диапазон коммитов: `29652a2`..`f910c40` (4 commits)

---

## [0.10.0] — 17-03-26 — RC-слияние Codex

Одиночный merge commit, интегрирующий работу из ветки `CRYODAQ-CODEX`.
+14 690 / -6 632 строк через 83 файла. Backend workflows (experiments,
reports, housekeeping, calibration), GUI workflows (tray status,
operator hardening), packaging metadata.

### Изменено

- **Codex RC merge** — `dc2ea6a`, масштабное слияние всех backend и
  GUI workflow из параллельной ветки разработки.

Диапазон коммитов: `dc2ea6a` (1 commit)

---

## [0.9.0] — 15-03-26 — P1-исправления и instrument_id

Исправления развёртывания P1 (8 дефектов) и BREAKING изменение
контракта данных: `instrument_id` становится first-class полем
на `Reading` dataclass.

### Исправлено

- **P1-01: Async ZMQ** — persistent socket + `ZmqCommandWorker(QThread)`
  для non-blocking emergency off.
- **P1-02: AutoSweep compliance** — V_comp (10V) и I_comp (0.1A)
  spinboxes; удалены hardcoded 40V/3A.
- **P1-03: Heartbeat regex** — configurable `keithley_channels` patterns
  из `safety.yaml`; проверка freshness AND status.
- **P1-04: Centralized paths** — `paths.py` с `get_data_dir()`.
- **P1-05: Experiment menu** — dialog с name/operator/sample/description.
- **P1-06: Persistent aiohttp** — `_get_session()` + `close()` в
  Telegram notifier/bot/reporter.
- **P1-07: SQLite REAL timestamp** — новые БД используют `REAL`;
  `_parse_timestamp()` поддерживает оба формата.
- **P1-08: Composite index** — `idx_channel_ts ON readings (channel, timestamp)`.

### Изменено

- **BREAKING: `instrument_id`** — промотирован в first-class поле
  `Reading` dataclass. 37 затронутых файлов.

Диапазон коммитов: `de715dc`..`0078d57` (6 commits)

---

## [0.8.0] — 14-03-26 — Аудит и P0-исправления

Первая волна аудита безопасности (14 fixes) и 5 критических P0
дефектов. Тестовая база: 118 тестов.

### Исправлено

- **Safety audit (14 fixes)** — `FAULT_LATCHED` latch, status checks,
  heartbeat, state transitions.
- **P0-01: Alarm pipeline** — `AlarmEngine` публикует события и
  `analytics/alarm_count` через `DataBroker`; `filter_fn` предотвращает
  feedback loops.
- **P0-02: Safety state publish** — `analytics/safety_state` Reading
  на каждом переходе + initial snapshot.
- **P0-03: P/V/I limits** — `max_power_w=5W`, `max_voltage_v=40V`,
  `max_current_a=1A` валидируются в `request_run()` ДО `RUN_PERMITTED`.
- **P0-04: Emergency_off latched** — возвращает `{latched: true}` при
  `FAULT_LATCHED`.
- **P0-05: smub cleanup** — вкладка отключена в GUI, удалена из
  autosweep dropdown (впоследствии восстановлена в dual-channel модели).

### Добавлено

- **Тестовая база** — 118 тестов через все модули (`734f641`).

Диапазон коммитов: `e9a538f`..`0f8dd59` (4 commits)

---

## [0.7.0] — 14-03-26 — Cooldown predictor и обзор

Интеграция ensemble-предиктора охлаждения. Overview panel, экспорт,
DiskMonitor.

### Добавлено

- **Cooldown predictor** — `cooldown_predictor.py` (~900 строк):
  dual-channel progress variable, rate-adaptive weighting, LOO
  validation, quality-gated ingest.
- **`cooldown_service.py`** — asyncio-сервис: `CooldownDetector`
  (IDLE→COOLING→STABILIZING→COMPLETE), периодический predict (30с),
  автоматический ingest.
- **GUI** — ETA ±CI, progress bar, фаза, пунктирная траектория с CI
  band на вкладке Аналитика.
- **CLI** — `cryodaq-cooldown build|predict|validate|demo|update`.
- **`config/cooldown.yaml`** — конфигурация каналов, детекции, модели.
- **Overview panel** — объединение температур + давления в единый
  dashboard с StatusStrip, 24 карточками, графиками.
- **Экспорт** — CSV, Excel (openpyxl), HDF5 через меню Файл.
- **DiskMonitor** — проверка свободного места каждые 5 мин,
  WARNING <10 GB, CRITICAL <2 GB.
- 26 новых тестов (16 предиктор + 10 сервис).

Диапазон коммитов: `9217489`..`9390419` (7 commits)

---

## [0.6.0] — 14-03-26 — SafetyManager и безопасность данных

Архитектура безопасности и persistence-first ordering.

### Добавлено

- **SafetyManager** — 6-state FSM: SAFE_OFF → READY → RUN_PERMITTED →
  RUNNING → FAULT_LATCHED → MANUAL_RECOVERY. Fail-on-silence: устаревшие
  данные (>10с) → FAULT + `emergency_off`. Rate limit: dT/dt >5 K/мин
  → FAULT. Two-step recovery с указанием причины + 60с cooldown.
- **SafetyBroker** — выделенный канал безопасности, overflow=FAULT
  (не drop).
- **Persistence-first ordering** — `SQLiteWriter.write_immediate()` WAL
  commit ПЕРЕД публикацией в `DataBroker`. Гарантия: если данные видны
  оператору — они уже на диске. 7 новых тестов.

### Изменено

- **SQLiteWriter** — вызывается напрямую из Scheduler (не через broker).

Диапазон коммитов: `603a472`..`a8e8bbf` (8 commits)

---

## [0.5.0] — 14-03-26 — Launcher и двухканальный Keithley

Operator launcher, dual-channel Keithley, workflow теплопроводности,
централизованное управление каналами.

### Добавлено

- **Launcher** (`cryodaq`) — operator launcher: engine + GUI + system
  tray, auto-restart.
- **Dual-channel Keithley** — backend, driver и GUI поддерживают `smua`,
  `smub` и одновременную работу `smua+smub`.
- **Вкладка Теплопроводность** — выбор цепочки датчиков, R/G, T∞
  прогноз. Автоизмерение (развёрт P₁→P₂→…→Pₙ) интегрировано.
- **ChannelManager** — централизованные имена и видимость каналов,
  YAML persistence.
- **ConnectionSettingsDialog** — настройка адресов приборов из GUI.

Диапазон коммитов: `77638b0`..`b2b4d97` (5 commits)

---

## [0.4.0] — 14-03-26 — Третий прибор и тестовая база

Thyracont VSP63D (третий прибор), все вкладки GUI активны,
руководство оператора, полная тестовая база.

### Добавлено

- **Thyracont VSP63D driver** — RS-232, протокол MV00, вакуумметр.
- **Serial transport** — async pyserial wrapper.
- **Вкладка Давление** — лог-шкала, цветовая индикация.
- **Все 10 GUI вкладок** — полностью функциональны.
- **`docs/operator_manual.md`** — руководство оператора на русском.
- **Agent Teams Skill v2** — `.claude/skills/cryodaq-team-lead.md`
  для Claude Code (6 ролей, 4 инварианта).
- **Code review (13 пунктов)** — CRITICAL: отозван утёкший Telegram bot
  token. Удалён `__del__` из Keithley driver. `asyncio.create_task()`
  вместо deprecated `get_event_loop()`. InterlockCondition regex
  pre-compiled. DataBroker tuple snapshot iteration.
- `install.bat`, `create_shortcut.py` — Windows installer helpers.
- `docs/deployment.md`, `docs/first_deployment.md`.

Диапазон коммитов: `33e51f3`..`da825f1` (9 commits)

---

## [0.3.0] — 14-03-26 — Скелет workflow

Entry points engine и GUI, experiment lifecycle, Telegram уведомления,
web dashboard, периодические отчёты.

### Добавлено

- **Engine + GUI entry points** — `cryodaq-engine`, `cryodaq-gui`
  в `pyproject.toml`. Main window с панелью алармов и статусом приборов.
- **Experiment lifecycle** — `ExperimentManager` с start/stop, config
  snapshot, SQLite persistence.
- **Data export** — CSV, HDF5 экспорт из SQLite. `ReplaySource` для
  воспроизведения исторических данных.
- **TelegramNotifier** — alarm events → Telegram Bot API.
- **PeriodicReporter** — matplotlib графики + текстовая сводка в
  Telegram каждые 30 мин.
- **Web dashboard** — FastAPI + WebSocket + Chart.js, тёмная тема.

Диапазон коммитов: `e64b516`..`e4bbcb6` (4 commits)

---

## [0.2.0] — 14-03-26 — Инструменты и аналитика

LakeShore 218S и Keithley 2604B drivers, первые alarm и analytics
abstractions, plugin pipeline.

### Добавлено

- **LakeShore 218S driver** — GPIB, SCPI, `KRDG?` без аргумента
  для batch считывания 8 каналов, 3 прибора = 24 канала.
- **Keithley 2604B driver** — USB-TMC, TSP/Lua supervisor (`p_const.lua`),
  heartbeat, `emergency_off`.
- **AlarmEngine** — state machine (OK → ACTIVE → ACKNOWLEDGED),
  hysteresis, severity levels.
- **PluginPipeline** — hot-reload `.py` из `plugins/`, watchdog
  filesystem events, error isolation.
- **ThermalCalculator plugin** — R_thermal = (T_hot - T_cold) / P.
- **CooldownEstimator plugin** — exponential decay fit → cooldown ETA.
- **InterlockEngine** — threshold detection, regex channel matching.
- **Вкладка Температуры** — 24 ChannelCard + pyqtgraph, ring buffer.
- **Вкладка Алармы** — severity table, acknowledge.
- **Вкладка Keithley** — smua/smub: V/I/R/P графики + управление.
- **Вкладка Аналитика** — R_thermal plot + cooldown ETA.
- `config/interlocks.yaml`, `config/alarms.yaml`,
  `config/notifications.yaml`.

Диапазон коммитов: `0c54010`..`75ebdc1` (4 commits)

---

## [0.1.0] — 14-03-26 — Начальная архитектура

Первые коммиты проекта. Базовая двухпроцессная архитектура с headless
engine и PySide6 GUI, связанными через ZeroMQ. Первый скелет сбора
данных, персистентности и межпроцессного взаимодействия.

### Добавлено

- **Архитектурный контракт** в `CLAUDE.md` — описание двухпроцессной
  модели, инвариантов безопасности, правил разработки.
- **Пакетная структура** — `pyproject.toml`, каталоги `src/cryodaq/`,
  driver ABC, `DataBroker` (fan-out pub/sub с bounded `asyncio.Queue`
  и политикой `DROP_OLDEST`).
- **SQLiteWriter** — WAL mode, crash-safe, batch insert, daily rotation.
- **Scheduler** — per-instrument polling с exponential backoff и
  автоматическим реконнектом.
- **ZMQ bridge** — PUB/SUB на порту :5555 (msgpack) + REP/REQ :5556
  (JSON) для команд GUI → engine.

Диапазон коммитов: `be52137`..`2882845` (4 commits)
