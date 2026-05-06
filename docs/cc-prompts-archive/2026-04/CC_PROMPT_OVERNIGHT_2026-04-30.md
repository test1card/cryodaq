# Overnight Runner 2026-04-30 — Big Cleanup Sprint

> Single mega-prompt. Sonnet executes 3 phase clusters across the
> night. Architect ASLEEP throughout. Morning review of everything
> at once.

---

## 0. Operating posture

- **Architect is asleep.** No mid-night chat. Sonnet makes tactical
  decisions per ORCHESTRATION v1.2 §13 autonomy band; strategic
  ambiguities go to handoff with "ARCHITECT DECISION NEEDED" markers.
- **No quota anxiety.** Burn audits freely. Re-audit until convergence
  per cycle.
- **Time budget:** ~8-10 hours total across 3 phase clusters.
- **Sonnet model.** Same approach as F3 + F10 overnights worked well.
- **Architect: web Claude Opus 4.7** — not active during the night.

This is a **multi-track sprint** consolidating 12 outstanding
tasks into one execution session. Doc updates, F-task implementation,
plugin disposition, and calibration re-run combined.

---

## 1. Phase clusters

Three clusters, executed sequentially.

### Phase A — Doc/process updates (1-1.5h)
A1. HF3 docstring fix (calibration spot-check #1)
A2. Multi-model-consultation skill v1.1 update (calibration v1.0 routing)
A3. ORCHESTRATION v1.3 update
A4. Plugin disposition (oh-my-claudecode disable for CryoDAQ)

### Phase B — F-task implementation cluster (5-7h, 7 features)
B1. F19 — F3.W3 enriched experiment_summary (~150-250 LOC)
B2. F20 — Diagnostic alarm aggregation + cooldown (~80-150 LOC)
B3. F21 — Alarm hysteresis deadband (~80-150 LOC)
B4. F22 — F10 escalation severity-upgrade (~80 LOC)
B5. F23 — RateEstimator measurement timestamp (~30 LOC)
B6. F24 — Interlock acknowledge ZMQ command (~100 LOC)
B7. F25 — SQLite WAL startup gate (~50 LOC)

### Phase C — Auxiliary (1-2h)
C1. T2 calibration re-run (`git show 189c4b7` corrected diff)
C2. Final consolidation handoff + tag v0.43.0 if Phase B substantial

---

## 2. Phase A — Doc/process updates

Sequential, all on master directly (no feature branch — these are
small docs edits architect-pre-approved). One commit per task.

### A1. HF3 docstring fix

**Source:** calibration spot-check #1 (Codex+Qwen3+Kimi convergent
finding). Architect-verified against keithley_2604b.py:170-205 —
slew-rate limit (MAX_DELTA_V_PER_STEP = 0.5 V) makes "≤1 s" wrong
for non-small p_target steps.

Edit `src/cryodaq/core/safety_manager.py` `update_target()` docstring:

```python
"""Live-update P_target on an active channel. Validates against config limits.

Updates ``runtime.p_target`` in-memory. The hardware voltage is NOT
changed here directly — the P=const regulation loop in
``Keithley2604B.read_channels()`` reads ``runtime.p_target`` on every
poll cycle and recomputes ``target_v = sqrt(p_target * R)``.

Convergence time depends on the size of the p_target step. For small
steps (delta_v ≤ MAX_DELTA_V_PER_STEP = 0.5 V), convergence completes
in one poll interval (typically ≤1 s). For larger steps, the
slew-rate limiter caps voltage change at 0.5 V per poll cycle, so
full convergence may take multiple seconds (e.g., a 0.5W → 5W jump
on 100Ω can require ~15 polls = ~7-15 s depending on poll interval).

This is intentional: slew-rate limiting and compliance checks live in
the regulation loop and must not be bypassed by direct SCPI writes.
"""
```

