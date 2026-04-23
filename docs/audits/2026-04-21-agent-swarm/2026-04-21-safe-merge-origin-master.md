# Safe Merge From Truth-Recovery Branch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a clean integration branch from `origin/master` that carries only the intended B1 truth-recovery and changelog corrections, without importing the polluted local `master` review-pack history.

**Architecture:** This is a non-rewriting merge plan. Leave the current local `master` untouched, create a fresh worktree and branch directly from `origin/master`, then cherry-pick only the vetted commits from `codex/b1-truth-recovery` in two tranches: mandatory B1 tooling/docs first, optional changelog reconstruction second.

**Tech Stack:** `git`, `git worktree`, `git cherry-pick`, `pytest`, `rg`, CryoDAQ docs/runbooks

---

## File Structure And Scope Lock

**Mandatory merge candidates**

- `ROADMAP.md`
  Responsibility: authoritative B1 roadmap status synced to current repo truth.
- `CODEX_ARCHITECTURE_CONTROL_PLANE.md`
  Responsibility: architecture control document for the next B1 phase.
- `tools/_b1_diagnostics.py`
  Responsibility: reusable helper functions for bridge snapshots and direct engine probes.
- `tools/diag_zmq_b1_capture.py`
  Responsibility: canonical JSONL capture CLI for B1 evidence runs.
- `docs/runbooks/B1_CURRENT_MASTER_RUNBOOK.md`
  Responsibility: exact dev-Mac evidence procedure for current-master B1 capture.
- `tests/tools/test_b1_diagnostics.py`
  Responsibility: unit coverage for snapshot and direct-probe helpers.
- `tests/tools/test_diag_zmq_b1_capture.py`
  Responsibility: capture CLI coverage.

**Optional merge candidate**

- `CHANGELOG.md`
  Responsibility: retroactive release reconstruction for post-`v0.33.0` history, including the corrected next version line `0.36.0`.

**Explicitly excluded from the safe merge**

- `docs/superpowers/specs/2026-04-21-next-phase-recovery-design.md`
  Reason: useful branch-local planning artifact, not authoritative product or operator documentation.
- Local `master` accidental review-pack chain:
  - `6ecc5d0`
  - `b2dc6f6`
  - `8f9e673`
  - `8eaf1b4`
  - `7d1c337`
- Review-pack docs/tests that exist only because of the accidental `master` chain:
  - `docs/runbooks/B1_TRUTH_RECOVERY_REVIEW_CONTROL.md`
  - `docs/runbooks/B1_REVIEW_PROMPT_CODEX.md`
  - `docs/runbooks/B1_REVIEW_PROMPT_GEMINI.md`
  - `docs/runbooks/B1_REVIEW_PROMPT_METASWARM.md`
  - `docs/runbooks/B1_REVIEW_PROMPT_CODEX_ON_GEMINI.md`
  - `docs/runbooks/B1_REVIEW_PROMPT_GEMINI_ON_CODEX.md`
  - `docs/runbooks/B1_REVIEW_LEDGER.md`
  - `docs/runbooks/B1_REVIEW_PACK_SWARM_FIX_PROMPT.md`
  - `tests/tools/test_b1_review_pack.py`
  - `tests/tools/test_b1_review_pack_swarm_fix_prompt.py`

**Source branch**

- `codex/b1-truth-recovery`
- source worktree: `/Users/vladimir/Projects/cryodaq/.worktrees/codex-b1-truth-recovery`

**Target integration branch**

- `codex/safe-merge-b1-truth-recovery`
- target worktree: `/Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery`

**Cherry-pick set**

- Mandatory tranche:
  - `196d200`
  - `7f1f607`
  - `9ac10f7`
  - `0782f4c`
  - `1096ae5`
  - `23c5f00`
  - `9151a65`
- Optional changelog tranche:
  - `c14cde4`

### Task 1: Freeze Baseline And Create Clean Integration Branch

**Files:**
- No tracked file changes in this task.
- Verify only: `/Users/vladimir/Projects/cryodaq/.git`
- Verify only: `/Users/vladimir/Projects/cryodaq/.worktrees/codex-b1-truth-recovery`

- [ ] **Step 1: Record the true starting points**

Run:

```bash
git -C /Users/vladimir/Projects/cryodaq fetch origin
git -C /Users/vladimir/Projects/cryodaq rev-parse origin/master
git -C /Users/vladimir/Projects/cryodaq rev-parse master
git -C /Users/vladimir/Projects/cryodaq rev-parse codex/b1-truth-recovery
git -C /Users/vladimir/Projects/cryodaq log --oneline --decorate --max-count=10 master
```

Expected:
- `origin/master` resolves to `256da7a5b0adaf6ed3cd16313f19e106558d6caa`
- `master` is ahead of `origin/master`
- `codex/b1-truth-recovery` is ahead of `256da7a`
- local `master` log includes the accidental review-pack chain

- [ ] **Step 2: Create the clean integration worktree from `origin/master`**

Run:

```bash
git -C /Users/vladimir/Projects/cryodaq worktree add \
  /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery \
  -b codex/safe-merge-b1-truth-recovery \
  origin/master
```

Expected:
- worktree is created successfully
- branch `codex/safe-merge-b1-truth-recovery` points at `origin/master`

- [ ] **Step 3: Verify the new worktree is clean and detached from local `master` pollution**

Run:

```bash
git -C /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery status --short --branch
git -C /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery log --oneline --decorate -5
```

Expected:
- status prints `## codex/safe-merge-b1-truth-recovery`
- no modified or untracked files
- top commit equals `256da7a`

- [ ] **Step 4: Prove the accidental review-pack chain is absent in the new branch**

Run:

```bash
git -C /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery log --oneline origin/master..HEAD
```

Expected:
- no output

- [ ] **Step 5: Commit checkpoint**

There is no new tracked-file commit in this task. The checkpoint is the new clean branch and worktree. Record that branch creation succeeded before moving on.

### Task 2: Cherry-Pick The Mandatory Truth-Recovery Tranche

**Files:**
- Create: `tools/_b1_diagnostics.py`
- Create: `tools/diag_zmq_b1_capture.py`
- Create: `docs/runbooks/B1_CURRENT_MASTER_RUNBOOK.md`
- Create: `tests/tools/test_b1_diagnostics.py`
- Create: `tests/tools/test_diag_zmq_b1_capture.py`
- Modify: `ROADMAP.md`
- Modify: `CODEX_ARCHITECTURE_CONTROL_PLANE.md`

- [ ] **Step 1: Reconfirm the exact commit list before applying it**

Run:

```bash
git -C /Users/vladimir/Projects/cryodaq show --stat --summary 196d200 7f1f607 9ac10f7 0782f4c 1096ae5 23c5f00 9151a65
```

Expected:
- only the seven mandatory target files above are touched
- no review-pack docs/tests appear in these commit stats

- [ ] **Step 2: Cherry-pick the mandatory tranche onto the clean branch**

Run:

```bash
git -C /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery cherry-pick \
  196d200 7f1f607 9ac10f7 0782f4c 1096ae5 23c5f00 9151a65
```

Expected:
- seven cherry-pick commits apply cleanly
- branch now contains the B1 tooling/runbook/roadmap updates without any review-pack deletions

If this command conflicts, stop and run:

```bash
git -C /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery cherry-pick --abort
```

Expected:
- branch returns to the clean pre-cherry-pick state

- [ ] **Step 3: Run the focused tool tests**

Run:

```bash
/Users/vladimir/Projects/cryodaq/.venv/bin/pytest \
  /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/tests/tools/test_b1_diagnostics.py \
  /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/tests/tools/test_diag_zmq_b1_capture.py \
  -q
```

Expected:
- `5 passed`

- [ ] **Step 4: Verify the diff against `origin/master` contains only the intended truth-recovery surface**

Run:

```bash
git -C /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery diff --name-status origin/master..HEAD
```

Expected:

```text
M  ROADMAP.md
M  CODEX_ARCHITECTURE_CONTROL_PLANE.md
A  docs/runbooks/B1_CURRENT_MASTER_RUNBOOK.md
A  tests/tools/test_b1_diagnostics.py
A  tests/tools/test_diag_zmq_b1_capture.py
A  tools/_b1_diagnostics.py
A  tools/diag_zmq_b1_capture.py
```

