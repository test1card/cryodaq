# Docs audit findings — 2026-04-30

## Truth source state

- **Master:** `c44c575` (release: v0.43.0)
- **Tag:** `v0.43.0` (released 2026-04-30)
- **Tests:** 60 targeted (post-merge); full suite last counted at 1 931 (v0.42.0) + 39 new (F19-F25) = ~1 970 (re-run pending)
- **ROADMAP:** F1, F2, F3, F4, F6, F10, F11, F19, F20, F21, F22, F23, F24, F25 ✅ DONE; F5, F7, F15 blocked; F8, F9 research; F26 new (XS polish backlog)
- **CHANGELOG:** `[Unreleased]` empty ✅; `[0.43.0]` section present ✅

---

## Per-doc verdict — In-repo (27 docs)

### Top-level (7 tracked docs)

| Doc | Last commit | Mod date | Claims version | Reality | Verdict |
|---|---|---|---|---|---|
| `README.md` | `b254de2` | 2026-04-27 | v0.33.0 (header) | v0.43.0 | **STALE-BOTH** |
| `PROJECT_STATUS.md` | `6662981` | 2026-04-29 | v0.42.0, commit `35f2798`, 1 931 tests | v0.43.0, `c44c575`, ~1 970 | **STALE-BOTH** |
| `DOC_REALITY_MAP.md` | `6662981` | 2026-04-29 | addendum to v0.42.0; "fresh audit pending" | no v0.43.0 addendum | **STALE-VERSION** |
| `RELEASE_CHECKLIST.md` | `466fb7f` | 2026-04-20 | none visible | — | **MIGHT-BE-OK** |
| `CHANGELOG.md` | `c44c575` | 2026-04-30 | [0.43.0] present; [Unreleased] empty | current | **CURRENT** |
| `CLAUDE.md` | `0fed332` | 2026-04-27 | "Current package metadata: `0.13.0`" | 0.43.0 | **STALE-VERSION** |
| `ROADMAP.md` | `c44c575` | 2026-04-30 | F19-F25 ✅ DONE; F26 new | current | **CURRENT** |

### docs/ (20 docs)

| Doc | Last commit | Mod date | Claims version / status | Verdict |
|---|---|---|---|---|
| `docs/ORCHESTRATION.md` | `4115703` | 2026-04-29 | v1.3, 2026-04-30 | **CURRENT** |
| `docs/architecture.md` | `44c399f` | 2026-03-22 | "Версия документа: 0.13.0, март 2026" | **STALE-BOTH** |
| `docs/instruments.md` | `c9d9651` | 2026-04-17 | no version claim | **MIGHT-BE-OK** |
| `docs/safety-operator.md` | `604e0ea` | 2026-04-17 | last_updated: 2026-04-17; no version | **MIGHT-BE-OK** |
| `docs/operator_manual.md` | `0fed332` | 2026-04-27 | "Версия документа: 0.13.0, март 2026" | **STALE-VERSION** |
| `docs/deployment.md` | `6f0261e` | 2026-04-20 | no version claim | **MIGHT-BE-OK** |
| `docs/first_deployment.md` | `c427247` | 2026-03-21 | "Версия документа: 0.13.0, март 2026" | **STALE-BOTH** |
| `docs/alarms_tuning_guide.md` | `9339d9f` | 2026-04-20 | "Обновлён 2026-04-20 (HEAD `b06c657`)" | **STALE-CONTENT** |
| `docs/NEXT_SESSION.md` | `6662981` | 2026-04-29 | HEAD `35f2798` v0.42.0; F19-F25 open | **STALE-BOTH** |
| `docs/REPO_AUDIT_REPORT.md` | `42a9bc7` | 2026-04-29 | audit through v0.42.0 | **STALE-CONTENT** |
| `docs/UI_REWORK_ROADMAP.md` | `0d4d386` | 2026-04-17 | SUPERSEDED banner | **OUTDATED-FRAMING** |
| `docs/DESIGN_SYSTEM.md` | `0d4d386` | 2026-04-17 | SUPERSEDED banner | **OUTDATED-FRAMING** |
| `docs/PHASE_UI1_V2_WIREFRAME.md` | `0d4d386` | 2026-04-17 | SUPERSEDED banner | **OUTDATED-FRAMING** |
| `docs/CODEX_SELF_REVIEW_PLAYBOOK.md` | `2d3b504` | 2026-04-20 | process doc | **MIGHT-BE-OK** |
| `docs/SPEC_AUTHORING_TEMPLATE.md` | `2d3b504` | 2026-04-20 | template | **MIGHT-BE-OK** |
| `docs/bug_B1_zmq_idle_death_handoff.md` | `9f5cea3` | 2026-04-27 | H5 confirmed + fixed | **MIGHT-BE-OK** |
| `docs/codex-architecture-control-plane.md` | `634ff1d` | 2026-04-29 | reference doc | **MIGHT-BE-OK** |
| `docs/runbooks/stall_diagnosis.md` | `d0dbdfc` | 2026-04-17 | runbook | **MIGHT-BE-OK** |
| `docs/changelog/RETRO_ANALYSIS_V3.md` | `271f1f3` | 2026-04-14 | historical | **MIGHT-BE-OK** |