Commit:
```
docs(safety): clarify update_target convergence time per slew limit

Calibration session 2026-04-30 spot-check #1: convergent finding from
3 independent models (Codex + Qwen3 + Kimi) flagged the existing
docstring claim "typically ≤1 s" as imprecise.

Architect verified: keithley_2604b.py MAX_DELTA_V_PER_STEP = 0.5 V
slew-rate cap means non-small p_target steps require multiple poll
cycles to converge.

No behavior change. No tests changed.

Ref: artifacts/calibration/2026-04-30/architect-spot-check.md item 1
Batch: phase-A / overnight 2026-04-30 / A1
Risk: docs-only.
```

### A2. Multi-model-consultation skill v1.1

Edit `.claude/skills/multi-model-consultation.md`. Apply
calibration v1.0 routing matrix:

- §2 routing tree update with task-class-aware routing:
  - Bug hypothesis (asyncio/ZMQ/concurrency) → Codex first;
    Chimera/MiniMax for verification
  - Code review (verify correctness, not invent issues) → GLM
    first; Gemini secondary; AVOID Codex/Qwen3/Kimi (over-flag)
  - Spec design → Codex+GLM+Gemini parallel (each adds unique
    insight per calibration T4)
  - Code generation → Codex+GLM (avoid Gemini fabrication; T5
    found Gemini hallucinated `getattr(runtime, "last_i", 0.0)`)
  - Long-context digest → Codex+Qwen3 (only two with arc
    identification on T6 96KB CHANGELOG)
  - Math derivation → any single model (T7 clean sweep, no
    discrimination value)

- §3 formation patterns: add new formation 3.7 — "Calibrated
  task routing" — references the matrix above

- §6 budget table updates: max_tokens=32000 default for Chutes;
  document Kimi long-prompt instability (>50KB unstable) and
  R1/Chimera capacity throttling (add 30+ min inter-wave delay)

- §7 anti-patterns: add "high-reasoning over-flag on consistency
  review" pattern with calibration T3 finding as evidence

Commit:
```
docs(skills): multi-model-consultation v1.1 — calibrated routing matrix

Apply 2026-04-30 calibration session findings to routing rules.

Updates per task class (§2):
- Bug hypothesis → Codex first (sole 3/3 on T1 pyzmq reactor state)
- Code review → GLM first (sole 3/3 on T3 arch-consistency; high-
  reasoning models systematically over-flagged)
- Spec design → Codex+GLM+Gemini parallel (T4 all 3/3 with unique
  insights)
- Code gen → Codex+GLM (T5 Gemini fabricated nonexistent attributes)
- Long digest → Codex+Qwen3 (T6 only two with meta-arc identification)
- Math → any single (T7 clean sweep)

§7 new anti-pattern: high-reasoning models over-flag on consistency
review tasks (Codex/Qwen3/Kimi all rendered DRIFT verdict on
clean code in T3).

§6 budget updates: max_tokens=32000 default for Chutes; Kimi
unstable on >50KB prompts; R1/Chimera need 30+ min inter-wave delay.

Ref: artifacts/calibration/2026-04-30/CALIBRATION-MATRIX.md
Ref: artifacts/calibration/2026-04-30/MASTER-SUMMARY.md
Batch: phase-A / overnight 2026-04-30 / A2
Risk: docs-only.
```

### A3. ORCHESTRATION v1.3

Edit `docs/ORCHESTRATION.md`. Three additions:

#### §10 session-start checklist — add bullet

```
- [ ] **Plugin auto-load awareness.** At session start, note any
  plugins (`oh-my-claudecode`, `metaswarm`, etc.) that loaded
  automatically per skill description matchers. If auto-load was
  not architect-anticipated, flag in handoff. Plugin tooling
  outside our skill registry may conflict with multi-model-
  consultation routing.
```

#### §14 verification practices — new subsection §14.6

```
### 14.6 Hallucination verification before action

When a metaswarm or multi-model audit produces CRITICAL or HIGH
findings, architect-side verification MANDATORY before any
hotfix or merge. Models are confidently wrong with non-trivial
frequency.

Empirical: 2026-04-29 metaswarm Task A produced 9 verified
findings + 2 fabricated (~22% hallucination rate on CRITICAL
claims). 2026-04-30 calibration session: convergent T3 finding
across 3 models was real (slew-rate docstring imprecision)
but each model's verdict (DRIFT vs CONSISTENT) was wrong.

Discipline before action:
1. Read source file at exact line referenced
2. Verify the claimed condition exists (grep for method name,
   class, regex pattern)
3. If condition exists: severity may still differ from model's
   claim (CRITICAL vs LOW). Architect re-rates.
4. If condition does NOT exist: HALLUCINATION. Document in
   verification ledger. Do NOT fix the imagined issue.

Verification ledger format:
`artifacts/handoffs/<date>-<topic>-verification.md`

Per finding: claim, file:line referenced, actual content at that
location, REAL/HALLUCINATION/RELOCATE/AMBIGUOUS verdict, action.
```

