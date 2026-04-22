# Solo Handoff Readiness Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the B1 handoff cleanup as a truthful single-agent tranche: remove residual overclaim from authoritative docs, remove misleading simulated swarm artifacts, verify against source files, and leave the branch in a clean handoff-ready state.

**Architecture:** Treat this as a documentation-only truth-recovery pass. Recompute the runtime facts from the JSONL, then align the highest-authority current-state docs to the runbook and control-plane ceiling before touching lower-level notes. Do not pretend this was a completed swarm run; either delete simulated swarm review artifacts or replace them with one honest solo verification note.

**Tech Stack:** Markdown, Git, `python3`, `rg`, `sed`, `apply_patch`

---

### Task 1: Re-establish the Solo Authority Baseline

**Files:**
- Inspect: `/Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/artifacts/diagnostics/b1-devmac-current-master.jsonl`
- Inspect: `/Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/docs/runbooks/B1_CURRENT_MASTER_RUNBOOK.md`
- Inspect: `/Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/CODEX_ARCHITECTURE_CONTROL_PLANE.md`
- Inspect: `/Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/artifacts/reviews/roadmap-metaswarm-arbitration.md`
- Inspect: `/Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/docs/decisions/ROADMAP_RESOLUTION_LEDGER.md`
- Inspect: `/Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/docs/B1_NEXT_PHASE_HANDOFF.md`
- Inspect: `/Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/artifacts/diagnostics/b1-devmac-run-note.md`

- [ ] **Step 1: Verify branch, HEAD, and dirty state**

Run:

```bash
cd /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery
git branch --show-current
git rev-parse HEAD
git rev-parse origin/master
git status --short
git diff --name-only origin/master..HEAD
```

Expected:
- branch is `codex/safe-merge-b1-truth-recovery`
- HEAD is still `0a4ae040bf0698b3804d0b440391be2b9643ff2b` unless intentionally advanced
- tracked modified docs and untracked handoff/calibration artifacts are visible

- [ ] **Step 2: Recompute the raw runtime facts from the JSONL**

Run:

```bash
python3 - <<'PY'
import json
from datetime import datetime
p='/Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/artifacts/diagnostics/b1-devmac-current-master.jsonl'
rows=[json.loads(line) for line in open(p)]
fmt=lambda s: datetime.fromisoformat(s)
first=rows[0]
first_fail=next(r for r in rows if r.get('bridge_reply',{}).get('ok') is False and r.get('direct_reply',{}).get('ok') is False)
last=rows[-1]
print('sample_count=', len(rows))
print('first_sample=', first['ts_utc'])
print('first_failed_sample=', first_fail['ts_utc'])
print('final_sample=', last['ts_utc'])
print('time_to_failure=', (fmt(first_fail['ts_utc'])-fmt(first['ts_utc'])).total_seconds())
print('wall_clock=', (fmt(last['ts_utc'])-fmt(first['ts_utc'])).total_seconds())
PY
```

Expected:
- `sample_count= 56`
- `time_to_failure= 52.47795`
- `wall_clock= 175.566708`

- [ ] **Step 3: Restate the evidence ceiling in a scratch note before editing**

Use this exact text in your terminal notes or scratchpad:

```text
Allowed:
- B1 reproduced with evidence
- ~52 seconds after first sample
- ~176 seconds wall-clock
- both bridge and direct paths fail together
- engine REP path or lower transport implicated
- IV.7 justified as bounded experiment
- baseline for comparison established
- TCP hypothesis under test

Not allowed:
- TCP is the culprit
- TCP transport is culprit
- TCP transport proven
- root cause proven
- Engine REP path failure
- transport layer as if mechanism is proven
```

- [ ] **Step 4: Confirm the exact remaining offending lines before patching**

Run:

```bash
rg -n "TCP transport is culprit|likely culprit|Engine REP path failure|transport layer" \
  /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/artifacts/reviews/roadmap-metaswarm-arbitration.md \
  /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/docs/decisions/ROADMAP_RESOLUTION_LEDGER.md \
  /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/docs/B1_NEXT_PHASE_HANDOFF.md \
  /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/artifacts/diagnostics/b1-devmac-run-note.md
```

Expected matches include:
- `roadmap-metaswarm-arbitration.md:41`
- `ROADMAP_RESOLUTION_LEDGER.md:68`
- `ROADMAP_RESOLUTION_LEDGER.md:100`
- `ROADMAP_RESOLUTION_LEDGER.md:159`
- `B1_NEXT_PHASE_HANDOFF.md:85`
- `b1-devmac-run-note.md:137`

### Task 2: Fix the Top-Level Authoritative Files First

