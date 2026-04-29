OpenAI Codex v0.124.0 (research preview)
--------
workdir: /Users/vladimir/Projects/cryodaq
model: gpt-5.5
provider: openai
approval: never
sandbox: read-only
reasoning effort: medium
reasoning summaries: none
session id: 019ddaa4-db84-7752-bb3b-dc0f6024faed
--------
user
commit 164a8da: F28 Cycle 1: Ollama client + audit + context builder
exec
/opt/homebrew/bin/bash -lc 'cat /Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6807e4de/skills/using-superpowers/SKILL.md' in /Users/vladimir/Projects/cryodaq
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

exec
/opt/homebrew/bin/bash -lc 'git status --short && git rev-parse --show-toplevel && git show --stat --oneline --decorate --no-renames 164a8da' in /Users/vladimir/Projects/cryodaq
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
?? artifacts/calibration/2026-05-01-f28-cycle1/
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
164a8da (HEAD -> feat/f28-hermes-agent) feat(f28): Cycle 1 — Ollama client + audit log + context builder skeleton
 pyproject.toml                        |   3 +
 src/cryodaq/agents/__init__.py        |   0
 src/cryodaq/agents/audit.py           |  86 +++++++++++
 src/cryodaq/agents/context_builder.py | 110 +++++++++++++
 src/cryodaq/agents/ollama_client.py   | 145 ++++++++++++++++++
 src/cryodaq/core/event_bus.py         |   2 +
 tests/agents/__init__.py              |   0
 tests/agents/test_ollama_client.py    | 281 ++++++++++++++++++++++++++++++++++
 8 files changed, 627 insertions(+)

exec
/opt/homebrew/bin/bash -lc 'git show --no-ext-diff --unified=80 --no-renames 164a8da -- src/cryodaq/agents/audit.py src/cryodaq/agents/context_builder.py src/cryodaq/agents/ollama_client.py src/cryodaq/core/event_bus.py pyproject.toml tests/agents/test_ollama_client.py' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
commit 164a8da64ba45c40d5280ef37a38f062166a2521
Author: Vladimir Fomenko <polsovatel111@gmail.com>
Date:   Wed Apr 29 22:07:20 2026 +0300

    feat(f28): Cycle 1 — Ollama client + audit log + context builder skeleton
    
    Pre-Cycle-2 fix: EventBus warns on duplicate subscribe name (LOW finding
    from Cycle 0 audit, ledger item carry-forward).
    
    New agents/ module (src/cryodaq/agents/):
    - ollama_client.py: async Ollama /api/generate wrapper. OllamaClient
      with configurable model/timeout. GenerationResult dataclass. Graceful
      errors: OllamaUnavailableError (connection refused), OllamaModelMissingError
      (model not pulled), truncated=True on timeout. Default model: gemma4:e4b.
    - audit.py: AuditLogger writes one JSON file per LLM call under
      data/agents/gemma/audit/<YYYY-MM-DD>/. Full schema per spec §2.8.
    - context_builder.py: ContextBuilder + AlarmContext dataclass. Slice A
      interface with experiment state assembly; SQLite reading/alarm history
      stubbed for Cycle 2 wiring.
    
    Tests: tests/agents/test_ollama_client.py — 16 unit (mock HTTP) + 1 smoke.
    Smoke test verified against real gemma4:e4b via Ollama: PASSED in 24.94s.
    
    Also: pyproject.toml registers 'smoke' pytest marker.
    
    Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

diff --git a/pyproject.toml b/pyproject.toml
index 1da84a7..1ad8206 100644
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -6,87 +6,90 @@ build-backend = "hatchling.build"
 name = "cryodaq"
 version = "0.44.0"
 description = "Система сбора данных для криогенной лаборатории (АКЦ ФИАН, Millimetron)"
 requires-python = ">=3.12"
 license = { file = "LICENSE" }
 authors = [
     { name = "Vladimir Fomenko" },
 ]
 dependencies = [
     # Phase 2c M.1: upper bounds added so a future major-version bump
     # cannot silently break the bundle build. Lockfile in
     # requirements-lock.txt pins exact versions for reproducible builds.
     "pyside6>=6.6,<7",
     "pyqtgraph>=0.13,<0.14",
     "pyvisa>=1.14,<2",
     "pyserial-asyncio>=0.6,<1",
     "pyzmq>=25,<27",
     "h5py>=3.10,<4",
     "pyyaml>=6.0,<7",
     "msgpack>=1.0,<2",
     "matplotlib>=3.8,<4",
     "aiohttp>=3.9.5,<4",
     "numpy>=1.26,<3",
     "scipy>=1.12,<2",
     "openpyxl>=3.1,<4",
     "python-docx>=1.1,<2",
     "pyqtdarktheme-fork>=2.3.6,<3",
     # IV.3 Finding 4: ToolRail uses qtawesome to render Phosphor icons
     # at runtime instead of shipping Lucide SVG files. Phosphor has
     # 1200+ icons vs. 10 SVGs previously; theming falls out naturally
     # because qta.icon(color=...) renders fresh on each call.
     "qtawesome>=1.4,<2",
     # IV.4 Finding 1: pyarrow promoted from [archive] extra to base.
     # Backend already exports Parquet best-effort on finalize; optional
     # install meant silent skip with "pyarrow not installed" warning
     # whenever the lab PC missed the extras. UI gains an explicit
     # Parquet export button in the same commit, so the feature must
     # work out of the box. Adds ~60 MB to the install footprint.
     # Upper bound set to <25 so the lockfile's pyarrow 23.x pin
     # resolves cleanly from the declared spec.
     "pyarrow>=15,<25",
 ]
 
 [project.optional-dependencies]
 dev = [
     "pytest>=8",
     "pytest-asyncio>=0.23",
     "pytest-cov>=4",
     "pytest-timeout>=2.0",
     "ruff>=0.3",
     "pyinstaller>=6.0",
     "pip-tools>=7.4",
 ]
 web = [
     "fastapi>=0.111",
     "uvicorn[standard]>=0.29",
 ]
 # IV.4 Finding 1: archive extra retained as a no-op alias so any
 # deployment / CI script pinned to `pip install -e ".[archive]"` keeps
 # working. pyarrow now ships in base deps (see above); this list is
 # intentionally empty.
 archive = []
 
 [project.scripts]
 cryodaq-engine = "cryodaq.engine:main"
 cryodaq-gui = "cryodaq.gui.app:main"
 cryodaq = "cryodaq.launcher:main"
 cryodaq-cooldown = "cryodaq.tools.cooldown_cli:main"
 # Frozen entry points — used by PyInstaller spec. Call freeze_support()
 # BEFORE importing PySide6 / cryodaq submodules to avoid Windows fork bomb.
 cryodaq-frozen = "cryodaq._frozen_main:main_launcher"
 cryodaq-frozen-engine = "cryodaq._frozen_main:main_engine"
 cryodaq-frozen-gui = "cryodaq._frozen_main:main_gui"
 
 [tool.hatch.build.targets.wheel]
 packages = ["src/cryodaq"]
 
 [tool.pytest.ini_options]
 testpaths = ["tests"]
 asyncio_mode = "auto"
+markers = [
+    "smoke: requires live external services (ollama, instruments); excluded from default CI",
+]
 
 [tool.ruff]
 target-version = "py312"
 line-length = 100
 
 [tool.ruff.lint]
 select = ["E", "F", "W", "I", "UP", "ASYNC"]
