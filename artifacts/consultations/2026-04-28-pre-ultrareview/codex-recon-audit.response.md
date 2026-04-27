Reading additional input from stdin...
OpenAI Codex v0.124.0 (research preview)
--------
workdir: /Users/vladimir/Projects/cryodaq
model: gpt-5.5
provider: openai
approval: never
sandbox: read-only
reasoning effort: high
reasoning summaries: none
session id: 019dd13a-9158-7630-8e07-94aeff2cc9aa
--------
user
Model: gpt-5.5
Reasoning effort: high

# Pre-/ultrareview recon audit — Codex literal verifier

## Mission
CC produced artifacts/2026-04-28-pre-ultrareview-recon.md identifying
4 pending items. Verify the recon is complete and accurate. What did
CC miss?

## What to verify

### A. CC's recon claims
Read artifacts/2026-04-28-pre-ultrareview-recon.md, then verify each
claim against actual repo state.

- A1: "ORCHESTRATION v1.2 committed" — grep docs/ORCHESTRATION.md for
  "## 14. Verification practices" and "### 14.5". Both must be present.
- A2: "Tags v0.33.0–v0.39.0" — run: git tag -l "v0.*" --sort=v:refname
- A3: "No doc drift in README.md" — grep README.md for ".330" — should
  show only "`.330` removed" (the explicit removal note on line ~84).
- A4: "Root .md whitelist clean" — list repo root .md files,
  cross-check against ORCHESTRATION §6 whitelist
- A5: "All remaining .330 hits intentional regression tests" —
  grep -rn "\.330" src/ tests/ and verify each hit is in a test
  that explicitly verifies removal (not a live code path)

### B. What CC didn't check (likely blindspots)
- B1: Test suite passes — run: .venv/bin/pytest tests/analytics/test_calibration.py tests/gui/shell/overlays/test_calibration_panel.py tests/core/test_calibration_commands.py -q
- B2: Calibration module imports cleanly — .venv/bin/python -c "from cryodaq.analytics.calibration import CalibrationStore; print('OK')"
- B3: GUI calibration overlay imports cleanly — .venv/bin/python -c "import os; os.environ['QT_QPA_PLATFORM']='offscreen'; from cryodaq.gui.shell.overlays.calibration_panel import CalibrationPanel; print('OK')"
- B4: Engine imports cleanly — .venv/bin/python -c "import cryodaq.engine; print('OK')"
- B5: No stale TODO/FIXME referencing removed export_curve_330 — grep -rn "TODO.*330\|FIXME.*330" src/

### C. Likely /ultrareview findings (predict top-5)
Rank the 5 issues most likely to surface if /ultrareview ran now.
Examples to check:
- Type coverage gaps in calibration.py (export_curve_cof return type, _write_cof_export None return)
- Async task leaks (search for asyncio.create_task without cancel/await)
- Resource cleanup (search for open() without context manager in src/)
- Missing CHANGELOG entry for .cof migration
- export_curve_cof() docstring references "Chebyshev" but no zone-count validation

## Source files
- artifacts/2026-04-28-pre-ultrareview-recon.md
- docs/ORCHESTRATION.md
- src/cryodaq/analytics/calibration.py
- src/cryodaq/engine.py
- src/cryodaq/gui/shell/overlays/calibration_panel.py
- tests/analytics/test_calibration.py
- tests/gui/shell/overlays/test_calibration_panel.py
- CHANGELOG.md (check for .cof migration entry)

## Output
Three sections:
1. **CC recon verification** — per-claim PASS/FAIL with file:line
2. **Missed by CC** — itemized blindspots with severity
3. **Likely /ultrareview findings** — top-5 ranked

Final verdict: RECON COMPLETE / RECON HAS GAPS / REPO NOT READY.
Hard cap: 3000 words. NO prelude.

Write output to:
~/Projects/cryodaq/artifacts/consultations/2026-04-28-pre-ultrareview/codex-recon-audit.response.md
codex
Using `superpowers:using-superpowers` to satisfy the session workflow requirement, then I’ll run the requested literal checks against the repo.
exec
/opt/homebrew/bin/bash -lc "sed -n '1,220p' /Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/2e3f0bd9b95ad1fc5c9d0bfd20e0849038250c23/skills/using-superpowers/SKILL.md" in /Users/vladimir/Projects/cryodaq
 exited 1 in 0ms:
sed: /Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/2e3f0bd9b95ad1fc5c9d0bfd20e0849038250c23/skills/using-superpowers/SKILL.md: No such file or directory

codex
The listed Superpowers skill path is stale in this workspace, so I’m locating the installed skill file and continuing with the same verification flow.
exec
/opt/homebrew/bin/bash -lc "rg --files /Users/vladimir/.codex | rg 'using-superpowers/SKILL\\.md"'$|Superpowers|superpowers'"'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/assets/superpowers-small.svg
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/assets/app-icon.png
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/subagent-driven-development/code-quality-reviewer-prompt.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/subagent-driven-development/SKILL.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/subagent-driven-development/agents/openai.yaml
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/subagent-driven-development/implementer-prompt.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/subagent-driven-development/spec-reviewer-prompt.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/verification-before-completion/SKILL.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/verification-before-completion/agents/openai.yaml
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/writing-skills/graphviz-conventions.dot
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/writing-skills/SKILL.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/writing-skills/persuasion-principles.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/writing-skills/examples/CLAUDE_MD_TESTING.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/writing-skills/anthropic-best-practices.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/writing-skills/render-graphs.js
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/writing-skills/testing-skills-with-subagents.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/writing-skills/agents/openai.yaml
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/using-superpowers/SKILL.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/receiving-code-review/SKILL.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/receiving-code-review/agents/openai.yaml
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/using-superpowers/agents/openai.yaml
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/requesting-code-review/SKILL.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/using-superpowers/references/gemini-tools.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/using-superpowers/references/codex-tools.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/using-superpowers/references/copilot-tools.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/requesting-code-review/agents/openai.yaml
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/requesting-code-review/code-reviewer.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/writing-plans/SKILL.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/systematic-debugging/find-polluter.sh
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/systematic-debugging/condition-based-waiting-example.ts
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/systematic-debugging/root-cause-tracing.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/systematic-debugging/test-pressure-3.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/systematic-debugging/SKILL.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/systematic-debugging/defense-in-depth.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/systematic-debugging/test-academic.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/systematic-debugging/CREATION-LOG.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/systematic-debugging/test-pressure-2.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/systematic-debugging/condition-based-waiting.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/systematic-debugging/test-pressure-1.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/executing-plans/SKILL.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/dispatching-parallel-agents/SKILL.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/CODE_OF_CONDUCT.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/LICENSE
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/writing-plans/agents/openai.yaml
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/writing-plans/plan-document-reviewer-prompt.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/systematic-debugging/agents/openai.yaml
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/brainstorming/spec-document-reviewer-prompt.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/brainstorming/SKILL.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/executing-plans/agents/openai.yaml
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/brainstorming/visual-companion.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/dispatching-parallel-agents/agents/openai.yaml
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/README.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/using-git-worktrees/SKILL.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/agents/code-reviewer.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/test-driven-development/testing-anti-patterns.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/test-driven-development/SKILL.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/finishing-a-development-branch/SKILL.md
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/brainstorming/scripts/helper.js
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/brainstorming/scripts/server.cjs
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/brainstorming/scripts/start-server.sh
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/brainstorming/scripts/frame-template.html
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/brainstorming/scripts/stop-server.sh
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/using-git-worktrees/agents/openai.yaml
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/brainstorming/agents/openai.yaml
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/test-driven-development/agents/openai.yaml
/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/finishing-a-development-branch/agents/openai.yaml

exec
/opt/homebrew/bin/bash -lc "sed -n '1,220p' /Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/using-superpowers/SKILL.md" in /Users/vladimir/Projects/cryodaq
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
I’m gathering the recon text and the exact repo evidence first: orchestration markers, tag list, README `.330` hits, root markdown files, and source/test `.330` references.
exec
/opt/homebrew/bin/bash -lc 'nl -ba artifacts/2026-04-28-pre-ultrareview-recon.md' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	# Pre-/ultrareview recon — 2026-04-28
     2	
     3	## Repo state
     4	
     5	- **HEAD:** `c1e5a20` — `merge: GUI .cof wiring (deferred follow-up from .cof migration)`
     6	  - 2 parents confirmed via `git cat-file -p HEAD`: `4c44a38` (master pre-merge) + `b254de2` (branch tip)
     7	- **Tags:** v0.33.0 → v0.39.0 (7 tags, latest: v0.39.0)
     8	- **Local uncommitted changes:** None
     9	- **Uncommitted ORCHESTRATION v1.2:** No — committed at `4c44a38` (2026-04-27 23:14)
    10	
    11	## Active branches (5 local)
    12	
    13	| Branch | Status | Notes |
    14	|--------|--------|-------|
    15	| `master` | HEAD, clean | c1e5a20 |
    16	| `codex/safe-merge-b1-truth-recovery` | **[ahead 7]** of origin | B1 vault investigation; 7 commits not pushed/merged. Unclear if closed. |
    17	| `experiment/iv7-ipc-transport` | Active worktree | `.worktrees/experiment-iv7-ipc-transport` at `63a3fed`. In-progress — do not touch. |
    18	| `feat/cof-calibration-export` | Merged to master | Can be deleted. |
    19	| `feat/cof-gui-wiring` | Merged to master | Can be deleted. |
    20	| `feat/launcher-sigterm-handler` | Not merged | `9a8412e` — status unknown; handoff exists at `artifacts/handoffs/2026-04-27-launcher-sigterm-review.md`. |
    21	
    22	## Worktrees (1 active)
    23	
    24	- `~/Projects/cryodaq/.worktrees/experiment-iv7-ipc-transport` at `63a3fed [experiment/iv7-ipc-transport]`
    25	
    26	## Untracked files (8 files, 2 directories)
    27	
    28	All in `artifacts/consultations/2026-04-28-*` — consultation prompt + response files from this session's .cof audits. Per ORCHESTRATION §6.2 these belong committed.
    29	
    30	```
    31	artifacts/consultations/2026-04-28-cof-gui-audit/codex-cof-gui-audit.prompt.md
    32	artifacts/consultations/2026-04-28-cof-gui-audit/codex-cof-gui-audit.response.md
    33	artifacts/consultations/2026-04-28-cof-gui-audit/gemini-cof-gui-audit.prompt.md
    34	artifacts/consultations/2026-04-28-cof-gui-audit/gemini-cof-gui-audit.response.md
    35	artifacts/consultations/2026-04-28-cof-migration/codex-cof-audit.prompt.md
    36	artifacts/consultations/2026-04-28-cof-migration/codex-cof-audit.response.md
    37	artifacts/consultations/2026-04-28-cof-migration/gemini-cof-audit.prompt.md
    38	artifacts/consultations/2026-04-28-cof-migration/gemini-cof-audit.response.md
    39	```
    40	
    41	## Repo root .md violations: 0
    42	
    43	All 19 root .md files match ORCHESTRATION §6.2 whitelist:
    44	`CC_PROMPT_*.md`, `HANDOFF_*.md`, `SESSION_DETAIL_*.md`, `CHANGELOG.md`, `CLAUDE.md`, `CODEX_ARCHITECTURE_CONTROL_PLANE.md`, `DOC_REALITY_MAP.md`, `PROJECT_STATUS.md`, `README.md`, `RELEASE_CHECKLIST.md`, `ROADMAP.md`, `THIRD_PARTY_NOTICES.md`. No violations.
    45	
    46	## GUI .330 outstanding: 0 (all intentional)
    47	
    48	All remaining `.330` strings in tests are deliberate:
    49	- `test_calibration_panel.py:360` — `assert "curve_330_path" not in cmd` (negative assertion)
    50	- `test_calibration.py:359-367` — `test_export_curve_330_removed` regression guard + `fake_330` fixture for rejection test
    51	
    52	No spurious `.330` references in `src/`. Phase D fully closed.
    53	
    54	## Doc drift (Phase II.x references): LOW RISK
    55	
    56	`grep "II\.13|dual-shell|Phase II\."` found hits only in:
    57	- `docs/phase-ui-1/phase_ui_v2_roadmap.md` — historical phase tracking (expected)
    58	- `docs/phase-ui-1/ui_refactor_context.md` — context doc (expected)
    59	- `docs/operator_manual.md` — future work reference ("Phase II.9 rebuild")
    60	- `docs/design-system/` — component docs (expected historical context)
    61	
    62	No hits in `CLAUDE.md` or `README.md`. No actionable drift for pre-/ultrareview.
    63	
    64	## Stale artifacts: 0 candidates
    65	
    66	All consultation directories and handoffs are ≤ 5 days old (2026-04-23 to 2026-04-28). Nothing to archive yet.
    67	
    68	---
    69	
    70	## Recommended pre-review actions (priority order)
    71	
    72	1. **Commit untracked consultation files** — 8 files in `artifacts/consultations/2026-04-28-*/`. Per ORCHESTRATION §6.2, these are audit artifacts that belong in the repo alongside the handoffs that reference them. Simple `git add + commit`.
    73	
    74	2. **Resolve `feat/launcher-sigterm-handler`** — branch exists, handoff at `2026-04-27-launcher-sigterm-review.md`. Architect review pending or completed? If approved: merge. If stale: document and delete.
    75	
    76	3. **Resolve `codex/safe-merge-b1-truth-recovery` [ahead 7]** — 7 local commits not on origin or master. B1 investigation branch. Determine if this was superseded by vault investigation closures; if so, push or delete.
    77	
    78	4. **Delete merged branches** — `feat/cof-calibration-export` and `feat/cof-gui-wiring` are merged; safe to delete locally and on origin.
    79	
    80	5. **Pre-/ultrareview trigger** — repo is clean and consistent post-items 1-4. Trigger ultrareview when ready.

exec
/opt/homebrew/bin/bash -lc "rg -n \"\\.330\" README.md" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
84:  - `.cof` (Chebyshev coefficients) / `.340` / JSON / CSV export; `.330` removed

exec
/opt/homebrew/bin/bash -lc 'rg -n "''^## 14'"\\. Verification practices|"'^### 14'"\\.5|root.*\\.md|whitelist|README|ORCHESTRATION|CHANGELOG|AGENTS\" docs/ORCHESTRATION.md" in /Users/vladimir/Projects/cryodaq
exec
/opt/homebrew/bin/bash -lc "find . -maxdepth 1 -type f -name '*.md' -print | sort" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
240:├── ORCHESTRATION.md          ← this file
262:At **repo root**, the only `.md` files permitted are:
263:- `README.md`
265:- `CHANGELOG.md`
432:| Repo cleanup | this document, §§ 6, 5.2 | ✅ DONE (commits `adb49fe`..`8ebc893`, 2026-04-23) — 12 root .md archived (11 to audits, 1 preserved as blessed dossier), agent workspaces gitignored, duplicate branches pruned, worktree naming aligned |
456:   untracked. Rule preventing it: §6.2 (strict root whitelist).
529:- Architect-domain decision required: whitelist membership change,
568:ORCHESTRATION.md §11 and Vladimir's memory slot 20 say
629:## 14. Verification practices
731:### 14.5 rtk-ai proxy filters merge commits

 succeeded in 0ms:
./CC_PROMPT_IV_2_ORCHESTRATOR.md
./CC_PROMPT_IV_3_BATCH.md
./CC_PROMPT_IV_4_BATCH.md
./CC_PROMPT_IV_6_ZMQ_BRIDGE_FIX.md
./CC_PROMPT_IV_7_IPC_TRANSPORT.md
./CC_PROMPT_OVERNIGHT_SWARM_2026-04-24.md
./CC_PROMPT_VAULT_AUDIT_2026-04-27.md
./CC_PROMPT_VAULT_BUILD_2026-04-26.md
./CHANGELOG.md
./CLAUDE.md
./CODEX_ARCHITECTURE_CONTROL_PLANE.md
./DOC_REALITY_MAP.md
./HANDOFF_2026-04-20_GLM.md
./PROJECT_STATUS.md
./README.md
./RELEASE_CHECKLIST.md
./ROADMAP.md
./SESSION_DETAIL_2026-04-20.md
./THIRD_PARTY_NOTICES.md

exec
/opt/homebrew/bin/bash -lc 'git tag -l "v0.*" --sort=v:refname' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
v0.33.0
v0.34.0
v0.35.0
v0.36.0
v0.37.0
v0.38.0
v0.39.0

exec
/opt/homebrew/bin/bash -lc "rg -n \"\\.330\" src tests" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
tests/analytics/test_calibration.py:279:# Phase D: .cof export + .330 removal
tests/analytics/test_calibration.py:367:    fake_330 = tmp_path / "curve.330"

codex
The first pass confirms the marker claims mostly line up, but there are two places to tighten: CC’s `.330` hit description overstates the grep result, and the root whitelist needs exact §6.2 line matching rather than relying on the prose summary. I’m running the blindspot checks now.
exec
/opt/homebrew/bin/bash -lc "nl -ba docs/ORCHESTRATION.md | sed -n '258,276p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   258	```
   259	
   260	### 6.2 Where things must NOT live
   261	
   262	At **repo root**, the only `.md` files permitted are:
   263	- `README.md`
   264	- `CLAUDE.md`
   265	- `CHANGELOG.md`
   266	- `CODEX_ARCHITECTURE_CONTROL_PLANE.md` — Codex technical dossier (commit 256da7a)
   267	- `ROADMAP.md`
   268	- `PROJECT_STATUS.md`
   269	- `RELEASE_CHECKLIST.md`
   270	- `DOC_REALITY_MAP.md` (historical, may be removed)
   271	- `LICENSE`, `THIRD_PARTY_NOTICES.md`
   272	- `CC_PROMPT_*.md` — architect-authored specs
   273	- `HANDOFF_*.md`, `SESSION_DETAIL_*.md` — architect-authored
   274	
   275	A consultant (or CC on behalf of a consultant) producing
   276	`REPO_HARDENING_FINAL.md` / `REVIEW_PLAN_GEMINI.md` /

exec
/opt/homebrew/bin/bash -lc "nl -ba tests/analytics/test_calibration.py | sed -n '250,380p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   250	        index_path.unlink()
   251	
   252	    reloaded = CalibrationStore(tmp_path / "legacy")
   253	    reloaded.load_curves(tmp_path / "legacy" / "curves")
   254	
   255	    assert reloaded.get_curve_info("sensor-005")["curve_id"] == curve.curve_id
   256	    assert index_path.exists()
   257	    assert curve_path.exists()
   258	
   259	
   260	# ---------------------------------------------------------------------------
   261	# Phase 2d B-1: atomic write for calibration index
   262	# ---------------------------------------------------------------------------
   263	
   264	
   265	def test_calibration_index_uses_atomic_write():
   266	    """B-1.2: calibration.py index/curve writes must use atomic_write_text."""
   267	    source = Path("src/cryodaq/analytics/calibration.py").read_text(encoding="utf-8")
   268	    import re
   269	
   270	    raw_state_writes = re.findall(r"_index_path\.write_text|target\.write_text\(json", source)
   271	    assert len(raw_state_writes) == 0, (
   272	        f"Found {len(raw_state_writes)} raw write_text calls for state files — "
   273	        f"should all route through atomic_write_text"
   274	    )
   275	    assert "atomic_write_text" in source
   276	
   277	
   278	# ---------------------------------------------------------------------------
   279	# Phase D: .cof export + .330 removal
   280	# ---------------------------------------------------------------------------
   281	
   282	
   283	def test_export_curve_cof_writes_file_with_expected_structure(tmp_path: Path) -> None:
   284	    store = CalibrationStore(tmp_path)
   285	    curve = store.fit_curve(
   286	        "sensor-cof-01", _multi_zone_samples(300), raw_unit="V", max_zones=2, min_points_per_zone=24
   287	    )
   288	    store.save_curve(curve)
   289	
   290	    cof_path = store.export_curve_cof("sensor-cof-01")
   291	
   292	    assert cof_path.exists()
   293	    assert cof_path.suffix == ".cof"
   294	    text = cof_path.read_text(encoding="utf-8")
   295	    assert "# CryoDAQ calibration curve export .cof" in text
   296	    assert f"# sensor_id: {curve.sensor_id}" in text
   297	    assert f"# curve_id: {curve.curve_id}" in text
   298	    assert "[zone 1]" in text
   299	    assert "raw_min:" in text
   300	    assert "raw_max:" in text
   301	    assert "order:" in text
   302	    assert "coefficients:" in text
   303	
   304	
   305	def test_export_curve_cof_preserves_chebyshev_coefficients_round_trip(tmp_path: Path) -> None:
   306	    store = CalibrationStore(tmp_path)
   307	    curve = store.fit_curve(
   308	        "sensor-cof-02", _multi_zone_samples(600), raw_unit="V", max_zones=3, min_points_per_zone=24
   309	    )
   310	    store.save_curve(curve)
   311	
   312	    cof_path = store.export_curve_cof("sensor-cof-02")
   313	    text = cof_path.read_text(encoding="utf-8")
   314	
   315	    parsed_coefficients: list[tuple[float, ...]] = []
   316	    for line in text.splitlines():
   317	        line = line.strip()
   318	        if line.startswith("coefficients:"):
   319	            values = tuple(float(v) for v in line.split(":", 1)[1].split(","))
   320	            parsed_coefficients.append(values)
   321	
   322	    assert len(parsed_coefficients) == len(curve.zones)
   323	    for parsed, zone in zip(parsed_coefficients, curve.zones, strict=True):
   324	        assert len(parsed) == len(zone.coefficients)
   325	        for a, b in zip(parsed, zone.coefficients, strict=True):
   326	            assert a == pytest.approx(b, rel=1e-10)
   327	
   328	
   329	def test_export_curve_cof_includes_zone_count_header(tmp_path: Path) -> None:
   330	    store = CalibrationStore(tmp_path)
   331	    curve = store.fit_curve(
   332	        "sensor-cof-03", _multi_zone_samples(300), raw_unit="V", max_zones=3, min_points_per_zone=24
   333	    )
   334	    store.save_curve(curve)
   335	
   336	    cof_path = store.export_curve_cof("sensor-cof-03")
   337	    text = cof_path.read_text(encoding="utf-8")
   338	
   339	    assert f"# zone_count: {len(curve.zones)}" in text
   340	
   341	
   342	def test_export_curve_cof_metadata_comments_match_curve(tmp_path: Path) -> None:
   343	    store = CalibrationStore(tmp_path)
   344	    curve = store.fit_curve(
   345	        "sensor-cof-04", _sample_series(), raw_unit="ohm", max_zones=2, min_points_per_zone=4
   346	    )
   347	    store.save_curve(curve)
   348	
   349	    cof_path = store.export_curve_cof("sensor-cof-04")
   350	    text = cof_path.read_text(encoding="utf-8")
   351	
   352	    assert f"# raw_unit: {curve.raw_unit}" in text
   353	    assert f"# fit_timestamp: {curve.fit_timestamp.isoformat()}" in text
   354	    assert "# rmse_k:" in text
   355	    assert "# max_abs_error_k:" in text
   356	    assert "# point_count:" in text
   357	
   358	
   359	def test_export_curve_330_removed(tmp_path: Path) -> None:
   360	    store = CalibrationStore(tmp_path)
   361	    assert not hasattr(store, "export_curve_330"), (
   362	        "export_curve_330 must be removed — architect decision 2026-04-25"
   363	    )
   364	
   365	
   366	def test_import_curve_file_rejects_330_suffix(tmp_path: Path) -> None:
   367	    fake_330 = tmp_path / "curve.330"
   368	    fake_330.write_text("# header\n4.0 75.0\n6.0 60.0\n10.0 40.0\n20.0 22.0\n", encoding="utf-8")
   369	    store = CalibrationStore(tmp_path)
   370	    with pytest.raises(ValueError, match="Unsupported calibration import format"):
   371	        store.import_curve_file(fake_330)

exec
/opt/homebrew/bin/bash -lc "nl -ba tests/gui/shell/overlays/test_calibration_panel.py | sed -n '340,370p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   340	
   341	    panel = CalibrationPanel()
   342	    panel.set_connected(True)
   343	    panel._results_widget.set_channels(["Т1"])
   344	    out = tmp_path / "Т1.cof"
   345	    monkeypatch.setattr(
   346	        QFileDialog,
   347	        "getSaveFileName",
   348	        staticmethod(lambda *a, **k: (str(out), "Chebyshev .cof (*.cof)")),
   349	    )
   350	    _StubWorker.dispatched = []
   351	    panel._results_widget._export_cof_btn.click()
   352	    export_cmds = [c for c in _StubWorker.dispatched if c.get("cmd") == "calibration_curve_export"]
   353	    assert len(export_cmds) == 1
   354	    cmd = export_cmds[0]
   355	    assert cmd["sensor_id"] == "Т1"
   356	    assert cmd["curve_cof_path"] == str(out)
   357	    # Other format paths not set.
   358	    assert "json_path" not in cmd
   359	    assert "table_path" not in cmd
   360	    assert "curve_330_path" not in cmd
   361	    assert "curve_340_path" not in cmd
   362	
   363	
   364	def test_export_json_dispatches_json_path(app, monkeypatch, tmp_path):
   365	    from PySide6.QtWidgets import QFileDialog
   366	
   367	    panel = CalibrationPanel()
   368	    panel.set_connected(True)
   369	    panel._results_widget.set_channels(["Т5"])
   370	    out = tmp_path / "Т5.json"

exec
/opt/homebrew/bin/bash -lc 'git worktree list' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
/Users/vladimir/Projects/cryodaq                                         95240ae [master]
/Users/vladimir/Projects/cryodaq/.worktrees/experiment-iv7-ipc-transport 63a3fed [experiment/iv7-ipc-transport]

exec
/opt/homebrew/bin/bash -lc 'git branch -vv' in /Users/vladimir/Projects/cryodaq
exec
/opt/homebrew/bin/bash -lc 'git status --short' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
  codex/safe-merge-b1-truth-recovery b2b4fb5 [origin/codex/safe-merge-b1-truth-recovery: ahead 7] fix: harden B1 capture bridge startup validation
+ experiment/iv7-ipc-transport       63a3fed (/Users/vladimir/Projects/cryodaq/.worktrees/experiment-iv7-ipc-transport) Make launcher transport probe IPC-aware
* master                             95240ae [origin/master] artifacts: commit cof migration + cof-gui audit consultations + recon

 succeeded in 0ms:
?? artifacts/consultations/2026-04-28-pre-ultrareview/

codex
The repo state has moved since CC’s recon: master is now `95240ae`, the prior consultation files appear committed, and only the new pre-ultrareview consultation directory is untracked. I’m checking whether that changes the readiness verdict and running the targeted pytest/import probes.
exec
/opt/homebrew/bin/bash -lc 'rg -n "TODO.*330|FIXME.*330" src' in /Users/vladimir/Projects/cryodaq
 exited 1 in 0ms:
exec
/opt/homebrew/bin/bash -lc '.venv/bin/pytest tests/analytics/test_calibration.py tests/gui/shell/overlays/test_calibration_panel.py tests/core/test_calibration_commands.py -q' in /Users/vladimir/Projects/cryodaq
exec
/opt/homebrew/bin/bash -lc ".venv/bin/python -c \"from cryodaq.analytics.calibration import CalibrationStore; print('OK')\"" in /Users/vladimir/Projects/cryodaq
exec
/opt/homebrew/bin/bash -lc ".venv/bin/python -c \"import os; os.environ['QT_QPA_PLATFORM']='offscreen'; from cryodaq.gui.shell.overlays.calibration_panel import CalibrationPanel; print('OK')\"" in /Users/vladimir/Projects/cryodaq
exec
/opt/homebrew/bin/bash -lc ".venv/bin/python -c \"import cryodaq.engine; print('OK')\"" in /Users/vladimir/Projects/cryodaq
 succeeded in 104ms:
 exited 1 in 243ms:
Traceback (most recent call last):
  File "/Users/vladimir/Projects/cryodaq/.venv/bin/pytest", line 6, in <module>
    sys.exit(console_main())
             ~~~~~~~~~~~~^^
  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/_pytest/config/__init__.py", line 223, in console_main
    code = main()
  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/_pytest/config/__init__.py", line 193, in main
    config = _prepareconfig(new_args, plugins)
  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/_pytest/config/__init__.py", line 361, in _prepareconfig
    config: Config = pluginmanager.hook.pytest_cmdline_parse(
                     ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^
        pluginmanager=pluginmanager, args=args
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/pluggy/_hooks.py", line 512, in __call__
    return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)
           ~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/pluggy/_manager.py", line 120, in _hookexec
    return self._inner_hookexec(hook_name, methods, kwargs, firstresult)
           ~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/pluggy/_callers.py", line 167, in _multicall
    raise exception
  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/pluggy/_callers.py", line 139, in _multicall
    teardown.throw(exception)
    ~~~~~~~~~~~~~~^^^^^^^^^^^
  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/_pytest/helpconfig.py", line 124, in pytest_cmdline_parse
    config = yield
             ^^^^^
  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/pluggy/_callers.py", line 121, in _multicall
    res = hook_impl.function(*args)
  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/_pytest/config/__init__.py", line 1192, in pytest_cmdline_parse
    self.parse(args)
    ~~~~~~~~~~^^^^^^
  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/_pytest/config/__init__.py", line 1562, in parse
    self.hook.pytest_load_initial_conftests(
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^
        early_config=self, args=args, parser=self._parser
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/pluggy/_hooks.py", line 512, in __call__
    return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)
           ~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/pluggy/_manager.py", line 120, in _hookexec
    return self._inner_hookexec(hook_name, methods, kwargs, firstresult)
           ~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/pluggy/_callers.py", line 167, in _multicall
    raise exception
  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/pluggy/_callers.py", line 139, in _multicall
    teardown.throw(exception)
    ~~~~~~~~~~~~~~^^^^^^^^^^^
  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/_pytest/warnings.py", line 128, in pytest_load_initial_conftests
    return (yield)
            ^^^^^
  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/pluggy/_callers.py", line 116, in _multicall
    next(function_gen)  # first yield
    ~~~~^^^^^^^^^^^^^^
  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/_pytest/capture.py", line 170, in pytest_load_initial_conftests
    capman.start_global_capturing()
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^
  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/_pytest/capture.py", line 773, in start_global_capturing
    self._global_capturing = _get_multicapture(self._method)
                             ~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^
  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/_pytest/capture.py", line 714, in _get_multicapture
    return MultiCapture(in_=FDCapture(0), out=FDCapture(1), err=FDCapture(2))
                                              ~~~~~~~~~^^^
  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/_pytest/capture.py", line 493, in __init__
    TemporaryFile(buffering=0),
    ~~~~~~~~~~~~~^^^^^^^^^^^^^
  File "/Library/Frameworks/Python.framework/Versions/3.14/lib/python3.14/tempfile.py", line 652, in TemporaryFile
    prefix, suffix, dir, output_type = _sanitize_params(prefix, suffix, dir)
                                       ~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^
  File "/Library/Frameworks/Python.framework/Versions/3.14/lib/python3.14/tempfile.py", line 126, in _sanitize_params
    dir = gettempdir()
  File "/Library/Frameworks/Python.framework/Versions/3.14/lib/python3.14/tempfile.py", line 316, in gettempdir
    return _os.fsdecode(_gettempdir())
                        ~~~~~~~~~~~^^
  File "/Library/Frameworks/Python.framework/Versions/3.14/lib/python3.14/tempfile.py", line 309, in _gettempdir
    tempdir = _get_default_tempdir()
  File "/Library/Frameworks/Python.framework/Versions/3.14/lib/python3.14/tempfile.py", line 224, in _get_default_tempdir
    raise FileNotFoundError(_errno.ENOENT,
                            "No usable temporary directory found in %s" %
                            dirlist)
