# CryoDAQ — PROJECT_STATUS

**Дата:** 2026-07-14 *(release baseline v0.64.1 + active pre-lab campaign note)*
**Релизная ветка:** master
**Активная campaign-ветка:** `feat/montana-phase-a` (последний recorded exact-SHA checkpoint `b7b1356`)
**Релизная граница:** tag `v0.64.1`
**Версия пакета:** 0.64.1 (released 2026-07-08)
**Тесты:** 3 657 selected / 3 658 collected (1 deselected: `@ollama` marker). Последний зелёный полный прогон — 3 608 passed / 2 skipped на baseline v0.63.0.
**CI релизной линии:** GitHub Actions (`.github/workflows/main.yml`) — зелёный на полном сьюте `ubuntu-latest` + `windows-latest`, начиная с v0.64.0. Это **первый полностью зелёный прогон в истории репозитория** (ранее сборка обрывалась на lint-шаге до запуска pytest, маскируя падения).
**CI recorded checkpoint:** PASS — sharded exact-SHA run `29340534592` для `b7b1356` завершён зелёным: agents/core/GUI/remaining PASS на Windows и Ubuntu. Safe SQLite verification прошла во всех jobs; lint и requirements-lock drift checks прошли в обоих remaining jobs. Каждый более новый candidate требует свой exact-SHA eight-job PASS. Это не закрывает frozen-build, soak-duration, physical-hardware, F35 frozen-packaging или F36 production-activation gates.
**Фронтир:** Release train v0.58.0 → v0.64.0 отгружен 2026-07-07/08.
После релиза активна software-side pre-lab campaign: H3/H4 runtime/ONEDIR,
F35 ASC extension contract и F36 operator/fleet readiness из `ROADMAP.md`.
Физическая лабораторная верификация остаётся отдельным честным гейтом в
`docs/lab_verification_checklist.md`; ни один software/mock pass её не закрывает.

---

## Масштаб проекта на границе релиза v0.64.1

| Метрика | Значение |
|---|---|
| Python файлы (`src/cryodaq/`) | **216** |
| Строки кода (`src/cryodaq/`) | **~68 900** |
| Тестовые файлы (`tests/`) | **361** |
| Строки тестов (`tests/`) | **~80 500** |
| Тесты | **3 657 selected / 3 658 collected** (1 deselected: `@ollama` marker) |
| Coverage (full suite) | re-run pending (на лабораторном ПК) |
| Design System | **v1.0.1**, 85 `.md` файлов в `docs/design-system/`, 139 токенов в `theme.py` |
| Версия пакета | **0.64.1** |
| Python | 3.12+ (CI закреплён на 3.13) |

Это зафиксированный снимок релизной границы v0.64.1, а не live-инвентарь
текущей feature-ветки. `CHANGELOG.md` хранит shipped history; детали по
архитектуре — в `docs/architecture.md`. Метрики обновляются на следующей
авторизованной релизной границе.

---

## Физическая установка

| Прибор | Интерфейс | Каналы | Драйвер |
|---|---|---|---|
| LakeShore 218S (x3) | GPIB | 24 температурных | `lakeshore_218s.py` |
| Keithley 2604B | USB-TMC | smua + smub | `keithley_2604b.py` |
| Thyracont VSP63D | RS-232 | 1 давление | `thyracont_vsp63d.py` |
| Etalon MultiLine | TCP/IP | интерферометрическая метрология длины | `etalon_multiline.py` |

Т11 / Т12 — позиционно зафиксированные ступени GM-cooler-а, единственные
`critical_channels` для FSM безопасности (`safety.yaml`, с v0.55.4).

### Аппаратные / рантайм инварианты

