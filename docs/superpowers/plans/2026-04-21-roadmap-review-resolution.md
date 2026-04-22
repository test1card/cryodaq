# Roadmap Review And Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish one authoritative review program that classifies every active roadmap item, resolves repo-truth drift, and produces the evidence needed to decide whether CryoDAQ can leave hardening mode and resume feature work.

**Architecture:** Run this as a bounded review-and-arbitration tranche, not as open-ended “please review the repo.” The work has two tracks: `A)` code-truth and runtime evidence for B1 on a clean branch, and `B)` roadmap-resolution documentation that classifies every feature or blocker into shipped, blocked, research, deferred, or human-checkpoint-required. The review target should be `codex/safe-merge-b1-truth-recovery`, not the preserved dirty branch and not the current dirty checkout.

**Tech Stack:** `git`, `pytest`, Markdown docs, existing B1 runbook/tooling, `/codex`, `/gemini`, Kimi contradiction pass, `/metaswarm`.

---

## File structure and responsibilities

- `docs/runbooks/ROADMAP_REVIEW_CONTROL.md`
  Single source of truth for review scope, exact branch/ref under review, and output artifact paths.
- `docs/runbooks/ROADMAP_REVIEW_PROMPT_CODEX.md`
  Code-truth and regression-surface review prompt.
- `docs/runbooks/ROADMAP_REVIEW_PROMPT_GEMINI.md`
  Adversarial and overclaim-detection review prompt.
- `docs/runbooks/ROADMAP_REVIEW_PROMPT_KIMI.md`
  Contradiction-review prompt that challenges shared blind spots.
- `docs/runbooks/ROADMAP_REVIEW_PROMPT_METASWARM.md`
  Final arbitration prompt that merges findings into one decision record.
- `docs/runbooks/ROADMAP_REVIEW_LEDGER.md`
  Run-order ledger, artifact registry, and sign-off status.
- `docs/decisions/ROADMAP_RESOLUTION_LEDGER.md`
  Final classification of every roadmap item into `done`, `blocked`, `research`, `defer`, or `human checkpoint`.
- `tests/tools/test_roadmap_review_pack.py`
  Acceptance test that proves the review pack files exist and point at the correct branch, files, and outputs.
- `artifacts/reviews/roadmap-codex-primary.md`
  Codex primary review output.
- `artifacts/reviews/roadmap-gemini-primary.md`
  Gemini primary review output.
- `artifacts/reviews/roadmap-kimi-contradiction.md`
  Kimi contradiction output.
- `artifacts/reviews/roadmap-metaswarm-arbitration.md`
  Final arbitration output.
- `artifacts/diagnostics/b1-devmac-current-master.jsonl`
  Canonical dev-Mac B1 evidence packet from the current-master runbook.
- `artifacts/diagnostics/b1-devmac-run-note.md`
  Run note that records exact branch, exact `HEAD`, dirty state, commands run, and summary outcome.

Execution baseline:
- Use `/Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery`
- Do **not** use `/Users/vladimir/Projects/cryodaq` while it is on `codex/preserved-local-master-2026-04-21`
- Do **not** treat local preserved dirt as planning truth

Roadmap truth this plan is built around:
- `IV.4` is closed in [ROADMAP.md](/Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/ROADMAP.md:53)
- `IV.5` is blocked by `B1` in [ROADMAP.md](/Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/ROADMAP.md:88) and [ROADMAP.md](/Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/ROADMAP.md:426)
- `B1` remains unresolved in [CODEX_ARCHITECTURE_CONTROL_PLANE.md](/Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/CODEX_ARCHITECTURE_CONTROL_PLANE.md:98)
- The next evidence step is the current-master runbook in [B1_CURRENT_MASTER_RUNBOOK.md](/Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/docs/runbooks/B1_CURRENT_MASTER_RUNBOOK.md:1)

### Task 1: Freeze the review baseline and create the control pack

**Files:**
- Create: `docs/runbooks/ROADMAP_REVIEW_CONTROL.md`
- Create: `docs/runbooks/ROADMAP_REVIEW_LEDGER.md`
- Test: `tests/tools/test_roadmap_review_pack.py`

- [ ] **Step 1: Write the failing acceptance test**

Create `tests/tools/test_roadmap_review_pack.py` with:

