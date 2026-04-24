# Overnight swarm batch — 2026-04-24 → 2026-04-25 morning

**Mission.** Dispatch 10 consultation jobs across Codex and Gemini
tonight. Let them run overnight. Morning: CC synthesizes per-stream,
architect (Vladimir + web Claude) reviews syntheses and makes decisions.

**Economics.** Codex (ChatGPT Plus) and Gemini (Google AI Pro) are
prepaid subscriptions. Cost of running them tonight is zero marginal.
Cost of NOT running them is opportunity loss: we wake up without data.

**Scope discipline.** 10 tasks. No more. Each task has its own brief
file, response file, clear expected output format. No free-form
"explore the repo" invitations — every task is scoped and answerable.

**GLM and Kimi excluded from this run** because (a) they are accessed
via CCR as CC-with-different-model rather than independent processes,
(b) yesterday's tests showed low signal-to-noise, (c) cost is Chutes
pay-as-you-go vs Codex/Gemini sunk cost. Revisit later if needed.

---

## 1. Directory structure

All artifacts under `artifacts/consultations/2026-04-24-overnight/`:

```
artifacts/consultations/2026-04-24-overnight/
├── BRIEFS/                          ← prompts sent to consultants
│   ├── codex-01-r123-pick.prompt.md
│   ├── codex-02-shared-context.prompt.md
│   ├── codex-03-launcher-concurrency.prompt.md
│   ├── codex-04-alarm-v2-threshold.prompt.md
│   ├── codex-05-thyracont-probe.prompt.md
│   ├── gemini-01-r123-blast.prompt.md
│   ├── gemini-02-arch-drift.prompt.md
│   ├── gemini-03-doc-reality.prompt.md
│   ├── gemini-04-safe-merge-eval.prompt.md
│   └── gemini-05-coverage-gaps.prompt.md
├── RESPONSES/                       ← raw responses from consultants
│   ├── codex-01-r123-pick.response.md
│   ├── ... (parallel to BRIEFS)
├── STREAM_SYNTHESES/                ← CC morning work
│   ├── A-r123-repair-choice.md
│   ├── B-b1-and-concurrency.md
│   ├── C-repo-health.md
│   └── D-safe-merge-disposition.md
└── MASTER_SUMMARY.md                ← CC final rollup for architect
```

Create all directories in Phase 0 before dispatches.

---

## 2. Task streams

### Stream A — b2b4fb5 repair choice (2 tasks)

**Codex-01** adversarial pick between R1/R2/R3.
**Gemini-01** blast radius analysis R1/R2/R3.

→ Morning synthesis: architect picks one of R1/R2/R3, CC implements on
`feat/b2b4fb5-repair` branch in a follow-up session.

### Stream B — B1 root cause + concurrency (3 tasks)

**Codex-02** shared `zmq.Context()` race analysis in `zmq_subprocess.py`.
Per `CODEX_ARCHITECTURE_CONTROL_PLANE.md` §1.1, IV.6 eliminated shared
REQ socket but retained shared Context. This is the leading H4 candidate.

**Codex-03** `launcher.py` concurrency sweep. Find any other
lifecycle / race / ordering bugs beyond b2b4fb5. 1500-line file,
safety-critical, worth a careful read.

**Gemini-02** whole `src/cryodaq` architectural drift since v0.33.0.
Wide audit using 1M context window — find patterns that silently broke,
invariants violated, abstractions leaking.

→ Morning synthesis: map of remaining B1 candidates (H4, H5, new
ones), priority order for next investigation.

### Stream C — Repo health (4 tasks)

**Codex-04** `alarm_v2.py` KeyError for `cooldown_stall` fix approach.
Small scope, known bug, produce patch spec.

**Codex-05** `thyracont_vsp63d.py` `_try_v1_probe` checksum consistency
review. Small scope, known brittleness, produce patch spec.

**Gemini-03** doc-vs-code reality check. Top-level docs often drift
from actual source. Verify claims in `CLAUDE.md` + `PROJECT_STATUS.md` +
`ROADMAP.md` + `DOC_REALITY_MAP.md` against current `src/` truth.

