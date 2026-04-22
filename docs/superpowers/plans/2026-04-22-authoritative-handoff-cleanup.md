# Authoritative Handoff Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create and run one bounded swarm prompt that converts the current B1/IV.7 review state into an authoritative next-phase handoff packet without overclaiming what the runtime evidence proves.

**Architecture:** The next useful tranche is not more generic review. The branch already has runtime evidence, roadmap arbitration, and control-plane guidance. The gap is that handoff-facing docs still diverge in wording and authority level. This plan writes one strict swarm prompt that forces raw-artifact review, cleans residual overclaim in the actual edited files, demotes historical wording where needed, and creates one authoritative handoff document for the next worker.

**Tech Stack:** Markdown docs, `git`, `rg`, raw JSONL runtime artifact, `/codex`, `/gemini`, `/metaswarm`.

---

## File structure and responsibilities

- `docs/runbooks/B1_AUTHORITATIVE_HANDOFF_SWARM_PROMPT.md`
  Single bounded swarm prompt for the handoff-cleanup tranche.
- `docs/superpowers/plans/2026-04-22-authoritative-handoff-cleanup.md`
  This implementation plan.

Grounded source files the prompt must treat as inputs:
- `artifacts/diagnostics/b1-devmac-current-master.jsonl`
  Raw runtime evidence.
- `docs/runbooks/B1_CURRENT_MASTER_RUNBOOK.md`
  Classification ceiling for what the runtime evidence justifies.
- `CODEX_ARCHITECTURE_CONTROL_PLANE.md`
  Authoritative next-phase stance: diagnose now, not decide.
- `ROADMAP.md`
  Public project-state narrative that still contains stronger IV.7 wording.
- `docs/bug_B1_zmq_idle_death_handoff.md`
  Historical handoff/evidence history; useful, but not authoritative for current next-phase conclusions.
- `artifacts/diagnostics/b1-devmac-run-note.md`
  Runtime note that must remain aligned with the JSONL and runbook.
- `artifacts/reviews/roadmap-kimi-contradiction.md`
  Contradiction artifact that must not overclaim.
- `artifacts/reviews/roadmap-metaswarm-arbitration.md`
  Arbitration artifact that still contains residual overclaim.
- `docs/decisions/ROADMAP_RESOLUTION_LEDGER.md`
  Current next-step decision ledger; must be coherent with the final handoff.

### Task 1: Freeze the handoff-cleanup target set

**Files:**
- Modify: `docs/superpowers/plans/2026-04-22-authoritative-handoff-cleanup.md`
- Create: `docs/runbooks/B1_AUTHORITATIVE_HANDOFF_SWARM_PROMPT.md`

- [ ] **Step 1: Verify the active branch and dirty handoff files**

Run:

```bash
git -C /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery branch --show-current
git -C /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery rev-parse HEAD
git -C /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery rev-parse origin/master
git -C /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery status --short
```

Expected:
- branch is `codex/safe-merge-b1-truth-recovery`
- `origin/master` is the comparison base
- the runtime/arbitration/ledger files are still modified, which means the next prompt must target the **live working tree**, not just committed `HEAD`

- [ ] **Step 2: Reconfirm the handoff authority boundaries**

Run:

```bash
nl -ba /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/CODEX_ARCHITECTURE_CONTROL_PLANE.md | sed -n '114,123p'
nl -ba /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/CODEX_ARCHITECTURE_CONTROL_PLANE.md | sed -n '160,184p'
nl -ba /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/ROADMAP.md | sed -n '519,525p'
nl -ba /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/docs/bug_B1_zmq_idle_death_handoff.md | sed -n '589,613p'
```

Expected:
- control plane says the old handoff doc is useful but historically misleading
- control plane says IV.7 is diagnose-now, not decide-now
- roadmap and old handoff still contain stronger TCP/IV.7 wording than the control plane allows

- [ ] **Step 3: Reconfirm the runtime-evidence ceiling**

Run:

```bash
nl -ba /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/docs/runbooks/B1_CURRENT_MASTER_RUNBOOK.md | sed -n '45,60p'
python3 <<'EOF'
import json
from datetime import datetime
from pathlib import Path
path = Path("/Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/artifacts/diagnostics/b1-devmac-current-master.jsonl")
rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
first = datetime.fromisoformat(rows[0]["ts_utc"])
fail = datetime.fromisoformat(rows[52]["ts_utc"])
last = datetime.fromisoformat(rows[-1]["ts_utc"])
print(f"sample_count={len(rows)}")
print(f"time_to_failure_s={(fail-first).total_seconds():.1f}")
print(f"wall_clock_s={(last-first).total_seconds():.1f}")
EOF
```