```python
from pathlib import Path


RUNBOOKS = Path("docs/runbooks")

REQUIRED_SNIPPETS = {
    "ROADMAP_REVIEW_CONTROL.md": [
        "codex/safe-merge-b1-truth-recovery",
        "origin/master",
        "ROADMAP.md",
        "CODEX_ARCHITECTURE_CONTROL_PLANE.md",
        "docs/runbooks/B1_CURRENT_MASTER_RUNBOOK.md",
        "artifacts/reviews/roadmap-codex-primary.md",
        "artifacts/reviews/roadmap-gemini-primary.md",
        "artifacts/reviews/roadmap-kimi-contradiction.md",
        "artifacts/reviews/roadmap-metaswarm-arbitration.md",
        "artifacts/diagnostics/b1-devmac-current-master.jsonl",
    ],
    "ROADMAP_REVIEW_LEDGER.md": [
        "Codex primary",
        "Gemini primary",
        "Kimi contradiction",
        "Metaswarm arbitration",
        "ROADMAP_RESOLUTION_LEDGER.md",
    ],
}


def test_roadmap_review_pack_exists_and_points_at_authoritative_branch():
    for filename, snippets in REQUIRED_SNIPPETS.items():
        path = RUNBOOKS / filename
        assert path.exists(), f"missing review control file: {path}"
        text = path.read_text(encoding="utf-8")
        for snippet in snippets:
            assert snippet in text, f"{filename} missing snippet: {snippet}"
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
/Users/vladimir/Projects/cryodaq/.venv/bin/pytest tests/tools/test_roadmap_review_pack.py -q
```

Expected:
- `FAIL`
- missing `docs/runbooks/ROADMAP_REVIEW_CONTROL.md`

- [ ] **Step 3: Write the control doc**

Create `docs/runbooks/ROADMAP_REVIEW_CONTROL.md` with this structure:

```md
# Roadmap Review Control

Branch under review: `codex/safe-merge-b1-truth-recovery`
Base branch: `origin/master`
Execution worktree: `/Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery`

Primary code/docs under review:
- `ROADMAP.md`
- `CHANGELOG.md`
- `CODEX_ARCHITECTURE_CONTROL_PLANE.md`
- `docs/runbooks/B1_CURRENT_MASTER_RUNBOOK.md`
- `tools/_b1_diagnostics.py`
- `tools/diag_zmq_b1_capture.py`
- `tests/tools/test_b1_diagnostics.py`
- `tests/tools/test_diag_zmq_b1_capture.py`

Authoritative questions:
1. Is B1 still the only blocker for leaving hardening mode?
2. Which roadmap items are actually done vs merely documented?
3. Which items require human checkpoint or research rather than implementation?
4. Is IV.7 justified by code truth plus dev-Mac evidence, or still premature?

Required outputs:
- `artifacts/reviews/roadmap-codex-primary.md`
- `artifacts/reviews/roadmap-gemini-primary.md`
- `artifacts/reviews/roadmap-kimi-contradiction.md`
- `artifacts/reviews/roadmap-metaswarm-arbitration.md`
- `artifacts/diagnostics/b1-devmac-current-master.jsonl`
- `artifacts/diagnostics/b1-devmac-run-note.md`
- `docs/decisions/ROADMAP_RESOLUTION_LEDGER.md`
```

- [ ] **Step 4: Write the review ledger**

Create `docs/runbooks/ROADMAP_REVIEW_LEDGER.md` with:

```md
# Roadmap Review Ledger

Review target: `codex/safe-merge-b1-truth-recovery`
Base: `origin/master`

Execution order:
1. Codex primary
2. Gemini primary
3. Dev-Mac B1 evidence run
4. Kimi contradiction
5. Metaswarm arbitration
6. Resolution ledger update

Artifacts:
- `artifacts/reviews/roadmap-codex-primary.md`
- `artifacts/reviews/roadmap-gemini-primary.md`
- `artifacts/reviews/roadmap-kimi-contradiction.md`
- `artifacts/reviews/roadmap-metaswarm-arbitration.md`
- `artifacts/diagnostics/b1-devmac-current-master.jsonl`
- `artifacts/diagnostics/b1-devmac-run-note.md`
- `docs/decisions/ROADMAP_RESOLUTION_LEDGER.md`
```

- [ ] **Step 5: Run the test to verify it passes**

