# CryoDAQ Phase UI-1 v2 — Roadmap

**Status:** Living roadmap. Reflects reality as of HEAD `9676acc` (2026-04-19). Phase II blocks shipped end-to-end: II.1 AnalyticsView (`860ecf3`), II.6 Keithley (`96adf5a`), II.3 OperatorLog (`9676acc`). II.6 post-review established the Host Integration Contract pattern codified in `PROJECT_STATUS.md`. Next block: II.2 ArchiveOverlay.

**Companion doc:** `docs/ui_refactor_context.md` — pain points + preserve list + design principles. Read first.

**Strategy:** "Build the system once, fill it many times."
Не переизобретаем design language для каждого overlay. Один раз
выстраиваем reusable composition primitives + apply systematically.

---

## Strategic shift (recorded for context)

Через B.8 → B.8.0.1 → B.8.0.2 цикл стало ясно:
- Overlays = **один паттерн повторённый 9 раз**, не 9 уникальных design problems
- Skill UI UX Pro Max патэрны (Bento Box, Drill-Down, Executive Dashboard, Data-Dense, Real-Time Monitoring, Swiss Modernism) — composable layers
- Building primitives once → каждый последующий overlay стоит 1-2 дня вместо 1-2 недель

Old plan: B.8 → B.9 Keithley → B.10 Analytics → B.11 batch restyle → ... (each from scratch).

New plan: Phase 0 Legacy Inventory → Phase I Design System → Phase II Apply → Phase III Polish.

---

## Phase 0 — Foundation Audit

**Goal:** Завершить понимание "что есть в legacy" до design work.

### Block: Legacy Inventory Audit (10 legacy surfaces)

Read-only CC block, аналог того что был сделан для ExperimentWorkspace.
Cuts uncertainty в design decisions. Без этого следующие overlay rebuilds
будут blind.

**Output:** 10 markdown reports в `docs/legacy-inventory/`.

**Estimate:** ~6h CC work (single large block, или 3 medium blocks по 3 tabs).

**Spec deliverable:** Architect writes one spec, CC executes. Template
готов — copy structure from `/tmp/legacy_experiment_workspace_inventory.md`.

**Success criteria:**
- All 10 inventories produced
- Each lists: layout, fields, ZMQ commands, signals, comparison к B.8 patterns
- Updated §1 of `ui_refactor_context.md`

---

## Phase I — Overlay Design System (Primitives)

**Goal:** One-time investment в reusable composition primitives. 

**Solves pain points:** P1 (consistent UX reduces cognitive load), implicit via consistency.

**Preserves:** все K1-K7 — primitives are content-agnostic, не trump existing functionality.

### Block I.1 — Modal Card Shell + Drill-Down Navigation

**Status:** ✅ COMPLETE — `ModalCard`, `DrillDownBreadcrumb`, `BentoGrid` landed in `src/cryodaq/gui/shell/overlays/_design_system/` (Phase I.1 complete 2026-04-16; subsequent refinements A.5 focus trap `6010a07`, A.6 BentoGrid 12→8 cols `8a8d189`).

Skill patterns: **Drill-Down Analytics**, **Swiss Modernism 2.0** (12-col grid).

Primitives:
- `ModalCard` — backdrop dim + centered card (1100px max width, 80vh max height)
- 3 close mechanisms (ESC + × + backdrop click)
- `DrillDownBreadcrumb` — sticky top bar «← Дашборд / <Overlay name>»
- 12-column grid layout container (`BentoGrid`)

Tests + visual showcase HTML page (Vladimir reviews before applying).

**Estimate:** 1 medium block (~2h CC).

### Block I.2 — Bento Tile Primitives

**Status:** ⬜ NOT STARTED — none of `BentoTile` / `ExecutiveKpi` / `DataDenseTile` / `LiveTile` / `ChartTile` / `EditableField` exist in `_design_system/`. Deliberately bypassed for AnalyticsView (II.1, `860ecf3`): plot-dominant primary views don't benefit from BentoGrid composition, so `QVBoxLayout + QHBoxLayout` + fixed-height chrome strips + direct pyqtgraph wrapping were chosen instead. Primitives remain on the roadmap for data-dense blocks (Archive II.2, OperatorLog II.3, Calibration II.7) where they are structurally useful.