diff --git a/src/cryodaq/agents/audit.py b/src/cryodaq/agents/audit.py
new file mode 100644
index 0000000..8e21c64
--- /dev/null
+++ b/src/cryodaq/agents/audit.py
@@ -0,0 +1,86 @@
+"""Audit logger — persists every GemmaAgent LLM call for post-hoc review."""
+
+from __future__ import annotations
+
+import json
+import logging
+import uuid
+from datetime import UTC, datetime
+from pathlib import Path
+from typing import Any
+
+logger = logging.getLogger(__name__)
+
+
+class AuditLogger:
+    """Writes one JSON file per LLM call under audit_dir/<YYYY-MM-DD>/.
+
+    Schema per file matches docs/ORCHESTRATION spec §2.8 audit record.
+    Retention housekeeping (deleting old files) is handled by HousekeepingService.
+    """
+
+    def __init__(
+        self,
+        audit_dir: Path,
+        *,
+        enabled: bool = True,
+        retention_days: int = 90,
+    ) -> None:
+        self._audit_dir = Path(audit_dir)
+        self._enabled = enabled
+        self._retention_days = retention_days
+
+    def make_audit_id(self) -> str:
+        """Return a short unique ID for one audit record."""
+        return uuid.uuid4().hex[:12]
+
+    async def log(
+        self,
+        *,
+        audit_id: str,
+        trigger_event: dict[str, Any],
+        context_assembled: str,
+        prompt_template: str,
+        model: str,
+        system_prompt: str,
+        user_prompt: str,
+        response: str,
+        tokens: dict[str, int],
+        latency_s: float,
+        outputs_dispatched: list[str],
+        errors: list[str],
+    ) -> Path | None:
+        """Persist an audit record. Returns the file path, or None if disabled or failed."""
+        if not self._enabled:
+            return None
+
+        now = datetime.now(UTC)
+        date_dir = self._audit_dir / now.strftime("%Y-%m-%d")
+        date_dir.mkdir(parents=True, exist_ok=True)
+
+        filename = f"{now.strftime('%Y%m%dT%H%M%S%f')}_{audit_id}.json"
+        path = date_dir / filename
+
+        record: dict[str, Any] = {
+            "audit_id": audit_id,
+            "timestamp": now.isoformat(),
+            "trigger_event": trigger_event,
+            "context_assembled": context_assembled,
+            "prompt_template": prompt_template,
+            "model": model,
+            "system_prompt": system_prompt,
+            "user_prompt": user_prompt,
+            "response": response,
+            "tokens": tokens,
+            "latency_s": round(latency_s, 3),
+            "outputs_dispatched": outputs_dispatched,
+            "errors": errors,
+        }
+
+        try:
+            path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
+        except Exception:
+            logger.warning("AuditLogger: failed to write %s", path, exc_info=True)
+            return None
+
+        return path
diff --git a/src/cryodaq/agents/context_builder.py b/src/cryodaq/agents/context_builder.py
new file mode 100644
index 0000000..81b47b2
--- /dev/null
+++ b/src/cryodaq/agents/context_builder.py
@@ -0,0 +1,110 @@
+"""Context assembler for GemmaAgent LLM prompts.
+
+Each task type (alarm summary, diagnostic, campaign report) requires
+different context. Builders read SQLite state and format compact text
+for LLM token budget.
+
+Cycle 1: AlarmContext dataclass + build_alarm_context interface.
+SQLite queries and full context assembly wired in Cycle 2.
+Slice B (diagnostic) and Slice C (campaign) contexts deferred.
+"""
+
+from __future__ import annotations
+
+import logging
+from dataclasses import dataclass, field
+from typing import Any
+
+logger = logging.getLogger(__name__)
+
+
+@dataclass
+class AlarmContext:
+    """Context for alarm summary generation (Slice A)."""
+
+    alarm_id: str
+    level: str
+    channels: list[str]
+    values: dict[str, float]
+    phase: str | None
+    experiment_id: str | None
+    experiment_age_s: float | None
+    target_temp: float | None
+    active_interlocks: list[str] = field(default_factory=list)
+    recent_readings_text: str = ""
+    recent_alarms_text: str = ""
+
+
+class ContextBuilder:
+    """Assembles engine state for LLM prompt construction."""
+
+    def __init__(self, sqlite_reader: Any, experiment_manager: Any) -> None:
+        self._reader = sqlite_reader
+        self._em = experiment_manager
+
+    async def build_alarm_context(
+        self,
+        alarm_payload: dict[str, Any],
+        *,
+        lookback_s: float = 60.0,
+        recent_alarm_lookback_s: float = 3600.0,
+    ) -> AlarmContext:
+        """Assemble context for a Slice A alarm summary prompt.
+
+        Reads experiment state from ExperimentManager (in-memory, fast).
+        SQLite reading history and alarm history wired in Cycle 2.
+        """
+        alarm_id = alarm_payload.get("alarm_id", "unknown")
+        channels: list[str] = alarm_payload.get("channels", [])
+        values: dict[str, float] = alarm_payload.get("values", {})
+        level: str = alarm_payload.get("level", "WARNING")
+
+        experiment_id: str | None = getattr(self._em, "active_experiment_id", None)
+
+        phase: str | None = None
+        if hasattr(self._em, "get_current_phase"):
+            try:
+                phase = self._em.get_current_phase()
+            except Exception:
+                pass
+
+        experiment_age_s: float | None = _compute_experiment_age(self._em)
+
+        return AlarmContext(
+            alarm_id=alarm_id,
+            level=level,
+            channels=channels,
+            values=values,
+            phase=phase,
+            experiment_id=experiment_id,
+            experiment_age_s=experiment_age_s,
+            target_temp=None,
+            active_interlocks=[],
+            recent_readings_text=_readings_stub(channels, lookback_s),
+            recent_alarms_text=_alarms_stub(recent_alarm_lookback_s),
+        )
+
+
+def _compute_experiment_age(em: Any) -> float | None:
+    try:
+        history = em.get_phase_history()
+        if not history:
+            return None
+        first = history[0].get("started_at")
+        if not first:
+            return None
+        from datetime import UTC, datetime
+
+        started = datetime.fromisoformat(first)
+        return (datetime.now(UTC) - started.astimezone(UTC)).total_seconds()
+    except Exception:
+        return None
+
+
+def _readings_stub(channels: list[str], lookback_s: float) -> str:
+    ch = ", ".join(channels) if channels else "(none)"
+    return f"[Readings for {ch} over last {lookback_s:.0f}s — wired in Cycle 2]"
+
+
+def _alarms_stub(lookback_s: float) -> str:
+    return f"[Alarm history over last {lookback_s:.0f}s — wired in Cycle 2]"
diff --git a/src/cryodaq/agents/ollama_client.py b/src/cryodaq/agents/ollama_client.py
new file mode 100644
index 0000000..3a2b228
--- /dev/null
+++ b/src/cryodaq/agents/ollama_client.py
@@ -0,0 +1,145 @@
+"""Ollama HTTP client for local LLM inference."""
+
+from __future__ import annotations
+
+import asyncio
+import logging
+import time
+from dataclasses import dataclass
+from typing import Any
+
+import aiohttp
+
+logger = logging.getLogger(__name__)
+
+_GENERATE_PATH = "/api/generate"
+
+
+class OllamaUnavailableError(Exception):
+    """Ollama server unreachable (connection refused or network error)."""
+
+
+class OllamaModelMissingError(Exception):
+    """Requested model is not pulled on this Ollama instance."""
+
+    def __init__(self, model: str) -> None:
+        self.model = model
+        super().__init__(f"Model '{model}' not found. Run: ollama pull {model}")
+
+
+@dataclass
+class GenerationResult:
+    """Result of a single LLM generate call."""
+
+    text: str
+    tokens_in: int
+    tokens_out: int
+    latency_s: float
+    model: str
+    truncated: bool = False
+
+
+class OllamaClient:
+    """Async HTTP wrapper around Ollama /api/generate.
+
+    Manages one aiohttp.ClientSession; call close() on shutdown.
+    """
+
+    def __init__(
+        self,
+        base_url: str = "http://localhost:11434",
+        default_model: str = "gemma4:e4b",
+        *,
+        timeout_s: float = 30.0,
+    ) -> None:
+        self._base_url = base_url.rstrip("/")
+        self._default_model = default_model
+        self._timeout_s = timeout_s
+        self._session: aiohttp.ClientSession | None = None
+
+    async def _get_session(self) -> aiohttp.ClientSession:
+        if self._session is None or self._session.closed:
+            self._session = aiohttp.ClientSession()
+        return self._session
+
+    async def close(self) -> None:
+        """Close the underlying HTTP session."""
+        if self._session is not None and not self._session.closed:
+            await self._session.close()
+            self._session = None
+
+    async def generate(
+        self,
+        prompt: str,
+        *,
+        model: str | None = None,
+        max_tokens: int = 1024,
+        temperature: float = 0.3,
+        system: str | None = None,
+    ) -> GenerationResult:
+        """Call Ollama /api/generate and return a GenerationResult.
+
+        On timeout: returns truncated=True with empty text (does not raise).
+
+        Raises:
+            OllamaUnavailableError: server not reachable
+            OllamaModelMissingError: model not pulled
+        """
+        effective_model = model or self._default_model
+        url = f"{self._base_url}{_GENERATE_PATH}"
+        payload: dict[str, Any] = {
+            "model": effective_model,
+            "prompt": prompt,
+            "stream": False,
+            "options": {
+                "num_predict": max_tokens,
+                "temperature": temperature,
+            },
+        }
+        if system is not None:
+            payload["system"] = system
+
+        session = await self._get_session()
+        t0 = time.monotonic()
+
+        try:
+            async with asyncio.timeout(self._timeout_s):
+                async with session.post(url, json=payload) as resp:
+                    data: dict[str, Any] = await resp.json(content_type=None)
+        except TimeoutError:
+            latency_s = time.monotonic() - t0
+            logger.warning(
+                "OllamaClient: timeout after %.1fs for model %s",
+                latency_s,
+                effective_model,
+            )
+            return GenerationResult(
+                text="",
+                tokens_in=0,
+                tokens_out=0,
+                latency_s=latency_s,
+                model=effective_model,
+                truncated=True,
+            )
+        except aiohttp.ClientConnectorError as exc:
+            raise OllamaUnavailableError(
+                f"Cannot connect to Ollama at {self._base_url}: {exc}"
+            ) from exc
+        except aiohttp.ClientError as exc:
+            raise OllamaUnavailableError(f"Ollama HTTP error: {exc}") from exc
+
+        latency_s = time.monotonic() - t0
+
+        if "error" in data:
+            err = str(data["error"])
+            if "not found" in err.lower():
+                raise OllamaModelMissingError(effective_model)
+            raise OllamaUnavailableError(f"Ollama error: {err}")
+
+        return GenerationResult(
+            text=data.get("response", ""),
+            tokens_in=data.get("prompt_eval_count", 0),
+            tokens_out=data.get("eval_count", 0),
+            latency_s=latency_s,
+            model=data.get("model", effective_model),
+        )
diff --git a/src/cryodaq/core/event_bus.py b/src/cryodaq/core/event_bus.py
index 9c97978..d2f4271 100644
--- a/src/cryodaq/core/event_bus.py
+++ b/src/cryodaq/core/event_bus.py
@@ -1,60 +1,62 @@
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
+        if name in self._subscribers:
+            logger.warning("EventBus: duplicate subscribe '%s' — replacing existing queue", name)
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
diff --git a/tests/agents/test_ollama_client.py b/tests/agents/test_ollama_client.py
new file mode 100644
index 0000000..d6972d1
--- /dev/null
+++ b/tests/agents/test_ollama_client.py
@@ -0,0 +1,281 @@
+"""Tests for OllamaClient — mock HTTP + smoke test."""
+
+from __future__ import annotations
+
+from unittest.mock import AsyncMock, MagicMock, patch
+
+import pytest
+
+from cryodaq.agents.ollama_client import (
+    GenerationResult,
+    OllamaClient,
+    OllamaModelMissingError,
+    OllamaUnavailableError,
+)
+
+# ---------------------------------------------------------------------------
+# Helpers
+# ---------------------------------------------------------------------------
+
+
+def _mock_response(data: dict) -> MagicMock:
+    """Build a mock aiohttp async context manager returning data."""
+    resp = AsyncMock()
+    resp.json = AsyncMock(return_value=data)
+    cm = AsyncMock()
+    cm.__aenter__ = AsyncMock(return_value=resp)
+    cm.__aexit__ = AsyncMock(return_value=False)
+    return cm
+
+
+def _mock_session(response_cm) -> MagicMock:
+    s = AsyncMock()
+    s.closed = False
+    s.post = MagicMock(return_value=response_cm)
+    return s
+
+
+def _success_data(
+    text: str = "Гемма: всё в норме.",
+    tokens_in: int = 100,
+    tokens_out: int = 30,
+    model: str = "gemma3:e4b",
+) -> dict:
+    return {
+        "model": model,
+        "response": text,
+        "prompt_eval_count": tokens_in,
+        "eval_count": tokens_out,
+        "done": True,
+    }
+
+
+# ---------------------------------------------------------------------------
+# GenerationResult dataclass
+# ---------------------------------------------------------------------------
+
+
+def test_generation_result_fields() -> None:
+    r = GenerationResult(
+        text="response", tokens_in=10, tokens_out=5, latency_s=1.2, model="gemma3:e4b"
+    )
+    assert r.text == "response"
+    assert r.tokens_in == 10
+    assert r.tokens_out == 5
+    assert r.latency_s == 1.2
+    assert r.model == "gemma3:e4b"
+    assert r.truncated is False
+
+
+def test_generation_result_truncated_default_false() -> None:
+    r = GenerationResult(text="", tokens_in=0, tokens_out=0, latency_s=0.1, model="m")
+    assert r.truncated is False
+
+
+# ---------------------------------------------------------------------------
+# Successful generation
+# ---------------------------------------------------------------------------
+
+
+async def test_generate_returns_text_and_counts() -> None:
+    client = OllamaClient(default_model="gemma3:e4b")
+    client._session = _mock_session(_mock_response(_success_data()))
+
+    result = await client.generate("Summarize alarm")
+
+    assert result.text == "Гемма: всё в норме."
+    assert result.tokens_in == 100
+    assert result.tokens_out == 30
+    assert result.model == "gemma3:e4b"
+    assert not result.truncated
+
+
+async def test_generate_uses_default_model() -> None:
+    client = OllamaClient(default_model="qwen3:14b")
+    client._session = _mock_session(_mock_response(_success_data(model="qwen3:14b")))
+
+    await client.generate("test")
+
+    payload = client._session.post.call_args[1]["json"]
+    assert payload["model"] == "qwen3:14b"
+
+
+async def test_generate_overrides_model() -> None:
+    client = OllamaClient(default_model="gemma3:e4b")
+    client._session = _mock_session(_mock_response(_success_data(model="qwen3:14b")))
+
+    await client.generate("test", model="qwen3:14b")
+
+    payload = client._session.post.call_args[1]["json"]
+    assert payload["model"] == "qwen3:14b"
+
+
+async def test_generate_includes_system_prompt() -> None:
+    client = OllamaClient()
+    client._session = _mock_session(_mock_response(_success_data()))
+
+    await client.generate("prompt", system="Ты — Гемма.")
+
+    payload = client._session.post.call_args[1]["json"]
+    assert payload["system"] == "Ты — Гемма."
+
+
+async def test_generate_omits_system_when_none() -> None:
+    client = OllamaClient()
+    client._session = _mock_session(_mock_response(_success_data()))
+
+    await client.generate("prompt")
+
+    payload = client._session.post.call_args[1]["json"]
+    assert "system" not in payload
+
+
+async def test_generate_passes_options() -> None:
+    client = OllamaClient()
+    client._session = _mock_session(_mock_response(_success_data()))
+
+    await client.generate("p", max_tokens=512, temperature=0.1)
+
+    options = client._session.post.call_args[1]["json"]["options"]
+    assert options["num_predict"] == 512
+    assert options["temperature"] == 0.1
+
+
+async def test_generate_stream_false() -> None:
+    client = OllamaClient()
+    client._session = _mock_session(_mock_response(_success_data()))
+
+    await client.generate("p")
+
+    assert client._session.post.call_args[1]["json"]["stream"] is False
+
+
+# ---------------------------------------------------------------------------
+# Error cases
+# ---------------------------------------------------------------------------
+
+
+async def test_generate_raises_unavailable_on_connector_error() -> None:
+    import aiohttp
+
+    client = OllamaClient()
+    mock_session = AsyncMock()
+    mock_session.closed = False
+    mock_session.post = MagicMock(
+        side_effect=aiohttp.ClientError("connection refused")
+    )
+    client._session = mock_session
+
+    with pytest.raises(OllamaUnavailableError):
+        await client.generate("test")
+
+
+async def test_generate_raises_model_missing_on_not_found_error() -> None:
+    client = OllamaClient(default_model="no-such-model:latest")
+    err_data = {"error": "model 'no-such-model:latest' not found, try pulling it first"}
+    client._session = _mock_session(_mock_response(err_data))
+
+    with pytest.raises(OllamaModelMissingError) as exc_info:
+        await client.generate("test")
+
+    assert "no-such-model:latest" in str(exc_info.value)
+    assert "ollama pull" in str(exc_info.value)
+
+
+async def test_generate_model_missing_error_has_model_attr() -> None:
+    exc = OllamaModelMissingError("gemma3:e4b")
+    assert exc.model == "gemma3:e4b"
+    assert "ollama pull" in str(exc)
+
+
+async def test_generate_raises_unavailable_on_generic_error_response() -> None:
+    client = OllamaClient()
+    client._session = _mock_session(_mock_response({"error": "internal server error"}))
+
+    with pytest.raises(OllamaUnavailableError, match="internal server error"):
+        await client.generate("test")
+
+
+async def test_generate_returns_truncated_on_timeout() -> None:
+    client = OllamaClient(timeout_s=30.0)
+    client._session = _mock_session(_mock_response(_success_data()))  # prevent real session
+
+    timeout_cm = AsyncMock()
+    timeout_cm.__aenter__ = AsyncMock(side_effect=TimeoutError())
+    timeout_cm.__aexit__ = AsyncMock(return_value=False)
+
+    with patch("cryodaq.agents.ollama_client.asyncio.timeout", return_value=timeout_cm):
+        result = await client.generate("test")
+
+    assert result.truncated is True
+    assert result.text == ""
+    assert result.tokens_in == 0
+    assert result.tokens_out == 0
+
+
+# ---------------------------------------------------------------------------
+# Session lifecycle
+# ---------------------------------------------------------------------------
+
+
+async def test_close_clears_session() -> None:
+    client = OllamaClient()
+    mock_session = AsyncMock()
+    mock_session.closed = False
+    client._session = mock_session
+
+    await client.close()
+
+    mock_session.close.assert_awaited_once()
+    assert client._session is None
+
+
+async def test_close_noop_when_no_session() -> None:
+    client = OllamaClient()
+    await client.close()  # should not raise
+
+
+# ---------------------------------------------------------------------------
+# Smoke test — requires running Ollama + gemma4:4b (or configured model)
+# ---------------------------------------------------------------------------
+
+
+@pytest.mark.smoke
+async def test_smoke_real_ollama() -> None:
+    """Real Ollama inference — requires: ollama serve + model pulled.
+
+    Run with: pytest -m smoke tests/agents/test_ollama_client.py -v
+    """
+    import subprocess
+
+    result_ls = subprocess.run(  # noqa: ASYNC221
+        ["ollama", "list"], capture_output=True, text=True, timeout=5
+    )
+    available = result_ls.stdout
+
+    if "gemma4:e4b" in available:
+        model = "gemma4:e4b"
+    elif "gemma4" in available:
+        model = "gemma4:26b"
+    elif "qwen3:14b" in available:
+        model = "qwen3:14b"
+    else:
+        pytest.skip("No known model available in ollama list")
+
+    client = OllamaClient(
+        base_url="http://localhost:11434",
+        default_model=model,
+        timeout_s=120.0,
+    )
+    try:
+        result = await client.generate(
+            "Reply with exactly the word: PASS",
+            system="You are a test assistant. Reply with only the exact word requested.",
+            max_tokens=10,
+            temperature=0.0,
+        )
+        assert not result.truncated, f"Timed out. model={model}"
+        assert result.tokens_out > 0, f"No tokens generated. model={model}"
+        assert len(result.text.strip()) > 0, f"Empty response. model={model}"
+    finally:
+        await client.close()