1. **SAFE_OFF** — состояние по умолчанию. Source ON = непрерывное доказательство здоровья.
2. **Persistence-first:** `SQLiteWriter.write_immediate()` → `DataBroker` → `SafetyBroker`.
3. **SafetyState FSM:** 6 состояний — `SAFE_OFF → READY → RUN_PERMITTED → RUNNING → FAULT_LATCHED → MANUAL_RECOVERY → READY`.
4. **Fail-on-silence:** stale data → FAULT (только в RUNNING; вне RUNNING блокирует readiness через preconditions).
5. **Rate limit:** `dT/dt > 5 K/мин` → FAULT (конфигурируемый default в `safety.yaml`, не жёсткий инвариант).
6. **Keithley connect** forces OUTPUT_OFF на обоих SMU (best-effort, с v0.64 — verified readback).
7. **Keithley disconnect** вызывает `emergency_off()` первым.
8. **No blocking I/O** на engine event loop (исключение: `reporting/generator.py` sync `subprocess.run` для LibreOffice).
9. **No numpy/scipy** в `drivers/core` (исключение: `core/sensor_diagnostics.py` — MAD/корреляция).
10. **OVERRANGE/UNDERRANGE** persist с `status`; non-finite (SENSOR_ERROR/TIMEOUT) обрабатываются NaN-доктриной (см. инвариант 24).
11. **Cancellation shielding** на `_fault()` post-fault paths: `emergency_off`, `fault_log_callback` (before publish), `_ensure_output_off` в `_safe_off`.
12. **Fail-closed config:** `safety.yaml`, `alarms_v3.yaml`, `interlocks.yaml`, `housekeeping.yaml`, `channels.yaml` → subsystem-specific `ConfigError` → engine exit code 2 (без auto-restart).
13. **Atomic file writes** для experiment sidecars и calibration index/curve через `core/atomic_write`.
14. **WAL mode verification:** engine останавливается с `RuntimeError`, если SQLite `journal_mode=WAL` не подтвердился.
15. **Calibration KRDG+SRDG** persist в одной транзакции per poll cycle. State mutation deferred to `on_srdg_persisted`.
16. **Scheduler.stop()** — graceful drain (configurable via `safety.yaml scheduler_drain_timeout_s`, default 5s) перед forced cancel.
17. **_fault() ordering:** post-mortem log callback BEFORE optional broker publish.
18. **_fault() re-entry guard:** ранний `return` если `state == FAULT_LATCHED`, предотвращает overwrite `_fault_reason` + duplicate events / emergency_off при параллельных вызовах.
19. **_SLOW_COMMANDS:** `keithley_emergency_off` / `keithley_stop` используют `HANDLER_TIMEOUT_SLOW_S` (30 s), не fast 2 s envelope (`zmq_bridge.py`).
20. **Severity upgrade in-place:** `AlarmStateManager.publish_diagnostic_alarm()` upgrades WARNING→CRITICAL на том же `alarm_id`; история пишет `SEVERITY_UPGRADED`.
21. **RateEstimator measurement timestamp:** rate estimator берёт `reading.timestamp.timestamp()`, не `time.monotonic()`.
22. **SQLite WAL startup gate:** `_check_sqlite_version()` raises `RuntimeError` на версиях `[3.7.0, 3.51.3)`.

### Инварианты релизного поезда v0.57–v0.64

