OpenAI Codex v0.124.0 (research preview)
--------
workdir: /Users/vladimir/Projects/cryodaq
model: gpt-5.5
provider: openai
approval: never
sandbox: read-only
reasoning effort: medium
reasoning summaries: none
session id: 019ddab5-537f-7fe2-8197-50fc07759218
--------
user
commit 535cc95: F28 Cycle 2: GemmaAgent service + Slice A alarm flow
exec
/opt/homebrew/bin/bash -lc "cat /Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6807e4de/skills/using-superpowers/SKILL.md && printf '\\n---\\n' && cat /Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6807e4de/skills/requesting-code-review/SKILL.md" in /Users/vladimir/Projects/cryodaq
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

exec
/opt/homebrew/bin/bash -lc 'git status --short && git rev-parse --show-toplevel && git show --stat --oneline --decorate=short 535cc95 && git show --find-renames --find-copies --stat --name-only --format=fuller 535cc95' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
?? CC_PROMPT_CALIBRATION_2026-04-30.md
?? CC_PROMPT_DOCS_AUDIT_REWRITE_2026-04-30.md
?? CC_PROMPT_DOCS_REWRITE_PHASE2_2026-04-30.md
?? CC_PROMPT_F28_CYCLE0_MULTI_AUDIT_2026-05-01.md
?? CC_PROMPT_F28_HERMES_AGENT.md
?? CC_PROMPT_METASWARM_F17.md
?? CC_PROMPT_OVERNIGHT_2026-04-30.md
?? CC_PROMPT_OVERNIGHT_2026-05-01.md
?? CC_PROMPT_PARALLEL_WORK_2026-05-01.md
?? CC_PROMPT_REPO_CLEANUP_2026-04-30.md
?? artifacts/calibration/2026-05-01-f28-cycle2/
?? artifacts/consultations/2026-04-29-f10-cycle1/
?? artifacts/consultations/2026-04-29-f10-cycle2/
?? artifacts/consultations/2026-04-29-f10-cycle3/
?? artifacts/consultations/2026-04-29-f3-cycle1/
?? artifacts/consultations/2026-04-29-f3-cycle2/
?? artifacts/consultations/2026-04-29-f3-cycle3/
?? artifacts/consultations/2026-04-29-metaswarm/
?? artifacts/consultations/2026-04-30/
?? artifacts/consultations/2026-05-01-overnight-f17/
?? artifacts/consultations/2026-05-01-overnight-f26/
?? artifacts/handoffs/2026-04-29-f10-cycle1-handoff.md
?? artifacts/handoffs/2026-04-29-f10-cycle2-handoff.md
?? artifacts/handoffs/2026-04-29-f10-cycle3-handoff.md
?? artifacts/handoffs/2026-04-29-f28-cycle0-handoff.md
?? artifacts/handoffs/2026-04-29-hf1-hf2-review.md
?? artifacts/handoffs/2026-04-29-metaswarm-summary.md
?? artifacts/handoffs/2026-04-29-overnight-summary.md
?? artifacts/handoffs/2026-04-29-task-a-verification.md
?? artifacts/handoffs/2026-05-01-f26-handoff.md
?? draft.py
?? draft2.py
?? release_notes.py
/Users/vladimir/Projects/cryodaq
535cc95 (HEAD -> feat/f28-hermes-agent) feat(f28): Cycle 2 — GemmaAgent service + alarm summary (Slice A)
 config/agent.yaml                     |  39 +++++
 src/cryodaq/agents/gemma.py           | 291 ++++++++++++++++++++++++++++++++
 src/cryodaq/agents/output_router.py   | 102 +++++++++++
 src/cryodaq/agents/prompts.py         |  83 +++++++++
 src/cryodaq/engine.py                 |  63 ++++++-
 tests/agents/test_gemma_alarm_flow.py | 307 ++++++++++++++++++++++++++++++++++
 6 files changed, 881 insertions(+), 4 deletions(-)
commit 535cc95a0491bf31f94be7936e419645a15a40d7
Author:     Vladimir Fomenko <polsovatel111@gmail.com>
AuthorDate: Wed Apr 29 22:25:04 2026 +0300
Commit:     Vladimir Fomenko <polsovatel111@gmail.com>
CommitDate: Wed Apr 29 22:25:04 2026 +0300

    feat(f28): Cycle 2 — GemmaAgent service + alarm summary (Slice A)
    
    Pre-Cycle-2 fixes (from Cycle 0 ledger):
    - Swap phase_transition/event_logged order: phase_transition now
      published BEFORE event_logger.log_event() in advance_phase handler
    - Distinct event_types: experiment_stop/experiment_finalize/experiment_abort
      now each produce their own event_type string (was: all non-abort
      mapped to "experiment_finalize")
    
    New files:
    - agents/gemma.py: GemmaAgent service class (Гемма). Subscribes to
      EventBus, handles alarm_fired events (Slice A). Rate limiting:
      Semaphore(2) concurrent + 60/hr hourly bucket. Graceful Ollama
      failure: warns + skips, engine unaffected. GemmaConfig.from_dict()
      loads from agent.yaml.
    - agents/prompts.py: Russian-language prompt templates. ALARM_SUMMARY_
      SYSTEM + ALARM_SUMMARY_USER per spec §2.6. Versioned with revision notes.
    - agents/output_router.py: OutputRouter dispatches to Telegram/_send_to_all,
      operator_log via event_logger.log_event(tag=gemma), GUI insight via
      EventBus(gemma_insight). "🤖 Гемма:" prefix on all outputs.
    - config/agent.yaml: gemma config (enabled=true, gemma4:e4b, rate limits,
      slice toggles, audit settings).
    
    Engine wiring: GemmaAgent instantiated from agent.yaml, started after
    TelegramCommandBot, stopped before it in shutdown sequence. Failure to
    start = warn + disable (engine continues).
    
    Tests: 15 new tests in test_gemma_alarm_flow.py. Covers start/stop,
    alarm_fired → Ollama → Telegram + log dispatch, INFO level filter,
    CRITICAL level handling, OllamaUnavailable resilience, rate limiting,
    helper functions.
    
    Cycle 2 milestone: alarm fires → Гемма generates Russian summary →
    Telegram + operator log entry. Slice A first task working end-to-end.
    
    Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

config/agent.yaml
src/cryodaq/agents/gemma.py
src/cryodaq/agents/output_router.py
src/cryodaq/agents/prompts.py
src/cryodaq/engine.py
tests/agents/test_gemma_alarm_flow.py

exec
/opt/homebrew/bin/bash -lc 'git show --find-renames --format= --unified=80 535cc95 -- src/cryodaq/agents/gemma.py src/cryodaq/agents/output_router.py src/cryodaq/engine.py config/agent.yaml tests/agents/test_gemma_alarm_flow.py' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
diff --git a/config/agent.yaml b/config/agent.yaml
new file mode 100644
index 0000000..23b694f
--- /dev/null
+++ b/config/agent.yaml
@@ -0,0 +1,39 @@
+gemma:
+  enabled: true
+
+  ollama:
+    base_url: http://localhost:11434
+    default_model: gemma4:e4b
+    timeout_s: 30
+    temperature: 0.3
+
+  triggers:
+    alarm_fired:
+      enabled: true
+      min_level: WARNING
+    experiment_finalize:
+      enabled: true
+    sensor_anomaly_critical:
+      enabled: true
+    shift_handover_request:
+      enabled: true
+    phase_transition_to_finalize:
+      enabled: true
+
+  outputs:
+    telegram: true
+    operator_log: true
+    gui_insight_panel: true
+
+  rate_limit:
+    max_calls_per_hour: 60
+    max_concurrent_inferences: 2
+
+  slices:
+    a_notification: true
+    b_suggestion: false
+    c_campaign_report: false
+
+  audit:
+    enabled: true
+    retention_days: 90
diff --git a/src/cryodaq/agents/gemma.py b/src/cryodaq/agents/gemma.py
new file mode 100644
index 0000000..da4cb49
--- /dev/null
+++ b/src/cryodaq/agents/gemma.py
@@ -0,0 +1,291 @@
+"""GemmaAgent — local LLM agent observing engine events.
+
+Service named Гемма (after the underlying Gemma 4 model via Ollama).
+Subscribes to EventBus, generates Russian-language operator insights,
+dispatches to Telegram + operator log + GUI insight panel.
+
+Constraints (ORCHESTRATION v1.3 §13):
+- NEVER executes engine commands or modifies engine state.
+- Text-only output channels (Telegram, log, GUI).
+- Fails gracefully if Ollama is unavailable — engine continues.
+"""
+
+from __future__ import annotations
+
+import asyncio
+import logging
+import time
+from collections import deque
+from dataclasses import dataclass, field
+from pathlib import Path
+from typing import Any
+
+from cryodaq.agents.audit import AuditLogger
+from cryodaq.agents.context_builder import ContextBuilder
+from cryodaq.agents.ollama_client import (
+    OllamaClient,
+    OllamaModelMissingError,
+    OllamaUnavailableError,
+)
+from cryodaq.agents.output_router import OutputRouter, OutputTarget
+from cryodaq.agents.prompts import ALARM_SUMMARY_SYSTEM, ALARM_SUMMARY_USER
+from cryodaq.core.event_bus import EngineEvent, EventBus
+
+logger = logging.getLogger(__name__)
+
+_MIN_LEVELS = {"INFO": 0, "WARNING": 1, "CRITICAL": 2}
+
+
+@dataclass
+class GemmaConfig:
+    enabled: bool = True
+    ollama_base_url: str = "http://localhost:11434"
+    default_model: str = "gemma4:e4b"
+    timeout_s: float = 30.0
+    temperature: float = 0.3
+    max_tokens: int = 1024
+    max_concurrent_inferences: int = 2
+    max_calls_per_hour: int = 60
+    alarm_min_level: str = "WARNING"
+    slice_a_notification: bool = True
+    slice_b_suggestion: bool = False
+    slice_c_campaign_report: bool = False
+    output_telegram: bool = True
+    output_operator_log: bool = True
+    output_gui_insight: bool = True
+    audit_enabled: bool = True
+    audit_retention_days: int = 90
+    audit_dir: Path = field(default_factory=lambda: Path("data/agents/gemma/audit"))
+
+    @classmethod
+    def from_dict(cls, d: dict[str, Any]) -> GemmaConfig:
+        """Build from agent.yaml gemma section dict."""
+        cfg = cls()
+        cfg.enabled = bool(d.get("enabled", True))
+        ollama = d.get("ollama", {})
+        cfg.ollama_base_url = str(ollama.get("base_url", cfg.ollama_base_url))
+        cfg.default_model = str(ollama.get("default_model", cfg.default_model))
+        cfg.timeout_s = float(ollama.get("timeout_s", cfg.timeout_s))
+        cfg.temperature = float(ollama.get("temperature", cfg.temperature))
+        rl = d.get("rate_limit", {})
+        cfg.max_calls_per_hour = int(rl.get("max_calls_per_hour", cfg.max_calls_per_hour))
+        cfg.max_concurrent_inferences = int(
+            rl.get("max_concurrent_inferences", cfg.max_concurrent_inferences)
+        )
+        triggers = d.get("triggers", {})
+        alarm_t = triggers.get("alarm_fired", {})
+        if isinstance(alarm_t, dict):
+            cfg.alarm_min_level = str(alarm_t.get("min_level", cfg.alarm_min_level))
+        outputs = d.get("outputs", {})
+        cfg.output_telegram = bool(outputs.get("telegram", cfg.output_telegram))
+        cfg.output_operator_log = bool(outputs.get("operator_log", cfg.output_operator_log))
+        cfg.output_gui_insight = bool(outputs.get("gui_insight_panel", cfg.output_gui_insight))
+        slices = d.get("slices", {})
+        cfg.slice_a_notification = bool(slices.get("a_notification", cfg.slice_a_notification))
+        cfg.slice_b_suggestion = bool(slices.get("b_suggestion", cfg.slice_b_suggestion))
+        cfg.slice_c_campaign_report = bool(
+            slices.get("c_campaign_report", cfg.slice_c_campaign_report)
+        )
+        audit = d.get("audit", {})
+        cfg.audit_enabled = bool(audit.get("enabled", cfg.audit_enabled))
+        cfg.audit_retention_days = int(audit.get("retention_days", cfg.audit_retention_days))
+        return cfg
+
+
+class GemmaAgent:
+    """Local LLM agent. Operator-facing brand: Гемма."""
+
+    def __init__(
+        self,
+        *,
+        config: GemmaConfig,
+        event_bus: EventBus,
+        ollama_client: OllamaClient,
+        context_builder: ContextBuilder,
+        audit_logger: AuditLogger,
+        output_router: OutputRouter,
+    ) -> None:
+        self._config = config
+        self._bus = event_bus
+        self._ollama = ollama_client
+        self._ctx_builder = context_builder
+        self._audit = audit_logger
+        self._router = output_router
+
+        self._semaphore = asyncio.Semaphore(config.max_concurrent_inferences)
+        self._call_timestamps: deque[float] = deque()
+        self._task: asyncio.Task[None] | None = None
+        self._queue: asyncio.Queue[EngineEvent] | None = None
+
+    async def start(self) -> None:
+        """Subscribe to EventBus and begin event processing."""
+        if not self._config.enabled:
+            logger.info("GemmaAgent (Гемма): отключён в конфигурации")
+            return
+        self._queue = await self._bus.subscribe("gemma_agent", maxsize=1000)
+        self._task = asyncio.create_task(self._event_loop(), name="gemma_agent")
+        logger.info(
+            "GemmaAgent (Гемма): запущен. Модель=%s, timeout=%.0fs",
+            self._config.default_model,
+            self._config.timeout_s,
+        )
+
+    async def stop(self) -> None:
+        """Cancel the event loop and release resources."""
+        if self._task is not None:
+            self._task.cancel()
+            try:
+                await self._task
+            except asyncio.CancelledError:
+                pass
+            self._task = None
+        if self._queue is not None:
+            self._bus.unsubscribe("gemma_agent")
+            self._queue = None
+        await self._ollama.close()
+        logger.info("GemmaAgent (Гемма): остановлен")
+
+    async def _event_loop(self) -> None:
+        """Drain the EventBus queue and dispatch handlers."""
+        assert self._queue is not None
+        while True:
+            try:
+                event = await self._queue.get()
+                if self._should_handle(event):
+                    asyncio.create_task(
+                        self._safe_handle(event),
+                        name=f"gemma_{event.event_type}",
+                    )
+            except asyncio.CancelledError:
+                return
+            except Exception:
+                logger.warning("GemmaAgent: event loop error", exc_info=True)
+
+    def _should_handle(self, event: EngineEvent) -> bool:
+        if not self._config.slice_a_notification:
+            return False
+        if event.event_type == "alarm_fired":
+            level = event.payload.get("level", "INFO")
+            return _MIN_LEVELS.get(level, 0) >= _MIN_LEVELS.get(
+                self._config.alarm_min_level, 1
+            )
+        return False  # experiment_finalize and phase_transition handled in Cycle 3
+
+    def _check_rate_limit(self) -> bool:
+        """True if we can make a call now (hourly bucket)."""
+        now = time.monotonic()
+        cutoff = now - 3600.0
+        while self._call_timestamps and self._call_timestamps[0] < cutoff:
+            self._call_timestamps.popleft()
+        return len(self._call_timestamps) < self._config.max_calls_per_hour
+
+    async def _safe_handle(self, event: EngineEvent) -> None:
+        """Handle one event with rate-limit + semaphore + error isolation."""
+        if not self._check_rate_limit():
+            logger.warning(
+                "GemmaAgent: rate limit reached (%d/hr), dropping %s",
+                self._config.max_calls_per_hour,
+                event.event_type,
+            )
+            return
+
+        async with self._semaphore:
+            self._call_timestamps.append(time.monotonic())
+            try:
+                await self._handle_alarm_fired(event)
+            except (OllamaUnavailableError, OllamaModelMissingError) as exc:
+                logger.warning("GemmaAgent: Ollama недоступен — %s", exc)
+            except Exception:
+                logger.warning(
+                    "GemmaAgent: ошибка обработки %s", event.event_type, exc_info=True
+                )
+
+    async def _handle_alarm_fired(self, event: EngineEvent) -> None:
+        audit_id = self._audit.make_audit_id()
+        payload = event.payload
+
+        ctx = await self._ctx_builder.build_alarm_context(payload)
+        channels_str = ", ".join(ctx.channels) if ctx.channels else "—"
+        values_str = ", ".join(f"{k}={v}" for k, v in ctx.values.items()) if ctx.values else "—"
+        age_str = _format_age(ctx.experiment_age_s)
+
+        user_prompt = ALARM_SUMMARY_USER.format(
+            alarm_id=ctx.alarm_id,
+            level=ctx.level,
+            channels=channels_str,
+            values=values_str,
+            phase=ctx.phase or "—",
+            experiment_id=ctx.experiment_id or "—",
+            experiment_age=age_str,
+            target_temp=ctx.target_temp if ctx.target_temp is not None else "—",
+            interlocks=", ".join(ctx.active_interlocks) if ctx.active_interlocks else "нет",
+            lookback_s=60,
+            recent_readings=ctx.recent_readings_text,
+            recent_alarms=ctx.recent_alarms_text,
+        )
+
+        result = await self._ollama.generate(
+            user_prompt,
+            system=ALARM_SUMMARY_SYSTEM,
+            max_tokens=self._config.max_tokens,
+            temperature=self._config.temperature,
+        )
+
+        errors: list[str] = []
+        if result.truncated:
+            errors.append("timeout_truncated")
+            logger.warning("GemmaAgent: ответ обрезан по таймауту (audit_id=%s)", audit_id)
+
+        targets = _build_targets(self._config)
+        dispatched = await self._router.dispatch(
+            event, result.text, targets=targets, audit_id=audit_id
+        )
+
+        await self._audit.log(
+            audit_id=audit_id,
+            trigger_event={
+                "event_type": event.event_type,
+                "payload": payload,
+                "experiment_id": event.experiment_id,
+            },
+            context_assembled=user_prompt,
+            prompt_template="alarm_summary",
+            model=result.model,
+            system_prompt=ALARM_SUMMARY_SYSTEM,
+            user_prompt=user_prompt,
+            response=result.text,
+            tokens={"in": result.tokens_in, "out": result.tokens_out},
+            latency_s=result.latency_s,
+            outputs_dispatched=dispatched,
+            errors=errors,
+        )
+
+        logger.info(
+            "GemmaAgent: alarm_fired обработан (audit_id=%s, latency=%.1fs, dispatched=%s)",
+            audit_id,
+            result.latency_s,
+            dispatched,
+        )
+
+
+def _build_targets(config: GemmaConfig) -> list[OutputTarget]:
+    targets = []
+    if config.output_telegram:
+        targets.append(OutputTarget.TELEGRAM)
+    if config.output_operator_log:
+        targets.append(OutputTarget.OPERATOR_LOG)
+    if config.output_gui_insight:
+        targets.append(OutputTarget.GUI_INSIGHT)
+    return targets
+
+
+def _format_age(age_s: float | None) -> str:
+    if age_s is None:
+        return "неизвестно"
+    h, rem = divmod(int(age_s), 3600)
+    m, s = divmod(rem, 60)
+    if h > 0:
+        return f"{h}ч {m}м"
+    if m > 0:
+        return f"{m}м {s}с"
+    return f"{s}с"
diff --git a/src/cryodaq/agents/output_router.py b/src/cryodaq/agents/output_router.py
new file mode 100644
index 0000000..f33120b
--- /dev/null
+++ b/src/cryodaq/agents/output_router.py
@@ -0,0 +1,102 @@
+"""Output routing for GemmaAgent LLM responses.
+
+Dispatches generated text to configured output channels.
+Every output is prefixed with "🤖 Гемма:" so operators immediately
+distinguish AI-generated content from human input.
+"""
+
+from __future__ import annotations
+
+import enum
+import logging
+from typing import TYPE_CHECKING, Any
+
+if TYPE_CHECKING:
+    from cryodaq.core.event_bus import EngineEvent, EventBus
+    from cryodaq.core.event_logger import EventLogger
+
+logger = logging.getLogger(__name__)
+
+_GEMMA_PREFIX = "🤖 Гемма:"
+
+
+class OutputTarget(enum.Enum):
+    TELEGRAM = "telegram"
+    OPERATOR_LOG = "operator_log"
+    GUI_INSIGHT = "gui_insight"
+
+
+class OutputRouter:
+    """Dispatches GemmaAgent LLM output to configured channels."""
+
+    def __init__(
+        self,
+        *,
+        telegram_bot: Any | None,
+        event_logger: EventLogger,
+        event_bus: EventBus,
+    ) -> None:
+        self._telegram = telegram_bot
+        self._event_logger = event_logger
+        self._event_bus = event_bus
+
+    async def dispatch(
+        self,
+        trigger_event: EngineEvent,
+        llm_output: str,
+        *,
+        targets: list[OutputTarget],
+        audit_id: str,
+    ) -> list[str]:
+        """Send llm_output to all configured targets.
+
+        Returns list of successfully dispatched target names.
+        """
+        dispatched: list[str] = []
+        prefixed = f"{_GEMMA_PREFIX} {llm_output}"
+
+        for target in targets:
+            try:
+                if target == OutputTarget.TELEGRAM:
+                    if self._telegram is not None:
+                        await self._telegram._send_to_all(prefixed)
+                        dispatched.append("telegram")
+                    else:
+                        logger.debug("OutputRouter: Telegram bot not configured, skipping")
+
+                elif target == OutputTarget.OPERATOR_LOG:
+                    await self._event_logger.log_event(
+                        "gemma",
+                        prefixed,
+                        extra_tags=["ai", audit_id],
+                    )
+                    dispatched.append("operator_log")
+
+                elif target == OutputTarget.GUI_INSIGHT:
+                    from datetime import UTC, datetime
+
+                    from cryodaq.core.event_bus import EngineEvent as _EngineEvent
+
+                    await self._event_bus.publish(
+                        _EngineEvent(
+                            event_type="gemma_insight",
+                            timestamp=datetime.now(UTC),
+                            payload={
+                                "text": llm_output,
+                                "trigger_event_type": trigger_event.event_type,
+                                "audit_id": audit_id,
+                            },
+                            experiment_id=trigger_event.experiment_id,
+                        )
+                    )
+                    dispatched.append("gui_insight")
+
+            except Exception:
+                logger.warning(
+                    "OutputRouter: failed to dispatch to %s (audit_id=%s)",
+                    target.value,
+                    audit_id,
+                    exc_info=True,
+                )
+
+        return dispatched
diff --git a/src/cryodaq/engine.py b/src/cryodaq/engine.py
index fad2b60..ccfc919 100644
--- a/src/cryodaq/engine.py
+++ b/src/cryodaq/engine.py
@@ -1,111 +1,116 @@
 """Головной процесс CryoDAQ Engine (безголовый).
 
 Запуск:
     cryodaq-engine          # через entry point
     python -m cryodaq.engine  # напрямую
 
 Загружает конфигурации, создаёт и связывает все подсистемы:
     drivers → DataBroker →
     [SQLiteWriter, ZMQPublisher, AlarmEngine, InterlockEngine, PluginPipeline]
 
 Корректное завершение по SIGINT / SIGTERM (Unix) или Ctrl+C (Windows).
 """
 
 from __future__ import annotations
 
 import asyncio
 import logging
 import os
 import signal
 import sys
 import time
 from datetime import UTC, datetime
 
 # Windows: pyzmq требует SelectorEventLoop (не Proactor)
 if sys.platform == "win32":
     asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
 from pathlib import Path
 from typing import Any
 
 import yaml
 
