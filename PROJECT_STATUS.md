# CryoDAQ — PROJECT_STATUS

**Дата:** 2026-07-22 *(release baseline v0.64.1 + active Montana correction campaign)*
**Релизная ветка:** master
**Активная campaign-ветка:** `feat/montana-phase-a` (current committed HEAD `c16cabc` rejected as a candidate; последний published checkpoint `503c8bf`)
**Релизная граница:** tag `v0.64.1`
**Версия пакета:** 0.64.1 (released 2026-07-08)

## Проверяемая таблица программных доказательств

| Объект | Полный SHA | ОС / среда | Проверяемая команда или запись | Результат и граница |
|---|---|---|---|---|
| Выпущенная основа `v0.64.1` | `f5d6434d20dffae62c9f03fbc12f68b03f48351b` (аннотированный tag object проверяется отдельно) | Git-объект; не runtime-гейт | `git rev-parse v0.64.1^{}` и `git show -s v0.64.1` | Фиксирует выпущенный source baseline; не доказывает текущее поведение Montana. |
| Исторический Montana CI checkpoint | `7607bc19eca51e5d76d917be2c7a27a6788ff62f` | GitHub-hosted `windows-latest` + `ubuntu-latest` | `gh run view 29488046377` | Все восемь agents/core/GUI/remaining jobs PASS. Не переносится на более новый SHA и не закрывает ONEDIR/soak/hardware. |
| Последний опубликованный checkpoint | `503c8bf8d884654256ede4f08a9e44ab7b382242` | GitHub-hosted `windows-latest` + `ubuntu-latest` | `gh run view 29662599972 --json headSha,status,conclusion,jobs,url` | PASS: восемь matrix jobs завершены успешно; safe-SQLite во всех jobs, lint/format/lock в remaining jobs. Hosted Windows ONEDIR evidence для этого SHA отсутствует. Не включает текущий незапечатанный worktree. |
| Текущий final candidate | **pending после интеграции** | Windows, native-ext4 WSL/Linux, Windows ONEDIR, затем hosted CI | Сначала `git rev-parse HEAD` + clean tree; затем команды из `docs/lab_verification_checklist.md` и новый `gh run view <run-id>` | Нельзя заявлять PASS, пока один и тот же frozen SHA не пройдёт все применимые гейты. |

**Final-candidate evidence:** pending. Две изолированные implementation lanes
остаются незапечатанными: primary `feat/montana-phase-a` имеет rejected HEAD
`c16cabc`, а CLI correction `review/montana-cli-corrections-staging` имеет
rejected proposal HEAD `97cff82c` / tree `f03e3224`; primary остаётся широко
dirty, а CLI worktree содержит active uncommitted product/test corrections plus
13 preserved dirty/untracked `docs/**` paths вне implementation ownership. Ни
один объект не является approvable proposal. Raw CLI commit `f3e28a7`
не является допустимым integration parent; только независимо проверенное
reconstructed content может перейти в Phase A. Ни один текущий dirty blob не
покрыт run `29662599972`, и PR ещё не открыт.

До code-complete остаются: retained ZMQ mutation authority/quarantine и stop
settlement; full 128-bit globally reserved experiment identity и обязательное
mutation/recording/replay binding; exact verified-OFF launcher HOLD; USBTMC /
Keithley incomplete-close settlement; sealed safety configuration и production
physical-alarm binding; durable hot+cold operator-log idempotency; удаление
Telegram/RAG/assistant mutation and second-writer authority; exact GUI
lifecycle/freshness/incarnation cuts; QThread settlement; protocol,
architecture, report и SVG reconciliation. После двух proposal freezes reviewer
сначала отдельно проверяет CLI и Phase A objects; один integration owner затем
переносит только approved CLI implementation content в Phase A, и все combined
gates продолжаются в одной ветке.
Exact-candidate evidence tooling также open: Windows smoke исполняет runtime
copy, но hashes/uploads исходный dist без equality receipt; PR head и synthetic
merge SHA не различаются внутри evidence; host checkout участвует в одном
frozen boundary; nightly использует legacy unsealed soak; editable CI не
доказывает wheel/sdist completeness.
Current full-tree `git diff --check` passed at 2026-07-22 11:29 +03:00 after the
RAG test EOF defect was corrected; CRLF normalization warnings remain. This is
moving-tree hygiene evidence only and must be repeated on the frozen proposal.

