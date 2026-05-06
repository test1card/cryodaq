# Model Calibration Session — 2026-04-30

> Single overnight calibration run. 7 task classes × 8 models = 56
> dispatches. Goal: build empirical calibration matrix showing each
> model's strengths/weaknesses per task class. Output: refined
> routing rules in `multi-model-consultation` skill.

---

## 0. Operating posture

- **Architect asleep** during dispatch. No mid-night chat.
- **Goal: measurement, not output.** This is a controlled experiment —
  the answers themselves are not the deliverable. The deliverable is
  the **calibration matrix** showing which models excel at which
  task classes.
- **8 models per task class.** Codex, Gemini, R1, Qwen3-Coder, GLM,
  Kimi, plus two new probes: TNG Chimera (R1T2-Chimera-TEE) and
  MiniMax-M2.5.
- **7 task classes.** Mix of ground-truth tasks (where correct answer
  is known) and generative tasks (where output quality is graded
  on rubric).
- **Total: 56 dispatches.** Plus 7 task synthesis files + 1 master
  calibration matrix.
- **No artificial token limits.** `max_tokens: 32000` for Chutes API.

---

## 1. Task class specifications

Each class has: a sample task, a scoring rubric, and a ground-truth
reference (where applicable). Models receive **identical prompt**
per task class with model-specific dispatch syntax.

### Class T1 — Bug hypothesis (ground-truth)

**Task:** Given pre-fix B1 ZMQ code (commit before H5 fix) plus a
description of the symptom (REP socket dies after ~50 seconds idle),
identify the root cause.

**Ground truth:** H5 — `asyncio.wait_for(socket.recv(), timeout=1.0)`
cancellation polling pattern accumulates pyzmq reactor state, wedging
the REP socket. Documented in
`docs/decisions/2026-04-27-d4-h5-fix.md`.

**Inline content for prompt:** the pre-fix `_serve_loop()` source
(roughly 30-50 lines). Architect provides via `git show
<pre-H5-commit>:src/cryodaq/core/zmq_bridge.py` extraction in CC's
brief-build phase.

**Rubric (scored 0-3):**
- 0: did not identify cancellation-related issue
- 1: identified cancellation as suspect but wrong specific mechanism
- 2: correct root cause but missed pyzmq-specific reactor state detail
- 3: correctly identified `wait_for(recv())` cancellation pattern as
  root cause + explained pyzmq reactor state accumulation

**Why this class matters:** measures concurrency / asyncio /
subsystem-specific reasoning under uncertainty.

---

### Class T2 — Narrow code review (ground-truth)

**Task:** Review the diff that introduced HF1+HF2 fixes (commit
`189c4b7`). Find any issues.

**Ground truth:** None — the fix is correct as-merged. A model that
fabricates "issues" is hallucinating. A model that confirms PASS or
suggests genuinely valid minor improvements (style, naming) is on
target.

**Inline content:** `git show 189c4b7` diff (~60 LOC).

**Rubric (scored 0-3):**
- 0: invented major bugs that do not exist (HALLUCINATION) OR
  declared the fix broken
- 1: invented minor issues that do not exist
- 2: PASS with no findings, or only style nits
- 3: PASS with one or two genuinely valid minor improvements
  (e.g., test could also assert log output, comment phrasing)

**Why this class matters:** measures hallucination resistance on
narrow scope. Healthy adversarial review should not invent bugs.

---

### Class T3 — Architectural drift detection (ground-truth)

**Task:** Read three files. Find any inconsistency between docstring,
implementation, and tests.

**Files:**
- `src/cryodaq/core/safety_manager.py` (`update_target` method —
  freshly clarified docstring)
- `src/cryodaq/drivers/instruments/keithley_2604b.py` (P=const
  regulation loop)
- `tests/core/test_safety_manager.py` (new test
  `test_update_target_updates_runtime_p_target_immediately`)

**Ground truth:** No inconsistency exists. Docstring says "delayed
update", impl is delayed update, test asserts delayed update. If
model finds an inconsistency — it is hallucinating OR the model
caught a subtle real issue we missed (architect verifies in
synthesis).

