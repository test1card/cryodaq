# Metaswarm 2026-04-29 — 4 tasks × 6 models

> Single overnight metaswarm dispatch. 24 model invocations across 4 
> independent tasks. CC synthesizes per-task in morning. Architect 
> reviews master summary.

---

## 0. Operating posture

- **Architect asleep** during dispatch. No mid-night chat.
- **Burn quota deliberately.** Goal: extract value from paid Chutes 
  subscription + Codex window + Gemini quota. No conservation.
- **Six models per task.** Codex, Gemini, DeepSeek-R1-0528, 
  Qwen3-Coder-Next, GLM-5.1, Kimi-K2.6.
- **Four tasks A/B/D/F.** Each gets all six models independently.
- **Total: 24 dispatches.** Plus 4 synthesis files + 1 master summary.
- **No artificial token limits.** Use `max_tokens: 32000` for Chutes 
  API requests (cap high enough that models hit natural stop 
  conditions, not truncation). Codex / Gemini CLIs use their own 
  defaults — do not impose lower caps. The "hard cap N words" hints 
  in brief templates are SUGGESTIONS to the model about preferred 
  response density, not hard truncation. Prefer complete reasoning 
  over arbitrary length cuts.

---

## 1. Task definitions

### Task A — Architectural blind spots audit

**Question:** "What is wrong or missing in CryoDAQ that the regular 
Codex+Gemini audit cycle has not surfaced? Where are the blind spots?"

**Scope (read these only):**
- `src/cryodaq/core/engine.py` (84 KB — large, but central)
- `src/cryodaq/core/safety_manager.py`
- `src/cryodaq/core/alarm_v2.py`
- `src/cryodaq/core/interlock.py`
- `src/cryodaq/core/sensor_diagnostics.py`
- `src/cryodaq/core/scheduler.py`
- `src/cryodaq/core/broker.py`
- `src/cryodaq/core/zmq_bridge.py`
- `src/cryodaq/storage/sqlite_writer.py`
- `src/cryodaq/storage/parquet_archive.py`
- `src/cryodaq/drivers/lakeshore_218s.py`
- `src/cryodaq/drivers/keithley_2604b.py`
- `src/cryodaq/drivers/thyracont_vsp63d.py`
- `ROADMAP.md` (current state)
- `CHANGELOG.md` [0.41.0] entry (most recent)

**Out of scope:**
- GUI (already shipped, not in scope for this audit)
- Tests (out of scope — we want production code blind spots)
- Web (separate subsystem, not focus)

**Output format requested:**
- Top 5-7 blind spots, ranked by severity
- Per blind spot: name + file:line refs + 2-3 sentence explanation 
  + suggested mitigation
- One-paragraph "what surprised me reading this codebase"

**Brief template path:** `artifacts/consultations/2026-04-29-metaswarm/A-blindspots/<model>.prompt.md`

### Task B — F17 (cold rotation) spec design

**Question:** "Design a specification for F17: SQLite → Parquet 
cold-storage rotation, following the architect's spec style."

**Reference spec style:** `CC_PROMPT_F3_ANALYTICS_WIRING.md` (recent 
F3 spec — same format expected for F17).

**Scope (read these):**
- `ROADMAP.md` F17 entry (defines feature contract)
- `src/cryodaq/storage/sqlite_writer.py` (current write path)
- `src/cryodaq/storage/parquet_archive.py` (existing per-experiment 
  parquet export — the F1 dependency)
- `src/cryodaq/core/experiment_manager.py` (finalize_experiment hook 
  pattern)
- `src/cryodaq/core/engine.py` (housekeeping service location — search 
  for existing housekeeping pattern)

**Required spec sections (architect format):**
- §0 Mandate
- §1 Scope (in / out)
- §2 Architecture (current state + target wiring)
- §3 Implementation details (per-component)
- §4 Acceptance criteria (numbered list)
- §5 Test coverage requirements
- §6 Implementation phases (cycle breakdown)
- §7 Hard stops
- §8 Spec deviations encouraged
- §9 End

