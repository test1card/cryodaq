# Safe-merge branch recon — D1/D4 re-plan

**Date:** 2026-04-24 (session 3 — recon pass)
**Source branch:** `codex/safe-merge-b1-truth-recovery` (tip `b2b4fb5`)
**Target branch:** `master` (tip `0a38f93`)
**Commits in range (`master..codex/safe-merge-b1-truth-recovery`):** **18**

## Classification table (chronological order)

| # | SHA | subject | files | bucket | Gemini-04 verdict |
|---|---|---|---|---|---|
| 1 | `8a32494` | docs: sync B1 roadmap and control-plane state | `CODEX_ARCHITECTURE_CONTROL_PLANE.md`, `ROADMAP.md` | **DOCS-ONLY** | MERGE |
| 2 | `3b661e2` | tools: add reusable B1 diagnostic helpers | `tools/_b1_diagnostics.py` (+ test) | **DIAG-TOOL** | MERGE |
| 3 | `056a199` | tools: add canonical B1 capture CLI | `tools/diag_zmq_b1_capture.py` (+ test) | **DIAG-TOOL** | MERGE |
| 4 | `9824b85` | docs: add current-master B1 runbook | `docs/runbooks/B1_CURRENT_MASTER_RUNBOOK.md` | **DOCS-ONLY** | MERGE |
| 5 | `8e79ea6` | tools: align B1 diagnostic helpers | `tools/_b1_diagnostics.py` (+ test) | **DIAG-TOOL** | MERGE |
| 6 | `983480d` | tools: align B1 capture CLI with jsonl master capture | `tools/diag_zmq_b1_capture.py` (+ test) | **DIAG-TOOL** | MERGE |
| 7 | `fafaa50` | docs: align runbook with capture plan | `docs/runbooks/B1_CURRENT_MASTER_RUNBOOK.md` | **DOCS-ONLY** | MERGE |
| 8 | `2ed975f` | tools: record direct probe timeouts in B1 capture | `tools/diag_zmq_b1_capture.py` (+ test) | **DIAG-TOOL** | MERGE |
| 9 | `6405a62` | docs: reconstruct post-v0.33.0 changelog releases | `CHANGELOG.md` | **DOCS-ONLY** | MERGE |
| 10 | `32b4312` | docs: make changelog grouping non-overlapping | `CHANGELOG.md` | **DOCS-ONLY** | MERGE |
| 11 | `8ddd2f4` | docs: align release gating with reconstructed versions | `CODEX_ARCH`, `ROADMAP.md`, `B1_RUNBOOK` | **DOCS-ONLY** | MERGE |
| 12 | `ab72c84` | docs: add roadmap review prompts and resolution ledger | `docs/decisions/ROADMAP_RESOLUTION_LEDGER.md`, 4 `ROADMAP_REVIEW_PROMPT_*` | **DROP** | DROP |
| 13 | `8feda6b` | review: add roadmap review artifacts (codex/gemini/kimi/metaswarm) | 4 `artifacts/reviews/roadmap-*.md` | **DROP** | DROP |
| 14 | `bbc65c8` | diagnostics: add B1 evidence documentation (runbook NOT RUN) | 2 `artifacts/diagnostics/b1-devmac-*` | **DROP** | DROP |
| 15 | `0a4ae04` | review: update Kimi/Metaswarm arbitration with evidence-gap | 3 files (artifacts + ledger) | **DROP** | DROP |
| 16 | `9ccb3d5` | docs: finalize B1 handoff truth-recovery packet | 17 files mixed | **CHERRY-PICK modified** (ROADMAP.md only) | CHERRY-PICK modified |
| 17 | `4cdc4f4` | docs: align B1 runbook artifact path | `docs/runbooks/B1_CURRENT_MASTER_RUNBOOK.md` | **DOCS-ONLY** | MERGE |
| 18 | `b2b4fb5` | fix: harden B1 capture bridge startup validation | `tools/diag_zmq_b1_capture.py` (+ test) | **REPAIR TARGET** (D1 scope) | excluded from Gemini-04 per scope fence |

## Bucket counts

| bucket | count | SHAs |
|---|---|---|
| DIAG-TOOL | 5 | `3b661e2`, `056a199`, `8e79ea6`, `983480d`, `2ed975f` |
| DOCS-ONLY | 7 | `8a32494`, `9824b85`, `fafaa50`, `6405a62`, `32b4312`, `8ddd2f4`, `4cdc4f4` |
| CHERRY-PICK modified | 1 | `9ccb3d5` |
| DROP | 4 | `ab72c84`, `8feda6b`, `bbc65c8`, `0a4ae04` |
| REPAIR TARGET | 1 | `b2b4fb5` |
| **total** | **18** | |

## Cross-check vs architect expectation and Gemini-04

- **Architect said "11 commits per Gemini-04 table" in prior prompt.** Actual: **18 commits in range**, of which 17 were evaluated by Gemini-04 (excluding `b2b4fb5` per brief scope fence). The "11" figure was off — Gemini-04's table has 17 rows.
- **Gemini-04: 12 MERGE + 1 CHERRY-PICK modified + 4 DROP = 17 ✓** (matches my DIAG-TOOL 5 + DOCS-ONLY 7 + CHERRY-PICK 1 + DROP 4 = 17).
- **Plus b2b4fb5 = 18 ✓** — total matches.

## Conflict analysis

Two simulations were run:

### 1. Independent replay (each commit onto bare master)