**Текущий review state:** обе implementation lanes имеют disposition
**REJECT / CORRECTIONS REQUIRED**. Независимое воспроизведение доказало, что
текущий ZMQ server после timed-out mutation допускает вторую mutation и может
вернуться из `stop()`, пока первая mutation ещё способна commit; один текущий
test прямо сохраняет это небезопасное поведение. Experiment IDs остаются
12-hex, не globally reserved и не path-contained; launcher может
`terminate()/kill()` без exact OFF/exit receipt; Telegram сохраняет generic
mutation capability; production operator-log dedup остаётся process-memory-only,
а cold rotation удаляет request identity. CLI moving tree всё ещё сохраняет
false READY, dead strict physical-alarm production wiring, incomplete transport
and QThread settlement, missing Dashboard API и небезопасный annunciation ack.
SafetyManager child-death/HOLD/retry paths также могут запускать overlapping
global-OFF owners; один текущий test требует третью OFF попытку при всё ещё
blocked второй. Durable child receipt failure ошибочно считается settled, а
restart health может быть восстановлен только по elapsed time.
Recording lifecycle сохраняет acquisition/persistence epochs после replacement,
поэтому A-era receipt может ошибочно отметить experiment B как RECORDING;
replay fingerprint остаётся caller decoration и replay metadata делит live
namespace. Conductivity auto-advance также активен вопреки открытому hazard
decision: до frozen PAUSE/HOLD-versus-verified-STOP/OFF policy он должен быть
unavailable, а safety-critical freshness loss всегда ведёт к FAULT/OFF.

Persistence shutdown has a P0 ordering defect: the engine drains potentially
unbounded operator-log/SQLite owners before starting verified global OFF, so a
hung observational write can prevent OFF forever. Cancellation also abandons the
SQLite receipt path while the executor transaction continues: a reproduced run
emitted persistence/acquisition stopped with zero rows, then committed one late
row with zero receipts. OFF must start independently, persistence owners remain
retained in visible HOLD, and no stopped receipt may precede terminal settlement.

New P0 review evidence: alarm acknowledgement can commit state and then lose its
only event when the fast REP timeout cancels publication; command-server stop
does not settle retained/uncertain mutation owners. REST currently returns HTTP
200 for stale or unknown writes, and GUI transport exceptions erase delivery,
commit, retry-safety, action, and request identity. Experiment mutations still
accept an implicit current experiment and their receipts lack incarnation,
nonce, payload fingerprint, and durable retry lookup. These require retained
owners, durable outbox/receipts, exact HTTP outcome mapping, structured GUI
unknown-state propagation, and mandatory experiment/incarnation binding.

The moving CLI correction is not yet acceptable: its GUI-generated bridge UUID
is stamped onto data after receipt from a reused queue, so late old-producer data
can be relabelled as current disk evidence. Its cancellation/shutdown paths also
erase dispatched/unknown command identity and leave several QThread owners on
unchecked bounded waits. Trusted producer identity must cross the wire unchanged,
queues must be incarnation-fresh, and close must prove every owner settled.
The new Dashboard API removes one construction error, but MainWindow still
derives its mutation-enabling `connected` flag from arbitrary recent measurement
traffic. Data flow is not command/engine/experiment authority; production must
use a fresh exact handshake and per-action lifecycle preconditions.
Pinned staging tests remain red: snapshot/UI 306/46, USBTMC/Keithley 45/23,
physical/support 88/6. Cached READY has no age/liveness, ingress validates only
batch type/revision before taking the newest mixed member, Keithley accepts bare
zero as OFF proof, and USBTMC cancellation can detach a live close thread.
Annunciation still accepts `event_emitted=False`, tooltip identity is AutoText,
and strict physical-alarm loading is not used by production.

