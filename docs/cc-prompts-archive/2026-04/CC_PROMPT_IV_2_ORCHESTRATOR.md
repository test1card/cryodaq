# IV.2 — Overnight batch orchestrator (runs after IV.1 closes)

**DO NOT START UNTIL IV.1 IS CLOSED.** Check `git log --oneline -10` 
and verify IV.1's five commits are pushed with Codex PASS on each. 
If IV.1 is incomplete or has STOPs — do NOT proceed, report and 
wait for architect.

**Target HEAD at start:** IV.1 final SHA (unknown at orchestrator 
authoring time).

**Scope:** Six findings from three restored spec files. Single 
overnight run. /codex after each commit per playbook.

---

## ❗ Critical rules

### Rule 1 — `/codex` is a slash command
Just type it. Do NOT search `~/.claude/commands/` or grep plugin 
directory. If unknown-command error: defer review, push commit, 
move on. Never spend time debugging the plugin.

### Rule 2 — NO file deletion, ever
Architect policy. Claude never deletes files in this repo — not 
manually, not via CC, not via codex, not in Stage Cleanup. All 
spec files stay on disk. If you see any `rm CC_PROMPT_*.md` or 
`rm <anything>` instruction in a spec — **SKIP IT**. This is a 
hard rule, overrides everything else in specs.

### Rule 3 — Model override in BOTH places
`--model gpt-5.4 --reasoning high` inline AND `Model: gpt-5.4` / 
`Reasoning effort: high` as first two lines of prompt body.  
Belt + suspenders. If response says o3, retry once; still o3 → 
DEFER, push, move on.

### Rule 4 — Autonomy mode
Per `docs/CODEX_SELF_REVIEW_PLAYBOOK.md`. Max 3 amend cycles per 
commit. STOP conditions: architectural fork, design-decision FAIL, 
3-cycle exhaust, out-of-scope Codex requirement, pre-commit fail 
in untouched code, plugin failure.

### Rule 5 — HMI philosophy
Cognitive load is NOT a constraint. Lab HMI, not consumer app. 
Keep dense data, explicit numbers, visible metrics. Do NOT 
simplify layouts beyond what spec explicitly requires.

### Rule 6 — Targeted tests only
Per-commit targeted tests, not full pytest. Shell subtree sanity 
run is acceptable at orchestrator end.

---

## Spec file references

Three spec files on disk contain findings. Each marked «SPEC 
RESTORED FROM MEMORY» — verify each finding still reproduces 
before fixing (some may have been resolved by intermediate 
commits).

- `CC_PROMPT_III_E_UX_HOTFIXES.md` — Findings A.1 (conductivity 
  stability header), A.2 (alarm ACK K1), A.3 (Keithley global 
  time window).
- `CC_PROMPT_III_E_EXPERIMENT_FIXES.md` — Findings B.1 (experiment 
  overlay landing), B.2 (phase pills STATUS_OK), B.3 (DS gap: 
  internal versioning + empty-state rules).
- `CC_PROMPT_III_F_DS_GAP_FIX.md` — **MERGE NOTE:** content 
  overlaps with B.3 above. This orchestrator treats B.3 as the 
  canonical location. C spec stays on disk as reference. Do NOT 
  execute C separately; it's absorbed into B.3.

---

## Stage 0 — Global preflight (once, before any commits)

Before starting any finding, run this global preflight:

### 0.1 — Verify IV.1 closed cleanly

```bash
cd /Users/vladimir/Projects/cryodaq
git log --oneline -15
git status --short
```

Expected:
- IV.1 final SHA is HEAD and matches origin/master
- Working tree clean (no uncommitted changes EXCEPT perhaps 
  `config/channels.yaml` which is architect's pre-existing local 
  edit, out of scope)
- Five IV.1 commits visible in history

If any of these fail — STOP with report «IV.1 not closed 
cleanly, cannot start IV.2».

### 0.2 — Runtime re-verification of findings

The three spec files were restored from memory after accidental 
overwrite. Findings may have been resolved by IV.1 amends or 
earlier commits. Re-verify each finding is still reproducible 
before starting its fix.

For each of the 6 findings below, grep or inspect the relevant 
file and confirm the symptom exists:

```bash
# A.1 — Conductivity stability header empty state
grep -A 5 "Стабильность\|stability" \
  src/cryodaq/gui/shell/overlays/conductivity_panel.py | head -30

# A.2 — Alarm ACK removal
grep -A 15 "alarm_v2_ack\|_on_ack" \
  src/cryodaq/gui/shell/overlays/alarm_panel.py | head -40

# A.3 — Keithley local time window  
grep -B 2 -A 10 "_WINDOW_OPTIONS\|window_btn\|\"10м\"\|'10м'" \
  src/cryodaq/gui/shell/overlays/keithley_panel.py | head -40

# B.1 — Experiment overlay no-experiment branch
grep -B 2 -A 10 "_experiment is None\|no active experiment\|нет активного" \
  src/cryodaq/gui/shell/experiment_overlay.py | head -40

# B.2 — Phase pills STATUS_OK usage
grep -B 1 -A 3 "STATUS_OK\|current_phase" \
  src/cryodaq/gui/dashboard/phase_stepper.py 2>/dev/null | head -30

# B.3 — v1/v2 in alarm panel labels
grep -B 1 -A 3 "(v1)\|(v2)\|Физические тревоги\|Текущие тревоги" \
  src/cryodaq/gui/shell/overlays/alarm_panel.py | head -20
```

Categorize each finding:
- **CONFIRMED** — symptom reproduces, proceed with fix
- **RESOLVED** — already fixed, skip; note in final report
- **CHANGED** — partially fixed or different shape now, update 
  spec inline before executing

Report categorization before starting fixes. Proceed without 
stopping — this is informational.

---

## Execution order

Recommended order maximizes safety (K1 fixes early) and leverages 
dependencies (DS rules before DS-compliant code):

| # | Finding | Source | Severity | Est LOC | Depends on |
|---|---|---|---|---|---|
| 1 | A.1 Conductivity stability header placeholder | IV.2.A | LOW | ~80 | — |
| 2 | A.2 Alarm ACK removal | IV.2.A | **K1** | ~150 | engine API |
| 3 | B.3 DS rules (content-voice + surface) | IV.2.B + IV.2.C | MED | ~100 docs + test | — |
| 4 | B.2 Phase pills ACCENT migration | IV.2.B | MED | ~50 | #3 DS rules |
| 5 | B.1 Experiment overlay landing state | IV.2.B | MED | ~300 | #3 empty-state rule |
| 6 | A.3 Keithley global time window | IV.2.A | MED | ~120 | IV.1 Finding 4 |

Each finding = one commit. /codex review after each.

---

## Per-commit workflow

For each finding in order:

1. **Stage 0 recon** (2-5 min) — read target file, confirm bug 
   reproduces, plan approach.
2. **Stage 1-N** — implement per spec instructions in the 
   referenced file.
3. **Pre-commit gates:**
   - `ruff check src tests` clean
   - `ruff format` new/modified files
   - Forbidden-token grep (DS v1.0.1 compliance)
   - Emoji scan (U+1F300-U+1FAFF, U+2600-U+27BF, ✓)
   - Targeted tests pass
4. **Commit** with descriptive message.
5. **Push** `origin master`.
6. **/codex review** with focus questions tailored to the 
   commit. 10-min cap per review.
7. Handle verdict:
   - PASS → next finding
   - CRITICAL/HIGH/small-scope MEDIUM → autonomous amend, re-
     review (max 3 cycles)
   - Design-decision FAIL → STOP this commit, document reason, 
     move to next
   - 3-cycle exhaust → STOP, next

### A.2 alarm ACK specific risk

If Stage 0 diagnosis shows the root cause is **engine-side** 
(Diagnosis A or B from IV.2.A spec — handler stub or bad reply 
shape) — STOP this commit, report «A.2 requires engine change, 
out of scope», move to next. Engine-side changes are NOT in 
IV.2 scope; architect decides separately.

### B.3 DS rule writing specific approach

Rule-first approach: write DS rule text in 
`docs/design-system/rules/content-voice-rules.md` and 
`docs/design-system/rules/surface-rules.md` BEFORE touching any 
code. Commit the rules additions separately IF it's easier for 
Codex to review, OR combine with first DS-compliant code fix 
(phase pills #4) if small enough.

Recommendation: commit #3 is **rules only** (docs + test for CI 
enforcement grep). Commits #4 and #5 apply the rules.

### B.2 phase pills specific

Grep BEFORE touching:
```bash
find src/cryodaq/gui -name "phase_stepper*"
grep -rn "phase_stepper\|PhaseStepper" src/cryodaq/gui/
```

Phase pills may live in dashboard, experiment overlay, or both. 
Apply DS fix to ALL locations. Check docs/design-system for 
existing phase-pill primitive spec; create one if missing.

### B.1 experiment overlay landing specific

