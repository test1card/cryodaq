# CryoDAQ — PROJECT_STATUS

**Дата:** 2026-04-17
**Ветка:** master
**Последний commit:** `0d4d386` (`chore: repo cleanup — move audit artifacts, mark superseded docs`)
**Тесты:** 1 087 passed, 2 skipped (1 089 collected)
**Фронтир:** Phase I.1 shell + Design System v1.0.1 merged; Phase II UI rebuild в процессе (Group 1 open).

---

## Масштаб проекта

| Метрика | Значение |
|---|---|
| Python файлы (`src/cryodaq/`) | **133** |
| Строки кода (`src/cryodaq/`) | **41 397** |
| Тестовые файлы (`tests/`) | **150** |
| Строки тестов (`tests/`) | **24 275** |
| Тесты | **1 087 passed, 2 skipped** (1 089 collected) |
| Coverage (full suite) | **66%** (21 522 stmts, 7 305 miss) |
| Design System | **v1.0.1**, 67 canonical .md файлов, 139 токенов |
| Версия пакета | 0.13.0 |
| Python | 3.12+ (dev: 3.14.3) |

Источник актуального репо-инвентаря: `docs/REPO_AUDIT_REPORT.md` (2026-04-17).

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

---

## Архитектура

```
Instruments → Scheduler → SQLiteWriter → DataBroker → ZMQ → GUI (PySide6)
                                       → SafetyBroker → SafetyManager
                                       → CalibrationAcquisition
```

- **Engine** (headless asyncio): drivers, scheduler, persistence, safety, alarms, interlocks, plugins
- **GUI** (PySide6): `MainWindowV2` shell + dashboard (Phase I.1 / Phase UI-1 v2 через Block B.2) + legacy v1 widgets (в ожидании Block B.7 миграции)
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

### Phase 2d — COMPLETE (до 2026-04-13)

14 commits, +61 tests (829 → 890), zero regressions. Triple-reviewer pipeline (CC tactical + Codex second-opinion + Jules architectural) валидирован на Safety, Persistence и Config Fail-Closed subsystems.

Детальная хронология commit'ов Phase 2d и темы (Safety hardening / Persistence integrity / Operational polish) — см. `docs/audits/2026-04-09/MASTER_TRIAGE.md` и retro-анализ в `docs/changelog/archive/RETRO_ANALYSIS_V3.md` (canonical). Полная таблица 14 commit'ов вынесена в архив вместе с audit-докладами.

---

## В работе

**Phase II UI rebuild — Group 1 OPEN (2026-04-17).**

Cleanup + quick wins:

- ✅ Repo cleanup: root audit-артефакты → `docs/audits/2026-04-09/`, superseded markers на старой design system / wireframe / roadmap, RETRO V1/V2 в архив.
- ✅ `PROJECT_STATUS.md` refresh (этот commit).
- ⏭ PhaseStepper ACCENT → STATUS_OK (A.4).
- ⏭ Fira Code + Fira Sans bundle + load (C.1 / FONT-1).

**Phase II Groups 2–7 — not yet started.**

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