The current RAG correction is also incomplete. Assistant helper tests are green,
but the production sink registry still constructs `RAGIndexSink`, experiment
terminal dispatch still reaches `build_index`, and the GUI still presents and
tests running/complete live rebuild states. Live finalization must have no RAG
mutation sink; rebuild remains offline CLI-only.
The affected RAG Ruff lint gate passes, but Ruff formatting is red for
`assistant_main.py` and `sinks/registry.py`. A periodic-PNG test also widens a
poll loop from 100 to 5000 iterations without changing production settlement;
that is diagnostic evidence, not closure.

Focused counts `23 passed`, `83 passed`, `460 passed`, `205 passed` и
другие moving-tree результаты являются только correction evidence: они не
закрывают перечисленные контрпримеры и не получают exact-candidate credit.
Воспроизводимый docs-freshness gate: `17 passed / 3 failed`; tray contract,
SVG parity и report metrics остаются красными. Experiment outcome wording gate
теперь green отдельно, но не закрывает остальные candidate-finalization items.
**Final review evidence:** pending. Для одного замороженного candidate нужен
детерминированный object/range ledger: все текущие и удалённые текстовые строки,
binary/symlink/gitlink, mode, rename и LFS pointer/resolved artifact получают
точные blob identities и отдельные reviewer dispositions. В текущей campaign
обязателен полный task-designated primary review; evidence дополнительных
внешних reviewers маркируется раздельно и не подменяет обязательного reviewer.
Missing, truncated,
quota-limited, unavailable и stale-hash evidence дают нулевое покрытие; любое
изменение снова открывает затронутый объект. Обязательны два disposition:
полный task-designated fresh-context review и отдельная coordinator re-review;
evidence дополнительных внешних reviewers маркируется раздельно и не
подменяет ни один обязательный disposition. Даже 100% такого ledger не заменяет
отдельные architecture, threat-model, operator, safety, concurrency и test
quality audits.

**Фронтир:** Release train v0.58.0 → v0.64.0 отгружен 2026-07-07/08.
После релиза активна software-side pre-lab campaign: H3/H4 runtime/ONEDIR,
F35 ASC extension contract и F36 operator readiness из `ROADMAP.md`; F37 fleet/
projector scale остаётся deferred.
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
| Python | 3.12+ package floor; v0.64.1 CI pinned 3.13 |

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

Целевая физическая семантика: Т11 — азотная плита, Т12 — вторая ступень
GM-cooler-а, и только они являются SafetyManager `critical_channels` без
отдельного hazard review. Это пока **open gate**, а не доказанный current truth:
`alarms_v3.yaml` и `safety.yaml` содержат конфликтующие/переставленные привязки.
До atomic exact-descriptor binding receipt нельзя давать RUN authority или
считать UI/report/alarm mapping согласованным.

### Аппаратные / рантайм инварианты

1. **SAFE_OFF** — состояние по умолчанию. Source ON = непрерывное доказательство здоровья.
2. **Persistence-first:** `SQLiteWriter.write_immediate()` → `DataBroker` → `SafetyBroker`.
3. **SafetyState FSM:** 6 состояний — `SAFE_OFF → READY → RUN_PERMITTED → RUNNING → FAULT_LATCHED → MANUAL_RECOVERY → READY`.
4. **Fail-on-silence:** stale data → FAULT (только в RUNNING; вне RUNNING блокирует readiness через preconditions).
5. **Rate limit:** `dT/dt > 5 K/мин` → FAULT (конфигурируемый default в `safety.yaml`, не жёсткий инвариант).
6. **Keithley connect** отправляет OFF на оба SMU и требует nonce-bound verified
   readback каждого канала; отсутствующее, malformed или ON-подтверждение
   fail-closed блокирует connect/RUN authority.
7. **Keithley disconnect** вызывает `emergency_off()` первым.
8. **No blocking I/O** на engine event loop: production engine/periodic report
   generation запускает synchronous `reporting/generator.py` через bounded
   `ReportProcessRunner` child. Сам generator остаётся synchronous public API;
   direct callers обязаны держать его вне event loop.