#### §15 NEW — Multi-model dispatch realities

```
## 15. Multi-model dispatch realities

Added 2026-04-30 (v1.3) consolidating empirical findings from
metaswarm session 2026-04-29 + calibration session 2026-04-30.

### 15.1 CCR vs direct Chutes API

CCR `localhost:3456` requires Claude Code OAuth context to route
to providers. Direct curl (without OAuth) returns "Provider
'undefined' not found". This is by-design CCR behavior, NOT a
config bug.

For batch dispatch (metaswarm, calibration), use **direct
Chutes API**:
- Endpoint: `https://llm.chutes.ai/v1/chat/completions`
- Auth: `Authorization: Bearer $CHUTES_API_KEY`
- Key location: `~/.claude-code-router/config.json` Providers[chutes].api_key
- Extract via: `python3 -c "import json; cfg=json.load(open('$HOME/.claude-code-router/config.json')); [print(p['api_key']) for p in cfg['Providers'] if 'chutes' in p['name'].lower()]"`

CCR is for interactive use within CC sessions. Batch dispatch
uses direct API.

### 15.2 max_tokens per model

Chutes models reject `max_tokens=null`. Use explicit cap. Default:
`max_tokens=32000` (high enough that models hit natural stop
conditions, not truncation).

Per-model practical caps:
- MiniMax-M2.5: 8192 non-streaming
- R1-0528, Kimi-K2.6: 8000 in practice
- GLM-5.1, Qwen3-Coder: 4000 stable

Set 32000 as request, models cap themselves.

### 15.3 Codex sandbox modes

Three sandbox options affect stdout:
- `--sandbox read-only` — blocks stdout writes. EMPTY responses
  for spec-generation tasks (2026-04-29 metaswarm Task B).
- `--sandbox workspace-write` — DEFAULT for review/audit tasks.
  Writes to workspace allowed.
- `--sandbox none` — invalid (codex 0.124+ rejects). Use
  workspace-write.

For audit + review use workspace-write. NOT none.

### 15.4 Capacity reliability ranking (empirical)

Per 2026-04-30 calibration session:
1. Codex, Qwen3-Coder, MiniMax-M2.5 — 0% failure rate
2. GLM-5.1, Gemini — ~17% failure rate (single waves)
3. R1-0528 — 33% failure rate (daytime UTC saturation)
4. Chimera (TNG) — 50% failure rate
5. Kimi-K2.6 — 67% failure rate (connection instability on
   long prompts)

For overnight reliability: prefer Codex + Qwen3-Coder + MiniMax
over R1/Chimera/Kimi. Add 30+ min inter-wave delay if R1 or
Chimera in dispatch list.

### 15.5 Kimi long-prompt threshold

Kimi-K2.6 connection drops on prompts >50KB approximately.
2026-04-29 metaswarm 375KB prompts all PARSE_ERROR.
2026-04-30 calibration T6 96KB also failed.
T4 spec design ~5KB succeeded.

Discipline: keep Kimi prompts ≤10KB conservative, ≤50KB risky.

### 15.6 Architect verification mandatory

Per §14.6: synthesis is first-pass aggregation, NOT truth.
Hallucination rate is non-zero. Architect verifies CRITICAL
+ HIGH findings against actual source before any action.
```

Commit:
```
docs(orchestration): v1.3 — plugin awareness + hallucination + dispatch realities

Three additions accumulated from 2026-04-29 metaswarm + 2026-04-30
calibration sessions:

§10 session checklist: plugin auto-load awareness bullet
(oh-my-claudecode auto-loaded without announcement during 2026-04-29
HF1+HF2 session; transparency requires CC announces at start).

