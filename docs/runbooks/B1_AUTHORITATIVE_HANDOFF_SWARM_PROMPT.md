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