9. **No numpy/scipy** в `drivers/core` (исключение: `core/sensor_diagnostics.py` — MAD/корреляция).
10. **OVERRANGE/UNDERRANGE** persist с `status`; non-finite (SENSOR_ERROR/TIMEOUT) обрабатываются NaN-доктриной (см. инвариант 24).
11. **Cancellation shielding** на `_fault()` post-fault paths: `emergency_off`, `fault_log_callback` (before publish), `_ensure_output_off` в `_safe_off`.
12. **Config boundary:** descriptor selection и часть subsystem configuration
    fail closed через `ConfigError`/`ChannelDescriptorStorageError` и engine exit
    code 2. Полный safety YAML gate остаётся открытым:
    `SafetyManager.__init__()` создаёт default `SafetyConfig`, `start()` не
    требует sealed configuration receipt, а `load_config()` использует
    permissive bool/float/int coercions и не является полностью transactional.
    Production engine всё же вызывает `load_config()` до `start()`.
    Descriptor selection связан с
    instrument authority: `instruments.local.yaml` требует complete
    `channel_descriptors.local.yaml`; base `instruments.yaml` использует base
    `channel_descriptors.yaml`. Local descriptor-файл заменяет base whole-file,
    а не merge'ится с ним.
13. **Atomic file writes** для experiment sidecars и calibration index/curve через `core/atomic_write`.
14. **WAL mode verification:** engine останавливается с `RuntimeError`, если SQLite `journal_mode=WAL` не подтвердился.
15. **Calibration KRDG+SRDG** persist в одной транзакции per poll cycle. State mutation deferred to `on_srdg_persisted`.
16. **Scheduler.stop()** — graceful drain (configurable via `safety.yaml scheduler_drain_timeout_s`, default 5s) перед forced cancel.
17. **_fault() ordering:** post-mortem log callback BEFORE optional broker publish.
18. **_fault() re-entry guard:** ранний `return` если `state == FAULT_LATCHED`, предотвращает overwrite `_fault_reason` + duplicate events / emergency_off при параллельных вызовах.
19. **_SLOW_COMMANDS:** `keithley_emergency_off` / `keithley_stop` используют `HANDLER_TIMEOUT_SLOW_S` (30 s), не fast 2 s envelope (`zmq_bridge.py`).
20. **Severity upgrade in-place:** `AlarmStateManager.publish_diagnostic_alarm()` upgrades WARNING→CRITICAL на том же `alarm_id`; история пишет `SEVERITY_UPGRADED`.
21. **RateEstimator measurement timestamp:** rate estimator берёт `reading.timestamp.timestamp()`, не `time.monotonic()`.
22. **SQLite WAL startup gate:** `_check_sqlite_version()` raises `RuntimeError`
    на версиях `[3.7.0, 3.51.3)`, кроме backport-safe 3.44.6 и 3.50.7.

### Инварианты релизного поезда v0.57–v0.64

