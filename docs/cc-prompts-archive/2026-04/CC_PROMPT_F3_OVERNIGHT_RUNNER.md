# F3 Overnight Autonomous Runner — Cycles 1-5

> Single mega-prompt. CC runs all 5 cycles autonomously overnight.
> Architect ASLEEP throughout. Morning review of everything at once.
> Spec at CC_PROMPT_F3_ANALYTICS_WIRING.md is authoritative.

---

## 0. Operating posture

**Architect is asleep.** No mid-night chat replies. CC makes all
tactical decisions per the rules below. Strategic decisions defer
to morning by writing to handoff and continuing what CAN be done.

**No quota anxiety.** Burn audits freely. Run as many Codex+Gemini
cycles per implementation cycle as Opus judges necessary to converge
on PASS. There is no audit budget.

**Time budget:** night (~6-9 hours). If Cycle N runs over 4 hours,
CC writes incomplete handoff and moves to Cycle N+1 instead of
camping forever.

---

## 1. Cycle merge policy (Q1 = Hybrid C)

**Cycle 1 (foundation):**
- If both verifiers PASS after fix iterations → CC merges to master
  autonomously. Subsequent cycles branch from updated master.
- If verifiers don't converge → CC does NOT merge, leaves branch,
  flags in summary handoff. Cycles 2-4 branch from PRE-Cycle-1 master.