Expected:
- runbook ceiling remains `engine REP path or lower transport is implicated`
- runtime artifact facts stay approximately:
  - `sample_count=56`
  - `time_to_failure_s=52.5`
  - `wall_clock_s=175.6`

- [ ] **Step 4: Commit the plan only if you are executing it**

```bash
git add /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/docs/superpowers/plans/2026-04-22-authoritative-handoff-cleanup.md
git commit -m "docs: add authoritative handoff cleanup plan"
```

### Task 2: Write the bounded handoff-cleanup swarm prompt

**Files:**
- Create: `docs/runbooks/B1_AUTHORITATIVE_HANDOFF_SWARM_PROMPT.md`

- [ ] **Step 1: Write the prompt with exact branch and worktree control**

Create `docs/runbooks/B1_AUTHORITATIVE_HANDOFF_SWARM_PROMPT.md` with:

```md
# B1 Authoritative Handoff Swarm Prompt

Use `/metaswarm` to run a bounded handoff-cleanup pass on the **live working tree** in:

`/Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery`

Branch:
- `codex/safe-merge-b1-truth-recovery`

Base:
- `origin/master`

Do not use:
- `master`
- `codex/preserved-local-master-2026-04-21`

This is not a repo review and not an IV.7 implementation pass.
This is an **authoritative handoff cleanup** pass.

Before doing anything, verify:
```bash
cd /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery
git branch --show-current
git rev-parse HEAD
git rev-parse origin/master
git status --short
git diff --name-only origin/master..HEAD
```

Then restate which modified tracked files and untracked docs you are actually reviewing.

## Goal

Leave one evidence-disciplined handoff state for the next worker:
- runtime facts remain accurate
- IV.7 remains a bounded experiment, not an approved migration
- TCP remains a hypothesis, not a proven culprit
- historical handoff text is not mistaken for current authoritative guidance
- one new handoff document tells the next engineer exactly what is authoritative and what to do next

## Source-of-truth inputs

Raw evidence and authority ceiling:
- `artifacts/diagnostics/b1-devmac-current-master.jsonl`
- `docs/runbooks/B1_CURRENT_MASTER_RUNBOOK.md`
- `CODEX_ARCHITECTURE_CONTROL_PLANE.md`

Files to correct:
- `artifacts/diagnostics/b1-devmac-run-note.md`
- `artifacts/reviews/roadmap-kimi-contradiction.md`
- `artifacts/reviews/roadmap-metaswarm-arbitration.md`
- `docs/decisions/ROADMAP_RESOLUTION_LEDGER.md`
- `ROADMAP.md`
- `docs/bug_B1_zmq_idle_death_handoff.md`

New file to create:
- `docs/B1_NEXT_PHASE_HANDOFF.md`

## Artifact-first method

1. Open `artifacts/diagnostics/b1-devmac-current-master.jsonl`
2. Identify:
   - first sample timestamp
   - last healthy sample timestamp
   - first failed sample timestamp
   - final sample timestamp
3. Compute or clearly infer:
   - time to failure
   - wall-clock capture duration
   - sample count
4. Compare those facts against every derived document
5. Use the exact runbook ceiling from `B1_CURRENT_MASTER_RUNBOOK.md`
6. Only then edit wording

## Required claim ceilings

Allowed:
- `B1 reproduced with evidence`
- `~52 seconds to failure after first sample`
- `~176 seconds wall-clock capture`
- `both bridge and direct paths fail together`
- `engine REP path or lower transport implicated`
- `IV.7 justified as bounded experiment`
- `baseline for comparison established`
- `TCP is one hypothesis under test`

Not allowed unless newly proven:
- `TCP is the culprit`
- `transport layer proven`
- `root cause proven`
- `strongly justified`
- `bypass TCP loopback entirely`
- `working hypothesis` stated as settled architecture truth
- `runtime ~56 seconds`
- `stopped at ~56 seconds due to failure`

## Required edits

1. Correct residual overclaim and timing drift in the four runtime/arbitration files.
2. Correct `ROADMAP.md` B1/IV.7 next-step wording so it matches the control plane and current evidence.
3. Add a short historical-warning note in `docs/bug_B1_zmq_idle_death_handoff.md` near the IV.7 section or header so readers do not treat it as the current authoritative architecture decision.
4. Create `docs/B1_NEXT_PHASE_HANDOFF.md` with:
   - current branch and base
   - authoritative inputs
   - historical-but-non-authoritative inputs
   - current B1 status
   - current IV.7 status
   - no-go rules
   - exact next action for the next engineer

## Execution order

1. `/codex`
   Task: raw-artifact truth pass + exact edit plan
2. `/gemini`
   Task: overclaim and authority-boundary pass
3. `/metaswarm`
   Task: arbitrate exact acceptable wording and handoff structure
4. Apply the agreed edits to the actual target files
5. Create `docs/B1_NEXT_PHASE_HANDOFF.md`
6. Re-open the edited files and verify them directly

## Required outputs

- `artifacts/reviews/handoff-cleanup-codex.md`
- `artifacts/reviews/handoff-cleanup-gemini.md`
- `artifacts/reviews/handoff-cleanup-metaswarm.md`
- `docs/B1_NEXT_PHASE_HANDOFF.md`

## Post-edit proof

After edits, verify against the **edited source files**, not a summary doc:

```bash
rg -n "TCP is the culprit|strongly justified|~56 seconds|stopped at ~56|bypass TCP loopback entirely|working hypothesis" \
  artifacts/diagnostics/b1-devmac-run-note.md \
  artifacts/reviews/roadmap-kimi-contradiction.md \
  artifacts/reviews/roadmap-metaswarm-arbitration.md \
  docs/decisions/ROADMAP_RESOLUTION_LEDGER.md \
  ROADMAP.md \
  docs/bug_B1_zmq_idle_death_handoff.md \
  docs/B1_NEXT_PHASE_HANDOFF.md
