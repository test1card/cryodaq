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
session id: 019dbc69-e169-7e53-a0d3-e7e72ac1eaf1
--------
user
Model: gpt-5.5
Reasoning effort: high

# Driver hardening — Thyracont VSP63D probe checksum consistency

## Mission

`src/cryodaq/drivers/instruments/thyracont_vsp63d.py::_try_v1_probe`
(~lines 157-166) validates only the response prefix — it does NOT
check the checksum byte. The normal read path DOES validate the
checksum. Consequence: a non-VSP63D device (e.g., VSP206, which
bit us on 2026-04-20) can pass probe and be "connected" by the
driver, then emit NaN forever from read_channels. ~5 LOC fix
(patch spec only — CC will implement in a follow-up session).

## Context files

- `src/cryodaq/drivers/instruments/thyracont_vsp63d.py` full
- `HANDOFF_2026-04-20_GLM.md` §3 — the 2026-04-20 VSP206-masquerading
  incident record
- `tests/drivers/test_thyracont*.py` if any — match test style
- `src/cryodaq/drivers/base.py` `InstrumentDriver` / `Reading` ABC
  for return-value contract

## Specific questions

1. Why does the probe skip checksum validation? Git blame and
   architect intent (HANDOFF §3) suggest "forgiving probe for
   multi-firmware-version compatibility" — verify or refute.
2. Is there any case where a probe-without-checksum is correct?
   For example: do some legit VSP63D firmware revisions return a
   probe response with a non-standard or optional checksum that
   the current strict read-path would reject? If yes, we need to
   keep the probe lax but log the discrepancy loudly.
3. Propose: tighten probe to validate checksum (consistent with
   read path) OR keep lax probe + emit WARNING on checksum
   mismatch + record driver metadata flag "probe_checksum_mismatch".
   Which is safer given the 2026-04-20 failure mode and the
   SafetyManager's fail-closed default?
4. Patch (unified diff, under 50 lines) and regression test (under
   30 lines) for the chosen option.

## Output format

- First line: `Model: gpt-5.5 / Reasoning effort: high`
- Root-cause / intent paragraph (≤ 120 words)
- Preferred option: `TIGHTEN` or `LAX+WARN` with one-line rationale
- Unified diff patch (< 50 lines)
- Test case (< 30 lines)
- Max 1500 words total

## Scope fence

- Do not rewrite the transport layer (`drivers/transport/serial.py`).
- Do not propose mocking Protocol V2 — not currently used in the
  lab.
- Do not comment on unrelated Thyracont features (pressure unit
  conversion, etc.).

## Response file

Write to: `artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-05-thyracont-probe.response.md`

codex
I’ll inspect the driver, handoff note, and existing tests, then write the requested response file. The workspace is read-only, so I can produce the exact content here; if file creation is blocked I’ll call that out clearly.
exec
/opt/homebrew/bin/bash -lc "sed -n '1,260p' /Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/f09cfd210e21e96a0031f4d247be5f2e416d23b1/skills/using-superpowers/SKILL.md && sed -n '1,220p' /Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/f09cfd210e21e96a0031f4d247be5f2e416d23b1/skills/systematic-debugging/SKILL.md" in /Users/vladimir/Projects/cryodaq
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
name: systematic-debugging
description: Use when encountering any bug, test failure, or unexpected behavior, before proposing fixes
---

# Systematic Debugging

## Overview

Random fixes waste time and create new bugs. Quick patches mask underlying issues.

**Core principle:** ALWAYS find root cause before attempting fixes. Symptom fixes are failure.

**Violating the letter of this process is violating the spirit of debugging.**

## The Iron Law

```
NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST
```

If you haven't completed Phase 1, you cannot propose fixes.

## When to Use

Use for ANY technical issue:
- Test failures
- Bugs in production
- Unexpected behavior
- Performance problems
- Build failures
- Integration issues

**Use this ESPECIALLY when:**
- Under time pressure (emergencies make guessing tempting)
- "Just one quick fix" seems obvious
- You've already tried multiple fixes
- Previous fix didn't work
- You don't fully understand the issue

**Don't skip when:**
- Issue seems simple (simple bugs have root causes too)
- You're in a hurry (rushing guarantees rework)
- Manager wants it fixed NOW (systematic is faster than thrashing)

## The Four Phases

You MUST complete each phase before proceeding to the next.

### Phase 1: Root Cause Investigation

**BEFORE attempting ANY fix:**

1. **Read Error Messages Carefully**
   - Don't skip past errors or warnings
   - They often contain the exact solution
   - Read stack traces completely
   - Note line numbers, file paths, error codes

2. **Reproduce Consistently**
   - Can you trigger it reliably?
   - What are the exact steps?
   - Does it happen every time?
   - If not reproducible → gather more data, don't guess

3. **Check Recent Changes**
   - What changed that could cause this?
   - Git diff, recent commits
   - New dependencies, config changes
   - Environmental differences

4. **Gather Evidence in Multi-Component Systems**

   **WHEN system has multiple components (CI → build → signing, API → service → database):**

   **BEFORE proposing fixes, add diagnostic instrumentation:**
   ```
   For EACH component boundary:
     - Log what data enters component
     - Log what data exits component
     - Verify environment/config propagation
     - Check state at each layer

   Run once to gather evidence showing WHERE it breaks
   THEN analyze evidence to identify failing component
   THEN investigate that specific component
   ```

   **Example (multi-layer system):**
   ```bash
   # Layer 1: Workflow
   echo "=== Secrets available in workflow: ==="
   echo "IDENTITY: ${IDENTITY:+SET}${IDENTITY:-UNSET}"

   # Layer 2: Build script
   echo "=== Env vars in build script: ==="
   env | grep IDENTITY || echo "IDENTITY not in environment"

   # Layer 3: Signing script
   echo "=== Keychain state: ==="
   security list-keychains
   security find-identity -v

   # Layer 4: Actual signing
   codesign --sign "$IDENTITY" --verbose=4 "$APP"
   ```

   **This reveals:** Which layer fails (secrets → workflow ✓, workflow → build ✗)

5. **Trace Data Flow**

   **WHEN error is deep in call stack:**

   See `root-cause-tracing.md` in this directory for the complete backward tracing technique.

   **Quick version:**
   - Where does bad value originate?
   - What called this with bad value?
   - Keep tracing up until you find the source
   - Fix at source, not at symptom

### Phase 2: Pattern Analysis

**Find the pattern before fixing:**

1. **Find Working Examples**
   - Locate similar working code in same codebase
   - What works that's similar to what's broken?

2. **Compare Against References**
   - If implementing pattern, read reference implementation COMPLETELY
   - Don't skim - read every line
   - Understand the pattern fully before applying

3. **Identify Differences**
   - What's different between working and broken?
   - List every difference, however small
   - Don't assume "that can't matter"

4. **Understand Dependencies**
   - What other components does this need?
   - What settings, config, environment?
   - What assumptions does it make?

### Phase 3: Hypothesis and Testing

**Scientific method:**

1. **Form Single Hypothesis**
   - State clearly: "I think X is the root cause because Y"
   - Write it down
   - Be specific, not vague

2. **Test Minimally**
   - Make the SMALLEST possible change to test hypothesis
   - One variable at a time
   - Don't fix multiple things at once

3. **Verify Before Continuing**
   - Did it work? Yes → Phase 4
   - Didn't work? Form NEW hypothesis
   - DON'T add more fixes on top

4. **When You Don't Know**
   - Say "I don't understand X"
   - Don't pretend to know
   - Ask for help
   - Research more

### Phase 4: Implementation

**Fix the root cause, not the symptom:**

1. **Create Failing Test Case**
   - Simplest possible reproduction
   - Automated test if possible
   - One-off test script if no framework
   - MUST have before fixing
   - Use the `superpowers:test-driven-development` skill for writing proper failing tests

2. **Implement Single Fix**
   - Address the root cause identified
   - ONE change at a time
   - No "while I'm here" improvements
   - No bundled refactoring

3. **Verify Fix**
   - Test passes now?
   - No other tests broken?
   - Issue actually resolved?

4. **If Fix Doesn't Work**
   - STOP
   - Count: How many fixes have you tried?
   - If < 3: Return to Phase 1, re-analyze with new information
   - **If ≥ 3: STOP and question the architecture (step 5 below)**
   - DON'T attempt Fix #4 without architectural discussion

5. **If 3+ Fixes Failed: Question Architecture**

   **Pattern indicating architectural problem:**
   - Each fix reveals new shared state/coupling/problem in different place
   - Fixes require "massive refactoring" to implement
   - Each fix creates new symptoms elsewhere

   **STOP and question fundamentals:**
   - Is this pattern fundamentally sound?
   - Are we "sticking with it through sheer inertia"?
   - Should we refactor architecture vs. continue fixing symptoms?

   **Discuss with your human partner before attempting more fixes**

   This is NOT a failed hypothesis - this is a wrong architecture.

## Red Flags - STOP and Follow Process

If you catch yourself thinking:
- "Quick fix for now, investigate later"
- "Just try changing X and see if it works"
- "Add multiple changes, run tests"

codex
Using `superpowers:systematic-debugging` for the probe failure analysis. I’m going to pin the root cause from code and history first, then keep the recommendation scoped to the requested patch spec.
exec
/opt/homebrew/bin/bash -lc "sed -n '1,260p' HANDOFF_2026-04-20_GLM.md" in /Users/vladimir/Projects/cryodaq
exec
/opt/homebrew/bin/bash -lc "sed -n '1,260p' src/cryodaq/drivers/instruments/thyracont_vsp63d.py" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
# Handoff — 2026-04-20 evening → GLM-5.1 (via CCR)

**Author:** Claude Opus 4.7 (web) — primary architect for this project.
**Read this before anything else.** It is the single-source-of-truth
snapshot at the moment control handed off.

**Context:** Vladimir's Anthropic weekly limit is 99 % burnt. For
the next ~4-5 days the primary model driving Claude Code will be
**GLM-5.1 via Chutes** through `claude-code-router` proxy, not
Claude Opus directly. Codex (ChatGPT subscription) and Gemini
(Google subscription) still work on their own quotas independently.

This handoff exists because the running-context of the human-AI pair
today is 40 + turns deep and none of it is in git. The goal is:
**no operational memory loss across the architect-model transition.**

---

## 0. Who is Vladimir, how does he work

Read this once, do not re-ask.

- **Vladimir Fomenko**, 28, Head of Cryogenic Laboratory at
  Astro Space Center of FIAN (Lebedev Physical Institute), Moscow.
  Works on thermal vacuum testing and cryogenic systems for the
  Millimetron space observatory.
- He is **NOT a career programmer**. He started writing CryoDAQ
  less than a month ago. He is a thermal engineer and researcher
  first. He reads code fine but does not write large features —
  models do.
- **Communication:** Russian by default, technical English for
  code / docs / tool calls. Direct, peer-to-peer, no filler,
  sarcasm welcome. Never praise-by-default; never
  "great question!" opener. Engineer-to-engineer tone.
- **Epistemology:** every claim must be verifiable via physics,
  logic, or standards. No data → say "no reliable data." Uncertain
  → ask, do not guess. He cross-checks everything. Errors are
  data, not cause for apology or defence. Thesis → Reasoning →
  Conclusion audit format.
- **Methodology:** equations → analytical limits → code. Never
  code before physics is understood. Calculations show units,
  dimensional checks, assumptions.
- **Voice:** see `/mnt/skills/user/vladimir-voice/SKILL.md` (Mac
  Claude Code skill) if available — strong signal of his authorial
  style for any text that ships under his name.

---

## 1. System state at handoff (2026-04-20 ~17:00 Moscow)

### Pushed to `origin/master`

In chronological order (all today):

| SHA | What | Status |
|---|---|---|
| `362431b` | docs: B1 Codex analysis + IV.6 fix spec | ✅ shipped |
| `74dbbc7` | reporting: xml_safe sanitizer for python-docx | ✅ verified on Ubuntu |
| `be51a24` | zmq: IV.6 partial B1 mitigation (ephemeral REQ + watchdog) | ⚠️ did NOT fix B1, landed as architectural improvement |
| `aabd75f` | engine: wire validate_checksum through Thyracont driver loader | ✅ verified fixes pressure display |

Earlier today (before handoff window): IV.4 batch closed at `7cb5634`,
TCP_KEEPALIVE partial at `f5f9039`.

### Possibly uncommitted on Ubuntu lab PC (confirm with Vladimir)

**Launcher watchdog cooldown fix.** IV.6 watchdog (in `be51a24`) had
a regression: after watchdog-triggered bridge restart, the
`_last_cmd_timeout` flag persisted across the restart,
`command_channel_stalled()` returned True on the very next poll,
triggering another restart → restart storm (30-40 restarts/min
observed on Ubuntu lab PC).

Surgical fix was applied in-place on Ubuntu's `src/cryodaq/launcher.py`
adding 60 s cooldown + missing `return` after restart. Block now:

```python
        # IV.6 watchdog guard: 60s cooldown prevents restart storm when
        # a freshly-restarted subprocess immediately sees a stale
        # cmd_timeout signal from before the restart.
        if self._bridge.command_channel_stalled(timeout_s=10.0):
            now = time.monotonic()
            last_cmd_restart = getattr(self, "_last_cmd_watchdog_restart", 0.0)
            if now - last_cmd_restart >= 60.0:
                logger.warning(
                    "ZMQ bridge: command channel unhealthy "
                    "(recent command timeout). Restarting bridge."
                )
                self._last_cmd_watchdog_restart = now
                self._bridge.shutdown()
                self._bridge.start()
                return
```

**Commit message (pre-drafted):**