Skill patterns: **Bento Box Grid**, **Real-Time Monitoring** (без pulse).

Primitives:
- `BentoTile` — base tile with optional header, optional `[gear]` menu, content slot
- `ExecutiveKpi` — large metric tile (KPI font 24-32px, Fira Code, optional sparkline)
- `DataDenseTile` — compact tile с form fields внутри (8-12px padding)
- `LiveTile` — content + small `[live •]` indicator (static dot, не animated)
- `ChartTile` — pyqtgraph wrapper with consistent header + axis styling
- `EditableField` — click to edit inline pattern (extracted from B.8 name edit)

Tests + visual showcase extension.

**Estimate:** 1 medium block (~2h CC).

### Block I.3 — Reusable Content Widgets Catalog

**Status:** ⚠️ PARTIAL — `PhaseStepper`, `HeroReadout`, `EtaDisplay`, `MilestoneList` exist under `src/cryodaq/gui/dashboard/phase_content/` (extracted from B.5.5 for dashboard use). This satisfies the B.5.x implementation need but NOT the I.3 extraction goal — classes have not been relocated to the `_design_system/` package and no `StatusBadge` / `ZmqWorkerField` primitives have been built.

Existing primitives + new:
- `PhaseStepper` (B.5.5) — phase pills row
- `HeroReadout` (B.5.5) — large numeric readout
- `EtaDisplay` (B.5.5) — ETA with progress
- `MilestoneList` (B.5.5) — phase history list
- NEW `StatusBadge` — unified pattern для ModeBadge + alarm + connection (replaces 3 разных implementations)
- NEW `ZmqWorkerField` — field auto-syncing via ZMQ command с in-flight guard (extracted from save card pattern)

Doc + tests.

**Estimate:** 1 small block (~1h CC, mostly extraction).

### Block I.4 — Visual Showcase Page

**Status:** ⚠️ PARTIAL — `_showcase.py` exists in `_design_system/` but covers only Phase I.1 primitives (ModalCard, BentoGrid, DrillDownBreadcrumb). Not extended for I.2/I.3 because those blocks haven't landed.

HTML artifact или Qt-based "storybook" page демонстрирующий все primitives
вместе. Vladimir reviews и approves design system **before** Phase II применяется.

**Estimate:** 1 small block (~1h).

**Phase I deliverable:**
- `src/cryodaq/gui/shell/overlays/_design_system/` package
- `docs/overlay_design_system.md` с visual examples
- `tests/gui/shell/overlays/_design_system/` test coverage
- Visual showcase для review

---

## Phase II — Apply Design System

**Goal:** Каждый existing overlay/panel → thin layer над primitives.

Order revised based on Phase 0 inventory findings (Phase 0 Summary above).
HIGH priority first (max user value, currently uncovered), then MEDIUM,
then LOW. Sensor Diag and Instruments combined; Sensor Diag becomes
popover not standalone overlay.

### HIGH priority — uncovered, daily-use

#### Block II.1 — AnalyticsOverlay

**Status:** ✅ COMPLETE — shipped as `AnalyticsView` primary-view QWidget at `src/cryodaq/gui/shell/views/analytics_view.py` (commit `860ecf3`, B.8 revision 2). Revision 1 (`9a089f9`) landed as ModalCard overlay but was architecturally corrected to primary view with plot-dominant layout (`QVBoxLayout + QHBoxLayout` + fixed-height chrome strips + direct pyqtgraph wrapping — bypassed Phase I.2/I.3 primitives deliberately). Follow-ups (non-blocking): actual-trajectory publisher not yet emitting, R_thermal publisher missing, VacuumTrendPanel not yet design-system-aligned.

Skill patterns: Bento + ChartTile + DataDense.
Uncovered by current dashboard. Highest user value.
B.5.5 primitives (HeroReadout, EtaDisplay, MilestoneList) finally
applied as designed.
Solves: P6 plot co-location.
Preserves: K5 plot zoom/pan.
Additional scope (Phase 0 K7 decision): include "Detected phase" tile showing
phase_detector output (`detected_phase` + `phase_confidence` from
`analytics/phase_detector/*`). Tile uses `LiveTile` primitive (live indicator
without pulse).
Estimate: 1 medium block.

#### Block II.2 — ArchiveOverlay

**Status:** ⬜ NOT STARTED.

