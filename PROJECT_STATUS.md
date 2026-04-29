# CryoDAQ — PROJECT_STATUS

**Дата:** 2026-05-01 *(обновлено post-v0.44.0 — parallel work session)*
**Ветка:** master
**Последний commit:** `880c6e6` (`docs(readme): restore Russian-dominant style, update to v0.44.0`)
**Тесты:** ~2 019 passed (baseline 1 970 + 49 new: F26+F17+F13)
**Фронтир:** v0.44.0 shipped. F26+F17+F13 ✅ DONE. Open: F28 ArchiveReader engine replay (XS), F27 chamber photos (L, spec ready), F19 LOW polish, Lab Ubuntu PC verification.

---

## Масштаб проекта

| Метрика | Значение |
|---|---|
| Python файлы (`src/cryodaq/`) | **145** |
| Строки кода (`src/cryodaq/`) | **~48 800** |
| Тестовые файлы (`tests/`) | **208** |
| Строки тестов (`tests/`) | **~39 500** |
| Тесты | **~2 019 passed** (1 970 + 49 new: F26+6, F17+16, F13+19) |
| Coverage (full suite) | stale — re-run pending |
| Design System | **v1.0.1**, 67 canonical .md файлов, 139 токенов |
| Версия пакета | **0.44.0** |
| Python | 3.12+ (dev: 3.14.3) |

Источник актуального репо-инвентаря: этот документ, обновляется при каждом релизе.

Per-subsystem implementation details: see vault notes at `~/Vault/CryoDAQ/10 Subsystems/`.
`DOC_REALITY_MAP.md` retired 2026-04-30 (moved to `docs/handoffs-archive/2026-04/`).

---

## Физическая установка

| Прибор | Интерфейс | Каналы | Драйвер |
|---|---|---|---|
| LakeShore 218S (x3) | GPIB | 24 температурных | `lakeshore_218s.py` |
| Keithley 2604B | USB-TMC | smua + smub | `keithley_2604b.py` |
| Thyracont VSP63D | RS-232 | 1 давление | `thyracont_vsp63d.py` |

### Аппаратные / рантайм инварианты

1. **SAFE_OFF** — состояние по умолчанию. Source ON = непрерывное доказательство здоровья.
2. **Persistence-first:** `SQLiteWriter.write_immediate()` → `DataBroker` → `SafetyBroker`.
3. **SafetyState FSM:** 6 состояний — `SAFE_OFF → READY → RUN_PERMITTED → RUNNING → FAULT_LATCHED → MANUAL_RECOVERY → READY`.
4. **Fail-on-silence:** stale data → FAULT (только в RUNNING; вне RUNNING блокирует readiness через preconditions).
5. **Rate limit:** `dT/dt > 5 K/мин` → FAULT (конфигурируемый default в `safety.yaml`, не жёсткий инвариант).
6. **Keithley connect** forces OUTPUT_OFF на обоих SMU (best-effort).
7. **Keithley disconnect** вызывает `emergency_off()` первым.
8. **No blocking I/O** на engine event loop (исключение: `reporting/generator.py` sync `subprocess.run` для LibreOffice).
9. **No numpy/scipy** в `drivers/core` (исключение: `core/sensor_diagnostics.py` — MAD/корреляция).

### Инварианты добавленные Phase 2d (активны)

