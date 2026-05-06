# Repo Cleanup 2026-04-30

> Full-scope housekeeping pass after intensive 6-week sprint.
> Not parallel to calibration session — this runs AFTER calibration
> closes (architect-confirmed sequence).

---

## 0. Operating posture

**Critical safety rules:**
- **NEVER delete files autonomously.** Architect-only decision.
  Move-not-delete for everything stale. ORCHESTRATION rule applies.
- **`git mv` not plain `mv`** — preserve history.
- **One commit per category** — easier to revert if something breaks.
- **Conservative on ambiguity** — when in doubt, archive don't touch.
- **Investigate before action** for suspicious files.

**This session does NOT:**
- Delete any files
- Touch `CC_PROMPT_CALIBRATION_2026-04-30.md` or `CC_PROMPT_REPO_CLEANUP_2026-04-30.md` (active prompts)
- Touch `.worktrees/`, `.swarm/`, `.audit-run/` (potential active agent workspaces)
- Touch `artifacts/calibration/` (calibration may have written there)
- Touch source code in `src/`, `tests/`, `config/`

---

## 1. Phase structure

7 phases sequentially. Each ends with verification + commit.

| Phase | What | Risk |
|---|---|---|
| 0 | Recon + audit findings doc | none |
| 1 | Investigation of suspicious files (read-only) | none |
| 2 | Archive completed CC_PROMPT_* files | low |
| 3 | Archive stale top-level docs | low |
| 4 | artifacts/ structure cleanup | low |
| 5 | Update living docs (PROJECT_STATUS, DOC_REALITY_MAP, NEXT_SESSION) | medium |
| 6 | Final repo audit report | none |
| 7 | Master summary + push | none |

---

## 2. Phase 0 — Recon

### 2.1 Session start (§10 v1.2)

  cd ~/Projects/cryodaq
  git status
  git log -1 --format='%h %P %s' HEAD     # rtk-aware §14.5
  git tag -l "v0.*" --sort=v:refname | tail -5

