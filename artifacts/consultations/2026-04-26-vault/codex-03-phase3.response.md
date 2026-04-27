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
session id: 019dcbdb-84df-7261-868a-6e3065739393
--------
user
Model: gpt-5.5
Reasoning effort: high

# Vault audit — Phase 3 (Codex literal verifier)

## Mission

Verify factual accuracy of Phase 3 synthesis pages in
`~/Vault/CryoDAQ/`. Read each note, cross-reference against the
source files declared in note frontmatter. Flag what is wrong.

You are the literal verifier. Codex's job here is line-by-line
correctness. Gemini's parallel audit covers structural / coherence
issues — DO NOT duplicate that.

Phase 3 is the synthesis layer — these notes interpret repo content,
not just mirror it. Synthesis vs strict-mirror tension exists by
design (vault is digest, not duplicate). Only flag things that are
wrong, not things that you would have phrased differently.

## Notes to audit (22 files in `~/Vault/CryoDAQ/`)

Subsystems:
- `10 Subsystems/Safety FSM.md`
- `10 Subsystems/ZMQ bridge.md`
- `10 Subsystems/Persistence-first.md`
- `10 Subsystems/Calibration v2.md`
- `10 Subsystems/Alarm engine v2.md`
- `10 Subsystems/Plugin architecture.md`

Drivers:
- `20 Drivers/LakeShore 218S.md`
- `20 Drivers/Keithley 2604B.md`
- `20 Drivers/Thyracont VSP63D.md`

Investigations:
- `30 Investigations/B1 ZMQ idle-death.md`
- `30 Investigations/b2b4fb5 hardening race.md`
- `30 Investigations/Cyrillic homoglyph in alarm config.md`
- `30 Investigations/Codex H2 wrong hypothesis.md`
- `30 Investigations/Plugin isolation rebuild.md`
- `30 Investigations/IV.6 cmd plane hardening.md`

ADRs (synthesized):
- `40 Decisions/ADR-001 Persistence-first invariant.md`
- `40 Decisions/ADR-002 R1 bounded-backoff probe retry.md`
- `40 Decisions/ADR-003 Plugin isolation via ABC.md`

Workflow:
- `50 Workflow/ORCHESTRATION contract.md`
- `50 Workflow/Multi-model consultation.md`
- `50 Workflow/Overnight swarm pattern.md`
- `50 Workflow/Calibration loops history.md`

## Source files for verification (in `~/Projects/cryodaq/`)

- `CLAUDE.md`, `README.md`, `PROJECT_STATUS.md`, `ROADMAP.md`,
  `CHANGELOG.md`
- `docs/ORCHESTRATION.md`
- `docs/bug_B1_zmq_idle_death_handoff.md`
- `docs/decisions/2026-04-23-cleanup-baseline.md`
- `docs/decisions/2026-04-24-b2b4fb5-investigation.md`
- `docs/decisions/2026-04-24-d1-d4a-execution.md`
- `docs/decisions/2026-04-24-overnight-swarm-launch.md`
- `.claude/skills/multi-model-consultation.md`
- `CC_PROMPT_OVERNIGHT_SWARM_2026-04-24.md`
- `src/cryodaq/core/safety_manager.py`
- `src/cryodaq/core/zmq_bridge.py`, `core/zmq_subprocess.py`
- `src/cryodaq/core/scheduler.py`
- `src/cryodaq/core/alarm_v2.py`, `core/alarm_config.py`
- `src/cryodaq/analytics/base_plugin.py`,
  `analytics/plugin_loader.py`
- `src/cryodaq/analytics/calibration.py`,
  `analytics/calibration_fitter.py`,
  `core/calibration_acquisition.py`
- `src/cryodaq/drivers/instruments/*.py`

## What to flag (CRITICAL / HIGH / MEDIUM / LOW)

- **CRITICAL** — claim contradicts source code or repo doc
  (homoglyph-class, wrong commit SHA, wrong invariant statement,
  wrong API name or signature, "X is required" when source says
  "X is optional", etc.).
- **HIGH** — claim is overstatement vs what source supports.
- **MEDIUM** — claim is true but missing an important caveat that
  source explicitly attaches.
- **LOW** — minor wording drift.

## What NOT to flag

- Stylistic preferences.
- Information density (Phase 3 notes are digest by design).
- Structural choices (where to put a section, whether two notes
  should merge — Gemini's domain).
- "I would have written this differently".
- Forward references to Phase 4 / 5 notes that don't exist yet
  (Phase 4 sweeps broken links).

## Output

Per finding (one bullet each):
- severity / vault file:line / source file:line / proposed fix
- Verdict at end: PASS / FAIL / CONDITIONAL
- Cap: 4000 words.

## Response file

Stdout will be redirected to:
`~/Projects/cryodaq/artifacts/consultations/2026-04-26-vault/codex-03-phase3.response.md`

If your sandbox is read-only, do NOT attempt to write the file
yourself; just emit your full response to stdout (canonical content
in markdown) and the wrapper captures it.

codex
I’ll use the Superpowers startup workflow to satisfy the session rule, then audit strictly against the declared sources. The filesystem is read-only, so I’ll only inspect files and return the markdown report.
exec
/opt/homebrew/bin/bash -lc "sed -n '1,220p' /Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/b066e4a04761672ce316491d2d62b10ad27a6b15/skills/using-superpowers/SKILL.md && pwd && rg --files /Users/vladimir/Vault/CryoDAQ /Users/vladimir/Projects/cryodaq | sed -n '1,220p'" in /Users/vladimir/Projects/cryodaq
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
/Users/vladimir/Projects/cryodaq
/Users/vladimir/Vault/CryoDAQ/50 Workflow/_index.md
/Users/vladimir/Vault/CryoDAQ/50 Workflow/ORCHESTRATION contract.md
/Users/vladimir/Vault/CryoDAQ/50 Workflow/Overnight swarm pattern.md
/Users/vladimir/Vault/CryoDAQ/50 Workflow/Calibration loops history.md
/Users/vladimir/Vault/CryoDAQ/50 Workflow/Multi-model consultation.md
/Users/vladimir/Vault/CryoDAQ/60 Roadmap/_index.md
/Users/vladimir/Vault/CryoDAQ/60 Roadmap/F-table backlog.md
/Users/vladimir/Vault/CryoDAQ/60 Roadmap/Versions.md
/Users/vladimir/Vault/CryoDAQ/40 Decisions/_index.md
/Users/vladimir/Vault/CryoDAQ/40 Decisions/2026-04-24-d1-d4a-execution.md
/Users/vladimir/Vault/CryoDAQ/40 Decisions/2026-04-24-b2b4fb5-investigation.md
/Users/vladimir/Vault/CryoDAQ/40 Decisions/ADR-001 Persistence-first invariant.md
/Users/vladimir/Vault/CryoDAQ/40 Decisions/2026-04-23-cleanup-baseline.md
/Users/vladimir/Vault/CryoDAQ/40 Decisions/2026-04-24-overnight-swarm-launch.md
/Users/vladimir/Vault/CryoDAQ/40 Decisions/ADR-003 Plugin isolation via ABC.md
/Users/vladimir/Vault/CryoDAQ/40 Decisions/ADR-002 R1 bounded-backoff probe retry.md
/Users/vladimir/Vault/CryoDAQ/README.md
/Users/vladimir/Vault/CryoDAQ/_meta/_index.md
/Users/vladimir/Vault/CryoDAQ/_meta/build log.md
/Users/vladimir/Vault/CryoDAQ/_meta/glossary.md
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/_index.md
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/Safety FSM.md
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/Calibration v2.md
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/ZMQ bridge.md
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/Plugin architecture.md
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/Alarm engine v2.md
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/Persistence-first.md
/Users/vladimir/Vault/CryoDAQ/00 Overview/_index.md
/Users/vladimir/Vault/CryoDAQ/00 Overview/Architecture overview.md
/Users/vladimir/Vault/CryoDAQ/00 Overview/Hardware setup.md
/Users/vladimir/Vault/CryoDAQ/00 Overview/What is CryoDAQ.md
/Users/vladimir/Vault/CryoDAQ/30 Investigations/_index.md
/Users/vladimir/Vault/CryoDAQ/30 Investigations/Cyrillic homoglyph in alarm config.md
/Users/vladimir/Vault/CryoDAQ/30 Investigations/Plugin isolation rebuild.md
/Users/vladimir/Vault/CryoDAQ/30 Investigations/b2b4fb5 hardening race.md
/Users/vladimir/Vault/CryoDAQ/30 Investigations/B1 ZMQ idle-death.md
/Users/vladimir/Vault/CryoDAQ/30 Investigations/IV.6 cmd plane hardening.md
/Users/vladimir/Vault/CryoDAQ/30 Investigations/Codex H2 wrong hypothesis.md
/Users/vladimir/Vault/CryoDAQ/90 Archive/_index.md
/Users/vladimir/Vault/CryoDAQ/20 Drivers/_index.md
/Users/vladimir/Vault/CryoDAQ/20 Drivers/Thyracont VSP63D.md
/Users/vladimir/Vault/CryoDAQ/20 Drivers/LakeShore 218S.md
/Users/vladimir/Vault/CryoDAQ/20 Drivers/Keithley 2604B.md
/Users/vladimir/Projects/cryodaq/README.md
/Users/vladimir/Projects/cryodaq/install.bat
/Users/vladimir/Projects/cryodaq/package.json
/Users/vladimir/Projects/cryodaq/create_shortcut.py
/Users/vladimir/Projects/cryodaq/package-lock.json
/Users/vladimir/Projects/cryodaq/CC_PROMPT_IV_7_IPC_TRANSPORT.md
/Users/vladimir/Projects/cryodaq/ROADMAP.md
/Users/vladimir/Projects/cryodaq/CC_PROMPT_IV_6_ZMQ_BRIDGE_FIX.md
/Users/vladimir/Projects/cryodaq/THIRD_PARTY_NOTICES.md
/Users/vladimir/Projects/cryodaq/CC_PROMPT_IV_2_ORCHESTRATOR.md
/Users/vladimir/Projects/cryodaq/RELEASE_CHECKLIST.md
/Users/vladimir/Projects/cryodaq/tsp/p_const.lua
/Users/vladimir/Projects/cryodaq/docs/alarms_tuning_guide.md
/Users/vladimir/Projects/cryodaq/docs/CODEX_SELF_REVIEW_PLAYBOOK.md
/Users/vladimir/Projects/cryodaq/config/cooldown.yaml
/Users/vladimir/Projects/cryodaq/config/interlocks.yaml
/Users/vladimir/Projects/cryodaq/config/alarms.yaml
/Users/vladimir/Projects/cryodaq/src/cryodaq/logging_setup.py
/Users/vladimir/Projects/cryodaq/tests/analytics/test_cooldown_predictor.py
/Users/vladimir/Projects/cryodaq/tests/analytics/test_calibration_fitter.py
/Users/vladimir/Projects/cryodaq/tests/analytics/test_calibration.py
/Users/vladimir/Projects/cryodaq/tests/analytics/test_cooldown_service.py
/Users/vladimir/Projects/cryodaq/tests/analytics/test_vacuum_trend.py
/Users/vladimir/Projects/cryodaq/tests/analytics/__init__.py
/Users/vladimir/Projects/cryodaq/tests/analytics/test_thermal.py
/Users/vladimir/Projects/cryodaq/tests/analytics/test_plugins.py
/Users/vladimir/Projects/cryodaq/tests/analytics/test_phase_detector.py
/Users/vladimir/Projects/cryodaq/tests/analytics/conftest.py
/Users/vladimir/Projects/cryodaq/tests/analytics/test_cooldown.py
/Users/vladimir/Projects/cryodaq/build_scripts/cryodaq.spec
/Users/vladimir/Projects/cryodaq/build_scripts/build.sh
/Users/vladimir/Projects/cryodaq/build_scripts/build.bat
/Users/vladimir/Projects/cryodaq/build_scripts/post_build.py
/Users/vladimir/Projects/cryodaq/scripts/disable_usb_suspend.ps1
/Users/vladimir/Projects/cryodaq/CC_PROMPT_IV_3_BATCH.md
/Users/vladimir/Projects/cryodaq/CC_PROMPT_IV_4_BATCH.md
/Users/vladimir/Projects/cryodaq/HANDOFF_2026-04-20_GLM.md
/Users/vladimir/Projects/cryodaq/CLAUDE.md
/Users/vladimir/Projects/cryodaq/start.sh
/Users/vladimir/Projects/cryodaq/requirements-lock.txt
/Users/vladimir/Projects/cryodaq/src/cryodaq/engine.py
/Users/vladimir/Projects/cryodaq/start_mock.bat
/Users/vladimir/Projects/cryodaq/DOC_REALITY_MAP.md
/Users/vladimir/Projects/cryodaq/CODEX_ARCHITECTURE_CONTROL_PLANE.md
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration_fitter.py
/Users/vladimir/Projects/cryodaq/config/themes/rose_dusk.yaml
/Users/vladimir/Projects/cryodaq/config/themes/xcode.yaml
/Users/vladimir/Projects/cryodaq/config/themes/gost.yaml
/Users/vladimir/Projects/cryodaq/config/themes/anthropic_mono.yaml
/Users/vladimir/Projects/cryodaq/config/themes/default_cool.yaml
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/calibration.py
/Users/vladimir/Projects/cryodaq/config/themes/ochre_bloom.yaml
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/cooldown_service.py
/Users/vladimir/Projects/cryodaq/config/themes/taupe_quiet.yaml
/Users/vladimir/Projects/cryodaq/config/themes/warm_stone.yaml
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/vacuum_trend.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/base_plugin.py
/Users/vladimir/Projects/cryodaq/config/themes/braun.yaml
/Users/vladimir/Projects/cryodaq/config/themes/signal.yaml
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/__init__.py
/Users/vladimir/Projects/cryodaq/config/themes/instrument.yaml
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/cooldown_predictor.py
/Users/vladimir/Projects/cryodaq/config/themes/amber.yaml
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/steady_state.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/analytics/plugin_loader.py
/Users/vladimir/Projects/cryodaq/config/plugins.yaml
/Users/vladimir/Projects/cryodaq/config/instruments.local.yaml.example
/Users/vladimir/Projects/cryodaq/config/notifications.local.yaml.example
/Users/vladimir/Projects/cryodaq/config/instruments.yaml
/Users/vladimir/Projects/cryodaq/config/housekeeping.yaml
/Users/vladimir/Projects/cryodaq/config/alarms_v3.yaml
/Users/vladimir/Projects/cryodaq/CHANGELOG.md
/Users/vladimir/Projects/cryodaq/LICENSE
/Users/vladimir/Projects/cryodaq/start_mock.sh
/Users/vladimir/Projects/cryodaq/SESSION_DETAIL_2026-04-20.md
/Users/vladimir/Projects/cryodaq/config/analytics_layout.yaml
/Users/vladimir/Projects/cryodaq/docs/design-system/V101_REVIEW_REPORT.md
/Users/vladimir/Projects/cryodaq/config/channels.yaml
/Users/vladimir/Projects/cryodaq/docs/design-system/THEME_FOLLOWUPS.md
/Users/vladimir/Projects/cryodaq/config/shifts.yaml
/Users/vladimir/Projects/cryodaq/config/notifications.yaml
/Users/vladimir/Projects/cryodaq/config/safety.yaml
/Users/vladimir/Projects/cryodaq/tools/diag_zmq_bridge_extended.py
/Users/vladimir/Projects/cryodaq/tools/diag_zmq_bridge.py
/Users/vladimir/Projects/cryodaq/tools/diag_zmq_b1_capture.py
/Users/vladimir/Projects/cryodaq/tools/diag_zmq_idle_hypothesis.py
/Users/vladimir/Projects/cryodaq/tools/diag_zmq_subprocess.py
/Users/vladimir/Projects/cryodaq/tools/theme_previewer.py
/Users/vladimir/Projects/cryodaq/tools/mock_scenario.py
/Users/vladimir/Projects/cryodaq/tools/force_phase.py
/Users/vladimir/Projects/cryodaq/tools/__init__.py
/Users/vladimir/Projects/cryodaq/tools/_zmq_helpers.py
/Users/vladimir/Projects/cryodaq/tools/replay_session.py
/Users/vladimir/Projects/cryodaq/tools/_b1_diagnostics.py
/Users/vladimir/Projects/cryodaq/CC_PROMPT_OVERNIGHT_SWARM_2026-04-24.md
/Users/vladimir/Projects/cryodaq/PROJECT_STATUS.md
/Users/vladimir/Projects/cryodaq/src/cryodaq/paths.py
/Users/vladimir/Projects/cryodaq/tests/notifications/test_telegram_allowlist.py
/Users/vladimir/Projects/cryodaq/tests/notifications/test_secret_str.py
/Users/vladimir/Projects/cryodaq/tests/notifications/__init__.py
/Users/vladimir/Projects/cryodaq/tests/notifications/test_telegram_phase_vocab.py
/Users/vladimir/Projects/cryodaq/tests/notifications/test_telegram.py
/Users/vladimir/Projects/cryodaq/tests/test_launcher_engine_stderr.py
/Users/vladimir/Projects/cryodaq/tests/test_logging_setup.py
/Users/vladimir/Projects/cryodaq/tests/test_zmq_bind_recovery.py
/Users/vladimir/Projects/cryodaq/tests/test_launcher_theme_menu.py
/Users/vladimir/Projects/cryodaq/config/experiment_templates/debug_checkout.yaml
/Users/vladimir/Projects/cryodaq/config/experiment_templates/custom.yaml
/Users/vladimir/Projects/cryodaq/config/experiment_templates/thermal_conductivity.yaml
/Users/vladimir/Projects/cryodaq/config/experiment_templates/calibration.yaml
/Users/vladimir/Projects/cryodaq/config/experiment_templates/cooldown_test.yaml
/Users/vladimir/Projects/cryodaq/tests/test_paths_frozen.py
/Users/vladimir/Projects/cryodaq/tests/__init__.py
/Users/vladimir/Projects/cryodaq/artifacts/handoffs/2026-04-24-d1-review-handoff.md
/Users/vladimir/Projects/cryodaq/artifacts/handoffs/2026-04-23-cc-to-architect.md
/Users/vladimir/Projects/cryodaq/artifacts/handoffs/2026-04-24-cc-to-architect.md
/Users/vladimir/Projects/cryodaq/artifacts/vault-build/0-preflight-ok.md
/Users/vladimir/Projects/cryodaq/artifacts/vault-build/1-skeleton-ok.md
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/sqlite_writer.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/xlsx_export.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/parquet_archive.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/csv_export.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/hdf5_export.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/replay.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/storage/__init__.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/instance_lock.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/notifications/_secrets.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/notifications/escalation.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/notifications/__init__.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/notifications/telegram.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/notifications/telegram_commands.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/notifications/periodic_report.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/__main__.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/launcher.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/py.typed
/Users/vladimir/Projects/cryodaq/tests/web/__init__.py
/Users/vladimir/Projects/cryodaq/tests/web/test_xss_escaping.py
/Users/vladimir/Projects/cryodaq/tests/design_system/__init__.py
/Users/vladimir/Projects/cryodaq/tests/design_system/test_no_internal_versioning_ast.py
/Users/vladimir/Projects/cryodaq/tests/test_instance_lock.py
/Users/vladimir/Projects/cryodaq/tests/test_web_dashboard.py
/Users/vladimir/Projects/cryodaq/tests/test_launcher_backoff.py
/Users/vladimir/Projects/cryodaq/artifacts/versioning/2026-04-24-safe-merge-recon.md
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/rate_estimator.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_subprocess.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/sensor_diagnostics.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/atomic_write.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/broker.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/channel_state.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/alarm_providers.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/channel_manager.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/scheduler.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/smu_channel.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/alarm_config.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/calibration_acquisition.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/event_logger.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/housekeeping.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/zmq_bridge.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/experiment.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/safety_broker.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/__init__.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/alarm.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/safety_manager.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/operator_log.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/phase_labels.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/alarm_v2.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/user_preferences.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/interlock.py
/Users/vladimir/Projects/cryodaq/src/cryodaq/core/disk_monitor.py
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/layout.md
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/icons.md
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/elevation.md
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/typography.md
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/spacing.md
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/colors.md
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/breakpoints.md
/Users/vladimir/Projects/cryodaq/docs/design-system/tokens/keyboard-shortcuts.md

codex
I’ve confirmed the note set and source tree are present. Next I’m going to extract frontmatter/source declarations and read the notes with line numbers so findings can point to exact vault claims.
exec
/opt/homebrew/bin/bash -lc 'rg -n "''^(sources|source_files|source|repo_sources|---|#|##|###|status|created|updated|tags):|''^- .*'"\\.md|"'^- .*'"\\.py|"'^- .*'"\\.yaml|"'^- .*'"\\.yml|"'^- .*'"\\.lua\" /Users/vladimir/Vault/CryoDAQ/{10\\ Subsystems,20\\ Drivers,30\\ Investigations,40\\ Decisions,50\\ Workflow}/*.md" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
/Users/vladimir/Vault/CryoDAQ/20 Drivers/Thyracont VSP63D.md:2:source: src/cryodaq/drivers/instruments/thyracont_vsp63d.py; drivers/transport/serial.py; CLAUDE.md "Драйверы"; CHANGELOG aabd75f validate_checksum; CHANGELOG 2026-04-20 ModemManager
/Users/vladimir/Vault/CryoDAQ/20 Drivers/Thyracont VSP63D.md:4:status: synthesized
/Users/vladimir/Vault/CryoDAQ/20 Drivers/Thyracont VSP63D.md:13:- **Transport:** RS-232 / USB-Serial (`drivers/transport/serial.py`
/Users/vladimir/Vault/CryoDAQ/20 Drivers/Keithley 2604B.md:2:source: src/cryodaq/drivers/instruments/keithley_2604b.py; drivers/transport/usbtmc.py; core/smu_channel.py; CLAUDE.md "Архитектура safety" + "Ключевые правила"; tsp/p_const.lua
/Users/vladimir/Vault/CryoDAQ/20 Drivers/Keithley 2604B.md:4:status: synthesized
/Users/vladimir/Vault/CryoDAQ/20 Drivers/Keithley 2604B.md:15:- **Transport:** USB-TMC (`drivers/transport/usbtmc.py` via PyVISA).
/Users/vladimir/Vault/CryoDAQ/20 Drivers/Keithley 2604B.md:89:- `tsp/p_const.lua` — TSP supervisor draft (Phase 3, hardware-verify)
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/Calibration v2.md:2:source: src/cryodaq/analytics/calibration.py; analytics/calibration_fitter.py; core/calibration_acquisition.py; CLAUDE.md "Снимок сверки"; README.md "Calibration v2"
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/Calibration v2.md:4:status: synthesized
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/Plugin architecture.md:2:source: src/cryodaq/analytics/base_plugin.py; analytics/plugin_loader.py; config/plugins.yaml
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/Plugin architecture.md:4:status: synthesized
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/Plugin architecture.md:66:- Add a new `.py` to `plugins/` → loaded within ~5 s.
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/_index.md:2:source: skeleton stub
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/_index.md:4:status: index
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/Persistence-first.md:2:source: CLAUDE.md persistence section; PROJECT_STATUS.md invariant 2; src/cryodaq/core/scheduler.py; src/cryodaq/storage/sqlite_writer.py
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/Persistence-first.md:4:status: synthesized
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/Persistence-first.md:69:- **Atomic file writes** (`core/atomic_write.py`) for experiment
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/ZMQ bridge.md:2:source: src/cryodaq/core/zmq_bridge.py; src/cryodaq/core/zmq_subprocess.py; docs/bug_B1_zmq_idle_death_handoff.md; CHANGELOG IPC/REP hardening; ROADMAP "Known broken"
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/ZMQ bridge.md:4:status: synthesized
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/Safety FSM.md:2:source: src/cryodaq/core/safety_manager.py; CLAUDE.md "Архитектура safety"; PROJECT_STATUS.md "Аппаратные / рантайм инварианты"; config/safety.yaml
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/Safety FSM.md:4:status: synthesized
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/Safety FSM.md:114:- `safety.yaml` not found at the configured path
/Users/vladimir/Vault/CryoDAQ/20 Drivers/LakeShore 218S.md:2:source: src/cryodaq/drivers/instruments/lakeshore_218s.py; drivers/transport/gpib.py; CLAUDE.md "Драйверы"; config/instruments.yaml
/Users/vladimir/Vault/CryoDAQ/20 Drivers/LakeShore 218S.md:4:status: synthesized
/Users/vladimir/Vault/CryoDAQ/20 Drivers/LakeShore 218S.md:14:- **Transport:** GPIB (`drivers/transport/gpib.py` via PyVISA).
/Users/vladimir/Vault/CryoDAQ/20 Drivers/LakeShore 218S.md:15:- **Default poll interval:** 2.0 s (`config/instruments.yaml`).
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/Alarm engine v2.md:2:source: src/cryodaq/core/alarm_v2.py; core/alarm_config.py; config/alarms_v3.yaml; CHANGELOG.md "alarm_v2.py:252 cooldown_stall"; CLAUDE.md alarm section
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/Alarm engine v2.md:4:status: synthesized
/Users/vladimir/Vault/CryoDAQ/10 Subsystems/Alarm engine v2.md:84:- Config-side: adjust `config/alarms_v3.yaml` to drop the spurious
/Users/vladimir/Vault/CryoDAQ/30 Investigations/b2b4fb5 hardening race.md:2:source: docs/decisions/2026-04-24-b2b4fb5-investigation.md; docs/decisions/2026-04-24-d1-d4a-execution.md; docs/ORCHESTRATION.md §7 hardening rule
/Users/vladimir/Vault/CryoDAQ/30 Investigations/b2b4fb5 hardening race.md:4:status: closed — H3 confirmed, R1 fix shipped
/Users/vladimir/Vault/CryoDAQ/30 Investigations/B1 ZMQ idle-death.md:2:source: docs/bug_B1_zmq_idle_death_handoff.md; ROADMAP.md "Known broken" (B1); CHANGELOG.md (Unreleased Apr 20); decisions docs 2026-04-24
/Users/vladimir/Vault/CryoDAQ/30 Investigations/B1 ZMQ idle-death.md:4:status: synthesized — bug OPEN
/Users/vladimir/Vault/CryoDAQ/30 Investigations/B1 ZMQ idle-death.md:52:- Raw subprocess without `ZmqBridge` wrapping (`diag_zmq_subprocess.py`)
/Users/vladimir/Vault/CryoDAQ/30 Investigations/B1 ZMQ idle-death.md:79:- `tools/diag_zmq_subprocess.py` — subprocess alone, short.
/Users/vladimir/Vault/CryoDAQ/30 Investigations/B1 ZMQ idle-death.md:80:- `tools/diag_zmq_bridge.py` — full ZmqBridge 60 s soak.
/Users/vladimir/Vault/CryoDAQ/30 Investigations/B1 ZMQ idle-death.md:81:- `tools/diag_zmq_bridge_extended.py` — 180 s past-first-failure.
/Users/vladimir/Vault/CryoDAQ/30 Investigations/B1 ZMQ idle-death.md:82:- `tools/diag_zmq_idle_hypothesis.py` — rate-dependence reproducer.
/Users/vladimir/Vault/CryoDAQ/30 Investigations/B1 ZMQ idle-death.md:83:- `tools/diag_zmq_b1_capture.py` — canonical B1 capture CLI
/Users/vladimir/Vault/CryoDAQ/30 Investigations/B1 ZMQ idle-death.md:85:- `tools/_b1_diagnostics.py` — reusable helpers (bridge_snapshot,
/Users/vladimir/Vault/CryoDAQ/30 Investigations/Cyrillic homoglyph in alarm config.md:2:source: PROJECT_STATUS.md "A1 safety audit"; CLAUDE.md "Кодировка файлов"; docs/design-system/ rules; config/alarms_v3.yaml history
/Users/vladimir/Vault/CryoDAQ/30 Investigations/Cyrillic homoglyph in alarm config.md:4:status: closed — regression test in place
/Users/vladimir/Vault/CryoDAQ/30 Investigations/Cyrillic homoglyph in alarm config.md:32:- `config/alarms_v3.yaml` rule channel patterns (this incident).
/Users/vladimir/Vault/CryoDAQ/30 Investigations/Cyrillic homoglyph in alarm config.md:33:- `config/interlocks.yaml::overheat_cryostat::channel_pattern` —
/Users/vladimir/Vault/CryoDAQ/30 Investigations/Cyrillic homoglyph in alarm config.md:57:- **Design system rules** (`docs/design-system/rules/*-rules.md`)
/Users/vladimir/Vault/CryoDAQ/30 Investigations/Cyrillic homoglyph in alarm config.md:60:- **Adversarial second-model review** (`docs/CODEX_SELF_REVIEW_PLAYBOOK.md`)
/Users/vladimir/Vault/CryoDAQ/30 Investigations/_index.md:2:source: skeleton stub
/Users/vladimir/Vault/CryoDAQ/30 Investigations/_index.md:4:status: index
/Users/vladimir/Vault/CryoDAQ/30 Investigations/Codex H2 wrong hypothesis.md:2:source: docs/bug_B1_zmq_idle_death_handoff.md "Codex revised analysis"; CHANGELOG.md `be51a24` IV.6 partial mitigation; ROADMAP.md "IV.6 partial mitigation outcome"
/Users/vladimir/Vault/CryoDAQ/30 Investigations/Codex H2 wrong hypothesis.md:4:status: closed — adversarial review counter-example
/Users/vladimir/Vault/CryoDAQ/40 Decisions/2026-04-24-b2b4fb5-investigation.md:2:source: docs/decisions/2026-04-24-b2b4fb5-investigation.md
/Users/vladimir/Vault/CryoDAQ/40 Decisions/2026-04-24-b2b4fb5-investigation.md:5:status: accepted
/Users/vladimir/Vault/CryoDAQ/40 Decisions/2026-04-23-cleanup-baseline.md:2:source: docs/decisions/2026-04-23-cleanup-baseline.md
/Users/vladimir/Vault/CryoDAQ/40 Decisions/2026-04-23-cleanup-baseline.md:5:status: accepted
/Users/vladimir/Vault/CryoDAQ/40 Decisions/2026-04-23-cleanup-baseline.md:17:- 3 modified tracked files (`CLAUDE.md`, `.gitignore`, `config/channels.yaml`)
/Users/vladimir/Vault/CryoDAQ/40 Decisions/2026-04-23-cleanup-baseline.md:65:- ORCHESTRATION.md §5.4 wording cleanup ("already gitignored" → "enforced invariant").
/Users/vladimir/Vault/CryoDAQ/30 Investigations/IV.6 cmd plane hardening.md:2:source: CHANGELOG.md `be51a24` IV.6 partial mitigation; ROADMAP.md "IV.6 partial mitigation outcome" + "watchdog regression"; docs/bug_B1_zmq_idle_death_handoff.md "Codex revised analysis"
/Users/vladimir/Vault/CryoDAQ/30 Investigations/IV.6 cmd plane hardening.md:4:status: shipped — defense-in-depth, does NOT close B1
/Users/vladimir/Vault/CryoDAQ/30 Investigations/Plugin isolation rebuild.md:2:source: src/cryodaq/analytics/base_plugin.py; analytics/plugin_loader.py history; CLAUDE.md "Аналитика"
/Users/vladimir/Vault/CryoDAQ/30 Investigations/Plugin isolation rebuild.md:4:status: closed — rebuilt with isolation
/Users/vladimir/Vault/CryoDAQ/30 Investigations/Plugin isolation rebuild.md:76:- ABC: `analytics/base_plugin.py`.
/Users/vladimir/Vault/CryoDAQ/30 Investigations/Plugin isolation rebuild.md:77:- Pipeline: `analytics/plugin_loader.py`.
/Users/vladimir/Vault/CryoDAQ/30 Investigations/Plugin isolation rebuild.md:78:- Production plugin examples: `analytics/sensor_diagnostics.py`,
/Users/vladimir/Vault/CryoDAQ/30 Investigations/Plugin isolation rebuild.md:82:- Configuration: `config/plugins.yaml` controls which plugins are
/Users/vladimir/Vault/CryoDAQ/50 Workflow/Multi-model consultation.md:2:source: .claude/skills/multi-model-consultation.md (v post-2026-04-24)
/Users/vladimir/Vault/CryoDAQ/50 Workflow/Multi-model consultation.md:4:status: digest — read full skill for templates and routing detail
/Users/vladimir/Vault/CryoDAQ/20 Drivers/_index.md:2:source: skeleton stub
/Users/vladimir/Vault/CryoDAQ/20 Drivers/_index.md:4:status: index
/Users/vladimir/Vault/CryoDAQ/40 Decisions/ADR-002 R1 bounded-backoff probe retry.md:2:source: synthesized from docs/decisions/2026-04-24-b2b4fb5-investigation.md, docs/decisions/2026-04-24-d1-d4a-execution.md, ORCHESTRATION.md §7
/Users/vladimir/Vault/CryoDAQ/40 Decisions/ADR-002 R1 bounded-backoff probe retry.md:5:status: accepted
/Users/vladimir/Vault/CryoDAQ/50 Workflow/Calibration loops history.md:2:source: docs/decisions/2026-04-23-cleanup-baseline.md; docs/decisions/2026-04-24-*.md; docs/ORCHESTRATION.md §12 + §13; docs/CODEX_SELF_REVIEW_PLAYBOOK.md
/Users/vladimir/Vault/CryoDAQ/50 Workflow/Calibration loops history.md:4:status: synthesized meta-narrative
/Users/vladimir/Vault/CryoDAQ/50 Workflow/Calibration loops history.md:129:- **ORCHESTRATION.md §5.4 wording cleanup** ("already gitignored" →
/Users/vladimir/Vault/CryoDAQ/40 Decisions/ADR-001 Persistence-first invariant.md:2:source: synthesized from CLAUDE.md persistence section, PROJECT_STATUS.md invariants 2/13/14, src/cryodaq/core/scheduler.py, Phase 2d retro
/Users/vladimir/Vault/CryoDAQ/40 Decisions/ADR-001 Persistence-first invariant.md:5:status: accepted
/Users/vladimir/Vault/CryoDAQ/40 Decisions/ADR-001 Persistence-first invariant.md:65:- GUI dashboards must hold local rolling buffers (`channel_buffer.py`)
/Users/vladimir/Vault/CryoDAQ/40 Decisions/2026-04-24-overnight-swarm-launch.md:2:source: docs/decisions/2026-04-24-overnight-swarm-launch.md
/Users/vladimir/Vault/CryoDAQ/40 Decisions/2026-04-24-overnight-swarm-launch.md:5:status: accepted
/Users/vladimir/Vault/CryoDAQ/40 Decisions/2026-04-24-overnight-swarm-launch.md:34:- stdin-fed prompt (`< BRIEF.prompt.md`), stdout `> RESPONSE.response.md 2>&1`
/Users/vladimir/Vault/CryoDAQ/40 Decisions/2026-04-24-overnight-swarm-launch.md:39:- `-o text`, `-p "$(cat BRIEF.prompt.md)"`
/Users/vladimir/Vault/CryoDAQ/50 Workflow/Overnight swarm pattern.md:2:source: CC_PROMPT_OVERNIGHT_SWARM_2026-04-24.md; docs/decisions/2026-04-24-overnight-swarm-launch.md; .claude/skills/multi-model-consultation.md §6/§7
/Users/vladimir/Vault/CryoDAQ/50 Workflow/Overnight swarm pattern.md:4:status: synthesized — pattern reusable for future overnight runs
/Users/vladimir/Vault/CryoDAQ/50 Workflow/ORCHESTRATION contract.md:2:source: docs/ORCHESTRATION.md (v1.1, 2026-04-23 + amendments)
/Users/vladimir/Vault/CryoDAQ/50 Workflow/ORCHESTRATION contract.md:4:status: digest — read repo doc for full rules
/Users/vladimir/Vault/CryoDAQ/50 Workflow/ORCHESTRATION contract.md:173:- `~/Projects/cryodaq/docs/ORCHESTRATION.md` — full text (~600 lines)
/Users/vladimir/Vault/CryoDAQ/40 Decisions/_index.md:2:source: skeleton stub
/Users/vladimir/Vault/CryoDAQ/40 Decisions/_index.md:4:status: index
/Users/vladimir/Vault/CryoDAQ/40 Decisions/_index.md:13:- One ADR per `docs/decisions/*.md` (mirrored)
/Users/vladimir/Vault/CryoDAQ/40 Decisions/2026-04-24-d1-d4a-execution.md:2:source: docs/decisions/2026-04-24-d1-d4a-execution.md
/Users/vladimir/Vault/CryoDAQ/40 Decisions/2026-04-24-d1-d4a-execution.md:5:status: accepted
/Users/vladimir/Vault/CryoDAQ/40 Decisions/2026-04-24-d1-d4a-execution.md:43:- Scope: `tools/diag_zmq_b1_capture.py` + its test only (Codex-01
/Users/vladimir/Vault/CryoDAQ/40 Decisions/ADR-003 Plugin isolation via ABC.md:2:source: synthesized from src/cryodaq/analytics/base_plugin.py, analytics/plugin_loader.py, CLAUDE.md "Аналитика"
/Users/vladimir/Vault/CryoDAQ/40 Decisions/ADR-003 Plugin isolation via ABC.md:5:status: accepted
/Users/vladimir/Vault/CryoDAQ/50 Workflow/_index.md:2:source: skeleton stub
/Users/vladimir/Vault/CryoDAQ/50 Workflow/_index.md:4:status: index

exec
/opt/homebrew/bin/bash -lc "for f in \"10 Subsystems/Safety FSM.md\" \"10 Subsystems/ZMQ bridge.md\" \"10 Subsystems/Persistence-first.md\" \"10 Subsystems/Calibration v2.md\" \"10 Subsystems/Alarm engine v2.md\" \"10 Subsystems/Plugin architecture.md\" \"20 Drivers/LakeShore 218S.md\" \"20 Drivers/Keithley 2604B.md\" \"20 Drivers/Thyracont VSP63D.md\" \"30 Investigations/B1 ZMQ idle-death.md\" \"30 Investigations/b2b4fb5 hardening race.md\" \"30 Investigations/Cyrillic homoglyph in alarm config.md\" \"30 Investigations/Codex H2 wrong hypothesis.md\" \"30 Investigations/Plugin isolation rebuild.md\" \"30 Investigations/IV.6 cmd plane hardening.md\" \"40 Decisions/ADR-001 Persistence-first invariant.md\" \"40 Decisions/ADR-002 R1 bounded-backoff probe retry.md\" \"40 Decisions/ADR-003 Plugin isolation via ABC.md\" \"50 Workflow/ORCHESTRATION contract.md\" \"50 Workflow/Multi-model consultation.md\" \"50 Workflow/Overnight swarm pattern.md\" \"50 Workflow/Calibration loops history.md\"; do printf '\\n===== %s =====\\n' \""'$f"; nl -ba "/Users/vladimir/Vault/CryoDAQ/$f"; done' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:

===== 10 Subsystems/Safety FSM.md =====
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
    42	  preconditions; source-on transition pending.
    43	- **RUNNING** — source active. Fail-on-silence and rate limit are
    44	  armed.
    45	- **FAULT_LATCHED** — entered on any fault while RUNNING. Source forced
    46	  OFF. No automatic recovery. Re-entry guard returns early on
    47	  concurrent `_fault()` calls (added 2026-04-17).
    48	- **MANUAL_RECOVERY** — entered after `acknowledge_fault()`. Returns to
    49	  READY when preconditions restore.
    50	
    51	`request_run()` may shortcut `SAFE_OFF → RUNNING` when all preconditions
    52	already hold, per docstring of `safety_manager.py`.
    53	
    54	## Fail-on-silence
    55	
    56	`SafetyManager` consumes the `SafetyBroker` (dedicated channel,
    57	`overflow=FAULT`). Stale data — no reading on a critical channel for
    58	`stale_timeout_s` (default 10 s) — fires `_fault("stale data")` and
    59	emergency-off **only while state == RUNNING**. Outside RUNNING, stale
    60	data blocks readiness via preconditions, not via fault.
    61	
    62	## Rate limit
    63	
    64	`dT/dt` is computed by [[_meta/glossary#FSM|`RateEstimator`]]
    65	(`window_s=120.0`, `min_points=60` after Phase 2c CC I.3). When any
    66	critical-channel rate exceeds `max_dT_dt_K_per_min` (default 5 K/min,
    67	configured in `safety.yaml`), `_fault()` fires.
    68	
    69	> Note: 5 K/min is the **configurable default**, not a hard-coded
    70	> invariant — production tuning is allowed.
    71	
    72	`min_points=60` × 0.5 s poll = 30 s data warmup before any rate-based
    73	fault decision.
    74	
    75	## Crash-recovery guard at Keithley connect
    76	
    77	`Keithley2604B.connect()` forces `OUTPUT_OFF` on both SMU channels
    78	before assuming control. Best-effort: if force-OFF fails, logs
    79	CRITICAL and continues (no crash, but the safety guarantee weakens).
    80	Documented in [[20 Drivers/Keithley 2604B]].
    81	
    82	## Cancellation shielding
    83	
    84	Phase 2d added `asyncio.shield()` around the post-fault sequence:
    85	
    86	- `emergency_off`
    87	- `fault_log_callback` (ordered BEFORE optional broker publish — Jules
    88	  R2 fix; callback after publish would have allowed an escape path)
    89	- `_ensure_output_off` in `_safe_off`
    90	
    91	These survive task cancellation during a fault cascade, so a
    92	post-mortem log entry is always written even if the engine is being
    93	torn down.
    94	
    95	## Re-entry guard
    96	
    97	A `_fault()` re-entry guard added 2026-04-17 (`A1 safety audit
    98	eb267c4`):
    99	
   100	```python
   101	if self._state == SafetyState.FAULT_LATCHED:
   102	    return  # already faulted; do not overwrite reason or duplicate events
   103	```
   104	
   105	Prevents concurrent `_fault()` calls (e.g. multiple critical-channel
   106	violations in the same poll cycle) from clobbering `_fault_reason`,
   107	emitting duplicate events, or re-firing `emergency_off`.
   108	
   109	## Fail-closed config
   110	
   111	`load_config()` raises `SafetyConfigError` (distinct class for
   112	clean-exit recognition) when:
   113	
   114	- `safety.yaml` not found at the configured path
   115	- file is malformed (not a mapping)
   116	- `critical_channels` is missing, not a list, or empty
   117	- any pattern fails to compile
   118	
   119	Engine exits with code 2; no auto-restart. Same fail-closed pattern
   120	applies to `alarms_v3.yaml`, `interlocks.yaml`, `housekeeping.yaml`,
   121	`channels.yaml`.
   122	
   123	## What is NOT here
   124	
   125	- **No firmware TSP watchdog.** P=const regulation is host-side in
   126	  `keithley_2604b.py`; the `tsp/p_const.lua` draft is **not loaded**
   127	  on the device. Phase 3 plan, requires hardware verification.
   128	- **No GUI-side authority.** GUI is read-only with respect to safety
   129	  state. Operator commands flow as REQ → REP and the FSM is the
   130	  single decision point.
   131	- **No automatic recovery from FAULT_LATCHED.** Operator
   132	  `acknowledge_fault()` is required.
   133	
   134	## See also
   135	
   136	- [[10 Subsystems/Persistence-first]] — readings reach SafetyBroker
   137	  AFTER SQLite commit
   138	- [[10 Subsystems/Alarm engine v2]] — separate from safety FSM;
   139	  operator-attention level, not source-control authority
   140	- [[20 Drivers/Keithley 2604B]] — crash-recovery guard implementation
   141	- [[40 Decisions/ADR-001 Persistence-first invariant]] — same
   142	  fail-closed-by-default ethos

===== 10 Subsystems/ZMQ bridge.md =====
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
   106	`tcp://`. Hypothesis: TCP-loopback layer is the remaining culprit
   107	since shared-REQ-state, mp.Queue back-pressure, engine REP wedge,
   108	and async cancellation have all been ruled out.
   109	
   110	Outcome 2026-04-23 was originally a runtime failure attributed to
   111	the transport. [[40 Decisions/2026-04-24-b2b4fb5-investigation|H3]]
   112	confirmed the failure was the b2b4fb5 hardening probe racing the
   113	ipc:// bind, NOT the transport. Repaired via R1 (bounded-backoff
   114	retry). After the repair lands, ipc:// runs normally for ~80 s
   115	then B1 fires anyway — IV.7 does not close B1, only shifts the
   116	failure surface.
   117	
   118	## Status (2026-04-26)
   119	
   120	- B1 ZMQ idle-death — still OPEN. Blocks `v0.34.0` tag. See
   121	  [[30 Investigations/B1 ZMQ idle-death]].
   122	- IV.6 partial mitigation — landed, defense-in-depth.
   123	- IV.7 ipc:// — viable transport, but does not close B1. Next
   124	  hypotheses: H4 (pyzmq 25.x + Python 3.14 asyncio integration),
   125	  H5 (engine REP state machine).
   126	
   127	## See also
   128	
   129	- [[30 Investigations/B1 ZMQ idle-death]]
   130	- [[30 Investigations/IV.6 cmd plane hardening]]
   131	- [[30 Investigations/b2b4fb5 hardening race]]
   132	- [[40 Decisions/ADR-002 R1 bounded-backoff probe retry]]

===== 10 Subsystems/Persistence-first.md =====
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
    52	## GUI latency tradeoff
    53	
    54	The cost is the SQLite `INSERT` time per poll cycle on the engine
    55	loop's hot path. Measured cost: a few ms per batch under WAL on
    56	spinning disk; sub-ms on SSD. Operator-perceived latency is the
    57	LakeShore poll interval (2 s) anyway, so the SQLite write does not
    58	dominate.
    59	
    60	GUI-side caching mitigates per-tick latency: the dashboard widgets
    61	hold local rolling history (`channel_buffer.py`). But all that data
    62	ultimately came from the broker, which came from a committed write.
    63	
    64	## Crash recovery and atomic sidecars
    65	
    66	Persistence-first is part of a wider fail-closed pattern (Phase 2d
    67	invariants):
    68	
    69	- **Atomic file writes** (`core/atomic_write.py`) for experiment
    70	  metadata sidecars and calibration index/curve files. `os.replace()`
    71	  is the durability primitive.
    72	- **Calibration KRDG+SRDG persist in one transaction per poll cycle.**
    73	  State mutation deferred to `on_srdg_persisted` so a write failure
    74	  does not leave `t_min`/`t_max` diverged from the actual persisted
    75	  data (Jules Round 2 Q3). See [[10 Subsystems/Calibration v2]].
    76	- **Cancellation shielding** on post-fault paths (Phase 2d):
    77	  `emergency_off`, `fault_log_callback` (BEFORE optional broker
    78	  publish), `_ensure_output_off` in `_safe_off`.
    79	- **OVERRANGE / UNDERRANGE persist** as `±inf` in REAL SQLite columns;
    80	  NaN-valued statuses (SENSOR_ERROR / TIMEOUT) are filtered out
    81	  before write because SQLite treats NaN as NULL (Phase 2d
    82	  Codex finding).
    83	
    84	## Daily rotation
    85	
    86	`SQLiteWriter` rotates to a new `data_YYYY-MM-DD.db` file at midnight.
    87	Old files are read-only with respect to the writer. Replay
    88	(`storage/replay.py`) reads any of them.
    89	
    90	## What this is NOT
    91	
    92	- **Not synchronous block.** The publisher tasks return as soon as
    93	  the writer call returns; they don't wait for any subscriber.
    94	- **Not a transactional barrier across drivers.** Two drivers polling
    95	  in parallel each enforce ordering individually; there is no
    96	  cross-driver "all-or-nothing" semantics.
    97	- **Not write-replicated.** A single SQLite per day; backup is via
    98	  external file copy or the optional Parquet cold rotation (F17 in
    99	  [[60 Roadmap/F-table backlog]]).
   100	
   101	## See also
   102	
   103	- [[40 Decisions/ADR-001 Persistence-first invariant]] — the synthesized
   104	  ADR for this rule
   105	- [[10 Subsystems/Safety FSM]] — cancellation shielding details
   106	- [[10 Subsystems/Calibration v2]] — KRDG+SRDG one-transaction rule

===== 10 Subsystems/Calibration v2.md =====
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
    49	3. **Breakpoints.** Identify zone boundaries for the multi-zone
    50	   Chebyshev fit (e.g. transitions across narrow regions of high
    51	   curvature need their own zone).
    52	4. **Fit.** Per-zone Chebyshev polynomial via `numpy.polynomial.chebyshev`.
    53	   Yields `CalibrationCurve` with coefficients per zone, fit metrics,
    54	   source session IDs, metadata.
    55	
    56	Result is a `CalibrationFitResult` with raw, downsampled, and
    57	breakpoint pair lists kept around for plotting / inspection.
    58	
    59	## Output formats
    60	
    61	`CalibrationCurve.export(format)` supports four targets:
    62	
    63	- **`.330`** — LakeShore controller calibration table format,
    64	  breakpoint-based. Contains sampled curve breakpoints, NOT polynomial
    65	  coefficients. Older format.
    66	- **`.340`** — LakeShore newer breakpoint format, same family as
    67	  `.330`.
    68	- **JSON** — CryoDAQ-internal format with Chebyshev coefficients per
    69	  zone, metrics, source session IDs, metadata. Source-of-truth
    70	  artifact.
    71	- **`.cof`** — **PENDING.** Architect-decided 2026-04-25: raw
    72	  Chebyshev coefficient export format. Not yet implemented; `.330` to
    73	  be removed when `.cof` lands.
    74	
    75	CSV import / export available via `CalibrationStore` for round-trip
    76	with external tooling.
    77	
    78	## Runtime apply policy
    79	
    80	Calibration v2 supports per-channel runtime routing in
    81	`LakeShore218S` (`drivers/instruments/lakeshore_218s.py`):
    82	
    83	- **Global mode `on/off`** — enable / disable runtime calibration
    84	  application across all LakeShore channels at once.
    85	- **Per-channel policy `inherit | off | on`** — overrides the global
    86	  mode. `inherit` follows global; `off`/`on` pin per-channel behavior.
    87	- **Conservative fallback** — at runtime, if curve / assignment /
    88	  SRDG missing OR computation throws, the driver falls back to KRDG
    89	  (calibrated reading from the LakeShore controller itself) and logs
    90	  the reason once per `(channel_key, reason)` to avoid log spam
    91	  (`_runtime_warning_cache`).
    92	
    93	Policy + fallback together mean a malformed curve never silently
    94	breaks an experiment — operator sees KRDG, behavior degrades to v1
    95	semantics, log line tells them what happened.
    96	
    97	## Lab-verification gap
    98	
    99	Per `README.md` "Известные ограничения": runtime apply policy is
   100	implemented and tested in mock; **per-channel behavior on the live
   101	LakeShore requires separate lab verification** before being trusted
   102	as the active calibration in production runs.
   103	
   104	## See also
   105	
   106	- [[20 Drivers/LakeShore 218S]] — driver runtime routing impl
   107	- [[10 Subsystems/Persistence-first]] — KRDG+SRDG one-transaction rule
   108	- [[_meta/glossary]] — KRDG, SRDG definitions
   109	- [[60 Roadmap/F-table backlog]] — F8 (cooldown ML), F9 (TIM auto-report)

===== 10 Subsystems/Alarm engine v2.md =====
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
    56	`config/alarm_providers.py` ships concrete `PhaseProvider` and
    57	`SetpointProvider` wired to `ExperimentManager`.
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
    70	## Per-machine config (Ubuntu lab PC, 2026-04-20)
    71	
    72	- Т4 added to `uncalibrated` and `all_temp` channel groups so
    73	  `sensor_fault` still publishes WARNING for the disconnected sensor
    74	  without triggering hardware lockout via `interlocks.yaml`.
    75	
    76	## Known issue (open)
    77	
    78	`alarm_v2.py:252` raises `KeyError: 'threshold'` when evaluating the
    79	`cooldown_stall` composite alarm. One sub-condition is missing a
    80	`threshold` field — probably a stale rate-type rule where
    81	`threshold` is spurious. Log spam every ~2 s; engine does not
    82	crash. Fix candidates:
    83	
    84	- Config-side: adjust `config/alarms_v3.yaml` to drop the spurious
    85	  field.
    86	- Code-side: defensive `cond.get("threshold")` in `_eval_condition`.
    87	
    88	Pending Codex-04 patch (overnight swarm 2026-04-24 stream).
    89	
    90	## Relationship to safety
    91	
    92	The alarm engine is for **operator attention**, not source-control
    93	authority. `SafetyManager` is the only thing that turns sources on
    94	or off. An alarm at CRITICAL level may trigger an interlock action
    95	configured separately in `config/interlocks.yaml`, but the
    96	authority to act is still `SafetyManager`'s. See
    97	[[10 Subsystems/Safety FSM]].
    98	
    99	## See also
   100	
   101	- [[30 Investigations/Cyrillic homoglyph in alarm config]]
   102	- [[10 Subsystems/Safety FSM]]
   103	- [[60 Roadmap/F-table backlog]] — F10 (sensor diagnostics → alarm)

===== 10 Subsystems/Plugin architecture.md =====
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
    53	## Exception isolation
    54	
    55	A plugin throwing inside `process()` is caught at the pipeline
    56	boundary, logged as ERROR, and that batch is dropped for that plugin
    57	only. Other plugins keep running. This is the rebuild after the
    58	original direct-import architecture (which would crash the engine
    59	when a plugin threw — see [[30 Investigations/Plugin isolation rebuild]]).
    60	
    61	`_load_plugin()` also wraps the entire load attempt in a try/except;
    62	a malformed file logs and is skipped, not failed.
    63	
    64	## Hot reload semantics
    65	
    66	- Add a new `.py` to `plugins/` → loaded within ~5 s.
    67	- Modify a plugin → unload + reload within ~5 s of mtime change.
    68	- Delete a plugin → removed within ~5 s.
    69	
    70	5 s mtime polling is intentional — `inotify`/`FSEvents` would be
    71	faster but add a platform dependency for marginal benefit.
    72	
    73	## Plugin data flow
    74	
    75	```text
    76	DataBroker  ─subscribe─►  PluginPipeline._queue
    77	                          (asyncio.Queue[Reading])
    78	                                │
    79	                                ▼
    80	                          _process_loop:
    81	                            batch ≤ 500 readings
    82	                            ├─► plugin1.process()  ──► DerivedMetric[]
    83	                            ├─► plugin2.process()  ──► DerivedMetric[]
    84	                            └─► ...
    85	                                │
    86	                                ▼
    87	                          publish each DerivedMetric
    88	                          back into DataBroker as Reading
    89	```
    90	
    91	The "publish back as Reading" step means downstream consumers (GUI,
    92	web, SQLite) treat derived metrics uniformly with raw readings.
    93	
    94	## Configuration
    95	
    96	`config/plugins.yaml` carries feature flags for shipped plugins:
    97	
    98	- `sensor_diagnostics` — MAD / correlation health scoring
    99	  (numpy exception per `CLAUDE.md`).
   100	- `vacuum_trend` — BIC-selected pump-down extrapolation.
   101	- (cooldown predictor lives outside the plugin pipeline since it
   102	  needs orchestration with `core/cooldown_service.py`.)
   103	
   104	Plugins NOT ENABLED by default — operator opts in.
   105	
   106	## See also
   107	
   108	- [[30 Investigations/Plugin isolation rebuild]] — why exception
   109	  isolation is non-negotiable
   110	- [[40 Decisions/ADR-003 Plugin isolation via ABC]] — synthesized
   111	  rationale
   112	- [[60 Roadmap/F-table backlog]] — F16 (plugin SDK + examples)

===== 20 Drivers/LakeShore 218S.md =====
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
    58	`_use_per_channel_krdg` and `_use_per_channel_srdg` are tri-state
    59	flags driven by `_krdg0_fail_count` and `_srdg0_fail_count`: if the
    60	batch `KRDG?`/`SRDG?` form fails N times, the driver switches to
    61	per-channel form for `_krdg_batch_retry_interval_s` (default 60 s),
    62	then attempts batch form again.
    63	
    64	## Mock mode
    65	
    66	`mock=True` produces realistic signals via `_mock_sensor_unit(t)`
    67	(`temp` → ohms approximation `1600/(T+15) + 0.08`) over a tuple of
    68	realistic base temperatures (4.2 K, 4.8 K, 77 K, 77.5 K, 4.5 K, 4.1 K,
    69	3.9 K, 300 K). Useful for engine smoke tests and GUI development.
    70	
    71	## Notable quirks
    72	
    73	- **GPIB bus serialization.** Multiple LakeShores on the same bus
    74	  (`GPIB0::*`) cannot be polled in parallel — NI GPIB-USB-HS does
    75	  not tolerate concurrent access even with `asyncio.Lock` +
    76	  `run_in_executor`. `Scheduler` groups same-bus drivers into one
    77	  sequential task. See `core/scheduler.py:67`.
    78	- **`OVERRANGE`/`UNDERRANGE` valid as ±inf.** `RDGST?` returns
    79	  status codes; the driver maps them to `ChannelStatus` enum.
    80	  OVERRANGE/UNDERRANGE persist as `±inf` in REAL SQLite columns;
    81	  SENSOR_ERROR/TIMEOUT (NaN) are filtered before write (Phase 2d
    82	  invariant 10).
    83	- **Cyrillic Т prefix homoglyph hazard.** Per-channel labels use
    84	  Cyrillic Т (U+0422). LLMs occasionally produce Latin "T" in
    85	  generated config; tests can pass while the channel never matches
    86	  any rule. See [[30 Investigations/Cyrillic homoglyph in alarm config]].
    87	
    88	## See also
    89	
    90	- [[20 Drivers/Keithley 2604B]]
    91	- [[20 Drivers/Thyracont VSP63D]]
    92	- [[10 Subsystems/Calibration v2]]
    93	- [[10 Subsystems/Safety FSM]] — Т1..Т8 are critical channels for
    94	  rate-limit and overheat interlock

===== 20 Drivers/Keithley 2604B.md =====
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
    17	- **Channels:** `smua` and `smub` (dual-SMU). Combined mode
    18	  `smua + smub` is also supported. Channel ID parsing in
    19	  `core/smu_channel.py` via `SmuChannel` enum + `normalize_smu_channel`.
    20	
    21	Per-channel reading kinds: `voltage` (V), `current` (A),
    22	`resistance` (Ohm), `power` (W). All four published per poll cycle
    23	with channel naming `<instrument_id>/<smu>/<kind>`.
    24	
    25	## Host-side P=const regulation
    26	
    27	```python
    28	# tsp/p_const.lua — DRAFT, NOT LOADED on the device.
    29	# P=const feedback runs host-side in keithley_2604b.read_channels().
    30	```
    31	
    32	Per `CLAUDE.md` "Ключевые правила": no TSP scripts are uploaded to
    33	the instrument; the VISA bus stays free for queries. The host loop:
    34	
    35	1. Read V and I from each active SMU.
    36	2. Compute `R = V/I` (skipped when `|I| < _I_MIN_A = 1e-7` to avoid
    37	   noise-dominated divisions).
    38	3. Compute `target_v = sqrt(P_target × R)` for the requested
    39	   `p_target`.
    40	4. Apply slew-rate limit `MAX_DELTA_V_PER_STEP = 0.5 V` per cycle so
    41	   `target_v` cannot jump from 0 to `V_compliance` in one step on an
    42	   abrupt resistance change (superconducting transition, wire break).
    43	5. Set new V; let next cycle re-measure.
    44	
    45	`_COMPLIANCE_NOTIFY_THRESHOLD = 10` consecutive compliance cycles
    46	notifies `SafetyManager` (this is operator-attention, not auto-fault).
    47	
    48	## Crash-recovery guard at connect
    49	
    50	`Keithley2604B.connect()` forces `OUTPUT_OFF` on both SMU channels
    51	before assuming control:
    52	
    53	> Best-effort: if force-OFF fails, logs CRITICAL and continues — not
    54	> guaranteed.
    55	
    56	The intent: a previous engine crash that left the source ON cannot
    57	silently keep being ON when the new engine attaches. See `CLAUDE.md`
    58	safety section ("Crash-recovery guard").
    59	
    60	## Disconnect calls emergency_off first
    61	
    62	Per `CLAUDE.md` "Ключевые правила": `Keithley disconnect must call
    63	emergency off first.` `disconnect()` runs `emergency_off()` on each
    64	active SMU before closing transport, ensuring the operator's stop
    65	button doesn't leave the source ON.
    66	
    67	## NI-VISA `\x00` quirk
    68	
    69	VISA resource strings on Windows / NI-VISA contain `\x00` per spec
    70	(e.g. `USB0::0x05E6::0x2604::04052028::INSTR`). python-docx rejects
    71	those as XML 1.0-illegal control chars when embedded in auto-reports.
    72	Fixed `74dbbc7` (2026-04-20) via `src/cryodaq/utils/xml_safe.py`
    73	sanitizer applied at all `add_paragraph()` / `cell.text` sites in
    74	`reporting/sections.py`. Logger upgraded from `log.warning` to
    75	`log.exception` so future report-gen failures carry tracebacks.
    76	
    77	## Mock mode
    78	
    79	`_mock_r_of_t()` produces a realistic R(T) curve `R = R0 × (1 + α×T)`
    80	with `_MOCK_R0=100`, `_MOCK_T0=300`, `_MOCK_ALPHA=0.0033`,
    81	`_MOCK_COOLING_RATE=0.1`, `_MOCK_SMUB_FACTOR=0.7`. Sufficient for
    82	engine smoke and GUI exercise.
    83	
    84	## See also
    85	
    86	- [[10 Subsystems/Safety FSM]] — single source-on/off authority
    87	- [[20 Drivers/LakeShore 218S]]
    88	- [[20 Drivers/Thyracont VSP63D]]
    89	- `tsp/p_const.lua` — TSP supervisor draft (Phase 3, hardware-verify)

===== 20 Drivers/Thyracont VSP63D.md =====
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
    36	115200: 9600}` controls the fallback once per attempt:
    37	
    38	1. Try MV00 probe at the configured baudrate.
    39	2. If fail, try V1 probe at the alternate baudrate.
    40	3. If neither responds, raise.
    41	
    42	## Status map
    43	
    44	```python
    45	_STATUS_OK         = 0  → ChannelStatus.OK
    46	_STATUS_UNDERRANGE = 1  → ChannelStatus.UNDERRANGE
    47	_STATUS_OVERRANGE  = 2  → ChannelStatus.OVERRANGE
    48	_STATUS_SENSOR_ERROR = 3 → ChannelStatus.SENSOR_ERROR
    49	```
    50	
    51	OVERRANGE / UNDERRANGE persist as `±inf` per Phase 2d invariant 10
    52	(see [[10 Subsystems/Persistence-first]]).
    53	
    54	## V1 checksum quirk
    55	
    56	V1 protocol response contains a 1-character checksum at the end.
    57	`_verify_v1_checksum(response)` validates; checksum failure causes
    58	the driver to drop the reading rather than parse partial garbage.
    59	
    60	The checksum formula differs slightly between VSP63D and VSP206
    61	hardware (lab PC has VSP206). `validate_checksum: false` in
    62	`config/instruments.local.yaml` (Ubuntu lab PC) bypasses this check.
    63	The YAML key was previously **silently ignored** by the engine
    64	loader — driver defaulted to `True` regardless. Wiring fixed in
    65	`aabd75f` (2026-04-20). Without the fix, the operator could turn
    66	the toggle off and the engine would still strict-validate.
    67	
    68	## Probe-vs-read inconsistency (open issue)
    69	
    70	Per CHANGELOG "Open / known issues carrying into 0.34.0":
    71	
    72	> `_try_v1_probe` always succeeds; read checksum-validates. Driver
    73	> can "connect" and emit NaN forever on non-VSP63D hardware.
    74	
    75	Pending hardening fix. Intended approach: V1 probe should read at
    76	least one full message and validate checksum before reporting
    77	"connected".
    78	
    79	## Lab-PC-specific operational hazard
    80	
    81	`ModemManager` (Ubuntu) was transiently grabbing `/dev/ttyUSB0`
    82	when the Thyracont was plugged in. Disabled on the lab PC
    83	2026-04-20. Documented in CHANGELOG. Future deployments should
    84	disable `ModemManager` (or systemd-mask it) as part of the
    85	operator-PC bring-up runbook.
    86	
    87	## Mock mode
    88	
    89	`_MOCK_BASE_PRESSURE_MBAR = 1.5e-6`. Random walk around base value;
    90	realistic enough for vacuum-trend plugin testing and GUI plot
    91	exercise.
    92	
    93	## See also
    94	
    95	- [[20 Drivers/LakeShore 218S]]
    96	- [[20 Drivers/Keithley 2604B]]
    97	- [[60 Roadmap/F-table backlog]] — F13 (vacuum leak rate estimator)

===== 30 Investigations/B1 ZMQ idle-death.md =====
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
    25	into the same context **also hang**. Engine REP itself answers a
    26	direct in-process Python client in 0.001 s while the bridge
    27	subprocess is deep into B1 — engine is not wedged.
    28	
    29	| Platform | First failure |
    30	|---|---|
    31	| macOS Darwin (Python 3.14.3, pyzmq 25.x) | stochastic 4–92 s uptime |
    32	| Ubuntu 22.04 (Python 3.12.13, pyzmq 26.4.0) | exactly 120 s after subprocess start (single data point, may vary) |
    33	
    34	Real Ubuntu lab PC reproduces in `./start.sh`, not just diag tools.
    35	
    36	## Hypothesis tree
    37	
    38	| H | Hypothesis | Evidence | Status |
    39	|---|---|---|---|
    40	| H1 | macOS kernel idle reaping of loopback TCP | `tcp_keepalive_time = 7200s` on Linux, yet 120 s deterministic failure | **falsified 2026-04-20** |
    41	| H2 | Single long-lived REQ socket accumulating bad state (Codex's primary) | IV.6 implemented per-cmd ephemeral REQ; B1 still reproduces | **falsified 2026-04-20** |
    42	| H3 | b2b4fb5 hardening probe incompatible with `ipc://` | repro on revert + bind-time race confirmed | **partially confirmed** — explains 2026-04-23 IV.7 misattribution but does NOT explain B1 itself; B1 still fires after ~80 s on ipc:// |
    43	| H4 | pyzmq 25.x + Python 3.14 asyncio integration / engine REP task state under rapid REQ connect-disconnect churn | not yet tested in isolation | **untested** — D2 split-context falsification experiment scheduled |
    44	| H5 | engine REP state machine | not yet specifically probed | **untested** |
    45	
    46	## What works
    47	
    48	- Engine REP socket itself — direct Python REQ client gets 0.001 s
    49	  reply mid-failure.
    50	- Engine internals: SQLite writes (~9000/10 min), heartbeats every
    51	  30 s, plugin ticks, scheduler all stay healthy.
    52	- Raw subprocess without `ZmqBridge` wrapping (`diag_zmq_subprocess.py`)
    53	  succeeds short-term on both `fork` and `spawn` mp start methods.
    54	
    55	## What's been tried
    56	
    57	1. **`TCP_KEEPALIVE` on all four sockets** (commit `f5f9039`,
    58	   reverted on cmd path in IV.6). Partial delay of failure on macOS
    59	   only; Linux unaffected. Reverted on command + PUB paths since H1
    60	   was falsified; kept on `sub_drain_loop` SUB as orthogonal
    61	   safeguard.
    62	2. **IV.6 ephemeral REQ + cmd-channel watchdog** (`be51a24`).
    63	   Codex's H2 hypothesis. Implements ZeroMQ Guide ch.4 canonical
    64	   "poll / timeout / close / reopen" pattern. **Did not fix B1.**
    65	3. **IV.6 watchdog cooldown hotfix** — solves restart-storm
    66	   regression (30–40 restarts/min on Ubuntu) but is not a B1 fix;
    67	   produces "works ~60–120 s, one restart, works again" cycle as
    68	   workaround.
    69	4. **IV.7 ipc:// transport experiment.** Branch
    70	   `experiment/iv7-ipc-transport`. Switches loopback default to
    71	   Unix-domain sockets on macOS / Linux. ipc:// runs normally for
    72	   ~80 s then B1 fires anyway — not a transport-layer fix, but
    73	   useful as a diagnostic constant.
    74	
    75	## Diagnostics in tree
    76	
    77	`tools/diag_zmq_*.py` retained for regression after fix:
    78	
    79	- `tools/diag_zmq_subprocess.py` — subprocess alone, short.
    80	- `tools/diag_zmq_bridge.py` — full ZmqBridge 60 s soak.
    81	- `tools/diag_zmq_bridge_extended.py` — 180 s past-first-failure.
    82	- `tools/diag_zmq_idle_hypothesis.py` — rate-dependence reproducer.
    83	- `tools/diag_zmq_b1_capture.py` — canonical B1 capture CLI
    84	  (post-D4a, post-R1).
    85	- `tools/_b1_diagnostics.py` — reusable helpers (bridge_snapshot,
    86	  direct_engine_probe).
    87	
    88	`/tmp/diag_iv6_*.log` and `/tmp/engine_iv6_debug.log` preserved for
    89	architect review.
    90	
    91	## Why this still matters
    92	
    93	`v0.34.0` cannot ship while B1 reproduces — the user-visible
    94	symptom is "GUI buttons don't work after a couple of minutes; have
    95	to restart the bridge subprocess". The IV.6 watchdog cooldown
    96	provides a usable workaround (60–120 s cycle with single restart),
    97	not an acceptable production state.
    98	
    99	## Next experiments
   100	
   101	- **D2 — H4 split-context falsification** on
   102	  `experiment/iv7-ipc-transport` worktree.
   103	- If H4 / H5 both falsified: target may be lower (libzmq 4.x
   104	  loopback handling, kernel-level interaction). Would justify a
   105	  switch to a different IPC mechanism entirely (mp.Pipe, UNIX
   106	  socket without zmq, etc.).
   107	
   108	## See also
   109	
   110	- [[30 Investigations/IV.6 cmd plane hardening]]
   111	- [[30 Investigations/b2b4fb5 hardening race]]
   112	- [[30 Investigations/Codex H2 wrong hypothesis]]
   113	- [[40 Decisions/2026-04-24-b2b4fb5-investigation]]
   114	- [[40 Decisions/2026-04-24-d1-d4a-execution]]
   115	- [[10 Subsystems/ZMQ bridge]]

===== 30 Investigations/b2b4fb5 hardening race.md =====
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
    15	- **2026-04-23 14:25** — Commit `b2b4fb5` ("harden B1 capture bridge
    16	  startup validation") landed. Adds synchronous probe
    17	  `_validate_bridge_startup()` to `tools/diag_zmq_b1_capture.py` that
    18	  fails fast on `bridge.is_alive() == False` or first non-OK
    19	  `safety_status` reply.
    20	- **2026-04-23 15:10** — Commit `157c4bc` (IV.7 `ipc://` transport
    21	  experiment) landed 45 minutes later, on a different branch.
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

===== 30 Investigations/Cyrillic homoglyph in alarm config.md =====
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
    33	- `config/interlocks.yaml::overheat_cryostat::channel_pattern` —
    34	  was previously `Т[1-8] .*` with mixed case, also touched in `9feaf3e`
    35	  fix; later tightened to `Т(1|2|3|5|6|7|8) .*` to exclude
    36	  physically-disconnected Т4 on the Ubuntu lab PC.
    37	- `docs/design-system/` rules involving "мбар" vs "mbar" (similar
    38	  class — Latin `mbar` got flagged in `1c61268` CRITICAL domain
    39	  cleanup).
    40	
    41	## Why it survives ordinary review
    42	
    43	- **Visual identity** — Cyrillic Т and Latin T are visually
    44	  indistinguishable in most monospace fonts. PR diff review by a
    45	  human reading the screen catches nothing.
    46	- **Test design** — alarm tests ran the engine on synthetic
    47	  channels named in the test. They didn't cross-reference back to
    48	  the production `instruments.yaml` namespace.
    49	- **Encoding** — both characters are valid UTF-8, both serialize
    50	  fine in YAML. The file never failed to load.
    51	
    52	## Defenses now in place
    53	
    54	- **Regression test** that asserts every channel pattern in
    55	  `config/alarms_v3.yaml` matches at least one channel in
    56	  `config/channels.yaml` after canonical resolution.
    57	- **Design system rules** (`docs/design-system/rules/*-rules.md`)
    58	  carry explicit Cyrillic-Т-vs-Latin-T invariant for any operator-
    59	  facing rendered text.
    60	- **Adversarial second-model review** (`docs/CODEX_SELF_REVIEW_PLAYBOOK.md`)
    61	  — Codex gpt-5.5/high catches homoglyph-class issues alongside
    62	  semantic regressions.
    63	
    64	## Encoding policy (CLAUDE.md "Кодировка файлов")
    65	
    66	- Python source / Markdown / YAML in repo: UTF-8 **without BOM**.
    67	- BOM is applied **only** to operator-facing CSV exports
    68	  (`storage/csv_export.py`) — Excel on Russian Windows needs the
    69	  BOM prefix to read Cyrillic correctly.
    70	- Do not add BOM to any source file. External reviewers occasionally
    71	  flag a BOM invariant for source — that's misapplication.
    72	
    73	## Lesson
    74	
    75	Tests prove logic correctness, not identifier correctness. When a
    76	rule and the channel namespace it operates over both come from
    77	different files, the regression test must close that loop
    78	explicitly. Visual review can never catch homoglyphs reliably.
    79	
    80	## See also
    81	
    82	- [[10 Subsystems/Alarm engine v2]]
    83	- [[20 Drivers/LakeShore 218S]] — Cyrillic Т prefix origin
    84	- [[30 Investigations/Codex H2 wrong hypothesis]] — different lesson
    85	  from the same year about model confidence vs tests

===== 30 Investigations/Codex H2 wrong hypothesis.md =====
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

===== 30 Investigations/Plugin isolation rebuild.md =====
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
    71	synthetic `Reading`s, so downstream consumers (GUI, web, SQLite)
    72	treat them uniformly.
    73	
    74	## Where it lives now
    75	
    76	- ABC: `analytics/base_plugin.py`.
    77	- Pipeline: `analytics/plugin_loader.py`.
    78	- Production plugin examples: `analytics/sensor_diagnostics.py`,
    79	  `analytics/vacuum_trend.py`. (Cooldown predictor lives outside
    80	  the plugin pipeline because it needs orchestration with
    81	  `core/cooldown_service.py`.)
    82	- Configuration: `config/plugins.yaml` controls which plugins are
    83	  enabled; `<plugin_id>.yaml` siblings carry plugin-specific config.
    84	
    85	## Lesson
    86	
    87	Engine survival is non-negotiable. Any extension point that lets a
    88	third party (operator-authored plugin) run code in the hot path
    89	must isolate exceptions explicitly — Python's default exception
    90	flow is to crash the loop, and that is the wrong default for
    91	acquisition systems.
    92	
    93	## See also
    94	
    95	- [[10 Subsystems/Plugin architecture]] — full subsystem page
    96	- [[40 Decisions/ADR-003 Plugin isolation via ABC]] — synthesized
    97	  ADR for this rebuild

===== 30 Investigations/IV.6 cmd plane hardening.md =====
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
    43	[[30 Investigations/Codex H2 wrong hypothesis]]. Engine REP goes
    44	silently unresponsive after ~30–90 s of bridge uptime while the
    45	asyncio loop, data-plane PUB, heartbeats, scheduler writes, and
    46	plugin ticks all remain healthy.
    47	
    48	## Watchdog regression + cooldown hotfix (2026-04-20 evening)
    49	
    50	The IV.6 watchdog initially had a bug: `_last_cmd_timeout` persisted
    51	across watchdog-triggered subprocess restart. A fresh subprocess
    52	saw a stale timeout signal on the first poll cycle, triggered
    53	another restart, etc. — restart storm (30–40 restarts/minute on
    54	Ubuntu lab PC).
    55	
    56	Hotfix in `src/cryodaq/launcher.py`:
    57	- 60 s cooldown between command-watchdog restarts via
    58	  `_last_cmd_watchdog_restart` timestamp.
    59	- Missing `return` after restart added so no further checks run in
    60	  the same poll cycle.
    61	
    62	Effect: restart storm gone, but B1 itself still fires. System
    63	reaches usable steady state of "works ~60–120 s, one restart, works
    64	again" — workaround until IV.7 ipc:// or other root-cause fix.
    65	
    66	## Why it stayed in master
    67	
    68	Even though IV.6 doesn't fix B1, the changes are kept:
    69	
    70	- **Architectural improvement.** Matches ZeroMQ Guide ch.4
    71	  canonical reliable req-reply pattern. Future maintainers expect
    72	  this shape.
    73	- **Removes a real brittle point.** Shared REQ state across
    74	  commands was a long-term maintainability hazard regardless of
    75	  whether it caused B1.
    76	- **Gives the launcher a cmd-channel watchdog.** Separate from
    77	  data-plane health detection, the launcher can now detect and
    78	  recover from any future command-only failure shape.
    79	- **Defense-in-depth.** B1 root cause may be deeper still; if a
    80	  future bug surfaces with a similar shape, IV.6 closes one of the
    81	  candidate failure modes.
    82	
    83	## Related fixes shipped alongside
    84	
    85	- `aabd75f` — `engine: wire validate_checksum through Thyracont
    86	  driver loader`. `_create_instruments()` was ignoring the YAML
    87	  key; driver defaulted to `True` regardless of config. Resolves
    88	  TopWatchBar pressure em-dash on Ubuntu lab PC (VSP206 vs VSP63D
    89	  checksum). See [[20 Drivers/Thyracont VSP63D]].
    90	- `74dbbc7` — `reporting: xml_safe sanitizer for python-docx
    91	  compatibility`. Keithley VISA resource strings contain `\x00`;
    92	  python-docx rejected them as XML 1.0 incompatible. New
    93	  `src/cryodaq/utils/xml_safe.py` strips XML-illegal control chars
    94	  at all add_paragraph / cell.text sites in
    95	  `reporting/sections.py`. See [[20 Drivers/Keithley 2604B]].
    96	
    97	## Lesson
    98	
    99	Shipping a hypothesis-driven fix is OK even when it doesn't close
   100	the bug, **provided** the change is independently defensible and
   101	documented as partial mitigation. The mistake would have been to
   102	celebrate IV.6 as a B1 fix and stop investigating; the audit
   103	record clearly says "partial — B1 still open".
   104	
   105	## See also
   106	
   107	- [[30 Investigations/B1 ZMQ idle-death]]
   108	- [[30 Investigations/Codex H2 wrong hypothesis]]
   109	- [[10 Subsystems/ZMQ bridge]]

===== 40 Decisions/ADR-001 Persistence-first invariant.md =====
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
    65	- GUI dashboards must hold local rolling buffers (`channel_buffer.py`)
    66	  to render high-frequency timeseries — but the buffer is fed from
    67	  the broker, which only sees committed readings.
    68	- "Performance mode" overrides are not allowed. Any future
    69	  optimization that would skip or defer the write step has to clear
    70	  this ADR.
    71	- The fail-closed config invariant (engine exit code 2 on missing
    72	  / malformed `safety.yaml`, `alarms_v3.yaml`, `interlocks.yaml`,
    73	  `housekeeping.yaml`, `channels.yaml`) extends the same default:
    74	  start in a state where durable behavior is guaranteed, refuse to
    75	  start otherwise.
    76	
    77	## Status
    78	
    79	Accepted. Has been the operating contract since Phase 2d. The
    80	`docs/decisions/*` ledgers do not contain a separate ADR for this
    81	invariant because it predates the ledger system; the invariant is
    82	captured in `CLAUDE.md` and `PROJECT_STATUS.md`. This synthesized
    83	ADR exists to make the rationale visible alongside the other ADRs
    84	in this vault.
    85	
    86	## See also
    87	
    88	- [[10 Subsystems/Persistence-first]] — implementation page
    89	- [[10 Subsystems/Safety FSM]] — cancellation-shielded fault path
    90	- [[10 Subsystems/Calibration v2]] — one-transaction rule

===== 40 Decisions/ADR-002 R1 bounded-backoff probe retry.md =====
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

===== 40 Decisions/ADR-003 Plugin isolation via ABC.md =====
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
    59	- Synthetic `Reading` republishing means downstream consumers
    60	  (GUI, web, SQLite) treat derived metrics uniformly. No special
    61	  channel or pipeline for analytics output.
    62	
    63	## Status
    64	
    65	Accepted. Pattern is the basis of all subsequent analytics work
    66	(`sensor_diagnostics`, `vacuum_trend`, future F16 plugin SDK).
    67	
    68	The cooldown predictor (`core/cooldown_service.py`) is deliberately
    69	**not** a plugin, because it needs orchestration with the
    70	experiment lifecycle that the plugin pipeline doesn't provide.
    71	That carve-out is fine; the ABC is for stateless, batch-driven
    72	analytics.
    73	
    74	## See also
    75	
    76	- [[10 Subsystems/Plugin architecture]] — implementation page
    77	- [[30 Investigations/Plugin isolation rebuild]] — story behind
    78	  the rebuild
    79	- [[60 Roadmap/F-table backlog]] — F16 (plugin hot-reload SDK +
    80	  examples)

===== 50 Workflow/ORCHESTRATION contract.md =====
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
    74	`PROJECT_STATUS.md`, `RELEASE_CHECKLIST.md`, `LICENSE`,
    75	`THIRD_PARTY_NOTICES.md`, `CC_PROMPT_*.md`, `HANDOFF_*.md`,
    76	`SESSION_DETAIL_*.md`). Audit / review / hardening output goes
    77	under `docs/audits/<date-slug>/` or
    78	`artifacts/consultations/<date>/<topic>/`, never at root.
    79	
    80	Decision ledger: every session CC writes
    81	`docs/decisions/<YYYY-MM-DD>-session.md` with `## HH:MM —
    82	<decision>` blocks (Thesis / Reasoning / Decision / Consulted /
    83	Open). The ledger is the long-term memory.
    84	
    85	## §7. Hardening + feature interaction rule
    86	
    87	**The rule that exists because of `b2b4fb5` vs IV.7.** Before
    88	landing a hardening / tightening change, check whether it could
    89	affect any active feature branch. If yes, hold or merge into the
    90	feature branch and retest. If no, document why not in the commit
    91	`Risk:` line. Active branches are visible via `git worktree list`
    92	— check before tightening shared infra. See
    93	[[30 Investigations/b2b4fb5 hardening race]].
    94	
    95	## §8. Architect-absent operating mode
    96	
    97	When architect is unavailable (quota window): CC continues
    98	**only on previously-architected plans**. No new directions, no
    99	new feature branches for initiative work. Bug / regression fixes on
   100	in-progress work are OK. End-of-session handoff goes to
   101	`artifacts/handoffs/<date>-cc-to-architect.md`.
   102	
   103	## §9. Document evolution
   104	
   105	This contract is authoritative but not immutable. Disagreement
   106	goes through the architect via decision-ledger note → next
   107	architect session → commit. Do **not** silently bypass.
   108	
   109	## §10. Session start checklist
   110	
   111	Read this doc end-to-end + `CLAUDE.md`. `git status`,
   112	`git branch --show-current`, `git worktree list`. Check
   113	`artifacts/consultations/` for unsynthesized responses. Check
   114	`docs/decisions/` for the latest session ledger. Stale
   115	(>2 day) feature branch detected → block work, surface to
   116	architect.
   117	
   118	## §11. Known active plans
   119	
   120	Tracked table — only plans listed here can be worked on. If a
   121	consultant claims to be working on something else, STOP.
   122	
   123	## §12. Failure-mode reference
   124	
   125	Six historical failure modes are enumerated as the rationale
   126	behind the rules:
   127	
   128	1. Parallel rewrites (`codex/b1-truth-recovery` vs
   129	   `codex/safe-merge-b1-truth-recovery`).
   130	2. Root-directory markdown flood (12 ungoverned `.md` at root).
   131	3. Hardening / feature collision (`b2b4fb5` × IV.7).
   132	4. No-leader multi-agent drift (five agents reviewing without
   133	   synthesis).
   134	5. Lost context (untracked architect dump for 3 days).
   135	6. Over-strict stopping — added retroactively after the
   136	   2026-04-23 cleanup-baseline session
   137	   ([[40 Decisions/2026-04-23-cleanup-baseline]]).
   138	
   139	## §13. STOP discipline and autonomy band (added 2026-04-23)
   140	
   141	§13.1 — when CC must STOP: irreversible data loss / git rewrite,
   142	genuine semantic ambiguity, architect-domain decision, sensitive
   143	material, file > 100 KB about to be silently lost, real test
   144	failure, junk consultant response.
   145	
   146	§13.2 — when CC must NOT stop, adapt instead: 1-line plan
   147	inaccuracy, mechanical detail differs, untracked file would be
   148	lost (preserve to archive then proceed — the "no delete" rule is a
   149	PRESERVE rule, not a STOP rule).
   150	
   151	§13.3 — adaptations are recorded inline in the session ledger as
   152	`Plan said / Reality / Adapted / Outcome`.
   153	
   154	§13.4 — the preserve-vs-delete clarification: archive routine
   155	plan-document patterns and proceed; STOP only on > 100 KB,
   156	sensitive content, credential paths, or binary garbage.
   157	
   158	§13.5 — autonomy band explicitly granted for commit message
   159	wording, file-path adjustments, mechanical step reordering, side-
   160	commits to preserve untracked files. NOT granted for branch
   161	merges outside plan, file deletions outside `git branch -D`
   162	targets, history rewrites, consultant invocations on already-
   163	covered decisions, new feature branches under §8.
   164	
   165	§13.6 — calibration principle: rules that over-stop waste
   166	architect time; rules that under-stop risk silent breakage. The
   167	ledger + handoff are the mechanism that lets CC run with relaxed
   168	stopping discipline; architect end-of-day review catches anything
   169	that should have been a stop.
   170	
   171	## See also
   172	
   173	- `~/Projects/cryodaq/docs/ORCHESTRATION.md` — full text (~600 lines)
   174	- [[50 Workflow/Multi-model consultation]] — skill that operates
   175	  under §4
   176	- [[50 Workflow/Calibration loops history]] — how prompts and CC
   177	  behavior evolved into this contract
   178	- [[40 Decisions/2026-04-23-cleanup-baseline]] — first session run
   179	  under this contract

===== 50 Workflow/Multi-model consultation.md =====
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

===== 50 Workflow/Overnight swarm pattern.md =====
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

===== 50 Workflow/Calibration loops history.md =====
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
   115	- Required prompt template (`Model: gpt-5.5 / Reasoning effort:
   116	  high` mandatory).
   117	- Autonomy on FAIL: CRITICAL/HIGH → amend without asking;
   118	  design-decision FAIL → STOP + escalate.
   119	- 3-amend cycle limit.
   120	- Final report to architect: SHA + Codex PASS summary + residual
   121	  risks.
   122	
   123	**Outcome.** Block-level work since 2026-04-23 has predictable
   124	review cadence. Architect reads result, not process.
   125	
   126	## Open loops (as of 2026-04-26)
   127	
   128	- **Skill-registry refresh** (Loop 5 above) — pending edit.
   129	- **ORCHESTRATION.md §5.4 wording cleanup** ("already gitignored" →
   130	  "enforced invariant" since `587bea8`) — open from
   131	  [[40 Decisions/2026-04-23-cleanup-baseline]].
   132	- **Retroactive semantic versioning** (v0.34.0..v0.38.0) — postponed
   133	  pending B1 mitigation.
   134	- **§11 known-active-plans table** updates trail by ~1 session
   135	  every architect cycle.
   136	
   137	## The calibration principle (§13.6)
   138	
   139	The point of the loops is that **rules that over-stop waste
   140	architect time, and rules that under-stop risk silent breakage**.
   141	The session ledger + handoff are the corrective mechanism: relaxed
   142	stopping is fine because the architect's end-of-day ledger review
   143	catches anything that should have been a stop.
   144	
   145	If that review pattern breaks down (architect misses something
   146	important in the ledger), specific rules tighten. Otherwise, the
   147	default is autonomy band. The loops are what calibrate that band.
   148	
   149	## See also
   150	
   151	- [[50 Workflow/ORCHESTRATION contract]] §13
   152	- [[40 Decisions/2026-04-23-cleanup-baseline]]
   153	- [[40 Decisions/2026-04-24-b2b4fb5-investigation]]
   154	- [[50 Workflow/Multi-model consultation]]
   155	- [[50 Workflow/Overnight swarm pattern]]

codex
The first bulk read was too large and truncated midway, so I’m splitting the audit into subsystems/drivers/investigations/decisions/workflow. I’m also going to read the relevant source implementations alongside each group to avoid relying on summaries.
exec
/opt/homebrew/bin/bash -lc "for f in \"10 Subsystems/Alarm engine v2.md\" \"10 Subsystems/Plugin architecture.md\" \"20 Drivers/LakeShore 218S.md\" \"20 Drivers/Keithley 2604B.md\" \"20 Drivers/Thyracont VSP63D.md\"; do printf '\\n===== %s =====\\n' \""'$f"; nl -ba "/Users/vladimir/Vault/CryoDAQ/$f"; done' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:

===== 10 Subsystems/Alarm engine v2.md =====
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
    56	`config/alarm_providers.py` ships concrete `PhaseProvider` and
    57	`SetpointProvider` wired to `ExperimentManager`.
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
    70	## Per-machine config (Ubuntu lab PC, 2026-04-20)
    71	
    72	- Т4 added to `uncalibrated` and `all_temp` channel groups so
    73	  `sensor_fault` still publishes WARNING for the disconnected sensor
    74	  without triggering hardware lockout via `interlocks.yaml`.
    75	
    76	## Known issue (open)
    77	
    78	`alarm_v2.py:252` raises `KeyError: 'threshold'` when evaluating the
    79	`cooldown_stall` composite alarm. One sub-condition is missing a
    80	`threshold` field — probably a stale rate-type rule where
    81	`threshold` is spurious. Log spam every ~2 s; engine does not
    82	crash. Fix candidates:
    83	
    84	- Config-side: adjust `config/alarms_v3.yaml` to drop the spurious
    85	  field.
    86	- Code-side: defensive `cond.get("threshold")` in `_eval_condition`.
    87	
    88	Pending Codex-04 patch (overnight swarm 2026-04-24 stream).
    89	
    90	## Relationship to safety
    91	
    92	The alarm engine is for **operator attention**, not source-control
    93	authority. `SafetyManager` is the only thing that turns sources on
    94	or off. An alarm at CRITICAL level may trigger an interlock action
    95	configured separately in `config/interlocks.yaml`, but the
    96	authority to act is still `SafetyManager`'s. See
    97	[[10 Subsystems/Safety FSM]].
    98	
    99	## See also
   100	
   101	- [[30 Investigations/Cyrillic homoglyph in alarm config]]
   102	- [[10 Subsystems/Safety FSM]]
   103	- [[60 Roadmap/F-table backlog]] — F10 (sensor diagnostics → alarm)

===== 10 Subsystems/Plugin architecture.md =====
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
    53	## Exception isolation
    54	
    55	A plugin throwing inside `process()` is caught at the pipeline
    56	boundary, logged as ERROR, and that batch is dropped for that plugin
    57	only. Other plugins keep running. This is the rebuild after the
    58	original direct-import architecture (which would crash the engine
    59	when a plugin threw — see [[30 Investigations/Plugin isolation rebuild]]).
    60	
    61	`_load_plugin()` also wraps the entire load attempt in a try/except;
    62	a malformed file logs and is skipped, not failed.
    63	
    64	## Hot reload semantics
    65	
    66	- Add a new `.py` to `plugins/` → loaded within ~5 s.
    67	- Modify a plugin → unload + reload within ~5 s of mtime change.
    68	- Delete a plugin → removed within ~5 s.
    69	
    70	5 s mtime polling is intentional — `inotify`/`FSEvents` would be
    71	faster but add a platform dependency for marginal benefit.
    72	
    73	## Plugin data flow
    74	
    75	```text
    76	DataBroker  ─subscribe─►  PluginPipeline._queue
    77	                          (asyncio.Queue[Reading])
    78	                                │
    79	                                ▼
    80	                          _process_loop:
    81	                            batch ≤ 500 readings
    82	                            ├─► plugin1.process()  ──► DerivedMetric[]
    83	                            ├─► plugin2.process()  ──► DerivedMetric[]
    84	                            └─► ...
    85	                                │
    86	                                ▼
    87	                          publish each DerivedMetric
    88	                          back into DataBroker as Reading
    89	```
    90	
    91	The "publish back as Reading" step means downstream consumers (GUI,
    92	web, SQLite) treat derived metrics uniformly with raw readings.
    93	
    94	## Configuration
    95	
    96	`config/plugins.yaml` carries feature flags for shipped plugins:
    97	
    98	- `sensor_diagnostics` — MAD / correlation health scoring
    99	  (numpy exception per `CLAUDE.md`).
   100	- `vacuum_trend` — BIC-selected pump-down extrapolation.
   101	- (cooldown predictor lives outside the plugin pipeline since it
   102	  needs orchestration with `core/cooldown_service.py`.)
   103	
   104	Plugins NOT ENABLED by default — operator opts in.
   105	
   106	## See also
   107	
   108	- [[30 Investigations/Plugin isolation rebuild]] — why exception
   109	  isolation is non-negotiable
   110	- [[40 Decisions/ADR-003 Plugin isolation via ABC]] — synthesized
   111	  rationale
   112	- [[60 Roadmap/F-table backlog]] — F16 (plugin SDK + examples)

===== 20 Drivers/LakeShore 218S.md =====
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
    58	`_use_per_channel_krdg` and `_use_per_channel_srdg` are tri-state
    59	flags driven by `_krdg0_fail_count` and `_srdg0_fail_count`: if the
    60	batch `KRDG?`/`SRDG?` form fails N times, the driver switches to
    61	per-channel form for `_krdg_batch_retry_interval_s` (default 60 s),
    62	then attempts batch form again.
    63	
    64	## Mock mode
    65	
    66	`mock=True` produces realistic signals via `_mock_sensor_unit(t)`
    67	(`temp` → ohms approximation `1600/(T+15) + 0.08`) over a tuple of
    68	realistic base temperatures (4.2 K, 4.8 K, 77 K, 77.5 K, 4.5 K, 4.1 K,
    69	3.9 K, 300 K). Useful for engine smoke tests and GUI development.
    70	
    71	## Notable quirks
    72	
    73	- **GPIB bus serialization.** Multiple LakeShores on the same bus
    74	  (`GPIB0::*`) cannot be polled in parallel — NI GPIB-USB-HS does
    75	  not tolerate concurrent access even with `asyncio.Lock` +
    76	  `run_in_executor`. `Scheduler` groups same-bus drivers into one
    77	  sequential task. See `core/scheduler.py:67`.
    78	- **`OVERRANGE`/`UNDERRANGE` valid as ±inf.** `RDGST?` returns
    79	  status codes; the driver maps them to `ChannelStatus` enum.
    80	  OVERRANGE/UNDERRANGE persist as `±inf` in REAL SQLite columns;
    81	  SENSOR_ERROR/TIMEOUT (NaN) are filtered before write (Phase 2d
    82	  invariant 10).
    83	- **Cyrillic Т prefix homoglyph hazard.** Per-channel labels use
    84	  Cyrillic Т (U+0422). LLMs occasionally produce Latin "T" in
    85	  generated config; tests can pass while the channel never matches
    86	  any rule. See [[30 Investigations/Cyrillic homoglyph in alarm config]].
    87	
    88	## See also
    89	
    90	- [[20 Drivers/Keithley 2604B]]
    91	- [[20 Drivers/Thyracont VSP63D]]
    92	- [[10 Subsystems/Calibration v2]]
    93	- [[10 Subsystems/Safety FSM]] — Т1..Т8 are critical channels for
    94	  rate-limit and overheat interlock

===== 20 Drivers/Keithley 2604B.md =====
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
    17	- **Channels:** `smua` and `smub` (dual-SMU). Combined mode
    18	  `smua + smub` is also supported. Channel ID parsing in
    19	  `core/smu_channel.py` via `SmuChannel` enum + `normalize_smu_channel`.
    20	
    21	Per-channel reading kinds: `voltage` (V), `current` (A),
    22	`resistance` (Ohm), `power` (W). All four published per poll cycle
    23	with channel naming `<instrument_id>/<smu>/<kind>`.
    24	
    25	## Host-side P=const regulation
    26	
    27	```python
    28	# tsp/p_const.lua — DRAFT, NOT LOADED on the device.
    29	# P=const feedback runs host-side in keithley_2604b.read_channels().
    30	```
    31	
    32	Per `CLAUDE.md` "Ключевые правила": no TSP scripts are uploaded to
    33	the instrument; the VISA bus stays free for queries. The host loop:
    34	
    35	1. Read V and I from each active SMU.
    36	2. Compute `R = V/I` (skipped when `|I| < _I_MIN_A = 1e-7` to avoid
    37	   noise-dominated divisions).
    38	3. Compute `target_v = sqrt(P_target × R)` for the requested
    39	   `p_target`.
    40	4. Apply slew-rate limit `MAX_DELTA_V_PER_STEP = 0.5 V` per cycle so
    41	   `target_v` cannot jump from 0 to `V_compliance` in one step on an
    42	   abrupt resistance change (superconducting transition, wire break).
    43	5. Set new V; let next cycle re-measure.
    44	
    45	`_COMPLIANCE_NOTIFY_THRESHOLD = 10` consecutive compliance cycles
    46	notifies `SafetyManager` (this is operator-attention, not auto-fault).
    47	
    48	## Crash-recovery guard at connect
    49	
    50	`Keithley2604B.connect()` forces `OUTPUT_OFF` on both SMU channels
    51	before assuming control:
    52	
    53	> Best-effort: if force-OFF fails, logs CRITICAL and continues — not
    54	> guaranteed.
    55	
    56	The intent: a previous engine crash that left the source ON cannot
    57	silently keep being ON when the new engine attaches. See `CLAUDE.md`
    58	safety section ("Crash-recovery guard").
    59	
    60	## Disconnect calls emergency_off first
    61	
    62	Per `CLAUDE.md` "Ключевые правила": `Keithley disconnect must call
    63	emergency off first.` `disconnect()` runs `emergency_off()` on each
    64	active SMU before closing transport, ensuring the operator's stop
    65	button doesn't leave the source ON.
    66	
    67	## NI-VISA `\x00` quirk
    68	
    69	VISA resource strings on Windows / NI-VISA contain `\x00` per spec
    70	(e.g. `USB0::0x05E6::0x2604::04052028::INSTR`). python-docx rejects
    71	those as XML 1.0-illegal control chars when embedded in auto-reports.
    72	Fixed `74dbbc7` (2026-04-20) via `src/cryodaq/utils/xml_safe.py`
    73	sanitizer applied at all `add_paragraph()` / `cell.text` sites in
    74	`reporting/sections.py`. Logger upgraded from `log.warning` to
    75	`log.exception` so future report-gen failures carry tracebacks.
    76	
    77	## Mock mode
    78	
    79	`_mock_r_of_t()` produces a realistic R(T) curve `R = R0 × (1 + α×T)`
    80	with `_MOCK_R0=100`, `_MOCK_T0=300`, `_MOCK_ALPHA=0.0033`,
    81	`_MOCK_COOLING_RATE=0.1`, `_MOCK_SMUB_FACTOR=0.7`. Sufficient for
    82	engine smoke and GUI exercise.
    83	
    84	## See also
    85	
    86	- [[10 Subsystems/Safety FSM]] — single source-on/off authority
    87	- [[20 Drivers/LakeShore 218S]]
    88	- [[20 Drivers/Thyracont VSP63D]]
    89	- `tsp/p_const.lua` — TSP supervisor draft (Phase 3, hardware-verify)

===== 20 Drivers/Thyracont VSP63D.md =====
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
    36	115200: 9600}` controls the fallback once per attempt:
    37	
    38	1. Try MV00 probe at the configured baudrate.
    39	2. If fail, try V1 probe at the alternate baudrate.
    40	3. If neither responds, raise.
    41	
    42	## Status map
    43	
    44	```python
    45	_STATUS_OK         = 0  → ChannelStatus.OK
    46	_STATUS_UNDERRANGE = 1  → ChannelStatus.UNDERRANGE
    47	_STATUS_OVERRANGE  = 2  → ChannelStatus.OVERRANGE
    48	_STATUS_SENSOR_ERROR = 3 → ChannelStatus.SENSOR_ERROR
    49	```
    50	
    51	OVERRANGE / UNDERRANGE persist as `±inf` per Phase 2d invariant 10
    52	(see [[10 Subsystems/Persistence-first]]).
    53	
    54	## V1 checksum quirk
    55	
    56	V1 protocol response contains a 1-character checksum at the end.
    57	`_verify_v1_checksum(response)` validates; checksum failure causes
    58	the driver to drop the reading rather than parse partial garbage.
    59	
    60	The checksum formula differs slightly between VSP63D and VSP206
    61	hardware (lab PC has VSP206). `validate_checksum: false` in
    62	`config/instruments.local.yaml` (Ubuntu lab PC) bypasses this check.
    63	The YAML key was previously **silently ignored** by the engine
    64	loader — driver defaulted to `True` regardless. Wiring fixed in
    65	`aabd75f` (2026-04-20). Without the fix, the operator could turn
    66	the toggle off and the engine would still strict-validate.
    67	
    68	## Probe-vs-read inconsistency (open issue)
    69	
    70	Per CHANGELOG "Open / known issues carrying into 0.34.0":
    71	
    72	> `_try_v1_probe` always succeeds; read checksum-validates. Driver
    73	> can "connect" and emit NaN forever on non-VSP63D hardware.
    74	
    75	Pending hardening fix. Intended approach: V1 probe should read at
    76	least one full message and validate checksum before reporting
    77	"connected".
    78	
    79	## Lab-PC-specific operational hazard
    80	
    81	`ModemManager` (Ubuntu) was transiently grabbing `/dev/ttyUSB0`
    82	when the Thyracont was plugged in. Disabled on the lab PC
    83	2026-04-20. Documented in CHANGELOG. Future deployments should
    84	disable `ModemManager` (or systemd-mask it) as part of the
    85	operator-PC bring-up runbook.
    86	
    87	## Mock mode
    88	
    89	`_MOCK_BASE_PRESSURE_MBAR = 1.5e-6`. Random walk around base value;
    90	realistic enough for vacuum-trend plugin testing and GUI plot
    91	exercise.
    92	
    93	## See also
    94	
    95	- [[20 Drivers/LakeShore 218S]]
    96	- [[20 Drivers/Keithley 2604B]]
    97	- [[60 Roadmap/F-table backlog]] — F13 (vacuum leak rate estimator)

exec
/opt/homebrew/bin/bash -lc "for f in src/cryodaq/analytics/calibration.py src/cryodaq/analytics/calibration_fitter.py src/cryodaq/core/calibration_acquisition.py src/cryodaq/drivers/instruments/lakeshore_218s.py src/cryodaq/drivers/instruments/keithley_2604b.py src/cryodaq/drivers/instruments/thyracont_vsp63d.py; do printf '\\n===== %s =====\\n' \""'$f"; nl -ba "$f" | sed -n '"'1,280p'; done" in /Users/vladimir/Projects/cryodaq
exec
/opt/homebrew/bin/bash -lc "for f in src/cryodaq/core/safety_manager.py src/cryodaq/core/scheduler.py src/cryodaq/storage/sqlite_writer.py src/cryodaq/core/alarm_v2.py src/cryodaq/core/alarm_config.py src/cryodaq/analytics/base_plugin.py src/cryodaq/analytics/plugin_loader.py; do printf '\\n===== %s =====\\n' \""'$f"; nl -ba "$f" | sed -n '"'1,260p'; done" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:

===== src/cryodaq/analytics/calibration.py =====
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
   261	            max_order=max(1, max_order),
   262	            target_rmse_k=max(float(target_rmse_k), 0.0),
   263	        )
   264	
   265	        all_predictions = np.array(
   266	            [self._evaluate_zones(zones, raw_value) for raw_value in raw_values],
   267	            dtype=float,
   268	        )
   269	        residuals = all_predictions - temperatures
   270	        sensitivity = np.gradient(raw_values, temperatures)
   271	        curve = CalibrationCurve(
   272	            curve_id=uuid.uuid4().hex[:12],
   273	            sensor_id=sensor_id.strip(),
   274	            fit_timestamp=_utcnow(),
   275	            raw_unit=raw_unit.strip() or "sensor_unit",
   276	            sensor_kind=sensor_kind.strip() or "generic",
   277	            source_session_ids=tuple(str(item) for item in (source_session_ids or ()) if str(item)),
   278	            zones=tuple(zones),
   279	            metrics={
   280	                "sample_count": int(len(normalized_samples)),

===== src/cryodaq/analytics/calibration_fitter.py =====
     1	"""Calibration v2 post-run pipeline: extract pairs, downsample, breakpoints, fit."""
     2	
     3	from __future__ import annotations
     4	
     5	import logging
     6	import math
     7	import sqlite3
     8	from dataclasses import dataclass
     9	from datetime import UTC, datetime
    10	from pathlib import Path
    11	from typing import Any
    12	
    13	import numpy as np
    14	
    15	from cryodaq.analytics.calibration import CalibrationCurve, CalibrationSample, CalibrationStore
    16	
    17	logger = logging.getLogger(__name__)
    18	
    19	
    20	@dataclass
    21	class CalibrationFitResult:
    22	    sensor_id: str
    23	    reference_channel: str
    24	    raw_pairs_count: int
    25	    downsampled_count: int
    26	    breakpoint_count: int
    27	    curve: CalibrationCurve
    28	    metrics: dict[str, Any]
    29	    raw_pairs: list[tuple[float, float]]
    30	    downsampled: list[tuple[float, float]]
    31	    breakpoints: list[tuple[float, float]]
    32	
    33	
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
    71	                krdg_data.extend(cursor.fetchall())
    72	
    73	                cursor = conn.execute(
    74	                    "SELECT timestamp, value FROM readings "
    75	                    "WHERE channel = ? AND timestamp >= ? AND timestamp <= ? "
    76	                    "ORDER BY timestamp",
    77	                    (srdg_channel, start_ts, end_ts),
    78	                )
    79	                srdg_data.extend(cursor.fetchall())
    80	                conn.close()
    81	            except Exception:
    82	                logger.warning("Failed to read %s", db_path, exc_info=True)
    83	
    84	        if not krdg_data or not srdg_data:
    85	            return []
    86	
    87	        # Time-align: for each SRDG point, find nearest KRDG
    88	        krdg_ts = np.array([t for t, _ in krdg_data])
    89	        krdg_vals = np.array([v for _, v in krdg_data])
    90	
    91	        pairs: list[tuple[float, float]] = []
    92	        for ts, srdg_val in srdg_data:
    93	            # Filter bad SRDG
    94	            if not math.isfinite(srdg_val) or srdg_val <= 0:
    95	                continue
    96	
    97	            # Find nearest KRDG
    98	            idx = int(np.searchsorted(krdg_ts, ts))
    99	            best_idx = idx
   100	            best_delta = float("inf")
   101	            for candidate in (idx - 1, idx, idx + 1):
   102	                if 0 <= candidate < len(krdg_ts):
   103	                    delta = abs(krdg_ts[candidate] - ts)
   104	                    if delta < best_delta:
   105	                        best_delta = delta
   106	                        best_idx = candidate
   107	
   108	            if best_delta > max_time_delta_s:
   109	                continue
   110	
   111	            krdg_val = float(krdg_vals[best_idx])
   112	            if not math.isfinite(krdg_val) or krdg_val < 1.5 or krdg_val > 1e6:
   113	                continue
   114	
   115	            pairs.append((srdg_val, krdg_val))
   116	
   117	        return pairs
   118	
   119	    # ------------------------------------------------------------------
   120	    # Downsample
   121	    # ------------------------------------------------------------------
   122	
   123	    @staticmethod
   124	    def adaptive_downsample(
   125	        raw_pairs: list[tuple[float, float]],
   126	        target_count: int = 500,
   127	        min_per_bin: int = 3,
   128	    ) -> list[tuple[float, float]]:
   129	        """Downsample preserving high-curvature regions."""
   130	        if len(raw_pairs) <= target_count:
   131	            return list(raw_pairs)
   132	
   133	        # Sort by SRDG value
   134	        sorted_pairs = sorted(raw_pairs, key=lambda p: p[0])
   135	        n = len(sorted_pairs)
   136	
   137	        # Compute curvature (second derivative magnitude)
   138	        srdg = np.array([p[0] for p in sorted_pairs])
   139	        krdg = np.array([p[1] for p in sorted_pairs])
   140	
   141	        # Smooth second derivative
   142	        curvature = np.zeros(n)
   143	        for i in range(1, n - 1):
   144	            ds = srdg[i + 1] - srdg[i - 1]
   145	            if ds > 0:
   146	                d2t = abs(krdg[i + 1] - 2 * krdg[i] + krdg[i - 1])
   147	                curvature[i] = d2t / (ds * ds + 1e-12)
   148	
   149	        # Divide into bins
   150	        n_bins = max(4, target_count // min_per_bin)
   151	        bin_edges = np.linspace(srdg[0], srdg[-1], n_bins + 1)
   152	
   153	        # Compute per-bin curvature weight
   154	        bin_weights = np.ones(n_bins)
   155	        for b in range(n_bins):
   156	            mask = (srdg >= bin_edges[b]) & (srdg < bin_edges[b + 1])
   157	            if b == n_bins - 1:
   158	                mask = (srdg >= bin_edges[b]) & (srdg <= bin_edges[b + 1])
   159	            if mask.any():
   160	                bin_weights[b] = max(1.0, float(np.mean(curvature[mask])))
   161	
   162	        # Allocate points proportional to curvature
   163	        total_weight = bin_weights.sum()
   164	        bin_alloc = np.maximum(
   165	            min_per_bin,
   166	            np.round(bin_weights / total_weight * target_count).astype(int),
   167	        )
   168	
   169	        # Sample from each bin
   170	        result: list[tuple[float, float]] = []
   171	        for b in range(n_bins):
   172	            mask = (srdg >= bin_edges[b]) & (srdg < bin_edges[b + 1])
   173	            if b == n_bins - 1:
   174	                mask = (srdg >= bin_edges[b]) & (srdg <= bin_edges[b + 1])
   175	            indices = np.where(mask)[0]
   176	            if len(indices) == 0:
   177	                continue
   178	            count = min(int(bin_alloc[b]), len(indices))
   179	            chosen = np.linspace(0, len(indices) - 1, count, dtype=int)
   180	            for idx in chosen:
   181	                result.append(sorted_pairs[int(indices[idx])])
   182	
   183	        # Ensure boundary points included
   184	        result.append(sorted_pairs[0])
   185	        result.append(sorted_pairs[-1])
   186	
   187	        # Deduplicate and sort
   188	        result = sorted(set(result), key=lambda p: p[0])
   189	        return result
   190	
   191	    # ------------------------------------------------------------------
   192	    # Breakpoints (Douglas-Peucker)
   193	    # ------------------------------------------------------------------
   194	
   195	    @staticmethod
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
   231	            ds = s_end - s_start
   232	            dt = t_end - t_start
   233	            seg_len = math.sqrt(ds * ds + dt * dt) or 1e-12
   234	
   235	            for i in range(start + 1, end):
   236	                # Perpendicular distance from point to line segment
   237	                s_i = sorted_pairs[i][0]
   238	                t_i = sorted_pairs[i][1]
   239	                dist = abs(dt * (s_start - s_i) - ds * (t_start - t_i)) / seg_len
   240	                if dist > max_dist:
   241	                    max_dist = dist
   242	                    max_idx = i
   243	
   244	            if max_dist > tolerance_k:
   245	                include[max_idx] = True
   246	                stack.append((start, max_idx))
   247	                stack.append((max_idx, end))
   248	
   249	        return [sorted_pairs[i] for i in range(n) if include[i]]
   250	
   251	    # ------------------------------------------------------------------
   252	    # Coverage
   253	    # ------------------------------------------------------------------
   254	
   255	    @staticmethod
   256	    def compute_coverage(
   257	        raw_pairs: list[tuple[float, float]],
   258	        n_bins: int = 20,
   259	    ) -> list[dict[str, Any]]:
   260	        """Coverage statistics by temperature range."""
   261	        if not raw_pairs:
   262	            return []
   263	
   264	        temps = [t for _, t in raw_pairs]
   265	        t_min, t_max = min(temps), max(temps)
   266	        if t_max - t_min < 0.1:
   267	            return [
   268	                {
   269	                    "temp_min": t_min,
   270	                    "temp_max": t_max,
   271	                    "point_count": len(raw_pairs),
   272	                    "density": float(len(raw_pairs)),
   273	                    "status": "dense",
   274	                }
   275	            ]
   276	
   277	        bin_edges = np.linspace(t_min, t_max, n_bins + 1)
   278	        bins: list[dict[str, Any]] = []
   279	
   280	        for i in range(n_bins):

===== src/cryodaq/core/calibration_acquisition.py =====
     1	"""Continuous SRDG acquisition during calibration experiments."""
     2	
     3	from __future__ import annotations
     4	
     5	import logging
     6	import math
     7	from typing import Any
     8	
     9	from cryodaq.core.channel_manager import ChannelConfigError
    10	from cryodaq.drivers.base import ChannelStatus, Reading
    11	
    12	logger = logging.getLogger(__name__)
    13	
    14	
    15	class CalibrationCommandError(ValueError):
    16	    """Raised when a calibration command cannot be executed due to invalid parameters."""
    17	
    18	
    19	class CalibrationAcquisitionService:
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
   171	        Kept for test backward compatibility. Production code uses the
   172	        new split via Scheduler. Will be removed in next major version.
   173	        """
   174	        import warnings
   175	
   176	        warnings.warn(
   177	            "on_readings is deprecated; use prepare_srdg_readings + on_srdg_persisted",
   178	            DeprecationWarning,
   179	            stacklevel=2,
   180	        )
   181	        if not self._active:
   182	            return
   183	
   184	        to_write, pending_state = self.prepare_srdg_readings(krdg, srdg)
   185	        if to_write:
   186	            await self._writer.write_immediate(to_write)
   187	            self.on_srdg_persisted(len(to_write), pending_state)

===== src/cryodaq/drivers/instruments/lakeshore_218s.py =====
     1	"""LakeShore 218S driver with optional runtime calibration routing."""
     2	
     3	from __future__ import annotations
     4	
     5	import asyncio
     6	import logging
     7	import random
     8	import time as _time
     9	from typing import Any
    10	
    11	from cryodaq.analytics.calibration import CalibrationStore
    12	from cryodaq.drivers.base import ChannelStatus, InstrumentDriver, Reading
    13	from cryodaq.drivers.transport.gpib import GPIBTransport
    14	
    15	log = logging.getLogger(__name__)
    16	
    17	_MOCK_BASE_TEMPS: tuple[float, ...] = (4.2, 4.8, 77.0, 77.5, 4.5, 4.1, 3.9, 300.0)
    18	
    19	
    20	def _mock_sensor_unit(temp_k: float) -> float:
    21	    return round((1600.0 / (temp_k + 15.0)) + 0.08, 6)
    22	
    23	
    24	class LakeShore218S(InstrumentDriver):
    25	    def __init__(
    26	        self,
    27	        name: str,
    28	        resource_str: str,
    29	        *,
    30	        channel_labels: dict[int, str] | None = None,
    31	        mock: bool = False,
    32	        calibration_store: CalibrationStore | None = None,
    33	    ) -> None:
    34	        super().__init__(name, mock=mock)
    35	        self._resource_str = resource_str
    36	        self._channel_labels: dict[int, str] = channel_labels or {}
    37	        self._transport = GPIBTransport(mock=mock)
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
    76	                upper = idn_raw.upper()
    77	                if idn_raw and "LSCI" in upper and "218" in upper:
    78	                    idn_valid = True
    79	                    self._instrument_id = idn_raw
    80	                    log.info("%s: IDN verified: %s", self.name, idn_raw)
    81	                    break
    82	
    83	                if attempt == 0:
    84	                    # Try a Selected Device Clear before the second attempt.
    85	                    log.warning(
    86	                        "%s: IDN validation failed (response=%r), issuing GPIB clear and retrying",
    87	                        self.name,
    88	                        idn_raw,
    89	                    )
    90	                    try:
    91	                        await self._transport.clear_bus()
    92	                    except Exception as clear_exc:
    93	                        log.warning(
    94	                            "%s: clear_bus before IDN retry failed: %s",
    95	                            self.name,
    96	                            clear_exc,
    97	                        )
    98	                    await asyncio.sleep(0.2)
    99	
   100	            if not idn_valid:
   101	                await self._transport.close()
   102	                raise RuntimeError(
   103	                    f"{self.name}: LakeShore 218S IDN validation failed. "
   104	                    f"Expected 'LSCI,MODEL218...', got {idn_raw!r}. "
   105	                    f"Check GPIB address and cabling."
   106	                )
   107	
   108	        self._connected = True
   109	        self._use_per_channel_krdg = False
   110	        self._use_per_channel_srdg = False
   111	        self._krdg0_fail_count = 0
   112	        self._srdg0_fail_count = 0
   113	        log.info("%s: connected", self.name)
   114	
   115	    async def disconnect(self) -> None:
   116	        if not self._connected:
   117	            return
   118	        await self._transport.close()
   119	        self._connected = False
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
   141	            self._last_status_check = now
   142	            try:
   143	                self._last_status_result = await self.read_status()
   144	            except Exception as exc:
   145	                log.debug("%s: RDGST? periodic check failed: %s", self.name, exc)
   146	        # Attach status bits as metadata
   147	        if self._last_status_result:
   148	            for r in readings:
   149	                ch_num = (r.metadata or {}).get("raw_channel")
   150	                if ch_num is not None and ch_num in self._last_status_result:
   151	                    if r.metadata is None:
   152	                        r.metadata = {}
   153	                    r.metadata["sensor_status"] = self._last_status_result[ch_num]
   154	
   155	        return readings
   156	
   157	    async def _read_krdg_channels(self) -> list[Reading]:
   158	        if self.mock:
   159	            return self._mock_readings()
   160	
   161	        if self._use_per_channel_krdg:
   162	            return await self._read_krdg_per_channel()
   163	
   164	        raw_response = await self._transport.query("KRDG?")
   165	        log.debug("%s: KRDG? -> %s", self.name, raw_response)
   166	        readings = self._parse_response(raw_response, unit="K", reading_kind="temperature")
   167	        if len(readings) < 8:
   168	            self._krdg0_fail_count += 1
   169	            log.warning(
   170	                "%s: KRDG? returned %d values (expected 8), fallback #%d",
   171	                self.name,
   172	                len(readings),
   173	                self._krdg0_fail_count,
   174	            )
   175	            if self._krdg0_fail_count >= 3:
   176	                self._use_per_channel_krdg = True
   177	                log.warning(
   178	                    "%s: KRDG? failed %d times, switching to per-channel mode permanently",
   179	                    self.name,
   180	                    self._krdg0_fail_count,
   181	                )
   182	            return await self._read_krdg_per_channel()
   183	        self._krdg0_fail_count = 0
   184	        return readings
   185	
   186	    async def _read_krdg_per_channel(self) -> list[Reading]:
   187	        """Fallback: query each channel individually (KRDG? 1 .. KRDG? 8).
   188	
   189	        Periodically retries batch KRDG? to recover from transient failures.
   190	        """
   191	
   192	        now = _time.monotonic()
   193	        if now - self._krdg_last_batch_retry >= self._krdg_batch_retry_interval_s:
   194	            self._krdg_last_batch_retry = now
   195	            try:
   196	                raw = await self._transport.query("KRDG?")
   197	                readings = self._parse_response(raw, unit="K", reading_kind="temperature")
   198	                if len(readings) >= 8:
   199	                    log.info(
   200	                        "%s: KRDG? batch mode recovered — switching back from per-channel",
   201	                        self.name,
   202	                    )
   203	                    self._use_per_channel_krdg = False
   204	                    self._krdg0_fail_count = 0
   205	                    return readings
   206	            except Exception:
   207	                pass  # Stay in per-channel mode
   208	
   209	        readings: list[Reading] = []
   210	        for ch in range(1, 9):
   211	            try:
   212	                raw = await self._transport.query(f"KRDG? {ch}")
   213	                parsed = self._parse_response(raw, unit="K", reading_kind="temperature")
   214	                if parsed:
   215	                    # Fix channel index — _parse_response starts at 1 for first token
   216	                    reading = parsed[0]
   217	                    channel_name = self._channel_labels.get(ch, f"CH{ch}")
   218	                    readings.append(
   219	                        Reading.now(
   220	                            channel=channel_name,
   221	                            value=reading.value,
   222	                            unit=reading.unit,
   223	                            instrument_id=self.name,
   224	                            status=reading.status,
   225	                            raw=reading.raw,
   226	                            metadata={"raw_channel": ch, "reading_kind": "temperature"},
   227	                        )
   228	                    )
   229	            except Exception as exc:
   230	                log.error("%s: KRDG? %d failed: %s", self.name, ch, exc)
   231	                channel_name = self._channel_labels.get(ch, f"CH{ch}")
   232	                readings.append(
   233	                    Reading.now(
   234	                        channel=channel_name,
   235	                        value=float("nan"),
   236	                        unit="K",
   237	                        instrument_id=self.name,
   238	                        status=ChannelStatus.SENSOR_ERROR,
   239	                        raw=None,
   240	                        metadata={"raw_channel": ch, "reading_kind": "temperature"},
   241	                    )
   242	                )
   243	        return readings
   244	
   245	    async def read_srdg_channels(self) -> list[Reading]:
   246	        if not self._connected:
   247	            raise RuntimeError(f"{self.name}: instrument is not connected")
   248	        if self.mock:
   249	            return self._mock_sensor_readings()
   250	
   251	        if self._use_per_channel_srdg:
   252	            return await self._read_srdg_per_channel()
   253	
   254	        raw_response = await self._transport.query("SRDG?")
   255	        log.debug("%s: SRDG? -> %s", self.name, raw_response)
   256	        readings = self._parse_response(raw_response, unit="sensor_unit", reading_kind="raw_sensor")
   257	        if len(readings) < 8:
   258	            self._srdg0_fail_count += 1
   259	            log.warning(
   260	                "%s: SRDG? returned %d values (expected 8), fallback #%d",
   261	                self.name,
   262	                len(readings),
   263	                self._srdg0_fail_count,
   264	            )
   265	            if self._srdg0_fail_count >= 3:
   266	                self._use_per_channel_srdg = True
   267	                log.warning(
   268	                    "%s: SRDG? failed %d times, switching to per-channel mode permanently",
   269	                    self.name,
   270	                    self._srdg0_fail_count,
   271	                )
   272	            return await self._read_srdg_per_channel()
   273	        self._srdg0_fail_count = 0
   274	        return readings
   275	
   276	    async def _read_srdg_per_channel(self) -> list[Reading]:
   277	        """Fallback: query each channel individually (SRDG? 1 .. SRDG? 8).
   278	
   279	        Periodically retries batch SRDG? to recover from transient failures.
   280	        """

===== src/cryodaq/drivers/instruments/keithley_2604b.py =====
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
   121	        await self.emergency_off()
   122	        await self._transport.close()
   123	        self._connected = False
   124	
   125	    async def read_channels(self) -> list[Reading]:
   126	        if not self._connected:
   127	            raise RuntimeError(f"{self.name}: instrument not connected")
   128	
   129	        if self.mock:
   130	            return self._mock_readings()
   131	
   132	        readings: list[Reading] = []
   133	        for smu_channel in SMU_CHANNELS:
   134	            runtime = self._channels[smu_channel]
   135	            try:
   136	                if not runtime.active:
   137	                    # Check output state — source may be OFF or left ON from
   138	                    # a previous session.  measure.iv() errors when output is OFF.
   139	                    output_raw = await self._transport.query(
   140	                        f"print({smu_channel}.source.output)", timeout_ms=3000
   141	                    )
   142	                    try:
   143	                        output_on = float(output_raw.strip()) > 0.5
   144	                    except ValueError:
   145	                        output_on = False
   146	
   147	                    if not output_on:
   148	                        readings.extend(
   149	                            self._build_channel_readings(
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
   186	                        if resistance > 0:
   187	                            target_v = math.sqrt(runtime.p_target * resistance)
   188	                            target_v = max(0.0, min(target_v, runtime.v_comp))
   189	
   190	                            # Slew rate limit
   191	                            current_v = self._last_v[smu_channel]
   192	                            delta_v = target_v - current_v
   193	                            if abs(delta_v) > MAX_DELTA_V_PER_STEP:
   194	                                delta_v = (
   195	                                    MAX_DELTA_V_PER_STEP if delta_v > 0 else -MAX_DELTA_V_PER_STEP
   196	                                )
   197	                                target_v = current_v + delta_v
   198	                                log.debug(
   199	                                    "Slew rate limited: delta=%.3f V, target=%.3f V",
   200	                                    delta_v,
   201	                                    target_v,
   202	                                )
   203	
   204	                            await self._transport.write(f"{smu_channel}.source.levelv = {target_v}")
   205	                            self._last_v[smu_channel] = target_v
   206	
   207	                readings.extend(
   208	                    self._build_channel_readings(
   209	                        smu_channel, voltage, current, extra_meta=extra_meta
   210	                    )
   211	                )
   212	            except OSError as exc:
   213	                # Transport-level error (USB disconnect, pipe broken) —
   214	                # mark disconnected so scheduler triggers reconnect.
   215	                log.error("%s: transport error on %s: %s", self.name, smu_channel, exc)
   216	                self._connected = False
   217	                raise
   218	            except Exception as exc:
   219	                log.error("%s: read failure on %s: %s", self.name, smu_channel, exc)
   220	                readings.extend(self._error_readings_for_channel(smu_channel))
   221	        return readings
   222	
   223	    async def start_source(
   224	        self,
   225	        channel: str,
   226	        p_target: float,
   227	        v_compliance: float,
   228	        i_compliance: float,
   229	    ) -> None:
   230	        smu_channel = normalize_smu_channel(channel)
   231	        runtime = self._channels[smu_channel]
   232	
   233	        if not self._connected:
   234	            raise RuntimeError(f"{self.name}: instrument not connected")
   235	        if p_target <= 0 or v_compliance <= 0 or i_compliance <= 0:
   236	            raise ValueError("P/V/I must be > 0")
   237	        if runtime.active:
   238	            raise RuntimeError(f"Channel {smu_channel} already active")
   239	
   240	        runtime.p_target = p_target
   241	        runtime.v_comp = v_compliance
   242	        runtime.i_comp = i_compliance
   243	
   244	        if self.mock:
   245	            runtime.active = True
   246	            return
   247	
   248	        # Configure source directly via VISA — no TSP script.
   249	        await self._transport.write(f"{smu_channel}.reset()")
   250	        await self._transport.write(f"{smu_channel}.source.func = {smu_channel}.OUTPUT_DCVOLTS")
   251	        await self._transport.write(f"{smu_channel}.source.autorangev = {smu_channel}.AUTORANGE_ON")
   252	        await self._transport.write(
   253	            f"{smu_channel}.measure.autorangei = {smu_channel}.AUTORANGE_ON"
   254	        )
   255	        await self._transport.write(f"{smu_channel}.source.limitv = {v_compliance}")
   256	        await self._transport.write(f"{smu_channel}.source.limiti = {i_compliance}")
   257	        await self._transport.write(f"{smu_channel}.source.levelv = 0")
   258	        await self._transport.write(f"{smu_channel}.source.output = {smu_channel}.OUTPUT_ON")
   259	        self._last_v[smu_channel] = 0.0
   260	        self._compliance_count[smu_channel] = 0
   261	        runtime.active = True
   262	
   263	    async def stop_source(self, channel: str) -> None:
   264	        smu_channel = normalize_smu_channel(channel)
   265	        runtime = self._channels[smu_channel]
   266	
   267	        if self.mock:
   268	            self._last_v[smu_channel] = 0.0
   269	            self._compliance_count[smu_channel] = 0
   270	            runtime.active = False
   271	            runtime.p_target = 0.0
   272	            return
   273	
   274	        if not self._connected:
   275	            return
   276	
   277	        await self._transport.write(f"{smu_channel}.source.levelv = 0")
   278	        await self._transport.write(f"{smu_channel}.source.output = {smu_channel}.OUTPUT_OFF")
   279	        await self._verify_output_off(smu_channel)
   280	        self._last_v[smu_channel] = 0.0

===== src/cryodaq/drivers/instruments/thyracont_vsp63d.py =====
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
   181	                log.debug("%s: MV00 probe OK: %s", self.name, resp_stripped)
   182	                return True
   183	        except Exception as exc:
   184	            log.debug("%s: MV00 probe failed: %s", self.name, exc)
   185	        return False
   186	
   187	    async def disconnect(self) -> None:
   188	        """Разорвать соединение с прибором (идемпотентно)."""
   189	        if not self._connected:
   190	            return
   191	        log.info("%s: отключение", self.name)
   192	        await self._transport.close()
   193	        self._connected = False
   194	
   195	    async def read_channels(self) -> list[Reading]:
   196	        """Считать давление командой ``MV00``.
   197	
   198	        Returns
   199	        -------
   200	        list[Reading]
   201	            Список из одного объекта :class:`~cryodaq.drivers.base.Reading`.
   202	            Единица измерения — миллибар (``"mbar"``).
   203	
   204	        Raises
   205	        ------
   206	        RuntimeError
   207	            Если прибор не подключён.
   208	        """
   209	        if not self._connected:
   210	            raise RuntimeError(f"{self.name}: прибор не подключён")
   211	
   212	        if self.mock:
   213	            return self._mock_readings()
   214	
   215	        if self._protocol_v1:
   216	            cmd = f"{self._address}M^"
   217	            raw_response = await self._transport.query(cmd)
   218	            log.debug("%s: %s → %s", self.name, cmd, raw_response.strip())
   219	            return [self._parse_v1_response(raw_response)]
   220	
   221	        raw_response = await self._transport.query("MV00")
   222	        log.debug("%s: MV00 → %s", self.name, raw_response.strip())
   223	        return [self._parse_response(raw_response)]
   224	
   225	    # ------------------------------------------------------------------
   226	    # Разбор ответа прибора
   227	    # ------------------------------------------------------------------
   228	
   229	    def _parse_response(self, response: str) -> Reading:
   230	        """Разобрать строку ответа ``"status,value\\r"`` в Reading.
   231	
   232	        Формат ответа: ``"<код_статуса>,<значение_давления>\\r"``, например::
   233	
   234	            0,1.234E-06\\r
   235	
   236	        Parameters
   237	        ----------
   238	        response:
   239	            Сырая строка ответа от прибора.
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

 succeeded in 0ms:

===== src/cryodaq/core/safety_manager.py =====
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
   181	
   182	        logger.info(
   183	            "SafetyManager config: %d critical channel patterns from %s",
   184	            len(patterns),
   185	            path,
   186	        )
   187	
   188	        try:
   189	            src_limits = raw.get("source_limits", {})
   190	            self._config = SafetyConfig(
   191	                critical_channels=patterns,
   192	                stale_timeout_s=float(raw.get("stale_timeout_s", 10.0)),
   193	                heartbeat_timeout_s=float(raw.get("heartbeat_timeout_s", 15.0)),
   194	                max_safety_backlog=int(raw.get("max_safety_backlog", 100)),
   195	                require_keithley_for_run=bool(raw.get("require_keithley_for_run", True)),
   196	                max_dT_dt_K_per_min=float(
   197	                    raw.get("rate_limits", {}).get("max_dT_dt_K_per_min", 5.0)
   198	                ),
   199	                require_reason=bool(raw.get("recovery", {}).get("require_reason", True)),
   200	                cooldown_before_rearm_s=float(
   201	                    raw.get("recovery", {}).get("cooldown_before_rearm_s", 60.0)
   202	                ),
   203	                max_power_w=float(src_limits.get("max_power_w", 5.0)),
   204	                max_voltage_v=float(src_limits.get("max_voltage_v", 40.0)),
   205	                max_current_a=float(src_limits.get("max_current_a", 1.0)),
   206	                scheduler_drain_timeout_s=float(raw.get("scheduler_drain_timeout_s", 5.0)),
   207	            )
   208	            self._keithley_patterns = [
   209	                re.compile(pattern) for pattern in raw.get("keithley_channels", [".*/smu.*"])
   210	            ]
   211	        except (ValueError, TypeError, KeyError, AttributeError) as exc:
   212	            raise SafetyConfigError(
   213	                f"safety.yaml at {path}: invalid config value — {type(exc).__name__}: {exc}"
   214	            ) from exc
   215	
   216	    async def start(self) -> None:
   217	        self._queue = self._broker.subscribe(
   218	            "safety_manager", maxsize=self._config.max_safety_backlog
   219	        )
   220	        self._broker.freeze()
   221	        self._collect_task = asyncio.create_task(self._collect_loop(), name="safety_collect")
   222	        self._monitor_task = asyncio.create_task(self._monitor_loop(), name="safety_monitor")
   223	        await self._publish_state("initial")
   224	        await self._publish_keithley_channel_states("initial")
   225	
   226	    async def stop(self) -> None:
   227	        if self._active_sources:
   228	            await self._safe_off("system stop", channels=set(self._active_sources))
   229	
   230	        for task in (self._collect_task, self._monitor_task):
   231	            if task and not task.done():
   232	                task.cancel()
   233	                try:
   234	                    await task
   235	                except asyncio.CancelledError:
   236	                    pass
   237	        self._collect_task = None
   238	        self._monitor_task = None
   239	
   240	    @property
   241	    def state(self) -> SafetyState:
   242	        return self._state
   243	
   244	    @property
   245	    def fault_reason(self) -> str:
   246	        return self._fault_reason
   247	
   248	    async def request_run(
   249	        self,
   250	        p_target: float,
   251	        v_comp: float,
   252	        i_comp: float,
   253	        *,
   254	        channel: str | None = None,
   255	    ) -> dict[str, Any]:
   256	        async with self._cmd_lock:
   257	            smu_channel = normalize_smu_channel(channel)
   258	
   259	            if self._state == SafetyState.FAULT_LATCHED:
   260	                return {

===== src/cryodaq/core/scheduler.py =====
     1	"""Scheduler — планировщик опроса приборов.
     2	
     3	Для каждого InstrumentDriver создаёт изолированную asyncio-задачу.
     4	Исключение: приборы на одной GPIB-шине группируются в один task
     5	и опрашиваются последовательно (NI GPIB-USB-HS не переносит
     6	параллельный доступ даже с asyncio.Lock + run_in_executor).
     7	
     8	Таймаут одного прибора не блокирует приборы на другой шине.
     9	При ошибке соединения — экспоненциальный backoff с переподключением.
    10	"""
    11	
    12	from __future__ import annotations
    13	
    14	import asyncio
    15	import logging
    16	from collections import defaultdict
    17	from dataclasses import dataclass, field
    18	from typing import Any
    19	
    20	from cryodaq.core.broker import DataBroker
    21	from cryodaq.drivers.base import InstrumentDriver
    22	
    23	logger = logging.getLogger(__name__)
    24	
    25	DEFAULT_POLL_INTERVAL_S = 1.0
    26	MAX_BACKOFF_S = 60.0
    27	INITIAL_BACKOFF_S = 1.0
    28	READ_TIMEOUT_S = 10.0
    29	
    30	# Standalone (non-GPIB) instrument disconnect backoff
    31	_STANDALONE_INITIAL_BACKOFF_S = 30.0
    32	_STANDALONE_MAX_BACKOFF_S = 300.0
    33	_DISCONNECT_TIMEOUT_S = 5.0
    34	
    35	_GPIB_PREFIX = "GPIB"
    36	
    37	
    38	@dataclass
    39	class InstrumentConfig:
    40	    """Конфигурация опроса одного прибора."""
    41	
    42	    driver: InstrumentDriver
    43	    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S
    44	    read_timeout_s: float = READ_TIMEOUT_S
    45	    enabled: bool = True
    46	    resource_str: str = ""
    47	
    48	
    49	@dataclass
    50	class _InstrumentState:
    51	    """Внутреннее состояние задачи опроса."""
    52	
    53	    config: InstrumentConfig
    54	    task: asyncio.Task[None] | None = None
    55	    consecutive_errors: int = 0
    56	    total_reads: int = 0
    57	    total_errors: int = 0
    58	    backoff_s: float = field(default=INITIAL_BACKOFF_S)
    59	
    60	
    61	def _gpib_bus_prefix(resource_str: str) -> str | None:
    62	    """Extract GPIB bus prefix (e.g. 'GPIB0') or None if not GPIB."""
    63	    if resource_str.upper().startswith(_GPIB_PREFIX):
    64	        return resource_str.split("::")[0]
    65	    return None
    66	
    67	
    68	class Scheduler:
    69	    """Планировщик: GPIB приборы на одной шине → один последовательный task.
    70	
    71	    Использование::
    72	
    73	        scheduler = Scheduler(broker)
    74	        scheduler.add(InstrumentConfig(driver=lakeshore1, resource_str="GPIB0::12::INSTR"))
    75	        scheduler.add(InstrumentConfig(driver=lakeshore2, resource_str="GPIB0::11::INSTR"))
    76	        scheduler.add(InstrumentConfig(driver=keithley, resource_str="USB0::..."))
    77	        await scheduler.start()
    78	        ...
    79	        await scheduler.stop()
    80	    """
    81	
    82	    def __init__(
    83	        self,
    84	        broker: DataBroker,
    85	        *,
    86	        safety_broker: Any | None = None,
    87	        sqlite_writer: Any | None = None,
    88	        adaptive_throttle: Any | None = None,
    89	        calibration_acquisition: Any | None = None,
    90	        drain_timeout_s: float = 5.0,
    91	    ) -> None:
    92	        self._broker = broker
    93	        self._safety_broker = safety_broker
    94	        self._sqlite_writer = sqlite_writer
    95	        self._adaptive_throttle = adaptive_throttle
    96	        self._calibration_acquisition = calibration_acquisition
    97	        self._drain_timeout_s = drain_timeout_s
    98	        self._instruments: dict[str, _InstrumentState] = {}
    99	        self._running = False
   100	        self._gpib_tasks: dict[str, asyncio.Task[None]] = {}
   101	
   102	    def add(self, config: InstrumentConfig) -> None:
   103	        """Зарегистрировать прибор. Вызывать до start()."""
   104	        name = config.driver.name
   105	        if name in self._instruments:
   106	            raise ValueError(f"Прибор '{name}' уже зарегистрирован")
   107	        self._instruments[name] = _InstrumentState(config=config)
   108	        logger.info("Прибор '%s' добавлен (интервал=%.1fs)", name, config.poll_interval_s)
   109	
   110	    async def _disconnect_driver(
   111	        self,
   112	        driver: InstrumentDriver,
   113	        *,
   114	        timeout_s: float = _DISCONNECT_TIMEOUT_S,
   115	        context: str = "",
   116	    ) -> None:
   117	        """Disconnect with a bounded wait so wedged transports do not hang recovery."""
   118	        try:
   119	            await asyncio.wait_for(driver.disconnect(), timeout=timeout_s)
   120	        except TimeoutError:
   121	            if context:
   122	                logger.warning(
   123	                    "Таймаут отключения '%s' за %.1fs (%s)",
   124	                    driver.name,
   125	                    timeout_s,
   126	                    context,
   127	                )
   128	            else:
   129	                logger.warning("Таймаут отключения '%s' за %.1fs", driver.name, timeout_s)
   130	        except Exception:
   131	            if context:
   132	                logger.exception("Ошибка отключения '%s' (%s)", driver.name, context)
   133	            else:
   134	                logger.exception("Ошибка отключения '%s'", driver.name)
   135	
   136	    async def _poll_loop(self, state: _InstrumentState) -> None:
   137	        """Цикл опроса одного прибора с reconnect и backoff."""
   138	        cfg = state.config
   139	        driver = cfg.driver
   140	        name = driver.name
   141	        loop = asyncio.get_event_loop()
   142	        next_deadline = loop.time() + cfg.poll_interval_s
   143	
   144	        while self._running:
   145	            if not driver.connected:
   146	                try:
   147	                    await driver.connect()
   148	                    state.consecutive_errors = 0
   149	                    state.backoff_s = INITIAL_BACKOFF_S
   150	                    logger.info("Прибор '%s' подключён", name)
   151	                except Exception:
   152	                    logger.exception("Не удалось подключить '%s'", name)
   153	                    await self._backoff(state)
   154	                    continue
   155	
   156	            try:
   157	                readings = await asyncio.wait_for(driver.safe_read(), timeout=cfg.read_timeout_s)
   158	                state.consecutive_errors = 0
   159	                state.backoff_s = INITIAL_BACKOFF_S
   160	                await self._process_readings(state, readings)
   161	            except TimeoutError:
   162	                state.consecutive_errors += 1
   163	                state.total_errors += 1
   164	                logger.warning(
   165	                    "Таймаут опроса '%s' (%.1fs), ошибок подряд: %d",
   166	                    name,
   167	                    cfg.read_timeout_s,
   168	                    state.consecutive_errors,
   169	                )
   170	                if state.consecutive_errors >= 3:
   171	                    logger.warning(
   172	                        "'%s': %d consecutive errors, disconnect + backoff",
   173	                        name,
   174	                        state.consecutive_errors,
   175	                    )
   176	                    await self._disconnect_driver(driver, context="standalone timeout recovery")
   177	                    state.backoff_s = max(state.backoff_s, _STANDALONE_INITIAL_BACKOFF_S)
   178	                    await self._backoff(state, max_s=_STANDALONE_MAX_BACKOFF_S)
   179	                    continue
   180	            except Exception:
   181	                state.consecutive_errors += 1
   182	                state.total_errors += 1
   183	                logger.warning(
   184	                    "Ошибка опроса '%s', ошибок подряд: %d", name, state.consecutive_errors
   185	                )
   186	                if state.consecutive_errors >= 3:
   187	                    logger.warning(
   188	                        "'%s': %d consecutive errors, disconnect + backoff",
   189	                        name,
   190	                        state.consecutive_errors,
   191	                    )
   192	                    await self._disconnect_driver(driver, context="standalone error recovery")
   193	                    state.backoff_s = max(state.backoff_s, _STANDALONE_INITIAL_BACKOFF_S)
   194	                    await self._backoff(state, max_s=_STANDALONE_MAX_BACKOFF_S)
   195	                    continue
   196	
   197	            next_deadline += cfg.poll_interval_s
   198	            now = loop.time()
   199	            if next_deadline < now:
   200	                missed = int((now - next_deadline) / cfg.poll_interval_s) + 1
   201	                next_deadline += missed * cfg.poll_interval_s
   202	            sleep_remaining = max(0, next_deadline - loop.time())
   203	            await asyncio.sleep(sleep_remaining)
   204	
   205	    async def _gpib_poll_loop(self, bus_prefix: str, states: list[_InstrumentState]) -> None:
   206	        """Последовательный опрос всех приборов на одной GPIB шине в одном task.
   207	
   208	        Гарантирует: ни в какой момент два run_in_executor вызова к одной GPIB
   209	        шине не выполняются параллельно. Один сбойный прибор не блокирует остальные.
   210	        """
   211	        poll_interval = max(s.config.poll_interval_s for s in states)
   212	        _CONNECT_TIMEOUT_S = 3.0
   213	        _POLL_TIMEOUT_S = 3.0
   214	        _RECONNECT_INTERVAL_S = 30.0
   215	        _PREVENTIVE_CLEAR_INTERVAL_S = 300.0
   216	        _IFC_COOLDOWN_S = 2.0
   217	        last_reconnect: dict[str, float] = {}
   218	        last_preventive_clear: dict[str, float] = {}
   219	        bus_error_count: int = 0  # consecutive errors across ALL devices on this bus
   220	
   221	        # Подключить все последовательно — skip failures
   222	        for state in states:
   223	            driver = state.config.driver
   224	            try:
   225	                await asyncio.wait_for(driver.connect(), timeout=_CONNECT_TIMEOUT_S)
   226	                state.consecutive_errors = 0
   227	                logger.info("Прибор '%s' подключён (GPIB bus %s)", driver.name, bus_prefix)
   228	            except Exception:
   229	                logger.warning(
   230	                    "Не удалось подключить '%s' на %s — skipping", driver.name, bus_prefix
   231	                )
   232	                driver._connected = False
   233	
   234	        loop = asyncio.get_event_loop()
   235	        next_deadline = loop.time() + poll_interval
   236	
   237	        while self._running:
   238	            now = loop.time()
   239	
   240	            for state in states:
   241	                driver = state.config.driver
   242	                name = driver.name
   243	
   244	                # Reconnect failed devices — rate-limited
   245	                if not driver.connected:
   246	                    last_try = last_reconnect.get(name, 0.0)
   247	                    if now - last_try < _RECONNECT_INTERVAL_S:
   248	                        continue
   249	                    last_reconnect[name] = now
   250	                    try:
   251	                        await asyncio.wait_for(driver.connect(), timeout=_CONNECT_TIMEOUT_S)
   252	                        state.consecutive_errors = 0
   253	                        logger.info("Прибор '%s' переподключён (GPIB bus %s)", name, bus_prefix)
   254	                    except Exception:
   255	                        logger.warning("Не удалось переподключить '%s' — skipping", name)
   256	                        driver._connected = False
   257	                        continue
   258	
   259	                # Preventive clear — every 5 minutes per device
   260	                last_clear = last_preventive_clear.get(name, 0.0)

===== src/cryodaq/storage/sqlite_writer.py =====
     1	"""SQLiteWriter — запись показаний в SQLite с WAL-режимом.
     2	
     3	Один файл на день: data_YYYY-MM-DD.db.
     4	Батчевая вставка каждую секунду (или при накоплении batch_size).
     5	Работает в отдельном потоке (sqlite3 не async), взаимодействие через asyncio.Queue.
     6	"""
     7	
     8	from __future__ import annotations
     9	
    10	import asyncio
    11	import json
    12	import logging
    13	import math
    14	import os
    15	import sqlite3
    16	from collections.abc import Awaitable, Callable
    17	from concurrent.futures import ThreadPoolExecutor
    18	from datetime import UTC, date, datetime
    19	from functools import partial
    20	from pathlib import Path
    21	from typing import Any
    22	
    23	from cryodaq.core.operator_log import OperatorLogEntry, normalize_operator_log_tags
    24	from cryodaq.drivers.base import ChannelStatus, Reading
    25	
    26	logger = logging.getLogger(__name__)
    27	
    28	SCHEMA_READINGS = """
    29	CREATE TABLE IF NOT EXISTS readings (
    30	    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    31	    timestamp   REAL    NOT NULL,
    32	    instrument_id TEXT  NOT NULL,
    33	    channel     TEXT    NOT NULL,
    34	    value       REAL    NOT NULL,
    35	    unit        TEXT    NOT NULL,
    36	    status      TEXT    NOT NULL
    37	);
    38	"""
    39	
    40	SCHEMA_SOURCE_DATA = """
    41	-- Reserved for future Keithley raw SMU buffer recording.
    42	-- Currently unused — Keithley data goes through standard Reading path.
    43	CREATE TABLE IF NOT EXISTS source_data (
    44	    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    45	    timestamp   TEXT    NOT NULL,
    46	    channel     TEXT    NOT NULL,
    47	    voltage     REAL,
    48	    current     REAL,
    49	    resistance  REAL,
    50	    power       REAL
    51	);
    52	"""
    53	
    54	INDEX_READINGS_TS = """
    55	CREATE INDEX IF NOT EXISTS idx_readings_ts ON readings (timestamp);
    56	"""
    57	
    58	INDEX_SOURCE_DATA_TS = """
    59	CREATE INDEX IF NOT EXISTS idx_source_data_ts ON source_data (timestamp);
    60	"""
    61	
    62	INDEX_CHANNEL_TS = """
    63	CREATE INDEX IF NOT EXISTS idx_channel_ts ON readings (channel, timestamp);
    64	"""
    65	
    66	SCHEMA_OPERATOR_LOG = """
    67	CREATE TABLE IF NOT EXISTS operator_log (
    68	    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    69	    timestamp     REAL    NOT NULL,
    70	    experiment_id TEXT,
    71	    author        TEXT    NOT NULL DEFAULT '',
    72	    source        TEXT    NOT NULL DEFAULT '',
    73	    message       TEXT    NOT NULL,
    74	    tags          TEXT    NOT NULL DEFAULT '[]'
    75	);
    76	"""
    77	
    78	INDEX_OPERATOR_LOG_TS = """
    79	CREATE INDEX IF NOT EXISTS idx_operator_log_ts ON operator_log (timestamp);
    80	"""
    81	
    82	INDEX_OPERATOR_LOG_EXPERIMENT = """
    83	CREATE INDEX IF NOT EXISTS idx_operator_log_experiment ON operator_log (experiment_id, timestamp);
    84	"""
    85	
    86	
    87	def _parse_timestamp(raw) -> datetime:
    88	    """Parse timestamp from REAL (float) or legacy TEXT (isoformat)."""
    89	    if isinstance(raw, (int, float)):
    90	        return datetime.fromtimestamp(raw, tz=UTC)
    91	    return datetime.fromisoformat(str(raw))
    92	
    93	
    94	_SQLITE_VERSION_CHECKED = False
    95	
    96	
    97	def _check_sqlite_version() -> None:
    98	    """Warn if running on a SQLite version affected by the March 2026 WAL-reset bug.
    99	
   100	    The bug affects SQLite versions in [3.7.0, 3.51.3) when multiple
   101	    connections across threads/processes write or checkpoint "at the same
   102	    instant". CryoDAQ uses WAL with multiple concurrent connections (writer,
   103	    history reader, web dashboard, reporting); upgrade to >= 3.51.3 in
   104	    production. See: https://www.sqlite.org/wal.html
   105	    """
   106	    global _SQLITE_VERSION_CHECKED
   107	    if _SQLITE_VERSION_CHECKED:
   108	        return
   109	    _SQLITE_VERSION_CHECKED = True
   110	    version = sqlite3.sqlite_version_info  # tuple, e.g. (3, 37, 2)
   111	    if (3, 7, 0) <= version < (3, 51, 3):
   112	        logger.warning(
   113	            "SQLite %d.%d.%d is affected by the March 2026 WAL-reset corruption "
   114	            "bug (range 3.7.0 – 3.51.2). CryoDAQ uses WAL with multiple "
   115	            "connections; upgrade to SQLite >= 3.51.3 in production. On Ubuntu "
   116	            "22.04 this means building libsqlite3 from source or bundling a "
   117	            "custom libsqlite3 in the PyInstaller build. "
   118	            "See https://www.sqlite.org/wal.html",
   119	            version[0],
   120	            version[1],
   121	            version[2],
   122	        )
   123	
   124	
   125	class SQLiteWriter:
   126	    """Асинхронный писатель показаний в SQLite.
   127	
   128	    Использование::
   129	
   130	        writer = SQLiteWriter(data_dir=Path("./data"))
   131	        await writer.start(queue)   # queue: asyncio.Queue[Reading]
   132	        ...
   133	        await writer.stop()
   134	    """
   135	
   136	    def __init__(
   137	        self,
   138	        data_dir: Path,
   139	        *,
   140	        flush_interval_s: float = 1.0,
   141	        batch_size: int = 500,
   142	    ) -> None:
   143	        self._data_dir = data_dir
   144	        self._flush_interval_s = flush_interval_s
   145	        self._batch_size = batch_size
   146	        self._conn: sqlite3.Connection | None = None
   147	        self._current_date: date | None = None
   148	        self._task: asyncio.Task[None] | None = None
   149	        self._running = False
   150	        self._total_written: int = 0
   151	        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sqlite_write")
   152	        self._read_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sqlite_read")
   153	        # Periodic explicit WAL checkpoint counter (DEEP_AUDIT_CC.md D.1).
   154	        self._checkpoint_counter = 0
   155	
   156	        # Disk-full graceful degradation (Phase 2a H.1).
   157	        # When the writer thread detects disk-full from sqlite3.OperationalError,
   158	        # it sets _disk_full=True and (optionally) schedules a callback on the
   159	        # engine event loop via run_coroutine_threadsafe so the SafetyManager
   160	        # can latch a fault. The flag is cleared by DiskMonitor when free
   161	        # space recovers, BUT the operator still has to acknowledge_fault to
   162	        # actually resume polling.
   163	        self._disk_full = False
   164	        self._loop: asyncio.AbstractEventLoop | None = None
   165	        self._persistence_failure_callback: Callable[[str], Awaitable[None]] | None = None
   166	
   167	        _check_sqlite_version()
   168	
   169	    def _db_path(self, day: date) -> Path:
   170	        return self._data_dir / f"data_{day.isoformat()}.db"
   171	
   172	    # ------------------------------------------------------------------
   173	    # Disk-full graceful degradation (Phase 2a H.1)
   174	    # ------------------------------------------------------------------
   175	    @property
   176	    def is_disk_full(self) -> bool:
   177	        """True when the most recent write hit a disk-full / out-of-space error."""
   178	        return self._disk_full
   179	
   180	    def clear_disk_full(self) -> None:
   181	        """Clear the disk-full flag.
   182	
   183	        Called by DiskMonitor when free space recovers above the threshold.
   184	        Note: this does NOT auto-resume polling — the SafetyManager has
   185	        already latched a fault, and the operator must acknowledge_fault
   186	        explicitly. This is a deliberate guard against disk-space flapping.
   187	        """
   188	        if self._disk_full:
   189	            logger.warning(
   190	                "Disk space recovered — clearing _disk_full flag. "
   191	                "SafetyManager fault remains latched until operator acknowledge."
   192	            )
   193	            self._disk_full = False
   194	
   195	    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
   196	        """Bind the writer to an event loop so the executor thread can
   197	        schedule the persistence-failure callback on it."""
   198	        self._loop = loop
   199	
   200	    def set_persistence_failure_callback(self, callback: Callable[[str], Awaitable[None]]) -> None:
   201	        """Register an async callback for persistence failures (disk full etc).
   202	
   203	        The callback is awaited via :func:`asyncio.run_coroutine_threadsafe`
   204	        from the writer thread, so it lands on the engine event loop where
   205	        SafetyManager.on_persistence_failure can latch a fault.
   206	        """
   207	        self._persistence_failure_callback = callback
   208	
   209	    def _signal_persistence_failure(self, reason: str) -> None:
   210	        """Schedule persistence-failure callback on the engine event loop.
   211	
   212	        Runs in the writer thread (called from _write_day_batch) — must NOT
   213	        block. We use run_coroutine_threadsafe and intentionally do NOT await
   214	        the resulting Future, because the writer thread does not have an
   215	        event loop of its own.
   216	        """
   217	        if self._persistence_failure_callback is None or self._loop is None:
   218	            return
   219	        try:
   220	            asyncio.run_coroutine_threadsafe(
   221	                self._persistence_failure_callback(reason),
   222	                self._loop,
   223	            )
   224	        except Exception as exc:
   225	            logger.error("Failed to schedule persistence_failure callback: %s", exc)
   226	
   227	    def _ensure_connection(self, day: date) -> sqlite3.Connection:
   228	        """Открыть/переоткрыть БД если сменился день."""
   229	        if self._conn is not None and self._current_date == day:
   230	            return self._conn
   231	        if self._conn is not None:
   232	            logger.info("Смена дня: закрываю %s", self._db_path(self._current_date))
   233	            # Final WAL checkpoint at rotation (DEEP_AUDIT_CC.md D.1, H.2).
   234	            try:
   235	                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
   236	                self._conn.commit()
   237	            except sqlite3.OperationalError as exc:
   238	                logger.warning("Final WAL checkpoint at rotation failed: %s", exc)
   239	            self._conn.close()
   240	        db_path = self._db_path(day)
   241	        self._data_dir.mkdir(parents=True, exist_ok=True)
   242	        conn = sqlite3.connect(str(db_path), timeout=10, check_same_thread=False)
   243	        # WAL with explicit checkpoint policy (DEEP_AUDIT_CC.md D.1).
   244	        # Default autocheckpoint (1000 pages) can starve under concurrent
   245	        # readers. See https://www.sqlite.org/wal.html
   246	        result = conn.execute("PRAGMA journal_mode=WAL;").fetchone()
   247	        actual_mode = (result[0] if result else "").lower()
   248	        if actual_mode != "wal":
   249	            raise RuntimeError(
   250	                f"SQLite WAL mode could not be enabled at {db_path}. "
   251	                f"PRAGMA journal_mode returned {actual_mode!r}. "
   252	                f"This may indicate an unsupported filesystem (network share, "
   253	                f"WSL with DrvFs, or read-only mount). CryoDAQ requires WAL "
   254	                f"for cross-process read concurrency. Refusing to start."
   255	            )
   256	        # synchronous=NORMAL loses last ~1s on power loss but gives ~10x
   257	        # throughput. Production deployments must be on a UPS. If no UPS,
   258	        # set CRYODAQ_SQLITE_SYNC=FULL.
   259	        sync_mode = os.environ.get("CRYODAQ_SQLITE_SYNC", "NORMAL").upper()
   260	        if sync_mode not in ("NORMAL", "FULL"):

===== src/cryodaq/core/alarm_v2.py =====
     1	"""AlarmEngine v2 — физически обоснованные алармы с composite, rate, stale conditions.
     2	
     3	Компоненты:
     4	  AlarmEvent       — событие срабатывания аларма
     5	  PhaseProvider    — интерфейс для получения текущей фазы эксперимента
     6	  SetpointProvider — интерфейс для получения setpoints
     7	  AlarmEvaluator   — вычисляет условие аларма → AlarmEvent | None
     8	  AlarmStateManager — управляет состоянием (active/cleared), гистерезис, dedup
     9	
    10	Физическое обоснование: docs/alarm_tz_physics_v3.md
    11	"""
    12	
    13	from __future__ import annotations
    14	
    15	import logging
    16	import time
    17	from collections import deque
    18	from dataclasses import dataclass
    19	from typing import TYPE_CHECKING, Any, Literal
    20	
    21	if TYPE_CHECKING:
    22	    from cryodaq.core.channel_state import ChannelStateTracker
    23	    from cryodaq.core.rate_estimator import RateEstimator
    24	
    25	logger = logging.getLogger(__name__)
    26	
    27	
    28	# ---------------------------------------------------------------------------
    29	# AlarmEvent
    30	# ---------------------------------------------------------------------------
    31	
    32	
    33	@dataclass
    34	class AlarmEvent:
    35	    """Событие срабатывания аларма."""
    36	
    37	    alarm_id: str
    38	    level: str  # "INFO" | "WARNING" | "CRITICAL"
    39	    message: str
    40	    triggered_at: float  # unix timestamp
    41	    channels: list[str]  # каналы-участники
    42	    values: dict[str, float]  # channel → значение на момент срабатывания
    43	    acknowledged: bool = False
    44	    acknowledged_at: float = 0.0
    45	    acknowledged_by: str = ""
    46	
    47	
    48	# ---------------------------------------------------------------------------
    49	# AlarmTransition
    50	# ---------------------------------------------------------------------------
    51	
    52	AlarmTransition = Literal["TRIGGERED", "CLEARED"]
    53	
    54	
    55	# ---------------------------------------------------------------------------
    56	# Provider protocols (duck-typed, без runtime Protocol overhead)
    57	# ---------------------------------------------------------------------------
    58	
    59	
    60	class PhaseProvider:
    61	    """Базовый провайдер фазы — заглушка для тестов."""
    62	
    63	    def get_current_phase(self) -> str | None:
    64	        return None
    65	
    66	    def get_phase_elapsed_s(self) -> float:
    67	        return 0.0
    68	
    69	
    70	class SetpointProvider:
    71	    """Базовый провайдер setpoints — заглушка для тестов."""
    72	
    73	    def __init__(self, defaults: dict[str, float] | None = None) -> None:
    74	        self._defaults: dict[str, float] = defaults or {}
    75	
    76	    def get(self, key: str) -> float:
    77	        return self._defaults.get(key, 0.0)
    78	
    79	
    80	# ---------------------------------------------------------------------------
    81	# AlarmEvaluator
    82	# ---------------------------------------------------------------------------
    83	
    84	_DEFAULT_RATE_WINDOW_S = 120.0
    85	
    86	
    87	class AlarmEvaluator:
    88	    """Вычисляет условие аларма по текущему состоянию системы.
    89	
    90	    Параметры
    91	    ----------
    92	    state:
    93	        ChannelStateTracker с текущими значениями каналов.
    94	    rate:
    95	        RateEstimator с оценками dX/dt.
    96	    phase_provider:
    97	        Провайдер текущей фазы эксперимента.
    98	    setpoint_provider:
    99	        Провайдер setpoints.
   100	    """
   101	
   102	    def __init__(
   103	        self,
   104	        state: ChannelStateTracker,
   105	        rate: RateEstimator,
   106	        phase_provider: PhaseProvider,
   107	        setpoint_provider: SetpointProvider,
   108	    ) -> None:
   109	        self._state = state
   110	        self._rate = rate
   111	        self._phase = phase_provider
   112	        self._setpoint = setpoint_provider
   113	
   114	    def evaluate(self, alarm_id: str, alarm_config: dict[str, Any]) -> AlarmEvent | None:
   115	        """Проверить одну alarm-конфигурацию. None = не сработал."""
   116	        alarm_type = alarm_config.get("alarm_type")
   117	        try:
   118	            if alarm_type == "threshold":
   119	                return self._eval_threshold(alarm_id, alarm_config)
   120	            elif alarm_type == "composite":
   121	                return self._eval_composite(alarm_id, alarm_config)
   122	            elif alarm_type == "rate":
   123	                return self._eval_rate(alarm_id, alarm_config)
   124	            elif alarm_type == "stale":
   125	                return self._eval_stale(alarm_id, alarm_config)
   126	            else:
   127	                logger.warning("Неизвестный alarm_type=%r для %s", alarm_type, alarm_id)
   128	                return None
   129	        except Exception as exc:
   130	            logger.error("Ошибка evaluate %s: %s", alarm_id, exc, exc_info=True)
   131	            return None
   132	
   133	    # ------------------------------------------------------------------
   134	    # threshold
   135	    # ------------------------------------------------------------------
   136	
   137	    def _eval_threshold(self, alarm_id: str, cfg: dict) -> AlarmEvent | None:
   138	        check = cfg.get("check", "above")
   139	        channels = self._resolve_channels(cfg)
   140	        level = cfg.get("level", "WARNING")
   141	        message_tmpl = cfg.get("message", f"Alarm {alarm_id}")
   142	
   143	        for ch in channels:
   144	            triggered, value = self._check_threshold_channel(ch, check, cfg)
   145	            if triggered:
   146	                msg = self._format_message(message_tmpl, channel=ch, value=value)
   147	                return AlarmEvent(
   148	                    alarm_id=alarm_id,
   149	                    level=level,
   150	                    message=msg,
   151	                    triggered_at=time.time(),
   152	                    channels=[ch],
   153	                    values={ch: value},
   154	                )
   155	        return None
   156	
   157	    def _check_threshold_channel(self, channel: str, check: str, cfg: dict) -> tuple[bool, float]:
   158	        """Возвращает (сработал, значение)."""
   159	        if check == "fault_count_in_window":
   160	            count = self._state.get_fault_count(channel)
   161	            min_count = cfg.get("min_fault_count", 1)
   162	            return count >= min_count, float(count)
   163	
   164	        state = self._state.get(channel)
   165	        if state is None:
   166	            return False, 0.0
   167	        value = state.value
   168	
   169	        if check == "above":
   170	            return value > cfg["threshold"], value
   171	        elif check == "below":
   172	            return value < cfg["threshold"], value
   173	        elif check == "outside_range":
   174	            r = cfg["range"]
   175	            return (value < r[0] or value > r[1]), value
   176	        elif check == "deviation_from_setpoint":
   177	            setpoint = self._setpoint.get(cfg["setpoint_source"])
   178	            return abs(value - setpoint) > cfg["threshold"], value
   179	        else:
   180	            logger.warning("Неизвестный threshold check=%r", check)
   181	            return False, value
   182	
   183	    # ------------------------------------------------------------------
   184	    # composite
   185	    # ------------------------------------------------------------------
   186	
   187	    def _eval_composite(self, alarm_id: str, cfg: dict) -> AlarmEvent | None:
   188	        operator = cfg.get("operator", "AND")
   189	        conditions = cfg.get("conditions", [])
   190	        level = cfg.get("level", "WARNING")
   191	        message = cfg.get("message", f"Alarm {alarm_id}")
   192	
   193	        results = [self._eval_condition(c) for c in conditions]
   194	
   195	        if operator == "AND":
   196	            fired = all(results)
   197	        elif operator == "OR":
   198	            fired = any(results)
   199	        else:
   200	            logger.warning("Неизвестный composite operator=%r", operator)
   201	            return None
   202	
   203	        if not fired:
   204	            return None
   205	
   206	        # Collect channels and values
   207	        channels: list[str] = []
   208	        values: dict[str, float] = {}
   209	        for cond in conditions:
   210	            for ch in self._resolve_channels(cond):
   211	                state = self._state.get(ch)
   212	                if state and ch not in channels:
   213	                    channels.append(ch)
   214	                    values[ch] = state.value
   215	
   216	        return AlarmEvent(
   217	            alarm_id=alarm_id,
   218	            level=level,
   219	            message=str(message),
   220	            triggered_at=time.time(),
   221	            channels=channels,
   222	            values=values,
   223	        )
   224	
   225	    def _eval_condition(self, cond: dict) -> bool:
   226	        """Вычислить одно sub-condition → bool."""
   227	        check = cond.get("check", "above")
   228	
   229	        if check == "any_below":
   230	            channels = self._resolve_channels(cond)
   231	            threshold = cond["threshold"]
   232	            return any(
   233	                (s := self._state.get(ch)) is not None and s.value < threshold for ch in channels
   234	            )
   235	
   236	        elif check == "any_above":
   237	            channels = self._resolve_channels(cond)
   238	            threshold = cond["threshold"]
   239	            return any(
   240	                (s := self._state.get(ch)) is not None and s.value > threshold for ch in channels
   241	            )
   242	
   243	        elif check == "above":
   244	            ch = cond.get("channel")
   245	            if not ch:
   246	                return False
   247	            # Special: phase_elapsed_s
   248	            if ch == "phase_elapsed_s":
   249	                elapsed = self._phase.get_phase_elapsed_s()
   250	                return elapsed > cond["threshold"]
   251	            state = self._state.get(ch)
   252	            return state is not None and state.value > cond["threshold"]
   253	
   254	        elif check == "below":
   255	            ch = cond.get("channel")
   256	            if not ch:
   257	                return False
   258	            state = self._state.get(ch)
   259	            return state is not None and state.value < cond["threshold"]
   260	

===== src/cryodaq/core/alarm_config.py =====
     1	"""AlarmConfig — загрузка и парсинг конфигурации алармов v3.
     2	
     3	Читает alarms_v3.yaml и возвращает:
     4	  - EngineConfig    — параметры движка (rate_window_s, setpoints…)
     5	  - list[AlarmConfig] — плоский список всех алармов с фазовым фильтром
     6	"""
     7	
     8	from __future__ import annotations
     9	
    10	import copy
    11	from dataclasses import dataclass, field
    12	from pathlib import Path
    13	from typing import Any
    14	
    15	import yaml
    16	
    17	
    18	class AlarmConfigError(RuntimeError):
    19	    """Raised when alarms_v3.yaml cannot be loaded in a fail-closed manner.
    20	
    21	    Distinct class so engine startup maps it to config exit code
    22	    instead of generic runtime crash.
    23	    """
    24	
    25	
    26	# ---------------------------------------------------------------------------
    27	# Dataclasses
    28	# ---------------------------------------------------------------------------
    29	
    30	
    31	@dataclass
    32	class SetpointDef:
    33	    """Описание одного setpoint из секции engine.setpoints."""
    34	
    35	    key: str
    36	    source: str  # "experiment_metadata" | "constant"
    37	    default: float
    38	    unit: str = "K"
    39	
    40	
    41	@dataclass
    42	class EngineConfig:
    43	    """Параметры движка алармов из секции engine."""
    44	
    45	    poll_interval_s: float = 2.0
    46	    rate_window_s: float = 120.0
    47	    rate_min_points: int = 60
    48	    rate_method: str = "linear_fit"
    49	    setpoints: dict[str, SetpointDef] = field(default_factory=dict)
    50	
    51	
    52	@dataclass
    53	class AlarmConfig:
    54	    """Одна alarm-запись, готовая к передаче в AlarmEvaluator.
    55	
    56	    Атрибуты
    57	    ----------
    58	    alarm_id:
    59	        Уникальный идентификатор аларма.
    60	    config:
    61	        Словарь конфигурации (alarm_type, check, threshold, …).
    62	        channel_group уже раскрыт → channels list.
    63	    phase_filter:
    64	        None — работает всегда (global alarm).
    65	        list[str] — только при активной фазе из этого списка.
    66	    notify:
    67	        Список каналов уведомлений: "gui", "telegram", "sound".
    68	    """
    69	
    70	    alarm_id: str
    71	    config: dict[str, Any]
    72	    phase_filter: list[str] | None = None
    73	    notify: list[str] = field(default_factory=list)
    74	
    75	
    76	# ---------------------------------------------------------------------------
    77	# Loader
    78	# ---------------------------------------------------------------------------
    79	
    80	
    81	def load_alarm_config(
    82	    path: str | Path | None = None,
    83	) -> tuple[EngineConfig, list[AlarmConfig]]:
    84	    """Загрузить alarms_v3.yaml → (EngineConfig, list[AlarmConfig]).
    85	
    86	    Если path не задан, ищет config/alarms_v3.yaml рядом с этим модулем
    87	    (поднимаясь до корня пакета).
    88	
    89	    Raises AlarmConfigError if file is missing, malformed, non-mapping,
    90	    or contains coercion errors in alarm definitions.
    91	    """
    92	    if path is None:
    93	        path = _find_default_config()
    94	        if path is None:
    95	            raise AlarmConfigError(
    96	                "alarms_v3.yaml not found: no path provided and no default "
    97	                "config located via standard search. Refusing to start alarm "
    98	                "engine without alarm configuration."
    99	            )
   100	    path = Path(path)
   101	    if not path.exists():
   102	        raise AlarmConfigError(
   103	            f"alarms_v3.yaml not found at {path} — refusing to start "
   104	            f"alarm engine without alarm configuration"
   105	        )
   106	
   107	    try:
   108	        with open(path, encoding="utf-8") as f:
   109	            raw = yaml.safe_load(f)
   110	    except yaml.YAMLError as exc:
   111	        raise AlarmConfigError(f"alarms_v3.yaml at {path}: YAML parse error — {exc}") from exc
   112	
   113	    if not isinstance(raw, dict):
   114	        raise AlarmConfigError(
   115	            f"alarms_v3.yaml at {path} is malformed (expected mapping, got {type(raw).__name__})"
   116	        )
   117	
   118	    channel_groups: dict[str, list[str]] = raw.get("channel_groups", {})
   119	    try:
   120	        engine_cfg = _parse_engine_config(raw.get("engine", {}))
   121	        alarms: list[AlarmConfig] = []
   122	
   123	        # --- Global alarms ---
   124	        for alarm_id, alarm_raw in raw.get("global_alarms", {}).items():
   125	            cfg = _expand_alarm(alarm_id, alarm_raw, channel_groups)
   126	            if cfg is not None:
   127	                alarms.append(cfg)
   128	
   129	        # --- Phase alarms ---
   130	        for phase_name, phase_dict in raw.get("phase_alarms", {}).items():
   131	            if not isinstance(phase_dict, dict):
   132	                continue
   133	            for alarm_id, alarm_raw in phase_dict.items():
   134	                cfg = _expand_alarm(alarm_id, alarm_raw, channel_groups, phase_filter=[phase_name])
   135	                if cfg is not None:
   136	                    alarms.append(cfg)
   137	    except (ValueError, TypeError, KeyError, AttributeError) as exc:
   138	        raise AlarmConfigError(
   139	            f"alarms_v3.yaml at {path}: invalid config value — {type(exc).__name__}: {exc}"
   140	        ) from exc
   141	
   142	    return engine_cfg, alarms
   143	
   144	
   145	# ---------------------------------------------------------------------------
   146	# Internal helpers
   147	# ---------------------------------------------------------------------------
   148	
   149	
   150	def _parse_engine_config(raw: dict) -> EngineConfig:
   151	    setpoints: dict[str, SetpointDef] = {}
   152	    for key, sp_raw in raw.get("setpoints", {}).items():
   153	        setpoints[key] = SetpointDef(
   154	            key=key,
   155	            source=sp_raw.get("source", "constant"),
   156	            default=float(sp_raw.get("default", 0.0)),
   157	            unit=sp_raw.get("unit", "K"),
   158	        )
   159	    return EngineConfig(
   160	        poll_interval_s=float(raw.get("poll_interval_s", 2.0)),
   161	        rate_window_s=float(raw.get("rate_window_s", 120.0)),
   162	        rate_min_points=int(raw.get("rate_min_points", 60)),
   163	        rate_method=str(raw.get("rate_method", "linear_fit")),
   164	        setpoints=setpoints,
   165	    )
   166	
   167	
   168	def _expand_alarm(
   169	    alarm_id: str,
   170	    alarm_raw: Any,
   171	    channel_groups: dict[str, list[str]],
   172	    phase_filter: list[str] | None = None,
   173	) -> AlarmConfig | None:
   174	    """Создать AlarmConfig из raw YAML-словаря, раскрыв channel_group."""
   175	    if not isinstance(alarm_raw, dict):
   176	        return None
   177	
   178	    cfg = copy.deepcopy(alarm_raw)
   179	    notify: list[str] = cfg.pop("notify", []) or []
   180	    # Remove non-evaluator keys
   181	    for key in ("gui_action", "side_effect"):
   182	        cfg.pop(key, None)
   183	
   184	    # Expand channel_group → channels
   185	    _expand_channel_group(cfg, channel_groups)
   186	
   187	    # Expand channel_group inside composite conditions
   188	    for cond in cfg.get("conditions", []):
   189	        if isinstance(cond, dict):
   190	            _expand_channel_group(cond, channel_groups)
   191	
   192	    return AlarmConfig(
   193	        alarm_id=alarm_id,
   194	        config=cfg,
   195	        phase_filter=phase_filter,
   196	        notify=notify if isinstance(notify, list) else [notify],
   197	    )
   198	
   199	
   200	def _expand_channel_group(cfg: dict, groups: dict[str, list[str]]) -> None:
   201	    """Заменить channel_group → channels in-place."""
   202	    group_name = cfg.pop("channel_group", None)
   203	    if group_name and group_name in groups:
   204	        cfg["channels"] = list(groups[group_name])
   205	
   206	
   207	def _find_default_config() -> Path | None:
   208	    """Найти config/alarms_v3.yaml, поднимаясь от текущего файла."""
   209	    here = Path(__file__).resolve()
   210	    for parent in here.parents:
   211	        candidate = parent / "config" / "alarms_v3.yaml"
   212	        if candidate.exists():
   213	            return candidate
   214	    return None

===== src/cryodaq/analytics/base_plugin.py =====
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

===== src/cryodaq/analytics/plugin_loader.py =====
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

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/core/zmq_bridge.py | sed -n '1,240p'
nl -ba src/cryodaq/core/zmq_subprocess.py | sed -n '1,280p'" in /Users/vladimir/Projects/cryodaq
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
   181	            try:
   182	                payload = _pack_reading(reading)
   183	                await self._socket.send_multipart([self._topic, payload])
   184	                self._total_sent += 1
   185	            except Exception:
   186	                logger.exception("Ошибка отправки ZMQ")
   187	
   188	    async def start(self, queue: asyncio.Queue[Reading]) -> None:
   189	        self._ctx = zmq.asyncio.Context()
   190	        self._socket = self._ctx.socket(zmq.PUB)
   191	        # Phase 2b H.4: LINGER=0 so the socket doesn't hold the port open
   192	        # after close — relevant on Windows where TIME_WAIT can keep
   193	        # 5555 occupied for 240s after a SIGKILL'd engine.
   194	        self._socket.setsockopt(zmq.LINGER, 0)
   195	        # IV.6: TCP_KEEPALIVE previously added here on the idle-reap
   196	        # hypothesis (commit f5f9039). Codex revised analysis disproved
   197	        # that — Ubuntu 120 s deterministic failure with default
   198	        # tcp_keepalive_time=7200 s rules out kernel reaping. Keepalive
   199	        # reverted on the command path (REQ + REP); retained on the
   200	        # SUB drain path in zmq_subprocess.sub_drain_loop as an
   201	        # orthogonal safeguard for long between-experiment pauses.
   202	        _bind_with_retry(self._socket, self._address)
   203	        self._running = True
   204	        self._task = asyncio.create_task(self._publish_loop(queue), name="zmq_publisher")
   205	        logger.info("ZMQPublisher запущен: %s", self._address)
   206	
   207	    async def stop(self) -> None:
   208	        self._running = False
   209	        if self._task:
   210	            self._task.cancel()
   211	            try:
   212	                await self._task
   213	            except asyncio.CancelledError:
   214	                pass
   215	            self._task = None
   216	        if self._socket:
   217	            self._socket.close(linger=0)
   218	            self._socket = None
   219	        if self._ctx:
   220	            self._ctx.term()
   221	            self._ctx = None
   222	        logger.info("ZMQPublisher остановлен (отправлено: %d)", self._total_sent)
   223	
   224	
   225	class ZMQSubscriber:
   226	    """SUB-сокет: GUI-процесс подписывается на поток данных от engine.
   227	
   228	    Использование::
   229	
   230	        async def on_reading(r: Reading):
   231	            print(r.channel, r.value)
   232	
   233	        sub = ZMQSubscriber("tcp://127.0.0.1:5555", callback=on_reading)
   234	        await sub.start()
   235	        ...
   236	        await sub.stop()
   237	    """
   238	
   239	    def __init__(
   240	        self,
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
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/core/scheduler.py | sed -n '260,430p'
nl -ba src/cryodaq/storage/sqlite_writer.py | sed -n '1,260p'
nl -ba src/cryodaq/storage/sqlite_writer.py | sed -n '260,520p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   260	                last_clear = last_preventive_clear.get(name, 0.0)
   261	                if now - last_clear > _PREVENTIVE_CLEAR_INTERVAL_S:
   262	                    transport = getattr(driver, "_transport", None)
   263	                    if transport is not None and hasattr(transport, "clear_bus"):
   264	                        try:
   265	                            await asyncio.wait_for(transport.clear_bus(), timeout=2.0)
   266	                            last_preventive_clear[name] = now
   267	                        except Exception:
   268	                            pass
   269	
   270	                # Poll
   271	                try:
   272	                    readings = await asyncio.wait_for(driver.safe_read(), timeout=_POLL_TIMEOUT_S)
   273	                    await self._process_readings(state, readings)
   274	                    bus_error_count = 0  # reset on success
   275	                except Exception as exc:
   276	                    state.consecutive_errors += 1
   277	                    state.total_errors += 1
   278	                    bus_error_count += 1
   279	                    logger.warning(
   280	                        "Ошибка опроса '%s': %s (device: %d, bus: %d)",
   281	                        name,
   282	                        exc,
   283	                        state.consecutive_errors,
   284	                        bus_error_count,
   285	                    )
   286	
   287	                    transport = getattr(driver, "_transport", None)
   288	
   289	                    if bus_error_count <= 2:
   290	                        # Level 1: SDC on the specific device
   291	                        if transport is not None and hasattr(transport, "clear_bus"):
   292	                            try:
   293	                                await asyncio.wait_for(transport.clear_bus(), timeout=2.0)
   294	                            except Exception:
   295	                                logger.warning("SDC failed after '%s' error", name)
   296	                    elif bus_error_count <= 5:
   297	                        # Level 2: IFC — reset entire bus
   298	                        if transport is not None and hasattr(transport, "send_ifc"):
   299	                            try:
   300	                                await asyncio.wait_for(transport.send_ifc(), timeout=3.0)
   301	                            except Exception:
   302	                                logger.warning("IFC failed on bus %s", bus_prefix)
   303	                            await asyncio.sleep(_IFC_COOLDOWN_S)
   304	                            # After IFC, all devices need reconnect
   305	                            for s in states:
   306	                                await self._disconnect_driver(
   307	                                    s.config.driver,
   308	                                    context=f"GPIB IFC recovery {bus_prefix}",
   309	                                )
   310	                                s.config.driver._connected = False
   311	                            break  # restart the for-loop (all devices disconnected)
   312	                    else:
   313	                        # Level 3: Close and reopen ResourceManager
   314	                        logger.error(
   315	                            "GPIB bus %s: %d consecutive errors, resetting ResourceManager",
   316	                            bus_prefix,
   317	                            bus_error_count,
   318	                        )
   319	                        from cryodaq.drivers.transport.gpib import GPIBTransport
   320	
   321	                        GPIBTransport.close_all_managers()
   322	                        for s in states:
   323	                            s.config.driver._connected = False
   324	                        bus_error_count = 0
   325	                        break  # restart the for-loop
   326	
   327	                    if state.consecutive_errors >= 3:
   328	                        logger.warning("'%s': 3+ ошибок, disconnect + skip", name)
   329	                        await self._disconnect_driver(
   330	                            driver,
   331	                            context=f"GPIB error recovery {bus_prefix}",
   332	                        )
   333	                        driver._connected = False
   334	
   335	            next_deadline += poll_interval
   336	            now = loop.time()
   337	            if next_deadline < now:
   338	                missed = int((now - next_deadline) / poll_interval) + 1
   339	                next_deadline += missed * poll_interval
   340	            sleep_remaining = max(0, next_deadline - loop.time())
   341	            await asyncio.sleep(sleep_remaining)
   342	
   343	    async def _process_readings(self, state: _InstrumentState, readings: list[Any]) -> None:
   344	        """Persist, calibrate, and publish readings — shared by both loop types."""
   345	        driver = state.config.driver
   346	        name = driver.name
   347	
   348	        # Disk-full graceful degradation (Phase 2a H.1).
   349	        # If the writer has detected disk-full, skip the entire pipeline:
   350	        # we cannot persist (so persistence-first invariant blocks publish),
   351	        # and SafetyManager has already latched a fault via the writer's
   352	        # callback. Returning here keeps the loop alive (so when disk
   353	        # recovers and the operator acknowledges, polling resumes cleanly)
   354	        # without spamming CRITICAL logs.
   355	        if self._sqlite_writer is not None and getattr(self._sqlite_writer, "is_disk_full", False):
   356	            return
   357	
   358	        persisted_readings = list(readings)
   359	        if self._adaptive_throttle is not None:
   360	            persisted_readings = self._adaptive_throttle.filter_for_archive(readings)
   361	        state.total_reads += 1
   362	        state.consecutive_errors = 0
   363	        state.backoff_s = INITIAL_BACKOFF_S
   364	
   365	        # Step 1a: If calibration acquisition active, read SRDG BEFORE persisting
   366	        # so KRDG+SRDG can be written atomically in one transaction (H.10).
   367	        srdg_to_persist: list = []
   368	        srdg_pending_state = None
   369	        if (
   370	            self._calibration_acquisition is not None
   371	            and self._calibration_acquisition.is_active
   372	            and hasattr(driver, "read_srdg_channels")
   373	        ):
   374	            try:
   375	                srdg = await driver.read_srdg_channels()
   376	                srdg_to_persist, srdg_pending_state = (
   377	                    self._calibration_acquisition.prepare_srdg_readings(readings, srdg)
   378	                )
   379	            except Exception:
   380	                logger.warning(
   381	                    "Failed to read SRDG for calibration on '%s'",
   382	                    name,
   383	                    exc_info=True,
   384	                )
   385	
   386	        # Step 1b: Persist KRDG + SRDG atomically in one transaction
   387	        combined = list(persisted_readings) + srdg_to_persist
   388	        if self._sqlite_writer is not None and combined:
   389	            try:
   390	                await self._sqlite_writer.write_immediate(combined)
   391	            except Exception:
   392	                logger.exception(
   393	                    "CRITICAL: Ошибка записи '%s' — данные НЕ отправлены подписчикам",
   394	                    name,
   395	                )
   396	                state.consecutive_errors += 1
   397	                state.total_errors += 1
   398	                return
   399	
   400	            # If write_immediate silently absorbed a disk-full error
   401	            if getattr(self._sqlite_writer, "is_disk_full", False):
   402	                return
   403	
   404	        # Step 1c: Notify calibration acquisition (no longer writes — already persisted)
   405	        if srdg_to_persist:
   406	            self._calibration_acquisition.on_srdg_persisted(
   407	                len(srdg_to_persist), srdg_pending_state
   408	            )
   409	
   410	        # Step 2: Publish to brokers
   411	        if persisted_readings:
   412	            await self._broker.publish_batch(persisted_readings)
   413	        if self._safety_broker is not None:
   414	            await self._safety_broker.publish_batch(readings)
   415	
   416	    async def _handle_error(self, state: _InstrumentState) -> None:
   417	        """При 3+ ошибках подряд — переподключение с backoff."""
   418	        if state.consecutive_errors >= 3:
   419	            driver = state.config.driver
   420	            logger.warning(
   421	                "Переподключение '%s' после %d ошибок", driver.name, state.consecutive_errors
   422	            )
   423	            await self._disconnect_driver(driver, context="generic error recovery")
   424	            await self._backoff(state)
   425	
   426	    async def _backoff(self, state: _InstrumentState, *, max_s: float = MAX_BACKOFF_S) -> None:
   427	        """Экспоненциальная задержка перед переподключением."""
   428	        delay = min(state.backoff_s, max_s)
   429	        logger.info("Backoff '%s': %.1fs", state.config.driver.name, delay)
   430	        await asyncio.sleep(delay)
     1	"""SQLiteWriter — запись показаний в SQLite с WAL-режимом.
     2	
     3	Один файл на день: data_YYYY-MM-DD.db.
     4	Батчевая вставка каждую секунду (или при накоплении batch_size).
     5	Работает в отдельном потоке (sqlite3 не async), взаимодействие через asyncio.Queue.
     6	"""
     7	
     8	from __future__ import annotations
     9	
    10	import asyncio
    11	import json
    12	import logging
    13	import math
    14	import os
    15	import sqlite3
    16	from collections.abc import Awaitable, Callable
    17	from concurrent.futures import ThreadPoolExecutor
    18	from datetime import UTC, date, datetime
    19	from functools import partial
    20	from pathlib import Path
    21	from typing import Any
    22	
    23	from cryodaq.core.operator_log import OperatorLogEntry, normalize_operator_log_tags
    24	from cryodaq.drivers.base import ChannelStatus, Reading
    25	
    26	logger = logging.getLogger(__name__)
    27	
    28	SCHEMA_READINGS = """
    29	CREATE TABLE IF NOT EXISTS readings (
    30	    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    31	    timestamp   REAL    NOT NULL,
    32	    instrument_id TEXT  NOT NULL,
    33	    channel     TEXT    NOT NULL,
    34	    value       REAL    NOT NULL,
    35	    unit        TEXT    NOT NULL,
    36	    status      TEXT    NOT NULL
    37	);
    38	"""
    39	
    40	SCHEMA_SOURCE_DATA = """
    41	-- Reserved for future Keithley raw SMU buffer recording.
    42	-- Currently unused — Keithley data goes through standard Reading path.
    43	CREATE TABLE IF NOT EXISTS source_data (
    44	    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    45	    timestamp   TEXT    NOT NULL,
    46	    channel     TEXT    NOT NULL,
    47	    voltage     REAL,
    48	    current     REAL,
    49	    resistance  REAL,
    50	    power       REAL
    51	);
    52	"""
    53	
    54	INDEX_READINGS_TS = """
    55	CREATE INDEX IF NOT EXISTS idx_readings_ts ON readings (timestamp);
    56	"""
    57	
    58	INDEX_SOURCE_DATA_TS = """
    59	CREATE INDEX IF NOT EXISTS idx_source_data_ts ON source_data (timestamp);
    60	"""
    61	
    62	INDEX_CHANNEL_TS = """
    63	CREATE INDEX IF NOT EXISTS idx_channel_ts ON readings (channel, timestamp);
    64	"""
    65	
    66	SCHEMA_OPERATOR_LOG = """
    67	CREATE TABLE IF NOT EXISTS operator_log (
    68	    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    69	    timestamp     REAL    NOT NULL,
    70	    experiment_id TEXT,
    71	    author        TEXT    NOT NULL DEFAULT '',
    72	    source        TEXT    NOT NULL DEFAULT '',
    73	    message       TEXT    NOT NULL,
    74	    tags          TEXT    NOT NULL DEFAULT '[]'
    75	);
    76	"""
    77	
    78	INDEX_OPERATOR_LOG_TS = """
    79	CREATE INDEX IF NOT EXISTS idx_operator_log_ts ON operator_log (timestamp);
    80	"""
    81	
    82	INDEX_OPERATOR_LOG_EXPERIMENT = """
    83	CREATE INDEX IF NOT EXISTS idx_operator_log_experiment ON operator_log (experiment_id, timestamp);
    84	"""
    85	
    86	
    87	def _parse_timestamp(raw) -> datetime:
    88	    """Parse timestamp from REAL (float) or legacy TEXT (isoformat)."""
    89	    if isinstance(raw, (int, float)):
    90	        return datetime.fromtimestamp(raw, tz=UTC)
    91	    return datetime.fromisoformat(str(raw))
    92	
    93	
    94	_SQLITE_VERSION_CHECKED = False
    95	
    96	
    97	def _check_sqlite_version() -> None:
    98	    """Warn if running on a SQLite version affected by the March 2026 WAL-reset bug.
    99	
   100	    The bug affects SQLite versions in [3.7.0, 3.51.3) when multiple
   101	    connections across threads/processes write or checkpoint "at the same
   102	    instant". CryoDAQ uses WAL with multiple concurrent connections (writer,
   103	    history reader, web dashboard, reporting); upgrade to >= 3.51.3 in
   104	    production. See: https://www.sqlite.org/wal.html
   105	    """
   106	    global _SQLITE_VERSION_CHECKED
   107	    if _SQLITE_VERSION_CHECKED:
   108	        return
   109	    _SQLITE_VERSION_CHECKED = True
   110	    version = sqlite3.sqlite_version_info  # tuple, e.g. (3, 37, 2)
   111	    if (3, 7, 0) <= version < (3, 51, 3):
   112	        logger.warning(
   113	            "SQLite %d.%d.%d is affected by the March 2026 WAL-reset corruption "
   114	            "bug (range 3.7.0 – 3.51.2). CryoDAQ uses WAL with multiple "
   115	            "connections; upgrade to SQLite >= 3.51.3 in production. On Ubuntu "
   116	            "22.04 this means building libsqlite3 from source or bundling a "
   117	            "custom libsqlite3 in the PyInstaller build. "
   118	            "See https://www.sqlite.org/wal.html",
   119	            version[0],
   120	            version[1],
   121	            version[2],
   122	        )
   123	
   124	
   125	class SQLiteWriter:
   126	    """Асинхронный писатель показаний в SQLite.
   127	
   128	    Использование::
   129	
   130	        writer = SQLiteWriter(data_dir=Path("./data"))
   131	        await writer.start(queue)   # queue: asyncio.Queue[Reading]
   132	        ...
   133	        await writer.stop()
   134	    """
   135	
   136	    def __init__(
   137	        self,
   138	        data_dir: Path,
   139	        *,
   140	        flush_interval_s: float = 1.0,
   141	        batch_size: int = 500,
   142	    ) -> None:
   143	        self._data_dir = data_dir
   144	        self._flush_interval_s = flush_interval_s
   145	        self._batch_size = batch_size
   146	        self._conn: sqlite3.Connection | None = None
   147	        self._current_date: date | None = None
   148	        self._task: asyncio.Task[None] | None = None
   149	        self._running = False
   150	        self._total_written: int = 0
   151	        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sqlite_write")
   152	        self._read_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sqlite_read")
   153	        # Periodic explicit WAL checkpoint counter (DEEP_AUDIT_CC.md D.1).
   154	        self._checkpoint_counter = 0
   155	
   156	        # Disk-full graceful degradation (Phase 2a H.1).
   157	        # When the writer thread detects disk-full from sqlite3.OperationalError,
   158	        # it sets _disk_full=True and (optionally) schedules a callback on the
   159	        # engine event loop via run_coroutine_threadsafe so the SafetyManager
   160	        # can latch a fault. The flag is cleared by DiskMonitor when free
   161	        # space recovers, BUT the operator still has to acknowledge_fault to
   162	        # actually resume polling.
   163	        self._disk_full = False
   164	        self._loop: asyncio.AbstractEventLoop | None = None
   165	        self._persistence_failure_callback: Callable[[str], Awaitable[None]] | None = None
   166	
   167	        _check_sqlite_version()
   168	
   169	    def _db_path(self, day: date) -> Path:
   170	        return self._data_dir / f"data_{day.isoformat()}.db"
   171	
   172	    # ------------------------------------------------------------------
   173	    # Disk-full graceful degradation (Phase 2a H.1)
   174	    # ------------------------------------------------------------------
   175	    @property
   176	    def is_disk_full(self) -> bool:
   177	        """True when the most recent write hit a disk-full / out-of-space error."""
   178	        return self._disk_full
   179	
   180	    def clear_disk_full(self) -> None:
   181	        """Clear the disk-full flag.
   182	
   183	        Called by DiskMonitor when free space recovers above the threshold.
   184	        Note: this does NOT auto-resume polling — the SafetyManager has
   185	        already latched a fault, and the operator must acknowledge_fault
   186	        explicitly. This is a deliberate guard against disk-space flapping.
   187	        """
   188	        if self._disk_full:
   189	            logger.warning(
   190	                "Disk space recovered — clearing _disk_full flag. "
   191	                "SafetyManager fault remains latched until operator acknowledge."
   192	            )
   193	            self._disk_full = False
   194	
   195	    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
   196	        """Bind the writer to an event loop so the executor thread can
   197	        schedule the persistence-failure callback on it."""
   198	        self._loop = loop
   199	
   200	    def set_persistence_failure_callback(self, callback: Callable[[str], Awaitable[None]]) -> None:
   201	        """Register an async callback for persistence failures (disk full etc).
   202	
   203	        The callback is awaited via :func:`asyncio.run_coroutine_threadsafe`
   204	        from the writer thread, so it lands on the engine event loop where
   205	        SafetyManager.on_persistence_failure can latch a fault.
   206	        """
   207	        self._persistence_failure_callback = callback
   208	
   209	    def _signal_persistence_failure(self, reason: str) -> None:
   210	        """Schedule persistence-failure callback on the engine event loop.
   211	
   212	        Runs in the writer thread (called from _write_day_batch) — must NOT
   213	        block. We use run_coroutine_threadsafe and intentionally do NOT await
   214	        the resulting Future, because the writer thread does not have an
   215	        event loop of its own.
   216	        """
   217	        if self._persistence_failure_callback is None or self._loop is None:
   218	            return
   219	        try:
   220	            asyncio.run_coroutine_threadsafe(
   221	                self._persistence_failure_callback(reason),
   222	                self._loop,
   223	            )
   224	        except Exception as exc:
   225	            logger.error("Failed to schedule persistence_failure callback: %s", exc)
   226	
   227	    def _ensure_connection(self, day: date) -> sqlite3.Connection:
   228	        """Открыть/переоткрыть БД если сменился день."""
   229	        if self._conn is not None and self._current_date == day:
   230	            return self._conn
   231	        if self._conn is not None:
   232	            logger.info("Смена дня: закрываю %s", self._db_path(self._current_date))
   233	            # Final WAL checkpoint at rotation (DEEP_AUDIT_CC.md D.1, H.2).
   234	            try:
   235	                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
   236	                self._conn.commit()
   237	            except sqlite3.OperationalError as exc:
   238	                logger.warning("Final WAL checkpoint at rotation failed: %s", exc)
   239	            self._conn.close()
   240	        db_path = self._db_path(day)
   241	        self._data_dir.mkdir(parents=True, exist_ok=True)
   242	        conn = sqlite3.connect(str(db_path), timeout=10, check_same_thread=False)
   243	        # WAL with explicit checkpoint policy (DEEP_AUDIT_CC.md D.1).
   244	        # Default autocheckpoint (1000 pages) can starve under concurrent
   245	        # readers. See https://www.sqlite.org/wal.html
   246	        result = conn.execute("PRAGMA journal_mode=WAL;").fetchone()
   247	        actual_mode = (result[0] if result else "").lower()
   248	        if actual_mode != "wal":
   249	            raise RuntimeError(
   250	                f"SQLite WAL mode could not be enabled at {db_path}. "
   251	                f"PRAGMA journal_mode returned {actual_mode!r}. "
   252	                f"This may indicate an unsupported filesystem (network share, "
   253	                f"WSL with DrvFs, or read-only mount). CryoDAQ requires WAL "
   254	                f"for cross-process read concurrency. Refusing to start."
   255	            )
   256	        # synchronous=NORMAL loses last ~1s on power loss but gives ~10x
   257	        # throughput. Production deployments must be on a UPS. If no UPS,
   258	        # set CRYODAQ_SQLITE_SYNC=FULL.
   259	        sync_mode = os.environ.get("CRYODAQ_SQLITE_SYNC", "NORMAL").upper()
   260	        if sync_mode not in ("NORMAL", "FULL"):
   260	        if sync_mode not in ("NORMAL", "FULL"):
   261	            sync_mode = "NORMAL"
   262	        conn.execute(f"PRAGMA synchronous={sync_mode};")
   263	        conn.execute("PRAGMA busy_timeout=5000;")
   264	        conn.execute("PRAGMA wal_autocheckpoint=1000;")  # ~4 MB
   265	        conn.execute("PRAGMA cache_size=-16384;")  # 16 MB cache
   266	        conn.execute("PRAGMA temp_store=MEMORY;")
   267	        conn.execute(SCHEMA_READINGS)
   268	        conn.execute(SCHEMA_SOURCE_DATA)
   269	        conn.execute(SCHEMA_OPERATOR_LOG)
   270	        conn.execute(INDEX_READINGS_TS)
   271	        conn.execute(INDEX_SOURCE_DATA_TS)
   272	        conn.execute(INDEX_CHANNEL_TS)
   273	        conn.execute(INDEX_OPERATOR_LOG_TS)
   274	        conn.execute(INDEX_OPERATOR_LOG_EXPERIMENT)
   275	        conn.commit()
   276	        self._conn = conn
   277	        self._current_date = day
   278	        logger.info("Открыта БД: %s", db_path)
   279	        return conn
   280	
   281	    def _write_batch(self, batch: list[Reading]) -> None:
   282	        """Вставить пакет в таблицу readings (вызывается в потоке).
   283	
   284	        Readings с value=None или value=NaN пропускаются (sqlite3 maps NaN
   285	        to NULL, which violates the NOT NULL constraint on readings.value).
   286	
   287	        Readings are grouped by day before writing so that a batch spanning
   288	        midnight is correctly split across daily DB files.
   289	        """
   290	        if not batch:
   291	            return
   292	        # Group readings by day to handle midnight crossing
   293	        by_day: dict[date, list[Reading]] = {}
   294	        for r in batch:
   295	            day = r.timestamp.date()
   296	            by_day.setdefault(day, []).append(r)
   297	        for day, day_readings in sorted(by_day.items()):
   298	            conn = self._ensure_connection(day)
   299	            self._write_day_batch(conn, day_readings)
   300	
   301	    # Status values where a non-finite value IS the sensor state (not garbage).
   302	    # Only inf-valued statuses are persisted — SQLite accepts ±inf in a REAL
   303	    # column but rejects NaN (SQLite treats NaN as NULL, violating NOT NULL).
   304	    #
   305	    # OVERRANGE  → +inf (LakeShore +OVL)  — stored as REAL, no issue.
   306	    # UNDERRANGE → -inf or finite float    — stored as REAL, no issue.
   307	    # SENSOR_ERROR → NaN (driver sentinel) — NOT persistable, dropped.
   308	    # TIMEOUT    → NaN (driver sentinel)   — NOT persistable, dropped.
   309	    #
   310	    # Full post-mortem evidence for NaN-valued sensor states requires
   311	    # schema migration (nullable value column) or sentinel substitution.
   312	    # Deferred to Phase 3 item B.1.2.
   313	    _STATE_CARRYING_STATUSES = {
   314	        ChannelStatus.OVERRANGE,  # +OVL → +inf (stored as REAL)
   315	        ChannelStatus.UNDERRANGE,  # -OVL → -inf or finite (stored as REAL)
   316	    }
   317	
   318	    def _write_day_batch(self, conn: sqlite3.Connection, batch: list[Reading]) -> None:
   319	        """Write a single day's readings to the given connection."""
   320	        rows = []
   321	        skipped = 0
   322	        for r in batch:
   323	            if r.value is None:
   324	                skipped += 1
   325	                continue
   326	            if isinstance(r.value, float) and not math.isfinite(r.value):
   327	                # Non-finite value: persist if status says this IS the sensor state
   328	                if r.status not in self._STATE_CARRYING_STATUSES:
   329	                    skipped += 1
   330	                    continue
   331	            rows.append(
   332	                (
   333	                    r.timestamp.timestamp(),
   334	                    r.instrument_id or "unknown",
   335	                    r.channel,
   336	                    r.value,
   337	                    r.unit,
   338	                    r.status.value,
   339	                )
   340	            )
   341	        if skipped:
   342	            logger.warning(
   343	                "Пропущено %d readings с value=None/NaN (из батча %d)",
   344	                skipped,
   345	                len(batch),
   346	            )
   347	        if not rows:
   348	            return
   349	        try:
   350	            conn.executemany(
   351	                "INSERT INTO readings (timestamp, instrument_id, channel, value, unit, status) "
   352	                "VALUES (?, ?, ?, ?, ?, ?);",
   353	                rows,
   354	            )
   355	            conn.commit()
   356	        except sqlite3.OperationalError as exc:
   357	            # Disk-full graceful degradation (Phase 2a H.1).
   358	            # Detect by exact PHRASES to avoid false positives like
   359	            # "database disk image is malformed" (SQLITE_CORRUPT) or
   360	            # "disk I/O error" (SQLITE_IOERR), which are NOT disk-full.
   361	            # Phrases cover SQLITE_FULL on Linux/macOS/Windows + quota.
   362	            msg = str(exc).lower()
   363	            disk_full_phrases = (
   364	                "database or disk is full",
   365	                "database is full",
   366	                "no space left on device",
   367	                "not enough space on the disk",
   368	                "disk quota exceeded",
   369	            )
   370	            if any(phrase in msg for phrase in disk_full_phrases):
   371	                if not self._disk_full:
   372	                    logger.critical(
   373	                        "DISK FULL detected in SQLite write: %s. "
   374	                        "Pausing polling, triggering safety fault.",
   375	                        exc,
   376	                    )
   377	                self._disk_full = True
   378	                self._signal_persistence_failure(f"disk full: {exc}")
   379	                # Do NOT re-raise. Re-raising would propagate up to
   380	                # write_immediate / scheduler and cause the historic tight
   381	                # CRITICAL-log loop. The flag + signalled callback are the
   382	                # signalling mechanism now.
   383	                return
   384	            # Any other OperationalError keeps the existing semantics.
   385	            raise
   386	
   387	        # Periodic explicit PASSIVE checkpoint (~once per minute at 1 Hz batch
   388	        # cadence). Prevents WAL file growth under concurrent reader pressure.
   389	        # See DEEP_AUDIT_CC.md D.1.
   390	        self._checkpoint_counter += 1
   391	        if self._checkpoint_counter >= 60:
   392	            try:
   393	                conn.execute("PRAGMA wal_checkpoint(PASSIVE);")
   394	            except sqlite3.OperationalError as exc:
   395	                logger.warning("Periodic WAL checkpoint failed: %s", exc)
   396	            self._checkpoint_counter = 0
   397	        self._total_written += len(rows)
   398	
   399	    def _write_source_row(
   400	        self,
   401	        timestamp: datetime,
   402	        channel: str,
   403	        *,
   404	        voltage: float | None = None,
   405	        current: float | None = None,
   406	        resistance: float | None = None,
   407	        power: float | None = None,
   408	    ) -> None:
   409	        """Reserved for future Keithley raw data recording.
   410	
   411	        Currently unused — Keithley data goes through standard Reading path.
   412	        Kept for future direct SMU buffer recording.
   413	        """
   414	        day = timestamp.date()
   415	        conn = self._ensure_connection(day)
   416	        conn.execute(
   417	            "INSERT INTO source_data (timestamp, channel, voltage, current, resistance, power) "
   418	            "VALUES (?, ?, ?, ?, ?, ?);",
   419	            (timestamp.isoformat(), channel, voltage, current, resistance, power),
   420	        )
   421	        conn.commit()
   422	
   423	    def _write_operator_log_entry(
   424	        self,
   425	        *,
   426	        timestamp: datetime,
   427	        experiment_id: str | None,
   428	        author: str,
   429	        source: str,
   430	        message: str,
   431	        tags: tuple[str, ...],
   432	    ) -> OperatorLogEntry:
   433	        day = timestamp.date()
   434	        conn = self._ensure_connection(day)
   435	        cursor = conn.execute(
   436	            "INSERT INTO operator_log (timestamp, experiment_id, author, source, message, tags) "
   437	            "VALUES (?, ?, ?, ?, ?, ?);",
   438	            (
   439	                timestamp.timestamp(),
   440	                experiment_id,
   441	                author,
   442	                source,
   443	                message,
   444	                json.dumps(list(tags), ensure_ascii=False),
   445	            ),
   446	        )
   447	        conn.commit()
   448	        return OperatorLogEntry(
   449	            id=int(cursor.lastrowid),
   450	            timestamp=timestamp,
   451	            experiment_id=experiment_id,
   452	            author=author,
   453	            source=source,
   454	            message=message,
   455	            tags=tags,
   456	        )
   457	
   458	    def _operator_log_db_paths(
   459	        self,
   460	        *,
   461	        start_time: datetime | None,
   462	        end_time: datetime | None,
   463	    ) -> list[Path]:
   464	        db_files = sorted(self._data_dir.glob("data_????-??-??.db"))
   465	        if not db_files:
   466	            return []
   467	
   468	        if start_time is None and end_time is None:
   469	            return db_files
   470	
   471	        selected: list[Path] = []
   472	        start_day = start_time.date() if start_time is not None else None
   473	        end_day = end_time.date() if end_time is not None else None
   474	        for db_path in db_files:
   475	            try:
   476	                day = date.fromisoformat(db_path.stem.removeprefix("data_"))
   477	            except ValueError:
   478	                continue
   479	            if start_day is not None and day < start_day:
   480	                continue
   481	            if end_day is not None and day > end_day:
   482	                continue
   483	            selected.append(db_path)
   484	        return selected
   485	
   486	    def _read_operator_log(
   487	        self,
   488	        *,
   489	        experiment_id: str | None = None,
   490	        start_time: datetime | None = None,
   491	        end_time: datetime | None = None,
   492	        limit: int = 100,
   493	    ) -> list[OperatorLogEntry]:
   494	        rows: list[OperatorLogEntry] = []
   495	        for db_path in self._operator_log_db_paths(start_time=start_time, end_time=end_time):
   496	            conn = sqlite3.connect(str(db_path), timeout=10)
   497	            conn.row_factory = sqlite3.Row
   498	            try:
   499	                conn.execute(SCHEMA_OPERATOR_LOG)
   500	                query = (
   501	                    "SELECT id, timestamp, experiment_id, author, source, message, tags "
   502	                    "FROM operator_log WHERE 1 = 1"
   503	                )
   504	                params: list[Any] = []
   505	                if experiment_id is not None:
   506	                    query += " AND experiment_id = ?"
   507	                    params.append(experiment_id)
   508	                if start_time is not None:
   509	                    query += " AND timestamp >= ?"
   510	                    params.append(start_time.timestamp())
   511	                if end_time is not None:
   512	                    query += " AND timestamp <= ?"
   513	                    params.append(end_time.timestamp())
   514	                query += " ORDER BY timestamp DESC"
   515	                for row in conn.execute(query, params).fetchall():
   516	                    tags = tuple(json.loads(row["tags"] or "[]"))
   517	                    rows.append(
   518	                        OperatorLogEntry(
   519	                            id=int(row["id"]),
   520	                            timestamp=_parse_timestamp(row["timestamp"]),

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/core/alarm_providers.py | sed -n '1,220p'
nl -ba config/alarms_v3.yaml | sed -n '1,260p'
rg -n \"cooldown_stall|threshold|KeyError|alarm_v2.py:252|alarm_v2|Cyrillic|homoglyph|ModemManager|validate_checksum|be51a24|b2b4fb5|B1|IV\\.7|gpt-5.5|gemini\" CHANGELOG.md ROADMAP.md PROJECT_STATUS.md CLAUDE.md README.md docs/bug_B1_zmq_idle_death_handoff.md docs/decisions/*.md .claude/skills/multi-model-consultation.md docs/ORCHESTRATION.md docs/CODEX_SELF_REVIEW_PLAYBOOK.md" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	"""Конкретные реализации PhaseProvider и SetpointProvider для alarm engine v2.
     2	
     3	ExperimentPhaseProvider  — читает фазу из ExperimentManager
     4	ExperimentSetpointProvider — читает setpoints из метаданных эксперимента
     5	
     6	Используются при инициализации AlarmEvaluator в engine.py.
     7	"""
     8	
     9	from __future__ import annotations
    10	
    11	import time
    12	from datetime import UTC
    13	from typing import TYPE_CHECKING
    14	
    15	from cryodaq.core.alarm_v2 import PhaseProvider, SetpointProvider
    16	
    17	if TYPE_CHECKING:
    18	    from cryodaq.core.alarm_config import SetpointDef
    19	    from cryodaq.core.experiment import ExperimentManager
    20	
    21	
    22	# ---------------------------------------------------------------------------
    23	# PhaseProvider
    24	# ---------------------------------------------------------------------------
    25	
    26	
    27	class ExperimentPhaseProvider(PhaseProvider):
    28	    """Читает текущую фазу из ExperimentManager.
    29	
    30	    Параметры
    31	    ----------
    32	    experiment_manager:
    33	        Экземпляр ExperimentManager из engine.
    34	    """
    35	
    36	    def __init__(self, experiment_manager: ExperimentManager) -> None:
    37	        self._mgr = experiment_manager
    38	
    39	    def get_current_phase(self) -> str | None:
    40	        """Текущая фаза активного эксперимента, или None."""
    41	        return self._mgr.get_current_phase()
    42	
    43	    def get_phase_elapsed_s(self) -> float:
    44	        """Время с начала текущей фазы, в секундах. 0 если нет фазы."""
    45	        active = self._mgr.get_active_experiment()
    46	        if active is None:
    47	            return 0.0
    48	        history = self._mgr.get_phase_history()
    49	        if not history:
    50	            return 0.0
    51	        # Последняя запись в истории — текущая фаза
    52	        last = history[-1]
    53	        started_at_raw = last.get("started_at")
    54	        if not started_at_raw:
    55	            return 0.0
    56	        # started_at хранится как ISO string
    57	        from datetime import datetime
    58	
    59	        try:
    60	            if isinstance(started_at_raw, str):
    61	                dt = datetime.fromisoformat(started_at_raw)
    62	                if dt.tzinfo is None:
    63	                    dt = dt.replace(tzinfo=UTC)
    64	                return time.time() - dt.timestamp()
    65	        except (ValueError, TypeError):
    66	            return 0.0
    67	        return 0.0
    68	
    69	
    70	# ---------------------------------------------------------------------------
    71	# SetpointProvider
    72	# ---------------------------------------------------------------------------
    73	
    74	
    75	class ExperimentSetpointProvider(SetpointProvider):
    76	    """Читает setpoints из метаданных эксперимента.
    77	
    78	    Для source=="experiment_metadata" ищет значение в custom_fields
    79	    активного эксперимента. Fallback — default из SetpointDef.
    80	
    81	    Параметры
    82	    ----------
    83	    experiment_manager:
    84	        Экземпляр ExperimentManager из engine.
    85	    setpoint_defs:
    86	        Словарь определений setpoints из EngineConfig.setpoints.
    87	    """
    88	
    89	    def __init__(
    90	        self,
    91	        experiment_manager: ExperimentManager,
    92	        setpoint_defs: dict[str, SetpointDef] | None = None,
    93	    ) -> None:
    94	        super().__init__()
    95	        self._mgr = experiment_manager
    96	        self._defs: dict[str, SetpointDef] = setpoint_defs or {}
    97	
    98	    def get(self, key: str) -> float:
    99	        """Получить значение setpoint по ключу.
   100	
   101	        Порядок:
   102	        1. Если source=="experiment_metadata" → custom_fields активного эксперимента
   103	        2. Иначе — default из SetpointDef
   104	        3. Если ключ не определён → 0.0
   105	        """
   106	        sp_def = self._defs.get(key)
   107	        if sp_def is None:
   108	            # Попытка прочитать напрямую из _defaults (базовый класс)
   109	            return self._defaults.get(key, 0.0)
   110	
   111	        if sp_def.source == "experiment_metadata":
   112	            active = self._mgr.get_active_experiment()
   113	            if active is not None:
   114	                custom_val = active.custom_fields.get(key)
   115	                if custom_val is not None:
   116	                    try:
   117	                        return float(custom_val)
   118	                    except (ValueError, TypeError):
   119	                        pass
   120	
   121	        return sp_def.default
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
    91	    message: >
    92	      Датчик {channel}: {value} K — вне диапазона 0–350 K.
    93	      Обрыв / КЗ / плохой контакт в месте пайки.
    94	    notify: [gui]
    95	    gui_action: highlight_red    # подсветить окно датчика красным на обзорном dashboard
    96	    side_effect: exclude_channel
    97	
    98	  # --- Fault: кратковременные скачки (intermittent) ---
    99	  sensor_fault_intermittent:
   100	    alarm_type: threshold
   101	    channel_group: uncalibrated
   102	    check: fault_count_in_window
   103	    range: [0.0, 350.0]
   104	    window_s: 300                # последние 5 мин
   105	    min_fault_count: 1           # хотя бы один скачок за окно
   106	    level: WARNING
   107	    message: >
   108	      Датчик {channel}: обнаружены скачки за 0/350 K в последние 5 мин.
   109	      Нестабильный контакт / деградация пайки.
   110	    notify: [gui]
   111	    gui_action: highlight_red
   112	
   113	  # --- Fault на калиброванных (те же границы, но отдельно для ясности) ---
   114	  calibrated_sensor_fault:
   115	    alarm_type: threshold
   116	    channels: [Т11, Т12]
   117	    check: outside_range
   118	    range: [1.0, 350.0]         # K — нижняя граница 1K (ниже калибровки DT-670)
   119	    level: CRITICAL              # CRITICAL — потеря калиброванного датчика опасна
   120	    message: >
   121	      КАЛИБРОВАННЫЙ датчик {channel}: {value} K — fault.
   122	      Количественный контроль ПОТЕРЯН.
   123	      ДЕЙСТВИЕ: немедленная проверка.
   124	    notify: [gui, telegram, sound]
   125	    side_effect: exclude_channel
   126	
   127	  # --- Потеря данных ---
   128	  data_stale_temperature:
   129	    alarm_type: stale
   130	    channel_group: all_temp
   131	    timeout_s: 30
   132	    level: WARNING
   133	    message: "Нет данных от {instrument} > 30с."
   134	    notify: [gui]
   135	
   136	  data_loss_temperature:
   137	    alarm_type: stale
   138	    channel_group: all_temp
   139	    timeout_s: 120
   140	    level: CRITICAL
   141	    message: "ПОЛНАЯ ПОТЕРЯ ДАННЫХ > 2 мин. Безопасность не гарантирована."
   142	    notify: [gui, telegram, sound]
   143	
   144	  data_loss_pressure:
   145	    alarm_type: stale
   146	    channel: P1
   147	    timeout_s: 60
   148	    level: CRITICAL
   149	    message: "Нет данных давления > 60с. Вакуумный контроль потерян."
   150	    notify: [gui, telegram, sound]
   151	
   152	  # --- Keithley ---
   153	  keithley_overpower:
   154	    alarm_type: threshold
   155	    channels: [smua_power, smub_power]
   156	    check: above
   157	    threshold: 4.0               # W (лимит 5W, запас 20%)
   158	    hysteresis: 0.5
   159	    level: CRITICAL
   160	    interlock: stop_source
   161	    message: "Мощность {channel} > 4W."
   162	    notify: [gui, telegram, sound]
   163	
   164	  # --- Диск ---
   165	  disk_space_warning:
   166	    alarm_type: threshold
   167	    channel: system_disk_gb
   168	    check: below
   169	    threshold: 10
   170	    level: WARNING
   171	    message: "Диск < 10 GB."
   172	    notify: [gui]
   173	
   174	  disk_space_critical:
   175	    alarm_type: threshold
   176	    channel: system_disk_gb
   177	    check: below
   178	    threshold: 2
   179	    level: CRITICAL
   180	    message: "Диск < 2 GB. Запись может прерваться."
   181	    notify: [gui, telegram]
   182	
   183	# ============================================================================
   184	# ФАЗОЗАВИСИМЫЕ АЛАРМЫ
   185	# ============================================================================
   186	phase_alarms:
   187	
   188	  vacuum:
   189	    vacuum_insufficient:
   190	      alarm_type: composite
   191	      operator: AND
   192	      conditions:
   193	        - channel: P1
   194	          check: above
   195	          threshold: 1.0e-4
   196	        - channel: phase_elapsed_s
   197	          check: above
   198	          threshold: 3600        # 60 мин
   199	      level: WARNING
   200	      message: "Не достигнут вакуум 1e-4 mbar за 60 мин."
   201	      notify: [gui]
   202	
   203	    vacuum_stall:
   204	      alarm_type: rate
   205	      channel: P1
   206	      check: relative_rate_near_zero
   207	      rate_threshold: 0.01       # |dP/P| < 1% за окно
   208	      additional_condition:
   209	        channel: P1
   210	        check: above
   211	        threshold: 1.0e-5
   212	      level: INFO
   213	      message: "Давление перестало падать при P > 1e-5."
   214	      notify: [gui]
   215	
   216	  cooldown:
   217	    excessive_cooling_rate:
   218	      alarm_type: rate
   219	      channels: [Т11, Т12]
   220	      check: rate_below
   221	      threshold: -5.0            # K/мин (отрицательный = охлаждение)
   222	      rate_window_s: 120
   223	      level: WARNING
   224	      message: "Скорость охлаждения {channel} > 5 K/мин ({value} K/мин)."
   225	      notify: [gui, telegram]
   226	
   227	    cooldown_stall:
   228	      alarm_type: composite
   229	      operator: AND
   230	      conditions:
   231	        - channel: Т12
   232	          check: rate_near_zero
   233	          rate_threshold: 0.1    # K/мин
   234	          rate_window_s: 900     # 15 мин
   235	        - channel: Т12
   236	          check: above
   237	          threshold: 150  # threshold_expr not implemented; using static threshold (~100K setpoint + 50K)
   238	      level: WARNING
   239	      message: "Охлаждение остановилось, Т12 далеко от setpoint."
   240	      notify: [gui, telegram]
   241	
   242	  measurement:
   243	    detector_drift:
   244	      alarm_type: threshold
   245	      channel: Т12
   246	      check: deviation_from_setpoint
   247	      setpoint_source: T12_setpoint
   248	      threshold: 0.5             # K
   249	      sustained_s: 60
   250	      level: WARNING
   251	      message: "Т12 отклонился от setpoint на > 0.5 K > 60с."
   252	      notify: [gui]
   253	
   254	    detector_unstable:
   255	      alarm_type: threshold
   256	      channel: Т12
   257	      check: deviation_from_setpoint
   258	      setpoint_source: T12_setpoint
   259	      threshold: 2.0
   260	      sustained_s: 10
docs/decisions/2026-04-24-b2b4fb5-investigation.md:1:# 2026-04-24 — b2b4fb5 hypothesis investigation
docs/decisions/2026-04-24-b2b4fb5-investigation.md:5:Determine whether commit `b2b4fb5` (2026-04-23 15:10, "harden B1
docs/decisions/2026-04-24-b2b4fb5-investigation.md:7:transport introduced by IV.7, and if so whether this incompatibility
docs/decisions/2026-04-24-b2b4fb5-investigation.md:8:caused the 2026-04-23 ~16:30 IV.7 runtime failure to be misattributed
docs/decisions/2026-04-24-b2b4fb5-investigation.md:13:`b2b4fb5`'s synchronous startup probe `_validate_bridge_startup()`
docs/decisions/2026-04-24-b2b4fb5-investigation.md:24:**IV.7 failure on 2026-04-23 was not caused by the ipc:// transport
docs/decisions/2026-04-24-b2b4fb5-investigation.md:41:Thesis: `b2b4fb5` only touches `tools/diag_zmq_b1_capture.py` and its
docs/decisions/2026-04-24-b2b4fb5-investigation.md:42:test. Post-b2b4fb5 commits (`157c4bc`, `63a3fed`) touched different
docs/decisions/2026-04-24-b2b4fb5-investigation.md:52:`/tmp/diag_iv7_capture.log` exists on disk from the 2026-04-23 IV.7
docs/decisions/2026-04-24-b2b4fb5-investigation.md:55:    B1 capture aborted: Bridge startup probe failed:
docs/decisions/2026-04-24-b2b4fb5-investigation.md:59:from `b2b4fb5`. The tool used for the IV.7 test was `diag_zmq_b1_capture.py`
docs/decisions/2026-04-24-b2b4fb5-investigation.md:87:- Ran `git revert --no-commit b2b4fb5` — clean revert, 2 files
docs/decisions/2026-04-24-b2b4fb5-investigation.md:104:underlying B1 idle-death bug fires. This matches the pre-existing
docs/decisions/2026-04-24-b2b4fb5-investigation.md:105:B1 signature ("cmd #48 FAIL at uptime 82s", `HANDOFF_2026-04-20_GLM.md`
docs/decisions/2026-04-24-b2b4fb5-investigation.md:106:line 238). IV.7 did NOT fix B1 — it just changed the transport.
docs/decisions/2026-04-24-b2b4fb5-investigation.md:111:B1 degraded state, ran `tools/diag_zmq_b1_capture.py` (short,
docs/decisions/2026-04-24-b2b4fb5-investigation.md:118:Interpretation: confirms engine is in the B1 degraded state, not a
docs/decisions/2026-04-24-b2b4fb5-investigation.md:122:### 00:20 — b1_capture against FRESH engine with b2b4fb5 reverted
docs/decisions/2026-04-24-b2b4fb5-investigation.md:135:transport at the exact same codebase tip, minus only the b2b4fb5
docs/decisions/2026-04-24-b2b4fb5-investigation.md:142:- Branch tip intact: `63a3fed`, `157c4bc`, `b2b4fb5`, ... preserved.
docs/decisions/2026-04-24-b2b4fb5-investigation.md:150:| IV.7 2026-04-23 failure | present | ipc:// | ~fresh (< 1s) | **abort at cmd#0** — "Engine не отвечает" |
docs/decisions/2026-04-24-b2b4fb5-investigation.md:151:| retest 2026-04-24 (bridge_extended) | reverted | ipc:// | 4s | 44/44 early OK, B1 idle-death at cmd #45 |
docs/decisions/2026-04-24-b2b4fb5-investigation.md:152:| retest 2026-04-24 (b1_capture against degraded engine) | reverted | ipc:// | ~4 min | fail (engine already broken by B1) |
docs/decisions/2026-04-24-b2b4fb5-investigation.md:155:The controlling variable is the presence of the b2b4fb5 hardening
docs/decisions/2026-04-24-b2b4fb5-investigation.md:163:1. IV.7's `ipc://` transport is viable. It runs normally for the
docs/decisions/2026-04-24-b2b4fb5-investigation.md:165:2. `b2b4fb5`'s startup probe is incompatible with ipc:// at engine
docs/decisions/2026-04-24-b2b4fb5-investigation.md:168:3. The 2026-04-23 16:30 "IV.7 failed" narrative was a
docs/decisions/2026-04-24-b2b4fb5-investigation.md:169:   misattribution: b2b4fb5 aborted the diag capture before IV.7's
docs/decisions/2026-04-24-b2b4fb5-investigation.md:174:4. **B1 idle-death is unrelated to b2b4fb5.** B1 fires at ~80s
docs/decisions/2026-04-24-b2b4fb5-investigation.md:175:   uptime regardless of hardening presence. IV.7 did not fix B1.
docs/decisions/2026-04-24-b2b4fb5-investigation.md:183:**Option R1 — fix b2b4fb5 to be startup-race-tolerant.**
docs/decisions/2026-04-24-b2b4fb5-investigation.md:195:**Option R3 — revert b2b4fb5 and accept no startup guard.**
docs/decisions/2026-04-24-b2b4fb5-investigation.md:200:Merge path for IV.7:
docs/decisions/2026-04-24-b2b4fb5-investigation.md:203:  **but note**: IV.7 does NOT close B1. B1 investigation continues
docs/decisions/2026-04-24-b2b4fb5-investigation.md:205:- If R3: straight revert of `b2b4fb5`, merge iv7 → master, tag
docs/decisions/2026-04-24-b2b4fb5-investigation.md:213:- IV.7's `_prepare_ipc_path` cleans up stale sockets but still
docs/decisions/2026-04-24-b2b4fb5-investigation.md:224:  69-76 on `b2b4fb5`
docs/decisions/2026-04-24-b2b4fb5-investigation.md:228:  ipc-aware; unrelated to the b2b4fb5 hardening issue)
docs/decisions/2026-04-24-b2b4fb5-investigation.md:232:- `/tmp/diag_iv7_retest.log` — 180s soak showing B1 idle-death
docs/decisions/2026-04-24-b2b4fb5-investigation.md:239:- B1 root cause still unknown. H4 (pyzmq/asyncio) and H5 (engine
docs/decisions/2026-04-24-overnight-swarm-launch.md:6:consultation jobs dispatched to Codex (gpt-5.5 / reasoning high ×
docs/decisions/2026-04-24-overnight-swarm-launch.md:7:5 tasks) and Gemini (gemini-2.5-pro × 5 tasks). All artifacts
docs/decisions/2026-04-24-overnight-swarm-launch.md:18:| 1 | codex-01-r123-pick | Codex gpt-5.5/high | `BRIEFS/codex-01-r123-pick.prompt.md` | `RESPONSES/codex-01-r123-pick.response.md` | ~01:15 | RUNNING (PID 48746 wrapper, 48757 codex) |
docs/decisions/2026-04-24-overnight-swarm-launch.md:19:| 2 | codex-02-shared-context | Codex gpt-5.5/high | `BRIEFS/codex-02-shared-context.prompt.md` | `RESPONSES/codex-02-shared-context.response.md` | ~01:15 | RUNNING (PID 48747 wrapper, 48758 codex) |
docs/decisions/2026-04-24-overnight-swarm-launch.md:20:| 3 | codex-03-launcher-concurrency | Codex gpt-5.5/high | `BRIEFS/codex-03-launcher-concurrency.prompt.md` | `RESPONSES/codex-03-launcher-concurrency.response.md` | ~01:15 | RUNNING (PID 48748 wrapper, 48759 codex) |
docs/decisions/2026-04-24-overnight-swarm-launch.md:21:| 4 | codex-04-alarm-v2-threshold | Codex gpt-5.5/high | `BRIEFS/codex-04-alarm-v2-threshold.prompt.md` | `RESPONSES/codex-04-alarm-v2-threshold.response.md` | ~01:15 | RUNNING (PID 48749 wrapper, 48763 codex) |
docs/decisions/2026-04-24-overnight-swarm-launch.md:22:| 5 | codex-05-thyracont-probe | Codex gpt-5.5/high | `BRIEFS/codex-05-thyracont-probe.prompt.md` | `RESPONSES/codex-05-thyracont-probe.response.md` | ~01:15 | RUNNING (PID 48750 wrapper, 48764 codex) |
docs/decisions/2026-04-24-overnight-swarm-launch.md:23:| 6 | gemini-01-r123-blast | Gemini 2.5-pro | `BRIEFS/gemini-01-r123-blast.prompt.md` | `RESPONSES/gemini-01-r123-blast.response.md` | ~01:17 (relaunch) | QUEUED — in serial chain PID 50252 |
docs/decisions/2026-04-24-overnight-swarm-launch.md:24:| 7 | gemini-02-arch-drift | Gemini 2.5-pro | `BRIEFS/gemini-02-arch-drift.prompt.md` | `RESPONSES/gemini-02-arch-drift.response.md` | ~01:17 | QUEUED in chain |
docs/decisions/2026-04-24-overnight-swarm-launch.md:25:| 8 | gemini-03-doc-reality | Gemini 2.5-pro | `BRIEFS/gemini-03-doc-reality.prompt.md` | `RESPONSES/gemini-03-doc-reality.response.md` | ~01:17 | QUEUED in chain |
docs/decisions/2026-04-24-overnight-swarm-launch.md:26:| 9 | gemini-04-safe-merge-eval | Gemini 2.5-pro | `BRIEFS/gemini-04-safe-merge-eval.prompt.md` | `RESPONSES/gemini-04-safe-merge-eval.response.md` | ~01:17 | QUEUED in chain |
docs/decisions/2026-04-24-overnight-swarm-launch.md:27:| 10 | gemini-05-coverage-gaps | Gemini 2.5-pro | `BRIEFS/gemini-05-coverage-gaps.prompt.md` | `RESPONSES/gemini-05-coverage-gaps.response.md` | ~01:17 | QUEUED in chain |
docs/decisions/2026-04-24-overnight-swarm-launch.md:36:Plan said: ``/codex:rescue --model gpt-5.5 --reasoning high --background ...``
docs/decisions/2026-04-24-overnight-swarm-launch.md:39:`gemini` are on PATH. Adapted to: direct `codex exec` and `gemini`
docs/decisions/2026-04-24-overnight-swarm-launch.md:44:- `-m gpt-5.5`
docs/decisions/2026-04-24-overnight-swarm-launch.md:52:- `-m gemini-2.5-pro`
docs/decisions/2026-04-24-overnight-swarm-launch.md:61:Plan §3.7 said: if `/codex` rejects `gpt-5.5`, fall back to `gpt-5.4`.
docs/decisions/2026-04-24-overnight-swarm-launch.md:62:Ran a 3-token round-trip probe with `echo "Say 'probe ok'" | codex exec -m gpt-5.5 ...`
docs/decisions/2026-04-24-overnight-swarm-launch.md:64:gpt-5.5 is accepted upstream. No fallback needed.
docs/decisions/2026-04-24-overnight-swarm-launch.md:79:1. **Rate limit.** Parallel 5× gemini-2.5-pro calls hit per-minute
docs/decisions/2026-04-24-overnight-swarm-launch.md:85:- Killed wrapper PIDs for the five Gemini jobs (`awk '/^gemini-/'
docs/decisions/2026-04-24-overnight-swarm-launch.md:86:  .pids | kill`). Pre-existing unrelated gemini processes
docs/decisions/2026-04-24-overnight-swarm-launch.md:103:## Codex confirmation — gpt-5.5 accepted
docs/decisions/2026-04-24-overnight-swarm-launch.md:105:Probe result: `codex exec -m gpt-5.5 -c model_reasoning_effort="high"`
docs/decisions/2026-04-24-overnight-swarm-launch.md:113:model: gpt-5.5
docs/decisions/2026-04-24-overnight-swarm-launch.md:121:- Codex briefs have `Model: gpt-5.5 / Reasoning effort: high` as
docs/decisions/2026-04-24-overnight-swarm-launch.md:123:- Gemini briefs have `Model: gemini-2.5-pro` as first line
docs/decisions/2026-04-24-overnight-swarm-launch.md:158:- `docs/decisions/2026-04-24-b2b4fb5-investigation.md` — input
docs/decisions/2026-04-23-cleanup-baseline.md:120:Decision: `git worktree remove --force .worktrees/codex-b1-truth-recovery` (safe now that stray file preserved). `git branch -D codex/b1-truth-recovery` (was 9 commits ahead of master). `git branch -D codex/preserved-local-master-2026-04-21` (was 6 commits ahead of master). Kept `codex/safe-merge-b1-truth-recovery` (b2b4fb5, pending architect eval) and `experiment/iv7-ipc-transport` (63a3fed, pending b2b4fb5 hypothesis test).
docs/decisions/2026-04-23-cleanup-baseline.md:128:| codex/safe-merge-b1-truth-recovery | b2b4fb5 | preserved, pending architect eval |
docs/decisions/2026-04-23-cleanup-baseline.md:129:| experiment/iv7-ipc-transport | 63a3fed | preserved, pending b2b4fb5 hypothesis test |
docs/decisions/2026-04-23-cleanup-baseline.md:142:- **b2b4fb5 hypothesis test**: does the hardened B1 probe reject a healthy `ipc://` bridge, causing the 2026-04-23 IV.7 runtime failure to have been misattributed? (Plan `CC_PROMPT_IV_7_IPC_TRANSPORT.md` still active per §11.)
docs/decisions/2026-04-23-cleanup-baseline.md:144:- **IV.7 status**: depends on b2b4fb5 test outcome.
PROJECT_STATUS.md:91:- `1c61268` — CRITICAL domain cleanup (Latin T→Cyrillic Т в правилах; Latin `mbar`→`мбар`); invalid Python blocks; v1.0.0→v1.0.1 metadata; ghost token refs qualified; Ctrl+W в canonical shortcut registry
docs/decisions/2026-04-24-d1-d4a-execution.md:6:implemented on `feat/b2b4fb5-repair` branch, pushed to origin for
docs/decisions/2026-04-24-d1-d4a-execution.md:14:| `8b9ce4a` | `3b661e2` | tools: add reusable B1 diagnostic helpers |
docs/decisions/2026-04-24-d1-d4a-execution.md:15:| `cc090be` | `056a199` | tools: add canonical B1 capture CLI |
docs/decisions/2026-04-24-d1-d4a-execution.md:16:| `40553ea` | `8e79ea6` | tools: align B1 diagnostic helpers with bridge/direct capture |
docs/decisions/2026-04-24-d1-d4a-execution.md:17:| `033f87b` | `983480d` | tools: align B1 capture CLI with jsonl master capture |
docs/decisions/2026-04-24-d1-d4a-execution.md:18:| `62314be` | `2ed975f` | tools: record direct probe timeouts in B1 capture |
docs/decisions/2026-04-24-d1-d4a-execution.md:28:  **pre-b2b4fb5 form** — the state that R1 must land on top of.
docs/decisions/2026-04-24-d1-d4a-execution.md:34:- **Branch:** `feat/b2b4fb5-repair` (new, tracks `origin/feat/b2b4fb5-repair`)
docs/decisions/2026-04-24-d1-d4a-execution.md:36:- **HEAD:** `c3f4f86` — fix(diag): bounded-backoff retry in B1 capture probe (R1 repair for b2b4fb5)
docs/decisions/2026-04-24-d1-d4a-execution.md:47:4. All attempts non-OK → `raise RuntimeError(f"Bridge startup probe failed: {last_reply!r}")` — same error surface as b2b4fb5.
docs/decisions/2026-04-24-d1-d4a-execution.md:49:Call site added in `main()` between `bridge.start()` + `time.sleep(1.0)` and `run_capture(...)`. Failure → stderr `"B1 capture aborted: ..."` + `return 1`, matching b2b4fb5's behavior so downstream tooling that greps this marker is unaffected.
docs/decisions/2026-04-24-d1-d4a-execution.md:67:`artifacts/consultations/2026-04-24-overnight/RESPONSES/gemini-04-safe-merge-eval.response.md`.
docs/decisions/2026-04-24-d1-d4a-execution.md:73:- `8feda6b` — review: add roadmap review artifacts (codex / gemini / kimi / metaswarm)
docs/decisions/2026-04-24-d1-d4a-execution.md:75:- `bbc65c8` — diagnostics: add B1 evidence documentation (runbook NOT RUN — env unavailable)
docs/decisions/2026-04-24-d1-d4a-execution.md:86:3. **Post-D1-merge Codex equivalence check** (architect Q4) — verify functionally equivalent to post-`b2b4fb5` state plus the R1 delta.
docs/decisions/2026-04-24-d1-d4a-execution.md:87:4. **Architect review + merge** of `feat/b2b4fb5-repair`.
docs/decisions/2026-04-24-d1-d4a-execution.md:102:- Consulted: Codex gpt-5.5 / high reasoning, ~88 KB response
docs/decisions/2026-04-24-d1-d4a-execution.md:112:  `{"ok": 1}`, `{"ok": True}`, `{"ok": False}`) — R1 and b2b4fb5
docs/decisions/2026-04-24-d1-d4a-execution.md:121:1. `git branch -D feat/b2b4fb5-repair` (local)
docs/decisions/2026-04-24-d1-d4a-execution.md:122:2. `git push origin --delete feat/b2b4fb5-repair` (remote)
docs/decisions/2026-04-24-d1-d4a-execution.md:126:Consulted: Codex gpt-5.5 high.
docs/decisions/2026-04-24-d1-d4a-execution.md:132:Review `feat/b2b4fb5-repair` (`c3f4f86`):
ROADMAP.md:340:Warning threshold configurable. Historical leak rate as criostat health
ROADMAP.md:423:### B1 — ZMQ subprocess command channel dies (not idle-related)
ROADMAP.md:449:  threshold), so probes never fire — TCP_KEEPALIVE fix doesn't
ROADMAP.md:467:`docs/bug_B1_zmq_idle_death_handoff.md`.
ROADMAP.md:486:full subtree 1775/1776 (1 unrelated flaky). Committed as `be51a24`
ROADMAP.md:490:macOS reproduce B1 with structurally identical timing to pre-fix
ROADMAP.md:512:**Status:** still 🔧. B1 remains OPEN and blocks `0.34.0`.
ROADMAP.md:514:**Next:** IV.7 `ipc://` transport experiment (spec
ROADMAP.md:524:command-only failure shape — independent of whether B1 is
ROADMAP.md:539:checks run in the same poll cycle. Does not resolve B1 itself —
ROADMAP.md:542:cycle which is a usable workaround until IV.7 `ipc://` ships.
ROADMAP.md:546:- `aabd75f` — `engine: wire validate_checksum through Thyracont
ROADMAP.md:562:reading-driven, not B1-caused) is now resolved by `aabd75f` +
ROADMAP.md:563:Ubuntu-side config (`validate_checksum: false` in
ROADMAP.md:566:**Orthogonal issue still open:** `alarm_v2.py:252` raises
ROADMAP.md:567:`KeyError: 'threshold'` when evaluating the `cooldown_stall`
ROADMAP.md:568:composite alarm (one sub-condition is missing a `threshold`
ROADMAP.md:569:field — probably stale/rate-type where `threshold` is spurious).
ROADMAP.md:572:`cond.get("threshold")` check in `_eval_condition`.
docs/bug_B1_zmq_idle_death_handoff.md:1:# Bug B1 — ZMQ subprocess command channel dies — Codex handoff
docs/bug_B1_zmq_idle_death_handoff.md:293:- This doc (`docs/bug_B1_zmq_idle_death_handoff.md`)
docs/bug_B1_zmq_idle_death_handoff.md:395:## Pressure display bug is SEPARATE from B1
docs/bug_B1_zmq_idle_death_handoff.md:402:The "pressure shows em-dash" observation does NOT help diagnose B1.
docs/bug_B1_zmq_idle_death_handoff.md:503:  commands. Mitigation: short streak / recent-window threshold.
docs/bug_B1_zmq_idle_death_handoff.md:553:# 2026-04-20 evening update — IV.6 outcome + IV.7 plan
docs/bug_B1_zmq_idle_death_handoff.md:555:## IV.6 landed at `be51a24` but did NOT fix B1
docs/bug_B1_zmq_idle_death_handoff.md:560:diag tools against mock engine on macOS — **B1 still reproduces
docs/bug_B1_zmq_idle_death_handoff.md:576:IV.6 was still committed as `be51a24` on Vladimir's explicit
docs/bug_B1_zmq_idle_death_handoff.md:578:whether it individually closed B1.
docs/bug_B1_zmq_idle_death_handoff.md:589:## Next attempt: IV.7 `ipc://` transport
docs/bug_B1_zmq_idle_death_handoff.md:597:  without fixing B1)
docs/bug_B1_zmq_idle_death_handoff.md:607:**IV.7 spec:** `CC_PROMPT_IV_7_IPC_TRANSPORT.md`. Change two
docs/bug_B1_zmq_idle_death_handoff.md:611:Ubuntu → tag `0.34.0`. If failures persist → B1 is higher than
docs/bug_B1_zmq_idle_death_handoff.md:615:## Related fixes shipped during B1 investigation (2026-04-20)
docs/bug_B1_zmq_idle_death_handoff.md:620:`validate_checksum` YAML key when constructing `ThyracontVSP63D`.
docs/bug_B1_zmq_idle_death_handoff.md:630:    validate_checksum=bool(entry.get("validate_checksum", True)),
docs/bug_B1_zmq_idle_death_handoff.md:654:## Still-open orthogonal bugs (not B1, not blocking 0.34.0)
docs/bug_B1_zmq_idle_death_handoff.md:656:1. `alarm_v2.py::_eval_condition` raises `KeyError 'threshold'`
docs/bug_B1_zmq_idle_death_handoff.md:657:   when evaluating `cooldown_stall` composite — one sub-condition
docs/bug_B1_zmq_idle_death_handoff.md:658:   is missing a `threshold` field (probably stale/rate-type).
docs/bug_B1_zmq_idle_death_handoff.md:660:   `cond.get("threshold")` defensive access OR config audit.
docs/bug_B1_zmq_idle_death_handoff.md:664:   `self._validate_checksum=True`. Read path DOES validate. Driver
CLAUDE.md:170:- `src/cryodaq/core/alarm.py` — v1 alarm engine (threshold + hysteresis)
CLAUDE.md:171:- `src/cryodaq/core/alarm_v2.py` — v2 alarm engine (YAML-driven, phase-aware, composite conditions)
CLAUDE.md:183:- `src/cryodaq/core/interlock.py` — threshold detection, delegates actions to SafetyManager
CLAUDE.md:380:- **BOM применяется только к** operator-facing CSV-выгрузкам (`storage/csv_export.py`) — Excel на русской Windows корректно читает Cyrillic только при BOM-префиксе. Это per-usecase решение, не общее правило репо.
CHANGELOG.md:16:release is `0.34.0` once B1 is resolved via IV.7.
CHANGELOG.md:20:- `aabd75f` — `engine: wire validate_checksum through Thyracont
CHANGELOG.md:25:  config-side `validate_checksum: false` in
CHANGELOG.md:39:- `be51a24` — `zmq: ephemeral REQ per command + cmd-channel
CHANGELOG.md:40:  watchdog (IV.6 partial B1 mitigation)`. Landed the full
CHANGELOG.md:41:  Codex-proposed B1 fix plan: per-command ephemeral REQ socket in
CHANGELOG.md:47:  **Does NOT fix B1 — Stage 3 diag tools still reproduce it.**
CHANGELOG.md:60:  - `instruments.local.yaml` — `validate_checksum: false` on
CHANGELOG.md:63:- Operational on Ubuntu lab PC: `ModemManager` disabled
CHANGELOG.md:68:- **B1 still unresolved.** GUI command channel silently dies
CHANGELOG.md:69:  ~30-120 s after bridge startup on both platforms. IV.7 `ipc://`
CHANGELOG.md:76:- `alarm_v2.py::_eval_condition` raises `KeyError 'threshold'`
CHANGELOG.md:77:  when evaluating `cooldown_stall` composite. One sub-condition
CHANGELOG.md:78:  is missing a `threshold` field. Log spam, not crash. Pending
CHANGELOG.md:244:  threshold), sensor diagnostics table with 10 s polling of
CHANGELOG.md:262:  v1 threshold-based table (fed via `on_reading` + `metadata["alarm_name"]`
CHANGELOG.md:264:  polling of `alarm_v2_status`). Emoji severity icons (🔴 / 🟡 / 🔵)
CHANGELOG.md:336:  driving settling detection with `percent_settled` threshold +
CHANGELOG.md:340:  (`dT/dt > 0.01 К/мин` threshold), steady-state banner adapting to
CHANGELOG.md:719:  `DataBroker` на channel `alarm_v2/acknowledged`. Enables future
CHANGELOG.md:720:  v2 alarm badge. `alarm_v2_status` response включает
CHANGELOG.md:1217:- **AlarmEvaluator** — composite (AND/OR), threshold, rate, stale alarm
CHANGELOG.md:1578:- **InterlockEngine** — threshold detection, regex channel matching.
docs/ORCHESTRATION.md:28:- `b2b4fb5` (hardening gate for B1 capture probe) landed 45 min
docs/ORCHESTRATION.md:29:  before `157c4bc` (IV.7 ipc:// transport) without anyone noticing
docs/ORCHESTRATION.md:31:  bridge — so IV.7 failed runtime and was blamed, instead of the
docs/ORCHESTRATION.md:101:`/gemini:rescue`, etc.) passing the brief path.
docs/ORCHESTRATION.md:161:Branch prefixes `codex/`, `gemini/`, `kimi/`, `agent/`,
docs/ORCHESTRATION.md:211:  (e.g. "IV.7 / commit 1 of 3")
docs/ORCHESTRATION.md:221:Batch: IV.7 / commit 1 of 2
docs/ORCHESTRATION.md:242:├── runbooks/                 ← operational procedures (B1_*, tuning, deployment)
docs/ORCHESTRATION.md:244:└── bug_*.md                  ← individual bug handoffs (B1, etc.)
docs/ORCHESTRATION.md:316:Pulled out as its own section because it's what broke IV.7 on
docs/ORCHESTRATION.md:329:The 2026-04-23 mistake: `b2b4fb5` hardened the bridge startup
docs/ORCHESTRATION.md:330:probe 45 min before IV.7 `157c4bc` added ipc:// transport. The
docs/ORCHESTRATION.md:333:didn't recognize it and aborted the capture. IV.7 then got
docs/ORCHESTRATION.md:416:| IV.7 | `CC_PROMPT_IV_7_IPC_TRANSPORT.md` | Failed runtime 2026-04-23; likely blocked by unrelated hardening (`b2b4fb5`); **next architect action**: test the hypothesis — revert hardening on iv7 worktree, rerun diag, see if ipc:// was actually healthy |
docs/ORCHESTRATION.md:443:3. **Hardening / feature collision.** 2026-04-23: `b2b4fb5`
docs/ORCHESTRATION.md:444:   hardened the B1 probe without considering that `157c4bc`
docs/ORCHESTRATION.md:447:   what killed the IV.7 capture, not the ipc:// transport
.claude/skills/multi-model-consultation.md:43:### Codex CLI — gpt-5.5 high reasoning
.claude/skills/multi-model-consultation.md:55:**Always pass:** `--model gpt-5.5 --reasoning high` as flags AND
.claude/skills/multi-model-consultation.md:56:`Model: gpt-5.5 / Reasoning effort: high` as first two lines of prompt
.claude/skills/multi-model-consultation.md:61:2026-04-24, use gpt-5.5. If architect references a newer version,
.claude/skills/multi-model-consultation.md:120:**Always pass:** `-m gemini-3.1-pro-preview` (full model string
.claude/skills/multi-model-consultation.md:127:recent Gemini CLI. Older `gemini-2.5-pro` endpoint still works but is
.claude/skills/multi-model-consultation.md:162:   plausible word salad. Hypotheses about B1-class bugs were wrong
.claude/skills/multi-model-consultation.md:546:**What happened:** `b2b4fb5` hardening gate landed in the B1 capture
.claude/skills/multi-model-consultation.md:547:probe 45 min before `157c4bc` IV.7 ipc:// transport. The hardened
.claude/skills/multi-model-consultation.md:549:a healthy ipc:// bridge, causing IV.7 to be blamed for a runtime
.claude/skills/multi-model-consultation.md:583:used for a B1 analysis earlier. Output was shallow and missed the
.claude/skills/multi-model-consultation.md:591:**Do:** ALWAYS pass `--model gpt-5.5 --reasoning high` AND repeat in
.claude/skills/multi-model-consultation.md:592:prompt body first two lines: `Model: gpt-5.5 / Reasoning effort: high`.
.claude/skills/multi-model-consultation.md:593:(Or the current latest Codex model — gpt-5.5 as of 2026-04-24.)
.claude/skills/multi-model-consultation.md:602:Model: gpt-5.5
.claude/skills/multi-model-consultation.md:638:Model: gemini-3.1-pro-preview
.claude/skills/multi-model-consultation.md:664:Write to: artifacts/consultations/[DATE]/[topic]/gemini.response.md

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/analytics/plugin_loader.py | sed -n '253,380p'" in /Users/vladimir/Projects/cryodaq
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
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/core/alarm_v2.py | sed -n '1,360p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	"""AlarmEngine v2 — физически обоснованные алармы с composite, rate, stale conditions.
     2	
     3	Компоненты:
     4	  AlarmEvent       — событие срабатывания аларма
     5	  PhaseProvider    — интерфейс для получения текущей фазы эксперимента
     6	  SetpointProvider — интерфейс для получения setpoints
     7	  AlarmEvaluator   — вычисляет условие аларма → AlarmEvent | None
     8	  AlarmStateManager — управляет состоянием (active/cleared), гистерезис, dedup
     9	
    10	Физическое обоснование: docs/alarm_tz_physics_v3.md
    11	"""
    12	
    13	from __future__ import annotations
    14	
    15	import logging
    16	import time
    17	from collections import deque
    18	from dataclasses import dataclass
    19	from typing import TYPE_CHECKING, Any, Literal
    20	
    21	if TYPE_CHECKING:
    22	    from cryodaq.core.channel_state import ChannelStateTracker
    23	    from cryodaq.core.rate_estimator import RateEstimator
    24	
    25	logger = logging.getLogger(__name__)
    26	
    27	
    28	# ---------------------------------------------------------------------------
    29	# AlarmEvent
    30	# ---------------------------------------------------------------------------
    31	
    32	
    33	@dataclass
    34	class AlarmEvent:
    35	    """Событие срабатывания аларма."""
    36	
    37	    alarm_id: str
    38	    level: str  # "INFO" | "WARNING" | "CRITICAL"
    39	    message: str
    40	    triggered_at: float  # unix timestamp
    41	    channels: list[str]  # каналы-участники
    42	    values: dict[str, float]  # channel → значение на момент срабатывания
    43	    acknowledged: bool = False
    44	    acknowledged_at: float = 0.0
    45	    acknowledged_by: str = ""
    46	
    47	
    48	# ---------------------------------------------------------------------------
    49	# AlarmTransition
    50	# ---------------------------------------------------------------------------
    51	
    52	AlarmTransition = Literal["TRIGGERED", "CLEARED"]
    53	
    54	
    55	# ---------------------------------------------------------------------------
    56	# Provider protocols (duck-typed, без runtime Protocol overhead)
    57	# ---------------------------------------------------------------------------
    58	
    59	
    60	class PhaseProvider:
    61	    """Базовый провайдер фазы — заглушка для тестов."""
    62	
    63	    def get_current_phase(self) -> str | None:
    64	        return None
    65	
    66	    def get_phase_elapsed_s(self) -> float:
    67	        return 0.0
    68	
    69	
    70	class SetpointProvider:
    71	    """Базовый провайдер setpoints — заглушка для тестов."""
    72	
    73	    def __init__(self, defaults: dict[str, float] | None = None) -> None:
    74	        self._defaults: dict[str, float] = defaults or {}
    75	
    76	    def get(self, key: str) -> float:
    77	        return self._defaults.get(key, 0.0)
    78	
    79	
    80	# ---------------------------------------------------------------------------
    81	# AlarmEvaluator
    82	# ---------------------------------------------------------------------------
    83	
    84	_DEFAULT_RATE_WINDOW_S = 120.0
    85	
    86	
    87	class AlarmEvaluator:
    88	    """Вычисляет условие аларма по текущему состоянию системы.
    89	
    90	    Параметры
    91	    ----------
    92	    state:
    93	        ChannelStateTracker с текущими значениями каналов.
    94	    rate:
    95	        RateEstimator с оценками dX/dt.
    96	    phase_provider:
    97	        Провайдер текущей фазы эксперимента.
    98	    setpoint_provider:
    99	        Провайдер setpoints.
   100	    """
   101	
   102	    def __init__(
   103	        self,
   104	        state: ChannelStateTracker,
   105	        rate: RateEstimator,
   106	        phase_provider: PhaseProvider,
   107	        setpoint_provider: SetpointProvider,
   108	    ) -> None:
   109	        self._state = state
   110	        self._rate = rate
   111	        self._phase = phase_provider
   112	        self._setpoint = setpoint_provider
   113	
   114	    def evaluate(self, alarm_id: str, alarm_config: dict[str, Any]) -> AlarmEvent | None:
   115	        """Проверить одну alarm-конфигурацию. None = не сработал."""
   116	        alarm_type = alarm_config.get("alarm_type")
   117	        try:
   118	            if alarm_type == "threshold":
   119	                return self._eval_threshold(alarm_id, alarm_config)
   120	            elif alarm_type == "composite":
   121	                return self._eval_composite(alarm_id, alarm_config)
   122	            elif alarm_type == "rate":
   123	                return self._eval_rate(alarm_id, alarm_config)
   124	            elif alarm_type == "stale":
   125	                return self._eval_stale(alarm_id, alarm_config)
   126	            else:
   127	                logger.warning("Неизвестный alarm_type=%r для %s", alarm_type, alarm_id)
   128	                return None
   129	        except Exception as exc:
   130	            logger.error("Ошибка evaluate %s: %s", alarm_id, exc, exc_info=True)
   131	            return None
   132	
   133	    # ------------------------------------------------------------------
   134	    # threshold
   135	    # ------------------------------------------------------------------
   136	
   137	    def _eval_threshold(self, alarm_id: str, cfg: dict) -> AlarmEvent | None:
   138	        check = cfg.get("check", "above")
   139	        channels = self._resolve_channels(cfg)
   140	        level = cfg.get("level", "WARNING")
   141	        message_tmpl = cfg.get("message", f"Alarm {alarm_id}")
   142	
   143	        for ch in channels:
   144	            triggered, value = self._check_threshold_channel(ch, check, cfg)
   145	            if triggered:
   146	                msg = self._format_message(message_tmpl, channel=ch, value=value)
   147	                return AlarmEvent(
   148	                    alarm_id=alarm_id,
   149	                    level=level,
   150	                    message=msg,
   151	                    triggered_at=time.time(),
   152	                    channels=[ch],
   153	                    values={ch: value},
   154	                )
   155	        return None
   156	
   157	    def _check_threshold_channel(self, channel: str, check: str, cfg: dict) -> tuple[bool, float]:
   158	        """Возвращает (сработал, значение)."""
   159	        if check == "fault_count_in_window":
   160	            count = self._state.get_fault_count(channel)
   161	            min_count = cfg.get("min_fault_count", 1)
   162	            return count >= min_count, float(count)
   163	
   164	        state = self._state.get(channel)
   165	        if state is None:
   166	            return False, 0.0
   167	        value = state.value
   168	
   169	        if check == "above":
   170	            return value > cfg["threshold"], value
   171	        elif check == "below":
   172	            return value < cfg["threshold"], value
   173	        elif check == "outside_range":
   174	            r = cfg["range"]
   175	            return (value < r[0] or value > r[1]), value
   176	        elif check == "deviation_from_setpoint":
   177	            setpoint = self._setpoint.get(cfg["setpoint_source"])
   178	            return abs(value - setpoint) > cfg["threshold"], value
   179	        else:
   180	            logger.warning("Неизвестный threshold check=%r", check)
   181	            return False, value
   182	
   183	    # ------------------------------------------------------------------
   184	    # composite
   185	    # ------------------------------------------------------------------
   186	
   187	    def _eval_composite(self, alarm_id: str, cfg: dict) -> AlarmEvent | None:
   188	        operator = cfg.get("operator", "AND")
   189	        conditions = cfg.get("conditions", [])
   190	        level = cfg.get("level", "WARNING")
   191	        message = cfg.get("message", f"Alarm {alarm_id}")
   192	
   193	        results = [self._eval_condition(c) for c in conditions]
   194	
   195	        if operator == "AND":
   196	            fired = all(results)
   197	        elif operator == "OR":
   198	            fired = any(results)
   199	        else:
   200	            logger.warning("Неизвестный composite operator=%r", operator)
   201	            return None
   202	
   203	        if not fired:
   204	            return None
   205	
   206	        # Collect channels and values
   207	        channels: list[str] = []
   208	        values: dict[str, float] = {}
   209	        for cond in conditions:
   210	            for ch in self._resolve_channels(cond):
   211	                state = self._state.get(ch)
   212	                if state and ch not in channels:
   213	                    channels.append(ch)
   214	                    values[ch] = state.value
   215	
   216	        return AlarmEvent(
   217	            alarm_id=alarm_id,
   218	            level=level,
   219	            message=str(message),
   220	            triggered_at=time.time(),
   221	            channels=channels,
   222	            values=values,
   223	        )
   224	
   225	    def _eval_condition(self, cond: dict) -> bool:
   226	        """Вычислить одно sub-condition → bool."""
   227	        check = cond.get("check", "above")
   228	
   229	        if check == "any_below":
   230	            channels = self._resolve_channels(cond)
   231	            threshold = cond["threshold"]
   232	            return any(
   233	                (s := self._state.get(ch)) is not None and s.value < threshold for ch in channels
   234	            )
   235	
   236	        elif check == "any_above":
   237	            channels = self._resolve_channels(cond)
   238	            threshold = cond["threshold"]
   239	            return any(
   240	                (s := self._state.get(ch)) is not None and s.value > threshold for ch in channels
   241	            )
   242	
   243	        elif check == "above":
   244	            ch = cond.get("channel")
   245	            if not ch:
   246	                return False
   247	            # Special: phase_elapsed_s
   248	            if ch == "phase_elapsed_s":
   249	                elapsed = self._phase.get_phase_elapsed_s()
   250	                return elapsed > cond["threshold"]
   251	            state = self._state.get(ch)
   252	            return state is not None and state.value > cond["threshold"]
   253	
   254	        elif check == "below":
   255	            ch = cond.get("channel")
   256	            if not ch:
   257	                return False
   258	            state = self._state.get(ch)
   259	            return state is not None and state.value < cond["threshold"]
   260	
   261	        elif check == "rate_above":
   262	            ch = cond.get("channel")
   263	            if not ch:
   264	                return False
   265	            window = cond.get("rate_window_s", _DEFAULT_RATE_WINDOW_S)
   266	            rate = self._rate.get_rate_custom_window(ch, window)
   267	            return rate is not None and rate > cond["threshold"]
   268	
   269	        elif check == "rate_below":
   270	            ch = cond.get("channel")
   271	            if not ch:
   272	                return False
   273	            window = cond.get("rate_window_s", _DEFAULT_RATE_WINDOW_S)
   274	            rate = self._rate.get_rate_custom_window(ch, window)
   275	            return rate is not None and rate < cond["threshold"]
   276	
   277	        elif check == "rate_near_zero":
   278	            ch = cond.get("channel")
   279	            if not ch:
   280	                return False
   281	            window = cond.get("rate_window_s", _DEFAULT_RATE_WINDOW_S)
   282	            rate = self._rate.get_rate_custom_window(ch, window)
   283	            rate_threshold = cond.get("rate_threshold", 0.1)
   284	            return rate is not None and abs(rate) < rate_threshold
   285	
   286	        else:
   287	            logger.warning("Неизвестный composite condition check=%r", check)
   288	            return False
   289	
   290	    # ------------------------------------------------------------------
   291	    # rate
   292	    # ------------------------------------------------------------------
   293	
   294	    def _eval_rate(self, alarm_id: str, cfg: dict) -> AlarmEvent | None:
   295	        channels = self._resolve_channels(cfg)
   296	        check = cfg.get("check", "rate_above")
   297	        window = cfg.get("rate_window_s", _DEFAULT_RATE_WINDOW_S)
   298	        level = cfg.get("level", "WARNING")
   299	        message_tmpl = cfg.get("message", f"Alarm {alarm_id}")
   300	
   301	        for ch in channels:
   302	            rate = self._rate.get_rate_custom_window(ch, window)
   303	            if rate is None:
   304	                continue
   305	
   306	            fired = False
   307	            if check == "rate_above":
   308	                fired = rate > cfg["threshold"]
   309	            elif check == "rate_below":
   310	                fired = rate < cfg["threshold"]
   311	            elif check == "rate_near_zero":
   312	                fired = abs(rate) < cfg.get("rate_threshold", 0.1)
   313	            elif check == "relative_rate_near_zero":
   314	                state = self._state.get(ch)
   315	                if state and state.value > 0:
   316	                    rel_rate = abs(rate / state.value)
   317	                    fired = rel_rate < cfg.get("rate_threshold", 0.01)
   318	
   319	            if fired:
   320	                # Check additional_condition if present
   321	                add_cond = cfg.get("additional_condition")
   322	                if add_cond and not self._eval_condition(add_cond):
   323	                    continue
   324	
   325	                msg = self._format_message(message_tmpl, channel=ch, value=rate)
   326	                return AlarmEvent(
   327	                    alarm_id=alarm_id,
   328	                    level=level,
   329	                    message=msg,
   330	                    triggered_at=time.time(),
   331	                    channels=[ch],
   332	                    values={ch: rate},
   333	                )
   334	        return None
   335	
   336	    # ------------------------------------------------------------------
   337	    # stale
   338	    # ------------------------------------------------------------------
   339	
   340	    def _eval_stale(self, alarm_id: str, cfg: dict) -> AlarmEvent | None:
   341	        timeout = cfg.get("timeout_s", 30.0)
   342	        channels = self._resolve_channels(cfg)
   343	        level = cfg.get("level", "WARNING")
   344	        message_tmpl = cfg.get("message", "Stale data: {channel}")
   345	        now = time.time()
   346	
   347	        for ch in channels:
   348	            state = self._state.get(ch)
   349	            if state is None:
   350	                # Канал никогда не получал данных — тоже stale (если есть данные вообще)
   351	                continue
   352	            if (now - state.timestamp) > timeout:
   353	                msg = self._format_message(message_tmpl, channel=ch, value=0.0)
   354	                return AlarmEvent(
   355	                    alarm_id=alarm_id,
   356	                    level=level,
   357	                    message=msg,
   358	                    triggered_at=now,
   359	                    channels=[ch],
   360	                    values={ch: now - state.timestamp},

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/core/alarm_config.py | sed -n '1,220p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	"""AlarmConfig — загрузка и парсинг конфигурации алармов v3.
     2	
     3	Читает alarms_v3.yaml и возвращает:
     4	  - EngineConfig    — параметры движка (rate_window_s, setpoints…)
     5	  - list[AlarmConfig] — плоский список всех алармов с фазовым фильтром
     6	"""
     7	
     8	from __future__ import annotations
     9	
    10	import copy
    11	from dataclasses import dataclass, field
    12	from pathlib import Path
    13	from typing import Any
    14	
    15	import yaml
    16	
    17	
    18	class AlarmConfigError(RuntimeError):
    19	    """Raised when alarms_v3.yaml cannot be loaded in a fail-closed manner.
    20	
    21	    Distinct class so engine startup maps it to config exit code
    22	    instead of generic runtime crash.
    23	    """
    24	
    25	
    26	# ---------------------------------------------------------------------------
    27	# Dataclasses
    28	# ---------------------------------------------------------------------------
    29	
    30	
    31	@dataclass
    32	class SetpointDef:
    33	    """Описание одного setpoint из секции engine.setpoints."""
    34	
    35	    key: str
    36	    source: str  # "experiment_metadata" | "constant"
    37	    default: float
    38	    unit: str = "K"
    39	
    40	
    41	@dataclass
    42	class EngineConfig:
    43	    """Параметры движка алармов из секции engine."""
    44	
    45	    poll_interval_s: float = 2.0
    46	    rate_window_s: float = 120.0
    47	    rate_min_points: int = 60
    48	    rate_method: str = "linear_fit"
    49	    setpoints: dict[str, SetpointDef] = field(default_factory=dict)
    50	
    51	
    52	@dataclass
    53	class AlarmConfig:
    54	    """Одна alarm-запись, готовая к передаче в AlarmEvaluator.
    55	
    56	    Атрибуты
    57	    ----------
    58	    alarm_id:
    59	        Уникальный идентификатор аларма.
    60	    config:
    61	        Словарь конфигурации (alarm_type, check, threshold, …).
    62	        channel_group уже раскрыт → channels list.
    63	    phase_filter:
    64	        None — работает всегда (global alarm).
    65	        list[str] — только при активной фазе из этого списка.
    66	    notify:
    67	        Список каналов уведомлений: "gui", "telegram", "sound".
    68	    """
    69	
    70	    alarm_id: str
    71	    config: dict[str, Any]
    72	    phase_filter: list[str] | None = None
    73	    notify: list[str] = field(default_factory=list)
    74	
    75	
    76	# ---------------------------------------------------------------------------
    77	# Loader
    78	# ---------------------------------------------------------------------------
    79	
    80	
    81	def load_alarm_config(
    82	    path: str | Path | None = None,
    83	) -> tuple[EngineConfig, list[AlarmConfig]]:
    84	    """Загрузить alarms_v3.yaml → (EngineConfig, list[AlarmConfig]).
    85	
    86	    Если path не задан, ищет config/alarms_v3.yaml рядом с этим модулем
    87	    (поднимаясь до корня пакета).
    88	
    89	    Raises AlarmConfigError if file is missing, malformed, non-mapping,
    90	    or contains coercion errors in alarm definitions.
    91	    """
    92	    if path is None:
    93	        path = _find_default_config()
    94	        if path is None:
    95	            raise AlarmConfigError(
    96	                "alarms_v3.yaml not found: no path provided and no default "
    97	                "config located via standard search. Refusing to start alarm "
    98	                "engine without alarm configuration."
    99	            )
   100	    path = Path(path)
   101	    if not path.exists():
   102	        raise AlarmConfigError(
   103	            f"alarms_v3.yaml not found at {path} — refusing to start "
   104	            f"alarm engine without alarm configuration"
   105	        )
   106	
   107	    try:
   108	        with open(path, encoding="utf-8") as f:
   109	            raw = yaml.safe_load(f)
   110	    except yaml.YAMLError as exc:
   111	        raise AlarmConfigError(f"alarms_v3.yaml at {path}: YAML parse error — {exc}") from exc
   112	
   113	    if not isinstance(raw, dict):
   114	        raise AlarmConfigError(
   115	            f"alarms_v3.yaml at {path} is malformed (expected mapping, got {type(raw).__name__})"
   116	        )
   117	
   118	    channel_groups: dict[str, list[str]] = raw.get("channel_groups", {})
   119	    try:
   120	        engine_cfg = _parse_engine_config(raw.get("engine", {}))
   121	        alarms: list[AlarmConfig] = []
   122	
   123	        # --- Global alarms ---
   124	        for alarm_id, alarm_raw in raw.get("global_alarms", {}).items():
   125	            cfg = _expand_alarm(alarm_id, alarm_raw, channel_groups)
   126	            if cfg is not None:
   127	                alarms.append(cfg)
   128	
   129	        # --- Phase alarms ---
   130	        for phase_name, phase_dict in raw.get("phase_alarms", {}).items():
   131	            if not isinstance(phase_dict, dict):
   132	                continue
   133	            for alarm_id, alarm_raw in phase_dict.items():
   134	                cfg = _expand_alarm(alarm_id, alarm_raw, channel_groups, phase_filter=[phase_name])
   135	                if cfg is not None:
   136	                    alarms.append(cfg)
   137	    except (ValueError, TypeError, KeyError, AttributeError) as exc:
   138	        raise AlarmConfigError(
   139	            f"alarms_v3.yaml at {path}: invalid config value — {type(exc).__name__}: {exc}"
   140	        ) from exc
   141	
   142	    return engine_cfg, alarms
   143	
   144	
   145	# ---------------------------------------------------------------------------
   146	# Internal helpers
   147	# ---------------------------------------------------------------------------
   148	
   149	
   150	def _parse_engine_config(raw: dict) -> EngineConfig:
   151	    setpoints: dict[str, SetpointDef] = {}
   152	    for key, sp_raw in raw.get("setpoints", {}).items():
   153	        setpoints[key] = SetpointDef(
   154	            key=key,
   155	            source=sp_raw.get("source", "constant"),
   156	            default=float(sp_raw.get("default", 0.0)),
   157	            unit=sp_raw.get("unit", "K"),
   158	        )
   159	    return EngineConfig(
   160	        poll_interval_s=float(raw.get("poll_interval_s", 2.0)),
   161	        rate_window_s=float(raw.get("rate_window_s", 120.0)),
   162	        rate_min_points=int(raw.get("rate_min_points", 60)),
   163	        rate_method=str(raw.get("rate_method", "linear_fit")),
   164	        setpoints=setpoints,
   165	    )
   166	
   167	
   168	def _expand_alarm(
   169	    alarm_id: str,
   170	    alarm_raw: Any,
   171	    channel_groups: dict[str, list[str]],
   172	    phase_filter: list[str] | None = None,
   173	) -> AlarmConfig | None:
   174	    """Создать AlarmConfig из raw YAML-словаря, раскрыв channel_group."""
   175	    if not isinstance(alarm_raw, dict):
   176	        return None
   177	
   178	    cfg = copy.deepcopy(alarm_raw)
   179	    notify: list[str] = cfg.pop("notify", []) or []
   180	    # Remove non-evaluator keys
   181	    for key in ("gui_action", "side_effect"):
   182	        cfg.pop(key, None)
   183	
   184	    # Expand channel_group → channels
   185	    _expand_channel_group(cfg, channel_groups)
   186	
   187	    # Expand channel_group inside composite conditions
   188	    for cond in cfg.get("conditions", []):
   189	        if isinstance(cond, dict):
   190	            _expand_channel_group(cond, channel_groups)
   191	
   192	    return AlarmConfig(
   193	        alarm_id=alarm_id,
   194	        config=cfg,
   195	        phase_filter=phase_filter,
   196	        notify=notify if isinstance(notify, list) else [notify],
   197	    )
   198	
   199	
   200	def _expand_channel_group(cfg: dict, groups: dict[str, list[str]]) -> None:
   201	    """Заменить channel_group → channels in-place."""
   202	    group_name = cfg.pop("channel_group", None)
   203	    if group_name and group_name in groups:
   204	        cfg["channels"] = list(groups[group_name])
   205	
   206	
   207	def _find_default_config() -> Path | None:
   208	    """Найти config/alarms_v3.yaml, поднимаясь от текущего файла."""
   209	    here = Path(__file__).resolve()
   210	    for parent in here.parents:
   211	        candidate = parent / "config" / "alarms_v3.yaml"
   212	        if candidate.exists():
   213	            return candidate
   214	    return None

exec
/opt/homebrew/bin/bash -lc "nl -ba docs/bug_B1_zmq_idle_death_handoff.md | sed -n '1,220p'
nl -ba docs/bug_B1_zmq_idle_death_handoff.md | sed -n '220,460p'
nl -ba docs/bug_B1_zmq_idle_death_handoff.md | sed -n '460,700p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	# Bug B1 — ZMQ subprocess command channel dies — Codex handoff
     2	
     3	> Purpose: complete evidence dump + Codex analysis + agreed fix plan.
     4	>
     5	> **Status 2026-04-20 afternoon:** Codex review completed. Original
     6	> "idle-death" hypothesis proved WRONG. Revised root cause: single
     7	> long-lived REQ socket accumulates state and becomes unrecoverable
     8	> after platform-specific trigger. Fix plan: per-command ephemeral
     9	> REQ socket + launcher watchdog for command-channel-only failure.
    10	> Implementation batch spec: `CC_PROMPT_IV_6_ZMQ_BRIDGE_FIX.md`.
    11	>
    12	> See section "Codex revised analysis" below for details.
    13	
    14	---
    15	
    16	## TL;DR
    17	
    18	Python 3.14.3 on macOS Darwin + pyzmq 25.x, ZMQ REQ socket in a
    19	`multiprocessing.Process` child hangs on `recv_string()` after some
    20	idle time, exactly 35 seconds (= `RCVTIMEO`). After first hang, ALL
    21	subsequent commands on the same socket ALSO hang 35s. Socket never
    22	recovers. Bug triggers faster at lower command rates.
    23	
    24	**Not a general pyzmq crash.** Direct in-process Python client (no
    25	subprocess) has not been tested for long-soak behavior. Engine REP
    26	itself is healthy when tested directly.
    27	
    28	---
    29	
    30	## System
    31	
    32	- **OS:** macOS (darwin), laptop + MacBook Pro M5
    33	- **Python:** 3.14.3 (from python.org installer, Feb 2026 release)
    34	- **pyzmq:** version 25.x (check `.venv/bin/pip show pyzmq`)
    35	- **libzmq:** bundled with pyzmq wheel
    36	- **Transport:** `tcp://127.0.0.1:5555` (PUB/SUB) and
    37	  `tcp://127.0.0.1:5556` (REQ/REP), both loopback TCP
    38	- **Process model:** engine = separate OS process, GUI process
    39	  spawns a `multiprocessing.Process` child that owns ALL ZMQ
    40	  sockets on the GUI side; GUI↔subprocess communication via
    41	  `mp.Queue`. Rationale: Windows libzmq `signaler.cpp` crash
    42	  isolation (but bug manifests on macOS).
    43	
    44	---
    45	
    46	## Reproduction: 100%
    47	
    48	### Symptom variant A (1 cmd/sec soak, current)
    49	
    50	After TCP_KEEPALIVE fix applied:
    51	
    52	```
    53	Run 1: 55 commands OK, cmd #58 FAIL 35s (uptime 92s), 0/3 recovery
    54	Run 2: 20 commands OK, cmd #22 FAIL 35s (uptime 56s), 0/4 recovery
    55	Run 3: 4 commands OK,  cmd #5  FAIL 35s (uptime 39s), 0/5 recovery  (before fix)
    56	```
    57	
    58	`tools/diag_zmq_bridge_extended.py` — instantiates `ZmqBridge`, sends
    59	`{"cmd": "safety_status"}` every 1 second for 180 seconds.
    60	
    61	Exact timings variable across runs (4-90s uptime to first fail).
    62	
    63	### Symptom variant B (rate-dependent)
    64	
    65	`tools/diag_zmq_idle_hypothesis.py`:
    66	
    67	```
    68	Phase 1 RAPID  5Hz    (200ms idle) for 60s: 291/291 OK, 0 fails
    69	Phase 2 SPARSE 0.33Hz (3000ms idle) for 60s: 9 OK, cmd #10 FAIL 35s
    70	Phase 3 RECOVER 5Hz              30s: cmd #1 FAIL immediately
    71	```
    72	
    73	**High command rate never fails. Low rate fails reproducibly. Once
    74	failed, even rapid-fire commands continue to fail.** Socket is
    75	permanently dead after first timeout.
    76	
    77	### Symptom variant C (rapid initial burst)
    78	
    79	`tools/diag_zmq_bridge.py`:
    80	
    81	```
    82	Phase 1: 5 sequential commands, all <1ms OK
    83	Phase 2: 10 concurrent commands, all <2ms OK
    84	Phase 3: 1 cmd/sec for 60s:
    85	  #10 OK, #20 OK, #28 FAIL 35s
    86	```
    87	
    88	After 15 rapid commands + 28 sec sparse → fail. Rapid burst
    89	"primes" the socket, delays eventual failure.
    90	
    91	---
    92	
    93	## What works
    94	
    95	**Engine REP socket is healthy.** Direct Python client test:
    96	
    97	```python
    98	import zmq, json, time
    99	ctx = zmq.Context()
   100	req = ctx.socket(zmq.REQ)
   101	req.setsockopt(zmq.RCVTIMEO, 5000)
   102	req.setsockopt(zmq.SNDTIMEO, 5000)
   103	req.connect("tcp://127.0.0.1:5556")
   104	req.send_string(json.dumps({"cmd": "safety_status"}))
   105	reply = req.recv_string()  # GOT REPLY in 0.001s
   106	```
   107	
   108	**Engine itself runs fine for minutes.** Readings flow (`sub_drain_loop`
   109	in subprocess receives steady 20 readings/sec), heartbeats every 30s,
   110	SQLite writes ~9000 entries per 10 minutes.
   111	
   112	**Raw subprocess without ZmqBridge wrapping works short-term.**
   113	`tools/diag_zmq_subprocess.py` — spawns `zmq_bridge_main()` directly,
   114	runs both spawn and fork mp start_methods. First command GOT REPLY
   115	in 0.002s on both. (Did not run long soak.)
   116	
   117	---
   118	
   119	## Attempted fix (did NOT resolve)
   120	
   121	Added TCP_KEEPALIVE options to all four loopback sockets to prevent
   122	macOS kernel idle reaping:
   123	
   124	```python
   125	sock.setsockopt(zmq.TCP_KEEPALIVE, 1)
   126	sock.setsockopt(zmq.TCP_KEEPALIVE_IDLE, 10)
   127	sock.setsockopt(zmq.TCP_KEEPALIVE_INTVL, 5)
   128	sock.setsockopt(zmq.TCP_KEEPALIVE_CNT, 3)
   129	```
   130	
   131	Applied to:
   132	- `src/cryodaq/core/zmq_subprocess.py`: REQ socket in
   133	  `cmd_forward_loop::_new_req_socket()`, SUB socket in
   134	  `sub_drain_loop`
   135	- `src/cryodaq/core/zmq_bridge.py`: `ZMQPublisher` PUB socket,
   136	  `ZMQCommandServer` REP socket
   137	
   138	**Partial effect observed:** time to first failure increased (4s→22s
   139	→55s across 3 runs). But failures still occur, and after first
   140	failure socket is still permanently dead.
   141	
   142	---
   143	
   144	## Code paths
   145	
   146	### Engine side (`src/cryodaq/core/zmq_bridge.py`)
   147	
   148	- `ZMQCommandServer.start()` — creates REP socket, binds
   149	  `tcp://127.0.0.1:5556`, starts `_serve_loop()` asyncio task
   150	- `ZMQCommandServer._serve_loop()` — `while running: recv + handler +
   151	  send`. Handler wrapped in `asyncio.wait_for(timeout=_timeout_for(cmd))`.
   152	  Fast commands get 2s envelope, slow commands (experiment_finalize etc)
   153	  get 30s envelope.
   154	- `ZMQCommandServer._run_handler()` — IV.3 Finding 7: ALWAYS returns a
   155	  dict. REP socket state-machine-sensitive, so handler timeouts yield
   156	  `{ok: False, error: "handler timeout"}` rather than silent exception.
   157	- `_on_serve_task_done()` — if serve loop crashes, restart it via
   158	  `loop.call_soon`.
   159	
   160	### GUI subprocess side (`src/cryodaq/core/zmq_subprocess.py`)
   161	
   162	- `zmq_bridge_main()` — entry point for `mp.Process` child
   163	- Spawns two threads:
   164	  - `sub_drain_loop` — owns SUB socket, drains readings, emits
   165	    heartbeats every 5s via `data_queue.put_nowait()`
   166	  - `cmd_forward_loop` — owns REQ socket, pulls commands from
   167	    `cmd_queue.get(timeout=0.5)`, sends via `req.send_string()`,
   168	    waits on `req.recv_string()` (RCVTIMEO=35s)
   169	- On `zmq.ZMQError` (including `zmq.Again` from RCVTIMEO): close and
   170	  recreate REQ socket
   171	
   172	### GUI main process (`src/cryodaq/gui/zmq_client.py`)
   173	
   174	- `ZmqBridge` class — starts mp.Process, spawns
   175	  `_consume_replies` thread that reads replies from `reply_queue`,
   176	  routes to Future via `_pending[rid]` dict
   177	- `send_command()` — puts cmd in `cmd_queue`, waits on
   178	  `future.result(timeout=_CMD_REPLY_TIMEOUT_S=35.0)`
   179	
   180	---
   181	
   182	## Hypotheses considered and ruled out
   183	
   184	1. **Engine REP wedge** — Ruled out. Direct zmq client gets 0.001s
   185	   reply mid-session when ZmqBridge subprocess is in failed state.
   186	2. **mp.Queue back-pressure** — Considered, not tested. Data queue has
   187	   maxsize=10000. In 180s at 20 readings/sec = 3600 readings, no
   188	   overflow. Plus `diag_zmq_idle_hypothesis.py` explicitly drains
   189	   readings (Phase 3 included drain call) yet still fails.
   190	3. **`asyncio.CancelledError` on engine side wedging REP** — Code
   191	   explicitly handles this: always sends reply before re-raising.
   192	4. **Windows libzmq signaler.cpp crash** — Original reason for
   193	   subprocess isolation. Does not apply on macOS.
   194	5. **Message size / serialization** — All commands tested are tiny
   195	   (<200 bytes).
   196	6. **fork vs spawn mp start method** — Both fail same way per
   197	   `diag_zmq_subprocess.py` output (both get heartbeats/readings).
   198	
   199	## Still open
   200	
   201	1. **ZMQ internal state machine after recreate_socket**. In
   202	   `cmd_forward_loop`, after RCVTIMEO:
   203	   ```python
   204	   req.close(linger=0)
   205	   req = _new_req_socket()  # connect()s fresh
   206	   ```
   207	   Why does a fresh REQ socket still hang? If engine REP is healthy
   208	   (verified), a fresh connect() should produce working socket.
   209	
   210	2. **Why rate-dependent?** What changes between 5Hz and 0.33Hz?
   211	   Candidates:
   212	   - pyzmq io_threads starvation under specific timing
   213	   - asyncio event loop on engine side batching differently
   214	   - SQLite WAL checkpoint or other 30s-periodic operation on engine
   215	     that briefly blocks event loop, and only happens to catch low-rate
   216	     client
   217	   - Kernel network stack loopback optimization that expires
   218	
   219	3. **Why is failure permanent after first hang?** If issue is
   220	   transient (idle reap, event-loop stall), fresh socket should
   220	   transient (idle reap, event-loop stall), fresh socket should
   221	   recover. It doesn't. Suggests persistent corruption in pyzmq
   222	   ZMQ context OR in engine's REP state (but engine responds to
   223	   fresh direct clients fine).
   224	
   225	4. **Is it `zmq.Again` or something else?** Current subprocess
   226	   catches `zmq.ZMQError` broadly. RCVTIMEO normally produces
   227	   `zmq.Again` subclass. But the warning "REP timeout on
   228	   safety_status (Resource temporarily unavailable)" observed in
   229	   `diag_zmq_idle_hypothesis.py` output confirms it's indeed
   230	   `zmq.Again`. Yet reply eventually arrives later (see "Unmatched
   231	   ZMQ reply" log).
   232	
   233	---
   234	
   235	## Observations that may be clues
   236	
   237	1. Output says "Unmatched ZMQ reply" sometimes — this means reply DID
   238	   make it to `reply_queue` in main process, but Future was already
   239	   resolved (by timeout) and removed from `_pending`. So reply
   240	   actually arrived eventually. Not a dead socket, but a very late
   241	   one. Inconsistent with "permanent failure" — unless some
   242	   replies arrive and some don't.
   243	
   244	2. Timing of first failure shifted with TCP_KEEPALIVE (4s→55s).
   245	   Keepalive had SOME effect. Suggests kernel-level interaction is
   246	   real but keepalive alone insufficient.
   247	
   248	3. macOS 12+ has known issues with aggressive loopback TCP cleanup
   249	   under specific `sysctl net.inet.tcp.*` defaults. Worth checking
   250	   current settings:
   251	   ```
   252	   sysctl net.inet.tcp.keepidle
   253	   sysctl net.inet.tcp.keepintvl
   254	   sysctl net.inet.tcp.always_keepalive
   255	   sysctl net.inet.tcp.msl
   256	   ```
   257	
   258	4. `pyzmq.utils.z85` / libzmq `zmq_close_socket` docs mention ZMQ
   259	   context retaining peer routing tables — "fresh" socket on same
   260	   context might inherit stale state.
   261	
   262	---
   263	
   264	## Question for Codex
   265	
   266	**Primary:** Why does REQ socket (recreated fresh after RCVTIMEO)
   267	continue hanging, when engine REP is verified healthy via direct
   268	client tests?
   269	
   270	**Secondary:** Is this a known pyzmq + Python 3.14 + macOS
   271	regression? (Python 3.14.3 released Feb 2026 — may have
   272	mp.Queue changes that interact poorly with libzmq context in
   273	child process.)
   274	
   275	**Tertiary:** Should the architecture switch to:
   276	- (a) `ipc:///tmp/cryodaq-pub.sock` (Unix domain sockets, no
   277	  TCP kernel layer) — minimal code change, engine + subprocess
   278	  both update `DEFAULT_PUB_ADDR`/`DEFAULT_CMD_ADDR`
   279	- (b) In-process threads in GUI (drop mp.Process) — removes
   280	  subprocess isolation but pyzmq is thread-safe. Windows
   281	  rationale doesn't apply on macOS/Linux.
   282	- (c) Keep architecture, add watchdog that kills + restarts
   283	  subprocess when any command times out
   284	
   285	Recommended fix (from the architect's POV but unverified): try
   286	(a) first — smallest change, addresses loopback TCP entirely,
   287	backwards-compatible on Linux. Test with the same diag suite.
   288	
   289	---
   290	
   291	## Files to share with Codex
   292	
   293	- This doc (`docs/bug_B1_zmq_idle_death_handoff.md`)
   294	- `src/cryodaq/core/zmq_subprocess.py` (with TCP_KEEPALIVE fix)
   295	- `src/cryodaq/core/zmq_bridge.py` (with TCP_KEEPALIVE fix)
   296	- `src/cryodaq/gui/zmq_client.py` (ZmqBridge wrapper)
   297	- `tools/diag_zmq_bridge_extended.py` (reproducer, 3 min to run)
   298	- `tools/diag_zmq_idle_hypothesis.py` (rate dependence reproducer)
   299	- `/tmp/engine_debug.log` from one of the failing runs if available
   300	
   301	## Environment info for Codex to check
   302	
   303	```bash
   304	# versions
   305	.venv/bin/python -c "import sys, zmq; print(sys.version); print('pyzmq', zmq.__version__); print('libzmq', zmq.zmq_version())"
   306	
   307	# macOS TCP tuning
   308	sysctl net.inet.tcp.keepidle net.inet.tcp.keepintvl net.inet.tcp.always_keepalive net.inet.tcp.msl
   309	
   310	# macOS version
   311	sw_vers
   312	```
   313	
   314	---
   315	
   316	## Reproduction steps for Codex
   317	
   318	```bash
   319	cd /Users/vladimir/Projects/cryodaq
   320	pkill -9 -f cryodaq; sleep 2
   321	rm -f data/.engine.lock data/.launcher.lock
   322	
   323	# Terminal 1: engine
   324	CRYODAQ_MOCK=1 .venv/bin/cryodaq-engine --mock > /tmp/engine_debug.log 2>&1 &
   325	
   326	# Terminal 2 (after engine reports ═══ CryoDAQ Engine запущен ═══):
   327	.venv/bin/python tools/diag_zmq_bridge_extended.py
   328	
   329	# Expected BEFORE any fix: first FAIL within ~30-90s, then 0% recovery
   330	# After TCP_KEEPALIVE fix (current state): same, but first fail later
   331	# on average
   332	```
   333	
   334	---
   335	
   336	*Prepared by Claude (architect) for Codex review, 2026-04-20.*
   337	*After 4 diag iterations + 1 fix attempt. Ready for architectural*
   338	*review / alternative transport exploration.*
   339	
   340	---
   341	
   342	# Codex revised analysis (2026-04-20 afternoon)
   343	
   344	## Ubuntu data point
   345	
   346	During lab session 2026-04-20:
   347	
   348	- **Real system** (`./start.sh`, not diag tool) — first REP timeout on
   349	  `experiment_status` at **exactly 120s** after subprocess start.
   350	- Ubuntu 22.04, Linux 5.15.0-173, Python 3.12.13, pyzmq 26.4.0,
   351	  libzmq 4.3.5.
   352	- TCP_KEEPALIVE fix already applied (commit `f5f9039`).
   353	- Linux kernel defaults `net.ipv4.tcp_keepalive_time = 7200s` mean
   354	  kernel would NOT reap idle loopback for 2 hours by default
   355	  — the 120s failure cannot be kernel idle reaping.
   356	
   357	## Revised root cause
   358	
   359	NOT idle death. NOT loopback TCP kernel reaping.
   360	
   361	**Actual root cause:** the GUI-side subprocess command plane uses
   362	**one long-lived REQ socket** in `cmd_forward_loop()`:
   363	
   364	- Created once at `src/cryodaq/core/zmq_subprocess.py` in
   365	  `_new_req_socket()` helper
   366	- Configured with `REQ_RELAXED` + `REQ_CORRELATE`
   367	- Reused indefinitely across ALL commands
   368	
   369	On both platforms, something eventually pushes that single connection
   370	into a bad state — on macOS sparse cadence triggers it faster, on
   371	Ubuntu it appears connection-age or socket-state related rather than
   372	idle-related. Once one REQ connection goes bad, the **entire command
   373	plane degrades** because every GUI command shares it.
   374	
   375	ZeroMQ's own reliable request-reply guidance is explicitly
   376	**"poll / timeout / close / reopen"** on failure (Guide ch.4). Our
   377	current design violates that: we trust one long-lived REQ socket.
   378	
   379	## TCP_KEEPALIVE fix assessment
   380	
   381	The TCP_KEEPALIVE fix applied at commit `f5f9039` is **NOT
   382	participating** in the observed failure modes:
   383	
   384	- Active diagnostics run at 1 Hz or 5 Hz — socket never sits idle
   385	  for 10s (our `TCP_KEEPALIVE_IDLE`) so probes never fire.
   386	- Linux kernel wouldn't reap idle loopback for 7200s anyway —
   387	  aggressive 25s keepalive cannot help.
   388	- Partial delay of failure on macOS (4s→55s uptime) may be coincidence
   389	  or benign side-effect of socket configuration churn.
   390	
   391	Recommendation: **remove TCP_KEEPALIVE from the command path** in
   392	the same fix batch. Can keep on PUB/SUB path (orthogonal, unused
   393	during active polling).
   394	
   395	## Pressure display bug is SEPARATE from B1
   396	
   397	TopWatchBar pressure display is **reading-driven** (`on_reading()`
   398	matching `ch.endswith("/pressure")`), not command-driven. It flows
   399	via the SUB path, which continues working even when command path
   400	is dead.
   401	
   402	The "pressure shows em-dash" observation does NOT help diagnose B1.
   403	Separate investigation needed — most likely:
   404	- Channel ID renamed in `config/channels.yaml` (uncommitted edits)
   405	- MainWindowV2 reading dispatch broken by recent overlay rewrites
   406	
   407	## Agreed fix plan
   408	
   409	### Primary fix: per-command ephemeral REQ socket
   410	
   411	**Change:** `cmd_forward_loop()` in `zmq_subprocess.py`:
   412	
   413	BEFORE (current):
   414	```python
   415	req = _new_req_socket()  # created ONCE, outer scope
   416	try:
   417	    while not shutdown_event.is_set():
   418	        cmd = cmd_queue.get(timeout=0.5)
   419	        try:
   420	            req.send_string(json.dumps(cmd))
   421	            reply_raw = req.recv_string()
   422	            reply = json.loads(reply_raw)
   423	        except zmq.ZMQError:
   424	            # recover: close + recreate on same context
   425	            req.close(linger=0)
   426	            req = _new_req_socket()
   427	        ...
   428	finally:
   429	    req.close(linger=0)
   430	```
   431	
   432	AFTER (proposed):
   433	```python
   434	while not shutdown_event.is_set():
   435	    cmd = cmd_queue.get(timeout=0.5)
   436	    req = _new_req_socket()  # fresh for EACH command
   437	    try:
   438	        req.send_string(json.dumps(cmd))
   439	        reply_raw = req.recv_string()
   440	        reply = json.loads(reply_raw)
   441	    except zmq.ZMQError as exc:
   442	        reply = {"ok": False, "error": str(exc)}
   443	        # emit structured cmd_timeout control message
   444	    finally:
   445	        req.close(linger=0)
   446	    # reply routing unchanged
   447	```
   448	
   449	Plus:
   450	- Remove `REQ_RELAXED` and `REQ_CORRELATE` from `_new_req_socket()`
   451	  (only needed for stateful recovery — unnecessary with ephemeral).
   452	- Remove `TCP_KEEPALIVE*` from command-path REQ + engine-side REP.
   453	- Emit structured `{"__type": "cmd_timeout", ...}` message to
   454	  `data_queue` on any command failure (not just string warning).
   455	
   456	### Secondary fix: command-channel watchdog in launcher
   457	
   458	**Change:** `src/cryodaq/launcher.py` `_poll_bridge_data()` periodic
   459	check:
   460	
   460	
   461	Current logic restarts bridge on:
   462	- Dead subprocess
   463	- Stale heartbeat (>30s)
   464	- Stalled data flow (>30s)
   465	
   466	Missing: **command timeouts while data flow is healthy.** Add
   467	`bridge.command_channel_stalled(timeout_s=10.0)` check; on true,
   468	restart bridge.
   469	
   470	### GUI-side infrastructure
   471	
   472	**Change:** `src/cryodaq/gui/zmq_client.py`:
   473	
   474	- Add `_last_cmd_timeout: float = 0.0` field.
   475	- In `poll_readings()` handle `__type == "cmd_timeout"` separately
   476	  (not just as warning string).
   477	- Add `command_channel_stalled(timeout_s: float) -> bool` method.
   478	
   479	## Why this works cross-platform
   480	
   481	The fix **removes shared accumulated state entirely**. Each command
   482	gets a fresh TCP connection, fresh ZMTP handshake, fresh REQ
   483	state machine. There is no long-lived socket to degrade.
   484	
   485	- macOS: even if something in pyzmq 25.x loopback TCP has a subtle
   486	  state bug, fresh socket-per-command never hits it.
   487	- Ubuntu: even if libzmq 4.3.5 has some 120s internal timer on
   488	  persistent REQ sockets, fresh socket resets that clock per command.
   489	- Windows: subprocess crash-isolation model preserved (ipc:// or
   490	  threads would break that).
   491	
   492	## Costs
   493	
   494	- Slight TCP connect/close churn per command. At 1 Hz command rate
   495	  this is trivially cheap (loopback connect is microseconds).
   496	- Very minor per-command latency bump (likely <1ms).
   497	- Re-establishes TCP connection per call — irrelevant on loopback,
   498	  would matter on real network but we never plan to go off loopback.
   499	
   500	## Risks
   501	
   502	- Watchdog too aggressive → false restarts on transient slow
   503	  commands. Mitigation: short streak / recent-window threshold.
   504	- Missing edge case where ephemeral REQ creation itself fails
   505	  under sustained load. Mitigation: error handling around
   506	  `_new_req_socket()` with fallback to structured error reply.
   507	
   508	## Verification plan
   509	
   510	### macOS
   511	```bash
   512	CRYODAQ_MOCK=1 .venv/bin/cryodaq-engine --mock &
   513	.venv/bin/python tools/diag_zmq_idle_hypothesis.py
   514	# Expected: all 3 phases 0 failures
   515	
   516	.venv/bin/python tools/diag_zmq_bridge_extended.py
   517	# Expected: 180/180 OK
   518	
   519	.venv/bin/cryodaq   # real launcher
   520	# Leave idle 15+ min, verify no REP timeout warnings
   521	```
   522	
   523	### Ubuntu
   524	```bash
   525	./start.sh
   526	# Leave idle 15+ min, verify experiment_status continues
   527	# No timeout at 120s mark
   528	
   529	.venv/bin/python tools/diag_zmq_bridge_extended.py
   530	# Expected: 180/180 OK
   531	```
   532	
   533	### Watchdog validation
   534	After primary fix, inject synthetic cmd_timeout via test harness:
   535	- Data path stays alive (readings continue)
   536	- Launcher detects command-channel stalled
   537	- Bridge restarts
   538	- Commands resume
   539	
   540	## References
   541	
   542	- ZeroMQ Guide ch.4 reliable request-reply: https://zguide.zeromq.org/docs/chapter4/
   543	- libzmq zmq_setsockopt REQ_RELAXED/REQ_CORRELATE: https://libzmq.readthedocs.io/en/latest/zmq_setsockopt.html
   544	- libzmq issue #4673 (sparse-traffic oddities): https://github.com/zeromq/libzmq/issues/4673
   545	
   546	---
   547	
   548	*Codex analysis reviewed and endorsed by architect (Claude) 2026-04-20.*
   549	*Implementation handed to CC via `CC_PROMPT_IV_6_ZMQ_BRIDGE_FIX.md`.*
   550	
   551	---
   552	
   553	# 2026-04-20 evening update — IV.6 outcome + IV.7 plan
   554	
   555	## IV.6 landed at `be51a24` but did NOT fix B1
   556	
   557	Per-command ephemeral REQ socket + launcher command-channel
   558	watchdog shipped as Codex recommended. 60/60 unit tests green.
   559	Full pytest subtree 1775/1776 (1 unrelated flaky). Ran Stage 3
   560	diag tools against mock engine on macOS — **B1 still reproduces
   561	with structurally identical timing**:
   562	
   563	- `diag_zmq_idle_hypothesis.py` SPARSE_0.33HZ: cmd #8 FAIL at
   564	  uptime 56 s (pre-fix was cmd #10 at ~30 s).
   565	- `diag_zmq_bridge_extended.py`: cmd #48 FAIL at uptime 82 s,
   566	  0/3 recovery thereafter (pre-fix was cmd #28 at 92 s).
   567	- RAPID_5 Hz path still clean (295/295), matching pre-fix rate
   568	  dependence.
   569	
   570	**Codex's shared-REQ-state hypothesis FALSIFIED.** Removing the
   571	long-lived socket did not eliminate the failure. Engine REP goes
   572	silently unresponsive after ~30-90 s of bridge uptime while the
   573	asyncio loop, data-plane PUB, heartbeats, scheduler writes, and
   574	plugin ticks all remain healthy. Root cause is elsewhere.
   575	
   576	IV.6 was still committed as `be51a24` on Vladimir's explicit
   577	directive — the architectural improvement stands regardless of
   578	whether it individually closed B1.
   579	
   580	## IV.6 watchdog regression: restart storm
   581	
   582	`_last_cmd_timeout` persisted across watchdog-triggered bridge
   583	restart. Fresh subprocess immediately saw stale signal on next
   584	`_poll_bridge_data` tick → another restart → storm (30-40 /min
   585	on Ubuntu). Hotfix: 60 s cooldown + missing `return` after
   586	restart. See `src/cryodaq/launcher.py`, commit TBD (watchdog
   587	cooldown hotfix).
   588	
   589	## Next attempt: IV.7 `ipc://` transport
   590	
   591	Original handoff's fallback (a) becomes the working hypothesis.
   592	Given:
   593	
   594	- idle TCP reaping ruled out (Linux default keepalive 7200 s,
   595	  active polling never idled past 1 s)
   596	- shared-REQ accumulated state ruled out (IV.6 eliminated it
   597	  without fixing B1)
   598	- everything above the transport verified healthy during failure
   599	  window
   600	
   601	The remaining candidate is the TCP-loopback layer itself — libzmq
   602	handling, pyzmq asyncio integration, or kernel loopback state
   603	under rapid connect/disconnect churn. Unix domain sockets via
   604	`ipc://` bypass TCP entirely and are libzmq's recommended
   605	transport for same-host IPC.
   606	
   607	**IV.7 spec:** `CC_PROMPT_IV_7_IPC_TRANSPORT.md`. Change two
   608	constants + add stale-socket cleanup helper + update diag tools
   609	to import the new defaults. Single commit, ~20 LOC source. If
   610	both diag tools show 0 failures post-change on macOS **and**
   611	Ubuntu → tag `0.34.0`. If failures persist → B1 is higher than
   612	the transport; consider in-process threading or pyzmq
   613	replacement as next strategy.
   614	
   615	## Related fixes shipped during B1 investigation (2026-04-20)
   616	
   617	### `aabd75f` — pressure display fix
   618	
   619	`engine.py::_create_instruments()` was silently dropping the
   620	`validate_checksum` YAML key when constructing `ThyracontVSP63D`.
   621	Driver default (`True`, flipped in Phase 2c Codex F.2) then
   622	rejected every VSP206 read as checksum mismatch → NaN →
   623	TopWatchBar silently dropped. Root cause was a loader-wiring
   624	gap, not a driver bug. Single-line fix:
   625	
   626	```python
   627	driver = ThyracontVSP63D(
   628	    name, resource,
   629	    baudrate=baudrate,
   630	    validate_checksum=bool(entry.get("validate_checksum", True)),
   631	    mock=mock,
   632	)
   633	```
   634	
   635	Operator opt-out path via `instruments.local.yaml` now actually
   636	works.
   637	
   638	### `74dbbc7` — xml_safe sanitizer
   639	
   640	Keithley VISA resource strings contain `\x00` per NI-VISA spec.
   641	python-docx rejected them as XML 1.0 incompatible when embedded
   642	in auto-reports. Fix:
   643	
   644	- `src/cryodaq/utils/xml_safe.py` strips XML-illegal control
   645	  chars (NULL, 0x01-0x08, 0x0B, 0x0C, 0x0E-0x1F, 0x7F); preserves
   646	  Tab/LF/CR.
   647	- Applied at all `add_paragraph()` / `cell.text` sites in
   648	  `src/cryodaq/reporting/sections.py`.
   649	- `src/cryodaq/core/experiment.py:782` logger upgraded from
   650	  `log.warning` to `log.exception` so future report-generation
   651	  failures carry tracebacks (that's how the bug survived this
   652	  long — only the exception message was logged).
   653	
   654	## Still-open orthogonal bugs (not B1, not blocking 0.34.0)
   655	
   656	1. `alarm_v2.py::_eval_condition` raises `KeyError 'threshold'`
   657	   when evaluating `cooldown_stall` composite — one sub-condition
   658	   is missing a `threshold` field (probably stale/rate-type).
   659	   Log spam every ~2 s. Engine does not crash. Mini-fix:
   660	   `cond.get("threshold")` defensive access OR config audit.
   661	
   662	2. Thyracont `_try_v1_probe` (lines 157-166) only checks response
   663	   prefix `<addr>M`, does NOT validate checksum even when
   664	   `self._validate_checksum=True`. Read path DOES validate. Driver
   665	   can "successfully connect" and then emit NaN-sensor_error
   666	   forever. That's what bit us this morning. Proper hardening:
   667	   make probe consistent with read path. ~5 LOC.
   668	
   669	---
   670	
   671	*Evening update by architect (Claude Opus 4.7, web), handing off to*
   672	*GLM-5.1 via CCR for the coming days while Vladimir's Anthropic*
   673	*weekly limit recovers. See `HANDOFF_2026-04-20_GLM.md` for full*
   674	*context transfer.*

exec
/opt/homebrew/bin/bash -lc "nl -ba docs/decisions/2026-04-24-b2b4fb5-investigation.md | sed -n '1,260p'
nl -ba docs/decisions/2026-04-24-d1-d4a-execution.md | sed -n '1,180p'
nl -ba docs/decisions/2026-04-23-cleanup-baseline.md | sed -n '1,190p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	# 2026-04-24 — b2b4fb5 hypothesis investigation
     2	
     3	## Mission
     4	
     5	Determine whether commit `b2b4fb5` (2026-04-23 15:10, "harden B1
     6	capture bridge startup validation") is incompatible with the `ipc://`
     7	transport introduced by IV.7, and if so whether this incompatibility
     8	caused the 2026-04-23 ~16:30 IV.7 runtime failure to be misattributed
     9	to the ipc:// switch itself.
    10	
    11	## Verdict: **H3 CONFIRMED**
    12	
    13	`b2b4fb5`'s synchronous startup probe `_validate_bridge_startup()`
    14	fails against a fresh ipc://-bound engine because the engine's REP
    15	socket is not yet ready when the probe fires. The probe returns
    16	`{"ok": false, "error": "Engine не отвечает (Resource temporarily
    17	unavailable)"}` (a `zmq.Again` surfaced from the bridge subprocess),
    18	and the capture tool aborts at cmd #0.
    19	
    20	Once the engine has had time to bind the ipc socket and open its REP
    21	handler, the same transport works normally — 20 consecutive samples
    22	succeeded against ipc:// with the hardening reverted.
    23	
    24	**IV.7 failure on 2026-04-23 was not caused by the ipc:// transport
    25	itself. It was caused by the hardening probe's startup race with
    26	ipc:// bind timing.**
    27	
    28	## Skill loaded
    29	
    30	Skill `multi-model-consultation` was loaded manually with a `Read`
    31	tool call at session start, because the harness skill-registry
    32	snapshot did not include it (skill was created and committed
    33	mid-session 2026-04-23 via `9a1a100`, after the registry scan).
    34	Open item for ORCHESTRATION.md edit: document that skill registry
    35	refresh requires harness restart.
    36	
    37	## 00:05 — Phase 1 self-analysis (revised mid-analysis)
    38	
    39	### Initial reading (code inspection only)
    40	
    41	Thesis: `b2b4fb5` only touches `tools/diag_zmq_b1_capture.py` and its
    42	test. Post-b2b4fb5 commits (`157c4bc`, `63a3fed`) touched different
    43	files. The hardening code itself uses `bridge.is_alive()` (a
    44	`multiprocessing.Process.is_alive()` call) and `bridge.send_command()`
    45	(a queue-dispatched wrapper), both transport-agnostic.
    46	
    47	Concluded: H3 falsified by source-code inspection. No tcp-specific
    48	identifiers in hardening patch.
    49	
    50	### Revised reading (after discovering evidence log)
    51	
    52	`/tmp/diag_iv7_capture.log` exists on disk from the 2026-04-23 IV.7
    53	test attempt. Its single line reads:
    54	
    55	    B1 capture aborted: Bridge startup probe failed:
    56	    {'ok': False, 'error': 'Engine не отвечает (Resource temporarily unavailable)'}
    57	
    58	This is the **exact literal output** of `_validate_bridge_startup`
    59	from `b2b4fb5`. The tool used for the IV.7 test was `diag_zmq_b1_capture.py`
    60	(contrary to `docs/NEXT_SESSION.md` step 4 which referenced
    61	`diag_zmq_bridge_extended.py`), and the hardening aborted the run
    62	at cmd #0.
    63	
    64	Revised thesis: even though the hardening code is transport-agnostic
    65	at the abstraction layer, it introduces a synchronous check at an
    66	earlier-than-before point in the startup lifecycle. Under tcp://
    67	loopback, connect()+send()+recv() with a short retry is effectively
    68	instantaneous, so the check tends to pass. Under ipc://, socket-file
    69	existence and REP bind-completion are not instantaneous — the
    70	engine side may still be binding when the bridge subprocess fires
    71	its first REQ. The bridge returns `zmq.Again` to the hardening, which
    72	treats it as a hard failure.
    73	
    74	Decision: this warrants empirical confirmation. Proceed to Phase 3.
    75	Phase 2 (Codex consultation) skipped per skill §0 — evidence is
    76	concrete, not ambiguous.
    77	
    78	Consulted: none.
    79	Open: refined thesis not yet empirically verified.
    80	
    81	## 00:18 — Phase 3 empirical verification
    82	
    83	### 00:15 — Extended diag against ipc:// engine (bridge_extended.py)
    84	
    85	Worktree `.worktrees/experiment-iv7-ipc-transport` (branch
    86	`experiment/iv7-ipc-transport` at `63a3fed`).
    87	- Ran `git revert --no-commit b2b4fb5` — clean revert, 2 files
    88	  modified (tool + its test).
    89	- Restarted engine from worktree source (`PYTHONPATH=$(pwd)/src` +
    90	  `CRYODAQ_ROOT=$(pwd)`) in `--mock` mode.
    91	- Engine bound to `ipc:///tmp/cryodaq-pub.sock` and
    92	  `ipc:///tmp/cryodaq-cmd.sock` (Unix default from
    93	  `zmq_transport.py`).
    94	- Ran `tools/diag_zmq_bridge_extended.py` — 180s soak.
    95	
    96	Result:
    97	- Commands #1–#44: OK, 1-2ms each.
    98	- Command #45 at uptime 79.1s: FAIL with 35 s timeout
    99	  (`TimeoutError`).
   100	- Commands #46–#48 (to end of 180s window): all FAIL with same 35s
   101	  timeout.
   102	
   103	Interpretation: **ipc:// transport itself works for ~80s**, then the
   104	underlying B1 idle-death bug fires. This matches the pre-existing
   105	B1 signature ("cmd #48 FAIL at uptime 82s", `HANDOFF_2026-04-20_GLM.md`
   106	line 238). IV.7 did NOT fix B1 — it just changed the transport.
   107	
   108	### 00:19 — b1_capture against degraded engine
   109	
   110	After extended diag's failure at cmd #45 left the engine in the
   111	B1 degraded state, ran `tools/diag_zmq_b1_capture.py` (short,
   112	30s) against the same engine process.
   113	
   114	Result: `bridge_reply: {"ok": false, "error": "Engine не отвечает
   115	(Resource temporarily unavailable)"}`, `direct_reply: TimeoutError`.
   116	Only 1 sample captured, all fields showing stalled cmd plane.
   117	
   118	Interpretation: confirms engine is in the B1 degraded state, not a
   119	startup issue. Can't directly test hardening hypothesis from this
   120	state. Need fresh engine.
   121	
   122	### 00:20 — b1_capture against FRESH engine with b2b4fb5 reverted
   123	
   124	Killed engine, removed sockets + lock, relaunched from worktree
   125	source. Waited 4s for engine to bind. Ran
   126	`tools/diag_zmq_b1_capture.py --duration 20 --interval 1`.
   127	
   128	Result:
   129	- 20/20 samples successful.
   130	- `bridge_reply: {"ok": true, "state": "ready", ...}`.
   131	- `direct_reply: {"ok": true, ...}`.
   132	
   133	Interpretation: **with the hardening reverted, b1_capture runs
   134	normally against ipc://**. The exact same tool with the exact same
   135	transport at the exact same codebase tip, minus only the b2b4fb5
   136	changes, succeeds.
   137	
   138	### 00:22 — Phase 3 cleanup
   139	
   140	- `kill` engine process, `rm` ipc sockets.
   141	- `git reset --hard` in worktree → back to `63a3fed`.
   142	- Branch tip intact: `63a3fed`, `157c4bc`, `b2b4fb5`, ... preserved.
   143	- 3 untracked files (prior session plans + handoff response) in
   144	  worktree not touched.
   145	
   146	## Evidence summary
   147	
   148	| scenario | hardening | transport | engine age at cmd#1 | result |
   149	|---|---|---|---|---|
   150	| IV.7 2026-04-23 failure | present | ipc:// | ~fresh (< 1s) | **abort at cmd#0** — "Engine не отвечает" |
   151	| retest 2026-04-24 (bridge_extended) | reverted | ipc:// | 4s | 44/44 early OK, B1 idle-death at cmd #45 |
   152	| retest 2026-04-24 (b1_capture against degraded engine) | reverted | ipc:// | ~4 min | fail (engine already broken by B1) |
   153	| retest 2026-04-24 (b1_capture against fresh engine) | reverted | ipc:// | 4s | **20/20 OK** |
   154	
   155	The controlling variable is the presence of the b2b4fb5 hardening
   156	probe combined with engine age at cmd #1. Reverting the hardening
   157	makes b1_capture pass on ipc://.
   158	
   159	## Phase 4 — decision
   160	
   161	### What this proves
   162	
   163	1. IV.7's `ipc://` transport is viable. It runs normally for the
   164	   first ~80 seconds of engine uptime against ipc sockets.
   165	2. `b2b4fb5`'s startup probe is incompatible with ipc:// at engine
   166	   boot time. The race window is in the first few hundred ms where
   167	   engine REP hasn't bound yet.
   168	3. The 2026-04-23 16:30 "IV.7 failed" narrative was a
   169	   misattribution: b2b4fb5 aborted the diag capture before IV.7's
   170	   transport ever had a chance to demonstrate anything.
   171	
   172	### What this does NOT prove
   173	
   174	4. **B1 idle-death is unrelated to b2b4fb5.** B1 fires at ~80s
   175	   uptime regardless of hardening presence. IV.7 did not fix B1.
   176	   Next hypotheses (H4 pyzmq/asyncio, H5 engine REP state) remain
   177	   viable and need separate tests.
   178	
   179	### Recommended next action
   180	
   181	Architect decision required on hardening repair strategy:
   182	
   183	**Option R1 — fix b2b4fb5 to be startup-race-tolerant.**
   184	Rework `_validate_bridge_startup()` to retry the probe with bounded
   185	backoff (e.g., 5 × 200ms) instead of single-shot. This makes it work
   186	for both tcp and ipc without losing the guard against subprocess
   187	spawn failures.
   188	
   189	**Option R2 — move readiness into `bridge.start()`.**
   190	Have `ZmqBridge.start()` block until the subprocess reports its REQ
   191	socket has successfully received at least one reply, then return.
   192	The diag tool's hardening check then just verifies `is_alive()`,
   193	which is already correct.
   194	
   195	**Option R3 — revert b2b4fb5 and accept no startup guard.**
   196	Cheapest, but loses the catch for real subprocess-start failures.
   197	
   198	Architect pick R1 / R2 / R3. Subsequent CC session can implement.
   199	
   200	Merge path for IV.7:
   201	- If R1 or R2: fix first, then merge `experiment/iv7-ipc-transport`
   202	  and `codex/safe-merge-b1-truth-recovery` → `master`, tag `v0.34.0`,
   203	  **but note**: IV.7 does NOT close B1. B1 investigation continues
   204	  with H4/H5 as separate tasks.
   205	- If R3: straight revert of `b2b4fb5`, merge iv7 → master, tag
   206	  `v0.34.0`.
   207	
   208	### Residual risks
   209	
   210	- The startup race may be platform-dependent. macOS Unix-socket
   211	  bind might be slower than Linux. Confirmation on lab Ubuntu PC
   212	  needed before tagging v0.34.0.
   213	- IV.7's `_prepare_ipc_path` cleans up stale sockets but still
   214	  has a narrow window between `_cleanup_ipc_path_if_safe` and
   215	  the bind. Unlikely to matter in practice but worth a line of
   216	  defensive logging.
   217	- The mock engine may not exercise the same bind timing as real
   218	  hardware. Real-hardware verification should be part of the
   219	  v0.34.0 gate.
   220	
   221	## Related files
   222	
   223	- `tools/diag_zmq_b1_capture.py` — hardening lives here, lines
   224	  69-76 on `b2b4fb5`
   225	- `src/cryodaq/core/zmq_transport.py` — ipc:// defaults (iv7
   226	  only)
   227	- `src/cryodaq/launcher.py` — transport probe (63a3fed made
   228	  ipc-aware; unrelated to the b2b4fb5 hardening issue)
   229	- `/tmp/diag_iv7_capture.log` — original evidence of 2026-04-23
   230	  failure signature
   231	- `/tmp/b1_retest_fresh.jsonl` — 20/20 success with revert
   232	- `/tmp/diag_iv7_retest.log` — 180s soak showing B1 idle-death
   233	  signature on ipc://
   234	
   235	## Open for next architect session
   236	
   237	- Pick repair strategy: R1 / R2 / R3.
   238	- After repair lands: retest on Ubuntu lab PC before tagging.
   239	- B1 root cause still unknown. H4 (pyzmq/asyncio) and H5 (engine
   240	  REP state machine) next.
   241	- ORCHESTRATION.md edit: document skill-registry refresh requires
   242	  harness restart.
   243	- Skill consumption note: used Phase 1 self-analysis instead of
   244	  Codex per skill §0; evidence was concrete, consultation would
   245	  have been premature. Skill successfully guided restraint.
     1	# 2026-04-24 — D4a + D1 execution
     2	
     3	## Summary
     4	
     5	D4a (5 diag-tool cherry-picks) landed on master. D1 (R1 repair)
     6	implemented on `feat/b2b4fb5-repair` branch, pushed to origin for
     7	architect review. D4b (docs) and the D2 H4 experiment deferred to
     8	the next session per architect directive (sequential, not parallel).
     9	
    10	## D4a commits (cherry-picked onto master, `-x` for provenance)
    11	
    12	| new SHA | original SHA | subject |
    13	|---|---|---|
    14	| `8b9ce4a` | `3b661e2` | tools: add reusable B1 diagnostic helpers |
    15	| `cc090be` | `056a199` | tools: add canonical B1 capture CLI |
    16	| `40553ea` | `8e79ea6` | tools: align B1 diagnostic helpers with bridge/direct capture |
    17	| `033f87b` | `983480d` | tools: align B1 capture CLI with jsonl master capture |
    18	| `62314be` | `2ed975f` | tools: record direct probe timeouts in B1 capture |
    19	
    20	Each carries an `(cherry picked from commit <orig-sha>)` trailer
    21	from `-x`, so provenance is recorded without rewriting bodies (per
    22	architect Q5).
    23	
    24	Post-D4a state:
    25	- `tools/_b1_diagnostics.py` present on master (reusable helpers:
    26	  `bridge_snapshot`, `direct_engine_probe`).
    27	- `tools/diag_zmq_b1_capture.py` present on master in its
    28	  **pre-b2b4fb5 form** — the state that R1 must land on top of.
    29	- `tests/tools/test_b1_diagnostics.py` + `tests/tools/test_diag_zmq_b1_capture.py`
    30	  present. Full `tests/tools/` suite: 37/37 passing in 0.93 s.
    31	
    32	## D1 branch
    33	
    34	- **Branch:** `feat/b2b4fb5-repair` (new, tracks `origin/feat/b2b4fb5-repair`)
    35	- **Base:** master `62314be` (tip of D4a)
    36	- **HEAD:** `c3f4f86` — fix(diag): bounded-backoff retry in B1 capture probe (R1 repair for b2b4fb5)
    37	- **Tests:** 8/8 passing in the modified file; 37/37 in `tests/tools/` overall.
    38	- **Scope:** `tools/diag_zmq_b1_capture.py` + `tests/tools/test_diag_zmq_b1_capture.py` only. No other files touched (Codex-01 Stream A synthesis scope fence respected).
    39	- **Status:** awaiting architect review.
    40	
    41	### R1 implementation outline (c3f4f86)
    42	
    43	New helper `_validate_bridge_startup(bridge, attempts=5, backoff_s=0.2, sleep_fn=time.sleep)`:
    44	1. `bridge.is_alive()` single-shot — subprocess-spawn-failure catch.
    45	2. Loop up to `attempts` times: `bridge.send_command({"cmd": "safety_status"})`. First OK reply passes.
    46	3. Inter-attempt `sleep_fn(backoff_s)` with DEBUG log.
    47	4. All attempts non-OK → `raise RuntimeError(f"Bridge startup probe failed: {last_reply!r}")` — same error surface as b2b4fb5.
    48	
    49	Call site added in `main()` between `bridge.start()` + `time.sleep(1.0)` and `run_capture(...)`. Failure → stderr `"B1 capture aborted: ..."` + `return 1`, matching b2b4fb5's behavior so downstream tooling that greps this marker is unaffected.
    50	
    51	### Test coverage landed
    52	
    53	| # | Codex-01 test case | status | notes |
    54	|---|---|---|---|
    55	| 1 | dead bridge (is_alive=False) → raises without send_command | ✅ | `test_validate_bridge_startup_dead_bridge_raises_without_send_command` |
    56	| 2 | alive + 2× non-OK + OK → succeeds after 3 attempts with fake sleep | ✅ | `test_validate_bridge_startup_succeeds_after_transient_non_ok` |
    57	| 3 | alive + all non-OK → raises with last reply; sleeps bounded | ✅ | `test_validate_bridge_startup_all_non_ok_raises_with_last_reply` + `test_main_returns_nonzero_when_bridge_startup_fails` |
    58	| 4 | ipc:// 50-run loop, zero cmd #0 aborts | ⚠️ deferred | needs live engine + mock config; manual hardware verification |
    59	| 5 | tcp:// fallback loop same | ⚠️ deferred | same as 4 |
    60	| 6 | Delayed REP harness: bind REP after 300-800ms | ⚠️ deferred | Same signal as case 2 at unit level; real-engine version deferred |
    61	
    62	Deferred cases are noted in a file-header comment in `tests/tools/test_diag_zmq_b1_capture.py` so a future hardware-validation session can pick them up directly.
    63	
    64	## DROP bucket — ledger-only per architect Q3
    65	
    66	Per architect decision: session ledger entry only, no forwarding doc, no cherry-pick. Rationale via
    67	`artifacts/consultations/2026-04-24-overnight/RESPONSES/gemini-04-safe-merge-eval.response.md`.
    68	
    69	Commits recorded as **intentionally not merged** to master (preserved on `codex/safe-merge-b1-truth-recovery` branch indefinitely):
    70	
    71	- `ab72c84` — docs: add roadmap review prompts and resolution ledger
    72	  - **DROP reason:** roadmap review artifacts from the pre-ORCHESTRATION agent-swarm cycle; superseded by architect-authored `docs/ORCHESTRATION.md` + multi-model-consultation skill.
    73	- `8feda6b` — review: add roadmap review artifacts (codex / gemini / kimi / metaswarm)
    74	  - **DROP reason:** swarm-era multi-model review pack; conclusions either superseded or re-established under the new consultation protocol.
    75	- `bbc65c8` — diagnostics: add B1 evidence documentation (runbook NOT RUN — env unavailable)
    76	  - **DROP reason:** stale run-note documenting a runbook that was never actually executed. The real diag tools + runbook landed via D4a + associated docs (to be merged in D4b).
    77	- `0a4ae04` — review: update Kimi/Metaswarm arbitration with evidence-gap findings
    78	  - **DROP reason:** same as 8feda6b — arbitration of superseded artifacts.
    79	
    80	Architect Q3 explicitly declined a forwarding doc at `docs/audits/2026-04-22-agent-swarm/`. The branch preservation on `codex/safe-merge-b1-truth-recovery` is the authoritative historical record.
    81	
    82	## Deferred to next session(s)
    83	
    84	1. **D4b** — 7 DOCS-ONLY cherry-picks + `9ccb3d5` trimmed to ROADMAP-only (8 commits total).
    85	2. **D2** — H4 split-context falsification experiment on `experiment/iv7-ipc-transport` worktree.
    86	3. **Post-D1-merge Codex equivalence check** (architect Q4) — verify functionally equivalent to post-`b2b4fb5` state plus the R1 delta.
    87	4. **Architect review + merge** of `feat/b2b4fb5-repair`.
    88	5. **Retroactive semantic versioning** (previously-queued v0.34.0..v0.38.0 tag pass) — still postponed.
    89	
    90	## §13.3 adaptations during execution (none material)
    91	
    92	- D4a cherry-picks all clean (0 conflicts — matches recon simulation from `artifacts/versioning/2026-04-24-safe-merge-recon.md`).
    93	- D1 implementation followed Codex-01 spec verbatim; no deviations.
    94	- Test cases 4-6 deferred to manual hardware verification per architect explicit instruction ("Don't block on hardware-dependent tests").
    95	- New dependency: added `import logging` to `tools/diag_zmq_b1_capture.py` (stdlib, no `pyproject.toml` change). Called out in commit body.
    96	
    97	## 22:16 — Q4 equivalence check PASS (session addendum)
    98	
    99	Post-merge Codex adversarial equivalence review dispatched per
   100	architect Q4 directive after the M2 merge-commit `89b4db1` landed.
   101	
   102	- Consulted: Codex gpt-5.5 / high reasoning, ~88 KB response
   103	  (1924 lines), completed in ~1 min wall-clock.
   104	- Brief: `artifacts/consultations/2026-04-24-overnight/BRIEFS/codex-06-q4-equivalence.prompt.md`
   105	- Raw response: `artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-06-q4-equivalence.response.md`
   106	- Synthesis: `artifacts/consultations/2026-04-24-overnight/STREAM_SYNTHESES/Q4-equivalence-synthesis.md`
   107	- Verdict: **EQUIVALENT + improvement only.** Zero findings at any
   108	  severity level. Only `ACCEPTABLE` category used, describing the
   109	  intended retry improvement.
   110	- Key evidence: Codex ran inline Python predicate simulation across
   111	  7 edge-case inputs (`None`, `{}`, `{"ok": None}`, `{"ok": "True"}`,
   112	  `{"ok": 1}`, `{"ok": True}`, `{"ok": False}`) — R1 and b2b4fb5
   113	  predicates behave identically for all. Cross-referenced
   114	  `ZmqBridge.send_command` + `zmq_subprocess.cmd_forward_loop`
   115	  confirmed no retry-induced REQ socket state leak (IV.6 ephemeral
   116	  REQ invariant preserved).
   117	
   118	Decision: D1 loop formally closed. Branch cleanup authorized.
   119	
   120	Action taken this session:
   121	1. `git branch -D feat/b2b4fb5-repair` (local)
   122	2. `git push origin --delete feat/b2b4fb5-repair` (remote)
   123	3. Verified `c3f4f86` remains reachable via merge-commit `89b4db1`
   124	   second-parent link — history intact.
   125	
   126	Consulted: Codex gpt-5.5 high.
   127	Open: none for D1. D2 / D4b / retro-tag queue still open for future
   128	sessions.
   129	
   130	## Next architect action
   131	
   132	Review `feat/b2b4fb5-repair` (`c3f4f86`):
   133	- `tools/diag_zmq_b1_capture.py` — R1 implementation vs Codex-01 Stream A synthesis
   134	- `tests/tools/test_diag_zmq_b1_capture.py` — test cases 1-3 coverage; deferred 4-6 noted
   135	- Commit body — `Ref:` / `Batch:` / `Risk:` per ORCHESTRATION.md §5.5
   136	
   137	Options per `artifacts/handoffs/2026-04-24-d1-review-handoff.md`:
   138	- **APPROVE** → merge to master, proceed to D4b / D2 in follow-up session.
   139	- **REQUEST CHANGES** → CC iterates on branch.
   140	- **REJECT** → would indicate R1 spec itself was wrong; rare.
     1	# 2026-04-23 — cleanup baseline session
     2	
     3	## Context
     4	
     5	Architect (Vladimir + web Claude Opus 4.7) authored ORCHESTRATION.md
     6	2026-04-23 evening. This session executes the cleanup plan that
     7	establishes baseline under the new contract. First session run under
     8	the CC-as-sole-coordinator model.
     9	
    10	No consultants invoked. Mechanical cleanup only.
    11	
    12	## Session-start checklist (§10)
    13	
    14	| # | Item | Result |
    15	|---|---|---|
    16	| 1 | Read `docs/ORCHESTRATION.md` end-to-end | done (466 lines) |
    17	| 2 | Read `CLAUDE.md` | loaded — includes metaswarm section; architect directed checkout of that section (see 22:58 entry below) |
    18	| 3 | `git status` — uncommitted state | 3 modified tracked files + 34 untracked at session start |
    19	| 4 | `git branch --show-current` | `codex/preserved-local-master-2026-04-21` (NOT master) |
    20	| 5 | `git worktree list` | 3 real + 1 prunable `/private/tmp`; `.worktrees/codex-safe-merge-b1-truth-recovery` naming mismatch on branch `experiment/iv7-ipc-transport` (§5.4 violation) |
    21	| 6 | `artifacts/consultations/` pending | dir does not exist — nothing pending |
    22	| 7 | Latest `docs/decisions/` ledger | only `ROADMAP_RESOLUTION_LEDGER.md` present — this is the first dated session ledger |
    23	| 8 | Stale feature branch (>2d)? | `codex/safe-merge-b1-truth-recovery` and `experiment/iv7-ipc-transport` — architect-preserved per §11; not touched this session |
    24	
    25	## Architect resolutions applied (pre-execution)
    26	
    27	After session-start recon, CC paused with a 5-blocker STOP report.
    28	Architect responded with Resolutions A–E plus an autonomy-expansion
    29	amendment. Summary:
    30	
    31	- **Resolution A** — current branch `codex/preserved-local-master-2026-04-21`: its 6 branch-only commits (swarm review-pack test specs) discarded. All 3 modified tracked files checked out. Switched to master.
    32	- **Resolution B** — `CLAUDE.md` metaswarm section checked out (contradicts ORCHESTRATION.md §§ 2, 3). Handled in Resolution A's checkout.
    33	- **Resolution C** — `.gitignore` uncommitted diff discarded. Handled in Resolution A's checkout. `.worktrees/` addition also discarded, which later required a plan adjustment (see 22:58 `.gitignore` entry).
    34	- **Resolution D** — `config/channels.yaml` 18-line comment deletion reverted. Handled in Resolution A's checkout.
    35	- **Resolution E** — worktree naming mismatch addressed via new Step 5.5 (worktree rename).
    36	
    37	Mid-execution the architect added two further directives:
    38	- **STOP discipline update** — plan factual inaccuracies of 1-line magnitude (off-by-one counts, wrong commit messages) should be corrected inline and noted in ledger, not escalated.
    39	- **Autonomy expansion** — untracked files inside to-be-removed worktrees are to be preserved via archive-and-commit, not escalated. Applies retroactively.
    40	
    41	## 22:55 — §10 session-start STOP report to architect
    42	
    43	Thesis: Working tree had 3 modified tracked files + branch was not master; plan step 2 ("expect clean after step 1") assumed only CLAUDE.md modified.
    44	Reasoning: Diff inspection showed CLAUDE.md had an unauthorized metaswarm section contradicting ORCHESTRATION.md, `.gitignore` had uncommitted additions that partially overlapped Step 5, `config/channels.yaml` deleted 18 lines of runtime-config documentation, and the current branch was one of the targets scheduled for Step 6 deletion.
    45	Decision: reported 5 blockers (A-E) to architect, held all action.
    46	Consulted: none.
    47	Open: none — architect returned resolutions.
    48	
    49	## 22:58 — Pre-Step 3 adjustment: CLAUDE.md + .gitignore + channels.yaml reverts
    50	
    51	Thesis: Resolution A's `git checkout --` on three files brings working tree to master-consistent state before switching.
    52	Reasoning: Plan factual recon was built on a dirty working tree; the three tracked modifications were all directed for revert.
    53	Decision: `git checkout -- CLAUDE.md .gitignore config/channels.yaml` then `git checkout master`. Tree clean.
    54	Consulted: none.
    55	Open: none.
    56	
    57	## 22:59 — Second STOP: .worktrees/ invariant gap in plan Step 5
    58	
    59	Thesis: Plan Step 5 claims `.worktrees/` already gitignored on master; verification showed the entry was only in the now-discarded uncommitted diff.
    60	Reasoning: Plan's grep verification would fail; ORCHESTRATION.md §5.4 invariant not met on master.
    61	Decision: paused and reported to architect.
    62	Consulted: none.
    63	Open: ORCHESTRATION.md §5.4 wording still says "already gitignored" — architect agreed to clean up phrasing later (tracked in "Open for next architect session" below).
    64	
    65	## 23:00 — §5.4 invariant repair during Step 5
    66	
    67	Thesis: docs/ORCHESTRATION.md §5.4 claimed `.worktrees/` was already gitignored on master; verification showed this was false.
    68	Reasoning: Original claim was based on recon report that observed uncommitted `.gitignore` diff; on master the pattern was absent.
    69	Decision: Added `.worktrees/` to Step 5 heredoc as 7th pattern (first in list, as the largest and highest-risk). Architect will update §5.4 phrasing in a later session to describe this as a repo invariant enforced by this commit, not pre-existing state.
    70	Consulted: none.
    71	Open: ORCHESTRATION.md §5.4 wording cleanup.
    72	
    73	## 23:03 — Commit 1/4: docs preservation
    74	
    75	Decision: committed `SESSION_DETAIL_2026-04-20.md` + `docs/ORCHESTRATION.md` to master.
    76	SHA: **adb49fe**
    77	Consulted: none.
    78	Open: none.
    79	
    80	## 23:05 — Third STOP: Step 4 plan inaccuracy ("all 12 untracked")
    81	
    82	Thesis: Plan's commit message claimed all 12 archive-target files were untracked; reality was 11 untracked + 1 tracked (`CODEX_ARCHITECTURE_CONTROL_PLANE.md` added in master HEAD `256da7a`).
    83	Reasoning: Committing with a false statement would pollute the ledger; mv of tracked file shows as D+A in status which git would detect as rename.
    84	Decision: paused, reported to architect. Architect returned three sub-resolutions: (1) `CODEX_ARCHITECTURE_CONTROL_PLANE.md` stays at root as architect-blessed dossier, (2) other 11 archive as planned, (3) update §6.2 whitelist.
    85	Consulted: none.
    86	Open: none.
    87	
    88	## 23:08 — Commit 2/4: archive 11 agent-swarm files + whitelist update
    89	
    90	Decision: moved 11 untracked `.md` files to `docs/audits/2026-04-21-agent-swarm/` and 3 untracked `.py` files to `.scratch/zmq-exploration-2026-04-21/`. Reverted the `CODEX_ARCHITECTURE_CONTROL_PLANE.md` move — it stays at root. Added that filename to ORCHESTRATION.md §6.2 whitelist (inserted alphabetically after `CHANGELOG.md`).
    91	SHA: **1ea049d**
    92	Plan said "12", reality was 11+1. Adjusted commit message from "All 12 were previously untracked" to "All 11 were previously untracked" and added a paragraph explaining the `CODEX_ARCHITECTURE_CONTROL_PLANE.md` exception. Noted per new STOP-discipline rule.
    93	Consulted: none.
    94	Open: none.
    95	
    96	## 23:12 — Commit 3/4: gitignore agent workspaces
    97	
    98	Decision: 7 patterns appended to `.gitignore` (`.worktrees/` first, then `.audit-run/`, `.omc/`, `.swarm/`, `.venv-tools/`, `agentswarm/`, `.scratch/`). Verification `grep -n ".worktrees" .gitignore` returned line 59.
    99	SHA: **587bea8**
   100	Consulted: none.
   101	Open: ORCHESTRATION.md §5.4 wording cleanup (noted above).
   102	
   103	## 23:14 — Step 5.5: worktree rename (architect Resolution E)
   104	
   105	Decision: `git worktree move .worktrees/codex-safe-merge-b1-truth-recovery .worktrees/experiment-iv7-ipc-transport`. Name now matches branch. §5.4 naming-mismatch invariant restored.
   106	Consulted: none. No commit (worktree ops not tracked).
   107	Open: none.
   108	
   109	## 23:16 — Fourth STOP → inline adaptation: stray plan in worktree
   110	
   111	Thesis: `git worktree remove .worktrees/codex-b1-truth-recovery` refused because the worktree had 1 untracked file: `docs/superpowers/plans/2026-04-21-safe-merge-origin-master.md` (11.9K). `--force` would have deleted it, violating §11.
   112	Reasoning: File content is a plan for safe-merge work now superseded by commits on `codex/safe-merge-b1-truth-recovery`. Candidate for archive.
   113	Decision: paused once, reported to architect, architect directed Option 1 (preserve to archive then force-remove) AND issued autonomy-expansion making this the default for future cases. Plan document copied to `docs/audits/2026-04-21-agent-swarm/`, committed as side-commit.
   114	SHA: **cfee680**
   115	Consulted: none.
   116	Open: none — autonomy-expansion makes future preserve-and-proceed routine.
   117	
   118	## 23:18 — Commit 4 of 4 (branch prune, no git commit)
   119	
   120	Decision: `git worktree remove --force .worktrees/codex-b1-truth-recovery` (safe now that stray file preserved). `git branch -D codex/b1-truth-recovery` (was 9 commits ahead of master). `git branch -D codex/preserved-local-master-2026-04-21` (was 6 commits ahead of master). Kept `codex/safe-merge-b1-truth-recovery` (b2b4fb5, pending architect eval) and `experiment/iv7-ipc-transport` (63a3fed, pending b2b4fb5 hypothesis test).
   121	Consulted: none. No git commit (branch/worktree deletions are not tracked).
   122	
   123	## Branches at session end
   124	
   125	| branch | sha | status |
   126	|---|---|---|
   127	| master | cfee680 (pre-ledger commit) | clean, pushed |
   128	| codex/safe-merge-b1-truth-recovery | b2b4fb5 | preserved, pending architect eval |
   129	| experiment/iv7-ipc-transport | 63a3fed | preserved, pending b2b4fb5 hypothesis test |
   130	
   131	## Worktrees at session end
   132	
   133	| path | branch | notes |
   134	|---|---|---|
   135	| `~/Projects/cryodaq` | master | primary working copy |
   136	| `.worktrees/experiment-iv7-ipc-transport` | experiment/iv7-ipc-transport | renamed from `.worktrees/codex-safe-merge-b1-truth-recovery` per §5.4 |
   137	
   138	Prunable `/private/tmp/cryodaq-commit-test` reference cleared by `git worktree prune`.
   139	
   140	## Open for next architect session
   141	
   142	- **b2b4fb5 hypothesis test**: does the hardened B1 probe reject a healthy `ipc://` bridge, causing the 2026-04-23 IV.7 runtime failure to have been misattributed? (Plan `CC_PROMPT_IV_7_IPC_TRANSPORT.md` still active per §11.)
   143	- **safe-merge docs evaluation**: 11 commits on `codex/safe-merge-b1-truth-recovery`, merge or drop?
   144	- **IV.7 status**: depends on b2b4fb5 test outcome.
   145	- **ORCHESTRATION.md §5.4 wording cleanup**: current text says `.worktrees/` is "already gitignored"; after this session it is enforced by commit 587bea8. Rephrase as "enforced invariant" vs "pre-existing state".
   146	- **§11 "Known active plans" table update**: add status note "Repo cleanup — DONE (2026-04-23, commits adb49fe..cfee680)".

exec
/opt/homebrew/bin/bash -lc "for f in \"30 Investigations/B1 ZMQ idle-death.md\" \"30 Investigations/b2b4fb5 hardening race.md\" \"30 Investigations/Cyrillic homoglyph in alarm config.md\" \"30 Investigations/Codex H2 wrong hypothesis.md\" \"30 Investigations/Plugin isolation rebuild.md\" \"30 Investigations/IV.6 cmd plane hardening.md\"; do printf '\\n===== %s =====\\n' \""'$f"; nl -ba "/Users/vladimir/Vault/CryoDAQ/$f"; done' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:

===== 30 Investigations/B1 ZMQ idle-death.md =====
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
    25	into the same context **also hang**. Engine REP itself answers a
    26	direct in-process Python client in 0.001 s while the bridge
    27	subprocess is deep into B1 — engine is not wedged.
    28	
    29	| Platform | First failure |
    30	|---|---|
    31	| macOS Darwin (Python 3.14.3, pyzmq 25.x) | stochastic 4–92 s uptime |
    32	| Ubuntu 22.04 (Python 3.12.13, pyzmq 26.4.0) | exactly 120 s after subprocess start (single data point, may vary) |
    33	
    34	Real Ubuntu lab PC reproduces in `./start.sh`, not just diag tools.
    35	
    36	## Hypothesis tree
    37	
    38	| H | Hypothesis | Evidence | Status |
    39	|---|---|---|---|
    40	| H1 | macOS kernel idle reaping of loopback TCP | `tcp_keepalive_time = 7200s` on Linux, yet 120 s deterministic failure | **falsified 2026-04-20** |
    41	| H2 | Single long-lived REQ socket accumulating bad state (Codex's primary) | IV.6 implemented per-cmd ephemeral REQ; B1 still reproduces | **falsified 2026-04-20** |
    42	| H3 | b2b4fb5 hardening probe incompatible with `ipc://` | repro on revert + bind-time race confirmed | **partially confirmed** — explains 2026-04-23 IV.7 misattribution but does NOT explain B1 itself; B1 still fires after ~80 s on ipc:// |
    43	| H4 | pyzmq 25.x + Python 3.14 asyncio integration / engine REP task state under rapid REQ connect-disconnect churn | not yet tested in isolation | **untested** — D2 split-context falsification experiment scheduled |
    44	| H5 | engine REP state machine | not yet specifically probed | **untested** |
    45	
    46	## What works
    47	
    48	- Engine REP socket itself — direct Python REQ client gets 0.001 s
    49	  reply mid-failure.
    50	- Engine internals: SQLite writes (~9000/10 min), heartbeats every
    51	  30 s, plugin ticks, scheduler all stay healthy.
    52	- Raw subprocess without `ZmqBridge` wrapping (`diag_zmq_subprocess.py`)
    53	  succeeds short-term on both `fork` and `spawn` mp start methods.
    54	
    55	## What's been tried
    56	
    57	1. **`TCP_KEEPALIVE` on all four sockets** (commit `f5f9039`,
    58	   reverted on cmd path in IV.6). Partial delay of failure on macOS
    59	   only; Linux unaffected. Reverted on command + PUB paths since H1
    60	   was falsified; kept on `sub_drain_loop` SUB as orthogonal
    61	   safeguard.
    62	2. **IV.6 ephemeral REQ + cmd-channel watchdog** (`be51a24`).
    63	   Codex's H2 hypothesis. Implements ZeroMQ Guide ch.4 canonical
    64	   "poll / timeout / close / reopen" pattern. **Did not fix B1.**
    65	3. **IV.6 watchdog cooldown hotfix** — solves restart-storm
    66	   regression (30–40 restarts/min on Ubuntu) but is not a B1 fix;
    67	   produces "works ~60–120 s, one restart, works again" cycle as
    68	   workaround.
    69	4. **IV.7 ipc:// transport experiment.** Branch
    70	   `experiment/iv7-ipc-transport`. Switches loopback default to
    71	   Unix-domain sockets on macOS / Linux. ipc:// runs normally for
    72	   ~80 s then B1 fires anyway — not a transport-layer fix, but
    73	   useful as a diagnostic constant.
    74	
    75	## Diagnostics in tree
    76	
    77	`tools/diag_zmq_*.py` retained for regression after fix:
    78	
    79	- `tools/diag_zmq_subprocess.py` — subprocess alone, short.
    80	- `tools/diag_zmq_bridge.py` — full ZmqBridge 60 s soak.
    81	- `tools/diag_zmq_bridge_extended.py` — 180 s past-first-failure.
    82	- `tools/diag_zmq_idle_hypothesis.py` — rate-dependence reproducer.
    83	- `tools/diag_zmq_b1_capture.py` — canonical B1 capture CLI
    84	  (post-D4a, post-R1).
    85	- `tools/_b1_diagnostics.py` — reusable helpers (bridge_snapshot,
    86	  direct_engine_probe).
    87	
    88	`/tmp/diag_iv6_*.log` and `/tmp/engine_iv6_debug.log` preserved for
    89	architect review.
    90	
    91	## Why this still matters
    92	
    93	`v0.34.0` cannot ship while B1 reproduces — the user-visible
    94	symptom is "GUI buttons don't work after a couple of minutes; have
    95	to restart the bridge subprocess". The IV.6 watchdog cooldown
    96	provides a usable workaround (60–120 s cycle with single restart),
    97	not an acceptable production state.
    98	
    99	## Next experiments
   100	
   101	- **D2 — H4 split-context falsification** on
   102	  `experiment/iv7-ipc-transport` worktree.
   103	- If H4 / H5 both falsified: target may be lower (libzmq 4.x
   104	  loopback handling, kernel-level interaction). Would justify a
   105	  switch to a different IPC mechanism entirely (mp.Pipe, UNIX
   106	  socket without zmq, etc.).
   107	
   108	## See also
   109	
   110	- [[30 Investigations/IV.6 cmd plane hardening]]
   111	- [[30 Investigations/b2b4fb5 hardening race]]
   112	- [[30 Investigations/Codex H2 wrong hypothesis]]
   113	- [[40 Decisions/2026-04-24-b2b4fb5-investigation]]
   114	- [[40 Decisions/2026-04-24-d1-d4a-execution]]
   115	- [[10 Subsystems/ZMQ bridge]]

===== 30 Investigations/b2b4fb5 hardening race.md =====
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
    15	- **2026-04-23 14:25** — Commit `b2b4fb5` ("harden B1 capture bridge
    16	  startup validation") landed. Adds synchronous probe
    17	  `_validate_bridge_startup()` to `tools/diag_zmq_b1_capture.py` that
    18	  fails fast on `bridge.is_alive() == False` or first non-OK
    19	  `safety_status` reply.
    20	- **2026-04-23 15:10** — Commit `157c4bc` (IV.7 `ipc://` transport
    21	  experiment) landed 45 minutes later, on a different branch.
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

===== 30 Investigations/Cyrillic homoglyph in alarm config.md =====
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
    33	- `config/interlocks.yaml::overheat_cryostat::channel_pattern` —
    34	  was previously `Т[1-8] .*` with mixed case, also touched in `9feaf3e`
    35	  fix; later tightened to `Т(1|2|3|5|6|7|8) .*` to exclude
    36	  physically-disconnected Т4 on the Ubuntu lab PC.
    37	- `docs/design-system/` rules involving "мбар" vs "mbar" (similar
    38	  class — Latin `mbar` got flagged in `1c61268` CRITICAL domain
    39	  cleanup).
    40	
    41	## Why it survives ordinary review
    42	
    43	- **Visual identity** — Cyrillic Т and Latin T are visually
    44	  indistinguishable in most monospace fonts. PR diff review by a
    45	  human reading the screen catches nothing.
    46	- **Test design** — alarm tests ran the engine on synthetic
    47	  channels named in the test. They didn't cross-reference back to
    48	  the production `instruments.yaml` namespace.
    49	- **Encoding** — both characters are valid UTF-8, both serialize
    50	  fine in YAML. The file never failed to load.
    51	
    52	## Defenses now in place
    53	
    54	- **Regression test** that asserts every channel pattern in
    55	  `config/alarms_v3.yaml` matches at least one channel in
    56	  `config/channels.yaml` after canonical resolution.
    57	- **Design system rules** (`docs/design-system/rules/*-rules.md`)
    58	  carry explicit Cyrillic-Т-vs-Latin-T invariant for any operator-
    59	  facing rendered text.
    60	- **Adversarial second-model review** (`docs/CODEX_SELF_REVIEW_PLAYBOOK.md`)
    61	  — Codex gpt-5.5/high catches homoglyph-class issues alongside
    62	  semantic regressions.
    63	
    64	## Encoding policy (CLAUDE.md "Кодировка файлов")
    65	
    66	- Python source / Markdown / YAML in repo: UTF-8 **without BOM**.
    67	- BOM is applied **only** to operator-facing CSV exports
    68	  (`storage/csv_export.py`) — Excel on Russian Windows needs the
    69	  BOM prefix to read Cyrillic correctly.
    70	- Do not add BOM to any source file. External reviewers occasionally
    71	  flag a BOM invariant for source — that's misapplication.
    72	
    73	## Lesson
    74	
    75	Tests prove logic correctness, not identifier correctness. When a
    76	rule and the channel namespace it operates over both come from
    77	different files, the regression test must close that loop
    78	explicitly. Visual review can never catch homoglyphs reliably.
    79	
    80	## See also
    81	
    82	- [[10 Subsystems/Alarm engine v2]]
    83	- [[20 Drivers/LakeShore 218S]] — Cyrillic Т prefix origin
    84	- [[30 Investigations/Codex H2 wrong hypothesis]] — different lesson
    85	  from the same year about model confidence vs tests

===== 30 Investigations/Codex H2 wrong hypothesis.md =====
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

===== 30 Investigations/Plugin isolation rebuild.md =====
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
    71	synthetic `Reading`s, so downstream consumers (GUI, web, SQLite)
    72	treat them uniformly.
    73	
    74	## Where it lives now
    75	
    76	- ABC: `analytics/base_plugin.py`.
    77	- Pipeline: `analytics/plugin_loader.py`.
    78	- Production plugin examples: `analytics/sensor_diagnostics.py`,
    79	  `analytics/vacuum_trend.py`. (Cooldown predictor lives outside
    80	  the plugin pipeline because it needs orchestration with
    81	  `core/cooldown_service.py`.)
    82	- Configuration: `config/plugins.yaml` controls which plugins are
    83	  enabled; `<plugin_id>.yaml` siblings carry plugin-specific config.
    84	
    85	## Lesson
    86	
    87	Engine survival is non-negotiable. Any extension point that lets a
    88	third party (operator-authored plugin) run code in the hot path
    89	must isolate exceptions explicitly — Python's default exception
    90	flow is to crash the loop, and that is the wrong default for
    91	acquisition systems.
    92	
    93	## See also
    94	
    95	- [[10 Subsystems/Plugin architecture]] — full subsystem page
    96	- [[40 Decisions/ADR-003 Plugin isolation via ABC]] — synthesized
    97	  ADR for this rebuild

===== 30 Investigations/IV.6 cmd plane hardening.md =====
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
    43	[[30 Investigations/Codex H2 wrong hypothesis]]. Engine REP goes
    44	silently unresponsive after ~30–90 s of bridge uptime while the
    45	asyncio loop, data-plane PUB, heartbeats, scheduler writes, and
    46	plugin ticks all remain healthy.
    47	
    48	## Watchdog regression + cooldown hotfix (2026-04-20 evening)
    49	
    50	The IV.6 watchdog initially had a bug: `_last_cmd_timeout` persisted
    51	across watchdog-triggered subprocess restart. A fresh subprocess
    52	saw a stale timeout signal on the first poll cycle, triggered
    53	another restart, etc. — restart storm (30–40 restarts/minute on
    54	Ubuntu lab PC).
    55	
    56	Hotfix in `src/cryodaq/launcher.py`:
    57	- 60 s cooldown between command-watchdog restarts via
    58	  `_last_cmd_watchdog_restart` timestamp.
    59	- Missing `return` after restart added so no further checks run in
    60	  the same poll cycle.
    61	
    62	Effect: restart storm gone, but B1 itself still fires. System
    63	reaches usable steady state of "works ~60–120 s, one restart, works
    64	again" — workaround until IV.7 ipc:// or other root-cause fix.
    65	
    66	## Why it stayed in master
    67	
    68	Even though IV.6 doesn't fix B1, the changes are kept:
    69	
    70	- **Architectural improvement.** Matches ZeroMQ Guide ch.4
    71	  canonical reliable req-reply pattern. Future maintainers expect
    72	  this shape.
    73	- **Removes a real brittle point.** Shared REQ state across
    74	  commands was a long-term maintainability hazard regardless of
    75	  whether it caused B1.
    76	- **Gives the launcher a cmd-channel watchdog.** Separate from
    77	  data-plane health detection, the launcher can now detect and
    78	  recover from any future command-only failure shape.
    79	- **Defense-in-depth.** B1 root cause may be deeper still; if a
    80	  future bug surfaces with a similar shape, IV.6 closes one of the
    81	  candidate failure modes.
    82	
    83	## Related fixes shipped alongside
    84	
    85	- `aabd75f` — `engine: wire validate_checksum through Thyracont
    86	  driver loader`. `_create_instruments()` was ignoring the YAML
    87	  key; driver defaulted to `True` regardless of config. Resolves
    88	  TopWatchBar pressure em-dash on Ubuntu lab PC (VSP206 vs VSP63D
    89	  checksum). See [[20 Drivers/Thyracont VSP63D]].
    90	- `74dbbc7` — `reporting: xml_safe sanitizer for python-docx
    91	  compatibility`. Keithley VISA resource strings contain `\x00`;
    92	  python-docx rejected them as XML 1.0 incompatible. New
    93	  `src/cryodaq/utils/xml_safe.py` strips XML-illegal control chars
    94	  at all add_paragraph / cell.text sites in
    95	  `reporting/sections.py`. See [[20 Drivers/Keithley 2604B]].
    96	
    97	## Lesson
    98	
    99	Shipping a hypothesis-driven fix is OK even when it doesn't close
   100	the bug, **provided** the change is independently defensible and
   101	documented as partial mitigation. The mistake would have been to
   102	celebrate IV.6 as a B1 fix and stop investigating; the audit
   103	record clearly says "partial — B1 still open".
   104	
   105	## See also
   106	
   107	- [[30 Investigations/B1 ZMQ idle-death]]
   108	- [[30 Investigations/Codex H2 wrong hypothesis]]
   109	- [[10 Subsystems/ZMQ bridge]]

exec
/opt/homebrew/bin/bash -lc "for f in \"40 Decisions/ADR-001 Persistence-first invariant.md\" \"40 Decisions/ADR-002 R1 bounded-backoff probe retry.md\" \"40 Decisions/ADR-003 Plugin isolation via ABC.md\"; do printf '\\n===== %s =====\\n' \""'$f"; nl -ba "/Users/vladimir/Vault/CryoDAQ/$f"; done' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:

===== 40 Decisions/ADR-001 Persistence-first invariant.md =====
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
    65	- GUI dashboards must hold local rolling buffers (`channel_buffer.py`)
    66	  to render high-frequency timeseries — but the buffer is fed from
    67	  the broker, which only sees committed readings.
    68	- "Performance mode" overrides are not allowed. Any future
    69	  optimization that would skip or defer the write step has to clear
    70	  this ADR.
    71	- The fail-closed config invariant (engine exit code 2 on missing
    72	  / malformed `safety.yaml`, `alarms_v3.yaml`, `interlocks.yaml`,
    73	  `housekeeping.yaml`, `channels.yaml`) extends the same default:
    74	  start in a state where durable behavior is guaranteed, refuse to
    75	  start otherwise.
    76	
    77	## Status
    78	
    79	Accepted. Has been the operating contract since Phase 2d. The
    80	`docs/decisions/*` ledgers do not contain a separate ADR for this
    81	invariant because it predates the ledger system; the invariant is
    82	captured in `CLAUDE.md` and `PROJECT_STATUS.md`. This synthesized
    83	ADR exists to make the rationale visible alongside the other ADRs
    84	in this vault.
    85	
    86	## See also
    87	
    88	- [[10 Subsystems/Persistence-first]] — implementation page
    89	- [[10 Subsystems/Safety FSM]] — cancellation-shielded fault path
    90	- [[10 Subsystems/Calibration v2]] — one-transaction rule

===== 40 Decisions/ADR-002 R1 bounded-backoff probe retry.md =====
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

===== 40 Decisions/ADR-003 Plugin isolation via ABC.md =====
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
    59	- Synthetic `Reading` republishing means downstream consumers
    60	  (GUI, web, SQLite) treat derived metrics uniformly. No special
    61	  channel or pipeline for analytics output.
    62	
    63	## Status
    64	
    65	Accepted. Pattern is the basis of all subsequent analytics work
    66	(`sensor_diagnostics`, `vacuum_trend`, future F16 plugin SDK).
    67	
    68	The cooldown predictor (`core/cooldown_service.py`) is deliberately
    69	**not** a plugin, because it needs orchestration with the
    70	experiment lifecycle that the plugin pipeline doesn't provide.
    71	That carve-out is fine; the ABC is for stateless, batch-driven
    72	analytics.
    73	
    74	## See also
    75	
    76	- [[10 Subsystems/Plugin architecture]] — implementation page
    77	- [[30 Investigations/Plugin isolation rebuild]] — story behind
    78	  the rebuild
    79	- [[60 Roadmap/F-table backlog]] — F16 (plugin hot-reload SDK +
    80	  examples)

exec
/opt/homebrew/bin/bash -lc 'rg -n "persistence|DataBroker|SafetyBroker|write_immediate|WAL|SQLite|bounded-backoff|_validate_bridge_startup|PluginPipeline|AnalyticsPlugin|DerivedMetric|plugin" CLAUDE.md PROJECT_STATUS.md docs/decisions/2026-04-24-b2b4fb5-investigation.md docs/decisions/2026-04-24-d1-d4a-execution.md src/cryodaq/core/scheduler.py src/cryodaq/storage/sqlite_writer.py src/cryodaq/analytics/base_plugin.py src/cryodaq/analytics/plugin_loader.py config/plugins.yaml' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
src/cryodaq/analytics/base_plugin.py:3:Определяет DerivedMetric — результат вычисления плагина — и
src/cryodaq/analytics/base_plugin.py:4:абстрактный класс AnalyticsPlugin, от которого наследуются все
src/cryodaq/analytics/base_plugin.py:20:class DerivedMetric:
src/cryodaq/analytics/base_plugin.py:27:        plugin_id:  Уникальный идентификатор плагина-источника.
src/cryodaq/analytics/base_plugin.py:35:    plugin_id: str
src/cryodaq/analytics/base_plugin.py:43:        plugin_id: str,
src/cryodaq/analytics/base_plugin.py:48:    ) -> DerivedMetric:
src/cryodaq/analytics/base_plugin.py:49:        """Создать DerivedMetric с текущей меткой времени UTC.
src/cryodaq/analytics/base_plugin.py:52:            plugin_id:  Идентификатор плагина.
src/cryodaq/analytics/base_plugin.py:59:            Экземпляр :class:`DerivedMetric` с ``timestamp = datetime.now(UTC)``.
src/cryodaq/analytics/base_plugin.py:61:        return DerivedMetric(
src/cryodaq/analytics/base_plugin.py:63:            plugin_id=plugin_id,
src/cryodaq/analytics/base_plugin.py:71:class AnalyticsPlugin(ABC):
src/cryodaq/analytics/base_plugin.py:75:    :meth:`process`.  Жизненный цикл управляется :class:`PluginPipeline`:
src/cryodaq/analytics/base_plugin.py:81:        class MyPlugin(AnalyticsPlugin):
src/cryodaq/analytics/base_plugin.py:84:                return [DerivedMetric.now(self.plugin_id, "my_metric", 42.0, "arb")]
src/cryodaq/analytics/base_plugin.py:87:    def __init__(self, plugin_id: str) -> None:
src/cryodaq/analytics/base_plugin.py:91:            plugin_id:  Уникальный идентификатор плагина в рамках пайплайна.
src/cryodaq/analytics/base_plugin.py:94:        self._plugin_id = plugin_id
src/cryodaq/analytics/base_plugin.py:98:    def plugin_id(self) -> str:
src/cryodaq/analytics/base_plugin.py:100:        return self._plugin_id
src/cryodaq/analytics/base_plugin.py:103:    async def process(self, readings: list[Reading]) -> list[DerivedMetric]:
src/cryodaq/analytics/base_plugin.py:106:        Вызывается :class:`PluginPipeline` на каждом интервале сбора данных.
src/cryodaq/analytics/base_plugin.py:115:            Список :class:`DerivedMetric`.  Допустимо вернуть пустой список,
src/cryodaq/analytics/plugin_loader.py:7:- публикацию результатов (DerivedMetric) обратно в брокер как Reading.
src/cryodaq/analytics/plugin_loader.py:22:from cryodaq.analytics.base_plugin import AnalyticsPlugin, DerivedMetric
src/cryodaq/analytics/plugin_loader.py:23:from cryodaq.core.broker import DataBroker
src/cryodaq/analytics/plugin_loader.py:30:_SUBSCRIBE_NAME = "plugin_pipeline"
src/cryodaq/analytics/plugin_loader.py:33:class PluginPipeline:
src/cryodaq/analytics/plugin_loader.py:42:        pipeline = PluginPipeline(broker, Path("plugins/"))
src/cryodaq/analytics/plugin_loader.py:50:        broker: DataBroker,
src/cryodaq/analytics/plugin_loader.py:51:        plugins_dir: Path,
src/cryodaq/analytics/plugin_loader.py:58:            broker:            Экземпляр :class:`~cryodaq.core.broker.DataBroker`.
src/cryodaq/analytics/plugin_loader.py:59:            plugins_dir:       Директория с файлами плагинов (``.py``).
src/cryodaq/analytics/plugin_loader.py:63:        self._plugins_dir = plugins_dir
src/cryodaq/analytics/plugin_loader.py:64:        self._plugins: dict[str, AnalyticsPlugin] = {}
src/cryodaq/analytics/plugin_loader.py:78:        Подписывается на брокер, загружает все плагины из ``plugins_dir``,
src/cryodaq/analytics/plugin_loader.py:88:        self._plugins_dir.mkdir(parents=True, exist_ok=True)
src/cryodaq/analytics/plugin_loader.py:89:        for path in sorted(self._plugins_dir.glob("*.py")):
src/cryodaq/analytics/plugin_loader.py:90:            self._load_plugin(path)
src/cryodaq/analytics/plugin_loader.py:99:            len(self._plugins),
src/cryodaq/analytics/plugin_loader.py:129:    def _load_plugin(self, path: Path) -> None:
src/cryodaq/analytics/plugin_loader.py:133:        :class:`~cryodaq.analytics.base_plugin.AnalyticsPlugin`,
src/cryodaq/analytics/plugin_loader.py:143:            plugin_id = path.stem
src/cryodaq/analytics/plugin_loader.py:144:            spec = importlib.util.spec_from_file_location(f"cryodaq_plugin_{plugin_id}", path)
src/cryodaq/analytics/plugin_loader.py:146:                logger.error("Не удалось создать spec для плагина '%s': %s", plugin_id, path)
src/cryodaq/analytics/plugin_loader.py:152:            plugin_cls: type[AnalyticsPlugin] | None = None
src/cryodaq/analytics/plugin_loader.py:155:                    issubclass(obj, AnalyticsPlugin)
src/cryodaq/analytics/plugin_loader.py:156:                    and obj is not AnalyticsPlugin
src/cryodaq/analytics/plugin_loader.py:160:                    plugin_cls = obj
src/cryodaq/analytics/plugin_loader.py:163:            if plugin_cls is None:
src/cryodaq/analytics/plugin_loader.py:165:                    "Файл '%s' не содержит конкретного подкласса AnalyticsPlugin — пропущен",
src/cryodaq/analytics/plugin_loader.py:170:            # Плагин может определять __init__(self) без аргументов (с plugin_id
src/cryodaq/analytics/plugin_loader.py:171:            # как атрибутом класса) или __init__(self, plugin_id).
src/cryodaq/analytics/plugin_loader.py:173:                plugin = plugin_cls(plugin_id)
src/cryodaq/analytics/plugin_loader.py:175:                plugin = plugin_cls()
src/cryodaq/analytics/plugin_loader.py:176:                # Если плагин не задал plugin_id — установить принудительно
src/cryodaq/analytics/plugin_loader.py:177:                if plugin.plugin_id != plugin_id:
src/cryodaq/analytics/plugin_loader.py:178:                    plugin._plugin_id = plugin_id
src/cryodaq/analytics/plugin_loader.py:185:                    plugin.configure(config)
src/cryodaq/analytics/plugin_loader.py:186:                    logger.debug("Конфиг '%s' применён к плагину '%s'", config_path, plugin_id)
src/cryodaq/analytics/plugin_loader.py:191:                        plugin_id,
src/cryodaq/analytics/plugin_loader.py:195:            self._plugins[plugin_id] = plugin
src/cryodaq/analytics/plugin_loader.py:198:                plugin_id,
src/cryodaq/analytics/plugin_loader.py:199:                plugin_cls.__name__,
src/cryodaq/analytics/plugin_loader.py:206:    def _unload_plugin(self, plugin_id: str) -> None:
src/cryodaq/analytics/plugin_loader.py:210:            plugin_id:  Идентификатор плагина (обычно имя файла без расширения).
src/cryodaq/analytics/plugin_loader.py:212:        removed = self._plugins.pop(plugin_id, None)
src/cryodaq/analytics/plugin_loader.py:214:            logger.info("Плагин выгружен: id='%s'", plugin_id)
src/cryodaq/analytics/plugin_loader.py:216:            logger.debug("Попытка выгрузить незарегистрированный плагин '%s'", plugin_id)
src/cryodaq/analytics/plugin_loader.py:228:        полученные :class:`~cryodaq.analytics.base_plugin.DerivedMetric`
src/cryodaq/analytics/plugin_loader.py:254:            for plugin in list(self._plugins.values()):
src/cryodaq/analytics/plugin_loader.py:255:                plugin_id = plugin.plugin_id
src/cryodaq/analytics/plugin_loader.py:257:                    metrics: list[DerivedMetric] = await plugin.process(batch)
src/cryodaq/analytics/plugin_loader.py:261:                        plugin_id,
src/cryodaq/analytics/plugin_loader.py:268:                        channel=f"analytics/{plugin_id}/{metric.metric}",
src/cryodaq/analytics/plugin_loader.py:271:                        instrument_id=plugin_id,
src/cryodaq/analytics/plugin_loader.py:275:                            "plugin_id": plugin_id,
src/cryodaq/analytics/plugin_loader.py:286:        - новый файл → :meth:`_load_plugin`;
src/cryodaq/analytics/plugin_loader.py:287:        - изменённый файл (mtime отличается) → :meth:`_unload_plugin`
src/cryodaq/analytics/plugin_loader.py:288:          + :meth:`_load_plugin`;
src/cryodaq/analytics/plugin_loader.py:289:        - удалённый файл → :meth:`_unload_plugin`.
src/cryodaq/analytics/plugin_loader.py:294:        known_files: dict[str, float] = self._scan_plugins()
src/cryodaq/analytics/plugin_loader.py:300:                current_files = self._scan_plugins()
src/cryodaq/analytics/plugin_loader.py:306:                        self._load_plugin(self._plugins_dir / filename)
src/cryodaq/analytics/plugin_loader.py:309:                        self._unload_plugin(Path(filename).stem)
src/cryodaq/analytics/plugin_loader.py:310:                        self._load_plugin(self._plugins_dir / filename)
src/cryodaq/analytics/plugin_loader.py:316:                        self._unload_plugin(Path(filename).stem)
src/cryodaq/analytics/plugin_loader.py:329:    def _scan_plugins(self) -> dict[str, float]:
src/cryodaq/analytics/plugin_loader.py:334:            в ``plugins_dir``.  При ошибке доступа к файловой системе
src/cryodaq/analytics/plugin_loader.py:340:                for path in self._plugins_dir.glob("*.py")
src/cryodaq/analytics/plugin_loader.py:346:                self._plugins_dir,
docs/decisions/2026-04-24-b2b4fb5-investigation.md:13:`b2b4fb5`'s synchronous startup probe `_validate_bridge_startup()`
docs/decisions/2026-04-24-b2b4fb5-investigation.md:58:This is the **exact literal output** of `_validate_bridge_startup`
docs/decisions/2026-04-24-b2b4fb5-investigation.md:184:Rework `_validate_bridge_startup()` to retry the probe with bounded
src/cryodaq/core/scheduler.py:20:from cryodaq.core.broker import DataBroker
src/cryodaq/core/scheduler.py:84:        broker: DataBroker,
src/cryodaq/core/scheduler.py:350:        # we cannot persist (so persistence-first invariant blocks publish),
src/cryodaq/core/scheduler.py:390:                await self._sqlite_writer.write_immediate(combined)
src/cryodaq/core/scheduler.py:400:            # If write_immediate silently absorbed a disk-full error
docs/decisions/2026-04-24-d1-d4a-execution.md:36:- **HEAD:** `c3f4f86` — fix(diag): bounded-backoff retry in B1 capture probe (R1 repair for b2b4fb5)
docs/decisions/2026-04-24-d1-d4a-execution.md:43:New helper `_validate_bridge_startup(bridge, attempts=5, backoff_s=0.2, sleep_fn=time.sleep)`:
docs/decisions/2026-04-24-d1-d4a-execution.md:55:| 1 | dead bridge (is_alive=False) → raises without send_command | ✅ | `test_validate_bridge_startup_dead_bridge_raises_without_send_command` |
docs/decisions/2026-04-24-d1-d4a-execution.md:56:| 2 | alive + 2× non-OK + OK → succeeds after 3 attempts with fake sleep | ✅ | `test_validate_bridge_startup_succeeds_after_transient_non_ok` |
docs/decisions/2026-04-24-d1-d4a-execution.md:57:| 3 | alive + all non-OK → raises with last reply; sleeps bounded | ✅ | `test_validate_bridge_startup_all_non_ok_raises_with_last_reply` + `test_main_returns_nonzero_when_bridge_startup_fails` |
PROJECT_STATUS.md:40:2. **Persistence-first:** `SQLiteWriter.write_immediate()` → `DataBroker` → `SafetyBroker`.
PROJECT_STATUS.md:51:10. **OVERRANGE/UNDERRANGE** persist с `status` (`±inf` валидные REAL в SQLite). SENSOR_ERROR/TIMEOUT (NaN) отфильтровываются.
PROJECT_STATUS.md:55:14. **WAL mode verification:** raises `RuntimeError` если `PRAGMA journal_mode=WAL` вернул не `'wal'`.
PROJECT_STATUS.md:66:Instruments → Scheduler → SQLiteWriter → DataBroker → ZMQ → GUI (PySide6)
PROJECT_STATUS.md:67:                                       → SafetyBroker → SafetyManager
PROJECT_STATUS.md:71:- **Engine** (headless asyncio): drivers, scheduler, persistence, safety, alarms, interlocks, plugins
PROJECT_STATUS.md:206:  - K.2 — `post_build.py` копирует plugin YAML sidecars
PROJECT_STATUS.md:208:  - H.1 — runtime plugin loading trust boundary
PROJECT_STATUS.md:216:  - C.1 — Ubuntu 22.04 SQLite version gating (WAL-reset bug на libsqlite3 < 3.51.3)
PROJECT_STATUS.md:230:2. **Persistence-first** — SQLite WAL commit BEFORE any subscriber sees data.
PROJECT_STATUS.md:234:6. **OVERRANGE/UNDERRANGE persist** — `±inf` в REAL SQLite. NaN-valued statuses dropped до Phase 3.
PROJECT_STATUS.md:236:8. **WAL mode verification** — engine refuses to start, если SQLite не включает WAL.
PROJECT_STATUS.md:266:2. **Codex second-opinion** — независимый LLM-review committed diff. Ловит line-level семантику (wrong type, wrong API, wrong filter). Примеры Phase 2d: RUN_PERMITTED heartbeat gap (gated on `_active_sources` которая пустая в момент source start); `housekeeping.py` читает `alarms_v3.yaml:interlocks:` секцию, которую CC удалил как "dead config"; NaN vs ±inf IEEE 754 distinction (SQLite treats NaN as NULL).
PROJECT_STATUS.md:267:3. **Jules architectural review** — смотрит fault path целиком через несколько commit'ов. Находит cross-cutting вещи: R1 — `_fault_log_callback` не shielded; R2 — `_fault()` ordering vulnerability (callback после publish = escape path), calibration state mutation до persistence.
src/cryodaq/storage/sqlite_writer.py:1:"""SQLiteWriter — запись показаний в SQLite с WAL-режимом.
src/cryodaq/storage/sqlite_writer.py:98:    """Warn if running on a SQLite version affected by the March 2026 WAL-reset bug.
src/cryodaq/storage/sqlite_writer.py:100:    The bug affects SQLite versions in [3.7.0, 3.51.3) when multiple
src/cryodaq/storage/sqlite_writer.py:102:    instant". CryoDAQ uses WAL with multiple concurrent connections (writer,
src/cryodaq/storage/sqlite_writer.py:113:            "SQLite %d.%d.%d is affected by the March 2026 WAL-reset corruption "
src/cryodaq/storage/sqlite_writer.py:114:            "bug (range 3.7.0 – 3.51.2). CryoDAQ uses WAL with multiple "
src/cryodaq/storage/sqlite_writer.py:115:            "connections; upgrade to SQLite >= 3.51.3 in production. On Ubuntu "
src/cryodaq/storage/sqlite_writer.py:125:class SQLiteWriter:
src/cryodaq/storage/sqlite_writer.py:126:    """Асинхронный писатель показаний в SQLite.
src/cryodaq/storage/sqlite_writer.py:130:        writer = SQLiteWriter(data_dir=Path("./data"))
src/cryodaq/storage/sqlite_writer.py:153:        # Periodic explicit WAL checkpoint counter (DEEP_AUDIT_CC.md D.1).
src/cryodaq/storage/sqlite_writer.py:165:        self._persistence_failure_callback: Callable[[str], Awaitable[None]] | None = None
src/cryodaq/storage/sqlite_writer.py:197:        schedule the persistence-failure callback on it."""
src/cryodaq/storage/sqlite_writer.py:200:    def set_persistence_failure_callback(self, callback: Callable[[str], Awaitable[None]]) -> None:
src/cryodaq/storage/sqlite_writer.py:201:        """Register an async callback for persistence failures (disk full etc).
src/cryodaq/storage/sqlite_writer.py:205:        SafetyManager.on_persistence_failure can latch a fault.
src/cryodaq/storage/sqlite_writer.py:207:        self._persistence_failure_callback = callback
src/cryodaq/storage/sqlite_writer.py:209:    def _signal_persistence_failure(self, reason: str) -> None:
src/cryodaq/storage/sqlite_writer.py:210:        """Schedule persistence-failure callback on the engine event loop.
src/cryodaq/storage/sqlite_writer.py:217:        if self._persistence_failure_callback is None or self._loop is None:
src/cryodaq/storage/sqlite_writer.py:221:                self._persistence_failure_callback(reason),
src/cryodaq/storage/sqlite_writer.py:225:            logger.error("Failed to schedule persistence_failure callback: %s", exc)
src/cryodaq/storage/sqlite_writer.py:233:            # Final WAL checkpoint at rotation (DEEP_AUDIT_CC.md D.1, H.2).
src/cryodaq/storage/sqlite_writer.py:238:                logger.warning("Final WAL checkpoint at rotation failed: %s", exc)
src/cryodaq/storage/sqlite_writer.py:243:        # WAL with explicit checkpoint policy (DEEP_AUDIT_CC.md D.1).
src/cryodaq/storage/sqlite_writer.py:246:        result = conn.execute("PRAGMA journal_mode=WAL;").fetchone()
src/cryodaq/storage/sqlite_writer.py:250:                f"SQLite WAL mode could not be enabled at {db_path}. "
src/cryodaq/storage/sqlite_writer.py:253:                f"WSL with DrvFs, or read-only mount). CryoDAQ requires WAL "
src/cryodaq/storage/sqlite_writer.py:302:    # Only inf-valued statuses are persisted — SQLite accepts ±inf in a REAL
src/cryodaq/storage/sqlite_writer.py:303:    # column but rejects NaN (SQLite treats NaN as NULL, violating NOT NULL).
src/cryodaq/storage/sqlite_writer.py:373:                        "DISK FULL detected in SQLite write: %s. "
src/cryodaq/storage/sqlite_writer.py:378:                self._signal_persistence_failure(f"disk full: {exc}")
src/cryodaq/storage/sqlite_writer.py:380:                # write_immediate / scheduler and cause the historic tight
src/cryodaq/storage/sqlite_writer.py:388:        # cadence). Prevents WAL file growth under concurrent reader pressure.
src/cryodaq/storage/sqlite_writer.py:395:                logger.warning("Periodic WAL checkpoint failed: %s", exc)
src/cryodaq/storage/sqlite_writer.py:556:    async def write_immediate(self, readings: list[Reading]) -> None:
src/cryodaq/storage/sqlite_writer.py:557:        """Записать пакет синхронно (await до WAL commit).
src/cryodaq/storage/sqlite_writer.py:559:        Используется Scheduler для гарантии persistence-first:
src/cryodaq/storage/sqlite_writer.py:560:        данные попадают в DataBroker ТОЛЬКО после записи на диск.
src/cryodaq/storage/sqlite_writer.py:568:                "CRITICAL: Ошибка write_immediate (%d записей) — данные НЕ персистированы",
src/cryodaq/storage/sqlite_writer.py:618:        # persistence-first writes on _executor. The engine REP task awaits
src/cryodaq/storage/sqlite_writer.py:620:        # and was previously serialised against scheduler.write_immediate()
src/cryodaq/storage/sqlite_writer.py:625:        """Инициализировать writer без очереди (persistence-first режим).
src/cryodaq/storage/sqlite_writer.py:628:        Запись происходит через write_immediate(), вызываемый из Scheduler.
src/cryodaq/storage/sqlite_writer.py:632:        logger.info("SQLiteWriter запущен (immediate mode)")
src/cryodaq/storage/sqlite_writer.py:639:            "SQLiteWriter запущен (flush=%.1fs, batch=%d)", self._flush_interval_s, self._batch_size
src/cryodaq/storage/sqlite_writer.py:661:        logger.info("SQLiteWriter остановлен (записано: %d)", self._total_written)
src/cryodaq/storage/sqlite_writer.py:675:        """Read historical readings from SQLite.
CLAUDE.md:99:SafetyBroker (dedicated, overflow=FAULT)
CLAUDE.md:123:     1. SQLiteWriter.write_immediate()
CLAUDE.md:124:     2. THEN DataBroker.publish_batch()
CLAUDE.md:125:     3. THEN SafetyBroker.publish_batch()
CLAUDE.md:128:Invariant: if DataBroker has a reading, it has already been written to SQLite.
CLAUDE.md:175:- `src/cryodaq/core/broker.py` — DataBroker fan-out pub/sub
CLAUDE.md:189:- `src/cryodaq/core/scheduler.py` — instrument polling, persistence-first ordering
CLAUDE.md:198:- `src/cryodaq/analytics/base_plugin.py` — AnalyticsPlugin ABC
CLAUDE.md:203:- `src/cryodaq/analytics/plugin_loader.py` — hot-reload plugin pipeline (5s mtime polling)
CLAUDE.md:289:- `src/cryodaq/storage/sqlite_writer.py` — WAL-mode SQLite, daily rotation, persistence-first
CLAUDE.md:291:- `src/cryodaq/storage/csv_export.py` — экспорт данных из SQLite в CSV
CLAUDE.md:292:- `src/cryodaq/storage/hdf5_export.py` — экспорт данных из SQLite в HDF5
CLAUDE.md:294:- `src/cryodaq/storage/replay.py` — воспроизведение исторических данных из SQLite через DataBroker
CLAUDE.md:333:- `config/plugins.yaml`
CLAUDE.md:351:- Scheduler writes to SQLite before publishing to brokers.
CLAUDE.md:362:- **Модель:** `gpt-5.4` с high reasoning effort — ОБЯЗАТЕЛЬНО. `/codex` по умолчанию берёт o3, который слаб для нашего workflow. Всегда указывать в первых строках prompt блока `Model: gpt-5.4 / Reasoning effort: high` + inline flags если plugin их поддерживает. Если Codex ответил как o3 — retry с override.
CLAUDE.md:423:- Supported deployment: `pip install -e .` из корня репозитория. Wheel-install не self-contained — config/, plugins/, data/ находятся вне пакета. Используйте CRYODAQ_ROOT для нестандартных layout.

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/storage/sqlite_writer.py | sed -n '548,575p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   548	                except TimeoutError:
   549	                    break
   550	            if batch:
   551	                try:
   552	                    await loop.run_in_executor(executor, self._write_batch, batch)
   553	                except Exception:
   554	                    logger.exception("Ошибка записи батча (%d записей)", len(batch))
   555	
   556	    async def write_immediate(self, readings: list[Reading]) -> None:
   557	        """Записать пакет синхронно (await до WAL commit).
   558	
   559	        Используется Scheduler для гарантии persistence-first:
   560	        данные попадают в DataBroker ТОЛЬКО после записи на диск.
   561	        При ошибке — логирует CRITICAL и пробрасывает исключение.
   562	        """
   563	        loop = asyncio.get_running_loop()
   564	        try:
   565	            await loop.run_in_executor(self._executor, self._write_batch, readings)
   566	        except Exception:
   567	            logger.critical(
   568	                "CRITICAL: Ошибка write_immediate (%d записей) — данные НЕ персистированы",
   569	                len(readings),
   570	            )
   571	            raise
   572	
   573	    async def append_operator_log(
   574	        self,
   575	        *,

exec
/opt/homebrew/bin/bash -lc "rg -n \"PluginPipeline|plugin_pipeline|subscribe\\(|SQLiteWriter|write_immediate|analytics/\" src/cryodaq/engine.py src/cryodaq/core/broker.py src/cryodaq/storage -g '*.py'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
src/cryodaq/storage/sqlite_writer.py:1:"""SQLiteWriter — запись показаний в SQLite с WAL-режимом.
src/cryodaq/storage/sqlite_writer.py:125:class SQLiteWriter:
src/cryodaq/storage/sqlite_writer.py:130:        writer = SQLiteWriter(data_dir=Path("./data"))
src/cryodaq/storage/sqlite_writer.py:380:                # write_immediate / scheduler and cause the historic tight
src/cryodaq/storage/sqlite_writer.py:556:    async def write_immediate(self, readings: list[Reading]) -> None:
src/cryodaq/storage/sqlite_writer.py:568:                "CRITICAL: Ошибка write_immediate (%d записей) — данные НЕ персистированы",
src/cryodaq/storage/sqlite_writer.py:620:        # and was previously serialised against scheduler.write_immediate()
src/cryodaq/storage/sqlite_writer.py:628:        Запись происходит через write_immediate(), вызываемый из Scheduler.
src/cryodaq/storage/sqlite_writer.py:632:        logger.info("SQLiteWriter запущен (immediate mode)")
src/cryodaq/storage/sqlite_writer.py:639:            "SQLiteWriter запущен (flush=%.1fs, batch=%d)", self._flush_interval_s, self._batch_size
src/cryodaq/storage/sqlite_writer.py:661:        logger.info("SQLiteWriter остановлен (записано: %d)", self._total_written)
src/cryodaq/core/broker.py:47:        q = broker.subscribe("sqlite_writer", maxsize=5000)
src/cryodaq/core/broker.py:57:    async def subscribe(
src/cryodaq/core/broker.py:76:    async def unsubscribe(self, name: str) -> None:
src/cryodaq/engine.py:9:    [SQLiteWriter, ZMQPublisher, AlarmEngine, InterlockEngine, PluginPipeline]
src/cryodaq/engine.py:33:from cryodaq.analytics.plugin_loader import PluginPipeline
src/cryodaq/engine.py:72:from cryodaq.storage.sqlite_writer import SQLiteWriter
src/cryodaq/engine.py:162:            channel="analytics/operator_log_entry",
src/cryodaq/engine.py:173:    writer: SQLiteWriter,
src/cryodaq/engine.py:794:    writer: SQLiteWriter,
src/cryodaq/engine.py:903:    writer = SQLiteWriter(_DATA_DIR)
src/cryodaq/engine.py:956:    zmq_queue = await broker.subscribe("zmq_publisher")
src/cryodaq/engine.py:1103:        queue = await broker.subscribe("adaptive_throttle_runtime", maxsize=2000)
src/cryodaq/engine.py:1112:        queue = await broker.subscribe("alarm_v2_state_feed", maxsize=2000)
src/cryodaq/engine.py:1168:        queue = await broker.subscribe("sensor_diag_feed", maxsize=2000)
src/cryodaq/engine.py:1198:        queue = await broker.subscribe("vacuum_trend_feed", maxsize=2000)
src/cryodaq/engine.py:1492:    plugin_pipeline = PluginPipeline(broker, _PLUGINS_DIR)
src/cryodaq/engine.py:1600:    await plugin_pipeline.start()
src/cryodaq/engine.py:1719:    await plugin_pipeline.stop()

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/engine.py | sed -n '880,980p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   880	    safety_manager.load_config(safety_cfg)
   881	
   882	    housekeeping_raw = load_housekeeping_config(housekeeping_cfg)
   883	    # Phase 2b Codex H.1: merge legacy alarms.yaml/interlocks.yaml protection
   884	    # patterns with the modern alarms_v3.yaml critical channels. Without this
   885	    # the throttle thins critical channels even though alarms_v3 marks them
   886	    # CRITICAL.
   887	    legacy_patterns = load_protected_channel_patterns(alarms_cfg, interlocks_cfg)
   888	    alarms_v3_path = _CONFIG_DIR / "alarms_v3.yaml"
   889	    v3_patterns = load_critical_channels_from_alarms_v3(alarms_v3_path)
   890	    merged_patterns = list({*legacy_patterns, *v3_patterns})
   891	    logger.info(
   892	        "Adaptive-throttle protection: %d legacy + %d v3 = %d unique patterns",
   893	        len(legacy_patterns),
   894	        len(v3_patterns),
   895	        len(merged_patterns),
   896	    )
   897	    adaptive_throttle = AdaptiveThrottle(
   898	        housekeeping_raw.get("adaptive_throttle", {}),
   899	        protected_patterns=merged_patterns,
   900	    )
   901	
   902	    # SQLite — persistence-first: writer создаётся ДО scheduler
   903	    writer = SQLiteWriter(_DATA_DIR)
   904	    await writer.start_immediate()
   905	    # Disk-full graceful degradation (Phase 2a H.1): wire writer to the
   906	    # engine event loop and SafetyManager so a disk-full error in the
   907	    # writer thread can latch a safety fault via run_coroutine_threadsafe.
   908	    # The reverse hook (acknowledge_fault → clear writer flag) ensures
   909	    # polling does NOT resume until the operator explicitly acknowledges,
   910	    # even if free space recovered earlier (no auto-recovery on flapping).
   911	    writer.set_event_loop(asyncio.get_running_loop())
   912	    writer.set_persistence_failure_callback(safety_manager.on_persistence_failure)
   913	    safety_manager.set_persistence_failure_clear(writer.clear_disk_full)
   914	
   915	    # H.6: wire safety fault → operator_log machine event
   916	    async def _safety_fault_log_callback(
   917	        source: str,
   918	        message: str,
   919	        channel: str = "",
   920	        value: float = 0.0,
   921	    ) -> None:
   922	        entry = await writer.append_operator_log(
   923	            message=message,
   924	            author=source,
   925	            source="machine",
   926	            tags=("safety_fault", channel) if channel else ("safety_fault",),
   927	        )
   928	        # Codex followup: publish to broker so live consumers (GUI, web)
   929	        # see safety faults without waiting for SQLite refresh.
   930	        try:
   931	            await _publish_operator_log_entry(broker, entry)
   932	        except Exception as exc:
   933	            logger.error("Failed to publish safety fault operator_log entry: %s", exc)
   934	
   935	    safety_manager._fault_log_callback = _safety_fault_log_callback
   936	
   937	    # Calibration acquisition — continuous SRDG during calibration experiments
   938	    calibration_acquisition = CalibrationAcquisitionService(
   939	        writer,
   940	        channel_manager=get_channel_manager(),
   941	    )
   942	
   943	    # Планировщик — публикует в ОБА брокера, пишет на диск ДО публикации
   944	    scheduler = Scheduler(
   945	        broker,
   946	        safety_broker=safety_broker,
   947	        sqlite_writer=writer,
   948	        adaptive_throttle=adaptive_throttle,
   949	        calibration_acquisition=calibration_acquisition,
   950	        drain_timeout_s=safety_manager._config.scheduler_drain_timeout_s,
   951	    )
   952	    for cfg in driver_configs:
   953	        scheduler.add(cfg)
   954	
   955	    # ZMQ PUB
   956	    zmq_queue = await broker.subscribe("zmq_publisher")
   957	    zmq_pub = ZMQPublisher()
   958	
   959	    # Alarm Engine
   960	    alarm_engine = AlarmEngine(broker)
   961	    if alarms_cfg.exists():
   962	        alarm_engine.load_config(alarms_cfg)
   963	    else:
   964	        logger.warning("Файл тревог не найден: %s", alarms_cfg)
   965	
   966	    # Interlock Engine — действия делегируются SafetyManager.
   967	    # Phase 2a Codex I.1: the actions-dict callables are kept as no-ops for
   968	    # backwards compatibility with InterlockEngine's required interface, but
   969	    # the REAL safety routing happens via trip_handler which receives the
   970	    # full (condition, reading) context. Without this the action name and
   971	    # channel would be discarded and stop_source would behave as emergency_off.
   972	    async def _interlock_noop() -> None:
   973	        return None
   974	
   975	    interlock_actions: dict[str, Any] = {
   976	        "emergency_off": _interlock_noop,
   977	        "stop_source": _interlock_noop,
   978	    }
   979	
   980	    async def _interlock_trip_handler(condition: Any, reading: Any) -> None:

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/engine.py | sed -n '1480,1610p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
  1480	                pred = vacuum_trend.get_prediction()
  1481	                if pred is None:
  1482	                    return {"ok": True, "status": "no_data"}
  1483	                return {"ok": True, **asdict(pred)}
  1484	            return {"ok": False, "error": f"unknown command: {action}"}
  1485	        except Exception as exc:
  1486	            logger.error("Ошибка выполнения команды '%s': %s", action, exc)
  1487	            return {"ok": False, "error": str(exc)}
  1488	
  1489	    cmd_server = ZMQCommandServer(handler=_handle_gui_command)
  1490	
  1491	    # Plugin Pipeline
  1492	    plugin_pipeline = PluginPipeline(broker, _PLUGINS_DIR)
  1493	
  1494	    # --- CooldownService (прогноз охлаждения) ---
  1495	    cooldown_service: Any = None
  1496	    cooldown_cfg_path = _cfg("cooldown")
  1497	    if cooldown_cfg_path.exists():
  1498	        try:
  1499	            with cooldown_cfg_path.open(encoding="utf-8") as fh:
  1500	                _cd_raw = yaml.safe_load(fh) or {}
  1501	            _cd_cfg = _cd_raw.get("cooldown", {})
  1502	            if _cd_cfg.get("enabled", False):
  1503	                from cryodaq.analytics.cooldown_service import CooldownService
  1504	
  1505	                cooldown_service = CooldownService(
  1506	                    broker=broker,
  1507	                    config=_cd_cfg,
  1508	                    model_dir=_PROJECT_ROOT / _cd_cfg.get("model_dir", "data/cooldown_model"),
  1509	                )
  1510	                logger.info("CooldownService создан")
  1511	        except Exception as exc:
  1512	            logger.error("Ошибка создания CooldownService: %s", exc)
  1513	
  1514	    # --- Уведомления (один раз разбираем YAML) ---
  1515	    periodic_reporter: PeriodicReporter | None = None
  1516	    telegram_bot: TelegramCommandBot | None = None
  1517	    escalation_service: EscalationService | None = None
  1518	    notifications_cfg = _cfg("notifications")
  1519	    if notifications_cfg.exists():
  1520	        try:
  1521	            with notifications_cfg.open(encoding="utf-8") as fh:
  1522	                notif_raw: dict[str, Any] = yaml.safe_load(fh) or {}
  1523	
  1524	            tg_cfg = notif_raw.get("telegram", {})
  1525	            bot_token = str(tg_cfg.get("bot_token", ""))
  1526	            token_valid = bot_token and bot_token != "YOUR_BOT_TOKEN_HERE"
  1527	
  1528	            # PeriodicReporter
  1529	            pr_cfg = notif_raw.get("periodic_report", {})
  1530	            if pr_cfg.get("enabled", False) and token_valid:
  1531	                periodic_reporter = PeriodicReporter(
  1532	                    broker,
  1533	                    alarm_engine,
  1534	                    bot_token=bot_token,
  1535	                    chat_id=tg_cfg.get("chat_id", 0),
  1536	                    report_interval_s=float(pr_cfg.get("report_interval_s", 1800)),
  1537	                    chart_hours=float(pr_cfg.get("chart_hours", 2.0)),
  1538	                    include_channels=pr_cfg.get("include_channels"),
  1539	                )
  1540	                logger.info("PeriodicReporter создан")
  1541	
  1542	            # TelegramCommandBot
  1543	            cmd_cfg = notif_raw.get("commands", {})
  1544	            commands_enabled = bool(cmd_cfg.get("enabled", False)) and token_valid
  1545	            if commands_enabled:
  1546	                allowed_raw = (
  1547	                    tg_cfg.get("allowed_chat_ids") or cmd_cfg.get("allowed_chat_ids") or []
  1548	                )
  1549	                allowed_ids = [int(x) for x in allowed_raw]
  1550	                # Phase 2b Codex K.1 — TelegramCommandBot raises on empty list,
  1551	                # so refuse to enable cleanly here with a config-error log
  1552	                # rather than letting the constructor surface an exception
  1553	                # mid-startup.
  1554	                if not allowed_ids:
  1555	                    logger.error(
  1556	                        "Telegram commands are enabled but allowed_chat_ids "
  1557	                        "is empty. Refusing to start TelegramCommandBot. "
  1558	                        "Add at least one chat ID or set commands.enabled: false."
  1559	                    )
  1560	                else:
  1561	                    telegram_bot = TelegramCommandBot(
  1562	                        broker,
  1563	                        alarm_engine,
  1564	                        bot_token=bot_token,
  1565	                        allowed_chat_ids=allowed_ids,
  1566	                        poll_interval_s=float(cmd_cfg.get("poll_interval_s", 2.0)),
  1567	                        command_handler=_handle_gui_command,
  1568	                    )
  1569	                    logger.info(
  1570	                        "TelegramCommandBot создан (allowed=%d chat ids)",
  1571	                        len(allowed_ids),
  1572	                    )
  1573	
  1574	            # EscalationService
  1575	            if token_valid and notif_raw.get("escalation"):
  1576	                from cryodaq.notifications.telegram import TelegramNotifier
  1577	
  1578	                _esc_notifier = TelegramNotifier(
  1579	                    bot_token=bot_token,
  1580	                    chat_id=tg_cfg.get("chat_id", 0),
  1581	                )
  1582	                escalation_service = EscalationService(_esc_notifier, notif_raw)
  1583	                logger.info("EscalationService создан (%d уровней)", len(notif_raw["escalation"]))
  1584	
  1585	            if not token_valid:
  1586	                logger.info("Telegram-уведомления отключены (bot_token не настроен)")
  1587	        except Exception as exc:
  1588	            logger.error("Ошибка загрузки конфигурации уведомлений: %s", exc)
  1589	    else:
  1590	        logger.info("Файл конфигурации уведомлений не найден: %s", notifications_cfg)
  1591	
  1592	    # --- Запуск всех подсистем ---
  1593	    await safety_manager.start()
  1594	    logger.info("SafetyManager запущен: состояние=%s", safety_manager.state.value)
  1595	    # writer уже запущен через start_immediate() выше
  1596	    await zmq_pub.start(zmq_queue)
  1597	    await cmd_server.start()
  1598	    await alarm_engine.start()
  1599	    await interlock_engine.start()
  1600	    await plugin_pipeline.start()
  1601	    if cooldown_service is not None:
  1602	        await cooldown_service.start()
  1603	    if periodic_reporter is not None:
  1604	        await periodic_reporter.start()
  1605	    if telegram_bot is not None:
  1606	        await telegram_bot.start()
  1607	    await scheduler.start()
  1608	    throttle_task = asyncio.create_task(_track_runtime_signals(), name="adaptive_throttle_runtime")
  1609	    alarm_v2_feed_task = asyncio.create_task(_alarm_v2_feed_readings(), name="alarm_v2_feed")
  1610	    alarm_v2_tick_task: asyncio.Task | None = None

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/core/broker.py | sed -n '1,140p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	"""DataBroker — центральная шина данных движка CryoDAQ.
     2	
     3	Принимает Reading от драйверов, раздаёт подписчикам (writer, alarms, ZMQ publisher)
     4	через ограниченные asyncio.Queue. Переполненные очереди сбрасывают старые данные
     5	(OverflowPolicy.DROP_OLDEST) — утечки памяти недопустимы.
     6	"""
     7	
     8	from __future__ import annotations
     9	
    10	import asyncio
    11	import logging
    12	from collections.abc import Callable
    13	from dataclasses import dataclass, field
    14	from enum import Enum
    15	
    16	from cryodaq.drivers.base import Reading
    17	
    18	logger = logging.getLogger(__name__)
    19	
    20	DEFAULT_QUEUE_SIZE = 10_000
    21	
    22	
    23	class OverflowPolicy(Enum):
    24	    """Политика при переполнении очереди подписчика."""
    25	
    26	    DROP_OLDEST = "drop_oldest"
    27	    DROP_NEWEST = "drop_newest"
    28	
    29	
    30	@dataclass
    31	class Subscription:
    32	    """Подписка на данные брокера."""
    33	
    34	    name: str
    35	    queue: asyncio.Queue[Reading]
    36	    policy: OverflowPolicy = OverflowPolicy.DROP_OLDEST
    37	    filter_fn: Callable[[Reading], bool] | None = None
    38	    dropped: int = field(default=0, init=False)
    39	
    40	
    41	class DataBroker:
    42	    """Fan-out брокер: драйверы публикуют Reading, подписчики получают копии.
    43	
    44	    Использование::
    45	
    46	        broker = DataBroker()
    47	        q = broker.subscribe("sqlite_writer", maxsize=5000)
    48	        await broker.publish(reading)
    49	        r = await q.get()
    50	    """
    51	
    52	    def __init__(self) -> None:
    53	        self._subscribers: dict[str, Subscription] = {}
    54	        self._lock = asyncio.Lock()
    55	        self._total_published: int = 0
    56	
    57	    async def subscribe(
    58	        self,
    59	        name: str,
    60	        *,
    61	        maxsize: int = DEFAULT_QUEUE_SIZE,
    62	        policy: OverflowPolicy = OverflowPolicy.DROP_OLDEST,
    63	        filter_fn: Callable[[Reading], bool] | None = None,
    64	    ) -> asyncio.Queue[Reading]:
    65	        """Создать подписку. Возвращает очередь для чтения."""
    66	        async with self._lock:
    67	            if name in self._subscribers:
    68	                raise ValueError(f"Подписчик '{name}' уже зарегистрирован")
    69	            queue: asyncio.Queue[Reading] = asyncio.Queue(maxsize=maxsize)
    70	            self._subscribers[name] = Subscription(
    71	                name=name, queue=queue, policy=policy, filter_fn=filter_fn
    72	            )
    73	            logger.info("Подписчик '%s' зарегистрирован (maxsize=%d)", name, maxsize)
    74	            return queue
    75	
    76	    async def unsubscribe(self, name: str) -> None:
    77	        """Удалить подписку."""
    78	        async with self._lock:
    79	            sub = self._subscribers.pop(name, None)
    80	            if sub:
    81	                logger.info("Подписчик '%s' удалён (потеряно сообщений: %d)", name, sub.dropped)
    82	
    83	    async def publish(self, reading: Reading) -> None:
    84	        """Разослать Reading всем подписчикам."""
    85	        self._total_published += 1
    86	        for sub in tuple(self._subscribers.values()):
    87	            try:
    88	                if sub.filter_fn and not sub.filter_fn(reading):
    89	                    continue
    90	                if sub.queue.full():
    91	                    if sub.policy == OverflowPolicy.DROP_OLDEST:
    92	                        try:
    93	                            sub.queue.get_nowait()
    94	                        except asyncio.QueueEmpty:
    95	                            pass
    96	                        sub.dropped += 1
    97	                    elif sub.policy == OverflowPolicy.DROP_NEWEST:
    98	                        sub.dropped += 1
    99	                        continue
   100	                try:
   101	                    sub.queue.put_nowait(reading)
   102	                except asyncio.QueueFull:
   103	                    sub.dropped += 1
   104	            except asyncio.CancelledError:
   105	                raise
   106	            except Exception:
   107	                logger.exception(
   108	                    "DataBroker subscriber '%s' raised during publish; continuing fan-out",
   109	                    sub.name,
   110	                )
   111	
   112	    async def publish_batch(self, readings: list[Reading]) -> None:
   113	        """Опубликовать пакет показаний."""
   114	        for reading in readings:
   115	            await self.publish(reading)
   116	
   117	    @property
   118	    def stats(self) -> dict[str, dict[str, int]]:
   119	        """Статистика по подписчикам (для мониторинга)."""
   120	        return {
   121	            name: {
   122	                "queued": sub.queue.qsize(),
   123	                "dropped": sub.dropped,
   124	            }
   125	            for name, sub in self._subscribers.items()
   126	        } | {"_total_published": {"count": self._total_published}}

exec
/opt/homebrew/bin/bash -lc "nl -ba config/plugins.yaml | sed -n '1,220p'
rg -n \"plugins.yaml|plugin\" src/cryodaq/engine.py src/cryodaq/analytics/*.py CLAUDE.md PROJECT_STATUS.md README.md" in /Users/vladimir/Projects/cryodaq
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
src/cryodaq/analytics/base_plugin.py:27:        plugin_id:  Уникальный идентификатор плагина-источника.
src/cryodaq/analytics/base_plugin.py:35:    plugin_id: str
src/cryodaq/analytics/base_plugin.py:43:        plugin_id: str,
src/cryodaq/analytics/base_plugin.py:52:            plugin_id:  Идентификатор плагина.
src/cryodaq/analytics/base_plugin.py:63:            plugin_id=plugin_id,
src/cryodaq/analytics/base_plugin.py:84:                return [DerivedMetric.now(self.plugin_id, "my_metric", 42.0, "arb")]
src/cryodaq/analytics/base_plugin.py:87:    def __init__(self, plugin_id: str) -> None:
src/cryodaq/analytics/base_plugin.py:91:            plugin_id:  Уникальный идентификатор плагина в рамках пайплайна.
src/cryodaq/analytics/base_plugin.py:94:        self._plugin_id = plugin_id
src/cryodaq/analytics/base_plugin.py:98:    def plugin_id(self) -> str:
src/cryodaq/analytics/base_plugin.py:100:        return self._plugin_id
src/cryodaq/analytics/plugin_loader.py:22:from cryodaq.analytics.base_plugin import AnalyticsPlugin, DerivedMetric
src/cryodaq/analytics/plugin_loader.py:30:_SUBSCRIBE_NAME = "plugin_pipeline"
src/cryodaq/analytics/plugin_loader.py:42:        pipeline = PluginPipeline(broker, Path("plugins/"))
src/cryodaq/analytics/plugin_loader.py:51:        plugins_dir: Path,
src/cryodaq/analytics/plugin_loader.py:59:            plugins_dir:       Директория с файлами плагинов (``.py``).
src/cryodaq/analytics/plugin_loader.py:63:        self._plugins_dir = plugins_dir
src/cryodaq/analytics/plugin_loader.py:64:        self._plugins: dict[str, AnalyticsPlugin] = {}
src/cryodaq/analytics/plugin_loader.py:78:        Подписывается на брокер, загружает все плагины из ``plugins_dir``,
src/cryodaq/analytics/plugin_loader.py:88:        self._plugins_dir.mkdir(parents=True, exist_ok=True)
src/cryodaq/analytics/plugin_loader.py:89:        for path in sorted(self._plugins_dir.glob("*.py")):
src/cryodaq/analytics/plugin_loader.py:90:            self._load_plugin(path)
src/cryodaq/analytics/plugin_loader.py:99:            len(self._plugins),
src/cryodaq/analytics/plugin_loader.py:129:    def _load_plugin(self, path: Path) -> None:
src/cryodaq/analytics/plugin_loader.py:133:        :class:`~cryodaq.analytics.base_plugin.AnalyticsPlugin`,
src/cryodaq/analytics/plugin_loader.py:143:            plugin_id = path.stem
src/cryodaq/analytics/plugin_loader.py:144:            spec = importlib.util.spec_from_file_location(f"cryodaq_plugin_{plugin_id}", path)
src/cryodaq/analytics/plugin_loader.py:146:                logger.error("Не удалось создать spec для плагина '%s': %s", plugin_id, path)
src/cryodaq/analytics/plugin_loader.py:152:            plugin_cls: type[AnalyticsPlugin] | None = None
src/cryodaq/analytics/plugin_loader.py:160:                    plugin_cls = obj
src/cryodaq/analytics/plugin_loader.py:163:            if plugin_cls is None:
src/cryodaq/analytics/plugin_loader.py:170:            # Плагин может определять __init__(self) без аргументов (с plugin_id
src/cryodaq/analytics/plugin_loader.py:171:            # как атрибутом класса) или __init__(self, plugin_id).
src/cryodaq/analytics/plugin_loader.py:173:                plugin = plugin_cls(plugin_id)
src/cryodaq/analytics/plugin_loader.py:175:                plugin = plugin_cls()
src/cryodaq/analytics/plugin_loader.py:176:                # Если плагин не задал plugin_id — установить принудительно
src/cryodaq/analytics/plugin_loader.py:177:                if plugin.plugin_id != plugin_id:
src/cryodaq/analytics/plugin_loader.py:178:                    plugin._plugin_id = plugin_id
src/cryodaq/analytics/plugin_loader.py:185:                    plugin.configure(config)
src/cryodaq/analytics/plugin_loader.py:186:                    logger.debug("Конфиг '%s' применён к плагину '%s'", config_path, plugin_id)
src/cryodaq/analytics/plugin_loader.py:191:                        plugin_id,
src/cryodaq/analytics/plugin_loader.py:195:            self._plugins[plugin_id] = plugin
src/cryodaq/analytics/plugin_loader.py:198:                plugin_id,
src/cryodaq/analytics/plugin_loader.py:199:                plugin_cls.__name__,
src/cryodaq/analytics/plugin_loader.py:206:    def _unload_plugin(self, plugin_id: str) -> None:
src/cryodaq/analytics/plugin_loader.py:210:            plugin_id:  Идентификатор плагина (обычно имя файла без расширения).
src/cryodaq/analytics/plugin_loader.py:212:        removed = self._plugins.pop(plugin_id, None)
src/cryodaq/analytics/plugin_loader.py:214:            logger.info("Плагин выгружен: id='%s'", plugin_id)
src/cryodaq/analytics/plugin_loader.py:216:            logger.debug("Попытка выгрузить незарегистрированный плагин '%s'", plugin_id)
src/cryodaq/analytics/plugin_loader.py:228:        полученные :class:`~cryodaq.analytics.base_plugin.DerivedMetric`
src/cryodaq/analytics/plugin_loader.py:254:            for plugin in list(self._plugins.values()):
src/cryodaq/analytics/plugin_loader.py:255:                plugin_id = plugin.plugin_id
src/cryodaq/analytics/plugin_loader.py:257:                    metrics: list[DerivedMetric] = await plugin.process(batch)
src/cryodaq/analytics/plugin_loader.py:261:                        plugin_id,
src/cryodaq/analytics/plugin_loader.py:268:                        channel=f"analytics/{plugin_id}/{metric.metric}",
src/cryodaq/analytics/plugin_loader.py:271:                        instrument_id=plugin_id,
src/cryodaq/analytics/plugin_loader.py:275:                            "plugin_id": plugin_id,
src/cryodaq/analytics/plugin_loader.py:286:        - новый файл → :meth:`_load_plugin`;
src/cryodaq/analytics/plugin_loader.py:287:        - изменённый файл (mtime отличается) → :meth:`_unload_plugin`
src/cryodaq/analytics/plugin_loader.py:288:          + :meth:`_load_plugin`;
src/cryodaq/analytics/plugin_loader.py:289:        - удалённый файл → :meth:`_unload_plugin`.
src/cryodaq/analytics/plugin_loader.py:294:        known_files: dict[str, float] = self._scan_plugins()
src/cryodaq/analytics/plugin_loader.py:300:                current_files = self._scan_plugins()
src/cryodaq/analytics/plugin_loader.py:306:                        self._load_plugin(self._plugins_dir / filename)
src/cryodaq/analytics/plugin_loader.py:309:                        self._unload_plugin(Path(filename).stem)
src/cryodaq/analytics/plugin_loader.py:310:                        self._load_plugin(self._plugins_dir / filename)
src/cryodaq/analytics/plugin_loader.py:316:                        self._unload_plugin(Path(filename).stem)
src/cryodaq/analytics/plugin_loader.py:329:    def _scan_plugins(self) -> dict[str, float]:
src/cryodaq/analytics/plugin_loader.py:334:            в ``plugins_dir``.  При ошибке доступа к файловой системе
src/cryodaq/analytics/plugin_loader.py:340:                for path in self._plugins_dir.glob("*.py")
src/cryodaq/analytics/plugin_loader.py:346:                self._plugins_dir,
src/cryodaq/engine.py:33:from cryodaq.analytics.plugin_loader import PluginPipeline
src/cryodaq/engine.py:82:_PLUGINS_DIR = _PROJECT_ROOT / "plugins"
src/cryodaq/engine.py:1058:    _plugins_cfg_path = _cfg("plugins")
src/cryodaq/engine.py:1059:    _plugins_raw: dict[str, Any] = {}
src/cryodaq/engine.py:1060:    if _plugins_cfg_path.exists():
src/cryodaq/engine.py:1061:        with _plugins_cfg_path.open(encoding="utf-8") as fh:
src/cryodaq/engine.py:1062:            _plugins_raw = yaml.safe_load(fh) or {}
src/cryodaq/engine.py:1063:    _sd_cfg = _plugins_raw.get("sensor_diagnostics", {})
src/cryodaq/engine.py:1080:        logger.info("SensorDiagnostics: отключён (plugins.yaml не найден или enabled=false)")
src/cryodaq/engine.py:1083:    _vt_cfg = _plugins_raw.get("vacuum_trend", {})
src/cryodaq/engine.py:1492:    plugin_pipeline = PluginPipeline(broker, _PLUGINS_DIR)
src/cryodaq/engine.py:1600:    await plugin_pipeline.start()
src/cryodaq/engine.py:1715:    # Порядок: scheduler → plugins → alarms → interlocks → writer → zmq
src/cryodaq/engine.py:1719:    await plugin_pipeline.stop()
PROJECT_STATUS.md:71:- **Engine** (headless asyncio): drivers, scheduler, persistence, safety, alarms, interlocks, plugins
PROJECT_STATUS.md:206:  - K.2 — `post_build.py` копирует plugin YAML sidecars
PROJECT_STATUS.md:208:  - H.1 — runtime plugin loading trust boundary
README.md:166:- `config/plugins.yaml` — sensor_diagnostics и vacuum_trend feature flags
README.md:244:  analytics/          # calibration fitter, cooldown, plugins, vacuum trend
CLAUDE.md:198:- `src/cryodaq/analytics/base_plugin.py` — AnalyticsPlugin ABC
CLAUDE.md:203:- `src/cryodaq/analytics/plugin_loader.py` — hot-reload plugin pipeline (5s mtime polling)
CLAUDE.md:333:- `config/plugins.yaml`
CLAUDE.md:362:- **Модель:** `gpt-5.4` с high reasoning effort — ОБЯЗАТЕЛЬНО. `/codex` по умолчанию берёт o3, который слаб для нашего workflow. Всегда указывать в первых строках prompt блока `Model: gpt-5.4 / Reasoning effort: high` + inline flags если plugin их поддерживает. Если Codex ответил как o3 — retry с override.
CLAUDE.md:423:- Supported deployment: `pip install -e .` из корня репозитория. Wheel-install не self-contained — config/, plugins/, data/ находятся вне пакета. Используйте CRYODAQ_ROOT для нестандартных layout.
src/cryodaq/analytics/cooldown_service.py:21:from cryodaq.analytics.base_plugin import DerivedMetric
src/cryodaq/analytics/cooldown_service.py:418:            plugin_id="cooldown_predictor",
src/cryodaq/analytics/cooldown_service.py:431:            metadata=metadata | {"plugin_id": "cooldown_predictor"},

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/engine.py | sed -n '1048,1095p'
nl -ba src/cryodaq/engine.py | sed -n '1096,1225p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
  1048	    alarm_v2_evaluator = AlarmEvaluator(
  1049	        _alarm_v2_state_tracker, _alarm_v2_rate, _alarm_v2_phase, _alarm_v2_setpoint
  1050	    )
  1051	    alarm_v2_state_mgr = AlarmStateManager()
  1052	    if _alarm_v2_configs:
  1053	        logger.info("Alarm Engine v2: загружено %d алармов", len(_alarm_v2_configs))
  1054	    else:
  1055	        logger.info("Alarm Engine v2: config/alarms_v3.yaml не найден, v2 отключён")
  1056	
  1057	    # --- Sensor Diagnostics Engine ---
  1058	    _plugins_cfg_path = _cfg("plugins")
  1059	    _plugins_raw: dict[str, Any] = {}
  1060	    if _plugins_cfg_path.exists():
  1061	        with _plugins_cfg_path.open(encoding="utf-8") as fh:
  1062	            _plugins_raw = yaml.safe_load(fh) or {}
  1063	    _sd_cfg = _plugins_raw.get("sensor_diagnostics", {})
  1064	    _sd_enabled = _sd_cfg.get("enabled", False)
  1065	    sensor_diag: SensorDiagnosticsEngine | None = None
  1066	    if _sd_enabled:
  1067	        _ch_mgr = get_channel_manager()
  1068	        # Build correlation groups from config; channel ids use display prefix (Т1→T1)
  1069	        sensor_diag = SensorDiagnosticsEngine(config=_sd_cfg)
  1070	        # Set display names from channel_manager
  1071	        sensor_diag.set_channel_names(
  1072	            {ch_id: _ch_mgr.get_display_name(ch_id) for ch_id in _ch_mgr.get_all()}
  1073	        )
  1074	        logger.info(
  1075	            "SensorDiagnostics: enabled, update_interval=%ds, groups=%d",
  1076	            _sd_cfg.get("update_interval_s", 10),
  1077	            len(_sd_cfg.get("correlation_groups", {})),
  1078	        )
  1079	    else:
  1080	        logger.info("SensorDiagnostics: отключён (plugins.yaml не найден или enabled=false)")
  1081	
  1082	    # --- Vacuum Trend Predictor ---
  1083	    _vt_cfg = _plugins_raw.get("vacuum_trend", {})
  1084	    _vt_enabled = _vt_cfg.get("enabled", False)
  1085	    vacuum_trend: VacuumTrendPredictor | None = None
  1086	    if _vt_enabled:
  1087	        vacuum_trend = VacuumTrendPredictor(config=_vt_cfg)
  1088	        logger.info(
  1089	            "VacuumTrendPredictor: enabled, window=%ds, targets=%s",
  1090	            _vt_cfg.get("window_s", 3600),
  1091	            _vt_cfg.get("targets_mbar", [1e-4, 1e-5, 1e-6]),
  1092	        )
  1093	    else:
  1094	        logger.info("VacuumTrendPredictor: отключён")
  1095	
  1096	    housekeeping_service = HousekeepingService(
  1097	        _DATA_DIR,
  1098	        experiment_manager.data_dir / "experiments",
  1099	        config=housekeeping_raw.get("retention", {}),
  1100	    )
  1101	
  1102	    async def _track_runtime_signals() -> None:
  1103	        queue = await broker.subscribe("adaptive_throttle_runtime", maxsize=2000)
  1104	        try:
  1105	            while True:
  1106	                adaptive_throttle.observe_runtime_signal(await queue.get())
  1107	        except asyncio.CancelledError:
  1108	            return
  1109	
  1110	    async def _alarm_v2_feed_readings() -> None:
  1111	        """Подписаться на DataBroker и кормить v2 channel_state + rate_estimator."""
  1112	        queue = await broker.subscribe("alarm_v2_state_feed", maxsize=2000)
  1113	        try:
  1114	            while True:
  1115	                reading: Reading = await queue.get()
  1116	                _alarm_v2_state_tracker.update(reading)
  1117	                _alarm_v2_rate.push(
  1118	                    reading.channel,
  1119	                    reading.timestamp.timestamp(),
  1120	                    reading.value,
  1121	                )
  1122	        except asyncio.CancelledError:
  1123	            return
  1124	
  1125	    # Strong-ref set for fire-and-forget Telegram dispatch tasks.
  1126	    # Without this the loop only weak-refs tasks and GC can drop a pending
  1127	    # alarm notification mid-flight. See DEEP_AUDIT_CC.md A.1/A.2/I.2.
  1128	    _alarm_dispatch_tasks: set[asyncio.Task] = set()
  1129	
  1130	    async def _alarm_v2_tick() -> None:
  1131	        """Периодически вычислять алармы v2 и диспетчеризировать события."""
  1132	        poll_s = _alarm_v2_engine_cfg.poll_interval_s
  1133	        while True:
  1134	            await asyncio.sleep(poll_s)
  1135	            if not _alarm_v2_configs:
  1136	                continue
  1137	            current_phase = _alarm_v2_phase.get_current_phase()
  1138	            for alarm_cfg in _alarm_v2_configs:
  1139	                # Проверка фазового фильтра
  1140	                if alarm_cfg.phase_filter is not None:
  1141	                    if current_phase not in alarm_cfg.phase_filter:
  1142	                        # Вне фазы — явно очистить если был активен
  1143	                        alarm_v2_state_mgr.process(alarm_cfg.alarm_id, None, alarm_cfg.config)
  1144	                        continue
  1145	                try:
  1146	                    event = alarm_v2_evaluator.evaluate(alarm_cfg.alarm_id, alarm_cfg.config)
  1147	                    transition = alarm_v2_state_mgr.process(
  1148	                        alarm_cfg.alarm_id, event, alarm_cfg.config
  1149	                    )
  1150	                    if transition == "TRIGGERED" and event is not None:
  1151	                        # GUI polls via alarm_v2_status command; optionally notify via Telegram
  1152	                        if "telegram" in alarm_cfg.notify and telegram_bot is not None:
  1153	                            msg = f"⚠ [{event.level}] {event.alarm_id}\n{event.message}"
  1154	                            t = asyncio.create_task(
  1155	                                telegram_bot._send_to_all(msg),
  1156	                                name=f"alarm_v2_tg_{alarm_cfg.alarm_id}",
  1157	                            )
  1158	                            _alarm_dispatch_tasks.add(t)
  1159	                            t.add_done_callback(_alarm_dispatch_tasks.discard)
  1160	                except Exception as exc:
  1161	                    logger.error("Alarm v2 tick error %s: %s", alarm_cfg.alarm_id, exc)
  1162	
  1163	    # --- Sensor diagnostics feed + tick tasks ---
  1164	    async def _sensor_diag_feed() -> None:
  1165	        """Feed readings into SensorDiagnosticsEngine buffers."""
  1166	        if sensor_diag is None:
  1167	            return
  1168	        queue = await broker.subscribe("sensor_diag_feed", maxsize=2000)
  1169	        try:
  1170	            while True:
  1171	                reading: Reading = await queue.get()
  1172	                sensor_diag.push(
  1173	                    reading.channel,
  1174	                    reading.timestamp.timestamp(),
  1175	                    reading.value,
  1176	                )
  1177	        except asyncio.CancelledError:
  1178	            return
  1179	
  1180	    async def _sensor_diag_tick() -> None:
  1181	        """Periodically recompute sensor diagnostics."""
  1182	        if sensor_diag is None:
  1183	            return
  1184	        interval = _sd_cfg.get("update_interval_s", 10)
  1185	        while True:
  1186	            await asyncio.sleep(interval)
  1187	            try:
  1188	                sensor_diag.update()
  1189	            except Exception as exc:
  1190	                logger.error("SensorDiagnostics tick error: %s", exc)
  1191	
  1192	    # --- Vacuum trend feed + tick tasks ---
  1193	    async def _vacuum_trend_feed() -> None:
  1194	        """Feed pressure readings into VacuumTrendPredictor."""
  1195	        if vacuum_trend is None:
  1196	            return
  1197	        pressure_channel = _vt_cfg.get("pressure_channel", "")
  1198	        queue = await broker.subscribe("vacuum_trend_feed", maxsize=2000)
  1199	        try:
  1200	            while True:
  1201	                reading: Reading = await queue.get()
  1202	                # Accept readings from the pressure channel or any mbar-unit reading
  1203	                if pressure_channel and reading.channel != pressure_channel:
  1204	                    if reading.unit != "mbar":
  1205	                        continue
  1206	                elif not pressure_channel and reading.unit != "mbar":
  1207	                    continue
  1208	                vacuum_trend.push(reading.timestamp.timestamp(), reading.value)
  1209	        except asyncio.CancelledError:
  1210	            return
  1211	
  1212	    async def _vacuum_trend_tick() -> None:
  1213	        """Periodically recompute vacuum trend prediction."""
  1214	        if vacuum_trend is None:
  1215	            return
  1216	        interval = _vt_cfg.get("update_interval_s", 30)
  1217	        while True:
  1218	            await asyncio.sleep(interval)
  1219	            try:
  1220	                vacuum_trend.update()
  1221	            except Exception as exc:
  1222	                logger.error("VacuumTrendPredictor tick error: %s", exc)
  1223	
  1224	    # Обработчик команд от GUI — через SafetyManager
  1225	    async def _handle_gui_command(cmd: dict[str, Any]) -> dict[str, Any]:

exec
/opt/homebrew/bin/bash -lc "nl -ba config/instruments.yaml | sed -n '1,220p'" in /Users/vladimir/Projects/cryodaq
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

exec
/opt/homebrew/bin/bash -lc 'rg -n "class LakeShore|KRDG|SRDG|RDGST|_mock_sensor_unit|_use_per_channel|_krdg|runtime|calibration|IDN|GPIB" src/cryodaq/drivers/instruments/lakeshore_218s.py' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
1:"""LakeShore 218S driver with optional runtime calibration routing."""
11:from cryodaq.analytics.calibration import CalibrationStore
13:from cryodaq.drivers.transport.gpib import GPIBTransport
20:def _mock_sensor_unit(temp_k: float) -> float:
24:class LakeShore218S(InstrumentDriver):
32:        calibration_store: CalibrationStore | None = None,
37:        self._transport = GPIBTransport(mock=mock)
39:        self._calibration_store = calibration_store
40:        self._runtime_warning_cache: set[tuple[str, str]] = set()
41:        self._use_per_channel_krdg: bool = False
42:        self._use_per_channel_srdg: bool = False
43:        self._krdg0_fail_count: int = 0
45:        self._krdg_batch_retry_interval_s: float = 60.0
47:        self._krdg_last_batch_retry: float = 0.0
57:            # Phase 2c Codex F.1: validate IDN with retry-after-clear fallback.
59:            # mis-routing to a wrong GPIB address — KRDG? would still produce
66:                    idn_raw = (await self._transport.query("*IDN?")).strip()
69:                        "%s: *IDN? query failed (attempt %d/2): %s",
80:                    log.info("%s: IDN verified: %s", self.name, idn_raw)
86:                        "%s: IDN validation failed (response=%r), issuing GPIB clear and retrying",
94:                            "%s: clear_bus before IDN retry failed: %s",
103:                    f"{self.name}: LakeShore 218S IDN validation failed. "
105:                    f"Check GPIB address and cabling."
109:        self._use_per_channel_krdg = False
110:        self._use_per_channel_srdg = False
111:        self._krdg0_fail_count = 0
125:        runtime_policies = self._runtime_channel_policies()
126:        if not runtime_policies:
127:            readings = await self._read_krdg_channels()
129:            temperature_readings = await self._read_krdg_channels()
131:                policy.get("reading_mode") == "curve" for policy in runtime_policies.values()
134:            readings = self._merge_runtime_readings(
135:                temperature_readings, raw_readings, runtime_policies
138:        # Periodic RDGST? status check (every 60s)
145:                log.debug("%s: RDGST? periodic check failed: %s", self.name, exc)
157:    async def _read_krdg_channels(self) -> list[Reading]:
161:        if self._use_per_channel_krdg:
162:            return await self._read_krdg_per_channel()
164:        raw_response = await self._transport.query("KRDG?")
165:        log.debug("%s: KRDG? -> %s", self.name, raw_response)
168:            self._krdg0_fail_count += 1
170:                "%s: KRDG? returned %d values (expected 8), fallback #%d",
173:                self._krdg0_fail_count,
175:            if self._krdg0_fail_count >= 3:
176:                self._use_per_channel_krdg = True
178:                    "%s: KRDG? failed %d times, switching to per-channel mode permanently",
180:                    self._krdg0_fail_count,
182:            return await self._read_krdg_per_channel()
183:        self._krdg0_fail_count = 0
186:    async def _read_krdg_per_channel(self) -> list[Reading]:
187:        """Fallback: query each channel individually (KRDG? 1 .. KRDG? 8).
189:        Periodically retries batch KRDG? to recover from transient failures.
193:        if now - self._krdg_last_batch_retry >= self._krdg_batch_retry_interval_s:
194:            self._krdg_last_batch_retry = now
196:                raw = await self._transport.query("KRDG?")
200:                        "%s: KRDG? batch mode recovered — switching back from per-channel",
203:                    self._use_per_channel_krdg = False
204:                    self._krdg0_fail_count = 0
212:                raw = await self._transport.query(f"KRDG? {ch}")
230:                log.error("%s: KRDG? %d failed: %s", self.name, ch, exc)
251:        if self._use_per_channel_srdg:
254:        raw_response = await self._transport.query("SRDG?")
255:        log.debug("%s: SRDG? -> %s", self.name, raw_response)
260:                "%s: SRDG? returned %d values (expected 8), fallback #%d",
266:                self._use_per_channel_srdg = True
268:                    "%s: SRDG? failed %d times, switching to per-channel mode permanently",
277:        """Fallback: query each channel individually (SRDG? 1 .. SRDG? 8).
279:        Periodically retries batch SRDG? to recover from transient failures.
286:                raw = await self._transport.query("SRDG?")
290:                        "%s: SRDG? batch mode recovered — switching back from per-channel",
293:                    self._use_per_channel_srdg = False
302:                raw = await self._transport.query(f"SRDG? {ch}")
319:                log.error("%s: SRDG? %d failed: %s", self.name, ch, exc)
335:        """Query RDGST? for all channels. Returns {channel_num: status_bitmap}.
347:                raw = await self._transport.query(f"RDGST? {ch}")
350:                log.warning("%s: RDGST? %d failed: %s", self.name, ch, exc)
354:    async def read_calibration_pair(
360:        temperatures = await self._read_krdg_channels()
446:            raw_base = _mock_sensor_unit(base_temp)
465:    def _runtime_channel_policies(self) -> dict[int, dict[str, Any]]:
466:        if self._calibration_store is None:
471:            channel_key = self._runtime_channel_key(channel_name)
472:            resolution = self._calibration_store.resolve_runtime_policy(channel_key=channel_key)
481:                self._log_runtime_fallback(channel_key=channel_key, reason=reason)
484:    def _merge_runtime_readings(
504:                    self._with_runtime_metadata(
507:                        raw_source="KRDG",
510:                        runtime_reason=str(policy.get("reason", "krdg_default")),
517:                self._log_runtime_fallback(
521:                    self._with_runtime_metadata(
524:                        raw_source="KRDG",
527:                        runtime_reason="missing_srdg",
534:                calibrated_value = self._calibration_store.evaluate(
538:                self._log_runtime_fallback(
542:                    self._with_runtime_metadata(
545:                        raw_source="KRDG",
548:                        runtime_reason="curve_evaluate_failed",
565:                        "raw_source": "SRDG",
573:    def _with_runtime_metadata(
581:        runtime_reason: str,
597:                "runtime_reason": runtime_reason,
601:    def _runtime_channel_key(self, channel_name: str) -> str:
604:    def _log_runtime_fallback(self, *, channel_key: str, reason: str) -> None:
606:        if cache_key in self._runtime_warning_cache:
608:        self._runtime_warning_cache.add(cache_key)
609:        log.warning("%s: runtime calibration fallback for %s (%s)", self.name, channel_key, reason)

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/drivers/instruments/lakeshore_218s.py | sed -n '1,240p'
nl -ba src/cryodaq/drivers/instruments/lakeshore_218s.py | sed -n '240,520p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	"""LakeShore 218S driver with optional runtime calibration routing."""
     2	
     3	from __future__ import annotations
     4	
     5	import asyncio
     6	import logging
     7	import random
     8	import time as _time
     9	from typing import Any
    10	
    11	from cryodaq.analytics.calibration import CalibrationStore
    12	from cryodaq.drivers.base import ChannelStatus, InstrumentDriver, Reading
    13	from cryodaq.drivers.transport.gpib import GPIBTransport
    14	
    15	log = logging.getLogger(__name__)
    16	
    17	_MOCK_BASE_TEMPS: tuple[float, ...] = (4.2, 4.8, 77.0, 77.5, 4.5, 4.1, 3.9, 300.0)
    18	
    19	
    20	def _mock_sensor_unit(temp_k: float) -> float:
    21	    return round((1600.0 / (temp_k + 15.0)) + 0.08, 6)
    22	
    23	
    24	class LakeShore218S(InstrumentDriver):
    25	    def __init__(
    26	        self,
    27	        name: str,
    28	        resource_str: str,
    29	        *,
    30	        channel_labels: dict[int, str] | None = None,
    31	        mock: bool = False,
    32	        calibration_store: CalibrationStore | None = None,
    33	    ) -> None:
    34	        super().__init__(name, mock=mock)
    35	        self._resource_str = resource_str
    36	        self._channel_labels: dict[int, str] = channel_labels or {}
    37	        self._transport = GPIBTransport(mock=mock)
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
    76	                upper = idn_raw.upper()
    77	                if idn_raw and "LSCI" in upper and "218" in upper:
    78	                    idn_valid = True
    79	                    self._instrument_id = idn_raw
    80	                    log.info("%s: IDN verified: %s", self.name, idn_raw)
    81	                    break
    82	
    83	                if attempt == 0:
    84	                    # Try a Selected Device Clear before the second attempt.
    85	                    log.warning(
    86	                        "%s: IDN validation failed (response=%r), issuing GPIB clear and retrying",
    87	                        self.name,
    88	                        idn_raw,
    89	                    )
    90	                    try:
    91	                        await self._transport.clear_bus()
    92	                    except Exception as clear_exc:
    93	                        log.warning(
    94	                            "%s: clear_bus before IDN retry failed: %s",
    95	                            self.name,
    96	                            clear_exc,
    97	                        )
    98	                    await asyncio.sleep(0.2)
    99	
   100	            if not idn_valid:
   101	                await self._transport.close()
   102	                raise RuntimeError(
   103	                    f"{self.name}: LakeShore 218S IDN validation failed. "
   104	                    f"Expected 'LSCI,MODEL218...', got {idn_raw!r}. "
   105	                    f"Check GPIB address and cabling."
   106	                )
   107	
   108	        self._connected = True
   109	        self._use_per_channel_krdg = False
   110	        self._use_per_channel_srdg = False
   111	        self._krdg0_fail_count = 0
   112	        self._srdg0_fail_count = 0
   113	        log.info("%s: connected", self.name)
   114	
   115	    async def disconnect(self) -> None:
   116	        if not self._connected:
   117	            return
   118	        await self._transport.close()
   119	        self._connected = False
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
   141	            self._last_status_check = now
   142	            try:
   143	                self._last_status_result = await self.read_status()
   144	            except Exception as exc:
   145	                log.debug("%s: RDGST? periodic check failed: %s", self.name, exc)
   146	        # Attach status bits as metadata
   147	        if self._last_status_result:
   148	            for r in readings:
   149	                ch_num = (r.metadata or {}).get("raw_channel")
   150	                if ch_num is not None and ch_num in self._last_status_result:
   151	                    if r.metadata is None:
   152	                        r.metadata = {}
   153	                    r.metadata["sensor_status"] = self._last_status_result[ch_num]
   154	
   155	        return readings
   156	
   157	    async def _read_krdg_channels(self) -> list[Reading]:
   158	        if self.mock:
   159	            return self._mock_readings()
   160	
   161	        if self._use_per_channel_krdg:
   162	            return await self._read_krdg_per_channel()
   163	
   164	        raw_response = await self._transport.query("KRDG?")
   165	        log.debug("%s: KRDG? -> %s", self.name, raw_response)
   166	        readings = self._parse_response(raw_response, unit="K", reading_kind="temperature")
   167	        if len(readings) < 8:
   168	            self._krdg0_fail_count += 1
   169	            log.warning(
   170	                "%s: KRDG? returned %d values (expected 8), fallback #%d",
   171	                self.name,
   172	                len(readings),
   173	                self._krdg0_fail_count,
   174	            )
   175	            if self._krdg0_fail_count >= 3:
   176	                self._use_per_channel_krdg = True
   177	                log.warning(
   178	                    "%s: KRDG? failed %d times, switching to per-channel mode permanently",
   179	                    self.name,
   180	                    self._krdg0_fail_count,
   181	                )
   182	            return await self._read_krdg_per_channel()
   183	        self._krdg0_fail_count = 0
   184	        return readings
   185	
   186	    async def _read_krdg_per_channel(self) -> list[Reading]:
   187	        """Fallback: query each channel individually (KRDG? 1 .. KRDG? 8).
   188	
   189	        Periodically retries batch KRDG? to recover from transient failures.
   190	        """
   191	
   192	        now = _time.monotonic()
   193	        if now - self._krdg_last_batch_retry >= self._krdg_batch_retry_interval_s:
   194	            self._krdg_last_batch_retry = now
   195	            try:
   196	                raw = await self._transport.query("KRDG?")
   197	                readings = self._parse_response(raw, unit="K", reading_kind="temperature")
   198	                if len(readings) >= 8:
   199	                    log.info(
   200	                        "%s: KRDG? batch mode recovered — switching back from per-channel",
   201	                        self.name,
   202	                    )
   203	                    self._use_per_channel_krdg = False
   204	                    self._krdg0_fail_count = 0
   205	                    return readings
   206	            except Exception:
   207	                pass  # Stay in per-channel mode
   208	
   209	        readings: list[Reading] = []
   210	        for ch in range(1, 9):
   211	            try:
   212	                raw = await self._transport.query(f"KRDG? {ch}")
   213	                parsed = self._parse_response(raw, unit="K", reading_kind="temperature")
   214	                if parsed:
   215	                    # Fix channel index — _parse_response starts at 1 for first token
   216	                    reading = parsed[0]
   217	                    channel_name = self._channel_labels.get(ch, f"CH{ch}")
   218	                    readings.append(
   219	                        Reading.now(
   220	                            channel=channel_name,
   221	                            value=reading.value,
   222	                            unit=reading.unit,
   223	                            instrument_id=self.name,
   224	                            status=reading.status,
   225	                            raw=reading.raw,
   226	                            metadata={"raw_channel": ch, "reading_kind": "temperature"},
   227	                        )
   228	                    )
   229	            except Exception as exc:
   230	                log.error("%s: KRDG? %d failed: %s", self.name, ch, exc)
   231	                channel_name = self._channel_labels.get(ch, f"CH{ch}")
   232	                readings.append(
   233	                    Reading.now(
   234	                        channel=channel_name,
   235	                        value=float("nan"),
   236	                        unit="K",
   237	                        instrument_id=self.name,
   238	                        status=ChannelStatus.SENSOR_ERROR,
   239	                        raw=None,
   240	                        metadata={"raw_channel": ch, "reading_kind": "temperature"},
   240	                        metadata={"raw_channel": ch, "reading_kind": "temperature"},
   241	                    )
   242	                )
   243	        return readings
   244	
   245	    async def read_srdg_channels(self) -> list[Reading]:
   246	        if not self._connected:
   247	            raise RuntimeError(f"{self.name}: instrument is not connected")
   248	        if self.mock:
   249	            return self._mock_sensor_readings()
   250	
   251	        if self._use_per_channel_srdg:
   252	            return await self._read_srdg_per_channel()
   253	
   254	        raw_response = await self._transport.query("SRDG?")
   255	        log.debug("%s: SRDG? -> %s", self.name, raw_response)
   256	        readings = self._parse_response(raw_response, unit="sensor_unit", reading_kind="raw_sensor")
   257	        if len(readings) < 8:
   258	            self._srdg0_fail_count += 1
   259	            log.warning(
   260	                "%s: SRDG? returned %d values (expected 8), fallback #%d",
   261	                self.name,
   262	                len(readings),
   263	                self._srdg0_fail_count,
   264	            )
   265	            if self._srdg0_fail_count >= 3:
   266	                self._use_per_channel_srdg = True
   267	                log.warning(
   268	                    "%s: SRDG? failed %d times, switching to per-channel mode permanently",
   269	                    self.name,
   270	                    self._srdg0_fail_count,
   271	                )
   272	            return await self._read_srdg_per_channel()
   273	        self._srdg0_fail_count = 0
   274	        return readings
   275	
   276	    async def _read_srdg_per_channel(self) -> list[Reading]:
   277	        """Fallback: query each channel individually (SRDG? 1 .. SRDG? 8).
   278	
   279	        Periodically retries batch SRDG? to recover from transient failures.
   280	        """
   281	
   282	        now = _time.monotonic()
   283	        if now - self._srdg_last_batch_retry >= self._srdg_batch_retry_interval_s:
   284	            self._srdg_last_batch_retry = now
   285	            try:
   286	                raw = await self._transport.query("SRDG?")
   287	                readings = self._parse_response(raw, unit="sensor_unit", reading_kind="raw_sensor")
   288	                if len(readings) >= 8:
   289	                    log.info(
   290	                        "%s: SRDG? batch mode recovered — switching back from per-channel",
   291	                        self.name,
   292	                    )
   293	                    self._use_per_channel_srdg = False
   294	                    self._srdg0_fail_count = 0
   295	                    return readings
   296	            except Exception:
   297	                pass
   298	
   299	        readings: list[Reading] = []
   300	        for ch in range(1, 9):
   301	            try:
   302	                raw = await self._transport.query(f"SRDG? {ch}")
   303	                parsed = self._parse_response(raw, unit="sensor_unit", reading_kind="raw_sensor")
   304	                if parsed:
   305	                    reading = parsed[0]
   306	                    channel_name = self._channel_labels.get(ch, f"CH{ch}")
   307	                    readings.append(
   308	                        Reading.now(
   309	                            channel=channel_name,
   310	                            value=reading.value,
   311	                            unit=reading.unit,
   312	                            instrument_id=self.name,
   313	                            status=reading.status,
   314	                            raw=reading.raw,
   315	                            metadata={"raw_channel": ch, "reading_kind": "raw_sensor"},
   316	                        )
   317	                    )
   318	            except Exception as exc:
   319	                log.error("%s: SRDG? %d failed: %s", self.name, ch, exc)
   320	                channel_name = self._channel_labels.get(ch, f"CH{ch}")
   321	                readings.append(
   322	                    Reading.now(
   323	                        channel=channel_name,
   324	                        value=float("nan"),
   325	                        unit="sensor_unit",
   326	                        instrument_id=self.name,
   327	                        status=ChannelStatus.SENSOR_ERROR,
   328	                        raw=None,
   329	                        metadata={"raw_channel": ch, "reading_kind": "raw_sensor"},
   330	                    )
   331	                )
   332	        return readings
   333	
   334	    async def read_status(self) -> dict[int, int]:
   335	        """Query RDGST? for all channels. Returns {channel_num: status_bitmap}.
   336	
   337	        Bitmap bits: 0=invalid, 4=T_under, 5=T_over, 6=sensor_overrange, 7=sensor_zero.
   338	        Call periodically (every 30-60s), not every poll cycle.
   339	        """
   340	        if self.mock:
   341	            return {ch: 0 for ch in range(1, 9)}
   342	        if not self._connected:
   343	            raise RuntimeError(f"{self.name}: instrument is not connected")
   344	        result: dict[int, int] = {}
   345	        for ch in range(1, 9):
   346	            try:
   347	                raw = await self._transport.query(f"RDGST? {ch}")
   348	                result[ch] = int(raw.strip())
   349	            except Exception as exc:
   350	                log.warning("%s: RDGST? %d failed: %s", self.name, ch, exc)
   351	                result[ch] = -1
   352	        return result
   353	
   354	    async def read_calibration_pair(
   355	        self,
   356	        *,
   357	        reference_channel: int | str,
   358	        sensor_channel: int | str,
   359	    ) -> dict[str, Any]:
   360	        temperatures = await self._read_krdg_channels()
   361	        raw_readings = await self.read_srdg_channels()
   362	        reference_reading = self._resolve_channel_reading(temperatures, reference_channel)
   363	        sensor_reading = self._resolve_channel_reading(raw_readings, sensor_channel)
   364	        return {
   365	            "reference": reference_reading,
   366	            "sensor": sensor_reading,
   367	        }
   368	
   369	    def _parse_response(self, response: str, *, unit: str, reading_kind: str) -> list[Reading]:
   370	        tokens = [token.strip() for token in response.split(",")]
   371	        readings: list[Reading] = []
   372	        for index, token in enumerate(tokens[:8], start=1):
   373	            channel_name = self._channel_labels.get(index, f"CH{index}")
   374	            metadata = {
   375	                "raw_channel": index,
   376	                "reading_kind": reading_kind,
   377	            }
   378	            token_upper = token.upper().lstrip("+")
   379	            if token_upper in {"OVL", "+OVL"}:
   380	                readings.append(
   381	                    Reading.now(
   382	                        channel=channel_name,
   383	                        value=float("inf"),
   384	                        unit=unit,
   385	                        instrument_id=self.name,
   386	                        status=ChannelStatus.OVERRANGE,
   387	                        raw=None,
   388	                        metadata=metadata,
   389	                    )
   390	                )
   391	                continue
   392	            try:
   393	                value = float(token)
   394	            except ValueError:
   395	                readings.append(
   396	                    Reading.now(
   397	                        channel=channel_name,
   398	                        value=float("nan"),
   399	                        unit=unit,
   400	                        instrument_id=self.name,
   401	                        status=ChannelStatus.SENSOR_ERROR,
   402	                        raw=None,
   403	                        metadata=metadata,
   404	                    )
   405	                )
   406	                continue
   407	            readings.append(
   408	                Reading.now(
   409	                    channel=channel_name,
   410	                    value=value,
   411	                    unit=unit,
   412	                    instrument_id=self.name,
   413	                    status=ChannelStatus.OK,
   414	                    raw=value,
   415	                    metadata=metadata,
   416	                )
   417	            )
   418	        return readings
   419	
   420	    def _mock_readings(self) -> list[Reading]:
   421	        readings: list[Reading] = []
   422	        for index, base_temp in enumerate(_MOCK_BASE_TEMPS, start=1):
   423	            channel_name = self._channel_labels.get(index, f"CH{index}")
   424	            noise = base_temp * random.uniform(-0.005, 0.005)
   425	            value = round(base_temp + noise, 4)
   426	            readings.append(
   427	                Reading.now(
   428	                    channel=channel_name,
   429	                    value=value,
   430	                    unit="K",
   431	                    instrument_id=self.name,
   432	                    status=ChannelStatus.OK,
   433	                    raw=value,
   434	                    metadata={
   435	                        "raw_channel": index,
   436	                        "reading_kind": "temperature",
   437	                    },
   438	                )
   439	            )
   440	        return readings
   441	
   442	    def _mock_sensor_readings(self) -> list[Reading]:
   443	        readings: list[Reading] = []
   444	        for index, base_temp in enumerate(_MOCK_BASE_TEMPS, start=1):
   445	            channel_name = self._channel_labels.get(index, f"CH{index}")
   446	            raw_base = _mock_sensor_unit(base_temp)
   447	            noise = raw_base * random.uniform(-0.002, 0.002)
   448	            value = round(raw_base + noise, 6)
   449	            readings.append(
   450	                Reading.now(
   451	                    channel=channel_name,
   452	                    value=value,
   453	                    unit="sensor_unit",
   454	                    instrument_id=self.name,
   455	                    status=ChannelStatus.OK,
   456	                    raw=value,
   457	                    metadata={
   458	                        "raw_channel": index,
   459	                        "reading_kind": "raw_sensor",
   460	                    },
   461	                )
   462	            )
   463	        return readings
   464	
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

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/drivers/instruments/lakeshore_218s.py | sed -n '515,620p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
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
   616	        if isinstance(channel_spec, int):
   617	            for reading in readings:
   618	                if reading.metadata.get("raw_channel") == channel_spec:
   619	                    return reading
   620	            raise KeyError(f"LakeShore channel {channel_spec} not found.")

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/drivers/instruments/keithley_2604b.py | sed -n '1,120p'
nl -ba src/cryodaq/drivers/instruments/keithley_2604b.py | sed -n '120,330p'
nl -ba src/cryodaq/drivers/instruments/keithley_2604b.py | sed -n '330,520p'" in /Users/vladimir/Projects/cryodaq
exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/core/smu_channel.py | sed -n '1,220p'
rg -n \"COMPLIANCE|MAX_DELTA|I_MIN|mock|p_target|combined|both|smua|smub\" src/cryodaq/drivers/instruments/keithley_2604b.py" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
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
23:_I_MIN_A = 1e-7
28:MAX_DELTA_V_PER_STEP = 0.5  # V — do not increase without thermal analysis
31:_COMPLIANCE_NOTIFY_THRESHOLD = 10
50:    p_target: float = 0.0
62:        mock: bool = False,
64:        super().__init__(name, mock=mock)
66:        self._transport = USBTMCTransport(mock=mock)
69:            "smua": ChannelRuntime(channel="smua"),
70:            "smub": ChannelRuntime(channel="smub"),
73:        self._last_v: dict[SmuChannel, float] = {"smua": 0.0, "smub": 0.0}
75:        self._compliance_count: dict[SmuChannel, int] = {"smua": 0, "smub": 0}
76:        self._mock_temp = _MOCK_T0
97:            if not self.mock:
99:                    await self._transport.write("smua.source.levelv = 0")
100:                    await self._transport.write("smub.source.levelv = 0")
101:                    await self._transport.write("smua.source.output = smua.OUTPUT_OFF")
102:                    await self._transport.write("smub.source.output = smub.OUTPUT_OFF")
129:        if self.mock:
130:            return self._mock_readings()
184:                    if abs(current) > _I_MIN_A:
187:                            target_v = math.sqrt(runtime.p_target * resistance)
193:                            if abs(delta_v) > MAX_DELTA_V_PER_STEP:
195:                                    MAX_DELTA_V_PER_STEP if delta_v > 0 else -MAX_DELTA_V_PER_STEP
226:        p_target: float,
235:        if p_target <= 0 or v_compliance <= 0 or i_compliance <= 0:
240:        runtime.p_target = p_target
244:        if self.mock:
267:        if self.mock:
271:            runtime.p_target = 0.0
283:        runtime.p_target = 0.0
288:        if self.mock:
289:            return self._mock_buffer(start_idx, count)
293:            f"printbuffer({start_idx}, {end_idx}, smua.nvbuffer1.timestamps, smua.nvbuffer1.sourcevalues, smua.nvbuffer1)",  # noqa: E501
303:            runtime.p_target = 0.0
307:        if self.mock or not self._connected:
352:        return self._compliance_count.get(channel, 0) >= _COMPLIANCE_NOTIFY_THRESHOLD
356:        if not self._connected or self.mock:
371:        if self.mock or not self._connected:
476:    def _mock_r_of_t(self) -> float:
477:        return max(_MOCK_R0 * (1.0 + _MOCK_ALPHA * (self._mock_temp - _MOCK_T0)), 1.0)
479:    def _mock_readings(self) -> list[Reading]:
480:        if self._mock_temp > 4.0:
481:            self._mock_temp = max(4.0, self._mock_temp - _MOCK_COOLING_RATE)
484:        base_r = self._mock_r_of_t()
487:            resistance = base_r if smu_channel == "smua" else base_r * _MOCK_SMUB_FACTOR
488:            if runtime.active and runtime.p_target > 0.0:
489:                voltage = math.sqrt(runtime.p_target * resistance)
504:    def _mock_buffer(self, start_idx: int, count: int) -> list[dict[str, float]]:
506:        resistance = self._mock_r_of_t()
507:        runtime = self._channels["smua"]
509:            math.sqrt(runtime.p_target * resistance)
510:            if runtime.active and runtime.p_target > 0.0

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
   120	            return
   121	        await self.emergency_off()
   122	        await self._transport.close()
   123	        self._connected = False
   124	
   125	    async def read_channels(self) -> list[Reading]:
   126	        if not self._connected:
   127	            raise RuntimeError(f"{self.name}: instrument not connected")
   128	
   129	        if self.mock:
   130	            return self._mock_readings()
   131	
   132	        readings: list[Reading] = []
   133	        for smu_channel in SMU_CHANNELS:
   134	            runtime = self._channels[smu_channel]
   135	            try:
   136	                if not runtime.active:
   137	                    # Check output state — source may be OFF or left ON from
   138	                    # a previous session.  measure.iv() errors when output is OFF.
   139	                    output_raw = await self._transport.query(
   140	                        f"print({smu_channel}.source.output)", timeout_ms=3000
   141	                    )
   142	                    try:
   143	                        output_on = float(output_raw.strip()) > 0.5
   144	                    except ValueError:
   145	                        output_on = False
   146	
   147	                    if not output_on:
   148	                        readings.extend(
   149	                            self._build_channel_readings(
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
   186	                        if resistance > 0:
   187	                            target_v = math.sqrt(runtime.p_target * resistance)
   188	                            target_v = max(0.0, min(target_v, runtime.v_comp))
   189	
   190	                            # Slew rate limit
   191	                            current_v = self._last_v[smu_channel]
   192	                            delta_v = target_v - current_v
   193	                            if abs(delta_v) > MAX_DELTA_V_PER_STEP:
   194	                                delta_v = (
   195	                                    MAX_DELTA_V_PER_STEP if delta_v > 0 else -MAX_DELTA_V_PER_STEP
   196	                                )
   197	                                target_v = current_v + delta_v
   198	                                log.debug(
   199	                                    "Slew rate limited: delta=%.3f V, target=%.3f V",
   200	                                    delta_v,
   201	                                    target_v,
   202	                                )
   203	
   204	                            await self._transport.write(f"{smu_channel}.source.levelv = {target_v}")
   205	                            self._last_v[smu_channel] = target_v
   206	
   207	                readings.extend(
   208	                    self._build_channel_readings(
   209	                        smu_channel, voltage, current, extra_meta=extra_meta
   210	                    )
   211	                )
   212	            except OSError as exc:
   213	                # Transport-level error (USB disconnect, pipe broken) —
   214	                # mark disconnected so scheduler triggers reconnect.
   215	                log.error("%s: transport error on %s: %s", self.name, smu_channel, exc)
   216	                self._connected = False
   217	                raise
   218	            except Exception as exc:
   219	                log.error("%s: read failure on %s: %s", self.name, smu_channel, exc)
   220	                readings.extend(self._error_readings_for_channel(smu_channel))
   221	        return readings
   222	
   223	    async def start_source(
   224	        self,
   225	        channel: str,
   226	        p_target: float,
   227	        v_compliance: float,
   228	        i_compliance: float,
   229	    ) -> None:
   230	        smu_channel = normalize_smu_channel(channel)
   231	        runtime = self._channels[smu_channel]
   232	
   233	        if not self._connected:
   234	            raise RuntimeError(f"{self.name}: instrument not connected")
   235	        if p_target <= 0 or v_compliance <= 0 or i_compliance <= 0:
   236	            raise ValueError("P/V/I must be > 0")
   237	        if runtime.active:
   238	            raise RuntimeError(f"Channel {smu_channel} already active")
   239	
   240	        runtime.p_target = p_target
   241	        runtime.v_comp = v_compliance
   242	        runtime.i_comp = i_compliance
   243	
   244	        if self.mock:
   245	            runtime.active = True
   246	            return
   247	
   248	        # Configure source directly via VISA — no TSP script.
   249	        await self._transport.write(f"{smu_channel}.reset()")
   250	        await self._transport.write(f"{smu_channel}.source.func = {smu_channel}.OUTPUT_DCVOLTS")
   251	        await self._transport.write(f"{smu_channel}.source.autorangev = {smu_channel}.AUTORANGE_ON")
   252	        await self._transport.write(
   253	            f"{smu_channel}.measure.autorangei = {smu_channel}.AUTORANGE_ON"
   254	        )
   255	        await self._transport.write(f"{smu_channel}.source.limitv = {v_compliance}")
   256	        await self._transport.write(f"{smu_channel}.source.limiti = {i_compliance}")
   257	        await self._transport.write(f"{smu_channel}.source.levelv = 0")
   258	        await self._transport.write(f"{smu_channel}.source.output = {smu_channel}.OUTPUT_ON")
   259	        self._last_v[smu_channel] = 0.0
   260	        self._compliance_count[smu_channel] = 0
   261	        runtime.active = True
   262	
   263	    async def stop_source(self, channel: str) -> None:
   264	        smu_channel = normalize_smu_channel(channel)
   265	        runtime = self._channels[smu_channel]
   266	
   267	        if self.mock:
   268	            self._last_v[smu_channel] = 0.0
   269	            self._compliance_count[smu_channel] = 0
   270	            runtime.active = False
   271	            runtime.p_target = 0.0
   272	            return
   273	
   274	        if not self._connected:
   275	            return
   276	
   277	        await self._transport.write(f"{smu_channel}.source.levelv = 0")
   278	        await self._transport.write(f"{smu_channel}.source.output = {smu_channel}.OUTPUT_OFF")
   279	        await self._verify_output_off(smu_channel)
   280	        self._last_v[smu_channel] = 0.0
   281	        self._compliance_count[smu_channel] = 0
   282	        runtime.active = False
   283	        runtime.p_target = 0.0
   284	
   285	    async def read_buffer(self, start_idx: int = 1, count: int = 100) -> list[dict[str, float]]:
   286	        if not self._connected:
   287	            raise RuntimeError(f"{self.name}: instrument not connected")
   288	        if self.mock:
   289	            return self._mock_buffer(start_idx, count)
   290	
   291	        end_idx = start_idx + count - 1
   292	        raw = await self._transport.query(
   293	            f"printbuffer({start_idx}, {end_idx}, smua.nvbuffer1.timestamps, smua.nvbuffer1.sourcevalues, smua.nvbuffer1)",  # noqa: E501
   294	            timeout_ms=10_000,
   295	        )
   296	        return self._parse_buffer_response(raw)
   297	
   298	    async def emergency_off(self, channel: str | None = None) -> None:
   299	        channels = [normalize_smu_channel(channel)] if channel is not None else list(SMU_CHANNELS)
   300	        for smu_channel in channels:
   301	            runtime = self._channels[smu_channel]
   302	            runtime.active = False
   303	            runtime.p_target = 0.0
   304	            self._last_v[smu_channel] = 0.0
   305	            self._compliance_count[smu_channel] = 0
   306	
   307	        if self.mock or not self._connected:
   308	            return
   309	
   310	        for smu_channel in channels:
   311	            try:
   312	                await self._transport.write(f"{smu_channel}.source.levelv = 0")
   313	                await self._transport.write(
   314	                    f"{smu_channel}.source.output = {smu_channel}.OUTPUT_OFF"
   315	                )
   316	            except Exception as exc:
   317	                log.critical("%s: emergency_off failed on %s: %s", self.name, smu_channel, exc)
   318	            # SAFETY (Phase 2a Codex G.1): readback-verify each channel.
   319	            # emergency_off is the most critical path — silent failure here
   320	            # is unacceptable. _verify_output_off logs CRITICAL on mismatch.
   321	            # Wrap in try because the caller is already in an emergency path
   322	            # and a raise here would just propagate noise; the CRITICAL log
   323	            # is the signalling mechanism (alarm pipeline filters on level).
   324	            try:
   325	                await self._verify_output_off(smu_channel)
   326	            except Exception as exc:
   327	                log.critical(
   328	                    "%s: emergency_off verify FAILED on %s: %s — instrument may still be sourcing!",
   329	                    self.name,
   330	                    smu_channel,
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
   366	        except Exception as exc:
   367	            log.error("%s: diagnostics error: %s", self.name, exc)
   368	        return result
   369	
   370	    async def _verify_output_off(self, channel: str) -> None:
   371	        if self.mock or not self._connected:
   372	            return
   373	        smu_channel = normalize_smu_channel(channel)
   374	        response = await self._transport.query(
   375	            f"print({smu_channel}.source.output)", timeout_ms=3000
   376	        )
   377	        try:
   378	            if float(response.strip()) > 0.5:
   379	                log.critical(
   380	                    "%s: %s still reports output=%s", self.name, smu_channel, response.strip()
   381	                )
   382	        except ValueError:
   383	            log.critical(
   384	                "%s: %s unexpected output response: %r", self.name, smu_channel, response.strip()
   385	            )
   386	
   387	    def _parse_iv_response(self, raw: str, channel: SmuChannel) -> tuple[float, float]:
   388	        parts = raw.strip().split("\t")
   389	        if len(parts) != 2:
   390	            raise ValueError(f"{channel}: expected 2 values, got {raw!r}")
   391	        return float(parts[0]), float(parts[1])
   392	
   393	    def _build_channel_readings(
   394	        self,
   395	        channel: SmuChannel,
   396	        voltage: float,
   397	        current: float,
   398	        *,
   399	        resistance_override: float | None = None,
   400	        extra_meta: dict[str, Any] | None = None,
   401	    ) -> list[Reading]:
   402	        resistance = (
   403	            resistance_override
   404	            if resistance_override is not None
   405	            else (voltage / current if current != 0.0 else float("nan"))
   406	        )
   407	        power = voltage * current
   408	        metadata: dict[str, Any] = {"resource_str": self._resource_str, "smu_channel": channel}
   409	        if extra_meta:
   410	            metadata.update(extra_meta)
   411	        return [
   412	            Reading.now(
   413	                channel=f"{self.name}/{channel}/voltage",
   414	                value=voltage,
   415	                unit="V",
   416	                instrument_id=self.name,
   417	                status=ChannelStatus.OK,
   418	                raw=voltage,
   419	                metadata=metadata,
   420	            ),
   421	            Reading.now(
   422	                channel=f"{self.name}/{channel}/current",
   423	                value=current,
   424	                unit="A",
   425	                instrument_id=self.name,
   426	                status=ChannelStatus.OK,
   427	                raw=current,
   428	                metadata=metadata,
   429	            ),
   430	            Reading.now(
   431	                channel=f"{self.name}/{channel}/resistance",
   432	                value=resistance,
   433	                unit="Ohm",
   434	                instrument_id=self.name,
   435	                status=ChannelStatus.OK
   436	                if math.isfinite(resistance)
   437	                else ChannelStatus.SENSOR_ERROR,
   438	                raw=resistance if math.isfinite(resistance) else None,
   439	                metadata=metadata,
   440	            ),
   441	            Reading.now(
   442	                channel=f"{self.name}/{channel}/power",
   443	                value=power,
   444	                unit="W",
   445	                instrument_id=self.name,
   446	                status=ChannelStatus.OK,
   447	                raw=power,
   448	                metadata=metadata,
   449	            ),
   450	        ]
   451	
   452	    def _parse_buffer_response(self, raw: str) -> list[dict[str, float]]:
   453	        tokens = [token.strip() for token in raw.replace("\t", ",").split(",")]
   454	        results: list[dict[str, float]] = []
   455	        n = len(tokens) // 3
   456	        for idx in range(n):
   457	            try:
   458	                ts = float(tokens[idx])
   459	                voltage = float(tokens[n + idx])
   460	                current = float(tokens[2 * n + idx])
   461	            except (ValueError, IndexError):
   462	                continue
   463	            resistance = voltage / current if current != 0.0 else float("nan")
   464	            power = voltage * current
   465	            results.append(
   466	                {
   467	                    "timestamp": ts,
   468	                    "voltage": voltage,
   469	                    "current": current,
   470	                    "resistance": resistance,
   471	                    "power": power,
   472	                }
   473	            )
   474	        return results
   475	
   476	    def _mock_r_of_t(self) -> float:
   477	        return max(_MOCK_R0 * (1.0 + _MOCK_ALPHA * (self._mock_temp - _MOCK_T0)), 1.0)
   478	
   479	    def _mock_readings(self) -> list[Reading]:
   480	        if self._mock_temp > 4.0:
   481	            self._mock_temp = max(4.0, self._mock_temp - _MOCK_COOLING_RATE)
   482	
   483	        readings: list[Reading] = []
   484	        base_r = self._mock_r_of_t()
   485	        for smu_channel in SMU_CHANNELS:
   486	            runtime = self._channels[smu_channel]
   487	            resistance = base_r if smu_channel == "smua" else base_r * _MOCK_SMUB_FACTOR
   488	            if runtime.active and runtime.p_target > 0.0:
   489	                voltage = math.sqrt(runtime.p_target * resistance)
   490	                current = voltage / resistance
   491	            else:
   492	                voltage = 0.0
   493	                current = 0.0
   494	            readings.extend(
   495	                self._build_channel_readings(
   496	                    smu_channel,
   497	                    round(voltage, 6),
   498	                    round(current, 7),
   499	                    resistance_override=round(resistance, 4),
   500	                )
   501	            )
   502	        return readings
   503	
   504	    def _mock_buffer(self, start_idx: int, count: int) -> list[dict[str, float]]:
   505	        results: list[dict[str, float]] = []
   506	        resistance = self._mock_r_of_t()
   507	        runtime = self._channels["smua"]
   508	        voltage = (
   509	            math.sqrt(runtime.p_target * resistance)
   510	            if runtime.active and runtime.p_target > 0.0
   511	            else 0.0
   512	        )
   513	        current = voltage / resistance if resistance > 0.0 else 0.0
   514	        for idx in range(count):
   515	            results.append(
   516	                {
   517	                    "timestamp": float(start_idx + idx) * 0.5,
   518	                    "voltage": round(voltage, 6),
   519	                    "current": round(current, 7),
   520	                    "resistance": round(resistance, 4),

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/drivers/instruments/thyracont_vsp63d.py | sed -n '280,440p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
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
   331	        ----------
   332	        response:
   333	            Сырая строка ответа от прибора.
   334	
   335	        Returns
   336	        -------
   337	        Reading
   338	            Показание давления.
   339	        """
   340	        channel = f"{self.name}/pressure"
   341	        response_stripped = response.strip()
   342	
   343	        # Validate checksum if enabled and response has expected structure
   344	        if self._validate_checksum and len(response_stripped) >= 2:
   345	            if not self._verify_v1_checksum(response_stripped):
   346	                log.warning(
   347	                    "%s: V1 checksum mismatch in '%s' — possible RS-232 corruption",
   348	                    self.name,
   349	                    response_stripped,
   350	                )
   351	                return Reading.now(
   352	                    channel=channel,
   353	                    value=float("nan"),
   354	                    unit="mbar",
   355	                    instrument_id=self.name,
   356	                    status=ChannelStatus.SENSOR_ERROR,
   357	                    raw=None,
   358	                    metadata={"raw_response": response_stripped, "error": "checksum_mismatch"},
   359	                )
   360	
   361	        try:
   362	            # Ожидаемый формат: <addr><cmd><6digits><checksum>
   363	            # Например: "001M260017N" → addr="001", cmd="M", value="260017", checksum="N"
   364	            if not response_stripped.startswith(self._address):
   365	                raise ValueError(f"Неверный адрес в ответе: '{response_stripped}'")
   366	
   367	            # Пропустить адрес (3 символа) + команду (1 символ)
   368	            payload = response_stripped[len(self._address) + 1 :]
   369	
   370	            if len(payload) < 6:
   371	                raise ValueError(f"Слишком короткий payload: '{payload}'")
   372	
   373	            # Первые 6 символов: 4 мантисса + 2 экспонента
   374	            value_str = payload[:6]
   375	            mantissa = int(value_str[:4])
   376	            exponent = int(value_str[4:6])
   377	            pressure_mbar = (mantissa / 1000.0) * (10.0 ** (exponent - 20))
   378	
   379	        except (ValueError, IndexError) as exc:
   380	            log.error(
   381	                "%s: не удалось разобрать V1 ответ '%s' — %s",
   382	                self.name,
   383	                response_stripped,
   384	                exc,
   385	            )
   386	            return Reading.now(
   387	                channel=channel,
   388	                value=float("nan"),
   389	                unit="mbar",
   390	                instrument_id=self.name,
   391	                status=ChannelStatus.SENSOR_ERROR,
   392	                raw=None,
   393	                metadata={"raw_response": response_stripped},
   394	            )
   395	
   396	        return Reading.now(
   397	            channel=channel,
   398	            value=pressure_mbar,
   399	            unit="mbar",
   400	            instrument_id=self.name,
   401	            status=ChannelStatus.OK,
   402	            raw=pressure_mbar,
   403	            metadata={"raw_response": response_stripped, "protocol": "v1"},
   404	        )
   405	
   406	    # ------------------------------------------------------------------
   407	    # Mock-режим
   408	    # ------------------------------------------------------------------
   409	
   410	    def _mock_readings(self) -> list[Reading]:
   411	        """Сгенерировать реалистичное имитированное давление (~1.5e-6 мбар)."""
   412	        noise = random.uniform(0.8, 1.2)
   413	        drift = math.sin(time.monotonic() * 0.001) * _MOCK_BASE_PRESSURE_MBAR * 0.05
   414	        value = _MOCK_BASE_PRESSURE_MBAR * noise + drift
   415	
   416	        return [
   417	            Reading.now(
   418	                channel=f"{self.name}/pressure",
   419	                value=value,
   420	                unit="mbar",
   421	                instrument_id=self.name,
   422	                status=ChannelStatus.OK,
   423	                raw=value,
   424	            )
   425	        ]

exec
/opt/homebrew/bin/bash -lc 'rg -n "compliance_persistent|compliance|_COMPLIANCE_NOTIFY_THRESHOLD|notify" src/cryodaq/core src/cryodaq/engine.py src/cryodaq/drivers/instruments/keithley_2604b.py CLAUDE.md PROJECT_STATUS.md' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
src/cryodaq/drivers/instruments/keithley_2604b.py:26:# Prevents target_v from jumping from 0 to V_compliance in one step when
src/cryodaq/drivers/instruments/keithley_2604b.py:30:# Number of consecutive compliance cycles before notifying SafetyManager.
src/cryodaq/drivers/instruments/keithley_2604b.py:31:_COMPLIANCE_NOTIFY_THRESHOLD = 10
src/cryodaq/drivers/instruments/keithley_2604b.py:74:        # Compliance tracking: consecutive cycles where SMU reports compliance.
src/cryodaq/drivers/instruments/keithley_2604b.py:75:        self._compliance_count: dict[SmuChannel, int] = {"smua": 0, "smub": 0}
src/cryodaq/drivers/instruments/keithley_2604b.py:166:                comp_raw = await self._transport.query(f"print({smu_channel}.source.compliance)")
src/cryodaq/drivers/instruments/keithley_2604b.py:167:                in_compliance = comp_raw.strip().lower() == "true"
src/cryodaq/drivers/instruments/keithley_2604b.py:170:                if in_compliance:
src/cryodaq/drivers/instruments/keithley_2604b.py:171:                    self._compliance_count[smu_channel] += 1
src/cryodaq/drivers/instruments/keithley_2604b.py:173:                        "%s: %s in compliance — P=const regulation ineffective (consecutive=%d)",
src/cryodaq/drivers/instruments/keithley_2604b.py:176:                        self._compliance_count[smu_channel],
src/cryodaq/drivers/instruments/keithley_2604b.py:178:                    extra_meta["compliance"] = True
src/cryodaq/drivers/instruments/keithley_2604b.py:181:                    self._compliance_count[smu_channel] = 0
src/cryodaq/drivers/instruments/keithley_2604b.py:227:        v_compliance: float,
src/cryodaq/drivers/instruments/keithley_2604b.py:228:        i_compliance: float,
src/cryodaq/drivers/instruments/keithley_2604b.py:235:        if p_target <= 0 or v_compliance <= 0 or i_compliance <= 0:
src/cryodaq/drivers/instruments/keithley_2604b.py:241:        runtime.v_comp = v_compliance
src/cryodaq/drivers/instruments/keithley_2604b.py:242:        runtime.i_comp = i_compliance
src/cryodaq/drivers/instruments/keithley_2604b.py:255:        await self._transport.write(f"{smu_channel}.source.limitv = {v_compliance}")
src/cryodaq/drivers/instruments/keithley_2604b.py:256:        await self._transport.write(f"{smu_channel}.source.limiti = {i_compliance}")
src/cryodaq/drivers/instruments/keithley_2604b.py:260:        self._compliance_count[smu_channel] = 0
src/cryodaq/drivers/instruments/keithley_2604b.py:269:            self._compliance_count[smu_channel] = 0
src/cryodaq/drivers/instruments/keithley_2604b.py:281:        self._compliance_count[smu_channel] = 0
src/cryodaq/drivers/instruments/keithley_2604b.py:305:            self._compliance_count[smu_channel] = 0
src/cryodaq/drivers/instruments/keithley_2604b.py:350:    def compliance_persistent(self, channel: SmuChannel) -> bool:
src/cryodaq/drivers/instruments/keithley_2604b.py:351:        """True if compliance has persisted for >= threshold consecutive cycles."""
src/cryodaq/drivers/instruments/keithley_2604b.py:352:        return self._compliance_count.get(channel, 0) >= _COMPLIANCE_NOTIFY_THRESHOLD
src/cryodaq/engine.py:1151:                        # GUI polls via alarm_v2_status command; optionally notify via Telegram
src/cryodaq/engine.py:1152:                        if "telegram" in alarm_cfg.notify and telegram_bot is not None:
src/cryodaq/core/safety_manager.py:470:        """Live-update V/I compliance limits. Validates against config limits."""
src/cryodaq/core/channel_manager.py:125:        self._notify()
src/cryodaq/core/channel_manager.py:258:    def _notify(self) -> None:
src/cryodaq/core/alarm_v2.py:447:                return None  # Уже активен, не re-notify
src/cryodaq/core/alarm_config.py:66:    notify:
src/cryodaq/core/alarm_config.py:73:    notify: list[str] = field(default_factory=list)
src/cryodaq/core/alarm_config.py:179:    notify: list[str] = cfg.pop("notify", []) or []
src/cryodaq/core/alarm_config.py:196:        notify=notify if isinstance(notify, list) else [notify],
src/cryodaq/core/alarm.py:186:        async def telegram_notify(event: AlarmEvent) -> None:
src/cryodaq/core/alarm.py:191:            notifiers=[telegram_notify],
src/cryodaq/core/interlock.py:468:        # Phase 2a Codex I.1: notify the optional trip_handler with FULL

exec
/opt/homebrew/bin/bash -lc "nl -ba docs/ORCHESTRATION.md | sed -n '1,220p'
nl -ba docs/ORCHESTRATION.md | sed -n '220,520p'" in /Users/vladimir/Projects/cryodaq
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
   121	- Points of disagreement + CC's own reasoning on which side wins
   122	- Final decision: what CC will do (write code, run tests,
   123	  propose something back to architect, drop the task)
   124	
   125	The synthesis is the artifact that lives. Individual consultant
   126	prompts and responses can be archived or deleted later —
   127	synthesis stays.
   128	
   129	### 4.4 What consultants must NOT be asked
   130	
   131	- "What do you think of this repo overall?" (broad slop invites
   132	  broad slop)
   133	- "Review everything" (→ shallow audits, see 2026-04-20
   134	  `/ultrareview` attempt)
   135	- "Give me 10 things to improve" (→ premature lists of items with
   136	  no priority signal)
   137	
   138	Valid consultation prompts are **scoped and concrete**: "Here is
   139	a 50-line diff, here is the hypothesis it encodes, here are the
   140	two failure modes I am worried about — tell me which of these
   141	two is more likely and what one experiment would distinguish
   142	them."
   143	
   144	If CC cannot phrase the question at this level of specificity,
   145	it does not need a consultant. It needs to think more.
   146	
   147	---
   148	
   149	## 5. Branch and merge discipline
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
   241	│   └── 2026-04-21-agent-swarm/   ← multi-model review output, archived
   242	├── runbooks/                 ← operational procedures (B1_*, tuning, deployment)
   243	├── decisions/                ← ADRs and resolution ledgers
   244	└── bug_*.md                  ← individual bug handoffs (B1, etc.)
   245	
   246	artifacts/
   247	├── consultations/            ← per-session consultant prompts + responses + synthesis
   248	│   └── YYYY-MM-DD/<topic>/
   249	├── diagnostics/              ← JSONL captures from diag tools
   250	│   └── b1-*.jsonl
   251	└── postmortems/              ← abort postmortems for failed branches
   252	
   253	CC_PROMPT_IV_*_*.md           ← architect-authored batch specs (at repo root, only architect creates)
   254	HANDOFF_<date>_<to>.md        ← session handoffs (at repo root, only architect creates)
   255	SESSION_DETAIL_<date>.md      ← architect chronology dumps (at repo root, only architect creates)
   256	```
   257	
   258	### 6.2 Where things must NOT live
   259	
   260	At **repo root**, the only `.md` files permitted are:
   261	- `README.md`
   262	- `CLAUDE.md`
   263	- `CHANGELOG.md`
   264	- `CODEX_ARCHITECTURE_CONTROL_PLANE.md` — Codex technical dossier (commit 256da7a)
   265	- `ROADMAP.md`
   266	- `PROJECT_STATUS.md`
   267	- `RELEASE_CHECKLIST.md`
   268	- `DOC_REALITY_MAP.md` (historical, may be removed)
   269	- `LICENSE`, `THIRD_PARTY_NOTICES.md`
   270	- `CC_PROMPT_*.md` — architect-authored specs
   271	- `HANDOFF_*.md`, `SESSION_DETAIL_*.md` — architect-authored
   272	
   273	A consultant (or CC on behalf of a consultant) producing
   274	`REPO_HARDENING_FINAL.md` / `REVIEW_PLAN_GEMINI.md` /
   275	`ZERO_TRUST_AUDIT_2026-04-20.md` at repo root is a violation of
   276	this rule. Place under `docs/audits/<date>-<slug>/` or
   277	`artifacts/consultations/<date>/<topic>/` instead. The 12 root-
   278	level markdowns as of 2026-04-23 pre-date this rule; they are
   279	grandfathered into `docs/audits/2026-04-21-agent-swarm/` and
   280	deleted from root.
   281	
   282	### 6.3 Decision ledger
   283	
   284	Every session CC writes to `docs/decisions/<YYYY-MM-DD>-session.md`
   285	a log:
   286	
   287	```
   288	## <HH:MM> — <decision>
   289	Thesis: <one sentence>
   290	Reasoning: <2-4 sentences>
   291	Decision: <what I did>
   292	Consulted: <which models>
   293	Open: <what remains>
   294	```
   295	
   296	One line per decision. The point is that three months from now
   297	somebody reading this ledger can reconstruct what happened and
   298	why, without reading all consultant outputs. The ledger IS the
   299	long-term memory.
   300	
   301	### 6.4 What gets deleted
   302	
   303	Consultant prompt + response files under `artifacts/consultations/`
   304	can be deleted at 30-day age if the synthesis exists and is
   305	committed. The synthesis + decision ledger are the permanent
   306	record. Raw consultant output is ephemeral.
   307	
   308	`.swarm/`, `.omc/`, `.audit-run/`, `agentswarm/`, `.scratch/`
   309	are gitignored working directories. Their contents are never
   310	part of the durable record.
   311	
   312	---
   313	
   314	## 7. Hardening + feature interaction rule
   315	
   316	Pulled out as its own section because it's what broke IV.7 on
   317	2026-04-23.
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
   361	
   362	## 9. What to do when this document is wrong
   363	
   364	This document is authoritative but not immutable. If a rule here
   365	blocks a real improvement:
   366	
   367	1. Note the conflict in that session's decision ledger
   368	2. Propose a rule change in the next architect session
   369	3. Architect updates this file via normal commit
   370	4. Continue under the new rule
   371	
   372	Do not bypass the rule silently. Do not append exceptions to
   373	this file without architect approval.
   374	
   375	---
   376	
   377	## 10. Checklist CC runs at session start
   378	
   379	At the start of every CC session on this repo:
   380	
   381	- [ ] Read this file end-to-end
   382	- [ ] Read `CLAUDE.md` (repo-level invariants)
   383	- [ ] `git status` — note any uncommitted state
   384	- [ ] **If tracked files are modified and not explicitly covered
   385	  by the current plan, STOP with a diff summary.** Plans must be
   386	  built against known-clean state; surprise modifications mean
   387	  recon was stale.
   388	- [ ] `git branch --show-current` — confirm current branch
   389	- [ ] **If current branch does NOT match what architect's plan
   390	  assumes, STOP.** Do not `git checkout` to the planned branch
   391	  silently — plans are annotated with their starting branch for
   392	  a reason. Report the mismatch and wait.
   393	- [ ] `git worktree list` — note active worktrees and branches
   394	- [ ] Check `artifacts/consultations/` for pending response files
   395	  that haven't been synthesized
   396	- [ ] Check `docs/decisions/` for the latest session ledger to
   397	  understand current state of work
   398	- [ ] If stale feature branch (> 2 days) detected: report it and
   399	  block further work until architect decides abort vs merge
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
   461	   extended by convention to untracked architect-authored files
   462	   that start with `SESSION_DETAIL_` or `HANDOFF_`).
   463	
   464	6. **Over-strict stopping.** 2026-04-23 cleanup-baseline session:
   465	   CC stopped 4 times on mechanical inaccuracies in the
   466	   architect's plan (file count off by one, `.worktrees/`
   467	   gitignore assumption wrong, untracked file in worktree that
   468	   would be lost on force-remove, stray plan document in
   469	   secondary worktree). Each stop was correctly justified by
   470	   the then-current rules. But the cumulative architect
   471	   round-trip cost exceeded the value of the caution. Rule
   472	   preventing it: §13 (STOP discipline + autonomy band,
   473	   introduced retroactively after this session).
   474	
   475	Rules exist because specific failures happened. The failures are
   476	enumerated above so that when a future agent is tempted to think
   477	"the rule is too strict, I know better" — check if their
   478	situation matches one of these and remember why we wrote this.
   479	
   480	---
   481	
   482	## 13. STOP discipline and autonomy band
   483	
   484	Added 2026-04-23 evening after cleanup-baseline session exposed
   485	that §§ 2-12 under-specified when to stop vs when to adapt. Four
   486	mid-session stops revealed the gap. Rules below codify what
   487	architect directed in-band.
   488	
   489	### 13.1 When CC MUST stop
   490	
   491	- Irreversible data loss or git history rewrite is at risk
   492	- Semantic ambiguity where two reasonable interpretations produce
   493	  materially different outcomes (not "the file count differs by 1")
   494	- Architect-domain decision required: whitelist membership change,
   495	  branch strategy, policy change, commit message intent, scope
   496	  boundary for a task
   497	- File content suggests sensitive material (credentials, secrets,
   498	  keys, PII) before any mv/copy
   499	- A file > 100 KB is about to be silently discarded
   500	- Test failure during verification (not a warning, an actual fail)
   501	- Consultant response is junk (§4.2 criteria)
   502	
   503	### 13.2 When CC should NOT stop — adapt and ledger instead
   504	
   505	- Plan has factual inaccuracy but the correct fix is mechanically
   506	  obvious (e.g., "plan says 12 files, reality is 11 + 1 tracked;
   507	  adjust commit message, proceed")
   508	- Mechanical detail differs from plan: rename vs add, path depth,
   509	  ordering of steps, exact wording of commit message body
   510	- Untracked file would be lost by planned operation — copy to
   511	  appropriate archive location and proceed (the "no delete" rule
   512	  is a PRESERVE rule, not a STOP rule; see §11 note below)
   513	- Small plan deviation that CC can adapt without polluting the
   514	  semantic outcome
   515	- Command output differs from plan's expected output but achieves
   516	  the same end state
   517	
   518	### 13.3 How to adapt without stopping
   519	
   520	Inline in the session ledger, under the relevant step:

exec
/opt/homebrew/bin/bash -lc "nl -ba \"/Users/vladimir/Vault/CryoDAQ/50 Workflow/ORCHESTRATION contract.md\" | sed -n '1,220p'
nl -ba \"/Users/vladimir/Vault/CryoDAQ/50 Workflow/Multi-model consultation.md\" | sed -n '1,170p'
nl -ba \"/Users/vladimir/Vault/CryoDAQ/50 Workflow/Overnight swarm pattern.md\" | sed -n '1,180p'
nl -ba \"/Users/vladimir/Vault/CryoDAQ/50 Workflow/Calibration loops history.md\" | sed -n '1,180p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
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
    74	`PROJECT_STATUS.md`, `RELEASE_CHECKLIST.md`, `LICENSE`,
    75	`THIRD_PARTY_NOTICES.md`, `CC_PROMPT_*.md`, `HANDOFF_*.md`,
    76	`SESSION_DETAIL_*.md`). Audit / review / hardening output goes
    77	under `docs/audits/<date-slug>/` or
    78	`artifacts/consultations/<date>/<topic>/`, never at root.
    79	
    80	Decision ledger: every session CC writes
    81	`docs/decisions/<YYYY-MM-DD>-session.md` with `## HH:MM —
    82	<decision>` blocks (Thesis / Reasoning / Decision / Consulted /
    83	Open). The ledger is the long-term memory.
    84	
    85	## §7. Hardening + feature interaction rule
    86	
    87	**The rule that exists because of `b2b4fb5` vs IV.7.** Before
    88	landing a hardening / tightening change, check whether it could
    89	affect any active feature branch. If yes, hold or merge into the
    90	feature branch and retest. If no, document why not in the commit
    91	`Risk:` line. Active branches are visible via `git worktree list`
    92	— check before tightening shared infra. See
    93	[[30 Investigations/b2b4fb5 hardening race]].
    94	
    95	## §8. Architect-absent operating mode
    96	
    97	When architect is unavailable (quota window): CC continues
    98	**only on previously-architected plans**. No new directions, no
    99	new feature branches for initiative work. Bug / regression fixes on
   100	in-progress work are OK. End-of-session handoff goes to
   101	`artifacts/handoffs/<date>-cc-to-architect.md`.
   102	
   103	## §9. Document evolution
   104	
   105	This contract is authoritative but not immutable. Disagreement
   106	goes through the architect via decision-ledger note → next
   107	architect session → commit. Do **not** silently bypass.
   108	
   109	## §10. Session start checklist
   110	
   111	Read this doc end-to-end + `CLAUDE.md`. `git status`,
   112	`git branch --show-current`, `git worktree list`. Check
   113	`artifacts/consultations/` for unsynthesized responses. Check
   114	`docs/decisions/` for the latest session ledger. Stale
   115	(>2 day) feature branch detected → block work, surface to
   116	architect.
   117	
   118	## §11. Known active plans
   119	
   120	Tracked table — only plans listed here can be worked on. If a
   121	consultant claims to be working on something else, STOP.
   122	
   123	## §12. Failure-mode reference
   124	
   125	Six historical failure modes are enumerated as the rationale
   126	behind the rules:
   127	
   128	1. Parallel rewrites (`codex/b1-truth-recovery` vs
   129	   `codex/safe-merge-b1-truth-recovery`).
   130	2. Root-directory markdown flood (12 ungoverned `.md` at root).
   131	3. Hardening / feature collision (`b2b4fb5` × IV.7).
   132	4. No-leader multi-agent drift (five agents reviewing without
   133	   synthesis).
   134	5. Lost context (untracked architect dump for 3 days).
   135	6. Over-strict stopping — added retroactively after the
   136	   2026-04-23 cleanup-baseline session
   137	   ([[40 Decisions/2026-04-23-cleanup-baseline]]).
   138	
   139	## §13. STOP discipline and autonomy band (added 2026-04-23)
   140	
   141	§13.1 — when CC must STOP: irreversible data loss / git rewrite,
   142	genuine semantic ambiguity, architect-domain decision, sensitive
   143	material, file > 100 KB about to be silently lost, real test
   144	failure, junk consultant response.
   145	
   146	§13.2 — when CC must NOT stop, adapt instead: 1-line plan
   147	inaccuracy, mechanical detail differs, untracked file would be
   148	lost (preserve to archive then proceed — the "no delete" rule is a
   149	PRESERVE rule, not a STOP rule).
   150	
   151	§13.3 — adaptations are recorded inline in the session ledger as
   152	`Plan said / Reality / Adapted / Outcome`.
   153	
   154	§13.4 — the preserve-vs-delete clarification: archive routine
   155	plan-document patterns and proceed; STOP only on > 100 KB,
   156	sensitive content, credential paths, or binary garbage.
   157	
   158	§13.5 — autonomy band explicitly granted for commit message
   159	wording, file-path adjustments, mechanical step reordering, side-
   160	commits to preserve untracked files. NOT granted for branch
   161	merges outside plan, file deletions outside `git branch -D`
   162	targets, history rewrites, consultant invocations on already-
   163	covered decisions, new feature branches under §8.
   164	
   165	§13.6 — calibration principle: rules that over-stop waste
   166	architect time; rules that under-stop risk silent breakage. The
   167	ledger + handoff are the mechanism that lets CC run with relaxed
   168	stopping discipline; architect end-of-day review catches anything
   169	that should have been a stop.
   170	
   171	## See also
   172	
   173	- `~/Projects/cryodaq/docs/ORCHESTRATION.md` — full text (~600 lines)
   174	- [[50 Workflow/Multi-model consultation]] — skill that operates
   175	  under §4
   176	- [[50 Workflow/Calibration loops history]] — how prompts and CC
   177	  behavior evolved into this contract
   178	- [[40 Decisions/2026-04-23-cleanup-baseline]] — first session run
   179	  under this contract
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
   115	- Required prompt template (`Model: gpt-5.5 / Reasoning effort:
   116	  high` mandatory).
   117	- Autonomy on FAIL: CRITICAL/HIGH → amend without asking;
   118	  design-decision FAIL → STOP + escalate.
   119	- 3-amend cycle limit.
   120	- Final report to architect: SHA + Codex PASS summary + residual
   121	  risks.
   122	
   123	**Outcome.** Block-level work since 2026-04-23 has predictable
   124	review cadence. Architect reads result, not process.
   125	
   126	## Open loops (as of 2026-04-26)
   127	
   128	- **Skill-registry refresh** (Loop 5 above) — pending edit.
   129	- **ORCHESTRATION.md §5.4 wording cleanup** ("already gitignored" →
   130	  "enforced invariant" since `587bea8`) — open from
   131	  [[40 Decisions/2026-04-23-cleanup-baseline]].
   132	- **Retroactive semantic versioning** (v0.34.0..v0.38.0) — postponed
   133	  pending B1 mitigation.
   134	- **§11 known-active-plans table** updates trail by ~1 session
   135	  every architect cycle.
   136	
   137	## The calibration principle (§13.6)
   138	
   139	The point of the loops is that **rules that over-stop waste
   140	architect time, and rules that under-stop risk silent breakage**.
   141	The session ledger + handoff are the corrective mechanism: relaxed
   142	stopping is fine because the architect's end-of-day ledger review
   143	catches anything that should have been a stop.
   144	
   145	If that review pattern breaks down (architect misses something
   146	important in the ledger), specific rules tighten. Otherwise, the
   147	default is autonomy band. The loops are what calibrate that band.
   148	
   149	## See also
   150	
   151	- [[50 Workflow/ORCHESTRATION contract]] §13
   152	- [[40 Decisions/2026-04-23-cleanup-baseline]]
   153	- [[40 Decisions/2026-04-24-b2b4fb5-investigation]]
   154	- [[50 Workflow/Multi-model consultation]]
   155	- [[50 Workflow/Overnight swarm pattern]]

exec
/opt/homebrew/bin/bash -lc "nl -ba .claude/skills/multi-model-consultation.md | sed -n '1,190p'
nl -ba .claude/skills/multi-model-consultation.md | sed -n '190,380p'
nl -ba .claude/skills/multi-model-consultation.md | sed -n '560,700p'" in /Users/vladimir/Projects/cryodaq
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
   241	  │   ├─ code draft, routine transformation
   242	  │   │     → GLM-5.1 draft → CC verify before commit
   243	  │   │
   244	  │   ├─ code draft, non-trivial
   245	  │   │     → CC drafts, Codex reviews. GLM not trustworthy enough.
   246	  │   │
   247	  │   └─ long-form doc / strategy / spec
   248	  │         → CC drafts. Gemini reviews for gaps if needed.
   249	  │
   250	  ├─ NO — is it an audit of existing state (repo, docs, code health)?
   251	  │   │
   252	  │   ├─ narrow scope: one file, specific concern
   253	  │   │     → Codex solo
   254	  │   │
   255	  │   └─ wide scope: whole repo, architectural drift
   256	  │         → Gemini solo, --background
   257	  │
   258	  ├─ NO — is it a question CC can't answer alone?
   259	  │   │
   260	  │   ├─ concurrency / race / lifecycle question → Codex
   261	  │   ├─ cross-file pattern question → Gemini
   262	  │   ├─ long-document comprehension → Kimi
   263	  │   ├─ translation question → GLM or Kimi
   264	  │   └─ math derivation → Kimi
   265	  │
   266	  └─ NO — is it a major architectural decision?
   267	        │
   268	        └─ THREE-way parallel review (Codex + Gemini + one of GLM/Kimi
   269	           for Russian-language clarification if needed) → CC synthesizes
   270	           → architect approves BEFORE action
   271	```
   272	
   273	## 3. Formation patterns
   274	
   275	These are the only patterns you should use. Invent new ones only with
   276	architect approval.
   277	
   278	### 3.1 Solo consultant (most common, ~70% of consultations)
   279	
   280	One consultant, one focused question, one response. CC synthesizes
   281	with its own reasoning.
   282	
   283	Use when: you need a specific answer, budget-sensitive, the decision
   284	is narrow.
   285	
   286	Example: "Codex, is this specific diff safe to commit? Review
   287	docs/ORCHESTRATION.md §4 protocol for context."
   288	
   289	### 3.2 Writer-reviewer pair (~15%)
   290	
   291	One consultant writes a draft, another reviews it. CC integrates the
   292	reviewer's critique into the draft and decides whether to commit.
   293	
   294	Cost: 2x solo. Value: catches issues the drafter misses.
   295	
   296	Classic pair:
   297	- **GLM draft → Codex review** — cheap draft + rigorous review, good
   298	  for routine code changes
   299	- **Kimi draft (when long context helps) → Codex review** — same
   300	  pattern for doc-heavy work
   301	
   302	NEVER pair:
   303	- **Codex + Codex** — same model twice is waste
   304	- **GLM review → anything** — GLM is too weak as adversarial reviewer
   305	
   306	### 3.3 Adversarial pair (~10%)
   307	
   308	Two consultants with opposing perspectives evaluate the same artifact.
   309	CC sees where they agree (high confidence) and where they disagree
   310	(flag for architect or for CC's own deeper analysis).
   311	
   312	Classic pair: **Codex (detail hunter) + Gemini (architecture view)**.
   313	They will often converge. When they don't, the divergence is
   314	informative.
   315	
   316	Use when: high-stakes decision, genuinely unclear tradeoff.
   317	
   318	### 3.4 Wide audit (~3%)
   319	
   320	Single consultant (almost always Gemini with --background flag) given
   321	the whole repository or a large subsystem to scan. Output is a map
   322	of issues, not a fix.
   323	
   324	Use when: entering a new area, inheriting work, preparing for major
   325	refactor. Expensive time-wise.
   326	
   327	DO NOT use as a "default safety net" — `/ultrareview` misuse on
   328	2026-04-20 is the cautionary tale.
   329	
   330	### 3.5 Three-way parallel (~2%)
   331	
   332	Reserved for truly major decisions: architecture pivots, major
   333	dependency changes, safety-logic rewrites.
   334	
   335	Pattern: CC drafts a proposal → Codex, Gemini, and Kimi in parallel
   336	each review it → CC synthesizes all three → architect approves.
   337	
   338	Requires architect to be available. Do NOT use as coordinator-solo
   339	decision mechanism.
   340	
   341	## 4. Consultation protocol (from ORCHESTRATION.md §4)
   342	
   343	Every consultation has four artifacts. All four are created by CC.
   344	
   345	### 4.1 Brief
   346	
   347	`artifacts/consultations/<YYYY-MM-DD>/<topic-slug>/<consultant>.prompt.md`
   348	
   349	```
   350	# Consultation brief — <topic> — for <consultant>
   351	
   352	## Mission
   353	<one-paragraph description of what we are trying to decide>
   354	
   355	## Context files
   356	<list of paths — consultant MUST read these before answering>
   357	
   358	## Specific questions
   359	1. <numbered, answerable>
   360	2. <question>
   361	
   362	## Expected output format
   363	<e.g., "markdown table with columns X Y Z, maximum 800 words,
   364	file:line refs for every claim, no prose introduction">
   365	
   366	## Time / token budget
   367	<e.g., "respond in < 30 min of wall clock, single pass, no
   368	deep-background mode">
   369	
   370	## Response file path
   371	<absolute path where consultant output goes>
   372	
   373	## What NOT to answer
   374	<scope fences — what is out of scope for this consultation>
   375	```
   376	
   377	### 4.2 Response
   378	
   379	`artifacts/consultations/<YYYY-MM-DD>/<topic-slug>/<consultant>.response.md`
   380	
   560	active feature branch state, evaluates whether the hardening would
   561	reject the feature's post-change state, holds or revises the
   562	hardening accordingly. See `docs/ORCHESTRATION.md` §7.
   563	
   564	### 7.6 No-synthesis slam
   565	
   566	**What happened:** multiple review files were produced by different
   567	models on 2026-04-21 with no synthesis step. Each proposed different
   568	next moves. Architect had to read all of them to piece together a
   569	decision.
   570	
   571	**Why:** CC dispatched consultants but never integrated their outputs.
   572	
   573	**Don't:** skip step 4.3 (synthesis). The prompt/response files are
   574	NOT the record — the synthesis is.
   575	
   576	**Do:** synthesize before calling next consultant. If you don't know
   577	how to synthesize the first response yet, don't dispatch the next
   578	one.
   579	
   580	### 7.7 Wrong reasoning level on Codex
   581	
   582	**What happened:** Codex default `o3` model with low reasoning was
   583	used for a B1 analysis earlier. Output was shallow and missed the
   584	shared-REQ-state pattern that `gpt-5.4 high` (then the latest) later
   585	identified.
   586	
   587	**Why:** `/codex` defaults are weak. Override is required.
   588	
   589	**Don't:** invoke `/codex` without explicit model + reasoning flags.
   590	
   591	**Do:** ALWAYS pass `--model gpt-5.5 --reasoning high` AND repeat in
   592	prompt body first two lines: `Model: gpt-5.5 / Reasoning effort: high`.
   593	(Or the current latest Codex model — gpt-5.5 as of 2026-04-24.)
   594	
   595	## 8. Templates
   596	
   597	Copy-paste starting points. Fill in brackets.
   598	
   599	### 8.1 Codex adversarial review brief
   600	
   601	```
   602	Model: gpt-5.5
   603	Reasoning effort: high
   604	
   605	# Adversarial review — [one-line task description]
   606	
   607	## Context files (read before answering)
   608	- [path 1]
   609	- [path 2]
   610	- [optional: diff to review — paste inline or reference commit SHA]
   611	
   612	## Your role
   613	Adversarial reviewer. Find what is wrong with the commit / diff /
   614	proposal. If it passes your scrutiny, say PASS and stop. If it fails,
   615	list findings in CRITICAL / HIGH / MEDIUM / LOW buckets with file:line
   616	refs for every claim.
   617	
   618	## Specifically verify
   619	1. [specific concern 1]
   620	2. [specific concern 2]
   621	
   622	## Expected output format
   623	- Header: PASS | FAIL | CONDITIONAL (specify condition)
   624	- Findings: numbered, with severity + file:line + reasoning
   625	- Max 2000 words. Terse is better than verbose.
   626	
   627	## Scope fence
   628	[anything explicitly NOT to critique, e.g. "do not comment on
   629	unrelated style issues"]
   630	
   631	## Response file
   632	Write to: artifacts/consultations/[DATE]/[topic]/codex.response.md
   633	```
   634	
   635	### 8.2 Gemini wide-audit brief
   636	
   637	```
   638	Model: gemini-3.1-pro-preview
   639	
   640	# Wide audit — [subsystem or topic]
   641	
   642	## Context
   643	You have the entire [src/cryodaq/...] tree available. Use 1M window.
   644	
   645	## Mission
   646	[what you are scanning for — architectural drift, doc-vs-code mismatch,
   647	pattern consistency, etc.]
   648	
   649	## Specifically look for
   650	1. [pattern 1]
   651	2. [pattern 2]
   652	
   653	## Expected output format
   654	- Single markdown table with columns: [finding, file:line, severity, explanation]
   655	- Maximum 3000 words total
   656	- No executive summary, no recommendations — CC synthesizes those
   657	- Include BOTH positive findings (consistent patterns worth preserving)
   658	  AND negative findings (drift, bugs)
   659	
   660	## Time budget
   661	Run deep (--background). 60-90 min wall clock acceptable.
   662	
   663	## Response file
   664	Write to: artifacts/consultations/[DATE]/[topic]/gemini.response.md
   665	```
   666	
   667	### 8.3 GLM draft brief
   668	
   669	```
   670	# Code draft — [one-line task]
   671	
   672	## Mission
   673	Produce a draft of [specific code change or file]. CC will verify
   674	against tests before commit. You are NOT the final authority — your
   675	output is a starting point.
   676	
   677	## Specification
   678	[exact spec of what the code should do]
   679	
   680	## Context files
   681	- [path to file to modify]
   682	- [related files]
   683	
   684	## Expected output
   685	- Full file content (not a diff)
   686	- Maximum 200 lines of code
   687	- Standard-compliant Python 3.12+, use repo's ruff config
   688	- No external dependencies beyond what's already in pyproject.toml
   689	- Include docstrings
   690	
   691	## Scope fence
   692	- Do NOT modify any files other than the one specified
   693	- Do NOT add new config keys
   694	- Do NOT commit, push, or create branches
   695	
   696	## Response file
   697	Write to: artifacts/consultations/[DATE]/[topic]/glm.response.md
   698	```
   699	
   700	### 8.4 Kimi long-document-digest brief

exec
/opt/homebrew/bin/bash -lc "rg -n \"cof|\\.330|\\.340|export\\(|CalibrationFitResult|extract_pairs|adaptive_downsample|generate_breakpoints|resolve_runtime_policy|global_mode|per_channel|runtime_settings|CSV|import\" src/cryodaq/analytics/calibration.py src/cryodaq/analytics/calibration_fitter.py src/cryodaq/core/calibration_acquisition.py README.md CLAUDE.md PROJECT_STATUS.md" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
src/cryodaq/core/calibration_acquisition.py:3:from __future__ import annotations
src/cryodaq/core/calibration_acquisition.py:5:import logging
src/cryodaq/core/calibration_acquisition.py:6:import math
src/cryodaq/core/calibration_acquisition.py:7:from typing import Any
src/cryodaq/core/calibration_acquisition.py:9:from cryodaq.core.channel_manager import ChannelConfigError
src/cryodaq/core/calibration_acquisition.py:10:from cryodaq.drivers.base import ChannelStatus, Reading
src/cryodaq/core/calibration_acquisition.py:174:        import warnings
CLAUDE.md:44:- Calibration v2: continuous SRDG acquisition during calibration experiments (CalibrationAcquisitionService), post-run pipeline (CalibrationFitter: extract → downsample → breakpoints → Chebyshev fit), three-mode GUI (Setup → Acquisition → Results), `.330` / `.340` / JSON export, runtime apply с per-channel policy.
CLAUDE.md:147:- `Файл` — экспорт CSV / HDF5 / Excel
CLAUDE.md:291:- `src/cryodaq/storage/csv_export.py` — экспорт данных из SQLite в CSV
CLAUDE.md:375:- Exception: if the amend touches a module imported by many non-test files (e.g. `main_window_v2.py`, `engine.py`, `safety_manager.py`), run the full suite. Judgment call.
CLAUDE.md:380:- **BOM применяется только к** operator-facing CSV-выгрузкам (`storage/csv_export.py`) — Excel на русской Windows корректно читает Cyrillic только при BOM-префиксе. Это per-usecase решение, не общее правило репо.
CLAUDE.md:432:- After modifying code files in this session, run `python3 -c "from graphify.watch import _rebuild_code; from pathlib import Path; _rebuild_code(Path('.'))"` to keep the graph current
README.md:9:- Calibration v2: непрерывный сбор SRDG при калибровочных экспериментах, post-run pipeline (extract → downsample → Chebyshev fit), `.330` / `.340` export, runtime apply с global/per-channel policy.
README.md:62:- меню `Файл` с экспортом CSV / HDF5 / Excel
README.md:84:  - `.330` / `.340` / JSON / CSV import/export
README.md:252:  storage/            # SQLiteWriter, Parquet, CSV, HDF5, XLSX export
src/cryodaq/analytics/calibration_fitter.py:3:from __future__ import annotations
src/cryodaq/analytics/calibration_fitter.py:5:import logging
src/cryodaq/analytics/calibration_fitter.py:6:import math
src/cryodaq/analytics/calibration_fitter.py:7:import sqlite3
src/cryodaq/analytics/calibration_fitter.py:8:from dataclasses import dataclass
src/cryodaq/analytics/calibration_fitter.py:9:from datetime import UTC, datetime
src/cryodaq/analytics/calibration_fitter.py:10:from pathlib import Path
src/cryodaq/analytics/calibration_fitter.py:11:from typing import Any
src/cryodaq/analytics/calibration_fitter.py:13:import numpy as np
src/cryodaq/analytics/calibration_fitter.py:15:from cryodaq.analytics.calibration import CalibrationCurve, CalibrationSample, CalibrationStore
src/cryodaq/analytics/calibration_fitter.py:21:class CalibrationFitResult:
src/cryodaq/analytics/calibration_fitter.py:42:    def extract_pairs(
src/cryodaq/analytics/calibration_fitter.py:124:    def adaptive_downsample(
src/cryodaq/analytics/calibration_fitter.py:196:    def generate_breakpoints(
src/cryodaq/analytics/calibration_fitter.py:201:        """Douglas-Peucker breakpoint selection for .330 export."""
src/cryodaq/analytics/calibration_fitter.py:325:    ) -> CalibrationFitResult:
src/cryodaq/analytics/calibration_fitter.py:330:        raw_pairs = self.extract_pairs(
src/cryodaq/analytics/calibration_fitter.py:344:        downsampled = self.adaptive_downsample(raw_pairs, target_count)
src/cryodaq/analytics/calibration_fitter.py:347:        breakpoints = self.generate_breakpoints(
src/cryodaq/analytics/calibration_fitter.py:394:        return CalibrationFitResult(
src/cryodaq/analytics/calibration.py:3:from __future__ import annotations
src/cryodaq/analytics/calibration.py:5:import csv
src/cryodaq/analytics/calibration.py:6:import json
src/cryodaq/analytics/calibration.py:7:import math
src/cryodaq/analytics/calibration.py:8:import uuid
src/cryodaq/analytics/calibration.py:9:import warnings
src/cryodaq/analytics/calibration.py:10:from dataclasses import dataclass, field
src/cryodaq/analytics/calibration.py:11:from datetime import UTC, datetime
src/cryodaq/analytics/calibration.py:12:from pathlib import Path
src/cryodaq/analytics/calibration.py:13:from typing import Any
src/cryodaq/analytics/calibration.py:15:import numpy as np
src/cryodaq/analytics/calibration.py:16:import yaml
src/cryodaq/analytics/calibration.py:17:from numpy.polynomial import chebyshev as cheb
src/cryodaq/analytics/calibration.py:207:        self._runtime_settings: dict[str, Any] = {
src/cryodaq/analytics/calibration.py:208:            "global_mode": "off",
src/cryodaq/analytics/calibration.py:345:        from cryodaq.core.atomic_write import atomic_write_text
src/cryodaq/analytics/calibration.py:364:    def import_curve_json(self, path: Path) -> CalibrationCurve:
src/cryodaq/analytics/calibration.py:367:    def import_curve_file(
src/cryodaq/analytics/calibration.py:378:            curve = self.import_curve_json(path)
src/cryodaq/analytics/calibration.py:379:        elif suffix in {".330", ".340"}:
src/cryodaq/analytics/calibration.py:380:            curve = self._import_curve_text(
src/cryodaq/analytics/calibration.py:386:                import_format=suffix.lstrip("."),
src/cryodaq/analytics/calibration.py:389:            raise ValueError(f"Unsupported calibration import format: {path.suffix}")
src/cryodaq/analytics/calibration.py:432:        target = path or (self._curve_directory(curve.sensor_id, curve.curve_id) / "curve.330")
src/cryodaq/analytics/calibration.py:435:        self._write_curve_text_export(target, curve, rows, format_name="330")
src/cryodaq/analytics/calibration.py:452:        self._write_curve_text_export(target, curve, rows, format_name="340")
src/cryodaq/analytics/calibration.py:482:                self._curve_directory(curve.sensor_id, curve.curve_id) / "curve.330"
src/cryodaq/analytics/calibration.py:502:    def get_runtime_settings(self) -> dict[str, Any]:
src/cryodaq/analytics/calibration.py:506:            resolution = self.resolve_runtime_policy(channel_key=channel_key) if channel_key else {}
src/cryodaq/analytics/calibration.py:514:            "global_mode": str(self._runtime_settings.get("global_mode", "off") or "off"),
src/cryodaq/analytics/calibration.py:515:            "updated_at": str(self._runtime_settings.get("updated_at", "")).strip(),
src/cryodaq/analytics/calibration.py:519:    def set_runtime_global_mode(self, mode: str) -> dict[str, Any]:
src/cryodaq/analytics/calibration.py:522:            raise ValueError("Runtime calibration global_mode must be 'off' or 'on'.")
src/cryodaq/analytics/calibration.py:523:        self._runtime_settings["global_mode"] = normalized
src/cryodaq/analytics/calibration.py:524:        self._runtime_settings["updated_at"] = _utcnow().isoformat()
src/cryodaq/analytics/calibration.py:526:        return self.get_runtime_settings()
src/cryodaq/analytics/calibration.py:556:            "resolution": self.resolve_runtime_policy(channel_key=normalized_channel_key),
src/cryodaq/analytics/calibration.py:559:    def resolve_runtime_policy(
src/cryodaq/analytics/calibration.py:567:        global_mode = str(self._runtime_settings.get("global_mode", "off") or "off")
src/cryodaq/analytics/calibration.py:576:        if global_mode == "off":
src/cryodaq/analytics/calibration.py:578:                "global_mode": global_mode,
src/cryodaq/analytics/calibration.py:588:                "global_mode": global_mode,
src/cryodaq/analytics/calibration.py:599:                "global_mode": global_mode,
src/cryodaq/analytics/calibration.py:609:                "global_mode": global_mode,
src/cryodaq/analytics/calibration.py:620:                "global_mode": global_mode,
src/cryodaq/analytics/calibration.py:630:            "global_mode": global_mode,
src/cryodaq/analytics/calibration.py:731:            / "curve.340"
src/cryodaq/analytics/calibration.py:740:            global_mode = str(runtime.get("global_mode", "off") or "off").strip().lower()
src/cryodaq/analytics/calibration.py:741:            if global_mode in {"off", "on"}:
src/cryodaq/analytics/calibration.py:742:                self._runtime_settings["global_mode"] = global_mode
src/cryodaq/analytics/calibration.py:743:            self._runtime_settings["updated_at"] = str(runtime.get("updated_at", "")).strip()
src/cryodaq/analytics/calibration.py:773:                "global_mode": str(self._runtime_settings.get("global_mode", "off") or "off"),
src/cryodaq/analytics/calibration.py:774:                "updated_at": str(self._runtime_settings.get("updated_at", "")).strip(),
src/cryodaq/analytics/calibration.py:788:                        self._curve_directory(curve.sensor_id, curve.curve_id) / "curve.330"
src/cryodaq/analytics/calibration.py:803:        from cryodaq.core.atomic_write import atomic_write_text
src/cryodaq/analytics/calibration.py:852:    def _write_curve_text_export(
src/cryodaq/analytics/calibration.py:870:    def _import_curve_text(
src/cryodaq/analytics/calibration.py:878:        import_format: str,
src/cryodaq/analytics/calibration.py:903:                reference_channel="import",
src/cryodaq/analytics/calibration.py:907:                metadata={"import_format": import_format, "source_path": str(path)},
src/cryodaq/analytics/calibration.py:922:                "import_format": import_format,
src/cryodaq/analytics/calibration.py:923:                "import_source_path": str(path),
src/cryodaq/analytics/calibration.py:928:        if import_format == "330":
src/cryodaq/analytics/calibration.py:930:        if import_format == "340":

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/analytics/calibration.py | sed -n '320,490p'
nl -ba src/cryodaq/analytics/calibration.py | sed -n '490,635p'
nl -ba src/cryodaq/analytics/calibration_fitter.py | sed -n '320,410p'
nl -ba src/cryodaq/core/calibration_acquisition.py | sed -n '1,230p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   320	        magnetic_field_T: float = 0.0,
   321	    ) -> float:
   322	        return self.evaluate(sensor_id, voltage, magnetic_field_T=magnetic_field_T)
   323	
   324	    def T_from_V(
   325	        self,
   326	        sensor_id: str,
   327	        voltage: float,
   328	        *,
   329	        magnetic_field_T: float = 0.0,
   330	    ) -> float:
   331	        return self.voltage_to_temp(sensor_id, voltage, magnetic_field_T=magnetic_field_T)
   332	
   333	    def resistance_to_temp(
   334	        self,
   335	        sensor_id: str,
   336	        resistance: float,
   337	        *,
   338	        magnetic_field_T: float = 0.0,
   339	    ) -> float:
   340	        return self.evaluate(sensor_id, resistance, magnetic_field_T=magnetic_field_T)
   341	
   342	    def save_curve(self, curve: CalibrationCurve, path: Path | None = None) -> Path:
   343	        target = path or self._curve_path(curve.sensor_id, curve.curve_id)
   344	        target.parent.mkdir(parents=True, exist_ok=True)
   345	        from cryodaq.core.atomic_write import atomic_write_text
   346	
   347	        atomic_write_text(target, json.dumps(curve.to_payload(), ensure_ascii=False, indent=2))
   348	        self._curves[curve.sensor_id] = curve
   349	        self._ensure_assignment(sensor_id=curve.sensor_id, curve_id=curve.curve_id)
   350	        self._write_index()
   351	        return target
   352	
   353	    def load_curve(self, path: Path) -> CalibrationCurve:
   354	        curve = CalibrationCurve.from_payload(json.loads(path.read_text(encoding="utf-8")))
   355	        self._curves[curve.sensor_id] = curve
   356	        self._ensure_assignment(sensor_id=curve.sensor_id, curve_id=curve.curve_id)
   357	        return curve
   358	
   359	    def load_curves(self, curves_dir: Path) -> None:
   360	        for path in sorted(curves_dir.glob("**/*.json")):
   361	            self.load_curve(path)
   362	        self._write_index()
   363	
   364	    def import_curve_json(self, path: Path) -> CalibrationCurve:
   365	        return self.load_curve(path)
   366	
   367	    def import_curve_file(
   368	        self,
   369	        path: Path,
   370	        *,
   371	        sensor_id: str | None = None,
   372	        channel_key: str | None = None,
   373	        raw_unit: str = "sensor_unit",
   374	        sensor_kind: str = "generic",
   375	    ) -> CalibrationCurve:
   376	        suffix = path.suffix.lower()
   377	        if suffix == ".json":
   378	            curve = self.import_curve_json(path)
   379	        elif suffix in {".330", ".340"}:
   380	            curve = self._import_curve_text(
   381	                path,
   382	                sensor_id=sensor_id,
   383	                channel_key=channel_key,
   384	                raw_unit=raw_unit,
   385	                sensor_kind=sensor_kind,
   386	                import_format=suffix.lstrip("."),
   387	            )
   388	        else:
   389	            raise ValueError(f"Unsupported calibration import format: {path.suffix}")
   390	        if channel_key:
   391	            self.assign_curve(
   392	                sensor_id=curve.sensor_id,
   393	                curve_id=curve.curve_id,
   394	                channel_key=channel_key,
   395	                runtime_apply_ready=False,
   396	            )
   397	        self._write_index()
   398	        return curve
   399	
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
   456	    def get_curve_info(
   457	        self, sensor_id: str | None = None, curve_id: str | None = None
   458	    ) -> dict[str, Any]:
   459	        curve = self._resolve_curve(sensor_id=sensor_id, curve_id=curve_id)
   460	        return {
   461	            "sensor_id": curve.sensor_id,
   462	            "curve_id": curve.curve_id,
   463	            "fit_timestamp": curve.fit_timestamp.isoformat(),
   464	            "raw_unit": curve.raw_unit,
   465	            "sensor_kind": curve.sensor_kind,
   466	            "source_session_ids": list(curve.source_session_ids),
   467	            "zones": [zone.to_payload() for zone in curve.zones],
   468	            "metrics": dict(curve.metrics),
   469	            "metadata": dict(curve.metadata),
   470	            "artifacts": self.get_curve_artifacts(curve.sensor_id),
   471	            "assignment": dict(self._assignments.get(curve.sensor_id) or {}),
   472	        }
   473	
   474	    def get_curve_artifacts(self, sensor_id: str) -> dict[str, str]:
   475	        curve = self._require_curve(sensor_id)
   476	        return {
   477	            "curve_path": str(self._curve_path(curve.sensor_id, curve.curve_id)),
   478	            "table_path": str(
   479	                self._curve_directory(curve.sensor_id, curve.curve_id) / "curve_table.csv"
   480	            ),
   481	            "curve_330_path": str(
   482	                self._curve_directory(curve.sensor_id, curve.curve_id) / "curve.330"
   483	            ),
   484	            "curve_340_path": str(
   485	                self._curve_340_path(curve.sensor_id, curve.curve_id) if self._exports_dir else ""
   486	            ),
   487	            "index_path": str(self._index_path) if self._index_path else "",
   488	        }
   489	
   490	    def list_curves(self, *, sensor_id: str | None = None) -> list[dict[str, Any]]:
   490	    def list_curves(self, *, sensor_id: str | None = None) -> list[dict[str, Any]]:
   491	        curves = list(self._curves.values())
   492	        if sensor_id:
   493	            curves = [curve for curve in curves if curve.sensor_id == sensor_id]
   494	        curves.sort(key=lambda item: item.fit_timestamp, reverse=True)
   495	        return [self.get_curve_info(curve_id=curve.curve_id) for curve in curves]
   496	
   497	    def list_assignments(self) -> list[dict[str, Any]]:
   498	        assignments = [dict(item) for item in self._assignments.values()]
   499	        assignments.sort(key=lambda item: str(item.get("sensor_id", "")))
   500	        return assignments
   501	
   502	    def get_runtime_settings(self) -> dict[str, Any]:
   503	        assignments = []
   504	        for item in self.list_assignments():
   505	            channel_key = str(item.get("channel_key", "")).strip()
   506	            resolution = self.resolve_runtime_policy(channel_key=channel_key) if channel_key else {}
   507	            assignments.append(
   508	                {
   509	                    **item,
   510	                    "resolution": resolution,
   511	                }
   512	            )
   513	        return {
   514	            "global_mode": str(self._runtime_settings.get("global_mode", "off") or "off"),
   515	            "updated_at": str(self._runtime_settings.get("updated_at", "")).strip(),
   516	            "assignments": assignments,
   517	        }
   518	
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
   616	            }
   617	        sensor_id = str(assignment.get("sensor_id", "")).strip()
   618	        if not sensor_id or sensor_id not in self._curves:
   619	            return {
   620	                "global_mode": global_mode,
   621	                "channel_key": normalized_channel_key,
   622	                "effective_mode": "off",
   623	                "reading_mode": "krdg",
   624	                "raw_source": "KRDG",
   625	                "reason": "missing_curve",
   626	                "assignment": assignment,
   627	            }
   628	        curve = self._curves[sensor_id]
   629	        return {
   630	            "global_mode": global_mode,
   631	            "channel_key": normalized_channel_key,
   632	            "effective_mode": "on",
   633	            "reading_mode": "curve",
   634	            "raw_source": "SRDG",
   635	            "reason": "curve_applied",
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
   401	            metrics=metrics,
   402	            raw_pairs=raw_pairs,
   403	            downsampled=downsampled,
   404	            breakpoints=breakpoints,
   405	        )
     1	"""Continuous SRDG acquisition during calibration experiments."""
     2	
     3	from __future__ import annotations
     4	
     5	import logging
     6	import math
     7	from typing import Any
     8	
     9	from cryodaq.core.channel_manager import ChannelConfigError
    10	from cryodaq.drivers.base import ChannelStatus, Reading
    11	
    12	logger = logging.getLogger(__name__)
    13	
    14	
    15	class CalibrationCommandError(ValueError):
    16	    """Raised when a calibration command cannot be executed due to invalid parameters."""
    17	
    18	
    19	class CalibrationAcquisitionService:
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
   171	        Kept for test backward compatibility. Production code uses the
   172	        new split via Scheduler. Will be removed in next major version.
   173	        """
   174	        import warnings
   175	
   176	        warnings.warn(
   177	            "on_readings is deprecated; use prepare_srdg_readings + on_srdg_persisted",
   178	            DeprecationWarning,
   179	            stacklevel=2,
   180	        )
   181	        if not self._active:
   182	            return
   183	
   184	        to_write, pending_state = self.prepare_srdg_readings(krdg, srdg)
   185	        if to_write:
   186	            await self._writer.write_immediate(to_write)
   187	            self.on_srdg_persisted(len(to_write), pending_state)

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/core/safety_manager.py | sed -n '248,560p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   248	    async def request_run(
   249	        self,
   250	        p_target: float,
   251	        v_comp: float,
   252	        i_comp: float,
   253	        *,
   254	        channel: str | None = None,
   255	    ) -> dict[str, Any]:
   256	        async with self._cmd_lock:
   257	            smu_channel = normalize_smu_channel(channel)
   258	
   259	            if self._state == SafetyState.FAULT_LATCHED:
   260	                return {
   261	                    "ok": False,
   262	                    "state": self._state.value,
   263	                    "channel": smu_channel,
   264	                    "error": f"FAULT: {self._fault_reason}",
   265	                }
   266	
   267	            if self._state not in (SafetyState.SAFE_OFF, SafetyState.READY, SafetyState.RUNNING):
   268	                return {
   269	                    "ok": False,
   270	                    "state": self._state.value,
   271	                    "channel": smu_channel,
   272	                    "error": f"Start not allowed from {self._state.value}",
   273	                }
   274	
   275	            if smu_channel in self._active_sources:
   276	                return {
   277	                    "ok": False,
   278	                    "state": self._state.value,
   279	                    "channel": smu_channel,
   280	                    "error": f"Channel {smu_channel} already active",
   281	                }
   282	
   283	            ok, reason = self._check_preconditions()
   284	            if not ok:
   285	                return {
   286	                    "ok": False,
   287	                    "state": self._state.value,
   288	                    "channel": smu_channel,
   289	                    "error": reason,
   290	                }
   291	
   292	            if p_target > self._config.max_power_w:
   293	                return {
   294	                    "ok": False,
   295	                    "state": self._state.value,
   296	                    "channel": smu_channel,
   297	                    "error": f"P={p_target}W exceeds limit {self._config.max_power_w}W",
   298	                }
   299	            if v_comp > self._config.max_voltage_v:
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
   391	                    "error": "System is fault-latched - acknowledge_fault required",
   392	                }
   393	
   394	            await self._safe_off("Operator stop", channels=channels)
   395	            await self._publish_keithley_channel_states("stop")
   396	            return {
   397	                "ok": True,
   398	                "state": self._state.value,
   399	                "channels": sorted(channels),
   400	                "active_channels": sorted(self._active_sources),
   401	            }
   402	
   403	    async def emergency_off(self, *, channel: str | None = None) -> dict[str, Any]:
   404	        async with self._cmd_lock:
   405	            channels = self._resolve_channels(channel)
   406	            await self._ensure_output_off(channel)
   407	            self._active_sources.difference_update(channels)
   408	            await self._publish_keithley_channel_states("emergency_off")
   409	
   410	            if self._state == SafetyState.FAULT_LATCHED:
   411	                return {
   412	                    "ok": True,
   413	                    "state": self._state.value,
   414	                    "channels": sorted(channels),
   415	                    "active_channels": sorted(self._active_sources),
   416	                    "latched": True,
   417	                    "warning": "Outputs disabled but fault remains latched",
   418	                }
   419	
   420	            if not self._active_sources:
   421	                self._transition(SafetyState.SAFE_OFF, "Operator emergency off")
   422	
   423	            return {
   424	                "ok": True,
   425	                "state": self._state.value,
   426	                "channels": sorted(channels),
   427	                "active_channels": sorted(self._active_sources),
   428	            }
   429	
   430	    async def update_target(self, p_target: float, *, channel: str | None = None) -> dict[str, Any]:
   431	        """Live-update P_target on an active channel. Validates against config limits."""
   432	        async with self._cmd_lock:
   433	            smu_channel = normalize_smu_channel(channel)
   434	
   435	            if self._state == SafetyState.FAULT_LATCHED:
   436	                return {"ok": False, "error": f"FAULT: {self._fault_reason}"}
   437	
   438	            if smu_channel not in self._active_sources:
   439	                return {"ok": False, "error": f"Channel {smu_channel} not active"}
   440	
   441	            if p_target <= 0:
   442	                return {"ok": False, "error": "p_target must be > 0"}
   443	
   444	            if p_target > self._config.max_power_w:
   445	                return {
   446	                    "ok": False,
   447	                    "error": f"P={p_target}W exceeds limit {self._config.max_power_w}W",
   448	                }
   449	
   450	            if self._keithley is None:
   451	                return {"ok": False, "error": "Keithley not connected"}
   452	
   453	            runtime = self._keithley._channels.get(smu_channel)
   454	            if runtime is None or not runtime.active:
   455	                return {"ok": False, "error": f"Channel {smu_channel} not active on instrument"}
   456	
   457	            old_p = runtime.p_target
   458	            runtime.p_target = p_target
   459	            logger.info("SAFETY: P_target update %s: %.4f → %.4f W", smu_channel, old_p, p_target)
   460	
   461	            return {"ok": True, "channel": smu_channel, "p_target": p_target}
   462	
   463	    async def update_limits(
   464	        self,
   465	        *,
   466	        channel: str | None = None,
   467	        v_comp: float | None = None,
   468	        i_comp: float | None = None,
   469	    ) -> dict[str, Any]:
   470	        """Live-update V/I compliance limits. Validates against config limits."""
   471	        async with self._cmd_lock:
   472	            smu_channel = normalize_smu_channel(channel)
   473	
   474	            if self._state == SafetyState.FAULT_LATCHED:
   475	                return {"ok": False, "error": f"FAULT: {self._fault_reason}"}
   476	
   477	            if smu_channel not in self._active_sources:
   478	                return {"ok": False, "error": f"Channel {smu_channel} not active"}
   479	
   480	            if self._keithley is None:
   481	                return {"ok": False, "error": "Keithley not connected"}
   482	
   483	            runtime = self._keithley._channels.get(smu_channel)
   484	            if runtime is None or not runtime.active:
   485	                return {"ok": False, "error": f"Channel {smu_channel} not active on instrument"}
   486	
   487	            if v_comp is not None:
   488	                if v_comp <= 0:
   489	                    return {"ok": False, "error": "v_comp must be > 0"}
   490	                if v_comp > self._config.max_voltage_v:
   491	                    return {
   492	                        "ok": False,
   493	                        "error": f"V={v_comp}V exceeds limit {self._config.max_voltage_v}V",
   494	                    }
   495	                if not self._keithley.mock:
   496	                    await self._keithley._transport.write(f"{smu_channel}.source.limitv = {v_comp}")
   497	                runtime.v_comp = v_comp  # update only after successful write
   498	
   499	            if i_comp is not None:
   500	                if i_comp <= 0:
   501	                    return {"ok": False, "error": "i_comp must be > 0"}
   502	                if i_comp > self._config.max_current_a:
   503	                    return {
   504	                        "ok": False,
   505	                        "error": f"I={i_comp}A exceeds limit {self._config.max_current_a}A",
   506	                    }
   507	                if not self._keithley.mock:
   508	                    await self._keithley._transport.write(f"{smu_channel}.source.limiti = {i_comp}")
   509	                runtime.i_comp = i_comp  # update only after successful write
   510	
   511	            logger.info(
   512	                "SAFETY: limits update %s: V_comp=%.1f I_comp=%.3f",
   513	                smu_channel,
   514	                runtime.v_comp,
   515	                runtime.i_comp,
   516	            )
   517	            return {
   518	                "ok": True,
   519	                "channel": smu_channel,
   520	                "v_comp": runtime.v_comp,
   521	                "i_comp": runtime.i_comp,
   522	            }
   523	
   524	    async def acknowledge_fault(self, reason: str) -> dict[str, Any]:
   525	        async with self._cmd_lock:
   526	            if self._state != SafetyState.FAULT_LATCHED:
   527	                return {
   528	                    "ok": False,
   529	                    "state": self._state.value,
   530	                    "error": "Нет активной аварии для подтверждения",
   531	                }
   532	            if self._config.require_reason and not reason.strip():
   533	                return {"ok": False, "state": self._state.value, "error": "Укажите причину аварии"}
   534	
   535	            elapsed = time.monotonic() - self._fault_time
   536	            if elapsed < self._config.cooldown_before_rearm_s:
   537	                remaining = self._config.cooldown_before_rearm_s - elapsed
   538	                return {
   539	                    "ok": False,
   540	                    "state": self._state.value,
   541	                    "error": f"Ожидание: ещё {remaining:.0f}с до разрешения восстановления",
   542	                }
   543	
   544	            self._recovery_reason = reason.strip()
   545	            # Phase 2a H.1: clear persistence-failure latch on the writer
   546	            # via the engine-wired callback. This is what unblocks scheduler
   547	            # polling — DiskMonitor only logs recovery, it does not clear.
   548	            if self._persistence_failure_clear is not None:
   549	                try:
   550	                    self._persistence_failure_clear()
   551	                except Exception as exc:
   552	                    logger.error("persistence_failure_clear callback failed: %s", exc)
   553	            self._transition(SafetyState.MANUAL_RECOVERY, f"Fault acknowledged: {reason}")
   554	            await self._publish_keithley_channel_states("fault_acknowledged")
   555	            return {"ok": True, "state": self._state.value}
   556	
   557	    def set_persistence_failure_clear(self, callback: Callable[[], None]) -> None:
   558	        """Register a sync callback that clears external persistence-failure
   559	        flags (Phase 2a H.1). Called from acknowledge_fault."""
   560	        self._persistence_failure_clear = callback

exec
/opt/homebrew/bin/bash -lc "nl -ba config/safety.yaml | sed -n '1,200p'
rg -n \"SafetyManager|SAFE_OFF|READY|RUN_PERMITTED|FAULT_LATCHED|stale|RateEstimator|acknowledge_fault|exit code 2|SafetyConfigError|interlocks.yaml|housekeeping.yaml|channels.yaml\" CLAUDE.md PROJECT_STATUS.md README.md src/cryodaq/core/safety_manager.py src/cryodaq/engine.py src/cryodaq/launcher.py" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
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
src/cryodaq/engine.py:59:from cryodaq.core.rate_estimator import RateEstimator
src/cryodaq/engine.py:61:from cryodaq.core.safety_manager import SafetyConfigError, SafetyManager
src/cryodaq/engine.py:94:    safety_manager: SafetyManager,
src/cryodaq/engine.py:96:    """Dispatch channel-scoped Keithley commands to SafetyManager."""
src/cryodaq/engine.py:865:    # Keithley driver (нужен для SafetyManager)
src/cryodaq/engine.py:872:    # SafetyManager — создаётся ПЕРВЫМ
src/cryodaq/engine.py:874:    safety_manager = SafetyManager(
src/cryodaq/engine.py:883:    # Phase 2b Codex H.1: merge legacy alarms.yaml/interlocks.yaml protection
src/cryodaq/engine.py:906:    # engine event loop and SafetyManager so a disk-full error in the
src/cryodaq/engine.py:908:    # The reverse hook (acknowledge_fault → clear writer flag) ensures
src/cryodaq/engine.py:966:    # Interlock Engine — действия делегируются SafetyManager.
src/cryodaq/engine.py:982:        # so this handler is the SOLE path that triggers a SafetyManager
src/cryodaq/engine.py:1037:        stale_timeout_s=30.0,
src/cryodaq/engine.py:1040:    _alarm_v2_rate = RateEstimator(
src/cryodaq/engine.py:1224:    # Обработчик команд от GUI — через SafetyManager
src/cryodaq/engine.py:1256:                return await safety_manager.acknowledge_fault(reason)
src/cryodaq/engine.py:1594:    logger.info("SafetyManager запущен: состояние=%s", safety_manager.state.value)
src/cryodaq/engine.py:1741:    logger.info("SafetyManager остановлен: состояние=%s", safety_manager.state.value)
src/cryodaq/engine.py:1947:            SafetyConfigError,
src/cryodaq/engine.py:1954:                SafetyConfigError: "safety",
src/cryodaq/core/safety_manager.py:1:"""SafetyManager for CryoDAQ."""
src/cryodaq/core/safety_manager.py:20:from cryodaq.core.rate_estimator import RateEstimator
src/cryodaq/core/safety_manager.py:31:class SafetyConfigError(RuntimeError):
src/cryodaq/core/safety_manager.py:41:    SAFE_OFF = "safe_off"
src/cryodaq/core/safety_manager.py:42:    READY = "ready"
src/cryodaq/core/safety_manager.py:43:    RUN_PERMITTED = "run_permitted"
src/cryodaq/core/safety_manager.py:45:    FAULT_LATCHED = "fault_latched"
src/cryodaq/core/safety_manager.py:62:    stale_timeout_s: float = 10.0
src/cryodaq/core/safety_manager.py:76:class SafetyManager:
src/cryodaq/core/safety_manager.py:93:        self._state = SafetyState.SAFE_OFF
src/cryodaq/core/safety_manager.py:100:        self._run_permitted_since: float = 0.0  # monotonic timestamp of RUN_PERMITTED entry
src/cryodaq/core/safety_manager.py:109:        self._rate_estimator = RateEstimator(window_s=120.0, min_points=60)
src/cryodaq/core/safety_manager.py:121:        # Hook called from acknowledge_fault to clear external persistence
src/cryodaq/core/safety_manager.py:138:            raise SafetyConfigError(
src/cryodaq/core/safety_manager.py:140:                f"SafetyManager without safety configuration"
src/cryodaq/core/safety_manager.py:147:            raise SafetyConfigError(
src/cryodaq/core/safety_manager.py:153:            raise SafetyConfigError(
src/cryodaq/core/safety_manager.py:158:            raise SafetyConfigError(
src/cryodaq/core/safety_manager.py:160:                f"refusing to start SafetyManager without critical channel monitoring"
src/cryodaq/core/safety_manager.py:175:            raise SafetyConfigError(
src/cryodaq/core/safety_manager.py:180:            raise SafetyConfigError(f"safety.yaml at {path} produced no valid critical_channels")
src/cryodaq/core/safety_manager.py:183:            "SafetyManager config: %d critical channel patterns from %s",
src/cryodaq/core/safety_manager.py:192:                stale_timeout_s=float(raw.get("stale_timeout_s", 10.0)),
src/cryodaq/core/safety_manager.py:212:            raise SafetyConfigError(
src/cryodaq/core/safety_manager.py:259:            if self._state == SafetyState.FAULT_LATCHED:
src/cryodaq/core/safety_manager.py:267:            if self._state not in (SafetyState.SAFE_OFF, SafetyState.READY, SafetyState.RUNNING):
src/cryodaq/core/safety_manager.py:317:                    SafetyState.RUN_PERMITTED,
src/cryodaq/core/safety_manager.py:325:                    self._transition(SafetyState.SAFE_OFF, "Keithley not connected")
src/cryodaq/core/safety_manager.py:350:                # emergency_off and latched FAULT_LATCHED. We must NOT add the
src/cryodaq/core/safety_manager.py:354:                if self._state == SafetyState.FAULT_LATCHED:
src/cryodaq/core/safety_manager.py:385:            if self._state == SafetyState.FAULT_LATCHED:
src/cryodaq/core/safety_manager.py:391:                    "error": "System is fault-latched - acknowledge_fault required",
src/cryodaq/core/safety_manager.py:410:            if self._state == SafetyState.FAULT_LATCHED:
src/cryodaq/core/safety_manager.py:421:                self._transition(SafetyState.SAFE_OFF, "Operator emergency off")
src/cryodaq/core/safety_manager.py:435:            if self._state == SafetyState.FAULT_LATCHED:
src/cryodaq/core/safety_manager.py:474:            if self._state == SafetyState.FAULT_LATCHED:
src/cryodaq/core/safety_manager.py:524:    async def acknowledge_fault(self, reason: str) -> dict[str, Any]:
src/cryodaq/core/safety_manager.py:526:            if self._state != SafetyState.FAULT_LATCHED:
src/cryodaq/core/safety_manager.py:559:        flags (Phase 2a H.1). Called from acknowledge_fault."""
src/cryodaq/core/safety_manager.py:650:        level = logging.CRITICAL if new_state == SafetyState.FAULT_LATCHED else logging.INFO
src/cryodaq/core/safety_manager.py:678:        # FAULT_LATCHED and exits.
src/cryodaq/core/safety_manager.py:679:        if self._state == SafetyState.FAULT_LATCHED:
src/cryodaq/core/safety_manager.py:689:        #    FAULT_LATCHED and reject before any yield point.
src/cryodaq/core/safety_manager.py:692:        self._transition(SafetyState.FAULT_LATCHED, reason, channel=channel, value=value)
src/cryodaq/core/safety_manager.py:771:        if self._state == SafetyState.FAULT_LATCHED:
src/cryodaq/core/safety_manager.py:807:        self._transition(SafetyState.SAFE_OFF, reason)
src/cryodaq/core/safety_manager.py:826:                if age > self._config.stale_timeout_s:
src/cryodaq/core/safety_manager.py:841:        if self._state == SafetyState.FAULT_LATCHED:
src/cryodaq/core/safety_manager.py:872:                self._transition(SafetyState.READY, "Recovery preconditions restored")
src/cryodaq/core/safety_manager.py:875:        if self._state == SafetyState.SAFE_OFF:
src/cryodaq/core/safety_manager.py:878:                self._transition(SafetyState.READY, "All preconditions satisfied")
src/cryodaq/core/safety_manager.py:881:        # Active monitoring states: RUN_PERMITTED (source starting) and
src/cryodaq/core/safety_manager.py:882:        # RUNNING (source on). Both need stale/rate/heartbeat checks because
src/cryodaq/core/safety_manager.py:884:        if self._state not in (SafetyState.RUN_PERMITTED, SafetyState.RUNNING):
src/cryodaq/core/safety_manager.py:889:                if pattern.match(ch) and now - ts > self._config.stale_timeout_s:
src/cryodaq/core/safety_manager.py:912:                self._state == SafetyState.RUN_PERMITTED
src/cryodaq/core/safety_manager.py:916:                # Stuck start_source(): sitting in RUN_PERMITTED longer than
src/cryodaq/core/safety_manager.py:919:                    f"start_source() stuck: RUN_PERMITTED for "
src/cryodaq/core/safety_manager.py:964:            Full fault latch — outputs off, FAULT_LATCHED, operator must
src/cryodaq/core/safety_manager.py:965:            acknowledge_fault to recover.
src/cryodaq/core/safety_manager.py:968:            Soft stop — outputs off, transition to SAFE_OFF, no fault latch.
src/cryodaq/core/safety_manager.py:1008:                if self._state not in (SafetyState.FAULT_LATCHED, SafetyState.MANUAL_RECOVERY):
src/cryodaq/core/safety_manager.py:1010:                        SafetyState.SAFE_OFF,
src/cryodaq/core/safety_manager.py:1037:        ``request_run`` callers will see ``FAULT_LATCHED`` and abort.
README.md:159:- `config/safety.yaml` — SafetyManager FSM timeouts, rate limits, drain timeout
README.md:162:- `config/interlocks.yaml` — interlock conditions and action mappings
README.md:163:- `config/channels.yaml` — channel display names, visibility, groupings
README.md:165:- `config/housekeeping.yaml` — data throttle, retention, compression
CLAUDE.md:95:SafetyManager is the single authority for source on/off decisions.
CLAUDE.md:100:  -> SafetyManager
CLAUDE.md:101:     States: SAFE_OFF -> READY -> RUN_PERMITTED -> RUNNING -> FAULT_LATCHED -> MANUAL_RECOVERY -> READY
CLAUDE.md:102:     Note: request_run() can shortcut SAFE_OFF -> RUNNING when all preconditions met
CLAUDE.md:103:     MANUAL_RECOVERY: entered after acknowledge_fault(), transitions to
CLAUDE.md:104:     READY when preconditions restore.
CLAUDE.md:105:     Fail-on-silence: stale data -> FAULT + emergency_off (fires only
CLAUDE.md:106:     while state=RUNNING; outside RUNNING, stale data blocks readiness
CLAUDE.md:178:- `src/cryodaq/core/channel_state.py` — per-channel state tracker for alarm evaluation (staleness, fault history)
CLAUDE.md:183:- `src/cryodaq/core/interlock.py` — threshold detection, delegates actions to SafetyManager
CLAUDE.md:324:- `config/interlocks.yaml`
CLAUDE.md:329:- `config/channels.yaml`
CLAUDE.md:332:- `config/housekeeping.yaml`
CLAUDE.md:345:- `SAFE_OFF` — состояние по умолчанию.
PROJECT_STATUS.md:20:| Coverage (full suite) | **66%** (stale — last measured 2026-04-17; re-run pending) |
PROJECT_STATUS.md:39:1. **SAFE_OFF** — состояние по умолчанию. Source ON = непрерывное доказательство здоровья.
PROJECT_STATUS.md:41:3. **SafetyState FSM:** 6 состояний — `SAFE_OFF → READY → RUN_PERMITTED → RUNNING → FAULT_LATCHED → MANUAL_RECOVERY → READY`.
PROJECT_STATUS.md:42:4. **Fail-on-silence:** stale data → FAULT (только в RUNNING; вне RUNNING блокирует readiness через preconditions).
PROJECT_STATUS.md:53:12. **Fail-closed config:** `safety.yaml`, `alarms_v3.yaml`, `interlocks.yaml`, `housekeeping.yaml`, `channels.yaml` → subsystem-specific `ConfigError` → engine exit code 2 (без auto-restart).
PROJECT_STATUS.md:59:18. **_fault() re-entry guard** (добавлен 2026-04-17): ранний `return` если `state == FAULT_LATCHED`, предотвращает overwrite `_fault_reason` + duplicate events / emergency_off при параллельных вызовах.
PROJECT_STATUS.md:67:                                       → SafetyBroker → SafetyManager
PROJECT_STATUS.md:97:**A1 safety audit (`eb267c4`, 2026-04-17).** Latin Т12 исправлен в `config/interlocks.yaml` (description + два поясняющих комментария; сам `channel_pattern` был исправлен ранее в `9feaf3e`). `_fault()` получил early-return guard против concurrent re-entries. XSS в `web/server.py`, fail-closed в `load_config()`, stuck RUN_PERMITTED — всё уже закрыто, отмечено NOT REPRODUCIBLE.
PROJECT_STATUS.md:154:10. Test isolation for stale reply consumers.
PROJECT_STATUS.md:233:5. **`_fault()` re-entry guard** — ранний return если state=`FAULT_LATCHED`, предотвращает race на concurrent вызовы (добавлен 2026-04-17).
PROJECT_STATUS.md:266:2. **Codex second-opinion** — независимый LLM-review committed diff. Ловит line-level семантику (wrong type, wrong API, wrong filter). Примеры Phase 2d: RUN_PERMITTED heartbeat gap (gated on `_active_sources` которая пустая в момент source start); `housekeeping.py` читает `alarms_v3.yaml:interlocks:` секцию, которую CC удалил как "dead config"; NaN vs ±inf IEEE 754 distinction (SQLite treats NaN as NULL).
src/cryodaq/launcher.py:339:                # Lock was free → stale file, proceed
src/cryodaq/launcher.py:917:            # when fresh subprocess immediately sees stale cmd_timeout.

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/core/safety_manager.py | sed -n '810,930p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   810	        if channel is not None:
   811	            return {normalize_smu_channel(channel)}
   812	        if self._active_sources:
   813	            return set(self._active_sources)
   814	        return {normalize_smu_channel(None)}
   815	
   816	    def _check_preconditions(self) -> tuple[bool, str]:
   817	        now = time.monotonic()
   818	
   819	        for pattern in self._config.critical_channels:
   820	            matched = False
   821	            for ch, (ts, value, status) in self._latest.items():
   822	                if not pattern.match(ch):
   823	                    continue
   824	                matched = True
   825	                age = now - ts
   826	                if age > self._config.stale_timeout_s:
   827	                    return False, f"Stale data: {ch} ({age:.1f}s)"
   828	                if status != "ok":
   829	                    return False, f"Channel {ch} status={status}"
   830	                if math.isnan(value) or math.isinf(value):
   831	                    return False, f"Channel {ch} invalid value {value}"
   832	            if not matched and not self._mock:
   833	                return False, f"No data for critical channel: {pattern.pattern}"
   834	
   835	        if self._config.require_keithley_for_run and not self._mock:
   836	            if self._keithley is None:
   837	                return False, "Keithley not connected"
   838	            if not getattr(self._keithley, "connected", False):
   839	                return False, "Keithley connected=False"
   840	
   841	        if self._state == SafetyState.FAULT_LATCHED:
   842	            return False, f"Active fault: {self._fault_reason}"
   843	
   844	        return True, ""
   845	
   846	    async def _collect_loop(self) -> None:
   847	        assert self._queue is not None
   848	        try:
   849	            while True:
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
   911	            elif (
   912	                self._state == SafetyState.RUN_PERMITTED
   913	                and self._run_permitted_since > 0
   914	                and now - self._run_permitted_since > self._config.heartbeat_timeout_s
   915	            ):
   916	                # Stuck start_source(): sitting in RUN_PERMITTED longer than
   917	                # heartbeat timeout without _active_sources being populated.
   918	                await self._fault(
   919	                    f"start_source() stuck: RUN_PERMITTED for "
   920	                    f">{self._config.heartbeat_timeout_s:.0f}s without source activation",
   921	                )
   922	                return
   923	
   924	        for ch in self._rate_estimator.channels():
   925	            if not any(pattern.match(ch) for pattern in self._config.critical_channels):
   926	                continue
   927	            rate = self._rate_estimator.get_rate(ch)
   928	            if rate is None:
   929	                continue
   930	            abs_rate = abs(rate)

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/core/safety_manager.py | sed -n '930,1045p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   930	            abs_rate = abs(rate)
   931	            if abs_rate > self._config.max_dT_dt_K_per_min:
   932	                await self._fault(
   933	                    f"Rate limit exceeded {ch}: {abs_rate:.2f} K/min > {self._config.max_dT_dt_K_per_min}",  # noqa: E501
   934	                    channel=ch,
   935	                    value=abs_rate,
   936	                )
   937	                return
   938	
   939	    def _has_fresh_keithley_data(self, now: float, smu_channel: SmuChannel) -> bool:
   940	        aliases = {smu_channel, smu_channel.replace("smu", "smu_")}
   941	        for channel, (ts, _value, status) in self._latest.items():
   942	            if status != "ok":
   943	                continue
   944	            if not any(pattern.match(channel) for pattern in self._keithley_patterns):
   945	                continue
   946	            if (
   947	                any(f"/{alias}/" in channel for alias in aliases)
   948	                and now - ts < self._config.heartbeat_timeout_s
   949	            ):
   950	                return True
   951	        return False
   952	
   953	    async def on_interlock_trip(
   954	        self,
   955	        interlock_name: str,
   956	        channel: str,
   957	        value: float,
   958	        *,
   959	        action: str = "emergency_off",
   960	    ) -> None:
   961	        """Handle an interlock trip from InterlockEngine.
   962	
   963	        ``action="emergency_off"`` (default, backwards-compatible):
   964	            Full fault latch — outputs off, FAULT_LATCHED, operator must
   965	            acknowledge_fault to recover.
   966	
   967	        ``action="stop_source"``:
   968	            Soft stop — outputs off, transition to SAFE_OFF, no fault latch.
   969	            Operator can call ``request_run`` again as soon as the underlying
   970	            condition (e.g. detector_warmup) clears.
   971	
   972	        Any other action escalates to a full fault as the safe default.
   973	
   974	        See DEEP_AUDIT_CODEX.md I.1.
   975	        """
   976	        reason = f"Interlock '{interlock_name}' tripped: channel={channel}, value={value:.4g}"
   977	
   978	        if action == "emergency_off":
   979	            logger.critical("INTERLOCK emergency_off: %s", reason)
   980	            await self._fault(reason, channel=channel, value=value)
   981	            return
   982	
   983	        if action == "stop_source":
   984	            logger.warning("INTERLOCK stop_source: %s", reason)
   985	            # Soft stop: outputs off, no fault latch.
   986	            async with self._cmd_lock:
   987	                if self._keithley is not None:
   988	                    try:
   989	                        await self._keithley.emergency_off()
   990	                    except Exception as exc:
   991	                        logger.error(
   992	                            "stop_source interlock: emergency_off failed: %s — "
   993	                            "escalating to full fault",
   994	                            exc,
   995	                        )
   996	                        # The lock is released when this `async with` block
   997	                        # exits via the `return` below. _fault itself is
   998	                        # unlocked, so it does not deadlock — but it WILL
   999	                        # serialize behind the lock until _fault returns.
  1000	                        await self._fault(
  1001	                            f"{reason} (emergency_off failed: {exc})",
  1002	                            channel=channel,
  1003	                            value=value,
  1004	                        )
  1005	                        return
  1006	                self._active_sources.clear()
  1007	                await self._publish_keithley_channel_states(f"interlock_stop:{interlock_name}")
  1008	                if self._state not in (SafetyState.FAULT_LATCHED, SafetyState.MANUAL_RECOVERY):
  1009	                    self._transition(
  1010	                        SafetyState.SAFE_OFF,
  1011	                        f"Interlock stop_source: {interlock_name}",
  1012	                        channel=channel,
  1013	                        value=value,
  1014	                    )
  1015	            return
  1016	
  1017	        # Unknown action — fail-safe to a full fault rather than ignore.
  1018	        logger.critical(
  1019	            "Unknown interlock action %r for '%s' — escalating to full fault",
  1020	            action,
  1021	            interlock_name,
  1022	        )
  1023	        await self._fault(
  1024	            f"Unknown interlock action {action!r}: {reason}",
  1025	            channel=channel,
  1026	            value=value,
  1027	        )
  1028	
  1029	    async def on_persistence_failure(self, reason: str) -> None:
  1030	        """Called by SQLiteWriter when persistent storage fails (disk full etc).
  1031	
  1032	        Immediately triggers ``_fault`` with a persistence-failure reason.
  1033	        ``_fault`` is intentionally NOT wrapped in ``_cmd_lock`` so this can
  1034	        be called from any context (including the writer thread via
  1035	        :func:`asyncio.run_coroutine_threadsafe`). The fault path itself
  1036	        latches the state synchronously before any await, so concurrent
  1037	        ``request_run`` callers will see ``FAULT_LATCHED`` and abort.
  1038	        """
  1039	        logger.critical("PERSISTENCE FAILURE: %s — triggering safety fault", reason)
  1040	        await self._fault(
  1041	            f"Persistence failure: {reason}",
  1042	            channel="",
  1043	            value=0.0,
  1044	        )

codex
- **CRITICAL / `10 Subsystems/Safety FSM.md:59` / `src/cryodaq/core/safety_manager.py:881` / proposed fix:** change “emergency-off only while `state == RUNNING`” to “active monitoring faults fire in `RUN_PERMITTED` and `RUNNING`; outside those states stale data blocks readiness.” Current code explicitly monitors both `RUN_PERMITTED` and `RUNNING` so stuck `start_source()` cannot disable checks.

- **MEDIUM / `10 Subsystems/Safety FSM.md:51` / `src/cryodaq/core/safety_manager.py:314` / proposed fix:** replace “shortcut `SAFE_OFF → RUNNING`” with “may skip `READY`, but still records `RUN_PERMITTED` before `RUNNING`.” Code transitions to `RUN_PERMITTED` at lines 314-321, then `RUNNING` at 366-370.

- **MEDIUM / `10 Subsystems/Persistence-first.md:23` / `src/cryodaq/storage/sqlite_writer.py:256` / proposed fix:** add the explicit durability caveat: SQLite uses `synchronous=NORMAL` by default, which source comments say can lose the last ~1 s on power loss; production requires UPS or `CRYODAQ_SQLITE_SYNC=FULL`. “Durable storage” is otherwise overstated.

- **CRITICAL / `10 Subsystems/Calibration v2.md:61` / `src/cryodaq/analytics/calibration.py:400` / proposed fix:** replace `CalibrationCurve.export(format)` and the “four targets” list. Source exposes `CalibrationStore.export_curve_json`, `export_curve_table` CSV, `export_curve_330`, and `export_curve_340`; there is no `CalibrationCurve.export(format)` API and no `.cof` support in the declared sources.

- **HIGH / `10 Subsystems/Calibration v2.md:49` / `src/cryodaq/analytics/calibration_fitter.py:346` / proposed fix:** do not say breakpoints identify Chebyshev zone boundaries. `generate_breakpoints()` is used for breakpoint/export/inspection output; the Chebyshev fit is delegated to `CalibrationStore.fit_curve()` at lines 366-372, which detects zones internally.

- **LOW / `10 Subsystems/Alarm engine v2.md:56` / `src/cryodaq/core/alarm_providers.py:1` / proposed fix:** path is wrong. Change `config/alarm_providers.py` to `src/cryodaq/core/alarm_providers.py`.

- **HIGH / `10 Subsystems/Alarm engine v2.md:84` / `ROADMAP.md:566` / proposed fix:** “drop the spurious field” is the wrong config-side candidate. Source says the issue is a missing `threshold` field, with mini-fix as `cond.get("threshold")` defensive access or config audit. Rephrase to “audit/add the required threshold or change the condition type; alternatively guard with `cond.get(...)`.”

- **CRITICAL / `10 Subsystems/Plugin architecture.md:91` / `src/cryodaq/analytics/plugin_loader.py:266` / proposed fix:** remove SQLite from “downstream consumers treat derived metrics uniformly.” `PluginPipeline` publishes synthetic readings to `DataBroker`; current writer is started in immediate mode from `Scheduler`, not as a broker subscriber. Say “live broker consumers such as GUI/web/ZMQ/alarm subscribers,” unless persistence is later wired.

- **HIGH / `10 Subsystems/Plugin architecture.md:104` / `config/plugins.yaml:1` / proposed fix:** “Plugins NOT ENABLED by default” contradicts current config: `sensor_diagnostics.enabled: true` and `vacuum_trend.enabled: true`. Also hot-reload files in `plugins_dir` are loaded unconditionally by `PluginPipeline.start()` (`plugin_loader.py:88`). Clarify the distinction between shipped analytics feature flags and filesystem plugin loading.

- **CRITICAL / `30 Investigations/Plugin isolation rebuild.md:70` / `src/cryodaq/analytics/plugin_loader.py:266` / proposed fix:** same SQLite overclaim as above. Returned metrics are republished to `DataBroker` as synthetic `Reading`s; source does not show them being persisted by SQLite.

- **CRITICAL / `40 Decisions/ADR-003 Plugin isolation via ABC.md:59` / `src/cryodaq/analytics/plugin_loader.py:266` / proposed fix:** same SQLite overclaim. Change consequence to “broker consumers can handle analytics output as `Reading`s”; do not include SQLite unless persistence is implemented.

- **CRITICAL / `20 Drivers/Keithley 2604B.md:17` / `src/cryodaq/core/smu_channel.py:5` / proposed fix:** remove “combined mode `smua + smub` is also supported.” The channel type is `Literal["smua", "smub"]`; `normalize_smu_channel()` rejects anything else. Both channels can be controlled independently, and `emergency_off(channel=None)` covers both.

- **HIGH / `20 Drivers/Keithley 2604B.md:45` / `src/cryodaq/drivers/instruments/keithley_2604b.py:170` / proposed fix:** “notifies `SafetyManager`” is not supported by current code. The driver increments `_compliance_count`, logs warnings, sets metadata, and exposes `compliance_persistent()` at line 350; no SafetyManager notification path is wired in the cited sources.

- **CRITICAL / `20 Drivers/Thyracont VSP63D.md:38` / `src/cryodaq/drivers/instruments/thyracont_vsp63d.py:120` / proposed fix:** probe order is wrong. Code tries Protocol V1 first at each baudrate, then MV00, then closes and falls back to the alternate baudrate. Replace the numbered sequence accordingly.

- **MEDIUM / `20 Drivers/Thyracont VSP63D.md:57` / `src/cryodaq/drivers/instruments/thyracont_vsp63d.py:343` / proposed fix:** checksum failure does not “drop the reading”; it returns a `Reading` with `value=NaN`, `status=SENSOR_ERROR`, and checksum metadata. Rephrase to avoid implying no reading object is emitted.

- **MEDIUM / `40 Decisions/ADR-001 Persistence-first invariant.md:15` / `src/cryodaq/storage/sqlite_writer.py:256` / proposed fix:** same durability caveat as the subsystem page. Add that default WAL `synchronous=NORMAL` can lose the last ~1 s on power loss, and FULL sync is available through `CRYODAQ_SQLITE_SYNC=FULL`.

- **MEDIUM / `50 Workflow/ORCHESTRATION contract.md:72` / `docs/ORCHESTRATION.md:260` / proposed fix:** root whitelist digest omits `DOC_REALITY_MAP.md`, which the authoritative source includes as historical/may be removed. Add it or say the list is abbreviated.

Verdict: **FAIL**. The synthesis layer is mostly directionally aligned, but there are several line-level contradictions against current code/API surfaces, especially plugin persistence, calibration export API, safety monitoring state, Keithley channel support, and Thyracont probe order.
tokens used
258 765
- **CRITICAL / `10 Subsystems/Safety FSM.md:59` / `src/cryodaq/core/safety_manager.py:881` / proposed fix:** change “emergency-off only while `state == RUNNING`” to “active monitoring faults fire in `RUN_PERMITTED` and `RUNNING`; outside those states stale data blocks readiness.” Current code explicitly monitors both `RUN_PERMITTED` and `RUNNING` so stuck `start_source()` cannot disable checks.

- **MEDIUM / `10 Subsystems/Safety FSM.md:51` / `src/cryodaq/core/safety_manager.py:314` / proposed fix:** replace “shortcut `SAFE_OFF → RUNNING`” with “may skip `READY`, but still records `RUN_PERMITTED` before `RUNNING`.” Code transitions to `RUN_PERMITTED` at lines 314-321, then `RUNNING` at 366-370.

- **MEDIUM / `10 Subsystems/Persistence-first.md:23` / `src/cryodaq/storage/sqlite_writer.py:256` / proposed fix:** add the explicit durability caveat: SQLite uses `synchronous=NORMAL` by default, which source comments say can lose the last ~1 s on power loss; production requires UPS or `CRYODAQ_SQLITE_SYNC=FULL`. “Durable storage” is otherwise overstated.

- **CRITICAL / `10 Subsystems/Calibration v2.md:61` / `src/cryodaq/analytics/calibration.py:400` / proposed fix:** replace `CalibrationCurve.export(format)` and the “four targets” list. Source exposes `CalibrationStore.export_curve_json`, `export_curve_table` CSV, `export_curve_330`, and `export_curve_340`; there is no `CalibrationCurve.export(format)` API and no `.cof` support in the declared sources.

- **HIGH / `10 Subsystems/Calibration v2.md:49` / `src/cryodaq/analytics/calibration_fitter.py:346` / proposed fix:** do not say breakpoints identify Chebyshev zone boundaries. `generate_breakpoints()` is used for breakpoint/export/inspection output; the Chebyshev fit is delegated to `CalibrationStore.fit_curve()` at lines 366-372, which detects zones internally.

- **LOW / `10 Subsystems/Alarm engine v2.md:56` / `src/cryodaq/core/alarm_providers.py:1` / proposed fix:** path is wrong. Change `config/alarm_providers.py` to `src/cryodaq/core/alarm_providers.py`.

- **HIGH / `10 Subsystems/Alarm engine v2.md:84` / `ROADMAP.md:566` / proposed fix:** “drop the spurious field” is the wrong config-side candidate. Source says the issue is a missing `threshold` field, with mini-fix as `cond.get("threshold")` defensive access or config audit. Rephrase to “audit/add the required threshold or change the condition type; alternatively guard with `cond.get(...)`.”

- **CRITICAL / `10 Subsystems/Plugin architecture.md:91` / `src/cryodaq/analytics/plugin_loader.py:266` / proposed fix:** remove SQLite from “downstream consumers treat derived metrics uniformly.” `PluginPipeline` publishes synthetic readings to `DataBroker`; current writer is started in immediate mode from `Scheduler`, not as a broker subscriber. Say “live broker consumers such as GUI/web/ZMQ/alarm subscribers,” unless persistence is later wired.

- **HIGH / `10 Subsystems/Plugin architecture.md:104` / `config/plugins.yaml:1` / proposed fix:** “Plugins NOT ENABLED by default” contradicts current config: `sensor_diagnostics.enabled: true` and `vacuum_trend.enabled: true`. Also hot-reload files in `plugins_dir` are loaded unconditionally by `PluginPipeline.start()` (`plugin_loader.py:88`). Clarify the distinction between shipped analytics feature flags and filesystem plugin loading.

- **CRITICAL / `30 Investigations/Plugin isolation rebuild.md:70` / `src/cryodaq/analytics/plugin_loader.py:266` / proposed fix:** same SQLite overclaim as above. Returned metrics are republished to `DataBroker` as synthetic `Reading`s; source does not show them being persisted by SQLite.

- **CRITICAL / `40 Decisions/ADR-003 Plugin isolation via ABC.md:59` / `src/cryodaq/analytics/plugin_loader.py:266` / proposed fix:** same SQLite overclaim. Change consequence to “broker consumers can handle analytics output as `Reading`s”; do not include SQLite unless persistence is implemented.

- **CRITICAL / `20 Drivers/Keithley 2604B.md:17` / `src/cryodaq/core/smu_channel.py:5` / proposed fix:** remove “combined mode `smua + smub` is also supported.” The channel type is `Literal["smua", "smub"]`; `normalize_smu_channel()` rejects anything else. Both channels can be controlled independently, and `emergency_off(channel=None)` covers both.

- **HIGH / `20 Drivers/Keithley 2604B.md:45` / `src/cryodaq/drivers/instruments/keithley_2604b.py:170` / proposed fix:** “notifies `SafetyManager`” is not supported by current code. The driver increments `_compliance_count`, logs warnings, sets metadata, and exposes `compliance_persistent()` at line 350; no SafetyManager notification path is wired in the cited sources.

- **CRITICAL / `20 Drivers/Thyracont VSP63D.md:38` / `src/cryodaq/drivers/instruments/thyracont_vsp63d.py:120` / proposed fix:** probe order is wrong. Code tries Protocol V1 first at each baudrate, then MV00, then closes and falls back to the alternate baudrate. Replace the numbered sequence accordingly.

- **MEDIUM / `20 Drivers/Thyracont VSP63D.md:57` / `src/cryodaq/drivers/instruments/thyracont_vsp63d.py:343` / proposed fix:** checksum failure does not “drop the reading”; it returns a `Reading` with `value=NaN`, `status=SENSOR_ERROR`, and checksum metadata. Rephrase to avoid implying no reading object is emitted.

- **MEDIUM / `40 Decisions/ADR-001 Persistence-first invariant.md:15` / `src/cryodaq/storage/sqlite_writer.py:256` / proposed fix:** same durability caveat as the subsystem page. Add that default WAL `synchronous=NORMAL` can lose the last ~1 s on power loss, and FULL sync is available through `CRYODAQ_SQLITE_SYNC=FULL`.

- **MEDIUM / `50 Workflow/ORCHESTRATION contract.md:72` / `docs/ORCHESTRATION.md:260` / proposed fix:** root whitelist digest omits `DOC_REALITY_MAP.md`, which the authoritative source includes as historical/may be removed. Add it or say the list is abbreviated.

Verdict: **FAIL**. The synthesis layer is mostly directionally aligned, but there are several line-level contradictions against current code/API surfaces, especially plugin persistence, calibration export API, safety monitoring state, Keithley channel support, and Thyracont probe order.