§14.6 NEW: hallucination verification discipline. Empirical: 22%
hallucination rate on CRITICAL findings from metaswarm Task A
(2/9). Architect-side verification MANDATORY before action on any
CRITICAL/HIGH finding. Read source at file:line, grep for claimed
condition, judge severity independently of model claim.

§15 NEW: multi-model dispatch realities. Six subsections:
- CCR requires OAuth; direct Chutes API for batch dispatch
- max_tokens=32000 default; per-model caps documented
- Codex sandbox modes (workspace-write for audit, NOT read-only or none)
- Capacity reliability ranking from calibration data
- Kimi long-prompt threshold ~50KB
- Architect verification mandatory pointer back to §14.6

Ref: artifacts/calibration/2026-04-30/MASTER-SUMMARY.md
Ref: artifacts/handoffs/2026-04-29-task-a-verification.md
Ref: artifacts/handoffs/2026-04-29-metaswarm-summary.md
Batch: phase-A / overnight 2026-04-30 / A3
Risk: docs-only.
```

### A4. Plugin disposition

Disable oh-my-claudecode plugin auto-load for CryoDAQ.

Recon:
```bash
ls -la ~/.claude/plugins/cache/omc/ 2>/dev/null
cat .claude/settings.json 2>/dev/null
cat .claude/settings.local.json 2>/dev/null
```

Decision tree:
- If repo has `.claude/settings.json`: add directive disabling
  oh-my-claudecode auto-load for this project
- If no settings.json: create one with project-level skill
  exclusion rule
- Document chosen approach in `docs/decisions/2026-04-30-plugin-disposition.md`

Format of disable directive (verify against current CC plugin
docs — pattern may have changed):
```json
{
  "plugins": {
    "disabled": ["oh-my-claudecode"]
  }
}
```

OR use plugin-level `.claude-plugins-ignore` if such file exists.

If neither pattern works (CC docs unclear): fall back to renaming
plugin cache:
```bash
mv ~/.claude/plugins/cache/omc/oh-my-claudecode/4.13.1 \
   ~/.claude/plugins/cache/omc/oh-my-claudecode/4.13.1.disabled-cryodaq-2026-04-30
```

Document the chosen approach in decision file.

Commit:
```
chore(plugins): disable oh-my-claudecode auto-load for CryoDAQ

Plugin loaded silently during 2026-04-29 HF1+HF2 session
("making commits" trigger). Architect decision: existing
multi-model-consultation skill + ORCHESTRATION v1.2 sufficient;
silent auto-activation undermines transparency.

Per ORCHESTRATION v1.3 §10 session-start checklist (plugin
auto-load awareness).

Approach taken: <document the actual approach used>.