**Files:**
- Modify: `/Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/artifacts/reviews/roadmap-metaswarm-arbitration.md`
- Modify: `/Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/docs/decisions/ROADMAP_RESOLUTION_LEDGER.md`

- [ ] **Step 1: Patch the arbitration doc to remove TCP culprit language**

Apply this exact replacement:

```diff
- Falsification criteria: If B1 reproduces on ipc://, hypothesis falsified; if not, TCP transport is culprit
+ Falsification criteria: If B1 reproduces on ipc://, TCP-specific hypothesis weakened; if not, TCP-specific transport hypothesis gains support but remains unproven
```

- [ ] **Step 2: Patch the ledger classification row to match the runbook exactly**

Apply this exact replacement:

```diff
- | Classification | Engine REP path failure (NOT bridge-specific) |
+ | Classification | Engine REP path or lower transport implicated (NOT bridge-specific) |
```

- [ ] **Step 3: Patch the first IV.7 rationale block in the ledger**

Apply this exact replacement:

```diff
-   - Experimental design: If B1 reproduces on ipc://, TCP hypothesis falsified; if not, TCP is implicated as likely culprit
+   - Experimental design: If B1 reproduces on ipc://, TCP-specific hypothesis weakened; if not, TCP-specific transport hypothesis gains support but remains unproven
```

- [ ] **Step 4: Patch the second IV.7 rationale block in the ledger**

Apply this exact replacement:

```diff
- - Experimental design: If B1 reproduces on ipc://, TCP hypothesis falsified; if not, TCP is implicated as likely culprit
+ - Experimental design: If B1 reproduces on ipc://, TCP-specific hypothesis weakened; if not, TCP-specific transport hypothesis gains support but remains unproven
```

- [ ] **Step 5: Verify the top-level files now match the ceiling**

Run:

```bash
sed -n '36,42p;150,156p' /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/artifacts/reviews/roadmap-metaswarm-arbitration.md
sed -n '68,75p;96,101p;155,160p' /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/docs/decisions/ROADMAP_RESOLUTION_LEDGER.md
```

Expected:
- no `culprit`
- no `Engine REP path failure`
- no wording stronger than `gains support but remains unproven`

### Task 3: Fix the Remaining Lower-Level Drift

**Files:**
- Modify: `/Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/docs/B1_NEXT_PHASE_HANDOFF.md`
- Modify: `/Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/artifacts/diagnostics/b1-devmac-run-note.md`

- [ ] **Step 1: Patch the handoff falsification line**

Apply this exact replacement:

```diff
- - **Falsification design:** If B1 reproduces on `ipc://`, TCP hypothesis falsified; if not, TCP is the likely culprit
+ - **Falsification design:** If B1 reproduces on `ipc://`, TCP-specific hypothesis weakened; if not, TCP-specific transport hypothesis gains support but remains unproven
```

- [ ] **Step 2: Patch the run-note closing summary**

Apply this exact replacement:

```diff
- *This run note documents successful B1 reproduction on current master. Engine REP path failure at ~52s, affecting both bridge and direct paths. Root cause still unknown - IV.7 ipc:// experiment remains relevant diagnostic path.*
+ *This run note documents successful B1 reproduction on current master. Engine REP path or lower transport is implicated at ~52s, affecting both bridge and direct paths. Root cause still unknown; IV.7 ipc:// remains a bounded diagnostic path.*
```

- [ ] **Step 3: Verify the lower-level files now agree with the top-level docs**

Run:

```bash
sed -n '82,86p' /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/docs/B1_NEXT_PHASE_HANDOFF.md
sed -n '133,138p' /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/artifacts/diagnostics/b1-devmac-run-note.md
```

Expected:
- no `likely culprit`
- no `Engine REP path failure`

### Task 4: Remove Misleading Simulated Swarm Artifacts and Replace Them with One Honest Solo Note

**Files:**
- Delete: `/Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/artifacts/reviews/final-authority-calibration-codex.md`
- Delete: `/Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/artifacts/reviews/final-authority-calibration-gemini.md`
- Delete: `/Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/artifacts/reviews/final-authority-calibration-metaswarm.md`
- Create: `/Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/artifacts/reviews/final-handoff-readiness-solo.md`

- [ ] **Step 1: Delete the three simulated multi-agent calibration artifacts**

Run:

```bash
rm /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/artifacts/reviews/final-authority-calibration-codex.md
rm /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/artifacts/reviews/final-authority-calibration-gemini.md
rm /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/artifacts/reviews/final-authority-calibration-metaswarm.md
```

Expected:
- files are removed from the working tree

- [ ] **Step 2: Create one honest solo verification note**

Write this exact file content:

```markdown
# Final Handoff Readiness - Solo Verification

