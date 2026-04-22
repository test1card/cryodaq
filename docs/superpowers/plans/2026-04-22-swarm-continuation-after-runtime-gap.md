# Swarm Continuation After Runtime Gap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resume the roadmap review on `codex/safe-merge-b1-truth-recovery` from the exact point where it stopped: gather the missing dev-Mac B1 runtime evidence, then rerun contradiction and arbitration so the repo-mode decision is backed by both code truth and fresh runtime data.

**Architecture:** Do not restart the whole review program. The existing primary review artifacts on this branch are valid inputs, and the current resolution ledger explicitly says the missing piece is the dev-Mac B1 run. This tranche therefore has one narrow purpose: create the missing diagnostics artifacts, feed them back through Kimi and Metaswarm, and update the decision ledger from provisional to runtime-backed.

**Tech Stack:** `git`, `pytest`, `cryodaq-engine`, `tools/diag_zmq_b1_capture.py`, Markdown docs, Kimi contradiction pass, `/metaswarm`.

---

## File structure and responsibilities

- `artifacts/diagnostics/b1-devmac-current-master.jsonl`
  Canonical 180s dev-Mac B1 capture artifact.
- `artifacts/diagnostics/b1-devmac-run-note.md`
  Exact branch/ref/dirty-state/command log plus result classification.
- `artifacts/reviews/roadmap-kimi-contradiction.md`
  Existing contradiction review, updated to include the runtime evidence.
- `artifacts/reviews/roadmap-metaswarm-arbitration.md`
  Existing arbitration, updated from provisional to runtime-backed.
- `docs/decisions/ROADMAP_RESOLUTION_LEDGER.md`
  Current decision ledger; step 3 is still pending and must be completed.
- `docs/runbooks/ROADMAP_REVIEW_SWARM_CONTINUATION_PROMPT.md`
  Strict resume prompt telling the swarm to continue from pending runtime evidence rather than rerunning the whole review.

Execution baseline:
- Branch: `codex/safe-merge-b1-truth-recovery`
- Worktree: `/Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery`
- Base: `origin/master`

Grounded starting point from current branch state:
- `docs/decisions/ROADMAP_RESOLUTION_LEDGER.md` marks Codex/Gemini/Kimi/Metaswarm complete but the `Dev-Mac Run` still `pending`.
- `artifacts/reviews/roadmap-codex-primary.md`, `artifacts/reviews/roadmap-gemini-primary.md`, `artifacts/reviews/roadmap-kimi-contradiction.md`, and `artifacts/reviews/roadmap-metaswarm-arbitration.md` already exist.
- `artifacts/diagnostics/` does not exist yet on this branch.
- `docs/runbooks/B1_CURRENT_MASTER_RUNBOOK.md` is the authoritative runtime procedure.

### Task 1: Freeze the continuation baseline and create the continuation prompt

**Files:**
- Create: `docs/runbooks/ROADMAP_REVIEW_SWARM_CONTINUATION_PROMPT.md`
- Modify: `docs/decisions/ROADMAP_RESOLUTION_LEDGER.md`

- [ ] **Step 1: Verify the continuation starting point**

Run:

```bash
git branch --show-current
git rev-parse HEAD
find artifacts/reviews -maxdepth 1 -type f | sort
test -d artifacts/diagnostics && find artifacts/diagnostics -maxdepth 1 -type f | sort || echo "NO_DIAGNOSTICS_DIR"
sed -n '1,120p' docs/decisions/ROADMAP_RESOLUTION_LEDGER.md
```

Expected:
- branch is `codex/safe-merge-b1-truth-recovery`
- review artifacts exist
- diagnostics directory is absent or empty
- ledger step 3 (`Dev-Mac Run`) is still pending

- [ ] **Step 2: Write the swarm continuation prompt**

Create `docs/runbooks/ROADMAP_REVIEW_SWARM_CONTINUATION_PROMPT.md`:

```md
# Roadmap Review Swarm Continuation Prompt

Resume the bounded roadmap review on `codex/safe-merge-b1-truth-recovery`.

Do not restart the whole review. Primary review artifacts already exist on this branch:
- `artifacts/reviews/roadmap-codex-primary.md`
- `artifacts/reviews/roadmap-gemini-primary.md`
- `artifacts/reviews/roadmap-kimi-contradiction.md`
- `artifacts/reviews/roadmap-metaswarm-arbitration.md`

The missing work is the runtime-evidence gap:
- execute `docs/runbooks/B1_CURRENT_MASTER_RUNBOOK.md`
- produce `artifacts/diagnostics/b1-devmac-current-master.jsonl`
- produce `artifacts/diagnostics/b1-devmac-run-note.md`
- then rerun Kimi contradiction and Metaswarm arbitration using the new evidence

Before doing anything, switch local checkout to:
- branch: `codex/safe-merge-b1-truth-recovery`
- base for comparison: `origin/master`

Verify with:
```bash
git branch --show-current
git rev-parse HEAD
git rev-parse origin/master
git diff --name-only origin/master..HEAD
```

Strict continuation order:
1. verify existing review artifacts are present
2. run the dev-Mac B1 capture from `B1_CURRENT_MASTER_RUNBOOK.md`
3. update `docs/decisions/ROADMAP_RESOLUTION_LEDGER.md` step 3 from `pending` to `complete`
4. rerun Kimi contradiction with runtime evidence
5. rerun `/metaswarm` arbitration with runtime evidence
6. update the ledger’s final decision only if the runtime evidence changes it

No-go rules:
- no feature work
- no IV.7 implementation yet
- no safety-semantic config changes
- no deletion of existing review artifacts
- no claim that B1 is fixed unless the runtime evidence really supports that
```

