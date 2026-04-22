# Roadmap Review Swarm Prompt

Use `/metaswarm` to run a bounded roadmap review on `codex/safe-merge-b1-truth-recovery` against `origin/master`.

Before doing any review work, the swarm must switch its local repo checkout to:
- branch: `codex/safe-merge-b1-truth-recovery`
- base for comparison: `origin/master`

Do not review whatever branch happens to be checked out locally. Do not use `master` or the preserved local branch as the working surface.

Required branch verification before starting:

```bash
git branch --show-current
git rev-parse HEAD
git rev-parse origin/master
git diff --name-only origin/master..HEAD
```

Expected:
- current branch is `codex/safe-merge-b1-truth-recovery`
- comparison base is `origin/master`
- diff surface is the bounded review tranche, not the preserved dirty local branch

This is not a request for open-ended repo review. It is a strict hardening-tranche review whose purpose is to answer one question: does CryoDAQ remain in hardening mode, or is there enough evidence to reopen feature work?

## Ground truth from the branch

- `IV.4` is closed in `ROADMAP.md`
- `IV.5` is still blocked by `B1`
- `B1` remains unresolved in `CODEX_ARCHITECTURE_CONTROL_PLANE.md`
- the branch already contains the canonical B1 tools and runbook:
  - `tools/_b1_diagnostics.py`
  - `tools/diag_zmq_b1_capture.py`
  - `docs/runbooks/B1_CURRENT_MASTER_RUNBOOK.md`

## Scope

Review:
- `ROADMAP.md`
- `CHANGELOG.md`
- `CODEX_ARCHITECTURE_CONTROL_PLANE.md`
- `docs/runbooks/B1_CURRENT_MASTER_RUNBOOK.md`
- `tools/_b1_diagnostics.py`
- `tools/diag_zmq_b1_capture.py`
- `tests/tools/test_b1_diagnostics.py`
- `tests/tools/test_diag_zmq_b1_capture.py`

And then review the dev-Mac evidence packet after it is created:
- `artifacts/diagnostics/b1-devmac-current-master.jsonl`
- `artifacts/diagnostics/b1-devmac-run-note.md`

## Required execution order

0. switch local checkout to `codex/safe-merge-b1-truth-recovery` and verify it with the commands above
1. `/codex` using `docs/runbooks/ROADMAP_REVIEW_PROMPT_CODEX.md`
2. `/gemini` using `docs/runbooks/ROADMAP_REVIEW_PROMPT_GEMINI.md`
3. dev-Mac B1 evidence run using `docs/runbooks/B1_CURRENT_MASTER_RUNBOOK.md`
4. Kimi using `docs/runbooks/ROADMAP_REVIEW_PROMPT_KIMI.md`
5. `/metaswarm` arbitration using `docs/runbooks/ROADMAP_REVIEW_PROMPT_METASWARM.md`

## Required outputs

- `artifacts/reviews/roadmap-codex-primary.md`
- `artifacts/reviews/roadmap-gemini-primary.md`
- `artifacts/reviews/roadmap-kimi-contradiction.md`
- `artifacts/reviews/roadmap-metaswarm-arbitration.md`
- `artifacts/diagnostics/b1-devmac-current-master.jsonl`
- `artifacts/diagnostics/b1-devmac-run-note.md`
- `docs/decisions/ROADMAP_RESOLUTION_LEDGER.md`

## Questions the swarm must answer

1. Is B1 still the blocker that keeps CryoDAQ in hardening mode?
2. Does the current branch provide enough evidence to justify IV.7 as the next bounded experiment?
3. Which roadmap items are actually done, blocked, research-only, deferred, or human-checkpoint-required?
4. Is any current roadmap or changelog wording overstating closure or readiness?

## No-go rules

- no feature work
- no transport migration in this tranche
- no safety-semantic config changes
- no claim that B1 is fixed without fresh runtime evidence
- no “review the whole repo” scope expansion
- no broad redesign suggestions

## Expected final decision format

The final arbitration must say explicitly:

- Repo mode: `hardening` or `feature-ready`
- B1 status: `open`, `insufficient evidence`, or `closed`
- IV.7 status: `justified next` or `premature`
- Roadmap item classes:
  - `done`
  - `blocked`
  - `research`
  - `defer`
  - `human checkpoint`