Skill patterns: Drill-Down + Bento (experiment cards) + DataDense (details).
Zero coverage in new UI. K2-critical.
Preserves: K2 archive functionality. Per Phase 0 K6 decision: this overlay also hosts
the 3 global export buttons (CSV / HDF5 / Excel) migrated from legacy MainWindow File menu.
Each button exports current archive selection or active experiment data.
Estimate impact: +1 small task within block (button wiring to existing
`storage/csv_export.py`, `hdf5_export.py`, `xlsx_export.py`).
Estimate: 1 medium block.

#### Block II.3 — OperatorLog Overlay

**Status:** ✅ COMPLETE (`9676acc`, 2026-04-19). Full-featured operator journal overlay at `shell/overlays/operator_log_panel.py` — composer (author + tags + message + bind-experiment), filter chips (all / current / 8h / 24h), client-side text/author/tag filters with 250 ms debounce, day-grouped timeline, system-entry graying via MUTED_FOREGROUND, optimistic prepend on `log_entry` success, DS v1.0.1 tokens throughout. Host Integration Contract wired via `_tick_status` + `_on_experiment_status_received` + `_ensure_overlay("log")` replay. Legacy `widgets/operator_log_panel.py` marked DEPRECATED. Codex review PASS after one post-review amendment (forbidden token `TEXT_DISABLED` → `MUTED_FOREGROUND` in disabled-state QSS; chip border `STATUS_INFO` → `BORDER_SUBTLE`).

Skill patterns: Drill-Down + DataDense + filter sidebar.
QuickLogBlock covers only quick entry, full overlay needed.
Preserves: K1 service log with chronology.
Solves: P3 shift handover (partial — Phase III.1 completes).
Estimate: 1 small block.

### MEDIUM priority — functional rebuild

#### Block II.4 — AlarmOverlay (with badge popover)

**Status:** ⚠️ PARTIAL — TopWatchBar badge already routes into the registered legacy `AlarmPanel` (Phase I.1 wiring). Visual modernization + acknowledge-workflow polish pending.

Skill patterns: Drill-Down + DataDense (alarm rules table).
Badge in TopWatchBar already routes into the registered AlarmPanel overlay;
this block rebuilds that surface with visual modernization and verifies
acknowledge workflow polish / acknowledgment history presentation.
Solves: P2 alarm visibility (already partially solved via badge → existing panel).
Estimate: 1 small block.

#### Block II.5 — ConductivityOverlay

**Status:** ⬜ NOT STARTED.

Skill patterns: Drill-Down (auto-measurement workflow) + ChartTile + DataDense.
Auto-measurement state machine with min_wait safety guard preserved exactly.
Preserves: K6 export (CSV auto-measurement results).
Estimate: 1 medium block.

#### Block II.6 — KeithleyOverlay

**Status:** ✅ COMPLETE (`96adf5a`, 2026-04-18). Full rewrite from scratch at `shell/overlays/keithley_panel.py` aligned with engine power-control API (`p_target + v_comp + i_comp`). B.7 (`920aa97`) mode-based overlay was architecturally wrong (invented Ток/Напряжение/Откл semantics disconnected from engine) and never wired — replaced. Shipped features: P target / V compliance / I compliance spinboxes debounced 300 ms, 4 readouts per channel (V/I/R/P) with tabular figures, 2×2 rolling plot grid per channel (10м/1ч/6ч window), state badge (ВЫКЛ/ВКЛ/АВАРИЯ), A+B panel-level actions, connection + safety gating, emergency guarded by `QMessageBox.warning`. Host Integration Contract wired after Codex FAIL on initial commit (`36463f4`) surfaced that `set_connected`/`set_safety_ready` were never called by shell. Post-review amendment added `_tick_status` mirror + safety dispatch at `_dispatch_reading` + `_ensure_overlay("source")` replay + `_map_safety_state` helper (pure function, tested in isolation). Follow-ups (tracked, non-blocking): FU.4 K4 custom-command popup, FU.5 HoldConfirm 1 s for emergency button.

