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
session id: 019dce0f-e837-7f13-b572-63d0e663d340
--------
user
Model: gpt-5.5
Reasoning effort: high

# Full-vault audit — Codex literal verifier (post-build)

## Mission
Read every markdown note under ~/Vault/CryoDAQ/ except `_meta/`. For each
factual claim that has a `source:` reference in the note's frontmatter,
cross-reference the claim against the actual repo file. Flag what's
factually wrong.

This is post-build verification. The vault was built overnight 2026-04-26
and passed self-driven audit gates during build. This pass is independent
adversarial review on the full integrated artifact.

## Scope of vault to audit
- ~/Vault/CryoDAQ/00 Overview/*.md (4 notes — What is CryoDAQ, Hardware setup, Architecture overview, UI and design system)
- ~/Vault/CryoDAQ/10 Subsystems/*.md (6 notes — Web/Cooldown/Experiment/Interlock deferred, not present)
- ~/Vault/CryoDAQ/20 Drivers/*.md (3 notes)
- ~/Vault/CryoDAQ/30 Investigations/*.md (6 notes)
- ~/Vault/CryoDAQ/40 Decisions/*.md (7 notes — 4 mirrored ADRs + 3 synthesized ADR-001..003)
- ~/Vault/CryoDAQ/50 Workflow/*.md (4 notes)
- ~/Vault/CryoDAQ/60 Roadmap/*.md (2 notes — Versions, F-table backlog)
- ~/Vault/CryoDAQ/README.md
- skip 90 Archive/ (intentionally empty)
- skip _meta/ (build log + glossary + source map are CC-internal)

## Source files in repo for cross-reference
- ~/Projects/cryodaq/CLAUDE.md
- ~/Projects/cryodaq/PROJECT_STATUS.md
- ~/Projects/cryodaq/ROADMAP.md
- ~/Projects/cryodaq/CHANGELOG.md
- ~/Projects/cryodaq/docs/decisions/*.md
- ~/Projects/cryodaq/docs/ORCHESTRATION.md
- ~/Projects/cryodaq/.claude/skills/*.md
- ~/Projects/cryodaq/src/cryodaq/core/safety_manager.py
- ~/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py
- ~/Projects/cryodaq/src/cryodaq/core/zmq_subprocess.py
- ~/Projects/cryodaq/src/cryodaq/analytics/calibration.py
- ~/Projects/cryodaq/src/cryodaq/analytics/calibration_fitter.py
- ~/Projects/cryodaq/src/cryodaq/analytics/base_plugin.py
- ~/Projects/cryodaq/src/cryodaq/analytics/plugin_loader.py
- ~/Projects/cryodaq/src/cryodaq/core/alarm_v2.py
- ~/Projects/cryodaq/src/cryodaq/core/alarm_config.py
- ~/Projects/cryodaq/config/instruments.yaml
- ~/Projects/cryodaq/config/alarms_v3.yaml
- ~/Projects/cryodaq/config/safety.yaml
- ~/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py
- ~/Projects/cryodaq/src/cryodaq/drivers/instruments/keithley_2604b.py
- ~/Projects/cryodaq/src/cryodaq/drivers/instruments/thyracont_vsp63d.py
- (read additional files as cited by individual notes' source: headers)

## Severity scale (use exactly these labels)
- CRITICAL: claim contradicts source code or repo doc
  (homoglyph-class — actively wrong)
- HIGH: claim is overstatement vs source
  (technically partial-true but reader will draw wrong conclusion)
- MEDIUM: claim is true but missing important caveat
- LOW: minor wording / clarity / style
- DEFERRED-COVERAGE: source declares something exists that vault has
  zero mention of (only when totally absent — for partial coverage use HIGH)

## What NOT to flag
- Stylistic preferences (prose density, paragraph length, voice)
- Information density: vault is digest by design, not exhaustive mirror
- Structural choices (folder layout, ADR template choice — CC's domain)
- "I would have written it differently" — only flag what's WRONG
- Coverage gaps already deferred per
  ~/Projects/cryodaq/artifacts/handoffs/2026-04-27-vault-build-handoff.md
  §"Deferred coverage gaps" (4 specific notes — Web/Cooldown/Experiment/Interlock)

## Output format

```
## Finding NN
**Severity:** CRITICAL | HIGH | MEDIUM | LOW | DEFERRED-COVERAGE
**Vault file:** path/to/note.md
**Vault line(s):** line numbers (or section heading)
**Source file:** ~/Projects/cryodaq/path/to/source
**Source line(s):** line numbers
**Claim in vault:** "exact quote from vault"
**What source says:** "exact quote from source OR plain statement of source state"
**Why this is wrong:** 1-2 sentences
**Suggested fix:** specific text replacement OR "remove sentence" OR "add caveat: ..."
```

After all findings:

```
## Verdict
- Total findings: N
- By severity: CRITICAL=A HIGH=B MEDIUM=C LOW=D DEFERRED=E
- PASS / FAIL / CONDITIONAL with one-sentence reason

## Confidence notes
- Areas where you weren't sure / source was ambiguous / 30-second-rule cases
```

Hard cap: **5000 words total**. Prefer specificity over volume —
better 10 well-cited findings than 30 noise.

## Response file
~/Projects/cryodaq/artifacts/consultations/2026-04-27-vault-audit/codex-full-vault.response.md

If your sandbox is read-only, do NOT attempt to write the response file
yourself. Emit the full response to stdout — the wrapper redirect captures it.

codex
I’ll use the `superpowers:using-superpowers` instruction first because it is required at conversation start, then I’ll audit the vault against cited repo sources and return the response content directly since the sandbox is read-only.
exec
/opt/homebrew/bin/bash -lc "sed -n '1,220p' /Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/b066e4a04761672ce316491d2d62b10ad27a6b15/skills/using-superpowers/SKILL.md" in /Users/vladimir/Projects/cryodaq
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
I’m gathering the exact note set and their frontmatter sources first. The main risk in this audit is false positives from paraphrase, so I’m going to anchor every finding to line numbers on both sides.
exec
/opt/homebrew/bin/bash -lc "find /Users/vladimir/Vault/CryoDAQ -path '/Users/vladimir/Vault/CryoDAQ/_meta' -prune -o -path '/Users/vladimir/Vault/CryoDAQ/90 Archive' -prune -o -name '*.md' -print | sort" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
/Users/vladimir/Vault/CryoDAQ/00 Overview/Architecture overview.md
/Users/vladimir/Vault/CryoDAQ/00 Overview/Hardware setup.md
/Users/vladimir/Vault/CryoDAQ/00 Overview/UI and design system.md
/Users/vladimir/Vault/CryoDAQ/00 Overview/What is CryoDAQ.md
/Users/vladimir/Vault/CryoDAQ/00 Overview/_index.md
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/Alarm engine v2.md
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/Calibration v2.md
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/Persistence-first.md
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/Plugin architecture.md
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/Safety FSM.md
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/ZMQ bridge.md
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/_index.md
/Users/vladimir/Vault/CryoDAQ/20 Drivers/Keithley 2604B.md
/Users/vladimir/Vault/CryoDAQ/20 Drivers/LakeShore 218S.md
/Users/vladimir/Vault/CryoDAQ/20 Drivers/Thyracont VSP63D.md
/Users/vladimir/Vault/CryoDAQ/20 Drivers/_index.md
/Users/vladimir/Vault/CryoDAQ/30 Investigations/B1 ZMQ idle-death.md
/Users/vladimir/Vault/CryoDAQ/30 Investigations/Codex H2 wrong hypothesis.md
/Users/vladimir/Vault/CryoDAQ/30 Investigations/Cyrillic homoglyph in alarm config.md
/Users/vladimir/Vault/CryoDAQ/30 Investigations/IV.6 cmd plane hardening.md
/Users/vladimir/Vault/CryoDAQ/30 Investigations/Plugin isolation rebuild.md
/Users/vladimir/Vault/CryoDAQ/30 Investigations/_index.md
/Users/vladimir/Vault/CryoDAQ/30 Investigations/b2b4fb5 hardening race.md
/Users/vladimir/Vault/CryoDAQ/40 Decisions/2026-04-23-cleanup-baseline.md
/Users/vladimir/Vault/CryoDAQ/40 Decisions/2026-04-24-b2b4fb5-investigation.md
/Users/vladimir/Vault/CryoDAQ/40 Decisions/2026-04-24-d1-d4a-execution.md
/Users/vladimir/Vault/CryoDAQ/40 Decisions/2026-04-24-overnight-swarm-launch.md
/Users/vladimir/Vault/CryoDAQ/40 Decisions/ADR-001 Persistence-first invariant.md
/Users/vladimir/Vault/CryoDAQ/40 Decisions/ADR-002 R1 bounded-backoff probe retry.md
/Users/vladimir/Vault/CryoDAQ/40 Decisions/ADR-003 Plugin isolation via ABC.md
/Users/vladimir/Vault/CryoDAQ/40 Decisions/_index.md
/Users/vladimir/Vault/CryoDAQ/50 Workflow/Calibration loops history.md
/Users/vladimir/Vault/CryoDAQ/50 Workflow/Multi-model consultation.md
/Users/vladimir/Vault/CryoDAQ/50 Workflow/ORCHESTRATION contract.md
/Users/vladimir/Vault/CryoDAQ/50 Workflow/Overnight swarm pattern.md
/Users/vladimir/Vault/CryoDAQ/50 Workflow/_index.md
/Users/vladimir/Vault/CryoDAQ/60 Roadmap/F-table backlog.md
/Users/vladimir/Vault/CryoDAQ/60 Roadmap/Versions.md
/Users/vladimir/Vault/CryoDAQ/60 Roadmap/_index.md
/Users/vladimir/Vault/CryoDAQ/README.md

exec
/opt/homebrew/bin/bash -lc "find /Users/vladimir/Projects/cryodaq -maxdepth 3 -type f \\( -path '*/docs/decisions/*.md' -o -path '*/artifacts/handoffs/2026-04-27-vault-build-handoff.md' -o -name 'CLAUDE.md' -o -name 'PROJECT_STATUS.md' -o -name 'ROADMAP.md' -o -name 'CHANGELOG.md' -o -path '*/docs/ORCHESTRATION.md' \\) -print | sort" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
/Users/vladimir/Projects/cryodaq/.worktrees/experiment-iv7-ipc-transport/CHANGELOG.md
/Users/vladimir/Projects/cryodaq/.worktrees/experiment-iv7-ipc-transport/CLAUDE.md
/Users/vladimir/Projects/cryodaq/.worktrees/experiment-iv7-ipc-transport/PROJECT_STATUS.md
/Users/vladimir/Projects/cryodaq/.worktrees/experiment-iv7-ipc-transport/ROADMAP.md
/Users/vladimir/Projects/cryodaq/CHANGELOG.md
/Users/vladimir/Projects/cryodaq/CLAUDE.md
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md
/Users/vladimir/Projects/cryodaq/ROADMAP.md
/Users/vladimir/Projects/cryodaq/artifacts/handoffs/2026-04-27-vault-build-handoff.md
/Users/vladimir/Projects/cryodaq/docs/ORCHESTRATION.md
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-23-cleanup-baseline.md
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-d1-d4a-execution.md
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-overnight-swarm-launch.md
/Users/vladimir/Projects/cryodaq/docs/design-system/CHANGELOG.md

exec
/opt/homebrew/bin/bash -lc 'for f in $(find /Users/vladimir/Vault/CryoDAQ -path '"'/Users/vladimir/Vault/CryoDAQ/_meta' -prune -o -path '/Users/vladimir/Vault/CryoDAQ/90 Archive' -prune -o -name '*.md' -print | sort); do echo \"FILE:"'$f"; sed -n '"'1,40p' \""'$f" | sed -n '"'/"'^---$/,/''^---$/p'"' | rg -n \""'^(source|sources|repo|title|created|updated|tags):|''^- " || true; done' in /Users/vladimir/Projects/cryodaq
 succeeded in 380ms:
sed: Subsystems/Safety: No such file or directory
FILE:FSM.md
sed: FSM.md: No such file or directory
FILE:/Users/vladimir/Vault/CryoDAQ/10
sed: /Users/vladimir/Vault/CryoDAQ/10: No such file or directory
FILE:Subsystems/ZMQ
sed: Subsystems/ZMQ: No such file or directory
FILE:bridge.md
sed: bridge.md: No such file or directory
FILE:/Users/vladimir/Vault/CryoDAQ/10
sed: /Users/vladimir/Vault/CryoDAQ/10: No such file or directory
FILE:Subsystems/_index.md
sed: Subsystems/_index.md: No such file or directory
FILE:/Users/vladimir/Vault/CryoDAQ/20
sed: /Users/vladimir/Vault/CryoDAQ/20: No such file or directory
FILE:Drivers/Keithley
sed: Drivers/Keithley: No such file or directory
FILE:2604B.md
sed: 2604B.md: No such file or directory
FILE:/Users/vladimir/Vault/CryoDAQ/20
sed: /Users/vladimir/Vault/CryoDAQ/20: No such file or directory
FILE:Drivers/LakeShore
sed: Drivers/LakeShore: No such file or directory
FILE:218S.md
sed: 218S.md: No such file or directory
FILE:/Users/vladimir/Vault/CryoDAQ/20
sed: /Users/vladimir/Vault/CryoDAQ/20: No such file or directory
FILE:Drivers/Thyracont
sed: Drivers/Thyracont: No such file or directory
FILE:VSP63D.md
sed: VSP63D.md: No such file or directory
FILE:/Users/vladimir/Vault/CryoDAQ/20
sed: /Users/vladimir/Vault/CryoDAQ/20: No such file or directory
FILE:Drivers/_index.md
sed: Drivers/_index.md: No such file or directory
FILE:/Users/vladimir/Vault/CryoDAQ/30
sed: /Users/vladimir/Vault/CryoDAQ/30: No such file or directory
FILE:Investigations/B1
sed: Investigations/B1: No such file or directory
FILE:ZMQ
sed: ZMQ: No such file or directory
FILE:idle-death.md
sed: idle-death.md: No such file or directory
FILE:/Users/vladimir/Vault/CryoDAQ/30
sed: /Users/vladimir/Vault/CryoDAQ/30: No such file or directory
FILE:Investigations/Codex
sed: Investigations/Codex: No such file or directory
FILE:H2
sed: H2: No such file or directory
FILE:wrong
sed: wrong: No such file or directory
FILE:hypothesis.md
sed: hypothesis.md: No such file or directory
FILE:/Users/vladimir/Vault/CryoDAQ/30
sed: /Users/vladimir/Vault/CryoDAQ/30: No such file or directory
FILE:Investigations/Cyrillic
sed: Investigations/Cyrillic: No such file or directory
FILE:homoglyph
sed: homoglyph: No such file or directory
FILE:in
sed: in: No such file or directory
FILE:alarm
sed: alarm: No such file or directory
FILE:config.md
sed: config.md: No such file or directory
FILE:/Users/vladimir/Vault/CryoDAQ/30
sed: /Users/vladimir/Vault/CryoDAQ/30: No such file or directory
FILE:Investigations/IV.6
sed: Investigations/IV.6: No such file or directory
FILE:cmd
sed: cmd: No such file or directory
FILE:plane
sed: plane: No such file or directory
FILE:hardening.md
sed: hardening.md: No such file or directory
FILE:/Users/vladimir/Vault/CryoDAQ/30
sed: /Users/vladimir/Vault/CryoDAQ/30: No such file or directory
FILE:Investigations/Plugin
sed: Investigations/Plugin: No such file or directory
FILE:isolation
sed: isolation: No such file or directory
FILE:rebuild.md
sed: rebuild.md: No such file or directory
FILE:/Users/vladimir/Vault/CryoDAQ/30
sed: /Users/vladimir/Vault/CryoDAQ/30: No such file or directory
FILE:Investigations/_index.md
sed: Investigations/_index.md: No such file or directory
FILE:/Users/vladimir/Vault/CryoDAQ/30
sed: /Users/vladimir/Vault/CryoDAQ/30: No such file or directory
FILE:Investigations/b2b4fb5
sed: Investigations/b2b4fb5: No such file or directory
FILE:hardening
sed: hardening: No such file or directory
FILE:race.md
sed: race.md: No such file or directory
FILE:/Users/vladimir/Vault/CryoDAQ/40
sed: /Users/vladimir/Vault/CryoDAQ/40: No such file or directory
FILE:Decisions/2026-04-23-cleanup-baseline.md
sed: Decisions/2026-04-23-cleanup-baseline.md: No such file or directory
FILE:/Users/vladimir/Vault/CryoDAQ/40
sed: /Users/vladimir/Vault/CryoDAQ/40: No such file or directory
FILE:Decisions/2026-04-24-b2b4fb5-investigation.md
sed: Decisions/2026-04-24-b2b4fb5-investigation.md: No such file or directory
FILE:/Users/vladimir/Vault/CryoDAQ/40
sed: /Users/vladimir/Vault/CryoDAQ/40: No such file or directory
FILE:Decisions/2026-04-24-d1-d4a-execution.md
sed: Decisions/2026-04-24-d1-d4a-execution.md: No such file or directory
FILE:/Users/vladimir/Vault/CryoDAQ/40
sed: /Users/vladimir/Vault/CryoDAQ/40: No such file or directory
FILE:Decisions/2026-04-24-overnight-swarm-launch.md
sed: Decisions/2026-04-24-overnight-swarm-launch.md: No such file or directory
FILE:/Users/vladimir/Vault/CryoDAQ/40
sed: /Users/vladimir/Vault/CryoDAQ/40: No such file or directory
FILE:Decisions/ADR-001
sed: Decisions/ADR-001: No such file or directory
FILE:Persistence-first
sed: Persistence-first: No such file or directory
FILE:invariant.md
sed: invariant.md: No such file or directory
FILE:/Users/vladimir/Vault/CryoDAQ/40
sed: /Users/vladimir/Vault/CryoDAQ/40: No such file or directory
FILE:Decisions/ADR-002
sed: Decisions/ADR-002: No such file or directory
FILE:R1
sed: R1: No such file or directory
FILE:bounded-backoff
sed: bounded-backoff: No such file or directory
FILE:probe
sed: probe: No such file or directory
FILE:retry.md
sed: retry.md: No such file or directory
FILE:/Users/vladimir/Vault/CryoDAQ/40
sed: /Users/vladimir/Vault/CryoDAQ/40: No such file or directory
FILE:Decisions/ADR-003
sed: Decisions/ADR-003: No such file or directory
FILE:Plugin
sed: Plugin: No such file or directory
FILE:isolation
sed: isolation: No such file or directory
FILE:via
sed: via: No such file or directory
FILE:ABC.md
sed: ABC.md: No such file or directory
FILE:/Users/vladimir/Vault/CryoDAQ/40
sed: /Users/vladimir/Vault/CryoDAQ/40: No such file or directory
FILE:Decisions/_index.md
sed: Decisions/_index.md: No such file or directory
FILE:/Users/vladimir/Vault/CryoDAQ/50
sed: /Users/vladimir/Vault/CryoDAQ/50: No such file or directory
FILE:Workflow/Calibration
sed: Workflow/Calibration: No such file or directory
FILE:loops
sed: loops: No such file or directory
FILE:history.md
sed: history.md: No such file or directory
FILE:/Users/vladimir/Vault/CryoDAQ/50
sed: /Users/vladimir/Vault/CryoDAQ/50: No such file or directory
FILE:Workflow/Multi-model
sed: Workflow/Multi-model: No such file or directory
FILE:consultation.md
sed: consultation.md: No such file or directory
FILE:/Users/vladimir/Vault/CryoDAQ/50
sed: /Users/vladimir/Vault/CryoDAQ/50: No such file or directory
FILE:Workflow/ORCHESTRATION
sed: Workflow/ORCHESTRATION: No such file or directory
FILE:contract.md
sed: contract.md: No such file or directory
FILE:/Users/vladimir/Vault/CryoDAQ/50
sed: /Users/vladimir/Vault/CryoDAQ/50: No such file or directory
FILE:Workflow/Overnight
sed: Workflow/Overnight: No such file or directory
FILE:swarm
sed: swarm: No such file or directory
FILE:pattern.md
sed: pattern.md: No such file or directory
FILE:/Users/vladimir/Vault/CryoDAQ/50
sed: /Users/vladimir/Vault/CryoDAQ/50: No such file or directory
FILE:Workflow/_index.md
sed: Workflow/_index.md: No such file or directory
FILE:/Users/vladimir/Vault/CryoDAQ/60
sed: /Users/vladimir/Vault/CryoDAQ/60: No such file or directory
FILE:Roadmap/F-table
sed: Roadmap/F-table: No such file or directory
FILE:backlog.md
sed: backlog.md: No such file or directory
FILE:/Users/vladimir/Vault/CryoDAQ/60
sed: /Users/vladimir/Vault/CryoDAQ/60: No such file or directory
FILE:Roadmap/Versions.md
sed: Roadmap/Versions.md: No such file or directory
FILE:/Users/vladimir/Vault/CryoDAQ/60
sed: /Users/vladimir/Vault/CryoDAQ/60: No such file or directory
FILE:Roadmap/_index.md
sed: Roadmap/_index.md: No such file or directory
FILE:/Users/vladimir/Vault/CryoDAQ/README.md

exec
/opt/homebrew/bin/bash -lc "find /Users/vladimir/Vault/CryoDAQ -path '/Users/vladimir/Vault/CryoDAQ/_meta' -prune -o -path '/Users/vladimir/Vault/CryoDAQ/90 Archive' -prune -o -name '*.md' -print0 | sort -z | while IFS= read -r -d '' f; do printf '\\nFILE:%s\\n' \""'$f"; awk '"'NR==1 && "'$0=="---"{infm=1; print; next} infm{print; if($0=="---") exit}'"' \""'$f" | rg -n "''^(source|sources|repo|title|created|updated|tags):|''^- " || true; done' in /Users/vladimir/Projects/cryodaq
 succeeded in 108ms:
2:source: git tag -l; git log; CHANGELOG.md (Unreleased + recent); PROJECT_STATUS.md; ROADMAP.md

FILE:/Users/vladimir/Vault/CryoDAQ/60 Roadmap/_index.md
2:source: skeleton stub

FILE:/Users/vladimir/Vault/CryoDAQ/README.md

exec
/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Projects/cryodaq/artifacts/handoffs/2026-04-27-vault-build-handoff.md | sed -n '1,220p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	# Vault build overnight 2026-04-26 → 27 — handoff
     2	
     3	**Built by:** Claude Code (Opus 4.7, 1M context) under
     4	`CC_PROMPT_VAULT_BUILD_2026-04-26.md`.
     5	**Build window:** 2026-04-27 00:47 MSK → 2026-04-27 01:33 MSK
     6	(~46 min wall-clock active vs 8 h budget; integration loop quiesced
     7	after iter 1).
     8	**Hard cap:** 06:00 MSK. Plenty of margin remained at quiescence.
     9	
    10	## Outcome
    11	
    12	**Quiescent after 1 integration-loop iteration.** Per spec §7
    13	quiescence criteria: 0 CRITICAL, 0 HIGH, 0 DRIFT findings; ≤10
    14	MEDIUM, ≤5 GAPS; coverage gaps deferred to architect. Build
    15	exited cleanly, well inside the wall-clock cap.
    16	
    17	## Vault state at handoff
    18	
    19	- **49 markdown notes** under `~/Vault/CryoDAQ/`
    20	- **303 wikilinks**, **0 broken** (verified at handoff time)
    21	- 9 indexed folders (`00 Overview`, `10 Subsystems`, `20 Drivers`,
    22	  `30 Investigations`, `40 Decisions`, `50 Workflow`, `60 Roadmap`,
    23	  `90 Archive`, `_meta`)
    24	- 4 ADRs mirrored from `docs/decisions/*.md` + 3 synthesized ADRs
    25	  (ADR-001 Persistence-first, ADR-002 R1 bounded-backoff,
    26	  ADR-003 Plugin isolation)
    27	- 3 templates under `_meta/templates/` (ADR / Investigation / Subsystem)
    28	- Source map at `_meta/source map.md` regenerated by the
    29	  re-runnable Python script at
    30	  `artifacts/vault-build/build_source_map.py`
    31	
    32	## Audit cycles
    33	
    34	| Phase | Codex verdict | Gemini verdict | Findings | Fixed | Disputed |
    35	|---|---|---|---|---|---|
    36	| Phase 2 (reference seed) | CONDITIONAL | GAPS / DRIFT | 5 + 8 = 13 | 7 | 1 (CC overruled re: II.13 vs I.1 retirement) |
    37	| Phase 3 (synthesis, 22 pages) | **FAIL** | GAPS / DRIFT | 17 + 6 = 23 | 17 | 0 material |
    38	| Integration iter 1 (full vault) | **FAIL** | DRIFT / GAPS | 8 + 5 = 13 | 9 | 1 (CC overruled re: Т4 alarm-group inclusion) |
    39	| Phase 4 audit gate | SKIPPED | — | — | — | — (collapsed into integration loop per §13.3) |
    40	
    41	**Convergent findings** (both verifiers flagged same issue from
    42	different angles — high-confidence) caught:
    43	- Phase 2: test-file count drift (171 → 194); UI legacy-widget
    44	  retirement misstatement
    45	- Phase 3: plugin SQLite consumer overclaim; Т4 alarm-group state;
    46	  IV.6 / B1 engine-REP wording
    47	
    48	**Codex sandbox quirk** (per `multi-model-consultation` skill §6):
    49	Codex CLI v0.124.0 rejected the older `--sandbox workspace-read`
    50	value; switched to `read-only` + `--skip-git-repo-check --cd`
    51	for Phase 0 onward. Codex tried to write the response file
    52	itself; sandbox blocked → emitted canonical content via stdout
    53	which the wrapper redirect captured. Documented as the proven path.
    54	
    55	**Gemini quirk:** integration audit's structural finding on
    56	Т4 alarm-group state contradicted Gemini's own Phase 3 finding
    57	on the same question. Repo state (alarms_v3.yaml line 32-35)
    58	agrees with the Phase 3 reading (Т4 EXCLUDED). CC overruled the
    59	later integration finding.
    60	
    61	## Polish applied (Phase 8)
    62	
    63	- **Theme.** No global theme override applied — would touch user's
    64	  other vault content under `Soban Soundbar`, `Tags`, `projects`.
    65	  Default theme retained. User can change via UI in 5 s if desired.
    66	- **Core plugins.** Already enabled per shipped
    67	  `.obsidian/core-plugins.json` — file-explorer, global-search,
    68	  graph, backlink, outgoing-link, tag-pane, page-preview, templates,
    69	  command-palette, bookmarks, outline, word-count, file-recovery,
    70	  sync. No changes needed.
    71	- **Graph view.** 9 colorGroups added to `.obsidian/graph.json`
    72	  matching CryoDAQ folder prefixes (00 / 10 / 20 / 30 / 40 / 50 /
    73	  60 / 90 / _meta). Colors are folder-distinct, not flashy. Original
    74	  state was empty `colorGroups: []`; revert is one diff away.
    75	- **Templates folder.** `_meta/templates/` contains ADR,
    76	  Investigation, and Subsystem templates linked from the `_meta`
    77	  index. Future-Vladimir picks via Obsidian template-insert.
    78	
    79	No third-party themes / community plugins installed (per spec §11).
    80	
    81	## Deferred coverage gaps
    82	
    83	These were flagged by Gemini's wide-context audits across multiple
    84	rounds, accepted as real but **not synthesized** in this build —
    85	they need architect judgment on scope and tone before being written:
    86	
    87	1. `10 Subsystems/Web dashboard.md` — covers `web/server.py`
    88	   FastAPI monitoring surface. Would document loopback-only default,
    89	   `/status` / `/history` / `/api/status` / `/ws` endpoints, auth
    90	   deferral (G.1 in PROJECT_STATUS) and the F7 extension plan.
    91	2. `10 Subsystems/Cooldown predictor.md` — covers
    92	   `analytics/cooldown_predictor.py` + `analytics/cooldown_service.py`.
    93	   Would cover progress-variable ensemble, async orchestration with
    94	   experiment lifecycle, and the F8 ML-upgrade plan.
    95	3. `10 Subsystems/Experiment manager.md` — covers `core/experiment.py`
    96	   (~70 KB), the experiment lifecycle (templates, phases, metadata,
    97	   finalize), report generation hook, calibration acquisition
    98	   activation.
    99	4. `10 Subsystems/Interlock engine.md` — covers `core/interlock.py`
   100	   + `config/interlocks.yaml`, `on_interlock_trip()` action mapping
   101	   (`emergency_off` vs `stop_source`), relationship to alarm
   102	   engine v2 and Safety FSM.
   103	
   104	Templates exist if architect wants CC to draft any of these.
   105	
   106	## Disputes (CC overruled, ledgered)
   107	
   108	| Round | Finding | Source said | CC ruling |
   109	|---|---|---|---|
   110	| Phase 2 (Gemini) | "MainWindow retired in Phase I.1, not II.13" | `CLAUDE.md`: "main_window_v2.py — sole owner of shortcut bindings after the v1 `gui/main_window.py` was retired in Phase II.13" | Kept II.13 phrasing; matches source |
   111	| Phase 2 (Gemini) | "Retroactive tagging v0.34.0..v0.38.0 chronologically broken" | `docs/decisions/2026-04-23-cleanup-baseline.md` uses this exact wording | Kept source phrasing; added clarifier |
   112	| Integration (Gemini) | "Т4 ADDED to alarm groups per CHANGELOG" | `config/alarms_v3.yaml:32-35` excludes Т4 from `uncalibrated` and `all_temp` | Repo state authoritative; Gemini's own Phase 3 audit agreed |
   113	
   114	## What worked
   115	
   116	- **Codex parallel + Gemini parallel** dispatch (no rate-limit
   117	  collisions during this 4-job-pair run, unlike 2026-04-24 swarm
   118	  where 5-Gemini-parallel failed).
   119	- **Audit gates dispatched in background** while CC continued the
   120	  next phase's authoring → wall-clock parallelism between LLM-side
   121	  reasoning and CC-side authoring.
   122	- **Re-runnable source map** (`artifacts/vault-build/build_source_map.py`)
   123	  caught broken-link regressions instantly between phases.
   124	- **Convergent-finding policy** — both verifiers independently
   125	  flagging the same issue from different angles consistently
   126	  identified real problems (test-count drift, plugin SQLite
   127	  overclaim, engine-REP-vs-bridge phrasing).
   128	
   129	## What didn't
   130	
   131	- **Codex CLI sandbox-write rejection** — known per skill §6, but
   132	  required the stdout-redirect workaround on every Codex dispatch.
   133	  Long stretches of "Could not update ... read-only sandbox" prose
   134	  in the response file before the canonical findings; tail parsing
   135	  is the operating mode.
   136	- **Hook false-positives.** This environment's hooks intermittently
   137	  emit "Edit operation failed" / "Write operation failed" while the
   138	  tool itself reports success and grep confirms changes landed.
   139	  Treated as known false-positive; verified actual state with
   140	  ls / wc / grep after each batch.
   141	- **Gemini contradiction across rounds** (Т4 alarm-group inclusion).
   142	  Lesson: even with consistent wide-context, Gemini's structural
   143	  reading can flip between rounds. Repo state is the tiebreaker.
   144	
   145	## Open questions for architect
   146	
   147	1. **Should the four deferred subsystem notes** (Web / Cooldown /
   148	   Experiment manager / Interlock engine) be drafted by CC in the
   149	   next session, or are they out of scope for vault?
   150	2. **`gpt-5.5` vs `gpt-5.4` Codex playbook**. `CLAUDE.md` "Codex
   151	   self-review loop" still mandates `gpt-5.4`. Sessions from
   152	   2026-04-24 onward used `gpt-5.5`. Update CLAUDE.md to match
   153	   reality, or pin sessions back to gpt-5.4?
   154	3. **Skill registry refresh requires harness restart** — open
   155	   ORCHESTRATION.md edit item from
   156	   `2026-04-24-b2b4fb5-investigation` ledger. Still open. Document
   157	   in §5 or leave for next architect session?
   158	4. **The "B1 ZMQ idle-death" engine-REP framing.** The source dossier
   159	   itself contains contradictory claims (early "engine REP healthy"
   160	   vs post-IV.6 "engine REP can also go unresponsive"). Vault now
   161	   reflects both, but a clean architect-side reconciliation in
   162	   `docs/bug_B1_zmq_idle_death_handoff.md` would make the vault
   163	   note tighter.
   164	5. **`.cof` calibration export.** Discussed (architect note 2026-04-25)
   165	   but NOT in current code surface. Vault notes call this out
   166	   correctly. If implementation lands, vault needs touchup; do it
   167	   on next reconciliation.
   168	
   169	## Next architect actions suggested
   170	
   171	- Read `_meta/build log.md` for the full per-phase narrative + audit
   172	  ledgers + Codex / Gemini disagreements.
   173	- Spot-check 5–10 notes you'd expect to know best:
   174	  - `10 Subsystems/Safety FSM.md` (rate-limit + min_points math fixed
   175	    per Gemini)
   176	  - `10 Subsystems/ZMQ bridge.md` + `30 Investigations/B1 ZMQ idle-death.md`
   177	    + `30 Investigations/IV.6 cmd plane hardening.md` (engine-REP
   178	    framing per Codex integration round)
   179	  - `10 Subsystems/Calibration v2.md` (export API per Codex CRITICAL)
   180	  - `10 Subsystems/Plugin architecture.md` +
   181	    `30 Investigations/Plugin isolation rebuild.md` +
   182	    `40 Decisions/ADR-003 Plugin isolation via ABC.md` (SQLite
   183	    overclaim removed)
   184	- If accepting current state: just close this handoff; the vault is
   185	  Obsidian-ready.
   186	- If revising: list specific notes for CC to redo in the next
   187	  session. The four deferred subsystem notes are likely candidates.
   188	- Review `.obsidian/graph.json` colorGroups — easy to revert by
   189	  emptying the array.
   190	
   191	## Wall-clock metrics
   192	
   193	| Phase | Wall-clock |
   194	|---|---|
   195	| Phase 0 pre-flight | ~3 min |
   196	| Phase 1 skeleton | ~3 min |
   197	| Phase 2 reference seed | ~10 min (with audit dispatch overlap) |
   198	| Phase 2 audit + fixes | ~7 min wall-clock; ~3 min audit run |
   199	| Phase 3 synthesis (22 pages) | ~12 min (with audit dispatch overlap) |
   200	| Phase 3 audit + fixes | ~10 min wall-clock; ~4 min audit run |
   201	| Phase 4 cross-link + source map | ~3 min |
   202	| Phase 5 update protocol | ~3 min |
   203	| Integration loop iter 1 + fixes | ~10 min wall-clock; ~6 min audit run |
   204	| Phase 8 polish (theme / plugins / graph / templates) | ~3 min |
   205	| Phase 10 handoff | ~5 min |
   206	| **Total active** | ~46 min |
   207	
   208	Loop iterations: **1** (quiesced).
   209	Codex calls: **4** (Phase 2, Phase 3, integration iter 1, all
   210	gpt-5.5 / high). Each ran 1–6 min wall-clock.
   211	Gemini calls: **4** (Phase 2, Phase 3, integration iter 1, plus
   212	the early skill-context reads via the same harness).
   213	Total tokens used: Codex ~131K + 259K + 208K = ~600K reasoning
   214	across the three audits.
   215	
   216	## Handoff artifacts
   217	
   218	- `~/Projects/cryodaq/artifacts/vault-build/0-preflight-ok.md`
   219	- `~/Projects/cryodaq/artifacts/vault-build/1-skeleton-ok.md`
   220	- `~/Projects/cryodaq/artifacts/vault-build/build_source_map.py`

exec
/opt/homebrew/bin/bash -lc "find /Users/vladimir/Vault/CryoDAQ -path '/Users/vladimir/Vault/CryoDAQ/_meta' -prune -o -path '/Users/vladimir/Vault/CryoDAQ/90 Archive' -prune -o -name '*.md' -print0 | sort -z | while IFS= read -r -d '' f; do printf '%5d %s\\n' \""'$(wc -l < "$f")" "$f"; done' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
  132 /Users/vladimir/Vault/CryoDAQ/00 Overview/Architecture overview.md
   78 /Users/vladimir/Vault/CryoDAQ/00 Overview/Hardware setup.md
  153 /Users/vladimir/Vault/CryoDAQ/00 Overview/UI and design system.md
   98 /Users/vladimir/Vault/CryoDAQ/00 Overview/What is CryoDAQ.md
   15 /Users/vladimir/Vault/CryoDAQ/00 Overview/_index.md
  107 /Users/vladimir/Vault/CryoDAQ/10 Subsystems/Alarm engine v2.md
  113 /Users/vladimir/Vault/CryoDAQ/10 Subsystems/Calibration v2.md
  114 /Users/vladimir/Vault/CryoDAQ/10 Subsystems/Persistence-first.md
  131 /Users/vladimir/Vault/CryoDAQ/10 Subsystems/Plugin architecture.md
  148 /Users/vladimir/Vault/CryoDAQ/10 Subsystems/Safety FSM.md
  134 /Users/vladimir/Vault/CryoDAQ/10 Subsystems/ZMQ bridge.md
   19 /Users/vladimir/Vault/CryoDAQ/10 Subsystems/_index.md
   96 /Users/vladimir/Vault/CryoDAQ/20 Drivers/Keithley 2604B.md
   95 /Users/vladimir/Vault/CryoDAQ/20 Drivers/LakeShore 218S.md
  105 /Users/vladimir/Vault/CryoDAQ/20 Drivers/Thyracont VSP63D.md
   16 /Users/vladimir/Vault/CryoDAQ/20 Drivers/_index.md
  120 /Users/vladimir/Vault/CryoDAQ/30 Investigations/B1 ZMQ idle-death.md
  113 /Users/vladimir/Vault/CryoDAQ/30 Investigations/Codex H2 wrong hypothesis.md
   91 /Users/vladimir/Vault/CryoDAQ/30 Investigations/Cyrillic homoglyph in alarm config.md
  113 /Users/vladimir/Vault/CryoDAQ/30 Investigations/IV.6 cmd plane hardening.md
  100 /Users/vladimir/Vault/CryoDAQ/30 Investigations/Plugin isolation rebuild.md
   19 /Users/vladimir/Vault/CryoDAQ/30 Investigations/_index.md
  124 /Users/vladimir/Vault/CryoDAQ/30 Investigations/b2b4fb5 hardening race.md
   78 /Users/vladimir/Vault/CryoDAQ/40 Decisions/2026-04-23-cleanup-baseline.md
   85 /Users/vladimir/Vault/CryoDAQ/40 Decisions/2026-04-24-b2b4fb5-investigation.md
  104 /Users/vladimir/Vault/CryoDAQ/40 Decisions/2026-04-24-d1-d4a-execution.md
   89 /Users/vladimir/Vault/CryoDAQ/40 Decisions/2026-04-24-overnight-swarm-launch.md
   96 /Users/vladimir/Vault/CryoDAQ/40 Decisions/ADR-001 Persistence-first invariant.md
  107 /Users/vladimir/Vault/CryoDAQ/40 Decisions/ADR-002 R1 bounded-backoff probe retry.md
   83 /Users/vladimir/Vault/CryoDAQ/40 Decisions/ADR-003 Plugin isolation via ABC.md
   29 /Users/vladimir/Vault/CryoDAQ/40 Decisions/_index.md
  159 /Users/vladimir/Vault/CryoDAQ/50 Workflow/Calibration loops history.md
  140 /Users/vladimir/Vault/CryoDAQ/50 Workflow/Multi-model consultation.md
  180 /Users/vladimir/Vault/CryoDAQ/50 Workflow/ORCHESTRATION contract.md
  150 /Users/vladimir/Vault/CryoDAQ/50 Workflow/Overnight swarm pattern.md
   17 /Users/vladimir/Vault/CryoDAQ/50 Workflow/_index.md
   58 /Users/vladimir/Vault/CryoDAQ/60 Roadmap/F-table backlog.md
   62 /Users/vladimir/Vault/CryoDAQ/60 Roadmap/Versions.md
   14 /Users/vladimir/Vault/CryoDAQ/60 Roadmap/_index.md
   23 /Users/vladimir/Vault/CryoDAQ/README.md

exec
/opt/homebrew/bin/bash -lc "for f in /Users/vladimir/Vault/CryoDAQ/00\\ Overview/*.md; do printf '\\n===== %s =====\\n' \""'$f"; nl -ba "$f"; done' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:

===== /Users/vladimir/Vault/CryoDAQ/00 Overview/Architecture overview.md =====
     1	---
     2	source: CLAUDE.md "Архитектура"; PROJECT_STATUS.md "Архитектура"; README.md; CLAUDE.md persistence section
     3	last_synced: 2026-04-26
     4	status: synthesized
     5	---
     6	
     7	# Architecture overview
     8	
     9	CryoDAQ runs as three independent processes that communicate over
    10	ZeroMQ. Each contour can be restarted without taking the others down.
    11	
    12	## Three runtime contours
    13	
    14	```text
    15	                 ZMQ PUB :5555 (data, msgpack)
    16	                 ZMQ REP :5556 (commands, JSON)
    17	                          ↓
    18	cryodaq-engine  ─────────────────────  cryodaq-gui (PySide6)
    19	(headless                                 ToolRail / TopWatchBar /
    20	 asyncio)                                 Dashboard / Overlays /
    21	                                          BottomStatusBar
    22	                          ↓
    23	                  cryodaq.web.server:app
    24	                  (FastAPI monitoring,
    25	                   :8080, optional)
    26	```
    27	
    28	**Engine (`cryodaq-engine`).** Headless asyncio runtime. Owns
    29	`Scheduler`, drivers, `SQLiteWriter`, `DataBroker`, `SafetyBroker`,
    30	`SafetyManager`, alarms, interlocks, housekeeping, plugin loader,
    31	calibration acquisition. No PySide6 import. Rules:
    32	
    33	- No blocking I/O on the event loop (one documented exception:
    34	  `reporting/generator.py` shells out to `soffice` via sync
    35	  `subprocess.run` for best-effort PDF — DEEP_AUDIT finding E.2)
    36	- No numpy/scipy in `drivers/` or `core/` (one documented exception:
    37	  `core/sensor_diagnostics.py` for MAD / correlation)
    38	
    39	**GUI (`cryodaq-gui` / `cryodaq` launcher).** Separate process. Subscribes
    40	to engine PUB stream; sends commands via REQ. Since v0.33.0 the
    41	canonical shell is `MainWindowV2` (Phase I.1 / Phase UI-1 v2):
    42	`TopWatchBar` + `ToolRail` + `BottomStatusBar` + overlay-based content.
    43	The legacy 10-tab `MainWindow` (`gui/main_window.py`) and the
    44	DEPRECATED Phase-I widget panels (alarm / archive / calibration /
    45	conductivity / instrument_status / sensor_diag_panel / keithley /
    46	operator_log / experiment_workspace / autosweep) were retired and
    47	deleted in Phase II.13. Remaining `gui/widgets/*` modules are
    48	ancillary, non-overlay surfaces (overview_panel, temp_panel,
    49	pressure_panel, channel_editor, connection_settings, shift_handover,
    50	etc.); `widgets/common.py` is retained for shared helpers.
    51	
    52	**Web (`cryodaq.web.server:app`).** Optional FastAPI surface on
    53	`:8080`. Read-only monitoring. Loopback-only deployment is the
    54	expected pattern (auth deferred to F7 / G.1).
    55	
    56	## Persistence-first ordering
    57	
    58	Hard ordering invariant:
    59	
    60	```text
    61	InstrumentDriver.read_channels()
    62	  → Scheduler
    63	     1. SQLiteWriter.write_immediate()       ← commit first
    64	     2. THEN DataBroker.publish_batch()      ← GUI / web see it
    65	     3. THEN SafetyBroker.publish_batch()    ← safety FSM sees it
    66	```
    67	
    68	> If `DataBroker` has a reading, it has already been written to SQLite.
    69	
    70	This is non-negotiable for post-mortem reconstruction
    71	([[10 Subsystems/Persistence-first]]). It costs ~few-ms GUI latency
    72	per poll; that tradeoff is intentional.
    73	
    74	## ZMQ topology
    75	
    76	- **PUB/SUB :5555** — data plane (msgpack). Always-on stream of
    77	  readings, alarm events, safety state.
    78	- **REP/REQ :5556** — command plane (JSON). Operator commands
    79	  (start experiment, acknowledge fault, request status).
    80	- **Subprocess isolation.** Engine runs ZMQ in a child subprocess
    81	  (`core/zmq_subprocess.py`); the engine main loop is shielded from
    82	  ZMQ crashes.
    83	- **Watchdog** with 60s cooldown after restart — prevents IV.6 restart
    84	  storm ([[30 Investigations/IV.6 cmd plane hardening]]).
    85	- **Transport experiment** `ipc://` (IV.7) is in progress — see
    86	  [[30 Investigations/B1 ZMQ idle-death]] and
    87	  [[30 Investigations/b2b4fb5 hardening race]].
    88	
    89	## Subsystem map
    90	
    91	Active narrative pages live under `10 Subsystems/`:
    92	
    93	- [[10 Subsystems/Safety FSM]] — single source on/off authority
    94	- [[10 Subsystems/ZMQ bridge]] — engine ↔ GUI command + data planes
    95	- [[10 Subsystems/Persistence-first]] — write-before-publish invariant
    96	- [[10 Subsystems/Calibration v2]] — continuous SRDG, Chebyshev fit
    97	- [[10 Subsystems/Alarm engine v2]] — YAML config, phase-aware
    98	- [[10 Subsystems/Plugin architecture]] — hot-reload analytics SDK
    99	
   100	## Configuration files
   101	
   102	All YAML, all under `config/`. Changes require engine restart
   103	(fail-closed on malformed):
   104	
   105	- `instruments.yaml` (+ `*.local.yaml` overrides)
   106	- `safety.yaml`, `interlocks.yaml`, `alarms.yaml`, `alarms_v3.yaml`
   107	- `channels.yaml`, `housekeeping.yaml`, `cooldown.yaml`, `plugins.yaml`
   108	- `notifications.yaml`, `shifts.yaml`
   109	- `experiment_templates/*.yaml`
   110	- `themes/*.yaml` (12 bundled theme packs: six original since 2026-04-18 plus six added in Phase III.A)
   111	
   112	Five safety-adjacent configs (`safety`, `alarm`, `interlock`,
   113	`housekeeping`, `channels`) raise subsystem-specific `ConfigError` →
   114	engine exit code 2 → no auto-restart. See
   115	[[40 Decisions/ADR-001 Persistence-first invariant]] for the
   116	rationale on similar fail-closed defaults.
   117	
   118	## Concurrency model
   119	
   120	Single asyncio event loop in the engine. Scheduler drives drivers
   121	sequentially (each driver instance has its own poll task).
   122	`SafetyManager` re-entry guarded against concurrent `_fault()` calls
   123	(early return if `state == FAULT_LATCHED`, added 2026-04-17).
   124	
   125	`reporting/generator.py` and `log_get` are the documented exits to
   126	synchronous I/O and read executors respectively.
   127	
   128	## See also
   129	
   130	- [[00 Overview/Hardware setup]] — what's on the bus
   131	- [[00 Overview/What is CryoDAQ]] — scope and motivation
   132	- [[40 Decisions/_index]] — accepted ADRs

===== /Users/vladimir/Vault/CryoDAQ/00 Overview/Hardware setup.md =====
     1	---
     2	source: CLAUDE.md "Физическая установка"; config/instruments.yaml; PROJECT_STATUS.md
     3	last_synced: 2026-04-26
     4	status: synthesized
     5	---
     6	
     7	# Hardware setup
     8	
     9	CryoDAQ runs against a single physical rig at the Millimetron / АКЦ
    10	ФИАН cryogenic lab. Three instrument families on three transports.
    11	
    12	## Instruments
    13	
    14	| Instrument | Interface | Channels | Driver |
    15	|---|---|---|---|
    16	| LakeShore 218S × 3 (`LS218_1` `GPIB0::12::INSTR`, `LS218_2` `GPIB0::14::INSTR`, `LS218_3` `GPIB0::16::INSTR`) | GPIB | 24 temperature (Т1..Т24) | [[20 Drivers/LakeShore 218S]] |
    17	| Keithley 2604B (`Keithley_1` `USB0::0x05E6::0x2604::04052028::INSTR`) | USB-TMC | `smua` + `smub` | [[20 Drivers/Keithley 2604B]] |
    18	| Thyracont VSP63D type [^vsp206] (`VSP63D_1` COM3 @ 9600 baud) | RS-232 (serial) | 1 pressure | [[20 Drivers/Thyracont VSP63D]] |
    19	
    20	[^vsp206]: Production lab PC actually has VSP206 hardware (different checksum formula); driver still loaded as `thyracont_vsp63d` type with `validate_checksum: false` per-machine override. See [[20 Drivers/Thyracont VSP63D]] and [[10 Subsystems/Alarm engine v2]].
    21	
    22	Configuration lives in `config/instruments.yaml`; per-machine overrides
    23	in `config/instruments.local.yaml` (gitignored).
    24	
    25	## Channel layout (LakeShore daisy-chain)
    26	
    27	Three controllers, eight channels each, grouped semantically:
    28	
    29	- **LS218_1** (GPIB::12) — `Т1 Криостат верх`, `Т2 Криостат низ`, `Т3 Радиатор 1`,
    30	  `Т4 Радиатор 2`, `Т5 Экран 77К`, `Т6 Экран 4К`, `Т7 Детектор`,
    31	  `Т8 Калибровка`
    32	- **LS218_2** (GPIB::14) — `Т9 Компрессор вход`, `Т10 Компрессор выход`,
    33	  `Т11 Теплообменник 1`, `Т12 Теплообменник 2`, `Т13 Труба подачи`,
    34	  `Т14 Труба возврата`, `Т15 Вакуумный кожух`, `Т16 Фланец`
    35	- **LS218_3** (GPIB::16) — `Т17 Зеркало 1`, `Т18 Зеркало 2`, `Т19 Подвес`,
    36	  `Т20 Рама`, `Т21..24 Резерв 1..4`
    37	
    38	The «Т» prefix is **Cyrillic Т (U+0422)**, not Latin T. This homoglyph
    39	caused a real config-evaluation bug; see [[30 Investigations/Cyrillic homoglyph in alarm config]].
    40	
    41	## Per-machine field state (Ubuntu lab PC, 2026-04-20)
    42	
    43	- `Т4 Радиатор 2` is **physically disconnected** — open-circuit reads
    44	  ~380 K. `interlocks.yaml::overheat_cryostat` regex was tightened
    45	  from `Т[1-8] .*` to `Т(1|2|3|5|6|7|8) .*` to exclude it without
    46	  losing coverage on Т1..Т8.
    47	- Thyracont hardware on this PC is actually **VSP206**, not VSP63D —
    48	  uses a different checksum formula. `instruments.local.yaml` carries
    49	  `validate_checksum: false` (per-machine override; `aabd75f` wired
    50	  the YAML key through after it had been silently ignored).
    51	- `ModemManager` was disabled on the lab PC because it was transiently
    52	  grabbing `/dev/ttyUSB0`.
    53	
    54	## Polling cadence
    55	
    56	| Instrument | `poll_interval_s` |
    57	|---|---|
    58	| LakeShore 218S × 3 | 2.0 |
    59	| Keithley 2604B | 1.0 |
    60	| Thyracont VSP63D | 2.0 |
    61	
    62	Polling is host-driven by [[10 Subsystems/Persistence-first|`Scheduler`]];
    63	per-driver intervals are independent.
    64	
    65	## Out-of-band hardware
    66	
    67	- **Keithley TSP supervisor** — `tsp/p_const.lua` is drafted but **not
    68	  loaded** on the device. P=const feedback runs host-side in
    69	  `keithley_2604b.py`. TSP supervisor planned for Phase 3 (requires
    70	  hardware verification).
    71	
    72	## See also
    73	
    74	- [[10 Subsystems/Safety FSM]] — uses temperature channels for rate
    75	  limit / overheat interlock
    76	- [[10 Subsystems/Calibration v2]] — calibration applies to LakeShore
    77	  channels via per-channel policy
    78	- [[_meta/glossary]] — KRDG, SRDG, FSM definitions

===== /Users/vladimir/Vault/CryoDAQ/00 Overview/UI and design system.md =====
     1	---
     2	source: CLAUDE.md "Источник истины по UI/визуальному дизайну"; PROJECT_STATUS.md "Phase I.1 + Design System v1.0.1"; PROJECT_STATUS.md "Host Integration Contract"; CHANGELOG.md "Phase III.A/B/C"
     3	last_synced: 2026-04-26
     4	status: synthesized — Phase 4 coverage-gap fix
     5	---
     6	
     7	# UI and design system
     8	
     9	Operator-facing UI architecture, design system canon, and the
    10	Host Integration Contract that ships overlays end-to-end.
    11	
    12	## Why this note exists
    13	
    14	Gemini's Phase 2 audit flagged a coverage gap: the Phase I.1 shell
    15	rebuild + Design System v1.0.1 + Host Integration Contract are a
    16	significant fraction of recent architectural effort but had no
    17	dedicated Overview note. This page closes that gap.
    18	
    19	## Design system canon
    20	
    21	Source of truth for all operator-facing UI is `docs/design-system/`
    22	(v1.0.1, 67 canonical .md files, 139 tokens). The folder structure:
    23	
    24	- `docs/design-system/README.md` — entry point, navigation
    25	- `docs/design-system/MANIFEST.md` — full index + 65 encoded decisions
    26	- `docs/design-system/rules/<category>-rules.md` — 79 enforcement rules
    27	- `docs/design-system/components/<widget>.md` — generic primitives
    28	- `docs/design-system/cryodaq-primitives/<widget>.md` — domain widgets
    29	- `docs/design-system/patterns/<pattern>.md` — composition patterns
    30	- `docs/design-system/accessibility/*.md` — WCAG 2.2 AA commitment
    31	- `docs/design-system/governance/*.md` — evolution rules
    32	
    33	Token semantics ship through `gui/theme.py` (139 foundation tokens).
    34	Hard rule: **all colors / sizes / radii / fonts come from `theme.py`.
    35	Hardcoded hex / px / font-size violates RULE-COLOR-010 / RULE-TYPO-007 /
    36	RULE-SPACE-001.**
    37	
    38	Deprecated tokens (STONE_*) are policy-tracked through
    39	`docs/design-system/governance/deprecation-policy.md`. New code uses
    40	canonical names (FOREGROUND, BACKGROUND, MUTED_FOREGROUND, etc.).
    41	
    42	## Phase I.1 — shell rebuild (v0.33.0)
    43	
    44	`MainWindowV2` replaced the legacy 10-tab `MainWindow` as primary
    45	shell. Layout:
    46	
    47	- `TopWatchBar` — engine indicator, experiment status, 4 vitals + mode
    48	  badge (Эксперимент / Отладка)
    49	- `ToolRail` — left-side icon navigation (9 slots, `Ctrl+[1-9]`
    50	  transitional)
    51	- `OverlayContainer` — central content host with overlay primitives
    52	- `BottomStatusBar` — safety state strip
    53	- `DashboardView` — 5-zone ambient information radiator (sensor grid,
    54	  temp plot, pressure plot, phase widget, quick log) used as the
    55	  default view
    56	
    57	Canonical mnemonic shortcuts (per AD-002): `Ctrl+L/E/A/K/M/R/C/D` for
    58	global navigation, plus `F5` and `Ctrl+Shift+X`. Sole owner of bindings
    59	since `gui/main_window.py` was retired in Phase II.13. The
    60	transitional `Ctrl+[1-9]` rail-slot numbering is scheduled to retire
    61	with the legacy widget cleanup.
    62	
    63	Overlay primitives under
    64	`gui/shell/overlays/_design_system/`: `ModalCard`, `BentoGrid`,
    65	`DrillDownBreadcrumb`. Showcase at `_showcase.py` for visual review.
    66	
    67	## Phase II — overlay rebuilds + Host Integration Contract
    68	
    69	| Block | Status (2026-04-19) |
    70	|---|---|
    71	| II.1 AnalyticsView | ✅ COMPLETE (`860ecf3`) |
    72	| II.2 ArchiveOverlay | ✅ COMPLETE (`e4a60f3`) |
    73	| II.3 OperatorLog | ✅ COMPLETE (`9676acc`) |
    74	| II.4 AlarmOverlay | ⚠️ PARTIAL (badge routing only) |
    75	| II.5 ConductivityOverlay | ⬜ NOT STARTED (next) |
    76	| II.6 KeithleyOverlay | ✅ COMPLETE (`96adf5a`) |
    77	| II.7 CalibrationOverlay | ⬜ NOT STARTED |
    78	| II.8 Instruments+SensorDiag | ⬜ NOT STARTED |
    79	| II.9 ExperimentOverlay v3 | ⚠️ PARTIAL (functional; visual pending) |
    80	| II.13 legacy cleanup | ✅ — DEPRECATED v1 widgets and `main_window.py` deleted |
    81	
    82	### Host Integration Contract
    83	
    84	Codified after the II.6 Keithley FAIL revealed a systemic risk:
    85	overlays with public push setters (`set_connected`,
    86	`set_current_experiment`, `set_safety_ready`, etc.) are useless if
    87	`MainWindowV2` never calls them. Unit tests on the overlay alone pass
    88	while production is broken.
    89	
    90	Contract — mandatory for every overlay with push setters:
    91	
    92	1. **`_tick_status()` mirror** for `set_connected(bool)`.
    93	2. **`_dispatch_reading()` state sinks** for stateful readings
    94	   (safety state, experiment status, finalized events).
    95	3. **`_ensure_overlay()` replay** on lazy open — push cached state
    96	   the moment the overlay is constructed, so the first paint is
    97	   correct.
    98	
    99	Tests: overlay unit tests AND host integration tests
   100	(`tests/gui/shell/test_main_window_v2_<block>_wiring.py`) that
   101	exercise `MainWindowV2` entry points end-to-end (signal fire / cache
   102	set / `_ensure_overlay` call) and assert overlay state.
   103	
   104	## Phase III — analytics + theming + accent decoupling
   105	
   106	- **III.A — DS accent / status decoupling.** `STATUS_OK` (safety
   107	  green) was rendering UI states (selected rows, active tabs, primary
   108	  buttons, mode badge) and reading to operators as "this is healthy".
   109	  Introduced `SELECTION_BG` and `FOCUS_RING` neutral interaction
   110	  tokens; required by `_theme_loader.REQUIRED_TOKENS` across all 12
   111	  bundled themes; 5 overlays + TopWatchBar mode badge migrated to
   112	  `ACCENT + ON_ACCENT`. ADR 002 captures the rationale +
   113	  hue-distance invariants.
   114	- **III.B — GlobalTimeWindow + shared PressurePlot + PredictionWidget.**
   115	  `TimeWindow` enum promoted from dashboard-local to
   116	  `cryodaq.gui.state.time_window` with `GlobalTimeWindowController`
   117	  singleton. Every historical plot subscribes — clicking 1мин / 1ч /
   118	  6ч / 24ч / Всё on any plot updates every plot. Prediction plots
   119	  do NOT subscribe; they have their own forward horizon (1/3/6/12/24/48ч).
   120	  `ScientificLogAxisItem` for log-Y tick labels.
   121	- **III.C — Phase-aware AnalyticsView rebuild.** 2×2 QGridLayout swap
   122	  per experiment phase via `config/analytics_layout.yaml`. Layout per
   123	  phase: preparation → temperature; vacuum → vacuum prediction +
   124	  temp/pressure; cooldown → cooldown prediction; measurement → R_thermal
   125	  + keithley power; warmup / disassembly own mappings. New widget
   126	  registry at `gui/shell/views/analytics_widgets.py`.
   127	
   128	## Theme switcher (2026-04-18)
   129	
   130	Six bundled YAML theme packs at `config/themes/`: `default_cool`,
   131	`warm_stone`, `anthropic_mono`, `ochre_bloom`, `taupe_quiet`,
   132	`rose_dusk`. Runtime theme loader at `gui/_theme_loader.py` —
   133	`theme.py` reads tokens from YAML packs. Settings → Тема menu uses
   134	`os.execv` restart pattern. Status palette (STATUS_OK, WARNING,
   135	CAUTION, FAULT, INFO, STALE, COLD_HIGHLIGHT) locked across all packs.
   136	Phase III.A added `SELECTION_BG` + `FOCUS_RING` to all 12 themes
   137	including the additional `braun` pack.
   138	
   139	## Governance
   140	
   141	Architect = Vladimir. Every design-system change goes through
   142	`docs/design-system/governance/contribution.md`. Every GUI change
   143	that touches visual rendering must start by reading the relevant
   144	design-system files. Codex / Gemini reviews check for token leakage
   145	(hardcoded values), pattern mismatches, and accessibility regressions.
   146	
   147	## See also
   148	
   149	- [[00 Overview/Architecture overview]] — three runtime contours
   150	- [[00 Overview/What is CryoDAQ]] — scope and motivation
   151	- [[40 Decisions/_index]] — accepted ADRs
   152	- `docs/design-system/README.md` — full source of truth
   153	- `docs/CODEX_SELF_REVIEW_PLAYBOOK.md` — block-commit review cadence

===== /Users/vladimir/Vault/CryoDAQ/00 Overview/What is CryoDAQ.md =====
     1	---
     2	source: CLAUDE.md; README.md; PROJECT_STATUS.md (2026-04-19); pyproject.toml; live wc/find counts (2026-04-26)
     3	last_synced: 2026-04-26
     4	status: synthesized
     5	---
     6	
     7	# What is CryoDAQ
     8	
     9	## What it is
    10	
    11	CryoDAQ is the data acquisition and control stack for a cryogenic
    12	laboratory at АКЦ ФИАН (the Millimetron telescope project). It
    13	replaces the previous LabVIEW system with a Python 3.12+ codebase
    14	built on `asyncio` and `PySide6`. Operator-facing language is Russian.
    15	
    16	## What it does
    17	
    18	End-to-end laboratory workflow:
    19	
    20	- Continuous acquisition from three instrument families
    21	  ([[00 Overview/Hardware setup]])
    22	- Safety-critical source on/off authority via the
    23	  [[10 Subsystems/Safety FSM]] (single-authority `SafetyManager`,
    24	  source OFF by default, fail-on-silence in RUN_PERMITTED/RUNNING)
    25	- Persistence-first data path
    26	  ([[10 Subsystems/Persistence-first]] — SQLite WAL commit before
    27	  any subscriber sees a reading)
    28	- ZMQ-bridged operator GUI ([[10 Subsystems/ZMQ bridge]])
    29	- Experiment lifecycle (templates, phases, finalize, archive,
    30	  auto-report)
    31	- Calibration v2 — continuous SRDG capture, three-mode UI, post-run
    32	  Chebyshev fit ([[10 Subsystems/Calibration v2]])
    33	- YAML-driven alarm engine v2 ([[10 Subsystems/Alarm engine v2]]),
    34	  interlocks, housekeeping, telegram notifications
    35	- Optional FastAPI web dashboard for monitoring
    36	
    37	## Where it runs
    38	
    39	Three runtime contours, all on a single lab PC (Linux Ubuntu 22.04
    40	production / macOS dev):
    41	
    42	1. `cryodaq-engine` — headless asyncio runtime: drivers, scheduler,
    43	   persistence, safety, alarms, plugins. Survives GUI restart.
    44	2. `cryodaq-gui` (or `cryodaq` Windows launcher) — desktop operator
    45	   client. Connects to engine over ZMQ; can be killed/restarted
    46	   without stopping data.
    47	3. `cryodaq.web.server:app` — optional FastAPI monitoring on `:8080`.
    48	
    49	ZeroMQ topology: PUB/SUB `:5555` for data (msgpack), REP/REQ `:5556`
    50	for commands (JSON). The bridge subprocess isolates engine from GUI
    51	crashes ([[10 Subsystems/ZMQ bridge]]).
    52	
    53	## Who maintains it
    54	
    55	- **Architect:** Vladimir (also project owner; user of this vault).
    56	- **Implementation:** Claude Code as primary implementer with
    57	  Codex / Gemini as adversarial reviewers
    58	  ([[50 Workflow/Multi-model consultation]],
    59	  [[50 Workflow/ORCHESTRATION contract]]).
    60	- **Pipeline:** CC tactical → Codex line-level review → optional
    61	  Jules architectural review on safety-critical changes
    62	  ([[50 Workflow/Calibration loops history]]).
    63	
    64	## Scale (2026-04-26)
    65	
    66	| Metric | Value | Source |
    67	|---|---|---|
    68	| Python files (`src/cryodaq/`) | **145** | `find` |
    69	| Lines of code (`src/cryodaq/`) | **47 610** | `wc -l` |
    70	| Test files (`tests/`) | **194** | `find tests -name '*.py' -not -path '*/__pycache__/*'` |
    71	| Test LOC (`tests/`) | **36 002** | `wc -l` |
    72	| Tests passing (post-IV.6) | 1 775 / 1 776 (1 pre-existing flaky) | `CHANGELOG.md` `be51a24` — full subtree count |
    73	| Tests passing (last formal measurement, older) | 1 368 / 2 skipped | `PROJECT_STATUS.md` 2026-04-19 |
    74	| Coverage (full suite, stale) | 66 % | last measured 2026-04-17 |
    75	| `pyproject.toml` version | 0.34.0.dev0 | `pyproject.toml` |
    76	| Latest version git tag | v0.33.0 | `git tag -l` (also: non-package marker `design-system-v1.0.1`) |
    77	| Design system | v1.0.1 (67 .md, 139 tokens) | `docs/design-system/` |
    78	| Python | 3.12+ (dev: 3.14.3) | `CLAUDE.md` |
    79	| Instruments | 3 LakeShore + 1 Keithley + 1 Thyracont | [[00 Overview/Hardware setup]] |
    80	
    81	LOC count is `wc -l` over `*.py` only and excludes `__pycache__/`.
    82	Test pass count is from the last published session ledger; live count
    83	likely higher (several feature batches merged since IV.4 close).
    84	
    85	## Where it lives
    86	
    87	- **Repo:** `~/Projects/cryodaq/` (this vault is read-only with
    88	  respect to the repo)
    89	- **Data:** `data/data_*.db` (SQLite WAL, daily rotation),
    90	  `data/experiments/<id>/`, `data/calibration/`
    91	- **Vault:** `~/Vault/CryoDAQ/` (this knowledge base)
    92	- **TSP scripts (drafts, not loaded):** `tsp/p_const.lua`
    93	
    94	## See also
    95	
    96	- [[00 Overview/Architecture overview]]
    97	- [[60 Roadmap/Versions]]
    98	- [[60 Roadmap/F-table backlog]]

===== /Users/vladimir/Vault/CryoDAQ/00 Overview/_index.md =====
     1	---
     2	source: skeleton stub
     3	last_synced: 2026-04-26
     4	status: index
     5	---
     6	
     7	# 00 Overview
     8	
     9	Entry point notes — what CryoDAQ is, who runs it, the physical hardware,
    10	and the high-level architecture.
    11	
    12	- [[00 Overview/What is CryoDAQ]]
    13	- [[00 Overview/Hardware setup]]
    14	- [[00 Overview/Architecture overview]]
    15	- [[00 Overview/UI and design system]]

exec
/opt/homebrew/bin/bash -lc "for f in /Users/vladimir/Vault/CryoDAQ/10\\ Subsystems/*.md; do printf '\\n===== %s =====\\n' \""'$f"; nl -ba "$f"; done' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:

===== /Users/vladimir/Vault/CryoDAQ/10 Subsystems/Alarm engine v2.md =====
     1	---
     2	source: src/cryodaq/core/alarm_v2.py; core/alarm_config.py; config/alarms_v3.yaml; CHANGELOG.md "alarm_v2.py:252 cooldown_stall"; CLAUDE.md alarm section
     3	last_synced: 2026-04-26
     4	status: synthesized
     5	---
     6	
     7	# Alarm engine v2
     8	
     9	YAML-driven, phase-aware alarm engine. Replaces v1's hardcoded
    10	threshold-with-hysteresis logic.
    11	
    12	## Components
    13	
    14	`core/alarm_v2.py` defines:
    15	
    16	- **`AlarmEvent`** — frozen dataclass: `alarm_id`, `level`,
    17	  `message`, `triggered_at`, `channels`, `values`, `acknowledged`.
    18	- **`AlarmTransition` = TRIGGERED | CLEARED`** — typed literal.
    19	- **`PhaseProvider` / `SetpointProvider`** — duck-typed protocols
    20	  feeding the evaluator.
    21	- **`AlarmEvaluator`** — pure function from `(alarm_id, alarm_config)`
    22	  to `AlarmEvent | None`, dispatching by `alarm_type`.
    23	- **`AlarmStateManager`** — manages active/cleared transitions,
    24	  hysteresis, deduplication.
    25	
    26	## Alarm types
    27	
    28	| `alarm_type` | Signal | Where used |
    29	|---|---|---|
    30	| `threshold` | scalar `value > threshold` (or `<`) | static safety/operational limits |
    31	| `composite` | AND/OR of sub-conditions, each typed | physically-motivated multi-channel rules |
    32	| `rate` | `dX/dt` over a configurable window via `RateEstimator` | trend-based anomaly (cooldown stall, runaway warming) |
    33	| `stale` | last reading age > threshold | sensor / link health |
    34	
    35	Composite sub-conditions support `above`, `below`, `rate_above`,
    36	`rate_below`, `rate_near_zero`, plus `phase_elapsed_s` as a
    37	synthetic channel for time-based gates within an experiment phase.
    38	
    39	## Phase-aware
    40	
    41	`PhaseProvider.get_current_phase()` and
    42	`get_phase_elapsed_s()` let alarm rules be active only during
    43	specific experiment phases. Example: `cooldown_stall` is meaningful
    44	during the cooldown phase but not during disassembly.
    45	
    46	`SetpointProvider` lets thresholds be parameterized by experiment
    47	template (e.g. T_target = 4.2 K vs 77 K) so the same rule fires for
    48	the right physical regime per experiment.
    49	
    50	## Configuration
    51	
    52	`config/alarms_v3.yaml` declares all alarms. `core/alarm_config.py`
    53	validates and parses. Fail-closed: malformed `alarms_v3.yaml` → engine
    54	exit code 2.
    55	
    56	`src/cryodaq/core/alarm_providers.py` ships concrete `PhaseProvider`
    57	and `SetpointProvider` wired to `ExperimentManager`.
    58	
    59	## Cyrillic Т homoglyph regression
    60	
    61	`config/alarms_v3.yaml` previously contained a Latin "T" where
    62	Cyrillic "Т" (U+0422) was meant. Runtime tests passed because the
    63	alarm logic was correct; the channels just never matched anything.
    64	Caught by adversarial LLM review (Codex). Regression test added.
    65	Full story: [[30 Investigations/Cyrillic homoglyph in alarm config]].
    66	
    67	`docs/design-system/` rules (RULE-COLOR / RULE-TYPO) carry similar
    68	Latin/Cyrillic invariants. Mention in MANIFEST.
    69	
    70	## Channel groups (current `alarms_v3.yaml`)
    71	
    72	`uncalibrated` and `all_temp` groups **explicitly exclude** Т4
    73	(Радиатор 2) and Т8 (Калибровка) — both physically disconnected on
    74	the production lab PC. Comment on `alarms_v3.yaml:32` reads
    75	"Т4 (Радиатор 2), Т8 (Калибровка) — отключённые датчики, исключены".
    76	The exclusion is in master, not just per-machine; future deploys with
    77	Т4/Т8 connected need to add them back manually.
    78	
    79	## Known issue (open)
    80	
    81	`alarm_v2.py:252` raises `KeyError: 'threshold'` when evaluating the
    82	`cooldown_stall` composite alarm: one sub-condition is missing a
    83	required `threshold` field. Log spam every ~2 s; engine does not
    84	crash. Fix candidates per ROADMAP:
    85	
    86	- Config-side: audit `config/alarms_v3.yaml` to add the missing
    87	  threshold (or change the offending condition's type if `threshold`
    88	  is genuinely spurious for that condition shape).
    89	- Code-side: defensive `cond.get("threshold")` access in
    90	  `_eval_condition`.
    91	
    92	Pending Codex-04 patch (overnight swarm 2026-04-24 stream).
    93	
    94	## Relationship to safety
    95	
    96	The alarm engine is for **operator attention**, not source-control
    97	authority. `SafetyManager` is the only thing that turns sources on
    98	or off. An alarm at CRITICAL level may trigger an interlock action
    99	configured separately in `config/interlocks.yaml`, but the
   100	authority to act is still `SafetyManager`'s. See
   101	[[10 Subsystems/Safety FSM]].
   102	
   103	## See also
   104	
   105	- [[30 Investigations/Cyrillic homoglyph in alarm config]]
   106	- [[10 Subsystems/Safety FSM]]
   107	- [[60 Roadmap/F-table backlog]] — F10 (sensor diagnostics → alarm)

===== /Users/vladimir/Vault/CryoDAQ/10 Subsystems/Calibration v2.md =====
     1	---
     2	source: src/cryodaq/analytics/calibration.py; analytics/calibration_fitter.py; core/calibration_acquisition.py; CLAUDE.md "Снимок сверки"; README.md "Calibration v2"
     3	last_synced: 2026-04-26
     4	status: synthesized
     5	---
     6	
     7	# Calibration v2
     8	
     9	Three-mode calibration pipeline introduced as the v2 redesign of the
    10	LakeShore sensor calibration workflow.
    11	
    12	## Three-mode flow
    13	
    14	| Mode | Surface | Action |
    15	|---|---|---|
    16	| **Setup** | GUI: `cryodaq-gui` Calibration tab | Operator picks reference channel, target channels, optional context. Engine starts the experiment with `calibration_acquisition: true`. |
    17	| **Acquisition** | Engine: `CalibrationAcquisitionService` | Continuous SRDG (`Sensor Raw Data Grabbing`) capture during the experiment, alongside KRDG (calibrated kelvin readings). One transaction per poll cycle. |
    18	| **Results** | Engine + GUI: `CalibrationFitter` post-run pipeline | Extract → downsample → breakpoints → Chebyshev fit → export. Operator reviews and applies. |
    19	
    20	## Continuous SRDG acquisition
    21	
    22	`CalibrationAcquisitionService` (`core/calibration_acquisition.py`) is
    23	activated by experiments with `calibration_acquisition: true`. The
    24	scheduler calls `prepare_srdg_readings(krdg, srdg)` after each
    25	LakeShore poll; the writer commits both KRDG and SRDG in one
    26	transaction; `on_srdg_persisted(pending_state)` then applies the
    27	in-memory `t_min`/`t_max` updates AFTER the commit.
    28	
    29	The deferral matters: state mutation BEFORE persistence would let a
    30	crash leave `t_min`/`t_max` diverged from what's actually in SQLite.
    31	See [[10 Subsystems/Persistence-first]] (Phase 2d invariant 15).
    32	
    33	`reference_channel` and `target_channels` are canonicalized through
    34	`ChannelManager.resolve_channel_reference()` so per-rack semantics
    35	("rack 1 sensor 3") resolve to the canonical Cyrillic Т-prefixed
    36	names regardless of how the operator typed it.
    37	
    38	## Post-run pipeline
    39	
    40	`CalibrationFitter` (`analytics/calibration_fitter.py`):
    41	
    42	1. **Extract.** Read SQLite over the experiment time range; pair each
    43	   SRDG raw value with its time-aligned KRDG reference temperature
    44	   (default `max_time_delta_s=2.0`). Returns
    45	   `list[tuple[sensor_raw, reference_T_K]]`.
    46	2. **Downsample.** Reduce dense pairs to representative pairs while
    47	   preserving curve shape. Density along T axis matters more than
    48	   along time axis.
    49	3. **Breakpoints.** `generate_breakpoints()` produces a sampled
    50	   breakpoint list intended for export / inspection (e.g. preview of
    51	   what the LakeShore `.340` table will look like). The actual
    52	   Chebyshev zone boundaries are detected internally by the fitter
    53	   (`CalibrationStore.fit_curve()` at `analytics/calibration.py`).
    54	4. **Fit.** `CalibrationStore.fit_curve()` uses
    55	   `numpy.polynomial.chebyshev` per zone; produces a
    56	   `CalibrationCurve` with coefficients per zone, fit metrics,
    57	   source session IDs, metadata.
    58	
    59	Result is a `CalibrationFitResult` with raw, downsampled, and
    60	breakpoint pair lists kept around for plotting / inspection.
    61	
    62	## Output formats
    63	
    64	Exports go through `CalibrationStore` methods:
    65	`export_curve_json()`, `export_curve_table()` (CSV), `export_curve_330()`,
    66	`export_curve_340()`. Targets:
    67	
    68	- **`.330`** — LakeShore controller calibration table format,
    69	  breakpoint-based. Contains sampled curve breakpoints, NOT polynomial
    70	  coefficients. Older format.
    71	- **`.340`** — LakeShore newer breakpoint format, same family as
    72	  `.330`.
    73	- **JSON** — CryoDAQ-internal format with Chebyshev coefficients per
    74	  zone, metrics, source session IDs, metadata. Source-of-truth
    75	  artifact.
    76	- **CSV** — round-trip with external tooling via `export_curve_table()`.
    77	
    78	A `.cof` raw-Chebyshev-coefficient export format was discussed
    79	(architect note 2026-04-25) but is **not in the current code surface**
    80	— if and when it lands, this note must be updated.
    81	
    82	## Runtime apply policy
    83	
    84	Calibration v2 supports per-channel runtime routing in
    85	`LakeShore218S` (`drivers/instruments/lakeshore_218s.py`):
    86	
    87	- **Global mode `on/off`** — enable / disable runtime calibration
    88	  application across all LakeShore channels at once.
    89	- **Per-channel policy `inherit | off | on`** — overrides the global
    90	  mode. `inherit` follows global; `off`/`on` pin per-channel behavior.
    91	- **Conservative fallback** — at runtime, if curve / assignment /
    92	  SRDG missing OR computation throws, the driver falls back to KRDG
    93	  (calibrated reading from the LakeShore controller itself) and logs
    94	  the reason once per `(channel_key, reason)` to avoid log spam
    95	  (`_runtime_warning_cache`).
    96	
    97	Policy + fallback together mean a malformed curve never silently
    98	breaks an experiment — operator sees KRDG, behavior degrades to v1
    99	semantics, log line tells them what happened.
   100	
   101	## Lab-verification gap
   102	
   103	Per `README.md` "Известные ограничения": runtime apply policy is
   104	implemented and tested in mock; **per-channel behavior on the live
   105	LakeShore requires separate lab verification** before being trusted
   106	as the active calibration in production runs.
   107	
   108	## See also
   109	
   110	- [[20 Drivers/LakeShore 218S]] — driver runtime routing impl
   111	- [[10 Subsystems/Persistence-first]] — KRDG+SRDG one-transaction rule
   112	- [[_meta/glossary]] — KRDG, SRDG definitions
   113	- [[60 Roadmap/F-table backlog]] — F8 (cooldown ML), F9 (TIM auto-report)

===== /Users/vladimir/Vault/CryoDAQ/10 Subsystems/Persistence-first.md =====
     1	---
     2	source: CLAUDE.md persistence section; PROJECT_STATUS.md invariant 2; src/cryodaq/core/scheduler.py; src/cryodaq/storage/sqlite_writer.py
     3	last_synced: 2026-04-26
     4	status: synthesized
     5	---
     6	
     7	# Persistence-first ordering
     8	
     9	CryoDAQ's most-load-bearing invariant.
    10	
    11	## The invariant
    12	
    13	```text
    14	InstrumentDriver.read_channels()
    15	  → Scheduler
    16	     1. SQLiteWriter.write_immediate()
    17	     2. THEN DataBroker.publish_batch()
    18	     3. THEN SafetyBroker.publish_batch()
    19	```
    20	
    21	> If `DataBroker` has a reading, it has already been written to SQLite.
    22	
    23	The same property holds for `SafetyBroker`. Engine subscribers see a
    24	reading **strictly after** that reading has committed to durable
    25	storage.
    26	
    27	## Why it matters
    28	
    29	Cryogenic experiments are long (days–weeks) and expensive. After any
    30	unexpected engine termination (crash, SIGKILL, power loss) the
    31	post-mortem reconstruction MUST be able to answer "what did the
    32	operator's GUI see at time T?". If the broker had a reading the
    33	SQLite did not, the operator's last-observed state diverges from the
    34	durable record — that's the failure mode this invariant rules out.
    35	
    36	## Implementation
    37	
    38	`Scheduler._process_readings()` calls writer first, then publishers.
    39	The order is unconditional and not switchable — there is no
    40	"performance mode" override.
    41	
    42	`SQLiteWriter` uses WAL mode. Engine startup verifies WAL is actually
    43	on:
    44	
    45	```python
    46	if pragma_journal_mode != 'wal':
    47	    raise RuntimeError("PRAGMA journal_mode=WAL did not apply")
    48	```
    49	
    50	(Phase 2d invariant 14 — "WAL mode verification".)
    51	
    52	> **Durability caveat.** SQLite uses `synchronous=NORMAL` by default
    53	> in WAL mode, which can lose roughly the last ~1 s of writes on
    54	> abrupt power loss (see source comments at
    55	> `src/cryodaq/storage/sqlite_writer.py:256`). Production lab
    56	> deployment expects either UPS coverage or `CRYODAQ_SQLITE_SYNC=FULL`
    57	> environment override; see Phase 2d C.3 deferral
    58	> ([[60 Roadmap/F-table backlog]] / `PROJECT_STATUS.md`).
    59	
    60	## GUI latency tradeoff
    61	
    62	The cost is the SQLite `INSERT` time per poll cycle on the engine
    63	loop's hot path. Measured cost: a few ms per batch under WAL on
    64	spinning disk; sub-ms on SSD. Operator-perceived latency is the
    65	LakeShore poll interval (2 s) anyway, so the SQLite write does not
    66	dominate.
    67	
    68	GUI-side caching mitigates per-tick latency: the dashboard widgets
    69	hold local rolling history (`channel_buffer.py`). But all that data
    70	ultimately came from the broker, which came from a committed write.
    71	
    72	## Crash recovery and atomic sidecars
    73	
    74	Persistence-first is part of a wider fail-closed pattern (Phase 2d
    75	invariants):
    76	
    77	- **Atomic file writes** (`core/atomic_write.py`) for experiment
    78	  metadata sidecars and calibration index/curve files. `os.replace()`
    79	  is the durability primitive.
    80	- **Calibration KRDG+SRDG persist in one transaction per poll cycle.**
    81	  State mutation deferred to `on_srdg_persisted` so a write failure
    82	  does not leave `t_min`/`t_max` diverged from the actual persisted
    83	  data (Jules Round 2 Q3). See [[10 Subsystems/Calibration v2]].
    84	- **Cancellation shielding** on post-fault paths (Phase 2d):
    85	  `emergency_off`, `fault_log_callback` (BEFORE optional broker
    86	  publish), `_ensure_output_off` in `_safe_off`.
    87	- **OVERRANGE / UNDERRANGE persist** as `±inf` in REAL SQLite columns;
    88	  NaN-valued statuses (SENSOR_ERROR / TIMEOUT) are filtered out
    89	  before write because SQLite treats NaN as NULL (Phase 2d
    90	  Codex finding).
    91	
    92	## Daily rotation
    93	
    94	`SQLiteWriter` rotates to a new `data_YYYY-MM-DD.db` file at midnight.
    95	Old files are read-only with respect to the writer. Replay
    96	(`storage/replay.py`) reads any of them.
    97	
    98	## What this is NOT
    99	
   100	- **Not synchronous block.** The publisher tasks return as soon as
   101	  the writer call returns; they don't wait for any subscriber.
   102	- **Not a transactional barrier across drivers.** Two drivers polling
   103	  in parallel each enforce ordering individually; there is no
   104	  cross-driver "all-or-nothing" semantics.
   105	- **Not write-replicated.** A single SQLite per day; backup is via
   106	  external file copy or the optional Parquet cold rotation (F17 in
   107	  [[60 Roadmap/F-table backlog]]).
   108	
   109	## See also
   110	
   111	- [[40 Decisions/ADR-001 Persistence-first invariant]] — the synthesized
   112	  ADR for this rule
   113	- [[10 Subsystems/Safety FSM]] — cancellation shielding details
   114	- [[10 Subsystems/Calibration v2]] — KRDG+SRDG one-transaction rule

===== /Users/vladimir/Vault/CryoDAQ/10 Subsystems/Plugin architecture.md =====
     1	---
     2	source: src/cryodaq/analytics/base_plugin.py; analytics/plugin_loader.py; config/plugins.yaml
     3	last_synced: 2026-04-26
     4	status: synthesized
     5	---
     6	
     7	# Plugin architecture
     8	
     9	Hot-reloadable analytics SDK for derived metrics
    10	(`R_thermal`, `cooldown_eta_s`, custom user metrics).
    11	
    12	## Two-class API
    13	
    14	```python
    15	class AnalyticsPlugin(ABC):
    16	    plugin_id: str
    17	
    18	    @abstractmethod
    19	    async def process(self, readings: list[Reading]) -> list[DerivedMetric]: ...
    20	
    21	    def configure(self, config: dict[str, Any]) -> None: ...
    22	```
    23	
    24	`DerivedMetric` is a frozen dataclass with `timestamp`, `plugin_id`,
    25	`metric`, `value`, `unit`, `metadata`. `DerivedMetric.now(...)` is
    26	a factory that auto-stamps UTC.
    27	
    28	A minimal plugin:
    29	
    30	```python
    31	class MyPlugin(AnalyticsPlugin):
    32	    async def process(self, readings):
    33	        return [DerivedMetric.now(self.plugin_id, "my_metric", 42.0, "arb")]
    34	```
    35	
    36	## PluginPipeline lifecycle
    37	
    38	`PluginPipeline` (`analytics/plugin_loader.py`):
    39	
    40	1. `start()` — subscribe to `DataBroker` as `plugin_pipeline`,
    41	   `glob("*.py")` over `plugins_dir`, load each via
    42	   `importlib.util.spec_from_file_location` + `exec_module`, find
    43	   the first concrete `AnalyticsPlugin` subclass, optionally apply
    44	   YAML config (sibling `<plugin_id>.yaml`), register.
    45	2. `_process_loop` — every `batch_interval_s` (default 1 s), drain
    46	   the queue (max `_MAX_BATCH_SIZE = 500` readings per batch), call
    47	   each plugin's `process()`, publish returned `DerivedMetric`s back
    48	   into the broker as synthetic `Reading`s.
    49	3. `_watch_loop` — polls `_WATCH_INTERVAL_S = 5.0` s on file mtime;
    50	   reloads modified plugins, loads new files, removes deleted ones.
    51	4. `stop()` — cancels both tasks, unsubscribes.
    52	
    53	`PluginPipeline.start()` loads every `*.py` in `plugins_dir`
    54	unconditionally; the `config/plugins.yaml` `enabled` flag is for
    55	shipped analytics modules (sensor_diagnostics, vacuum_trend) wired
    56	elsewhere, not a gate on filesystem plugin loading.
    57	
    58	## Exception isolation
    59	
    60	A plugin throwing inside `process()` is caught at the pipeline
    61	boundary, logged as ERROR, and that batch is dropped for that plugin
    62	only. Other plugins keep running. This is the rebuild after the
    63	original direct-import architecture (which would crash the engine
    64	when a plugin threw — see [[30 Investigations/Plugin isolation rebuild]]).
    65	
    66	`_load_plugin()` also wraps the entire load attempt in a try/except;
    67	a malformed file logs and is skipped, not failed.
    68	
    69	## Hot reload semantics
    70	
    71	- Add a new `.py` to `plugins/` → loaded within ~5 s.
    72	- Modify a plugin → unload + reload within ~5 s of mtime change.
    73	- Delete a plugin → removed within ~5 s.
    74	
    75	5 s mtime polling is intentional — `inotify`/`FSEvents` would be
    76	faster but add a platform dependency for marginal benefit.
    77	
    78	## Plugin data flow
    79	
    80	```text
    81	DataBroker  ─subscribe─►  PluginPipeline._queue
    82	                          (asyncio.Queue[Reading])
    83	                                │
    84	                                ▼
    85	                          _process_loop:
    86	                            batch ≤ 500 readings
    87	                            ├─► plugin1.process()  ──► DerivedMetric[]
    88	                            ├─► plugin2.process()  ──► DerivedMetric[]
    89	                            └─► ...
    90	                                │
    91	                                ▼
    92	                          publish each DerivedMetric
    93	                          back into DataBroker as Reading
    94	```
    95	
    96	The "publish back as Reading" step means **live broker subscribers**
    97	— GUI, web, ZMQ, alarm, downstream plugins — treat derived metrics
    98	uniformly with raw readings. Note: `SQLiteWriter` runs in immediate
    99	mode from `Scheduler` (not as a broker subscriber) so synthetic
   100	plugin metrics are NOT persisted via this path. Persisting plugin
   101	output is a future wiring task.
   102	
   103	## Configuration
   104	
   105	`config/plugins.yaml` carries feature flags for shipped analytics
   106	modules (independent from filesystem plugin loading):
   107	
   108	- `sensor_diagnostics` — MAD / correlation health scoring
   109	  (numpy exception per `CLAUDE.md`). `enabled: true` in shipped
   110	  config.
   111	- `vacuum_trend` — BIC-selected pump-down extrapolation. `enabled: true`
   112	  in shipped config.
   113	- (cooldown predictor lives outside the plugin pipeline since it
   114	  needs orchestration with `core/cooldown_service.py`.)
   115	
   116	The `plugins_dir` filesystem layer is independent: any `*.py` in
   117	the configured plugins directory is loaded by `PluginPipeline.start()`
   118	on engine launch; operator-authored plugins live there.
   119	
   120	## See also
   121	
   122	- [[20 Drivers/Thyracont VSP63D]] — produces the pressure stream the
   123	  `vacuum_trend` plugin consumes
   124	
   125	## Related notes
   126	
   127	- [[30 Investigations/Plugin isolation rebuild]] — why exception
   128	  isolation is non-negotiable
   129	- [[40 Decisions/ADR-003 Plugin isolation via ABC]] — synthesized
   130	  rationale
   131	- [[60 Roadmap/F-table backlog]] — F16 (plugin SDK + examples)

===== /Users/vladimir/Vault/CryoDAQ/10 Subsystems/Safety FSM.md =====
     1	---
     2	source: src/cryodaq/core/safety_manager.py; CLAUDE.md "Архитектура safety"; PROJECT_STATUS.md "Аппаратные / рантайм инварианты"; config/safety.yaml
     3	last_synced: 2026-04-26
     4	status: synthesized
     5	---
     6	
     7	# Safety FSM
     8	
     9	`SafetyManager` is the single authority for source-on/off decisions in
    10	the engine. Source OFF is the default; running requires continuous
    11	proof of health.
    12	
    13	## Problem solved
    14	
    15	Before `SafetyManager`, source-on/off authority was distributed across
    16	interlocks, alarm callbacks, and the GUI. Two failure modes followed:
    17	
    18	1. Race conditions between subsystems firing emergency-off in different
    19	   orders during a fault cascade.
    20	2. No single place where "is it safe to run right now?" had a defensible
    21	   answer at any moment.
    22	
    23	`SafetyManager` collapses authority into a single FSM, with a single
    24	asyncio lock (`_cmd_lock`) serializing `_active_sources` mutations
    25	across REQ clients (GUI subprocess + web dashboard + future operator
    26	CLI). See `safety_manager.py:130`.
    27	
    28	## Six-state FSM
    29	
    30	```text
    31	SAFE_OFF ──────► READY ──────► RUN_PERMITTED ──────► RUNNING
    32	   ▲              ▲                                     │
    33	   │              │                                     │
    34	   └─ MANUAL_RECOVERY ◄──── FAULT_LATCHED ◄────────────┘
    35	                  (acknowledge_fault)    (any fault while RUNNING)
    36	```
    37	
    38	- **SAFE_OFF** — default. No source active. Preconditions may not be met.
    39	- **READY** — preconditions met (Keithley present, critical channels
    40	  fresh, no active interlock). Operator may request a run.
    41	- **RUN_PERMITTED** — operator requested run; manager has gated through
    42	  preconditions; source-on transition pending. Active monitoring
    43	  (stale, rate, heartbeat) is armed in this state.
    44	- **RUNNING** — source active. Active monitoring continues.
    45	- **FAULT_LATCHED** — entered on any fault while RUN_PERMITTED or
    46	  RUNNING. Source forced OFF. No automatic recovery. Re-entry guard
    47	  returns early on concurrent `_fault()` calls (added 2026-04-17).
    48	- **MANUAL_RECOVERY** — entered after `acknowledge_fault()`. Returns to
    49	  READY when preconditions restore.
    50	
    51	`request_run()` may skip `READY` and go directly toward `RUNNING`
    52	when all preconditions already hold, but it still records the
    53	`RUN_PERMITTED` step on the way (`safety_manager.py:314-321 → 366-370`).
    54	
    55	## Fail-on-silence
    56	
    57	`SafetyManager` consumes the `SafetyBroker` (dedicated channel,
    58	`overflow=FAULT`). Stale data — no reading on a critical channel for
    59	`stale_timeout_s` (default 10 s) — fires `_fault("stale data")`.
    60	Active monitoring runs in **`RUN_PERMITTED` and `RUNNING`** (not
    61	`RUNNING` only) so a stuck `start_source()` cannot silently disable
    62	the checks (`safety_manager.py:884`). Outside those two states stale
    63	data blocks readiness via preconditions, not via fault.
    64	
    65	## Rate limit
    66	
    67	`dT/dt` is computed by [[_meta/glossary#FSM|`RateEstimator`]]
    68	(`window_s=120.0`, `min_points=60` after Phase 2c CC I.3). When any
    69	critical-channel rate exceeds `max_dT_dt_K_per_min` (default 5 K/min,
    70	configured in `safety.yaml`), `_fault()` fires.
    71	
    72	> Note: 5 K/min is the **configurable default**, not a hard-coded
    73	> invariant — production tuning is allowed.
    74	
    75	`min_points=60` over the `window_s=120 s` window means at least 60
    76	critical-channel readings must have accumulated within the last 2 min
    77	before the rate estimator returns a non-`None` rate; under the
    78	default 2 s LakeShore poll cadence (`config/instruments.yaml`) that's
    79	~120 s of arrivals, matching the window length.
    80	
    81	## Crash-recovery guard at Keithley connect
    82	
    83	`Keithley2604B.connect()` forces `OUTPUT_OFF` on both SMU channels
    84	before assuming control. Best-effort: if force-OFF fails, logs
    85	CRITICAL and continues (no crash, but the safety guarantee weakens).
    86	Documented in [[20 Drivers/Keithley 2604B]].
    87	
    88	## Cancellation shielding
    89	
    90	Phase 2d added `asyncio.shield()` around the post-fault sequence:
    91	
    92	- `emergency_off`
    93	- `fault_log_callback` (ordered BEFORE optional broker publish — Jules
    94	  R2 fix; callback after publish would have allowed an escape path)
    95	- `_ensure_output_off` in `_safe_off`
    96	
    97	These survive task cancellation during a fault cascade, so a
    98	post-mortem log entry is always written even if the engine is being
    99	torn down.
   100	
   101	## Re-entry guard
   102	
   103	A `_fault()` re-entry guard added 2026-04-17 (`A1 safety audit
   104	eb267c4`):
   105	
   106	```python
   107	if self._state == SafetyState.FAULT_LATCHED:
   108	    return  # already faulted; do not overwrite reason or duplicate events
   109	```
   110	
   111	Prevents concurrent `_fault()` calls (e.g. multiple critical-channel
   112	violations in the same poll cycle) from clobbering `_fault_reason`,
   113	emitting duplicate events, or re-firing `emergency_off`.
   114	
   115	## Fail-closed config
   116	
   117	`load_config()` raises `SafetyConfigError` (distinct class for
   118	clean-exit recognition) when:
   119	
   120	- `safety.yaml` not found at the configured path
   121	- file is malformed (not a mapping)
   122	- `critical_channels` is missing, not a list, or empty
   123	- any pattern fails to compile
   124	
   125	Engine exits with code 2; no auto-restart. Same fail-closed pattern
   126	applies to `alarms_v3.yaml`, `interlocks.yaml`, `housekeeping.yaml`,
   127	`channels.yaml`.
   128	
   129	## What is NOT here
   130	
   131	- **No firmware TSP watchdog.** P=const regulation is host-side in
   132	  `keithley_2604b.py`; the `tsp/p_const.lua` draft is **not loaded**
   133	  on the device. Phase 3 plan, requires hardware verification.
   134	- **No GUI-side authority.** GUI is read-only with respect to safety
   135	  state. Operator commands flow as REQ → REP and the FSM is the
   136	  single decision point.
   137	- **No automatic recovery from FAULT_LATCHED.** Operator
   138	  `acknowledge_fault()` is required.
   139	
   140	## See also
   141	
   142	- [[10 Subsystems/Persistence-first]] — readings reach SafetyBroker
   143	  AFTER SQLite commit
   144	- [[10 Subsystems/Alarm engine v2]] — separate from safety FSM;
   145	  operator-attention level, not source-control authority
   146	- [[20 Drivers/Keithley 2604B]] — crash-recovery guard implementation
   147	- [[40 Decisions/ADR-001 Persistence-first invariant]] — same
   148	  fail-closed-by-default ethos

===== /Users/vladimir/Vault/CryoDAQ/10 Subsystems/ZMQ bridge.md =====
     1	---
     2	source: src/cryodaq/core/zmq_bridge.py; src/cryodaq/core/zmq_subprocess.py; docs/bug_B1_zmq_idle_death_handoff.md; CHANGELOG IPC/REP hardening; ROADMAP "Known broken"
     3	last_synced: 2026-04-26
     4	status: synthesized
     5	---
     6	
     7	# ZMQ bridge
     8	
     9	The ZMQ bridge is the engine ↔ GUI IPC layer. It carries two
    10	independent channels and lives partly in the engine (PUB / REP
    11	sockets) and partly in a dedicated GUI-side subprocess that the GUI
    12	can survive losing.
    13	
    14	## Topology
    15	
    16	| Channel | Pattern | Address | Format | Purpose |
    17	|---|---|---|---|---|
    18	| Data plane | PUB / SUB | `tcp://127.0.0.1:5555` (default; `ipc://` experiment in IV.7) | msgpack | Continuous reading stream + alarm events + safety state |
    19	| Command plane | REP / REQ | `tcp://127.0.0.1:5556` | JSON | Operator commands, status queries |
    20	
    21	Topic for data plane is `b"readings"`. The engine PUBs are owned by
    22	`ZMQPublisher` + `ZMQCommandServer` (`zmq_bridge.py`). Connection
    23	order matters: SUB must `connect()` BEFORE `subscribe()`. The
    24	inverse pattern produced zero received messages on macOS Python 3.14
    25	+ pyzmq 25 (documented at `zmq_subprocess.py:97`).
    26	
    27	## Subprocess isolation (GUI side)
    28	
    29	The GUI process never imports `zmq` directly. Instead, `mp.Process`
    30	spawns `zmq_bridge_main()` (`zmq_subprocess.py:56`), which owns ALL
    31	ZMQ sockets on the GUI side and communicates with the GUI main process
    32	through `mp.Queue` (data, cmd, reply). Rationale: libzmq
    33	`signaler.cpp` assertion crash on Windows takes down only the
    34	subprocess; the GUI itself survives.
    35	
    36	Two threads inside the subprocess:
    37	
    38	- `sub_drain_loop` — owns SUB socket. Drains readings; emits
    39	  heartbeat every 5 s into `data_queue` so the GUI can verify the
    40	  *data path* is alive (not just that the subprocess exists).
    41	- `cmd_forward_loop` — owns REQ socket. Pulls commands from
    42	  `cmd_queue`, sends, awaits reply with `RCVTIMEO=35s`.
    43	
    44	## Per-command tiered handler timeouts (IV.3 Finding 7)
    45	
    46	Engine REP wraps each command handler in `asyncio.wait_for(timeout=
    47	_timeout_for(cmd))` (`zmq_bridge.py:60`):
    48	
    49	- Fast envelope **2.0 s** for status polls.
    50	- Slow envelope **30.0 s** for stateful operations
    51	  (`experiment_finalize`, `experiment_create`, `experiment_abort`,
    52	  `calibration_curve_import/export`, `calibration_v2_fit/extract`,
    53	  etc.).
    54	
    55	Handlers that exceed the envelope return `{"ok": False, "error":
    56	"handler timeout"}` rather than silent exception — REP socket
    57	state-machine sensitivity demands a paired send for every recv.
    58	
    59	## Bind retry (Phase 2b H.4)
    60	
    61	`_bind_with_retry()` (`zmq_bridge.py:84`) retries on `EADDRINUSE`
    62	with exponential backoff (`0.5 s → 10 s`, max 10 attempts). On
    63	Windows a socket from a SIGKILL'd engine can hold the port for up
    64	to 240 s (TIME_WAIT). Caller must set `LINGER=0` BEFORE calling, or
    65	`close()` will hold the address even after retry succeeds.
    66	
    67	## IV.6 ephemeral REQ + watchdog (`be51a24`, 2026-04-20)
    68	
    69	Codex's revised root-cause hypothesis for B1 was that one long-lived
    70	REQ socket in `cmd_forward_loop()` accumulates state and becomes
    71	unrecoverable. IV.6 implemented the canonical ZeroMQ Guide ch.4
    72	"poll / timeout / close / reopen" pattern:
    73	
    74	- Per-command ephemeral REQ socket (`_new_req_socket()` per send).
    75	- `REQ_RELAXED` and `REQ_CORRELATE` removed (unnecessary with
    76	  ephemeral sockets).
    77	- Launcher-side `command_channel_stalled()` watchdog in
    78	  `_poll_bridge_data` — restarts the bridge subprocess if the cmd
    79	  plane is stalled while data plane stays alive.
    80	- `TCP_KEEPALIVE` reverted on command + PUB paths (kept on
    81	  `sub_drain_loop` SUB as orthogonal safeguard).
    82	
    83	**Outcome:** code stays in master as defense-in-depth and matches
    84	canonical reliable req-reply pattern, **but B1 still reproduces** at
    85	~80 s uptime. Codex's shared-REQ-state hypothesis was empirically
    86	falsified. See [[30 Investigations/IV.6 cmd plane hardening]] and
    87	[[30 Investigations/Codex H2 wrong hypothesis]].
    88	
    89	## Watchdog cooldown hotfix (2026-04-20 evening)
    90	
    91	The IV.6 watchdog had a regression: `_last_cmd_timeout` persisted
    92	across watchdog-triggered subprocess restart, so the fresh
    93	subprocess immediately saw a stale timeout signal on the next
    94	poll and was restarted again — restart storm (30–40
    95	restarts/minute observed on Ubuntu lab PC). Hotfix added 60 s
    96	cooldown between command-watchdog restarts via
    97	`_last_cmd_watchdog_restart` timestamp + missing `return` after
    98	restart so no further checks run in the same poll cycle. Does NOT
    99	resolve B1; only prevents pathological amplification.
   100	
   101	## IV.7 ipc:// transport experiment
   102	
   103	Branch `experiment/iv7-ipc-transport` switches the loopback default
   104	to Unix-domain sockets (`ipc:///tmp/cryodaq-pub.sock`,
   105	`ipc:///tmp/cryodaq-cmd.sock`) on macOS / Linux; Windows retains
   106	`tcp://`. Original hypothesis: TCP-loopback layer is the remaining
   107	culprit. Post-experiment: shared-REQ-state (H2) and transport
   108	misattribution (H3) have been ruled out, but H4 (pyzmq /
   109	Python 3.14 asyncio integration) and H5 (engine REP state machine)
   110	remain viable.
   111	
   112	Outcome 2026-04-23 was originally a runtime failure attributed to
   113	the transport. [[40 Decisions/2026-04-24-b2b4fb5-investigation|H3]]
   114	confirmed the failure was the b2b4fb5 hardening probe racing the
   115	ipc:// bind, NOT the transport. Repaired via R1 (bounded-backoff
   116	retry). After the repair lands, ipc:// runs normally for ~80 s
   117	then B1 fires anyway — IV.7 does not close B1, only shifts the
   118	failure surface.
   119	
   120	## Status (2026-04-26)
   121	
   122	- B1 ZMQ idle-death — still OPEN. Blocks `v0.34.0` tag. See
   123	  [[30 Investigations/B1 ZMQ idle-death]].
   124	- IV.6 partial mitigation — landed, defense-in-depth.
   125	- IV.7 ipc:// — viable transport, but does not close B1. Next
   126	  hypotheses: H4 (pyzmq 25.x + Python 3.14 asyncio integration),
   127	  H5 (engine REP state machine).
   128	
   129	## See also
   130	
   131	- [[30 Investigations/B1 ZMQ idle-death]]
   132	- [[30 Investigations/IV.6 cmd plane hardening]]
   133	- [[30 Investigations/b2b4fb5 hardening race]]
   134	- [[40 Decisions/ADR-002 R1 bounded-backoff probe retry]]

===== /Users/vladimir/Vault/CryoDAQ/10 Subsystems/_index.md =====
     1	---
     2	source: skeleton stub
     3	last_synced: 2026-04-26
     4	status: index
     5	---
     6	
     7	# 10 Subsystems
     8	
     9	Per-subsystem narrative explainers. Cover what each subsystem solves,
    10	how it's structured, and what it explicitly is NOT.
    11	
    12	- [[10 Subsystems/Safety FSM]]
    13	- [[10 Subsystems/ZMQ bridge]]
    14	- [[10 Subsystems/Persistence-first]]
    15	- [[10 Subsystems/Calibration v2]]
    16	- [[10 Subsystems/Alarm engine v2]]
    17	- [[10 Subsystems/Plugin architecture]]
    18	
    19	<!-- TODO: add notes for engine startup sequence, GUI shell, web dashboard if scope expands -->

codex
I’ve finished the first pass through Overview and Subsystems. A few candidate issues need source confirmation rather than guesswork, especially around UI/design-system counts, alarm channel-group claims, and ZMQ subprocess ownership.
exec
/opt/homebrew/bin/bash -lc "for f in /Users/vladimir/Vault/CryoDAQ/20\\ Drivers/*.md; do printf '\\n===== %s =====\\n' \""'$f"; nl -ba "$f"; done' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:

===== /Users/vladimir/Vault/CryoDAQ/20 Drivers/Keithley 2604B.md =====
     1	---
     2	source: src/cryodaq/drivers/instruments/keithley_2604b.py; drivers/transport/usbtmc.py; core/smu_channel.py; CLAUDE.md "Архитектура safety" + "Ключевые правила"; tsp/p_const.lua
     3	last_synced: 2026-04-26
     4	status: synthesized
     5	---
     6	
     7	# Keithley 2604B
     8	
     9	Dual-SMU source-meter. Authority over electrical power source-on/off
    10	delegated through `SafetyManager`; the driver itself does not decide
    11	when to source.
    12	
    13	## Interface and channels
    14	
    15	- **Transport:** USB-TMC (`drivers/transport/usbtmc.py` via PyVISA).
    16	- **Default poll interval:** 1.0 s.
    17	- **Channels:** `smua` and `smub` (dual-SMU). Each channel can be
    18	  controlled independently; `emergency_off(channel=None)` covers
    19	  both. There is **no single-name "combined" channel** —
    20	  `core/smu_channel.py` types the channel as
    21	  `Literal["smua", "smub"]`, and `normalize_smu_channel()` rejects
    22	  anything else. The "smua + smub" wording in operator docs refers
    23	  to running both channels concurrently with independent setpoints.
    24	
    25	Per-channel reading kinds: `voltage` (V), `current` (A),
    26	`resistance` (Ohm), `power` (W). All four published per poll cycle
    27	with channel naming `<instrument_id>/<smu>/<kind>`.
    28	
    29	## Host-side P=const regulation
    30	
    31	```python
    32	# tsp/p_const.lua — DRAFT, NOT LOADED on the device.
    33	# P=const feedback runs host-side in keithley_2604b.read_channels().
    34	```
    35	
    36	Per `CLAUDE.md` "Ключевые правила": no TSP scripts are uploaded to
    37	the instrument; the VISA bus stays free for queries. The host loop:
    38	
    39	1. Read V and I from each active SMU.
    40	2. Compute `R = V/I` (skipped when `|I| < _I_MIN_A = 1e-7` to avoid
    41	   noise-dominated divisions).
    42	3. Compute `target_v = sqrt(P_target × R)` for the requested
    43	   `p_target`.
    44	4. Apply slew-rate limit `MAX_DELTA_V_PER_STEP = 0.5 V` per cycle so
    45	   `target_v` cannot jump from 0 to `V_compliance` in one step on an
    46	   abrupt resistance change (superconducting transition, wire break).
    47	5. Set new V; let next cycle re-measure.
    48	
    49	`_COMPLIANCE_NOTIFY_THRESHOLD = 10` consecutive compliance cycles
    50	flips a per-channel `compliance_persistent()` flag and logs warnings;
    51	it sets metadata on subsequent readings but does NOT directly notify
    52	`SafetyManager` in the current code surface — the flag is a hook for
    53	future safety integration. See `keithley_2604b.py:170` and `:350`.
    54	
    55	## Crash-recovery guard at connect
    56	
    57	`Keithley2604B.connect()` forces `OUTPUT_OFF` on both SMU channels
    58	before assuming control:
    59	
    60	> Best-effort: if force-OFF fails, logs CRITICAL and continues — not
    61	> guaranteed.
    62	
    63	The intent: a previous engine crash that left the source ON cannot
    64	silently keep being ON when the new engine attaches. See `CLAUDE.md`
    65	safety section ("Crash-recovery guard").
    66	
    67	## Disconnect calls emergency_off first
    68	
    69	Per `CLAUDE.md` "Ключевые правила": `Keithley disconnect must call
    70	emergency off first.` `disconnect()` runs `emergency_off()` on each
    71	active SMU before closing transport, ensuring the operator's stop
    72	button doesn't leave the source ON.
    73	
    74	## NI-VISA `\x00` quirk
    75	
    76	VISA resource strings on Windows / NI-VISA contain `\x00` per spec
    77	(e.g. `USB0::0x05E6::0x2604::04052028::INSTR`). python-docx rejects
    78	those as XML 1.0-illegal control chars when embedded in auto-reports.
    79	Fixed `74dbbc7` (2026-04-20) via `src/cryodaq/utils/xml_safe.py`
    80	sanitizer applied at all `add_paragraph()` / `cell.text` sites in
    81	`reporting/sections.py`. Logger upgraded from `log.warning` to
    82	`log.exception` so future report-gen failures carry tracebacks.
    83	
    84	## Mock mode
    85	
    86	`_mock_r_of_t()` produces a realistic R(T) curve `R = R0 × (1 + α×T)`
    87	with `_MOCK_R0=100`, `_MOCK_T0=300`, `_MOCK_ALPHA=0.0033`,
    88	`_MOCK_COOLING_RATE=0.1`, `_MOCK_SMUB_FACTOR=0.7`. Sufficient for
    89	engine smoke and GUI exercise.
    90	
    91	## See also
    92	
    93	- [[10 Subsystems/Safety FSM]] — single source-on/off authority
    94	- [[20 Drivers/LakeShore 218S]]
    95	- [[20 Drivers/Thyracont VSP63D]]
    96	- `tsp/p_const.lua` — TSP supervisor draft (Phase 3, hardware-verify)

===== /Users/vladimir/Vault/CryoDAQ/20 Drivers/LakeShore 218S.md =====
     1	---
     2	source: src/cryodaq/drivers/instruments/lakeshore_218s.py; drivers/transport/gpib.py; CLAUDE.md "Драйверы"; config/instruments.yaml
     3	last_synced: 2026-04-26
     4	status: synthesized
     5	---
     6	
     7	# LakeShore 218S
     8	
     9	8-channel cryogenic temperature monitor. Read-only with respect to
    10	the system being measured (no source authority).
    11	
    12	## Interface and channels
    13	
    14	- **Transport:** GPIB (`drivers/transport/gpib.py` via PyVISA).
    15	- **Default poll interval:** 2.0 s (`config/instruments.yaml`).
    16	- **Daisy-chain:** three controllers in production
    17	  (`LS218_1` GPIB::12, `LS218_2` GPIB::14, `LS218_3` GPIB::16).
    18	  Combined channel count: 24, named Т1..Т24 (Cyrillic Т prefix).
    19	- **Driver class:** `LakeShore218S` — extends `InstrumentDriver` ABC.
    20	
    21	Per-channel labels are loaded from
    22	`config/instruments.yaml::instruments[*].channels` and used as the
    23	canonical channel names everywhere downstream.
    24	
    25	## Reading kinds
    26	
    27	| Method | Command | Output |
    28	|---|---|---|
    29	| `read_channels()` | `KRDG?` (or `KRDG? <ch>` per-channel) | calibrated kelvin reading from the LakeShore controller (uses on-device calibration table) |
    30	| `read_srdg_channels()` | `SRDG?` | sensor raw value (Ohm / V depending on input type), pre-calibration |
    31	| `read_calibration_pair()` | `KRDG? <ch>` + `SRDG? <ch>` | one (kelvin, raw) pair for calibration v2 acquisition |
    32	| `read_status()` | `RDGST?` | per-channel status bitmask (overrange / underrange / sensor-error) |
    33	
    34	KRDG and SRDG are surfaced as separate channels in the broker so
    35	calibration acquisition (`CalibrationAcquisitionService`) can pair
    36	them. See [[10 Subsystems/Calibration v2]].
    37	
    38	## IDN validation with retry-after-clear (Phase 2c Codex F.1)
    39	
    40	`connect()` validates `*IDN?` against expected vendor before assuming
    41	control. Earlier behavior (warn-and-proceed) allowed silent
    42	mis-routing — `KRDG?` would return numbers from the wrong instrument
    43	without anyone noticing. Current behavior: retry once after `*CLS`,
    44	then fail hard if IDN still doesn't match.
    45	
    46	## Per-channel runtime calibration (v2)
    47	
    48	`LakeShore218S` ships per-channel runtime routing for calibration v2:
    49	
    50	- Global mode `on/off`: enable / disable per-channel calibration
    51	  application across all channels.
    52	- Per-channel policy `inherit | off | on`: overrides the global mode.
    53	- Conservative fallback: if curve / assignment / SRDG missing OR
    54	  computation throws, fall back to KRDG (controller calibrated reading)
    55	  and log the reason once per `(channel, reason)` to avoid log spam
    56	  (`_runtime_warning_cache`).
    57	
    58	`_use_per_channel_krdg` and `_use_per_channel_srdg` are boolean
    59	fallback flags. The companion `_krdg0_fail_count` /
    60	`_srdg0_fail_count` and `_krdg_batch_retry_interval_s` /
    61	`_srdg_batch_retry_interval_s` (default 60 s each) drive when the
    62	driver switches to per-channel form and when it retries the batch
    63	form.
    64	
    65	## Mock mode
    66	
    67	`mock=True` produces realistic signals via `_mock_sensor_unit(t)`
    68	(`temp` → ohms approximation `1600/(T+15) + 0.08`) over a tuple of
    69	realistic base temperatures (4.2 K, 4.8 K, 77 K, 77.5 K, 4.5 K, 4.1 K,
    70	3.9 K, 300 K). Useful for engine smoke tests and GUI development.
    71	
    72	## Notable quirks
    73	
    74	- **GPIB bus serialization.** Multiple LakeShores on the same bus
    75	  (`GPIB0::*`) cannot be polled in parallel — NI GPIB-USB-HS does
    76	  not tolerate concurrent access even with `asyncio.Lock` +
    77	  `run_in_executor`. `Scheduler` groups same-bus drivers into one
    78	  sequential task. See `core/scheduler.py:67`.
    79	- **`OVERRANGE`/`UNDERRANGE` valid as ±inf.** `RDGST?` returns
    80	  status codes; the driver maps them to `ChannelStatus` enum.
    81	  OVERRANGE/UNDERRANGE persist as `±inf` in REAL SQLite columns;
    82	  SENSOR_ERROR/TIMEOUT (NaN) are filtered before write (Phase 2d
    83	  invariant 10).
    84	- **Cyrillic Т prefix homoglyph hazard.** Per-channel labels use
    85	  Cyrillic Т (U+0422). LLMs occasionally produce Latin "T" in
    86	  generated config; tests can pass while the channel never matches
    87	  any rule. See [[30 Investigations/Cyrillic homoglyph in alarm config]].
    88	
    89	## See also
    90	
    91	- [[20 Drivers/Keithley 2604B]]
    92	- [[20 Drivers/Thyracont VSP63D]]
    93	- [[10 Subsystems/Calibration v2]]
    94	- [[10 Subsystems/Safety FSM]] — Т1..Т8 are critical channels for
    95	  rate-limit and overheat interlock

===== /Users/vladimir/Vault/CryoDAQ/20 Drivers/Thyracont VSP63D.md =====
     1	---
     2	source: src/cryodaq/drivers/instruments/thyracont_vsp63d.py; drivers/transport/serial.py; CLAUDE.md "Драйверы"; CHANGELOG aabd75f validate_checksum; CHANGELOG 2026-04-20 ModemManager
     3	last_synced: 2026-04-26
     4	status: synthesized
     5	---
     6	
     7	# Thyracont VSP63D
     8	
     9	Vacuum gauge. Single pressure channel.
    10	
    11	## Interface and channels
    12	
    13	- **Transport:** RS-232 / USB-Serial (`drivers/transport/serial.py`
    14	  via `pyserial-asyncio`). Default 9600 baud.
    15	- **Default poll interval:** 2.0 s.
    16	- **Channels:** 1 — pressure (mbar).
    17	- **Driver class:** `ThyracontVSP63D` — also handles VSM77DL and
    18	  similar V1/V2-protocol siblings.
    19	
    20	## Two-protocol auto-detection
    21	
    22	```text
    23	VSP63D (default):
    24	  9600 baud
    25	  command:  "MV00\r"
    26	  response: "status,value\r"
    27	
    28	Thyracont Protocol V1 (VSM77DL family):
    29	  115200 baud
    30	  command:  "<addr>M^\r"
    31	  response: "<addr>M<6digits><checksum>\r"
    32	  6-digit value ABCDEF: pressure = (ABCD/1000) × 10^(EF − 20) mbar
    33	```
    34	
    35	`connect()` probes both. `_FALLBACK_BAUDRATES = {9600: 115200,
    36	115200: 9600}` controls the fallback once per attempt. Actual probe
    37	order in `thyracont_vsp63d.py:120`:
    38	
    39	1. Try Protocol V1 probe (`_try_v1_probe`) at the configured baudrate.
    40	2. If fail, try MV00 probe (`_try_mv00_probe`) at the configured baudrate.
    41	3. If both fail, close transport and reopen at the alternate baudrate
    42	   (per `_FALLBACK_BAUDRATES`); repeat the V1-then-MV00 sequence.
    43	4. If still nothing responds, raise.
    44	
    45	## Status map
    46	
    47	```python
    48	_STATUS_OK         = 0  → ChannelStatus.OK
    49	_STATUS_UNDERRANGE = 1  → ChannelStatus.UNDERRANGE
    50	_STATUS_OVERRANGE  = 2  → ChannelStatus.OVERRANGE
    51	_STATUS_SENSOR_ERROR = 3 → ChannelStatus.SENSOR_ERROR
    52	```
    53	
    54	OVERRANGE / UNDERRANGE persist as `±inf` per Phase 2d invariant 10
    55	(see [[10 Subsystems/Persistence-first]]).
    56	
    57	## V1 checksum quirk
    58	
    59	V1 protocol response contains a 1-character checksum at the end.
    60	`_verify_v1_checksum(response)` validates; on checksum failure the
    61	driver returns a `Reading` with `value=NaN`,
    62	`status=ChannelStatus.SENSOR_ERROR`, and checksum-failure metadata
    63	attached, rather than parsing partial garbage. The reading object
    64	still flows downstream so the safety / alarm layer can react.
    65	
    66	The checksum formula differs slightly between VSP63D and VSP206
    67	hardware (lab PC has VSP206). `validate_checksum: false` in
    68	`config/instruments.local.yaml` (Ubuntu lab PC) bypasses this check.
    69	The YAML key was previously **silently ignored** by the engine
    70	loader — driver defaulted to `True` regardless. Wiring fixed in
    71	`aabd75f` (2026-04-20). Without the fix, the operator could turn
    72	the toggle off and the engine would still strict-validate.
    73	
    74	## Probe-vs-read inconsistency (open issue)
    75	
    76	Per CHANGELOG "Open / known issues carrying into 0.34.0":
    77	
    78	> `_try_v1_probe` always succeeds; read checksum-validates. Driver
    79	> can "connect" and emit NaN forever on non-VSP63D hardware.
    80	
    81	Pending hardening fix. Intended approach: V1 probe should read at
    82	least one full message and validate checksum before reporting
    83	"connected".
    84	
    85	## Lab-PC-specific operational hazard
    86	
    87	`ModemManager` (Ubuntu) was transiently grabbing `/dev/ttyUSB0`
    88	when the Thyracont was plugged in. Disabled on the lab PC
    89	2026-04-20. Documented in CHANGELOG. Future deployments should
    90	disable `ModemManager` (or systemd-mask it) as part of the
    91	operator-PC bring-up runbook.
    92	
    93	## Mock mode
    94	
    95	`_MOCK_BASE_PRESSURE_MBAR = 1.5e-6`. Random walk around base value;
    96	realistic enough for [[10 Subsystems/Plugin architecture|`vacuum_trend`
    97	plugin]] testing and GUI plot exercise.
    98	
    99	## See also
   100	
   101	- [[20 Drivers/LakeShore 218S]]
   102	- [[20 Drivers/Keithley 2604B]]
   103	- [[10 Subsystems/Plugin architecture]] — vacuum_trend plugin lives
   104	  here
   105	- [[60 Roadmap/F-table backlog]] — F13 (vacuum leak rate estimator)

===== /Users/vladimir/Vault/CryoDAQ/20 Drivers/_index.md =====
     1	---
     2	source: skeleton stub
     3	last_synced: 2026-04-26
     4	status: index
     5	---
     6	
     7	# 20 Drivers
     8	
     9	Instrument-specific notes — interfaces, channels, protocol quirks,
    10	crash recovery, known issues.
    11	
    12	- [[20 Drivers/LakeShore 218S]]
    13	- [[20 Drivers/Keithley 2604B]]
    14	- [[20 Drivers/Thyracont VSP63D]]
    15	
    16	<!-- TODO: add transport-layer notes (gpib, serial, usbtmc) if useful -->

exec
/opt/homebrew/bin/bash -lc "for f in /Users/vladimir/Vault/CryoDAQ/30\\ Investigations/*.md; do printf '\\n===== %s =====\\n' \""'$f"; nl -ba "$f"; done' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:

===== /Users/vladimir/Vault/CryoDAQ/30 Investigations/B1 ZMQ idle-death.md =====
     1	---
     2	source: docs/bug_B1_zmq_idle_death_handoff.md; ROADMAP.md "Known broken" (B1); CHANGELOG.md (Unreleased Apr 20); decisions docs 2026-04-24
     3	last_synced: 2026-04-26
     4	status: synthesized — bug OPEN
     5	---
     6	
     7	# B1 — ZMQ command channel idle-death
     8	
     9	The single bug that blocks `v0.34.0` tag.
    10	
    11	## Symptom
    12	
    13	The GUI ↔ engine command plane (REQ on
    14	`tcp://127.0.0.1:5556`, or `ipc://` since IV.7) stops responding
    15	after some time of operation. Data plane (SUB on 5555 or
    16	`ipc:///tmp/cryodaq-pub.sock`) keeps publishing readings normally.
    17	
    18	```
    19	RAPID 5Hz   (200ms idle): 291/291 OK, 0 fails    — high rate never fails
    20	SPARSE 0.33Hz (3s idle):    9 OK, cmd #10 FAIL 35s — low rate fails
    21	RECOVER 5Hz, post-fail:     cmd #1 FAIL immediately — permanent
    22	```
    23	
    24	Once a REQ socket has timed out once, fresh REQ sockets recreated
    25	into the same context **also hang**. **Pre-IV.6 evidence** had the
    26	engine REP answering a direct in-process Python client in 0.001 s
    27	while the bridge subprocess was deep into B1, suggesting the engine
    28	itself was healthy. **Post-IV.6 evidence** is less clean: the
    29	handoff doc's addendum reports the engine REP also going silently
    30	unresponsive after ~30–90 s of bridge uptime while the asyncio
    31	loop, data plane, heartbeats, scheduler writes, and plugin ticks
    32	remain healthy. The wedge layer is unclear; H4 and H5 remain viable.
    33	
    34	| Platform | First failure |
    35	|---|---|
    36	| macOS Darwin (Python 3.14.3, pyzmq 25.x) | stochastic 4–92 s uptime |
    37	| Ubuntu 22.04 (Python 3.12.13, pyzmq 26.4.0) | exactly 120 s after subprocess start (single data point, may vary) |
    38	
    39	Real Ubuntu lab PC reproduces in `./start.sh`, not just diag tools.
    40	
    41	## Hypothesis tree
    42	
    43	| H | Hypothesis | Evidence | Status |
    44	|---|---|---|---|
    45	| H1 | macOS kernel idle reaping of loopback TCP | `tcp_keepalive_time = 7200s` on Linux, yet 120 s deterministic failure | **falsified 2026-04-20** |
    46	| H2 | Single long-lived REQ socket accumulating bad state (Codex's primary) | IV.6 implemented per-cmd ephemeral REQ; B1 still reproduces | **falsified 2026-04-20** |
    47	| H3 | b2b4fb5 hardening probe incompatible with `ipc://` | repro on revert + bind-time race confirmed | **partially confirmed** — explains 2026-04-23 IV.7 misattribution but does NOT explain B1 itself; B1 still fires after ~80 s on ipc:// |
    48	| H4 | pyzmq 25.x + Python 3.14 asyncio integration / engine REP task state under rapid REQ connect-disconnect churn | not yet tested in isolation | **untested** — D2 split-context falsification experiment scheduled |
    49	| H5 | engine REP state machine | not yet specifically probed | **untested** |
    50	
    51	## What works
    52	
    53	- Engine REP socket itself — direct Python REQ client gets 0.001 s
    54	  reply mid-failure.
    55	- Engine internals: SQLite writes (~9000/10 min), heartbeats every
    56	  30 s, plugin ticks, scheduler all stay healthy.
    57	- Raw subprocess without `ZmqBridge` wrapping (`diag_zmq_subprocess.py`)
    58	  succeeds short-term on both `fork` and `spawn` mp start methods.
    59	
    60	## What's been tried
    61	
    62	1. **`TCP_KEEPALIVE` on all four sockets** (commit `f5f9039`,
    63	   reverted on cmd path in IV.6). Partial delay of failure on macOS
    64	   only; Linux unaffected. Reverted on command + PUB paths since H1
    65	   was falsified; kept on `sub_drain_loop` SUB as orthogonal
    66	   safeguard.
    67	2. **IV.6 ephemeral REQ + cmd-channel watchdog** (`be51a24`).
    68	   Codex's H2 hypothesis. Implements ZeroMQ Guide ch.4 canonical
    69	   "poll / timeout / close / reopen" pattern. **Did not fix B1.**
    70	3. **IV.6 watchdog cooldown hotfix** — solves restart-storm
    71	   regression (30–40 restarts/min on Ubuntu) but is not a B1 fix;
    72	   produces "works ~60–120 s, one restart, works again" cycle as
    73	   workaround.
    74	4. **IV.7 ipc:// transport experiment.** Branch
    75	   `experiment/iv7-ipc-transport`. Switches loopback default to
    76	   Unix-domain sockets on macOS / Linux. ipc:// runs normally for
    77	   ~80 s then B1 fires anyway — not a transport-layer fix, but
    78	   useful as a diagnostic constant.
    79	
    80	## Diagnostics in tree
    81	
    82	`tools/diag_zmq_*.py` retained for regression after fix:
    83	
    84	- `tools/diag_zmq_subprocess.py` — subprocess alone, short.
    85	- `tools/diag_zmq_bridge.py` — full ZmqBridge 60 s soak.
    86	- `tools/diag_zmq_bridge_extended.py` — 180 s past-first-failure.
    87	- `tools/diag_zmq_idle_hypothesis.py` — rate-dependence reproducer.
    88	- `tools/diag_zmq_b1_capture.py` — canonical B1 capture CLI
    89	  (post-D4a, post-R1).
    90	- `tools/_b1_diagnostics.py` — reusable helpers (bridge_snapshot,
    91	  direct_engine_probe).
    92	
    93	`/tmp/diag_iv6_*.log` and `/tmp/engine_iv6_debug.log` preserved for
    94	architect review.
    95	
    96	## Why this still matters
    97	
    98	`v0.34.0` cannot ship while B1 reproduces — the user-visible
    99	symptom is "GUI buttons don't work after a couple of minutes; have
   100	to restart the bridge subprocess". The IV.6 watchdog cooldown
   101	provides a usable workaround (60–120 s cycle with single restart),
   102	not an acceptable production state.
   103	
   104	## Next experiments
   105	
   106	- **D2 — H4 split-context falsification** on
   107	  `experiment/iv7-ipc-transport` worktree.
   108	- If H4 / H5 both falsified: target may be lower (libzmq 4.x
   109	  loopback handling, kernel-level interaction). Would justify a
   110	  switch to a different IPC mechanism entirely (mp.Pipe, UNIX
   111	  socket without zmq, etc.).
   112	
   113	## See also
   114	
   115	- [[30 Investigations/IV.6 cmd plane hardening]]
   116	- [[30 Investigations/b2b4fb5 hardening race]]
   117	- [[30 Investigations/Codex H2 wrong hypothesis]]
   118	- [[40 Decisions/2026-04-24-b2b4fb5-investigation]]
   119	- [[40 Decisions/2026-04-24-d1-d4a-execution]]
   120	- [[10 Subsystems/ZMQ bridge]]

===== /Users/vladimir/Vault/CryoDAQ/30 Investigations/Codex H2 wrong hypothesis.md =====
     1	---
     2	source: docs/bug_B1_zmq_idle_death_handoff.md "Codex revised analysis"; CHANGELOG.md `be51a24` IV.6 partial mitigation; ROADMAP.md "IV.6 partial mitigation outcome"
     3	last_synced: 2026-04-26
     4	status: closed — adversarial review counter-example
     5	---
     6	
     7	# Codex H2 wrong hypothesis
     8	
     9	A counter-example to "Codex high reasoning is right" worth keeping
    10	visible. Pairs with [[30 Investigations/Cyrillic homoglyph in alarm config]]
    11	as a reminder that **tests > model confidence**.
    12	
    13	## Setup
    14	
    15	By 2026-04-20 afternoon, B1 had:
    16	
    17	- Reproduced 100 % on macOS, also reproduced on Ubuntu 22.04
    18	- Resisted a `TCP_KEEPALIVE` fix (commit `f5f9039`)
    19	- Architect's H1 ("idle reaping") falsified by Linux's
    20	  `tcp_keepalive_time = 7200 s` ruling out kernel-level reaping in
    21	  120 s
    22	
    23	Architect handed the evidence dossier
    24	(`docs/bug_B1_zmq_idle_death_handoff.md`) to Codex gpt-5.5/high
    25	asking for a revised root cause.
    26	
    27	## What Codex said (H2)
    28	
    29	Codex's revised root cause:
    30	
    31	> The GUI-side subprocess command plane uses one long-lived REQ
    32	> socket in `cmd_forward_loop()`. On both platforms, something
    33	> eventually pushes that single connection into a bad state — on
    34	> macOS sparse cadence triggers it faster, on Ubuntu it appears
    35	> connection-age or socket-state related rather than idle-related.
    36	> Once one REQ connection goes bad, the entire command plane
    37	> degrades because every GUI command shares it.
    38	
    39	Cited specific file:line refs to `_new_req_socket()` in
    40	`zmq_subprocess.py`. Pointed to ZeroMQ Guide ch. 4 canonical
    41	"poll / timeout / close / reopen" pattern. Recommended per-command
    42	ephemeral REQ socket as the fix. Tone confident; reasoning clean.
    43	
    44	## What we did
    45	
    46	IV.6 batch (`be51a24`) implemented the fix exactly as Codex
    47	proposed:
    48	
    49	- Per-command ephemeral REQ socket in
    50	  `zmq_subprocess.cmd_forward_loop`.
    51	- `REQ_RELAXED` and `REQ_CORRELATE` removed (unnecessary with
    52	  ephemeral sockets).
    53	- Launcher-side `command_channel_stalled()` watchdog in
    54	  `_poll_bridge_data`.
    55	- `TCP_KEEPALIVE` reverted on command + PUB paths (kept on SUB
    56	  drain as orthogonal safeguard).
    57	
    58	60/60 unit tests green; full subtree 1775/1776 (1 unrelated flaky).
    59	
    60	## What happened
    61	
    62	Post-fix diag runs reproduced B1 with structurally identical
    63	timing to pre-fix master:
    64	
    65	| Test | Result |
    66	|---|---|
    67	| `diag_zmq_idle_hypothesis.py` SPARSE_0.33HZ | cmd #8 FAIL at uptime 56 s (pre-fix: cmd #10 FAIL at ~30 s) |
    68	| `diag_zmq_bridge_extended.py` | cmd #48 FAIL at uptime 82 s, 0/3 recovery (pre-fix: cmd #28 FAIL at 92 s) |
    69	| RAPID_5HZ path | 295/295 OK — same rate-dependence pattern as before |
    70	
    71	Removing shared REQ state did NOT eliminate the failure. **H2
    72	falsified.**
    73	
    74	## Why this is the lesson
    75	
    76	Codex's reasoning was clean. The hypothesis was internally
    77	consistent with all data given to it. The fix was *good* — it
    78	implements the canonical reliable req-reply pattern, removes a
    79	brittle point in the design, and gives the launcher a real
    80	command-channel watchdog. IV.6 stays in master as defense-in-depth.
    81	
    82	But the bug remained. The model was confidently wrong in a way
    83	that only **diagnostic re-execution** could detect — not by another
    84	model's reasoning, not by closer reading of the same file:line refs
    85	Codex cited.
    86	
    87	The lesson is not "don't use Codex". The lesson is:
    88	
    89	> Confidence in a model's review does not substitute for re-running
    90	> the failing test after applying the fix. **Tests > model confidence**,
    91	> always, with no exceptions for "the reasoning looks airtight".
    92	
    93	## Where this applies in workflow
    94	
    95	- [[50 Workflow/ORCHESTRATION contract]] §4 (consultant invocation
    96	  protocol): synthesis must include "what experiment would
    97	  distinguish the proposed root cause from alternatives", and CC
    98	  must run that experiment after applying the fix.
    99	- [[50 Workflow/Multi-model consultation]] (skill): Codex's
   100	  signature signals (FAIL/PASS verdict, file:line refs, terse
   101	  critiques) are markers of *form*, not of *correctness*.
   102	- [[40 Decisions/2026-04-24-d1-d4a-execution]] §"Q4 equivalence
   103	  check": post-merge adversarial review on R1 was specifically run
   104	  *after* the fix landed, partly as discipline for not repeating
   105	  this pattern.
   106	
   107	## See also
   108	
   109	- [[30 Investigations/B1 ZMQ idle-death]] — bug is still open
   110	- [[30 Investigations/IV.6 cmd plane hardening]] — what shipped from
   111	  H2 and why it stayed
   112	- [[30 Investigations/Cyrillic homoglyph in alarm config]] — sister
   113	  story about tests passing on a thing that didn't work

===== /Users/vladimir/Vault/CryoDAQ/30 Investigations/Cyrillic homoglyph in alarm config.md =====
     1	---
     2	source: PROJECT_STATUS.md "A1 safety audit"; CLAUDE.md "Кодировка файлов"; docs/design-system/ rules; config/alarms_v3.yaml history
     3	last_synced: 2026-04-26
     4	status: closed — regression test in place
     5	---
     6	
     7	# Cyrillic Т homoglyph in alarm config
     8	
     9	A small story about a bug that tests passed.
    10	
    11	## Story
    12	
    13	`config/alarms_v3.yaml` is the YAML-driven alarm rule set
    14	([[10 Subsystems/Alarm engine v2]]). Channels in CryoDAQ are named
    15	with Cyrillic Т (U+0422) prefix — `Т1`, `Т12`, etc. — because that's
    16	the Russian convention in `config/instruments.yaml`.
    17	
    18	At some point an LLM-generated edit introduced **Latin "T"** in the
    19	rule patterns where Cyrillic "Т" was meant. The two letters render
    20	identically in most fonts; tests that exercised the alarm engine
    21	mechanics (threshold logic, hysteresis, message formatting) all
    22	passed because the engine logic was correct. The rule simply never
    23	fired against any real channel — Latin T wasn't in the channel
    24	namespace.
    25	
    26	Caught by adversarial second-model review. The fix added a
    27	regression test for the channel-prefix character class plus a
    28	Cyrillic-Т invariant in `docs/design-system/` rules.
    29	
    30	## Where the homoglyph lurks
    31	
    32	- `config/alarms_v3.yaml` rule channel patterns (this incident).
    33	- `config/interlocks.yaml::overheat_cryostat::channel_pattern` — was
    34	  fixed for Cyrillic Т earlier (commit `9feaf3e`). Current master
    35	  pattern is `Т[1-8] .*`; Т4 exclusion exists at the alarm-group
    36	  level (`alarms_v3.yaml` `uncalibrated`/`all_temp` groups omit Т4
    37	  and Т8) rather than at the interlock regex level. Tighter
    38	  `Т(1|2|3|5|6|7|8) .*` was discussed during 2026-04-20 lab work but
    39	  is not in master at the time of this build's audit.
    40	- `config/interlocks.yaml::overheat_compressor::channel_pattern` —
    41	  separate `Т12 .*` pattern; same homoglyph hazard, addressed in
    42	  the A1 audit fix.
    43	- `docs/design-system/` rules involving "мбар" vs "mbar" (similar
    44	  class — Latin `mbar` got flagged in `1c61268` CRITICAL domain
    45	  cleanup).
    46	
    47	## Why it survives ordinary review
    48	
    49	- **Visual identity** — Cyrillic Т and Latin T are visually
    50	  indistinguishable in most monospace fonts. PR diff review by a
    51	  human reading the screen catches nothing.
    52	- **Test design** — alarm tests ran the engine on synthetic
    53	  channels named in the test. They didn't cross-reference back to
    54	  the production `instruments.yaml` namespace.
    55	- **Encoding** — both characters are valid UTF-8, both serialize
    56	  fine in YAML. The file never failed to load.
    57	
    58	## Defenses now in place
    59	
    60	- **Regression test** that asserts every channel pattern in
    61	  `config/alarms_v3.yaml` matches at least one channel in
    62	  `config/channels.yaml` after canonical resolution.
    63	- **Design system rules** (`docs/design-system/rules/*-rules.md`)
    64	  carry explicit Cyrillic-Т-vs-Latin-T invariant for any operator-
    65	  facing rendered text.
    66	- **Adversarial second-model review** (`docs/CODEX_SELF_REVIEW_PLAYBOOK.md`)
    67	  — Codex gpt-5.5/high catches homoglyph-class issues alongside
    68	  semantic regressions.
    69	
    70	## Encoding policy (CLAUDE.md "Кодировка файлов")
    71	
    72	- Python source / Markdown / YAML in repo: UTF-8 **without BOM**.
    73	- BOM is applied **only** to operator-facing CSV exports
    74	  (`storage/csv_export.py`) — Excel on Russian Windows needs the
    75	  BOM prefix to read Cyrillic correctly.
    76	- Do not add BOM to any source file. External reviewers occasionally
    77	  flag a BOM invariant for source — that's misapplication.
    78	
    79	## Lesson
    80	
    81	Tests prove logic correctness, not identifier correctness. When a
    82	rule and the channel namespace it operates over both come from
    83	different files, the regression test must close that loop
    84	explicitly. Visual review can never catch homoglyphs reliably.
    85	
    86	## See also
    87	
    88	- [[10 Subsystems/Alarm engine v2]]
    89	- [[20 Drivers/LakeShore 218S]] — Cyrillic Т prefix origin
    90	- [[30 Investigations/Codex H2 wrong hypothesis]] — different lesson
    91	  from the same year about model confidence vs tests

===== /Users/vladimir/Vault/CryoDAQ/30 Investigations/IV.6 cmd plane hardening.md =====
     1	---
     2	source: CHANGELOG.md `be51a24` IV.6 partial mitigation; ROADMAP.md "IV.6 partial mitigation outcome" + "watchdog regression"; docs/bug_B1_zmq_idle_death_handoff.md "Codex revised analysis"
     3	last_synced: 2026-04-26
     4	status: shipped — defense-in-depth, does NOT close B1
     5	---
     6	
     7	# IV.6 — Cmd plane hardening
     8	
     9	What shipped, what it didn't fix, why it stayed.
    10	
    11	## What shipped (`be51a24`, 2026-04-20)
    12	
    13	The full Codex-proposed B1 fix plan (H2):
    14	
    15	1. **Per-command ephemeral REQ socket** in
    16	   `zmq_subprocess.cmd_forward_loop`. `_new_req_socket()` creates a
    17	   fresh REQ for each command; closed after reply or timeout.
    18	   Matches ZeroMQ Guide ch.4 canonical "poll / timeout / close /
    19	   reopen" pattern.
    20	2. **Launcher-side `command_channel_stalled()` watchdog** in
    21	   `_poll_bridge_data` — restarts bridge subprocess if cmd plane is
    22	   stalled while data plane stays alive.
    23	3. **`TCP_KEEPALIVE` reverted on command + PUB paths** (kept on
    24	   `sub_drain_loop` SUB as orthogonal safeguard). Keepalive added
    25	   on the original idle-reap hypothesis (commit `f5f9039`); H1
    26	   falsified — Linux `tcp_keepalive_time = 7200 s` rules out kernel
    27	   reaping at 120 s.
    28	
    29	Tests: 60/60 unit tests green; full subtree 1775/1776 (1
    30	pre-existing flaky).
    31	
    32	## What it didn't fix
    33	
    34	B1 still reproduces structurally identical to pre-fix:
    35	
    36	| Diag | Pre-fix | Post-fix (IV.6) |
    37	|---|---|---|
    38	| `diag_zmq_idle_hypothesis.py` SPARSE_0.33HZ | cmd #10 FAIL ~30 s | cmd #8 FAIL 56 s |
    39	| `diag_zmq_bridge_extended.py` | cmd #28 FAIL 92 s, 0/3 recovery | cmd #48 FAIL 82 s, 0/3 recovery |
    40	| RAPID_5HZ | 295/295 OK | 295/295 OK |
    41	
    42	Codex's H2 (shared-REQ-state) was empirically falsified. See
    43	[[30 Investigations/Codex H2 wrong hypothesis]]. Post-IV.6 evidence
    44	in the handoff doc reports that the engine REP itself can also go
    45	silently unresponsive after ~30–90 s of bridge uptime — while the
    46	asyncio loop, data-plane PUB, heartbeats, scheduler writes, and
    47	plugin ticks remain healthy. So shared-REQ-state and transport
    48	misattribution have been ruled out; the actual wedge layer is still
    49	unclear, and H4 (pyzmq 25 / Python 3.14 asyncio) and H5 (engine REP
    50	state machine) both remain viable.
    51	
    52	## Watchdog regression + cooldown hotfix (2026-04-20 evening)
    53	
    54	The IV.6 watchdog initially had a bug: `_last_cmd_timeout` persisted
    55	across watchdog-triggered subprocess restart. A fresh subprocess
    56	saw a stale timeout signal on the first poll cycle, triggered
    57	another restart, etc. — restart storm (30–40 restarts/minute on
    58	Ubuntu lab PC).
    59	
    60	Hotfix in `src/cryodaq/launcher.py`:
    61	- 60 s cooldown between command-watchdog restarts via
    62	  `_last_cmd_watchdog_restart` timestamp.
    63	- Missing `return` after restart added so no further checks run in
    64	  the same poll cycle.
    65	
    66	Effect: restart storm gone, but B1 itself still fires. System
    67	reaches usable steady state of "works ~60–120 s, one restart, works
    68	again" — workaround until IV.7 ipc:// or other root-cause fix.
    69	
    70	## Why it stayed in master
    71	
    72	Even though IV.6 doesn't fix B1, the changes are kept:
    73	
    74	- **Architectural improvement.** Matches ZeroMQ Guide ch.4
    75	  canonical reliable req-reply pattern. Future maintainers expect
    76	  this shape.
    77	- **Removes a real brittle point.** Shared REQ state across
    78	  commands was a long-term maintainability hazard regardless of
    79	  whether it caused B1.
    80	- **Gives the launcher a cmd-channel watchdog.** Separate from
    81	  data-plane health detection, the launcher can now detect and
    82	  recover from any future command-only failure shape.
    83	- **Defense-in-depth.** B1 root cause may be deeper still; if a
    84	  future bug surfaces with a similar shape, IV.6 closes one of the
    85	  candidate failure modes.
    86	
    87	## Related fixes shipped alongside
    88	
    89	- `aabd75f` — `engine: wire validate_checksum through Thyracont
    90	  driver loader`. `_create_instruments()` was ignoring the YAML
    91	  key; driver defaulted to `True` regardless of config. Resolves
    92	  TopWatchBar pressure em-dash on Ubuntu lab PC (VSP206 vs VSP63D
    93	  checksum). See [[20 Drivers/Thyracont VSP63D]].
    94	- `74dbbc7` — `reporting: xml_safe sanitizer for python-docx
    95	  compatibility`. Keithley VISA resource strings contain `\x00`;
    96	  python-docx rejected them as XML 1.0 incompatible. New
    97	  `src/cryodaq/utils/xml_safe.py` strips XML-illegal control chars
    98	  at all add_paragraph / cell.text sites in
    99	  `reporting/sections.py`. See [[20 Drivers/Keithley 2604B]].
   100	
   101	## Lesson
   102	
   103	Shipping a hypothesis-driven fix is OK even when it doesn't close
   104	the bug, **provided** the change is independently defensible and
   105	documented as partial mitigation. The mistake would have been to
   106	celebrate IV.6 as a B1 fix and stop investigating; the audit
   107	record clearly says "partial — B1 still open".
   108	
   109	## See also
   110	
   111	- [[30 Investigations/B1 ZMQ idle-death]]
   112	- [[30 Investigations/Codex H2 wrong hypothesis]]
   113	- [[10 Subsystems/ZMQ bridge]]

===== /Users/vladimir/Vault/CryoDAQ/30 Investigations/Plugin isolation rebuild.md =====
     1	---
     2	source: src/cryodaq/analytics/base_plugin.py; analytics/plugin_loader.py history; CLAUDE.md "Аналитика"
     3	last_synced: 2026-04-26
     4	status: closed — rebuilt with isolation
     5	---
     6	
     7	# Plugin isolation rebuild
     8	
     9	A small story about why an architectural change was needed.
    10	
    11	## Original architecture
    12	
    13	Plugins were direct imports — modules in `analytics/` imported and
    14	called from the engine's hot path. A plugin's `process()` ran inline
    15	on the engine event loop. Configuration was via `config/plugins.yaml`
    16	to flag-on individual modules.
    17	
    18	## Failure mode
    19	
    20	A plugin throwing an exception inside `process()` propagated up the
    21	asyncio call chain, killed the scheduler task, and **crashed the
    22	engine** as a side effect. Single buggy plugin → entire data
    23	acquisition stops.
    24	
    25	This is bad for a system whose value proposition is "long-running,
    26	reliable, no-touch acquisition during multi-day experiments".
    27	
    28	## Rebuild
    29	
    30	Two changes landed together:
    31	
    32	1. **`AnalyticsPlugin` ABC** (`analytics/base_plugin.py`). Defines
    33	   the contract: `process(readings) -> list[DerivedMetric]`. Plugin
    34	   id is set in `__init__`. Optional `configure(config)` for YAML
    35	   parameter ingestion.
    36	2. **`PluginPipeline`** (`analytics/plugin_loader.py`). Owns the
    37	   plugin lifecycle:
    38	   - Loads `*.py` files dynamically via
    39	     `importlib.util.spec_from_file_location` + `exec_module`.
    40	   - Subscribes once to `DataBroker` as `plugin_pipeline`.
    41	   - Per-batch try/except around each plugin's `process()` —
    42	     **plugin exceptions logged and dropped, never propagated**.
    43	   - Hot reload via 5 s mtime polling (`_watch_loop`).
    44	   - File-load failures log + skip; one bad file does not poison
    45	     the pipeline.
    46	
    47	## Net effect
    48	
    49	- Engine survives a plugin throwing.
    50	- Failed plugin's batches are skipped; other plugins keep running.
    51	- `numpy`/`scipy` allowed inside plugins (they live outside `core/`
    52	  and `drivers/`); the no-numpy rule for those layers stays.
    53	- `DerivedMetric.now(...)` factory provides a uniform timestamping
    54	  pattern across plugins.
    55	
    56	## Surface area for plugin authors
    57	
    58	A minimal compliant plugin is ~10 lines:
    59	
    60	```python
    61	class MyPlugin(AnalyticsPlugin):
    62	    async def process(self, readings):
    63	        if not readings:
    64	            return []
    65	        return [DerivedMetric.now(self.plugin_id, "metric", value, "unit")]
    66	```
    67	
    68	The pipeline gives the plugin a fresh batch every
    69	`batch_interval_s` (default 1 s), capped at `_MAX_BATCH_SIZE = 500`
    70	readings. Returned metrics are republished into `DataBroker` as
    71	synthetic `Reading`s; live broker subscribers (GUI, web, ZMQ, alarm
    72	subscribers) treat them uniformly with raw readings. SQLite
    73	persistence of plugin output is **not** wired in the current code
    74	surface — `SQLiteWriter` runs in immediate mode from `Scheduler`,
    75	not as a broker subscriber.
    76	
    77	## Where it lives now
    78	
    79	- ABC: `analytics/base_plugin.py`.
    80	- Pipeline: `analytics/plugin_loader.py`.
    81	- Production plugin examples: `analytics/sensor_diagnostics.py`,
    82	  `analytics/vacuum_trend.py`. (Cooldown predictor lives outside
    83	  the plugin pipeline because it needs orchestration with
    84	  `core/cooldown_service.py`.)
    85	- Configuration: `config/plugins.yaml` controls which plugins are
    86	  enabled; `<plugin_id>.yaml` siblings carry plugin-specific config.
    87	
    88	## Lesson
    89	
    90	Engine survival is non-negotiable. Any extension point that lets a
    91	third party (operator-authored plugin) run code in the hot path
    92	must isolate exceptions explicitly — Python's default exception
    93	flow is to crash the loop, and that is the wrong default for
    94	acquisition systems.
    95	
    96	## See also
    97	
    98	- [[10 Subsystems/Plugin architecture]] — full subsystem page
    99	- [[40 Decisions/ADR-003 Plugin isolation via ABC]] — synthesized
   100	  ADR for this rebuild

===== /Users/vladimir/Vault/CryoDAQ/30 Investigations/_index.md =====
     1	---
     2	source: skeleton stub
     3	last_synced: 2026-04-26
     4	status: index
     5	---
     6	
     7	# 30 Investigations
     8	
     9	Bug stories with hypothesis trees, what shipped vs what was falsified,
    10	and current open status.
    11	
    12	- [[30 Investigations/B1 ZMQ idle-death]]
    13	- [[30 Investigations/b2b4fb5 hardening race]]
    14	- [[30 Investigations/Cyrillic homoglyph in alarm config]]
    15	- [[30 Investigations/Codex H2 wrong hypothesis]]
    16	- [[30 Investigations/Plugin isolation rebuild]]
    17	- [[30 Investigations/IV.6 cmd plane hardening]]
    18	
    19	<!-- TODO: link any new investigations as they close -->

===== /Users/vladimir/Vault/CryoDAQ/30 Investigations/b2b4fb5 hardening race.md =====
     1	---
     2	source: docs/decisions/2026-04-24-b2b4fb5-investigation.md; docs/decisions/2026-04-24-d1-d4a-execution.md; docs/ORCHESTRATION.md §7 hardening rule
     3	last_synced: 2026-04-26
     4	status: closed — H3 confirmed, R1 fix shipped
     5	---
     6	
     7	# b2b4fb5 hardening race
     8	
     9	The story of how a transport-agnostic hardening probe ended up
    10	killing an unrelated transport experiment, and how it got blamed for
    11	something it didn't cause.
    12	
    13	## Timeline
    14	
    15	- **2026-04-23 15:10** — Commit `b2b4fb5` ("harden B1 capture bridge
    16	  startup validation") landed. Adds synchronous probe
    17	  `_validate_bridge_startup()` to `tools/diag_zmq_b1_capture.py` that
    18	  fails fast on `bridge.is_alive() == False` or first non-OK
    19	  `safety_status` reply.
    20	- **2026-04-23 ~15:55** — Commit `157c4bc` (IV.7 `ipc://` transport
    21	  experiment) landed ~45 minutes later, on a different branch.
    22	- **2026-04-23 ~16:30** — IV.7 runtime test fails. Single-line
    23	  evidence in `/tmp/diag_iv7_capture.log`:
    24	
    25	  > B1 capture aborted: Bridge startup probe failed:
    26	  > `{'ok': False, 'error': 'Engine не отвечает (Resource temporarily unavailable)'}`
    27	
    28	  The IV.7 narrative becomes "ipc:// transport doesn't work".
    29	- **2026-04-24 00:05** — Investigation session loads
    30	  multi-model-consultation skill manually (registry snapshot at
    31	  session start did not include it; skill was committed mid-session
    32	  via `9a1a100`). Phase 1 self-analysis produces revised reading.
    33	- **2026-04-24 00:18** — Phase 3 empirical retest with
    34	  `git revert b2b4fb5` on the worktree. Fresh ipc:// engine, b2b4fb5
    35	  hardening reverted: **20/20 captures OK**.
    36	- **2026-04-24** — H3 confirmed; R1 (bounded-backoff retry) chosen
    37	  by architect; implemented on `feat/b2b4fb5-repair` (`c3f4f86`),
    38	  Q4 equivalence check PASS, merged via `89b4db1`.
    39	
    40	## What the probe was supposed to do
    41	
    42	The hardening probe added a guard against subprocess-spawn-failure:
    43	if `bridge.is_alive() == False`, the diag tool aborts with a clear
    44	error before trying to send commands. Useful intent — the previous
    45	behavior was that a broken subprocess would surface as cryptic
    46	timeout 35 s later.
    47	
    48	## What actually happened
    49	
    50	`b2b4fb5`'s probe is technically transport-agnostic: it calls
    51	`bridge.is_alive()` (on `multiprocessing.Process`) and
    52	`bridge.send_command()` (queue-dispatched), not anything
    53	TCP-specific. But the probe is **synchronous** and fires
    54	immediately after `bridge.start() + time.sleep(1.0)`. Under
    55	`tcp://` loopback that's plenty of time — `connect()+send()+recv()`
    56	is effectively instantaneous. Under `ipc://` Unix-socket bind, the
    57	engine's REP socket may not be ready when the probe fires; the
    58	bridge subprocess returns `zmq.Again` to the diag, and the diag
    59	treats it as a hard failure.
    60	
    61	Result: probe race against ipc:// bind timing. Tcp:// hides the
    62	race; ipc:// exposes it.
    63	
    64	## Empirical confirmation
    65	
    66	| Scenario | Hardening | Transport | Engine age at cmd #1 | Result |
    67	|---|---|---|---|---|
    68	| 2026-04-23 IV.7 failure | present | ipc:// | < 1 s | **abort at cmd #0** |
    69	| `git revert b2b4fb5`, bridge_extended | reverted | ipc:// | 4 s | 44/44 OK then B1 idle-death cmd #45 |
    70	| `git revert b2b4fb5`, b1_capture fresh | reverted | ipc:// | 4 s | **20/20 OK** |
    71	| pre-b2b4fb5 master, tcp:// | n/a | tcp:// | < 1 s | OK |
    72	
    73	The controlling variable is hardening + engine-age combo; revert
    74	makes b1_capture pass on ipc://.
    75	
    76	## Repair (R1)
    77	
    78	`feat/b2b4fb5-repair` `c3f4f86` — bounded-backoff retry in the
    79	probe. Helper signature:
    80	
    81	```python
    82	_validate_bridge_startup(bridge, attempts=5, backoff_s=0.2,
    83	                         sleep_fn=time.sleep)
    84	```
    85	
    86	1. `bridge.is_alive()` single-shot — keeps subprocess-spawn-failure
    87	   detection.
    88	2. Loop up to 5 attempts × `bridge.send_command({"cmd":
    89	   "safety_status"})`. First OK reply passes.
    90	3. 0.2 s sleep between attempts (bounded; total wait ≤ 1.0 s).
    91	4. All non-OK after 5 → raises `RuntimeError(f"Bridge startup probe
    92	   failed: {last_reply!r}")` — same error surface as b2b4fb5 so
    93	   downstream greppers aren't broken.
    94	
    95	Q4 adversarial equivalence check (Codex gpt-5.5/high) PASS, zero
    96	findings, R1 and b2b4fb5 predicates behave identically across 7
    97	edge-case inputs.
    98	
    99	## What this taught us
   100	
   101	- **Hardening + feature collision is a real failure mode**, not
   102	  hypothetical. ORCHESTRATION.md §7 was added specifically because
   103	  of this incident: if CC is about to land a hardening change and
   104	  there's an active feature branch, check whether the hardening
   105	  could affect the feature.
   106	- **Tcp:// and ipc:// have different bind semantics.** Sync health
   107	  probes that worked on TCP loopback may fail on ipc:// without
   108	  any code path being "wrong" per se — just an unstated timing
   109	  assumption.
   110	- **Misattribution is recoverable** if evidence is preserved.
   111	  `/tmp/diag_iv7_capture.log` was the single sentence that broke
   112	  the false narrative.
   113	
   114	## Status
   115	
   116	Closed. R1 in master; B1 still OPEN (separately) — see
   117	[[30 Investigations/B1 ZMQ idle-death]].
   118	
   119	## See also
   120	
   121	- [[30 Investigations/B1 ZMQ idle-death]]
   122	- [[40 Decisions/2026-04-24-b2b4fb5-investigation]]
   123	- [[40 Decisions/ADR-002 R1 bounded-backoff probe retry]]
   124	- [[50 Workflow/ORCHESTRATION contract]] §7

exec
/opt/homebrew/bin/bash -lc "for f in /Users/vladimir/Vault/CryoDAQ/40\\ Decisions/*.md; do printf '\\n===== %s =====\\n' \""'$f"; nl -ba "$f"; done' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:

===== /Users/vladimir/Vault/CryoDAQ/40 Decisions/2026-04-23-cleanup-baseline.md =====
     1	---
     2	source: docs/decisions/2026-04-23-cleanup-baseline.md
     3	adr_id: ADR-2026-04-23-cleanup-baseline
     4	date: 2026-04-23
     5	status: accepted
     6	---
     7	
     8	# ADR-2026-04-23 — Cleanup baseline session
     9	
    10	## Context
    11	
    12	First session run under the new sole-coordinator model defined by
    13	`docs/ORCHESTRATION.md` (authored 2026-04-23 evening by Vladimir +
    14	web Claude Opus 4.7). Working tree was non-clean and current branch
    15	was not master:
    16	
    17	- 3 modified tracked files (`CLAUDE.md`, `.gitignore`, `config/channels.yaml`)
    18	- 34 untracked files at root
    19	- Current branch `codex/preserved-local-master-2026-04-21` (6 branch-only swarm-era commits, queued for deletion)
    20	- One worktree with §5.4-violating naming mismatch
    21	  (`.worktrees/codex-safe-merge-b1-truth-recovery` on branch `experiment/iv7-ipc-transport`)
    22	- `.gitignore` did NOT actually carry `.worktrees/` despite §5.4
    23	  claiming it did
    24	
    25	CC paused with a 5-blocker STOP report. Architect returned
    26	Resolutions A–E plus a STOP-discipline amendment and an
    27	autonomy-expansion (untracked files inside to-be-removed worktrees:
    28	preserve-and-proceed default).
    29	
    30	## Decision
    31	
    32	Mechanical cleanup applied:
    33	
    34	1. Discard the 6 branch-only commits on `codex/preserved-local-master-2026-04-21`; revert all 3 modified tracked files; switch to master.
    35	2. Commit 1/4 (`adb49fe`) — preserve session detail + ORCHESTRATION.md.
    36	3. Commit 2/4 (`1ea049d`) — archive 11 agent-swarm `.md` files to `docs/audits/2026-04-21-agent-swarm/` and 3 `.py` to `.scratch/zmq-exploration-2026-04-21/`. Keep `CODEX_ARCHITECTURE_CONTROL_PLANE.md` at root and add to §6.2 whitelist.
    37	4. Commit 3/4 (`587bea8`) — `.gitignore` adds 7 patterns (`.worktrees/` first; then `.audit-run/`, `.omc/`, `.swarm/`, `.venv-tools/`, `agentswarm/`, `.scratch/`).
    38	5. Worktree rename (no commit) — `git worktree move` to fix §5.4 naming mismatch.
    39	6. Stray plan in worktree archived (`cfee680`), then `--force` worktree removal authorized; branch prune of two stale codex/* branches; preserved `codex/safe-merge-b1-truth-recovery` and `experiment/iv7-ipc-transport`.
    40	
    41	Adopted operational rules from this session:
    42	
    43	- **STOP discipline update.** Plan factual inaccuracies of 1-line
    44	  magnitude (off-by-one counts, wrong commit messages) → adapt
    45	  inline, note in ledger, do NOT escalate. Codified in
    46	  [[_meta/glossary]] and reinforced by `feedback_stop_discipline.md`.
    47	- **Autonomy expansion.** Untracked files inside to-be-removed
    48	  worktrees: preserve to archive then proceed. Default, not
    49	  exception.
    50	- **Retroactive semantic versioning** plan for v0.34.0..v0.38.0 —
    51	  postponed pending B1 mitigation.
    52	
    53	## Consequences
    54	
    55	Master at `cfee680` (pre-ledger commit). Two preserved branches
    56	remain pending architect evaluation:
    57	- `codex/safe-merge-b1-truth-recovery` @ `b2b4fb5` (later H3-validated)
    58	- `experiment/iv7-ipc-transport` @ `63a3fed` (transport experiment in flight)
    59	
    60	Open follow-ups recorded for the next architect session:
    61	
    62	- B2b4fb5 hypothesis test → resolved by [[40 Decisions/2026-04-24-b2b4fb5-investigation]] (H3 CONFIRMED).
    63	- Safe-merge docs evaluation (11 commits) → DROP bucket per [[40 Decisions/2026-04-24-d1-d4a-execution]] §"DROP bucket".
    64	- IV.7 status follow-up → ongoing.
    65	- ORCHESTRATION.md §5.4 wording cleanup ("already gitignored" → "enforced invariant").
    66	- §11 known-active-plans table update — Repo cleanup DONE 2026-04-23 (`adb49fe..cfee680`).
    67	
    68	## Status
    69	
    70	Accepted. Codified in `docs/ORCHESTRATION.md` and the autonomy /
    71	STOP-discipline rules now drive subsequent sessions. Repo cleanup is
    72	done; the operational amendments outlive this session.
    73	
    74	## See also
    75	
    76	- [[50 Workflow/ORCHESTRATION contract]]
    77	- [[40 Decisions/2026-04-24-b2b4fb5-investigation]]
    78	- [[40 Decisions/2026-04-24-d1-d4a-execution]]

===== /Users/vladimir/Vault/CryoDAQ/40 Decisions/2026-04-24-b2b4fb5-investigation.md =====
     1	---
     2	source: docs/decisions/2026-04-24-b2b4fb5-investigation.md
     3	adr_id: ADR-2026-04-24-b2b4fb5-investigation
     4	date: 2026-04-24
     5	status: accepted
     6	---
     7	
     8	# ADR-2026-04-24 — b2b4fb5 hypothesis investigation (H3 CONFIRMED)
     9	
    10	## Context
    11	
    12	Commit `b2b4fb5` (2026-04-23 15:10, "harden B1 capture bridge startup
    13	validation") added a synchronous probe `_validate_bridge_startup()`
    14	to `tools/diag_zmq_b1_capture.py`. The 2026-04-23 ~16:30 IV.7 runtime
    15	test failed with cmd #0 abort and the failure was originally
    16	attributed to the IV.7 `ipc://` transport itself.
    17	
    18	Hypothesis H3: `b2b4fb5`'s startup probe is incompatible with `ipc://`
    19	because the engine's REP socket isn't ready when the probe fires,
    20	causing a `zmq.Again` to surface as a hard failure — and IV.7's
    21	runtime failure was therefore a misattribution of a hardening race,
    22	not a transport defect.
    23	
    24	## Decision
    25	
    26	H3 CONFIRMED via empirical test on `experiment/iv7-ipc-transport`
    27	worktree:
    28	
    29	| Scenario | Hardening | Transport | Engine age at cmd #1 | Result |
    30	|---|---|---|---|---|
    31	| IV.7 2026-04-23 failure | present | ipc:// | < 1 s (fresh) | abort at cmd #0 — "Engine не отвечает" |
    32	| Retest with `git revert b2b4fb5` (bridge_extended) | reverted | ipc:// | 4 s | 44/44 OK then B1 idle-death at cmd #45 (uptime 79.1 s) |
    33	| Retest (b1_capture, fresh engine) | reverted | ipc:// | 4 s | **20/20 OK** |
    34	
    35	The probe's literal output (`{"ok": false, "error": "Engine не отвечает (Resource temporarily unavailable)"}`) matched `/tmp/diag_iv7_capture.log` from the original failure — same code path, same error message.
    36	
    37	What this proves:
    38	1. `ipc://` transport itself is viable; the IV.7 narrative was a misattribution.
    39	2. The b2b4fb5 probe has a startup race against ipc:// bind timing
    40	   (instantaneous on tcp:// loopback; non-instantaneous on Unix-socket bind).
    41	
    42	What this does NOT prove:
    43	3. **B1 idle-death is unrelated to b2b4fb5.** B1 reproduces at ~80 s
    44	   uptime regardless of hardening presence. IV.7 did not fix B1. H4
    45	   (pyzmq/asyncio integration) and H5 (engine REP state machine)
    46	   remain viable for B1 root cause.
    47	
    48	Repair options proposed:
    49	
    50	- **R1** — fix probe to be startup-race-tolerant (bounded backoff retry).
    51	- **R2** — move readiness into `bridge.start()` itself.
    52	- **R3** — revert b2b4fb5 entirely.
    53	
    54	Architect chose **R1**. Implementation landed on `feat/b2b4fb5-repair`
    55	branch (`c3f4f86`), merged to master via `89b4db1`. Q4 adversarial
    56	equivalence check (Codex gpt-5.5/high) — PASS, zero findings, R1 and
    57	b2b4fb5 predicates behave identically across 7 edge-case inputs.
    58	See [[40 Decisions/2026-04-24-d1-d4a-execution]] for execution detail.
    59	
    60	## Consequences
    61	
    62	- IV.7 unblocks transport-level testing. B1 still OPEN; root cause
    63	  to be found at H4/H5 layer or elsewhere
    64	  ([[30 Investigations/B1 ZMQ idle-death]]).
    65	- A new pattern is codified: synchronous health probes at engine /
    66	  subprocess startup must accommodate non-instantaneous bind
    67	  semantics. `ipc://` Unix-socket bind in particular needs a
    68	  retry-with-backoff.
    69	- Skill loaded mid-session via manual `Read` (the registry snapshot
    70	  at session start did not include `multi-model-consultation`,
    71	  committed mid-session via `9a1a100`). Surfaced as an
    72	  ORCHESTRATION.md edit item: skill registry refresh requires
    73	  harness restart.
    74	
    75	## Status
    76	
    77	Accepted; R1 merged to master; D1 loop formally closed via Q4
    78	adversarial check.
    79	
    80	## See also
    81	
    82	- [[30 Investigations/B1 ZMQ idle-death]]
    83	- [[30 Investigations/b2b4fb5 hardening race]]
    84	- [[40 Decisions/2026-04-24-d1-d4a-execution]]
    85	- [[50 Workflow/Multi-model consultation]]

===== /Users/vladimir/Vault/CryoDAQ/40 Decisions/2026-04-24-d1-d4a-execution.md =====
     1	---
     2	source: docs/decisions/2026-04-24-d1-d4a-execution.md
     3	adr_id: ADR-2026-04-24-d1-d4a-execution
     4	date: 2026-04-24
     5	status: accepted
     6	---
     7	
     8	# ADR-2026-04-24 — D4a cherry-picks + D1 R1 repair execution
     9	
    10	## Context
    11	
    12	After [[40 Decisions/2026-04-24-b2b4fb5-investigation]] confirmed H3,
    13	architect approved the **R1 repair** strategy: bounded-backoff retry
    14	in the b2b4fb5 startup probe. Two streams of work needed to land:
    15	
    16	- **D4a** — 5 diag-tool cherry-picks from the agent-swarm branch onto
    17	  master (reusable B1 helpers + canonical capture CLI).
    18	- **D1** — implement R1 on a feature branch on top of D4a.
    19	
    20	`D4b` (7 doc cherry-picks) and `D2` (H4 split-context falsification
    21	on `experiment/iv7-ipc-transport`) were deferred to a later session
    22	per architect "sequential, not parallel" directive.
    23	
    24	## Decision
    25	
    26	### D4a — 5 cherry-picks landed on master with `-x` provenance
    27	
    28	| New SHA | Original SHA | Subject |
    29	|---|---|---|
    30	| `8b9ce4a` | `3b661e2` | tools: add reusable B1 diagnostic helpers |
    31	| `cc090be` | `056a199` | tools: add canonical B1 capture CLI |
    32	| `40553ea` | `8e79ea6` | tools: align B1 diagnostic helpers with bridge/direct capture |
    33	| `033f87b` | `983480d` | tools: align B1 capture CLI with jsonl master capture |
    34	| `62314be` | `2ed975f` | tools: record direct probe timeouts in B1 capture |
    35	
    36	Post-D4a state on master: `tools/_b1_diagnostics.py` reusable helpers,
    37	`tools/diag_zmq_b1_capture.py` in its **pre-b2b4fb5 form**, plus
    38	`tests/tools/` 37/37 passing.
    39	
    40	### D1 — R1 implementation on `feat/b2b4fb5-repair`
    41	
    42	- Branch: `feat/b2b4fb5-repair`, base = `62314be`, HEAD = `c3f4f86`.
    43	- Scope: `tools/diag_zmq_b1_capture.py` + its test only (Codex-01
    44	  Stream A scope fence respected).
    45	- New helper `_validate_bridge_startup(bridge, attempts=5,
    46	  backoff_s=0.2, sleep_fn=time.sleep)`:
    47	  1. `bridge.is_alive()` single-shot subprocess-spawn-failure catch.
    48	  2. Loop up to `attempts` × `bridge.send_command({"cmd":
    49	     "safety_status"})`. First OK reply passes.
    50	  3. Inter-attempt `sleep_fn(backoff_s)` with DEBUG log.
    51	  4. All non-OK → `RuntimeError(f"Bridge startup probe failed:
    52	     {last_reply!r}")` — same error surface as b2b4fb5 (downstream
    53	     greppers unaffected).
    54	- Tests landed: cases 1–3 (dead bridge / transient non-OK + recover /
    55	  all non-OK with bounded sleeps). Cases 4–6 (live engine ipc://,
    56	  tcp://, delayed-REP harness) deferred to a hardware-validation
    57	  session, noted in test-file header.
    58	
    59	### DROP bucket — 4 commits, ledger only
    60	
    61	Per architect Q3 (rationale via
    62	`gemini-04-safe-merge-eval.response.md`): no forwarding doc, no
    63	cherry-pick, branch preservation on `codex/safe-merge-b1-truth-recovery`
    64	is the historical record:
    65	
    66	- `ab72c84` — pre-ORCHESTRATION roadmap-review prompts; superseded.
    67	- `8feda6b` — swarm-era multi-model review pack; superseded.
    68	- `bbc65c8` — stale run-note for a runbook never executed.
    69	- `0a4ae04` — arbitration of the superseded artifacts above.
    70	
    71	### Q4 equivalence check — PASS
    72	
    73	Post-merge Codex gpt-5.5/high adversarial equivalence review on the
    74	M2 merge-commit `89b4db1`:
    75	- Zero findings at any severity. Only `ACCEPTABLE` category used,
    76	  describing the intended retry improvement.
    77	- Codex ran inline Python predicate simulation across 7 edge-case
    78	  inputs — R1 and b2b4fb5 behave identically.
    79	- Verified `ZmqBridge.send_command` + `zmq_subprocess.cmd_forward_loop`:
    80	  no retry-induced REQ socket state leak (IV.6 ephemeral REQ
    81	  invariant preserved).
    82	
    83	D1 loop formally closed. Branch `feat/b2b4fb5-repair` deleted local +
    84	remote; `c3f4f86` reachable via second-parent of `89b4db1`.
    85	
    86	## Consequences
    87	
    88	- IV.7 transport-level testing unblocked (probe no longer races bind).
    89	- B1 still OPEN; H4 / H5 next.
    90	- D4b doc-cherry-picks + retroactive-tag pass remain queued.
    91	- §13.3 adaptations during execution: zero conflicts, no scope
    92	  escapes, only added `import logging` (stdlib).
    93	
    94	## Status
    95	
    96	Accepted. Master tip `cabd854` reflects post-merge state plus the Q4
    97	synthesis docs.
    98	
    99	## See also
   100	
   101	- [[40 Decisions/2026-04-24-b2b4fb5-investigation]] — H3 confirmation
   102	- [[30 Investigations/b2b4fb5 hardening race]] — investigation page
   103	- [[30 Investigations/B1 ZMQ idle-death]] — still open
   104	- [[50 Workflow/ORCHESTRATION contract]] — §13.3 ledger format

===== /Users/vladimir/Vault/CryoDAQ/40 Decisions/2026-04-24-overnight-swarm-launch.md =====
     1	---
     2	source: docs/decisions/2026-04-24-overnight-swarm-launch.md
     3	adr_id: ADR-2026-04-24-overnight-swarm-launch
     4	date: 2026-04-24
     5	status: accepted
     6	---
     7	
     8	# ADR-2026-04-24 — Overnight swarm launch
     9	
    10	## Context
    11	
    12	Executing `CC_PROMPT_OVERNIGHT_SWARM_2026-04-24.md` — ten scoped
    13	consultation jobs distributed to two independent verifier models:
    14	
    15	- **Codex gpt-5.5 / reasoning high** × 5 tasks (codex-01..05).
    16	- **Gemini 2.5-pro** × 5 tasks (gemini-01..05).
    17	
    18	All artifacts collected under
    19	`artifacts/consultations/2026-04-24-overnight/` (briefs, responses,
    20	per-stream syntheses, master summary).
    21	
    22	## Decision
    23	
    24	### CLI-direct dispatch instead of slash commands
    25	
    26	Plan referenced `/codex:rescue --background ...`; reality: the
    27	slash-command form is not a shell invocation. Adapted to direct
    28	`codex exec` and `gemini` CLI calls, wrapped in detached
    29	`nohup bash -c '...' </dev/null >/dev/null 2>&1 &` subshells.
    30	
    31	Codex flags settled on:
    32	- `-m gpt-5.5`, `-c model_reasoning_effort="high"`
    33	- `-s read-only`, `--skip-git-repo-check`
    34	- stdin-fed prompt (`< BRIEF.prompt.md`), stdout `> RESPONSE.response.md 2>&1`
    35	
    36	Gemini flags settled on (after parallel-dispatch failure, see below):
    37	- `-m gemini-2.5-pro`, `--yolo` (so Gemini can read repo files
    38	  + run `git show` — default approval mode blocks shell)
    39	- `-o text`, `-p "$(cat BRIEF.prompt.md)"`
    40	
    41	### Model-string probe before batch
    42	
    43	3-token round-trip probe with `gpt-5.5` and `gemini-2.5-pro` returned
    44	"probe ok". §3.7 fallback to gpt-5.4 did not fire.
    45	
    46	### Gemini parallel → serial chain (rate-limit + tool-access fix)
    47	
    48	First parallel dispatch hit two issues within ~20 s:
    49	1. **Per-minute rate ceiling** — 5× parallel gemini-2.5-pro calls
    50	   exhausted capacity ("Your quota will reset after 0s").
    51	2. **Tool access** — without `--yolo`, Gemini default approval mode
    52	   refused `run_shell_command`; briefs require Gemini to read multiple
    53	   files + `git show`.
    54	
    55	Adaptation: kill swarm wrapper PIDs (carefully avoiding pre-existing
    56	unrelated gemini processes), zero out partial-error response files,
    57	relaunch Gemini as a single serial chain with 30 s gaps and `--yolo`,
    58	single tracking PID `50252`. Codex stayed parallel.
    59	
    60	### Outcome rules
    61	
    62	- Per skill §4.2 slop check (< 500 words, no file:line refs, evasive)
    63	  → retry once per §7.
    64	- Phase 6–9 morning retrieval: per-stream synthesis → 4 files under
    65	  `STREAM_SYNTHESES/`, `MASTER_SUMMARY.md`, single commit.
    66	
    67	## Consequences
    68	
    69	- This ledger records a working CLI-direct dispatch adaptation.
    70	  Codex stayed parallel; Gemini was relaunched as a serial chain
    71	  with 30 s gaps and `--yolo`, expected runtime ~30–60 min for 5 jobs.
    72	- `--yolo` is required for Gemini whenever the brief asks the model
    73	  to read repo files or run shell tooling.
    74	- Morning retrieval / synthesis / commit (Phase 6–9 of the launch
    75	  spec) remained open at session end.
    76	
    77	## Status
    78	
    79	Accepted. Morning retrieval and synthesis remain open in this source
    80	ledger; the digest of the operational pattern that emerged from this
    81	and similar runs lives in [[50 Workflow/Overnight swarm pattern]].
    82	
    83	## See also
    84	
    85	- [[50 Workflow/Multi-model consultation]] — skill that gates this
    86	  protocol
    87	- [[50 Workflow/Overnight swarm pattern]] — replayable template
    88	- [[40 Decisions/2026-04-24-d1-d4a-execution]] — what came out of
    89	  this swarm's syntheses

===== /Users/vladimir/Vault/CryoDAQ/40 Decisions/ADR-001 Persistence-first invariant.md =====
     1	---
     2	source: synthesized from CLAUDE.md persistence section, PROJECT_STATUS.md invariants 2/13/14, src/cryodaq/core/scheduler.py, Phase 2d retro
     3	adr_id: ADR-001
     4	date: 2026-04-26 (synthesized)
     5	status: accepted
     6	---
     7	
     8	# ADR-001 — Persistence-first invariant
     9	
    10	## Context
    11	
    12	CryoDAQ runs multi-day cryogenic experiments. After any unplanned
    13	engine termination the post-mortem reconstruction must answer "what
    14	did the operator's GUI see at time T?". If the in-memory broker
    15	publishes a reading that has not yet committed to durable SQLite
    16	storage, the operator's last-observed state diverges from the
    17	durable record. That divergence makes incident analysis unreliable
    18	exactly when it matters most.
    19	
    20	CryoDAQ also runs alongside a safety subsystem
    21	([[10 Subsystems/Safety FSM]]) that consumes a separate broker and
    22	makes source-on/off decisions. If the safety subsystem ever sees a
    23	reading the writer didn't, the safety state and durable record can
    24	diverge under fault.
    25	
    26	## Decision
    27	
    28	The engine enforces a strict ordering at every poll cycle, in
    29	`Scheduler._process_readings()`:
    30	
    31	```text
    32	InstrumentDriver.read_channels()
    33	  → 1. SQLiteWriter.write_immediate()
    34	    2. THEN DataBroker.publish_batch()
    35	    3. THEN SafetyBroker.publish_batch()
    36	```
    37	
    38	The order is unconditional and not switchable.
    39	
    40	This is supported by:
    41	
    42	- **WAL mode verification at startup.** `PRAGMA journal_mode=WAL`
    43	  result is checked; engine refuses to start if WAL is not actually
    44	  on (Phase 2d invariant 14).
    45	- **Atomic file writes** for sidecar artifacts (experiment
    46	  metadata, calibration index/curve) via `core/atomic_write.py`
    47	  using `os.replace()` (Phase 2d invariant 13).
    48	- **OVERRANGE / UNDERRANGE → ±inf** with `status` carried as REAL
    49	  in SQLite. SENSOR_ERROR / TIMEOUT (NaN) filtered before write
    50	  because SQLite treats NaN as NULL (Phase 2d invariant 10).
    51	- **Calibration KRDG+SRDG persist in one transaction per poll
    52	  cycle.** State mutation deferred to `on_srdg_persisted` so that a
    53	  write failure does not leave `t_min`/`t_max` diverged from the
    54	  actual persisted data (Phase 2d invariant 15, Jules R2 Q3).
    55	- **Cancellation shielding** on post-fault paths: `emergency_off`,
    56	  `fault_log_callback` (BEFORE optional broker publish — Jules R2),
    57	  `_ensure_output_off` in `_safe_off` (Phase 2d invariant 11).
    58	
    59	## Consequences
    60	
    61	- A few-ms SQLite write latency lands on the engine's hot path per
    62	  poll cycle. On WAL on SSD this is sub-ms; on spinning disk a few
    63	  ms. Operator-perceived latency is dominated by the LakeShore
    64	  poll interval (2 s) anyway.
    65	- **Durability caveat.** SQLite WAL uses `synchronous=NORMAL` by
    66	  default, which can lose roughly the last ~1 s on abrupt power
    67	  loss. Production deployment expects UPS coverage or
    68	  `CRYODAQ_SQLITE_SYNC=FULL` environment override; the latter
    69	  trades write throughput for stronger durability. Phase 2d C.3
    70	  deferral.
    71	- GUI dashboards must hold local rolling buffers (`channel_buffer.py`)
    72	  to render high-frequency timeseries — but the buffer is fed from
    73	  the broker, which only sees committed readings.
    74	- "Performance mode" overrides are not allowed. Any future
    75	  optimization that would skip or defer the write step has to clear
    76	  this ADR.
    77	- The fail-closed config invariant (engine exit code 2 on missing
    78	  / malformed `safety.yaml`, `alarms_v3.yaml`, `interlocks.yaml`,
    79	  `housekeeping.yaml`, `channels.yaml`) extends the same default:
    80	  start in a state where durable behavior is guaranteed, refuse to
    81	  start otherwise.
    82	
    83	## Status
    84	
    85	Accepted. Has been the operating contract since Phase 2d. The
    86	`docs/decisions/*` ledgers do not contain a separate ADR for this
    87	invariant because it predates the ledger system; the invariant is
    88	captured in `CLAUDE.md` and `PROJECT_STATUS.md`. This synthesized
    89	ADR exists to make the rationale visible alongside the other ADRs
    90	in this vault.
    91	
    92	## See also
    93	
    94	- [[10 Subsystems/Persistence-first]] — implementation page
    95	- [[10 Subsystems/Safety FSM]] — cancellation-shielded fault path
    96	- [[10 Subsystems/Calibration v2]] — one-transaction rule

===== /Users/vladimir/Vault/CryoDAQ/40 Decisions/ADR-002 R1 bounded-backoff probe retry.md =====
     1	---
     2	source: synthesized from docs/decisions/2026-04-24-b2b4fb5-investigation.md, docs/decisions/2026-04-24-d1-d4a-execution.md, ORCHESTRATION.md §7
     3	adr_id: ADR-002
     4	date: 2026-04-26 (synthesized; underlying decision 2026-04-24)
     5	status: accepted
     6	---
     7	
     8	# ADR-002 — R1 bounded-backoff probe retry
     9	
    10	## Context
    11	
    12	Commit `b2b4fb5` (2026-04-23) added a synchronous startup probe to
    13	`tools/diag_zmq_b1_capture.py`:
    14	`_validate_bridge_startup()` aborts on `bridge.is_alive() == False`
    15	or first non-OK `safety_status` reply. Useful intent — fail fast on
    16	subprocess-spawn failure rather than wait 35 s for a misleading
    17	`zmq.Again`.
    18	
    19	The probe is technically transport-agnostic but is **synchronous
    20	and single-shot**. Under tcp:// loopback that's adequate — bind +
    21	connect + first reply is effectively instantaneous. Under
    22	ipc:// Unix-socket bind, the engine's REP socket may not be ready
    23	when the probe fires; the diag aborts at cmd #0.
    24	
    25	This is what killed the 2026-04-23 IV.7 test and led to the
    26	"ipc:// transport doesn't work" misattribution.
    27	[[40 Decisions/2026-04-24-b2b4fb5-investigation|H3 confirmed
    28	2026-04-24]].
    29	
    30	## Decision
    31	
    32	Replace the single-shot probe with a bounded-backoff retry. New
    33	helper signature in `tools/diag_zmq_b1_capture.py`:
    34	
    35	```python
    36	_validate_bridge_startup(bridge, attempts=5, backoff_s=0.2,
    37	                         sleep_fn=time.sleep)
    38	```
    39	
    40	Behavior:
    41	
    42	1. `bridge.is_alive()` single-shot — keeps the
    43	   subprocess-spawn-failure detection that was the original intent.
    44	2. Loop up to `attempts=5` × `bridge.send_command({"cmd":
    45	   "safety_status"})`. First OK reply passes.
    46	3. `sleep_fn(backoff_s)` between attempts (bounded; total wait ≤
    47	   1.0 s for default values).
    48	4. All 5 attempts non-OK → raise
    49	   `RuntimeError(f"Bridge startup probe failed: {last_reply!r}")` —
    50	   same error surface as `b2b4fb5` so downstream tooling that
    51	   greps this marker is unaffected.
    52	
    53	`sleep_fn` injected as a parameter so unit tests can substitute a
    54	fake without burning real wall-clock.
    55	
    56	Considered and rejected:
    57	
    58	- **R2** — move readiness into `bridge.start()`. Cleaner in
    59	  principle, but touches more code (new `start()` semantics,
    60	  test churn). Cost > benefit for a tool-side guard.
    61	- **R3** — revert b2b4fb5 entirely. Loses the spawn-failure catch.
    62	  Cheapest, but the catch is genuinely useful when subprocess fails
    63	  to start (rare but real on Windows).
    64	
    65	## Consequences
    66	
    67	- IV.7 ipc:// transport-level testing unblocked.
    68	- Pattern codified for future health probes: synchronous health
    69	  checks at engine / subprocess startup must accommodate
    70	  non-instantaneous bind semantics — ipc:// in particular needs a
    71	  retry-with-backoff. Applies to any future `_validate_*_startup`
    72	  shape.
    73	- Downstream `B1 capture aborted: ...` greppers are preserved
    74	  (same error string).
    75	- B1 itself remains OPEN. R1 only repairs the probe; the underlying
    76	  bug (`30 Investigations/B1 ZMQ idle-death`) is independent.
    77	
    78	## Validation (Q4)
    79	
    80	Post-merge Codex gpt-5.5/high adversarial equivalence review on the
    81	M2 merge-commit `89b4db1`:
    82	
    83	- Zero findings at any severity. Only `ACCEPTABLE` category used.
    84	- Codex ran inline Python predicate simulation across 7 edge-case
    85	  inputs (`None`, `{}`, `{"ok": None}`, `{"ok": "True"}`, `{"ok":
    86	  1}`, `{"ok": True}`, `{"ok": False}`) — R1 and b2b4fb5 predicates
    87	  behave identically.
    88	- Cross-referenced `ZmqBridge.send_command` +
    89	  `zmq_subprocess.cmd_forward_loop` to confirm no retry-induced
    90	  REQ socket state leak (IV.6 ephemeral REQ invariant preserved).
    91	
    92	D1 loop closed. Branch `feat/b2b4fb5-repair` deleted local + remote;
    93	`c3f4f86` reachable via second-parent of `89b4db1`.
    94	
    95	## Status
    96	
    97	Accepted. R1 in master. ORCHESTRATION.md §7 ("Hardening + feature
    98	interaction rule") captures the workflow lesson — this incident is
    99	the reason that section exists.
   100	
   101	## See also
   102	
   103	- [[40 Decisions/2026-04-24-b2b4fb5-investigation]]
   104	- [[40 Decisions/2026-04-24-d1-d4a-execution]]
   105	- [[30 Investigations/b2b4fb5 hardening race]]
   106	- [[30 Investigations/B1 ZMQ idle-death]]
   107	- [[50 Workflow/ORCHESTRATION contract]] §7

===== /Users/vladimir/Vault/CryoDAQ/40 Decisions/ADR-003 Plugin isolation via ABC.md =====
     1	---
     2	source: synthesized from src/cryodaq/analytics/base_plugin.py, analytics/plugin_loader.py, CLAUDE.md "Аналитика"
     3	adr_id: ADR-003
     4	date: 2026-04-26 (synthesized; underlying decision pre-2026)
     5	status: accepted
     6	---
     7	
     8	# ADR-003 — Plugin isolation via ABC
     9	
    10	## Context
    11	
    12	Original analytics architecture imported plugin modules directly
    13	into the engine and called their `process()` functions inline on
    14	the asyncio event loop. A plugin throwing an exception propagated
    15	up the call chain, killed the scheduler task, and crashed the
    16	engine.
    17	
    18	For a system whose value proposition is "long-running, reliable,
    19	no-touch acquisition during multi-day experiments", a single
    20	buggy operator-authored plugin should never be able to stop data
    21	acquisition.
    22	
    23	## Decision
    24	
    25	Two pieces:
    26	
    27	1. **`AnalyticsPlugin` ABC** (`analytics/base_plugin.py`). Defines
    28	   the contract via `@abstractmethod async def process(self,
    29	   readings: list[Reading]) -> list[DerivedMetric]`. Plugin id is
    30	   set in `__init__`. Optional `configure(config: dict)` for
    31	   YAML parameter ingestion (default impl just stores the dict).
    32	
    33	2. **`PluginPipeline`** (`analytics/plugin_loader.py`). Owns the
    34	   plugin lifecycle:
    35	   - Loads `*.py` files dynamically via
    36	     `importlib.util.spec_from_file_location` + `exec_module`.
    37	   - Subscribes once to `DataBroker` as `plugin_pipeline`.
    38	   - **Per-batch `try/except` around each plugin's `process()`** —
    39	     plugin exceptions are logged at ERROR level and that batch is
    40	     dropped for that plugin only. Other plugins continue.
    41	   - Hot reload via 5 s mtime polling (`_watch_loop`).
    42	   - File-load failures log + skip; one bad file does not poison
    43	     the pipeline.
    44	
    45	`DerivedMetric` is a frozen dataclass with `timestamp`, `plugin_id`,
    46	`metric`, `value`, `unit`, `metadata` and a
    47	`DerivedMetric.now(...)` factory for uniform UTC timestamping.
    48	
    49	## Consequences
    50	
    51	- Engine survives plugin exceptions.
    52	- Plugins may use `numpy`/`scipy` (the no-numpy invariant applies
    53	  only to `core/` and `drivers/`).
    54	- 5 s mtime polling adds a small steady-state cost; chosen over
    55	  `inotify` / `FSEvents` to avoid platform-specific dependencies.
    56	- Plugin authors get a tiny, predictable surface: implement
    57	  `process()`, optionally `configure()`. Roughly 10 lines for a
    58	  minimal plugin.
    59	- Synthetic `Reading` republishing means **live broker subscribers**
    60	  (GUI, web, ZMQ, alarm subscribers) handle derived metrics uniformly.
    61	  No SQLite persistence in the current code surface
    62	  (`SQLiteWriter` runs in immediate mode from `Scheduler`, not as a
    63	  broker subscriber); persisting plugin output is a future wiring
    64	  task if needed.
    65	
    66	## Status
    67	
    68	Accepted. Pattern is the basis of all subsequent analytics work
    69	(`sensor_diagnostics`, `vacuum_trend`, future F16 plugin SDK).
    70	
    71	The cooldown predictor (`core/cooldown_service.py`) is deliberately
    72	**not** a plugin, because it needs orchestration with the
    73	experiment lifecycle that the plugin pipeline doesn't provide.
    74	That carve-out is fine; the ABC is for stateless, batch-driven
    75	analytics.
    76	
    77	## See also
    78	
    79	- [[10 Subsystems/Plugin architecture]] — implementation page
    80	- [[30 Investigations/Plugin isolation rebuild]] — story behind
    81	  the rebuild
    82	- [[60 Roadmap/F-table backlog]] — F16 (plugin hot-reload SDK +
    83	  examples)

===== /Users/vladimir/Vault/CryoDAQ/40 Decisions/_index.md =====
     1	---
     2	source: skeleton stub + Phase 4 cross-link
     3	last_synced: 2026-04-26
     4	status: index
     5	---
     6	
     7	# 40 Decisions
     8	
     9	Architecture Decision Records (ADRs). One file per accepted decision.
    10	
    11	## Mirrored from `docs/decisions/*.md`
    12	
    13	- [[40 Decisions/2026-04-23-cleanup-baseline]]
    14	- [[40 Decisions/2026-04-24-b2b4fb5-investigation]]
    15	- [[40 Decisions/2026-04-24-d1-d4a-execution]]
    16	- [[40 Decisions/2026-04-24-overnight-swarm-launch]]
    17	
    18	## Synthesized (no committed source ADR)
    19	
    20	- [[40 Decisions/ADR-001 Persistence-first invariant]]
    21	- [[40 Decisions/ADR-002 R1 bounded-backoff probe retry]]
    22	- [[40 Decisions/ADR-003 Plugin isolation via ABC]]
    23	
    24	New ADRs land here whenever:
    25	- A new `docs/decisions/*.md` lands in the repo (mirror it)
    26	- A synthesized decision rationale crystallizes from accumulated
    27	  history (next free `ADR-NNN`)
    28	
    29	See [[_meta/update protocol]] for the trigger rules.

exec
/opt/homebrew/bin/bash -lc "for f in /Users/vladimir/Vault/CryoDAQ/50\\ Workflow/*.md /Users/vladimir/Vault/CryoDAQ/60\\ Roadmap/*.md /Users/vladimir/Vault/CryoDAQ/README.md; do printf '\\n===== %s =====\\n' \""'$f"; nl -ba "$f"; done' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:

===== /Users/vladimir/Vault/CryoDAQ/50 Workflow/Calibration loops history.md =====
     1	---
     2	source: docs/decisions/2026-04-23-cleanup-baseline.md; docs/decisions/2026-04-24-*.md; docs/ORCHESTRATION.md §12 + §13; docs/CODEX_SELF_REVIEW_PLAYBOOK.md
     3	last_synced: 2026-04-26
     4	status: synthesized meta-narrative
     5	---
     6	
     7	# Calibration loops history
     8	
     9	How prompts and CC behavior evolved from "lots of stops" toward an
    10	"autonomy band". This page is meta — it's about how we work, not
    11	about what the code does.
    12	
    13	## The shape of a calibration loop
    14	
    15	A calibration loop is one round of: prompt → CC tries to execute →
    16	something doesn't fit → CC stops or adapts → architect (Vladimir +
    17	web Claude) updates the prompt or the contract → next session
    18	runs cleaner.
    19	
    20	The repo has been running these loops since the beginning, but they
    21	became explicit and named after 2026-04-23 when
    22	`docs/ORCHESTRATION.md` was authored as v1.0 and amended through
    23	v1.1 same evening. Six loops are clearly visible in the decision
    24	ledgers; more exist but didn't get named.
    25	
    26	## Loop 1 — STOP discipline
    27	
    28	**Symptom (pre-2026-04-23).** CC stopped on every plan-vs-reality
    29	mismatch. Off-by-one file counts, wrong commit messages, mechanical
    30	ordering details — each got a 5-blocker STOP report and a round-trip
    31	to architect. Cleanup-baseline session (2026-04-23) hit four such
    32	stops in one short session.
    33	
    34	**Architect amendment.** ORCHESTRATION.md §13 STOP discipline + §13.5
    35	autonomy band: codify what CC may adapt inline (`Plan said / Reality
    36	/ Adapted / Outcome` in the ledger) vs what truly requires escalation
    37	(irreversible action, semantic ambiguity, architect-domain decision).
    38	
    39	**Outcome.** Subsequent sessions run with relaxed stopping discipline.
    40	Architect end-of-day review catches anything that should have been
    41	a stop. Memory captures the rule:
    42	[`feedback_stop_discipline.md`](https://internal/auto-memory).
    43	
    44	## Loop 2 — recon before plan
    45	
    46	**Symptom.** Plans were built on stale recon reports. The
    47	2026-04-23 session opened with 3 modified tracked files + 34
    48	untracked at root + branch != master, none of which the plan
    49	anticipated.
    50	
    51	**Architect amendment.** §10 session-start checklist: read
    52	ORCHESTRATION.md + CLAUDE.md, `git status`, `git branch --show-
    53	current`, `git worktree list`, check pending consultations and
    54	latest decision ledger BEFORE running any plan step.
    55	
    56	**Outcome.** Subsequent sessions catch dirty-tree state and stale
    57	branch up front, surface to architect cleanly without 5-blocker
    58	reports.
    59	
    60	## Loop 3 — model version drift
    61	
    62	**Symptom.** Multi-model consultation skill named specific model
    63	versions (gpt-5.4 high, gemini-2.5-pro). Models updated, skills
    64	didn't. Sessions either ran on outdated models silently or had to
    65	discover availability ad hoc.
    66	
    67	**Architect amendment.** Skill carries explicit fallback rules
    68	(`gpt-5.5 → gpt-5.4` if not yet released) and a 3-token probe
    69	before any batch (§3.7). When architect references a newer
    70	version, architect wins; update the skill.
    71	
    72	**Outcome.** Overnight swarm 2026-04-24 ran the probe, confirmed
    73	gpt-5.5 + gemini-2.5-pro available, no fallback. 2026-04-26 vault
    74	build using gpt-5.5 + gemini-3.1-pro-preview ran clean.
    75	
    76	## Loop 4 — tool call budget
    77	
    78	**Symptom (pre-2026-04-23 era).** Web Claude (architect) was
    79	editing files in the repo directly during architect sessions,
    80	consuming the architect's own tool call budget for mechanical
    81	output that CC could have done.
    82	
    83	**Architect amendment.** ORCHESTRATION.md §3 role matrix: architect
    84	provides mission + constraints; CC owns code edits, branch creation,
    85	merges. Architect can edit files in emergencies but the default is
    86	CC.
    87	
    88	**Outcome.** Architect tool call budget reserved for high-leverage
    89	work (specs, reviews, decisions). CC handles the mechanical surface.
    90	
    91	## Loop 5 — skill loading lifecycle
    92	
    93	**Symptom.** Skills are loaded at harness session start. If a skill
    94	is committed mid-session (e.g. `multi-model-consultation` via
    95	`9a1a100` on 2026-04-23), the running CC session does not see it
    96	until restart. The 2026-04-24 b2b4fb5 investigation session had to
    97	manually `Read` the skill file to load it.
    98	
    99	**Workaround.** Manual `Read` of the skill markdown to bring it
   100	into context — observed working pattern, recorded in the
   101	investigation ledger.
   102	
   103	**Pending architect action.** ORCHESTRATION.md edit to document the
   104	skill-registry-refresh-requires-restart constraint. (Open as of
   105	2026-04-26.)
   106	
   107	## Loop 6 — self-review playbook
   108	
   109	**Symptom.** Codex review cycles on block commits were inconsistent
   110	— some blocks got Codex review, some didn't, and the FAIL response
   111	flow wasn't standardized.
   112	
   113	**Artifact.** `docs/CODEX_SELF_REVIEW_PLAYBOOK.md`. Defines:
   114	- When to call Codex (initial block commit + amend after FAIL).
   115	- Required prompt template — playbook + `CLAUDE.md` mandate
   116	  `Model: gpt-5.4 / Reasoning effort: high`. Sessions from
   117	  2026-04-24 onward used `gpt-5.5` (newer, available on Codex CLI),
   118	  with the playbook still pinned at `gpt-5.4` as the documented
   119	  minimum. If using `gpt-5.5`, ledger the version choice in the
   120	  session record.
   121	- Autonomy on FAIL: CRITICAL/HIGH → amend without asking;
   122	  design-decision FAIL → STOP + escalate.
   123	- 3-amend cycle limit.
   124	- Final report to architect: SHA + Codex PASS summary + residual
   125	  risks.
   126	
   127	**Outcome.** Block-level work since 2026-04-23 has predictable
   128	review cadence. Architect reads result, not process.
   129	
   130	## Open loops (as of 2026-04-26)
   131	
   132	- **Skill-registry refresh** (Loop 5 above) — pending edit.
   133	- **ORCHESTRATION.md §5.4 wording cleanup** ("already gitignored" →
   134	  "enforced invariant" since `587bea8`) — open from
   135	  [[40 Decisions/2026-04-23-cleanup-baseline]].
   136	- **Retroactive semantic versioning** (v0.34.0..v0.38.0) — postponed
   137	  pending B1 mitigation.
   138	- **§11 known-active-plans table** updates trail by ~1 session
   139	  every architect cycle.
   140	
   141	## The calibration principle (§13.6)
   142	
   143	The point of the loops is that **rules that over-stop waste
   144	architect time, and rules that under-stop risk silent breakage**.
   145	The session ledger + handoff are the corrective mechanism: relaxed
   146	stopping is fine because the architect's end-of-day ledger review
   147	catches anything that should have been a stop.
   148	
   149	If that review pattern breaks down (architect misses something
   150	important in the ledger), specific rules tighten. Otherwise, the
   151	default is autonomy band. The loops are what calibrate that band.
   152	
   153	## See also
   154	
   155	- [[50 Workflow/ORCHESTRATION contract]] §13
   156	- [[40 Decisions/2026-04-23-cleanup-baseline]]
   157	- [[40 Decisions/2026-04-24-b2b4fb5-investigation]]
   158	- [[50 Workflow/Multi-model consultation]]
   159	- [[50 Workflow/Overnight swarm pattern]]

===== /Users/vladimir/Vault/CryoDAQ/50 Workflow/Multi-model consultation.md =====
     1	---
     2	source: .claude/skills/multi-model-consultation.md (v post-2026-04-24)
     3	last_synced: 2026-04-26
     4	status: digest — read full skill for templates and routing detail
     5	---
     6	
     7	# Multi-model consultation — digest
     8	
     9	CC's skill for invoking external models. Full text at
    10	`~/Projects/cryodaq/.claude/skills/multi-model-consultation.md`
    11	— this is a quick map.
    12	
    13	## §0. When NOT to use
    14	
    15	Most of the time, don't. External consultation is expensive
    16	(tokens, wall-clock, synthesis overhead) and injects noise. The
    17	2026-04-21..23 swarm cycle that produced 12 untracked review
    18	markdowns happened because consultation became reflex.
    19	
    20	Skip when:
    21	- Task is mechanical.
    22	- CC's reasoning produces a clear answer + architect plan is
    23	  complete.
    24	- Question is so scoped a unit test trivially verifies.
    25	- Budget tight and architect is available.
    26	
    27	Use only when **all three** hold:
    28	1. Decision has meaningful downside cost if wrong (safety,
    29	   architecture, irreversible migration, hardware behavior, merge).
    30	2. CC's reasoning is not confident (competing hypotheses, missing
    31	   domain knowledge, non-obvious tradeoff).
    32	3. Architect has either explicitly asked for a cross-check OR is
    33	   unavailable and the task can't wait.
    34	
    35	## §1. Routing
    36	
    37	| Model | Strength | Use for | Don't use for |
    38	|---|---|---|---|
    39	| **Codex (gpt-5.5 / high)** | Adversarial code review with file:line refs. Concurrency, race conditions, IPC, subprocess, socket state. Terse FAIL/PASS verdicts. | Diff review pre-commit; specific bug hypothesis test; ZMQ / asyncio / subprocess code; ≤ 500-line diffs. | Long-prose strategy; "review the entire repo"; > 10 files at once. |
    40	| **Gemini (3.1 Pro Preview)** | Wide-context architectural analysis. 1M-token window. Multi-file drift, doc-vs-code reconciliation, cross-cutting patterns. | Wide audit; doc-vs-code reconciliation; second opinion when Codex too narrow; loading entire spec + src tree. | Short-scope bug review (use Codex); < 500-word output (Gemini overwrites); quick yes/no. |
    41	| **GLM-5.1 (via Chutes)** | Cheap. RU↔EN translation, mechanical transforms, second opinion check. | Translation; mechanical-transform draft (CC verifies); batch rename / rewrite; one-claim cheap second opinion. | Anything safety-critical; anything that lands unchecked on master; primary coordination (always CC). |
    42	| **Kimi K2.6 (via Chutes)** | 256K context, math-heavy, language tasks; lower hallucination than GLM in known domain. | Long-document analysis; math; second opinion on language. | Narrow code debugging vs Codex; trust unverified introspection. |
    43	
    44	## §1.x identity-leak hazard
    45	
    46	GLM and Kimi will sometimes claim "I am Claude" on introspection —
    47	trained partly on Claude outputs. Authority on what model
    48	responded: `tail ~/.claude-code-router/logs/ccr-*.log | grep '"model":"'`.
    49	Never trust self-identification.
    50	
    51	## §2. Brief templates
    52	
    53	§2.1 Codex brief opens with:
    54	```
    55	Model: gpt-5.5
    56	Reasoning effort: high
    57	```
    58	+ Mission / Context files / Specific questions / Output format
    59	(severity / file:line / fix) / Scope fence / Response file path.
    60	
    61	§2.2 Gemini brief opens with:
    62	```
    63	Model: gemini-3.1-pro-preview
    64	```
    65	+ same shape, plus an explicit length cap (Gemini overwrites
    66	without it).
    67	
    68	## §3. Invocation patterns
    69	
    70	| Pattern | When | How |
    71	|---|---|---|
    72	| Single | Routine review | One Codex foreground |
    73	| Writer-reviewer | Adversarial code review | CC writes, Codex reviews |
    74	| Adversarial pair | High-risk decision | Codex literal + Gemini structural in parallel |
    75	| Wide audit | Architectural drift | Gemini full-context, then Codex on specific findings |
    76	
    77	§3.7 model-string probe: before any batch dispatch, send a 3-token
    78	round-trip ("Say 'probe ok'") to confirm the upstream model name
    79	resolves. If `gpt-5.5` not yet released or rejected → fall back to
    80	`gpt-5.4`. Update skill as model versions evolve.
    81	
    82	## §4. Slop check / retry
    83	
    84	§4.2 — junk response criteria: <500 words of actual content; no
    85	file:line refs; evasive on specific questions. Log as junk in
    86	ledger; retry once with tighter prompt OR drop that consultant
    87	from the decision.
    88	
    89	## §5. Synthesis format
    90	
    91	After all consultations: `synthesis.md` covers
    92	- summary of each consultant
    93	- points of agreement
    94	- points of disagreement + CC's reasoning on which side wins
    95	- final decision (code / test / propose / drop)
    96	
    97	Synthesis is the durable artifact; raw consultant output is
    98	ephemeral.
    99	
   100	## §6. Codex sandbox / response gotchas
   101	
   102	- Codex defaults to **read-only** filesystem sandbox. Cannot write
   103	  the response file itself. Two workarounds:
   104	  1. Pass `--sandbox workspace-write` (for write-allowed sessions).
   105	  2. Capture stdout via shell redirect:
   106	     `codex exec ... > RESPONSES/....md`. **Proven path** for
   107	     overnight batches since 2026-04-24.
   108	- Codex prints full reasoning transcript (100–300 KB typical).
   109	  Final verdict + findings at the END of the response file. Use
   110	  `tail -250` or parse for the last `Model: gpt-5.X` marker.
   111	- CLI v0.124.0+ requires `--sandbox read-only|workspace-write|
   112	  danger-full-access` (rejects the older `workspace-read` value).
   113	  Combine with `--skip-git-repo-check --cd <repo-root>` if
   114	  invoking from outside the trusted repo.
   115	
   116	## §7. Gemini operational notes
   117	
   118	- `--yolo` required when the brief asks Gemini to read repo files
   119	  or run shell commands; default approval mode blocks
   120	  `run_shell_command`.
   121	- Per-minute rate limit: 5 parallel Gemini-3.1-pro calls exhaust
   122	  capacity within ~20 s. Default pattern when ≥4 jobs:
   123	  **Codex parallel + Gemini serial chain with 30 s gaps**. See
   124	  [[50 Workflow/Overnight swarm pattern]].
   125	
   126	## §8. When the architect is unavailable
   127	
   128	§8 of ORCHESTRATION.md takes precedence. CC works on previously
   129	architected plans, doesn't invent directions, doesn't start new
   130	feature branches. Consultations during this window are scoped to
   131	the active plan only.
   132	
   133	## See also
   134	
   135	- [[50 Workflow/ORCHESTRATION contract]] §4 — protocol that
   136	  consultations operate under
   137	- [[50 Workflow/Overnight swarm pattern]] — when to use 10-job
   138	  batches
   139	- [[30 Investigations/Codex H2 wrong hypothesis]] — what happens
   140	  when a consultant's confident reasoning is wrong

===== /Users/vladimir/Vault/CryoDAQ/50 Workflow/ORCHESTRATION contract.md =====
     1	---
     2	source: docs/ORCHESTRATION.md (v1.1, 2026-04-23 + amendments)
     3	last_synced: 2026-04-26
     4	status: digest — read repo doc for full rules
     5	---
     6	
     7	# ORCHESTRATION contract — digest
     8	
     9	`docs/ORCHESTRATION.md` is the authoritative agent-orchestration
    10	contract for the CryoDAQ repo. This page is a digest. **Read the
    11	repo doc end-to-end at the start of every CC session** —
    12	[[_meta/glossary]] flags this as a memory invariant.
    13	
    14	## §1. Why this document exists
    15	
    16	Between 2026-04-21 and 2026-04-23 the repo accumulated 4 parallel
    17	feature branches (none merged), 9 duplicate commits, 12 untracked
    18	review markdowns at root, 4 conflicting orchestrator state
    19	directories, and a hardening-vs-feature collision that produced a
    20	misattribution. None of this happened because individual models
    21	were bad. It happened because there was no central coordinator.
    22	
    23	## §2. Core principle
    24	
    25	**Claude Code is the central coordinator.** Every other model —
    26	Codex CLI, Gemini CLI, GLM, Kimi, DeepSeek, metaswarm — operates in
    27	**consultant mode**: text in, text out, CC reads and converts to
    28	final action. Consultants never push, never branch, never write
    29	files in the repo except via CC.
    30	
    31	## §3. Role matrix
    32	
    33	Architect (Vladimir + web Claude during architect sessions) provides
    34	mission and constraints. CC executes. Consultants advise. **One
    35	coordinator at a time** — no parallel CC sessions on the same
    36	branch.
    37	
    38	## §4. Consultant invocation protocol
    39	
    40	Brief at
    41	`artifacts/consultations/<YYYY-MM-DD>/<topic>/<consultant>.prompt.md`
    42	with mission / context files / numbered questions / expected output
    43	format / response file path. Response lands at `*.response.md`.
    44	After all consultations CC writes a `synthesis.md` covering
    45	agreement / disagreement / final decision.
    46	
    47	**Synthesis is the durable artifact.** Raw consultant output can be
    48	deleted after 30 days; synthesis stays.
    49	
    50	§4.4 anti-prompts: "review the entire repo" / "give me 10 things to
    51	improve" / "what do you think overall" — invite slop. Valid prompts
    52	are scoped and concrete.
    53	
    54	## §5. Branch and merge discipline
    55	
    56	| Type | Pattern | Lifetime |
    57	|---|---|---|
    58	| Main | `master` | forever |
    59	| Feature | `feat/<slug>` | ≤ 2 days |
    60	| Experiment | `experiment/<slug>` | ≤ 1 day |
    61	| Hotfix | `hotfix/<slug>` | ≤ 4 hours |
    62	| Architect fork | `arch/<yyyy-mm-dd>-<purpose>` | until merged |
    63	
    64	**One active feature branch.** Branches live ≤ 2 days. After 3+
    65	days CC auto-aborts at next session. Worktree dirs in `.worktrees/`
    66	must match branch names exactly. Commit body must include
    67	`Ref:`, `Batch:` (if multi-commit), and `Risk:` for changes to
    68	`launcher.py` / `engine.py` / `safety_manager.py` / `zmq_*.py`.
    69	
    70	## §6. Artifact discipline
    71	
    72	Strict root whitelist (`README.md`, `CLAUDE.md`, `CHANGELOG.md`,
    73	`CODEX_ARCHITECTURE_CONTROL_PLANE.md`, `ROADMAP.md`,
    74	`PROJECT_STATUS.md`, `RELEASE_CHECKLIST.md`,
    75	`DOC_REALITY_MAP.md` (historical, may be removed),
    76	`LICENSE`, `THIRD_PARTY_NOTICES.md`, `CC_PROMPT_*.md`, `HANDOFF_*.md`,
    77	`SESSION_DETAIL_*.md`). Audit / review / hardening output goes
    78	under `docs/audits/<date-slug>/` or
    79	`artifacts/consultations/<date>/<topic>/`, never at root.
    80	
    81	Decision ledger: every session CC writes
    82	`docs/decisions/<YYYY-MM-DD>-session.md` with `## HH:MM —
    83	<decision>` blocks (Thesis / Reasoning / Decision / Consulted /
    84	Open). The ledger is the long-term memory.
    85	
    86	## §7. Hardening + feature interaction rule
    87	
    88	**The rule that exists because of `b2b4fb5` vs IV.7.** Before
    89	landing a hardening / tightening change, check whether it could
    90	affect any active feature branch. If yes, hold or merge into the
    91	feature branch and retest. If no, document why not in the commit
    92	`Risk:` line. Active branches are visible via `git worktree list`
    93	— check before tightening shared infra. See
    94	[[30 Investigations/b2b4fb5 hardening race]].
    95	
    96	## §8. Architect-absent operating mode
    97	
    98	When architect is unavailable (quota window): CC continues
    99	**only on previously-architected plans**. No new directions, no
   100	new feature branches for initiative work. Bug / regression fixes on
   101	in-progress work are OK. End-of-session handoff goes to
   102	`artifacts/handoffs/<date>-cc-to-architect.md`.
   103	
   104	## §9. Document evolution
   105	
   106	This contract is authoritative but not immutable. Disagreement
   107	goes through the architect via decision-ledger note → next
   108	architect session → commit. Do **not** silently bypass.
   109	
   110	## §10. Session start checklist
   111	
   112	Read this doc end-to-end + `CLAUDE.md`. `git status`,
   113	`git branch --show-current`, `git worktree list`. Check
   114	`artifacts/consultations/` for unsynthesized responses. Check
   115	`docs/decisions/` for the latest session ledger. Stale
   116	(>2 day) feature branch detected → block work, surface to
   117	architect.
   118	
   119	## §11. Known active plans
   120	
   121	Tracked table — only plans listed here can be worked on. If a
   122	consultant claims to be working on something else, STOP.
   123	
   124	## §12. Failure-mode reference
   125	
   126	Six historical failure modes are enumerated as the rationale
   127	behind the rules:
   128	
   129	1. Parallel rewrites (`codex/b1-truth-recovery` vs
   130	   `codex/safe-merge-b1-truth-recovery`).
   131	2. Root-directory markdown flood (12 ungoverned `.md` at root).
   132	3. Hardening / feature collision (`b2b4fb5` × IV.7).
   133	4. No-leader multi-agent drift (five agents reviewing without
   134	   synthesis).
   135	5. Lost context (untracked architect dump for 3 days).
   136	6. Over-strict stopping — added retroactively after the
   137	   2026-04-23 cleanup-baseline session
   138	   ([[40 Decisions/2026-04-23-cleanup-baseline]]).
   139	
   140	## §13. STOP discipline and autonomy band (added 2026-04-23)
   141	
   142	§13.1 — when CC must STOP: irreversible data loss / git rewrite,
   143	genuine semantic ambiguity, architect-domain decision, sensitive
   144	material, file > 100 KB about to be silently lost, real test
   145	failure, junk consultant response.
   146	
   147	§13.2 — when CC must NOT stop, adapt instead: 1-line plan
   148	inaccuracy, mechanical detail differs, untracked file would be
   149	lost (preserve to archive then proceed — the "no delete" rule is a
   150	PRESERVE rule, not a STOP rule).
   151	
   152	§13.3 — adaptations are recorded inline in the session ledger as
   153	`Plan said / Reality / Adapted / Outcome`.
   154	
   155	§13.4 — the preserve-vs-delete clarification: archive routine
   156	plan-document patterns and proceed; STOP only on > 100 KB,
   157	sensitive content, credential paths, or binary garbage.
   158	
   159	§13.5 — autonomy band explicitly granted for commit message
   160	wording, file-path adjustments, mechanical step reordering, side-
   161	commits to preserve untracked files. NOT granted for branch
   162	merges outside plan, file deletions outside `git branch -D`
   163	targets, history rewrites, consultant invocations on already-
   164	covered decisions, new feature branches under §8.
   165	
   166	§13.6 — calibration principle: rules that over-stop waste
   167	architect time; rules that under-stop risk silent breakage. The
   168	ledger + handoff are the mechanism that lets CC run with relaxed
   169	stopping discipline; architect end-of-day review catches anything
   170	that should have been a stop.
   171	
   172	## See also
   173	
   174	- `~/Projects/cryodaq/docs/ORCHESTRATION.md` — full text (~600 lines)
   175	- [[50 Workflow/Multi-model consultation]] — skill that operates
   176	  under §4
   177	- [[50 Workflow/Calibration loops history]] — how prompts and CC
   178	  behavior evolved into this contract
   179	- [[40 Decisions/2026-04-23-cleanup-baseline]] — first session run
   180	  under this contract

===== /Users/vladimir/Vault/CryoDAQ/50 Workflow/Overnight swarm pattern.md =====
     1	---
     2	source: CC_PROMPT_OVERNIGHT_SWARM_2026-04-24.md; docs/decisions/2026-04-24-overnight-swarm-launch.md; .claude/skills/multi-model-consultation.md §6/§7
     3	last_synced: 2026-04-26
     4	status: synthesized — pattern reusable for future overnight runs
     5	---
     6	
     7	# Overnight swarm pattern
     8	
     9	CC dispatching 10 scoped consultation jobs to Codex + Gemini in
    10	parallel, sleeping while they run, synthesizing in the morning.
    11	Pattern validated 2026-04-24 (10/10 jobs landed) and reused 2026-04-26
    12	for vault build audits.
    13	
    14	## When the pattern fits
    15	
    16	- Architect has identified ≥ 4 independent questions where second-
    17	  model judgment would help.
    18	- Each question has a scoped brief (one diff, one hypothesis, one
    19	  module's drift, etc.) — not "review the entire repo" slop.
    20	- Architect is going to sleep / stepping away; the time can be
    21	  spent productively or wasted entirely.
    22	- All briefs cleanly fit the
    23	  [[50 Workflow/Multi-model consultation|multi-model consultation
    24	  skill]] §1.x routing.
    25	
    26	## What the prompt looks like
    27	
    28	A swarm prompt at root (`CC_PROMPT_OVERNIGHT_SWARM_<date>.md`)
    29	enumerates jobs:
    30	
    31	- 5 Codex briefs (`codex-NN-<topic>`) — narrow adversarial review
    32	  questions
    33	- 5 Gemini briefs (`gemini-NN-<topic>`) — wide-context structural
    34	  questions
    35	
    36	Each brief follows skill §2 templates. Briefs have anti-anchoring
    37	rules where the same question goes to both models (alphabetical
    38	ordering of options, neutral tone, no hint at expected answer).
    39	
    40	## Dispatch (proven 2026-04-24)
    41	
    42	CLI-direct, not slash-command-driven. Codex parallel, Gemini
    43	serial:
    44	
    45	```bash
    46	# Codex — 5 in parallel
    47	for n in 01 02 03 04 05; do
    48	  nohup bash -c '
    49	    codex exec \
    50	      -m gpt-5.5 -c model_reasoning_effort="high" \
    51	      --sandbox read-only --skip-git-repo-check \
    52	      --cd ~/Projects/cryodaq \
    53	      < BRIEFS/codex-'"$n"'-...prompt.md \
    54	      > RESPONSES/codex-'"$n"'-...response.md 2>&1
    55	  ' </dev/null >/dev/null 2>&1 &
    56	done
    57	
    58	# Gemini — single serial chain (rate limit + tool access)
    59	nohup bash -c '
    60	  for brief in BRIEFS/gemini-*.prompt.md; do
    61	    response=$(echo "$brief" | sed "s/BRIEFS/RESPONSES/; s/prompt/response/")
    62	    gemini -m gemini-3.1-pro-preview --yolo \
    63	      -p "$(cat "$brief")" \
    64	      > "$response" 2>&1
    65	    sleep 30
    66	  done
    67	' </dev/null >/dev/null 2>&1 &
    68	```
    69	
    70	Tracking PIDs go to a `.pids` file under the artifacts dir for
    71	later sweep + diagnostic.
    72	
    73	## What worked (2026-04-24, 10/10)
    74	
    75	- Codex parallel held up. Each Codex (`gpt-5.5 / high`) ran in
    76	  ~1–10 min wall-clock per brief.
    77	- Codex `gpt-5.5` model name accepted on first try after a
    78	  3-token probe. §3.7 fallback to gpt-5.4 did not fire.
    79	- Briefs landed clean responses with file:line refs.
    80	
    81	## What didn't (and the workaround)
    82	
    83	- **Gemini parallel rate-limited.** 5 simultaneous gemini-2.5-pro
    84	  calls exhausted per-minute capacity within ~20 s. Variants of
    85	  "Your quota will reset after 0s".
    86	- **Gemini default approval mode blocked tool access.**
    87	  `run_shell_command` not approved → Gemini couldn't read files /
    88	  run `git show` even though the brief said to.
    89	
    90	Workaround: kill the parallel Gemini wrapper PIDs (carefully —
    91	avoid pre-existing unrelated gemini processes), zero out partial
    92	error response files, relaunch as a single serial chain with 30 s
    93	gaps and `--yolo`. Single tracking PID.
    94	
    95	Cost: serial chain bottoms out at ~30–60 min for 5 jobs vs
    96	Codex's true-parallel ~10–15 min. Acceptable for overnight.
    97	
    98	## Morning retrieval (Phase 6–9 of the prompt)
    99	
   100	1. **Verify completion.** `.pids` file shows wrapper exit. Lost /
   101	   slop cases (skill §4.2: < 500 words, no file:line refs,
   102	   evasive) → retry once with tighter brief.
   103	2. **Per-stream synthesis.** Group Codex + Gemini briefs by topic
   104	   stream (e.g. "B1 root cause" + "transport drift") into single
   105	   `STREAM_SYNTHESES/<stream>.md`.
   106	3. **Master summary.** `MASTER_SUMMARY.md` with stream decisions +
   107	   priority action list + TL;DR.
   108	4. **Single commit** of the whole `artifacts/consultations/<date>/`
   109	   tree + synthesis + summary, batch-labeled.
   110	
   111	## Adaptations from plan (§13.3 ledger format)
   112	
   113	Adaptations recorded inline in the session ledger:
   114	`Plan said / Reality / Adapted / Outcome`. The 2026-04-24 launch
   115	recorded three:
   116	
   117	- CLI-direct dispatch instead of `/codex:rescue` slash form.
   118	- Model probe before batch (gpt-5.5 + gemini-2.5-pro both passed
   119	  3-token probe).
   120	- Gemini parallel → serial chain after rate-limit + tool-access
   121	  failures.
   122	
   123	## Reuse pattern
   124	
   125	The same shape works for any "scoped, parallel, can-tolerate-slop-
   126	filter" review. Examples:
   127	
   128	- Vault audit gates (this 2026-04-26 build) — Codex literal +
   129	  Gemini structural per phase.
   130	- Multi-stream architectural review (2026-04-24 syntheses).
   131	- D-bucket review (drop / merge classification across N branches).
   132	
   133	What does NOT fit the pattern:
   134	
   135	- Bug reproduction. Needs interactive iteration; no overnight
   136	  acceleration.
   137	- Single ambiguous decision. One scoped Codex review is enough;
   138	  swarm is overkill.
   139	- Synthesis-heavy work. Models can't synthesize; CC has to do
   140	  that next morning.
   141	
   142	## See also
   143	
   144	- [[50 Workflow/ORCHESTRATION contract]] §4 — consultation protocol
   145	- [[50 Workflow/Multi-model consultation]] — skill that gates
   146	  per-job decisions
   147	- [[40 Decisions/2026-04-24-overnight-swarm-launch]] — launch
   148	  ledger from the proven run
   149	- [[40 Decisions/2026-04-24-d1-d4a-execution]] — what came out of
   150	  the syntheses

===== /Users/vladimir/Vault/CryoDAQ/50 Workflow/_index.md =====
     1	---
     2	source: skeleton stub
     3	last_synced: 2026-04-26
     4	status: index
     5	---
     6	
     7	# 50 Workflow
     8	
     9	Orchestration contract, multi-model consultation skill, overnight swarm
    10	pattern, and the meta-narrative of how prompts evolved.
    11	
    12	- [[50 Workflow/ORCHESTRATION contract]]
    13	- [[50 Workflow/Multi-model consultation]]
    14	- [[50 Workflow/Overnight swarm pattern]]
    15	- [[50 Workflow/Calibration loops history]]
    16	
    17	<!-- TODO: add per-skill digests if more skills land in .claude/skills/ -->

===== /Users/vladimir/Vault/CryoDAQ/60 Roadmap/F-table backlog.md =====
     1	---
     2	source: ROADMAP.md (F-table, 2026-04-20)
     3	last_synced: 2026-04-26
     4	status: synthesized
     5	---
     6	
     7	# F-table backlog
     8	
     9	Feature roadmap from `ROADMAP.md`. Status taken at IV.4 close
    10	(2026-04-20). Refresh by re-reading `ROADMAP.md` Quick Index when
    11	status changes.
    12	
    13	| # | Feature | Status | Effort | ROI | Notes |
    14	|---|---|---|---|---|---|
    15	| F1 | Parquet archive wire-up | ✅ shipped (IV.4) | S | H | UI export button + pyarrow base dep |
    16	| F2 | Debug mode toggle (verbose logging) | ✅ shipped (IV.4) | S | H | QSettings + Settings menu |
    17	| F3 | Analytics placeholder widgets → data wiring | ⬜ queued | M | M | Needs `cooldown_history_get` engine command |
    18	| F4 | Analytics lazy-open snapshot replay | ⬜ queued | S | M | Cache + replay on overlay construct |
    19	| F5 | Engine events → Hermes webhook | ⬜ queued | M | M | Blocked on Hermes service deployment |
    20	| F6 | Auto-report on experiment finalize | ✅ shipped (IV.4) | S | H | Verified + per-experiment override |
    21	| F7 | Web API readings query extension | ⬜ queued | L | M | Needs auth or loopback-only default |
    22	| F8 | Cooldown ML prediction upgrade | 🔬 research | L | M | Needs training set + xgboost notebook |
    23	| F9 | Thermal conductivity auto-report (TIM) | 🔬 research | M | H | Physics collab with Vladimir; GOST Р 54500.3-2011 |
    24	| F10 | Sensor diagnostics → alarm integration | ⬜ queued | M | M | Anomaly → WARNING/CRITICAL pipeline |
    25	| F11 | Shift handover enrichment | ✅ shipped (IV.4) | S | H | Telegram export deferred |
    26	| F12 | Experiment templates UI editor | ⬜ queued | M | L | Custom-fields + preview + import/export |
    27	| F13 | Vacuum leak rate estimator | ⬜ queued | M | M | dP/dt × V_chamber after valve close |
    28	| F14 | Remote command approval (Telegram) | ⬜ queued | M | L | Two-factor confirm; safety review needed |
    29	| F15 | Linux AppImage / .deb package | ⬜ queued | L | L | Post-0.18.0; AppImage preferred |
    30	| F16 | Plugin hot-reload SDK + examples | ⬜ queued | M | L | `plugin_loader` exists; SDK + examples missing |
    31	| F17 | SQLite → Parquet cold-storage rotation | ⬜ queued | M | M | Depends on F1 |
    32	| F18 | CI/CD upgrade (coverage, matrix, releases) | ⬜ queued | M | L | Phase 2e residual |
    33	
    34	Effort: **S** ≤200 LOC · **M** 200–600 LOC · **L** >600 LOC.
    35	ROI: **H** immediate user value · **M** clear but deferred · **L** nice-to-have.
    36	
    37	## Planned batches
    38	
    39	| Batch | Target tag | Status | Scope |
    40	|---|---|---|---|
    41	| IV.4 — Safe features | 0.34.0 | ✅ closed `7cb5634` (2026-04-20) | F1 / F2 / F6 / F11 |
    42	| IV.5 — Stretch features | 0.35.0 | ⬜ pending B1 fix | F3 / F5 / F17 |
    43	| IV.6 — ZMQ cmd-plane hardening | n/a (defense-in-depth) | ✅ partial `be51a24` | Per-cmd ephemeral REQ + watchdog. Does NOT close B1 |
    44	| IV.7 — `ipc://` transport experiment | n/a (still investigating) | 🔧 H3 confirmed (b2b4fb5 race), R1 repair shipped, ipc:// still subject to B1 idle-death after ~80s | See [[30 Investigations/B1 ZMQ idle-death]] |
    45	
    46	## Collaboration mode
    47	
    48	- **Autonomous CC batches:** F1, F2, F3, F4, F5, F7, F10, F11, F12,
    49	  F13, F14, F16, F17, F18.
    50	- **Physics collab with Vladimir:** F8, F9, F13.
    51	- **Infrastructure collab:** F5 (Hermes deployment), F15 (Linux
    52	  packaging).
    53	
    54	## See also
    55	
    56	- [[60 Roadmap/Versions]] — tag history
    57	- [[30 Investigations/B1 ZMQ idle-death]] — blocking 0.34.0 tag
    58	- [[50 Workflow/ORCHESTRATION contract]] — how batches are scoped

===== /Users/vladimir/Vault/CryoDAQ/60 Roadmap/Versions.md =====
     1	---
     2	source: git tag -l; git log; CHANGELOG.md (Unreleased + recent); PROJECT_STATUS.md; ROADMAP.md
     3	last_synced: 2026-04-26
     4	status: synthesized
     5	---
     6	
     7	# Versions
     8	
     9	The CryoDAQ tag history is **partial**. `pyproject.toml` carries the
    10	intended next version, but most package-state increments between
    11	v0.13.0 (CLAUDE.md "Current package metadata") and the present have
    12	not been tagged. Retroactive tagging (`v0.34.0..v0.38.0` plan) is
    13	queued per `docs/decisions/2026-04-23-cleanup-baseline.md`.
    14	
    15	## Tag table
    16	
    17	| Version | Date | Status | Scope summary | Closing commit |
    18	|---|---|---|---|---|
    19	| `v0.33.0` | (last released tag) | shipped | Phase I.1 shell + design system v1.0.1 + IPC/REP hardening + theme switcher | tag points at the v0.33.0 sha (see `git show v0.33.0`) |
    20	| `v0.34.0` | (planned) | **blocked** | IV.4 safe features batch (F1 Parquet, F2 debug toggle, F6 auto-report verify, F11 shift handover); Phase II.1–II.6/II.13 cleanup. **Blocked by B1 ZMQ idle-death** ([[30 Investigations/B1 ZMQ idle-death]]). | `7cb5634` (IV.4 close) — pending real `git tag` |
    21	| Retroactive tags v0.34.0..v0.38.0 | (planned) | postponed | Per [[40 Decisions/2026-04-23-cleanup-baseline]], pre-2026-04-20 dev increments may be retroactively tagged once v0.34.0 ships. (Wording is per source ledger; chronologically it covers a future tag-pass over historical work.) | n/a |
    22	| `design-system-v1.0.1` | 2026-04-15..17 | non-package marker | Design system release marker, not a package version. | `1c61268` (CRITICAL domain cleanup) |
    23	| `pre-tier1-merge-backup-2026-04-14` | 2026-04-14 | safety marker | Pre-merge backup tag from before Tier 1 work. | n/a |
    24	
    25	Current branch tip (`master`): `cabd854 docs: Q4 equivalence check
    26	synthesis + D1 closure`. `pyproject.toml` reads `0.34.0.dev0` (bumped
    27	in `5030682`).
    28	
    29	## Pending tag — v0.34.0
    30	
    31	Per `ROADMAP.md`, IV.4 closed at `7cb5634` (2026-04-20) but the
    32	**v0.34.0 git tag has not been issued** because B1 (ZMQ command
    33	channel idle-death) still reproduces. Once B1 is mitigated via the
    34	IV.7 ipc:// path or another route, v0.34.0 can ship.
    35	
    36	Confirmed since IV.4 close:
    37	- Q4 equivalence check PASS (Codex gpt-5.5/high) on the b2b4fb5 R1
    38	  repair ([[40 Decisions/2026-04-24-d1-d4a-execution]] 22:16
    39	  addendum). Branch `feat/b2b4fb5-repair` merged via `89b4db1`.
    40	- IV.6 ephemeral-REQ + watchdog landed (`be51a24`); does NOT close
    41	  B1 but stays in master as defense-in-depth.
    42	- Thyracont `validate_checksum` wired through (`aabd75f`).
    43	- `xml_safe` sanitizer for python-docx (`74dbbc7`) — fixes auto-report
    44	  failure with real Keithley `\x00` resource strings.
    45	
    46	## Release discipline
    47	
    48	Per `CLAUDE.md` "Дисциплина релизов": each new tag updates
    49	`CHANGELOG.md` (Added / Changed / Fixed / Infrastructure / Known
    50	Issues / Test baseline / Tags / Selected commits) and only updates
    51	`README.md` / `CLAUDE.md` if user-facing facts changed. No re-tagging
    52	to fold post-tag docs updates; no auto-update hooks.
    53	
    54	## See also
    55	
    56	- [[60 Roadmap/F-table backlog]] — F1..F18 feature index
    57	- [[30 Investigations/IV.6 cmd plane hardening]] — the partial
    58	  mitigation that doesn't close B1
    59	- [[40 Decisions/2026-04-23-cleanup-baseline]] — retroactive-tag plan
    60	- [[40 Decisions/2026-04-24-b2b4fb5-investigation]] — H3 confirmed,
    61	  R1 repair scope
    62	- `CHANGELOG.md` (in repo) — full per-release record

===== /Users/vladimir/Vault/CryoDAQ/60 Roadmap/_index.md =====
     1	---
     2	source: skeleton stub
     3	last_synced: 2026-04-26
     4	status: index
     5	---
     6	
     7	# 60 Roadmap
     8	
     9	Where the project has been and where it's going.
    10	
    11	- [[60 Roadmap/Versions]]
    12	- [[60 Roadmap/F-table backlog]]
    13	
    14	<!-- TODO: add open-questions log if useful -->

===== /Users/vladimir/Vault/CryoDAQ/README.md =====
     1	# CryoDAQ knowledge base
     2	
     3	Source-of-truth synthesis of the CryoDAQ project (Millimetron / АКЦ ФИАН
     4	cryogenic laboratory instrument stack). Authoritative repository lives
     5	at `~/Projects/cryodaq/`. This vault is a derived integration layer:
     6	narrative explainers, investigation history, decision rationale, glossary.
     7	
     8	If this vault and the repo conflict — the repo wins. Vault notes carry
     9	a `source:` and `last_synced:` header to make staleness visible.
    10	
    11	## Navigation
    12	
    13	- [[00 Overview/_index|00 Overview]] — what is CryoDAQ, who, why, hardware
    14	- [[10 Subsystems/_index|10 Subsystems]] — safety FSM, ZMQ bridge, persistence-first, calibration v2, alarm v2, plugin architecture
    15	- [[20 Drivers/_index|20 Drivers]] — LakeShore 218S, Keithley 2604B, Thyracont VSP63D
    16	- [[30 Investigations/_index|30 Investigations]] — bug histories with hypothesis trees (B1, b2b4fb5, homoglyph, Codex H2, plugin rebuild, IV.6)
    17	- [[40 Decisions/_index|40 Decisions]] — ADRs (architectural decision records)
    18	- [[50 Workflow/_index|50 Workflow]] — orchestration contract, multi-model consultation, overnight swarm, calibration loops
    19	- [[60 Roadmap/_index|60 Roadmap]] — versions, F-table backlog, open questions
    20	- [[90 Archive/_index|90 Archive]] — superseded designs, dropped hypotheses, pre-rewrite LabVIEW
    21	- [[_meta/_index|_meta]] — glossary, source map, update protocol, build log
    22	
    23	Built by Claude Code overnight 2026-04-26 from CC_PROMPT_VAULT_BUILD_2026-04-26.md.

exec
/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Projects/cryodaq/config/interlocks.yaml | sed -n '1,160p'; nl -ba /Users/vladimir/Projects/cryodaq/config/alarms_v3.yaml | sed -n '1,90p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	# Конфигурация блокировок CryoDAQ
     2	#
     3	# ВНИМАНИЕ: изменения в этом файле влияют на безопасность криогенного оборудования.
     4	# Любые правки должны быть согласованы с ответственным инженером и задокументированы.
     5	#
     6	# Структура каждой блокировки:
     7	#   name            — уникальный идентификатор (используется в API и логах)
     8	#   description     — текстовое описание (отображается в интерфейсе при срабатывании)
     9	#   channel_pattern — регулярное выражение для сопоставления с Reading.channel
    10	#   threshold       — пороговое значение
    11	#   comparison      — оператор: ">" (больше) или "<" (меньше)
    12	#   action          — имя защитного действия: "emergency_off" или "stop_source"
    13	#   cooldown_s      — минимальный интервал между повторными срабатываниями (секунды)
    14	
    15	interlocks:
    16	
    17	  # ─── Температурные блокировки криостата (каналы Т1–Т8) ──────────────────────
    18	  - name: "overheat_cryostat"
    19	    description: "Перегрев криостата — аварийное отключение нагревателя"
    20	    channel_pattern: "Т[1-8] .*"
    21	    threshold: 350.0
    22	    comparison: ">"
    23	    action: "emergency_off"
    24	    cooldown_s: 10.0
    25	
    26	  # ─── Температурные блокировки компрессорной линии (каналы Т9–Т12) ───────────
    27	  - name: "overheat_compressor"
    28	    description: "Перегрев компрессорной линии"
    29	    channel_pattern: "Т(9|10|11|12) .*"
    30	    threshold: 320.0
    31	    comparison: ">"
    32	    action: "emergency_off"
    33	    cooldown_s: 10.0
    34	
    35	  # ─── Защита детектора ────────────────────────────────────────────────────────
    36	  # Примечание: фазовое условие (только в фазе measurement при активном источнике)
    37	  # обеспечивается Alarm Engine v2 (detector_warmup_interlock в alarms_v3.yaml).
    38	  # Данный интерлок — аппаратная страховка для любой фазы при Т12 > 10 K.
    39	  - name: "detector_warmup"
    40	    description: "Нагрев детектора (Т12) выше рабочей температуры — остановка источника"
    41	    channel_pattern: "Т12 .*"
    42	    threshold: 10.0
    43	    comparison: ">"
    44	    action: "stop_source"
    45	    cooldown_s: 5.0
    46	
    47	  # undercool_shield (Т5 < 50 K) — УДАЛЁН: ложное срабатывание при штатном cooldown.
    48	  # Физическое обоснование: см. alarm_tz_physics_v3.md §4.2 "Undercool false alarm".
     1	# ============================================================================
     2	# CryoDAQ Alarm Configuration v3
     3	# ============================================================================
     4	#
     5	# Криовакуумный стенд, проект Миллиметрон, АКЦ ФИАН
     6	#
     7	# Калиброванные датчики:  Т11 (Азотная плита, 1-я ступень)
     8	#                         Т12 (2-я ступень, холодная точка)
     9	# Остальные:              только fault-детекция (0 K / 350+ K)
    10	#
    11	# Физическое обоснование: alarm_tz_physics_v3.md
    12	#
    13	# ============================================================================
    14	
    15	engine:
    16	  poll_interval_s: 0.5
    17	  rate_window_s: 120          # 240 точек при 2 Hz
    18	  rate_min_points: 60         # минимум 30с данных
    19	  rate_method: linear_fit
    20	
    21	  setpoints:
    22	    T12_setpoint:
    23	      source: experiment_metadata   # SQLite → experiments.custom_fields → "T12_setpoint"
    24	      default: 4.2                  # K
    25	      unit: K
    26	
    27	# --------------------------------------------------------------------------
    28	# Группы каналов
    29	# --------------------------------------------------------------------------
    30	channel_groups:
    31	  calibrated:    [Т11, Т12]
    32	  # Т4 (Радиатор 2), Т8 (Калибровка) — отключённые датчики, исключены
    33	  uncalibrated:  [Т1, Т2, Т3, Т5, Т6, Т7, Т9, Т10,
    34	                  Т13, Т14, Т15, Т16, Т17, Т18, Т19, Т20]
    35	  all_temp:      [Т1, Т2, Т3, Т5, Т6, Т7, Т9, Т10,
    36	                  Т11, Т12, Т13, Т14, Т15, Т16, Т17, Т18, Т19, Т20]
    37	
    38	# ============================================================================
    39	# ГЛОБАЛЬНЫЕ АЛАРМЫ (работают при ЛЮБОЙ фазе)
    40	# ============================================================================
    41	global_alarms:
    42	
    43	  # --- ГЛАВНЫЙ: потеря вакуума при холодном криостате ---
    44	  vacuum_loss_cold:
    45	    alarm_type: composite
    46	    operator: AND
    47	    conditions:
    48	      - channels: [Т11, Т12]
    49	        check: any_below
    50	        threshold: 200           # K
    51	      - channel: P1
    52	        check: above
    53	        threshold: 1.0e-3        # mbar — граница молекулярного режима
    54	    level: CRITICAL
    55	    hysteresis:
    56	      pressure: 5.0e-4
    57	    message: >
    58	      ПОТЕРЯ ВАКУУМА ПРИ ХОЛОДНОМ КРИОСТАТЕ.
    59	      Давление вышло из молекулярного режима (P > 1e-3 mbar) при T < 200K.
    60	      ДЕЙСТВИЕ: проверить вакуумную систему, подготовить аварийный напуск N₂.
    61	    notify: [gui, telegram, sound]
    62	
    63	  # --- Ранний предвестник ---
    64	  vacuum_loss_cold_early:
    65	    alarm_type: composite
    66	    operator: AND
    67	    conditions:
    68	      - channels: [Т11, Т12]
    69	        check: any_below
    70	        threshold: 200
    71	      - channel: P1
    72	        check: above
    73	        threshold: 1.0e-4        # mbar — ещё безопасно, но аномально
    74	      - channel: P1
    75	        check: rate_above
    76	        threshold: 0             # dP/dt > 0
    77	        rate_window_s: 60
    78	    level: WARNING
    79	    message: >
    80	      Давление растёт при холодном криостате (P > 1e-4 mbar).
    81	      Возможна течь. ДЕЙСТВИЕ: проверить уплотнения, фланцы.
    82	    notify: [gui, telegram]
    83	
    84	  # --- Fault на некалиброванных датчиках ---
    85	  sensor_fault:
    86	    alarm_type: threshold
    87	    channel_group: uncalibrated
    88	    check: outside_range
    89	    range: [0.0, 350.0]         # K — hardcoded, ниже 0 или выше 350 = неисправность
    90	    level: WARNING

exec
/opt/homebrew/bin/bash -lc "find /Users/vladimir/Projects/cryodaq/config/themes -maxdepth 1 -type f -name '*.yaml' -print | sort && rg -n \"braun|SELECTION_BG|FOCUS_RING|STATUS_OK|REQUIRED_TOKENS\" /Users/vladimir/Projects/cryodaq/config/themes /Users/vladimir/Projects/cryodaq/src/cryodaq/gui/_theme_loader.py /Users/vladimir/Projects/cryodaq/CHANGELOG.md -S" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
/Users/vladimir/Projects/cryodaq/config/themes/amber.yaml
/Users/vladimir/Projects/cryodaq/config/themes/anthropic_mono.yaml
/Users/vladimir/Projects/cryodaq/config/themes/braun.yaml
/Users/vladimir/Projects/cryodaq/config/themes/default_cool.yaml
/Users/vladimir/Projects/cryodaq/config/themes/gost.yaml
/Users/vladimir/Projects/cryodaq/config/themes/instrument.yaml
/Users/vladimir/Projects/cryodaq/config/themes/ochre_bloom.yaml
/Users/vladimir/Projects/cryodaq/config/themes/rose_dusk.yaml
/Users/vladimir/Projects/cryodaq/config/themes/signal.yaml
/Users/vladimir/Projects/cryodaq/config/themes/taupe_quiet.yaml
/Users/vladimir/Projects/cryodaq/config/themes/warm_stone.yaml
/Users/vladimir/Projects/cryodaq/config/themes/xcode.yaml
/Users/vladimir/Projects/cryodaq/src/cryodaq/gui/_theme_loader.py:30:REQUIRED_TOKENS = frozenset(
/Users/vladimir/Projects/cryodaq/src/cryodaq/gui/_theme_loader.py:53:        "SELECTION_BG",
/Users/vladimir/Projects/cryodaq/src/cryodaq/gui/_theme_loader.py:54:        "FOCUS_RING",
/Users/vladimir/Projects/cryodaq/src/cryodaq/gui/_theme_loader.py:59:        "STATUS_OK",
/Users/vladimir/Projects/cryodaq/src/cryodaq/gui/_theme_loader.py:119:    missing = REQUIRED_TOKENS - set(pack.keys())
/Users/vladimir/Projects/cryodaq/src/cryodaq/gui/_theme_loader.py:131:    for token in REQUIRED_TOKENS:
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:160:  and horizon buttons render checked state in ACCENT, not STATUS_OK.
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:163:  collision where `STATUS_OK` (safety-green) rendered UI states
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:167:  tokens: `SELECTION_BG` (subtle tint for selected rows) and
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:168:  `FOCUS_RING` (neutral outline for focused elements). Added to all
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:169:  12 bundled theme packs and required by `_theme_loader.REQUIRED_TOKENS`.
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:172:  use `ACCENT + ON_ACCENT` instead of `STATUS_OK + ON_PRIMARY`;
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:175:  outline (prior filled `STATUS_OK` pill); `ExperimentCard` mode
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:180:  (identical to STATUS_OK) → `#b89e7a` warm sand; `taupe_quiet`
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:181:  `#4a8a5e` (with obsolete «matches STATUS_OK by design» comment) →
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:182:  `#a39482` warm taupe (comment removed); `braun` `#476f20` (olive
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:185:  All 9 other themes' ACCENT verified hue-distant from STATUS_OK
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:290:  DS tokens (dense → STATUS_OK, medium → STATUS_CAUTION, sparse →
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:316:  braun (light).** STATUS palette hue-locked with lightness unlocked
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:320:  (gost / xcode / braun) ship a shifted-lightness variant that
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:510:  phase pills с past durations + current 2px STATUS_OK highlight,
/Users/vladimir/Projects/cryodaq/config/themes/rose_dusk.yaml:23:SELECTION_BG: "#2b2326"
/Users/vladimir/Projects/cryodaq/config/themes/rose_dusk.yaml:24:FOCUS_RING: "#6b5560"
/Users/vladimir/Projects/cryodaq/config/themes/rose_dusk.yaml:37:STATUS_OK: "#4a8a5e"
/Users/vladimir/Projects/cryodaq/config/themes/xcode.yaml:23:SELECTION_BG: "#e8e6e3"
/Users/vladimir/Projects/cryodaq/config/themes/xcode.yaml:24:FOCUS_RING: "#8b8374"
/Users/vladimir/Projects/cryodaq/config/themes/xcode.yaml:38:STATUS_OK: "#2e6b45"
/Users/vladimir/Projects/cryodaq/config/themes/gost.yaml:23:SELECTION_BG: "#e8e4de"
/Users/vladimir/Projects/cryodaq/config/themes/gost.yaml:24:FOCUS_RING: "#8a7f6f"
/Users/vladimir/Projects/cryodaq/config/themes/gost.yaml:38:STATUS_OK: "#2e6b45"
/Users/vladimir/Projects/cryodaq/config/themes/warm_stone.yaml:23:SELECTION_BG: "#2c2723"
/Users/vladimir/Projects/cryodaq/config/themes/warm_stone.yaml:24:FOCUS_RING: "#6b5d4d"
/Users/vladimir/Projects/cryodaq/config/themes/warm_stone.yaml:26:# Accent (warm sand — Phase III.A decoupled from STATUS_OK) + scale
/Users/vladimir/Projects/cryodaq/config/themes/warm_stone.yaml:37:STATUS_OK: "#4a8a5e"
/Users/vladimir/Projects/cryodaq/config/themes/anthropic_mono.yaml:23:SELECTION_BG: "#2a2826"
/Users/vladimir/Projects/cryodaq/config/themes/anthropic_mono.yaml:24:FOCUS_RING: "#6b6559"
/Users/vladimir/Projects/cryodaq/config/themes/anthropic_mono.yaml:37:STATUS_OK: "#4a8a5e"
/Users/vladimir/Projects/cryodaq/config/themes/ochre_bloom.yaml:23:SELECTION_BG: "#2a251e"
/Users/vladimir/Projects/cryodaq/config/themes/ochre_bloom.yaml:24:FOCUS_RING: "#6b5c42"
/Users/vladimir/Projects/cryodaq/config/themes/ochre_bloom.yaml:26:# Accent (olive, 90° from STATUS_OK — verified Phase III.A) + scale
/Users/vladimir/Projects/cryodaq/config/themes/ochre_bloom.yaml:37:STATUS_OK: "#4a8a5e"
/Users/vladimir/Projects/cryodaq/config/themes/default_cool.yaml:23:SELECTION_BG: "#2a2d38"
/Users/vladimir/Projects/cryodaq/config/themes/default_cool.yaml:24:FOCUS_RING: "#5a6380"
/Users/vladimir/Projects/cryodaq/config/themes/default_cool.yaml:38:STATUS_OK: "#4a8a5e"
/Users/vladimir/Projects/cryodaq/config/themes/taupe_quiet.yaml:23:SELECTION_BG: "#2b2a27"
/Users/vladimir/Projects/cryodaq/config/themes/taupe_quiet.yaml:24:FOCUS_RING: "#6a6762"
/Users/vladimir/Projects/cryodaq/config/themes/taupe_quiet.yaml:26:# Accent (warm taupe — Phase III.A decoupled from STATUS_OK) + scale
/Users/vladimir/Projects/cryodaq/config/themes/taupe_quiet.yaml:37:STATUS_OK: "#4a8a5e"
/Users/vladimir/Projects/cryodaq/config/themes/instrument.yaml:23:SELECTION_BG: "#262b2f"
/Users/vladimir/Projects/cryodaq/config/themes/instrument.yaml:24:FOCUS_RING: "#586d78"
/Users/vladimir/Projects/cryodaq/config/themes/instrument.yaml:37:STATUS_OK: "#4a8a5e"
/Users/vladimir/Projects/cryodaq/config/themes/braun.yaml:23:SELECTION_BG: "#e6e0d8"
/Users/vladimir/Projects/cryodaq/config/themes/braun.yaml:24:FOCUS_RING: "#8a7d65"
/Users/vladimir/Projects/cryodaq/config/themes/braun.yaml:27:# Prior hue 90° violated the ≥60° invariant vs STATUS_OK 143° at 53°.
/Users/vladimir/Projects/cryodaq/config/themes/braun.yaml:28:# New hue ≈70° (yellow-olive): 73° from STATUS_OK, 37° from WARNING,
/Users/vladimir/Projects/cryodaq/config/themes/braun.yaml:29:# satisfies both III.A ≥60°/STATUS_OK and ADR 001 ≥30°/all-status
/Users/vladimir/Projects/cryodaq/config/themes/braun.yaml:42:STATUS_OK: "#2e6b45"
/Users/vladimir/Projects/cryodaq/config/themes/amber.yaml:23:SELECTION_BG: "#2b2720"
/Users/vladimir/Projects/cryodaq/config/themes/amber.yaml:24:FOCUS_RING: "#6b5f43"
/Users/vladimir/Projects/cryodaq/config/themes/amber.yaml:37:STATUS_OK: "#4a8a5e"
/Users/vladimir/Projects/cryodaq/config/themes/signal.yaml:23:SELECTION_BG: "#2a2a32"
/Users/vladimir/Projects/cryodaq/config/themes/signal.yaml:24:FOCUS_RING: "#6a6a82"
/Users/vladimir/Projects/cryodaq/config/themes/signal.yaml:37:STATUS_OK: "#4a8a5e"

exec
/opt/homebrew/bin/bash -lc "find /Users/vladimir/Projects/cryodaq/docs/design-system -name '*.md' -type f | wc -l && rg -n \"65 encoded|79 enforcement|139|v1\\.0\\.1|RULE-COLOR-010|RULE-TYPO-007|RULE-SPACE-001|Cyrillic|Т|mbar|мбар\" /Users/vladimir/Projects/cryodaq/docs/design-system /Users/vladimir/Projects/cryodaq/src/cryodaq/gui/theme.py /Users/vladimir/Projects/cryodaq/config/themes -S" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
      85
/Users/vladimir/Projects/cryodaq/docs/design-system/V101_REVIEW_REPORT.md:1:# v1.0.1 Full Review Report
/Users/vladimir/Projects/cryodaq/docs/design-system/V101_REVIEW_REPORT.md:5:v1.0.1 is materially better than the pre-fix-pass state: the sampled token values now match `theme.py`, the recomputed contrast ratios in `contrast-matrix.md` are correct, WCAG baseline claims are honest, and the corpus is structurally clean (stats, fences, RULE refs). It is not ready to tag yet because three blocking problem classes remain: unqualified ghost references to non-shipped primitives/tokens, domain-invariant drift in normative examples, and a shortcut registry that is not coherent across the canonical registry, navigation guidance, ToolRail spec, and the shipped ToolRail implementation.
/Users/vladimir/Projects/cryodaq/docs/design-system/V101_REVIEW_REPORT.md:15:| R5 Domain accuracy | FAIL | Normative docs still contain uppercase FSM labels and operator-facing Latin `T` / `mbar` examples. T11/T12 metrology, Keithley TSP/dual-channel, and SafetyManager authority are otherwise correct. |
/Users/vladimir/Projects/cryodaq/docs/design-system/V101_REVIEW_REPORT.md:32:- **[V-006]** Check R5: [docs/design-system/tokens/colors.md:89] — normative operator-facing example uses Latin `T5` (`T5 Экран 77К badge`); the same drift appears in [docs/design-system/rules/color-rules.md:500] (`T5`, `T6`). Operator-facing channel IDs must use Cyrillic `Т`. Severity: CRITICAL.
/Users/vladimir/Projects/cryodaq/docs/design-system/V101_REVIEW_REPORT.md:33:- **[V-007]** Check R5: [docs/design-system/rules/surface-rules.md:305] — a good example renders operator-facing pressure text as `1.23e-06 mbar`; operator-facing prose/examples must use `мбар`. Severity: CRITICAL.
/Users/vladimir/Projects/cryodaq/docs/design-system/V101_REVIEW_REPORT.md:38:Do not tag `design-system-v1.0.1` yet.
/Users/vladimir/Projects/cryodaq/docs/design-system/V101_REVIEW_REPORT.md:42:- Normalize domain invariants everywhere: lowercase FSM states only, Cyrillic `Т` in operator-facing channel examples, `мбар` in operator-facing pressure examples.
/Users/vladimir/Projects/cryodaq/config/themes/gost.yaml:1:__meta_name__: "ГОСТ"
/Users/vladimir/Projects/cryodaq/docs/design-system/THEME_FOLLOWUPS.md:22:STATUS hue» установленное в v1.0.1 handoff.
/Users/vladimir/Projects/cryodaq/docs/design-system/THEME_FOLLOWUPS.md:50:   STATUS_OK (139°), ни с STATUS_WARNING (33°). Запрашивает
/Users/vladimir/Projects/cryodaq/config/themes/ochre_bloom.yaml:2:__meta_description__: "Тёплый студийный охристо-коричневый. Вдохновлено темой Ableton Ochre — оливковый акцент на тёмно-коричневом фоне."
/Users/vladimir/Projects/cryodaq/config/themes/taupe_quiet.yaml:1:__meta_name__: "Таупэ"
/Users/vladimir/Projects/cryodaq/config/themes/warm_stone.yaml:1:__meta_name__: "Тёплый камень"
/Users/vladimir/Projects/cryodaq/config/themes/warm_stone.yaml:2:__meta_description__: "Тёплый серый на основе Pantone Warm Gray. Лабораторная атмосфера без клинического холода."
/Users/vladimir/Projects/cryodaq/docs/design-system/MANIFEST.md:11:**Scope:** Batches 1-6 complete. Full design system v1.0.1 — foundation tokens + enforcement rules + generic components + CryoDAQ domain primitives + cross-surface patterns + accessibility commitments + governance policies.
/Users/vladimir/Projects/cryodaq/docs/design-system/MANIFEST.md:23:│   ├── typography.md                   # 36 typography tokens, Fira fonts, Cyrillic rules
/Users/vladimir/Projects/cryodaq/docs/design-system/MANIFEST.md:130:11. **Cyrillic Т (U+0422) in user-facing temperature channel IDs** — never Latin T.
/Users/vladimir/Projects/cryodaq/docs/design-system/MANIFEST.md:140:21. **TopWatchBar T-min/T-max locked to Т11/Т12** — the only positionally fixed reference channels (physically immovable on the second stage / nitrogen plate; cannot be relocated without dismantling the rheostat). All temperature channels are metrologically calibrated, but other channels may change position between experiments, disqualifying them as fixed quantitative reference points.
/Users/vladimir/Projects/cryodaq/docs/design-system/MANIFEST.md:192:**Design system v1.0.1 — complete.** All 67 files, 79 rules, 139 tokens, 6 batches.
/Users/vladimir/Projects/cryodaq/config/themes/amber.yaml:2:__meta_description__: "Обожжённая амбровая база со сниженной контрастной амплитудой и винно-фиолетовым акцентом. Тёплый медитативный long-session режим."
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:13:Typography in CryoDAQ uses **two font families**: Fira Sans (body) and Fira Code (display + mono). Both fully support Cyrillic + Latin + Greek scripts. This is verified against Google Fonts metadata.
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:25:| Token | Value | Use | Cyrillic? | Weights available |
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:27:| `FONT_BODY` | `Fira Sans` | All body text, labels, paragraphs, form inputs | ✅ Full Cyrillic + Cyrillic-ext + Greek | 100-900 regular+italic |
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:29:| `FONT_DISPLAY` | `Fira Code` | Display-size numeric headers, TopWatchBar readouts | ✅ Full Cyrillic + Cyrillic-ext + Greek | 300-700 |
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:30:| `FONT_MONO` | `Fira Code` | Data cells, code snippets, log entries, timestamps | ✅ Full Cyrillic + Cyrillic-ext + Greek | 300-700 |
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:129:**Use for:** Temperature and pressure values in TopWatchBar («3.90 K», «1.23e-06 мбар»). Hero readout in experiment status.
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:157:**Use for:** «КАРТОЧКА» / «ХРОНИКА» section headers inside ExperimentOverlay, archive panel section dividers.
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:171:**Use for:** Form field labels, sensor channel labels («Т1 Криостат верх»), status badges, tile titles (often uppercase — see RULE-TYPO-008).
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:241:## Cyrillic-specific considerations
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:243:Fira Sans and Fira Code both have complete Cyrillic + Cyrillic-Ext coverage.
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:247:1. **Temperature channel identifiers use Cyrillic Т (U+0422)**, never Latin T (U+0054). Enforce in user-facing strings. See `rules/content-voice-rules.md` RULE-COPY-001.
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:248:2. **UPPERCASE Cyrillic labels** (e.g., «ЭКСПЕРИМЕНТ», «АВАР. ОТКЛ.») require `letter-spacing: 0.05em` because Cyrillic uppercase has narrower default tracking than Latin. Without this, letters cram together.
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:249:3. **Russian text is ~15% more vertically dense** than English at same size — Cyrillic glyphs often have tall diacriticals. Increase line-height by 2-3px for multi-line Russian content.
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:254:# DESIGN: RULE-TYPO-005 (Cyrillic uppercase spacing)
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:255:uppercase_label = QLabel("АВАР. ОТКЛ.")
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:272:Fallback preserves Cyrillic on all platforms:
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:273:- **Windows**: Segoe UI (Cyrillic ✅)
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:274:- **macOS**: Helvetica Neue (Cyrillic ✅)
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:275:- **Linux**: DejaVu Sans or Liberation Sans (Cyrillic ✅)
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:283:- **Mixed Latin T and Cyrillic Т in same view** — broken encoding, confuses operators
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:296:- `RULE-TYPO-005` — Cyrillic uppercase letter-spacing (`rules/typography-rules.md`)
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:298:- `RULE-TYPO-007` — Off-scale sizes (15, 32) are protected (`rules/typography-rules.md`)
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:299:- `RULE-COPY-001` — Cyrillic Т for temperature channels (`rules/content-voice-rules.md`)
/Users/vladimir/Projects/cryodaq/docs/design-system/components/badge.md:16:- Status label: «НОРМА», «ВНИМАНИЕ», «АВАРИЯ», «УСТАРЕЛО»
/Users/vladimir/Projects/cryodaq/docs/design-system/components/badge.md:32:│   АВАРИЯ     │                │    ВНИМАНИЕ       │          │ 3 │  Тревоги
/Users/vladimir/Projects/cryodaq/docs/design-system/components/badge.md:44: ● Авария канала Т11
/Users/vladimir/Projects/cryodaq/docs/design-system/components/badge.md:60:3. **Uppercase Cyrillic has letter-spacing.** Filled status badges use `0.05em` tracking. (RULE-TYPO-005)
/Users/vladimir/Projects/cryodaq/docs/design-system/components/badge.md:245:Usage: `● Норма`, `● Авария канала Т11`, `● Ожидание подключения`.
/Users/vladimir/Projects/cryodaq/docs/design-system/components/badge.md:319:4. **Cyrillic uppercase without letter-spacing.** "АВАРИЯ" cramps without tracking. RULE-TYPO-005.
/Users/vladimir/Projects/cryodaq/docs/design-system/components/modal.md:211:save_raw = QCheckBox("Также экспортировать сырые данные в CSV")
/Users/vladimir/Projects/cryodaq/docs/design-system/CHANGELOG.md:61:- 79 enforcement rules across 9 categories.
/Users/vladimir/Projects/cryodaq/docs/design-system/CHANGELOG.md:63:- `MANIFEST.md` (65 encoded decisions) and `README.md` entry points.
/Users/vladimir/Projects/cryodaq/docs/design-system/CHANGELOG.md:69:- `design-system-v1.0.1` — audit fix pass (this release).
/Users/vladimir/Projects/cryodaq/docs/design-system/components/dialog.md:150:    body="Несохранённые параметры датчика Т11 будут утеряны при переходе.",
/Users/vladimir/Projects/cryodaq/docs/design-system/components/dialog.md:210:        "Последняя калибровка датчика Т5 выполнена 97 дней назад. "
/Users/vladimir/Projects/cryodaq/docs/design-system/components/dialog.md:223:# DESIGN: RULE-SPACE-001 (SPACE_2 between related buttons)
/Users/vladimir/Projects/cryodaq/docs/design-system/components/dialog.md:311:- 2026-04-17 (v1.0.1): Added explicit States matrix (FR-015 / FR-020) — default-open, Cancel-focus, Primary-focus, hover, disabled, destructive variant, Escape dismiss.
/Users/vladimir/Projects/cryodaq/docs/design-system/components/tab-group.md:145:    TabDef(label="Температуры", key="temps", icon_name="thermometer"),
/Users/vladimir/Projects/cryodaq/docs/design-system/components/tab-group.md:274:3. **Using UPPERCASE on labels.** "ОБЩИЕ / ДАТЧИКИ / СОЕДИНЕНИЯ" is miscalibrated — these are navigation labels, sentence case per RULE-COPY-003.
/Users/vladimir/Projects/cryodaq/docs/design-system/components/breadcrumb.md:29: ← Дашборд  /  Датчики  /  Т11 Теплообменник
/Users/vladimir/Projects/cryodaq/docs/design-system/components/breadcrumb.md:99:    DrillDownCrumb("Т11 Теплообменник"),  # current — no handler
/Users/vladimir/Projects/cryodaq/docs/design-system/components/breadcrumb.md:147:← Дашборд  /  ...  /  Т11 Теплообменник
/Users/vladimir/Projects/cryodaq/docs/design-system/components/breadcrumb.md:233:# DESIGN: RULE-SPACE-001
/Users/vladimir/Projects/cryodaq/docs/design-system/components/breadcrumb.md:252:5. **Full path in title bar.** Window title "CryoDAQ — Дашборд — Датчики — Т11" as breadcrumb substitute is unreadable and small. Use in-page breadcrumb widget.
/Users/vladimir/Projects/cryodaq/docs/design-system/components/breadcrumb.md:254:6. **Uppercase Cyrillic in crumbs.** Crumbs are sentence case (per RULE-COPY-003) — "Дашборд", not "ДАШБОРД". UPPERCASE is for category labels (tile headers, destructive action buttons), not navigation.
/Users/vladimir/Projects/cryodaq/docs/design-system/README.md:218:From `src/cryodaq/gui/theme.py` inventory (v1.0.1, 139 tokens):
/Users/vladimir/Projects/cryodaq/docs/design-system/README.md:242:- 2026-04-17: Initial version. Written during Phase I.1 after Vladimir visual review revealed cross-surface inconsistency. Based on real `theme.py` token inventory (126 tokens across 5 categories at v1.0.0; expanded to 139 tokens in v1.0.1).
/Users/vladimir/Projects/cryodaq/docs/design-system/ANTI_PATTERNS.md:157:**Related rules:** RULE-COLOR-010 (canonical token registry; non-sanctioned palettes forbidden).
/Users/vladimir/Projects/cryodaq/docs/design-system/ANTI_PATTERNS.md:167:**Related rules:** RULE-COLOR-010 (canonical token registry; saturated primaries are not sanctioned tokens).
/Users/vladimir/Projects/cryodaq/docs/design-system/ANTI_PATTERNS.md:187:**Why forbidden:** Violates RULE-COPY-001. Russian UI uses Cyrillic Т (U+0422). Latin T breaks Russian typographic consistency and may interact poorly with Cyrillic-optimized fonts.
/Users/vladimir/Projects/cryodaq/docs/design-system/ANTI_PATTERNS.md:189:**Fix:** Use Cyrillic Т throughout. Consistent across all 24 temperature channels.
/Users/vladimir/Projects/cryodaq/docs/design-system/ANTI_PATTERNS.md:221:**Pattern:** `"АВАР. ОТКЛ."` in default letter-spacing — glyphs cram together.
/Users/vladimir/Projects/cryodaq/docs/design-system/ANTI_PATTERNS.md:223:**Why forbidden:** Violates RULE-TYPO-005. Cyrillic uppercase has narrower default tracking than Latin; needs positive letter-spacing.
/Users/vladimir/Projects/cryodaq/docs/design-system/ANTI_PATTERNS.md:225:**Fix:** `font.setLetterSpacing(QFont.AbsoluteSpacing, 0.05)` for Cyrillic uppercase labels.
/Users/vladimir/Projects/cryodaq/docs/design-system/ANTI_PATTERNS.md:231:**Why forbidden:** Violates RULE-TYPO-007. The off-scale sizes (15, 32) solve specific legibility problems in specific widgets. Normalizing breaks that optimization.
/Users/vladimir/Projects/cryodaq/docs/design-system/components/button.md:34:| **Destructive** | Irreversible / emergency action (АВАР. ОТКЛ., Удалить) | Filled `DESTRUCTIVE`, `ON_DESTRUCTIVE` text |
/Users/vladimir/Projects/cryodaq/docs/design-system/components/button.md:45:│  Начать эксперимент    │     │  Отмена          │      │   АВАР. ОТКЛ.    │
/Users/vladimir/Projects/cryodaq/docs/design-system/components/button.md:67:| **Icon + label spacing** | Mixed variants | `SPACE_1` (4px) between icon and text (RULE-SPACE-001) |
/Users/vladimir/Projects/cryodaq/docs/design-system/components/button.md:80:10. **Uppercase Cyrillic has letter-spacing.** `АВАР. ОТКЛ.` uses `0.05em` tracking. (RULE-TYPO-005)
/Users/vladimir/Projects/cryodaq/docs/design-system/components/button.md:199:button = QPushButton("АВАР. ОТКЛ.")  # uppercase Cyrillic category label
/Users/vladimir/Projects/cryodaq/docs/design-system/components/button.md:264:# DESIGN: RULE-SPACE-001, RULE-SPACE-008
/Users/vladimir/Projects/cryodaq/docs/design-system/components/button.md:406:9. **Cyrillic uppercase without letter-spacing.** "АВАР. ОТКЛ." cramps without `0.05em` tracking. RULE-TYPO-005.
/Users/vladimir/Projects/cryodaq/docs/design-system/components/input-field.md:54:| **Unit suffix** | Numeric fields | Inline right-aligned unit label (K, мбар, Вт) per RULE-COPY-006 |
/Users/vladimir/Projects/cryodaq/docs/design-system/components/input-field.md:61:4. **Unit always displayed for numeric fields.** Temperature field shows "K" suffix; pressure shows "мбар". (RULE-COPY-006, RULE-DATA-006)
/Users/vladimir/Projects/cryodaq/docs/design-system/components/input-field.md:88:        unit: str = "",          # "K", "мбар", "Вт", etc.
/Users/vladimir/Projects/cryodaq/docs/design-system/components/input-field.md:269:        self.set_error("Температура не может быть отрицательной.")
/Users/vladimir/Projects/cryodaq/docs/design-system/components/input-field.md:316:        layout.setSpacing(theme.SPACE_1)  # DESIGN: RULE-SPACE-001
/Users/vladimir/Projects/cryodaq/docs/design-system/components/input-field.md:416:8. **Label in uppercase.** "ИМЯ ЭКСПЕРИМЕНТА" — use sentence case for field labels. Uppercase is for category headers per RULE-TYPO-008, not form labels.
/Users/vladimir/Projects/cryodaq/docs/design-system/adr/001-light-theme-status-unlock.md:5:**Supersedes:** §4 «STATUS palette LOCKED» из handoff v1.0.1 (частично — только
/Users/vladimir/Projects/cryodaq/docs/design-system/adr/001-light-theme-status-unlock.md:17:COLD_HIGHLIGHT) была заморожена в v1.0.1 как семантический инвариант:
/Users/vladimir/Projects/cryodaq/docs/design-system/adr/001-light-theme-status-unlock.md:52:Пример: STATUS_OK design-intent hue 139°.
/Users/vladimir/Projects/cryodaq/docs/design-system/adr/001-light-theme-status-unlock.md:63:Толерантность применяется ТОЛЬКО к реконструированному hue из
/Users/vladimir/Projects/cryodaq/docs/design-system/adr/001-light-theme-status-unlock.md:65:handoff-документах) по-прежнему точный: WARNING=33°, OK=139°, etc.
/Users/vladimir/Projects/cryodaq/docs/design-system/adr/001-light-theme-status-unlock.md:70:| STATUS_OK | `#4a8a5e` | `#2e6b45` | 139° | forest green |
/Users/vladimir/Projects/cryodaq/docs/design-system/adr/001-light-theme-status-unlock.md:82:трёх light-тем (см. Таблицу 2 ниже).
/Users/vladimir/Projects/cryodaq/docs/design-system/adr/001-light-theme-status-unlock.md:112:  тёплая sepia-тема может потребовать slight shift OK от 139° в
/Users/vladimir/Projects/cryodaq/docs/design-system/adr/001-light-theme-status-unlock.md:116:## Таблица 2 — контрастные метрики shifted-L статусов
/Users/vladimir/Projects/cryodaq/docs/design-system/adr/001-light-theme-status-unlock.md:142:  theme в v1.0.1 — dark).
/Users/vladimir/Projects/cryodaq/docs/design-system/adr/001-light-theme-status-unlock.md:146:- Тест «STATUS_OK не совпадает с ACCENT» в light-темах теперь
/Users/vladimir/Projects/cryodaq/docs/design-system/adr/001-light-theme-status-unlock.md:148:  Тестовая инфраструктура должна читать STATUS из активной темы,
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/spacing.md:60:# DESIGN: RULE-SPACE-001 (inline gap = SPACE_1 for icon, SPACE_2 for text)
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/spacing.md:64:row.addWidget(QLabel("Т мин"))
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/spacing.md:159:- `RULE-SPACE-001` — Inline row gaps (`rules/spacing-rules.md`)
/Users/vladimir/Projects/cryodaq/docs/design-system/components/popover.md:149:title = QLabel("Т11 Теплообменник 1")
/Users/vladimir/Projects/cryodaq/docs/design-system/components/chart-tile.md:35:│  │ ДИНАМИКА ТЕМПЕРАТУР     Т1 — Т14  |  последние 60с │    │  ← title + legend/meta
/Users/vladimir/Projects/cryodaq/docs/design-system/components/chart-tile.md:86:    label: str                      # display name ("Т1", "Давление", ...)
/Users/vladimir/Projects/cryodaq/docs/design-system/components/chart-tile.md:100:        y_unit: str = "",           # "K", "мбар" — displayed on axis
/Users/vladimir/Projects/cryodaq/docs/design-system/components/chart-tile.md:121:    title="ДИНАМИКА ТЕМПЕРАТУР",
/Users/vladimir/Projects/cryodaq/docs/design-system/components/chart-tile.md:129:for i, channel in enumerate(cold_channels):  # Т1–Т14
/Users/vladimir/Projects/cryodaq/docs/design-system/components/chart-tile.md:138:tile.push_sample("Т1", time.time(), 4.21)
/Users/vladimir/Projects/cryodaq/docs/design-system/components/chart-tile.md:139:tile.push_sample("Т2", time.time(), 4.15)
/Users/vladimir/Projects/cryodaq/docs/design-system/components/chart-tile.md:153:    y_unit="мбар",
/Users/vladimir/Projects/cryodaq/docs/design-system/components/chart-tile.md:167:    title="Т11",
/Users/vladimir/Projects/cryodaq/docs/design-system/components/chart-tile.md:174:    label="Т11",
/Users/vladimir/Projects/cryodaq/docs/design-system/components/chart-tile.md:192:    title="ЭКСПЕРИМЕНТ calibration_run_042",
/Users/vladimir/Projects/cryodaq/docs/design-system/components/chart-tile.md:358:7. **Legend inside plot area.** pyqtgraph's in-plot legend obscures data. Put legend in tile header row instead ("Т1 — Т14").
/Users/vladimir/Projects/cryodaq/docs/design-system/components/chart-tile.md:364:10. **Title sentence case.** "Динамика температур" — should be UPPERCASE "ДИНАМИКА ТЕМПЕРАТУР" per RULE-TYPO-008 (tile title = category label).
/Users/vladimir/Projects/cryodaq/docs/design-system/components/bento-tile.md:106:    Example: "Pressure" / "1.23e-06 мбар"
/Users/vladimir/Projects/cryodaq/docs/design-system/components/bento-tile.md:112:        value: str,           # "1.23e-06 мбар" — formatted display
/Users/vladimir/Projects/cryodaq/docs/design-system/components/bento-tile.md:154:# DESIGN: RULE-TYPO-007 (FONT_DISPLAY_SIZE = 32, protected off-scale)
/Users/vladimir/Projects/cryodaq/docs/design-system/components/bento-tile.md:210:tile = DataDenseTile(title="ДАТЧИКИ")
/Users/vladimir/Projects/cryodaq/docs/design-system/components/bento-tile.md:221:tile = LiveTile(title="ДИНАМИКА Т11")
/Users/vladimir/Projects/cryodaq/docs/design-system/components/card.md:159:footer_layout.setSpacing(theme.SPACE_2)  # DESIGN: RULE-SPACE-001
/Users/vladimir/Projects/cryodaq/docs/design-system/adr/002-accent-status-decoupling.md:11:К концу Phase II все overlays мигрированы на DS v1.0.1-токены и
/Users/vladimir/Projects/cryodaq/docs/design-system/adr/002-accent-status-decoupling.md:96:| ochre_bloom | `#a39450` olive ≈49° | **KEEP** (distance 90° from STATUS_OK 139°) | — |
/Users/vladimir/Projects/cryodaq/docs/design-system/components/toast.md:18:- Warnings that operator should notice but don't block work («Калибровка Т5 устареет через 3 дня»)
/Users/vladimir/Projects/cryodaq/docs/design-system/components/toast.md:166:    body="Калибровочные коэффициенты Т11 обновлены.",
/Users/vladimir/Projects/cryodaq/docs/design-system/components/toast.md:213:    body="Датчик Т5 калиброван 97 дней назад. Рекомендуется повторить.",
/Users/vladimir/Projects/cryodaq/docs/design-system/accessibility/wcag-baseline.md:184:- 2026-04-17: v1.0.1 — Downgraded 1.4.11 Non-text Contrast from Met to Partial after recomputing BORDER contrast (1.46:1 actual vs 3.1:1 claimed). Corrected 1.4.6 AAA note (FOREGROUND meets AAA; MUTED_FOREGROUND misses). Added 1.4.11 exception to external conformance statement.
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/colors.md:96:| `STATUS_FAULT` | `#c44545` | Out of spec, interlock, fault_latched | Red alarm badge, "АВАР. ОТКЛ." text, safety fault | Any non-fault red, generic error display text |
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/colors.md:99:| `COLD_HIGHLIGHT` | `#5b8db8` | Cryogenic temperature emphasis | Cold channel highlighting, low-temp series in plots, Т5 Экран 77К badge | General informational use (use INFO) |
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/colors.md:149:| `ON_DESTRUCTIVE` | `#e8eaf0` | Text on destructive button background | АВАР. ОТКЛ. button label. |
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/colors.md:214:| `DESTRUCTIVE` | `#c44545` | Destructive button background (e.g., АВАР. ОТКЛ.) — same hex as STATUS_FAULT |
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/chart-tokens.md:127:- Unit suffix if present (`K`, `мбар`)
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/chart-tokens.md:141:pressure_plot.setLabel('left', 'Давление', units='мбар')
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/chart-tokens.md:217:- 2026-04-17 (v1.0.1): Recounted PLOT_* tokens against theme.py — total is 12 (5 color + 1 palette + 3 alpha + 2 line-width + 1 layout). Earlier "9 + 1 = 10" undercounted line-width tokens and conflated the line palette with the color set (FR-019). Switched the operator-facing axis-label example from the Latin pressure-unit spelling to `мбар` (FR-016).
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/destructive-actions.md:79:emergency_btn = HoldConfirmButton("АВАР. ОТКЛ.")
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/destructive-actions.md:155:| Emergency stop (Keithley) | «АВАР. ОТКЛ. (Ctrl+Shift+X)» | — (no dialog; hold-confirm is sole protection for maximum speed) | «ПОДТВЕРДИТЬ (удерживать)» | Single layer; button itself is the protection; also global shortcut |
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/destructive-actions.md:176:`Ctrl+Shift+X` triggers АВАР. ОТКЛ. from anywhere. This is the one exception to «no shortcut without visible affordance» — emergency stop is too critical to hunt for.
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/destructive-actions.md:180:On trigger, it behaves identically to pressing-and-holding the АВАР. ОТКЛ. button: emits emergency_off_requested signal, which the engine handles as immediate hardware-level stop.
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/destructive-actions.md:198:- Label UPPERCASE for maximum emergency («АВАР. ОТКЛ.») OR sentence-case verb («Удалить») depending on severity
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/destructive-actions.md:228:6. **Double-confirmation on low-stakes.** «Удалить фильтр → Подтвердите → Да, удалить → Точно удалить?» Three clicks to clear a filter. Cumulative friction.
/Users/vladimir/Projects/cryodaq/docs/design-system/accessibility/keyboard-navigation.md:63:| **Ctrl+Shift+X** | **Emergency stop (АВАР. ОТКЛ.)** |
/Users/vladimir/Projects/cryodaq/docs/design-system/accessibility/keyboard-navigation.md:92:- Emergency stop may be needed when operator panics — hunting for the АВАР. ОТКЛ. button in the Keithley panel (which might not even be the active panel) costs seconds
/Users/vladimir/Projects/cryodaq/docs/design-system/accessibility/keyboard-navigation.md:94:- The Keithley panel's АВАР. ОТКЛ. hold-confirm button remains visible AND carries the same shortcut in its tooltip
/Users/vladimir/Projects/cryodaq/docs/design-system/accessibility/keyboard-navigation.md:239:- 2026-04-17 (v1.0.1): Aligned shortcut registry with mnemonic scheme per architect decision AD-002 (FR-011). Canonical bindings are Ctrl+L/E/A/K/M/R/C/D + Ctrl+Shift+X; numeric Ctrl+1..9 demoted to transitional fallback. Updated "type while focus elsewhere" example to use Ctrl+E. `tokens/keyboard-shortcuts.md` is the canonical registry — this file mirrors it.
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/tool-rail.md:54:| 6 | `activity` or `thermometer` | Теплопроводность | `Ctrl+C` | Ctrl+6 |
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/tool-rail.md:351:- 2026-04-17 (v1.0.1): Aligned with canonical mnemonic shortcut registry per AD-002 (FR-011). Added canonical-shortcut column to the slot table (Ctrl+E / Ctrl+K / Ctrl+A / Ctrl+C / Ctrl+M / Ctrl+L / Ctrl+D). Demoted Ctrl+[1-9] to "numeric fallback" column. Clarified that slots 1 and 2 do not yet have approved mnemonics and still rely on the fallback. Keyboard-shortcut-policy section rewritten to match.
/Users/vladimir/Projects/cryodaq/docs/design-system/accessibility/contrast-matrix.md:224:- 2026-04-17: v1.0.1 — Recomputed all ratios from theme.py. Fixed stale ON_DESTRUCTIVE input. Corrected BORDER non-text contrast.
/Users/vladimir/Projects/cryodaq/docs/design-system/FINAL_REVIEW_REPORT.md:9:This does **not** require a redesign. It requires a targeted v1.0.1 doc repair pass. The codebase ground truth is stable enough: `src/cryodaq/gui/theme.py`, current dashboard widgets, `config/channels.yaml`, and `config/safety.yaml` make the intended reality readable. The design-system docs need to catch up to that reality and stop mixing current-state guidance with future-state proposals without labeling.
/Users/vladimir/Projects/cryodaq/docs/design-system/FINAL_REVIEW_REPORT.md:57:- **[FR-016]** `[source: final review, new]` Pressure-unit policy splits across layers. [rules/content-voice-rules.md](/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md):368-371 says operator-facing pressure unit is `мбар`, not `mbar`. But [rules/data-display-rules.md](/Users/vladimir/Projects/cryodaq/docs/design-system/rules/data-display-rules.md):174,182,320,331,425,430,446, [tokens/typography.md](/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md):128, [tokens/chart-tokens.md](/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/chart-tokens.md):126,140, and [cryodaq-primitives/top-watch-bar.md](/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/top-watch-bar.md):53 currently use or exemplify `mbar`. **Fix:** canonicalize one operator-facing unit spelling and update every example and invariant to match. **Blast radius:** high — copy, chart, and widget docs currently point in two directions.
/Users/vladimir/Projects/cryodaq/docs/design-system/FINAL_REVIEW_REPORT.md:95:- **[FR-016] Pressure-unit split.** Token and chart examples still say `mbar`, while copy rules require `мбар`. This is not just wording drift; it creates two incompatible operator-facing conventions.
/Users/vladimir/Projects/cryodaq/docs/design-system/FINAL_REVIEW_REPORT.md:119:### Batch 1 — CRITICAL fixes (block v1.0.0 → v1.0.1)
/Users/vladimir/Projects/cryodaq/docs/design-system/FINAL_REVIEW_REPORT.md:130:### Batch 2 — HIGH fixes (v1.0.1 → v1.1.0)
/Users/vladimir/Projects/cryodaq/docs/design-system/FINAL_REVIEW_REPORT.md:193:- [FR-016] Fix `units='mbar'` example if operator-facing canonical unit is `мбар`
/Users/vladimir/Projects/cryodaq/docs/design-system/FINAL_REVIEW_REPORT.md:197:- [FR-016] Fix `mбар`/`mbar` invariant language and API example
/Users/vladimir/Projects/cryodaq/docs/design-system/FINAL_REVIEW_REPORT.md:236:  Recommendation: for immediate v1.0.1 integrity, patch docs to truthfully describe current code unless Vladimir explicitly wants the code reverted in a near-term block.
/Users/vladimir/Projects/cryodaq/docs/design-system/FINAL_REVIEW_REPORT.md:267:- [ ] Version bump to v1.0.1
/Users/vladimir/Projects/cryodaq/docs/design-system/FINAL_REVIEW_REPORT.md:299:| R-027 | final review | — | `rules/content-voice-rules.md`, `rules/data-display-rules.md`, `tokens/*`, `top-watch-bar.md` | Pressure-unit convention split (`мбар` vs `mbar`) | CONFIRMED | HIGH |
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/information-hierarchy.md:60:- Channel friendly names («Теплообменник 1» in sensor cells)
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/information-hierarchy.md:158:- **RULE-TYPO-007** — off-scale protected font sizes (FONT_MONO_VALUE_SIZE, FONT_DISPLAY_SIZE) reserved for Tier 1 & 2
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/motion.md:26:# Canonical usage — RULE-COLOR-010-style rule: reference theme, not literals
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/motion.md:203:- 2026-04-17 (v1.0.1): Acknowledged that `TRANSITION_FAST_MS` / `TRANSITION_BASE_MS` / `TRANSITION_SLOW_MS` are shipped in `theme.py` (FR-003). Removed the "NOT yet in theme.py" claim; replaced duration-literal examples with token references; moved the richer `DURATION_*` family to an explicitly "proposed future expansion" section. Easing tokens remain proposed.
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/breakpoints.md:56:Текущий: 1024×768
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/numeric-formatting.md:22:| **Temperature** | `{:.2f}` | K (Cyrillic К also valid, prefer Latin K for SI) | `4.21 K`, `77.30 K`, `350.00 K` |
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/numeric-formatting.md:23:| **Pressure** | `{:.2e}` | мбар | `1.23e-06 мбар`, `9.87e-03 мбар` |
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/numeric-formatting.md:70:Pressure values span ~10 orders of magnitude in a cryogenic system (atmospheric 1e3 мбар → ultra-high vacuum 1e-10 мбар). Always scientific notation with 2 decimals in the mantissa:
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/numeric-formatting.md:73:1.23e-06 мбар   ← canonical form
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/numeric-formatting.md:74:9.87e-03 мбар
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/numeric-formatting.md:75:1.00e+00 мбар
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/numeric-formatting.md:76:1.23e+03 мбар   ← atmospheric
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/numeric-formatting.md:81:Never linear: `0.00000123 мбар` is unreadable at-a-glance; count of zeros hides magnitude.
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/numeric-formatting.md:94:0.00e+00 мбар  ← not "0 мбар"
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/numeric-formatting.md:198:Т1 – Т14            ← using en-dash (U+2013) for range
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/numeric-formatting.md:203:Not `Т1-Т14` (hyphen, tight). Not `Т1 to Т14` (English «to»).
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/numeric-formatting.md:281:5. **Linear pressure.** `0.00000123 мбар`. Use scientific. RULE-DATA-005.
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/experiment-panel.md:26:**Decision: Path A — surgical harmonization.** The overlay was already DS v1.0.1-compliant at shipping (B.8). The single remaining gap was the missing Host Integration Contract: `set_connected(bool)` to disable action buttons on engine silence. Path A lands exactly that hook with a minimal diff; Path B would have been churn without deliverable improvement.
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/experiment-panel.md:81:- `rules/color-rules.md` RULE-COLOR-010 — no hardcoded hex (satisfied; zero hits in Stage 0).
/Users/vladimir/Projects/cryodaq/docs/design-system/HANDOFF_THEMES_V2.md:12:(BG luminance > 0.8). Темы с «warm» в названиях
/Users/vladimir/Projects/cryodaq/docs/design-system/HANDOFF_THEMES_V2.md:26:design-осью**, не hue. Три dark, три light.
/Users/vladimir/Projects/cryodaq/docs/design-system/HANDOFF_THEMES_V2.md:33:| `gost.yaml` | ГОСТ | light | кремовая бумага + wine accent | 315° wine-maroon |
/Users/vladimir/Projects/cryodaq/docs/design-system/HANDOFF_THEMES_V2.md:105:**Ассоциативный якорь:** Тарковский, аналоговая warm-медитативность.
/Users/vladimir/Projects/cryodaq/docs/design-system/HANDOFF_THEMES_V2.md:132:## 4. Light — ГОСТ (`gost.yaml`)
/Users/vladimir/Projects/cryodaq/docs/design-system/HANDOFF_THEMES_V2.md:134:**Ассоциативный якорь:** советская инженерная документация ВНИИФТРИ,
/Users/vladimir/Projects/cryodaq/docs/design-system/HANDOFF_THEMES_V2.md:225:ГОСТ — ближе к «белой поверхности продукта», не к «старой бумаге»).
/Users/vladimir/Projects/cryodaq/docs/design-system/HANDOFF_THEMES_V2.md:247:- BG hue 43° sat 27% — теплее Xcode (cool), прохладнее ГОСТ (warm
/Users/vladimir/Projects/cryodaq/docs/design-system/HANDOFF_THEMES_V2.md:256:- Тема ближе к «Braun-влияние» чем к «Braun-reproduction».
/Users/vladimir/Projects/cryodaq/docs/design-system/HANDOFF_THEMES_V2.md:268:| STATUS_OK | `#4a8a5e` | `#2e6b45` | 139° |
/Users/vladimir/Projects/cryodaq/docs/design-system/HANDOFF_THEMES_V2.md:293:3. **Settings → Тема menu** — добавить radio-selection пункты для
/Users/vladimir/Projects/cryodaq/docs/design-system/HANDOFF_THEMES_V2.md:304:     light-темы проверить что STATUS/CARD ≥4.5:1 (см. Таблицу 2
/Users/vladimir/Projects/cryodaq/docs/design-system/HANDOFF_THEMES_V2.md:333:- **ГОСТ:** при возражениях на wine-magenta accent — альтернатива
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/alarm-panel.md:19:- Emoji → `SeverityChip` pill widget using `STATUS_FAULT` / `STATUS_WARNING` / `STATUS_INFO` tokens with Russian short labels (`КРИТ` / `ПРЕД` / `ИНФО`).
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/alarm-panel.md:42:│ ┌ Card: Текущие тревоги (v1) ──────────────────────────────┐   │
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/alarm-panel.md:43:│ │  [КРИТ] | Имя | Канал | Значение | Порог | Время | N | ACK   │
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/alarm-panel.md:47:│ │  [КРИТ] | alarm_id | Сообщение | Каналы | Время | ACK        │
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/alarm-panel.md:92:- Label: `КРИТ` / `ПРЕД` / `ИНФО` (Russian short, `FONT_MONO` + SEMIBOLD, `FONT_SIZE_XS`).
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/alarm-panel.md:111:- `rules/color-rules.md` RULE-COLOR-010 — no hardcoded hex (satisfied: only DS tokens).
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/alarm-panel.md:119:- **2026-04-18 (Phase II.4)** — rebuild landed. Emoji removed; DS v1.0.1 tokens throughout; `set_connected` hook added; eager registration kept by design (tray-count path).
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/cross-surface-consistency.md:52:The easiest drift: one panel uses «Температуры» sentence case as a section header; another uses «ТЕМПЕРАТУРЫ» uppercase. They look like different features. Fix: RULE-TYPO-008 says UPPERCASE for category labels, always.
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/keyboard-shortcuts.md:179:- 2026-04-17 (v1.0.1): Marked canonical per architect decision AD-002 (FR-011). Clarified that mnemonic shortcuts (`Ctrl+L`, `Ctrl+E`, …) are the canonical scheme and that `Ctrl+[1-9]` numeric rail-slot navigation is transitional. Removed `Ctrl+1`…`Ctrl+6` phase-jump entries to eliminate collision with rail slot bindings. Changed status from `partially-proposed` to `canonical`.
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/quick-log-block.md:35:│  ЖУРНАЛ ОПЕРАТОРА                                     [ 📓 Открыть ] │
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/quick-log-block.md:124:        super().__init__(parent=parent, title="ЖУРНАЛ ОПЕРАТОРА")
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/quick-log-block.md:157:        title = QLabel("ЖУРНАЛ ОПЕРАТОРА")
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/instruments-panel.md:25:- Summary emoji replaced by `SeverityChip` widgets imported from `shell/overlays/alarm_panel.py` (reuse the exact DS status pill pattern). Labels become plain Russian («ОК / ПРЕД / КРИТ»).
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/instruments-panel.md:41:3. LakeShore T-number mapping (`Т1–8` → `LS218_1`, `Т9–16` → `LS218_2`, `Т17–24` → `LS218_3`).
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/instruments-panel.md:66:│ ПРИБОРЫ И ДИАГНОСТИКА                                          │
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/instruments-panel.md:76:│ ┌ Card: ДИАГНОСТИКА ДАТЧИКОВ     [18 ОК][1 ПРЕД][1 КРИТ] ───┐  │
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/instruments-panel.md:117:- `rules/color-rules.md` RULE-COLOR-010 — no hardcoded hex (satisfied).
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/responsive-behavior.md:176:9. **Auto-wrapping category labels.** «ТЕПЛОПРОВОДНОСТЬ ОБРАЗЦА В АЗОТНОЙ ВАННЕ» as section header wraps to two lines. Shorten the label; don't handle the wrap.
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/copy-voice.md:42:   - «ДАВЛЕНИЕ», «Т МИН», «Т МАКС», «НАГРЕВАТЕЛЬ» (TopWatchBar)
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/copy-voice.md:43:   - «ЭКСПЕРИМЕНТ», «ЖУРНАЛ ОПЕРАТОРА» (card titles)
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/copy-voice.md:44:   - «ДИНАМИКА ТЕМПЕРАТУР» (chart tile title)
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/copy-voice.md:48:   - Emergency destructive button: «АВАР. ОТКЛ.»
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/copy-voice.md:158:## Channel IDs (Cyrillic Т)
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/copy-voice.md:160:Always Cyrillic Т (U+0422) in channel identifiers shown to the operator:
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/copy-voice.md:162:- «Т1», «Т11», «Т24» (not Latin «T11»)
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/copy-voice.md:163:- «Т мин», «Т макс» (TopWatchBar labels)
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/copy-voice.md:182:- «Температура превышает 400 K. Введите значение от 0 до 400.»
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/copy-voice.md:244:- «Давление достигло 1.23e-06 мбар»
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/copy-voice.md:257:- **K** (Kelvin) — Latin K is international SI; «К» Cyrillic also valid. Pick one and use consistently. Recommend Latin K for SI alignment.
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/copy-voice.md:258:- **мбар** (millibar)
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/copy-voice.md:284:- Mixed Cyrillic/Latin when one or the other would suffice
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/copy-voice.md:292:- OR avoid count display where plural would be awkward (e.g., «Тревог: 3» with separator)
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/copy-voice.md:308:- **RULE-COPY-001** — Cyrillic Т for channel IDs
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/copy-voice.md:316:- **RULE-TYPO-005** — Cyrillic uppercase letter-spacing
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/copy-voice.md:333:7. **UPPERCASE for regular labels.** «НАСТРОЙКИ» as panel title. Use sentence case «Настройки». UPPERCASE reserved per `patterns/information-hierarchy.md`.
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/copy-voice.md:339:10. **Latin T in channel ID.** «T11» with Latin T. Must be Cyrillic Т11.
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/conductivity-panel.md:18:> auto-sweep), DS v1.0.1 tokens exclusively (zero legacy tokens,
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/conductivity-panel.md:46:- ToolRail slot «Теплопроводность» opens this overlay.
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/conductivity-panel.md:68:│  ТЕПЛОПРОВОДНОСТЬ                                                    │
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/conductivity-panel.md:74:│  │ ☐ Т1 Криостат верх    │ │ Стабильность: ...   P = ... Вт     │  │
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/conductivity-panel.md:75:│  │ ☑ Т3 Рад. 1           │ │                                     │  │
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/conductivity-panel.md:76:│  │ ☑ Т4 Рад. 2           │ │ ┌─ R/G Table (11 cols) ──────────┐ │  │
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/conductivity-panel.md:77:│  │ ☑ Т5 Экран77          │ │ │ Пара | T гор. | T хол. | dT | R │ │  │
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/conductivity-panel.md:79:│  │                        │ │ │ ИТОГО                           │ │  │
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/conductivity-panel.md:104:| **Header** | Yes | «ТЕПЛОПРОВОДНОСТЬ» title, FONT_SIZE_XL semibold with letter-spacing (RULE-TYPO-005) |
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/conductivity-panel.md:108:| **R/G table** | Yes | 11 columns: Пара / T гор. / T хол. / dT / R / G / T∞ прогноз / τ (мин) / Готово % / R прогноз / G прогноз. ИТОГО row summarizes first-to-last endpoints. FONT_MONO cells with tabular figures. |
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/conductivity-panel.md:175:- Pre-commit gates: forbidden-token grep, emoji scan, and hex-color scan must all be clean before commit (any hex outside `PLOT_LINE_PALETTE` is a RULE-COLOR-010 violation).
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/conductivity-panel.md:186:| **Stabilization reached (banner)** | «ГОТОВО — стационар достигнут» STATUS_OK |
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/conductivity-panel.md:199:6. **Using `apply_group_box_style` / `apply_button_style` / `apply_status_label_style`** — forbidden. Inline QSS with DS v1.0.1 tokens only.
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/conductivity-panel.md:212:- **2026-04-19 — Phase II.5 initial version.** Full rewrite from legacy v1 at `src/cryodaq/gui/widgets/conductivity_panel.py`. DS v1.0.1 tokens throughout; legacy helpers (`PanelHeader` / `StatusBanner` / `apply_button_style` / `apply_group_box_style` / `apply_status_label_style` / `build_action_row` / `create_panel_root`) purged. Hardcoded `_LINE_COLORS` palette replaced with `PLOT_LINE_PALETTE` via `series_pen`. Auto-sweep FSM preserved verbatim: `idle` / `stabilizing` / `done` states, 1 Hz `QTimer` tick, `SteadyStatePredictor`-driven settling detection, Keithley power stepping via `ZmqCommandWorker`. Flight recorder schema (18 columns, `utf-8-sig`) and path (`get_data_dir() / conductivity_logs / conductivity_<ts>.csv`) preserved. Public accessor `get_auto_state()` / `is_auto_sweep_active()` added for future ExperimentOverlay finalize guard (II.9). Host Integration Contract wired: `_tick_status` mirror + `_ensure_overlay("conductivity")` replay. Legacy widget marked DEPRECATED; removal scheduled for Phase III.3.
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/analytics-panel.md:106:│  Прогноз: 1e-6 мбар через ~2ч 30мин   [compact log-Y sparkline]   │
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/analytics-panel.md:193:  Cyrillic).
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/analytics-panel.md:233:Cyrillic мбар axis, log-Y per RULE-DATA-008) is tracked as a separate
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/analytics-panel.md:269:4. **Cyrillic where user-facing** (RULE-COPY-001, RULE-COPY-006):
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/analytics-panel.md:270:   Т for channel IDs, мбар for pressure units, «R_тепл» not
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/analytics-panel.md:401:- RULE-COPY-001 — Cyrillic Т for channel IDs
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/analytics-panel.md:403:- RULE-COPY-006 — мбар canonical
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/interaction-rules.md:171:**Statement:** Destructive actions — emergency stop (АВАР. ОТКЛ.), delete experiment, clear archive, overwrite configuration — MUST use one of:
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/interaction-rules.md:179:**Applies to:** АВАР. ОТКЛ., delete actions, configuration overwrites, irreversible state changes
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/color-rules.md:27:- RULE-COLOR-010 — Legacy STONE_* tokens read-only in new code
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/color-rules.md:377:**TL;DR:** Destructive action buttons (АВАР. ОТКЛ., Удалить эксперимент) use `theme.DESTRUCTIVE`, not raw `STATUS_FAULT`. They are aliases but semantic intent differs.
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/color-rules.md:394:emergency_stop = QPushButton("АВАР. ОТКЛ.")
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/color-rules.md:500:  - Highlighting Т5 (Экран 77К) or Т6 (Экран 4К) in sensor grid
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/color-rules.md:551:## RULE-COLOR-010: Legacy STONE_* tokens read-only in new code
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/color-rules.md:578:# DESIGN: RULE-COLOR-010
/Users/vladimir/Projects/cryodaq/docs/design-system/governance/testing-strategy.md:39:Enforce RULE-COLOR-010: all color references go through `theme` module; no raw hex in component code.
/Users/vladimir/Projects/cryodaq/docs/design-system/governance/testing-strategy.md:96:Enforce RULE-TYPO-007: only approved font sizes, no ad-hoc pixel values.
/Users/vladimir/Projects/cryodaq/docs/design-system/governance/testing-strategy.md:115:Enforce RULE-SPACE-001: only approved spacing values (`SPACE_0..SPACE_6`). Catches `margin: 18px` (not 16 or 24).
/Users/vladimir/Projects/cryodaq/docs/design-system/governance/testing-strategy.md:130:### Cyrillic Т vs Latin T lint
/Users/vladimir/Projects/cryodaq/docs/design-system/governance/testing-strategy.md:336:- **RULE-COLOR-010** — token-based references (enforced via lint)
/Users/vladimir/Projects/cryodaq/docs/design-system/governance/testing-strategy.md:337:- **RULE-TYPO-007** — off-scale font sizes protected (enforced via lint)
/Users/vladimir/Projects/cryodaq/docs/design-system/governance/testing-strategy.md:338:- **RULE-SPACE-001** — spacing scale (enforced via lint)
/Users/vladimir/Projects/cryodaq/docs/design-system/governance/testing-strategy.md:339:- **RULE-COPY-001** — Cyrillic Т (enforced via lint)
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/spacing-rules.md:18:- RULE-SPACE-001 — Inline row gaps (4-8px for icon+text, 12-16px for controls)
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/spacing-rules.md:29:## RULE-SPACE-001: Inline row gaps
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/spacing-rules.md:39:| Label + value in data row | `SPACE_2` | 8px | `Т мин:  3.90 K` |
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/spacing-rules.md:50:# DESIGN: RULE-SPACE-001
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/spacing-rules.md:61:data_row.addWidget(QLabel("Т мин"))
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/spacing-rules.md:360:- Destructive "АВАР. ОТКЛ." button: may exceed ROW_HEIGHT for emphasis (documented)
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/spacing-rules.md:432:warning_row.setSpacing(theme.SPACE_1)  # 4px (RULE-SPACE-001)
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/spacing-rules.md:468:**Related rules:** RULE-SPACE-001 (inline row gaps), RULE-COLOR-005 (icon color inheritance), `tokens/icons.md`
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/experiment-card.md:20:> channel Т11 / Т12 + pressure in Cyrillic мбар), actions row
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/experiment-card.md:51:│  ЭКСПЕРИМЕНТ                               ● Эксперимент  ● 47 мин  │
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/experiment-card.md:65:│  │  Т11 (целевой канал):  4.21 K                              │     │  ◀── key vital
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/experiment-card.md:66:│  │  Давление:             1.23e-06 мбар                       │     │     (domain-specific
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/experiment-card.md:80:| **Header row** | Yes | Category label («ЭКСПЕРИМЕНТ») + mode badge + elapsed time |
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/experiment-card.md:92:4. **Target channel is a positionally fixed reference channel** (Т11 or Т12) — physically immovable on the second stage (nitrogen plate). Required for quantitative decisions because thresholds based on relocatable channels lose meaning between experiments. Other channels can be shown as context but not as target for alarm thresholds.
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/experiment-card.md:94:6. **Experiment name is operator-assigned freeform text.** May contain Latin chars (calibration_run_042), Cyrillic («Калибровка 2026-04»), or mix. Don't force Cyrillic-only. Apply same RULE-COPY-001 ONLY to channel IDs, not experiment names.
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/experiment-card.md:111:    target_channel_id: str        # "Т11" or "Т12" — positionally fixed reference channel
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/experiment-card.md:114:    pressure_mbar: float | None
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/experiment-card.md:198:        category = QLabel("ЭКСПЕРИМЕНТ")
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/experiment-card.md:245:        # DESIGN: RULE-COPY-001 Cyrillic Т, RULE-COPY-006 units
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/experiment-card.md:246:        self._target_line = QLabel("Т11 (целевой канал): —")
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/experiment-card.md:283:        if snapshot.pressure_mbar is not None:
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/experiment-card.md:284:            self._pressure_line.setText(f"Давление: {snapshot.pressure_mbar:.2e} мбар")
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/experiment-card.md:350:1. **Using a relocatable channel as target.** Т5 as target — its physical position may differ across experiments, so thresholds built on it are not reproducible. Target must be Т11 or Т12 (positionally fixed). Enforce at ExperimentSnapshot validation level.
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/experiment-card.md:380:- 2026-04-17: Initial version. Dashboard + Overlay variants. Target channel restricted to Т11 / Т12 — positionally fixed reference channels (second stage, nitrogen plate). Mode mirrors TopWatchBar. Fault chrome via 3px left border. Compact PhaseStepper for dashboard per Phase B.5.6. Abort uses Dialog-level confirmation on top of HoldConfirmButton hold safety.
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/operator-log-panel.md:18:> filter bar (quick chips «Все» / «Текущий экспт.» / «Последние 8ч» /
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/operator-log-panel.md:20:> state, load-more pagination, DS v1.0.1 tokens throughout. Composer
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/operator-log-panel.md:55:│  ЖУРНАЛ ОПЕРАТОРА                                                             │  ◀── header
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/operator-log-panel.md:60:│  │  Автор: [_____________]    Теги: [___________________________]          │  │  ◀── composer card
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/operator-log-panel.md:69:│  │  [Все] [Текущий экспт.] [Последние 8ч] [За сутки]                       │ │  ◀── filter bar
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/operator-log-panel.md:70:│  │  Поиск: [______________]   Автор: [________]   Тег: [________]          │ │
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/operator-log-panel.md:80:│  │         Аларм: Т11 выше порога                                           │ │  (gray,
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/operator-log-panel.md:95:| **Header** | Yes | «ЖУРНАЛ ОПЕРАТОРА» title in FONT_SIZE_XL semibold with letter-spacing (RULE-TYPO-005) |
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/operator-log-panel.md:104:| **Filter chips** | Yes | Mutually exclusive: «Все» / «Текущий экспт.» / «Последние 8ч» / «За сутки». Default «Последние 8ч». Active chip uses `accent` variant |
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/operator-log-panel.md:120:6. **«Текущий экспт.» is server-side.** Sends `current_experiment: true` in `log_get`. Other chips refetch without that flag and apply time cutoff client-side.
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/operator-log-panel.md:196:1. **Using TEXT_PRIMARY / TEXT_SECONDARY legacy tokens.** These are DS-v1.0.1-deprecated aliases. Use FOREGROUND / MUTED_FOREGROUND.
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/operator-log-panel.md:205:10. **Hardcoded pixel values.** Use SPACE_* and RADIUS_* tokens; raw pixel literals violate RULE-SPACE-001 / RULE-RADIUS-001.
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/operator-log-panel.md:217:- **2026-04-18 — Phase II.3 initial version.** Full rewrite from v1 widget at `src/cryodaq/gui/widgets/operator_log_panel.py`. Day-grouped timeline, filter chips (all / current / 8h / 24h), client-side text/author/tag search, composer with tags + experiment binding, DS v1.0.1 tokens, lazy host integration via `MainWindowV2._tick_status` / `_on_experiment_status_received` / `_ensure_overlay("log")` replay. Legacy widget marked DEPRECATED; removal scheduled for Phase III.3.
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/archive-panel.md:26:> `[ИЗМЕРЕНИЯ]` / `[УСТАВКИ]` per RULE-COPY-005. Host Integration
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/archive-panel.md:62:│  АРХИВ ЭКСПЕРИМЕНТОВ                                                          │  ◀── header
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/archive-panel.md:105:| **Header** | Yes | «АРХИВ ЭКСПЕРИМЕНТОВ» title, FONT_SIZE_XL semibold with letter-spacing (RULE-TYPO-005) |
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/archive-panel.md:128:10. **Artifact role formatting uses ASCII bracketed tags.** `[ДАННЫЕ]`, `[ИЗМЕРЕНИЯ]`, `[УСТАВКИ]`. No emoji. (RULE-COPY-005.)
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/archive-panel.md:215:- **2026-04-19 — Phase II.2 initial version.** Full rewrite from legacy v1 at `src/cryodaq/gui/widgets/archive_panel.py`. DS v1.0.1 tokens throughout; legacy helpers (`PanelHeader` / `StatusBanner` / `build_action_row` / `create_panel_root` / `setup_standard_table` / `add_form_rows` / `TEXT_DISABLED`) purged. Emoji in artifact roles replaced with ASCII bracketed tags. K6 bulk export migration: CSV / HDF5 / Excel card added with `QThread` workers wrapping existing exporter classes unchanged. Host Integration Contract wired via `MainWindowV2._tick_status` mirror + `_ensure_overlay("archive")` replay; `on_reading` is a contract no-op (no engine finalize event). Legacy widget marked DEPRECATED; removal scheduled for Phase III.3.
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/data-display-rules.md:175:**TL;DR:** Temperature = 2 decimals ("3.90 K"). Pressure = scientific with 2 mantissa digits ("1.23e-06 мбар"). Voltage = 3 decimals ("1.234 V"). Precision is per-quantity, constant.
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/data-display-rules.md:183:| Pressure (мбар) | scientific 2 mantissa | `1.23e-06`, `8.75e-03` |
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/data-display-rules.md:202:def format_pressure(value_mbar: float) -> str:
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/data-display-rules.md:203:    return f"{value_mbar:.2e}"  # always scientific, 2 mantissa digits
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/data-display-rules.md:237:Т11 (Криостат)
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/data-display-rules.md:329:**TL;DR:** Every numeric value shown to operator MUST include its unit (K, мбар, V, A, W, Ω). No implicit units. No unit in header/column alone.
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/data-display-rules.md:340:SI mandatory: K (not Kelvin or °K), мбар (avoid Latin pressure-unit spelling in operator-facing text per RULE-COPY-006), V, A, W, Ω (not Ohm).
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/data-display-rules.md:355:status_label.setText(f"Температура стабилизирована на {temp:.2f} K")
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/data-display-rules.md:358:plot.getAxis('left').setLabel("Температура", units="K")
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/data-display-rules.md:368:column_header.setText("Температура (K)")
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/data-display-rules.md:410:    plot.plot(data, pen=pen, name=f"Т{index + 1}")
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/data-display-rules.md:455:plot.getAxis('left').setLabel("Давление", units="мбар")
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/data-display-rules.md:456:plot.plot(timestamps, pressures_mbar, pen=pg.mkPen(theme.COLD_HIGHLIGHT))
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/data-display-rules.md:464:plot.plot(timestamps, pressures_mbar)
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/data-display-rules.md:468:pressures_log = [math.log10(p) for p in pressures_mbar]
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/data-display-rules.md:561:plot.getAxis('left').setLabel("Температура", units="K")
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/data-display-rules.md:605:- 2026-04-17 (v1.0.1): Switched operator-facing pressure unit examples from `mbar` to `мбар` (RULE-DATA-004 TL;DR, table row, RULE-DATA-006 TL;DR + SI line, RULE-DATA-008 axis-label code example). Code identifiers (`pressures_mbar`, `value_mbar` parameter) and English-prose explanations of the magnitude-span rationale stay as-is. (FR-016)
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/governance-rules.md:47:**Current version:** v1.0.1 (post-deep-audit cleanup of v1.0.0 initial release).
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/governance-rules.md:60:- What cannot be deprecated (Cyrillic Т, SI units, WCAG AA commitment, persistence-first, TSP-not-SCPI)
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/governance-rules.md:78:These three rules are themselves subject to the design system's evolution process. They can be deprecated, revised, or removed through the contribution process (`governance/contribution.md`). Current v1.0.1 state: all three Active, no pending changes.
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/governance-rules.md:82:- `rules/color-rules.md` — RULE-COLOR-010 token-referenced colors feeds into GOV-001
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/governance-rules.md:83:- `rules/typography-rules.md` — RULE-TYPO-007 protected font sizes feeds into GOV-001
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/governance-rules.md:84:- `rules/spacing-rules.md` — RULE-SPACE-001 scale adherence feeds into GOV-001
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/keithley-panel.md:18:> (Cyrillic А per RULE-COPY-002), per-channel P target / V compliance /
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/keithley-panel.md:29:> / «Стоп A+B» / «АВАР. ОТКЛ. A+B», time-window toolbar
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/keithley-panel.md:86:│  │  [Старт][Стоп][АВАР.ОТКЛ]│     │  [Старт][Стоп][АВАР.ОТКЛ]│                │
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/keithley-panel.md:88:│  │  Напряжение   Ток        │     │  Напряжение   Ток        │                │
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/keithley-panel.md:100:│                          [Старт A+B] [Стоп A+B] [АВАР. ОТКЛ. A+B]             │  ◀── footer: panel-level
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/keithley-panel.md:115:| **Controls card** | Per channel | P target + V compliance + I compliance `QDoubleSpinBox` + Старт / Стоп / АВАР. ОТКЛ. |
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/keithley-panel.md:118:| **Panel-level footer** | Yes | «Старт A+B» / «Стоп A+B» / «АВАР. ОТКЛ. A+B» (single confirmation dialog for A+B emergency) |
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/keithley-panel.md:133:12. **Labels «Канал А» / «Канал B», not «smua» / «smub» in operator-facing UI.** Those identifiers are internal. Cyrillic А (U+0410), Latin B. (RULE-COPY-002.)
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/keithley-panel.md:190:- **Footer right-anchored.** Panel-level «Старт A+B» / «Стоп A+B» / «АВАР. ОТКЛ. A+B» all right-aligned with equal spacing.
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/keithley-panel.md:208:1. **Inventing mode semantics.** The engine does not have a `mode` field. `p_target + v_comp + i_comp` is the complete control surface. B.7 (`920aa97`) invented Ток/Напряжение/Откл and was never wired. Do not reintroduce.
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/keithley-panel.md:212:5. **Using «smua» / «smub» as operator labels.** Those are TSP identifiers. Operator sees «Канал А» / «Канал B». RULE-COPY-002. Cyrillic А (U+0410), not Latin A.
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/calibration-panel.md:30:> result (v1 declared them but never wrote). DS v1.0.1 tokens
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/calibration-panel.md:68:│  КАЛИБРОВКА ДАТЧИКОВ                                                 │
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/calibration-panel.md:74:│  │  │ Опорный канал: [▼ LS218_1:Т1]                    │         │  │
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/calibration-panel.md:75:│  │  │ [LS218_1 group] [☑Т1] [☑Т2] [☑Т3]...             │         │  │
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/calibration-panel.md:91:│  │  │ Точек записано: N                                  │         │  │
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/calibration-panel.md:99:│  │  │ Т1_raw: 1234.5                                     │         │  │
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/calibration-panel.md:100:│  │  │ Т2_raw: 2345.6                                     │         │  │
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/calibration-panel.md:105:│  │  ┌─ Канал: [▼ Т1] ───────────────────────────────────┐         │  │
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/calibration-panel.md:128:| **Header** | Yes | «КАЛИБРОВКА ДАТЧИКОВ» title, FONT_SIZE_XL semibold with letter-spacing (RULE-TYPO-005) |
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/calibration-panel.md:134:| **Acquisition: Stats card** | Yes | Эксперимент / Время (HH:MM:SS) / Точек / Диапазон T_ref. Values from poll result. |
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/calibration-panel.md:150:7. **CoverageBar token-coded.** Status strings (`dense` / `medium` / `sparse` / `empty`) map 1:1 to `STATUS_OK` / `STATUS_CAUTION` / `STATUS_WARNING` / `MUTED_FOREGROUND`. RULE-COLOR-010 compliance verified by pre-commit hex grep.
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/calibration-panel.md:246:- **2026-04-19 — Phase II.7 initial version.** Full rewrite from legacy v1 at `src/cryodaq/gui/widgets/calibration_panel.py`. DS v1.0.1 tokens throughout; legacy helpers (`PanelHeader` / `StatusBanner` / `apply_button_style` / `apply_group_box_style` / `create_panel_root` / `setup_standard_table`) purged. CoverageBar hardcoded hex palette replaced with DS status tokens. Three-mode QStackedWidget + 3 s engine poll + auto-switch logic preserved verbatim. **K3 mandate completed:** all six import / export / runtime-apply buttons now dispatch real engine commands (`calibration_curve_import`, `calibration_curve_export`, `calibration_runtime_set_global`, `calibration_runtime_set_channel_policy` with `calibration_curve_lookup` bridge). Acquisition widget's `_experiment_label` / `_elapsed_label` populated from poll result (v1 declared them but never wrote). Public accessors `get_current_mode()` / `is_acquisition_active()` added for future finalize guards. Host Integration Contract wired: `_tick_status` mirror + `_ensure_overlay("calibration")` replay. Legacy widget marked DEPRECATED; removal scheduled for Phase III.3.
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:18:- RULE-COPY-001 — Cyrillic Т (U+0422) for temperature channels
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:29:## RULE-COPY-001: Cyrillic Т (U+0422) for temperature channels
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:31:**TL;DR:** Temperature channel labels use Cyrillic `Т` (U+0422), never Latin `T` (U+0054). Applies to Т1–Т24 channel IDs in user-facing strings.
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:33:**Statement:** All temperature channel identifiers displayed to operators MUST use Cyrillic letter `Т` (U+0422). Latin `T` (U+0054) is visually identical but distinct at code-point level and breaks consistency. Applies to:
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:35:- Channel labels in SensorCell (`Т1`, `Т2`, ..., `Т24`)
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:44:**Rationale:** Russian operator expects Russian text. Mixing Latin `T` with Cyrillic context creates visual jitter. Many fonts render Cyrillic `Т` with different metrics than Latin `T` (especially in monospace at small sizes) — mixing causes subtle layout drift. Code review must catch this because it's easy to type Latin T on Latin keyboard.
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:52:# channels.yaml — Cyrillic Т
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:54:  Т1:
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:58:  Т2:
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:66:label = QLabel("Т5")  # U+0422 Cyrillic Т
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:71:fault_message = f"Канал Т11 превысил лимит: {value:.2f} K"  # Cyrillic Т
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:80:# Mixed Latin / Cyrillic in same string
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:81:message = f"Temperature T1 → Т2 transition"  # inconsistent
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:99:# Replace Latin T with Cyrillic Т in user-facing YAML strings
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:106:    fixed = re.sub(r'(\s|^)T(\d+):', r'\1Т\2:', text)
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:110:**Related rules:** RULE-TYPO-002 (Fira fonts include Cyrillic), RULE-COPY-002 (Russian vocabulary)
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:126:| Emergency stop | «Аварийное отключение» or «АВАР. ОТКЛ.» | «Экстренная остановка», «Emergency Stop» |
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:134:| Temperature | «Температура» | «Температьюр» |
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:141:| Fault / alarm | «Авария», «Тревога» | «Фолт» |
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:168:**Related rules:** RULE-COPY-001 (Cyrillic Т), RULE-COPY-003 (sentence case)
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:193:table_header = "Температура канала"
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:194:log_entry = "Датчик Т11 восстановил связь в 14:32"
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:203:table_header = "Температура Канала"                                               # WRONG
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:206:log_entry = "датчик т11 восстановил связь"  # WRONG — Cyrillic Т missing + no capital
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:209:**Exception per RULE-TYPO-008:** Category labels, tile titles, destructive action buttons MAY be UPPERCASE («ДАВЛЕНИЕ», «АВАР. ОТКЛ.»). That is a separate convention for labels, not prose.
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:236:"Канал Т11 не обновлялся более 10 секунд. Проверьте подключение LakeShore #2 (GPIB 14)."
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:258:"В процессе циклического опроса температурных датчиков канала Т11 контроллером LakeShore 218S "
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:275:Датчик Т7 потерял связь.
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:341:alarm_text = "🚨 АВАРИЯ: Канал Т11"  # WRONG — emoji prefix
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:364:**TL;DR:** Display values in SI units with correct Russian spacing and symbols. `3.90 K` (space between value and unit), `1.23 × 10⁻⁶ мбар`, `42 Вт`.
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:369:2. **Standard symbols.** Temperature: `K` (Kelvin). Pressure: `мбар` (millibar) or `Па` (Pascal). Power: `Вт` (Watt). Current: `А` (Ampere). Voltage: `В` (Volt). Resistance: `Ом` (Ohm).
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:370:3. **Scientific notation for small/large values.** Pressure in vacuum ranges uses `1.23 × 10⁻⁶ мбар` or `1.23e-6 мбар`. Don't write `0.00000123 мбар`.
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:372:5. **Units in Russian where established.** Use `мбар`, `Вт`, `Ом` in operator-facing text; avoid Latin pressure/power/resistance spellings. Kelvin stays `K` (international convention for temperature).
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:386:pressure_display = f"{value:.2e} мбар"  # "1.23e-06 мбар"
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:403:pressure_display = f"{value:.2e} mbar"  # WRONG — use "мбар"
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:410:pressure_display = f"{value:.10f} мбар"  # WRONG — "0.0000012345 мбар" unreadable
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:421:def format_pressure(value_mbar: float) -> str:
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:422:    """1.23e-06 мбар — scientific, 2 significant figures, Russian unit."""
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:423:    return f"{value_mbar:.2e} мбар"
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:464:QLabel("Датчик Т7 не откликается")      # current state
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:520:pressure = f"{value:.2e} мбар"              # "1.23e-06 мбар"
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:540:tooltip = "Температура повысилась на 0,5 K за минуту"  # acceptable in prose
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:561:title = QLabel("Текущие тревоги (v1)")
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:593:**Related rules:** RULE-COPY-001 (Cyrillic channel names), RULE-COPY-002 (Russian vocabulary), RULE-COPY-007 (imperative/descriptive).
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:599:- 2026-04-17: Initial version. 8 rules covering Cyrillic Т, Russian vocabulary, sentence case, error style, emoji prohibition, SI units, imperative/descriptive, decimal convention. RULE-COPY-004 fills the previously-reserved gap.
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:600:- 2026-04-17 (v1.0.1): Verified canonical operator-facing pressure unit is `мбар` per RULE-COPY-006 (FR-016). No content change here — this file already states the canonical unit; downstream files (typography.md, chart-tokens.md, top-watch-bar.md, data-display-rules.md) updated to match.
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/phase-stepper.md:93:9. **Cyrillic labels only.** Phase names are Russian: «Готов», «Охлаждение», «Захолаживание», «Измерение», «Отогрев», «Завершение». (RULE-COPY-001, RULE-COPY-002)
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/phase-stepper.md:199:            # DESIGN: RULE-TYPO-005 (Cyrillic letter-spacing), RULE-TYPO-008 (UPPERCASE for active)
/Users/vladimir/Projects/cryodaq/docs/design-system/AUDIT_REPORT_B.md:115:The component-spec layer is structurally usable, and the domain-fact layer is in better shape than the raw traceability layer: I did **not** find the high-cost B5 failures this audit was specifically watching for (wrong `Т11/Т12` metrology claim, Latin `T` in operator-facing examples, uppercase FSM states as normative UI text, or SCPI replacing Keithley TSP). The main problems are elsewhere: several specs point to nonexistent or wrong implementation files, `bento-grid.md` no longer describes the actual shipped grid primitive, and one code example (`toast.md`) is not syntactically valid Python. That means the layer is directionally sound but not yet trustworthy as an implementation source of truth without a cleanup pass on traceability and example accuracy.
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/top-watch-bar.md:17:> height = `HEADER_HEIGHT` (56px), pressure formatted in `мбар`
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/top-watch-bar.md:18:> (Cyrillic), `Т мин` / `Т макс` locked to `Т11` / `Т12` (positionally
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/top-watch-bar.md:48:│  Давление         Т мин         Т макс         Нагреватель    [Эксперимент] │
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/top-watch-bar.md:49:│  1.23e-06 мбар    4.21 K        77.3 K         0.125 Вт                    │
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/top-watch-bar.md:66:| **Vital cells** | 4 fixed | ДАВЛЕНИЕ, Т МИН, Т МАКС, НАГРЕВАТЕЛЬ — in that order |
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/top-watch-bar.md:74:3. **Pressure always in мбар, scientific notation.** (RULE-COPY-006, RULE-DATA-005)
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/top-watch-bar.md:75:4. **T min / T max use Т11 and Т12.** These are the positionally fixed reference channels — physically immovable on the second stage (nitrogen plate); cannot be relocated without dismantling the rheostat. All temperature channels are metrologically calibrated, but other channels may change position between experiments, making them unsuitable as fixed quantitative reference points. Using other channels for T min / T max thresholds is a domain violation (architect-level rule, see channels.yaml).
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/top-watch-bar.md:79:8. **UPPERCASE category labels** with letter-spacing. «ДАВЛЕНИЕ», «НАГРЕВАТЕЛЬ». (RULE-TYPO-005, RULE-TYPO-008)
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/top-watch-bar.md:105:│   1.23e-06 мбар      │     uppercase, letter-spacing 0.05em
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/top-watch-bar.md:146:    def set_pressure(self, mbar: float, status: str = "ok") -> None: ...  # parameter name stays Latin
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/top-watch-bar.md:181:        self._tmin = VitalCell("Т МИН")
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/top-watch-bar.md:182:        self._tmax = VitalCell("Т МАКС")
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/top-watch-bar.md:183:        self._heater = VitalCell("НАГРЕВАТЕЛЬ")
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/top-watch-bar.md:218:        # DESIGN: RULE-TYPO-003 (tnum), RULE-TYPO-007 (15px off-scale protected)
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/top-watch-bar.md:328:**Why badge is critical:** the very same UI affords both real and debug operations. Operator error risk: pressing «АВАР. ОТКЛ.» thinking they're in Debug when actually in Experiment (or vice versa). Persistent visible badge reduces this risk.
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/top-watch-bar.md:342:1. **Using Т1 or Т7 for T-min / T-max thresholds.** These channels may be relocated between experiments (operator-moveable placement). Т11 / Т12 are the only physically fixed reference channels. Hardcoded channel IDs for T-min / T-max in TopWatchBar backend.
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/top-watch-bar.md:358:9. **Latin T for channel labels.** "T MIN" with Latin T; should be "Т МИН" with Cyrillic. RULE-COPY-001.
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/top-watch-bar.md:370:- 2026-04-17: Initial version. Documents B.4 / B.4.5.2 implementation. 4 fixed vitals (Pressure / T min / T max / Heater) + mode badge. T-min / T-max locked to Т11 / Т12 — positionally fixed reference channels on the second stage (nitrogen plate), not relocatable without dismantling the rheostat. Mode badge distinguishes Experiment from Debug.
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/top-watch-bar.md:371:- 2026-04-17 (v1.0.1): Fixed `mбар` → `мбар` in pressure invariant (FR-016) — was a typo mixing Latin `m` with Cyrillic `бар`. Code identifier `mbar:` in `set_pressure` API stays Latin (parameter name).
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/accessibility-rules.md:210:text = QLabel("Т11 вышел за уставку, срабатывание блокировки")
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/accessibility-rules.md:222:fault_label = QLabel("Т11 вышел за уставку, срабатывание блокировки")
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/accessibility-rules.md:338:**Related rules:** RULE-TYPO-006 (minimum weight), RULE-TYPO-007 (off-scale sizes), RULE-A11Y-003 (contrast)
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/accessibility-rules.md:506:- 2026-04-17 (v1.0.1): Replaced screen-reader scope-out language with positive AD-003 commitment. CryoDAQ provides basic SR support (accessibleName / accessibleDescription / throttled QAccessible events / immediate fault announcements); only full SR narration of chart data points remains out of scope.
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/sensor-cell.md:13:Smallest atom of the sensor grid. Displays one channel: channel ID (Cyrillic Т#) + current value + unit + state-aware color. Appears in grids of many at once (DynamicSensorGrid with 24 channels, typical 14 visible).
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/sensor-cell.md:30:│  Т11                  │ ◀── channel ID (Cyrillic Т)
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/sensor-cell.md:34:│  Теплообменник 1      │     tnum, color varies by status
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/sensor-cell.md:49:| **Channel ID** | Yes | «Т1», «Т11», «Т24» — Cyrillic letter always |
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/sensor-cell.md:50:| **Value + unit** | Yes | «4.21 K», «1.23e-06 мбар», «0.125 Вт» |
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/sensor-cell.md:51:| **Friendly name** | Optional | Second-line descriptor from channels.yaml (e.g. «Теплообменник 1») |
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/sensor-cell.md:56:1. **Channel ID uses Cyrillic Т (U+0422).** Never Latin T. (RULE-COPY-001)
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/sensor-cell.md:57:2. **Value format fixed per unit.** Temperature `{:.2f} K`, pressure `{:.2e} мбар`, voltage `{:.3f} В`. (RULE-DATA-004, RULE-COPY-006)
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/sensor-cell.md:62:7. **Positionally fixed reference channels matter.** Т11 / Т12 are the only channels with guaranteed fixed physical location — mounted on the second stage (nitrogen plate), cannot be relocated without dismantling the rheostat. All temperature channels are metrologically calibrated, but other channels may change position between experiments, which disqualifies them as fixed reference points for quantitative thresholds. SensorCell itself does not enforce consumer policy — but consumers (TopWatchBar T-min / T-max, alarm thresholds) must prefer Т11 / Т12 for cross-experiment quantitative comparisons. Document in tooltip.
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/sensor-cell.md:91:    channel_id: str        # "Т11" (Cyrillic)
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/sensor-cell.md:92:    friendly_name: str     # "Теплообменник 1"
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/sensor-cell.md:94:    unit: str              # "K", "мбар", "Вт", "В", "А"
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/sensor-cell.md:141:        # DESIGN: RULE-COPY-001 — Cyrillic Т
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/sensor-cell.md:150:        # DESIGN: RULE-TYPO-003 tnum, RULE-TYPO-007 off-scale 15px protected
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/sensor-cell.md:180:        elif r.unit == "мбар":
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/sensor-cell.md:181:            return f"{r.value:.2e} мбар"
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/sensor-cell.md:240:            f"Тип: {'Холодный' if r.is_cold else 'Тёплый'}",
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/sensor-cell.md:242:        if r.channel_id in ("Т11", "Т12"):
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/sensor-cell.md:277:  `ChannelManager.get_all_visible()` whose id starts with Cyrillic Т
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/sensor-cell.md:316:1. **Latin T in channel ID.** `QLabel("T11")` with Latin T. Should be Cyrillic `"Т11"`. RULE-COPY-001.
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/sensor-cell.md:324:5. **Alarm firing on relocatable channel for fixed-threshold decisions.** Quantitative cross-experiment alarm on Т5 (a relocatable channel). Threshold that's meaningful in one experiment layout may be meaningless in the next if the sensor moved. Safety rule at safety engine level; display-level cue: SensorCell tooltip should mark Т11 / Т12 as «Неподвижный опорный канал» so alarm panels know which cells are position-stable reference points.
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/sensor-cell.md:346:- 2026-04-17: Initial version. Documents Phase B.3 implementation (DynamicSensorGrid with width-driven dynamic column count: `cols = available_width // (MIN_CELL_WIDTH + spacing)`, `MIN_CELL_WIDTH = 160`, `CELL_HEIGHT = 80`). Cold/warm distinction via COLD_HIGHLIGHT left edge. Positionally fixed reference status surfaced in tooltip for Т11 / Т12 («Неподвижный опорный канал»). Fault state uses border + icon + color redundancy. Hover / keyboard-focus / pressed interaction states added to the visual state matrix (FR-021).
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/typography-rules.md:22:- RULE-TYPO-005 — Cyrillic uppercase requires positive letter-spacing
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/typography-rules.md:24:- RULE-TYPO-007 — Off-scale sizes (15, 32) protected from normalization
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/typography-rules.md:261:## RULE-TYPO-005: Cyrillic uppercase requires positive letter-spacing
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/typography-rules.md:263:**TL;DR:** UPPERCASE Cyrillic labels ("АВАР. ОТКЛ.", "ЭКСПЕРИМЕНТ") need `letter-spacing: 0.05em` because default Cyrillic uppercase tracks narrower than Latin. Without this, letters visually cram together.
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/typography-rules.md:265:**Statement:** When rendering Russian uppercase labels at any size, widget font MUST apply positive letter-spacing. Fira Sans (and most fonts) are optimized for Latin uppercase tracking; Cyrillic uppercase glyphs are on average 5-10% narrower, causing visual cramping when tracked at zero.
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/typography-rules.md:269:**Rationale:** Typography is tuned for Latin. Cyrillic has denser glyph structure. Without explicit tracking, an uppercase label like "АВАР. ОТКЛ." renders as "АВАРОТКЛ"-like visual blob. Latin equivalent "EMERG. STOP." looks fine at same tracking due to wider Latin letterforms.
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/typography-rules.md:271:**Applies to:** any widget displaying uppercase Cyrillic text at any size, especially headers, buttons, status labels
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/typography-rules.md:277:# Destructive button with Cyrillic uppercase label
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/typography-rules.md:284:emergency_button = QPushButton("АВАР. ОТКЛ.")
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/typography-rules.md:300:button.setText("АВАР. ОТКЛ.")
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/typography-rules.md:306:# No letter-spacing — Cyrillic uppercase cramps
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/typography-rules.md:309:button = QPushButton("АВАР. ОТКЛ.")
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/typography-rules.md:311:# Visual result: "АВАР.ОТКЛ." appears cramped, period almost touches "О"
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/typography-rules.md:314:**Exception:** Lowercase or title-case Cyrillic (e.g., "Эксперимент", "Захолаживание") does NOT need explicit letter-spacing. Default tracking is optimized for mixed-case Cyrillic. Rule applies only to UPPERCASE.
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/typography-rules.md:374:## RULE-TYPO-007: Off-scale sizes protected from normalization
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/typography-rules.md:399:# DESIGN: RULE-TYPO-007
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/typography-rules.md:429:**Statement:** UPPERCASE Cyrillic usage in CryoDAQ UI follows this convention:
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/typography-rules.md:432:- Tile titles in BentoGrid: "ДАВЛЕНИЕ", "ТЕМПЕРАТУРА", "АНАЛИТИКА" (compact header labels)
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/typography-rules.md:434:- Destructive action buttons: "АВАР. ОТКЛ."
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/typography-rules.md:438:- Body prose: "ЭКСПЕРИМЕНТ НАЧАТ В 14:32" → use "Эксперимент начат в 14:32"
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/typography-rules.md:439:- Tooltips: "НАЖМИТЕ ДЛЯ ОТКРЫТИЯ" → use "Нажмите для открытия"
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/typography-rules.md:440:- Alert messages: "ТЕМПЕРАТУРА ВЫШЕ ПРЕДЕЛА" → use "Температура выше предела"
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/typography-rules.md:441:- Button labels with action phrasing: "СОХРАНИТЬ ЭКСПЕРИМЕНТ" → use "Сохранить эксперимент"
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/typography-rules.md:475:status_label = QLabel("ЭКСПЕРИМЕНТ ПЕРЕВЕДЁН В ФАЗУ ЗАХОЛАЖИВАНИЯ")
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/typography-rules.md:479:button.setToolTip("НАЖМИТЕ ДЛЯ НАЧАЛА ЭКСПЕРИМЕНТА")  # WRONG
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/typography-rules.md:483:**Related rules:** RULE-TYPO-005 (Cyrillic uppercase letter-spacing), RULE-COPY-003 (Russian UI text style)
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/typography-rules.md:596:- 2026-04-17: Initial version. 10 rules covering preset preference, font loading, tnum/liga features, Cyrillic typography, weight minimums, off-scale size protection, uppercase convention, line-height ratios, text color pairing.
/Users/vladimir/Projects/cryodaq/docs/design-system/governance/versioning.md:29:- Tagged in git as `design-system-vX.Y.Z` (e.g., `design-system-v1.0.1`)
/Users/vladimir/Projects/cryodaq/docs/design-system/governance/versioning.md:251:- 2026-04-17 (v1.0.1): Created the `VERSION` and `CHANGELOG.md` artifacts that this document was referencing but which did not previously exist (FR-013). No process changes — the described release process is now actually wired up.
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/surface-rules.md:305:tile = ExecutiveKpiTile(label="Давление", value="1.23e-06 мбар")
/Users/vladimir/Projects/cryodaq/docs/design-system/governance/token-naming.md:135:FONT_DISPLAY_SIZE = 32       # off-scale protected per RULE-TYPO-007
/Users/vladimir/Projects/cryodaq/docs/design-system/governance/token-naming.md:136:FONT_MONO_VALUE_SIZE = 15    # off-scale protected per RULE-TYPO-007
/Users/vladimir/Projects/cryodaq/docs/design-system/governance/token-naming.md:175:Current registered prefixes — every token in `theme.py` belongs to one. Counts reflect the shipped state of `src/cryodaq/gui/theme.py` as of v1.0.1 (verify via the audit script in `governance/testing-strategy.md`).
/Users/vladimir/Projects/cryodaq/docs/design-system/governance/token-naming.md:370:Per RULE-COLOR-010. Violation caught by `governance/testing-strategy.md` lint.
/Users/vladimir/Projects/cryodaq/docs/design-system/governance/token-naming.md:390:- **RULE-COLOR-010** — tokens referenced through theme module, not hardcoded
/Users/vladimir/Projects/cryodaq/docs/design-system/governance/token-naming.md:422:- 2026-04-17 (v1.0.1): Rebuilt prefix registry from actual `theme.py` reality (FR-012). Added `SURFACE_`, `TEXT_`, `TRANSITION_`, `QUANTITY_`, `QDARKTHEME_`, `ACCENT_`, `BORDER_`, `CARD_`, `MUTED_`, `SUCCESS_`, `WARNING_`, `DANGER_` prefixes that were previously undocumented. Corrected spacing scale to `SPACE_0`…`SPACE_6` (7 steps shipped, not 9). Moved `OVERLAY_` and `ICON_SIZE_` to the proposed-prefixes table — neither is in theme.py yet. Updated STONE_* count to actual 13 aliases.
/Users/vladimir/Projects/cryodaq/docs/design-system/governance/deprecation-policy.md:234:- **Cyrillic Т (U+0422)** for channel IDs — domain vocabulary, not a design decision

exec
/opt/homebrew/bin/bash -lc "rg -n \"LakeShore|LS218|Keithley|Thyracont|VSP|GPIB|USB0|COM3|poll_interval|Т4|ModemManager|validate_checksum|tsp|p_const|interlock|Т\\(1\\|2\\|3\\|5\\|6\\|7\\|8\\)|Т\\[1-8\\]\" /Users/vladimir/Projects/cryodaq/CLAUDE.md /Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md /Users/vladimir/Projects/cryodaq/CHANGELOG.md /Users/vladimir/Projects/cryodaq/config/instruments.yaml /Users/vladimir/Projects/cryodaq/config/interlocks.yaml -S" in /Users/vladimir/Projects/cryodaq
exec
/opt/homebrew/bin/bash -lc 'rg -n "three independent processes|ZeroMQ|cryodaq-engine|cryodaq-gui|FastAPI|No PySide6|No blocking|numpy|MainWindowV2|Phase II.13|legacy|themes|ConfigError|exit code 2|single asyncio|SafetyManager|log_get" /Users/vladimir/Projects/cryodaq/CLAUDE.md /Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md /Users/vladimir/Projects/cryodaq/README.md /Users/vladimir/Projects/cryodaq/CHANGELOG.md -S' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:7:**Фронтир:** Phase II.2 ArchiveOverlay (`e4a60f3`) и II.3 OperatorLog (`9676acc`) закрыты вслед за II.6 Keithley (`96adf5a`); следующий блок — II.5 ConductivityOverlay.
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:33:| LakeShore 218S (x3) | GPIB | 24 температурных | `lakeshore_218s.py` |
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:34:| Keithley 2604B | USB-TMC | smua + smub | `keithley_2604b.py` |
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:35:| Thyracont VSP63D | RS-232 | 1 давление | `thyracont_vsp63d.py` |
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:44:6. **Keithley connect** forces OUTPUT_OFF на обоих SMU (best-effort).
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:45:7. **Keithley disconnect** вызывает `emergency_off()` первым.
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:53:12. **Fail-closed config:** `safety.yaml`, `alarms_v3.yaml`, `interlocks.yaml`, `housekeeping.yaml`, `channels.yaml` → subsystem-specific `ConfigError` → engine exit code 2 (без auto-restart).
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:71:- **Engine** (headless asyncio): drivers, scheduler, persistence, safety, alarms, interlocks, plugins
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:97:**A1 safety audit (`eb267c4`, 2026-04-17).** Latin Т12 исправлен в `config/interlocks.yaml` (description + два поясняющих комментария; сам `channel_pattern` был исправлен ранее в `9feaf3e`). `_fault()` получил early-return guard против concurrent re-entries. XSS в `web/server.py`, fail-closed в `load_config()`, stuck RUN_PERMITTED — всё уже закрыто, отмечено NOT REPRODUCIBLE.
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:109:- **B.7 Keithley v2** (`920aa97`) — mode-based dual-channel overlay at `shell/overlays/keithley_panel.py`. Functional regression vs v1 (no V/I/R/P plots — v2 has 0 pyqtgraph refs, v1 had 4 — no P-target control, no A+B actions, no debounced spin controls, no K4 custom-command popup). Documented in `docs/legacy-inventory/keithley.md`. Maps to II.6 PARTIAL; scope to be reopened as a second block.
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:122:| II.6 KeithleyOverlay | ✅ COMPLETE (`96adf5a` — power-control rewrite + host integration) |
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:175:- ✅ II.6 KeithleyOverlay COMPLETE (`96adf5a`, power-control rewrite + host wiring)
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:229:1. **Dual-channel Keithley (`smua` + `smub`)** — confirmed operational model.
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:231:3. **Fail-closed config** — все 5 safety-adjacent configs (safety, alarm, interlock, housekeeping, channels) предотвращают запуск движка при missing / malformed файлах.
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:266:2. **Codex second-opinion** — независимый LLM-review committed diff. Ловит line-level семантику (wrong type, wrong API, wrong filter). Примеры Phase 2d: RUN_PERMITTED heartbeat gap (gated on `_active_sources` которая пустая в момент source start); `housekeeping.py` читает `alarms_v3.yaml:interlocks:` секцию, которую CC удалил как "dead config"; NaN vs ±inf IEEE 754 distinction (SQLite treats NaN as NULL).
/Users/vladimir/Projects/cryodaq/CLAUDE.md:42:- Dual-channel Keithley (`smua`, `smub`, `smua + smub`) остаётся актуальной моделью. Старые ожидания про disable/hide/remove `smub` устарели.
/Users/vladimir/Projects/cryodaq/CLAUDE.md:81:Local configs are gitignored and intended for machine-specific deployment data such as COM ports, GPIB addresses, and notification credentials.
/Users/vladimir/Projects/cryodaq/CLAUDE.md:111:     Safety regulation is host-side only (no Keithley TSP watchdog yet —
/Users/vladimir/Projects/cryodaq/CLAUDE.md:113:     Crash-recovery guard: Keithley2604B.connect() forces OUTPUT_OFF on
/Users/vladimir/Projects/cryodaq/CLAUDE.md:183:- `src/cryodaq/core/interlock.py` — threshold detection, delegates actions to SafetyManager
/Users/vladimir/Projects/cryodaq/CLAUDE.md:191:- `src/cryodaq/core/smu_channel.py` — SmuChannel enum + normalize helper for Keithley channel IDs
/Users/vladimir/Projects/cryodaq/CLAUDE.md:210:- `src/cryodaq/drivers/instruments/keithley_2604b.py` — Keithley 2604B dual-SMU (host-side P=const)
/Users/vladimir/Projects/cryodaq/CLAUDE.md:211:- `src/cryodaq/drivers/instruments/lakeshore_218s.py` — LakeShore 218S 8-channel thermometer
/Users/vladimir/Projects/cryodaq/CLAUDE.md:212:- `src/cryodaq/drivers/instruments/thyracont_vsp63d.py` — Thyracont VSP63D vacuum gauge (MV00 + V1)
/Users/vladimir/Projects/cryodaq/CLAUDE.md:213:- `src/cryodaq/drivers/transport/gpib.py` — async GPIB transport via PyVISA
/Users/vladimir/Projects/cryodaq/CLAUDE.md:318:- `tsp/p_const.lua` — draft TSP supervisor for Phase 3 hardware watchdog
/Users/vladimir/Projects/cryodaq/CLAUDE.md:324:- `config/interlocks.yaml`
/Users/vladimir/Projects/cryodaq/CLAUDE.md:339:- LakeShore 218S
/Users/vladimir/Projects/cryodaq/CLAUDE.md:340:- Keithley 2604B
/Users/vladimir/Projects/cryodaq/CLAUDE.md:341:- Thyracont VSP63D
/Users/vladimir/Projects/cryodaq/CLAUDE.md:347:- Keithley disconnect must call emergency off first.
/Users/vladimir/Projects/cryodaq/config/instruments.yaml:3:    name: "LS218_1"
/Users/vladimir/Projects/cryodaq/config/instruments.yaml:4:    resource: "GPIB0::12::INSTR"
/Users/vladimir/Projects/cryodaq/config/instruments.yaml:5:    poll_interval_s: 2.0
/Users/vladimir/Projects/cryodaq/config/instruments.yaml:10:      4: "Т4 Радиатор 2"
/Users/vladimir/Projects/cryodaq/config/instruments.yaml:17:    name: "LS218_2"
/Users/vladimir/Projects/cryodaq/config/instruments.yaml:18:    resource: "GPIB0::14::INSTR"
/Users/vladimir/Projects/cryodaq/config/instruments.yaml:19:    poll_interval_s: 2.0
/Users/vladimir/Projects/cryodaq/config/instruments.yaml:31:    name: "LS218_3"
/Users/vladimir/Projects/cryodaq/config/instruments.yaml:32:    resource: "GPIB0::16::INSTR"
/Users/vladimir/Projects/cryodaq/config/instruments.yaml:33:    poll_interval_s: 2.0
/Users/vladimir/Projects/cryodaq/config/instruments.yaml:45:    name: "Keithley_1"
/Users/vladimir/Projects/cryodaq/config/instruments.yaml:46:    resource: "USB0::0x05E6::0x2604::04052028::INSTR"
/Users/vladimir/Projects/cryodaq/config/instruments.yaml:47:    poll_interval_s: 1.0
/Users/vladimir/Projects/cryodaq/config/instruments.yaml:50:    name: "VSP63D_1"
/Users/vladimir/Projects/cryodaq/config/instruments.yaml:51:    resource: "COM3"
/Users/vladimir/Projects/cryodaq/config/instruments.yaml:53:    poll_interval_s: 2.0
/Users/vladimir/Projects/cryodaq/config/interlocks.yaml:15:interlocks:
/Users/vladimir/Projects/cryodaq/config/interlocks.yaml:20:    channel_pattern: "Т[1-8] .*"
/Users/vladimir/Projects/cryodaq/config/interlocks.yaml:37:  # обеспечивается Alarm Engine v2 (detector_warmup_interlock в alarms_v3.yaml).
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:20:- `aabd75f` — `engine: wire validate_checksum through Thyracont
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:22:  PC when VSP206 hardware is connected. `_create_instruments()`
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:25:  config-side `validate_checksum: false` in
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:30:  real Keithley 2604B is connected (VISA resource contains `\x00`
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:53:  - `interlocks.yaml` — `overheat_cryostat` regex tightened from
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:54:    `Т[1-8] .*` to `Т(1|2|3|5|6|7|8) .*`. Т4 sensor is physically
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:56:    `emergency_off` on Keithley during normal operation.
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:57:  - `alarms_v3.yaml` — Т4 added to `uncalibrated` and `all_temp`
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:60:  - `instruments.local.yaml` — `validate_checksum: false` on
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:61:    Thyracont block (per-machine override; NOT in git).
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:63:- Operational on Ubuntu lab PC: `ModemManager` disabled
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:64:  (was transiently grabbing `/dev/ttyUSB0`).
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:81:- Thyracont `_try_v1_probe` probe-vs-read inconsistency. Probe
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:83:  and emit NaN forever on non-VSP63D hardware. Pending
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:116:  `KeithleyPowerWidget`, plus 4 placeholder cards for the widget IDs
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:337:  `min_wait` gate, Keithley power stepping via `ZmqCommandWorker`
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:400:- **Phase II.6 Keithley overlay rebuilt.** Replaces the dead B.7
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:740:  `"LS218_1:Т1 Криостат верх"` format from combobox. Pre-Tier-1
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:844:- **Fail-closed завершён** — `interlocks.yaml`, `housekeeping.yaml`,
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:982:- **Keithley spinbox** — debounce + non-blocking live update.
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:991:## [0.26.0] — 23-03-26 — GPIB-восстановление и preflight
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:998:- **GPIB auto-recovery** — очистка шины по timeout, preventive clear.
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:999:- **GPIB escalating recovery** — IFC bus reset, enable unaddressing.
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1066:- **Вкладка Keithley** — переименована, добавлены кнопки time window
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1077:- **Thyracont MV00 fallback** + SQLite read/write split + SafetyManager
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1078:  transition + Keithley disconnect.
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1096:- **Phase 2 safety** — тесты + bugfixes + LakeShore `RDGST?`.
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1104:  phase reset, GPIB leak, deque cap.
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1112:## [0.21.0] — 20-03-26 — Аналитика и безопасность Keithley
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1120:- **Keithley safety** — slew rate limit, compliance detection +
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1134:## [0.20.0] — 19-03-26 — GPIB-стабилизация и ZMQ-изоляция
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1142:- **GPIB bus lock** — расширен scope: покрытие `open_resource()` и
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1144:- **GPIB стратегии** — последовательно опробованы open-per-query,
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1161:и исправляется ими. Широкий sweep аппаратных проблем: GPIB, Thyracont,
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1162:Keithley, алармы, давление.
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1166:- **GPIB bus lock** — покрытие `open_resource()` и `close()`, а не
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1168:- **Keithley source-off** — NaN при выключенном источнике приводил к
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1170:- **Thyracont VSP63D** — протокол V1 вместо SCPI `*IDN?`; формула
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1178:- **Keithley P=const** — перенесён с TSP/Lua на host-side control loop
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1180:- **Keithley live update** — `P_target` обновляется на лету + исправлена
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1229:- **`interlocks.yaml`** — удалён `undercool_shield` (ложное срабатывание
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1282:- **EventLogger** — автоматическая запись: Keithley start/stop/e-off,
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1329:  Ctrl+1..9/0 (вкладки), Ctrl+Shift+X (аварийное отключение Keithley),
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1350:Dashboard hub с quick-actions для Keithley, quick log, experiment
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1355:- **Dashboard hub** — Keithley quick-actions, quick log, experiment
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1493:## [0.5.0] — 14-03-26 — Launcher и двухканальный Keithley
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1495:Operator launcher, dual-channel Keithley, workflow теплопроводности,
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1502:- **Dual-channel Keithley** — backend, driver и GUI поддерживают `smua`,
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1516:Thyracont VSP63D (третий прибор), все вкладки GUI активны,
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1521:- **Thyracont VSP63D driver** — RS-232, протокол MV00, вакуумметр.
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1529:  token. Удалён `__del__` из Keithley driver. `asyncio.create_task()`
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1563:LakeShore 218S и Keithley 2604B drivers, первые alarm и analytics
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1568:- **LakeShore 218S driver** — GPIB, SCPI, `KRDG?` без аргумента
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1570:- **Keithley 2604B driver** — USB-TMC, TSP/Lua supervisor (`p_const.lua`),
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1581:- **Вкладка Keithley** — smua/smub: V/I/R/P графики + управление.
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1583:- `config/interlocks.yaml`, `config/alarms.yaml`,

 succeeded in 0ms:
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:48:  Committed anyway as architectural improvement matching ZeroMQ
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:120:  `MainWindowV2._on_experiment_status_received`. Public setters
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:130:  the legacy status tier in non-status contexts. Tests: 37 new
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:185:  All 9 other themes' ACCENT verified hue-distant from STATUS_OK
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:187:  all 12 themes side-by-side for architect visual review. ADR 002
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:193:- **Phase II.13 legacy cleanup.** All DEPRECATED-marked Phase I-era
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:207:  - `src/cryodaq/gui/main_window.py` (v1 tab-based main window; `cryodaq-gui` entry point was already on `MainWindowV2` via `gui/app.py` since Phase I.1).
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:208:  Removed test files: 7 legacy widget-specific tests (archive,
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:228:  wiring: `MainWindowV2._tick_status` mirrors connection state;
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:239:  Merged two legacy modules (`instrument_status.py` +
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:253:  Integration Contract wired: `MainWindowV2._tick_status` connection
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:257:  for Phase II.13. Tests: 41 overlay cases + 7 host-wiring cases.
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:261:  the legacy v1 widget in `MainWindowV2`. Dual-engine layout preserved:
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:270:  Host Integration Contract wired: `MainWindowV2._tick_status` mirrors
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:279:  its module docstring; slated for deletion in Phase II.13. Zero legacy
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:286:  legacy v1 widget. QStackedWidget (Setup / Acquisition / Results)
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:304:  `MainWindowV2._tick_status` connection mirror +
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:308:  legacy tokens / zero emoji / zero hardcoded hex (pre-commit gates
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:315:- **Six new themes: signal, instrument, amber (dark); gost, xcode,
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:334:  legacy v1 widget. Auto-sweep state machine preserved verbatim
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:348:  legacy tokens, zero emoji, zero hardcoded hex colors (plot pens come
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:350:  Integration Contract wired: `MainWindowV2._tick_status` connection
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:361:  `src/cryodaq/gui/shell/overlays/archive_panel.py` replaces the legacy
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:367:  Excel export migrated from the legacy `main_window.py` File menu
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:369:  — `MainWindowV2` has no menu bar, so this was the only path to
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:373:  Emoji pictograms `📊` / `📋` in the legacy artifact view replaced
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:377:  Integration Contract wired via `MainWindowV2._tick_status` connection
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:382:  export actions remain intact for the transitional legacy path.
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:386:  replaces the legacy v1 widget. Timeline grouped by calendar day,
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:393:  integration contract: `MainWindowV2._tick_status()` mirrors
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:401:  mode-based shell overlay (never wired into `MainWindowV2`) and
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:402:  supersedes the legacy v1 widget surface visible via Ctrl+K. Full
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:413:  banner. Design System v1.0.1 compliant — legacy `TEXT_PRIMARY` /
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:419:  MainWindowV2 now imports the overlay from
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:431:  `config/themes/<selected>.yaml` via `src/cryodaq/gui/_theme_loader.py`.
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:461:  spacing, layout, radius, motion, plot palette, legacy STONE_* unique
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:465:- **Status palette — one-time semantic refresh (LOCKED across all themes).**
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:473:  by `tests/gui/test_theme_loader.py::test_status_palette_identical_across_all_themes`.
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:508:  template, name auto-suggest, full legacy payload (template_id, sample,
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:514:  ⋯ menu с Прервать. Finalize saves card fields first (legacy parity).
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:528:  Legacy ExperimentWorkspace removed from MainWindowV2.
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:536:  wired font loading only in `cryodaq-gui` entry (`gui/app.py:main`).
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:537:  The `cryodaq` launcher creates QApplication + MainWindowV2 directly
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:601:  данные через TopWatchBar → MainWindowV2 → DashboardView forwarding.
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:661:- **Phase UI-1 v2 shell (блоки A через A.9).** Новый `MainWindowV2`
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:663:  `BottomStatusBar` и `OverlayContainer` заменяют tab-based legacy
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:694:  (195), `SafetyManager` (156). Injected в Claude Code sessions via
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:732:- **Launcher и `gui/app.py`.** Entry point `cryodaq-gui` routes to
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:733:  `MainWindowV2` as primary shell. Legacy `MainWindow` и tab panels
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:781:  и tab panels remain active alongside `MainWindowV2` until Block B.7.
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:845:  `channels.yaml` теперь вызывают `InterlockConfigError` /
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:846:  `HousekeepingConfigError` / `ChannelConfigError` при отсутствии
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:847:  или повреждении. Engine exit code 2.
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:871:- **SafetyConfigError / AlarmConfigError** — typed exception hierarchy
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:928:- **SafetyManager deep dive** — исчерпывающий FSM-анализ (1 062 строки).
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1077:- **Thyracont MV00 fallback** + SQLite read/write split + SafetyManager
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1244:  FastAPI + self-contained HTML, `/api/status`, `/api/log`, `/ws`.
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1315:- Удалён legacy `CalibrationSessionStore` и ручной workflow.
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1469:## [0.6.0] — 14-03-26 — SafetyManager и безопасность данных
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1475:- **SafetyManager** — 6-state FSM: SAFE_OFF → READY → RUN_PERMITTED →
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1546:- **Engine + GUI entry points** — `cryodaq-engine`, `cryodaq-gui`
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1555:- **Web dashboard** — FastAPI + WebSocket + Chart.js, тёмная тема.
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1593:engine и PySide6 GUI, связанными через ZeroMQ. Первый скелет сбора
/Users/vladimir/Projects/cryodaq/CLAUDE.md:54:#  base dep. The legacy `archive` extra is retained as a no-op alias
/Users/vladimir/Projects/cryodaq/CLAUDE.md:57:cryodaq-engine                 # Run engine headless (real instruments)
/Users/vladimir/Projects/cryodaq/CLAUDE.md:58:cryodaq-engine --mock          # Run engine with simulated data
/Users/vladimir/Projects/cryodaq/CLAUDE.md:59:cryodaq-gui                    # Run GUI only (connects to engine over ZMQ)
/Users/vladimir/Projects/cryodaq/CLAUDE.md:89:- `cryodaq-engine` — headless asyncio runtime: acquisition, safety, storage, commands
/Users/vladimir/Projects/cryodaq/CLAUDE.md:90:- `cryodaq-gui` или `cryodaq` — desktop operator client / launcher
/Users/vladimir/Projects/cryodaq/CLAUDE.md:91:- web dashboard — optional FastAPI monitoring surface
/Users/vladimir/Projects/cryodaq/CLAUDE.md:95:SafetyManager is the single authority for source on/off decisions.
/Users/vladimir/Projects/cryodaq/CLAUDE.md:100:  -> SafetyManager
/Users/vladimir/Projects/cryodaq/CLAUDE.md:183:- `src/cryodaq/core/interlock.py` — threshold detection, delegates actions to SafetyManager
/Users/vladimir/Projects/cryodaq/CLAUDE.md:190:- `src/cryodaq/core/sensor_diagnostics.py` — noise/drift/correlation health scoring (numpy exception)
/Users/vladimir/Projects/cryodaq/CLAUDE.md:227:- `src/cryodaq/gui/shell/main_window_v2.py` — v2 shell: TopWatchBar + ToolRail + BottomStatusBar + main content area; canonical mnemonic shortcuts (`Ctrl+L/E/A/K/M/R/C/D`, `F5`, `Ctrl+Shift+X`) per AD-002 — sole owner of shortcut bindings after the v1 `gui/main_window.py` was retired in Phase II.13
/Users/vladimir/Projects/cryodaq/CLAUDE.md:265:Remaining widget modules after Phase II.13 legacy cleanup. All
/Users/vladimir/Projects/cryodaq/CLAUDE.md:271:`cryodaq-gui` entry point has used `MainWindowV2` via `gui/app.py` since
/Users/vladimir/Projects/cryodaq/CLAUDE.md:279:- `src/cryodaq/gui/widgets/experiment_dialogs.py` — диалоги старта/завершения эксперимента (legacy)
/Users/vladimir/Projects/cryodaq/CLAUDE.md:348:- No blocking I/O on the engine event loop (known exception: `reporting/generator.py` uses sync `subprocess.run()` for LibreOffice PDF conversion — DEEP_AUDIT finding E.2).
/Users/vladimir/Projects/cryodaq/CLAUDE.md:350:- No numpy/scipy в drivers/core (исключение: core/sensor_diagnostics.py — MAD/корреляция).
/Users/vladimir/Projects/cryodaq/CLAUDE.md:372:- **Full `pytest -q` suite** (~10-15 min on Mac) runs ONLY on initial block commits where the diff is large: new overlay file (~1000 LOC), new test file, multiple `MainWindowV2` wiring changes. This is the commit that gets pushed first and reviewed by Codex.
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:46:8. **No blocking I/O** на engine event loop (исключение: `reporting/generator.py` sync `subprocess.run` для LibreOffice).
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:47:9. **No numpy/scipy** в `drivers/core` (исключение: `core/sensor_diagnostics.py` — MAD/корреляция).
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:53:12. **Fail-closed config:** `safety.yaml`, `alarms_v3.yaml`, `interlocks.yaml`, `housekeeping.yaml`, `channels.yaml` → subsystem-specific `ConfigError` → engine exit code 2 (без auto-restart).
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:67:                                       → SafetyBroker → SafetyManager
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:72:- **GUI** (PySide6): `MainWindowV2` shell + dashboard (Phase I.1 / Phase UI-1 v2 через Block B.2) + legacy v1 widgets (в ожидании Block B.7 миграции)
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:73:- **Web** (FastAPI, опционально): monitoring dashboard на `:8080`
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:74:- **IPC:** ZeroMQ PUB/SUB `:5555` (data, msgpack) + REP/REQ `:5556` (commands, JSON)
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:93:**Phase I.1 shell primitives.** Новый shell `MainWindowV2` (TopWatchBar + ToolRail + BottomStatusBar + overlay container), overlay DS primitives (ModalCard, BentoGrid, DrillDownBreadcrumb). Shell замещает tab-based `MainWindow`; v1 widgets продолжают работу под легаси-ключом до Block B.7.
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:95:**CLAUDE.md module index rebuild (`8840922`, 2026-04-17).** Полная инвентаризация GUI под Phase I.1: Shell / Overlays / Dashboard / Theming+IPC / Legacy sub-groups; добавлены 20+ ранее неучтённых модулей; canonical mnemonic scheme per AD-002 (`Ctrl+L/E/A/K/M/R/C/D`) задокументирована на `main_window_v2`; legacy `main_window.py` хранит transitional `Ctrl+1-9`.
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:101:**CI dependency fix (`1e824a7`).** `.github/workflows/main.yml` теперь ставит `.[dev,web]`, чтобы FastAPI / starlette / httpx тесты не скипались.
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:109:- **B.7 Keithley v2** (`920aa97`) — mode-based dual-channel overlay at `shell/overlays/keithley_panel.py`. Functional regression vs v1 (no V/I/R/P plots — v2 has 0 pyqtgraph refs, v1 had 4 — no P-target control, no A+B actions, no debounced spin controls, no K4 custom-command popup). Documented in `docs/legacy-inventory/keithley.md`. Maps to II.6 PARTIAL; scope to be reopened as a second block.
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:131:Infrastructure landing outside the original roadmap. Six bundled YAML theme packs at `config/themes/`: `default_cool`, `warm_stone`, `anthropic_mono`, `ochre_bloom`, `taupe_quiet`, `rose_dusk`. Runtime theme loader at `src/cryodaq/gui/_theme_loader.py` — `theme.py` now reads tokens from YAML packs. Settings → Тема menu with `os.execv` restart pattern. Status palette (STATUS_OK, WARNING, CAUTION, FAULT, INFO, STALE, COLD_HIGHLIGHT) locked across all packs. Legacy hardcoded theme overrides stripped from 9 `apply_panel_frame` callsites.
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:148:4. `log_get` routed to a dedicated read executor (long reads don't block REP).
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:151:7. Per-handler 2.0s timeout envelope. `log_get` and `experiment_status` get 1.5s inner wrappers for faster client feedback.
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:183:Codex FAIL on II.6 surfaced a systemic risk: overlays with public push setters (`set_connected`, `set_current_experiment`, `set_safety_ready`, etc.) are useless if `MainWindowV2` never calls them — the overlay opens in defaults and stays there. Unit tests on the overlay alone pass while production is broken.
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:191:**Tests:** overlay unit tests AND host integration tests (`tests/gui/shell/test_main_window_v2_<block>_wiring.py`) that exercise `MainWindowV2` entry points end-to-end — firing the signal / setting the cache / calling `_ensure_overlay` and asserting overlay state.
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:241:13. **Mnemonic shortcuts canonical per AD-002** — `Ctrl+L/E/A/K/M/R/C/D` для глобальной навигации. `Ctrl+1-9` transitional (rail slot numbering), уходят вместе с legacy `main_window.py`.
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:250:cryodaq-engine --mock          # mock engine
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:251:cryodaq-gui                    # GUI only (нуждается в engine на ZMQ)
/Users/vladimir/Projects/cryodaq/README.md:15:- `cryodaq-engine` — headless runtime-процесс. Он опрашивает приборы, проверяет safety/alarm/interlock-логику, пишет данные и обслуживает GUI-команды.
/Users/vladimir/Projects/cryodaq/README.md:16:- `cryodaq-gui` — отдельный настольный клиент. Его можно перезапускать без остановки сбора данных.
/Users/vladimir/Projects/cryodaq/README.md:22:Начиная с v0.33.0 CryoDAQ использует новый `MainWindowV2` (Phase UI-1 v2)
/Users/vladimir/Projects/cryodaq/README.md:28:в режиме transition state до завершения блока B.7 (миграция всех legacy
/Users/vladimir/Projects/cryodaq/README.md:30:operator видит только `MainWindowV2`.
/Users/vladimir/Projects/cryodaq/README.md:32:### MainWindowV2 (primary, с v0.33.0)
/Users/vladimir/Projects/cryodaq/README.md:43:- `OverlayContainer` — host для legacy tab panels через overlay mechanism
/Users/vladimir/Projects/cryodaq/README.md:133:cryodaq-engine
/Users/vladimir/Projects/cryodaq/README.md:134:cryodaq-gui
/Users/vladimir/Projects/cryodaq/README.md:150:cryodaq-engine --mock
/Users/vladimir/Projects/cryodaq/README.md:159:- `config/safety.yaml` — SafetyManager FSM timeouts, rate limits, drain timeout
/Users/vladimir/Projects/cryodaq/README.md:160:- `config/alarms.yaml` — legacy alarm definitions
/Users/vladimir/Projects/cryodaq/README.md:234:- `tsp/p_const_single.lua` — legacy single-channel вариант
/Users/vladimir/Projects/cryodaq/README.md:248:    shell/            # MainWindowV2, TopWatchBar, ToolRail, BottomStatusBar (v0.33.0)
/Users/vladimir/Projects/cryodaq/README.md:250:    widgets/          # legacy tab panels (active until block B.7)
/Users/vladimir/Projects/cryodaq/README.md:253:  web/                # FastAPI monitoring dashboard
/Users/vladimir/Projects/cryodaq/README.md:263:- `src/cryodaq/gui/main_window.py` — legacy 10-tab shell (fallback)

exec
/opt/homebrew/bin/bash -lc 'rg -n "persistence|write_immediate|publish_batch|WAL|synchronous|NORMAL|CRYODAQ_SQLITE_SYNC|OVERRANGE|UNDERRANGE|write.*publish|Scheduler|DataBroker|SafetyBroker|SQLiteWriter" /Users/vladimir/Projects/cryodaq/CLAUDE.md /Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md /Users/vladimir/Projects/cryodaq/src/cryodaq/core/scheduler.py /Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py -S' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
/Users/vladimir/Projects/cryodaq/CLAUDE.md:99:SafetyBroker (dedicated, overflow=FAULT)
/Users/vladimir/Projects/cryodaq/CLAUDE.md:122:  -> Scheduler
/Users/vladimir/Projects/cryodaq/CLAUDE.md:123:     1. SQLiteWriter.write_immediate()
/Users/vladimir/Projects/cryodaq/CLAUDE.md:124:     2. THEN DataBroker.publish_batch()
/Users/vladimir/Projects/cryodaq/CLAUDE.md:125:     3. THEN SafetyBroker.publish_batch()
/Users/vladimir/Projects/cryodaq/CLAUDE.md:128:Invariant: if DataBroker has a reading, it has already been written to SQLite.
/Users/vladimir/Projects/cryodaq/CLAUDE.md:175:- `src/cryodaq/core/broker.py` — DataBroker fan-out pub/sub
/Users/vladimir/Projects/cryodaq/CLAUDE.md:189:- `src/cryodaq/core/scheduler.py` — instrument polling, persistence-first ordering
/Users/vladimir/Projects/cryodaq/CLAUDE.md:289:- `src/cryodaq/storage/sqlite_writer.py` — WAL-mode SQLite, daily rotation, persistence-first
/Users/vladimir/Projects/cryodaq/CLAUDE.md:294:- `src/cryodaq/storage/replay.py` — воспроизведение исторических данных из SQLite через DataBroker
/Users/vladimir/Projects/cryodaq/CLAUDE.md:351:- Scheduler writes to SQLite before publishing to brokers.
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:40:2. **Persistence-first:** `SQLiteWriter.write_immediate()` → `DataBroker` → `SafetyBroker`.
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:51:10. **OVERRANGE/UNDERRANGE** persist с `status` (`±inf` валидные REAL в SQLite). SENSOR_ERROR/TIMEOUT (NaN) отфильтровываются.
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:55:14. **WAL mode verification:** raises `RuntimeError` если `PRAGMA journal_mode=WAL` вернул не `'wal'`.
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:57:16. **Scheduler.stop()** — graceful drain (configurable via `safety.yaml scheduler_drain_timeout_s`, default 5s) перед forced cancel.
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:66:Instruments → Scheduler → SQLiteWriter → DataBroker → ZMQ → GUI (PySide6)
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:67:                                       → SafetyBroker → SafetyManager
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:71:- **Engine** (headless asyncio): drivers, scheduler, persistence, safety, alarms, interlocks, plugins
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:216:  - C.1 — Ubuntu 22.04 SQLite version gating (WAL-reset bug на libsqlite3 < 3.51.3)
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:217:  - C.3 — `synchronous=FULL` decision с UPS deployment note
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:230:2. **Persistence-first** — SQLite WAL commit BEFORE any subscriber sees data.
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:234:6. **OVERRANGE/UNDERRANGE persist** — `±inf` в REAL SQLite. NaN-valued statuses dropped до Phase 3.
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:236:8. **WAL mode verification** — engine refuses to start, если SQLite не включает WAL.
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:267:3. **Jules architectural review** — смотрит fault path целиком через несколько commit'ов. Находит cross-cutting вещи: R1 — `_fault_log_callback` не shielded; R2 — `_fault()` ordering vulnerability (callback после publish = escape path), calibration state mutation до persistence.
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:1:"""SQLiteWriter — запись показаний в SQLite с WAL-режимом.
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:98:    """Warn if running on a SQLite version affected by the March 2026 WAL-reset bug.
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:102:    instant". CryoDAQ uses WAL with multiple concurrent connections (writer,
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:113:            "SQLite %d.%d.%d is affected by the March 2026 WAL-reset corruption "
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:114:            "bug (range 3.7.0 – 3.51.2). CryoDAQ uses WAL with multiple "
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:125:class SQLiteWriter:
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:130:        writer = SQLiteWriter(data_dir=Path("./data"))
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:153:        # Periodic explicit WAL checkpoint counter (DEEP_AUDIT_CC.md D.1).
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:165:        self._persistence_failure_callback: Callable[[str], Awaitable[None]] | None = None
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:197:        schedule the persistence-failure callback on it."""
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:200:    def set_persistence_failure_callback(self, callback: Callable[[str], Awaitable[None]]) -> None:
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:201:        """Register an async callback for persistence failures (disk full etc).
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:205:        SafetyManager.on_persistence_failure can latch a fault.
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:207:        self._persistence_failure_callback = callback
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:209:    def _signal_persistence_failure(self, reason: str) -> None:
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:210:        """Schedule persistence-failure callback on the engine event loop.
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:217:        if self._persistence_failure_callback is None or self._loop is None:
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:221:                self._persistence_failure_callback(reason),
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:225:            logger.error("Failed to schedule persistence_failure callback: %s", exc)
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:233:            # Final WAL checkpoint at rotation (DEEP_AUDIT_CC.md D.1, H.2).
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:238:                logger.warning("Final WAL checkpoint at rotation failed: %s", exc)
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:243:        # WAL with explicit checkpoint policy (DEEP_AUDIT_CC.md D.1).
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:246:        result = conn.execute("PRAGMA journal_mode=WAL;").fetchone()
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:250:                f"SQLite WAL mode could not be enabled at {db_path}. "
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:253:                f"WSL with DrvFs, or read-only mount). CryoDAQ requires WAL "
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:256:        # synchronous=NORMAL loses last ~1s on power loss but gives ~10x
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:258:        # set CRYODAQ_SQLITE_SYNC=FULL.
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:259:        sync_mode = os.environ.get("CRYODAQ_SQLITE_SYNC", "NORMAL").upper()
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:260:        if sync_mode not in ("NORMAL", "FULL"):
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:261:            sync_mode = "NORMAL"
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:262:        conn.execute(f"PRAGMA synchronous={sync_mode};")
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:305:    # OVERRANGE  → +inf (LakeShore +OVL)  — stored as REAL, no issue.
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:306:    # UNDERRANGE → -inf or finite float    — stored as REAL, no issue.
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:314:        ChannelStatus.OVERRANGE,  # +OVL → +inf (stored as REAL)
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:315:        ChannelStatus.UNDERRANGE,  # -OVL → -inf or finite (stored as REAL)
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:378:                self._signal_persistence_failure(f"disk full: {exc}")
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:380:                # write_immediate / scheduler and cause the historic tight
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:388:        # cadence). Prevents WAL file growth under concurrent reader pressure.
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:395:                logger.warning("Periodic WAL checkpoint failed: %s", exc)
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:556:    async def write_immediate(self, readings: list[Reading]) -> None:
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:557:        """Записать пакет синхронно (await до WAL commit).
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:559:        Используется Scheduler для гарантии persistence-first:
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:560:        данные попадают в DataBroker ТОЛЬКО после записи на диск.
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:568:                "CRITICAL: Ошибка write_immediate (%d записей) — данные НЕ персистированы",
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:618:        # persistence-first writes on _executor. The engine REP task awaits
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:620:        # and was previously serialised against scheduler.write_immediate()
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:625:        """Инициализировать writer без очереди (persistence-first режим).
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:628:        Запись происходит через write_immediate(), вызываемый из Scheduler.
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:632:        logger.info("SQLiteWriter запущен (immediate mode)")
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:639:            "SQLiteWriter запущен (flush=%.1fs, batch=%d)", self._flush_interval_s, self._batch_size
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py:661:        logger.info("SQLiteWriter остановлен (записано: %d)", self._total_written)
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/scheduler.py:1:"""Scheduler — планировщик опроса приборов.
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/scheduler.py:20:from cryodaq.core.broker import DataBroker
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/scheduler.py:68:class Scheduler:
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/scheduler.py:73:        scheduler = Scheduler(broker)
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/scheduler.py:84:        broker: DataBroker,
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/scheduler.py:350:        # we cannot persist (so persistence-first invariant blocks publish),
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/scheduler.py:390:                await self._sqlite_writer.write_immediate(combined)
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/scheduler.py:400:            # If write_immediate silently absorbed a disk-full error
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/scheduler.py:412:            await self._broker.publish_batch(persisted_readings)
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/scheduler.py:414:            await self._safety_broker.publish_batch(readings)
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/scheduler.py:480:            "Scheduler запущен (%d приборов, %d GPIB bus, %d standalone)",
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/scheduler.py:512:                logger.info("Scheduler: graceful drain complete")
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/scheduler.py:515:                    "Scheduler: drain timed out after %.1fs, force-cancelling",
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/scheduler.py:528:        logger.info("Scheduler остановлен")

exec
/opt/homebrew/bin/bash -lc "rg -n \"direct|REP|0\\.001|unresponsive|silently|30|90|H4|H5|291/291|cmd #10|RAPID|SPARSE|RECOVER|Ubuntu|120|80|B1|data plane\" /Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md /Users/vladimir/Projects/cryodaq/ROADMAP.md /Users/vladimir/Projects/cryodaq/CHANGELOG.md -S" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:16:release is `0.34.0` once B1 is resolved via IV.7.
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:21:  driver loader`. Fixes TopWatchBar pressure em-dash on Ubuntu lab
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:40:  watchdog (IV.6 partial B1 mitigation)`. Landed the full
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:41:  Codex-proposed B1 fix plan: per-command ephemeral REQ socket in
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:47:  **Does NOT fix B1 — Stage 3 diag tools still reproduce it.**
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:52:- Config edits on Ubuntu lab PC (some in git, some local):
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:55:    disconnected (reads 380 K open-circuit), was triggering
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:63:- Operational on Ubuntu lab PC: `ModemManager` disabled
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:68:- **B1 still unresolved.** GUI command channel silently dies
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:69:  ~30-120 s after bridge startup on both platforms. IV.7 `ipc://`
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:73:  regression, system works in 60-120 s cycles with single
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:183:  hue ≈90°, violated ≥60° invariant) → `#6a7530` moss-olive ≈70°.
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:243:  (median × 5 timeout, 10 s floor, 300 s default, 3-reading adaptive
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:346:  replace direct `_auto_state` attribute access for external finalize
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:405:  P target / V compliance / I compliance `QDoubleSpinBox` with 300 ms
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:424:  deferred. Tests: 30 new cases in
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:466:  `STATUS_CAUTION` shifts from `#c47a30` (amber) to `#b35a38` (red-orange)
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:468:  `#4a7ba8` → `#6490c4` for slightly higher legibility on dark surfaces;
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:479:  (`#11151d` / `#30363d` / `#141821` etc.) that bypassed theme.py and
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:537:  The `cryodaq` launcher creates QApplication + MainWindowV2 directly
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:584:  визуальной оценки B.4.5. Desaturation status tier цветов на 30-40%,
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:608:  загрязняли индикатор. Stale-индикация через 30 секунд.
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:624:  использовался на строке 969. Регрессия от `8070b2db`. Engine падал
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:633:  1280, `BentoGrid` row-span now affects rendered height (with geometry test),
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:731:  with idempotent re-ack guard. Ruff lint debt 830 → 445.
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:750:  без pytest module, silently failed, injected `"Tests: no output"`
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:760:  60-90% token compression on dev operations. Note: strips `--no-ff`
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:761:  flag from `git merge` — workaround: `/usr/bin/git` directly.
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:763:  files into 4,304 nodes, 10,602 edges, 169 Leiden communities.
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:769:  `graphify-out/GRAPH_REPORT.md` first.
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:833:- **Ruff lint** — накопленный долг сокращён с 830 до 445 ошибок
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:894:## [0.30.0] — 12-04-26 — Карта реальности и документация
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:906:  состояние `MANUAL_RECOVERY`.
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:930:  инварианта (1 090 строк).
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:936:- **Master triage** — синтез всех аудит-документов (307 строк).
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:938:Диапазон коммитов: `380df96`..`7aaeb2b` (12 commits)
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:983:- **Experiment workspace** — 1080p layout для phase bar и passport forms.
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1101:- **ZMQ datetime** — сериализация + REP socket stuck на ошибке.
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1130:Диапазон коммитов: `856ad19`..`50e30e3` (7 commits)
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1311:  export). `.330` / `.340` / JSON export.
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1368:+14 690 / -6 632 строк через 83 файла. Backend workflows (experiments,
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1448:- **Cooldown predictor** — `cooldown_predictor.py` (~900 строк):
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1452:  (IDLE→COOLING→STABILIZING→COMPLETE), периодический predict (30с),
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1465:Диапазон коммитов: `9217489`..`9390419` (7 commits)
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1476:  RUNNING → FAULT_LATCHED → MANUAL_RECOVERY. Fail-on-silence: устаревшие
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1554:  Telegram каждые 30 мин.
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:1606:- **ZMQ bridge** — PUB/SUB на порту :5555 (msgpack) + REP/REQ :5556
/Users/vladimir/Projects/cryodaq/ROADMAP.md:3:> **Living document.** Updated 2026-04-20 after IV.2 close (HEAD `df43081`).
/Users/vladimir/Projects/cryodaq/ROADMAP.md:67:Shipped: ~800 LOC, 4 commits, 5 amend cycles total, 863 GUI tests
/Users/vladimir/Projects/cryodaq/ROADMAP.md:92:Estimated: ~1100-1300 LOC, 3 commits, ~7-8h CC. Includes engine changes.
/Users/vladimir/Projects/cryodaq/ROADMAP.md:127:   Benefit: finalize Parquet hook never silently skips.
/Users/vladimir/Projects/cryodaq/ROADMAP.md:186:Estimated: ~600 LOC (400 GUI + 200 engine) + 30 tests.
/Users/vladimir/Projects/cryodaq/ROADMAP.md:225:**Blocker:** Hermes service must be deployed on lab Ubuntu first.
/Users/vladimir/Projects/cryodaq/ROADMAP.md:239:3. Confirm LibreOffice path works on lab Ubuntu 22.04 for PDF generation.
/Users/vladimir/Projects/cryodaq/ROADMAP.md:263:- Feature engineering from 30+ historical cooldowns (extract from SQLite)
/Users/vladimir/Projects/cryodaq/ROADMAP.md:288:**Value:** direct support for publication-worthy TIM characterization data.
/Users/vladimir/Projects/cryodaq/ROADMAP.md:319:Estimated: ~300 LOC + 15 tests.
/Users/vladimir/Projects/cryodaq/ROADMAP.md:350:Two-factor: command + confirmation within 30s. Rate-limited,
/Users/vladimir/Projects/cryodaq/ROADMAP.md:359:Current deployment: `git clone` + `pip install -e .` works on Ubuntu.
/Users/vladimir/Projects/cryodaq/ROADMAP.md:379:Estimated: ~300 LOC plugins + docs.
/Users/vladimir/Projects/cryodaq/ROADMAP.md:401:- Cross-platform matrix (Ubuntu + Windows + macOS)
/Users/vladimir/Projects/cryodaq/ROADMAP.md:423:### B1 — ZMQ subprocess command channel dies (not idle-related)
/Users/vladimir/Projects/cryodaq/ROADMAP.md:429:**Symptom:** GUI command plane (REQ/REP on `tcp://127.0.0.1:5556`)
/Users/vladimir/Projects/cryodaq/ROADMAP.md:434:- Ubuntu: first failure at **exactly 120s** after subprocess start
/Users/vladimir/Projects/cryodaq/ROADMAP.md:437:**NOT macOS-specific.** Confirmed on Ubuntu 22.04 lab machine
/Users/vladimir/Projects/cryodaq/ROADMAP.md:451:- TCP_KEEPALIVE fix (commit `f5f9039`) will be **reverted** on
/Users/vladimir/Projects/cryodaq/ROADMAP.md:467:`docs/bug_B1_zmq_idle_death_handoff.md`.
/Users/vladimir/Projects/cryodaq/ROADMAP.md:476:- `tools/diag_zmq_bridge_extended.py` — 180s past-first-failure
/Users/vladimir/Projects/cryodaq/ROADMAP.md:490:macOS reproduce B1 with structurally identical timing to pre-fix
/Users/vladimir/Projects/cryodaq/ROADMAP.md:493:- `diag_zmq_idle_hypothesis.py` SPARSE_0.33HZ: cmd #8 FAIL at
/Users/vladimir/Projects/cryodaq/ROADMAP.md:494:  uptime 56 s (pre-fix was cmd #10 FAIL at ~30 s).
/Users/vladimir/Projects/cryodaq/ROADMAP.md:497:- RAPID_5HZ path still clean (295/295), matching pre-fix behaviour
/Users/vladimir/Projects/cryodaq/ROADMAP.md:501:REP goes silently unresponsive after ~30-90 s of bridge uptime
/Users/vladimir/Projects/cryodaq/ROADMAP.md:505:Python 3.14 asyncio integration, or engine-side REP task state
/Users/vladimir/Projects/cryodaq/ROADMAP.md:512:**Status:** still 🔧. B1 remains OPEN and blocks `0.34.0`.
/Users/vladimir/Projects/cryodaq/ROADMAP.md:524:command-only failure shape — independent of whether B1 is
/Users/vladimir/Projects/cryodaq/ROADMAP.md:533:was restarted again — restart storm (30-40 restarts/minute
/Users/vladimir/Projects/cryodaq/ROADMAP.md:534:observed on Ubuntu lab PC).
/Users/vladimir/Projects/cryodaq/ROADMAP.md:539:checks run in the same poll cycle. Does not resolve B1 itself —
/Users/vladimir/Projects/cryodaq/ROADMAP.md:541:System returns to "works ~60-120 s, one restart, works again"
/Users/vladimir/Projects/cryodaq/ROADMAP.md:549:  resolves TopWatchBar pressure em-dash on Ubuntu lab PC (VSP206
/Users/vladimir/Projects/cryodaq/ROADMAP.md:562:reading-driven, not B1-caused) is now resolved by `aabd75f` +
/Users/vladimir/Projects/cryodaq/ROADMAP.md:563:Ubuntu-side config (`validate_checksum: false` in
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:1:# Bug B1 — ZMQ subprocess command channel dies — Codex handoff
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:25:subprocess) has not been tested for long-soak behavior. Engine REP
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:26:itself is healthy when tested directly.
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:37:  `tcp://127.0.0.1:5556` (REQ/REP), both loopback TCP
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:59:`{"cmd": "safety_status"}` every 1 second for 180 seconds.
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:61:Exact timings variable across runs (4-90s uptime to first fail).
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:68:Phase 1 RAPID  5Hz    (200ms idle) for 60s: 291/291 OK, 0 fails
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:69:Phase 2 SPARSE 0.33Hz (3000ms idle) for 60s: 9 OK, cmd #10 FAIL 35s
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:70:Phase 3 RECOVER 5Hz              30s: cmd #1 FAIL immediately
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:95:**Engine REP socket is healthy.** Direct Python client test:
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:105:reply = req.recv_string()  # GOT REPLY in 0.001s
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:109:in subprocess receives steady 20 readings/sec), heartbeats every 30s,
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:110:SQLite writes ~9000 entries per 10 minutes.
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:113:`tools/diag_zmq_subprocess.py` — spawns `zmq_bridge_main()` directly,
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:114:runs both spawn and fork mp start_methods. First command GOT REPLY
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:136:  `ZMQCommandServer` REP socket
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:148:- `ZMQCommandServer.start()` — creates REP socket, binds
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:153:  get 30s envelope.
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:155:  dict. REP socket state-machine-sensitive, so handler timeouts yield
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:178:  `future.result(timeout=_CMD_REPLY_TIMEOUT_S=35.0)`
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:184:1. **Engine REP wedge** — Ruled out. Direct zmq client gets 0.001s
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:187:   maxsize=10000. In 180s at 20 readings/sec = 3600 readings, no
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:190:3. **`asyncio.CancelledError` on engine side wedging REP** — Code
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:207:   Why does a fresh REQ socket still hang? If engine REP is healthy
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:214:   - SQLite WAL checkpoint or other 30s-periodic operation on engine
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:222:   ZMQ context OR in engine's REP state (but engine responds to
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:223:   fresh direct clients fine).
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:227:   `zmq.Again` subclass. But the warning "REP timeout on
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:267:continue hanging, when engine REP is verified healthy via direct
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:293:- This doc (`docs/bug_B1_zmq_idle_death_handoff.md`)
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:329:# Expected BEFORE any fix: first FAIL within ~30-90s, then 0% recovery
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:344:## Ubuntu data point
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:348:- **Real system** (`./start.sh`, not diag tool) — first REP timeout on
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:349:  `experiment_status` at **exactly 120s** after subprocess start.
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:350:- Ubuntu 22.04, Linux 5.15.0-173, Python 3.12.13, pyzmq 26.4.0,
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:352:- TCP_KEEPALIVE fix already applied (commit `f5f9039`).
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:355:  — the 120s failure cannot be kernel idle reaping.
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:371:Ubuntu it appears connection-age or socket-state related rather than
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:381:The TCP_KEEPALIVE fix applied at commit `f5f9039` is **NOT
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:395:## Pressure display bug is SEPARATE from B1
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:402:The "pressure shows em-dash" observation does NOT help diagnose B1.
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:452:- Remove `TCP_KEEPALIVE*` from command-path REQ + engine-side REP.
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:463:- Stale heartbeat (>30s)
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:464:- Stalled data flow (>30s)
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:487:- Ubuntu: even if libzmq 4.3.5 has some 120s internal timer on
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:517:# Expected: 180/180 OK
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:520:# Leave idle 15+ min, verify no REP timeout warnings
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:523:### Ubuntu
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:527:# No timeout at 120s mark
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:530:# Expected: 180/180 OK
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:555:## IV.6 landed at `be51a24` but did NOT fix B1
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:560:diag tools against mock engine on macOS — **B1 still reproduces
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:563:- `diag_zmq_idle_hypothesis.py` SPARSE_0.33HZ: cmd #8 FAIL at
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:564:  uptime 56 s (pre-fix was cmd #10 at ~30 s).
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:567:- RAPID_5 Hz path still clean (295/295), matching pre-fix rate
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:571:long-lived socket did not eliminate the failure. Engine REP goes
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:572:silently unresponsive after ~30-90 s of bridge uptime while the
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:577:directive — the architectural improvement stands regardless of
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:578:whether it individually closed B1.
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:584:`_poll_bridge_data` tick → another restart → storm (30-40 /min
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:585:on Ubuntu). Hotfix: 60 s cooldown + missing `return` after
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:597:  without fixing B1)
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:611:Ubuntu → tag `0.34.0`. If failures persist → B1 is higher than
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:615:## Related fixes shipped during B1 investigation (2026-04-20)
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:619:`engine.py::_create_instruments()` was silently dropping the
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:623:TopWatchBar silently dropped. Root cause was a loader-wiring
/Users/vladimir/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md:654:## Still-open orthogonal bugs (not B1, not blocking 0.34.0)

exec
/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py | sed -n '1,180p'; nl -ba /Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_subprocess.py | sed -n '1,260p'" in /Users/vladimir/Projects/cryodaq
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
    23	from cryodaq.drivers.base import ChannelStatus, Reading
    24	
    25	logger = logging.getLogger(__name__)
    26	
    27	DEFAULT_PUB_ADDR = "tcp://127.0.0.1:5555"
    28	DEFAULT_CMD_ADDR = "tcp://127.0.0.1:5556"
    29	DEFAULT_TOPIC = b"readings"
    30	
    31	# IV.3 Finding 7: per-command tiered handler timeout.
    32	# A flat 2 s envelope was wrong for stateful transitions —
    33	# experiment_finalize / abort / create and calibration curve
    34	# import/export/fit routinely exceed 2 s (SQLite writes + DOCX/PDF
    35	# report generation). When they timed out the outer REP reply path
    36	# still fired (the original code already returned {ok: False}), but
    37	# the operator saw a "handler timeout (2s)" error that was a lie:
    38	# the operation usually completed a few seconds later. Fast status
    39	# polls stay on the 2 s envelope; known-slow commands get 30 s.
    40	HANDLER_TIMEOUT_FAST_S = 2.0
    41	HANDLER_TIMEOUT_SLOW_S = 30.0
    42	
    43	_SLOW_COMMANDS: frozenset[str] = frozenset(
    44	    {
    45	        "experiment_finalize",
    46	        "experiment_stop",
    47	        "experiment_abort",
    48	        "experiment_create",
    49	        "experiment_create_retroactive",
    50	        "experiment_start",
    51	        "experiment_generate_report",
    52	        "calibration_curve_import",
    53	        "calibration_curve_export",
    54	        "calibration_v2_fit",
    55	        "calibration_v2_extract",
    56	    }
    57	)
    58	
    59	
    60	def _timeout_for(cmd: Any) -> float:
    61	    """Return the handler timeout envelope for ``cmd``.
    62	
    63	    Slow commands get ``HANDLER_TIMEOUT_SLOW_S``; everything else
    64	    gets ``HANDLER_TIMEOUT_FAST_S``. Unknown / malformed payloads
    65	    fall back to fast — a cmd that isn't in the slow set must not
    66	    trigger the longer wait by accident.
    67	    """
    68	    if not isinstance(cmd, dict):
    69	        return HANDLER_TIMEOUT_FAST_S
    70	    action = cmd.get("cmd")
    71	    if isinstance(action, str) and action in _SLOW_COMMANDS:
    72	        return HANDLER_TIMEOUT_SLOW_S
    73	    return HANDLER_TIMEOUT_FAST_S
    74	
    75	
    76	# Phase 2b H.4: bind with EADDRINUSE retry. On Windows the socket from a
    77	# SIGKILL'd engine can hold the port for up to 240s (TIME_WAIT). Linux is
    78	# usually fine due to SO_REUSEADDR but the same logic protects both.
    79	_BIND_MAX_ATTEMPTS = 10
    80	_BIND_INITIAL_DELAY_S = 0.5
    81	_BIND_MAX_DELAY_S = 10.0
    82	
    83	
    84	def _bind_with_retry(socket: Any, address: str) -> None:
    85	    """Bind a ZMQ socket, retrying on EADDRINUSE with exponential backoff.
    86	
    87	    Caller MUST set ``zmq.LINGER = 0`` on the socket BEFORE calling this
    88	    helper, otherwise close() will hold the address even after retry succeeds.
    89	    """
    90	    delay = _BIND_INITIAL_DELAY_S
    91	    for attempt in range(_BIND_MAX_ATTEMPTS):
    92	        try:
    93	            socket.bind(address)
    94	            if attempt > 0:
    95	                logger.info(
    96	                    "ZMQ bound to %s after %d retries",
    97	                    address,
    98	                    attempt,
    99	                )
   100	            return
   101	        except zmq.ZMQError as exc:
   102	            # libzmq maps EADDRINUSE to its own errno value.
   103	            is_addr_in_use = exc.errno == zmq.EADDRINUSE or exc.errno == errno.EADDRINUSE
   104	            if not is_addr_in_use:
   105	                raise
   106	            if attempt == _BIND_MAX_ATTEMPTS - 1:
   107	                logger.critical(
   108	                    "ZMQ bind FAILED after %d attempts: %s still in use. "
   109	                    "Check for stale sockets via lsof/netstat.",
   110	                    _BIND_MAX_ATTEMPTS,
   111	                    address,
   112	                )
   113	                raise
   114	            logger.warning(
   115	                "ZMQ bind EADDRINUSE on %s, retry in %.1fs (attempt %d/%d)",
   116	                address,
   117	                delay,
   118	                attempt + 1,
   119	                _BIND_MAX_ATTEMPTS,
   120	            )
   121	            time.sleep(delay)
   122	            delay = min(delay * 2, _BIND_MAX_DELAY_S)
   123	
   124	
   125	def _pack_reading(reading: Reading) -> bytes:
   126	    """Сериализовать Reading в msgpack."""
   127	    data = {
   128	        "ts": reading.timestamp.timestamp(),
   129	        "iid": reading.instrument_id,
   130	        "ch": reading.channel,
   131	        "v": reading.value,
   132	        "u": reading.unit,
   133	        "st": reading.status.value,
   134	        "raw": reading.raw,
   135	        "meta": reading.metadata,
   136	    }
   137	    return msgpack.packb(data, use_bin_type=True)
   138	
   139	
   140	def _unpack_reading(payload: bytes) -> Reading:
   141	    """Десериализовать Reading из msgpack."""
   142	    data = msgpack.unpackb(payload, raw=False)
   143	    return Reading(
   144	        timestamp=datetime.fromtimestamp(data["ts"], tz=UTC),
   145	        instrument_id=data.get("iid", ""),
   146	        channel=data["ch"],
   147	        value=data["v"],
   148	        unit=data["u"],
   149	        status=ChannelStatus(data["st"]),
   150	        raw=data.get("raw"),
   151	        metadata=data.get("meta", {}),
   152	    )
   153	
   154	
   155	class ZMQPublisher:
   156	    """PUB-сокет: engine публикует Reading для GUI и внешних подписчиков.
   157	
   158	    Использование::
   159	
   160	        pub = ZMQPublisher("tcp://127.0.0.1:5555")
   161	        await pub.start(queue)   # asyncio.Queue[Reading] от DataBroker
   162	        ...
   163	        await pub.stop()
   164	    """
   165	
   166	    def __init__(self, address: str = DEFAULT_PUB_ADDR, *, topic: bytes = DEFAULT_TOPIC) -> None:
   167	        self._address = address
   168	        self._topic = topic
   169	        self._ctx: zmq.asyncio.Context | None = None
   170	        self._socket: zmq.asyncio.Socket | None = None
   171	        self._task: asyncio.Task[None] | None = None
   172	        self._running = False
   173	        self._total_sent: int = 0
   174	
   175	    async def _publish_loop(self, queue: asyncio.Queue[Reading]) -> None:
   176	        while self._running:
   177	            try:
   178	                reading = await asyncio.wait_for(queue.get(), timeout=1.0)
   179	            except TimeoutError:
   180	                continue
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
/opt/homebrew/bin/bash -lc 'rg -n "_validate_bridge_startup|attempts|backoff|safety_status|Bridge startup probe|b2b4fb5|89b4db1|c3f4f86|Q4|7 edge|ipc|44/44|20/20|Engine не отвечает|Resource temporarily unavailable" /Users/vladimir/Projects/cryodaq/docs/decisions /Users/vladimir/Projects/cryodaq/docs/ORCHESTRATION.md /Users/vladimir/Projects/cryodaq/tools/diag_zmq_b1_capture.py -S' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
/Users/vladimir/Projects/cryodaq/tools/diag_zmq_b1_capture.py:20:# Startup probe tuning. Each attempt sends one `safety_status` command
/Users/vladimir/Projects/cryodaq/tools/diag_zmq_b1_capture.py:63:    sample["bridge_reply"] = bridge.send_command({"cmd": "safety_status"})
/Users/vladimir/Projects/cryodaq/tools/diag_zmq_b1_capture.py:81:def _validate_bridge_startup(
/Users/vladimir/Projects/cryodaq/tools/diag_zmq_b1_capture.py:84:    attempts: int = _STARTUP_PROBE_ATTEMPTS,
/Users/vladimir/Projects/cryodaq/tools/diag_zmq_b1_capture.py:85:    backoff_s: float = _STARTUP_PROBE_BACKOFF_S,
/Users/vladimir/Projects/cryodaq/tools/diag_zmq_b1_capture.py:90:    R1 repair for the b2b4fb5 startup race: instead of a single-shot
/Users/vladimir/Projects/cryodaq/tools/diag_zmq_b1_capture.py:91:    ``safety_status`` probe (which aborted the capture at cmd #0 when
/Users/vladimir/Projects/cryodaq/tools/diag_zmq_b1_capture.py:92:    the engine's ipc:// REP socket had not finished binding), retry
/Users/vladimir/Projects/cryodaq/tools/diag_zmq_b1_capture.py:93:    the probe up to ``attempts`` times with ``backoff_s`` between
/Users/vladimir/Projects/cryodaq/tools/diag_zmq_b1_capture.py:94:    attempts. Any OK reply passes. See
/Users/vladimir/Projects/cryodaq/tools/diag_zmq_b1_capture.py:95:    ``docs/decisions/2026-04-24-b2b4fb5-investigation.md`` for the
/Users/vladimir/Projects/cryodaq/tools/diag_zmq_b1_capture.py:105:    for attempt in range(attempts):
/Users/vladimir/Projects/cryodaq/tools/diag_zmq_b1_capture.py:106:        reply = bridge.send_command({"cmd": "safety_status"})
/Users/vladimir/Projects/cryodaq/tools/diag_zmq_b1_capture.py:110:        if attempt < attempts - 1:
/Users/vladimir/Projects/cryodaq/tools/diag_zmq_b1_capture.py:114:                attempts,
/Users/vladimir/Projects/cryodaq/tools/diag_zmq_b1_capture.py:115:                backoff_s,
/Users/vladimir/Projects/cryodaq/tools/diag_zmq_b1_capture.py:118:            sleep_fn(backoff_s)
/Users/vladimir/Projects/cryodaq/tools/diag_zmq_b1_capture.py:120:    raise RuntimeError(f"Bridge startup probe failed: {last_reply!r}")
/Users/vladimir/Projects/cryodaq/tools/diag_zmq_b1_capture.py:167:            _validate_bridge_startup(bridge)
/Users/vladimir/Projects/cryodaq/docs/ORCHESTRATION.md:28:- `b2b4fb5` (hardening gate for B1 capture probe) landed 45 min
/Users/vladimir/Projects/cryodaq/docs/ORCHESTRATION.md:29:  before `157c4bc` (IV.7 ipc:// transport) without anyone noticing
/Users/vladimir/Projects/cryodaq/docs/ORCHESTRATION.md:30:  the hardening gate's assumptions would reject a healthy ipc://
/Users/vladimir/Projects/cryodaq/docs/ORCHESTRATION.md:201:checked out on `experiment/iv7-ipc-transport`) is what the rule
/Users/vladimir/Projects/cryodaq/docs/ORCHESTRATION.md:218:zmq(transport): switch loopback default to ipc:// on unix
/Users/vladimir/Projects/cryodaq/docs/ORCHESTRATION.md:223:  Stale socket file cleanup via _prepare_ipc_path() required
/Users/vladimir/Projects/cryodaq/docs/ORCHESTRATION.md:329:The 2026-04-23 mistake: `b2b4fb5` hardened the bridge startup
/Users/vladimir/Projects/cryodaq/docs/ORCHESTRATION.md:330:probe 45 min before IV.7 `157c4bc` added ipc:// transport. The
/Users/vladimir/Projects/cryodaq/docs/ORCHESTRATION.md:332:healthy." ipc:// bridge may have been healthy but the probe
/Users/vladimir/Projects/cryodaq/docs/ORCHESTRATION.md:416:| IV.7 | `CC_PROMPT_IV_7_IPC_TRANSPORT.md` | Failed runtime 2026-04-23; likely blocked by unrelated hardening (`b2b4fb5`); **next architect action**: test the hypothesis — revert hardening on iv7 worktree, rerun diag, see if ipc:// was actually healthy |
/Users/vladimir/Projects/cryodaq/docs/ORCHESTRATION.md:443:3. **Hardening / feature collision.** 2026-04-23: `b2b4fb5`
/Users/vladimir/Projects/cryodaq/docs/ORCHESTRATION.md:445:   (landed 45 min later) would switch transport to ipc://. The
/Users/vladimir/Projects/cryodaq/docs/ORCHESTRATION.md:447:   what killed the IV.7 capture, not the ipc:// transport
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-d1-d4a-execution.md:6:implemented on `feat/b2b4fb5-repair` branch, pushed to origin for
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-d1-d4a-execution.md:28:  **pre-b2b4fb5 form** — the state that R1 must land on top of.
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-d1-d4a-execution.md:34:- **Branch:** `feat/b2b4fb5-repair` (new, tracks `origin/feat/b2b4fb5-repair`)
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-d1-d4a-execution.md:36:- **HEAD:** `c3f4f86` — fix(diag): bounded-backoff retry in B1 capture probe (R1 repair for b2b4fb5)
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-d1-d4a-execution.md:41:### R1 implementation outline (c3f4f86)
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-d1-d4a-execution.md:43:New helper `_validate_bridge_startup(bridge, attempts=5, backoff_s=0.2, sleep_fn=time.sleep)`:
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-d1-d4a-execution.md:45:2. Loop up to `attempts` times: `bridge.send_command({"cmd": "safety_status"})`. First OK reply passes.
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-d1-d4a-execution.md:46:3. Inter-attempt `sleep_fn(backoff_s)` with DEBUG log.
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-d1-d4a-execution.md:47:4. All attempts non-OK → `raise RuntimeError(f"Bridge startup probe failed: {last_reply!r}")` — same error surface as b2b4fb5.
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-d1-d4a-execution.md:49:Call site added in `main()` between `bridge.start()` + `time.sleep(1.0)` and `run_capture(...)`. Failure → stderr `"B1 capture aborted: ..."` + `return 1`, matching b2b4fb5's behavior so downstream tooling that greps this marker is unaffected.
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-d1-d4a-execution.md:55:| 1 | dead bridge (is_alive=False) → raises without send_command | ✅ | `test_validate_bridge_startup_dead_bridge_raises_without_send_command` |
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-d1-d4a-execution.md:56:| 2 | alive + 2× non-OK + OK → succeeds after 3 attempts with fake sleep | ✅ | `test_validate_bridge_startup_succeeds_after_transient_non_ok` |
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-d1-d4a-execution.md:57:| 3 | alive + all non-OK → raises with last reply; sleeps bounded | ✅ | `test_validate_bridge_startup_all_non_ok_raises_with_last_reply` + `test_main_returns_nonzero_when_bridge_startup_fails` |
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-d1-d4a-execution.md:58:| 4 | ipc:// 50-run loop, zero cmd #0 aborts | ⚠️ deferred | needs live engine + mock config; manual hardware verification |
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-d1-d4a-execution.md:85:2. **D2** — H4 split-context falsification experiment on `experiment/iv7-ipc-transport` worktree.
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-d1-d4a-execution.md:86:3. **Post-D1-merge Codex equivalence check** (architect Q4) — verify functionally equivalent to post-`b2b4fb5` state plus the R1 delta.
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-d1-d4a-execution.md:87:4. **Architect review + merge** of `feat/b2b4fb5-repair`.
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-d1-d4a-execution.md:97:## 22:16 — Q4 equivalence check PASS (session addendum)
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-d1-d4a-execution.md:100:architect Q4 directive after the M2 merge-commit `89b4db1` landed.
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-d1-d4a-execution.md:106:- Synthesis: `artifacts/consultations/2026-04-24-overnight/STREAM_SYNTHESES/Q4-equivalence-synthesis.md`
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-d1-d4a-execution.md:111:  7 edge-case inputs (`None`, `{}`, `{"ok": None}`, `{"ok": "True"}`,
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-d1-d4a-execution.md:112:  `{"ok": 1}`, `{"ok": True}`, `{"ok": False}`) — R1 and b2b4fb5
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-d1-d4a-execution.md:121:1. `git branch -D feat/b2b4fb5-repair` (local)
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-d1-d4a-execution.md:122:2. `git push origin --delete feat/b2b4fb5-repair` (remote)
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-d1-d4a-execution.md:123:3. Verified `c3f4f86` remains reachable via merge-commit `89b4db1`
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-d1-d4a-execution.md:132:Review `feat/b2b4fb5-repair` (`c3f4f86`):
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-23-cleanup-baseline.md:20:| 5 | `git worktree list` | 3 real + 1 prunable `/private/tmp`; `.worktrees/codex-safe-merge-b1-truth-recovery` naming mismatch on branch `experiment/iv7-ipc-transport` (§5.4 violation) |
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-23-cleanup-baseline.md:23:| 8 | Stale feature branch (>2d)? | `codex/safe-merge-b1-truth-recovery` and `experiment/iv7-ipc-transport` — architect-preserved per §11; not touched this session |
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-23-cleanup-baseline.md:105:Decision: `git worktree move .worktrees/codex-safe-merge-b1-truth-recovery .worktrees/experiment-iv7-ipc-transport`. Name now matches branch. §5.4 naming-mismatch invariant restored.
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-23-cleanup-baseline.md:120:Decision: `git worktree remove --force .worktrees/codex-b1-truth-recovery` (safe now that stray file preserved). `git branch -D codex/b1-truth-recovery` (was 9 commits ahead of master). `git branch -D codex/preserved-local-master-2026-04-21` (was 6 commits ahead of master). Kept `codex/safe-merge-b1-truth-recovery` (b2b4fb5, pending architect eval) and `experiment/iv7-ipc-transport` (63a3fed, pending b2b4fb5 hypothesis test).
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-23-cleanup-baseline.md:128:| codex/safe-merge-b1-truth-recovery | b2b4fb5 | preserved, pending architect eval |
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-23-cleanup-baseline.md:129:| experiment/iv7-ipc-transport | 63a3fed | preserved, pending b2b4fb5 hypothesis test |
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-23-cleanup-baseline.md:136:| `.worktrees/experiment-iv7-ipc-transport` | experiment/iv7-ipc-transport | renamed from `.worktrees/codex-safe-merge-b1-truth-recovery` per §5.4 |
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-23-cleanup-baseline.md:142:- **b2b4fb5 hypothesis test**: does the hardened B1 probe reject a healthy `ipc://` bridge, causing the 2026-04-23 IV.7 runtime failure to have been misattributed? (Plan `CC_PROMPT_IV_7_IPC_TRANSPORT.md` still active per §11.)
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-23-cleanup-baseline.md:144:- **IV.7 status**: depends on b2b4fb5 test outcome.
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:1:# 2026-04-24 — b2b4fb5 hypothesis investigation
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:5:Determine whether commit `b2b4fb5` (2026-04-23 15:10, "harden B1
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:6:capture bridge startup validation") is incompatible with the `ipc://`
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:9:to the ipc:// switch itself.
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:13:`b2b4fb5`'s synchronous startup probe `_validate_bridge_startup()`
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:14:fails against a fresh ipc://-bound engine because the engine's REP
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:16:`{"ok": false, "error": "Engine не отвечает (Resource temporarily
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:20:Once the engine has had time to bind the ipc socket and open its REP
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:22:succeeded against ipc:// with the hardening reverted.
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:24:**IV.7 failure on 2026-04-23 was not caused by the ipc:// transport
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:26:ipc:// bind timing.**
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:41:Thesis: `b2b4fb5` only touches `tools/diag_zmq_b1_capture.py` and its
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:42:test. Post-b2b4fb5 commits (`157c4bc`, `63a3fed`) touched different
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:55:    B1 capture aborted: Bridge startup probe failed:
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:56:    {'ok': False, 'error': 'Engine не отвечает (Resource temporarily unavailable)'}
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:58:This is the **exact literal output** of `_validate_bridge_startup`
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:59:from `b2b4fb5`. The tool used for the IV.7 test was `diag_zmq_b1_capture.py`
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:68:instantaneous, so the check tends to pass. Under ipc://, socket-file
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:83:### 00:15 — Extended diag against ipc:// engine (bridge_extended.py)
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:85:Worktree `.worktrees/experiment-iv7-ipc-transport` (branch
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:86:`experiment/iv7-ipc-transport` at `63a3fed`).
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:87:- Ran `git revert --no-commit b2b4fb5` — clean revert, 2 files
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:91:- Engine bound to `ipc:///tmp/cryodaq-pub.sock` and
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:92:  `ipc:///tmp/cryodaq-cmd.sock` (Unix default from
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:103:Interpretation: **ipc:// transport itself works for ~80s**, then the
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:114:Result: `bridge_reply: {"ok": false, "error": "Engine не отвечает
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:115:(Resource temporarily unavailable)"}`, `direct_reply: TimeoutError`.
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:122:### 00:20 — b1_capture against FRESH engine with b2b4fb5 reverted
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:129:- 20/20 samples successful.
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:134:normally against ipc://**. The exact same tool with the exact same
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:135:transport at the exact same codebase tip, minus only the b2b4fb5
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:140:- `kill` engine process, `rm` ipc sockets.
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:142:- Branch tip intact: `63a3fed`, `157c4bc`, `b2b4fb5`, ... preserved.
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:150:| IV.7 2026-04-23 failure | present | ipc:// | ~fresh (< 1s) | **abort at cmd#0** — "Engine не отвечает" |
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:151:| retest 2026-04-24 (bridge_extended) | reverted | ipc:// | 4s | 44/44 early OK, B1 idle-death at cmd #45 |
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:152:| retest 2026-04-24 (b1_capture against degraded engine) | reverted | ipc:// | ~4 min | fail (engine already broken by B1) |
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:153:| retest 2026-04-24 (b1_capture against fresh engine) | reverted | ipc:// | 4s | **20/20 OK** |
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:155:The controlling variable is the presence of the b2b4fb5 hardening
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:157:makes b1_capture pass on ipc://.
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:163:1. IV.7's `ipc://` transport is viable. It runs normally for the
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:164:   first ~80 seconds of engine uptime against ipc sockets.
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:165:2. `b2b4fb5`'s startup probe is incompatible with ipc:// at engine
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:169:   misattribution: b2b4fb5 aborted the diag capture before IV.7's
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:174:4. **B1 idle-death is unrelated to b2b4fb5.** B1 fires at ~80s
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:183:**Option R1 — fix b2b4fb5 to be startup-race-tolerant.**
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:184:Rework `_validate_bridge_startup()` to retry the probe with bounded
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:185:backoff (e.g., 5 × 200ms) instead of single-shot. This makes it work
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:186:for both tcp and ipc without losing the guard against subprocess
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:195:**Option R3 — revert b2b4fb5 and accept no startup guard.**
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:201:- If R1 or R2: fix first, then merge `experiment/iv7-ipc-transport`
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:205:- If R3: straight revert of `b2b4fb5`, merge iv7 → master, tag
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:213:- IV.7's `_prepare_ipc_path` cleans up stale sockets but still
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:214:  has a narrow window between `_cleanup_ipc_path_if_safe` and
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:224:  69-76 on `b2b4fb5`
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:225:- `src/cryodaq/core/zmq_transport.py` — ipc:// defaults (iv7
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:228:  ipc-aware; unrelated to the b2b4fb5 hardening issue)
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:231:- `/tmp/b1_retest_fresh.jsonl` — 20/20 success with revert
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-b2b4fb5-investigation.md:233:  signature on ipc://
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-overnight-swarm-launch.md:158:- `docs/decisions/2026-04-24-b2b4fb5-investigation.md` — input

exec
/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Projects/cryodaq/src/cryodaq/core/safety_manager.py | sed -n '1,180p;300,390p;850,910p'; nl -ba /Users/vladimir/Projects/cryodaq/config/safety.yaml | sed -n '1,120p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	"""SafetyManager for CryoDAQ."""
     2	
     3	from __future__ import annotations
     4	
     5	import asyncio
     6	import logging
     7	import math
     8	import re
     9	import time
    10	from collections import deque
    11	from collections.abc import Callable
    12	from dataclasses import dataclass, field
    13	from datetime import UTC, datetime
    14	from enum import Enum
    15	from pathlib import Path
    16	from typing import Any
    17	
    18	import yaml
    19	
    20	from cryodaq.core.rate_estimator import RateEstimator
    21	from cryodaq.core.safety_broker import SafetyBroker
    22	from cryodaq.core.smu_channel import SmuChannel, normalize_smu_channel
    23	from cryodaq.drivers.base import Reading
    24	
    25	logger = logging.getLogger(__name__)
    26	
    27	_MAX_EVENTS = 500
    28	_CHECK_INTERVAL_S = 1.0
    29	
    30	
    31	class SafetyConfigError(RuntimeError):
    32	    """Raised when safety.yaml cannot be loaded in a fail-closed manner.
    33	
    34	    Distinct class so engine startup and launcher can recognise it as a
    35	    config error (clean exit code, no auto-restart) rather than a generic
    36	    runtime crash (retryable).
    37	    """
    38	
    39	
    40	class SafetyState(Enum):
    41	    SAFE_OFF = "safe_off"
    42	    READY = "ready"
    43	    RUN_PERMITTED = "run_permitted"
    44	    RUNNING = "running"
    45	    FAULT_LATCHED = "fault_latched"
    46	    MANUAL_RECOVERY = "manual_recovery"
    47	
    48	
    49	@dataclass(frozen=True, slots=True)
    50	class SafetyEvent:
    51	    timestamp: datetime
    52	    from_state: SafetyState
    53	    to_state: SafetyState
    54	    reason: str
    55	    channel: str = ""
    56	    value: float = 0.0
    57	
    58	
    59	@dataclass
    60	class SafetyConfig:
    61	    critical_channels: list[re.Pattern[str]] = field(default_factory=list)
    62	    stale_timeout_s: float = 10.0
    63	    heartbeat_timeout_s: float = 15.0
    64	    max_safety_backlog: int = 100
    65	    require_keithley_for_run: bool = True
    66	    max_dT_dt_K_per_min: float = 5.0
    67	    require_reason: bool = True
    68	    cooldown_before_rearm_s: float = 60.0
    69	    max_power_w: float = 5.0
    70	    max_voltage_v: float = 40.0
    71	    max_current_a: float = 1.0
    72	    keithley_channel_patterns: list[str] = field(default_factory=lambda: [".*/smu.*"])
    73	    scheduler_drain_timeout_s: float = 5.0
    74	
    75	
    76	class SafetyManager:
    77	    """Single safety state machine with channel-aware Keithley control."""
    78	
    79	    def __init__(
    80	        self,
    81	        safety_broker: SafetyBroker,
    82	        *,
    83	        keithley_driver: Any | None = None,
    84	        mock: bool = False,
    85	        data_broker: Any | None = None,
    86	        fault_log_callback: Any | None = None,
    87	    ) -> None:
    88	        self._broker = safety_broker
    89	        self._keithley = keithley_driver
    90	        self._mock = mock
    91	        self._data_broker = data_broker
    92	        self._fault_log_callback = fault_log_callback
    93	        self._state = SafetyState.SAFE_OFF
    94	        self._config = SafetyConfig()
    95	        self._events: deque[SafetyEvent] = deque(maxlen=_MAX_EVENTS)
    96	        self._fault_reason = ""
    97	        self._fault_time = 0.0
    98	        self._recovery_reason = ""
    99	        self._active_sources: set[SmuChannel] = set()
   100	        self._run_permitted_since: float = 0.0  # monotonic timestamp of RUN_PERMITTED entry
   101	
   102	        self._latest: dict[str, tuple[float, float, str]] = {}
   103	        # Phase 2c CC I.3: min_points raised from 10 to 60 to match
   104	        # rate_estimator.py's documented noise-suppression recommendation.
   105	        # At 0.5s poll interval the 120s window holds ~240 points;
   106	        # min_points=60 = 30s of data before any rate-based fault decision,
   107	        # which keeps response time acceptable for the 5 K/min threshold
   108	        # while reducing false-positive rate ~2.4x under LS218 ±0.01 K noise.
   109	        self._rate_estimator = RateEstimator(window_s=120.0, min_points=60)
   110	
   111	        self._queue: asyncio.Queue[Reading] | None = None
   112	        self._monitor_task: asyncio.Task[None] | None = None
   113	        self._collect_task: asyncio.Task[None] | None = None
   114	
   115	        # Strong-ref set for fire-and-forget _publish_state tasks scheduled
   116	        # from synchronous _transition. Without this the event loop only
   117	        # weak-refs the task and GC can silently drop a fault-state broadcast.
   118	        # See DEEP_AUDIT_CC.md A.2/I.2.
   119	        self._pending_publishes: set[asyncio.Task[None]] = set()
   120	
   121	        # Hook called from acknowledge_fault to clear external persistence
   122	        # flags (Phase 2a H.1). Engine wires this to writer.clear_disk_full
   123	        # so operator acknowledgment, not auto-recovery, resumes polling.
   124	        self._persistence_failure_clear: Callable[[], None] | None = None
   125	
   126	        # Lock that serializes _active_sources mutations across await points.
   127	        # Multiple REQ clients (GUI subprocess + web dashboard + future
   128	        # operator CLI) can race on request_run / request_stop / emergency_off.
   129	        # See DEEP_AUDIT_CC.md I.1.
   130	        self._cmd_lock = asyncio.Lock()
   131	
   132	        self._keithley_patterns = [re.compile(p) for p in self._config.keithley_channel_patterns]
   133	        self._on_state_change: list[Callable[[SafetyState, SafetyState, str], Any]] = []
   134	        self._broker.set_overflow_callback(lambda: self._fault("SafetyBroker overflow - data lost"))
   135	
   136	    def load_config(self, path: Path) -> None:
   137	        if not path.exists():
   138	            raise SafetyConfigError(
   139	                f"safety.yaml not found at {path} — refusing to start "
   140	                f"SafetyManager without safety configuration"
   141	            )
   142	
   143	        with path.open(encoding="utf-8") as fh:
   144	            raw = yaml.safe_load(fh) or {}
   145	
   146	        if not isinstance(raw, dict):
   147	            raise SafetyConfigError(
   148	                f"safety.yaml at {path} is malformed (expected mapping, got {type(raw).__name__})"
   149	            )
   150	
   151	        raw_patterns = raw.get("critical_channels", [])
   152	        if not isinstance(raw_patterns, list):
   153	            raise SafetyConfigError(
   154	                f"safety.yaml at {path}: critical_channels must be a list, "
   155	                f"got {type(raw_patterns).__name__}"
   156	            )
   157	        if not raw_patterns:
   158	            raise SafetyConfigError(
   159	                f"safety.yaml at {path} has no critical_channels defined — "
   160	                f"refusing to start SafetyManager without critical channel monitoring"
   161	            )
   162	
   163	        patterns: list[re.Pattern[str]] = []
   164	        errors: list[str] = []
   165	        for pattern in raw_patterns:
   166	            if not isinstance(pattern, str):
   167	                errors.append(f"  - {pattern!r}: expected string, got {type(pattern).__name__}")
   168	                continue
   169	            try:
   170	                patterns.append(re.compile(pattern))
   171	            except re.error as exc:
   172	                errors.append(f"  - {pattern!r}: {exc}")
   173	
   174	        if errors:
   175	            raise SafetyConfigError(
   176	                f"safety.yaml at {path} has invalid critical_channels regex:\n" + "\n".join(errors)
   177	            )
   178	
   179	        if not patterns:
   180	            raise SafetyConfigError(f"safety.yaml at {path} produced no valid critical_channels")
   300	                return {
   301	                    "ok": False,
   302	                    "state": self._state.value,
   303	                    "channel": smu_channel,
   304	                    "error": f"V={v_comp}V exceeds limit {self._config.max_voltage_v}V",
   305	                }
   306	            if i_comp > self._config.max_current_a:
   307	                return {
   308	                    "ok": False,
   309	                    "state": self._state.value,
   310	                    "channel": smu_channel,
   311	                    "error": f"I={i_comp}A exceeds limit {self._config.max_current_a}A",
   312	                }
   313	
   314	            if self._state != SafetyState.RUNNING:
   315	                self._run_permitted_since = time.monotonic()
   316	                self._transition(
   317	                    SafetyState.RUN_PERMITTED,
   318	                    f"Start requested for {smu_channel}: P={p_target}W",
   319	                    channel=smu_channel,
   320	                    value=p_target,
   321	                )
   322	
   323	            if self._keithley is None:
   324	                if self._config.require_keithley_for_run and not self._mock:
   325	                    self._transition(SafetyState.SAFE_OFF, "Keithley not connected")
   326	                    return {
   327	                        "ok": False,
   328	                        "state": self._state.value,
   329	                        "channel": smu_channel,
   330	                        "error": "Keithley not connected",
   331	                    }
   332	            else:
   333	                try:
   334	                    await self._keithley.start_source(smu_channel, p_target, v_comp, i_comp)
   335	                except Exception as exc:
   336	                    await self._fault(
   337	                        f"Source start failed on {smu_channel}: {exc}", channel=smu_channel
   338	                    )
   339	                    return {
   340	                        "ok": False,
   341	                        "state": self._state.value,
   342	                        "channel": smu_channel,
   343	                        "error": str(exc),
   344	                    }
   345	
   346	                # CRITICAL safety reconciliation (Codex Phase 1 review P0-2):
   347	                # _fault() runs OUTSIDE _cmd_lock — a fail-on-silence /
   348	                # rate-limit / interlock fault can fire while we are awaiting
   349	                # start_source(). When that happens, _fault has already issued
   350	                # emergency_off and latched FAULT_LATCHED. We must NOT add the
   351	                # channel to _active_sources, and as defense-in-depth we
   352	                # re-issue emergency_off in case start_source's last write
   353	                # interleaved after the fault's OUTPUT_OFF.
   354	                if self._state == SafetyState.FAULT_LATCHED:
   355	                    try:
   356	                        await self._keithley.emergency_off()
   357	                    except Exception as exc:
   358	                        logger.critical("FAULT after start_source: emergency_off failed: %s", exc)
   359	                    return {
   360	                        "ok": False,
   361	                        "state": self._state.value,
   362	                        "channel": smu_channel,
   363	                        "error": f"Fault during start: {self._fault_reason}",
   364	                    }
   365	
   366	            self._active_sources.add(smu_channel)
   367	            if self._state != SafetyState.RUNNING:
   368	                self._transition(
   369	                    SafetyState.RUNNING,
   370	                    f"Source {smu_channel} enabled: P={p_target}W",
   371	                    channel=smu_channel,
   372	                    value=p_target,
   373	                )
   374	            await self._publish_keithley_channel_states(f"run:{smu_channel}")
   375	            return {
   376	                "ok": True,
   377	                "state": self._state.value,
   378	                "channel": smu_channel,
   379	                "active_channels": sorted(self._active_sources),
   380	            }
   381	
   382	    async def request_stop(self, *, channel: str | None = None) -> dict[str, Any]:
   383	        async with self._cmd_lock:
   384	            channels = self._resolve_channels(channel)
   385	            if self._state == SafetyState.FAULT_LATCHED:
   386	                await self._ensure_output_off(channel)
   387	                return {
   388	                    "ok": False,
   389	                    "state": self._state.value,
   390	                    "channels": sorted(channels),
   850	                reading = await self._queue.get()
   851	                now = time.monotonic()
   852	                self._latest[reading.channel] = (now, reading.value, reading.status.value)
   853	                if reading.unit == "K":
   854	                    self._rate_estimator.push(reading.channel, now, reading.value)
   855	        except asyncio.CancelledError:
   856	            return
   857	
   858	    async def _monitor_loop(self) -> None:
   859	        try:
   860	            while True:
   861	                await asyncio.sleep(_CHECK_INTERVAL_S)
   862	                await self._run_checks()
   863	        except asyncio.CancelledError:
   864	            return
   865	
   866	    async def _run_checks(self) -> None:
   867	        now = time.monotonic()
   868	
   869	        if self._state == SafetyState.MANUAL_RECOVERY:
   870	            ok, _ = self._check_preconditions()
   871	            if ok:
   872	                self._transition(SafetyState.READY, "Recovery preconditions restored")
   873	            return
   874	
   875	        if self._state == SafetyState.SAFE_OFF:
   876	            ok, _ = self._check_preconditions()
   877	            if ok and self._latest:
   878	                self._transition(SafetyState.READY, "All preconditions satisfied")
   879	            return
   880	
   881	        # Active monitoring states: RUN_PERMITTED (source starting) and
   882	        # RUNNING (source on). Both need stale/rate/heartbeat checks because
   883	        # a stuck start_source() call must not silently disable monitoring.
   884	        if self._state not in (SafetyState.RUN_PERMITTED, SafetyState.RUNNING):
   885	            return
   886	
   887	        for pattern in self._config.critical_channels:
   888	            for ch, (ts, _value, _status) in self._latest.items():
   889	                if pattern.match(ch) and now - ts > self._config.stale_timeout_s:
   890	                    await self._fault(f"Устаревшие данные канала {ch}", channel=ch)
   891	                    return
   892	
   893	        for ch, (_ts, value, status) in self._latest.items():
   894	            if any(pattern.match(ch) for pattern in self._config.critical_channels):
   895	                if status != "ok":
   896	                    await self._fault(f"Channel {ch} status={status}", channel=ch, value=value)
   897	                    return
   898	                if math.isnan(value) or math.isinf(value):
   899	                    await self._fault(f"Channel {ch}: NaN/Inf", channel=ch, value=value)
   900	                    return
   901	
   902	        if self._keithley is not None and not self._mock:
   903	            if self._active_sources:
   904	                for smu_channel in sorted(self._active_sources):
   905	                    if not self._has_fresh_keithley_data(now, smu_channel):
   906	                        await self._fault(
   907	                            f"Keithley heartbeat timeout {smu_channel}: no data {self._config.heartbeat_timeout_s}s",  # noqa: E501
   908	                            channel=smu_channel,
   909	                        )
   910	                        return
     1	# Конфигурация системы безопасности CryoDAQ
     2	#
     3	# ВНИМАНИЕ: изменения в этом файле влияют на безопасность криогенного оборудования.
     4	# Любые правки должны быть согласованы с ответственным инженером.
     5	
     6	# Каналы, обязательные для разрешения работы нагревателя.
     7	# Regex — если канал не обновляется в течение stale_timeout_s → FAULT.
     8	critical_channels:
     9	  - "Т1 .*"     # верхняя часть криостата
    10	  - "Т7 .*"     # детектор
    11	  - "Т11 .*"    # 1-я ступень GM-cooler (калиброванный)
    12	  - "Т12 .*"    # 2-я ступень, холодная точка (калиброванный)
    13	
    14	# Через сколько секунд без обновления критический канал считается устаревшим
    15	stale_timeout_s: 10.0
    16	
    17	# Таймаут heartbeat Keithley — если нет ответа дольше, → FAULT
    18	heartbeat_timeout_s: 15.0
    19	
    20	# Максимальный размер очереди безопасности. Переполнение → FAULT.
    21	max_safety_backlog: 100
    22	
    23	# Требуется ли подключённый Keithley для перехода в RUN.
    24	# false только для mock-режима.
    25	require_keithley_for_run: true
    26	
    27	# Ограничения по скорости изменения температуры
    28	rate_limits:
    29	  max_dT_dt_K_per_min: 5.0
    30	
    31	# Параметры восстановления после аварии
    32	recovery:
    33	  require_reason: true             # оператор обязан указать причину при acknowledge
    34	  cooldown_before_rearm_s: 60.0   # минимум 60с после аварии до повторного запуска
    35	
    36	# Аппаратные лимиты источника тока
    37	source_limits:
    38	  max_power_w: 5.0
    39	  max_voltage_v: 40.0
    40	  max_current_a: 1.0
    41	
    42	# Регулярные выражения для определения каналов Keithley (heartbeat check)
    43	keithley_channels:
    44	  - ".*/smu.*"
    45	
    46	# Graceful shutdown drain timeout (seconds) before forced cancellation.
    47	# Scheduler waits this long for in-flight polls to complete persist+publish.
    48	scheduler_drain_timeout_s: 5.0

exec
/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/base_plugin.py | sed -n '1,180p'; nl -ba /Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/plugin_loader.py | sed -n '1,260p'; nl -ba /Users/vladimir/Projects/cryodaq/config/plugins.yaml | sed -n '1,160p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	"""Базовые классы аналитического слоя CryoDAQ.
     2	
     3	Определяет DerivedMetric — результат вычисления плагина — и
     4	абстрактный класс AnalyticsPlugin, от которого наследуются все
     5	аналитические плагины (расчёт тепловых сопротивлений, прогноз
     6	времени охлаждения и т.д.).
     7	"""
     8	
     9	from __future__ import annotations
    10	
    11	from abc import ABC, abstractmethod
    12	from dataclasses import dataclass, field
    13	from datetime import UTC, datetime
    14	from typing import Any
    15	
    16	from cryodaq.drivers.base import Reading
    17	
    18	
    19	@dataclass(frozen=True, slots=True)
    20	class DerivedMetric:
    21	    """Производная метрика, вычисленная аналитическим плагином.
    22	
    23	    Неизменяемый объект — безопасен для передачи между сопрограммами.
    24	
    25	    Атрибуты:
    26	        timestamp:  Метка времени UTC момента вычисления.
    27	        plugin_id:  Уникальный идентификатор плагина-источника.
    28	        metric:     Имя метрики (например, ``"R_thermal"``, ``"cooldown_eta_s"``).
    29	        value:      Числовое значение метрики.
    30	        unit:       Единица измерения (например, ``"K/W"``, ``"s"``).
    31	        metadata:   Произвольные аннотации (параметры алгоритма, версия модели и т.п.).
    32	    """
    33	
    34	    timestamp: datetime
    35	    plugin_id: str
    36	    metric: str
    37	    value: float
    38	    unit: str
    39	    metadata: dict[str, Any] = field(default_factory=dict)
    40	
    41	    @staticmethod
    42	    def now(
    43	        plugin_id: str,
    44	        metric: str,
    45	        value: float,
    46	        unit: str,
    47	        **kwargs: Any,
    48	    ) -> DerivedMetric:
    49	        """Создать DerivedMetric с текущей меткой времени UTC.
    50	
    51	        Аргументы:
    52	            plugin_id:  Идентификатор плагина.
    53	            metric:     Имя метрики.
    54	            value:      Значение метрики.
    55	            unit:       Единица измерения.
    56	            **kwargs:   Дополнительные поля (например, ``metadata={}``).
    57	
    58	        Возвращает:
    59	            Экземпляр :class:`DerivedMetric` с ``timestamp = datetime.now(UTC)``.
    60	        """
    61	        return DerivedMetric(
    62	            timestamp=datetime.now(UTC),
    63	            plugin_id=plugin_id,
    64	            metric=metric,
    65	            value=value,
    66	            unit=unit,
    67	            **kwargs,
    68	        )
    69	
    70	
    71	class AnalyticsPlugin(ABC):
    72	    """Абстрактный аналитический плагин.
    73	
    74	    Каждый конкретный плагин наследует этот класс и реализует метод
    75	    :meth:`process`.  Жизненный цикл управляется :class:`PluginPipeline`:
    76	    загрузка из файловой системы, опциональная конфигурация через YAML,
    77	    горячая перезагрузка при изменении файла.
    78	
    79	    Пример минимального плагина::
    80	
    81	        class MyPlugin(AnalyticsPlugin):
    82	            async def process(self, readings):
    83	                ...
    84	                return [DerivedMetric.now(self.plugin_id, "my_metric", 42.0, "arb")]
    85	    """
    86	
    87	    def __init__(self, plugin_id: str) -> None:
    88	        """Инициализировать плагин.
    89	
    90	        Аргументы:
    91	            plugin_id:  Уникальный идентификатор плагина в рамках пайплайна.
    92	                        Обычно совпадает с именем файла без расширения.
    93	        """
    94	        self._plugin_id = plugin_id
    95	        self._config: dict[str, Any] = {}
    96	
    97	    @property
    98	    def plugin_id(self) -> str:
    99	        """Уникальный идентификатор плагина (только для чтения)."""
   100	        return self._plugin_id
   101	
   102	    @abstractmethod
   103	    async def process(self, readings: list[Reading]) -> list[DerivedMetric]:
   104	        """Обработать пакет показаний и вернуть производные метрики.
   105	
   106	        Вызывается :class:`PluginPipeline` на каждом интервале сбора данных.
   107	        Метод не должен генерировать исключения: внутренние ошибки следует
   108	        логировать и возвращать пустой список.
   109	
   110	        Аргументы:
   111	            readings:  Список :class:`~cryodaq.drivers.base.Reading`,
   112	                       накопленных за последний интервал.
   113	
   114	        Возвращает:
   115	            Список :class:`DerivedMetric`.  Допустимо вернуть пустой список,
   116	            если данных недостаточно для вычисления.
   117	        """
   118	
   119	    def configure(self, config: dict[str, Any]) -> None:
   120	        """Применить конфигурацию из YAML-файла.
   121	
   122	        Переопределите этот метод для валидации и разбора специфичных
   123	        параметров плагина.  Реализация по умолчанию просто сохраняет
   124	        словарь в ``self._config``.
   125	
   126	        Аргументы:
   127	            config:  Десериализованный словарь из YAML (``yaml.safe_load``).
   128	        """
   129	        self._config = config
     1	"""Загрузчик аналитических плагинов и управление пайплайном CryoDAQ.
     2	
     3	Модуль реализует:
     4	- динамическую загрузку плагинов из директории файловой системы;
     5	- горячую перезагрузку при изменении/добавлении/удалении .py-файлов;
     6	- сбор пакетов Reading от брокера и их передачу плагинам;
     7	- публикацию результатов (DerivedMetric) обратно в брокер как Reading.
     8	"""
     9	
    10	from __future__ import annotations
    11	
    12	import asyncio
    13	import importlib.util
    14	import inspect
    15	import logging
    16	import types
    17	from pathlib import Path
    18	from typing import Any
    19	
    20	import yaml
    21	
    22	from cryodaq.analytics.base_plugin import AnalyticsPlugin, DerivedMetric
    23	from cryodaq.core.broker import DataBroker
    24	from cryodaq.drivers.base import Reading
    25	
    26	logger = logging.getLogger(__name__)
    27	
    28	_MAX_BATCH_SIZE = 500
    29	_WATCH_INTERVAL_S = 5.0
    30	_SUBSCRIBE_NAME = "plugin_pipeline"
    31	
    32	
    33	class PluginPipeline:
    34	    """Пайплайн аналитических плагинов.
    35	
    36	    Управляет полным жизненным циклом плагинов: загрузка из директории,
    37	    конфигурирование через YAML, батчевая обработка потока Reading,
    38	    публикация производных метрик и горячая перезагрузка файлов.
    39	
    40	    Пример использования::
    41	
    42	        pipeline = PluginPipeline(broker, Path("plugins/"))
    43	        await pipeline.start()
    44	        ...
    45	        await pipeline.stop()
    46	    """
    47	
    48	    def __init__(
    49	        self,
    50	        broker: DataBroker,
    51	        plugins_dir: Path,
    52	        *,
    53	        batch_interval_s: float = 1.0,
    54	    ) -> None:
    55	        """Инициализировать пайплайн.
    56	
    57	        Аргументы:
    58	            broker:            Экземпляр :class:`~cryodaq.core.broker.DataBroker`.
    59	            plugins_dir:       Директория с файлами плагинов (``.py``).
    60	            batch_interval_s:  Интервал накопления пакета показаний в секундах.
    61	        """
    62	        self._broker = broker
    63	        self._plugins_dir = plugins_dir
    64	        self._plugins: dict[str, AnalyticsPlugin] = {}
    65	        self._batch_interval_s = batch_interval_s
    66	        self._queue: asyncio.Queue[Reading] | None = None
    67	        self._process_task: asyncio.Task[None] | None = None
    68	        self._watch_task: asyncio.Task[None] | None = None
    69	        self._running: bool = False
    70	
    71	    # ------------------------------------------------------------------
    72	    # Публичный API
    73	    # ------------------------------------------------------------------
    74	
    75	    async def start(self) -> None:
    76	        """Запустить пайплайн.
    77	
    78	        Подписывается на брокер, загружает все плагины из ``plugins_dir``,
    79	        затем запускает фоновые задачи обработки и слежения за файлами.
    80	        """
    81	        if self._running:
    82	            logger.warning("Пайплайн уже запущен — повторный вызов start() проигнорирован")
    83	            return
    84	
    85	        self._queue = await self._broker.subscribe(_SUBSCRIBE_NAME)
    86	        logger.info("Пайплайн подписан на брокер как '%s'", _SUBSCRIBE_NAME)
    87	
    88	        self._plugins_dir.mkdir(parents=True, exist_ok=True)
    89	        for path in sorted(self._plugins_dir.glob("*.py")):
    90	            self._load_plugin(path)
    91	
    92	        self._running = True
    93	        self._process_task = asyncio.create_task(
    94	            self._process_loop(), name="analytics_process_loop"
    95	        )
    96	        self._watch_task = asyncio.create_task(self._watch_loop(), name="analytics_watch_loop")
    97	        logger.info(
    98	            "Пайплайн запущен: загружено плагинов=%d, интервал=%.2f с",
    99	            len(self._plugins),
   100	            self._batch_interval_s,
   101	        )
   102	
   103	    async def stop(self) -> None:
   104	        """Остановить пайплайн.
   105	
   106	        Отменяет фоновые задачи и удаляет подписку в брокере.
   107	        """
   108	        self._running = False
   109	
   110	        for task in (self._process_task, self._watch_task):
   111	            if task and not task.done():
   112	                task.cancel()
   113	                try:
   114	                    await task
   115	                except asyncio.CancelledError:
   116	                    pass
   117	
   118	        self._process_task = None
   119	        self._watch_task = None
   120	
   121	        await self._broker.unsubscribe(_SUBSCRIBE_NAME)
   122	        self._queue = None
   123	        logger.info("Пайплайн остановлен")
   124	
   125	    # ------------------------------------------------------------------
   126	    # Загрузка / выгрузка плагинов
   127	    # ------------------------------------------------------------------
   128	
   129	    def _load_plugin(self, path: Path) -> None:
   130	        """Загрузить плагин из файла.
   131	
   132	        Импортирует модуль, находит первый конкретный подкласс
   133	        :class:`~cryodaq.analytics.base_plugin.AnalyticsPlugin`,
   134	        применяет YAML-конфиг (если есть) и регистрирует плагин.
   135	
   136	        Любая ошибка перехватывается — некорректный файл не останавливает
   137	        пайплайн.
   138	
   139	        Аргументы:
   140	            path:  Путь к ``.py``-файлу плагина.
   141	        """
   142	        try:
   143	            plugin_id = path.stem
   144	            spec = importlib.util.spec_from_file_location(f"cryodaq_plugin_{plugin_id}", path)
   145	            if spec is None or spec.loader is None:
   146	                logger.error("Не удалось создать spec для плагина '%s': %s", plugin_id, path)
   147	                return
   148	
   149	            module: types.ModuleType = importlib.util.module_from_spec(spec)
   150	            spec.loader.exec_module(module)  # type: ignore[union-attr]
   151	
   152	            plugin_cls: type[AnalyticsPlugin] | None = None
   153	            for _name, obj in inspect.getmembers(module, inspect.isclass):
   154	                if (
   155	                    issubclass(obj, AnalyticsPlugin)
   156	                    and obj is not AnalyticsPlugin
   157	                    and not inspect.isabstract(obj)
   158	                    and obj.__module__ == module.__name__
   159	                ):
   160	                    plugin_cls = obj
   161	                    break
   162	
   163	            if plugin_cls is None:
   164	                logger.warning(
   165	                    "Файл '%s' не содержит конкретного подкласса AnalyticsPlugin — пропущен",
   166	                    path,
   167	                )
   168	                return
   169	
   170	            # Плагин может определять __init__(self) без аргументов (с plugin_id
   171	            # как атрибутом класса) или __init__(self, plugin_id).
   172	            try:
   173	                plugin = plugin_cls(plugin_id)
   174	            except TypeError:
   175	                plugin = plugin_cls()
   176	                # Если плагин не задал plugin_id — установить принудительно
   177	                if plugin.plugin_id != plugin_id:
   178	                    plugin._plugin_id = plugin_id
   179	
   180	            config_path = path.with_suffix(".yaml")
   181	            if config_path.exists():
   182	                try:
   183	                    with config_path.open("r", encoding="utf-8") as fh:
   184	                        config: dict[str, Any] = yaml.safe_load(fh) or {}
   185	                    plugin.configure(config)
   186	                    logger.debug("Конфиг '%s' применён к плагину '%s'", config_path, plugin_id)
   187	                except Exception as cfg_exc:
   188	                    logger.error(
   189	                        "Ошибка загрузки конфига '%s' для плагина '%s': %s",
   190	                        config_path,
   191	                        plugin_id,
   192	                        cfg_exc,
   193	                    )
   194	
   195	            self._plugins[plugin_id] = plugin
   196	            logger.info(
   197	                "Плагин загружен: id='%s', класс=%s, файл=%s",
   198	                plugin_id,
   199	                plugin_cls.__name__,
   200	                path,
   201	            )
   202	
   203	        except Exception as exc:
   204	            logger.error("Критическая ошибка при загрузке плагина из '%s': %s", path, exc)
   205	
   206	    def _unload_plugin(self, plugin_id: str) -> None:
   207	        """Выгрузить плагин по идентификатору.
   208	
   209	        Аргументы:
   210	            plugin_id:  Идентификатор плагина (обычно имя файла без расширения).
   211	        """
   212	        removed = self._plugins.pop(plugin_id, None)
   213	        if removed is not None:
   214	            logger.info("Плагин выгружен: id='%s'", plugin_id)
   215	        else:
   216	            logger.debug("Попытка выгрузить незарегистрированный плагин '%s'", plugin_id)
   217	
   218	    # ------------------------------------------------------------------
   219	    # Фоновые задачи
   220	    # ------------------------------------------------------------------
   221	
   222	    async def _process_loop(self) -> None:
   223	        """Основной цикл обработки: накопление пакета и вызов плагинов.
   224	
   225	        На каждой итерации собирает Reading из очереди брокера в течение
   226	        ``batch_interval_s`` (не более ``_MAX_BATCH_SIZE`` элементов),
   227	        передаёт пакет каждому загруженному плагину и публикует
   228	        полученные :class:`~cryodaq.analytics.base_plugin.DerivedMetric`
   229	        обратно в брокер.
   230	        """
   231	        assert self._queue is not None, "Очередь не инициализирована — вызовите start()"
   232	
   233	        while self._running:
   234	            batch: list[Reading] = []
   235	            deadline = asyncio.get_event_loop().time() + self._batch_interval_s
   236	
   237	            # Накапливаем пакет до истечения интервала или достижения лимита
   238	            while len(batch) < _MAX_BATCH_SIZE:
   239	                remaining = deadline - asyncio.get_event_loop().time()
   240	                if remaining <= 0:
   241	                    break
   242	                try:
   243	                    reading = await asyncio.wait_for(self._queue.get(), timeout=remaining)
   244	                    batch.append(reading)
   245	                except TimeoutError:
   246	                    break
   247	                except asyncio.CancelledError:
   248	                    return
   249	
   250	            if not batch:
   251	                continue
   252	
   253	            # Передаём пакет каждому плагину
   254	            for plugin in list(self._plugins.values()):
   255	                plugin_id = plugin.plugin_id
   256	                try:
   257	                    metrics: list[DerivedMetric] = await plugin.process(batch)
   258	                except Exception as exc:
   259	                    logger.error(
   260	                        "Плагин '%s' выбросил исключение при обработке пакета: %s",
     1	sensor_diagnostics:
     2	  enabled: true
     3	  update_interval_s: 10
     4	  noise_window_s: 120
     5	  drift_window_s: 600
     6	  outlier_window_s: 300
     7	  correlation_window_s: 600
     8	  min_points: 10
     9	  thresholds:
    10	    noise_cold_K: 0.02        # T < 30K (DT-670 high sensitivity zone)
    11	    noise_mid1_K: 0.05        # 30-100K
    12	    noise_mid2_K: 0.1         # 100-200K
    13	    noise_warm_K: 0.2         # T > 200K
    14	    drift_K_per_min: 0.1      # absolute drift threshold
    15	    outlier_sigma: 5.0        # outlier = deviation > 5σ from median
    16	    correlation_min: 0.8      # flag uncorrelated below this
    17	    health_warning: 50
    18	    health_critical: 30
    19	  correlation_groups:
    20	    shield:    [Т1, Т2, Т3, Т4, Т5, Т6, Т7, Т8]
    21	    cold:      [Т9, Т10, Т11, Т12, Т13, Т14]
    22	    periphery: [Т15, Т16, Т17, Т18, Т19, Т20]
    23	
    24	vacuum_trend:
    25	  enabled: true
    26	  window_s: 3600                           # data window for fitting (s)
    27	  update_interval_s: 30                    # refit interval (s)
    28	  min_points: 60                           # minimum points for fit
    29	  min_points_combined: 200                 # minimum for 5-param combined model
    30	  targets_mbar:
    31	    - 1.0e-4
    32	    - 1.0e-5
    33	    - 1.0e-6
    34	  anomaly_threshold_sigma: 3.0
    35	  rising_sustained_s: 60                   # sustained rise before "rising" flag
    36	  trend_threshold_log10_per_s: 1.0e-4     # d(log₁₀P)/dt threshold
    37	  extrapolation_horizon_factor: 2.0       # extrapolate 2× window ahead
    38	  pressure_channel: ""                     # auto-detect any mbar-unit reading

exec
/opt/homebrew/bin/bash -lc 'rg -n "class CalibrationStore|export_curve|export_curve_330|export_curve_340|generate_breakpoints|CalibrationFitter|CalibrationFitResult|max_time_delta|read_srdg|runtime|calibration|fallback|_runtime_warning_cache|on_srdg_persisted|prepare_srdg|t_min|t_max|one transaction" /Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py /Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration_fitter.py /Users/vladimir/Projects/cryodaq/src/cryodaq/core/calibration_acquisition.py /Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py /Users/vladimir/Projects/cryodaq/README.md /Users/vladimir/Projects/cryodaq/CLAUDE.md -S' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
/Users/vladimir/Projects/cryodaq/CLAUDE.md:44:- Calibration v2: continuous SRDG acquisition during calibration experiments (CalibrationAcquisitionService), post-run pipeline (CalibrationFitter: extract → downsample → breakpoints → Chebyshev fit), three-mode GUI (Setup → Acquisition → Results), `.330` / `.340` / JSON export, runtime apply с per-channel policy.
/Users/vladimir/Projects/cryodaq/CLAUDE.md:52:pip install -e ".[dev,web]"    # Install runtime, dev, and optional web dependencies
/Users/vladimir/Projects/cryodaq/CLAUDE.md:87:Три основных runtime-контура:
/Users/vladimir/Projects/cryodaq/CLAUDE.md:89:- `cryodaq-engine` — headless asyncio runtime: acquisition, safety, storage, commands
/Users/vladimir/Projects/cryodaq/CLAUDE.md:166:- `src/cryodaq/paths.py` — runtime path resolution (CRYODAQ_ROOT, frozen vs source layout)
/Users/vladimir/Projects/cryodaq/CLAUDE.md:176:- `src/cryodaq/core/calibration_acquisition.py` — непрерывный сбор SRDG при калибровке
/Users/vladimir/Projects/cryodaq/CLAUDE.md:199:- `src/cryodaq/analytics/calibration.py` — CalibrationStore, Chebyshev fit, runtime policy
/Users/vladimir/Projects/cryodaq/CLAUDE.md:200:- `src/cryodaq/analytics/calibration_fitter.py` — post-run pipeline (extract, downsample, breakpoints, fit)
/Users/vladimir/Projects/cryodaq/CLAUDE.md:238:- `src/cryodaq/gui/shell/overlays/_design_system/bento_grid.py` — grid layout (12-col runtime; 8-col canonical target per design-system)
/Users/vladimir/Projects/cryodaq/CLAUDE.md:266:`MainWindow`-era overlays (alarm / archive / calibration / conductivity
/Users/vladimir/Projects/cryodaq/CLAUDE.md:346:- GUI — отдельный процесс и не должен быть источником истины для runtime state.
/Users/vladimir/Projects/cryodaq/CLAUDE.md:412:   - Operator memory — последний fallback, не primary source
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration_fitter.py:15:from cryodaq.analytics.calibration import CalibrationCurve, CalibrationSample, CalibrationStore
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration_fitter.py:21:class CalibrationFitResult:
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration_fitter.py:34:class CalibrationFitter:
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration_fitter.py:35:    """Post-run calibration pipeline: extract → downsample → breakpoints → fit."""
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration_fitter.py:49:        max_time_delta_s: float = 2.0,
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration_fitter.py:108:            if best_delta > max_time_delta_s:
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration_fitter.py:196:    def generate_breakpoints(
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration_fitter.py:265:        t_min, t_max = min(temps), max(temps)
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration_fitter.py:266:        if t_max - t_min < 0.1:
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration_fitter.py:269:                    "temp_min": t_min,
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration_fitter.py:270:                    "temp_max": t_max,
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration_fitter.py:277:        bin_edges = np.linspace(t_min, t_max, n_bins + 1)
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration_fitter.py:318:        calibration_store: CalibrationStore,
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration_fitter.py:325:    ) -> CalibrationFitResult:
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration_fitter.py:339:                f"Not enough calibration pairs: {len(raw_pairs)} "
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration_fitter.py:347:        breakpoints = self.generate_breakpoints(
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration_fitter.py:366:        curve = calibration_store.fit_curve(
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration_fitter.py:373:        calibration_store.save_curve(curve)
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration_fitter.py:379:                predicted = calibration_store.evaluate(sensor_id, srdg_val)
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration_fitter.py:394:        return CalibrationFitResult(
/Users/vladimir/Projects/cryodaq/README.md:9:- Calibration v2: непрерывный сбор SRDG при калибровочных экспериментах, post-run pipeline (extract → downsample → Chebyshev fit), `.330` / `.340` export, runtime apply с global/per-channel policy.
/Users/vladimir/Projects/cryodaq/README.md:11:CryoDAQ — система сбора данных и управления для криогенной лаборатории АКЦ ФИАН (проект Millimetron). Полнофункциональная система с experiment/report/archive/operator-log/calibration/housekeeping/shift-handover workflow.
/Users/vladimir/Projects/cryodaq/README.md:15:- `cryodaq-engine` — headless runtime-процесс. Он опрашивает приборы, проверяет safety/alarm/interlock-логику, пишет данные и обслуживает GUI-команды.
/Users/vladimir/Projects/cryodaq/README.md:45:### Legacy MainWindow (fallback, до блока B.7)
/Users/vladimir/Projects/cryodaq/README.md:74:- dual-channel Keithley 2604B runtime для `smua`, `smub` и `smua + smub`
/Users/vladimir/Projects/cryodaq/README.md:80:- calibration backend:
/Users/vladimir/Projects/cryodaq/README.md:82:  - calibration sessions
/Users/vladimir/Projects/cryodaq/README.md:85:- calibration GUI для capture / fit / export
/Users/vladimir/Projects/cryodaq/README.md:102:Минимальная runtime-установка без dev/web extras:
/Users/vladimir/Projects/cryodaq/README.md:116:Ключевые runtime-зависимости из `pyproject.toml`:
/Users/vladimir/Projects/cryodaq/README.md:179:- `config/experiment_templates/calibration.yaml`
/Users/vladimir/Projects/cryodaq/README.md:198:data/calibration/sessions/<session_id>/
/Users/vladimir/Projects/cryodaq/README.md:199:data/calibration/curves/<sensor_id>/<curve_id>/
/Users/vladimir/Projects/cryodaq/README.md:207:Основой для генерации отчёта служат архивная карточка эксперимента и её артефакты; для части данных текущий contour всё ещё может использовать fallback-чтение из SQLite.
/Users/vladimir/Projects/cryodaq/README.md:244:  analytics/          # calibration fitter, cooldown, plugins, vacuum trend
/Users/vladimir/Projects/cryodaq/README.md:263:- `src/cryodaq/gui/main_window.py` — legacy 10-tab shell (fallback)
/Users/vladimir/Projects/cryodaq/README.md:264:- `src/cryodaq/gui/widgets/calibration_panel.py`
/Users/vladimir/Projects/cryodaq/README.md:285:- Runtime calibration policy реализована: глобальный режим `on/off` и per-channel policy переключают `KRDG` / `SRDG + curve`. При отсутствии curve, assignment, `SRDG` или ошибке вычисления backend консервативно возвращается к `KRDG`; поведение на живом LakeShore требует отдельной lab verification.
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/calibration_acquisition.py:1:"""Continuous SRDG acquisition during calibration experiments."""
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/calibration_acquisition.py:16:    """Raised when a calibration command cannot be executed due to invalid parameters."""
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/calibration_acquisition.py:20:    """Records SRDG readings alongside normal KRDG during calibration runs.
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/calibration_acquisition.py:22:    Activated when an experiment with ``calibration_acquisition: true``
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/calibration_acquisition.py:34:        self._t_min: float | None = None
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/calibration_acquisition.py:35:        self._t_max: float | None = None
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/calibration_acquisition.py:53:        self._t_min = None
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/calibration_acquisition.py:54:        self._t_max = None
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/calibration_acquisition.py:67:                self._t_min or 0,
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/calibration_acquisition.py:68:                self._t_max or 0,
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/calibration_acquisition.py:81:            "t_min": self._t_min,
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/calibration_acquisition.py:82:            "t_max": self._t_max,
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/calibration_acquisition.py:87:    def prepare_srdg_readings(
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/calibration_acquisition.py:95:        The scheduler must call on_srdg_persisted with the returned
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/calibration_acquisition.py:97:        deferred so that a write failure does not leave t_min/t_max
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/calibration_acquisition.py:106:        # Compute pending t_min/t_max WITHOUT applying yet
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/calibration_acquisition.py:113:                cur_min = self._t_min if "t_min" not in pending else pending["t_min"]
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/calibration_acquisition.py:115:                    pending["t_min"] = t
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/calibration_acquisition.py:116:                cur_max = self._t_max if "t_max" not in pending else pending["t_max"]
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/calibration_acquisition.py:118:                    pending["t_max"] = t
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/calibration_acquisition.py:139:                        "reading_kind": "calibration_srdg",
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/calibration_acquisition.py:147:    def on_srdg_persisted(
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/calibration_acquisition.py:155:            if "t_min" in pending_state:
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/calibration_acquisition.py:156:                new = pending_state["t_min"]
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/calibration_acquisition.py:157:                if self._t_min is None or new < self._t_min:
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/calibration_acquisition.py:158:                    self._t_min = new
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/calibration_acquisition.py:159:            if "t_max" in pending_state:
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/calibration_acquisition.py:160:                new = pending_state["t_max"]
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/calibration_acquisition.py:161:                if self._t_max is None or new > self._t_max:
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/calibration_acquisition.py:162:                    self._t_max = new
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/calibration_acquisition.py:169:        """Deprecated: use prepare_srdg_readings + on_srdg_persisted.
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/calibration_acquisition.py:177:            "on_readings is deprecated; use prepare_srdg_readings + on_srdg_persisted",
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/calibration_acquisition.py:184:        to_write, pending_state = self.prepare_srdg_readings(krdg, srdg)
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/calibration_acquisition.py:187:            self.on_srdg_persisted(len(to_write), pending_state)
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:194:class CalibrationStore:
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:207:        self._runtime_settings: dict[str, Any] = {
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:229:            raise ValueError("sensor_id is required for calibration fit.")
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:231:            raise ValueError("Not enough calibration samples for fitting.")
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:237:            raise ValueError("Not enough calibration samples for fitting after preprocessing.")
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:389:            raise ValueError(f"Unsupported calibration import format: {path.suffix}")
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:395:                runtime_apply_ready=False,
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:400:    def export_curve_json(self, sensor_id: str, path: Path | None = None) -> Path:
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:404:    def export_curve_table(
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:424:    def export_curve_330(
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:439:    def export_curve_340(
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:502:    def get_runtime_settings(self) -> dict[str, Any]:
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:506:            resolution = self.resolve_runtime_policy(channel_key=channel_key) if channel_key else {}
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:514:            "global_mode": str(self._runtime_settings.get("global_mode", "off") or "off"),
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:515:            "updated_at": str(self._runtime_settings.get("updated_at", "")).strip(),
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:519:    def set_runtime_global_mode(self, mode: str) -> dict[str, Any]:
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:522:            raise ValueError("Runtime calibration global_mode must be 'off' or 'on'.")
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:523:        self._runtime_settings["global_mode"] = normalized
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:524:        self._runtime_settings["updated_at"] = _utcnow().isoformat()
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:526:        return self.get_runtime_settings()
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:528:    def set_runtime_channel_policy(
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:535:        runtime_apply_ready: bool | None = None,
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:542:            raise ValueError("Channel runtime policy must be 'inherit', 'off', or 'on'.")
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:550:        if runtime_apply_ready is not None:
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:551:            assignment["runtime_apply_ready"] = bool(runtime_apply_ready)
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:556:            "resolution": self.resolve_runtime_policy(channel_key=normalized_channel_key),
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:559:    def resolve_runtime_policy(
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:567:        global_mode = str(self._runtime_settings.get("global_mode", "off") or "off")
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:607:        if not bool(assignment.get("runtime_apply_ready", False)):
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:614:                "reason": "not_runtime_ready",
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:646:        runtime_apply_ready: bool = False,
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:658:            "runtime_apply_ready": bool(runtime_apply_ready),
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:738:        runtime = payload.get("runtime", {})
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:739:        if isinstance(runtime, dict):
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:740:            global_mode = str(runtime.get("global_mode", "off") or "off").strip().lower()
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:742:                self._runtime_settings["global_mode"] = global_mode
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:743:            self._runtime_settings["updated_at"] = str(runtime.get("updated_at", "")).strip()
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:756:                        "runtime_apply_ready": bool(item.get("runtime_apply_ready", False)),
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:772:            "runtime": {
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:773:                "global_mode": str(self._runtime_settings.get("global_mode", "off") or "off"),
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:774:                "updated_at": str(self._runtime_settings.get("updated_at", "")).strip(),
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:820:            "runtime_apply_ready": False,
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:861:            handle.write(f"# CryoDAQ calibration curve export .{format_name}\n")
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:929:            self.export_curve_330(curve.sensor_id)
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:931:            self.export_curve_340(curve.sensor_id)
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:948:            raise ValueError("Not enough finite calibration samples for fitting.")
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:1120:            raise RuntimeError("Failed to fit calibration zone: degenerate input range.")
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:1130:            fallback_max = min(max_order, max(1, len(ordered_raw) - 1))
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:1131:            candidate_orders = list(range(1, fallback_max + 1))
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py:1146:            raise RuntimeError("Failed to fit calibration zone.")
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:1:"""LakeShore 218S driver with optional runtime calibration routing."""
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:11:from cryodaq.analytics.calibration import CalibrationStore
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:32:        calibration_store: CalibrationStore | None = None,
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:39:        self._calibration_store = calibration_store
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:40:        self._runtime_warning_cache: set[tuple[str, str]] = set()
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:57:            # Phase 2c Codex F.1: validate IDN with retry-after-clear fallback.
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:58:            # The previous fallback (log a warning and proceed) allowed silent
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:125:        runtime_policies = self._runtime_channel_policies()
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:126:        if not runtime_policies:
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:131:                policy.get("reading_mode") == "curve" for policy in runtime_policies.values()
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:133:            raw_readings = await self.read_srdg_channels() if needs_curve else []
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:134:            readings = self._merge_runtime_readings(
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:135:                temperature_readings, raw_readings, runtime_policies
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:170:                "%s: KRDG? returned %d values (expected 8), fallback #%d",
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:245:    async def read_srdg_channels(self) -> list[Reading]:
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:252:            return await self._read_srdg_per_channel()
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:260:                "%s: SRDG? returned %d values (expected 8), fallback #%d",
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:272:            return await self._read_srdg_per_channel()
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:276:    async def _read_srdg_per_channel(self) -> list[Reading]:
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:354:    async def read_calibration_pair(
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:361:        raw_readings = await self.read_srdg_channels()
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:465:    def _runtime_channel_policies(self) -> dict[int, dict[str, Any]]:
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:466:        if self._calibration_store is None:
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:471:            channel_key = self._runtime_channel_key(channel_name)
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:472:            resolution = self._calibration_store.resolve_runtime_policy(channel_key=channel_key)
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:481:                self._log_runtime_fallback(channel_key=channel_key, reason=reason)
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:484:    def _merge_runtime_readings(
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:504:                    self._with_runtime_metadata(
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:510:                        runtime_reason=str(policy.get("reason", "krdg_default")),
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:517:                self._log_runtime_fallback(
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:521:                    self._with_runtime_metadata(
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:527:                        runtime_reason="missing_srdg",
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:534:                calibrated_value = self._calibration_store.evaluate(
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:538:                self._log_runtime_fallback(
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:542:                    self._with_runtime_metadata(
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:548:                        runtime_reason="curve_evaluate_failed",
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:573:    def _with_runtime_metadata(
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:581:        runtime_reason: str,
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:597:                "runtime_reason": runtime_reason,
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:601:    def _runtime_channel_key(self, channel_name: str) -> str:
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:604:    def _log_runtime_fallback(self, *, channel_key: str, reason: str) -> None:
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:606:        if cache_key in self._runtime_warning_cache:
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:608:        self._runtime_warning_cache.add(cache_key)
/Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py:609:        log.warning("%s: runtime calibration fallback for %s (%s)", self.name, channel_key, reason)

exec
/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/plugin_loader.py | sed -n '253,360p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   253	            # Передаём пакет каждому плагину
   254	            for plugin in list(self._plugins.values()):
   255	                plugin_id = plugin.plugin_id
   256	                try:
   257	                    metrics: list[DerivedMetric] = await plugin.process(batch)
   258	                except Exception as exc:
   259	                    logger.error(
   260	                        "Плагин '%s' выбросил исключение при обработке пакета: %s",
   261	                        plugin_id,
   262	                        exc,
   263	                    )
   264	                    continue
   265	
   266	                for metric in metrics:
   267	                    reading = Reading.now(
   268	                        channel=f"analytics/{plugin_id}/{metric.metric}",
   269	                        value=metric.value,
   270	                        unit=metric.unit,
   271	                        instrument_id=plugin_id,
   272	                        metadata=metric.metadata
   273	                        | {
   274	                            "source": "analytics",
   275	                            "plugin_id": plugin_id,
   276	                        },
   277	                    )
   278	                    await self._broker.publish(reading)
   279	
   280	    async def _watch_loop(self) -> None:
   281	        """Цикл слежения за директорией плагинов (горячая перезагрузка).
   282	
   283	        Каждые ``_WATCH_INTERVAL_S`` секунд сравнивает текущие mtime
   284	        файлов с ранее сохранёнными:
   285	
   286	        - новый файл → :meth:`_load_plugin`;
   287	        - изменённый файл (mtime отличается) → :meth:`_unload_plugin`
   288	          + :meth:`_load_plugin`;
   289	        - удалённый файл → :meth:`_unload_plugin`.
   290	
   291	        Ошибки в цикле перехватываются — сбой слежения не влияет на
   292	        обработку данных.
   293	        """
   294	        known_files: dict[str, float] = self._scan_plugins()
   295	
   296	        while self._running:
   297	            try:
   298	                await asyncio.sleep(_WATCH_INTERVAL_S)
   299	
   300	                current_files = self._scan_plugins()
   301	
   302	                # Новые или изменённые файлы
   303	                for filename, mtime in current_files.items():
   304	                    if filename not in known_files:
   305	                        logger.info("Обнаружен новый файл плагина: %s", filename)
   306	                        self._load_plugin(self._plugins_dir / filename)
   307	                    elif known_files[filename] != mtime:
   308	                        logger.info("Файл плагина изменён, перезагрузка: %s", filename)
   309	                        self._unload_plugin(Path(filename).stem)
   310	                        self._load_plugin(self._plugins_dir / filename)
   311	
   312	                # Удалённые файлы
   313	                for filename in list(known_files.keys()):
   314	                    if filename not in current_files:
   315	                        logger.info("Файл плагина удалён: %s", filename)
   316	                        self._unload_plugin(Path(filename).stem)
   317	
   318	                known_files = current_files
   319	
   320	            except asyncio.CancelledError:
   321	                return
   322	            except Exception as exc:
   323	                logger.error("Ошибка в цикле слежения за плагинами: %s — продолжаю работу", exc)
   324	
   325	    # ------------------------------------------------------------------
   326	    # Вспомогательные методы
   327	    # ------------------------------------------------------------------
   328	
   329	    def _scan_plugins(self) -> dict[str, float]:
   330	        """Собрать mtime всех .py-файлов в директории плагинов.
   331	
   332	        Возвращает:
   333	            Словарь ``{имя_файла: mtime}`` для каждого ``.py``-файла
   334	            в ``plugins_dir``.  При ошибке доступа к файловой системе
   335	            возвращает пустой словарь.
   336	        """
   337	        try:
   338	            return {
   339	                path.name: path.stat().st_mtime
   340	                for path in self._plugins_dir.glob("*.py")
   341	                if path.is_file()
   342	            }
   343	        except Exception as exc:
   344	            logger.error(
   345	                "Ошибка сканирования директории плагинов '%s': %s",
   346	                self._plugins_dir,
   347	                exc,
   348	            )
   349	            return {}

exec
/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/lakeshore_218s.py | sed -n '38,75p;120,140p;465,615p'" in /Users/vladimir/Projects/cryodaq
exec
/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Projects/cryodaq/src/cryodaq/core/calibration_acquisition.py | sed -n '20,170p'; nl -ba /Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration_fitter.py | sed -n '34,70p;196,230p;318,400p'; nl -ba /Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py | sed -n '400,455p;519,615p;861,940p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
    38	        self._instrument_id: str = ""
    39	        self._calibration_store = calibration_store
    40	        self._runtime_warning_cache: set[tuple[str, str]] = set()
    41	        self._use_per_channel_krdg: bool = False
    42	        self._use_per_channel_srdg: bool = False
    43	        self._krdg0_fail_count: int = 0
    44	        self._srdg0_fail_count: int = 0
    45	        self._krdg_batch_retry_interval_s: float = 60.0
    46	        self._srdg_batch_retry_interval_s: float = 60.0
    47	        self._krdg_last_batch_retry: float = 0.0
    48	        self._srdg_last_batch_retry: float = 0.0
    49	        self._last_status_check: float = 0.0
    50	        self._last_status_result: dict[int, int] = {}
    51	
    52	    async def connect(self) -> None:
    53	        log.info("%s: connecting to %s", self.name, self._resource_str)
    54	        await self._transport.open(self._resource_str)
    55	
    56	        if not self.mock:
    57	            # Phase 2c Codex F.1: validate IDN with retry-after-clear fallback.
    58	            # The previous fallback (log a warning and proceed) allowed silent
    59	            # mis-routing to a wrong GPIB address — KRDG? would still produce
    60	            # numbers, just from the wrong instrument.
    61	            idn_valid = False
    62	            idn_raw = ""
    63	
    64	            for attempt in range(2):  # initial + one retry after device clear
    65	                try:
    66	                    idn_raw = (await self._transport.query("*IDN?")).strip()
    67	                except Exception as exc:
    68	                    log.warning(
    69	                        "%s: *IDN? query failed (attempt %d/2): %s",
    70	                        self.name,
    71	                        attempt + 1,
    72	                        exc,
    73	                    )
    74	                    idn_raw = ""
    75	
   120	
   121	    async def read_channels(self) -> list[Reading]:
   122	        if not self._connected:
   123	            raise RuntimeError(f"{self.name}: instrument is not connected")
   124	
   125	        runtime_policies = self._runtime_channel_policies()
   126	        if not runtime_policies:
   127	            readings = await self._read_krdg_channels()
   128	        else:
   129	            temperature_readings = await self._read_krdg_channels()
   130	            needs_curve = any(
   131	                policy.get("reading_mode") == "curve" for policy in runtime_policies.values()
   132	            )
   133	            raw_readings = await self.read_srdg_channels() if needs_curve else []
   134	            readings = self._merge_runtime_readings(
   135	                temperature_readings, raw_readings, runtime_policies
   136	            )
   137	
   138	        # Periodic RDGST? status check (every 60s)
   139	        now = _time.monotonic()
   140	        if not self.mock and now - self._last_status_check > 60.0:
   465	    def _runtime_channel_policies(self) -> dict[int, dict[str, Any]]:
   466	        if self._calibration_store is None:
   467	            return {}
   468	        policies: dict[int, dict[str, Any]] = {}
   469	        for channel_num in range(1, 9):
   470	            channel_name = self._channel_labels.get(channel_num, f"CH{channel_num}")
   471	            channel_key = self._runtime_channel_key(channel_name)
   472	            resolution = self._calibration_store.resolve_runtime_policy(channel_key=channel_key)
   473	            policies[channel_num] = resolution
   474	            reason = str(resolution.get("reason", ""))
   475	            if resolution.get("reading_mode") != "curve" and reason not in {
   476	                "global_off",
   477	                "channel_off",
   478	                "missing_assignment",
   479	                "",
   480	            }:
   481	                self._log_runtime_fallback(channel_key=channel_key, reason=reason)
   482	        return policies
   483	
   484	    def _merge_runtime_readings(
   485	        self,
   486	        temperature_readings: list[Reading],
   487	        raw_readings: list[Reading],
   488	        policies: dict[int, dict[str, Any]],
   489	    ) -> list[Reading]:
   490	        raw_by_channel = {
   491	            int(reading.metadata.get("raw_channel", 0)): reading
   492	            for reading in raw_readings
   493	            if int(reading.metadata.get("raw_channel", 0)) > 0
   494	        }
   495	        merged: list[Reading] = []
   496	        for reading in temperature_readings:
   497	            channel_num = int(reading.metadata.get("raw_channel", 0))
   498	            policy = policies.get(channel_num) or {}
   499	            assignment = (
   500	                policy.get("assignment") if isinstance(policy.get("assignment"), dict) else {}
   501	            )
   502	            if policy.get("reading_mode") != "curve":
   503	                merged.append(
   504	                    self._with_runtime_metadata(
   505	                        reading,
   506	                        reading_mode="krdg",
   507	                        raw_source="KRDG",
   508	                        curve_id=assignment.get("curve_id"),
   509	                        sensor_id=assignment.get("sensor_id"),
   510	                        runtime_reason=str(policy.get("reason", "krdg_default")),
   511	                    )
   512	                )
   513	                continue
   514	
   515	            raw_reading = raw_by_channel.get(channel_num)
   516	            if raw_reading is None or raw_reading.status is not ChannelStatus.OK:
   517	                self._log_runtime_fallback(
   518	                    channel_key=str(policy.get("channel_key", "")), reason="missing_srdg"
   519	                )
   520	                merged.append(
   521	                    self._with_runtime_metadata(
   522	                        reading,
   523	                        reading_mode="krdg",
   524	                        raw_source="KRDG",
   525	                        curve_id=assignment.get("curve_id"),
   526	                        sensor_id=assignment.get("sensor_id"),
   527	                        runtime_reason="missing_srdg",
   528	                    )
   529	                )
   530	                continue
   531	
   532	            sensor_id = str(assignment.get("sensor_id", "")).strip()
   533	            try:
   534	                calibrated_value = self._calibration_store.evaluate(
   535	                    sensor_id, float(raw_reading.value)
   536	                )  # type: ignore[union-attr]
   537	            except Exception:
   538	                self._log_runtime_fallback(
   539	                    channel_key=str(policy.get("channel_key", "")), reason="curve_evaluate_failed"
   540	                )
   541	                merged.append(
   542	                    self._with_runtime_metadata(
   543	                        reading,
   544	                        reading_mode="krdg",
   545	                        raw_source="KRDG",
   546	                        curve_id=assignment.get("curve_id"),
   547	                        sensor_id=assignment.get("sensor_id"),
   548	                        runtime_reason="curve_evaluate_failed",
   549	                    )
   550	                )
   551	                continue
   552	
   553	            merged.append(
   554	                Reading(
   555	                    timestamp=reading.timestamp,
   556	                    instrument_id=reading.instrument_id,
   557	                    channel=reading.channel,
   558	                    value=float(calibrated_value),
   559	                    unit="K",
   560	                    status=ChannelStatus.OK,
   561	                    raw=float(raw_reading.value),
   562	                    metadata={
   563	                        **reading.metadata,
   564	                        "reading_mode": "curve",
   565	                        "raw_source": "SRDG",
   566	                        "curve_id": assignment.get("curve_id"),
   567	                        "sensor_id": assignment.get("sensor_id"),
   568	                    },
   569	                )
   570	            )
   571	        return merged
   572	
   573	    def _with_runtime_metadata(
   574	        self,
   575	        reading: Reading,
   576	        *,
   577	        reading_mode: str,
   578	        raw_source: str,
   579	        curve_id: Any,
   580	        sensor_id: Any,
   581	        runtime_reason: str,
   582	    ) -> Reading:
   583	        return Reading(
   584	            timestamp=reading.timestamp,
   585	            instrument_id=reading.instrument_id,
   586	            channel=reading.channel,
   587	            value=reading.value,
   588	            unit=reading.unit,
   589	            status=reading.status,
   590	            raw=reading.raw,
   591	            metadata={
   592	                **reading.metadata,
   593	                "reading_mode": reading_mode,
   594	                "raw_source": raw_source,
   595	                "curve_id": curve_id,
   596	                "sensor_id": sensor_id,
   597	                "runtime_reason": runtime_reason,
   598	            },
   599	        )
   600	
   601	    def _runtime_channel_key(self, channel_name: str) -> str:
   602	        return f"{self.name}:{channel_name}"
   603	
   604	    def _log_runtime_fallback(self, *, channel_key: str, reason: str) -> None:
   605	        cache_key = (channel_key, reason)
   606	        if cache_key in self._runtime_warning_cache:
   607	            return
   608	        self._runtime_warning_cache.add(cache_key)
   609	        log.warning("%s: runtime calibration fallback for %s (%s)", self.name, channel_key, reason)
   610	
   611	    def _resolve_channel_reading(
   612	        self,
   613	        readings: list[Reading],
   614	        channel_spec: int | str,
   615	    ) -> Reading:

 succeeded in 0ms:
    20	    """Records SRDG readings alongside normal KRDG during calibration runs.
    21	
    22	    Activated when an experiment with ``calibration_acquisition: true``
    23	    starts, deactivated when the experiment ends.  The scheduler calls
    24	    :meth:`on_readings` after each LakeShore poll cycle.
    25	    """
    26	
    27	    def __init__(self, writer: Any, channel_manager: Any = None) -> None:
    28	        self._writer = writer
    29	        self._channel_manager = channel_manager
    30	        self._active = False
    31	        self._reference_channel: str | None = None
    32	        self._target_channels: list[str] = []
    33	        self._point_count = 0
    34	        self._t_min: float | None = None
    35	        self._t_max: float | None = None
    36	
    37	    def _resolve(self, reference: str) -> str:
    38	        """Canonicalize a channel reference via ChannelManager."""
    39	        try:
    40	            return self._channel_manager.resolve_channel_reference(reference)
    41	        except ChannelConfigError as e:
    42	            raise CalibrationCommandError(f"cannot resolve channel reference: {e}") from e
    43	
    44	    def activate(self, reference_channel: str, target_channels: list[str]) -> None:
    45	        """Start recording SRDG for *target_channels*."""
    46	        if self._channel_manager is not None:
    47	            reference_channel = self._resolve(reference_channel)
    48	            target_channels = [self._resolve(t) for t in target_channels]
    49	        self._active = True
    50	        self._reference_channel = reference_channel
    51	        self._target_channels = list(target_channels)
    52	        self._point_count = 0
    53	        self._t_min = None
    54	        self._t_max = None
    55	        logger.info(
    56	            "Calibration acquisition activated: ref=%s targets=%s",
    57	            reference_channel,
    58	            target_channels,
    59	        )
    60	
    61	    def deactivate(self) -> None:
    62	        """Stop recording SRDG."""
    63	        if self._active:
    64	            logger.info(
    65	                "Calibration acquisition deactivated (%d points, T %.1f–%.1f K)",
    66	                self._point_count,
    67	                self._t_min or 0,
    68	                self._t_max or 0,
    69	            )
    70	        self._active = False
    71	
    72	    @property
    73	    def is_active(self) -> bool:
    74	        return self._active
    75	
    76	    @property
    77	    def stats(self) -> dict[str, Any]:
    78	        return {
    79	            "active": self._active,
    80	            "point_count": self._point_count,
    81	            "t_min": self._t_min,
    82	            "t_max": self._t_max,
    83	            "reference_channel": self._reference_channel,
    84	            "target_channels": self._target_channels,
    85	        }
    86	
    87	    def prepare_srdg_readings(
    88	        self,
    89	        krdg: list[Reading],
    90	        srdg: list[Reading],
    91	    ) -> tuple[list[Reading], dict[str, float] | None]:
    92	        """Prepare SRDG readings for persistence (H.10: atomic with KRDG).
    93	
    94	        Computes (but does NOT apply) pending temperature range updates.
    95	        The scheduler must call on_srdg_persisted with the returned
    96	        pending_state AFTER write_immediate succeeds. State mutation is
    97	        deferred so that a write failure does not leave t_min/t_max
    98	        diverged from actual persisted data (Jules Round 2 Q3).
    99	
   100	        Returns:
   101	            (readings_to_persist, pending_state)
   102	        """
   103	        if not self._active:
   104	            return ([], None)
   105	
   106	        # Compute pending t_min/t_max WITHOUT applying yet
   107	        pending: dict[str, float] = {}
   108	        for r in krdg:
   109	            if r.channel == self._reference_channel and r.status == ChannelStatus.OK:
   110	                t = r.value
   111	                if not math.isfinite(t) or t < 1.0:
   112	                    continue
   113	                cur_min = self._t_min if "t_min" not in pending else pending["t_min"]
   114	                if cur_min is None or t < cur_min:
   115	                    pending["t_min"] = t
   116	                cur_max = self._t_max if "t_max" not in pending else pending["t_max"]
   117	                if cur_max is None or t > cur_max:
   118	                    pending["t_max"] = t
   119	
   120	        # Build SRDG readings for target channels
   121	        to_write: list[Reading] = []
   122	        for reading in srdg:
   123	            if reading.channel not in self._target_channels:
   124	                continue
   125	            if reading.status != ChannelStatus.OK:
   126	                continue
   127	            if not math.isfinite(reading.value):
   128	                continue
   129	            to_write.append(
   130	                Reading(
   131	                    timestamp=reading.timestamp,
   132	                    instrument_id=reading.instrument_id,
   133	                    channel=f"{reading.channel}_raw",
   134	                    value=reading.value,
   135	                    unit="sensor_unit",
   136	                    status=ChannelStatus.OK,
   137	                    raw=reading.value,
   138	                    metadata={
   139	                        "reading_kind": "calibration_srdg",
   140	                        "source_channel": reading.channel,
   141	                    },
   142	                )
   143	            )
   144	
   145	        return (to_write, pending if pending else None)
   146	
   147	    def on_srdg_persisted(
   148	        self,
   149	        count: int,
   150	        pending_state: dict[str, float] | None = None,
   151	    ) -> None:
   152	        """Update counter and apply pending state after successful persistence."""
   153	        self._point_count += count
   154	        if pending_state:
   155	            if "t_min" in pending_state:
   156	                new = pending_state["t_min"]
   157	                if self._t_min is None or new < self._t_min:
   158	                    self._t_min = new
   159	            if "t_max" in pending_state:
   160	                new = pending_state["t_max"]
   161	                if self._t_max is None or new > self._t_max:
   162	                    self._t_max = new
   163	
   164	    async def on_readings(
   165	        self,
   166	        krdg: list[Reading],
   167	        srdg: list[Reading],
   168	    ) -> None:
   169	        """Deprecated: use prepare_srdg_readings + on_srdg_persisted.
   170	
    34	class CalibrationFitter:
    35	    """Post-run calibration pipeline: extract → downsample → breakpoints → fit."""
    36	
    37	    # ------------------------------------------------------------------
    38	    # Extract
    39	    # ------------------------------------------------------------------
    40	
    41	    @staticmethod
    42	    def extract_pairs(
    43	        data_dir: Path,
    44	        start_ts: float,
    45	        end_ts: float,
    46	        reference_channel: str,
    47	        target_channel: str,
    48	        *,
    49	        max_time_delta_s: float = 2.0,
    50	    ) -> list[tuple[float, float]]:
    51	        """Extract time-aligned (SRDG, KRDG) pairs from SQLite data files.
    52	
    53	        Returns list of ``(sensor_raw_value, reference_temperature_K)`` tuples.
    54	        """
    55	        srdg_channel = f"{target_channel}_raw"
    56	
    57	        # Collect readings from all day-partitioned DB files
    58	        krdg_data: list[tuple[float, float]] = []  # (timestamp, value)
    59	        srdg_data: list[tuple[float, float]] = []
    60	
    61	        for db_path in sorted(data_dir.glob("data_????-??-??.db")):
    62	            try:
    63	                conn = sqlite3.connect(str(db_path), timeout=5)
    64	                conn.execute("PRAGMA journal_mode=WAL")
    65	                cursor = conn.execute(
    66	                    "SELECT timestamp, value FROM readings "
    67	                    "WHERE channel = ? AND timestamp >= ? AND timestamp <= ? "
    68	                    "ORDER BY timestamp",
    69	                    (reference_channel, start_ts, end_ts),
    70	                )
   196	    def generate_breakpoints(
   197	        pairs: list[tuple[float, float]],
   198	        max_breakpoints: int = 200,
   199	        tolerance_mk: float = 50.0,
   200	    ) -> list[tuple[float, float]]:
   201	        """Douglas-Peucker breakpoint selection for .330 export."""
   202	        if len(pairs) <= 2:
   203	            return list(pairs)
   204	
   205	        sorted_pairs = sorted(pairs, key=lambda p: p[0])
   206	        tolerance_k = tolerance_mk / 1000.0
   207	
   208	        # Iterative Douglas-Peucker
   209	        n = len(sorted_pairs)
   210	        include = [False] * n
   211	        include[0] = True
   212	        include[n - 1] = True
   213	
   214	        # Stack-based DP
   215	        stack: list[tuple[int, int]] = [(0, n - 1)]
   216	        while stack:
   217	            if sum(include) >= max_breakpoints:
   218	                break
   219	            start, end = stack.pop()
   220	            if end - start <= 1:
   221	                continue
   222	
   223	            # Find point with max perpendicular distance
   224	            s_start = sorted_pairs[start][0]
   225	            t_start = sorted_pairs[start][1]
   226	            s_end = sorted_pairs[end][0]
   227	            t_end = sorted_pairs[end][1]
   228	
   229	            max_dist = 0.0
   230	            max_idx = start
   318	        calibration_store: CalibrationStore,
   319	        *,
   320	        target_count: int = 500,
   321	        max_breakpoints: int = 200,
   322	        tolerance_mk: float = 50.0,
   323	        min_points_per_zone: int = 6,
   324	        target_rmse_k: float = 0.05,
   325	    ) -> CalibrationFitResult:
   326	        """Full pipeline: extract → downsample → breakpoints → Chebyshev fit."""
   327	        sensor_id = f"{target_channel}_cal"
   328	
   329	        # 1. Extract
   330	        raw_pairs = self.extract_pairs(
   331	            data_dir,
   332	            start_ts,
   333	            end_ts,
   334	            reference_channel,
   335	            target_channel,
   336	        )
   337	        if len(raw_pairs) < max(4, min_points_per_zone):
   338	            raise ValueError(
   339	                f"Not enough calibration pairs: {len(raw_pairs)} "
   340	                f"(need at least {max(4, min_points_per_zone)})"
   341	            )
   342	
   343	        # 2. Downsample
   344	        downsampled = self.adaptive_downsample(raw_pairs, target_count)
   345	
   346	        # 3. Breakpoints
   347	        breakpoints = self.generate_breakpoints(
   348	            downsampled,
   349	            max_breakpoints,
   350	            tolerance_mk,
   351	        )
   352	
   353	        # 4. Chebyshev fit via CalibrationStore
   354	        now = datetime.now(UTC)
   355	        samples = [
   356	            CalibrationSample(
   357	                timestamp=now,
   358	                reference_channel=reference_channel,
   359	                reference_temperature=krdg_val,
   360	                sensor_channel=target_channel,
   361	                sensor_raw_value=srdg_val,
   362	            )
   363	            for srdg_val, krdg_val in downsampled
   364	        ]
   365	
   366	        curve = calibration_store.fit_curve(
   367	            sensor_id,
   368	            samples,
   369	            raw_unit="sensor_unit",
   370	            min_points_per_zone=min_points_per_zone,
   371	            target_rmse_k=target_rmse_k,
   372	        )
   373	        calibration_store.save_curve(curve)
   374	
   375	        # 5. Compute metrics on downsampled set
   376	        errors: list[float] = []
   377	        for srdg_val, krdg_val in downsampled:
   378	            try:
   379	                predicted = calibration_store.evaluate(sensor_id, srdg_val)
   380	                errors.append(predicted - krdg_val)
   381	            except Exception:
   382	                pass
   383	
   384	        rmse = float(np.sqrt(np.mean(np.array(errors) ** 2))) if errors else float("nan")
   385	        max_err = float(np.max(np.abs(errors))) if errors else float("nan")
   386	
   387	        metrics = {
   388	            "rmse_k": round(rmse, 6),
   389	            "max_abs_error_k": round(max_err, 6),
   390	            "zone_count": len(curve.zones),
   391	            "pair_count": len(raw_pairs),
   392	        }
   393	
   394	        return CalibrationFitResult(
   395	            sensor_id=sensor_id,
   396	            reference_channel=reference_channel,
   397	            raw_pairs_count=len(raw_pairs),
   398	            downsampled_count=len(downsampled),
   399	            breakpoint_count=len(breakpoints),
   400	            curve=curve,
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
   424	    def export_curve_330(
   425	        self,
   426	        sensor_id: str,
   427	        *,
   428	        path: Path | None = None,
   429	        points: int = 200,
   430	    ) -> Path:
   431	        curve = self._require_curve(sensor_id)
   432	        target = path or (self._curve_directory(curve.sensor_id, curve.curve_id) / "curve.330")
   433	        target.parent.mkdir(parents=True, exist_ok=True)
   434	        rows = self._export_rows(curve, points=max(points, 2))
   435	        self._write_curve_text_export(target, curve, rows, format_name="330")
   436	        self._write_index()
   437	        return target
   438	
   439	    def export_curve_340(
   440	        self,
   441	        sensor_id: str,
   442	        *,
   443	        path: Path | None = None,
   444	        points: int = 200,
   445	    ) -> Path:
   446	        curve = self._require_curve(sensor_id)
   447	        if self._exports_dir is None:
   448	            raise RuntimeError("CalibrationStore base_dir is required for export.")
   449	        target = path or self._curve_340_path(curve.sensor_id, curve.curve_id)
   450	        target.parent.mkdir(parents=True, exist_ok=True)
   451	        rows = self._export_rows(curve, points=max(points, 2))
   452	        self._write_curve_text_export(target, curve, rows, format_name="340")
   453	        self._write_index()
   454	        return target
   455	
   519	    def set_runtime_global_mode(self, mode: str) -> dict[str, Any]:
   520	        normalized = str(mode).strip().lower()
   521	        if normalized not in {"off", "on"}:
   522	            raise ValueError("Runtime calibration global_mode must be 'off' or 'on'.")
   523	        self._runtime_settings["global_mode"] = normalized
   524	        self._runtime_settings["updated_at"] = _utcnow().isoformat()
   525	        self._write_index()
   526	        return self.get_runtime_settings()
   527	
   528	    def set_runtime_channel_policy(
   529	        self,
   530	        *,
   531	        channel_key: str,
   532	        policy: str,
   533	        sensor_id: str | None = None,
   534	        curve_id: str | None = None,
   535	        runtime_apply_ready: bool | None = None,
   536	    ) -> dict[str, Any]:
   537	        normalized_channel_key = str(channel_key).strip()
   538	        if not normalized_channel_key:
   539	            raise ValueError("channel_key is required.")
   540	        normalized_policy = str(policy).strip().lower()
   541	        if normalized_policy not in {"inherit", "off", "on"}:
   542	            raise ValueError("Channel runtime policy must be 'inherit', 'off', or 'on'.")
   543	        curve = self._resolve_curve(
   544	            sensor_id=str(sensor_id or "").strip() or None,
   545	            curve_id=str(curve_id or "").strip() or None,
   546	        )
   547	        assignment = self._ensure_assignment(sensor_id=curve.sensor_id, curve_id=curve.curve_id)
   548	        assignment["channel_key"] = normalized_channel_key
   549	        assignment["reading_mode_policy"] = normalized_policy
   550	        if runtime_apply_ready is not None:
   551	            assignment["runtime_apply_ready"] = bool(runtime_apply_ready)
   552	        assignment["updated_at"] = _utcnow().isoformat()
   553	        self._write_index()
   554	        return {
   555	            "assignment": dict(assignment),
   556	            "resolution": self.resolve_runtime_policy(channel_key=normalized_channel_key),
   557	        }
   558	
   559	    def resolve_runtime_policy(
   560	        self,
   561	        *,
   562	        channel_key: str,
   563	    ) -> dict[str, Any]:
   564	        normalized_channel_key = str(channel_key).strip()
   565	        if not normalized_channel_key:
   566	            raise ValueError("channel_key is required.")
   567	        global_mode = str(self._runtime_settings.get("global_mode", "off") or "off")
   568	        assignment = next(
   569	            (
   570	                dict(item)
   571	                for item in self._assignments.values()
   572	                if str(item.get("channel_key", "")).strip() == normalized_channel_key
   573	            ),
   574	            None,
   575	        )
   576	        if global_mode == "off":
   577	            return {
   578	                "global_mode": global_mode,
   579	                "channel_key": normalized_channel_key,
   580	                "effective_mode": "off",
   581	                "reading_mode": "krdg",
   582	                "raw_source": "KRDG",
   583	                "reason": "global_off",
   584	                "assignment": assignment,
   585	            }
   586	        if assignment is None:
   587	            return {
   588	                "global_mode": global_mode,
   589	                "channel_key": normalized_channel_key,
   590	                "effective_mode": "off",
   591	                "reading_mode": "krdg",
   592	                "raw_source": "KRDG",
   593	                "reason": "missing_assignment",
   594	                "assignment": None,
   595	            }
   596	        policy = str(assignment.get("reading_mode_policy", "inherit") or "inherit").lower()
   597	        if policy == "off":
   598	            return {
   599	                "global_mode": global_mode,
   600	                "channel_key": normalized_channel_key,
   601	                "effective_mode": "off",
   602	                "reading_mode": "krdg",
   603	                "raw_source": "KRDG",
   604	                "reason": "channel_off",
   605	                "assignment": assignment,
   606	            }
   607	        if not bool(assignment.get("runtime_apply_ready", False)):
   608	            return {
   609	                "global_mode": global_mode,
   610	                "channel_key": normalized_channel_key,
   611	                "effective_mode": "off",
   612	                "reading_mode": "krdg",
   613	                "raw_source": "KRDG",
   614	                "reason": "not_runtime_ready",
   615	                "assignment": assignment,
   861	            handle.write(f"# CryoDAQ calibration curve export .{format_name}\n")
   862	            handle.write(f"# sensor_id: {curve.sensor_id}\n")
   863	            handle.write(f"# curve_id: {curve.curve_id}\n")
   864	            handle.write(f"# raw_unit: {curve.raw_unit}\n")
   865	            handle.write("# columns: temperature_K, sensor_raw\n")
   866	            writer = csv.writer(handle)
   867	            for temperature_k, raw_value in rows:
   868	                writer.writerow([f"{temperature_k:.9g}", f"{raw_value:.9g}"])
   869	
   870	    def _import_curve_text(
   871	        self,
   872	        path: Path,
   873	        *,
   874	        sensor_id: str | None,
   875	        channel_key: str | None,
   876	        raw_unit: str,
   877	        sensor_kind: str,
   878	        import_format: str,
   879	    ) -> CalibrationCurve:
   880	        rows: list[tuple[float, float]] = []
   881	        for raw_line in path.read_text(encoding="utf-8").splitlines():
   882	            line = raw_line.strip()
   883	            if not line or line.startswith("#"):
   884	                continue
   885	            line = line.replace(",", " ")
   886	            parts = [item for item in line.split() if item]
   887	            if len(parts) < 2:
   888	                continue
   889	            try:
   890	                temperature_k = float(parts[0])
   891	                raw_value = float(parts[1])
   892	            except ValueError:
   893	                continue
   894	            rows.append((temperature_k, raw_value))
   895	        if len(rows) < 4:
   896	            raise ValueError(
   897	                f"Calibration file '{path.name}' does not contain enough numeric pairs."
   898	            )
   899	        resolved_sensor_id = (sensor_id or (channel_key or path.stem)).strip()
   900	        samples = [
   901	            CalibrationSample(
   902	                timestamp=_utcnow(),
   903	                reference_channel="import",
   904	                reference_temperature=temperature_k,
   905	                sensor_channel=channel_key or resolved_sensor_id,
   906	                sensor_raw_value=raw_value,
   907	                metadata={"import_format": import_format, "source_path": str(path)},
   908	            )
   909	            for temperature_k, raw_value in sorted(rows, key=lambda item: item[1])
   910	        ]
   911	        curve = self.fit_curve(
   912	            resolved_sensor_id,
   913	            samples,
   914	            raw_unit=raw_unit,
   915	            sensor_kind=sensor_kind,
   916	            source_session_ids=(),
   917	            max_zones=3,
   918	            min_points_per_zone=4,
   919	            max_order=12,
   920	            target_rmse_k=0.05,
   921	            metadata={
   922	                "import_format": import_format,
   923	                "import_source_path": str(path),
   924	                "channel_key": channel_key or resolved_sensor_id,
   925	            },
   926	        )
   927	        self.save_curve(curve)
   928	        if import_format == "330":
   929	            self.export_curve_330(curve.sensor_id)
   930	        if import_format == "340":
   931	            self.export_curve_340(curve.sensor_id)
   932	        return curve
   933	
   934	    def _preprocess_samples(
   935	        self,
   936	        samples: list[CalibrationSample] | tuple[CalibrationSample, ...],
   937	        *,
   938	        downsample_target: int,
   939	    ) -> tuple[CalibrationSample, ...]:
   940	        rows: list[tuple[float, float, CalibrationSample]] = []

exec
/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/keithley_2604b.py | sed -n '1,120p;150,185p;330,365p;600,680p'; nl -ba /Users/vladimir/Projects/cryodaq/src/cryodaq/core/smu_channel.py | sed -n '1,120p'" in /Users/vladimir/Projects/cryodaq
exec
/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Projects/cryodaq/src/cryodaq/drivers/instruments/thyracont_vsp63d.py | sed -n '1,180p;240,330p'; nl -ba /Users/vladimir/Projects/cryodaq/CHANGELOG.md | sed -n '16,86p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	"""Keithley 2604B driver with dual-channel runtime support.
     2	
     3	P=const control loop runs host-side in read_channels() — no TSP scripts
     4	are uploaded to the instrument, so the VISA bus stays free for queries.
     5	"""
     6	
     7	from __future__ import annotations
     8	
     9	import logging
    10	import math
    11	from dataclasses import dataclass
    12	from typing import Any
    13	
    14	from cryodaq.core.smu_channel import SMU_CHANNELS, SmuChannel, normalize_smu_channel
    15	from cryodaq.drivers.base import ChannelStatus, InstrumentDriver, Reading
    16	from cryodaq.drivers.transport.usbtmc import USBTMCTransport
    17	
    18	log = logging.getLogger(__name__)
    19	
    20	# Minimum measurable current for resistance calculation (avoid division by noise).
    21	# At 1 nA, R = V/I is dominated by noise.  For heaters with R ~ 10–1000 Ω,
    22	# 100 nA gives R accurate to ~1%.
    23	_I_MIN_A = 1e-7
    24	
    25	# Maximum voltage change per poll cycle (slew rate limit).
    26	# Prevents target_v from jumping from 0 to V_compliance in one step when
    27	# resistance changes abruptly (superconducting transition, wire break).
    28	MAX_DELTA_V_PER_STEP = 0.5  # V — do not increase without thermal analysis
    29	
    30	# Number of consecutive compliance cycles before notifying SafetyManager.
    31	_COMPLIANCE_NOTIFY_THRESHOLD = 10
    32	
    33	_MOCK_R0 = 100.0
    34	_MOCK_T0 = 300.0
    35	_MOCK_ALPHA = 0.0033
    36	_MOCK_COOLING_RATE = 0.1
    37	_MOCK_SMUB_FACTOR = 0.7
    38	
    39	_IV_FIELDS = (
    40	    ("voltage", "V"),
    41	    ("current", "A"),
    42	    ("resistance", "Ohm"),
    43	    ("power", "W"),
    44	)
    45	
    46	
    47	@dataclass
    48	class ChannelRuntime:
    49	    channel: SmuChannel
    50	    p_target: float = 0.0
    51	    v_comp: float = 40.0
    52	    i_comp: float = 1.0
    53	    active: bool = False
    54	
    55	
    56	class Keithley2604B(InstrumentDriver):
    57	    def __init__(
    58	        self,
    59	        name: str,
    60	        resource_str: str,
    61	        *,
    62	        mock: bool = False,
    63	    ) -> None:
    64	        super().__init__(name, mock=mock)
    65	        self._resource_str = resource_str
    66	        self._transport = USBTMCTransport(mock=mock)
    67	        self._instrument_id = ""
    68	        self._channels: dict[SmuChannel, ChannelRuntime] = {
    69	            "smua": ChannelRuntime(channel="smua"),
    70	            "smub": ChannelRuntime(channel="smub"),
    71	        }
    72	        # Slew rate state: last voltage actually written to each SMU channel.
    73	        self._last_v: dict[SmuChannel, float] = {"smua": 0.0, "smub": 0.0}
    74	        # Compliance tracking: consecutive cycles where SMU reports compliance.
    75	        self._compliance_count: dict[SmuChannel, int] = {"smua": 0, "smub": 0}
    76	        self._mock_temp = _MOCK_T0
    77	
    78	    async def connect(self) -> None:
    79	        log.info("%s: connecting to %s", self.name, self._resource_str)
    80	        await self._transport.open(self._resource_str)
    81	        try:
    82	            idn = await self._transport.query("*IDN?")
    83	            self._instrument_id = idn
    84	            if "2604B" not in idn:
    85	                raise RuntimeError(f"{self.name}: unexpected IDN {idn!r}")
    86	            # Drain stale errors so they don't confuse runtime error checks.
    87	            await self._transport.write("errorqueue.clear()")
    88	            # SAFETY (Phase 2a G.1): force outputs off on every connect.
    89	            # The previous engine process may have crashed mid-experiment
    90	            # while sourcing — Keithley holds the last programmed voltage
    91	            # indefinitely with no TSP-side watchdog (see CLAUDE.md). This
    92	            # guarantees a known-safe state every time we assume control.
    93	            # Best-effort: an exception here is logged but does NOT abort
    94	            # connect (the higher-level health checks will catch a truly
    95	            # broken instrument; our priority is to avoid leaving an
    96	            # unconnected lab in a worse state than "possibly still sourcing").
    97	            if not self.mock:
    98	                try:
    99	                    await self._transport.write("smua.source.levelv = 0")
   100	                    await self._transport.write("smub.source.levelv = 0")
   101	                    await self._transport.write("smua.source.output = smua.OUTPUT_OFF")
   102	                    await self._transport.write("smub.source.output = smub.OUTPUT_OFF")
   103	                    log.info(
   104	                        "%s: SAFETY: forced outputs off on connect (crash-recovery guard)",
   105	                        self.name,
   106	                    )
   107	                except Exception as exc:
   108	                    log.critical(
   109	                        "%s: SAFETY: failed to force output off on connect: %s",
   110	                        self.name,
   111	                        exc,
   112	                    )
   113	        except Exception:
   114	            await self._transport.close()
   115	            raise
   116	        self._connected = True
   117	
   118	    async def disconnect(self) -> None:
   119	        if not self._connected:
   120	            return
   150	                                smu_channel, 0.0, 0.0, resistance_override=0.0
   151	                            )
   152	                        )
   153	                        continue
   154	
   155	                    # Output is ON but not managed by us — read for monitoring.
   156	                    raw = await self._transport.query(f"print({smu_channel}.measure.iv())")
   157	                    current, voltage = self._parse_iv_response(raw, smu_channel)
   158	                    readings.extend(self._build_channel_readings(smu_channel, voltage, current))
   159	                    continue
   160	
   161	                # --- Active P=const channel: measure + regulate ---
   162	                raw = await self._transport.query(f"print({smu_channel}.measure.iv())")
   163	                current, voltage = self._parse_iv_response(raw, smu_channel)
   164	
   165	                # --- Compliance check ---
   166	                comp_raw = await self._transport.query(f"print({smu_channel}.source.compliance)")
   167	                in_compliance = comp_raw.strip().lower() == "true"
   168	
   169	                extra_meta: dict[str, Any] = {}
   170	                if in_compliance:
   171	                    self._compliance_count[smu_channel] += 1
   172	                    log.warning(
   173	                        "%s: %s in compliance — P=const regulation ineffective (consecutive=%d)",
   174	                        self.name,
   175	                        smu_channel,
   176	                        self._compliance_count[smu_channel],
   177	                    )
   178	                    extra_meta["compliance"] = True
   179	                    # Do NOT adjust voltage — the SMU is already at its limit.
   180	                else:
   181	                    self._compliance_count[smu_channel] = 0
   182	
   183	                    # --- P=const voltage regulation with slew rate limit ---
   184	                    if abs(current) > _I_MIN_A:
   185	                        resistance = voltage / current
   330	                    smu_channel,
   331	                    exc,
   332	                )
   333	
   334	    async def check_error(self) -> str | None:
   335	        if not self._connected:
   336	            raise RuntimeError(f"{self.name}: instrument not connected")
   337	        response = (await self._transport.query("print(errorqueue.count)")).strip()
   338	        if response in {"", "0"}:
   339	            return None
   340	        return response
   341	
   342	    @property
   343	    def any_active(self) -> bool:
   344	        return any(runtime.active for runtime in self._channels.values())
   345	
   346	    @property
   347	    def active_channels(self) -> list[str]:
   348	        return [channel for channel, runtime in self._channels.items() if runtime.active]
   349	
   350	    def compliance_persistent(self, channel: SmuChannel) -> bool:
   351	        """True if compliance has persisted for >= threshold consecutive cycles."""
   352	        return self._compliance_count.get(channel, 0) >= _COMPLIANCE_NOTIFY_THRESHOLD
   353	
   354	    async def diagnostics(self) -> dict[str, Any]:
   355	        """Periodic health check — called by scheduler every 30s."""
   356	        if not self._connected or self.mock:
   357	            return {}
   358	        result: dict[str, Any] = {}
   359	        try:
   360	            raw = await self._transport.query("print(errorqueue.count)")
   361	            err_count = int(float(raw.strip()))
   362	            if err_count > 0:
   363	                raw = await self._transport.query("print(errorqueue.next())")
   364	                log.warning("Keithley error queue: %s", raw.strip())
   365	                result["error_queue"] = raw.strip()
     1	from __future__ import annotations
     2	
     3	from typing import Literal
     4	
     5	type SmuChannel = Literal["smua", "smub"]
     6	SMU_CHANNELS: tuple[SmuChannel, SmuChannel] = ("smua", "smub")
     7	
     8	
     9	def normalize_smu_channel(channel: str | None) -> SmuChannel:
    10	    value = (channel or "smua").strip().lower()
    11	    if value not in SMU_CHANNELS:
    12	        allowed = ", ".join(SMU_CHANNELS)
    13	        raise ValueError(f"Invalid Keithley channel '{channel}'. Allowed values: {allowed}.")
    14	    return value  # type: ignore[return-value]

 succeeded in 0ms:
     1	"""Драйвер вакуумметра Thyracont VSP63D (RS-232/USB-Serial)."""
     2	
     3	from __future__ import annotations
     4	
     5	import logging
     6	import math
     7	import random
     8	import time
     9	
    10	from cryodaq.drivers.base import ChannelStatus, InstrumentDriver, Reading
    11	from cryodaq.drivers.transport.serial import SerialTransport
    12	
    13	log = logging.getLogger(__name__)
    14	
    15	# Известные пары baudrate ↔ fallback для автоопределения протокола
    16	_FALLBACK_BAUDRATES: dict[int, int] = {9600: 115200, 115200: 9600}
    17	
    18	# Коды статуса из ответа прибора
    19	_STATUS_OK = 0
    20	_STATUS_UNDERRANGE = 1
    21	_STATUS_OVERRANGE = 2
    22	_STATUS_SENSOR_ERROR = 3
    23	
    24	# Карта кода статуса → ChannelStatus
    25	_STATUS_MAP: dict[int, ChannelStatus] = {
    26	    _STATUS_OK: ChannelStatus.OK,
    27	    _STATUS_UNDERRANGE: ChannelStatus.UNDERRANGE,
    28	    _STATUS_OVERRANGE: ChannelStatus.OVERRANGE,
    29	    _STATUS_SENSOR_ERROR: ChannelStatus.SENSOR_ERROR,
    30	}
    31	
    32	# Mock-параметры: реалистичный вакуум
    33	_MOCK_BASE_PRESSURE_MBAR: float = 1.5e-6
    34	
    35	
    36	class ThyracontVSP63D(InstrumentDriver):
    37	    """Вакуумметр Thyracont VSP63D / VSM77DL.
    38	
    39	    Поддерживает два протокола:
    40	
    41	    **VSP63D (по умолчанию):**
    42	      RS-232/USB-Serial, 9600 бод.
    43	      Команда: ``"MV00\\r"`` → ответ: ``"status,value\\r"``
    44	
    45	    **Thyracont Protocol V1 (VSM77DL и аналоги):**
    46	      RS-232/USB-Serial, 115200 бод.
    47	      Команда: ``"<addr>M^\\r"`` → ответ: ``"<addr>M<6digits><checksum>\\r"``
    48	      Кодировка 6-значного значения (ABCDEF): ABCD = мантисса, EF = экспонента.
    49	      ``pressure = (ABCD / 1000) * 10^(EF - 20)`` mbar.
    50	
    51	    Протокол определяется автоматически по формату ответа, а также может
    52	    быть форсирован через параметр ``protocol``.
    53	
    54	    Parameters
    55	    ----------
    56	    name:
    57	        Уникальное имя экземпляра прибора (используется в метаданных Reading).
    58	    resource_str:
    59	        Имя последовательного порта, например ``"COM3"`` или ``"/dev/ttyUSB0"``.
    60	    baudrate:
    61	        Скорость обмена в бодах (по умолчанию 9600).
    62	    address:
    63	        Адрес прибора для Protocol V1 (по умолчанию ``"001"``).
    64	    mock:
    65	        Если ``True`` — работает без реального прибора, возвращает
    66	        имитированное давление ~1.5e-6 мбар.
    67	    """
    68	
    69	    def __init__(
    70	        self,
    71	        name: str,
    72	        resource_str: str,
    73	        *,
    74	        baudrate: int = 9600,
    75	        address: str = "001",
    76	        mock: bool = False,
    77	        # Phase 2c Codex F.2: default flipped from False to True. Thyracont
    78	        # protocol carries an explicit CS field; on noisy RS-232 lines a
    79	        # silent corruption could otherwise produce an incorrect pressure
    80	        # reading. Operators with known-bad firmware can opt back out via
    81	        # `validate_checksum: false` in instruments.local.yaml.
    82	        validate_checksum: bool = True,
    83	    ) -> None:
    84	        super().__init__(name, mock=mock)
    85	        self._resource_str = resource_str
    86	        self._baudrate = baudrate
    87	        self._address = address
    88	        self._transport = SerialTransport(mock=mock)
    89	        self._instrument_id: str = ""
    90	        self._protocol_v1: bool = False
    91	        self._validate_checksum: bool = validate_checksum
    92	
    93	    # ------------------------------------------------------------------
    94	    # InstrumentDriver — обязательный интерфейс
    95	    # ------------------------------------------------------------------
    96	
    97	    async def connect(self) -> None:
    98	        """Открыть последовательный порт и верифицировать связь с прибором.
    99	
   100	        Пробует Protocol V1 (``"<addr>M^"``), затем MV00. Если ни один
   101	        протокол не отвечает на сконфигурированном baudrate, пробует
   102	        fallback baudrate (9600 ↔ 115200). Устанавливает флаг
   103	        ``_connected = True`` при успехе.
   104	        """
   105	        baudrates_to_try = [self._baudrate]
   106	        fallback = _FALLBACK_BAUDRATES.get(self._baudrate)
   107	        if fallback is not None:
   108	            baudrates_to_try.append(fallback)
   109	
   110	        last_error = ""
   111	        for baud in baudrates_to_try:
   112	            log.info("%s: подключение к %s @ %d бод", self.name, self._resource_str, baud)
   113	            try:
   114	                await self._transport.open(self._resource_str, baudrate=baud)
   115	            except Exception as exc:
   116	                log.warning("%s: failed to open port @ %d baud: %s", self.name, baud, exc)
   117	                last_error = str(exc)
   118	                continue
   119	
   120	            # Try Protocol V1
   121	            if await self._try_v1_probe():
   122	                self._protocol_v1 = True
   123	                self._instrument_id = f"Thyracont-V1@{self._address}"
   124	                self._connected = True
   125	                if baud != self._baudrate:
   126	                    log.info(
   127	                        "%s: connected via Protocol V1 @ %d baud (fallback from %d)",
   128	                        self.name,
   129	                        baud,
   130	                        self._baudrate,
   131	                    )
   132	                else:
   133	                    log.info("%s: connected via Protocol V1", self.name)
   134	                return
   135	
   136	            # Try MV00
   137	            if await self._try_mv00_probe():
   138	                self._protocol_v1 = False
   139	                self._instrument_id = f"Thyracont-MV00@{self._resource_str}"
   140	                self._connected = True
   141	                if baud != self._baudrate:
   142	                    log.info(
   143	                        "%s: connected via MV00 @ %d baud (fallback from %d)",
   144	                        self.name,
   145	                        baud,
   146	                        self._baudrate,
   147	                    )
   148	                else:
   149	                    log.info("%s: connected via MV00", self.name)
   150	                return
   151	
   152	            await self._transport.close()
   153	            last_error = f"neither V1 nor MV00 responded @ {baud} baud"
   154	
   155	        raise RuntimeError(f"{self.name}: {last_error}")
   156	
   157	    async def _try_v1_probe(self) -> bool:
   158	        """Attempt Protocol V1 probe. Returns True on success."""
   159	        cmd = f"{self._address}M^"
   160	        expected_prefix = f"{self._address}M"
   161	        for attempt in range(3):
   162	            if attempt > 0:
   163	                await self._transport.flush_input()
   164	            try:
   165	                resp = await self._transport.query(cmd)
   166	                if resp.strip().startswith(expected_prefix):
   167	                    log.debug("%s: V1 probe OK (attempt %d)", self.name, attempt + 1)
   168	                    return True
   169	            except Exception as exc:
   170	                log.debug("%s: V1 probe attempt %d failed: %s", self.name, attempt + 1, exc)
   171	        return False
   172	
   173	    async def _try_mv00_probe(self) -> bool:
   174	        """Attempt MV00 protocol probe. Returns True on success."""
   175	        await self._transport.flush_input()
   176	        try:
   177	            resp = await self._transport.query("MV00")
   178	            resp_stripped = resp.strip()
   179	            # MV00 returns "<status>,<value>" e.g. "0,1.234E-06"
   180	            if "," in resp_stripped:
   240	
   241	        Returns
   242	        -------
   243	        Reading
   244	            Показание давления с соответствующим статусом.
   245	        """
   246	        response_stripped = response.strip()
   247	        channel = f"{self.name}/pressure"
   248	
   249	        try:
   250	            parts = response_stripped.split(",", 1)
   251	            if len(parts) != 2:
   252	                raise ValueError(f"Неверный формат ответа: '{response_stripped}'")
   253	
   254	            status_code = int(parts[0].strip())
   255	            value = float(parts[1].strip())
   256	        except (ValueError, IndexError) as exc:
   257	            log.error(
   258	                "%s: не удалось разобрать ответ '%s' — %s",
   259	                self.name,
   260	                response_stripped,
   261	                exc,
   262	            )
   263	            return Reading.now(
   264	                channel=channel,
   265	                value=float("nan"),
   266	                unit="mbar",
   267	                instrument_id=self.name,
   268	                status=ChannelStatus.SENSOR_ERROR,
   269	                raw=None,
   270	                metadata={"raw_response": response_stripped},
   271	            )
   272	
   273	        ch_status = _STATUS_MAP.get(status_code, ChannelStatus.SENSOR_ERROR)
   274	
   275	        if ch_status != ChannelStatus.OK:
   276	            log.warning(
   277	                "%s: статус ответа %d (%s), значение=%s мбар",
   278	                self.name,
   279	                status_code,
   280	                ch_status.value,
   281	                value,
   282	            )
   283	
   284	        return Reading.now(
   285	            channel=channel,
   286	            value=value,
   287	            unit="mbar",
   288	            instrument_id=self.name,
   289	            status=ch_status,
   290	            raw=value,
   291	            metadata={"status_code": status_code},
   292	        )
   293	
   294	    # ------------------------------------------------------------------
   295	    # Разбор ответа Protocol V1 (VSM77DL)
   296	    # ------------------------------------------------------------------
   297	
   298	    @staticmethod
   299	    def _verify_v1_checksum(response: str) -> bool:
   300	        """Verify Thyracont Protocol V1 checksum.
   301	
   302	        Format: <payload><checksum_char>
   303	        Checksum = XOR of all bytes in payload, masked to 0x7F.
   304	        """
   305	        if len(response) < 2:
   306	            return False
   307	        payload = response[:-1]
   308	        expected_char = response[-1]
   309	        computed = 0
   310	        for byte in payload.encode("ascii", errors="replace"):
   311	            computed ^= byte
   312	        computed &= 0x7F
   313	        return chr(computed) == expected_char
   314	
   315	    def _parse_v1_response(self, response: str) -> Reading:
   316	        """Разобрать ответ Thyracont Protocol V1.
   317	
   318	        Формат: ``"<addr>M<6digits><checksum>\\r"``, например ``"001M260017N\\r"``.
   319	
   320	        Кодировка 6-значного значения ABCDEF::
   321	
   322	            ABCD = мантисса (4 цифры)
   323	            EF   = экспонента (2 цифры)
   324	            pressure_mbar = (ABCD / 1000) × 10^(EF − 20)
   325	
   326	        Примеры:
   327	        - ``260017`` → (2600/1000) × 10^(17−20) = 2.6e-3 mbar
   328	        - ``100023`` → (1000/1000) × 10^(23−20) = 1000 mbar
   329	
   330	        Parameters
    16	release is `0.34.0` once B1 is resolved via IV.7.
    17	
    18	**Fixed / shipped:**
    19	
    20	- `aabd75f` — `engine: wire validate_checksum through Thyracont
    21	  driver loader`. Fixes TopWatchBar pressure em-dash on Ubuntu lab
    22	  PC when VSP206 hardware is connected. `_create_instruments()`
    23	  was ignoring the YAML key entirely; driver defaulted to strict
    24	  checksum validation regardless of config. One-line loader fix;
    25	  config-side `validate_checksum: false` in
    26	  `instruments.local.yaml` now actually applies.
    27	
    28	- `74dbbc7` — `reporting: xml_safe sanitizer for python-docx
    29	  compatibility`. Fixes `experiment_generate_report` failure when
    30	  real Keithley 2604B is connected (VISA resource contains `\x00`
    31	  per NI-VISA spec; python-docx rejects XML 1.0 control chars).
    32	  New `src/cryodaq/utils/xml_safe.py` with 10 unit tests. Applied
    33	  at all `add_paragraph()` / `cell.text` sites in
    34	  `src/cryodaq/reporting/sections.py`. `core/experiment.py:782`
    35	  logger upgraded from `log.warning` to `log.exception` — future
    36	  report-gen failures will include tracebacks (how this bug
    37	  survived: only the exception message was ever logged).
    38	
    39	- `be51a24` — `zmq: ephemeral REQ per command + cmd-channel
    40	  watchdog (IV.6 partial B1 mitigation)`. Landed the full
    41	  Codex-proposed B1 fix plan: per-command ephemeral REQ socket in
    42	  `zmq_subprocess.cmd_forward_loop`, launcher-side
    43	  `command_channel_stalled()` watchdog in `_poll_bridge_data`,
    44	  `TCP_KEEPALIVE` reverted on command + PUB paths (kept on
    45	  `sub_drain_loop` as orthogonal safeguard). 60/60 unit tests
    46	  green, full subtree 1775/1776 (1 pre-existing flaky).
    47	  **Does NOT fix B1 — Stage 3 diag tools still reproduce it.**
    48	  Committed anyway as architectural improvement matching ZeroMQ
    49	  Guide ch.4 canonical reliable req-reply pattern. Codex's
    50	  shared-REQ-state hypothesis falsified by this experiment.
    51	
    52	- Config edits on Ubuntu lab PC (some in git, some local):
    53	  - `interlocks.yaml` — `overheat_cryostat` regex tightened from
    54	    `Т[1-8] .*` to `Т(1|2|3|5|6|7|8) .*`. Т4 sensor is physically
    55	    disconnected (reads 380 K open-circuit), was triggering
    56	    `emergency_off` on Keithley during normal operation.
    57	  - `alarms_v3.yaml` — Т4 added to `uncalibrated` and `all_temp`
    58	    channel groups so `sensor_fault` still publishes WARNING
    59	    without hardware lockout.
    60	  - `instruments.local.yaml` — `validate_checksum: false` on
    61	    Thyracont block (per-machine override; NOT in git).
    62	
    63	- Operational on Ubuntu lab PC: `ModemManager` disabled
    64	  (was transiently grabbing `/dev/ttyUSB0`).
    65	
    66	**Open / known issues carrying into 0.34.0:**
    67	
    68	- **B1 still unresolved.** GUI command channel silently dies
    69	  ~30-120 s after bridge startup on both platforms. IV.7 `ipc://`
    70	  transport experiment is the next attempt — spec at
    71	  `CC_PROMPT_IV_7_IPC_TRANSPORT.md`. Workaround in place:
    72	  watchdog cooldown (TBD commit) prevents the IV.6 restart storm
    73	  regression, system works in 60-120 s cycles with single
    74	  restarts between.
    75	
    76	- `alarm_v2.py::_eval_condition` raises `KeyError 'threshold'`
    77	  when evaluating `cooldown_stall` composite. One sub-condition
    78	  is missing a `threshold` field. Log spam, not crash. Pending
    79	  mini-fix.
    80	
    81	- Thyracont `_try_v1_probe` probe-vs-read inconsistency. Probe
    82	  always succeeds; read checksum-validates. Driver can "connect"
    83	  and emit NaN forever on non-VSP63D hardware. Pending
    84	  hardening fix.
    85	
    86	**Infrastructure:**

exec
/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Projects/cryodaq/config/instruments.yaml | sed -n '1,90p'; nl -ba /Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md | sed -n '28,58p;220,238p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	instruments:
     2	  - type: lakeshore_218s
     3	    name: "LS218_1"
     4	    resource: "GPIB0::12::INSTR"
     5	    poll_interval_s: 2.0
     6	    channels:
     7	      1: "Т1 Криостат верх"
     8	      2: "Т2 Криостат низ"
     9	      3: "Т3 Радиатор 1"
    10	      4: "Т4 Радиатор 2"
    11	      5: "Т5 Экран 77К"
    12	      6: "Т6 Экран 4К"
    13	      7: "Т7 Детектор"
    14	      8: "Т8 Калибровка"
    15	
    16	  - type: lakeshore_218s
    17	    name: "LS218_2"
    18	    resource: "GPIB0::14::INSTR"
    19	    poll_interval_s: 2.0
    20	    channels:
    21	      1: "Т9 Компрессор вход"
    22	      2: "Т10 Компрессор выход"
    23	      3: "Т11 Теплообменник 1"
    24	      4: "Т12 Теплообменник 2"
    25	      5: "Т13 Труба подачи"
    26	      6: "Т14 Труба возврата"
    27	      7: "Т15 Вакуумный кожух"
    28	      8: "Т16 Фланец"
    29	
    30	  - type: lakeshore_218s
    31	    name: "LS218_3"
    32	    resource: "GPIB0::16::INSTR"
    33	    poll_interval_s: 2.0
    34	    channels:
    35	      1: "Т17 Зеркало 1"
    36	      2: "Т18 Зеркало 2"
    37	      3: "Т19 Подвес"
    38	      4: "Т20 Рама"
    39	      5: "Т21 Резерв 1"
    40	      6: "Т22 Резерв 2"
    41	      7: "Т23 Резерв 3"
    42	      8: "Т24 Резерв 4"
    43	
    44	  - type: keithley_2604b
    45	    name: "Keithley_1"
    46	    resource: "USB0::0x05E6::0x2604::04052028::INSTR"
    47	    poll_interval_s: 1.0
    48	
    49	  - type: thyracont_vsp63d
    50	    name: "VSP63D_1"
    51	    resource: "COM3"
    52	    baudrate: 9600
    53	    poll_interval_s: 2.0
    28	
    29	## Физическая установка
    30	
    31	| Прибор | Интерфейс | Каналы | Драйвер |
    32	|---|---|---|---|
    33	| LakeShore 218S (x3) | GPIB | 24 температурных | `lakeshore_218s.py` |
    34	| Keithley 2604B | USB-TMC | smua + smub | `keithley_2604b.py` |
    35	| Thyracont VSP63D | RS-232 | 1 давление | `thyracont_vsp63d.py` |
    36	
    37	### Аппаратные / рантайм инварианты
    38	
    39	1. **SAFE_OFF** — состояние по умолчанию. Source ON = непрерывное доказательство здоровья.
    40	2. **Persistence-first:** `SQLiteWriter.write_immediate()` → `DataBroker` → `SafetyBroker`.
    41	3. **SafetyState FSM:** 6 состояний — `SAFE_OFF → READY → RUN_PERMITTED → RUNNING → FAULT_LATCHED → MANUAL_RECOVERY → READY`.
    42	4. **Fail-on-silence:** stale data → FAULT (только в RUNNING; вне RUNNING блокирует readiness через preconditions).
    43	5. **Rate limit:** `dT/dt > 5 K/мин` → FAULT (конфигурируемый default в `safety.yaml`, не жёсткий инвариант).
    44	6. **Keithley connect** forces OUTPUT_OFF на обоих SMU (best-effort).
    45	7. **Keithley disconnect** вызывает `emergency_off()` первым.
    46	8. **No blocking I/O** на engine event loop (исключение: `reporting/generator.py` sync `subprocess.run` для LibreOffice).
    47	9. **No numpy/scipy** в `drivers/core` (исключение: `core/sensor_diagnostics.py` — MAD/корреляция).
    48	
    49	### Инварианты добавленные Phase 2d (активны)
    50	
    51	10. **OVERRANGE/UNDERRANGE** persist с `status` (`±inf` валидные REAL в SQLite). SENSOR_ERROR/TIMEOUT (NaN) отфильтровываются.
    52	11. **Cancellation shielding** на `_fault()` post-fault paths: `emergency_off`, `fault_log_callback` (before publish), `_ensure_output_off` в `_safe_off`.
    53	12. **Fail-closed config:** `safety.yaml`, `alarms_v3.yaml`, `interlocks.yaml`, `housekeeping.yaml`, `channels.yaml` → subsystem-specific `ConfigError` → engine exit code 2 (без auto-restart).
    54	13. **Atomic file writes** для experiment sidecars и calibration index/curve через `core/atomic_write`.
    55	14. **WAL mode verification:** raises `RuntimeError` если `PRAGMA journal_mode=WAL` вернул не `'wal'`.
    56	15. **Calibration KRDG+SRDG** persist в одной транзакции per poll cycle. State mutation deferred to `on_srdg_persisted`.
    57	16. **Scheduler.stop()** — graceful drain (configurable via `safety.yaml scheduler_drain_timeout_s`, default 5s) перед forced cancel.
    58	17. **_fault() ordering:** post-mortem log callback BEFORE optional broker publish (Jules R2 fix).
   220	
   221	- **GAP документы** (выявлены `docs/REPO_AUDIT_REPORT.md`): user-facing calibration guide, Web API spec (`/status`, `/history`, `/api/status`, `/ws`), instrument setup guide, operator-safety guide (в дополнение к developer-oriented `SAFETY_MANAGER_DEEP_DIVE.md`), TSP Phase-3 status.
   222	
   223	Полный audit findings list — `docs/audits/2026-04-09/DEEP_AUDIT_CC_POST_2C.md`, `docs/audits/2026-04-09/MASTER_TRIAGE.md`.
   224	
   225	---
   226	
   227	## Ключевые решения
   228	
   229	1. **Dual-channel Keithley (`smua` + `smub`)** — confirmed operational model.
   230	2. **Persistence-first** — SQLite WAL commit BEFORE any subscriber sees data.
   231	3. **Fail-closed config** — все 5 safety-adjacent configs (safety, alarm, interlock, housekeeping, channels) предотвращают запуск движка при missing / malformed файлах.
   232	4. **Cancellation shielding** — hardware `emergency_off`, post-mortem log emission, `_safe_off` cleanup все `asyncio.shield`'d. Log callback ordered BEFORE optional publish.
   233	5. **`_fault()` re-entry guard** — ранний return если state=`FAULT_LATCHED`, предотвращает race на concurrent вызовы (добавлен 2026-04-17).
   234	6. **OVERRANGE/UNDERRANGE persist** — `±inf` в REAL SQLite. NaN-valued statuses dropped до Phase 3.
   235	7. **Atomic sidecar writes** — experiment metadata, calibration index/curve через `core/atomic_write`.
   236	8. **WAL mode verification** — engine refuses to start, если SQLite не включает WAL.
   237	9. **Graceful scheduler drain** — configurable via `safety.yaml scheduler_drain_timeout_s` (default 5s).
   238	10. **Three-layer review** — CC tactical + Codex second-opinion + Jules architectural; применяется ко всем safety-критичным изменениям.

exec
/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Projects/cryodaq/.claude/skills/multi-model-consultation.md | sed -n '1,240p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	---
     2	name: multi-model-consultation
     3	description: "Use when CC needs to consult external AI models (Codex CLI, Gemini CLI, GLM-5.1, Kimi K2.6) for review, audit, draft, or second opinion on CryoDAQ work. Routes the task to the right model based on its strengths, produces a synthesis artifact that becomes the durable record, follows docs/ORCHESTRATION.md §4 protocol. Invoke whenever architect says 'get a review from', 'ask Codex', 'ask Gemini', 'run swarm', 'second opinion', 'adversarial review', 'cross-check with another model', or CC itself encounters a decision where its own confidence is low and architect is unavailable. Covers routing decision, budget discipline, identity-leak gotchas, formation patterns (single / writer-reviewer / adversarial pair / wide audit), brief templates, synthesis format, and anti-patterns learned from 2026-04-21..23 failed swarm cycle."
     4	---
     5	
     6	# Multi-model consultation — CC as conductor, not soloist
     7	
     8	## 0. When NOT to use this skill
     9	
    10	Most of the time, don't. CC should try its own reasoning first. External
    11	consultation is expensive (token budget, wall-clock, synthesis overhead)
    12	and injects noise that still has to be filtered. The 2026-04-21..23
    13	swarm cycle that produced 12 untracked review markdowns in repo root +
    14	two parallel duplicate branches happened because **consultation became
    15	reflex**, not judgment.
    16	
    17	Skip consultation when:
    18	
    19	- The task is mechanical (rename files, apply architect-spec'd patch,
    20	  gitignore pattern edit)
    21	- CC's own reasoning produces a single clear answer and architect's
    22	  plan is complete
    23	- The question is scoped so narrowly a single-model answer is trivially
    24	  verifiable by running a test
    25	- Budget is tight and architect is available for direct guidance
    26	
    27	Use consultation only when all three of these hold:
    28	
    29	1. The decision has meaningful downside cost if wrong (safety code,
    30	   architectural change, irreversible migration, production hardware
    31	   behavior, branch merge decision)
    32	2. CC's own reasoning is not confident (competing hypotheses, missing
    33	   domain knowledge, non-obvious tradeoff)
    34	3. Either architect is available but has explicitly asked for a model
    35	   cross-check, or architect is not available and the task cannot wait
    36	
    37	## 1. Why four models — what each actually offers
    38	
    39	Claude, Codex, Gemini, GLM, Kimi are NOT interchangeable. Each has a
    40	real niche. Using the wrong model is not just wasteful — it actively
    41	produces worse output than no consultation.
    42	
    43	### Codex CLI — gpt-5.5 high reasoning
    44	
    45	**Strength:** narrow adversarial code review. Step-by-step reasoning on
    46	concurrency, race conditions, IPC, subprocess lifecycle, socket state
    47	machines, specific bug hunts in a diff. Will cite `file:line` references
    48	without being told. Writes terse critiques that skip filler.
    49	
    50	**Weakness:** holistic architecture vision. Tends to see trees not
    51	forest. Long context (> ~50K tokens) degrades. Prose-heavy reports
    52	(strategy docs, vision statements) are not Codex's format — it produces
    53	bullet lists and verdicts instead.
    54	
    55	**Always pass:** `--model gpt-5.5 --reasoning high` as flags AND
    56	`Model: gpt-5.5 / Reasoning effort: high` as first two lines of prompt
    57	body. Default `o3` is weak for this workflow.
    58	
    59	**Version note:** GPT-5.5 released post 2026-04-24. Prior to that release
    60	we used gpt-5.4. When CC reads this skill and the date is later than
    61	2026-04-24, use gpt-5.5. If architect references a newer version,
    62	architect wins — update this skill accordingly.
    63	
    64	**Signature signal:** verdict headers like "FAIL / PASS / CONDITIONAL",
    65	numbered findings with file:line, short reasoning per finding.
    66	
    67	**Budget:** ChatGPT Plus subscription, 5-hour rolling window. Plan
    68	for ~3-5 substantial reviews per day. Background jobs eat the window
    69	fast — use `/codex:review` foreground unless you genuinely need
    70	parallelism.
    71	
    72	**Sandbox gotcha (2026-04-24 observed):** Codex CLI defaults to
    73	read-only filesystem sandbox and will emit
    74	`patch rejected: writing is blocked by read-only sandbox` when asked
    75	to write the response file itself. Two workarounds:
    76	1. Invoke with `--sandbox workspace-write` flag so Codex can write
    77	   directly to the response path.
    78	2. Let Codex print response to stdout and have CC redirect the
    79	   stdout to the response file: `codex exec ... > RESPONSES/....md`.
    80	Option 2 is the proven path for overnight batches since CC adapted
    81	to it 2026-04-24.
    82	
    83	**Response size gotcha:** Codex returns full reasoning transcript
    84	(100-300 KB typical). Final verdict + findings are at the END of
    85	the response file, not the top. When synthesizing: use `tail -250`
    86	or parse for the last `Model: gpt-5.X` marker. Codex tends to
    87	repeat its final answer after the transcript, so the bottom is
    88	the authoritative section.
    89	
    90	**Use for:**
    91	- Review of a completed diff before commit (adversarial review)
    92	- Specific bug hypothesis testing ("is this a race or a deadlock?")
    93	- Concurrency-heavy code (ZMQ, asyncio, subprocess)
    94	- Short audit of a single file or small diff (≤ 500 lines)
    95	
    96	**Do NOT use for:**
    97	- Long-prose strategy writing
    98	- "Review the entire repo"
    99	- Anything that requires loading > 10 files at once
   100	
   101	### Gemini CLI — Gemini 3.1 Pro Preview
   102	
   103	**Strength:** wide-context architectural analysis. 1M token window lets
   104	you drop the entire CryoDAQ src tree into one prompt and ask
   105	cross-cutting questions. Strong on multi-file drift detection, impact
   106	analysis, doc-vs-code reconciliation, finding patterns across many
   107	files. 3.1 Pro improved long-horizon stability + tool orchestration
   108	over 2.5 Pro (Feb 2026 release), scores Artificial Analysis Intelligence
   109	Index 57 (top in class at release). Three-tier thinking modes (low /
   110	medium / high) added.
   111	
   112	**Weakness:** verbosity. Default response size is 3-10x what you asked
   113	for. Needs explicit "maximum 800 words" or "single markdown table, no
   114	prose". Can be confidently wrong on narrow hot-path bugs that Codex
   115	would catch. Architect voice — tends toward summary statements over
   116	specific findings without line refs. Higher time-to-first-token than
   117	2.5 Pro (~30s) — noticeable for interactive use, irrelevant for
   118	background batches.
   119	
   120	**Always pass:** `-m gemini-3.1-pro-preview` (full model string
   121	required — plain `pro` may resolve to 2.5 on older CLI installs, and
   122	`--model pro` defaults to auto-routing which can include flash). For
   123	audits → `--background` or `--yolo` if tool approval would block.
   124	
   125	**Version note:** Gemini 3.1 Pro Preview released 2026-02-19. Previous
   126	was Gemini 2.5 Pro. Auto-route is now Gemini 3 family by default on
   127	recent Gemini CLI. Older `gemini-2.5-pro` endpoint still works but is
   128	strictly worse; no reason to prefer it.
   129	
   130	**Signature signal:** section-headed reports with tables, high-level
   131	recommendations. Watch for confident claims without file:line backing —
   132	those are often hallucinated.
   133	
   134	**Budget:** Google AI Pro — daily quota via OAuth (consumer Gemini app
   135	limits apply; CLI shows limit-reached banner when hit). Individual deep
   136	audit counts as 1 request but may take 60-90 min of wall-clock.
   137	
   138	**Use for:**
   139	- Wide audit ("find architectural drift across the whole engine")
   140	- Doc-vs-code reconciliation over many files
   141	- Second opinion on architecture decisions where Codex is too narrow
   142	- Loading entire specs + entire source tree at once
   143	
   144	**Do NOT use for:**
   145	- Short-scope bug review (use Codex)
   146	- Anything where you need < 500-word output (Gemini will overwrite)
   147	- Quick yes/no decisions
   148	
   149	### GLM-5.1 — Zhipu AI via Chutes
   150	
   151	**Strength:** cheap per token. OK on routine code transformations,
   152	translation RU/EN/ZH, baseline question-answering. Fine for bulk
   153	mechanical work where a second cheap opinion is nice but not
   154	load-bearing.
   155	
   156	**Weakness:** three specific ones.
   157	1. **Identity leakage** — trained partly on Claude outputs; will claim
   158	   "I am Claude" on introspection. Do not trust any self-identification.
   159	   Authority on what model responded: `tail ~/.claude-code-router/logs/ccr-*.log | grep '"model":"'`.
   160	2. **Falls apart at scale** — 50+ file contexts, complex multi-step
   161	   reasoning, or sophisticated concurrency bugs — output becomes
   162	   plausible word salad. Hypotheses about B1-class bugs were wrong
   163	   last week.
   164	3. **Hallucinates with confidence** — when asked about things it
   165	   doesn't know, generates fluent false detail instead of saying
   166	   "unknown".
   167	
   168	**Budget:** Chutes pay-as-you-go, very cheap (~$1-3 per full session,
   169	$0.5 per typical code transform).
   170	
   171	**Use for:**
   172	- Translation RU↔EN of technical text
   173	- Draft of mechanical code transformation CC will then verify
   174	  itself before commit
   175	- Batch rename / rewrite where failures are trivially detectable
   176	  (tests catch them)
   177	- Cheap second opinion to check one specific claim — verify its
   178	  answer against another source if it matters
   179	
   180	**Do NOT use for:**
   181	- Anything safety-critical
   182	- Any decision that would land unchecked on master
   183	- Anything where "sounds plausible" matters more than correctness
   184	- Primary coordinator (this is CC's role, always)
   185	
   186	### Kimi K2.6 — Moonshot AI
   187	
   188	**Strength:** 256K context window for long documents + math-heavy
   189	tasks. Stronger on literary/language tasks than the others. Lower
   190	hallucination rate than GLM on the domain it knows.
   191	
   192	**Weakness:** same identity-leak issues as GLM. Less mature for
   193	narrow-scope code debugging than Codex. Chinese-centric training
   194	shows in some edge cases (date formats, unit conventions). If
   195	K2.6 is genuinely new (post-2026-Q1), profile is partly inferred
   196	from K2.5 — verify in practice.
   197	
   198	**Budget:** Chutes pay-as-you-go, similar to GLM.
   199	
   200	**Use for:**
   201	- Reading a single very long document (> 50K tokens) and
   202	  summarizing it
   203	- Math derivations where showing work matters
   204	- Specific document digestion tasks with clear output format
   205	- Contradiction detection between multiple documents (had some
   206	  success on 2026-04-22 hardening pass)
   207	
   208	**Do NOT use for:**
   209	- Primary code review (Codex is better)
   210	- Wide-scope architecture work (Gemini is better)
   211	- Anything where its identity leak could cause architect to
   212	  misread the output as CC's
   213	
   214	### Claude Code (CC / Opus 4.7) — coordinator
   215	
   216	Not a consultant for itself. If CC needs a second CC opinion, write
   217	the question down, stop, ask architect on next available session.
   218	Parallel CC sessions on the same repo violate `docs/ORCHESTRATION.md`
   219	§3 (one coordinator at a time).
   220	
   221	## 2. Routing decision tree
   222	
   223	Start here. Do NOT improvise routing.
   224	
   225	```
   226	Is the task a code review of an existing diff?
   227	  │
   228	  ├─ YES
   229	  │   │
   230	  │   ├─ diff < 500 lines, narrow scope (1-3 files)
   231	  │   │     → Codex solo (adversarial)
   232	  │   │
   233	  │   ├─ diff > 500 lines OR touches > 5 files
   234	  │   │     → Gemini solo (architectural impact)
   235	  │   │
   236	  │   └─ safety-critical diff (SafetyManager, interlocks, drivers)
   237	  │         → Codex + Gemini adversarial pair, synthesize both
   238	  │
   239	  ├─ NO — is it a draft of NEW content (code, spec, doc)?
   240	  │   │

exec
/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Projects/cryodaq/docs/ORCHESTRATION.md | sed -n '1,120p;150,240p;318,360p;400,460p;560,660p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	# CryoDAQ agent orchestration — CC-centric swarm model
     2	
     3	**Authoritative as of 2026-04-23.** Supersedes ad-hoc multi-agent
     4	coordination from 2026-04-21 to 2026-04-23.
     5	
     6	**Who reads this:** every agent session (Claude Code, Codex CLI,
     7	Gemini CLI, GLM via CCR, architect web Claude, metaswarm). If you
     8	are starting a session on this repo, read this document first.
     9	
    10	**Who owns this:** Vladimir Fomenko (architect). Changes go through
    11	a commit by Vladimir, not by any agent.
    12	
    13	---
    14	
    15	## 1. Why this document exists
    16	
    17	Between 2026-04-21 and 2026-04-23 the repository accumulated:
    18	
    19	- 4 parallel feature branches, none merged to master
    20	- 9 duplicate commits (same title, different SHA) between
    21	  `codex/b1-truth-recovery` and `codex/safe-merge-b1-truth-recovery`
    22	- 12 untracked `REPO_HARDENING_*.md` / `REVIEW_*.md` /
    23	  `*_AUDIT*.md` files in repo root, generated by reviewers with
    24	  no home
    25	- 4 new infrastructure directories (`.swarm/`, `.omc/`,
    26	  `.audit-run/`, `agentswarm/`) each containing state of a
    27	  different orchestrator attempt
    28	- `b2b4fb5` (hardening gate for B1 capture probe) landed 45 min
    29	  before `157c4bc` (IV.7 ipc:// transport) without anyone noticing
    30	  the hardening gate's assumptions would reject a healthy ipc://
    31	  bridge — so IV.7 failed runtime and was blamed, instead of the
    32	  gate being re-examined
    33	- `SESSION_DETAIL_2026-04-20.md` (93 KB architect context dump)
    34	  remained untracked and could have been lost at any moment
    35	
    36	None of this happened because the models were bad at individual
    37	tasks. It happened because there was no central coordinator, no
    38	artifact discipline, and no merge cadence.
    39	
    40	This document fixes that. The rules below are not suggestions.
    41	
    42	---
    43	
    44	## 2. Core principle
    45	
    46	**Claude Code (`claude` CLI, locally or via `ccr code` during
    47	quota windows) is the central coordinator for all agent work on
    48	this repository.**
    49	
    50	Every other model — Codex CLI, Gemini CLI, GLM, Kimi, DeepSeek,
    51	metaswarm agents — operates in **consultant mode**: they produce
    52	text (reviews, proposals, specs, analyses, code drafts) which CC
    53	reads, synthesizes, and converts into final action. Consultants
    54	never push directly. Consultants never create branches.
    55	Consultants never drop files into the repository filesystem
    56	except via CC.
    57	
    58	CC is a single thread of responsibility. If something lands on
    59	master or any branch, CC landed it and CC can explain why.
    60	
    61	The architect (Vladimir, possibly web Claude during architect
    62	sessions) provides mission, constraints, priorities. CC executes.
    63	
    64	---
    65	
    66	## 3. Role matrix
    67	
    68	| Role | Who | Can commit? | Can create branch? | Can merge? | Can write files in repo? | Primary output |
    69	|------|-----|-------------|--------------------|------------|--------------------------|----------------|
    70	| Architect | Vladimir, web Claude (during architect sessions) | yes (manual) | yes | yes | yes | mission, specs, review of CC work |
    71	| Coordinator | Claude Code | yes | yes, one at a time | yes, after gate | yes | code changes, commits, integration |
    72	| Consultant (review) | Codex, Gemini, Kimi | no | no | no | no — output goes through CC | critique text, counter-proposals |
    73	| Consultant (draft) | GLM, DeepSeek, Codex | no | no | no | no — output goes through CC | code drafts, plans |
    74	| Executor (fallback) | architect web Claude during CC quota outage | yes (via architect) | rare | rare | yes | direct patches delivered through Vladimir |
    75	
    76	**One coordinator at a time.** Do not run two CC sessions in
    77	parallel on the same branch. Do not run metaswarm orchestrator
    78	concurrently with direct CC coordination. Pick one driver, stick
    79	with it for the feature.
    80	
    81	---
    82	
    83	## 4. Consultant invocation protocol
    84	
    85	When CC needs a consultant, the call follows a fixed shape.
    86	
    87	### 4.1 Dispatch
    88	
    89	CC writes a consultation brief at
    90	`artifacts/consultations/<YYYY-MM-DD>/<topic>/<consultant>.prompt.md`.
    91	
    92	The brief includes:
    93	- Mission (one paragraph)
    94	- Required context files (list of paths — consultant reads these)
    95	- Specific question(s) — numbered
    96	- Expected output format (e.g. "markdown table, ≤ 3 pages")
    97	- Deadline / budget (time limit or token budget if applicable)
    98	- Response file path — where consultant output goes
    99	
   100	CC then invokes the consultant tool (`/codex:rescue`,
   101	`/gemini:rescue`, etc.) passing the brief path.
   102	
   103	### 4.2 Response
   104	
   105	Consultant response lands at
   106	`artifacts/consultations/<YYYY-MM-DD>/<topic>/<consultant>.response.md`.
   107	
   108	CC reads the response in full before synthesizing. If the
   109	response is junk (< 500 words of actual content, no file:line
   110	refs, evasive on specific questions) CC logs it as junk in the
   111	decision ledger (§6.3) and either retries with a tighter prompt
   112	or drops that consultant from the decision.
   113	
   114	### 4.3 Synthesis
   115	
   116	After all consultations, CC writes a synthesis at
   117	`artifacts/consultations/<YYYY-MM-DD>/<topic>/synthesis.md`
   118	covering:
   119	- Short summary of what each consultant said
   120	- Points of agreement across consultants
   150	
   151	### 5.1 Branch types
   152	
   153	| Type | Name pattern | Lifetime | Creator |
   154	|------|--------------|----------|---------|
   155	| Main | `master` | forever | — |
   156	| Feature | `feat/<slug>` | ≤ 2 days | CC |
   157	| Experiment | `experiment/<slug>` | ≤ 1 day | CC |
   158	| Hotfix | `hotfix/<slug>` | ≤ 4 hours | CC |
   159	| Architect fork | `arch/<yyyy-mm-dd>-<purpose>` | until merged | architect |
   160	
   161	Branch prefixes `codex/`, `gemini/`, `kimi/`, `agent/`,
   162	`consultant/` are forbidden. Consultants do not own branches.
   163	
   164	### 5.2 One active feature branch
   165	
   166	At most one active feature or experiment branch at a time.
   167	If a second task becomes urgent:
   168	- Either finish + merge the current branch, or
   169	- Abort it (`git branch -D`, log the abort in ROADMAP with SHA
   170	  and reason)
   171	
   172	This rule exists because of what happened 2026-04-21:
   173	`codex/b1-truth-recovery` and `codex/safe-merge-b1-truth-recovery`
   174	were parallel rewrites of the same work — 9 duplicate commits,
   175	wasted effort, ambiguous merge target.
   176	
   177	### 5.3 Merge cadence
   178	
   179	Feature branches live ≤ 2 days. At end of day 2:
   180	- **Pass:** merge to master (via fast-forward or explicit merge
   181	  commit), delete branch, delete worktree, push
   182	- **Fail:** revert any changes that cannot land cleanly, commit
   183	  a "postmortem.md" artifact explaining what was tried and what
   184	  did not work, delete branch
   185	
   186	A branch that has sat for 3+ days without merge or abort gets
   187	automatically aborted by CC at the start of the next session,
   188	no exceptions. The risk of stale branch + parallel drift + merge
   189	conflict chain exceeds any value the branch still holds.
   190	
   191	### 5.4 Worktree naming
   192	
   193	Worktrees live in `.worktrees/` (enforced invariant — gitignored
   194	per commit `587bea8`, 2026-04-23). The worktree directory name MUST
   195	match the branch name exactly:
   196	
   197	    .worktrees/feat-<slug>/          checked out on feat/<slug>
   198	    .worktrees/experiment-<slug>/    checked out on experiment/<slug>
   199	
   200	The 2026-04-23 mismatch (`.worktrees/codex-safe-merge-b1-truth-recovery`
   201	checked out on `experiment/iv7-ipc-transport`) is what the rule
   202	prevents. If CC ever sees a mismatch, first action is to fix the
   203	naming, not to continue work in the confused state.
   204	
   205	### 5.5 Commit message protocol
   206	
   207	Every commit on any branch must include in its body:
   208	- **Ref:** which plan, spec, or issue this commit addresses
   209	  (file path or slug)
   210	- **Batch:** if part of a multi-commit batch, which number
   211	  (e.g. "IV.7 / commit 1 of 3")
   212	- **Risk:** one-line risk assessment, especially for changes to
   213	  `launcher.py`, `engine.py`, `safety_manager.py`, `zmq_*.py`
   214	
   215	Example:
   216	
   217	```
   218	zmq(transport): switch loopback default to ipc:// on unix
   219	
   220	Ref: CC_PROMPT_IV_7_IPC_TRANSPORT.md
   221	Batch: IV.7 / commit 1 of 2
   222	Risk: IPC-only sockets on macOS/Linux; Windows retains tcp://.
   223	  Stale socket file cleanup via _prepare_ipc_path() required
   224	  before bind; crash recovery depends on this.
   225	```
   226	
   227	Commits without `Ref:` or `Risk:` are a signal CC is working
   228	without architect-approved plan. Architect will ask why.
   229	
   230	---
   231	
   232	## 6. Artifact discipline
   233	
   234	### 6.1 Where things live
   235	
   236	```
   237	docs/
   238	├── ORCHESTRATION.md          ← this file
   239	├── design-system/            ← UI source of truth, do not touch without architect
   240	├── audits/                   ← archived historical audits, one subdir per date
   318	
   319	If CC is about to land a change that hardens, tightens, or adds
   320	a gate to an existing tool (diag probe, test harness, health
   321	check), and there is an **active feature branch** (§5.2), CC
   322	must:
   323	
   324	1. Check whether the hardening could affect the feature
   325	2. If yes: hold the hardening until feature lands OR merges into
   326	   the feature branch and the feature branch is retested
   327	3. If no: document why not in the commit's `Risk:` line
   328	
   329	The 2026-04-23 mistake: `b2b4fb5` hardened the bridge startup
   330	probe 45 min before IV.7 `157c4bc` added ipc:// transport. The
   331	hardened probe had tcp://-flavoured assumptions about "bridge
   332	healthy." ipc:// bridge may have been healthy but the probe
   333	didn't recognize it and aborted the capture. IV.7 then got
   334	blamed.
   335	
   336	Active branches are known. `git worktree list` lists them. Check
   337	before tightening shared infra.
   338	
   339	---
   340	
   341	## 8. When the architect is unavailable
   342	
   343	The architect (Vladimir + web Claude) has weekly quota cycles.
   344	During quota exhaustion windows:
   345	
   346	- CC continues operating **only on previously-architected plans**.
   347	  If there is a `CC_PROMPT_*.md` with clear scope, CC can execute
   348	  it. If not, CC **stops**.
   349	- CC does not invent new directions.
   350	- CC does not start new feature branches for initiative-work.
   351	- CC handles bugs and regression fixes on in-progress work.
   352	- CC writes an `artifacts/handoffs/<date>-cc-to-architect.md` for
   353	  when architect returns.
   354	
   355	The 2026-04-21..23 failure mode was architect-absent multi-model
   356	initiative: five agents started branches and review packs without
   357	an architected plan. Do not do this. If architect is gone and
   358	there is no plan, stop.
   359	
   360	---
   400	
   401	At the end of every CC session:
   402	
   403	- [ ] Commit or stash all modified files (no dangling tracked
   404	  changes left overnight)
   405	- [ ] Write session ledger entry if decisions were made
   406	- [ ] Push active branch to origin (unless explicitly told not to)
   407	- [ ] If architect is absent, write handoff to
   408	  `artifacts/handoffs/<date>-cc-to-architect.md`
   409	
   410	---
   411	
   412	## 11. Known active plans (as of 2026-04-23 evening)
   413	
   414	| Plan | Spec file | Status |
   415	|------|-----------|--------|
   416	| IV.7 | `CC_PROMPT_IV_7_IPC_TRANSPORT.md` | Failed runtime 2026-04-23; likely blocked by unrelated hardening (`b2b4fb5`); **next architect action**: test the hypothesis — revert hardening on iv7 worktree, rerun diag, see if ipc:// was actually healthy |
   417	| Repo cleanup | this document, §§ 6, 5.2 | ✅ DONE (commits `adb49fe`..`8ebc893`, 2026-04-23) — 12 root .md archived (11 to audits, 1 preserved as blessed dossier), agent workspaces gitignored, duplicate branches pruned, worktree naming aligned |
   418	| Т4 interlock | no spec; see `HANDOFF_2026-04-20_GLM.md` §4 | Pending — commit config changes if not already |
   419	| Orchestration v1.1 | this document update, 2026-04-23 | ✅ DONE — incorporates calibration lessons from cleanup baseline session |
   420	
   421	No other plans are active. If a consultant or agent claims to
   422	be working on something, it must be referenceable as a plan
   423	here. If not — STOP and escalate to architect.
   424	
   425	---
   426	
   427	## 12. Reference — the failure modes this document prevents
   428	
   429	For future generations of CC / agents reading this to understand
   430	why the rules exist:
   431	
   432	1. **Parallel rewrites.** 2026-04-21: `codex/b1-truth-recovery`
   433	   and `codex/safe-merge-b1-truth-recovery` each produced a
   434	   9-commit "tools + docs + runbook" chain with identical commit
   435	   messages and different SHAs. Nobody needed the second chain.
   436	   Rule preventing it: §5.2 (one active feature branch).
   437	
   438	2. **Root-directory markdown flood.** 2026-04-21..23: 12 new
   439	   .md files in repo root, produced by different
   440	   review / hardening / audit passes, no clear home, mostly
   441	   untracked. Rule preventing it: §6.2 (strict root whitelist).
   442	
   443	3. **Hardening / feature collision.** 2026-04-23: `b2b4fb5`
   444	   hardened the B1 probe without considering that `157c4bc`
   445	   (landed 45 min later) would switch transport to ipc://. The
   446	   hardened probe's tcp://-flavoured assumptions may have been
   447	   what killed the IV.7 capture, not the ipc:// transport
   448	   itself. Rule preventing it: §7.
   449	
   450	4. **No-leader multi-agent drift.** 2026-04-21: five agents
   451	   (Codex, Gemini, Kimi, metaswarm, possibly others) produced
   452	   review output that was never synthesized into action. Each
   453	   proposed different next steps. No merge to master. No
   454	   singular decision. Rule preventing it: §2 (CC as sole
   455	   coordinator), §4 (synthesis artifact required).
   456	
   457	5. **Lost context.** `SESSION_DETAIL_2026-04-20.md` (93 KB
   458	   architect context dump) lived untracked for three days,
   459	   could have been lost. Rule preventing it: §10 end-of-session
   460	   checklist ("no dangling tracked changes left overnight"
   560	  otherwise be lost (per §13.4)
   561	- Include additional context in session ledger beyond what plan
   562	  explicitly asked for
   563	
   564	CC is NOT authorized, even with autonomy band:
   565	
   566	- To merge branches not explicitly named in plan
   567	- To delete files outside `git branch -D` targets in the plan
   568	- To rewrite commit history on master (amend pushed commits,
   569	  rebase shared branches, force-push)
   570	- To invoke consultants for decisions this document already
   571	  covers
   572	- To create new feature branches for initiative work while
   573	  architect is unavailable (§8)
   574	
   575	### 13.6 The calibration principle
   576	
   577	Rules that over-stop waste architect time. Rules that under-stop
   578	risk silent breakage. The session ledger + handoff artifacts are
   579	the mechanism that lets us run with relaxed stopping discipline
   580	— architect reviews the ledger end-of-day and catches any
   581	adaptation that should have been a stop. If that review pattern
   582	breaks down (architect misses something important in the ledger),
   583	then specific rules get tightened. Otherwise, stay in autonomy
   584	band.
   585	
   586	---
   587	
   588	*This document is the contract. If you are an agent on this repo
   589	and you don't like a rule, propose a change through the
   590	architect. Do not work around it.*
   591	
   592	*— Vladimir Fomenko (architect), authored by Claude Opus 4.7
   593	(web), 2026-04-23.*

exec
/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-24-overnight-swarm-launch.md | sed -n '1,120p'; test -f /Users/vladimir/Projects/cryodaq/CC_PROMPT_OVERNIGHT_SWARM_2026-04-24.md && nl -ba /Users/vladimir/Projects/cryodaq/CC_PROMPT_OVERNIGHT_SWARM_2026-04-24.md | sed -n '1,140p' || true" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	# 2026-04-24 — overnight swarm launch ledger
     2	
     3	## Context
     4	
     5	Executing `CC_PROMPT_OVERNIGHT_SWARM_2026-04-24.md`. Ten scoped
     6	consultation jobs dispatched to Codex (gpt-5.5 / reasoning high ×
     7	5 tasks) and Gemini (gemini-2.5-pro × 5 tasks). All artifacts
     8	collect under
     9	`artifacts/consultations/2026-04-24-overnight/`.
    10	
    11	Morning session synthesizes per-stream, master summary, architect
    12	review.
    13	
    14	## Dispatch status — 10/10
    15	
    16	| # | task | consultant | brief path | response path | dispatch | status |
    17	|---|---|---|---|---|---|---|
    18	| 1 | codex-01-r123-pick | Codex gpt-5.5/high | `BRIEFS/codex-01-r123-pick.prompt.md` | `RESPONSES/codex-01-r123-pick.response.md` | ~01:15 | RUNNING (PID 48746 wrapper, 48757 codex) |
    19	| 2 | codex-02-shared-context | Codex gpt-5.5/high | `BRIEFS/codex-02-shared-context.prompt.md` | `RESPONSES/codex-02-shared-context.response.md` | ~01:15 | RUNNING (PID 48747 wrapper, 48758 codex) |
    20	| 3 | codex-03-launcher-concurrency | Codex gpt-5.5/high | `BRIEFS/codex-03-launcher-concurrency.prompt.md` | `RESPONSES/codex-03-launcher-concurrency.response.md` | ~01:15 | RUNNING (PID 48748 wrapper, 48759 codex) |
    21	| 4 | codex-04-alarm-v2-threshold | Codex gpt-5.5/high | `BRIEFS/codex-04-alarm-v2-threshold.prompt.md` | `RESPONSES/codex-04-alarm-v2-threshold.response.md` | ~01:15 | RUNNING (PID 48749 wrapper, 48763 codex) |
    22	| 5 | codex-05-thyracont-probe | Codex gpt-5.5/high | `BRIEFS/codex-05-thyracont-probe.prompt.md` | `RESPONSES/codex-05-thyracont-probe.response.md` | ~01:15 | RUNNING (PID 48750 wrapper, 48764 codex) |
    23	| 6 | gemini-01-r123-blast | Gemini 2.5-pro | `BRIEFS/gemini-01-r123-blast.prompt.md` | `RESPONSES/gemini-01-r123-blast.response.md` | ~01:17 (relaunch) | QUEUED — in serial chain PID 50252 |
    24	| 7 | gemini-02-arch-drift | Gemini 2.5-pro | `BRIEFS/gemini-02-arch-drift.prompt.md` | `RESPONSES/gemini-02-arch-drift.response.md` | ~01:17 | QUEUED in chain |
    25	| 8 | gemini-03-doc-reality | Gemini 2.5-pro | `BRIEFS/gemini-03-doc-reality.prompt.md` | `RESPONSES/gemini-03-doc-reality.response.md` | ~01:17 | QUEUED in chain |
    26	| 9 | gemini-04-safe-merge-eval | Gemini 2.5-pro | `BRIEFS/gemini-04-safe-merge-eval.prompt.md` | `RESPONSES/gemini-04-safe-merge-eval.response.md` | ~01:17 | QUEUED in chain |
    27	| 10 | gemini-05-coverage-gaps | Gemini 2.5-pro | `BRIEFS/gemini-05-coverage-gaps.prompt.md` | `RESPONSES/gemini-05-coverage-gaps.response.md` | ~01:17 | QUEUED in chain |
    28	
    29	Tracking file: `artifacts/consultations/2026-04-24-overnight/.pids`
    30	(wrapper PIDs + chain PID).
    31	
    32	## Adaptations from plan (§13.3 ledger format)
    33	
    34	### 01:14 — CLI-direct dispatch instead of slash commands
    35	
    36	Plan said: ``/codex:rescue --model gpt-5.5 --reasoning high --background ...``
    37	Reality: Claude Code slash-command dispatch with `--background` is
    38	not a shell-level invocation. The underlying binaries `codex` and
    39	`gemini` are on PATH. Adapted to: direct `codex exec` and `gemini`
    40	CLI invocation, wrapped in `nohup bash -c '...' </dev/null >/dev/null 2>&1 &`
    41	for full detachment from session shell.
    42	
    43	Codex flags used:
    44	- `-m gpt-5.5`
    45	- `-c model_reasoning_effort="high"` (TOML override for reasoning)
    46	- `-s read-only` (sandbox)
    47	- `--skip-git-repo-check` (worktree-aware dispatch)
    48	- stdin-fed prompt via `< BRIEF.prompt.md`
    49	- stdout captured via `> RESPONSE.response.md 2>&1`
    50	
    51	Gemini flags used (after initial failure — see 01:16 below):
    52	- `-m gemini-2.5-pro`
    53	- `--yolo` (auto-accept tool calls so Gemini can read repo files
    54	  and run git)
    55	- `-o text`
    56	- `-p "$(cat BRIEF.prompt.md)"`
    57	- stdout captured via `> RESPONSE.response.md 2>&1`
    58	
    59	### 01:14 — Model-string probe before batch dispatch
    60	
    61	Plan §3.7 said: if `/codex` rejects `gpt-5.5`, fall back to `gpt-5.4`.
    62	Ran a 3-token round-trip probe with `echo "Say 'probe ok'" | codex exec -m gpt-5.5 ...`
    63	before the batch. Probe returned "probe ok" cleanly, confirming
    64	gpt-5.5 is accepted upstream. No fallback needed.
    65	Same probe for Gemini 2.5-pro — returned "probe ok". Also fine.
    66	
    67	### 01:16 — Gemini parallel dispatch failure, relaunched as serial chain
    68	
    69	First dispatch: 5 Gemini jobs fired in parallel same as Codex.
    70	After ~20 seconds, all 5 Gemini response files contained variants
    71	of:
    72	- `Attempt 1 failed: You have exhausted your capacity on this
    73	  model. Your quota will reset after 0s`
    74	- `Error executing tool run_shell_command: Tool "run_shell_command"
    75	  not found` (Gemini CLI in default approval mode blocks shell
    76	  access — it cannot read files or run git to fulfill the briefs)
    77	
    78	Two distinct issues:
    79	1. **Rate limit.** Parallel 5× gemini-2.5-pro calls hit per-minute
    80	   ceiling.
    81	2. **Tool access.** Default approval mode refuses `run_shell_command`;
    82	   briefs require Gemini to read multiple files + run `git show`.
    83	
    84	Adaptation:
    85	- Killed wrapper PIDs for the five Gemini jobs (`awk '/^gemini-/'
    86	  .pids | kill`). Pre-existing unrelated gemini processes
    87	  (PIDs 8270, 8283, 8297, 3+ days elapsed — not mine) were NOT
    88	  touched.
    89	- Zeroed the five Gemini response files to discard the partial
    90	  error output.
    91	- Relaunched Gemini as a single serial chain in a detached
    92	  `nohup bash -c '...' &` — jobs run one at a time with 30-s
    93	  gaps, avoiding rate limits.
    94	- Added `--yolo` to grant Gemini tool access so it can actually
    95	  read the repo files the briefs reference.
    96	- Single tracking PID for the chain: **50252**. Individual
    97	  Gemini job PIDs rotate as the chain progresses.
    98	
    99	Expected: chain runs for ~30-60 min total (5 jobs × 5-10 min
   100	each + 30s gaps). If a later job still rate-limits, it will
   101	retry internally then move on.
   102	
   103	## Codex confirmation — gpt-5.5 accepted
   104	
   105	Probe result: `codex exec -m gpt-5.5 -c model_reasoning_effort="high"`
   106	returned cleanly. No fallback to gpt-5.4 needed. §3.7 condition
   107	did not fire.
   108	
   109	Reasoning header visible in Codex output file (see
   110	`RESPONSES/codex-01-r123-pick.response.md` lines 1-13):
   111	```
   112	OpenAI Codex v0.124.0 (research preview)
   113	model: gpt-5.5
   114	reasoning effort: high
   115	sandbox: read-only
   116	```
   117	
   118	## Brief inventory
   119	
   120	All 10 briefs authored per skill §§ 8.1 / 8.2 templates:
     1	# Overnight swarm batch — 2026-04-24 → 2026-04-25 morning
     2	
     3	**Mission.** Dispatch 10 consultation jobs across Codex and Gemini
     4	tonight. Let them run overnight. Morning: CC synthesizes per-stream,
     5	architect (Vladimir + web Claude) reviews syntheses and makes decisions.
     6	
     7	**Economics.** Codex (ChatGPT Plus) and Gemini (Google AI Pro) are
     8	prepaid subscriptions. Cost of running them tonight is zero marginal.
     9	Cost of NOT running them is opportunity loss: we wake up without data.
    10	
    11	**Scope discipline.** 10 tasks. No more. Each task has its own brief
    12	file, response file, clear expected output format. No free-form
    13	"explore the repo" invitations — every task is scoped and answerable.
    14	
    15	**GLM and Kimi excluded from this run** because (a) they are accessed
    16	via CCR as CC-with-different-model rather than independent processes,
    17	(b) yesterday's tests showed low signal-to-noise, (c) cost is Chutes
    18	pay-as-you-go vs Codex/Gemini sunk cost. Revisit later if needed.
    19	
    20	---
    21	
    22	## 1. Directory structure
    23	
    24	All artifacts under `artifacts/consultations/2026-04-24-overnight/`:
    25	
    26	```
    27	artifacts/consultations/2026-04-24-overnight/
    28	├── BRIEFS/                          ← prompts sent to consultants
    29	│   ├── codex-01-r123-pick.prompt.md
    30	│   ├── codex-02-shared-context.prompt.md
    31	│   ├── codex-03-launcher-concurrency.prompt.md
    32	│   ├── codex-04-alarm-v2-threshold.prompt.md
    33	│   ├── codex-05-thyracont-probe.prompt.md
    34	│   ├── gemini-01-r123-blast.prompt.md
    35	│   ├── gemini-02-arch-drift.prompt.md
    36	│   ├── gemini-03-doc-reality.prompt.md
    37	│   ├── gemini-04-safe-merge-eval.prompt.md
    38	│   └── gemini-05-coverage-gaps.prompt.md
    39	├── RESPONSES/                       ← raw responses from consultants
    40	│   ├── codex-01-r123-pick.response.md
    41	│   ├── ... (parallel to BRIEFS)
    42	├── STREAM_SYNTHESES/                ← CC morning work
    43	│   ├── A-r123-repair-choice.md
    44	│   ├── B-b1-and-concurrency.md
    45	│   ├── C-repo-health.md
    46	│   └── D-safe-merge-disposition.md
    47	└── MASTER_SUMMARY.md                ← CC final rollup for architect
    48	```
    49	
    50	Create all directories in Phase 0 before dispatches.
    51	
    52	---
    53	
    54	## 2. Task streams
    55	
    56	### Stream A — b2b4fb5 repair choice (2 tasks)
    57	
    58	**Codex-01** adversarial pick between R1/R2/R3.
    59	**Gemini-01** blast radius analysis R1/R2/R3.
    60	
    61	→ Morning synthesis: architect picks one of R1/R2/R3, CC implements on
    62	`feat/b2b4fb5-repair` branch in a follow-up session.
    63	
    64	### Stream B — B1 root cause + concurrency (3 tasks)
    65	
    66	**Codex-02** shared `zmq.Context()` race analysis in `zmq_subprocess.py`.
    67	Per `CODEX_ARCHITECTURE_CONTROL_PLANE.md` §1.1, IV.6 eliminated shared
    68	REQ socket but retained shared Context. This is the leading H4 candidate.
    69	
    70	**Codex-03** `launcher.py` concurrency sweep. Find any other
    71	lifecycle / race / ordering bugs beyond b2b4fb5. 1500-line file,
    72	safety-critical, worth a careful read.
    73	
    74	**Gemini-02** whole `src/cryodaq` architectural drift since v0.33.0.
    75	Wide audit using 1M context window — find patterns that silently broke,
    76	invariants violated, abstractions leaking.
    77	
    78	→ Morning synthesis: map of remaining B1 candidates (H4, H5, new
    79	ones), priority order for next investigation.
    80	
    81	### Stream C — Repo health (4 tasks)
    82	
    83	**Codex-04** `alarm_v2.py` KeyError for `cooldown_stall` fix approach.
    84	Small scope, known bug, produce patch spec.
    85	
    86	**Codex-05** `thyracont_vsp63d.py` `_try_v1_probe` checksum consistency
    87	review. Small scope, known brittleness, produce patch spec.
    88	
    89	**Gemini-03** doc-vs-code reality check. Top-level docs often drift
    90	from actual source. Verify claims in `CLAUDE.md` + `PROJECT_STATUS.md` +
    91	`ROADMAP.md` + `DOC_REALITY_MAP.md` against current `src/` truth.
    92	
    93	**Gemini-05** test coverage gaps. Which subsystems have weakest
    94	coverage? What tests should exist but don't? Prioritize by safety
    95	criticality.
    96	
    97	→ Morning synthesis: list of 2-5 day-and-done fixes (alarm_v2,
    98	thyracont, doc reconciliation), test-writing backlog ordered by
    99	priority.
   100	
   101	### Stream D — Safe-merge branch disposition (1 task)
   102	
   103	**Gemini-04** read 11 docs commits on `codex/safe-merge-b1-truth-recovery`
   104	and produce merge/drop recommendation per commit.
   105	
   106	→ Morning synthesis: list of commits to cherry-pick into master vs
   107	abandon. Architect executes in a follow-up session.
   108	
   109	---
   110	
   111	## 3. Dispatch protocol
   112	
   113	### 3.1 Pre-dispatch setup
   114	
   115	```bash
   116	mkdir -p artifacts/consultations/2026-04-24-overnight/{BRIEFS,RESPONSES,STREAM_SYNTHESES}
   117	```
   118	
   119	### 3.2 For each Codex task
   120	
   121	Create `BRIEFS/codex-NN-slug.prompt.md` using skill §8.1 template.
   122	
   123	Dispatch:
   124	
   125	```bash
   126	# Background so all 5 launch without CC blocking
   127	/codex:rescue --model gpt-5.5 --reasoning high --background \
   128	  --prompt "$(cat artifacts/consultations/2026-04-24-overnight/BRIEFS/codex-NN-slug.prompt.md)" \
   129	  --output artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-NN-slug.response.md
   130	```
   131	
   132	(Adapt to actual `/codex:rescue` flag names — they may differ. If
   133	`--prompt` is not a flag, heredoc the prompt. If `--output` not
   134	supported, capture via shell redirect or a wrapper script. Adapt and
   135	ledger.)
   136	
   137	After dispatch, run `/codex:status` to confirm all 5 Codex jobs are
   138	queued or running.
   139	
   140	### 3.3 For each Gemini task

exec
/opt/homebrew/bin/bash -lc "find /Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight -maxdepth 2 -type f | sort | sed -n '1,120p'; rg -n \"10/10|all .*landed|completed|DONE|MASTER_SUMMARY|Gemini.*serial|Codex parallel\" /Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight -S" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/.pids
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/BRIEFS/codex-01-r123-pick.prompt.md
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/BRIEFS/codex-02-shared-context.prompt.md
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/BRIEFS/codex-03-launcher-concurrency.prompt.md
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/BRIEFS/codex-04-alarm-v2-threshold.prompt.md
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/BRIEFS/codex-05-thyracont-probe.prompt.md
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/BRIEFS/codex-06-q4-equivalence.prompt.md
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/BRIEFS/gemini-01-r123-blast.prompt.md
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/BRIEFS/gemini-02-arch-drift.prompt.md
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/BRIEFS/gemini-03-doc-reality.prompt.md
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/BRIEFS/gemini-04-safe-merge-eval.prompt.md
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/BRIEFS/gemini-05-coverage-gaps.prompt.md
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/MASTER_SUMMARY.md
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-01-r123-pick.response.md
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-02-shared-context.response.md
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-03-launcher-concurrency.response.md
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-04-alarm-v2-threshold.response.md
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-05-thyracont-probe.response.md
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-06-q4-equivalence.response.md
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/RESPONSES/gemini-01-r123-blast.response.md
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/RESPONSES/gemini-02-arch-drift.response.md
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/RESPONSES/gemini-03-doc-reality.response.md
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/RESPONSES/gemini-04-safe-merge-eval.response.md
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/RESPONSES/gemini-05-coverage-gaps.response.md
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/STREAM_SYNTHESES/A-r123-repair-choice.md
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/STREAM_SYNTHESES/B-b1-and-concurrency.md
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/STREAM_SYNTHESES/C-repo-health.md
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/STREAM_SYNTHESES/D-safe-merge-disposition.md
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/STREAM_SYNTHESES/Q4-equivalence-synthesis.md
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/RESPONSES/gemini-04-safe-merge-eval.response.md:28:I have completed the analysis of the commits on the `codex/safe-merge-b1-truth-recovery` branch and created the requested report at `artifacts/consultations/2026-04-24-overnight/RESPONSES/gemini-04-safe-merge-eval.response.md`. The report contains a per-commit evaluation with recommendations to `MERGE`, `DROP`, or `CHERRY-PICK modified`, along with a summary of the overall patterns observed.
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/RESPONSES/gemini-03-doc-reality.response.md:92:I have completed the audit and created the report as requested.
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/RESPONSES/gemini-05-coverage-gaps.response.md:63:I have completed the audit and written the results to `artifacts/consultations/2026-04-24-overnight/RESPONSES/gemini-05-coverage-gaps.response.md`.
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-03-launcher-concurrency.response.md:245:If you haven't completed Phase 1, you cannot propose fixes.
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-03-launcher-concurrency.response.md:2869:    38	# the operation usually completed a few seconds later. Fast status
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/RESPONSES/gemini-01-r123-blast.response.md:17:In summary, R1 offers the best balance: it repairs the immediate bug with minimal impact, preserves the intended hardening (albeit in a more robust form), and does not interfere with future, more complex investigations into the ZMQ architecture.I have completed the analysis and created the report at `artifacts/consultations/2026-04-24-overnight/RESPONSES/gemini-01-r123-blast.response.md`.
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-04-alarm-v2-threshold.response.md:220:If you haven't completed Phase 1, you cannot propose fixes.
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/MASTER_SUMMARY.md:105:- Initial parallel 5× dispatch hit rate limit + default approval mode blocked `run_shell_command`. Relaunched as serial chain with `--yolo` tool access — all 5 completed (elapsed 01:17 → 01:36, ~20 min).
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/RESPONSES/gemini-02-arch-drift.response.md:42:I have completed the architectural drift audit and written the report to `artifacts/consultations/2026-04-24-overnight/RESPONSES/gemini-02-arch-drift.response.md`. All specified invariants were found to be held, and I have included additional findings on new architectural patterns and boundary integrity as requested.
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-01-r123-pick.response.md:285:[Just completed Task 2: Add verification function]
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-01-r123-pick.response.md:2700:    42	# the operation usually completed a few seconds later. Fast status
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-06-q4-equivalence.response.md:314:| Agent completed | VCS diff shows changes | Agent reports "success" |
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-02-shared-context.response.md:255:If you haven't completed Phase 1, you cannot propose fixes.
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-02-shared-context.response.md:778:    38	# the operation usually completed a few seconds later. Fast status
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-02-shared-context.response.md:1634:     5	> **Status 2026-04-20 afternoon:** Codex review completed. Original
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-02-shared-context.response.md:2745:docs/changelog/RETRO_ANALYSIS_V3.md:532:- `b803967`: Overview dashboard, XLSX export, DiskMonitor, completed export TODOs
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-02-shared-context.response.md:2764:docs/changelog/RETRO_ANALYSIS_V3.md:2428:| `b803967` | 2026-03-14T20:02:34+03:00 | Overview dashboard, XLSX export, DiskMonitor, completed export TODOs | `0.7.0` |
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-02-shared-context.response.md:2896:docs/changelog/archive/RETRO_ANALYSIS.md:1500:| 38 | `b803967` | 2026-03-14T20:02:34+03:00 | Overview dashboard, XLSX export, DiskMonitor, completed export TODOs |
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-02-shared-context.response.md:2962:docs/changelog/archive/RETRO_ANALYSIS_V2.md:1766:| `b803967` | 2026-03-14T20:02:34+03:00 | Overview dashboard, XLSX export, DiskMonitor, completed export TODOs | `0.6.0` |
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-02-shared-context.response.md:3425:docs/decisions/2026-04-23-cleanup-baseline.md:146:- **§11 "Known active plans" table update**: add status note "Repo cleanup — DONE (2026-04-23, commits adb49fe..cfee680)".
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-02-shared-context.response.md:3831:    70	        f"[{_ts()}] {label} DONE: total={i} fails={fails} "
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-02-shared-context.response.md:4644:mcp: codex_apps/github_fetch (completed)
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-02-shared-context.response.md:4646:mcp: codex_apps/github_fetch (completed)
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-02-shared-context.response.md:4648:mcp: codex_apps/github_fetch_file (completed)
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-02-shared-context.response.md:4650:mcp: codex_apps/github_fetch_file (completed)
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-02-shared-context.response.md:4652:mcp: codex_apps/github_fetch_file (completed)
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-02-shared-context.response.md:4654:mcp: codex_apps/github_fetch_file (completed)
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-05-thyracont-probe.response.md:220:If you haven't completed Phase 1, you cannot propose fixes.
/Users/vladimir/Projects/cryodaq/artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-05-thyracont-probe.response.md:2586:If you haven't completed Phase 1, you cannot propose fixes.

exec
/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Projects/cryodaq/ROADMAP.md | sed -n '1,120p;120,220p;220,420p;423,570p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	# CryoDAQ — Feature Roadmap
     2	
     3	> **Living document.** Updated 2026-04-20 after IV.2 close (HEAD `df43081`).
     4	> Companion to `PROJECT_STATUS.md` (infrastructure state) and
     5	> `docs/phase-ui-1/phase_ui_v2_roadmap.md` (UI rebuild phases).
     6	>
     7	> **Scope:** forward-looking **feature work** (new code, new capabilities).
     8	> NOT review / bugfix backlog — those live in batch specs
     9	> (`CC_PROMPT_IV_*_BATCH.md`).
    10	
    11	---
    12	
    13	## Status key
    14	
    15	- ✅ **DONE** — shipped and working
    16	- 🔧 **PARTIAL** — code exists, missing wiring / UI / tests
    17	- ⬜ **NOT STARTED** — spec only
    18	- 🔬 **RESEARCH** — requires physics / methodology work before code
    19	
    20	---
    21	
    22	## Quick index
    23	
    24	| # | Feature | Status | Effort | ROI |
    25	|---|---|---|---|---|
    26	| F1 | Parquet archive wire-up | ✅ DONE (UI + base dep, IV.4.F1) | S | H |
    27	| F2 | Debug mode toggle (verbose logging) | ✅ DONE (IV.4.F2) | S | H |
    28	| F3 | Analytics placeholder widgets → data wiring | ⬜ | M | M |
    29	| F4 | Analytics lazy-open snapshot replay | ⬜ | S | M |
    30	| F5 | Engine events → Hermes webhook | ⬜ | M | M |
    31	| F6 | Auto-report on experiment finalize | ✅ DONE (verified + per-experiment override, IV.4.F6) | S | H |
    32	| F7 | Web API readings query extension | ⬜ | L | M |
    33	| F8 | Cooldown ML prediction upgrade | 🔬 | L | M |
    34	| F9 | Thermal conductivity auto-report (TIM) | 🔬 | M | H |
    35	| F10 | Sensor diagnostics → alarm integration | ⬜ | M | M |
    36	| F11 | Shift handover enrichment | ✅ DONE (IV.4.F11, Telegram export deferred) | S | H |
    37	| F12 | Experiment templates UI editor | ⬜ | M | L |
    38	| F13 | Vacuum leak rate estimator | ⬜ | M | M |
    39	| F14 | Remote command approval (Telegram) | ⬜ | M | L |
    40	| F15 | Linux AppImage / .deb package | ⬜ | L | L |
    41	| F16 | Plugin hot-reload SDK + examples | ⬜ | M | L |
    42	| F17 | SQLite → Parquet cold-storage rotation | ⬜ | M | M |
    43	| F18 | CI/CD upgrade (coverage, matrix, releases) | ⬜ | M | L |
    44	
    45	Effort: **S** ≤200 LOC, **M** 200-600 LOC, **L** >600 LOC.
    46	ROI: **H** user value immediate, **M** clear but deferred, **L** nice-to-have.
    47	
    48	---
    49	
    50	## Planned batches
    51	
    52	Ordered by when we intend to ship them. Status at 2026-04-20.
    53	
    54	### IV.4 — Safe features batch
    55	
    56	**Target:** tag `0.34.0` (next increment after current `0.33.0`).
    57	
    58	**Status:** ✅ CLOSED at HEAD `7cb5634` (2026-04-20).
    59	All 4 findings PASS. Pending: real `git tag` command.
    60	
    61	Scope:
    62	- **F1** — Parquet UI export button + default pyarrow install
    63	- **F2** — Debug mode toggle
    64	- **F6** — Auto-report verification + report_enabled UI toggle
    65	- **F11** — Shift handover auto-sections
    66	
    67	Shipped: ~800 LOC, 4 commits, 5 amend cycles total, 863 GUI tests
    68	passing. No engine refactor.
    69	
    70	Spec: `CC_PROMPT_IV_4_BATCH.md` (closed).
    71	
    72	Commit SHAs:
    73	- F1 Parquet UI: `bf584ed` (2 amends)
    74	- F6 auto-report verify: `0ec842f` (0 amends)
    75	- F2 debug mode: `5f8b394` (2 amends)
    76	- F11 shift handover: `7cb5634` (2 amends)
    77	
    78	Telegram export in F11 deferred (out of IV.4 scope per Rule 4).
    79	
    80	### IV.5 — Stretch features batch
    81	
    82	**Target:** tag `0.35.0` after IV.4 closes, smoke passes, and ZMQ
    83	subprocess bug (see "Known broken" below) resolved.
    84	
    85	Scope:
    86	- **F3** — Analytics placeholder widgets data wiring
    87	  (requires engine-side `cooldown_history_get` command; non-trivial)
    88	- **F5** — Hermes webhook integration
    89	  (depends on Hermes service deployment on lab PC — coordinate with Vladimir)
    90	- **F17** — SQLite → Parquet cold rotation in housekeeping
    91	
    92	Estimated: ~1100-1300 LOC, 3 commits, ~7-8h CC. Includes engine changes.
    93	
    94	Spec: not yet drafted; pending IV.4 outcomes + Hermes service readiness.
    95	
    96	### Collaboration blocks (not autonomous)
    97	
    98	- **F9** TIM auto-report — requires physics review with Vladimir for
    99	  uncertainty budget correctness, GOST Р 54500.3-2011 compliance, methodology
   100	  cross-check against existing protocol documents.
   101	- **F8** Cooldown ML upgrade — requires training dataset curation from
   102	  historical SQLite files + model evaluation notebook.
   103	
   104	### Deferred (not scheduled)
   105	
   106	F4, F7, F10, F12, F13, F14, F15, F16, F18 — see individual entries below.
   107	
   108	---
   109	
   110	## Detailed feature entries
   111	
   112	### F1 — Parquet archive wire-up
   113	
   114	**Status:** 🔧 PARTIAL.
   115	
   116	Backend already works: `src/cryodaq/storage/parquet_archive.py` ships
   117	`export_experiment_readings_to_parquet()`, and
   118	`ExperimentManager.finalize_experiment()` already calls it best-effort
   119	on every experiment close — the file lands at
   120	`data/experiments/<id>/readings.parquet`. `pyarrow` is an optional
   120	`data/experiments/<id>/readings.parquet`. `pyarrow` is an optional
   121	dependency (`pip install -e ".[archive]"`).
   122	
   123	Missing pieces:
   124	
   125	1. **Default install.** Move `pyarrow` from `[archive]` extra into
   126	   base runtime deps in `pyproject.toml`. Cost: +60 MB install size.
   127	   Benefit: finalize Parquet hook never silently skips.
   128	2. **Archive UI export button.** The v2 ArchiveOverlay already has a
   129	   global bulk-export card (CSV / HDF5 / Excel). Add «Parquet» as the
   130	   fourth button, calling the same function as the finalize hook but
   131	   targeting a user-chosen output path via `QFileDialog.getSaveFileName`.
   132	3. **Per-experiment export button.** In ArchiveOverlay's details pane,
   133	   for each archived experiment add «Скачать Parquet» that links to
   134	   the existing `data/experiments/<id>/readings.parquet`.
   135	
   136	Tests: 10 new cases covering UI button wiring + file-dialog flow.
   137	
   138	### F2 — Debug mode toggle
   139	
   140	**Status:** ⬜ NOT STARTED.
   141	
   142	Operator needs to enable verbose file logging post-deployment to diagnose
   143	issues without recompiling or editing `logging_setup.py`.
   144	
   145	Implementation:
   146	
   147	1. `QSettings` key `logging/debug_mode` (persistent across sessions).
   148	2. QAction in Settings menu «Подробные логи (перезапуск)» with checkmark
   149	   reflecting current state.
   150	3. `logging_setup.setup_logging()` reads setting before configuring level:
   151	   `logging.DEBUG if debug_mode else logging.INFO`.
   152	4. Dialog informs operator that change requires launcher restart.
   153	5. Engine also respects the setting — via environment variable
   154	   `CRYODAQ_LOG_LEVEL=DEBUG` set by launcher before spawning engine.
   155	
   156	Tests: 5 new cases covering setting persist, menu toggle, env var pass-through.
   157	
   158	### F3 — Analytics placeholder widgets data wiring
   159	
   160	**Status:** ⬜ NOT STARTED.
   161	
   162	Phase III.C shipped 4 placeholder cards — layout correct, no data flow.
   163	Used in warmup + disassembly phases + one cooldown slot.
   164	
   165	Four widgets to wire:
   166	
   167	- **`r_thermal_placeholder`** (cooldown/bottom_right) — prediction of
   168	  when R_thermal stabilizes. Needs new engine service (R_thermal
   169	  predictor) or derivable from existing cooldown_service.
   170	- **`temperature_trajectory`** (warmup/main) — all temp channels on
   171	  shared axis, full-experiment time window. Reuses existing
   172	  `readings_history` command; just needs widget.
   173	- **`cooldown_history`** (warmup/bottom_right) — past cooldown durations
   174	  for comparison. Needs new engine command `cooldown_history_get` that
   175	  mines past experiment metadata + phase transitions.
   176	- **`experiment_summary`** (disassembly/main) — final summary card:
   177	  total duration, phase breakdown, min/max values, alarm count, artifact
   178	  links. Assembled from existing `experiment_status` + `readings_history`.
   179	
   180	Engine-side additions:
   181	- `cooldown_history_get` command (returns list of `{experiment_id,
   182	  duration_s, start_T, end_T, timestamp}` for past cooldowns)
   183	- Optional: `r_thermal_prediction` command if R_thermal predictor built
   184	  (else defer to F8)
   185	
   186	Estimated: ~600 LOC (400 GUI + 200 engine) + 30 tests.
   187	
   188	### F4 — Analytics lazy-open snapshot replay
   189	
   190	**Status:** ⬜ NOT STARTED. Residual from III.C.
   191	
   192	When operator opens Analytics overlay mid-experiment, fresh replay is
   193	empty — `set_cooldown()` was called before overlay existed. Widgets
   194	see no initial data until next snapshot push.
   195	
   196	Fix: shell caches last-known snapshot per widget ID (similar to existing
   197	pattern for `set_experiment`). On overlay construction, replay cached
   198	snapshots into newly-created widgets.
   199	
   200	Estimated: ~150 LOC + 10 tests.
   201	
   202	### F5 — Engine events → Hermes webhook
   203	
   204	**Status:** ⬜ NOT STARTED. Depends on Hermes service deployment.
   205	
   206	Configurable HTTP POST from `event_logger.log_event()`:
   207	
   208	```yaml
   209	# config/notifications.yaml
   210	webhooks:
   211	  - url: http://localhost:37777/cryodaq-event
   212	    events: [phase_change, fault_latched, experiment_finalize]
   213	    timeout_s: 2.0
   214	    retry_attempts: 0
   215	```
   216	
   217	Best-effort: timeout + swallow on failure (Hermes may be down).
   218	Payload shape: `{event, timestamp, experiment_id, phase, metadata}`.
   219	
   220	Unlocks: Obsidian campaign notes, GraphRAG indexing, Telegram Q&A
   220	Unlocks: Obsidian campaign notes, GraphRAG indexing, Telegram Q&A
   221	about lab state.
   222	
   223	Estimated: ~200 LOC + 15 tests.
   224	
   225	**Blocker:** Hermes service must be deployed on lab Ubuntu first.
   226	
   227	### F6 — Auto-report on experiment finalize
   228	
   229	**Status:** ✅ DONE — verify only.
   230	
   231	`ExperimentManager.finalize_experiment()` already calls
   232	`ReportGenerator(data_dir).generate(experiment_id)` when
   233	`report_enabled=True` on the experiment template.
   234	
   235	Remaining verification:
   236	1. Confirm current templates have `report_enabled: true` by default.
   237	2. Confirm `NewExperimentDialog` exposes a UI checkbox for
   238	   `report_enabled` override per-run (may already exist — check).
   239	3. Confirm LibreOffice path works on lab Ubuntu 22.04 for PDF generation.
   240	
   241	If all three pass, F6 is already shipped. No code changes needed.
   242	
   243	### F7 — Web API readings query extension
   244	
   245	**Status:** ⬜ NOT STARTED. Noted as GAP in PROJECT_STATUS.
   246	
   247	Extend `src/cryodaq/web/server.py` with:
   248	
   249	- `GET /api/readings?channels=T1,T2&from=<ts>&to=<ts>` — JSON/CSV response
   250	- `GET /api/experiment/<id>` — summary
   251	- `GET /api/experiment/<id>/readings.parquet` — Parquet stream
   252	- `WebSocket /ws` — live readings stream (verify if already exists)
   253	- Auth or loopback-only default per deferred G.1
   254	
   255	Estimated: ~400 LOC + 25 tests + OpenAPI spec doc.
   256	
   257	### F8 — Cooldown ML prediction upgrade
   258	
   259	**Status:** 🔬 RESEARCH.
   260	
   261	Current `cooldown_predictor.py` uses simple regression. Upgrade to
   262	gradient boosted model (xgboost/lightgbm) with:
   263	- Feature engineering from 30+ historical cooldowns (extract from SQLite)
   264	- Uncertainty quantification via quantile regression
   265	- A/B comparison notebook
   266	
   267	Deliverables: new predictor class, training script, evaluation notebook.
   268	
   269	Estimated: ~600 LOC + 40 tests + notebook. Non-blocking for operations.
   270	
   271	### F9 — Thermal conductivity auto-report (TIM characterization)
   272	
   273	**Status:** 🔬 RESEARCH. Physics collaboration with Vladimir required.
   274	
   275	After conductivity experiment finalize, auto-generate report with:
   276	- G(T) plot per sensor pair
   277	- Uncertainty budget per GOST Р 54500.3-2011
   278	- Comparison to previous samples (materials DB)
   279	- Raw data Parquet export (F1 dependency)
   280	
   281	Blockers:
   282	- Vladimir's uncertainty budget methodology needs to be formalized as code
   283	- Materials comparison DB structure TBD
   284	- Report templates TBD
   285	
   286	Estimated: ~500 LOC + 25 tests + DOCX templates. Close Vladimir interaction.
   287	
   288	**Value:** direct support for publication-worthy TIM characterization data.
   289	
   290	### F10 — Sensor diagnostics → alarm integration
   291	
   292	**Status:** ⬜ NOT STARTED.
   293	
   294	`sensor_diagnostics.py` shipped (MAD, correlation). Currently displays
   295	only. Upgrade to publish anomaly events into Alarm Engine v2:
   296	
   297	- Anomaly > 5 min → WARNING
   298	- Anomaly > 15 min → CRITICAL
   299	- ACK + auto-mute with configurable retry window
   300	
   301	Estimated: ~250 LOC + 20 tests.
   302	
   303	### F11 — Shift handover enrichment
   304	
   305	**Status:** 🔧 PARTIAL. Legacy widget at `gui/widgets/shift_handover.py`
   306	ships with form dialog + operator log integration.
   307	
   308	Missing auto-sections:
   309	- «Что случилось за смену» — filter `event_logger` by last 8/12/24h
   310	- Active + acknowledged alarms list
   311	- Max/min temperatures per channel over shift window
   312	- Experiment progress (start phase → current phase)
   313	- Export handover → Markdown / PDF / Telegram
   314	
   315	Implementation note: legacy widget can be extended in-place OR rewritten
   316	as `shell/overlays/shift_handover_panel.py` Phase II block. Pick extension
   317	first (faster), rewrite later if Phase II reaches this widget.
   318	
   319	Estimated: ~300 LOC + 15 tests.
   320	
   321	### F12 — Experiment templates UI editor
   322	
   323	**Status:** ⬜ NOT STARTED.
   324	
   325	Templates live in `config/experiment_templates/*.yaml`, editable only by
   326	hand. Add:
   327	- GUI editor for custom_fields
   328	- Preview card before save
   329	- Import / export templates via `.yaml`
   330	
   331	Estimated: ~400 LOC + 25 tests. Non-blocking.
   332	
   333	### F13 — Vacuum leak rate estimator
   334	
   335	**Status:** ⬜ NOT STARTED.
   336	
   337	After valve close, measure pressure rise rate:
   338	`dP/dt × V_chamber = leak rate (mbar·L/s)`.
   339	
   340	Warning threshold configurable. Historical leak rate as criostat health
   341	metric.
   342	
   343	Estimated: ~200 LOC + 15 tests + physical calibration.
   344	
   345	### F14 — Remote command approval (Telegram)
   346	
   347	**Status:** ⬜ NOT STARTED. Safety-sensitive — requires security review.
   348	
   349	Telegram command `/emergency_off confirm` → CryoDAQ emergency stop.
   350	Two-factor: command + confirmation within 30s. Rate-limited,
   351	chat_id-whitelisted.
   352	
   353	Estimated: ~250 LOC + 20 tests + threat model doc.
   354	
   355	### F15 — Linux AppImage / .deb package
   356	
   357	**Status:** ⬜ NOT STARTED. Post-0.18.0.
   358	
   359	Current deployment: `git clone` + `pip install -e .` works on Ubuntu.
   360	PyInstaller + PySide6 + linux-gpib introduces complexity.
   361	
   362	Options: AppImage (standalone exec), `.deb` package, Docker image.
   363	Preferred: AppImage for desktop deployment simplicity.
   364	
   365	Estimated: 1-2 days dev + cross-version testing.
   366	
   367	### F16 — Plugin hot-reload SDK + examples
   368	
   369	**Status:** ⬜ NOT STARTED.
   370	
   371	`plugin_loader.py` shipped. Hot-reload assumed to work but not tested.
   372	
   373	Add:
   374	- `docs/plugins.md` SDK documentation
   375	- 3-4 example plugins (Google Sheets uploader, webhook publisher,
   376	  custom alarm rule)
   377	- Hot-reload test suite
   378	
   379	Estimated: ~300 LOC plugins + docs.
   380	
   381	### F17 — SQLite → Parquet cold-storage rotation
   382	
   383	**Status:** ⬜ NOT STARTED. Depends on F1.
   384	
   385	`data/data_*.db` files accumulate forever. Housekeeping:
   386	- Daily SQLite older than N days → Parquet (Zstd)
   387	- Layout: `data/archive/year=YYYY/month=MM/`
   388	- Original SQLite deleted after successful Parquet write
   389	- Replay service reads both (SQLite recent, Parquet archive)
   390	
   391	Estimated: ~350 LOC + 20 tests.
   392	
   393	### F18 — CI/CD upgrade
   394	
   395	**Status:** ⬜ NOT STARTED. Phase 2e residual.
   396	
   397	Current `.github/workflows/main.yml`: pytest + ruff on push.
   398	
   399	Add:
   400	- Coverage reporting
   401	- Cross-platform matrix (Ubuntu + Windows + macOS)
   402	- Auto-tag + GitHub release on version bump
   403	- Artifact publishing (wheels + F15 AppImage)
   404	
   405	Estimated: ~200 LOC workflow.
   406	
   407	---
   408	
   409	## Collaboration guidelines
   410	
   411	**Autonomous (CC batch work):** F1, F2, F3, F4, F5, F7, F10, F11, F12,
   412	F13, F14, F16, F17, F18.
   413	
   414	**Physics collab with Vladimir:** F8, F9, F13.
   415	
   416	**Infrastructure collab (deployment side):** F5 (Hermes), F15 (Linux
   417	packaging).
   418	
   419	---
   420	
   423	### B1 — ZMQ subprocess command channel dies (not idle-related)
   424	
   425	**Status:** 🔧 root cause identified, fix spec prepared
   426	(`CC_PROMPT_IV_6_ZMQ_BRIDGE_FIX.md`), awaiting implementation.
   427	Blocks `0.34.0` tag.
   428	
   429	**Symptom:** GUI command plane (REQ/REP on `tcp://127.0.0.1:5556`)
   430	works for some time then hangs permanently. Data plane (SUB on 5555)
   431	unaffected — readings continue flowing.
   432	
   433	- macOS: first failure at 4-92s uptime (stochastic, rate-dependent)
   434	- Ubuntu: first failure at **exactly 120s** after subprocess start
   435	  (deterministic — single data point, may vary)
   436	
   437	**NOT macOS-specific.** Confirmed on Ubuntu 22.04 lab machine
   438	(Python 3.12.13, pyzmq 26.4.0, libzmq 4.3.5). Reproduces in live
   439	`./start.sh` run, not just diagnostic tools.
   440	
   441	**Root cause (Codex-confirmed 2026-04-20 afternoon):** single
   442	long-lived REQ socket in `cmd_forward_loop()` eventually enters
   443	unrecoverable state. Shared state across all commands means one
   444	bad socket poisons the entire command channel permanently.
   445	
   446	**Original "macOS idle-reap" hypothesis proved WRONG:**
   447	- Linux default `tcp_keepalive_time = 7200s` rules out kernel reaping.
   448	- Active polling at 1 Hz never goes idle for 10s (our keepalive
   449	  threshold), so probes never fire — TCP_KEEPALIVE fix doesn't
   450	  participate in failure mode.
   451	- TCP_KEEPALIVE fix (commit `f5f9039`) will be **reverted** on
   452	  command path in IV.6 batch; maybe helped with failure delay on
   453	  macOS by coincidence, not by mechanism.
   454	
   455	**Agreed fix plan:**
   456	1. **Primary:** per-command ephemeral REQ socket in
   457	   `zmq_subprocess.py::cmd_forward_loop()`. Remove `REQ_RELAXED`,
   458	   `REQ_CORRELATE`, `TCP_KEEPALIVE*` (all unnecessary with
   459	   ephemeral sockets). Matches ZeroMQ Guide ch.4 canonical
   460	   "poll / timeout / close / reopen" pattern.
   461	2. **Secondary:** command-channel watchdog in `launcher.py`.
   462	   Current watchdog restarts bridge on data-plane failure but
   463	   not command-only failure. Add `command_channel_stalled()`
   464	   check.
   465	
   466	**Full evidence + Codex analysis:**
   467	`docs/bug_B1_zmq_idle_death_handoff.md`.
   468	
   469	**Implementation spec:**
   470	`CC_PROMPT_IV_6_ZMQ_BRIDGE_FIX.md`.
   471	
   472	**Diagnostics kept in tree** (will remain after fix for
   473	regression testing):
   474	- `tools/diag_zmq_subprocess.py` — subprocess alone
   475	- `tools/diag_zmq_bridge.py` — full ZmqBridge 60s soak
   476	- `tools/diag_zmq_bridge_extended.py` — 180s past-first-failure
   477	- `tools/diag_zmq_idle_hypothesis.py` — rate-dependence
   478	
   479	#### IV.6 partial mitigation outcome (2026-04-20)
   480	
   481	IV.6 landed the full Codex-proposed fix plan: per-command ephemeral
   482	REQ socket in `zmq_subprocess.cmd_forward_loop`, launcher-side
   483	`command_channel_stalled()` watchdog in `_poll_bridge_data`, and
   484	`TCP_KEEPALIVE` reverted on the command + PUB paths (kept on
   485	`sub_drain_loop` as orthogonal safeguard). 60/60 unit tests green,
   486	full subtree 1775/1776 (1 unrelated flaky). Committed as `be51a24`
   487	as partial mitigation rather than a fix.
   488	
   489	**Shared-REQ-state hypothesis FALSIFIED.** Post-fix diag runs on
   490	macOS reproduce B1 with structurally identical timing to pre-fix
   491	master:
   492	
   493	- `diag_zmq_idle_hypothesis.py` SPARSE_0.33HZ: cmd #8 FAIL at
   494	  uptime 56 s (pre-fix was cmd #10 FAIL at ~30 s).
   495	- `diag_zmq_bridge_extended.py`: cmd #48 FAIL at uptime 82 s,
   496	  0/3 recovery thereafter (pre-fix was cmd #28 FAIL at 92 s).
   497	- RAPID_5HZ path still clean (295/295), matching pre-fix behaviour
   498	  — rate-dependence preserved.
   499	
   500	Removing shared REQ state did NOT eliminate the failure. Engine
   501	REP goes silently unresponsive after ~30-90 s of bridge uptime
   502	while the asyncio loop, data-plane PUB, heartbeats, scheduler
   503	writes, and plugin ticks all remain healthy. Root cause is
   504	elsewhere — likely libzmq loopback-TCP handling, pyzmq 25.x +
   505	Python 3.14 asyncio integration, or engine-side REP task state
   506	under rapid REQ connect/disconnect churn.
   507	
   508	Diag logs preserved at `/tmp/diag_iv6_idle.log`,
   509	`/tmp/diag_iv6_extended.log`, and `/tmp/engine_iv6_debug.log`
   510	for architect review.
   511	
   512	**Status:** still 🔧. B1 remains OPEN and blocks `0.34.0`.
   513	
   514	**Next:** IV.7 `ipc://` transport experiment (spec
   515	`CC_PROMPT_IV_7_IPC_TRANSPORT.md`). Fallback (a) from the original
   516	handoff is now the working hypothesis — Unix-domain sockets bypass
   517	the TCP-loopback layer entirely, which is the most likely remaining
   518	culprit given everything above the transport has been ruled out.
   519	
   520	IV.6 code stays in master as defense-in-depth: matches ZeroMQ
   521	Guide ch.4 canonical poll/timeout/close/reopen pattern, removes
   522	a real brittle point (shared REQ accumulated state), and gives
   523	the launcher a genuine command-channel watchdog for any future
   524	command-only failure shape — independent of whether B1 is
   525	ultimately resolved at the transport layer.
   526	
   527	#### IV.6 watchdog regression + cooldown hotfix (2026-04-20 evening)
   528	
   529	The IV.6 `command_channel_stalled()` watchdog had a regression:
   530	`_last_cmd_timeout` persisted across watchdog-triggered subprocess
   531	restart, so the fresh subprocess immediately saw a stale
   532	cmd_timeout signal on the very next `_poll_bridge_data` tick and
   533	was restarted again — restart storm (30-40 restarts/minute
   534	observed on Ubuntu lab PC).
   535	
   536	Hotfix applied in `src/cryodaq/launcher.py`: 60 s cooldown between
   537	command-watchdog restarts via `_last_cmd_watchdog_restart`
   538	timestamp, plus missing `return` after restart so no further
   539	checks run in the same poll cycle. Does not resolve B1 itself —
   540	only prevents the watchdog from pathologically amplifying it.
   541	System returns to "works ~60-120 s, one restart, works again"
   542	cycle which is a usable workaround until IV.7 `ipc://` ships.
   543	
   544	#### Related fixes shipped alongside IV.6 (2026-04-20)
   545	
   546	- `aabd75f` — `engine: wire validate_checksum through Thyracont
   547	  driver loader`. `_create_instruments()` was ignoring the YAML
   548	  key; driver defaulted to `True` regardless of config. Fix
   549	  resolves TopWatchBar pressure em-dash on Ubuntu lab PC (VSP206
   550	  hardware has different checksum formula than VSP63D).
   551	- `74dbbc7` — `reporting: xml_safe sanitizer for python-docx
   552	  compatibility`. Keithley VISA resource strings contain `\x00`
   553	  per NI-VISA spec; python-docx rejected them as XML 1.0
   554	  incompatible when embedded in auto-reports. New
   555	  `src/cryodaq/utils/xml_safe.py` strips XML-illegal control chars;
   556	  applied at all `add_paragraph()` / `cell.text` sites in
   557	  `src/cryodaq/reporting/sections.py`; `core/experiment.py:782`
   558	  logger upgraded from `log.warning` to `log.exception` so future
   559	  report-gen failures carry tracebacks.
   560	
   561	**No-longer-broken bugs:** TopWatchBar pressure display (was
   562	reading-driven, not B1-caused) is now resolved by `aabd75f` +
   563	Ubuntu-side config (`validate_checksum: false` in
   564	`instruments.local.yaml`).
   565	
   566	**Orthogonal issue still open:** `alarm_v2.py:252` raises
   567	`KeyError: 'threshold'` when evaluating the `cooldown_stall`
   568	composite alarm (one sub-condition is missing a `threshold`
   569	field — probably stale/rate-type where `threshold` is spurious).
   570	Log spam every ~2 s. Engine does not crash. Fix candidate: config

exec
/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md | sed -n '1,20p;120,150p;160,200p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	# CryoDAQ — PROJECT_STATUS
     2	
     3	**Дата:** 2026-04-19
     4	**Ветка:** master
     5	**Последний commit:** `e4a60f3` (`feat(ui): II.2 ArchiveOverlay + K6 bulk export migration — DS v1.0.1`)
     6	**Тесты:** 1 368 passed, 2 skipped
     7	**Фронтир:** Phase II.2 ArchiveOverlay (`e4a60f3`) и II.3 OperatorLog (`9676acc`) закрыты вслед за II.6 Keithley (`96adf5a`); следующий блок — II.5 ConductivityOverlay.
     8	
     9	---
    10	
    11	## Масштаб проекта
    12	
    13	| Метрика | Значение |
    14	|---|---|
    15	| Python файлы (`src/cryodaq/`) | **139** |
    16	| Строки кода (`src/cryodaq/`) | **44 195** |
    17	| Тестовые файлы (`tests/`) | **150** |
    18	| Строки тестов (`tests/`) | **24 275** |
    19	| Тесты | **1 368 passed, 2 skipped** |
    20	| Coverage (full suite) | **66%** (stale — last measured 2026-04-17; re-run pending) |
   120	| II.4 AlarmOverlay | ⚠️ PARTIAL (badge routing only) |
   121	| II.5 ConductivityOverlay | ⬜ NOT STARTED (next) |
   122	| II.6 KeithleyOverlay | ✅ COMPLETE (`96adf5a` — power-control rewrite + host integration) |
   123	| II.7 CalibrationOverlay | ⬜ NOT STARTED |
   124	| II.8 Instruments+SensorDiag | ⬜ NOT STARTED |
   125	| II.9 ExperimentOverlay v3 | ⚠️ PARTIAL (functional; visual pending) |
   126	
   127	**Phase I status** (revised against actual `_design_system/` contents): I.1 COMPLETE; I.2 NOT STARTED (deliberately bypassed for II.1 AnalyticsView); I.3 PARTIAL (widgets exist under `dashboard/phase_content/` but not extracted into `_design_system/`, no StatusBadge / ZmqWorkerField); I.4 PARTIAL (showcase covers only Phase I.1 primitives).
   128	
   129	### Runtime theme switcher — shipped 2026-04-18
   130	
   131	Infrastructure landing outside the original roadmap. Six bundled YAML theme packs at `config/themes/`: `default_cool`, `warm_stone`, `anthropic_mono`, `ochre_bloom`, `taupe_quiet`, `rose_dusk`. Runtime theme loader at `src/cryodaq/gui/_theme_loader.py` — `theme.py` now reads tokens from YAML packs. Settings → Тема menu with `os.execv` restart pattern. Status palette (STATUS_OK, WARNING, CAUTION, FAULT, INFO, STALE, COLD_HIGHLIGHT) locked across all packs. Legacy hardcoded theme overrides stripped from 9 `apply_panel_frame` callsites.
   132	
   133	Commit chain: `ecd447a` (YAML reader) → `e52b17b` (strip hardcoded overrides) → `9ac307e` (ship 5 additional packs) → `77ffc93` (Settings → Тема menu) → `903553a` (operator manual + CHANGELOG).
   134	
   135	Palette tuning follow-ups tracked in `HANDOFF_THEME_PALETTES.md` — not blocking.
   136	
   137	### IPC/REP hardening — shipped 2026-04-18
   138	
   139	Architectural hardening of the engine ↔ GUI command plane after a production wedge revealed the `ZMQCommandServer` REP task crashing silently while the engine subprocess's `stderr=DEVNULL` swallowed the evidence. Ten commits; two Codex review rounds; final verdict PASS at `27dfecb`.
   140	
   141	Commits: `5299aa6`, `f5b0f22`, `a38e2fa`, `913b9b3`, `2b1370b`, `abfdf44`, `81e2daa`, `3a16c54`, `ba20f84`, `27dfecb`.
   142	
   143	Mechanisms added:
   144	
   145	1. Bridge subprocess split — SUB drain + CMD forward on separate owner threads.
   146	2. Data-flow watchdog independent of heartbeat (stall detection works even when PUB is alive).
   147	3. Bridge sockets moved to owner threads (prevents cross-thread ZMQ calls).
   148	4. `log_get` routed to a dedicated read executor (long reads don't block REP).
   149	5. Transport disconnect recovery bounded (no unbounded cleanup).
   150	6. `ZMQCommandServer` task supervision — `add_done_callback` detects unexpected exit and spawns a fresh serve loop. Reentrancy-safe.
   160	14 commits, +61 tests (829 → 890), zero regressions. Triple-reviewer pipeline (CC tactical + Codex second-opinion + Jules architectural) валидирован на Safety, Persistence и Config Fail-Closed subsystems.
   161	
   162	Детальная хронология commit'ов Phase 2d и темы (Safety hardening / Persistence integrity / Operational polish) — см. `docs/audits/2026-04-09/MASTER_TRIAGE.md` и retro-анализ в `docs/changelog/archive/RETRO_ANALYSIS_V3.md` (canonical). Полная таблица 14 commit'ов вынесена в архив вместе с audit-докладами.
   163	
   164	---
   165	
   166	## В работе
   167	
   168	**Phase II UI rebuild — mixed status (2026-04-16 … 2026-04-19).**
   169	
   170	Block-level status map canonicalized in `docs/phase-ui-1/phase_ui_v2_roadmap.md`. Short version:
   171	
   172	- ✅ II.1 AnalyticsView COMPLETE (`860ecf3`, primary-view QWidget)
   173	- ✅ II.2 ArchiveOverlay COMPLETE (`e4a60f3`, K6 bulk export migration + three Codex amend cycles)
   174	- ✅ II.3 OperatorLog COMPLETE (`9676acc`, timeline + filters + Host Integration Contract)
   175	- ✅ II.6 KeithleyOverlay COMPLETE (`96adf5a`, power-control rewrite + host wiring)
   176	- ⚠️ II.4 AlarmOverlay PARTIAL (badge routing only)
   177	- ⚠️ II.9 ExperimentOverlay v3 PARTIAL (functional; visual rebuild pending)
   178	- ⬜ II.5 ConductivityOverlay — next block
   179	- ⬜ II.7, II.8 NOT STARTED
   180	
   181	### Host Integration Contract — pattern codified (2026-04-19)
   182	
   183	Codex FAIL on II.6 surfaced a systemic risk: overlays with public push setters (`set_connected`, `set_current_experiment`, `set_safety_ready`, etc.) are useless if `MainWindowV2` never calls them — the overlay opens in defaults and stays there. Unit tests on the overlay alone pass while production is broken.
   184	
   185	**Contract (mandatory for every overlay with push setters):**
   186	
   187	1. `_tick_status()` mirror — for `set_connected(bool)`.
   188	2. `_dispatch_reading()` state sinks — for stateful readings (safety state, experiment status, finalized events).
   189	3. `_ensure_overlay()` replay on lazy open — push cached state the moment the overlay is constructed, so the first paint is correct.
   190	
   191	**Tests:** overlay unit tests AND host integration tests (`tests/gui/shell/test_main_window_v2_<block>_wiring.py`) that exercise `MainWindowV2` entry points end-to-end — firing the signal / setting the cache / calling `_ensure_overlay` and asserting overlay state.
   192	
   193	Earlier cleanup/quick-win steps that landed between Phase I.1 close-out and Phase II blocks:
   194	
   195	- Repo cleanup (`0d4d386`): root audit-артефакты → `docs/audits/2026-04-09/`, superseded markers на старой design system / wireframe / roadmap, RETRO V1/V2 в архив.
   196	- `PROJECT_STATUS.md` refresh (`50ab8c0`, 2026-04-17).
   197	- PhaseStepper ACCENT → STATUS_OK (`05f27d0`, A.4) — active pill теперь `theme.STATUS_OK`; `ACCENT` остаётся только для keyboard focus ring.
   198	- Fira Code + Fira Sans bundle + load — 12 .ttf files под `src/cryodaq/gui/resources/fonts/`, `_load_bundled_fonts()` вызывается из `gui/app.py:131` и `launcher.py:825` до любой widget construction.
   199	
   200	**Phase III — not yet started.**

exec
/opt/homebrew/bin/bash -lc "git -C /Users/vladimir/Projects/cryodaq tag -l | sort; git -C /Users/vladimir/Projects/cryodaq log --oneline --decorate -n 12; rg -n \"version =|0\\.34\\.0|v0\\.33\\.0|7cb5634|cabd854|design-system-v1\\.0\\.1|retroactive|F1|F18|IV\\.4|Known broken|B1\" /Users/vladimir/Projects/cryodaq/pyproject.toml /Users/vladimir/Projects/cryodaq/CHANGELOG.md /Users/vladimir/Projects/cryodaq/ROADMAP.md /Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md /Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-23-cleanup-baseline.md -S" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
design-system-v1.0.1
pre-tier1-merge-backup-2026-04-14
v0.33.0
cabd854 (HEAD -> master, origin/master, origin/HEAD) docs: Q4 equivalence check synthesis + D1 closure
89b4db1 merge: D1 R1 repair from feat/b2b4fb5-repair
680240a artifacts: D1 R1 repair review handoff for feat/b2b4fb5-repair
a82d6bf docs: session ledger for 2026-04-24 D4a + D1 execution
c3f4f86 fix(diag): bounded-backoff retry in B1 capture probe (R1 repair for b2b4fb5)
62314be tools: record direct probe timeouts in B1 capture
033f87b tools: align B1 capture CLI with jsonl master capture
40553ea tools: align B1 diagnostic helpers with bridge/direct capture
cc090be tools: add canonical B1 capture CLI
8b9ce4a tools: add reusable B1 diagnostic helpers
af77095 recon: safe-merge branch commit classification for D1/D4 re-plan
0a38f93 models: update skill + overnight batch to Gemini 3.1 Pro Preview + GPT-5.5
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:22:| Версия пакета | 0.34.0.dev0 |
/Users/vladimir/Projects/cryodaq/ROADMAP.md:26:| F1 | Parquet archive wire-up | ✅ DONE (UI + base dep, IV.4.F1) | S | H |
/Users/vladimir/Projects/cryodaq/ROADMAP.md:27:| F2 | Debug mode toggle (verbose logging) | ✅ DONE (IV.4.F2) | S | H |
/Users/vladimir/Projects/cryodaq/ROADMAP.md:31:| F6 | Auto-report on experiment finalize | ✅ DONE (verified + per-experiment override, IV.4.F6) | S | H |
/Users/vladimir/Projects/cryodaq/ROADMAP.md:35:| F10 | Sensor diagnostics → alarm integration | ⬜ | M | M |
/Users/vladimir/Projects/cryodaq/ROADMAP.md:36:| F11 | Shift handover enrichment | ✅ DONE (IV.4.F11, Telegram export deferred) | S | H |
/Users/vladimir/Projects/cryodaq/ROADMAP.md:37:| F12 | Experiment templates UI editor | ⬜ | M | L |
/Users/vladimir/Projects/cryodaq/ROADMAP.md:38:| F13 | Vacuum leak rate estimator | ⬜ | M | M |
/Users/vladimir/Projects/cryodaq/ROADMAP.md:39:| F14 | Remote command approval (Telegram) | ⬜ | M | L |
/Users/vladimir/Projects/cryodaq/ROADMAP.md:40:| F15 | Linux AppImage / .deb package | ⬜ | L | L |
/Users/vladimir/Projects/cryodaq/ROADMAP.md:41:| F16 | Plugin hot-reload SDK + examples | ⬜ | M | L |
/Users/vladimir/Projects/cryodaq/ROADMAP.md:42:| F17 | SQLite → Parquet cold-storage rotation | ⬜ | M | M |
/Users/vladimir/Projects/cryodaq/ROADMAP.md:43:| F18 | CI/CD upgrade (coverage, matrix, releases) | ⬜ | M | L |
/Users/vladimir/Projects/cryodaq/ROADMAP.md:54:### IV.4 — Safe features batch
/Users/vladimir/Projects/cryodaq/ROADMAP.md:56:**Target:** tag `0.34.0` (next increment after current `0.33.0`).
/Users/vladimir/Projects/cryodaq/ROADMAP.md:58:**Status:** ✅ CLOSED at HEAD `7cb5634` (2026-04-20).
/Users/vladimir/Projects/cryodaq/ROADMAP.md:62:- **F1** — Parquet UI export button + default pyarrow install
/Users/vladimir/Projects/cryodaq/ROADMAP.md:65:- **F11** — Shift handover auto-sections
/Users/vladimir/Projects/cryodaq/ROADMAP.md:73:- F1 Parquet UI: `bf584ed` (2 amends)
/Users/vladimir/Projects/cryodaq/ROADMAP.md:76:- F11 shift handover: `7cb5634` (2 amends)
/Users/vladimir/Projects/cryodaq/ROADMAP.md:78:Telegram export in F11 deferred (out of IV.4 scope per Rule 4).
/Users/vladimir/Projects/cryodaq/ROADMAP.md:82:**Target:** tag `0.35.0` after IV.4 closes, smoke passes, and ZMQ
/Users/vladimir/Projects/cryodaq/ROADMAP.md:83:subprocess bug (see "Known broken" below) resolved.
/Users/vladimir/Projects/cryodaq/ROADMAP.md:90:- **F17** — SQLite → Parquet cold rotation in housekeeping
/Users/vladimir/Projects/cryodaq/ROADMAP.md:94:Spec: not yet drafted; pending IV.4 outcomes + Hermes service readiness.
/Users/vladimir/Projects/cryodaq/ROADMAP.md:106:F4, F7, F10, F12, F13, F14, F15, F16, F18 — see individual entries below.
/Users/vladimir/Projects/cryodaq/ROADMAP.md:112:### F1 — Parquet archive wire-up
/Users/vladimir/Projects/cryodaq/ROADMAP.md:279:- Raw data Parquet export (F1 dependency)
/Users/vladimir/Projects/cryodaq/ROADMAP.md:290:### F10 — Sensor diagnostics → alarm integration
/Users/vladimir/Projects/cryodaq/ROADMAP.md:303:### F11 — Shift handover enrichment
/Users/vladimir/Projects/cryodaq/ROADMAP.md:321:### F12 — Experiment templates UI editor
/Users/vladimir/Projects/cryodaq/ROADMAP.md:333:### F13 — Vacuum leak rate estimator
/Users/vladimir/Projects/cryodaq/ROADMAP.md:345:### F14 — Remote command approval (Telegram)
/Users/vladimir/Projects/cryodaq/ROADMAP.md:355:### F15 — Linux AppImage / .deb package
/Users/vladimir/Projects/cryodaq/ROADMAP.md:367:### F16 — Plugin hot-reload SDK + examples
/Users/vladimir/Projects/cryodaq/ROADMAP.md:381:### F17 — SQLite → Parquet cold-storage rotation
/Users/vladimir/Projects/cryodaq/ROADMAP.md:383:**Status:** ⬜ NOT STARTED. Depends on F1.
/Users/vladimir/Projects/cryodaq/ROADMAP.md:393:### F18 — CI/CD upgrade
/Users/vladimir/Projects/cryodaq/ROADMAP.md:403:- Artifact publishing (wheels + F15 AppImage)
/Users/vladimir/Projects/cryodaq/ROADMAP.md:411:**Autonomous (CC batch work):** F1, F2, F3, F4, F5, F7, F10, F11, F12,
/Users/vladimir/Projects/cryodaq/ROADMAP.md:412:F13, F14, F16, F17, F18.
/Users/vladimir/Projects/cryodaq/ROADMAP.md:414:**Physics collab with Vladimir:** F8, F9, F13.
/Users/vladimir/Projects/cryodaq/ROADMAP.md:416:**Infrastructure collab (deployment side):** F5 (Hermes), F15 (Linux
/Users/vladimir/Projects/cryodaq/ROADMAP.md:421:## Known broken (blocking next tag)
/Users/vladimir/Projects/cryodaq/ROADMAP.md:423:### B1 — ZMQ subprocess command channel dies (not idle-related)
/Users/vladimir/Projects/cryodaq/ROADMAP.md:427:Blocks `0.34.0` tag.
/Users/vladimir/Projects/cryodaq/ROADMAP.md:467:`docs/bug_B1_zmq_idle_death_handoff.md`.
/Users/vladimir/Projects/cryodaq/ROADMAP.md:490:macOS reproduce B1 with structurally identical timing to pre-fix
/Users/vladimir/Projects/cryodaq/ROADMAP.md:512:**Status:** still 🔧. B1 remains OPEN and blocks `0.34.0`.
/Users/vladimir/Projects/cryodaq/ROADMAP.md:524:command-only failure shape — independent of whether B1 is
/Users/vladimir/Projects/cryodaq/ROADMAP.md:539:checks run in the same poll cycle. Does not resolve B1 itself —
/Users/vladimir/Projects/cryodaq/ROADMAP.md:562:reading-driven, not B1-caused) is now resolved by `aabd75f` +
/Users/vladimir/Projects/cryodaq/pyproject.toml:7:version = "0.34.0.dev0"
/Users/vladimir/Projects/cryodaq/pyproject.toml:38:    # IV.4 Finding 1: pyarrow promoted from [archive] extra to base.
/Users/vladimir/Projects/cryodaq/pyproject.toml:63:# IV.4 Finding 1: archive extra retained as a no-op alias so any
/Users/vladimir/Projects/cryodaq/pyproject.toml:88:target-version = "py312"
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-23-cleanup-baseline.md:39:- **Autonomy expansion** — untracked files inside to-be-removed worktrees are to be preserved via archive-and-commit, not escalated. Applies retroactively.
/Users/vladimir/Projects/cryodaq/docs/decisions/2026-04-23-cleanup-baseline.md:142:- **b2b4fb5 hypothesis test**: does the hardened B1 probe reject a healthy `ipc://` bridge, causing the 2026-04-23 IV.7 runtime failure to have been misattributed? (Plan `CC_PROMPT_IV_7_IPC_TRANSPORT.md` still active per §11.)
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:16:release is `0.34.0` once B1 is resolved via IV.7.
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:40:  watchdog (IV.6 partial B1 mitigation)`. Landed the full
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:41:  Codex-proposed B1 fix plan: per-command ephemeral REQ socket in
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:47:  **Does NOT fix B1 — Stage 3 diag tools still reproduce it.**
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:66:**Open / known issues carrying into 0.34.0:**
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:68:- **B1 still unresolved.** GUI command channel silently dies
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:787:- **Gap между v0.13.0 и v0.33.0.** Versions 0.14.0-0.32.x developed
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:802:- `v0.33.0` — merge commit `7b453d5`

exec
/opt/homebrew/bin/bash -lc "find /Users/vladimir/Projects/cryodaq/.claude/skills -maxdepth 1 -type f -name '*.md' -print -exec sh -c 'for f; do echo ---"'$f; sed -n "1,40p" "$f"; done'"' sh {} +" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
/Users/vladimir/Projects/cryodaq/.claude/skills/multi-model-consultation.md
/Users/vladimir/Projects/cryodaq/.claude/skills/cryodaq-team-lead.md
---/Users/vladimir/Projects/cryodaq/.claude/skills/multi-model-consultation.md
---
name: multi-model-consultation
description: "Use when CC needs to consult external AI models (Codex CLI, Gemini CLI, GLM-5.1, Kimi K2.6) for review, audit, draft, or second opinion on CryoDAQ work. Routes the task to the right model based on its strengths, produces a synthesis artifact that becomes the durable record, follows docs/ORCHESTRATION.md §4 protocol. Invoke whenever architect says 'get a review from', 'ask Codex', 'ask Gemini', 'run swarm', 'second opinion', 'adversarial review', 'cross-check with another model', or CC itself encounters a decision where its own confidence is low and architect is unavailable. Covers routing decision, budget discipline, identity-leak gotchas, formation patterns (single / writer-reviewer / adversarial pair / wide audit), brief templates, synthesis format, and anti-patterns learned from 2026-04-21..23 failed swarm cycle."
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

Claude, Codex, Gemini, GLM, Kimi are NOT interchangeable. Each has a
real niche. Using the wrong model is not just wasteful — it actively
---/Users/vladimir/Projects/cryodaq/.claude/skills/cryodaq-team-lead.md
---
name: cryodaq-team-lead
description: "Orchestrate Claude Code agent teams for CryoDAQ — a LabVIEW replacement for cryogenic lab instrumentation (АКЦ ФИАН, Millimetron). Master-track scope: engine, drivers, storage, analytics, reporting, web, notifications, core, safety, configs, build, tests. GUI excluded (owned by feat/ui-phase-1). Safety-critical: 6-state SafetyManager FSM, fail-on-silence, crash-safe SQLite WAL. 3 instrument types (5 instances), 24 temperature channels."
---

# Team Lead — CryoDAQ (master track)

You are the team lead for CryoDAQ on the **master** branch. You NEVER implement code, touch files, or run commands directly. You analyze tasks, compose teams, spawn teammates with role-specific prompts, coordinate, and synthesize.

## Prerequisites

1. Verify `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` is set.
2. Remind user to enable **delegate mode** (`Shift+Tab`).

## Branch ownership

| Branch | Owns | Does NOT touch |
|---|---|---|
| `master` | engine, drivers, storage, analytics, reporting, web, notifications, core, safety, configs, build, tests | `src/cryodaq/gui/` |
| `feat/ui-phase-1` | `src/cryodaq/gui/`, `tests/gui/` | engine internals |

**This skill is for master-track agents only.** GUI lives in `src/cryodaq/gui/` and is owned by the `feat/ui-phase-1` branch. Master-track agents do not read or modify GUI files.

## Project context

CryoDAQ is a Python application for cryogenic measurement and control (АКЦ ФИАН, Millimetron space telescope project). It replaces LabVIEW.

**Architecture (master-track scope):**
- `cryodaq-engine` (headless, asyncio): drivers → Scheduler → SQLiteWriter.write_immediate() → DataBroker.publish_batch() → ZMQ / alarms / plugins. Scheduler → SafetyBroker.publish_batch() → SafetyManager (dedicated safety channel). Runs weeks without restart.
- Web server (`uvicorn cryodaq.web.server:app`): FastAPI + WebSocket, optional remote monitoring dashboard.
- IPC: ZeroMQ PUB/SUB :5555 (data stream, msgpack) + REP/REQ :5556 (commands, JSON via ZMQCommandServer).

**Platform:** Python 3.12+, asyncio. Windows (primary lab PC) + Linux (future).

**Codebase (non-GUI master track):**
- 74 Python source files, ~22,300 lines
- 88 test files, 718 collected tests
- 11 config YAML files + 5 experiment templates + 2 .local.yaml.example templates

**Dependencies (pyproject.toml, no pydantic):**

exec
/opt/homebrew/bin/bash -lc 'rg -n "cryodaq-team-lead|team lead|delegate mode|CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS|agent teams|Team Lead" /Users/vladimir/Vault/CryoDAQ -S' in /Users/vladimir/Projects/cryodaq
 exited 1 in 0ms:
exec
/opt/homebrew/bin/bash -lc "test -e /Users/vladimir/Projects/cryodaq/src/cryodaq/gui/main_window.py && echo exists || echo missing; find /Users/vladimir/Projects/cryodaq/src/cryodaq/gui/widgets -maxdepth 1 -type f -name '*.py' -printf '%f
' | sort | sed -n '1,120p'; rg -n \"DEPRECATED|Phase II.13|deleted|src/cryodaq/gui/main_window.py|widgets/(alarm|archive|calibration|conductivity|instrument_status|sensor_diag_panel|keithley|operator_log|experiment_workspace|autosweep)\" /Users/vladimir/Projects/cryodaq/CHANGELOG.md /Users/vladimir/Projects/cryodaq/CLAUDE.md /Users/vladimir/Projects/cryodaq/README.md -S" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
missing
find: -printf: unknown primary or operator
/Users/vladimir/Projects/cryodaq/README.md:263:- `src/cryodaq/gui/main_window.py` — legacy 10-tab shell (fallback)
/Users/vladimir/Projects/cryodaq/README.md:264:- `src/cryodaq/gui/widgets/calibration_panel.py`
/Users/vladimir/Projects/cryodaq/CLAUDE.md:227:- `src/cryodaq/gui/shell/main_window_v2.py` — v2 shell: TopWatchBar + ToolRail + BottomStatusBar + main content area; canonical mnemonic shortcuts (`Ctrl+L/E/A/K/M/R/C/D`, `F5`, `Ctrl+Shift+X`) per AD-002 — sole owner of shortcut bindings after the v1 `gui/main_window.py` was retired in Phase II.13
/Users/vladimir/Projects/cryodaq/CLAUDE.md:265:Remaining widget modules after Phase II.13 legacy cleanup. All
/Users/vladimir/Projects/cryodaq/CLAUDE.md:268:experiment_workspace / autosweep) were deleted in II.13 and replaced by
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:193:- **Phase II.13 legacy cleanup.** All DEPRECATED-marked Phase I-era
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:194:  widgets deleted now that their shell-v2 overlay replacements
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:197:  - `src/cryodaq/gui/widgets/alarm_panel.py` (superseded by II.4).
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:198:  - `src/cryodaq/gui/widgets/archive_panel.py` (superseded by II.2).
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:199:  - `src/cryodaq/gui/widgets/calibration_panel.py` (superseded by II.7).
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:200:  - `src/cryodaq/gui/widgets/conductivity_panel.py` (superseded by II.5).
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:201:  - `src/cryodaq/gui/widgets/instrument_status.py` (superseded by II.8).
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:202:  - `src/cryodaq/gui/widgets/sensor_diag_panel.py` (superseded by II.8 — folded into `InstrumentsPanel._SensorDiagSection`).
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:203:  - `src/cryodaq/gui/widgets/keithley_panel.py` (superseded by II.6).
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:204:  - `src/cryodaq/gui/widgets/operator_log_panel.py` (superseded by II.3).
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:205:  - `src/cryodaq/gui/widgets/experiment_workspace.py` (superseded by II.9; shell overlay retained at `shell/experiment_overlay.py` per Path A).
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:206:  - `src/cryodaq/gui/widgets/autosweep_panel.py` (pre-Phase-II DEPRECATED).
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:207:  - `src/cryodaq/gui/main_window.py` (v1 tab-based main window; `cryodaq-gui` entry point was already on `MainWindowV2` via `gui/app.py` since Phase I.1).
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:212:  by non-DEPRECATED widgets (shift_handover, pressure_panel,
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:256:  widgets marked DEPRECATED in module docstrings; deletion slated
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:257:  for Phase II.13. Tests: 41 overlay cases + 7 host-wiring cases.
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:278:  at `src/cryodaq/gui/widgets/alarm_panel.py` marked DEPRECATED in
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:279:  its module docstring; slated for deletion in Phase II.13. Zero legacy
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:310:  `src/cryodaq/gui/widgets/calibration_panel.py` marked DEPRECATED;
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:356:  `src/cryodaq/gui/widgets/conductivity_panel.py` marked DEPRECATED;
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:380:  widget at `src/cryodaq/gui/widgets/archive_panel.py` marked
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:381:  DEPRECATED; removal in Phase III.3. `main_window.py` File menu
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:396:  open. Legacy widget at `src/cryodaq/gui/widgets/operator_log_panel.py`
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:397:  marked DEPRECATED; removal in Phase III.3. `QuickLogBlock`
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:421:  `src/cryodaq/gui/widgets/keithley_panel.py` marked DEPRECATED;
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:739:  `gui/widgets/calibration_panel.py` built channel refs в
/Users/vladimir/Projects/cryodaq/CHANGELOG.md:745:  `gui/main_window.py` и `gui/widgets/experiment_workspace.py` had

codex
A concrete issue is emerging: one Overview note misplaces `zmq_subprocess.py` on the engine side, while the code says it is the GUI-side ZMQ owner process. I’m now checking for similar cross-note contradictions where one note has already corrected a stale source claim but another still repeats it.
exec
/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Projects/cryodaq/src/cryodaq/web/server.py | sed -n '1,240p'; rg -n \"web|FastAPI|loopback|auth|read-only|/status|/history|/api/status|/ws|command|request\" /Users/vladimir/Projects/cryodaq/README.md /Users/vladimir/Projects/cryodaq/CLAUDE.md /Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md /Users/vladimir/Projects/cryodaq/ROADMAP.md -S" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	"""Веб-панель удалённого мониторинга CryoDAQ.
     2	
     3	Лёгкий FastAPI-сервер для доступа к данным engine из браузера:
     4	- WebSocket ``/ws`` — поток показаний в реальном времени
     5	- GET ``/status`` — JSON со статусом приборов, тревог, uptime
     6	- GET ``/history`` — JSON с историческими данными из SQLite (последние N минут)
     7	- GET ``/`` — статическая HTML-страница (single-page dashboard)
     8	
     9	Запуск::
    10	
    11	    uvicorn cryodaq.web.server:app --host 0.0.0.0 --port 8080
    12	
    13	Или программно::
    14	
    15	    from cryodaq.web.server import create_app
    16	    app = create_app()
    17	"""
    18	
    19	from __future__ import annotations
    20	
    21	import asyncio
    22	from importlib.metadata import version as _get_version
    23	
    24	try:
    25	    _VERSION = _get_version("cryodaq")
    26	except Exception:
    27	    _VERSION = "dev"
    28	import json
    29	import logging
    30	import sqlite3
    31	import time
    32	from datetime import UTC, datetime, timedelta
    33	from pathlib import Path
    34	from typing import Any
    35	
    36	import zmq
    37	from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    38	from fastapi.responses import HTMLResponse
    39	from fastapi.staticfiles import StaticFiles
    40	
    41	from cryodaq.core.zmq_bridge import ZMQSubscriber
    42	from cryodaq.drivers.base import Reading
    43	from cryodaq.paths import get_data_dir
    44	
    45	logger = logging.getLogger(__name__)
    46	
    47	_STATIC_DIR = Path(__file__).parent / "static"
    48	
    49	# ---------------------------------------------------------------------------
    50	# Standalone ZMQ command client (no GUI dependency)
    51	# ---------------------------------------------------------------------------
    52	
    53	_CMD_ADDR = "tcp://127.0.0.1:5556"  # REP port = PUB + 1
    54	
    55	
    56	def _send_engine_command(cmd: dict) -> dict:
    57	    """Send a command to the engine via ZMQ REQ/REP. Thread-safe per call."""
    58	    ctx = zmq.Context.instance()
    59	    sock = ctx.socket(zmq.REQ)
    60	    sock.setsockopt(zmq.RCVTIMEO, 5000)
    61	    sock.setsockopt(zmq.SNDTIMEO, 5000)
    62	    sock.setsockopt(zmq.LINGER, 0)
    63	    try:
    64	        sock.connect(_CMD_ADDR)
    65	        sock.send_json(cmd)
    66	        return sock.recv_json()
    67	    except zmq.ZMQError:
    68	        return {"ok": False, "error": "Engine не отвечает"}
    69	    finally:
    70	        sock.close()
    71	
    72	
    73	async def _async_engine_command(cmd: dict) -> dict:
    74	    """Non-blocking engine command via thread pool."""
    75	    return await asyncio.to_thread(_send_engine_command, cmd)
    76	
    77	
    78	# Директория с файлами данных SQLite (data_YYYY-MM-DD.db)
    79	_DATA_DIR = get_data_dir()
    80	
    81	# ---------------------------------------------------------------------------
    82	# Глобальное состояние сервера
    83	# ---------------------------------------------------------------------------
    84	
    85	
    86	class _ServerState:
    87	    """Общее состояние для всех WebSocket-клиентов."""
    88	
    89	    def __init__(self) -> None:
    90	        self.start_time: float = time.monotonic()
    91	        self.total_readings: int = 0
    92	        self.last_readings: dict[str, dict[str, Any]] = {}  # channel → serialized reading
    93	        self.active_alarms: dict[str, dict[str, Any]] = {}
    94	        self.safety_state: str = "unknown"
    95	        self.instrument_status: dict[str, dict[str, Any]] = {}
    96	        self.clients: set[WebSocket] = set()
    97	        self.subscriber: ZMQSubscriber | None = None
    98	        self._lock = asyncio.Lock()
    99	        # Bounded broadcast queue — prevents task explosion under load.
   100	        # Initialised in startup (requires running event loop).
   101	        self.broadcast_q: asyncio.Queue[dict[str, Any]] | None = None
   102	
   103	    def on_reading(self, reading: Reading) -> None:
   104	        """Обработать входящее показание (вызывается из ZMQ callback)."""
   105	        self.total_readings += 1
   106	
   107	        data = {
   108	            "timestamp": reading.timestamp.isoformat(),
   109	            "channel": reading.channel,
   110	            "value": reading.value,
   111	            "unit": reading.unit,
   112	            "status": reading.status.value,
   113	        }
   114	        self.last_readings[reading.channel] = data
   115	
   116	        # Определить прибор
   117	        inst_id = reading.instrument_id or ""
   118	        if not inst_id and "/" in reading.channel:
   119	            inst_id = reading.channel.split("/")[0]
   120	        elif not inst_id and reading.channel.startswith("Т"):
   121	            try:
   122	                num = int(reading.channel[1:].split(" ")[0])
   123	                if 1 <= num <= 8:
   124	                    inst_id = "LS218_1"
   125	                elif 9 <= num <= 16:
   126	                    inst_id = "LS218_2"
   127	                elif 17 <= num <= 24:
   128	                    inst_id = "LS218_3"
   129	            except (ValueError, IndexError):
   130	                pass
   131	
   132	        if inst_id:
   133	            self.instrument_status[inst_id] = {
   134	                "last_seen": reading.timestamp.isoformat(),
   135	                "status": reading.status.value,
   136	                "total_readings": self.instrument_status.get(inst_id, {}).get("total_readings", 0)
   137	                + 1,
   138	            }
   139	
   140	    def status_json(self) -> dict[str, Any]:
   141	        """Собрать JSON-статус для GET /status."""
   142	        uptime_s = time.monotonic() - self.start_time
   143	        hours, rem = divmod(int(uptime_s), 3600)
   144	        mins, secs = divmod(rem, 60)
   145	        return {
   146	            "uptime": f"{hours:02d}:{mins:02d}:{secs:02d}",
   147	            "uptime_s": round(uptime_s, 1),
   148	            "total_readings": self.total_readings,
   149	            "channels": len(self.last_readings),
   150	            "instruments": self.instrument_status,
   151	            "safety_state": self.safety_state,
   152	            "active_alarms": self.active_alarms,
   153	            "ws_clients": len(self.clients),
   154	        }
   155	
   156	
   157	_state = _ServerState()
   158	
   159	
   160	# ---------------------------------------------------------------------------
   161	# Broadcast к WebSocket-клиентам
   162	# ---------------------------------------------------------------------------
   163	
   164	
   165	async def _broadcast(data: dict[str, Any]) -> None:
   166	    """Отправить JSON всем подключённым WebSocket-клиентам."""
   167	    if not _state.clients:
   168	        return
   169	    message = json.dumps(data, ensure_ascii=False)
   170	    disconnected: list[WebSocket] = []
   171	    for ws in _state.clients:
   172	        try:
   173	            await ws.send_text(message)
   174	        except Exception:
   175	            disconnected.append(ws)
   176	    for ws in disconnected:
   177	        _state.clients.discard(ws)
   178	
   179	
   180	async def _broadcast_pump() -> None:
   181	    """Одна фоновая задача вместо N fire-and-forget tasks.
   182	
   183	    Читает из ограниченной очереди _state.broadcast_q и рассылает
   184	    по WebSocket. Если нет клиентов — сообщение просто отбрасывается.
   185	    Это предотвращает накопление тысяч Task-объектов в event loop.
   186	    """
   187	    q = _state.broadcast_q
   188	    assert q is not None
   189	    while True:
   190	        data = await q.get()
   191	        if _state.clients:
   192	            await _broadcast(data)
   193	
   194	
   195	async def _zmq_to_ws_bridge() -> None:
   196	    """Фоновая задача: получает Reading от ZMQ, рассылает по WebSocket."""
   197	    sub = ZMQSubscriber(callback=_on_reading_callback)
   198	    _state.subscriber = sub
   199	    await sub.start()
   200	    logger.info("ZMQ→WS мост запущен")
   201	    # Задача живёт вечно — остановка через lifespan
   202	    try:
   203	        while True:  # noqa: ASYNC110
   204	            await asyncio.sleep(3600)
   205	    except asyncio.CancelledError:
   206	        await sub.stop()
   207	
   208	
   209	def _on_reading_callback(reading: Reading) -> None:
   210	    """Sync callback от ZMQSubscriber — обновляет состояние и ставит broadcast."""
   211	    _state.on_reading(reading)
   212	
   213	    if not _state.clients:
   214	        return  # Нет клиентов — не создавать очередные задачи
   215	
   216	    q = _state.broadcast_q
   217	    if q is None:
   218	        return
   219	
   220	    data = {
   221	        "type": "reading",
   222	        "timestamp": reading.timestamp.isoformat(),
   223	        "channel": reading.channel,
   224	        "value": reading.value,
   225	        "unit": reading.unit,
   226	        "status": reading.status.value,
   227	    }
   228	    try:
   229	        q.put_nowait(data)
   230	    except asyncio.QueueFull:
   231	        pass  # Отбрасываем показание, очередь переполнена
   232	
   233	
   234	# ---------------------------------------------------------------------------
   235	# История из SQLite
   236	# ---------------------------------------------------------------------------
   237	
   238	
   239	def _find_recent_db(data_dir: Path) -> Path | None:
   240	    """Найти самый свежий файл data_YYYY-MM-DD.db в директории."""
/Users/vladimir/Projects/cryodaq/README.md:18:- `cryodaq.web.server:app` — опциональный web-доступ для мониторинга.
/Users/vladimir/Projects/cryodaq/README.md:73:- backend-driven GUI для safety/alarm/status
/Users/vladimir/Projects/cryodaq/README.md:75:- журнал оператора в SQLite с GUI и command access
/Users/vladimir/Projects/cryodaq/README.md:99:pip install -e ".[dev,web]"
/Users/vladimir/Projects/cryodaq/README.md:102:Минимальная runtime-установка без dev/web extras:
/Users/vladimir/Projects/cryodaq/README.md:108:Если нужен только web dashboard, используйте:
/Users/vladimir/Projects/cryodaq/README.md:111:pip install -e ".[web]"
/Users/vladimir/Projects/cryodaq/README.md:141:uvicorn cryodaq.web.server:app --host 0.0.0.0 --port 8080
/Users/vladimir/Projects/cryodaq/README.md:144:Команда `uvicorn cryodaq.web.server:app` относится к optional web-path и требует установленного extra `web`
/Users/vladimir/Projects/cryodaq/README.md:145:(или полного dev/test install path `.[dev,web]`).
/Users/vladimir/Projects/cryodaq/README.md:253:  web/                # FastAPI monitoring dashboard
/Users/vladimir/Projects/cryodaq/README.md:281:Запускайте эти команды из корня репозитория после `pip install -e ".[dev,web]"`. GUI tests требуют установленного `PySide6` и `pyqtgraph`. Web dashboard в этот smoke set не входит и требует отдельного `.[web]` install path.
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:73:- **Web** (FastAPI, опционально): monitoring dashboard на `:8080`
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:74:- **IPC:** ZeroMQ PUB/SUB `:5555` (data, msgpack) + REP/REQ `:5556` (commands, JSON)
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:97:**A1 safety audit (`eb267c4`, 2026-04-17).** Latin Т12 исправлен в `config/interlocks.yaml` (description + два поясняющих комментария; сам `channel_pattern` был исправлен ранее в `9feaf3e`). `_fault()` получил early-return guard против concurrent re-entries. XSS в `web/server.py`, fail-closed в `load_config()`, stuck RUN_PERMITTED — всё уже закрыто, отмечено NOT REPRODUCIBLE.
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:101:**CI dependency fix (`1e824a7`).** `.github/workflows/main.yml` теперь ставит `.[dev,web]`, чтобы FastAPI / starlette / httpx тесты не скипались.
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:109:- **B.7 Keithley v2** (`920aa97`) — mode-based dual-channel overlay at `shell/overlays/keithley_panel.py`. Functional regression vs v1 (no V/I/R/P plots — v2 has 0 pyqtgraph refs, v1 had 4 — no P-target control, no A+B actions, no debounced spin controls, no K4 custom-command popup). Documented in `docs/legacy-inventory/keithley.md`. Maps to II.6 PARTIAL; scope to be reopened as a second block.
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:139:Architectural hardening of the engine ↔ GUI command plane after a production wedge revealed the `ZMQCommandServer` REP task crashing silently while the engine subprocess's `stderr=DEVNULL` swallowed the evidence. Ten commits; two Codex review rounds; final verdict PASS at `27dfecb`.
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:209:  - G.1 — web dashboard auth или loopback-only default
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:210:  - G.2 — web history/log query size bounds
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:221:- **GAP документы** (выявлены `docs/REPO_AUDIT_REPORT.md`): user-facing calibration guide, Web API spec (`/status`, `/history`, `/api/status`, `/ws`), instrument setup guide, operator-safety guide (в дополнение к developer-oriented `SAFETY_MANAGER_DEEP_DIVE.md`), TSP Phase-3 status.
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:248:pip install -e ".[dev,web]"    # runtime + dev + web extras
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:252:uvicorn cryodaq.web.server:app --host 0.0.0.0 --port 8080
/Users/vladimir/Projects/cryodaq/CLAUDE.md:52:pip install -e ".[dev,web]"    # Install runtime, dev, and optional web dependencies
/Users/vladimir/Projects/cryodaq/CLAUDE.md:55:#  so older install lines keep working: `pip install -e ".[dev,web,archive]"`.)
/Users/vladimir/Projects/cryodaq/CLAUDE.md:60:uvicorn cryodaq.web.server:app --host 0.0.0.0 --port 8080
/Users/vladimir/Projects/cryodaq/CLAUDE.md:89:- `cryodaq-engine` — headless asyncio runtime: acquisition, safety, storage, commands
/Users/vladimir/Projects/cryodaq/CLAUDE.md:91:- web dashboard — optional FastAPI monitoring surface
/Users/vladimir/Projects/cryodaq/CLAUDE.md:95:SafetyManager is the single authority for source on/off decisions.
/Users/vladimir/Projects/cryodaq/CLAUDE.md:102:     Note: request_run() can shortcut SAFE_OFF -> RUNNING when all preconditions met
/Users/vladimir/Projects/cryodaq/CLAUDE.md:193:- `src/cryodaq/core/zmq_bridge.py` — ZMQ PUB/SUB + REP/REQ command server
/Users/vladimir/Projects/cryodaq/CLAUDE.md:220:- `src/cryodaq/notifications/telegram_commands.py` — interactive command bot (/status /temps /pressure)
/Users/vladimir/Projects/cryodaq/CLAUDE.md:304:- `src/cryodaq/web/server.py`
/Users/vladimir/Projects/cryodaq/CLAUDE.md:310:- See `## Источник истины по UI/визуальному дизайну` above for the full reference and authority rules
/Users/vladimir/Projects/cryodaq/CLAUDE.md:401:   - Новые commands или entry points
/Users/vladimir/Projects/cryodaq/ROADMAP.md:30:| F5 | Engine events → Hermes webhook | ⬜ | M | M |
/Users/vladimir/Projects/cryodaq/ROADMAP.md:39:| F14 | Remote command approval (Telegram) | ⬜ | M | L |
/Users/vladimir/Projects/cryodaq/ROADMAP.md:59:All 4 findings PASS. Pending: real `git tag` command.
/Users/vladimir/Projects/cryodaq/ROADMAP.md:87:  (requires engine-side `cooldown_history_get` command; non-trivial)
/Users/vladimir/Projects/cryodaq/ROADMAP.md:88:- **F5** — Hermes webhook integration
/Users/vladimir/Projects/cryodaq/ROADMAP.md:172:  `readings_history` command; just needs widget.
/Users/vladimir/Projects/cryodaq/ROADMAP.md:174:  for comparison. Needs new engine command `cooldown_history_get` that
/Users/vladimir/Projects/cryodaq/ROADMAP.md:181:- `cooldown_history_get` command (returns list of `{experiment_id,
/Users/vladimir/Projects/cryodaq/ROADMAP.md:183:- Optional: `r_thermal_prediction` command if R_thermal predictor built
/Users/vladimir/Projects/cryodaq/ROADMAP.md:202:### F5 — Engine events → Hermes webhook
/Users/vladimir/Projects/cryodaq/ROADMAP.md:210:webhooks:
/Users/vladimir/Projects/cryodaq/ROADMAP.md:247:Extend `src/cryodaq/web/server.py` with:
/Users/vladimir/Projects/cryodaq/ROADMAP.md:252:- `WebSocket /ws` — live readings stream (verify if already exists)
/Users/vladimir/Projects/cryodaq/ROADMAP.md:253:- Auth or loopback-only default per deferred G.1
/Users/vladimir/Projects/cryodaq/ROADMAP.md:345:### F14 — Remote command approval (Telegram)
/Users/vladimir/Projects/cryodaq/ROADMAP.md:349:Telegram command `/emergency_off confirm` → CryoDAQ emergency stop.
/Users/vladimir/Projects/cryodaq/ROADMAP.md:350:Two-factor: command + confirmation within 30s. Rate-limited,
/Users/vladimir/Projects/cryodaq/ROADMAP.md:375:- 3-4 example plugins (Google Sheets uploader, webhook publisher,
/Users/vladimir/Projects/cryodaq/ROADMAP.md:423:### B1 — ZMQ subprocess command channel dies (not idle-related)
/Users/vladimir/Projects/cryodaq/ROADMAP.md:429:**Symptom:** GUI command plane (REQ/REP on `tcp://127.0.0.1:5556`)
/Users/vladimir/Projects/cryodaq/ROADMAP.md:443:unrecoverable state. Shared state across all commands means one
/Users/vladimir/Projects/cryodaq/ROADMAP.md:444:bad socket poisons the entire command channel permanently.
/Users/vladimir/Projects/cryodaq/ROADMAP.md:452:  command path in IV.6 batch; maybe helped with failure delay on
/Users/vladimir/Projects/cryodaq/ROADMAP.md:456:1. **Primary:** per-command ephemeral REQ socket in
/Users/vladimir/Projects/cryodaq/ROADMAP.md:461:2. **Secondary:** command-channel watchdog in `launcher.py`.
/Users/vladimir/Projects/cryodaq/ROADMAP.md:463:   not command-only failure. Add `command_channel_stalled()`
/Users/vladimir/Projects/cryodaq/ROADMAP.md:481:IV.6 landed the full Codex-proposed fix plan: per-command ephemeral
/Users/vladimir/Projects/cryodaq/ROADMAP.md:483:`command_channel_stalled()` watchdog in `_poll_bridge_data`, and
/Users/vladimir/Projects/cryodaq/ROADMAP.md:484:`TCP_KEEPALIVE` reverted on the command + PUB paths (kept on
/Users/vladimir/Projects/cryodaq/ROADMAP.md:504:elsewhere — likely libzmq loopback-TCP handling, pyzmq 25.x +
/Users/vladimir/Projects/cryodaq/ROADMAP.md:517:the TCP-loopback layer entirely, which is the most likely remaining
/Users/vladimir/Projects/cryodaq/ROADMAP.md:523:the launcher a genuine command-channel watchdog for any future
/Users/vladimir/Projects/cryodaq/ROADMAP.md:524:command-only failure shape — independent of whether B1 is
/Users/vladimir/Projects/cryodaq/ROADMAP.md:529:The IV.6 `command_channel_stalled()` watchdog had a regression:
/Users/vladimir/Projects/cryodaq/ROADMAP.md:537:command-watchdog restarts via `_last_cmd_watchdog_restart`

exec
/opt/homebrew/bin/bash -lc 'rg -n "Engine runs ZMQ|zmq_subprocess|GUI process never imports|subprocess|isolates|PUB|REP|ZMQPublisher|ZMQCommandServer|cryodaq.web.server|bridge subprocess" /Users/vladimir/Vault/CryoDAQ /Users/vladimir/Projects/cryodaq/CLAUDE.md /Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md /Users/vladimir/Projects/cryodaq/README.md /Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py /Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_subprocess.py -S' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:25:Источник актуального репо-инвентаря: `docs/REPO_AUDIT_REPORT.md` (2026-04-17).
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:46:8. **No blocking I/O** на engine event loop (исключение: `reporting/generator.py` sync `subprocess.run` для LibreOffice).
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:74:- **IPC:** ZeroMQ PUB/SUB `:5555` (data, msgpack) + REP/REQ `:5556` (commands, JSON)
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:97:**A1 safety audit (`eb267c4`, 2026-04-17).** Latin Т12 исправлен в `config/interlocks.yaml` (description + два поясняющих комментария; сам `channel_pattern` был исправлен ранее в `9feaf3e`). `_fault()` получил early-return guard против concurrent re-entries. XSS в `web/server.py`, fail-closed в `load_config()`, stuck RUN_PERMITTED — всё уже закрыто, отмечено NOT REPRODUCIBLE.
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:137:### IPC/REP hardening — shipped 2026-04-18
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:139:Architectural hardening of the engine ↔ GUI command plane after a production wedge revealed the `ZMQCommandServer` REP task crashing silently while the engine subprocess's `stderr=DEVNULL` swallowed the evidence. Ten commits; two Codex review rounds; final verdict PASS at `27dfecb`.
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:145:1. Bridge subprocess split — SUB drain + CMD forward on separate owner threads.
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:146:2. Data-flow watchdog independent of heartbeat (stall detection works even when PUB is alive).
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:148:4. `log_get` routed to a dedicated read executor (long reads don't block REP).
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:150:6. `ZMQCommandServer` task supervision — `add_done_callback` detects unexpected exit and spawns a fresh serve loop. Reentrancy-safe.
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:153:9. Engine subprocess stderr persisted to `logs/engine.stderr.log` via `RotatingFileHandler` (50MB × 3 backups), with handler lifecycle that survives engine restarts on Windows.
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:156:**Residual risk** documented in-code at `engine.py:1328`: `asyncio.wait_for(asyncio.to_thread(...))` cancels the await but not the worker thread. REP is protected by the outer envelope; the inner wrapper gives faster client feedback only.
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:221:- **GAP документы** (выявлены `docs/REPO_AUDIT_REPORT.md`): user-facing calibration guide, Web API spec (`/status`, `/history`, `/api/status`, `/ws`), instrument setup guide, operator-safety guide (в дополнение к developer-oriented `SAFETY_MANAGER_DEEP_DIVE.md`), TSP Phase-3 status.
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md:252:uvicorn cryodaq.web.server:app --host 0.0.0.0 --port 8080
/Users/vladimir/Projects/cryodaq/README.md:18:- `cryodaq.web.server:app` — опциональный web-доступ для мониторинга.
/Users/vladimir/Projects/cryodaq/README.md:141:uvicorn cryodaq.web.server:app --host 0.0.0.0 --port 8080
/Users/vladimir/Projects/cryodaq/README.md:144:Команда `uvicorn cryodaq.web.server:app` относится к optional web-path и требует установленного extra `web`
/Users/vladimir/Projects/cryodaq/CLAUDE.md:60:uvicorn cryodaq.web.server:app --host 0.0.0.0 --port 8080
/Users/vladimir/Projects/cryodaq/CLAUDE.md:193:- `src/cryodaq/core/zmq_bridge.py` — ZMQ PUB/SUB + REP/REQ command server
/Users/vladimir/Projects/cryodaq/CLAUDE.md:194:- `src/cryodaq/core/zmq_subprocess.py` — subprocess isolation for ZMQ bridge
/Users/vladimir/Projects/cryodaq/CLAUDE.md:261:- `src/cryodaq/gui/zmq_client.py` — ZMQ bridge client for GUI (all ZMQ lives in a subprocess)
/Users/vladimir/Projects/cryodaq/CLAUDE.md:304:- `src/cryodaq/web/server.py`
/Users/vladimir/Projects/cryodaq/CLAUDE.md:348:- No blocking I/O on the engine event loop (known exception: `reporting/generator.py` uses sync `subprocess.run()` for LibreOffice PDF conversion — DEEP_AUDIT finding E.2).
/Users/vladimir/Projects/cryodaq/CLAUDE.md:430:- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_subprocess.py:4:assertion on Windows), only this subprocess dies. The GUI detects
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_subprocess.py:7:The GUI process never imports zmq.
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_subprocess.py:9:Threading model (see fix(gui): split bridge subprocess ...):
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_subprocess.py:31:DEFAULT_PUB_ADDR = "tcp://127.0.0.1:5555"
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_subprocess.py:64:    """Entry point for ZMQ bridge subprocess.
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_subprocess.py:69:        Engine PUB address, e.g. "tcp://127.0.0.1:5555".
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_subprocess.py:71:        Engine REP address, e.g. "tcp://127.0.0.1:5556".
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_subprocess.py:76:        GUI → subprocess: command dicts to send via REQ.
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_subprocess.py:95:        alive, not just that the subprocess exists.
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_subprocess.py:193:            # (_CMD_REPLY_TIMEOUT_S), so timeouts at each layer fire
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_subprocess.py:194:            # in predictable order: server → subprocess → GUI future.
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_subprocess.py:223:                                "message": f"REP timeout on {cmd_type} ({exc})",
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py:3:ZMQPublisher — PUB-сокет в engine, сериализует Reading через msgpack.
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py:5:ZMQCommandServer — REP-сокет в engine, принимает JSON-команды от GUI.
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py:27:DEFAULT_PUB_ADDR = "tcp://127.0.0.1:5555"
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py:35:# report generation). When they timed out the outer REP reply path
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py:155:class ZMQPublisher:
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py:156:    """PUB-сокет: engine публикует Reading для GUI и внешних подписчиков.
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py:160:        pub = ZMQPublisher("tcp://127.0.0.1:5555")
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py:166:    def __init__(self, address: str = DEFAULT_PUB_ADDR, *, topic: bytes = DEFAULT_TOPIC) -> None:
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py:190:        self._socket = self._ctx.socket(zmq.PUB)
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py:199:        # reverted on the command path (REQ + REP); retained on the
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py:200:        # SUB drain path in zmq_subprocess.sub_drain_loop as an
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py:205:        logger.info("ZMQPublisher запущен: %s", self._address)
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py:222:        logger.info("ZMQPublisher остановлен (отправлено: %d)", self._total_sent)
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py:241:        address: str = DEFAULT_PUB_ADDR,
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py:311:class ZMQCommandServer:
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py:312:    """REP-сокет: engine принимает JSON-команды от GUI.
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py:319:        srv = ZMQCommandServer(handler=handler)
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py:356:        """Restart the REP loop after unexpected task exit."""
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py:371:                "ZMQCommandServer serve loop crashed; restarting",
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py:375:            logger.error("ZMQCommandServer serve loop exited unexpectedly; restarting")
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py:379:            logger.error("ZMQCommandServer loop is closed; cannot restart serve loop")
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py:386:        IV.3 Finding 7: always returns a dict. REP sockets require exactly
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py:388:        leave REP wedged and cascade every subsequent command into
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py:401:        # so REP was not wedged, but the failure path was accidental.
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py:459:            # dict back through the normal return path keeps the REP
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py:482:            # Once recv() succeeds, the REP socket is in "awaiting send" state.
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py:494:                # to avoid leaving REP socket in stuck state.
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py:516:                # to avoid leaving the REP socket in stuck state.
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py:526:        self._socket = self._ctx.socket(zmq.REP)
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py:531:        # an ephemeral per-command REQ socket on the GUI subprocess
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py:532:        # side (zmq_subprocess.cmd_forward_loop). With a fresh TCP
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py:538:        logger.info("ZMQCommandServer запущен: %s", self._address)
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py:556:        logger.info("ZMQCommandServer остановлен")
/Users/vladimir/Vault/CryoDAQ/50 Workflow/Multi-model consultation.md:39:| **Codex (gpt-5.5 / high)** | Adversarial code review with file:line refs. Concurrency, race conditions, IPC, subprocess, socket state. Terse FAIL/PASS verdicts. | Diff review pre-commit; specific bug hypothesis test; ZMQ / asyncio / subprocess code; ≤ 500-line diffs. | Long-prose strategy; "review the entire repo"; > 10 files at once. |
/Users/vladimir/Vault/CryoDAQ/60 Roadmap/Versions.md:19:| `v0.33.0` | (last released tag) | shipped | Phase I.1 shell + design system v1.0.1 + IPC/REP hardening + theme switcher | tag points at the v0.33.0 sha (see `git show v0.33.0`) |
/Users/vladimir/Vault/CryoDAQ/00 Overview/What is CryoDAQ.md:47:3. `cryodaq.web.server:app` — optional FastAPI monitoring on `:8080`.
/Users/vladimir/Vault/CryoDAQ/00 Overview/What is CryoDAQ.md:49:ZeroMQ topology: PUB/SUB `:5555` for data (msgpack), REP/REQ `:5556`
/Users/vladimir/Vault/CryoDAQ/00 Overview/What is CryoDAQ.md:50:for commands (JSON). The bridge subprocess isolates engine from GUI
/Users/vladimir/Vault/CryoDAQ/40 Decisions/2026-04-24-d1-d4a-execution.md:47:  1. `bridge.is_alive()` single-shot subprocess-spawn-failure catch.
/Users/vladimir/Vault/CryoDAQ/40 Decisions/2026-04-24-d1-d4a-execution.md:56:  tcp://, delayed-REP harness) deferred to a hardware-validation
/Users/vladimir/Vault/CryoDAQ/40 Decisions/2026-04-24-d1-d4a-execution.md:79:- Verified `ZmqBridge.send_command` + `zmq_subprocess.cmd_forward_loop`:
/Users/vladimir/Vault/CryoDAQ/40 Decisions/2026-04-24-b2b4fb5-investigation.md:19:because the engine's REP socket isn't ready when the probe fires,
/Users/vladimir/Vault/CryoDAQ/40 Decisions/2026-04-24-b2b4fb5-investigation.md:45:   (pyzmq/asyncio integration) and H5 (engine REP state machine)
/Users/vladimir/Vault/CryoDAQ/40 Decisions/2026-04-24-b2b4fb5-investigation.md:66:  subprocess startup must accommodate non-instantaneous bind
/Users/vladimir/Vault/CryoDAQ/00 Overview/Architecture overview.md:15:                 ZMQ PUB :5555 (data, msgpack)
/Users/vladimir/Vault/CryoDAQ/00 Overview/Architecture overview.md:16:                 ZMQ REP :5556 (commands, JSON)
/Users/vladimir/Vault/CryoDAQ/00 Overview/Architecture overview.md:23:                  cryodaq.web.server:app
/Users/vladimir/Vault/CryoDAQ/00 Overview/Architecture overview.md:35:  `subprocess.run` for best-effort PDF — DEEP_AUDIT finding E.2)
/Users/vladimir/Vault/CryoDAQ/00 Overview/Architecture overview.md:40:to engine PUB stream; sends commands via REQ. Since v0.33.0 the
/Users/vladimir/Vault/CryoDAQ/00 Overview/Architecture overview.md:52:**Web (`cryodaq.web.server:app`).** Optional FastAPI surface on
/Users/vladimir/Vault/CryoDAQ/00 Overview/Architecture overview.md:76:- **PUB/SUB :5555** — data plane (msgpack). Always-on stream of
/Users/vladimir/Vault/CryoDAQ/00 Overview/Architecture overview.md:78:- **REP/REQ :5556** — command plane (JSON). Operator commands
/Users/vladimir/Vault/CryoDAQ/00 Overview/Architecture overview.md:80:- **Subprocess isolation.** Engine runs ZMQ in a child subprocess
/Users/vladimir/Vault/CryoDAQ/00 Overview/Architecture overview.md:81:  (`core/zmq_subprocess.py`); the engine main loop is shielded from
/Users/vladimir/Vault/CryoDAQ/40 Decisions/ADR-002 R1 bounded-backoff probe retry.md:16:subprocess-spawn failure rather than wait 35 s for a misleading
/Users/vladimir/Vault/CryoDAQ/40 Decisions/ADR-002 R1 bounded-backoff probe retry.md:22:ipc:// Unix-socket bind, the engine's REP socket may not be ready
/Users/vladimir/Vault/CryoDAQ/40 Decisions/ADR-002 R1 bounded-backoff probe retry.md:43:   subprocess-spawn-failure detection that was the original intent.
/Users/vladimir/Vault/CryoDAQ/40 Decisions/ADR-002 R1 bounded-backoff probe retry.md:62:  Cheapest, but the catch is genuinely useful when subprocess fails
/Users/vladimir/Vault/CryoDAQ/40 Decisions/ADR-002 R1 bounded-backoff probe retry.md:69:  checks at engine / subprocess startup must accommodate
/Users/vladimir/Vault/CryoDAQ/40 Decisions/ADR-002 R1 bounded-backoff probe retry.md:89:  `zmq_subprocess.cmd_forward_loop` to confirm no retry-induced
/Users/vladimir/Vault/CryoDAQ/_meta/source map.md:34:| [[10 Subsystems/ZMQ bridge]] | src/cryodaq/core/zmq_bridge.py; src/cryodaq/core/zmq_subprocess.py; docs/bug_B1_zmq_idl... | 2026-04-26 | 6 | 6 |
/Users/vladimir/Vault/CryoDAQ/30 Investigations/B1 ZMQ idle-death.md:26:engine REP answering a direct in-process Python client in 0.001 s
/Users/vladimir/Vault/CryoDAQ/30 Investigations/B1 ZMQ idle-death.md:27:while the bridge subprocess was deep into B1, suggesting the engine
/Users/vladimir/Vault/CryoDAQ/30 Investigations/B1 ZMQ idle-death.md:29:handoff doc's addendum reports the engine REP also going silently
/Users/vladimir/Vault/CryoDAQ/30 Investigations/B1 ZMQ idle-death.md:37:| Ubuntu 22.04 (Python 3.12.13, pyzmq 26.4.0) | exactly 120 s after subprocess start (single data point, may vary) |
/Users/vladimir/Vault/CryoDAQ/30 Investigations/B1 ZMQ idle-death.md:48:| H4 | pyzmq 25.x + Python 3.14 asyncio integration / engine REP task state under rapid REQ connect-disconnect churn | not yet tested in isolation | **untested** — D2 split-context falsification experiment scheduled |
/Users/vladimir/Vault/CryoDAQ/30 Investigations/B1 ZMQ idle-death.md:49:| H5 | engine REP state machine | not yet specifically probed | **untested** |
/Users/vladimir/Vault/CryoDAQ/30 Investigations/B1 ZMQ idle-death.md:53:- Engine REP socket itself — direct Python REQ client gets 0.001 s
/Users/vladimir/Vault/CryoDAQ/30 Investigations/B1 ZMQ idle-death.md:57:- Raw subprocess without `ZmqBridge` wrapping (`diag_zmq_subprocess.py`)
/Users/vladimir/Vault/CryoDAQ/30 Investigations/B1 ZMQ idle-death.md:64:   only; Linux unaffected. Reverted on command + PUB paths since H1
/Users/vladimir/Vault/CryoDAQ/30 Investigations/B1 ZMQ idle-death.md:84:- `tools/diag_zmq_subprocess.py` — subprocess alone, short.
/Users/vladimir/Vault/CryoDAQ/30 Investigations/B1 ZMQ idle-death.md:100:to restart the bridge subprocess". The IV.6 watchdog cooldown
/Users/vladimir/Vault/CryoDAQ/30 Investigations/Codex H2 wrong hypothesis.md:31:> The GUI-side subprocess command plane uses one long-lived REQ
/Users/vladimir/Vault/CryoDAQ/30 Investigations/Codex H2 wrong hypothesis.md:40:`zmq_subprocess.py`. Pointed to ZeroMQ Guide ch. 4 canonical
/Users/vladimir/Vault/CryoDAQ/30 Investigations/Codex H2 wrong hypothesis.md:50:  `zmq_subprocess.cmd_forward_loop`.
/Users/vladimir/Vault/CryoDAQ/30 Investigations/Codex H2 wrong hypothesis.md:55:- `TCP_KEEPALIVE` reverted on command + PUB paths (kept on SUB
/Users/vladimir/Vault/CryoDAQ/30 Investigations/IV.6 cmd plane hardening.md:16:   `zmq_subprocess.cmd_forward_loop`. `_new_req_socket()` creates a
/Users/vladimir/Vault/CryoDAQ/30 Investigations/IV.6 cmd plane hardening.md:21:   `_poll_bridge_data` — restarts bridge subprocess if cmd plane is
/Users/vladimir/Vault/CryoDAQ/30 Investigations/IV.6 cmd plane hardening.md:23:3. **`TCP_KEEPALIVE` reverted on command + PUB paths** (kept on
/Users/vladimir/Vault/CryoDAQ/30 Investigations/IV.6 cmd plane hardening.md:44:in the handoff doc reports that the engine REP itself can also go
/Users/vladimir/Vault/CryoDAQ/30 Investigations/IV.6 cmd plane hardening.md:46:asyncio loop, data-plane PUB, heartbeats, scheduler writes, and
/Users/vladimir/Vault/CryoDAQ/30 Investigations/IV.6 cmd plane hardening.md:49:unclear, and H4 (pyzmq 25 / Python 3.14 asyncio) and H5 (engine REP
/Users/vladimir/Vault/CryoDAQ/30 Investigations/IV.6 cmd plane hardening.md:55:across watchdog-triggered subprocess restart. A fresh subprocess
/Users/vladimir/Vault/CryoDAQ/30 Investigations/b2b4fb5 hardening race.md:42:The hardening probe added a guard against subprocess-spawn-failure:
/Users/vladimir/Vault/CryoDAQ/30 Investigations/b2b4fb5 hardening race.md:45:behavior was that a broken subprocess would surface as cryptic
/Users/vladimir/Vault/CryoDAQ/30 Investigations/b2b4fb5 hardening race.md:57:engine's REP socket may not be ready when the probe fires; the
/Users/vladimir/Vault/CryoDAQ/30 Investigations/b2b4fb5 hardening race.md:58:bridge subprocess returns `zmq.Again` to the diag, and the diag
/Users/vladimir/Vault/CryoDAQ/30 Investigations/b2b4fb5 hardening race.md:86:1. `bridge.is_alive()` single-shot — keeps subprocess-spawn-failure
/Users/vladimir/Vault/CryoDAQ/_meta/build log.md:154:  - IV.6 phrasing implies engine REP dead — actually bridge REQ
/Users/vladimir/Vault/CryoDAQ/_meta/build log.md:155:    path; engine REP itself answers fresh clients
/Users/vladimir/Vault/CryoDAQ/_meta/build log.md:165:  Т4 alarm-group state, IV.6 phrasing about engine REP. All fixed.
/Users/vladimir/Vault/CryoDAQ/_meta/build log.md:189:  MEDIUM, 1 LOW). Convergent with Gemini on the engine-REP-vs-bridge
/Users/vladimir/Vault/CryoDAQ/_meta/build log.md:190:  phrasing — the source itself contradicts its earlier "engine REP
/Users/vladimir/Vault/CryoDAQ/_meta/build log.md:191:  healthy" claim with the post-IV.6 "engine REP can also go
/Users/vladimir/Vault/CryoDAQ/_meta/build log.md:216:- Convergent fixes: 3 (engine-REP-phrasing across B1 / IV.6 /
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/ZMQ bridge.md:2:source: src/cryodaq/core/zmq_bridge.py; src/cryodaq/core/zmq_subprocess.py; docs/bug_B1_zmq_idle_death_handoff.md; CHANGELOG IPC/REP hardening; ROADMAP "Known broken"
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/ZMQ bridge.md:10:independent channels and lives partly in the engine (PUB / REP
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/ZMQ bridge.md:11:sockets) and partly in a dedicated GUI-side subprocess that the GUI
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/ZMQ bridge.md:18:| Data plane | PUB / SUB | `tcp://127.0.0.1:5555` (default; `ipc://` experiment in IV.7) | msgpack | Continuous reading stream + alarm events + safety state |
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/ZMQ bridge.md:19:| Command plane | REP / REQ | `tcp://127.0.0.1:5556` | JSON | Operator commands, status queries |
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/ZMQ bridge.md:21:Topic for data plane is `b"readings"`. The engine PUBs are owned by
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/ZMQ bridge.md:22:`ZMQPublisher` + `ZMQCommandServer` (`zmq_bridge.py`). Connection
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/ZMQ bridge.md:25:+ pyzmq 25 (documented at `zmq_subprocess.py:97`).
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/ZMQ bridge.md:29:The GUI process never imports `zmq` directly. Instead, `mp.Process`
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/ZMQ bridge.md:30:spawns `zmq_bridge_main()` (`zmq_subprocess.py:56`), which owns ALL
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/ZMQ bridge.md:34:subprocess; the GUI itself survives.
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/ZMQ bridge.md:36:Two threads inside the subprocess:
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/ZMQ bridge.md:40:  *data path* is alive (not just that the subprocess exists).
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/ZMQ bridge.md:46:Engine REP wraps each command handler in `asyncio.wait_for(timeout=
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/ZMQ bridge.md:56:"handler timeout"}` rather than silent exception — REP socket
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/ZMQ bridge.md:78:  `_poll_bridge_data` — restarts the bridge subprocess if the cmd
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/ZMQ bridge.md:80:- `TCP_KEEPALIVE` reverted on command + PUB paths (kept on
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/ZMQ bridge.md:92:across watchdog-triggered subprocess restart, so the fresh
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/ZMQ bridge.md:93:subprocess immediately saw a stale timeout signal on the next
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/ZMQ bridge.md:109:Python 3.14 asyncio integration) and H5 (engine REP state machine)
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/ZMQ bridge.md:127:  H5 (engine REP state machine).
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/Safety FSM.md:25:across REQ clients (GUI subprocess + web dashboard + future operator
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/Safety FSM.md:135:  state. Operator commands flow as REQ → REP and the FSM is the

exec
/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Projects/cryodaq/src/cryodaq/web/server.py | sed -n '240,520p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   240	    """Найти самый свежий файл data_YYYY-MM-DD.db в директории."""
   241	    if not data_dir.exists():
   242	        return None
   243	    db_files = sorted(data_dir.glob("data_????-??-??.db"))
   244	    return db_files[-1] if db_files else None
   245	
   246	
   247	def _query_history(minutes: int) -> dict[str, list[dict[str, Any]]]:
   248	    """Запросить данные из SQLite за последние N минут.
   249	
   250	    Сканирует все DB-файлы, чей date-суффикс может пересекаться с окном запроса,
   251	    чтобы корректно обрабатывать cross-midnight запросы.
   252	
   253	    Возвращает словарь: channel → [{"t": iso, "v": float, "u": unit}, ...]
   254	    """
   255	    cutoff = datetime.now(UTC) - timedelta(minutes=minutes)
   256	    cutoff_epoch = cutoff.timestamp()
   257	
   258	    result: dict[str, list[dict[str, Any]]] = {}
   259	
   260	    if not _DATA_DIR.exists():
   261	        return result
   262	
   263	    for db_path in sorted(_DATA_DIR.glob("data_????-??-??.db")):
   264	        conn = None
   265	        try:
   266	            conn = sqlite3.connect(str(db_path), timeout=5)
   267	            conn.row_factory = sqlite3.Row
   268	            rows = conn.execute(
   269	                "SELECT timestamp, channel, value, unit FROM readings "
   270	                "WHERE timestamp >= ? ORDER BY timestamp ASC",
   271	                (cutoff_epoch,),
   272	            ).fetchall()
   273	        except Exception:
   274	            continue
   275	        finally:
   276	            if conn is not None:
   277	                conn.close()
   278	        for row in rows:
   279	            ch = row["channel"]
   280	            result.setdefault(ch, []).append(
   281	                {
   282	                    "t": datetime.fromtimestamp(row["timestamp"], tz=UTC).isoformat(),
   283	                    "v": row["value"],
   284	                    "u": row["unit"],
   285	                }
   286	            )
   287	
   288	    return result
   289	
   290	
   291	# ---------------------------------------------------------------------------
   292	# FastAPI приложение
   293	# ---------------------------------------------------------------------------
   294	
   295	
   296	def create_app() -> FastAPI:
   297	    """Создать и настроить FastAPI-приложение."""
   298	    application = FastAPI(
   299	        title="CryoDAQ Web Dashboard",
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
   325	        logger.info("Веб-сервер CryoDAQ остановлен")
   326	
   327	    # Статические файлы
   328	    if _STATIC_DIR.exists():
   329	        application.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
   330	
   331	    @application.get("/", response_class=HTMLResponse)
   332	    async def index() -> HTMLResponse:
   333	        """Главная страница — self-contained HTML dashboard."""
   334	        return HTMLResponse(content=_DASHBOARD_HTML.replace("__VERSION__", _VERSION))
   335	
   336	    @application.get("/status")
   337	    async def status() -> dict[str, Any]:
   338	        """JSON-статус системы."""
   339	        return _state.status_json()
   340	
   341	    @application.get("/api/status")
   342	    async def api_status() -> dict[str, Any]:
   343	        """Полный JSON-статус: readings + experiment + shift."""
   344	        base = _state.status_json()
   345	        base["readings"] = _state.last_readings
   346	        # Safety status via engine command
   347	        try:
   348	            safety = await _async_engine_command({"cmd": "safety_status"})
   349	            base["safety"] = safety if safety.get("ok") else None
   350	            if safety.get("ok"):
   351	                _state.safety_state = safety.get("state", "unknown")
   352	        except Exception:
   353	            base["safety"] = None
   354	        # Alarm status via engine command
   355	        try:
   356	            alarms = await _async_engine_command({"cmd": "alarm_v2_status"})
   357	            if alarms.get("ok"):
   358	                base["active_alarms"] = alarms.get("active", {})
   359	                _state.active_alarms = alarms.get("active", {})
   360	        except Exception:
   361	            pass
   362	        # Experiment/shift data via ZMQ command
   363	        try:
   364	            exp = await _async_engine_command({"cmd": "experiment_status"})
   365	            base["experiment"] = exp if exp.get("ok") else None
   366	        except Exception:
   367	            base["experiment"] = None
   368	        return base
   369	
   370	    @application.get("/api/log")
   371	    async def api_log(limit: int = 10) -> dict[str, Any]:
   372	        """Последние записи журнала."""
   373	        try:
   374	            result = await _async_engine_command({"cmd": "log_get", "limit": limit})
   375	            if result.get("ok"):
   376	                return {"ok": True, "entries": result.get("entries", [])}
   377	        except Exception:
   378	            pass
   379	        return {"ok": False, "entries": []}
   380	
   381	    @application.get("/history")
   382	    async def history(minutes: int = 60) -> dict[str, Any]:
   383	        """Исторические данные из SQLite за последние N минут.
   384	
   385	        Возвращает::
   386	
   387	            {
   388	              "channels": {
   389	                "Т1": [{"t": "2026-03-14T10:00:00+00:00", "v": 4.2, "u": "K"}, ...],
   390	                ...
   391	              }
   392	            }
   393	        """
   394	        loop = asyncio.get_running_loop()
   395	        channels = await loop.run_in_executor(None, _query_history, minutes)
   396	        return {"channels": channels}
   397	
   398	    @application.websocket("/ws")
   399	    async def websocket_endpoint(ws: WebSocket) -> None:
   400	        """WebSocket — поток показаний в реальном времени."""
   401	        await ws.accept()
   402	        _state.clients.add(ws)
   403	        logger.info("WebSocket клиент подключён (всего: %d)", len(_state.clients))
   404	        try:
   405	            while True:
   406	                # Ждём ping/pong или команды от клиента
   407	                await ws.receive_text()
   408	        except WebSocketDisconnect:
   409	            pass
   410	        finally:
   411	            _state.clients.discard(ws)
   412	            logger.info("WebSocket клиент отключён (всего: %d)", len(_state.clients))
   413	
   414	    return application
   415	
   416	
   417	_DASHBOARD_HTML = """<!DOCTYPE html>
   418	<html lang="ru">
   419	<head>
   420	<meta charset="utf-8">
   421	<meta name="viewport" content="width=device-width,initial-scale=1">
   422	<title>CryoDAQ Monitor</title>
   423	<style>
   424	*{margin:0;padding:0;box-sizing:border-box}
   425	body{background:#0d1117;color:#c9d1d9;font-family:system-ui,-apple-system,sans-serif;padding:8px}
   426	.header{display:flex;justify-content:space-between;align-items:center;padding:8px 12px;
   427	background:#161b22;border:1px solid #30363d;border-radius:6px;margin-bottom:8px}
   428	.header h1{font-size:16px;color:#f0f6fc}
   429	.header .ver{color:#8b949e;font-size:12px}
   430	.status-bar{display:flex;gap:16px;padding:8px 12px;background:#161b22;
   431	border:1px solid #30363d;border-radius:6px;margin-bottom:8px;flex-wrap:wrap}
   432	.status-bar .item{font-size:13px}
   433	.section{background:#161b22;border:1px solid #30363d;border-radius:6px;
   434	padding:10px 12px;margin-bottom:8px}
   435	.section-title{font-size:12px;color:#8b949e;margin-bottom:6px;text-transform:uppercase}
   436	.temps{display:grid;grid-template-columns:repeat(8,1fr);gap:4px}
   437	@media(max-width:600px){.temps{grid-template-columns:repeat(4,1fr)}}
   438	.temp-card{background:#21262d;border-radius:4px;padding:4px 6px;text-align:center}
   439	.temp-card .name{font-size:10px;color:#8b949e}
   440	.temp-card .val{font-size:16px;font-weight:bold}
   441	.cold{color:#58a6ff} .mid{color:#c9d1d9} .warm{color:#f0883e} .hot{color:#f85149}
   442	.log-entry{font-size:12px;color:#8b949e;padding:2px 0;border-bottom:1px solid #21262d}
   443	.log-entry .ts{color:#58a6ff}
   444	#updated{font-size:11px;color:#484f58;text-align:right;padding:4px}
   445	</style>
   446	</head>
   447	<body>
   448	<div class="header"><h1>CryoDAQ Monitor</h1><span class="ver">v__VERSION__</span></div>
   449	<div class="status-bar">
   450	 <span class="item" id="safety">—</span>
   451	 <span class="item" id="uptime">Аптайм: --:--:--</span>
   452	 <span class="item" id="alarms">—</span>
   453	 <span class="item" id="channels">0 каналов</span>
   454	</div>
   455	<div class="section"><div class="section-title">Эксперимент</div><div id="experiment">—</div></div>
   456	<div class="section"><div class="section-title">Температуры</div>
   457	<div class="temps" id="temps"></div></div>
   458	<div class="section"><div class="section-title">Давление</div><div id="pressure">—</div></div>
   459	<div class="section"><div class="section-title">Keithley</div><div id="keithley">—</div></div>
   460	<div class="section"><div class="section-title">Журнал</div><div id="log"></div></div>
   461	<div id="updated"></div>
   462	<script>
   463	function escapeHtml(s){if(s==null)return '';return String(s)
   464	 .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
   465	 .replace(/"/g,'&quot;').replace(/'/g,'&#39;')}
   466	function tempColor(v){if(v<10)return'cold';if(v<100)return'mid';if(v<250)return'warm';return'hot'}
   467	async function refresh(){
   468	 try{
   469	  const r=await fetch('/api/status');const d=await r.json();
   470	  document.getElementById('uptime').textContent='Аптайм: '+(d.uptime||'--');
   471	  document.getElementById('channels').textContent=(d.channels||0)+' каналов';
   472	  // Safety state
   473	  const safety=d.safety;
   474	  if(safety&&safety.state){
   475	   const st=safety.state;
   476	   const el=document.getElementById('safety');
   477	   el.textContent=st.toUpperCase();
   478	   el.style.color=(st==='fault'||st==='fault_latched')?'#f85149':'#3fb950';
   479	  }else{document.getElementById('safety').textContent='—'}
   480	  // Alarms
   481	  const aa=d.active_alarms||{};
   482	  const ac=Object.keys(aa).length;
   483	  document.getElementById('alarms').textContent=ac+' алармов';
   484	  // Readings
   485	  const readings=d.readings||{};
   486	  let temps='',pressure='—',kA='ВЫКЛ',kB='ВЫКЛ';
   487	  const sorted=Object.entries(readings).sort((a,b)=>a[0].localeCompare(b[0]));
   488	  for(const[ch,r]of sorted){
   489	   if(r.unit==='K'&&ch.match(/^\\u0422|^T/)){
   490	    const c=tempColor(r.value);
   491	    temps+=`<div class="temp-card"><div class="name">${escapeHtml(ch.split(' ')[0])}</div>`+
   492	      `<div class="val ${c}">${r.value.toFixed(2)}</div></div>`;
   493	   }
   494	   if(r.unit==='mbar')pressure=r.value.toExponential(2)+' mbar';
   495	   if(ch.includes('/smua/'))kA=ch.endsWith('power')?'ВКЛ '+r.value.toFixed(1)+'W':kA;
   496	   if(ch.includes('/smub/'))kB=ch.endsWith('power')?'ВКЛ '+r.value.toFixed(1)+'W':kB;
   497	  }
   498	  document.getElementById('temps').innerHTML=temps||'Нет данных';
   499	  document.getElementById('pressure').textContent=pressure;
   500	  document.getElementById('keithley').textContent='A: '+kA+' │ B: '+kB;
   501	  // Experiment
   502	  const exp=d.experiment;
   503	  if(exp&&exp.active_experiment){
   504	   const e=exp.active_experiment;
   505	   const phase=exp.current_phase?' ['+exp.current_phase+']':'';
   506	   document.getElementById('experiment').textContent=(e.name||'—')+phase;
   507	  }else{document.getElementById('experiment').textContent='Нет активного эксперимента'}
   508	 }catch(e){document.getElementById('updated').textContent='Ошибка: '+e.message}
   509	 // Log
   510	 try{
   511	  const lr=await fetch('/api/log?limit=5');const ld=await lr.json();
   512	  let html='';
   513	  for(const e of(ld.entries||[])){
   514	   const ts=(e.timestamp||'').split('T')[1]||'';
   515	   html+=`<div class="log-entry"><span class="ts">${ts.substring(0,8)}</span> `+
   516	     `[${escapeHtml(e.author||e.source||'?')}] ${escapeHtml(e.message||'')}</div>`;
   517	  }
   518	  document.getElementById('log').innerHTML=html||'Нет записей';
   519	 }catch(e){}
   520	 document.getElementById('updated').textContent='Обновлено: '+new Date().toLocaleTimeString();

exec
/opt/homebrew/bin/bash -lc "rg -n \"alarms_v3|channel pattern|matches at least one|Latin|Cyrillic|U\\+0422|config/channels|channel_groups|uncalibrated|all_temp|Т4|Т8|Т\\[1-8\\]|Т\\(1\\|2\\|3\\|5\\|6\\|7\\|8\\)\" /Users/vladimir/Projects/cryodaq/tests /Users/vladimir/Projects/cryodaq/docs/design-system /Users/vladimir/Projects/cryodaq/config/channels.yaml -S" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
/Users/vladimir/Projects/cryodaq/config/channels.yaml:17:  Т4:
/Users/vladimir/Projects/cryodaq/config/channels.yaml:37:  Т8:
/Users/vladimir/Projects/cryodaq/docs/design-system/V101_REVIEW_REPORT.md:15:| R5 Domain accuracy | FAIL | Normative docs still contain uppercase FSM labels and operator-facing Latin `T` / `mbar` examples. T11/T12 metrology, Keithley TSP/dual-channel, and SafetyManager authority are otherwise correct. |
/Users/vladimir/Projects/cryodaq/docs/design-system/V101_REVIEW_REPORT.md:32:- **[V-006]** Check R5: [docs/design-system/tokens/colors.md:89] — normative operator-facing example uses Latin `T5` (`T5 Экран 77К badge`); the same drift appears in [docs/design-system/rules/color-rules.md:500] (`T5`, `T6`). Operator-facing channel IDs must use Cyrillic `Т`. Severity: CRITICAL.
/Users/vladimir/Projects/cryodaq/docs/design-system/V101_REVIEW_REPORT.md:42:- Normalize domain invariants everywhere: lowercase FSM states only, Cyrillic `Т` in operator-facing channel examples, `мбар` in operator-facing pressure examples.
/Users/vladimir/Projects/cryodaq/docs/design-system/governance/testing-strategy.md:130:### Cyrillic Т vs Latin T lint
/Users/vladimir/Projects/cryodaq/docs/design-system/governance/testing-strategy.md:132:Catch Latin T in channel IDs:
/Users/vladimir/Projects/cryodaq/docs/design-system/governance/testing-strategy.md:339:- **RULE-COPY-001** — Cyrillic Т (enforced via lint)
/Users/vladimir/Projects/cryodaq/docs/design-system/accessibility/wcag-baseline.md:95:| **3.1.1 Language of Page** (A) | Met | `lang="ru"` on shell; technical Latin subsystem names (Engine, ZMQ) within Russian context don't count as language switch |
/Users/vladimir/Projects/cryodaq/docs/design-system/accessibility/wcag-baseline.md:96:| **3.1.2 Language of Parts** (AA) | Partial | Subsystem names in Latin not individually marked; operators treat them as borrowed vocabulary |
/Users/vladimir/Projects/cryodaq/docs/design-system/ANTI_PATTERNS.md:185:**Pattern:** Channel label `"T1 Криостат верх"` using Latin T (U+0054).
/Users/vladimir/Projects/cryodaq/docs/design-system/ANTI_PATTERNS.md:187:**Why forbidden:** Violates RULE-COPY-001. Russian UI uses Cyrillic Т (U+0422). Latin T breaks Russian typographic consistency and may interact poorly with Cyrillic-optimized fonts.
/Users/vladimir/Projects/cryodaq/docs/design-system/ANTI_PATTERNS.md:189:**Fix:** Use Cyrillic Т throughout. Consistent across all 24 temperature channels.
/Users/vladimir/Projects/cryodaq/docs/design-system/ANTI_PATTERNS.md:223:**Why forbidden:** Violates RULE-TYPO-005. Cyrillic uppercase has narrower default tracking than Latin; needs positive letter-spacing.
/Users/vladimir/Projects/cryodaq/docs/design-system/ANTI_PATTERNS.md:225:**Fix:** `font.setLetterSpacing(QFont.AbsoluteSpacing, 0.05)` for Cyrillic uppercase labels.
/Users/vladimir/Projects/cryodaq/docs/design-system/FINAL_REVIEW_REPORT.md:9:This does **not** require a redesign. It requires a targeted v1.0.1 doc repair pass. The codebase ground truth is stable enough: `src/cryodaq/gui/theme.py`, current dashboard widgets, `config/channels.yaml`, and `config/safety.yaml` make the intended reality readable. The design-system docs need to catch up to that reality and stop mixing current-state guidance with future-state proposals without labeling.
/Users/vladimir/Projects/cryodaq/docs/design-system/FINAL_REVIEW_REPORT.md:114:- No CRITICAL domain-safety drift of the type feared in the prompt was found. I did **not** find “only certified T11/T12”, Latin `T11` in operator-facing guidance, uppercase FSM states as normative UI labels, or linear-pressure guidance in chart specs.
/Users/vladimir/Projects/cryodaq/docs/design-system/MANIFEST.md:23:│   ├── typography.md                   # 36 typography tokens, Fira fonts, Cyrillic rules
/Users/vladimir/Projects/cryodaq/docs/design-system/MANIFEST.md:116:- Latin T in channel-ID context appears only in lint-pattern documentation (`testing-strategy.md`) and explicit bad-example counterexamples
/Users/vladimir/Projects/cryodaq/docs/design-system/MANIFEST.md:130:11. **Cyrillic Т (U+0422) in user-facing temperature channel IDs** — never Latin T.
/Users/vladimir/Projects/cryodaq/docs/design-system/MANIFEST.md:170:51. **Subsystem names stay Latin** — Engine, ZMQ, Safety, Keithley. Domain vocabulary exception.
/Users/vladimir/Projects/cryodaq/tests/storage/test_parquet_export.py:104:            (base_ts + 1, "ls218s", "Т8", float("-inf"), "K", "underrange"),
/Users/vladimir/Projects/cryodaq/docs/design-system/governance/deprecation-policy.md:234:- **Cyrillic Т (U+0422)** for channel IDs — domain vocabulary, not a design decision
/Users/vladimir/Projects/cryodaq/docs/design-system/components/badge.md:60:3. **Uppercase Cyrillic has letter-spacing.** Filled status badges use `0.05em` tracking. (RULE-TYPO-005)
/Users/vladimir/Projects/cryodaq/docs/design-system/components/badge.md:319:4. **Cyrillic uppercase without letter-spacing.** "АВАРИЯ" cramps without tracking. RULE-TYPO-005.
/Users/vladimir/Projects/cryodaq/docs/design-system/components/breadcrumb.md:254:6. **Uppercase Cyrillic in crumbs.** Crumbs are sentence case (per RULE-COPY-003) — "Дашборд", not "ДАШБОРД". UPPERCASE is for category labels (tile headers, destructive action buttons), not navigation.
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:13:Typography in CryoDAQ uses **two font families**: Fira Sans (body) and Fira Code (display + mono). Both fully support Cyrillic + Latin + Greek scripts. This is verified against Google Fonts metadata.
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:25:| Token | Value | Use | Cyrillic? | Weights available |
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:27:| `FONT_BODY` | `Fira Sans` | All body text, labels, paragraphs, form inputs | ✅ Full Cyrillic + Cyrillic-ext + Greek | 100-900 regular+italic |
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:29:| `FONT_DISPLAY` | `Fira Code` | Display-size numeric headers, TopWatchBar readouts | ✅ Full Cyrillic + Cyrillic-ext + Greek | 300-700 |
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:30:| `FONT_MONO` | `Fira Code` | Data cells, code snippets, log entries, timestamps | ✅ Full Cyrillic + Cyrillic-ext + Greek | 300-700 |
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:241:## Cyrillic-specific considerations
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:243:Fira Sans and Fira Code both have complete Cyrillic + Cyrillic-Ext coverage.
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:247:1. **Temperature channel identifiers use Cyrillic Т (U+0422)**, never Latin T (U+0054). Enforce in user-facing strings. See `rules/content-voice-rules.md` RULE-COPY-001.
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:248:2. **UPPERCASE Cyrillic labels** (e.g., «ЭКСПЕРИМЕНТ», «АВАР. ОТКЛ.») require `letter-spacing: 0.05em` because Cyrillic uppercase has narrower default tracking than Latin. Without this, letters cram together.
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:249:3. **Russian text is ~15% more vertically dense** than English at same size — Cyrillic glyphs often have tall diacriticals. Increase line-height by 2-3px for multi-line Russian content.
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:254:# DESIGN: RULE-TYPO-005 (Cyrillic uppercase spacing)
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:272:Fallback preserves Cyrillic on all platforms:
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:273:- **Windows**: Segoe UI (Cyrillic ✅)
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:274:- **macOS**: Helvetica Neue (Cyrillic ✅)
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:275:- **Linux**: DejaVu Sans or Liberation Sans (Cyrillic ✅)
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:283:- **Mixed Latin T and Cyrillic Т in same view** — broken encoding, confuses operators
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:296:- `RULE-TYPO-005` — Cyrillic uppercase letter-spacing (`rules/typography-rules.md`)
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md:299:- `RULE-COPY-001` — Cyrillic Т for temperature channels (`rules/content-voice-rules.md`)
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:18:- RULE-COPY-001 — Cyrillic Т (U+0422) for temperature channels
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:29:## RULE-COPY-001: Cyrillic Т (U+0422) for temperature channels
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:31:**TL;DR:** Temperature channel labels use Cyrillic `Т` (U+0422), never Latin `T` (U+0054). Applies to Т1–Т24 channel IDs in user-facing strings.
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:33:**Statement:** All temperature channel identifiers displayed to operators MUST use Cyrillic letter `Т` (U+0422). Latin `T` (U+0054) is visually identical but distinct at code-point level and breaks consistency. Applies to:
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:42:Code-level channel IDs in backend, database, and configuration keys MAY use Latin `T` for ASCII compatibility — this rule applies only to user-facing strings.
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:44:**Rationale:** Russian operator expects Russian text. Mixing Latin `T` with Cyrillic context creates visual jitter. Many fonts render Cyrillic `Т` with different metrics than Latin `T` (especially in monospace at small sizes) — mixing causes subtle layout drift. Code review must catch this because it's easy to type Latin T on Latin keyboard.
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:52:# channels.yaml — Cyrillic Т
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:66:label = QLabel("Т5")  # U+0422 Cyrillic Т
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:71:fault_message = f"Канал Т11 превысил лимит: {value:.2f} K"  # Cyrillic Т
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:77:# Latin T — visually identical, semantically wrong
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:78:label = QLabel("T5")  # U+0054 Latin T — WRONG
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:80:# Mixed Latin / Cyrillic in same string
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:87:# Find Latin T used as channel prefix in user-facing strings
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:92:# Scan yaml configs for user-visible Latin T
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:93:rg -n '\bT[0-9]+' config/channels.yaml
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:99:# Replace Latin T with Cyrillic Т in user-facing YAML strings
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:105:    # Match Latin T followed by digit at start of line / after whitespace
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:110:**Related rules:** RULE-TYPO-002 (Fira fonts include Cyrillic), RULE-COPY-002 (Russian vocabulary)
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:168:**Related rules:** RULE-COPY-001 (Cyrillic Т), RULE-COPY-003 (sentence case)
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:206:log_entry = "датчик т11 восстановил связь"  # WRONG — Cyrillic Т missing + no capital
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:353:# Also config/channels.yaml, dialog text, anything displayed to operator
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:372:5. **Units in Russian where established.** Use `мбар`, `Вт`, `Ом` in operator-facing text; avoid Latin pressure/power/resistance spellings. Kelvin stays `K` (international convention for temperature).
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:593:**Related rules:** RULE-COPY-001 (Cyrillic channel names), RULE-COPY-002 (Russian vocabulary), RULE-COPY-007 (imperative/descriptive).
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/content-voice-rules.md:599:- 2026-04-17: Initial version. 8 rules covering Cyrillic Т, Russian vocabulary, sentence case, error style, emoji prohibition, SI units, imperative/descriptive, decimal convention. RULE-COPY-004 fills the previously-reserved gap.
/Users/vladimir/Projects/cryodaq/docs/design-system/AUDIT_REPORT_B.md:115:The component-spec layer is structurally usable, and the domain-fact layer is in better shape than the raw traceability layer: I did **not** find the high-cost B5 failures this audit was specifically watching for (wrong `Т11/Т12` metrology claim, Latin `T` in operator-facing examples, uppercase FSM states as normative UI text, or SCPI replacing Keithley TSP). The main problems are elsewhere: several specs point to nonexistent or wrong implementation files, `bento-grid.md` no longer describes the actual shipped grid primitive, and one code example (`toast.md`) is not syntactically valid Python. That means the layer is directionally sound but not yet trustworthy as an implementation source of truth without a cleanup pass on traceability and example accuracy.
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/top-watch-bar.md:18:> (Cyrillic), `Т мин` / `Т макс` locked to `Т11` / `Т12` (positionally
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/top-watch-bar.md:146:    def set_pressure(self, mbar: float, status: str = "ok") -> None: ...  # parameter name stays Latin
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/top-watch-bar.md:358:9. **Latin T for channel labels.** "T MIN" with Latin T; should be "Т МИН" with Cyrillic. RULE-COPY-001.
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/top-watch-bar.md:371:- 2026-04-17 (v1.0.1): Fixed `mбар` → `мбар` in pressure invariant (FR-016) — was a typo mixing Latin `m` with Cyrillic `бар`. Code identifier `mbar:` in `set_pressure` API stays Latin (parameter name).
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/information-hierarchy.md:86:Latin-script readers scan content in an F-shape: top-left first, then top-right, then down-left. Place Tier-2 content accordingly:
/Users/vladimir/Projects/cryodaq/docs/design-system/components/dialog.md:84:4. **Action buttons right-aligned.** Cancel first (left), primary action second (right). Latin pattern: destination on right.
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/chart-tokens.md:217:- 2026-04-17 (v1.0.1): Recounted PLOT_* tokens against theme.py — total is 12 (5 color + 1 palette + 3 alpha + 2 line-width + 1 layout). Earlier "9 + 1 = 10" undercounted line-width tokens and conflated the line palette with the color set (FR-019). Switched the operator-facing axis-label example from the Latin pressure-unit spelling to `мбар` (FR-016).
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/phase-stepper.md:93:9. **Cyrillic labels only.** Phase names are Russian: «Готов», «Охлаждение», «Захолаживание», «Измерение», «Отогрев», «Завершение». (RULE-COPY-001, RULE-COPY-002)
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/phase-stepper.md:199:            # DESIGN: RULE-TYPO-005 (Cyrillic letter-spacing), RULE-TYPO-008 (UPPERCASE for active)
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/phase-stepper.md:410:7. **Latin phase keys in operator-facing labels.** `"cooldown"` shown to operator; should be `«Захолаживание»`. Keys stay internal, labels are Russian.
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/data-display-rules.md:340:SI mandatory: K (not Kelvin or °K), мбар (avoid Latin pressure-unit spelling in operator-facing text per RULE-COPY-006), V, A, W, Ω (not Ohm).
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/governance-rules.md:60:- What cannot be deprecated (Cyrillic Т, SI units, WCAG AA commitment, persistence-first, TSP-not-SCPI)
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/keithley-panel.md:18:> (Cyrillic А per RULE-COPY-002), per-channel P target / V compliance /
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/keithley-panel.md:133:12. **Labels «Канал А» / «Канал B», not «smua» / «smub» in operator-facing UI.** Those identifiers are internal. Cyrillic А (U+0410), Latin B. (RULE-COPY-002.)
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/keithley-panel.md:212:5. **Using «smua» / «smub» as operator labels.** Those are TSP identifiers. Operator sees «Канал А» / «Канал B». RULE-COPY-002. Cyrillic А (U+0410), not Latin A.
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/numeric-formatting.md:22:| **Temperature** | `{:.2f}` | K (Cyrillic К also valid, prefer Latin K for SI) | `4.21 K`, `77.30 K`, `350.00 K` |
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/typography-rules.md:22:- RULE-TYPO-005 — Cyrillic uppercase requires positive letter-spacing
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/typography-rules.md:261:## RULE-TYPO-005: Cyrillic uppercase requires positive letter-spacing
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/typography-rules.md:263:**TL;DR:** UPPERCASE Cyrillic labels ("АВАР. ОТКЛ.", "ЭКСПЕРИМЕНТ") need `letter-spacing: 0.05em` because default Cyrillic uppercase tracks narrower than Latin. Without this, letters visually cram together.
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/typography-rules.md:265:**Statement:** When rendering Russian uppercase labels at any size, widget font MUST apply positive letter-spacing. Fira Sans (and most fonts) are optimized for Latin uppercase tracking; Cyrillic uppercase glyphs are on average 5-10% narrower, causing visual cramping when tracked at zero.
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/typography-rules.md:269:**Rationale:** Typography is tuned for Latin. Cyrillic has denser glyph structure. Without explicit tracking, an uppercase label like "АВАР. ОТКЛ." renders as "АВАРОТКЛ"-like visual blob. Latin equivalent "EMERG. STOP." looks fine at same tracking due to wider Latin letterforms.
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/typography-rules.md:271:**Applies to:** any widget displaying uppercase Cyrillic text at any size, especially headers, buttons, status labels
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/typography-rules.md:277:# Destructive button with Cyrillic uppercase label
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/typography-rules.md:306:# No letter-spacing — Cyrillic uppercase cramps
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/typography-rules.md:314:**Exception:** Lowercase or title-case Cyrillic (e.g., "Эксперимент", "Захолаживание") does NOT need explicit letter-spacing. Default tracking is optimized for mixed-case Cyrillic. Rule applies only to UPPERCASE.
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/typography-rules.md:429:**Statement:** UPPERCASE Cyrillic usage in CryoDAQ UI follows this convention:
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/typography-rules.md:483:**Related rules:** RULE-TYPO-005 (Cyrillic uppercase letter-spacing), RULE-COPY-003 (Russian UI text style)
/Users/vladimir/Projects/cryodaq/docs/design-system/rules/typography-rules.md:596:- 2026-04-17: Initial version. 10 rules covering preset preference, font loading, tnum/liga features, Cyrillic typography, weight minimums, off-scale size protection, uppercase convention, line-height ratios, text color pairing.
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/sensor-cell.md:13:Smallest atom of the sensor grid. Displays one channel: channel ID (Cyrillic Т#) + current value + unit + state-aware color. Appears in grids of many at once (DynamicSensorGrid with 24 channels, typical 14 visible).
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/sensor-cell.md:30:│  Т11                  │ ◀── channel ID (Cyrillic Т)
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/sensor-cell.md:49:| **Channel ID** | Yes | «Т1», «Т11», «Т24» — Cyrillic letter always |
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/sensor-cell.md:56:1. **Channel ID uses Cyrillic Т (U+0422).** Never Latin T. (RULE-COPY-001)
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/sensor-cell.md:91:    channel_id: str        # "Т11" (Cyrillic)
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/sensor-cell.md:141:        # DESIGN: RULE-COPY-001 — Cyrillic Т
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/sensor-cell.md:277:  `ChannelManager.get_all_visible()` whose id starts with Cyrillic Т
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/sensor-cell.md:278:  (U+0422) are rendered; hidden channels (channels.yaml `visible: false`)
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/sensor-cell.md:316:1. **Latin T in channel ID.** `QLabel("T11")` with Latin T. Should be Cyrillic `"Т11"`. RULE-COPY-001.
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/conductivity-panel.md:76:│  │ ☑ Т4 Рад. 2           │ │ ┌─ R/G Table (11 cols) ──────────┐ │  │
/Users/vladimir/Projects/cryodaq/tests/config/test_alarms_v3_cooldown_stall_threshold.py:6:ALARMS_V3 = Path("config/alarms_v3.yaml")
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/analytics-panel.md:193:  Cyrillic).
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/analytics-panel.md:233:Cyrillic мбар axis, log-Y per RULE-DATA-008) is tracked as a separate
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/analytics-panel.md:269:4. **Cyrillic where user-facing** (RULE-COPY-001, RULE-COPY-006):
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/analytics-panel.md:271:   «R_thermal» in labels. Latin identifiers in code.
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/analytics-panel.md:401:- RULE-COPY-001 — Cyrillic Т for channel IDs
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/copy-voice.md:120:## Subsystem names (keep in Latin)
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/copy-voice.md:122:These are kept in Latin because they're either brand names, library names, or globally-recognized technical identifiers:
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/copy-voice.md:158:## Channel IDs (Cyrillic Т)
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/copy-voice.md:160:Always Cyrillic Т (U+0422) in channel identifiers shown to the operator:
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/copy-voice.md:162:- «Т1», «Т11», «Т24» (not Latin «T11»)
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/copy-voice.md:165:Latin T in channel IDs is a specific violation per RULE-COPY-001.
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/copy-voice.md:255:Prefer Russian unit abbreviations over Latin:
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/copy-voice.md:257:- **K** (Kelvin) — Latin K is international SI; «К» Cyrillic also valid. Pick one and use consistently. Recommend Latin K for SI alignment.
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/copy-voice.md:284:- Mixed Cyrillic/Latin when one or the other would suffice
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/copy-voice.md:308:- **RULE-COPY-001** — Cyrillic Т for channel IDs
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/copy-voice.md:309:- **RULE-COPY-002** — subsystem names in Latin exception
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/copy-voice.md:316:- **RULE-TYPO-005** — Cyrillic uppercase letter-spacing
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/copy-voice.md:327:4. **English subsystem labels translated to Russian.** «Движок: подключён» — «Engine» is the subsystem name, keep Latin.
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/copy-voice.md:339:10. **Latin T in channel ID.** «T11» with Latin T. Must be Cyrillic Т11.
/Users/vladimir/Projects/cryodaq/docs/design-system/patterns/copy-voice.md:356:- 2026-04-17: Initial version. Vocabulary lexicon (canonical forms). Subsystem name Latin exception. FSM state display policy. Error / empty / placeholder / tooltip / log-entry patterns. Pluralization strategies.
/Users/vladimir/Projects/cryodaq/tests/config/test_alarms_v3_interlocks_preserved.py:1:"""Regression: keithley_overpower_interlock must stay in alarms_v3.yaml.
/Users/vladimir/Projects/cryodaq/tests/config/test_alarms_v3_interlocks_preserved.py:11:ALARMS_V3 = Path("config/alarms_v3.yaml")
/Users/vladimir/Projects/cryodaq/docs/design-system/components/button.md:80:10. **Uppercase Cyrillic has letter-spacing.** `АВАР. ОТКЛ.` uses `0.05em` tracking. (RULE-TYPO-005)
/Users/vladimir/Projects/cryodaq/docs/design-system/components/button.md:199:button = QPushButton("АВАР. ОТКЛ.")  # uppercase Cyrillic category label
/Users/vladimir/Projects/cryodaq/docs/design-system/components/button.md:406:9. **Cyrillic uppercase without letter-spacing.** "АВАР. ОТКЛ." cramps without `0.05em` tracking. RULE-TYPO-005.
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/experiment-card.md:20:> channel Т11 / Т12 + pressure in Cyrillic мбар), actions row
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/experiment-card.md:94:6. **Experiment name is operator-assigned freeform text.** May contain Latin chars (calibration_run_042), Cyrillic («Калибровка 2026-04»), or mix. Don't force Cyrillic-only. Apply same RULE-COPY-001 ONLY to channel IDs, not experiment names.
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/experiment-card.md:245:        # DESIGN: RULE-COPY-001 Cyrillic Т, RULE-COPY-006 units
/Users/vladimir/Projects/cryodaq/tests/config/test_housekeeping_patterns.py:1:"""Regression test for C.5: Latin T in housekeeping.yaml include_patterns."""
/Users/vladimir/Projects/cryodaq/tests/config/test_housekeeping_patterns.py:12:    """include_patterns must match real Cyrillic Т channel names."""
/Users/vladimir/Projects/cryodaq/tests/config/test_housekeeping_patterns.py:25:            f"No include pattern matched Cyrillic channel {channel!r}"
/Users/vladimir/Projects/cryodaq/tests/config/test_housekeeping_patterns.py:30:    """Т1-Т8 must NOT be throttled (negative lookahead)."""
/Users/vladimir/Projects/cryodaq/tests/config/test_housekeeping_patterns.py:34:    excluded = ["Т1 Криостат верх", "Т7 Детектор", "Т8 Калибровка"]
/Users/vladimir/Projects/cryodaq/tests/config/test_housekeeping_patterns.py:42:    """Both Cyrillic AND Latin T must match for defense in depth."""
/Users/vladimir/Projects/cryodaq/tests/config/test_housekeeping_patterns.py:47:        "Latin T fallback missing from include_patterns"
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/bottom-status-bar.md:85:**Note on Engine label:** «Engine» stays in Latin — it's the subsystem name, not operator-facing vocabulary (RULE-COPY-002 exception for subsystem names). `safe_off` / `fault_latched` also stay in code form — these are precise FSM state IDs that operators recognize from logs.
/Users/vladimir/Projects/cryodaq/docs/design-system/cryodaq-primitives/bottom-status-bar.md:294:6. **Translating Engine / ZMQ / Safety.** These are subsystem names (domain vocabulary). Stay in Latin. Per RULE-COPY-002 exception.
/Users/vladimir/Projects/cryodaq/tests/test_launcher_theme_menu.py:94:    grep looks for the escape sequence for «Подробные» (Cyrillic П
/Users/vladimir/Projects/cryodaq/tests/core/test_alarm_config.py:21:    p = tmp_path / "alarms_v3.yaml"
/Users/vladimir/Projects/cryodaq/tests/core/test_alarm_config.py:41:channel_groups:
/Users/vladimir/Projects/cryodaq/tests/core/test_alarm_config.py:43:  all_temp: [T1, T2, T11, T12]
/Users/vladimir/Projects/cryodaq/tests/core/test_alarm_config.py:142:    """A.7: missing alarms_v3.yaml must be startup-fatal."""
/Users/vladimir/Projects/cryodaq/tests/core/test_alarm_config.py:148:    """load_alarm_config(None) should find config/alarms_v3.yaml via traversal."""
/Users/vladimir/Projects/cryodaq/tests/core/test_alarm_config.py:178:channel_groups:
/Users/vladimir/Projects/cryodaq/tests/core/test_safety_fixes.py:329:            r = Reading.now(channel="Т4 Радиатор 2", value=temp, unit="K", instrument_id="test")
/Users/vladimir/Projects/cryodaq/tests/core/test_atomic_write.py:44:    """Cyrillic content (Russian operator log) round-trips through utf-8."""
/Users/vladimir/Projects/cryodaq/tests/core/test_sensor_diagnostics.py:534:            "cold": ["\u0422\u0031\u0031", "\u0422\u0031\u0032"],  # Т11, Т12 (Cyrillic)
/Users/vladimir/Projects/cryodaq/tests/core/test_sensor_diagnostics.py:544:    # Push with full runtime names (Cyrillic Т)
/Users/vladimir/Projects/cryodaq/tests/core/test_calibration_acquisition.py:128:        _srdg_reading("Т4", 70.0),  # not a target
/Users/vladimir/Projects/cryodaq/tests/core/test_alarm_v2.py:499:    # Config uses short channel ID (as in alarms_v3.yaml)
/Users/vladimir/Projects/cryodaq/tests/core/test_sqlite_writer.py:371:        channel="Т4 Радиатор 2",
/Users/vladimir/Projects/cryodaq/tests/core/test_sqlite_writer.py:383:    rows = conn.execute("SELECT * FROM readings WHERE channel='Т4 Радиатор 2'").fetchall()
/Users/vladimir/Projects/cryodaq/tests/core/test_housekeeping_alarms_v3.py:1:"""Verify adaptive-throttle reads critical channels from alarms_v3.yaml.
/Users/vladimir/Projects/cryodaq/tests/core/test_housekeeping_alarms_v3.py:16:    load_critical_channels_from_alarms_v3,
/Users/vladimir/Projects/cryodaq/tests/core/test_housekeeping_alarms_v3.py:21:    config = tmp_path / "alarms_v3.yaml"
/Users/vladimir/Projects/cryodaq/tests/core/test_housekeeping_alarms_v3.py:43:    patterns = load_critical_channels_from_alarms_v3(config)
/Users/vladimir/Projects/cryodaq/tests/core/test_housekeeping_alarms_v3.py:49:    config = tmp_path / "alarms_v3.yaml"
/Users/vladimir/Projects/cryodaq/tests/core/test_housekeeping_alarms_v3.py:66:    patterns = load_critical_channels_from_alarms_v3(config)
/Users/vladimir/Projects/cryodaq/tests/core/test_housekeeping_alarms_v3.py:72:    config = tmp_path / "alarms_v3.yaml"
/Users/vladimir/Projects/cryodaq/tests/core/test_housekeeping_alarms_v3.py:93:    patterns = load_critical_channels_from_alarms_v3(config)
/Users/vladimir/Projects/cryodaq/tests/core/test_housekeeping_alarms_v3.py:100:    config = tmp_path / "alarms_v3.yaml"
/Users/vladimir/Projects/cryodaq/tests/core/test_housekeeping_alarms_v3.py:104:                "channel_groups": {
/Users/vladimir/Projects/cryodaq/tests/core/test_housekeeping_alarms_v3.py:106:                    "all_temp": ["Т1", "Т2", "Т3"],
/Users/vladimir/Projects/cryodaq/tests/core/test_housekeeping_alarms_v3.py:110:                        "channel_group": "all_temp",
/Users/vladimir/Projects/cryodaq/tests/core/test_housekeeping_alarms_v3.py:120:    patterns = load_critical_channels_from_alarms_v3(config)
/Users/vladimir/Projects/cryodaq/tests/core/test_housekeeping_alarms_v3.py:127:    config = tmp_path / "alarms_v3.yaml"
/Users/vladimir/Projects/cryodaq/tests/core/test_housekeeping_alarms_v3.py:141:    patterns = load_critical_channels_from_alarms_v3(config)
/Users/vladimir/Projects/cryodaq/tests/core/test_housekeeping_alarms_v3.py:152:    config = tmp_path / "alarms_v3.yaml"
/Users/vladimir/Projects/cryodaq/tests/core/test_housekeeping_alarms_v3.py:180:    patterns = load_critical_channels_from_alarms_v3(config)
/Users/vladimir/Projects/cryodaq/tests/core/test_housekeeping_alarms_v3.py:191:    config = tmp_path / "alarms_v3.yaml"
/Users/vladimir/Projects/cryodaq/tests/core/test_housekeeping_alarms_v3.py:213:    patterns = load_critical_channels_from_alarms_v3(config)
/Users/vladimir/Projects/cryodaq/tests/core/test_housekeeping_alarms_v3.py:219:    config = tmp_path / "alarms_v3.yaml"
/Users/vladimir/Projects/cryodaq/tests/core/test_housekeeping_alarms_v3.py:223:                "channel_groups": {"calibrated": ["Т11"]},
/Users/vladimir/Projects/cryodaq/tests/core/test_housekeeping_alarms_v3.py:236:    patterns = load_critical_channels_from_alarms_v3(config)
/Users/vladimir/Projects/cryodaq/tests/core/test_housekeeping_alarms_v3.py:242:    patterns = load_critical_channels_from_alarms_v3(tmp_path / "nonexistent.yaml")
/Users/vladimir/Projects/cryodaq/tests/core/test_housekeeping_alarms_v3.py:247:    config = tmp_path / "alarms_v3.yaml"
/Users/vladimir/Projects/cryodaq/tests/core/test_housekeeping_alarms_v3.py:251:    patterns = load_critical_channels_from_alarms_v3(config)
/Users/vladimir/Projects/cryodaq/tests/core/test_housekeeping_alarms_v3.py:253:    assert any("alarms_v3" in r.message for r in caplog.records)
/Users/vladimir/Projects/cryodaq/tests/core/test_housekeeping_alarms_v3.py:258:    config = tmp_path / "alarms_v3.yaml"
/Users/vladimir/Projects/cryodaq/tests/core/test_housekeeping_alarms_v3.py:274:    patterns = load_critical_channels_from_alarms_v3(config)
/Users/vladimir/Projects/cryodaq/tests/core/test_housekeeping_alarms_v3.py:278:def test_throttle_protects_alarms_v3_channels(tmp_path):
/Users/vladimir/Projects/cryodaq/tests/core/test_housekeeping_alarms_v3.py:284:    config = tmp_path / "alarms_v3.yaml"
/Users/vladimir/Projects/cryodaq/tests/core/test_housekeeping_alarms_v3.py:300:    patterns = list(load_critical_channels_from_alarms_v3(config))
/Users/vladimir/Projects/cryodaq/tests/core/test_housekeeping_alarms_v3.py:335:    assert len(out_t11) == 1, "Т11 should be protected (alarms_v3 critical) and bypass throttling"
/Users/vladimir/Projects/cryodaq/tests/core/test_interlock.py:396:    # Also verify it does NOT match Latin T12
/Users/vladimir/Projects/cryodaq/tests/core/test_interlock.py:397:    assert not re.fullmatch(pattern, "T12 Something"), "Cyrillic pattern should not match Latin T"
/Users/vladimir/Projects/cryodaq/tests/gui/test_design_system_rules.py:45:# Cyrillic / uppercase-English context before declaring a violation.
/Users/vladimir/Projects/cryodaq/tests/gui/test_design_system_rules.py:96:    Accepts strings with Cyrillic characters (definitionally operator-
/Users/vladimir/Projects/cryodaq/tests/core/test_safety_manager.py:127:        # Now add critical channel pattern and stop feeding
/Users/vladimir/Projects/cryodaq/tests/gui/shell/test_top_watch_bar_persistent_context.py:109:    # Operator-facing unit is Cyrillic "мбар" (RULE-COPY-006).
/Users/vladimir/Projects/cryodaq/tests/gui/shell/test_top_watch_bar_persistent_context.py:110:    # Internal variable / upstream Reading.unit remains Latin "mbar"
/Users/vladimir/Projects/cryodaq/tests/gui/dashboard/test_experiment_card.py:128:    assert "Т11" in text  # Cyrillic Т
/Users/vladimir/Projects/cryodaq/tests/gui/dashboard/test_experiment_card.py:141:    assert "мбар" in text  # Cyrillic
/Users/vladimir/Projects/cryodaq/tests/gui/dashboard/test_experiment_card.py:142:    assert "mbar" not in text  # no Latin bleed
/Users/vladimir/Projects/cryodaq/tests/gui/shell/overlays/test_keithley_panel.py:62:    # «Канал А» — last character must be Cyrillic А (U+0410) not Latin A (U+0041).
/Users/vladimir/Projects/cryodaq/tests/gui/shell/overlays/test_keithley_panel.py:66:    assert ord(panel._smub_block._label_text[-1]) == 0x0042  # Latin B is correct
/Users/vladimir/Projects/cryodaq/tests/gui/shell/overlays/test_operator_log_panel.py:100:    # Title label is the first QLabel with the Cyrillic "ЖУРНАЛ" prefix.

context compacted
codex
I’m going to do the final verification pass against the evidence already gathered, then emit the requested response content here since this session is read-only.
exec
/opt/homebrew/bin/bash -lc "sed -n '1,180p' /Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/b066e4a04761672ce316491d2d62b10ad27a6b15/skills/verification-before-completion/SKILL.md" in /Users/vladimir/Projects/cryodaq
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

codex
I’ve got the audit down to high-signal mismatches. I’m checking the exact quoted line ranges now so the final report can stand on its own without relying on paraphrase.
exec
/opt/homebrew/bin/bash -lc "nl -ba '/Users/vladimir/Vault/CryoDAQ/00 Overview/Architecture overview.md' | sed -n '48,86p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
    48	ancillary, non-overlay surfaces (overview_panel, temp_panel,
    49	pressure_panel, channel_editor, connection_settings, shift_handover,
    50	etc.); `widgets/common.py` is retained for shared helpers.
    51	
    52	**Web (`cryodaq.web.server:app`).** Optional FastAPI surface on
    53	`:8080`. Read-only monitoring. Loopback-only deployment is the
    54	expected pattern (auth deferred to F7 / G.1).
    55	
    56	## Persistence-first ordering
    57	
    58	Hard ordering invariant:
    59	
    60	```text
    61	InstrumentDriver.read_channels()
    62	  → Scheduler
    63	     1. SQLiteWriter.write_immediate()       ← commit first
    64	     2. THEN DataBroker.publish_batch()      ← GUI / web see it
    65	     3. THEN SafetyBroker.publish_batch()    ← safety FSM sees it
    66	```
    67	
    68	> If `DataBroker` has a reading, it has already been written to SQLite.
    69	
    70	This is non-negotiable for post-mortem reconstruction
    71	([[10 Subsystems/Persistence-first]]). It costs ~few-ms GUI latency
    72	per poll; that tradeoff is intentional.
    73	
    74	## ZMQ topology
    75	
    76	- **PUB/SUB :5555** — data plane (msgpack). Always-on stream of
    77	  readings, alarm events, safety state.
    78	- **REP/REQ :5556** — command plane (JSON). Operator commands
    79	  (start experiment, acknowledge fault, request status).
    80	- **Subprocess isolation.** Engine runs ZMQ in a child subprocess
    81	  (`core/zmq_subprocess.py`); the engine main loop is shielded from
    82	  ZMQ crashes.
    83	- **Watchdog** with 60s cooldown after restart — prevents IV.6 restart
    84	  storm ([[30 Investigations/IV.6 cmd plane hardening]]).
    85	- **Transport experiment** `ipc://` (IV.7) is in progress — see
    86	  [[30 Investigations/B1 ZMQ idle-death]] and

exec
/opt/homebrew/bin/bash -lc "nl -ba '/Users/vladimir/Vault/CryoDAQ/00 Overview/Hardware setup.md' | sed -n '38,48p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
    38	The «Т» prefix is **Cyrillic Т (U+0422)**, not Latin T. This homoglyph
    39	caused a real config-evaluation bug; see [[30 Investigations/Cyrillic homoglyph in alarm config]].
    40	
    41	## Per-machine field state (Ubuntu lab PC, 2026-04-20)
    42	
    43	- `Т4 Радиатор 2` is **physically disconnected** — open-circuit reads
    44	  ~380 K. `interlocks.yaml::overheat_cryostat` regex was tightened
    45	  from `Т[1-8] .*` to `Т(1|2|3|5|6|7|8) .*` to exclude it without
    46	  losing coverage on Т1..Т8.
    47	- Thyracont hardware on this PC is actually **VSP206**, not VSP63D —
    48	  uses a different checksum formula. `instruments.local.yaml` carries

exec
/opt/homebrew/bin/bash -lc "nl -ba '/Users/vladimir/Vault/CryoDAQ/30 Investigations/Plugin isolation rebuild.md' | sed -n '80,90p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
    80	- Pipeline: `analytics/plugin_loader.py`.
    81	- Production plugin examples: `analytics/sensor_diagnostics.py`,
    82	  `analytics/vacuum_trend.py`. (Cooldown predictor lives outside
    83	  the plugin pipeline because it needs orchestration with
    84	  `core/cooldown_service.py`.)
    85	- Configuration: `config/plugins.yaml` controls which plugins are
    86	  enabled; `<plugin_id>.yaml` siblings carry plugin-specific config.
    87	
    88	## Lesson
    89	
    90	Engine survival is non-negotiable. Any extension point that lets a

exec
/opt/homebrew/bin/bash -lc "nl -ba '/Users/vladimir/Vault/CryoDAQ/50 Workflow/_index.md' | sed -n '1,24p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	---
     2	source: skeleton stub
     3	last_synced: 2026-04-26
     4	status: index
     5	---
     6	
     7	# 50 Workflow
     8	
     9	Orchestration contract, multi-model consultation skill, overnight swarm
    10	pattern, and the meta-narrative of how prompts evolved.
    11	
    12	- [[50 Workflow/ORCHESTRATION contract]]
    13	- [[50 Workflow/Multi-model consultation]]
    14	- [[50 Workflow/Overnight swarm pattern]]
    15	- [[50 Workflow/Calibration loops history]]
    16	
    17	<!-- TODO: add per-skill digests if more skills land in .claude/skills/ -->

exec
/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py | sed -n '1,12p'" in /Users/vladimir/Projects/cryodaq
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

exec
/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_subprocess.py | sed -n '1,12p;64,80p'" in /Users/vladimir/Projects/cryodaq
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

exec
/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Projects/cryodaq/src/cryodaq/web/server.py | sed -n '1,14p;49,75p;341,379p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	"""Веб-панель удалённого мониторинга CryoDAQ.
     2	
     3	Лёгкий FastAPI-сервер для доступа к данным engine из браузера:
     4	- WebSocket ``/ws`` — поток показаний в реальном времени
     5	- GET ``/status`` — JSON со статусом приборов, тревог, uptime
     6	- GET ``/history`` — JSON с историческими данными из SQLite (последние N минут)
     7	- GET ``/`` — статическая HTML-страница (single-page dashboard)
     8	
     9	Запуск::
    10	
    11	    uvicorn cryodaq.web.server:app --host 0.0.0.0 --port 8080
    12	
    13	Или программно::
    14	
    49	# ---------------------------------------------------------------------------
    50	# Standalone ZMQ command client (no GUI dependency)
    51	# ---------------------------------------------------------------------------
    52	
    53	_CMD_ADDR = "tcp://127.0.0.1:5556"  # REP port = PUB + 1
    54	
    55	
    56	def _send_engine_command(cmd: dict) -> dict:
    57	    """Send a command to the engine via ZMQ REQ/REP. Thread-safe per call."""
    58	    ctx = zmq.Context.instance()
    59	    sock = ctx.socket(zmq.REQ)
    60	    sock.setsockopt(zmq.RCVTIMEO, 5000)
    61	    sock.setsockopt(zmq.SNDTIMEO, 5000)
    62	    sock.setsockopt(zmq.LINGER, 0)
    63	    try:
    64	        sock.connect(_CMD_ADDR)
    65	        sock.send_json(cmd)
    66	        return sock.recv_json()
    67	    except zmq.ZMQError:
    68	        return {"ok": False, "error": "Engine не отвечает"}
    69	    finally:
    70	        sock.close()
    71	
    72	
    73	async def _async_engine_command(cmd: dict) -> dict:
    74	    """Non-blocking engine command via thread pool."""
    75	    return await asyncio.to_thread(_send_engine_command, cmd)
   341	    @application.get("/api/status")
   342	    async def api_status() -> dict[str, Any]:
   343	        """Полный JSON-статус: readings + experiment + shift."""
   344	        base = _state.status_json()
   345	        base["readings"] = _state.last_readings
   346	        # Safety status via engine command
   347	        try:
   348	            safety = await _async_engine_command({"cmd": "safety_status"})
   349	            base["safety"] = safety if safety.get("ok") else None
   350	            if safety.get("ok"):
   351	                _state.safety_state = safety.get("state", "unknown")
   352	        except Exception:
   353	            base["safety"] = None
   354	        # Alarm status via engine command
   355	        try:
   356	            alarms = await _async_engine_command({"cmd": "alarm_v2_status"})
   357	            if alarms.get("ok"):
   358	                base["active_alarms"] = alarms.get("active", {})
   359	                _state.active_alarms = alarms.get("active", {})
   360	        except Exception:
   361	            pass
   362	        # Experiment/shift data via ZMQ command
   363	        try:
   364	            exp = await _async_engine_command({"cmd": "experiment_status"})
   365	            base["experiment"] = exp if exp.get("ok") else None
   366	        except Exception:
   367	            base["experiment"] = None
   368	        return base
   369	
   370	    @application.get("/api/log")
   371	    async def api_log(limit: int = 10) -> dict[str, Any]:
   372	        """Последние записи журнала."""
   373	        try:
   374	            result = await _async_engine_command({"cmd": "log_get", "limit": limit})
   375	            if result.get("ok"):
   376	                return {"ok": True, "entries": result.get("entries", [])}
   377	        except Exception:
   378	            pass
   379	        return {"ok": False, "entries": []}

exec
/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md | sed -n '204,212p;248,254p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   204	- **Phase 2e parallel track** (перенесено из Phase 2d Block C-2):
   205	  - K.1 — requirements-lock.txt hash verification в build path
   206	  - K.2 — `post_build.py` копирует plugin YAML sidecars
   207	  - J.1 — runtime root вне bundle directory (writable state separation)
   208	  - H.1 — runtime plugin loading trust boundary
   209	  - G.1 — web dashboard auth или loopback-only default
   210	  - G.2 — web history/log query size bounds
   211	  - F.1 — Telegram bot persist `last_update_id`, discard backlog on restart
   212	  - C.1 config-audit — `.local.yaml` merge вместо replace
   248	pip install -e ".[dev,web]"    # runtime + dev + web extras
   249	cryodaq                        # operator launcher
   250	cryodaq-engine --mock          # mock engine
   251	cryodaq-gui                    # GUI only (нуждается в engine на ZMQ)
   252	uvicorn cryodaq.web.server:app --host 0.0.0.0 --port 8080
   253	pytest                         # 1 087 passed, 2 skipped
   254	pytest tests/ --cov=src/cryodaq --cov-report=term   # 66% покрытие

exec
/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Projects/cryodaq/config/interlocks.yaml | sed -n '17,24p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
    17	  # ─── Температурные блокировки криостата (каналы Т1–Т8) ──────────────────────
    18	  - name: "overheat_cryostat"
    19	    description: "Перегрев криостата — аварийное отключение нагревателя"
    20	    channel_pattern: "Т[1-8] .*"
    21	    threshold: 350.0
    22	    comparison: ">"
    23	    action: "emergency_off"
    24	    cooldown_s: 10.0

exec
/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Projects/cryodaq/config/alarms_v3.yaml | sed -n '30,36p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
    30	channel_groups:
    31	  calibrated:    [Т11, Т12]
    32	  # Т4 (Радиатор 2), Т8 (Калибровка) — отключённые датчики, исключены
    33	  uncalibrated:  [Т1, Т2, Т3, Т5, Т6, Т7, Т9, Т10,
    34	                  Т13, Т14, Т15, Т16, Т17, Т18, Т19, Т20]
    35	  all_temp:      [Т1, Т2, Т3, Т5, Т6, Т7, Т9, Т10,
    36	                  Т11, Т12, Т13, Т14, Т15, Т16, Т17, Т18, Т19, Т20]

exec
/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/plugin_loader.py | sed -n '75,90p;180,185p'" in /Users/vladimir/Projects/cryodaq
exec
/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Projects/cryodaq/config/plugins.yaml | sed -n '1,40p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
    75	    async def start(self) -> None:
    76	        """Запустить пайплайн.
    77	
    78	        Подписывается на брокер, загружает все плагины из ``plugins_dir``,
    79	        затем запускает фоновые задачи обработки и слежения за файлами.
    80	        """
    81	        if self._running:
    82	            logger.warning("Пайплайн уже запущен — повторный вызов start() проигнорирован")
    83	            return
    84	
    85	        self._queue = await self._broker.subscribe(_SUBSCRIBE_NAME)
    86	        logger.info("Пайплайн подписан на брокер как '%s'", _SUBSCRIBE_NAME)
    87	
    88	        self._plugins_dir.mkdir(parents=True, exist_ok=True)
    89	        for path in sorted(self._plugins_dir.glob("*.py")):
    90	            self._load_plugin(path)
   180	            config_path = path.with_suffix(".yaml")
   181	            if config_path.exists():
   182	                try:
   183	                    with config_path.open("r", encoding="utf-8") as fh:
   184	                        config: dict[str, Any] = yaml.safe_load(fh) or {}
   185	                    plugin.configure(config)

 succeeded in 0ms:
     1	sensor_diagnostics:
     2	  enabled: true
     3	  update_interval_s: 10
     4	  noise_window_s: 120
     5	  drift_window_s: 600
     6	  outlier_window_s: 300
     7	  correlation_window_s: 600
     8	  min_points: 10
     9	  thresholds:
    10	    noise_cold_K: 0.02        # T < 30K (DT-670 high sensitivity zone)
    11	    noise_mid1_K: 0.05        # 30-100K
    12	    noise_mid2_K: 0.1         # 100-200K
    13	    noise_warm_K: 0.2         # T > 200K
    14	    drift_K_per_min: 0.1      # absolute drift threshold
    15	    outlier_sigma: 5.0        # outlier = deviation > 5σ from median
    16	    correlation_min: 0.8      # flag uncorrelated below this
    17	    health_warning: 50
    18	    health_critical: 30
    19	  correlation_groups:
    20	    shield:    [Т1, Т2, Т3, Т4, Т5, Т6, Т7, Т8]
    21	    cold:      [Т9, Т10, Т11, Т12, Т13, Т14]
    22	    periphery: [Т15, Т16, Т17, Т18, Т19, Т20]
    23	
    24	vacuum_trend:
    25	  enabled: true
    26	  window_s: 3600                           # data window for fitting (s)
    27	  update_interval_s: 30                    # refit interval (s)
    28	  min_points: 60                           # minimum points for fit
    29	  min_points_combined: 200                 # minimum for 5-param combined model
    30	  targets_mbar:
    31	    - 1.0e-4
    32	    - 1.0e-5
    33	    - 1.0e-6
    34	  anomaly_threshold_sigma: 3.0
    35	  rising_sustained_s: 60                   # sustained rise before "rising" flag
    36	  trend_threshold_log10_per_s: 1.0e-4     # d(log₁₀P)/dt threshold
    37	  extrapolation_horizon_factor: 2.0       # extrapolate 2× window ahead
    38	  pressure_channel: ""                     # auto-detect any mbar-unit reading

exec
/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Projects/cryodaq/.claude/skills/cryodaq-team-lead.md | sed -n '1,24p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	---
     2	name: cryodaq-team-lead
     3	description: "Orchestrate Claude Code agent teams for CryoDAQ — a LabVIEW replacement for cryogenic lab instrumentation (АКЦ ФИАН, Millimetron). Master-track scope: engine, drivers, storage, analytics, reporting, web, notifications, core, safety, configs, build, tests. GUI excluded (owned by feat/ui-phase-1). Safety-critical: 6-state SafetyManager FSM, fail-on-silence, crash-safe SQLite WAL. 3 instrument types (5 instances), 24 temperature channels."
     4	---
     5	
     6	# Team Lead — CryoDAQ (master track)
     7	
     8	You are the team lead for CryoDAQ on the **master** branch. You NEVER implement code, touch files, or run commands directly. You analyze tasks, compose teams, spawn teammates with role-specific prompts, coordinate, and synthesize.
     9	
    10	## Prerequisites
    11	
    12	1. Verify `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` is set.
    13	2. Remind user to enable **delegate mode** (`Shift+Tab`).
    14	
    15	## Branch ownership
    16	
    17	| Branch | Owns | Does NOT touch |
    18	|---|---|---|
    19	| `master` | engine, drivers, storage, analytics, reporting, web, notifications, core, safety, configs, build, tests | `src/cryodaq/gui/` |
    20	| `feat/ui-phase-1` | `src/cryodaq/gui/`, `tests/gui/` | engine internals |
    21	
    22	**This skill is for master-track agents only.** GUI lives in `src/cryodaq/gui/` and is owned by the `feat/ui-phase-1` branch. Master-track agents do not read or modify GUI files.
    23	
    24	## Project context

exec
/opt/homebrew/bin/bash -lc "rg -n \"cryodaq-team-lead|Team Lead|delegate mode|EXPERIMENTAL_AGENT_TEAMS|agent teams\" /Users/vladimir/Vault/CryoDAQ --glob '*.md' --glob '"'!_meta/**'"' --glob '"'!90 Archive/**'"'" in /Users/vladimir/Projects/cryodaq
 exited 1 in 0ms:
codex
## Finding 01
**Severity:** CRITICAL  
**Vault file:** `~/Vault/CryoDAQ/00 Overview/Architecture overview.md`  
**Vault line(s):** 80-82  
**Source file:** `~/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py`; `~/Projects/cryodaq/src/cryodaq/core/zmq_subprocess.py`  
**Source line(s):** `zmq_bridge.py:3-5`; `zmq_subprocess.py:1-7,64-78`  
**Claim in vault:** "Subprocess isolation. Engine runs ZMQ in a child subprocess (`core/zmq_subprocess.py`); the engine main loop is shielded from ZMQ crashes."  
**What source says:** "`ZMQPublisher` — PUB-сокет в engine"; "`ZMQCommandServer` — REP-сокет в engine"; `zmq_subprocess.py` says "The GUI process never imports zmq" and its parameters are "Engine PUB address" / "Engine REP address" with "GUI -> subprocess" command queues.  
**Why this is wrong:** The vault puts `zmq_subprocess.py` on the engine side. Source state is engine PUB/REP sockets in `zmq_bridge.py`, with the subprocess acting as the GUI-side bridge for SUB/REQ isolation.  
**Suggested fix:** Replace with: "Subprocess isolation is GUI-side: the GUI spawns `zmq_bridge_main()` from `core/zmq_subprocess.py`, which owns GUI SUB/REQ sockets so libzmq crashes kill only that subprocess. Engine PUB/REP sockets live in `core/zmq_bridge.py`."

## Finding 02
**Severity:** HIGH  
**Vault file:** `~/Vault/CryoDAQ/00 Overview/Architecture overview.md`  
**Vault line(s):** 52-54  
**Source file:** `~/Projects/cryodaq/src/cryodaq/web/server.py`; `~/Projects/cryodaq/PROJECT_STATUS.md`  
**Source line(s):** `server.py:9-12,49-75,341-379`; `PROJECT_STATUS.md:209-210,252`  
**Claim in vault:** "Web (`cryodaq.web.server:app`). Optional FastAPI surface on `:8080`. Read-only monitoring. Loopback-only deployment is the expected pattern (auth deferred to F7 / G.1)."  
**What source says:** The web server docstring launches with `uvicorn cryodaq.web.server:app --host 0.0.0.0 --port 8080`; `PROJECT_STATUS.md` lists "G.1 — web dashboard auth или loopback-only default" as deferred.  
**Why this is wrong:** The vault implies a loopback-only deployment pattern, but current repo docs expose the server on all interfaces and explicitly defer auth-or-loopback default work. The read-only part is mostly consistent, but the security/deployment caveat is materially overstated.  
**Suggested fix:** Replace with: "Optional FastAPI monitoring surface on `:8080`. Current docs launch uvicorn with `--host 0.0.0.0`; auth or loopback-only default is deferred under G.1, so production exposure remains unresolved."

## Finding 03
**Severity:** CRITICAL  
**Vault file:** `~/Vault/CryoDAQ/00 Overview/Hardware setup.md`  
**Vault line(s):** 43-46  
**Source file:** `~/Projects/cryodaq/config/interlocks.yaml`; `~/Projects/cryodaq/config/alarms_v3.yaml`  
**Source line(s):** `interlocks.yaml:17-24`; `alarms_v3.yaml:30-36`  
**Claim in vault:** "`Т4 Радиатор 2` is **physically disconnected** — open-circuit reads ~380 K. `interlocks.yaml::overheat_cryostat` regex was tightened from `Т[1-8] .*` to `Т(1|2|3|5|6|7|8) .*` to exclude it without losing coverage on Т1..Т8."  
**What source says:** `interlocks.yaml` still has `channel_pattern: "Т[1-8] .*"` for `overheat_cryostat`. `alarms_v3.yaml` excludes Т4/Т8 from alarm channel groups: "# Т4 (Радиатор 2), Т8 (Калибровка) — отключённые датчики, исключены".  
**Why this is wrong:** Current master does not exclude Т4 at the interlock regex level. The exclusion exists in alarm groups, not in `interlocks.yaml`.  
**Suggested fix:** Replace with: "`Т4 Радиатор 2` is physically disconnected — open-circuit reads ~380 K. Current master still has `interlocks.yaml::overheat_cryostat` as `Т[1-8] .*`, so Т4 is not excluded at the interlock regex level; master excludes Т4/Т8 only from `alarms_v3.yaml` channel groups."

## Finding 04
**Severity:** HIGH  
**Vault file:** `~/Vault/CryoDAQ/30 Investigations/Plugin isolation rebuild.md`  
**Vault line(s):** 85-86  
**Source file:** `~/Projects/cryodaq/src/cryodaq/analytics/plugin_loader.py`; `~/Projects/cryodaq/config/plugins.yaml`  
**Source line(s):** `plugin_loader.py:75-90,180-185`; `plugins.yaml:1-38`  
**Claim in vault:** "Configuration: `config/plugins.yaml` controls which plugins are enabled; `<plugin_id>.yaml` siblings carry plugin-specific config."  
**What source says:** `PluginPipeline.start()` "загружает все плагины из `plugins_dir`" and loops over `self._plugins_dir.glob("*.py")`; sibling YAML is loaded via `path.with_suffix(".yaml")`. `config/plugins.yaml` contains `sensor_diagnostics` and `vacuum_trend` settings.  
**Why this is wrong:** For filesystem plugins, `plugin_loader.py` loads every `*.py` in `plugins_dir`; `config/plugins.yaml` is not the enable gate for that pipeline. The claim would make readers believe PluginPipeline loading is centrally gated when it is not.  
**Suggested fix:** Replace with: "Filesystem plugins are loaded from every `*.py` in `plugins_dir`; optional sibling `<plugin_id>.yaml` files configure them. `config/plugins.yaml` controls shipped analytics modules such as `sensor_diagnostics` and `vacuum_trend`, not PluginPipeline loading."

## Finding 05
**Severity:** DEFERRED-COVERAGE  
**Vault file:** `~/Vault/CryoDAQ/50 Workflow/_index.md`  
**Vault line(s):** 9-15; no matching note found  
**Source file:** `~/Projects/cryodaq/.claude/skills/cryodaq-team-lead.md`  
**Source line(s):** 1-23  
**Claim in vault:** "Orchestration contract, multi-model consultation skill, overnight swarm pattern, and the meta-narrative of how prompts evolved." The workflow index lists four notes and has no mention of `cryodaq-team-lead`.  
**What source says:** `.claude/skills/cryodaq-team-lead.md` declares `name: cryodaq-team-lead` and describes a master-track team-lead workflow, prerequisites for `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` and delegate mode, plus branch ownership boundaries.  
**Why this is wrong:** The requested source scope includes `.claude/skills/*.md`; the vault covers `multi-model-consultation` but has zero mention of the second skill. This is total absence, not partial summarization.  
**Suggested fix:** Add a `50 Workflow/CryoDAQ team lead skill.md` digest, or add an index entry explicitly covering the master-track/delegate-mode skill and its GUI exclusion boundary.

## Verdict
- Total findings: 5
- By severity: CRITICAL=2 HIGH=2 MEDIUM=0 LOW=0 DEFERRED=1
- FAIL: the vault contains two direct contradictions against current source state and two material overstatements that would mislead readers.

## Confidence notes
- I did not flag the intentionally deferred Web/Cooldown/Experiment/Interlock subsystem-note coverage gaps; Finding 02 is about an incorrect deployment caveat inside an existing overview note.
- I did not flag the B1 ZMQ note’s older "engine REP works" wording because that same note already includes the post-IV.6 caveat; tightening that section would help, but the source dossier is internally time-phased.
- I did not flag design-system file counts because the repo manifest supports "67 canonical" files even though the directory now contains additional reports/ADRs/follow-up docs.
tokens used
255 636
## Finding 01
**Severity:** CRITICAL  
**Vault file:** `~/Vault/CryoDAQ/00 Overview/Architecture overview.md`  
**Vault line(s):** 80-82  
**Source file:** `~/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py`; `~/Projects/cryodaq/src/cryodaq/core/zmq_subprocess.py`  
**Source line(s):** `zmq_bridge.py:3-5`; `zmq_subprocess.py:1-7,64-78`  
**Claim in vault:** "Subprocess isolation. Engine runs ZMQ in a child subprocess (`core/zmq_subprocess.py`); the engine main loop is shielded from ZMQ crashes."  
**What source says:** "`ZMQPublisher` — PUB-сокет в engine"; "`ZMQCommandServer` — REP-сокет в engine"; `zmq_subprocess.py` says "The GUI process never imports zmq" and its parameters are "Engine PUB address" / "Engine REP address" with "GUI -> subprocess" command queues.  
**Why this is wrong:** The vault puts `zmq_subprocess.py` on the engine side. Source state is engine PUB/REP sockets in `zmq_bridge.py`, with the subprocess acting as the GUI-side bridge for SUB/REQ isolation.  
**Suggested fix:** Replace with: "Subprocess isolation is GUI-side: the GUI spawns `zmq_bridge_main()` from `core/zmq_subprocess.py`, which owns GUI SUB/REQ sockets so libzmq crashes kill only that subprocess. Engine PUB/REP sockets live in `core/zmq_bridge.py`."

## Finding 02
**Severity:** HIGH  
**Vault file:** `~/Vault/CryoDAQ/00 Overview/Architecture overview.md`  
**Vault line(s):** 52-54  
**Source file:** `~/Projects/cryodaq/src/cryodaq/web/server.py`; `~/Projects/cryodaq/PROJECT_STATUS.md`  
**Source line(s):** `server.py:9-12,49-75,341-379`; `PROJECT_STATUS.md:209-210,252`  
**Claim in vault:** "Web (`cryodaq.web.server:app`). Optional FastAPI surface on `:8080`. Read-only monitoring. Loopback-only deployment is the expected pattern (auth deferred to F7 / G.1)."  
**What source says:** The web server docstring launches with `uvicorn cryodaq.web.server:app --host 0.0.0.0 --port 8080`; `PROJECT_STATUS.md` lists "G.1 — web dashboard auth или loopback-only default" as deferred.  
**Why this is wrong:** The vault implies a loopback-only deployment pattern, but current repo docs expose the server on all interfaces and explicitly defer auth-or-loopback default work. The read-only part is mostly consistent, but the security/deployment caveat is materially overstated.  
**Suggested fix:** Replace with: "Optional FastAPI monitoring surface on `:8080`. Current docs launch uvicorn with `--host 0.0.0.0`; auth or loopback-only default is deferred under G.1, so production exposure remains unresolved."

## Finding 03
**Severity:** CRITICAL  
**Vault file:** `~/Vault/CryoDAQ/00 Overview/Hardware setup.md`  
**Vault line(s):** 43-46  
**Source file:** `~/Projects/cryodaq/config/interlocks.yaml`; `~/Projects/cryodaq/config/alarms_v3.yaml`  
**Source line(s):** `interlocks.yaml:17-24`; `alarms_v3.yaml:30-36`  
**Claim in vault:** "`Т4 Радиатор 2` is **physically disconnected** — open-circuit reads ~380 K. `interlocks.yaml::overheat_cryostat` regex was tightened from `Т[1-8] .*` to `Т(1|2|3|5|6|7|8) .*` to exclude it without losing coverage on Т1..Т8."  
**What source says:** `interlocks.yaml` still has `channel_pattern: "Т[1-8] .*"` for `overheat_cryostat`. `alarms_v3.yaml` excludes Т4/Т8 from alarm channel groups: "# Т4 (Радиатор 2), Т8 (Калибровка) — отключённые датчики, исключены".  
**Why this is wrong:** Current master does not exclude Т4 at the interlock regex level. The exclusion exists in alarm groups, not in `interlocks.yaml`.  
**Suggested fix:** Replace with: "`Т4 Радиатор 2` is physically disconnected — open-circuit reads ~380 K. Current master still has `interlocks.yaml::overheat_cryostat` as `Т[1-8] .*`, so Т4 is not excluded at the interlock regex level; master excludes Т4/Т8 only from `alarms_v3.yaml` channel groups."

## Finding 04
**Severity:** HIGH  
**Vault file:** `~/Vault/CryoDAQ/30 Investigations/Plugin isolation rebuild.md`  
**Vault line(s):** 85-86  
**Source file:** `~/Projects/cryodaq/src/cryodaq/analytics/plugin_loader.py`; `~/Projects/cryodaq/config/plugins.yaml`  
**Source line(s):** `plugin_loader.py:75-90,180-185`; `plugins.yaml:1-38`  
**Claim in vault:** "Configuration: `config/plugins.yaml` controls which plugins are enabled; `<plugin_id>.yaml` siblings carry plugin-specific config."  
**What source says:** `PluginPipeline.start()` "загружает все плагины из `plugins_dir`" and loops over `self._plugins_dir.glob("*.py")`; sibling YAML is loaded via `path.with_suffix(".yaml")`. `config/plugins.yaml` contains `sensor_diagnostics` and `vacuum_trend` settings.  
**Why this is wrong:** For filesystem plugins, `plugin_loader.py` loads every `*.py` in `plugins_dir`; `config/plugins.yaml` is not the enable gate for that pipeline. The claim would make readers believe PluginPipeline loading is centrally gated when it is not.  
**Suggested fix:** Replace with: "Filesystem plugins are loaded from every `*.py` in `plugins_dir`; optional sibling `<plugin_id>.yaml` files configure them. `config/plugins.yaml` controls shipped analytics modules such as `sensor_diagnostics` and `vacuum_trend`, not PluginPipeline loading."

## Finding 05
**Severity:** DEFERRED-COVERAGE  
**Vault file:** `~/Vault/CryoDAQ/50 Workflow/_index.md`  
**Vault line(s):** 9-15; no matching note found  
**Source file:** `~/Projects/cryodaq/.claude/skills/cryodaq-team-lead.md`  
**Source line(s):** 1-23  
**Claim in vault:** "Orchestration contract, multi-model consultation skill, overnight swarm pattern, and the meta-narrative of how prompts evolved." The workflow index lists four notes and has no mention of `cryodaq-team-lead`.  
**What source says:** `.claude/skills/cryodaq-team-lead.md` declares `name: cryodaq-team-lead` and describes a master-track team-lead workflow, prerequisites for `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` and delegate mode, plus branch ownership boundaries.  
**Why this is wrong:** The requested source scope includes `.claude/skills/*.md`; the vault covers `multi-model-consultation` but has zero mention of the second skill. This is total absence, not partial summarization.  
**Suggested fix:** Add a `50 Workflow/CryoDAQ team lead skill.md` digest, or add an index entry explicitly covering the master-track/delegate-mode skill and its GUI exclusion boundary.

## Verdict
- Total findings: 5
- By severity: CRITICAL=2 HIGH=2 MEDIUM=0 LOW=0 DEFERRED=1
- FAIL: the vault contains two direct contradictions against current source state and two material overstatements that would mislead readers.

## Confidence notes
- I did not flag the intentionally deferred Web/Cooldown/Experiment/Interlock subsystem-note coverage gaps; Finding 02 is about an incorrect deployment caveat inside an existing overview note.
- I did not flag the B1 ZMQ note’s older "engine REP works" wording because that same note already includes the post-IV.6 caveat; tightening that section would help, but the source dossier is internally time-phased.
- I did not flag design-system file counts because the repo manifest supports "67 canonical" files even though the directory now contains additional reports/ADRs/follow-up docs.
