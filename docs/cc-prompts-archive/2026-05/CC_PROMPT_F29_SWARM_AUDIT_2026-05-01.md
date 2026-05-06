# F29 Cycle 1 — Swarm audit для калибровки

> Multi-model independent audit of F29 periodic reports (commit
> `ef0a1eb`, tag v0.46.0, branch `feat/f29-periodic-reports`).
> Codex self-audit already PASS_AFTER_FIX. GLM dispatch hung
> (CCR). This swarm gives independent verification + calibration
> data points across all available models.
>
> Per ORCHESTRATION v1.4 §16.3: narrow_feature_extension scope.
> Per ORCHESTRATION v1.4 §17: append all dispatches to log.jsonl
> for calibration accumulation.
>
> Goal: PASS_RATIFIED with independent verification, OR surface
> any missed real finding for fix-up before master merge.

---

## 0. Operating posture

- Architect synchronously available
- F29 already PASS_AFTER_FIX from Codex self-audit (commit `ef0a1eb`)
- Branch NOT yet merged to master — fix-up still possible
- Use direct Chutes API via `.swarm/scripts/run_chutes.sh` (CCR
  hung last attempt)
- Use Codex CLI directly for fresh independent Codex dispatch
- Skip Gemini if chronic 429 (acceptable, log as API_ERROR)

---

## 1. Recon first

Verify state before any dispatch:

```bash
cd /Users/vladimir/Projects/cryodaq

# Verify branch state
git rev-parse HEAD                          # should be on master
git rev-parse feat/f29-periodic-reports     # should resolve to ef0a1eb area
git tag -l v0.46.0                           # should exist
git log master..feat/f29-periodic-reports --oneline | head -20

# Verify worktree
ls .worktrees/feat-f29-periodic-reports/

# Verify swarm tooling
ls .swarm/scripts/
cat .swarm/config/env.sh
test -f "$HOME/.claude-code-router/config.json" && echo "CCR config OK"

# Verify previous audit artifacts
ls .worktrees/feat-f29-periodic-reports/artifacts/consultations/2026-04-30/f29-cycle1-audit/
```

If recon fails on any item — STOP, surface to architect.

---

## 2. Build audit artifact

Single self-contained prompt sent to all models. Construct in:

`artifacts/calibration/2026-05-01-f29-swarm/audit-prompt.md`

### 2.1 Prompt structure

