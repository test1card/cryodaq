---
name: multi-model-consultation
description: "Use when CC needs to consult external AI models (Codex CLI, Gemini CLI, GLM-5.1, Kimi K2.6, DeepSeek-R1-0528, Qwen3-Coder-Next) for review, audit, draft, or second opinion on CryoDAQ work. Routes the task to the right model based on its strengths, produces a synthesis artifact that becomes the durable record, follows docs/ORCHESTRATION.md §4 protocol. Invoke whenever architect says 'get a review from', 'ask Codex', 'ask Gemini', 'run swarm', 'second opinion', 'adversarial review', 'cross-check with another model', or CC itself encounters a decision where its own confidence is low and architect is unavailable. Covers routing decision, budget discipline, identity-leak gotchas, formation patterns (single / writer-reviewer / adversarial pair / wide audit / three-model code review), brief templates, synthesis format, and anti-patterns learned from 2026-04-21..23 failed swarm cycle."
---

# Multi-model consultation — CC as conductor, not soloist

## 0. When NOT to use this skill

Most of the time, don't. CC should try its own reasoning first. External
consultation is expensive (token budget, wall-clock, synthesis overhead)
and injects noise that still has to be filtered. The 2026-04-21..23
swarm cycle that produced 12 untracked review markdowns in repo root +
two parallel duplicate branches happened because **consultation became
reflex**, not judgment.

Skip consultation when:

- The task is mechanical (rename files, apply architect-spec'd patch,
  gitignore pattern edit)
- CC's own reasoning produces a single clear answer and architect's
  plan is complete
- The question is scoped so narrowly a single-model answer is trivially
  verifiable by running a test
- Budget is tight and architect is available for direct guidance

Use consultation only when all three of these hold:

1. The decision has meaningful downside cost if wrong (safety code,
   architectural change, irreversible migration, production hardware
   behavior, branch merge decision)
2. CC's own reasoning is not confident (competing hypotheses, missing
   domain knowledge, non-obvious tradeoff)
3. Either architect is available but has explicitly asked for a model
   cross-check, or architect is not available and the task cannot wait

## 1. Why four models — what each actually offers

Claude, Codex, Gemini, GLM, Kimi, DeepSeek-R1, and Qwen3-Coder are
NOT interchangeable. Each has a real niche. Using the wrong model is
not just wasteful — it actively produces worse output than no
consultation.

### Codex CLI — gpt-5.5 high reasoning

**Strength:** narrow adversarial code review. Step-by-step reasoning on
concurrency, race conditions, IPC, subprocess lifecycle, socket state
machines, specific bug hunts in a diff. Will cite `file:line` references
without being told. Writes terse critiques that skip filler.

**Weakness:** holistic architecture vision. Tends to see trees not
forest. Long context (> ~50K tokens) degrades. Prose-heavy reports
(strategy docs, vision statements) are not Codex's format — it produces
bullet lists and verdicts instead.

**Always pass:** `--model gpt-5.5 --reasoning high` as flags AND
`Model: gpt-5.5 / Reasoning effort: high` as first two lines of prompt
body. Default `o3` is weak for this workflow.

**Version note:** GPT-5.5 released post 2026-04-24. Prior to that release
we used gpt-5.4. When CC reads this skill and the date is later than
2026-04-24, use gpt-5.5. If architect references a newer version,
architect wins — update this skill accordingly.

**Signature signal:** verdict headers like "FAIL / PASS / CONDITIONAL",
numbered findings with file:line, short reasoning per finding.

**Budget:** ChatGPT Plus subscription, 5-hour rolling window. Plan
for ~3-5 substantial reviews per day. Background jobs eat the window
fast — use `/codex:review` foreground unless you genuinely need
parallelism.

**Sandbox gotcha (2026-04-24 observed):** Codex CLI defaults to
read-only filesystem sandbox and will emit
`patch rejected: writing is blocked by read-only sandbox` when asked
to write the response file itself. Two workarounds:
1. Invoke with `--sandbox workspace-write` flag so Codex can write
   directly to the response path.
2. Let Codex print response to stdout and have CC redirect the
   stdout to the response file: `codex exec ... > RESPONSES/....md`.
Option 2 is the proven path for overnight batches since CC adapted
to it 2026-04-24.

**Response size gotcha:** Codex returns full reasoning transcript
(100-300 KB typical). Final verdict + findings are at the END of
the response file, not the top. When synthesizing: use `tail -250`
or parse for the last `Model: gpt-5.X` marker. Codex tends to
repeat its final answer after the transcript, so the bottom is
the authoritative section.

**Use for:**
- Review of a completed diff before commit (adversarial review)
- Specific bug hypothesis testing ("is this a race or a deadlock?")
- Concurrency-heavy code (ZMQ, asyncio, subprocess)
- Short audit of a single file or small diff (≤ 500 lines)