Run:

```bash
/Users/vladimir/Projects/cryodaq/.venv/bin/pytest tests/tools/test_roadmap_review_pack.py -q
```

Expected:
- `PASS`

- [ ] **Step 6: Commit**

```bash
git add tests/tools/test_roadmap_review_pack.py docs/runbooks/ROADMAP_REVIEW_CONTROL.md docs/runbooks/ROADMAP_REVIEW_LEDGER.md
git commit -m "docs: add roadmap review control pack baseline"
```

### Task 2: Create bounded prompts for the swarm

**Files:**
- Create: `docs/runbooks/ROADMAP_REVIEW_PROMPT_CODEX.md`
- Create: `docs/runbooks/ROADMAP_REVIEW_PROMPT_GEMINI.md`
- Create: `docs/runbooks/ROADMAP_REVIEW_PROMPT_KIMI.md`
- Create: `docs/runbooks/ROADMAP_REVIEW_PROMPT_METASWARM.md`
- Modify: `tests/tools/test_roadmap_review_pack.py`

- [ ] **Step 1: Extend the test with prompt contracts**

Add to `REQUIRED_SNIPPETS`:

```python
    "ROADMAP_REVIEW_PROMPT_CODEX.md": [
        "/codex",
        "code truth",
        "regression surface",
        "Do not suggest broad redesigns",
    ],
    "ROADMAP_REVIEW_PROMPT_GEMINI.md": [
        "/gemini",
        "overclaim",
        "falsification",
        "Do not approve IV.7 without evidence",
    ],
    "ROADMAP_REVIEW_PROMPT_KIMI.md": [
        "Kimi",
        "contradiction",
        "shared blind spots",
        "roadmap-gemini-primary.md",
    ],
    "ROADMAP_REVIEW_PROMPT_METASWARM.md": [
        "/metaswarm",
        "arbitration",
        "ROADMAP_RESOLUTION_LEDGER.md",
        "current-master evidence",
    ],
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
/Users/vladimir/Projects/cryodaq/.venv/bin/pytest tests/tools/test_roadmap_review_pack.py -q
```

Expected:
- `FAIL`
- missing prompt files

- [ ] **Step 3: Write the Codex prompt**

Create `docs/runbooks/ROADMAP_REVIEW_PROMPT_CODEX.md`:

```md
# Roadmap Review Prompt: Codex Primary

Invocation: `/codex`

Review branch `codex/safe-merge-b1-truth-recovery` against `origin/master`.

Priority:
1. code truth
2. regression surface
3. roadmap status accuracy
4. whether B1 still blocks leaving hardening mode

Files to anchor on:
- `ROADMAP.md`
- `CHANGELOG.md`
- `CODEX_ARCHITECTURE_CONTROL_PLANE.md`
- `docs/runbooks/B1_CURRENT_MASTER_RUNBOOK.md`
- `tools/_b1_diagnostics.py`
- `tools/diag_zmq_b1_capture.py`

Required output:
- `artifacts/reviews/roadmap-codex-primary.md`

Do not suggest broad redesigns.
Do not claim B1 is fixed.
Do not treat the preserved dirty branch as authoritative.
```

- [ ] **Step 4: Write the Gemini prompt**

Create `docs/runbooks/ROADMAP_REVIEW_PROMPT_GEMINI.md`:

```md
# Roadmap Review Prompt: Gemini Primary

Invocation: `/gemini`

Review branch `codex/safe-merge-b1-truth-recovery` against `origin/master`.

Priority:
1. overclaim detection
2. falsification quality
3. whether roadmap language outruns evidence
4. whether IV.7 is being treated as approved without proof

Required output:
- `artifacts/reviews/roadmap-gemini-primary.md`

Do not approve IV.7 without evidence.
Do not downgrade B1 merely because mitigations exist.
Do not suggest broad redesigns.
```

- [ ] **Step 5: Write the Kimi contradiction prompt**

Create `docs/runbooks/ROADMAP_REVIEW_PROMPT_KIMI.md`:

```md
# Roadmap Review Prompt: Kimi Contradiction Pass

Invocation: `Kimi`

Inputs:
- `artifacts/reviews/roadmap-codex-primary.md`
- `artifacts/reviews/roadmap-gemini-primary.md`
- `artifacts/diagnostics/b1-devmac-current-master.jsonl`
- `artifacts/diagnostics/b1-devmac-run-note.md`

Task:
- find contradiction
- find shared blind spots
- reject conclusions not warranted by evidence

Required output:
- `artifacts/reviews/roadmap-kimi-contradiction.md`
```