- [ ] **Step 3: Mark the ledger as continuation mode**

Append to `docs/decisions/ROADMAP_RESOLUTION_LEDGER.md`:

```md
## Continuation Status

This ledger is provisional until the dev-Mac B1 run is completed.
Existing Codex/Gemini/Kimi/Metaswarm outputs are code-truth and document-truth reviews only.
The missing artifact set is:
- `artifacts/diagnostics/b1-devmac-current-master.jsonl`
- `artifacts/diagnostics/b1-devmac-run-note.md`
```

- [ ] **Step 4: Commit**

```bash
git add docs/runbooks/ROADMAP_REVIEW_SWARM_CONTINUATION_PROMPT.md docs/decisions/ROADMAP_RESOLUTION_LEDGER.md
git commit -m "docs: add strict continuation prompt for roadmap runtime gap"
```

### Task 2: Execute the missing dev-Mac B1 run exactly once

**Files:**
- Create: `artifacts/diagnostics/b1-devmac-current-master.jsonl`
- Create: `artifacts/diagnostics/b1-devmac-run-note.md`

- [ ] **Step 1: Create the diagnostics directory and run note**

Run:

```bash
mkdir -p artifacts/diagnostics
```

Create `artifacts/diagnostics/b1-devmac-run-note.md`:

```md
# Dev-Mac B1 Run Note

Branch under test: `codex/safe-merge-b1-truth-recovery`
Base branch: `origin/master`
Reason for run: resolve the missing runtime-evidence gap in the roadmap review

Baseline capture:
- `git branch --show-current`
- `git rev-parse HEAD`
- `git status --short`

Runtime commands:
- `CRYODAQ_MOCK=1 .venv/bin/cryodaq-engine --mock`
- `.venv/bin/python tools/diag_zmq_b1_capture.py --duration 180 --interval 1.0 --output artifacts/diagnostics/b1-devmac-current-master.jsonl`
```

- [ ] **Step 2: Record the baseline state**

Run and append output into the run note:

```bash
git branch --show-current
git rev-parse HEAD
git status --short
```

Expected:
- branch is `codex/safe-merge-b1-truth-recovery`
- `HEAD` is recorded
- any local dirt is explicitly visible in the note

- [ ] **Step 3: Start the mock engine**

Run:

```bash
CRYODAQ_MOCK=1 /Users/vladimir/Projects/cryodaq/.venv/bin/cryodaq-engine --mock
```

Expected:
- engine process starts
- process remains running for the capture window

- [ ] **Step 4: Run the canonical capture**

Run in another shell:

```bash
/Users/vladimir/Projects/cryodaq/.venv/bin/python tools/diag_zmq_b1_capture.py \
  --duration 180 \
  --interval 1.0 \
  --output artifacts/diagnostics/b1-devmac-current-master.jsonl
```

Expected:
- JSONL file created
- command exits zero

- [ ] **Step 5: Record the result classification**

Append one exact block to `artifacts/diagnostics/b1-devmac-run-note.md`:

```md
Result classification:
- `bridge_reply` failed while `direct_reply` stayed healthy
```

or

```md
Result classification:
- `bridge_reply` and `direct_reply` failed together
```

or

```md
Result classification:
- neither path failed during the dev-Mac capture window
```

- [ ] **Step 6: Commit**

```bash
git add artifacts/diagnostics/b1-devmac-current-master.jsonl artifacts/diagnostics/b1-devmac-run-note.md
git commit -m "diag: add dev-mac B1 runtime evidence"
```

### Task 3: Rerun contradiction review with evidence

**Files:**
- Modify: `artifacts/reviews/roadmap-kimi-contradiction.md`
- Modify: `docs/decisions/ROADMAP_RESOLUTION_LEDGER.md`

- [ ] **Step 1: Re-run Kimi on the updated evidence set**

Use these exact inputs:

```text
artifacts/reviews/roadmap-codex-primary.md
artifacts/reviews/roadmap-gemini-primary.md
artifacts/diagnostics/b1-devmac-current-master.jsonl
artifacts/diagnostics/b1-devmac-run-note.md
```

Required output target:

```text
artifacts/reviews/roadmap-kimi-contradiction.md
```