**Cycles 2-4 (independent widgets):**
- Each branches from current master at start of its cycle (so if
  Cycle 1 merged, they get the lazy-replay foundation; if not,
  they don't).
- Each cycle's branch is INDEPENDENT — Cycle 2-4 do NOT depend on
  each other.
- DO NOT merge Cycles 2-4 autonomously. Architect reviews in morning.

**Cycle 5 (integration):**
- Branches from current master at end of night (whatever was merged).
- CHANGELOG + W4 placeholder text + roadmap update.
- DO NOT merge autonomously. Architect reviews.

---

## 2. Per-cycle fix-up loop (Q3 = unlimited convergence then stop)

After implementation + tests + initial audit:

```
loop:
    dispatch Codex + Gemini in parallel
    wait for both responses
    if both PASS / COHERENT with no findings:
        break  # cycle complete
    if either has CRITICAL or HIGH findings:
        apply fixes
        re-test (full pytest scope)
        if test regression: STOP cycle, write incomplete handoff
    if all remaining findings are LOW or DEFERRED-judgment:
        break  # acceptable
    if loop iteration count > 5:
        STOP cycle, write incomplete handoff explaining lack of convergence
        proceed to next cycle
    iterate
```

CC's judgment on "what's the right call" defers to morning when
ambiguous: write findings into handoff, mark "ARCHITECT DECISION
NEEDED", continue.

---

## 3. Per-cycle structure (template applied 5 times)

For each cycle N:

1. **Setup:** branch from appropriate base per §1 policy
2. **Recon (§14.1):** read spec section, grep existing patterns,
   verify spec assumptions
3. **Implement** per spec section
4. **Test scoped** then **test full suite**
5. **Commit on branch** (don't merge)
6. **Push branch to origin**
7. **Dispatch Codex + Gemini parallel** per §6 audit prompts below
8. **Wait** (simple timeout pattern, not stability counter)
9. **Read responses**, classify findings
10. **Fix-up loop** per §2
11. **Per-cycle handoff** at
    `artifacts/handoffs/2026-04-29-f3-cycleN-handoff.md`
12. **Conditional merge** (Cycle 1 only, per §1 policy)
13. **Move to next cycle** — DO NOT wait for architect

---

## 4. Audit prompts (template per cycle)

For each cycle, use these prompt templates with cycle-specific
substitutions in {curly_braces}.

### 4.1 Codex prompt template

Write to:
`artifacts/consultations/2026-04-29-f3-cycleN/codex-audit-iterM.prompt.md`
(M = audit iteration, starts at 1)

```markdown
Model: gpt-5.5
Reasoning effort: high

# F3 Cycle {N} ({cycle_name}) audit — Codex literal verifier
{audit iteration M}

## Mission
Verify factual correctness of branch feat/f3-cycleN-{slug}
against spec CC_PROMPT_F3_ANALYTICS_WIRING.md §{section}.

## What to verify

{cycle-specific A/B/C/D checks per spec acceptance criteria}

## Specifically check (this iteration)

{if iter > 1: list of findings from previous iter that should now
be fixed; verify each one is gone or correctly addressed}

## Severity scale
- CRITICAL: spec violation, runtime error, broken contract
- HIGH: missing test for stated behavior, doc-vs-code drift
- MEDIUM: redundant code, suboptimal patterns
- LOW: style, naming, comments

## Output
Per finding: severity / file:line / what's wrong / suggested fix.
Final verdict: PASS / CONDITIONAL / FAIL.
Hard cap: 2500 words. Table-first. NO skill-loading prelude.

## Response file
artifacts/consultations/2026-04-29-f3-cycleN/codex-audit-iterM.response.md
```

### 4.2 Gemini prompt template

Write to:
`artifacts/consultations/2026-04-29-f3-cycleN/gemini-audit-iterM.prompt.md`

```markdown
Model: gemini-3.1-pro-preview

# F3 Cycle {N} ({cycle_name}) audit — Gemini structural
{audit iteration M}

## Mission
Wide-context structural audit. Find caller-impact, doc-vs-code
drift, lifecycle gaps, integration issues Codex's narrow scope
misses.

## Read scope
- Branch diff: feat/f3-cycleN-{slug} vs base (master OR
  feat/f3-cycle1-lazy-replay if Cycle 1 didn't merge)
- Spec section §{N}
- {cycle-specific grep patterns for caller impact}

## What to flag
- DRIFT, INCONSISTENT, GAP, CALLER-IMPACT, LIFECYCLE-GAP,
  DEAD-END

## What NOT to flag
- Per-line nits (Codex covers)
- Pre-existing scope items (ROADMAP backlog)
- Out-of-scope items per spec §2

## Output
Single markdown table:
| # | Type | Files | Issue | Suggested fix |

After table: 5 sentences max. Verdict:
COHERENT / GAPS / DRIFT / CALLER-IMPACT.

Hard cap: 1500 words. Table-first.

## Response file
artifacts/consultations/2026-04-29-f3-cycleN/gemini-audit-iterM.response.md
```

### 4.3 Dispatch commands (template)

```bash
mkdir -p ~/Projects/cryodaq/artifacts/consultations/2026-04-29-f3-cycleN

nohup codex exec -m gpt-5.5 -c model_reasoning_effort="high" \
  --sandbox read-only --skip-git-repo-check \
  --cd ~/Projects/cryodaq \
  < ~/Projects/cryodaq/artifacts/consultations/2026-04-29-f3-cycleN/codex-audit-iterM.prompt.md \
  > ~/Projects/cryodaq/artifacts/consultations/2026-04-29-f3-cycleN/codex-audit-iterM.response.md 2>&1 &
echo "Codex PID: $!"

nohup gemini -m gemini-3.1-pro-preview --yolo \
  -p "$(cat ~/Projects/cryodaq/artifacts/consultations/2026-04-29-f3-cycleN/gemini-audit-iterM.prompt.md)" \
  > ~/Projects/cryodaq/artifacts/consultations/2026-04-29-f3-cycleN/gemini-audit-iterM.response.md 2>&1 &
echo "Gemini PID: $!"
```

### 4.4 Wait pattern (use this, NOT stability counter)

```bash
for i in $(seq 1 12); do
  sleep 60
  CODEX_RUN=$(pgrep -f "codex exec" > /dev/null && echo "yes" || echo "no")
  GEMINI_RUN=$(pgrep -f "gemini -m gemini" > /dev/null && echo "yes" || echo "no")
  echo "minute $i: codex=$CODEX_RUN gemini=$GEMINI_RUN"
  if [ "$CODEX_RUN" = "no" ] && [ "$GEMINI_RUN" = "no" ]; then
    echo "Both finished at minute $i"
    break
  fi
done
```

12-min cap; if either still running, kill and proceed with partial.

---

## 5. Cycle-by-cycle scope

### Cycle 1 — F4 lazy-open snapshot replay (foundation)

- **Branch:** `feat/f3-cycle1-lazy-replay`
- **Base:** master (current HEAD pre-batch)
- **Spec section:** §4.5
- **Audit focus:**
  - Codex: 7 setters extended, set_fault NOT replayed, cache
    lifecycle, memory discipline
  - Gemini: caller-impact in MainWindowV2 hot path, replay pattern
    consistency with existing set_experiment cache
- **Merge rule:** if both PASS → CC merges to master autonomously
- **Slug for paths:** `cycle1-lazy-replay`

### Cycle 2 — W1 temperature_trajectory

- **Branch:** `feat/f3-cycle2-temperature-trajectory`
- **Base:** current master (Cycle 1 if merged, else pre-batch master)
- **Spec section:** §4.1
- **Audit focus:**
  - Codex: pyqtgraph plot construction, channel grouping, snapshot
    replay integration, live append behavior
  - Gemini: time window correctness, AnalyticsView setter delegation,
    pre-existing test compat
- **Merge rule:** DO NOT merge — architect reviews in morning
- **Slug:** `cycle2-temperature-trajectory`

### Cycle 3 — W2 cooldown_history + new engine command

- **Branch:** `feat/f3-cycle3-cooldown-history`
- **Base:** current master
- **Spec section:** §4.2 + §5
- **Audit focus:**
  - Codex: engine action handler dispatch, request/response schema
    matches §5.2, error response format
  - Gemini: SQLite query semantically captures "cooldown completed"
    (not aborted), WAL safety, test coverage of edge cases
    (empty result, error response)
- **Merge rule:** DO NOT merge
- **Slug:** `cycle3-cooldown-history`

### Cycle 4 — W3 experiment_summary

- **Branch:** `feat/f3-cycle4-experiment-summary`
- **Base:** current master
- **Spec section:** §4.3
- **Pre-cycle decision:** does `get_alarm_history` engine command
  exist already?

  ```bash
  grep -n "get_alarm_history\|alarm_history_get" src/cryodaq/engine.py
  ```

  - If YES: use existing command
  - If NO: add minimal one (~30 LOC engine) within this cycle.
    Document in commit message.

- **Audit focus:**
  - Codex: all sections populated (header/duration/min-max/alarms/
    artifacts), QDesktopServices wiring, empty state
  - Gemini: missing artifact graceful handling (no Parquet file),
    alarm count logic edge cases, integration with experiment FSM
    state
- **Merge rule:** DO NOT merge
- **Slug:** `cycle4-experiment-summary`

### Cycle 5 — Integration audit + W4 polish + docs

- **Branch:** `feat/f3-cycle5-integration`
- **Base:** current master AT END OF NIGHT (whatever's there)
- **Spec section:** §4.4 (W4 docstring update only) + §10 docs +
  CHANGELOG entry
- **Audit focus:**
  - Codex: docs match implemented state, W4 placeholder text
    accurate, CHANGELOG entry covers all merged cycles correctly
  - Gemini: full F3 narrative coherent, ROADMAP/CHANGELOG/F3
    spec consistency, no orphaned references
- **Merge rule:** DO NOT merge
- **Slug:** `cycle5-integration`

---

## 6. Per-cycle handoff template

Each cycle's handoff (`artifacts/handoffs/2026-04-29-f3-cycleN-handoff.md`):

```markdown
# F3 Cycle N ({cycle_name}) — architect review

## Status
{COMPLETE-PASSED / COMPLETE-FINDINGS / INCOMPLETE-STOPPED / INCOMPLETE-DEFERRED}

## Branch
feat/f3-cycleN-{slug} at {SHA}
Pushed: yes/no
Merged: yes/no (Cycle 1 only, per §1 policy)

## Tests
{pass}/{total} green at final commit
Pre-existing tests: regression count = N
Failing tests: list if any

## Audit history
| Iteration | Codex verdict | Codex findings | Gemini verdict | Gemini findings | Action |
|---|---|---|---|---|---|
| 1 | ... | ... | ... | ... | applied N fixes |
| 2 | ... | ... | ... | ... | converged / iterated |
| ... |

## Final findings (any unfixed)
| # | Severity | Source | Issue | Why unfixed |
|---|---|---|---|---|

## Spec deviations
- None / list specific deviations with rationale

## Architect decisions needed (morning)
1. {specific question if any}
2. {ambiguity that paused convergence}

## Files changed
{list with line counts}

## Commits on branch
{SHA list with subjects}
```

---

## 7. Master summary handoff (END OF NIGHT)

After all 5 cycles done (or stopped), CC writes:
`artifacts/handoffs/2026-04-29-f3-OVERNIGHT-summary.md`

```markdown
# F3 Overnight Run — Master Summary

## Start state
Master HEAD pre-batch: {SHA}
Time started: {timestamp}

## End state
Master HEAD: {SHA}
Cycle 1 merged to master: yes/no
Time ended: {timestamp}
Wall clock: {duration}

## Cycle results
| Cycle | Branch | Status | Audit iters | Final verdict | Merged |
|---|---|---|---|---|---|
| 1 | feat/f3-cycle1-lazy-replay | ... | N | ... | yes/no |
| 2 | feat/f3-cycle2-temperature-trajectory | ... | N | ... | no |
| 3 | feat/f3-cycle3-cooldown-history | ... | N | ... | no |
| 4 | feat/f3-cycle4-experiment-summary | ... | N | ... | no |
| 5 | feat/f3-cycle5-integration | ... | N | ... | no |

## Total work
- Audits dispatched: {count}
- Code commits across all branches: {count}
- LOC added: {count}
- LOC tests added: {count}
- Files touched: {count}

## Architect morning queue (priority order)
1. Review Cycle 1 merge decision (if applicable)
2. Review Cycle 2 handoff
3. Review Cycle 3 handoff
4. Review Cycle 4 handoff
5. Review Cycle 5 handoff (integration)
6. Decide merge order for Cycles 2-5

## Outstanding architect decisions
{aggregate from per-cycle handoffs}

## CC's overall confidence
{HIGH / MEDIUM / LOW per cycle}

## Overnight bugs / surprises
{anything CC encountered that didn't fit into a cycle}

## Recommendations for tomorrow
{merge order, fix priorities, what to defer}
```

---

## 8. Hard stops (whole-night-level)

Most stops are per-cycle (write handoff, move on). These STOP THE
ENTIRE NIGHT:

- **Master HEAD discovered to be different from expected at start** —
  unexpected commits since Phase 0 of THIS prompt. STOP, write
  summary explaining drift.
- **Test infrastructure broken** (pytest can't run at all on master)
  — STOP.
- **Disk full / OOM / system instability** — STOP, write what you
  can to handoff.
- **Codex AND Gemini both fail dispatch on Cycle 1** (both response
  files < 200 bytes after wait) — environment issue, STOP.
- **Working tree corruption** (git status shows unexpected state
  CC didn't introduce) — STOP, write summary.

A single failed cycle does NOT stop the night. Move to next cycle.

---

## 9. Architect comm-out discipline

CC will NOT see chat messages from architect during the night.
Architect responses are NOT possible.

CC writes handoffs to disk. Morning architect reads handoffs.

If CC encounters something it WOULD ask architect about: write the
question explicitly into the cycle handoff under "Architect
decisions needed", apply the safest possible interpretation, mark
the deviation in the handoff, continue.

Examples of "safest interpretation":
- Ambiguous spec → defer to existing pattern in code
- Two acceptable test designs → pick the one with simpler fixtures
- Cycle 4 alarm command absent → add it (per spec recommendation)
- Audit finding ambiguity → if HIGH, fix; if MEDIUM, judgment call;
  if LOW, leave + document

---

## 10. Push policy

EVERY cycle pushes its branch. Even if cycle is INCOMPLETE-STOPPED
— push what you have so architect can review.

Do NOT push:
- Master commits except Cycle 1 merge per §1 policy
- Branches deleted before night ends (don't delete branches at all
  this batch)

---

## 11. Vault

Do NOT touch vault during the night. Vault sync is a morning
architect-driven task.

---

## 12. Final report at end of night

Write summary handoff (§7).

Then in shell:

```
echo "═══════════════════════════════════════"
echo "F3 OVERNIGHT RUN COMPLETE"
echo "═══════════════════════════════════════"
echo "Master HEAD: $(git log -1 --format='%h %s' master)"
echo "Branches:"
git branch -av | grep -E "f3-cycle[1-5]"
echo "Handoffs:"
ls artifacts/handoffs/2026-04-29-f3-*
echo "═══════════════════════════════════════"
echo "Architect: read artifacts/handoffs/2026-04-29-f3-OVERNIGHT-summary.md first"
```

This is the wake-up display.

---

## 13. Begin

Start NOW. Cycle 1 first. Reference spec
CC_PROMPT_F3_ANALYTICS_WIRING.md throughout. Use ORCHESTRATION
v1.2 §10 + §14 verification practices at every cycle's start.

GO.