**Do NOT use for:**
- Long-prose strategy writing
- "Review the entire repo"
- Anything that requires loading > 10 files at once

### Gemini CLI — Gemini 3.1 Pro Preview

**Strength:** wide-context architectural analysis. 1M token window lets
you drop the entire CryoDAQ src tree into one prompt and ask
cross-cutting questions. Strong on multi-file drift detection, impact
analysis, doc-vs-code reconciliation, finding patterns across many
files. 3.1 Pro improved long-horizon stability + tool orchestration
over 2.5 Pro (Feb 2026 release), scores Artificial Analysis Intelligence
Index 57 (top in class at release). Three-tier thinking modes (low /
medium / high) added.

**Weakness:** verbosity. Default response size is 3-10x what you asked
for. Needs explicit "maximum 800 words" or "single markdown table, no
prose". Can be confidently wrong on narrow hot-path bugs that Codex
would catch. Architect voice — tends toward summary statements over
specific findings without line refs. Higher time-to-first-token than
2.5 Pro (~30s) — noticeable for interactive use, irrelevant for
background batches.

**Always pass:** `-m gemini-3.1-pro-preview` (full model string
required — plain `pro` may resolve to 2.5 on older CLI installs, and
`--model pro` defaults to auto-routing which can include flash). For
audits → `--background` or `--yolo` if tool approval would block.

**Version note:** Gemini 3.1 Pro Preview released 2026-02-19. Previous
was Gemini 2.5 Pro. Auto-route is now Gemini 3 family by default on
recent Gemini CLI. Older `gemini-2.5-pro` endpoint still works but is
strictly worse; no reason to prefer it.

**Signature signal:** section-headed reports with tables, high-level
recommendations. Watch for confident claims without file:line backing —
those are often hallucinated.

**Budget:** Google AI Pro — daily quota via OAuth (consumer Gemini app
limits apply; CLI shows limit-reached banner when hit). Individual deep
audit counts as 1 request but may take 60-90 min of wall-clock.

**Use for:**
- Wide audit ("find architectural drift across the whole engine")
- Doc-vs-code reconciliation over many files
- Second opinion on architecture decisions where Codex is too narrow
- Loading entire specs + entire source tree at once

**Do NOT use for:**
- Short-scope bug review (use Codex)
- Anything where you need < 500-word output (Gemini will overwrite)
- Quick yes/no decisions

### GLM-5.1 — Zhipu AI via Chutes

**Strength:** cheap per token. OK on routine code transformations,
translation RU/EN/ZH, baseline question-answering. Fine for bulk
mechanical work where a second cheap opinion is nice but not
load-bearing.

**Weakness:** three specific ones.
1. **Identity leakage** — trained partly on Claude outputs; will claim
   "I am Claude" on introspection. Do not trust any self-identification.
   Authority on what model responded: `tail ~/.claude-code-router/logs/ccr-*.log | grep '"model":"'`.
2. **Falls apart at scale** — 50+ file contexts, complex multi-step
   reasoning, or sophisticated concurrency bugs — output becomes
   plausible word salad. Hypotheses about B1-class bugs were wrong
   last week.
3. **Hallucinates with confidence** — when asked about things it
   doesn't know, generates fluent false detail instead of saying
   "unknown".

**Budget:** Chutes pay-as-you-go, very cheap (~$1-3 per full session,
$0.5 per typical code transform).

**Use for:**
- Translation RU↔EN of technical text
- Draft of mechanical code transformation CC will then verify
  itself before commit
- Batch rename / rewrite where failures are trivially detectable
  (tests catch them)
- Cheap second opinion to check one specific claim — verify its
  answer against another source if it matters