+from cryodaq.agents.audit import AuditLogger
+from cryodaq.agents.context_builder import ContextBuilder
+from cryodaq.agents.gemma import GemmaAgent, GemmaConfig
+from cryodaq.agents.ollama_client import OllamaClient
+from cryodaq.agents.output_router import OutputRouter
 from cryodaq.analytics.calibration import CalibrationStore
 from cryodaq.analytics.leak_rate import LeakRateEstimator
 from cryodaq.analytics.plugin_loader import PluginPipeline
 from cryodaq.analytics.vacuum_trend import VacuumTrendPredictor
 from cryodaq.core.alarm import AlarmEngine
 from cryodaq.core.alarm_config import AlarmConfigError, load_alarm_config
 from cryodaq.core.alarm_providers import ExperimentPhaseProvider, ExperimentSetpointProvider
 from cryodaq.core.alarm_v2 import AlarmEvaluator, AlarmStateManager
 from cryodaq.core.broker import DataBroker
 from cryodaq.core.calibration_acquisition import (
     CalibrationAcquisitionService,
     CalibrationCommandError,
 )
 from cryodaq.core.channel_manager import ChannelConfigError, get_channel_manager
 from cryodaq.core.channel_state import ChannelStateTracker
 from cryodaq.core.disk_monitor import DiskMonitor
 from cryodaq.core.event_bus import EngineEvent, EventBus
 from cryodaq.core.event_logger import EventLogger
 from cryodaq.core.experiment import ExperimentManager, ExperimentStatus
 from cryodaq.core.housekeeping import (
     AdaptiveThrottle,
     HousekeepingConfigError,
     HousekeepingService,
     load_critical_channels_from_alarms_v3,
     load_housekeeping_config,
     load_protected_channel_patterns,
 )
 from cryodaq.core.interlock import InterlockConfigError, InterlockEngine
 from cryodaq.core.operator_log import OperatorLogEntry
 from cryodaq.core.rate_estimator import RateEstimator
 from cryodaq.core.safety_broker import SafetyBroker
 from cryodaq.core.safety_manager import SafetyConfigError, SafetyManager
 from cryodaq.core.scheduler import InstrumentConfig, Scheduler
 from cryodaq.core.sensor_diagnostics import SensorDiagnosticsEngine
 from cryodaq.core.smu_channel import normalize_smu_channel
 from cryodaq.core.zmq_bridge import ZMQCommandServer, ZMQPublisher
 from cryodaq.drivers.base import Reading
 from cryodaq.notifications.escalation import EscalationService
 from cryodaq.notifications.periodic_report import PeriodicReporter
 from cryodaq.notifications.telegram_commands import TelegramCommandBot
 from cryodaq.paths import get_config_dir, get_data_dir, get_project_root
 from cryodaq.reporting.generator import ReportGenerator
 from cryodaq.storage.sqlite_writer import SQLiteWriter
 
 logger = logging.getLogger("cryodaq.engine")
 
 # ---------------------------------------------------------------------------
 # Пути по умолчанию (относительно корня проекта)
 # ---------------------------------------------------------------------------
 
 _PROJECT_ROOT = get_project_root()
 _CONFIG_DIR = get_config_dir()
 _PLUGINS_DIR = _PROJECT_ROOT / "plugins"
 _DATA_DIR = get_data_dir()
 
 # Интервал самодиагностики (секунды)
 _WATCHDOG_INTERVAL_S = 30.0
 _LOG_GET_TIMEOUT_S = 1.5
 _EXPERIMENT_STATUS_TIMEOUT_S = 1.5
 
 
 async def _run_keithley_command(
     action: str,
     cmd: dict[str, Any],
     safety_manager: SafetyManager,
 ) -> dict[str, Any]:
     """Dispatch channel-scoped Keithley commands to SafetyManager."""
     channel = cmd.get("channel")
 
     if action == "keithley_start":
         smu_channel = normalize_smu_channel(channel)
         p = float(cmd.get("p_target", 0))
         v = float(cmd.get("v_comp", 40))
         i = float(cmd.get("i_comp", 1.0))
         return await safety_manager.request_run(p, v, i, channel=smu_channel)
 
     if action == "keithley_stop":
         smu_channel = normalize_smu_channel(channel)
         return await safety_manager.request_stop(channel=smu_channel)
 
@@ -1579,180 +1584,178 @@ async def _run_engine(*, mock: bool = False) -> None:
                     "event_emitted": ack_event is not None,
                 }
             if action in {
                 "get_app_mode",
                 "set_app_mode",
                 "experiment_templates",
                 "experiment_status",
                 "experiment_archive_list",
                 "experiment_list_archive",
                 "experiment_start",
                 "experiment_create",
                 "experiment_get_active",
                 "experiment_update",
                 "experiment_finalize",
                 "experiment_stop",
                 "experiment_abort",
                 "experiment_get_archive_item",
                 "experiment_attach_run_record",
                 "experiment_create_retroactive",
                 "experiment_generate_report",
                 "experiment_advance_phase",
                 "experiment_phase_status",
             }:
                 experiment_call = asyncio.to_thread(
                     _run_experiment_command,
                     action,
                     cmd,
                     experiment_manager,
                 )
                 if action == "experiment_status":
                     # NOTE: asyncio.wait_for on an asyncio.to_thread() call times out the AWAIT,
                     # not the worker thread. If get_status_payload() is pathologically slow, the
                     # background thread keeps running until it returns naturally. This is an
                     # accepted residual risk — REP is still protected by the outer 2.0s handler
                     # timeout envelope in ZMQCommandServer._run_handler(); this inner 1.5s wrapper
                     # only gives faster client feedback and frees the REP loop earlier. There is
                     # no safe way to terminate a Python thread mid-call, so Option C
                     # ("actually interrupt") is not available. See Codex commit-7 review.
                     try:
                         result = await asyncio.wait_for(
                             experiment_call,
                             timeout=_EXPERIMENT_STATUS_TIMEOUT_S,
                         )
                     except TimeoutError as exc:
                         raise TimeoutError(
                             f"experiment_status timeout ({_EXPERIMENT_STATUS_TIMEOUT_S:g}s)"
                         ) from exc
                 else:
                     result = await experiment_call
                 # Hook calibration acquisition on experiment lifecycle
                 if result.get("ok") and action in {"experiment_start", "experiment_create"}:
                     await asyncio.to_thread(
                         _try_activate_calibration_acquisition,
                         calibration_acquisition,
                         experiment_manager,
                         cmd,
                     )
                     name = cmd.get("name") or cmd.get("title") or "?"
                     await event_logger.log_event("experiment", f"Эксперимент начат: {name}")
                     await event_bus.publish(
                         EngineEvent(
                             event_type="experiment_start",
                             timestamp=datetime.now(UTC),
                             payload={"name": name, "experiment_id": result.get("experiment_id")},
                             experiment_id=result.get("experiment_id"),
                         )
                     )
                 elif result.get("ok") and action in {
                     "experiment_finalize",
                     "experiment_stop",
                     "experiment_abort",
                 }:
                     calibration_acquisition.deactivate()
                     if action == "experiment_abort":
                         await event_logger.log_event("experiment", "\u26a0 Эксперимент прерван")
                     else:
                         await event_logger.log_event("experiment", "Эксперимент завершён")
                     _exp_info = result.get("experiment", {})
                     await event_bus.publish(
                         EngineEvent(
-                            event_type="experiment_finalize"
-                            if action != "experiment_abort"
-                            else "experiment_abort",
+                            event_type=action,
                             timestamp=datetime.now(UTC),
                             payload={"action": action, "experiment": _exp_info},
                             experiment_id=_exp_info.get("experiment_id"),
                         )
                     )
                 elif result.get("ok") and action == "experiment_advance_phase":
                     phase = cmd.get("phase", "?")
-                    await event_logger.log_event("phase", f"Фаза: → {phase}")
                     _active = experiment_manager.active_experiment
                     await event_bus.publish(
                         EngineEvent(
                             event_type="phase_transition",
                             timestamp=datetime.now(UTC),
                             payload={"phase": phase, "entry": result.get("phase", {})},
                             experiment_id=_active.experiment_id if _active else None,
                         )
                     )
+                    await event_logger.log_event("phase", f"Фаза: → {phase}")
                 return result
             if action == "calibration_acquisition_status":
                 return {"ok": True, **calibration_acquisition.stats}
             if action in {
                 "calibration_v2_extract",
                 "calibration_v2_fit",
                 "calibration_v2_coverage",
             }:
                 return await asyncio.to_thread(
                     _run_calibration_v2_command,
                     action,
                     cmd,
                     calibration_store,
                 )
             if action == "readings_history":
                 channels_raw = cmd.get("channels")
                 channels = list(channels_raw) if channels_raw else None
                 from_ts = cmd.get("from_ts")
                 to_ts = cmd.get("to_ts")
                 limit = int(cmd.get("limit_per_channel", 3600))
                 data = await writer.read_readings_history(
                     channels=channels,
                     from_ts=float(from_ts) if from_ts is not None else None,
                     to_ts=float(to_ts) if to_ts is not None else None,
                     limit_per_channel=limit,
                 )
                 # Serialize: {channel: [[ts, value], ...]}
                 return {
                     "ok": True,
                     "data": {ch: pts for ch, pts in data.items()},
                 }
             if action == "cooldown_history_get":
                 return await _run_cooldown_history_command(
                     cmd, experiment_manager, writer
                 )
             if action in {"log_entry", "log_get"}:
                 return await _run_operator_log_command(
                     action,
                     cmd,
                     writer,
                     experiment_manager,
                     broker,
                 )
             if action in {
                 "calibration_curve_evaluate",
                 "calibration_curve_list",
                 "calibration_curve_get",
                 "calibration_curve_lookup",
                 "calibration_curve_assign",
                 "calibration_runtime_status",
                 "calibration_runtime_set_global",
                 "calibration_runtime_set_channel_policy",
                 "calibration_curve_export",
                 "calibration_curve_import",
             }:
                 return await asyncio.to_thread(
                     _run_calibration_command,
                     action,
                     cmd,
                     calibration_store=calibration_store,
                     experiment_manager=experiment_manager,
                     drivers_by_name=drivers_by_name,
                 )
             if action == "get_sensor_diagnostics":
                 if sensor_diag is None:
                     return {"ok": False, "error": "SensorDiagnostics отключён"}
                 from dataclasses import asdict
 
                 diag = sensor_diag.get_diagnostics()
                 summary = sensor_diag.get_summary()
                 return {
                     "ok": True,
                     "channels": {k: asdict(v) for k, v in diag.items()},
                     "summary": asdict(summary),
                 }
             if action == "get_vacuum_trend":
                 if vacuum_trend is None:
                     return {"ok": False, "error": "VacuumTrendPredictor отключён"}
                 from dataclasses import asdict
 
@@ -1791,304 +1794,356 @@ async def _run_engine(*, mock: bool = False) -> None:
             logger.error("Ошибка создания CooldownService: %s", exc)
 
     # --- Уведомления (один раз разбираем YAML) ---
     periodic_reporter: PeriodicReporter | None = None
     telegram_bot: TelegramCommandBot | None = None
     escalation_service: EscalationService | None = None
     notifications_cfg = _cfg("notifications")
     if notifications_cfg.exists():
         try:
             with notifications_cfg.open(encoding="utf-8") as fh:
                 notif_raw: dict[str, Any] = yaml.safe_load(fh) or {}
 
             tg_cfg = notif_raw.get("telegram", {})
             bot_token = str(tg_cfg.get("bot_token", ""))
             token_valid = bot_token and bot_token != "YOUR_BOT_TOKEN_HERE"
 
             # PeriodicReporter
             pr_cfg = notif_raw.get("periodic_report", {})
             if pr_cfg.get("enabled", False) and token_valid:
                 periodic_reporter = PeriodicReporter(
                     broker,
                     alarm_engine,
                     bot_token=bot_token,
                     chat_id=tg_cfg.get("chat_id", 0),
                     report_interval_s=float(pr_cfg.get("report_interval_s", 1800)),
                     chart_hours=float(pr_cfg.get("chart_hours", 2.0)),
                     include_channels=pr_cfg.get("include_channels"),
                 )
                 logger.info("PeriodicReporter создан")
 
             # TelegramCommandBot
             cmd_cfg = notif_raw.get("commands", {})
             commands_enabled = bool(cmd_cfg.get("enabled", False)) and token_valid
             if commands_enabled:
                 allowed_raw = (
                     tg_cfg.get("allowed_chat_ids") or cmd_cfg.get("allowed_chat_ids") or []
                 )
                 allowed_ids = [int(x) for x in allowed_raw]
                 # Phase 2b Codex K.1 — TelegramCommandBot raises on empty list,
                 # so refuse to enable cleanly here with a config-error log
                 # rather than letting the constructor surface an exception
                 # mid-startup.
                 if not allowed_ids:
                     logger.error(
                         "Telegram commands are enabled but allowed_chat_ids "
                         "is empty. Refusing to start TelegramCommandBot. "
                         "Add at least one chat ID or set commands.enabled: false."
                     )
                 else:
                     telegram_bot = TelegramCommandBot(
                         broker,
                         alarm_engine,
                         bot_token=bot_token,
                         allowed_chat_ids=allowed_ids,
                         poll_interval_s=float(cmd_cfg.get("poll_interval_s", 2.0)),
                         command_handler=_handle_gui_command,
                     )
                     logger.info(
                         "TelegramCommandBot создан (allowed=%d chat ids)",
                         len(allowed_ids),
                     )
 
             # EscalationService
             if token_valid and notif_raw.get("escalation"):
                 from cryodaq.notifications.telegram import TelegramNotifier
 
                 _esc_notifier = TelegramNotifier(
                     bot_token=bot_token,
                     chat_id=tg_cfg.get("chat_id", 0),
                 )
                 escalation_service = EscalationService(_esc_notifier, notif_raw)
                 logger.info("EscalationService создан (%d уровней)", len(notif_raw["escalation"]))
 
             if not token_valid:
                 logger.info("Telegram-уведомления отключены (bot_token не настроен)")
         except Exception as exc:
             logger.error("Ошибка загрузки конфигурации уведомлений: %s", exc)
     else:
         logger.info("Файл конфигурации уведомлений не найден: %s", notifications_cfg)
 