**Gemini-05** test coverage gaps. Which subsystems have weakest
coverage? What tests should exist but don't? Prioritize by safety
criticality.

→ Morning synthesis: list of 2-5 day-and-done fixes (alarm_v2,
thyracont, doc reconciliation), test-writing backlog ordered by
priority.

### Stream D — Safe-merge branch disposition (1 task)

**Gemini-04** read 11 docs commits on `codex/safe-merge-b1-truth-recovery`
and produce merge/drop recommendation per commit.

→ Morning synthesis: list of commits to cherry-pick into master vs
abandon. Architect executes in a follow-up session.

---

## 3. Dispatch protocol

### 3.1 Pre-dispatch setup

```bash
mkdir -p artifacts/consultations/2026-04-24-overnight/{BRIEFS,RESPONSES,STREAM_SYNTHESES}
```

### 3.2 For each Codex task

Create `BRIEFS/codex-NN-slug.prompt.md` using skill §8.1 template.

Dispatch:

```bash
# Background so all 5 launch without CC blocking
/codex:rescue --model gpt-5.5 --reasoning high --background \
  --prompt "$(cat artifacts/consultations/2026-04-24-overnight/BRIEFS/codex-NN-slug.prompt.md)" \
  --output artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-NN-slug.response.md
```

(Adapt to actual `/codex:rescue` flag names — they may differ. If
`--prompt` is not a flag, heredoc the prompt. If `--output` not
supported, capture via shell redirect or a wrapper script. Adapt and
ledger.)

After dispatch, run `/codex:status` to confirm all 5 Codex jobs are
queued or running.

### 3.3 For each Gemini task

Create `BRIEFS/gemini-NN-slug.prompt.md` using skill §8.2 template
(adapted per task needs).

Dispatch:

```bash
/gemini:rescue -m gemini-3.1-pro-preview --background \
  --prompt "$(cat artifacts/consultations/2026-04-24-overnight/BRIEFS/gemini-NN-slug.prompt.md)" \
  --output artifacts/consultations/2026-04-24-overnight/RESPONSES/gemini-NN-slug.response.md
```

After dispatch, run `/gemini:status` to confirm all 5 jobs.

### 3.4 Brief content — CRITICAL anti-anchoring rules

Some briefs (Codex-01, Gemini-01) ask consultants to pick between
R1/R2/R3. Those briefs MUST NOT:
- Reveal CC's or architect's preferred option
- Hint at "the right answer" in wording
- Present R1 first and most detailed (implies preference)

Randomize option ordering. Present each with equal space and
neutral tone. Ask consultant to reach their own conclusion from
evidence.

For other briefs (analysis, review, audit), this doesn't apply —
those are genuinely open questions.

### 3.5 Brief content — required universal elements

Every brief contains:

- **Mission** — one paragraph what we're deciding or analyzing
- **Evidence files to read** — list of `file:line` or full paths
- **Specific questions** — numbered, answerable with concrete
  output
- **Output format** — word count cap, structure, required elements
- **Scope fence** — what NOT to answer (don't invent unrelated
  critique)
- **Response file path** — exact path where response goes
- **Model confirmation** — first line `Model: gpt-5.5 / Reasoning
  effort: high` for Codex, `Model: gemini-3.1-pro-preview` for Gemini

### 3.6 Context file budget per brief

Briefs should NOT paste entire files — they should reference paths.
Consultants have read access to the repo. Paste diff snippets (max
200 lines) when critical, reference files by path otherwise.

If a consultant's response indicates they didn't read the referenced
file — that's a retry-once condition.

### 3.7 Model version note

All Codex invocations use `gpt-5.5` (latest as of 2026-04-24). If
`/codex` rejects that model string (e.g. "model not found"), fall
back to `gpt-5.4` for this batch and ledger the issue — the plugin
config may need updating separately.

All Gemini invocations use `gemini-3.1-pro-preview` (latest as of
2026-04-24, released 2026-02-19). Plain `-m gemini-3.1-pro-preview`
in Gemini CLI. If CLI rejects, fall back to `gemini-2.5-pro` with
ledger note. Older CLI installs may not recognize the 3.1 string;
running `gemini --version` and comparing against CLI changelog is a
fast check.

