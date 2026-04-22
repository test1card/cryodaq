# Bounded Roadmap Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the next CryoDAQ review tranche on `codex/safe-merge-b1-truth-recovery`, gather dev-Mac B1 evidence, and produce one authoritative decision on whether the repo stays in hardening mode or can resume feature work.

**Architecture:** This is a bounded review-and-arbitration tranche, not general repo exploration. The branch already contains the canonical B1 tooling and current-master runbook, so the work now is to freeze the branch baseline, collect evidence, run a structured Codex/Gemini/Kimi/Metaswarm review sequence, and resolve the roadmap into a single decision ledger.

**Tech Stack:** `git`, `pytest`, Markdown docs, `tools/_b1_diagnostics.py`, `tools/diag_zmq_b1_capture.py`, `/codex`, `/gemini`, Kimi, `/metaswarm`.

---

## File structure and responsibilities

- `docs/runbooks/ROADMAP_REVIEW_CONTROL.md`
  Review source of truth: branch, base, scope, outputs, no-go rules.
- `docs/runbooks/ROADMAP_REVIEW_LEDGER.md`
  Execution order and completion tracking.
- `docs/runbooks/ROADMAP_REVIEW_PROMPT_CODEX.md`
  Codex primary code-truth/review prompt.
- `docs/runbooks/ROADMAP_REVIEW_PROMPT_GEMINI.md`
  Gemini primary adversarial prompt.
- `docs/runbooks/ROADMAP_REVIEW_PROMPT_KIMI.md`
  Kimi contradiction prompt.
- `docs/runbooks/ROADMAP_REVIEW_PROMPT_METASWARM.md`
  Final arbitration prompt.
- `docs/runbooks/ROADMAP_REVIEW_SWARM_PROMPT.md`
  Single launch prompt for `/metaswarm` that starts the bounded review program.
- `docs/decisions/ROADMAP_RESOLUTION_LEDGER.md`
  Final classification of roadmap items and repo mode.
- `tests/tools/test_roadmap_review_pack.py`
  Acceptance test for the review pack and prompt files.
- `artifacts/diagnostics/b1-devmac-current-master.jsonl`
  Canonical dev-Mac evidence artifact.
- `artifacts/diagnostics/b1-devmac-run-note.md`
  Branch/ref/dirty-state/evidence summary note.
- `artifacts/reviews/roadmap-codex-primary.md`
  Codex review result.
- `artifacts/reviews/roadmap-gemini-primary.md`
  Gemini review result.
- `artifacts/reviews/roadmap-kimi-contradiction.md`
  Kimi contradiction result.
- `artifacts/reviews/roadmap-metaswarm-arbitration.md`
  Metaswarm arbitration result.

Execution baseline:
- Branch: `codex/safe-merge-b1-truth-recovery`
- Worktree: `/Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery`
- Base: `origin/master`
- Do not use `/Users/vladimir/Projects/cryodaq` while it is on `codex/preserved-local-master-2026-04-21`

Grounded constraints from current repo state:
- [ROADMAP.md](/Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/ROADMAP.md:88) still blocks `IV.5` on B1.
- [ROADMAP.md](/Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/ROADMAP.md:426) still says B1 blocks the next formal tag line.
- [CODEX_ARCHITECTURE_CONTROL_PLANE.md](/Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/CODEX_ARCHITECTURE_CONTROL_PLANE.md:134) says the next safe move is one disciplined evidence pass.
- [docs/runbooks/B1_CURRENT_MASTER_RUNBOOK.md](/Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/docs/runbooks/B1_CURRENT_MASTER_RUNBOOK.md:1) already defines the canonical capture.

### Task 1: Freeze the review baseline and validate the review pack

**Files:**
- Create: `tests/tools/test_roadmap_review_pack.py`
- Create: `docs/runbooks/ROADMAP_REVIEW_CONTROL.md`
- Create: `docs/runbooks/ROADMAP_REVIEW_LEDGER.md`

- [ ] **Step 1: Write the failing acceptance test**

Create `tests/tools/test_roadmap_review_pack.py`:

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
        "artifacts/diagnostics/b1-devmac-current-master.jsonl",
        "artifacts/reviews/roadmap-codex-primary.md",
        "artifacts/reviews/roadmap-gemini-primary.md",
        "artifacts/reviews/roadmap-kimi-contradiction.md",
        "artifacts/reviews/roadmap-metaswarm-arbitration.md",
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

- [ ] **Step 3: Write the review control doc**

Create `docs/runbooks/ROADMAP_REVIEW_CONTROL.md`:

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
1. Is B1 still the blocker that keeps CryoDAQ in hardening mode?
2. Which roadmap items are actually shipped versus merely planned?
3. Which roadmap items require human checkpoint or research rather than implementation?
4. Is IV.7 justified next, or still premature?