```markdown
# F29 Cycle 1 audit — periodic narrative reports

## Context

CryoDAQ is a production cryogenic data-acquisition system. v0.46.0
ships F29: hourly Russian-language narrative summary of last-N-minutes
engine activity, dispatched to Telegram + operator log + GUI insight
panel.

This commit was already self-audited by Codex gpt-5.5 — that audit
found 2 real issues which were fixed before this audit. Your job
is independent verification: are there issues that Codex missed?

## Scope

Branch: feat/f29-periodic-reports
Final commit: ef0a1eb (release: v0.46.0)
Diff range: master..feat/f29-periodic-reports

## Files in scope

- src/cryodaq/engine.py — _periodic_report_tick coroutine, startup wiring
- src/cryodaq/agents/assistant/live/agent.py — _handle_periodic_report
- src/cryodaq/agents/assistant/live/context_builder.py — build_periodic_report_context, PeriodicReportContext
- src/cryodaq/agents/assistant/live/prompts.py — PERIODIC_REPORT_SYSTEM/USER
- src/cryodaq/agents/assistant/live/output_router.py — prefix_suffix support
- config/agent.yaml — triggers.periodic_report block
- tests/agents/assistant/test_engine_periodic_report_tick.py
- tests/agents/assistant/test_periodic_report_config.py
- tests/agents/assistant/test_periodic_report_context.py
- tests/agents/assistant/test_periodic_report_handler.py
- artifacts/scripts/smoke_f29_periodic_report.py
- CHANGELOG.md, ROADMAP.md, pyproject.toml (release bump)

## Already fixed in pre-audit pass (DO NOT report these as findings)

The following issues were caught by Codex self-audit and FIXED in
ef0a1eb. Reporting them again will be classified as
HALLUCINATION_ECHO and lower your score:

1. PERIODIC_REPORT_SYSTEM hardcoded "последний час" wording —
   FIXED to "заданное окно времени"
2. Calibration events bucketed into other-events instead of own
   section — FIXED with calibration_entries field + Калибровка:
   prompt section
3. Smoke harness fake timer sleep loop — FIXED with CancelledError
   on second sleep

## Your task

Independent review. Focus on:

1. **Engine integration** — _periodic_report_tick startup,
   shutdown, cancellation, exception handling. Could it crash
   the engine? Could it leak tasks? Could it block other
   periodic ticks?
2. **EventBus contract** — periodic_report_request payload schema.
   Does it match what handler expects? Is window_minutes int or
   float?
3. **Skip-if-idle correctness** — total_event_count threshold.
   Does it count what it should count? Could empty intervals
   slip through? Could populated intervals get suppressed?
4. **Rate limiter interaction** — periodic_report shares bucket
   with other triggers. Could a stuck periodic block other
   handlers? Could rate limit drop a periodic without
   acknowledgement?
5. **Russian prompt grounding** — does PERIODIC_REPORT_USER
   actually pass real data through? Could it hallucinate events?
   Could empty sections leak placeholders?
6. **Output dispatch path** — prefix_suffix passed to all 3
   channels (Telegram, log, GUI)? Could one fail silently?
7. **Test coverage gaps** — what scenarios are NOT tested?
   - Engine timer cancellation mid-inference
   - Concurrent periodic + alarm dispatch
   - Empty Ollama response handling
   - SQLite read failure during context build
   - Misconfigured interval (negative, zero, float)
8. **Russian quality regressions** — anything in PERIODIC_REPORT_*
   templates that could degrade quality vs F28 Slice A baseline?
9. **Markdown rendering in Telegram** — sample output contained
   `$\rightarrow$` (LaTeX). Does the prompt instruct against
   LaTeX? Does the output sanitizer strip it? This is a known
   architect concern not yet addressed.
10. **Locale / timezone** — do timestamps in summaries use
    consistent timezone? Could DST transition cause off-by-1h?

## Output format

Verdict: PASS / CONDITIONAL / FAIL

For each finding:
- Severity: CRITICAL / HIGH / MEDIUM / LOW
- File:line reference (must exist in actual diff — verify)
- Description: what's wrong, in 1-3 sentences
- Why it matters: 1 sentence operational impact
- Recommended fix: 1-2 sentences

If no findings: brief explanation why confidence is high after
review.

## Constraints

- Be specific. Vague concerns ("may have issues") are not findings.
- Reference exact lines from the diff. Speculation about code not
  shown will be classified as hallucination.
- Keep response under 1500 words. Quality over quantity.
- Russian or English both fine. Russian preferred for findings
  about Russian prompt quality.
- DO NOT echo the 3 already-fixed findings in §"Already fixed".
```

### 2.2 Inline diff content

Append to prompt file:

```bash
mkdir -p artifacts/calibration/2026-05-01-f29-swarm/

# Generate diff brief (~10KB target)
git diff master..feat/f29-periodic-reports -- \
  src/cryodaq/engine.py \
  src/cryodaq/agents/assistant/live/agent.py \
  src/cryodaq/agents/assistant/live/context_builder.py \
  src/cryodaq/agents/assistant/live/prompts.py \
  src/cryodaq/agents/assistant/live/output_router.py \
  config/agent.yaml \
  tests/agents/assistant/test_engine_periodic_report_tick.py \
  tests/agents/assistant/test_periodic_report_config.py \
  tests/agents/assistant/test_periodic_report_context.py \
  tests/agents/assistant/test_periodic_report_handler.py \
  > /tmp/f29-diff.patch

wc -l /tmp/f29-diff.patch
wc -c /tmp/f29-diff.patch

# If <100KB, embed in prompt; else trim to most-changed files
cat artifacts/calibration/2026-05-01-f29-swarm/audit-prompt.md \
  <(echo) <(echo "## Diff") <(echo '```diff') /tmp/f29-diff.patch <(echo '```') \
  > artifacts/calibration/2026-05-01-f29-swarm/audit-prompt-with-diff.md

wc -c artifacts/calibration/2026-05-01-f29-swarm/audit-prompt-with-diff.md
```