---

## 4. Per-task briefs (specifications)

### Codex-01 — R1/R2/R3 adversarial pick

**Mission.** Commit `b2b4fb5` hardened the B1 capture bridge startup
probe. Under `ipc://` transport it races with engine bind and fails
at cmd #0. Three repair options exist:

- **R1** — retry probe with bounded backoff (5 × 200ms)
- **R2** — block `ZmqBridge.start()` until first reply received
- **R3** — revert b2b4fb5, accept no startup guard

Anti-anchor: Options presented alphabetically. No preference signaled.

**Context files to read:**
- `docs/decisions/2026-04-24-b2b4fb5-investigation.md` (full)
- `git show b2b4fb5 -- tools/diag_zmq_b1_capture.py` (diff)
- `src/cryodaq/core/zmq_subprocess.py` lines 150-250 (bridge command loop)
- `src/cryodaq/core/zmq_transport.py` (ipc:// defaults, IV.7 addition)

**Questions:**
1. Which option has smallest probability of introducing new race
   conditions? Why?
2. Is there a fourth option missed? If yes, describe with file:line.
3. For the chosen option, specific test cases to empirically confirm
   it works on both tcp:// and ipc://.
4. What failure modes does the chosen option NOT address?

**Output:**
- First line: `Model: gpt-5.5 / Reasoning effort: high`
- Verdict header: `PICK: R1` or `R2` or `R3` or `R4-<n>`
- Findings with file:line refs
- Specific test case list (at least 3)
- Residual risks
- Max 2500 words

---

### Codex-02 — Shared `zmq.Context()` race analysis

**Mission.** `CODEX_ARCHITECTURE_CONTROL_PLANE.md` §1.1 notes:
> "The bridge subprocess still uses one shared zmq.Context() for
> both SUB and ephemeral REQ sockets (src/cryodaq/core/zmq_subprocess.py:86).
> Ephemeral sockets did not eliminate that shared-context surface."

IV.6 removed shared REQ socket but kept shared Context. B1 still
fires ~80s into any run on both tcp:// and ipc://. Current
working hypothesis H4: shared Context state accumulates across
ephemeral REQ sockets and eventually becomes unusable for the REP
path.

**Context files:**
- `src/cryodaq/core/zmq_subprocess.py` full
- `src/cryodaq/core/zmq_bridge.py` full
- `docs/bug_B1_zmq_idle_death_handoff.md` full
- `CODEX_ARCHITECTURE_CONTROL_PLANE.md` §1.1

**Questions:**
1. Is the shared-Context hypothesis consistent with the observed B1
   signature (~80s uptime, cmd-plane only, data-plane alive)?
2. What specific Context state could degrade across ephemeral socket
   create/close cycles? Fd leaks? IO thread state? Monitor state?
   Internal queue? Name them at libzmq source level if possible.
3. Proposed minimal experiment to falsify or confirm this hypothesis.
   Must be runnable via existing diag tools or a small new one.
4. If H4 is confirmed, what's the architectural fix? Per-command
   Context (expensive) vs separate SUB and REQ contexts (cheap) vs
   something else?

**Output:**
- First line: `Model: gpt-5.5 / Reasoning effort: high`
- Hypothesis status: CONSISTENT / INCONSISTENT / UNKNOWN
- Evidence for each of 4 questions, file:line refs where applicable
- Proposed falsification experiment with concrete commands
- Max 3000 words

---

### Codex-03 — `launcher.py` concurrency sweep

**Mission.** Beyond b2b4fb5, find other concurrency / lifecycle /
ordering bugs in `src/cryodaq/launcher.py`. This file is 1500 lines,
orchestrates engine lifecycle, bridge subprocess, GUI, watchdogs.
Safety-critical.

**Context files:**
- `src/cryodaq/launcher.py` full
- `src/cryodaq/gui/zmq_client.py` full (bridge wrapper that launcher
  interacts with)
- `CODEX_ARCHITECTURE_CONTROL_PLANE.md` §1.1 (notes on launcher TCP
  coupling)

**Questions:**
1. Race conditions between engine start, bridge start, GUI start?
2. Shutdown ordering bugs — what if engine crashes first vs bridge
   first vs GUI first?
3. Watchdog logic bugs — beyond the IV.6 cooldown fix from yesterday,
   anything else?
4. Signal handling — SIGTERM/SIGINT handling correct across
   subprocesses?
5. Resource leaks — file descriptors, sockets, locks that might not
   close on error paths?

**Output format:**
- First line: `Model: gpt-5.5 / Reasoning effort: high`
- Findings numbered by severity: CRITICAL / HIGH / MEDIUM / LOW
- Each finding: file:line + concrete failure scenario + repro
  steps (even if manual)
- Max 3500 words

---

### Codex-04 — `alarm_v2.py` KeyError fix

**Mission.** `alarm_v2.py::_eval_condition` raises `KeyError: 'threshold'`
when evaluating `cooldown_stall` composite alarm. Not crash, but log
spam every ~2s. Fix approach needed.

**Context files:**
- `src/cryodaq/core/alarm_v2.py` (focus on `_eval_condition`)
- `config/alarms_v3.yaml` (search for `cooldown_stall`)

**Questions:**
1. Root cause: missing field in config? Config-code contract
   mismatch? Stale feature flag?
2. Fix preference: tighten config OR make code defensive with
   `cond.get("threshold")`? What's the safer choice given this
   is an alarm (warning about real conditions) and we don't want
   to silently swallow valid errors?
3. Specific patch: show exact lines to change, with before/after.
4. Test case: what new test verifies the fix doesn't regress?

**Output:**
- First line: `Model: gpt-5.5 / Reasoning effort: high`
- Root cause one paragraph
- Fix patch (unified diff format, under 50 lines)
- Test case (under 30 lines)
- Max 1500 words

---

### Codex-05 — Thyracont `_try_v1_probe` hardening

**Mission.** `_try_v1_probe` (lines 157-166) only checks response
prefix, not checksum. Read path validates. Driver can "connect"
and emit NaN forever on non-VSP63D hardware (which is what bit us
2026-04-20 with VSP206). ~5 LOC hardening.

**Context files:**
- `src/cryodaq/drivers/instruments/thyracont_vsp63d.py` full
- `HANDOFF_2026-04-20_GLM.md` §3 (description of 2026-04-20 incident)

**Questions:**
1. Why does probe skip checksum? Deliberate choice for
   compatibility or oversight?
2. Is there any case where probe-without-checksum is correct?
   (e.g., different vendor variants that we want to still connect
   to but with warning?)
3. Proposed fix: make probe consistent with read path, OR keep
   relaxed probe + add warning log when checksum differs?
4. Patch + test case.

**Output:**
- First line: `Model: gpt-5.5 / Reasoning effort: high`
- Root cause one paragraph
- Fix patch (unified diff, under 50 lines)
- Test case (under 30 lines)
- Max 1500 words

---

### Gemini-01 — R1/R2/R3 blast radius

**Mission.** Same R1/R2/R3 as Codex-01, but different question:
which choice minimizes future interference with B1 root cause
investigation (H4, H5), and which has smallest "ripple" in
dependent code?

Anti-anchor: options presented alphabetically, no preference
signaled.

**Context files (use 1M context generously):**
- `docs/decisions/2026-04-24-b2b4fb5-investigation.md`
- `git show b2b4fb5 -- tools/diag_zmq_b1_capture.py`
- `src/cryodaq/core/zmq_bridge.py`
- `src/cryodaq/core/zmq_subprocess.py`
- `tools/diag_zmq_*.py` (all diag tools)
- `docs/bug_B1_zmq_idle_death_handoff.md`

**Questions:**
1. Which option has smallest blast radius — i.e., fewest files
   and behaviors changed outside `diag_zmq_b1_capture.py` itself?
2. For each option, what second-order changes ripple into:
   other diag tools, tests, launcher, docs?
3. Considering future B1 work (H4 shared-context, H5 engine REP
   state), which option least constrains the experimental surface
   we'll need?
4. Load-bearing assumptions in current repo that any option might
   silently break?

**Output:**
- First line: `Model: gemini-2.5-pro`
- Single markdown table columns: Option | First-order impact |
  Second-order impact | B1 investigation interference | Overall
  verdict
- Then max 500 words commentary
- Total max 1500 words

---

### Gemini-02 — Architectural drift since v0.33.0

**Mission.** 50 commits landed on master between v0.33.0 and HEAD.
Find architectural drift: invariants silently broken, abstractions
leaking, patterns losing consistency, subsystem boundaries eroded.

**Context scope:** `src/cryodaq/` entire tree. Gemini 1M context —
drop it all in.

**Known invariants to check (from CLAUDE.md + PROJECT_STATUS.md):**
1. Persistence-first: SQLite commit before broker publish
2. No `gui/` imports in engine code
3. No numpy/scipy in drivers/core (exception: sensor_diagnostics)
4. SafetyManager is single authority for source on/off
5. Plugin exceptions isolated — can't crash engine
6. Every `asyncio.create_task` must be tracked and cancellable
7. No blocking I/O on engine event loop (exception: LibreOffice)
8. Keithley disconnect calls emergency_off first
9. Config files fail-closed (ConfigError → exit 2)

**Questions:**
1. For each invariant, is it still honored? Specific violations
   with file:line.
2. New patterns introduced during v0.33.0..HEAD that bypass or
   contradict existing patterns?
3. Subsystem boundaries — are `core/`, `drivers/`, `analytics/`
   maintaining their isolation per CLAUDE.md module index?
4. Abstraction leaks — cases where a lower-level detail bleeds
   into higher-level code?

**Output:**
- First line: `Model: gemini-2.5-pro`
- Table: Invariant | Status (HELD / VIOLATED / AMBIGUOUS) |
  Evidence file:line | Severity
- Section per non-HELD invariant with details
- Additional findings beyond the 9 invariants (new patterns, etc.)
- Max 4000 words

---

### Gemini-03 — Doc-vs-code reality check

**Mission.** Top-level documentation drifts from code over time.
Verify claims in 4 key documents against actual source.

**Context files to read:**
- `CLAUDE.md`
- `PROJECT_STATUS.md`
- `ROADMAP.md`
- `DOC_REALITY_MAP.md`
- Plus `src/cryodaq/` tree to verify against

**Questions:**
1. For each factual claim in each doc (module paths, function
   signatures, invariants, numerical specs like "24 channels",
   "6-state FSM", "WAL mode"), is it still accurate?
2. Claims that USED to be true but aren't anymore?
3. Claims that were aspirational ("planned for Phase 3") —
   still relevant or should be removed?
4. Internal inconsistencies — one doc says X, another says Y?

**Output:**
- First line: `Model: gemini-2.5-pro`
- Per document: table of factual claims with status (TRUE /
  FALSE / STALE / UNVERIFIABLE) + evidence
- Cross-document inconsistencies as a separate section
- Priority-ranked fix list (top 10)
- Max 4000 words

---

### Gemini-04 — Safe-merge branch 11 docs eval

**Mission.** `codex/safe-merge-b1-truth-recovery` branch has 11
commits that master doesn't. They are docs and runbooks authored
during 2026-04-21..23 agent swarm activity. Determine for each:
merge into master (valuable) or drop (slop).

**Context:**
- `git log --oneline master..codex/safe-merge-b1-truth-recovery`
  for list
- `git show <sha>` on each commit for content
- Current state of master docs (compare for overlap or redundancy)

**Questions per commit:**
1. What does this commit add or change?
2. Is the content still relevant as of 2026-04-24 (some may be
   superseded by later work)?
3. Is it contradicted by anything on master?
4. Merge recommendation: MERGE / CHERRY-PICK modified / DROP

**Output:**
- First line: `Model: gemini-2.5-pro`
- Table with one row per commit: SHA | Subject | Content summary
  (1 line) | Relevance now | Recommendation | Reasoning (1 line)
- Max 2500 words

---

### Gemini-05 — Test coverage gaps

**Mission.** CryoDAQ has ~1800 tests. Which subsystems have
weakest coverage? What critical paths are untested? Prioritize
by safety criticality — untested safety code is more urgent than
untested UI.

**Context:**
- `tests/` tree
- `.coverage` file if valid (may be stale from 2026-04-17)
- `src/cryodaq/` tree for what should be tested
- `CLAUDE.md` safety invariants

**Questions:**
1. Per major subsystem (core, drivers, storage, analytics,
   notifications, reporting, web, safety), what's the coverage
   qualitatively? (Gemini likely can't run pytest, so use
   file-ratio heuristics and code-path analysis.)
2. What code paths in safety-critical code (safety_manager,
   interlock, scheduler persistence-first) are NOT hit by any
   existing test?
3. Top 10 tests that should exist but don't, ordered by
   safety-criticality first, then by bug-finding-probability.
4. Any tests that look like they test implementation details
   rather than behavior (will break on refactor)?

**Output:**
- First line: `Model: gemini-2.5-pro`
- Subsystem coverage qualitative summary (table)
- Untested critical paths (list with file:line refs)
- Top 10 missing tests (priority ordered)
- Anti-pattern tests (bonus, max 5)
- Max 3000 words

---

## 5. Dispatch sequence (tonight)

Do all in one CC session before sleeping:

1. **Phase 0** — directory setup (30 sec)
2. **Phase 1** — write all 10 BRIEFS files (30-60 min)
   - Each brief: ~300-600 words
   - Use skill §8.1 / §8.2 templates as starting points
   - Anti-anchoring rules STRICT on Stream A briefs (Codex-01, Gemini-01)
3. **Phase 2** — dispatch all 10 in background (5-10 min)
   - 5 Codex jobs via `/codex:rescue --background`
   - 5 Gemini jobs via `/gemini:rescue --background -m gemini-3.1-pro-preview`
4. **Phase 3** — status verification (2 min)
   - `/codex:status` shows 5 Codex jobs queued/running
   - `/gemini:status` shows 5 Gemini jobs queued/running
5. **Phase 4** — launch ledger (5 min)
   - Create `docs/decisions/2026-04-24-overnight-swarm-launch.md`
   - Log dispatch timestamps, job IDs if available, expected
     response paths
6. **Phase 5** — end session

Total tonight: ~1h CC session.

---

## 6. Morning retrieval sequence (tomorrow)

New CC session starts with:

1. **Phase 6** — status check (5 min)
   - `/codex:status` + `/codex:result` for each of 5 jobs
   - `/gemini:status` + `/gemini:result` for each of 5 jobs
   - Expected: all 10 responses landed in `RESPONSES/`
   - If some didn't: retry once with tighter brief, else mark
     FAILED and proceed without that data

2. **Phase 7** — per-stream synthesis (60-90 min)
   CC writes 4 synthesis files:
   - `STREAM_SYNTHESES/A-r123-repair-choice.md`
     - Codex-01 verdict + reasoning
     - Gemini-01 verdict + reasoning
     - Convergence? (if both picked same → high confidence)
     - Divergence? (if different → present to architect as open)
     - CC's own post-reading recommendation
   - `STREAM_SYNTHESES/B-b1-and-concurrency.md`
     - Codex-02 shared-context hypothesis verdict
     - Codex-03 launcher bugs list (filter for actually new)
     - Gemini-02 architectural drift findings relevant to B1
     - Cross-reference: does Codex-02 + Gemini-02 agree on next
       B1 hypothesis to test?
   - `STREAM_SYNTHESES/C-repo-health.md`
     - Codex-04 alarm_v2 patch + verdict
     - Codex-05 Thyracont patch + verdict
     - Gemini-03 doc drift top-10 fix list
     - Gemini-05 missing tests top-10
     - Integrated: day-and-done fixes (mini PR candidates)
   - `STREAM_SYNTHESES/D-safe-merge-disposition.md`
     - Gemini-04 per-commit recommendations, in table form
     - CC's own reading of the highest-stakes commits (≤ 3) as
       sanity check
     - Merge execution plan if recommendations are clean

3. **Phase 8** — master rollup (30 min)
   `MASTER_SUMMARY.md` with:
   - 4 stream-level decisions architect needs to make
   - Prioritized action list (today / this week / later)
   - Open questions for architect
   - Resource cost estimate for each action
   - One-paragraph TL;DR at top

4. **Phase 9** — commit + push (5 min)
   Everything under `artifacts/consultations/2026-04-24-overnight/`
   goes into one commit with message referencing this batch.

Total morning: ~2h CC session.

---

## 7. Budget and failure modes

### Budget

- Codex: 5 jobs via 5-hour window. Each background job runs
  independently. Should fit easily in one window IF no retries.
  If 2+ retries hit, budget tight.
- Gemini: 5 jobs × 1 req each = 5 requests of Google AI Pro 1000/day.
  Negligible.
- CC: ~1h tonight + ~2h tomorrow = 3h total session time.
  Moderate.

### Failure modes to handle

**F1. Consultant dispatches but returns nothing.**
Wait up to 8 hours. After that, retry once with tighter brief. If
still nothing, mark FAILED and note in synthesis.

**F2. Consultant returns slop.**
Criteria for slop:
- < 500 words of actual content
- No file:line refs when brief asked for them
- Evades specific numbered questions
Action: retry once with explicit "answer ALL numbered questions,
with file:line refs where indicated". If still slop, note in
synthesis as "consultant returned non-actionable response, drop
this input".

**F3. Consultant answers with different model than requested.**
Check first line of response for model declaration. If Codex returns
"Model: o3" or an older Codex model when we asked `gpt-5.5` — retry
once. If Gemini returns "Model: gemini-2.5-pro" or "gemini-2.5-flash"
when we asked `gemini-3.1-pro-preview` — retry once with explicit
full model string in both CLI flag and prompt body. This is the
common failure.

**F4. Background job lost.**
`/codex:status` or `/gemini:status` shows job neither running nor
completed. Dispatch again with same brief.

**F5. CC quota exhausted tonight before dispatch completes.**
Write ledger showing which jobs dispatched vs pending. Morning
session picks up from pending list.

### Zero-content scenario

If 5+ of 10 responses are FAILED or slop, morning synthesis notes
this as "overnight batch had low yield — primary cause [network /
quota / model issue]". Architect decides whether to re-run or
pivot.