This is the largest commit (~300 LOC). QStackedWidget with 
landing state + mid-experiment state. Reuse existing 
`NewExperimentDialog` via whatever signal/slot path already 
exists (grep for `experiment_create_requested`). Do NOT invent 
new creation flow.

### A.3 Keithley global window specific

Depends on IV.1 Finding 4 (Keithley two-row layout). If IV.1 
Finding 4 lives in the same file — inspect current state after 
IV.1, don't assume structure.

Remove `_WINDOW_OPTIONS` local constant. Migrate to 
`TimeWindowSelector` from `src/cryodaq/gui/state/time_window_selector.py`.

«10м» value is NOT in the global TimeWindow enum. Do NOT add it. 
Default: drop 10м, use 1мин/1ч/6ч/24ч/Всё (pass `show_6h=True` 
to selector).

---

## Final report

```
=== IV.2 ORCHESTRATOR — FINAL REPORT ===

Start: <timestamp>
End: <timestamp>
Duration: <H:MM>

Stage 0 preflight:
  IV.1 closure verified: YES | NO <reason>
  Finding re-verification:
    A.1: CONFIRMED | RESOLVED | CHANGED
    A.2: CONFIRMED | RESOLVED | CHANGED
    A.3: CONFIRMED | RESOLVED | CHANGED
    B.1: CONFIRMED | RESOLVED | CHANGED
    B.2: CONFIRMED | RESOLVED | CHANGED
    B.3: CONFIRMED | RESOLVED | CHANGED

Commit 1 — A.1 Conductivity stability header placeholder:
  SHA: <sha>
  Codex verdict: PASS | FAIL <reason> | SKIPPED (resolved)
  Amend cycles: N
  Tests: M targeted passing

Commit 2 — A.2 Alarm ACK removal:
  SHA: <sha>
  Codex verdict: PASS | FAIL <reason> | STOPPED (engine-side)
  Amend cycles: N
  Tests: M targeted passing

Commit 3 — B.3 DS rules additions:
  SHA: <sha>
  Codex verdict: PASS | FAIL <reason>
  Amend cycles: N
  Tests: M targeted passing

Commit 4 — B.2 Phase pills ACCENT migration:
  SHA: <sha>
  Codex verdict: PASS | FAIL <reason>
  Amend cycles: N
  Tests: M targeted passing

Commit 5 — B.1 Experiment overlay landing state:
  SHA: <sha>
  Codex verdict: PASS | FAIL <reason>
  Amend cycles: N
  Tests: M targeted passing

Commit 6 — A.3 Keithley global time window:
  SHA: <sha>
  Codex verdict: PASS | FAIL <reason>
  Amend cycles: N
  Tests: M targeted passing

Repository state:
  HEAD: <sha>
  Modified-but-uncommitted: <list or "config/channels.yaml only, pre-existing">
  
STOPs: <list with reasons or "none">

Spec files (retained per architect policy):
  - CC_PROMPT_III_E_UX_HOTFIXES.md — retained
  - CC_PROMPT_III_E_EXPERIMENT_FIXES.md — retained
  - CC_PROMPT_III_F_DS_GAP_FIX.md — retained (archive; content 
    absorbed into B.3 execution)
  - CC_PROMPT_IV_2_ORCHESTRATOR.md — retained

Next action items for architect:
  <residual risks, deferred items, architect decisions needed>
```

Print to terminal. Do NOT delete any files.

---

## Out of scope

- Engine-side handler changes (A.2 STOP if needed)
- Full overlay rewrites beyond B.1
- Schema migrations
- New DS tokens beyond Phase III.A + B.3 rule additions
- Operator manual full rewrite (CHANGELOG per commit enough)
- IV.1 findings (those are closed by IV.1)
- Analytics placeholder widget data wiring (separate block)
- Lazy-open snapshot replay for AnalyticsView (separate block)

---

## Cleanup

**NONE.** No files deleted. All spec files remain on disk:

- `CC_PROMPT_III_E_UX_HOTFIXES.md`
- `CC_PROMPT_III_E_EXPERIMENT_FIXES.md`  
- `CC_PROMPT_III_F_DS_GAP_FIX.md`
- `CC_PROMPT_IV_2_ORCHESTRATOR.md` (this file)
- `CC_PROMPT_IV_BATCH_HOTFIX.md` (IV.1)

Architect has sole authority over file deletion. Final report 
emission ends the block — filesystem state preserved as-is.

---

## Begin

1. Verify IV.1 closed cleanly (Stage 0.1).
2. Re-verify each finding reproduces (Stage 0.2).
3. Execute commits 1-6 in order per spec references.
4. Emit final report.
5. Stop. Leave all files in place.
