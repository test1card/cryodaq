# Overnight Runner 2026-04-29 (night)

> Single mega-prompt. Sonnet executes 4 phases sequentially overnight.
> Architect ASLEEP. Morning review of everything at once.

---

## 0. Operating posture

- **Architect is asleep.** No mid-night chat. Sonnet makes tactical 
  decisions per rules below; strategic ambiguities go to handoff with 
  "ARCHITECT DECISION NEEDED" marker.
- **No quota anxiety.** Burn audits freely. Re-audit until convergence 
  per cycle.
- **Time budget:** ~6-9 hours total across all 4 phases.
- **Sonnet model.** Pre-existing F3 ran on Sonnet successfully across 
  5 cycles. Continue with same model. If Sonnet's CC session is on 
  Opus by default, no change needed — model selection is automatic 
  per CC config.
- **Architect is web-Claude Opus 4.7.** Not active during the night.

---

## 1. Phase order (strict sequential)

1. **Phase A** (~20 min): Vault sync v0.40.0 closure — refreshes 
   `Versions.md`, `Analytics view.md`, F4 lazy-replay note. Cheap, 
   completes F3 release loop.
2. **Phase B** (~3-4h): F10 sensor diagnostics → alarm integration. 
   3 cycles per spec.
3. **Phase C** (~2h): 4 architectural vault notes (subsystem quartet).
4. **Phase D** (~30 min): Final consolidation handoff + version bump 
   if F10 shipped + push.

If Phase B stuck, skip to Phase C anyway. Vault notes are independent.
If Phase A surprisingly fails (rare), STOP — vault is too important 
to corrupt blindly.

---

## 2. Phase A — Vault sync v0.40.0

**Spec inline (no separate doc).**

### A.1 Recon
- Verify clean master at expected HEAD (post-v0.40.0 tag, which was 
  983bc93 or later).
- Read current state of `~/Vault/CryoDAQ/60 Roadmap/Versions.md`.

### A.2 Updates
- Add row for v0.40.0:
  - Version: v0.40.0
  - Date: 2026-04-29
  - Status: ✅ released
  - Scope summary: F3 Analytics widgets data wiring (W1-W3 + F4 lazy 
    replay); 86 new tests; new engine command `cooldown_history_get`; 
    audit-caught experiment_id key fix
  - Closing commit: <SHA from Phase 0 recon>

- Update `~/Vault/CryoDAQ/10 Subsystems/Analytics view.md`:
  - Reflect F3 wiring landed
  - Cross-link new widgets (temperature_trajectory, cooldown_history, 
    experiment_summary)
  - Note W4 still placeholder pending F8
  - Reference F4 lazy-open replay
  - Update `last_synced: 2026-04-29`

- Create new `~/Vault/CryoDAQ/10 Subsystems/F4 lazy replay.md`:
  - Brief note (~50 lines) on shell-level snapshot cache
  - Replay mechanism on AnalyticsView construction / phase swap
  - List of replayed setters (set_cooldown, set_temperature_readings, 
    set_pressure_reading, set_keithley_readings, set_instrument_health, 
    set_vacuum_prediction, set_experiment_status)
  - set_fault excluded reason
  - Cross-link to Analytics view + Main window v2

### A.3 Source map + build log
- Run `python3 ~/Projects/cryodaq/artifacts/vault-build/build_source_map.py`
- Verify 0 broken wikilinks
- Append build log entry

### A.4 No repo touch
This phase is vault-only. Repo state untouched.

---

## 3. Phase B — F10 (3-4 cycles)

**Spec:** `CC_PROMPT_F10_SENSOR_DIAGNOSTICS_ALARM.md` (read in full first).

### B.1 Per-cycle template (3 cycles per F10 spec §6)

For each cycle N:

1. **Setup:** branch `feat/f10-cycleN-<slug>` from current master
2. **Recon (§14.1):** read spec section, grep existing patterns
3. **Implement** per spec section
4. **Test scoped** then **test full suite**
5. **Commit on branch**, push to origin
6. **Dispatch Codex + Gemini parallel** (audit prompt template §B.2)
7. **Wait** (simple timeout pattern §B.3)
8. **Read responses, classify findings**
9. **Fix-up loop** until both PASS or 5 iterations exhausted
10. **Per-cycle handoff** at 
    `artifacts/handoffs/2026-04-29-f10-cycleN-handoff.md`
11. **Conditional auto-merge:**
    - Cycles 1 + 2: auto-merge if dual PASS
    - Cycle 3: STOP for architect (integration risk)
12. **Move to next cycle**

### B.2 Audit prompt templates

#### Codex template (per cycle)