23. **Verified-off fail-closed (v0.57 / v0.58 / v0.64).** `emergency_off()` возвращает `bool`; неподтверждённый OFF (ошибка записи или readback = «включено») эскалирует в `FAULT_LATCHED`, а не в ложный `SAFE_OFF`. Тот же контракт на `stop_source`, interlock-трипе и `connect()` force-OFF (readback-verified, неудача ставит блокирующее RUN-предусловие).
24. **NaN-доктрина (v0.59).** `Reading.is_usable()` — единый предикат (usable ⟺ `status == OK` и значение finite); `status` дискриминатор на каждом слое. Non-finite пишутся единым finite sentinel (`-8.888e88`, `storage/sentinel.py`); каждый reader декодирует пары `(value, status)` на read-boundary — sentinel или legacy `±inf` не всплывёт числом. Устойчиво non-usable readings на интерлок-каналах эскалируют debounced (≥5 подряд ≥10 s → `on_interlock_dead_channel`, латч только в RUNNING).
25. **Rate-clock robustness (v0.57 / v0.59).** Защита 5 K/мин взводится по временно́му охвату (`min_span_s=30`), не по числу точек. Clock-jump guard: backward-шаг или forward-gap >4× медианного периода чистит буфер и якорится на текущем сэмпле (reset-not-drop, слепота ≤ ~30 s).
26. **SQLite fail-closed runtime (v0.64 + pre-lab hardening).** `environment.yml` фиксирует Python 3.14 и безопасный SQLite 3.53.2 для Windows/Linux; F25 проверяет реально выбранную реализацию и запрещает WAL-reset corruption range, сохраняя только явно проверенные backport-safe 3.44.6/3.50.7. Опциональный `pysqlite3` принимается только если сам проходит тот же гейт; небезопасного bundled fallback больше нет. Все runtime-импортёры берут sqlite3 из шима — одна библиотека на БД.
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
   активирован для POSIX source-mode short profile: registry единолично
   запускает owned execution, проверяет process/artifact/receipt cut, выдаёт и
   поглощает opaque evidence и завершает cleanup. Windows-ветка остаётся
   fail-closed unsupported. Открыты чистый integrated 15-minute run на финальном
   SHA, 12/72-hour duration evidence и реальный Windows ONEDIR.
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
   Specialized calibration/conductivity/analytics/Keithley/pressure/cold-stage/
   MultiLine routing теперь принимает только authoritative descriptors; bare и
   refused readings не получают specialist authority. Открыты Windows
   ONEDIR/frozen evidence и physical reference-hardware evidence; mock TCP не
   закрывает physical/hardware gate.