If diff exceeds 50KB after assembly — split into prompt-with-diff
(full version for Codex/GLM/Qwen) and prompt-with-summary (trimmed
diff for Kimi which has known >50KB instability).

---

## 3. Dispatch waves

### 3.1 Wave A — Fresh Codex (independent)

Codex stateless between sessions. Fresh dispatch frame as foreign
code:

```bash
START=$(date +%s)

cd /Users/vladimir/Projects/cryodaq
nohup codex exec \
  --sandbox read-only \
  --skip-git-repo-check \
  -- "$(cat artifacts/calibration/2026-05-01-f29-swarm/audit-prompt-with-diff.md)" \
  > artifacts/calibration/2026-05-01-f29-swarm/codex-fresh.response.md 2>&1 &

CODEX_PID=$!
echo "Codex fresh dispatched PID=$CODEX_PID at $START"
```

Note: This Codex instance has no memory of writing F29. It sees
the diff as foreign code. Independent verification.

### 3.2 Wave B — Chutes models via .swarm

Use existing `.swarm/scripts/run_chutes.sh` infrastructure. Runs
in parallel. Models per ORCHESTRATION v1.4 §17.4 patterns:

```bash
source .swarm/config/env.sh

PROMPT_FILE=artifacts/calibration/2026-05-01-f29-swarm/audit-prompt-with-diff.md
OUT_DIR=artifacts/calibration/2026-05-01-f29-swarm

# Models to dispatch
MODELS=(
  "zai-org/GLM-5.1-TEE:0.3:GLM-5.1"
  "Qwen/Qwen3-Coder-Next-TEE:0.3:Qwen3-Coder-Next"
  "moonshotai/Kimi-K2.6-TEE:0.3:Kimi-K2.6"
  "MiniMaxAI/MiniMax-M2.5-TEE:0.3:MiniMax-M2.5"
  "deepseek-ai/DeepSeek-R1-0528:0.3:R1-0528"
  "tngtech/DeepSeek-TNG-R1T2-Chimera:0.3:Chimera-R1T2"
)

for ENTRY in "${MODELS[@]}"; do
  IFS=':' read -r MODEL_ID TEMP SHORT <<< "$ENTRY"
  OUT_FILE="$OUT_DIR/${SHORT}.response.md"
  echo "[$(date +%H:%M:%S)] Dispatching $SHORT ($MODEL_ID)..."
  nohup .swarm/scripts/run_chutes.sh "$MODEL_ID" "$TEMP" "$PROMPT_FILE" "$OUT_FILE" \
    > "$OUT_DIR/${SHORT}.dispatch.log" 2>&1 &
  PID=$!
  echo "$SHORT PID=$PID"
  sleep 2  # stagger to avoid burst rate limits
done

echo "All Chutes dispatches launched"
```

**IMPORTANT:** `run_chutes.sh` has `max_tokens: 4000` hardcoded.
For GLM-5.1 reasoning mode this is too tight (per
ORCHESTRATION v1.4 §17.4 — needs ≥8192). Either:

- Override max_tokens in a copy of the script for this run, OR
- Edit `.swarm/scripts/run_chutes.sh` (carefully, with backup) to
  bump default to 8192

Architect default: temporary script copy `run_chutes_8k.sh` with
`max_tokens: 8192` for this swarm only. Original script unchanged.

### 3.3 Wave C — Gemini (optional)

Try once, accept failure:

```bash
START=$(date +%s)
timeout 300 gemini -m gemini-3.1-pro-preview --yolo \
  -p "$(cat artifacts/calibration/2026-05-01-f29-swarm/audit-prompt-with-diff.md)" \
  > artifacts/calibration/2026-05-01-f29-swarm/Gemini-3.1-Pro.response.md 2>&1 || \
  echo "GEMINI_FAILED" > artifacts/calibration/2026-05-01-f29-swarm/Gemini-3.1-Pro.response.md
END=$(date +%s)
echo "Gemini wall: $((END - START))s"

# Verify what model actually responded (silent fallback to 2.5-pro common)
grep -i "gemini\|model" artifacts/calibration/2026-05-01-f29-swarm/Gemini-3.1-Pro.response.md | head -5
```

Per ORCHESTRATION v1.4 §17.6 — record actual model identity if
silent fallback to 2.5-Pro detected.

