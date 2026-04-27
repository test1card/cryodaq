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
session id: 019dbf3e-2541-7ef3-b726-f798cd6111b4
--------
user
Model: gpt-5.5
Reasoning effort: high

# Adversarial diff review — Q4 post-merge equivalence check

## Mission

Master now carries the R1 repair for the `b2b4fb5` startup-race
(merged via merge-commit `89b4db1` on 2026-04-24). The R1 implementation
was adopted in place of cherry-picking `b2b4fb5` itself, so master
has **never** carried the original single-shot probe. Architect Q4
wants confirmation that:

**Is master post-R1 semantically equivalent to "b2b4fb5 intent
(single-shot startup probe with is_alive + safety_status check)
PLUS the intentional bounded-backoff retry improvement" — and
nothing else?**

Specifically: does R1 behave like `b2b4fb5` would have, when the
retry window is exhausted? And when called against a healthy
bridge on the first attempt, does the fast path match b2b4fb5's
fast path exactly? Any behavior drift outside the intended retry
loop is a finding.

## Evidence files (read before answering)

Three specific comparisons, all inspectable via `git show`:

1. **R1 implementation on master** — `tools/diag_zmq_b1_capture.py`
   at `89b4db1` (or HEAD). Specifically:
   - `_validate_bridge_startup()` function
   - `main()` call site (error handling path)
   - Module-level constants `_STARTUP_PROBE_ATTEMPTS`,
     `_STARTUP_PROBE_BACKOFF_S`
   - New `logging` import + `log` module attribute

2. **b2b4fb5 reference** — original single-shot probe on
   `codex/safe-merge-b1-truth-recovery`. Quickest access:
   `git show b2b4fb5 -- tools/diag_zmq_b1_capture.py`
   (only ~13 lines of additions in that commit).

3. **Pre-D1 master baseline** — `tools/diag_zmq_b1_capture.py`
   at parent `680240a` (or any ancestor before the merge). At
   this point the tool had no `_validate_bridge_startup` at all
   — compare for dead-code or side-effect introduction.

## Specific questions

1. **Fast-path equivalence.** When the first `send_command` reply
   is `{"ok": True, ...}`:
   - Does R1 do exactly what b2b4fb5 does?
   - Same side effects? Same return value? Same log output?
   - Verify `reply and reply.get("ok") is True` (R1) vs
     `not reply or reply.get("ok") is not True` (b2b4fb5) — these
     are logically equivalent for truthy-dict/True/False inputs,
     but check corner cases (None, empty dict, ok=None,
     ok="True" string, ok=1).

2. **Exhausted-window equivalence.** When all attempts produce
   non-OK replies, R1 eventually raises. Compare the exception
   type, message format, and message content to b2b4fb5's raise.
   Are they identical from a downstream-grep perspective?

3. **is_alive short-circuit.** Both paths do a single `is_alive()`
   check. Is the timing, error message, and raised type identical?