Expected:
- Kimi explicitly states whether the runtime evidence changes any earlier conclusion
- Kimi explicitly preserves uncertainty if the run is inconclusive

- [ ] **Step 2: Update the ledger step status**

Edit `docs/decisions/ROADMAP_RESOLUTION_LEDGER.md` so this row changes:

```md
| 3 | Dev-Mac Run | `B1_CURRENT_MASTER_RUNBOOK.md` | `b1-devmac-*.jsonl`, `b1-devmac-run-note.md` | **complete** |
```

And this row stays complete:

```md
| 4 | Kimi | `ROADMAP_REVIEW_PROMPT_KIMI.md` | `roadmap-kimi-contradiction.md` | **complete** |
```

- [ ] **Step 3: Add one runtime-evidence note to the ledger**

Append:

```md
## Runtime Evidence Delta

- Dev-Mac run completed
- Evidence files:
  - `artifacts/diagnostics/b1-devmac-current-master.jsonl`
  - `artifacts/diagnostics/b1-devmac-run-note.md`
- Kimi contradiction rerun completed against the runtime evidence
```

- [ ] **Step 4: Commit**

```bash
git add artifacts/reviews/roadmap-kimi-contradiction.md docs/decisions/ROADMAP_RESOLUTION_LEDGER.md
git commit -m "review: rerun kimi contradiction with runtime evidence"
```

### Task 4: Rerun final arbitration with runtime evidence

**Files:**
- Modify: `artifacts/reviews/roadmap-metaswarm-arbitration.md`
- Modify: `docs/decisions/ROADMAP_RESOLUTION_LEDGER.md`

- [ ] **Step 1: Rerun Metaswarm with the evidence-complete input set**

Use these exact inputs:

```text
artifacts/reviews/roadmap-codex-primary.md
artifacts/reviews/roadmap-gemini-primary.md
artifacts/reviews/roadmap-kimi-contradiction.md
artifacts/diagnostics/b1-devmac-current-master.jsonl
artifacts/diagnostics/b1-devmac-run-note.md
```

Required output target:

```text
artifacts/reviews/roadmap-metaswarm-arbitration.md
```

Expected:
- explicit runtime-backed decision for `Repo Mode`
- explicit runtime-backed decision for `B1 Status`
- explicit runtime-backed decision for `IV.7 Status`

- [ ] **Step 2: Update the ledger final status**

Edit `docs/decisions/ROADMAP_RESOLUTION_LEDGER.md` so:

```md
| 5 | Metaswarm | `ROADMAP_REVIEW_PROMPT_METASWARM.md` | `roadmap-metaswarm-arbitration.md` | **complete** |
```

And replace the current `Final Arbitration` section with the runtime-backed result from Metaswarm.

- [ ] **Step 3: Verify the evidence-complete state**

Run:

```bash
find artifacts/diagnostics -maxdepth 1 -type f | sort
sed -n '1,220p' artifacts/reviews/roadmap-metaswarm-arbitration.md
sed -n '1,220p' docs/decisions/ROADMAP_RESOLUTION_LEDGER.md
```

Expected:
- both diagnostics files exist
- arbitration explicitly references the runtime evidence
- ledger no longer calls the result provisional

- [ ] **Step 4: Commit**

```bash
git add artifacts/reviews/roadmap-metaswarm-arbitration.md docs/decisions/ROADMAP_RESOLUTION_LEDGER.md
git commit -m "review: finalize roadmap arbitration with runtime evidence"
```

### Task 5: Decide whether an IV.7 branch should be prepared

**Files:**
- Modify: `docs/decisions/ROADMAP_RESOLUTION_LEDGER.md`

- [ ] **Step 1: Apply the exact decision rule**

Use this rule verbatim:

```text
If the runtime-backed arbitration still says B1 is open and IV.7 is justified next, prepare an IV.7 bounded experiment branch.
If the runtime-backed arbitration says IV.7 is premature, stop and do not create an IV.7 branch.
If the runtime-backed arbitration says B1 is closed, update repo mode and do not create an IV.7 branch.
```

- [ ] **Step 2: Record the next-step decision**

Append:

```md
## Next-Step Decision

- Repo mode:
- B1 status:
- IV.7 status:
- Next branch action: `prepare IV.7 branch` or `stop`
```

- [ ] **Step 3: Commit**

```bash
git add docs/decisions/ROADMAP_RESOLUTION_LEDGER.md
git commit -m "docs: record post-evidence next-step decision"
```

## Swarm continuation rule

The swarm must continue only from the missing runtime-evidence gap. It must not:
- redo Codex and Gemini primary reviews unless branch content changed materially
- reopen feature work
- implement IV.7 inside this continuation tranche
- mutate safety semantics

This continuation is finished only when:
- the diagnostics artifacts exist
- the contradiction review has been rerun against them
- the arbitration has been rerun against them
- the ledger is no longer provisional