Most commits reported CONFLICT because later commits modify files introduced by earlier commits (`8e79ea6` modifies `_b1_diagnostics.py` which `3b661e2` creates, etc.) — chain-dependency conflicts, NOT content conflicts with master.

### 2. Sequential replay (cherry-pick in chronological order)

**All 12 non-DROP commits cherry-picked CLEANLY against master.** No real content conflicts exist between safe-merge branch work and master's parallel evolution. Zero manual merge required.

The simulation branch `recon-sequential` was created, replayed all 12 in order, produced 12 new SHAs (cleanly rebased onto master), then deleted. Master untouched.

### 9ccb3d5 specifically

Conflicts when cherry-picked at any point because it:
- Modifies `artifacts/reviews/roadmap-kimi-contradiction.md` and `roadmap-metaswarm-arbitration.md` (created by `8feda6b`, modified by `0a4ae04` — both in DROP bucket)
- Modifies `artifacts/diagnostics/b1-devmac-*` (created by `bbc65c8` — DROP bucket)
- Modifies `docs/decisions/ROADMAP_RESOLUTION_LEDGER.md` (also modified by DROP commits)
- Modifies `ROADMAP.md` (clean-mergeable)

Gemini-04 already specified "**keep only ROADMAP.md delta**" — the conflict files are all DROP-bucket siblings, so the modified cherry-pick discards them naturally. CC executes as:
```
git cherry-pick -n 9ccb3d5
git reset HEAD -- <everything except ROADMAP.md>
git checkout -- <same set from master>
git commit -c 9ccb3d5  # edit msg to note partial
```

## Proposed execution order

Architect's prior plan named three sub-phases:

### D4a — DIAG-TOOL prereq for D1 (5 commits)

Cherry-pick in chronological order ONTO master:
```
git cherry-pick 3b661e2 056a199 8e79ea6 983480d 2ed975f
```

Result: master now has `tools/_b1_diagnostics.py`, `tools/diag_zmq_b1_capture.py` (in its pre-`b2b4fb5` state) plus matching tests. This is the state that the R1 repair must land on top of.

### D1 — R1 repair (one commit on new branch)

Branch `feat/b2b4fb5-repair` from post-D4a master. Apply R1 per Codex-01 + Stream A synthesis: bounded-backoff retry inside `_validate_bridge_startup()`. Push branch for architect review and merge.

**b2b4fb5 itself is NOT cherry-picked.** The R1 commit IS the repaired form of b2b4fb5's intent.

### D4b — DOCS-ONLY + ROADMAP-partial on top of D1 (8 commits)

Once D1 is merged (or even before, if architect prefers parallel), cherry-pick the 7 docs-only commits in chronological order, plus the 9ccb3d5 modified cherry-pick:
```
git cherry-pick 8a32494 9824b85 fafaa50 6405a62 32b4312 8ddd2f4 4cdc4f4
git cherry-pick -n 9ccb3d5   # then trim to ROADMAP.md only, commit
```

Note: `8a32494`, `8ddd2f4`, `9824b85`, `fafaa50`, `4cdc4f4` modify files that the diag-tool commits don't touch — they can land at any order relative to D4a/D1. Listing them post-D1 simply keeps the chronological order clean on master.

### DROPs — not merged, ledger entry

4 commits recorded in the session ledger as dropped per Gemini-04 rationale. `codex/safe-merge-b1-truth-recovery` branch stays preserved (it still holds these commits in its history; they're just never landed on master).

## Alternative ordering considered

**Alt-A — single batch cherry-pick of all 12 commits in chronological order.** Does not separate D4a from D4b. Simpler to execute (one run of `git cherry-pick`), but commingles DIAG-TOOL with DOCS-ONLY. Architect's prior plan specifically split them, so I'm not proposing this unless architect prefers.

**Alt-B — D4a first, then D1 on new branch, then D4b on master (parallel to D1).** Lets docs work proceed while R1 is implemented. Minor coordination risk: the `9ccb3d5` modified cherry-pick touches `ROADMAP.md`, and if D1 also touches `ROADMAP.md` (unlikely but possible), we'd have a merge conflict. Pure R1 scope is `tools/` + `tests/tools/` — shouldn't touch ROADMAP. So this alternative is safe.

## Questions for architect

1. **Execution order:** confirm D4a → D1 → D4b (sequential), or prefer Alt-B (D4a, then D1 and D4b in parallel)?
2. **9ccb3d5 cherry-pick modification:** Gemini-04 said "keep only ROADMAP.md changes". Confirm or adjust (e.g. also keep `docs/bug_B1_zmq_idle_death_handoff.md` update)?
3. **Drop handling:** ledger entry only, or also create a forwarding doc at `docs/audits/2026-04-22-agent-swarm/` summarizing what was dropped and why?
4. **b2b4fb5 residual:** after R1 lands as D1, should CC also verify that `tools/diag_zmq_b1_capture.py` on master is functionally equivalent to the post-b2b4fb5 state *plus* the R1 improvement (i.e., the retry works the same way the original probe did, just with retries)?
5. **D4a commit message envelope:** individual cherry-picks preserve original messages, or add a common `Batch: D4a / diag-tool prereq` line to each? (Risk of rewriting 5 commits' bodies vs preserving fidelity.)

## Readiness for next phase

Recon complete. **No unexpected findings.** All 12 non-DROP commits are content-clean vs master; the split D4a / D1 / D4b is feasible as architect proposed; the 17/18 accounting matches Gemini-04.

**Awaiting architect approval on questions 1-5 before any execution.**
