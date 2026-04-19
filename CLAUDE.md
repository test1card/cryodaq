# CLAUDE.md

Этот файл задаёт рабочие ориентиры для Claude Code при работе с данным репозиторием.

# CryoDAQ

## Источник истины по UI/визуальному дизайну

Единый источник правды для всего operator-facing UI — `docs/design-system/`.
66 файлов, v1.0.0, покрывают токены, правила, компоненты, паттерны,
доступность и governance.

**Перед любой работой с GUI-кодом** (создание виджетов, стилизация,
QSS, layout, цвета, шрифты) — читай релевантные файлы:

- `docs/design-system/README.md` — точка входа, навигация
- `docs/design-system/MANIFEST.md` — полный индекс + 65 encoded decisions
- `docs/design-system/rules/<category>-rules.md` — 79 enforcement rules
- `docs/design-system/components/<widget>.md` — generic primitives
- `docs/design-system/cryodaq-primitives/<widget>.md` — domain widgets
- `docs/design-system/patterns/<pattern>.md` — композиция правил для типовых задач
- `docs/design-system/accessibility/*.md` — WCAG 2.2 AA commitment
- `docs/design-system/governance/*.md` — как правила/токены эволюционируют

**Правило:** каждое GUI-изменение, затрагивающее визуальное представление,
должно начинаться с чтения релевантных файлов design-system. Значения
цветов, размеров, отступов, радиусов, шрифтов берутся ТОЛЬКО из
theme.py (который определён через docs/design-system/tokens/*.md).
Hardcoded hex / px / font-size — нарушение RULE-COLOR-010 / RULE-TYPO-007 /
RULE-SPACE-001 соответственно.

**Deprecated tokens:** STONE_* семейство (ref `docs/design-system/governance/deprecation-policy.md`).
Новый код использует канонические имена (FOREGROUND, BACKGROUND, MUTED_FOREGROUND etc.).

Governance: Architect = Vladimir; все изменения дизайн-системы идут через
`docs/design-system/governance/contribution.md`.

## Снимок сверки

- Источник истины по продуктовой модели: один эксперимент равен одной experiment card, и во время активного эксперимента открыта ровно одна карточка.
- Основной операторский workflow различает `Эксперимент` и `Отладка`; `Отладка` не должна создавать архивные записи и автоматические отчёты по эксперименту.
- Dual-channel Keithley (`smua`, `smub`, `smua + smub`) остаётся актуальной моделью. Старые ожидания про disable/hide/remove `smub` устарели.
- Контракт внешних отчётов и текущий код используют `report_raw.pdf` и `report_editable.docx`, а `report_raw.docx` остаётся machine-generated intermediate input для best-effort PDF-конвертации.
- Calibration v2: continuous SRDG acquisition during calibration experiments (CalibrationAcquisitionService), post-run pipeline (CalibrationFitter: extract → downsample → breakpoints → Chebyshev fit), three-mode GUI (Setup → Acquisition → Results), `.330` / `.340` / JSON export, runtime apply с per-channel policy.

Замена LabVIEW для cryogenic laboratory workflow (Millimetron / АКЦ ФИАН).
Python 3.12+, asyncio, PySide6. Current package metadata: `0.13.0`.

## Команды сборки и разработки

```bash
pip install -e ".[dev,web]"    # Install runtime, dev, and optional web dependencies
# (Parquet archive support ships by default since IV.4 — pyarrow is a
#  base dep. The legacy `archive` extra is retained as a no-op alias
#  so older install lines keep working: `pip install -e ".[dev,web,archive]"`.)
cryodaq                        # Operator launcher
cryodaq-engine                 # Run engine headless (real instruments)
cryodaq-engine --mock          # Run engine with simulated data
cryodaq-gui                    # Run GUI only (connects to engine over ZMQ)
uvicorn cryodaq.web.server:app --host 0.0.0.0 --port 8080
install.bat                    # Windows installer helper
python create_shortcut.py      # Create desktop shortcut
cryodaq-cooldown build --data cooldown_v5/ --output model/
cryodaq-cooldown predict --model model/ --T_cold 50 --T_warm 120 --t_elapsed 8
pytest
pytest tests/core/
pytest -k test_safety
pytest -k test_cooldown
ruff check src/ tests/
ruff format src/ tests/
```

## Переменные окружения

- `CRYODAQ_ROOT` — переопределяет корневой каталог проекта
- `CRYODAQ_MOCK=1` — запускает engine в mock mode

## Развёртывание

`config/*.local.yaml` overrides `config/*.yaml`.
Local configs are gitignored and intended for machine-specific deployment data such as COM ports, GPIB addresses, and notification credentials.

See `docs/deployment.md` for operator-PC deployment steps.

## Архитектура

Три основных runtime-контура:

- `cryodaq-engine` — headless asyncio runtime: acquisition, safety, storage, commands
- `cryodaq-gui` или `cryodaq` — desktop operator client / launcher
- web dashboard — optional FastAPI monitoring surface

### Архитектура safety

SafetyManager is the single authority for source on/off decisions.
Source OFF is the default. Running requires continuous proof of health.

```text
SafetyBroker (dedicated, overflow=FAULT)
  -> SafetyManager
     States: SAFE_OFF -> READY -> RUN_PERMITTED -> RUNNING -> FAULT_LATCHED -> MANUAL_RECOVERY -> READY
     Note: request_run() can shortcut SAFE_OFF -> RUNNING when all preconditions met
     MANUAL_RECOVERY: entered after acknowledge_fault(), transitions to
     READY when preconditions restore.
     Fail-on-silence: stale data -> FAULT + emergency_off (fires only
     while state=RUNNING; outside RUNNING, stale data blocks readiness
     via preconditions, not via fault)
     Rate limit: dT/dt > 5 K/min -> FAULT (5 K/min is the configurable
     default in safety.yaml, not a hard-coded invariant)
     Recovery: acknowledge + precondition re-check + cooldown
     Safety regulation is host-side only (no Keithley TSP watchdog yet —
     planned for Phase 3, requires hardware verification).
     Crash-recovery guard: Keithley2604B.connect() forces OUTPUT_OFF on
     both SMU channels before assuming control (best-effort: if force-OFF
     fails, logs CRITICAL and continues — not guaranteed).
```

### Persistence-first ordering

```text
InstrumentDriver.read_channels()
  -> Scheduler
     1. SQLiteWriter.write_immediate()
     2. THEN DataBroker.publish_batch()
     3. THEN SafetyBroker.publish_batch()
```

Invariant: if DataBroker has a reading, it has already been written to SQLite.

### Вкладки GUI

Текущие вкладки `MainWindow`:

- `Обзор` — двухколоночный layout (графики слева, sidebar справа)
- `Эксперимент` — ExperimentWorkspace (создание, управление, финализация)
- `Источник мощности`
- `Аналитика`
- `Теплопроводность` — включает встроенное автоизмерение (ранее отдельная вкладка)
- `Алармы`
- `Служебный лог`
- `Архив`
- `Калибровка`
- `Приборы`

Меню:

- `Файл` — экспорт CSV / HDF5 / Excel
- `Эксперимент` — запуск и завершение эксперимента
- `Настройки` — редактор каналов и параметры подключений

### Индекс модулей

**Точки входа**

- `src/cryodaq/engine.py` — headless engine
- `src/cryodaq/launcher.py` — operator launcher
- `src/cryodaq/__main__.py` — `python -m cryodaq` invokes launcher
- `src/cryodaq/_frozen_main.py` — frozen-app entry point wrapper (PyInstaller)
- `src/cryodaq/gui/app.py` — standalone GUI entry point
- `src/cryodaq/gui/__main__.py` — `python -m cryodaq.gui` invokes the GUI app

**Поддержка процесса**

- `src/cryodaq/instance_lock.py` — single-instance lock for GUI processes
- `src/cryodaq/logging_setup.py` — shared logging configuration (secret redaction defence-in-depth)
- `src/cryodaq/paths.py` — runtime path resolution (CRYODAQ_ROOT, frozen vs source layout)

**Core**

- `src/cryodaq/core/alarm.py` — v1 alarm engine (threshold + hysteresis)
- `src/cryodaq/core/alarm_v2.py` — v2 alarm engine (YAML-driven, phase-aware, composite conditions)
- `src/cryodaq/core/alarm_config.py` — загрузка и парсинг конфигурации алармов v3
- `src/cryodaq/core/alarm_providers.py` — конкретные PhaseProvider / SetpointProvider для alarm engine v2
- `src/cryodaq/core/atomic_write.py` — atomic file write via os.replace()
- `src/cryodaq/core/broker.py` — DataBroker fan-out pub/sub
- `src/cryodaq/core/calibration_acquisition.py` — непрерывный сбор SRDG при калибровке
- `src/cryodaq/core/channel_manager.py` — channel name/visibility singleton (get_channel_manager())
- `src/cryodaq/core/channel_state.py` — per-channel state tracker for alarm evaluation (staleness, fault history)
- `src/cryodaq/core/disk_monitor.py` — мониторинг свободного места на диске
- `src/cryodaq/core/event_logger.py` — автоматическое логирование системных событий
- `src/cryodaq/core/experiment.py` — управление экспериментами, фазы (ExperimentPhase)
- `src/cryodaq/core/housekeeping.py`
- `src/cryodaq/core/interlock.py` — threshold detection, delegates actions to SafetyManager
- `src/cryodaq/core/operator_log.py`
- `src/cryodaq/core/phase_labels.py` — canonical Russian phase labels (shared)
- `src/cryodaq/core/rate_estimator.py` — rolling dT/dt estimator with min_points gate
- `src/cryodaq/core/safety_broker.py` — dedicated safety channel (overflow=FAULT)
- `src/cryodaq/core/safety_manager.py` — 6-state FSM, fail-on-silence, rate limiting
- `src/cryodaq/core/scheduler.py` — instrument polling, persistence-first ordering
- `src/cryodaq/core/sensor_diagnostics.py` — noise/drift/correlation health scoring (numpy exception)
- `src/cryodaq/core/smu_channel.py` — SmuChannel enum + normalize helper for Keithley channel IDs
- `src/cryodaq/core/user_preferences.py` — persistent user preferences for experiment-creation forms
- `src/cryodaq/core/zmq_bridge.py` — ZMQ PUB/SUB + REP/REQ command server
- `src/cryodaq/core/zmq_subprocess.py` — subprocess isolation for ZMQ bridge

**Аналитика**

- `src/cryodaq/analytics/base_plugin.py` — AnalyticsPlugin ABC
- `src/cryodaq/analytics/calibration.py` — CalibrationStore, Chebyshev fit, runtime policy
- `src/cryodaq/analytics/calibration_fitter.py` — post-run pipeline (extract, downsample, breakpoints, fit)
- `src/cryodaq/analytics/cooldown_predictor.py` — progress-variable ensemble cooldown ETA
- `src/cryodaq/analytics/cooldown_service.py` — async cooldown orchestration
- `src/cryodaq/analytics/plugin_loader.py` — hot-reload plugin pipeline (5s mtime polling)
- `src/cryodaq/analytics/steady_state.py` — T∞ predictor via exponential decay fit
- `src/cryodaq/analytics/vacuum_trend.py` — BIC-selected vacuum pump-down extrapolation

**Драйверы**

- `src/cryodaq/drivers/base.py` — InstrumentDriver ABC, Reading dataclass, ChannelStatus enum
- `src/cryodaq/drivers/instruments/keithley_2604b.py` — Keithley 2604B dual-SMU (host-side P=const)
- `src/cryodaq/drivers/instruments/lakeshore_218s.py` — LakeShore 218S 8-channel thermometer
- `src/cryodaq/drivers/instruments/thyracont_vsp63d.py` — Thyracont VSP63D vacuum gauge (MV00 + V1)
- `src/cryodaq/drivers/transport/gpib.py` — async GPIB transport via PyVISA
- `src/cryodaq/drivers/transport/serial.py` — async serial transport via pyserial-asyncio
- `src/cryodaq/drivers/transport/usbtmc.py` — async USB-TMC transport via PyVISA

**Уведомления**

- `src/cryodaq/notifications/telegram.py` — TelegramNotifier (alarm callbacks)
- `src/cryodaq/notifications/telegram_commands.py` — interactive command bot (/status /temps /pressure)
- `src/cryodaq/notifications/escalation.py` — timed escalation service
- `src/cryodaq/notifications/periodic_report.py` — scheduled Telegram reports with charts
- `src/cryodaq/notifications/_secrets.py` — SecretStr wrapper for token leak prevention

**GUI — Shell (Phase I.1 chrome)**

- `src/cryodaq/gui/shell/main_window_v2.py` — v2 shell: TopWatchBar + ToolRail + BottomStatusBar + main content area; canonical mnemonic shortcuts (`Ctrl+L/E/A/K/M/R/C/D`, `F5`, `Ctrl+Shift+X`) per AD-002 — sole owner of shortcut bindings after the v1 `gui/main_window.py` was retired in Phase II.13
- `src/cryodaq/gui/shell/top_watch_bar.py` — top bar: 4 vitals + mode badge (Эксперимент / Отладка)
- `src/cryodaq/gui/shell/tool_rail.py` — left-side icon navigation (9 slots, Ctrl+[1-9] transitional)
- `src/cryodaq/gui/shell/bottom_status_bar.py` — bottom safety-state strip
- `src/cryodaq/gui/shell/overlay_container.py` — central content container (overlay host)
- `src/cryodaq/gui/shell/new_experiment_dialog.py` — experiment creation dialog (B.8 rebuild)
- `src/cryodaq/gui/shell/experiment_overlay.py` — experiment management overlay (B.8)

**GUI — Overlay primitives (`shell/overlays/_design_system/`)**

- `src/cryodaq/gui/shell/overlays/_design_system/modal_card.py` — centered overlay with backdrop (Phase I.1)
- `src/cryodaq/gui/shell/overlays/_design_system/bento_grid.py` — grid layout (12-col runtime; 8-col canonical target per design-system)
- `src/cryodaq/gui/shell/overlays/_design_system/drill_down_breadcrumb.py` — sticky top bar with back navigation
- `src/cryodaq/gui/shell/overlays/_design_system/_showcase.py` — standalone visual showcase for overlay primitives

**GUI — Dashboard (Phase I.1 content)**

- `src/cryodaq/gui/dashboard/dashboard_view.py` — 5-zone dashboard container
- `src/cryodaq/gui/dashboard/channel_buffer.py` — shared per-channel rolling history store
- `src/cryodaq/gui/dashboard/dynamic_sensor_grid.py` — width-driven responsive grid of SensorCell widgets
- `src/cryodaq/gui/dashboard/sensor_cell.py` — single-channel data cell (B.3)
- `src/cryodaq/gui/dashboard/phase_aware_widget.py` — compact phase-aware widget for dashboard (B.5.6)
- `src/cryodaq/gui/dashboard/phase_stepper.py` — 6-phase stepper (extracted from PhaseAwareWidget B.5.5)
- `src/cryodaq/gui/dashboard/phase_content/hero_readout.py` — phase hero readout
- `src/cryodaq/gui/dashboard/phase_content/eta_display.py` — phase ETA display
- `src/cryodaq/gui/dashboard/phase_content/milestone_list.py` — phase milestone list
- `src/cryodaq/gui/dashboard/temp_plot_widget.py` — multi-channel temperature plot with clickable legend
- `src/cryodaq/gui/dashboard/pressure_plot_widget.py` — compact log-Y pressure plot
- `src/cryodaq/gui/dashboard/quick_log_block.py` — compact inline log composer + recent entries (B.7)
- `src/cryodaq/gui/dashboard/time_window.py` — TimeWindow enum for time-range selection

**GUI — Theming and IPC**

- `src/cryodaq/gui/theme.py` — foundation design tokens (colors, fonts, spacing) — 139 tokens, see design-system v1.0.1
- `src/cryodaq/gui/zmq_client.py` — ZMQ bridge client for GUI (all ZMQ lives in a subprocess)

**GUI — Ancillary widgets (non-overlay surfaces)**

Remaining widget modules after Phase II.13 legacy cleanup. All
`MainWindow`-era overlays (alarm / archive / calibration / conductivity
/ instrument_status / sensor_diag_panel / keithley / operator_log /
experiment_workspace / autosweep) were deleted in II.13 and replaced by
shell-v2 overlays under `src/cryodaq/gui/shell/overlays/`. The v1 tab
main window (`gui/main_window.py`) was also retired in II.13 — the
`cryodaq-gui` entry point has used `MainWindowV2` via `gui/app.py` since
Phase I.1.

- `src/cryodaq/gui/tray_status.py` — system-tray status indicator
- `src/cryodaq/gui/widgets/analytics_panel.py` — R_thermal + прогноз охлаждения
- `src/cryodaq/gui/widgets/channel_editor.py` — редактор каналов (видимость, имена)
- `src/cryodaq/gui/widgets/common.py` — shared helpers / mixins (retained — consumed by remaining widgets listed below)
- `src/cryodaq/gui/widgets/connection_settings.py` — диалог настройки подключения приборов
- `src/cryodaq/gui/widgets/experiment_dialogs.py` — диалоги старта/завершения эксперимента (legacy)
- `src/cryodaq/gui/widgets/overview_panel.py` — двухколоночный: графики + карточки
- `src/cryodaq/gui/widgets/preflight_dialog.py` — предполётная проверка перед экспериментом
- `src/cryodaq/gui/widgets/pressure_panel.py` — панель давления (вакуумметр)
- `src/cryodaq/gui/widgets/shift_handover.py` — смены (ShiftBar, ShiftStartDialog, ShiftEndDialog)
- `src/cryodaq/gui/widgets/temp_panel.py` — панель отображения температурных каналов (24 канала)
- `src/cryodaq/gui/widgets/vacuum_trend_panel.py` — прогноз вакуума

**Storage**

- `src/cryodaq/storage/sqlite_writer.py` — WAL-mode SQLite, daily rotation, persistence-first
- `src/cryodaq/storage/parquet_archive.py` — Parquet export/read для архива экспериментов (pyarrow теперь базовая зависимость, IV.4 F1)
- `src/cryodaq/storage/csv_export.py` — экспорт данных из SQLite в CSV
- `src/cryodaq/storage/hdf5_export.py` — экспорт данных из SQLite в HDF5
- `src/cryodaq/storage/xlsx_export.py` — экспорт данных в Excel (.xlsx) через openpyxl
- `src/cryodaq/storage/replay.py` — воспроизведение исторических данных из SQLite через DataBroker

**Reporting**

- `src/cryodaq/reporting/data.py`
- `src/cryodaq/reporting/generator.py`
- `src/cryodaq/reporting/sections.py`

**Web**

- `src/cryodaq/web/server.py`

**Design System**

- `docs/design-system/README.md` — design system entry point (v1.0.1, 67 files, 139 tokens)
- `docs/design-system/MANIFEST.md` — full index + 65 encoded decisions
- See `## Источник истины по UI/визуальному дизайну` above for the full reference and authority rules

**Tools**

- `src/cryodaq/tools/cooldown_cli.py`

**TSP**

- `tsp/p_const.lua` — draft TSP supervisor for Phase 3 hardware watchdog
  upload (currently NOT loaded — keithley_2604b.py runs P=const host-side)

## Конфигурационные файлы

- `config/instruments.yaml`
- `config/interlocks.yaml`
- `config/alarms.yaml`
- `config/alarms_v3.yaml`
- `config/safety.yaml`
- `config/notifications.yaml`
- `config/channels.yaml`
- `config/cooldown.yaml`
- `config/experiment_templates/*.yaml`
- `config/housekeeping.yaml`
- `config/plugins.yaml`
- `config/shifts.yaml`
- `config/*.local.yaml.example`

## Приборы

- LakeShore 218S
- Keithley 2604B
- Thyracont VSP63D

## Ключевые правила

- `SAFE_OFF` — состояние по умолчанию.
- GUI — отдельный процесс и не должен быть источником истины для runtime state.
- Keithley disconnect must call emergency off first.
- No blocking I/O on the engine event loop (known exception: `reporting/generator.py` uses sync `subprocess.run()` for LibreOffice PDF conversion — DEEP_AUDIT finding E.2).
- Operator-facing GUI text should remain in Russian.
- No numpy/scipy в drivers/core (исключение: core/sensor_diagnostics.py — MAD/корреляция).
- Scheduler writes to SQLite before publishing to brokers.

## Codex self-review loop (mandatory for block commits)

**Автономный workflow:** после каждого **initial block commit** (новый overlay / новая feature surface / engine wiring) и каждого **amend-fix в ответ на предыдущий Codex FAIL** Claude Code вызывает Codex через slash-команду `/codex`, самостоятельно читает verdict, решает amend или close по правилам `docs/CODEX_SELF_REVIEW_PLAYBOOK.md`, и продолжает до PASS или 3-cycle limit — без ожидания `continue` от architect.

**Полный playbook:** `docs/CODEX_SELF_REVIEW_PLAYBOOK.md` — autonomy mode rules, canonical prompt template, fix-amend template, invocation pattern, model selection (gpt-5.4 high reasoning ОБЯЗАТЕЛЬНО), anti-patterns, max-cycle limit, decision tree для FAIL findings. Читать перед каждым block commit.

**Short version:**
- **Когда звать Codex:** initial block commit + любой amend после FAIL.
- **Когда НЕ звать:** doc-only commits, theme/YAML drops, cleanup commits, уже PASS на текущем SHA.
- **Модель:** `gpt-5.4` с high reasoning effort — ОБЯЗАТЕЛЬНО. `/codex` по умолчанию берёт o3, который слаб для нашего workflow. Всегда указывать в первых строках prompt блока `Model: gpt-5.4 / Reasoning effort: high` + inline flags если plugin их поддерживает. Если Codex ответил как o3 — retry с override.
- **На FAIL — автономно:** CRITICAL/HIGH → amend без спроса; MEDIUM <3 файлов скоп → amend без спроса; LOW trivial → amend, иначе в residual risks; design-decision FAIL (wine vs blue, layout choice) → STOP + surface to architect.
- **Когда ОБЯЗАТЕЛЬНО surface к architect:** genuine architectural fork в Stage 0 (missing engine API, duplicate backend); design-decision FAIL; 3 amend cycles без PASS; out-of-scope требования Codex; pre-commit gates fail в чужом коде.
- **Лимит:** 3 amend cycles на блок. 4-я попытка — STOP, что-то структурное сломано.
- **Репорт architect’у в конце:** финальный SHA + Codex PASS summary + residual risks list (если есть). Architect видит результат, не процесс.

Это не replacement для architect review — Vladimir finalizes каждый block. Это фильтр первой ступени: Codex ловит очевидные DS leaks / token slips / pattern mismatches до того как они дойдут до architect, освобождая Vladimir'у context для архитектурных вопросов.

## CI budget discipline

- **Full `pytest -q` suite** (~10-15 min on Mac) runs ONLY on initial block commits where the diff is large: new overlay file (~1000 LOC), new test file, multiple `MainWindowV2` wiring changes. This is the commit that gets pushed first and reviewed by Codex.
- **Amend-fix commits** (post-Codex-review surgical patches, 1-3 files changed, < 100 LOC delta) run ONLY targeted tests: `ruff check <touched files>` + `pytest <touched test files>`. The full suite naturally runs at the start of the next block's initial commit; regression detection is NOT lost, it's deferred by one block.
- Rationale: amend diffs by definition have small blast radius (architect-reviewed scope limits them). Burning 10+ minutes of pytest wait time on every amend is token and wall-clock waste.
- Exception: if the amend touches a module imported by many non-test files (e.g. `main_window_v2.py`, `engine.py`, `safety_manager.py`), run the full suite. Judgment call.

## Кодировка файлов

- **Python source / Markdown / YAML source in repo** — UTF-8 **без BOM** (стандарт Python 3; все исходники в `src/`, `tests/`, `docs/`, `config/` свободны от BOM). Проверено `file src/cryodaq/gui/shell/overlays/*.py` и hex-head `head -c 3 file.py` → `"""` / `---`, не `EF BB BF`.
- **BOM применяется только к** operator-facing CSV-выгрузкам (`storage/csv_export.py`) — Excel на русской Windows корректно читает Cyrillic только при BOM-префиксе. Это per-usecase решение, не общее правило репо.
- Не добавлять BOM к Python-файлам / markdown-спекам / YAML-конфигам. Если внешний обзор флагует BOM-инвариант для source — это misapplication; ссылка на этот раздел.

## Дисциплина релизов

Документация курируется на границах релизов, не перезаписывается
автоматически на каждый commit. При создании нового tag `vX.Y.Z`:

1. **Обновить `CHANGELOG.md`** — добавить новую запись сверху:
   - Заголовок с датой: `## [X.Y.Z] — YYYY-MM-DD`
   - Краткий параграф, описывающий релиз
   - `### Added` — новые features и capabilities
   - `### Changed` — изменённые contracts и поведение (с commit hashes)
   - `### Fixed` — исправления багов (с commit hashes)
   - `### Infrastructure` — tooling, build, hooks, external integrations
   - `### Known Issues` — унаследованные или release-time caveats
   - `### Test baseline` — passed/skipped count, delta от предыдущего
   - `### Tags` — имена тегов и commits на которые они указывают
   - `### Selected commits in this release` — ключевые commits

2. **Обновить `README.md`** — только если изменились user-facing facts:
   - Новые commands или entry points
   - Новые обязательные зависимости
   - Version badge в заголовке

3. **Обновить этот файл (`CLAUDE.md`)** — только если изменились
   архитектура или workflow: новые модули, инварианты, constraints.

4. **Источники правды для CHANGELOG-записи:**
   - Audit documents в `docs/audits/` (Codex findings per-commit)
   - Phase specs в `docs/phase-ui-1/` и similar directories
   - Git log как secondary confirmation
   - Operator memory — последний fallback, не primary source

5. **Commit discipline:**
   - НЕ re-tag для включения post-tag docs updates.
   - НЕ использовать auto-update hooks для README / CHANGELOG /
     CLAUDE.md. Это curated документация, не mechanical output.

## Известные ограничения

- Best-effort PDF generation по-прежнему зависит от внешнего `soffice` / `LibreOffice`; отсутствие этого инструмента является ограничением окружения, а не code regression.
- `WindowsSelectorEventLoopPolicy` продолжает давать известные Python 3.14+ deprecation warnings.
- Supported deployment: `pip install -e .` из корня репозитория. Wheel-install не self-contained — config/, plugins/, data/ находятся вне пакета. Используйте CRYODAQ_ROOT для нестандартных layout.

## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- After modifying code files in this session, run `python3 -c "from graphify.watch import _rebuild_code; from pathlib import Path; _rebuild_code(Path('.'))"` to keep the graph current