**Constraints:**
- Must respect existing SQLite WAL mode + March 2026 corruption bug warning
- Must allow operator emergency restore from Parquet (read-only access)
- Layout `data/archive/year=YYYY/month=MM/` per ROADMAP F17 hint
- Original SQLite deleted ONLY after successful Parquet write 
  (atomicity)
- Replay service reads both SQLite (recent) and Parquet (archive)

**Brief template path:** `artifacts/consultations/2026-04-29-metaswarm/B-f17-spec/<model>.prompt.md`

### Task D — Independent re-implementation of `_serve_loop`

**Question:** "Implement `_serve_loop()` for `ZMQCommandServer` from 
scratch, given the test suite. Must pass all existing tests + add one 
new test for B1 regression."

**Scope (read these):**
- `src/cryodaq/core/zmq_bridge.py` — focus on `ZMQCommandServer` class, 
  particularly `_serve_loop()` method (current impl uses 
  `poll(timeout=1000) + conditional recv()` pattern post-H5 fix)
- `tests/core/test_zmq_bridge.py` (or whatever test file covers 
  ZMQCommandServer — find it)
- `docs/decisions/2026-04-27-d4-h5-fix.md` (B1 root cause)
- `docs/bug_B1_zmq_idle_death_handoff.md` (full B1 history)

**Output requested:**
- Complete `_serve_loop()` implementation as code block (full method, 
  not diff)
- Full helper methods if needed
- One new test case verifying no idle-death after 50+ seconds 
  with no traffic
- Brief explanation of design choices and why this impl is correct

**Constraints:**
- Must NOT use `asyncio.wait_for(socket.recv(), timeout)` cancellation 
  polling (this was the B1 root cause)
