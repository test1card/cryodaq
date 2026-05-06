# Docs audit + rewrite — 2026-04-30

> Two phases: full recon for stale data → rewrite + sync of every
> document found stale. Architect (web Claude) drives spec; Sonnet
> executes both phases.

---

## 0. Operating posture

- Architect available synchronously during this session (not asleep).
- Phase 1 is RECON — read-only, write findings doc, STOP for architect
  review before Phase 2.
- Phase 2 is REWRITE — gated by architect approval of Phase 1 findings.
  No auto-proceed.

**Why two phases:** rewriting README without knowing what other docs
also lie is busy-work. Full audit first; rewrite once with complete
picture.

---

## 1. Why this exists

User-facing documentation lies. Specifically caught:
- `README.md` claims v0.33.0 (real: v0.43.0) — 4 minor versions stale
- `PROJECT_STATUS.md` claims v0.42.0 (real: v0.43.0) — 1 minor version
  stale (cleanup Phase 5 update happened pre-v0.43.0 ship)
- Architect repeatedly said "production stack stable" / "everything
  closed" without verifying user-facing docs

This audit closes the documentation loop. Engineering loop is closed
(master clean, tag v0.43.0, tests green, ROADMAP/CHANGELOG current).
Documentation loop is not.

---

## 2. Phase 1 — Recon

### 2.1 Session start (§10 v1.2)

  cd ~/Projects/cryodaq
  git status
  git log -1 --format='%h %P %s' HEAD
  git tag -l "v0.*" --sort=v:refname | tail -5

Expected: master at `c44c575` post-v0.43.0. Working tree clean except
for this prompt file (untracked).

### 2.2 Inventory of "live" docs

Live docs = user-facing OR architect-facing OR claim-state-of-project.
Static reference (e.g., specs in `docs/decisions/`) excluded.

Build inventory:

```bash
mkdir -p artifacts/docs-audit/2026-04-30/

# Top-level docs
ls -la *.md > artifacts/docs-audit/2026-04-30/inventory.txt

# docs/ tree (exclude archives + decisions)
find docs/ -maxdepth 2 -name "*.md" \
  -not -path "*/cc-prompts-archive/*" \
  -not -path "*/handoffs-archive/*" \
  -not -path "*/audits/*" \
  -not -path "*/decisions/*" \
  -not -path "*/legacy-inventory/*" \
  -not -path "*/phase-ui-1/*" \
  -not -path "*/design-system/*" \
  >> artifacts/docs-audit/2026-04-30/inventory.txt

# Vault (read-only access)
ls ~/Vault/CryoDAQ/60\ Roadmap/ 2>&1 >> artifacts/docs-audit/2026-04-30/inventory.txt
ls ~/Vault/CryoDAQ/00\ Overview/ 2>&1 >> artifacts/docs-audit/2026-04-30/inventory.txt
```

### 2.3 Per-doc staleness check

For each doc in inventory, check:

1. **Last modified date** (`stat`)
2. **Last git commit** affecting file (`git log -1 --format='%h %ad %s' --date=short -- <path>`)
3. **First 30 lines** content scan for version strings, dates, status
   claims

Build staleness table:

| Doc | Last commit | Mod date | Claims version | Reality | Verdict |
|---|---|---|---|---|---|

Verdict scale:
- **CURRENT** — content matches v0.43.0 reality
- **STALE-VERSION** — version reference outdated but body still
  truthful
- **STALE-CONTENT** — body content describes wrong reality (missing
  features, wrong workflow)
- **STALE-BOTH** — both
- **OUTDATED-FRAMING** — premise of doc no longer valid (e.g., mentions
  "Phase III in progress" when Phase III complete)
- **MIGHT-BE-OK** — needs deeper read to judge

### 2.4 Specific docs to audit (minimum scope)

#### Top-level (highest visibility)
- `README.md`
- `PROJECT_STATUS.md`
- `DOC_REALITY_MAP.md`
- `RELEASE_CHECKLIST.md`
- `CLAUDE.md`
- `CHANGELOG.md` *(verify [Unreleased] empty post-v0.43.0)*
- `ROADMAP.md` *(verify F19-F25 marked DONE, F26 present)*

#### docs/
- `docs/architecture.md`
- `docs/operator_manual.md`
- `docs/safety-operator.md`
- `docs/instruments.md`
- `docs/deployment.md`
- `docs/first_deployment.md`
- `docs/alarms_tuning_guide.md`
- `docs/ORCHESTRATION.md` *(should be v1.3 after morning A3)*
- `docs/SPEC_AUTHORING_TEMPLATE.md`
- `docs/CODEX_SELF_REVIEW_PLAYBOOK.md`
- `docs/UI_REWORK_ROADMAP.md`
- `docs/DESIGN_SYSTEM.md`
- `docs/PHASE_UI1_V2_WIREFRAME.md`
- `docs/REPO_AUDIT_REPORT.md`
- `docs/NEXT_SESSION.md`
- `docs/codex-architecture-control-plane.md`
- `docs/bug_B1_zmq_idle_death_handoff.md`
- `docs/runbooks/*.md` (list all)