Skill patterns: Bento + Executive (smua/smub readouts) + DataDense (controls).
Functionally complete in legacy for structured control; this is primarily
visual modernization of per-channel and A+B control surfaces. A visible
custom-command console was not found in current GUI code.
Preserves: direct Keithley control (targets, limits, per-channel and A+B actions).
Additional scope (Phase 0 K4 decision): include "Custom command" popup as NEW feature.
Popup contents:
- Catalog list of common Keithley TSP/SCPI commands (curated, ~10-20 entries with descriptions)
- Free-text QLineEdit for arbitrary command input
- Send button → `ZmqCommandWorker` with new `keithley_raw_command` payload (engine command
  to be added; verify backend support before Phase II.6 starts)
- Response display area (read-only `QPlainTextEdit`, scrollable, last N responses)
- Accessible from a small "Команды..." button in KeithleyOverlay header
This is NEW feature, not preserve. Estimate impact: +1 medium task within block.
Estimate: 1 medium block.

#### Block II.7 — CalibrationOverlay

**Status:** ⬜ NOT STARTED.

Skill patterns: Drill-Down (Setup → Acquisition → Results) + DataDense.
Three-mode QStackedWidget remains the right structural target, but this is
not wrap-only work: the visible export/apply controls in legacy source are
currently unwired and Phase II.7 must connect them to real export/apply
backends as part of the rebuild.
Preserves: K3 CalibrationFitter pipeline and the visible export/apply workflow surface.
Estimate: 1 medium block.

### LOW priority — combined or folded

#### Block II.8 — InstrumentsOverlay + SensorDiag popover

**Status:** ⬜ NOT STARTED.

Combined block:
- InstrumentsOverlay: per-instrument status cards (theme tokens wrap)
- SensorDiag: folded into right-click popover on dashboard sensor cell
  (per Strategy Q4 resolution — eliminates separate tab, solves P1 for diag)
Estimate: 1 medium block (combined).

### ExperimentOverlay v3 visual rebuild

#### Block II.9 — ExperimentOverlay v3

**Status:** ⚠️ PARTIAL — functional parity shipped in B.8.0.2 (`968e995`). Visual primitives-based rebuild pending. Ergonomic fixes landed 2026-04-18: full phase names in stepper (`1850482`), conditional hide of nav buttons when unavailable (`2d6edc7`), × close button removed to reinforce primary-view semantics (`b0b460b`), regression guards (`19993ce`). B.5.x PhaseAwareWidget integration (`468b964`, `a514b69`) also contributes here.

Apply Phase I primitives to existing B.8.0.2 functional code.
Functional logic preserved, visual rebuild only.
Position deferred to last block of Phase II — primitives are mature
by then, applied to most-iterated overlay.
Additional scope (Phase 0 K7 decision): subtle highlight on suggested-next-phase pill
in `PhaseStepper` when phase_detector confidence exceeds threshold (threshold TBD in spec).
Visual: outline color shift on the pill matching the detected phase, no animation.
Tooltip explains "Detected phase based on temperature/pressure trends".
Source data: `analytics/phase_detector/detected_phase` +
`analytics/phase_detector/phase_confidence`.
Estimate: 1 medium block.

**Phase II deliverable:**
- 9 overlays + 1 popover built on primitives
- Visual consistency across all surfaces
- Each overlay ~150-300 lines (vs current 500-1700)
- Test coverage maintained or improved

---

## Phase III — Polish + Deploy

### Block III.1 — Shift Handover Surface

**Solves:** P3 (handovers устные → built into UI).

New widget: `ShiftHandoverPanel` accessible from TopWatchBar.
Shows: что произошло за последние X часов (recent log entries highlighting
critical events), current state summary, suggested handover notes
(auto-extracted phase transitions, alarms, manual operator notes).

Designed for end-of-shift workflow: operator click → одна короткая запись
которая captures essential context для следующей смены.

**Estimate:** 1 medium block.

### Block III.2 — Notifications Audit

**Solves:** P7 (no notifications when away).

Audit existing Telegram bot integration. Verify all critical events trigger
notifications:
- All alarm threshold crossings
- All fault state transitions
- Source off events
- Optional: phase transition completions (operator preference toggle)

Add what's missing. Document notification policy.

**Estimate:** 1 small block.

### Block III.3 — Legacy Code Cleanup

Delete:
- Old `MainWindow` and tab classes
- `experiment_workspace.py` and 9 other legacy widgets
- Dead routes from `engine.py` if any
- Deprecated CSS / theme files

**Critical:** verify no functionality lost. Cross-reference §3 preserve list.