exec
/opt/homebrew/bin/bash -lc "nl -ba tests/agents/test_ollama_client.py | sed -n '240,281p'
nl -ba pyproject.toml | sed -n '70,95p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   240	# ---------------------------------------------------------------------------
   241	
   242	
   243	@pytest.mark.smoke
   244	async def test_smoke_real_ollama() -> None:
   245	    """Real Ollama inference — requires: ollama serve + model pulled.
   246	
   247	    Run with: pytest -m smoke tests/agents/test_ollama_client.py -v
   248	    """
   249	    import subprocess
   250	
   251	    result_ls = subprocess.run(  # noqa: ASYNC221
   252	        ["ollama", "list"], capture_output=True, text=True, timeout=5
   253	    )
   254	    available = result_ls.stdout
   255	
   256	    if "gemma4:e4b" in available:
   257	        model = "gemma4:e4b"
   258	    elif "gemma4" in available:
   259	        model = "gemma4:26b"
   260	    elif "qwen3:14b" in available:
   261	        model = "qwen3:14b"
   262	    else:
   263	        pytest.skip("No known model available in ollama list")
   264	
   265	    client = OllamaClient(
   266	        base_url="http://localhost:11434",
   267	        default_model=model,
   268	        timeout_s=120.0,
   269	    )
   270	    try:
   271	        result = await client.generate(
   272	            "Reply with exactly the word: PASS",
   273	            system="You are a test assistant. Reply with only the exact word requested.",
   274	            max_tokens=10,
   275	            temperature=0.0,
   276	        )
   277	        assert not result.truncated, f"Timed out. model={model}"
   278	        assert result.tokens_out > 0, f"No tokens generated. model={model}"
   279	        assert len(result.text.strip()) > 0, f"Empty response. model={model}"
   280	    finally:
   281	        await client.close()
    70	cryodaq-engine = "cryodaq.engine:main"
    71	cryodaq-gui = "cryodaq.gui.app:main"
    72	cryodaq = "cryodaq.launcher:main"
    73	cryodaq-cooldown = "cryodaq.tools.cooldown_cli:main"
    74	# Frozen entry points — used by PyInstaller spec. Call freeze_support()
    75	# BEFORE importing PySide6 / cryodaq submodules to avoid Windows fork bomb.
    76	cryodaq-frozen = "cryodaq._frozen_main:main_launcher"
    77	cryodaq-frozen-engine = "cryodaq._frozen_main:main_engine"
    78	cryodaq-frozen-gui = "cryodaq._frozen_main:main_gui"
    79	
    80	[tool.hatch.build.targets.wheel]
    81	packages = ["src/cryodaq"]
    82	
    83	[tool.pytest.ini_options]
    84	testpaths = ["tests"]
    85	asyncio_mode = "auto"
    86	markers = [
    87	    "smoke: requires live external services (ollama, instruments); excluded from default CI",
    88	]
    89	
    90	[tool.ruff]
    91	target-version = "py312"
    92	line-length = 100
    93	
    94	[tool.ruff.lint]
    95	select = ["E", "F", "W", "I", "UP", "ASYNC"]