**Date:** 2026-04-22  
**Mode:** degraded single-agent review  
**Branch:** `codex/safe-merge-b1-truth-recovery`

## Runtime Facts

- 56 samples
- first failure at ~52.5s after first sample
- wall-clock capture ~175.6s
- both bridge and direct paths fail together

## Evidence Ceiling

- strongest supported claim: engine REP path or lower transport implicated
- IV.7 status: justified as bounded experiment
- TCP remains a hypothesis under test, not a proven culprit

## Verification Result

- top-level current-state docs checked against JSONL, runbook, and control plane
- residual `culprit` / `failure` overclaim removed from authoritative docs
- historical handoff doc remains demoted by warning header

## Swarm Status

The intended multi-agent swarm did not run. This note records a truthful solo verification pass only.
```

- [ ] **Step 3: Verify the artifact set is now honest**

Run:

```bash
ls -1 /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/artifacts/reviews/final-*.md
```

Expected:
- `final-handoff-readiness-solo.md` exists
- no `final-authority-calibration-gemini.md`
- no `final-authority-calibration-codex.md`
- no `final-authority-calibration-metaswarm.md`

### Task 5: Source-File Verification, Stage, and Commit

**Files:**
- Verify: `/Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/artifacts/reviews/roadmap-metaswarm-arbitration.md`
- Verify: `/Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/docs/decisions/ROADMAP_RESOLUTION_LEDGER.md`
- Verify: `/Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/docs/B1_NEXT_PHASE_HANDOFF.md`
- Verify: `/Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/ROADMAP.md`
- Verify: `/Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/artifacts/diagnostics/b1-devmac-run-note.md`

- [ ] **Step 1: Run the prohibited-phrase sweep on authoritative files**

Run:

```bash
rg -n "TCP is the culprit|TCP transport is culprit|strongly justified|strengthened by evidence|significantly strengthened|bypass TCP loopback entirely|working hypothesis|Engine REP path failure" \
  /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/artifacts/reviews/roadmap-metaswarm-arbitration.md \
  /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/docs/decisions/ROADMAP_RESOLUTION_LEDGER.md \
  /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/docs/B1_NEXT_PHASE_HANDOFF.md \
  /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/ROADMAP.md \
  /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/artifacts/diagnostics/b1-devmac-run-note.md
```

Expected:
- no matches

- [ ] **Step 2: Run the semantic sweep on top-level files**

Run:

```bash
rg -n "culprit|likely culprit|proven|entirely|strengthened|working hypothesis|transport layer|REP path failure|ready for IV.7" \
  /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/artifacts/reviews/roadmap-metaswarm-arbitration.md \
  /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/docs/decisions/ROADMAP_RESOLUTION_LEDGER.md \
  /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/docs/B1_NEXT_PHASE_HANDOFF.md \
  /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/ROADMAP.md
```

Expected:
- only justified uses remain, such as negative examples in the handoff doc or historical context explicitly marked as such

- [ ] **Step 3: Confirm the worktree now contains only intentional docs for handoff**

Run:

```bash
git status --short
```

Expected:
- no simulated calibration artifacts
- only intended handoff and review docs remain

- [ ] **Step 4: Stage the truthful single-agent cleanup tranche**

Run:

```bash
git add \
  /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/artifacts/diagnostics/b1-devmac-run-note.md \
  /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/artifacts/reviews/roadmap-metaswarm-arbitration.md \
  /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/docs/decisions/ROADMAP_RESOLUTION_LEDGER.md \
  /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/docs/B1_NEXT_PHASE_HANDOFF.md \
  /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/artifacts/reviews/final-handoff-readiness-solo.md
git rm \
  /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/artifacts/reviews/final-authority-calibration-codex.md \
  /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/artifacts/reviews/final-authority-calibration-gemini.md \
  /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/artifacts/reviews/final-authority-calibration-metaswarm.md
```

Expected:
- staged adds for the corrected authoritative docs
- staged deletes for the simulated calibration artifacts

- [ ] **Step 5: Commit the solo cleanup**

Run:

```bash
git commit -m "docs: finish solo B1 handoff cleanup"
```

Expected:
- one commit containing only truthful handoff-readiness cleanup changes

---

## Self-Review

- Spec coverage: The plan covers authority-baseline recheck, exact residual wording fixes, honest handling of degraded solo execution, source-file verification, and clean handoff/commit.
- Placeholder scan: No `TBD`, `TODO`, or abstract “fix wording” steps remain; every edit has exact replacement text or exact commands.
- Type consistency: All wording targets use the same ceiling throughout: `engine REP path or lower transport implicated`, `bounded experiment`, `TCP-specific hypothesis gains support but remains unproven`.