Expected: master at `35f2798` or later (post-v0.42.0). Working tree
clean OR has untracked CC prompts only (those untracked is fine —
we're about to deal with them).

### 2.2 Inventory

Create `artifacts/cleanup/2026-04-30/inventory.md` with full root
listing + all stale files identified. Use:

  ls -la ~/Projects/cryodaq/ | grep -v "^d.*\." > /tmp/root-files.txt
  ls -la ~/Projects/cryodaq/docs/ > /tmp/docs-files.txt
  ls -la ~/Projects/cryodaq/artifacts/ > /tmp/artifacts-files.txt

Per file age check:

  for f in ~/Projects/cryodaq/{*.md,*.py}; do
    if [ -f "$f" ]; then
      mod=$(stat -f "%Sm" -t "%Y-%m-%d" "$f" 2>/dev/null || stat -c "%y" "$f" 2>/dev/null | cut -d' ' -f1)
      echo "$mod $(basename $f)"
    fi
  done | sort

### 2.3 Audit findings doc

Write `artifacts/cleanup/2026-04-30/audit-findings.md`:

```markdown
# Repo Cleanup Audit — 2026-04-30

## Top-level files (root of repo)

### Legitimate (keep as-is)
- README.md, LICENSE, CHANGELOG.md, ROADMAP.md, ...

### CC_PROMPT_* files to archive (scope completed)
- CC_PROMPT_IV_2_ORCHESTRATOR.md (IV.2 closed v0.34.0)
- CC_PROMPT_IV_3_BATCH.md (IV.3 closed)
- ...

### CC_PROMPT_* files to keep (active or pending)
- CC_PROMPT_CALIBRATION_2026-04-30.md (RUNNING)
- CC_PROMPT_REPO_CLEANUP_2026-04-30.md (THIS PROMPT)
- CC_PROMPT_METASWARM_F17.md (NEEDS CHECK — F17 spec from yesterday's metaswarm, not yet implemented)

### Stale top-level docs to archive
- HANDOFF_2026-04-20_GLM.md (10 days old, single session)
- SESSION_DETAIL_2026-04-20.md (10 days)
- CODEX_ARCHITECTURE_CONTROL_PLANE.md (belongs in docs/)

### Living docs requiring update
- PROJECT_STATUS.md (last modified 2026-04-24, 6 days stale)
- DOC_REALITY_MAP.md (last modified 2026-04-17, 13 days stale)
- docs/NEXT_SESSION.md (date check)

### Suspicious files (Phase 1 investigates)
- draft.py (created 2026-04-28, 3.8KB)
- draft2.py (date check)
- ~/ directory (shell mistake — confirmed by architect: rm -rf safe BUT do not auto-delete)
- tsp/p_const.lua (Keithley TSP script — KEEP, legitimate instrument-side code)
```

Commit Phase 0:

  git add artifacts/cleanup/2026-04-30/
  git commit -m "docs(cleanup): Phase 0 inventory + audit findings (2026-04-30)

Pre-cleanup recon. Documents repo state before housekeeping pass.

Ref: CC_PROMPT_REPO_CLEANUP_2026-04-30.md Phase 0
Risk: docs only."

---

## 3. Phase 1 — Investigation (read-only, no moves)

Investigate suspicious files. Append findings to
`artifacts/cleanup/2026-04-30/audit-findings.md` under
"Investigation results" section.

### 3.1 draft.py / draft2.py

  cat ~/Projects/cryodaq/draft.py
  cat ~/Projects/cryodaq/draft2.py
  
  # Are they git-tracked?
  git log --oneline draft.py 2>/dev/null | head -5
  git log --oneline draft2.py 2>/dev/null | head -5
  
  # Are they referenced anywhere?
  grep -rn "draft\.py\|draft2\.py" ~/Projects/cryodaq/ \
    --exclude-dir=.git --exclude-dir=.venv --exclude-dir=.pytest_cache \
    2>/dev/null | head -10

Document: contents summary (1-2 lines), git-tracked yes/no,
references count, recommendation (archive / delete-by-architect /
move to scripts/).

### 3.2 ~/ directory (shell mistake)

  ls -la ~/Projects/cryodaq/~/
  find ~/Projects/cryodaq/~/ -type f
  
  # Is it git-tracked?
  git ls-files ~/Projects/cryodaq/~/ | head -5
  git status --short | grep "~/"

Architect already confirmed: empty mkdir mistake. Do NOT auto-delete
(per safety rule). Document recommendation: "rm -rf when architect
present".

### 3.3 tsp/ directory

  cat ~/Projects/cryodaq/tsp/p_const.lua
  
  # Used / referenced?
  grep -rn "p_const\.lua\|tsp/" ~/Projects/cryodaq/src/ ~/Projects/cryodaq/docs/ \
    2>/dev/null | head -10

Document: this is Keithley 2604B TSP (Test Script Processor)
on-instrument script. Architect-confirmed: KEEP. Add note to
docs/instruments.md if not already documented.

### 3.4 agentswarm/ directory

  ls -la ~/Projects/cryodaq/agentswarm/
  ls ~/Projects/cryodaq/agentswarm/2026-04-21-overnight-hardening/

  # Already gitignored per .gitignore line 88. Verify:
  git check-ignore -v ~/Projects/cryodaq/agentswarm/

Document: already gitignored. Local-only artifacts. Recommendation:
move to `~/Projects/cryodaq-archive/` outside repo OR leave as
gitignored local cache.

### 3.5 graphify-out and graphify-out.stale-pre-merge

  ls -d ~/Projects/cryodaq/graphify-out*

Both gitignored per .gitignore. .stale-pre-merge folder name says
"stale" — recommendation: architect can delete locally when convenient,
no cleanup action needed in this pass since gitignored already.

### 3.6 .scratch, .swarm, .audit-run, .omc

  for d in .scratch .swarm .audit-run .omc; do
    echo "=== $d ==="
    ls -la ~/Projects/cryodaq/$d/ | head -10
    git check-ignore ~/Projects/cryodaq/$d/ 2>&1
  done

All gitignored per existing .gitignore. Recommendation: no action.
Document for awareness only.

### 3.7 build/, dist/

Already gitignored. PyInstaller artifacts. No cleanup action.

### 3.8 Commit

  git add artifacts/cleanup/2026-04-30/audit-findings.md
  git commit -m "docs(cleanup): Phase 1 investigation results

Suspicious files investigated read-only. No files moved.

Findings:
- draft.py / draft2.py: <result>
- ~/ directory: shell mkdir mistake, safe to remove (architect-only)
- tsp/p_const.lua: legitimate Keithley TSP script, KEEP
- agentswarm/, graphify-out/: gitignored local caches
- .scratch, .swarm, .audit-run, .omc: gitignored agent workspaces

Ref: CC_PROMPT_REPO_CLEANUP_2026-04-30.md Phase 1
Risk: docs only, no code or file moves."

---

## 4. Phase 2 — Archive completed CC_PROMPT_* files

### 4.1 Create archive structure

  mkdir -p docs/cc-prompts-archive/2026-04/

### 4.2 Identify files

Per audit-findings.md, completed CC_PROMPT files:
- CC_PROMPT_IV_2_ORCHESTRATOR.md (IV.2 → v0.34.0)
- CC_PROMPT_IV_3_BATCH.md (IV.3 → v0.34.0)
- CC_PROMPT_IV_4_BATCH.md (IV.4 → v0.34.0, retroactive)
- CC_PROMPT_IV_6_ZMQ_BRIDGE_FIX.md (IV.6 → v0.34.0)
- CC_PROMPT_IV_7_IPC_TRANSPORT.md (superseded by H5 fix in v0.39.0)
- CC_PROMPT_OVERNIGHT_SWARM_2026-04-24.md (closed)
- CC_PROMPT_VAULT_AUDIT_2026-04-27.md (closed)
- CC_PROMPT_VAULT_BUILD_2026-04-26.md (closed)
- CC_PROMPT_F3_ANALYTICS_WIRING.md (F3 → v0.40.0)
- CC_PROMPT_F3_OVERNIGHT_RUNNER.md (F3 → v0.40.0)
- CC_PROMPT_F10_SENSOR_DIAGNOSTICS_ALARM.md (F10 → v0.41.0)
- CC_PROMPT_VAULT_SUBSYSTEM_QUARTET.md (closed v0.41.0)
- CC_PROMPT_OVERNIGHT_RUNNER_2026-04-29.md (closed v0.41.0)
- CC_PROMPT_METASWARM_2026-04-29.md (closed)

DO NOT archive:
- CC_PROMPT_CALIBRATION_2026-04-30.md (RUNNING — leave in root)
- CC_PROMPT_REPO_CLEANUP_2026-04-30.md (THIS PROMPT — leave in root)
- CC_PROMPT_METASWARM_F17.md (NEEDS CHECK)

For CC_PROMPT_METASWARM_F17.md: read first paragraph, verify it's
F17 spec design from yesterday's metaswarm. If yes, keep in root
(pending implementation). If it's actually closed, archive too.

### 4.3 Archive via git mv

  cd ~/Projects/cryodaq
  for f in CC_PROMPT_IV_2_ORCHESTRATOR.md CC_PROMPT_IV_3_BATCH.md \
           CC_PROMPT_IV_4_BATCH.md CC_PROMPT_IV_6_ZMQ_BRIDGE_FIX.md \
           CC_PROMPT_IV_7_IPC_TRANSPORT.md \
           CC_PROMPT_OVERNIGHT_SWARM_2026-04-24.md \
           CC_PROMPT_VAULT_AUDIT_2026-04-27.md \
           CC_PROMPT_VAULT_BUILD_2026-04-26.md \
           CC_PROMPT_F3_ANALYTICS_WIRING.md \
           CC_PROMPT_F3_OVERNIGHT_RUNNER.md \
           CC_PROMPT_F10_SENSOR_DIAGNOSTICS_ALARM.md \
           CC_PROMPT_VAULT_SUBSYSTEM_QUARTET.md \
           CC_PROMPT_OVERNIGHT_RUNNER_2026-04-29.md \
           CC_PROMPT_METASWARM_2026-04-29.md; do
    if [ -f "$f" ]; then
      # Some of these are not git-tracked (untracked); use plain mv 
      # for those, git mv for tracked
      if git ls-files --error-unmatch "$f" >/dev/null 2>&1; then
        git mv "$f" "docs/cc-prompts-archive/2026-04/$f"
        echo "tracked: git mv $f"
      else
        mv "$f" "docs/cc-prompts-archive/2026-04/$f"
        echo "untracked: mv $f"
      fi
    fi
  done

### 4.4 Index file

Create `docs/cc-prompts-archive/2026-04/README.md`:

```markdown
# CC Prompt Archive — 2026-04

Archived prompts for completed work. Each file documents the
specification + execution prompt for a feature batch.

| File | Feature | Shipped in |
|---|---|---|
| CC_PROMPT_IV_2_ORCHESTRATOR.md | IV.2 batch coordination | v0.34.0 |
| CC_PROMPT_IV_3_BATCH.md | IV.3 fixes | v0.34.0 |
| CC_PROMPT_IV_4_BATCH.md | IV.4 safe features (F1/F2/F6/F11) | v0.34.0 |
| CC_PROMPT_IV_6_ZMQ_BRIDGE_FIX.md | IV.6 ZMQ ephemeral REQ | v0.34.0 |
| CC_PROMPT_IV_7_IPC_TRANSPORT.md | IV.7 ipc:// experiment | superseded by H5 fix in v0.39.0 |
| CC_PROMPT_OVERNIGHT_SWARM_2026-04-24.md | Overnight harden batch | v0.36.0 |
| CC_PROMPT_VAULT_BUILD_2026-04-26.md | Initial vault construction | (vault, not repo release) |
| CC_PROMPT_VAULT_AUDIT_2026-04-27.md | Post-build vault audit | (vault) |
| CC_PROMPT_F3_ANALYTICS_WIRING.md | F3 spec | v0.40.0 |
| CC_PROMPT_F3_OVERNIGHT_RUNNER.md | F3 5-cycle runner | v0.40.0 |
| CC_PROMPT_F10_SENSOR_DIAGNOSTICS_ALARM.md | F10 spec | v0.41.0 |
| CC_PROMPT_VAULT_SUBSYSTEM_QUARTET.md | 4 vault notes | v0.41.0 |
| CC_PROMPT_OVERNIGHT_RUNNER_2026-04-29.md | Multi-track overnight | v0.41.0 |
| CC_PROMPT_METASWARM_2026-04-29.md | 24-dispatch metaswarm | (metaswarm session) |
```

### 4.5 Commit

  git add docs/cc-prompts-archive/
  git commit -m "chore(cleanup): archive completed CC_PROMPT files (2026-04 batch)

Moved 14 completed CC_PROMPT_*.md files from repo root into
docs/cc-prompts-archive/2026-04/. Each prompt documents a feature
spec + execution that shipped in v0.34.0..v0.41.0 (or vault build
sessions).

Kept in root (active or pending):
- CC_PROMPT_CALIBRATION_2026-04-30.md (running)
- CC_PROMPT_REPO_CLEANUP_2026-04-30.md (this session)
- CC_PROMPT_METASWARM_F17.md (pending implementation)

Index at docs/cc-prompts-archive/2026-04/README.md.

Some files were untracked (mv) others tracked (git mv) — git history
preserved for tracked.

Ref: CC_PROMPT_REPO_CLEANUP_2026-04-30.md Phase 2
Risk: low — archive moves only, no content changes."

---

## 5. Phase 3 — Archive stale top-level docs

### 5.1 Create archive

  mkdir -p docs/handoffs-archive/2026-04/

### 5.2 Move stale handoffs and session details

  cd ~/Projects/cryodaq
  for f in HANDOFF_2026-04-20_GLM.md SESSION_DETAIL_2026-04-20.md; do
    if [ -f "$f" ]; then
      if git ls-files --error-unmatch "$f" >/dev/null 2>&1; then
        git mv "$f" "docs/handoffs-archive/2026-04/$f"
      else
        mv "$f" "docs/handoffs-archive/2026-04/$f"
      fi
    fi
  done

### 5.3 Move CODEX_ARCHITECTURE_CONTROL_PLANE.md to docs/

  if [ -f CODEX_ARCHITECTURE_CONTROL_PLANE.md ]; then
    if git ls-files --error-unmatch CODEX_ARCHITECTURE_CONTROL_PLANE.md >/dev/null 2>&1; then
      git mv CODEX_ARCHITECTURE_CONTROL_PLANE.md docs/codex-architecture-control-plane.md
    else
      mv CODEX_ARCHITECTURE_CONTROL_PLANE.md docs/codex-architecture-control-plane.md
    fi
  fi

  # Update any references
  grep -rln "CODEX_ARCHITECTURE_CONTROL_PLANE" \
    --include="*.md" --include="*.py" \
    ~/Projects/cryodaq/ 2>/dev/null

  # If references exist outside the file itself, sed-replace them
  # (architect verifies in handoff)

### 5.4 Commit

  git add docs/handoffs-archive/ docs/codex-architecture-control-plane.md \
          [any files modified for reference updates]

  git commit -m "chore(cleanup): archive stale top-level handoffs + docs

- HANDOFF_2026-04-20_GLM.md → docs/handoffs-archive/2026-04/
- SESSION_DETAIL_2026-04-20.md → docs/handoffs-archive/2026-04/
- CODEX_ARCHITECTURE_CONTROL_PLANE.md → docs/codex-architecture-control-plane.md
  (moved from root + renamed to lowercase per docs/ convention)

Reference updates: <count> files updated to point to new path.

Ref: CC_PROMPT_REPO_CLEANUP_2026-04-30.md Phase 3
Risk: low — moves + reference updates."

---

## 6. Phase 4 — artifacts/ structure cleanup

### 6.1 Current state

  ls -la ~/Projects/cryodaq/artifacts/

Plain markdown files at top-level of artifacts/:
- 2026-04-28-pre-ultrareview-recon.md
- 2026-04-28-ultrareview-ready.md
- 2026-04-29-ccr-chutes-recon.md
- 2026-04-29-plugin-discovery.md

### 6.2 Move into recon/ subdirectory

  mkdir -p artifacts/recon/

  cd ~/Projects/cryodaq/artifacts/
  for f in 2026-04-28-pre-ultrareview-recon.md \
           2026-04-28-ultrareview-ready.md \
           2026-04-29-ccr-chutes-recon.md \
           2026-04-29-plugin-discovery.md; do
    if [ -f "$f" ]; then
      if git ls-files --error-unmatch "$f" >/dev/null 2>&1; then
        git mv "$f" "recon/$f"
      else
        mv "$f" "recon/$f"
      fi
    fi
  done

### 6.3 Index file

Create `artifacts/recon/README.md`:

```markdown
# Recon artifacts

One-shot reconnaissance documents — usually CC reading
configuration / state / inventories before architect-driven
changes. Date-prefixed for chronological clarity.

| Date | File | Purpose |
|---|---|---|
| 2026-04-28 | pre-ultrareview-recon.md | State before ultrareview |
| 2026-04-28 | ultrareview-ready.md | Ultrareview-ready confirmation |
| 2026-04-29 | ccr-chutes-recon.md | CCR + Chutes catalog inventory |
| 2026-04-29 | plugin-discovery.md | OMC + Gemini + Metaswarm plugin discovery |
```

### 6.4 Commit

  git add artifacts/recon/
  git commit -m "chore(cleanup): move recon artifacts into artifacts/recon/

4 plain-markdown recon documents moved from artifacts/ root into
artifacts/recon/ for clearer hierarchy.

Index at artifacts/recon/README.md.

Ref: CC_PROMPT_REPO_CLEANUP_2026-04-30.md Phase 4
Risk: low — moves only."

---

## 7. Phase 5 — Update living docs

### 7.1 PROJECT_STATUS.md refresh

Read current PROJECT_STATUS.md (last modified 2026-04-24). Identify
stale sections.

Update sections to reflect:
- Current version: v0.42.0 (was probably v0.34.0 at last update)
- Recent releases: v0.34.0 → v0.42.0 chain (retroactive 2026-04-27)
- Open features: F19, F20, F21, F22, F23, F24, F25 (deferred from
  Task A verification + F-task plot/dashboard items)
- Blocked: F5 (Hermes), F7 (Web API), F15 (Linux packaging)
- Research: F8 (cooldown ML), F9 (TIM auto-report)
- Done features: F1, F2, F3, F4, F6, F10, F11

Cross-reference ROADMAP.md as source of truth. Don't invent state.

If a section is still completely accurate as-is: leave alone, but
update the "last updated" date at top.

### 7.2 DOC_REALITY_MAP.md refresh

Read current DOC_REALITY_MAP.md (last modified 2026-04-17, 13 days
stale). This document maps which code modules have which docs.

Update for new modules / changes since 2026-04-17:
- F3 widgets in src/cryodaq/gui/shell/views/analytics_widgets.py
- F4 lazy replay (cache logic in MainWindowV2)
- F10 sensor diagnostics → alarm bridge
- v0.42.0 safety hotfix files (safety_manager update_target docstring,
  zmq_bridge _SLOW_COMMANDS expansion)
- New vault notes (4 architectural quartet + F4 + Sensor diag → alarm)

Don't invent module-doc relationships. Verify via grep.

### 7.3 docs/NEXT_SESSION.md refresh

Read current docs/NEXT_SESSION.md. This is the architect's "what's
next" pointer.

Update to:
- Outstanding F-tasks: F19, F20, F21, F22, F23, F24, F25
- Outstanding ops: Lab Ubuntu PC verification of v0.39.0 H5 fix
- Outstanding ops: GUI .cof minor wiring
- Plugin disposition: oh-my-claudecode disable for CryoDAQ
  (post-calibration architect decision)
- ORCHESTRATION v1.3 update pending (plugin auto-load awareness +
  hallucination verification + metaswarm dispatch realities)

Recent completions:
- v0.40.0 F3 + F4
- v0.41.0 F10 + 4 vault subsystem notes
- v0.42.0 HF1 + HF2 safety hotfix
- 2026-04-29 metaswarm session (24 dispatches, 14 useful, 7 verified findings)
- 2026-04-30 calibration session (per CC_PROMPT_CALIBRATION_2026-04-30.md)

### 7.4 Commit

  git add PROJECT_STATUS.md DOC_REALITY_MAP.md docs/NEXT_SESSION.md
  git commit -m "docs(cleanup): refresh living docs to current state

PROJECT_STATUS.md: updated from v0.34.0 baseline to v0.42.0 reality.
F-task index reconciled with ROADMAP.md.

DOC_REALITY_MAP.md: 13-day-stale code-doc mapping updated for F3,
F4, F10, v0.42.0 hotfix paths, and new vault notes.

docs/NEXT_SESSION.md: outstanding tasks list updated. Recent
completions documented. Plugin disposition noted as pending
architect decision.

Ref: CC_PROMPT_REPO_CLEANUP_2026-04-30.md Phase 5
Risk: medium — content updates to authoritative state docs.
Architect should spot-check before further action."

---

## 8. Phase 6 — Final repo audit report

Write `docs/REPO_AUDIT_REPORT.md` (replaces existing if present, OR
add timestamp section if existing report should be preserved as
historical):

```markdown
# Repo Audit Report — 2026-04-30

Last audit: <previous date if present>
This audit: 2026-04-30

## State
- Master HEAD: <SHA>
- Latest tag: v0.42.0 (2026-04-29)
- Total commits since start: <count>
- Test count: 1931 passing, 4 skipped
- LOC runtime: ~50K
- LOC tests: ~36K

## Cleanup actions taken (this audit)
- 14 CC_PROMPT files archived to docs/cc-prompts-archive/2026-04/
- 2 stale handoffs moved to docs/handoffs-archive/2026-04/
- 1 doc moved out of root into docs/
- 4 recon files reorganized into artifacts/recon/
- 3 living docs refreshed (PROJECT_STATUS, DOC_REALITY_MAP, NEXT_SESSION)

## Outstanding (not addressed this pass — architect-only decisions)
- ~/ shell-mistake directory (architect rm -rf when present)
- draft.py / draft2.py (architect decides keep / archive / delete)
- graphify-out.stale-pre-merge/ (gitignored, architect can rm locally)
- agentswarm/ historical artifact (gitignored, architect can move outside repo)

## Ignored / out-of-scope
- src/, tests/, config/ (no cleanup — production)
- .venv/, .pytest_cache/, build/, dist/ (gitignored, not visible to git)
- .worktrees/, .swarm/, .audit-run/, .omc/ (gitignored agent workspaces)
- artifacts/calibration/ (active session, not touched)

## Repo root after cleanup
[list of remaining root-level files]

## Health metrics
- Untracked files in root: <count>
- Stale docs (>14 days unmodified): <count>
- TODO / FIXME density in src: <count>
```

Commit Phase 6:

  git add docs/REPO_AUDIT_REPORT.md
  git commit -m "docs(cleanup): final repo audit report 2026-04-30

Documents cleanup actions taken + state of repo post-housekeeping.
Reference for next audit.

Ref: CC_PROMPT_REPO_CLEANUP_2026-04-30.md Phase 6
Risk: docs only."

---

## 9. Phase 7 — Master summary + push

### 9.1 Master summary handoff

Write `artifacts/handoffs/2026-04-30-repo-cleanup-summary.md`:

```markdown
# Repo Cleanup Summary — 2026-04-30

## Phases executed
| Phase | Status | Commit | Risk |
|---|---|---|---|
| 0 Recon + audit | ... | <SHA> | none |
| 1 Investigation | ... | <SHA> | none |
| 2 CC_PROMPT archive | ... | <SHA> | low |
| 3 Top-level archive | ... | <SHA> | low |
| 4 artifacts/ cleanup | ... | <SHA> | low |
| 5 Living docs refresh | ... | <SHA> | medium |
| 6 Audit report | ... | <SHA> | none |
| 7 This summary | ... | n/a | n/a |

## Files moved (count)
- CC_PROMPT_*.md: 14 → docs/cc-prompts-archive/2026-04/
- HANDOFF/SESSION top-level: 2 → docs/handoffs-archive/2026-04/
- Top-level → docs/: 1 (codex-architecture-control-plane)
- artifacts/ → artifacts/recon/: 4

## Files updated (living docs)
- PROJECT_STATUS.md
- DOC_REALITY_MAP.md
- docs/NEXT_SESSION.md

## Files explicitly NOT touched
- All src/, tests/, config/ source code
- Active prompts in root
- artifacts/calibration/ (active session)
- .worktrees/, .swarm/, .audit-run/, .omc/ (gitignored workspaces)

## Architect decisions remaining
- ~/ directory: rm -rf when present (shell mistake)
- draft.py, draft2.py: archive/delete decision pending Phase 1 contents review
- agentswarm/, graphify-out.stale-pre-merge/: local-only cleanup at architect convenience

## Test impact
None expected (no source code touched). Verification: pytest one-shot
sanity check before close (architect option, not auto-run).

## Outstanding for next session
- Plugin disposition (oh-my-claudecode for CryoDAQ)
- ORCHESTRATION v1.3
- Calibration matrix application to multi-model-consultation skill
```

### 9.2 Optional sanity test

  cd ~/Projects/cryodaq
  .venv/bin/pytest tests/ -x --co -q | tail -5
  # Just collection check, not full run; verifies no test imports broke

If collection fails: STOP, report. If clean: proceed.

### 9.3 Final push

  git status
  git log --oneline -10
  git push origin master

### 9.4 Wake-up echo

```bash
echo "═══════════════════════════════════════"
echo "REPO CLEANUP COMPLETE 2026-04-30"
echo "═══════════════════════════════════════"
echo "Master: $(git log -1 --format='%h %s')"
echo "Files in root (excluding hidden):"
ls ~/Projects/cryodaq/ | grep -v "^\." | head -30
echo "═══════════════════════════════════════"
echo "Architect: read artifacts/handoffs/2026-04-30-repo-cleanup-summary.md"
```

---

## 10. Hard stops

- Phase 0 finds master HEAD different from expected → STOP, drift
- Phase 5 update breaks ROADMAP.md, CHANGELOG.md, or other authoritative
  state → STOP, revert that commit
- Test collection fails after cleanup (Phase 7.2) → STOP, may need
  selective revert
- Calibration session detected as still running (active CC processes
  on calibration paths) → STOP, wait for calibration to close

A single phase failure does NOT stop the cleanup. Move to next phase
with that finding documented as STOP_AT_PHASE_N in summary.

---

## 11. Architect comm-out discipline

- Architect available after calibration closes (morning).
- This session runs after calibration. May overlap morning architect
  presence — no need for night-strict comm-out.
- For ambiguous decisions: write "ARCHITECT DECISION NEEDED" in
  summary and continue. Don't auto-decide on:
  - Whether draft.py / draft2.py should be deleted
  - Whether ~/ directory should be removed
  - Whether to update particular section of living doc

---

## 12. Begin

Start NOW (after calibration session closes — verify calibration
master summary exists before beginning).

  ls ~/Projects/cryodaq/artifacts/calibration/2026-04-30/MASTER-SUMMARY.md
  # Must exist before this prompt proceeds

If calibration not yet complete: STOP, wait. This prompt does not
race calibration.

If calibration complete: proceed Phase 0.

GO.