- [ ] **Step 6: Write the Metaswarm arbitration prompt**

Create `docs/runbooks/ROADMAP_REVIEW_PROMPT_METASWARM.md`:

```md
# Roadmap Review Prompt: Metaswarm Arbitration

Invocation: `/metaswarm`

Inputs:
- `artifacts/reviews/roadmap-codex-primary.md`
- `artifacts/reviews/roadmap-gemini-primary.md`
- `artifacts/reviews/roadmap-kimi-contradiction.md`
- `artifacts/diagnostics/b1-devmac-current-master.jsonl`
- `artifacts/diagnostics/b1-devmac-run-note.md`

Task:
- produce one arbitration decision
- state whether CryoDAQ stays in hardening mode
- state whether IV.7 is justified next
- state which roadmap items are active, blocked, deferred, or human-checkpoint-only

Required output:
- `artifacts/reviews/roadmap-metaswarm-arbitration.md`
- `docs/decisions/ROADMAP_RESOLUTION_LEDGER.md`
```

- [ ] **Step 7: Run the test to verify it passes**

Run:

```bash
/Users/vladimir/Projects/cryodaq/.venv/bin/pytest tests/tools/test_roadmap_review_pack.py -q
```

Expected:
- `PASS`

- [ ] **Step 8: Commit**

```bash
git add tests/tools/test_roadmap_review_pack.py docs/runbooks/ROADMAP_REVIEW_PROMPT_CODEX.md docs/runbooks/ROADMAP_REVIEW_PROMPT_GEMINI.md docs/runbooks/ROADMAP_REVIEW_PROMPT_KIMI.md docs/runbooks/ROADMAP_REVIEW_PROMPT_METASWARM.md
git commit -m "docs: add bounded roadmap review prompts"
```

### Task 3: Execute the review swarm in the correct order

**Files:**
- Create: `artifacts/reviews/roadmap-codex-primary.md`
- Create: `artifacts/reviews/roadmap-gemini-primary.md`
- Create: `artifacts/reviews/roadmap-kimi-contradiction.md`
- Create: `artifacts/reviews/roadmap-metaswarm-arbitration.md`
- Modify: `docs/runbooks/ROADMAP_REVIEW_LEDGER.md`

- [ ] **Step 1: Record the exact review target**

Run:

```bash
git rev-parse HEAD
git diff --name-only origin/master..HEAD
git status --short
```

Expected:
- `HEAD` is on `codex/safe-merge-b1-truth-recovery`
- diff vs `origin/master` is the intended review surface
- local dirt, if any, is intentional and recorded

- [ ] **Step 2: Run Codex primary review**

Use `docs/runbooks/ROADMAP_REVIEW_PROMPT_CODEX.md` and save output to:

```text
artifacts/reviews/roadmap-codex-primary.md
```

Expected minimum sections in output:
- Current code truth
- Regression risks
- B1 status
- Roadmap misstatements

- [ ] **Step 3: Run Gemini primary review**

Use `docs/runbooks/ROADMAP_REVIEW_PROMPT_GEMINI.md` and save output to:

```text
artifacts/reviews/roadmap-gemini-primary.md
```

Expected minimum sections in output:
- Overclaims
- Unsupported assumptions
- Which roadmap items are not ready for implementation

- [ ] **Step 4: Update the ledger with primary-review status**

Append to `docs/runbooks/ROADMAP_REVIEW_LEDGER.md`:

```md
## Primary review status

- Codex primary: complete
- Gemini primary: complete
- Dev-Mac B1 evidence: pending
- Kimi contradiction: pending
- Metaswarm arbitration: pending
```

- [ ] **Step 5: Commit**

```bash
git add artifacts/reviews/roadmap-codex-primary.md artifacts/reviews/roadmap-gemini-primary.md docs/runbooks/ROADMAP_REVIEW_LEDGER.md
git commit -m "docs: record primary roadmap reviews"
```

### Task 4: Run the dev-Mac B1 evidence pass before contradiction and arbitration