+    # --- GemmaAgent (Гемма local LLM agent) ---
+    _agent_cfg_path = _CONFIG_DIR / "agent.yaml"
+    gemma_agent: GemmaAgent | None = None
+    if _agent_cfg_path.exists():
+        try:
+            _agent_raw = yaml.safe_load(_agent_cfg_path.read_text(encoding="utf-8")) or {}
+            _gemma_raw = _agent_raw.get("gemma", {})
+            _gemma_config = GemmaConfig.from_dict(_gemma_raw)
+            if _gemma_config.enabled:
+                _gemma_ollama = OllamaClient(
+                    base_url=_gemma_config.ollama_base_url,
+                    default_model=_gemma_config.default_model,
+                    timeout_s=_gemma_config.timeout_s,
+                )
+                _gemma_ctx = ContextBuilder(writer, experiment_manager)
+                _gemma_audit = AuditLogger(
+                    _DATA_DIR / "agents" / "gemma" / "audit",
+                    enabled=_gemma_config.audit_enabled,
+                    retention_days=_gemma_config.audit_retention_days,
+                )
+                _gemma_router = OutputRouter(
+                    telegram_bot=telegram_bot,
+                    event_logger=event_logger,
+                    event_bus=event_bus,
+                )
+                gemma_agent = GemmaAgent(
+                    config=_gemma_config,
+                    event_bus=event_bus,
+                    ollama_client=_gemma_ollama,
+                    context_builder=_gemma_ctx,
+                    audit_logger=_gemma_audit,
+                    output_router=_gemma_router,
+                )
+                logger.info(
+                    "GemmaAgent (Гемма): инициализирован, модель=%s",
+                    _gemma_config.default_model,
+                )
+        except Exception as _gemma_exc:
+            logger.warning("GemmaAgent: ошибка инициализации — %s", _gemma_exc)
+    else:
+        logger.info("GemmaAgent: config/agent.yaml не найден, агент отключён")
+
     # --- Запуск всех подсистем ---
     await safety_manager.start()
     logger.info("SafetyManager запущен: состояние=%s", safety_manager.state.value)
     # writer уже запущен через start_immediate() выше
     await zmq_pub.start(zmq_queue)
     await cmd_server.start()
     await alarm_engine.start()
     await interlock_engine.start()
     await plugin_pipeline.start()
     if cooldown_service is not None:
         await cooldown_service.start()
     if periodic_reporter is not None:
         await periodic_reporter.start()
     if telegram_bot is not None:
         await telegram_bot.start()
+    if gemma_agent is not None:
+        try:
+            await gemma_agent.start()
+        except Exception as _gemma_start_exc:
+            logger.warning("GemmaAgent: ошибка запуска — %s. Агент отключён.", _gemma_start_exc)
+            gemma_agent = None
     await scheduler.start()
     throttle_task = asyncio.create_task(_track_runtime_signals(), name="adaptive_throttle_runtime")
     alarm_v2_feed_task = asyncio.create_task(_alarm_v2_feed_readings(), name="alarm_v2_feed")
     alarm_v2_tick_task: asyncio.Task | None = None
     if _alarm_v2_configs:
         alarm_v2_tick_task = asyncio.create_task(_alarm_v2_tick(), name="alarm_v2_tick")
     sd_feed_task: asyncio.Task | None = None
     sd_tick_task: asyncio.Task | None = None
     if sensor_diag is not None:
         sd_feed_task = asyncio.create_task(_sensor_diag_feed(), name="sensor_diag_feed")
         sd_tick_task = asyncio.create_task(_sensor_diag_tick(), name="sensor_diag_tick")
     vt_feed_task: asyncio.Task | None = None
     vt_tick_task: asyncio.Task | None = None
     if vacuum_trend is not None:
         vt_feed_task = asyncio.create_task(_vacuum_trend_feed(), name="vacuum_trend_feed")
         vt_tick_task = asyncio.create_task(_vacuum_trend_tick(), name="vacuum_trend_tick")
     leak_rate_feed_task = asyncio.create_task(_leak_rate_feed(), name="leak_rate_feed")
     await housekeeping_service.start()
 
     # Watchdog
     watchdog_task = asyncio.create_task(
         _watchdog(broker, scheduler, writer, start_ts),
         name="engine_watchdog",
     )
 
     # DiskMonitor — also wires the writer so disk-recovery can clear the
     # _disk_full flag (Phase 2a H.1).
     disk_monitor = DiskMonitor(data_dir=_DATA_DIR, broker=broker, sqlite_writer=writer)
     await disk_monitor.start()
 
     logger.info(
         "═══ CryoDAQ Engine запущен ═══ | приборов=%d | тревог=%d | блокировок=%d | mock=%s",
         len(driver_configs),
         len(alarm_engine.get_state()),
         len(interlock_engine.get_state()),
         mock,
     )
 
     # --- Ожидание сигнала завершения ---
     shutdown_event = asyncio.Event()
 
     def _request_shutdown() -> None:
         logger.info("Получен сигнал завершения")
         shutdown_event.set()
 
     # Регистрация обработчиков сигналов
     loop = asyncio.get_running_loop()
     if sys.platform != "win32":
         loop.add_signal_handler(signal.SIGINT, _request_shutdown)
         loop.add_signal_handler(signal.SIGTERM, _request_shutdown)
     else:
         # Windows: signal.signal работает только в главном потоке
         signal.signal(signal.SIGINT, lambda *_: _request_shutdown())
 
     await shutdown_event.wait()
 
     # --- Корректное завершение ---
     logger.info("═══ Завершение CryoDAQ Engine ═══")
 
     watchdog_task.cancel()
     try:
         await watchdog_task
     except asyncio.CancelledError:
         pass
 
     throttle_task.cancel()
     try:
         await throttle_task
     except asyncio.CancelledError:
         pass
 
     alarm_v2_feed_task.cancel()
     try:
         await alarm_v2_feed_task
     except asyncio.CancelledError:
         pass
     if alarm_v2_tick_task is not None:
         alarm_v2_tick_task.cancel()
         try:
             await alarm_v2_tick_task
         except asyncio.CancelledError:
             pass
 
     if sd_feed_task is not None:
         sd_feed_task.cancel()
         try:
             await sd_feed_task
         except asyncio.CancelledError:
             pass
     if sd_tick_task is not None:
         sd_tick_task.cancel()
         try:
             await sd_tick_task
         except asyncio.CancelledError:
             pass
 
     if vt_feed_task is not None:
         vt_feed_task.cancel()
         try:
             await vt_feed_task
         except asyncio.CancelledError:
             pass
     if vt_tick_task is not None:
         vt_tick_task.cancel()
         try:
             await vt_tick_task
         except asyncio.CancelledError:
             pass
     leak_rate_feed_task.cancel()
     try:
         await leak_rate_feed_task
     except asyncio.CancelledError:
         pass
 
     # Порядок: scheduler → plugins → alarms → interlocks → writer → zmq
     await scheduler.stop()
     logger.info("Планировщик остановлен")
 
     await plugin_pipeline.stop()
     logger.info("Пайплайн плагинов остановлен")
 
     if cooldown_service is not None:
         await cooldown_service.stop()
         logger.info("CooldownService остановлен")
 
     if periodic_reporter is not None:
         await periodic_reporter.stop()
         logger.info("PeriodicReporter остановлен")
 
+    if gemma_agent is not None:
+        await gemma_agent.stop()
+        logger.info("GemmaAgent (Гемма) остановлен")
+
     if telegram_bot is not None:
         await telegram_bot.stop()
         logger.info("TelegramCommandBot остановлен")
 
     await alarm_engine.stop()
     logger.info("Движок тревог остановлен")
 
     await interlock_engine.stop()
     logger.info("Движок блокировок остановлен")
 
     await safety_manager.stop()
     logger.info("SafetyManager остановлен: состояние=%s", safety_manager.state.value)
 
     await disk_monitor.stop()
     logger.info("DiskMonitor остановлен")
 
     await housekeeping_service.stop()
     logger.info("HousekeepingService остановлен")
 
     await writer.stop()
     logger.info("SQLite записано: %d", writer.stats.get("total_written", 0))
 
     await cmd_server.stop()
     logger.info("ZMQ CommandServer остановлен")
 
     await zmq_pub.stop()
     logger.info("ZMQ Publisher остановлен")
 
     from cryodaq.drivers.transport.gpib import GPIBTransport
 
     GPIBTransport.close_all_managers()
     logger.info("GPIB ResourceManagers закрыты")
 
     uptime = time.monotonic() - start_ts
     logger.info(
         "═══ CryoDAQ Engine завершён ═══ | uptime=%.1f с",
         uptime,
     )
 
 
 # ---------------------------------------------------------------------------
 # Single-instance guard
 # ---------------------------------------------------------------------------
 
 _LOCK_FILE = get_data_dir() / ".engine.lock"
 
 
 def _is_pid_alive(pid: int) -> bool:
     """Check if process with given PID exists."""
     try:
         if sys.platform == "win32":
             import ctypes
 
             handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
             if handle:
                 ctypes.windll.kernel32.CloseHandle(handle)
                 return True
             return False
         else:
             os.kill(pid, 0)
             return True
     except (OSError, ProcessLookupError):
         return False
 
 
 def _acquire_engine_lock() -> int:
     """Acquire exclusive engine lock via flock/msvcrt. Returns fd.
 
     If lock is held by a dead process, auto-cleans and retries.
     Shows helpful error with PID and kill command if lock is live.
     """
     _LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
     fd = os.open(str(_LOCK_FILE), os.O_CREAT | os.O_RDWR, 0o644)
     try:
         if sys.platform == "win32":
             import msvcrt
 
             msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
         else:
             import fcntl
diff --git a/tests/agents/test_gemma_alarm_flow.py b/tests/agents/test_gemma_alarm_flow.py
new file mode 100644
index 0000000..3bcb11a
--- /dev/null
+++ b/tests/agents/test_gemma_alarm_flow.py
@@ -0,0 +1,307 @@
+"""Tests for GemmaAgent alarm flow — Slice A end-to-end (mock Ollama)."""
+
+from __future__ import annotations
+
+import asyncio
+from datetime import UTC, datetime
+from pathlib import Path
+from unittest.mock import AsyncMock, MagicMock
+
+from cryodaq.agents.audit import AuditLogger
+from cryodaq.agents.context_builder import ContextBuilder
+from cryodaq.agents.gemma import GemmaAgent, GemmaConfig, _format_age
+from cryodaq.agents.ollama_client import GenerationResult, OllamaUnavailableError
+from cryodaq.agents.output_router import OutputRouter
+from cryodaq.core.event_bus import EngineEvent, EventBus
+
+# ---------------------------------------------------------------------------
+# Fixtures
+# ---------------------------------------------------------------------------
+
+
+def _alarm_event(
+    alarm_id: str = "test_alarm",
+    level: str = "WARNING",
+    experiment_id: str | None = "exp-001",
+) -> EngineEvent:
+    return EngineEvent(
+        event_type="alarm_fired",
+        timestamp=datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC),
+        payload={
+            "alarm_id": alarm_id,
+            "level": level,
+            "channels": ["T1", "T2"],
+            "values": {"T1": 4.5, "T2": 4.8},
+            "message": "Temperature above threshold",
+        },
+        experiment_id=experiment_id,
+    )
+
+
+def _make_config(**overrides) -> GemmaConfig:
+    cfg = GemmaConfig(
+        enabled=True,
+        max_concurrent_inferences=1,
+        max_calls_per_hour=60,
+        alarm_min_level="WARNING",
+        output_telegram=True,
+        output_operator_log=True,
+        output_gui_insight=False,
+        audit_enabled=False,
+    )
+    for k, v in overrides.items():
+        setattr(cfg, k, v)
+    return cfg
+
+
+def _make_mock_ollama(text: str = "🤖 Тест: температура T1 4.5K выше порога.") -> MagicMock:
+    ollama = AsyncMock()
+    ollama.generate = AsyncMock(
+        return_value=GenerationResult(
+            text=text, tokens_in=80, tokens_out=25, latency_s=3.5, model="gemma4:e4b"
+        )
+    )
+    ollama.close = AsyncMock()
+    return ollama
+
+
+def _make_mock_em() -> MagicMock:
+    em = MagicMock()
+    em.active_experiment_id = "exp-001"
+    em.get_current_phase = MagicMock(return_value="COOL")
+    em.get_phase_history = MagicMock(return_value=[])
+    return em
+
+
+def _make_context_builder(em) -> ContextBuilder:
+    reader = MagicMock()
+    return ContextBuilder(reader, em)
+
+
+def _make_audit(tmp_path: Path) -> AuditLogger:
+    return AuditLogger(tmp_path / "audit", enabled=False)
+
+
+def _make_output_router(telegram=None, event_logger=None, event_bus=None) -> OutputRouter:
+    if telegram is None:
+        telegram = AsyncMock()
+        telegram._send_to_all = AsyncMock()
+    if event_logger is None:
+        event_logger = AsyncMock()
+        event_logger.log_event = AsyncMock()
+    if event_bus is None:
+        event_bus = EventBus()
+    return OutputRouter(
+        telegram_bot=telegram,
+        event_logger=event_logger,
+        event_bus=event_bus,
+    )
+
+
+def _make_agent(
+    *,
+    config: GemmaConfig | None = None,
+    ollama=None,
+    telegram=None,
+    event_logger=None,
+    tmp_path: Path,
+) -> tuple[GemmaAgent, EventBus]:
+    bus = EventBus()
+    cfg = config or _make_config()
+    em = _make_mock_em()
+    ctx = _make_context_builder(em)
+    audit = _make_audit(tmp_path)
+    router = _make_output_router(telegram=telegram, event_logger=event_logger, event_bus=bus)
+    agent = GemmaAgent(
+        config=cfg,
+        event_bus=bus,
+        ollama_client=ollama or _make_mock_ollama(),
+        context_builder=ctx,
+        audit_logger=audit,
+        output_router=router,
+    )
+    return agent, bus
+
+
+# ---------------------------------------------------------------------------
+# GemmaConfig
+# ---------------------------------------------------------------------------
+
+
+def test_config_defaults() -> None:
+    cfg = GemmaConfig()
+    assert cfg.enabled is True
+    assert cfg.alarm_min_level == "WARNING"
+    assert cfg.max_concurrent_inferences == 2
+    assert cfg.slice_a_notification is True
+    assert cfg.slice_b_suggestion is False
+
+
+def test_config_from_dict() -> None:
+    raw = {
+        "enabled": True,
+        "ollama": {
+            "base_url": "http://localhost:11434",
+            "default_model": "gemma4:e4b",
+            "timeout_s": 30,
+        },
+        "rate_limit": {"max_calls_per_hour": 60, "max_concurrent_inferences": 2},
+        "triggers": {"alarm_fired": {"min_level": "WARNING"}},
+        "outputs": {"telegram": True, "operator_log": True, "gui_insight_panel": True},
+        "slices": {"a_notification": True, "b_suggestion": False},
+        "audit": {"enabled": True, "retention_days": 90},
+    }
+    cfg = GemmaConfig.from_dict(raw)
+    assert cfg.enabled is True
+    assert cfg.default_model == "gemma4:e4b"
+    assert cfg.alarm_min_level == "WARNING"
+    assert cfg.max_calls_per_hour == 60
+
+
+# ---------------------------------------------------------------------------
+# GemmaAgent — start / stop
+# ---------------------------------------------------------------------------
+
+
+async def test_agent_start_subscribes_to_bus(tmp_path: Path) -> None:
+    agent, bus = _make_agent(tmp_path=tmp_path)
+    await agent.start()
+    assert bus.subscriber_count == 1
+    await agent.stop()
+    assert bus.subscriber_count == 0
+
+
+async def test_agent_disabled_does_not_subscribe(tmp_path: Path) -> None:
+    agent, bus = _make_agent(config=_make_config(enabled=False), tmp_path=tmp_path)
+    await agent.start()
+    assert bus.subscriber_count == 0
+    await agent.stop()
+
+
+# ---------------------------------------------------------------------------
+# GemmaAgent — alarm_fired → LLM → dispatch
+# ---------------------------------------------------------------------------
+
+
+async def test_alarm_fired_triggers_ollama_generate(tmp_path: Path) -> None:
+    ollama = _make_mock_ollama()
+    agent, bus = _make_agent(ollama=ollama, tmp_path=tmp_path)
+    await agent.start()
+
+    await bus.publish(_alarm_event())
+    await asyncio.sleep(0.05)
+
+    ollama.generate.assert_awaited_once()
+    await agent.stop()
+
+
+async def test_alarm_fired_dispatches_to_telegram(tmp_path: Path) -> None:
+    telegram = AsyncMock()
+    telegram._send_to_all = AsyncMock()
+    agent, bus = _make_agent(telegram=telegram, tmp_path=tmp_path)
+    await agent.start()
+
+    await bus.publish(_alarm_event())
+    await asyncio.sleep(0.05)
+
+    telegram._send_to_all.assert_awaited_once()
+    sent_text = telegram._send_to_all.call_args[0][0]
+    assert "🤖 Гемма:" in sent_text
+    await agent.stop()
+
+
+async def test_alarm_fired_dispatches_to_operator_log(tmp_path: Path) -> None:
+    event_logger = AsyncMock()
+    event_logger.log_event = AsyncMock()
+    agent, bus = _make_agent(event_logger=event_logger, tmp_path=tmp_path)
+    await agent.start()
+
+    await bus.publish(_alarm_event())
+    await asyncio.sleep(0.05)
+
+    event_logger.log_event.assert_awaited_once()
+    args = event_logger.log_event.call_args
+    assert args[0][0] == "gemma"
+    await agent.stop()
+
+
+async def test_info_level_alarm_not_handled(tmp_path: Path) -> None:
+    ollama = _make_mock_ollama()
+    agent, bus = _make_agent(
+        config=_make_config(alarm_min_level="WARNING"), ollama=ollama, tmp_path=tmp_path
+    )
+    await agent.start()
+
+    await bus.publish(_alarm_event(level="INFO"))
+    await asyncio.sleep(0.05)
+
+    ollama.generate.assert_not_awaited()
+    await agent.stop()
+
+
+async def test_critical_level_alarm_is_handled(tmp_path: Path) -> None:
+    ollama = _make_mock_ollama()
+    agent, bus = _make_agent(ollama=ollama, tmp_path=tmp_path)
+    await agent.start()
+
+    await bus.publish(_alarm_event(level="CRITICAL"))
+    await asyncio.sleep(0.05)
+
+    ollama.generate.assert_awaited_once()
+    await agent.stop()
+
+
+# ---------------------------------------------------------------------------
+# GemmaAgent — error resilience
+# ---------------------------------------------------------------------------
+
+
+async def test_ollama_unavailable_does_not_crash_agent(tmp_path: Path) -> None:
+    ollama = AsyncMock()
+    ollama.generate = AsyncMock(side_effect=OllamaUnavailableError("connection refused"))
+    ollama.close = AsyncMock()
+    agent, bus = _make_agent(ollama=ollama, tmp_path=tmp_path)
+    await agent.start()
+
+    await bus.publish(_alarm_event())
+    await asyncio.sleep(0.05)
+
+    assert agent._task is not None
+    assert not agent._task.done()
+    await agent.stop()
+
+
+async def test_rate_limit_drops_excess_calls(tmp_path: Path) -> None:
+    ollama = _make_mock_ollama()
+    agent, bus = _make_agent(
+        config=_make_config(max_calls_per_hour=1), ollama=ollama, tmp_path=tmp_path
+    )
+    await agent.start()
+
+    await bus.publish(_alarm_event(alarm_id="a1"))
+    await bus.publish(_alarm_event(alarm_id="a2"))
+    await asyncio.sleep(0.1)
+
+    assert ollama.generate.await_count == 1
+    await agent.stop()
+
+
+# ---------------------------------------------------------------------------
+# Helpers
+# ---------------------------------------------------------------------------
+
+
+def test_format_age_none() -> None:
+    assert _format_age(None) == "неизвестно"
+
+
+def test_format_age_seconds() -> None:
+    assert _format_age(45) == "45с"
+
+
+def test_format_age_minutes() -> None:
+    assert _format_age(150) == "2м 30с"
+
+
+def test_format_age_hours() -> None:
+    assert _format_age(7260) == "2ч 1м"