4. **main() integration.** Stderr output ("B1 capture aborted:
   ..."), exit code (1), bridge.shutdown() called on failure,
   output file not created. All identical to b2b4fb5?

5. **Drift scan — list anything R1 changes that is NOT in the
   b2b4fb5 + retry spec:**
   - `import logging` (new)
   - `log = logging.getLogger(__name__)` (new)
   - two module-level constants (new)
   - `log.debug(...)` inside the retry loop (new)
   - `sleep_fn=time.sleep` keyword arg (test injectability, new)
   - docstring on `_validate_bridge_startup` (new)
   - anything else?
   For each: is it load-bearing for R1 semantics, or inert? Does
   any of it introduce a hidden behavior change (e.g., a log call
   that evaluates arguments with side effects)?

6. **Subprocess / ZMQ plumbing.** The R1 function calls
   `bridge.send_command({"cmd": "safety_status"})` in a loop. Does
   the ZmqBridge behavior on a non-OK reply leak state across
   iterations (per-call ephemeral REQ socket per IV.6, per-call
   correlation id, no shared REQ state)? Anything in the retry
   loop that could compound across attempts?

## Output format

- First line verbatim: `Model: gpt-5.5 / Reasoning effort: high`
- Verdict header: `EQUIVALENT + improvement only`,
  `DRIFT: <short-label>` (with severity), or `PARTIALLY EQUIVALENT`
  (explain)
- For each of the 6 questions above: numbered answer with file:line
  refs where concrete
- Findings grouped by severity: CRITICAL / HIGH / MEDIUM / LOW /
  ACCEPTABLE (expected from R1 design)
- Max 2000 words. Terse is better than verbose.

## Scope fence

- Do NOT evaluate whether R1 was the right choice vs R2 / R3 —
  that's already settled (Stream A synthesis 2026-04-24 morning).
- Do NOT evaluate B1 idle-death (separate H4 investigation).
- Do NOT propose new test cases beyond what's already landed
  (cases 4-6 are deferred, architect knows).
- Do NOT comment on unrelated style / naming / import ordering
  unless it's load-bearing for equivalence.
- Do NOT comment on the two commits that landed on master
  AFTER the branch point but BEFORE the merge (ledger + handoff,
  `a82d6bf` + `680240a`) — they touch only docs/ and artifacts/.

## Response file

Write to: `artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-06-q4-equivalence.response.md`

Note: write-via-apply_patch will be blocked by read-only sandbox;
CC will capture stdout via redirect. Produce the response as you
normally would — print the final content as the last section so
it is captured by stdout.

codex
I’ll inspect the requested commits and line-level diffs directly from git, then produce the response content to stdout since the sandbox is read-only.
exec
/opt/homebrew/bin/bash -lc "sed -n '1,220p' /Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/f09cfd210e21e96a0031f4d247be5f2e416d23b1/skills/using-superpowers/SKILL.md" in /Users/vladimir/Projects/cryodaq
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

codex
Using `superpowers:using-superpowers` for skill routing; this is a code review/equivalence task, so I’ll keep the workflow evidence-driven and limited to the requested refs.
exec
/opt/homebrew/bin/bash -lc "sed -n '1,220p' /Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/f09cfd210e21e96a0031f4d247be5f2e416d23b1/skills/verification-before-completion/SKILL.md" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
---
name: verification-before-completion
description: Use when about to claim work is complete, fixed, or passing, before committing or creating PRs - requires running verification commands and confirming output before making any success claims; evidence before assertions always
---

# Verification Before Completion

## Overview

Claiming work is complete without verification is dishonesty, not efficiency.

**Core principle:** Evidence before claims, always.

**Violating the letter of this rule is violating the spirit of this rule.**

## The Iron Law

```
NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE
```

If you haven't run the verification command in this message, you cannot claim it passes.

## The Gate Function

```
BEFORE claiming any status or expressing satisfaction:

1. IDENTIFY: What command proves this claim?
2. RUN: Execute the FULL command (fresh, complete)
3. READ: Full output, check exit code, count failures
4. VERIFY: Does output confirm the claim?
   - If NO: State actual status with evidence
   - If YES: State claim WITH evidence
5. ONLY THEN: Make the claim

Skip any step = lying, not verifying
```

## Common Failures

| Claim | Requires | Not Sufficient |
|-------|----------|----------------|
| Tests pass | Test command output: 0 failures | Previous run, "should pass" |
| Linter clean | Linter output: 0 errors | Partial check, extrapolation |
| Build succeeds | Build command: exit 0 | Linter passing, logs look good |
| Bug fixed | Test original symptom: passes | Code changed, assumed fixed |
| Regression test works | Red-green cycle verified | Test passes once |
| Agent completed | VCS diff shows changes | Agent reports "success" |
| Requirements met | Line-by-line checklist | Tests passing |

## Red Flags - STOP

- Using "should", "probably", "seems to"
- Expressing satisfaction before verification ("Great!", "Perfect!", "Done!", etc.)
- About to commit/push/PR without verification
- Trusting agent success reports
- Relying on partial verification
- Thinking "just this once"
- Tired and wanting work over
- **ANY wording implying success without having run verification**

## Rationalization Prevention

| Excuse | Reality |
|--------|---------|
| "Should work now" | RUN the verification |
| "I'm confident" | Confidence ≠ evidence |
| "Just this once" | No exceptions |
| "Linter passed" | Linter ≠ compiler |
| "Agent said success" | Verify independently |
| "I'm tired" | Exhaustion ≠ excuse |
| "Partial check is enough" | Partial proves nothing |
| "Different words so rule doesn't apply" | Spirit over letter |

## Key Patterns

**Tests:**
```
✅ [Run test command] [See: 34/34 pass] "All tests pass"
❌ "Should pass now" / "Looks correct"
```

**Regression tests (TDD Red-Green):**
```
✅ Write → Run (pass) → Revert fix → Run (MUST FAIL) → Restore → Run (pass)
❌ "I've written a regression test" (without red-green verification)
```

**Build:**
```
✅ [Run build] [See: exit 0] "Build passes"
❌ "Linter passed" (linter doesn't check compilation)
```

**Requirements:**
```
✅ Re-read plan → Create checklist → Verify each → Report gaps or completion
❌ "Tests pass, phase complete"
```

**Agent delegation:**
```
✅ Agent reports success → Check VCS diff → Verify changes → Report actual state
❌ Trust agent report
```

## Why This Matters

From 24 failure memories:
- your human partner said "I don't believe you" - trust broken
- Undefined functions shipped - would crash
- Missing requirements shipped - incomplete features
- Time wasted on false completion → redirect → rework
- Violates: "Honesty is a core value. If you lie, you'll be replaced."

## When To Apply

**ALWAYS before:**
- ANY variation of success/completion claims
- ANY expression of satisfaction
- ANY positive statement about work state
- Committing, PR creation, task completion
- Moving to next task
- Delegating to agents

**Rule applies to:**
- Exact phrases
- Paraphrases and synonyms
- Implications of success
- ANY communication suggesting completion/correctness

## The Bottom Line

**No shortcuts for verification.**

Run the command. Read the output. THEN claim the result.

This is non-negotiable.

exec
/opt/homebrew/bin/bash -lc 'git rev-parse --show-toplevel && git status --short && git rev-parse HEAD && git log --oneline -5' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
/Users/vladimir/Projects/cryodaq
?? artifacts/consultations/2026-04-24-overnight/BRIEFS/codex-06-q4-equivalence.prompt.md
?? artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-06-q4-equivalence.response.md
?? node_modules/
?? package-lock.json
?? package.json
89b4db14d86b89fc547d56b16eed6298d7a16850
89b4db1 merge: D1 R1 repair from feat/b2b4fb5-repair
680240a artifacts: D1 R1 repair review handoff for feat/b2b4fb5-repair
a82d6bf docs: session ledger for 2026-04-24 D4a + D1 execution
c3f4f86 fix(diag): bounded-backoff retry in B1 capture probe (R1 repair for b2b4fb5)
62314be tools: record direct probe timeouts in B1 capture

codex
HEAD is the requested merge commit `89b4db1`. I’m reading the exact function/call-site bodies from HEAD, the `b2b4fb5` patch, and the pre-D1 baseline now, including line numbers for the final response.
exec
/opt/homebrew/bin/bash -lc "git show HEAD:tools/diag_zmq_b1_capture.py | nl -ba | sed -n '1,260p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	from __future__ import annotations
     2	
     3	import argparse
     4	import json
     5	import logging
     6	import sys
     7	import time
     8	from datetime import UTC, datetime
     9	from pathlib import Path
    10	
    11	if __package__ in {None, ""}:
    12	    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    13	
    14	from cryodaq.gui.zmq_client import ZmqBridge
    15	from tools._b1_diagnostics import bridge_snapshot, direct_engine_probe
    16	from tools._zmq_helpers import DEFAULT_CMD_ADDR
    17	
    18	log = logging.getLogger(__name__)
    19	
    20	# Startup probe tuning. Each attempt sends one `safety_status` command
    21	# through the bridge; any OK reply passes. Total wall-clock bound is
    22	# dominated by the bridge command timeout on each attempt, not by the
    23	# inter-attempt sleeps.
    24	_STARTUP_PROBE_ATTEMPTS = 5
    25	_STARTUP_PROBE_BACKOFF_S = 0.2
    26	
    27	
    28	def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    29	    parser = argparse.ArgumentParser(
    30	        description=(
    31	            "Canonical B1 capture against current master. Records bridge-side "
    32	            "and direct-engine command health into JSONL."
    33	        )
    34	    )
    35	    parser.add_argument("--output", type=Path, required=True, help="JSONL artifact path.")
    36	    parser.add_argument("--duration", type=float, default=180.0, help="Capture length in seconds.")
    37	    parser.add_argument("--interval", type=float, default=1.0, help="Sample interval in seconds.")
    38	    parser.add_argument("--address", default=DEFAULT_CMD_ADDR, help="Direct engine REQ address.")
    39	    parser.add_argument(
    40	        "--direct-timeout",
    41	        type=float,
    42	        default=5.0,
    43	        help="Seconds to wait for the direct engine probe.",
    44	    )
    45	    parser.add_argument(
    46	        "--skip-direct-probe",
    47	        action="store_true",
    48	        help="Only record bridge-side command health.",
    49	    )
    50	    return parser.parse_args(argv)
    51	
    52	
    53	def _sample_once(
    54	    bridge: ZmqBridge,
    55	    *,
    56	    address: str,
    57	    direct_timeout_s: float,
    58	    skip_direct_probe: bool,
    59	) -> dict:
    60	    bridge.poll_readings()
    61	    sample = bridge_snapshot(bridge)
    62	    sample["ts_utc"] = datetime.now(UTC).isoformat()
    63	    sample["bridge_reply"] = bridge.send_command({"cmd": "safety_status"})
    64	    if skip_direct_probe:
    65	        sample["direct_reply"] = None
    66	    else:
    67	        try:
    68	            sample["direct_reply"] = direct_engine_probe(
    69	                address=address,
    70	                timeout_s=direct_timeout_s,
    71	            )
    72	        except TimeoutError as exc:
    73	            sample["direct_reply"] = {
    74	                "ok": False,
    75	                "error": str(exc),
    76	                "exception_type": type(exc).__name__,
    77	            }
    78	    return sample
    79	
    80	
    81	def _validate_bridge_startup(
    82	    bridge: ZmqBridge,
    83	    *,
    84	    attempts: int = _STARTUP_PROBE_ATTEMPTS,
    85	    backoff_s: float = _STARTUP_PROBE_BACKOFF_S,
    86	    sleep_fn=time.sleep,
    87	) -> None:
    88	    """Verify bridge subprocess is alive and engine REP is answering.
    89	
    90	    R1 repair for the b2b4fb5 startup race: instead of a single-shot
    91	    ``safety_status`` probe (which aborted the capture at cmd #0 when
    92	    the engine's ipc:// REP socket had not finished binding), retry
    93	    the probe up to ``attempts`` times with ``backoff_s`` between
    94	    attempts. Any OK reply passes. See
    95	    ``docs/decisions/2026-04-24-b2b4fb5-investigation.md`` for the
    96	    empirical background.
    97	
    98	    Subprocess-spawn failure is still a single-shot check — no point
    99	    retrying a dead subprocess.
   100	    """
   101	    if not bridge.is_alive():
   102	        raise RuntimeError("ZMQ bridge subprocess failed to start")
   103	
   104	    last_reply: dict | None = None
   105	    for attempt in range(attempts):
   106	        reply = bridge.send_command({"cmd": "safety_status"})
   107	        if reply and reply.get("ok") is True:
   108	            return
   109	        last_reply = reply
   110	        if attempt < attempts - 1:
   111	            log.debug(
   112	                "bridge startup probe attempt %d/%d non-OK, retrying in %.2fs: %r",
   113	                attempt + 1,
   114	                attempts,
   115	                backoff_s,
   116	                reply,
   117	            )
   118	            sleep_fn(backoff_s)
   119	
   120	    raise RuntimeError(f"Bridge startup probe failed: {last_reply!r}")
   121	
   122	
   123	def run_capture(
   124	    bridge: ZmqBridge,
   125	    *,
   126	    duration_s: float,
   127	    interval_s: float,
   128	    output_path: Path,
   129	    address: str,
   130	    direct_timeout_s: float,
   131	    skip_direct_probe: bool,
   132	    now_fn=time.monotonic,
   133	    sleep_fn=time.sleep,
   134	) -> int:
   135	    output_path.parent.mkdir(parents=True, exist_ok=True)
   136	    deadline = now_fn() + duration_s
   137	    count = 0
   138	
   139	    with output_path.open("w", encoding="utf-8") as fh:
   140	        while True:
   141	            if now_fn() >= deadline:
   142	                break
   143	            sample = _sample_once(
   144	                bridge,
   145	                address=address,
   146	                direct_timeout_s=direct_timeout_s,
   147	                skip_direct_probe=skip_direct_probe,
   148	            )
   149	            count += 1
   150	            sample["seq"] = count
   151	            fh.write(json.dumps(sample, ensure_ascii=False) + "\n")
   152	            fh.flush()
   153	            if now_fn() >= deadline:
   154	                break
   155	            sleep_fn(interval_s)
   156	
   157	    return count
   158	
   159	
   160	def main(argv: list[str] | None = None) -> int:
   161	    args = _parse_args(argv)
   162	    bridge = ZmqBridge()
   163	    bridge.start()
   164	    time.sleep(1.0)
   165	    try:
   166	        try:
   167	            _validate_bridge_startup(bridge)
   168	        except RuntimeError as exc:
   169	            print(f"B1 capture aborted: {exc}", file=sys.stderr)
   170	            return 1
   171	        samples = run_capture(
   172	            bridge,
   173	            duration_s=args.duration,
   174	            interval_s=args.interval,
   175	            output_path=args.output,
   176	            address=args.address,
   177	            direct_timeout_s=args.direct_timeout,
   178	            skip_direct_probe=args.skip_direct_probe,
   179	        )
   180	    finally:
   181	        bridge.shutdown()
   182	    print(f"Wrote {samples} samples to {args.output}")
   183	    return 0
   184	
   185	
   186	if __name__ == "__main__":
   187	    sys.exit(main())

exec
/opt/homebrew/bin/bash -lc 'git show b2b4fb5 -- tools/diag_zmq_b1_capture.py' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
commit b2b4fb551e577c6bee972b6fc9ebe2a9b64a600a
Author: Vladimir Fomenko <polsovatel111@gmail.com>
Date:   Thu Apr 23 15:10:29 2026 +0300

    fix: harden B1 capture bridge startup validation

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
/opt/homebrew/bin/bash -lc "git show b2b4fb5:tools/diag_zmq_b1_capture.py | nl -ba | sed -n '1,260p'" in /Users/vladimir/Projects/cryodaq
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
/opt/homebrew/bin/bash -lc "git show 680240a:tools/diag_zmq_b1_capture.py | nl -ba | sed -n '1,260p'" in /Users/vladimir/Projects/cryodaq
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
    71	def run_capture(
    72	    bridge: ZmqBridge,
    73	    *,
    74	    duration_s: float,
    75	    interval_s: float,
    76	    output_path: Path,
    77	    address: str,
    78	    direct_timeout_s: float,
    79	    skip_direct_probe: bool,
    80	    now_fn=time.monotonic,
    81	    sleep_fn=time.sleep,
    82	) -> int:
    83	    output_path.parent.mkdir(parents=True, exist_ok=True)
    84	    deadline = now_fn() + duration_s
    85	    count = 0
    86	
    87	    with output_path.open("w", encoding="utf-8") as fh:
    88	        while True:
    89	            if now_fn() >= deadline:
    90	                break
    91	            sample = _sample_once(
    92	                bridge,
    93	                address=address,
    94	                direct_timeout_s=direct_timeout_s,
    95	                skip_direct_probe=skip_direct_probe,
    96	            )
    97	            count += 1
    98	            sample["seq"] = count
    99	            fh.write(json.dumps(sample, ensure_ascii=False) + "\n")
   100	            fh.flush()
   101	            if now_fn() >= deadline:
   102	                break
   103	            sleep_fn(interval_s)
   104	
   105	    return count
   106	
   107	
   108	def main(argv: list[str] | None = None) -> int:
   109	    args = _parse_args(argv)
   110	    bridge = ZmqBridge()
   111	    bridge.start()
   112	    time.sleep(1.0)
   113	    try:
   114	        samples = run_capture(
   115	            bridge,
   116	            duration_s=args.duration,
   117	            interval_s=args.interval,
   118	            output_path=args.output,
   119	            address=args.address,
   120	            direct_timeout_s=args.direct_timeout,
   121	            skip_direct_probe=args.skip_direct_probe,
   122	        )
   123	    finally:
   124	        bridge.shutdown()
   125	    print(f"Wrote {samples} samples to {args.output}")
   126	    return 0
   127	
   128	
   129	if __name__ == "__main__":
   130	    sys.exit(main())

codex
The R1 and b2b4fb5 startup checks align structurally except for the retry loop and its support scaffolding. I’m checking `ZmqBridge.send_command` next to answer the REQ/correlation/state question rather than assuming the plumbing.
exec
/opt/homebrew/bin/bash -lc "nl -ba cryodaq/gui/zmq_client.py | sed -n '1,260p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
nl: cryodaq/gui/zmq_client.py: No such file or directory

exec
/opt/homebrew/bin/bash -lc "rg -n \"class ZmqBridge|def send_command|REQ|correlation|request_id|poller|linger|socket\" cryodaq/gui/zmq_client.py cryodaq -g '*.py'" in /Users/vladimir/Projects/cryodaq
 exited 2 in 0ms:
rg: cryodaq/gui/zmq_client.py: No such file or directory (os error 2)
rg: cryodaq: No such file or directory (os error 2)

codex
The import path is package-relative but the source tree is not at `cryodaq/` from repo root. I’m locating the module path and then I’ll inspect the concrete implementation.
exec
/opt/homebrew/bin/bash -lc "rg --files | rg 'zmq_client\\.py"'$|_zmq_helpers'"\\.py"'$|_b1_diagnostics'"\\.py"'$'"'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
tools/_zmq_helpers.py
tools/_b1_diagnostics.py
src/cryodaq/gui/zmq_client.py
tests/tools/test_b1_diagnostics.py

exec
/opt/homebrew/bin/bash -lc "find . -maxdepth 3 -type d | sed -n '1,120p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
.
./artifacts
./artifacts/consultations
./artifacts/consultations/2026-04-24-overnight
./artifacts/versioning
./artifacts/handoffs
./tools
./tools/__pycache__
./.pytest_cache
./.pytest_cache/v
./.pytest_cache/v/cache
./dist
./dist/CryoDAQ
./dist/CryoDAQ/_internal
./dist/CryoDAQ/config
./dist/CryoDAQ/plugins
./dist/CryoDAQ/logs
./dist/CryoDAQ/data
./config
./config/experiment_templates
./config/themes
./tsp
./plugins
./plugins/__pycache__
./.ruff_cache
./.ruff_cache/0.15.9
./node_modules
./node_modules/.bin
./node_modules/json-schema-traverse
./node_modules/json-schema-traverse/spec
./node_modules/json-schema-traverse/.github
./node_modules/ecc-universal
./node_modules/ecc-universal/.cursor
./node_modules/ecc-universal/.gemini
./node_modules/ecc-universal/.opencode
./node_modules/ecc-universal/.agents
./node_modules/ecc-universal/agents
./node_modules/ecc-universal/schemas
./node_modules/ecc-universal/.codex
./node_modules/ecc-universal/mcp-configs
./node_modules/ecc-universal/hooks
./node_modules/ecc-universal/scripts
./node_modules/ecc-universal/.claude-plugin
./node_modules/ecc-universal/rules
./node_modules/ecc-universal/commands
./node_modules/ecc-universal/skills
./node_modules/ecc-universal/manifests
./node_modules/ecc-universal/.codex-plugin
./node_modules/sql.js
./node_modules/sql.js/dist
./node_modules/sql.js/.devcontainer
./node_modules/fast-uri
./node_modules/fast-uri/benchmark
./node_modules/fast-uri/types
./node_modules/fast-uri/test
./node_modules/fast-uri/.github
./node_modules/fast-uri/lib
./node_modules/@iarna
./node_modules/@iarna/toml
./node_modules/ajv
./node_modules/ajv/dist
./node_modules/ajv/lib
./node_modules/fast-deep-equal
./node_modules/fast-deep-equal/es6
./node_modules/require-from-string
./tests
./tests/reporting
./tests/reporting/__pycache__
./tests/tools
./tests/tools/__pycache__
./tests/drivers
./tests/drivers/__pycache__
./tests/core
./tests/core/__pycache__
./tests/config
./tests/config/__pycache__
./tests/web
./tests/web/__pycache__
./tests/design_system
./tests/design_system/__pycache__
./tests/utils
./tests/utils/__pycache__
./tests/__pycache__
./tests/storage
./tests/storage/__pycache__
./tests/gui
./tests/gui/shell
./tests/gui/utils
./tests/gui/__pycache__
./tests/gui/state
./tests/gui/dashboard
./tests/gui/widgets
./tests/notifications
./tests/notifications/__pycache__
./tests/analytics
./tests/analytics/__pycache__
./.claude
./.claude/hooks
./.claude/commands
./.claude/skills
./.audit-run
./.audit-run/2026-04-20-zero-trust
./.audit-run/2026-04-20-zero-trust/.omc
./docs
./docs/changelog
./docs/changelog/archive
./docs/audits
./docs/audits/2026-04-17
./docs/audits/2026-04-21-agent-swarm
./docs/audits/2026-04-09
./docs/phase-ui-1
./docs/legacy-inventory
./docs/runbooks
./docs/decisions
./docs/design-system
./docs/design-system/adr
./docs/design-system/patterns
./docs/design-system/components
./docs/design-system/governance
./docs/design-system/rules

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/gui/zmq_client.py | sed -n '1,300p'" in /Users/vladimir/Projects/cryodaq
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
   261	        # Stop reply consumer thread
   262	        self._reply_stop.set()
   263	        with self._pending_lock:
   264	            for rid, future in self._pending.items():
   265	                if not future.done():
   266	                    future.set_result({"ok": False, "error": "ZMQ bridge shutting down"})
   267	            self._pending.clear()
   268	        if self._reply_consumer is not None and self._reply_consumer.is_alive():
   269	            self._reply_consumer.join(timeout=3.0)
   270	
   271	        # Stop subprocess
   272	        self._shutdown_event.set()
   273	        if self._process is not None:
   274	            self._process.join(timeout=3)
   275	            if self._process.is_alive():
   276	                logger.warning("ZMQ bridge subprocess did not exit, killing")
   277	                self._process.kill()
   278	                self._process.join(timeout=2)
   279	            # Hardening 2026-04-21: log exit code for B1 diagnostic
   280	            exit_code = self._process.exitcode
   281	            if exit_code is not None:
   282	                logger.info("ZMQ bridge subprocess stopped (exitcode=%s)", exit_code)
   283	            else:
   284	                logger.warning("ZMQ bridge subprocess stopped (exitcode=None after kill)")
   285	            self._process = None
   286	        else:
   287	            logger.info("ZMQ bridge subprocess stopped")
   288	
   289	
   290	def _drain(q: mp.Queue) -> None:
   291	    """Drain a multiprocessing Queue, ignoring errors."""
   292	    while True:
   293	        try:
   294	            q.get_nowait()
   295	        except (queue.Empty, EOFError, OSError):
   296	            break
   297	
   298	
   299	# --- Backwards-compatible API used by keithley_panel and other GUI widgets ---
   300	

exec
/opt/homebrew/bin/bash -lc "rg -n \"class ZmqBridge|def send_command|REQ|correlation|request_id|poller|linger|socket\" src/cryodaq/gui/zmq_client.py src/cryodaq -g '*.py'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
src/cryodaq/gui/zmq_client.py:48:class ZmqBridge:
src/cryodaq/gui/zmq_client.py:85:        # failures where the data plane is still healthy but REQ/REP
src/cryodaq/gui/zmq_client.py:93:        # Hardening 2026-04-21: restart counter for B1 diagnostic correlation
src/cryodaq/gui/zmq_client.py:213:    def send_command(self, cmd: dict) -> dict:
src/cryodaq/gui/zmq_client.py:214:        """Thread-safe command dispatch with Future-per-request correlation."""
src/cryodaq/gui/zmq_client.py:310:def send_command(cmd: dict) -> dict:
src/cryodaq/web/server.py:57:    """Send a command to the engine via ZMQ REQ/REP. Thread-safe per call."""
src/cryodaq/web/server.py:59:    sock = ctx.socket(zmq.REQ)
src/cryodaq/web/server.py:398:    @application.websocket("/ws")
src/cryodaq/web/server.py:399:    async def websocket_endpoint(ws: WebSocket) -> None:
src/cryodaq/gui/_theme_loader.py:30:REQUIRED_TOKENS = frozenset(
src/cryodaq/gui/_theme_loader.py:119:    missing = REQUIRED_TOKENS - set(pack.keys())
src/cryodaq/gui/_theme_loader.py:131:    for token in REQUIRED_TOKENS:
src/cryodaq/launcher.py:157:    import socket
src/cryodaq/launcher.py:161:            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
src/cryodaq/launcher.py:180:        sock = ctx.socket(zmq.REQ)
src/cryodaq/launcher.py:823:        is still releasing its ZMQ sockets.
src/cryodaq/launcher.py:842:        (5556) — the orphaned bridge's mid-flight REQ was never consumed
src/cryodaq/launcher.py:843:        by its dead peer, so every subsequent REQ from the new launcher's
src/cryodaq/launcher.py:848:        # Order matters: shut down the bridge first so no REQ is mid-flight,
src/cryodaq/launcher.py:912:        # a recent REQ/REP timeout indicates the command plane has
src/cryodaq/launcher.py:914:        # REQ / REP connection and recover command path.
src/cryodaq/core/zmq_subprocess.py:3:This process owns ALL ZMQ sockets. If libzmq crashes (signaler.cpp
src/cryodaq/core/zmq_subprocess.py:10:- sub_drain owns the SUB socket, receives readings, emits heartbeats.
src/cryodaq/core/zmq_subprocess.py:12:- cmd_forward owns the REQ socket, sends commands and waits up to 3s
src/cryodaq/core/zmq_subprocess.py:76:        GUI → subprocess: command dicts to send via REQ.
src/cryodaq/core/zmq_subprocess.py:91:        """Own SUB socket; drain readings and emit periodic heartbeats.
src/cryodaq/core/zmq_subprocess.py:100:        sub = ctx.socket(zmq.SUB)
src/cryodaq/core/zmq_subprocess.py:103:        # 2026-04-20 idle-death fix: same keepalive as REQ side to
src/cryodaq/core/zmq_subprocess.py:146:                    # Unexpected socket error — swallow and continue.
src/cryodaq/core/zmq_subprocess.py:155:            sub.close(linger=0)
src/cryodaq/core/zmq_subprocess.py:158:        """Forward GUI commands via a fresh REQ socket per command.
src/cryodaq/core/zmq_subprocess.py:160:        IV.6 B1 fix: each command creates, uses, and closes its own REQ
src/cryodaq/core/zmq_subprocess.py:161:        socket. Shared long-lived REQ accumulated state across commands
src/cryodaq/core/zmq_subprocess.py:164:        deterministic). Ephemeral REQ per command matches ZeroMQ Guide
src/cryodaq/core/zmq_subprocess.py:168:        May block up to 35 s per timed-out REQ. That does not starve
src/cryodaq/core/zmq_subprocess.py:170:        A timed-out REQ emits a structured ``cmd_timeout`` control
src/cryodaq/core/zmq_subprocess.py:175:        def _new_req_socket():
src/cryodaq/core/zmq_subprocess.py:176:            """Build a fresh per-command REQ socket.
src/cryodaq/core/zmq_subprocess.py:178:            IV.6: REQ_RELAXED / REQ_CORRELATE dropped — they were only
src/cryodaq/core/zmq_subprocess.py:179:            useful for stateful recovery on a shared socket, which the
src/cryodaq/core/zmq_subprocess.py:184:            debugging of the real socket state.
src/cryodaq/core/zmq_subprocess.py:186:            req = ctx.socket(zmq.REQ)
src/cryodaq/core/zmq_subprocess.py:188:            # IV.3 Finding 7: REQ timeout stays at 35 s so a slow
src/cryodaq/core/zmq_subprocess.py:191:            # the REQ side gives up. Server's 30 s ceiling + 5 s slack
src/cryodaq/core/zmq_subprocess.py:208:            # Fresh socket per command — no shared state across commands.
src/cryodaq/core/zmq_subprocess.py:209:            req = _new_req_socket()
src/cryodaq/core/zmq_subprocess.py:229:                req.close(linger=0)
src/cryodaq/core/sensor_diagnostics.py:6:- correlation (Pearson r внутри групп)
src/cryodaq/core/sensor_diagnostics.py:86:    correlation: float | None  # Pearson r with nearest neighbour in group
src/cryodaq/core/sensor_diagnostics.py:135:    """Pearson correlation. None if insufficient data or zero variance."""
src/cryodaq/core/sensor_diagnostics.py:169:        self.corr_min: float = thresholds.get("correlation_min", 0.8)
src/cryodaq/core/sensor_diagnostics.py:177:        # correlation_groups: group_name → list of channel_ids
src/cryodaq/core/sensor_diagnostics.py:178:        self._correlation_groups: dict[str, list[str]] = dict(cfg.get("correlation_groups", {}))
src/cryodaq/core/sensor_diagnostics.py:181:        for group_name, channels in self._correlation_groups.items():
src/cryodaq/core/sensor_diagnostics.py:282:        correlation = self._compute_correlation(channel_id)
src/cryodaq/core/sensor_diagnostics.py:290:            correlation,
src/cryodaq/core/sensor_diagnostics.py:298:            correlation,
src/cryodaq/core/sensor_diagnostics.py:311:            correlation=correlation,
src/cryodaq/core/sensor_diagnostics.py:357:    def _compute_correlation(self, channel_id: str) -> float | None:
src/cryodaq/core/sensor_diagnostics.py:366:        group_channels = self._correlation_groups.get(group_name, [])
src/cryodaq/core/sensor_diagnostics.py:414:        correlation: float | None,
src/cryodaq/core/sensor_diagnostics.py:427:        if correlation is not None and correlation < self.corr_min:
src/cryodaq/core/sensor_diagnostics.py:436:        correlation: float | None,
src/cryodaq/core/sensor_diagnostics.py:468:        if correlation is not None and correlation < self.corr_min:
src/cryodaq/core/zmq_bridge.py:76:# Phase 2b H.4: bind with EADDRINUSE retry. On Windows the socket from a
src/cryodaq/core/zmq_bridge.py:84:def _bind_with_retry(socket: Any, address: str) -> None:
src/cryodaq/core/zmq_bridge.py:85:    """Bind a ZMQ socket, retrying on EADDRINUSE with exponential backoff.
src/cryodaq/core/zmq_bridge.py:87:    Caller MUST set ``zmq.LINGER = 0`` on the socket BEFORE calling this
src/cryodaq/core/zmq_bridge.py:93:            socket.bind(address)
src/cryodaq/core/zmq_bridge.py:109:                    "Check for stale sockets via lsof/netstat.",
src/cryodaq/core/zmq_bridge.py:170:        self._socket: zmq.asyncio.Socket | None = None
src/cryodaq/core/zmq_bridge.py:183:                await self._socket.send_multipart([self._topic, payload])
src/cryodaq/core/zmq_bridge.py:190:        self._socket = self._ctx.socket(zmq.PUB)
src/cryodaq/core/zmq_bridge.py:191:        # Phase 2b H.4: LINGER=0 so the socket doesn't hold the port open
src/cryodaq/core/zmq_bridge.py:194:        self._socket.setsockopt(zmq.LINGER, 0)
src/cryodaq/core/zmq_bridge.py:199:        # reverted on the command path (REQ + REP); retained on the
src/cryodaq/core/zmq_bridge.py:202:        _bind_with_retry(self._socket, self._address)
src/cryodaq/core/zmq_bridge.py:216:        if self._socket:
src/cryodaq/core/zmq_bridge.py:217:            self._socket.close(linger=0)
src/cryodaq/core/zmq_bridge.py:218:            self._socket = None
src/cryodaq/core/zmq_bridge.py:250:        self._socket: zmq.asyncio.Socket | None = None
src/cryodaq/core/zmq_bridge.py:258:                parts = await asyncio.wait_for(self._socket.recv_multipart(), timeout=1.0)
src/cryodaq/core/zmq_bridge.py:282:        self._socket = self._ctx.socket(zmq.SUB)
src/cryodaq/core/zmq_bridge.py:283:        self._socket.setsockopt(zmq.LINGER, 0)
src/cryodaq/core/zmq_bridge.py:284:        self._socket.setsockopt(zmq.RECONNECT_IVL, 500)
src/cryodaq/core/zmq_bridge.py:285:        self._socket.setsockopt(zmq.RECONNECT_IVL_MAX, 5000)
src/cryodaq/core/zmq_bridge.py:286:        self._socket.setsockopt(zmq.RCVTIMEO, 3000)
src/cryodaq/core/zmq_bridge.py:287:        self._socket.connect(self._address)
src/cryodaq/core/zmq_bridge.py:288:        self._socket.subscribe(self._topic)
src/cryodaq/core/zmq_bridge.py:302:        if self._socket:
src/cryodaq/core/zmq_bridge.py:303:            self._socket.close(linger=0)
src/cryodaq/core/zmq_bridge.py:304:            self._socket = None
src/cryodaq/core/zmq_bridge.py:340:        self._socket: zmq.asyncio.Socket | None = None
src/cryodaq/core/zmq_bridge.py:386:        IV.3 Finding 7: always returns a dict. REP sockets require exactly
src/cryodaq/core/zmq_bridge.py:473:                raw = await asyncio.wait_for(self._socket.recv(), timeout=1.0)
src/cryodaq/core/zmq_bridge.py:482:            # Once recv() succeeds, the REP socket is in "awaiting send" state.
src/cryodaq/core/zmq_bridge.py:483:            # We MUST send a reply — otherwise the socket is stuck forever.
src/cryodaq/core/zmq_bridge.py:487:                await self._socket.send(json.dumps({"ok": False, "error": "invalid JSON"}).encode())
src/cryodaq/core/zmq_bridge.py:494:                # to avoid leaving REP socket in stuck state.
src/cryodaq/core/zmq_bridge.py:496:                    await self._socket.send(json.dumps({"ok": False, "error": "internal"}).encode())
src/cryodaq/core/zmq_bridge.py:505:                await self._socket.send(json.dumps(reply, default=str).encode())
src/cryodaq/core/zmq_bridge.py:509:                    await self._socket.send(json.dumps({"ok": False, "error": "internal"}).encode())
src/cryodaq/core/zmq_bridge.py:516:                # to avoid leaving the REP socket in stuck state.
src/cryodaq/core/zmq_bridge.py:518:                    await self._socket.send(
src/cryodaq/core/zmq_bridge.py:526:        self._socket = self._ctx.socket(zmq.REP)
src/cryodaq/core/zmq_bridge.py:528:        self._socket.setsockopt(zmq.LINGER, 0)
src/cryodaq/core/zmq_bridge.py:531:        # an ephemeral per-command REQ socket on the GUI subprocess
src/cryodaq/core/zmq_bridge.py:534:        _bind_with_retry(self._socket, self._address)
src/cryodaq/core/zmq_bridge.py:550:        if self._socket:
src/cryodaq/core/zmq_bridge.py:551:            self._socket.close(linger=0)
src/cryodaq/core/zmq_bridge.py:552:            self._socket = None
src/cryodaq/engine.py:1068:        # Build correlation groups from config; channel ids use display prefix (Т1→T1)
src/cryodaq/engine.py:1077:            len(_sd_cfg.get("correlation_groups", {})),
src/cryodaq/core/safety_manager.py:127:        # Multiple REQ clients (GUI subprocess + web dashboard + future
src/cryodaq/gui/zmq_client.py:48:class ZmqBridge:
src/cryodaq/gui/zmq_client.py:85:        # failures where the data plane is still healthy but REQ/REP
src/cryodaq/gui/zmq_client.py:93:        # Hardening 2026-04-21: restart counter for B1 diagnostic correlation
src/cryodaq/gui/zmq_client.py:213:    def send_command(self, cmd: dict) -> dict:
src/cryodaq/gui/zmq_client.py:214:        """Thread-safe command dispatch with Future-per-request correlation."""
src/cryodaq/gui/zmq_client.py:310:def send_command(cmd: dict) -> dict:
src/cryodaq/gui/shell/overlays/instruments_panel.py:512:                    _fmt(float(data["correlation"]), 2)
src/cryodaq/gui/shell/overlays/instruments_panel.py:513:                    if data.get("correlation") is not None
src/cryodaq/gui/shell/main_window_v2.py:642:        import socket
src/cryodaq/gui/shell/main_window_v2.py:651:            with socket.create_connection((host, _WEB_PORT), timeout=0.5):

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/core/zmq_subprocess.py | sed -n '150,240p'" in /Users/vladimir/Projects/cryodaq
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

codex
`send_command` uses a GUI-side request id and the subprocess creates a fresh REQ socket per queued command, so repeated non-OK probes do not reuse a poisoned REQ socket. I’m doing one final diff scan for additions outside the retry design before drafting the response.
exec
/opt/homebrew/bin/bash -lc 'git diff --unified=80 b2b4fb5 HEAD -- tools/diag_zmq_b1_capture.py' in /Users/vladimir/Projects/cryodaq
exec
/opt/homebrew/bin/bash -lc "python - <<'PY'
values = [None, {}, {'ok': None}, {'ok':'True'}, {'ok':1}, {'ok': True}, {'ok': False}]
for reply in values:
    r1_pass = bool(reply and reply.get('ok') is True)
    b2_fail = (not reply or reply.get('ok') is not True)
    print(repr(reply), 'r1_pass=', r1_pass, 'b2_fail=', b2_fail, 'equiv=', r1_pass == (not b2_fail))
PY" in /Users/vladimir/Projects/cryodaq
 exited 127 in 0ms:
/opt/homebrew/bin/bash: line 1: python: command not found

 succeeded in 0ms:
diff --git a/tools/diag_zmq_b1_capture.py b/tools/diag_zmq_b1_capture.py
index 632090f..d690eb3 100644
--- a/tools/diag_zmq_b1_capture.py
+++ b/tools/diag_zmq_b1_capture.py
@@ -1,143 +1,187 @@
 from __future__ import annotations
 
 import argparse
 import json
+import logging
 import sys
 import time
 from datetime import UTC, datetime
 from pathlib import Path
 
 if __package__ in {None, ""}:
     sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
 
 from cryodaq.gui.zmq_client import ZmqBridge
 from tools._b1_diagnostics import bridge_snapshot, direct_engine_probe
 from tools._zmq_helpers import DEFAULT_CMD_ADDR
 
+log = logging.getLogger(__name__)
+
+# Startup probe tuning. Each attempt sends one `safety_status` command
+# through the bridge; any OK reply passes. Total wall-clock bound is
+# dominated by the bridge command timeout on each attempt, not by the
+# inter-attempt sleeps.
+_STARTUP_PROBE_ATTEMPTS = 5
+_STARTUP_PROBE_BACKOFF_S = 0.2
+
 
 def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
     parser = argparse.ArgumentParser(
         description=(
             "Canonical B1 capture against current master. Records bridge-side "
             "and direct-engine command health into JSONL."
         )
     )
     parser.add_argument("--output", type=Path, required=True, help="JSONL artifact path.")
     parser.add_argument("--duration", type=float, default=180.0, help="Capture length in seconds.")
     parser.add_argument("--interval", type=float, default=1.0, help="Sample interval in seconds.")
     parser.add_argument("--address", default=DEFAULT_CMD_ADDR, help="Direct engine REQ address.")
     parser.add_argument(
         "--direct-timeout",
         type=float,
         default=5.0,
         help="Seconds to wait for the direct engine probe.",
     )
     parser.add_argument(
         "--skip-direct-probe",
         action="store_true",
         help="Only record bridge-side command health.",
     )
     return parser.parse_args(argv)
 
 
 def _sample_once(
     bridge: ZmqBridge,
     *,
     address: str,
     direct_timeout_s: float,
     skip_direct_probe: bool,
 ) -> dict:
     bridge.poll_readings()
     sample = bridge_snapshot(bridge)
     sample["ts_utc"] = datetime.now(UTC).isoformat()
     sample["bridge_reply"] = bridge.send_command({"cmd": "safety_status"})
     if skip_direct_probe:
         sample["direct_reply"] = None
     else:
         try:
             sample["direct_reply"] = direct_engine_probe(
                 address=address,
                 timeout_s=direct_timeout_s,
             )
         except TimeoutError as exc:
             sample["direct_reply"] = {
                 "ok": False,
                 "error": str(exc),
                 "exception_type": type(exc).__name__,
             }
     return sample
 
 
-def _validate_bridge_startup(bridge: ZmqBridge) -> None:
+def _validate_bridge_startup(
+    bridge: ZmqBridge,
+    *,
+    attempts: int = _STARTUP_PROBE_ATTEMPTS,
+    backoff_s: float = _STARTUP_PROBE_BACKOFF_S,
+    sleep_fn=time.sleep,
+) -> None:
+    """Verify bridge subprocess is alive and engine REP is answering.
+
+    R1 repair for the b2b4fb5 startup race: instead of a single-shot
+    ``safety_status`` probe (which aborted the capture at cmd #0 when
+    the engine's ipc:// REP socket had not finished binding), retry
+    the probe up to ``attempts`` times with ``backoff_s`` between
+    attempts. Any OK reply passes. See
+    ``docs/decisions/2026-04-24-b2b4fb5-investigation.md`` for the
+    empirical background.
+
+    Subprocess-spawn failure is still a single-shot check — no point
+    retrying a dead subprocess.
+    """
     if not bridge.is_alive():
         raise RuntimeError("ZMQ bridge subprocess failed to start")
-    reply = bridge.send_command({"cmd": "safety_status"})
-    if not reply or reply.get("ok") is not True:
-        raise RuntimeError(f"Bridge startup probe failed: {reply!r}")
+
+    last_reply: dict | None = None
+    for attempt in range(attempts):
+        reply = bridge.send_command({"cmd": "safety_status"})
+        if reply and reply.get("ok") is True:
+            return
+        last_reply = reply
+        if attempt < attempts - 1:
+            log.debug(
+                "bridge startup probe attempt %d/%d non-OK, retrying in %.2fs: %r",
+                attempt + 1,
+                attempts,
+                backoff_s,
+                reply,
+            )
+            sleep_fn(backoff_s)
+
+    raise RuntimeError(f"Bridge startup probe failed: {last_reply!r}")
 
 
 def run_capture(
     bridge: ZmqBridge,
     *,
     duration_s: float,
     interval_s: float,
     output_path: Path,
     address: str,
     direct_timeout_s: float,
     skip_direct_probe: bool,
     now_fn=time.monotonic,
     sleep_fn=time.sleep,
 ) -> int:
     output_path.parent.mkdir(parents=True, exist_ok=True)
     deadline = now_fn() + duration_s
     count = 0
 
     with output_path.open("w", encoding="utf-8") as fh:
         while True:
             if now_fn() >= deadline:
                 break
             sample = _sample_once(
                 bridge,
                 address=address,
                 direct_timeout_s=direct_timeout_s,
                 skip_direct_probe=skip_direct_probe,
             )
             count += 1
             sample["seq"] = count
             fh.write(json.dumps(sample, ensure_ascii=False) + "\n")
             fh.flush()
             if now_fn() >= deadline:
                 break
             sleep_fn(interval_s)
 
     return count
 
 
 def main(argv: list[str] | None = None) -> int:
     args = _parse_args(argv)
     bridge = ZmqBridge()
     bridge.start()
     time.sleep(1.0)
     try:
         try:
             _validate_bridge_startup(bridge)
         except RuntimeError as exc:
             print(f"B1 capture aborted: {exc}", file=sys.stderr)
             return 1
         samples = run_capture(
             bridge,
             duration_s=args.duration,
             interval_s=args.interval,
             output_path=args.output,
             address=args.address,
             direct_timeout_s=args.direct_timeout,
             skip_direct_probe=args.skip_direct_probe,
         )
     finally:
         bridge.shutdown()
     print(f"Wrote {samples} samples to {args.output}")
     return 0
 
 
 if __name__ == "__main__":
     sys.exit(main())

exec
/opt/homebrew/bin/bash -lc 'git show --stat --oneline c3f4f86 && git show -- tools/diag_zmq_b1_capture.py c3f4f86' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
c3f4f86 fix(diag): bounded-backoff retry in B1 capture probe (R1 repair for b2b4fb5)
 tests/tools/test_diag_zmq_b1_capture.py | 150 +++++++++++++++++++++++++++++++-
 tools/diag_zmq_b1_capture.py            |  57 ++++++++++++
 2 files changed, 204 insertions(+), 3 deletions(-)

exec
/opt/homebrew/bin/bash -lc "python3 - <<'PY'
values = [None, {}, {'ok': None}, {'ok':'True'}, {'ok':1}, {'ok': True}, {'ok': False}]
for reply in values:
    r1_pass = bool(reply and reply.get('ok') is True)
    b2_fail = (not reply or reply.get('ok') is not True)
    print(repr(reply), 'r1_pass=', r1_pass, 'b2_fail=', b2_fail, 'equiv=', r1_pass == (not b2_fail))
PY" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
None r1_pass= False b2_fail= True equiv= True
{} r1_pass= False b2_fail= True equiv= True
{'ok': None} r1_pass= False b2_fail= True equiv= True
{'ok': 'True'} r1_pass= False b2_fail= True equiv= True
{'ok': 1} r1_pass= False b2_fail= True equiv= True
{'ok': True} r1_pass= True b2_fail= False equiv= True
{'ok': False} r1_pass= False b2_fail= True equiv= True

codex
Model: gpt-5.5 / Reasoning effort: high

EQUIVALENT + improvement only

1. **Fast-path equivalence.** Yes. R1 checks `is_alive()`, sends one `{"cmd": "safety_status"}`, and returns `None` immediately on first OK reply: `tools/diag_zmq_b1_capture.py:101-108`. b2b4fb5 does the same: `b2b4fb5:tools/diag_zmq_b1_capture.py:71-76`. No R1 debug log runs on the OK fast path because the return precedes `log.debug(...)`; b2b4fb5 also logs nothing. Predicate check is equivalent for requested cases: `None`, `{}`, `{"ok": None}`, `{"ok": "True"}`, `{"ok": 1}`, `{"ok": False}` all fail; only `{"ok": True}` passes. Both use identity with literal `True`, so `1` is rejected.

2. **Exhausted-window equivalence.** Equivalent except for intended retry semantics. On exhaustion R1 raises `RuntimeError(f"Bridge startup probe failed: {last_reply!r}")`: `tools/diag_zmq_b1_capture.py:104-120`. b2b4fb5 raises `RuntimeError(f"Bridge startup probe failed: {reply!r}")`: `b2b4fb5:tools/diag_zmq_b1_capture.py:74-76`. Type and prefix/message format are identical. Content is the terminal failed reply, not necessarily the first failed reply. That is expected from retry: if all attempts return the same non-OK reply, downstream text is identical; if replies vary, grep on `Bridge startup probe failed:` remains identical while payload reflects the final attempt.

3. **is_alive short-circuit.** Identical. Both check once before any probe send and raise `RuntimeError("ZMQ bridge subprocess failed to start")`: R1 `tools/diag_zmq_b1_capture.py:101-102`; b2b4fb5 `b2b4fb5:tools/diag_zmq_b1_capture.py:72-73`. Main timing is also identical: `bridge.start()`, `time.sleep(1.0)`, then validation: R1 `tools/diag_zmq_b1_capture.py:162-168`; b2b4fb5 `b2b4fb5:tools/diag_zmq_b1_capture.py:118-124`.

4. **main() integration.** Identical to b2b4fb5. R1 catches `RuntimeError`, prints `B1 capture aborted: {exc}` to stderr, returns `1`, and still runs `bridge.shutdown()` through `finally`: `tools/diag_zmq_b1_capture.py:165-181`. b2b4fb5 has the same structure: `b2b4fb5:tools/diag_zmq_b1_capture.py:121-137`. Output file is not created on validation failure because `run_capture()` is not reached; file creation lives inside `run_capture()` at R1 `tools/diag_zmq_b1_capture.py:135-139`, b2b4fb5 `b2b4fb5:tools/diag_zmq_b1_capture.py:91-95`.

5. **Drift scan.** No behavior drift outside the intended retry loop.
   - `import logging`, `log = logging.getLogger(__name__)`: new, inert on fast path, no output by itself: `tools/diag_zmq_b1_capture.py:5,18`.
   - `_STARTUP_PROBE_ATTEMPTS = 5`, `_STARTUP_PROBE_BACKOFF_S = 0.2`: load-bearing retry bounds: `tools/diag_zmq_b1_capture.py:20-25`.
   - Signature `attempts`, `backoff_s`, `sleep_fn=time.sleep`: load-bearing for retry/test injection, private helper only: `tools/diag_zmq_b1_capture.py:81-87`.
   - Docstring/comment: inert: `tools/diag_zmq_b1_capture.py:88-100`.
   - `last_reply` local and `for attempt in range(attempts)`: load-bearing retry state: `tools/diag_zmq_b1_capture.py:104-110`.
   - `log.debug(...)`: new debug output only on non-final non-OK attempts; no fast-path effect. Arguments are simple locals/reply object; formatting is deferred by logging unless enabled: `tools/diag_zmq_b1_capture.py:110-118`.

6. **Subprocess / ZMQ plumbing.** No retry-induced REQ state leak found. GUI `ZmqBridge.send_command()` creates a fresh `_rid`, stores a `Future`, queues the command, waits, and removes pending state in `finally`: `src/cryodaq/gui/zmq_client.py:213-232`. Reply routing consumes `_rid` per reply: `src/cryodaq/gui/zmq_client.py:234-255`. Subprocess command forwarding creates a fresh REQ socket per command and closes it with `linger=0`: `src/cryodaq/core/zmq_subprocess.py:157-166,175-198,208-229`. Non-OK/timeouts may enqueue `cmd_timeout` control messages, but validation does not reuse a shared REQ socket; retries compound only time, debug logs, and possible timeout control markers, not ZMQ socket state.

**CRITICAL**
None.

**HIGH**
None.

**MEDIUM**
None.

**LOW**
None.

**ACCEPTABLE**
R1 intentionally changes single-shot failure into bounded retry: up to 5 startup probes with 0.2s inter-attempt sleeps, debug logging on retryable non-OK attempts, and final exception payload from the last failed reply. Fast path and exhausted-window exception type/prefix remain equivalent to b2b4fb5.
tokens used
44 488
Model: gpt-5.5 / Reasoning effort: high

EQUIVALENT + improvement only

1. **Fast-path equivalence.** Yes. R1 checks `is_alive()`, sends one `{"cmd": "safety_status"}`, and returns `None` immediately on first OK reply: `tools/diag_zmq_b1_capture.py:101-108`. b2b4fb5 does the same: `b2b4fb5:tools/diag_zmq_b1_capture.py:71-76`. No R1 debug log runs on the OK fast path because the return precedes `log.debug(...)`; b2b4fb5 also logs nothing. Predicate check is equivalent for requested cases: `None`, `{}`, `{"ok": None}`, `{"ok": "True"}`, `{"ok": 1}`, `{"ok": False}` all fail; only `{"ok": True}` passes. Both use identity with literal `True`, so `1` is rejected.

2. **Exhausted-window equivalence.** Equivalent except for intended retry semantics. On exhaustion R1 raises `RuntimeError(f"Bridge startup probe failed: {last_reply!r}")`: `tools/diag_zmq_b1_capture.py:104-120`. b2b4fb5 raises `RuntimeError(f"Bridge startup probe failed: {reply!r}")`: `b2b4fb5:tools/diag_zmq_b1_capture.py:74-76`. Type and prefix/message format are identical. Content is the terminal failed reply, not necessarily the first failed reply. That is expected from retry: if all attempts return the same non-OK reply, downstream text is identical; if replies vary, grep on `Bridge startup probe failed:` remains identical while payload reflects the final attempt.

3. **is_alive short-circuit.** Identical. Both check once before any probe send and raise `RuntimeError("ZMQ bridge subprocess failed to start")`: R1 `tools/diag_zmq_b1_capture.py:101-102`; b2b4fb5 `b2b4fb5:tools/diag_zmq_b1_capture.py:72-73`. Main timing is also identical: `bridge.start()`, `time.sleep(1.0)`, then validation: R1 `tools/diag_zmq_b1_capture.py:162-168`; b2b4fb5 `b2b4fb5:tools/diag_zmq_b1_capture.py:118-124`.

4. **main() integration.** Identical to b2b4fb5. R1 catches `RuntimeError`, prints `B1 capture aborted: {exc}` to stderr, returns `1`, and still runs `bridge.shutdown()` through `finally`: `tools/diag_zmq_b1_capture.py:165-181`. b2b4fb5 has the same structure: `b2b4fb5:tools/diag_zmq_b1_capture.py:121-137`. Output file is not created on validation failure because `run_capture()` is not reached; file creation lives inside `run_capture()` at R1 `tools/diag_zmq_b1_capture.py:135-139`, b2b4fb5 `b2b4fb5:tools/diag_zmq_b1_capture.py:91-95`.

5. **Drift scan.** No behavior drift outside the intended retry loop.
   - `import logging`, `log = logging.getLogger(__name__)`: new, inert on fast path, no output by itself: `tools/diag_zmq_b1_capture.py:5,18`.
   - `_STARTUP_PROBE_ATTEMPTS = 5`, `_STARTUP_PROBE_BACKOFF_S = 0.2`: load-bearing retry bounds: `tools/diag_zmq_b1_capture.py:20-25`.
   - Signature `attempts`, `backoff_s`, `sleep_fn=time.sleep`: load-bearing for retry/test injection, private helper only: `tools/diag_zmq_b1_capture.py:81-87`.
   - Docstring/comment: inert: `tools/diag_zmq_b1_capture.py:88-100`.
   - `last_reply` local and `for attempt in range(attempts)`: load-bearing retry state: `tools/diag_zmq_b1_capture.py:104-110`.
   - `log.debug(...)`: new debug output only on non-final non-OK attempts; no fast-path effect. Arguments are simple locals/reply object; formatting is deferred by logging unless enabled: `tools/diag_zmq_b1_capture.py:110-118`.

6. **Subprocess / ZMQ plumbing.** No retry-induced REQ state leak found. GUI `ZmqBridge.send_command()` creates a fresh `_rid`, stores a `Future`, queues the command, waits, and removes pending state in `finally`: `src/cryodaq/gui/zmq_client.py:213-232`. Reply routing consumes `_rid` per reply: `src/cryodaq/gui/zmq_client.py:234-255`. Subprocess command forwarding creates a fresh REQ socket per command and closes it with `linger=0`: `src/cryodaq/core/zmq_subprocess.py:157-166,175-198,208-229`. Non-OK/timeouts may enqueue `cmd_timeout` control messages, but validation does not reuse a shared REQ socket; retries compound only time, debug logs, and possible timeout control markers, not ZMQ socket state.

**CRITICAL**
None.

**HIGH**
None.

**MEDIUM**
None.

**LOW**
None.

**ACCEPTABLE**
R1 intentionally changes single-shot failure into bounded retry: up to 5 startup probes with 0.2s inter-attempt sleeps, debug logging on retryable non-OK attempts, and final exception payload from the last failed reply. Fast path and exhausted-window exception type/prefix remain equivalent to b2b4fb5.