**Do NOT use for:**
- Anything safety-critical
- Any decision that would land unchecked on master
- Anything where "sounds plausible" matters more than correctness
- Primary coordinator (this is CC's role, always)

### Kimi K2.6 — Moonshot AI

**Strength:** 256K context window for long documents + math-heavy
tasks. Stronger on literary/language tasks than the others. Lower
hallucination rate than GLM on the domain it knows.

**Weakness:** same identity-leak issues as GLM. Less mature for
narrow-scope code debugging than Codex. Chinese-centric training
shows in some edge cases (date formats, unit conventions). If
K2.6 is genuinely new (post-2026-Q1), profile is partly inferred
from K2.5 — verify in practice.

**Budget:** Chutes pay-as-you-go, similar to GLM.

**Use for:**
- Reading a single very long document (> 50K tokens) and
  summarizing it
- Math derivations where showing work matters
- Specific document digestion tasks with clear output format
- Contradiction detection between multiple documents (had some
  success on 2026-04-22 hardening pass)

**Do NOT use for:**
- Primary code review (Codex is better)
- Wide-scope architecture work (Gemini is better)
- Anything where its identity leak could cause architect to
  misread the output as CC's

### DeepSeek-R1-0528 — reasoning model via Chutes (`think` route)

**Strength:** explicit chain-of-thought reasoning. Best in the Chutes
arsenal for math-heavy derivations, multi-step logic, concurrency
analysis where you want the reasoning trace, and scenarios where you
need to see the model's work (not just the answer). May 2026 update
improved instruction-following over the original R1.

**Weakness:** slower than instruct models (CoT adds latency). Verbose
output — reasoning trace can be 2-10x the answer length. Not a code
generator — it reasons about code, it doesn't produce it as well as
Qwen3-Coder. Still has hallucination risk on domain-specific facts
(instruments, VISA protocols, PySide6 internals).

**Route:** `think` — triggered automatically by CCR when extended
thinking is requested. For manual dispatch: use
`chutes,deepseek-ai/deepseek-r1-0528-tee` as model alias.

**Use for:**
- Multi-step concurrency analysis as Codex backup when Codex window
  is exhausted (R1 reasons, doesn't just scan)
- Math derivations where intermediate steps matter
- Hypothesis evaluation: "is this analysis correct?" as a reasoning audit
- When Codex returns CONDITIONAL and you want a second reasoning pass

**Do NOT use for:**
- Primary code generation (use Qwen3-Coder or Codex)
- Wide-scope architecture (use Gemini)
- Anything requiring < 30s response (latency is higher than GLM/Kimi)

**Budget:** Chutes pay-as-you-go. R1 is more expensive per token than
GLM-5.1 but cheaper than Codex. Expect 2-5× GLM cost per session.

### Qwen3-Coder-Next — dedicated code model via Chutes (`coder` route)

**Strength:** purpose-built for code generation. Better than GLM-5.1
on fresh code drafts, boilerplate reduction, and completing
partially-written functions. Qwen3 family showed strong benchmark
results on HumanEval/MBPP-style tasks. Next-gen update over Qwen3-Coder.

**Weakness:** no long-context advantage over Kimi. May hallucinate
repo-specific APIs (instrument drivers, ZMQ contracts) — always verify
against actual interfaces. Not a reviewer — use Codex for adversarial
review of its output.

**Route:** `coder` — manual dispatch only (not auto-triggered by CCR).
Use `chutes,qwen/qwen3-coder-next-tee` as model alias, or set model
to `coder` route in Claude Code via `/model` command.

**Use for:**
- Fresh code generation where GLM draft quality is insufficient
- Boilerplate scaffolding (new overlay, new driver stub, new test class)
- Completing partially-written functions from a spec
- Alternative implementation when Codex flags CC's draft as FAIL and
  a fresh perspective is worth trying

**Do NOT use for:**
- Adversarial review (use Codex — Qwen3-Coder will be too agreeable)
- Long-context document analysis (use Kimi or Gemini)
- Safety-critical code without Codex review pass afterward

**Budget:** Chutes pay-as-you-go, similar to GLM ($0.5-2 per session).

### Claude Code (CC / Opus 4.7) — coordinator

Not a consultant for itself. If CC needs a second CC opinion, write
the question down, stop, ask architect on next available session.
Parallel CC sessions on the same repo violate `docs/ORCHESTRATION.md`
§3 (one coordinator at a time).

## 2. Routing decision tree

Start here. Do NOT improvise routing.

```
Is the task a code review of an existing diff?
  │
  ├─ YES
  │   │
  │   ├─ diff < 500 lines, narrow scope (1-3 files)
  │   │     → Codex solo (adversarial)
  │   │
  │   ├─ diff > 500 lines OR touches > 5 files
  │   │     → Gemini solo (architectural impact)
  │   │
  │   └─ safety-critical diff (SafetyManager, interlocks, drivers)
  │         → Codex + Gemini adversarial pair, synthesize both
  │
  ├─ NO — is it a draft of NEW content (code, spec, doc)?
  │   │
  │   ├─ code draft, routine transformation
  │   │     → GLM-5.1 draft → CC verify before commit
  │   │
  │   ├─ code draft, non-trivial
  │   │     → CC drafts, Codex reviews. GLM not trustworthy enough.
  │   │
  │   └─ long-form doc / strategy / spec
  │         → CC drafts. Gemini reviews for gaps if needed.
  │
  ├─ NO — is it an audit of existing state (repo, docs, code health)?
  │   │
  │   ├─ narrow scope: one file, specific concern
  │   │     → Codex solo
  │   │
  │   └─ wide scope: whole repo, architectural drift
  │         → Gemini solo, --background
  │
  ├─ NO — is it a question CC can't answer alone?
  │   │
  │   ├─ concurrency / race / lifecycle question
  │   │     → Codex first (if window available); R1-0528 as backup
  │   │       or when math-heavy reasoning trace is needed
  │   ├─ cross-file pattern question → Gemini
  │   ├─ long-document comprehension → Kimi
  │   ├─ translation question → GLM or Kimi
  │   ├─ math derivation → R1-0528 (reasoning trace) or Kimi (show work)
  │   └─ code generation / scaffolding task
  │         → Qwen3-Coder draft → Codex review (writer-reviewer pair)
  │           OR GLM draft if budget-sensitive and task is mechanical
  │
  └─ NO — is it a major architectural decision?
        │
        └─ THREE-way parallel review (Codex + Gemini + one of GLM/Kimi
           for Russian-language clarification if needed) → CC synthesizes
           → architect approves BEFORE action
```

### 2.1 Calibrated task-class routing matrix

Empirical from 2026-04-30 calibration session (T1–T7). Overrides the
generic tree above when task class is unambiguous.

| Task class | Primary | Secondary / verify | Avoid |
|---|---|---|---|
| Bug hypothesis (asyncio / ZMQ / concurrency) | Codex | Chimera or MiniMax for independent verify | — |
| Code review (verify correctness only — no invention) | GLM | Gemini secondary | Codex, Qwen3, Kimi — over-flag on clean code (T3) |
| Spec design | Codex + GLM + Gemini parallel | — | — (all three add unique insight, T4) |
| Code generation | Codex + GLM | — | Gemini — fabricated `getattr(runtime, "last_i", 0.0)` in T5 |
| Long-context digest (>20KB) | Codex + Qwen3 | — | Others — only Codex + Qwen3 identified meta-arc in T6 96KB CHANGELOG |
| Math derivation | Any single model | — | No discrimination between models (T7 clean sweep) |

**Key calibration T3 finding:** high-reasoning models (Codex, Qwen3, Kimi) all produced
DRIFT verdict on architecturally-consistent code during a consistency check task. GLM
was the only 3/3 CONSISTENT. For tasks asking "is this consistent?" — route to GLM
first; reserve Codex for tasks asking "what is wrong?".

**Calibration T5 finding:** Gemini hallucinated a non-existent method
`getattr(runtime, "last_i", 0.0)` during code generation. Gemini may fabricate
plausible-looking repo-specific attributes; always verify against actual source.

## 3. Formation patterns

These are the only patterns you should use. Invent new ones only with
architect approval.

### 3.1 Solo consultant (most common, ~70% of consultations)

One consultant, one focused question, one response. CC synthesizes
with its own reasoning.

Use when: you need a specific answer, budget-sensitive, the decision
is narrow.

Example: "Codex, is this specific diff safe to commit? Review
docs/ORCHESTRATION.md §4 protocol for context."

### 3.2 Writer-reviewer pair (~15%)

One consultant writes a draft, another reviews it. CC integrates the
reviewer's critique into the draft and decides whether to commit.

Cost: 2x solo. Value: catches issues the drafter misses.

Classic pair:
- **GLM draft → Codex review** — cheap draft + rigorous review, good
  for routine code changes
- **Kimi draft (when long context helps) → Codex review** — same
  pattern for doc-heavy work

NEVER pair:
- **Codex + Codex** — same model twice is waste
- **GLM review → anything** — GLM is too weak as adversarial reviewer

### 3.3 Adversarial pair (~10%)

Two consultants with opposing perspectives evaluate the same artifact.
CC sees where they agree (high confidence) and where they disagree
(flag for architect or for CC's own deeper analysis).

Classic pair: **Codex (detail hunter) + Gemini (architecture view)**.
They will often converge. When they don't, the divergence is
informative.

Use when: high-stakes decision, genuinely unclear tradeoff.

### 3.4 Wide audit (~3%)

Single consultant (almost always Gemini with --background flag) given
the whole repository or a large subsystem to scan. Output is a map
of issues, not a fix.

Use when: entering a new area, inheriting work, preparing for major
refactor. Expensive time-wise.

DO NOT use as a "default safety net" — `/ultrareview` misuse on
2026-04-20 is the cautionary tale.

### 3.6 Three-model code review (~3%)

Parallel adversarial review + reasoning audit + alternative
implementation. Heavier than 3.3 but covers the diff from three
distinct angles.

Pattern:
- **Codex** (adversarial review): standard diff review, PASS/FAIL
  verdict with file:line findings
- **R1-0528** (reasoning audit): given the same diff + the Codex
  findings, verify the reasoning chain — does Codex's logic hold?
  Are there concurrency or logic issues Codex missed?
- **Qwen3-Coder** (alternative): given only the spec (not the diff),
  produce an alternative implementation. CC compares: does the
  alternative reveal a simpler approach? Does it agree with CC's
  implementation or flag a different pattern?

CC synthesizes: Codex verdict, R1 reasoning audit, Qwen3-Coder
alternative diff. Decision: commit as-is, amend based on R1 findings,
or consider Qwen3-Coder alternative.

Use when:
- CC is uncertain about its own implementation AND Codex alone hasn't
  cleared the uncertainty
- The diff touches safety-adjacent code and a second reasoning pass
  adds confidence
- Architect explicitly asks for a three-way review

Cost: 3 consultants in parallel. Reserve for genuinely high-stakes
diffs — not a default gate.

### 3.5 Three-way parallel (~2%)

Reserved for truly major decisions: architecture pivots, major
dependency changes, safety-logic rewrites.

Pattern: CC drafts a proposal → Codex, Gemini, and Kimi in parallel
each review it → CC synthesizes all three → architect approves.

Requires architect to be available. Do NOT use as coordinator-solo
decision mechanism.

### 3.7 Calibrated task routing (~5%)

Use the 2.1 matrix when task class is unambiguous. Replaces ad-hoc
model selection for the six task classes listed.

Key distinction from 3.1–3.6: routing is driven by empirical
calibration data, not just model profile heuristics. When the matrix
says "avoid Codex for consistency review" — that is not a heuristic,
it is a measured 0/3 result on a clean-code consistency task (T3).

For consistency-review tasks specifically:
- Start with GLM (3/3 CONSISTENT on T3 — best calibrated for this class)
- Add Gemini as secondary if architectural context is needed
- Do NOT use Codex / Qwen3 / Kimi as primary reviewers for "is this
  consistent?" tasks — they will over-flag clean code

For spec-design tasks specifically:
- Dispatch Codex + GLM + Gemini in parallel (formation 3.5-style)
- All three contributed unique insights in T4; no single model was sufficient

## 4. Consultation protocol (from ORCHESTRATION.md §4)

Every consultation has four artifacts. All four are created by CC.

### 4.1 Brief

`artifacts/consultations/<YYYY-MM-DD>/<topic-slug>/<consultant>.prompt.md`

```
# Consultation brief — <topic> — for <consultant>

## Mission
<one-paragraph description of what we are trying to decide>

## Context files
<list of paths — consultant MUST read these before answering>

## Specific questions
1. <numbered, answerable>
2. <question>

## Expected output format
<e.g., "markdown table with columns X Y Z, maximum 800 words,
file:line refs for every claim, no prose introduction">

## Time / token budget
<e.g., "respond in < 30 min of wall clock, single pass, no
deep-background mode">

## Response file path
<absolute path where consultant output goes>

## What NOT to answer
<scope fences — what is out of scope for this consultation>
```

### 4.2 Response

`artifacts/consultations/<YYYY-MM-DD>/<topic-slug>/<consultant>.response.md`

Captured verbatim from consultant. No editing. If it's long — save it
all. Raw response is reference material; synthesis is the record.

### 4.3 Synthesis

`artifacts/consultations/<YYYY-MM-DD>/<topic-slug>/synthesis.md`

```
# Synthesis — <topic> — <YYYY-MM-DD>

## Consulted
- <consultant>: <response file path>, <summary in one line>
- ...

## Points of agreement
- <what all consultants converge on>

## Points of disagreement
- <where they differ, with CC's reasoning on which side is correct>

## CC decision
<what CC will do — write code, run test, escalate to architect,
drop task>

## Rationale
<why this decision — 3-5 sentences>

## Residual risks
<what could still go wrong with this decision>
```

Synthesis is the artifact that lives. Raw prompts/responses can be
archived after 30 days.

### 4.4 Ledger entry

Add to `docs/decisions/<YYYY-MM-DD>-session.md` under the time
the consultation happened:

```
## <HH:MM> — Consultation: <topic>
Thesis: <one sentence>
Consulted: <models used>
Synthesis: artifacts/consultations/<path>
Decision: <what CC did>
Open: <what remains>
```

## 5. Identity leakage — critical safety rule

GLM and Kimi are trained partly on Claude outputs. They will
spontaneously introduce themselves as "Claude" or "Claude Sonnet"
when asked about their identity.

**This is training leak, not a routing bug.** Do NOT take model
self-identification as evidence the request reached Anthropic. Do
NOT let this confuse the synthesis ("Claude said X and then Claude
also said Y" when one was GLM and one was Kimi).

**Sole authority on what model actually responded:**

```bash
tail -f ~/.claude-code-router/logs/ccr-*.log | grep '"model":"'
```

If the log shows `"zai-org/GLM-5.1-TEE"` — that's GLM.
If `"moonshotai/Kimi-K2.6-TEE"` — that's Kimi.
If `"deepseek-ai/DeepSeek-R1-0528-TEE"` — that's R1 reasoning.
If `"Qwen/Qwen3-Coder-Next-TEE"` — that's Qwen3-Coder.
If Anthropic endpoint — that's real Claude (only when architect's
quota is not exhausted).

Label every response file and synthesis entry with the actual
model per the log, not the self-claim.

## 6. Budget discipline

Per session (rough):

| Model | Typical session cost | Budget per week | max_tokens default |
|---|---|---|---|
| Codex | 1 review = 0.5-1 hr of 5hr window | 10-15 reviews/week before throttle | n/a (CLI) |
| Gemini | 1 request = free, but wall-clock 1-90 min | effectively unlimited | n/a (CLI) |
| GLM | $0.5-2 per session | $20 budget ≈ 10-40 sessions | 32000 |
| Kimi | $0.5-2 per session | $20 budget ≈ 10-40 sessions | 32000 (but see below) |
| R1-0528 | $1-4 per session (CoT overhead) | $20 budget ≈ 5-20 sessions | 32000 (but see below) |
| Qwen3-Coder | $0.5-2 per session | $20 budget ≈ 10-40 sessions | 32000 |
| MiniMax-M2.5 | $0.5-2 per session | $20 budget ≈ 10-40 sessions | 8192 (hard cap) |
| Chimera (TNG) | $0.5-2 per session | $20 budget ≈ 10-40 sessions | 32000 (but see below) |
| CC (coordinator) | architect weekly quota | watch architect | n/a |

**Chutes API max_tokens discipline (2026-04-30):**
Chutes models reject `max_tokens=null`. Always set explicit cap. Default: `max_tokens=32000`
(high enough that models hit natural stop conditions, not artificial truncation).
Per-model practical caps observed in calibration:
- MiniMax-M2.5: 8192 non-streaming hard cap — always set ≤8192
- R1-0528, Kimi-K2.6: 8000 stable in practice
- GLM-5.1, Qwen3-Coder: 4000 stable; 32000 request is fine, model self-caps

**Kimi long-prompt instability (2026-04-30):**
Kimi-K2.6 connection drops on prompts >50KB approximately.
- 2026-04-29 metaswarm 375KB prompts → all PARSE_ERROR
- 2026-04-30 calibration T6 96KB prompt → failed
- T4 spec design ~5KB → succeeded
Discipline: keep Kimi prompts ≤10KB (conservative) or ≤50KB (risky).
Do NOT dispatch Kimi for long-context digest unless prompt fits safely under threshold.

**R1 / Chimera capacity throttling (2026-04-30):**
R1-0528 showed 33% failure rate during calibration (daytime UTC saturation).
Chimera (TNG) showed 50% failure rate.
For overnight or multi-wave dispatch including either: add ≥30 min inter-wave delay.
Do not include R1 or Chimera in reliability-critical dispatch where failure would
block the session. Prefer Codex + Qwen3-Coder + MiniMax for overnight reliability.

Hard budget rules:

1. **No speculative consultations.** Every consultation must have a
   specific question derivable from current work state.
2. **Synthesis before next consultation.** Don't dispatch consultant
   B while consultant A's response is still unprocessed. Synthesize
   A first, then decide if B is needed.
3. **No re-consulting for scope creep.** If consultant A answered
   question X, don't go back to A with X+Y+Z. Make a new brief or
   pick a different consultant.
4. **Token caps in briefs.** Set expected response length explicitly
   so Gemini doesn't produce 10K words when 2K would do.

## 7. Anti-patterns — what NOT to do

Each of these is traced to a specific 2026-04-21..23 failure mode.
They are here to be learned from, not repeated.

### 7.1 "Review the entire repo"

**What happened:** `/ultrareview` invocation on Gemini returned a
1-page shallow audit with no file:line refs and three "things I
could not assess" items.

**Why:** the prompt was unscoped. Consultants produce slop proportional
to how slop-shaped the prompt is.

**Don't:** ask "review the repo", "find bugs", "improve code quality",
"audit the architecture".

**Do:** ask specific, scoped questions with context files and an
expected output format.

### 7.2 Parallel consultants with overlapping scope

**What happened:** 2026-04-21, `codex/b1-truth-recovery` and
`codex/safe-merge-b1-truth-recovery` — 9 commits of the same work
rewritten on two branches. Different agents thought they were the
sole authority on the same task.

**Why:** no central coordinator. Agents spawned without shared state
view.

**Don't:** dispatch two consultants on the same task without a shared
brief that names the coordinator as CC.

**Do:** every brief names `artifacts/consultations/<path>/synthesis.md`
as the authoritative target and says "CC synthesizes; you do not write
files anywhere else".

### 7.3 Consultant writing files or branches directly

**What happened:** 12 untracked `REPO_HARDENING_*.md` and `REVIEW_*.md`
files landed in repo root from various agent runs. No consistent home,
no index, no authority.

**Why:** consultants were given filesystem write access without a
fixed artifact location.

**Don't:** let consultants write anywhere but the response file path
in their brief.

**Do:** brief specifies exact response path. CC is the only mover of
that content into archives or docs.

### 7.4 Trusting self-identification

**What happened:** GLM answered "I am Claude Sonnet" on introspection
during routing tests. If architect had assumed the routing was broken
("why is Claude claiming to be Sonnet?") real state would have been
misunderstood.

**Why:** training leak is universal in Chinese TEE models.

**Don't:** take self-claims as model identity.

**Do:** verify via CCR log. Label synthesis entries with actual model.

### 7.5 Hardening + feature collision

**What happened:** `b2b4fb5` hardening gate landed in the B1 capture
probe 45 min before `157c4bc` IV.7 ipc:// transport. The hardened
probe had tcp://-flavoured assumptions and may have silently rejected
a healthy ipc:// bridge, causing IV.7 to be blamed for a runtime
failure that was not its fault.

**Why:** two agents, two commits, no awareness of each other's active
work.

**Don't:** tighten shared infrastructure (probes, test harnesses, gate
logic) while a feature touching that infrastructure is on an active
branch.

**Do:** before any hardening commit, CC checks `git worktree list` +
active feature branch state, evaluates whether the hardening would
reject the feature's post-change state, holds or revises the
hardening accordingly. See `docs/ORCHESTRATION.md` §7.

### 7.6 No-synthesis slam

**What happened:** multiple review files were produced by different
models on 2026-04-21 with no synthesis step. Each proposed different
next moves. Architect had to read all of them to piece together a
decision.

**Why:** CC dispatched consultants but never integrated their outputs.

**Don't:** skip step 4.3 (synthesis). The prompt/response files are
NOT the record — the synthesis is.

**Do:** synthesize before calling next consultant. If you don't know
how to synthesize the first response yet, don't dispatch the next
one.

### 7.7 Wrong reasoning level on Codex

**What happened:** Codex default `o3` model with low reasoning was
used for a B1 analysis earlier. Output was shallow and missed the
shared-REQ-state pattern that `gpt-5.4 high` (then the latest) later
identified.

**Why:** `/codex` defaults are weak. Override is required.

**Don't:** invoke `/codex` without explicit model + reasoning flags.

**Do:** ALWAYS pass `--model gpt-5.5 --reasoning high` AND repeat in
prompt body first two lines: `Model: gpt-5.5 / Reasoning effort: high`.
(Or the current latest Codex model — gpt-5.5 as of 2026-04-24.)

### 7.8 High-reasoning models over-flag on consistency review

**What happened:** 2026-04-30 calibration T3 — narrow code review of
HF1+HF2 commit (189c4b7). The commit was architect-reviewed and correct.
Codex, Qwen3, and Kimi all returned DRIFT verdict. GLM returned
CONSISTENT (3/3). The DRIFT verdicts from high-reasoning models were
false positives — the code was consistent with documented invariants.

**Why:** high-reasoning models apply adversarial pressure by default.
On "verify correctness" tasks they search for problems and find
pattern-matches-to-problems even when no actual problem exists.
This is a feature for adversarial review, a bug for consistency check.

**Don't:** use Codex, Qwen3, or Kimi as the primary reviewer for
"does this code match the spec / is this consistent?" tasks.
They are calibrated for "what is wrong?" not "is this right?"

**Do:** use GLM first for consistency-check tasks (§2.1 matrix).
Use Codex for adversarial review only when you want it to hunt for
problems. Separate the task class from the model selection — a model
good at finding bugs is bad at confirming absence of bugs.

**Ref:** artifacts/calibration/2026-04-30/CALIBRATION-MATRIX.md T3.

## 8. Templates

Copy-paste starting points. Fill in brackets.

### 8.1 Codex adversarial review brief

```
Model: gpt-5.5
Reasoning effort: high

# Adversarial review — [one-line task description]

## Context files (read before answering)
- [path 1]
- [path 2]
- [optional: diff to review — paste inline or reference commit SHA]

## Your role
Adversarial reviewer. Find what is wrong with the commit / diff /
proposal. If it passes your scrutiny, say PASS and stop. If it fails,
list findings in CRITICAL / HIGH / MEDIUM / LOW buckets with file:line
refs for every claim.

## Specifically verify
1. [specific concern 1]
2. [specific concern 2]

## Expected output format
- Header: PASS | FAIL | CONDITIONAL (specify condition)
- Findings: numbered, with severity + file:line + reasoning
- Max 2000 words. Terse is better than verbose.

## Scope fence
[anything explicitly NOT to critique, e.g. "do not comment on
unrelated style issues"]

## Response file
Write to: artifacts/consultations/[DATE]/[topic]/codex.response.md
```

### 8.2 Gemini wide-audit brief

```
Model: gemini-3.1-pro-preview

# Wide audit — [subsystem or topic]

## Context
You have the entire [src/cryodaq/...] tree available. Use 1M window.

## Mission
[what you are scanning for — architectural drift, doc-vs-code mismatch,
pattern consistency, etc.]

## Specifically look for
1. [pattern 1]
2. [pattern 2]

## Expected output format
- Single markdown table with columns: [finding, file:line, severity, explanation]
- Maximum 3000 words total
- No executive summary, no recommendations — CC synthesizes those
- Include BOTH positive findings (consistent patterns worth preserving)
  AND negative findings (drift, bugs)

## Time budget
Run deep (--background). 60-90 min wall clock acceptable.

## Response file
Write to: artifacts/consultations/[DATE]/[topic]/gemini.response.md
```

### 8.3 GLM draft brief

```
# Code draft — [one-line task]

## Mission
Produce a draft of [specific code change or file]. CC will verify
against tests before commit. You are NOT the final authority — your
output is a starting point.

## Specification
[exact spec of what the code should do]

## Context files
- [path to file to modify]
- [related files]

## Expected output
- Full file content (not a diff)
- Maximum 200 lines of code
- Standard-compliant Python 3.12+, use repo's ruff config
- No external dependencies beyond what's already in pyproject.toml
- Include docstrings

## Scope fence
- Do NOT modify any files other than the one specified
- Do NOT add new config keys
- Do NOT commit, push, or create branches

## Response file
Write to: artifacts/consultations/[DATE]/[topic]/glm.response.md
```

### 8.4 Kimi long-document-digest brief

```
# Document digest — [document name]

## Mission
Read the entire document at [path] (X tokens estimated) and produce
a structured digest.

## Output requirements
- Main thesis (1 sentence)
- Key claims with evidence (numbered list, max 10)
- Specific numbers, dates, names (verbatim quotes with line refs)
- Open questions the document leaves unanswered (numbered list)
- Maximum 2000 words

## What to NOT do
- Do not analyze, evaluate, or critique — just digest
- Do not generate prose — use lists and tables

## Response file
Write to: artifacts/consultations/[DATE]/[topic]/kimi.response.md
```

### 8.5 Synthesis template

```
# Synthesis — [topic] — [DATE]

## Consulted
| model | response file | one-line summary |
|---|---|---|
| [actual model per CCR log] | [path] | [summary] |

## Points of agreement
1. [finding where multiple consultants agree]
2. ...

## Points of disagreement
1. Claim: [what was disputed]
   - [Consultant A]: [A's view]
   - [Consultant B]: [B's view]
   - CC reasoning: [why CC thinks one side is right, or escalation
     to architect]

## CC decision
[what CC will do next — commit, test, escalate, drop]

## Rationale
[3-5 sentences]

## Residual risks
- [risk 1]
- [risk 2]

## Archived to
docs/decisions/[DATE]-session.md (ledger entry)
```

## 9. Session-start checklist for multi-model work

When CC begins a session that will involve consultation:

- [ ] Read this skill
- [ ] Read `docs/ORCHESTRATION.md` §§ 2, 4, 7
- [ ] Check CCR status: `ccr status` — if not running and GLM/Kimi needed, `ccr start`
- [ ] Check `artifacts/consultations/` for stale pending response files that need synthesis
- [ ] Note current budget estimates: when does architect's CC quota reset, what's left on Codex 5h window, any Chutes budget concerns
- [ ] Before EACH consultation: can CC answer this itself without
      external help? If yes — do that, skip consultation.

## 10. When architect is unavailable

If CC is running without architect during a multi-model session:

1. **Never start a consultation for a decision CC should defer.**
   If in doubt, stop and write a handoff.
2. **Solo consultations only** unless the task is pre-architected in
   a `CC_PROMPT_*.md` or existing plan.
3. **Always synthesize** before dispatching the next one.
4. **Ledger everything** so returning architect sees what happened
   and why.

## 11. Glossary

| Term | Meaning |
|---|---|
| CCR | claude-code-router, proxies Anthropic API calls to Chutes (GLM/Kimi/R1/Qwen3-Coder) |
| Chutes | pay-as-you-go endpoint for GLM/DeepSeek/Kimi/Qwen models |
| think route | CCR route → DeepSeek-R1-0528-TEE (triggered by extended thinking or manual alias) |
| coder route | CCR route → Qwen3-Coder-Next-TEE (manual dispatch only) |
| Synthesis | CC-authored artifact that integrates consultant responses into a decision |
| Brief | CC-authored prompt for a consultant, stored as .prompt.md |
| Adversarial review | review whose primary goal is to find what's wrong, not approve |
| Wide audit | broad-scope scan, typically Gemini with --background |
| TEE | Trusted Execution Environment — Chutes' GLM/Kimi hosting mode |
| Identity leak | model trained on Claude outputs claiming to be Claude |

---

*This skill is living. If a rule here becomes wrong, flag it in
session ledger under "Open for next architect session". Architect
updates this file via normal commit. Do not silently diverge.*