**Estimate:** 1 small block.

### Block III.4 — Lab PC Ubuntu Deploy + Calibration

Out-of-scope для chat work. Vladimir does on lab Ubuntu 22.04:
- Install linux-gpib
- Verify all instruments connect
- Font metrics check (Fira loading on Linux может отличаться от Mac)
- Visual review on FHD monitor (where actual operators sit)
- Operator usability test (5 operators, gather feedback)

**Estimate:** 1-2 days lab time.

---

## Estimate summary

| Phase | Blocks | Total architect+CC time |
|-------|--------|-------------------------|
| Phase 0 (Inventory + Audit) | DONE — 4 commits | ~9h CC + 3h architect |
| Phase I (Primitives) | 4 blocks | ~6h CC + 3h architect |
| Phase II (Apply ×9) | 9 blocks | ~14h CC + 9h architect |
| Phase III (Polish) | 4 blocks | ~6h CC + 3h architect + lab time |
| **Remaining** | **17 blocks** | **~26h CC + ~15h architect** |

Phase 0 status: COMPLETE.

---

## Decision log

- **2026-04-15** B.8.0.2 commit `968e995` — feature parity ExperimentOverlay completed despite layout still being ugly. Layout fix deferred to Phase II.1.
- **2026-04-15** Strategic shift to "build system once" approach after skill deep-dive identified composable patterns.
- **2026-04-15** Vladimir validated all 7 pain points (P1-P7) and the preserve list as planning input. Later code verification narrowed two preserve claims: K4 custom-command surface was not found in GUI, and K7 currently exists as background analytics without a verified GUI suggestion surface.
- **2026-04-16** Phase 0.1 — Legacy Inventory batch 1 completed. Tabs: Обзор (1729 LOC), Источник мощности (586 LOC), Аналитика (934 LOC). Reports at docs/legacy-inventory/. Total 3249 LOC inventoried. Key findings: (1) Overview almost entirely superseded by new dashboard — only ML prediction curve overlay unique. (2) Keithley functionally complete, rebuild is visual-only. (3) Analytics is LEAST covered by new surfaces — highest priority rebuild for Phase II.
- **2026-04-16** Phase 0.2 — Legacy Inventory batch 2 completed. Tabs: Теплопроводность (1068 LOC), Алармы (378 LOC), Служебный лог (171 LOC). Reports at docs/legacy-inventory/. Total 1617 LOC inventoried. Key findings: (1) Conductivity has embedded auto-measurement state machine with min_wait safety guard — must preserve timing logic carefully. (2) Alarms panel is structurally simple (two tables + ACK buttons) but P2 only partially solved by TopWatchBar badge. (3) Operator Log is K1-critical for shift handovers — QuickLogBlock covers only quick entry, full overlay needed.
- **2026-04-16** Phase 0.3 — Legacy Inventory batch 3 completed (FINAL). Tabs: Архив (529 LOC), Калибровка (499 LOC), Приборы (308 LOC), Датчики-диагностика (211 LOC). Phase 0 complete: 10 files inventoried, 6413 LOC total. Key findings: (1) Archive has rich filtering + detail pane + report regeneration — full rebuild needed for K2. (2) Calibration has clean 3-mode QStackedWidget architecture — Wrap approach viable. (3) Instruments + SensorDiag are low-priority (operators check only on problems).
- **2026-04-16** Phase 0 Codex audit completed. Verdict: FIX FIRST. 7 HIGH + 9 MEDIUM issues. Report: docs/phase-ui-1/phase_0_audit_report.md.
- **2026-04-16** Phase II reordered: HIGH (Analytics/Archive/OperatorLog) first, MEDIUM (Alarm/Conductivity/Keithley/Calibration) middle, LOW (Instruments+SensorDiag combined) last. ExperimentOverlay v3 visual rebuild moved to II.9 (after primitives mature).
- **2026-04-16** Preserve features verified. K7 = EXISTS+ENGINE-ONLY (root plugin present, no GUI consumer found). K6 HDF5/Excel = EXISTS+LOCATED in legacy File menu. K4 custom commands = NOT FOUND IN GUI. AlarmOverlay (II.4) demoted from HIGH to MEDIUM because badge already routes into existing AlarmPanel. Calibration overlay (II.7) scope clarified: export/apply buttons exist but are unwired, so real work includes connecting them, not only visual wrap.
- **2026-04-16** Phase 0 product decisions applied:
  - K4: NEW feature popup (custom-command catalog + input + send + response) added to Phase II.6 KeithleyOverlay scope
  - K7: phase detector hints wired to Phase II.1 Analytics overlay (tile) + Phase II.9 ExperimentOverlay v3 (suggested-next-phase pill highlight)
  - K6: global CSV/HDF5/Excel exports migrated to Phase II.2 Archive overlay buttons; legacy File menu can be removed in Phase III.3 cleanup
  - Bell emoji removed from operator-facing GUI text (UX polish)