10. **OVERRANGE/UNDERRANGE** persist с `status` (`±inf` валидные REAL в SQLite). SENSOR_ERROR/TIMEOUT (NaN) отфильтровываются.
11. **Cancellation shielding** на `_fault()` post-fault paths: `emergency_off`, `fault_log_callback` (before publish), `_ensure_output_off` в `_safe_off`.
12. **Fail-closed config:** `safety.yaml`, `alarms_v3.yaml`, `interlocks.yaml`, `housekeeping.yaml`, `channels.yaml` → subsystem-specific `ConfigError` → engine exit code 2 (без auto-restart).
13. **Atomic file writes** для experiment sidecars и calibration index/curve через `core/atomic_write`.
14. **WAL mode verification:** raises `RuntimeError` если `PRAGMA journal_mode=WAL` вернул не `'wal'`.
15. **Calibration KRDG+SRDG** persist в одной транзакции per poll cycle. State mutation deferred to `on_srdg_persisted`.
16. **Scheduler.stop()** — graceful drain (configurable via `safety.yaml scheduler_drain_timeout_s`, default 5s) перед forced cancel.
17. **_fault() ordering:** post-mortem log callback BEFORE optional broker publish (Jules R2 fix).
18. **_fault() re-entry guard** (добавлен 2026-04-17): ранний `return` если `state == FAULT_LATCHED`, предотвращает overwrite `_fault_reason` + duplicate events / emergency_off при параллельных вызовах.

### Инварианты добавленные Phase 2e (v0.42.0–v0.43.0)

19. **_SLOW_COMMANDS expansion (HF2, v0.42.0):** `keithley_emergency_off` и `keithley_stop` добавлены в `_SLOW_COMMANDS` frozenset в `zmq_bridge.py`. Safety commands используют `HANDLER_TIMEOUT_SLOW_S` (30 s), не fast 2 s envelope.
20. **Severity upgrade in-place (F22, v0.43.0):** `AlarmStateManager.publish_diagnostic_alarm()` upgrades WARNING→CRITICAL in-place на том же `alarm_id`. Мутация `AlarmEvent.level` безопасна (frozen=False intentional); история записывает `SEVERITY_UPGRADED` event.
21. **RateEstimator measurement timestamp (F23, v0.43.0):** `SafetyManager._collect_loop` использует `reading.timestamp.timestamp()` вместо `time.monotonic()` для rate estimator input. Dequeue time искажает computed rate под queue backlog.
22. **SQLite WAL startup gate (F25, v0.43.0):** `_check_sqlite_version()` raises `RuntimeError` на SQLite версиях в `[3.7.0, 3.51.3)` (WAL-reset corruption bug). Bypass: `CRYODAQ_ALLOW_BROKEN_SQLITE=1` с warning log.

---

## Архитектура

```
Instruments → Scheduler → SQLiteWriter → DataBroker → ZMQ → GUI (PySide6)
                                       → SafetyBroker → SafetyManager
                                       → CalibrationAcquisition
```

- **Engine** (headless asyncio): drivers, scheduler, persistence, safety, alarms, interlocks, plugins
- **GUI** (PySide6): `MainWindowV2` shell + dashboard (Phase III complete v0.40.0; все 5 dashboard zones активны) + legacy v1 widgets (permanent fallback; migration plan B.7 retired)
- **Web** (FastAPI, опционально): monitoring dashboard на `:8080`
- **IPC:** ZeroMQ PUB/SUB `:5555` (data, msgpack) + REP/REQ `:5556` (commands, JSON)

Актуальный module index — `CLAUDE.md ### Индекс модулей` (rebuilt 2026-04-17 под Phase I.1).

---

## История исправлений

### Phase I.1 + Design System v1.0.1 — COMPLETE (2026-04-15 … 2026-04-17)

Крупный блок работы между Phase 2d и Phase II. Идёт вне schedule формального Phase 2e.

**Design System v1.0.1 (67 canonical .md, 139 токенов в `theme.py`).** Полная переработка дизайн-системы после Vladimir visual review: foundation tokens + 79 enforcement rules + 14 generic components + 9 CryoDAQ domain primitives + 9 cross-surface patterns + 5 accessibility docs + 6 governance docs. Главные commit-ключи:

- `a48706f` — deploy v1.0.0 (66 файлов, 79 правил, 126 токенов)
- `7a1b206`..`548269c` — serial batches fix pass (contrast matrix, 8-col canonical, governance sync, shortcuts alignment, мбар, PanelCard/OVERLAY_MAX_WIDTH)
- `8d37c7f` — implementation-status callouts на shipped widgets
- `1c61268` — CRITICAL domain cleanup (Latin T→Cyrillic Т в правилах; Latin `mbar`→`мбар`); invalid Python blocks; v1.0.0→v1.0.1 metadata; ghost token refs qualified; Ctrl+W в canonical shortcut registry