**Rubric (scored 0-3):**
- 0: invented major drift that does not exist
- 1: invented minor drift that does not exist
- 2: correctly reports "no drift found"
- 3: correctly reports "no drift" + adds one valid observation
  (e.g., "test name could also cover the warning case")

**Why this class matters:** Gemini's classic strength on paper.
This task class will reveal whether wide-context advantage actually
materializes vs narrow models.

---

### Class T4 — Spec design (generative)

**Task:** Write a spec for F23 (RateEstimator measurement timestamp
fix, ~30 LOC implementation). Spec format: architect's standard
sections (mandate, scope, architecture, implementation,
acceptance, tests, phases).

**No ground truth** — generative output. Scored on rubric for
quality.

**Reference for context:** `CC_PROMPT_F3_ANALYTICS_WIRING.md`
(architect's spec style).

**Rubric (scored 0-3):**
- 0: missing key sections, vague, or did not address F23 scope
- 1: covers basics but lacks acceptance criteria or test plan
- 2: complete spec, adequate but generic (could apply to any small
  fix)
- 3: complete + spec demonstrates deep understanding (notes that
  measurement timestamp comes from `Reading.timestamp` not
  monotonic; references RateEstimator's existing test patterns;
  flags edge cases like clock skew)

**Why this class matters:** measures generative engineering output
quality. Code review is reactive; spec writing is proactive.

---

### Class T5 — Code generation from spec (generative)

**Task:** Implement the `update_target()` SCPI write hypothetically
(do NOT regress the recent fix — this is exploratory: "if you were
to add direct SCPI write while preserving slew-rate limiting, how
would you do it?"). Output as Python diff or full method.

**Reference:** `update_target()` current state, `start_source()`
pattern, slew-rate limiting in `read_channels()`.

**Rubric (scored 0-3):**
- 0: code does not compile / breaks tests / regresses HF1
- 1: compiles but has clear bug (e.g., bypasses slew rate)
- 2: works correctly but does not preserve slew rate limiting
  semantics
- 3: works correctly + preserves all existing safety properties +
  notes the design tradeoff with delayed-update approach

**Why this class matters:** measures code synthesis quality on
realistic safety-critical scope.

---

### Class T6 — Long document digest (generative)

**Task:** Read CHANGELOG.md (covers v0.27.0..v0.42.0, ~30 KB). Write
a 500-word "release notes for stakeholders" suitable for an external
audience (managers, collaborators, not engineers).

**Rubric (scored 0-3):**
- 0: cherry-picks single release, ignores narrative arc
- 1: accurate but list-format, no narrative
- 2: 500-word narrative covering major themes (Phase III UI rebuild,
  B1 closure, F3 analytics, F10 sensor diagnostics, safety hotfixes)
- 3: 500-word narrative + identifies the meta-arc (productionization
  of LabVIEW replacement: bug closure → UI maturation → safety
  hardening) + accessible language

**Why this class matters:** Kimi's classic strength (256K context).
Probes whether long-context advantage translates to better
synthesis.

---

### Class T7 — Math / derivation (generative)

**Task:** Derive uncertainty propagation for the thermal conductance
formula `G = P / (ΔT - ΔT₀)`, where P has uncertainty u(P), ΔT has
u(ΔT), ΔT₀ has u(ΔT₀). Show working. Express u(G) in terms of input
uncertainties using GUM (Guide to Uncertainty in Measurement)
methodology.

**Ground truth:** Standard GUM expansion gives
`u(G)/G = sqrt[(u(P)/P)^2 + (u(ΔT)/ΔT_eff)^2 + (u(ΔT₀)/ΔT_eff)^2]`
where `ΔT_eff = ΔT - ΔT₀`. Cross-correlation terms zero if
inputs independent.

**Rubric (scored 0-3):**
- 0: wrong formula or no derivation shown
- 1: correct relative-uncertainty form but skipped derivation
- 2: correct derivation via partial derivatives, GUM-compliant
- 3: correct derivation + flags edge case (ΔT_eff → 0 makes
  uncertainty diverge) + correlation handling

**Why this class matters:** R1's claimed strength + Kimi's claimed
strength + Codex's actual technical training. Probes math reasoning.

---

## 2. Models tested

8 models in this calibration:

| # | Model | Dispatch path |
|---|---|---|
| 1 | Codex (gpt-5.5 high) | `codex exec` CLI |
| 2 | Gemini 3.1 Pro | `gemini` CLI |
| 3 | DeepSeek-R1-0528 | direct Chutes API |
| 4 | DeepSeek-TNG-Chimera-R1T2 (NEW) | direct Chutes API |
| 5 | Qwen3-Coder-Next | direct Chutes API |
| 6 | GLM-5.1 | direct Chutes API |
| 7 | Kimi-K2.6 | direct Chutes API |
| 8 | MiniMax-M2.5 (NEW) | direct Chutes API |

Chutes model IDs (verified per
`artifacts/2026-04-29-ccr-chutes-recon.md`):
- `deepseek-ai/DeepSeek-R1-0528-TEE`
- `tngtech/DeepSeek-TNG-R1T2-Chimera-TEE`
- `Qwen/Qwen3-Coder-Next-TEE`
- `zai-org/GLM-5.1-TEE`
- `moonshotai/Kimi-K2.6-TEE`
- `MiniMaxAI/MiniMax-M2.5-TEE`

Dispatch via direct Chutes API (CCR is broken without OAuth, per
metaswarm session yesterday). Extract `CHUTES_API_KEY` via
`python3 -c` snippet from `~/.claude-code-router/config.json`
Providers[chutes].api_key.

---

## 3. Execution sequence

### 3.1 Setup

1. `cd ~/Projects/cryodaq && git status`
2. Verify clean master at `35f2798` or later (post-v0.42.0).
3. Extract `CHUTES_API_KEY` to environment.
4. Smoke test 1 Chutes model (Qwen3-Coder, fastest) to verify
   API working.
5. Create artifact tree:
   ```
   artifacts/calibration/2026-04-30/
     T1-bug-hypothesis/
     T2-narrow-review/
     T3-arch-drift/
     T4-spec-design/
     T5-code-gen/
     T6-long-digest/
     T7-math-derivation/
   ```

### 3.2 Brief generation (8 task class × 8 models = 64 brief files,
some shared)

For each task class, write 2 brief variants:
- Codex+Gemini brief (CLI tools, can read files)
- Chutes brief (must inline source content)

Same brief used across the 6 Chutes models for that task class.

Briefs location:
`artifacts/calibration/2026-04-30/<TX>-<slug>/<model>.prompt.md`

### 3.3 Wave dispatch (sequential by task class)

Each task class is one wave. 8 models in parallel per wave.

Wait pattern per wave (12-min cap):
```bash
for i in $(seq 1 12); do
  sleep 60
  RUNNING=$(pgrep -f "codex exec\|gemini -m\|curl.*chat/completions" | wc -l)
  echo "minute $i: running=$RUNNING"
  if [ "$RUNNING" -le 0 ]; then
    echo "Wave complete at minute $i"
    break
  fi
done
```

### 3.4 Per-wave scoring

After each wave completes, CC reads all 8 responses for that task
class and scores per the class's rubric (§1).

Scoring file:
`artifacts/calibration/2026-04-30/<TX>-<slug>/scoring.md`

```markdown
# Task class TX — <name> — scoring

## Ground truth
[exact correct answer if known, OR rubric reference]

## Per-model scores

| Model | Score | Verdict | Notes |
|---|---|---|---|
| Codex | N/3 | [one-word] | [one sentence] |
| Gemini | N/3 | ... | ... |
| R1 | N/3 | ... | ... |
| Chimera | N/3 | ... | ... |
| Qwen3-Coder | N/3 | ... | ... |
| GLM | N/3 | ... | ... |
| Kimi | N/3 | ... | ... |
| MiniMax | N/3 | ... | ... |

## Notable patterns
- Hallucinations observed: list
- Surprising performances: list
- Failure modes: list
```

### 3.5 Master calibration matrix

After all 7 waves done:

`artifacts/calibration/2026-04-30/CALIBRATION-MATRIX.md`

```markdown
# Calibration Matrix — 2026-04-30

## Score matrix (model × task class, 0-3)

|              | T1 bug hyp | T2 narrow rev | T3 arch drift | T4 spec | T5 code gen | T6 long doc | T7 math | AVG |
|--------------|-----------|---------------|---------------|---------|-------------|-------------|---------|-----|
| Codex        | N         | N             | N             | N       | N           | N           | N       | N.NN|
| Gemini       | ...       | ...           | ...           | ...     | ...         | ...         | ...     | ... |
| R1           | ...       | ...           | ...           | ...     | ...         | ...         | ...     | ... |
| Chimera      | ...       | ...           | ...           | ...     | ...         | ...         | ...     | ... |
| Qwen3-Coder  | ...       | ...           | ...           | ...     | ...         | ...         | ...     | ... |
| GLM          | ...       | ...           | ...           | ...     | ...         | ...         | ...     | ... |
| Kimi         | ...       | ...           | ...           | ...     | ...         | ...         | ...     | ... |
| MiniMax      | ...       | ...           | ...           | ...     | ...         | ...         | ...     | ... |

## Strongest model per class
| Class | Winner | Score | Margin over runner-up |
|---|---|---|---|

## Weakest model per class
(skipping if score < 1 — model failed at this class)

## Hallucination rate per model
(across T1-T3 ground-truth classes only)
| Model | Hallucinated tasks (out of 3) |
|---|---|

## Recommendations for routing
- T1 (bug hypothesis): use [winner], avoid [loser]
- T2 (narrow review): use [winner]
- ... per class ...

## Updates needed in multi-model-consultation skill
- Section §2 routing tree changes
- Section §6 budget table updates
- Section §7 anti-pattern additions if any new failure mode
  observed
```

### 3.6 Architect spot-check tasks

CC writes a list of bottom-3 cells per task class to
`artifacts/calibration/2026-04-30/architect-spot-check.md`:

```markdown
# Architect spot-check items

## Cells where CC scored 0 (failure / hallucination)
| Task | Model | CC's score | Verify by reading |
|---|---|---|---|

## Cells where two models disagreed wildly
| Task | High scorer | Low scorer | Where to look |

Architect verifies these manually post-session before committing
calibration matrix as authoritative.
```

---

## 4. Brief templates per task class

### 4.1 T1 — Bug hypothesis (Chutes brief — inline source)

```markdown
# Bug Investigation Challenge

You are reviewing pre-fix Python code from a cryogenic data-acquisition
system. The code uses pyzmq's async socket API to receive ZMQ commands.

**Symptom observed in production:** The REP socket stops responding to
new requests after approximately 50 seconds of idle time. No exception
is raised. Subsequent client requests time out. Restarting the engine
process fixes the issue.

## Source code (pre-fix `_serve_loop`)

```python
[CC inlines git show HEAD~30:src/cryodaq/core/zmq_bridge.py from
the pre-H5-fix commit, specifically the _serve_loop method, ~30-50
LOC]
```

## Question

What is the root cause of the idle-death? Be specific about the
mechanism.

## Output format

- Your hypothesis (1-3 sentences)
- The specific line(s) in the code that cause the issue
- Why this mechanism produces the 50-second-idle symptom
- Suggested fix (in code)

Hard cap 1500 words. No skill-loading prelude.
```

For Codex/Gemini variants: use file paths instead of inlined code.

### 4.2 T2 — Narrow review (Chutes brief)

```markdown
# Code Review

Review the following diff. Find any issues. If the diff is correct
as-is, say PASS.

## Diff

```diff
[CC inlines git show 189c4b7]
```

## Output format

- Verdict: PASS or FAIL
- If FAIL: list issues with severity (CRITICAL/HIGH/MEDIUM/LOW)
- If PASS: optional minor improvement suggestions, max 3

Hard cap 1000 words.
```

### 4.3 T3 — Architectural drift (Chutes brief)

```markdown
# Drift Detection

Read three pieces of code (docstring + implementation + test).
Determine whether they are consistent with each other.

## Docstring (safety_manager.update_target)

```python
[CC inlines current update_target docstring + signature]
```

## Implementation (relevant parts)

```python
[CC inlines update_target body + relevant Keithley read_channels
P=const loop excerpt]
```

## Test

```python
[CC inlines test_update_target_updates_runtime_p_target_immediately]
```

## Question

Is the docstring promise consistent with the implementation
behavior, and does the test actually verify what the docstring
describes?

## Output format

- Verdict: CONSISTENT or DRIFT
- If DRIFT: list specific inconsistencies
- If CONSISTENT: optional one observation, no more

Hard cap 800 words.
```

### 4.4 T4 — Spec design (Chutes brief)

```markdown
# Spec Writing

Write a complete implementation spec for the following feature.
Use the architect's spec format (sections: mandate, scope,
architecture, implementation, acceptance criteria, tests, phases).

## Feature: F23 — RateEstimator measurement timestamp fix

Currently, `SafetyManager._collect_loop` calls
`RateEstimator.push(channel, now, value)` where
`now = time.monotonic()` (queue dequeue time). Under queue backlog,
multiple readings dequeue with similar `now` values, distorting the
computed rate.

Fix: use `reading.timestamp.timestamp()` (the actual measurement
time captured at instrument read).

## Reference materials inlined

```python
[CC inlines RateEstimator.push signature, _collect_loop method,
Reading dataclass with timestamp field]
```

## Output format

Write the full spec. Approximately 100-200 lines of markdown.
Sections: §0 Mandate, §1 Scope, §2 Architecture, §3 Implementation,
§4 Acceptance criteria, §5 Tests, §6 Phases, §7 Hard stops.

Hard cap 3000 words.
```

### 4.5 T5 — Code generation (Chutes brief)

```markdown
# Code Generation Challenge

Implement a hypothetical change to the `update_target()` method
in safety_manager.py. The hypothetical: instead of letting the
P=const regulation loop pick up the new p_target on next poll,
issue a direct SCPI write immediately while preserving the
slew-rate limit (MAX_DELTA_V_PER_STEP = 0.5 V).

This is exploratory — do NOT actually merge this. Show how you
would write it.

## Reference materials

```python
[CC inlines current update_target() body, start_source() body,
read_channels() P=const regulation slew-rate limiting block,
MAX_DELTA_V_PER_STEP constant definition]
```

## Output format

Full method body in Python. Plus 3-5 sentences explaining
design choices and tradeoffs vs the current delayed-update
approach.

Hard cap 1500 words.
```

### 4.6 T6 — Long document digest (Chutes brief)

For models with sufficient context (Kimi 256K, MiniMax 256K+,
Qwen3-Coder 256K, R1 64K, Chimera 64K, GLM 128K), inline full
CHANGELOG.md content. For models with less context, document
truncation in scoring notes.

```markdown
# Release Notes Synthesis

Read the CHANGELOG.md content below (~30 KB covering v0.27.0
through v0.42.0). Write a 500-word "release notes for stakeholders"
document suitable for non-engineers (managers, collaborators).

Identify major themes, the project's narrative arc over these
releases, and what stakeholders should care about.

## CHANGELOG content

```markdown
[CC inlines full CHANGELOG.md]
```

## Output format

500 words, narrative paragraphs (not bullet lists). Accessible
language. Group by themes, not by version.

Hard cap exactly 500 words.
```

### 4.7 T7 — Math derivation (Chutes brief)

```markdown
# Uncertainty Propagation Derivation

Derive the propagation of measurement uncertainties for the
thermal conductance formula:

    G = P / (ΔT - ΔT₀)

where P is heater power, ΔT is the measured temperature
difference across the sample, and ΔT₀ is a calibration offset.

Each input has its own standard uncertainty:
- u(P) for power
- u(ΔT) for temperature difference
- u(ΔT₀) for calibration offset

Assume inputs are uncorrelated.

## Output format

1. State the formula for u(G) in terms of input uncertainties.
2. Show the derivation step-by-step using GUM (Guide to
   Uncertainty in Measurement) methodology with partial
   derivatives.
3. Express the result as relative uncertainty u(G)/|G|.
4. Note any edge cases (e.g., when ΔT - ΔT₀ approaches zero).

Hard cap 2000 words. Plain text math notation OK
(use ^, /, * symbols).
```

---

## 5. Dispatch syntax (verified yesterday)

### 5.1 Codex

```bash
nohup codex exec -m gpt-5.5 -c model_reasoning_effort="high" \
  --sandbox none --skip-git-repo-check \
  --cd ~/Projects/cryodaq \
  < <prompt_file> \
  > <response_file> 2>&1 &
```

Note: `--sandbox none` instead of `--sandbox read-only` because
yesterday's metaswarm Codex Task B was EMPTY due to read-only
sandbox blocking stdout. `none` lets stdout-only output reach
the response file.

### 5.2 Gemini

```bash
nohup gemini -m gemini-3.1-pro-preview --yolo \
  -p "$(cat <prompt_file>)" \
  > <response_file> 2>&1 &
```

If quota exhausted: mark QUOTA_EXHAUSTED, no retry.

### 5.3 Chutes (R1 / Chimera / Qwen3-Coder / GLM / Kimi / MiniMax)

```bash
nohup curl -s https://llm.chutes.ai/v1/chat/completions \
  -H "Authorization: Bearer $CHUTES_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "<chutes-model-id>",
    "messages": [{"role": "user", "content": "<full-brief-content>"}],
    "max_tokens": 32000
  }' > <raw-response-json> 2>&1 &
```

After dispatch, extract content with:
```bash
python3 -c "
import json
with open('<raw-response-json>') as f:
    data = json.load(f)
print(data['choices'][0]['message']['content'])
" > <response.md>
```

If model returns 401/403/429 OR `Infrastructure at maximum
capacity`: mark FAILED, no retry within this session.

---

## 6. Failure modes

### 6.1 Model API down

- R1 was down all of yesterday's session. May be back today, may
  not. If FAIL on first dispatch: mark and skip remaining waves
  for that model.
- Chimera and MiniMax are NEW probes — may have setup issues. If
  401/404 on first dispatch: model not in user's plan, mark FAILED,
  document.

### 6.2 Gemini quota

Likely exhausted on first 1-2 waves. Retry on later waves. If
exhausted entire session: matrix has Gemini row partially empty.

### 6.3 Codex 5h window

Exhausted = all 7 task classes return same WINDOW_EXHAUSTED. Less
likely than yesterday because budget refresh window crossed
midnight.

### 6.4 Kimi parse error on large prompts

Yesterday Kimi PARSE_ERROR on 375KB prompts. T6 (CHANGELOG digest)
prompt is large. If Kimi PARSE_ERROR on T6: document, score 0
for T6 but allow Kimi to participate in other waves.

### 6.5 Chutes infrastructure capacity

Chutes shows "Infrastructure at maximum capacity" intermittently.
Per spec §6.1: no retry within this session. Document.

### 6.6 Scoring ambiguity

If CC cannot confidently score a response (rubric edge case): score
1.5 (mid) and add to architect-spot-check.md for manual review.

---

## 7. Hard stops

- All 8 models fail in Wave 1 (T1) → STOP, environment broken
- Test infrastructure broken on master → STOP, drift since v0.42.0
- Disk full / OOM → STOP

A single model failure does NOT stop the wave. A single wave
failure does NOT stop the night.

---

## 8. Architect comm-out discipline

- Sonnet does not see chat. All decisions to handoff with
  "ARCHITECT DECISION NEEDED" markers.
- Safest interpretation rules: ambiguous rubric → score mid (1.5),
  flag for review. Spec deviation needed → take simpler path,
  document.

---

## 9. Final report shape

`artifacts/calibration/2026-04-30/MASTER-SUMMARY.md`:

```markdown
# Calibration Master Summary

## Configuration
- 7 task classes × 8 models = 56 dispatch slots
- Successful dispatches: N / 56
- Wall clock: <duration>
- Date: 2026-04-30

## Scoring matrix
[reference to CALIBRATION-MATRIX.md]

## Headline findings
- Best general-purpose model: <name> (avg <N>/3)
- Most reliable adversarial reviewer: <name>
- Best at math: <name>
- Best at long-context: <name>
- Highest hallucination rate: <name>
- Most surprising performance: <name>

## Skill update needed
- Update multi-model-consultation.md §2 routing tree:
  [specific changes]

## Architect morning queue
1. Read this summary
2. Review architect-spot-check.md
3. Verify bottom-cells if any are surprising
4. Approve calibration matrix as authoritative
5. Apply skill update

## Outstanding
- [model that failed entirely]
- [task class with low scoring confidence]
- [novel failure modes encountered]
```

---

## 10. Begin

Start NOW. Phase 3.1 setup first. Read this whole spec.

GO.