### 3.4 Wait for completion

```bash
for i in $(seq 1 15); do
  sleep 60
  CR=$(pgrep -f "codex exec" | wc -l | xargs)
  CHR=$(pgrep -f "run_chutes" | wc -l | xargs)
  echo "[minute $i] codex=$CR chutes=$CHR"
  if [ "$CR" = "0" ] && [ "$CHR" = "0" ]; then
    echo "All dispatches complete"
    break
  fi
done

# After loop — kill any stragglers >15min
pkill -f "run_chutes" 2>/dev/null || true
pkill -f "codex exec" 2>/dev/null || true
```

15-min cap. Kimi/MiniMax/R1/Chimera may TIMEOUT — log honestly.

---

## 4. Architect classification (synchronous)

**Surface to architect when responses arrive.** Do not classify
autonomously — this requires architect judgment per
ORCHESTRATION v1.4 §14.6.

For each model that returned content, prepare:

`artifacts/calibration/2026-05-01-f29-swarm/verification-ledger.md`:

```markdown
# F29 swarm audit — verification ledger

## Per-model summary

| Model | Latency | Verdict | Crit | High | Med | Low | Real | Halluc | Ambig | Notes |
|---|---|---|---|---|---|---|---|---|---|---|

## Per-finding classification

### Codex fresh (independent)

#### F-CF-1 [SEVERITY] Description
- File:line claimed: ...
- Architect verified: REAL / HALLUCINATION / AMBIGUOUS / HALLUCINATION_ECHO
- Reasoning: ...

(repeat per finding)

### GLM-5.1
(...)

### Qwen3-Coder-Next
(...)

### Kimi-K2.6
(...)

### MiniMax-M2.5
(...)

### R1-0528
(...)

### Chimera-R1T2
(...)

### Gemini-3.x
(...)

## Convergent findings (>1 model identified)

- Finding X: identified by [models]. REAL/HALLUCINATION classification: ...

## Unique findings (only one model)

- ...

## HALLUCINATION_ECHO findings (re-reporting already-fixed)

These get downweighted in calibration scoring (model failed to
notice fix or didn't read stop-list):
- Model X reported [issue] which was already fixed in ef0a1eb

## Notable model behaviors this session

- Model X timed out / EMPTY / API_ERROR
- Model Y unusual signal-to-noise pattern
- ...

## Architect verdict on F29 ratification

PASS_RATIFIED / FIX-AND-RE-AUDIT / FAIL with reasoning
```

### 4.1 Architect surfaces decision

After ledger drafted, architect makes one of:

- **PASS_RATIFIED** — no architect-verified CRITICAL/HIGH findings
  beyond Codex self-audit fixes → Vladimir merges branch to master
- **FIX-NEEDED** — architect-verified CRITICAL/HIGH found that
  Codex missed → fix on branch, optionally re-audit (1-2 models)
  before merge
- **AMBIGUOUS** — borderline findings that need Vladimir input —
  surface for synchronous decision

---

## 5. Append to calibration log

After classification done, append one record per dispatched model
to `artifacts/calibration/log.jsonl`:

```python
import json
from pathlib import Path

records = [
  {
    "session_id": "2026-05-01-f29-swarm",
    "session_purpose": "F29 Cycle 1 swarm audit (independent verification)",
    "session_date": "2026-05-01",
    "task_class": "narrow_feature_extension",
    "task_subtype": "F29 periodic narrative reports — engine timer + handler + prompts + tests",
    "task_artifact_path": "artifacts/calibration/2026-05-01-f29-swarm/audit-prompt-with-diff.md",
    "model": "<model_id>",
    "verdict": "<PASS|CONDITIONAL|FAIL|EMPTY|TIMEOUT|API_ERROR>",
    "findings_critical": <int>,
    "findings_high": <int>,
    "findings_medium": <int>,
    "findings_low": <int>,
    "real_findings_count": <int>,
    "hallucinated_findings_count": <int>,
    "ambiguous_findings_count": <int>,
    "architect_verification_done": True,
    "latency_s": <float>,
    "tokens_in": None,
    "tokens_out": None,
    "notes": "<free-text behavior observations>"
  },
  # ... per model
]

log_path = Path("artifacts/calibration/log.jsonl")
with log_path.open("a", encoding="utf-8") as f:
    for r in records:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

print(f"Appended {len(records)} records to log.jsonl")
```