Required outputs:
- `artifacts/diagnostics/b1-devmac-current-master.jsonl`
- `artifacts/diagnostics/b1-devmac-run-note.md`
- `artifacts/reviews/roadmap-codex-primary.md`
- `artifacts/reviews/roadmap-gemini-primary.md`
- `artifacts/reviews/roadmap-kimi-contradiction.md`
- `artifacts/reviews/roadmap-metaswarm-arbitration.md`
- `docs/decisions/ROADMAP_RESOLUTION_LEDGER.md`

No-go rules:
- no feature implementation
- no transport migration
- no safety-semantic config edits
- no claim that B1 is fixed without fresh runtime evidence
```

- [ ] **Step 4: Write the review ledger**

Create `docs/runbooks/ROADMAP_REVIEW_LEDGER.md`:

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
- `artifacts/diagnostics/b1-devmac-current-master.jsonl`
- `artifacts/diagnostics/b1-devmac-run-note.md`
- `artifacts/reviews/roadmap-codex-primary.md`
- `artifacts/reviews/roadmap-gemini-primary.md`
- `artifacts/reviews/roadmap-kimi-contradiction.md`
- `artifacts/reviews/roadmap-metaswarm-arbitration.md`
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
git commit -m "docs: add roadmap review control pack"
```

### Task 2: Create the review prompts and the single swarm launch prompt