---

## 8. Execution checklist for CC tonight

Before starting, confirm:

- [ ] `docs/ORCHESTRATION.md` and
      `.claude/skills/multi-model-consultation.md` loaded in
      session context
- [ ] On branch `master`, clean tracked tree
- [ ] `/codex` and `/gemini` plugins responding (test: `/codex:status`
      and `/gemini:status` return something)
- [ ] `ccr status` — optional, not strictly needed for this batch
      (we're not using GLM/Kimi)
- [ ] Enough time tonight for 1h session
- [ ] Tomorrow's architect time blocked for review (~1h to read
      syntheses + decide)

Execute phases 0 through 5. Tonight done.

---

## 9. What this gets us

**Tomorrow morning:**
- Confirmed/rejected H4 hypothesis (shared Context) for B1
- Clear R1/R2/R3 choice with two-model adversarial support
- Patch for alarm_v2 KeyError ready to commit
- Patch for Thyracont probe ready to commit
- Map of doc drift top-10 for CLAUDE.md update session
- List of concurrency bugs in launcher.py beyond b2b4fb5
- Architectural drift inventory since v0.33.0
- Safe-merge branch disposition plan
- Missing test backlog

That's enough work for ~3 days of focused sessions on its own, and
it was generated overnight while Vladimir slept. This is the value
proposition of owning prepaid Codex + Gemini subscriptions.

**Next strategic session:** architect reads `MASTER_SUMMARY.md`,
picks top 3 actions, writes batch specs for them, CC executes in
daytime sessions. Repeat.

---

*Architect-authored batch spec, 2026-04-24 evening. Will be
re-usable pattern for future overnight runs — adapt the 10 task
specifications, keep the structure.*

*Codex model: gpt-5.5 (released post-2026-04-24). If rejected, fall
back to gpt-5.4 with ledger note per §3.7.*

*Gemini model: gemini-3.1-pro-preview (released 2026-02-19). If
rejected by older CLI, fall back to gemini-2.5-pro with ledger note
per §3.7.*