exec
/opt/homebrew/bin/bash -lc "ls -R src/cryodaq/agents && sed -n '1,260p' src/cryodaq/agents/context_builder.py && sed -n '1,260p' src/cryodaq/agents/audit.py && sed -n '1,240p' src/cryodaq/agents/ollama_client.py && sed -n '1,180p' src/cryodaq/core/event_bus.py && sed -n '1,220p' src/cryodaq/core/event_logger.py" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
__init__.py
__pycache__
audit.py
context_builder.py
gemma.py
ollama_client.py
output_router.py
prompts.py

src/cryodaq/agents/__pycache__:
__init__.cpython-314.pyc
audit.cpython-314.pyc
context_builder.cpython-314.pyc
gemma.cpython-314.pyc
ollama_client.cpython-314.pyc
output_router.cpython-314.pyc
prompts.cpython-314.pyc
"""Context assembler for GemmaAgent LLM prompts.

Each task type (alarm summary, diagnostic, campaign report) requires
different context. Builders read SQLite state and format compact text
for LLM token budget.

Cycle 1: AlarmContext dataclass + build_alarm_context interface.
SQLite queries and full context assembly wired in Cycle 2.
Slice B (diagnostic) and Slice C (campaign) contexts deferred.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AlarmContext:
    """Context for alarm summary generation (Slice A)."""

    alarm_id: str
    level: str
    channels: list[str]
    values: dict[str, float]
    phase: str | None
    experiment_id: str | None
    experiment_age_s: float | None
    target_temp: float | None
    active_interlocks: list[str] = field(default_factory=list)
    recent_readings_text: str = ""
    recent_alarms_text: str = ""


class ContextBuilder:
    """Assembles engine state for LLM prompt construction."""

    def __init__(self, sqlite_reader: Any, experiment_manager: Any) -> None:
        self._reader = sqlite_reader
        self._em = experiment_manager

    async def build_alarm_context(
        self,
        alarm_payload: dict[str, Any],
        *,
        lookback_s: float = 60.0,
        recent_alarm_lookback_s: float = 3600.0,
    ) -> AlarmContext:
        """Assemble context for a Slice A alarm summary prompt.

        Reads experiment state from ExperimentManager (in-memory, fast).
        SQLite reading history and alarm history wired in Cycle 2.
        """
        alarm_id = alarm_payload.get("alarm_id", "unknown")
        channels: list[str] = alarm_payload.get("channels", [])
        values: dict[str, float] = alarm_payload.get("values", {})
        level: str = alarm_payload.get("level", "WARNING")

        experiment_id: str | None = getattr(self._em, "active_experiment_id", None)

        phase: str | None = None
        if hasattr(self._em, "get_current_phase"):
            try:
                phase = self._em.get_current_phase()
            except Exception:
                pass

        experiment_age_s: float | None = _compute_experiment_age(self._em)

        return AlarmContext(
            alarm_id=alarm_id,
            level=level,
            channels=channels,
            values=values,
            phase=phase,
            experiment_id=experiment_id,
            experiment_age_s=experiment_age_s,
            target_temp=None,
            active_interlocks=[],
            recent_readings_text=_readings_stub(channels, lookback_s),
            recent_alarms_text=_alarms_stub(recent_alarm_lookback_s),
        )


def _compute_experiment_age(em: Any) -> float | None:
    try:
        history = em.get_phase_history()
        if not history:
            return None
        first = history[0].get("started_at")
        if not first:
            return None
        from datetime import UTC, datetime

        started = datetime.fromisoformat(first)
        return (datetime.now(UTC) - started.astimezone(UTC)).total_seconds()
    except Exception:
        return None


def _readings_stub(channels: list[str], lookback_s: float) -> str:
    ch = ", ".join(channels) if channels else "(none)"
    return f"[Readings for {ch} over last {lookback_s:.0f}s — wired in Cycle 2]"


def _alarms_stub(lookback_s: float) -> str:
    return f"[Alarm history over last {lookback_s:.0f}s — wired in Cycle 2]"
"""Audit logger — persists every GemmaAgent LLM call for post-hoc review."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class AuditLogger:
    """Writes one JSON file per LLM call under audit_dir/<YYYY-MM-DD>/.

    Schema per file matches docs/ORCHESTRATION spec §2.8 audit record.
    Retention housekeeping (deleting old files) is handled by HousekeepingService.
    """

    def __init__(
        self,
        audit_dir: Path,
        *,
        enabled: bool = True,
        retention_days: int = 90,
    ) -> None:
        self._audit_dir = Path(audit_dir)
        self._enabled = enabled
        self._retention_days = retention_days

    def make_audit_id(self) -> str:
        """Return a short unique ID for one audit record."""
        return uuid.uuid4().hex[:12]

    async def log(
        self,
        *,
        audit_id: str,
        trigger_event: dict[str, Any],
        context_assembled: str,
        prompt_template: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        response: str,
        tokens: dict[str, int],
        latency_s: float,
        outputs_dispatched: list[str],
        errors: list[str],
    ) -> Path | None:
        """Persist an audit record. Returns the file path, or None if disabled or failed."""
        if not self._enabled:
            return None

        now = datetime.now(UTC)
        date_dir = self._audit_dir / now.strftime("%Y-%m-%d")
        date_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{now.strftime('%Y%m%dT%H%M%S%f')}_{audit_id}.json"
        path = date_dir / filename

        record: dict[str, Any] = {
            "audit_id": audit_id,
            "timestamp": now.isoformat(),
            "trigger_event": trigger_event,
            "context_assembled": context_assembled,
            "prompt_template": prompt_template,
            "model": model,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "response": response,
            "tokens": tokens,
            "latency_s": round(latency_s, 3),
            "outputs_dispatched": outputs_dispatched,
            "errors": errors,
        }

        try:
            path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            logger.warning("AuditLogger: failed to write %s", path, exc_info=True)
            return None

        return path
"""Ollama HTTP client for local LLM inference."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

_GENERATE_PATH = "/api/generate"


class OllamaUnavailableError(Exception):
    """Ollama server unreachable (connection refused or network error)."""


class OllamaModelMissingError(Exception):
    """Requested model is not pulled on this Ollama instance."""

    def __init__(self, model: str) -> None:
        self.model = model
        super().__init__(f"Model '{model}' not found. Run: ollama pull {model}")


@dataclass
class GenerationResult:
    """Result of a single LLM generate call."""

    text: str
    tokens_in: int
    tokens_out: int
    latency_s: float
    model: str
    truncated: bool = False


class OllamaClient:
    """Async HTTP wrapper around Ollama /api/generate.

    Manages one aiohttp.ClientSession; call close() on shutdown.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        default_model: str = "gemma4:e4b",
        *,
        timeout_s: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._timeout_s = timeout_s
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        """Close the underlying HTTP session."""
        if self._session is not None and not self._session.closed:
            await self._session.close()
            self._session = None

    async def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.3,
        system: str | None = None,
    ) -> GenerationResult:
        """Call Ollama /api/generate and return a GenerationResult.

        On timeout: returns truncated=True with empty text (does not raise).

        Raises:
            OllamaUnavailableError: server not reachable
            OllamaModelMissingError: model not pulled
        """
        effective_model = model or self._default_model
        url = f"{self._base_url}{_GENERATE_PATH}"
        payload: dict[str, Any] = {
            "model": effective_model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }
        if system is not None:
            payload["system"] = system

        session = await self._get_session()
        t0 = time.monotonic()

        try:
            async with asyncio.timeout(self._timeout_s):
                async with session.post(url, json=payload) as resp:
                    data: dict[str, Any] = await resp.json(content_type=None)
        except TimeoutError:
            latency_s = time.monotonic() - t0
            logger.warning(
                "OllamaClient: timeout after %.1fs for model %s",
                latency_s,
                effective_model,
            )
            return GenerationResult(
                text="",
                tokens_in=0,
                tokens_out=0,
                latency_s=latency_s,
                model=effective_model,
                truncated=True,
            )
        except aiohttp.ClientConnectorError as exc:
            raise OllamaUnavailableError(
                f"Cannot connect to Ollama at {self._base_url}: {exc}"
            ) from exc
        except aiohttp.ClientError as exc:
            raise OllamaUnavailableError(f"Ollama HTTP error: {exc}") from exc

        latency_s = time.monotonic() - t0

        if "error" in data:
            err = str(data["error"])
            if "not found" in err.lower():
                raise OllamaModelMissingError(effective_model)
            raise OllamaUnavailableError(f"Ollama error: {err}")

        return GenerationResult(
            text=data.get("response", ""),
            tokens_in=data.get("prompt_eval_count", 0),
            tokens_out=data.get("eval_count", 0),
            latency_s=latency_s,
            model=data.get("model", effective_model),
        )
"""Lightweight pub/sub event bus for engine events (not Reading data)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EngineEvent:
    """An engine-level event published to EventBus subscribers."""

    event_type: str  # "alarm_fired", "alarm_cleared", "phase_transition", "experiment_finalize", …
    timestamp: datetime
    payload: dict[str, Any]
    experiment_id: str | None = None


class EventBus:
    """Lightweight pub/sub for engine events (not Reading data).

    Subscribers receive a dedicated asyncio.Queue. Publish is non-blocking:
    a full queue logs a warning and drops the event rather than blocking
    the engine event loop.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, asyncio.Queue[EngineEvent]] = {}

    async def subscribe(self, name: str, *, maxsize: int = 1000) -> asyncio.Queue[EngineEvent]:
        """Register a named subscriber and return its dedicated queue."""
        if name in self._subscribers:
            logger.warning("EventBus: duplicate subscribe '%s' — replacing existing queue", name)
        q: asyncio.Queue[EngineEvent] = asyncio.Queue(maxsize=maxsize)
        self._subscribers[name] = q
        return q

    def unsubscribe(self, name: str) -> None:
        """Remove a subscriber by name. No-op if not registered."""
        self._subscribers.pop(name, None)

    async def publish(self, event: EngineEvent) -> None:
        """Fan out event to all subscriber queues (non-blocking; drops on full)."""
        for name, q in list(self._subscribers.items()):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(
                    "EventBus: subscriber '%s' queue full, dropping %s",
                    name,
                    event.event_type,
                )

    @property
    def subscriber_count(self) -> int:
        """Number of currently registered subscribers."""
        return len(self._subscribers)