- [ ] **Step 5: Commit checkpoint**

Cherry-pick created the commits. Verify the preserved commit chain:

```bash
git -C /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery log --oneline --decorate -10
```

Expected:
- top of branch includes `9151a65`, `23c5f00`, `1096ae5`, `0782f4c`, `9ac10f7`, `7f1f607`, `196d200`

### Task 3: Cherry-Pick The Optional Changelog Reconstruction

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Review the changelog-only commit before applying it**

Run:

```bash
git -C /Users/vladimir/Projects/cryodaq show --stat --summary c14cde4
```

Expected:
- only `CHANGELOG.md` is touched

- [ ] **Step 2: Cherry-pick the changelog reconstruction commit**

Run:

```bash
git -C /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery cherry-pick c14cde4
```

Expected:
- one commit applies cleanly
- no `docs/superpowers/specs/...` file is introduced

If this command conflicts, stop and run:

```bash
git -C /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery cherry-pick --abort
```

Expected:
- branch returns to the post-Task-2 state

- [ ] **Step 3: Verify the version-line reconstruction**

Run:

```bash
rg -n "^## \\[(0\\.36\\.0|0\\.35\\.0|0\\.34\\.0|0\\.33\\.0)\\]" \
  /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/CHANGELOG.md
```

Expected:

```text
## [0.36.0]
## [0.35.0]
## [0.34.0]
## [0.33.0]
```

- [ ] **Step 4: Verify the Unreleased note does not claim `0.34.0` is the next formal line**

Run:

```bash
sed -n '1,40p' /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/CHANGELOG.md
```

Expected:
- `Unreleased` explains that the structured release reconstruction supersedes the old `0.34.0` planning target

- [ ] **Step 5: Commit checkpoint**

Cherry-pick created the commit. Verify it is present:

```bash
git -C /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery log --oneline --decorate -5
```

Expected:
- top commit is `c14cde4`

### Task 4: Prove The Branch Is Safe To Review Against `origin/master`

**Files:**
- No tracked file changes in this task.
- Verify only: branch refs, test results, and merge simulation

- [ ] **Step 1: Verify the final diff against `origin/master`**

Run:

```bash
git -C /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery diff --stat origin/master..HEAD
git -C /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery diff --name-status origin/master..HEAD
```

Expected:
- only the mandatory truth-recovery files plus `CHANGELOG.md` (if Task 3 was completed)
- no review-pack docs/tests deleted
- no branch-local design spec included

- [ ] **Step 2: Simulate the merge against `origin/master`**

Run:

```bash
git -C /Users/vladimir/Projects/cryodaq merge-tree \
  $(git -C /Users/vladimir/Projects/cryodaq merge-base origin/master codex/safe-merge-b1-truth-recovery) \
  origin/master \
  codex/safe-merge-b1-truth-recovery | rg -n "<<<<<<<|>>>>>>>|changed in both|CONFLICT" || true
```

Expected:
- no output

- [ ] **Step 3: Verify the polluted local `master` has not been modified or “cleaned up”**

Run:

```bash
git -C /Users/vladimir/Projects/cryodaq status --short --branch
git -C /Users/vladimir/Projects/cryodaq log --oneline --decorate -5
```

Expected:
- local `master` still shows its pre-existing dirty state and review-pack chain
- this plan did not rewrite or mutate local `master`

- [ ] **Step 4: Push the clean integration branch for review**

Run:

```bash
git -C /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery push -u origin codex/safe-merge-b1-truth-recovery
```

Expected:
- remote branch is created successfully

- [ ] **Step 5: Commit checkpoint**

There is no new manual commit in this task. The checkpoint is a pushed clean integration branch that can be reviewed against `origin/master` without involving local polluted `master`.

## Self-Review

- Spec coverage:
  - Safe base from `origin/master`: Task 1
  - Mandatory truth-recovery cherry-picks: Task 2
  - Optional changelog reconstruction: Task 3
  - Review-safe proof and publication: Task 4
- Placeholder scan:
  - No `TBD`, `TODO`, or abstract “handle appropriately” language remains.
- Type consistency:
  - Branch names, worktree paths, and commit hashes are used consistently throughout.
