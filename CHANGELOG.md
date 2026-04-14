# CHANGELOG.md

Все заметные изменения в проекте CryoDAQ документируются в этом файле.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/).
Проект использует [Semantic Versioning](https://semver.org/lang/ru/).

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

## Pre-release history (версии до v0.33.0)

Версии 0.1.0 через 0.32.x разрабатывались, но не были individually tagged.
Предыдущие CHANGELOG-записи для этих версий содержали reconstructed content
с неправильными version boundaries, датами и content-to-version assignments
относительно actual commit archaeology (подтверждено cross-reference
verification против docs/audits/GIT_HISTORY_ARCHAEOLOGY.md и
docs/changelog/RETRO_ANALYSIS_V3.md).

Старые записи удалены. Для исследования pre-v0.33.0 истории обращайтесь
к authoritative источникам:

- **`docs/audits/GIT_HISTORY_ARCHAEOLOGY.md`** — 14-фазная authoritative
  commit archaeology (200 first-parent commits, 2026-03-14 — 2026-04-14)
- **`docs/changelog/RETRO_ANALYSIS_V3.md`** — 33 предложенные retroactive
  версии с commit hash ranges (research-grade, не canonical)
- **`docs/audits/CODEX_FULL_AUDIT.md`** — Phase 2d findings с commit-level
  detail
- **`docs/audits/CODEX_ROUND_2_AUDIT.md`** — round 2 findings, Tier 1 sources

Canonical CHANGELOG starting from v0.33.0 maintained per release discipline
section in CLAUDE.md.