- **2026-04-16** Phase I.1 — Overlay Design System primitives implemented.
  ModalCard + DrillDownBreadcrumb + BentoGrid + visual showcase.
  Located at `src/cryodaq/gui/shell/overlays/_design_system/`.
  Tests: 1063 → 1085. Ready for Phase I.2 (content tiles).
- **2026-04-16** Phase I.1 shell alignment batch (A.1-A.6) — ToolRail (`d2ccb37`), TopWatchBar (`f4146a9`), BottomStatusBar (`4ac620f`), PhaseStepper active ACCENT→STATUS_OK (`05f27d0`), ModalCard focus trap + restoration (`6010a07`), BentoGrid 12→8 columns + overlap validation (`8a8d189`). Group 1 follow-up `e558fd5`.
- **2026-04-16** Safety A1 fixes — Latin T12 interlock description corrected and `_fault()` re-entry guard added (`eb267c4`). See PROJECT_STATUS §Invariants 18.
- **2026-04-16** CI / lint hygiene — 587 ruff errors cleaned (`d8ec668`); CI install upgraded to `.[dev,web]` so FastAPI/starlette tests run (`1e824a7`).
- **2026-04-16** Phase II B.5.x PhaseAwareWidget batch — mode badge Эксперимент/Отладка colors aligned (`468b964`), centralized plot styling with chart-tokens (`a514b69`). Contributes to II.9 functional polish.
- **2026-04-16** Block B.6 — ExperimentCard dashboard tile (`8b3a453`). Dashboard composition, not an overlay rebuild — no direct II.X mapping.
- **2026-04-17** Block B.7 — Keithley v2 dual-channel overlay shipped (`920aa97`) as mode-based surface at `src/cryodaq/gui/shell/overlays/keithley_panel.py`. Visual-only rebuild. **Known regression vs v1:** 0 plots (v1 had 4 pyqtgraph plot widgets), no P-target control, no A+B actions, no debounced spin controls. K4 custom-command popup NOT shipped. Maps to II.6 PARTIAL — scope to be reopened as a second block. Legacy regression documented in `docs/legacy-inventory/keithley.md`.
- **2026-04-17** Block B.8 → B.8 revision 2 — AnalyticsPanel shipped first as ModalCard overlay (`9a089f9`), Codex data-flow adapter follow-up (`53232ea`), then architecturally corrected to **AnalyticsView primary-view QWidget** (spec `3bb0f2b`, implementation `860ecf3`) at `src/cryodaq/gui/shell/views/analytics_view.py`. Plot-dominant layout (QVBoxLayout + QHBoxLayout + fixed-height chrome strips + direct pyqtgraph wrapping) bypasses Phase I.2/I.3 primitives deliberately. Primary-view vs modal-overlay audit: `a5494ee`. Maps to II.1 COMPLETE. Non-blocking follow-ups: actual-trajectory publisher, R_thermal publisher, VacuumTrendPanel design-system alignment.
- **2026-04-17** Architectural decision — AnalyticsView shipped without Phase I.2/I.3 primitives. Plot-dominant primary views don't benefit from BentoGrid composition; data-dense views (Archive II.2, OperatorLog II.3, Calibration II.7) will still benefit from the primitives library when it's built. The "primitives-first" strategy is softened to "primitives where structurally useful".
- **2026-04-18** Infrastructure polish — force Fusion style + dark palette globally for Linux deployment parity (`fcc08c0`); TopWatchBar transparent separators + heater removal (`041b1bb`); compact pressure format + RU debug-mode error + defaults (`4d3fff8`); bridge subprocess SUB subscription reliability — connect first + bytes subscription (`d0dbdfc`).
- **2026-04-18** Runtime theme switcher — shipped. `theme.py` now reads tokens from YAML packs via `_theme_loader` (`ecd447a`); legacy hardcoded overrides stripped from 9 `apply_panel_frame` callsites (`e52b17b`); 5 additional theme packs bundled (`9ac307e`) — total 6 packs at `config/themes/` (`default_cool`, `warm_stone`, `anthropic_mono`, `ochre_bloom`, `taupe_quiet`, `rose_dusk`); Settings → Тема menu with `os.execv` restart (`77ffc93`); operator manual + CHANGELOG (`903553a`). Status palette (STATUS_OK, WARNING, CAUTION, FAULT, INFO, STALE, COLD_HIGHLIGHT) locked across all packs. Not in original roadmap — infrastructure landing. Palette tuning follow-ups tracked in `HANDOFF_THEME_PALETTES.md`.
- **2026-04-18** ExperimentOverlay B batch polish — full phase names in stepper (`1850482`), nav buttons hidden when unavailable (`2d6edc7`), × close button removed to reinforce primary-view semantics (`b0b460b`), regression guards (`19993ce`). Contributes to II.9 PARTIAL; visual primitives-based rebuild still deferred.
- **2026-04-18** Infrastructure: IPC/REP hardening — 10-commit architectural hardening of the engine ↔ GUI command plane after a production wedge revealed the REP task crashing silently with engine stderr swallowed by `DEVNULL`. Commits: `5299aa6` (bridge SUB drain + CMD forward split), `f5b0f22` (data-flow watchdog independent of heartbeat), `a38e2fa` (`log_get` routed to dedicated read executor), `913b9b3` (separate bridge heartbeat and data flow), `2b1370b` (bridge sockets moved to owner threads), `abfdf44` (bounded transport disconnect recovery), `81e2daa` (legacy alarm count through MainWindow), `3a16c54` (web sqlite close on errors), `ba20f84` (test isolation for stale reply consumers), `27dfecb` (REP task supervision with auto-restart + per-handler 2.0s timeout envelope + 1.5s inner wrappers for `log_get`/`experiment_status` + inner TimeoutError preservation + engine subprocess stderr persisted to `logs/engine.stderr.log` via RotatingFileHandler 50MB × 3 with handler lifecycle surviving engine restarts on Windows). Two Codex review rounds. Final verdict PASS at `27dfecb`. Residual risk documented in-code at `engine.py:1328`: `asyncio.wait_for(asyncio.to_thread(...))` cancels the await but not the worker thread; REP is protected by the outer envelope, inner wrapper gives faster client feedback only.
- **2026-04-18** Block II.6 — Keithley overlay rewritten from scratch (`36463f4` → `96adf5a` after Codex FAIL + amend). Shell overlay now matches engine power-control API (`p_target + v_comp + i_comp`); mode-based B.7 semantics retired. Codex initial FAIL flagged that shell never invoked `set_connected` / `set_safety_ready` — overlay opened in defaults and stayed there. Post-review amendment added `_tick_status` mirror + safety dispatch + `_ensure_overlay("source")` replay + pure `_map_safety_state` helper. Legacy v1 marked DEPRECATED.
- **2026-04-19** **Host Integration Contract pattern codified.** II.6 post-review revealed a systemic risk: overlays with public push setters are useless if `MainWindowV2` never calls them — unit tests pass while production is broken. Three mandatory hook points for every overlay with push setters: (a) `_tick_status()` mirror for `set_connected(bool)`; (b) `_dispatch_reading()` state sinks for stateful readings (safety state, experiment status, finalized events); (c) `_ensure_overlay()` replay on lazy open so first paint is correct. Both overlay unit tests AND host integration tests (`tests/gui/shell/test_main_window_v2_<block>_wiring.py`) required — integration tests exercise `MainWindowV2` entry points, not setters in isolation.
- **2026-04-19** Block II.3 — OperatorLog overlay shipped (`f18c1bf` → `9676acc` after Codex amend). Full-featured journal surface with day-grouped timeline, filter chips (all / current / 8h / 24h), client-side text/author/tag filters with 250 ms debounce, composer with tag normalization + experiment binding, optimistic prepend on `log_entry` success using engine's returned entry payload. Host Integration Contract followed per II.6 codification. Codex FAIL flagged residual DS violations (`TEXT_DISABLED` in disabled-state QSS; `STATUS_INFO` chip border) — amended to `MUTED_FOREGROUND` and `BORDER_SUBTLE` per DS v1.0.1. Legacy v1 widget marked DEPRECATED.
- **2026-04-19** PROJECT_STATUS + roadmap synced to HEAD `9676acc` (II.6 + II.3 closed; II.2 ArchiveOverlay next; test baseline 1321).