#### Vault (read-only, but flag stale)
- `~/Vault/CryoDAQ/60 Roadmap/Versions.md` — definitely missing v0.43.0
- `~/Vault/CryoDAQ/00 Overview/*.md` (system overview)
- `~/Vault/CryoDAQ/10 Subsystems/*.md` (subsystem notes — sample 3-4)
- `~/Vault/CryoDAQ/_meta/build log.md`

### 2.5 Truth source for "current reality"

Authoritative state:
- **Master HEAD:** `c44c575`
- **Latest tag:** `v0.43.0`
- **Tests:** 1992+ passing (or actual count from latest pytest run)
- **CHANGELOG.md** [0.43.0] section
- **ROADMAP.md** F-row index (post-v0.43.0)
- **`pyproject.toml`** version field
- **`src/`** actual module structure

For each doc claim that may be stale, cross-reference with truth
source. Don't trust doc-internal references to other docs (which may
also be stale).

### 2.6 Findings doc

Write `artifacts/docs-audit/2026-04-30/findings.md`:

```markdown
# Docs audit findings — 2026-04-30

## Truth source state
- Master: c44c575
- Tag: v0.43.0 (released 2026-04-30)
- Tests: <count> passed
- ROADMAP: F1, F2, F3, F4, F6, F10, F11, F19, F20, F21, F22, F23, F24, F25 ✅ DONE; F5, F7, F15 blocked; F8, F9 research; F26 new (XS polish backlog)

## Per-doc verdict

[full table here]

## Stale claim catalog
For each stale doc, list specific stale claims:

### README.md
- Header: "Текущее состояние (v0.33.0)" → reality v0.43.0
- "Phase UI-1 v2 ... primary shell ... v0.33.0" → status of UI rework?
- "Sensor grid (placeholder в v0.33.0, заполняется в блоке B.3)" → status of B.3?
- "Phase widget (placeholder, блоки B.4-B.5)" → status?
- "Quick log (placeholder, блок B.6)" → status?
- "Legacy MainWindow ... до завершения блока B.7" → status of B.7?
- Реализованные workflow-блоки missing F3 widgets, F10 sensor diag → alarm pipeline, F19 enrichment, F20-F25
- Известные ограничения may be outdated post-F25 SQLite gate
- ...

### PROJECT_STATUS.md
- Header date 2026-04-30 (correct) but claims v0.42.0 (was true at write time, now stale)
- Last commit `35f2798` → reality `c44c575`
- ...

### DOC_REALITY_MAP.md
- Last modified 2026-04-17 → 13 days stale
- Cleanup phase 5 added "addendum" — verify if substantive
- ...

[continue for every doc verdict != CURRENT]

## Open questions for architect
1. UI rework Phase blocks (B.3 sensor grid, B.4-B.5 phase widget,
   B.6 quick log, B.7 legacy migration) — what's actual status?
   README references suggest mid-work; ROADMAP doesn't track these.
2. `docs/UI_REWORK_ROADMAP.md` — still authoritative or superseded?
3. `docs/PHASE_UI1_V2_WIREFRAME.md` — still relevant or archive?
4. `docs/REPO_AUDIT_REPORT.md` 2026-04-30 section adequate, or needs
   v0.43.0 update?
5. `docs/codex-architecture-control-plane.md` — last reviewed when?
6. Vault `00 Overview/` notes — separate session vs include here?

## Recommended Phase 2 work order

By visibility / impact:
1. README.md (full rewrite)
2. PROJECT_STATUS.md (version + commit + headline updates)
3. DOC_REALITY_MAP.md (full refresh OR retire if better captured elsewhere)
4. docs/NEXT_SESSION.md
5. docs/REPO_AUDIT_REPORT.md (v0.43.0 audit section)
6. Vault Versions.md (v0.43.0 row)
7. Operator-facing docs (operator_manual, safety-operator, instruments, alarms_tuning_guide) — only if stale
8. Other docs by case
```

### 2.7 Phase 1 commit

  git add artifacts/docs-audit/2026-04-30/
  git commit -m "docs(audit): Phase 1 staleness recon — findings doc

Full inventory of live documentation + per-doc staleness verdict.
Catalog of stale claims per file. Open questions for architect on
UI rework status and doc archival decisions.