**Files:**
- Create: `artifacts/diagnostics/b1-devmac-current-master.jsonl`
- Create: `artifacts/diagnostics/b1-devmac-run-note.md`

- [ ] **Step 1: Record the branch and dirty state in the run note**

Create `artifacts/diagnostics/b1-devmac-run-note.md` with:

```md
# Dev-Mac B1 Run Note

Branch under test: `codex/safe-merge-b1-truth-recovery`
Base branch: `origin/master`
Reason for run: decide whether B1 still blocks feature work and whether IV.7 is justified

Commands:
- `git rev-parse HEAD`
- `git status --short`
- `CRYODAQ_MOCK=1 .venv/bin/cryodaq-engine --mock`
- `.venv/bin/python tools/diag_zmq_b1_capture.py --duration 180 --interval 1.0 --output artifacts/diagnostics/b1-devmac-current-master.jsonl`
```

- [ ] **Step 2: Start the engine in mock mode**

Run:

```bash
CRYODAQ_MOCK=1 /Users/vladimir/Projects/cryodaq/.venv/bin/cryodaq-engine --mock
```

Expected:
- engine stays running
- no immediate startup failure

- [ ] **Step 3: Run the canonical capture**

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

- [ ] **Step 4: Summarize the result class in the run note**

Append one of these exact result summaries to `artifacts/diagnostics/b1-devmac-run-note.md`:

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

- [ ] **Step 5: Commit**

```bash
git add artifacts/diagnostics/b1-devmac-current-master.jsonl artifacts/diagnostics/b1-devmac-run-note.md
git commit -m "diag: capture dev-mac B1 evidence for roadmap arbitration"
```

### Task 5: Run contradiction review and final arbitration

**Files:**
- Create: `artifacts/reviews/roadmap-kimi-contradiction.md`
- Create: `artifacts/reviews/roadmap-metaswarm-arbitration.md`
- Modify: `docs/runbooks/ROADMAP_REVIEW_LEDGER.md`

- [ ] **Step 1: Run Kimi contradiction review**

Use `docs/runbooks/ROADMAP_REVIEW_PROMPT_KIMI.md` and save output to:

```text
artifacts/reviews/roadmap-kimi-contradiction.md
```

Expected minimum sections:
- Shared blind spots
- Overconfident conclusions to reject
- Which claims survive contradiction review

- [ ] **Step 2: Run Metaswarm arbitration**

Use `docs/runbooks/ROADMAP_REVIEW_PROMPT_METASWARM.md` and save output to:

```text
artifacts/reviews/roadmap-metaswarm-arbitration.md
```

Expected minimum sections:
- Stay in hardening mode vs resume features
- B1 status
- IV.7 go/no-go
- Roadmap item classification summary

- [ ] **Step 3: Mark the ledger complete**

Append to `docs/runbooks/ROADMAP_REVIEW_LEDGER.md`:

```md
## Final review status

- Codex primary: complete
- Gemini primary: complete
- Dev-Mac B1 evidence: complete
- Kimi contradiction: complete
- Metaswarm arbitration: complete
```

- [ ] **Step 4: Commit**

```bash
git add artifacts/reviews/roadmap-kimi-contradiction.md artifacts/reviews/roadmap-metaswarm-arbitration.md docs/runbooks/ROADMAP_REVIEW_LEDGER.md
git commit -m "docs: record contradiction review and final roadmap arbitration"
```

### Task 6: Resolve the roadmap into an actionable ledger

**Files:**
- Create: `docs/decisions/ROADMAP_RESOLUTION_LEDGER.md`
- Modify: `ROADMAP.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Write the resolution ledger**

Create `docs/decisions/ROADMAP_RESOLUTION_LEDGER.md` with this table:

```md
# Roadmap Resolution Ledger

