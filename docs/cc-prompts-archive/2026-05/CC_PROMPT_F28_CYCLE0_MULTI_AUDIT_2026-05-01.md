# F28 Cycle 0 — Multi-model audit + calibration log start

> EventBus foundation review with Gemini + 4-model metaswarm wave
> alongside running Codex review. Plus: start persistent
> `artifacts/calibration/log.jsonl` capturing each dispatch's
> outcome for multi-session calibration accumulation.

---

## 0. Why this exists

Spec marked Cycle 0 EventBus addition as HIGH risk (foundational
change affecting engine.py + alarm_v2.py + experiment.py +
event_logger.py). Single Codex review insufficient for
verification confidence on safety-critical changes.

Plus: pilot calibration session 2026-04-30 was n=1 per task
class — not proper calibration. Each subsequent multi-model
dispatch should add to a persistent log so we accumulate
data points over weeks. After 5-10 dispatches per task class,
variance estimates become defensible.

This prompt does both: parallel audit of Cycle 0 + bootstrap of
persistent calibration log.

---

## 1. Operating posture

- Architect synchronously available
- Codex Cycle 0 review already running asynchronously — DO NOT
  re-dispatch Codex
- Spawn Gemini + 4-model metaswarm wave in parallel
- Aggregate all 5 verdicts (Codex completing async + 4 new)
- Create persistent calibration log
- Architect smoke-tests verdicts against actual code, classifies
  REAL vs HALLUCINATION per ORCHESTRATION v1.3 §14.6

---

## 2. Persistent calibration log — bootstrap

### 2.1 Create infrastructure

```bash
mkdir -p artifacts/calibration/
```

### 2.2 Initial schema

Create `artifacts/calibration/log.jsonl` (empty file initially).

Each line is a JSON record with this schema:

```json
{
  "session_id": "string, e.g. 2026-05-01-f28-cycle0",
  "session_purpose": "string, free-text purpose",
  "session_date": "ISO-8601 date",
  "task_class": "enum: bug_hypothesis | narrow_review | foundational_change_review | arch_drift | spec_design | code_generation | long_digest | math",
  "task_subtype": "string, free-text more specific (e.g. 'EventBus integration in cryodaq engine')",
  "task_artifact_path": "string, path to the prompt or diff reviewed",
  "model": "string, 'codex/gpt-5.5' | 'gemini/3.1-pro' | 'glm/5.1' | 'qwen3/coder-next' | 'kimi/k2.6' | 'minimax/m2.5' | 'r1/0528' | 'chimera/r1t2' | 'sonnet/4.6' | 'opus/4.7'",
  "verdict": "enum: PASS | CONDITIONAL | FAIL | EMPTY | TIMEOUT | API_ERROR",
  "findings_critical": "int, count of CRITICAL findings claimed",
  "findings_high": "int",
  "findings_medium": "int",
  "findings_low": "int",
  "real_findings_count": "int, after architect verification per §14.6",
  "hallucinated_findings_count": "int, after architect verification",
  "ambiguous_findings_count": "int",
  "architect_verification_done": "bool",
  "latency_s": "float, wall-clock for the dispatch",
  "tokens_in": "int, optional",
  "tokens_out": "int, optional",
  "notes": "string, free-text observations about model behavior in this session"
}
```

### 2.3 Create README

`artifacts/calibration/README.md`:

```markdown
# Calibration log

Append-only structured record of multi-model audit dispatches.
Each dispatch creates one record per model in `log.jsonl`.

## Purpose

Accumulate empirical data on model performance across task
classes over weeks/months. Pilot session 2026-04-30 was n=1
per class; this log enables n>1 statistics over time.

## Schema

See first line of log.jsonl format docs below, or refer to
session prompt files for write-time schema.

## Reading

```bash
# All records for a model
cat log.jsonl | jq 'select(.model == "codex/gpt-5.5")'

# All records for a task class
cat log.jsonl | jq 'select(.task_class == "foundational_change_review")'

# Real-finding ratio per model (post-verification)
cat log.jsonl | jq 'select(.architect_verification_done == true) | 
  {model: .model, ratio: (.real_findings_count / 
   (.real_findings_count + .hallucinated_findings_count + 
    .ambiguous_findings_count))}'
```

## Synthesis

`MODEL-PROFILES.md` — periodically updated synthesis of accumulated
data. Architect-maintained, not auto-generated. Updated when
sufficient data points accumulated for new conclusions.

## Sessions

| Date | Session | Purpose | Records added |
|---|---|---|---|
| 2026-04-30 | pilot calibration | 8 models × 7 task classes | 56 |
| 2026-05-01 | f28-cycle0 | EventBus foundation review | 5 |
| ... | ... | ... | ... |
```