---

## Per-doc verdict — Vault (29 content notes)

### 00 Overview (4 notes)

| Note | last_synced | Verdict |
|---|---|---|
| `What is CryoDAQ.md` | 2026-04-26 | **STALE-CONTENT** |
| `Architecture overview.md` | 2026-04-27 | **STALE-CONTENT** |
| `Hardware setup.md` | 2026-04-27 | **MIGHT-BE-OK** |
| `UI and design system.md` | 2026-04-26 | **MIGHT-BE-OK** |

### 10 Subsystems (14 notes)

| Note | last_synced | Verdict |
|---|---|---|
| `Alarm engine v2.md` | 2026-04-26 | **STALE-CONTENT** |
| `Analytics view.md` | 2026-04-29 | **STALE-CONTENT** |
| `Calibration v2.md` | 2026-04-28 | **CURRENT** |
| `Cooldown predictor.md` | 2026-04-29 | **CURRENT** |
| `Experiment manager.md` | 2026-04-29 | **CURRENT** |
| `F4 lazy replay.md` | 2026-04-29 | **CURRENT** |
| `Interlock engine.md` | 2026-04-29 | **STALE-CONTENT** |
| `Persistence-first.md` | 2026-04-27 | **STALE-CONTENT** |
| `Plugin architecture.md` | 2026-04-26 | **STALE-CONTENT** |
| `Reporting.md` | 2026-04-28 | **CURRENT** |
| `Safety FSM.md` | 2026-04-27 | **STALE-CONTENT** |
| `Sensor diagnostics alarm.md` | 2026-04-29 | **STALE-CONTENT** |
| `Web dashboard.md` | 2026-04-29 | **CURRENT** |
| `ZMQ bridge.md` | 2026-04-27 | **MIGHT-BE-OK** |

### 20 Drivers (3 notes)

| Note | last_synced | Verdict |
|---|---|---|
| `Keithley 2604B.md` | 2026-04-26 | **MIGHT-BE-OK** |
| `LakeShore 218S.md` | 2026-04-27 | **CURRENT** |
| `Thyracont VSP63D.md` | 2026-04-26 | **CURRENT** |

### 30 Investigations (6 notes)

| Note | last_synced | status frontmatter | Verdict |
|---|---|---|---|
| `B1 ZMQ idle-death.md` | 2026-04-27 | "bug OPEN" ← **WRONG** | **STALE-CONTENT** |
| `b2b4fb5 hardening race.md` | 2026-04-26 | closed | **CURRENT** |
| `Codex H2 wrong hypothesis.md` | 2026-04-27 | closed | **CURRENT** |
| `Cyrillic homoglyph.md` | 2026-04-26 | closed | **CURRENT** |
| `IV.6 cmd plane hardening.md` | 2026-04-26 | shipped | **CURRENT** |
| `Plugin isolation rebuild.md` | 2026-04-27 | closed | **CURRENT** |

### 60 Roadmap (2 notes)

| Note | last_synced | Verdict |
|---|---|---|
| `Versions.md` | 2026-04-29 | **STALE-BOTH** |
| `F-table backlog.md` | 2026-04-26 | **STALE-CONTENT** |