4. F36: committed foundation включает wire envelope, durable revision
   allocator, typed authority receipts, ordered composer, replay-compatible
   publisher, отдельный snapshot SUB, один GUI-thread Store, pure replay session
   и conservative live adapters. SafetyManager cache + live safety/readiness
   authority доступны и fail-conservative. Один supervised production path
   теперь использует actual loop-owned experiment/acquisition/direct-SQLite
   persistence feeds, один durable revision allocator и sole PUB socket;
   cold/disconnected cuts fail-dark, а stale/ambiguous persistence остаётся
   явно NOT_RECORDING/unavailable без fallback writer. Панорамный dashboard
   теперь является основным home; POD сохранён как дополнительный
   маршрут сводки смены. Оба production launch root удерживают одного
   ingress owner, передают newest coherent cuts в реальный POD и
   завершают ingress до normal shutdown. Выбор темы валидируется и атомарно
   откладывается до следующего обычного запуска без остановки acquisition,
   engine, bridge или ingress. Reviewed
   source-mode 1280x800 POD visual QA собран. Открыты все 12 operator
   scenarios, keyboard/NVDA, DPI/ONEDIR, WSL candidate integration,
   startup/frame/memory/long-session и physical gates; один скриншот их не
   закрывает.

   **Software reconciliation behavior experiment-команд реализовано и покрыто
   focused deterministic regressions в текущем dirty worktree; candidate-level
   gate остаётся open до frozen-SHA review/CI.** REP timeout по-прежнему означает
   **outcome unknown** для клиента, а не rollback: автоматический/слепой retry
   запрещён, сначала нужно повторно запросить authoritative
   `experiment_status`/operator snapshot и сверить durable state. Named
   deterministic gates `timeout-then-late-commit` и `post-commit` остаются
   обязательными для exact candidate. Но один
   retained/shielded owner-task переживает timeout/cancellation waiter'а и
   проходит один reconciliation path для принятой команды; это single-process
   ownership guarantee, а не distributed/external exactly-once. Успешный
   принятый ответ
   содержит `committed: true`, `retry_safe: false` и
   `experiment_command_commit_v1` `commit_receipt`; частичный сбой возвращает
   `committed_reconciliation_failed`, явные `reconciliation_failures` и не
   притворяется rollback. Shutdown сначала закрывает ingress, затем удерживает
   dependent resources до settlement mutation/read/status/operator-log owners;
   deadline только эскалирует событие. Это не закрывает exact-SHA CI,
   real-Windows, frozen-build или physical-lab gates нового candidate.
   **Current reviewer disposition is CORRECTIONS_REQUIRED for both moving
   implementation lanes.** Primary Phase A advanced to local proposal
   `c16cabc363bf9a9dd7eb3148e9c253106f33cfa7`, tree
   `edb806b322e16a90ac4a89c3eac077fdc40bb074`, but that commit is rejected:
   its 32 committed blobs match the manifest while committed
   `assistant_main.py` imports an uncommitted/untracked `context_reader.py`.
   Clean-export collection fails three assistant modules with
   `ModuleNotFoundError`, and zero of 11 checked registered exact
   assistant/integration guard names are present. The earlier `8ff15811`
   proposal remains rejected for the same exact-tree evidence class. Independent
   exact-object storage review also rejects `c16cabc`: scheduler cancellation
   can strand, cross-attribute, or silently evict late commit receipts; cold
   rotation drops operator-log request identity; outbox recovery is not wired
   into production; live keyed admission can exceed its cap; legacy stranded
   rotation can delete unproven operator rows; and production archive export
   omits mandatory experiment identity. The observed 30 scheduler passes and
   101 storage passes plus one skip do not cover those production boundaries.
   The CLI correction lane produced proposal commit
   `97cff82c047f8fb39262c16d2088dd8bf346c13f`, tree
   `f03e3224739eabb938af076c1243fc30bd7fb21b`, parent
   `4024f72cc29fc0780b3d18ccf962f16a44ab92ef`; the reviewer disposition is
   **REJECT / CORRECTIONS REQUIRED**. The commit was created while registered
   exact guards were absent and independently reproduced lifecycle-default,
   shell-authority, reply-consumer-generation, real-QThread, plain-text, and
   disk-freshness blockers remained. Candidate-pinned execution passed 244
   nearby tests while all 24 then-registered CLI guard nodes were absent; exact
   exported affected partitions then failed 10 cases: 2 T11/T12 liveness plus
   8 lifecycle-fixture, replay-ingress, and experiment-binding cases.
   A later CLI correction descendant was observed at
   `870607ffd5776f4235aae1fde10987d803b62f51`, tree
   `fedb481ce874f95b4aae9f17023d60ac9d0acdb9`. Exact-object disposition is
   **REJECT / CORRECTIONS REQUIRED**. Its 27 reported blobs and modes match,
   but a clean export contains only 1 of 45 effective CLI guard nodes by exact
   name; 44 are absent. The reported 179 focused, 603 driver, and 20x84 passes
   do not exercise the registered failure boundaries.
   Lifecycle defaults and disk-incarnation checks appear improved, but locked
   experiment CAS, origin-bound quick-log, caller-visible late ZMQ settlement,
   retained GPIB/Keithley close settlement, recovery quarantine clearing, Qt
  plain-text rendering, and complete real-QThread teardown remain open. Its
  worktree still contains 13 forbidden dirty documentation paths.
   Independent line review additionally found that a new GPIB test explicitly
   blesses a live handle after cancelled connect and relies on a later manual
   disconnect. This is P0 false-green evidence; terminal close settlement must
   remain owned and automatic for the exact handle generation.
   USBTMC also converts a successfully settled handle close into false terminal
   incomplete state when caller cancellation is propagated, and its current
   test explicitly blesses that result. Its 13 residual dirty/untracked `docs/**`
   paths are outside the proposal commit and remain untouched. The current dirty
   primary engine now starts retained
   SafetyManager shutdown before observational persistence drains, shields
   experiment reply owners, requires the expected ID for phase advance, improves
   hot operator-log idempotency, and rejects registered live RAG rebuilding.
   These are provisional uncommitted improvements, not approval. Reproduced P0
   gates still include SQLite commits landing after `persistence_stopped` without
   receipts, ZMQ mutation owners escaping timeout quarantine, overlapping global
   OFF owners, omitted OFF scope becoming `smua`, old subprocess readings being
   relabeled with a new GUI incarnation, Dashboard mutation authority derived
   from arbitrary telemetry, and post-enqueue cancellation losing outcome-
   unknown identity. Real QThread and executor settlement, durable operator-log
   idempotency/outbox ownership, strict Keithley OFF proof, lifecycle freshness,
   full-batch ingress identity, and exact producer incarnation are also open.
   Passing focused counts are diagnostic only until each lane freezes one exact
   commit/tree and the reviewer reruns the affected and broader gates.
   Independent 2026-07-22 audits additionally rejected the live GPIB delta
   despite 10 focused passes: close can lose ownership and return success while
   a close/I/O thread remains live, double-open leaks the first resource, and
   desynchronization admits ordinary writes. Conductivity automatic sweep also
   remains unavailable because arbitrary telemetry can enable it, cached data
   can advance it, commanded power is recorded as measured evidence, and bare
   success is rendered as verified OFF. Experiment/replay remains blocked on
   durable cross-process CAS, full globally reserved identity, commit-time
   experiment/epoch provenance, stale-journal rejection, canonical paths, and
   adapter-computed archive fingerprints. Exact correction gates are maintained
   in `ROADMAP.md`.
   The AI-first governing layer now distinguishes repository-universal,
   product-contract, and Montana campaign-local rules. The reviewer-owned
   `governance/agent_preventions.yaml` currently contains 37 unique open
   runtime/governance prevention records,
   66 separately identified false-green coverage pairs, and 110 declared record
   guard nodes. Structural local parsing
   confirms unique IDs, resolved runtime-to-coverage links, and durable
   product-contract authority. The required implementation-owned validators are
   still absent, 12 referenced guard files do not yet exist, named-node
   collectability and default-CI inclusion remain unproven, and immutable
   red/green evidence is pending. A read-only live registry-to-worktree check on
   2026-07-22 initially found **0 of 59** durable primary-owner nodes and **1 of
   34** durable CLI-owner nodes present by registered file/node name. That
   census incorrectly mixed durable maintenance ownership with Montana's active
   edit authority. The exact campaign override map now yields an effective
   **0 of 57 primary** and **1 of 38 CLI** checkpoint after adding its two
   enforcement nodes. Aggregate focused-pass counts and capsule assertions
   therefore provide no proposal-freeze evidence for either moving lane, but a
   bounded lane is responsible only for its effective edit-owned affected
   closure; the combined/final gates require the union.
   `AGENT-CONTEXT-COMPACTION-001` now defines
   one ignored capsule per long-running role. Capsule presence is transient
   ignored evidence and is therefore checked live rather than counted in this
   tracked status document. Both worker capsules currently fail the live
   contract: CLI uses an unregistered legacy shape with stale green assertions;
   primary binds the wrong governing-set ID, incomplete hashes/owned paths,
  stale inventory, and a wait state contradicted by active edits. They grant no
  continuity until each worker rewrites only its own capsule under the current
  schema and the validator passes. ADR 003 remains
   Revalidation after explicit correction orders reproduced the same failure:
   primary still waited on obsolete governing hashes after rejection, while
   CLI still self-certified `870607ff` through the legacy capsule. Both capsules
   therefore carry zero continuity or freeze authority.
   locally ignored and the Montana contract plus governance schemas/registry are
   untracked; explicit candidate-manifest inclusion is therefore an open
   governance gate, not an assumed Git side effect.
