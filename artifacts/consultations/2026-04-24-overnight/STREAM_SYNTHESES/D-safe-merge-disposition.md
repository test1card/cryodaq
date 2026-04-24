# Stream D synthesis — safe-merge branch disposition

## Consulted

| model (actual) | response file | one-line summary |
|---|---|---|
| Gemini 2.5-pro | `RESPONSES/gemini-04-safe-merge-eval.response.md` | 17 commits evaluated (hypothesis `master..codex/safe-merge-b1-truth-recovery` excluding `b2b4fb5` per brief scope fence). **12 MERGE, 1 CHERRY-PICK modified, 4 DROP.** |

Single-consultant stream — Gemini-04 is the only model that read all 11 commits and produced a per-commit verdict. No convergence / divergence step.

## Per-commit recommendations (Gemini-04 verbatim table compressed)

### MERGE (12 commits — low-churn docs + diagnostic tool evolution)

| SHA | subject | why merge |
|---|---|---|
| `4cdc4f4` | docs: align B1 runbook artifact path | runbook↔tool consistency fix |
| `8ddd2f4` | docs: align release gating with reconstructed version lines | aligns with changelog reconstruction |
| `32b4312` | docs: make post-v0.33.0 changelog grouping non-overlapping | changelog cleanup |
| `6405a62` | docs: reconstruct post-v0.33.0 changelog releases | valuable historical reconstruction |
| `2ed975f` | tools: record direct probe timeouts in B1 capture | diag-tool bugfix |
| `fafaa50` | docs: align current-master B1 runbook with capture plan | runbook final state |
| `983480d` | tools: align B1 capture CLI with jsonl master capture | diag-tool final state |
| `8e79ea6` | tools: align B1 diagnostic helpers with bridge/direct capture | diag-tool evolution step |
| `9824b85` | docs: add current-master B1 runbook | runbook initial state (preserve history) |
| `056a199` | tools: add canonical B1 capture CLI | diag-tool initial state (preserve history) |
| `3b661e2` | tools: add reusable B1 diagnostic helpers | diag-tool foundation (preserve history) |
| `8a32494` | docs: sync B1 roadmap and control-plane state | valuable state-capture doc |

### CHERRY-PICK modified (1 commit)

| SHA | subject | modification |
|---|---|---|
| `9ccb3d5` | docs: finalize B1 handoff truth-recovery packet | **Keep ONLY `ROADMAP.md` changes.** Drop the voluminous agent-prompt files and diagnostic data attached to this commit — they are process detritus. |

### DROP (4 commits — process detritus, no durable value)

| SHA | subject | why drop |
|---|---|---|
| `bbc65c8` | diagnostics: add B1 evidence documentation (runbook NOT RUN) | placeholder, immediately superseded by `9ccb3d5` |
| `0a4ae04` | review: update Kimi/Metaswarm arbitration with evidence-gap findings | transient update to process artifacts that are themselves being dropped |
| `8feda6b` | review: add roadmap review artifacts from codex/gemini/kimi/metaswarm passes | multi-agent review logs; conclusions already captured in other docs |
| `ab72c84` | docs: add roadmap review prompts and resolution ledger | scaffolding for a review process, no durable value |

## CC decision

**Adopt Gemini-04's recommendations with minor architect-domain caveat.**

### Execution plan (for a follow-up CC session, under §5 branch discipline)

**Option DD-A — simple chronological cherry-pick (preferred):**

1. Create `feat/safe-merge-cleanup` branch from `master`.
2. Cherry-pick the 12 MERGE commits in chronological order:
   ```
   git cherry-pick 3b661e2 056a199 9824b85 8e79ea6 983480d fafaa50 \
                   2ed975f 8a32494 6405a62 32b4312 8ddd2f4 4cdc4f4
   ```
3. For `9ccb3d5` (CHERRY-PICK modified):
   ```
   git cherry-pick --no-commit 9ccb3d5
   # Un-stage everything except ROADMAP.md:
   git reset HEAD -- <other-paths>
   git checkout -- <other-paths>
   git commit -c 9ccb3d5  # edit commit msg to note "docs-only cherry-pick"
   ```
4. The 4 DROP commits are never replayed — effectively abandoned.
5. Fast-forward merge `feat/safe-merge-cleanup` → `master`.
6. Delete `codex/safe-merge-b1-truth-recovery` branch after merge.

**Option DD-B — defer entirely until after Stream A + B work lands:**

The 12 MERGE commits are not blocking any active work. They are historical reconstructions + diag-tool evolution that's already effectively on master via other paths (the diag tools currently used on `master` may differ from these historical versions). CC cannot confirm the diag-tool commits are byte-identical to current master's tools without deeper comparison.

**CC recommendation: DD-A for the docs commits only, DD-B for the diag-tool commits until CC does a diff vs current master's `tools/diag_zmq_*.py`.**

Specifically:
- Safe to merge now (docs only, no code overlap risk): `6405a62`, `32b4312`, `8ddd2f4`, `4cdc4f4`, `fafaa50`, `9824b85`, `8a32494`, plus the `9ccb3d5` modified cherry-pick. 8 commits.
- Defer with diff review: `2ed975f`, `983480d`, `8e79ea6`, `056a199`, `3b661e2` (5 diag-tool commits). A CC session can diff the branch's `tools/diag_zmq_*.py` vs `master`'s and determine whether replay is additive or conflicting.

## Rationale

- Single-model review is a weaker signal than adversarial pair, but the task (per-commit docs vs code classification) is mechanical enough that Gemini's wide-context read is trustworthy.
- The MERGE chain has no safety-critical code changes — it's docs + a diag-tool evolution. Low blast radius either way.
- The DROP recommendations are process artifacts from the pre-ORCHESTRATION swarm cycle (documented in `docs/ORCHESTRATION.md` §1). Consistent with §6.2 whitelist + §6.4 "consultant outputs are ephemeral".
- The CHERRY-PICK modified case (`9ccb3d5`) is the single judgment call — Gemini wants to salvage the `ROADMAP.md` delta but drop the agent-prompt attachments. CC agrees.

## Residual risks

1. **Diag-tool commits may conflict with current master** if the tools have been modified independently since the branch was cut. A quick `git diff master <sha>~1..<sha> -- tools/diag_zmq_*.py` per commit would resolve this before replay.
2. **Changelog reconstruction (`6405a62`) asserts `0.34.0` / `0.35.0` / `0.36.0` version jumps** that don't match current `pyproject.toml = 0.13.0` (see Stream C residual risk #1). Merging this commit commits to a specific historical version labeling that may conflict with whatever architect resolves for the version policy.
3. **Gemini-04 was the only model on this stream.** If something subtle was missed in any of the 17 commits (e.g. a stealth config change piggybacking on a "docs" commit), no other consultant caught it. CC should spot-check the 2-3 largest MERGE commits before final merge.
4. **`b2b4fb5` itself is excluded from this brief** (per scope fence) — its disposition is the Stream A R1 repair.

## Archived to

- This synthesis
- `docs/decisions/2026-04-23-cleanup-baseline.md` (which discusses `codex/safe-merge-b1-truth-recovery` as the preserved branch)
- Gemini-04 response with full 17-row table