exec
/opt/homebrew/bin/bash -lc "grep -R \"gemma4\\|GemmaAgent\\|audit\" -n docs src tests | head -80" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:26:8.  Gemini audit status + what to do with the result
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:150:is a focused known bug, not a time for broad audit. Agreed,
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:376:not a deep audit. Correct tool for polish, wrong for this
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:392:### Evening — second deep Gemini audit dispatched
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:394:Vladimir then asked for a "настоящий deep audit". I wrote a
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:405:If the audit returns while GLM is in charge:
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:415:5. Save Gemini's output to `docs/gemini_B1_audit_2026-04-20.md`
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:481:design system handoff notes, phase-ui-1 findings, audit reports,
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:1069:## 8. Gemini audit status
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:1071:### First audit: shallow / dismissed
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:1077:  real audit since it blocks production)
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:1083:### Second audit: deep / dispatched
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:1100:1. **Save it.** Write to `docs/gemini_B1_audit_2026-04-20.md`
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:1120:   probably didn't know about today's commits since the audit
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:1224:Gemini: Google AI Pro, 1000 req/day via OAuth. Deep audit
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:1900:Gemini's shallow audit claimed "archive globs 1000 metadata
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:1903:Trust your data over model bullshit. GLM — if any audit
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:1946:### Pre-emptive "fix all the Gemini audit findings"
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:1948:First shallow audit had 10+ findings. Vladimir could have
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:1988:6. **Gemini audit integration** — see section 8.
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:2237:5. Check Gemini audit arrived and was integrated.
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:2463:and that might be useful for comparing against Gemini's audit
docs/handoffs-archive/2026-04/DOC_REALITY_MAP.md:4:> See CHANGELOG.md for full details. A fresh full audit against `35f2798` (v0.42.0) is pending.
docs/handoffs-archive/2026-04/DOC_REALITY_MAP.md:72:| `DEEP_AUDIT_CC.md` | 940 | untracked | CC deep audit (Phase 1, 15 areas A-O) |
docs/handoffs-archive/2026-04/DOC_REALITY_MAP.md:73:| `DEEP_AUDIT_CC_POST_2C.md` | 1240 | 2026-04-09 | CC deep audit post-Phase 2c (51 findings) |
docs/handoffs-archive/2026-04/DOC_REALITY_MAP.md:74:| `DEEP_AUDIT_CODEX.md` | 438 | untracked | Codex audit companion to DEEP_AUDIT_CC |
docs/handoffs-archive/2026-04/DOC_REALITY_MAP.md:75:| `DEEP_AUDIT_CODEX_POST_2C.md` | 763 | 2026-04-09 | Codex audit companion post-Phase 2c |
docs/handoffs-archive/2026-04/DOC_REALITY_MAP.md:76:| `CONFIG_FILES_AUDIT.md` | 719 | 2026-04-09 | Config file security and completeness audit |
docs/handoffs-archive/2026-04/DOC_REALITY_MAP.md:80:| `MASTER_TRIAGE.md` | 307 | 2026-04-09 | Triage of all open audit findings |
docs/handoffs-archive/2026-04/DOC_REALITY_MAP.md:367:These 10+ audit documents are **point-in-time snapshots** from 2026-04-09. They are not living documents and are not expected to stay current. No DRIFT/STALE analysis needed — they serve as historical records.
docs/handoffs-archive/2026-04/DOC_REALITY_MAP.md:378:| 4 | No blocking I/O on engine event loop | ⚠ PARTIALLY | reporting/generator.py:180 uses `subprocess.run()` (sync) — called from async context. Known audit finding. |
docs/handoffs-archive/2026-04/DOC_REALITY_MAP.md:400:Team lead agent skill definition (475 lines). References project structure and conventions. Not audited in detail — it's an agent prompt, not a code-reality claim.
docs/handoffs-archive/2026-04/DOC_REALITY_MAP.md:433:**Gap:** No dedicated documentation for config file formats, valid keys, defaults, and interactions. The existing `CONFIG_FILES_AUDIT.md` is a one-time audit, not a living reference.
docs/handoffs-archive/2026-04/DOC_REALITY_MAP.md:449:### 7.4 Consolidate audit documents
docs/handoffs-archive/2026-04/DOC_REALITY_MAP.md:451:**Gap:** 10+ audit/deep-dive documents at repo root create visual noise. They are point-in-time snapshots, not living docs.
docs/handoffs-archive/2026-04/DOC_REALITY_MAP.md:453:**Change:** Move all audit docs to `docs/audits/` subdirectory. No content changes.
docs/handoffs-archive/2026-04/DOC_REALITY_MAP.md:475:2. **7.4 (audit doc consolidation) is more invasive than stated.** Root-level audit filenames are referenced from code comments (e.g. atomic_write.py:11 references DEEP_AUDIT_CC.md D.3) and from MASTER_TRIAGE.md. Moving files requires updating cross-references.
docs/handoffs-archive/2026-04/DOC_REALITY_MAP.md:491:3. **Web dashboard HTML/JS:** `web/server.py` includes embedded HTML template with JavaScript — not audited for XSS or correctness
docs/handoffs-archive/2026-04/DOC_REALITY_MAP.md:493:5. **GUI tab list accuracy:** CLAUDE.md lists 10 GUI tabs (lines 94-105) — GUI is excluded from this audit
docs/handoffs-archive/2026-04/DOC_REALITY_MAP.md:504:Single comprehensive audit covering inventory, correspondence, and recommendations.
docs/handoffs-archive/2026-04/DOC_REALITY_MAP.md:510:**Recommendation corrections:** Reclassified quick wins 3-7 as structural. Warned against making CLAUDE.md exhaustively mirror all 62 modules. Advised against premature CHANGELOG entry. Flagged audit-doc-move as more invasive than estimated due to cross-references in code comments.
docs/handoffs-archive/2026-04/ui-superseded/DESIGN_SYSTEM.md:1201:5. **Лог в служебном логе** — всегда, для всего (audit trail, не feedback)
docs/handoffs-archive/2026-04/ui-superseded/UI_REWORK_ROADMAP.md:101:- Density audit на разных разрешениях
docs/handoffs-archive/2026-04/ui-superseded/UI_REWORK_ROADMAP.md:104:- Accessibility audit (keyboard nav, focus order, contrast verification)
docs/handoffs-archive/2026-04/ui-superseded/UI_REWORK_ROADMAP.md:111:- Accessibility audit passes
docs/handoffs-archive/2026-04/ui-superseded/UI_REWORK_ROADMAP.md:214:**Block 4:** setStyleSheet audit (classification document, read-only)
docs/handoffs-archive/2026-04/ui-superseded/UI_REWORK_ROADMAP.md:293:1. **Density audit** — проверка на разных разрешениях (1366×768 compact,
docs/handoffs-archive/2026-04/ui-superseded/UI_REWORK_ROADMAP.md:298:4. **Accessibility audit**:
docs/handoffs-archive/2026-04/ui-superseded/UI_REWORK_ROADMAP.md:312:- Accessibility audit passes (AA minimum для все interactive elements)
docs/handoffs-archive/2026-04/HANDOFF_2026-04-20_GLM.md:39:  Conclusion audit format.
docs/handoffs-archive/2026-04/HANDOFF_2026-04-20_GLM.md:420:- **A Gemini deep B1 audit was dispatched earlier today.** It was
docs/handoffs-archive/2026-04/HANDOFF_2026-04-20_GLM.md:424:  audit result was not yet returned. If it has arrived by the time
docs/handoffs-archive/2026-04/HANDOFF_2026-04-20_GLM.md:427:  surface review), the deep-audit prompt required 60-90 min of
docs/handoffs-archive/2026-04/HANDOFF_2026-04-20_GLM.md:557:### Task E — Gemini audit integration (when it arrives)
docs/handoffs-archive/2026-04/HANDOFF_2026-04-20_GLM.md:559:Check `~/.gemini/sessions/` or ask Vladimir. If the deep B1 audit
docs/handoffs-archive/2026-04/HANDOFF_2026-04-20_GLM.md:612:5. Do NOT run `/ultrareview` or similar broad-scope audits to "find
docs/handoffs-archive/2026-04/HANDOFF_2026-04-20_GLM.md:614:   review. Breadth-first audit now expands scope catastrophically.
docs/ORCHESTRATION.md:5:findings from vault build/audit, B1 investigation closure, and `.cof`
docs/ORCHESTRATION.md:28:  `.audit-run/`, `agentswarm/`) each containing state of a
docs/ORCHESTRATION.md:135:- "Review everything" (→ shallow audits, see 2026-04-20
docs/ORCHESTRATION.md:242:├── audits/                   ← archived historical audits, one subdir per date
docs/ORCHESTRATION.md:278:this rule. Place under `docs/audits/<date>-<slug>/` or
docs/ORCHESTRATION.md:281:grandfathered into `docs/audits/2026-04-21-agent-swarm/` and
docs/ORCHESTRATION.md:310:`.swarm/`, `.omc/`, `.audit-run/`, `agentswarm/`, `.scratch/`
docs/ORCHESTRATION.md:438:| Repo cleanup | this document, §§ 6, 5.2 | ✅ DONE (commits `adb49fe`..`8ebc893`, 2026-04-23) — 12 root .md archived (11 to audits, 1 preserved as blessed dossier), agent workspaces gitignored, duplicate branches pruned, worktree naming aligned |
docs/ORCHESTRATION.md:461:   review / hardening / audit passes, no clear home, mostly
docs/ORCHESTRATION.md:496:7. **Vault/doc propagation gap.** 2026-04-27 vault audit: Т4
docs/ORCHESTRATION.md:501:   because audit fixes were per-flagged-file rather than per-claim.
docs/ORCHESTRATION.md:507:   migration audit: Codex audited `calibration.py` per declared
docs/ORCHESTRATION.md:582:  - Plan documents / agent outputs → `docs/audits/<date-slug>/`
docs/ORCHESTRATION.md:584:  - Uncertain category → `docs/audits/<date-slug>/uncategorized/`
docs/ORCHESTRATION.md:638:dual-verifier patterns surfaced through vault build, vault audit,
docs/ORCHESTRATION.md:670:- **Gemini** (`gemini-3.1-pro-preview`): wide-context audit, finds
docs/ORCHESTRATION.md:675:The 2026-04-28 `.cof` migration audit demonstrated the pattern:
docs/ORCHESTRATION.md:703:The 2026-04-27 vault audit caught Т4 interlock fact landing
docs/ORCHESTRATION.md:706:notes, one fact, propagation incomplete because audit fixes were
docs/ORCHESTRATION.md:764:When a metaswarm or multi-model audit produces CRITICAL or HIGH
docs/ORCHESTRATION.md:832:- `--sandbox workspace-write` — DEFAULT for review/audit tasks.
docs/ORCHESTRATION.md:837:For audit + review use workspace-write. NOT none.
docs/safety-operator.md:8:  в docs/audits/2026-04-09/SAFETY_MANAGER_DEEP_DIVE.md)

