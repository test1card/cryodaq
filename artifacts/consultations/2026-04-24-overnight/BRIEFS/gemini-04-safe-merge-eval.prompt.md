Model: gemini-2.5-pro

# Targeted audit — safe-merge branch 11 docs commits, merge or drop

## Mission

Branch `codex/safe-merge-b1-truth-recovery` contains commits that
`master` does not. The tip is `b2b4fb5`, plus 10 preceding docs
commits authored during the 2026-04-21..23 agent-swarm cycle (before
the orchestration contract was established). For each commit,
decide: merge into master, cherry-pick-modified, or drop as slop.

The architect will execute the recommendation in a follow-up
session. This brief produces the list.

## Context

- `git log --oneline master..codex/safe-merge-b1-truth-recovery`
  for the commit list (expect ~11 entries)
- `git show <sha>` for each commit's content
- Current state of `master` (post-cleanup-baseline 2026-04-23 +
  post-b2b4fb5-investigation 2026-04-24) for comparison / overlap
- `docs/decisions/2026-04-24-b2b4fb5-investigation.md` — the
  hardening question is settled
- `docs/decisions/2026-04-23-cleanup-baseline.md` — what got
  archived, what got deleted

## Per-commit evaluation

For each commit on the branch (exclude `b2b4fb5` — keep for now,
architect will decide repair strategy separately):

1. What does the commit add or change, in one sentence?
2. Is the content still relevant on 2026-04-24? Some may be
   superseded by later master commits; identify those.
3. Is it contradicted by anything now on master?
4. Does it add durable value (runbook, evidence, architectural
   record) or is it process detritus (review pack, agent prompt,
   ledger from a now-abandoned workflow)?
5. Recommendation: `MERGE` / `CHERRY-PICK modified` / `DROP`

## Output format

- First line: `Model: gemini-2.5-pro`
- Primary deliverable: single markdown table, one row per commit:
  `SHA (short) | Subject | Content summary (≤ 20 words) |
  Relevance now | Recommendation | Reasoning (≤ 30 words)`
- After the table: ≤ 3 paragraphs on patterns — e.g., "most of
  these are review-pack artifacts that belong archived if at all,
  not merged to master".
- If any commit needs `CHERRY-PICK modified`, specify what
  modification (file rename, path move, trim).
- Max 2500 words total.

## Scope fence

- Do NOT evaluate `b2b4fb5` itself — separate investigation,
  repair strategy is on Codex-01 / Gemini-01.
- Do not look at `experiment/iv7-ipc-transport` commits
  (157c4bc, 63a3fed) — those are on a different branch; separate
  merge decision.
- Do not propose new docs to write; you're evaluating existing
  ones.

## Response file

Write to: `artifacts/consultations/2026-04-24-overnight/RESPONSES/gemini-04-safe-merge-eval.response.md`
