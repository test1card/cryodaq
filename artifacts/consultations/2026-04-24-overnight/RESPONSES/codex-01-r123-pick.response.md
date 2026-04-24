Reading prompt from stdin...
OpenAI Codex v0.124.0 (research preview)
--------
workdir: /Users/vladimir/Projects/cryodaq
model: gpt-5.5
provider: openai
approval: never
sandbox: read-only
reasoning effort: high
reasoning summaries: none
session id: 019dbc69-e167-7ef2-ac05-72ff797c36a3
--------
user
Model: gpt-5.5
Reasoning effort: high

# Adversarial review — pick repair option for b2b4fb5 startup race

## Mission

Commit `b2b4fb5` (2026-04-23) added `_validate_bridge_startup()` to
`tools/diag_zmq_b1_capture.py`. Under the `ipc://` transport introduced
by IV.7 (commit `157c4bc`), the synchronous startup probe fires before
the engine's REP socket has finished binding to the ipc socket file,
returns `zmq.Again` ("Resource temporarily unavailable"), and aborts
the capture tool at cmd #0. Empirically confirmed on 2026-04-24: with
the hardening reverted, 20/20 samples succeed on ipc://; with the
hardening present, abort at cmd #0. Full evidence at
`docs/decisions/2026-04-24-b2b4fb5-investigation.md`.

Three repair options are on the table. Pick one. Or propose a fourth.
No preference has been signaled — read the evidence and reach your
own conclusion.

## Context files (read before answering)

- `docs/decisions/2026-04-24-b2b4fb5-investigation.md` (full — the
  empirical record)
- `git show b2b4fb5 -- tools/diag_zmq_b1_capture.py` (the 13-line
  hardening patch)
- `src/cryodaq/core/zmq_subprocess.py` lines 150-250 (bridge
  subprocess command loop — where ephemeral REQ sockets are created
  and torn down)
- `src/cryodaq/core/zmq_transport.py` (ipc:// defaults + path cleanup,
  IV.7 addition)
- `src/cryodaq/gui/zmq_client.py` class `ZmqBridge`, methods
  `start()`, `is_alive()`, `send_command()` (GUI-side wrapper that
  the tool uses)

## The three options (alphabetical, equal space)

### R1 — Bounded-backoff retry inside the probe

Keep `_validate_bridge_startup()` as the guard. Change it to retry
the `send_command({"cmd": "safety_status"})` call with bounded backoff
(for example 5 attempts × 200 ms) before raising `RuntimeError`.
`is_alive()` check stays single-shot. Any single success counts as
startup OK.

### R2 — Move readiness into `ZmqBridge.start()`

Change `ZmqBridge.start()` so it blocks until the subprocess reports
a successful first reply from the engine REP socket, then returns.
The tool's hardening check becomes just `bridge.is_alive()` — which
is already a correct guard for subprocess spawn failure.

### R3 — Revert `b2b4fb5`

Delete `_validate_bridge_startup()` entirely. The tool returns to
its pre-2026-04-23 behavior: `bridge.start()` then directly into
the capture loop, no explicit guard for subprocess spawn failure.
Spawn failures surface naturally as downstream `send_command()`
timeouts.

## Specific questions

1. Which option has the smallest probability of introducing new race
   conditions or regressions? Provide reasoning at the libzmq /
   multiprocessing level, not just "seems safer".
2. Is there a fourth option I missed? If yes, describe it with
   file:line references to where the change would live.
3. For the option you pick, list at least three concrete test cases
   that would empirically confirm it works on both tcp:// (Windows
   fallback) and ipc:// (Unix default).
4. What failure modes does your chosen option NOT address? Be
   explicit — we need to know the remaining exposure, not just the
   closed one.

## Output format

- First line verbatim: `Model: gpt-5.5 / Reasoning effort: high`
- Verdict header: `PICK: R1`, `PICK: R2`, `PICK: R3`, or
  `PICK: R4-<shortname>`
- Numbered findings, each with file:line refs for any claim about
  the current code
- Explicit test case list (at least three items)
- Explicit residual risks section (what your pick does NOT fix)
- Max 2500 words. Terse is better than verbose.

## Scope fence

- Do not relitigate whether b2b4fb5 caused the IV.7 misattribution.
  That is settled per the investigation ledger.
- Do not propose a fix for B1 idle-death itself (the separate
  ~80s-uptime bug). That's a different investigation.
- Do not stray into unrelated style / naming / doc critique.

## Response file

Write to: `artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-01-r123-pick.response.md`

codex
Using the superpowers startup workflow because this is a codebase review task, then I’ll read only the cited evidence and write the requested response file.
exec
/opt/homebrew/bin/bash -lc "sed -n '1,220p' /Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/f09cfd210e21e96a0031f4d247be5f2e416d23b1/skills/using-superpowers/SKILL.md && sed -n '1,220p' /Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/f09cfd210e21e96a0031f4d247be5f2e416d23b1/skills/requesting-code-review/SKILL.md" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
---
name: using-superpowers
description: Use when starting any conversation - establishes how to find and use skills, requiring Skill tool invocation before ANY response including clarifying questions
---

<SUBAGENT-STOP>
If you were dispatched as a subagent to execute a specific task, skip this skill.
</SUBAGENT-STOP>

<EXTREMELY-IMPORTANT>
If you think there is even a 1% chance a skill might apply to what you are doing, you ABSOLUTELY MUST invoke the skill.

IF A SKILL APPLIES TO YOUR TASK, YOU DO NOT HAVE A CHOICE. YOU MUST USE IT.

This is not negotiable. This is not optional. You cannot rationalize your way out of this.
</EXTREMELY-IMPORTANT>

## Instruction Priority

Superpowers skills override default system prompt behavior, but **user instructions always take precedence**:

1. **User's explicit instructions** (CLAUDE.md, GEMINI.md, AGENTS.md, direct requests) — highest priority
2. **Superpowers skills** — override default system behavior where they conflict
3. **Default system prompt** — lowest priority

If CLAUDE.md, GEMINI.md, or AGENTS.md says "don't use TDD" and a skill says "always use TDD," follow the user's instructions. The user is in control.

## How to Access Skills

**In Claude Code:** Use the `Skill` tool. When you invoke a skill, its content is loaded and presented to you—follow it directly. Never use the Read tool on skill files.

**In Copilot CLI:** Use the `skill` tool. Skills are auto-discovered from installed plugins. The `skill` tool works the same as Claude Code's `Skill` tool.

**In Gemini CLI:** Skills activate via the `activate_skill` tool. Gemini loads skill metadata at session start and activates the full content on demand.

**In other environments:** Check your platform's documentation for how skills are loaded.

## Platform Adaptation

Skills use Claude Code tool names. Non-CC platforms: see `references/copilot-tools.md` (Copilot CLI), `references/codex-tools.md` (Codex) for tool equivalents. Gemini CLI users get the tool mapping loaded automatically via GEMINI.md.

# Using Skills

## The Rule

**Invoke relevant or requested skills BEFORE any response or action.** Even a 1% chance a skill might apply means that you should invoke the skill to check. If an invoked skill turns out to be wrong for the situation, you don't need to use it.

```dot
digraph skill_flow {
    "User message received" [shape=doublecircle];
    "About to EnterPlanMode?" [shape=doublecircle];
    "Already brainstormed?" [shape=diamond];
    "Invoke brainstorming skill" [shape=box];
    "Might any skill apply?" [shape=diamond];
    "Invoke Skill tool" [shape=box];
    "Announce: 'Using [skill] to [purpose]'" [shape=box];
    "Has checklist?" [shape=diamond];
    "Create TodoWrite todo per item" [shape=box];
    "Follow skill exactly" [shape=box];
    "Respond (including clarifications)" [shape=doublecircle];

    "About to EnterPlanMode?" -> "Already brainstormed?";
    "Already brainstormed?" -> "Invoke brainstorming skill" [label="no"];
    "Already brainstormed?" -> "Might any skill apply?" [label="yes"];
    "Invoke brainstorming skill" -> "Might any skill apply?";

    "User message received" -> "Might any skill apply?";
    "Might any skill apply?" -> "Invoke Skill tool" [label="yes, even 1%"];
    "Might any skill apply?" -> "Respond (including clarifications)" [label="definitely not"];
    "Invoke Skill tool" -> "Announce: 'Using [skill] to [purpose]'";
    "Announce: 'Using [skill] to [purpose]'" -> "Has checklist?";
    "Has checklist?" -> "Create TodoWrite todo per item" [label="yes"];
    "Has checklist?" -> "Follow skill exactly" [label="no"];
    "Create TodoWrite todo per item" -> "Follow skill exactly";
}
```

## Red Flags

These thoughts mean STOP—you're rationalizing:

| Thought | Reality |
|---------|---------|
| "This is just a simple question" | Questions are tasks. Check for skills. |
| "I need more context first" | Skill check comes BEFORE clarifying questions. |
| "Let me explore the codebase first" | Skills tell you HOW to explore. Check first. |
| "I can check git/files quickly" | Files lack conversation context. Check for skills. |
| "Let me gather information first" | Skills tell you HOW to gather information. |
| "This doesn't need a formal skill" | If a skill exists, use it. |
| "I remember this skill" | Skills evolve. Read current version. |
| "This doesn't count as a task" | Action = task. Check for skills. |
| "The skill is overkill" | Simple things become complex. Use it. |
| "I'll just do this one thing first" | Check BEFORE doing anything. |
| "This feels productive" | Undisciplined action wastes time. Skills prevent this. |
| "I know what that means" | Knowing the concept ≠ using the skill. Invoke it. |

## Skill Priority

When multiple skills could apply, use this order:

1. **Process skills first** (brainstorming, debugging) - these determine HOW to approach the task
2. **Implementation skills second** (frontend-design, mcp-builder) - these guide execution

"Let's build X" → brainstorming first, then implementation skills.
"Fix this bug" → debugging first, then domain-specific skills.

## Skill Types

**Rigid** (TDD, debugging): Follow exactly. Don't adapt away discipline.

**Flexible** (patterns): Adapt principles to context.

The skill itself tells you which.

## User Instructions

Instructions say WHAT, not HOW. "Add X" or "Fix Y" doesn't mean skip workflows.
---
name: requesting-code-review
description: Use when completing tasks, implementing major features, or before merging to verify work meets requirements
---

# Requesting Code Review

Dispatch superpowers:code-reviewer subagent to catch issues before they cascade. The reviewer gets precisely crafted context for evaluation — never your session's history. This keeps the reviewer focused on the work product, not your thought process, and preserves your own context for continued work.

**Core principle:** Review early, review often.

## When to Request Review

**Mandatory:**
- After each task in subagent-driven development
- After completing major feature
- Before merge to main

**Optional but valuable:**
- When stuck (fresh perspective)
- Before refactoring (baseline check)
- After fixing complex bug

## How to Request

**1. Get git SHAs:**
```bash
BASE_SHA=$(git rev-parse HEAD~1)  # or origin/main
HEAD_SHA=$(git rev-parse HEAD)
```

**2. Dispatch code-reviewer subagent:**

Use Task tool with superpowers:code-reviewer type, fill template at `code-reviewer.md`

**Placeholders:**
- `{WHAT_WAS_IMPLEMENTED}` - What you just built
- `{PLAN_OR_REQUIREMENTS}` - What it should do
- `{BASE_SHA}` - Starting commit
- `{HEAD_SHA}` - Ending commit
- `{DESCRIPTION}` - Brief summary

**3. Act on feedback:**
- Fix Critical issues immediately
- Fix Important issues before proceeding
- Note Minor issues for later
- Push back if reviewer is wrong (with reasoning)

## Example

```
[Just completed Task 2: Add verification function]

You: Let me request code review before proceeding.

BASE_SHA=$(git log --oneline | grep "Task 1" | head -1 | awk '{print $1}')
HEAD_SHA=$(git rev-parse HEAD)

[Dispatch superpowers:code-reviewer subagent]
  WHAT_WAS_IMPLEMENTED: Verification and repair functions for conversation index
  PLAN_OR_REQUIREMENTS: Task 2 from docs/superpowers/plans/deployment-plan.md
  BASE_SHA: a7981ec
  HEAD_SHA: 3df7661
  DESCRIPTION: Added verifyIndex() and repairIndex() with 4 issue types

[Subagent returns]:
  Strengths: Clean architecture, real tests
  Issues:
    Important: Missing progress indicators
    Minor: Magic number (100) for reporting interval
  Assessment: Ready to proceed

You: [Fix progress indicators]
[Continue to Task 3]
```

## Integration with Workflows

**Subagent-Driven Development:**
- Review after EACH task
- Catch issues before they compound
- Fix before moving to next task

**Executing Plans:**
- Review after each batch (3 tasks)
- Get feedback, apply, continue

**Ad-Hoc Development:**
- Review before merge
- Review when stuck

## Red Flags

**Never:**
- Skip review because "it's simple"
- Ignore Critical issues
- Proceed with unfixed Important issues
- Argue with valid technical feedback

**If reviewer wrong:**
- Push back with technical reasoning
- Show code/tests that prove it works
- Request clarification

See template at: requesting-code-review/code-reviewer.md

codex
I’m gathering the exact current line references now: the investigation record, the hardening commit, and the bridge/transport code paths involved in REQ/REP startup. Since this workspace is read-only in the current session, I’ll verify whether I can write the requested response file before claiming it exists.
exec
/opt/homebrew/bin/bash -lc "sed -n '1,260p' docs/decisions/2026-04-24-b2b4fb5-investigation.md" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
# 2026-04-24 — b2b4fb5 hypothesis investigation

## Mission

Determine whether commit `b2b4fb5` (2026-04-23 15:10, "harden B1
capture bridge startup validation") is incompatible with the `ipc://`
transport introduced by IV.7, and if so whether this incompatibility
caused the 2026-04-23 ~16:30 IV.7 runtime failure to be misattributed
to the ipc:// switch itself.

## Verdict: **H3 CONFIRMED**

`b2b4fb5`'s synchronous startup probe `_validate_bridge_startup()`
fails against a fresh ipc://-bound engine because the engine's REP
socket is not yet ready when the probe fires. The probe returns
`{"ok": false, "error": "Engine не отвечает (Resource temporarily
unavailable)"}` (a `zmq.Again` surfaced from the bridge subprocess),
and the capture tool aborts at cmd #0.

Once the engine has had time to bind the ipc socket and open its REP
handler, the same transport works normally — 20 consecutive samples
succeeded against ipc:// with the hardening reverted.

**IV.7 failure on 2026-04-23 was not caused by the ipc:// transport
itself. It was caused by the hardening probe's startup race with
ipc:// bind timing.**

## Skill loaded

Skill `multi-model-consultation` was loaded manually with a `Read`
tool call at session start, because the harness skill-registry
snapshot did not include it (skill was created and committed
mid-session 2026-04-23 via `9a1a100`, after the registry scan).
Open item for ORCHESTRATION.md edit: document that skill registry
refresh requires harness restart.

## 00:05 — Phase 1 self-analysis (revised mid-analysis)

### Initial reading (code inspection only)

Thesis: `b2b4fb5` only touches `tools/diag_zmq_b1_capture.py` and its
test. Post-b2b4fb5 commits (`157c4bc`, `63a3fed`) touched different
files. The hardening code itself uses `bridge.is_alive()` (a
`multiprocessing.Process.is_alive()` call) and `bridge.send_command()`
(a queue-dispatched wrapper), both transport-agnostic.

Concluded: H3 falsified by source-code inspection. No tcp-specific
identifiers in hardening patch.

### Revised reading (after discovering evidence log)

`/tmp/diag_iv7_capture.log` exists on disk from the 2026-04-23 IV.7
test attempt. Its single line reads:

    B1 capture aborted: Bridge startup probe failed:
    {'ok': False, 'error': 'Engine не отвечает (Resource temporarily unavailable)'}

This is the **exact literal output** of `_validate_bridge_startup`
from `b2b4fb5`. The tool used for the IV.7 test was `diag_zmq_b1_capture.py`
(contrary to `docs/NEXT_SESSION.md` step 4 which referenced
`diag_zmq_bridge_extended.py`), and the hardening aborted the run
at cmd #0.

Revised thesis: even though the hardening code is transport-agnostic
at the abstraction layer, it introduces a synchronous check at an
earlier-than-before point in the startup lifecycle. Under tcp://
loopback, connect()+send()+recv() with a short retry is effectively
instantaneous, so the check tends to pass. Under ipc://, socket-file
existence and REP bind-completion are not instantaneous — the
engine side may still be binding when the bridge subprocess fires
its first REQ. The bridge returns `zmq.Again` to the hardening, which
treats it as a hard failure.

Decision: this warrants empirical confirmation. Proceed to Phase 3.
Phase 2 (Codex consultation) skipped per skill §0 — evidence is
concrete, not ambiguous.

Consulted: none.
Open: refined thesis not yet empirically verified.

## 00:18 — Phase 3 empirical verification

### 00:15 — Extended diag against ipc:// engine (bridge_extended.py)

Worktree `.worktrees/experiment-iv7-ipc-transport` (branch
`experiment/iv7-ipc-transport` at `63a3fed`).
- Ran `git revert --no-commit b2b4fb5` — clean revert, 2 files
  modified (tool + its test).
- Restarted engine from worktree source (`PYTHONPATH=$(pwd)/src` +
  `CRYODAQ_ROOT=$(pwd)`) in `--mock` mode.
- Engine bound to `ipc:///tmp/cryodaq-pub.sock` and
  `ipc:///tmp/cryodaq-cmd.sock` (Unix default from
  `zmq_transport.py`).
- Ran `tools/diag_zmq_bridge_extended.py` — 180s soak.

Result:
- Commands #1–#44: OK, 1-2ms each.
- Command #45 at uptime 79.1s: FAIL with 35 s timeout
  (`TimeoutError`).
- Commands #46–#48 (to end of 180s window): all FAIL with same 35s
  timeout.

Interpretation: **ipc:// transport itself works for ~80s**, then the
underlying B1 idle-death bug fires. This matches the pre-existing
B1 signature ("cmd #48 FAIL at uptime 82s", `HANDOFF_2026-04-20_GLM.md`
line 238). IV.7 did NOT fix B1 — it just changed the transport.

### 00:19 — b1_capture against degraded engine

After extended diag's failure at cmd #45 left the engine in the
B1 degraded state, ran `tools/diag_zmq_b1_capture.py` (short,
30s) against the same engine process.

Result: `bridge_reply: {"ok": false, "error": "Engine не отвечает
(Resource temporarily unavailable)"}`, `direct_reply: TimeoutError`.
Only 1 sample captured, all fields showing stalled cmd plane.

Interpretation: confirms engine is in the B1 degraded state, not a
startup issue. Can't directly test hardening hypothesis from this
state. Need fresh engine.

### 00:20 — b1_capture against FRESH engine with b2b4fb5 reverted

Killed engine, removed sockets + lock, relaunched from worktree
source. Waited 4s for engine to bind. Ran
`tools/diag_zmq_b1_capture.py --duration 20 --interval 1`.

Result:
- 20/20 samples successful.
- `bridge_reply: {"ok": true, "state": "ready", ...}`.
- `direct_reply: {"ok": true, ...}`.

Interpretation: **with the hardening reverted, b1_capture runs
normally against ipc://**. The exact same tool with the exact same
transport at the exact same codebase tip, minus only the b2b4fb5
changes, succeeds.

### 00:22 — Phase 3 cleanup

- `kill` engine process, `rm` ipc sockets.
- `git reset --hard` in worktree → back to `63a3fed`.
- Branch tip intact: `63a3fed`, `157c4bc`, `b2b4fb5`, ... preserved.
- 3 untracked files (prior session plans + handoff response) in
  worktree not touched.

## Evidence summary

| scenario | hardening | transport | engine age at cmd#1 | result |
|---|---|---|---|---|
| IV.7 2026-04-23 failure | present | ipc:// | ~fresh (< 1s) | **abort at cmd#0** — "Engine не отвечает" |
| retest 2026-04-24 (bridge_extended) | reverted | ipc:// | 4s | 44/44 early OK, B1 idle-death at cmd #45 |
| retest 2026-04-24 (b1_capture against degraded engine) | reverted | ipc:// | ~4 min | fail (engine already broken by B1) |
| retest 2026-04-24 (b1_capture against fresh engine) | reverted | ipc:// | 4s | **20/20 OK** |

The controlling variable is the presence of the b2b4fb5 hardening
probe combined with engine age at cmd #1. Reverting the hardening
makes b1_capture pass on ipc://.

## Phase 4 — decision

### What this proves

1. IV.7's `ipc://` transport is viable. It runs normally for the
   first ~80 seconds of engine uptime against ipc sockets.
2. `b2b4fb5`'s startup probe is incompatible with ipc:// at engine
   boot time. The race window is in the first few hundred ms where
   engine REP hasn't bound yet.
3. The 2026-04-23 16:30 "IV.7 failed" narrative was a
   misattribution: b2b4fb5 aborted the diag capture before IV.7's
   transport ever had a chance to demonstrate anything.

### What this does NOT prove

4. **B1 idle-death is unrelated to b2b4fb5.** B1 fires at ~80s
   uptime regardless of hardening presence. IV.7 did not fix B1.
   Next hypotheses (H4 pyzmq/asyncio, H5 engine REP state) remain
   viable and need separate tests.

### Recommended next action

Architect decision required on hardening repair strategy:

**Option R1 — fix b2b4fb5 to be startup-race-tolerant.**
Rework `_validate_bridge_startup()` to retry the probe with bounded
backoff (e.g., 5 × 200ms) instead of single-shot. This makes it work
for both tcp and ipc without losing the guard against subprocess
spawn failures.

**Option R2 — move readiness into `bridge.start()`.**
Have `ZmqBridge.start()` block until the subprocess reports its REQ
socket has successfully received at least one reply, then return.
The diag tool's hardening check then just verifies `is_alive()`,
which is already correct.

**Option R3 — revert b2b4fb5 and accept no startup guard.**
Cheapest, but loses the catch for real subprocess-start failures.

Architect pick R1 / R2 / R3. Subsequent CC session can implement.

Merge path for IV.7:
- If R1 or R2: fix first, then merge `experiment/iv7-ipc-transport`
  and `codex/safe-merge-b1-truth-recovery` → `master`, tag `v0.34.0`,
  **but note**: IV.7 does NOT close B1. B1 investigation continues
  with H4/H5 as separate tasks.
- If R3: straight revert of `b2b4fb5`, merge iv7 → master, tag
  `v0.34.0`.

### Residual risks

- The startup race may be platform-dependent. macOS Unix-socket
  bind might be slower than Linux. Confirmation on lab Ubuntu PC
  needed before tagging v0.34.0.
- IV.7's `_prepare_ipc_path` cleans up stale sockets but still
  has a narrow window between `_cleanup_ipc_path_if_safe` and
  the bind. Unlikely to matter in practice but worth a line of
  defensive logging.
- The mock engine may not exercise the same bind timing as real
  hardware. Real-hardware verification should be part of the
  v0.34.0 gate.

## Related files

- `tools/diag_zmq_b1_capture.py` — hardening lives here, lines
  69-76 on `b2b4fb5`
- `src/cryodaq/core/zmq_transport.py` — ipc:// defaults (iv7
  only)
- `src/cryodaq/launcher.py` — transport probe (63a3fed made
  ipc-aware; unrelated to the b2b4fb5 hardening issue)
- `/tmp/diag_iv7_capture.log` — original evidence of 2026-04-23
  failure signature
- `/tmp/b1_retest_fresh.jsonl` — 20/20 success with revert
- `/tmp/diag_iv7_retest.log` — 180s soak showing B1 idle-death
  signature on ipc://

## Open for next architect session

- Pick repair strategy: R1 / R2 / R3.
- After repair lands: retest on Ubuntu lab PC before tagging.
- B1 root cause still unknown. H4 (pyzmq/asyncio) and H5 (engine
  REP state machine) next.
- ORCHESTRATION.md edit: document skill-registry refresh requires
  harness restart.
- Skill consumption note: used Phase 1 self-analysis instead of
  Codex per skill §0; evidence was concrete, consultation would
  have been premature. Skill successfully guided restraint.

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/core/zmq_subprocess.py | sed -n '150,250p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   150	                if now - last_heartbeat >= HEARTBEAT_INTERVAL:
   151	                    with contextlib.suppress(queue.Full):
   152	                        data_queue.put_nowait({"__type": "heartbeat", "ts": now})
   153	                    last_heartbeat = now
   154	        finally:
   155	            sub.close(linger=0)
   156	
   157	    def cmd_forward_loop() -> None:
   158	        """Forward GUI commands via a fresh REQ socket per command.
   159	
   160	        IV.6 B1 fix: each command creates, uses, and closes its own REQ
   161	        socket. Shared long-lived REQ accumulated state across commands
   162	        and became permanently unrecoverable after a platform-specific
   163	        trigger (macOS sparse cadence within ~minutes, Ubuntu 120 s
   164	        deterministic). Ephemeral REQ per command matches ZeroMQ Guide
   165	        ch.4 canonical "poll / timeout / close / reopen" reliable
   166	        request-reply pattern.
   167	
   168	        May block up to 35 s per timed-out REQ. That does not starve
   169	        the data path because SUB drain runs on a separate thread.
   170	        A timed-out REQ emits a structured ``cmd_timeout`` control
   171	        message via data_queue so the launcher watchdog can detect
   172	        command-channel-only failures and restart the bridge.
   173	        """
   174	
   175	        def _new_req_socket():
   176	            """Build a fresh per-command REQ socket.
   177	
   178	            IV.6: REQ_RELAXED / REQ_CORRELATE dropped — they were only
   179	            useful for stateful recovery on a shared socket, which the
   180	            ephemeral model has eliminated. TCP_KEEPALIVE dropped from
   181	            the command path (reverting the f5f9039 partial fix) —
   182	            Codex revised analysis confirmed idle-reap was not the
   183	            actual cause; keepalive is a no-op here and clutters
   184	            debugging of the real socket state.
   185	            """
   186	            req = ctx.socket(zmq.REQ)
   187	            req.setsockopt(zmq.LINGER, 0)
   188	            # IV.3 Finding 7: REQ timeout stays at 35 s so a slow
   189	            # server-side handler (experiment_finalize / report
   190	            # generation, tiered at 30 s) has room to reply before
   191	            # the REQ side gives up. Server's 30 s ceiling + 5 s slack
   192	            # stays inside the client's 35 s future wait
   193	            # (_CMD_REPLY_TIMEOUT_S), so timeouts at each layer fire
   194	            # in predictable order: server → subprocess → GUI future.
   195	            req.setsockopt(zmq.RCVTIMEO, 35000)
   196	            req.setsockopt(zmq.SNDTIMEO, 35000)
   197	            req.connect(cmd_addr)
   198	            return req
   199	
   200	        while not shutdown_event.is_set():
   201	            try:
   202	                cmd = cmd_queue.get(timeout=0.5)
   203	            except queue.Empty:
   204	                continue
   205	            rid = cmd.pop("_rid", None) if isinstance(cmd, dict) else None
   206	            cmd_type = cmd.get("cmd", "?") if isinstance(cmd, dict) else "?"
   207	
   208	            # Fresh socket per command — no shared state across commands.
   209	            req = _new_req_socket()
   210	            try:
   211	                try:
   212	                    req.send_string(json.dumps(cmd))
   213	                    reply_raw = req.recv_string()
   214	                    reply = json.loads(reply_raw)
   215	                except zmq.ZMQError as exc:
   216	                    reply = {"ok": False, "error": f"Engine не отвечает ({exc})"}
   217	                    with contextlib.suppress(queue.Full):
   218	                        data_queue.put_nowait(
   219	                            {
   220	                                "__type": "cmd_timeout",
   221	                                "cmd": cmd_type,
   222	                                "ts": time.monotonic(),
   223	                                "message": f"REP timeout on {cmd_type} ({exc})",
   224	                            }
   225	                        )
   226	                except Exception as exc:  # noqa: BLE001
   227	                    reply = {"ok": False, "error": str(exc)}
   228	            finally:
   229	                req.close(linger=0)
   230	
   231	            if rid is not None:
   232	                reply["_rid"] = rid
   233	            try:
   234	                reply_queue.put(reply, timeout=2.0)
   235	            except queue.Full:
   236	                with contextlib.suppress(queue.Full):
   237	                    data_queue.put_nowait(
   238	                        {"__type": "warning", "message": "Reply queue overflow"}
   239	                    )
   240	
   241	    sub_thread = threading.Thread(target=sub_drain_loop, name="zmq-sub-drain", daemon=True)
   242	    cmd_thread = threading.Thread(target=cmd_forward_loop, name="zmq-cmd-forward", daemon=True)
   243	
   244	    try:
   245	        sub_thread.start()
   246	        cmd_thread.start()
   247	        while not shutdown_event.is_set():
   248	            shutdown_event.wait(timeout=0.5)
   249	    except KeyboardInterrupt:
   250	        pass

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/core/zmq_transport.py | sed -n '1,260p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
nl: src/cryodaq/core/zmq_transport.py: No such file or directory