---

## Phase 0 Summary

All 10 legacy components inventoried (9 tabs + 1 embedded diagnostic panel).
Total LOC documented: 6413.
ZMQ commands cataloged: 24.
Reports at: docs/legacy-inventory/ (10 files).

### Coverage assessment by Phase II priority

**HIGH priority rebuild** (operator value, currently uncovered or critical):
- Analytics (934 LOC) — LEAST covered by new surfaces, highest daily usage
- Archive (529 LOC) — K2-critical, zero coverage in new UI
- Operator Log (171 LOC) — K1-critical for shift handovers, QuickLogBlock partial only

**MEDIUM priority rebuild** (functional, embedded complexity):
- Alarms (378 LOC) — P2 already solved for badge→panel routing; rebuild is visual modernization + acknowledge-workflow polish
- Conductivity (1068 LOC) — auto-measurement state machine, K6 export
- Keithley (586 LOC) — direct control complete; custom-command surface not found in current GUI
- Calibration (499 LOC) — K3-critical but 1-2x/year; visible export/apply controls exist but wiring is incomplete

**LOW priority rebuild** (mostly superseded by new dashboard):
- Overview (1729 LOC) — almost entirely covered by B.1-B.7 dashboard
- Instruments (308 LOC) — checked only on problems
- Sensor Diagnostics (211 LOC) — fold into sensor grid popover (Q4 resolution)