### 2.4 Backfill pilot session into log

Read `artifacts/calibration/2026-04-30/CALIBRATION-MATRIX.md` and
extract scores. For each cell (model, task_class), append one
JSONL line to `log.jsonl` with:
- session_id: "2026-04-30-pilot"
- session_purpose: "Pilot calibration: 8 models × 7 task classes"
- session_date: "2026-04-30"
- task_class: per task name in matrix
- model: per row
- verdict: derived from score (3=PASS, 2=CONDITIONAL, 1=FAIL_partial, 0=FAIL or HALLUCINATION)
- findings counts: from session scoring file if available
- real_findings_count / hallucinated: from architect-spot-check.md if known
- notes: brief summary from per-task scoring file

This bootstraps log with 56 records (or however many were captured).

If exact data not available for a cell, set fields to null and
note in `notes` field "score-only, no findings counts retained".

---

## 3. Cycle 0 multi-model audit

### 3.1 Prepare audit artifact

Codex already has the Cycle 0 commit (26d4162). For other models,
prepare a self-contained prompt:

`artifacts/calibration/2026-05-01-f28-cycle0/audit-prompt.md`:

```markdown
# F28 Cycle 0 audit — EventBus foundation

## Context

CryoDAQ is a production cryogenic data-acquisition system replacing
a 3-year-old LabVIEW VI. Safety-critical, 1,992+ tests. Currently
v0.43.0 master.

Cycle 0 of F28 (Гемма local LLM agent) adds an EventBus primitive
for non-Reading engine events. This is a foundational change touching
multiple core subsystems. Pre-existing event flow:
- AlarmStateManager._listeners callbacks
- ExperimentManager direct method calls
- EventLogger SQLite writes

The new EventBus is a single subscribe point for all engine event
types (alarm transitions, phase transitions, experiment lifecycle,
event_logger appends). Future agents (Гемма) will subscribe.

## Files changed

- `src/cryodaq/core/event_bus.py` — NEW (57 LOC)
- `src/cryodaq/core/event_logger.py` — MODIFIED (+35 LOC)
- `src/cryodaq/engine.py` — MODIFIED (+55 LOC)
- `tests/core/test_event_bus.py` — NEW (130 LOC)

## Diff

[CC inlines `git show 26d4162` here — full diff content]

## Your task

Review this commit with safety-critical mindset. Look for:

1. **Concurrency issues:** EventBus is async pub/sub. Are queue
   operations safe? Backpressure handling on slow subscribers?
   Cancellation safety?
2. **Engine integration breakage:** does adding 6 publish points
   to engine.py change ordering of existing operations? Could
   alarm dispatch be delayed by EventBus publish? Could a
   publish failure crash the engine?
3. **Event ordering guarantees:** when alarm fires AND phase
   transitions in same tick, do EventBus subscribers see them in
   correct order?
4. **Memory safety:** unbounded queue growth if no subscribers?
   Subscriber slow consumer behavior?
5. **Test coverage gaps:** what edge cases are NOT covered by
   the 130 LOC of new tests?

## Output format

Verdict: PASS / CONDITIONAL / FAIL

For each finding:
- Severity: CRITICAL / HIGH / MEDIUM / LOW
- Location: file:line reference
- Description: what's wrong
- Recommended fix

If no findings: brief explanation why confidence is high.

## Constraints

- Be specific. Vague concerns ("may have issues") are not findings.
- Reference exact lines from the diff. Don't speculate about code
  not shown.
- Keep response under 2000 words. Quality over quantity.
- Russian or English both fine.
```

Inline `git show 26d4162` content in the prompt file. Use
`git show 26d4162 --no-color > /tmp/diff.txt` then embed.

### 3.2 Dispatch waves

#### Wave A: Gemini (CLI, parallel to running Codex)

```bash
mkdir -p artifacts/calibration/2026-05-01-f28-cycle0/

START=$(date +%s)
nohup gemini -m gemini-3.1-pro-preview --yolo \
  -p "$(cat artifacts/calibration/2026-05-01-f28-cycle0/audit-prompt.md)" \
  > artifacts/calibration/2026-05-01-f28-cycle0/gemini.response.md 2>&1 &
GEMINI_PID=$!
echo "Gemini dispatched PID=$GEMINI_PID at $START"
```

#### Wave B: Metaswarm (4 models direct Chutes API)