Path: `artifacts/consultations/2026-04-29-f10-cycleN/codex-iterM.prompt.md`

```markdown
Model: gpt-5.5
Reasoning effort: high

# F10 Cycle N audit — Codex literal verifier (iter M)

## Mission
Verify branch feat/f10-cycleN-<slug> against spec 
CC_PROMPT_F10_SENSOR_DIAGNOSTICS_ALARM.md §<section>.

## Verify
{cycle-specific checks per spec §6}

## Iteration {M} previous findings
{If iter > 1: list previous findings, verify each fixed}

## Severity scale
CRITICAL / HIGH / MEDIUM / LOW per usual.

## Output
Per finding: severity / file:line / what's wrong / suggested fix.
Verdict: PASS / CONDITIONAL / FAIL.
2500 words cap. Table-first. NO skill-loading prelude.

## Response
artifacts/consultations/2026-04-29-f10-cycleN/codex-iterM.response.md
```

#### Gemini template (per cycle)

Path: `artifacts/consultations/2026-04-29-f10-cycleN/gemini-iterM.prompt.md`

```markdown
Model: gemini-3.1-pro-preview

# F10 Cycle N audit — Gemini structural (iter M)

## Mission
Wide-context audit of feat/f10-cycleN-<slug>. Find caller-impact, 
DRIFT, INCONSISTENT, GAP, LIFECYCLE-GAP that Codex misses.

## Read
- Branch diff vs base
- Spec §<section>
- Caller-impact greps for affected APIs

## Output
Single markdown table:
| # | Type | Files | Issue | Suggested fix |

After table: 5 sentences. Verdict: COHERENT / GAPS / DRIFT / 
CALLER-IMPACT.

1500 words cap. Table-first.

## Response
artifacts/consultations/2026-04-29-f10-cycleN/gemini-iterM.response.md
```

### B.3 Dispatch + wait pattern

```bash
mkdir -p ~/Projects/cryodaq/artifacts/consultations/2026-04-29-f10-cycleN

nohup codex exec -m gpt-5.5 -c model_reasoning_effort="high" \
  --sandbox read-only --skip-git-repo-check \
  --cd ~/Projects/cryodaq \
  < ~/Projects/cryodaq/artifacts/consultations/2026-04-29-f10-cycleN/codex-iterM.prompt.md \
  > ~/Projects/cryodaq/artifacts/consultations/2026-04-29-f10-cycleN/codex-iterM.response.md 2>&1 &

nohup gemini -m gemini-3.1-pro-preview --yolo \
  -p "$(cat ~/Projects/cryodaq/artifacts/consultations/2026-04-29-f10-cycleN/gemini-iterM.prompt.md)" \
  > ~/Projects/cryodaq/artifacts/consultations/2026-04-29-f10-cycleN/gemini-iterM.response.md 2>&1 &

# Wait — simple pgrep poll, NOT stability counter
for i in $(seq 1 12); do
  sleep 60
  CR=$(pgrep -f "codex exec" > /dev/null && echo "yes" || echo "no")
  GR=$(pgrep -f "gemini -m gemini" > /dev/null && echo "yes" || echo "no")
  echo "minute $i: codex=$CR gemini=$GR"
  if [ "$CR" = "no" ] && [ "$GR" = "no" ]; then
    echo "Both finished at minute $i"
    break
  fi
done
```

If 12 min cap hit: kill, work with partial.

### B.4 Convergence rule per cycle

```
audit iteration M:
    if both PASS / COHERENT, no findings: BREAK (cycle complete)
    if CRITICAL or HIGH findings: 
        apply fixes
        re-test full suite
        if regression: STOP cycle, write incomplete handoff
        next iter (M+1)
    if all remaining findings MEDIUM/LOW: 
        BREAK (acceptable)
    if iter > 5: STOP cycle, "no convergence after 5 iter"
```

### B.5 Per-cycle handoff schema

```markdown
# F10 Cycle N — architect review

## Status
{COMPLETE-PASSED / COMPLETE-FINDINGS / INCOMPLETE-STOPPED / INCOMPLETE-DEFERRED}

## Branch
feat/f10-cycleN-<slug> at <SHA>
Pushed: yes
Merged: yes/no

## Tests
<pass>/<total> green at final commit
Pre-existing regressions: <count>

## Audit history
| Iter | Codex | Codex# | Gemini | Gemini# | Action |
|---|---|---|---|---|---|

## Final unfixed findings
| # | Severity | Source | Issue | Why unfixed |

## Spec deviations
- None / list with rationale

## Architect decisions needed (morning)
- ...

## Files changed + commits
```

---

## 4. Phase C — Vault subsystem quartet