| Item | Current status | Evidence source | Next action |
|---|---|---|---|
| B1 | blocked | `roadmap-metaswarm-arbitration.md` + `b1-devmac-run-note.md` | stay hardening / run IV.7 branch / close |
| IV.5 | blocked by B1 | `ROADMAP.md` + arbitration | do not implement yet |
| F3 | blocked | roadmap + arbitration | queue after B1 |
| F5 | blocked + deployment dependency | roadmap + arbitration | queue after B1 + Vladimir checkpoint |
| F17 | blocked | roadmap + arbitration | queue after B1 |
| F8 | research | roadmap | no code until dataset + eval |
| F9 | human checkpoint | roadmap | physics review with Vladimir |
| F4/F7/F10/F12/F13/F14/F15/F16/F18 | deferred | roadmap | no action now |
| F1/F2/F6/F11 | done | roadmap + changelog | keep as shipped |
```

- [ ] **Step 2: Update `ROADMAP.md` to reflect arbitration**

Apply these rules:
- If arbitration says `stay in hardening mode`, keep IV.5 blocked language explicit.
- If arbitration says `IV.7 justified`, state it as the next experiment branch, not a migration.
- If arbitration says `IV.7 not justified`, remove “working hypothesis” wording that overcommits.
- For every active item, make sure `ROADMAP.md` matches `docs/decisions/ROADMAP_RESOLUTION_LEDGER.md`.

- [ ] **Step 3: Update `CHANGELOG.md` only if review changed release truth**

Allowed change:
- adjust the `Unreleased` prose if arbitration changes the next-step description

Not allowed:
- backfill new release lines without evidence

- [ ] **Step 4: Verify the ledger resolves all roadmap items**

Run:

```bash
rg -n '^### F|^### B1|^### IV\\.' ROADMAP.md
sed -n '1,200p' docs/decisions/ROADMAP_RESOLUTION_LEDGER.md
```

Expected:
- every active roadmap item is represented in the ledger
- no item is left without `Current status` and `Next action`

- [ ] **Step 5: Commit**

```bash
git add docs/decisions/ROADMAP_RESOLUTION_LEDGER.md ROADMAP.md CHANGELOG.md
git commit -m "docs: resolve roadmap status after review arbitration"
```

### Task 7: Decide whether the repo stays in hardening mode

**Files:**
- Modify: `docs/decisions/ROADMAP_RESOLUTION_LEDGER.md`
- Modify: `CODEX_ARCHITECTURE_CONTROL_PLANE.md`

- [ ] **Step 1: Apply the decision rule**

Use this exact rule:

```text
If B1 is still open or evidence is insufficient, CryoDAQ remains in hardening mode.
If B1 is closed by fresh runtime evidence and contradiction review does not reject that closure, CryoDAQ may leave hardening mode and draft the next feature batch.
```

- [ ] **Step 2: Write the repo-mode outcome**

Append to `docs/decisions/ROADMAP_RESOLUTION_LEDGER.md`:

```md
## Repo mode decision

Outcome: `hardening` or `feature-ready`

Reason:
- B1 status:
- IV.7 status:
- Safety/human-checkpoint blockers:
```

- [ ] **Step 3: Mirror the same outcome in the control-plane doc**

Add a short section to `CODEX_ARCHITECTURE_CONTROL_PLANE.md`:

```md
## Current operating mode

- Repo mode: `hardening` or `feature-ready`
- Basis: `docs/decisions/ROADMAP_RESOLUTION_LEDGER.md`
```

- [ ] **Step 4: Commit**

```bash
git add docs/decisions/ROADMAP_RESOLUTION_LEDGER.md CODEX_ARCHITECTURE_CONTROL_PLANE.md
git commit -m "docs: record repo mode after roadmap review"
```

## Explicit recommendation on swarm usage

Yes, this review **should** go to the agent swarm, but only as a bounded program:
- `/codex` for code truth and regression surface
- `/gemini` for overclaim and falsification quality
- Kimi for contradiction review
- `/metaswarm` only after the primary reviews and dev-Mac evidence are in hand

No unscoped “review the whole repo” prompt is allowed. The swarm must review:
- the clean integration branch
- the current active blockers and roadmap claims
- the dev-Mac B1 evidence packet

## Expected outcome of the plan

After Task 7, every roadmap item should fall into one of these states:
- shipped and verified
- blocked by B1
- research-only
- human checkpoint required
- deferred with no current action

The repo should only leave hardening mode if the evidence and arbitration explicitly permit it. Based on the current repo state in `ROADMAP.md`, `CODEX_ARCHITECTURE_CONTROL_PLANE.md`, and `B1_CURRENT_MASTER_RUNBOOK.md`, the most likely outcome is:
- `stay in hardening mode`
- `complete the bounded B1 evidence + arbitration loop`
- `decide IV.7 go/no-go`
- only then reopen IV.5 or later features
