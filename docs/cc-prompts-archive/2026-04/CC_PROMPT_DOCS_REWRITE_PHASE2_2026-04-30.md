# Docs Rewrite — Phase 2 (2026-04-30)

> Phase 1 complete (commit `6c5a6d8`). 23 actionable docs identified.
> Architect (web Claude + Vladimir) provided answers to all 11 OQ.
> This prompt encodes those decisions and drives Phase 2 execution.

---

## 0. Operating posture

- **Architect synchronously available** during this session.
- **Architect-approved structure** for every rewrite below — no
  improvising on document shape.
- **Truth source authoritative:** ROADMAP.md, CHANGELOG.md, src/,
  pyproject.toml, vault frontmatter. NOT doc-to-doc references
  (which are themselves stale).
- **NEVER DELETE.** Archives via `git mv` to preserve history.

---

## 1. Architect decisions per OQ

| OQ | Decision |
|---|---|
| #1 UI blocks B.3-B.6 | All 3 zones now LIVE (sensor grid, phase widget, quick log). README must reflect: dashboard 5 zones working, no placeholders. |
| #2 Legacy MainWindow | Migration plan B.7 CLOSED. Legacy remains as permanent fallback (not in-progress migration). README must reflect: "Phase III complete v0.40.0; legacy MainWindow remains as permanent fallback." |
| #3 first_deployment.md | ARCHIVE. Move to `docs/handoffs-archive/2026-03/first_deployment-historical.md`. Don't rewrite. |
| #4 architecture.md | ARCHIVE old + WRITE NEW. Old → `docs/handoffs-archive/2026-03/architecture-v0.13-historical.md`. New `docs/architecture.md` from scratch reflecting v0.43.0. |
| #5 DOC_REALITY_MAP.md | RETIRE. Move to `docs/handoffs-archive/2026-04/DOC_REALITY_MAP.md`. PROJECT_STATUS + vault subsystem notes supersede. Add note in PROJECT_STATUS pointing to vault as new source. |
| #6 SUPERSEDED docs (3) | ARCHIVE. Move all 3 to `docs/handoffs-archive/2026-04/ui-superseded/`. Banners stay intact. |
| #7 Vault per-feature vs in-place | IN-PLACE EXTENSION. 7 edits, no new notes. |
| #8 B1 frontmatter fix | Trivial: status `OPEN` → `closed (H5 fix shipped v0.39.0 2026-04-27)`. Fix body line about "blocks v0.34.0 tag" to closure note. |
| #9 CLAUDE.md "0.13.0" | Rewrite version-agnostic ("see pyproject.toml" pointer). |
| #10 safety-operator F24 | Add F24 section: how to acknowledge tripped interlock via ZMQ command. 1-2 paragraphs. |
| #11 alarms_tuning_guide | Targeted additions only (config keys for F20/F21/F22). No full rewrite. |

---

## 2. Phase 2 work order

19 docs in priority order. Execute sequentially. Each section
specifies: read scope, output structure, commit grouping.

Group commits by doc family (one commit per group, not per doc):

- **Group I:** Top-level user-facing (README, PROJECT_STATUS, CLAUDE.md)
- **Group II:** docs/ refresh (NEXT_SESSION, REPO_AUDIT_REPORT, alarms_tuning_guide, safety-operator if updated, new architecture.md)
- **Group III:** docs/ archive (first_deployment, old architecture.md, DOC_REALITY_MAP, 3 SUPERSEDED)
- **Group IV:** Vault refresh (Versions, F-table, 7 subsystem in-place, B1 frontmatter, What is CryoDAQ, Architecture overview)

Push after each group lands.

---

## 3. Group I — Top-level user-facing

### 3.1 README.md — full rewrite

Current state: STALE-BOTH (claims v0.33.0, missing F10/F19-F25, UI section with placeholder claims).

Structure (architect-approved):