**Phase I.1 shell primitives.** Новый shell `MainWindowV2` (TopWatchBar + ToolRail + BottomStatusBar + overlay container), overlay DS primitives (ModalCard, BentoGrid, DrillDownBreadcrumb). Shell замещает tab-based `MainWindow`; v1 widgets продолжают работу под легаси-ключом до Block B.7.

**CLAUDE.md module index rebuild (`8840922`, 2026-04-17).** Полная инвентаризация GUI под Phase I.1: Shell / Overlays / Dashboard / Theming+IPC / Legacy sub-groups; добавлены 20+ ранее неучтённых модулей; canonical mnemonic scheme per AD-002 (`Ctrl+L/E/A/K/M/R/C/D`) задокументирована на `main_window_v2`; legacy `main_window.py` хранит transitional `Ctrl+1-9`.

**A1 safety audit (`eb267c4`, 2026-04-17).** Latin Т12 исправлен в `config/interlocks.yaml` (description + два поясняющих комментария; сам `channel_pattern` был исправлен ранее в `9feaf3e`). `_fault()` получил early-return guard против concurrent re-entries. XSS в `web/server.py`, fail-closed в `load_config()`, stuck RUN_PERMITTED — всё уже закрыто, отмечено NOT REPRODUCIBLE.

**Ruff lint cleanup (`d8ec668`).** 587 lint-ошибок исправлено `ruff check --fix --unsafe-fixes` + manual cleanup (232 файла изменено). CI зелёный.

**CI dependency fix (`1e824a7`).** `.github/workflows/main.yml` теперь ставит `.[dev,web]`, чтобы FastAPI / starlette / httpx тесты не скипались.

### Phase II Group 1 — в процессе (2026-04-16 … 2026-04-18)

Пять Phase II блоков приземлились на master в течение второй половины апреля. Полная хронология — `docs/phase-ui-1/phase_ui_v2_roadmap.md` Decision log.

- **B.5.x PhaseAwareWidget** (`468b964`, `a514b69`) — experiment phase stepper + centralized plot styling. Contributes to II.9 partial.
- **B.6 ExperimentCard dashboard tile** (`8b3a453`) — dashboard composition, no direct II.X mapping.
- **B.7 Keithley v2** (`920aa97`) — mode-based dual-channel overlay at `shell/overlays/keithley_panel.py`. Functional regression vs v1 (no V/I/R/P plots — v2 has 0 pyqtgraph refs, v1 had 4 — no P-target control, no A+B actions, no debounced spin controls, no K4 custom-command popup). Documented in `docs/legacy-inventory/keithley.md`. Maps to II.6 PARTIAL; scope to be reopened as a second block.
- **B.8 AnalyticsPanel → AnalyticsView rev 2** (`9a089f9` → `860ecf3`) — primary-view QWidget at `shell/views/analytics_view.py` with plot-dominant layout. Architecturally corrected from rev 1 ModalCard overlay. Bypasses Phase I.2/I.3 primitives deliberately. Maps to II.1 COMPLETE. Follow-ups: actual-trajectory publisher, R_thermal publisher, VacuumTrendPanel DS alignment (non-blocking).
- **B.8.0.1 / B.8.0.2 ExperimentOverlay polish** (`1850482`, `2d6edc7`, `b0b460b`, `19993ce`) — full phase names, conditional nav buttons, × removed for primary-view semantics, regression tests. Functional parity preserved; visual primitives-based rebuild deferred. Maps to II.9 PARTIAL.

**Phase II block status map** (canonical in roadmap):