Ref: docs/decisions/2026-04-30-plugin-disposition.md
Batch: phase-A / overnight 2026-04-30 / A4
Risk: low — config change only.
```

### A5. Phase A summary

After A1-A4 commits, push:
```
git push origin master
```

If any of A1-A4 fails for non-trivial reason: STOP that task,
write findings to handoff, move to remaining A tasks. Don't
block whole phase A on single failure.

---

## 3. Phase B — F-task implementation cluster

7 features. Sonnet implements **on dedicated feature branch per
batch**, not on master. Each feature is small (S effort) so we
batch related ones.

### Branch strategy

Two batches of grouped features:

**Batch B-alarm:** F20, F21, F22 — all alarm-pipeline-touching
- Branch: `feat/overnight-alarm-cluster`
- Total: ~240-380 LOC
- Audit: dual-verifier per feature, merge whole batch when all green

**Batch B-misc:** F19, F23, F24, F25 — independent features
- Branch: `feat/overnight-misc-cluster`
- Total: ~360-600 LOC
- Audit: dual-verifier per feature, merge whole batch when all green

Two batches because:
1. Alarm-cluster shares context (alarm_v2.py, sensor_diagnostics.py)
   so dispatching together saves recon time
2. Misc-cluster touches independent files; can be implemented in
   any order

### Per-feature pattern

For each F-task within a batch:

1. **Spec recon:** read ROADMAP entry + Task A verification ledger
   for original finding source
2. **Source recon:** §14.1 — verify the file/line referenced in
   spec exists and is current
3. **Implement:** per spec
4. **Test:** add tests covering spec acceptance criteria
5. **Audit dispatch:** dual-verifier per ORCHESTRATION §14.2
   (Codex + Gemini). If Gemini quota exhausted: skip, document.
6. **Fix loop:** apply audit findings until both PASS or 5 iter
7. **Commit on batch branch** (not master)
8. **Move to next feature in batch**

After all features in batch done, push branch + write batch
handoff. **Do NOT auto-merge.** Architect reviews in morning.

### B1. F19 — F3.W3 enriched experiment_summary

**Branch:** feat/overnight-misc-cluster

**Source:** ROADMAP F19. Three sub-items:
1. Channel min/max/mean table (T1..T8 cryostat, pressure, Keithley)
   computed via readings_history range queries
2. Top-3 most-triggered alarm names from alarm_v2_history
3. Clickable artifact links via QDesktopServices.openUrl

**Files:** `src/cryodaq/gui/shell/views/analytics_widgets.py` (W3
ExperimentSummaryWidget)

**Tests:** `tests/gui/shell/views/test_analytics_widget_experiment_summary.py`
extension — assert each new section renders with mock data, plus
empty-state coverage.

### B2. F20 — Diagnostic alarm aggregation + cooldown

**Branch:** feat/overnight-alarm-cluster

**Source:** ROADMAP F20. Two enhancements:
1. **Aggregation:** when N>3 channels go warning/critical in same
   tick, single Telegram message: "5 channels critical: T1, T3, T5,
   T7, T9" instead of 5 separate.
2. **Per-channel escalation cooldown:** prevent rapid
   warning→critical→warning re-firing if channel oscillates near
   threshold. Configurable cooldown window.

**Files:** `src/cryodaq/core/alarm_v2.py`,
`src/cryodaq/core/sensor_diagnostics.py`,
`config/plugins.yaml` (new `escalation_cooldown_s` field).

**Tests:** new test_diagnostic_alarm_aggregation.py covering both
aggregation threshold + cooldown semantics.

### B3. F21 — Alarm hysteresis deadband

**Branch:** feat/overnight-alarm-cluster

**Source:** ROADMAP F21 / Task A finding #1.3. Implement
`AlarmStateManager._check_hysteresis_cleared()` per config schema's
existing `hysteresis` key (currently stub returning True).

**Files:** `src/cryodaq/core/alarm_v2.py`, `config/alarms_v3.yaml`
(document schema), tests.

**Tests:** add test_hysteresis_deadband_clears_only_below_margin.

### B4. F22 — F10 escalation severity-upgrade

**Branch:** feat/overnight-alarm-cluster

**Source:** ROADMAP F22 / Task A finding #1.4. Current behavior:
warning + critical use same `alarm_id = f"diag:{channel_id}"`,
critical never fires once warning active.

**Decision:** implement severity-upgrade semantics (critical
replaces warning in-place, same alarm_id). Alternative was
separate alarm_ids — rejected because operator gets duplicate
notifications.

**Files:** `src/cryodaq/core/alarm_v2.py`
`publish_diagnostic_alarm()`.

**Tests:** test_warning_then_critical_progression edge case
(warning → 5 min later critical, expect single alarm with severity
upgrade event).

### B5. F23 — RateEstimator measurement timestamp

**Branch:** feat/overnight-misc-cluster

**Source:** ROADMAP F23 / Task A finding #1.7. Currently
`SafetyManager._collect_loop` calls
`RateEstimator.push(channel, time.monotonic(), value)`. Should be
`RateEstimator.push(channel, reading.timestamp.timestamp(), value)`
to use measurement time, not queue dequeue time.

**Files:** `src/cryodaq/core/safety_manager.py` `_collect_loop`.

**Tests:** test_rate_estimator_uses_measurement_timestamp_not_dequeue.

### B6. F24 — Interlock acknowledge ZMQ command

**Branch:** feat/overnight-misc-cluster

**Source:** ROADMAP F24 / Task A finding #1.8. Expose
`InterlockEngine.acknowledge()` as ZMQ verb so operator can re-arm
interlock after underlying condition cleared. Currently no way to
re-arm without process restart.

**Files:** `src/cryodaq/core/zmq_bridge.py` (add
`interlock_acknowledge` handler), `src/cryodaq/core/interlock.py`
(if `acknowledge()` method needs adjustment).

**Tests:** test_interlock_acknowledge_via_zmq_command.

### B7. F25 — SQLite WAL startup gate

**Branch:** feat/overnight-misc-cluster

**Source:** ROADMAP F25 / Task A finding #1.10. Currently
`SQLiteWriter._check_sqlite_version()` uses `logger.warning()` for
affected SQLite versions (3.7.0–3.51.2 WAL corruption bug). Should
hard-fail OR opt-in env var bypass.

**Architect decision:** hard-fail by default, env var
`CRYODAQ_ALLOW_BROKEN_SQLITE=1` to bypass with explicit operator
acknowledgment.

**Files:** `src/cryodaq/storage/sqlite_writer.py`
`_check_sqlite_version()`.

**Tests:** test_startup_gates_on_known_broken_sqlite_version,
test_env_var_bypass_allows_broken_version.

### B8. Phase B summary

After both batches green + pushed:
- `feat/overnight-alarm-cluster` at SHA pushed
- `feat/overnight-misc-cluster` at SHA pushed
- DO NOT merge. Architect reviews in morning per ORCHESTRATION
  v1.2 §13 (architect-domain decision: merge or not)

Write batch handoffs:
- `artifacts/handoffs/2026-04-30-f-cluster-alarm.md` (F20-F22)
- `artifacts/handoffs/2026-04-30-f-cluster-misc.md` (F19, F23-F25)

---

## 4. Phase C — Auxiliary

### C1. T2 calibration re-run

Re-dispatch T2 (narrow code review of HF1+HF2 commit `189c4b7`)
with the **corrected brief** that uses `git show 189c4b7` raw
diff output, not the bug-formatted version that placed test
functions under production module header.

5 models in scope (R1/Chimera/Qwen3 had capacity failures during
original T2 wave anyway): Codex, Gemini, GLM, Kimi, MiniMax.

Per calibration spec dispatch syntax (direct Chutes API for
non-CLI models):

Brief at `artifacts/calibration/2026-04-30/T2-narrow-review/codex.prompt.md`
+ similar for each model. Generate brief from git diff:
```bash
mkdir -p artifacts/calibration/2026-04-30/T2-narrow-review-rerun/
git show 189c4b7 > artifacts/calibration/2026-04-30/T2-narrow-review-rerun/diff.txt
```

Inline diff content into each model's brief. Models score per
T2 rubric (PASS/FAIL on bug-finding, hallucination resistance).

Update `artifacts/calibration/2026-04-30/T2-narrow-review/scoring.md`
with re-run results. Mark original session T2 column as
INVALIDATED-RERUN with pointer to new file.

If any model returns CRITICAL findings: architect manually
verifies in morning (HF1+HF2 already merged + tagged in v0.42.0).

### C2. Final consolidation handoff

After Phases A+B+C done:

Write `artifacts/handoffs/2026-04-30-overnight-summary.md`:

```markdown
# Overnight 2026-04-30 — Master Summary