```

If any result remains in an authoritative or current-state file, the task is not complete.

## Required questions

1. What files are authoritative for next-phase handoff?
2. What files are historical/provenance only?
3. What is the strongest supported B1 claim?
4. What is the strongest supported IV.7 claim?
5. Which exact phrases had to be downgraded or removed?
6. After edits, do `ROADMAP.md`, `CODEX_ARCHITECTURE_CONTROL_PLANE.md`, `docs/B1_NEXT_PHASE_HANDOFF.md`, and the runtime decision files tell one coherent story?

## No-go rules

- no feature work
- no IV.7 implementation
- no safety config edits
- no repo-wide redesign
- no summary-first response
- no correction-summary-as-proof
- no using the historical handoff doc as the final authority

## Final answer format

- Findings
- Exact edits applied
- Authoritative handoff file created
- Remaining uncertainties
- Post-edit verification results
```

- [ ] **Step 2: Smoke-check the created prompt for branch, authority, and verification coverage**

Run:

```bash
rg -n "live working tree|origin/master|docs/B1_NEXT_PHASE_HANDOFF.md|Post-edit proof|TCP is the culprit|working hypothesis" \
  /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/docs/runbooks/B1_AUTHORITATIVE_HANDOFF_SWARM_PROMPT.md
```

Expected:
- prompt explicitly targets the live working tree
- prompt creates a new authoritative handoff doc
- prompt includes banned-phrase sweep
- prompt distinguishes authoritative vs historical documents

- [ ] **Step 3: Commit the prompt only if you are executing the plan**

```bash
git add /Users/vladimir/Projects/cryodaq/.worktrees/codex-safe-merge-b1-truth-recovery/docs/runbooks/B1_AUTHORITATIVE_HANDOFF_SWARM_PROMPT.md
git commit -m "docs: add authoritative handoff cleanup swarm prompt"
```

## Self-review

- Spec coverage:
  - The prompt now targets the actual remaining gap: current runtime files, roadmap, and historical handoff divergence.
  - It explicitly uses the runbook and control plane as the ceiling for acceptable claims.
  - It adds one authoritative next-phase handoff file instead of forcing future readers to reconstruct truth from mixed artifacts.
- Placeholder scan:
  - No `TBD`, `TODO`, or implicit “fix as appropriate” phrasing remains.
  - Every output path and target file is explicit.
- Type/term consistency:
  - `engine REP path or lower transport implicated` is used as the ceiling.
  - `justified as bounded experiment` is used for IV.7.
  - `docs/B1_NEXT_PHASE_HANDOFF.md` is consistently the new handoff target.