Phase 2 (rewrite) gated on architect review of findings.

Ref: CC_PROMPT_DOCS_AUDIT_REWRITE_2026-04-30.md Phase 1
Risk: docs only, no source touched, no doc rewrites yet."

  git push origin master

### 2.8 STOP

DO NOT proceed to Phase 2. Wait for architect to:
- Read findings.md
- Answer open questions in §2.6
- Approve Phase 2 scope
- Architect-approve any architectural-domain decisions (e.g., archive
  vs refresh for unclear docs)

Output a final report:
- Findings doc path
- Inventory size (count of docs audited)
- Stale doc count by verdict category
- Open question count
- Awaiting architect review

---

## 3. Phase 2 — Rewrite + sync

> Architect-gated. Begins only after Phase 1 review approved.
> Architect provides answers to §2.6 open questions, may add scope.

### 3.1 Approach per stale doc

For each doc with verdict != CURRENT, choose action:

- **CURRENT** → no action
- **STALE-VERSION** only → minimal sed-style update of version
  strings + date stamps + commit ref
- **STALE-CONTENT** or **STALE-BOTH** → full or partial rewrite
  driven by truth source
- **OUTDATED-FRAMING** → architect decides: rewrite OR archive

Architect's per-doc decision communicated via Phase 1 review feedback.

### 3.2 Per-doc work pattern

For each doc to rewrite:

1. **Plan stage (Sonnet thinking):**
   - Read current full version
   - Read truth-source equivalents (CHANGELOG, ROADMAP, src/)
   - Identify sections to keep / replace / add / delete
   - Note any architect-decision-needed items

2. **Draft stage (Sonnet writing):**
   - Write rewritten version
   - Preserve any sections marked "keep"
   - Add new sections per truth source
   - Match doc's existing tone (Russian for README, mixed for
     PROJECT_STATUS, etc.)

3. **Self-check stage:**
   - Re-read draft. Any claim → verify against truth source.
   - Any claim that can't be verified → mark "ARCHITECT VERIFY" or
     drop.
   - No "we plan to" / "soon" — only state of THIS commit.

4. **Architect review checkpoint:**
   - Print diff stat (lines added / removed)
   - For each major section rewritten: 2-line summary of change
   - STOP for architect approval before commit

5. **Commit (after approval):**
   - Single commit per doc family (README+PROJECT_STATUS+DOC_REALITY_MAP
     can be one commit; subsystem docs separate; vault separate)
   - Commit message lists what changed

### 3.3 README rewrite — required structure

Architect-approved structure for new README:

```markdown
# CryoDAQ

Brief project description (1-2 paragraphs). What it is, who it's
for, what problem it solves.

## Status

- **Latest release:** v0.43.0 (2026-04-30)
- **Master:** c44c575
- **Tests:** 1992+ passing
- **Production status:** [accurate one-liner from architect]

## Architecture overview

What components run, how they talk:
- cryodaq-engine (headless, instruments + safety + data)
- cryodaq-gui (Qt, primary shell + dashboard)
- cryodaq (Windows launcher)
- cryodaq.web.server (optional FastAPI)

Brief diagram of data flow (instrument → engine → broker → GUI/storage).

## Hardware

What's supported (current, not aspirational):
- 3× LakeShore 218S (GPIB)
- Keithley 2604B (USB-TMC, dual-channel SMU)
- Thyracont VSP63D (RS-232)

## Implemented workflows

What CURRENTLY works end-to-end:
- Experiment lifecycle: idle → cooldown → measurement → warmup → disassembly
- Cryo-vacuum campaign automation (FSM-driven)
- Calibration v2: SRDG capture → multi-zone Chebyshev fit → .cof/.340/JSON/CSV export, .340/JSON import, runtime apply
- Auto-report generation: DOCX (guaranteed) + PDF (best-effort via LibreOffice)
- Telegram alerts: role-filtered (operators get full stream, managers get curated subset)
- Sensor diagnostics → alarm pipeline (warning at 5 min sustained anomaly, critical at 15 min)
- Operator log + experiment metadata + artifact archival
- Plugin architecture for analytics with isolation boundaries

## GUI

Primary: MainWindowV2 (Phase III complete as of v0.40.0):
- TopWatchBar
- ToolRail
- DashboardView (5 zones)
- BottomStatusBar
- OverlayContainer

Phase III closed all overlay views (Analytics with W1+W2+W3
widgets, plus W4 placeholder pending F8). Legacy 10-tab
MainWindow remains as fallback; user sees primary only.

## Installation

[same as current README, unchanged]

## Running

[same, unchanged]

## Configuration

Updated config file list per current state.

## Project structure

src/cryodaq/ tree, ground-truth from actual filesystem.

## Tests

How to run, what coverage.

## Known limitations

Current limitations as of v0.43.0:
- SQLite WAL gate hard-fails on broken versions [3.7.0, 3.51.3) per F25
- Lab Ubuntu PC verification of v0.39.0 H5 fix outstanding
- ...

## License + acknowledgments

[same]
```