5. Recorded exact-SHA CI checkpoint `29662599972` для `503c8bf`: все восемь
   agents/core/GUI/remaining jobs PASS на Ubuntu и Windows. Safe SQLite
   verification прошла во всех jobs; lint и requirements-lock drift
   checks PASS в обоих remaining jobs. Hosted Windows ONEDIR evidence в этом
   run отсутствует. Каждый новый candidate требует свой exact-SHA eight-job PASS
   и отдельный ONEDIR gate;
   frozen-build, soak-duration, physical-hardware, F35 frozen-packaging и F36
   operator/accessibility/performance/scenario gates остаются открыты.
6. Готовые точные Windows/physical evidence procedures с thresholds,
   abort/rollback и ожидаемыми артефактами.

Отдельно остаются проверки, требующие физического доступа к приборам и
лабораторным ПК — полный turnkey-протокол в
`docs/lab_verification_checklist.md`:

1. **Гейт версии SQLite на лабораторном Ubuntu ПК** — развернуть уже tracked
   `environment.yml`, подтвердить выбранную безопасную версию и отказ запуска
   вне неё; bundled self-heal не считается доказательством.
2. **Верификация H5 / ZMQ idle-death** на текущем лабораторном ПК (регрессионный гейт `diag_zmq_direct_req.py`, 180 s без зависаний).
3. **Runtime-калибровка LakeShore на реальном железе** — per-channel KRDG/SRDG, консервативный откат на KRDG вне диапазона.
4. **Keithley A8a–A8e, не один armed-mode checkbox** — A8a (upload/version/
   explicit non-autonomous contract) и A8b (late-pet stall-recovery) выполняются
   на dummy-нагрузке; A8c (host death без последующей команды), A8d
   (независимые terminal V/I/P + trip time) и A8e (внешний final element +
   common-cause proof) остаются физическими блокерами. Ни один подпункт не
   заменяет другой; Phase C заблокирована до A8c–A8e.
   Перед ними A8-0 на реальном 2604B/Windows USBTMC должен подтвердить строгий
   `*IDN?` identity contract и точный однострочный ASCII reply
   `CRYODAQ_OFF_V1|<32-lowercase-hex-nonce>|0` для свежего nonce и обоих каналов.
   Любое отличие fail-closed; до этого evidence нельзя заявлять restart-durable
   OFF proof.
