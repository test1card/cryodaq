# Metaswarm dispatch — F17 Cold-storage rotation spec

> Three-way parallel design swarm. GLM + Kimi + DeepSeek each produce an
> independent F17 spec. CC synthesizes into final spec for implementation.
>
> Per `.claude/skills/multi-model-consultation.md` §3.5 (three-way parallel)
> and `docs/ORCHESTRATION.md` §4 (consultation protocol).

---

## 0. Mission

CryoDAQ's `data/data_*.db` SQLite files accumulate forever (current 
production behavior). For long-term lab use (months/years) this becomes 
disk-space concern + slow archive query.

F17 (per ROADMAP): SQLite → Parquet cold-storage rotation. Daily 
housekeeping moves SQLite older than N days to Parquet (Zstd), 
delete original after successful Parquet write, replay layer reads 
both (SQLite recent, Parquet archive).

Dependency F1 (Parquet archive UI) — already shipped v0.34.0.

This metaswarm: each model independently designs F17. CC compares + 
synthesizes into one final spec for implementation.

---

## 1. Why three models, not one

Each brings different strengths per `multi-model-consultation.md` §1:

- **GLM-5.1-TEE** — cheap, decent code transforms. Likely produces 
  workable design with clean Python conventions.
- **Kimi-K2.5-TEE** — 256K context window. Will read full CryoDAQ src 
  + ROADMAP + CHANGELOG + relevant docs in one shot, design with full 
  ecosystem awareness.
- **DeepSeek-V3.2-TEE** — strong reasoning + code. Likely catches edge 
  cases (transactional writes, crash recovery, replay query semantics).

CC synthesizes: where designs converge → high confidence shared 
features; where diverge → architect decides; gaps in all three → 
architect adds.

---

## 2. Per-model brief template

Same brief to all three (only model header changes). Each writes to 
its own response file. CC dispatches in parallel.

```markdown
Model: <model_id>

# F17 design brief — SQLite → Parquet cold-storage rotation

## Mission
Design a cold-storage rotation system for CryoDAQ's data layer. 
Output: complete spec document ready for implementation.

## Context files (read all before designing)

Mandatory reads:
- `ROADMAP.md` (esp. F17 entry + F1 entry as dependency)
- `CHANGELOG.md` v0.40.0 + v0.41.0 sections (recent landed features)
- `src/cryodaq/storage/sqlite_writer.py` (current SQLite writer)
- `src/cryodaq/storage/parquet_archive.py` (existing Parquet exporter)
- `src/cryodaq/storage/` directory listing — note all related files
- `docs/ORCHESTRATION.md` v1.2 (governance)
- `config/plugins.yaml` (existing housekeeping config patterns)

Reference reads (skim):
- `src/cryodaq/core/experiment_manager.py` (finalize_experiment hook 
  that writes Parquet today)
- `src/cryodaq/utils/atomic_write.py` (safety pattern for file writes)

## Design questions to answer

### A. Trigger model
- When does rotation run? (cron-like daily, on engine idle, on 
  explicit operator command, all three?)
- Which subsystem owns it? (new HousekeepingService, extend 
  experiment_manager, plugin?)
- How is it disabled / paused (config flag, runtime command)?

### B. Selection logic
- Which SQLite files are eligible? (age threshold? completed 
  experiments only? exclude active session?)
- What's the default age threshold? (30 days? 90 days? configurable?)
- How do we identify "no longer needed in SQLite" (last write 
  timestamp? experiment finalize timestamp? manual mark?)

### C. Atomicity + crash recovery
- What guarantees correct end state if rotation crashes mid-write?
- Does rotation happen in temp file then atomic rename, or directly?
- What happens if Parquet write succeeds but SQLite delete fails?
- How do we detect + recover from a half-finished rotation on next 
  startup?

### D. Storage layout
- Path convention for archived Parquet files? (proposed: 
  `data/archive/year=YYYY/month=MM/<original_db_name>.parquet` 
  but verify per existing patterns)
- Index file or directory traversal for listing archives?
- Compression: Zstd default; configurable level?

### E. Replay query layer
- New API: `query_readings(channels, from_ts, to_ts)` that 
  transparently reads from SQLite + Parquet?
- Or separate APIs that operator selects?
- Performance: how do we keep recent-data queries fast (don't read 
  archived Parquet for queries that don't need it)?
- Schema evolution: what if SQLite schema changes between rotation 
  events? (versioned Parquet files?)

### F. Telemetry + observability
- Logs: what does rotation log on success, failure, skip?
- Metrics: anything emitted to Prometheus/Telegraf style? 
  (CryoDAQ doesn't have those today — design as future-proof)
- Operator-visible: GUI indication that archive exists for old data?

### G. Test coverage
- Minimum test set:
  - Happy path: 30-day-old DB → Parquet → SQLite removed → query 
    reads from archive
  - Error path: Parquet write fails → SQLite preserved
  - Concurrency: rotation runs while engine writes (should rotation 
    skip active DB?)
  - Schema preservation: SQLite types ↔ Parquet types round-trip
  - Replay: query spanning recent + archived data
- Estimated test count?

## Output format

Single markdown document with sections matching A-G above. After A-G:

- **Implementation phases** (3-5 cycles, each ≤300 LOC)
- **Out of scope** (what this design explicitly defers)
- **Open questions for architect** (anything you couldn't resolve)
- **Estimated total LOC + test count**

Hard cap: 4000 words. Code snippets where they clarify (≤30 lines 
each). NO repetition of context files content — assume reader has 
read them.

## Independence note

You are ONE of THREE models designing this independently. CC will 
compare your design to the others. Do NOT try to game agreement; 
write what you actually think is right.

## Response file
Write to: artifacts/consultations/2026-04-29-f17-metaswarm/<model_short>.response.md

Where <model_short> is one of: glm | kimi | deepseek

## Time budget
~30 min wall-clock per model, run in parallel.
```

