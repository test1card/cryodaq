# CryoDAQ Phase UI-1 v2 — Roadmap

**Status:** Living roadmap. Reflects current strategy as of B.8.0.2 commit `968e995`.

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

### Block: Legacy Inventory Audit (9 tabs)

Read-only CC block, аналог того что был сделан для ExperimentWorkspace.
Cuts uncertainty в design decisions. Без этого следующие overlay rebuilds
будут blind.

**Output:** 9 markdown reports в `docs/legacy-inventory/`.

**Estimate:** ~6h CC work (single large block, или 3 medium blocks по 3 tabs).

**Spec deliverable:** Architect writes one spec, CC executes. Template
готов — copy structure from `/tmp/legacy_experiment_workspace_inventory.md`.

**Success criteria:**
- All 9 inventories produced
- Each lists: layout, fields, ZMQ commands, signals, comparison к B.8 patterns
- Updated §1 of `ui_refactor_context.md`

---

## Phase I — Overlay Design System (Primitives)

**Goal:** One-time investment в reusable composition primitives. 

**Solves pain points:** P1 (consistent UX reduces cognitive load), implicit via consistency.

**Preserves:** все K1-K7 — primitives are content-agnostic, не trump existing functionality.

### Block I.1 — Modal Card Shell + Drill-Down Navigation

Skill patterns: **Drill-Down Analytics**, **Swiss Modernism 2.0** (12-col grid).

Primitives:
- `ModalCard` — backdrop dim + centered card (1100px max width, 80vh max height)
- 3 close mechanisms (ESC + × + backdrop click)
- `DrillDownBreadcrumb` — sticky top bar «← Дашборд / <Overlay name>»
- 12-column grid layout container (`BentoGrid`)

Tests + visual showcase HTML page (Vladimir reviews before applying).

**Estimate:** 1 medium block (~2h CC).

### Block I.2 — Bento Tile Primitives

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

Order chosen для max value early: experiment first (already broken visually),
then highest-traffic, then specialized.

### Block II.1 — ExperimentOverlay v3 (visual rebuild on primitives)

Functional code from B.8.0.2 preserved. Layout reшается через BentoGrid с Executive KPI row + dominant Phase tile + Card+Хроника tiles + footer.

**Solves:** P1 (better hierarchy), validates Phase I design system.

**Estimate:** 1 medium block (~2h).

### Block II.2 — KeithleyOverlay rebuild

Skill patterns: Bento + Executive (smua/smub readouts) + DataDense (controls).

Bento: smua readout tile + smub readout tile + controls tile + safety tile + custom command tile (preserves K4).

**Estimate:** 1 medium block.

### Block II.3 — AnalyticsOverlay rebuild

Skill patterns: Bento + ChartTile + DataDense.

Bento: cooldown predictor tile + conductivity panel + calibration panel + correlated trends.

Preserves K5 (zoom/pan plots).

**Estimate:** 1 medium block.

### Block II.4 — Operator Log Overlay rebuild

Standalone log overlay (отдельно от ХРОНИКА column в ExperimentOverlay).

Skill patterns: Drill-Down + DataDense + filter sidebar.

Preserves K1 (full log access, filter, search, export).

**Estimate:** 1 small block.

### Block II.5 — Archive Overlay rebuild

Skill patterns: Drill-Down + Bento (experiment cards) + DataDense (details).

Preserves K2 (full archive functionality, K6 export). Browse list → detail card → export button.

**Estimate:** 1 medium block.

### Block II.6 — Calibration Overlay rebuild

Skill patterns: Drill-Down (Setup → Acquisition → Results steps) + DataDense.

Preserves K3 (CalibrationFitter pipeline, three modes).

**Estimate:** 1 medium block.

### Block II.7 — Sensor Diagnostics + Instrument Status Overlays

Two related overlays. Bento with sensor health tiles + instrument status tiles.

Real-Time Monitoring pattern (live indicators no pulse).

**Estimate:** 1 medium block (combined).

### Block II.8 — Conductivity Overlay rebuild

Skill patterns: Drill-Down (auto-measurement workflow) + ChartTile + DataDense.

Preserves K7 phase detector integration.

**Estimate:** 1 medium block.

### Block II.9 — Alarm Overlay rebuild

Skill patterns: Drill-Down + DataDense (alarm rules table).