"""Automatic event logging for system actions."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cryodaq.core.event_bus import EventBus

logger = logging.getLogger(__name__)


class EventLogger:
    """Logs system events to the operator journal via SQLiteWriter."""

    def __init__(
        self,
        writer: Any,
        experiment_manager: Any,
        *,
        event_bus: EventBus | None = None,
    ) -> None:
        self._writer = writer
        self._em = experiment_manager
        self._event_bus = event_bus

    async def log_event(
        self,
        event_type: str,
        message: str,
        *,
        extra_tags: list[str] | None = None,
    ) -> None:
        """Write an auto-log entry to SQLite and publish to EventBus."""
        experiment_id = self._em.active_experiment_id
        try:
            await self._writer.append_operator_log(
                message=message,
                author="system",
                source="auto",
                experiment_id=experiment_id,
                tags=["auto", event_type, *(extra_tags or [])],
            )
        except Exception:
            logger.warning("Failed to auto-log event: %s", message, exc_info=True)

        if self._event_bus is not None:
            from cryodaq.core.event_bus import EngineEvent

            try:
                await self._event_bus.publish(
                    EngineEvent(
                        event_type="event_logged",
                        timestamp=datetime.now(UTC),
                        payload={"event_type": event_type, "message": message},
                        experiment_id=experiment_id,
                    )
                )
            except Exception:
                logger.warning("EventBus publish failed in log_event", exc_info=True)

exec
/opt/homebrew/bin/bash -lc 'git diff 535cc95''^ 535cc95 --unified=60 -- src/cryodaq/engine.py | sed -n '"'1,260p'; echo '---'; git diff 535cc95"'^ 535cc95 --unified=60 -- src/cryodaq/engine.py | sed -n '"'260,620p'; echo '---prompts'; git show 535cc95:src/cryodaq/agents/prompts.py" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
diff --git a/src/cryodaq/engine.py b/src/cryodaq/engine.py
index fad2b60..ccfc919 100644
--- a/src/cryodaq/engine.py
+++ b/src/cryodaq/engine.py
@@ -1,91 +1,96 @@
 """Головной процесс CryoDAQ Engine (безголовый).
 
 Запуск:
     cryodaq-engine          # через entry point
     python -m cryodaq.engine  # напрямую
 
 Загружает конфигурации, создаёт и связывает все подсистемы:
     drivers → DataBroker →
     [SQLiteWriter, ZMQPublisher, AlarmEngine, InterlockEngine, PluginPipeline]
 
 Корректное завершение по SIGINT / SIGTERM (Unix) или Ctrl+C (Windows).
 """
 
 from __future__ import annotations
 
 import asyncio
 import logging
 import os
 import signal
 import sys
 import time
 from datetime import UTC, datetime
 
 # Windows: pyzmq требует SelectorEventLoop (не Proactor)
 if sys.platform == "win32":
     asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
 from pathlib import Path
 from typing import Any
 
 import yaml
 
+from cryodaq.agents.audit import AuditLogger
+from cryodaq.agents.context_builder import ContextBuilder
+from cryodaq.agents.gemma import GemmaAgent, GemmaConfig
+from cryodaq.agents.ollama_client import OllamaClient
+from cryodaq.agents.output_router import OutputRouter
 from cryodaq.analytics.calibration import CalibrationStore
 from cryodaq.analytics.leak_rate import LeakRateEstimator
 from cryodaq.analytics.plugin_loader import PluginPipeline
 from cryodaq.analytics.vacuum_trend import VacuumTrendPredictor
 from cryodaq.core.alarm import AlarmEngine
 from cryodaq.core.alarm_config import AlarmConfigError, load_alarm_config
 from cryodaq.core.alarm_providers import ExperimentPhaseProvider, ExperimentSetpointProvider
 from cryodaq.core.alarm_v2 import AlarmEvaluator, AlarmStateManager
 from cryodaq.core.broker import DataBroker
 from cryodaq.core.calibration_acquisition import (
     CalibrationAcquisitionService,
     CalibrationCommandError,
 )
 from cryodaq.core.channel_manager import ChannelConfigError, get_channel_manager
 from cryodaq.core.channel_state import ChannelStateTracker
 from cryodaq.core.disk_monitor import DiskMonitor
 from cryodaq.core.event_bus import EngineEvent, EventBus
 from cryodaq.core.event_logger import EventLogger
 from cryodaq.core.experiment import ExperimentManager, ExperimentStatus
 from cryodaq.core.housekeeping import (
     AdaptiveThrottle,
     HousekeepingConfigError,
     HousekeepingService,
     load_critical_channels_from_alarms_v3,
     load_housekeeping_config,
     load_protected_channel_patterns,
 )
 from cryodaq.core.interlock import InterlockConfigError, InterlockEngine
 from cryodaq.core.operator_log import OperatorLogEntry
 from cryodaq.core.rate_estimator import RateEstimator
 from cryodaq.core.safety_broker import SafetyBroker
 from cryodaq.core.safety_manager import SafetyConfigError, SafetyManager
 from cryodaq.core.scheduler import InstrumentConfig, Scheduler
 from cryodaq.core.sensor_diagnostics import SensorDiagnosticsEngine
 from cryodaq.core.smu_channel import normalize_smu_channel
 from cryodaq.core.zmq_bridge import ZMQCommandServer, ZMQPublisher
 from cryodaq.drivers.base import Reading
 from cryodaq.notifications.escalation import EscalationService
 from cryodaq.notifications.periodic_report import PeriodicReporter
 from cryodaq.notifications.telegram_commands import TelegramCommandBot
 from cryodaq.paths import get_config_dir, get_data_dir, get_project_root
 from cryodaq.reporting.generator import ReportGenerator
 from cryodaq.storage.sqlite_writer import SQLiteWriter
 
 logger = logging.getLogger("cryodaq.engine")
 
 # ---------------------------------------------------------------------------
 # Пути по умолчанию (относительно корня проекта)
 # ---------------------------------------------------------------------------
 
 _PROJECT_ROOT = get_project_root()
 _CONFIG_DIR = get_config_dir()
 _PLUGINS_DIR = _PROJECT_ROOT / "plugins"
 _DATA_DIR = get_data_dir()
 
 # Интервал самодиагностики (секунды)
 _WATCHDOG_INTERVAL_S = 30.0
 _LOG_GET_TIMEOUT_S = 1.5
 _EXPERIMENT_STATUS_TIMEOUT_S = 1.5
 
@@ -1599,140 +1604,138 @@ async def _run_engine(*, mock: bool = False) -> None:
                 "experiment_advance_phase",
                 "experiment_phase_status",
             }:
                 experiment_call = asyncio.to_thread(
                     _run_experiment_command,
                     action,
                     cmd,
                     experiment_manager,
                 )
                 if action == "experiment_status":
                     # NOTE: asyncio.wait_for on an asyncio.to_thread() call times out the AWAIT,
                     # not the worker thread. If get_status_payload() is pathologically slow, the
                     # background thread keeps running until it returns naturally. This is an
                     # accepted residual risk — REP is still protected by the outer 2.0s handler
                     # timeout envelope in ZMQCommandServer._run_handler(); this inner 1.5s wrapper
                     # only gives faster client feedback and frees the REP loop earlier. There is
                     # no safe way to terminate a Python thread mid-call, so Option C
                     # ("actually interrupt") is not available. See Codex commit-7 review.
                     try:
                         result = await asyncio.wait_for(
                             experiment_call,
                             timeout=_EXPERIMENT_STATUS_TIMEOUT_S,
                         )
                     except TimeoutError as exc:
                         raise TimeoutError(
                             f"experiment_status timeout ({_EXPERIMENT_STATUS_TIMEOUT_S:g}s)"
                         ) from exc
                 else:
                     result = await experiment_call
                 # Hook calibration acquisition on experiment lifecycle
                 if result.get("ok") and action in {"experiment_start", "experiment_create"}:
                     await asyncio.to_thread(
                         _try_activate_calibration_acquisition,
                         calibration_acquisition,
                         experiment_manager,
                         cmd,
                     )
                     name = cmd.get("name") or cmd.get("title") or "?"
                     await event_logger.log_event("experiment", f"Эксперимент начат: {name}")
                     await event_bus.publish(
                         EngineEvent(
                             event_type="experiment_start",
                             timestamp=datetime.now(UTC),
                             payload={"name": name, "experiment_id": result.get("experiment_id")},
                             experiment_id=result.get("experiment_id"),
                         )
                     )
                 elif result.get("ok") and action in {
                     "experiment_finalize",
                     "experiment_stop",
                     "experiment_abort",
                 }:
                     calibration_acquisition.deactivate()
                     if action == "experiment_abort":
                         await event_logger.log_event("experiment", "\u26a0 Эксперимент прерван")
                     else:
                         await event_logger.log_event("experiment", "Эксперимент завершён")
                     _exp_info = result.get("experiment", {})
                     await event_bus.publish(
                         EngineEvent(
-                            event_type="experiment_finalize"
-                            if action != "experiment_abort"
-                            else "experiment_abort",
+                            event_type=action,
                             timestamp=datetime.now(UTC),
                             payload={"action": action, "experiment": _exp_info},
                             experiment_id=_exp_info.get("experiment_id"),
                         )
                     )
                 elif result.get("ok") and action == "experiment_advance_phase":
                     phase = cmd.get("phase", "?")
-                    await event_logger.log_event("phase", f"Фаза: → {phase}")
                     _active = experiment_manager.active_experiment
                     await event_bus.publish(
                         EngineEvent(
                             event_type="phase_transition",
                             timestamp=datetime.now(UTC),
                             payload={"phase": phase, "entry": result.get("phase", {})},
                             experiment_id=_active.experiment_id if _active else None,
                         )
                     )
+                    await event_logger.log_event("phase", f"Фаза: → {phase}")
                 return result
             if action == "calibration_acquisition_status":
                 return {"ok": True, **calibration_acquisition.stats}
             if action in {
                 "calibration_v2_extract",
                 "calibration_v2_fit",
                 "calibration_v2_coverage",
             }:
                 return await asyncio.to_thread(
                     _run_calibration_v2_command,
                     action,
                     cmd,
                     calibration_store,
                 )
             if action == "readings_history":
                 channels_raw = cmd.get("channels")
                 channels = list(channels_raw) if channels_raw else None
                 from_ts = cmd.get("from_ts")
                 to_ts = cmd.get("to_ts")
                 limit = int(cmd.get("limit_per_channel", 3600))
                 data = await writer.read_readings_history(
                     channels=channels,
                     from_ts=float(from_ts) if from_ts is not None else None,
                     to_ts=float(to_ts) if to_ts is not None else None,
                     limit_per_channel=limit,
                 )
                 # Serialize: {channel: [[ts, value], ...]}
                 return {
                     "ok": True,
                     "data": {ch: pts for ch, pts in data.items()},
                 }
             if action == "cooldown_history_get":
                 return await _run_cooldown_history_command(
                     cmd, experiment_manager, writer
                 )
             if action in {"log_entry", "log_get"}:
                 return await _run_operator_log_command(
                     action,
                     cmd,
                     writer,
                     experiment_manager,
                     broker,
                 )
             if action in {
                 "calibration_curve_evaluate",
                 "calibration_curve_list",
                 "calibration_curve_get",
                 "calibration_curve_lookup",
                 "calibration_curve_assign",
                 "calibration_runtime_status",
                 "calibration_runtime_set_global",
                 "calibration_runtime_set_channel_policy",
                 "calibration_curve_export",
                 "calibration_curve_import",
             }:
                 return await asyncio.to_thread(
                     _run_calibration_command,
                     action,
                     cmd,
                     calibration_store=calibration_store,
@@ -1811,135 +1814,183 @@ async def _run_engine(*, mock: bool = False) -> None:
                     broker,
                     alarm_engine,
                     bot_token=bot_token,
                     chat_id=tg_cfg.get("chat_id", 0),
                     report_interval_s=float(pr_cfg.get("report_interval_s", 1800)),
                     chart_hours=float(pr_cfg.get("chart_hours", 2.0)),
                     include_channels=pr_cfg.get("include_channels"),
                 )
                 logger.info("PeriodicReporter создан")
 
             # TelegramCommandBot
             cmd_cfg = notif_raw.get("commands", {})
             commands_enabled = bool(cmd_cfg.get("enabled", False)) and token_valid
             if commands_enabled:
                 allowed_raw = (
---
                 allowed_raw = (
                     tg_cfg.get("allowed_chat_ids") or cmd_cfg.get("allowed_chat_ids") or []
                 )
                 allowed_ids = [int(x) for x in allowed_raw]
                 # Phase 2b Codex K.1 — TelegramCommandBot raises on empty list,
                 # so refuse to enable cleanly here with a config-error log
                 # rather than letting the constructor surface an exception
                 # mid-startup.
                 if not allowed_ids:
                     logger.error(
                         "Telegram commands are enabled but allowed_chat_ids "
                         "is empty. Refusing to start TelegramCommandBot. "
                         "Add at least one chat ID or set commands.enabled: false."
                     )
                 else:
                     telegram_bot = TelegramCommandBot(
                         broker,
                         alarm_engine,
                         bot_token=bot_token,
                         allowed_chat_ids=allowed_ids,
                         poll_interval_s=float(cmd_cfg.get("poll_interval_s", 2.0)),
                         command_handler=_handle_gui_command,
                     )
                     logger.info(
                         "TelegramCommandBot создан (allowed=%d chat ids)",
                         len(allowed_ids),
                     )
 
             # EscalationService
             if token_valid and notif_raw.get("escalation"):
                 from cryodaq.notifications.telegram import TelegramNotifier
 
                 _esc_notifier = TelegramNotifier(
                     bot_token=bot_token,
                     chat_id=tg_cfg.get("chat_id", 0),
                 )
                 escalation_service = EscalationService(_esc_notifier, notif_raw)
                 logger.info("EscalationService создан (%d уровней)", len(notif_raw["escalation"]))
 
             if not token_valid:
                 logger.info("Telegram-уведомления отключены (bot_token не настроен)")
         except Exception as exc:
             logger.error("Ошибка загрузки конфигурации уведомлений: %s", exc)
     else:
         logger.info("Файл конфигурации уведомлений не найден: %s", notifications_cfg)
 
+    # --- GemmaAgent (Гемма local LLM agent) ---
+    _agent_cfg_path = _CONFIG_DIR / "agent.yaml"
+    gemma_agent: GemmaAgent | None = None
+    if _agent_cfg_path.exists():
+        try:
+            _agent_raw = yaml.safe_load(_agent_cfg_path.read_text(encoding="utf-8")) or {}
+            _gemma_raw = _agent_raw.get("gemma", {})
+            _gemma_config = GemmaConfig.from_dict(_gemma_raw)
+            if _gemma_config.enabled:
+                _gemma_ollama = OllamaClient(
+                    base_url=_gemma_config.ollama_base_url,
+                    default_model=_gemma_config.default_model,
+                    timeout_s=_gemma_config.timeout_s,
+                )
+                _gemma_ctx = ContextBuilder(writer, experiment_manager)
+                _gemma_audit = AuditLogger(
+                    _DATA_DIR / "agents" / "gemma" / "audit",
+                    enabled=_gemma_config.audit_enabled,
+                    retention_days=_gemma_config.audit_retention_days,
+                )
+                _gemma_router = OutputRouter(
+                    telegram_bot=telegram_bot,
+                    event_logger=event_logger,
+                    event_bus=event_bus,
+                )
+                gemma_agent = GemmaAgent(
+                    config=_gemma_config,
+                    event_bus=event_bus,
+                    ollama_client=_gemma_ollama,
+                    context_builder=_gemma_ctx,
+                    audit_logger=_gemma_audit,
+                    output_router=_gemma_router,
+                )
+                logger.info(
+                    "GemmaAgent (Гемма): инициализирован, модель=%s",
+                    _gemma_config.default_model,
+                )
+        except Exception as _gemma_exc:
+            logger.warning("GemmaAgent: ошибка инициализации — %s", _gemma_exc)
+    else:
+        logger.info("GemmaAgent: config/agent.yaml не найден, агент отключён")
+
     # --- Запуск всех подсистем ---
     await safety_manager.start()
     logger.info("SafetyManager запущен: состояние=%s", safety_manager.state.value)
     # writer уже запущен через start_immediate() выше
     await zmq_pub.start(zmq_queue)
     await cmd_server.start()
     await alarm_engine.start()
     await interlock_engine.start()
     await plugin_pipeline.start()
     if cooldown_service is not None:
         await cooldown_service.start()
     if periodic_reporter is not None:
         await periodic_reporter.start()
     if telegram_bot is not None:
         await telegram_bot.start()
+    if gemma_agent is not None:
+        try:
+            await gemma_agent.start()
+        except Exception as _gemma_start_exc:
+            logger.warning("GemmaAgent: ошибка запуска — %s. Агент отключён.", _gemma_start_exc)
+            gemma_agent = None
     await scheduler.start()
     throttle_task = asyncio.create_task(_track_runtime_signals(), name="adaptive_throttle_runtime")
     alarm_v2_feed_task = asyncio.create_task(_alarm_v2_feed_readings(), name="alarm_v2_feed")
     alarm_v2_tick_task: asyncio.Task | None = None
     if _alarm_v2_configs:
         alarm_v2_tick_task = asyncio.create_task(_alarm_v2_tick(), name="alarm_v2_tick")
     sd_feed_task: asyncio.Task | None = None
     sd_tick_task: asyncio.Task | None = None
     if sensor_diag is not None:
         sd_feed_task = asyncio.create_task(_sensor_diag_feed(), name="sensor_diag_feed")
         sd_tick_task = asyncio.create_task(_sensor_diag_tick(), name="sensor_diag_tick")
     vt_feed_task: asyncio.Task | None = None
     vt_tick_task: asyncio.Task | None = None
     if vacuum_trend is not None:
         vt_feed_task = asyncio.create_task(_vacuum_trend_feed(), name="vacuum_trend_feed")
         vt_tick_task = asyncio.create_task(_vacuum_trend_tick(), name="vacuum_trend_tick")
     leak_rate_feed_task = asyncio.create_task(_leak_rate_feed(), name="leak_rate_feed")
     await housekeeping_service.start()
 
     # Watchdog
     watchdog_task = asyncio.create_task(
         _watchdog(broker, scheduler, writer, start_ts),
         name="engine_watchdog",
     )
 
     # DiskMonitor — also wires the writer so disk-recovery can clear the
     # _disk_full flag (Phase 2a H.1).
     disk_monitor = DiskMonitor(data_dir=_DATA_DIR, broker=broker, sqlite_writer=writer)
     await disk_monitor.start()
 
     logger.info(
         "═══ CryoDAQ Engine запущен ═══ | приборов=%d | тревог=%d | блокировок=%d | mock=%s",
         len(driver_configs),
         len(alarm_engine.get_state()),
         len(interlock_engine.get_state()),
         mock,
     )
 
     # --- Ожидание сигнала завершения ---
     shutdown_event = asyncio.Event()
 
     def _request_shutdown() -> None:
         logger.info("Получен сигнал завершения")
         shutdown_event.set()
 
     # Регистрация обработчиков сигналов
     loop = asyncio.get_running_loop()
     if sys.platform != "win32":
         loop.add_signal_handler(signal.SIGINT, _request_shutdown)
         loop.add_signal_handler(signal.SIGTERM, _request_shutdown)
     else:
         # Windows: signal.signal работает только в главном потоке
         signal.signal(signal.SIGINT, lambda *_: _request_shutdown())
 
     await shutdown_event.wait()
 
     # --- Корректное завершение ---
     logger.info("═══ Завершение CryoDAQ Engine ═══")
 
     watchdog_task.cancel()
@@ -1955,120 +2006,124 @@ async def _run_engine(*, mock: bool = False) -> None:
         pass
 
     alarm_v2_feed_task.cancel()
     try:
         await alarm_v2_feed_task
     except asyncio.CancelledError:
         pass
     if alarm_v2_tick_task is not None:
         alarm_v2_tick_task.cancel()
         try:
             await alarm_v2_tick_task
         except asyncio.CancelledError:
             pass
 
     if sd_feed_task is not None:
         sd_feed_task.cancel()
         try:
             await sd_feed_task
         except asyncio.CancelledError:
             pass
     if sd_tick_task is not None:
         sd_tick_task.cancel()
         try:
             await sd_tick_task
         except asyncio.CancelledError:
             pass
 
     if vt_feed_task is not None:
         vt_feed_task.cancel()
         try:
             await vt_feed_task
         except asyncio.CancelledError:
             pass
     if vt_tick_task is not None:
         vt_tick_task.cancel()
         try:
             await vt_tick_task
         except asyncio.CancelledError:
             pass
     leak_rate_feed_task.cancel()
     try:
         await leak_rate_feed_task
     except asyncio.CancelledError:
         pass
 
     # Порядок: scheduler → plugins → alarms → interlocks → writer → zmq
     await scheduler.stop()
     logger.info("Планировщик остановлен")
 
     await plugin_pipeline.stop()
     logger.info("Пайплайн плагинов остановлен")
 
     if cooldown_service is not None:
         await cooldown_service.stop()
         logger.info("CooldownService остановлен")
 
     if periodic_reporter is not None:
         await periodic_reporter.stop()
         logger.info("PeriodicReporter остановлен")
 
+    if gemma_agent is not None:
+        await gemma_agent.stop()
+        logger.info("GemmaAgent (Гемма) остановлен")
+
     if telegram_bot is not None:
         await telegram_bot.stop()
         logger.info("TelegramCommandBot остановлен")
 
     await alarm_engine.stop()
     logger.info("Движок тревог остановлен")
 
     await interlock_engine.stop()
     logger.info("Движок блокировок остановлен")
 
     await safety_manager.stop()
     logger.info("SafetyManager остановлен: состояние=%s", safety_manager.state.value)
 
     await disk_monitor.stop()
     logger.info("DiskMonitor остановлен")
 
     await housekeeping_service.stop()
     logger.info("HousekeepingService остановлен")
 
     await writer.stop()
     logger.info("SQLite записано: %d", writer.stats.get("total_written", 0))
 
     await cmd_server.stop()
     logger.info("ZMQ CommandServer остановлен")
 
     await zmq_pub.stop()
     logger.info("ZMQ Publisher остановлен")
 
     from cryodaq.drivers.transport.gpib import GPIBTransport
 
     GPIBTransport.close_all_managers()
     logger.info("GPIB ResourceManagers закрыты")
 
     uptime = time.monotonic() - start_ts
     logger.info(
         "═══ CryoDAQ Engine завершён ═══ | uptime=%.1f с",
         uptime,
     )
 
 
 # ---------------------------------------------------------------------------
 # Single-instance guard
 # ---------------------------------------------------------------------------
 
 _LOCK_FILE = get_data_dir() / ".engine.lock"
 
 
 def _is_pid_alive(pid: int) -> bool:
     """Check if process with given PID exists."""
     try:
         if sys.platform == "win32":
             import ctypes
 
             handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
             if handle:
                 ctypes.windll.kernel32.CloseHandle(handle)
                 return True
             return False
         else:
             os.kill(pid, 0)
---prompts
"""Prompt templates for GemmaAgent.

All operator-facing output is Russian per project standard (CryoDAQ is
a Russian-language product; operators are Russian-speaking).

Templates are versioned via inline comments. Update the revision note
when changing wording to maintain an audit trail for prompt evolution.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Alarm summary — Slice A
# Revision: 2026-05-01 v1 (initial)
# ---------------------------------------------------------------------------

ALARM_SUMMARY_SYSTEM = """\
Ты — Гемма, ассистент-аналитик в криогенной лаборатории. Твоя задача — \
краткий, точный summary сработавшего аларма для оператора в Telegram.

Принципы:
- Отвечай ТОЛЬКО на русском языке. Никакого английского в ответе.
- Не выдумывай контекст. Используй только данные из запроса ниже.
- Конкретные значения, не размытые описания.
- Если возможна причина — предложи. Если неясно — напиши "причина неясна".
- НИКОГДА не предлагай safety-действия автоматически (аварийное отключение, \
переключение фаз). Только наблюдения и предложения для оператора.
- 80-150 слов. Telegram-friendly Markdown (жирный, курсив — ok, заголовки — нет).
"""

ALARM_SUMMARY_USER = """\
АЛАРМ СРАБОТАЛ:
- ID: {alarm_id}
- Уровень: {level}
- Каналы: {channels}
- Значения: {values}

ТЕКУЩЕЕ СОСТОЯНИЕ:
- Фаза: {phase}
- Эксперимент: {experiment_id} (запущен {experiment_age})
- Целевая температура: {target_temp}
- Активные блокировки: {interlocks}

ПОСЛЕДНИЕ ПОКАЗАНИЯ (последние {lookback_s}с) на затронутых каналах:
{recent_readings}

ПОСЛЕДНИЕ АЛАРМЫ (последний час):
{recent_alarms}

Сформируй краткий summary для оператора в Telegram. Только русский язык.
"""