For models that returned no usable content (TIMEOUT, EMPTY,
API_ERROR) — still append a record with appropriate verdict
and counts=0. Calibration tracks failures too.

For HALLUCINATION_ECHO findings — count them under
`hallucinated_findings_count` AND add note flag in `notes`:
"NN echo findings re-reporting already-fixed issues from §"Already fixed""

---

## 6. Final report

`artifacts/calibration/2026-05-01-f29-swarm/SUMMARY.md`:

```markdown
# F29 Cycle 1 swarm audit — final report

## Ratification verdict
[PASS_RATIFIED | FIX-NEEDED | AMBIGUOUS]

## Models dispatched

| Model | Latency | Verdict | Real / Halluc / Ambig | Echo |
|---|---|---|---|---|

## New findings (beyond Codex self-audit fixes)
[list architect-verified REAL findings, if any]

## Codex self-audit re-validation
- 2 self-audit findings independently confirmed by [N] of [M] models?
- Or only Codex saw them — calibration data point about Codex
  unique signal

## Calibration data points added
- [N] records appended to log.jsonl
- Highlights for MODEL-PROFILES.md update:
  - GLM-5.1: [behavior summary]
  - Qwen3-Coder-Next: [behavior summary]
  - ...

## Recommendation
- Merge feat/f29-periodic-reports → master? YES/NO/CONDITIONAL
- Re-audit needed? YES/NO
- Outstanding architect decisions: [list]

## Process notes
- CCR vs direct Chutes: [observations]
- Stop-list compliance: [N of M models echoed already-fixed; pattern]
- max_tokens budget: [GLM 8192 worked? other models?]
```

---

## 7. Commit

```bash
git add artifacts/calibration/log.jsonl
git add artifacts/calibration/2026-05-01-f29-swarm/

git commit -m "calibration: F29 swarm audit + log records

Independent multi-model audit of F29 Cycle 1 (commit ef0a1eb,
v0.46.0 tag on feat/f29-periodic-reports branch).

Verifiers dispatched: Codex (fresh), GLM-5.1, Qwen3-Coder-Next,
Kimi-K2.6, MiniMax-M2.5, R1-0528, Chimera-R1T2, Gemini.

Verdict: [PASS_RATIFIED | FIX-NEEDED]
[N] new findings, [M] hallucinations, [P] echo of already-fixed.

Calibration log: [N] records appended. Notable patterns: [...]

Per ORCHESTRATION v1.4 §16.3 (narrow feature scope warrants 2-model
audit; this swarm exceeds requirement for calibration data) and
§17 (calibration log discipline).

Ref: CC_PROMPT_F29_SWARM_AUDIT_2026-05-01.md
Risk: docs only (audit records, no code changes)."
```

If FIX-NEEDED — separate commit on branch with fixes, NOT in
this calibration commit.

---

## 8. Hard stops

- Recon §1 fails on critical item → STOP, surface to architect
- All 7+ models EMPTY/TIMEOUT → unusual, STOP
- 3+ convergent CRITICAL findings architect-verified REAL →
  STOP, fix-up cycle takes priority over calibration record
- max_tokens override script accidentally writes to original
  `run_chutes.sh` → revert immediately from git
- Disk space exhaustion from accumulating audit responses →
  unlikely but check before dispatch

---

## 9. Architect comm-out discipline

Surface immediately:
- After all dispatches return (whether content or failure) →
  architect classifies
- After classification → architect ratifies F29 or requests fix
- If any model produces a CRITICAL finding that looks plausible
  → surface for fast architect verify before completing other
  models

---

## 10. Begin

Per ORCHESTRATION v1.4 §10:
1. Recon (§1)
2. Build audit artifact (§2)
3. Dispatch Wave A (Codex fresh)
4. Dispatch Wave B (Chutes 6 models)
5. Dispatch Wave C (Gemini optional)
6. Wait for completion (15-min cap)
7. Extract responses
8. Surface to architect for classification (§4)
9. After architect classifies → append log records (§5)
10. Final report + commit (§6, §7)

GO.