23. **Verified-off fail-closed (v0.57 / v0.58 / v0.64).** `emergency_off()` возвращает `bool`; неподтверждённый OFF (ошибка записи или readback = «включено») эскалирует в `FAULT_LATCHED`, а не в ложный `SAFE_OFF`. Тот же контракт на `stop_source`, interlock-трипе и `connect()` force-OFF (readback-verified, неудача ставит блокирующее RUN-предусловие).
24. **NaN-доктрина (v0.59).** `Reading.is_usable()` — единый предикат (usable ⟺ `status == OK` и значение finite); `status` дискриминатор на каждом слое. Non-finite пишутся единым finite sentinel (`-8.888e88`, `storage/sentinel.py`); каждый reader декодирует пары `(value, status)` на read-boundary — sentinel или legacy `±inf` не всплывёт числом. Устойчиво non-usable readings на интерлок-каналах эскалируют debounced (≥5 подряд ≥10 s → `on_interlock_dead_channel`, латч только в RUNNING).
25. **Rate-clock robustness (v0.57 / v0.59).** Защита 5 K/мин взводится по временно́му охвату (`min_span_s=30`), не по числу точек. Clock-jump guard: backward-шаг или forward-gap >4× медианного периода чистит буфер и якорится на текущем сэмпле (reset-not-drop, слепота ≤ ~30 s).
26. **SQLite fail-closed runtime (v0.64 + pre-lab hardening).** `environment.yml` фиксирует Python 3.14 и безопасный SQLite 3.53.2 для Windows/Linux; F25 проверяет реально выбранную реализацию и запрещает запуск в диапазоне WAL-reset corruption. Опциональный `pysqlite3` принимается только если сам проходит тот же гейт; небезопасного bundled fallback больше нет. Все runtime-импортёры берут sqlite3 из шима — одна библиотека на БД.
27. **Cold-storage archive layer (v0.61 / v0.63).** `ArchiveReader` объединяет горячий SQLite и холодный Parquet (`query_rows`, end-exclusive, union+dedup на overlap-днях). `ColdRotationService` включён по умолчанию (`cold_rotation.enabled: true`), раз в сутки в `schedule_time`; данные старше 30 дней остаются видны в GUI-истории, журнале оператора, отчётах, экспорте, replay и калибровке. Retention не трогает дневные БД при включённой ротации.
28. **REST-периметр (v0.58 / v0.60).** `/api/v1` — read-only GET-фасад (Pydantic-модели как field-whitelist) плюс ровно два authenticated write-endpoint (`POST /log` append, `POST /alarms/{id}/ack`) за `require_write_token` (токен в gitignored `config/web.local.yaml`, fail-closed default). Loopback-only bind; `zmq_bridge` отбивает wildcard-bind.
29. **Path jail (v0.58).** Все operator-supplied пути импорта/экспорта калибровки confined через `core/path_jail.resolve_within()` (realpath + commonpath + normcase); escape → `{ok: false}`.
30. **ZMQ size-caps (v0.58).** `ZMQ_MAXMSGSIZE` на командном REP (256 KiB) и data-SUB (2 MiB) до bind/connect; `_unpack_reading` — bounded msgpack с per-type `max_*_len`.
31. **TSP late-pet check — operator-selected mode (v0.62).** `keithley.watchdog.mode`: `off` (driver default, байт-идентичен прежнему потоку команд) | `best_effort` | `required`. V3 явно неавтономен: `best_effort` покрывает только stall-then-recover, а `required` fail-closed отказывает при `cryodaq_wdog_autonomous=0`. Полный host-death OFF требует нового документированного решения и независимого стендового доказательства.

---

## Архитектура

```
Instruments → Scheduler → SQLiteWriter → DataBroker → ZMQ → GUI (PySide6)
                                       → SafetyBroker → SafetyManager
                                       → CalibrationAcquisition
                          ArchiveReader ← SQLite (hot) ∪ Parquet (cold)
```

- **Engine** (headless asyncio): drivers, scheduler, persistence, safety, alarms, interlocks, plugins, cold-rotation и операторские контуры уведомлений/поиска.
- **GUI** (PySide6): shell-v2 `MainWindowV2` (TopWatchBar + ToolRail + BottomStatusBar + overlay container) + dashboard + shell-overlays. Легаси v1-виджетный слой удалён (ME-16, v0.61).
- **Web** (FastAPI, опционально): read-only мониторинг + REST `/api/v1` на loopback `:8080`.
- **IPC:** ZeroMQ PUB/SUB `:5555` (data, msgpack) + REP/REQ `:5556` (commands, JSON), с socket-level size-caps.

Актуальный module index — `docs/architecture.md`.

---

## Хронология релизов

Полная история с commit-ссылками — `CHANGELOG.md`. Ниже — сводка по релизам
после v0.44.0.