---

## Stale claim catalog

### README.md (STALE-BOTH)

- Header: "Текущее состояние (v0.33.0)" → reality v0.43.0
- GUI section: "начиная с v0.33.0 CryoDAQ использует новый MainWindowV2" → still true but version stale
- Dashboard: "Sensor grid (placeholder в v0.33.0, заполняется в блоке B.3)" → status of B.3? **[OPEN QUESTION #1]**
- Dashboard: "Phase widget (placeholder, блоки B.4-B.5)" → status? **[OPEN QUESTION #1]**
- Dashboard: "Quick log (placeholder, блок B.6)" → status? **[OPEN QUESTION #1]**
- `OverlayContainer — host для legacy tab panels через overlay mechanism` → legacy panels still active?
- "Legacy MainWindow (fallback, до блока B.7)" → is B.7 complete? **[OPEN QUESTION #2]**
- Реализованные workflow-блоки missing: F10 sensor diag → alarm pipeline, F19 enrichment, F20-F25
- Известные ограничения: no mention of F25 SQLite WAL gate ([3.7.0, 3.51.3) hard-fail)

### PROJECT_STATUS.md (STALE-BOTH)

- Header commit: `35f2798` → reality `c44c575`
- "Версия пакета: 0.42.0" → 0.43.0
- "Тесты: 1 931 passed, 4 skipped" → ~1 970 (39 new tests from F19-F25)
- "Фронтир: v0.42.0 shipped. Open feature work: F19–F25" → F19-F25 all DONE in v0.43.0
- Python files 145, LOC ~48 500, test files 206, test LOC ~38 800 → stale (new test files added)
- "Phase II UI rebuild в процессе" → need architect confirmation **[OPEN QUESTION #2]**
- `Источник актуального репо-инвентаря: docs/REPO_AUDIT_REPORT.md (2026-04-17)` → now 2026-04-29

### DOC_REALITY_MAP.md (STALE-VERSION)

- Addendum says "fresh full audit against 35f2798 (v0.42.0) is pending" — still pending, now needs v0.43.0
- HISTORICAL banner is accurate; addendum is accurate but now 1 version behind

### CLAUDE.md (STALE-VERSION)

- "Current package metadata: `0.13.0`" → 0.43.0 (in the description paragraph)

### docs/architecture.md (STALE-BOTH)

- "Версия документа: 0.13.0, март 2026" → 6+ weeks stale
- Missing: calibration v2 pipeline, F10 sensor diag alarm, alarm_v2 v2 features (F20/F21/F22), F23/F24/F25
- Entire document describes pre-v0.34.0 architecture

### docs/operator_manual.md (STALE-VERSION)

- "Версия документа: 0.13.0, март 2026" → version claim stale; body updated to v0.27.x era calibration
- Does describe calibration v2 .cof export (updated 2026-04-27)
- Missing: F19 experiment_summary enrichment UI, F24 interlock acknowledge operator action

### docs/first_deployment.md (STALE-BOTH)

- "Версия документа: 0.13.0, март 2026" → 0.43.0
- Last commit 2026-03-21 — 5+ weeks stale
- Deployment steps may reference obsolete package structure **[OPEN QUESTION #3]**

### docs/alarms_tuning_guide.md (STALE-CONTENT)

- "Обновлён 2026-04-20 после IV.3 close (HEAD `b06c657`)" → stale reference
- F20: aggregation_threshold (default 3) and escalation_cooldown_s (default 120) not documented
- F21: hysteresis deadband (active_channels filter) not documented
- F22: severity upgrade WARNING→CRITICAL behavior not documented

### docs/NEXT_SESSION.md (STALE-BOTH)

- "Current HEAD: `35f2798` — v0.42.0" → `c44c575` v0.43.0
- "Test baseline: 1 931 passed, 4 skipped" → ~1 970
- F21-F25 listed in "Open F-tasks" table → all DONE in v0.43.0
- "ORCHESTRATION v1.3: update pending — Current version: v1.2" → v1.3 shipped in A3
- "Plugin disposition: ...Not urgent operationally" → A4 shipped (disabled)
- "T2 re-run: calibration T2 invalidated" → completed overnight
- "T3 docstring: update_target '≤1 s' claim" → HF3 (A1) shipped the fix
- Where-to-find: "Agent orchestration contract: docs/ORCHESTRATION.md (v1.2)" → v1.3

### docs/REPO_AUDIT_REPORT.md (STALE-CONTENT)

- Latest section covers v0.42.0 state
- No v0.43.0 section (7 features + 39 tests + 2 merges)

### Vault: What is CryoDAQ.md (STALE-CONTENT)

- Feature list likely stops at v0.40.0/v0.41.0 wave; no F19-F25 features
- last_synced 2026-04-26 (before F10 vault sync and before F19-F25)

### Vault: Architecture overview.md (STALE-CONTENT)

- last_synced 2026-04-27; pre-F19-F25
- Missing: RateEstimator timestamp source (F23), interlock acknowledge ZMQ (F24), SQLite startup gate (F25)

### Vault: Alarm engine v2.md (STALE-CONTENT)

- last_synced 2026-04-26
- Missing: F20 aggregation+cooldown, F21 hysteresis deadband (active_channels), F22 severity upgrade in-place

### Vault: Analytics view.md (STALE-CONTENT)

- last_synced 2026-04-29 (has W3 experiment_summary entry)
- Missing: F19 enrichment — channel min/max/mean stats, top-3 alarms, clickable DOCX/PDF links
- `ExperimentSummaryWidget` entry does not reflect F19 additions

### Vault: Interlock engine.md (STALE-CONTENT)

- last_synced 2026-04-29
- Describes TRIPPED → acknowledge() → ARMED state machine correctly
- Missing: F24 — `interlock_acknowledge` exposed as ZMQ verb (engine.py _handle_gui_command)

### Vault: Persistence-first.md (STALE-CONTENT)

- last_synced 2026-04-27
- Describes WAL mode invariant correctly
- Missing: F25 — `_check_sqlite_version()` now raises `RuntimeError` on [3.7.0, 3.51.3); `CRYODAQ_ALLOW_BROKEN_SQLITE=1` bypass

### Vault: Plugin architecture.md (STALE-CONTENT)

- last_synced 2026-04-26
- Missing: F20 config additions to `plugins.yaml` (`aggregation_threshold: 3`, `escalation_cooldown_s: 120.0`)

### Vault: Safety FSM.md (STALE-CONTENT)

- last_synced 2026-04-27
- Missing: F23 — `_collect_loop` now uses `reading.timestamp.timestamp()` not `time.monotonic()`
- Missing: HF3 — `update_target()` docstring clarification (delayed-update design, slew-rate convergence)

### Vault: Sensor diagnostics alarm.md (STALE-CONTENT)

- last_synced 2026-04-29
- Has "## Deferred (F20)" section listing aggregation and cooldown as **deferred**
- F20 is now **DONE** (shipped v0.43.0) — section needs to become "## Shipped (F20)"

### Vault: B1 ZMQ idle-death.md (STALE-CONTENT)

- last_synced 2026-04-27, `status: synthesized — bug OPEN`
- Body: "The single bug that blocks `v0.34.0` tag"
- **Both claims wrong**: B1 CLOSED in v0.39.0 (2026-04-27); v0.34.0 shipped
- Note was last synced on the same day B1 was closed; status field was not updated

### Vault: Versions.md (STALE-BOTH)

- Tag table ends at v0.41.0; missing v0.42.0 and v0.43.0
- "Current state" section: HEAD `983bc93`, `pyproject.toml: 0.40.0` → `c44c575`, `0.43.0`
- "Next release: v0.41.0" → already shipped; next is undefined (F26 XS, then research)

### Vault: F-table backlog.md (STALE-CONTENT)

- `source: ROADMAP.md (F-table, 2026-04-20)` — 10 days stale at vault build; now 10 more days stale
- F1-F20 listed; F19-F20 shown as `⬜ NOT STARTED` → now ✅ DONE
- F21-F26 entirely absent

---

## Verdict summary

### In-repo (27 docs)

| Verdict | Count | Docs |
|---|---|---|
| **CURRENT** | 3 | CHANGELOG.md, ROADMAP.md, docs/ORCHESTRATION.md |
| **STALE-BOTH** | 5 | README.md, PROJECT_STATUS.md, docs/architecture.md, docs/first_deployment.md, docs/NEXT_SESSION.md |
| **STALE-VERSION** | 3 | DOC_REALITY_MAP.md, CLAUDE.md, docs/operator_manual.md |
| **STALE-CONTENT** | 2 | docs/alarms_tuning_guide.md, docs/REPO_AUDIT_REPORT.md |
| **OUTDATED-FRAMING** | 3 | docs/UI_REWORK_ROADMAP.md, docs/DESIGN_SYSTEM.md, docs/PHASE_UI1_V2_WIREFRAME.md |
| **MIGHT-BE-OK** | 11 | RELEASE_CHECKLIST.md, docs/instruments.md, docs/safety-operator.md, docs/deployment.md, docs/CODEX_SELF_REVIEW_PLAYBOOK.md, docs/SPEC_AUTHORING_TEMPLATE.md, docs/bug_B1_zmq_idle_death_handoff.md, docs/codex-architecture-control-plane.md, docs/runbooks/stall_diagnosis.md, docs/changelog/RETRO_ANALYSIS_V3.md, THIRD_PARTY_NOTICES.md |

### Vault (29 content notes)

| Verdict | Count | Notes |
|---|---|---|
| **CURRENT** | 13 | Calibration v2, Cooldown predictor, Experiment manager, F4 lazy replay, Reporting, Web dashboard, LakeShore 218S, Thyracont VSP63D, b2b4fb5 hardening, Codex H2, Cyrillic homoglyph, IV.6 cmd plane, Plugin isolation |
| **STALE-BOTH** | 1 | Versions.md |
| **STALE-CONTENT** | 11 | What is CryoDAQ, Architecture overview, Alarm engine v2, Analytics view, Interlock engine, Persistence-first, Plugin architecture, Safety FSM, Sensor diagnostics alarm, B1 ZMQ idle-death, F-table backlog |
| **MIGHT-BE-OK** | 4 | Hardware setup, UI and design system, ZMQ bridge, Keithley 2604B |

---

## Vault subsystem coverage gaps

New features shipped in v0.43.0 with no dedicated vault note:

| Feature | Current gap | Resolution options |
|---|---|---|
| F19 W3 enrichment | Not in Analytics view.md | Extend Analytics view.md §W3 |
| F20 aggregation+cooldown | Sensor diagnostics alarm.md has it as "Deferred" | Update §Deferred → §Shipped |
| F21 hysteresis deadband | Not in Alarm engine v2.md | Extend Alarm engine v2.md |
| F22 severity upgrade | Not in Alarm engine v2.md | Extend Alarm engine v2.md |
| F23 RateEstimator timestamp | Not in Safety FSM.md | Extend Safety FSM.md |
| F24 interlock acknowledge ZMQ | Not in Interlock engine.md | Extend Interlock engine.md §ZMQ |
| F25 SQLite WAL gate | Not in Persistence-first.md | Extend Persistence-first.md |

Architect decides: refresh existing notes in-place vs new per-feature note.

---

## Vault Versions.md gaps

| Version | Date | In Versions.md? |
|---|---|---|
| v0.34.0 | 2026-04-20 | ✅ yes |
| v0.35.0 | 2026-04-24 | ✅ yes |
| v0.36.0 | 2026-04-21 | ✅ yes |
| v0.37.0 | 2026-04-24 | ✅ yes |
| v0.38.0 | 2026-04-27 | ✅ yes |
| v0.39.0 | 2026-04-27 | ✅ yes |
| v0.40.0 | 2026-04-29 | ✅ yes |
| v0.41.0 | 2026-04-29 | ✅ yes |
| v0.42.0 | 2026-04-29 | ❌ MISSING |
| v0.43.0 | 2026-04-30 | ❌ MISSING |

Current state section: HEAD `983bc93` v0.40.0 — 3 versions behind.

---

## Open questions for architect

1. **UI rework blocks B.3–B.7 status** — README describes sensor grid (B.3), phase widget (B.4-B.5), quick log (B.6), and legacy migration (B.7) as in-progress placeholder blocks. Are any of these now shipped? Or still active? README rewrite needs accurate status for the dashboard zones section.

2. **Legacy MainWindow status** — README says `gui/main_window.py` is "fallback, до завершения блока B.7". CLAUDE.md module index says "legacy tab panels (active until block B.7)". Is this still the right framing, or has B.7 completed/been retired?

3. **docs/first_deployment.md** — v0.13.0 from 2026-03-21. Full rewrite to v0.43.0 state, or archive? The deployment steps may reference obsolete package structure.

4. **docs/architecture.md** — v0.13.0 from 2026-03-22. Full rewrite or retire? Does PROJECT_STATUS.md architecture section adequately supersede it?

5. **DOC_REALITY_MAP.md** — 13+ days stale. Refresh to v0.43.0 state, or retire? See §3.5 of prompt.

6. **Three SUPERSEDED docs** (UI_REWORK_ROADMAP, DESIGN_SYSTEM, PHASE_UI1_V2_WIREFRAME) — keep as historical, or move to archive/delete? They have SUPERSEDED banners but bloat docs/.

7. **Vault: per-feature note vs in-place extension** — 7 coverage gaps (F19-F25). Prefer extending existing notes (7 edits) vs 7 new notes?

8. **Vault: B1 ZMQ idle-death.md** — status frontmatter says "OPEN" but B1 CLOSED in v0.39.0. Trivial fix: update frontmatter status to "closed — H5 fix shipped v0.39.0". Confirm this is all that's needed.

9. **CLAUDE.md package metadata** — "Current package metadata: `0.13.0`" in the description narrative. Update to `0.43.0` or rewrite sentence to be version-agnostic?

10. **docs/safety-operator.md + docs/instruments.md** — these are MIGHT-BE-OK. Do operators need to know about F24 (interlock acknowledge is now a ZMQ command)? If yes, safety-operator.md needs a section.

11. **docs/alarms_tuning_guide.md** — STALE-CONTENT for F20/F21/F22 config. Full rewrite of the alarm sections or targeted additions (aggregation_threshold, escalation_cooldown_s, hysteresis config)?

---

## Recommended Phase 2 work order

By visibility / urgency:

1. **README.md** — full rewrite to v0.43.0 per §3.3 structure (needs architect answers to OQ #1 and #2 first)
2. **PROJECT_STATUS.md** — version + commit + metrics + F-status update
3. **docs/NEXT_SESSION.md** — clear completed items, update HEAD/version/baseline
4. **Vault: Versions.md** — add v0.42.0 + v0.43.0 rows; update Current state section
5. **Vault: F-table backlog.md** — sync from current ROADMAP.md (F19-F26 status)
6. **Vault: Sensor diagnostics alarm.md** — F20 "Deferred" → "Shipped"
7. **Vault: Alarm engine v2.md** — add F20/F21/F22 sections
8. **Vault: Interlock engine.md** — add F24 ZMQ verb section
9. **Vault: Persistence-first.md** — add F25 startup gate section
10. **Vault: Safety FSM.md** — add F23 + HF3 sections
11. **Vault: Analytics view.md** — add F19 enrichment to W3 entry
12. **Vault: Plugin architecture.md** — add F20 config additions
13. **Vault: What is CryoDAQ.md** + **Architecture overview.md** — refresh feature lists
14. **Vault: B1 ZMQ idle-death.md** — update status frontmatter to closed
15. **docs/alarms_tuning_guide.md** — F20/F21/F22 config additions
16. **docs/REPO_AUDIT_REPORT.md** — append v0.43.0 section
17. **CLAUDE.md** — fix "0.13.0" metadata claim
18. **DOC_REALITY_MAP.md** — refresh or retire (architect decision OQ #5)
19. **docs/architecture.md** + **docs/first_deployment.md** — full rewrite or archive (architect OQ #3, #4)
20. **Operator-facing docs** (safety-operator.md, instruments.md, deployment.md) — only if architect confirms OQ #10 actionable

**Not-in-scope for Phase 2 (defer):**
- OUTDATED-FRAMING docs (UI_REWORK_ROADMAP, DESIGN_SYSTEM, PHASE_UI1_V2_WIREFRAME) — architect decides
- MIGHT-BE-OK docs without confirmed stale claims