| Block | Status |
|---|---|
| II.1 AnalyticsView | ✅ COMPLETE (`860ecf3`) |
| II.2 ArchiveOverlay | ✅ COMPLETE (`e4a60f3` — overlay + K6 bulk export migration + refresh in-flight guard after Codex amend cycle) |
| II.3 OperatorLog | ✅ COMPLETE (`9676acc`) |
| II.4 AlarmOverlay | ⚠️ PARTIAL (badge routing only) |
| II.5 ConductivityOverlay | ⬜ NOT STARTED (next) |
| II.6 KeithleyOverlay | ✅ COMPLETE (`96adf5a` — power-control rewrite + host integration) |
| II.7 CalibrationOverlay | ⬜ NOT STARTED |
| II.8 Instruments+SensorDiag | ⬜ NOT STARTED |
| II.9 ExperimentOverlay v3 | ⚠️ PARTIAL (functional; visual pending) |

**Phase I status** (revised against actual `_design_system/` contents): I.1 COMPLETE; I.2 NOT STARTED (deliberately bypassed for II.1 AnalyticsView); I.3 PARTIAL (widgets exist under `dashboard/phase_content/` but not extracted into `_design_system/`, no StatusBadge / ZmqWorkerField); I.4 PARTIAL (showcase covers only Phase I.1 primitives).

### Runtime theme switcher — shipped 2026-04-18

Infrastructure landing outside the original roadmap. Six bundled YAML theme packs at `config/themes/`: `default_cool`, `warm_stone`, `anthropic_mono`, `ochre_bloom`, `taupe_quiet`, `rose_dusk`. Runtime theme loader at `src/cryodaq/gui/_theme_loader.py` — `theme.py` now reads tokens from YAML packs. Settings → Тема menu with `os.execv` restart pattern. Status palette (STATUS_OK, WARNING, CAUTION, FAULT, INFO, STALE, COLD_HIGHLIGHT) locked across all packs. Legacy hardcoded theme overrides stripped from 9 `apply_panel_frame` callsites.

Commit chain: `ecd447a` (YAML reader) → `e52b17b` (strip hardcoded overrides) → `9ac307e` (ship 5 additional packs) → `77ffc93` (Settings → Тема menu) → `903553a` (operator manual + CHANGELOG).

Palette tuning follow-ups tracked in `HANDOFF_THEME_PALETTES.md` — not blocking.

### IPC/REP hardening — shipped 2026-04-18

Architectural hardening of the engine ↔ GUI command plane after a production wedge revealed the `ZMQCommandServer` REP task crashing silently while the engine subprocess's `stderr=DEVNULL` swallowed the evidence. Ten commits; two Codex review rounds; final verdict PASS at `27dfecb`.

Commits: `5299aa6`, `f5b0f22`, `a38e2fa`, `913b9b3`, `2b1370b`, `abfdf44`, `81e2daa`, `3a16c54`, `ba20f84`, `27dfecb`.

Mechanisms added:

1. Bridge subprocess split — SUB drain + CMD forward on separate owner threads.
2. Data-flow watchdog independent of heartbeat (stall detection works even when PUB is alive).
3. Bridge sockets moved to owner threads (prevents cross-thread ZMQ calls).
4. `log_get` routed to a dedicated read executor (long reads don't block REP).
5. Transport disconnect recovery bounded (no unbounded cleanup).
6. `ZMQCommandServer` task supervision — `add_done_callback` detects unexpected exit and spawns a fresh serve loop. Reentrancy-safe.
7. Per-handler 2.0s timeout envelope. `log_get` and `experiment_status` get 1.5s inner wrappers for faster client feedback.
8. Inner `TimeoutError` messages preserved in the envelope (not swallowed by the outer catch).
9. Engine subprocess stderr persisted to `logs/engine.stderr.log` via `RotatingFileHandler` (50MB × 3 backups), with handler lifecycle that survives engine restarts on Windows.
10. Test isolation for stale reply consumers.

**Residual risk** documented in-code at `engine.py:1328`: `asyncio.wait_for(asyncio.to_thread(...))` cancels the await but not the worker thread. REP is protected by the outer envelope; the inner wrapper gives faster client feedback only.

### Phase 2d — COMPLETE (до 2026-04-13)

14 commits, +61 tests (829 → 890), zero regressions. Triple-reviewer pipeline (CC tactical + Codex second-opinion + Jules architectural) валидирован на Safety, Persistence и Config Fail-Closed subsystems.

Детальная хронология commit'ов Phase 2d и темы (Safety hardening / Persistence integrity / Operational polish) — см. `docs/audits/2026-04-09/MASTER_TRIAGE.md` и retro-анализ в `docs/changelog/archive/RETRO_ANALYSIS_V3.md` (canonical). Полная таблица 14 commit'ов вынесена в архив вместе с audit-докладами.

---

## В работе

### Недавние релизы (v0.34.0 → v0.42.0)

| Версия | Дата | Highlights |
|---|---|---|
| v0.34.0 | 2026-04-27 (retroactive) | F1 Parquet, F2 Debug mode, F6 Auto-report, F11 Shift handover |
| v0.35.0–v0.39.0 | 2026-04-27 (retroactive) | B1 ZMQ idle-death fix chain, IV.6/7 experiments, B1 RESOLVED (H5 fix) |
| v0.40.0 | 2026-04-29 | F3 Analytics widgets (W1–W4) + F4 lazy-open snapshot replay |
| v0.41.0 | 2026-04-29 | F10 sensor diagnostics → alarm integration + 6 vault subsystem notes |
| v0.42.0 | 2026-04-29 | HF1 update_target docstring + HF2 _SLOW_COMMANDS safety expansion |

Full history: `CHANGELOG.md`. Tags: `v0.34.0`..`v0.42.0` on master.

### Открытые F-задачи (из ROADMAP.md, 2026-04-30)

| ID | Название | Статус | Приоритет |
|---|---|---|---|
| F19 | experiment_summary enriched content (W3 sub-items) | ⬜ NOT STARTED | S–M |
| F20 | Diagnostic alarm notification polish (aggregation + cooldown) | ⬜ NOT STARTED | S |
| F21 | Alarm hysteresis deadband (`_check_hysteresis_cleared` stub) | ⬜ NOT STARTED | S |
| F22 | F10 escalation severity fix (shared alarm_id blocks critical) | ⬜ NOT STARTED | S |
| F23 | RateEstimator measurement timestamp (use reading.timestamp) | ⬜ NOT STARTED | S |
| F24 | Interlock acknowledge ZMQ command | ⬜ NOT STARTED | S |
| F25 | SQLite WAL corruption startup gate (warning → hard fail) | ⬜ NOT STARTED | S |
| F5 | Engine events → Hermes webhook | ⬜ BLOCKED (Hermes service) | M |
| F7 | Web API readings query extension | ⬜ NOT STARTED | L |
| F8 | Cooldown ML prediction upgrade | 🔬 RESEARCH | L |
| F9 | TIM thermal conductivity auto-report | 🔬 RESEARCH | M |
| F15 | Linux AppImage / .deb | ⬜ BLOCKED (packaging) | L |
| F17 | SQLite → Parquet cold-storage rotation | ⬜ NOT STARTED (F17 spec drafted) | M |

Source of truth: `ROADMAP.md` (updated 2026-04-28).

### Phase II UI rebuild — mixed status (2026-04-16 … 2026-04-19)

*Block-level statuses below were last verified 2026-04-19. Phase II work may have progressed — see `docs/phase-ui-1/phase_ui_v2_roadmap.md` for authoritative block status.*

**Phase II UI rebuild — mixed status (2026-04-16 … 2026-04-19).**

Block-level status map canonicalized in `docs/phase-ui-1/phase_ui_v2_roadmap.md`. Short version:

- ✅ II.1 AnalyticsView COMPLETE (`860ecf3`, primary-view QWidget)
- ✅ II.2 ArchiveOverlay COMPLETE (`e4a60f3`, K6 bulk export migration + three Codex amend cycles)
- ✅ II.3 OperatorLog COMPLETE (`9676acc`, timeline + filters + Host Integration Contract)
- ✅ II.6 KeithleyOverlay COMPLETE (`96adf5a`, power-control rewrite + host wiring)
- ⚠️ II.4 AlarmOverlay PARTIAL (badge routing only)
- ⚠️ II.9 ExperimentOverlay v3 PARTIAL (functional; visual rebuild pending)
- ⬜ II.5 ConductivityOverlay — next block
- ⬜ II.7, II.8 NOT STARTED

### Host Integration Contract — pattern codified (2026-04-19)

Codex FAIL on II.6 surfaced a systemic risk: overlays with public push setters (`set_connected`, `set_current_experiment`, `set_safety_ready`, etc.) are useless if `MainWindowV2` never calls them — the overlay opens in defaults and stays there. Unit tests on the overlay alone pass while production is broken.

**Contract (mandatory for every overlay with push setters):**

1. `_tick_status()` mirror — for `set_connected(bool)`.
2. `_dispatch_reading()` state sinks — for stateful readings (safety state, experiment status, finalized events).
3. `_ensure_overlay()` replay on lazy open — push cached state the moment the overlay is constructed, so the first paint is correct.

**Tests:** overlay unit tests AND host integration tests (`tests/gui/shell/test_main_window_v2_<block>_wiring.py`) that exercise `MainWindowV2` entry points end-to-end — firing the signal / setting the cache / calling `_ensure_overlay` and asserting overlay state.

Earlier cleanup/quick-win steps that landed between Phase I.1 close-out and Phase II blocks:

- Repo cleanup (`0d4d386`): root audit-артефакты → `docs/audits/2026-04-09/`, superseded markers на старой design system / wireframe / roadmap, RETRO V1/V2 в архив.
- `PROJECT_STATUS.md` refresh (`50ab8c0`, 2026-04-17).
- PhaseStepper ACCENT → STATUS_OK (`05f27d0`, A.4) — active pill теперь `theme.STATUS_OK`; `ACCENT` остаётся только для keyboard focus ring.
- Fira Code + Fira Sans bundle + load — 12 .ttf files под `src/cryodaq/gui/resources/fonts/`, `_load_bundled_fonts()` вызывается из `gui/app.py:131` и `launcher.py:825` до любой widget construction.

**Phase III — not yet started.**

### Open bugs / deferred work

- **Phase 2e parallel track** (перенесено из Phase 2d Block C-2):
  - K.1 — requirements-lock.txt hash verification в build path
  - K.2 — `post_build.py` копирует plugin YAML sidecars
  - J.1 — runtime root вне bundle directory (writable state separation)
  - H.1 — runtime plugin loading trust boundary
  - G.1 — web dashboard auth или loopback-only default
  - G.2 — web history/log query size bounds
  - F.1 — Telegram bot persist `last_update_id`, discard backlog on restart
  - C.1 config-audit — `.local.yaml` merge вместо replace

- **Deferred to Phase 3** (требует hardware validation):
  - B.1.2 — NaN statuses via sentinel or schema migration
  - C.1 — Ubuntu 22.04 SQLite version gating (WAL-reset bug на libsqlite3 < 3.51.3)
  - C.3 — `synchronous=FULL` decision с UPS deployment note

- **Legacy GUI debt**: `src/cryodaq/gui/widgets/*` — 10 522 строк / 22 файла, уходят в Block B.7. Модули `temp_panel.py`, `pressure_panel.py`, `channel_editor.py`, `connection_settings.py` сегодня имеют 0-21% coverage; план — удалить, а не покрывать.

- **GAP документы** (выявлены `docs/REPO_AUDIT_REPORT.md`): user-facing calibration guide, Web API spec (`/status`, `/history`, `/api/status`, `/ws`), instrument setup guide, operator-safety guide (в дополнение к developer-oriented `SAFETY_MANAGER_DEEP_DIVE.md`), TSP Phase-3 status.

Полный audit findings list — `docs/audits/2026-04-09/DEEP_AUDIT_CC_POST_2C.md`, `docs/audits/2026-04-09/MASTER_TRIAGE.md`.

---

## Ключевые решения

1. **Dual-channel Keithley (`smua` + `smub`)** — confirmed operational model.
2. **Persistence-first** — SQLite WAL commit BEFORE any subscriber sees data.
3. **Fail-closed config** — все 5 safety-adjacent configs (safety, alarm, interlock, housekeeping, channels) предотвращают запуск движка при missing / malformed файлах.
4. **Cancellation shielding** — hardware `emergency_off`, post-mortem log emission, `_safe_off` cleanup все `asyncio.shield`'d. Log callback ordered BEFORE optional publish.
5. **`_fault()` re-entry guard** — ранний return если state=`FAULT_LATCHED`, предотвращает race на concurrent вызовы (добавлен 2026-04-17).
6. **OVERRANGE/UNDERRANGE persist** — `±inf` в REAL SQLite. NaN-valued statuses dropped до Phase 3.
7. **Atomic sidecar writes** — experiment metadata, calibration index/curve через `core/atomic_write`.
8. **WAL mode verification** — engine refuses to start, если SQLite не включает WAL.
9. **Graceful scheduler drain** — configurable via `safety.yaml scheduler_drain_timeout_s` (default 5s).
10. **Three-layer review** — CC tactical + Codex second-opinion + Jules architectural; применяется ко всем safety-критичным изменениям.
11. **Calibration state deferral** — `prepare_srdg_readings` считает pending state, `on_srdg_persisted` применяет атомарно после успешной записи.
12. **Design system v1.0.1 canonical** — `docs/design-system/**` — единственный источник правды по UI. `docs/DESIGN_SYSTEM.md` v0.3 помечен SUPERSEDED.
13. **Mnemonic shortcuts canonical per AD-002** — `Ctrl+L/E/A/K/M/R/C/D` для глобальной навигации. `Ctrl+1-9` transitional (rail slot numbering), уходят вместе с legacy `main_window.py`.

---

## Команды

```bash
pip install -e ".[dev,web]"    # runtime + dev + web extras
cryodaq                        # operator launcher
cryodaq-engine --mock          # mock engine
cryodaq-gui                    # GUI only (нуждается в engine на ZMQ)
uvicorn cryodaq.web.server:app --host 0.0.0.0 --port 8080
pytest                         # 1 087 passed, 2 skipped
pytest tests/ --cov=src/cryodaq --cov-report=term   # 66% покрытие
ruff check src/ tests/         # должен быть чистым (zero errors по d8ec668)
ruff format src/ tests/
```

---

## Audit pipeline meta-observations

Phase 2d установил **three-layer review pattern** для safety-критичных изменений. Паттерн актуален и для Phase II:

1. **CC tactical review** — implementer верифицирует каждое изменение против prompt spec, пишет тесты, прогоняет сьют.
2. **Codex second-opinion** — независимый LLM-review committed diff. Ловит line-level семантику (wrong type, wrong API, wrong filter). Примеры Phase 2d: RUN_PERMITTED heartbeat gap (gated on `_active_sources` которая пустая в момент source start); `housekeeping.py` читает `alarms_v3.yaml:interlocks:` секцию, которую CC удалил как "dead config"; NaN vs ±inf IEEE 754 distinction (SQLite treats NaN as NULL).
3. **Jules architectural review** — смотрит fault path целиком через несколько commit'ов. Находит cross-cutting вещи: R1 — `_fault_log_callback` не shielded; R2 — `_fault()` ordering vulnerability (callback после publish = escape path), calibration state mutation до persistence.

**Key insight.** Codex — line-level. Jules — архитектура. Ни один не заменяет другого.

Phase 2d total: 14 commits, 17 Codex reviews, 2 Jules rounds. Каждый review находил реальную проблему. Итеративный паттерн (initial → Codex BLOCKING → fix → re-review → CLEAN) — ожидаемый workflow для safety-critical кода, не exception.