exec
/opt/homebrew/bin/bash -lc 'git show --stat --patch b2b4fb5 -- tools/diag_zmq_b1_capture.py' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
commit b2b4fb551e577c6bee972b6fc9ebe2a9b64a600a
Author: Vladimir Fomenko <polsovatel111@gmail.com>
Date:   Thu Apr 23 15:10:29 2026 +0300

    fix: harden B1 capture bridge startup validation
---
 tools/diag_zmq_b1_capture.py | 13 +++++++++++++
 1 file changed, 13 insertions(+)

diff --git a/tools/diag_zmq_b1_capture.py b/tools/diag_zmq_b1_capture.py
index cd4aee0..632090f 100644
--- a/tools/diag_zmq_b1_capture.py
+++ b/tools/diag_zmq_b1_capture.py
@@ -68,6 +68,14 @@ def _sample_once(
     return sample
 
 
+def _validate_bridge_startup(bridge: ZmqBridge) -> None:
+    if not bridge.is_alive():
+        raise RuntimeError("ZMQ bridge subprocess failed to start")
+    reply = bridge.send_command({"cmd": "safety_status"})
+    if not reply or reply.get("ok") is not True:
+        raise RuntimeError(f"Bridge startup probe failed: {reply!r}")
+
+
 def run_capture(
     bridge: ZmqBridge,
     *,
@@ -111,6 +119,11 @@ def main(argv: list[str] | None = None) -> int:
     bridge.start()
     time.sleep(1.0)
     try:
+        try:
+            _validate_bridge_startup(bridge)
+        except RuntimeError as exc:
+            print(f"B1 capture aborted: {exc}", file=sys.stderr)
+            return 1
         samples = run_capture(
             bridge,
             duration_s=args.duration,

exec
/opt/homebrew/bin/bash -lc "rg -n \"class ZmqBridge|def start|def is_alive|def send_command|_validate_bridge_startup\" src/cryodaq/gui/zmq_client.py tools/diag_zmq_b1_capture.py && nl -ba src/cryodaq/gui/zmq_client.py | sed -n '1,220p' && nl -ba tools/diag_zmq_b1_capture.py | sed -n '1,180p'" in /Users/vladimir/Projects/cryodaq
 exited 2 in 0ms:
rg: tools/diag_zmq_b1_capture.py: No such file or directory (os error 2)
src/cryodaq/gui/zmq_client.py:48:class ZmqBridge:
src/cryodaq/gui/zmq_client.py:96:    def start(self) -> None:
src/cryodaq/gui/zmq_client.py:140:    def is_alive(self) -> bool:
src/cryodaq/gui/zmq_client.py:213:    def send_command(self, cmd: dict) -> dict:
src/cryodaq/gui/zmq_client.py:310:def send_command(cmd: dict) -> dict:

codex
The cited transport file path does not exist at this checkout root, so I’m locating the renamed/current paths before deciding. The subprocess and GUI code are present, and the b2b4fb5 patch confirms the single-shot probe shape.
exec
/opt/homebrew/bin/bash -lc "pwd && rg --files | rg 'zmq_(transport|client|subprocess)|diag_zmq_b1_capture'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
/Users/vladimir/Projects/cryodaq
src/cryodaq/gui/zmq_client.py
tools/diag_zmq_subprocess.py
src/cryodaq/core/zmq_subprocess.py
tests/core/test_zmq_subprocess.py
tests/gui/test_zmq_client_data_flow_watchdog.py
tests/core/test_zmq_subprocess_ephemeral.py

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/gui/zmq_client.py | sed -n '1,260p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	"""ZMQ bridge client for GUI — all ZMQ lives in a subprocess.
     2	
     3	The GUI process never imports zmq. Communication with the subprocess
     4	is via multiprocessing.Queue. If libzmq crashes (signaler.cpp assertion
     5	on Windows), only the subprocess dies — GUI detects and restarts it.
     6	"""
     7	
     8	from __future__ import annotations
     9	
    10	import logging
    11	import multiprocessing as mp
    12	import queue
    13	import threading
    14	import time
    15	import uuid
    16	from concurrent.futures import Future
    17	from datetime import UTC, datetime
    18	from typing import Any
    19	
    20	from PySide6.QtCore import QThread, Signal
    21	
    22	from cryodaq.core.zmq_subprocess import (
    23	    DEFAULT_CMD_ADDR,
    24	    DEFAULT_PUB_ADDR,
    25	    zmq_bridge_main,
    26	)
    27	from cryodaq.drivers.base import ChannelStatus, Reading
    28	
    29	logger = logging.getLogger(__name__)
    30	
    31	_CMD_REPLY_TIMEOUT_S = 35.0  # IV.3 Finding 7: exceeds server 30 s ceiling
    32	
    33	
    34	def _reading_from_dict(d: dict[str, Any]) -> Reading:
    35	    """Reconstruct a Reading from a plain dict (received via mp.Queue)."""
    36	    return Reading(
    37	        timestamp=datetime.fromtimestamp(d["timestamp"], tz=UTC),
    38	        instrument_id=d.get("instrument_id", ""),
    39	        channel=d["channel"],
    40	        value=d["value"],
    41	        unit=d["unit"],
    42	        status=ChannelStatus(d["status"]),
    43	        raw=d.get("raw"),
    44	        metadata=d.get("metadata", {}),
    45	    )
    46	
    47	
    48	class ZmqBridge:
    49	    """GUI-side ZMQ bridge. No zmq import — all ZMQ lives in subprocess.
    50	
    51	    Usage::
    52	
    53	        bridge = ZmqBridge()
    54	        bridge.start()
    55	        # In QTimer tick:
    56	        for reading in bridge.poll_readings():
    57	            handle(reading)
    58	        # Commands:
    59	        reply = bridge.send_command({"cmd": "safety_status"})
    60	        # Shutdown:
    61	        bridge.shutdown()
    62	    """
    63	
    64	    def __init__(
    65	        self,
    66	        pub_addr: str = DEFAULT_PUB_ADDR,
    67	        cmd_addr: str = DEFAULT_CMD_ADDR,
    68	    ) -> None:
    69	        self._pub_addr = pub_addr
    70	        self._cmd_addr = cmd_addr
    71	        self._data_queue: mp.Queue = mp.Queue(maxsize=10_000)
    72	        self._cmd_queue: mp.Queue = mp.Queue(maxsize=1_000)
    73	        self._reply_queue: mp.Queue = mp.Queue(maxsize=1_000)
    74	        self._shutdown_event: mp.Event = mp.Event()
    75	        self._process: mp.Process | None = None
    76	        self._last_heartbeat: float = 0.0
    77	        # Data-flow watchdog: timestamp of the most recently drained
    78	        # actual reading (not heartbeat, not warning). Stays 0.0 until
    79	        # the first reading arrives so startup and between-experiment
    80	        # pauses don't trigger false-positive restarts.
    81	        self._last_reading_time: float = 0.0
    82	        # IV.6 B1 fix: timestamp of the most recent cmd_timeout control
    83	        # message emitted by the subprocess. Launcher watchdog uses
    84	        # ``command_channel_stalled()`` to detect command-channel-only
    85	        # failures where the data plane is still healthy but REQ/REP
    86	        # has entered a bad state.
    87	        self._last_cmd_timeout: float = 0.0
    88	        # Future-per-request command routing
    89	        self._pending: dict[str, Future] = {}
    90	        self._pending_lock = threading.Lock()
    91	        self._reply_stop = threading.Event()
    92	        self._reply_consumer: threading.Thread | None = None
    93	        # Hardening 2026-04-21: restart counter for B1 diagnostic correlation
    94	        self._restart_count: int = 0
    95	
    96	    def start(self) -> None:
    97	        """Start the ZMQ bridge subprocess."""
    98	        if self._process is not None and self._process.is_alive():
    99	            return
   100	        if self._reply_consumer is not None and self._reply_consumer.is_alive():
   101	            self._reply_stop.set()
   102	            self._reply_consumer.join(timeout=1.0)
   103	            self._reply_consumer = None
   104	        self._shutdown_event.clear()
   105	        # Drain stale queues
   106	        _drain(self._data_queue)
   107	        _drain(self._cmd_queue)
   108	        _drain(self._reply_queue)
   109	        self._process = mp.Process(
   110	            target=zmq_bridge_main,
   111	            args=(
   112	                self._pub_addr,
   113	                self._cmd_addr,
   114	                self._data_queue,
   115	                self._cmd_queue,
   116	                self._reply_queue,
   117	                self._shutdown_event,
   118	            ),
   119	            daemon=True,
   120	            name="zmq_bridge",
   121	        )
   122	        self._process.start()
   123	        self._last_heartbeat = time.monotonic()
   124	        self._last_reading_time = 0.0
   125	        # Start dedicated reply consumer thread
   126	        self._reply_stop.clear()
   127	        self._reply_consumer = threading.Thread(
   128	            target=self._consume_replies,
   129	            daemon=True,
   130	            name="zmq-reply-consumer",
   131	        )
   132	        self._reply_consumer.start()
   133	        self._restart_count += 1
   134	        logger.info(
   135	            "ZMQ bridge subprocess started (PID=%d, restart_count=%d)",
   136	            self._process.pid,
   137	            self._restart_count,
   138	        )
   139	
   140	    def is_alive(self) -> bool:
   141	        """Check if the subprocess is still running."""
   142	        return self._process is not None and self._process.is_alive()
   143	
   144	    def poll_readings(self) -> list[Reading]:
   145	        """Drain all available readings from the data queue. Non-blocking."""
   146	        readings: list[Reading] = []
   147	        while True:
   148	            try:
   149	                d = self._data_queue.get_nowait()
   150	                # Handle internal control messages from subprocess
   151	                msg_type = d.get("__type")
   152	                if msg_type == "heartbeat":
   153	                    self._last_heartbeat = time.monotonic()
   154	                    continue
   155	                if msg_type == "cmd_timeout":
   156	                    # IV.6 B1 fix: structured timeout marker used by the
   157	                    # launcher's command-channel watchdog. Separate from
   158	                    # "warning" because the launcher must restart the
   159	                    # bridge on this specific failure shape, not on
   160	                    # generic queue-overflow warnings.
   161	                    self._last_cmd_timeout = time.monotonic()
   162	                    logger.warning(
   163	                        "ZMQ bridge: %s",
   164	                        d.get("message", "command timeout"),
   165	                    )
   166	                    continue
   167	                if msg_type == "warning":
   168	                    logger.warning("ZMQ bridge: %s", d.get("message", ""))
   169	                    continue
   170	                self._last_reading_time = time.monotonic()
   171	                readings.append(_reading_from_dict(d))
   172	            except (queue.Empty, EOFError):
   173	                break
   174	            except Exception as exc:
   175	                logger.warning("poll_readings: error processing item: %s", exc)
   176	                continue
   177	        return readings
   178	
   179	    def heartbeat_stale(self, *, timeout_s: float = 30.0) -> bool:
   180	        """Return True if the bridge heartbeat is older than ``timeout_s``."""
   181	        return (
   182	            self._last_heartbeat != 0.0 and (time.monotonic() - self._last_heartbeat) >= timeout_s
   183	        )
   184	
   185	    def data_flow_stalled(self, *, timeout_s: float = 30.0) -> bool:
   186	        """Return True if readings previously flowed but are now stale."""
   187	        return (
   188	            self._last_reading_time != 0.0
   189	            and (time.monotonic() - self._last_reading_time) >= timeout_s
   190	        )
   191	
   192	    def command_channel_stalled(self, *, timeout_s: float = 10.0) -> bool:
   193	        """Return True if a command timeout occurred within the last
   194	        ``timeout_s`` seconds.
   195	
   196	        IV.6 B1 fix: used by launcher watchdog to detect command-channel-
   197	        only failures (data plane still healthy but commands fail). Single
   198	        recent timeout is enough to trigger — streak-count threshold may
   199	        be introduced later if field testing shows false positives.
   200	        """
   201	        if self._last_cmd_timeout == 0.0:
   202	            return False
   203	        return (time.monotonic() - self._last_cmd_timeout) < timeout_s
   204	
   205	    def is_healthy(self) -> bool:
   206	        """True if subprocess is alive and bridge heartbeats are fresh."""
   207	        return self.is_alive() and not self.heartbeat_stale()
   208	
   209	    def restart_count(self) -> int:
   210	        """Return the number of bridge restarts since launcher start."""
   211	        return self._restart_count
   212	
   213	    def send_command(self, cmd: dict) -> dict:
   214	        """Thread-safe command dispatch with Future-per-request correlation."""
   215	        if not self.is_alive():
   216	            return {"ok": False, "error": "ZMQ bridge subprocess not running"}
   217	
   218	        rid = uuid.uuid4().hex[:8]
   219	        cmd = {**cmd, "_rid": rid}
   220	        future: Future = Future()
   221	
   222	        with self._pending_lock:
   223	            self._pending[rid] = future
   224	
   225	        try:
   226	            self._cmd_queue.put(cmd, timeout=2.0)
   227	            return future.result(timeout=_CMD_REPLY_TIMEOUT_S)
   228	        except Exception as exc:
   229	            return {"ok": False, "error": f"Engine не отвечает ({type(exc).__name__}: {exc})"}
   230	        finally:
   231	            with self._pending_lock:
   232	                self._pending.pop(rid, None)
   233	
   234	    def _consume_replies(self) -> None:
   235	        """Dedicated thread: reads replies from subprocess, routes to correct Future."""
   236	        while not self._reply_stop.is_set():
   237	            try:
   238	                reply = self._reply_queue.get(timeout=0.5)
   239	            except queue.Empty:
   240	                continue
   241	            except (EOFError, OSError):
   242	                break
   243	
   244	            try:
   245	                if not isinstance(reply, dict):
   246	                    logger.warning("ZMQ reply consumer: non-dict reply: %r", type(reply))
   247	                    continue
   248	                rid = reply.pop("_rid", None)
   249	                if rid:
   250	                    with self._pending_lock:
   251	                        future = self._pending.get(rid)
   252	                    if future and not future.done():
   253	                        future.set_result(reply)
   254	                        continue
   255	                logger.debug("Unmatched ZMQ reply (rid=%s)", rid)
   256	            except Exception:
   257	                logger.exception("ZMQ reply consumer: error processing reply")
   258	
   259	    def shutdown(self) -> None:
   260	        """Signal subprocess to stop, cancel pending futures, wait for exit."""

exec
/opt/homebrew/bin/bash -lc 'git status --short && git branch --show-current && git rev-parse --short HEAD' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
?? .beads/
?? .coverage-thresholds.json
?? .env.example
?? .metaswarm/
?? .pre-commit-config.yaml
?? artifacts/consultations/
?? bin/
?? docs/decisions/ROADMAP_RESOLUTION_LEDGER.md
?? docs/runbooks/ROADMAP_REVIEW_PROMPT_CODEX.md
?? docs/runbooks/ROADMAP_REVIEW_PROMPT_GEMINI.md
?? docs/runbooks/ROADMAP_REVIEW_PROMPT_KIMI.md
?? docs/runbooks/ROADMAP_REVIEW_PROMPT_METASWARM.md
?? docs/superpowers/
?? scripts/beads-fetch-conversation-history.ts
?? scripts/beads-fetch-pr-comments.ts
master
57ca565

exec
/opt/homebrew/bin/bash -lc "git show b2b4fb5:tools/diag_zmq_b1_capture.py | nl -ba | sed -n '1,180p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	from __future__ import annotations
     2	
     3	import argparse
     4	import json
     5	import sys
     6	import time
     7	from datetime import UTC, datetime
     8	from pathlib import Path
     9	
    10	if __package__ in {None, ""}:
    11	    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    12	
    13	from cryodaq.gui.zmq_client import ZmqBridge
    14	from tools._b1_diagnostics import bridge_snapshot, direct_engine_probe
    15	from tools._zmq_helpers import DEFAULT_CMD_ADDR
    16	
    17	
    18	def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    19	    parser = argparse.ArgumentParser(
    20	        description=(
    21	            "Canonical B1 capture against current master. Records bridge-side "
    22	            "and direct-engine command health into JSONL."
    23	        )
    24	    )
    25	    parser.add_argument("--output", type=Path, required=True, help="JSONL artifact path.")
    26	    parser.add_argument("--duration", type=float, default=180.0, help="Capture length in seconds.")
    27	    parser.add_argument("--interval", type=float, default=1.0, help="Sample interval in seconds.")
    28	    parser.add_argument("--address", default=DEFAULT_CMD_ADDR, help="Direct engine REQ address.")
    29	    parser.add_argument(
    30	        "--direct-timeout",
    31	        type=float,
    32	        default=5.0,
    33	        help="Seconds to wait for the direct engine probe.",
    34	    )
    35	    parser.add_argument(
    36	        "--skip-direct-probe",
    37	        action="store_true",
    38	        help="Only record bridge-side command health.",
    39	    )
    40	    return parser.parse_args(argv)
    41	
    42	
    43	def _sample_once(
    44	    bridge: ZmqBridge,
    45	    *,
    46	    address: str,
    47	    direct_timeout_s: float,
    48	    skip_direct_probe: bool,
    49	) -> dict:
    50	    bridge.poll_readings()
    51	    sample = bridge_snapshot(bridge)
    52	    sample["ts_utc"] = datetime.now(UTC).isoformat()
    53	    sample["bridge_reply"] = bridge.send_command({"cmd": "safety_status"})
    54	    if skip_direct_probe:
    55	        sample["direct_reply"] = None
    56	    else:
    57	        try:
    58	            sample["direct_reply"] = direct_engine_probe(
    59	                address=address,
    60	                timeout_s=direct_timeout_s,
    61	            )
    62	        except TimeoutError as exc:
    63	            sample["direct_reply"] = {
    64	                "ok": False,
    65	                "error": str(exc),
    66	                "exception_type": type(exc).__name__,
    67	            }
    68	    return sample
    69	
    70	
    71	def _validate_bridge_startup(bridge: ZmqBridge) -> None:
    72	    if not bridge.is_alive():
    73	        raise RuntimeError("ZMQ bridge subprocess failed to start")
    74	    reply = bridge.send_command({"cmd": "safety_status"})
    75	    if not reply or reply.get("ok") is not True:
    76	        raise RuntimeError(f"Bridge startup probe failed: {reply!r}")
    77	
    78	
    79	def run_capture(
    80	    bridge: ZmqBridge,
    81	    *,
    82	    duration_s: float,
    83	    interval_s: float,
    84	    output_path: Path,
    85	    address: str,
    86	    direct_timeout_s: float,
    87	    skip_direct_probe: bool,
    88	    now_fn=time.monotonic,
    89	    sleep_fn=time.sleep,
    90	) -> int:
    91	    output_path.parent.mkdir(parents=True, exist_ok=True)
    92	    deadline = now_fn() + duration_s
    93	    count = 0
    94	
    95	    with output_path.open("w", encoding="utf-8") as fh:
    96	        while True:
    97	            if now_fn() >= deadline:
    98	                break
    99	            sample = _sample_once(
   100	                bridge,
   101	                address=address,
   102	                direct_timeout_s=direct_timeout_s,
   103	                skip_direct_probe=skip_direct_probe,
   104	            )
   105	            count += 1
   106	            sample["seq"] = count
   107	            fh.write(json.dumps(sample, ensure_ascii=False) + "\n")
   108	            fh.flush()
   109	            if now_fn() >= deadline:
   110	                break
   111	            sleep_fn(interval_s)
   112	
   113	    return count
   114	
   115	
   116	def main(argv: list[str] | None = None) -> int:
   117	    args = _parse_args(argv)
   118	    bridge = ZmqBridge()
   119	    bridge.start()
   120	    time.sleep(1.0)
   121	    try:
   122	        try:
   123	            _validate_bridge_startup(bridge)
   124	        except RuntimeError as exc:
   125	            print(f"B1 capture aborted: {exc}", file=sys.stderr)
   126	            return 1
   127	        samples = run_capture(
   128	            bridge,
   129	            duration_s=args.duration,
   130	            interval_s=args.interval,
   131	            output_path=args.output,
   132	            address=args.address,
   133	            direct_timeout_s=args.direct_timeout,
   134	            skip_direct_probe=args.skip_direct_probe,
   135	        )
   136	    finally:
   137	        bridge.shutdown()
   138	    print(f"Wrote {samples} samples to {args.output}")
   139	    return 0
   140	
   141	
   142	if __name__ == "__main__":
   143	    sys.exit(main())

exec
/opt/homebrew/bin/bash -lc "git show --name-status --oneline 157c4bc && git show 157c4bc:src/cryodaq/core/zmq_transport.py | nl -ba | sed -n '1,260p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
157c4bc Add shared ZMQ transport defaults
M	src/cryodaq/core/zmq_bridge.py
M	src/cryodaq/core/zmq_subprocess.py
A	src/cryodaq/core/zmq_transport.py
A	tests/core/test_zmq_transport_defaults.py
M	tests/test_zmq_bind_recovery.py
     1	from __future__ import annotations
     2	
     3	import errno
     4	import os
     5	import socket
     6	import stat
     7	import sys
     8	from pathlib import Path
     9	
    10	
    11	def _default_transport_addrs() -> tuple[str, str]:
    12	    if sys.platform == "win32":
    13	        return ("tcp://127.0.0.1:5555", "tcp://127.0.0.1:5556")
    14	    return ("ipc:///tmp/cryodaq-pub.sock", "ipc:///tmp/cryodaq-cmd.sock")
    15	
    16	
    17	DEFAULT_PUB_ADDR, DEFAULT_CMD_ADDR = _default_transport_addrs()
    18	
    19	
    20	def ipc_path(addr: str) -> Path | None:
    21	    if not addr.startswith("ipc://"):
    22	        return None
    23	    return Path(addr[len("ipc://") :])
    24	
    25	
    26	def tcp_host_port(addr: str) -> tuple[str, int] | None:
    27	    if not addr.startswith("tcp://"):
    28	        return None
    29	    host_port = addr[len("tcp://") :]
    30	    host, port = host_port.rsplit(":", 1)
    31	    return host, int(port)
    32	
    33	
    34	def _ipc_path_is_live(path: Path) -> bool:
    35	    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    36	    try:
    37	        probe.settimeout(0.1)
    38	        probe.connect(os.fspath(path))
    39	    except OSError as exc:
    40	        if exc.errno in {errno.ECONNREFUSED, errno.ENOENT}:
    41	            return False
    42	        raise FileExistsError(f"Refusing to remove IPC path with unknown state: {path}") from exc
    43	    finally:
    44	        probe.close()
    45	    return True
    46	
    47	
    48	def _cleanup_ipc_path_if_safe(path: Path) -> None:
    49	    try:
    50	        path_stat = path.lstat()
    51	    except FileNotFoundError:
    52	        return
    53	    if not stat.S_ISSOCK(path_stat.st_mode):
    54	        raise FileExistsError(f"Refusing to remove non-socket IPC path: {path}")
    55	    if _ipc_path_is_live(path):
    56	        raise FileExistsError(f"Refusing to remove live IPC endpoint: {path}")
    57	    os.unlink(path)
    58	
    59	
    60	def prepare_ipc_path(addr: str) -> None:
    61	    path = ipc_path(addr)
    62	    if path is None:
    63	        return
    64	    path.parent.mkdir(parents=True, exist_ok=True)
    65	    _cleanup_ipc_path_if_safe(path)
    66	
    67	
    68	def cleanup_ipc_path(addr: str) -> None:
    69	    path = ipc_path(addr)
    70	    if path is None:
    71	        return
    72	    _cleanup_ipc_path_if_safe(path)

exec
/opt/homebrew/bin/bash -lc "git show HEAD:src/cryodaq/core/zmq_subprocess.py | nl -ba | sed -n '1,150p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	"""ZMQ bridge running in a separate process.
     2	
     3	This process owns ALL ZMQ sockets. If libzmq crashes (signaler.cpp
     4	assertion on Windows), only this subprocess dies. The GUI detects
     5	the death via is_alive() and restarts it.
     6	
     7	The GUI process never imports zmq.
     8	
     9	Threading model (see fix(gui): split bridge subprocess ...):
    10	- sub_drain owns the SUB socket, receives readings, emits heartbeats.
    11	  Heartbeat comes from this thread so it proves the *data* path is alive.
    12	- cmd_forward owns the REQ socket, sends commands and waits up to 3s
    13	  per reply. May block; does not affect sub_drain.
    14	- Main thread starts both threads and waits on shutdown_event.
    15	"""
    16	
    17	from __future__ import annotations
    18	
    19	import contextlib
    20	import json
    21	import logging
    22	import multiprocessing as mp
    23	import queue
    24	import threading
    25	import time
    26	from typing import Any
    27	
    28	logger = logging.getLogger(__name__)
    29	
    30	# Re-export constants so GUI code doesn't need to import zmq_bridge
    31	DEFAULT_PUB_ADDR = "tcp://127.0.0.1:5555"
    32	DEFAULT_CMD_ADDR = "tcp://127.0.0.1:5556"
    33	# Mirror of zmq_bridge.DEFAULT_TOPIC. Duplicated (not imported) because this
    34	# module is loaded in the GUI process, which must not import zmq/zmq_bridge
    35	# at module scope. Keep in sync with cryodaq.core.zmq_bridge.DEFAULT_TOPIC.
    36	DEFAULT_TOPIC = b"readings"
    37	
    38	
    39	def _unpack_reading_dict(payload: bytes) -> dict[str, Any]:
    40	    """Unpack msgpack Reading into a plain dict (picklable for mp.Queue)."""
    41	    import msgpack
    42	
    43	    data = msgpack.unpackb(payload, raw=False)
    44	    return {
    45	        "timestamp": data["ts"],
    46	        "instrument_id": data.get("iid", ""),
    47	        "channel": data["ch"],
    48	        "value": data["v"],
    49	        "unit": data["u"],
    50	        "status": data["st"],
    51	        "raw": data.get("raw"),
    52	        "metadata": data.get("meta", {}),
    53	    }
    54	
    55	
    56	def zmq_bridge_main(
    57	    pub_addr: str,
    58	    cmd_addr: str,
    59	    data_queue: mp.Queue,
    60	    cmd_queue: mp.Queue,
    61	    reply_queue: mp.Queue,
    62	    shutdown_event: mp.Event,
    63	) -> None:
    64	    """Entry point for ZMQ bridge subprocess.
    65	
    66	    Parameters
    67	    ----------
    68	    pub_addr:
    69	        Engine PUB address, e.g. "tcp://127.0.0.1:5555".
    70	    cmd_addr:
    71	        Engine REP address, e.g. "tcp://127.0.0.1:5556".
    72	    data_queue:
    73	        Subprocess → GUI: Reading dicts plus control messages
    74	        (``__type`` in {"heartbeat", "warning"}).
    75	    cmd_queue:
    76	        GUI → subprocess: command dicts to send via REQ.
    77	    reply_queue:
    78	        Subprocess → GUI: command reply dicts.
    79	    shutdown_event:
    80	        Set by GUI to signal clean shutdown.
    81	    """
    82	    import zmq
    83	
    84	    HEARTBEAT_INTERVAL = 5.0  # seconds — keep generous vs is_healthy() threshold
    85	
    86	    ctx = zmq.Context()
    87	
    88	    dropped_counter = {"n": 0}
    89	
    90	    def sub_drain_loop() -> None:
    91	        """Own SUB socket; drain readings and emit periodic heartbeats.
    92	
    93	        Heartbeat comes from this thread (not the command thread) so
    94	        the GUI's heartbeat freshness check proves the *data* path is
    95	        alive, not just that the subprocess exists.
    96	        """
    97	        # Order matters: connect() BEFORE subscribe(). The inverse pattern
    98	        # (subscribe-before-connect with setsockopt_string(SUBSCRIBE, "")) produced
    99	        # zero received messages on macOS Python 3.14 pyzmq 25+.
   100	        sub = ctx.socket(zmq.SUB)
   101	        sub.setsockopt(zmq.LINGER, 0)
   102	        sub.setsockopt(zmq.RCVTIMEO, 100)
   103	        # 2026-04-20 idle-death fix: same keepalive as REQ side to
   104	        # survive macOS kernel idle reaping. SUB normally gets a
   105	        # stream of readings so idle is rare, but between-experiment
   106	        # quiet periods exist (scheduler paused, no active polls).
   107	        sub.setsockopt(zmq.TCP_KEEPALIVE, 1)
   108	        sub.setsockopt(zmq.TCP_KEEPALIVE_IDLE, 10)
   109	        sub.setsockopt(zmq.TCP_KEEPALIVE_INTVL, 5)
   110	        sub.setsockopt(zmq.TCP_KEEPALIVE_CNT, 3)
   111	        sub.connect(pub_addr)
   112	        sub.subscribe(DEFAULT_TOPIC)
   113	        last_heartbeat = time.monotonic()
   114	        try:
   115	            while not shutdown_event.is_set():
   116	                # SUB: blocking receive with 100ms RCVTIMEO. Keeps the loop
   117	                # responsive for shutdown and heartbeat emission.
   118	                try:
   119	                    parts = sub.recv_multipart()
   120	                    if len(parts) == 2:
   121	                        try:
   122	                            reading_dict = _unpack_reading_dict(parts[1])
   123	                        except Exception:
   124	                            reading_dict = None  # skip malformed
   125	                        if reading_dict is not None:
   126	                            try:
   127	                                data_queue.put_nowait(reading_dict)
   128	                            except queue.Full:
   129	                                dropped_counter["n"] += 1
   130	                                if dropped_counter["n"] % 100 == 1:
   131	                                    with contextlib.suppress(queue.Full):
   132	                                        data_queue.put_nowait(
   133	                                            {
   134	                                                "__type": "warning",
   135	                                                "message": (
   136	                                                    f"Queue overflow: "
   137	                                                    f"{dropped_counter['n']} readings dropped"
   138	                                                ),
   139	                                            }
   140	                                        )
   141	                except zmq.Again:
   142	                    pass
   143	                except zmq.ZMQError:
   144	                    if shutdown_event.is_set():
   145	                        break
   146	                    # Unexpected socket error — swallow and continue.
   147	                    time.sleep(0.01)
   148	
   149	                now = time.monotonic()
   150	                if now - last_heartbeat >= HEARTBEAT_INTERVAL:

exec
/opt/homebrew/bin/bash -lc 'git log --oneline --decorate --all -- tools/diag_zmq_b1_capture.py src/cryodaq/core/zmq_transport.py | head -40' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
157c4bc Add shared ZMQ transport defaults
b2b4fb5 (codex/safe-merge-b1-truth-recovery) fix: harden B1 capture bridge startup validation
2ed975f tools: record direct probe timeouts in B1 capture
983480d tools: align B1 capture CLI with jsonl master capture
056a199 tools: add canonical B1 capture CLI

exec
/opt/homebrew/bin/bash -lc "git show codex/safe-merge-b1-truth-recovery:src/cryodaq/core/zmq_subprocess.py | nl -ba | sed -n '1,260p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	"""ZMQ bridge running in a separate process.
     2	
     3	This process owns ALL ZMQ sockets. If libzmq crashes (signaler.cpp
     4	assertion on Windows), only this subprocess dies. The GUI detects
     5	the death via is_alive() and restarts it.
     6	
     7	The GUI process never imports zmq.
     8	
     9	Threading model (see fix(gui): split bridge subprocess ...):
    10	- sub_drain owns the SUB socket, receives readings, emits heartbeats.
    11	  Heartbeat comes from this thread so it proves the *data* path is alive.
    12	- cmd_forward owns the REQ socket, sends commands and waits up to 3s
    13	  per reply. May block; does not affect sub_drain.
    14	- Main thread starts both threads and waits on shutdown_event.
    15	"""
    16	
    17	from __future__ import annotations
    18	
    19	import contextlib
    20	import json
    21	import logging
    22	import multiprocessing as mp
    23	import queue
    24	import threading
    25	import time
    26	from typing import Any
    27	
    28	logger = logging.getLogger(__name__)
    29	
    30	# Re-export constants so GUI code doesn't need to import zmq_bridge
    31	DEFAULT_PUB_ADDR = "tcp://127.0.0.1:5555"
    32	DEFAULT_CMD_ADDR = "tcp://127.0.0.1:5556"
    33	# Mirror of zmq_bridge.DEFAULT_TOPIC. Duplicated (not imported) because this
    34	# module is loaded in the GUI process, which must not import zmq/zmq_bridge
    35	# at module scope. Keep in sync with cryodaq.core.zmq_bridge.DEFAULT_TOPIC.
    36	DEFAULT_TOPIC = b"readings"
    37	
    38	
    39	def _unpack_reading_dict(payload: bytes) -> dict[str, Any]:
    40	    """Unpack msgpack Reading into a plain dict (picklable for mp.Queue)."""
    41	    import msgpack
    42	
    43	    data = msgpack.unpackb(payload, raw=False)
    44	    return {
    45	        "timestamp": data["ts"],
    46	        "instrument_id": data.get("iid", ""),
    47	        "channel": data["ch"],
    48	        "value": data["v"],
    49	        "unit": data["u"],
    50	        "status": data["st"],
    51	        "raw": data.get("raw"),
    52	        "metadata": data.get("meta", {}),
    53	    }
    54	
    55	
    56	def zmq_bridge_main(
    57	    pub_addr: str,
    58	    cmd_addr: str,
    59	    data_queue: mp.Queue,
    60	    cmd_queue: mp.Queue,
    61	    reply_queue: mp.Queue,
    62	    shutdown_event: mp.Event,
    63	) -> None:
    64	    """Entry point for ZMQ bridge subprocess.
    65	
    66	    Parameters
    67	    ----------
    68	    pub_addr:
    69	        Engine PUB address, e.g. "tcp://127.0.0.1:5555".
    70	    cmd_addr:
    71	        Engine REP address, e.g. "tcp://127.0.0.1:5556".
    72	    data_queue:
    73	        Subprocess → GUI: Reading dicts plus control messages
    74	        (``__type`` in {"heartbeat", "warning"}).
    75	    cmd_queue:
    76	        GUI → subprocess: command dicts to send via REQ.
    77	    reply_queue:
    78	        Subprocess → GUI: command reply dicts.
    79	    shutdown_event:
    80	        Set by GUI to signal clean shutdown.
    81	    """
    82	    import zmq
    83	
    84	    HEARTBEAT_INTERVAL = 5.0  # seconds — keep generous vs is_healthy() threshold
    85	
    86	    ctx = zmq.Context()
    87	
    88	    dropped_counter = {"n": 0}
    89	
    90	    def sub_drain_loop() -> None:
    91	        """Own SUB socket; drain readings and emit periodic heartbeats.
    92	
    93	        Heartbeat comes from this thread (not the command thread) so
    94	        the GUI's heartbeat freshness check proves the *data* path is
    95	        alive, not just that the subprocess exists.
    96	        """
    97	        # Order matters: connect() BEFORE subscribe(). The inverse pattern
    98	        # (subscribe-before-connect with setsockopt_string(SUBSCRIBE, "")) produced
    99	        # zero received messages on macOS Python 3.14 pyzmq 25+.
   100	        sub = ctx.socket(zmq.SUB)
   101	        sub.setsockopt(zmq.LINGER, 0)
   102	        sub.setsockopt(zmq.RCVTIMEO, 100)
   103	        # 2026-04-20 idle-death fix: same keepalive as REQ side to
   104	        # survive macOS kernel idle reaping. SUB normally gets a
   105	        # stream of readings so idle is rare, but between-experiment
   106	        # quiet periods exist (scheduler paused, no active polls).
   107	        sub.setsockopt(zmq.TCP_KEEPALIVE, 1)
   108	        sub.setsockopt(zmq.TCP_KEEPALIVE_IDLE, 10)
   109	        sub.setsockopt(zmq.TCP_KEEPALIVE_INTVL, 5)
   110	        sub.setsockopt(zmq.TCP_KEEPALIVE_CNT, 3)
   111	        sub.connect(pub_addr)
   112	        sub.subscribe(DEFAULT_TOPIC)
   113	        last_heartbeat = time.monotonic()
   114	        try:
   115	            while not shutdown_event.is_set():
   116	                # SUB: blocking receive with 100ms RCVTIMEO. Keeps the loop
   117	                # responsive for shutdown and heartbeat emission.
   118	                try:
   119	                    parts = sub.recv_multipart()
   120	                    if len(parts) == 2:
   121	                        try:
   122	                            reading_dict = _unpack_reading_dict(parts[1])
   123	                        except Exception:
   124	                            reading_dict = None  # skip malformed
   125	                        if reading_dict is not None:
   126	                            try:
   127	                                data_queue.put_nowait(reading_dict)
   128	                            except queue.Full:
   129	                                dropped_counter["n"] += 1
   130	                                if dropped_counter["n"] % 100 == 1:
   131	                                    with contextlib.suppress(queue.Full):
   132	                                        data_queue.put_nowait(
   133	                                            {
   134	                                                "__type": "warning",
   135	                                                "message": (
   136	                                                    f"Queue overflow: "
   137	                                                    f"{dropped_counter['n']} readings dropped"
   138	                                                ),
   139	                                            }
   140	                                        )
   141	                except zmq.Again:
   142	                    pass
   143	                except zmq.ZMQError:
   144	                    if shutdown_event.is_set():
   145	                        break
   146	                    # Unexpected socket error — swallow and continue.
   147	                    time.sleep(0.01)
   148	
   149	                now = time.monotonic()
   150	                if now - last_heartbeat >= HEARTBEAT_INTERVAL:
   151	                    with contextlib.suppress(queue.Full):
   152	                        data_queue.put_nowait({"__type": "heartbeat", "ts": now})
   153	                    last_heartbeat = now
   154	        finally:
   155	            sub.close(linger=0)
   156	
   157	    def cmd_forward_loop() -> None:
   158	        """Forward GUI commands via a fresh REQ socket per command.
   159	
   160	        IV.6 B1 fix: each command creates, uses, and closes its own REQ
   161	        socket. Shared long-lived REQ accumulated state across commands
   162	        and became permanently unrecoverable after a platform-specific
   163	        trigger (macOS sparse cadence within ~minutes, Ubuntu 120 s
   164	        deterministic). Ephemeral REQ per command matches ZeroMQ Guide
   165	        ch.4 canonical "poll / timeout / close / reopen" reliable
   166	        request-reply pattern.
   167	
   168	        May block up to 35 s per timed-out REQ. That does not starve
   169	        the data path because SUB drain runs on a separate thread.
   170	        A timed-out REQ emits a structured ``cmd_timeout`` control
   171	        message via data_queue so the launcher watchdog can detect
   172	        command-channel-only failures and restart the bridge.
   173	        """
   174	
   175	        def _new_req_socket():
   176	            """Build a fresh per-command REQ socket.
   177	
   178	            IV.6: REQ_RELAXED / REQ_CORRELATE dropped — they were only
   179	            useful for stateful recovery on a shared socket, which the
   180	            ephemeral model has eliminated. TCP_KEEPALIVE dropped from
   181	            the command path (reverting the f5f9039 partial fix) —
   182	            Codex revised analysis confirmed idle-reap was not the
   183	            actual cause; keepalive is a no-op here and clutters
   184	            debugging of the real socket state.
   185	            """
   186	            req = ctx.socket(zmq.REQ)
   187	            req.setsockopt(zmq.LINGER, 0)
   188	            # IV.3 Finding 7: REQ timeout stays at 35 s so a slow
   189	            # server-side handler (experiment_finalize / report
   190	            # generation, tiered at 30 s) has room to reply before
   191	            # the REQ side gives up. Server's 30 s ceiling + 5 s slack
   192	            # stays inside the client's 35 s future wait
   193	            # (_CMD_REPLY_TIMEOUT_S), so timeouts at each layer fire
   194	            # in predictable order: server → subprocess → GUI future.
   195	            req.setsockopt(zmq.RCVTIMEO, 35000)
   196	            req.setsockopt(zmq.SNDTIMEO, 35000)
   197	            req.connect(cmd_addr)
   198	            return req
   199	
   200	        while not shutdown_event.is_set():
   201	            try:
   202	                cmd = cmd_queue.get(timeout=0.5)
   203	            except queue.Empty:
   204	                continue
   205	            rid = cmd.pop("_rid", None) if isinstance(cmd, dict) else None
   206	            cmd_type = cmd.get("cmd", "?") if isinstance(cmd, dict) else "?"
   207	
   208	            # Fresh socket per command — no shared state across commands.
   209	            req = _new_req_socket()
   210	            try:
   211	                try:
   212	                    req.send_string(json.dumps(cmd))
   213	                    reply_raw = req.recv_string()
   214	                    reply = json.loads(reply_raw)
   215	                except zmq.ZMQError as exc:
   216	                    reply = {"ok": False, "error": f"Engine не отвечает ({exc})"}
   217	                    with contextlib.suppress(queue.Full):
   218	                        data_queue.put_nowait(
   219	                            {
   220	                                "__type": "cmd_timeout",
   221	                                "cmd": cmd_type,
   222	                                "ts": time.monotonic(),
   223	                                "message": f"REP timeout on {cmd_type} ({exc})",
   224	                            }
   225	                        )
   226	                except Exception as exc:  # noqa: BLE001
   227	                    reply = {"ok": False, "error": str(exc)}
   228	            finally:
   229	                req.close(linger=0)
   230	
   231	            if rid is not None:
   232	                reply["_rid"] = rid
   233	            try:
   234	                reply_queue.put(reply, timeout=2.0)
   235	            except queue.Full:
   236	                with contextlib.suppress(queue.Full):
   237	                    data_queue.put_nowait(
   238	                        {"__type": "warning", "message": "Reply queue overflow"}
   239	                    )
   240	
   241	    sub_thread = threading.Thread(target=sub_drain_loop, name="zmq-sub-drain", daemon=True)
   242	    cmd_thread = threading.Thread(target=cmd_forward_loop, name="zmq-cmd-forward", daemon=True)
   243	
   244	    try:
   245	        sub_thread.start()
   246	        cmd_thread.start()
   247	        while not shutdown_event.is_set():
   248	            shutdown_event.wait(timeout=0.5)
   249	    except KeyboardInterrupt:
   250	        pass
   251	    finally:
   252	        shutdown_event.set()
   253	        sub_thread.join(timeout=2.0)
   254	        cmd_thread.join(timeout=4.0)
   255	        if sub_thread.is_alive() or cmd_thread.is_alive():
   256	            logger.warning("ZMQ bridge threads did not exit cleanly before context term")
   257	        ctx.term()

exec
/opt/homebrew/bin/bash -lc "git show codex/safe-merge-b1-truth-recovery:src/cryodaq/gui/zmq_client.py | nl -ba | sed -n '1,260p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	"""ZMQ bridge client for GUI — all ZMQ lives in a subprocess.
     2	
     3	The GUI process never imports zmq. Communication with the subprocess
     4	is via multiprocessing.Queue. If libzmq crashes (signaler.cpp assertion
     5	on Windows), only the subprocess dies — GUI detects and restarts it.
     6	"""
     7	
     8	from __future__ import annotations
     9	
    10	import logging
    11	import multiprocessing as mp
    12	import queue
    13	import threading
    14	import time
    15	import uuid
    16	from concurrent.futures import Future
    17	from datetime import UTC, datetime
    18	from typing import Any
    19	
    20	from PySide6.QtCore import QThread, Signal
    21	
    22	from cryodaq.core.zmq_subprocess import (
    23	    DEFAULT_CMD_ADDR,
    24	    DEFAULT_PUB_ADDR,
    25	    zmq_bridge_main,
    26	)
    27	from cryodaq.drivers.base import ChannelStatus, Reading
    28	
    29	logger = logging.getLogger(__name__)
    30	
    31	_CMD_REPLY_TIMEOUT_S = 35.0  # IV.3 Finding 7: exceeds server 30 s ceiling
    32	
    33	
    34	def _reading_from_dict(d: dict[str, Any]) -> Reading:
    35	    """Reconstruct a Reading from a plain dict (received via mp.Queue)."""
    36	    return Reading(
    37	        timestamp=datetime.fromtimestamp(d["timestamp"], tz=UTC),
    38	        instrument_id=d.get("instrument_id", ""),
    39	        channel=d["channel"],
    40	        value=d["value"],
    41	        unit=d["unit"],
    42	        status=ChannelStatus(d["status"]),
    43	        raw=d.get("raw"),
    44	        metadata=d.get("metadata", {}),
    45	    )
    46	
    47	
    48	class ZmqBridge:
    49	    """GUI-side ZMQ bridge. No zmq import — all ZMQ lives in subprocess.
    50	
    51	    Usage::
    52	
    53	        bridge = ZmqBridge()
    54	        bridge.start()
    55	        # In QTimer tick:
    56	        for reading in bridge.poll_readings():
    57	            handle(reading)
    58	        # Commands:
    59	        reply = bridge.send_command({"cmd": "safety_status"})
    60	        # Shutdown:
    61	        bridge.shutdown()
    62	    """
    63	
    64	    def __init__(
    65	        self,
    66	        pub_addr: str = DEFAULT_PUB_ADDR,
    67	        cmd_addr: str = DEFAULT_CMD_ADDR,
    68	    ) -> None:
    69	        self._pub_addr = pub_addr
    70	        self._cmd_addr = cmd_addr
    71	        self._data_queue: mp.Queue = mp.Queue(maxsize=10_000)
    72	        self._cmd_queue: mp.Queue = mp.Queue(maxsize=1_000)
    73	        self._reply_queue: mp.Queue = mp.Queue(maxsize=1_000)
    74	        self._shutdown_event: mp.Event = mp.Event()
    75	        self._process: mp.Process | None = None
    76	        self._last_heartbeat: float = 0.0
    77	        # Data-flow watchdog: timestamp of the most recently drained
    78	        # actual reading (not heartbeat, not warning). Stays 0.0 until
    79	        # the first reading arrives so startup and between-experiment
    80	        # pauses don't trigger false-positive restarts.
    81	        self._last_reading_time: float = 0.0
    82	        # IV.6 B1 fix: timestamp of the most recent cmd_timeout control
    83	        # message emitted by the subprocess. Launcher watchdog uses
    84	        # ``command_channel_stalled()`` to detect command-channel-only
    85	        # failures where the data plane is still healthy but REQ/REP
    86	        # has entered a bad state.
    87	        self._last_cmd_timeout: float = 0.0
    88	        # Future-per-request command routing
    89	        self._pending: dict[str, Future] = {}
    90	        self._pending_lock = threading.Lock()
    91	        self._reply_stop = threading.Event()
    92	        self._reply_consumer: threading.Thread | None = None
    93	        # Hardening 2026-04-21: restart counter for B1 diagnostic correlation
    94	        self._restart_count: int = 0
    95	
    96	    def start(self) -> None:
    97	        """Start the ZMQ bridge subprocess."""
    98	        if self._process is not None and self._process.is_alive():
    99	            return
   100	        if self._reply_consumer is not None and self._reply_consumer.is_alive():
   101	            self._reply_stop.set()
   102	            self._reply_consumer.join(timeout=1.0)
   103	            self._reply_consumer = None
   104	        self._shutdown_event.clear()
   105	        # Drain stale queues
   106	        _drain(self._data_queue)
   107	        _drain(self._cmd_queue)
   108	        _drain(self._reply_queue)
   109	        self._process = mp.Process(
   110	            target=zmq_bridge_main,
   111	            args=(
   112	                self._pub_addr,
   113	                self._cmd_addr,
   114	                self._data_queue,
   115	                self._cmd_queue,
   116	                self._reply_queue,
   117	                self._shutdown_event,
   118	            ),
   119	            daemon=True,
   120	            name="zmq_bridge",
   121	        )
   122	        self._process.start()
   123	        self._last_heartbeat = time.monotonic()
   124	        self._last_reading_time = 0.0
   125	        # Start dedicated reply consumer thread
   126	        self._reply_stop.clear()
   127	        self._reply_consumer = threading.Thread(
   128	            target=self._consume_replies,
   129	            daemon=True,
   130	            name="zmq-reply-consumer",
   131	        )
   132	        self._reply_consumer.start()
   133	        self._restart_count += 1
   134	        logger.info(
   135	            "ZMQ bridge subprocess started (PID=%d, restart_count=%d)",
   136	            self._process.pid,
   137	            self._restart_count,
   138	        )
   139	
   140	    def is_alive(self) -> bool:
   141	        """Check if the subprocess is still running."""
   142	        return self._process is not None and self._process.is_alive()
   143	
   144	    def poll_readings(self) -> list[Reading]:
   145	        """Drain all available readings from the data queue. Non-blocking."""
   146	        readings: list[Reading] = []
   147	        while True:
   148	            try:
   149	                d = self._data_queue.get_nowait()
   150	                # Handle internal control messages from subprocess
   151	                msg_type = d.get("__type")
   152	                if msg_type == "heartbeat":
   153	                    self._last_heartbeat = time.monotonic()
   154	                    continue
   155	                if msg_type == "cmd_timeout":
   156	                    # IV.6 B1 fix: structured timeout marker used by the
   157	                    # launcher's command-channel watchdog. Separate from
   158	                    # "warning" because the launcher must restart the
   159	                    # bridge on this specific failure shape, not on
   160	                    # generic queue-overflow warnings.
   161	                    self._last_cmd_timeout = time.monotonic()
   162	                    logger.warning(
   163	                        "ZMQ bridge: %s",
   164	                        d.get("message", "command timeout"),
   165	                    )
   166	                    continue
   167	                if msg_type == "warning":
   168	                    logger.warning("ZMQ bridge: %s", d.get("message", ""))
   169	                    continue
   170	                self._last_reading_time = time.monotonic()
   171	                readings.append(_reading_from_dict(d))
   172	            except (queue.Empty, EOFError):
   173	                break
   174	            except Exception as exc:
   175	                logger.warning("poll_readings: error processing item: %s", exc)
   176	                continue
   177	        return readings
   178	
   179	    def heartbeat_stale(self, *, timeout_s: float = 30.0) -> bool:
   180	        """Return True if the bridge heartbeat is older than ``timeout_s``."""
   181	        return (
   182	            self._last_heartbeat != 0.0 and (time.monotonic() - self._last_heartbeat) >= timeout_s
   183	        )
   184	
   185	    def data_flow_stalled(self, *, timeout_s: float = 30.0) -> bool:
   186	        """Return True if readings previously flowed but are now stale."""
   187	        return (
   188	            self._last_reading_time != 0.0
   189	            and (time.monotonic() - self._last_reading_time) >= timeout_s
   190	        )
   191	
   192	    def command_channel_stalled(self, *, timeout_s: float = 10.0) -> bool:
   193	        """Return True if a command timeout occurred within the last
   194	        ``timeout_s`` seconds.
   195	
   196	        IV.6 B1 fix: used by launcher watchdog to detect command-channel-
   197	        only failures (data plane still healthy but commands fail). Single
   198	        recent timeout is enough to trigger — streak-count threshold may
   199	        be introduced later if field testing shows false positives.
   200	        """
   201	        if self._last_cmd_timeout == 0.0:
   202	            return False
   203	        return (time.monotonic() - self._last_cmd_timeout) < timeout_s
   204	
   205	    def is_healthy(self) -> bool:
   206	        """True if subprocess is alive and bridge heartbeats are fresh."""
   207	        return self.is_alive() and not self.heartbeat_stale()
   208	
   209	    def restart_count(self) -> int:
   210	        """Return the number of bridge restarts since launcher start."""
   211	        return self._restart_count
   212	
   213	    def send_command(self, cmd: dict) -> dict:
   214	        """Thread-safe command dispatch with Future-per-request correlation."""
   215	        if not self.is_alive():
   216	            return {"ok": False, "error": "ZMQ bridge subprocess not running"}
   217	
   218	        rid = uuid.uuid4().hex[:8]
   219	        cmd = {**cmd, "_rid": rid}
   220	        future: Future = Future()
   221	
   222	        with self._pending_lock:
   223	            self._pending[rid] = future
   224	
   225	        try:
   226	            self._cmd_queue.put(cmd, timeout=2.0)
   227	            return future.result(timeout=_CMD_REPLY_TIMEOUT_S)
   228	        except Exception as exc:
   229	            return {"ok": False, "error": f"Engine не отвечает ({type(exc).__name__}: {exc})"}
   230	        finally:
   231	            with self._pending_lock:
   232	                self._pending.pop(rid, None)
   233	
   234	    def _consume_replies(self) -> None:
   235	        """Dedicated thread: reads replies from subprocess, routes to correct Future."""
   236	        while not self._reply_stop.is_set():
   237	            try:
   238	                reply = self._reply_queue.get(timeout=0.5)
   239	            except queue.Empty:
   240	                continue
   241	            except (EOFError, OSError):
   242	                break
   243	
   244	            try:
   245	                if not isinstance(reply, dict):
   246	                    logger.warning("ZMQ reply consumer: non-dict reply: %r", type(reply))
   247	                    continue
   248	                rid = reply.pop("_rid", None)
   249	                if rid:
   250	                    with self._pending_lock:
   251	                        future = self._pending.get(rid)
   252	                    if future and not future.done():
   253	                        future.set_result(reply)
   254	                        continue
   255	                logger.debug("Unmatched ZMQ reply (rid=%s)", rid)
   256	            except Exception:
   257	                logger.exception("ZMQ reply consumer: error processing reply")
   258	
   259	    def shutdown(self) -> None:
   260	        """Signal subprocess to stop, cancel pending futures, wait for exit."""

exec
/opt/homebrew/bin/bash -lc "git show codex/safe-merge-b1-truth-recovery:tools/diag_zmq_b1_capture.py | nl -ba | sed -n '1,180p'" in /Users/vladimir/Projects/cryodaq
exec
/opt/homebrew/bin/bash -lc "git show codex/safe-merge-b1-truth-recovery:src/cryodaq/core/zmq_transport.py | nl -ba | sed -n '1,180p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	from __future__ import annotations
     2	
     3	import argparse
     4	import json
     5	import sys
     6	import time
     7	from datetime import UTC, datetime
     8	from pathlib import Path
     9	
    10	if __package__ in {None, ""}:
    11	    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    12	
    13	from cryodaq.gui.zmq_client import ZmqBridge
    14	from tools._b1_diagnostics import bridge_snapshot, direct_engine_probe
    15	from tools._zmq_helpers import DEFAULT_CMD_ADDR
    16	
    17	
    18	def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    19	    parser = argparse.ArgumentParser(
    20	        description=(
    21	            "Canonical B1 capture against current master. Records bridge-side "
    22	            "and direct-engine command health into JSONL."
    23	        )
    24	    )
    25	    parser.add_argument("--output", type=Path, required=True, help="JSONL artifact path.")
    26	    parser.add_argument("--duration", type=float, default=180.0, help="Capture length in seconds.")
    27	    parser.add_argument("--interval", type=float, default=1.0, help="Sample interval in seconds.")
    28	    parser.add_argument("--address", default=DEFAULT_CMD_ADDR, help="Direct engine REQ address.")
    29	    parser.add_argument(
    30	        "--direct-timeout",
    31	        type=float,
    32	        default=5.0,
    33	        help="Seconds to wait for the direct engine probe.",
    34	    )
    35	    parser.add_argument(
    36	        "--skip-direct-probe",
    37	        action="store_true",
    38	        help="Only record bridge-side command health.",
    39	    )
    40	    return parser.parse_args(argv)
    41	
    42	
    43	def _sample_once(
    44	    bridge: ZmqBridge,
    45	    *,
    46	    address: str,
    47	    direct_timeout_s: float,
    48	    skip_direct_probe: bool,
    49	) -> dict:
    50	    bridge.poll_readings()
    51	    sample = bridge_snapshot(bridge)
    52	    sample["ts_utc"] = datetime.now(UTC).isoformat()
    53	    sample["bridge_reply"] = bridge.send_command({"cmd": "safety_status"})
    54	    if skip_direct_probe:
    55	        sample["direct_reply"] = None
    56	    else:
    57	        try:
    58	            sample["direct_reply"] = direct_engine_probe(
    59	                address=address,
    60	                timeout_s=direct_timeout_s,
    61	            )
    62	        except TimeoutError as exc:
    63	            sample["direct_reply"] = {
    64	                "ok": False,
    65	                "error": str(exc),
    66	                "exception_type": type(exc).__name__,
    67	            }
    68	    return sample
    69	
    70	
    71	def _validate_bridge_startup(bridge: ZmqBridge) -> None:
    72	    if not bridge.is_alive():
    73	        raise RuntimeError("ZMQ bridge subprocess failed to start")
    74	    reply = bridge.send_command({"cmd": "safety_status"})
    75	    if not reply or reply.get("ok") is not True:
    76	        raise RuntimeError(f"Bridge startup probe failed: {reply!r}")
    77	
    78	
    79	def run_capture(
    80	    bridge: ZmqBridge,
    81	    *,
    82	    duration_s: float,
    83	    interval_s: float,
    84	    output_path: Path,
    85	    address: str,
    86	    direct_timeout_s: float,
    87	    skip_direct_probe: bool,
    88	    now_fn=time.monotonic,
    89	    sleep_fn=time.sleep,
    90	) -> int:
    91	    output_path.parent.mkdir(parents=True, exist_ok=True)
    92	    deadline = now_fn() + duration_s
    93	    count = 0
    94	
    95	    with output_path.open("w", encoding="utf-8") as fh:
    96	        while True:
    97	            if now_fn() >= deadline:
    98	                break
    99	            sample = _sample_once(
   100	                bridge,
   101	                address=address,
   102	                direct_timeout_s=direct_timeout_s,
   103	                skip_direct_probe=skip_direct_probe,
   104	            )
   105	            count += 1
   106	            sample["seq"] = count
   107	            fh.write(json.dumps(sample, ensure_ascii=False) + "\n")
   108	            fh.flush()
   109	            if now_fn() >= deadline:
   110	                break
   111	            sleep_fn(interval_s)
   112	
   113	    return count
   114	
   115	
   116	def main(argv: list[str] | None = None) -> int:
   117	    args = _parse_args(argv)
   118	    bridge = ZmqBridge()
   119	    bridge.start()
   120	    time.sleep(1.0)
   121	    try:
   122	        try:
   123	            _validate_bridge_startup(bridge)
   124	        except RuntimeError as exc:
   125	            print(f"B1 capture aborted: {exc}", file=sys.stderr)
   126	            return 1
   127	        samples = run_capture(
   128	            bridge,
   129	            duration_s=args.duration,
   130	            interval_s=args.interval,
   131	            output_path=args.output,
   132	            address=args.address,
   133	            direct_timeout_s=args.direct_timeout,
   134	            skip_direct_probe=args.skip_direct_probe,
   135	        )
   136	    finally:
   137	        bridge.shutdown()
   138	    print(f"Wrote {samples} samples to {args.output}")
   139	    return 0
   140	
   141	
   142	if __name__ == "__main__":
   143	    sys.exit(main())

 succeeded in 0ms:
fatal: path 'src/cryodaq/core/zmq_transport.py' does not exist in 'codex/safe-merge-b1-truth-recovery'

codex
There are multiple branch states in play: `master` lacks the diagnostic tool and transport file, while the named b2b4fb5 branch has the tool but not IV.7. I’m cross-reading the IV.7 commit directly so the recommendation is about the combined behavior described in the investigation, not the current checked-out master alone.
exec
/opt/homebrew/bin/bash -lc 'git branch --all --contains 157c4bc && git branch --all --contains b2b4fb5' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
+ experiment/iv7-ipc-transport
  codex/safe-merge-b1-truth-recovery
+ experiment/iv7-ipc-transport

exec
/opt/homebrew/bin/bash -lc "git show 157c4bc:src/cryodaq/gui/zmq_client.py | nl -ba | sed -n '1,260p'" in /Users/vladimir/Projects/cryodaq
exec
/opt/homebrew/bin/bash -lc "git show 157c4bc:src/cryodaq/core/zmq_subprocess.py | nl -ba | sed -n '1,260p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	"""ZMQ bridge running in a separate process.
     2	
     3	This process owns ALL ZMQ sockets. If libzmq crashes (signaler.cpp
     4	assertion on Windows), only this subprocess dies. The GUI detects
     5	the death via is_alive() and restarts it.
     6	
     7	The GUI process never imports zmq.
     8	
     9	Threading model (see fix(gui): split bridge subprocess ...):
    10	- sub_drain owns the SUB socket, receives readings, emits heartbeats.
    11	  Heartbeat comes from this thread so it proves the *data* path is alive.
    12	- cmd_forward owns the REQ socket, sends commands and waits up to 3s
    13	  per reply. May block; does not affect sub_drain.
    14	- Main thread starts both threads and waits on shutdown_event.
    15	"""
    16	
    17	from __future__ import annotations
    18	
    19	import contextlib
    20	import json
    21	import logging
    22	import multiprocessing as mp
    23	import queue
    24	import threading
    25	import time
    26	from typing import Any
    27	
    28	from cryodaq.core.zmq_transport import DEFAULT_CMD_ADDR, DEFAULT_PUB_ADDR
    29	
    30	logger = logging.getLogger(__name__)
    31	
    32	# Re-export constants so GUI code doesn't need to import zmq_bridge
    33	# Mirror of zmq_bridge.DEFAULT_TOPIC. Duplicated (not imported) because this
    34	# module is loaded in the GUI process, which must not import zmq/zmq_bridge
    35	# at module scope. Keep in sync with cryodaq.core.zmq_bridge.DEFAULT_TOPIC.
    36	DEFAULT_TOPIC = b"readings"
    37	
    38	
    39	def _unpack_reading_dict(payload: bytes) -> dict[str, Any]:
    40	    """Unpack msgpack Reading into a plain dict (picklable for mp.Queue)."""
    41	    import msgpack
    42	
    43	    data = msgpack.unpackb(payload, raw=False)
    44	    return {
    45	        "timestamp": data["ts"],
    46	        "instrument_id": data.get("iid", ""),
    47	        "channel": data["ch"],
    48	        "value": data["v"],
    49	        "unit": data["u"],
    50	        "status": data["st"],
    51	        "raw": data.get("raw"),
    52	        "metadata": data.get("meta", {}),
    53	    }
    54	
    55	
    56	def zmq_bridge_main(
    57	    pub_addr: str,
    58	    cmd_addr: str,
    59	    data_queue: mp.Queue,
    60	    cmd_queue: mp.Queue,
    61	    reply_queue: mp.Queue,
    62	    shutdown_event: mp.Event,
    63	) -> None:
    64	    """Entry point for ZMQ bridge subprocess.
    65	
    66	    Parameters
    67	    ----------
    68	    pub_addr:
    69	        Engine PUB address, e.g. "tcp://127.0.0.1:5555".
    70	    cmd_addr:
    71	        Engine REP address, e.g. "tcp://127.0.0.1:5556".
    72	    data_queue:
    73	        Subprocess → GUI: Reading dicts plus control messages
    74	        (``__type`` in {"heartbeat", "warning"}).
    75	    cmd_queue:
    76	        GUI → subprocess: command dicts to send via REQ.
    77	    reply_queue:
    78	        Subprocess → GUI: command reply dicts.
    79	    shutdown_event:
    80	        Set by GUI to signal clean shutdown.
    81	    """
    82	    import zmq
    83	
    84	    HEARTBEAT_INTERVAL = 5.0  # seconds — keep generous vs is_healthy() threshold
    85	
    86	    ctx = zmq.Context()
    87	
    88	    dropped_counter = {"n": 0}
    89	
    90	    def sub_drain_loop() -> None:
    91	        """Own SUB socket; drain readings and emit periodic heartbeats.
    92	
    93	        Heartbeat comes from this thread (not the command thread) so
    94	        the GUI's heartbeat freshness check proves the *data* path is
    95	        alive, not just that the subprocess exists.
    96	        """
    97	        # Order matters: connect() BEFORE subscribe(). The inverse pattern
    98	        # (subscribe-before-connect with setsockopt_string(SUBSCRIBE, "")) produced
    99	        # zero received messages on macOS Python 3.14 pyzmq 25+.
   100	        sub = ctx.socket(zmq.SUB)
   101	        sub.setsockopt(zmq.LINGER, 0)
   102	        sub.setsockopt(zmq.RCVTIMEO, 100)
   103	        # 2026-04-20 idle-death fix: same keepalive as REQ side to
   104	        # survive macOS kernel idle reaping. SUB normally gets a
   105	        # stream of readings so idle is rare, but between-experiment
   106	        # quiet periods exist (scheduler paused, no active polls).
   107	        sub.setsockopt(zmq.TCP_KEEPALIVE, 1)
   108	        sub.setsockopt(zmq.TCP_KEEPALIVE_IDLE, 10)
   109	        sub.setsockopt(zmq.TCP_KEEPALIVE_INTVL, 5)
   110	        sub.setsockopt(zmq.TCP_KEEPALIVE_CNT, 3)
   111	        sub.connect(pub_addr)
   112	        sub.subscribe(DEFAULT_TOPIC)
   113	        last_heartbeat = time.monotonic()
   114	        try:
   115	            while not shutdown_event.is_set():
   116	                # SUB: blocking receive with 100ms RCVTIMEO. Keeps the loop
   117	                # responsive for shutdown and heartbeat emission.
   118	                try:
   119	                    parts = sub.recv_multipart()
   120	                    if len(parts) == 2:
   121	                        try:
   122	                            reading_dict = _unpack_reading_dict(parts[1])
   123	                        except Exception:
   124	                            reading_dict = None  # skip malformed
   125	                        if reading_dict is not None:
   126	                            try:
   127	                                data_queue.put_nowait(reading_dict)
   128	                            except queue.Full:
   129	                                dropped_counter["n"] += 1
   130	                                if dropped_counter["n"] % 100 == 1:
   131	                                    with contextlib.suppress(queue.Full):
   132	                                        data_queue.put_nowait(
   133	                                            {
   134	                                                "__type": "warning",
   135	                                                "message": (
   136	                                                    f"Queue overflow: "
   137	                                                    f"{dropped_counter['n']} readings dropped"
   138	                                                ),
   139	                                            }
   140	                                        )
   141	                except zmq.Again:
   142	                    pass
   143	                except zmq.ZMQError:
   144	                    if shutdown_event.is_set():
   145	                        break
   146	                    # Unexpected socket error — swallow and continue.
   147	                    time.sleep(0.01)
   148	
   149	                now = time.monotonic()
   150	                if now - last_heartbeat >= HEARTBEAT_INTERVAL:
   151	                    with contextlib.suppress(queue.Full):
   152	                        data_queue.put_nowait({"__type": "heartbeat", "ts": now})
   153	                    last_heartbeat = now
   154	        finally:
   155	            sub.close(linger=0)
   156	
   157	    def cmd_forward_loop() -> None:
   158	        """Forward GUI commands via a fresh REQ socket per command.
   159	
   160	        IV.6 B1 fix: each command creates, uses, and closes its own REQ
   161	        socket. Shared long-lived REQ accumulated state across commands
   162	        and became permanently unrecoverable after a platform-specific
   163	        trigger (macOS sparse cadence within ~minutes, Ubuntu 120 s
   164	        deterministic). Ephemeral REQ per command matches ZeroMQ Guide
   165	        ch.4 canonical "poll / timeout / close / reopen" reliable
   166	        request-reply pattern.
   167	
   168	        May block up to 35 s per timed-out REQ. That does not starve
   169	        the data path because SUB drain runs on a separate thread.
   170	        A timed-out REQ emits a structured ``cmd_timeout`` control
   171	        message via data_queue so the launcher watchdog can detect
   172	        command-channel-only failures and restart the bridge.
   173	        """
   174	
   175	        def _new_req_socket():
   176	            """Build a fresh per-command REQ socket.
   177	
   178	            IV.6: REQ_RELAXED / REQ_CORRELATE dropped — they were only
   179	            useful for stateful recovery on a shared socket, which the
   180	            ephemeral model has eliminated. TCP_KEEPALIVE dropped from
   181	            the command path (reverting the f5f9039 partial fix) —
   182	            Codex revised analysis confirmed idle-reap was not the
   183	            actual cause; keepalive is a no-op here and clutters
   184	            debugging of the real socket state.
   185	            """
   186	            req = ctx.socket(zmq.REQ)
   187	            req.setsockopt(zmq.LINGER, 0)
   188	            # IV.3 Finding 7: REQ timeout stays at 35 s so a slow
   189	            # server-side handler (experiment_finalize / report
   190	            # generation, tiered at 30 s) has room to reply before
   191	            # the REQ side gives up. Server's 30 s ceiling + 5 s slack
   192	            # stays inside the client's 35 s future wait
   193	            # (_CMD_REPLY_TIMEOUT_S), so timeouts at each layer fire
   194	            # in predictable order: server → subprocess → GUI future.
   195	            req.setsockopt(zmq.RCVTIMEO, 35000)
   196	            req.setsockopt(zmq.SNDTIMEO, 35000)
   197	            req.connect(cmd_addr)
   198	            return req
   199	
   200	        while not shutdown_event.is_set():
   201	            try:
   202	                cmd = cmd_queue.get(timeout=0.5)
   203	            except queue.Empty:
   204	                continue
   205	            rid = cmd.pop("_rid", None) if isinstance(cmd, dict) else None
   206	            cmd_type = cmd.get("cmd", "?") if isinstance(cmd, dict) else "?"
   207	
   208	            # Fresh socket per command — no shared state across commands.
   209	            req = _new_req_socket()
   210	            try:
   211	                try:
   212	                    req.send_string(json.dumps(cmd))
   213	                    reply_raw = req.recv_string()
   214	                    reply = json.loads(reply_raw)
   215	                except zmq.ZMQError as exc:
   216	                    reply = {"ok": False, "error": f"Engine не отвечает ({exc})"}
   217	                    with contextlib.suppress(queue.Full):
   218	                        data_queue.put_nowait(
   219	                            {
   220	                                "__type": "cmd_timeout",
   221	                                "cmd": cmd_type,
   222	                                "ts": time.monotonic(),
   223	                                "message": f"REP timeout on {cmd_type} ({exc})",
   224	                            }
   225	                        )
   226	                except Exception as exc:  # noqa: BLE001
   227	                    reply = {"ok": False, "error": str(exc)}
   228	            finally:
   229	                req.close(linger=0)
   230	
   231	            if rid is not None:
   232	                reply["_rid"] = rid
   233	            try:
   234	                reply_queue.put(reply, timeout=2.0)
   235	            except queue.Full:
   236	                with contextlib.suppress(queue.Full):
   237	                    data_queue.put_nowait(
   238	                        {"__type": "warning", "message": "Reply queue overflow"}
   239	                    )
   240	
   241	    sub_thread = threading.Thread(target=sub_drain_loop, name="zmq-sub-drain", daemon=True)
   242	    cmd_thread = threading.Thread(target=cmd_forward_loop, name="zmq-cmd-forward", daemon=True)
   243	
   244	    try:
   245	        sub_thread.start()
   246	        cmd_thread.start()
   247	        while not shutdown_event.is_set():
   248	            shutdown_event.wait(timeout=0.5)
   249	    except KeyboardInterrupt:
   250	        pass
   251	    finally:
   252	        shutdown_event.set()
   253	        sub_thread.join(timeout=2.0)
   254	        cmd_thread.join(timeout=4.0)
   255	        if sub_thread.is_alive() or cmd_thread.is_alive():
   256	            logger.warning("ZMQ bridge threads did not exit cleanly before context term")
   257	        ctx.term()

 succeeded in 0ms:
     1	"""ZMQ bridge client for GUI — all ZMQ lives in a subprocess.
     2	
     3	The GUI process never imports zmq. Communication with the subprocess
     4	is via multiprocessing.Queue. If libzmq crashes (signaler.cpp assertion
     5	on Windows), only the subprocess dies — GUI detects and restarts it.
     6	"""
     7	
     8	from __future__ import annotations
     9	
    10	import logging
    11	import multiprocessing as mp
    12	import queue
    13	import threading
    14	import time
    15	import uuid
    16	from concurrent.futures import Future
    17	from datetime import UTC, datetime
    18	from typing import Any
    19	
    20	from PySide6.QtCore import QThread, Signal
    21	
    22	from cryodaq.core.zmq_subprocess import (
    23	    DEFAULT_CMD_ADDR,
    24	    DEFAULT_PUB_ADDR,
    25	    zmq_bridge_main,
    26	)
    27	from cryodaq.drivers.base import ChannelStatus, Reading
    28	
    29	logger = logging.getLogger(__name__)
    30	
    31	_CMD_REPLY_TIMEOUT_S = 35.0  # IV.3 Finding 7: exceeds server 30 s ceiling
    32	
    33	
    34	def _reading_from_dict(d: dict[str, Any]) -> Reading:
    35	    """Reconstruct a Reading from a plain dict (received via mp.Queue)."""
    36	    return Reading(
    37	        timestamp=datetime.fromtimestamp(d["timestamp"], tz=UTC),
    38	        instrument_id=d.get("instrument_id", ""),
    39	        channel=d["channel"],
    40	        value=d["value"],
    41	        unit=d["unit"],
    42	        status=ChannelStatus(d["status"]),
    43	        raw=d.get("raw"),
    44	        metadata=d.get("metadata", {}),
    45	    )
    46	
    47	
    48	class ZmqBridge:
    49	    """GUI-side ZMQ bridge. No zmq import — all ZMQ lives in subprocess.
    50	
    51	    Usage::
    52	
    53	        bridge = ZmqBridge()
    54	        bridge.start()
    55	        # In QTimer tick:
    56	        for reading in bridge.poll_readings():
    57	            handle(reading)
    58	        # Commands:
    59	        reply = bridge.send_command({"cmd": "safety_status"})
    60	        # Shutdown:
    61	        bridge.shutdown()
    62	    """
    63	
    64	    def __init__(
    65	        self,
    66	        pub_addr: str = DEFAULT_PUB_ADDR,
    67	        cmd_addr: str = DEFAULT_CMD_ADDR,
    68	    ) -> None:
    69	        self._pub_addr = pub_addr
    70	        self._cmd_addr = cmd_addr
    71	        self._data_queue: mp.Queue = mp.Queue(maxsize=10_000)
    72	        self._cmd_queue: mp.Queue = mp.Queue(maxsize=1_000)
    73	        self._reply_queue: mp.Queue = mp.Queue(maxsize=1_000)
    74	        self._shutdown_event: mp.Event = mp.Event()
    75	        self._process: mp.Process | None = None
    76	        self._last_heartbeat: float = 0.0
    77	        # Data-flow watchdog: timestamp of the most recently drained
    78	        # actual reading (not heartbeat, not warning). Stays 0.0 until
    79	        # the first reading arrives so startup and between-experiment
    80	        # pauses don't trigger false-positive restarts.
    81	        self._last_reading_time: float = 0.0
    82	        # IV.6 B1 fix: timestamp of the most recent cmd_timeout control
    83	        # message emitted by the subprocess. Launcher watchdog uses
    84	        # ``command_channel_stalled()`` to detect command-channel-only
    85	        # failures where the data plane is still healthy but REQ/REP
    86	        # has entered a bad state.
    87	        self._last_cmd_timeout: float = 0.0
    88	        # Future-per-request command routing
    89	        self._pending: dict[str, Future] = {}
    90	        self._pending_lock = threading.Lock()
    91	        self._reply_stop = threading.Event()
    92	        self._reply_consumer: threading.Thread | None = None
    93	        # Hardening 2026-04-21: restart counter for B1 diagnostic correlation
    94	        self._restart_count: int = 0
    95	
    96	    def start(self) -> None:
    97	        """Start the ZMQ bridge subprocess."""
    98	        if self._process is not None and self._process.is_alive():
    99	            return
   100	        if self._reply_consumer is not None and self._reply_consumer.is_alive():
   101	            self._reply_stop.set()
   102	            self._reply_consumer.join(timeout=1.0)
   103	            self._reply_consumer = None
   104	        self._shutdown_event.clear()
   105	        # Drain stale queues
   106	        _drain(self._data_queue)
   107	        _drain(self._cmd_queue)
   108	        _drain(self._reply_queue)
   109	        self._process = mp.Process(
   110	            target=zmq_bridge_main,
   111	            args=(
   112	                self._pub_addr,
   113	                self._cmd_addr,
   114	                self._data_queue,
   115	                self._cmd_queue,
   116	                self._reply_queue,
   117	                self._shutdown_event,
   118	            ),
   119	            daemon=True,
   120	            name="zmq_bridge",
   121	        )
   122	        self._process.start()
   123	        self._last_heartbeat = time.monotonic()
   124	        self._last_reading_time = 0.0
   125	        # Start dedicated reply consumer thread
   126	        self._reply_stop.clear()
   127	        self._reply_consumer = threading.Thread(
   128	            target=self._consume_replies,
   129	            daemon=True,
   130	            name="zmq-reply-consumer",
   131	        )
   132	        self._reply_consumer.start()
   133	        self._restart_count += 1
   134	        logger.info(
   135	            "ZMQ bridge subprocess started (PID=%d, restart_count=%d)",
   136	            self._process.pid,
   137	            self._restart_count,
   138	        )
   139	
   140	    def is_alive(self) -> bool:
   141	        """Check if the subprocess is still running."""
   142	        return self._process is not None and self._process.is_alive()
   143	
   144	    def poll_readings(self) -> list[Reading]:
   145	        """Drain all available readings from the data queue. Non-blocking."""
   146	        readings: list[Reading] = []
   147	        while True:
   148	            try:
   149	                d = self._data_queue.get_nowait()
   150	                # Handle internal control messages from subprocess
   151	                msg_type = d.get("__type")
   152	                if msg_type == "heartbeat":
   153	                    self._last_heartbeat = time.monotonic()
   154	                    continue
   155	                if msg_type == "cmd_timeout":
   156	                    # IV.6 B1 fix: structured timeout marker used by the
   157	                    # launcher's command-channel watchdog. Separate from
   158	                    # "warning" because the launcher must restart the
   159	                    # bridge on this specific failure shape, not on
   160	                    # generic queue-overflow warnings.
   161	                    self._last_cmd_timeout = time.monotonic()
   162	                    logger.warning(
   163	                        "ZMQ bridge: %s",
   164	                        d.get("message", "command timeout"),
   165	                    )
   166	                    continue
   167	                if msg_type == "warning":
   168	                    logger.warning("ZMQ bridge: %s", d.get("message", ""))
   169	                    continue
   170	                self._last_reading_time = time.monotonic()
   171	                readings.append(_reading_from_dict(d))
   172	            except (queue.Empty, EOFError):
   173	                break
   174	            except Exception as exc:
   175	                logger.warning("poll_readings: error processing item: %s", exc)
   176	                continue
   177	        return readings
   178	
   179	    def heartbeat_stale(self, *, timeout_s: float = 30.0) -> bool:
   180	        """Return True if the bridge heartbeat is older than ``timeout_s``."""
   181	        return (
   182	            self._last_heartbeat != 0.0 and (time.monotonic() - self._last_heartbeat) >= timeout_s
   183	        )
   184	
   185	    def data_flow_stalled(self, *, timeout_s: float = 30.0) -> bool:
   186	        """Return True if readings previously flowed but are now stale."""
   187	        return (
   188	            self._last_reading_time != 0.0
   189	            and (time.monotonic() - self._last_reading_time) >= timeout_s
   190	        )
   191	
   192	    def command_channel_stalled(self, *, timeout_s: float = 10.0) -> bool:
   193	        """Return True if a command timeout occurred within the last
   194	        ``timeout_s`` seconds.
   195	
   196	        IV.6 B1 fix: used by launcher watchdog to detect command-channel-
   197	        only failures (data plane still healthy but commands fail). Single
   198	        recent timeout is enough to trigger — streak-count threshold may
   199	        be introduced later if field testing shows false positives.
   200	        """
   201	        if self._last_cmd_timeout == 0.0:
   202	            return False
   203	        return (time.monotonic() - self._last_cmd_timeout) < timeout_s
   204	
   205	    def is_healthy(self) -> bool:
   206	        """True if subprocess is alive and bridge heartbeats are fresh."""
   207	        return self.is_alive() and not self.heartbeat_stale()
   208	
   209	    def restart_count(self) -> int:
   210	        """Return the number of bridge restarts since launcher start."""
   211	        return self._restart_count
   212	
   213	    def send_command(self, cmd: dict) -> dict:
   214	        """Thread-safe command dispatch with Future-per-request correlation."""
   215	        if not self.is_alive():
   216	            return {"ok": False, "error": "ZMQ bridge subprocess not running"}
   217	
   218	        rid = uuid.uuid4().hex[:8]
   219	        cmd = {**cmd, "_rid": rid}
   220	        future: Future = Future()
   221	
   222	        with self._pending_lock:
   223	            self._pending[rid] = future
   224	
   225	        try:
   226	            self._cmd_queue.put(cmd, timeout=2.0)
   227	            return future.result(timeout=_CMD_REPLY_TIMEOUT_S)
   228	        except Exception as exc:
   229	            return {"ok": False, "error": f"Engine не отвечает ({type(exc).__name__}: {exc})"}
   230	        finally:
   231	            with self._pending_lock:
   232	                self._pending.pop(rid, None)
   233	
   234	    def _consume_replies(self) -> None:
   235	        """Dedicated thread: reads replies from subprocess, routes to correct Future."""
   236	        while not self._reply_stop.is_set():
   237	            try:
   238	                reply = self._reply_queue.get(timeout=0.5)
   239	            except queue.Empty:
   240	                continue
   241	            except (EOFError, OSError):
   242	                break
   243	
   244	            try:
   245	                if not isinstance(reply, dict):
   246	                    logger.warning("ZMQ reply consumer: non-dict reply: %r", type(reply))
   247	                    continue
   248	                rid = reply.pop("_rid", None)
   249	                if rid:
   250	                    with self._pending_lock:
   251	                        future = self._pending.get(rid)
   252	                    if future and not future.done():
   253	                        future.set_result(reply)
   254	                        continue
   255	                logger.debug("Unmatched ZMQ reply (rid=%s)", rid)
   256	            except Exception:
   257	                logger.exception("ZMQ reply consumer: error processing reply")
   258	
   259	    def shutdown(self) -> None:
   260	        """Signal subprocess to stop, cancel pending futures, wait for exit."""

exec
/opt/homebrew/bin/bash -lc "git show 157c4bc:src/cryodaq/core/zmq_bridge.py | nl -ba | sed -n '1,220p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	"""ZMQ-мост между engine и GUI.
     2	
     3	ZMQPublisher — PUB-сокет в engine, сериализует Reading через msgpack.
     4	ZMQSubscriber — SUB-сокет в GUI-процессе, десериализует и вызывает callback.
     5	ZMQCommandServer — REP-сокет в engine, принимает JSON-команды от GUI.
     6	"""
     7	
     8	from __future__ import annotations
     9	
    10	import asyncio
    11	import errno
    12	import json
    13	import logging
    14	import time
    15	from collections.abc import Callable
    16	from datetime import UTC, datetime
    17	from typing import Any
    18	
    19	import msgpack
    20	import zmq
    21	import zmq.asyncio
    22	
    23	from cryodaq.core.zmq_transport import (
    24	    DEFAULT_CMD_ADDR,
    25	    DEFAULT_PUB_ADDR,
    26	    cleanup_ipc_path,
    27	    prepare_ipc_path,
    28	)
    29	from cryodaq.drivers.base import ChannelStatus, Reading
    30	
    31	logger = logging.getLogger(__name__)
    32	
    33	DEFAULT_TOPIC = b"readings"
    34	
    35	# IV.3 Finding 7: per-command tiered handler timeout.
    36	# A flat 2 s envelope was wrong for stateful transitions —
    37	# experiment_finalize / abort / create and calibration curve
    38	# import/export/fit routinely exceed 2 s (SQLite writes + DOCX/PDF
    39	# report generation). When they timed out the outer REP reply path
    40	# still fired (the original code already returned {ok: False}), but
    41	# the operator saw a "handler timeout (2s)" error that was a lie:
    42	# the operation usually completed a few seconds later. Fast status
    43	# polls stay on the 2 s envelope; known-slow commands get 30 s.
    44	HANDLER_TIMEOUT_FAST_S = 2.0
    45	HANDLER_TIMEOUT_SLOW_S = 30.0
    46	
    47	_SLOW_COMMANDS: frozenset[str] = frozenset(
    48	    {
    49	        "experiment_finalize",
    50	        "experiment_stop",
    51	        "experiment_abort",
    52	        "experiment_create",
    53	        "experiment_create_retroactive",
    54	        "experiment_start",
    55	        "experiment_generate_report",
    56	        "calibration_curve_import",
    57	        "calibration_curve_export",
    58	        "calibration_v2_fit",
    59	        "calibration_v2_extract",
    60	    }
    61	)
    62	
    63	
    64	def _timeout_for(cmd: Any) -> float:
    65	    """Return the handler timeout envelope for ``cmd``.
    66	
    67	    Slow commands get ``HANDLER_TIMEOUT_SLOW_S``; everything else
    68	    gets ``HANDLER_TIMEOUT_FAST_S``. Unknown / malformed payloads
    69	    fall back to fast — a cmd that isn't in the slow set must not
    70	    trigger the longer wait by accident.
    71	    """
    72	    if not isinstance(cmd, dict):
    73	        return HANDLER_TIMEOUT_FAST_S
    74	    action = cmd.get("cmd")
    75	    if isinstance(action, str) and action in _SLOW_COMMANDS:
    76	        return HANDLER_TIMEOUT_SLOW_S
    77	    return HANDLER_TIMEOUT_FAST_S
    78	
    79	
    80	# Phase 2b H.4: bind with EADDRINUSE retry. On Windows the socket from a
    81	# SIGKILL'd engine can hold the port for up to 240s (TIME_WAIT). Linux is
    82	# usually fine due to SO_REUSEADDR but the same logic protects both.
    83	_BIND_MAX_ATTEMPTS = 10
    84	_BIND_INITIAL_DELAY_S = 0.5
    85	_BIND_MAX_DELAY_S = 10.0
    86	
    87	
    88	def _bind_with_retry(socket: Any, address: str) -> None:
    89	    """Bind a ZMQ socket, retrying on EADDRINUSE with exponential backoff.
    90	
    91	    Caller MUST set ``zmq.LINGER = 0`` on the socket BEFORE calling this
    92	    helper, otherwise close() will hold the address even after retry succeeds.
    93	    """
    94	    delay = _BIND_INITIAL_DELAY_S
    95	    for attempt in range(_BIND_MAX_ATTEMPTS):
    96	        try:
    97	            socket.bind(address)
    98	            if attempt > 0:
    99	                logger.info(
   100	                    "ZMQ bound to %s after %d retries",
   101	                    address,
   102	                    attempt,
   103	                )
   104	            return
   105	        except zmq.ZMQError as exc:
   106	            # libzmq maps EADDRINUSE to its own errno value.
   107	            is_addr_in_use = exc.errno == zmq.EADDRINUSE or exc.errno == errno.EADDRINUSE
   108	            if not is_addr_in_use:
   109	                raise
   110	            if attempt == _BIND_MAX_ATTEMPTS - 1:
   111	                logger.critical(
   112	                    "ZMQ bind FAILED after %d attempts: %s still in use. "
   113	                    "Check for stale sockets via lsof/netstat.",
   114	                    _BIND_MAX_ATTEMPTS,
   115	                    address,
   116	                )
   117	                raise
   118	            logger.warning(
   119	                "ZMQ bind EADDRINUSE on %s, retry in %.1fs (attempt %d/%d)",
   120	                address,
   121	                delay,
   122	                attempt + 1,
   123	                _BIND_MAX_ATTEMPTS,
   124	            )
   125	            time.sleep(delay)
   126	            delay = min(delay * 2, _BIND_MAX_DELAY_S)
   127	
   128	
   129	def _pack_reading(reading: Reading) -> bytes:
   130	    """Сериализовать Reading в msgpack."""
   131	    data = {
   132	        "ts": reading.timestamp.timestamp(),
   133	        "iid": reading.instrument_id,
   134	        "ch": reading.channel,
   135	        "v": reading.value,
   136	        "u": reading.unit,
   137	        "st": reading.status.value,
   138	        "raw": reading.raw,
   139	        "meta": reading.metadata,
   140	    }
   141	    return msgpack.packb(data, use_bin_type=True)
   142	
   143	
   144	def _unpack_reading(payload: bytes) -> Reading:
   145	    """Десериализовать Reading из msgpack."""
   146	    data = msgpack.unpackb(payload, raw=False)
   147	    return Reading(
   148	        timestamp=datetime.fromtimestamp(data["ts"], tz=UTC),
   149	        instrument_id=data.get("iid", ""),
   150	        channel=data["ch"],
   151	        value=data["v"],
   152	        unit=data["u"],
   153	        status=ChannelStatus(data["st"]),
   154	        raw=data.get("raw"),
   155	        metadata=data.get("meta", {}),
   156	    )
   157	
   158	
   159	class ZMQPublisher:
   160	    """PUB-сокет: engine публикует Reading для GUI и внешних подписчиков.
   161	
   162	    Использование::
   163	
   164	        pub = ZMQPublisher("tcp://127.0.0.1:5555")
   165	        await pub.start(queue)   # asyncio.Queue[Reading] от DataBroker
   166	        ...
   167	        await pub.stop()
   168	    """
   169	
   170	    def __init__(self, address: str = DEFAULT_PUB_ADDR, *, topic: bytes = DEFAULT_TOPIC) -> None:
   171	        self._address = address
   172	        self._topic = topic
   173	        self._ctx: zmq.asyncio.Context | None = None
   174	        self._socket: zmq.asyncio.Socket | None = None
   175	        self._task: asyncio.Task[None] | None = None
   176	        self._running = False
   177	        self._total_sent: int = 0
   178	
   179	    async def _publish_loop(self, queue: asyncio.Queue[Reading]) -> None:
   180	        while self._running:
   181	            try:
   182	                reading = await asyncio.wait_for(queue.get(), timeout=1.0)
   183	            except TimeoutError:
   184	                continue
   185	            try:
   186	                payload = _pack_reading(reading)
   187	                await self._socket.send_multipart([self._topic, payload])
   188	                self._total_sent += 1
   189	            except Exception:
   190	                logger.exception("Ошибка отправки ZMQ")
   191	
   192	    async def start(self, queue: asyncio.Queue[Reading]) -> None:
   193	        self._ctx = zmq.asyncio.Context()
   194	        self._socket = self._ctx.socket(zmq.PUB)
   195	        # Phase 2b H.4: LINGER=0 so the socket doesn't hold the port open
   196	        # after close — relevant on Windows where TIME_WAIT can keep
   197	        # 5555 occupied for 240s after a SIGKILL'd engine.
   198	        self._socket.setsockopt(zmq.LINGER, 0)
   199	        # IV.6: TCP_KEEPALIVE previously added here on the idle-reap
   200	        # hypothesis (commit f5f9039). Codex revised analysis disproved
   201	        # that — Ubuntu 120 s deterministic failure with default
   202	        # tcp_keepalive_time=7200 s rules out kernel reaping. Keepalive
   203	        # reverted on the command path (REQ + REP); retained on the
   204	        # SUB drain path in zmq_subprocess.sub_drain_loop as an
   205	        # orthogonal safeguard for long between-experiment pauses.
   206	        prepare_ipc_path(self._address)
   207	        _bind_with_retry(self._socket, self._address)
   208	        self._running = True
   209	        self._task = asyncio.create_task(self._publish_loop(queue), name="zmq_publisher")
   210	        logger.info("ZMQPublisher запущен: %s", self._address)
   211	
   212	    async def stop(self) -> None:
   213	        self._running = False
   214	        if self._task:
   215	            self._task.cancel()
   216	            try:
   217	                await self._task
   218	            except asyncio.CancelledError:
   219	                pass
   220	            self._task = None

exec
/opt/homebrew/bin/bash -lc "git show 157c4bc:src/cryodaq/core/zmq_bridge.py | nl -ba | sed -n '220,420p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   220	            self._task = None
   221	        if self._socket:
   222	            self._socket.close(linger=0)
   223	            self._socket = None
   224	        if self._ctx:
   225	            self._ctx.term()
   226	            self._ctx = None
   227	        cleanup_ipc_path(self._address)
   228	        logger.info("ZMQPublisher остановлен (отправлено: %d)", self._total_sent)
   229	
   230	
   231	class ZMQSubscriber:
   232	    """SUB-сокет: GUI-процесс подписывается на поток данных от engine.
   233	
   234	    Использование::
   235	
   236	        async def on_reading(r: Reading):
   237	            print(r.channel, r.value)
   238	
   239	        sub = ZMQSubscriber("tcp://127.0.0.1:5555", callback=on_reading)
   240	        await sub.start()
   241	        ...
   242	        await sub.stop()
   243	    """
   244	
   245	    def __init__(
   246	        self,
   247	        address: str = DEFAULT_PUB_ADDR,
   248	        *,
   249	        topic: bytes = DEFAULT_TOPIC,
   250	        callback: Callable[[Reading], object] | None = None,
   251	    ) -> None:
   252	        self._address = address
   253	        self._topic = topic
   254	        self._callback = callback
   255	        self._ctx: zmq.asyncio.Context | None = None
   256	        self._socket: zmq.asyncio.Socket | None = None
   257	        self._task: asyncio.Task[None] | None = None
   258	        self._running = False
   259	        self._total_received: int = 0
   260	
   261	    async def _receive_loop(self) -> None:
   262	        while self._running:
   263	            try:
   264	                parts = await asyncio.wait_for(self._socket.recv_multipart(), timeout=1.0)
   265	            except TimeoutError:
   266	                continue
   267	            except Exception:
   268	                logger.exception("Ошибка приёма ZMQ")
   269	                continue
   270	            if len(parts) != 2:
   271	                continue
   272	            try:
   273	                reading = _unpack_reading(parts[1])
   274	                self._total_received += 1
   275	            except Exception:
   276	                logger.exception("Ошибка десериализации Reading")
   277	                continue
   278	            if self._callback:
   279	                try:
   280	                    result = self._callback(reading)
   281	                    if asyncio.iscoroutine(result):
   282	                        await result
   283	                except Exception:
   284	                    logger.exception("Ошибка в callback подписчика")
   285	
   286	    async def start(self) -> None:
   287	        self._ctx = zmq.asyncio.Context()
   288	        self._socket = self._ctx.socket(zmq.SUB)
   289	        self._socket.setsockopt(zmq.LINGER, 0)
   290	        self._socket.setsockopt(zmq.RECONNECT_IVL, 500)
   291	        self._socket.setsockopt(zmq.RECONNECT_IVL_MAX, 5000)
   292	        self._socket.setsockopt(zmq.RCVTIMEO, 3000)
   293	        self._socket.connect(self._address)
   294	        self._socket.subscribe(self._topic)
   295	        self._running = True
   296	        self._task = asyncio.create_task(self._receive_loop(), name="zmq_subscriber")
   297	        logger.info("ZMQSubscriber подключён: %s", self._address)
   298	
   299	    async def stop(self) -> None:
   300	        self._running = False
   301	        if self._task:
   302	            self._task.cancel()
   303	            try:
   304	                await self._task
   305	            except asyncio.CancelledError:
   306	                pass
   307	            self._task = None
   308	        if self._socket:
   309	            self._socket.close(linger=0)
   310	            self._socket = None
   311	        if self._ctx:
   312	            self._ctx.term()
   313	            self._ctx = None
   314	        logger.info("ZMQSubscriber остановлен (получено: %d)", self._total_received)
   315	
   316	
   317	class ZMQCommandServer:
   318	    """REP-сокет: engine принимает JSON-команды от GUI.
   319	
   320	    Использование::
   321	
   322	        async def handler(cmd: dict) -> dict:
   323	            return {"ok": True}
   324	
   325	        srv = ZMQCommandServer(handler=handler)
   326	        await srv.start()
   327	        ...
   328	        await srv.stop()
   329	    """
   330	
   331	    def __init__(
   332	        self,
   333	        address: str = DEFAULT_CMD_ADDR,
   334	        *,
   335	        handler: Callable[[dict[str, Any]], Any] | None = None,
   336	        handler_timeout_s: float | None = None,
   337	    ) -> None:
   338	        self._address = address
   339	        self._handler = handler
   340	        # IV.3 Finding 7: honour an explicit override (tests supply one
   341	        # to exercise the timeout path without sleeping for 2 s), but
   342	        # the production path uses the tiered ``_timeout_for(cmd)``
   343	        # helper so slow commands get 30 s and fast commands 2 s.
   344	        self._handler_timeout_override_s = handler_timeout_s
   345	        self._ctx: zmq.asyncio.Context | None = None
   346	        self._socket: zmq.asyncio.Socket | None = None
   347	        self._task: asyncio.Task[None] | None = None
   348	        self._running = False
   349	        self._shutdown_requested = False
   350	
   351	    def _start_serve_task(self) -> None:
   352	        """Spawn the command loop exactly once while the server is running."""
   353	        if not self._running or self._shutdown_requested:
   354	            return
   355	        if self._task is not None and not self._task.done():
   356	            return
   357	        loop = asyncio.get_running_loop()
   358	        self._task = loop.create_task(self._serve_loop(), name="zmq_cmd_server")
   359	        self._task.add_done_callback(self._on_serve_task_done)
   360	
   361	    def _on_serve_task_done(self, task: asyncio.Task[None]) -> None:
   362	        """Restart the REP loop after unexpected task exit."""
   363	        if task is not self._task:
   364	            return
   365	
   366	        try:
   367	            exc = task.exception()
   368	        except asyncio.CancelledError:
   369	            exc = None
   370	
   371	        self._task = None
   372	        if self._shutdown_requested or not self._running:
   373	            return
   374	
   375	        if exc is not None:
   376	            logger.error(
   377	                "ZMQCommandServer serve loop crashed; restarting",
   378	                exc_info=(type(exc), exc, exc.__traceback__),
   379	            )
   380	        else:
   381	            logger.error("ZMQCommandServer serve loop exited unexpectedly; restarting")
   382	
   383	        loop = task.get_loop()
   384	        if loop.is_closed():
   385	            logger.error("ZMQCommandServer loop is closed; cannot restart serve loop")
   386	            return
   387	        loop.call_soon(self._start_serve_task)
   388	
   389	    async def _run_handler(self, cmd: dict[str, Any]) -> dict[str, Any]:
   390	        """Execute the command handler with a bounded wall-clock timeout.
   391	
   392	        IV.3 Finding 7: always returns a dict. REP sockets require exactly
   393	        one send() per recv(); any path that silently raises here would
   394	        leave REP wedged and cascade every subsequent command into
   395	        timeouts. Timeout fired or unexpected handler exception both
   396	        yield an ``ok=False`` reply with the failure reason and — on
   397	        timeout — the ``_handler_timeout`` marker so callers can tell
   398	        the difference from a normal handler-reported error.
   399	        """
   400	        if self._handler is None:
   401	            return {"ok": False, "error": "no handler"}
   402	
   403	        # IV.3 Finding 7 amend: _serve_loop forwards any valid JSON,
   404	        # not only objects. A scalar or list payload (valid JSON, wrong
   405	        # shape) previously raised AttributeError on cmd.get(...) and
   406	        # fell out to the outer serve-loop catch — still sent a reply
   407	        # so REP was not wedged, but the failure path was accidental.
   408	        # Validate the shape here so _run_handler's "always returns a
   409	        # dict" contract is explicit rather than luck-dependent.
   410	        if not isinstance(cmd, dict):
   411	            logger.warning(
   412	                "ZMQ command payload is %s, not dict — rejecting.",
   413	                type(cmd).__name__,
   414	            )
   415	            return {
   416	                "ok": False,
   417	                "error": f"invalid payload: expected object, got {type(cmd).__name__}",
   418	            }
   419	
   420	        action = str(cmd.get("cmd", ""))

exec
/opt/homebrew/bin/bash -lc "git show experiment/iv7-ipc-transport:src/cryodaq/core/zmq_transport.py | nl -ba | sed -n '1,180p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	from __future__ import annotations
     2	
     3	import errno
     4	import os
     5	import socket
     6	import stat
     7	import sys
     8	from pathlib import Path
     9	
    10	
    11	def _default_transport_addrs() -> tuple[str, str]:
    12	    if sys.platform == "win32":
    13	        return ("tcp://127.0.0.1:5555", "tcp://127.0.0.1:5556")
    14	    return ("ipc:///tmp/cryodaq-pub.sock", "ipc:///tmp/cryodaq-cmd.sock")
    15	
    16	
    17	DEFAULT_PUB_ADDR, DEFAULT_CMD_ADDR = _default_transport_addrs()
    18	
    19	
    20	def ipc_path(addr: str) -> Path | None:
    21	    if not addr.startswith("ipc://"):
    22	        return None
    23	    return Path(addr[len("ipc://") :])
    24	
    25	
    26	def tcp_host_port(addr: str) -> tuple[str, int] | None:
    27	    if not addr.startswith("tcp://"):
    28	        return None
    29	    host_port = addr[len("tcp://") :]
    30	    host, port = host_port.rsplit(":", 1)
    31	    return host, int(port)
    32	
    33	
    34	def _ipc_path_is_live(path: Path) -> bool:
    35	    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    36	    try:
    37	        probe.settimeout(0.1)
    38	        probe.connect(os.fspath(path))
    39	    except OSError as exc:
    40	        if exc.errno in {errno.ECONNREFUSED, errno.ENOENT}:
    41	            return False
    42	        raise FileExistsError(f"Refusing to remove IPC path with unknown state: {path}") from exc
    43	    finally:
    44	        probe.close()
    45	    return True
    46	
    47	
    48	def _cleanup_ipc_path_if_safe(path: Path) -> None:
    49	    try:
    50	        path_stat = path.lstat()
    51	    except FileNotFoundError:
    52	        return
    53	    if not stat.S_ISSOCK(path_stat.st_mode):
    54	        raise FileExistsError(f"Refusing to remove non-socket IPC path: {path}")
    55	    if _ipc_path_is_live(path):
    56	        raise FileExistsError(f"Refusing to remove live IPC endpoint: {path}")
    57	    os.unlink(path)
    58	
    59	
    60	def prepare_ipc_path(addr: str) -> None:
    61	    path = ipc_path(addr)
    62	    if path is None:
    63	        return
    64	    path.parent.mkdir(parents=True, exist_ok=True)
    65	    _cleanup_ipc_path_if_safe(path)
    66	
    67	
    68	def cleanup_ipc_path(addr: str) -> None:
    69	    path = ipc_path(addr)
    70	    if path is None:
    71	        return
    72	    _cleanup_ipc_path_if_safe(path)

exec
/opt/homebrew/bin/bash -lc "git show experiment/iv7-ipc-transport:tools/diag_zmq_b1_capture.py | nl -ba | sed -n '1,180p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	from __future__ import annotations
     2	
     3	import argparse
     4	import json
     5	import sys
     6	import time
     7	from datetime import UTC, datetime
     8	from pathlib import Path
     9	
    10	if __package__ in {None, ""}:
    11	    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    12	
    13	from cryodaq.gui.zmq_client import ZmqBridge
    14	from tools._b1_diagnostics import bridge_snapshot, direct_engine_probe
    15	from tools._zmq_helpers import DEFAULT_CMD_ADDR
    16	
    17	
    18	def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    19	    parser = argparse.ArgumentParser(
    20	        description=(
    21	            "Canonical B1 capture against current master. Records bridge-side "
    22	            "and direct-engine command health into JSONL."
    23	        )
    24	    )
    25	    parser.add_argument("--output", type=Path, required=True, help="JSONL artifact path.")
    26	    parser.add_argument("--duration", type=float, default=180.0, help="Capture length in seconds.")
    27	    parser.add_argument("--interval", type=float, default=1.0, help="Sample interval in seconds.")
    28	    parser.add_argument("--address", default=DEFAULT_CMD_ADDR, help="Direct engine REQ address.")
    29	    parser.add_argument(
    30	        "--direct-timeout",
    31	        type=float,
    32	        default=5.0,
    33	        help="Seconds to wait for the direct engine probe.",
    34	    )
    35	    parser.add_argument(
    36	        "--skip-direct-probe",
    37	        action="store_true",
    38	        help="Only record bridge-side command health.",
    39	    )
    40	    return parser.parse_args(argv)
    41	
    42	
    43	def _sample_once(
    44	    bridge: ZmqBridge,
    45	    *,
    46	    address: str,
    47	    direct_timeout_s: float,
    48	    skip_direct_probe: bool,
    49	) -> dict:
    50	    bridge.poll_readings()
    51	    sample = bridge_snapshot(bridge)
    52	    sample["ts_utc"] = datetime.now(UTC).isoformat()
    53	    sample["bridge_reply"] = bridge.send_command({"cmd": "safety_status"})
    54	    if skip_direct_probe:
    55	        sample["direct_reply"] = None
    56	    else:
    57	        try:
    58	            sample["direct_reply"] = direct_engine_probe(
    59	                address=address,
    60	                timeout_s=direct_timeout_s,
    61	            )
    62	        except TimeoutError as exc:
    63	            sample["direct_reply"] = {
    64	                "ok": False,
    65	                "error": str(exc),
    66	                "exception_type": type(exc).__name__,
    67	            }
    68	    return sample
    69	
    70	
    71	def _validate_bridge_startup(bridge: ZmqBridge) -> None:
    72	    if not bridge.is_alive():
    73	        raise RuntimeError("ZMQ bridge subprocess failed to start")
    74	    reply = bridge.send_command({"cmd": "safety_status"})
    75	    if not reply or reply.get("ok") is not True:
    76	        raise RuntimeError(f"Bridge startup probe failed: {reply!r}")
    77	
    78	
    79	def run_capture(
    80	    bridge: ZmqBridge,
    81	    *,
    82	    duration_s: float,
    83	    interval_s: float,
    84	    output_path: Path,
    85	    address: str,
    86	    direct_timeout_s: float,
    87	    skip_direct_probe: bool,
    88	    now_fn=time.monotonic,
    89	    sleep_fn=time.sleep,
    90	) -> int:
    91	    output_path.parent.mkdir(parents=True, exist_ok=True)
    92	    deadline = now_fn() + duration_s
    93	    count = 0
    94	
    95	    with output_path.open("w", encoding="utf-8") as fh:
    96	        while True:
    97	            if now_fn() >= deadline:
    98	                break
    99	            sample = _sample_once(
   100	                bridge,
   101	                address=address,
   102	                direct_timeout_s=direct_timeout_s,
   103	                skip_direct_probe=skip_direct_probe,
   104	            )
   105	            count += 1
   106	            sample["seq"] = count
   107	            fh.write(json.dumps(sample, ensure_ascii=False) + "\n")
   108	            fh.flush()
   109	            if now_fn() >= deadline:
   110	                break
   111	            sleep_fn(interval_s)
   112	
   113	    return count
   114	
   115	
   116	def main(argv: list[str] | None = None) -> int:
   117	    args = _parse_args(argv)
   118	    bridge = ZmqBridge()
   119	    bridge.start()
   120	    time.sleep(1.0)
   121	    try:
   122	        try:
   123	            _validate_bridge_startup(bridge)
   124	        except RuntimeError as exc:
   125	            print(f"B1 capture aborted: {exc}", file=sys.stderr)
   126	            return 1
   127	        samples = run_capture(
   128	            bridge,
   129	            duration_s=args.duration,
   130	            interval_s=args.interval,
   131	            output_path=args.output,
   132	            address=args.address,
   133	            direct_timeout_s=args.direct_timeout,
   134	            skip_direct_probe=args.skip_direct_probe,
   135	        )
   136	    finally:
   137	        bridge.shutdown()
   138	    print(f"Wrote {samples} samples to {args.output}")
   139	    return 0
   140	
   141	
   142	if __name__ == "__main__":
   143	    sys.exit(main())

exec
/opt/homebrew/bin/bash -lc "git show experiment/iv7-ipc-transport:src/cryodaq/gui/zmq_client.py | nl -ba | sed -n '1,260p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	"""ZMQ bridge client for GUI — all ZMQ lives in a subprocess.
     2	
     3	The GUI process never imports zmq. Communication with the subprocess
     4	is via multiprocessing.Queue. If libzmq crashes (signaler.cpp assertion
     5	on Windows), only the subprocess dies — GUI detects and restarts it.
     6	"""
     7	
     8	from __future__ import annotations
     9	
    10	import logging
    11	import multiprocessing as mp
    12	import queue
    13	import threading
    14	import time
    15	import uuid
    16	from concurrent.futures import Future
    17	from datetime import UTC, datetime
    18	from typing import Any
    19	
    20	from PySide6.QtCore import QThread, Signal
    21	
    22	from cryodaq.core.zmq_subprocess import (
    23	    DEFAULT_CMD_ADDR,
    24	    DEFAULT_PUB_ADDR,
    25	    zmq_bridge_main,
    26	)
    27	from cryodaq.drivers.base import ChannelStatus, Reading
    28	
    29	logger = logging.getLogger(__name__)
    30	
    31	_CMD_REPLY_TIMEOUT_S = 35.0  # IV.3 Finding 7: exceeds server 30 s ceiling
    32	
    33	
    34	def _reading_from_dict(d: dict[str, Any]) -> Reading:
    35	    """Reconstruct a Reading from a plain dict (received via mp.Queue)."""
    36	    return Reading(
    37	        timestamp=datetime.fromtimestamp(d["timestamp"], tz=UTC),
    38	        instrument_id=d.get("instrument_id", ""),
    39	        channel=d["channel"],
    40	        value=d["value"],
    41	        unit=d["unit"],
    42	        status=ChannelStatus(d["status"]),
    43	        raw=d.get("raw"),
    44	        metadata=d.get("metadata", {}),
    45	    )
    46	
    47	
    48	class ZmqBridge:
    49	    """GUI-side ZMQ bridge. No zmq import — all ZMQ lives in subprocess.
    50	
    51	    Usage::
    52	
    53	        bridge = ZmqBridge()
    54	        bridge.start()
    55	        # In QTimer tick:
    56	        for reading in bridge.poll_readings():
    57	            handle(reading)
    58	        # Commands:
    59	        reply = bridge.send_command({"cmd": "safety_status"})
    60	        # Shutdown:
    61	        bridge.shutdown()
    62	    """
    63	
    64	    def __init__(
    65	        self,
    66	        pub_addr: str = DEFAULT_PUB_ADDR,
    67	        cmd_addr: str = DEFAULT_CMD_ADDR,
    68	    ) -> None:
    69	        self._pub_addr = pub_addr
    70	        self._cmd_addr = cmd_addr
    71	        self._data_queue: mp.Queue = mp.Queue(maxsize=10_000)
    72	        self._cmd_queue: mp.Queue = mp.Queue(maxsize=1_000)
    73	        self._reply_queue: mp.Queue = mp.Queue(maxsize=1_000)
    74	        self._shutdown_event: mp.Event = mp.Event()
    75	        self._process: mp.Process | None = None
    76	        self._last_heartbeat: float = 0.0
    77	        # Data-flow watchdog: timestamp of the most recently drained
    78	        # actual reading (not heartbeat, not warning). Stays 0.0 until
    79	        # the first reading arrives so startup and between-experiment
    80	        # pauses don't trigger false-positive restarts.
    81	        self._last_reading_time: float = 0.0
    82	        # IV.6 B1 fix: timestamp of the most recent cmd_timeout control
    83	        # message emitted by the subprocess. Launcher watchdog uses
    84	        # ``command_channel_stalled()`` to detect command-channel-only
    85	        # failures where the data plane is still healthy but REQ/REP
    86	        # has entered a bad state.
    87	        self._last_cmd_timeout: float = 0.0
    88	        # Future-per-request command routing
    89	        self._pending: dict[str, Future] = {}
    90	        self._pending_lock = threading.Lock()
    91	        self._reply_stop = threading.Event()
    92	        self._reply_consumer: threading.Thread | None = None
    93	        # Hardening 2026-04-21: restart counter for B1 diagnostic correlation
    94	        self._restart_count: int = 0
    95	
    96	    def start(self) -> None:
    97	        """Start the ZMQ bridge subprocess."""
    98	        if self._process is not None and self._process.is_alive():
    99	            return
   100	        if self._reply_consumer is not None and self._reply_consumer.is_alive():
   101	            self._reply_stop.set()
   102	            self._reply_consumer.join(timeout=1.0)
   103	            self._reply_consumer = None
   104	        self._shutdown_event.clear()
   105	        # Drain stale queues
   106	        _drain(self._data_queue)
   107	        _drain(self._cmd_queue)
   108	        _drain(self._reply_queue)
   109	        self._process = mp.Process(
   110	            target=zmq_bridge_main,
   111	            args=(
   112	                self._pub_addr,
   113	                self._cmd_addr,
   114	                self._data_queue,
   115	                self._cmd_queue,
   116	                self._reply_queue,
   117	                self._shutdown_event,
   118	            ),
   119	            daemon=True,
   120	            name="zmq_bridge",
   121	        )
   122	        self._process.start()
   123	        self._last_heartbeat = time.monotonic()
   124	        self._last_reading_time = 0.0
   125	        # Start dedicated reply consumer thread
   126	        self._reply_stop.clear()
   127	        self._reply_consumer = threading.Thread(
   128	            target=self._consume_replies,
   129	            daemon=True,
   130	            name="zmq-reply-consumer",
   131	        )
   132	        self._reply_consumer.start()
   133	        self._restart_count += 1
   134	        logger.info(
   135	            "ZMQ bridge subprocess started (PID=%d, restart_count=%d)",
   136	            self._process.pid,
   137	            self._restart_count,
   138	        )
   139	
   140	    def is_alive(self) -> bool:
   141	        """Check if the subprocess is still running."""
   142	        return self._process is not None and self._process.is_alive()
   143	
   144	    def poll_readings(self) -> list[Reading]:
   145	        """Drain all available readings from the data queue. Non-blocking."""
   146	        readings: list[Reading] = []
   147	        while True:
   148	            try:
   149	                d = self._data_queue.get_nowait()
   150	                # Handle internal control messages from subprocess
   151	                msg_type = d.get("__type")
   152	                if msg_type == "heartbeat":
   153	                    self._last_heartbeat = time.monotonic()
   154	                    continue
   155	                if msg_type == "cmd_timeout":
   156	                    # IV.6 B1 fix: structured timeout marker used by the
   157	                    # launcher's command-channel watchdog. Separate from
   158	                    # "warning" because the launcher must restart the
   159	                    # bridge on this specific failure shape, not on
   160	                    # generic queue-overflow warnings.
   161	                    self._last_cmd_timeout = time.monotonic()
   162	                    logger.warning(
   163	                        "ZMQ bridge: %s",
   164	                        d.get("message", "command timeout"),
   165	                    )
   166	                    continue
   167	                if msg_type == "warning":
   168	                    logger.warning("ZMQ bridge: %s", d.get("message", ""))
   169	                    continue
   170	                self._last_reading_time = time.monotonic()
   171	                readings.append(_reading_from_dict(d))
   172	            except (queue.Empty, EOFError):
   173	                break
   174	            except Exception as exc:
   175	                logger.warning("poll_readings: error processing item: %s", exc)
   176	                continue
   177	        return readings
   178	
   179	    def heartbeat_stale(self, *, timeout_s: float = 30.0) -> bool:
   180	        """Return True if the bridge heartbeat is older than ``timeout_s``."""
   181	        return (
   182	            self._last_heartbeat != 0.0 and (time.monotonic() - self._last_heartbeat) >= timeout_s
   183	        )
   184	
   185	    def data_flow_stalled(self, *, timeout_s: float = 30.0) -> bool:
   186	        """Return True if readings previously flowed but are now stale."""
   187	        return (
   188	            self._last_reading_time != 0.0
   189	            and (time.monotonic() - self._last_reading_time) >= timeout_s
   190	        )
   191	
   192	    def command_channel_stalled(self, *, timeout_s: float = 10.0) -> bool:
   193	        """Return True if a command timeout occurred within the last
   194	        ``timeout_s`` seconds.
   195	
   196	        IV.6 B1 fix: used by launcher watchdog to detect command-channel-
   197	        only failures (data plane still healthy but commands fail). Single
   198	        recent timeout is enough to trigger — streak-count threshold may
   199	        be introduced later if field testing shows false positives.
   200	        """
   201	        if self._last_cmd_timeout == 0.0:
   202	            return False
   203	        return (time.monotonic() - self._last_cmd_timeout) < timeout_s
   204	
   205	    def is_healthy(self) -> bool:
   206	        """True if subprocess is alive and bridge heartbeats are fresh."""
   207	        return self.is_alive() and not self.heartbeat_stale()
   208	
   209	    def restart_count(self) -> int:
   210	        """Return the number of bridge restarts since launcher start."""
   211	        return self._restart_count
   212	
   213	    def send_command(self, cmd: dict) -> dict:
   214	        """Thread-safe command dispatch with Future-per-request correlation."""
   215	        if not self.is_alive():
   216	            return {"ok": False, "error": "ZMQ bridge subprocess not running"}
   217	
   218	        rid = uuid.uuid4().hex[:8]
   219	        cmd = {**cmd, "_rid": rid}
   220	        future: Future = Future()
   221	
   222	        with self._pending_lock:
   223	            self._pending[rid] = future
   224	
   225	        try:
   226	            self._cmd_queue.put(cmd, timeout=2.0)
   227	            return future.result(timeout=_CMD_REPLY_TIMEOUT_S)
   228	        except Exception as exc:
   229	            return {"ok": False, "error": f"Engine не отвечает ({type(exc).__name__}: {exc})"}
   230	        finally:
   231	            with self._pending_lock:
   232	                self._pending.pop(rid, None)
   233	
   234	    def _consume_replies(self) -> None:
   235	        """Dedicated thread: reads replies from subprocess, routes to correct Future."""
   236	        while not self._reply_stop.is_set():
   237	            try:
   238	                reply = self._reply_queue.get(timeout=0.5)
   239	            except queue.Empty:
   240	                continue
   241	            except (EOFError, OSError):
   242	                break
   243	
   244	            try:
   245	                if not isinstance(reply, dict):
   246	                    logger.warning("ZMQ reply consumer: non-dict reply: %r", type(reply))
   247	                    continue
   248	                rid = reply.pop("_rid", None)
   249	                if rid:
   250	                    with self._pending_lock:
   251	                        future = self._pending.get(rid)
   252	                    if future and not future.done():
   253	                        future.set_result(reply)
   254	                        continue
   255	                logger.debug("Unmatched ZMQ reply (rid=%s)", rid)
   256	            except Exception:
   257	                logger.exception("ZMQ reply consumer: error processing reply")
   258	
   259	    def shutdown(self) -> None:
   260	        """Signal subprocess to stop, cancel pending futures, wait for exit."""

exec
/opt/homebrew/bin/bash -lc 'git log --oneline --decorate -10 experiment/iv7-ipc-transport' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
63a3fed (experiment/iv7-ipc-transport) Make launcher transport probe IPC-aware
157c4bc Add shared ZMQ transport defaults
b2b4fb5 (codex/safe-merge-b1-truth-recovery) fix: harden B1 capture bridge startup validation
4cdc4f4 docs: align B1 runbook artifact path
9ccb3d5 docs: finalize B1 handoff truth-recovery packet
0a4ae04 review: update Kimi/Metaswarm arbitration with evidence-gap findings
bbc65c8 diagnostics: add B1 evidence documentation (runbook NOT RUN - env unavailable)
8feda6b review: add roadmap review artifacts from codex/gemini/kimi/metaswarm passes
ab72c84 docs: add roadmap review prompts and resolution ledger
8ddd2f4 (origin/codex/safe-merge-b1-truth-recovery) docs: align release gating with reconstructed version lines

exec
/opt/homebrew/bin/bash -lc "git show experiment/iv7-ipc-transport:src/cryodaq/core/zmq_subprocess.py | nl -ba | sed -n '1,260p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	"""ZMQ bridge running in a separate process.
     2	
     3	This process owns ALL ZMQ sockets. If libzmq crashes (signaler.cpp
     4	assertion on Windows), only this subprocess dies. The GUI detects
     5	the death via is_alive() and restarts it.
     6	
     7	The GUI process never imports zmq.
     8	
     9	Threading model (see fix(gui): split bridge subprocess ...):
    10	- sub_drain owns the SUB socket, receives readings, emits heartbeats.
    11	  Heartbeat comes from this thread so it proves the *data* path is alive.
    12	- cmd_forward owns the REQ socket, sends commands and waits up to 3s
    13	  per reply. May block; does not affect sub_drain.
    14	- Main thread starts both threads and waits on shutdown_event.
    15	"""
    16	
    17	from __future__ import annotations
    18	
    19	import contextlib
    20	import json
    21	import logging
    22	import multiprocessing as mp
    23	import queue
    24	import threading
    25	import time
    26	from typing import Any
    27	
    28	from cryodaq.core.zmq_transport import DEFAULT_CMD_ADDR, DEFAULT_PUB_ADDR
    29	
    30	logger = logging.getLogger(__name__)
    31	
    32	# Re-export constants so GUI code doesn't need to import zmq_bridge
    33	# Mirror of zmq_bridge.DEFAULT_TOPIC. Duplicated (not imported) because this
    34	# module is loaded in the GUI process, which must not import zmq/zmq_bridge
    35	# at module scope. Keep in sync with cryodaq.core.zmq_bridge.DEFAULT_TOPIC.
    36	DEFAULT_TOPIC = b"readings"
    37	
    38	
    39	def _unpack_reading_dict(payload: bytes) -> dict[str, Any]:
    40	    """Unpack msgpack Reading into a plain dict (picklable for mp.Queue)."""
    41	    import msgpack
    42	
    43	    data = msgpack.unpackb(payload, raw=False)
    44	    return {
    45	        "timestamp": data["ts"],
    46	        "instrument_id": data.get("iid", ""),
    47	        "channel": data["ch"],
    48	        "value": data["v"],
    49	        "unit": data["u"],
    50	        "status": data["st"],
    51	        "raw": data.get("raw"),
    52	        "metadata": data.get("meta", {}),
    53	    }
    54	
    55	
    56	def zmq_bridge_main(
    57	    pub_addr: str,
    58	    cmd_addr: str,
    59	    data_queue: mp.Queue,
    60	    cmd_queue: mp.Queue,
    61	    reply_queue: mp.Queue,
    62	    shutdown_event: mp.Event,
    63	) -> None:
    64	    """Entry point for ZMQ bridge subprocess.
    65	
    66	    Parameters
    67	    ----------
    68	    pub_addr:
    69	        Engine PUB address, e.g. "tcp://127.0.0.1:5555".
    70	    cmd_addr:
    71	        Engine REP address, e.g. "tcp://127.0.0.1:5556".
    72	    data_queue:
    73	        Subprocess → GUI: Reading dicts plus control messages
    74	        (``__type`` in {"heartbeat", "warning"}).
    75	    cmd_queue:
    76	        GUI → subprocess: command dicts to send via REQ.
    77	    reply_queue:
    78	        Subprocess → GUI: command reply dicts.
    79	    shutdown_event:
    80	        Set by GUI to signal clean shutdown.
    81	    """
    82	    import zmq
    83	
    84	    HEARTBEAT_INTERVAL = 5.0  # seconds — keep generous vs is_healthy() threshold
    85	
    86	    ctx = zmq.Context()
    87	
    88	    dropped_counter = {"n": 0}
    89	
    90	    def sub_drain_loop() -> None:
    91	        """Own SUB socket; drain readings and emit periodic heartbeats.
    92	
    93	        Heartbeat comes from this thread (not the command thread) so
    94	        the GUI's heartbeat freshness check proves the *data* path is
    95	        alive, not just that the subprocess exists.
    96	        """
    97	        # Order matters: connect() BEFORE subscribe(). The inverse pattern
    98	        # (subscribe-before-connect with setsockopt_string(SUBSCRIBE, "")) produced
    99	        # zero received messages on macOS Python 3.14 pyzmq 25+.
   100	        sub = ctx.socket(zmq.SUB)
   101	        sub.setsockopt(zmq.LINGER, 0)
   102	        sub.setsockopt(zmq.RCVTIMEO, 100)
   103	        # 2026-04-20 idle-death fix: same keepalive as REQ side to
   104	        # survive macOS kernel idle reaping. SUB normally gets a
   105	        # stream of readings so idle is rare, but between-experiment
   106	        # quiet periods exist (scheduler paused, no active polls).
   107	        sub.setsockopt(zmq.TCP_KEEPALIVE, 1)
   108	        sub.setsockopt(zmq.TCP_KEEPALIVE_IDLE, 10)
   109	        sub.setsockopt(zmq.TCP_KEEPALIVE_INTVL, 5)
   110	        sub.setsockopt(zmq.TCP_KEEPALIVE_CNT, 3)
   111	        sub.connect(pub_addr)
   112	        sub.subscribe(DEFAULT_TOPIC)
   113	        last_heartbeat = time.monotonic()
   114	        try:
   115	            while not shutdown_event.is_set():
   116	                # SUB: blocking receive with 100ms RCVTIMEO. Keeps the loop
   117	                # responsive for shutdown and heartbeat emission.
   118	                try:
   119	                    parts = sub.recv_multipart()
   120	                    if len(parts) == 2:
   121	                        try:
   122	                            reading_dict = _unpack_reading_dict(parts[1])
   123	                        except Exception:
   124	                            reading_dict = None  # skip malformed
   125	                        if reading_dict is not None:
   126	                            try:
   127	                                data_queue.put_nowait(reading_dict)
   128	                            except queue.Full:
   129	                                dropped_counter["n"] += 1
   130	                                if dropped_counter["n"] % 100 == 1:
   131	                                    with contextlib.suppress(queue.Full):
   132	                                        data_queue.put_nowait(
   133	                                            {
   134	                                                "__type": "warning",
   135	                                                "message": (
   136	                                                    f"Queue overflow: "
   137	                                                    f"{dropped_counter['n']} readings dropped"
   138	                                                ),
   139	                                            }
   140	                                        )
   141	                except zmq.Again:
   142	                    pass
   143	                except zmq.ZMQError:
   144	                    if shutdown_event.is_set():
   145	                        break
   146	                    # Unexpected socket error — swallow and continue.
   147	                    time.sleep(0.01)
   148	
   149	                now = time.monotonic()
   150	                if now - last_heartbeat >= HEARTBEAT_INTERVAL:
   151	                    with contextlib.suppress(queue.Full):
   152	                        data_queue.put_nowait({"__type": "heartbeat", "ts": now})
   153	                    last_heartbeat = now
   154	        finally:
   155	            sub.close(linger=0)
   156	
   157	    def cmd_forward_loop() -> None:
   158	        """Forward GUI commands via a fresh REQ socket per command.
   159	
   160	        IV.6 B1 fix: each command creates, uses, and closes its own REQ
   161	        socket. Shared long-lived REQ accumulated state across commands
   162	        and became permanently unrecoverable after a platform-specific
   163	        trigger (macOS sparse cadence within ~minutes, Ubuntu 120 s
   164	        deterministic). Ephemeral REQ per command matches ZeroMQ Guide
   165	        ch.4 canonical "poll / timeout / close / reopen" reliable
   166	        request-reply pattern.
   167	
   168	        May block up to 35 s per timed-out REQ. That does not starve
   169	        the data path because SUB drain runs on a separate thread.
   170	        A timed-out REQ emits a structured ``cmd_timeout`` control
   171	        message via data_queue so the launcher watchdog can detect
   172	        command-channel-only failures and restart the bridge.
   173	        """
   174	
   175	        def _new_req_socket():
   176	            """Build a fresh per-command REQ socket.
   177	
   178	            IV.6: REQ_RELAXED / REQ_CORRELATE dropped — they were only
   179	            useful for stateful recovery on a shared socket, which the
   180	            ephemeral model has eliminated. TCP_KEEPALIVE dropped from
   181	            the command path (reverting the f5f9039 partial fix) —
   182	            Codex revised analysis confirmed idle-reap was not the
   183	            actual cause; keepalive is a no-op here and clutters
   184	            debugging of the real socket state.
   185	            """
   186	            req = ctx.socket(zmq.REQ)
   187	            req.setsockopt(zmq.LINGER, 0)
   188	            # IV.3 Finding 7: REQ timeout stays at 35 s so a slow
   189	            # server-side handler (experiment_finalize / report
   190	            # generation, tiered at 30 s) has room to reply before
   191	            # the REQ side gives up. Server's 30 s ceiling + 5 s slack
   192	            # stays inside the client's 35 s future wait
   193	            # (_CMD_REPLY_TIMEOUT_S), so timeouts at each layer fire
   194	            # in predictable order: server → subprocess → GUI future.
   195	            req.setsockopt(zmq.RCVTIMEO, 35000)
   196	            req.setsockopt(zmq.SNDTIMEO, 35000)
   197	            req.connect(cmd_addr)
   198	            return req
   199	
   200	        while not shutdown_event.is_set():
   201	            try:
   202	                cmd = cmd_queue.get(timeout=0.5)
   203	            except queue.Empty:
   204	                continue
   205	            rid = cmd.pop("_rid", None) if isinstance(cmd, dict) else None
   206	            cmd_type = cmd.get("cmd", "?") if isinstance(cmd, dict) else "?"
   207	
   208	            # Fresh socket per command — no shared state across commands.
   209	            req = _new_req_socket()
   210	            try:
   211	                try:
   212	                    req.send_string(json.dumps(cmd))
   213	                    reply_raw = req.recv_string()
   214	                    reply = json.loads(reply_raw)
   215	                except zmq.ZMQError as exc:
   216	                    reply = {"ok": False, "error": f"Engine не отвечает ({exc})"}
   217	                    with contextlib.suppress(queue.Full):
   218	                        data_queue.put_nowait(
   219	                            {
   220	                                "__type": "cmd_timeout",
   221	                                "cmd": cmd_type,
   222	                                "ts": time.monotonic(),
   223	                                "message": f"REP timeout on {cmd_type} ({exc})",
   224	                            }
   225	                        )
   226	                except Exception as exc:  # noqa: BLE001
   227	                    reply = {"ok": False, "error": str(exc)}
   228	            finally:
   229	                req.close(linger=0)
   230	
   231	            if rid is not None:
   232	                reply["_rid"] = rid
   233	            try:
   234	                reply_queue.put(reply, timeout=2.0)
   235	            except queue.Full:
   236	                with contextlib.suppress(queue.Full):
   237	                    data_queue.put_nowait(
   238	                        {"__type": "warning", "message": "Reply queue overflow"}
   239	                    )
   240	
   241	    sub_thread = threading.Thread(target=sub_drain_loop, name="zmq-sub-drain", daemon=True)
   242	    cmd_thread = threading.Thread(target=cmd_forward_loop, name="zmq-cmd-forward", daemon=True)
   243	
   244	    try:
   245	        sub_thread.start()
   246	        cmd_thread.start()
   247	        while not shutdown_event.is_set():
   248	            shutdown_event.wait(timeout=0.5)
   249	    except KeyboardInterrupt:
   250	        pass
   251	    finally:
   252	        shutdown_event.set()
   253	        sub_thread.join(timeout=2.0)
   254	        cmd_thread.join(timeout=4.0)
   255	        if sub_thread.is_alive() or cmd_thread.is_alive():
   256	            logger.warning("ZMQ bridge threads did not exit cleanly before context term")
   257	        ctx.term()

exec
/opt/homebrew/bin/bash -lc 'rg -n "diag_zmq_b1_capture|validate_bridge|ipc://|cmd_timeout|safety_status|20/20|Resource temporarily unavailable|cmd #0" docs/decisions/2026-04-24-b2b4fb5-investigation.md' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
6:capture bridge startup validation") is incompatible with the `ipc://`
9:to the ipc:// switch itself.
13:`b2b4fb5`'s synchronous startup probe `_validate_bridge_startup()`
14:fails against a fresh ipc://-bound engine because the engine's REP
18:and the capture tool aborts at cmd #0.
22:succeeded against ipc:// with the hardening reverted.
24:**IV.7 failure on 2026-04-23 was not caused by the ipc:// transport
26:ipc:// bind timing.**
41:Thesis: `b2b4fb5` only touches `tools/diag_zmq_b1_capture.py` and its
56:    {'ok': False, 'error': 'Engine не отвечает (Resource temporarily unavailable)'}
58:This is the **exact literal output** of `_validate_bridge_startup`
59:from `b2b4fb5`. The tool used for the IV.7 test was `diag_zmq_b1_capture.py`
62:at cmd #0.
68:instantaneous, so the check tends to pass. Under ipc://, socket-file
83:### 00:15 — Extended diag against ipc:// engine (bridge_extended.py)
91:- Engine bound to `ipc:///tmp/cryodaq-pub.sock` and
92:  `ipc:///tmp/cryodaq-cmd.sock` (Unix default from
103:Interpretation: **ipc:// transport itself works for ~80s**, then the
111:B1 degraded state, ran `tools/diag_zmq_b1_capture.py` (short,
115:(Resource temporarily unavailable)"}`, `direct_reply: TimeoutError`.
126:`tools/diag_zmq_b1_capture.py --duration 20 --interval 1`.
129:- 20/20 samples successful.
134:normally against ipc://**. The exact same tool with the exact same
150:| IV.7 2026-04-23 failure | present | ipc:// | ~fresh (< 1s) | **abort at cmd#0** — "Engine не отвечает" |
151:| retest 2026-04-24 (bridge_extended) | reverted | ipc:// | 4s | 44/44 early OK, B1 idle-death at cmd #45 |
152:| retest 2026-04-24 (b1_capture against degraded engine) | reverted | ipc:// | ~4 min | fail (engine already broken by B1) |
153:| retest 2026-04-24 (b1_capture against fresh engine) | reverted | ipc:// | 4s | **20/20 OK** |
157:makes b1_capture pass on ipc://.
163:1. IV.7's `ipc://` transport is viable. It runs normally for the
165:2. `b2b4fb5`'s startup probe is incompatible with ipc:// at engine
184:Rework `_validate_bridge_startup()` to retry the probe with bounded
223:- `tools/diag_zmq_b1_capture.py` — hardening lives here, lines
225:- `src/cryodaq/core/zmq_transport.py` — ipc:// defaults (iv7
231:- `/tmp/b1_retest_fresh.jsonl` — 20/20 success with revert
233:  signature on ipc://

exec
/opt/homebrew/bin/bash -lc "git show experiment/iv7-ipc-transport:src/cryodaq/core/zmq_bridge.py | nl -ba | sed -n '420,560p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   420	        action = str(cmd.get("cmd", ""))
   421	        timeout = (
   422	            self._handler_timeout_override_s
   423	            if self._handler_timeout_override_s is not None
   424	            else _timeout_for(cmd)
   425	        )
   426	
   427	        async def _invoke() -> Any:
   428	            result = self._handler(cmd)
   429	            if asyncio.iscoroutine(result):
   430	                result = await result
   431	            return result
   432	
   433	        try:
   434	            result = await asyncio.wait_for(_invoke(), timeout=timeout)
   435	        except TimeoutError as exc:
   436	            # Preserve inner wrapper message when present (e.g.
   437	            # "log_get timeout (1.5s)"). Falls back to the generic
   438	            # envelope message when the timeout fired at the outer
   439	            # asyncio.wait_for layer.
   440	            inner_message = str(exc).strip()
   441	            error_message = (
   442	                inner_message
   443	                if inner_message
   444	                else f"handler timeout ({timeout:g}s); operation may still be running."
   445	            )
   446	            logger.error(
   447	                "ZMQ command handler timeout: action=%s error=%s payload=%r",
   448	                action,
   449	                error_message,
   450	                cmd,
   451	            )
   452	            return {
   453	                "ok": False,
   454	                "error": error_message,
   455	                "_handler_timeout": True,
   456	            }
   457	        except asyncio.CancelledError:
   458	            # Cancellation is not a handler failure — propagate so the
   459	            # serve loop can still try to send its own short error
   460	            # reply before the task itself tears down.
   461	            raise
   462	        except Exception as exc:
   463	            # Belt-and-suspenders: the outer serve loop already catches
   464	            # exceptions and sends an error reply, but pushing the
   465	            # dict back through the normal return path keeps the REP
   466	            # state-machine handling uniform with the timeout branch.
   467	            logger.exception(
   468	                "ZMQ command handler failed: action=%s payload=%r",
   469	                action,
   470	                cmd,
   471	            )
   472	            return {"ok": False, "error": str(exc) or type(exc).__name__}
   473	
   474	        return result if isinstance(result, dict) else {"ok": True}
   475	
   476	    async def _serve_loop(self) -> None:
   477	        while self._running:
   478	            try:
   479	                raw = await asyncio.wait_for(self._socket.recv(), timeout=1.0)
   480	            except TimeoutError:
   481	                continue
   482	            except asyncio.CancelledError:
   483	                raise
   484	            except Exception:
   485	                logger.exception("Ошибка приёма команды ZMQ")
   486	                continue
   487	
   488	            # Once recv() succeeds, the REP socket is in "awaiting send" state.
   489	            # We MUST send a reply — otherwise the socket is stuck forever.
   490	            try:
   491	                cmd = json.loads(raw)
   492	            except (json.JSONDecodeError, UnicodeDecodeError):
   493	                await self._socket.send(json.dumps({"ok": False, "error": "invalid JSON"}).encode())
   494	                continue
   495	
   496	            try:
   497	                reply = await self._run_handler(cmd)
   498	            except asyncio.CancelledError:
   499	                # CancelledError during handler — must still send reply
   500	                # to avoid leaving REP socket in stuck state.
   501	                try:
   502	                    await self._socket.send(json.dumps({"ok": False, "error": "internal"}).encode())
   503	                except Exception:
   504	                    pass
   505	                raise
   506	            except Exception as exc:
   507	                logger.exception("Ошибка обработки команды: %s", cmd)
   508	                reply = {"ok": False, "error": str(exc)}
   509	
   510	            try:
   511	                await self._socket.send(json.dumps(reply, default=str).encode())
   512	            except asyncio.CancelledError:
   513	                # Shutting down — try best-effort send
   514	                try:
   515	                    await self._socket.send(json.dumps({"ok": False, "error": "internal"}).encode())
   516	                except Exception:
   517	                    pass
   518	                raise
   519	            except Exception:
   520	                logger.exception("Ошибка отправки ответа ZMQ")
   521	                # Serialization or send failure — must still send a reply
   522	                # to avoid leaving the REP socket in stuck state.
   523	                try:
   524	                    await self._socket.send(
   525	                        json.dumps({"ok": False, "error": "serialization error"}).encode()
   526	                    )
   527	                except Exception:
   528	                    pass
   529	
   530	    async def start(self) -> None:
   531	        self._ctx = zmq.asyncio.Context()
   532	        self._socket = self._ctx.socket(zmq.REP)
   533	        # Phase 2b H.4: LINGER=0 + EADDRINUSE retry on bind.
   534	        self._socket.setsockopt(zmq.LINGER, 0)
   535	        # IV.6: TCP_KEEPALIVE previously added on the idle-reap
   536	        # hypothesis (commit f5f9039). Reverted — the actual fix is
   537	        # an ephemeral per-command REQ socket on the GUI subprocess
   538	        # side (zmq_subprocess.cmd_forward_loop). With a fresh TCP
   539	        # connection per command, loopback kernel reaping is moot.
   540	        prepare_ipc_path(self._address)
   541	        _bind_with_retry(self._socket, self._address)
   542	        self._running = True
   543	        self._shutdown_requested = False
   544	        self._start_serve_task()
   545	        logger.info("ZMQCommandServer запущен: %s", self._address)
   546	
   547	    async def stop(self) -> None:
   548	        self._shutdown_requested = True
   549	        self._running = False
   550	        if self._task:
   551	            self._task.cancel()
   552	            try:
   553	                await self._task
   554	            except asyncio.CancelledError:
   555	                pass
   556	            self._task = None
   557	        if self._socket:
   558	            self._socket.close(linger=0)
   559	            self._socket = None
   560	        if self._ctx:

exec
/opt/homebrew/bin/bash -lc "git show experiment/iv7-ipc-transport:tests/test_zmq_bind_recovery.py | nl -ba | sed -n '1,220p' && git show experiment/iv7-ipc-transport:tests/core/test_zmq_transport_defaults.py | nl -ba | sed -n '1,220p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	"""Verify ZMQ bind has EADDRINUSE retry + LINGER=0 (Phase 2b H.4)."""
     2	
     3	from __future__ import annotations
     4	
     5	import inspect
     6	
     7	import pytest
     8	import zmq
     9	
    10	from cryodaq.core import zmq_bridge
    11	
    12	
    13	def test_bind_with_retry_helper_exists():
    14	    assert hasattr(zmq_bridge, "_bind_with_retry")
    15	
    16	
    17	def test_bind_with_retry_succeeds_on_first_try():
    18	    """A clean bind to an unused address must succeed without retry."""
    19	    ctx = zmq.Context()
    20	    sock = ctx.socket(zmq.PUB)
    21	    sock.setsockopt(zmq.LINGER, 0)
    22	    try:
    23	        zmq_bridge._bind_with_retry(sock, "tcp://127.0.0.1:0")
    24	    finally:
    25	        sock.close(linger=0)
    26	        ctx.term()
    27	
    28	
    29	def test_bind_with_retry_raises_on_non_eaddrinuse():
    30	    """Non-EADDRINUSE ZMQError must propagate immediately, not retry."""
    31	    ctx = zmq.Context()
    32	    sock = ctx.socket(zmq.PUB)
    33	    sock.setsockopt(zmq.LINGER, 0)
    34	    try:
    35	        with pytest.raises(zmq.ZMQError):
    36	            # An invalid endpoint produces a ZMQError that is NOT EADDRINUSE.
    37	            zmq_bridge._bind_with_retry(sock, "totally-bogus://nope")
    38	    finally:
    39	        sock.close(linger=0)
    40	        ctx.term()
    41	
    42	
    43	def test_publisher_sets_linger_before_bind():
    44	    """LINGER must be set on PUB socket BEFORE bind in source order."""
    45	    src = inspect.getsource(zmq_bridge)
    46	    pub_start = src.find("class ZMQPublisher")
    47	    pub_end = src.find("class ZMQSubscriber")
    48	    assert pub_start >= 0 and pub_end >= 0
    49	    pub_block = src[pub_start:pub_end]
    50	    linger_pos = pub_block.find("LINGER")
    51	    bind_pos = pub_block.find("_bind_with_retry")
    52	    assert linger_pos >= 0, "PUB socket must set LINGER"
    53	    assert bind_pos >= 0, "PUB socket must use _bind_with_retry"
    54	    assert linger_pos < bind_pos, "LINGER must be set BEFORE bind"
    55	
    56	
    57	def test_command_server_sets_linger_before_bind():
    58	    """LINGER must be set on REP socket BEFORE bind in source order."""
    59	    src = inspect.getsource(zmq_bridge)
    60	    rep_start = src.find("class ZMQCommandServer")
    61	    assert rep_start >= 0
    62	    rep_block = src[rep_start:]
    63	    linger_pos = rep_block.find("LINGER")
    64	    bind_pos = rep_block.find("_bind_with_retry")
    65	    assert linger_pos >= 0, "REP socket must set LINGER"
    66	    assert bind_pos >= 0, "REP socket must use _bind_with_retry"
    67	    assert linger_pos < bind_pos, "LINGER must be set BEFORE bind"
    68	
    69	
    70	def test_no_raw_bind_in_publisher_or_command_server():
    71	    """Make sure neither class still uses unguarded socket.bind(...)."""
    72	    src = inspect.getsource(zmq_bridge)
    73	    for class_name in ("class ZMQPublisher", "class ZMQCommandServer"):
    74	        start = src.find(class_name)
    75	        end = src.find("class ", start + 10)
    76	        block = src[start:end] if end >= 0 else src[start:]
    77	        # The retry helper is the only allowed bind path in these classes.
    78	        assert "self._socket.bind(" not in block, (
    79	            f"{class_name} still calls raw self._socket.bind() — must use _bind_with_retry"
    80	        )
    81	
    82	
    83	def test_publisher_start_prepares_ipc_path_before_bind() -> None:
    84	    src = inspect.getsource(zmq_bridge)
    85	    pub_start = src.find("class ZMQPublisher")
    86	    pub_end = src.find("class ZMQSubscriber")
    87	    assert pub_start >= 0 and pub_end >= 0
    88	    pub_block = src[pub_start:pub_end]
    89	    prepare_pos = pub_block.find("prepare_ipc_path")
    90	    bind_pos = pub_block.find("_bind_with_retry")
    91	    assert prepare_pos >= 0, "PUB socket must prepare ipc path before bind"
    92	    assert bind_pos >= 0
    93	    assert prepare_pos < bind_pos
    94	
    95	
    96	def test_command_server_start_prepares_ipc_path_before_bind() -> None:
    97	    src = inspect.getsource(zmq_bridge)
    98	    rep_start = src.find("class ZMQCommandServer")
    99	    assert rep_start >= 0
   100	    rep_block = src[rep_start:]
   101	    prepare_pos = rep_block.find("prepare_ipc_path")
   102	    bind_pos = rep_block.find("_bind_with_retry")
   103	    assert prepare_pos >= 0, "REP socket must prepare ipc path before bind"
   104	    assert bind_pos >= 0
   105	    assert prepare_pos < bind_pos
     1	from __future__ import annotations
     2	
     3	import socket
     4	import sys
     5	import tempfile
     6	import uuid
     7	from pathlib import Path
     8	
     9	import pytest
    10	
    11	from cryodaq.core import zmq_transport
    12	
    13	
    14	def _short_socket_path(name: str) -> Path:
    15	    return Path(tempfile.gettempdir()) / f"cryodaq-{name}-{uuid.uuid4().hex}.sock"
    16	
    17	
    18	def test_default_addr_prefixes_match_platform() -> None:
    19	    if sys.platform == "win32":
    20	        assert zmq_transport.DEFAULT_PUB_ADDR.startswith("tcp://")
    21	        assert zmq_transport.DEFAULT_CMD_ADDR.startswith("tcp://")
    22	    else:
    23	        assert zmq_transport.DEFAULT_PUB_ADDR.startswith("ipc://")
    24	        assert zmq_transport.DEFAULT_CMD_ADDR.startswith("ipc://")
    25	
    26	
    27	def test_pub_and_cmd_addrs_are_different() -> None:
    28	    assert zmq_transport.DEFAULT_PUB_ADDR != zmq_transport.DEFAULT_CMD_ADDR
    29	
    30	
    31	def test_tcp_host_port_parses_tcp_address() -> None:
    32	    assert zmq_transport.tcp_host_port("tcp://127.0.0.1:5556") == ("127.0.0.1", 5556)
    33	
    34	
    35	def test_tcp_host_port_returns_none_for_ipc() -> None:
    36	    assert zmq_transport.tcp_host_port("ipc:///tmp/cryodaq-cmd.sock") is None
    37	
    38	
    39	def test_prepare_ipc_path_unlinks_stale_socket_path() -> None:
    40	    sock_path = _short_socket_path("stale")
    41	    stale_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    42	    stale_socket.bind(str(sock_path))
    43	    stale_socket.close()
    44	    try:
    45	        zmq_transport.prepare_ipc_path(f"ipc://{sock_path}")
    46	        assert sock_path.exists() is False
    47	    finally:
    48	        if sock_path.exists():
    49	            sock_path.unlink()
    50	
    51	
    52	def test_prepare_ipc_path_refuses_live_socket_path() -> None:
    53	    sock_path = _short_socket_path("live")
    54	    live_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    55	    live_socket.bind(str(sock_path))
    56	    live_socket.listen(1)
    57	    try:
    58	        with pytest.raises(FileExistsError, match="live IPC endpoint"):
    59	            zmq_transport.prepare_ipc_path(f"ipc://{sock_path}")
    60	        assert sock_path.exists()
    61	    finally:
    62	        live_socket.close()
    63	        if sock_path.exists():
    64	            sock_path.unlink()
    65	
    66	
    67	def test_cleanup_ipc_path_suppresses_missing_file(tmp_path) -> None:
    68	    zmq_transport.cleanup_ipc_path(f"ipc://{tmp_path / 'missing.sock'}")
    69	
    70	
    71	def test_cleanup_ipc_path_unlinks_stale_socket_path() -> None:
    72	    sock_path = _short_socket_path("cst")
    73	    stale_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    74	    stale_socket.bind(str(sock_path))
    75	    stale_socket.close()
    76	    try:
    77	        zmq_transport.cleanup_ipc_path(f"ipc://{sock_path}")
    78	        assert sock_path.exists() is False
    79	    finally:
    80	        if sock_path.exists():
    81	            sock_path.unlink()
    82	
    83	
    84	def test_cleanup_ipc_path_refuses_non_socket_file(tmp_path) -> None:
    85	    file_path = tmp_path / "not-a-socket.sock"
    86	    file_path.write_text("not a socket")
    87	
    88	    with pytest.raises(FileExistsError, match="non-socket IPC path"):
    89	        zmq_transport.cleanup_ipc_path(f"ipc://{file_path}")
    90	
    91	    assert file_path.exists()

exec
/opt/homebrew/bin/bash -lc "rg -n \"ZmqBridge\\(|\\.start\\(\\)|send_command\\(|command_channel_stalled\\(|is_alive\\(\\)\" src tests tools | head -200" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
tools/diag_zmq_bridge_extended.py:43:    bridge = ZmqBridge()
tools/diag_zmq_bridge_extended.py:44:    bridge.start()
tools/diag_zmq_bridge_extended.py:46:    print(f"[{_ts()}] bridge started, subprocess alive = {bridge.is_alive()}")
tools/diag_zmq_bridge_extended.py:61:        reply = bridge.send_command({"cmd": "safety_status"})
tools/diag_zmq_bridge.py:57:        reply = bridge.send_command({"cmd": "safety_status"})
tools/diag_zmq_bridge.py:74:        reply = bridge.send_command({"cmd": "safety_status"})
tools/diag_zmq_bridge.py:89:        t.start()
tools/diag_zmq_bridge.py:103:        reply = bridge.send_command({"cmd": "safety_status"})
tools/diag_zmq_bridge.py:127:    bridge = ZmqBridge()
tools/diag_zmq_bridge.py:129:    bridge.start()
tools/diag_zmq_bridge.py:133:    print(f"[{_ts()}] ZmqBridge started, subprocess alive = {bridge.is_alive()}")
tools/diag_zmq_idle_hypothesis.py:45:        reply = bridge.send_command({"cmd": "safety_status"})
tools/diag_zmq_idle_hypothesis.py:77:    bridge = ZmqBridge()
tools/diag_zmq_idle_hypothesis.py:78:    bridge.start()
tools/diag_zmq_idle_hypothesis.py:80:    print(f"[{_ts()}] bridge alive = {bridge.is_alive()}")
tools/diag_zmq_subprocess.py:81:    proc.start()
tools/diag_zmq_subprocess.py:82:    print(f"[main] proc.start() returned after {time.monotonic()-t_start:.3f}s")
tools/diag_zmq_subprocess.py:88:    alive = proc.is_alive()
tools/diag_zmq_subprocess.py:89:    print(f"[main] proc.is_alive() after 3s: {alive}")
tools/diag_zmq_subprocess.py:157:        print(f"[main] proc.is_alive() after timeout: {proc.is_alive()}")
tools/diag_zmq_subprocess.py:158:        if proc.is_alive():
tools/diag_zmq_subprocess.py:165:    if proc.is_alive():
tools/diag_zmq_subprocess.py:169:        if proc.is_alive():
tests/analytics/test_cooldown_service.py:165:    """CooldownService.start() then stop() must complete without errors."""
tests/analytics/test_cooldown_service.py:172:    await service.start()
tests/analytics/test_cooldown_service.py:191:    await service.start()
tests/analytics/test_cooldown_service.py:223:    await service.start()
tests/analytics/test_cooldown_service.py:260:    await service.start()
tests/analytics/test_cooldown_service.py:315:    await service.start()
tests/analytics/test_cooldown_service.py:380:    await service.start()
tests/analytics/test_cooldown_service.py:454:    await service.start()
tools/force_phase.py:77:        reply = send_command(cmd, address=args.address, timeout_s=args.timeout)
tests/analytics/test_plugins.py:85:    await pipeline.start()
tests/analytics/test_plugins.py:102:    await pipeline.start()
tests/analytics/test_plugins.py:146:    await pipeline.start()
tests/analytics/test_plugins.py:182:    await pipeline.start()
src/cryodaq/launcher.py:248:        self._async_timer.start()
src/cryodaq/launcher.py:251:        self._bridge = ZmqBridge()
src/cryodaq/launcher.py:259:        self._bridge.start()
src/cryodaq/launcher.py:273:        self._data_timer.start()
src/cryodaq/launcher.py:278:        self._health_timer.start()
src/cryodaq/launcher.py:284:            self._status_timer.start()
src/cryodaq/launcher.py:426:            self._engine_stderr_thread.start()
src/cryodaq/launcher.py:486:        self._bridge.start()
src/cryodaq/launcher.py:487:        self._data_timer.start()
src/cryodaq/launcher.py:488:        self._health_timer.start()
src/cryodaq/launcher.py:898:            if self._bridge.is_alive():
src/cryodaq/launcher.py:903:            self._bridge.start()
src/cryodaq/launcher.py:908:            self._bridge.start()
src/cryodaq/launcher.py:915:        if self._bridge.command_channel_stalled(timeout_s=10.0):
src/cryodaq/launcher.py:927:                self._bridge.start()
src/cryodaq/launcher.py:1154:        if alive and self._bridge.is_alive():
src/cryodaq/launcher.py:1159:                worker.start()
tools/_zmq_helpers.py:48:def send_command(
src/cryodaq/analytics/plugin_loader.py:43:        await pipeline.start()
src/cryodaq/gui/widgets/temp_panel.py:218:        self._plot_timer.start()
tests/test_instance_lock.py:69:    proc.start()
tests/test_instance_lock.py:90:    proc.start()
tests/storage/test_disk_full_handling.py:121:    await mgr.start()
tests/storage/test_disk_full_handling.py:186:    await mgr.start()
src/cryodaq/gui/widgets/analytics_panel.py:82:        self._timer.start()
src/cryodaq/core/zmq_subprocess.py:5:the death via is_alive() and restarts it.
src/cryodaq/core/zmq_subprocess.py:245:        sub_thread.start()
src/cryodaq/core/zmq_subprocess.py:246:        cmd_thread.start()
src/cryodaq/core/zmq_subprocess.py:255:        if sub_thread.is_alive() or cmd_thread.is_alive():
src/cryodaq/gui/widgets/vacuum_trend_panel.py:93:        self._poll_timer.start()
src/cryodaq/gui/widgets/vacuum_trend_panel.py:244:        worker.start()
src/cryodaq/core/alarm.py:194:        await engine.start()
src/cryodaq/gui/widgets/preflight_dialog.py:81:            worker.start()
src/cryodaq/core/interlock.py:160:        await engine.start()
src/cryodaq/web/server.py:199:    await sub.start()
src/cryodaq/core/scheduler.py:77:        await scheduler.start()
src/cryodaq/gui/widgets/overview_panel.py:212:        self._timer.start()
src/cryodaq/gui/widgets/overview_panel.py:867:        self._timer.start()
src/cryodaq/gui/widgets/overview_panel.py:880:        self._worker.start()
src/cryodaq/gui/widgets/overview_panel.py:985:        self._refresh_timer.start()
src/cryodaq/gui/widgets/overview_panel.py:1005:        worker.start()
src/cryodaq/gui/widgets/overview_panel.py:1023:        self._refresh_worker.start()
src/cryodaq/gui/widgets/overview_panel.py:1094:        self._plot_timer.start()
src/cryodaq/gui/widgets/overview_panel.py:1679:        self._history_worker.start()
tests/core/test_scheduler.py:80:    await sched.start()
tests/core/test_scheduler.py:118:    await sched.start()
tests/core/test_scheduler.py:137:    await sched.start()
tests/core/test_scheduler.py:168:    await sched.start()
tests/core/test_scheduler.py:205:    await sched.start()
tests/core/test_scheduler.py:226:    await sched.start()
tests/core/test_scheduler.py:244:    await sched.start()
src/cryodaq/gui/zmq_client.py:53:        bridge = ZmqBridge()
src/cryodaq/gui/zmq_client.py:54:        bridge.start()
src/cryodaq/gui/zmq_client.py:59:        reply = bridge.send_command({"cmd": "safety_status"})
src/cryodaq/gui/zmq_client.py:84:        # ``command_channel_stalled()`` to detect command-channel-only
src/cryodaq/gui/zmq_client.py:98:        if self._process is not None and self._process.is_alive():
src/cryodaq/gui/zmq_client.py:100:        if self._reply_consumer is not None and self._reply_consumer.is_alive():
src/cryodaq/gui/zmq_client.py:122:        self._process.start()
src/cryodaq/gui/zmq_client.py:132:        self._reply_consumer.start()
src/cryodaq/gui/zmq_client.py:142:        return self._process is not None and self._process.is_alive()
src/cryodaq/gui/zmq_client.py:192:    def command_channel_stalled(self, *, timeout_s: float = 10.0) -> bool:
src/cryodaq/gui/zmq_client.py:207:        return self.is_alive() and not self.heartbeat_stale()
src/cryodaq/gui/zmq_client.py:213:    def send_command(self, cmd: dict) -> dict:
src/cryodaq/gui/zmq_client.py:215:        if not self.is_alive():
src/cryodaq/gui/zmq_client.py:268:        if self._reply_consumer is not None and self._reply_consumer.is_alive():
src/cryodaq/gui/zmq_client.py:275:            if self._process.is_alive():
src/cryodaq/gui/zmq_client.py:310:def send_command(cmd: dict) -> dict:
src/cryodaq/gui/zmq_client.py:314:    return _bridge.send_command(cmd)
src/cryodaq/gui/zmq_client.py:333:        result = send_command(self._cmd)
tests/core/test_persistence_ordering.py:123:        await sched.start()
tests/core/test_persistence_ordering.py:153:    await sched.start()
tests/core/test_persistence_ordering.py:266:    await sched.start()
src/cryodaq/core/zmq_bridge.py:234:        await sub.start()
src/cryodaq/core/zmq_bridge.py:320:        await srv.start()
src/cryodaq/gui/widgets/pressure_panel.py:65:        self._timer.start()
src/cryodaq/gui/app.py:261:    bridge = ZmqBridge()
src/cryodaq/gui/app.py:263:    bridge.start()
src/cryodaq/gui/app.py:279:            if bridge.is_alive():
src/cryodaq/gui/app.py:284:            bridge.start()
src/cryodaq/gui/app.py:289:            bridge.start()
src/cryodaq/gui/app.py:292:    timer.start()
src/cryodaq/drivers/transport/usbtmc.py:34:    thread.start()
src/cryodaq/gui/widgets/shift_handover.py:94:    worker.start()
src/cryodaq/gui/widgets/shift_handover.py:172:        worker.start()
src/cryodaq/gui/widgets/shift_handover.py:693:            worker.start()
src/cryodaq/gui/widgets/shift_handover.py:954:        self._tick_timer.start()
src/cryodaq/gui/widgets/shift_handover.py:1053:        worker.start()
tests/core/test_zmq_bridge_subscribe.py:85:    pub_thread.start()
tests/core/test_zmq_bridge_subscribe.py:92:    proc.start()
tests/core/test_zmq_bridge_subscribe.py:116:        if proc.is_alive():
tests/core/test_safety_fixes.py:45:    await mgr.start()
tests/core/test_p0_fixes.py:45:    await mgr.start()
tests/core/test_p0_fixes.py:110:    await engine.start()
tests/core/test_p0_fixes.py:147:    await engine.start()
tests/core/test_p0_fixes.py:181:    await engine.start()
tests/core/test_p0_fixes.py:211:    await engine.start()
tests/core/test_p0_fixes.py:243:    await engine.start()
tests/core/test_p0_fixes.py:283:    await engine.start()
tests/core/test_p0_fixes.py:323:    await engine.start()
tests/core/test_p0_fixes.py:361:    await engine.start()
src/cryodaq/drivers/transport/gpib.py:50:    thread.start()
tests/core/test_zmq_subprocess.py:30:    proc.start()
tests/core/test_zmq_subprocess.py:31:    assert proc.is_alive()
tests/core/test_zmq_subprocess.py:35:    assert not proc.is_alive()
tests/core/test_zmq_subprocess.py:39:    """After killing subprocess, is_alive() returns False."""
tests/core/test_zmq_subprocess.py:46:    proc.start()
tests/core/test_zmq_subprocess.py:47:    assert proc.is_alive()
tests/core/test_zmq_subprocess.py:51:    assert not proc.is_alive()
tests/core/test_zmq_subprocess.py:62:    proc.start()
tests/core/test_zmq_subprocess.py:65:    assert not proc.is_alive()
tests/core/test_zmq_subprocess.py:74:    proc2.start()
tests/core/test_zmq_subprocess.py:75:    assert proc2.is_alive()
tests/core/test_zmq_subprocess.py:137:    assert "is_alive()" in source, (
tests/core/test_housekeeping.py:76:    await sched.start()
tests/core/test_housekeeping.py:109:    await sched.start()
tests/core/test_p1_fixes.py:50:    await mgr.start()
tests/core/test_zmq_bridge_subprocess_threading.py:52:        if proc.is_alive():
tests/core/test_zmq_bridge_subprocess_threading.py:99:    proc.start()
tests/core/test_zmq_bridge_subprocess_threading.py:102:    emitter.start()
tests/core/test_zmq_bridge_subprocess_threading.py:138:    proc.start()
tests/core/test_zmq_bridge_subprocess_threading.py:172:    proc.start()
tests/core/test_zmq_bridge_subprocess_threading.py:207:    proc.start()
tests/core/test_zmq_bridge_subprocess_threading.py:241:    server.start()
tests/core/test_zmq_bridge_subprocess_threading.py:271:    proc.start()
tests/core/test_zmq_bridge_subprocess_threading.py:278:    assert not proc.is_alive(), "bridge subprocess hung during shutdown with in-flight REQ"
tests/core/test_zmq_subprocess_ephemeral.py:116:        thread.start()
tests/core/test_zmq_subprocess_ephemeral.py:248:        thread.start()
tests/core/test_zmq_subprocess_ephemeral.py:327:        thread.start()
tests/core/test_zmq_subprocess_ephemeral.py:456:        thread.start()
src/cryodaq/gui/shell/main_window_v2.py:120:        self._status_timer.start()
src/cryodaq/gui/shell/main_window_v2.py:628:        self._create_exp_worker.start()
src/cryodaq/gui/shell/top_watch_bar.py:121:        self._fast_timer.start()
src/cryodaq/gui/shell/top_watch_bar.py:127:        self._channel_refresh_timer.start()
src/cryodaq/gui/shell/top_watch_bar.py:133:        self._slow_timer.start()
src/cryodaq/gui/shell/top_watch_bar.py:139:        self._stale_timer.start()
src/cryodaq/gui/shell/top_watch_bar.py:404:        self._experiment_worker.start()
src/cryodaq/gui/shell/top_watch_bar.py:504:        self._alarm_worker.start()
src/cryodaq/gui/shell/top_watch_bar.py:642:        self._mode_switch_worker.start()
tests/core/test_interlock.py:61:    await engine.start()
tests/core/test_interlock.py:150:    await engine.start()
tests/core/test_interlock.py:288:    await engine.start()
tests/core/test_interlock.py:436:    await engine.start()
tests/core/test_safety_dual_channel.py:25:    await manager.start()
src/cryodaq/gui/shell/overlays/alarm_panel.py:490:                self._v2_poll_timer.start()
src/cryodaq/gui/shell/overlays/alarm_panel.py:751:        worker.start()
src/cryodaq/gui/shell/overlays/alarm_panel.py:768:        worker.start()
src/cryodaq/gui/shell/overlays/alarm_panel.py:795:        worker.start()
src/cryodaq/gui/shell/overlays/calibration_panel.py:464:        worker.start()
src/cryodaq/gui/shell/overlays/calibration_panel.py:479:        worker.start()
src/cryodaq/gui/shell/overlays/calibration_panel.py:872:        worker.start()
src/cryodaq/gui/shell/overlays/calibration_panel.py:915:        worker.start()
src/cryodaq/gui/shell/overlays/calibration_panel.py:1069:        worker.start()
src/cryodaq/gui/shell/overlays/calibration_panel.py:1130:        worker.start()
src/cryodaq/gui/shell/overlays/calibration_panel.py:1198:            worker.start()
src/cryodaq/gui/shell/overlays/calibration_panel.py:1222:        lookup_worker.start()
src/cryodaq/gui/shell/overlays/calibration_panel.py:1244:        worker.start()
src/cryodaq/gui/shell/overlays/calibration_panel.py:1283:            self._mode_timer.start()
src/cryodaq/gui/shell/overlays/calibration_panel.py:1325:        self._banner_timer.start()
tests/core/test_safety_manager.py:33:    await mgr.start()
tests/core/test_safety_manager.py:253:    await mgr.start()
tests/core/test_safety_manager.py:280:    await mgr.start()
tests/drivers/test_visa_executors.py:114:            t.start()
src/cryodaq/gui/shell/overlays/keithley_panel.py:588:        self._p_debounce.start()
src/cryodaq/gui/shell/overlays/keithley_panel.py:593:        self._limits_debounce.start()

exec
/opt/homebrew/bin/bash -lc "git show experiment/iv7-ipc-transport:src/cryodaq/launcher.py | nl -ba | sed -n '1,220p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	"""Единая точка входа CryoDAQ для оператора.
     2	
     3	Запуск:
     4	    cryodaq                     # через entry point
     5	    pythonw -m cryodaq.launcher # без окна терминала
     6	
     7	Автоматически запускает engine как подпроцесс, показывает GUI,
     8	управляет жизненным циклом системы. Оператору достаточно
     9	дважды кликнуть по ярлыку на рабочем столе.
    10	"""
    11	
    12	from __future__ import annotations
    13	
    14	import asyncio
    15	import logging
    16	import logging.handlers
    17	import os
    18	import subprocess
    19	import sys
    20	import threading
    21	import time
    22	import webbrowser
    23	from pathlib import Path
    24	from typing import IO
    25	
    26	# Windows: pyzmq требует SelectorEventLoop
    27	if sys.platform == "win32":
    28	    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    29	
    30	from PySide6.QtCore import Qt, QTimer, Signal, Slot
    31	from PySide6.QtGui import QAction, QActionGroup, QColor, QFont, QIcon, QPainter, QPixmap
    32	from PySide6.QtWidgets import (
    33	    QApplication,
    34	    QHBoxLayout,
    35	    QLabel,
    36	    QMainWindow,
    37	    QMenu,
    38	    QMessageBox,
    39	    QPushButton,
    40	    QSystemTrayIcon,
    41	    QVBoxLayout,
    42	    QWidget,
    43	)
    44	
    45	from cryodaq.core.zmq_transport import DEFAULT_CMD_ADDR, DEFAULT_PUB_ADDR, ipc_path, tcp_host_port
    46	from cryodaq.drivers.base import Reading
    47	from cryodaq.gui.shell.main_window_v2 import MainWindowV2 as MainWindow
    48	from cryodaq.gui.zmq_client import ZmqBridge, ZmqCommandWorker, set_bridge
    49	from cryodaq.instance_lock import release_lock, try_acquire_lock
    50	
    51	logger = logging.getLogger("cryodaq.launcher")
    52	
    53	_WEB_PORT = 8080
    54	
    55	# Settings → Тема menu: curated display order. Dark group first, then
    56	# a visual separator, then light group. Packs not listed here fall
    57	# through to a trailing alphabetical extras block — keeps the menu
    58	# forward-compatible with locally-dropped dev packs without a code
    59	# edit. See docs/design-system/HANDOFF_THEMES_V2.md for the rationale.
    60	#
    61	# Classification is empirical (BACKGROUND luminance > 0.5 → light) —
    62	# the handoff doc groups warm_stone / ochre_bloom / taupe_quiet /
    63	# rose_dusk as "light" but their BG hexes are all dark. Only
    64	# gost / xcode / braun are actual light substrates.
    65	_THEME_DISPLAY_ORDER: tuple[str, ...] = (
    66	    # Dark
    67	    "default_cool",
    68	    "warm_stone",
    69	    "anthropic_mono",
    70	    "ochre_bloom",
    71	    "taupe_quiet",
    72	    "rose_dusk",
    73	    "signal",
    74	    "instrument",
    75	    "amber",
    76	    # Light (ADR 001 shifted-L STATUS set)
    77	    "gost",
    78	    "xcode",
    79	    "braun",
    80	)
    81	_LIGHT_THEME_IDS: frozenset[str] = frozenset({"gost", "xcode", "braun"})
    82	
    83	# Флаги создания процесса без окна (Windows)
    84	_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
    85	_ENGINE_STDERR_LOG_NAME = "engine.stderr.log"
    86	_ENGINE_STDERR_MAX_BYTES = 50 * 1024 * 1024
    87	_ENGINE_STDERR_BACKUP_COUNT = 3
    88	_ENGINE_STDERR_LOGGER_NAME = "cryodaq.launcher.engine_stderr"
    89	
    90	
    91	def _create_engine_stderr_logger() -> tuple[logging.Logger, logging.Handler, Path]:
    92	    """Build a dedicated rotating logger for forwarded engine stderr lines."""
    93	    from cryodaq.paths import get_logs_dir
    94	
    95	    log_path = get_logs_dir() / _ENGINE_STDERR_LOG_NAME
    96	    stderr_logger = logging.getLogger(_ENGINE_STDERR_LOGGER_NAME)
    97	    # Explicitly close and detach any handlers from a prior _start_engine() call
    98	    # so the previous RotatingFileHandler releases its file lock. Plain
    99	    # `handlers = []` relies on GC and breaks on Windows where the file stays
   100	    # locked, blocking rotation across engine restarts.
   101	    for prior in list(stderr_logger.handlers):
   102	        try:
   103	            prior.close()
   104	        except Exception:
   105	            pass
   106	        stderr_logger.removeHandler(prior)
   107	    stderr_logger.setLevel(logging.ERROR)
   108	    stderr_logger.propagate = False
   109	
   110	    handler = logging.handlers.RotatingFileHandler(
   111	        log_path,
   112	        maxBytes=_ENGINE_STDERR_MAX_BYTES,
   113	        backupCount=_ENGINE_STDERR_BACKUP_COUNT,
   114	        encoding="utf-8",
   115	        delay=True,
   116	    )
   117	    handler.setFormatter(
   118	        logging.Formatter(
   119	            fmt="%(asctime)s │ %(message)s",
   120	            datefmt="%Y-%m-%d %H:%M:%S",
   121	        )
   122	    )
   123	    stderr_logger.addHandler(handler)
   124	    return stderr_logger, handler, log_path
   125	
   126	
   127	def _pump_engine_stderr(pipe: IO[bytes], stderr_logger: logging.Logger) -> None:
   128	    """Forward engine stderr bytes into the rotating launcher-managed log."""
   129	    try:
   130	        for raw_line in iter(pipe.readline, b""):
   131	            text = raw_line.decode("utf-8", errors="replace").rstrip()
   132	            if text:
   133	                stderr_logger.error(text)
   134	    finally:
   135	        try:
   136	            pipe.close()
   137	        except Exception:
   138	            pass
   139	
   140	
   141	def _make_icon(color: str) -> QIcon:
   142	    """Создать иконку-кружок указанного цвета (16×16)."""
   143	    pix = QPixmap(16, 16)
   144	    pix.fill(QColor(0, 0, 0, 0))
   145	    painter = QPainter(pix)
   146	    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
   147	    painter.setBrush(QColor(color))
   148	    painter.setPen(Qt.PenStyle.NoPen)
   149	    painter.drawEllipse(2, 2, 12, 12)
   150	    painter.end()
   151	    return QIcon(pix)
   152	
   153	
   154	def _transport_endpoint_present() -> bool:
   155	    """Check if any configured engine transport endpoint is accepting connections."""
   156	    import socket
   157	
   158	    for addr in (DEFAULT_PUB_ADDR, DEFAULT_CMD_ADDR):
   159	        ipc = ipc_path(addr)
   160	        if ipc is not None:
   161	            if not ipc.exists() or not hasattr(socket, "AF_UNIX"):
   162	                continue
   163	            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
   164	            try:
   165	                probe.settimeout(1.0)
   166	                if probe.connect_ex(str(ipc)) == 0:
   167	                    return True
   168	            except OSError:
   169	                pass
   170	            finally:
   171	                probe.close()
   172	            continue
   173	
   174	        host_port = tcp_host_port(addr)
   175	        if host_port is None:
   176	            continue
   177	        host, port = host_port
   178	        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
   179	        try:
   180	            probe.settimeout(1.0)
   181	            if probe.connect_ex((host, port)) == 0:
   182	                return True
   183	        except OSError:
   184	            pass
   185	        finally:
   186	            probe.close()
   187	    return False
   188	
   189	
   190	def _ping_engine() -> bool:
   191	    """Check if a CryoDAQ engine is actually running on the command endpoint."""
   192	    try:
   193	        import json
   194	
   195	        import zmq
   196	
   197	        ctx = zmq.Context()
   198	        sock = ctx.socket(zmq.REQ)
   199	        sock.setsockopt(zmq.RCVTIMEO, 2000)
   200	        sock.setsockopt(zmq.SNDTIMEO, 2000)
   201	        sock.setsockopt(zmq.LINGER, 0)
   202	        sock.connect(DEFAULT_CMD_ADDR)
   203	        sock.send_string(json.dumps({"cmd": "safety_status"}))
   204	        reply = json.loads(sock.recv_string())
   205	        sock.close()
   206	        ctx.term()
   207	        return reply.get("ok", False)
   208	    except Exception:
   209	        return False
   210	
   211	
   212	class LauncherWindow(QMainWindow):
   213	    """Главное окно лаунчера — встраивает MainWindow и управляет engine."""
   214	
   215	    _reading_received = Signal(object)
   216	
   217	    def __init__(
   218	        self,
   219	        app: QApplication,
   220	        *,

exec
/opt/homebrew/bin/bash -lc 'ls -ld artifacts/consultations/2026-04-24-overnight/RESPONSES || true' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
drwxr-xr-x@ 12 vladimir  staff  384 Apr 24 01:15 artifacts/consultations/2026-04-24-overnight/RESPONSES

codex
I’ve got enough to make the call. I’m writing a compact consultation response now, with line references against the combined IV.7 branch where the cited files exist.
2026-04-23T22:18:48.852251Z ERROR codex_core::tools::router: error=patch rejected: writing is blocked by read-only sandbox; rejected by user approval settings
codex
I could not write `artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-01-r123-pick.response.md`: the session is in a read-only filesystem sandbox, and `apply_patch` was rejected. Here is the exact response content:

```markdown
Model: gpt-5.5 / Reasoning effort: high
PICK: R1

1. R1 has the smallest practical regression surface. The failing code is tool-local: `_validate_bridge_startup()` does one `is_alive()` check and one `send_command({"cmd": "safety_status"})`, then aborts on any non-OK reply (`tools/diag_zmq_b1_capture.py:71-76`), and `main()` calls it before capture (`tools/diag_zmq_b1_capture.py:118-126`). Change only that probe.

2. At the libzmq level, R1 is safe because each attempt is isolated. The bridge creates a fresh REQ socket per command (`src/cryodaq/core/zmq_subprocess.py:175-198`), sends/receives once (`src/cryodaq/core/zmq_subprocess.py:208-214`), converts `zmq.ZMQError` into a structured non-OK reply (`src/cryodaq/core/zmq_subprocess.py:215-225`), and closes with `linger=0` (`src/cryodaq/core/zmq_subprocess.py:228-229`). A failed startup REQ cannot poison the next attempt.

3. The race is expected: REQ `connect(cmd_addr)` (`src/cryodaq/core/zmq_subprocess.py:197`) is not a readiness barrier for the engine REP. IV.7 prepares the ipc path and binds REP (`src/cryodaq/core/zmq_bridge.py:530-542`), then schedules the serve task (`src/cryodaq/core/zmq_bridge.py:543-545`). Unix defaults are ipc socket files (`src/cryodaq/core/zmq_transport.py:11-17`), with cleanup before bind (`src/cryodaq/core/zmq_transport.py:48-65`).

4. R2 is higher risk because it changes `ZmqBridge.start()` from “spawn subprocess/start reply consumer/return” (`src/cryodaq/gui/zmq_client.py:96-138`) into “engine command plane is ready.” That affects launcher restart paths (`src/cryodaq/launcher.py:251-259`, `src/cryodaq/launcher.py:486-488`, `src/cryodaq/launcher.py:903-908`) and can block behind the 35 s command envelope (`src/cryodaq/gui/zmq_client.py:31`, `src/cryodaq/gui/zmq_client.py:225-229`).

5. R3 has least code churn but regresses b2b4fb5’s purpose: it removes the explicit subprocess-spawn guard (`tools/diag_zmq_b1_capture.py:71-73`) and lets spawn failures surface as downstream non-OK samples/timeouts.

6. R1 implementation: keep the single `bridge.is_alive()` guard, then retry `safety_status` inside `_validate_bridge_startup()` (`tools/diag_zmq_b1_capture.py:71-76`) with bounded attempts/backoff. Any OK reply passes; final failure raises using the last reply.

7. Fourth option: R4-short-timeout-probe. Add probe-specific timeout plumbing in `src/cryodaq/gui/zmq_client.py:213-229`, `src/cryodaq/core/zmq_subprocess.py:175-198`, and `tools/diag_zmq_b1_capture.py:71-76`. It would make wall-clock bounds stricter, but touches shared command plumbing, so I would not pick it for this repair.

Test cases:

1. Fake bridge: `is_alive() == False`; `_validate_bridge_startup()` raises subprocess-start failure without calling `send_command()`.

2. Fake bridge alive; replies are non-OK, non-OK, then `{"ok": true}`. Validation succeeds after three attempts with fake sleep.

3. Fake bridge alive; all attempts non-OK. Validation raises final `Bridge startup probe failed: ...` and elapsed fake sleep is bounded.

4. Unix ipc integration: fresh mock engine using `ipc:///tmp/cryodaq-pub.sock` and `ipc:///tmp/cryodaq-cmd.sock`; launch capture immediately in a loop, e.g. 50 short runs. Expected: no cmd #0 abort; early samples have `bridge_reply.ok == true` (`docs/decisions/2026-04-24-b2b4fb5-investigation.md:13-22`, `docs/decisions/2026-04-24-b2b4fb5-investigation.md:126-135`).

5. TCP fallback integration: force `tcp://127.0.0.1:5555` and `tcp://127.0.0.1:5556`; run the same immediate-start loop. Expected: all startup probes pass.

6. Delayed REP harness on both transports: start bridge immediately, bind a minimal REP after 300-800 ms. Expected: early attempts may fail, later attempt succeeds, capture proceeds.

Residual risks:

1. R1 does not address B1 idle-death around ~80 s (`docs/decisions/2026-04-24-b2b4fb5-investigation.md:83-107`).

2. R1 does not make `ZmqBridge.start()` a general readiness API; it remains subprocess spawn only (`src/cryodaq/gui/zmq_client.py:96-138`).

3. R1 does not strictly bound wall-clock time if `send_command()` waits 35 s (`src/cryodaq/gui/zmq_client.py:31`, `src/cryodaq/core/zmq_subprocess.py:195-196`). Use R4 if this appears in practice.

4. R1 does not fix stale/live ipc path edge cases in IV.7 cleanup/bind (`src/cryodaq/core/zmq_transport.py:48-65`).

5. R1 does not address subprocess crashes after the startup probe passes; existing `is_alive()`, heartbeat, and command timeout watchdogs still carry that (`src/cryodaq/gui/zmq_client.py:140-207`).
```
tokens used
102 547
I could not write `artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-01-r123-pick.response.md`: the session is in a read-only filesystem sandbox, and `apply_patch` was rejected. Here is the exact response content:

```markdown
Model: gpt-5.5 / Reasoning effort: high
PICK: R1

1. R1 has the smallest practical regression surface. The failing code is tool-local: `_validate_bridge_startup()` does one `is_alive()` check and one `send_command({"cmd": "safety_status"})`, then aborts on any non-OK reply (`tools/diag_zmq_b1_capture.py:71-76`), and `main()` calls it before capture (`tools/diag_zmq_b1_capture.py:118-126`). Change only that probe.

2. At the libzmq level, R1 is safe because each attempt is isolated. The bridge creates a fresh REQ socket per command (`src/cryodaq/core/zmq_subprocess.py:175-198`), sends/receives once (`src/cryodaq/core/zmq_subprocess.py:208-214`), converts `zmq.ZMQError` into a structured non-OK reply (`src/cryodaq/core/zmq_subprocess.py:215-225`), and closes with `linger=0` (`src/cryodaq/core/zmq_subprocess.py:228-229`). A failed startup REQ cannot poison the next attempt.

3. The race is expected: REQ `connect(cmd_addr)` (`src/cryodaq/core/zmq_subprocess.py:197`) is not a readiness barrier for the engine REP. IV.7 prepares the ipc path and binds REP (`src/cryodaq/core/zmq_bridge.py:530-542`), then schedules the serve task (`src/cryodaq/core/zmq_bridge.py:543-545`). Unix defaults are ipc socket files (`src/cryodaq/core/zmq_transport.py:11-17`), with cleanup before bind (`src/cryodaq/core/zmq_transport.py:48-65`).

4. R2 is higher risk because it changes `ZmqBridge.start()` from “spawn subprocess/start reply consumer/return” (`src/cryodaq/gui/zmq_client.py:96-138`) into “engine command plane is ready.” That affects launcher restart paths (`src/cryodaq/launcher.py:251-259`, `src/cryodaq/launcher.py:486-488`, `src/cryodaq/launcher.py:903-908`) and can block behind the 35 s command envelope (`src/cryodaq/gui/zmq_client.py:31`, `src/cryodaq/gui/zmq_client.py:225-229`).

5. R3 has least code churn but regresses b2b4fb5’s purpose: it removes the explicit subprocess-spawn guard (`tools/diag_zmq_b1_capture.py:71-73`) and lets spawn failures surface as downstream non-OK samples/timeouts.

6. R1 implementation: keep the single `bridge.is_alive()` guard, then retry `safety_status` inside `_validate_bridge_startup()` (`tools/diag_zmq_b1_capture.py:71-76`) with bounded attempts/backoff. Any OK reply passes; final failure raises using the last reply.

7. Fourth option: R4-short-timeout-probe. Add probe-specific timeout plumbing in `src/cryodaq/gui/zmq_client.py:213-229`, `src/cryodaq/core/zmq_subprocess.py:175-198`, and `tools/diag_zmq_b1_capture.py:71-76`. It would make wall-clock bounds stricter, but touches shared command plumbing, so I would not pick it for this repair.

Test cases:

1. Fake bridge: `is_alive() == False`; `_validate_bridge_startup()` raises subprocess-start failure without calling `send_command()`.

2. Fake bridge alive; replies are non-OK, non-OK, then `{"ok": true}`. Validation succeeds after three attempts with fake sleep.

3. Fake bridge alive; all attempts non-OK. Validation raises final `Bridge startup probe failed: ...` and elapsed fake sleep is bounded.

4. Unix ipc integration: fresh mock engine using `ipc:///tmp/cryodaq-pub.sock` and `ipc:///tmp/cryodaq-cmd.sock`; launch capture immediately in a loop, e.g. 50 short runs. Expected: no cmd #0 abort; early samples have `bridge_reply.ok == true` (`docs/decisions/2026-04-24-b2b4fb5-investigation.md:13-22`, `docs/decisions/2026-04-24-b2b4fb5-investigation.md:126-135`).

5. TCP fallback integration: force `tcp://127.0.0.1:5555` and `tcp://127.0.0.1:5556`; run the same immediate-start loop. Expected: all startup probes pass.

6. Delayed REP harness on both transports: start bridge immediately, bind a minimal REP after 300-800 ms. Expected: early attempts may fail, later attempt succeeds, capture proceeds.

Residual risks:

1. R1 does not address B1 idle-death around ~80 s (`docs/decisions/2026-04-24-b2b4fb5-investigation.md:83-107`).

2. R1 does not make `ZmqBridge.start()` a general readiness API; it remains subprocess spawn only (`src/cryodaq/gui/zmq_client.py:96-138`).

3. R1 does not strictly bound wall-clock time if `send_command()` waits 35 s (`src/cryodaq/gui/zmq_client.py:31`, `src/cryodaq/core/zmq_subprocess.py:195-196`). Use R4 if this appears in practice.

4. R1 does not fix stale/live ipc path edge cases in IV.7 cleanup/bind (`src/cryodaq/core/zmq_transport.py:48-65`).

5. R1 does not address subprocess crashes after the startup probe passes; existing `is_alive()`, heartbeat, and command timeout watchdogs still carry that (`src/cryodaq/gui/zmq_client.py:140-207`).
```