exec
/opt/homebrew/bin/bash -lc "grep -R \"GemmaAgent\\|Ollama\\|audit record\\|context\" -n docs | head -120" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:7:Claude Opus, or human reader) need context beyond the primary
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:11:session, burning the last of the weekly context quota to make sure
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:40:- A. Vladimir's personal context, condensed
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:77:### Morning — context inherited from previous session
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:365:context. That's the origin of the primary handoff and this
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:413:   Gemini has 1M context and could have spotted something
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:543:No Codex self-review (trivial surgical fix, not worth the context cost).
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:921:- Explains why recreating the socket on the same context didn't
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:922:  help (ZMQ context retains state beyond just the socket)
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:1115:   Gemini has 1M context and could have found something the
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:1133:│   ├─ hooks (pytest Stop, inject_context, RTK)    │
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:1184:/model chutes,moonshotai/Kimi-K2.5-TEE      # Kimi (256K context)
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:1887:prioritized preserving context over doing more work. Signal:
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:1888:when resources are tight, shift to defensive context
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:1925:because the conversation context was full (IV.6 + xml_safe
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:1928:**When `/ultrareview` makes sense:** clean CC context, green
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:2100:If you write your own: `with contextlib.suppress(FileNotFoundError):
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:2272:## Appendix A — Vladimir's personal context (condensed)
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:2335:Claude's context:
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:2536:> known-buggy for REQ timeout + reconnect on same context.
docs/handoffs-archive/2026-04/SESSION_DETAIL_2026-04-20.md:2586:Opus 4.7 (web) as final context preservation before weekly
docs/handoffs-archive/2026-04/DOC_REALITY_MAP.md:231:| `.claude/hooks/inject_context.py` | Claude Code hook for branch-aware context injection |
docs/handoffs-archive/2026-04/DOC_REALITY_MAP.md:300:| L204: No blocking I/O on engine event loop | ⚠ DRIFT | reporting/generator.py uses sync subprocess.run in async context (DEEP_AUDIT finding E.2) |
docs/handoffs-archive/2026-04/DOC_REALITY_MAP.md:378:| 4 | No blocking I/O on engine event loop | ⚠ PARTIALLY | reporting/generator.py:180 uses `subprocess.run()` (sync) — called from async context. Known audit finding. |
docs/handoffs-archive/2026-04/DOC_REALITY_MAP.md:394:### .claude/hooks/inject_context.py
docs/handoffs-archive/2026-04/DOC_REALITY_MAP.md:396:Branch-aware context injection hook. Checks `git branch --show-current` and injects context accordingly. No claims about specific modules — this is infrastructure.
docs/handoffs-archive/2026-04/ui-superseded/PHASE_UI1_V2_WIREFRAME.md:1:> **SUPERSEDED.** Replaced by `docs/phase-ui-1/phase_ui_v2_roadmap.md`. Retained for historical context.
docs/handoffs-archive/2026-04/ui-superseded/DESIGN_SYSTEM.md:1:> **SUPERSEDED.** This document (v0.3) is replaced by `docs/design-system/README.md` (v1.0.1). Retained for historical context.
docs/handoffs-archive/2026-04/ui-superseded/DESIGN_SYSTEM.md:1147:что можно drag — можно также сделать через меню или context action.
docs/handoffs-archive/2026-04/ui-superseded/DESIGN_SYSTEM.md:1251:3. **Text content** — value text в fault всегда читаем в context
docs/handoffs-archive/2026-04/ui-superseded/DESIGN_SYSTEM.md:1330:- ❌ **Никаких right-click context menus с уникальными командами** (всё в
docs/handoffs-archive/2026-04/ui-superseded/DESIGN_SYSTEM.md:1331:  context menu должно быть доступно и через primary UI).
docs/handoffs-archive/2026-04/ui-superseded/DESIGN_SYSTEM.md:1494:Почему не 4: 4 ступени недостаточно для different contexts (display vs
docs/handoffs-archive/2026-04/ui-superseded/UI_REWORK_ROADMAP.md:1:> **SUPERSEDED.** Replaced by `docs/phase-ui-1/phase_ui_v2_roadmap.md`. Retained for historical context.
docs/handoffs-archive/2026-04/HANDOFF_2026-04-20_GLM.md:13:This handoff exists because the running-context of the human-AI pair
docs/handoffs-archive/2026-04/HANDOFF_2026-04-20_GLM.md:393:## 5. Multi-model stack context — CRITICAL
docs/handoffs-archive/2026-04/HANDOFF_2026-04-20_GLM.md:419:  long context (1 M window).
docs/handoffs-archive/2026-04/HANDOFF_2026-04-20_GLM.md:664:## Appendix B — Vladimir's memory slots (for context)
docs/ORCHESTRATION.md:35:- `SESSION_DETAIL_2026-04-20.md` (93 KB architect context dump)
docs/ORCHESTRATION.md:96:- Required context files (list of paths — consultant reads these)
docs/ORCHESTRATION.md:478:5. **Lost context.** `SESSION_DETAIL_2026-04-20.md` (93 KB
docs/ORCHESTRATION.md:479:   architect context dump) lived untracked for three days,
docs/ORCHESTRATION.md:602:- Include additional context in session ledger beyond what plan
docs/ORCHESTRATION.md:670:- **Gemini** (`gemini-3.1-pro-preview`): wide-context audit, finds
docs/ORCHESTRATION.md:672:  context lets it read related files Codex would skip. Verbose
docs/ORCHESTRATION.md:740:context. Side-effect: `git log --oneline` may omit merge commits
docs/ORCHESTRATION.md:759:This is rtk's design choice for context economy. Don't fight it
docs/ORCHESTRATION.md:799:CCR `localhost:3456` requires Claude Code OAuth context to route
docs/changelog/archive/RETRO_ANALYSIS_V2.md:12:This file is the second-pass research document for the changelog rebuild. It supersedes `docs/changelog/RETRO_ANALYSIS.md` as the primary source material because it uses a finer version density and no longer treats the experimental `v0.12.0` tag as a hard anchor. The v1 document still matters: it contains useful prose, cluster context, and a coarser narrative that can still help a human writer decide where to compress or expand the final `CHANGELOG.md`.
docs/changelog/archive/RETRO_ANALYSIS_V2.md:43:- some “Add files via upload” commits have minimal message signal; where necessary I infer intent from neighboring commits and file-level context
docs/changelog/archive/RETRO_ANALYSIS_V2.md:1539:**Approach:** clean incidental debt, fix the late ordering/state gaps, complete fail-closed config work, declare 2d complete, then begin archive stage 1 and preserve the audit context around it.
docs/changelog/archive/RETRO_ANALYSIS_V2.md:1940:- **Clustering accuracy:** MEDIUM — the clusters are coherent and evidence-based, but some “upload snapshot” commits still require contextual inference.
docs/changelog/archive/RETRO_ANALYSIS_V2.md:1945:- **Context explanations:** HIGH — the why/how narratives are grounded in actual commit sequences and in the v1/archaeology context.
docs/changelog/archive/RETRO_ANALYSIS.md:14:The future `CHANGELOG.md` should be assembled from this document, not copied verbatim. Each section below groups commits into a **semantic cluster**: a coherent direction of work such as “GPIB recovery marathon” or “Calibration v2 rollout”. In the polished changelog, one cluster may collapse to one short bullet. Here it gets full context, file anchors, and a one-line explanation for every participating commit.
docs/changelog/archive/RETRO_ANALYSIS.md:28:For small, self-describing commits, I relied on subject line plus `--stat`. For large commits, merge commits, safety-critical commits, or commits with generic titles, I inspected the full commit message and diff/stat. In practice this means I read full context for the major foundation drops (`603a472`, `9217489`, `dc2ea6a`, `445c056`) and merge commits, and lighter context for obviously narrow doc or chore commits.
docs/changelog/archive/RETRO_ANALYSIS.md:37:- I did not inspect every large diff line by line. Some architectural intent inferences are still “inferred from context”.
docs/changelog/archive/RETRO_ANALYSIS.md:1196:- `1b12b87`: hardened alarm config and bridged safety faults into experiment/operator context
docs/changelog/RETRO_ANALYSIS_V3.md:15:This is still a research artifact, not a polished changelog. It intentionally preserves context a final `CHANGELOG.md` would compress away: merge commits as historical events, upload/task snapshots, audit-document waves, reality-map work, and release arcs that make sense only when seen in sequence. The later human-written changelog should distill from this file, not copy it verbatim.
docs/changelog/RETRO_ANALYSIS_V3.md:31:Known limitations remain the same as v2: this is still a first-parent narrative rather than a full branch archaeology of every side-branch commit, and some `Add files via upload` commits still require contextual inference from neighboring commits and file stats. But the boundary decisions themselves are mechanically checked against the full 205-commit first-parent chain, with no missing or overlapping assignments.
docs/changelog/RETRO_ANALYSIS_V3.md:79:| `0.33.0-pre` | Phase 2e Archive Kickoff and Round-2 Audit Context | 2026-04-14 02:55..2026-04-14 04:19 | 8 | `445c056` | `5b3ca29` | Phase 2e Parquet kickoff plus round-2 audit context define the current unreleased line. | v2 0.25.0 split 2/2 |
docs/changelog/RETRO_ANALYSIS_V3.md:1083:Remote ops landed first; alarm v2 then built on the richer operational context.
docs/changelog/RETRO_ANALYSIS_V3.md:2143:It had to land before the archive line and round-2 context could reasonably be described as the next chapter.
docs/changelog/RETRO_ANALYSIS_V3.md:2159:Split from v2 0.25.0. Once `445c056` lands, the story has changed: this is now the first Phase 2e archive release, plus the docs/audit context that explains the current unreleased state.
docs/changelog/RETRO_ANALYSIS_V3.md:2182:**Goal:** Open the archive line while preserving the exact audit and repository context around it.  
docs/changelog/RETRO_ANALYSIS_V3.md:2183:**Approach:** Start with the Parquet-at-finalize archive change, then add the branch/repo/audit reference documents and status updates that contextualize the new state.
docs/changelog/RETRO_ANALYSIS_V3.md:2194:Archive output expands again via Parquet; otherwise this is mostly maintainership-facing context.
docs/changelog/RETRO_ANALYSIS_V3.md:2602:- **Clustering accuracy:** MEDIUM — the major splits are strongly justified, but some upload/task snapshots still require contextual inference.
docs/audits/2026-04-17/stale_data_investigation.md:67:- External context: SQLite documents that checkpoints initiated by `sqlite3_wal_checkpoint()` are PASSIVE checkpoints. Source: https://sqlite.org/wal.html
docs/audits/2026-04-17/stale_data_investigation.md:68:- External context: the repo itself now warns that SQLite versions before 3.51.3 are affected by a March 2026 WAL bug when multiple connections across threads/processes write or checkpoint "at the same instant". See `src/cryodaq/storage/sqlite_writer.py:97-119`.
docs/audits/2026-04-17/stale_data_investigation.md:88:- External context: PyVISA documents that resource I/O operations obey `timeout`, and when an operation exceeds it an exception is raised. Source: https://pyvisa.readthedocs.io/en/1.8/resources.html and https://pyvisa.readthedocs.io/en/1.15.0/introduction/communication.html
docs/audits/2026-04-17/stale_data_investigation.md:113:- External context: the repo does not set explicit HWM values on the engine PUB or bridge SUB sockets. See `src/cryodaq/core/zmq_bridge.py:143-153` and `src/cryodaq/core/zmq_subprocess.py:72-77`.
docs/audits/2026-04-17/stale_data_investigation.md:114:- External context: ZeroMQ documents default SNDHWM/RCVHWM as 1000 messages, and for PUB/SUB sockets HWM overflow drops rather than blocks. Sources: https://api.zeromq.org/3-3:zmq-setsockopt and https://api.zeromq.org/2-2:zmq-socket
docs/audits/2026-04-21-agent-swarm/REPO_HARDENING_PLAN.md:233:| Item D unfocused instrumentation | Reduced from 5 counters to 2; removed context-ID, SUB-dropped, command-timeline; kept exit-code + restart-count |
docs/audits/2026-04-21-agent-swarm/REPO_HARDENING_MASTER_DOSSIER.md:39:- **Short rationale:** The ping bypasses the bridge's forwarding path and creates its own ZMQ context to ping the engine directly.
docs/audits/2026-04-21-agent-swarm/REVIEW_PLAN_GEMINI.md:110:| Context ID logging per REQ creation | Tests "context routing state" hypothesis but not stated |
docs/audits/2026-04-21-agent-swarm/REVIEW_PLAN_GEMINI.md:129:command timeline (redundant), per-REQ context ID (high overhead, unclear action)
docs/audits/2026-04-21-agent-swarm/ZERO_TRUST_AUDIT_2026-04-20.md:98:- Fresh context per REQ (not just fresh socket) resolves B1 → context routing state hypothesis confirmed
docs/audits/2026-04-21-agent-swarm/REVIEW_FINAL_CODEX.md:41:**Thread safety:** SAFE. `_check_engine_health()` runs on Qt's main thread (via `QTimer.timeout`). The `_last_cmd_watchdog_restart` attribute is only accessed in this single-threaded context. No synchronization primitives required.
docs/audits/2026-04-21-agent-swarm/GEMINI_READING_LEDGER.md:34:- `src/cryodaq/core/zmq_subprocess.py`: Checked ephemeral REQ creation, context sharing. Result: Ephemeral REQ implemented correctly, but `zmq.Context()` is shared globally inside the subprocess.
docs/audits/CODEX_ROUND_2_AUDIT.md:300:**Purpose:** provide phase and setpoint context to alarm engine v2.  
docs/audits/CODEX_ROUND_2_AUDIT.md:766:- **Git blame analysis:** `MEDIUM` — useful for context and missed-file detection, but intentionally shallow compared with the semantic code review.
docs/audits/CODEX_FULL_AUDIT.md:36:  - prompt context says `895`
docs/audits/DOCUMENTATION_AUDIT.md:191:- `docs/phase-ui-1/PHASE_UI1_V2_BLOCK_*.md` (5 files) — UI block specs. No incoming .md references. These are prompt specs for the UI rewrite, referenced from conversation context, not from other docs. Not truly orphan — they're process artifacts stored for reproducibility.
docs/audits/2026-04-09/VERIFICATION_PASS_HIGHS.md:13:2. Re-read the live code on `master` with at least 30 lines of context around the cited range.
docs/audits/2026-04-09/SAFETY_MANAGER_DEEP_DIVE.md:686:be called from any context ...
docs/audits/2026-04-09/DEEP_AUDIT_CODEX_POST_2C.md:106:**Impact:** A power cut, process kill, or disk hiccup during write can leave the JSON truncated or empty. That does not corrupt the main SQLite data, but it can orphan the active experiment, lose phase history, or break report/archive reconstruction right when operators need post-mortem context.
docs/audits/2026-04-09/DEEP_AUDIT_CODEX_POST_2C.md:391:**Impact:** A `/phase` or `/log` message sent during downtime can be executed later, after restart, when it is no longer contextually valid. In a safety-sensitive operator workflow, stale remote commands are worse than rejected ones.
docs/audits/2026-04-09/DEEP_AUDIT_CODEX_POST_2C.md:663:**Impact:** If the host process wedges or crashes while the source is active, the SMU can keep sourcing the last programmed voltage indefinitely until a restart path or human intervention reaches it. In a cryogenic heater/control context, that is a real hardware-risk failure mode, not just a software neatness issue.
docs/audits/2026-04-09/DEEP_AUDIT_CC.md:7:> **Note on sources:** Some `PROJECT_STATUS.md` and `.claude/rules/safety.md` files referenced in the task brief do not exist in the repository — context was reconstructed from `CLAUDE.md`, `CHANGELOG.md` 0.13.0 (`unreleased`, 0.13.0, 0.12.0…0.1.0), `RELEASE_CHECKLIST.md`, `docs/architecture.md`, `docs/deployment.md`, `graphify-out/GRAPH_REPORT.md` and direct source reading.
docs/audits/2026-04-09/DEEP_AUDIT_CC.md:92:**Recommendation.** `self._pending_publishes: set[asyncio.Task] = set()` in `__init__`; `t = asyncio.get_running_loop().create_task(...); self._pending_publishes.add(t); t.add_done_callback(self._pending_publishes.discard)`. Alternative: refactor `_transition` to be `async` and `await self._publish_state(reason)` directly — most callers (`_fault`, `_safe_off`, `request_run`, `acknowledge_fault`, `_run_checks`) are already in async context.
docs/audits/2026-04-09/DEEP_AUDIT_CC.md:676:**Verdict.** **MEDIUM in label, actually a sensible choice.** The polling approach is more robust than `watchdog` for the lab PC context. Document the 5 s latency in `docs/plugins.md` (if any).
docs/audits/2026-04-09/DEEP_AUDIT_CC_POST_2C.md:144:**synchronously** from inside an async context handler. `ReportGenerator.generate`
docs/audits/2026-04-09/DEEP_AUDIT_CC_POST_2C.md:175:sync SQLite + JSON disk writes from async context.
docs/audits/2026-04-09/DEEP_AUDIT_CC_POST_2C.md:603:#### E.2 [MEDIUM] ReportGenerator runs synchronously in async context
docs/audits/2026-04-09/DEEP_AUDIT_CC_POST_2C.md:612:called from the engine command handler — an async context.
docs/audits/2026-04-09/DEEP_AUDIT_CC_POST_2C.md:784:contains `<script>`, it's executed in the browser's context. Not a
docs/audits/2026-04-09/DEEP_AUDIT_CC_POST_2C.md:851:the `lifespan` async context manager pattern.
docs/audits/2026-04-09/DEEP_AUDIT_CC_POST_2C.md:1059:`_fault` is called from multiple contexts (overflow callback, _run_checks,
docs/audits/2026-04-09/DEEP_AUDIT_CC_POST_2C.md:1146:3. **Synchronous I/O in async context** is a recurring pattern: 
docs/cc-prompts-archive/2026-04/CC_PROMPT_VAULT_AUDIT_2026-04-27.md:20:  for context on what was built and what was deferred.
docs/cc-prompts-archive/2026-04/CC_PROMPT_VAULT_AUDIT_2026-04-27.md:165:Read all 49 notes under ~/Vault/CryoDAQ/ in 1M-context single pass.
docs/cc-prompts-archive/2026-04/CC_PROMPT_VAULT_AUDIT_2026-04-27.md:166:Skim repo source tree at ~/Projects/cryodaq/ for context. Find
docs/cc-prompts-archive/2026-04/CC_PROMPT_VAULT_AUDIT_2026-04-27.md:179:## Repo for context
docs/cc-prompts-archive/2026-04/CC_PROMPT_VAULT_BUILD_2026-04-26.md:413:- **Gemini (3.1-pro-preview)** — wide-context auditor. 1M context
docs/cc-prompts-archive/2026-04/CC_PROMPT_VAULT_BUILD_2026-04-26.md:480:# Vault audit — Phase N (Gemini wide-context auditor)
docs/cc-prompts-archive/2026-04/CC_PROMPT_VAULT_BUILD_2026-04-26.md:483:Read all vault notes from Phase N + skim repo source for context.
docs/cc-prompts-archive/2026-04/CC_PROMPT_VAULT_BUILD_2026-04-26.md:492:## Notes to read (use 1M context generously)
docs/cc-prompts-archive/2026-04/CC_PROMPT_VAULT_BUILD_2026-04-26.md:495:## Repo files for context
docs/cc-prompts-archive/2026-04/CC_PROMPT_VAULT_BUILD_2026-04-26.md:627:- Dark mode default (Vladimir's preference per design system context)
docs/cc-prompts-archive/2026-04/CC_PROMPT_OVERNIGHT_SWARM_2026-04-24.md:30:│   ├── codex-02-shared-context.prompt.md
docs/cc-prompts-archive/2026-04/CC_PROMPT_OVERNIGHT_SWARM_2026-04-24.md:75:Wide audit using 1M context window — find patterns that silently broke,
docs/cc-prompts-archive/2026-04/CC_PROMPT_OVERNIGHT_SWARM_2026-04-24.md:253:> Ephemeral sockets did not eliminate that shared-context surface."
docs/cc-prompts-archive/2026-04/CC_PROMPT_OVERNIGHT_SWARM_2026-04-24.md:276:   Context (expensive) vs separate SUB and REQ contexts (cheap) vs
docs/cc-prompts-archive/2026-04/CC_PROMPT_OVERNIGHT_SWARM_2026-04-24.md:391:**Context files (use 1M context generously):**
docs/cc-prompts-archive/2026-04/CC_PROMPT_OVERNIGHT_SWARM_2026-04-24.md:404:3. Considering future B1 work (H4 shared-context, H5 engine REP
docs/cc-prompts-archive/2026-04/CC_PROMPT_OVERNIGHT_SWARM_2026-04-24.md:426:**Context scope:** `src/cryodaq/` entire tree. Gemini 1M context —
docs/cc-prompts-archive/2026-04/CC_PROMPT_OVERNIGHT_SWARM_2026-04-24.md:600:     - Codex-02 shared-context hypothesis verdict
docs/cc-prompts-archive/2026-04/CC_PROMPT_OVERNIGHT_SWARM_2026-04-24.md:692:      session context
docs/cc-prompts-archive/2026-04/CC_PROMPT_IV_6_ZMQ_BRIDGE_FIX.md:116:            req = _new_req_socket()  # recreate on same context
docs/cc-prompts-archive/2026-04/CC_PROMPT_IV_6_ZMQ_BRIDGE_FIX.md:144:            with contextlib.suppress(queue.Full):

exec
/opt/homebrew/bin/bash -lc "grep -R \"not smoke\\|pytest\" -n .github pyproject.toml Makefile tox.ini setup.cfg 2>/dev/null | head -80" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
.github/workflows/main.yml:26:        run: pytest tests/ -x --tb=short -q
pyproject.toml:51:    "pytest>=8",
pyproject.toml:52:    "pytest-asyncio>=0.23",
pyproject.toml:53:    "pytest-cov>=4",
pyproject.toml:54:    "pytest-timeout>=2.0",
pyproject.toml:83:[tool.pytest.ini_options]

exec
/opt/homebrew/bin/bash -lc "sed -n '1,60p' .github/workflows/main.yml" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
name: CryoDAQ CI

on:
  push:
    branches: [master]
  pull_request:
    branches: [master]

jobs:
  test:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.14"

      - name: Install dependencies
        run: pip install -e ".[dev,web]"

      - name: Lint
        run: ruff check src/ tests/

      - name: Run tests
        run: pytest tests/ -x --tb=short -q

codex
The patch adds a live external-service smoke test that is still run by the repository's default pytest/CI command, which will break environments without Ollama. This is a blocking regression for the test suite.

Review comment:

- [P1] Exclude the live Ollama smoke test from default pytest — /Users/vladimir/Projects/cryodaq/tests/agents/test_ollama_client.py:243-244
  `@pytest.mark.smoke` only labels this test; it does not skip it by default. The existing CI runs `pytest tests/ -x --tb=short -q`, so this new test will execute on runners without Ollama installed and fail at `subprocess.run(["ollama", "list"], ...)` before it can skip. Add a default `-m "not smoke"`/CI filter or skip when the Ollama executable is unavailable.
The patch adds a live external-service smoke test that is still run by the repository's default pytest/CI command, which will break environments without Ollama. This is a blocking regression for the test suite.

Review comment:

- [P1] Exclude the live Ollama smoke test from default pytest — /Users/vladimir/Projects/cryodaq/tests/agents/test_ollama_client.py:243-244
  `@pytest.mark.smoke` only labels this test; it does not skip it by default. The existing CI runs `pytest tests/ -x --tb=short -q`, so this new test will execute on runners without Ollama installed and fail at `subprocess.run(["ollama", "list"], ...)` before it can skip. Add a default `-m "not smoke"`/CI filter or skip when the Ollama executable is unavailable.