### Операторские подсказки и знания (v0.45.0 → v0.50.0)

- **v0.45.0 — Гемма Live.** Контур, наблюдающий события движка: 4 триггера уведомлений (alarm / finalize / anomaly / handover), диагностические подсказки, вступление к отчёту (DOCX), GUI-панель инсайтов, audit-лог, config-only смена модели.
- **v0.46.x — периодические нарративные отчёты.** Таймер движка агрегирует события за N минут → русский нарратив → Telegram, со skip на idle-часах.
- **v0.47.x — Live Query.** Оператор спрашивает «что сейчас?» / «ETA вакуума» свободным текстом или `/ask`: классификация намерения → детерминированный service-adapter fetch → русский ответ.
- **v0.50.0 — F27 фотографии композиции через Telegram.** Фото эксперимента → подтверждение через inline-клавиатуру → persist в `<artifact_dir>/composition/` с sidecar; GUI-галерея, live-refresh по ZMQ-событию.

### Тревоги физического состояния и prediction-overlay-и (v0.51.0 → v0.52.x)

- **v0.51.0 — F-X v3.** Предикторные phase-aware тревоги: `CooldownAlarm` (траектория предиктора охлаждения) + `VacuumGuard` (давление × опорная температура) в WATCHDOG-режиме.
- **v0.52.0 — F-P1/2/3.** Overlay-и предсказаний на вкладке «Аналитика»: траектория охлаждения (± σ), проекция вакуумной течи, асимптота теплопроводности (R_thermal).
- **v0.52.2 — data-driven пол предиктора** + поддержка квазистационарного режима (реальная база ~2.9 K, не hardcode 4 K).
- **v0.52.1–v0.52.11** — русификация интерфейса, аппаратное соответствие Т11/Т12, deep-audit фиксы аналитики.

### Replay-режим (v0.53.x)

- **v0.53.0 — F-Replay.** 5-stage replay mode + bootstrap предиктора: воспроизведение исторических записей через ZMQ-совместимый replay-engine.
- **v0.53.1–v0.53.2 — F-ReplayPredictor.** `CooldownService` поверх replay-потока; проводка кнопок горизонта, стек считывания предиктора.

### Sinks, knowledge base, MultiLine (v0.54.0 → v0.55.x)

- **F31 sinks foundation.** `cryodaq.sinks`: filesystem Markdown note sink (finalize/stop/abort), webhook POST `ExperimentExport`, concurrent fan-out registry, команда `sinks_status`.
- **F32 knowledge-base indexer.** Индексация archive metadata, операторских заметок и operator log; поиск top-K по LanceDB. PDF-загрузчик для equipment-manuals (v0.55.7.1).
- **F-MultiLine Stage 1 + continuous.** Etalon MultiLine по новому line-based ASCII TCP-транспорту (`drivers/transport/tcp.py`); continuous-mode (`startmeasnogui` push) с decimation; burst-захват вибрации в Parquet.
- **F33 архивный query-интерфейс** + **F34 GUI chat overlay** — оба отгружены под зонтиком v0.54.0.
- **F-ChannelLandmarks / F-LegacyChannelMap** — системная идентичность каналов + карта переименований для replay старых записей.
- **v0.55.4** — политика `CooldownAlarm` (`auto_arm`), `critical_channels` сужены до Т11/Т12, «Алармы» → «Тревоги» в UI.
- **v0.56.x** — hotfix-серия: Y-axis deadband, `BrokerSnapshot` по каноническим id, `predictor.t_elapsed` от `reading_ts`.

### Release train — hardening (v0.57.0 → v0.64.0)