FileNotFoundError: [Errno 2] No usable temporary directory found in ['/var/folders/sy/gxxl_n9528qdws_74b5x8mdc0000gn/T/', '/tmp', '/var/tmp', '/usr/tmp', '/Users/vladimir/Projects/cryodaq']

 exited 1 in 407ms:
/Users/vladimir/.matplotlib is not a writable directory
Traceback (most recent call last):
  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/matplotlib/__init__.py", line 545, in _get_config_or_cache_dir
    tmpdir = tempfile.mkdtemp(prefix="matplotlib-")
  File "/Library/Frameworks/Python.framework/Versions/3.14/lib/python3.14/tempfile.py", line 374, in mkdtemp
    prefix, suffix, dir, output_type = _sanitize_params(prefix, suffix, dir)
                                       ~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^
  File "/Library/Frameworks/Python.framework/Versions/3.14/lib/python3.14/tempfile.py", line 126, in _sanitize_params
    dir = gettempdir()
  File "/Library/Frameworks/Python.framework/Versions/3.14/lib/python3.14/tempfile.py", line 316, in gettempdir
    return _os.fsdecode(_gettempdir())
                        ~~~~~~~~~~~^^
  File "/Library/Frameworks/Python.framework/Versions/3.14/lib/python3.14/tempfile.py", line 309, in _gettempdir
    tempdir = _get_default_tempdir()
  File "/Library/Frameworks/Python.framework/Versions/3.14/lib/python3.14/tempfile.py", line 224, in _get_default_tempdir
    raise FileNotFoundError(_errno.ENOENT,
                            "No usable temporary directory found in %s" %
                            dirlist)
FileNotFoundError: [Errno 2] No usable temporary directory found in ['/var/folders/sy/gxxl_n9528qdws_74b5x8mdc0000gn/T/', '/tmp', '/var/tmp', '/usr/tmp', '/Users/vladimir/Projects/cryodaq']

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "<string>", line 1, in <module>
    import cryodaq.engine; print('OK')
    ^^^^^^^^^^^^^^^^^^^^^
  File "/Users/vladimir/Projects/cryodaq/src/cryodaq/engine.py", line 71, in <module>
    from cryodaq.reporting.generator import ReportGenerator
  File "/Users/vladimir/Projects/cryodaq/src/cryodaq/reporting/__init__.py", line 1, in <module>
    from .generator import ReportGenerationResult, ReportGenerator
  File "/Users/vladimir/Projects/cryodaq/src/cryodaq/reporting/generator.py", line 13, in <module>
    from cryodaq.reporting.sections import SECTION_REGISTRY
  File "/Users/vladimir/Projects/cryodaq/src/cryodaq/reporting/sections.py", line 17, in <module>
    import matplotlib
  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/matplotlib/__init__.py", line 1010, in <module>
    rcParams._update_raw(_rc_params_in_file(matplotlib_fname()))
                                            ~~~~~~~~~~~~~~~~^^
  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/matplotlib/__init__.py", line 636, in matplotlib_fname
    for fname in gen_candidates():
                 ~~~~~~~~~~~~~~^^
  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/matplotlib/__init__.py", line 633, in gen_candidates
    yield os.path.join(get_configdir(), 'matplotlibrc')
                       ~~~~~~~~~~~~~^^
  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/matplotlib/__init__.py", line 340, in wrapper
    ret = func(**kwargs)
  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/matplotlib/__init__.py", line 579, in get_configdir
    return _get_config_or_cache_dir(_get_xdg_config_dir)
  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/matplotlib/__init__.py", line 547, in _get_config_or_cache_dir
    raise OSError(
    ...<3 lines>...
        f"variable to a writable directory") from exc
OSError: Matplotlib requires access to a writable cache directory, but there was an issue with the default path (/Users/vladimir/.matplotlib), and a temporary directory could not be created; set the MPLCONFIGDIR environment variable to a writable directory

 succeeded in 563ms:
OK