## Phases executed
| Cluster | Status | Commits | Risk |
|---|---|---|---|
| A — Doc/process | ... | A1+A2+A3+A4 SHAs | low |
| B — F-task alarm batch | ... | branch SHA | medium |
| B — F-task misc batch | ... | branch SHA | medium |
| C — T2 re-run + summary | ... | n/a | none |

## Phase A outcomes
- HF3 docstring: pushed
- multi-model-consultation v1.1: pushed
- ORCHESTRATION v1.3: pushed
- Plugin disposition: <approach>

## Phase B outcomes
| Feature | Branch | Status | Tests | Audit verdict |
|---|---|---|---|---|
| F19 | misc | ... | ... | ... |
| F20 | alarm | ... | ... | ... |
| F21 | alarm | ... | ... | ... |
| F22 | alarm | ... | ... | ... |
| F23 | misc | ... | ... | ... |
| F24 | misc | ... | ... | ... |
| F25 | misc | ... | ... | ... |

## Phase C outcomes
- T2 re-run: <model count successful>
- Calibration matrix updated: yes/no

## Architect morning queue (priority order)
1. Review A1-A4 commits (already on master, just verify state)
2. Review feat/overnight-alarm-cluster branch handoff
3. Review feat/overnight-misc-cluster branch handoff
4. Decide merge order for two batches
5. Decide tag v0.43.0 if features substantial
6. Review T2 re-run scoring update
7. Review any ARCHITECT DECISION NEEDED markers