```markdown
# CryoDAQ

Software stack for cryogenic test laboratory data acquisition,
control, and analysis. Replaces a 3-year-old LabVIEW VI used to
drive instruments + push email alerts. Adds: scripted FSM-driven
campaigns, automated calibration with multi-format export,
auto-generated DOCX reports, role-filtered Telegram alerts,
sensor-anomaly detection, plugin-based analytics, regression test
suite (~1970 tests).

## Status

- **Latest release:** v0.43.0 (2026-04-30)
- **Master:** c44c575
- **Tests:** ~1970 passing
- **Production status:** stable; LabVIEW VI fully replaced

## Architecture overview

Three runtime processes:

- `cryodaq-engine` — headless. Drives instruments, runs safety
  manager FSM, evaluates alarms + interlocks, persists data,
  serves GUI commands via ZMQ.
- `cryodaq-gui` — Qt desktop client. Connects via ZMQ. Restartable
  without stopping data acquisition.
- `cryodaq.web.server:app` — optional FastAPI monitoring dashboard.

Plus Windows launcher: `cryodaq`.

Data flow: instrument → driver → engine → SQLiteWriter → DataBroker
→ {SafetyBroker, GUI, Telegram, archive}.

## Hardware (currently supported)

- 3× LakeShore 218S (GPIB) — 24 temperature channels
- Keithley 2604B (USB-TMC) — dual-channel SMU (smua + smub)
- Thyracont VSP63D (RS-232) — 1 pressure channel

## Implemented workflows

End-to-end functional as of v0.43.0:

- **Experiment FSM:** 6-state lifecycle (idle → cooldown →
  measurement → warmup → disassembly → idle, plus aborted)
- **Cryo-vacuum campaign automation:** template-driven scripted
  runs from start to finalization
- **Calibration v2:** continuous SRDG capture during calibration
  experiments; post-run pipeline (extract → downsample →
  multi-zone Chebyshev fit); export to `.cof` (raw Chebyshev
  coefficients) / `.340` / JSON / CSV; import from `.340` / JSON;
  runtime apply with global / per-channel policy
- **Auto-report generation:** template-defined sections;
  guaranteed `report_editable.docx`; best-effort PDF via
  `soffice` / LibreOffice
- **Telegram alerts:** role-filtered. Operators get full alarm
  stream; managers get curated subset queryable on-demand.
- **Sensor diagnostics → alarm pipeline:** MAD-based outlier +
  cross-channel correlation drift detection. Sustained anomaly
  publishes alarm: warning at 5 min, critical at 15 min, auto-clear
  on recovery. Aggregation for simultaneous events; configurable
  per-channel escalation cooldown.
- **Alarm engine v2:** threshold / rate / composite / phase-dependent
  rules; hysteresis deadband; severity upgrade in-place; ack/clear
  publish path.
- **Interlocks:** 3 hard-safety rules (cryostat / compressor /
  detector). Trip transitions to TRIPPED state. Operator
  acknowledges via `interlock_acknowledge` ZMQ command to re-arm.
- **Operator log:** SQLite-backed, GUI + ZMQ access.
- **Experiment templates + lifecycle metadata + artifact archival:**
  per-experiment directory with metadata.json, reports/, optional
  Parquet archive.
- **Plugin architecture:** ABC-based isolation; callback failures
  mark plugin degraded without crashing engine.
- **Housekeeping:** conservative adaptive throttle + retention +
  compression policy.

## GUI

Primary: `MainWindowV2` (Phase III complete as of v0.40.0).

Layout — ambient information radiator for week-long experiments:

- **TopWatchBar** — engine indicator, experiment status, time
  window echo
- **ToolRail** — overlay navigation
- **DashboardView** — 5 live zones:
  1. Sensor grid (temperature + pressure overview)
  2. Temperature plot (multi-channel, clickable legend, time
     window picker)
  3. Pressure plot (compact log-Y)
  4. Phase widget (experiment phase indicator + transition)
  5. Quick log (operator log inline view)
- **BottomStatusBar** — safety state indicator
- **OverlayContainer** — host for analytics + archive overlays

Overlay views (from ToolRail):
- Analytics — phase-aware widgets (W1 temperature trajectory,
  W2 cooldown history, W3 experiment summary). W4 R_thermal
  remains placeholder pending F8 cooldown ML upgrade.
- Archive — past experiments + reports + Parquet exports
- Calibration — capture / fit / export workflow
- Operator log
- Other overlays per ToolRail icons

Legacy `MainWindow` (10-tab shell) remains as **permanent fallback**.
Operators see `MainWindowV2` only. Phase III closed the active
migration plan.

System tray: `healthy / warning / fault` status. `healthy` not
shown without sufficient backend-truth; `fault` set on unresolved
alarms or safety-state `fault` / `fault_latched`.

## Installation

[Same as current README content — Python 3.12+, pip install -e,
extras for dev/web.]

## Running

[Same — cryodaq-engine, cryodaq-gui, cryodaq launcher,
optional uvicorn web. Mock mode via --mock flag.]

## Configuration

Config files (active as of v0.43.0):

- `config/instruments.yaml` — GPIB/serial/USB addresses, LakeShore channels
- `config/instruments.local.yaml` — machine-specific override (gitignored)
- `config/safety.yaml` — SafetyManager FSM timeouts, rate limits, drain
- `config/alarms.yaml` — legacy alarm definitions
- `config/alarms_v3.yaml` — v2 alarm engine rules (threshold/rate/composite/phase)
- `config/interlocks.yaml` — interlock conditions + actions
- `config/channels.yaml` — display names, visibility, groupings
- `config/notifications.yaml` — Telegram bot_token, chat_ids, escalation
- `config/housekeeping.yaml` — throttle, retention, compression
- `config/plugins.yaml` — sensor_diagnostics + vacuum_trend; F20 aggregation_threshold + escalation_cooldown_s
- `config/cooldown.yaml` — cooldown predictor parameters
- `config/shifts.yaml` — shift definitions (GUI)
- `config/experiment_templates/*.yaml` — experiment type templates

`*.local.yaml` overrides base files for machine-specific settings.

## Experiment artifacts

[Same paths as current README — data/experiments/<id>/, calibration/sessions/,
calibration/curves/.]

## Reports

[Same renderers list. DOCX guaranteed, PDF best-effort.]

## Keithley TSP

[Same — `tsp/p_const.lua` is draft, NOT loaded on instrument.
Host-side P=const feedback in `keithley_2604b.py`.]

## Project structure

```
src/cryodaq/
  analytics/     # calibration fitter, cooldown, plugins, vacuum trend
  core/          # safety, scheduler, broker, alarms, interlocks, sensor_diagnostics, experiments, zmq_bridge
  drivers/       # transport + instrument drivers
  gui/           # MainWindowV2, dashboard, overlays, legacy widgets
  reporting/     # template-driven DOCX generator
  storage/       # SQLite, Parquet, CSV, HDF5, XLSX
  web/           # FastAPI monitoring
tsp/             # Keithley TSP scripts (draft, not loaded)
tests/           # ~1970 tests
config/          # YAML configs
```

## Tests

Per-module:
```bash
python -m pytest tests/core -q
python -m pytest tests/storage -q
python -m pytest tests/drivers -q
python -m pytest tests/analytics -q
python -m pytest tests/gui -q
python -m pytest tests/reporting -q
```

Run after `pip install -e ".[dev,web]"`. GUI tests need PySide6
and pyqtgraph. Web dashboard needs `.[web]` extra.

## Known limitations

As of v0.43.0:

- **SQLite WAL gate:** engine startup hard-fails on SQLite versions
  in the WAL-reset corruption range [3.7.0, 3.51.3) per F25.
  `CRYODAQ_ALLOW_BROKEN_SQLITE=1` env var bypasses with explicit
  warning. Ubuntu lab PC may have affected version — verify with
  `sqlite3 --version`.
- **Lab Ubuntu PC verification:** v0.39.0 H5 ZMQ fix verified on
  macOS dev only. Ubuntu lab box pending verification.
- **PDF reports:** best-effort only. Guaranteed artifact is DOCX.
- **Runtime calibration policy:** global on/off + per-channel
  policy switch KRDG / SRDG+curve. Conservative fallback to KRDG
  on missing curve / assignment / SRDG / compute error. Live-LakeShore
  behavior requires lab verification.
- **Deprecation warnings:** `asyncio.WindowsSelectorEventLoopPolicy`
  on newer Python versions.

## License + acknowledgments

[Same as current.]
```

Target ≤320 lines.

### 3.2 PROJECT_STATUS.md update

Update header section + metrics + Frontier:

- Header: Date 2026-04-30 (post-v0.43.0); Last commit `c44c575`;
  Tests "~1 970 passed (re-count after v0.43.0 merges)"; Frontier
  "v0.43.0 shipped. F19-F25 ✅ DONE. Open: F26 XS polish (SQLite
  backport whitelist), F19 LOW polish (channel heuristic), Lab
  Ubuntu PC verification, Vault refresh in-progress."
- Metric table: re-count Python files, LOC, test files, test LOC
  from filesystem (`find src/cryodaq -name '*.py' | xargs wc -l`).
  Version: 0.43.0.
- Phase 2d invariants: keep section. If new invariants added since
  2026-04-17 (HF2 _SLOW_COMMANDS expansion, F25 SQLite gate, F22
  in-place severity mutation, F23 measurement timestamp source) —
  add as Phase 2e numbered entries (continuing 19, 20, 21, 22).
- Add note pointing to vault subsystem notes as new doc-reality
  source: "Per-subsystem implementation details: see vault notes
  at `~/Vault/CryoDAQ/10 Subsystems/`. DOC_REALITY_MAP.md retired
  2026-04-30 (in archive)."
- Inventory pointer: "Source of actual repo inventory: this
  document, refreshed per release."

### 3.3 CLAUDE.md package metadata fix

OQ #9: rewrite version-agnostic.

Replace claim "Current package metadata: `0.13.0`" with one of:
- "Current package metadata: see `pyproject.toml`"
- Or remove the version reference entirely if not load-bearing for
  the surrounding sentence

Read full CLAUDE.md, locate the line, apply the minimal fix.

### 3.4 Group I commit

```
git add README.md PROJECT_STATUS.md CLAUDE.md
git commit -m "docs(top-level): refresh to v0.43.0 reality

README.md full rewrite (was v0.33.0 stale through 14 features):
- Status, architecture, hardware accurate to v0.43.0
- Workflows section reflects shipped features through F25
- GUI section: 5 dashboard zones LIVE (sensor grid, phase widget,
  quick log all working post-Phase III closure); legacy MainWindow
  permanent fallback (B.7 migration retired)
- Configuration: F20 plugins.yaml fields documented
- Known limitations: F25 SQLite gate noted

PROJECT_STATUS.md: header (commit/version/tests), metrics
re-counted, Phase 2e invariants added (HF2 + F22 + F23 + F25),
DOC_REALITY_MAP retirement noted with vault pointer.

CLAUDE.md: stale 0.13.0 metadata claim replaced with version-
agnostic pyproject.toml pointer.

Ref: artifacts/docs-audit/2026-04-30/findings.md
Batch: phase-D / docs-audit / Group I
Risk: docs only."

git push origin master
```

---

## 4. Group II — docs/ refresh

### 4.1 docs/NEXT_SESSION.md

Update outstanding items:

- Header: HEAD `c44c575` v0.43.0; tests ~1970
- Move to "Recent completions": ORCHESTRATION v1.3 (A3 shipped),
  multi-model-consultation v1.1 (A2), HF3 docstring (A1), plugin
  disposition (A4), F19-F25 (v0.43.0 merges), T2 calibration
  re-run, calibration session, repo cleanup
- Open work table: F26 (SQLite backport whitelist, XS), F19 channel
  heuristic refinement (LOW), Lab Ubuntu PC verification, Vault
  refresh (in-progress this session), docs audit Phase 2 (this session)
- Where-to-find: ORCHESTRATION.md (v1.3), CHANGELOG.md ([0.43.0]),
  ROADMAP.md (F-row index post-v0.43.0)
- Next probable session items: F26 implementation, F19 polish,
  Lab Ubuntu, article rewrite (B1 anecdote replacement +
  ORCHESTRATION paragraph + retroactive versioning sentence)

### 4.2 docs/REPO_AUDIT_REPORT.md — append v0.43.0 section

Existing 2026-04-30 audit covers v0.42.0. Append new section
"## 2026-04-30 (evening) — post-v0.43.0":

- State: master `c44c575`, tag `v0.43.0`
- Cleanup actions in this audit session: docs rewrite Group I-IV
  (count files), 3 SUPERSEDED docs archived, DOC_REALITY_MAP
  retired, first_deployment.md archived, architecture.md replaced
- Outstanding: Lab Ubuntu, F26 polish, F19 polish, vault refresh
  in-progress

Don't replace the morning section; append.

### 4.3 docs/alarms_tuning_guide.md — F20/F21/F22 additions

OQ #11: targeted additions only.

Add new sections (or extend existing):

- **F20 — Diagnostic alarm aggregation.** Document
  `aggregation_threshold` (plugins.yaml; default 3) and
  `escalation_cooldown_s` (default 120). Behavior: when N>threshold
  channels enter warning/critical in same tick, batched into one
  Telegram message. Critical bypasses cooldown.
- **F21 — Alarm hysteresis deadband.** Document `hysteresis` field
  on alarm rules (alarms_v3.yaml). Behavior: alarm clears only when
  channel value crosses threshold MINUS hysteresis margin. Filters
  to originally-triggering channels (F21 implementation detail).
- **F22 — Severity upgrade.** Behavior: WARNING→CRITICAL on same
  alarm_id (in-place .level mutation, history records
  SEVERITY_UPGRADED event). Operator sees single alarm with severity
  change, not duplicate notifications.

Update header "Обновлён 2026-04-30 после v0.43.0 ship".

### 4.4 docs/safety-operator.md — F24 section

OQ #10: add interlock acknowledge section.

New section "## Interlock acknowledge (F24)":

- When an interlock trips: state TRIPPED, monitoring stops, source
  emergency-off (per existing trip semantics).
- Operator must acknowledge to re-arm: execute
  `interlock_acknowledge` ZMQ command with the interlock name
  parameter. Engine transitions interlock TRIPPED → ARMED;
  monitoring resumes.
- Unknown interlock name → KeyError (no silent failure).
- Acknowledge is idempotent: already-ARMED interlock returns
  successfully without state change.
- Underlying condition must clear before acknowledge — engine does
  not validate, but trip immediately re-fires if condition still
  present.

Update last_updated 2026-04-30.

### 4.5 docs/architecture.md — new write from scratch

OQ #4: archive old, write new.

Old `docs/architecture.md` (v0.13.0, 2026-03-22) → first archive
it (Group III), then write replacement.

New `docs/architecture.md` structure:

```markdown
# CryoDAQ Architecture

**Version:** v0.43.0  
**Date:** 2026-04-30

## Overview
[3-paragraph: what CryoDAQ is, what subsystems exist, how they
talk to each other]

## Process model
[cryodaq-engine + cryodaq-gui + cryodaq.web.server roles]

## Data flow
[instrument → driver → engine → broker → consumers]

## Subsystem map
Pointer to vault subsystem notes (`~/Vault/CryoDAQ/10 Subsystems/`)
as authoritative per-subsystem details. List subsystems briefly:

- safety_manager (FSM)
- alarm_v2 (rule engine)
- interlock (hard safety)
- sensor_diagnostics (anomaly detection + alarm bridge)
- scheduler (cooperative event loop)
- broker (pub/sub)
- zmq_bridge (command plane)
- experiment_manager (lifecycle FSM + persistence)
- storage (SQLite + Parquet)
- reporting (DOCX template engine)
- analytics (calibration fitter, cooldown predictor, plugins, vacuum trend)
- drivers (LakeShore, Keithley, Thyracont + transport adapters)
- gui shell (MainWindowV2, dashboard, overlays)

Per-subsystem details deliberately not duplicated here. See vault.

## Persistence-first invariant
[Brief statement of write-immediate-then-broker pattern]

## SafetyState FSM
[6 states, transitions]

## Configuration
[config files inventory + override pattern]

## Test architecture
[~1970 tests, structure under tests/, fixtures pattern]

## Why these choices
[2-3 paragraphs: trade-offs vs LabVIEW, why Python+asyncio+ZMQ,
where the system DOESN'T fit (real-time DAQ, microsecond control —
explicitly out of scope)]
```

Target 200-300 lines. Authoritative pointer to vault for details.

### 4.6 Group II commit

```
git add docs/NEXT_SESSION.md docs/REPO_AUDIT_REPORT.md \
        docs/alarms_tuning_guide.md docs/safety-operator.md \
        docs/architecture.md
git commit -m "docs(refresh): update operator/architecture docs to v0.43.0

NEXT_SESSION: post-v0.43.0 outstanding items + recent completions.

REPO_AUDIT_REPORT: appended evening v0.43.0 section.

alarms_tuning_guide: F20/F21/F22 config keys documented (aggregation
threshold, escalation cooldown, hysteresis, severity upgrade).

safety-operator: new F24 section on interlock acknowledge ZMQ
command (operator action to re-arm tripped interlock).

architecture.md: full rewrite from scratch (old v0.13.0 archived
in Group III). New version is high-level + subsystem map pointing
to vault notes as authoritative per-subsystem details.

Ref: artifacts/docs-audit/2026-04-30/findings.md
Batch: phase-D / docs-audit / Group II
Risk: docs only."

git push origin master
```

---

## 5. Group III — Archive moves

### 5.1 Setup

```bash
mkdir -p docs/handoffs-archive/2026-03/
mkdir -p docs/handoffs-archive/2026-04/ui-superseded/
```

### 5.2 Moves

```bash
# OQ #3: first_deployment.md → archive
git mv docs/first_deployment.md \
       docs/handoffs-archive/2026-03/first_deployment-historical.md

# OQ #4: old architecture.md → archive (BEFORE writing new one in Group II)
# NOTE: Group II writes the new architecture.md. Sequencing: 
# do Group III BEFORE Group II if you haven't yet, OR do Group III's 
# architecture.md move first then Group II writes new file.
# 
# If Group II already done and new architecture.md is in place, the
# old version is gone — that's fine, we archived nothing because the
# rewrite replaced it. Document this in commit message.
#
# Recommended order: Group III → Group II — archive first, then
# write new architecture.md to replace it.

# (See sequencing note below — execute Group III in this order:)
git mv docs/architecture.md \
       docs/handoffs-archive/2026-03/architecture-v0.13-historical.md

# OQ #5: DOC_REALITY_MAP.md retire
git mv DOC_REALITY_MAP.md \
       docs/handoffs-archive/2026-04/DOC_REALITY_MAP.md

# OQ #6: 3 SUPERSEDED UI docs
git mv docs/UI_REWORK_ROADMAP.md \
       docs/handoffs-archive/2026-04/ui-superseded/UI_REWORK_ROADMAP.md
git mv docs/DESIGN_SYSTEM.md \
       docs/handoffs-archive/2026-04/ui-superseded/DESIGN_SYSTEM.md
git mv docs/PHASE_UI1_V2_WIREFRAME.md \
       docs/handoffs-archive/2026-04/ui-superseded/PHASE_UI1_V2_WIREFRAME.md
```

### 5.3 Archive index

Create `docs/handoffs-archive/2026-04/ui-superseded/README.md`:

```markdown
# UI rework superseded docs (archived 2026-04-30)

These three documents drove the Phase UI-1 v2 rebuild that landed
as MainWindowV2 in v0.33.0 and was finalized through v0.40.0
(Phase III F3 widget wiring).

Archived after Phase III closed and the legacy migration plan
(B.7) was retired (legacy MainWindow remains permanent fallback).

| File | Was at | Banner status |
|---|---|---|
| UI_REWORK_ROADMAP.md | docs/UI_REWORK_ROADMAP.md | SUPERSEDED |
| DESIGN_SYSTEM.md | docs/DESIGN_SYSTEM.md | SUPERSEDED |
| PHASE_UI1_V2_WIREFRAME.md | docs/PHASE_UI1_V2_WIREFRAME.md | SUPERSEDED |

Current UI source of truth: `docs/design-system/`.
Current architecture: `docs/architecture.md`.
```

Update existing `docs/handoffs-archive/2026-04/README.md` if exists
to mention DOC_REALITY_MAP retirement.

### 5.4 Group III commit

```
git add docs/handoffs-archive/
git commit -m "chore(archive): historical + retired docs to handoffs-archive

Archived:
- docs/first_deployment.md (v0.13.0 2026-03-21) → 2026-03/
- docs/architecture.md (v0.13.0 2026-03-22) → 2026-03/ (replacement
  written in Group II)
- DOC_REALITY_MAP.md → 2026-04/ — retired; PROJECT_STATUS + vault
  subsystem notes supersede this function
- docs/UI_REWORK_ROADMAP.md → 2026-04/ui-superseded/
- docs/DESIGN_SYSTEM.md → 2026-04/ui-superseded/
- docs/PHASE_UI1_V2_WIREFRAME.md → 2026-04/ui-superseded/

UI superseded archive index added.

Ref: artifacts/docs-audit/2026-04-30/findings.md OQ #3-#6
Batch: phase-D / docs-audit / Group III
Risk: archive moves only, history preserved via git mv."

git push origin master
```

**Sequencing note:** Group III's `architecture.md` move MUST happen
BEFORE Group II's new architecture.md write. If sequencing concern:
do Group III's archive moves first, THEN Group II's new write +
commit.

---

## 6. Group IV — Vault refresh

Read-write to `~/Vault/CryoDAQ/`. Use Obsidian MCP (`obsidian:*`
tools) — they handle frontmatter and wikilinks correctly.

### 6.1 Vault Versions.md — add v0.42.0 + v0.43.0

Add two rows. Format match existing rows (date, status, scope,
closing commit).

v0.42.0 row:
- Date: 2026-04-29
- Status: ✅ released
- Scope: Safety hotfix HF1 (update_target docstring) + HF2
  (keithley_emergency_off + keithley_stop in _SLOW_COMMANDS)
- Closing commit: `35f2798`

v0.43.0 row:
- Date: 2026-04-30
- Status: ✅ released
- Scope: Overnight sprint (F19-F25, 7 features) + Phase A doc/process
  (HF3 docstring, multi-model-consultation v1.1, ORCHESTRATION v1.3,
  plugin disposition)
- Closing commit: `c44c575`

Update "Current state" section: HEAD `c44c575`, pyproject `0.43.0`.
Set "Next release" line to "Undefined; F26 XS polish on backlog,
then research items F8/F9".

Update last_synced to 2026-04-30.

### 6.2 Vault F-table backlog.md — sync to ROADMAP

Refresh F1-F26 table from current ROADMAP:
- F1, F2, F3, F4, F6, F10, F11, F19, F20, F21, F22, F23, F24, F25 → ✅ DONE
- F5, F7, F15 → blocked
- F8, F9 → research
- F12, F13, F14, F16, F17, F18 → ⬜ NOT STARTED (autonomous)
- F26 → ⬜ NOT STARTED (XS polish, F25 backport whitelist)
- Source: `ROADMAP.md (2026-04-30, post-v0.43.0)`
- last_synced: 2026-04-30

### 6.3 Vault: 7 in-place subsystem extensions

For each, use `obsidian:read_note` then `obsidian:patch_note` (or
write_note if total replacement). Update last_synced: 2026-04-30.

#### Sensor diagnostics alarm.md
Section "## Deferred (F20)" → rename "## Shipped (F20)". Update
content from "deferred — to be implemented" to "shipped v0.43.0:
aggregation_threshold (default 3), escalation_cooldown_s (default
120), critical bypasses cooldown, first notification per channel
never suppressed".

#### Alarm engine v2.md
Add new sections at appropriate position:
- "## Hysteresis deadband (F21, v0.43.0)" — explain
  `_check_hysteresis_cleared()` no longer stub; filters to
  originally-triggering channels via `active_channels` param;
  `evaluate()` signature gained `is_active` + `active_channels`
- "## Severity upgrade (F22, v0.43.0)" — `publish_diagnostic_alarm`
  upgrades WARNING→CRITICAL in-place on same alarm_id;
  AlarmEvent.level mutation safe because frozen=False intentional;
  history records SEVERITY_UPGRADED event
- "## Aggregation + cooldown (F20, v0.43.0)" — engine batches >3
  events into single Telegram message; per-channel cooldown
  prevents oscillation re-firing

#### Interlock engine.md
Add section "## ZMQ acknowledge command (F24, v0.43.0)":
- `interlock_acknowledge` action handler in engine.py
- `acknowledge(name)` transitions TRIPPED → ARMED
- KeyError on unknown name (no silent failure)
- Idempotent on already-ARMED

#### Persistence-first.md
Add section "## SQLite WAL startup gate (F25, v0.43.0)":
- `_check_sqlite_version()` raises RuntimeError on [3.7.0, 3.51.3)
- WAL-reset corruption bug per SQLite official advisory
- Bypass via `CRYODAQ_ALLOW_BROKEN_SQLITE=1` (warning emitted)
- Module-level `_SQLITE_VERSION_CHECKED` flag prevents per-process
  re-check
- Backport whitelist for 3.44.6 / 3.50.7 deferred to F26

#### Safety FSM.md
Add sections:
- "## RateEstimator measurement timestamp (F23, v0.43.0)" —
  `_collect_loop` now uses `reading.timestamp.timestamp()` not
  `time.monotonic()`; queue dequeue time was distorting computed
  rate under backlog
- "## update_target() delayed-update design (HF1 + HF3, v0.42.0+)" —
  in-memory `runtime.p_target` mutation; P=const regulation loop
  in Keithley driver picks up on next poll cycle; convergence
  time depends on slew-rate (≤1 s for small steps, multi-second
  for large steps); HF3 docstring clarifies the convergence
  behavior

#### Analytics view.md
Update W3 ExperimentSummaryWidget entry to add F19 enrichment:
- Channel min/max/mean stats per critical channel (T1..T8 cryostat,
  pressure, Keithley)
- Top-3 most-triggered alarm names
- Clickable artifact links (DOCX, PDF) via QDesktopServices
- limit_per_channel = 50000 (sufficient for ~7-hour experiment at
  0.5 s cadence)
- Channel heuristic: T/Т prefix detection (LOW priority refinement
  deferred)

#### Plugin architecture.md
Add brief section "## F20 config additions (v0.43.0)":
- `plugins.yaml` gained `aggregation_threshold` (default 3) and
  `escalation_cooldown_s` (default 120) for sensor_diagnostics →
  alarm aggregation behavior

### 6.4 Vault B1 ZMQ idle-death.md frontmatter fix

OQ #8: trivial.

Frontmatter `status: synthesized — bug OPEN` → `status: synthesized — closed (H5 fix shipped v0.39.0 2026-04-27)`.

Body line "The single bug that blocks `v0.34.0` tag" → replace with
"This bug was the focus of a 7-day investigation (2026-04-21..27).
Closed via H5 cancellation polling fix in v0.39.0 (2026-04-27).
v0.34.0 was tagged retroactively as part of the 6-tag versioning
chain on 2026-04-27."

Update last_synced: 2026-04-30.

### 6.5 Vault What is CryoDAQ.md + Architecture overview.md

These are 00 Overview notes describing project at high level.

**What is CryoDAQ.md:** refresh feature list to v0.43.0:
- Add F10 sensor diagnostics → alarm pipeline
- Add F19 W3 experiment_summary enrichment
- Add F20-F25 (alarm aggregation, hysteresis, severity upgrade,
  rate estimator timestamp, interlock ZMQ ack, SQLite WAL gate)
- Update last_synced: 2026-04-30

**Architecture overview.md:** add subsystem references:
- F23 RateEstimator measurement timestamp source change
- F24 interlock_acknowledge ZMQ verb
- F25 SQLite startup gate
- Update last_synced: 2026-04-30

### 6.6 Source map regen + build log

After all vault edits:

```bash
python3 ~/Projects/cryodaq/artifacts/vault-build/build_source_map.py
```

Verify 0 broken wikilinks.

Append `~/Vault/CryoDAQ/_meta/build log.md`:
```markdown
## 2026-04-30 — docs-audit Phase 2 / Group IV vault refresh

- Versions.md: added v0.42.0 + v0.43.0 rows; updated current state
  HEAD c44c575
- F-table backlog.md: synced to ROADMAP post-v0.43.0
- 7 subsystem notes refreshed in-place: Sensor diagnostics alarm,
  Alarm engine v2, Interlock engine, Persistence-first, Safety FSM,
  Analytics view, Plugin architecture
- B1 frontmatter status corrected: OPEN → closed (H5 v0.39.0)
- 00 Overview refreshed: What is CryoDAQ, Architecture overview
- Source map regenerated, 0 broken wikilinks
- Total notes: 78 (unchanged — all edits in-place)
```

### 6.7 Vault has no git — no commit needed for vault itself

Vault edits land directly via Obsidian MCP. Track build log entry
as the audit trail for what changed.

In repo, document the vault sync in handoff:
`artifacts/handoffs/2026-04-30-vault-refresh.md`:

```markdown
# Vault refresh — 2026-04-30 docs-audit Phase 2 Group IV

## Notes refreshed
[list with old/new last_synced dates]

## Notes added
None — all edits in-place per architect OQ #7 decision.

## Source map
Regenerated, 0 broken wikilinks. Total 78 notes.

## Coverage gaps closed
F19, F20, F21, F22, F23, F24, F25 all now have vault subsystem
documentation (in-place extensions of existing notes).
```

### 6.8 Group IV commit (handoff only, vault is outside git)

```
git add artifacts/handoffs/2026-04-30-vault-refresh.md
git commit -m "docs(vault): refresh handoff for 2026-04-30 audit Group IV

Vault refresh executed via Obsidian MCP (Versions.md + F-table +
7 subsystem in-place extensions + B1 frontmatter fix +
2 overview notes).

Coverage gaps closed: F19-F25 all documented in vault.

Source map regenerated. 0 broken wikilinks. Total 78 notes
unchanged (all in-place edits).

Ref: artifacts/docs-audit/2026-04-30/findings.md
Ref: artifacts/handoffs/2026-04-30-vault-refresh.md
Batch: phase-D / docs-audit / Group IV
Risk: vault edits only (no repo source touched)."

git push origin master
```

---

## 7. Phase 2 final report

After all 4 groups land:

```markdown
# Docs Audit Phase 2 — Final Report

## Groups executed
| Group | Status | Commits | Files touched |
|---|---|---|---|
| I Top-level | DONE | 1 commit | README, PROJECT_STATUS, CLAUDE.md |
| II docs/ refresh | DONE | 1 commit | NEXT_SESSION, REPO_AUDIT_REPORT, alarms_tuning_guide, safety-operator, architecture.md |
| III docs/ archive | DONE | 1 commit | 6 files moved |
| IV vault refresh | DONE | 1 handoff commit | 78 notes refreshed in-place |

## Phase 1 verdicts → Phase 2 outcomes
[table mapping each STALE doc to action taken]

## Architect-decision items resolved
[list]

## Outstanding (deferred)
- MIGHT-BE-OK docs not touched: [list] — re-audit on next pass if needed
- F19 channel heuristic refinement (LOW)
- F26 SQLite backport whitelist (XS)
- Lab Ubuntu PC verification

## Master HEAD post-Phase-2
[final SHA]
```

---

## 8. Hard stops

- Master HEAD differs from `c44c575` at start (drift since v0.43.0)
- Group I-III commits fail (push rejected, conflict, etc.) — STOP, report
- Vault MCP unavailable (Obsidian not running) — STOP Group IV, defer
- Pytest collection breaks after any commit — STOP, may need revert
- Architect-decision item discovered mid-execution that wasn't in
  Phase 1 OQ — STOP, write to handoff, await architect

---

## 9. Begin

Read this prompt fully. Execute Groups in order: I → III → II →
IV. (Group III before Group II ensures architecture.md archive
happens before new architecture.md write.)

Or alternatively: I → II (skip new architecture.md) → III (archive
old architecture.md + 5 others) → loop back to write new
architecture.md → second commit. Choose whichever sequencing is
cleanest mechanically.

Architect available synchronously throughout if ARCHITECT DECISION
NEEDED markers arise.

GO.