**Spec:** `CC_PROMPT_VAULT_SUBSYSTEM_QUARTET.md`.

### C.1 Sequential 4 notes
Per spec §5: Web dashboard → Cooldown predictor → Experiment manager → 
Interlock engine. Sequential, not parallel.

### C.2 Per note flow
- Read source files (don't dump everything into thinking buffer)
- Synthesize per template §1
- Write via Obsidian MCP
- Move to next

### C.3 No audit
Vault hygiene. No Codex/Gemini per note. Architect reviews in morning.

### C.4 Post-quartet
- Run source map regen
- Verify 0 broken wikilinks
- Append build log entry: 4 notes added, total = 75
- Vault state confirmed

---

## 5. Phase D — Final consolidation

### D.1 Master summary handoff

Write `artifacts/handoffs/2026-04-29-overnight-summary.md`:

```markdown
# Overnight Run 2026-04-29 — Master Summary

## Phases executed
| Phase | Status | Duration | Outputs |
|---|---|---|---|
| A | ... | ... | Versions.md updated, F4 note created, etc |
| B | ... | ... | F10 cycles 1-3 |
| C | ... | ... | 4 vault notes |
| D | ... | ... | This summary |

## Master HEAD
Pre-night: <SHA>
Post-night: <SHA>

## Branches awaiting review
| Branch | Status |
|---|---|
| feat/f10-cycle3-integration | awaiting (Cycle 3 not auto-merged per spec) |

## Cycles auto-merged
- F10 Cycle 1 (if dual PASS)
- F10 Cycle 2 (if dual PASS)

## Total work
- Audits dispatched: <count>
- Code commits: <count>
- LOC: +<X> / -<Y>
- New tests: <count>
- Vault notes: <count>

## Architect morning queue
1. Review F10 Cycle 3 handoff (if any)
2. Decide on tag bump (v0.41.0 if F10 done?)
3. Review 4 vault subsystem notes for accuracy
4. Address ARCHITECT DECISION NEEDED markers from any phase

## Outstanding
- F19 (deferred F3 polish) — still ⬜
- Lab Ubuntu PC verification of v0.39.0 H5 fix
- GUI .cof minor wiring
```

### D.2 Conditional version bump

If F10 successfully merged (Cycles 1+2 auto-merged + Cycle 3 ready):

DO NOT auto-bump. Architect decides in morning whether to tag.

If F10 partially shipped (Cycles 1+2 only, Cycle 3 awaiting): leave 
`pyproject.toml` at 0.40.0. Note partial state in summary.

### D.3 Wake-up echo

```bash
echo "═══════════════════════════════════════"
echo "OVERNIGHT RUN COMPLETE 2026-04-29"
echo "═══════════════════════════════════════"
echo "Phases A B C D outcomes — read summary handoff"
echo "Master HEAD: $(git log -1 --format='%h %s' master)"
echo "Branches:"
git branch -av | grep "f10-cycle"
echo "Vault notes added:"
ls ~/Vault/CryoDAQ/10\ Subsystems/ | tail -5
echo "Handoffs:"
ls artifacts/handoffs/2026-04-29-* | head -10
echo "═══════════════════════════════════════"
echo "Architect: read artifacts/handoffs/2026-04-29-overnight-summary.md first"
```

---

## 6. Hard stops (whole-night-level)

These STOP THE ENTIRE NIGHT (write summary explaining and quit):

- Master HEAD different from expected at start (drift)
- Test infrastructure broken on master baseline
- Disk full / OOM
- Phase A vault corruption (Obsidian MCP mid-write failure)
- Both Codex AND Gemini fail dispatch on Cycle 1 of Phase B 
  (environment issue)
- Working tree corruption CC didn't introduce

A single failed cycle does NOT stop the night. Move to next phase.

---

## 7. Architect comm-out discipline

Sonnet will NOT see chat. Write everything to handoffs.

When unsure about a decision:
- Apply safest interpretation
- Document in handoff under "ARCHITECT DECISION NEEDED"  
- Continue

Examples of "safest":
- Spec ambiguous → defer to existing pattern in code
- Two acceptable test designs → simpler fixtures wins
- Audit MEDIUM finding ambiguous → leave + document

---

## 8. Begin

Phase A first. Read both spec files, then GO.

```
1. CC_PROMPT_F10_SENSOR_DIAGNOSTICS_ALARM.md (Phase B spec)
2. CC_PROMPT_VAULT_SUBSYSTEM_QUARTET.md (Phase C spec)
```

---

*Architect: Vladimir Fomenko + Claude Opus 4.7 (web).*  
*Sonnet executes overnight per ORCHESTRATION v1.2.*  
*F3 last night was Sonnet — same model, same approach.*