```
launcher: watchdog cooldown prevents restart storm (B1 regression fix)

IV.6 command-channel watchdog (commit be51a24) had a regression:
when the fresh subprocess starts after a watchdog-triggered restart,
the _last_cmd_timeout flag persists from before the restart,
command_channel_stalled() returns True on the very next poll,
triggering another restart -> restart storm (30-40 restarts/minute
observed on Ubuntu lab PC).

Fix: enforce 60s cooldown between command-watchdog restarts via
self._last_cmd_watchdog_restart timestamp. Also add missing 'return'
after restart so no further checks run in the same poll cycle.

This does not resolve B1 (command plane still fails ~60-120s after
any fresh bridge start). But it eliminates the storm — system
returns to 'works ~60-120s, one restart, works again' cycle which
is usable as a workaround until IV.7 ipc:// fix.
```

**First task GLM should do on wake-up:** check `git log --oneline -5`
on Ubuntu. If latest commit is NOT the watchdog cooldown fix,
commit + push using the message above.

### Ubuntu-only config changes (most NOT in git)

On the lab PC `~/cryodaq/config/`:

1. **`instruments.local.yaml`** — added `validate_checksum: false` to
   Thyracont block. **Per-machine, NOT in git** (gitignored). Required
   because lab hardware is VSP206, not VSP63D — different checksum
   formula; driver's V1 path now rejects every read as mismatch. Raw
   response `001M100023D` from real gauge decodes physically correct
   (~1000 mbar = atmosphere, stand not pumped down), only the CS byte
   differs.

2. **`interlocks.yaml`** — in git, **committed on Mac but may or may
   not be pushed**. Changed `overheat_cryostat` regex from `Т[1-8] .*`
   to `Т(1|2|3|5|6|7|8) .*` to exclude Т4. Physical reason: Т4
   ("Радиатор 2") sensor is disconnected on current hardware; reads
   380 K when open-circuit, was triggering `emergency_off` on
   Keithley during routine operation.

3. **`alarms_v3.yaml`** — in git, same push status as interlocks. Added
   Т4 to `uncalibrated` and `all_temp` channel groups. So Т4 open-
   circuit condition now generates WARNING via `sensor_fault` alarm
   (operator-visible in alarm panel) without hardware lockout.

If `interlocks.yaml` + `alarms_v3.yaml` changes are not yet in git —
commit them together with this message:

```
config: exclude Т4 (disconnected sensor) from overheat interlock

Physically Т4 (Радиатор 2) sensor is disconnected on current hardware —
reads 380K when open-circuit, which was triggering overheat_cryostat
interlock (threshold 350K) and causing spurious emergency_off events
on Keithley during normal operation.

- interlocks.yaml: overheat_cryostat regex Т[1-8] → Т(1|2|3|5|6|7|8)
  Keeps interlock coverage for all physically installed sensors
  on the cryostat (Т1-Т3, Т5-Т8), excludes Т4.
- alarms_v3.yaml: added Т4 to uncalibrated + all_temp channel groups
  so sensor_fault / stale detection still publishes WARNING alarms
  for Т4 (outside-range 0-350K) without hardware lockout.

Net effect: Т4 open-circuit produces WARNING in alarm panel
(operator visible) instead of emergency_off (production disruption).
Restore to full interlock coverage by reverting this commit when
Т4 is physically reconnected.
```

### Operational fix on Ubuntu (system-level, not in git)

`sudo systemctl stop ModemManager && sudo systemctl disable ModemManager`
— ModemManager was grabbing `/dev/ttyUSB0` briefly on every USB enumerate,
locking the FTDI port from Thyracont connect. After disable, port is
consistently available. No rollback needed.

---

## 2. What is fixed today (end-to-end verified)

1. **Pressure display** — was showing em-dash. Two causes stacked:
   - ModemManager grabbing `/dev/ttyUSB0` (operational fix)
   - `validate_checksum` YAML key was never wired through the driver
     loader (code fix, commit `aabd75f`)
   - Driver default flipped to `True` in Phase 2c Codex F.2, but VSP206
     has different checksum formula than VSP63D → opt-out needed for
     this hardware
   - Both fixed → pressure numeric value now shown in TopWatchBar.
     Config-side `validate_checksum: false` is the operational escape
     hatch.

2. **Т4 false interlock** — disconnected sensor triggered emergency_off.
   Fixed via config (regex + alarm group move).

3. **Report generation** — `experiment_generate_report` was failing
   with `All strings must be XML compatible: ...` on Ubuntu when real
   Keithley was connected. Keithley VISA resource string requires
   `\x00` null byte per NI-VISA spec → python-docx rejected string
   → ValueError → auto-report silently failed with only the exception
   message logged (traceback swallowed). Fix (commit `74dbbc7`):
   - New `src/cryodaq/utils/xml_safe.py` strips XML-illegal control chars
   - Applied at all `add_paragraph()` / `cell.text` sites in
     `src/cryodaq/reporting/sections.py`
   - Upgraded `src/cryodaq/core/experiment.py:782` from `log.warning`
     to `log.exception` so future failures carry tracebacks
   - **Verified on Ubuntu** — DOCX reports now generate correctly
     with real instruments connected

4. **TopWatchBar labels** (much earlier today, commit `5a8e823`):
   `Т мин` → `Т 2ст.` and `Т макс` → `Т N₂` (using Unicode subscript
   U+2082). Positional labels match Millimetron operator mental model.

---

## 3. What is NOT fixed — B1 is still open

### B1: ZMQ command channel silently dies after 30-120 s of bridge uptime

**Confirmed on both platforms.** Python/pyzmq/libzmq versions:
- macOS dev: Python 3.14.3 + pyzmq 25.x
- Ubuntu lab: Python 3.12.13 + pyzmq 26.4.0 + libzmq 4.3.5

**NOT an idle problem.** The original "macOS loopback TCP idle reap"
hypothesis was disproved by:

1. Linux default `tcp_keepalive_time = 7200s` rules out kernel reaping
   on Ubuntu (kernel wouldn't touch a loopback connection for 2 hours).
2. Active polling at 1 Hz never goes idle for more than 1 second.

**NOT a shared-REQ-state problem.** Codex's revised hypothesis
(be51a24) was that accumulated state on a single long-lived REQ
socket eventually poisoned the command plane. IV.6 replaced shared
REQ with per-command ephemeral REQ + launcher watchdog. Unit tests
pass 60/60. Full suite green. BUT Stage 3 diag tools reproduce B1
with structurally identical timing post-fix:

- `diag_zmq_idle_hypothesis.py` SPARSE_0.33HZ: cmd #8 FAIL at uptime
  56 s (pre-fix was cmd #10 at ~30 s)
- `diag_zmq_bridge_extended.py`: cmd #48 FAIL at uptime 82 s,
  0/3 recovery (pre-fix was cmd #28 at 92 s)
- RAPID_5 Hz path still clean (295/295) on both — rate dependence
  preserved

**Everything above the transport is ruled out.** Engine asyncio loop
healthy during failure window (heartbeats, readings, plugin ticks,
scheduler writes all continue). Engine REP task alive, just silently
not replying. Data-plane PUB/SUB unaffected.

**IV.6 code stayed in master as defence-in-depth** — matches ZeroMQ
Guide ch.4 canonical poll/timeout/close/reopen pattern, removes a
real brittle point (shared REQ accumulated state), gives the
launcher a genuine command-channel watchdog. Independent of whether
B1 is ultimately resolved at transport layer.

**Workaround in place:** watchdog cooldown + 60-120 s functional
window → single restart → another 60-120 s window. Not pretty, but
usable.

**Next attempt: IV.7 — `ipc://` transport experiment.** See
`CC_PROMPT_IV_7_IPC_TRANSPORT.md`. Rationale: if B1 is NOT idle
and NOT shared-state, the remaining likely culprit is TCP-loopback

 succeeded in 0ms:
"""Драйвер вакуумметра Thyracont VSP63D (RS-232/USB-Serial)."""

from __future__ import annotations

import logging
import math
import random
import time

from cryodaq.drivers.base import ChannelStatus, InstrumentDriver, Reading
from cryodaq.drivers.transport.serial import SerialTransport

log = logging.getLogger(__name__)

# Известные пары baudrate ↔ fallback для автоопределения протокола
_FALLBACK_BAUDRATES: dict[int, int] = {9600: 115200, 115200: 9600}

# Коды статуса из ответа прибора
_STATUS_OK = 0
_STATUS_UNDERRANGE = 1
_STATUS_OVERRANGE = 2
_STATUS_SENSOR_ERROR = 3

# Карта кода статуса → ChannelStatus
_STATUS_MAP: dict[int, ChannelStatus] = {
    _STATUS_OK: ChannelStatus.OK,
    _STATUS_UNDERRANGE: ChannelStatus.UNDERRANGE,
    _STATUS_OVERRANGE: ChannelStatus.OVERRANGE,
    _STATUS_SENSOR_ERROR: ChannelStatus.SENSOR_ERROR,
}

# Mock-параметры: реалистичный вакуум
_MOCK_BASE_PRESSURE_MBAR: float = 1.5e-6


class ThyracontVSP63D(InstrumentDriver):
    """Вакуумметр Thyracont VSP63D / VSM77DL.

    Поддерживает два протокола:

    **VSP63D (по умолчанию):**
      RS-232/USB-Serial, 9600 бод.
      Команда: ``"MV00\\r"`` → ответ: ``"status,value\\r"``

    **Thyracont Protocol V1 (VSM77DL и аналоги):**
      RS-232/USB-Serial, 115200 бод.
      Команда: ``"<addr>M^\\r"`` → ответ: ``"<addr>M<6digits><checksum>\\r"``
      Кодировка 6-значного значения (ABCDEF): ABCD = мантисса, EF = экспонента.
      ``pressure = (ABCD / 1000) * 10^(EF - 20)`` mbar.

    Протокол определяется автоматически по формату ответа, а также может
    быть форсирован через параметр ``protocol``.

    Parameters
    ----------
    name:
        Уникальное имя экземпляра прибора (используется в метаданных Reading).
    resource_str:
        Имя последовательного порта, например ``"COM3"`` или ``"/dev/ttyUSB0"``.
    baudrate:
        Скорость обмена в бодах (по умолчанию 9600).
    address:
        Адрес прибора для Protocol V1 (по умолчанию ``"001"``).
    mock:
        Если ``True`` — работает без реального прибора, возвращает
        имитированное давление ~1.5e-6 мбар.
    """

    def __init__(
        self,
        name: str,
        resource_str: str,
        *,
        baudrate: int = 9600,
        address: str = "001",
        mock: bool = False,
        # Phase 2c Codex F.2: default flipped from False to True. Thyracont
        # protocol carries an explicit CS field; on noisy RS-232 lines a
        # silent corruption could otherwise produce an incorrect pressure
        # reading. Operators with known-bad firmware can opt back out via
        # `validate_checksum: false` in instruments.local.yaml.
        validate_checksum: bool = True,
    ) -> None:
        super().__init__(name, mock=mock)
        self._resource_str = resource_str
        self._baudrate = baudrate
        self._address = address
        self._transport = SerialTransport(mock=mock)
        self._instrument_id: str = ""
        self._protocol_v1: bool = False
        self._validate_checksum: bool = validate_checksum

    # ------------------------------------------------------------------
    # InstrumentDriver — обязательный интерфейс
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Открыть последовательный порт и верифицировать связь с прибором.

        Пробует Protocol V1 (``"<addr>M^"``), затем MV00. Если ни один
        протокол не отвечает на сконфигурированном baudrate, пробует
        fallback baudrate (9600 ↔ 115200). Устанавливает флаг
        ``_connected = True`` при успехе.
        """
        baudrates_to_try = [self._baudrate]
        fallback = _FALLBACK_BAUDRATES.get(self._baudrate)
        if fallback is not None:
            baudrates_to_try.append(fallback)

        last_error = ""
        for baud in baudrates_to_try:
            log.info("%s: подключение к %s @ %d бод", self.name, self._resource_str, baud)
            try:
                await self._transport.open(self._resource_str, baudrate=baud)
            except Exception as exc:
                log.warning("%s: failed to open port @ %d baud: %s", self.name, baud, exc)
                last_error = str(exc)
                continue

            # Try Protocol V1
            if await self._try_v1_probe():
                self._protocol_v1 = True
                self._instrument_id = f"Thyracont-V1@{self._address}"
                self._connected = True
                if baud != self._baudrate:
                    log.info(
                        "%s: connected via Protocol V1 @ %d baud (fallback from %d)",
                        self.name,
                        baud,
                        self._baudrate,
                    )
                else:
                    log.info("%s: connected via Protocol V1", self.name)
                return

            # Try MV00
            if await self._try_mv00_probe():
                self._protocol_v1 = False
                self._instrument_id = f"Thyracont-MV00@{self._resource_str}"
                self._connected = True
                if baud != self._baudrate:
                    log.info(
                        "%s: connected via MV00 @ %d baud (fallback from %d)",
                        self.name,
                        baud,
                        self._baudrate,
                    )
                else:
                    log.info("%s: connected via MV00", self.name)
                return

            await self._transport.close()
            last_error = f"neither V1 nor MV00 responded @ {baud} baud"

        raise RuntimeError(f"{self.name}: {last_error}")

    async def _try_v1_probe(self) -> bool:
        """Attempt Protocol V1 probe. Returns True on success."""
        cmd = f"{self._address}M^"
        expected_prefix = f"{self._address}M"
        for attempt in range(3):
            if attempt > 0:
                await self._transport.flush_input()
            try:
                resp = await self._transport.query(cmd)
                if resp.strip().startswith(expected_prefix):
                    log.debug("%s: V1 probe OK (attempt %d)", self.name, attempt + 1)
                    return True
            except Exception as exc:
                log.debug("%s: V1 probe attempt %d failed: %s", self.name, attempt + 1, exc)
        return False

    async def _try_mv00_probe(self) -> bool:
        """Attempt MV00 protocol probe. Returns True on success."""
        await self._transport.flush_input()
        try:
            resp = await self._transport.query("MV00")
            resp_stripped = resp.strip()
            # MV00 returns "<status>,<value>" e.g. "0,1.234E-06"
            if "," in resp_stripped:
                log.debug("%s: MV00 probe OK: %s", self.name, resp_stripped)
                return True
        except Exception as exc:
            log.debug("%s: MV00 probe failed: %s", self.name, exc)
        return False

    async def disconnect(self) -> None:
        """Разорвать соединение с прибором (идемпотентно)."""
        if not self._connected:
            return
        log.info("%s: отключение", self.name)
        await self._transport.close()
        self._connected = False

    async def read_channels(self) -> list[Reading]:
        """Считать давление командой ``MV00``.

        Returns
        -------
        list[Reading]
            Список из одного объекта :class:`~cryodaq.drivers.base.Reading`.
            Единица измерения — миллибар (``"mbar"``).

        Raises
        ------
        RuntimeError
            Если прибор не подключён.
        """
        if not self._connected:
            raise RuntimeError(f"{self.name}: прибор не подключён")

        if self.mock:
            return self._mock_readings()

        if self._protocol_v1:
            cmd = f"{self._address}M^"
            raw_response = await self._transport.query(cmd)
            log.debug("%s: %s → %s", self.name, cmd, raw_response.strip())
            return [self._parse_v1_response(raw_response)]

        raw_response = await self._transport.query("MV00")
        log.debug("%s: MV00 → %s", self.name, raw_response.strip())
        return [self._parse_response(raw_response)]

    # ------------------------------------------------------------------
    # Разбор ответа прибора
    # ------------------------------------------------------------------

    def _parse_response(self, response: str) -> Reading:
        """Разобрать строку ответа ``"status,value\\r"`` в Reading.

        Формат ответа: ``"<код_статуса>,<значение_давления>\\r"``, например::

            0,1.234E-06\\r

        Parameters
        ----------
        response:
            Сырая строка ответа от прибора.

        Returns
        -------
        Reading
            Показание давления с соответствующим статусом.
        """
        response_stripped = response.strip()
        channel = f"{self.name}/pressure"

        try:
            parts = response_stripped.split(",", 1)
            if len(parts) != 2:
                raise ValueError(f"Неверный формат ответа: '{response_stripped}'")

            status_code = int(parts[0].strip())
            value = float(parts[1].strip())
        except (ValueError, IndexError) as exc:
            log.error(
                "%s: не удалось разобрать ответ '%s' — %s",
                self.name,
                response_stripped,

exec
/opt/homebrew/bin/bash -lc "rg --files tests src/cryodaq/drivers | rg 'thyracont|base.py'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
src/cryodaq/drivers/base.py
src/cryodaq/drivers/instruments/thyracont_vsp63d.py
tests/drivers/test_thyracont_checksum_default.py
tests/drivers/test_thyracont_vsp63d.py

exec
/opt/homebrew/bin/bash -lc 'git blame -L 145,180 -- src/cryodaq/drivers/instruments/thyracont_vsp63d.py' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
d8ec668c (Claude             2026-04-17 08:42:07 +0000 145)                         baud,
d8ec668c (Claude             2026-04-17 08:42:07 +0000 146)                         self._baudrate,
9feaf3ed (Vladimir Fomenko   2026-04-01 03:57:02 +0300 147)                     )
9feaf3ed (Vladimir Fomenko   2026-04-01 03:57:02 +0300 148)                 else:
9feaf3ed (Vladimir Fomenko   2026-04-01 03:57:02 +0300 149)                     log.info("%s: connected via MV00", self.name)
9feaf3ed (Vladimir Fomenko   2026-04-01 03:57:02 +0300 150)                 return
9feaf3ed (Vladimir Fomenko   2026-04-01 03:57:02 +0300 151) 
9feaf3ed (Vladimir Fomenko   2026-04-01 03:57:02 +0300 152)             await self._transport.close()
9feaf3ed (Vladimir Fomenko   2026-04-01 03:57:02 +0300 153)             last_error = f"neither V1 nor MV00 responded @ {baud} baud"
9feaf3ed (Vladimir Fomenko   2026-04-01 03:57:02 +0300 154) 
9feaf3ed (Vladimir Fomenko   2026-04-01 03:57:02 +0300 155)         raise RuntimeError(f"{self.name}: {last_error}")
a2f4bcd0 (Vladimir Fomenko   2026-03-21 12:01:31 +0300 156) 
a2f4bcd0 (Vladimir Fomenko   2026-03-21 12:01:31 +0300 157)     async def _try_v1_probe(self) -> bool:
a2f4bcd0 (Vladimir Fomenko   2026-03-21 12:01:31 +0300 158)         """Attempt Protocol V1 probe. Returns True on success."""
8605a52f (gaurlleboulledeaux 2026-03-19 11:14:49 +0300 159)         cmd = f"{self._address}M^"
8605a52f (gaurlleboulledeaux 2026-03-19 11:14:49 +0300 160)         expected_prefix = f"{self._address}M"
8605a52f (gaurlleboulledeaux 2026-03-19 11:14:49 +0300 161)         for attempt in range(3):
8605a52f (gaurlleboulledeaux 2026-03-19 11:14:49 +0300 162)             if attempt > 0:
8605a52f (gaurlleboulledeaux 2026-03-19 11:14:49 +0300 163)                 await self._transport.flush_input()
8605a52f (gaurlleboulledeaux 2026-03-19 11:14:49 +0300 164)             try:
8605a52f (gaurlleboulledeaux 2026-03-19 11:14:49 +0300 165)                 resp = await self._transport.query(cmd)
a2f4bcd0 (Vladimir Fomenko   2026-03-21 12:01:31 +0300 166)                 if resp.strip().startswith(expected_prefix):
a2f4bcd0 (Vladimir Fomenko   2026-03-21 12:01:31 +0300 167)                     log.debug("%s: V1 probe OK (attempt %d)", self.name, attempt + 1)
a2f4bcd0 (Vladimir Fomenko   2026-03-21 12:01:31 +0300 168)                     return True
8605a52f (gaurlleboulledeaux 2026-03-19 11:14:49 +0300 169)             except Exception as exc:
a2f4bcd0 (Vladimir Fomenko   2026-03-21 12:01:31 +0300 170)                 log.debug("%s: V1 probe attempt %d failed: %s", self.name, attempt + 1, exc)
a2f4bcd0 (Vladimir Fomenko   2026-03-21 12:01:31 +0300 171)         return False
a2f4bcd0 (Vladimir Fomenko   2026-03-21 12:01:31 +0300 172) 
a2f4bcd0 (Vladimir Fomenko   2026-03-21 12:01:31 +0300 173)     async def _try_mv00_probe(self) -> bool:
a2f4bcd0 (Vladimir Fomenko   2026-03-21 12:01:31 +0300 174)         """Attempt MV00 protocol probe. Returns True on success."""
a2f4bcd0 (Vladimir Fomenko   2026-03-21 12:01:31 +0300 175)         await self._transport.flush_input()
a2f4bcd0 (Vladimir Fomenko   2026-03-21 12:01:31 +0300 176)         try:
a2f4bcd0 (Vladimir Fomenko   2026-03-21 12:01:31 +0300 177)             resp = await self._transport.query("MV00")
a2f4bcd0 (Vladimir Fomenko   2026-03-21 12:01:31 +0300 178)             resp_stripped = resp.strip()
a2f4bcd0 (Vladimir Fomenko   2026-03-21 12:01:31 +0300 179)             # MV00 returns "<status>,<value>" e.g. "0,1.234E-06"
a2f4bcd0 (Vladimir Fomenko   2026-03-21 12:01:31 +0300 180)             if "," in resp_stripped:

codex
The blame points to the original V1 probe shape plus a later prefix-only refinement, not to the checksum-hardening commit. I’m checking the parser and tests now to see whether the current strict path already has the right reusable validation point.
exec
/opt/homebrew/bin/bash -lc "sed -n '260,560p' src/cryodaq/drivers/instruments/thyracont_vsp63d.py" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
                response_stripped,
                exc,
            )
            return Reading.now(
                channel=channel,
                value=float("nan"),
                unit="mbar",
                instrument_id=self.name,
                status=ChannelStatus.SENSOR_ERROR,
                raw=None,
                metadata={"raw_response": response_stripped},
            )

        ch_status = _STATUS_MAP.get(status_code, ChannelStatus.SENSOR_ERROR)

        if ch_status != ChannelStatus.OK:
            log.warning(
                "%s: статус ответа %d (%s), значение=%s мбар",
                self.name,
                status_code,
                ch_status.value,
                value,
            )

        return Reading.now(
            channel=channel,
            value=value,
            unit="mbar",
            instrument_id=self.name,
            status=ch_status,
            raw=value,
            metadata={"status_code": status_code},
        )

    # ------------------------------------------------------------------
    # Разбор ответа Protocol V1 (VSM77DL)
    # ------------------------------------------------------------------

    @staticmethod
    def _verify_v1_checksum(response: str) -> bool:
        """Verify Thyracont Protocol V1 checksum.

        Format: <payload><checksum_char>
        Checksum = XOR of all bytes in payload, masked to 0x7F.
        """
        if len(response) < 2:
            return False
        payload = response[:-1]
        expected_char = response[-1]
        computed = 0
        for byte in payload.encode("ascii", errors="replace"):
            computed ^= byte
        computed &= 0x7F
        return chr(computed) == expected_char

    def _parse_v1_response(self, response: str) -> Reading:
        """Разобрать ответ Thyracont Protocol V1.

        Формат: ``"<addr>M<6digits><checksum>\\r"``, например ``"001M260017N\\r"``.

        Кодировка 6-значного значения ABCDEF::

            ABCD = мантисса (4 цифры)
            EF   = экспонента (2 цифры)
            pressure_mbar = (ABCD / 1000) × 10^(EF − 20)

        Примеры:
        - ``260017`` → (2600/1000) × 10^(17−20) = 2.6e-3 mbar
        - ``100023`` → (1000/1000) × 10^(23−20) = 1000 mbar

        Parameters
        ----------
        response:
            Сырая строка ответа от прибора.

        Returns
        -------
        Reading
            Показание давления.
        """
        channel = f"{self.name}/pressure"
        response_stripped = response.strip()

        # Validate checksum if enabled and response has expected structure
        if self._validate_checksum and len(response_stripped) >= 2:
            if not self._verify_v1_checksum(response_stripped):
                log.warning(
                    "%s: V1 checksum mismatch in '%s' — possible RS-232 corruption",
                    self.name,
                    response_stripped,
                )
                return Reading.now(
                    channel=channel,
                    value=float("nan"),
                    unit="mbar",
                    instrument_id=self.name,
                    status=ChannelStatus.SENSOR_ERROR,
                    raw=None,
                    metadata={"raw_response": response_stripped, "error": "checksum_mismatch"},
                )

        try:
            # Ожидаемый формат: <addr><cmd><6digits><checksum>
            # Например: "001M260017N" → addr="001", cmd="M", value="260017", checksum="N"
            if not response_stripped.startswith(self._address):
                raise ValueError(f"Неверный адрес в ответе: '{response_stripped}'")

            # Пропустить адрес (3 символа) + команду (1 символ)
            payload = response_stripped[len(self._address) + 1 :]

            if len(payload) < 6:
                raise ValueError(f"Слишком короткий payload: '{payload}'")

            # Первые 6 символов: 4 мантисса + 2 экспонента
            value_str = payload[:6]
            mantissa = int(value_str[:4])
            exponent = int(value_str[4:6])
            pressure_mbar = (mantissa / 1000.0) * (10.0 ** (exponent - 20))

        except (ValueError, IndexError) as exc:
            log.error(
                "%s: не удалось разобрать V1 ответ '%s' — %s",
                self.name,
                response_stripped,
                exc,
            )
            return Reading.now(
                channel=channel,
                value=float("nan"),
                unit="mbar",
                instrument_id=self.name,
                status=ChannelStatus.SENSOR_ERROR,
                raw=None,
                metadata={"raw_response": response_stripped},
            )

        return Reading.now(
            channel=channel,
            value=pressure_mbar,
            unit="mbar",
            instrument_id=self.name,
            status=ChannelStatus.OK,
            raw=pressure_mbar,
            metadata={"raw_response": response_stripped, "protocol": "v1"},
        )

    # ------------------------------------------------------------------
    # Mock-режим
    # ------------------------------------------------------------------

    def _mock_readings(self) -> list[Reading]:
        """Сгенерировать реалистичное имитированное давление (~1.5e-6 мбар)."""
        noise = random.uniform(0.8, 1.2)
        drift = math.sin(time.monotonic() * 0.001) * _MOCK_BASE_PRESSURE_MBAR * 0.05
        value = _MOCK_BASE_PRESSURE_MBAR * noise + drift

        return [
            Reading.now(
                channel=f"{self.name}/pressure",
                value=value,
                unit="mbar",
                instrument_id=self.name,
                status=ChannelStatus.OK,
                raw=value,
            )
        ]

exec
/opt/homebrew/bin/bash -lc "sed -n '1,220p' tests/drivers/test_thyracont_checksum_default.py" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
"""Verify Thyracont validate_checksum default (Phase 2c Codex F.2)."""

from __future__ import annotations

from cryodaq.drivers.instruments.thyracont_vsp63d import ThyracontVSP63D


def test_validate_checksum_default_on():
    """Default MUST be True after Phase 2c (was False in earlier releases)."""
    t = ThyracontVSP63D(name="vacuum", resource_str="COM3")
    assert t._validate_checksum is True, (
        "Thyracont checksum validation must default to True. "
        "Operators with known-bad firmware can opt out via instruments.local.yaml."
    )


def test_validate_checksum_can_be_disabled():
    """Explicit opt-out still works for legacy firmware."""
    t = ThyracontVSP63D(name="vacuum", resource_str="COM3", validate_checksum=False)
    assert t._validate_checksum is False

exec
/opt/homebrew/bin/bash -lc "sed -n '1,260p' tests/drivers/test_thyracont_vsp63d.py" in /Users/vladimir/Projects/cryodaq
exec
/opt/homebrew/bin/bash -lc "sed -n '1,220p' src/cryodaq/drivers/base.py" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
"""Базовые классы для драйверов приборов."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class ChannelStatus(Enum):
    """Статус канала измерения."""

    OK = "ok"
    OVERRANGE = "overrange"
    UNDERRANGE = "underrange"
    SENSOR_ERROR = "sensor_error"
    TIMEOUT = "timeout"


@dataclass(frozen=True, slots=True)
class Reading:
    """Единичное измерение с прибора.

    Неизменяемый, легковесный, безопасен для передачи между потоками/процессами.
    """

    timestamp: datetime
    instrument_id: str
    channel: str
    value: float
    unit: str
    status: ChannelStatus = ChannelStatus.OK
    raw: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def now(
        channel: str, value: float, unit: str, *, instrument_id: str = "", **kwargs: Any
    ) -> Reading:
        """Создать Reading с текущим временем UTC."""
        return Reading(
            timestamp=datetime.now(UTC),
            instrument_id=instrument_id,
            channel=channel,
            value=value,
            unit=unit,
            **kwargs,
        )


class InstrumentDriver(ABC):
    """Абстрактный драйвер прибора.

    Контракт:
    - connect/disconnect — управление ресурсом (VISA session, serial port)
    - read_channels — один цикл опроса, возвращает список Reading
    - Все I/O — async, никогда не блокировать event loop
    - mock_mode — работа без реального прибора (для тестов и разработки GUI)
    """

    def __init__(self, name: str, *, mock: bool = False) -> None:
        self.name = name
        self.mock = mock
        self._connected = False
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._connected

    @abstractmethod
    async def connect(self) -> None:
        """Открыть соединение с прибором."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Закрыть соединение. Должен быть идемпотентным."""

    @abstractmethod
    async def read_channels(self) -> list[Reading]:
        """Опросить все каналы. Вернуть список показаний."""

    async def safe_read(self) -> list[Reading]:
        """Потокобезопасный опрос с блокировкой (один запрос за раз)."""
        async with self._lock:
            return await self.read_channels()

    async def __aenter__(self) -> InstrumentDriver:
        await self.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.disconnect()

 succeeded in 0ms:
"""Tests for the Thyracont VSP63D vacuum gauge driver."""

from __future__ import annotations

import math

from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.drivers.instruments.thyracont_vsp63d import _FALLBACK_BAUDRATES, ThyracontVSP63D

# ---------------------------------------------------------------------------
# 1. connect / disconnect lifecycle in mock mode
# ---------------------------------------------------------------------------


async def test_mock_connect_disconnect() -> None:
    driver = ThyracontVSP63D("vsp63d", "COM3", mock=True)

    assert not driver.connected

    await driver.connect()
    assert driver.connected

    await driver.disconnect()
    assert not driver.connected


# ---------------------------------------------------------------------------
# 2. Mock mode returns 1 pressure reading
# ---------------------------------------------------------------------------


async def test_mock_returns_pressure() -> None:
    driver = ThyracontVSP63D("vsp63d", "COM3", mock=True)
    await driver.connect()

    readings = await driver.read_channels()

    assert len(readings) == 1
    r = readings[0]
    assert isinstance(r, Reading)
    assert r.unit == "mbar"
    assert r.status == ChannelStatus.OK
    assert r.channel == "vsp63d/pressure"

    await driver.disconnect()


# ---------------------------------------------------------------------------
# 3. Mock pressure is in realistic range
# ---------------------------------------------------------------------------


async def test_mock_pressure_range() -> None:
    driver = ThyracontVSP63D("vsp63d", "COM3", mock=True)
    await driver.connect()

    readings = await driver.read_channels()
    value = readings[0].value

    # Base ~1.5e-6, with noise ±20% and small drift
    assert 1e-8 < value < 1e-4, f"Mock pressure {value} mbar out of range"

    await driver.disconnect()


# ---------------------------------------------------------------------------
# 4. Parse OK response
# ---------------------------------------------------------------------------


async def test_parse_ok_response() -> None:
    driver = ThyracontVSP63D("vsp63d", "COM3", mock=True)

    reading = driver._parse_response("0,1.234E-06\r")

    assert reading.status == ChannelStatus.OK
    assert math.isclose(reading.value, 1.234e-6, rel_tol=1e-4)
    assert reading.unit == "mbar"


# ---------------------------------------------------------------------------
# 5. Parse overrange response
# ---------------------------------------------------------------------------


async def test_parse_overrange() -> None:
    driver = ThyracontVSP63D("vsp63d", "COM3", mock=True)

    reading = driver._parse_response("2,1.000E+03\r")

    assert reading.status == ChannelStatus.OVERRANGE
    assert math.isclose(reading.value, 1000.0, rel_tol=1e-4)


# ---------------------------------------------------------------------------
# 6. Parse underrange response
# ---------------------------------------------------------------------------


async def test_parse_underrange() -> None:
    driver = ThyracontVSP63D("vsp63d", "COM3", mock=True)

    reading = driver._parse_response("1,0.000E+00\r")

    assert reading.status == ChannelStatus.UNDERRANGE
    assert reading.value == 0.0


# ---------------------------------------------------------------------------
# 7. Parse sensor error response
# ---------------------------------------------------------------------------


async def test_parse_sensor_error() -> None:
    driver = ThyracontVSP63D("vsp63d", "COM3", mock=True)

    reading = driver._parse_response("3,0.000E+00\r")

    assert reading.status == ChannelStatus.SENSOR_ERROR


# ---------------------------------------------------------------------------
# 8. Reconnect after disconnect
# ---------------------------------------------------------------------------


async def test_reconnect_after_disconnect() -> None:
    driver = ThyracontVSP63D("vsp63d", "COM3", mock=True)

    await driver.connect()
    assert driver.connected

    await driver.disconnect()
    assert not driver.connected

    await driver.connect()
    assert driver.connected

    readings = await driver.read_channels()
    assert len(readings) == 1

    await driver.disconnect()


# ---------------------------------------------------------------------------
# 9. Parse Protocol V1 — vacuum: "001M260017N" → (2600/1000)*10^(17-20) = 2.6e-3 mbar
# ---------------------------------------------------------------------------


async def test_thyracont_parse_pressure() -> None:
    """Protocol V1: '001M260017N' → mantissa=2600, exp=17 → 2.6e-3 mbar.

    These hard-coded fixture strings predate Phase 2c F.2 (default flip
    of validate_checksum to True). They test the *parser*, not the
    checksum validator, so explicit opt-out is correct.
    """
    driver = ThyracontVSP63D(
        "vsm77dl", "COM3", mock=True, baudrate=115200, address="001", validate_checksum=False
    )

    reading = driver._parse_v1_response("001M260017N\r")

    assert reading.status == ChannelStatus.OK
    assert math.isclose(reading.value, 2.6e-3, rel_tol=1e-4)
    assert reading.unit == "mbar"


# ---------------------------------------------------------------------------
# 10. Parse Protocol V1 — atmosphere: "001M100023D" → (1000/1000)*10^(23-20) = 1000 mbar
# ---------------------------------------------------------------------------


async def test_thyracont_parse_high_pressure() -> None:
    """Protocol V1: '001M100023D' → mantissa=1000, exp=23 → 1000 mbar."""
    driver = ThyracontVSP63D("vsm77dl", "COM3", mock=True, address="001", validate_checksum=False)

    reading = driver._parse_v1_response("001M100023D\r")

    assert reading.status == ChannelStatus.OK
    assert math.isclose(reading.value, 1000.0, rel_tol=1e-4)


# ---------------------------------------------------------------------------
# 11. Parse Protocol V1 — "001M400016O" → (4000/1000)*10^(16-20) = 4.0e-4 mbar
# ---------------------------------------------------------------------------


async def test_parse_v1_response_very_high_pressure() -> None:
    """Protocol V1: '001M400016O' → mantissa=4000, exp=16 → 4.0e-4 mbar."""
    driver = ThyracontVSP63D("vsm77dl", "COM3", mock=True, address="001", validate_checksum=False)

    reading = driver._parse_v1_response("001M400016O\r")

    assert reading.status == ChannelStatus.OK
    assert math.isclose(reading.value, 4.0e-4, rel_tol=1e-4)


# ---------------------------------------------------------------------------
# 14. Parse Protocol V1 — good vacuum: "001M100014X" → (1000/1000)*10^(14-20) = 1e-6 mbar
# ---------------------------------------------------------------------------


async def test_parse_v1_good_vacuum() -> None:
    """Protocol V1: '001M100014X' → mantissa=1000, exp=14 → 1e-6 mbar."""
    driver = ThyracontVSP63D("vsm77dl", "COM3", mock=True, address="001", validate_checksum=False)

    reading = driver._parse_v1_response("001M100014X\r")

    assert reading.status == ChannelStatus.OK
    assert math.isclose(reading.value, 1e-6, rel_tol=1e-4)


# ---------------------------------------------------------------------------
# 12. Parse Protocol V1 — invalid response
# ---------------------------------------------------------------------------


async def test_parse_v1_response_invalid() -> None:
    """Protocol V1: garbage response → SENSOR_ERROR + NaN."""
    driver = ThyracontVSP63D("vsm77dl", "COM3", mock=True, address="001")

    reading = driver._parse_v1_response("GARBAGE\r")

    assert reading.status == ChannelStatus.SENSOR_ERROR
    assert math.isnan(reading.value)


# ---------------------------------------------------------------------------
# 13. Connect via V1 protocol probe (mock transport)
# ---------------------------------------------------------------------------


async def test_thyracont_connect_v1() -> None:
    """connect() sends '001M^' and gets '001M100023D\\r' → connected via V1."""
    driver = ThyracontVSP63D("vsm77dl", "COM3", mock=True, baudrate=115200, address="001")

    await driver.connect()

    assert driver.connected
    assert driver._protocol_v1 is True
    assert driver._instrument_id == "Thyracont-V1@001"

    await driver.disconnect()


# ---------------------------------------------------------------------------
# 15. Fallback baudrate mapping
# ---------------------------------------------------------------------------


def test_fallback_baudrates_mapping() -> None:
    """Verify known fallback baudrate pairs."""
    assert _FALLBACK_BAUDRATES[9600] == 115200
    assert _FALLBACK_BAUDRATES[115200] == 9600
    assert _FALLBACK_BAUDRATES.get(19200) is None


# ---------------------------------------------------------------------------
# 16. Connect with fallback baudrate (mock)
# ---------------------------------------------------------------------------

exec
/opt/homebrew/bin/bash -lc "sed -n '260,560p' tests/drivers/test_thyracont_vsp63d.py" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
# ---------------------------------------------------------------------------


async def test_connect_fallback_baudrate() -> None:
    """When primary baudrate is 9600 in mock mode, connection still succeeds."""
    driver = ThyracontVSP63D("vsp63d", "COM3", baudrate=9600, mock=True)
    await driver.connect()
    assert driver.connected
    await driver.disconnect()


# ---------------------------------------------------------------------------
# 17. Connect preserves original baudrate on success
# ---------------------------------------------------------------------------


async def test_connect_preserves_original_baudrate_on_success() -> None:
    """When primary baudrate probe succeeds, no fallback is attempted."""
    driver = ThyracontVSP63D("vsp63d", "COM3", baudrate=115200, mock=True)
    await driver.connect()
    assert driver.connected
    assert driver._protocol_v1 is True
    await driver.disconnect()

exec
/opt/homebrew/bin/bash -lc "sed -n '1,260p' src/cryodaq/drivers/transport/serial.py" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
"""Асинхронная обёртка над pyserial-asyncio для последовательной коммуникации (RS-232/USB-Serial)."""  # noqa: E501

from __future__ import annotations

import asyncio
import logging

log = logging.getLogger(__name__)

# Таймаут чтения по умолчанию (секунды).  Если прибор не отвечает за это
# время, read_line() бросает asyncio.TimeoutError вместо вечного зависания.
_DEFAULT_READ_TIMEOUT_S: float = 3.0

# Mock-ответы для известных команд
_MOCK_IDN = "Thyracont,VSP63D,MOCK001,1.0"
_MOCK_PRESSURE_RESPONSE = "0,1.234E-06\r"


class SerialTransport:
    """Асинхронный транспорт RS-232/USB-Serial на основе pyserial-asyncio.

    Все I/O-операции неблокирующие: используется asyncio StreamReader/StreamWriter
    через ``serial_asyncio.open_serial_connection``.

    Parameters
    ----------
    mock:
        Если ``True`` — работает без реального порта, возвращает
        предопределённые ответы.
    """

    def __init__(self, *, mock: bool = False) -> None:
        self.mock = mock
        self._reader = None
        self._writer = None
        self._resource_str: str = ""
        self._read_timeout_s: float = _DEFAULT_READ_TIMEOUT_S

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    async def open(self, port: str, baudrate: int = 9600, timeout: float = 2.0) -> None:  # noqa: ASYNC109
        """Открыть последовательный порт.

        Parameters
        ----------
        port:
            Имя порта, например ``"COM3"`` или ``"/dev/ttyUSB0"``.
        baudrate:
            Скорость обмена в бодах (по умолчанию 9600).
        timeout:
            Таймаут чтения в секундах (по умолчанию 2.0).
        """
        self._resource_str = port
        self._read_timeout_s = timeout

        if self.mock:
            log.info("Serial [mock]: имитация открытия порта %s @ %d бод", port, baudrate)
            return

        try:
            import serial_asyncio  # type: ignore[import]

            self._reader, self._writer = await serial_asyncio.open_serial_connection(
                url=port, baudrate=baudrate
            )
            log.info("Serial: порт %s @ %d бод успешно открыт", port, baudrate)
        except Exception as exc:
            log.error("Serial: ошибка открытия порта %s — %s", port, exc)
            raise

    async def close(self) -> None:
        """Закрыть соединение (идемпотентно)."""
        if self.mock:
            log.info("Serial [mock]: имитация закрытия порта %s", self._resource_str)
            return

        if self._writer is None:
            return

        try:
            self._writer.close()
            await self._writer.wait_closed()
            log.info("Serial: порт %s закрыт", self._resource_str)
        except Exception as exc:
            log.warning("Serial: ошибка при закрытии порта %s — %s", self._resource_str, exc)
        finally:
            self._reader = None
            self._writer = None

    async def query(self, command: str, *, terminator: str = "\r") -> str:
        """Отправить команду и вернуть ответ прибора.

        Parameters
        ----------
        command:
            Команда для отправки (без терминатора).
        terminator:
            Символ-терминатор (по умолчанию ``"\\r"``).

        Returns
        -------
        str
            Ответ прибора (с терминатором, без дополнительной очистки).
        """
        if self.mock:
            response = self._mock_response(command)
            log.debug("Serial [mock] query '%s' → '%s'", command, response.strip())
            return response

        await self.write(command, terminator=terminator)
        return await self.read_line(terminator=terminator)

    async def write(self, data: str, *, terminator: str = "\r") -> None:
        """Отправить данные в порт.

        Parameters
        ----------
        data:
            Строка для отправки (без терминатора).
        terminator:
            Символ-терминатор (по умолчанию ``"\\r"``).
        """
        if self.mock:
            log.debug("Serial [mock] write: %s", data)
            return

        if self._writer is None:
            raise RuntimeError("Serial: порт не открыт")

        payload = (data + terminator).encode()
        self._writer.write(payload)
        await self._writer.drain()
        log.debug("Serial write → %s: %s", self._resource_str, data)

    async def read_line(self, *, terminator: str = "\r", timeout: float | None = None) -> str:  # noqa: ASYNC109
        """Читать байты из порта до терминатора.

        Parameters
        ----------
        terminator:
            Символ-терминатор (по умолчанию ``"\\r"``).
        timeout:
            Таймаут чтения в секундах (``None`` → использует значение из ``open()``).

        Returns
        -------
        str
            Прочитанная строка, включая терминатор.

        Raises
        ------
        asyncio.TimeoutError
            Если прибор не ответил за отведённое время.
        """
        if self.mock:
            return _MOCK_PRESSURE_RESPONSE

        if self._reader is None:
            raise RuntimeError("Serial: порт не открыт")

        effective_timeout = timeout if timeout is not None else self._read_timeout_s
        data = await asyncio.wait_for(
            self._reader.readuntil(terminator.encode()),
            timeout=effective_timeout,
        )
        return data.decode(errors="replace")

    async def flush_input(self) -> None:
        """Очистить входной буфер (сбросить незапрошенные данные).

        Полезно между probe-запросами в connect(), когда предыдущая попытка
        могла оставить мусор в буфере.
        """
        if self.mock or self._reader is None:
            return
        try:
            # Прочитать всё, что есть в буфере, с минимальным таймаутом
            while True:
                await asyncio.wait_for(self._reader.read(4096), timeout=0.1)
        except TimeoutError:
            pass
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Mock-утилиты
    # ------------------------------------------------------------------

    @staticmethod
    def _mock_response(command: str) -> str:
        """Сформировать имитированный ответ для известных команд."""
        cmd_stripped = command.strip()
        cmd_upper = cmd_stripped.upper()
        if cmd_upper in ("*IDN?", "IDN?"):
            return _MOCK_IDN
        if cmd_upper.startswith("MV"):
            return _MOCK_PRESSURE_RESPONSE
        # Protocol V1: "<addr>M^" → "<addr>M<5digits><checksum>\r"
        if len(cmd_stripped) >= 5 and cmd_stripped[3] == "M":
            addr = cmd_stripped[:3]
            return f"{addr}M100023D\r"
        return "\r"

exec
/opt/homebrew/bin/bash -lc 'rg -n "validate_checksum|checksum|VSP206|probe|SafetyManager|fail-closed|fail closed|fail_closed" HANDOFF_2026-04-20_GLM.md src tests config' in /Users/vladimir/Projects/cryodaq
exec
/opt/homebrew/bin/bash -lc 'git show --stat --oneline 8605a52f -- src/cryodaq/drivers/instruments/thyracont_vsp63d.py && git show --stat --oneline a2f4bcd0 -- src/cryodaq/drivers/instruments/thyracont_vsp63d.py && git show --stat --oneline aabd75f -- src/cryodaq/drivers/instruments/thyracont_vsp63d.py' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
8605a52 fix: thyracont VSP63D connect via V1 protocol probe instead of SCPI *IDN?
 .../drivers/instruments/thyracont_vsp63d.py        | 85 ++++++++++------------
 1 file changed, 37 insertions(+), 48 deletions(-)
a2f4bcd fix(safety): Thyracont MV00 fallback, SQLite read/write split, SafetyManager transition, Keithley disconnect
 .../drivers/instruments/thyracont_vsp63d.py        | 66 ++++++++++++++--------
 1 file changed, 41 insertions(+), 25 deletions(-)

 succeeded in 0ms:
HANDOFF_2026-04-20_GLM.md:60:| `aabd75f` | engine: wire validate_checksum through Thyracont driver loader | ✅ verified fixes pressure display |
HANDOFF_2026-04-20_GLM.md:125:1. **`instruments.local.yaml`** — added `validate_checksum: false` to
HANDOFF_2026-04-20_GLM.md:127:   because lab hardware is VSP206, not VSP63D — different checksum
HANDOFF_2026-04-20_GLM.md:182:   - `validate_checksum` YAML key was never wired through the driver
HANDOFF_2026-04-20_GLM.md:184:   - Driver default flipped to `True` in Phase 2c Codex F.2, but VSP206
HANDOFF_2026-04-20_GLM.md:185:     has different checksum formula than VSP63D → opt-out needed for
HANDOFF_2026-04-20_GLM.md:188:     Config-side `validate_checksum: false` is the operational escape
HANDOFF_2026-04-20_GLM.md:289:2. **Thyracont `_try_v1_probe` checksum inconsistency.** Probe at
HANDOFF_2026-04-20_GLM.md:292:   validate checksum even when `self._validate_checksum=True`.
HANDOFF_2026-04-20_GLM.md:296:   we route around it via `validate_checksum: false`, but the
HANDOFF_2026-04-20_GLM.md:297:   proper hardening is to make probe consistent with read path. ~5
HANDOFF_2026-04-20_GLM.md:370:watchdog cooldown, `validate_checksum` wiring) correctly skipped
HANDOFF_2026-04-20_GLM.md:448:| VSP63D_1 (serial /dev/ttyUSB0) | ✅ Connected | Actually VSP206 hardware; `validate_checksum: false` in local config |
HANDOFF_2026-04-20_GLM.md:466:aabd75f engine: wire validate_checksum through Thyracont driver loader
HANDOFF_2026-04-20_GLM.md:574:# Pressure reading probe (30 s)
src/cryodaq/launcher.py:326:            probe_fd = None
src/cryodaq/launcher.py:328:                probe_fd = os.open(str(lock_path), os.O_RDWR)
src/cryodaq/launcher.py:332:                    msvcrt.locking(probe_fd, msvcrt.LK_NBLCK, 1)
src/cryodaq/launcher.py:333:                    msvcrt.locking(probe_fd, msvcrt.LK_UNLCK, 1)
src/cryodaq/launcher.py:337:                    fcntl.flock(probe_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
src/cryodaq/launcher.py:338:                    fcntl.flock(probe_fd, fcntl.LOCK_UN)
src/cryodaq/launcher.py:343:                if probe_fd is not None:
src/cryodaq/launcher.py:345:                        os.close(probe_fd)
src/cryodaq/launcher.py:348:                    probe_fd = None
src/cryodaq/launcher.py:359:                if probe_fd is not None:
src/cryodaq/launcher.py:361:                        os.close(probe_fd)
tests/drivers/test_thyracont_checksum_default.py:1:"""Verify Thyracont validate_checksum default (Phase 2c Codex F.2)."""
tests/drivers/test_thyracont_checksum_default.py:8:def test_validate_checksum_default_on():
tests/drivers/test_thyracont_checksum_default.py:11:    assert t._validate_checksum is True, (
tests/drivers/test_thyracont_checksum_default.py:12:        "Thyracont checksum validation must default to True. "
tests/drivers/test_thyracont_checksum_default.py:17:def test_validate_checksum_can_be_disabled():
tests/drivers/test_thyracont_checksum_default.py:19:    t = ThyracontVSP63D(name="vacuum", resource_str="COM3", validate_checksum=False)
tests/drivers/test_thyracont_checksum_default.py:20:    assert t._validate_checksum is False
tests/core/test_p0_fixes.py:4:P0-02: SafetyManager publishes state as Reading to DataBroker
tests/core/test_p0_fixes.py:5:P0-03: SafetyManager.request_run validates source parameter limits
tests/core/test_p0_fixes.py:6:P0-04: SafetyManager.emergency_off returns latched flag when FAULT_LATCHED
tests/core/test_p0_fixes.py:19:from cryodaq.core.safety_manager import SafetyManager, SafetyState
tests/core/test_p0_fixes.py:41:    mgr = SafetyManager(sb, keithley_driver=keithley, mock=mock, data_broker=data_broker)
tests/core/test_p0_fixes.py:374:# P0-02: SafetyManager publishes state as Reading to DataBroker
tests/core/test_p0_fixes.py:379:    """SafetyManager publishes analytics/safety_state with state='safe_off' on start."""
tests/core/test_p0_fixes.py:400:    """SafetyManager publishes analytics/safety_state when transitioning to RUNNING."""
tests/core/test_p0_fixes.py:428:    """SafetyManager must not crash if data_broker.publish raises an exception."""
tests/core/test_p0_fixes.py:447:# P0-03: SafetyManager.request_run validates source parameter limits
tests/core/test_p0_fixes.py:454:    """Create a SafetyManager in READY state with source limits configured."""
tests/core/test_safety_set_target.py:1:"""Tests for SafetyManager.update_target() and update_limits()."""
tests/core/test_safety_set_target.py:6:from cryodaq.core.safety_manager import SafetyManager, SafetyState
tests/core/test_safety_set_target.py:10:async def _make_running(sm: SafetyManager, channel: str = "smua") -> None:
tests/core/test_safety_set_target.py:11:    """Helper: bring SafetyManager to RUNNING with an active channel."""
tests/core/test_safety_set_target.py:25:    sm = SafetyManager(broker, keithley_driver=k, mock=True)
tests/core/test_safety_set_target.py:40:    sm = SafetyManager(broker, keithley_driver=k, mock=True)
tests/core/test_safety_set_target.py:54:    sm = SafetyManager(broker, keithley_driver=k, mock=True)
tests/core/test_safety_set_target.py:67:    sm = SafetyManager(broker, keithley_driver=k, mock=True)
tests/core/test_safety_set_target.py:85:    sm = SafetyManager(broker, keithley_driver=k, mock=True)
tests/core/test_safety_set_target.py:104:    sm = SafetyManager(broker, keithley_driver=k, mock=True)
tests/core/test_safety_set_target.py:119:    sm = SafetyManager(broker, keithley_driver=k, mock=True)
tests/core/test_safety_set_target.py:134:    sm = SafetyManager(broker, keithley_driver=k, mock=True)
tests/core/test_safety_set_target.py:148:    sm = SafetyManager(broker, keithley_driver=k, mock=True)
tests/storage/test_disk_full_handling.py:112:    """SafetyManager.on_persistence_failure must transition to FAULT_LATCHED."""
tests/storage/test_disk_full_handling.py:114:    from cryodaq.core.safety_manager import SafetyManager, SafetyState
tests/storage/test_disk_full_handling.py:120:    mgr = SafetyManager(safety_broker, keithley_driver=keithley, mock=True)
tests/storage/test_disk_full_handling.py:168:    """SafetyManager.acknowledge_fault must clear the writer flag via callback."""
tests/storage/test_disk_full_handling.py:170:    from cryodaq.core.safety_manager import SafetyManager, SafetyState
tests/storage/test_disk_full_handling.py:175:    mgr = SafetyManager(safety_broker, keithley_driver=keithley, mock=True)
tests/core/test_p1_fixes.py:3:P1-03: SafetyManager heartbeat rejects SENSOR_ERROR readings; keithley channel
tests/core/test_p1_fixes.py:24:from cryodaq.core.safety_manager import SafetyManager, SafetyState
tests/core/test_p1_fixes.py:44:    """Create and start a SafetyManager in the standard test configuration."""
tests/core/test_p1_fixes.py:46:    mgr = SafetyManager(broker, keithley_driver=keithley, mock=mock)
tests/core/test_p1_fixes.py:67:async def _get_to_running(mgr: SafetyManager, broker: SafetyBroker) -> None:
tests/core/test_p1_fixes.py:68:    """Drive SafetyManager into RUNNING state (mock mode, no critical channels)."""
src/cryodaq/gui/widgets/overview_panel.py:166:        # SafetyManager state
tests/drivers/test_thyracont_vsp63d.py:154:    of validate_checksum to True). They test the *parser*, not the
tests/drivers/test_thyracont_vsp63d.py:155:    checksum validator, so explicit opt-out is correct.
tests/drivers/test_thyracont_vsp63d.py:158:        "vsm77dl", "COM3", mock=True, baudrate=115200, address="001", validate_checksum=False
tests/drivers/test_thyracont_vsp63d.py:175:    driver = ThyracontVSP63D("vsm77dl", "COM3", mock=True, address="001", validate_checksum=False)
tests/drivers/test_thyracont_vsp63d.py:190:    driver = ThyracontVSP63D("vsm77dl", "COM3", mock=True, address="001", validate_checksum=False)
tests/drivers/test_thyracont_vsp63d.py:205:    driver = ThyracontVSP63D("vsm77dl", "COM3", mock=True, address="001", validate_checksum=False)
tests/drivers/test_thyracont_vsp63d.py:229:# 13. Connect via V1 protocol probe (mock transport)
tests/drivers/test_thyracont_vsp63d.py:277:    """When primary baudrate probe succeeds, no fallback is attempted."""
src/cryodaq/storage/sqlite_writer.py:159:        # engine event loop via run_coroutine_threadsafe so the SafetyManager
src/cryodaq/storage/sqlite_writer.py:184:        Note: this does NOT auto-resume polling — the SafetyManager has
src/cryodaq/storage/sqlite_writer.py:191:                "SafetyManager fault remains latched until operator acknowledge."
src/cryodaq/storage/sqlite_writer.py:205:        SafetyManager.on_persistence_failure can latch a fault.
tests/core/test_safety_rate_estimator_config.py:1:"""Verify SafetyManager uses min_points >= 60 for the rate estimator
tests/core/test_safety_rate_estimator_config.py:7:from cryodaq.core.safety_manager import SafetyManager
tests/core/test_safety_rate_estimator_config.py:13:    SafetyManager value from 10 to 60 to close the documented gap."""
tests/core/test_safety_rate_estimator_config.py:15:    mgr = SafetyManager(safety_broker, keithley_driver=None, mock=True)
tests/core/test_safety_rate_estimator_config.py:17:        f"SafetyManager rate estimator min_points="
tests/core/test_interlock.py:461:# Phase 2d C-1.1: fail-closed interlock loading
tests/core/test_safety_dual_channel.py:7:from cryodaq.core.safety_manager import SafetyManager, SafetyState
tests/core/test_safety_dual_channel.py:22:    manager = SafetyManager(broker, keithley_driver=keithley, mock=mock)
tests/core/test_housekeeping.py:204:# Phase 2d C-1.2: fail-closed housekeeping loading
tests/core/test_interlock_action_dispatch.py:7:context to ``SafetyManager.on_interlock_trip(action=...)``, which
tests/core/test_interlock_action_dispatch.py:19:from cryodaq.core.safety_manager import SafetyManager, SafetyState
tests/core/test_interlock_action_dispatch.py:30:    m = SafetyManager(safety_broker, keithley_driver=keithley, mock=True)
tests/core/test_safety_fixes.py:1:"""Tests for SafetyManager safety fixes.
tests/core/test_safety_fixes.py:22:from cryodaq.core.safety_manager import SafetyManager, SafetyState
tests/core/test_safety_fixes.py:41:    mgr = SafetyManager(broker, keithley_driver=keithley, mock=mock)
tests/core/test_safety_fixes.py:274:        # Phase 2c CC I.3: SafetyManager rate estimator now requires >=60
tests/core/test_safety_fixes.py:370:# RateEstimator integration — verify SafetyManager uses RateEstimator
tests/core/test_safety_fixes.py:375:    """SafetyManager uses RateEstimator instead of raw _rate_buffers."""
tests/core/test_safety_fixes.py:379:            "SafetyManager should use RateEstimator, not raw _rate_buffers"
tests/core/test_safety_fixes.py:382:            "SafetyManager should have _rate_estimator attribute"
tests/core/test_keithley_channel_state_publish.py:7:from cryodaq.core.safety_manager import SafetyManager
tests/core/test_keithley_channel_state_publish.py:13:    manager = SafetyManager(safety_broker, mock=True, data_broker=data_broker)
tests/gui/shell/test_main_window_v2_alarms_wiring.py:74:        # without raising. Most reliable probe: verify the panel is the
src/cryodaq/core/channel_manager.py:22:    """Raised when channels.yaml cannot be loaded in a fail-closed manner."""
src/cryodaq/core/scheduler.py:351:        # and SafetyManager has already latched a fault via the writer's
tests/core/test_safety_manager.py:1:"""Tests for SafetyManager — safety-critical state machine."""
tests/core/test_safety_manager.py:12:from cryodaq.core.safety_manager import SafetyConfigError, SafetyManager, SafetyState
tests/core/test_safety_manager.py:27:    """Create and start a SafetyManager with SafetyBroker."""
tests/core/test_safety_manager.py:29:    mgr = SafetyManager(broker, keithley_driver=keithley, mock=mock)
tests/core/test_safety_manager.py:250:    mgr = SafetyManager(broker, keithley_driver=None, mock=True)
tests/core/test_safety_manager.py:278:    mgr = SafetyManager(broker, keithley_driver=None, mock=False)
tests/core/test_safety_manager.py:323:# 15. Interlock trip goes through SafetyManager
tests/core/test_safety_manager.py:363:    sm = SafetyManager(broker, keithley_driver=k, mock=True)
tests/core/test_safety_manager.py:391:    sm = SafetyManager(broker, keithley_driver=None, mock=True)
tests/core/test_safety_manager.py:409:    sm = SafetyManager(SafetyBroker(), mock=True)
tests/core/test_safety_manager.py:418:    sm = SafetyManager(SafetyBroker(), mock=True)
tests/core/test_safety_manager.py:427:    sm = SafetyManager(SafetyBroker(), mock=True)
tests/core/test_safety_manager.py:442:    sm = SafetyManager(SafetyBroker(), mock=True)
tests/core/test_safety_manager.py:459:    sm = SafetyManager(SafetyBroker(), mock=True)
tests/core/test_safety_manager.py:468:    sm = SafetyManager(SafetyBroker(), mock=True)
tests/core/test_safety_manager.py:477:    sm = SafetyManager(SafetyBroker(), mock=True)
tests/core/test_safety_manager.py:486:    sm = SafetyManager(SafetyBroker(), mock=True)
tests/core/test_safety_manager.py:495:    sm = SafetyManager(SafetyBroker(), mock=True)
tests/core/test_safety_manager.py:508:    sm = SafetyManager(broker, mock=True, fault_log_callback=fake_log_callback)
tests/core/test_safety_manager.py:525:    sm = SafetyManager(broker, mock=True, fault_log_callback=broken_callback)
tests/core/test_safety_manager.py:534:    sm = SafetyManager(broker, mock=True)  # no callback
tests/core/test_safety_manager.py:547:    sm = SafetyManager(broker, keithley_driver=k, mock=False)
tests/core/test_safety_manager.py:584:    sm = SafetyManager(broker, mock=True, fault_log_callback=slow_callback)
tests/core/test_safety_manager.py:617:    sm = SafetyManager(broker, keithley_driver=k, mock=True)
tests/core/test_safety_manager.py:651:    sm = SafetyManager(broker, mock=True, fault_log_callback=log_callback)
tests/core/test_safety_manager.py:675:    sm = SafetyManager(broker, mock=True, fault_log_callback=log_callback)
src/cryodaq/core/alarm_config.py:19:    """Raised when alarms_v3.yaml cannot be loaded in a fail-closed manner.
src/cryodaq/core/interlock.py:35:    """Raised when interlocks.yaml cannot be loaded in a fail-closed manner."""
src/cryodaq/core/interlock.py:183:            actions-dict callable. Used by SafetyManager wiring (Phase 2a
src/cryodaq/core/interlock.py:469:        # context. SafetyManager uses this to differentiate "stop_source"
src/cryodaq/core/disk_monitor.py:102:        # SafetyManager.acknowledge_fault() so the operator stays in the
src/cryodaq/core/safety_manager.py:1:"""SafetyManager for CryoDAQ."""
src/cryodaq/core/safety_manager.py:32:    """Raised when safety.yaml cannot be loaded in a fail-closed manner.
src/cryodaq/core/safety_manager.py:76:class SafetyManager:
src/cryodaq/core/safety_manager.py:140:                f"SafetyManager without safety configuration"
src/cryodaq/core/safety_manager.py:160:                f"refusing to start SafetyManager without critical channel monitoring"
src/cryodaq/core/safety_manager.py:183:            "SafetyManager config: %d critical channel patterns from %s",
src/cryodaq/core/housekeeping.py:22:    """Raised when housekeeping.yaml cannot be loaded in a fail-closed manner."""
src/cryodaq/engine.py:61:from cryodaq.core.safety_manager import SafetyConfigError, SafetyManager
src/cryodaq/engine.py:94:    safety_manager: SafetyManager,
src/cryodaq/engine.py:96:    """Dispatch channel-scoped Keithley commands to SafetyManager."""
src/cryodaq/engine.py:766:            validate_checksum = bool(entry.get("validate_checksum", True))
src/cryodaq/engine.py:767:            driver = ThyracontVSP63D(name, resource, baudrate=baudrate, validate_checksum=validate_checksum, mock=mock)
src/cryodaq/engine.py:865:    # Keithley driver (нужен для SafetyManager)
src/cryodaq/engine.py:872:    # SafetyManager — создаётся ПЕРВЫМ
src/cryodaq/engine.py:874:    safety_manager = SafetyManager(
src/cryodaq/engine.py:906:    # engine event loop and SafetyManager so a disk-full error in the
src/cryodaq/engine.py:966:    # Interlock Engine — действия делегируются SafetyManager.
src/cryodaq/engine.py:982:        # so this handler is the SOLE path that triggers a SafetyManager
src/cryodaq/engine.py:1224:    # Обработчик команд от GUI — через SafetyManager
src/cryodaq/engine.py:1594:    logger.info("SafetyManager запущен: состояние=%s", safety_manager.state.value)
src/cryodaq/engine.py:1741:    logger.info("SafetyManager остановлен: состояние=%s", safety_manager.state.value)
src/cryodaq/core/safety_broker.py:4:- Прямая доставка от Scheduler к SafetyManager
src/cryodaq/core/safety_broker.py:78:        """Установить callback на переполнение (вызывает FAULT в SafetyManager)."""
src/cryodaq/drivers/instruments/keithley_2604b.py:30:# Number of consecutive compliance cycles before notifying SafetyManager.
src/cryodaq/drivers/instruments/thyracont_vsp63d.py:47:      Команда: ``"<addr>M^\\r"`` → ответ: ``"<addr>M<6digits><checksum>\\r"``
src/cryodaq/drivers/instruments/thyracont_vsp63d.py:81:        # `validate_checksum: false` in instruments.local.yaml.
src/cryodaq/drivers/instruments/thyracont_vsp63d.py:82:        validate_checksum: bool = True,
src/cryodaq/drivers/instruments/thyracont_vsp63d.py:91:        self._validate_checksum: bool = validate_checksum
src/cryodaq/drivers/instruments/thyracont_vsp63d.py:121:            if await self._try_v1_probe():
src/cryodaq/drivers/instruments/thyracont_vsp63d.py:137:            if await self._try_mv00_probe():
src/cryodaq/drivers/instruments/thyracont_vsp63d.py:157:    async def _try_v1_probe(self) -> bool:
src/cryodaq/drivers/instruments/thyracont_vsp63d.py:158:        """Attempt Protocol V1 probe. Returns True on success."""
src/cryodaq/drivers/instruments/thyracont_vsp63d.py:167:                    log.debug("%s: V1 probe OK (attempt %d)", self.name, attempt + 1)
src/cryodaq/drivers/instruments/thyracont_vsp63d.py:170:                log.debug("%s: V1 probe attempt %d failed: %s", self.name, attempt + 1, exc)
src/cryodaq/drivers/instruments/thyracont_vsp63d.py:173:    async def _try_mv00_probe(self) -> bool:
src/cryodaq/drivers/instruments/thyracont_vsp63d.py:174:        """Attempt MV00 protocol probe. Returns True on success."""
src/cryodaq/drivers/instruments/thyracont_vsp63d.py:181:                log.debug("%s: MV00 probe OK: %s", self.name, resp_stripped)
src/cryodaq/drivers/instruments/thyracont_vsp63d.py:184:            log.debug("%s: MV00 probe failed: %s", self.name, exc)
src/cryodaq/drivers/instruments/thyracont_vsp63d.py:299:    def _verify_v1_checksum(response: str) -> bool:
src/cryodaq/drivers/instruments/thyracont_vsp63d.py:300:        """Verify Thyracont Protocol V1 checksum.
src/cryodaq/drivers/instruments/thyracont_vsp63d.py:302:        Format: <payload><checksum_char>
src/cryodaq/drivers/instruments/thyracont_vsp63d.py:318:        Формат: ``"<addr>M<6digits><checksum>\\r"``, например ``"001M260017N\\r"``.
src/cryodaq/drivers/instruments/thyracont_vsp63d.py:343:        # Validate checksum if enabled and response has expected structure
src/cryodaq/drivers/instruments/thyracont_vsp63d.py:344:        if self._validate_checksum and len(response_stripped) >= 2:
src/cryodaq/drivers/instruments/thyracont_vsp63d.py:345:            if not self._verify_v1_checksum(response_stripped):
src/cryodaq/drivers/instruments/thyracont_vsp63d.py:347:                    "%s: V1 checksum mismatch in '%s' — possible RS-232 corruption",
src/cryodaq/drivers/instruments/thyracont_vsp63d.py:358:                    metadata={"raw_response": response_stripped, "error": "checksum_mismatch"},
src/cryodaq/drivers/instruments/thyracont_vsp63d.py:362:            # Ожидаемый формат: <addr><cmd><6digits><checksum>
src/cryodaq/drivers/instruments/thyracont_vsp63d.py:363:            # Например: "001M260017N" → addr="001", cmd="M", value="260017", checksum="N"
tests/core/test_audit_fixes.py:22:    from cryodaq.core.safety_manager import SafetyManager, SafetyState
tests/core/test_audit_fixes.py:28:    sm = SafetyManager(broker, keithley_driver=k, mock=True)
tests/core/test_audit_fixes.py:71:    from cryodaq.core.safety_manager import SafetyManager, SafetyState
tests/core/test_audit_fixes.py:77:    sm = SafetyManager(broker, keithley_driver=k, mock=True)
src/cryodaq/drivers/transport/serial.py:173:        Полезно между probe-запросами в connect(), когда предыдущая попытка
src/cryodaq/drivers/transport/serial.py:200:        # Protocol V1: "<addr>M^" → "<addr>M<5digits><checksum>\r"

exec
/opt/homebrew/bin/bash -lc 'git log --oneline --decorate -- src/cryodaq/drivers/instruments/thyracont_vsp63d.py tests/drivers/test_thyracont*' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
d8ec668 style: fix 587 ruff lint errors (CI green)
efe6b49 chore: ruff --fix accumulated lint debt
b185fd3 fix: Phase 2c final hardening — close 8 findings before Phase 3
9feaf3e fix: audit - GUI non-blocking send_command + dead code cleanup
a2f4bcd fix(safety): Thyracont MV00 fallback, SQLite read/write split, SafetyManager transition, Keithley disconnect
bbb5809 feat: Phase 3 — safety correctness, reliability, phase detector
f3e62f5 fix: thyracont V1 value is 6 digits (4 mantissa + 2 exponent), formula (ABCD/1000)*10^(EF-20)
d0c40de fix: thyracont V1 pressure formula, keithley output float parse, pressure exponent format
8605a52 fix: thyracont VSP63D connect via V1 protocol probe instead of SCPI *IDN?
d7c843f fix: first hardware deployment — GPIB bus lock, Thyracont V1, Keithley source-off, alarms, pressure card, docs
61dca77 BREAKING: instrument_id is now a first-class field on Reading dataclass
167eb7d Thyracont VSP63D driver, periodic reports, live web dashboard

exec
/opt/homebrew/bin/bash -lc "sed -n '280,305p' HANDOFF_2026-04-20_GLM.md" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   ```
   One of the conditions in `cooldown_stall` composite is missing
   a `threshold` field (probably a stale-type or rate-type condition
   where `threshold` is spurious). Trigger: `ERROR` log spam every
   ~2 s. Engine does NOT crash (caught), but log pollution is
   material. Fix location: `config/alarms_v3.yaml` cooldown_stall
   block OR `alarm_v2._eval_condition` defensive `cond.get("threshold")`
   check. Prefer config fix.

2. **Thyracont `_try_v1_probe` checksum inconsistency.** Probe at
   `src/cryodaq/drivers/instruments/thyracont_vsp63d.py:157-166`
   only checks that response starts with `<addr>M` — does NOT
   validate checksum even when `self._validate_checksum=True`.
   Real read path DOES validate. Result: driver can "successfully
   connect" and then emit NaN-sensor_error on every single read
   forever. This is what bit us this morning. Post-fix operationally
   we route around it via `validate_checksum: false`, but the
   proper hardening is to make probe consistent with read path. ~5
   LOC fix. IV.7 candidate or separate mini-commit.

3. **B1 doc file name is stale.** `docs/bug_B1_zmq_idle_death_handoff.md`
   still carries "idle_death" in the filename despite the hypothesis
   being falsified. I did NOT rename because Vladimir's Rule 20
   ("NEVER delete files") would need explicit rename permission.
   Either leave as-is (the doc top clearly says "revised — not idle
   death") or if Vladimir approves, rename to e.g.

exec
/opt/homebrew/bin/bash -lc "git show -- src/cryodaq/drivers/instruments/thyracont_vsp63d.py | sed -n '1,220p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
exec
/opt/homebrew/bin/bash -lc "git show --oneline --stat b185fd3 -- src/cryodaq/drivers/instruments/thyracont_vsp63d.py tests/drivers/test_thyracont_checksum_default.py && git show -- src/cryodaq/drivers/instruments/thyracont_vsp63d.py | sed -n '1,220p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
b185fd3 fix: Phase 2c final hardening — close 8 findings before Phase 3
 src/cryodaq/drivers/instruments/thyracont_vsp63d.py |  7 ++++++-
 tests/drivers/test_thyracont_checksum_default.py    | 21 +++++++++++++++++++++
 2 files changed, 27 insertions(+), 1 deletion(-)

exec
/opt/homebrew/bin/bash -lc "git show 8605a52f -- src/cryodaq/drivers/instruments/thyracont_vsp63d.py | sed -n '1,220p' && git show a2f4bcd0 -- src/cryodaq/drivers/instruments/thyracont_vsp63d.py | sed -n '1,220p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
commit 8605a52fb6b288d994e5d724a83ccd92d5ebfac3
Author: gaurlleboulledeaux <gaurlleboulledeaux@gmail.com>
Date:   Thu Mar 19 11:14:49 2026 +0300

    fix: thyracont VSP63D connect via V1 protocol probe instead of SCPI *IDN?
    
    The Thyracont VSP63D does not support SCPI — sending *IDN? caused a
    timeout, leaving the driver in a disconnected state with 0 readings.
    Now connect() sends the native V1 measurement command ("001M^\r")
    directly, with up to 3 retries and flush_input() between attempts.
    
    Also fixes the V1 pressure decoding formula: was using mantissa×10^(E-5),
    now correctly uses 10^((value-20000)/4000) per the V1 protocol spec.
    
    Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

diff --git a/src/cryodaq/drivers/instruments/thyracont_vsp63d.py b/src/cryodaq/drivers/instruments/thyracont_vsp63d.py
index d39a73a..371258b 100644
--- a/src/cryodaq/drivers/instruments/thyracont_vsp63d.py
+++ b/src/cryodaq/drivers/instruments/thyracont_vsp63d.py
@@ -41,7 +41,7 @@ class ThyracontVSP63D(InstrumentDriver):
     **Thyracont Protocol V1 (VSM77DL и аналоги):**
       RS-232/USB-Serial, 115200 бод.
       Команда: ``"<addr>M^\\r"`` → ответ: ``"<addr>M<5digits><checksum>\\r"``
-      Кодировка значения: ``ABCDE`` → давление = ``ABCD × 10^(E - 5)`` mbar.
+      Кодировка значения: ``pressure = 10^((value - 20000) / 4000)`` mbar.
 
     Протокол определяется автоматически по формату ответа, а также может
     быть форсирован через параметр ``protocol``.
@@ -85,53 +85,44 @@ class ThyracontVSP63D(InstrumentDriver):
     async def connect(self) -> None:
         """Открыть последовательный порт и верифицировать связь с прибором.
 
-        Сначала пытается ``*IDN?`` (VSP63D). Если ответ невалидный или таймаут,
-        пробует Protocol V1 measurement запрос для определения связи (VSM77DL).
+        Thyracont VSP63D не поддерживает SCPI (``*IDN?``).  Вместо этого
+        отправляем measurement-запрос Protocol V1 (``"<addr>M^\\r"``) и
+        проверяем, что ответ начинается с ``"<addr>M"``.
+
         Устанавливает флаг ``_connected = True`` при успехе.
         """
         log.info("%s: подключение к %s @ %d бод", self.name, self._resource_str, self._baudrate)
         await self._transport.open(self._resource_str, baudrate=self._baudrate)
 
-        # Попытка 1: *IDN? (VSP63D)
-        try:
-            idn = await self._transport.query("*IDN?")
-            idn_stripped = idn.strip()
-            if idn_stripped and "thyracont" in idn_stripped.lower():
-                self._instrument_id = idn_stripped
-                self._protocol_v1 = False
-                log.info("%s: IDN = %s (VSP63D protocol)", self.name, self._instrument_id)
-                self._connected = True
-                return
-        except Exception:
-            pass
-
-        # Попытка 2: Protocol V1 measurement probe
-        try:
-            cmd = f"{self._address}M^"
-            resp = await self._transport.query(cmd)
-            resp_stripped = resp.strip()
-            if resp_stripped.startswith(self._address):
-                self._protocol_v1 = True
-                self._instrument_id = f"Thyracont-V1@{self._address}"
-                log.info(
-                    "%s: Protocol V1 detected (address=%s, probe=%r)",
-                    self.name, self._address, resp_stripped,
+        cmd = f"{self._address}M^"
+        expected_prefix = f"{self._address}M"
+        last_exc: Exception | None = None
+
+        for attempt in range(3):
+            if attempt > 0:
+                await self._transport.flush_input()
+            try:
+                resp = await self._transport.query(cmd)
+                resp_stripped = resp.strip()
+                if resp_stripped.startswith(expected_prefix):
+                    self._protocol_v1 = True
+                    self._instrument_id = f"Thyracont-V1@{self._address}"
+                    log.info(
+                        "%s: Protocol V1 detected (address=%s, probe=%r, attempt=%d)",
+                        self.name, self._address, resp_stripped, attempt + 1,
+                    )
+                    self._connected = True
+                    return
+            except Exception as exc:
+                last_exc = exc
+                log.debug(
+                    "%s: probe attempt %d failed — %s", self.name, attempt + 1, exc,
                 )
-                self._connected = True
-                return
-        except Exception as exc:
-            log.error(
-                "%s: не удалось связаться с прибором (ни IDN, ни Protocol V1) — %s",
-                self.name, exc,
-            )
-            await self._transport.close()
-            raise
 
-        # Оба протокола не ответили — ошибка
         await self._transport.close()
         raise RuntimeError(
-            f"{self.name}: прибор не ответил ни на *IDN?, ни на Protocol V1 probe"
-        )
+            f"{self.name}: прибор не ответил на Protocol V1 probe ({cmd!r})"
+        ) from last_exc
 
     async def disconnect(self) -> None:
         """Разорвать соединение с прибором (идемпотентно)."""
@@ -249,12 +240,11 @@ class ThyracontVSP63D(InstrumentDriver):
 
         Формат: ``"<addr>M<5digits><checksum>\\r"``, например ``"001M100023D\\r"``.
 
-        Кодировка значения ``ABCDE``:
-          мантисса = ``ABCD`` (первые 4 цифры)
-          экспонента = ``E`` (последняя цифра)
-          давление = мантисса × 10^(E - 5) mbar
+        Кодировка 5-значного значения::
+
+            pressure_mbar = 10 ^ ((value - 20000) / 4000)
 
-        Пример: ``10002`` → 1000 × 10^(2 - 5) = 1000 × 0.001 = 1.0 mbar
+        Пример: ``10002`` → 10^((10002 − 20000) / 4000) = 10^(−2.4995) ≈ 0.00316 mbar
 
         Parameters
         ----------
@@ -281,11 +271,10 @@ class ThyracontVSP63D(InstrumentDriver):
             if len(payload) < 5:
                 raise ValueError(f"Слишком короткий payload: '{payload}'")
 
-            # Первые 5 символов = значение давления
+            # Первые 5 символов = кодированное значение давления
             value_str = payload[:5]
-            mantissa = int(value_str[:4])
-            exponent = int(value_str[4])
-            pressure_mbar = mantissa * (10.0 ** (exponent - 5))
+            value_int = int(value_str)
+            pressure_mbar = 10.0 ** ((value_int - 20000) / 4000.0)
 
         except (ValueError, IndexError) as exc:
             log.error(
commit a2f4bcd0662c150dd861ee7f1324b31f0bdb0584
Author: Vladimir Fomenko <polsovatel111@gmail.com>
Date:   Sat Mar 21 12:01:31 2026 +0300

    fix(safety): Thyracont MV00 fallback, SQLite read/write split, SafetyManager transition, Keithley disconnect
    
    BUG-01: Thyracont connect() now tries MV00 after V1 probe failure.
    Refactored into _try_v1_probe() and _try_mv00_probe() methods.
    
    BUG-02: Separate ThreadPoolExecutor for reads vs writes.
    Long read_readings_history no longer blocks write_immediate.
    
    BUG-03: _safe_off() partial stop uses _transition() instead of
    direct self._state assignment. Events and callbacks now fire.
    
    BUG-06: Keithley read_channels catches OSError (transport-level)
    separately from measurement errors. Sets _connected=False and
    re-raises so scheduler triggers reconnect.
    
    Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

diff --git a/src/cryodaq/drivers/instruments/thyracont_vsp63d.py b/src/cryodaq/drivers/instruments/thyracont_vsp63d.py
index 5c3697f..754dae9 100644
--- a/src/cryodaq/drivers/instruments/thyracont_vsp63d.py
+++ b/src/cryodaq/drivers/instruments/thyracont_vsp63d.py
@@ -88,44 +88,60 @@ class ThyracontVSP63D(InstrumentDriver):
     async def connect(self) -> None:
         """Открыть последовательный порт и верифицировать связь с прибором.
 
-        Thyracont VSP63D не поддерживает SCPI (``*IDN?``).  Вместо этого
-        отправляем measurement-запрос Protocol V1 (``"<addr>M^\\r"``) и
-        проверяем, что ответ начинается с ``"<addr>M"``.
-
-        Устанавливает флаг ``_connected = True`` при успехе.
+        Пробует Protocol V1 (``"<addr>M^"``), затем MV00. Устанавливает
+        флаг ``_connected = True`` при успехе.
         """
         log.info("%s: подключение к %s @ %d бод", self.name, self._resource_str, self._baudrate)
         await self._transport.open(self._resource_str, baudrate=self._baudrate)
 
+        # Try Protocol V1
+        if await self._try_v1_probe():
+            self._protocol_v1 = True
+            self._instrument_id = f"Thyracont-V1@{self._address}"
+            self._connected = True
+            log.info("%s: connected via Protocol V1", self.name)
+            return
+
+        # Fallback: try MV00
+        if await self._try_mv00_probe():
+            self._protocol_v1 = False
+            self._instrument_id = f"Thyracont-MV00@{self._resource_str}"
+            self._connected = True
+            log.info("%s: connected via MV00", self.name)
+            return
+
+        await self._transport.close()
+        raise RuntimeError(f"{self.name}: neither V1 nor MV00 responded")
+
+    async def _try_v1_probe(self) -> bool:
+        """Attempt Protocol V1 probe. Returns True on success."""
         cmd = f"{self._address}M^"
         expected_prefix = f"{self._address}M"
-        last_exc: Exception | None = None
-
         for attempt in range(3):
             if attempt > 0:
                 await self._transport.flush_input()
             try:
                 resp = await self._transport.query(cmd)
-                resp_stripped = resp.strip()
-                if resp_stripped.startswith(expected_prefix):
-                    self._protocol_v1 = True
-                    self._instrument_id = f"Thyracont-V1@{self._address}"
-                    log.info(
-                        "%s: Protocol V1 detected (address=%s, probe=%r, attempt=%d)",
-                        self.name, self._address, resp_stripped, attempt + 1,
-                    )
-                    self._connected = True
-                    return
+                if resp.strip().startswith(expected_prefix):
+                    log.debug("%s: V1 probe OK (attempt %d)", self.name, attempt + 1)
+                    return True
             except Exception as exc:
-                last_exc = exc
-                log.debug(
-                    "%s: probe attempt %d failed — %s", self.name, attempt + 1, exc,
-                )
+                log.debug("%s: V1 probe attempt %d failed: %s", self.name, attempt + 1, exc)
+        return False
 
-        await self._transport.close()
-        raise RuntimeError(
-            f"{self.name}: прибор не ответил на Protocol V1 probe ({cmd!r})"
-        ) from last_exc
+    async def _try_mv00_probe(self) -> bool:
+        """Attempt MV00 protocol probe. Returns True on success."""
+        await self._transport.flush_input()
+        try:
+            resp = await self._transport.query("MV00")
+            resp_stripped = resp.strip()
+            # MV00 returns "<status>,<value>" e.g. "0,1.234E-06"
+            if "," in resp_stripped:
+                log.debug("%s: MV00 probe OK: %s", self.name, resp_stripped)
+                return True
+        except Exception as exc:
+            log.debug("%s: MV00 probe failed: %s", self.name, exc)
+        return False
 
     async def disconnect(self) -> None:
         """Разорвать соединение с прибором (идемпотентно)."""

exec
/opt/homebrew/bin/bash -lc "python - <<'PY'
for s in ['001M100023D','001M260017N','001M400016O','001M100014X']:
    payload=s[:-1]
    c=0
    for b in payload.encode('ascii'):
        c "'^= b
    c &= 0x7f
    print(s, chr(c), c, '"'valid', chr(c)==s[-1])
PY" in /Users/vladimir/Projects/cryodaq
 exited 127 in 0ms:
/opt/homebrew/bin/bash: line 1: python: command not found

exec
/opt/homebrew/bin/bash -lc "python3 - <<'PY'
for s in ['001M100023D','001M260017N','001M400016O','001M100014X']:
    payload=s[:-1]
    c=0
    for b in payload.encode('ascii'):
        c "'^= b
    c &= 0x7f
    print(s, chr(c), c, '"'valid', chr(c)==s[-1])
PY" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
001M100023D | 124 valid False
001M260017N ~ 126 valid False
001M400016O  127 valid False
001M100014X x 120 valid False

codex
The existing strict path returns `SENSOR_ERROR`/NaN on checksum mismatch, and the handoff explicitly calls this a probe/read inconsistency. The only operational exception documented is known non-VSP63D hardware using `validate_checksum: false`, so the patch should preserve that escape hatch rather than invent a second lax mode.
exec
/opt/homebrew/bin/bash -lc 'ls -la artifacts/consultations/2026-04-24-overnight/RESPONSES 2>/dev/null || true' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
total 2128
drwxr-xr-x@ 12 vladimir  staff     384 Apr 24 01:15 .
drwxr-xr-x@  6 vladimir  staff     192 Apr 24 01:15 ..
-rw-r--r--@  1 vladimir  staff  186586 Apr 24 01:17 codex-01-r123-pick.response.md
-rw-r--r--@  1 vladimir  staff  307451 Apr 24 01:17 codex-02-shared-context.response.md
-rw-r--r--@  1 vladimir  staff  208486 Apr 24 01:17 codex-03-launcher-concurrency.response.md
-rw-r--r--@  1 vladimir  staff  101011 Apr 24 01:17 codex-04-alarm-v2-threshold.response.md
-rw-r--r--@  1 vladimir  staff  110339 Apr 24 01:17 codex-05-thyracont-probe.response.md
-rw-r--r--@  1 vladimir  staff       0 Apr 24 01:17 gemini-01-r123-blast.response.md
-rw-r--r--@  1 vladimir  staff       0 Apr 24 01:17 gemini-02-arch-drift.response.md
-rw-r--r--@  1 vladimir  staff       0 Apr 24 01:17 gemini-03-doc-reality.response.md
-rw-r--r--@  1 vladimir  staff       0 Apr 24 01:17 gemini-04-safe-merge-eval.response.md
-rw-r--r--@  1 vladimir  staff       0 Apr 24 01:17 gemini-05-coverage-gaps.response.md

exec
/opt/homebrew/bin/bash -lc "sed -n '1,220p' artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-05-thyracont-probe.response.md" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
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
session id: 019dbc69-e169-7e53-a0d3-e7e72ac1eaf1
--------
user
Model: gpt-5.5
Reasoning effort: high

# Driver hardening — Thyracont VSP63D probe checksum consistency

## Mission

`src/cryodaq/drivers/instruments/thyracont_vsp63d.py::_try_v1_probe`
(~lines 157-166) validates only the response prefix — it does NOT
check the checksum byte. The normal read path DOES validate the
checksum. Consequence: a non-VSP63D device (e.g., VSP206, which
bit us on 2026-04-20) can pass probe and be "connected" by the
driver, then emit NaN forever from read_channels. ~5 LOC fix
(patch spec only — CC will implement in a follow-up session).

## Context files

- `src/cryodaq/drivers/instruments/thyracont_vsp63d.py` full
- `HANDOFF_2026-04-20_GLM.md` §3 — the 2026-04-20 VSP206-masquerading
  incident record
- `tests/drivers/test_thyracont*.py` if any — match test style
- `src/cryodaq/drivers/base.py` `InstrumentDriver` / `Reading` ABC
  for return-value contract

## Specific questions

1. Why does the probe skip checksum validation? Git blame and
   architect intent (HANDOFF §3) suggest "forgiving probe for
   multi-firmware-version compatibility" — verify or refute.
2. Is there any case where a probe-without-checksum is correct?
   For example: do some legit VSP63D firmware revisions return a
   probe response with a non-standard or optional checksum that
   the current strict read-path would reject? If yes, we need to
   keep the probe lax but log the discrepancy loudly.
3. Propose: tighten probe to validate checksum (consistent with
   read path) OR keep lax probe + emit WARNING on checksum
   mismatch + record driver metadata flag "probe_checksum_mismatch".
   Which is safer given the 2026-04-20 failure mode and the
   SafetyManager's fail-closed default?
4. Patch (unified diff, under 50 lines) and regression test (under
   30 lines) for the chosen option.

## Output format

- First line: `Model: gpt-5.5 / Reasoning effort: high`
- Root-cause / intent paragraph (≤ 120 words)
- Preferred option: `TIGHTEN` or `LAX+WARN` with one-line rationale
- Unified diff patch (< 50 lines)
- Test case (< 30 lines)
- Max 1500 words total

## Scope fence

- Do not rewrite the transport layer (`drivers/transport/serial.py`).
- Do not propose mocking Protocol V2 — not currently used in the
  lab.
- Do not comment on unrelated Thyracont features (pressure unit
  conversion, etc.).

## Response file

Write to: `artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-05-thyracont-probe.response.md`

codex
I’ll inspect the driver, handoff note, and existing tests, then write the requested response file. The workspace is read-only, so I can produce the exact content here; if file creation is blocked I’ll call that out clearly.
exec
/opt/homebrew/bin/bash -lc "sed -n '1,260p' /Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/f09cfd210e21e96a0031f4d247be5f2e416d23b1/skills/using-superpowers/SKILL.md && sed -n '1,220p' /Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/f09cfd210e21e96a0031f4d247be5f2e416d23b1/skills/systematic-debugging/SKILL.md" in /Users/vladimir/Projects/cryodaq
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
name: systematic-debugging
description: Use when encountering any bug, test failure, or unexpected behavior, before proposing fixes
---

# Systematic Debugging

## Overview

Random fixes waste time and create new bugs. Quick patches mask underlying issues.

**Core principle:** ALWAYS find root cause before attempting fixes. Symptom fixes are failure.

**Violating the letter of this process is violating the spirit of debugging.**

## The Iron Law

```
NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST
```

If you haven't completed Phase 1, you cannot propose fixes.

codex
The target response file currently contains a captured transcript rather than the requested response body. I’m going to replace it with the concise consultation answer and keep the patch/test blocks exactly in the requested format.
2026-04-23T22:17:40.374848Z ERROR codex_core::tools::router: error=patch rejected: writing is blocked by read-only sandbox; rejected by user approval settings
codex
I couldn’t write the response file because this session’s filesystem sandbox is read-only and write approval is disabled. The exact requested content is below.

Model: gpt-5.5 / Reasoning effort: high

Root-cause / intent: git history refutes “forgiving probe for multi-firmware compatibility” as an explicit design. `8605a52` replaced failing SCPI `*IDN?` with a native V1 measurement probe and only checked `<addr>M`; `a2f4bcd` later refactored that same prefix check into `_try_v1_probe()` while adding MV00 fallback. Checksum hardening came later (`b185fd3`, default `validate_checksum=True`) and updated the read path, not the probe. HANDOFF §3 explicitly records the VSP206 masquerade as an unfixed inconsistency: probe accepts, read rejects forever. The only documented legitimate mismatch case is known non-VSP63D/VSP206 hardware, already handled by `validate_checksum: false`; no evidence shows legit VSP63D probe-only checksum variance.

Preferred option: `TIGHTEN` — fail connect when `validate_checksum=True` and the V1 probe checksum is bad; this matches read-path semantics and SafetyManager fail-closed policy, while preserving the documented `validate_checksum: false` escape hatch.

```diff
diff --git a/src/cryodaq/drivers/instruments/thyracont_vsp63d.py b/src/cryodaq/drivers/instruments/thyracont_vsp63d.py
--- a/src/cryodaq/drivers/instruments/thyracont_vsp63d.py
+++ b/src/cryodaq/drivers/instruments/thyracont_vsp63d.py
@@ -163,8 +163,16 @@ class ThyracontVSP63D(InstrumentDriver):
                 await self._transport.flush_input()
             try:
                 resp = await self._transport.query(cmd)
-                if resp.strip().startswith(expected_prefix):
-                    log.debug("%s: V1 probe OK (attempt %d)", self.name, attempt + 1)
+                resp_stripped = resp.strip()
+                if resp_stripped.startswith(expected_prefix):
+                    if self._validate_checksum and not self._verify_v1_checksum(resp_stripped):
+                        log.warning(
+                            "%s: V1 probe checksum mismatch in '%s'",
+                            self.name,
+                            resp_stripped,
+                        )
+                        continue
+                    log.debug("%s: V1 probe OK (attempt %d)", self.name, attempt + 1)
                     return True
             except Exception as exc:
                 log.debug("%s: V1 probe attempt %d failed: %s", self.name, attempt + 1, exc)
```

```python
async def test_v1_probe_rejects_checksum_mismatch() -> None:
    """Prefix-only V1 response must not pass probe when checksum validation is on."""

    class BadChecksumTransport:
        async def query(self, command: str) -> str:
            assert command == "001M^"
            return "001M100023D\r"

        async def flush_input(self) -> None:
            return None

    driver = ThyracontVSP63D("vsm77dl", "COM3", mock=True, address="001")
    driver._transport = BadChecksumTransport()  # type: ignore[assignment]

    assert await driver._try_v1_probe() is False
```
tokens used
112 797
I couldn’t write the response file because this session’s filesystem sandbox is read-only and write approval is disabled. The exact requested content is below.

Model: gpt-5.5 / Reasoning effort: high

Root-cause / intent: git history refutes “forgiving probe for multi-firmware compatibility” as an explicit design. `8605a52` replaced failing SCPI `*IDN?` with a native V1 measurement probe and only checked `<addr>M`; `a2f4bcd` later refactored that same prefix check into `_try_v1_probe()` while adding MV00 fallback. Checksum hardening came later (`b185fd3`, default `validate_checksum=True`) and updated the read path, not the probe. HANDOFF §3 explicitly records the VSP206 masquerade as an unfixed inconsistency: probe accepts, read rejects forever. The only documented legitimate mismatch case is known non-VSP63D/VSP206 hardware, already handled by `validate_checksum: false`; no evidence shows legit VSP63D probe-only checksum variance.

Preferred option: `TIGHTEN` — fail connect when `validate_checksum=True` and the V1 probe checksum is bad; this matches read-path semantics and SafetyManager fail-closed policy, while preserving the documented `validate_checksum: false` escape hatch.

```diff
diff --git a/src/cryodaq/drivers/instruments/thyracont_vsp63d.py b/src/cryodaq/drivers/instruments/thyracont_vsp63d.py
--- a/src/cryodaq/drivers/instruments/thyracont_vsp63d.py
+++ b/src/cryodaq/drivers/instruments/thyracont_vsp63d.py
@@ -163,8 +163,16 @@ class ThyracontVSP63D(InstrumentDriver):
                 await self._transport.flush_input()
             try:
                 resp = await self._transport.query(cmd)
-                if resp.strip().startswith(expected_prefix):
-                    log.debug("%s: V1 probe OK (attempt %d)", self.name, attempt + 1)
+                resp_stripped = resp.strip()
+                if resp_stripped.startswith(expected_prefix):
+                    if self._validate_checksum and not self._verify_v1_checksum(resp_stripped):
+                        log.warning(
+                            "%s: V1 probe checksum mismatch in '%s'",
+                            self.name,
+                            resp_stripped,
+                        )
+                        continue
+                    log.debug("%s: V1 probe OK (attempt %d)", self.name, attempt + 1)
                     return True
             except Exception as exc:
                 log.debug("%s: V1 probe attempt %d failed: %s", self.name, attempt + 1, exc)
```

```python
async def test_v1_probe_rejects_checksum_mismatch() -> None:
    """Prefix-only V1 response must not pass probe when checksum validation is on."""

    class BadChecksumTransport:
        async def query(self, command: str) -> str:
            assert command == "001M^"
            return "001M100023D\r"

        async def flush_input(self) -> None:
            return None

    driver = ThyracontVSP63D("vsm77dl", "COM3", mock=True, address="001")
    driver._transport = BadChecksumTransport()  # type: ignore[assignment]

    assert await driver._try_v1_probe() is False
```