**Files:**
- Create: `docs/runbooks/ROADMAP_REVIEW_PROMPT_CODEX.md`
- Create: `docs/runbooks/ROADMAP_REVIEW_PROMPT_GEMINI.md`
- Create: `docs/runbooks/ROADMAP_REVIEW_PROMPT_KIMI.md`
- Create: `docs/runbooks/ROADMAP_REVIEW_PROMPT_METASWARM.md`
- Create: `docs/runbooks/ROADMAP_REVIEW_SWARM_PROMPT.md`
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
        "current-master evidence",
        "ROADMAP_RESOLUTION_LEDGER.md",
    ],
    "ROADMAP_REVIEW_SWARM_PROMPT.md": [
        "/metaswarm",
        "codex/safe-merge-b1-truth-recovery",
        "dev-Mac B1 evidence",
        "no feature work",
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

Review `codex/safe-merge-b1-truth-recovery` against `origin/master`.

Priority:
1. code truth
2. regression surface
3. affected callers
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

Review `codex/safe-merge-b1-truth-recovery` against `origin/master`.

Priority:
1. overclaim detection
2. falsification quality
3. unsupported assumptions
4. whether roadmap language outruns evidence

Required output:
- `artifacts/reviews/roadmap-gemini-primary.md`

Do not approve IV.7 without evidence.
Do not downgrade B1 merely because mitigations exist.
Do not suggest broad redesigns.
```

- [ ] **Step 5: Write the Kimi prompt**

Create `docs/runbooks/ROADMAP_REVIEW_PROMPT_KIMI.md`:

```md
# Roadmap Review Prompt: Kimi Contradiction

Invocation: `Kimi`

Inputs:
- `artifacts/reviews/roadmap-codex-primary.md`
- `artifacts/reviews/roadmap-gemini-primary.md`
- `artifacts/diagnostics/b1-devmac-current-master.jsonl`
- `artifacts/diagnostics/b1-devmac-run-note.md`

Task:
- find contradiction
- find shared blind spots
- reject claims not warranted by evidence

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
- state which roadmap items are done, blocked, deferred, research, or human checkpoint

Required output:
- `artifacts/reviews/roadmap-metaswarm-arbitration.md`
- `docs/decisions/ROADMAP_RESOLUTION_LEDGER.md`
```

- [ ] **Step 7: Write the single swarm launch prompt**

Create `docs/runbooks/ROADMAP_REVIEW_SWARM_PROMPT.md`:

```md
# Roadmap Review Swarm Prompt

Use `/metaswarm` to run a bounded roadmap review on `codex/safe-merge-b1-truth-recovery` against `origin/master`.

Scope:
- review current roadmap/control truth
- review canonical B1 tooling and runbook
- review dev-Mac B1 evidence after it is captured
- resolve roadmap items into one authoritative ledger

Do not do:
- no feature work
- no transport migration
- no safety-semantic config changes
- no claim that B1 is fixed without fresh runtime evidence

Execution order:
1. `/codex` using `docs/runbooks/ROADMAP_REVIEW_PROMPT_CODEX.md`
2. `/gemini` using `docs/runbooks/ROADMAP_REVIEW_PROMPT_GEMINI.md`
3. dev-Mac B1 evidence run using `docs/runbooks/B1_CURRENT_MASTER_RUNBOOK.md`
4. Kimi using `docs/runbooks/ROADMAP_REVIEW_PROMPT_KIMI.md`
5. `/metaswarm` arbitration using `docs/runbooks/ROADMAP_REVIEW_PROMPT_METASWARM.md`

Required final outputs:
- `artifacts/reviews/roadmap-codex-primary.md`
- `artifacts/reviews/roadmap-gemini-primary.md`
- `artifacts/reviews/roadmap-kimi-contradiction.md`
- `artifacts/reviews/roadmap-metaswarm-arbitration.md`
- `artifacts/diagnostics/b1-devmac-current-master.jsonl`
- `artifacts/diagnostics/b1-devmac-run-note.md`
- `docs/decisions/ROADMAP_RESOLUTION_LEDGER.md`
```

- [ ] **Step 8: Run the test to verify it passes**

Run:

```bash
/Users/vladimir/Projects/cryodaq/.venv/bin/pytest tests/tools/test_roadmap_review_pack.py -q
```

Expected:
- `PASS`

- [ ] **Step 9: Commit**

```bash
git add tests/tools/test_roadmap_review_pack.py docs/runbooks/ROADMAP_REVIEW_PROMPT_CODEX.md docs/runbooks/ROADMAP_REVIEW_PROMPT_GEMINI.md docs/runbooks/ROADMAP_REVIEW_PROMPT_KIMI.md docs/runbooks/ROADMAP_REVIEW_PROMPT_METASWARM.md docs/runbooks/ROADMAP_REVIEW_SWARM_PROMPT.md
git commit -m "docs: add bounded roadmap review prompts"
```

### Task 3: Run the primary reviews first

**Files:**
- Create: `artifacts/reviews/roadmap-codex-primary.md`
- Create: `artifacts/reviews/roadmap-gemini-primary.md`
- Modify: `docs/runbooks/ROADMAP_REVIEW_LEDGER.md`

- [ ] **Step 1: Record the exact branch state**

Run:

```bash
git rev-parse HEAD
git diff --name-only origin/master..HEAD
git status --short
```

Expected:
- `HEAD` is on `codex/safe-merge-b1-truth-recovery`
- diff vs `origin/master` matches the active review surface
- any local dirt is recorded before review output begins

- [ ] **Step 2: Run Codex primary review**

Use `docs/runbooks/ROADMAP_REVIEW_PROMPT_CODEX.md`.

Save output to:

```text
artifacts/reviews/roadmap-codex-primary.md
```

- [ ] **Step 3: Run Gemini primary review**

Use `docs/runbooks/ROADMAP_REVIEW_PROMPT_GEMINI.md`.

Save output to:

```text
artifacts/reviews/roadmap-gemini-primary.md
```

- [ ] **Step 4: Update the ledger after the primary reviews**

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

### Task 4: Run the dev-Mac B1 evidence pass

**Files:**
- Create: `artifacts/diagnostics/b1-devmac-current-master.jsonl`
- Create: `artifacts/diagnostics/b1-devmac-run-note.md`

- [ ] **Step 1: Start the run note**

Create `artifacts/diagnostics/b1-devmac-run-note.md`:

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
- engine starts and stays alive

- [ ] **Step 3: Run the canonical capture**

Run in another shell:

```bash
/Users/vladimir/Projects/cryodaq/.venv/bin/python tools/diag_zmq_b1_capture.py \
  --duration 180 \
  --interval 1.0 \
  --output artifacts/diagnostics/b1-devmac-current-master.jsonl
```

Expected:
- JSONL file exists
- capture exits zero

- [ ] **Step 4: Record the result class**

Append one exact summary to `artifacts/diagnostics/b1-devmac-run-note.md`:

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
git commit -m "diag: capture dev-mac B1 evidence for roadmap review"
```

### Task 5: Run contradiction review and final arbitration

**Files:**
- Create: `artifacts/reviews/roadmap-kimi-contradiction.md`
- Create: `artifacts/reviews/roadmap-metaswarm-arbitration.md`
- Create: `docs/decisions/ROADMAP_RESOLUTION_LEDGER.md`
- Modify: `docs/runbooks/ROADMAP_REVIEW_LEDGER.md`

- [ ] **Step 1: Run Kimi contradiction review**

Use `docs/runbooks/ROADMAP_REVIEW_PROMPT_KIMI.md`.

Save output to:

```text
artifacts/reviews/roadmap-kimi-contradiction.md
```

- [ ] **Step 2: Run Metaswarm arbitration**

Use `docs/runbooks/ROADMAP_REVIEW_PROMPT_METASWARM.md`.

Save output to:

```text
artifacts/reviews/roadmap-metaswarm-arbitration.md
```

- [ ] **Step 3: Write the roadmap resolution ledger**

Create `docs/decisions/ROADMAP_RESOLUTION_LEDGER.md`:

```md
# Roadmap Resolution Ledger

| Item | Current status | Evidence source | Next action |
|---|---|---|---|
| B1 | blocked / insufficient evidence / closed | `roadmap-metaswarm-arbitration.md` + `b1-devmac-run-note.md` | stay hardening / run IV.7 branch / close |
| IV.5 | blocked by B1 | `ROADMAP.md` + arbitration | do not implement yet |
| F3 | blocked | roadmap + arbitration | queue after B1 |
| F5 | blocked + Vladimir dependency | roadmap + arbitration | queue after B1 + checkpoint |
| F17 | blocked | roadmap + arbitration | queue after B1 |
| F8 | research | roadmap | no code now |
| F9 | human checkpoint | roadmap | Vladimir review first |
| F4/F7/F10/F12/F13/F14/F15/F16/F18 | deferred | roadmap | no action now |
| F1/F2/F6/F11 | done | roadmap + changelog | keep as shipped |
```

- [ ] **Step 4: Complete the ledger**

Append to `docs/runbooks/ROADMAP_REVIEW_LEDGER.md`:

```md
## Final review status

- Codex primary: complete
- Gemini primary: complete
- Dev-Mac B1 evidence: complete
- Kimi contradiction: complete
- Metaswarm arbitration: complete
```

- [ ] **Step 5: Commit**

```bash
git add artifacts/reviews/roadmap-kimi-contradiction.md artifacts/reviews/roadmap-metaswarm-arbitration.md docs/decisions/ROADMAP_RESOLUTION_LEDGER.md docs/runbooks/ROADMAP_REVIEW_LEDGER.md
git commit -m "docs: record contradiction review and roadmap arbitration"
```

### Task 6: Resolve repo direction after arbitration

**Files:**
- Modify: `ROADMAP.md`
- Modify: `CHANGELOG.md`
- Modify: `CODEX_ARCHITECTURE_CONTROL_PLANE.md`
- Modify: `docs/decisions/ROADMAP_RESOLUTION_LEDGER.md`

- [ ] **Step 1: Apply the repo-mode rule**

Use this exact rule:

```text
If B1 is still open or evidence is insufficient, CryoDAQ remains in hardening mode.
If B1 is closed by fresh runtime evidence and contradiction review does not reject that closure, CryoDAQ may leave hardening mode and draft the next feature batch.
```

- [ ] **Step 2: Record the repo mode**

Append to `docs/decisions/ROADMAP_RESOLUTION_LEDGER.md`:

```md
## Repo mode decision

Outcome: `hardening` or `feature-ready`

Reason:
- B1 status:
- IV.7 status:
- Safety/human-checkpoint blockers:
```

- [ ] **Step 3: Mirror that outcome in the control docs**

Apply these exact edits:
- `ROADMAP.md`: keep IV.5 blocked if outcome is `hardening`
- `CODEX_ARCHITECTURE_CONTROL_PLANE.md`: add `Repo mode: hardening` or `Repo mode: feature-ready`
- `CHANGELOG.md`: adjust `Unreleased` only if arbitration changes the next-step wording

- [ ] **Step 4: Verify all active roadmap items are resolved**

Run:

```bash
rg -n '^### F|^### B1|^### IV\\.' ROADMAP.md
sed -n '1,220p' docs/decisions/ROADMAP_RESOLUTION_LEDGER.md
```

Expected:
- every active item appears in the ledger
- no active item is left without `Current status` and `Next action`

- [ ] **Step 5: Commit**

```bash
git add ROADMAP.md CHANGELOG.md CODEX_ARCHITECTURE_CONTROL_PLANE.md docs/decisions/ROADMAP_RESOLUTION_LEDGER.md
git commit -m "docs: resolve roadmap direction after bounded review"
```

## Swarm usage decision

Yes, this should go to the swarm, but only in the bounded form above:
- `/codex` for code truth and regression surface
- `/gemini` for overclaim and falsification quality
- Kimi for contradiction review
- `/metaswarm` for final arbitration only after primary reviews and dev-Mac evidence exist

Do **not** ask the swarm to “review the whole repo.” The authoritative target is:
- branch `codex/safe-merge-b1-truth-recovery`
- the 8-file review surface above `origin/master`
- the dev-Mac B1 evidence packet
- the roadmap/control/changelog truth story