5. **Windows source-install smoke** — `install.bat` + ярлык + source launcher;
   отдельно требуется настоящий ONEDIR/frozen smoke. Editable install не снимает
   frozen-build gate.

### Известная проблема

- При завершении engine в логе один `ERROR «Unclosed client session»` (aiohttp-сессия не закрывается на shutdown-пути; замечено boot-smoke прогоном mock-engine). Косметика exit-пути — данные и safety не затронуты; фикс в следующем train (см. `CHANGELOG.md [0.64.0]`, Known Issues).

---

## Ключевые решения

1. **Dual-channel Keithley (`smua` + `smub`)** — confirmed operational model.
2. **Persistence-first** — SQLite WAL commit BEFORE any subscriber sees data.
3. **Fail-closed config — частично, gate открыт.** Descriptor/config selection
   закрывается при ряде malformed/missing случаев, но safety configuration ещё
   должна стать exact-typed, transactional, immutable и sealed до startup.
4. **Cancellation shielding** — hardware `emergency_off`, post-mortem log emission, `_safe_off` cleanup все `asyncio.shield`'d. Log callback ordered BEFORE optional publish.
5. **`_fault()` re-entry guard** — ранний return если state=`FAULT_LATCHED`.
6. **NaN-доктрина** — `status` дискриминатор; non-finite persist как единый sentinel, декодируются на read-boundary.
7. **Atomic sidecar writes** — experiment metadata, calibration index/curve через `core/atomic_write`.
8. **WAL mode verification** — engine refuses to start, если SQLite не включает WAL.
9. **Graceful scheduler drain** — configurable via `safety.yaml scheduler_drain_timeout_s`.
10. **Verified-off fail-closed** — неподтверждённый OFF латчит FAULT, а не ложный SAFE_OFF (все три call-site класса CR-2 + connect force-OFF).
11. **Calibration state deferral** — `prepare_srdg_readings` считает pending state, `on_srdg_persisted` применяет атомарно после успешной записи.
12. **Design system v4.0.3 canonical** — `docs/design-system/**` — единственный источник правды по UI в текущей campaign-ветке. Релизный снимок v0.64.1 в таблице выше исторически фиксирует v1.0.1. Значения токенов берутся ТОЛЬКО из `theme.py`.
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
ruff check src/ tests/         # запускать на frozen candidate; текущий dirty tree не сертифицирован
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