## Outstanding
- F-tasks F19-F25: pushed branches awaiting merge
- T2 calibration data refreshed
- ROADMAP: F-tasks status update needed after merge
- Vault: Versions.md row for v0.43.0 if tagged
```

If Phase B substantial (most features merged green):
- Tag candidate: v0.43.0 — feature batch
- Architect tags after morning review + merge

If only Phase A landed:
- No tag needed (docs-only)
- Master at A4 SHA

### C3. Wake-up echo

```bash
echo "═══════════════════════════════════════"
echo "OVERNIGHT 2026-04-30 COMPLETE"
echo "═══════════════════════════════════════"
echo "Master HEAD: $(git log -1 --format='%h %s' master)"
echo "Branches awaiting review:"
git branch -av | grep -E "feat/overnight-(alarm|misc)-cluster"
echo "Phase A commits on master:"
git log --oneline master | head -5
echo "Handoffs:"
ls artifacts/handoffs/2026-04-30-* | head -10
echo "═══════════════════════════════════════"
echo "Architect: read artifacts/handoffs/2026-04-30-overnight-summary.md first"
```

---

## 5. Hard stops (whole-night-level)

These STOP THE ENTIRE NIGHT (write summary explaining and quit):

- Master HEAD different from expected at start (drift since
  cleanup completion `4ecc03c`)
- Test infrastructure broken on master baseline
- Disk full / OOM
- Phase A1 (HF3) docstring fix breaks tests — investigate
  before any further work
- All audit dispatch (Codex+Gemini) fails on first feature in
  Phase B batch — environment issue
- Working tree corruption Sonnet didn't introduce

A single feature stuck does NOT stop the night. Move to next
feature in batch. Mark stuck feature INCOMPLETE in handoff.

---

## 6. Architect comm-out discipline

- Sonnet does NOT see chat. Write everything to handoffs.
- When unsure: apply safest interpretation, document in handoff
  under "ARCHITECT DECISION NEEDED", continue.
- Per ORCHESTRATION §13.5 autonomy band: adapt mechanical details,
  do NOT merge feature branches autonomously, do NOT delete files.

Examples of safest interpretation:
- Spec ambiguous → defer to existing pattern in code
- Test design two options → pick simpler fixtures
- Audit MEDIUM finding ambiguous → leave + document
- Plugin disable approach unclear → use most-conservative
  (rename cache directory; document in decision file)

---

## 7. Tracking discipline

For each feature in Phase B:

1. Pre-implementation snapshot:
   - Files to be modified (list)
   - Spec acceptance criteria (numbered list)
2. Post-implementation diff stat
3. Test count: pre / post
4. Audit verdict per iteration
5. Final state per acceptance criterion (PASS/FAIL/PARTIAL)

Per-feature handoff section in batch handoff:

```markdown
### F<NN> — <name>

Branch: feat/overnight-<batch>-cluster at <SHA>
Files changed: <list>
LOC: +X / -Y
Tests added: <count>

Acceptance criteria:
1. [PASS] <criterion>
2. [PASS] <criterion>
3. [PARTIAL] <criterion> — what was done, what wasn't

Audit history:
- Codex iter 1: <verdict>
- Gemini iter 1: <verdict>
- (subsequent iterations if needed)

Final unfixed findings:
| # | Severity | Notes |

Spec deviations:
- None / list with rationale

Architect decisions needed:
- ...
```

---

## 8. Begin

Phase A1 first. Read this whole prompt. Verify clean master at
`4ecc03c` or later (post-cleanup commit `4ecc03c`).

GO.