- **v0.57.0 — fail-closed на краях.** `emergency_off` fail-closed, span-based rate-gate, KRDG-fallback вне диапазона калибровки, детерминированный выбор кривой, cold-rotation больше не уничтожает `operator_log`/`source_data`, NaN-guard-ы на rolling-эстиматорах. CI lint-gate доведён до зелёного, Python в CI закреплён на 3.13, починены 7 ранее скрытых падавших тестов.
- **v0.58.0 — периметр мониторинга.** Read-only REST `/api/v1` + Swagger, socket-level ZMQ size-caps + bounded msgpack, path-jail для путей калибровки, per-cooldown fingerprint + сравнение с золотым эталоном (backend + GUI-карточка «История охлаждений»), inert-плумбинг TSP-watchdog. Регенерация `requirements-lock.txt` + CI drift-gate.
- **v0.59.0 — NaN-доктрина end-to-end.** `Reading.is_usable()`, sentinel-persistence, decode на всех read-boundary, debounced NaN-эскалация на интерлоках, reset-not-drop guard на rate-clock.
- **v0.60.0 — harden-loopback.** Write-auth token-зависимость (fail-closed default), ровно два allowlisted authenticated write-endpoint (log append + alarm ack), auth-before-parse middleware, reserved-tag guard, wildcard-bind reject; REP trust-model задокументирован как by-design для single-operator lab.
- **v0.61.0 — final sweep.** ME-16: удалён осиротевший v1-виджетный слой (−6634 LOC); собран контур холодного хранения (`ColdRotationService` + `ArchiveReader.query_rows`, CSV/XLSX/HDF5/отчёты через архивный слой); `ultimate_vacuum` в cooldown-fingerprint; GUI steady-state-фиды под NaN-доктриной.
- **v0.62.0 — TSP watchdog operator-selected mode.** `off | best_effort | required`; неблокирующий lua; latch-протокол чтения защёлки до загрузки скрипта.
- **v0.63.0 — Known Limitations закрыты.** Все исторические читатели переведены на архивный слой; холодная ротация впервые включена по умолчанию; громкая PDF-деградация; добавлен `docs/lab_verification_checklist.md`.
- **v0.64.0 — excellence-прогон.** Safety-ядро: дисциплина verified-off end-to-end (две fail-open дыры закрыты); retention больше не душит cold rotation (legacy `.db.gz` спасаются); тогда был добавлен SQLite auto-fallback (позже удалён pre-lab hardening из-за небезопасной bundled-версии); opt-in эскалация `VacuumGuard` в SafetyManager; чистота event loop + целостность SafetyBroker; config/docs когерентность. CI впервые полностью зелёный на ubuntu + windows.

---

## Открытые задачи

До поездки в лабораторию закрываются безопасные software-side задачи:

1. H3/H4: integrated runtime/lifecycle slice `026bf50` прошёл detached
   clean-SHA gate (4 939 passed / 11 skipped / 1 deselected). H4 R3a
   provider-neutral delivery receipt и durable state-v2 committed. H4 R3b
   (launcher-owned socketpair, bounded PNG/caption frames, runner ledger before
   ACK) остаётся в работе; short soak, 72-hour soak и реальный Windows ONEDIR
   evidence открыты.
2. Persistence P1A committed: FIFO, physical-cap и integrity gates,
   receipt-authorized ack, cancellation и close settlement сохраняются.
3. F35: F35.1 registry/capability и F35.2 shared-bus contracts committed.
   F35.3 D1 manifest authority, D2 persistence activation, D3 owner-issued
   committed receipts, D5 replay parity и D6 reporting parity завершены.
   Passive conformance harness, ASC reference TCP driver, registry adoption и
   exact frozen-driver allowlist committed как foundations. D4 live descriptor
   wire и D7.1 descriptor-qualified GUI ingress committed. D7 generic
   instrument-health presentation now attributes cards only from authoritative
   connected descriptors. D7.4 proves real-localhost descriptor ingress,
   restart invalidation ordering и shutdown/rebind on native Windows and WSL.
   Software reference-extension e2e proof замыкает один
   scheduler-produced artifact через persistence/live wire,
   replay/report projection, real shell dispatch и instrument-health display.
   Открыты specialized shell-routing heuristics и Windows ONEDIR/frozen
   evidence; mock TCP не закрывает physical/hardware gate.