Total target ≤300 lines, English-Russian mix as current.

### 3.4 PROJECT_STATUS.md update

- Header: 2026-04-30 (post-v0.43.0)
- Latest commit: c44c575
- Version: 0.43.0
- Tests: actual count
- Frontier: F19-F25 ✅ shipped, F26 (XS polish) deferred, F5/F7/F15
  blocked, F8/F9 research, Lab Ubuntu pending
- Update inventory metrics (Python files, LOC, etc.) — re-count from
  actual filesystem
- Hardware/runtime invariants section: verify each invariant still
  applies; any changed since 2026-04-17 (when Phase 2d was active)?
- Add "Phase 2e+" or whatever the current invariant cohort is, OR
  retire the "Phase 2d" framing if superseded

### 3.5 DOC_REALITY_MAP.md decision

This doc maps src/ modules → docs. 13 days stale. Two options:
- **Refresh fully** with current src/ tree + current docs/ inventory
- **Retire** if PROJECT_STATUS and per-subsystem docs cover this
  function adequately

Architect decides during Phase 1 review.

### 3.6 docs/NEXT_SESSION.md refresh

Update outstanding-items list to post-v0.43.0 state. Current
outstanding (per master summary):
- Lab Ubuntu PC verification
- F26 SQLite backport whitelist (XS)
- F19 channel heuristic refinement (LOW)
- Vault Versions.md sync
- ORCHESTRATION v1.3 already shipped earlier today (move to "recent
  completions" section)

### 3.7 docs/REPO_AUDIT_REPORT.md — v0.43.0 section

Append new audit section dated 2026-04-30 (evening, post-v0.43.0):
- State summary (master, tag, tests)
- Cleanup actions taken THIS audit (docs rewrite/sync — what landed)
- Outstanding (post-doc-audit)

### 3.8 Vault Versions.md sync

Add v0.43.0 row to `~/Vault/CryoDAQ/60 Roadmap/Versions.md`:
- Date: 2026-04-30
- Status: ✅ released
- Scope summary: Overnight sprint (F19-F25) + Phase A doc/process
  updates; 7 features; ORCHESTRATION v1.3; multi-model-consultation
  v1.1; HF3 docstring; plugin disposition
- Closing commit: c44c575

Also bump `last_synced` field if vault notes have one.

### 3.9 Subsystem docs — case-by-case

For each operator-facing doc (operator_manual, safety-operator,
instruments, alarms_tuning_guide), check Phase 1 verdict:
- CURRENT → skip
- STALE → architect-approved rewrite per Phase 2 pattern §3.2

### 3.10 Phase 2 commits

Group commits by doc family:

1. **Top-level rewrite commit:** README.md + PROJECT_STATUS.md +
   DOC_REALITY_MAP.md (or removal of latter) + docs/NEXT_SESSION.md +
   docs/REPO_AUDIT_REPORT.md
2. **Subsystem docs commit:** any operator-facing docs rewritten
3. **Vault commit:** Vault Versions.md + any subsystem note refreshes

Each commit message references docs-audit findings doc + lists files
changed + lists what got fixed (claims-level, not just file-level).

Push after all commits land.

### 3.11 Phase 2 final report

- Phase 1 findings file path
- Files rewritten (count + list)
- Stale claims fixed (count from findings catalog)
- Architect-decision items resolved (list)
- Outstanding (any docs deferred per architect direction)

---

## 4. Hard stops (whole-prompt-level)

- Master HEAD different from `c44c575` at start → drift since v0.43.0
- Test infrastructure broken on master → STOP, sanity check fails
- Architect feedback on Phase 1 unclear or absent at Phase 2 trigger
  → STOP, do not auto-proceed
- Working tree uncommitted changes outside this prompt's scope at
  start → STOP, surface via git status, await direction

---

## 5. Architect comm-out — but available

Unlike overnight runs, architect is available during this session.
Phase 1 → Phase 2 transition is synchronous: write findings, surface
to architect, get approval, proceed.

For ambiguous decisions during Phase 2 rewrite:
- If architect-domain (e.g., "is UI rework Phase B.7 still active?"):
  STOP, ask, wait
- If mechanical (e.g., "section ordering"): apply convention from
  existing README, document in commit

---

## 6. Begin

Phase 1 first. Read this whole prompt. Recon to find every stale
doc. Write findings.md. Commit + push. STOP.

GO.
