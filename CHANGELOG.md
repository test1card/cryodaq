# CHANGELOG.md

Все заметные изменения в проекте CryoDAQ документируются в этом файле.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/).
Проект использует [Semantic Versioning](https://semver.org/lang/ru/).

---

## [Unreleased]

### Добавлено

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

- **Шрифты** — Inter заменён на Fira Sans, JetBrains Mono заменён на
  Fira Code. Старые файлы остаются в `resources/fonts/` до B.7 cleanup.
- **theme.py** — полностью переработан под новые design tokens.
  Backwards-compatible alias'ы сохранены для постепенной миграции.

### Adopted from

- **UI UX Pro Max skill** v2.5.0 — design tokens, typography pairings,
  UX guidelines. MIT licensed by Next Level Builder.
  https://github.com/nextlevelbuilder/ui-ux-pro-max-skill

### Selected commits

- `ae7d8d4` fix(engine): add missing load_alarm_config import
- `c4396a8` ui(phase-1-v2): block B.3 — DynamicSensorGrid

---

## [0.33.0] — 2026-04-14

Первый tagged release. Hardened backend и Phase UI-1 v2 shell с dashboard
foundation, shipped одним merge commit `7b453d5`. Закрывает 20-версионный
gap в changelog с последнего v0.13.0.

### Added

- **Phase UI-1 v2 shell (блоки A через A.9).** Новый `MainWindowV2`
  (`gui/shell/main_window_v2.py`) с `TopWatchBar`, `ToolRail`,
  `BottomStatusBar` и `OverlayContainer` заменяют tab-based legacy
  `MainWindow`. Ambient information radiator layout для недельных
  экспериментов. Russian localization throughout. Блоки A.5 (icon
  visibility, launcher wiring), A.6 (chrome consolidation, RU
  localization), A.7 (layout collision fix), A.8 (child widget
  background seam fix), A.9 (orphan widget stubs, worker stacking
  guard, ChannelManager zone 3 channel summary).
- **Phase UI-1 v2 dashboard (блоки B.1, B.1.1, B.2).**
  `DashboardView` (`gui/dashboard/dashboard_view.py`) с пятью зонами
  (10/22/44/20/4 stretch ratios после B.1.1 reorder). Shared
  `ChannelBufferStore` (`gui/dashboard/channel_buffer.py`) для rolling
  per-channel history. `TimeWindow` enum (1мин/1ч/6ч/24ч/Всё).
  `TempPlotWidget` — multi-channel temperature plot с clickable legend
  и Lin/Log toggle. `PressurePlotWidget` — compact log-Y pressure
  plot, X-linked to temperature. Time window echo в `TopWatchBar`
  zone 2.
- **Phase UI-1 v1 theming foundation (блоки 1-7).** `theme.py`
  design tokens (colors, fonts, spacing). Inter + JetBrains Mono
  fonts bundled. 10 Lucide SVG icons. `pyqtdarktheme-fork`
  dependency. Systematic `setStyleSheet` classification и
  application across all widget panels. pyqtgraph `setBackground`
  cleanup.
- **Phase 2e Stage 1.** Streaming Parquet archive written at
  experiment finalize (`storage/parquet_archive.py`). Enables
  long-term archival и offline analytics. Confirmed shipped per
  CODEX_FULL_AUDIT H.7 (streaming writes, compression, midnight
  iteration, UTC timestamps, finalize integration).
- **Graphify knowledge graph integration.** Persistent structural
  memory via `graphify-out/`. Automatic rebuild on every commit и
  branch switch via git hooks. Top god nodes: `Reading` (789 edges),
  `ChannelStatus` (375), `DataBroker` (246), `ZmqCommandWorker`
  (195), `SafetyManager` (156). Injected в Claude Code sessions via
  `UserPromptSubmit` hook (62ms execution).

### Changed

- **Tier 1 Fix A — calibration channel canonicalization (`a5cd8b7`).**
  `CalibrationAcquisitionService.activate()` canonicalizes channel
  references через new `ChannelManager.resolve_channel_reference()`.
  Accepts short IDs (`"Т1"`) или full labels (`"Т1 Криостат верх"`).
  Raises new `CalibrationCommandError` on unknown or ambiguous refs.
  Engine returns structured failure response instead of crashing.
  Closes Codex round 2 NEW finding: "Calibration channel identity is
  not canonicalized before activation"
  (`engine.py:370-375`, `calibration_acquisition.py:92-108`).
- **Tier 1 Fix B — DataBroker subscriber exception isolation
  (`cbaa7f2`).** `DataBroker.publish()` wraps per-subscriber
  operations в try/except. One failing subscriber no longer aborts
  fan-out to siblings. `asyncio.CancelledError` still propagates.
  Protects new v2 dashboard subscribers from each other. Closes
  Codex round 1 finding B.1 / round 2 confirmed HIGH: "DataBroker
  subscriber exceptions sit on critical path before SafetyBroker"
  (`broker.py:85-109`, `scheduler.py:385-389`).
- **Tier 1 Fix C — alarm acknowledged state serialization
  (`d9e2fdf`).** `AlarmStateManager.acknowledge()` returns event dict
  or `None` (previously `bool`). Engine publishes event через
  `DataBroker` на channel `alarm_v2/acknowledged`. Enables future
  v2 alarm badge. `alarm_v2_status` response включает
  `acknowledged`, `acknowledged_at`, `acknowledged_by` fields.
  Closes Phase 2d deferred item A.9.1 (CODEX_FULL_AUDIT H.3).
- **Phase 2d safety и persistence hardening (14 commits).** Web
  stored XSS escape. `_fault()` hardware emergency_off shielded from
  cancellation. `_fault()` ordering: callback BEFORE publish (Jules
  R2). RUN_PERMITTED heartbeat monitoring. Fail-closed config for
  all 5 safety-adjacent configs. Atomic file writes via
  `core/atomic_write`. WAL mode verification. OVERRANGE/UNDERRANGE
  persist. Calibration KRDG+SRDG atomic per poll cycle. Scheduler
  graceful drain. AlarmStateManager.acknowledge real implementation
  with idempotent re-ack guard. Ruff lint debt 830 → 445.
- **Launcher и `gui/app.py`.** Entry point `cryodaq-gui` routes to
  `MainWindowV2` as primary shell. Legacy `MainWindow` и tab panels
  remain active for fallback until Block B.7.

### Fixed

- **Calibration panel instrument prefix bug (`621f98a`).** Pre-existing:
  `gui/widgets/calibration_panel.py` built channel refs в
  `"LS218_1:Т1 Криостат верх"` format from combobox. Pre-Tier-1
  this caused silent data loss; post-Tier-1 resolver rejects prefix
  format. Added `_strip_instrument_prefix()` helper applied to
  `reference_channel` и each `target_channel`.
- **Duplicate imports from rebase conflict (`621f98a`).**
  `gui/main_window.py` и `gui/widgets/experiment_workspace.py` had
  duplicate `ZmqBridge` и `get_data_dir` imports from v1 block 6
  merge conflict resolution. Removed duplicates.
- **`inject_context.py` broken pytest invocation (`f6fe4b9`).**
  `UserPromptSubmit` hook ran `pytest` against system `python3`
  без pytest module, silently failed, injected `"Tests: no output"`
  on every Claude Code prompt. Replaced с 62ms version using git
  metadata + graphify god nodes.
- **Codex R1 finding A.1 — calibration throttle atomicity
  regression.** Initially CRITICAL, downgraded to MEDIUM in R2 after
  verification showed common channels protected by config.

### Infrastructure

- **RTK (Rust Token Killer)** — pre-existing bash compression hook.
  60-90% token compression on dev operations. Note: strips `--no-ff`
  flag from `git merge` — workaround: `/usr/bin/git` directly.
- **Graphify skill 0.3.12 → 0.4.13.** First graph build indexed 294
  files into 4,304 nodes, 10,602 edges, 169 Leiden communities.
  ~3.1x token reduction for structural queries.
- **Git hooks:** `post-commit` и `post-checkout` for automatic
  incremental graph rebuild.
- **Project-level CC hook.** `.claude/settings.json` contains
  `PreToolUse` for `Glob|Grep` reminding Claude to read
  `graphify-out/GRAPH_REPORT.md` first.
- **Three-layer review pipeline** established in Phase 2d: CC
  tactical + Codex second-opinion + Jules architectural. 14 commits,
  17 Codex reviews, 2 Jules rounds.

### Known Issues

- **RTK strips `--no-ff` flag** from `git merge`. Workaround:
  `/usr/bin/git`.
- **~500 ruff lint errors** в `src/` и `tests/`. Pre-existing
  technical debt.
- **Dual-shell transition state.** Legacy `MainWindow`, `OverviewPanel`
  и tab panels remain active alongside `MainWindowV2` until Block B.7.
- **Wall-clock sensitivity** in `alarm_providers.py` и
  `channel_state.py` (`time.time()` vs `monotonic()`). Codex R2
  confirmed finding, not yet addressed.
- **Reporting generator blocking** — sync `subprocess.run()` for
  LibreOffice. Codex R1 E.1, still open.
- **Gap между v0.13.0 и v0.33.0.** Versions 0.14.0-0.32.x developed
  but not individually tagged. Retroactive research в
  `docs/changelog/RETRO_ANALYSIS_V3.md`.

### Test baseline

- 934 passed, 2 skipped
- +39 tests since Phase 2d start (895 baseline)
- +11 from Tier 1 fixes (5 calibration canon, 4 broker isolation,
  2 alarm ack serialization)
- +28 from v2 shell и dashboard merge
- Zero regressions

### Tags

- `v0.33.0` — merge commit `7b453d5`
- `pre-tier1-merge-backup-2026-04-14` — rollback anchor

### Selected commits in this release

- `a5cd8b7` tier1-a: canonicalize calibration channel identities
- `cbaa7f2` tier1-b: isolate DataBroker subscriber exceptions
- `d9e2fdf` tier1-c: serialize alarm acknowledged state through broker
- `7b453d5` merge: Phase UI-1 v2 shell и dashboard through Block B.2
- `621f98a` post-merge fixes: calibration prefix strip + dedupe imports
- `dafdd99` docs: post-merge PROJECT_STATUS и CLAUDE.md updates
- `f6fe4b9` infra: graphify setup + inject_context hook efficiency fix

Phase 2d detailed commit trail (14 commits): see `PROJECT_STATUS.md`
Phase 2d commits section. Codex audit trail: `docs/audits/CODEX_FULL_AUDIT.md`
и `docs/audits/CODEX_ROUND_2_AUDIT.md`.

### Upgrade notes

Не applicable — internal release.

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