codex
The targeted test command is blocked by this read-only execution environment because pytest cannot create a temp capture file. Two import probes pass; `cryodaq.engine` exposes a real environment-sensitive import problem around Matplotlib cache/temp dirs that CC did not check.
exec
/opt/homebrew/bin/bash -lc 'rg -n "def export_curve_cof|def _write_cof_export|Chebyshev|zone_count|max_zones|min_points_per_zone" src/cryodaq/analytics/calibration.py' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
1:"""Calibration backend: session storage, Chebyshev fits, and artifact IO."""
195:    """Calibration curve storage and multi-zone Chebyshev fitting."""
222:        max_zones: int = 3,
223:        min_points_per_zone: int = 6,
230:        if len(samples) < max(4, min_points_per_zone):
236:        if len(normalized_samples) < max(4, min_points_per_zone):
253:            max_zones=max(1, max_zones),
254:            min_points_per_zone=max(3, min_points_per_zone),
284:                "zone_count": int(len(zones)),
424:    def export_curve_cof(
430:        """Export calibration curve as .cof (Chebyshev coefficients) format.
875:    def _write_cof_export(self, path: Path, curve: CalibrationCurve) -> None:
876:        """Write .cof format: header + per-zone raw Chebyshev coefficients."""
886:            "# format: Chebyshev T_n(x); raw clipped to [raw_min, raw_max],"
889:        lines.append(f"# zone_count: {len(curve.zones)}")
951:            max_zones=3,
952:            min_points_per_zone=4,
1070:        max_zones: int,
1071:        min_points_per_zone: int,
1074:        if len(raw_values) < (min_points_per_zone * 2) or max_zones <= 1:
1085:            if index < min_points_per_zone or index > len(raw_values) - min_points_per_zone:
1087:            if any(abs(index - boundary) < min_points_per_zone for boundary in boundaries):
1093:                min_points_per_zone=min_points_per_zone,
1096:            if any(abs(refined - boundary) < min_points_per_zone for boundary in boundaries):
1099:            if len(boundaries) >= max_zones - 1:
1107:            if stop - start < min_points_per_zone:
1111:        if len(raw_values) - start < min_points_per_zone and slices:
1192:                fit = cheb.Chebyshev.fit(raw_values, temperatures, deg=order, domain=domain)
1293:        min_points_per_zone: int,
1296:        search_radius = max(3, min_points_per_zone // 2)
1297:        start = max(min_points_per_zone, candidate_index - search_radius)
1298:        stop = min(len(raw_values) - min_points_per_zone, candidate_index + search_radius)

exec
/opt/homebrew/bin/bash -lc "rg -n \"\\.cof|cof|\\.330|330|calibration\" CHANGELOG.md" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
319:  (operator_log, archive, calibration, conductivity, keithley) now
347:  - `src/cryodaq/gui/widgets/calibration_panel.py` (superseded by II.7).
357:  calibration, experiment_workspace, keithley_panel_contract,
358:  main_window_calibration_integration, operator_log_panel,
433:  `src/cryodaq/gui/shell/overlays/calibration_panel.py` replaces the
436:  `calibration_acquisition_status`). CoverageBar migrated from
442:  `calibration_curve_import` (with `QFileDialog.getOpenFileName`
443:  picker per format), `calibration_curve_export` (with
445:  `calibration_runtime_set_global`,
446:  `calibration_runtime_set_channel_policy` (chained via
447:  `calibration_curve_lookup` to resolve `curve_id`). Acquisition
453:  `_ensure_overlay("calibration")` replay; readings routing (shell
458:  `src/cryodaq/gui/widgets/calibration_panel.py` marked DEPRECATED;
847:- **Tier 1 Fix A — calibration channel canonicalization (`a5cd8b7`).**
855:  (`engine.py:370-375`, `calibration_acquisition.py:92-108`).
887:  `gui/widgets/calibration_panel.py` built channel refs в
901:- **Codex R1 finding A.1 — calibration throttle atomicity
943:- +11 from Tier 1 fixes (5 calibration canon, 4 broker isolation,
955:- `a5cd8b7` tier1-a: canonicalize calibration channel identities
959:- `621f98a` post-merge fixes: calibration prefix strip + dedupe imports
985:- **Jules R2: calibration state mutation** — `prepare_srdg_readings()`
1013:  `os.replace()` для experiment sidecars и calibration index/curve.
1033:- **KRDG+SRDG atomic** — calibration readings persist в одной
1253:- **UI** — CSV BOM, sensor diag stretch, calibration stretch, reports
1459:  export). `.330` / `.340` / JSON export.
1517:reports, housekeeping, calibration), GUI workflows (tray status,

exec
/opt/homebrew/bin/bash -lc "rg -n \"asyncio\\.create_task|create_task\\(\" src" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
src/cryodaq/analytics/cooldown_service.py:266:        self._consume_task = asyncio.create_task(
src/cryodaq/analytics/cooldown_service.py:270:        self._predict_task = asyncio.create_task(
src/cryodaq/notifications/escalation.py:70:            task = asyncio.create_task(
src/cryodaq/web/server.py:312:        _pump_task = asyncio.create_task(_broadcast_pump(), name="broadcast_pump")
src/cryodaq/web/server.py:313:        _zmq_task = asyncio.create_task(_zmq_to_ws_bridge(), name="zmq_ws_bridge")
src/cryodaq/core/alarm.py:331:        self._task = asyncio.create_task(self._check_loop(), name="alarm_check_loop")
src/cryodaq/notifications/telegram_commands.py:129:        self._collect_task = asyncio.create_task(self._collect_loop(), name="tg_cmd_collect")
src/cryodaq/notifications/telegram_commands.py:130:        self._poll_task = asyncio.create_task(self._poll_loop(), name="tg_cmd_poll")
src/cryodaq/core/housekeeping.py:368:        self._task = asyncio.create_task(self._loop(), name="housekeeping_service")
src/cryodaq/core/scheduler.py:463:            task = asyncio.create_task(
src/cryodaq/core/scheduler.py:474:            state.task = asyncio.create_task(
src/cryodaq/core/safety_manager.py:221:        self._collect_task = asyncio.create_task(self._collect_loop(), name="safety_collect")
src/cryodaq/core/safety_manager.py:222:        self._monitor_task = asyncio.create_task(self._monitor_loop(), name="safety_monitor")
src/cryodaq/core/safety_manager.py:660:            task = asyncio.get_running_loop().create_task(
src/cryodaq/core/safety_manager.py:702:            shutdown_task = asyncio.create_task(self._keithley.emergency_off())
src/cryodaq/core/safety_manager.py:723:            log_task = asyncio.create_task(
src/cryodaq/core/safety_manager.py:774:            off_task = asyncio.create_task(self._ensure_output_off())
src/cryodaq/analytics/plugin_loader.py:93:        self._process_task = asyncio.create_task(
src/cryodaq/analytics/plugin_loader.py:96:        self._watch_task = asyncio.create_task(self._watch_loop(), name="analytics_watch_loop")
src/cryodaq/notifications/periodic_report.py:115:        self._collect_task = asyncio.create_task(
src/cryodaq/notifications/periodic_report.py:118:        self._report_task = asyncio.create_task(
src/cryodaq/core/zmq_bridge.py:204:        self._task = asyncio.create_task(self._publish_loop(queue), name="zmq_publisher")
src/cryodaq/core/zmq_bridge.py:299:        self._task = asyncio.create_task(self._receive_loop(), name="zmq_subscriber")
src/cryodaq/core/zmq_bridge.py:361:        self._task = loop.create_task(self._serve_loop(), name="zmq_cmd_server")
src/cryodaq/core/disk_monitor.py:48:        self._task = asyncio.create_task(self._check_loop(), name="disk_monitor")
src/cryodaq/core/interlock.py:330:        self._task = asyncio.create_task(self._check_loop(), name="interlock_check_loop")
src/cryodaq/storage/sqlite_writer.py:637:        self._task = asyncio.create_task(self._consume_loop(queue), name="sqlite_writer")
src/cryodaq/engine.py:1153:                            t = asyncio.create_task(
src/cryodaq/engine.py:1607:    throttle_task = asyncio.create_task(_track_runtime_signals(), name="adaptive_throttle_runtime")
src/cryodaq/engine.py:1608:    alarm_v2_feed_task = asyncio.create_task(_alarm_v2_feed_readings(), name="alarm_v2_feed")
src/cryodaq/engine.py:1611:        alarm_v2_tick_task = asyncio.create_task(_alarm_v2_tick(), name="alarm_v2_tick")
src/cryodaq/engine.py:1615:        sd_feed_task = asyncio.create_task(_sensor_diag_feed(), name="sensor_diag_feed")
src/cryodaq/engine.py:1616:        sd_tick_task = asyncio.create_task(_sensor_diag_tick(), name="sensor_diag_tick")
src/cryodaq/engine.py:1620:        vt_feed_task = asyncio.create_task(_vacuum_trend_feed(), name="vacuum_trend_feed")
src/cryodaq/engine.py:1621:        vt_tick_task = asyncio.create_task(_vacuum_trend_tick(), name="vacuum_trend_tick")
src/cryodaq/engine.py:1625:    watchdog_task = asyncio.create_task(

exec
/opt/homebrew/bin/bash -lc "rg -n \"\\bopen\\(\" src" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
src/cryodaq/analytics/calibration.py:417:        with target.open("w", encoding="utf-8", newline="") as handle:
src/cryodaq/analytics/calibration.py:865:        with path.open("w", encoding="utf-8", newline="") as handle:
src/cryodaq/engine.py:383:        with raw_path.open(encoding="utf-8") as fh:
src/cryodaq/engine.py:734:    with config_path.open(encoding="utf-8") as fh:
src/cryodaq/engine.py:1060:        with _plugins_cfg_path.open(encoding="utf-8") as fh:
src/cryodaq/engine.py:1498:            with cooldown_cfg_path.open(encoding="utf-8") as fh:
src/cryodaq/engine.py:1520:            with notifications_cfg.open(encoding="utf-8") as fh:
src/cryodaq/engine.py:1801:    fd = os.open(str(_LOCK_FILE), os.O_CREAT | os.O_RDWR, 0o644)
src/cryodaq/engine.py:1836:        fd = os.open(str(_LOCK_FILE), os.O_RDONLY)
src/cryodaq/analytics/plugin_loader.py:183:                    with config_path.open("r", encoding="utf-8") as fh:
src/cryodaq/notifications/telegram.py:109:        with config_path.open(encoding="utf-8") as fh:
src/cryodaq/launcher.py:330:                probe_fd = os.open(str(lock_path), os.O_RDWR)
src/cryodaq/launcher.py:942:        webbrowser.open(f"http://127.0.0.1:{_WEB_PORT}")
src/cryodaq/storage/csv_export.py:79:        with output_path.open("w", newline="", encoding="utf-8-sig") as fh:
src/cryodaq/gui/widgets/connection_settings.py:63:            with cfg_path.open(encoding="utf-8") as fh:
src/cryodaq/gui/widgets/connection_settings.py:241:        with _LOCAL_CONFIG.open("w", encoding="utf-8") as fh:
src/cryodaq/gui/_theme_loader.py:76:        with SETTINGS_FILE.open(encoding="utf-8") as f:
src/cryodaq/gui/_theme_loader.py:111:        with pack_file.open(encoding="utf-8") as f:
src/cryodaq/gui/_theme_loader.py:159:            with SETTINGS_FILE.open(encoding="utf-8") as f:
src/cryodaq/gui/_theme_loader.py:171:    with SETTINGS_FILE.open("w", encoding="utf-8") as f:
src/cryodaq/gui/_theme_loader.py:183:            with pack_file.open(encoding="utf-8") as f:
src/cryodaq/gui/widgets/overview_panel.py:1774:            with open(path, "w", encoding="utf-8-sig") as f:
src/cryodaq/core/channel_manager.py:93:            with self._config_path.open(encoding="utf-8") as fh:
src/cryodaq/core/channel_manager.py:116:        with save_path.open("w", encoding="utf-8") as fh:
src/cryodaq/gui/widgets/shift_handover.py:53:            with _CONFIG_PATH.open(encoding="utf-8") as fh:
src/cryodaq/core/alarm_config.py:108:        with open(path, encoding="utf-8") as f:
src/cryodaq/core/interlock.py:233:            with config_path.open(encoding="utf-8") as fh:
src/cryodaq/reporting/sections.py:184:        with path.open(encoding="utf-8-sig", newline="") as handle:
src/cryodaq/reporting/sections.py:188:        with path.open(encoding="utf-8", newline="") as handle:
src/cryodaq/reporting/sections.py:522:    with path.open(encoding="utf-8", newline="") as handle:
src/cryodaq/core/housekeeping.py:33:        with config_path.open(encoding="utf-8") as handle:
src/cryodaq/core/housekeeping.py:51:        with path.open(encoding="utf-8") as handle:
src/cryodaq/core/housekeeping.py:148:        with config_path.open(encoding="utf-8") as handle:
src/cryodaq/core/housekeeping.py:437:            with action.source.open("rb") as src, gzip.open(action.target, "wb") as dst:
src/cryodaq/reporting/data.py:91:            with table_path.open(encoding="utf-8", newline="") as handle:
src/cryodaq/drivers/transport/usbtmc.py:87:    async def open(self, resource_str: str) -> None:
src/cryodaq/core/experiment.py:993:            with path.open(encoding="utf-8") as handle:
src/cryodaq/core/experiment.py:1563:        with path.open("w", encoding="utf-8", newline="") as handle:
src/cryodaq/core/experiment.py:1580:        with path.open("w", encoding="utf-8", newline="") as handle:
src/cryodaq/core/experiment.py:1598:        with path.open("w", encoding="utf-8", newline="") as handle:
src/cryodaq/core/experiment.py:1639:                    with path.open(encoding="utf-8", newline="") as handle:
src/cryodaq/core/experiment.py:1657:        with path.open("w", encoding="utf-8", newline="") as handle:
src/cryodaq/core/experiment.py:1782:            with self._instruments_config.open(encoding="utf-8") as handle:
src/cryodaq/core/alarm.py:245:        with config_path.open(encoding="utf-8") as fh:
src/cryodaq/drivers/transport/serial.py:43:    async def open(self, port: str, baudrate: int = 9600, timeout: float = 2.0) -> None:  # noqa: ASYNC109
src/cryodaq/drivers/transport/serial.py:145:            Таймаут чтения в секундах (``None`` → использует значение из ``open()``).
src/cryodaq/core/safety_manager.py:143:        with path.open(encoding="utf-8") as fh:
src/cryodaq/instance_lock.py:33:    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
src/cryodaq/gui/shell/views/analytics_view.py:98:    with _LAYOUT_CONFIG_PATH.open(encoding="utf-8") as f:
src/cryodaq/gui/shell/overlays/calibration_panel.py:83:        with config_path.open(encoding="utf-8") as fh:
src/cryodaq/drivers/instruments/keithley_2604b.py:80:        await self._transport.open(self._resource_str)
src/cryodaq/drivers/transport/gpib.py:143:    async def open(self, resource_str: str, *, timeout_ms: int = _DEFAULT_TIMEOUT_MS) -> None:
src/cryodaq/gui/shell/main_window_v2.py:662:        webbrowser.open(f"http://{host}:{_WEB_PORT}")
src/cryodaq/drivers/instruments/thyracont_vsp63d.py:114:                await self._transport.open(self._resource_str, baudrate=baud)
src/cryodaq/gui/shell/overlays/conductivity_panel.py:1321:            self._flight_log = log_path.open("w", newline="", encoding="utf-8-sig")
src/cryodaq/gui/shell/overlays/conductivity_panel.py:1430:        with out.open("w", newline="", encoding="utf-8-sig") as f:
src/cryodaq/drivers/instruments/lakeshore_218s.py:54:        await self._transport.open(self._resource_str)

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/analytics/calibration.py | sed -n '1,260p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	"""Calibration backend: session storage, Chebyshev fits, and artifact IO."""
     2	
     3	from __future__ import annotations
     4	
     5	import csv
     6	import json
     7	import math
     8	import uuid
     9	import warnings
    10	from dataclasses import dataclass, field
    11	from datetime import UTC, datetime
    12	from pathlib import Path
    13	from typing import Any
    14	
    15	import numpy as np
    16	import yaml
    17	from numpy.polynomial import chebyshev as cheb
    18	
    19	
    20	def _utcnow() -> datetime:
    21	    return datetime.now(UTC)
    22	
    23	
    24	def _parse_time(raw: datetime | str | None) -> datetime | None:
    25	    if raw is None:
    26	        return None
    27	    if isinstance(raw, datetime):
    28	        if raw.tzinfo is None:
    29	            return raw.replace(tzinfo=UTC)
    30	        return raw.astimezone(UTC)
    31	    text = str(raw).strip()
    32	    if not text:
    33	        return None
    34	    if text.endswith("Z"):
    35	        text = f"{text[:-1]}+00:00"
    36	    parsed = datetime.fromisoformat(text)
    37	    if parsed.tzinfo is None:
    38	        return parsed.replace(tzinfo=UTC)
    39	    return parsed.astimezone(UTC)
    40	
    41	
    42	def _json_dict(raw: Any) -> dict[str, Any]:
    43	    if raw is None:
    44	        return {}
    45	    if isinstance(raw, dict):
    46	        return {str(key): value for key, value in raw.items()}
    47	    raise ValueError("Expected dictionary payload.")
    48	
    49	
    50	def _safe_path_fragment(value: str) -> str:
    51	    cleaned = "".join("_" if char in '<>:"/\\|?*' else char for char in str(value).strip())
    52	    return cleaned or "unnamed"
    53	
    54	
    55	@dataclass(frozen=True, slots=True)
    56	class CalibrationSample:
    57	    timestamp: datetime
    58	    reference_channel: str
    59	    reference_temperature: float
    60	    sensor_channel: str
    61	    sensor_raw_value: float
    62	    reference_instrument_id: str = ""
    63	    sensor_instrument_id: str = ""
    64	    experiment_id: str | None = None
    65	    metadata: dict[str, Any] = field(default_factory=dict)
    66	
    67	    def to_payload(self) -> dict[str, Any]:
    68	        return {
    69	            "timestamp": self.timestamp.isoformat(),
    70	            "reference_channel": self.reference_channel,
    71	            "reference_temperature": self.reference_temperature,
    72	            "sensor_channel": self.sensor_channel,
    73	            "sensor_raw_value": self.sensor_raw_value,
    74	            "reference_instrument_id": self.reference_instrument_id,
    75	            "sensor_instrument_id": self.sensor_instrument_id,
    76	            "experiment_id": self.experiment_id,
    77	            "metadata": dict(self.metadata),
    78	        }
    79	
    80	    @classmethod
    81	    def from_payload(cls, payload: dict[str, Any]) -> CalibrationSample:
    82	        return cls(
    83	            timestamp=_parse_time(payload.get("timestamp")) or _utcnow(),
    84	            reference_channel=str(payload.get("reference_channel", "")),
    85	            reference_temperature=float(payload.get("reference_temperature", 0.0)),
    86	            sensor_channel=str(payload.get("sensor_channel", "")),
    87	            sensor_raw_value=float(payload.get("sensor_raw_value", 0.0)),
    88	            reference_instrument_id=str(payload.get("reference_instrument_id", "")),
    89	            sensor_instrument_id=str(payload.get("sensor_instrument_id", "")),
    90	            experiment_id=(
    91	                str(payload.get("experiment_id"))
    92	                if payload.get("experiment_id") not in (None, "")
    93	                else None
    94	            ),
    95	            metadata=_json_dict(payload.get("metadata")),
    96	        )
    97	
    98	
    99	@dataclass(frozen=True, slots=True)
   100	class CalibrationZone:
   101	    raw_min: float
   102	    raw_max: float
   103	    order: int
   104	    coefficients: tuple[float, ...]
   105	    rmse_k: float
   106	    max_abs_error_k: float
   107	    point_count: int
   108	
   109	    def contains(self, raw_value: float) -> bool:
   110	        return self.raw_min <= raw_value <= self.raw_max
   111	
   112	    def evaluate(self, raw_value: float) -> float:
   113	        if self.raw_max <= self.raw_min:
   114	            raise ValueError("Calibration zone has invalid range.")
   115	        clipped = min(max(raw_value, self.raw_min), self.raw_max)
   116	        scaled = ((2.0 * (clipped - self.raw_min)) / (self.raw_max - self.raw_min)) - 1.0
   117	        return float(cheb.chebval(scaled, self.coefficients))
   118	
   119	    def to_payload(self) -> dict[str, Any]:
   120	        return {
   121	            "raw_min": self.raw_min,
   122	            "raw_max": self.raw_max,
   123	            "order": self.order,
   124	            "coefficients": list(self.coefficients),
   125	            "rmse_k": self.rmse_k,
   126	            "max_abs_error_k": self.max_abs_error_k,
   127	            "point_count": self.point_count,
   128	        }
   129	
   130	    @classmethod
   131	    def from_payload(cls, payload: dict[str, Any]) -> CalibrationZone:
   132	        return cls(
   133	            raw_min=float(payload.get("raw_min", 0.0)),
   134	            raw_max=float(payload.get("raw_max", 0.0)),
   135	            order=int(payload.get("order", 1)),
   136	            coefficients=tuple(float(value) for value in payload.get("coefficients", [])),
   137	            rmse_k=float(payload.get("rmse_k", 0.0)),
   138	            max_abs_error_k=float(payload.get("max_abs_error_k", 0.0)),
   139	            point_count=int(payload.get("point_count", 0)),
   140	        )
   141	
   142	
   143	@dataclass(frozen=True, slots=True)
   144	class CalibrationCurve:
   145	    curve_id: str
   146	    sensor_id: str
   147	    fit_timestamp: datetime
   148	    raw_unit: str
   149	    sensor_kind: str
   150	    source_session_ids: tuple[str, ...]
   151	    zones: tuple[CalibrationZone, ...]
   152	    metrics: dict[str, Any] = field(default_factory=dict)
   153	    metadata: dict[str, Any] = field(default_factory=dict)
   154	
   155	    def evaluate(self, raw_value: float) -> float:
   156	        if not self.zones:
   157	            raise ValueError("Calibration curve has no fitted zones.")
   158	        for zone in self.zones:
   159	            if zone.contains(raw_value):
   160	                return zone.evaluate(raw_value)
   161	        if raw_value < self.zones[0].raw_min:
   162	            return self.zones[0].evaluate(raw_value)
   163	        return self.zones[-1].evaluate(raw_value)
   164	
   165	    def to_payload(self) -> dict[str, Any]:
   166	        return {
   167	            "schema_version": 1,
   168	            "curve_id": self.curve_id,
   169	            "sensor_id": self.sensor_id,
   170	            "fit_timestamp": self.fit_timestamp.isoformat(),
   171	            "raw_unit": self.raw_unit,
   172	            "sensor_kind": self.sensor_kind,
   173	            "source_session_ids": list(self.source_session_ids),
   174	            "zones": [zone.to_payload() for zone in self.zones],
   175	            "metrics": dict(self.metrics),
   176	            "metadata": dict(self.metadata),
   177	        }
   178	
   179	    @classmethod
   180	    def from_payload(cls, payload: dict[str, Any]) -> CalibrationCurve:
   181	        return cls(
   182	            curve_id=str(payload.get("curve_id", "")),
   183	            sensor_id=str(payload.get("sensor_id", "")),
   184	            fit_timestamp=_parse_time(payload.get("fit_timestamp")) or _utcnow(),
   185	            raw_unit=str(payload.get("raw_unit", "sensor_unit")),
   186	            sensor_kind=str(payload.get("sensor_kind", "generic")),
   187	            source_session_ids=tuple(str(item) for item in payload.get("source_session_ids", [])),
   188	            zones=tuple(CalibrationZone.from_payload(item) for item in payload.get("zones", [])),
   189	            metrics=_json_dict(payload.get("metrics")),
   190	            metadata=_json_dict(payload.get("metadata")),
   191	        )
   192	
   193	
   194	class CalibrationStore:
   195	    """Calibration curve storage and multi-zone Chebyshev fitting."""
   196	
   197	    _TASK_CV_ORDER_RANGE = tuple(range(7, 13))
   198	    _TASK_DOWNSAMPLE_TARGET = 5000
   199	
   200	    def __init__(self, base_dir: Path | None = None) -> None:
   201	        self._base_dir = base_dir
   202	        self._curves_dir = base_dir / "curves" if base_dir is not None else None
   203	        self._exports_dir = base_dir / "exports" if base_dir is not None else None
   204	        self._index_path = base_dir / "index.yaml" if base_dir is not None else None
   205	        self._curves: dict[str, CalibrationCurve] = {}
   206	        self._assignments: dict[str, dict[str, Any]] = {}
   207	        self._runtime_settings: dict[str, Any] = {
   208	            "global_mode": "off",
   209	            "updated_at": "",
   210	        }
   211	        if self._index_path is not None:
   212	            self._load_index()
   213	
   214	    def fit_curve(
   215	        self,
   216	        sensor_id: str,
   217	        samples: list[CalibrationSample] | tuple[CalibrationSample, ...],
   218	        *,
   219	        raw_unit: str = "sensor_unit",
   220	        sensor_kind: str = "generic",
   221	        source_session_ids: list[str] | tuple[str, ...] | None = None,
   222	        max_zones: int = 3,
   223	        min_points_per_zone: int = 6,
   224	        max_order: int = 12,
   225	        target_rmse_k: float = 0.05,
   226	        metadata: dict[str, Any] | None = None,
   227	    ) -> CalibrationCurve:
   228	        if not sensor_id.strip():
   229	            raise ValueError("sensor_id is required for calibration fit.")
   230	        if len(samples) < max(4, min_points_per_zone):
   231	            raise ValueError("Not enough calibration samples for fitting.")
   232	        normalized_samples = self._preprocess_samples(
   233	            samples,
   234	            downsample_target=self._TASK_DOWNSAMPLE_TARGET,
   235	        )
   236	        if len(normalized_samples) < max(4, min_points_per_zone):
   237	            raise ValueError("Not enough calibration samples for fitting after preprocessing.")
   238	
   239	        temperatures = np.array(
   240	            [sample.reference_temperature for sample in normalized_samples], dtype=float
   241	        )
   242	        raw_values = np.array(
   243	            [sample.sensor_raw_value for sample in normalized_samples], dtype=float
   244	        )
   245	
   246	        if not np.all(np.isfinite(raw_values)) or not np.all(np.isfinite(temperatures)):
   247	            raise ValueError("Calibration samples must contain finite values only.")
   248	        if np.ptp(raw_values) <= 0 or np.ptp(temperatures) <= 0:
   249	            raise ValueError("Calibration raw values must span a non-zero range.")
   250	        zone_slices = self._detect_zone_slices(
   251	            temperatures,
   252	            raw_values,
   253	            max_zones=max(1, max_zones),
   254	            min_points_per_zone=max(3, min_points_per_zone),
   255	            max_order=max(1, max_order),
   256	        )
   257	        zones = self._fit_zone_slices(
   258	            temperatures,
   259	            raw_values,
   260	            zone_slices=zone_slices,

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/engine.py | sed -n '1,110p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	"""Головной процесс CryoDAQ Engine (безголовый).
     2	
     3	Запуск:
     4	    cryodaq-engine          # через entry point
     5	    python -m cryodaq.engine  # напрямую
     6	
     7	Загружает конфигурации, создаёт и связывает все подсистемы:
     8	    drivers → DataBroker →
     9	    [SQLiteWriter, ZMQPublisher, AlarmEngine, InterlockEngine, PluginPipeline]
    10	
    11	Корректное завершение по SIGINT / SIGTERM (Unix) или Ctrl+C (Windows).
    12	"""
    13	
    14	from __future__ import annotations
    15	
    16	import asyncio
    17	import logging
    18	import os
    19	import signal
    20	import sys
    21	import time
    22	from datetime import UTC, datetime
    23	
    24	# Windows: pyzmq требует SelectorEventLoop (не Proactor)
    25	if sys.platform == "win32":
    26	    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    27	from pathlib import Path
    28	from typing import Any
    29	
    30	import yaml
    31	
    32	from cryodaq.analytics.calibration import CalibrationStore
    33	from cryodaq.analytics.plugin_loader import PluginPipeline
    34	from cryodaq.analytics.vacuum_trend import VacuumTrendPredictor
    35	from cryodaq.core.alarm import AlarmEngine
    36	from cryodaq.core.alarm_config import AlarmConfigError, load_alarm_config
    37	from cryodaq.core.alarm_providers import ExperimentPhaseProvider, ExperimentSetpointProvider
    38	from cryodaq.core.alarm_v2 import AlarmEvaluator, AlarmStateManager
    39	from cryodaq.core.broker import DataBroker
    40	from cryodaq.core.calibration_acquisition import (
    41	    CalibrationAcquisitionService,
    42	    CalibrationCommandError,
    43	)
    44	from cryodaq.core.channel_manager import ChannelConfigError, get_channel_manager
    45	from cryodaq.core.channel_state import ChannelStateTracker
    46	from cryodaq.core.disk_monitor import DiskMonitor
    47	from cryodaq.core.event_logger import EventLogger
    48	from cryodaq.core.experiment import ExperimentManager, ExperimentStatus
    49	from cryodaq.core.housekeeping import (
    50	    AdaptiveThrottle,
    51	    HousekeepingConfigError,
    52	    HousekeepingService,
    53	    load_critical_channels_from_alarms_v3,
    54	    load_housekeeping_config,
    55	    load_protected_channel_patterns,
    56	)
    57	from cryodaq.core.interlock import InterlockConfigError, InterlockEngine
    58	from cryodaq.core.operator_log import OperatorLogEntry
    59	from cryodaq.core.rate_estimator import RateEstimator
    60	from cryodaq.core.safety_broker import SafetyBroker
    61	from cryodaq.core.safety_manager import SafetyConfigError, SafetyManager
    62	from cryodaq.core.scheduler import InstrumentConfig, Scheduler
    63	from cryodaq.core.sensor_diagnostics import SensorDiagnosticsEngine
    64	from cryodaq.core.smu_channel import normalize_smu_channel
    65	from cryodaq.core.zmq_bridge import ZMQCommandServer, ZMQPublisher
    66	from cryodaq.drivers.base import Reading
    67	from cryodaq.notifications.escalation import EscalationService
    68	from cryodaq.notifications.periodic_report import PeriodicReporter
    69	from cryodaq.notifications.telegram_commands import TelegramCommandBot
    70	from cryodaq.paths import get_config_dir, get_data_dir, get_project_root
    71	from cryodaq.reporting.generator import ReportGenerator
    72	from cryodaq.storage.sqlite_writer import SQLiteWriter
    73	
    74	logger = logging.getLogger("cryodaq.engine")
    75	
    76	# ---------------------------------------------------------------------------
    77	# Пути по умолчанию (относительно корня проекта)
    78	# ---------------------------------------------------------------------------
    79	
    80	_PROJECT_ROOT = get_project_root()
    81	_CONFIG_DIR = get_config_dir()
    82	_PLUGINS_DIR = _PROJECT_ROOT / "plugins"
    83	_DATA_DIR = get_data_dir()
    84	
    85	# Интервал самодиагностики (секунды)
    86	_WATCHDOG_INTERVAL_S = 30.0
    87	_LOG_GET_TIMEOUT_S = 1.5
    88	_EXPERIMENT_STATUS_TIMEOUT_S = 1.5
    89	
    90	
    91	async def _run_keithley_command(
    92	    action: str,
    93	    cmd: dict[str, Any],
    94	    safety_manager: SafetyManager,
    95	) -> dict[str, Any]:
    96	    """Dispatch channel-scoped Keithley commands to SafetyManager."""
    97	    channel = cmd.get("channel")
    98	
    99	    if action == "keithley_start":
   100	        smu_channel = normalize_smu_channel(channel)
   101	        p = float(cmd.get("p_target", 0))
   102	        v = float(cmd.get("v_comp", 40))
   103	        i = float(cmd.get("i_comp", 1.0))
   104	        return await safety_manager.request_run(p, v, i, channel=smu_channel)
   105	
   106	    if action == "keithley_stop":
   107	        smu_channel = normalize_smu_channel(channel)
   108	        return await safety_manager.request_stop(channel=smu_channel)
   109	
   110	    if action == "keithley_emergency_off":

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/analytics/calibration.py | sed -n '400,455p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   400	    def export_curve_json(self, sensor_id: str, path: Path | None = None) -> Path:
   401	        curve = self._require_curve(sensor_id)
   402	        return self.save_curve(curve, path)
   403	
   404	    def export_curve_table(
   405	        self,
   406	        sensor_id: str,
   407	        *,
   408	        path: Path | None = None,
   409	        points: int = 200,
   410	    ) -> Path:
   411	        curve = self._require_curve(sensor_id)
   412	        target = path or self._curve_directory(curve.sensor_id, curve.curve_id) / "curve_table.csv"
   413	        target.parent.mkdir(parents=True, exist_ok=True)
   414	        raw_min = curve.zones[0].raw_min
   415	        raw_max = curve.zones[-1].raw_max
   416	        raw_grid = np.linspace(raw_min, raw_max, max(points, 2))
   417	        with target.open("w", encoding="utf-8", newline="") as handle:
   418	            writer = csv.writer(handle)
   419	            writer.writerow([f"raw_{curve.raw_unit}", "temperature_K"])
   420	            for raw_value in raw_grid:
   421	                writer.writerow([float(raw_value), curve.evaluate(float(raw_value))])
   422	        return target
   423	
   424	    def export_curve_cof(
   425	        self,
   426	        sensor_id: str,
   427	        *,
   428	        path: Path | None = None,
   429	    ) -> Path:
   430	        """Export calibration curve as .cof (Chebyshev coefficients) format.
   431	
   432	        Unlike .340 which exports sampled breakpoints, .cof preserves the
   433	        raw fit coefficients per zone. Portable: can be re-evaluated by
   434	        any code with numpy.polynomial.chebyshev, no CryoDAQ schema
   435	        dependency.
   436	        """
   437	        curve = self._require_curve(sensor_id)
   438	        target = path or (self._curve_directory(curve.sensor_id, curve.curve_id) / "curve.cof")
   439	        target.parent.mkdir(parents=True, exist_ok=True)
   440	        self._write_cof_export(target, curve)
   441	        self._write_index()
   442	        return target
   443	
   444	    def export_curve_340(
   445	        self,
   446	        sensor_id: str,
   447	        *,
   448	        path: Path | None = None,
   449	        points: int = 200,
   450	    ) -> Path:
   451	        curve = self._require_curve(sensor_id)
   452	        if self._exports_dir is None:
   453	            raise RuntimeError("CalibrationStore base_dir is required for export.")
   454	        target = path or self._curve_340_path(curve.sensor_id, curve.curve_id)
   455	        target.parent.mkdir(parents=True, exist_ok=True)

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/analytics/calibration.py | sed -n '850,905p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   850	            key = (round(item[0], 9), round(item[1], 9))
   851	            if key in seen:
   852	                continue
   853	            seen.add(key)
   854	            deduped.append(item)
   855	        return deduped[: max(points, 2)]
   856	
   857	    def _write_curve_text_export(
   858	        self,
   859	        path: Path,
   860	        curve: CalibrationCurve,
   861	        rows: list[tuple[float, float]],
   862	        *,
   863	        format_name: str,
   864	    ) -> None:
   865	        with path.open("w", encoding="utf-8", newline="") as handle:
   866	            handle.write(f"# CryoDAQ calibration curve export .{format_name}\n")
   867	            handle.write(f"# sensor_id: {curve.sensor_id}\n")
   868	            handle.write(f"# curve_id: {curve.curve_id}\n")
   869	            handle.write(f"# raw_unit: {curve.raw_unit}\n")
   870	            handle.write("# columns: temperature_K, sensor_raw\n")
   871	            writer = csv.writer(handle)
   872	            for temperature_k, raw_value in rows:
   873	                writer.writerow([f"{temperature_k:.9g}", f"{raw_value:.9g}"])
   874	
   875	    def _write_cof_export(self, path: Path, curve: CalibrationCurve) -> None:
   876	        """Write .cof format: header + per-zone raw Chebyshev coefficients."""
   877	        from cryodaq.core.atomic_write import atomic_write_text
   878	
   879	        lines: list[str] = []
   880	        lines.append("# CryoDAQ calibration curve export .cof")
   881	        lines.append(f"# sensor_id: {curve.sensor_id}")
   882	        lines.append(f"# curve_id: {curve.curve_id}")
   883	        lines.append(f"# raw_unit: {curve.raw_unit}")
   884	        lines.append(f"# fit_timestamp: {curve.fit_timestamp.isoformat()}")
   885	        lines.append(
   886	            "# format: Chebyshev T_n(x); raw clipped to [raw_min, raw_max],"
   887	            " then x = 2*(clipped - raw_min)/(raw_max - raw_min) - 1"
   888	        )
   889	        lines.append(f"# zone_count: {len(curve.zones)}")
   890	        lines.append("")
   891	        for index, zone in enumerate(curve.zones, start=1):
   892	            lines.append(f"[zone {index}]")
   893	            lines.append(f"raw_min: {zone.raw_min:.12g}")
   894	            lines.append(f"raw_max: {zone.raw_max:.12g}")
   895	            lines.append(f"order: {zone.order}")
   896	            coefficients = ", ".join(f"{value:.12g}" for value in zone.coefficients)
   897	            lines.append(f"coefficients: {coefficients}")
   898	            lines.append(f"# rmse_k: {zone.rmse_k:.6g}")
   899	            lines.append(f"# max_abs_error_k: {zone.max_abs_error_k:.6g}")
   900	            lines.append(f"# point_count: {zone.point_count}")
   901	            lines.append("")
   902	        atomic_write_text(path, "\n".join(lines))
   903	
   904	    def _import_curve_text(
   905	        self,

exec
/opt/homebrew/bin/bash -lc "nl -ba CHANGELOG.md | sed -n '1448,1465p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
  1448	Полный pipeline калибровки v2: непрерывный сбор SRDG при
  1449	калибровочных экспериментах, post-run pipeline, трёхрежимный GUI.
  1450	
  1451	### Добавлено
  1452	
  1453	- **`CalibrationAcquisitionService`** — непрерывный сбор SRDG
  1454	  параллельно с KRDG при калибровочном эксперименте.
  1455	- **`CalibrationFitter`** — post-run pipeline: извлечение пар из SQLite,
  1456	  адаптивный downsample, Douglas-Peucker breakpoints, Chebyshev fit.
  1457	- **Калибровка GUI** — трёхрежимная вкладка: Setup (выбор каналов,
  1458	  импорт) → Acquisition (live stats, coverage bar) → Results (метрики,
  1459	  export). `.330` / `.340` / JSON export.
  1460	
  1461	### Изменено
  1462	
  1463	- Удалён legacy `CalibrationSessionStore` и ручной workflow.
  1464	
  1465	Диапазон коммитов: `81ef8a6`..`98a5951` (4 commits)

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/engine.py | sed -n '1598,1640p'" in /Users/vladimir/Projects/cryodaq
exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/gui/shell/overlays/conductivity_panel.py | sed -n '1308,1335p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
  1308	    # Flight recorder
  1309	    # ------------------------------------------------------------------
  1310	
  1311	    def _write_flight_log(self, now: float, preds: dict) -> None:
  1312	        if len(self._chain) < 2:
  1313	            return
  1314	        if self._flight_log is None:
  1315	            from cryodaq.paths import get_data_dir
  1316	
  1317	            log_dir = get_data_dir() / "conductivity_logs"
  1318	            log_dir.mkdir(parents=True, exist_ok=True)
  1319	            ts_str = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
  1320	            log_path = log_dir / f"conductivity_{ts_str}.csv"
  1321	            self._flight_log = log_path.open("w", newline="", encoding="utf-8-sig")
  1322	            self._flight_log_writer = csv.writer(self._flight_log)
  1323	            self._flight_log_writer.writerow(
  1324	                [
  1325	                    "timestamp_utc",
  1326	                    "elapsed_s",
  1327	                    "T_hot",
  1328	                    "T_cold",
  1329	                    "dT",
  1330	                    "P",
  1331	                    "R_measured",
  1332	                    "G_measured",
  1333	                    "R_predicted",
  1334	                    "G_predicted",
  1335	                    "percent_settled_hot",

 succeeded in 0ms:
  1598	    await interlock_engine.start()
  1599	    await plugin_pipeline.start()
  1600	    if cooldown_service is not None:
  1601	        await cooldown_service.start()
  1602	    if periodic_reporter is not None:
  1603	        await periodic_reporter.start()
  1604	    if telegram_bot is not None:
  1605	        await telegram_bot.start()
  1606	    await scheduler.start()
  1607	    throttle_task = asyncio.create_task(_track_runtime_signals(), name="adaptive_throttle_runtime")
  1608	    alarm_v2_feed_task = asyncio.create_task(_alarm_v2_feed_readings(), name="alarm_v2_feed")
  1609	    alarm_v2_tick_task: asyncio.Task | None = None
  1610	    if _alarm_v2_configs:
  1611	        alarm_v2_tick_task = asyncio.create_task(_alarm_v2_tick(), name="alarm_v2_tick")
  1612	    sd_feed_task: asyncio.Task | None = None
  1613	    sd_tick_task: asyncio.Task | None = None
  1614	    if sensor_diag is not None:
  1615	        sd_feed_task = asyncio.create_task(_sensor_diag_feed(), name="sensor_diag_feed")
  1616	        sd_tick_task = asyncio.create_task(_sensor_diag_tick(), name="sensor_diag_tick")
  1617	    vt_feed_task: asyncio.Task | None = None
  1618	    vt_tick_task: asyncio.Task | None = None
  1619	    if vacuum_trend is not None:
  1620	        vt_feed_task = asyncio.create_task(_vacuum_trend_feed(), name="vacuum_trend_feed")
  1621	        vt_tick_task = asyncio.create_task(_vacuum_trend_tick(), name="vacuum_trend_tick")
  1622	    await housekeeping_service.start()
  1623	
  1624	    # Watchdog
  1625	    watchdog_task = asyncio.create_task(
  1626	        _watchdog(broker, scheduler, writer, start_ts),
  1627	        name="engine_watchdog",
  1628	    )
  1629	
  1630	    # DiskMonitor — also wires the writer so disk-recovery can clear the
  1631	    # _disk_full flag (Phase 2a H.1).
  1632	    disk_monitor = DiskMonitor(data_dir=_DATA_DIR, broker=broker, sqlite_writer=writer)
  1633	    await disk_monitor.start()
  1634	
  1635	    logger.info(
  1636	        "═══ CryoDAQ Engine запущен ═══ | приборов=%d | тревог=%d | блокировок=%d | mock=%s",
  1637	        len(driver_configs),
  1638	        len(alarm_engine.get_state()),
  1639	        len(interlock_engine.get_state()),
  1640	        mock,

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/web/server.py | sed -n '300,324p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   300	        description="Удалённый мониторинг криогенной системы",
   301	        version=_VERSION,
   302	    )
   303	
   304	    _zmq_task: asyncio.Task[None] | None = None
   305	    _pump_task: asyncio.Task[None] | None = None
   306	
   307	    @application.on_event("startup")
   308	    async def _startup() -> None:
   309	        nonlocal _zmq_task, _pump_task
   310	        # Инициализируем очередь в контексте event loop
   311	        _state.broadcast_q = asyncio.Queue(maxsize=200)
   312	        _pump_task = asyncio.create_task(_broadcast_pump(), name="broadcast_pump")
   313	        _zmq_task = asyncio.create_task(_zmq_to_ws_bridge(), name="zmq_ws_bridge")
   314	        logger.info("Веб-сервер CryoDAQ запущен")
   315	
   316	    @application.on_event("shutdown")
   317	    async def _shutdown() -> None:
   318	        for task in (_zmq_task, _pump_task):
   319	            if task and not task.done():
   320	                task.cancel()
   321	                try:
   322	                    await task
   323	                except asyncio.CancelledError:
   324	                    pass

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/engine.py | sed -n '1680,1785p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
  1680	        pass
  1681	    if alarm_v2_tick_task is not None:
  1682	        alarm_v2_tick_task.cancel()
  1683	        try:
  1684	            await alarm_v2_tick_task
  1685	        except asyncio.CancelledError:
  1686	            pass
  1687	
  1688	    if sd_feed_task is not None:
  1689	        sd_feed_task.cancel()
  1690	        try:
  1691	            await sd_feed_task
  1692	        except asyncio.CancelledError:
  1693	            pass
  1694	    if sd_tick_task is not None:
  1695	        sd_tick_task.cancel()
  1696	        try:
  1697	            await sd_tick_task
  1698	        except asyncio.CancelledError:
  1699	            pass
  1700	
  1701	    if vt_feed_task is not None:
  1702	        vt_feed_task.cancel()
  1703	        try:
  1704	            await vt_feed_task
  1705	        except asyncio.CancelledError:
  1706	            pass
  1707	    if vt_tick_task is not None:
  1708	        vt_tick_task.cancel()
  1709	        try:
  1710	            await vt_tick_task
  1711	        except asyncio.CancelledError:
  1712	            pass
  1713	
  1714	    # Порядок: scheduler → plugins → alarms → interlocks → writer → zmq
  1715	    await scheduler.stop()
  1716	    logger.info("Планировщик остановлен")
  1717	
  1718	    await plugin_pipeline.stop()
  1719	    logger.info("Пайплайн плагинов остановлен")
  1720	
  1721	    if cooldown_service is not None:
  1722	        await cooldown_service.stop()
  1723	        logger.info("CooldownService остановлен")
  1724	
  1725	    if periodic_reporter is not None:
  1726	        await periodic_reporter.stop()
  1727	        logger.info("PeriodicReporter остановлен")
  1728	
  1729	    if telegram_bot is not None:
  1730	        await telegram_bot.stop()
  1731	        logger.info("TelegramCommandBot остановлен")
  1732	
  1733	    await alarm_engine.stop()
  1734	    logger.info("Движок тревог остановлен")
  1735	
  1736	    await interlock_engine.stop()
  1737	    logger.info("Движок блокировок остановлен")
  1738	
  1739	    await safety_manager.stop()
  1740	    logger.info("SafetyManager остановлен: состояние=%s", safety_manager.state.value)
  1741	
  1742	    await disk_monitor.stop()
  1743	    logger.info("DiskMonitor остановлен")
  1744	
  1745	    await housekeeping_service.stop()
  1746	    logger.info("HousekeepingService остановлен")
  1747	
  1748	    await writer.stop()
  1749	    logger.info("SQLite записано: %d", writer.stats.get("total_written", 0))
  1750	
  1751	    await cmd_server.stop()
  1752	    logger.info("ZMQ CommandServer остановлен")
  1753	
  1754	    await zmq_pub.stop()
  1755	    logger.info("ZMQ Publisher остановлен")
  1756	
  1757	    from cryodaq.drivers.transport.gpib import GPIBTransport
  1758	
  1759	    GPIBTransport.close_all_managers()
  1760	    logger.info("GPIB ResourceManagers закрыты")
  1761	
  1762	    uptime = time.monotonic() - start_ts
  1763	    logger.info(
  1764	        "═══ CryoDAQ Engine завершён ═══ | uptime=%.1f с",
  1765	        uptime,
  1766	    )
  1767	
  1768	
  1769	# ---------------------------------------------------------------------------
  1770	# Single-instance guard
  1771	# ---------------------------------------------------------------------------
  1772	
  1773	_LOCK_FILE = get_data_dir() / ".engine.lock"
  1774	
  1775	
  1776	def _is_pid_alive(pid: int) -> bool:
  1777	    """Check if process with given PID exists."""
  1778	    try:
  1779	        if sys.platform == "win32":
  1780	            import ctypes
  1781	
  1782	            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
  1783	            if handle:
  1784	                ctypes.windll.kernel32.CloseHandle(handle)
  1785	                return True

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/engine.py | sed -n '1640,1682p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
  1640	        mock,
  1641	    )
  1642	
  1643	    # --- Ожидание сигнала завершения ---
  1644	    shutdown_event = asyncio.Event()
  1645	
  1646	    def _request_shutdown() -> None:
  1647	        logger.info("Получен сигнал завершения")
  1648	        shutdown_event.set()
  1649	
  1650	    # Регистрация обработчиков сигналов
  1651	    loop = asyncio.get_running_loop()
  1652	    if sys.platform != "win32":
  1653	        loop.add_signal_handler(signal.SIGINT, _request_shutdown)
  1654	        loop.add_signal_handler(signal.SIGTERM, _request_shutdown)
  1655	    else:
  1656	        # Windows: signal.signal работает только в главном потоке
  1657	        signal.signal(signal.SIGINT, lambda *_: _request_shutdown())
  1658	
  1659	    await shutdown_event.wait()
  1660	
  1661	    # --- Корректное завершение ---
  1662	    logger.info("═══ Завершение CryoDAQ Engine ═══")
  1663	
  1664	    watchdog_task.cancel()
  1665	    try:
  1666	        await watchdog_task
  1667	    except asyncio.CancelledError:
  1668	        pass
  1669	
  1670	    throttle_task.cancel()
  1671	    try:
  1672	        await throttle_task
  1673	    except asyncio.CancelledError:
  1674	        pass
  1675	
  1676	    alarm_v2_feed_task.cancel()
  1677	    try:
  1678	        await alarm_v2_feed_task
  1679	    except asyncio.CancelledError:
  1680	        pass
  1681	    if alarm_v2_tick_task is not None:
  1682	        alarm_v2_tick_task.cancel()

exec
/opt/homebrew/bin/bash -lc "rg -n \"_flight_log|close\\(\" src/cryodaq/gui/shell/overlays/conductivity_panel.py" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
247:        self._flight_log = None
248:        self._flight_log_writer = None
873:        self._write_flight_log(now, all_preds)
1311:    def _write_flight_log(self, now: float, preds: dict) -> None:
1314:        if self._flight_log is None:
1321:            self._flight_log = log_path.open("w", newline="", encoding="utf-8-sig")
1322:            self._flight_log_writer = csv.writer(self._flight_log)
1323:            self._flight_log_writer.writerow(
1381:        self._flight_log_writer.writerow(
1403:        self._flight_log.flush()
1406:        if self._flight_log:
1407:            self._flight_log.close()
1408:            self._flight_log = None

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/gui/shell/overlays/conductivity_panel.py | sed -n '1396,1412p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
  1396	                f"{tau_cold:.1f}",
  1397	                f"{T_inf_hot:.6f}",
  1398	                f"{T_inf_cold:.6f}",
  1399	                step,
  1400	                f"{step_P:.6g}",
  1401	            ]
  1402	        )
  1403	        self._flight_log.flush()
  1404	
  1405	    def closeEvent(self, event) -> None:
  1406	        if self._flight_log:
  1407	            self._flight_log.close()
  1408	            self._flight_log = None
  1409	        super().closeEvent(event)
  1410	
  1411	    # ------------------------------------------------------------------
  1412	    # Manual CSV export

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/engine.py | sed -n '1792,1850p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
  1792	
  1793	
  1794	def _acquire_engine_lock() -> int:
  1795	    """Acquire exclusive engine lock via flock/msvcrt. Returns fd.
  1796	
  1797	    If lock is held by a dead process, auto-cleans and retries.
  1798	    Shows helpful error with PID and kill command if lock is live.
  1799	    """
  1800	    _LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
  1801	    fd = os.open(str(_LOCK_FILE), os.O_CREAT | os.O_RDWR, 0o644)
  1802	    try:
  1803	        if sys.platform == "win32":
  1804	            import msvcrt
  1805	
  1806	            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
  1807	        else:
  1808	            import fcntl
  1809	
  1810	            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
  1811	    except OSError:
  1812	        # Lock held by another process (flock/msvcrt is authoritative)
  1813	        os.close(fd)
  1814	        logger.error(
  1815	            "CryoDAQ engine уже запущен (lock: %s).\n"
  1816	            "  Для принудительного запуска: cryodaq-engine --force\n"
  1817	            "  Или завершите процесс через Диспетчер задач (python/pythonw).",
  1818	            _LOCK_FILE,
  1819	        )
  1820	        raise SystemExit(1)
  1821	
  1822	    os.ftruncate(fd, 0)
  1823	    os.lseek(fd, 0, os.SEEK_SET)
  1824	    os.write(fd, f"{os.getpid()}\n".encode())
  1825	    return fd
  1826	
  1827	
  1828	def _force_kill_existing() -> None:
  1829	    """Force-kill any running engine and remove lock."""
  1830	    if not _LOCK_FILE.exists():
  1831	        return
  1832	    # Read PID via os.open — works even when file is locked by msvcrt
  1833	    pid = None
  1834	    fd = None
  1835	    try:
  1836	        fd = os.open(str(_LOCK_FILE), os.O_RDONLY)
  1837	        raw = os.read(fd, 64).decode().strip()
  1838	        pid = int(raw)
  1839	    except (OSError, ValueError):
  1840	        pass
  1841	    finally:
  1842	        if fd is not None:
  1843	            try:
  1844	                os.close(fd)
  1845	            except OSError:
  1846	                pass
  1847	    if pid is None:
  1848	        try:
  1849	            _LOCK_FILE.unlink(missing_ok=True)
  1850	        except OSError:

exec
/opt/homebrew/bin/bash -lc "rg -n \"_acquire_engine_lock|os\\.close\\(lock|lock_fd|engine_lock\" src/cryodaq/engine.py" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
1794:def _acquire_engine_lock() -> int:
1879:def _release_engine_lock(fd: int) -> None:
1918:    lock_fd = _acquire_engine_lock()
1968:        _release_engine_lock(lock_fd)

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/engine.py | sed -n '1868,1972p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
  1868	                break
  1869	        else:
  1870	            logger.error("PID %d не завершился после 5с", pid)
  1871	            raise SystemExit(1)
  1872	    try:
  1873	        _LOCK_FILE.unlink(missing_ok=True)
  1874	    except OSError:
  1875	        logger.debug("Lock file busy (will be released by OS)")
  1876	    logger.info("Старый engine остановлен, lock очищен")
  1877	
  1878	
  1879	def _release_engine_lock(fd: int) -> None:
  1880	    try:
  1881	        os.close(fd)
  1882	    except OSError:
  1883	        pass
  1884	    try:
  1885	        _LOCK_FILE.unlink(missing_ok=True)
  1886	    except OSError:
  1887	        pass
  1888	
  1889	
  1890	# ---------------------------------------------------------------------------
  1891	# Entry point
  1892	# ---------------------------------------------------------------------------
  1893	
  1894	#: Exit code for unrecoverable startup config errors (Phase 2b H.3).
  1895	#: Launcher detects this and refuses to auto-restart.
  1896	ENGINE_CONFIG_ERROR_EXIT_CODE = 2
  1897	
  1898	
  1899	def main() -> None:
  1900	    """Точка входа cryodaq-engine."""
  1901	    import argparse
  1902	    import traceback
  1903	
  1904	    parser = argparse.ArgumentParser(description="CryoDAQ Engine")
  1905	    parser.add_argument("--mock", action="store_true", help="Mock mode (simulated instruments)")
  1906	    parser.add_argument("--force", action="store_true", help="Kill existing engine and take over")
  1907	    args = parser.parse_args()
  1908	
  1909	    from cryodaq.logging_setup import resolve_log_level, setup_logging
  1910	
  1911	    setup_logging("engine", level=resolve_log_level())
  1912	
  1913	    if args.force:
  1914	        _force_kill_existing()
  1915	
  1916	    mock = args.mock or os.environ.get("CRYODAQ_MOCK", "").lower() in ("1", "true")
  1917	
  1918	    lock_fd = _acquire_engine_lock()
  1919	    try:
  1920	        if mock:
  1921	            logger.info("Режим MOCK: реальные приборы не используются")
  1922	        try:
  1923	            asyncio.run(_run_engine(mock=mock))
  1924	        except KeyboardInterrupt:
  1925	            logger.info("Прервано оператором (Ctrl+C)")
  1926	        except yaml.YAMLError as exc:
  1927	            # Phase 2b H.3: a YAML parse error during startup is
  1928	            # unrecoverable by retry — exit with a distinct code so the
  1929	            # launcher refuses to spin in a tight restart loop.
  1930	            logger.critical(
  1931	                "CONFIG ERROR (YAML parse): %s\n%s",
  1932	                exc,
  1933	                traceback.format_exc(),
  1934	            )
  1935	            sys.exit(ENGINE_CONFIG_ERROR_EXIT_CODE)
  1936	        except FileNotFoundError as exc:
  1937	            # Missing required config file at startup is also a config
  1938	            # error: same exit code.
  1939	            logger.critical(
  1940	                "CONFIG ERROR (file not found): %s\n%s",
  1941	                exc,
  1942	                traceback.format_exc(),
  1943	            )
  1944	            sys.exit(ENGINE_CONFIG_ERROR_EXIT_CODE)
  1945	        except (
  1946	            SafetyConfigError,
  1947	            AlarmConfigError,
  1948	            InterlockConfigError,
  1949	            HousekeepingConfigError,
  1950	            ChannelConfigError,
  1951	        ) as exc:
  1952	            labels = {
  1953	                SafetyConfigError: "safety",
  1954	                AlarmConfigError: "alarm",
  1955	                InterlockConfigError: "interlock",
  1956	                HousekeepingConfigError: "housekeeping",
  1957	                ChannelConfigError: "channel",
  1958	            }
  1959	            label = labels.get(type(exc), "config")
  1960	            logger.critical(
  1961	                "CONFIG ERROR (%s config): %s\n%s",
  1962	                label,
  1963	                exc,
  1964	                traceback.format_exc(),
  1965	            )
  1966	            sys.exit(ENGINE_CONFIG_ERROR_EXIT_CODE)
  1967	    finally:
  1968	        _release_engine_lock(lock_fd)
  1969	
  1970	
  1971	if __name__ == "__main__":
  1972	    main()

exec
/opt/homebrew/bin/bash -lc "nl -ba docs/ORCHESTRATION.md | sed -n '629,740p'" in /Users/vladimir/Projects/cryodaq
exec
/opt/homebrew/bin/bash -lc 'git cat-file -p HEAD' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
tree 38f00b81219f6671238719750345b2fa55fdf24e
parent c1e5a20be788e40f4941505861689f9473624576
author Vladimir Fomenko <polsovatel111@gmail.com> 1777331709 +0300
committer Vladimir Fomenko <polsovatel111@gmail.com> 1777331709 +0300

artifacts: commit cof migration + cof-gui audit consultations + recon

Per ORCHESTRATION §6.4, consultant prompt + response files belong
under artifacts/consultations/<date>/<topic>/. These cover dual-
verifier audits for .cof backend migration (Codex + Gemini) and
.cof GUI wiring (Codex + Gemini).

Also commits pre-/ultrareview recon doc.

Includes:
- 2026-04-28-cof-migration/ (4 files: prompt+response × 2 verifiers)
- 2026-04-28-cof-gui-audit/ (4 files: prompt+response × 2 verifiers)
- artifacts/2026-04-28-pre-ultrareview-recon.md (recon inventory)

Ref: artifacts/handoffs/2026-04-28-cof-{migration,gui}-review.md
Batch: phase-D / consultations-archive
Risk: docs only.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

 succeeded in 0ms:
   629	## 14. Verification practices
   630	
   631	Added 2026-04-28 (v1.2) consolidating recon, verification, and
   632	dual-verifier patterns surfaced through vault build, vault audit,
   633	B1 investigation, and `.cof` migration sessions.
   634	
   635	### 14.1 Recon before execution
   636	
   637	Architect plans contain stale assumptions. Before executing any
   638	multi-step plan, CC performs recon (read-only) and reports actual
   639	state vs plan-expected state:
   640	
   641	- `git status` + `git log -3 --oneline`
   642	- `git tag -l` if plan references tags
   643	- Inventory of touched files (existence, last_modified)
   644	- Dependency state (skills, configs, worktrees) per plan scope
   645	
   646	If reality differs materially from plan: STOP, report diff, await
   647	architect adjustment. If reality matches: proceed.
   648	
   649	This pattern caught vault folder collision (overnight build),
   650	retroactive tag execution memory gap, mystery `channels.yaml`
   651	modification — each would have caused silent corruption if CC
   652	had executed the plan blindly.
   653	
   654	### 14.2 Dual-verifier complementary review
   655	
   656	Codex (literal) and Gemini (structural) have non-overlapping
   657	strengths. Pair them for non-trivial code review:
   658	
   659	- **Codex** (`gpt-5.5 high`): verifies declared scope file-by-file,
   660	  line-level precision, file:line citations. Strong on factual
   661	  correctness within stated boundaries. Tends to NOT grep callers
   662	  or check downstream impact unless prompted explicitly.
   663	
   664	- **Gemini** (`gemini-3.1-pro-preview`): wide-context audit, finds
   665	  cross-file inconsistency, caller-impact, doc-vs-code drift. 1M
   666	  context lets it read related files Codex would skip. Verbose
   667	  by default — needs explicit output cap and table-first format.
   668	
   669	The 2026-04-28 `.cof` migration audit demonstrated the pattern:
   670	Codex CONDITIONAL on `calibration.py` with 1 LOW finding (all
   671	declared scope green). Gemini CRITICAL — found `engine.py` still
   672	called removed `export_curve_330()`, missed by Codex because
   673	Codex didn't grep caller sites. Without Gemini, the merge would
   674	have shipped a runtime `AttributeError`.
   675	
   676	Pair both verifiers when:
   677	- Public API changes (callers in unknown locations)
   678	- Removal of exported names (must grep all callers)
   679	- Structural refactor across multiple files
   680	- Doc claims that reference code state
   681	
   682	Skip dual-verifier when:
   683	- Single-file localized change with clear scope
   684	- Test-only addition
   685	- Pure documentation update without code claims
   686	
   687	### 14.3 Propagation gap when fixing flagged content
   688	
   689	Audit findings frequently surface in one location while equivalent
   690	stale claims exist in others. When applying a fix to a flagged
   691	note/file/doc:
   692	
   693	1. Grep all related artifacts for the corrected claim
   694	2. Fix all instances in single batch
   695	3. Don't merge until grep is clean
   696	
   697	The 2026-04-27 vault audit caught Т4 interlock fact landing
   698	correctly in `Cyrillic homoglyph` note while staying stale in
   699	`Hardware setup` AND `LakeShore 218S` See-also section. Three
   700	notes, one fact, propagation incomplete because audit fixes were
   701	per-flagged-file rather than per-claim.
   702	
   703	Same pattern applies to repo: removing `export_curve_330` from
   704	`calibration.py` without removing the caller in `engine.py` is
   705	the same bug class one level higher.
   706	
   707	Discipline: before committing, `grep -rn <claim>` across the
   708	edit's blast radius. Repository or vault, doesn't matter.
   709	
   710	### 14.4 Cross-branch divergence check
   711	
   712	Before any cross-branch operation (merge, cherry-pick, rebase,
   713	feature work depending on master state):
   714	
   715	```
   716	git rev-list --left-right --count master...feat/branch
   717	```
   718	
   719	Format: `<commits-on-master-not-in-branch> <commits-on-branch-not-in-master>`.
   720	
   721	Outputs to interpret:
   722	- `0 N` — branch is ahead, clean fast-forward possible
   723	- `M 0` — branch is behind, rebase or merge master in first
   724	- `M N` — both diverged, merge will be no-ff with potential
   725	  conflicts
   726	- `0 0` — branches identical (suspicious — verify intent)
   727	
   728	Run before merge to catch unexpected drift. Run before starting
   729	work on a branch to know whether rebase is needed.
   730	
   731	### 14.5 rtk-ai proxy filters merge commits
   732	
   733	The rtk-ai proxy compresses shell output before reaching CC's
   734	context. Side-effect: `git log --oneline` may omit merge commits
   735	from display, making merge commits invisible without explicit
   736	verification.
   737	
   738	When verifying merge state or parent SHAs, use direct git commands
   739	that bypass abbreviated formats:
   740	

exec
/opt/homebrew/bin/bash -lc 'git log -1 --oneline' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
95240ae artifacts: commit cof migration + cof-gui audit consultations + recon

exec
/opt/homebrew/bin/bash -lc "rg -n \"v1\\.2|Verification practices|14\\.5\" docs/ORCHESTRATION.md" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
3:**Authoritative as of 2026-04-28 (v1.2).** Supersedes ad-hoc multi-agent
4:coordination from 2026-04-21 to 2026-04-23. v1.2 incorporates calibration
629:## 14. Verification practices
631:Added 2026-04-28 (v1.2) consolidating recon, verification, and
731:### 14.5 rtk-ai proxy filters merge commits
763:(web), 2026-04-23 (v1.1) — extended 2026-04-28 (v1.2).*

codex
I have enough evidence for the audit. Before closing, I’m applying the verification-before-completion workflow and then I’ll attempt to write the requested response file; the sandbox may reject the write because this session is read-only.
exec
/opt/homebrew/bin/bash -lc "sed -n '1,220p' /Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/verification-before-completion/SKILL.md" in /Users/vladimir/Projects/cryodaq
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
/opt/homebrew/bin/bash -lc 'find artifacts/consultations/2026-04-28-pre-ultrareview -maxdepth 1 -type f -print | sort' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
artifacts/consultations/2026-04-28-pre-ultrareview/codex-recon-audit.prompt.md
artifacts/consultations/2026-04-28-pre-ultrareview/codex-recon-audit.response.md
artifacts/consultations/2026-04-28-pre-ultrareview/gemini-recon-audit.prompt.md
artifacts/consultations/2026-04-28-pre-ultrareview/gemini-recon-audit.response.md

exec
/opt/homebrew/bin/bash -lc 'nl -ba artifacts/consultations/2026-04-28-pre-ultrareview/codex-recon-audit.response.md' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	Reading additional input from stdin...
     2	OpenAI Codex v0.124.0 (research preview)
     3	--------
     4	workdir: /Users/vladimir/Projects/cryodaq
     5	model: gpt-5.5
     6	provider: openai
     7	approval: never
     8	sandbox: read-only
     9	reasoning effort: high
    10	reasoning summaries: none
    11	session id: 019dd13a-9158-7630-8e07-94aeff2cc9aa
    12	--------
    13	user
    14	Model: gpt-5.5
    15	Reasoning effort: high
    16	
    17	# Pre-/ultrareview recon audit — Codex literal verifier
    18	
    19	## Mission
    20	CC produced artifacts/2026-04-28-pre-ultrareview-recon.md identifying
    21	4 pending items. Verify the recon is complete and accurate. What did
    22	CC miss?
    23	
    24	## What to verify
    25	
    26	### A. CC's recon claims
    27	Read artifacts/2026-04-28-pre-ultrareview-recon.md, then verify each
    28	claim against actual repo state.
    29	
    30	- A1: "ORCHESTRATION v1.2 committed" — grep docs/ORCHESTRATION.md for
    31	  "## 14. Verification practices" and "### 14.5". Both must be present.
    32	- A2: "Tags v0.33.0–v0.39.0" — run: git tag -l "v0.*" --sort=v:refname
    33	- A3: "No doc drift in README.md" — grep README.md for ".330" — should
    34	  show only "`.330` removed" (the explicit removal note on line ~84).
    35	- A4: "Root .md whitelist clean" — list repo root .md files,
    36	  cross-check against ORCHESTRATION §6 whitelist
    37	- A5: "All remaining .330 hits intentional regression tests" —
    38	  grep -rn "\.330" src/ tests/ and verify each hit is in a test
    39	  that explicitly verifies removal (not a live code path)
    40	
    41	### B. What CC didn't check (likely blindspots)
    42	- B1: Test suite passes — run: .venv/bin/pytest tests/analytics/test_calibration.py tests/gui/shell/overlays/test_calibration_panel.py tests/core/test_calibration_commands.py -q
    43	- B2: Calibration module imports cleanly — .venv/bin/python -c "from cryodaq.analytics.calibration import CalibrationStore; print('OK')"
    44	- B3: GUI calibration overlay imports cleanly — .venv/bin/python -c "import os; os.environ['QT_QPA_PLATFORM']='offscreen'; from cryodaq.gui.shell.overlays.calibration_panel import CalibrationPanel; print('OK')"
    45	- B4: Engine imports cleanly — .venv/bin/python -c "import cryodaq.engine; print('OK')"
    46	- B5: No stale TODO/FIXME referencing removed export_curve_330 — grep -rn "TODO.*330\|FIXME.*330" src/
    47	
    48	### C. Likely /ultrareview findings (predict top-5)
    49	Rank the 5 issues most likely to surface if /ultrareview ran now.
    50	Examples to check:
    51	- Type coverage gaps in calibration.py (export_curve_cof return type, _write_cof_export None return)
    52	- Async task leaks (search for asyncio.create_task without cancel/await)
    53	- Resource cleanup (search for open() without context manager in src/)
    54	- Missing CHANGELOG entry for .cof migration
    55	- export_curve_cof() docstring references "Chebyshev" but no zone-count validation
    56	
    57	## Source files
    58	- artifacts/2026-04-28-pre-ultrareview-recon.md
    59	- docs/ORCHESTRATION.md
    60	- src/cryodaq/analytics/calibration.py
    61	- src/cryodaq/engine.py
    62	- src/cryodaq/gui/shell/overlays/calibration_panel.py
    63	- tests/analytics/test_calibration.py
    64	- tests/gui/shell/overlays/test_calibration_panel.py
    65	- CHANGELOG.md (check for .cof migration entry)
    66	
    67	## Output
    68	Three sections:
    69	1. **CC recon verification** — per-claim PASS/FAIL with file:line
    70	2. **Missed by CC** — itemized blindspots with severity
    71	3. **Likely /ultrareview findings** — top-5 ranked
    72	
    73	Final verdict: RECON COMPLETE / RECON HAS GAPS / REPO NOT READY.
    74	Hard cap: 3000 words. NO prelude.
    75	
    76	Write output to:
    77	~/Projects/cryodaq/artifacts/consultations/2026-04-28-pre-ultrareview/codex-recon-audit.response.md
    78	codex
    79	Using `superpowers:using-superpowers` to satisfy the session workflow requirement, then I’ll run the requested literal checks against the repo.
    80	exec
    81	/opt/homebrew/bin/bash -lc "sed -n '1,220p' /Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/2e3f0bd9b95ad1fc5c9d0bfd20e0849038250c23/skills/using-superpowers/SKILL.md" in /Users/vladimir/Projects/cryodaq
    82	 exited 1 in 0ms:
    83	sed: /Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/2e3f0bd9b95ad1fc5c9d0bfd20e0849038250c23/skills/using-superpowers/SKILL.md: No such file or directory
    84	
    85	codex
    86	The listed Superpowers skill path is stale in this workspace, so I’m locating the installed skill file and continuing with the same verification flow.
    87	exec
    88	/opt/homebrew/bin/bash -lc "rg --files /Users/vladimir/.codex | rg 'using-superpowers/SKILL\\.md"'$|Superpowers|superpowers'"'" in /Users/vladimir/Projects/cryodaq
    89	 succeeded in 0ms:
    90	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/assets/superpowers-small.svg
    91	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/assets/app-icon.png
    92	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/subagent-driven-development/code-quality-reviewer-prompt.md
    93	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/subagent-driven-development/SKILL.md
    94	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/subagent-driven-development/agents/openai.yaml
    95	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/subagent-driven-development/implementer-prompt.md
    96	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/subagent-driven-development/spec-reviewer-prompt.md
    97	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/verification-before-completion/SKILL.md
    98	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/verification-before-completion/agents/openai.yaml
    99	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/writing-skills/graphviz-conventions.dot
   100	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/writing-skills/SKILL.md
   101	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/writing-skills/persuasion-principles.md
   102	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/writing-skills/examples/CLAUDE_MD_TESTING.md
   103	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/writing-skills/anthropic-best-practices.md
   104	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/writing-skills/render-graphs.js
   105	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/writing-skills/testing-skills-with-subagents.md
   106	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/writing-skills/agents/openai.yaml
   107	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/using-superpowers/SKILL.md
   108	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/receiving-code-review/SKILL.md
   109	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/receiving-code-review/agents/openai.yaml
   110	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/using-superpowers/agents/openai.yaml
   111	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/requesting-code-review/SKILL.md
   112	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/using-superpowers/references/gemini-tools.md
   113	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/using-superpowers/references/codex-tools.md
   114	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/using-superpowers/references/copilot-tools.md
   115	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/requesting-code-review/agents/openai.yaml
   116	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/requesting-code-review/code-reviewer.md
   117	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/writing-plans/SKILL.md
   118	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/systematic-debugging/find-polluter.sh
   119	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/systematic-debugging/condition-based-waiting-example.ts
   120	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/systematic-debugging/root-cause-tracing.md
   121	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/systematic-debugging/test-pressure-3.md
   122	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/systematic-debugging/SKILL.md
   123	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/systematic-debugging/defense-in-depth.md
   124	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/systematic-debugging/test-academic.md
   125	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/systematic-debugging/CREATION-LOG.md
   126	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/systematic-debugging/test-pressure-2.md
   127	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/systematic-debugging/condition-based-waiting.md
   128	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/systematic-debugging/test-pressure-1.md
   129	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/executing-plans/SKILL.md
   130	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/dispatching-parallel-agents/SKILL.md
   131	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/CODE_OF_CONDUCT.md
   132	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/LICENSE
   133	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/writing-plans/agents/openai.yaml
   134	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/writing-plans/plan-document-reviewer-prompt.md
   135	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/systematic-debugging/agents/openai.yaml
   136	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/brainstorming/spec-document-reviewer-prompt.md
   137	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/brainstorming/SKILL.md
   138	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/executing-plans/agents/openai.yaml
   139	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/brainstorming/visual-companion.md
   140	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/dispatching-parallel-agents/agents/openai.yaml
   141	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/README.md
   142	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/using-git-worktrees/SKILL.md
   143	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/agents/code-reviewer.md
   144	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/test-driven-development/testing-anti-patterns.md
   145	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/test-driven-development/SKILL.md
   146	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/finishing-a-development-branch/SKILL.md
   147	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/brainstorming/scripts/helper.js
   148	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/brainstorming/scripts/server.cjs
   149	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/brainstorming/scripts/start-server.sh
   150	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/brainstorming/scripts/frame-template.html
   151	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/brainstorming/scripts/stop-server.sh
   152	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/using-git-worktrees/agents/openai.yaml
   153	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/brainstorming/agents/openai.yaml
   154	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/test-driven-development/agents/openai.yaml
   155	/Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/finishing-a-development-branch/agents/openai.yaml
   156	
   157	exec
   158	/opt/homebrew/bin/bash -lc "sed -n '1,220p' /Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/using-superpowers/SKILL.md" in /Users/vladimir/Projects/cryodaq
   159	 succeeded in 0ms:
   160	---
   161	name: using-superpowers
   162	description: Use when starting any conversation - establishes how to find and use skills, requiring Skill tool invocation before ANY response including clarifying questions
   163	---
   164	
   165	<SUBAGENT-STOP>
   166	If you were dispatched as a subagent to execute a specific task, skip this skill.
   167	</SUBAGENT-STOP>
   168	
   169	<EXTREMELY-IMPORTANT>
   170	If you think there is even a 1% chance a skill might apply to what you are doing, you ABSOLUTELY MUST invoke the skill.
   171	
   172	IF A SKILL APPLIES TO YOUR TASK, YOU DO NOT HAVE A CHOICE. YOU MUST USE IT.
   173	
   174	This is not negotiable. This is not optional. You cannot rationalize your way out of this.
   175	</EXTREMELY-IMPORTANT>
   176	
   177	## Instruction Priority
   178	
   179	Superpowers skills override default system prompt behavior, but **user instructions always take precedence**:
   180	
   181	1. **User's explicit instructions** (CLAUDE.md, GEMINI.md, AGENTS.md, direct requests) — highest priority
   182	2. **Superpowers skills** — override default system behavior where they conflict
   183	3. **Default system prompt** — lowest priority
   184	
   185	If CLAUDE.md, GEMINI.md, or AGENTS.md says "don't use TDD" and a skill says "always use TDD," follow the user's instructions. The user is in control.
   186	
   187	## How to Access Skills
   188	
   189	**In Claude Code:** Use the `Skill` tool. When you invoke a skill, its content is loaded and presented to you—follow it directly. Never use the Read tool on skill files.
   190	
   191	**In Copilot CLI:** Use the `skill` tool. Skills are auto-discovered from installed plugins. The `skill` tool works the same as Claude Code's `Skill` tool.
   192	
   193	**In Gemini CLI:** Skills activate via the `activate_skill` tool. Gemini loads skill metadata at session start and activates the full content on demand.
   194	
   195	**In other environments:** Check your platform's documentation for how skills are loaded.
   196	
   197	## Platform Adaptation
   198	
   199	Skills use Claude Code tool names. Non-CC platforms: see `references/copilot-tools.md` (Copilot CLI), `references/codex-tools.md` (Codex) for tool equivalents. Gemini CLI users get the tool mapping loaded automatically via GEMINI.md.
   200	
   201	# Using Skills
   202	
   203	## The Rule
   204	
   205	**Invoke relevant or requested skills BEFORE any response or action.** Even a 1% chance a skill might apply means that you should invoke the skill to check. If an invoked skill turns out to be wrong for the situation, you don't need to use it.
   206	
   207	```dot
   208	digraph skill_flow {
   209	    "User message received" [shape=doublecircle];
   210	    "About to EnterPlanMode?" [shape=doublecircle];
   211	    "Already brainstormed?" [shape=diamond];
   212	    "Invoke brainstorming skill" [shape=box];
   213	    "Might any skill apply?" [shape=diamond];
   214	    "Invoke Skill tool" [shape=box];
   215	    "Announce: 'Using [skill] to [purpose]'" [shape=box];
   216	    "Has checklist?" [shape=diamond];
   217	    "Create TodoWrite todo per item" [shape=box];
   218	    "Follow skill exactly" [shape=box];
   219	    "Respond (including clarifications)" [shape=doublecircle];
   220	
   221	    "About to EnterPlanMode?" -> "Already brainstormed?";
   222	    "Already brainstormed?" -> "Invoke brainstorming skill" [label="no"];
   223	    "Already brainstormed?" -> "Might any skill apply?" [label="yes"];
   224	    "Invoke brainstorming skill" -> "Might any skill apply?";
   225	
   226	    "User message received" -> "Might any skill apply?";
   227	    "Might any skill apply?" -> "Invoke Skill tool" [label="yes, even 1%"];
   228	    "Might any skill apply?" -> "Respond (including clarifications)" [label="definitely not"];
   229	    "Invoke Skill tool" -> "Announce: 'Using [skill] to [purpose]'";
   230	    "Announce: 'Using [skill] to [purpose]'" -> "Has checklist?";
   231	    "Has checklist?" -> "Create TodoWrite todo per item" [label="yes"];
   232	    "Has checklist?" -> "Follow skill exactly" [label="no"];
   233	    "Create TodoWrite todo per item" -> "Follow skill exactly";
   234	}
   235	```
   236	
   237	## Red Flags
   238	
   239	These thoughts mean STOP—you're rationalizing:
   240	
   241	| Thought | Reality |
   242	|---------|---------|
   243	| "This is just a simple question" | Questions are tasks. Check for skills. |
   244	| "I need more context first" | Skill check comes BEFORE clarifying questions. |
   245	| "Let me explore the codebase first" | Skills tell you HOW to explore. Check first. |
   246	| "I can check git/files quickly" | Files lack conversation context. Check for skills. |
   247	| "Let me gather information first" | Skills tell you HOW to gather information. |
   248	| "This doesn't need a formal skill" | If a skill exists, use it. |
   249	| "I remember this skill" | Skills evolve. Read current version. |
   250	| "This doesn't count as a task" | Action = task. Check for skills. |
   251	| "The skill is overkill" | Simple things become complex. Use it. |
   252	| "I'll just do this one thing first" | Check BEFORE doing anything. |
   253	| "This feels productive" | Undisciplined action wastes time. Skills prevent this. |
   254	| "I know what that means" | Knowing the concept ≠ using the skill. Invoke it. |
   255	
   256	## Skill Priority
   257	
   258	When multiple skills could apply, use this order:
   259	
   260	1. **Process skills first** (brainstorming, debugging) - these determine HOW to approach the task
   261	2. **Implementation skills second** (frontend-design, mcp-builder) - these guide execution
   262	
   263	"Let's build X" → brainstorming first, then implementation skills.
   264	"Fix this bug" → debugging first, then domain-specific skills.
   265	
   266	## Skill Types
   267	
   268	**Rigid** (TDD, debugging): Follow exactly. Don't adapt away discipline.
   269	
   270	**Flexible** (patterns): Adapt principles to context.
   271	
   272	The skill itself tells you which.
   273	
   274	## User Instructions
   275	
   276	Instructions say WHAT, not HOW. "Add X" or "Fix Y" doesn't mean skip workflows.
   277	
   278	codex
   279	I’m gathering the recon text and the exact repo evidence first: orchestration markers, tag list, README `.330` hits, root markdown files, and source/test `.330` references.
   280	exec
   281	/opt/homebrew/bin/bash -lc 'nl -ba artifacts/2026-04-28-pre-ultrareview-recon.md' in /Users/vladimir/Projects/cryodaq
   282	 succeeded in 0ms:
   283	     1	# Pre-/ultrareview recon — 2026-04-28
   284	     2	
   285	     3	## Repo state
   286	     4	
   287	     5	- **HEAD:** `c1e5a20` — `merge: GUI .cof wiring (deferred follow-up from .cof migration)`
   288	     6	  - 2 parents confirmed via `git cat-file -p HEAD`: `4c44a38` (master pre-merge) + `b254de2` (branch tip)
   289	     7	- **Tags:** v0.33.0 → v0.39.0 (7 tags, latest: v0.39.0)
   290	     8	- **Local uncommitted changes:** None
   291	     9	- **Uncommitted ORCHESTRATION v1.2:** No — committed at `4c44a38` (2026-04-27 23:14)
   292	    10	
   293	    11	## Active branches (5 local)
   294	    12	
   295	    13	| Branch | Status | Notes |
   296	    14	|--------|--------|-------|
   297	    15	| `master` | HEAD, clean | c1e5a20 |
   298	    16	| `codex/safe-merge-b1-truth-recovery` | **[ahead 7]** of origin | B1 vault investigation; 7 commits not pushed/merged. Unclear if closed. |
   299	    17	| `experiment/iv7-ipc-transport` | Active worktree | `.worktrees/experiment-iv7-ipc-transport` at `63a3fed`. In-progress — do not touch. |
   300	    18	| `feat/cof-calibration-export` | Merged to master | Can be deleted. |
   301	    19	| `feat/cof-gui-wiring` | Merged to master | Can be deleted. |
   302	    20	| `feat/launcher-sigterm-handler` | Not merged | `9a8412e` — status unknown; handoff exists at `artifacts/handoffs/2026-04-27-launcher-sigterm-review.md`. |
   303	    21	
   304	    22	## Worktrees (1 active)
   305	    23	
   306	    24	- `~/Projects/cryodaq/.worktrees/experiment-iv7-ipc-transport` at `63a3fed [experiment/iv7-ipc-transport]`
   307	    25	
   308	    26	## Untracked files (8 files, 2 directories)
   309	    27	
   310	    28	All in `artifacts/consultations/2026-04-28-*` — consultation prompt + response files from this session's .cof audits. Per ORCHESTRATION §6.2 these belong committed.
   311	    29	
   312	    30	```
   313	    31	artifacts/consultations/2026-04-28-cof-gui-audit/codex-cof-gui-audit.prompt.md
   314	    32	artifacts/consultations/2026-04-28-cof-gui-audit/codex-cof-gui-audit.response.md
   315	    33	artifacts/consultations/2026-04-28-cof-gui-audit/gemini-cof-gui-audit.prompt.md
   316	    34	artifacts/consultations/2026-04-28-cof-gui-audit/gemini-cof-gui-audit.response.md
   317	    35	artifacts/consultations/2026-04-28-cof-migration/codex-cof-audit.prompt.md
   318	    36	artifacts/consultations/2026-04-28-cof-migration/codex-cof-audit.response.md
   319	    37	artifacts/consultations/2026-04-28-cof-migration/gemini-cof-audit.prompt.md
   320	    38	artifacts/consultations/2026-04-28-cof-migration/gemini-cof-audit.response.md
   321	    39	```
   322	    40	
   323	    41	## Repo root .md violations: 0
   324	    42	
   325	    43	All 19 root .md files match ORCHESTRATION §6.2 whitelist:
   326	    44	`CC_PROMPT_*.md`, `HANDOFF_*.md`, `SESSION_DETAIL_*.md`, `CHANGELOG.md`, `CLAUDE.md`, `CODEX_ARCHITECTURE_CONTROL_PLANE.md`, `DOC_REALITY_MAP.md`, `PROJECT_STATUS.md`, `README.md`, `RELEASE_CHECKLIST.md`, `ROADMAP.md`, `THIRD_PARTY_NOTICES.md`. No violations.
   327	    45	
   328	    46	## GUI .330 outstanding: 0 (all intentional)
   329	    47	
   330	    48	All remaining `.330` strings in tests are deliberate:
   331	    49	- `test_calibration_panel.py:360` — `assert "curve_330_path" not in cmd` (negative assertion)
   332	    50	- `test_calibration.py:359-367` — `test_export_curve_330_removed` regression guard + `fake_330` fixture for rejection test
   333	    51	
   334	    52	No spurious `.330` references in `src/`. Phase D fully closed.
   335	    53	
   336	    54	## Doc drift (Phase II.x references): LOW RISK
   337	    55	
   338	    56	`grep "II\.13|dual-shell|Phase II\."` found hits only in:
   339	    57	- `docs/phase-ui-1/phase_ui_v2_roadmap.md` — historical phase tracking (expected)
   340	    58	- `docs/phase-ui-1/ui_refactor_context.md` — context doc (expected)
   341	    59	- `docs/operator_manual.md` — future work reference ("Phase II.9 rebuild")
   342	    60	- `docs/design-system/` — component docs (expected historical context)
   343	    61	
   344	    62	No hits in `CLAUDE.md` or `README.md`. No actionable drift for pre-/ultrareview.
   345	    63	
   346	    64	## Stale artifacts: 0 candidates
   347	    65	
   348	    66	All consultation directories and handoffs are ≤ 5 days old (2026-04-23 to 2026-04-28). Nothing to archive yet.
   349	    67	
   350	    68	---
   351	    69	
   352	    70	## Recommended pre-review actions (priority order)
   353	    71	
   354	    72	1. **Commit untracked consultation files** — 8 files in `artifacts/consultations/2026-04-28-*/`. Per ORCHESTRATION §6.2, these are audit artifacts that belong in the repo alongside the handoffs that reference them. Simple `git add + commit`.
   355	    73	
   356	    74	2. **Resolve `feat/launcher-sigterm-handler`** — branch exists, handoff at `2026-04-27-launcher-sigterm-review.md`. Architect review pending or completed? If approved: merge. If stale: document and delete.
   357	    75	
   358	    76	3. **Resolve `codex/safe-merge-b1-truth-recovery` [ahead 7]** — 7 local commits not on origin or master. B1 investigation branch. Determine if this was superseded by vault investigation closures; if so, push or delete.
   359	    77	
   360	    78	4. **Delete merged branches** — `feat/cof-calibration-export` and `feat/cof-gui-wiring` are merged; safe to delete locally and on origin.
   361	    79	
   362	    80	5. **Pre-/ultrareview trigger** — repo is clean and consistent post-items 1-4. Trigger ultrareview when ready.
   363	
   364	exec
   365	/opt/homebrew/bin/bash -lc "rg -n \"\\.330\" README.md" in /Users/vladimir/Projects/cryodaq
   366	 succeeded in 0ms:
   367	84:  - `.cof` (Chebyshev coefficients) / `.340` / JSON / CSV export; `.330` removed
   368	
   369	exec
   370	/opt/homebrew/bin/bash -lc 'rg -n "''^## 14'"\\. Verification practices|"'^### 14'"\\.5|root.*\\.md|whitelist|README|ORCHESTRATION|CHANGELOG|AGENTS\" docs/ORCHESTRATION.md" in /Users/vladimir/Projects/cryodaq
   371	exec
   372	/opt/homebrew/bin/bash -lc "find . -maxdepth 1 -type f -name '*.md' -print | sort" in /Users/vladimir/Projects/cryodaq
   373	 succeeded in 0ms:
   374	240:├── ORCHESTRATION.md          ← this file
   375	262:At **repo root**, the only `.md` files permitted are:
   376	263:- `README.md`
   377	265:- `CHANGELOG.md`
   378	432:| Repo cleanup | this document, §§ 6, 5.2 | ✅ DONE (commits `adb49fe`..`8ebc893`, 2026-04-23) — 12 root .md archived (11 to audits, 1 preserved as blessed dossier), agent workspaces gitignored, duplicate branches pruned, worktree naming aligned |
   379	456:   untracked. Rule preventing it: §6.2 (strict root whitelist).
   380	529:- Architect-domain decision required: whitelist membership change,
   381	568:ORCHESTRATION.md §11 and Vladimir's memory slot 20 say
   382	629:## 14. Verification practices
   383	731:### 14.5 rtk-ai proxy filters merge commits
   384	
   385	 succeeded in 0ms:
   386	./CC_PROMPT_IV_2_ORCHESTRATOR.md
   387	./CC_PROMPT_IV_3_BATCH.md
   388	./CC_PROMPT_IV_4_BATCH.md
   389	./CC_PROMPT_IV_6_ZMQ_BRIDGE_FIX.md
   390	./CC_PROMPT_IV_7_IPC_TRANSPORT.md
   391	./CC_PROMPT_OVERNIGHT_SWARM_2026-04-24.md
   392	./CC_PROMPT_VAULT_AUDIT_2026-04-27.md
   393	./CC_PROMPT_VAULT_BUILD_2026-04-26.md
   394	./CHANGELOG.md
   395	./CLAUDE.md
   396	./CODEX_ARCHITECTURE_CONTROL_PLANE.md
   397	./DOC_REALITY_MAP.md
   398	./HANDOFF_2026-04-20_GLM.md
   399	./PROJECT_STATUS.md
   400	./README.md
   401	./RELEASE_CHECKLIST.md
   402	./ROADMAP.md
   403	./SESSION_DETAIL_2026-04-20.md
   404	./THIRD_PARTY_NOTICES.md
   405	
   406	exec
   407	/opt/homebrew/bin/bash -lc 'git tag -l "v0.*" --sort=v:refname' in /Users/vladimir/Projects/cryodaq
   408	 succeeded in 0ms:
   409	v0.33.0
   410	v0.34.0
   411	v0.35.0
   412	v0.36.0
   413	v0.37.0
   414	v0.38.0
   415	v0.39.0
   416	
   417	exec
   418	/opt/homebrew/bin/bash -lc "rg -n \"\\.330\" src tests" in /Users/vladimir/Projects/cryodaq
   419	 succeeded in 0ms:
   420	tests/analytics/test_calibration.py:279:# Phase D: .cof export + .330 removal
   421	tests/analytics/test_calibration.py:367:    fake_330 = tmp_path / "curve.330"
   422	
   423	codex
   424	The first pass confirms the marker claims mostly line up, but there are two places to tighten: CC’s `.330` hit description overstates the grep result, and the root whitelist needs exact §6.2 line matching rather than relying on the prose summary. I’m running the blindspot checks now.
   425	exec
   426	/opt/homebrew/bin/bash -lc "nl -ba docs/ORCHESTRATION.md | sed -n '258,276p'" in /Users/vladimir/Projects/cryodaq
   427	 succeeded in 0ms:
   428	   258	```
   429	   259	
   430	   260	### 6.2 Where things must NOT live
   431	   261	
   432	   262	At **repo root**, the only `.md` files permitted are:
   433	   263	- `README.md`
   434	   264	- `CLAUDE.md`
   435	   265	- `CHANGELOG.md`
   436	   266	- `CODEX_ARCHITECTURE_CONTROL_PLANE.md` — Codex technical dossier (commit 256da7a)
   437	   267	- `ROADMAP.md`
   438	   268	- `PROJECT_STATUS.md`
   439	   269	- `RELEASE_CHECKLIST.md`
   440	   270	- `DOC_REALITY_MAP.md` (historical, may be removed)
   441	   271	- `LICENSE`, `THIRD_PARTY_NOTICES.md`
   442	   272	- `CC_PROMPT_*.md` — architect-authored specs
   443	   273	- `HANDOFF_*.md`, `SESSION_DETAIL_*.md` — architect-authored
   444	   274	
   445	   275	A consultant (or CC on behalf of a consultant) producing
   446	   276	`REPO_HARDENING_FINAL.md` / `REVIEW_PLAN_GEMINI.md` /
   447	
   448	exec
   449	/opt/homebrew/bin/bash -lc "nl -ba tests/analytics/test_calibration.py | sed -n '250,380p'" in /Users/vladimir/Projects/cryodaq
   450	 succeeded in 0ms:
   451	   250	        index_path.unlink()
   452	   251	
   453	   252	    reloaded = CalibrationStore(tmp_path / "legacy")
   454	   253	    reloaded.load_curves(tmp_path / "legacy" / "curves")
   455	   254	
   456	   255	    assert reloaded.get_curve_info("sensor-005")["curve_id"] == curve.curve_id
   457	   256	    assert index_path.exists()
   458	   257	    assert curve_path.exists()
   459	   258	
   460	   259	
   461	   260	# ---------------------------------------------------------------------------
   462	   261	# Phase 2d B-1: atomic write for calibration index
   463	   262	# ---------------------------------------------------------------------------
   464	   263	
   465	   264	
   466	   265	def test_calibration_index_uses_atomic_write():
   467	   266	    """B-1.2: calibration.py index/curve writes must use atomic_write_text."""
   468	   267	    source = Path("src/cryodaq/analytics/calibration.py").read_text(encoding="utf-8")
   469	   268	    import re
   470	   269	
   471	   270	    raw_state_writes = re.findall(r"_index_path\.write_text|target\.write_text\(json", source)
   472	   271	    assert len(raw_state_writes) == 0, (
   473	   272	        f"Found {len(raw_state_writes)} raw write_text calls for state files — "
   474	   273	        f"should all route through atomic_write_text"
   475	   274	    )
   476	   275	    assert "atomic_write_text" in source
   477	   276	
   478	   277	
   479	   278	# ---------------------------------------------------------------------------
   480	   279	# Phase D: .cof export + .330 removal
   481	   280	# ---------------------------------------------------------------------------
   482	   281	
   483	   282	
   484	   283	def test_export_curve_cof_writes_file_with_expected_structure(tmp_path: Path) -> None:
   485	   284	    store = CalibrationStore(tmp_path)
   486	   285	    curve = store.fit_curve(
   487	   286	        "sensor-cof-01", _multi_zone_samples(300), raw_unit="V", max_zones=2, min_points_per_zone=24
   488	   287	    )
   489	   288	    store.save_curve(curve)
   490	   289	
   491	   290	    cof_path = store.export_curve_cof("sensor-cof-01")
   492	   291	
   493	   292	    assert cof_path.exists()
   494	   293	    assert cof_path.suffix == ".cof"
   495	   294	    text = cof_path.read_text(encoding="utf-8")
   496	   295	    assert "# CryoDAQ calibration curve export .cof" in text
   497	   296	    assert f"# sensor_id: {curve.sensor_id}" in text
   498	   297	    assert f"# curve_id: {curve.curve_id}" in text
   499	   298	    assert "[zone 1]" in text
   500	   299	    assert "raw_min:" in text
   501	   300	    assert "raw_max:" in text
   502	   301	    assert "order:" in text
   503	   302	    assert "coefficients:" in text
   504	   303	
   505	   304	
   506	   305	def test_export_curve_cof_preserves_chebyshev_coefficients_round_trip(tmp_path: Path) -> None:
   507	   306	    store = CalibrationStore(tmp_path)
   508	   307	    curve = store.fit_curve(
   509	   308	        "sensor-cof-02", _multi_zone_samples(600), raw_unit="V", max_zones=3, min_points_per_zone=24
   510	   309	    )
   511	   310	    store.save_curve(curve)
   512	   311	
   513	   312	    cof_path = store.export_curve_cof("sensor-cof-02")
   514	   313	    text = cof_path.read_text(encoding="utf-8")
   515	   314	
   516	   315	    parsed_coefficients: list[tuple[float, ...]] = []
   517	   316	    for line in text.splitlines():
   518	   317	        line = line.strip()
   519	   318	        if line.startswith("coefficients:"):
   520	   319	            values = tuple(float(v) for v in line.split(":", 1)[1].split(","))
   521	   320	            parsed_coefficients.append(values)
   522	   321	
   523	   322	    assert len(parsed_coefficients) == len(curve.zones)
   524	   323	    for parsed, zone in zip(parsed_coefficients, curve.zones, strict=True):
   525	   324	        assert len(parsed) == len(zone.coefficients)
   526	   325	        for a, b in zip(parsed, zone.coefficients, strict=True):
   527	   326	            assert a == pytest.approx(b, rel=1e-10)
   528	   327	
   529	   328	
   530	   329	def test_export_curve_cof_includes_zone_count_header(tmp_path: Path) -> None:
   531	   330	    store = CalibrationStore(tmp_path)
   532	   331	    curve = store.fit_curve(
   533	   332	        "sensor-cof-03", _multi_zone_samples(300), raw_unit="V", max_zones=3, min_points_per_zone=24
   534	   333	    )
   535	   334	    store.save_curve(curve)
   536	   335	
   537	   336	    cof_path = store.export_curve_cof("sensor-cof-03")
   538	   337	    text = cof_path.read_text(encoding="utf-8")
   539	   338	
   540	   339	    assert f"# zone_count: {len(curve.zones)}" in text
   541	   340	
   542	   341	
   543	   342	def test_export_curve_cof_metadata_comments_match_curve(tmp_path: Path) -> None:
   544	   343	    store = CalibrationStore(tmp_path)
   545	   344	    curve = store.fit_curve(
   546	   345	        "sensor-cof-04", _sample_series(), raw_unit="ohm", max_zones=2, min_points_per_zone=4
   547	   346	    )
   548	   347	    store.save_curve(curve)
   549	   348	
   550	   349	    cof_path = store.export_curve_cof("sensor-cof-04")
   551	   350	    text = cof_path.read_text(encoding="utf-8")
   552	   351	
   553	   352	    assert f"# raw_unit: {curve.raw_unit}" in text
   554	   353	    assert f"# fit_timestamp: {curve.fit_timestamp.isoformat()}" in text
   555	   354	    assert "# rmse_k:" in text
   556	   355	    assert "# max_abs_error_k:" in text
   557	   356	    assert "# point_count:" in text
   558	   357	
   559	   358	
   560	   359	def test_export_curve_330_removed(tmp_path: Path) -> None:
   561	   360	    store = CalibrationStore(tmp_path)
   562	   361	    assert not hasattr(store, "export_curve_330"), (
   563	   362	        "export_curve_330 must be removed — architect decision 2026-04-25"
   564	   363	    )
   565	   364	
   566	   365	
   567	   366	def test_import_curve_file_rejects_330_suffix(tmp_path: Path) -> None:
   568	   367	    fake_330 = tmp_path / "curve.330"
   569	   368	    fake_330.write_text("# header\n4.0 75.0\n6.0 60.0\n10.0 40.0\n20.0 22.0\n", encoding="utf-8")
   570	   369	    store = CalibrationStore(tmp_path)
   571	   370	    with pytest.raises(ValueError, match="Unsupported calibration import format"):
   572	   371	        store.import_curve_file(fake_330)
   573	
   574	exec
   575	/opt/homebrew/bin/bash -lc "nl -ba tests/gui/shell/overlays/test_calibration_panel.py | sed -n '340,370p'" in /Users/vladimir/Projects/cryodaq
   576	 succeeded in 0ms:
   577	   340	
   578	   341	    panel = CalibrationPanel()
   579	   342	    panel.set_connected(True)
   580	   343	    panel._results_widget.set_channels(["Т1"])
   581	   344	    out = tmp_path / "Т1.cof"
   582	   345	    monkeypatch.setattr(
   583	   346	        QFileDialog,
   584	   347	        "getSaveFileName",
   585	   348	        staticmethod(lambda *a, **k: (str(out), "Chebyshev .cof (*.cof)")),
   586	   349	    )
   587	   350	    _StubWorker.dispatched = []
   588	   351	    panel._results_widget._export_cof_btn.click()
   589	   352	    export_cmds = [c for c in _StubWorker.dispatched if c.get("cmd") == "calibration_curve_export"]
   590	   353	    assert len(export_cmds) == 1
   591	   354	    cmd = export_cmds[0]
   592	   355	    assert cmd["sensor_id"] == "Т1"
   593	   356	    assert cmd["curve_cof_path"] == str(out)
   594	   357	    # Other format paths not set.
   595	   358	    assert "json_path" not in cmd
   596	   359	    assert "table_path" not in cmd
   597	   360	    assert "curve_330_path" not in cmd
   598	   361	    assert "curve_340_path" not in cmd
   599	   362	
   600	   363	
   601	   364	def test_export_json_dispatches_json_path(app, monkeypatch, tmp_path):
   602	   365	    from PySide6.QtWidgets import QFileDialog
   603	   366	
   604	   367	    panel = CalibrationPanel()
   605	   368	    panel.set_connected(True)
   606	   369	    panel._results_widget.set_channels(["Т5"])
   607	   370	    out = tmp_path / "Т5.json"
   608	
   609	exec
   610	/opt/homebrew/bin/bash -lc 'git worktree list' in /Users/vladimir/Projects/cryodaq
   611	 succeeded in 0ms:
   612	/Users/vladimir/Projects/cryodaq                                         95240ae [master]
   613	/Users/vladimir/Projects/cryodaq/.worktrees/experiment-iv7-ipc-transport 63a3fed [experiment/iv7-ipc-transport]
   614	
   615	exec
   616	/opt/homebrew/bin/bash -lc 'git branch -vv' in /Users/vladimir/Projects/cryodaq
   617	exec
   618	/opt/homebrew/bin/bash -lc 'git status --short' in /Users/vladimir/Projects/cryodaq
   619	 succeeded in 0ms:
   620	  codex/safe-merge-b1-truth-recovery b2b4fb5 [origin/codex/safe-merge-b1-truth-recovery: ahead 7] fix: harden B1 capture bridge startup validation
   621	+ experiment/iv7-ipc-transport       63a3fed (/Users/vladimir/Projects/cryodaq/.worktrees/experiment-iv7-ipc-transport) Make launcher transport probe IPC-aware
   622	* master                             95240ae [origin/master] artifacts: commit cof migration + cof-gui audit consultations + recon
   623	
   624	 succeeded in 0ms:
   625	?? artifacts/consultations/2026-04-28-pre-ultrareview/
   626	
   627	codex
   628	The repo state has moved since CC’s recon: master is now `95240ae`, the prior consultation files appear committed, and only the new pre-ultrareview consultation directory is untracked. I’m checking whether that changes the readiness verdict and running the targeted pytest/import probes.
   629	exec
   630	/opt/homebrew/bin/bash -lc 'rg -n "TODO.*330|FIXME.*330" src' in /Users/vladimir/Projects/cryodaq
   631	 exited 1 in 0ms:
   632	exec
   633	/opt/homebrew/bin/bash -lc '.venv/bin/pytest tests/analytics/test_calibration.py tests/gui/shell/overlays/test_calibration_panel.py tests/core/test_calibration_commands.py -q' in /Users/vladimir/Projects/cryodaq
   634	exec
   635	/opt/homebrew/bin/bash -lc ".venv/bin/python -c \"from cryodaq.analytics.calibration import CalibrationStore; print('OK')\"" in /Users/vladimir/Projects/cryodaq
   636	exec
   637	/opt/homebrew/bin/bash -lc ".venv/bin/python -c \"import os; os.environ['QT_QPA_PLATFORM']='offscreen'; from cryodaq.gui.shell.overlays.calibration_panel import CalibrationPanel; print('OK')\"" in /Users/vladimir/Projects/cryodaq
   638	exec
   639	/opt/homebrew/bin/bash -lc ".venv/bin/python -c \"import cryodaq.engine; print('OK')\"" in /Users/vladimir/Projects/cryodaq
   640	 succeeded in 104ms:
   641	 exited 1 in 243ms:
   642	Traceback (most recent call last):
   643	  File "/Users/vladimir/Projects/cryodaq/.venv/bin/pytest", line 6, in <module>
   644	    sys.exit(console_main())
   645	             ~~~~~~~~~~~~^^
   646	  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/_pytest/config/__init__.py", line 223, in console_main
   647	    code = main()
   648	  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/_pytest/config/__init__.py", line 193, in main
   649	    config = _prepareconfig(new_args, plugins)
   650	  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/_pytest/config/__init__.py", line 361, in _prepareconfig
   651	    config: Config = pluginmanager.hook.pytest_cmdline_parse(
   652	                     ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^
   653	        pluginmanager=pluginmanager, args=args
   654	        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
   655	    )
   656	    ^
   657	  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/pluggy/_hooks.py", line 512, in __call__
   658	    return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)
   659	           ~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
   660	  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/pluggy/_manager.py", line 120, in _hookexec
   661	    return self._inner_hookexec(hook_name, methods, kwargs, firstresult)
   662	           ~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
   663	  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/pluggy/_callers.py", line 167, in _multicall
   664	    raise exception
   665	  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/pluggy/_callers.py", line 139, in _multicall
   666	    teardown.throw(exception)
   667	    ~~~~~~~~~~~~~~^^^^^^^^^^^
   668	  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/_pytest/helpconfig.py", line 124, in pytest_cmdline_parse
   669	    config = yield
   670	             ^^^^^
   671	  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/pluggy/_callers.py", line 121, in _multicall
   672	    res = hook_impl.function(*args)
   673	  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/_pytest/config/__init__.py", line 1192, in pytest_cmdline_parse
   674	    self.parse(args)
   675	    ~~~~~~~~~~^^^^^^
   676	  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/_pytest/config/__init__.py", line 1562, in parse
   677	    self.hook.pytest_load_initial_conftests(
   678	    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^
   679	        early_config=self, args=args, parser=self._parser
   680	        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
   681	    )
   682	    ^
   683	  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/pluggy/_hooks.py", line 512, in __call__
   684	    return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)
   685	           ~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
   686	  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/pluggy/_manager.py", line 120, in _hookexec
   687	    return self._inner_hookexec(hook_name, methods, kwargs, firstresult)
   688	           ~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
   689	  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/pluggy/_callers.py", line 167, in _multicall
   690	    raise exception
   691	  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/pluggy/_callers.py", line 139, in _multicall
   692	    teardown.throw(exception)
   693	    ~~~~~~~~~~~~~~^^^^^^^^^^^
   694	  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/_pytest/warnings.py", line 128, in pytest_load_initial_conftests
   695	    return (yield)
   696	            ^^^^^
   697	  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/pluggy/_callers.py", line 116, in _multicall
   698	    next(function_gen)  # first yield
   699	    ~~~~^^^^^^^^^^^^^^
   700	  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/_pytest/capture.py", line 170, in pytest_load_initial_conftests
   701	    capman.start_global_capturing()
   702	    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^
   703	  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/_pytest/capture.py", line 773, in start_global_capturing
   704	    self._global_capturing = _get_multicapture(self._method)
   705	                             ~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^
   706	  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/_pytest/capture.py", line 714, in _get_multicapture
   707	    return MultiCapture(in_=FDCapture(0), out=FDCapture(1), err=FDCapture(2))
   708	                                              ~~~~~~~~~^^^
   709	  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/_pytest/capture.py", line 493, in __init__
   710	    TemporaryFile(buffering=0),
   711	    ~~~~~~~~~~~~~^^^^^^^^^^^^^
   712	  File "/Library/Frameworks/Python.framework/Versions/3.14/lib/python3.14/tempfile.py", line 652, in TemporaryFile
   713	    prefix, suffix, dir, output_type = _sanitize_params(prefix, suffix, dir)
   714	                                       ~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^
   715	  File "/Library/Frameworks/Python.framework/Versions/3.14/lib/python3.14/tempfile.py", line 126, in _sanitize_params
   716	    dir = gettempdir()
   717	  File "/Library/Frameworks/Python.framework/Versions/3.14/lib/python3.14/tempfile.py", line 316, in gettempdir
   718	    return _os.fsdecode(_gettempdir())
   719	                        ~~~~~~~~~~~^^
   720	  File "/Library/Frameworks/Python.framework/Versions/3.14/lib/python3.14/tempfile.py", line 309, in _gettempdir
   721	    tempdir = _get_default_tempdir()
   722	  File "/Library/Frameworks/Python.framework/Versions/3.14/lib/python3.14/tempfile.py", line 224, in _get_default_tempdir
   723	    raise FileNotFoundError(_errno.ENOENT,
   724	                            "No usable temporary directory found in %s" %
   725	                            dirlist)
   726	FileNotFoundError: [Errno 2] No usable temporary directory found in ['/var/folders/sy/gxxl_n9528qdws_74b5x8mdc0000gn/T/', '/tmp', '/var/tmp', '/usr/tmp', '/Users/vladimir/Projects/cryodaq']
   727	
   728	 exited 1 in 407ms:
   729	/Users/vladimir/.matplotlib is not a writable directory
   730	Traceback (most recent call last):
   731	  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/matplotlib/__init__.py", line 545, in _get_config_or_cache_dir
   732	    tmpdir = tempfile.mkdtemp(prefix="matplotlib-")
   733	  File "/Library/Frameworks/Python.framework/Versions/3.14/lib/python3.14/tempfile.py", line 374, in mkdtemp
   734	    prefix, suffix, dir, output_type = _sanitize_params(prefix, suffix, dir)
   735	                                       ~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^
   736	  File "/Library/Frameworks/Python.framework/Versions/3.14/lib/python3.14/tempfile.py", line 126, in _sanitize_params
   737	    dir = gettempdir()
   738	  File "/Library/Frameworks/Python.framework/Versions/3.14/lib/python3.14/tempfile.py", line 316, in gettempdir
   739	    return _os.fsdecode(_gettempdir())
   740	                        ~~~~~~~~~~~^^
   741	  File "/Library/Frameworks/Python.framework/Versions/3.14/lib/python3.14/tempfile.py", line 309, in _gettempdir
   742	    tempdir = _get_default_tempdir()
   743	  File "/Library/Frameworks/Python.framework/Versions/3.14/lib/python3.14/tempfile.py", line 224, in _get_default_tempdir
   744	    raise FileNotFoundError(_errno.ENOENT,
   745	                            "No usable temporary directory found in %s" %
   746	                            dirlist)
   747	FileNotFoundError: [Errno 2] No usable temporary directory found in ['/var/folders/sy/gxxl_n9528qdws_74b5x8mdc0000gn/T/', '/tmp', '/var/tmp', '/usr/tmp', '/Users/vladimir/Projects/cryodaq']
   748	
   749	The above exception was the direct cause of the following exception:
   750	
   751	Traceback (most recent call last):
   752	  File "<string>", line 1, in <module>
   753	    import cryodaq.engine; print('OK')
   754	    ^^^^^^^^^^^^^^^^^^^^^
   755	  File "/Users/vladimir/Projects/cryodaq/src/cryodaq/engine.py", line 71, in <module>
   756	    from cryodaq.reporting.generator import ReportGenerator
   757	  File "/Users/vladimir/Projects/cryodaq/src/cryodaq/reporting/__init__.py", line 1, in <module>
   758	    from .generator import ReportGenerationResult, ReportGenerator
   759	  File "/Users/vladimir/Projects/cryodaq/src/cryodaq/reporting/generator.py", line 13, in <module>
   760	    from cryodaq.reporting.sections import SECTION_REGISTRY
   761	  File "/Users/vladimir/Projects/cryodaq/src/cryodaq/reporting/sections.py", line 17, in <module>
   762	    import matplotlib
   763	  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/matplotlib/__init__.py", line 1010, in <module>
   764	    rcParams._update_raw(_rc_params_in_file(matplotlib_fname()))
   765	                                            ~~~~~~~~~~~~~~~~^^
   766	  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/matplotlib/__init__.py", line 636, in matplotlib_fname
   767	    for fname in gen_candidates():
   768	                 ~~~~~~~~~~~~~~^^
   769	  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/matplotlib/__init__.py", line 633, in gen_candidates
   770	    yield os.path.join(get_configdir(), 'matplotlibrc')
   771	                       ~~~~~~~~~~~~~^^
   772	  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/matplotlib/__init__.py", line 340, in wrapper
   773	    ret = func(**kwargs)
   774	  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/matplotlib/__init__.py", line 579, in get_configdir
   775	    return _get_config_or_cache_dir(_get_xdg_config_dir)
   776	  File "/Users/vladimir/Projects/cryodaq/.venv/lib/python3.14/site-packages/matplotlib/__init__.py", line 547, in _get_config_or_cache_dir
   777	    raise OSError(
   778	    ...<3 lines>...
   779	        f"variable to a writable directory") from exc
   780	OSError: Matplotlib requires access to a writable cache directory, but there was an issue with the default path (/Users/vladimir/.matplotlib), and a temporary directory could not be created; set the MPLCONFIGDIR environment variable to a writable directory
   781	
   782	 succeeded in 563ms:
   783	OK
   784	
   785	codex
   786	The targeted test command is blocked by this read-only execution environment because pytest cannot create a temp capture file. Two import probes pass; `cryodaq.engine` exposes a real environment-sensitive import problem around Matplotlib cache/temp dirs that CC did not check.
   787	exec
   788	/opt/homebrew/bin/bash -lc 'rg -n "def export_curve_cof|def _write_cof_export|Chebyshev|zone_count|max_zones|min_points_per_zone" src/cryodaq/analytics/calibration.py' in /Users/vladimir/Projects/cryodaq
   789	 succeeded in 0ms:
   790	1:"""Calibration backend: session storage, Chebyshev fits, and artifact IO."""
   791	195:    """Calibration curve storage and multi-zone Chebyshev fitting."""
   792	222:        max_zones: int = 3,
   793	223:        min_points_per_zone: int = 6,
   794	230:        if len(samples) < max(4, min_points_per_zone):
   795	236:        if len(normalized_samples) < max(4, min_points_per_zone):
   796	253:            max_zones=max(1, max_zones),
   797	254:            min_points_per_zone=max(3, min_points_per_zone),
   798	284:                "zone_count": int(len(zones)),
   799	424:    def export_curve_cof(
   800	430:        """Export calibration curve as .cof (Chebyshev coefficients) format.
   801	875:    def _write_cof_export(self, path: Path, curve: CalibrationCurve) -> None:
   802	876:        """Write .cof format: header + per-zone raw Chebyshev coefficients."""
   803	886:            "# format: Chebyshev T_n(x); raw clipped to [raw_min, raw_max],"
   804	889:        lines.append(f"# zone_count: {len(curve.zones)}")
   805	951:            max_zones=3,
   806	952:            min_points_per_zone=4,
   807	1070:        max_zones: int,
   808	1071:        min_points_per_zone: int,
   809	1074:        if len(raw_values) < (min_points_per_zone * 2) or max_zones <= 1:
   810	1085:            if index < min_points_per_zone or index > len(raw_values) - min_points_per_zone:
   811	1087:            if any(abs(index - boundary) < min_points_per_zone for boundary in boundaries):
   812	1093:                min_points_per_zone=min_points_per_zone,
   813	1096:            if any(abs(refined - boundary) < min_points_per_zone for boundary in boundaries):
   814	1099:            if len(boundaries) >= max_zones - 1:
   815	1107:            if stop - start < min_points_per_zone:
   816	1111:        if len(raw_values) - start < min_points_per_zone and slices:
   817	1192:                fit = cheb.Chebyshev.fit(raw_values, temperatures, deg=order, domain=domain)
   818	1293:        min_points_per_zone: int,
   819	1296:        search_radius = max(3, min_points_per_zone // 2)
   820	1297:        start = max(min_points_per_zone, candidate_index - search_radius)
   821	1298:        stop = min(len(raw_values) - min_points_per_zone, candidate_index + search_radius)
   822	
   823	exec
   824	/opt/homebrew/bin/bash -lc "rg -n \"\\.cof|cof|\\.330|330|calibration\" CHANGELOG.md" in /Users/vladimir/Projects/cryodaq
   825	 succeeded in 0ms:
   826	319:  (operator_log, archive, calibration, conductivity, keithley) now
   827	347:  - `src/cryodaq/gui/widgets/calibration_panel.py` (superseded by II.7).
   828	357:  calibration, experiment_workspace, keithley_panel_contract,
   829	358:  main_window_calibration_integration, operator_log_panel,
   830	433:  `src/cryodaq/gui/shell/overlays/calibration_panel.py` replaces the
   831	436:  `calibration_acquisition_status`). CoverageBar migrated from
   832	442:  `calibration_curve_import` (with `QFileDialog.getOpenFileName`
   833	443:  picker per format), `calibration_curve_export` (with
   834	445:  `calibration_runtime_set_global`,
   835	446:  `calibration_runtime_set_channel_policy` (chained via
   836	447:  `calibration_curve_lookup` to resolve `curve_id`). Acquisition
   837	453:  `_ensure_overlay("calibration")` replay; readings routing (shell
   838	458:  `src/cryodaq/gui/widgets/calibration_panel.py` marked DEPRECATED;
   839	847:- **Tier 1 Fix A — calibration channel canonicalization (`a5cd8b7`).**
   840	855:  (`engine.py:370-375`, `calibration_acquisition.py:92-108`).
   841	887:  `gui/widgets/calibration_panel.py` built channel refs в
   842	901:- **Codex R1 finding A.1 — calibration throttle atomicity
   843	943:- +11 from Tier 1 fixes (5 calibration canon, 4 broker isolation,
   844	955:- `a5cd8b7` tier1-a: canonicalize calibration channel identities
   845	959:- `621f98a` post-merge fixes: calibration prefix strip + dedupe imports
   846	985:- **Jules R2: calibration state mutation** — `prepare_srdg_readings()`
   847	1013:  `os.replace()` для experiment sidecars и calibration index/curve.
   848	1033:- **KRDG+SRDG atomic** — calibration readings persist в одной
   849	1253:- **UI** — CSV BOM, sensor diag stretch, calibration stretch, reports
   850	1459:  export). `.330` / `.340` / JSON export.
   851	1517:reports, housekeeping, calibration), GUI workflows (tray status,
   852	
   853	exec
   854	/opt/homebrew/bin/bash -lc "rg -n \"asyncio\\.create_task|create_task\\(\" src" in /Users/vladimir/Projects/cryodaq
   855	 succeeded in 0ms:
   856	src/cryodaq/analytics/cooldown_service.py:266:        self._consume_task = asyncio.create_task(
   857	src/cryodaq/analytics/cooldown_service.py:270:        self._predict_task = asyncio.create_task(
   858	src/cryodaq/notifications/escalation.py:70:            task = asyncio.create_task(
   859	src/cryodaq/web/server.py:312:        _pump_task = asyncio.create_task(_broadcast_pump(), name="broadcast_pump")
   860	src/cryodaq/web/server.py:313:        _zmq_task = asyncio.create_task(_zmq_to_ws_bridge(), name="zmq_ws_bridge")
   861	src/cryodaq/core/alarm.py:331:        self._task = asyncio.create_task(self._check_loop(), name="alarm_check_loop")
   862	src/cryodaq/notifications/telegram_commands.py:129:        self._collect_task = asyncio.create_task(self._collect_loop(), name="tg_cmd_collect")
   863	src/cryodaq/notifications/telegram_commands.py:130:        self._poll_task = asyncio.create_task(self._poll_loop(), name="tg_cmd_poll")
   864	src/cryodaq/core/housekeeping.py:368:        self._task = asyncio.create_task(self._loop(), name="housekeeping_service")
   865	src/cryodaq/core/scheduler.py:463:            task = asyncio.create_task(
   866	src/cryodaq/core/scheduler.py:474:            state.task = asyncio.create_task(
   867	src/cryodaq/core/safety_manager.py:221:        self._collect_task = asyncio.create_task(self._collect_loop(), name="safety_collect")
   868	src/cryodaq/core/safety_manager.py:222:        self._monitor_task = asyncio.create_task(self._monitor_loop(), name="safety_monitor")
   869	src/cryodaq/core/safety_manager.py:660:            task = asyncio.get_running_loop().create_task(
   870	src/cryodaq/core/safety_manager.py:702:            shutdown_task = asyncio.create_task(self._keithley.emergency_off())
   871	src/cryodaq/core/safety_manager.py:723:            log_task = asyncio.create_task(
   872	src/cryodaq/core/safety_manager.py:774:            off_task = asyncio.create_task(self._ensure_output_off())
   873	src/cryodaq/analytics/plugin_loader.py:93:        self._process_task = asyncio.create_task(
   874	src/cryodaq/analytics/plugin_loader.py:96:        self._watch_task = asyncio.create_task(self._watch_loop(), name="analytics_watch_loop")
   875	src/cryodaq/notifications/periodic_report.py:115:        self._collect_task = asyncio.create_task(
   876	src/cryodaq/notifications/periodic_report.py:118:        self._report_task = asyncio.create_task(
   877	src/cryodaq/core/zmq_bridge.py:204:        self._task = asyncio.create_task(self._publish_loop(queue), name="zmq_publisher")
   878	src/cryodaq/core/zmq_bridge.py:299:        self._task = asyncio.create_task(self._receive_loop(), name="zmq_subscriber")
   879	src/cryodaq/core/zmq_bridge.py:361:        self._task = loop.create_task(self._serve_loop(), name="zmq_cmd_server")
   880	src/cryodaq/core/disk_monitor.py:48:        self._task = asyncio.create_task(self._check_loop(), name="disk_monitor")
   881	src/cryodaq/core/interlock.py:330:        self._task = asyncio.create_task(self._check_loop(), name="interlock_check_loop")
   882	src/cryodaq/storage/sqlite_writer.py:637:        self._task = asyncio.create_task(self._consume_loop(queue), name="sqlite_writer")
   883	src/cryodaq/engine.py:1153:                            t = asyncio.create_task(
   884	src/cryodaq/engine.py:1607:    throttle_task = asyncio.create_task(_track_runtime_signals(), name="adaptive_throttle_runtime")
   885	src/cryodaq/engine.py:1608:    alarm_v2_feed_task = asyncio.create_task(_alarm_v2_feed_readings(), name="alarm_v2_feed")
   886	src/cryodaq/engine.py:1611:        alarm_v2_tick_task = asyncio.create_task(_alarm_v2_tick(), name="alarm_v2_tick")
   887	src/cryodaq/engine.py:1615:        sd_feed_task = asyncio.create_task(_sensor_diag_feed(), name="sensor_diag_feed")
   888	src/cryodaq/engine.py:1616:        sd_tick_task = asyncio.create_task(_sensor_diag_tick(), name="sensor_diag_tick")
   889	src/cryodaq/engine.py:1620:        vt_feed_task = asyncio.create_task(_vacuum_trend_feed(), name="vacuum_trend_feed")
   890	src/cryodaq/engine.py:1621:        vt_tick_task = asyncio.create_task(_vacuum_trend_tick(), name="vacuum_trend_tick")
   891	src/cryodaq/engine.py:1625:    watchdog_task = asyncio.create_task(
   892	
   893	exec
   894	/opt/homebrew/bin/bash -lc "rg -n \"\\bopen\\(\" src" in /Users/vladimir/Projects/cryodaq
   895	 succeeded in 0ms:
   896	src/cryodaq/analytics/calibration.py:417:        with target.open("w", encoding="utf-8", newline="") as handle:
   897	src/cryodaq/analytics/calibration.py:865:        with path.open("w", encoding="utf-8", newline="") as handle:
   898	src/cryodaq/engine.py:383:        with raw_path.open(encoding="utf-8") as fh:
   899	src/cryodaq/engine.py:734:    with config_path.open(encoding="utf-8") as fh:
   900	src/cryodaq/engine.py:1060:        with _plugins_cfg_path.open(encoding="utf-8") as fh:
   901	src/cryodaq/engine.py:1498:            with cooldown_cfg_path.open(encoding="utf-8") as fh:
   902	src/cryodaq/engine.py:1520:            with notifications_cfg.open(encoding="utf-8") as fh:
   903	src/cryodaq/engine.py:1801:    fd = os.open(str(_LOCK_FILE), os.O_CREAT | os.O_RDWR, 0o644)
   904	src/cryodaq/engine.py:1836:        fd = os.open(str(_LOCK_FILE), os.O_RDONLY)
   905	src/cryodaq/analytics/plugin_loader.py:183:                    with config_path.open("r", encoding="utf-8") as fh:
   906	src/cryodaq/notifications/telegram.py:109:        with config_path.open(encoding="utf-8") as fh:
   907	src/cryodaq/launcher.py:330:                probe_fd = os.open(str(lock_path), os.O_RDWR)
   908	src/cryodaq/launcher.py:942:        webbrowser.open(f"http://127.0.0.1:{_WEB_PORT}")
   909	src/cryodaq/storage/csv_export.py:79:        with output_path.open("w", newline="", encoding="utf-8-sig") as fh:
   910	src/cryodaq/gui/widgets/connection_settings.py:63:            with cfg_path.open(encoding="utf-8") as fh:
   911	src/cryodaq/gui/widgets/connection_settings.py:241:        with _LOCAL_CONFIG.open("w", encoding="utf-8") as fh:
   912	src/cryodaq/gui/_theme_loader.py:76:        with SETTINGS_FILE.open(encoding="utf-8") as f:
   913	src/cryodaq/gui/_theme_loader.py:111:        with pack_file.open(encoding="utf-8") as f:
   914	src/cryodaq/gui/_theme_loader.py:159:            with SETTINGS_FILE.open(encoding="utf-8") as f:
   915	src/cryodaq/gui/_theme_loader.py:171:    with SETTINGS_FILE.open("w", encoding="utf-8") as f:
   916	src/cryodaq/gui/_theme_loader.py:183:            with pack_file.open(encoding="utf-8") as f:
   917	src/cryodaq/gui/widgets/overview_panel.py:1774:            with open(path, "w", encoding="utf-8-sig") as f:
   918	src/cryodaq/core/channel_manager.py:93:            with self._config_path.open(encoding="utf-8") as fh:
   919	src/cryodaq/core/channel_manager.py:116:        with save_path.open("w", encoding="utf-8") as fh:
   920	src/cryodaq/gui/widgets/shift_handover.py:53:            with _CONFIG_PATH.open(encoding="utf-8") as fh:
   921	src/cryodaq/core/alarm_config.py:108:        with open(path, encoding="utf-8") as f:
   922	src/cryodaq/core/interlock.py:233:            with config_path.open(encoding="utf-8") as fh:
   923	src/cryodaq/reporting/sections.py:184:        with path.open(encoding="utf-8-sig", newline="") as handle:
   924	src/cryodaq/reporting/sections.py:188:        with path.open(encoding="utf-8", newline="") as handle:
   925	src/cryodaq/reporting/sections.py:522:    with path.open(encoding="utf-8", newline="") as handle:
   926	src/cryodaq/core/housekeeping.py:33:        with config_path.open(encoding="utf-8") as handle:
   927	src/cryodaq/core/housekeeping.py:51:        with path.open(encoding="utf-8") as handle:
   928	src/cryodaq/core/housekeeping.py:148:        with config_path.open(encoding="utf-8") as handle:
   929	src/cryodaq/core/housekeeping.py:437:            with action.source.open("rb") as src, gzip.open(action.target, "wb") as dst:
   930	src/cryodaq/reporting/data.py:91:            with table_path.open(encoding="utf-8", newline="") as handle:
   931	src/cryodaq/drivers/transport/usbtmc.py:87:    async def open(self, resource_str: str) -> None:
   932	src/cryodaq/core/experiment.py:993:            with path.open(encoding="utf-8") as handle:
   933	src/cryodaq/core/experiment.py:1563:        with path.open("w", encoding="utf-8", newline="") as handle:
   934	src/cryodaq/core/experiment.py:1580:        with path.open("w", encoding="utf-8", newline="") as handle:
   935	src/cryodaq/core/experiment.py:1598:        with path.open("w", encoding="utf-8", newline="") as handle:
   936	src/cryodaq/core/experiment.py:1639:                    with path.open(encoding="utf-8", newline="") as handle:
   937	src/cryodaq/core/experiment.py:1657:        with path.open("w", encoding="utf-8", newline="") as handle:
   938	src/cryodaq/core/experiment.py:1782:            with self._instruments_config.open(encoding="utf-8") as handle:
   939	src/cryodaq/core/alarm.py:245:        with config_path.open(encoding="utf-8") as fh:
   940	src/cryodaq/drivers/transport/serial.py:43:    async def open(self, port: str, baudrate: int = 9600, timeout: float = 2.0) -> None:  # noqa: ASYNC109
   941	src/cryodaq/drivers/transport/serial.py:145:            Таймаут чтения в секундах (``None`` → использует значение из ``open()``).
   942	src/cryodaq/core/safety_manager.py:143:        with path.open(encoding="utf-8") as fh:
   943	src/cryodaq/instance_lock.py:33:    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
   944	src/cryodaq/gui/shell/views/analytics_view.py:98:    with _LAYOUT_CONFIG_PATH.open(encoding="utf-8") as f:
   945	src/cryodaq/gui/shell/overlays/calibration_panel.py:83:        with config_path.open(encoding="utf-8") as fh:
   946	src/cryodaq/drivers/instruments/keithley_2604b.py:80:        await self._transport.open(self._resource_str)
   947	src/cryodaq/drivers/transport/gpib.py:143:    async def open(self, resource_str: str, *, timeout_ms: int = _DEFAULT_TIMEOUT_MS) -> None:
   948	src/cryodaq/gui/shell/main_window_v2.py:662:        webbrowser.open(f"http://{host}:{_WEB_PORT}")
   949	src/cryodaq/drivers/instruments/thyracont_vsp63d.py:114:                await self._transport.open(self._resource_str, baudrate=baud)
   950	src/cryodaq/gui/shell/overlays/conductivity_panel.py:1321:            self._flight_log = log_path.open("w", newline="", encoding="utf-8-sig")
   951	src/cryodaq/gui/shell/overlays/conductivity_panel.py:1430:        with out.open("w", newline="", encoding="utf-8-sig") as f:
   952	src/cryodaq/drivers/instruments/lakeshore_218s.py:54:        await self._transport.open(self._resource_str)
   953	
   954	exec
   955	/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/analytics/calibration.py | sed -n '1,260p'" in /Users/vladimir/Projects/cryodaq
   956	 succeeded in 0ms:
   957	     1	"""Calibration backend: session storage, Chebyshev fits, and artifact IO."""
   958	     2	
   959	     3	from __future__ import annotations
   960	     4	
   961	     5	import csv
   962	     6	import json
   963	     7	import math
   964	     8	import uuid
   965	     9	import warnings
   966	    10	from dataclasses import dataclass, field
   967	    11	from datetime import UTC, datetime
   968	    12	from pathlib import Path
   969	    13	from typing import Any
   970	    14	
   971	    15	import numpy as np
   972	    16	import yaml
   973	    17	from numpy.polynomial import chebyshev as cheb
   974	    18	
   975	    19	
   976	    20	def _utcnow() -> datetime:
   977	    21	    return datetime.now(UTC)
   978	    22	
   979	    23	
   980	    24	def _parse_time(raw: datetime | str | None) -> datetime | None:
   981	    25	    if raw is None:
   982	    26	        return None
   983	    27	    if isinstance(raw, datetime):
   984	    28	        if raw.tzinfo is None:
   985	    29	            return raw.replace(tzinfo=UTC)
   986	    30	        return raw.astimezone(UTC)
   987	    31	    text = str(raw).strip()
   988	    32	    if not text:
   989	    33	        return None
   990	    34	    if text.endswith("Z"):
   991	    35	        text = f"{text[:-1]}+00:00"
   992	    36	    parsed = datetime.fromisoformat(text)
   993	    37	    if parsed.tzinfo is None:
   994	    38	        return parsed.replace(tzinfo=UTC)
   995	    39	    return parsed.astimezone(UTC)
   996	    40	
   997	    41	
   998	    42	def _json_dict(raw: Any) -> dict[str, Any]:
   999	    43	    if raw is None:
  1000	    44	        return {}
  1001	    45	    if isinstance(raw, dict):
  1002	    46	        return {str(key): value for key, value in raw.items()}
  1003	    47	    raise ValueError("Expected dictionary payload.")
  1004	    48	
  1005	    49	
  1006	    50	def _safe_path_fragment(value: str) -> str:
  1007	    51	    cleaned = "".join("_" if char in '<>:"/\\|?*' else char for char in str(value).strip())
  1008	    52	    return cleaned or "unnamed"
  1009	    53	
  1010	    54	
  1011	    55	@dataclass(frozen=True, slots=True)
  1012	    56	class CalibrationSample:
  1013	    57	    timestamp: datetime
  1014	    58	    reference_channel: str
  1015	    59	    reference_temperature: float
  1016	    60	    sensor_channel: str
  1017	    61	    sensor_raw_value: float
  1018	    62	    reference_instrument_id: str = ""
  1019	    63	    sensor_instrument_id: str = ""
  1020	    64	    experiment_id: str | None = None
  1021	    65	    metadata: dict[str, Any] = field(default_factory=dict)
  1022	    66	
  1023	    67	    def to_payload(self) -> dict[str, Any]:
  1024	    68	        return {
  1025	    69	            "timestamp": self.timestamp.isoformat(),
  1026	    70	            "reference_channel": self.reference_channel,
  1027	    71	            "reference_temperature": self.reference_temperature,
  1028	    72	            "sensor_channel": self.sensor_channel,
  1029	    73	            "sensor_raw_value": self.sensor_raw_value,
  1030	    74	            "reference_instrument_id": self.reference_instrument_id,
  1031	    75	            "sensor_instrument_id": self.sensor_instrument_id,
  1032	    76	            "experiment_id": self.experiment_id,
  1033	    77	            "metadata": dict(self.metadata),
  1034	    78	        }
  1035	    79	
  1036	    80	    @classmethod
  1037	    81	    def from_payload(cls, payload: dict[str, Any]) -> CalibrationSample:
  1038	    82	        return cls(
  1039	    83	            timestamp=_parse_time(payload.get("timestamp")) or _utcnow(),
  1040	    84	            reference_channel=str(payload.get("reference_channel", "")),
  1041	    85	            reference_temperature=float(payload.get("reference_temperature", 0.0)),
  1042	    86	            sensor_channel=str(payload.get("sensor_channel", "")),
  1043	    87	            sensor_raw_value=float(payload.get("sensor_raw_value", 0.0)),
  1044	    88	            reference_instrument_id=str(payload.get("reference_instrument_id", "")),
  1045	    89	            sensor_instrument_id=str(payload.get("sensor_instrument_id", "")),
  1046	    90	            experiment_id=(
  1047	    91	                str(payload.get("experiment_id"))
  1048	    92	                if payload.get("experiment_id") not in (None, "")
  1049	    93	                else None
  1050	    94	            ),
  1051	    95	            metadata=_json_dict(payload.get("metadata")),
  1052	    96	        )
  1053	    97	
  1054	    98	
  1055	    99	@dataclass(frozen=True, slots=True)
  1056	   100	class CalibrationZone:
  1057	   101	    raw_min: float
  1058	   102	    raw_max: float
  1059	   103	    order: int
  1060	   104	    coefficients: tuple[float, ...]
  1061	   105	    rmse_k: float
  1062	   106	    max_abs_error_k: float
  1063	   107	    point_count: int
  1064	   108	
  1065	   109	    def contains(self, raw_value: float) -> bool:
  1066	   110	        return self.raw_min <= raw_value <= self.raw_max
  1067	   111	
  1068	   112	    def evaluate(self, raw_value: float) -> float:
  1069	   113	        if self.raw_max <= self.raw_min:
  1070	   114	            raise ValueError("Calibration zone has invalid range.")
  1071	   115	        clipped = min(max(raw_value, self.raw_min), self.raw_max)
  1072	   116	        scaled = ((2.0 * (clipped - self.raw_min)) / (self.raw_max - self.raw_min)) - 1.0
  1073	   117	        return float(cheb.chebval(scaled, self.coefficients))
  1074	   118	
  1075	   119	    def to_payload(self) -> dict[str, Any]:
  1076	   120	        return {
  1077	   121	            "raw_min": self.raw_min,
  1078	   122	            "raw_max": self.raw_max,
  1079	   123	            "order": self.order,
  1080	   124	            "coefficients": list(self.coefficients),
  1081	   125	            "rmse_k": self.rmse_k,
  1082	   126	            "max_abs_error_k": self.max_abs_error_k,
  1083	   127	            "point_count": self.point_count,
  1084	   128	        }
  1085	   129	
  1086	   130	    @classmethod
  1087	   131	    def from_payload(cls, payload: dict[str, Any]) -> CalibrationZone:
  1088	   132	        return cls(
  1089	   133	            raw_min=float(payload.get("raw_min", 0.0)),
  1090	   134	            raw_max=float(payload.get("raw_max", 0.0)),
  1091	   135	            order=int(payload.get("order", 1)),
  1092	   136	            coefficients=tuple(float(value) for value in payload.get("coefficients", [])),
  1093	   137	            rmse_k=float(payload.get("rmse_k", 0.0)),
  1094	   138	            max_abs_error_k=float(payload.get("max_abs_error_k", 0.0)),
  1095	   139	            point_count=int(payload.get("point_count", 0)),
  1096	   140	        )
  1097	   141	
  1098	   142	
  1099	   143	@dataclass(frozen=True, slots=True)
  1100	   144	class CalibrationCurve:
  1101	   145	    curve_id: str
  1102	   146	    sensor_id: str
  1103	   147	    fit_timestamp: datetime
  1104	   148	    raw_unit: str
  1105	   149	    sensor_kind: str
  1106	   150	    source_session_ids: tuple[str, ...]
  1107	   151	    zones: tuple[CalibrationZone, ...]
  1108	   152	    metrics: dict[str, Any] = field(default_factory=dict)
  1109	   153	    metadata: dict[str, Any] = field(default_factory=dict)
  1110	   154	
  1111	   155	    def evaluate(self, raw_value: float) -> float:
  1112	   156	        if not self.zones:
  1113	   157	            raise ValueError("Calibration curve has no fitted zones.")
  1114	   158	        for zone in self.zones:
  1115	   159	            if zone.contains(raw_value):
  1116	   160	                return zone.evaluate(raw_value)
  1117	   161	        if raw_value < self.zones[0].raw_min:
  1118	   162	            return self.zones[0].evaluate(raw_value)
  1119	   163	        return self.zones[-1].evaluate(raw_value)
  1120	   164	
  1121	   165	    def to_payload(self) -> dict[str, Any]:
  1122	   166	        return {
  1123	   167	            "schema_version": 1,
  1124	   168	            "curve_id": self.curve_id,
  1125	   169	            "sensor_id": self.sensor_id,
  1126	   170	            "fit_timestamp": self.fit_timestamp.isoformat(),
  1127	   171	            "raw_unit": self.raw_unit,
  1128	   172	            "sensor_kind": self.sensor_kind,
  1129	   173	            "source_session_ids": list(self.source_session_ids),
  1130	   174	            "zones": [zone.to_payload() for zone in self.zones],
  1131	   175	            "metrics": dict(self.metrics),
  1132	   176	            "metadata": dict(self.metadata),
  1133	   177	        }
  1134	   178	
  1135	   179	    @classmethod
  1136	   180	    def from_payload(cls, payload: dict[str, Any]) -> CalibrationCurve:
  1137	   181	        return cls(
  1138	   182	            curve_id=str(payload.get("curve_id", "")),
  1139	   183	            sensor_id=str(payload.get("sensor_id", "")),
  1140	   184	            fit_timestamp=_parse_time(payload.get("fit_timestamp")) or _utcnow(),
  1141	   185	            raw_unit=str(payload.get("raw_unit", "sensor_unit")),
  1142	   186	            sensor_kind=str(payload.get("sensor_kind", "generic")),
  1143	   187	            source_session_ids=tuple(str(item) for item in payload.get("source_session_ids", [])),
  1144	   188	            zones=tuple(CalibrationZone.from_payload(item) for item in payload.get("zones", [])),
  1145	   189	            metrics=_json_dict(payload.get("metrics")),
  1146	   190	            metadata=_json_dict(payload.get("metadata")),
  1147	   191	        )
  1148	   192	
  1149	   193	
  1150	   194	class CalibrationStore:
  1151	   195	    """Calibration curve storage and multi-zone Chebyshev fitting."""
  1152	   196	
  1153	   197	    _TASK_CV_ORDER_RANGE = tuple(range(7, 13))
  1154	   198	    _TASK_DOWNSAMPLE_TARGET = 5000
  1155	   199	
  1156	   200	    def __init__(self, base_dir: Path | None = None) -> None:
  1157	   201	        self._base_dir = base_dir
  1158	   202	        self._curves_dir = base_dir / "curves" if base_dir is not None else None
  1159	   203	        self._exports_dir = base_dir / "exports" if base_dir is not None else None
  1160	   204	        self._index_path = base_dir / "index.yaml" if base_dir is not None else None
  1161	   205	        self._curves: dict[str, CalibrationCurve] = {}
  1162	   206	        self._assignments: dict[str, dict[str, Any]] = {}
  1163	   207	        self._runtime_settings: dict[str, Any] = {
  1164	   208	            "global_mode": "off",
  1165	   209	            "updated_at": "",
  1166	   210	        }
  1167	   211	        if self._index_path is not None:
  1168	   212	            self._load_index()
  1169	   213	
  1170	   214	    def fit_curve(
  1171	   215	        self,
  1172	   216	        sensor_id: str,
  1173	   217	        samples: list[CalibrationSample] | tuple[CalibrationSample, ...],
  1174	   218	        *,
  1175	   219	        raw_unit: str = "sensor_unit",
  1176	   220	        sensor_kind: str = "generic",
  1177	   221	        source_session_ids: list[str] | tuple[str, ...] | None = None,
  1178	   222	        max_zones: int = 3,
  1179	   223	        min_points_per_zone: int = 6,
  1180	   224	        max_order: int = 12,
  1181	   225	        target_rmse_k: float = 0.05,
  1182	   226	        metadata: dict[str, Any] | None = None,
  1183	   227	    ) -> CalibrationCurve:
  1184	   228	        if not sensor_id.strip():
  1185	   229	            raise ValueError("sensor_id is required for calibration fit.")
  1186	   230	        if len(samples) < max(4, min_points_per_zone):
  1187	   231	            raise ValueError("Not enough calibration samples for fitting.")
  1188	   232	        normalized_samples = self._preprocess_samples(
  1189	   233	            samples,
  1190	   234	            downsample_target=self._TASK_DOWNSAMPLE_TARGET,
  1191	   235	        )
  1192	   236	        if len(normalized_samples) < max(4, min_points_per_zone):
  1193	   237	            raise ValueError("Not enough calibration samples for fitting after preprocessing.")
  1194	   238	
  1195	   239	        temperatures = np.array(
  1196	   240	            [sample.reference_temperature for sample in normalized_samples], dtype=float
  1197	   241	        )
  1198	   242	        raw_values = np.array(
  1199	   243	            [sample.sensor_raw_value for sample in normalized_samples], dtype=float
  1200	   244	        )
  1201	   245	
  1202	   246	        if not np.all(np.isfinite(raw_values)) or not np.all(np.isfinite(temperatures)):
  1203	   247	            raise ValueError("Calibration samples must contain finite values only.")
  1204	   248	        if np.ptp(raw_values) <= 0 or np.ptp(temperatures) <= 0:
  1205	   249	            raise ValueError("Calibration raw values must span a non-zero range.")
  1206	   250	        zone_slices = self._detect_zone_slices(
  1207	   251	            temperatures,
  1208	   252	            raw_values,
  1209	   253	            max_zones=max(1, max_zones),
  1210	   254	            min_points_per_zone=max(3, min_points_per_zone),
  1211	   255	            max_order=max(1, max_order),
  1212	   256	        )
  1213	   257	        zones = self._fit_zone_slices(
  1214	   258	            temperatures,
  1215	   259	            raw_values,
  1216	   260	            zone_slices=zone_slices,
  1217	
  1218	exec
  1219	/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/engine.py | sed -n '1,110p'" in /Users/vladimir/Projects/cryodaq
  1220	 succeeded in 0ms:
  1221	     1	"""Головной процесс CryoDAQ Engine (безголовый).
  1222	     2	
  1223	     3	Запуск:
  1224	     4	    cryodaq-engine          # через entry point
  1225	     5	    python -m cryodaq.engine  # напрямую
  1226	     6	
  1227	     7	Загружает конфигурации, создаёт и связывает все подсистемы:
  1228	     8	    drivers → DataBroker →
  1229	     9	    [SQLiteWriter, ZMQPublisher, AlarmEngine, InterlockEngine, PluginPipeline]
  1230	    10	
  1231	    11	Корректное завершение по SIGINT / SIGTERM (Unix) или Ctrl+C (Windows).
  1232	    12	"""
  1233	    13	
  1234	    14	from __future__ import annotations
  1235	    15	
  1236	    16	import asyncio
  1237	    17	import logging
  1238	    18	import os
  1239	    19	import signal
  1240	    20	import sys
  1241	    21	import time
  1242	    22	from datetime import UTC, datetime
  1243	    23	
  1244	    24	# Windows: pyzmq требует SelectorEventLoop (не Proactor)
  1245	    25	if sys.platform == "win32":
  1246	    26	    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
  1247	    27	from pathlib import Path
  1248	    28	from typing import Any
  1249	    29	
  1250	    30	import yaml
  1251	    31	
  1252	    32	from cryodaq.analytics.calibration import CalibrationStore
  1253	    33	from cryodaq.analytics.plugin_loader import PluginPipeline
  1254	    34	from cryodaq.analytics.vacuum_trend import VacuumTrendPredictor
  1255	    35	from cryodaq.core.alarm import AlarmEngine
  1256	    36	from cryodaq.core.alarm_config import AlarmConfigError, load_alarm_config
  1257	    37	from cryodaq.core.alarm_providers import ExperimentPhaseProvider, ExperimentSetpointProvider
  1258	    38	from cryodaq.core.alarm_v2 import AlarmEvaluator, AlarmStateManager
  1259	    39	from cryodaq.core.broker import DataBroker
  1260	    40	from cryodaq.core.calibration_acquisition import (
  1261	    41	    CalibrationAcquisitionService,
  1262	    42	    CalibrationCommandError,
  1263	    43	)
  1264	    44	from cryodaq.core.channel_manager import ChannelConfigError, get_channel_manager
  1265	    45	from cryodaq.core.channel_state import ChannelStateTracker
  1266	    46	from cryodaq.core.disk_monitor import DiskMonitor
  1267	    47	from cryodaq.core.event_logger import EventLogger
  1268	    48	from cryodaq.core.experiment import ExperimentManager, ExperimentStatus
  1269	    49	from cryodaq.core.housekeeping import (
  1270	    50	    AdaptiveThrottle,
  1271	    51	    HousekeepingConfigError,
  1272	    52	    HousekeepingService,
  1273	    53	    load_critical_channels_from_alarms_v3,
  1274	    54	    load_housekeeping_config,
  1275	    55	    load_protected_channel_patterns,
  1276	    56	)
  1277	    57	from cryodaq.core.interlock import InterlockConfigError, InterlockEngine
  1278	    58	from cryodaq.core.operator_log import OperatorLogEntry
  1279	    59	from cryodaq.core.rate_estimator import RateEstimator
  1280	    60	from cryodaq.core.safety_broker import SafetyBroker
  1281	    61	from cryodaq.core.safety_manager import SafetyConfigError, SafetyManager
  1282	    62	from cryodaq.core.scheduler import InstrumentConfig, Scheduler
  1283	    63	from cryodaq.core.sensor_diagnostics import SensorDiagnosticsEngine
  1284	    64	from cryodaq.core.smu_channel import normalize_smu_channel
  1285	    65	from cryodaq.core.zmq_bridge import ZMQCommandServer, ZMQPublisher
  1286	    66	from cryodaq.drivers.base import Reading
  1287	    67	from cryodaq.notifications.escalation import EscalationService
  1288	    68	from cryodaq.notifications.periodic_report import PeriodicReporter
  1289	    69	from cryodaq.notifications.telegram_commands import TelegramCommandBot
  1290	    70	from cryodaq.paths import get_config_dir, get_data_dir, get_project_root
  1291	    71	from cryodaq.reporting.generator import ReportGenerator
  1292	    72	from cryodaq.storage.sqlite_writer import SQLiteWriter
  1293	    73	
  1294	    74	logger = logging.getLogger("cryodaq.engine")
  1295	    75	
  1296	    76	# ---------------------------------------------------------------------------
  1297	    77	# Пути по умолчанию (относительно корня проекта)
  1298	    78	# ---------------------------------------------------------------------------
  1299	    79	
  1300	    80	_PROJECT_ROOT = get_project_root()
  1301	    81	_CONFIG_DIR = get_config_dir()
  1302	    82	_PLUGINS_DIR = _PROJECT_ROOT / "plugins"
  1303	    83	_DATA_DIR = get_data_dir()
  1304	    84	
  1305	    85	# Интервал самодиагностики (секунды)
  1306	    86	_WATCHDOG_INTERVAL_S = 30.0
  1307	    87	_LOG_GET_TIMEOUT_S = 1.5
  1308	    88	_EXPERIMENT_STATUS_TIMEOUT_S = 1.5
  1309	    89	
  1310	    90	
  1311	    91	async def _run_keithley_command(
  1312	    92	    action: str,
  1313	    93	    cmd: dict[str, Any],
  1314	    94	    safety_manager: SafetyManager,
  1315	    95	) -> dict[str, Any]:
  1316	    96	    """Dispatch channel-scoped Keithley commands to SafetyManager."""
  1317	    97	    channel = cmd.get("channel")
  1318	    98	
  1319	    99	    if action == "keithley_start":
  1320	   100	        smu_channel = normalize_smu_channel(channel)
  1321	   101	        p = float(cmd.get("p_target", 0))
  1322	   102	        v = float(cmd.get("v_comp", 40))
  1323	   103	        i = float(cmd.get("i_comp", 1.0))
  1324	   104	        return await safety_manager.request_run(p, v, i, channel=smu_channel)
  1325	   105	
  1326	   106	    if action == "keithley_stop":
  1327	   107	        smu_channel = normalize_smu_channel(channel)
  1328	   108	        return await safety_manager.request_stop(channel=smu_channel)
  1329	   109	
  1330	   110	    if action == "keithley_emergency_off":
  1331	
  1332	exec
  1333	/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/analytics/calibration.py | sed -n '400,455p'" in /Users/vladimir/Projects/cryodaq
  1334	 succeeded in 0ms:
  1335	   400	    def export_curve_json(self, sensor_id: str, path: Path | None = None) -> Path:
  1336	   401	        curve = self._require_curve(sensor_id)
  1337	   402	        return self.save_curve(curve, path)
  1338	   403	
  1339	   404	    def export_curve_table(
  1340	   405	        self,
  1341	   406	        sensor_id: str,
  1342	   407	        *,
  1343	   408	        path: Path | None = None,
  1344	   409	        points: int = 200,
  1345	   410	    ) -> Path:
  1346	   411	        curve = self._require_curve(sensor_id)
  1347	   412	        target = path or self._curve_directory(curve.sensor_id, curve.curve_id) / "curve_table.csv"
  1348	   413	        target.parent.mkdir(parents=True, exist_ok=True)
  1349	   414	        raw_min = curve.zones[0].raw_min
  1350	   415	        raw_max = curve.zones[-1].raw_max
  1351	   416	        raw_grid = np.linspace(raw_min, raw_max, max(points, 2))
  1352	   417	        with target.open("w", encoding="utf-8", newline="") as handle:
  1353	   418	            writer = csv.writer(handle)
  1354	   419	            writer.writerow([f"raw_{curve.raw_unit}", "temperature_K"])
  1355	   420	            for raw_value in raw_grid:
  1356	   421	                writer.writerow([float(raw_value), curve.evaluate(float(raw_value))])
  1357	   422	        return target
  1358	   423	
  1359	   424	    def export_curve_cof(
  1360	   425	        self,
  1361	   426	        sensor_id: str,
  1362	   427	        *,
  1363	   428	        path: Path | None = None,
  1364	   429	    ) -> Path:
  1365	   430	        """Export calibration curve as .cof (Chebyshev coefficients) format.
  1366	   431	
  1367	   432	        Unlike .340 which exports sampled breakpoints, .cof preserves the
  1368	   433	        raw fit coefficients per zone. Portable: can be re-evaluated by
  1369	   434	        any code with numpy.polynomial.chebyshev, no CryoDAQ schema
  1370	   435	        dependency.
  1371	   436	        """
  1372	   437	        curve = self._require_curve(sensor_id)
  1373	   438	        target = path or (self._curve_directory(curve.sensor_id, curve.curve_id) / "curve.cof")
  1374	   439	        target.parent.mkdir(parents=True, exist_ok=True)
  1375	   440	        self._write_cof_export(target, curve)
  1376	   441	        self._write_index()
  1377	   442	        return target
  1378	   443	
  1379	   444	    def export_curve_340(
  1380	   445	        self,
  1381	   446	        sensor_id: str,
  1382	   447	        *,
  1383	   448	        path: Path | None = None,
  1384	   449	        points: int = 200,
  1385	   450	    ) -> Path:
  1386	   451	        curve = self._require_curve(sensor_id)
  1387	   452	        if self._exports_dir is None:
  1388	   453	            raise RuntimeError("CalibrationStore base_dir is required for export.")
  1389	   454	        target = path or self._curve_340_path(curve.sensor_id, curve.curve_id)
  1390	   455	        target.parent.mkdir(parents=True, exist_ok=True)
  1391	
  1392	exec
  1393	/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/analytics/calibration.py | sed -n '850,905p'" in /Users/vladimir/Projects/cryodaq
  1394	 succeeded in 0ms:
  1395	   850	            key = (round(item[0], 9), round(item[1], 9))
  1396	   851	            if key in seen:
  1397	   852	                continue
  1398	   853	            seen.add(key)
  1399	   854	            deduped.append(item)
  1400	   855	        return deduped[: max(points, 2)]
  1401	   856	
  1402	   857	    def _write_curve_text_export(
  1403	   858	        self,
  1404	   859	        path: Path,
  1405	   860	        curve: CalibrationCurve,
  1406	   861	        rows: list[tuple[float, float]],
  1407	   862	        *,
  1408	   863	        format_name: str,
  1409	   864	    ) -> None:
  1410	   865	        with path.open("w", encoding="utf-8", newline="") as handle:
  1411	   866	            handle.write(f"# CryoDAQ calibration curve export .{format_name}\n")
  1412	   867	            handle.write(f"# sensor_id: {curve.sensor_id}\n")
  1413	   868	            handle.write(f"# curve_id: {curve.curve_id}\n")
  1414	   869	            handle.write(f"# raw_unit: {curve.raw_unit}\n")
  1415	   870	            handle.write("# columns: temperature_K, sensor_raw\n")
  1416	   871	            writer = csv.writer(handle)
  1417	   872	            for temperature_k, raw_value in rows:
  1418	   873	                writer.writerow([f"{temperature_k:.9g}", f"{raw_value:.9g}"])
  1419	   874	
  1420	   875	    def _write_cof_export(self, path: Path, curve: CalibrationCurve) -> None:
  1421	   876	        """Write .cof format: header + per-zone raw Chebyshev coefficients."""
  1422	   877	        from cryodaq.core.atomic_write import atomic_write_text
  1423	   878	
  1424	   879	        lines: list[str] = []
  1425	   880	        lines.append("# CryoDAQ calibration curve export .cof")
  1426	   881	        lines.append(f"# sensor_id: {curve.sensor_id}")
  1427	   882	        lines.append(f"# curve_id: {curve.curve_id}")
  1428	   883	        lines.append(f"# raw_unit: {curve.raw_unit}")
  1429	   884	        lines.append(f"# fit_timestamp: {curve.fit_timestamp.isoformat()}")
  1430	   885	        lines.append(
  1431	   886	            "# format: Chebyshev T_n(x); raw clipped to [raw_min, raw_max],"
  1432	   887	            " then x = 2*(clipped - raw_min)/(raw_max - raw_min) - 1"
  1433	   888	        )
  1434	   889	        lines.append(f"# zone_count: {len(curve.zones)}")
  1435	   890	        lines.append("")
  1436	   891	        for index, zone in enumerate(curve.zones, start=1):
  1437	   892	            lines.append(f"[zone {index}]")
  1438	   893	            lines.append(f"raw_min: {zone.raw_min:.12g}")
  1439	   894	            lines.append(f"raw_max: {zone.raw_max:.12g}")
  1440	   895	            lines.append(f"order: {zone.order}")
  1441	   896	            coefficients = ", ".join(f"{value:.12g}" for value in zone.coefficients)
  1442	   897	            lines.append(f"coefficients: {coefficients}")
  1443	   898	            lines.append(f"# rmse_k: {zone.rmse_k:.6g}")
  1444	   899	            lines.append(f"# max_abs_error_k: {zone.max_abs_error_k:.6g}")
  1445	   900	            lines.append(f"# point_count: {zone.point_count}")
  1446	   901	            lines.append("")
  1447	   902	        atomic_write_text(path, "\n".join(lines))
  1448	   903	
  1449	   904	    def _import_curve_text(
  1450	   905	        self,
  1451	
  1452	exec
  1453	/opt/homebrew/bin/bash -lc "nl -ba CHANGELOG.md | sed -n '1448,1465p'" in /Users/vladimir/Projects/cryodaq
  1454	 succeeded in 0ms:
  1455	  1448	Полный pipeline калибровки v2: непрерывный сбор SRDG при
  1456	  1449	калибровочных экспериментах, post-run pipeline, трёхрежимный GUI.
  1457	  1450	
  1458	  1451	### Добавлено
  1459	  1452	
  1460	  1453	- **`CalibrationAcquisitionService`** — непрерывный сбор SRDG
  1461	  1454	  параллельно с KRDG при калибровочном эксперименте.
  1462	  1455	- **`CalibrationFitter`** — post-run pipeline: извлечение пар из SQLite,
  1463	  1456	  адаптивный downsample, Douglas-Peucker breakpoints, Chebyshev fit.
  1464	  1457	- **Калибровка GUI** — трёхрежимная вкладка: Setup (выбор каналов,
  1465	  1458	  импорт) → Acquisition (live stats, coverage bar) → Results (метрики,
  1466	  1459	  export). `.330` / `.340` / JSON export.
  1467	  1460	
  1468	  1461	### Изменено
  1469	  1462	
  1470	  1463	- Удалён legacy `CalibrationSessionStore` и ручной workflow.
  1471	  1464	
  1472	  1465	Диапазон коммитов: `81ef8a6`..`98a5951` (4 commits)
  1473	
  1474	exec
  1475	/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/engine.py | sed -n '1598,1640p'" in /Users/vladimir/Projects/cryodaq
  1476	exec
  1477	/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/gui/shell/overlays/conductivity_panel.py | sed -n '1308,1335p'" in /Users/vladimir/Projects/cryodaq
  1478	 succeeded in 0ms:
  1479	  1308	    # Flight recorder
  1480	  1309	    # ------------------------------------------------------------------
  1481	  1310	
  1482	  1311	    def _write_flight_log(self, now: float, preds: dict) -> None:
  1483	  1312	        if len(self._chain) < 2:
  1484	  1313	            return
  1485	  1314	        if self._flight_log is None:
  1486	  1315	            from cryodaq.paths import get_data_dir
  1487	  1316	
  1488	  1317	            log_dir = get_data_dir() / "conductivity_logs"
  1489	  1318	            log_dir.mkdir(parents=True, exist_ok=True)
  1490	  1319	            ts_str = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
  1491	  1320	            log_path = log_dir / f"conductivity_{ts_str}.csv"
  1492	  1321	            self._flight_log = log_path.open("w", newline="", encoding="utf-8-sig")
  1493	  1322	            self._flight_log_writer = csv.writer(self._flight_log)
  1494	  1323	            self._flight_log_writer.writerow(
  1495	  1324	                [
  1496	  1325	                    "timestamp_utc",
  1497	  1326	                    "elapsed_s",
  1498	  1327	                    "T_hot",
  1499	  1328	                    "T_cold",
  1500	  1329	                    "dT",
  1501	  1330	                    "P",
  1502	  1331	                    "R_measured",
  1503	  1332	                    "G_measured",
  1504	  1333	                    "R_predicted",
  1505	  1334	                    "G_predicted",
  1506	  1335	                    "percent_settled_hot",
  1507	
  1508	 succeeded in 0ms:
  1509	  1598	    await interlock_engine.start()
  1510	  1599	    await plugin_pipeline.start()
  1511	  1600	    if cooldown_service is not None:
  1512	  1601	        await cooldown_service.start()
  1513	  1602	    if periodic_reporter is not None:
  1514	  1603	        await periodic_reporter.start()
  1515	  1604	    if telegram_bot is not None:
  1516	  1605	        await telegram_bot.start()
  1517	  1606	    await scheduler.start()
  1518	  1607	    throttle_task = asyncio.create_task(_track_runtime_signals(), name="adaptive_throttle_runtime")
  1519	  1608	    alarm_v2_feed_task = asyncio.create_task(_alarm_v2_feed_readings(), name="alarm_v2_feed")
  1520	  1609	    alarm_v2_tick_task: asyncio.Task | None = None
  1521	  1610	    if _alarm_v2_configs:
  1522	  1611	        alarm_v2_tick_task = asyncio.create_task(_alarm_v2_tick(), name="alarm_v2_tick")
  1523	  1612	    sd_feed_task: asyncio.Task | None = None
  1524	  1613	    sd_tick_task: asyncio.Task | None = None
  1525	  1614	    if sensor_diag is not None:
  1526	  1615	        sd_feed_task = asyncio.create_task(_sensor_diag_feed(), name="sensor_diag_feed")
  1527	  1616	        sd_tick_task = asyncio.create_task(_sensor_diag_tick(), name="sensor_diag_tick")
  1528	  1617	    vt_feed_task: asyncio.Task | None = None
  1529	  1618	    vt_tick_task: asyncio.Task | None = None
  1530	  1619	    if vacuum_trend is not None:
  1531	  1620	        vt_feed_task = asyncio.create_task(_vacuum_trend_feed(), name="vacuum_trend_feed")
  1532	  1621	        vt_tick_task = asyncio.create_task(_vacuum_trend_tick(), name="vacuum_trend_tick")
  1533	  1622	    await housekeeping_service.start()
  1534	  1623	
  1535	  1624	    # Watchdog
  1536	  1625	    watchdog_task = asyncio.create_task(
  1537	  1626	        _watchdog(broker, scheduler, writer, start_ts),
  1538	  1627	        name="engine_watchdog",
  1539	  1628	    )
  1540	  1629	
  1541	  1630	    # DiskMonitor — also wires the writer so disk-recovery can clear the
  1542	  1631	    # _disk_full flag (Phase 2a H.1).
  1543	  1632	    disk_monitor = DiskMonitor(data_dir=_DATA_DIR, broker=broker, sqlite_writer=writer)
  1544	  1633	    await disk_monitor.start()
  1545	  1634	
  1546	  1635	    logger.info(
  1547	  1636	        "═══ CryoDAQ Engine запущен ═══ | приборов=%d | тревог=%d | блокировок=%d | mock=%s",
  1548	  1637	        len(driver_configs),
  1549	  1638	        len(alarm_engine.get_state()),
  1550	  1639	        len(interlock_engine.get_state()),
  1551	  1640	        mock,
  1552	
  1553	exec
  1554	/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/web/server.py | sed -n '300,324p'" in /Users/vladimir/Projects/cryodaq
  1555	 succeeded in 0ms:
  1556	   300	        description="Удалённый мониторинг криогенной системы",
  1557	   301	        version=_VERSION,
  1558	   302	    )
  1559	   303	
  1560	   304	    _zmq_task: asyncio.Task[None] | None = None
  1561	   305	    _pump_task: asyncio.Task[None] | None = None
  1562	   306	
  1563	   307	    @application.on_event("startup")
  1564	   308	    async def _startup() -> None:
  1565	   309	        nonlocal _zmq_task, _pump_task
  1566	   310	        # Инициализируем очередь в контексте event loop
  1567	   311	        _state.broadcast_q = asyncio.Queue(maxsize=200)
  1568	   312	        _pump_task = asyncio.create_task(_broadcast_pump(), name="broadcast_pump")
  1569	   313	        _zmq_task = asyncio.create_task(_zmq_to_ws_bridge(), name="zmq_ws_bridge")
  1570	   314	        logger.info("Веб-сервер CryoDAQ запущен")
  1571	   315	
  1572	   316	    @application.on_event("shutdown")
  1573	   317	    async def _shutdown() -> None:
  1574	   318	        for task in (_zmq_task, _pump_task):
  1575	   319	            if task and not task.done():
  1576	   320	                task.cancel()
  1577	   321	                try:
  1578	   322	                    await task
  1579	   323	                except asyncio.CancelledError:
  1580	   324	                    pass
  1581	
  1582	exec
  1583	/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/engine.py | sed -n '1680,1785p'" in /Users/vladimir/Projects/cryodaq
  1584	 succeeded in 0ms:
  1585	  1680	        pass
  1586	  1681	    if alarm_v2_tick_task is not None:
  1587	  1682	        alarm_v2_tick_task.cancel()
  1588	  1683	        try:
  1589	  1684	            await alarm_v2_tick_task
  1590	  1685	        except asyncio.CancelledError:
  1591	  1686	            pass
  1592	  1687	
  1593	  1688	    if sd_feed_task is not None:
  1594	  1689	        sd_feed_task.cancel()
  1595	  1690	        try:
  1596	  1691	            await sd_feed_task
  1597	  1692	        except asyncio.CancelledError:
  1598	  1693	            pass
  1599	  1694	    if sd_tick_task is not None:
  1600	  1695	        sd_tick_task.cancel()
  1601	  1696	        try:
  1602	  1697	            await sd_tick_task
  1603	  1698	        except asyncio.CancelledError:
  1604	  1699	            pass
  1605	  1700	
  1606	  1701	    if vt_feed_task is not None:
  1607	  1702	        vt_feed_task.cancel()
  1608	  1703	        try:
  1609	  1704	            await vt_feed_task
  1610	  1705	        except asyncio.CancelledError:
  1611	  1706	            pass
  1612	  1707	    if vt_tick_task is not None:
  1613	  1708	        vt_tick_task.cancel()
  1614	  1709	        try:
  1615	  1710	            await vt_tick_task
  1616	  1711	        except asyncio.CancelledError:
  1617	  1712	            pass
  1618	  1713	
  1619	  1714	    # Порядок: scheduler → plugins → alarms → interlocks → writer → zmq
  1620	  1715	    await scheduler.stop()
  1621	  1716	    logger.info("Планировщик остановлен")
  1622	  1717	
  1623	  1718	    await plugin_pipeline.stop()
  1624	  1719	    logger.info("Пайплайн плагинов остановлен")
  1625	  1720	
  1626	  1721	    if cooldown_service is not None:
  1627	  1722	        await cooldown_service.stop()
  1628	  1723	        logger.info("CooldownService остановлен")
  1629	  1724	
  1630	  1725	    if periodic_reporter is not None:
  1631	  1726	        await periodic_reporter.stop()
  1632	  1727	        logger.info("PeriodicReporter остановлен")
  1633	  1728	
  1634	  1729	    if telegram_bot is not None:
  1635	  1730	        await telegram_bot.stop()
  1636	  1731	        logger.info("TelegramCommandBot остановлен")
  1637	  1732	
  1638	  1733	    await alarm_engine.stop()
  1639	  1734	    logger.info("Движок тревог остановлен")
  1640	  1735	
  1641	  1736	    await interlock_engine.stop()
  1642	  1737	    logger.info("Движок блокировок остановлен")
  1643	  1738	
  1644	  1739	    await safety_manager.stop()
  1645	  1740	    logger.info("SafetyManager остановлен: состояние=%s", safety_manager.state.value)
  1646	  1741	
  1647	  1742	    await disk_monitor.stop()
  1648	  1743	    logger.info("DiskMonitor остановлен")
  1649	  1744	
  1650	  1745	    await housekeeping_service.stop()
  1651	  1746	    logger.info("HousekeepingService остановлен")
  1652	  1747	
  1653	  1748	    await writer.stop()
  1654	  1749	    logger.info("SQLite записано: %d", writer.stats.get("total_written", 0))
  1655	  1750	
  1656	  1751	    await cmd_server.stop()
  1657	  1752	    logger.info("ZMQ CommandServer остановлен")
  1658	  1753	
  1659	  1754	    await zmq_pub.stop()
  1660	  1755	    logger.info("ZMQ Publisher остановлен")
  1661	  1756	
  1662	  1757	    from cryodaq.drivers.transport.gpib import GPIBTransport
  1663	  1758	
  1664	  1759	    GPIBTransport.close_all_managers()
  1665	  1760	    logger.info("GPIB ResourceManagers закрыты")
  1666	  1761	
  1667	  1762	    uptime = time.monotonic() - start_ts
  1668	  1763	    logger.info(
  1669	  1764	        "═══ CryoDAQ Engine завершён ═══ | uptime=%.1f с",
  1670	  1765	        uptime,
  1671	  1766	    )
  1672	  1767	
  1673	  1768	
  1674	  1769	# ---------------------------------------------------------------------------
  1675	  1770	# Single-instance guard
  1676	  1771	# ---------------------------------------------------------------------------
  1677	  1772	
  1678	  1773	_LOCK_FILE = get_data_dir() / ".engine.lock"
  1679	  1774	
  1680	  1775	
  1681	  1776	def _is_pid_alive(pid: int) -> bool:
  1682	  1777	    """Check if process with given PID exists."""
  1683	  1778	    try:
  1684	  1779	        if sys.platform == "win32":
  1685	  1780	            import ctypes
  1686	  1781	
  1687	  1782	            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
  1688	  1783	            if handle:
  1689	  1784	                ctypes.windll.kernel32.CloseHandle(handle)
  1690	  1785	                return True
  1691	
  1692	exec
  1693	/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/engine.py | sed -n '1640,1682p'" in /Users/vladimir/Projects/cryodaq
  1694	 succeeded in 0ms:
  1695	  1640	        mock,
  1696	  1641	    )
  1697	  1642	
  1698	  1643	    # --- Ожидание сигнала завершения ---
  1699	  1644	    shutdown_event = asyncio.Event()
  1700	  1645	
  1701	  1646	    def _request_shutdown() -> None:
  1702	  1647	        logger.info("Получен сигнал завершения")
  1703	  1648	        shutdown_event.set()
  1704	  1649	
  1705	  1650	    # Регистрация обработчиков сигналов
  1706	  1651	    loop = asyncio.get_running_loop()
  1707	  1652	    if sys.platform != "win32":
  1708	  1653	        loop.add_signal_handler(signal.SIGINT, _request_shutdown)
  1709	  1654	        loop.add_signal_handler(signal.SIGTERM, _request_shutdown)
  1710	  1655	    else:
  1711	  1656	        # Windows: signal.signal работает только в главном потоке
  1712	  1657	        signal.signal(signal.SIGINT, lambda *_: _request_shutdown())
  1713	  1658	
  1714	  1659	    await shutdown_event.wait()
  1715	  1660	
  1716	  1661	    # --- Корректное завершение ---
  1717	  1662	    logger.info("═══ Завершение CryoDAQ Engine ═══")
  1718	  1663	
  1719	  1664	    watchdog_task.cancel()
  1720	  1665	    try:
  1721	  1666	        await watchdog_task
  1722	  1667	    except asyncio.CancelledError:
  1723	  1668	        pass
  1724	  1669	
  1725	  1670	    throttle_task.cancel()
  1726	  1671	    try:
  1727	  1672	        await throttle_task
  1728	  1673	    except asyncio.CancelledError:
  1729	  1674	        pass
  1730	  1675	
  1731	  1676	    alarm_v2_feed_task.cancel()
  1732	  1677	    try:
  1733	  1678	        await alarm_v2_feed_task
  1734	  1679	    except asyncio.CancelledError:
  1735	  1680	        pass
  1736	  1681	    if alarm_v2_tick_task is not None:
  1737	  1682	        alarm_v2_tick_task.cancel()
  1738	
  1739	exec
  1740	/opt/homebrew/bin/bash -lc "rg -n \"_flight_log|close\\(\" src/cryodaq/gui/shell/overlays/conductivity_panel.py" in /Users/vladimir/Projects/cryodaq
  1741	 succeeded in 0ms:
  1742	247:        self._flight_log = None
  1743	248:        self._flight_log_writer = None
  1744	873:        self._write_flight_log(now, all_preds)
  1745	1311:    def _write_flight_log(self, now: float, preds: dict) -> None:
  1746	1314:        if self._flight_log is None:
  1747	1321:            self._flight_log = log_path.open("w", newline="", encoding="utf-8-sig")
  1748	1322:            self._flight_log_writer = csv.writer(self._flight_log)
  1749	1323:            self._flight_log_writer.writerow(
  1750	1381:        self._flight_log_writer.writerow(
  1751	1403:        self._flight_log.flush()
  1752	1406:        if self._flight_log:
  1753	1407:            self._flight_log.close()
  1754	1408:            self._flight_log = None
  1755	
  1756	exec
  1757	/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/gui/shell/overlays/conductivity_panel.py | sed -n '1396,1412p'" in /Users/vladimir/Projects/cryodaq
  1758	 succeeded in 0ms:
  1759	  1396	                f"{tau_cold:.1f}",
  1760	  1397	                f"{T_inf_hot:.6f}",
  1761	  1398	                f"{T_inf_cold:.6f}",
  1762	  1399	                step,
  1763	  1400	                f"{step_P:.6g}",
  1764	  1401	            ]
  1765	  1402	        )
  1766	  1403	        self._flight_log.flush()
  1767	  1404	
  1768	  1405	    def closeEvent(self, event) -> None:
  1769	  1406	        if self._flight_log:
  1770	  1407	            self._flight_log.close()
  1771	  1408	            self._flight_log = None
  1772	  1409	        super().closeEvent(event)
  1773	  1410	
  1774	  1411	    # ------------------------------------------------------------------
  1775	  1412	    # Manual CSV export
  1776	
  1777	exec
  1778	/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/engine.py | sed -n '1792,1850p'" in /Users/vladimir/Projects/cryodaq
  1779	 succeeded in 0ms:
  1780	  1792	
  1781	  1793	
  1782	  1794	def _acquire_engine_lock() -> int:
  1783	  1795	    """Acquire exclusive engine lock via flock/msvcrt. Returns fd.
  1784	  1796	
  1785	  1797	    If lock is held by a dead process, auto-cleans and retries.
  1786	  1798	    Shows helpful error with PID and kill command if lock is live.
  1787	  1799	    """
  1788	  1800	    _LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
  1789	  1801	    fd = os.open(str(_LOCK_FILE), os.O_CREAT | os.O_RDWR, 0o644)
  1790	  1802	    try:
  1791	  1803	        if sys.platform == "win32":
  1792	  1804	            import msvcrt
  1793	  1805	
  1794	  1806	            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
  1795	  1807	        else:
  1796	  1808	            import fcntl
  1797	  1809	
  1798	  1810	            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
  1799	  1811	    except OSError:
  1800	  1812	        # Lock held by another process (flock/msvcrt is authoritative)
  1801	  1813	        os.close(fd)
  1802	  1814	        logger.error(
  1803	  1815	            "CryoDAQ engine уже запущен (lock: %s).\n"
  1804	  1816	            "  Для принудительного запуска: cryodaq-engine --force\n"
  1805	  1817	            "  Или завершите процесс через Диспетчер задач (python/pythonw).",
  1806	  1818	            _LOCK_FILE,
  1807	  1819	        )
  1808	  1820	        raise SystemExit(1)
  1809	  1821	
  1810	  1822	    os.ftruncate(fd, 0)
  1811	  1823	    os.lseek(fd, 0, os.SEEK_SET)
  1812	  1824	    os.write(fd, f"{os.getpid()}\n".encode())
  1813	  1825	    return fd
  1814	  1826	
  1815	  1827	
  1816	  1828	def _force_kill_existing() -> None:
  1817	  1829	    """Force-kill any running engine and remove lock."""
  1818	  1830	    if not _LOCK_FILE.exists():
  1819	  1831	        return
  1820	  1832	    # Read PID via os.open — works even when file is locked by msvcrt
  1821	  1833	    pid = None
  1822	  1834	    fd = None
  1823	  1835	    try:
  1824	  1836	        fd = os.open(str(_LOCK_FILE), os.O_RDONLY)
  1825	  1837	        raw = os.read(fd, 64).decode().strip()
  1826	  1838	        pid = int(raw)
  1827	  1839	    except (OSError, ValueError):
  1828	  1840	        pass
  1829	  1841	    finally:
  1830	  1842	        if fd is not None:
  1831	  1843	            try:
  1832	  1844	                os.close(fd)
  1833	  1845	            except OSError:
  1834	  1846	                pass
  1835	  1847	    if pid is None:
  1836	  1848	        try:
  1837	  1849	            _LOCK_FILE.unlink(missing_ok=True)
  1838	  1850	        except OSError:
  1839	
  1840	exec
  1841	/opt/homebrew/bin/bash -lc "rg -n \"_acquire_engine_lock|os\\.close\\(lock|lock_fd|engine_lock\" src/cryodaq/engine.py" in /Users/vladimir/Projects/cryodaq
  1842	 succeeded in 0ms:
  1843	1794:def _acquire_engine_lock() -> int:
  1844	1879:def _release_engine_lock(fd: int) -> None:
  1845	1918:    lock_fd = _acquire_engine_lock()
  1846	1968:        _release_engine_lock(lock_fd)
  1847	
  1848	exec
  1849	/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/engine.py | sed -n '1868,1972p'" in /Users/vladimir/Projects/cryodaq
  1850	 succeeded in 0ms:
  1851	  1868	                break
  1852	  1869	        else:
  1853	  1870	            logger.error("PID %d не завершился после 5с", pid)
  1854	  1871	            raise SystemExit(1)
  1855	  1872	    try:
  1856	  1873	        _LOCK_FILE.unlink(missing_ok=True)
  1857	  1874	    except OSError:
  1858	  1875	        logger.debug("Lock file busy (will be released by OS)")
  1859	  1876	    logger.info("Старый engine остановлен, lock очищен")
  1860	  1877	
  1861	  1878	
  1862	  1879	def _release_engine_lock(fd: int) -> None:
  1863	  1880	    try:
  1864	  1881	        os.close(fd)
  1865	  1882	    except OSError:
  1866	  1883	        pass
  1867	  1884	    try:
  1868	  1885	        _LOCK_FILE.unlink(missing_ok=True)
  1869	  1886	    except OSError:
  1870	  1887	        pass
  1871	  1888	
  1872	  1889	
  1873	  1890	# ---------------------------------------------------------------------------
  1874	  1891	# Entry point
  1875	  1892	# ---------------------------------------------------------------------------
  1876	  1893	
  1877	  1894	#: Exit code for unrecoverable startup config errors (Phase 2b H.3).
  1878	  1895	#: Launcher detects this and refuses to auto-restart.
  1879	  1896	ENGINE_CONFIG_ERROR_EXIT_CODE = 2
  1880	  1897	
  1881	  1898	
  1882	  1899	def main() -> None:
  1883	  1900	    """Точка входа cryodaq-engine."""
  1884	  1901	    import argparse
  1885	  1902	    import traceback
  1886	  1903	
  1887	  1904	    parser = argparse.ArgumentParser(description="CryoDAQ Engine")
  1888	  1905	    parser.add_argument("--mock", action="store_true", help="Mock mode (simulated instruments)")
  1889	  1906	    parser.add_argument("--force", action="store_true", help="Kill existing engine and take over")
  1890	  1907	    args = parser.parse_args()
  1891	  1908	
  1892	  1909	    from cryodaq.logging_setup import resolve_log_level, setup_logging
  1893	  1910	
  1894	  1911	    setup_logging("engine", level=resolve_log_level())
  1895	  1912	
  1896	  1913	    if args.force:
  1897	  1914	        _force_kill_existing()
  1898	  1915	
  1899	  1916	    mock = args.mock or os.environ.get("CRYODAQ_MOCK", "").lower() in ("1", "true")
  1900	  1917	
  1901	  1918	    lock_fd = _acquire_engine_lock()
  1902	  1919	    try:
  1903	  1920	        if mock:
  1904	  1921	            logger.info("Режим MOCK: реальные приборы не используются")
  1905	  1922	        try:
  1906	  1923	            asyncio.run(_run_engine(mock=mock))
  1907	  1924	        except KeyboardInterrupt:
  1908	  1925	            logger.info("Прервано оператором (Ctrl+C)")
  1909	  1926	        except yaml.YAMLError as exc:
  1910	  1927	            # Phase 2b H.3: a YAML parse error during startup is
  1911	  1928	            # unrecoverable by retry — exit with a distinct code so the
  1912	  1929	            # launcher refuses to spin in a tight restart loop.
  1913	  1930	            logger.critical(
  1914	  1931	                "CONFIG ERROR (YAML parse): %s\n%s",
  1915	  1932	                exc,
  1916	  1933	                traceback.format_exc(),
  1917	  1934	            )
  1918	  1935	            sys.exit(ENGINE_CONFIG_ERROR_EXIT_CODE)
  1919	  1936	        except FileNotFoundError as exc:
  1920	  1937	            # Missing required config file at startup is also a config
  1921	  1938	            # error: same exit code.
  1922	  1939	            logger.critical(
  1923	  1940	                "CONFIG ERROR (file not found): %s\n%s",
  1924	  1941	                exc,
  1925	  1942	                traceback.format_exc(),
  1926	  1943	            )
  1927	  1944	            sys.exit(ENGINE_CONFIG_ERROR_EXIT_CODE)
  1928	  1945	        except (
  1929	  1946	            SafetyConfigError,
  1930	  1947	            AlarmConfigError,
  1931	  1948	            InterlockConfigError,
  1932	  1949	            HousekeepingConfigError,
  1933	  1950	            ChannelConfigError,
  1934	  1951	        ) as exc:
  1935	  1952	            labels = {
  1936	  1953	                SafetyConfigError: "safety",
  1937	  1954	                AlarmConfigError: "alarm",
  1938	  1955	                InterlockConfigError: "interlock",
  1939	  1956	                HousekeepingConfigError: "housekeeping",
  1940	  1957	                ChannelConfigError: "channel",
  1941	  1958	            }
  1942	  1959	            label = labels.get(type(exc), "config")
  1943	  1960	            logger.critical(
  1944	  1961	                "CONFIG ERROR (%s config): %s\n%s",
  1945	  1962	                label,
  1946	  1963	                exc,
  1947	  1964	                traceback.format_exc(),
  1948	  1965	            )
  1949	  1966	            sys.exit(ENGINE_CONFIG_ERROR_EXIT_CODE)
  1950	  1967	    finally:
  1951	  1968	        _release_engine_lock(lock_fd)
  1952	  1969	
  1953	  1970	
  1954	  1971	if __name__ == "__main__":
  1955	  1972	    main()
  1956	
  1957	exec
  1958	/opt/homebrew/bin/bash -lc "nl -ba docs/ORCHESTRATION.md | sed -n '629,740p'" in /Users/vladimir/Projects/cryodaq
  1959	exec
  1960	/opt/homebrew/bin/bash -lc 'git cat-file -p HEAD' in /Users/vladimir/Projects/cryodaq
  1961	 succeeded in 0ms:
  1962	tree 38f00b81219f6671238719750345b2fa55fdf24e
  1963	parent c1e5a20be788e40f4941505861689f9473624576
  1964	author Vladimir Fomenko <polsovatel111@gmail.com> 1777331709 +0300
  1965	committer Vladimir Fomenko <polsovatel111@gmail.com> 1777331709 +0300
  1966	
  1967	artifacts: commit cof migration + cof-gui audit consultations + recon
  1968	
  1969	Per ORCHESTRATION §6.4, consultant prompt + response files belong
  1970	under artifacts/consultations/<date>/<topic>/. These cover dual-
  1971	verifier audits for .cof backend migration (Codex + Gemini) and
  1972	.cof GUI wiring (Codex + Gemini).
  1973	
  1974	Also commits pre-/ultrareview recon doc.
  1975	
  1976	Includes:
  1977	- 2026-04-28-cof-migration/ (4 files: prompt+response × 2 verifiers)
  1978	- 2026-04-28-cof-gui-audit/ (4 files: prompt+response × 2 verifiers)
  1979	- artifacts/2026-04-28-pre-ultrareview-recon.md (recon inventory)
  1980	
  1981	Ref: artifacts/handoffs/2026-04-28-cof-{migration,gui}-review.md
  1982	Batch: phase-D / consultations-archive
  1983	Risk: docs only.
  1984	
  1985	Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
  1986	
  1987	 succeeded in 0ms:
  1988	   629	## 14. Verification practices
  1989	   630	
  1990	   631	Added 2026-04-28 (v1.2) consolidating recon, verification, and
  1991	   632	dual-verifier patterns surfaced through vault build, vault audit,
  1992	   633	B1 investigation, and `.cof` migration sessions.
  1993	   634	
  1994	   635	### 14.1 Recon before execution
  1995	   636	
  1996	   637	Architect plans contain stale assumptions. Before executing any
  1997	   638	multi-step plan, CC performs recon (read-only) and reports actual
  1998	   639	state vs plan-expected state:
  1999	   640	
  2000	   641	- `git status` + `git log -3 --oneline`
  2001	   642	- `git tag -l` if plan references tags
  2002	   643	- Inventory of touched files (existence, last_modified)
  2003	   644	- Dependency state (skills, configs, worktrees) per plan scope
  2004	   645	
  2005	   646	If reality differs materially from plan: STOP, report diff, await
  2006	   647	architect adjustment. If reality matches: proceed.
  2007	   648	
  2008	   649	This pattern caught vault folder collision (overnight build),
  2009	   650	retroactive tag execution memory gap, mystery `channels.yaml`
  2010	   651	modification — each would have caused silent corruption if CC
  2011	   652	had executed the plan blindly.
  2012	   653	
  2013	   654	### 14.2 Dual-verifier complementary review
  2014	   655	
  2015	   656	Codex (literal) and Gemini (structural) have non-overlapping
  2016	   657	strengths. Pair them for non-trivial code review:
  2017	   658	
  2018	   659	- **Codex** (`gpt-5.5 high`): verifies declared scope file-by-file,
  2019	   660	  line-level precision, file:line citations. Strong on factual
  2020	   661	  correctness within stated boundaries. Tends to NOT grep callers
  2021	   662	  or check downstream impact unless prompted explicitly.
  2022	   663	
  2023	   664	- **Gemini** (`gemini-3.1-pro-preview`): wide-context audit, finds
  2024	   665	  cross-file inconsistency, caller-impact, doc-vs-code drift. 1M
  2025	   666	  context lets it read related files Codex would skip. Verbose
  2026	   667	  by default — needs explicit output cap and table-first format.
  2027	   668	
  2028	   669	The 2026-04-28 `.cof` migration audit demonstrated the pattern:
  2029	   670	Codex CONDITIONAL on `calibration.py` with 1 LOW finding (all
  2030	   671	declared scope green). Gemini CRITICAL — found `engine.py` still
  2031	   672	called removed `export_curve_330()`, missed by Codex because
  2032	   673	Codex didn't grep caller sites. Without Gemini, the merge would
  2033	   674	have shipped a runtime `AttributeError`.
  2034	   675	
  2035	   676	Pair both verifiers when:
  2036	   677	- Public API changes (callers in unknown locations)
  2037	   678	- Removal of exported names (must grep all callers)
  2038	   679	- Structural refactor across multiple files
  2039	   680	- Doc claims that reference code state
  2040	   681	
  2041	   682	Skip dual-verifier when:
  2042	   683	- Single-file localized change with clear scope
  2043	   684	- Test-only addition
  2044	   685	- Pure documentation update without code claims
  2045	   686	
  2046	   687	### 14.3 Propagation gap when fixing flagged content
  2047	   688	
  2048	   689	Audit findings frequently surface in one location while equivalent
  2049	   690	stale claims exist in others. When applying a fix to a flagged
  2050	   691	note/file/doc:
  2051	   692	
  2052	   693	1. Grep all related artifacts for the corrected claim
  2053	   694	2. Fix all instances in single batch
  2054	   695	3. Don't merge until grep is clean
  2055	   696	
  2056	   697	The 2026-04-27 vault audit caught Т4 interlock fact landing
  2057	   698	correctly in `Cyrillic homoglyph` note while staying stale in
  2058	   699	`Hardware setup` AND `LakeShore 218S` See-also section. Three
  2059	   700	notes, one fact, propagation incomplete because audit fixes were
  2060	   701	per-flagged-file rather than per-claim.
  2061	   702	
  2062	   703	Same pattern applies to repo: removing `export_curve_330` from
  2063	   704	`calibration.py` without removing the caller in `engine.py` is
  2064	   705	the same bug class one level higher.
  2065	   706	
  2066	   707	Discipline: before committing, `grep -rn <claim>` across the
  2067	   708	edit's blast radius. Repository or vault, doesn't matter.
  2068	   709	
  2069	   710	### 14.4 Cross-branch divergence check
  2070	   711	
  2071	   712	Before any cross-branch operation (merge, cherry-pick, rebase,
  2072	   713	feature work depending on master state):
  2073	   714	
  2074	   715	```
  2075	   716	git rev-list --left-right --count master...feat/branch
  2076	   717	```
  2077	   718	
  2078	   719	Format: `<commits-on-master-not-in-branch> <commits-on-branch-not-in-master>`.
  2079	   720	
  2080	   721	Outputs to interpret:
  2081	   722	- `0 N` — branch is ahead, clean fast-forward possible
  2082	   723	- `M 0` — branch is behind, rebase or merge master in first
  2083	   724	- `M N` — both diverged, merge will be no-ff with potential
  2084	   725	  conflicts
  2085	   726	- `0 0` — branches identical (suspicious — verify intent)
  2086	   727	
  2087	   728	Run before merge to catch unexpected drift. Run before starting
  2088	   729	work on a branch to know whether rebase is needed.
  2089	   730	
  2090	   731	### 14.5 rtk-ai proxy filters merge commits
  2091	   732	
  2092	   733	The rtk-ai proxy compresses shell output before reaching CC's
  2093	   734	context. Side-effect: `git log --oneline` may omit merge commits
  2094	   735	from display, making merge commits invisible without explicit
  2095	   736	verification.
  2096	   737	
  2097	   738	When verifying merge state or parent SHAs, use direct git commands
  2098	   739	that bypass abbreviated formats:
  2099	   740	
  2100	
  2101	exec
  2102	/opt/homebrew/bin/bash -lc 'git log -1 --oneline' in /Users/vladimir/Projects/cryodaq
  2103	 succeeded in 0ms:
  2104	95240ae artifacts: commit cof migration + cof-gui audit consultations + recon
  2105	
  2106	exec
  2107	/opt/homebrew/bin/bash -lc "rg -n \"v1\\.2|Verification practices|14\\.5\" docs/ORCHESTRATION.md" in /Users/vladimir/Projects/cryodaq
  2108	 succeeded in 0ms:
  2109	3:**Authoritative as of 2026-04-28 (v1.2).** Supersedes ad-hoc multi-agent
  2110	4:coordination from 2026-04-21 to 2026-04-23. v1.2 incorporates calibration
  2111	629:## 14. Verification practices
  2112	631:Added 2026-04-28 (v1.2) consolidating recon, verification, and
  2113	731:### 14.5 rtk-ai proxy filters merge commits
  2114	763:(web), 2026-04-23 (v1.1) — extended 2026-04-28 (v1.2).*
  2115	
  2116	codex
  2117	I have enough evidence for the audit. Before closing, I’m applying the verification-before-completion workflow and then I’ll attempt to write the requested response file; the sandbox may reject the write because this session is read-only.
  2118	exec
  2119	/opt/homebrew/bin/bash -lc "sed -n '1,220p' /Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6021bacf3ca29d13980d0636b7162767b3e9d301/skills/verification-before-completion/SKILL.md" in /Users/vladimir/Projects/cryodaq
  2120	 succeeded in 0ms:
  2121	---
  2122	name: verification-before-completion
  2123	description: Use when about to claim work is complete, fixed, or passing, before committing or creating PRs - requires running verification commands and confirming output before making any success claims; evidence before assertions always
  2124	---
  2125	
  2126	# Verification Before Completion
  2127	
  2128	## Overview
  2129	
  2130	Claiming work is complete without verification is dishonesty, not efficiency.
  2131	
  2132	**Core principle:** Evidence before claims, always.
  2133	
  2134	**Violating the letter of this rule is violating the spirit of this rule.**
  2135	
  2136	## The Iron Law
  2137	
  2138	```
  2139	NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE
  2140	```
  2141	
  2142	If you haven't run the verification command in this message, you cannot claim it passes.
  2143	
  2144	## The Gate Function
  2145	
  2146	```
  2147	BEFORE claiming any status or expressing satisfaction:
  2148	
  2149	1. IDENTIFY: What command proves this claim?
  2150	2. RUN: Execute the FULL command (fresh, complete)
  2151	3. READ: Full output, check exit code, count failures
  2152	4. VERIFY: Does output confirm the claim?
  2153	   - If NO: State actual status with evidence
  2154	   - If YES: State claim WITH evidence
  2155	5. ONLY THEN: Make the claim
  2156	
  2157	Skip any step = lying, not verifying
  2158	```
  2159	
  2160	## Common Failures
  2161	
  2162	| Claim | Requires | Not Sufficient |
  2163	|-------|----------|----------------|
  2164	| Tests pass | Test command output: 0 failures | Previous run, "should pass" |
  2165	| Linter clean | Linter output: 0 errors | Partial check, extrapolation |
  2166	| Build succeeds | Build command: exit 0 | Linter passing, logs look good |
  2167	| Bug fixed | Test original symptom: passes | Code changed, assumed fixed |
  2168	| Regression test works | Red-green cycle verified | Test passes once |
  2169	| Agent completed | VCS diff shows changes | Agent reports "success" |
  2170	| Requirements met | Line-by-line checklist | Tests passing |
  2171	
  2172	## Red Flags - STOP
  2173	
  2174	- Using "should", "probably", "seems to"
  2175	- Expressing satisfaction before verification ("Great!", "Perfect!", "Done!", etc.)
  2176	- About to commit/push/PR without verification
  2177	- Trusting agent success reports
  2178	- Relying on partial verification
  2179	- Thinking "just this once"
  2180	- Tired and wanting work over
  2181	- **ANY wording implying success without having run verification**
  2182	
  2183	## Rationalization Prevention
  2184	
  2185	| Excuse | Reality |
  2186	|--------|---------|
  2187	| "Should work now" | RUN the verification |
  2188	| "I'm confident" | Confidence ≠ evidence |
  2189	| "Just this once" | No exceptions |
  2190	| "Linter passed" | Linter ≠ compiler |
  2191	| "Agent said success" | Verify independently |
  2192	| "I'm tired" | Exhaustion ≠ excuse |
  2193	| "Partial check is enough" | Partial proves nothing |
  2194	| "Different words so rule doesn't apply" | Spirit over letter |
  2195	
  2196	## Key Patterns
  2197	
  2198	**Tests:**
  2199	```
  2200	✅ [Run test command] [See: 34/34 pass] "All tests pass"
  2201	❌ "Should pass now" / "Looks correct"
  2202	```
  2203	
  2204	**Regression tests (TDD Red-Green):**
  2205	```
  2206	✅ Write → Run (pass) → Revert fix → Run (MUST FAIL) → Restore → Run (pass)
  2207	❌ "I've written a regression test" (without red-green verification)
  2208	```
  2209	
  2210	**Build:**
  2211	```
  2212	✅ [Run build] [See: exit 0] "Build passes"
  2213	❌ "Linter passed" (linter doesn't check compilation)
  2214	```
  2215	
  2216	**Requirements:**
  2217	```
  2218	✅ Re-read plan → Create checklist → Verify each → Report gaps or completion
  2219	❌ "Tests pass, phase complete"
  2220	```
  2221	
  2222	**Agent delegation:**
  2223	```
  2224	✅ Agent reports success → Check VCS diff → Verify changes → Report actual state
  2225	❌ Trust agent report
  2226	```
  2227	
  2228	## Why This Matters
  2229	
  2230	From 24 failure memories:
  2231	- your human partner said "I don't believe you" - trust broken
  2232	- Undefined functions shipped - would crash
  2233	- Missing requirements shipped - incomplete features
  2234	- Time wasted on false completion → redirect → rework
  2235	- Violates: "Honesty is a core value. If you lie, you'll be replaced."
  2236	
  2237	## When To Apply
  2238	
  2239	**ALWAYS before:**
  2240	- ANY variation of success/completion claims
  2241	- ANY expression of satisfaction
  2242	- ANY positive statement about work state
  2243	- Committing, PR creation, task completion
  2244	- Moving to next task
  2245	- Delegating to agents
  2246	
  2247	**Rule applies to:**
  2248	- Exact phrases
  2249	- Paraphrases and synonyms
  2250	- Implications of success
  2251	- ANY communication suggesting completion/correctness
  2252	
  2253	## The Bottom Line
  2254	
  2255	**No shortcuts for verification.**
  2256	
  2257	Run the command. Read the output. THEN claim the result.
  2258	
  2259	This is non-negotiable.
  2260	
  2261	exec
  2262	/opt/homebrew/bin/bash -lc 'find artifacts/consultations/2026-04-28-pre-ultrareview -maxdepth 1 -type f -print | sort' in /Users/vladimir/Projects/cryodaq
  2263	 succeeded in 0ms:
  2264	artifacts/consultations/2026-04-28-pre-ultrareview/codex-recon-audit.prompt.md
  2265	artifacts/consultations/2026-04-28-pre-ultrareview/codex-recon-audit.response.md
  2266	artifacts/consultations/2026-04-28-pre-ultrareview/gemini-recon-audit.prompt.md
  2267	artifacts/consultations/2026-04-28-pre-ultrareview/gemini-recon-audit.response.md
  2268	

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/notifications/escalation.py | sed -n '58,82p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
    58	            Текст уведомления.
    59	        """
    60	        for level in self._chain:
    61	            chat_id = level.get("chat_id")
    62	            if not chat_id:
    63	                continue
    64	            delay_s = float(level.get("delay_minutes", 0)) * 60
    65	            key = f"{event_type}_{chat_id}"
    66	            # Отменить предыдущую задачу для этого ключа, если есть
    67	            existing = self._pending.get(key)
    68	            if existing and not existing.done():
    69	                existing.cancel()
    70	            task = asyncio.create_task(
    71	                self._delayed_send(chat_id, message, delay_s),
    72	                name=f"escalation_{key}",
    73	            )
    74	            self._pending[key] = task
    75	            logger.debug("Эскалация %s: chat_id=%s, задержка=%.0f с", event_type, chat_id, delay_s)
    76	
    77	    async def cancel(self, event_type: str) -> None:
    78	        """Отменить все pending-уведомления для данного типа события.
    79	
    80	        Параметры
    81	        ----------
    82	        event_type:

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/core/safety_manager.py | sed -n '650,732p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   650	        level = logging.CRITICAL if new_state == SafetyState.FAULT_LATCHED else logging.INFO
   651	        logger.log(level, "SAFETY: %s -> %s | %s", old_state.value, new_state.value, reason)
   652	
   653	        for callback in self._on_state_change:
   654	            try:
   655	                callback(old_state, new_state, reason)
   656	            except Exception:
   657	                logger.exception("State change callback failed")
   658	
   659	        try:
   660	            task = asyncio.get_running_loop().create_task(
   661	                self._publish_state(reason),
   662	                name=f"safety_publish_{new_state.value}",
   663	            )
   664	            self._pending_publishes.add(task)
   665	            task.add_done_callback(self._pending_publishes.discard)
   666	        except RuntimeError:
   667	            # No running loop (sync caller during tests). Publish skipped.
   668	            pass
   669	
   670	    async def _fault(self, reason: str, *, channel: str = "", value: float = 0.0) -> None:
   671	        # Early-return guard: ignore concurrent re-entries while already latched.
   672	        # Multiple call sites (SafetyBroker overflow, monitoring loop, channel
   673	        # faults, start_source failure) can fire in the same tick. Without
   674	        # this guard, a second call would overwrite _fault_reason, emit
   675	        # duplicate events + log entries, and queue a redundant emergency_off.
   676	        # The check is safe under asyncio single-threaded semantics: state is
   677	        # mutated synchronously below before any await, so a later call sees
   678	        # FAULT_LATCHED and exits.
   679	        if self._state == SafetyState.FAULT_LATCHED:
   680	            logger.info(
   681	                "_fault() re-entry ignored (already latched); new reason=%s channel=%s",
   682	                reason,
   683	                channel or "-",
   684	            )
   685	            return
   686	
   687	        # 1. Latch fault state IMMEDIATELY — no awaits before this.
   688	        #    _transition is synchronous, so request_run() will see
   689	        #    FAULT_LATCHED and reject before any yield point.
   690	        self._fault_reason = reason
   691	        self._fault_time = time.monotonic()
   692	        self._transition(SafetyState.FAULT_LATCHED, reason, channel=channel, value=value)
   693	
   694	        # 2. Now safe to do async cleanup — state already protects us.
   695	        self._active_sources.clear()
   696	
   697	        if self._keithley is not None:
   698	            # Hardware shutdown must complete even if our caller is cancelled.
   699	            # asyncio.shield prevents outer cancellation from interrupting
   700	            # emergency_off. We catch CancelledError to ensure the shielded
   701	            # task finishes before re-raising.
   702	            shutdown_task = asyncio.create_task(self._keithley.emergency_off())
   703	            try:
   704	                await asyncio.shield(shutdown_task)
   705	            except asyncio.CancelledError:
   706	                logger.critical(
   707	                    "FAULT: _fault() cancelled but emergency_off is shielded; "
   708	                    "waiting for hardware shutdown to complete"
   709	                )
   710	                try:
   711	                    await shutdown_task
   712	                except Exception as exc:
   713	                    logger.critical("FAULT: shielded emergency_off failed: %s", exc)
   714	                raise
   715	            except Exception as exc:
   716	                logger.critical("FAULT: emergency_off failed: %s", exc)
   717	
   718	        # 4. Post-mortem log emission — shielded — MUST happen after hardware
   719	        #    shutdown but BEFORE optional broker publish. Previously this came
   720	        #    after publish, creating an escape path if publish was cancelled
   721	        #    (Jules Round 2 Q1).
   722	        if self._fault_log_callback is not None:
   723	            log_task = asyncio.create_task(
   724	                self._fault_log_callback(
   725	                    source="safety_manager",
   726	                    message=f"Safety fault: {reason}",
   727	                    channel=channel,
   728	                    value=value,
   729	                )
   730	            )
   731	            try:
   732	                await asyncio.shield(log_task)

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/core/scheduler.py | sed -n '450,482p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   450	                gpib_groups[bus].append(state)
   451	            else:
   452	                standalone.append(state)
   453	
   454	        # Launch one task per GPIB bus
   455	        for bus_prefix, states in gpib_groups.items():
   456	            names = [s.config.driver.name for s in states]
   457	            logger.info(
   458	                "GPIB bus %s: последовательный опрос %d приборов %s",
   459	                bus_prefix,
   460	                len(states),
   461	                names,
   462	            )
   463	            task = asyncio.create_task(
   464	                self._gpib_poll_loop(bus_prefix, states),
   465	                name=f"gpib_poll_{bus_prefix}",
   466	            )
   467	            self._gpib_tasks[bus_prefix] = task
   468	            # Point each state's task ref to the shared task for stop()
   469	            for state in states:
   470	                state.task = task
   471	
   472	        # Launch individual tasks for non-GPIB instruments
   473	        for state in standalone:
   474	            state.task = asyncio.create_task(
   475	                self._poll_loop(state), name=f"poll_{state.config.driver.name}"
   476	            )
   477	
   478	        total = sum(len(g) for g in gpib_groups.values()) + len(standalone)
   479	        logger.info(
   480	            "Scheduler запущен (%d приборов, %d GPIB bus, %d standalone)",
   481	            total,
   482	            len(gpib_groups),

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/analytics/cooldown_service.py | sed -n '254,286p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   254	                    self._model.duration_mean,
   255	                    self._model.duration_std,
   256	                )
   257	            else:
   258	                logger.warning(
   259	                    "Файл модели не найден: %s — прогнозирование недоступно",
   260	                    model_file,
   261	                )
   262	        except Exception as exc:
   263	            logger.error("Ошибка загрузки модели охлаждения: %s", exc)
   264	
   265	        self._running = True
   266	        self._consume_task = asyncio.create_task(
   267	            self._consume_loop(),
   268	            name="cooldown_consume",
   269	        )
   270	        self._predict_task = asyncio.create_task(
   271	            self._predict_loop(),
   272	            name="cooldown_predict",
   273	        )
   274	        logger.info("CooldownService запущен")
   275	
   276	    async def stop(self) -> None:
   277	        """Остановить сервис: отмена задач, отписка от брокера."""
   278	        if not self._running:
   279	            return
   280	        self._running = False
   281	
   282	        for task in (self._consume_task, self._predict_task):
   283	            if task is not None:
   284	                task.cancel()
   285	                try:
   286	                    await task

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/notifications/escalation.py | sed -n '77,125p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
    77	    async def cancel(self, event_type: str) -> None:
    78	        """Отменить все pending-уведомления для данного типа события.
    79	
    80	        Параметры
    81	        ----------
    82	        event_type:
    83	            Тип события для отмены (должен совпадать с переданным в :meth:`escalate`).
    84	        """
    85	        prefix = f"{event_type}_"
    86	        to_cancel = [key for key in list(self._pending) if key.startswith(prefix)]
    87	        for key in to_cancel:
    88	            task = self._pending.pop(key)
    89	            if not task.done():
    90	                task.cancel()
    91	                try:
    92	                    await task
    93	                except asyncio.CancelledError:
    94	                    pass
    95	        if to_cancel:
    96	            logger.info("Эскалация %s отменена (%d задач)", event_type, len(to_cancel))
    97	
    98	    async def _delayed_send(self, chat_id: int, message: str, delay_s: float) -> None:
    99	        try:
   100	            if delay_s > 0:
   101	                await asyncio.sleep(delay_s)
   102	            await self._notifier.send_message(chat_id, message)
   103	            logger.info("Эскалация отправлена: chat_id=%s", chat_id)
   104	        except asyncio.CancelledError:
   105	            logger.debug("Эскалация отменена до отправки: chat_id=%s", chat_id)
   106	            raise
   107	        except Exception as exc:
   108	            logger.error("Ошибка отправки эскалации на chat_id=%s: %s", chat_id, exc)

codex
The requested response file currently contains a captured session transcript, not the audit answer. I’m replacing it with the concise three-section report.
2026-04-27T23:19:25.375208Z ERROR codex_core::tools::router: error=patch rejected: writing is blocked by read-only sandbox; rejected by user approval settings
codex
Write failed: `apply_patch` was rejected by the read-only sandbox, so `artifacts/consultations/2026-04-28-pre-ultrareview/codex-recon-audit.response.md` was not replaced.

**CC recon verification**

- A1 PASS — `docs/ORCHESTRATION.md:629` has `## 14. Verification practices`; `docs/ORCHESTRATION.md:731` has `### 14.5`. v1.2 also appears at `docs/ORCHESTRATION.md:3`.
- A2 PASS — tags are exactly `v0.33.0` through `v0.39.0`.
- A3 PASS — only README `.330` hit is `README.md:84`: `.330` removed.
- A4 PASS — root `.md` files match ORCHESTRATION whitelist at `docs/ORCHESTRATION.md:262-273`.
- A5 PASS WITH CAVEAT — literal `.330` hits are only `tests/analytics/test_calibration.py:279` and `tests/analytics/test_calibration.py:367`, both intentional removal/rejection tests. Caveat: CC cited `tests/gui/shell/overlays/test_calibration_panel.py:360`, but that is `curve_330_path`, not a literal `.330` grep hit.

Additional gap: CC’s repo-state inventory is stale. Current HEAD is `95240ae`, not `c1e5a20`; current status shows only `?? artifacts/consultations/2026-04-28-pre-ultrareview/`; current local branches are `master`, `codex/safe-merge-b1-truth-recovery`, and worktree branch `experiment/iv7-ipc-transport`.

**Missed by CC**

- HIGH — B4 engine import fails. `import cryodaq.engine` exits 1 because `src/cryodaq/engine.py:71` eagerly imports reporting/Matplotlib, which needs writable cache/temp dirs.
- HIGH — B1 pytest suite not verified. The requested pytest command exits before collection because pytest cannot create a temp capture file in this read-only environment.
- LOW — B2 calibration import passes: prints `OK`.
- LOW — B3 GUI overlay import passes with offscreen Qt: prints `OK`.
- LOW — B5 TODO/FIXME `.330` search is clean: no matches.
- MEDIUM — CHANGELOG drift missed: `CHANGELOG.md:1457-1459` still advertises `.330` / `.340` / JSON export and no `.cof` migration entry was found.

**Likely /ultrareview findings**

1. HIGH — `cryodaq.engine` import-time Matplotlib dependency can fail before startup. Evidence: `src/cryodaq/engine.py:71`; requested import command failed.
2. HIGH — targeted calibration/gui/core tests are not proven green in this environment because pytest cannot create temp files.
3. MEDIUM — CHANGELOG stale/missing `.cof` migration entry; `CHANGELOG.md:1457-1459` conflicts with `README.md:84`.
4. MEDIUM — `.cof` export type hints are present, but malformed empty-zone curves are not rejected before writing `# zone_count: 0` at `src/cryodaq/analytics/calibration.py:889-902`.
5. LOW — async/resource greps are noisy; engine tasks are cancelled at `src/cryodaq/engine.py:1664-1712`, web tasks at `src/cryodaq/web/server.py:316-324`, and conductivity flight log is closed at `src/cryodaq/gui/shell/overlays/conductivity_panel.py:1405-1408`.

Final verdict: REPO NOT READY.
tokens used
102 130
Write failed: `apply_patch` was rejected by the read-only sandbox, so `artifacts/consultations/2026-04-28-pre-ultrareview/codex-recon-audit.response.md` was not replaced.

**CC recon verification**

- A1 PASS — `docs/ORCHESTRATION.md:629` has `## 14. Verification practices`; `docs/ORCHESTRATION.md:731` has `### 14.5`. v1.2 also appears at `docs/ORCHESTRATION.md:3`.
- A2 PASS — tags are exactly `v0.33.0` through `v0.39.0`.
- A3 PASS — only README `.330` hit is `README.md:84`: `.330` removed.
- A4 PASS — root `.md` files match ORCHESTRATION whitelist at `docs/ORCHESTRATION.md:262-273`.
- A5 PASS WITH CAVEAT — literal `.330` hits are only `tests/analytics/test_calibration.py:279` and `tests/analytics/test_calibration.py:367`, both intentional removal/rejection tests. Caveat: CC cited `tests/gui/shell/overlays/test_calibration_panel.py:360`, but that is `curve_330_path`, not a literal `.330` grep hit.

Additional gap: CC’s repo-state inventory is stale. Current HEAD is `95240ae`, not `c1e5a20`; current status shows only `?? artifacts/consultations/2026-04-28-pre-ultrareview/`; current local branches are `master`, `codex/safe-merge-b1-truth-recovery`, and worktree branch `experiment/iv7-ipc-transport`.

**Missed by CC**

- HIGH — B4 engine import fails. `import cryodaq.engine` exits 1 because `src/cryodaq/engine.py:71` eagerly imports reporting/Matplotlib, which needs writable cache/temp dirs.
- HIGH — B1 pytest suite not verified. The requested pytest command exits before collection because pytest cannot create a temp capture file in this read-only environment.
- LOW — B2 calibration import passes: prints `OK`.
- LOW — B3 GUI overlay import passes with offscreen Qt: prints `OK`.
- LOW — B5 TODO/FIXME `.330` search is clean: no matches.
- MEDIUM — CHANGELOG drift missed: `CHANGELOG.md:1457-1459` still advertises `.330` / `.340` / JSON export and no `.cof` migration entry was found.

**Likely /ultrareview findings**

1. HIGH — `cryodaq.engine` import-time Matplotlib dependency can fail before startup. Evidence: `src/cryodaq/engine.py:71`; requested import command failed.
2. HIGH — targeted calibration/gui/core tests are not proven green in this environment because pytest cannot create temp files.
3. MEDIUM — CHANGELOG stale/missing `.cof` migration entry; `CHANGELOG.md:1457-1459` conflicts with `README.md:84`.
4. MEDIUM — `.cof` export type hints are present, but malformed empty-zone curves are not rejected before writing `# zone_count: 0` at `src/cryodaq/analytics/calibration.py:889-902`.
5. LOW — async/resource greps are noisy; engine tasks are cancelled at `src/cryodaq/engine.py:1664-1712`, web tasks at `src/cryodaq/web/server.py:316-324`, and conductivity flight log is closed at `src/cryodaq/gui/shell/overlays/conductivity_panel.py:1405-1408`.

Final verdict: REPO NOT READY.