# ---------------------------------------------------------------------------
# Experiment finalize summary — Slice A
# Revision: 2026-05-01 v1 (initial)
# ---------------------------------------------------------------------------

EXPERIMENT_FINALIZE_SYSTEM = """\
Ты — Гемма, ассистент-аналитик в криогенной лаборатории. Твоя задача — \
краткое резюме завершённого эксперимента для оператора.

Принципы:
- Отвечай ТОЛЬКО на русском языке.
- Используй только данные из запроса.
- Конкретные факты: продолжительность, фазы, ключевые события.
- 80-120 слов. Telegram-friendly Markdown.
"""

EXPERIMENT_FINALIZE_USER = """\
ЭКСПЕРИМЕНТ ЗАВЕРШЁН:
- ID: {experiment_id}
- Название: {name}
- Продолжительность: {duration}
- Финальный статус: {status}

ФАЗЫ:
{phases}

АЛАРМЫ ЗА ЭКСПЕРИМЕНТ:
{alarms_summary}

Сформируй краткое резюме завершённого эксперимента. Только русский язык.
"""

exec
/opt/homebrew/bin/bash -lc "grep -R \"event_type=\\\"alarm_fired\\\"\\|alarm_fired\" -n src tests | head -80 && grep -R \"publish(.*EngineEvent\" -n src/cryodaq/core src/cryodaq/engine.py | head -80" in /Users/vladimir/Projects/cryodaq
 succeeded in 380ms:
src/cryodaq/core/event_bus.py:18:    event_type: str  # "alarm_fired", "alarm_cleared", "phase_transition", "experiment_finalize", …
Binary file src/cryodaq/agents/__pycache__/gemma.cpython-314.pyc matches
src/cryodaq/agents/gemma.py:76:        alarm_t = triggers.get("alarm_fired", {})
src/cryodaq/agents/gemma.py:167:        if event.event_type == "alarm_fired":
src/cryodaq/agents/gemma.py:195:                await self._handle_alarm_fired(event)
src/cryodaq/agents/gemma.py:203:    async def _handle_alarm_fired(self, event: EngineEvent) -> None:
src/cryodaq/agents/gemma.py:264:            "GemmaAgent: alarm_fired обработан (audit_id=%s, latency=%.1fs, dispatched=%s)",
Binary file src/cryodaq/__pycache__/engine.cpython-314.pyc matches
src/cryodaq/engine.py:1290:                                event_type="alarm_fired",
tests/core/test_event_bus.py:15:def _event(event_type: str = "alarm_fired", experiment_id: str | None = "exp-001") -> EngineEvent:
tests/core/test_event_bus.py:67:    ev = _event("alarm_fired")
tests/core/test_event_bus.py:74:    assert received.event_type == "alarm_fired"
tests/core/test_event_bus.py:100:    ev1 = _event("alarm_fired")
tests/core/test_event_bus.py:119:    await bus.publish(_event("alarm_fired"))
tests/core/test_event_bus.py:120:    await bus.publish(_event("alarm_fired"))
tests/core/test_event_bus.py:124:        await bus.publish(_event("alarm_fired"))
tests/core/test_event_bus.py:185:    await bus.publish(_event("alarm_fired"))
Binary file tests/core/__pycache__/test_event_bus.cpython-314-pytest-9.0.3.pyc matches
Binary file tests/agents/__pycache__/test_gemma_alarm_flow.cpython-314-pytest-9.0.3.pyc matches
tests/agents/test_gemma_alarm_flow.py:28:        event_type="alarm_fired",
tests/agents/test_gemma_alarm_flow.py:149:        "triggers": {"alarm_fired": {"min_level": "WARNING"}},
tests/agents/test_gemma_alarm_flow.py:182:# GemmaAgent — alarm_fired → LLM → dispatch
tests/agents/test_gemma_alarm_flow.py:186:async def test_alarm_fired_triggers_ollama_generate(tmp_path: Path) -> None:
tests/agents/test_gemma_alarm_flow.py:198:async def test_alarm_fired_dispatches_to_telegram(tmp_path: Path) -> None:
tests/agents/test_gemma_alarm_flow.py:213:async def test_alarm_fired_dispatches_to_operator_log(tmp_path: Path) -> None:
src/cryodaq/core/event_bus.py:47:    async def publish(self, event: EngineEvent) -> None:

exec
/opt/homebrew/bin/bash -lc "sed -n '1240,1325p' src/cryodaq/engine.py && sed -n '1,260p' src/cryodaq/core/alarm_v2.py && sed -n '1,220p' tests/core/test_alarm_event_bridge.py 2>/dev/null || true" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
            return

    # Strong-ref set for fire-and-forget Telegram dispatch tasks.
    # Without this the loop only weak-refs tasks and GC can drop a pending
    # alarm notification mid-flight. See DEEP_AUDIT_CC.md A.1/A.2/I.2.
    _alarm_dispatch_tasks: set[asyncio.Task] = set()

    async def _alarm_v2_tick() -> None:
        """Периодически вычислять алармы v2 и диспетчеризировать события."""
        poll_s = _alarm_v2_engine_cfg.poll_interval_s
        while True:
            await asyncio.sleep(poll_s)
            if not _alarm_v2_configs:
                continue
            current_phase = _alarm_v2_phase.get_current_phase()
            for alarm_cfg in _alarm_v2_configs:
                # Проверка фазового фильтра
                if alarm_cfg.phase_filter is not None:
                    if current_phase not in alarm_cfg.phase_filter:
                        # Вне фазы — явно очистить если был активен
                        alarm_v2_state_mgr.process(alarm_cfg.alarm_id, None, alarm_cfg.config)
                        continue
                try:
                    _active_alarms = alarm_v2_state_mgr.get_active()
                    _active_event = _active_alarms.get(alarm_cfg.alarm_id)
                    event = alarm_v2_evaluator.evaluate(
                        alarm_cfg.alarm_id,
                        alarm_cfg.config,
                        is_active=_active_event is not None,
                        active_channels=(
                            frozenset(_active_event.channels)
                            if _active_event is not None
                            else None
                        ),
                    )
                    transition = alarm_v2_state_mgr.process(
                        alarm_cfg.alarm_id, event, alarm_cfg.config
                    )
                    if transition == "TRIGGERED" and event is not None:
                        # GUI polls via alarm_v2_status command; optionally notify via Telegram
                        if "telegram" in alarm_cfg.notify and telegram_bot is not None:
                            msg = f"⚠ [{event.level}] {event.alarm_id}\n{event.message}"
                            t = asyncio.create_task(
                                telegram_bot._send_to_all(msg),
                                name=f"alarm_v2_tg_{alarm_cfg.alarm_id}",
                            )
                            _alarm_dispatch_tasks.add(t)
                            t.add_done_callback(_alarm_dispatch_tasks.discard)
                        await event_bus.publish(
                            EngineEvent(
                                event_type="alarm_fired",
                                timestamp=datetime.now(UTC),
                                payload={
                                    "alarm_id": event.alarm_id,
                                    "level": event.level,
                                    "message": event.message,
                                    "channels": event.channels,
                                    "values": event.values,
                                },
                                experiment_id=experiment_manager.active_experiment_id,
                            )
                        )
                    elif transition == "CLEARED":
                        await event_bus.publish(
                            EngineEvent(
                                event_type="alarm_cleared",
                                timestamp=datetime.now(UTC),
                                payload={"alarm_id": alarm_cfg.alarm_id},
                                experiment_id=experiment_manager.active_experiment_id,
                            )
                        )
                except Exception as exc:
                    logger.error("Alarm v2 tick error %s: %s", alarm_cfg.alarm_id, exc)

    # --- Sensor diagnostics feed + tick tasks ---
    async def _sensor_diag_feed() -> None:
        """Feed readings into SensorDiagnosticsEngine buffers."""
        if sensor_diag is None:
            return
        queue = await broker.subscribe("sensor_diag_feed", maxsize=2000)
        try:
            while True:
                reading: Reading = await queue.get()
                sensor_diag.push(
                    reading.channel,
                    reading.timestamp.timestamp(),
"""AlarmEngine v2 — физически обоснованные алармы с composite, rate, stale conditions.

Компоненты:
  AlarmEvent       — событие срабатывания аларма
  PhaseProvider    — интерфейс для получения текущей фазы эксперимента
  SetpointProvider — интерфейс для получения setpoints
  AlarmEvaluator   — вычисляет условие аларма → AlarmEvent | None
  AlarmStateManager — управляет состоянием (active/cleared), гистерезис, dedup

Физическое обоснование: docs/alarm_tz_physics_v3.md
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from cryodaq.core.channel_state import ChannelStateTracker
    from cryodaq.core.rate_estimator import RateEstimator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AlarmEvent
# ---------------------------------------------------------------------------


@dataclass
class AlarmEvent:
    """Событие срабатывания аларма."""

    alarm_id: str
    level: str  # "INFO" | "WARNING" | "CRITICAL"
    message: str
    triggered_at: float  # unix timestamp
    channels: list[str]  # каналы-участники
    values: dict[str, float]  # channel → значение на момент срабатывания
    acknowledged: bool = False
    acknowledged_at: float = 0.0
    acknowledged_by: str = ""


# ---------------------------------------------------------------------------
# AlarmTransition
# ---------------------------------------------------------------------------

AlarmTransition = Literal["TRIGGERED", "CLEARED"]


# ---------------------------------------------------------------------------
# Provider protocols (duck-typed, без runtime Protocol overhead)
# ---------------------------------------------------------------------------


class PhaseProvider:
    """Базовый провайдер фазы — заглушка для тестов."""

    def get_current_phase(self) -> str | None:
        return None

    def get_phase_elapsed_s(self) -> float:
        return 0.0


class SetpointProvider:
    """Базовый провайдер setpoints — заглушка для тестов."""

    def __init__(self, defaults: dict[str, float] | None = None) -> None:
        self._defaults: dict[str, float] = defaults or {}

    def get(self, key: str) -> float:
        return self._defaults.get(key, 0.0)


# ---------------------------------------------------------------------------
# AlarmEvaluator
# ---------------------------------------------------------------------------

_DEFAULT_RATE_WINDOW_S = 120.0


class AlarmEvaluator:
    """Вычисляет условие аларма по текущему состоянию системы.

    Параметры
    ----------
    state:
        ChannelStateTracker с текущими значениями каналов.
    rate:
        RateEstimator с оценками dX/dt.
    phase_provider:
        Провайдер текущей фазы эксперимента.
    setpoint_provider:
        Провайдер setpoints.
    """

    def __init__(
        self,
        state: ChannelStateTracker,
        rate: RateEstimator,
        phase_provider: PhaseProvider,
        setpoint_provider: SetpointProvider,
    ) -> None:
        self._state = state
        self._rate = rate
        self._phase = phase_provider
        self._setpoint = setpoint_provider

    def evaluate(
        self,
        alarm_id: str,
        alarm_config: dict[str, Any],
        *,
        is_active: bool = False,
        active_channels: frozenset[str] | None = None,
    ) -> AlarmEvent | None:
        """Проверить одну alarm-конфигурацию. None = не сработал.

        Parameters
        ----------
        is_active:
            True if this alarm is currently active in AlarmStateManager.
            Used by threshold evaluator to apply hysteresis deadband: alarm
            stays active until value clears ``threshold ± hysteresis``.
        active_channels:
            Set of channels that triggered the current active alarm event.
            When provided, hysteresis deadband is only applied to these
            channels — prevents a non-triggering channel from keeping a
            multi-channel alarm alive incorrectly.
        """
        alarm_type = alarm_config.get("alarm_type")
        try:
            if alarm_type == "threshold":
                return self._eval_threshold(
                    alarm_id, alarm_config,
                    is_active=is_active, active_channels=active_channels,
                )
            elif alarm_type == "composite":
                return self._eval_composite(alarm_id, alarm_config)
            elif alarm_type == "rate":
                return self._eval_rate(alarm_id, alarm_config)
            elif alarm_type == "stale":
                return self._eval_stale(alarm_id, alarm_config)
            else:
                logger.warning("Неизвестный alarm_type=%r для %s", alarm_type, alarm_id)
                return None
        except Exception as exc:
            logger.error("Ошибка evaluate %s: %s", alarm_id, exc, exc_info=True)
            return None

    # ------------------------------------------------------------------
    # threshold
    # ------------------------------------------------------------------

    def _eval_threshold(
        self,
        alarm_id: str,
        cfg: dict,
        *,
        is_active: bool = False,
        active_channels: frozenset[str] | None = None,
    ) -> AlarmEvent | None:
        check = cfg.get("check", "above")
        channels = self._resolve_channels(cfg)
        level = cfg.get("level", "WARNING")
        message_tmpl = cfg.get("message", f"Alarm {alarm_id}")
        hysteresis: float | None = cfg.get("hysteresis")

        for ch in channels:
            triggered, value = self._check_threshold_channel(ch, check, cfg)
            if triggered:
                msg = self._format_message(message_tmpl, channel=ch, value=value)
                return AlarmEvent(
                    alarm_id=alarm_id,
                    level=level,
                    message=msg,
                    triggered_at=time.time(),
                    channels=[ch],
                    values={ch: value},
                )
            # Hysteresis deadband (F21): if alarm is currently active, keep it
            # active until value clears threshold ± hysteresis margin. Returns a
            # "keep active" event that AlarmStateManager deduplicates (no new
            # TRIGGERED transition, no re-notification).
            # active_channels guard: only apply deadband to the channel(s) that
            # originally triggered the alarm; prevents a non-triggering channel
            # from keeping a multi-channel alarm alive indefinitely.
            if is_active and hysteresis is not None and check in ("above", "below"):
                if active_channels is not None and ch not in active_channels:
                    continue  # channel did not trigger this alarm; skip deadband
                threshold = cfg.get("threshold", 0.0)
                in_deadband = (check == "above" and value >= threshold - hysteresis) or (
                    check == "below" and value <= threshold + hysteresis
                )
                if in_deadband:
                    msg = self._format_message(message_tmpl, channel=ch, value=value)
                    return AlarmEvent(
                        alarm_id=alarm_id,
                        level=level,
                        message=msg,
                        triggered_at=time.time(),
                        channels=[ch],
                        values={ch: value},
                    )
        return None

    def _check_threshold_channel(self, channel: str, check: str, cfg: dict) -> tuple[bool, float]:
        """Возвращает (сработал, значение)."""
        if check == "fault_count_in_window":
            count = self._state.get_fault_count(channel)
            min_count = cfg.get("min_fault_count", 1)
            return count >= min_count, float(count)

        state = self._state.get(channel)
        if state is None:
            return False, 0.0
        value = state.value

        if check == "above":
            return value > cfg["threshold"], value
        elif check == "below":
            return value < cfg["threshold"], value
        elif check == "outside_range":
            r = cfg["range"]
            return (value < r[0] or value > r[1]), value
        elif check == "deviation_from_setpoint":
            setpoint = self._setpoint.get(cfg["setpoint_source"])
            return abs(value - setpoint) > cfg["threshold"], value
        else:
            logger.warning("Неизвестный threshold check=%r", check)
            return False, value

    # ------------------------------------------------------------------
    # composite
    # ------------------------------------------------------------------

    def _eval_composite(self, alarm_id: str, cfg: dict) -> AlarmEvent | None:
        operator = cfg.get("operator", "AND")
        conditions = cfg.get("conditions", [])
        level = cfg.get("level", "WARNING")
        message = cfg.get("message", f"Alarm {alarm_id}")

        results = [self._eval_condition(c) for c in conditions]

        if operator == "AND":
            fired = all(results)
        elif operator == "OR":
            fired = any(results)
        else:
            logger.warning("Неизвестный composite operator=%r", operator)
            return None

        if not fired:
            return None


exec
/opt/homebrew/bin/bash -lc "grep -R \"gemma_insight\\|gui_insight\" -n . --exclude-dir=.git --exclude='*.pyc'" in /Users/vladimir/Projects/cryodaq
2026-04-29T19:27:55.059395Z ERROR codex_core::tools::router: error=write_stdin failed: stdin is closed for this session; rerun exec_command with tty=true to keep stdin open
exec
/opt/homebrew/bin/bash -lc "git grep -n \"gemma_insight\\|gui_insight\" 535cc95 -- ." in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
535cc95:config/agent.yaml:26:    gui_insight_panel: true
535cc95:src/cryodaq/agents/gemma.py:55:    output_gui_insight: bool = True
535cc95:src/cryodaq/agents/gemma.py:82:        cfg.output_gui_insight = bool(outputs.get("gui_insight_panel", cfg.output_gui_insight))
535cc95:src/cryodaq/agents/gemma.py:277:    if config.output_gui_insight:
535cc95:src/cryodaq/agents/output_router.py:26:    GUI_INSIGHT = "gui_insight"
535cc95:src/cryodaq/agents/output_router.py:82:                            event_type="gemma_insight",
535cc95:src/cryodaq/agents/output_router.py:92:                    dispatched.append("gui_insight")
535cc95:tests/agents/test_gemma_alarm_flow.py:49:        output_gui_insight=False,
535cc95:tests/agents/test_gemma_alarm_flow.py:150:        "outputs": {"telegram": True, "operator_log": True, "gui_insight_panel": True},

exec
/opt/homebrew/bin/bash -lc "sed -n '1,240p' src/cryodaq/paths.py && git ls-files config | sed -n '1,50p' && grep -R \"get_config_dir\" -n tests src/cryodaq | head -50" in /Users/vladimir/Projects/cryodaq
 succeeded in 189ms:
Binary file src/cryodaq/core/__pycache__/channel_manager.cpython-314.pyc matches
src/cryodaq/core/channel_manager.py:16:from cryodaq.paths import get_config_dir as _get_config_dir
src/cryodaq/core/channel_manager.py:25:_DEFAULT_CONFIG = _get_config_dir() / "channels.yaml"
src/cryodaq/paths.py:48:def get_config_dir() -> Path:
Binary file src/cryodaq/__pycache__/paths.cpython-314.pyc matches
Binary file src/cryodaq/__pycache__/engine.cpython-314.pyc matches
src/cryodaq/engine.py:77:from cryodaq.paths import get_config_dir, get_data_dir, get_project_root
src/cryodaq/engine.py:88:_CONFIG_DIR = get_config_dir()
Binary file src/cryodaq/gui/shell/overlays/__pycache__/calibration_panel.cpython-314.pyc matches
src/cryodaq/gui/shell/overlays/calibration_panel.py:58:from cryodaq.paths import get_config_dir as _get_config_dir
src/cryodaq/gui/shell/overlays/calibration_panel.py:62:_INSTRUMENTS_DEFAULT = _get_config_dir() / "instruments.yaml"
src/cryodaq/gui/widgets/shift_handover.py:37:from cryodaq.paths import get_config_dir as _get_config_dir
src/cryodaq/gui/widgets/shift_handover.py:41:_CONFIG_PATH = _get_config_dir() / "shifts.yaml"
src/cryodaq/gui/widgets/connection_settings.py:33:from cryodaq.paths import get_config_dir as _get_config_dir
src/cryodaq/gui/widgets/connection_settings.py:37:_CONFIG_DIR = _get_config_dir()
Binary file src/cryodaq/gui/widgets/__pycache__/shift_handover.cpython-314.pyc matches
Binary file src/cryodaq/gui/widgets/__pycache__/connection_settings.cpython-314.pyc matches
Binary file src/cryodaq/gui/widgets/__pycache__/calibration_panel.cpython-314.pyc matches

exec
/opt/homebrew/bin/bash -lc "git grep -n \"experiment_finalize\\|experiment_stop\\|experiment_abort\" 535cc95 -- src tests | sed -n '1,240p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
535cc95:src/cryodaq/agents/gemma.py:172:        return False  # experiment_finalize and phase_transition handled in Cycle 3
535cc95:src/cryodaq/core/event_bus.py:18:    event_type: str  # "alarm_fired", "alarm_cleared", "phase_transition", "experiment_finalize", …
535cc95:src/cryodaq/core/zmq_bridge.py:33:# experiment_finalize / abort / create and calibration curve
535cc95:src/cryodaq/core/zmq_bridge.py:45:        "experiment_finalize",
535cc95:src/cryodaq/core/zmq_bridge.py:46:        "experiment_stop",
535cc95:src/cryodaq/core/zmq_bridge.py:47:        "experiment_abort",
535cc95:src/cryodaq/core/zmq_subprocess.py:189:            # server-side handler (experiment_finalize / report
535cc95:src/cryodaq/engine.py:595:    if action in {"experiment_finalize", "experiment_stop"}:
535cc95:src/cryodaq/engine.py:611:    if action == "experiment_abort":
535cc95:src/cryodaq/engine.py:1597:                "experiment_finalize",
535cc95:src/cryodaq/engine.py:1598:                "experiment_stop",
535cc95:src/cryodaq/engine.py:1599:                "experiment_abort",
535cc95:src/cryodaq/engine.py:1652:                    "experiment_finalize",
535cc95:src/cryodaq/engine.py:1653:                    "experiment_stop",
535cc95:src/cryodaq/engine.py:1654:                    "experiment_abort",
535cc95:src/cryodaq/engine.py:1657:                    if action == "experiment_abort":
535cc95:src/cryodaq/gui/shell/experiment_overlay.py:44:    experiment_finalized = Signal()
535cc95:src/cryodaq/gui/shell/experiment_overlay.py:844:        self._do_finalize("experiment_finalize")
535cc95:src/cryodaq/gui/shell/experiment_overlay.py:870:        self._do_finalize("experiment_abort")
535cc95:src/cryodaq/gui/shell/experiment_overlay.py:889:        if command == "experiment_abort":
535cc95:src/cryodaq/gui/shell/experiment_overlay.py:903:        self.experiment_finalized.emit()
535cc95:src/cryodaq/gui/shell/main_window_v2.py:321:            widget.experiment_finalized.connect(lambda: self._on_tool_clicked("home"))
535cc95:src/cryodaq/gui/widgets/experiment_dialogs.py:146:            "cmd": "experiment_finalize",
535cc95:tests/core/test_event_bus.py:82:    ev = _event("experiment_finalize")
535cc95:tests/core/test_experiment_commands.py:79:        "experiment_finalize",
535cc95:tests/core/test_experiment_commands.py:128:        "experiment_finalize",
535cc95:tests/core/test_experiment_commands.py:146:async def test_experiment_abort_command(manager: ExperimentManager) -> None:
535cc95:tests/core/test_experiment_commands.py:158:        "experiment_abort",
535cc95:tests/core/test_zmq_bridge.py:158:        "experiment_finalize",
535cc95:tests/core/test_zmq_bridge.py:159:        "experiment_stop",
535cc95:tests/core/test_zmq_bridge.py:160:        "experiment_abort",
535cc95:tests/core/test_zmq_bridge.py:193:    assert _timeout_for({"cmd": "experiment_finalize"}) == HANDLER_TIMEOUT_SLOW_S
535cc95:tests/core/test_zmq_bridge.py:280:    reply = await server._run_handler({"cmd": "experiment_finalize"})
535cc95:tests/core/test_zmq_bridge_subprocess_threading.py:177:    # handlers (experiment_finalize / report generation) have room to
535cc95:tests/gui/shell/overlays/test_archive_panel.py:530:            channel="analytics/experiment_finalized",
535cc95:tests/gui/shell/test_main_window_v2_archive_wiring.py:38:        channel="analytics/experiment_finalized",
535cc95:tests/gui/test_experiment_dialogs.py:73:    assert payload["cmd"] == "experiment_finalize"

exec
/opt/homebrew/bin/bash -lc 'pytest -q tests/agents/test_gemma_alarm_flow.py' in /Users/vladimir/Projects/cryodaq
 exited 127 in 0ms:
/opt/homebrew/bin/bash: line 1: pytest: command not found

exec
/opt/homebrew/bin/bash -lc "grep -n \"pytest\\|asyncio\" -n pyproject.toml setup.cfg pytest.ini tox.ini 2>/dev/null || true && ls" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
pyproject.toml:21:    "pyserial-asyncio>=0.6,<1",
pyproject.toml:51:    "pytest>=8",
pyproject.toml:52:    "pytest-asyncio>=0.23",
pyproject.toml:53:    "pytest-cov>=4",
pyproject.toml:54:    "pytest-timeout>=2.0",
pyproject.toml:83:[tool.pytest.ini_options]
pyproject.toml:85:asyncio_mode = "auto"
CC_PROMPT_CALIBRATION_2026-04-30.md
CC_PROMPT_DOCS_AUDIT_REWRITE_2026-04-30.md
CC_PROMPT_DOCS_REWRITE_PHASE2_2026-04-30.md
CC_PROMPT_F28_CYCLE0_MULTI_AUDIT_2026-05-01.md
CC_PROMPT_F28_HERMES_AGENT.md
CC_PROMPT_METASWARM_F17.md
CC_PROMPT_OVERNIGHT_2026-04-30.md
CC_PROMPT_OVERNIGHT_2026-05-01.md
CC_PROMPT_PARALLEL_WORK_2026-05-01.md
CC_PROMPT_REPO_CLEANUP_2026-04-30.md
CHANGELOG.md
CLAUDE.md
LICENSE
PROJECT_STATUS.md
README.md
RELEASE_CHECKLIST.md
ROADMAP.md
THIRD_PARTY_NOTICES.md
agentswarm
artifacts
build
build_scripts
config
create_shortcut.py
data
dist
docs
draft.py
draft2.py
graphify-out
graphify-out.stale-pre-merge
install.bat
logs
plugins
pyproject.toml
release_notes.py
requirements-lock.txt
scripts
src
start.bat
start.sh
start_mock.bat
start_mock.sh
tests
tools
tsp
~

exec
/opt/homebrew/bin/bash -lc "grep -R \"def _send_to_all\" -n src/cryodaq/notifications && sed -n '1,220p' src/cryodaq/notifications/telegram_commands.py" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
src/cryodaq/notifications/telegram_commands.py:456:    async def _send_to_all(self, text: str) -> None:
"""Интерактивный Telegram-бот: команды для удалённого мониторинга.

Опрашивает getUpdates в async-цикле и отвечает на команды:
/status, /temps, /pressure, /keithley, /alarms, /help.
Работает только с chat_id из списка allowed_chat_ids.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import aiohttp

from cryodaq.core.alarm import AlarmEngine
from cryodaq.core.broker import DataBroker

# Phase 2c Codex I.2: derive the accepted phase vocabulary from the canonical
# ExperimentPhase enum. Previously this was a hand-maintained list that
# drifted ("cooling"/"warming" instead of the enum's "cooldown"/"warmup",
# missing "vacuum") so remote operators received bogus "unknown phase"
# errors for phases that exist locally.
from cryodaq.core.experiment import ExperimentPhase as _ExperimentPhase
from cryodaq.drivers.base import Reading
from cryodaq.notifications._secrets import SecretStr

logger = logging.getLogger(__name__)

_SUBSCRIBE_NAME = "telegram_commands"
_HELP_TEXT = (
    "<b>CryoDAQ — команды бота</b>\n\n"
    "/status — состояние системы\n"
    "/temps — таблица температур\n"
    "/log &lt;текст&gt; — записать в операторский журнал\n"
    "/phase &lt;фаза&gt; — перевести эксперимент в фазу\n"
    "/pressure — уровень вакуума\n"
    "/keithley — показания Keithley (V, I, R, P)\n"
    "/alarms — активные тревоги\n"
    "/help — список команд"
)

VALID_PHASES: frozenset[str] = frozenset(p.value for p in _ExperimentPhase)
# Backwards-compatible aliases for Telegram clients that learned the old
# vocabulary. Mapped to canonical enum values at command-handler entry.
_PHASE_ALIASES: dict[str, str] = {
    "cooling": "cooldown",
    "warming": "warmup",
}
# Legacy mutable list kept for any callers that import it. Prefer VALID_PHASES.
_VALID_PHASES = sorted(VALID_PHASES)


class _TelegramAuthError(Exception):
    """Raised when Telegram API returns 401 or 404 (bad token)."""


class TelegramCommandBot:
    """Бот для обработки Telegram-команд.

    Параметры
    ----------
    broker:       DataBroker для подписки на данные.
    alarm_engine: AlarmEngine для запроса состояния тревог.
    bot_token:    Токен Telegram-бота (str или SecretStr).
    allowed_chat_ids: Список разрешённых chat_id. Phase 2b Codex K.1:
        пустой список + commands_enabled=True → ValueError при создании
        (default-deny — пустой ALLOW_ALL для safety-sensitive команд
        /phase / /log недопустим).
    commands_enabled: Если False, конструктор не валидирует allowed_chat_ids
        и бот стартует только для чтения (без обработки команд).
    poll_interval_s: Интервал опроса getUpdates.
    """

    def __init__(
        self,
        broker: DataBroker | None = None,
        alarm_engine: AlarmEngine | None = None,
        *,
        bot_token: str | SecretStr,
        allowed_chat_ids: list[int] | None = None,
        poll_interval_s: float = 2.0,
        command_handler: Callable[[dict], Awaitable[dict]] | None = None,
        commands_enabled: bool = True,
    ) -> None:
        # Phase 2b Codex K.1: default-deny — empty allowlist with commands
        # enabled would let any chat issue /phase and /log (safety-sensitive
        # control surface). Refuse to construct in that state.
        if commands_enabled and not (allowed_chat_ids or []):
            raise ValueError(
                "Telegram commands are enabled but allowed_chat_ids is empty. "
                "This would allow ANY chat to issue /phase and /log commands. "
                "Add at least one chat ID to config/notifications.local.yaml, "
                "or set commands.enabled: false."
            )

        self._broker = broker
        self._alarm_engine = alarm_engine
        # Phase 2b K.1: SecretStr wrapper.
        self._bot_token = bot_token if isinstance(bot_token, SecretStr) else SecretStr(bot_token)
        self._allowed_ids: set[int] = set(allowed_chat_ids or [])
        self._poll_interval_s = poll_interval_s
        self._command_handler = command_handler
        self._commands_enabled = commands_enabled

        # Runtime state — restored from the original constructor (the Phase 2b
        # rewrite of __init__ accidentally dropped these initializers).
        self._latest: dict[str, Reading] = {}
        self._start_time = datetime.now(UTC)
        self._last_update_id = 0
        self._collect_task: asyncio.Task[None] | None = None
        self._poll_task: asyncio.Task[None] | None = None
        self._queue: asyncio.Queue[Reading] | None = None
        self._session: aiohttp.ClientSession | None = None

    @property
    def _api(self) -> str:
        """Compute the Telegram API base URL on demand (no stored plain string)."""
        return f"https://api.telegram.org/bot{self._bot_token.get_secret_value()}"

    def _is_chat_allowed(self, chat_id: int) -> bool:
        """Default-deny chat permission check (Phase 2b Codex K.1)."""
        return chat_id in self._allowed_ids

    async def start(self) -> None:
        self._queue = await self._broker.subscribe(_SUBSCRIBE_NAME, maxsize=5000)
        self._collect_task = asyncio.create_task(self._collect_loop(), name="tg_cmd_collect")
        self._poll_task = asyncio.create_task(self._poll_loop(), name="tg_cmd_poll")
        logger.info(
            "TelegramCommandBot запущен | collect_task=%s poll_task=%s",
            self._collect_task.get_name(),
            self._poll_task.get_name(),
        )

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            # total=None чтобы long-poll (timeout=5 в params) не упирался в общий таймаут
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=None, connect=10, sock_read=30)
            )
        return self._session

    async def stop(self) -> None:
        for task in (self._collect_task, self._poll_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._collect_task = None
        self._poll_task = None
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
        await self._broker.unsubscribe(_SUBSCRIBE_NAME)
        logger.info("TelegramCommandBot остановлен")

    # ------------------------------------------------------------------
    # Data collection
    # ------------------------------------------------------------------

    async def _collect_loop(self) -> None:
        assert self._queue is not None
        try:
            while True:
                reading = await self._queue.get()
                self._latest[reading.channel] = reading
        except asyncio.CancelledError:
            return

    # ------------------------------------------------------------------
    # Telegram polling
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        logger.info("Telegram polling task started (interval=%.1fs)", self._poll_interval_s)
        iteration = 0
        backoff_s = self._poll_interval_s
        try:
            while True:
                iteration += 1
                logger.info("Telegram polling #%d, offset=%s", iteration, self._last_update_id)
                try:
                    await self._fetch_updates()
                    backoff_s = self._poll_interval_s  # сброс бэкоффа при успехе
                except _TelegramAuthError as exc:
                    # 401/404 — токен невалидный, не спамим
                    backoff_s = min(backoff_s * 2, 300)
                    logger.error(
                        "Telegram token error (#%d), backoff=%.0fs: %s",
                        iteration,
                        backoff_s,
                        exc,
                    )
                except Exception as exc:
                    logger.error("Telegram polling error (#%d): %s", iteration, exc, exc_info=True)
                await asyncio.sleep(backoff_s)
        except asyncio.CancelledError:
            logger.info("Telegram polling task cancelled after %d iterations", iteration)
            return

    async def _fetch_updates(self) -> None:
        url = f"{self._api}/getUpdates"
        params: dict[str, Any] = {"timeout": 5}
        if self._last_update_id:
            params["offset"] = self._last_update_id + 1

        session = await self._get_session()
        async with session.get(url, params=params) as resp:
            if resp.status != 200:
                body = await resp.text()
                logger.error("Telegram getUpdates HTTP %d: %s", resp.status, body[:300])
                if resp.status in (401, 404):
                    raise _TelegramAuthError(f"HTTP {resp.status}: {body[:100]}")
                return
            data = await resp.json()


exec
/opt/homebrew/bin/bash -lc "sed -n '440,490p' src/cryodaq/notifications/telegram_commands.py" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
    async def _send(self, chat_id: int, text: str) -> None:
        try:
            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
            session = await self._get_session()
            async with session.post(f"{self._api}/sendMessage", json=payload) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error("Telegram sendMessage %d: %s", resp.status, body[:200])
        except Exception as exc:
            logger.error("Ошибка отправки Telegram: %s", exc)

    async def _send_to_all(self, text: str) -> None:
        """Отправить текст всем разрешённым chat_id (или только первому если список пуст)."""
        if self._allowed_ids:
            for chat_id in self._allowed_ids:
                await self._send(chat_id, text)
        else:
            logger.debug("_send_to_all: нет allowed_chat_ids, сообщение не отправлено")

exec
/opt/homebrew/bin/bash -lc "grep -R \"def append_operator_log\" -n src/cryodaq/storage src/cryodaq/core && sed -n '1,120p' src/cryodaq/core/operator_log.py && grep -R \"tags\" -n src/cryodaq/storage/sqlite_writer.py | head -50" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
src/cryodaq/storage/sqlite_writer.py:597:    async def append_operator_log(
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


def normalize_operator_log_tags(tags: Any) -> tuple[str, ...]:
    if tags is None:
        return ()
    if isinstance(tags, str):
        parts = [item.strip() for item in tags.split(",")]
        return tuple(item for item in parts if item)
    if isinstance(tags, (list, tuple, set)):
        normalized = [str(item).strip() for item in tags if str(item).strip()]
        return tuple(normalized)
    raise ValueError("Operator log tags must be a string or a list of strings.")


@dataclass(frozen=True, slots=True)
class OperatorLogEntry:
    id: int
    timestamp: datetime
    experiment_id: str | None
    author: str
    source: str
    message: str
    tags: tuple[str, ...] = field(default_factory=tuple)

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "experiment_id": self.experiment_id,
            "author": self.author,
            "source": self.source,
            "message": self.message,
            "tags": list(self.tags),
        }
src/cryodaq/storage/sqlite_writer.py:23:from cryodaq.core.operator_log import OperatorLogEntry, normalize_operator_log_tags
src/cryodaq/storage/sqlite_writer.py:74:    tags          TEXT    NOT NULL DEFAULT '[]'
src/cryodaq/storage/sqlite_writer.py:455:        tags: tuple[str, ...],
src/cryodaq/storage/sqlite_writer.py:460:            "INSERT INTO operator_log (timestamp, experiment_id, author, source, message, tags) "
src/cryodaq/storage/sqlite_writer.py:468:                json.dumps(list(tags), ensure_ascii=False),
src/cryodaq/storage/sqlite_writer.py:479:            tags=tags,
src/cryodaq/storage/sqlite_writer.py:525:                    "SELECT id, timestamp, experiment_id, author, source, message, tags "
src/cryodaq/storage/sqlite_writer.py:540:                    tags = tuple(json.loads(row["tags"] or "[]"))
src/cryodaq/storage/sqlite_writer.py:549:                            tags=tags,
src/cryodaq/storage/sqlite_writer.py:604:        tags: list[str] | tuple[str, ...] | str | None = None,
src/cryodaq/storage/sqlite_writer.py:611:        normalized_tags = normalize_operator_log_tags(tags)
src/cryodaq/storage/sqlite_writer.py:621:            tags=normalized_tags,

exec
/opt/homebrew/bin/bash -lc "sed -n '580,635p' src/cryodaq/storage/sqlite_writer.py" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
    async def write_immediate(self, readings: list[Reading]) -> None:
        """Записать пакет синхронно (await до WAL commit).

        Используется Scheduler для гарантии persistence-first:
        данные попадают в DataBroker ТОЛЬКО после записи на диск.
        При ошибке — логирует CRITICAL и пробрасывает исключение.
        """
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(self._executor, self._write_batch, readings)
        except Exception:
            logger.critical(
                "CRITICAL: Ошибка write_immediate (%d записей) — данные НЕ персистированы",
                len(readings),
            )
            raise

    async def append_operator_log(
        self,
        *,
        message: str,
        author: str = "",
        source: str = "command",
        experiment_id: str | None = None,
        tags: list[str] | tuple[str, ...] | str | None = None,
        timestamp: datetime | None = None,
    ) -> OperatorLogEntry:
        text = message.strip()
        if not text:
            raise ValueError("Operator log message must not be empty.")

        normalized_tags = normalize_operator_log_tags(tags)
        entry_time = timestamp or datetime.now(UTC)
        loop = asyncio.get_running_loop()
        task = partial(
            self._write_operator_log_entry,
            timestamp=entry_time,
            experiment_id=experiment_id,
            author=author.strip(),
            source=source.strip() or "command",
            message=text,
            tags=normalized_tags,
        )
        return await loop.run_in_executor(self._executor, task)

    async def get_operator_log(
        self,
        *,
        experiment_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
    ) -> list[OperatorLogEntry]:
        loop = asyncio.get_running_loop()
        task = partial(
            self._read_operator_log,

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/agents/gemma.py | sed -n '60,95p;155,210p;230,255p' && nl -ba src/cryodaq/agents/output_router.py | sed -n '50,88p' && nl -ba src/cryodaq/agents/prompts.py | sed -n '16,32p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
    60	    @classmethod
    61	    def from_dict(cls, d: dict[str, Any]) -> GemmaConfig:
    62	        """Build from agent.yaml gemma section dict."""
    63	        cfg = cls()
    64	        cfg.enabled = bool(d.get("enabled", True))
    65	        ollama = d.get("ollama", {})
    66	        cfg.ollama_base_url = str(ollama.get("base_url", cfg.ollama_base_url))
    67	        cfg.default_model = str(ollama.get("default_model", cfg.default_model))
    68	        cfg.timeout_s = float(ollama.get("timeout_s", cfg.timeout_s))
    69	        cfg.temperature = float(ollama.get("temperature", cfg.temperature))
    70	        rl = d.get("rate_limit", {})
    71	        cfg.max_calls_per_hour = int(rl.get("max_calls_per_hour", cfg.max_calls_per_hour))
    72	        cfg.max_concurrent_inferences = int(
    73	            rl.get("max_concurrent_inferences", cfg.max_concurrent_inferences)
    74	        )
    75	        triggers = d.get("triggers", {})
    76	        alarm_t = triggers.get("alarm_fired", {})
    77	        if isinstance(alarm_t, dict):
    78	            cfg.alarm_min_level = str(alarm_t.get("min_level", cfg.alarm_min_level))
    79	        outputs = d.get("outputs", {})
    80	        cfg.output_telegram = bool(outputs.get("telegram", cfg.output_telegram))
    81	        cfg.output_operator_log = bool(outputs.get("operator_log", cfg.output_operator_log))
    82	        cfg.output_gui_insight = bool(outputs.get("gui_insight_panel", cfg.output_gui_insight))
    83	        slices = d.get("slices", {})
    84	        cfg.slice_a_notification = bool(slices.get("a_notification", cfg.slice_a_notification))
    85	        cfg.slice_b_suggestion = bool(slices.get("b_suggestion", cfg.slice_b_suggestion))
    86	        cfg.slice_c_campaign_report = bool(
    87	            slices.get("c_campaign_report", cfg.slice_c_campaign_report)
    88	        )
    89	        audit = d.get("audit", {})
    90	        cfg.audit_enabled = bool(audit.get("enabled", cfg.audit_enabled))
    91	        cfg.audit_retention_days = int(audit.get("retention_days", cfg.audit_retention_days))
    92	        return cfg
    93	
    94	
    95	class GemmaAgent:
   155	                    asyncio.create_task(
   156	                        self._safe_handle(event),
   157	                        name=f"gemma_{event.event_type}",
   158	                    )
   159	            except asyncio.CancelledError:
   160	                return
   161	            except Exception:
   162	                logger.warning("GemmaAgent: event loop error", exc_info=True)
   163	
   164	    def _should_handle(self, event: EngineEvent) -> bool:
   165	        if not self._config.slice_a_notification:
   166	            return False
   167	        if event.event_type == "alarm_fired":
   168	            level = event.payload.get("level", "INFO")
   169	            return _MIN_LEVELS.get(level, 0) >= _MIN_LEVELS.get(
   170	                self._config.alarm_min_level, 1
   171	            )
   172	        return False  # experiment_finalize and phase_transition handled in Cycle 3
   173	
   174	    def _check_rate_limit(self) -> bool:
   175	        """True if we can make a call now (hourly bucket)."""
   176	        now = time.monotonic()
   177	        cutoff = now - 3600.0
   178	        while self._call_timestamps and self._call_timestamps[0] < cutoff:
   179	            self._call_timestamps.popleft()
   180	        return len(self._call_timestamps) < self._config.max_calls_per_hour
   181	
   182	    async def _safe_handle(self, event: EngineEvent) -> None:
   183	        """Handle one event with rate-limit + semaphore + error isolation."""
   184	        if not self._check_rate_limit():
   185	            logger.warning(
   186	                "GemmaAgent: rate limit reached (%d/hr), dropping %s",
   187	                self._config.max_calls_per_hour,
   188	                event.event_type,
   189	            )
   190	            return
   191	
   192	        async with self._semaphore:
   193	            self._call_timestamps.append(time.monotonic())
   194	            try:
   195	                await self._handle_alarm_fired(event)
   196	            except (OllamaUnavailableError, OllamaModelMissingError) as exc:
   197	                logger.warning("GemmaAgent: Ollama недоступен — %s", exc)
   198	            except Exception:
   199	                logger.warning(
   200	                    "GemmaAgent: ошибка обработки %s", event.event_type, exc_info=True
   201	                )
   202	
   203	    async def _handle_alarm_fired(self, event: EngineEvent) -> None:
   204	        audit_id = self._audit.make_audit_id()
   205	        payload = event.payload
   206	
   207	        ctx = await self._ctx_builder.build_alarm_context(payload)
   208	        channels_str = ", ".join(ctx.channels) if ctx.channels else "—"
   209	        values_str = ", ".join(f"{k}={v}" for k, v in ctx.values.items()) if ctx.values else "—"
   210	        age_str = _format_age(ctx.experiment_age_s)
   230	            max_tokens=self._config.max_tokens,
   231	            temperature=self._config.temperature,
   232	        )
   233	
   234	        errors: list[str] = []
   235	        if result.truncated:
   236	            errors.append("timeout_truncated")
   237	            logger.warning("GemmaAgent: ответ обрезан по таймауту (audit_id=%s)", audit_id)
   238	
   239	        targets = _build_targets(self._config)
   240	        dispatched = await self._router.dispatch(
   241	            event, result.text, targets=targets, audit_id=audit_id
   242	        )
   243	
   244	        await self._audit.log(
   245	            audit_id=audit_id,
   246	            trigger_event={
   247	                "event_type": event.event_type,
   248	                "payload": payload,
   249	                "experiment_id": event.experiment_id,
   250	            },
   251	            context_assembled=user_prompt,
   252	            prompt_template="alarm_summary",
   253	            model=result.model,
   254	            system_prompt=ALARM_SUMMARY_SYSTEM,
   255	            user_prompt=user_prompt,
    50	    ) -> list[str]:
    51	        """Send llm_output to all configured targets.
    52	
    53	        Returns list of successfully dispatched target names.
    54	        """
    55	        dispatched: list[str] = []
    56	        prefixed = f"{_GEMMA_PREFIX} {llm_output}"
    57	
    58	        for target in targets:
    59	            try:
    60	                if target == OutputTarget.TELEGRAM:
    61	                    if self._telegram is not None:
    62	                        await self._telegram._send_to_all(prefixed)
    63	                        dispatched.append("telegram")
    64	                    else:
    65	                        logger.debug("OutputRouter: Telegram bot not configured, skipping")
    66	
    67	                elif target == OutputTarget.OPERATOR_LOG:
    68	                    await self._event_logger.log_event(
    69	                        "gemma",
    70	                        prefixed,
    71	                        extra_tags=["ai", audit_id],
    72	                    )
    73	                    dispatched.append("operator_log")
    74	
    75	                elif target == OutputTarget.GUI_INSIGHT:
    76	                    from datetime import UTC, datetime
    77	
    78	                    from cryodaq.core.event_bus import EngineEvent as _EngineEvent
    79	
    80	                    await self._event_bus.publish(
    81	                        _EngineEvent(
    82	                            event_type="gemma_insight",
    83	                            timestamp=datetime.now(UTC),
    84	                            payload={
    85	                                "text": llm_output,
    86	                                "trigger_event_type": trigger_event.event_type,
    87	                                "audit_id": audit_id,
    88	                            },
    16	
    17	ALARM_SUMMARY_SYSTEM = """\
    18	Ты — Гемма, ассистент-аналитик в криогенной лаборатории. Твоя задача — \
    19	краткий, точный summary сработавшего аларма для оператора в Telegram.
    20	
    21	Принципы:
    22	- Отвечай ТОЛЬКО на русском языке. Никакого английского в ответе.
    23	- Не выдумывай контекст. Используй только данные из запроса ниже.
    24	- Конкретные значения, не размытые описания.
    25	- Если возможна причина — предложи. Если неясно — напиши "причина неясна".
    26	- НИКОГДА не предлагай safety-действия автоматически (аварийное отключение, \
    27	переключение фаз). Только наблюдения и предложения для оператора.
    28	- 80-150 слов. Telegram-friendly Markdown (жирный, курсив — ok, заголовки — нет).
    29	"""
    30	
    31	ALARM_SUMMARY_USER = """\
    32	АЛАРМ СРАБОТАЛ:

 succeeded in 79917ms:
./artifacts/calibration/2026-05-01-f28-cycle2/full-prompt.md:65:  +    gui_insight_panel: true
./artifacts/calibration/2026-05-01-f28-cycle2/full-prompt.md:137:  +    output_gui_insight: bool = True
./artifacts/calibration/2026-05-01-f28-cycle2/full-prompt.md:164:  +        cfg.output_gui_insight = bool(outputs.get("gui_insight_panel", cfg.output_gui_insight))
./artifacts/calibration/2026-05-01-f28-cycle2/full-prompt.md:213:  +    GUI_INSIGHT = "gui_insight"
./artifacts/calibration/2026-05-01-f28-cycle2/full-prompt.md:269:  +                            event_type="gemma_insight",
./artifacts/calibration/2026-05-01-f28-cycle2/full-prompt.md:279:  +                    dispatched.append("gui_insight")
./artifacts/calibration/2026-05-01-f28-cycle2/full-prompt.md:522:  +        output_gui_insight=False,
./artifacts/calibration/2026-05-01-f28-cycle2/glm-prompt.md:49:  +    gui_insight_panel: true
./artifacts/calibration/2026-05-01-f28-cycle2/glm-prompt.md:121:  +    output_gui_insight: bool = True
./artifacts/calibration/2026-05-01-f28-cycle2/glm-prompt.md:148:  +        cfg.output_gui_insight = bool(outputs.get("gui_insight_panel", cfg.output_gui_insight))
./artifacts/calibration/2026-05-01-f28-cycle2/glm-prompt.md:197:  +    GUI_INSIGHT = "gui_insight"
./artifacts/calibration/2026-05-01-f28-cycle2/glm-prompt.md:253:  +                            event_type="gemma_insight",
./artifacts/calibration/2026-05-01-f28-cycle2/glm-prompt.md:263:  +                    dispatched.append("gui_insight")
./artifacts/calibration/2026-05-01-f28-cycle2/glm-prompt.md:506:  +        output_gui_insight=False,
./artifacts/calibration/2026-05-01-f28-cycle2/codex.response.md:312:      EventBus(gemma_insight). "🤖 Гемма:" prefix on all outputs.
./artifacts/calibration/2026-05-01-f28-cycle2/codex.response.md:371:+    gui_insight_panel: true
./artifacts/calibration/2026-05-01-f28-cycle2/codex.response.md:445:+    output_gui_insight: bool = True
./artifacts/calibration/2026-05-01-f28-cycle2/codex.response.md:472:+        cfg.output_gui_insight = bool(outputs.get("gui_insight_panel", cfg.output_gui_insight))
./artifacts/calibration/2026-05-01-f28-cycle2/codex.response.md:667:+    if config.output_gui_insight:
./artifacts/calibration/2026-05-01-f28-cycle2/codex.response.md:713:+    GUI_INSIGHT = "gui_insight"
./artifacts/calibration/2026-05-01-f28-cycle2/codex.response.md:769:+                            event_type="gemma_insight",
./artifacts/calibration/2026-05-01-f28-cycle2/codex.response.md:779:+                    dispatched.append("gui_insight")
./artifacts/calibration/2026-05-01-f28-cycle2/codex.response.md:1505:+        output_gui_insight=False,
./artifacts/calibration/2026-05-01-f28-cycle2/codex.response.md:1606:+        "outputs": {"telegram": True, "operator_log": True, "gui_insight_panel": True},
./artifacts/handoffs/2026-04-29-f28-cycle2-handoff.md:42:- **Safety** — no engine API accessible from agents/. OutputRouter only calls `_send_to_all`, `log_event`, `event_bus.publish("gemma_insight")` — all text-only channels
./artifacts/handoffs/2026-04-29-f28-cycle2-handoff.md:105:- GUI: `src/cryodaq/gui/shell/views/gemma_insight_panel.py` (~150 LOC)
./config/agent.yaml:26:    gui_insight_panel: true
./tests/agents/test_gemma_alarm_flow.py:49:        output_gui_insight=False,
./tests/agents/test_gemma_alarm_flow.py:150:        "outputs": {"telegram": True, "operator_log": True, "gui_insight_panel": True},
./CC_PROMPT_F28_HERMES_AGENT.md:289:  `gemma_insight` event_type, GUI subscribes (Cycle 4)
./CC_PROMPT_F28_HERMES_AGENT.md:364:    gui_insight_panel: true
./CC_PROMPT_F28_HERMES_AGENT.md:467:- GUI: `src/cryodaq/gui/shell/views/gemma_insight_panel.py`
./CC_PROMPT_F28_HERMES_AGENT.md:469:- Tests: extend test_gemma_alarm_flow + new test_gemma_insight_panel
./src/cryodaq/agents/output_router.py:26:    GUI_INSIGHT = "gui_insight"
./src/cryodaq/agents/output_router.py:82:                            event_type="gemma_insight",
./src/cryodaq/agents/output_router.py:92:                    dispatched.append("gui_insight")
./src/cryodaq/agents/gemma.py:55:    output_gui_insight: bool = True
./src/cryodaq/agents/gemma.py:82:        cfg.output_gui_insight = bool(outputs.get("gui_insight_panel", cfg.output_gui_insight))
./src/cryodaq/agents/gemma.py:277:    if config.output_gui_insight:

codex
The patch adds the intended Gemma alarm flow, but it leaves configured trigger disables ineffective and can send empty alarm summaries or leak in-flight inference tasks across shutdown. These are functional issues that should be fixed before considering the change correct.

Full review comments:

- [P2] Respect disabled alarm_fired triggers — /Users/vladimir/Projects/cryodaq/src/cryodaq/agents/gemma.py:75-78
  When `config/agent.yaml` sets `triggers.alarm_fired.enabled: false`, the agent still handles alarm events because `from_dict()` only reads `min_level` and `_should_handle()` only checks `slice_a_notification`. This makes the trigger-level kill switch in the shipped config ineffective; parse and store this `enabled` flag or remove the config knob.

- [P2] Avoid dispatching empty timeout responses — /Users/vladimir/Projects/cryodaq/src/cryodaq/agents/gemma.py:239-242
  When Ollama times out, `OllamaClient.generate()` returns `GenerationResult(text="", truncated=True)`, but this path still dispatches `result.text` to Telegram/log/GUI. In that scenario operators receive only the `🤖 Гемма:` prefix for a fired alarm, and the audit marks outputs as dispatched instead of reporting inference failure; skip routing or send an explicit fallback message when `result.truncated` and the text is empty.

- [P2] Track spawned handler tasks for shutdown — /Users/vladimir/Projects/cryodaq/src/cryodaq/agents/gemma.py:155-158
  Each alarm handler is created as an untracked background task, while `stop()` only cancels the queue loop and then closes the Ollama client. If shutdown happens during a slow inference, the `_safe_handle()` task can keep running after `GemmaAgent.stop()` returns and race with Telegram/writer shutdown; keep these tasks in a set and cancel/await them during `stop()`.
The patch adds the intended Gemma alarm flow, but it leaves configured trigger disables ineffective and can send empty alarm summaries or leak in-flight inference tasks across shutdown. These are functional issues that should be fixed before considering the change correct.

Full review comments:

- [P2] Respect disabled alarm_fired triggers — /Users/vladimir/Projects/cryodaq/src/cryodaq/agents/gemma.py:75-78
  When `config/agent.yaml` sets `triggers.alarm_fired.enabled: false`, the agent still handles alarm events because `from_dict()` only reads `min_level` and `_should_handle()` only checks `slice_a_notification`. This makes the trigger-level kill switch in the shipped config ineffective; parse and store this `enabled` flag or remove the config knob.

- [P2] Avoid dispatching empty timeout responses — /Users/vladimir/Projects/cryodaq/src/cryodaq/agents/gemma.py:239-242
  When Ollama times out, `OllamaClient.generate()` returns `GenerationResult(text="", truncated=True)`, but this path still dispatches `result.text` to Telegram/log/GUI. In that scenario operators receive only the `🤖 Гемма:` prefix for a fired alarm, and the audit marks outputs as dispatched instead of reporting inference failure; skip routing or send an explicit fallback message when `result.truncated` and the text is empty.

- [P2] Track spawned handler tasks for shutdown — /Users/vladimir/Projects/cryodaq/src/cryodaq/agents/gemma.py:155-158
  Each alarm handler is created as an untracked background task, while `stop()` only cancels the queue loop and then closes the Ollama client. If shutdown happens during a slow inference, the `_safe_handle()` task can keep running after `GemmaAgent.stop()` returns and race with Telegram/writer shutdown; keep these tasks in a set and cancel/await them during `stop()`.