4. F36: committed foundation включает wire envelope, durable revision
   allocator, typed authority receipts, ordered composer, replay-compatible
   publisher, отдельный snapshot SUB, один GUI-thread Store, pure replay session
   и conservative live adapters. SafetyManager cache + live safety/readiness
   authority доступны и fail-conservative. Один supervised production path
   теперь использует actual loop-owned experiment/acquisition/direct-SQLite
   persistence feeds, один durable revision allocator и sole PUB socket;
   cold/disconnected cuts fail-dark, а stale/ambiguous persistence остаётся
   явно NOT_RECORDING/unavailable без fallback writer. Открыты atomic shell cutover,
   все 12 operator scenarios и
   связанные accessibility/performance gates.
   После интеграции frontend в реальный shell обязателен isolated mock/replay
   запуск со скриншотами каждого достижимого экрана и material state. Visual QA
   проверяет operator scenarios, clipping, focus, stale/disconnected truth,
   non-color cues и соответствие design system; одни скриншоты gate не закрывают.
5. Recorded exact-SHA CI checkpoint `29340534592` для `b7b1356`: все восемь
   agents/core/GUI/remaining jobs PASS на Ubuntu и Windows. Safe SQLite
   verification прошла во всех jobs; lint и requirements-lock drift
   checks PASS в обоих remaining jobs. Каждый новый candidate требует
   свой exact-SHA eight-job PASS;
   frozen-build, soak-duration, physical-hardware, F35 frozen-packaging и F36
   production-activation gates остаются открыты.
6. Готовые точные Windows/physical evidence procedures с thresholds,
   abort/rollback и ожидаемыми артефактами.

Отдельно остаются проверки, требующие физического доступа к приборам и
лабораторным ПК — полный turnkey-протокол в
`docs/lab_verification_checklist.md`:

1. **Гейт версии SQLite на лабораторном Ubuntu ПК** — создать tracked `environment.yml`, подтвердить выбранную безопасную версию и отказ запуска вне неё; bundled self-heal не считается доказательством.
2. **Верификация H5 / ZMQ idle-death** на текущем лабораторном ПК (регрессионный гейт `diag_zmq_direct_req.py`, 180 s без зависаний).
3. **Runtime-калибровка LakeShore на реальном железе** — per-channel KRDG/SRDG, консервативный откат на KRDG вне диапазона.
4. **Keithley A8a–A8e, не один armed-mode checkbox** — A8a (upload/version/
   explicit non-autonomous contract) и A8b (late-pet stall-recovery) выполняются
   на dummy-нагрузке; A8c (host death без последующей команды), A8d
   (независимые terminal V/I/P + trip time) и A8e (внешний final element +
   common-cause proof) остаются физическими блокерами. Ни один подпункт не
   заменяет другой; Phase C заблокирована до A8c–A8e.
5. **Smoke frozen-сборки на Windows** — `install.bat` + ярлык + запуск лаунчера. Снимает ручной гейт Windows frozen-build smoke.

### Известная проблема

- При завершении engine в логе один `ERROR «Unclosed client session»` (aiohttp-сессия не закрывается на shutdown-пути; замечено boot-smoke прогоном mock-engine). Косметика exit-пути — данные и safety не затронуты; фикс в следующем train (см. `CHANGELOG.md [0.64.0]`, Known Issues).

---

## Ключевые решения