- Must support clean shutdown within 1 second of `_running = False`
- Must handle ZMQ errors gracefully (log + continue, don't crash loop)
- Must use pyzmq async Socket API

**Brief template path:** `artifacts/consultations/2026-04-29-metaswarm/D-serve-loop/<model>.prompt.md`

### Task F — Missing-feature ideation (engineer persona)

**Persona prompt:** "You are a senior cryogenic test engineer with 
15-20 years of experience working with cryostat instrumentation in a 
research lab. You have inherited the CryoDAQ system and have been 
using it daily for 3 months. You have replaced an older LabVIEW VI 
with this Python stack. You know the strengths and weaknesses of the 
LabVIEW system you replaced."

**Question:** "What ONE feature would you want added to CryoDAQ 
tomorrow that is currently missing? Be specific. Provide concrete 
acceptance criteria. The feature must be addressable in <500 LOC 
within 1-2 weeks of work."

**Scope (read these):**
- `README.md` (project overview)
- `ROADMAP.md` (current feature backlog F1-F20)
- `CHANGELOG.md` (what's been built)

**Output requested:**
- 3-5 distinct feature proposals (not just one — the persona answers 
  ONE, but model gives several variants for comparison)
- Per proposal:
  - Name
  - One-paragraph description (the feature in operator's words)
  - Concrete acceptance criteria (3-5 items)
  - Estimated LOC + effort
  - Why this is missing today (gap analysis)
  - Comparison: would this exist in a similar LabVIEW VI? Yes / No / 
    Partial.

**Brief template path:** `artifacts/consultations/2026-04-29-metaswarm/F-missing-features/<model>.prompt.md`

---

## 2. Six models per task

For each task, dispatch all six:

| Slot | Model | Dispatch method |
|---|---|---|
| 1 | gpt-5.5 (Codex) | `codex exec` CLI as before |
| 2 | gemini-3.1-pro-preview (Gemini) | `gemini` CLI as before |
| 3 | DeepSeek-R1-0528-TEE | curl to `localhost:3456` via CCR `think` route |
| 4 | Qwen3-Coder-Next-TEE | curl to CCR `coder` route |
| 5 | GLM-5.1-TEE | curl to CCR `default` route |
| 6 | Kimi-K2.6-TEE | curl to CCR `longContext` route |

### CCR dispatch syntax

CC must figure out actual CCR invocation pattern for `localhost:3456`. 
Options to try in order:

```bash
# Attempt 1 — model alias suffix
curl -s http://localhost:3456/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-sonnet-4-5,think",
    "messages": [{"role": "user", "content": "<brief>"}],
    "max_tokens": 32000
    }' > <response_file>

# Attempt 2 — direct route name
curl -s http://localhost:3456/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "think",
    ...
  }'

# Attempt 3 — header-based routing
curl -s http://localhost:3456/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-CCR-Route: think" \
  -d '{"model": "claude-sonnet-4-5", ...}'
```

CC should test ONE small request first (e.g. "reply 'OK' and stop") 
to confirm dispatch syntax works for ONE route. Once confirmed, that 
syntax applies to all 4 CCR routes.

If CCR returns "Provider 'undefined' not found" — same caveat as 
Phase 2 smoke test (needs Claude OAuth). Workaround: use the actual 
Chutes API directly:

```bash
# Direct Chutes API (bypasses CCR)
curl -s https://llm.chutes.ai/v1/chat/completions \
  -H "Authorization: Bearer $CHUTES_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-ai/DeepSeek-R1-0528-TEE",
    "messages": [{"role": "user", "content": "<brief>"}],
    "max_tokens": 32000
  }' > <response_file>
```

Use whichever works. If neither — STOP that model's track and 
report. Other 5 models continue.

### Codex dispatch (existing pattern)

```bash
nohup codex exec -m gpt-5.5 -c model_reasoning_effort="high" \
  --sandbox read-only --skip-git-repo-check \
  --cd ~/Projects/cryodaq \
  < <prompt_file> \
  > <response_file> 2>&1 &
```

### Gemini dispatch (existing pattern)

```bash
nohup gemini -m gemini-3.1-pro-preview --yolo \
  -p "$(cat <prompt_file>)" \
  > <response_file> 2>&1 &
```

If Gemini quota exhausted (likely): mark "QUOTA_EXHAUSTED" in 
synthesis, no retry.

---

## 3. Execution sequence

### 3.1 Setup
1. Verify clean master, fetch origin
2. Create artifact directories:
   ```
   artifacts/consultations/2026-04-29-metaswarm/A-blindspots/
   artifacts/consultations/2026-04-29-metaswarm/B-f17-spec/
   artifacts/consultations/2026-04-29-metaswarm/D-serve-loop/
   artifacts/consultations/2026-04-29-metaswarm/F-missing-features/
   ```

### 3.2 Brief writing (24 prompts)
For each task × model combo, write a brief file. Briefs are mostly 
identical per-task with model-specific intro line. Use the brief 
templates in §4 below.

### 3.3 CCR syntax validation
Quick smoke test on ONE Chutes model (recommend GLM as cheapest) to 
confirm dispatch syntax works. If fails on CCR: pivot to direct Chutes 
API. Document working syntax in `artifacts/consultations/2026-04-29-metaswarm/dispatch-syntax.md`.

### 3.4 Wave dispatch

**Wave 1: Task A (6 models in parallel)**
Dispatch all 6, wait until done (12-min cap), proceed.

**Wave 2: Task B (6 models in parallel)**
Same pattern.

**Wave 3: Task D (6 models in parallel)**
Same pattern.

**Wave 4: Task F (6 models in parallel)**
Same pattern.

Why sequential waves not 24-parallel: each wave's 6 models share 
context (same files), so CC's own bash background job count stays 
manageable. 6 parallel curls is fine; 24 parallel may overwhelm 
CCR or Codex.

### 3.5 Wait pattern (per wave)

```bash
for i in $(seq 1 12); do
  sleep 60
  # Count running dispatch processes for THIS wave
  RUNNING=$(pgrep -f "codex exec\|gemini -m\|curl.*chat/completions" | wc -l)
  echo "minute $i: running=$RUNNING"
  if [ "$RUNNING" -le 0 ]; then
    echo "Wave complete at minute $i"
    break
  fi
done
```

If 12-min cap hit with stragglers: kill, work with partial.

### 3.6 Per-wave synthesis

After each wave completes, write synthesis BEFORE starting next wave.

Synthesis path: `artifacts/consultations/2026-04-29-metaswarm/<task>/synthesis.md`

Synthesis template at §5.

### 3.7 Master summary

After all 4 waves done, write:
`artifacts/handoffs/2026-04-29-metaswarm-summary.md`

Master summary template at §6.

---

## 4. Brief templates

### 4.1 Task A — Codex variant

```markdown
Model: gpt-5.5
Reasoning effort: high

# Architectural blind spots audit — CryoDAQ

## Mission
Audit production code for blind spots that the regular Codex+Gemini 
audit cycle has not surfaced. Find what is wrong or missing.

## Read scope
[file paths from §1 Task A]

## Out of scope
GUI, tests, web subsystem.

## Required output
- Top 5-7 blind spots ranked by severity
- Per blind spot: name + file:line refs + 2-3 sentence 
  explanation + suggested mitigation
- One paragraph "what surprised me reading this codebase"

## Severity scale
CRITICAL / HIGH / MEDIUM / LOW

## Output format
Markdown sections per blind spot. Hard cap 3000 words. NO 
skill-loading prelude.

## Response file
artifacts/consultations/2026-04-29-metaswarm/A-blindspots/codex.response.md
```

### 4.2 Task A — Gemini variant

```markdown
Model: gemini-3.1-pro-preview

# Architectural blind spots audit — CryoDAQ

## Mission
Wide-context structural audit. Find blind spots in production code 
that narrow Codex audits would miss.

[same scope as Codex]

## Output
Single markdown table:
| # | Severity | File | Issue | Suggested mitigation |

After table: "what surprised me" paragraph.

Hard cap 2000 words. Table-first.

## Response file
artifacts/consultations/2026-04-29-metaswarm/A-blindspots/gemini.response.md
```

### 4.3 Task A — Chutes models variant (R1, Qwen-Coder, GLM, Kimi)

Use one shared template, dispatch via curl. Response files are 
embedded in CCR/Chutes JSON response — extract the `choices[0].message.content` 
field.

```markdown
# Architectural blind spots audit — CryoDAQ

You are auditing production Python code for an open-source cryogenic 
laboratory data acquisition system. Goal: find blind spots in the 
architecture that would survive a normal targeted code review.

[read scope listed inline — CC must paste source code into the 
prompt because Chutes models can't read files; this is a critical 
mechanical difference vs Codex/Gemini CLI]

OR alternative: send the source directly inline in the prompt. For 
large files, send only the file's docstrings + class/function signatures 
+ key methods. CC decides how much to inline based on each model's 
context window:
- R1: 64K context, send key methods only
- Qwen3-Coder: 256K, can send most files
- GLM: 128K, send key methods only
- Kimi: 256K, can send most files

## Required output
Top 5-7 blind spots ranked by severity. Per blind spot: name, file 
reference (no line refs since model didn't see line numbers), 
2-3 sentences explanation, suggested mitigation.

Hard cap 2000 words.
```

CC dispatches via curl, captures response, saves the `content` field 
to `artifacts/consultations/2026-04-29-metaswarm/A-blindspots/<model>.response.md`.

### 4.4 Tasks B, D, F briefs

Adapt §4.1-4.3 templates with task-specific scope and required outputs 
from §1. Same dispatch pattern.

For Task D (re-implementation), models need the test suite content 
inlined since they're writing code that must pass tests. Bundle 
test file content into the brief.

For Task F (persona), include the engineer persona statement as 
system role / first message.

---

## 5. Per-wave synthesis template

```markdown
# Task <X> synthesis — <task name>

## Models consulted
| Model | Status | Response length | Notes |
|---|---|---|---|
| Codex (gpt-5.5) | OK / FAILED / EMPTY | N tokens | ... |
| Gemini | OK / QUOTA / FAILED | N tokens | ... |
| DeepSeek-R1-0528 | ... | ... | ... |
| Qwen3-Coder-Next | ... | ... | ... |
| GLM-5.1 | ... | ... | ... |
| Kimi-K2.6 | ... | ... | ... |

## Convergent findings
What did 3+ models flag as the same issue / propose the same design / 
suggest the same feature?

| Finding | Source models | Severity / Priority |

## Divergent findings
Where do models disagree? What unique perspective did each contribute?

## Best individual contribution per model
Which response had the most actionable single insight, even if 
others didn't echo it?

## CC's pre-assessment
- Top 3 takeaways for architect
- Disputed claims requiring architect judgment
- Anything CC would reject outright

## Architect decisions needed
- ...
```

---

## 6. Master summary template

```markdown
# Metaswarm 2026-04-29 — Master Summary

## Configuration
- 4 tasks: A (blind spots), B (F17 spec), D (_serve_loop reimpl), F (missing features)
- 6 models per task: Codex, Gemini, R1, Qwen3-Coder, GLM, Kimi
- Total dispatches: 24 (or N if some failed/skipped)
- Wall clock: <duration>

## Per-task summary
[four sections, one per task, with synthesis pointer + 1-paragraph 
summary]

## Total work
- Dispatches successful: <count> / 24
- Synthesis files: 4
- Tokens consumed: <rough estimate>

## Cherry-pick recommendations
- Task A: [top blind spot architect should address first]
- Task B: [which F17 spec is best — name model + key strengths, plus 
  what to merge from runners-up]
- Task D: [is any reimpl better than current `poll+recv`? If yes, 
  which and why]
- Task F: [top 3 feature ideas to add to ROADMAP F21+]

## Architect morning queue
1. Read this summary
2. Read per-task synthesis
3. Decide which actionable items to ROADMAP/implement next
4. Tag review burned models for future use cases

## Outstanding
- Any model that failed entirely
- Any task that didn't converge in synthesis

## Files
- artifacts/consultations/2026-04-29-metaswarm/A-blindspots/synthesis.md
- artifacts/consultations/2026-04-29-metaswarm/B-f17-spec/synthesis.md
- artifacts/consultations/2026-04-29-metaswarm/D-serve-loop/synthesis.md
- artifacts/consultations/2026-04-29-metaswarm/F-missing-features/synthesis.md
- artifacts/handoffs/2026-04-29-metaswarm-summary.md (this file)
```

---

## 7. Failure modes

### 7.1 CCR dispatch fails entirely
Pivot to direct Chutes API with `$CHUTES_API_KEY`. If both fail: 
mark all 4 Chutes models as DISPATCH_FAILED, continue with Codex + 
Gemini only.

### 7.2 Gemini quota exhausted
Likely. Mark QUOTA_EXHAUSTED, no retry.

### 7.3 Codex 5-hour window exhausted
Possible if Codex was used heavily today. Mark WINDOW_EXHAUSTED, 
proceed with rest. Synthesis notes Codex absence.

### 7.4 One Chutes model returns 401/403
Model not in user's plan. Skip.

### 7.5 Response > expected size (Codex skill-loading prelude)
Use `tail -300` or grep for last verdict marker.

### 7.6 Response < 200 bytes (truncated/error)
Mark FAILED, proceed.

### 7.7 Synthesis ambiguous
Write what's clear. Mark "ARCHITECT DECISION NEEDED" for unclear 
parts. Do not invent consensus.

### 7.8 Master summary written but a wave incomplete
Note status in summary. Don't claim completion if not complete.

---

## 8. Hard stops

- Network down (cannot reach localhost:3456 OR llm.chutes.ai OR 
  Codex CLI doesn't exist) → STOP, report
- Disk full → STOP
- All 6 models fail in Wave 1 (Task A) → STOP, environment broken

A single model failure does NOT stop the wave. A single wave failure 
does NOT stop the night.

---

## 9. Begin

Start NOW. Phase 3.1 setup first. Read this whole prompt before 
dispatching anything.

GO.