Preserves alarm rule editing, history. **Critical**: alarm visibility (P2) уже
solved через persistent badge in TopWatchBar — overlay = drill-down details.

**Estimate:** 1 small block.

**Phase II deliverable:**
- All 9 overlays built on primitives
- Visual consistency across all surfaces
- Each overlay ~150-300 lines (vs current 500-900)
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
| Phase 0 (Inventory) | 1 large block | ~6h CC + 1h architect |
| Phase I (Primitives) | 4 blocks | ~6h CC + 3h architect |
| Phase II (Apply ×9) | 9 blocks | ~14h CC + 9h architect |
| Phase III (Polish) | 4 blocks | ~6h CC + 3h architect + lab time |
| **Total** | **18 blocks** | **~32h CC + ~16h architect** |

Spread over realistic calendar: 4-6 weeks at current cadence (1-3 blocks per week).

---

## Decision log

- **2026-04-15** B.8.0.2 commit `968e995` — feature parity ExperimentOverlay completed despite layout still being ugly. Layout fix deferred to Phase II.1.
- **2026-04-15** Strategic shift to "build system once" approach after skill deep-dive identified composable patterns.
- **2026-04-15** Vladimir validated all 7 pain points (P1-P7) and all 7 preserve features (K1-K7). All entries in context doc are real, not architect speculation.
- **2026-04-16** Phase 0.1 — Legacy Inventory batch 1 completed. Tabs: Обзор (1729 LOC), Источник мощности (586 LOC), Аналитика (934 LOC). Reports at docs/legacy-inventory/. Total 3249 LOC inventoried. Key findings: (1) Overview almost entirely superseded by new dashboard — only ML prediction curve overlay unique. (2) Keithley functionally complete, rebuild is visual-only. (3) Analytics is LEAST covered by new surfaces — highest priority rebuild for Phase II.
- **2026-04-16** Phase 0.2 — Legacy Inventory batch 2 completed. Tabs: Теплопроводность (1068 LOC), Алармы (378 LOC), Служебный лог (171 LOC). Reports at docs/legacy-inventory/. Total 1617 LOC inventoried. Key findings: (1) Conductivity has embedded auto-measurement state machine with min_wait safety guard — must preserve timing logic carefully. (2) Alarms panel is structurally simple (two tables + ACK buttons) but P2 only partially solved by TopWatchBar badge. (3) Operator Log is K1-critical for shift handovers — QuickLogBlock covers only quick entry, full overlay needed.
- **2026-04-16** Phase 0.3 — Legacy Inventory batch 3 completed (FINAL). Tabs: Архив (529 LOC), Калибровка (499 LOC), Приборы (308 LOC), Датчики-диагностика (211 LOC). Phase 0 complete: 10 files inventoried, 6413 LOC total. Key findings: (1) Archive has rich filtering + detail pane + report regeneration — full rebuild needed for K2. (2) Calibration has clean 3-mode QStackedWidget architecture — Wrap approach viable. (3) Instruments + SensorDiag are low-priority (operators check only on problems).

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
- Alarms (378 LOC) — P2 partially solved (badge), acknowledge workflow uncovered

**MEDIUM priority rebuild** (functional, embedded complexity):
- Conductivity (1068 LOC) — auto-measurement state machine, K6 export
- Keithley (586 LOC) — functionally complete, visual-only modernization
- Calibration (499 LOC) — K3-critical but 1-2x/year, clean Wrap target

**LOW priority rebuild** (mostly superseded by new dashboard):
- Overview (1729 LOC) — almost entirely covered by B.1-B.7 dashboard
- Instruments (308 LOC) — checked only on problems
- Sensor Diagnostics (211 LOC) — fold into sensor grid popover (Q4 resolution)

### Pain point coverage status

After Phase 0 + B.8.0.2:
- P1 ambient awareness: SOLVED by dashboard (B.1-B.7)
- P2 alarm visibility: PARTIAL — badge shows count, ack workflow needs overlay
- P3 shift handover: NOT SOLVED — needs Operator Log overlay + Phase III.1
- P4 form repetition: SOLVED for experiment create (B.8.0.2 autocomplete)
- P5 phase elapsed: SOLVED in TopWatchBar + B.8.0.2 phase pills
- P6 plot co-location: PARTIAL — temp+pressure on dashboard, Analytics overlay needed
- P7 notifications: PARTIAL — Telegram exists, audit needed Phase III.2

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