---

## 3. Dispatch sequence (CC executes)

### 3.1 Setup

```bash
cd ~/Projects/cryodaq
mkdir -p artifacts/consultations/2026-04-29-f17-metaswarm
```

### 3.2 Write per-model briefs

Three files, each a copy of the template above with `<model_id>` 
substituted:

- `artifacts/consultations/2026-04-29-f17-metaswarm/glm.prompt.md`
- `artifacts/consultations/2026-04-29-f17-metaswarm/kimi.prompt.md`
- `artifacts/consultations/2026-04-29-f17-metaswarm/deepseek.prompt.md`

Model IDs (per CCR config):
- GLM: `zai-org/GLM-5.1-TEE`
- Kimi: `moonshotai/Kimi-K2.5-TEE`
- DeepSeek: `deepseek-ai/DeepSeek-V3.2-TEE`

### 3.3 Parallel dispatch via CCR

CCR endpoint: `http://127.0.0.1:3456/v1/messages` (Anthropic-compatible)
or direct OpenAI-compatible at `/v1/chat/completions`.

Per-model dispatch via `curl` (background each one):

```bash
# GLM
nohup curl -s -X POST http://127.0.0.1:3456/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d "$(jq -nR --arg model "zai-org/GLM-5.1-TEE" \
        --arg prompt "$(cat artifacts/consultations/2026-04-29-f17-metaswarm/glm.prompt.md)" \
        '{model: $model, messages: [{role: "user", content: $prompt}], max_tokens: 8000}')" \
  > artifacts/consultations/2026-04-29-f17-metaswarm/glm.response.raw.json 2>&1 &
echo "GLM PID: $!"

# Kimi
nohup curl -s -X POST http://127.0.0.1:3456/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d "$(jq -nR --arg model "moonshotai/Kimi-K2.5-TEE" \
        --arg prompt "$(cat artifacts/consultations/2026-04-29-f17-metaswarm/kimi.prompt.md)" \
        '{model: $model, messages: [{role: "user", content: $prompt}], max_tokens: 8000}')" \
  > artifacts/consultations/2026-04-29-f17-metaswarm/kimi.response.raw.json 2>&1 &
echo "Kimi PID: $!"

# DeepSeek
nohup curl -s -X POST http://127.0.0.1:3456/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d "$(jq -nR --arg model "deepseek-ai/DeepSeek-V3.2-TEE" \
        --arg prompt "$(cat artifacts/consultations/2026-04-29-f17-metaswarm/deepseek.prompt.md)" \
        '{model: $model, messages: [{role: "user", content: $prompt}], max_tokens: 8000}')" \
  > artifacts/consultations/2026-04-29-f17-metaswarm/deepseek.response.raw.json 2>&1 &
echo "DeepSeek PID: $!"
```

### 3.4 Wait

```bash
for i in $(seq 1 15); do
  sleep 60
  G=$([ -s artifacts/consultations/2026-04-29-f17-metaswarm/glm.response.raw.json ] && echo "y" || echo "n")
  K=$([ -s artifacts/consultations/2026-04-29-f17-metaswarm/kimi.response.raw.json ] && echo "y" || echo "n")
  D=$([ -s artifacts/consultations/2026-04-29-f17-metaswarm/deepseek.response.raw.json ] && echo "y" || echo "n")
  echo "minute $i: glm=$G kimi=$K deepseek=$D"
  if [ "$G" = "y" ] && [ "$K" = "y" ] && [ "$D" = "y" ]; then
    sleep 30  # let final writes flush
    break
  fi
done
```