Per ORCHESTRATION v1.3 §15.1 — direct Chutes API, not CCR.

Extract API key:
```bash
CHUTES_API_KEY=$(python3 -c "
import json
cfg = json.load(open('$HOME/.claude-code-router/config.json'))
for p in cfg['Providers']:
    if 'chutes' in p['name'].lower():
        print(p['api_key'])
        break
")
```

For each of 4 models, dispatch with `nohup` background. Models:

1. `zai-org/GLM-5.1-TEE` (good on review per pilot)
2. `Qwen/Qwen3-Coder-Next-TEE` (over-flag risk per pilot — useful counter-signal)
3. `moonshotai/Kimi-K2.6-TEE` (long-context capable; prompt is 5-15KB so within Kimi's stable range)
4. `MiniMaxAI/MiniMax-M2.5-TEE` (new probe; little data)

Skip R1 / Chimera (capacity issues per pilot).

Dispatch template:
```bash
PROMPT_CONTENT=$(cat artifacts/calibration/2026-05-01-f28-cycle0/audit-prompt.md)
PROMPT_JSON=$(python3 -c "
import json, sys
content = sys.stdin.read()
print(json.dumps(content))
" <<< "$PROMPT_CONTENT")

for MODEL in "zai-org/GLM-5.1-TEE" "Qwen/Qwen3-Coder-Next-TEE" "moonshotai/Kimi-K2.6-TEE" "MiniMaxAI/MiniMax-M2.5-TEE"; do
    SHORT=$(echo "$MODEL" | sed 's|.*/||;s|-TEE||')
    nohup curl -s https://llm.chutes.ai/v1/chat/completions \
      -H "Authorization: Bearer $CHUTES_API_KEY" \
      -H "Content-Type: application/json" \
      -d "{\"model\": \"$MODEL\", \"messages\": [{\"role\": \"user\", \"content\": $PROMPT_JSON}], \"max_tokens\": 32000}" \
      > "artifacts/calibration/2026-05-01-f28-cycle0/${SHORT}.raw.json" 2>&1 &
    echo "$SHORT dispatched PID=$!"
done
```

#### Wait for all

12-min cap:
```bash
for i in $(seq 1 12); do
  sleep 60
  CR=$(pgrep -f "codex exec" | wc -l)
  GR=$(pgrep -f "gemini -m gemini" | wc -l)
  CHR=$(pgrep -f "curl.*chat/completions" | wc -l)
  echo "minute $i: codex=$CR gemini=$GR chutes=$CHR"
  if [ "$CR" = "0" ] && [ "$GR" = "0" ] && [ "$CHR" = "0" ]; then
    break
  fi
done
```

### 3.3 Extract responses

For each Chutes response:
```bash
for SHORT in "GLM-5.1" "Qwen3-Coder-Next" "Kimi-K2.6" "MiniMax-M2.5"; do
    python3 -c "
import json
try:
    data = json.load(open('artifacts/calibration/2026-05-01-f28-cycle0/${SHORT}.raw.json'))
    print(data['choices'][0]['message']['content'])
except Exception as e:
    print(f'EXTRACTION_ERROR: {e}')
" > "artifacts/calibration/2026-05-01-f28-cycle0/${SHORT}.response.md"
done
```

Codex response: at `artifacts/handoffs/2026-04-29-f28-cycle0-handoff.md`
or wherever Codex writes by default. Verify path.

### 3.4 Architect-side classification

Read all 5 responses. For each finding:
- File:line referenced — verify exists in diff
- Claimed condition — verify by reading source
- Severity claim — judge independently per ORCHESTRATION §14.6

Classify each finding:
- **REAL** — condition exists, severity defensible
- **HALLUCINATION** — condition does not exist, OR claim contradicts source
- **AMBIGUOUS** — condition exists but severity disputable, OR genuinely judgment call

Architect writes verification ledger:
`artifacts/calibration/2026-05-01-f28-cycle0/verification-ledger.md`:

```markdown
# Cycle 0 multi-model audit — verification ledger

## Per-model summary

| Model | Verdict | Critical | High | Medium | Low | Real | Hallucinated | Ambiguous |
|---|---|---|---|---|---|---|---|---|

## Per-finding classification

### Codex
1. [SEVERITY] Description... → REAL/HALLUCINATION/AMBIGUOUS
   - File:line claimed: ...
   - Architect verified: ...
   - Reasoning: ...

### Gemini
[same format]

### GLM-5.1
[same format]

### Qwen3-Coder
[same format]

### Kimi-K2.6
[same format]

### MiniMax-M2.5
[same format]

## Convergent findings (>1 model identified same issue)
- ...

## Unique findings (only one model identified)
- ...

## Notable model behaviors
- ...

## Architect verdict on Cycle 0
PASS / CONDITIONAL / FAIL with reasoning
```

### 3.5 Append to calibration log

For each model that responded, append one JSONL line to
`artifacts/calibration/log.jsonl` with full schema fields. Use
verification-ledger.md as authoritative source for real /
hallucinated counts.

---

## 4. Decision: merge or fix Cycle 0

Based on aggregated verdicts:

- **All 5 models PASS or CONDITIONAL with no architect-verified
  CRITICAL findings:** Cycle 0 ratified. Proceed to Cycle 1.
- **Any architect-verified CRITICAL finding:** STOP. Apply fix
  on `feat/f28-hermes-agent` branch. Re-dispatch audit (1-2 models
  this time, scope-narrowed to fix verification).
- **Multiple HIGH findings architect-verified:** STOP. Apply
  fixes. Re-dispatch.
- **Predominantly hallucinations:** Cycle 0 likely fine, but
  document hallucination patterns in calibration log notes for
  future weight calibration.

---

## 5. Output deliverables

### 5.1 Files

- `artifacts/calibration/log.jsonl` — bootstrapped with pilot
  backfill + 5 records from this dispatch
- `artifacts/calibration/README.md` — schema + usage
- `artifacts/calibration/2026-05-01-f28-cycle0/audit-prompt.md` —
  prompt sent to all models
- `artifacts/calibration/2026-05-01-f28-cycle0/{codex,gemini,glm,qwen,kimi,minimax}.response.md`
- `artifacts/calibration/2026-05-01-f28-cycle0/verification-ledger.md`

### 5.2 Final report

```markdown
# F28 Cycle 0 multi-audit + calibration log bootstrap

## Cycle 0 verdict
[PASS / FIX-AND-RE-AUDIT / FAIL]

## Models dispatched
| Model | Latency | Verdict | Real / Halluc / Ambiguous |
|---|---|---|---|

## Architect-verified findings to address (if any)
- ...

## Calibration log status
- log.jsonl bootstrapped with N records (M from pilot backfill, 5 from this session)
- README.md created

## Next action
- [Proceed to Cycle 1]  OR
- [Apply fixes per ledger, re-audit]
```

### 5.3 Commit

```bash
git add artifacts/calibration/
git commit -m "calibration: bootstrap log + Cycle 0 multi-audit

Created persistent artifacts/calibration/log.jsonl for accumulating
multi-model audit data over time. Pilot session 2026-04-30
backfilled (~56 records). Each future audit dispatch appends
records.

Cycle 0 (EventBus foundation, commit 26d4162) audited by 5 models:
Codex gpt-5.5 (running), Gemini 3.1 Pro, GLM 5.1, Qwen3-Coder-Next,
Kimi K2.6, MiniMax M2.5.

Architect verification ledger classifies findings as REAL /
HALLUCINATION / AMBIGUOUS per ORCHESTRATION v1.3 §14.6.

Verdict: [PASS / FIX]
[N] real findings, [M] hallucinations.

Ref: CC_PROMPT_F28_CYCLE0_MULTI_AUDIT_2026-05-01.md
Risk: docs only (calibration infrastructure + audit records)."
```

---

## 6. Hard stops

- Codex Cycle 0 review verdict has not yet arrived → wait, do
  NOT skip Codex
- Chutes API key extraction fails → use direct API key from
  shell env if set; otherwise STOP for architect
- All 4 Chutes models fail → calibration data still useful; log
  the failures (verdict: API_ERROR) and proceed
- Gemini quota exhausted → log quota exhaustion, proceed with 4
  Chutes + Codex
- Architect verification reveals all 5 models hallucinated SAME
  finding → unusual, STOP for architect investigation

---

## 7. Begin

Read this prompt fully. Verify Cycle 0 commit `26d4162` is on
`feat/f28-hermes-agent`. Verify Codex review is genuinely
running async (not yet returned). Then:

1. Bootstrap calibration log infrastructure (§2)
2. Backfill pilot session into log (§2.4)
3. Prepare audit artifact (§3.1)
4. Dispatch Gemini + 4 Chutes (§3.2)
5. Wait for all (§3.2 wait pattern)
6. Extract responses (§3.3)
7. Architect classifies (§3.4) — synchronous, surface to architect
   when responses arrive
8. Append to calibration log (§3.5)
9. Decision per §4
10. Final report + commit (§5)

GO.