### Pain point coverage status

After Phase 0 + B.8.0.2:
- P1 ambient awareness: SOLVED by dashboard (B.1-B.7)
- P2 alarm visibility: PARTIAL — badge already opens AlarmPanel overlay, but visual modernization and ack-workflow polish remain
- P3 shift handover: NOT SOLVED — needs Operator Log overlay + Phase III.1
- P4 form repetition: SOLVED for experiment create (B.8.0.2 autocomplete)
- P5 phase elapsed: SOLVED in TopWatchBar + B.8.0.2 phase pills
- P6 plot co-location: PARTIAL — temp+pressure on dashboard, Analytics overlay needed
- P7 notifications: PARTIAL — Telegram exists, audit needed Phase III.2

### Preserve features verified status

After Phase 0 audit + fix + verification:
- K1 (service log): ANCHORED in `operator_log.md` (full surface)
- K2 (archive): ANCHORED in `archive.md` (full surface)
- K3 (calibration): ANCHORED in `calibration.md` (3-mode workflow); export/apply buttons exist but are unwired (Phase II.7 must connect them)
- K4 (Keithley custom commands): NOT FOUND IN GUI. Direct Keithley control is anchored, but custom-command input was not located in legacy GUI source.
- K5 (plot zoom/pan): ANCHORED in `overview.md`, `analytics.md`, `conductivity.md`, `keithley.md`
- K6 (export CSV/HDF5/Excel): CSV anchored in `conductivity.md`; HDF5 + Excel exist in legacy `MainWindow` File menu, outside the 10 audited tab inventories
- K7 (phase detector): EXISTS+ENGINE-ONLY. Root-level plugin exists and publishes analytics metrics, but no GUI consumer / suggestion surface is currently wired.

Preserve features at risk of being lost:
- K4 custom-command surface — current preserve claim is not backed by GUI code
- K7 GUI suggestion surface — analytics plugin exists, but visible UI integration is not present

---

## How to use this roadmap in future chat sessions

1. **First action in any new chat:** read `docs/ui_refactor_context.md` then this file.
2. Identify which block is next (current state in Decision log).
3. Block specs are written architect-by-architect, not pre-written все 18.
4. Each block spec must:
   - Reference pain point (§2) it solves OR feature (§3) it preserves
   - List skill patterns used (Bento, Executive, etc)
   - Include Codex audit step
5. After block completes — update Decision log with commit SHA + Vladimir's visual review note.