15 min cap. Models on Chutes typically respond in 2-8 min for this 
size of prompt; 15 min is generous buffer.

### 3.5 Parse responses

Each `.response.raw.json` is OpenAI-format chat completion. Extract 
`choices[0].message.content` to clean .response.md:

```bash
for model in glm kimi deepseek; do
  python3 -c "
import json
with open('artifacts/consultations/2026-04-29-f17-metaswarm/${model}.response.raw.json') as f:
    data = json.load(f)
content = data.get('choices', [{}])[0].get('message', {}).get('content', '')
if not content:
    print('ERROR: empty response for ${model}')
    print(json.dumps(data, indent=2)[:500])
else:
    with open('artifacts/consultations/2026-04-29-f17-metaswarm/${model}.response.md', 'w') as f:
        f.write(content)
    print(f'${model}: wrote {len(content)} chars')
"
done
```

### 3.6 Identity verification per skill §5

```bash
tail -100 ~/.claude-code-router/logs/ccr-*.log | grep '"model":"' | sort -u
```

Confirms which models actually responded. Flag any mismatch in 
synthesis.

### 3.7 Read all three responses

CC reads each .response.md fully. Note design decisions per A-G 
sections.

### 3.8 Write synthesis

`artifacts/consultations/2026-04-29-f17-metaswarm/synthesis.md`:

```markdown
# F17 metaswarm synthesis — 2026-04-29

## Models consulted
| Model | Actual ID per CCR log | Response size | One-line take |
|---|---|---|---|
| GLM | <id> | <chars> | <summary> |
| Kimi | <id> | <chars> | <summary> |
| DeepSeek | <id> | <chars> | <summary> |

## Convergent design choices
For each section A-G, list where 2+ models agree:

### A. Trigger model
- All three: <converged choice>
- Divergence: <if any>

### B. Selection logic
- ...

[etc through G]

## Divergent design choices
Where models split badly. CC's reasoning on best path:
- <issue>: GLM says X, Kimi says Y, DeepSeek says Z. CC reasons: ...

## Gaps in all three
What none addressed adequately:
- <gap 1>
- <gap 2>

## CC's recommended F17 spec
[Synthesizes the three into one canonical design. Sections A-G with 
chosen approach + 1-sentence rationale per choice.]

## Implementation phases
[3-5 cycles, each ≤300 LOC, mirroring F3/F10 overnight pattern.]

## Out of scope
[Explicitly deferred items.]

## Open questions for architect
[Anything CC's synthesis couldn't resolve unilaterally.]

## Estimated effort
- LOC: <count>
- New tests: <count>
- Cycles: <count>
- Wall-clock estimate (Sonnet overnight): <hours>
```

### 3.9 Ledger entry

Append to `docs/decisions/2026-04-29-session.md`:

```markdown
## Metaswarm — F17 cold-storage rotation spec

Mission: independent F17 design from GLM + Kimi + DeepSeek-V3.2.
Synthesis: artifacts/consultations/2026-04-29-f17-metaswarm/synthesis.md
Cost estimate: ~$3-8 across three Chutes calls.
Decision: <CC's spec ratified by architect / pending architect review>
Next: <implement F17 per spec, or revise>
```

### 3.10 Final report

CC reports back to architect:

- Models actually invoked (per CCR log)
- Total chars per response (rough cost proxy)
- Synthesis location
- 3 highest-confidence design choices
- 3 divergent points awaiting architect decision
- Whether architect needs to read individual responses or just 
  synthesis is sufficient

---

## 4. Hard stops

- CCR not running → STOP, ask architect to start ccr
- Any single model returns < 1000 chars → STOP, dispatch failed for 
  that model, work with remaining two
- All three return empty → STOP, env issue (auth, quota, network)
- Synthesis cannot resolve fundamental design conflict → STOP, 
  present to architect, do NOT pick arbitrarily
- Identity check shows mismatch (e.g., DeepSeek log shows GLM 
  responded) → STOP, route is misconfigured

---

## 5. After synthesis

If synthesis is solid → CC can use it as F17 implementation spec for 
next overnight runner. Architect may want to review first; default 
posture is architect ratifies before implementation begins.

If gaps remain → escalate to architect with specific questions, 
don't loop the swarm.

If swarm output is poor (all three weak) → fall back to architect 
manually drafting F17 spec, mark this metaswarm as a learning 
exercise (we now know GLM/Kimi/DeepSeek can't do F17-class design 
independently).