1. **Dual-channel Keithley (`smua` + `smub`)** — confirmed operational model.
2. **Persistence-first** — SQLite WAL commit BEFORE any subscriber sees data.
3. **Fail-closed config** — все 5 safety-adjacent configs предотвращают запуск движка при missing / malformed файлах.
4. **Cancellation shielding** — hardware `emergency_off`, post-mortem log emission, `_safe_off` cleanup все `asyncio.shield`'d. Log callback ordered BEFORE optional publish.
5. **`_fault()` re-entry guard** — ранний return если state=`FAULT_LATCHED`.
6. **NaN-доктрина** — `status` дискриминатор; non-finite persist как единый sentinel, декодируются на read-boundary.
7. **Atomic sidecar writes** — experiment metadata, calibration index/curve через `core/atomic_write`.
8. **WAL mode verification** — engine refuses to start, если SQLite не включает WAL.
9. **Graceful scheduler drain** — configurable via `safety.yaml scheduler_drain_timeout_s`.
10. **Verified-off fail-closed** — неподтверждённый OFF латчит FAULT, а не ложный SAFE_OFF (все три call-site класса CR-2 + connect force-OFF).
11. **Calibration state deferral** — `prepare_srdg_readings` считает pending state, `on_srdg_persisted` применяет атомарно после успешной записи.
12. **Design system v1.0.1 canonical** — `docs/design-system/**` — единственный источник правды по UI. Значения токенов берутся ТОЛЬКО из `theme.py`.
13. **Mnemonic shortcuts canonical per AD-002** — `Ctrl+L/E/A/K/M/R/C/D`. Владелец биндингов — `main_window_v2.py` после ретайра v1-shell (Phase II.13).
14. **SQLite fail-closed runtime** — `environment.yml` фиксирует безопасный Python-linked SQLite для Windows/Linux; shim выбирает реализацию один раз и F25 проверяет её до записи. Bypass-флаг `CRYODAQ_ALLOW_BROKEN_SQLITE=1` — крайняя мера-подтверждение, не исправление.
15. **Cold-storage lossless** — архивный Parquet хранит сырые пары `(value, status)`; маскирование делают reader-ы на чтении; ротация идемпотентна (index пишется до удаления; sweep удаляет только байт-идентичный оригинал по `source_md5`).
16. **REST write-поверхность — ровно два endpoint-а** (log append, alarm ack) by design; source control, setpoint-ы, OFF-пути, калибровка и lifecycle эксперимента через REST недостижимы.
17. **REP trust-model** — unauthenticated loopback REP by-design для single-operator lab (D7.2 accepted); LAN-доступ только через SSH-туннель, никогда bind 0.0.0.0.
18. **TSP watchdog — operator-selected mode**, driver default `off`
    байт-идентичен прежнему поведению; v3 — только неавтономный late-pet check.
    `required` отказывает при autonomous=0; независимого host-death бэкстопа в
    SMU нет.
19. **Ступени safety-регуляции** — SafetyManager (host, единственный авторитет source on/off), interlock-engine (пороги, делегирует действия), опциональный TSP late-pet check. Независимый host-death final element пока не реализован и блокирует Phase C.

---

## Команды

```bash
conda env create --file environment.yml
conda activate cryodaq
pip install -r requirements-lock.txt
pip install -e . --no-deps
pip check
cryodaq                        # operator launcher
cryodaq-engine --mock          # mock engine
cryodaq-gui                    # GUI only (нуждается в engine на ZMQ)
uvicorn cryodaq.web.server:app --host 127.0.0.1 --port 8080   # loopback-only
cryodaq-cooldown build --data cooldown_v5/ --output model/
cryodaq-replay-curve ...       # extract/transform reference curve for replay
pytest                         # current suite; counts above are the v0.64.1 release snapshot
pytest tests/ --cov=src/cryodaq --cov-report=term
ruff check src/ tests/         # zero errors (CI lint-gate зелёный)
ruff format src/ tests/
```

---

## Верификация

Каждый релиз проходит собственный проход плюс независимые ревью по осям
(safety-ядро, asyncio, storage-целостность, config-когерентность). Найденные
дефекты закрываются с RED→GREEN-пинами: тест, который падал на старом коде,
идёт вместе с фиксом. Полный сьют (`pytest -q`, ~10–15 мин) прогоняется на
initial block commit; amend-фиксы прогоняют таргетные тесты + `ruff check`
затронутых файлов (регрессия ловится на следующем initial commit).
